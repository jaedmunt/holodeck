# import numpy as np
# import pyximport   # noqa
# pyximport.install(language_level=3, setup_args={"include_dirs": np.get_include()}, reload_support=True)

# import cytest







from datetime import datetime
import numpy as np
import holodeck as holo
from holodeck import cosmo
from holodeck.constants import PC, YR

import zcode.math as zmath

import numpy as np
import pyximport   # noqa
pyximport.install(language_level=3, setup_args={"include_dirs": np.get_include()}, reload_support=True)

import holodeck.cyutils

# NHARMS = 60
# SAM_SHAPE = 20
# NHARMS = 30
# SAM_SHAPE = 10
NHARMS = 10
SAM_SHAPE = 4

INIT_ECCEN = 0.999
INIT_SEPA = 10.0 * PC


def check_against(val, ref):
    print()
    print(val.shape, ref.shape)
    retval = np.allclose(val, ref, atol=0.0)
    print(f"{str(retval):5s}, {np.median(val):.8e}, {np.median(ref):.8e}")

    if not retval:
        for idx, rr in np.ndenumerate(ref):
            vv = val[idx]
            retval = np.isclose(rr, vv, atol=0.0)
            if not retval:
                print(idx, rr, vv, retval)

    return


def sam_evolve_eccen_uniform_single(sam, eccen_init, sepa_init, nsteps=300):
    assert (0.0 <= eccen_init) and (eccen_init <= 1.0)

    eccen = np.zeros(nsteps)
    eccen[0] = eccen_init

    sepa_max = sepa_init
    sepa_coal = holo.utils.schwarzschild_radius(sam.mtot) * 3
    # frst_coal = utils.kepler_freq_from_sepa(sam.mtot, sepa_coal)
    sepa_min = sepa_coal.min()
    sepa = np.logspace(*np.log10([sepa_max, sepa_min]), nsteps)

    for step in range(1, nsteps):
        a0 = sepa[step-1]
        a1 = sepa[step]
        da = (a1 - a0)
        e0 = eccen[step-1]

        _, e1 = zmath.numeric.rk4_step(holo.hardening.Hard_GW.deda, x0=a0, y0=e0, dx=da)
        e1 = np.clip(e1, 0.0, None)
        eccen[step] = e1

    return sepa, eccen


sam = holo.sam.Semi_Analytic_Model(shape=SAM_SHAPE)
dcom = cosmo.comoving_distance(sam.redz).to('Mpc').value
print("evolve")
sepa_evo, eccen_evo = sam_evolve_eccen_uniform_single(sam, INIT_ECCEN, INIT_SEPA)

print("interp and gwb")
gwfobs = np.logspace(-2, 1, 10) / YR

# ---- Reference GWB

dur = datetime.now()
rv_0 = holo.gravwaves.sam_calc_gwb_0(gwfobs, sam, sepa_evo, eccen_evo, nharms=NHARMS)
dur = datetime.now() - dur
print("0: ", dur.total_seconds())

gwb_0 = rv_0[1]
gwb_0 = np.sqrt(gwb_0)


# ---- Calculation 1 ----

edges = [np.log10(sam.mtot), sam.mrat, sam.redz]

dur = datetime.now()
rv_1 = holo.gravwaves.sam_calc_gwb_1(
    sam.static_binary_density, *edges, dcom,
    gwfobs, sepa_evo, eccen_evo, nharms=NHARMS
)
dur = datetime.now() - dur
print("1: ", dur.total_seconds())
gwb_1 = rv_1
gwb_1 = np.sqrt(gwb_1)

check_against(gwb_1, gwb_0)

'''
# ---- Calculation 2 ----

edges = [np.log10(sam.mtot), sam.mrat, sam.redz]

dur = datetime.now()
rv_2 = holodeck.cyutils.sam_calc_gwb_2(
    sam.static_binary_density, *edges, dcom,
    gwfobs, sepa_evo, eccen_evo, nharms=NHARMS
)
dur = datetime.now() - dur
print("2: ", dur.total_seconds())
gwb_2 = rv_2
gwb_2 = np.sqrt(gwb_2)

check_against(gwb_2, gwb_0)


# ---- Calculation 3 ----

edges = [np.log10(sam.mtot), sam.mrat, sam.redz]

dur = datetime.now()
rv_3 = holodeck.cyutils.sam_calc_gwb_3(
    sam.static_binary_density, *edges, dcom,
    gwfobs, sepa_evo, eccen_evo, nharms=NHARMS
)
dur = datetime.now() - dur
print("3: ", dur.total_seconds())
gwb_3 = rv_3
gwb_3 = np.sqrt(gwb_3)

check_against(gwb_3, gwb_0)
'''

# ---- Calculation 4 ----

edges = [np.log10(sam.mtot), sam.mrat, sam.redz]

dur = datetime.now()
rv_4 = holodeck.cyutils.sam_calc_gwb_4(
    sam.static_binary_density, *edges, dcom,
    gwfobs, sepa_evo, eccen_evo, nharms=NHARMS
)
dur = datetime.now() - dur
print("4: ", dur.total_seconds())
gwb_4 = rv_4
gwb_4 = np.sqrt(gwb_4)

check_against(gwb_4, gwb_0)


# ---- Calculation 5 ----

edges = [np.log10(sam.mtot), sam.mrat, sam.redz]

dur = datetime.now()
rv_5 = holodeck.cyutils.sam_calc_gwb_5(
    sam.static_binary_density, *edges, dcom,
    gwfobs, sepa_evo, eccen_evo, nharms=NHARMS
)
dur = datetime.now() - dur
print("5: ", dur.total_seconds())
gwb_5 = rv_5
gwb_5 = np.sqrt(gwb_5)

check_against(gwb_5, gwb_0)







# import numpy as np

# import pyximport   # This is part of Cython
# pyximport.install(language_level=3)

# import holodeck.gravwaves

# holodeck.gravwaves.tester_1()


# import holodeck
# import holodeck.cyutils
# # print(f"{holodeck.cyutils.gw_freq_dist_func__scalar_scalar(5, 0.565)=}")

# aa = np.random.uniform(0.0, 1.0, 2)
# # print(f"{holodeck.cyutils.gw_freq_dist_func__scalar_array(5, aa)=}")


# from numba import njit
# import ctypes
# from numba.extending import get_cython_function_address

# addr = get_cython_function_address("holodeck.cyutils", "gw_freq_dist_func__scalar_scalar")
# functype = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_int, ctypes.c_double)
# func = functype(addr)


# @njit
# def tester():
#     print("numba")

#     # print(holodeck.cyutils.gw_freq_dist_func__scalar_scalar(4, 0.565))
#     print(func(4, 0.565))
#     # print(holodeck.cyutils.gw_freq_dist_func__scalar_array(5, aa))

# tester()