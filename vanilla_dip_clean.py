from __future__ import print_function
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import os
import glob
import sys
from scipy.ndimage import gaussian_filter
import warnings
warnings.filterwarnings("ignore")
import numpy as np
from utils.denoising_utils import *
from utils.sharpness import *
from models import *
from quant import *
from ptflops import get_model_complexity_info
from models.cnn import cnn
import torch
import torch.optim
import time
from PIL import Image
from utils.inpainting_utils import *
import pickle as cPickle
torch.backends.cudnn.enabled = True
torch.backends.cudnn.benchmark = True
dtype = torch.cuda.FloatTensor
from torch.nn.utils import parameters_to_vector, vector_to_parameters
from sam import SAM
from skimage.metrics import peak_signal_noise_ratio as compare_psnr

import argparse

def load_image(train_folder, image_name, sigma):
    train_noisy_folder = f'{train_folder}/train_noisy_{sigma}'
    os.makedirs(train_noisy_folder, exist_ok=True)
    file_path = os.path.join(train_folder, f'{image_name}.png')
    filename = os.path.splitext(os.path.basename(file_path))[0]
    img_pil = Image.open(file_path)
    img_pil = resize_and_crop(img_pil, max(img_pil.size))
    img_np = pil_to_np(img_pil)
    img_noisy_np = np.clip(img_np + np.random.normal(scale=sigma, size=img_np.shape), 0, 1).astype(np.float32)
    img_noisy_pil = np_to_pil(img_noisy_np)
    img_noisy_pil.save(os.path.join(train_noisy_folder, filename + '.png'))
    noisy_psnr = compare_psnr(img_np, img_noisy_np)
    return img_np, img_noisy_np, noisy_psnr

def main(lr: float, max_steps: int, optim: str, reg: float = 0.0, sigma: float = 0.1, num_layers: int = 6, 
         show_every: int = 1000, device_id: int = 0, beta: float = 0.0, image_name: str = 'pepper', 
         weight_decay: float = 0.0):

    torch.cuda.set_device(device_id)
    torch.cuda.current_device()

    train_folder = 'data/denoising/Set14'
    img_np, img_noisy_np, noisy_psnr = load_image(train_folder, image_name, sigma)
    print("noisy psnr:", noisy_psnr)
    print(f'Starting vanilla DIP on {image_name} using {optim}(sigma={sigma}, lr={lr}, decay={weight_decay}, beta={beta})')
    print(f"Noisy PSNR is '{noisy_psnr}'")

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

    if optim == "SGD":
        optimizer = torch.optim.SGD(net.parameters(), lr=lr, weight_decay=weight_decay, momentum=beta)
    elif optim == "ADAM":
        optimizer = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=weight_decay)
    elif optim == "SAM":
        base_opt = torch.optim.SGD
        optimizer = SAM(net.parameters(), base_opt, rho=reg, adaptive=False, lr=lr, weight_decay=weight_decay, momentum=beta)

    def closure_sgd(net_input, img_var, noise_var):
        optimizer.zero_grad()
        img_var = np_to_torch(img_var).type(dtype)
        noise_var = np_to_torch(noise_var).type(dtype)
        out = net(net_input)
        total_loss = mse(out, noise_var)
        total_loss.backward()
        optimizer.step()
        out_np = out.detach().cpu().numpy()
        img_np = img_var.detach().cpu().numpy()
        psnr_gt = compare_psnr(img_np, out_np)
        return psnr_gt, out_np

    fileid = f'{optim}(sigma={sigma}, lr={lr}, decay={weight_decay}, beta={beta}, reg={reg})'
    outdir = f'data/denoising/Set14/mask/{image_name}/vanilla/{sigma}'
    os.makedirs(f'{outdir}', exist_ok=True)

    psnr_list = []
    for j in range(max_steps):
        psnr, out = closure_sgd(net_input, img_np, img_noisy_np)
        if j % show_every == 0 and j != 0:
            print(f"At step '{j}', psnr is '{psnr}'")
            psnr_list.append(psnr)

    plt.plot(psnr_list)
    plt.savefig(f'{outdir}/psnr_{image_name}.png')
    plt.close()
    np.savez(f'{outdir}/psnr_{image_name}.npz', psnr=psnr_list)

    torch.cuda.empty_cache()
    print("Experiment done")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Image denoising using DIP")

    image_choices = [
        'pepper', 'foreman', 'flowers', 'comic', 'lena', 'barbara', 'monarch', 
        'baboon', 'ppt3', 'coastguard', 'bridge', 'zebra', 'face', 'man'
    ]

    parser.add_argument("--lr", type=float, default=1e-3, help="the learning rate")
    parser.add_argument("--max_steps", type=int, default=40000, help="the maximum number of gradient steps to train for")
    parser.add_argument("--optim", type=str, default="ADAM", help="which optimizer")
    parser.add_argument("--reg", type=float, default=0.05, help="if regularization strength of igr")
    parser.add_argument("--sigma", type=float, default=0.1, help="noise-level")
    parser.add_argument("--num_layers", type=int, default=6, help="number of layers")
    parser.add_argument("--show_every", type=int, default=100, help="show every n steps")
    parser.add_argument("--device_id", type=int, default=1, help="specify which gpu")
    parser.add_argument("--beta", type=float, default=0, help="momentum for sgd")
    parser.add_argument("--decay", type=float, default=0, help="weight decay")
    parser.add_argument("--image_name", type=str, choices=image_choices, default="pepper", help="name of image to denoise")

    args = parser.parse_args()

    main(lr=args.lr, max_steps=args.max_steps, optim=args.optim, reg=args.reg, sigma=args.sigma,
         num_layers=args.num_layers, show_every=args.show_every, beta=args.beta, device_id=args.device_id,
         image_name=args.image_name, weight_decay=args.decay)