import numpy as np
from scipy.optimize import minimize_scalar


sxxt = 3.2e-3  # stretch design allowable
sxxc = 2.7e-3  # compression design allowable
sxy = 5.3e-3  # shear strain design allowable


strain_limits = np.array(
    [
        [sxxt, -sxxc],
        [sxxt, -sxxc],
        [sxxt, -sxxc],
        [sxy, -sxy],
        [sxy, -sxy],
        [sxy, -sxy],
    ]
)


def calc_failure_maximum_strain(stress_tensor, strain_tensor):
    # Simple exceedance of strain in each dimension
    f_t = np.divide(strain_tensor, strain_limits[:, 0]) * (strain_tensor > 0)
    f_c = np.divide(strain_tensor, strain_limits[:, 1]) * (strain_tensor < 0)
    # return the failure criteria value e.g. f = 1 indicates failure
    return np.max(np.hstack([f_t, f_c]))


failure_models = {"maximum_strain": calc_failure_maximum_strain}


def calc_stress_exposure_factor(stress_tensor, strain_tensor, model_name="maximum_strain"):

    # this is likely to be slow for large models, may need to move
    # this code to C++ and have fixed (predefined) failure models

    failure_model = failure_models[model_name]

    def fun(sR):
        R = 1.0 / sR
        f = failure_model(stress_tensor * R, strain_tensor * R) - 1.0
        return f * f

    res = minimize_scalar(fun, bounds=(1.0e-3, 1.0e3), method="bounded")
    # stress exposure factor is amount load must be decreased to
    # exactly meet the failure criterion
    if res.success:
        return res.x
    else:
        return 0.0
