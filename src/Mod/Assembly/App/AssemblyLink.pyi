# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from typing import Final

from App.Part import Part
from Base.Metadata import export

@export(
    Include="Mod/Assembly/App/AssemblyLink.h",
    Namespace="Assembly",
)
class AssemblyLink(Part):
    """
    This class handles document objects in Assembly

    Author: Ondsel (development@ondsel.com)
    License: LGPL-2.1-or-later
    """

    Joints: Final[list]
    """A list of all joints this assembly link has."""

    Forces: Final[list]
    """A list of all forces this assembly link has."""
