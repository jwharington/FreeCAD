# SPDX-License-Identifier: LGPL-2.1-or-later

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
    f_t = np.divide(strain_tensor, strain_limits[:, 0]) * (strain_tensor > 0)
    f_c = np.divide(strain_tensor, strain_limits[:, 1]) * (strain_tensor < 0)
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
    f_t = np.divide(stress_tensor, stress_limits[:, 0]) * (stress_tensor > 0)
    f_c = np.divide(stress_tensor, stress_limits[:, 1]) * (stress_tensor < 0)
    return np.max(np.hstack([f_t, f_c]))


_failure_models = {}
_failure_model_metadata = {}


def register_failure_model(name, fn, metadata=None):
    if not name:
        raise ValueError("Failure model name must be non-empty")
    if not callable(fn):
        raise TypeError("Failure model must be callable")
    _failure_models[name] = fn
    _failure_model_metadata[name] = metadata or {}


def unregister_failure_model(name):
    _failure_models.pop(name, None)
    _failure_model_metadata.pop(name, None)


def get_failure_model(name):
    return _failure_models.get(name)


def list_failure_models():
    return sorted(_failure_models.keys())


def _register_builtin_failure_models():
    register_failure_model("maximum_strain", calc_failure_maximum_strain)
    register_failure_model("maximum_stress", calc_failure_maximum_stress)


_register_builtin_failure_models()


def calc_stress_exposure_factor(
    stress_tensor,
    strain_tensor,
    model_options=default_options,
):
    model_name = model_options.get("model_name", default_options["model_name"])
    failure_model = get_failure_model(model_name)
    if failure_model is None:
        return 0.0

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
    if res.success:
        return res.x
    else:
        return 0.0
