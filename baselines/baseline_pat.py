from __future__ import print_function
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import os
import glob
import sys
from scipy.ndimage import gaussian_filter
import warnings
import numpy as np
from utils.denoising_utils import *
from models import *
from utils.quant import *
from utils.imp import *
from models.cnn import cnn
import torch
import torch.optim
import time
from PIL import Image
import pickle as cPickle
import argparse
from torch.nn.utils import parameters_to_vector, vector_to_parameters
from skimage.metrics import peak_signal_noise_ratio as compare_psnr
from utils.inpainting_utils import *
import yaml
warnings.filterwarnings("ignore")
torch.backends.cudnn.enabled = True
torch.backends.cudnn.benchmark =True
dtype = torch.cuda.FloatTensor

def main(lr: float, max_steps: int, reg: float = 0.0, sigma: float = 0.2,
         num_layers: int = 4, show_every: int = 1000, device_id: int = 0, beta: float = 0.0,
         image_name: str = 'baboon', weight_decay: float = 0.0, prune_iters: int = 0, percent: float = 0.0, num_epoch: int = 40000):

    torch.cuda.set_device(device_id)
    torch.cuda.current_device()

    img_np, img_noisy_np, noisy_psnr = load_image('images', image_name, sigma)
    print(f"Starting IMP on DIP with ADAM(sigma={sigma}, lr={lr}, decay={weight_decay}, beta={beta}) on image {image_name}")
    print(f"Noisy PSNR: {noisy_psnr}")

    input_depth = 32
    output_depth = 3

    mse = torch.nn.MSELoss().type(dtype)
    INPUT = "noise"

    net_input = get_noise(input_depth, INPUT, img_np.shape[1:]).type(dtype)
    net = skip(
        input_depth, output_depth,
        num_channels_down=[16, 32, 64, 128, 128, 128][:num_layers],
        num_channels_up=[16, 32, 64, 128, 128, 128][:num_layers],
        num_channels_skip=[0] * num_layers,
        upsample_mode='nearest',
        downsample_mode='avg',
        need1x1_up=False,
        filter_size_down=5,
        filter_size_up=3,
        filter_skip_size=1,
        need_sigmoid=True,
        need_bias=True,
        pad='reflection',
        act_fun='LeakyReLU'
    ).type(dtype)

    optimizer = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=weight_decay)

    outdir = f'sparse_models_imp/{image_name}'
    print(f"Output directory: {outdir}")
    os.makedirs(f'{outdir}', exist_ok=True)

    model, mask, psnr_history = iterative_pruning(
        net, net_input, img_np, img_noisy_np, percent, prune_iters, num_epoch, device=device_id)
    torch.cuda.empty_cache()
    print("Experiment done")

    def save_and_plot_psnr(psnr_history, outdir, prune_iters):
        for i, psnr_list in enumerate(psnr_history):
            npz_filename = os.path.join(outdir, f'psnr_data_iter_{i+1}.npz')
            np.savez(npz_filename, psnr=np.array(psnr_list))

            plt.figure()
            plt.plot(psnr_list, label=f'Iteration {i+1}')
            plt.xlabel('Training Steps')
            plt.ylabel('PSNR')
            plt.title(f'PSNR Curve for Pruning Iteration {i+1}')
            plt.legend()
            plt.grid(True)
            plt.savefig(os.path.join(outdir, f'psnr_curve_iter_{i+1}.png'))
            plt.close()

        if prune_iters > 0:
            torch.save(model.state_dict(), os.path.join(outdir, 'model_final.pth'))
            torch.save(mask, os.path.join(outdir, 'mask_final.pth'))
            torch.save(net_input, os.path.join(outdir, 'net_input_final.pth'))

    save_and_plot_psnr(psnr_history, outdir, prune_iters)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Image denoising using DIP")

    image_choices = [
        'baboon', 'barbara', 'lena', 'pepper'
    ]

    parser.add_argument("--lr", type=float, help="the learning rate")
    parser.add_argument("--max_steps", type=int, help="the maximum number of gradient steps to train for")
    parser.add_argument("--reg", type=float, help="regularization strength of igr")
    parser.add_argument("--sigma", type=float, help="noise-level")
    parser.add_argument("--num_layers", type=int, help="number of layers")
    parser.add_argument("--show_every", type=int, help="show every n steps")
    parser.add_argument("--device_id", type=int, help="specify which gpu")
    parser.add_argument("--beta", type=float, help="momentum for sgd")
    parser.add_argument("--decay", type=float, help="weight decay")
    parser.add_argument("--image_name", type=str, choices=image_choices, help="name of image to denoise")
    parser.add_argument("--prune_iters", type=int, help="number of pruning iterations")
    parser.add_argument("--percent", type=float, help="percentage of pruning")
    parser.add_argument("--num_epoch", type=int, help="number of iterations for each pruning iteration")
    parser.add_argument("-f", "--file", type=str, default='configs/config_baseline_pat_sparse.yaml', help="YAML configuration file, options passed on the command line override these")

    args = parser.parse_args()

    default_config = {
        'lr': 1e-2,
        'max_steps': 100000,
        'reg': 0.05,
        'sigma': 0.1,
        'num_layers': 6,
        'show_every': 200,
        'device_id': 0,
        'beta': 0,
        'decay': 0,
        'image_name': 'pepper',
        'prune_iters': 14,
        'percent': 0.2,
        'num_epoch': 40000
    }

    config = set_config(args, default_config)

    main(
        lr=config.get('lr', default_config['lr']),
        max_steps=config.get('max_steps', default_config['max_steps']),
        reg=config.get('reg', default_config['reg']),
        sigma=config.get('sigma', default_config['sigma']),
        num_layers=config.get('num_layers', default_config['num_layers']),
        show_every=config.get('show_every', default_config['show_every']),
        beta=config.get('beta', default_config['beta']),
        device_id=config.get('device_id', default_config['device_id']),
        image_name=config.get('image_name', default_config['image_name']),
        weight_decay=config.get('decay', default_config['decay']),
        prune_iters=config.get('prune_iters', default_config['prune_iters']),
        percent=config.get('percent', default_config['percent']),
        num_epoch=config.get('num_epoch', default_config['num_epoch'])
    )
