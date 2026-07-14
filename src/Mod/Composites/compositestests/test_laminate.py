# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for LaminateFP."""

import unittest

from .test_base import TestFreeCADFP


class TestLaminateFP(TestFreeCADFP):
    """Tests for LaminateFP."""

    def test_basic_creation(self):
        laminate = self._create_laminate()
        self.assertIsNotNone(laminate)

    def test_layers_property(self):
        laminate = self._create_laminate()
        laminate.Layers = []
        self.assertEqual(len(laminate.Layers), 0)