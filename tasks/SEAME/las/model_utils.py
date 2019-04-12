'''
Helper functions

To-do:
 - incrementally load data instead all at once
 - add conversation data to split

Character set/map and data loader code modified from LAS implementation by 
Sai Krishna Rallabandi (srallaba@andrew.cmu.edu)

Peter Wu
peterw1@andrew.cmu.edu
'''

import itertools
import os
import numpy as np
import torch

from nltk.metrics import edit_distance
from torch.utils.data import DataLoader, Dataset

def output_mask(maxlen, lengths):
    """
    Create a mask on-the-fly
    :param maxlen: length of mask
    :param lengths: length of each sequence
    :return: mask shaped (maxlen, len(lengths))
    """
    lens = lengths.unsqueeze(0)
    ran = torch.arange(0, maxlen, 1, out=lengths.new()).unsqueeze(1)
    mask = ran < lens
    return mask

def log_l(logits, target, lengths):
    '''Calculates the log-likelihood for the given batch

    Args:
        logits: shape (seq_len, batch_size, vocab_size)
        target: shape (seq_len, batch_size)
        lengths: shape (batch_size,)
    
    Return:
        log_probs: shape (batch_size,)
    '''
    seq_len, batch_size, vocab_size = logits.shape
    mask = output_mask(seq_len, lengths.data).float()
    logits_masked = logits * mask.unsqueeze(2)
    range_tens = torch.arange(vocab_size).repeat(seq_len, batch_size, 1)
    target_rep = target.repeat(vocab_size, 1, 1).permute(1, 2, 0)
    masked_tens = range_tens == target_rep
    all_probs = torch.sum(logits*masked_tens.float(), 2) # shape: (seq_len, batch_size)
    all_log_probs = torch.log(all_probs)
    log_probs = torch.sum(all_log_probs, 0) # shape: (batch_size,)
    return log_probs

def perplexity(logits, target, lengths):
    '''Calculates the perplexity for the given batch

    Args:
        logits: shape (seq_len, batch_size, vocab_size)
        target: shape (seq_len, batch_size)
        lengths: shape (batch_size,)
    
    Return:
        perp: float (tensor)
    '''
    log_probs = log_l(logits, target, lengths) # shape: (batch_size,)
    tot_log_l = torch.sum(log_probs)
    tot_len = torch.sum(lengths)
    return torch.exp(-tot_log_l/tot_len)

def generate_transcripts(args, model, loader, charset):
    '''Iteratively returns string transcriptions
    
    Return:
        generator object comprised of transcripts (each a string)
    '''
    # Create and yield transcripts
    for uarray, ulens, l1array, llens, l2array in loader:
        if args.cuda:
            uarray = uarray.cuda()
            ulens = ulens.cuda()
            l1array = l1array.cuda()
            llens = llens.cuda()
        uarray = Variable(uarray)
        ulens = Variable(ulens)
        l1array = Variable(l1array)
        llens = Variable(llens)

        logits, generated, lens = model(
            uarray, ulens, l1array, llens,
            future=args.generator_length)
        generated = generated.data.cpu().numpy()  # (L, BS)
        n = uarray.size(1)
        for i in range(n):
            transcript = decode_output(generated[:, i], charset)
            yield transcript

def cer(args, model, loader, charset, ys):
    '''Calculates the average normalized CER for the given data
    
    Args:
        ys: iterable of strings
    
    Return:
        number
    '''
    model.eval()
    norm_dists = []
    transcripts = generate_transcripts(args, model, loader, charset)
    for i, t in enumerate(transcripts):
        dist = edit_distance(t, ys[i])
        norm_dist = dist / len(ys[i])
        norm_dists.append(norm_dist)
    return sum(norm_dists)/len(ys)

def print_log(s, log_path):
    print(s)
    with open(log_path, 'a+') as ouf:
        ouf.write("%s\n" % s)

def build_charset(utterances):
    # Create a character set
    chars = set(itertools.chain.from_iterable(utterances))
    chars = list(chars)
    chars.sort()
    return chars

def make_charmap(charset):
    # Create the inverse character map
    return {c: i for i, c in enumerate(charset)}

def map_characters(utterances, charmap):
    # Convert transcripts to ints
    ints = [np.array([charmap[c] for c in u], np.int32) for u in utterances]
    return ints

