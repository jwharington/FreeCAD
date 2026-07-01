# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2026                                                     *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# ***************************************************************************

import FreeCAD

from femresult.failuremodels import (
    calc_stress_exposure_factor,
    default_options,
    list_failure_models,
    register_failure_model,
    unregister_failure_model,
)

from . import manager
from .manager import init_doc


def get_information():
    return {
        "name": "Failure model and stress exposure factor demo",
        "meshgeneration": "Postprocessing",
        "hasanalysis": False,
    }


def get_explanation(header=""):
    return (
        header
        + """

To run the example from Python console use:
from femexamples.failure_stress_exposure_factor_demo import setup
setup()

This example exercises fem-orthotropic post-processing features:
- failure model registry listing/registration
- stress exposure factor (SEF) computation path
- provider-friendly namespaced model registration pattern

"""
    )


def setup(doc=None, solver=None):

    if doc is None:
        doc = init_doc()

    lines = [get_explanation(manager.get_header(get_information()))]
    lines.append("Builtin failure models: {}".format(", ".join(list_failure_models())))

    stress = [180.0, 20.0, 0.0, 8.0, 0.0, 0.0]
    strain = [1.6e-3, 2.5e-4, 0.0, 5.0e-4, 0.0, 0.0]

    opts_stress = default_options | {
        "model_name": "maximum_stress",
        "XT": 450.0,
        "XC": 350.0,
        "YT": 120.0,
        "YC": 110.0,
        "ZT": 120.0,
        "ZC": 110.0,
        "S12": 80.0,
        "S13": 80.0,
        "S23": 65.0,
    }
    sef_stress = calc_stress_exposure_factor(stress, strain, opts_stress)
    lines.append(f"SEF (maximum_stress) = {sef_stress:.6g}")

    opts_strain = default_options | {
        "model_name": "maximum_strain",
        "sxxt": 2.8e-3,
        "sxxc": 2.4e-3,
        "sxy": 4.5e-3,
    }
    sef_strain = calc_stress_exposure_factor(stress, strain, opts_strain)
    lines.append(f"SEF (maximum_strain) = {sef_strain:.6g}")

    def max_stress_x_only(stress_tensor, strain_tensor, model_options):
        xt = model_options.get("XT", 1.0)
        xc = model_options.get("XC", 1.0)
        sxx = stress_tensor[0]
        return sxx / xt if sxx >= 0 else -sxx / xc

    register_failure_model("demo.max_stress_x", max_stress_x_only)
    try:
        opts_demo = default_options | {
            "model_name": "demo.max_stress_x",
            "XT": 500.0,
            "XC": 400.0,
        }
        sef_demo = calc_stress_exposure_factor(stress, strain, opts_demo)
        lines.append(f"SEF (demo.max_stress_x) = {sef_demo:.6g}")
    finally:
        unregister_failure_model("demo.max_stress_x")

    lines.append("Failure models after demo cleanup: {}".format(", ".join(list_failure_models())))

    report = doc.addObject("App::TextDocument", "FailureModelRegistryDemo")
    report.Text = "\n".join(lines)
    report.setPropertyStatus("Text", "ReadOnly")

    if FreeCAD.GuiUp:
        report.ViewObject.ReadOnly = True

    doc.recompute()
    return doc
