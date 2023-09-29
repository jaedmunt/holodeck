"""
"""

cimport cython
from cpython.pycapsule cimport PyCapsule_GetPointer

import numpy as np
cimport numpy as cnp
cnp.import_array()
from numpy.random cimport bitgen_t
from numpy.random import PCG64
from numpy.random.c_distributions cimport random_poisson, random_normal

from libc.stdio cimport printf
from libc.stdlib cimport malloc, free, realloc
# make sure to use c-native math functions instead of python/numpy
from libc.math cimport pow, sqrt, abs, M_PI, NAN, log

from holodeck import utils
from holodeck.cyutils cimport interp_at_index, _interp_between_vals, gw_freq_dist_func__scalar_scalar

# int64 type
DTYPE_LONG = np.int64
NPY_DTYPE_LONG = cnp.NPY_INT64
ctypedef cnp.int64_t DTYPE_LONG_t

# float64 type
DTYPE_DOUBLE = np.float64
NPY_DTYPE_DOUBLE = cnp.NPY_FLOAT64
ctypedef cnp.float64_t DTYPE_DOUBLE_t

ctypedef cnp.npy_intp SIZE_t

# cdef extern from "utils.py":
#     double _chirp_mass_m1m2(double m1, double m2)
#     double _gw_strain_source(double mchirp, double dcom, double freq_rest_orb)
#     double _dfdt_from_dadt(double dadt, double sepa, double frst_orb)
#     double _lambda_factor_dlnf(double frst, double dfdt, double redz, double dcom)

cdef double MIN_ECCEN_ZERO = 1.0e-4
cdef double POISSON_THRESHOLD = 1.0e8

# ---- Define Constants

cdef double MY_NWTG = 6.6742999e-08
cdef double MY_MSOL = 1.988409870698e+33
cdef double MY_SPLC = 29979245800.0
cdef double MY_MPC = 3.08567758e+24
cdef double MY_YR = 31557600.0

# freq = KEPLER_CONST * sqrt(mass) / pow(sepa, 1.5)
cdef double KEPLER_CONST = sqrt(MY_NWTG) / 2.0 / M_PI


cdef struct ArrayData:
    SIZE_t final_size
    DTYPE_LONG_t* bin
    DTYPE_LONG_t* interp_idx
    double* m1
    double* m2
    double* redz
    double* eccen
    double* dadt
    double* dedt


def interp_at_fobs(evo, fobs):
    fobs = np.atleast_1d(fobs)
    assert fobs.ndim == 1

    dadt_tot = np.sum(evo.dadt, axis=-1)
    dedt_tot = np.sum(evo.dedt, axis=-1)
    assert evo._first_index.dtype == DTYPE_LONG

    cdef ArrayData data
    _interp_at_fobs(
        evo._first_index, evo._last_index, fobs,
        evo.sepa, evo.eccen, evo.redz, dadt_tot, dedt_tot, evo.mass,
        &data
    )

    cdef cnp.ndarray[DTYPE_LONG_t, ndim=1, mode="c"] bin = cnp.PyArray_SimpleNewFromData(
        1, &data.final_size, NPY_DTYPE_LONG, <void*>data.bin
    )
    cdef cnp.ndarray[DTYPE_LONG_t, ndim=1, mode="c"] interp_idx = cnp.PyArray_SimpleNewFromData(
        1, &data.final_size, NPY_DTYPE_LONG, <void*>data.interp_idx
    )
    cdef cnp.ndarray[DTYPE_DOUBLE_t, ndim=1, mode="c"] m1 = cnp.PyArray_SimpleNewFromData(
        1, &data.final_size, NPY_DTYPE_DOUBLE, <void*>data.m1
    )
    cdef cnp.ndarray[DTYPE_DOUBLE_t, ndim=1, mode="c"] m2 = cnp.PyArray_SimpleNewFromData(
        1, &data.final_size, NPY_DTYPE_DOUBLE, <void*>data.m2
    )
    cdef cnp.ndarray[DTYPE_DOUBLE_t, ndim=1, mode="c"] redz = cnp.PyArray_SimpleNewFromData(
        1, &data.final_size, NPY_DTYPE_DOUBLE, <void*>data.redz
    )
    cdef cnp.ndarray[DTYPE_DOUBLE_t, ndim=1, mode="c"] eccen = cnp.PyArray_SimpleNewFromData(
        1, &data.final_size, NPY_DTYPE_DOUBLE, <void*>data.eccen
    )
    cdef cnp.ndarray[DTYPE_DOUBLE_t, ndim=1, mode="c"] dadt = cnp.PyArray_SimpleNewFromData(
        1, &data.final_size, NPY_DTYPE_DOUBLE, <void*>data.dadt
    )
    cdef cnp.ndarray[DTYPE_DOUBLE_t, ndim=1, mode="c"] dedt = cnp.PyArray_SimpleNewFromData(
        1, &data.final_size, NPY_DTYPE_DOUBLE, <void*>data.dedt
    )

    return bin, interp_idx, m1, m2, redz, eccen, dadt, dedt


