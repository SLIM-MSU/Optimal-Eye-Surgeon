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
from models import *
from utils.quant import *
from utils.imp import *
from models.cnn import cnn
import torch
import torch.optim
from PIL import Image
import time
#from skimage.measure import compare_psnr
from utils.inpainting_utils import * 
import pickle as cPickle
torch.backends.cudnn.enabled = True
torch.backends.cudnn.benchmark =True
dtype = torch.cuda.FloatTensor
from torch.nn.utils import parameters_to_vector, vector_to_parameters
from skimage.metrics import peak_signal_noise_ratio as compare_psnr
from sam import SAM

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

def main(images: list, lr: float, max_steps: int, optim: str, reg: float = 0.0, sigma: float = 0.1,
          num_layers: int = 4, show_every: int=1000, device_id: int = 0, beta: float = 0.0,
          image_name: str = "baboon", trans_type: str="pai", weight_decay: float = 0.0, transferimage_name: str = "barbara",
          mask_opt: str = "single", noise_steps: int = 80000, kl: float = 1e-5, prior_sigma: float = 0.0, sparsity: float = 0.05):

    torch.cuda.set_device(device_id)
    torch.cuda.current_device()

    train_folder = 'images'
    img_np, img_noisy_np, noisy_psnr = load_image(train_folder, image_name, sigma)
    print(f"Noisy PSNR is '{noisy_psnr}'")

    print(f"Performing mask transfer operation for {image_name} using {transferimage_name}'s mask with sparsity {sparsity}")
    input_depth = 32
    output_depth = 3
    num_steps = noise_steps

    mse = torch.nn.MSELoss().type(dtype)

    INPUT = "noise"

    net_input_list = get_noise(input_depth, INPUT, img_np.shape[1:]).type(dtype)
    masked_model = skip(
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
        act_fun='LeakyReLU').type(dtype)

    if trans_type == "pai":
        outdir = f'sparse_models/{transferimage_name}'
        print(f"Output directory: {outdir}")
        os.makedirs(f'{outdir}/trans_{transferimage_name}_sparsenet_set14/{sigma}', exist_ok=True)
        with open(f'{outdir}/net_input_list_{transferimage_name}.pkl', 'rb') as f:
            net_input_list = cPickle.load(f)
        with open(f'{outdir}/mask_{transferimage_name}.pkl', 'rb') as f:
            mask = cPickle.load(f)


    elif trans_type == "pat":
        outdir = f'sparse_models_imp/{transferimage_name}'
        print(f"Output directory: {outdir}")
        os.makedirs(f'{outdir}/trans_{transferimage_name}_sparsenet_set14/{sigma}', exist_ok=True)
        model_path = f'{outdir}/model_final.pth'
        net_input_list = torch.load(f'{outdir}/net_input_final.pth')
        mask = torch.load(f'{outdir}/mask_final.pth')

    masked_model = mask_network(mask, masked_model)

    psnr, out = train_sparse(masked_model, net_input_list, mask, img_np, img_noisy_np, max_step=max_steps, show_every=show_every, device=device_id)

    with torch.no_grad():
        out_np = out
        img_var = np_to_torch(img_np)
        img_np = img_var.detach().cpu().numpy()
        psnr_gt = compare_psnr(img_np, out_np)
        print("PSNR of output image is: ", psnr_gt)
        np.savez(f'{outdir}/trans_{transferimage_name}_sparsenet_set14/{sigma}/psnr_{image_name}.npz', psnr=psnr)

        output_paths = [
            f"{outdir}/trans_{image_name}_sparsenet_set14/{sigma}/out_{image_name}.png",
            f"{outdir}/trans_{image_name}_sparsenet_set14/{sigma}/img_np_{image_name}.png",
            f"{outdir}/trans_{image_name}_sparsenet_set14/{sigma}/img_noisy_np_{image_name}.png"]

        print(out_np.shape, img_np.shape, img_noisy_np.shape)
        images_to_save = [out_np[0, :, :, :].transpose(1, 2, 0), img_np[0, :, :, :].transpose(1, 2, 0), img_noisy_np.transpose(1, 2, 0)]
        for path, img in zip(output_paths, images_to_save):
            plt.imshow(img)
            plt.axis('off')
            plt.savefig(path, bbox_inches='tight', pad_inches=0)
            plt.close()
            plt.plot(psnr)
            plt.title(f'PSNR vs Iterations')
            plt.xlabel('Iterations')
            plt.ylabel('PSNR')
            plt.savefig(f'{outdir}/trans_{transferimage_name}_sparsenet_set14/{sigma}/psnr_{image_name}.png')
            plt.close()

    torch.cuda.empty_cache()
    print("Experiment done")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Image denoising using DIP")

    image_choices = [
        'baboon', 'barbara', 'lena', 'pepper'
    ]

    parser.add_argument("--images", type=str, default=["Lena512rgb"], help="which image to denoise")
    parser.add_argument("--lr", type=float, default=1e-2, help="the learning rate")
    parser.add_argument("--max_steps", type=int, default=40000, help="the maximum number of gradient steps to train for")
    parser.add_argument("--optim", type=str, default="SAM", help="which optimizer")
    parser.add_argument("--reg", type=float, default=0.05, help="if regularization strength of igr")
    parser.add_argument("--sigma", type=float, default=0.1, help="noise-level")
    parser.add_argument("--num_layers", type=int, default=6, help="number of layers")
    parser.add_argument("--show_every", type=int, default=1000, help="show_every")
    parser.add_argument("--device_id", type=int, default=0, help="specify which gpu")
    parser.add_argument("--beta", type=float, default=0, help="momentum for sgd")
    parser.add_argument("--decay", type=float, default=0, help="weight decay")
    parser.add_argument("--image_name", type=str, choices=image_choices, default="baboon", help="image to denoise")
    parser.add_argument("--transferimage_name", type=str, choices=image_choices, default="barbara", help="transfer image from which to transfer")
    parser.add_argument("--trans_type", type=str, default="pai", help="transfer type")
    parser.add_argument("--mask_opt", type=str, default="det", help="mask type")
    parser.add_argument("--noise_steps", type=int, default=80000, help="number of steps for noise")
    parser.add_argument("--kl", type=float, default=1e-5, help="regularization strength of kl")
    parser.add_argument("--prior_sigma", type=float, default=0.0, help="prior mean")
    parser.add_argument("--sparsity", type=float, default=0.05, help="sparsity percent")
    args = parser.parse_args()

    main(images=args.images, lr=args.lr, max_steps=args.max_steps, 
         optim=args.optim, reg=args.reg, sigma=args.sigma, num_layers=args.num_layers, 
         show_every=args.show_every, beta=args.beta, device_id=args.device_id, image_name=args.image_name, 
         transferimage_name=args.transferimage_name, trans_type=args.trans_type, weight_decay=args.decay, 
         mask_opt=args.mask_opt, noise_steps=args.noise_steps, kl=args.kl, prior_sigma=args.prior_sigma, sparsity=args.sparsity)


