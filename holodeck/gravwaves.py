"""
"""

import numpy as np
import tqdm

from holodeck import utils, cosmo
from holodeck.constants import SPLC, MPC, MSOL

# import zcode.math as zmath    # FIX: REMOVE


_CALC_MC_PARS = ['mass', 'sepa', 'dadt', 'time', 'eccen']


class Grav_Waves:

    def __init__(self, bin_evo, freqs, nharms=30, nreals=100):
        self.freqs = freqs
        self.nharms = nharms
        self.nreals = nreals
        self._bin_evo = bin_evo
        return


class GW_Discrete(Grav_Waves):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._box_vol_cgs = self._bin_evo._sample_volume
        return

    def emit(self, eccen=None, stats=False, progress=True, nloudest=5):
        freqs = self.freqs
        nharms = self.nharms
        nreals = self.nreals
        bin_evo = self._bin_evo
        box_vol = self._box_vol_cgs

        if eccen is None:
            eccen = (bin_evo.eccen is not None)

        if eccen not in [True, False]:
            raise ValueError("`eccen` '{}' is invalid!".format(eccen))

        eccen_fore = np.zeros((freqs.size, nreals))
        eccen_back = np.zeros((freqs.size, nreals))
        eccen_both = np.zeros((freqs.size, nreals))
        circ_fore = np.zeros((freqs.size, nreals))
        circ_back = np.zeros((freqs.size, nreals))
        circ_both = np.zeros((freqs.size, nreals))
        loudest = np.zeros((freqs.size, nloudest, nreals))
        sa_eccen = np.zeros_like(freqs)
        sa_circ = np.zeros_like(freqs)

        if eccen:
            harm_range = range(1, nharms+1)
        else:
            harm_range = [2]

        for ii, fobs in tqdm.tqdm(enumerate(freqs), total=len(freqs)):
            rv = _calc_mc_at_fobs(
                fobs, harm_range, nreals, bin_evo, box_vol,
                loudest=nloudest
            )
            mc_ecc, mc_circ, ret_sa_ecc, ret_sa_circ, loud = rv
            eccen_fore[ii, :] = mc_ecc[0]
            eccen_back[ii, :] = mc_ecc[1]
            eccen_both[ii, :] = mc_ecc[2]
            circ_fore[ii, :] = mc_circ[0]
            circ_back[ii, :] = mc_circ[1]
            circ_both[ii, :] = mc_circ[2]
            sa_eccen[ii] = ret_sa_ecc
            sa_circ[ii] = ret_sa_circ
            loudest[ii, :] = loud

        self.eccen_fore = np.sqrt(eccen_fore)
        self.eccen_back = np.sqrt(eccen_back)
        self.eccen_both = np.sqrt(eccen_both)

        self.circ_fore = np.sqrt(circ_fore)
        self.circ_back = np.sqrt(circ_back)
        self.circ_both = np.sqrt(circ_both)

        self.sa_eccen = np.sqrt(sa_eccen)
        self.sa_circ = np.sqrt(sa_circ)
        self.loudest = np.sqrt(loudest)

        return


class GW_Continuous(Grav_Waves):

    # def __init__(self, *args, **kwargs):
    #     super().__init__(*args, **kwargs)
    #     return

    def emit(self, eccen=None, stats=False, progress=True, nloudest=5):
        freqs = self.freqs
        # nharms = self.nharms
        # nreals = self.nreals
        bin_evo = self._bin_evo
        bin_pop = bin_evo._bin_pop
        weight = bin_pop.weight
        dm = np.log10(bin_pop._mtot[1]/MSOL) - np.log10(bin_pop._mtot[0]/MSOL)
        dq = bin_pop._mrat[1] - bin_pop._mrat[0]
        dz = bin_pop._redz[1] - bin_pop._redz[0]

        # (N,) ==> (1, N)    for later conversion to (F, N)
        m1, m2 = [mm[np.newaxis, :] for mm in bin_pop.mass.T]

        H0 = cosmo.H0*1e5 / MPC   # convert from [km/s/Mpc] to [1/s]
        redz = cosmo._a_to_z(bin_pop.time)                     # (N,)
        redz = np.clip(redz, 0.1, None)
        # print(f"redz={zmath.stats_str(redz)}")
        dlum = cosmo.luminosity_distance(redz).cgs.value
        # print(f"dlum={zmath.stats_str(dlum)}")
        dzdt = H0 * cosmo.efunc(redz) * np.square(1.0 + redz)  # (N,)
        # print(f"dzdt={zmath.stats_str(dzdt)}")

        frest = freqs[:, np.newaxis] / (1.0 + redz[np.newaxis, :])  # (F, N)
        # print(f"frest={zmath.stats_str(frest)}")
        dtr_dlnfr = frest / utils.gw_hardening_rate_dfdt(m1, m2, frest)  # (F, N)
        # print(f"dtr_dlnfr={zmath.stats_str(dtr_dlnfr)}")

        mchirp = utils.chirp_mass(m1, m2)
        # print(f"frest={zmath.stats_str(frest)}")
        # Calculate source-strain for each source (h;  NOT characteristic strain)
        strain = utils.gw_strain_source(mchirp, dlum[np.newaxis, :], frest)  # (F, N)
        # print(f"hs={zmath.stats_str(hs)}")

        time_fac = dzdt * dtr_dlnfr
        # print(f"time_fac={zmath.stats_str(time_fac)}")
        # Calculate characteristic-strain (squared)
        strain = weight[np.newaxis, :] * time_fac * strain**2
        # print(f"strain={zmath.stats_str(strain)}")

        dvol = dm * dq * dz
        # dvol = 1.0
        # print(f"{dvol=:.2e}")
        # print(f"numbers = {zmath.stats_str(dvol*weight)}")
        # print(f"number  = {np.sum(dvol*weight):.2e}")

        strain = np.sqrt(np.sum(strain * dvol, axis=1))
        # print(f"hc={zmath.stats_str(strain)}")

        return strain