@cython.boundscheck(False)
@cython.wraparound(False)
@cython.nonecheck(False)
@cython.cdivision(True)
cdef void _interp_at_fobs(
    DTYPE_LONG_t[:] beg_index,
    DTYPE_LONG_t[:] end_index,
    double[:] target_fobs,
    double[:] sepa,
    double[:] eccen,
    double[:] redz,
    double[:] dadt,
    double[:] dedt,
    double[:, :] mass,
    ArrayData* data,
):

    # Initialize sizes and shapes
    cdef DTYPE_LONG_t nbins = len(beg_index)
    # cdef DTYPE_LONG_t nentries = len(sepa)
    cdef DTYPE_LONG_t nfreqs = len(target_fobs)

    cdef DTYPE_LONG_t arr_size = nfreqs * nbins
    cdef DTYPE_LONG_t arr_size_tot = arr_size

    data.bin = <DTYPE_LONG_t *>malloc(arr_size * sizeof(DTYPE_LONG_t))         # binary index number
    data.interp_idx = <DTYPE_LONG_t *>malloc(arr_size * sizeof(DTYPE_LONG_t))         # target fobs index number
    data.m1 = <double *>malloc(arr_size * sizeof(double))         # target fobs index number
    data.m2 = <double *>malloc(arr_size * sizeof(double))         # target fobs index number
    data.redz = <double *>malloc(arr_size * sizeof(double))         # target fobs index number
    data.eccen = <double *>malloc(arr_size * sizeof(double))         # target fobs index number
    data.dadt = <double *>malloc(arr_size * sizeof(double))         # target fobs index number
    data.dedt = <double *>malloc(arr_size * sizeof(double))         # target fobs index number

    cdef DTYPE_LONG_t bin, left, right, fi, idx, direction, last_direction
    cdef DTYPE_LONG_t out = 0
    cdef DTYPE_LONG_t beg, end
    cdef double fobs_l, fobs_r

    for bin in range(nbins):
        # if (bin > 0) and ((bin == nbins-1) or (bin % (nbins//10) == 0)):
        #     printf("%ld, ", bin)
        #     if bin == nbins-1:
        #         printf("\n")

        # get the first and last index (both inclusive) for this binary
        beg = beg_index[bin]
        end = end_index[bin]
        # printf("\n---- bin %04ld [%04ld, %04ld]\n\n", bin, beg, end)

        # assume that we'll start out hardening (frequency increasing)
        direction = +1
        last_direction = +1

        # initialize to the first target frequency
        fi = 0
        # initialize left edge of step to the first entry for this binary
        left = beg
        # get the observer-frame frequency at the left edge
        fobs_l = get_fobs(sepa[left], mass[left, 0]+mass[left, 1], redz[left])
        # increment over steps, make sure final `right` value *includes* `end` (hence `end+1`)
        for right in range(left+1, end+1):
            # printf("[%03ld, %03ld] - %.3e, %.3e\n", left, right, fobs_l)

            # make sure arrays have enough space
            # for a given integration-step, we can match at most `nfreqs`, so thats as much extra space as we need
            if out + nfreqs >= arr_size_tot:
                # printf("out+nfreqs=%ld+%ld=%ld >= %ld, resizing\n", out, nfreqs, out+nfreqs, arr_size_tot)
                arr_size_tot += arr_size
                data.bin = <DTYPE_LONG_t *>realloc(data.bin, arr_size_tot * sizeof(DTYPE_LONG_t))
                data.interp_idx = <DTYPE_LONG_t *>realloc(data.interp_idx, arr_size_tot * sizeof(DTYPE_LONG_t))
                data.m1 = <double *>realloc(data.m1, arr_size_tot * sizeof(double))
                data.m2 = <double *>realloc(data.m2, arr_size_tot * sizeof(double))
                data.redz = <double *>realloc(data.redz, arr_size_tot * sizeof(double))
                data.eccen = <double *>realloc(data.eccen, arr_size_tot * sizeof(double))
                data.dadt = <double *>realloc(data.dadt, arr_size_tot * sizeof(double))
                data.dedt = <double *>realloc(data.dedt, arr_size_tot * sizeof(double))

            # get observer-frame freq at right edge
            fobs_r = get_fobs(sepa[right], mass[right, 0]+mass[right, 1], redz[right])
            # printf("%03ld :: %03ld ==> %03ld :: %.4e, %.4e || target = %.4e\n", left-beg, left, right, fobs_l, fobs_r, target_fobs[fi])

            # we are moving to higher frequencies = hardening
            if fobs_l < fobs_r:
                direction = +1

                # If we change directions, to decreasing in frequency, reset to the largest target frequency
                #! I don't think this is necessary (?), but it definitely works keeping it...  [LZK:2023-09-26]
                #! Disabling this check still passes the tests... so currently commenting out [LZK:2023-09-27]
                # if direction != last_direction:
                #     fi = 0
                #     # printf("| changed direction - ==> +  :: %ld\n", fi)

                # increment target frequency until it's above the left-edge (it may still be above right-edge also)
                while (fobs_l > target_fobs[fi]) and (fi+1 < nfreqs):
                    # printf("fobs_l > target_fobs[fi]  (%.4e > %.4e[%03ld]), fi ==> %ld\n", fobs_l, target_fobs[fi], fi, fi+1)
                    fi += 1

                # printf("  next target +++ : %03ld @ %.4e\n", fi, target_fobs[fi])

                # if target is above left-edge
                if fobs_l < target_fobs[fi]:
                    # if target is below right-edge, we have a match - time to interpolate
                    # this is a while-loop (instead of for-loop), for multiple targets at this step
                    while (target_fobs[fi] < fobs_r):
                        # printf("+ %.4e %.4e %.4e ==> target=%04ld - %04ld\n", fobs_l, target_fobs[fi], fobs_r, fi, out)

                        #! also interpolate individual hardening rates
                        # set output to show which binary and which target frequency this match corresponds to
                        data.bin[out] = bin
                        data.interp_idx[out] = fi
                        # interpolate desired values
                        data.m1[out] = _interp_between_vals(
                            target_fobs[fi], fobs_l, fobs_r, mass[left, 0], mass[right, 0]
                        )
                        # printf("\t%.4e %.4e %.4e\n", fobs_l*MY_YR, target_fobs[fi]*MY_YR, fobs_r*MY_YR)
                        # printf("\t%.4e %.4e %.4e\n", mass[left, 0]/MY_MSOL, data.m1[out]/MY_MSOL, mass[right, 0]/MY_MSOL)
                        data.m2[out] = _interp_between_vals(
                            target_fobs[fi], fobs_l, fobs_r, mass[left, 1], mass[right, 1]
                        )
                        data.redz[out] = _interp_between_vals(
                            target_fobs[fi], fobs_l, fobs_r, redz[left], redz[right]
                        )
                        data.eccen[out] = _interp_between_vals(
                            target_fobs[fi], fobs_l, fobs_r, eccen[left], eccen[right]
                        )
                        data.dadt[out] = _interp_between_vals(
                            target_fobs[fi], fobs_l, fobs_r, dadt[left], dadt[right]
                        )
                        data.dedt[out] = _interp_between_vals(
                            target_fobs[fi], fobs_l, fobs_r, dedt[left], dedt[right]
                        )

                        # increment the output array index pointer
                        out += 1

                        # go up to the next target frequency
                        if (fi+1 < nfreqs):
                            fi += 1
                            # printf("fi += 1 ==> %ld\n", fi)
                        else:
                            break

            # we are moving to lower frequencies = softening
            elif fobs_l > fobs_r:
                direction = -1

                # If we change directions, to decrease in frequency, reset to the largest target frequency
                #! I don't think this is necessary (?), but it definitely works keeping it... [LZK:2023-09-26]
                #! Disabling this check still passes the tests... so currently commenting out [LZK:2023-09-27]
                # if direction != last_direction:
                #     fi = nfreqs - 1
                #     # printf("| changed direction + ==> -  :: %ld\n", fi)

                # decrement target frequency until it's below
                while (fobs_l < target_fobs[fi]) and (fi > 0):
                    # printf("fobs_l < target_fobs[fi]  (%.4e < %.4e[%03ld]), fi ==> %ld\n", fobs_l, target_fobs[fi], fi, fi-1)
                    fi -= 1

                # printf("  next target --- : %03ld @ %.4e\n", fi, target_fobs[fi])

                # if target is below left-edge
                if fobs_l > target_fobs[fi]:
                    # if target is above right-edge, we have a match - time to interpolate
                    # this is a while-loop (instead of for-loop), for multiple targets at this step
                    while (target_fobs[fi] > fobs_r):
                        # printf("- %.4e %.4e %.4e ==> target=%04ld - %04ld\n", fobs_l, target_fobs[fi], fobs_r, fi, out)

                        # set output to show which binary and which target frequency this match corresponds to
                        data.bin[out] = bin
                        data.interp_idx[out] = fi
                        # interpolate desired values
                        data.m1[out] = _interp_between_vals(
                            target_fobs[fi], fobs_l, fobs_r, mass[left, 0], mass[right, 0]
                        )
                        # printf("\t%.4e %.4e %.4e\n", mass[left, 0]/MY_MSOL, data.m1[out]/MY_MSOL, mass[right, 0]/MY_MSOL)
                        # printf("\t%.4e %.4e %.4e\n", fobs_l*MY_YR, target_fobs[fi]*MY_YR, fobs_r*MY_YR)
                        data.m2[out] = _interp_between_vals(
                            target_fobs[fi], fobs_l, fobs_r, mass[left, 1], mass[right, 1]
                        )
                        data.redz[out] = _interp_between_vals(
                            target_fobs[fi], fobs_l, fobs_r, redz[left], redz[right]
                        )
                        data.eccen[out] = _interp_between_vals(
                            target_fobs[fi], fobs_l, fobs_r, eccen[left], eccen[right]
                        )
                        data.dadt[out] = _interp_between_vals(
                            target_fobs[fi], fobs_l, fobs_r, dadt[left], dadt[right]
                        )
                        data.dedt[out] = _interp_between_vals(
                            target_fobs[fi], fobs_l, fobs_r, dedt[left], dedt[right]
                        )

                        # increment the output array index pointer
                        out += 1
                        # go down to the next target frequency
                        if (fi > 0):
                            fi -= 1
                            # printf("fi -= 1 ==> %ld\n", fi)
                        else:
                            break

            else:
                printf("\n\nERROR: `discrete_cyutils._interp_at_fobs()` :: ")
                printf(
                    "fobs_l==fobs_r (%e, %e)!  bin=%ld, left=%ld, right=%ld\n\n",
                    fobs_l, fobs_r, bin, left, right
                )

            fobs_l = fobs_r
            left = right
            # last_direction = direction

    data.final_size = out
    # downsize arrays to amount of space used
    data.bin = <DTYPE_LONG_t *>realloc(data.bin, out * sizeof(DTYPE_LONG_t))
    data.interp_idx = <DTYPE_LONG_t *>realloc(data.interp_idx, out * sizeof(DTYPE_LONG_t))
    data.m1 = <double *>realloc(data.m1, out * sizeof(double))
    data.m2 = <double *>realloc(data.m2, out * sizeof(double))
    data.redz = <double *>realloc(data.redz, out * sizeof(double))
    data.eccen = <double *>realloc(data.eccen, out * sizeof(double))
    data.dadt = <double *>realloc(data.dadt, out * sizeof(double))
    data.dedt = <double *>realloc(data.dedt, out * sizeof(double))
    # printf("arr_size = %ld (tot = %ld), out =  %ld\n", arr_size, arr_size_tot, out)

    return


