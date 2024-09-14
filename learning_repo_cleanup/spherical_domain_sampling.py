import torch
from tqdm import tqdm
from utils.utils import *
from utils.model import *
from utils.distribution import *
from utils.mitsuba_brdf_scalar import meaturedbsdf as meaturedbsdf_scalar
from utils.emcee_sampling import *
import numpy as np
import argparse
import tinycudann




torch.set_default_dtype(torch.float32)

def pretrain_stage(args,brdf_samples,save_dir):
    Ndata = brdf_samples.shape[0] 
    pretrain_network = NN_cond_pretrain_spherical_one(input_dim=2,N_NEURONS=16,POSITIONAL_ENCODING_BASIS_NUM=3).to("cuda")
    optimizer_pretrain = torch.optim.Adam(pretrain_network.parameters(), lr=0.0003)
    pbar = tqdm(total=args.num_epochs_pretrain)
    print("Start training: pretrain")
    for iteration in (range(args.num_epochs_pretrain)):
        x_1 = brdf_samples[np.random.randint(0,Ndata,args.batchsize_pretrain),:]
        omega_o = x_1[:,2:4]
        omega_i = x_1[:,0:2]
        logp = pretrain_network.log_prob(omega_o,omega_i)    
        loss = -torch.mean(logp)
        loss.backward()
        optimizer_pretrain.step()
        if iteration % args.show_iter == 0:
            pbar.set_description(f"Loss {loss.item():.10f}")
            pbar.update(args.show_iter)   
        if iteration % args.save_iter == 0:
            save_model(pretrain_network,save_dir,"brdf_pretrain_network" + args.material)
        pretrain_network.zero_grad()
    pbar.close()
    print("Finish training: pretrain")

def diffusion_stage(args,brdf_samples,save_dir):
    Ndata = brdf_samples.shape[0]
    pretrain_network = NN_cond_pretrain_spherical_one(input_dim=2,N_NEURONS=16,POSITIONAL_ENCODING_BASIS_NUM=3).to("cuda")
    pretrain_network.load_state_dict(torch.load(os.path.join(save_dir,"brdf_pretrain_network" + args.material + ".pth")))
    diffusion_network_simpler = NN_cond_pos(input_dim=6,output_dim=2,N_NEURONS=32,POSITIONAL_ENCODING_BASIS_NUM=5).to("cuda")
    optimizer_diffusion_simpler = torch.optim.Adam(diffusion_network_simpler.parameters(), 0.001)
    
    diffusion_network_complex = NN_cond_pos_spherical_complicate(input_dim=6,output_dim=2,N_NEURONS=64,POSITIONAL_ENCODING_BASIS_NUM=5).to("cuda")
    optimizer_diffusion_complex = torch.optim.Adam(diffusion_network_complex.parameters(), 0.001)
    pbar = tqdm(total=args.num_epochs_diffusion)
    twopi = np.pi * 2

    print("Start training: diffusion simpler")
    for iteration in (range(args.num_epochs_diffusion)):
        x_1 = brdf_samples[np.random.randint(0,Ndata,args.batchsize_diffusion),:]
        omega_o = x_1[:,2:4]
        omega_i = x_1[:,0:2]
        with torch.no_grad():
            x_0 = pretrain_network.sample(omega_i,args.batchsize_diffusion)
        alpha = torch.linspace(0,1,args.batchsize_diffusion).to("cuda")
        alpha = alpha.reshape(-1,1)
        
        tmp_dirc = omega_o[:,1] - x_0[:,1]
        omega_o[:,1] = torch.where(tmp_dirc < - np.pi,omega_o[:,1] + twopi , torch.where(tmp_dirc > np.pi,omega_o[:,1] - twopi,omega_o[:,1]))
        x_alpha = (1 - alpha) * x_0 + alpha * omega_o
        x_alpha_predioc = torch.cat([torch.sin( x_alpha[:,1]).reshape(-1,1),torch.cos( x_alpha[:,1]).reshape(-1,1)],dim=1)
        x_alpha_2d = torch.cat([x_alpha[:,0].reshape(-1,1),x_alpha_predioc],dim=1)
        
        pred = diffusion_network_simpler(x_alpha_2d, alpha, omega_i)
        
        thetadirc = omega_o[:,0] - x_0[:,0]
        phidirc = torch.where(tmp_dirc < - np.pi,tmp_dirc + twopi , torch.where(tmp_dirc > np.pi,tmp_dirc - twopi,tmp_dirc))
        twod_dirc = torch.cat([thetadirc.reshape(-1,1),phidirc.reshape(-1,1)],dim=1)
        
        loss = torch.mean((pred -  (twod_dirc)) ** 2)
        loss.backward()
        optimizer_diffusion_simpler.step()
        if iteration % args.show_iter == 0:
            pbar.set_description(f"Loss {loss.item():.10f}")
            pbar.update(args.show_iter)
        if iteration % args.save_iter == 0:
            save_model(diffusion_network_simpler,save_dir,"brdf_diffusion_network_simpler" + args.material)
        optimizer_diffusion_simpler.zero_grad()
    pbar.close()
    print("Finish training: diffusion simpler")
    
    
    
    print("Start training: diffusion complex")
    for iteration in (range(args.num_epochs_diffusion)):
        x_1 = brdf_samples[np.random.randint(0,Ndata,args.batchsize_diffusion),:]
        omega_o = x_1[:,2:4]
        omega_i = x_1[:,0:2]
        with torch.no_grad():
            x_0 = pretrain_network.sample(omega_i,args.batchsize_diffusion)
        alpha = torch.linspace(0,1,args.batchsize_diffusion).to("cuda")
        alpha = alpha.reshape(-1,1)
        
        tmp_dirc = omega_o[:,1] - x_0[:,1]
        omega_o[:,1] = torch.where(tmp_dirc < - np.pi,omega_o[:,1] + twopi , torch.where(tmp_dirc > np.pi,omega_o[:,1] - twopi,omega_o[:,1]))
        x_alpha = (1 - alpha) * x_0 + alpha * omega_o
        x_alpha_predioc = torch.cat([torch.sin( x_alpha[:,1]).reshape(-1,1),torch.cos( x_alpha[:,1]).reshape(-1,1)],dim=1)
        x_alpha_2d = torch.cat([x_alpha[:,0].reshape(-1,1),x_alpha_predioc],dim=1)
        
        pred = diffusion_network_complex(x_alpha_2d, alpha, omega_i)
        
        thetadirc = omega_o[:,0] - x_0[:,0]
        phidirc = torch.where(tmp_dirc < - np.pi,tmp_dirc + twopi , torch.where(tmp_dirc > np.pi,tmp_dirc - twopi,tmp_dirc))
        twod_dirc = torch.cat([thetadirc.reshape(-1,1),phidirc.reshape(-1,1)],dim=1)
        
        loss = torch.mean((pred -  (twod_dirc)) ** 2)
        loss.backward()
        optimizer_diffusion_complex.step()
        if iteration % args.show_iter == 0:
            pbar.set_description(f"Loss {loss.item():.10f}")
            pbar.update(args.show_iter)
        if iteration % args.save_iter == 0:
            save_model(diffusion_network_complex,save_dir,"brdf_diffusion_network_complex" + args.material)
        optimizer_diffusion_complex.zero_grad()
    pbar.close()
    print("Finish training: diffusion complex")
    
