""" Module for predicting anisotropy with single source populations.

"""

import numpy as np
import matplotlib as plt
import matplotlib.cm as cm

import kalepy as kale
import healpy as hp
import h5py

import holodeck as holo
from holodeck import utils, cosmo, log, detstats
from holodeck.constants import YR

NSIDE = 32
NPIX = hp.nside2npix(NSIDE)
LMAX = 8
HC_REF15_10YR = 11.2*10**-15 

def healpix_map(hc_ss, hc_bg, nside=NSIDE):
    """ Build mollview array of strains for a healpix map
    
    Parameters
    ----------
    hc_ss : (F,R,L) NDarray
        Characteristic strain of single sources.
    hc_bg : (F,R) NDarray
        Characteristic strain of the background.
    nside : integer
        number of sides for healpix map.

    Returns
    -------
    moll_hc : (NPIX,) 1Darray
        Array of strain at every pixel for a mollview healpix map.
    
    NOTE: Could speed up the for-loops, but it's ok for now.
    """

    npix = hp.nside2npix(nside)
    nfreqs = len(hc_ss)
    nreals = len(hc_ss[0])
    nloudest = len(hc_ss[0,0])

    # spread background evenly across pixels in moll_hc
    moll_hc = np.ones((nfreqs,nreals,npix)) * hc_bg[:,:,np.newaxis]/np.sqrt(npix) # (frequency, realization, pixel)

    # choose random pixels to place the single sources
    pix_ss = np.random.randint(0, npix-1, size=nfreqs*nreals*nloudest).reshape(nfreqs, nreals, nloudest)
    for ff in range(nfreqs):
        for rr in range(nreals):
            for ll in range(nloudest):
                moll_hc[ff,rr,pix_ss[ff,rr,ll]] = np.sqrt(moll_hc[ff,rr,pix_ss[ff,rr,ll]]**2
                                                          + hc_ss[ff,rr,ll]**2)
                
    return moll_hc

def sph_harm_from_map(moll_hc, lmax=LMAX):
    """ Calculate spherical harmonics from strains at every pixel of 
    a healpix mollview map.
    
    Parameters
    ----------
    moll_hc : (F,R,NPIX,) 1Darray
        Characteristic strain of each pixel of a healpix map.
    lmax : int
        Highest harmonic to calculate.

    Returns
    -------
    Cl : (F,R,lmax+1) NDarray
        Spherical harmonic coefficients 
        
    """
    nfreqs = len(moll_hc)
    nreals = len(moll_hc[0])

    Cl = np.zeros((nfreqs, nreals, lmax+1))
    for ff in range(nfreqs):
        for rr in range(nreals):
            Cl[ff,rr,:] = hp.anafast(moll_hc[ff,rr], lmax=lmax)

    return Cl

def sph_harm_from_hc(hc_ss, hc_bg, nside = NSIDE, lmax = LMAX):
    """ Calculate spherical harmonics and strain at every pixel
    of a healpix mollview map from single source and background char strains.

    Parameters
    ----------
    hc_ss : (F,R,L) NDarray
        Characteristic strain of single sources.
    hc_bg : (F,R) NDarray
        Characteristic strain of the background.
    nside : integer
        number of sides for healpix map.

    Returns
    -------
    moll_hc : (F,R,NPIX,) 2Darray
        Array of strain at every pixel for a mollview healpix map.
    Cl : (F,R,lmax+1) NDarray
        Spherical harmonic coefficients 
    
    """
    moll_hc = healpix_map(hc_ss, hc_bg, nside)
    Cl = sph_harm_from_map(moll_hc, lmax)

    return moll_hc, Cl


######################################################################
############# Plots
######################################################################

def plot_ClC0_medians(fobs, Cl_best, lmax, nshow):
    xx = fobs*YR
    fig, ax = holo.plot.figax(figsize=(8,5), xlabel=holo.plot.LABEL_GW_FREQUENCY_YR, ylabel='$C_{\ell>0}/C_0$')

    yy = Cl_best[:,:,:,1:]/Cl_best[:,:,:,0,np.newaxis] # (B,F,R,l)
    yy = np.median(yy, axis=-1) # (B,F,l) median over realizations

    colors = cm.gist_rainbow(np.linspace(0, 1, lmax))
    for ll in range(lmax):
        ax.plot(xx, np.median(yy[:,:,ll], axis=0), color=colors[ll], alpha=0.75, label='$l=%d$' % (ll+1))
        for pp in [50, 98]:
            percs = pp/2
            percs = [50-percs, 50+percs]
            ax.fill_between(xx, *np.percentile(yy[:,:,ll], percs, axis=0), alpha=0.1, color=colors[ll])
        
        for bb in range(0,nshow):
            ax.plot(xx, yy[bb,:,ll], color=colors[ll], linestyle=':', alpha=0.1,
                                 linewidth=1)         
        ax.legend(ncols=2)
    holo.plot._twin_hz(ax, nano=False)
    
    # ax.set_title('50%% and 98%% confidence intervals of the %d best samples \nusing realizations medians, lmax=%d'
    #             % (nbest, lmax))
    return fig


