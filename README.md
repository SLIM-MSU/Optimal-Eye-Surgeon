# Optimal Eye Surgeon ([ICML-2024](https://arxiv.org/abs/2406.05288))

<div style="display: flex; justify-content: space-around;">
    <img src="paper_figures/flow.svg" alt="Flow Diagram" style="width: 45%;"/>
    <img src="paper_figures/transfer.svg" alt="Transfer Diagram" style="width: 45%;"/>
</div>

This repository contains the source code for pruning image generator networks at initialization to alleviate overfitting.

Repository structure:
```
📦
├─ baselines
│  ├─ baseline_pai.py
│  ├─ baseline_pat.py
│  ├─ sgld.py
│  ├─ vanilla_decoder.py
│  └─ vanilla_dip.py
├─ images
├─ configs
├─ sparse_models
│  ├─ baboon
│  ├─ barbara
│  ├─ lena
│  └─ pepper
├─ sparse_models_imp
│  ├─ baboon
│  ├─ barbara
│  ├─ lena
│  └─ pepper
├─ src
│  ├─ models
│  └─ utils
├─ dip_mask.py
├─ train_sparse.py
└─ transfer.py
```



## Table of Contents
- [Optimal Eye Surgeon (ICML-2024)](#optimal-eye-surgeon-icml-2024)
- [Table of Contents](#table-of-contents)
- [Setup](#setup)
- [Working](#working)
  - [Quick demo:](#quick-demo)
  - [Finding-1: Finding mask at initialization](#finding-1-finding-mask-at-initialization)
  - [Finding-2: Sparse network training](#finding-2-sparse-network-training)
  - [Finding-3: Sparse network transfer](#finding-3-sparse-network-transfer)
    - [Transfer OES masks](#transfer-oes-masks)
  - [Finding-4: Baseline pruning methods](#finding-4-baseline-pruning-methods)
    - [Pruning at initialization Methods](#pruning-at-initialization-methods)
    - [IMP](#imp)


##  Setup
Install conda, create and activate environment and install required packages

```bash
conda create --name oes python==3.7.16
conda activate oes
pip install -r requirements.txt && pip install -e .
```

## Working

### Quick demo:

Please run [OES_demo_comparison.ipynb](OES_demo_comparison.ipynb) to see how OES prevents overfitting in comparison to other methods. (Approximate runtime ~ 10 mins)

Run [impvsoes_comparison.ipynb](impvsoes_comparison.ipynb) to compare OES masks at initialization and IMP masks at convergence. (Approximate runtime ~ 7 mins)

Working with the code to reproduce results for each finding in the paper:

### Finding-1: Finding mask at initialization

<img src="paper_figures/equation.png" width="400px">

The following code implements the above optimization using Gumbel softmax reparameterization trick to find sparse network with 5% weights remaining with a noisy pepper image:

```python
python dip_mask.py --sparsity=0.05 --image_name="pepper"
```

to generate supermasks at various sparsity levels as follows

<img src="paper_figures/only2masks.svg" width="500px">

### Finding-2: Sparse network training

After obtaining a mask by the above procedure, run the following to train the sparse network on the image. The sparse network alleviates overfitting:

<img src="paper_figures/psnr_comb0.svg" width="500px">

```python
python train_sparse.py -f configs/config_train_sparse.yaml
```

For comparing with baselines

Run the following command for dense DIP

```python
python baselines/vanilla_dip.py -f configs/config_vanilla_dip.yaml
```

Run the following command for deep-decoder

```python
python baselines/vanilla_decoder.py -f configs/config_vanilla_decoder.yaml
```

and the command for SGLD

```python
python baselines/sgld.py -f configs/config_sgld.yaml
```

### Finding-3: Sparse network transfer
####  Transfer OES masks

<div style="display: flex; justify-content: space-between;">
  <img src="paper_figures/another.gif" alt="Sparse Network Transfer 1" width="300">
  <img src="paper_figures/Lena_ppt3.gif" alt="Sparse Network Transfer 2" width="300">
</div>


For OES mask transfer, use the following command:
```python
python transfer.py --trans_type="pai" --transferimage_name="pepper" --image_name="lena"
```

For IMP mask transfer, use the following command:
```python
python transfer.py --trans_type="pat" --transferimage_name="pepper" --image_name="lena"
```

### Finding-4: Baseline pruning methods
#### Pruning at initialization Methods


<img src="paper_figures/Set14-0.svg" alt="Set14-0" width="500px">


```python
python baselines/baseline_pai.py --image_name="pepper" --prune_type="grasp_local" --sparse=0.9
```
Chose among the following options for prune_type:

- `rand_global`
- `rand_local`
- `mag_global`
- `snip`
- `snip_local`
- `grasp`
- `grasp_local`
- `synflow`
- `synflow_local`

#### IMP
```python
python baselines/baseline_pat.py --image_name="pepper" --prune_iters=14 --percent=0.2
```
The above line runs IMP for 14 iterations with 20% deletion of weights at each iteration. Resulting in 5% sparsity. (drastic pruning degrades performance)


### Citation

If you use this code, consider citing our work:

```bibtex
@inproceedings{ghosh2024optimal,
  title={Optimal Eye Surgeon: Finding image priors through sparse generators at initialization},
  author={Ghosh, Avrajit and Zhang, Xitong and Sun, Kenneth K and Qu, Qing and Ravishankar, Saiprasad and Wang, Rongrong},
  booktitle={Forty-first International Conference on Machine Learning},
  year={2024}
}

