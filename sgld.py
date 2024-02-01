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
from models.cnn import cnn
import torch
import torch.optim
import time
from PIL import Image
#from skimage.measure import compare_psnr
from utils.inpainting_utils import * 
import pickle as cPickle
torch.backends.cudnn.enabled = True
torch.backends.cudnn.benchmark =True
dtype = torch.cuda.FloatTensor
from torch.nn.utils import parameters_to_vector, vector_to_parameters
from sam import SAM
#from skimage.measure import compare_psnr
from skimage.metrics import peak_signal_noise_ratio as compare_psnr


import argparse

def main(images: list, lr: float, max_steps: int, optim: str, reg: float = 0.0, sigma: float = 0.2, num_layers: int = 4, show_every: int=1000, device_id: int = 0,beta: float = 0.0,ino : int =0,weight_decay: float = 0.0):

    torch.cuda.set_device(device_id)
    torch.cuda.current_device() 

    def normalize_image(img):
        min_val = np.min(img)
        max_val = np.max(img)
        return (img - min_val) / (max_val - min_val)  

    # def compare_psnr(img1, img2):
    #     MSE = np.mean(np.abs(img1-img2)**2)
    #     psnr=10*np.log10(np.max(np.abs(img1))**2/MSE)
    #     return psnr 
    
    def add_noise(model):
        for n in [x for x in model.parameters() if len(x.size()) == 4]:
            # Create noise on the same device as the parameter 'n'
            noise = torch.randn(n.size()).to(n.device) * param_noise_sigma * args.lr
            # Add the noise to the parameter
            n.data = n.data + noise

    
    
    img_np_list=[]
    img_noisy_np_list=[]
    noisy_psnr_list=[]
    psrn_noisy_last = 0
    # train_folder = 'result/Urban100/image_SRF_2/train'
    # train_folder = 'data/denoising/Dataset'
    # train_noisy_folder = 'data/denoising/Dataset/train_noisy_{}'.format(sigma)
    train_folder = 'data/denoising/face'
    train_noisy_folder = 'data/denoising/face/train_noisy_{}'.format(sigma)

    os.makedirs(train_noisy_folder, exist_ok=True)