######################################################################
############# Libraries
######################################################################


def lib_anisotropy(lib_path, hc_ref_10yr=HC_REF15_10YR, nbest=100, nreals=50, lmax=LMAX, nside=NSIDE):

    # ---- read in file
    hdf_name = lib_path+'/sam_lib.hdf5'
    print('Hdf file:', hdf_name)

    ss_file = h5py.File(hdf_name, 'r')
    print('Loaded file, with keys:', list(ss_file.keys()))
    hc_ss = ss_file['hc_ss'][:,:,:nreals,:]
    hc_bg = ss_file['hc_bg'][:,:,:nreals]
    fobs = ss_file['fobs'][:]
    ss_file.close()

    shape = hc_ss.shape
    nsamps, nfreqs, nreals, nloudest = shape[0], shape[1], shape[2], shape[3]
    print('N,F,R,L =', nsamps, nfreqs, nreals, nloudest)


     # ---- rank samples
    nsort, fidx, hc_tt, hc_ref = detstats.rank_samples(hc_ss, hc_bg, fobs, fidx=1, hc_ref=hc_ref_10yr, ret_all=True)
    
    print('Ranked samples by hc_ref = %.2e at fobs = %.2f/yr' % (hc_ref, fobs[fidx]*YR))


    # ---- calculate spherical harmonics

    npix = hp.nside2npix(nside)
    Cl_best = np.zeros((nbest, nfreqs, nreals, lmax+1 ))
    moll_hc_best = np.zeros((nbest, nfreqs, nreals, npix))
    for nn in range(nbest):
        print('on nn=%d out of nbest=%d' % (nn,nbest))
        moll_hc_best[nn,...], Cl_best[nn,...] = sph_harm_from_hc(
            hc_ss[nsort[nn]], hc_bg[nsort[nn]], nside=nside, lmax=lmax, )
        

    # ---- save to npz file

    output_dir = lib_path+'/anisotropy'
    # Assign output folder
    import os
    if (os.path.exists(output_dir) is False):
        print('Making output directory.')
        os.makedirs(output_dir)
    else:
        print('Writing to an existing directory.')

    output_name = output_dir+'/sph_harm_lmax%d_nside%d_nbest%d.npz' % (lmax, nside, nbest)
    print('Saving npz file: ', output_name)
    np.savez(output_name,
             nsort=nsort, fidx=fidx, hc_tt=hc_tt, hc_ref=hc_ref, ss_shape=shape,
         moll_hc_best=moll_hc_best, Cl_best=Cl_best, nside=nside, lmax=lmax, fobs=fobs)
    

    # ---- plot median Cl/C0
    
    print('Plotting Cl/C0 for median realizations')
    fig = plot_ClC0_medians(fobs, Cl_best, lmax, nshow=nbest)
    fig_name = output_dir+'/sph_harm_lmax%d_nside%d_nbest%d.png' % (lmax, nside, nbest)
    fig.savefig(fig_name, dpi=300)





######################################################################
############# Analytic/Sato-Polito
######################################################################

def Cl_analytic_from_num(fobs_orb_edges, number, hs, realize = False):
    """ Calculate Cl using Eq. (17) of Sato-Polito & Kamionkowski
    Parameters
    ----------
    fobs_orb_edges : (F,) 1Darray
        Observed orbital frequency bin edges
    hs : (M,Q,Z,F) NDarray
        Strain amplitude of each M,q,z bin
    number : (M,Q,Z,F) NDarray
        Number of sources in each M,q,z, bin
    realize : boolean or integer
        How many realizations to Poisson sample.
    
    Returns
    -------
    C0 : (F,R) or (F,) NDarray
        C_0 
    Cl : (F,R) or (F,) NDarray
        C_l>0 for arbitrary l using shot noise approximation
    """

    df = np.diff(fobs_orb_edges)                 #: frequency bin widths
    fc = kale.utils.midpoints(fobs_orb_edges)    #: frequency-bin centers 

    # df = fobs_orb_widths[np.newaxis, np.newaxis, np.newaxis, :] # (M,Q,Z,F) NDarray
    # fc = fobs_orb_cents[np.newaxis, np.newaxis, np.newaxis, :]  # (M,Q,Z,F) NDarray


    # Poisson sample number in each bin
    if utils.isinteger(realize):
        number = np.random.poisson(number[...,np.newaxis], 
                                size = (number.shape + (realize,)))
        df = df[...,np.newaxis]
        fc = fc[...,np.newaxis]
        hs = hs[...,np.newaxis]
    elif realize is True:
        number = holo.gravwaves.poisson_as_needed(number)



    delta_term = (fc/(4*np.pi*df) * np.sum(number*hs**2, axis=(0,1,2)))**2

    Cl = (fc/(4*np.pi*df))**2 * np.sum(number*hs**4, axis=(0,1,2))

    C0 = Cl + delta_term

    return C0, Cl