def rectify_stage(args,save_dir):
    
    print("Start training: rectify")
    pretrain_network = NN_cond_pretrain_spherical_one(input_dim=2,N_NEURONS=16,POSITIONAL_ENCODING_BASIS_NUM=3).to("cuda")
    pretrain_network.load_state_dict(torch.load(os.path.join(save_dir,"brdf_pretrain_network" + args.material + ".pth")))
    diffusion_network = NN_cond_pos(input_dim=6,output_dim=2,N_NEURONS=32,POSITIONAL_ENCODING_BASIS_NUM=5).to("cuda")
    diffusion_pytorch_weights = torch.load(os.path.join(save_dir,"brdf_diffusion_network_simpler" + args.material + ".pth"))
    diffusion_network.load_state_dict(diffusion_pytorch_weights)
    rectify_temp_net = tinycudann.Network(
        n_input_dims=26,
        n_output_dims=2,
        network_config={
            "otype": "FullyFusedMLP",
            "activation": "SiLU",
            "output_activation": "None",
            "n_neurons": 64,
            "n_hidden_layers": 6
        }
    )
    diffusion_pytorch_weights = torch.load(os.path.join(save_dir,"brdf_diffusion_network_complex" + args.material + ".pth"))
    load_pytorch_model_to_tinycuda(rectify_temp_net,diffusion_pytorch_weights,26,2)
    rectify_temp_net.eval()
    
    T = args.timestep_rectify

    def dosampling(batchsize,omega_i,T):

        x_target_y = omega_i.repeat_interleave(batchsize,0)
        with torch.no_grad():
            x_alpha = pretrain_network.sample(x_target_y,batchsize * len(omega_i))
        x_base_samples = x_alpha.clone()
        
        x_target_y_tmp = positional_encoding_1(x_target_y, 5)
        ones = torch.ones(batchsize * len(omega_i),1,device='cuda')

        with torch.no_grad():
            for t in (range(T)):
                alpha = t / T * ones
                x_alpha_predioc = torch.cat([torch.sin( x_alpha[:,1]).reshape(-1,1),torch.cos( x_alpha[:,1]).reshape(-1,1)],dim=1)
                x_alpha_2d = torch.cat([x_alpha[:,0].reshape(-1,1),x_alpha_predioc],dim=1)
                x_input = torch.cat([x_alpha_2d,alpha,x_target_y_tmp],dim = 1)
                d_output = rectify_temp_net(x_input)
                x_alpha = x_alpha + 1 / T * d_output

        return x_alpha,x_base_samples,x_target_y

    optimizer_D = torch.optim.Adam(diffusion_network.parameters(), lr=0.001)
    twopi = np.pi * 2
    pbar = tqdm(total=args.num_epochs_rectify)
    for iteration in (range(1,args.num_epochs_rectify)):
        
        omega_i_samples = stratified_sampling_2d(args.batchsize_rectify).cuda()
        omega_i_samples[:,0] = omega_i_samples[:,0] * np.pi / 2
        omega_i_samples[:,1] = omega_i_samples[:,1] * 2 * np.pi - np.pi
        
        x_1,x_0,x_target_y = dosampling(args.num_samples_rectify,omega_i_samples,T)
        indices = torch.randperm(len(x_1))
        x_0 = x_0[indices, :]
        x_1 = x_1[indices, :]
        x_target_y = x_target_y[indices, :]
        omega_o = x_1
        omega_i = x_target_y
        alpha = torch.linspace(0,1,args.num_samples_rectify*args.batchsize_rectify,device='cuda').reshape(-1,1)
        tmp_dirc = omega_o[:,1] - x_0[:,1]
        omega_o[:,1] = torch.where(tmp_dirc < - np.pi,omega_o[:,1] + twopi , torch.where(tmp_dirc > np.pi,omega_o[:,1] - twopi,omega_o[:,1]))
        x_alpha = (1 - alpha) * x_0 + alpha * omega_o
        x_alpha_predioc = torch.cat([torch.sin( x_alpha[:,1]).reshape(-1,1),torch.cos( x_alpha[:,1]).reshape(-1,1)],dim=1)
        x_alpha_2d = torch.cat([x_alpha[:,0].reshape(-1,1),x_alpha_predioc],dim=1)
        pred = diffusion_network(x_alpha_2d, alpha, omega_i)
        thetadirc = omega_o[:,0] - x_0[:,0]
        phidirc = torch.where(tmp_dirc < - np.pi,tmp_dirc + twopi , torch.where(tmp_dirc > np.pi,tmp_dirc - twopi,tmp_dirc))
        twod_dirc = torch.cat([thetadirc.reshape(-1,1),phidirc.reshape(-1,1)],dim=1)
        loss = torch.mean((pred -  (twod_dirc)) ** 2)
        loss.backward()
        optimizer_D.step()
        if iteration % args.show_iter == 0:
            pbar.set_description(f"Loss {loss.item():.10f}")
            pbar.update(args.show_iter)   
        if iteration % args.save_iter == 0:
            save_model(diffusion_network,save_dir,"brdf_rectify_network" + args.material)
        optimizer_D.zero_grad()
    pbar.close()
    
    print("Finish training: rectify")