def load_ids():
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    SPLIT_DIR = os.path.join(parent_dir, 'split')
    TRAIN_IDS_FILE = 'train_ids.txt'
    DEV_IDS_FILE = 'dev_ids.txt'
    TEST_IDS_FILE = 'test_ids.txt'
    train_ids_path = os.path.join(SPLIT_DIR, TRAIN_IDS_FILE)
    dev_ids_path = os.path.join(SPLIT_DIR, DEV_IDS_FILE)
    test_ids_path = os.path.join(SPLIT_DIR, TEST_IDS_FILE)
    with open(train_ids_path, 'r') as inf:
        train_ids = inf.readlines()
    train_ids = [f.strip() for f in train_ids]
    with open(dev_ids_path, 'r') as inf:
        dev_ids = inf.readlines()
    dev_ids = [f.strip() for f in dev_ids]
    with open(test_ids_path, 'r') as inf:
        test_ids = inf.readlines()
    test_ids = [f.strip() for f in test_ids]
    return train_ids, dev_ids, test_ids

def load_x_data(ids, INTERVIEW_MFCC_DIR=None, max_data=1000000000):
    '''Returns list comprised of shape(seq_len, num_feats) np arrays'''
    if INTERVIEW_MFCC_DIR is None:
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        INTERVIEW_MFCC_DIR = os.path.join(parent_dir, 'data/interview/mfcc')
    mfcc_paths = [os.path.join(INTERVIEW_MFCC_DIR, fid+'.mfcc') for fid in ids]
    mfccs = []
    indices = []
    for i, path in enumerate(mfcc_paths):
        if len(mfccs) >= max_data:
            break
        if os.path.exists(path):
            curr_mfcc = np.loadtxt(path) # shape: (seq_len, num_feats)
            if curr_mfcc.shape[0] > 0:
                mfccs.append(curr_mfcc)
                indices.append(i)
    return mfccs, indices

def load_y_data(indices, stage):
    '''
    Args:
        stage: train, dev, or test
    
    Return:
        1-dim np array of strings
    '''
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    SPLIT_DIR = os.path.join(parent_dir, 'split')
    FILE = '%s_ys.txt' % stage
    ys_path = os.path.join(SPLIT_DIR, FILE)
    with open(ys_path, 'r') as inf:
        ys = inf.readlines()
    ys = [f.strip() for f in ys]
    return np.array(ys)[indices]

class SpeechDataset(Dataset):
    '''Assumes all characters in transcripts are alphanumeric'''
    def __init__(self, features, transcripts):
        '''
        self.transcripts is only True for test set

        Args:
            features: list of shape(seq_len, num_feats) np arrays
            transcripts: list of 1-dim int np arrays
        '''
        self.features = [torch.from_numpy(x).float() for x in features]
        if transcripts:
            self.transcripts = [torch.from_numpy(y + 1).long() for y in transcripts]  # +1 for start/end token
            assert len(self.features) == len(self.transcripts)
        else:
            self.transcripts = None

    def __len__(self):
        return len(self.features)

    def __getitem__(self, item):
        '''Returns 2 Torch.tensor objects'''
        if self.transcripts:
            return self.features[item], self.transcripts[item]
        else:
            return self.features[item], None

INPUT_DIM = 39

def speech_collate_fn(batch):
    n = len(batch)

    # allocate tensors for lengths
    ulens = torch.IntTensor(n)
    llens = torch.IntTensor(n)

    # calculate lengths
    for i, (u, l) in enumerate(batch): # u is x-val, l is y-val
        # +1 to account for start/end token
        ulens[i] = u.size(0)
        if l is None:
            llens[i] = 1
        else:
            llens[i] = l.size(0) + 1

    # calculate max length
    umax = int(ulens.max())
    lmax = int(llens.max())

    # allocate tensors for data based on max length
    uarray = torch.FloatTensor(umax, n, INPUT_DIM).zero_()
    l1array = torch.LongTensor(lmax, n).zero_()
    l2array = torch.LongTensor(lmax, n).zero_()

    # collate data tensors into pre-allocated arrays
    for i, (u, l) in enumerate(batch):
        uarray[:u.size(0), i, :] = u
        if l is not None:
            l1array[1:l.size(0) + 1, i] = l
            l2array[:l.size(0), i] = l

    return uarray, ulens, l1array, llens, l2array

def make_loader(features, labels, args, shuffle=True, batch_size=64):
    '''
    Args:
        features: len-num_samples list
        labels: list of 1-dim int np arrays
    '''
    # Build the DataLoaders
    kwargs = {'pin_memory': True, 'num_workers': args.num_workers} if args.cuda else {}
    dataset = SpeechDataset(features, labels)
    loader = DataLoader(dataset, collate_fn=speech_collate_fn, shuffle=shuffle, batch_size=batch_size, **kwargs)
    return loader