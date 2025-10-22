# SPDX-License-Identifier: LGPL-2.1-or-later

# references: https://nilspv.folk.ntnu.no/TMM4175/failure-criteria.html

import numpy as np
from scipy.optimize import minimize_scalar


default_options = {
    "model_name": "maximum_strain",
    "sxxt": 3.2e-3,  # stretch design allowable, unitless
    "sxxc": 2.7e-3,  # compression design allowable, unitless
    "sxy": 5.3e-3,  # shear strain design allowable, unitless
    "XT": 1,  # tension stress allowable X, pressure units
    "YT": 1,  # tension stress allowable Y, pressure units
    "ZT": 1,  # tension stress allowable Z, pressure units
    "XC": 1,  # compression stress allowable X, pressure units
    "YC": 1,  # compression stress allowable Y, pressure units
    "ZC": 1,  # compression stress allowable Z, pressure units
    "S12": 1,  # shear stress allowable 12, pressure units
    "S13": 1,  # shear stress allowable 13, pressure units
    "S23": 1,  # shear stress allowable 23, pressure units
}


def calc_failure_maximum_strain(
    stress_tensor,
    strain_tensor,
    model_options=default_options,
):
    o = model_options
    strain_limits = np.array(
        [
            [o["sxxt"], -o["sxxc"]],
            [o["sxxt"], -o["sxxc"]],
            [o["sxxt"], -o["sxxc"]],
            [o["sxy"], -o["sxy"]],
            [o["sxy"], -o["sxy"]],
            [o["sxy"], -o["sxy"]],
        ]
    )
    # Simple exceedance of strain in each dimension
    f_t = np.divide(strain_tensor, strain_limits[:, 0]) * (strain_tensor > 0)
    f_c = np.divide(strain_tensor, strain_limits[:, 1]) * (strain_tensor < 0)
    # return the failure criteria value e.g. f = 1 indicates failure
    return np.max(np.hstack([f_t, f_c]))


def calc_failure_maximum_stress(
    stress_tensor,
    strain_tensor,
    model_options=default_options,
):
    o = model_options
    stress_limits = np.array(
        [
            [o["XT"], -o["XC"]],
            [o["YT"], -o["YC"]],
            [o["ZT"], -o["ZC"]],
            [o["S12"], -o["S12"]],
            [o["S23"], -o["S23"]],
            [o["S13"], -o["S13"]],
        ]
    )
    # Simple exceedance of strain in each dimension
    f_t = np.divide(stress_tensor, stress_limits[:, 0]) * (stress_tensor > 0)
    f_c = np.divide(stress_tensor, stress_limits[:, 1]) * (stress_tensor < 0)
    # return the failure criteria value e.g. f = 1 indicates failure
    return np.max(np.hstack([f_t, f_c]))


def calc_failure_tsai_wu(
    stress_tensor,
    strain_tensor,
    model_options=default_options,
):
    o = model_options
    s = stress_tensor

    F1 = 1 / o["XT"] - 1 / o["XC"]
    F2 = 1 / o["YT"] - 1 / o["YC"]
    F3 = 1 / o["ZT"] - 1 / o["ZC"]
    F11 = 1 / (o["XT"] * o["XC"])
    F22 = 1 / (o["YT"] * o["YC"])
    F33 = 1 / (o["ZT"] * o["ZC"])
    F44 = 1 / o["S23"] ** 2
    F55 = 1 / o["S13"] ** 2
    F66 = 1 / o["S12"] ** 2
    F23 = o["f23"] * np.sqrt(F22 * F33)
    F13 = o["f13"] * np.sqrt(F11 * F33)
    F12 = o["f12"] * np.sqrt(F11 * F22)

    f = (
        F1 * s[0]
        + F2 * s[1]
        + F3 * s[2]
        + F11 * s[0] ** 2
        + F22 * s[1] ** 2
        + F33 * s[2] ** 2
        + F44 * s[3] ** 2
        + F55 * s[4] ** 2
        + F66 * s[5] ** 2
        + 2 * (F23 * s[1] * s[2] + F13 * s[0] * s[2] + F12 * s[0] * s[1])
    )
    return f


def calc_failure_hashin(
    stress_tensor,
    strain_tensor,
    model_options=default_options,
):
    o = model_options
    s = stress_tensor

    # fibre failure
    f_ff = 0
    if s[0] > 0:
        f_ff = (s[0] / o["XT"]) ** 2 + (s[3] ** 2 + s[4] ** 2) / o["S12"] ** 2
    else:
        f_ff = -s[0] / o["XC"]

    # interlaminar failure
    f_ilf = (s[5] ** 2 - s[1] * s[2]) / o["S23"] ** 2
    f_ilf += (s[3] ** 2 + s[4] ** 2) / o["S12"] ** 2

    sc = s[1] + s[2]
    if sc >= 0:
        f_ilf += sc**2 / o["YT"] ** 2
    else:
        f_ilf += sc**2 / (4 * o["S23"] ** 2)
        f_ilf += (o["YC"] ** 2 / (4 * o["S23"] ** 2) - 1) * sc / o["YC"]
    return np.max([f_ff, f_ilf])


failure_models = {
    "maximum_strain": calc_failure_maximum_strain,
    "maximum_stress": calc_failure_maximum_stress,
    "tsai_wu": calc_failure_tsai_wu,
    "hashin": calc_failure_hashin,
}


def calc_stress_exposure_factor(
    stress_tensor,
    strain_tensor,
    model_options=default_options,
):

    # this is likely to be slow for large models, may need to move
    # this code to C++ and have fixed (predefined) failure models

    failure_model = failure_models[model_options["model_name"]]

    def fun(sR):
        R = 1.0 / sR
        f = (
            failure_model(
                stress_tensor=stress_tensor * R,
                strain_tensor=strain_tensor * R,
                model_options=model_options,
            )
            - 1.0
        )
        return f * f

    res = minimize_scalar(fun, bounds=(1.0e-3, 1.0e3), method="bounded")
    # stress exposure factor is amount load must be decreased to
    # exactly meet the failure criterion
    if res.success:
        return res.x
    else:
        return 0.0
