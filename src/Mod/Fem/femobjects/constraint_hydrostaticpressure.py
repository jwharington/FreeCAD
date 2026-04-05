# ***************************************************************************
# *   Copyright (c) 2025 John Wharington <jwharington@gmail.com>            *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

__title__ = "FreeCAD FEM constraint hydrostatic pressure document object"
__author__ = "John Wharington"
__url__ = "https://www.freecad.org"

## @package constraint_hydrostaticpressure
#  \ingroup FEM
#  \brief constraint self weight object

import FreeCAD
import numpy as np
from femtools import constants
from femtools.distributions import DistributedPressureType
from scipy.interpolate import (
    LinearNDInterpolator,
    NearestNDInterpolator,
)

from . import base_fempythonobject


class ConstraintHydrostaticPressure(base_fempythonobject.BaseFemPythonObject):
    """
    The ConstraintHydrostaticPressure object"
    """

    Type = "Fem::ConstraintHydrostaticPressure"

    key_properties = {
        DistributedPressureType.Hydrostatic.name: [
            "GravityAcceleration",
            "MediumDensity",
            "ClipNegative",
        ],
        DistributedPressureType.NearestNeighbour.name: [
            "BasePressureScale",
            "DataFile",
        ],
        DistributedPressureType.Interpolated.name: [
            "BasePressureScale",
            "DataFile",
        ],
    }

    def __init__(self, obj):
        obj.Proxy = self

        obj.addProperty(
            type="App::PropertyEnumeration",
            name="ModelType",
            group="Distribution",
            doc="Model of distribution",
        )
        obj.ModelType = [item.name for item in DistributedPressureType]
        obj.ModelType = DistributedPressureType.Hydrostatic.name

        obj.addProperty(
            type="App::PropertyLinkGlobal",
            name="LocalCoordinateSystem",
            group="Distribution",
            doc="Local coordinate system used for distributed pressure",
        )

        # used for hydrostatic
        obj.addProperty(
            type="App::PropertyDensity",
            name="MediumDensity",
            group="Hydrostatic",
            doc="Density of medium, for hydrostatic pressure.",
        ).MediumDensity = "1000 kg/m^3"

        obj.addProperty(
            type="App::PropertyAcceleration",
            name="GravityAcceleration",
            group="Hydrostatic",
            doc="Gravity acceleration, for hydrostatic pressure.",
        )
        obj.setPropertyStatus("GravityAcceleration", "LockDynamic")
        obj.GravityAcceleration = constants.gravity()

        obj.addProperty(
            type="App::PropertyBool",
            name="ClipNegative",
            group="Hydrostatic",
            doc="Enable positive only hydrostatic pressure.",
        ).ClipNegative = False

        # file based
        obj.addProperty(
            type="App::PropertyPressure",
            name="BasePressureScale",
            group="Distribution",
            doc="Base pressure scale for non-hydrostatic pressure.",
        ).BasePressureScale = "1.0 MPa"

        obj.addProperty(
            type="App::PropertyFile",
            name="DataFile",
            group="Distribution",
            doc="Path to the data file containing locations and pressure data.",
        ).DataFile = ""

        # generic
        obj.addProperty(
            type="App::PropertyBool",
            name="EnableAmplitude",
            group="Distribution",
            doc="Enable amplitude scaling.",
        ).EnableAmplitude = False
        obj.setPropertyStatus("EnableAmplitude", "Hidden")

        obj.addProperty(
            type="App::PropertyBool", name="Reversed", group="Distribution", doc="Flip direction."
        ).Reversed = False

        # obj.setPropertyStatus("Scale", "LockDynamic")

    def execute(self, obj):
        if not hasattr(self, "elem_info"):
            self.elem_info = None
        if not hasattr(obj, "ModelType"):
            return
        for p in self.key_properties[obj.ModelType]:
            if not hasattr(obj, p):
                return
        print("hydrostatic pressure execute actual")

        if hasattr(obj, "LocalCoordinateSystem") and obj.LocalCoordinateSystem:
            self.map_coord = obj.LocalCoordinateSystem.getGlobalPlacement().inverse()
        else:
            # TODO get global placement from reference shape (if only one exists)
            self.map_coord = 1

        self.scale, self.interp = self.get_interpolator(obj)
        if FreeCAD.GuiUp and obj.ViewObject:
            obj.ViewObject.update()
        return False

    def data_valid(self, obj):
        req = ["data_points", "data_values"]
        for r in req:
            if getattr(self, r, None) is None:
                return False
        return True

    def pressure_valid(self, obj):
        return self.interp_valid(obj)

    def interp_valid(self, obj):
        if obj.ModelType == DistributedPressureType.Hydrostatic.name:
            return True
        req = ["scale", "interp", "map_coord"]
        for r in req:
            if getattr(self, r, None) is None:
                return False
        return True

    def get_data(self, obj):
        def invalid():
            self.data_points = None
            self.data_values = None

        if obj.ModelType == DistributedPressureType.Hydrostatic.name:
            return invalid()
        if not hasattr(obj, "DataFile") or len(obj.DataFile) == 0:
            return invalid()
        print("get_data actual")
        arr = np.loadtxt(obj.DataFile, delimiter=",")
        self.data_points = arr[:, 0:3]
        self.data_values = arr[:, 3]

    def get_interpolator(self, obj):

        fill_value = 0
        rescale = True

        if obj.ModelType == DistributedPressureType.NearestNeighbour.name:
            if not self.data_valid(obj):
                return None, None
            return (
                self.get_scale(obj, base=True),
                NearestNDInterpolator(self.data_points, self.data_values, rescale=rescale),
            )
        elif obj.ModelType == DistributedPressureType.Interpolated.name:
            if not self.data_valid(obj):
                return None, None
            return (
                self.get_scale(obj, base=True),
                LinearNDInterpolator(
                    self.data_points, self.data_values, fill_value=fill_value, rescale=rescale
                ),
            )
        elif obj.ModelType == DistributedPressureType.Hydrostatic.name:

            def hydrostatic(loc):
                return [loc[2]]

            def hydrostatic_positive(loc):
                return [max(0, loc[2])]

            fn = hydrostatic_positive if obj.ClipNegative else hydrostatic
            return (self.get_scale(obj, base=False), fn)

        def dummy(x):
            return fill_value

        return (1.0, dummy)

    def get_pressure_field(self, obj, elem_info):
        for i in range(len(elem_info["elem"])):
            loc = self.map_coord * elem_info["centroid"][i]
            scale = self.scale * elem_info["rev"][i]
            elem_info["pressure"][i] = scale * self.interp([loc.x, loc.y, loc.z])[0]
        self.elem_info = elem_info  # save copy
        return True

    def get_scale(self, obj, base=True):
        if base:
            scale = obj.BasePressureScale
            return scale.getValueAs("MPa").Value
        else:
            scale = obj.GravityAcceleration * obj.MediumDensity
            return scale.getValueAs("MPa/mm").Value

    def onChanged(self, fp, prop):
        if not hasattr(fp, "ModelType"):
            return
        if prop == "ModelType":
            fp.recompute()
        if prop == "DataFile":
            self.get_data(fp)
        if prop in self.key_properties[fp.ModelType]:
            fp.recompute()

    def onDocumentRestored(self, obj):
        self.get_data(obj)
        obj.recompute()
