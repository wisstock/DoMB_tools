"""
Calculation of Unmixing Coefficients and G Parameter

Require series of calibrationregistrations

Based on Zal and Gascoigne, 2004, doi: 10.1529/biophysj.103.022087

"""

import numpy as np
from numpy import ma
import pandas as pd

import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
import matplotlib.patheffects as PathEffects

from sklearn.linear_model import LinearRegression

from skimage import morphology
from skimage import filters
from skimage import measure
from skimage import io

from scipy import stats
from scipy import ndimage as ndi

from ...utils import masking


# crosstalk estimation
class CrossReg():
    """ Class for one 3-cube FRET method crosstalk calibration registration

    """
    def __init__(self, img, img_name, exp_list, img_type):
        self.img_name = img_name
        self.img_type = img_type
        self.img_raw = img

        self.D_exp = exp_list[0]
        self.A_exp = exp_list[1]

        bc_p_m = lambda x: np.array([f - np.percentile(f,1) for f in x]).clip(min=0).astype(np.uint16)

        self.DD_img = bc_p_m(self.img_raw[:,:,:,0])  # CFP-435  DD
        self.DA_img = bc_p_m(self.img_raw[:,:,:,1])  # YFP-435  DA
        self.AD_img = bc_p_m(self.img_raw[:,:,:,2])  # CFP-505  AD
        self.AA_img = bc_p_m(self.img_raw[:,:,:,3])  # YFP-505  AA

        self.DD_mean_img = np.mean(self.DD_img, axis=0)
        self.DA_mean_img = np.mean(self.DA_img, axis=0)
        self.AD_mean_img = np.mean(self.AD_img, axis=0)
        self.AA_mean_img = np.mean(self.AA_img, axis=0)

        if self.img_type == 'A':
            raw_mask = self.AA_mean_img > filters.threshold_otsu(self.AA_mean_img)
        elif self.img_type == 'D':
            raw_mask = self.DD_mean_img > filters.threshold_otsu(self.DD_mean_img)

        self.mask = morphology.closing(raw_mask, footprint=morphology.disk(10))
        self.mask = morphology.erosion(self.mask, footprint=morphology.disk(10))
        self.label = measure.label(self.mask)


    def cross_fit_px(self, frame_num=0, mode='a', bad_rois=[]):
        pure_frame_arr = np.asarray([])
        cross_frame_arr = np.asarray([])
        
        fig, ax = plt.subplots(layout="constrained", figsize=(10, 4))
        fig.suptitle(f'{self.img_name}: {mode} estimation pixel-wise (frame {frame_num})')
        
        if mode == 'a' and self.img_type == 'A':
            pure_frame = self.AA_img[frame_num] 
            cross_frame = self.DA_img[frame_num] 
        elif (mode == 'b') and (self.img_type == 'A'):
            pure_frame = self.AA_img[frame_num] 
            cross_frame = self.DD_img[frame_num] 
        elif (mode == 'c') and (self.img_type == 'D'):
            pure_frame = self.DD_img[frame_num] 
            cross_frame = self.AA_img[frame_num]
        elif (mode == 'd') and (self.img_type == 'D'):
            pure_frame = self.DD_img[frame_num] 
            cross_frame = self.DA_img[frame_num]
        else:
            raise ValueError('Inconsidtent image type and coeficient!')


        for label_num in range(1, np.max(self.label)+1):
            label_mask = self.label == label_num

            pure_i = ma.masked_where(label_mask, pure_frame).compressed()
            cross_i = ma.masked_where(label_mask, cross_frame).compressed()

            all_zeros = np.array([any(t) for t in zip(pure_i<=0, cross_i<=0)], dtype=np.bool_)
            pure_i, cross_i = pure_i[~all_zeros], cross_i[~all_zeros]

            if label_num in bad_rois:
                continue
            else:
                ax.scatter(x=pure_i,y=cross_i, label=label_num,
                           alpha=.1, s=0.075)

                pure_frame_arr = np.concatenate((pure_frame_arr, pure_i))
                cross_frame_arr = np.concatenate((cross_frame_arr, cross_i))

        # slope, intercept, r, p_slope, std_err = stats.linregress(DD_delta_arr, Fc_delta_arr)

        lin_mod_data = stats.linregress(pure_frame_arr, cross_frame_arr)
        slope, p_slope, std_err_slope = lin_mod_data.slope, lin_mod_data.pvalue, lin_mod_data.stderr
        intercept, std_err_intercept = lin_mod_data.intercept, lin_mod_data.intercept_stderr
        r = lin_mod_data.rvalue

        p_t_calc = lambda m,s,l: 2*stats.t.sf(abs(m/s), (1.0*l - 2))
        p_intercept = p_t_calc(intercept, std_err_intercept, len(pure_frame_arr))

        lin_mod = lambda x: slope*x + intercept

        ax.plot(pure_frame_arr, list(map(lin_mod, pure_frame_arr)),
                 color='k', linestyle='--')
        ax.set_title(f'{mode}={round(slope,3)}+/-{round(std_err_slope,3)} (p={p_slope}), inter.={round(intercept,1)}+/-{round(std_err_slope,3)} (p={p_intercept}), R^2={round(r,4)}')
        ax.set_xlabel('I, a.u.')
        ax.set_ylabel('I, a.u.')
        plt.show()



    def cross_calc(self):
        if self.img_type == 'A':
            _, self.a_prof_arr = masking.label_prof_arr(input_label=self.label,
                                                        input_img_series=self.DA_img / self.AA_img)
            self.a_prof_mean = np.mean(self.a_prof_arr, axis=0)
            _, self.b_prof_arr = masking.label_prof_arr(input_label=self.label,
                                                        input_img_series=self.AD_img / self.AA_img)
            self.b_prof_mean = np.mean(self.b_prof_arr, axis=0)
            # self.a_prof_mean = np.asarray([np.mean(self.DA_img[i] / self.AA_img[i]) for i in range(0, self.img_raw.shape[0])])
            # self.b_prof_mean = np.asarray([np.mean(self.AD_img[i] / self.AA_img[i]) for i in range(0, self.img_raw.shape[0])])

            self.a = np.mean(self.a_prof_mean)
            self.a_sd = np.std(self.a_prof_mean)

            self.b = np.mean(self.b_prof_mean)
            self.b_sd = np.std(self.b_prof_mean)

            a_df = pd.DataFrame({'ID':np.full(len(self.a_prof_mean), self.img_name),
                                 'type':np.full(len(self.a_prof_mean), self.img_type),
                                 'A_exp':np.full(len(self.a_prof_mean), self.A_exp),
                                 'D_exp':np.full(len(self.a_prof_mean), self.D_exp),
                                 'frame':range(len(self.a_prof_mean)),
                                 'coef':np.full(len(self.a_prof_mean), 'a'),
                                 'val':self.a_prof_mean})
            b_df = pd.DataFrame({'ID':np.full(len(self.b_prof_mean), self.img_name),
                                 'type':np.full(len(self.b_prof_mean), self.img_type),
                                 'A_exp':np.full(len(self.b_prof_mean), self.A_exp),
                                 'D_exp':np.full(len(self.b_prof_mean), self.D_exp),
                                 'frame':range(len(self.b_prof_mean)),
                                 'coef':np.full(len(self.b_prof_mean), 'b'),
                                 'val':self.b_prof_mean})
            self.cross_raw_df = pd.concat([a_df, b_df], ignore_index=True)

            self.cross_df = pd.DataFrame({'ID':[self.img_name, self.img_name],
                                          'type':[self.img_type, self.img_type],
                                          'A_exp':[self.A_exp, self.A_exp],
                                          'D_exp':[self.D_exp, self.D_exp],
                                          'coef':['a', 'b'],
                                          'val':[self.a, self.b],
                                          'sd':[self.a_sd, self.b_sd]})

        elif self.img_type == 'D':
            _, self.c_prof_arr = masking.label_prof_arr(input_label=self.label,
                                                        input_img_series=self.AA_img / self.DD_img)
            self.c_prof_mean = np.mean(self.c_prof_arr, axis=0)
            _, self.d_prof_arr = masking.label_prof_arr(input_label=self.label,
                                                        input_img_series=self.DA_img / self.DD_img)
            self.d_prof_mean = np.mean(self.d_prof_arr, axis=0)

            # self.c_prof_mean = np.asarray([np.mean(self.AA_img[i] / self.DD_img[i]) \
            #                          for i in range(0, self.img_raw.shape[0])])
            # self.d_prof_mean = np.asarray([np.mean(self.DA_img[i] / self.DD_img[i]) \
            #                          for i in range(0, self.img_raw.shape[0])])

            self.c = np.mean(self.c_prof_mean)
            self.c_sd = np.std(self.c_prof_mean)

            self.d = np.mean(self.d_prof_mean)
            self.d_sd = np.std(self.d_prof_mean)

            c_df = pd.DataFrame({'ID':np.full(len(self.c_prof_mean), self.img_name),
                                 'type':np.full(len(self.c_prof_mean), self.img_type),
                                 'A_exp':np.full(len(self.c_prof_mean), self.A_exp),
                                 'D_exp':np.full(len(self.c_prof_mean), self.D_exp),
                                 'frame':range(len(self.c_prof_mean)),
                                 'coef':np.full(len(self.c_prof_mean), 'c'),
                                 'val':self.c_prof_mean})
            d_df = pd.DataFrame({'ID':np.full(len(self.d_prof_mean), self.img_name),
                                 'type':np.full(len(self.d_prof_mean), self.img_type),
                                 'A_exp':np.full(len(self.d_prof_mean), self.A_exp),
                                 'D_exp':np.full(len(self.d_prof_mean), self.D_exp),
                                 'frame':range(len(self.d_prof_mean)),
                                 'coef':np.full(len(self.d_prof_mean), 'd'),
                                 'val':self.d_prof_mean})
            self.cross_raw_df = pd.concat([c_df, d_df], ignore_index=True)

            self.cross_df = pd.DataFrame({'ID':[self.img_name, self.img_name],
                                          'type':[self.img_type, self.img_type],
                                          'A_exp':[self.A_exp, self.A_exp],
                                          'D_exp':[self.D_exp, self.D_exp],
                                          'coef':['c', 'd'],
                                          'val':[self.c, self.d],
                                          'sd':[self.c_sd, self.d_sd]})


    def plot_hist(self):
        plt.figure(figsize=(8,8))

        ax0 = plt.subplot(211)
        ax0.hist(self.DD_mean_img.ravel(), bins=256,
                 alpha=.5,label='Ch 0 (CFP-435)', color='r')
        ax0.hist(self.DA_mean_img.ravel(), bins=256,
                 alpha=.5, label='Ch 1 (YFP-435)', color='g')
        ax0.hist(self.AD_mean_img.ravel(), bins=256,
                 alpha=.5, label='Ch 2 (CFP-505)', color='y')
        ax0.hist(self.AA_mean_img.ravel(), bins=256,
                 alpha=.5, label='Ch 3 (YFP-505)', color='b')
        ax0.legend()

        plt.title(f'File {self.img_name}, type {self.img_type}')
        plt.tight_layout()
        plt.show()


    def ff_profile(self):
        plt.figure(figsize=(8,4))

        ax0 = plt.subplot()
        ax0.plot(np.mean(self.DD_img, axis=(1,2)),
                 label='Ch 0 (CFP-435)', color='r')
        ax0.plot(np.mean(self.DA_img, axis=(1,2)),
                 label='Ch 1 (YFP-435)', color='g')
        ax0.plot(np.mean(self.AD_img, axis=(1,2)),
                 label='Ch 2 (CFP-505)', color='y')
        ax0.plot(np.mean(self.AA_img, axis=(1,2)),
                 label='Ch 3 (YFP-505)', color='b')
        ax0.legend()

        plt.title(f'File {self.img_name}, type {self.img_type}')
        plt.tight_layout()
        plt.show()        


    def ch_pic(self):
        int_min = np.min(self.img_raw)
        int_max = np.max(self.img_raw)

        plt.figure(figsize=(10,10))

        ax0 = plt.subplot(221)
        ax0.set_title('DD (Ch.0)')
        img0 = ax0.imshow(self.DD_mean_img, cmap='jet')
        img0.set_clim(vmin=int_min, vmax=int_max)
        div0 = make_axes_locatable(ax0)
        cax0 = div0.append_axes('right', size='3%', pad=0.1)
        plt.colorbar(img0, cax=cax0)
        ax0.axis('off')

        ax1 = plt.subplot(222)
        ax1.set_title('DA (Ch.1)')
        img1 = ax1.imshow(self.DA_mean_img, cmap='jet')
        img1.set_clim(vmin=int_min, vmax=int_max)
        div1 = make_axes_locatable(ax1)
        cax1 = div1.append_axes('right', size='3%', pad=0.1)
        plt.colorbar(img1, cax=cax1)
        ax1.axis('off')

        ax2 = plt.subplot(223)
        ax2.set_title('AD (Ch.2)')
        img2 = ax2.imshow(self.AD_mean_img, cmap='jet')
        img2.set_clim(vmin=int_min, vmax=int_max)
        div2 = make_axes_locatable(ax2)
        cax2 = div2.append_axes('right', size='3%', pad=0.1)
        plt.colorbar(img2, cax=cax2)
        ax2.axis('off')

        ax3 = plt.subplot(224)
        ax3.set_title('AA (Ch.3)')
        img3 = ax3.imshow(self.AA_mean_img, cmap='jet')
        img3.set_clim(vmin=int_min, vmax=int_max)
        div3 = make_axes_locatable(ax3)
        cax3 = div3.append_axes('right', size='3%', pad=0.1)
        plt.colorbar(img3, cax=cax3)
        ax3.axis('off')

        plt.suptitle(f'File {self.img_name}, type {self.img_type}')
        plt.tight_layout()
        plt.show()


