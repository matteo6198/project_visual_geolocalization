
import faiss
import torch
import logging
import numpy as np
from tqdm import tqdm
from os.path import join
from torch.utils.data import DataLoader
from torch.utils.data.dataset import Subset
from Utils.constants import FEATURES_DIM
from Visualize import viewNets
from Utils import constants
import time


def test(args, eval_ds, model):
    """Compute features of the given dataset and compute the recalls."""
    model = model.eval()
    with torch.no_grad():
        logging.debug("Extracting database features for evaluation/testing")
        # For database use "hard_resize", although it usually has no effect because database images have same resolution
        database_subset_ds = Subset(eval_ds, list(range(eval_ds.database_num)))
        database_dataloader = DataLoader(dataset=database_subset_ds, num_workers=args.num_workers,
                                        batch_size=args.infer_batch_size, pin_memory=(args.device=="cuda"))
        t1 = time.time()
        all_features = np.empty((len(eval_ds), FEATURES_DIM[args.net]), dtype="float32")
        for inputs, indices in tqdm(database_dataloader, ncols=100):
            features = model(inputs.to(args.device))
            features = features.cpu().numpy()
            all_features[indices.numpy(), :] = features
        t2 = time.time()
        logging.debug("Extracting queries features for evaluation/testing")
        queries_subset_ds = Subset(eval_ds, list(range(eval_ds.database_num, eval_ds.database_num+eval_ds.queries_num)))
        queries_dataloader = DataLoader(dataset=queries_subset_ds, num_workers=args.num_workers,
                                        batch_size=args.infer_batch_size, pin_memory=(args.device=="cuda"))
        t3 = time.time()
        for inputs, indices in tqdm(queries_dataloader, ncols=100):
            features = model(inputs.to(args.device))
            features = features.cpu().numpy()
            all_features[indices.numpy(), :] = features
        tot = t2-t1 + time.time()-t3
    logging.debug(f"mean execution time per image: {tot/len(eval_ds):.5f}")
    queries_features = all_features[eval_ds.database_num:]
    database_features = all_features[:eval_ds.database_num]
    
    faiss_index = faiss.IndexFlatL2(FEATURES_DIM[args.net])
    faiss_index.add(database_features)
    del database_features, all_features
    
    logging.debug("Calculating recalls")
    distances, predictions = faiss_index.search(queries_features, max(args.recall_values))
    
    #### For each query, check if the predictions are correct
    positives_per_query = eval_ds.get_positives()
    # args.recall_values by default is [1, 5, 10, 20]
    recalls = np.zeros(len(args.recall_values))
    for query_index, pred in enumerate(predictions):
        for i, n in enumerate(args.recall_values):
            if np.any(np.in1d(pred[:n], positives_per_query[query_index])):
                recalls[i:] += 1
                break
    # Divide by the number of queries*100, so the recalls are in percentages
    recalls = recalls / eval_ds.queries_num * 100
    recalls_str = ", ".join([f"R@{val}: {rec:.1f}" for val, rec in zip(args.recall_values, recalls)])

    # visualize some results
    if eval_ds.dataset_split == 'test' and hasattr(args, 'visual') and args.visual:
        logging.debug('Saving images')
        args.output_folder = join(constants.DRIVE_PATH, "runs", args.resume)
        # args = torch.load(join(args.output_folder, 'args.pth'))
        args.img_folder = join(args.output_folder, 'img', args.net)
        viewNets.view(args, eval_ds, predictions, model)

    return recalls, recalls_str