@cython.nonecheck(False)
@cython.cdivision(True)
cdef double get_fobs(double sepa, double mass, double redz):
    cdef double fobs = KEPLER_CONST * sqrt(mass)/pow(sepa, 1.5)
    fobs /= (1.0 + redz)
    return fobs



def gwb_from_harmonics_data(fobs_gw_edges, harms, fobs_index, harm_index, data, nreals, box_vol_cm3):
    cdef int nfreqs = fobs_gw_edges.size - 1
    cdef cnp.ndarray[cnp.double_t, ndim=3] gwb = np.zeros((nfreqs, harms.size, nreals))
    _gwb_from_harmonics_data(
        fobs_gw_edges, harms, fobs_index, harm_index, data['interp_idx'],
        data['mass'], data['sepa'], data['eccen'], data['redz'], data['dcom'], data['dadt'],
        nreals, box_vol_cm3,
        gwb,
    )
    return gwb


@cython.boundscheck(False)
@cython.wraparound(False)
@cython.nonecheck(False)
@cython.cdivision(True)
cdef void _gwb_from_harmonics_data(
    # input
    double[:] fobs_edges,    # GW observer-frame frequencies
    DTYPE_LONG_t[:] harms,
    DTYPE_LONG_t[:] fobs_idx,
    DTYPE_LONG_t[:] harm_idx,
    DTYPE_LONG_t[:] interp_idx,
    double[:, :] mass,
    double[:] sepa,
    double[:] eccen,
    double[:] redz,
    double[:] dcom,
    double[:] dadt,
    DTYPE_LONG_t nreals,
    double box_vol_cm3,
    # output
    double[:, :, :] gwb,
):

    cdef DTYPE_LONG_t nfreqs = len(fobs_edges) - 1
    cdef DTYPE_LONG_t nfreqharms = len(harm_idx)
    cdef DTYPE_LONG_t nvals = len(interp_idx)

    cdef DTYPE_LONG_t ii, idx, fi, hi, rr
    cdef double gne, frst_orb, mc, dfdt, lambda_factor, num_binaries, nb, h2temp

    cdef bitgen_t *rng
    cdef const char *capsule_name = "BitGenerator"
    capsule = PCG64().capsule
    # Cast the pointer
    rng = <bitgen_t *> PyCapsule_GetPointer(capsule, capsule_name)

    cdef double* fobs_cents = <double *>malloc(nfreqs * sizeof(double))
    cdef double* dlnf = <double *>malloc(nfreqs * sizeof(double))
    for ii in range(nfreqs):
        fobs_cents[ii] = 0.5 * (fobs_edges[ii] + fobs_edges[ii+1])
        dlnf[ii] = log(fobs_edges[ii+1]) - log(fobs_edges[ii])

    for ii in range(nvals):
        # which target-frequency this entry corresponds to
        idx = interp_idx[ii]
        # which GW-frequency-index this corresponds to
        fi = fobs_idx[idx]
        # which harmonic-index this corresponds to
        hi = harm_idx[idx]
        # rest-frame orbital frequency
        frst_orb = fobs_cents[fi] * (1.0 + redz[ii]) / harms[hi]

        if eccen[ii] < MIN_ECCEN_ZERO:
            if harms[hi] == 2:
                gne = 1.0
            else:
                gne = 0.0
        else:
            gne = gw_freq_dist_func__scalar_scalar(harms[hi], eccen[ii])

        mc = utils._chirp_mass_m1m2(mass[ii, 0], mass[ii, 1])
        h2temp = utils._gw_strain_source(mc, dcom[ii], frst_orb)**2

        dfdt, _ = utils._dfdt_from_dadt(
            dadt[ii], sepa[ii], frst_orb,
            # dfdt_mdot=evo.dfdt_mdot
        )

        h2temp = h2temp * gne * pow(2.0 / harms[hi], 2)

        lambda_factor = utils._lambda_factor_dlnf(frst_orb, dfdt, redz[ii], dcom[ii]) / box_vol_cm3
        num_binaries = lambda_factor * dlnf[fi]

        if num_binaries > POISSON_THRESHOLD:
            for rr in range(nreals):
                nb = <double>random_normal(rng, num_binaries, sqrt(num_binaries))
                gwb[fi, hi, rr] += nb * h2temp / dlnf[fi]
        else:
            for rr in range(nreals):
                nb = <double>random_poisson(rng, num_binaries)
                gwb[fi, hi, rr] += nb * h2temp / dlnf[fi]

    free(fobs_cents)

    return