class CrossRegSet():
    """ Class processing set of 3-cube FRET method crosstalk calibration registrations

    Requires sets of (A) and (D) registrations

    """
    def __init__(self, data_path, donor_reg_dict, acceptor_reg_dict, trim_frame=-1):
        self.donor_reg = donor_reg_dict
        self.acceptor_reg = acceptor_reg_dict


        self.donor_reg_list = []
        for reg_name in self.donor_reg.keys():
            name_path = data_path + f'{reg_name}.tif'
            self.donor_reg_list.append(CrossReg(data_path=name_path,
                                        data_name=reg_name,
                                        exp_list=self.donor_reg[reg_name],
                                        data_type='D',
                                        trim_frame=trim_frame))
        self.acceptor_reg_list = []
        for reg_name in self.acceptor_reg.keys():
            name_path = data_path + f'{reg_name}.tif'
            self.acceptor_reg_list.append(CrossReg(data_path=name_path,
                                                   data_name=reg_name,
                                                   exp_list=self.acceptor_reg[reg_name],
                                                   data_type='A',
                                                   trim_frame=trim_frame))


    def get_abcd(self, show_pic=False):
        """ Create data frame with calculated crosstalc coeficients for each calibration registration

        """

        self.cross_raw_df = pd.DataFrame(columns=['ID',  # df with raw results
                                                   'type',
                                                   'A_exp',
                                                   'D_exp',
                                                   'frame',
                                                   'coef',
                                                   'val'])

        self.cross_df = pd.DataFrame(columns=['ID',
                                                  'type',
                                                  'A_exp',
                                                  'D_exp',
                                                  'coef',
                                                  'val',
                                                  'sd'])

        for reg in self.acceptor_reg_list + self.donor_reg_list:
            if show_pic:
                reg.ch_pic()
            reg.cross_calc()
            self.cross_raw_df = pd.concat([self.cross_raw_df, reg.cross_raw_df], ignore_index=True)
            self.cross_df = pd.concat([self.cross_df, reg.cross_df], ignore_index=True)

        return self.cross_df
    

