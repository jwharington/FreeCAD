# ***************************************************************************
# *   Copyright (c) 2026 John Wharington <jwharington@gmail.com>            *
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

__title__ = "FreeCAD FEM virtual forces document object"
__author__ = "John Wharington"
__url__ = "https://www.freecad.org"

import FreeCAD as App
from FreeCAD import Vector

from . import base_fempythonobject


class ConstraintVirtualForces(base_fempythonobject.BaseFemPythonObject):
    """Stores inertial states used to map moving-body dynamics to quasi-static loads."""

    triggers = ["CenterOfMass", "LinearVelocity", "AngularVelocity", "References"]

    Type = "Fem::ConstraintVirtualForces"

    def __init__(self, obj):
        super().__init__(obj)

        obj.addProperty(
            type="App::PropertyVector",
            name="LinearAcceleration",
            group="dAlembertForces",
            doc="Linear acceleration",
        ).LinearAcceleration = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyVector",
            name="AngularVelocity",
            group="dAlembertForces",
            doc="Angular velocity",
        ).AngularVelocity = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyVector",
            name="AngularAcceleration",
            group="dAlembertForces",
            doc="Angular acceleration",
        ).AngularAcceleration = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyVector",
            name="LinearVelocity",
            group="dAlembertForces",
            doc="Linear velocity",
        ).LinearVelocity = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyVector",
            name="RelativeVelocity",
            group="dAlembertForces",
            doc="Relative velocity",
        ).RelativeVelocity = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyVector",
            name="CenterOfMass",
            group="dAlembertForces",
            doc="Center of mass",
        ).CenterOfMass = Vector(0, 0, 0)

        obj.addProperty(
            type="App::PropertyVector",
            name="CenterOfRotation",
            group="dAlembertForces",
            doc="Center of rotation",
        ).CenterOfRotation = Vector(0, 0, 0)

    def execute(self, obj):
        for t in self.triggers + ["CenterOfRotation"]:
            if not hasattr(obj, t):
                return

        omega = obj.AngularVelocity
        o_mag = omega.Length
        com = obj.CenterOfMass
        v = obj.LinearVelocity
        v_mag = v.Length
        if (o_mag > 0) and (v_mag > 0):
            omega_n = omega / o_mag
            v_perp = v - omega_n * (v.dot(omega_n))
            r = omega_n.cross(v_perp) / o_mag
            obj.CenterOfRotation = com + r
        else:
            obj.CenterOfRotation = com

    def onChanged(self, fp, prop):
        # during loading the onchanged may be triggered before full init.
        if App.isRestoring():
            return

        if prop in self.triggers:
            fp.recompute()
