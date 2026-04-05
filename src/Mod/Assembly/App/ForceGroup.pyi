# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

from App.DocumentObjectGroup import DocumentObjectGroup
from Base.Metadata import export

@export(Include="Mod/Assembly/App/ForceGroup.h", Namespace="Assembly")
class ForceGroup(DocumentObjectGroup):
    """
    This class is a group subclass for forces.

    Author: Ondsel (development@ondsel.com)
    License: LGPL-2.1-or-later
    """