# G parameter estimation
class GReg():
    def __init__(self, img_name, pre_img, post_img, coef_list):
        self.img_name = img_name
        self.img_raw = pre_img
        self.img_bleach = post_img

        # self.bleach_frame = bleach_frame
        # self.bleach_exp = bleach_exp
        # self.A_exp = A_exp
        # self.D_exp = D_exp

        self.a = coef_list[0]
        self.b = coef_list[1]
        self.c = coef_list[2]
        self.d = coef_list[3]


        self.DD_img = self.img_raw[:,:,:,0]  # CFP-435  DD
        self.DA_img = self.img_raw[:,:,:,1]  # YFP-435  DA
        self.AD_img = self.img_raw[:,:,:,2]  # CFP-505  AD
        self.AA_img = self.img_raw[:,:,:,3]  # YFP-505  AA

        self.DD_img_post = self.img_bleach[:,:,:,0]
        self.DA_img_post = self.img_bleach[:,:,:,1]
        self.AD_img_post = self.img_bleach[:,:,:,2]
        self.AA_img_post = self.img_bleach[:,:,:,3]


        self.DD_mean_img = np.mean(self.DD_img, axis=0)
        self.DA_mean_img = np.mean(self.DA_img, axis=0)
        self.AD_mean_img = np.mean(self.AD_img, axis=0)
        self.AA_mean_img = np.mean(self.AA_img, axis=0)

        # raw_mask = self.AA_mean_img > filters.threshold_otsu(self.AA_mean_img)
        self.raw_mask = masking.proc_mask(self.AA_mean_img, ext_fin_mask=True, proc_ext=30)
        self.narr_mask = masking.proc_mask(self.AA_mean_img)

        # self.filtered_mask = morphology.erosion(self.narr_mask, footprint=morphology.disk(10))
        # self.filtered_mask = morphology.dilation(self.filtered_mask, footprint=morphology.disk(5))
        # self.filtered_mask = ndi.binary_fill_holes(self.filtered_mask)
        self.filtered_mask = morphology.opening(self.narr_mask, footprint=morphology.disk(10))
        self.filtered_mask = morphology.erosion(self.filtered_mask, footprint=morphology.disk(10))
        self.filtered_mask = morphology.opening(self.filtered_mask, footprint=morphology.disk(5))
        # self.back_mask = morphology.dilation(self.filtered_mask, morphology.disk(3))
        self.mask = self.filtered_mask  # morphology.erosion(self.filtered_mask, footprint=morphology.disk(2))
        self.label = measure.label(self.mask)

        bc_p_m = lambda x: np.array([f - np.percentile(f,1) for f in x]).clip(min=0).astype(np.uint16)

        self.DD_img = bc_p_m(self.DD_img)
        self.DA_img = bc_p_m(self.DA_img)
        self.AD_img = bc_p_m(self.AD_img)
        self.AA_img = bc_p_m(self.AA_img)

        self.DD_img_post = bc_p_m(self.DD_img_post)
        self.DA_img_post = bc_p_m(self.DA_img_post)
        self.AD_img_post = bc_p_m(self.AD_img_post)
        self.AA_img_post = bc_p_m(self.AA_img_post)

        self.Fc_pre = self.__Fc_img(dd_img=self.DD_img,
                                    da_img=self.DA_img,
                                    aa_img=self.AA_img,
                                    a=self.a, b=self.b, c=self.c, d=self.d)
        self.Fc_post = self.__Fc_img(dd_img=self.DD_img_post,
                                     da_img=self.DA_img_post, aa_img=self.AA_img_post,
                                     a=self.a, b=self.b, c=self.c, d=self.d)
        
        self.G_img = self.__G_img(Fc_pre_img=self.Fc_pre, Fc_post_img=self.Fc_post,
                                  dd_pre_img=self.DD_img, dd_post_img=self.DD_img_post,
                                  mask=self.mask)


    @staticmethod
    def __Fc_img(dd_img, da_img, aa_img, a, b, c, d):
        Fc_img = []
        for frame_num in range(dd_img.shape[0]):
            DD_frame = dd_img[frame_num]
            DA_frame = da_img[frame_num]
            AA_frame = aa_img[frame_num]

            Fc_frame = DA_frame - a*(AA_frame - c*DD_frame) - d*(DD_frame - b*AA_frame)
            Fc_frame[Fc_frame < 0] = 0
            Fc_img.append(Fc_frame)

        return np.asarray(Fc_img)
    

    @staticmethod
    def __G_img(Fc_pre_img, Fc_post_img, dd_pre_img, dd_post_img, mask):
        G_img = []
        for frame_num in range(Fc_pre_img.shape[0]):
            Fc_pre_frame = ma.masked_where(~mask, Fc_pre_img[frame_num])
            Fc_post_frame = ma.masked_where(~mask, Fc_post_img[frame_num])
            DD_pre_frame = ma.masked_where(~mask, dd_pre_img[frame_num])
            DD_post_frame = ma.masked_where(~mask, dd_post_img[frame_num])

            G_frame = (Fc_pre_frame - Fc_post_frame) / (DD_post_frame - DD_pre_frame)
            G_img.append(G_frame)
        
        return np.asarray(G_img)
        

    def G_fit_frames(self, bad_rois):
        # https://realpython.com/linear-regression-in-python/)
        DD_delta_arr = np.asarray([])
        Fc_delta_arr = np.asarray([])
        
        fig, ax = plt.subplots(layout="constrained", figsize=(10, 4))
        fig.suptitle(f'{self.img_name}: G parameter estimation by frames')
        
        for label_num in range(1, np.max(self.label)+1):
            label_mask = self.label == label_num

            DD_delta = np.mean(self.DD_img_post, axis=(1,2), where=label_mask) - \
                       np.mean(self.DD_img, axis=(1,2), where=label_mask)
            
            Fc_delta = np.mean(self.Fc_pre, axis=(1,2), where=label_mask) - \
                       np.mean(self.Fc_post, axis=(1,2), where=label_mask)



            if label_num in bad_rois:
                ax.scatter(x=DD_delta,y=Fc_delta, label=label_num, alpha=.5, marker='x')
            else:
                ax.scatter(x=DD_delta,y=Fc_delta, label=label_num, alpha=.5)

                DD_delta_arr = np.concatenate((DD_delta_arr, DD_delta))
                Fc_delta_arr = np.concatenate((Fc_delta_arr, Fc_delta))

        # slope, intercept, r, p, std_err = stats.linregress(DD_delta_arr, Fc_delta_arr)
        # lin_mod = lambda x: slope*x + intercept

        lin_mod_data = stats.linregress(DD_delta_arr, Fc_delta_arr)
        slope, p_slope, std_err_slope = lin_mod_data.slope, lin_mod_data.pvalue, lin_mod_data.stderr
        intercept, std_err_intercept = lin_mod_data.intercept, lin_mod_data.intercept_stderr
        r = lin_mod_data.rvalue

        p_t_calc = lambda m,s,l: 2*stats.t.sf(abs(m/s), (1.0*l - 2))
        p_intercept = p_t_calc(intercept, std_err_intercept, len(DD_delta_arr))

        lin_mod = lambda x: slope*x + intercept


        ax.plot(DD_delta_arr, list(map(lin_mod, DD_delta_arr)),
                 color='k', linestyle='--')
        ax.set_title(f'G={round(slope,3)}+/-{round(std_err_slope,3)} (p={round(p_slope,4)}), inter.={round(intercept,1)}+/-{round(std_err_slope,3)} (p={round(p_intercept,4)}), R^2={round(r,4)}')
        ax.set_xlabel('Δ DD, a.u.')
        ax.set_ylabel('Δ Fc, a.u.')
        ax.legend()

        plt.show()


    def G_fit_px(self, frame_num=0, bad_rois=[]):
        DD_delta_frame_arr = np.asarray([])
        Fc_delta_frame_arr = np.asarray([])
        
        fig, ax = plt.subplots(layout="constrained", figsize=(10, 4))
        fig.suptitle(f'{self.img_name}: G parameter estimation pixel-wise (frame {frame_num})')
        
        DD_delta_frame = self.DD_img_post[frame_num] - np.minimum(self.DD_img[frame_num], self.DD_img_post[frame_num])  
        Fc_delta_frame = self.Fc_pre[frame_num] - np.minimum(self.Fc_post[frame_num], self.Fc_pre[frame_num]) 
        for label_num in range(1, np.max(self.label)+1):
            label_mask = self.label == label_num

            DD_delta = ma.masked_where(label_mask, DD_delta_frame).compressed()
            Fc_delta = ma.masked_where(label_mask, Fc_delta_frame).compressed()

            delta_zeros = np.array([any(t) for t in zip(DD_delta<=0, Fc_delta<=0)], dtype=np.bool_)
            DD_delta, Fc_delta = DD_delta[~delta_zeros], Fc_delta[~delta_zeros]

            if label_num in bad_rois:
                continue
            else:
                ax.scatter(x=DD_delta,y=Fc_delta, label=label_num,
                           alpha=.1, s=0.075)

                DD_delta_arr = np.concatenate((DD_delta_frame_arr, DD_delta))
                Fc_delta_arr = np.concatenate((Fc_delta_frame_arr, Fc_delta))

        # slope, intercept, r, p_slope, std_err = stats.linregress(DD_delta_arr, Fc_delta_arr)

        lin_mod_data = stats.linregress(DD_delta_arr, Fc_delta_arr)
        slope, p_slope, std_err_slope = lin_mod_data.slope, lin_mod_data.pvalue, lin_mod_data.stderr
        intercept, std_err_intercept = lin_mod_data.intercept, lin_mod_data.intercept_stderr
        r = lin_mod_data.rvalue

        p_t_calc = lambda m,s,l: 2*stats.t.sf(abs(m/s), (1.0*l - 2))
        p_intercept = p_t_calc(intercept, std_err_intercept, len(DD_delta_arr))

        lin_mod = lambda x: slope*x + intercept

        ax.plot(DD_delta_arr, list(map(lin_mod, DD_delta_arr)),
                 color='k', linestyle='--')
        ax.set_title(f'G={round(slope,3)}+/-{round(std_err_slope,3)} (p={round(p_slope,4)}), inter.={round(intercept,1)}+/-{round(std_err_slope,3)} (p={round(p_intercept,4)}), R^2={round(r,4)}')
        ax.set_xlabel('Δ DD, a.u.')
        ax.set_ylabel('Δ Fc, a.u.')
        plt.show()


    def mask_mean_overlay(self, sel_img='Fc_pre'):
        if sel_img == 'Fc_pre':
            img_mean = np.mean(self.Fc_pre, axis=0)
        elif sel_img == 'Fc_post':
            img_mean = np.mean(self.Fc_post, axis=0)
        elif sel_img == 'G':
            img_mean = np.mean(self.G_img, axis=0)
        elif sel_img == 'AA':
            img_mean = np.mean(self.AA_img, axis=0)

        cell_contour = measure.find_contours(self.mask, level=0.5)
        plt.figure(figsize=(10,10))

        ax0 = plt.subplot()
        ax0.set_title(f'{self.img_name} {sel_img}')
        img0 = ax0.imshow(img_mean, cmap='jet')
        div0 = make_axes_locatable(ax0)
        cax0 = div0.append_axes('right', size='3%', pad=0.1)
        ax0.axis('off')
        for ce_c in cell_contour:
            ax0.plot(ce_c[:, 1], ce_c[:, 0], linewidth=1.5, color='w')
        for region in measure.regionprops(self.label):
            txt0 = ax0.text(region.centroid[1], region.centroid[0], region.label, color='green', fontsize=20)
            txt0.set_path_effects([PathEffects.withStroke(linewidth=3, foreground='w')])
        plt.colorbar(img0, cax=cax0)
        plt.tight_layout()
        plt.show()    


    def prof_plot(self):
        plt.figure(figsize=(10,5))

        ax0 = plt.subplot()
        ax0.plot(np.mean(self.DD_img, axis=(1,2), where=self.mask),
                 label='DD', color='r', marker='.')
        ax0.plot(np.mean(self.DD_img_post, axis=(1,2), where=self.mask),
                 label='DD post', color='r', linestyle='--', marker='.')

        ax0.plot(np.mean(self.DA_img, axis=(1,2), where=self.mask),
                 label='DA', color='g', marker='.')
        ax0.plot(np.mean(self.DA_img_post, axis=(1,2), where=self.mask),
                 label='DA post', color='g', linestyle='--', marker='.')

        # ax0.plot(np.mean(self.AD_img, axis=(1,2), where=self.mask),
        #          label='AD', color='y', marker='.')
        # ax0.plot(np.mean(self.AD_img_post, axis=(1,2), where=self.mask),
        #          label='AD post', color='y', linestyle='--', marker='.')

        ax0.plot(np.mean(self.AA_img, axis=(1,2), where=self.mask),
                 label='AA', color='b', marker='.')
        ax0.plot(np.mean(self.AA_img_post, axis=(1,2), where=self.mask),
                 label='AA post', color='b', linestyle='--', marker='.')

        ax0.plot(np.mean(self.Fc_pre, axis=(1,2), where=self.mask),
                 label='Fc', color='m', marker='.')
        ax0.plot(np.mean(self.Fc_post, axis=(1,2), where=self.mask),
                 label='Fc post', color='m', linestyle='--', marker='.')

        ax0.set_xlabel('Frame num')
        ax0.set_ylabel('I, a.u.')
        ax0.legend()
        plt.suptitle(f'{self.img_name} profiles')
        plt.tight_layout()
        plt.show()


    # def Fc_DD_pic(self):
    #     plt.figure(figsize=(10,4))
    #     for label_num in range(1, np.max(self.label)+1):
    #         label_mask = self.label == label_num

    #         # DD_delta = np.mean(self.DD_img_post - self.DD_img,
    #         #                    axis=(1,2), where=label_mask)
            
    #         DD_delta = np.mean(self.DD_img_post, axis=(1,2), where=label_mask) - \
    #                    np.mean(self.DD_img, axis=(1,2), where=label_mask)
            
    #         Fc_delta = np.mean(self.Fc_pre, axis=(1,2), where=label_mask) - \
    #                    np.mean(self.Fc_post, axis=(1,2), where=label_mask)

    #         plt.scatter(x=DD_delta,y=Fc_delta, label=label_num, alpha=.5)
    #     plt.xlabel('Δ DD, a.u.')
    #     plt.ylabel('Δ Fc, a.u.')
    #     plt.legend()
    #     plt.title(f'{self.img_name}')
    #     plt.tight_layout()
    #     plt.show()


    # def G_calc_frame(self, calc_win:list[int,int]=[10,-10]):        
    #     _,self.G_prof_arr = masking.label_prof_arr(input_label=self.label,
    #                                                input_img_series=self.G_img)

    #     self.G_profile = np.mean(self.G_prof_arr, axis=0)  # np.mean(self.G_img, axis=(1,2), where=self.mask)
    #     self.G_profile_sd = np.std(self.G_prof_arr, axis=0)  # np.std(self.G_img, axis=(1,2), where=self.mask)
    #     self.G = np.mean(self.G_profile[calc_win[0]:calc_win[1]])
    #     self.G_sd = np.std(self.G_profile[calc_win[0]:calc_win[1]])

    #     self.G_df = pd.DataFrame({'ID':self.img_name,
    #                               'A_exp':self.A_exp,
    #                               'D_exp':self.D_exp,
    #                               'val':self.G,
    #                               'sd':self.G_sd}, index=[0])


    # def Fc_plot(self, raw_frames=-1, post_frames=-1):
    #     Fc_pre_mean = np.mean(self.Fc_pre[:raw_frames], axis=0)
    #     Fc_post_mean = np.mean(self.Fc_post[:post_frames], axis=0)

    #     plt.figure(figsize=(10,5))

    #     ax0 = plt.subplot(221)
    #     ax0.set_title('Fc pre mean')
    #     img0 = ax0.imshow(ma.masked_where(~self.mask, Fc_pre_mean), cmap='jet')
    #     # img0.set_clim(vmin=int_min, vmax=int_max)
    #     div0 = make_axes_locatable(ax0)
    #     cax0 = div0.append_axes('right', size='3%', pad=0.1)
    #     plt.colorbar(img0, cax=cax0)
    #     ax0.axis('off')

    #     ax1 = plt.subplot(222)
    #     ax1.set_title('Fc pre profiles')
    #     ax1.plot(np.mean(self.Fc_pre, axis=(1,2), where=self.mask),
    #              label='Fc', color='m', marker='.')
    #     ax1.plot(np.mean(self.DA_img, axis=(1,2), where=self.mask),
    #              label='DA', color='g', linestyle='--', marker='.')
    #     ax1.plot(np.mean(self.DD_img, axis=(1,2), where=self.mask),
    #              label='DD', color='r', linestyle=':', marker='.')
    #     ax1.legend()

    #     ax2 = plt.subplot(223)
    #     ax2.set_title('Fc post mean')
    #     img2 = ax2.imshow(ma.masked_where(~self.mask, Fc_post_mean), cmap='jet')
    #     # img0.set_clim(vmin=int_min, vmax=int_max)
    #     div2 = make_axes_locatable(ax2)
    #     cax2 = div2.append_axes('right', size='3%', pad=0.1)
    #     plt.colorbar(img2, cax=cax2)
    #     ax2.axis('off')

    #     ax3 = plt.subplot(224)
    #     ax3.set_title('Fc post profiles')
    #     ax3.axhline(y=0, color='black')
    #     ax3.plot(np.mean(self.Fc_post, axis=(1,2), where=self.mask),
    #              label='Fc', color='m', marker='.')
    #     ax3.plot(np.mean(self.DA_img_post, axis=(1,2), where=self.mask),
    #              label='DA', color='g', linestyle='--', marker='.')
    #     ax3.plot(np.mean(self.DD_img_post, axis=(1,2), where=self.mask),
    #              label='DD', color='r', linestyle=':', marker='.')
    #     ax3.legend()

    #     plt.suptitle(f'{self.img_name}')
    #     plt.tight_layout()
    #     plt.show()


    def pre_post_plot(self):
        plt.figure(figsize=(10,5))

        ax0 = plt.subplot(221)
        ax0.set_title('DD (Ch.0)')
        ax0.plot(np.mean(self.DD_img, axis=(1,2), where=self.mask),
                 label='pre', color='r', marker='.')
        ax0.plot(np.mean(self.DD_img_post, axis=(1,2), where=self.mask),
                 label='post', color='r', linestyle='--', marker='.')
        ax0.legend()

        ax1 = plt.subplot(222)
        ax1.set_title('DA (Ch.1)')
        ax1.plot(np.mean(self.DA_img, axis=(1,2), where=self.mask),
                 label='pre', color='g', marker='.')
        ax1.plot(np.mean(self.DA_img_post, axis=(1,2), where=self.mask),
                 label='post', color='g', linestyle='--', marker='.')
        ax1.legend()

        ax2 = plt.subplot(223)
        ax2.set_title('AD (Ch.2)')
        ax2.plot(np.mean(self.AD_img, axis=(1,2), where=self.mask),
                 label='pre', color='y', marker='.')
        ax2.plot(np.mean(self.AD_img_post, axis=(1,2), where=self.mask),
                 label='post', color='y', linestyle='--', marker='.')
        ax2.legend()

        ax3 = plt.subplot(224)
        ax3.set_title('AA (Ch.3)')
        ax3.plot(np.mean(self.AA_img, axis=(1,2), where=self.mask),
                 label='pre', color='b', marker='.')
        ax3.plot(np.mean(self.AA_img_post, axis=(1,2), where=self.mask),
                 label='post', color='b', linestyle='--', marker='.')
        ax3.legend()
        
        plt.suptitle(f'Registration {self.img_name}')
        plt.tight_layout()
        plt.show()


    def ch_pic(self):
        int_min = np.min(self.img_raw)
        int_max = np.max(self.img_raw)


        plt.figure(figsize=(10,10))

        ax0 = plt.subplot(221)
        ax0.set_title('DD (Ch.0)')
        img0 = ax0.imshow(self.DD_mean_img, cmap='jet')
        img0.set_clim(vmin=int_min, vmax=int_max)
        div0 = make_axes_locatable(ax0)
        cax0 = div0.append_axes('right', size='3%', pad=0.1)
        plt.colorbar(img0, cax=cax0)
        ax0.axis('off')

        ax1 = plt.subplot(222)
        ax1.set_title('DA (Ch.1)')
        img1 = ax1.imshow(self.DA_mean_img, cmap='jet')
        img1.set_clim(vmin=int_min, vmax=int_max)
        div1 = make_axes_locatable(ax1)
        cax1 = div1.append_axes('right', size='3%', pad=0.1)
        plt.colorbar(img1, cax=cax1)
        ax1.axis('off')

        ax2 = plt.subplot(223)
        ax2.set_title('AD (Ch.2)')
        img2 = ax2.imshow(self.AD_mean_img, cmap='jet')
        img2.set_clim(vmin=int_min, vmax=int_max)
        div2 = make_axes_locatable(ax2)
        cax2 = div2.append_axes('right', size='3%', pad=0.1)
        plt.colorbar(img2, cax=cax2)
        ax2.axis('off')

        ax3 = plt.subplot(224)
        ax3.set_title('AA (Ch.3)')
        img3 = ax3.imshow(self.AA_mean_img, cmap='jet')
        img3.set_clim(vmin=int_min, vmax=int_max)
        div3 = make_axes_locatable(ax3)
        cax3 = div3.append_axes('right', size='3%', pad=0.1)
        plt.colorbar(img3, cax=cax3)
        ax3.axis('off')

        plt.suptitle(f'Registration {self.img_name}')
        plt.tight_layout()
        plt.show()


    def G_plot_by_label(self):
        plt.figure(figsize=(10,4))
        for label_num in range(1, np.max(self.label)+1):
            label_mask = self.label == label_num

            label_prof_mean = np.mean(self.G_img, axis=(1,2), where=label_mask)
            label_prof_sd = np.std(self.G_img, axis=(1,2), where=label_mask)

            plt.errorbar(list(range(label_prof_mean.shape[0])), label_prof_mean,
                        yerr = label_prof_sd,
                        fmt ='-o', capsize=2, label=label_num, alpha=.75)
            plt.hlines(y=np.median(label_prof_mean),
                                xmin=0, xmax=label_prof_mean.shape[0],
                                linestyles='--')

        plt.legend()
        plt.tight_layout()
        plt.show()


    def G_report_pic(self):
        pass