#    for image in images:
#        imagename = "image_" + str(image) + ".png"
#        fname = 'data/denoising/Dataset' + "/" + imagename
#        imsize = -1
#        img_pil = crop_image(get_image(fname, imsize)[0], d=32)
#        img_np = pil_to_np(img_pil)
#        img_np = img_np[0, :, :]
#        img_noisy_np = img_np + sigma*np.random.normal(scale=sigma, size=img_np.shape)
#        img_noisy_np = normalize_image(img_noisy_np)                
#        img_np_list.append(img_np)
#        img_noisy_np_list.append(img_noisy_np)  

    for i, file_path in enumerate(glob.glob(os.path.join(train_folder, '*.jpg'))):
        if i == ino:  # we start counting from 0, so the 3rd image is at index 2
            # Get the filename (without extension) for use in messages
            filename = os.path.splitext(os.path.basename(file_path))[0]
            imsize = -1
            
            img_pil = Image.open(file_path)
            #img_pil = crop_image(get_image(file_path, imsize)[0], d=32)
            img_pil = resize_and_crop(img_pil, max(img_pil.size))
            img_np = pil_to_np(img_pil)
            print(img_np.shape)

            img_noisy_np = img_np +np.random.normal(scale=sigma, size=img_np.shape)
            img_noisy_np = np.clip(img_noisy_np , 0, 1).astype(np.float32)

            img_np_list.append(img_np)
            img_noisy_np_list.append(img_noisy_np)
            
            img_noisy_pil = np_to_pil(img_noisy_np)
            img_noisy_pil.save(os.path.join(train_noisy_folder, filename + '.png'))
            

            break  # exit the loop

    noisy_psnr = compare_psnr(img_np,img_noisy_np)
    noisy_psnr_list.append(noisy_psnr)
    print(f'Starting vanilla DIP on {ino} using {optim}(sigma={sigma},lr={lr},decay={weight_decay},beta={beta})')
    print(f"Noisy PSNR is '{noisy_psnr}'")

            

    # Modify input and output depths
    input_depth = 32   
    output_depth = 3
    param_noise_sigma = 4


    # Adjust loss function
    mse = torch.nn.MSELoss().type(dtype)
    # img_var_list = [np_to_torch(img_np).type(dtype) for img_np in img_np_list]
    # noise_var_list = [np_to_torch(img_mask_np).type(dtype) for img_mask_np in img_noisy_np_list]

    INPUT = "noise"
        
    net_input= get_noise(input_depth, INPUT, img_np.shape[1:]).type(dtype) 
    net_input_saved = net_input.detach().clone()
    noise = net_input.detach().clone()
    # print("input dim:", net_input.shape) [1, 3, 256, 256]
    # net_input = 
    net = skip(
        input_depth, output_depth,
        num_channels_down = [16, 32, 64, 128, 128, 128][:num_layers],
        num_channels_up   = [16, 32, 64, 128, 128, 128][:num_layers],
        num_channels_skip = [0]*num_layers,
        upsample_mode='nearest',
        downsample_mode='avg',
        need1x1_up = False,
        filter_size_down=5, 
        filter_size_up=3,
        filter_skip_size = 1,
        need_sigmoid=True, 
        need_bias=True, 
        pad='reflection', 
        act_fun='LeakyReLU').type(dtype)

    # net = cnn( num_input_channels=input_depth, num_output_channels=output_depth,
    #    num_layers=3,
    #    need_bias=True, pad='zero',
    #    act_fun='LeakyReLU').type(dtype)
   
    
    print(f"Starting optimization with optimizer '{optim}'")
    if optim =="SGD":
        optimizer = torch.optim.SGD(net.parameters(), lr=lr, weight_decay = weight_decay,momentum = beta)
    elif optim =="ADAM":
        optimizer = torch.optim.Adam(net.parameters(), lr=lr, weight_decay = weight_decay)
        print("here")
    elif optim =="SAM":
        base_opt = torch.optim.SGD
        optimizer = SAM(net.parameters(), base_opt, rho=args.reg, adaptive=False, lr=args.lr, weight_decay = weight_decay,momentum = beta) 
          
    i=0
   #[1e-1,1e-2,5e-2],[0.5,0.8] [1e-3 5e-3]
    tot_loss = []
    grad_list = []
    sharp=[]
    psnr_list=[]   
    psnr_noisy_last = 0 
    reg_noise_std = 1./30.
    
    def closure_sgld(net_input,img_var,noise_var):

        if reg_noise_std > 0:
            net_input = net_input_saved + (noise.normal_() * reg_noise_std)
        img_var = np_to_torch(img_var).type(dtype)
        noise_var = np_to_torch(noise_var).type(dtype)
        out = net(net_input)
        total_loss = mse(out, noise_var)
        total_loss.backward()
        out_np = out.detach().cpu().numpy()[0]
        #psrn_noisy = compare_psnr(img_noisy_np, out.detach().cpu().numpy()[0])
        psrn_gt    = compare_psnr(img_np, out_np)
        #print ('Iteration %05d    Loss %f   PSNR_noisy: %f   PSNR_gt: %f' % (i, total_loss.item(), psrn_noisy, psrn_gt), '\r', end='')

        # psnr_list.append(psrn_gt)
        return psrn_gt,out_np

    outdir = f'data/denoising/face/{ino}/sgld'
    os.makedirs(f'{outdir}', exist_ok=True)
    for j in range(max_steps):
        optimizer.zero_grad()
        psnr,out = closure_sgld( net_input, img_np, img_noisy_np)
        psnr_noisy = compare_psnr(img_noisy_np, out)
        optimizer.step()
        add_noise(net)

        if j%show_every==0 and j!=0:
            if psnr_noisy - psrn_noisy_last < -2: 
                print('Falling back to previous checkpoint.')
                for new_param, net_param in zip(last_net, net.parameters()):
                    net_param.detach().copy_(new_param.cuda())
            else:
                last_net = [x.detach().cpu() for x in net.parameters()]
                psrn_noisy_last = psnr_noisy            
            print(f"At step '{j}', psnr is '{psnr}', noisy psnr is '{psnr_noisy}")
            psnr_list.append(psnr)  

    ##plot and save psnr list in train folder with figure name including ino 
    plt.plot(psnr_list)
    plt.savefig(f'{outdir}/psnr_{ino}.png')
    plt.close()
    ## save the list "psnr" as an npz file and save in the outdir folder
    np.savez(f'{outdir}/psnr_{ino}.npz', psnr=psnr_list)

    output_paths = [
    f"{outdir}/out_{ino}.png",
    f"{outdir}/img_np_{ino}.png",
    f"{outdir}/img_noisy_np_{ino}.png"]  
    print(out.shape, img_np.shape, img_noisy_np.shape)
    images_to_save = [out.transpose(1,2,0), img_np.transpose(1,2,0), img_noisy_np.transpose(1,2,0)]
    for path, img in zip(output_paths, images_to_save):
        plt.imshow(img)
        plt.axis('off')
        plt.savefig(path, bbox_inches='tight', pad_inches=0)
        plt.close()
            ## plot the psnr which is a list and multiply the iteration index by showevery to get the x-axis
        plt.plot(psnr_list)
        plt.title('PSNR vs Iterations')
        plt.xlabel('Iterations')
        plt.ylabel('PSNR')
        plt.savefig(f'{outdir}/psnr_{ino}.png')
        plt.close()     

    torch.cuda.empty_cache()
    print("Experiment done")           
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Image denoising using DIP")
    
    parser.add_argument("--images", type=str, default = ["Lena512rgb"], help="which image to denoise")
    parser.add_argument("--lr", type=float,  default=1e-2, help="the learning rate")
    parser.add_argument("--max_steps", type=int, default=40000, help="the maximum number of gradient steps to train for")
    parser.add_argument("--optim", type=str, default="ADAM", help="which optimizer")
    #parser.add_argument("--IGR", type=str, default="Normal", help="true if SAM ")
    parser.add_argument("--reg", type=float, default=0.05, help="if regularization strength of igr")
    parser.add_argument("--sigma", type=float, default=0.1, help="noise-level")
    parser.add_argument("--num_layers", type=int, default=6, help="number of layers")
    parser.add_argument("--show_every", type=int, default=1000, help="show_every")
    parser.add_argument("--device_id", type=int, default=1, help="specify which gpu")
    parser.add_argument("--beta", type=float, default=0, help="momentum for sgd ")
    parser.add_argument("--decay", type=float, default=0, help="weight decay")
    parser.add_argument("--ino", type=int, default=0, help="image index ")
    args = parser.parse_args()
    
    main(images=args.images, lr=args.lr, max_steps=args.max_steps, optim= args.optim,reg=args.reg,sigma = args.sigma, num_layers = args.num_layers, show_every = args.show_every, beta = args.beta, device_id = args.device_id,ino = args.ino, weight_decay = args.decay)
        
    
    
        
        
    
    