def _calc_mc_at_fobs(fobs, harm_range, nreals, bin_evo, box_vol, loudest=5):
    """
    """

    # ---- Interpolate data to all harmonics of this frequency
    harm_range = np.asarray(harm_range)
    # Each parameter will be (N, H) = (binaries, harmonics)
    data_harms = bin_evo.at('fobs', fobs / harm_range, pars=_CALC_MC_PARS)

    # Only examine binaries reaching the given locations before redshift zero (other redz=inifinite)
    redz = data_harms['time']
    redz = utils.a_to_z(redz)
    valid = np.isfinite(redz) & (redz > 0.0)

    # Broadcast harmonics numbers to correct shape
    harms = np.ones_like(redz, dtype=int) * harm_range[np.newaxis, :]
    # Select the elements corresponding to the n=2 (circular) harmonic, to use later
    sel_n2 = np.zeros_like(redz, dtype=bool)
    sel_n2[(harms == 2)] = 1
    # Select only the valid elements, also converts to 1D, i.e. (N, H) ==> (V,)
    sel_n2 = sel_n2[valid]
    harms = harms[valid]
    redz = redz[valid]
    # If there are eccentricities, calculate the freq-dist-function
    eccen = data_harms['eccen']
    if eccen is None:
        gne = 1
    else:
        gne = utils.gw_freq_dist_func(harms, ee=eccen[valid])
        # BUG: FIX: NOTE: this fails for zero eccentricities (at times?) fix manually!
        # sel_e0 = (eccen[valid] == 0.0)
        sel_e0 = (eccen[valid] < 1e-8)
        gne[sel_e0] = 0.0
        gne[sel_n2 & sel_e0] = 1.0

    # Calculate required parameters for valid binaries (V,)
    dlum = cosmo.z_to_dlum(redz)
    zp1 = redz + 1
    frst_orb = fobs * zp1 / harms
    mchirp = data_harms['mass'][valid]
    mchirp = utils.chirp_mass(*mchirp.T)
    # NOTE: `dadt` is stored as positive values
    dfdt = utils.dfdt_from_dadt(
        -data_harms['dadt'][valid], data_harms['sepa'][valid], freq_orb=frst_orb)
    _tres = frst_orb / dfdt

    # Calculate strains from each source
    hs2 = utils.gw_strain_source(mchirp, dlum, frst_orb)**2
    # Calculate resampling factors
    vfac = 4.0*np.pi*SPLC * dlum**2 / box_vol   # * thub
    tfac = _tres  # / thub

    # Calculate weightings
    #    Sesana+08, Eq.10
    num_frac = vfac * tfac * zp1
    num_pois = np.random.poisson(num_frac, (nreals, num_frac.size)).T

    # --- Calculate GW Signals
    temp = hs2 * gne * (2.0 / harms)**2
    mc_ecc_both = np.sum(temp[:, np.newaxis] * num_pois, axis=0)
    mc_circ_both = np.sum(temp[:, np.newaxis] * num_pois * sel_n2[:, np.newaxis], axis=0)

    sa_ecc = np.sum(temp * num_frac, axis=0)
    sa_circ = np.sum(temp * num_frac * sel_n2, axis=0)

    if np.count_nonzero(num_pois) > 0:
        # Find the L loudest binaries in each realizations
        loud = np.sort(temp[:, np.newaxis] * (num_pois > 0), axis=0)[::-1, :]
        mc_ecc_fore = loud[0, :]
        loud = loud[:loudest, :]

        mc_circ_fore = np.max(temp[:, np.newaxis] * (num_pois > 0) * sel_n2[:, np.newaxis], axis=0)
    else:
        mc_ecc_fore = np.zeros_like(mc_ecc_both)
        mc_circ_fore = np.zeros_like(mc_circ_both)
        loud = np.zeros((loudest, nreals))

    mc_ecc_back = mc_ecc_both - mc_ecc_fore
    mc_circ_back = mc_circ_both - mc_circ_fore

    # Package and return
    mc_ecc = [mc_ecc_fore, mc_ecc_back, mc_ecc_both]
    mc_circ = [mc_circ_fore, mc_circ_back, mc_circ_both]

    return mc_ecc, mc_circ, sa_ecc, sa_circ, loud
