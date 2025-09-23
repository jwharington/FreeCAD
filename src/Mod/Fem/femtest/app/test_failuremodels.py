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
# *                                                                         *
# ***************************************************************************

__title__ = "Failure model FEM unit tests"
__author__ = "FreeCAD contributors"
__url__ = "https://www.freecad.org"

import unittest

import numpy as np

from .support_utils import fcc_print


class TestFailureModels(unittest.TestCase):
    fcc_print("import TestFailureModels")

    def test_00print(self):
        fcc_print(
            "\n{0}\n{1} run FEM TestFailureModels tests {2}\n{0}".format(
                100 * "*", 10 * "*", 52 * "*"
            )
        )

    def test_list_failure_models_builtin(self):
        from femresult.failuremodels import list_failure_models

        names = list_failure_models()
        self.assertIn("maximum_strain", names)
        self.assertIn("maximum_stress", names)

    def test_maximum_strain_increases_with_strain_scale(self):
        from femresult.failuremodels import calc_failure_maximum_strain

        stress = np.zeros(6)
        base = np.array([1.0e-3, 0.5e-3, -0.5e-3, 0.2e-3, 0.1e-3, 0.0])
        f1 = calc_failure_maximum_strain(stress, base)
        f2 = calc_failure_maximum_strain(stress, 2.0 * base)
        self.assertGreater(f2, f1)

    def test_maximum_stress_increases_with_stress_scale(self):
        from femresult.failuremodels import calc_failure_maximum_stress

        strain = np.zeros(6)
        base = np.array([0.2, 0.1, -0.1, 0.05, 0.01, 0.0])
        f1 = calc_failure_maximum_stress(base, strain)
        f2 = calc_failure_maximum_stress(2.0 * base, strain)
        self.assertGreater(f2, f1)

    def test_stress_exposure_factor_monotonic_with_stress(self):
        from femresult.failuremodels import calc_stress_exposure_factor, default_options

        strain = np.zeros(6)
        stress_small = np.array([0.05, 0.02, 0.01, 0.0, 0.0, 0.0])
        stress_large = 2.0 * stress_small

        o = default_options | {"model_name": "maximum_stress"}

        sef_small = calc_stress_exposure_factor(stress_small, strain, o)
        sef_large = calc_stress_exposure_factor(stress_large, strain, o)

        # Higher stress should require at least as much scaling to reach failure.
        self.assertGreaterEqual(sef_large, sef_small)

    def test_unknown_model_name_fails_soft(self):
        from femresult.failuremodels import calc_stress_exposure_factor

        stress = np.ones(6)
        strain = np.zeros(6)
        sef = calc_stress_exposure_factor(stress, strain, {"model_name": "does_not_exist"})
        self.assertEqual(sef, 0.0)
