import torch
import torch.nn.functional as F
import torch.backends.cudnn as cudnn

from torch.utils.data import DataLoader

from mean_teacher import losses, ramps
from utils.util import FocalLoss, PULoss
from models import MultiLayerPerceptron as Model
from models import CNN
from datasets import MNIST_Dataset_FixSample, get_mnist, binarize_mnist_class
from cifar_datasets import CIFAR_Dataset, get_cifar, binarize_cifar_class
from functions import *
from torchvision import transforms

import os
import time
import random
import argparse
import numpy as np
import shutil

from tqdm import tqdm

def boolean_string(s):
    if s not in {'False', 'True'}:
        raise ValueError('Not a valid boolean string')
    return s == 'True'

parser = argparse.ArgumentParser()
parser.add_argument('--seed', type=int, default=None)
parser.add_argument('--gpu', default=None, type=int, help='GPU id to use.')
parser.add_argument('-j', '--workers', default=4, type=int, help='workers')
parser.add_argument('--dataset', type=str, default="mnist")
parser.add_argument('--datapath', type=str, default="")
parser.add_argument('--model', type=str, default=None)


step = 0
results = np.zeros(61000)
switched = False
results1 = None
results2 = None
args = None

def main():

    global args, switched
    args = parser.parse_args()

    print(args)

    if args.seed is not None:
        random.seed(args.seed)
        torch.manual_seed(args.seed)
        cudnn.deterministic = True

    if args.dataset == "mnist":
        (trainX, trainY), (testX, testY) = get_mnist()
        _trainY, _testY = binarize_mnist_class(trainY, testY)

        dataset_test = MNIST_Dataset_FixSample(1000, 60000, 
            trainX, _trainY, testX, _testY, split='test', type="clean",
        seed = args.seed)

    elif args.dataset == 'cifar':
        data_transforms = {
            'train': transforms.Compose([
                transforms.ToPILImage(),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406],
                                     [0.229, 0.224, 0.225]),
            ]),
            'val': transforms.Compose([
                transforms.ToPILImage(),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406],
                                     [0.229, 0.224, 0.225]),
            ])
        } 
        
        (trainX, trainY), (testX, testY) = get_cifar()
        _trainY, _testY = binarize_cifar_class(trainY, testY)

        dataset_test = CIFAR_Dataset(1000, 50000, 
            trainX, _trainY, testX, _testY, split='test', transform = data_transforms['val'], type="clean",
        seed = args.seed)

    dataloader_test = DataLoader(dataset_test, batch_size=1, num_workers=args.workers, shuffle=False, pin_memory=True)
    consistency_criterion = losses.softmax_mse_loss
    if args.dataset == 'mnist':
        model = create_model()
    elif args.dataset == 'cifar':
        model = create_cifar_model()
    if args.gpu is not None:
        model = model.cuda()
    else:
        model = model.cuda()

    print("Evaluation mode!")
    
    if args.model is None:
        raise RuntimeError("Please specify a model file.")
    else:
        state_dict = torch.load(args.model)['state_dict']
        model.load_state_dict(state_dict)

    valPacc, valNacc, valPNacc = validate(dataloader_test, model)

def validate(val_loader, model):
    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()
    pacc = AverageMeter()
    nacc = AverageMeter()
    pnacc = AverageMeter()
    model.eval()
    end = time.time()
    
    with torch.no_grad():
        for i, (X, Y, _, T, ids, _) in enumerate(val_loader):
            # measure data loading time
            data_time.update(time.time() - end)

            X = X.cuda(args.gpu)
            if args.dataset == 'mnist':
                X = X.view(X.shape[0], 1, -1)
            Y = Y.cuda(args.gpu).float()
            T = T.cuda(args.gpu).long()

            # compute output
            output = model(X)
            prediction = torch.sign(output).long()
            
            pacc_, nacc_, pnacc_, psize = accuracy(prediction, T)
            pacc.update(pacc_, X.size(0))
            nacc.update(nacc_, X.size(0))
            pnacc.update(pnacc_, X.size(0))

    print('Test: \t'
                'PNACC {pnacc.val:.3f} ({pnacc.avg:.3f})\t'.format(
                pnacc=pnacc))
    print("=====================================")
    return pacc.avg, nacc.avg, pnacc.avg

def create_model():
    model = Model(28*28)
    return model

def create_cifar_model():
    model = CNN()
    return model

class AverageMeter(object):
    """Computes and stores the average and current value"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        #print(val, n)
        if self.count == 0:
            self.avg = 0
        else:
            self.avg = self.sum / self.count

def accuracy(output, target):
    with torch.no_grad():
        
        batch_size = float(target.size(0))
        
        output = output.view(-1)
        correct = torch.sum(output == target).float()
        
        pcorrect = torch.sum(output[target==1] == target[target == 1]).float()
        ncorrect = correct - pcorrect
    
    ptotal = torch.sum(target == 1).float()

    if ptotal == 0:
        return torch.tensor(0.).cuda(args.gpu), ncorrect / (batch_size - ptotal) * 100, correct / batch_size * 100, ptotal
    elif ptotal == batch_size:
        return pcorrect / ptotal * 100, torch.tensor(0.).cuda(args.gpu), correct / batch_size * 100, ptotal
    else:
        return pcorrect / ptotal * 100, ncorrect / (batch_size - ptotal) * 100, correct / batch_size * 100, ptotal

if __name__ == '__main__':
    main()