class GRegSet():
        def __init__(self, data_path, tandem_reg_dict, **kwargs):
            self.tandem_reg_list = []  # [raw reg, post reg, bleach frames, bleach exp, 435 exp, 505 exp]
            for reg_name in tandem_reg_dict.keys():
                reg_params = tandem_reg_dict[reg_name]
                raw_path = data_path + f'{reg_params[0]}.tif'
                bleach_path = data_path + f'{reg_params[1]}.tif'
                self.tandem_reg_list.append(GReg(img_name=reg_name,
                                                 raw_path=raw_path,
                                                 bleach_path=bleach_path,
                                                 bleach_frame=reg_params[2],
                                                 bleach_exp=reg_params[3],
                                                 A_exp=reg_params[4],
                                                 D_exp=reg_params[5],
                                                 **kwargs))


        def G_calc(self, bad_label:list[int,...]):
            self.G_df =  self.get_G(reg_list=self.tandem_reg_list)


        def G_fit_pic(self):
            for reg in self.tandem_reg_list:
                reg.Fc_DD_pic()

        def G_calc_fit(self, **kwargs):
            for reg in self.tandem_reg_list:
                reg.G_calc_fit(**kwargs)


        @ staticmethod
        def get_G(reg_list):
            """ Create data frame with calculated crosstalc coeficients for each calibration registration

            """
            G_df = pd.DataFrame(columns=['ID',
                                         'A_exp',
                                         'D_exp',
                                         'val',
                                         'sd'])

            for reg in reg_list:
                reg.G_calc_frame()
                G_df = pd.concat([G_df, reg.G_df], ignore_index=True)

            return G_df


        def draw_pic(self):
            """ Return selected plotting methods results
            Requires previous execution of 'get_G'
            
            """
            for reg in self.tandem_reg_list:
                reg.Fc_plot()
                reg.pre_post_plot()
                reg.G_plot()
                reg.G_plot_by_label()