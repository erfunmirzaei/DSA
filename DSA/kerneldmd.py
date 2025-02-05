from sklearn.gaussian_process.kernels import DotProduct, RBF
from kooplearn.data import traj_to_contexts
from kooplearn.models import  NystroemKernel
import numpy as np
import torch

class KernelDMD(NystroemKernel):
    def __init__(
            self,
            data,
            n_delays,
            kernel = RBF(),
            num_centers=0.1,
            delay_interval=1,
            rank=10,
            reduced_rank_reg=True,
            lamb=1e-10,
            verbose=False,
            svd_solver='arnoldi',
        ):
        """
        Subclass of kooplearn that uses a kernel to compute the DMD model.
        This will also use Reduced Rank Regression as opposed to Principal Component Regression (above)
        """
        super().__init__(kernel,reduced_rank_reg,rank,lamb,svd_solver,num_centers)
        self.n_delays = n_delays 
        self.context_window_len = n_delays + 1
        self.delay_interval = delay_interval
        self.verbose = verbose
        self.rank = rank
        self.lamb = 0 if lamb is None else lamb
        
        self.data = data
    
    def fit(
            self,
            data=None,
            lamb=None,
        ):
        """
        Parameters
        ----------
        data : np.ndarray or torch.tensor
            The data to fit the DMD model to. Must be either: (1) a
            2-dimensional array/tensor of shape T x N where T is the number
            of time points and N is the number of observed dimensions
            at each time point, or (2) a 3-dimensional array/tensor of shape
            K x T x N where K is the number of "trials" and T and N are
            as defined above. Defaults to None - provide only if you want to
            override the value from the init.

        lamb : float
            Regularization parameter for ridge regression. Defaults to None - provide only if you want to
            override the value from the init.
        """
        data = self.data if data is None else data
        lamb = self.lamb if lamb is None else lamb

        self.compute_hankel(data)
        self.compute_kernel_dmd(lamb)

    def compute_hankel(self,trajs):
        '''
        Given a numpy array or list of trajectories, returns a numpy array of delay embeddings
        in the format required by kooplearn. 
        Parameters
        ----------
        trajs : np.ndarray or list, with each array having shape 
            (num_samples, timesteps, dimension) or shape (timesteps, dimension).
            Note that trajectories can have different numbers of timesteps but must have the same dimension
        n_delays : int
            The number of delays to include in the delay embedding
        delay_interval : int
            The number of time steps between each delay in the delay embedding
        '''
        if isinstance(trajs, torch.Tensor):
            #convert trajs to a np array
            trajs = trajs.numpy()
        if isinstance(trajs,np.ndarray) and trajs.ndim == 2:
            trajs = trajs[np.newaxis,:,:]
        
        data = traj_to_contexts(trajs[0],context_window_len=self.context_window_len,
                                time_lag=self.delay_interval)
        # idx = np.zeros(data.idx_map.shape)
        # data.idx_map = np.concatenate((idx,data.idx_map),axis=-1)
        for i in range(1,len(trajs)):
            new_traj = traj_to_contexts(trajs[i],context_window_len=self.context_window_len,
                time_lag=self.delay_interval)

            data.data = np.concatenate((data.data,new_traj.data),axis=0)

            #update index map for consistency
            # idx = np.zeros(new_traj.idx_map.shape) + 1 
            # new_traj.idx_map = np.concatenate((idx,new_traj.idx_map),axis=-1)
            # data.idx_map = np.concatenate((data.idx_map,new_traj.idx_map),axis=0)

        self.data = data

        if self.verbose:
            print("Hankel matrix computed")

    def compute_kernel_dmd(self,lamb = None):
        '''
        Computes the kernel DMD model. 
        '''
        self.tikhonov_reg = self.lamb if lamb is None else lamb
        #we need to use the inherited .fit method from NystroemKernel

        # data = self.data.reshape(-1,*self.data.shape[2:])
        super().fit(self.data)

        self.A_v = self.V.T @ self.kernel_YX @ self.U / len(self.kernel_YX)

        if self.verbose:
            print("kernel regression complete")

    def predict(
        self,
        test_data=None,
        reseed=None,
        ):
        '''
        Assuming test_data is one trajectory or list of trajectories
        
        Returns
        -------
        pred_data : np.ndarray
             The predictions generated by the kernelDMD model. Of the same shape as test_data. Note that the first
             (self.n_delays - 1)*self.delay_interval + 1 time steps of the generated predictions are by construction
             identical to the test_data.
        '''
        if test_data is None:
            test_data = self.data
        if reseed is None:
            reseed = 1
        else:
            raise NotImplementedError
        
        if isinstance(test_data, torch.Tensor):
            test_data = test_data.numpy()
        if isinstance(test_data,list):
            test_data = np.array(test_data)

        isdim2 = test_data.ndim == 2
        if isdim2: #if we have a single trajectory
            test_data = test_data[np.newaxis, :, :]

        pred_data = np.zeros(test_data.shape)
        pred_data[:, 0:self.n_delays] = test_data[:, 0:self.n_delays]

        #here the hankel matrix should be (ntrials,time,n_delays,dim)
        self.compute_hankel(test_data)

        pred = super().predict(self.data)
        pred = pred.reshape(test_data.shape[0],test_data.shape[1]-self.n_delays,test_data.shape[2])
        pred_data[:,self.n_delays:] = pred

        return pred_data.squeeze()
        #TODO: integrate tailbiting
        #split into original trajectories so pred_data matches test_data
        # import ipdb; ipdb.set_trace()

        # #reshape into the right 4 dimensions
        # test_data = self.data.data.reshape(test_data.shape[0],test_data.shape[1]-self.n_delays,self.context_window_len,test_data.shape[2])
        
        # #get the test data into the format of the hankel matrix
        # #apply the nystroem predict function
        # for t in range(self.n_delays, test_data.shape[1]):
        #     if t % reseed == 0:
        #         #need to ignore the current value which is what we're trying to predict
        #         #hence the -1 at the end
        #         curr = test_data[:,t-1:t,:-1].reshape(-1,self.n_delays,test_data.shape[-1])
        #         pred_data[:,t] = super().predict(curr)
        #     else:
        #         past = pred_data[:,t-self.context_window_len:t]
        #         pred_data[:,t] = super().predict(past)

        # if isdim2:
        #     pred_data = pred_data[0]