if __name__ == "__main__":
    
    parser = argparse.ArgumentParser()
    
    parser.add_argument("--batchsize_pretrain", default = "4900000 * 2",type=eval_arg)
    parser.add_argument("--num_epochs_pretrain", default = "10000",type=eval_arg)
    
    parser.add_argument("--num_epochs_diffusion", default = "40000",type=eval_arg)
    parser.add_argument("--batchsize_diffusion", default = "4900000 ",type=eval_arg)

    parser.add_argument("--num_epochs_rectify", default = "20000",type=eval_arg)
    parser.add_argument("--timestep_rectify", default = 128,type=int)
    parser.add_argument("--num_samples_rectify", default = "2**16",type=eval_arg)
    parser.add_argument("--batchsize_rectify", default = "2**6",type=eval_arg)
    
    parser.add_argument("--save_iter", default = "1000",type=eval_arg)
    parser.add_argument("--show_iter", default = "100",type=eval_arg)
    parser.add_argument("--save_dir", default = "./checkpoints_new",type=str)
    parser.add_argument("--base_dir", default = "./measuredbsdfs",type=str)
    parser.add_argument("--material", type=str, default="chm_orange_rgb")
    
    parser.add_argument("--is_rectify", default = False,type=bool)
    args = parser.parse_args()
    
    prefix = args.material + "_spherical"
    mybsdf_scalar = meaturedbsdf_scalar(os.path.join(args.base_dir,args.material+".bsdf"),is_spherical=True)
    save_dir = os.path.join(args.save_dir,prefix)
    file_path = os.path.join(save_dir,"brdf_samples_emcee" + args.material + ".npy")
    
    def pdf_func(x):
        x = torch.tensor(x).reshape(-1,4)
        r = mybsdf_scalar.eval(x[:,0:2],x[:,2:4])
        return r
    
   
    if args.is_rectify:
        rectify_stage(args,save_dir)
    else:
        if os.path.exists(file_path):
            brdf_samples = np.load(file_path)
        else:
            brdf_samples = emcee_mcmc_brdf_spherical(pdf_func, 40000, burn_in=10000)
            os.makedirs(os.path.join(args.save_dir,prefix), exist_ok=True)
            np.save(os.path.join(args.save_dir,prefix,"brdf_samples_emcee" + args.material +".npy"),brdf_samples)
    
        brdf_samples = torch.from_numpy(brdf_samples).to("cuda").type(torch.float32)
        
        pretrain_stage(args,brdf_samples,save_dir)
        
        diffusion_stage(args,brdf_samples,save_dir)
        
        rectify_stage(args,save_dir)
    
