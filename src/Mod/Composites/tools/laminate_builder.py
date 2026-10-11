# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Building laminate document objects from a ply schedule.

A laminate is a stack of plies plus the material facts that travel with
them: the fibre card and its uuid, the resin and its uuid, and the fibre
volume fraction.  Those are a design's material schedule, so they arrive as
arguments here — a builder knows how to lay a stack out, not which fibre a
part is made of.
"""

from ..features.CompositeLaminate import (
    CompositeLaminateFP,
    ViewProviderCompositeLaminate,
)
from ..features.FibreCompositeLamina import (
    FibreCompositeLaminaFP,
    ViewProviderFibreCompositeLamina,
)
from ..objects import SymmetryType, WeaveType
from ..util.object_util import attach_view_provider


# The quasi-isotropic angle set, once: a [0/45/-45/90] stack is the reference
# laminate for a member no layup schedule singles out.
QI_ANGLES = (0.0, 45.0, -45.0, 90.0)


def _weave_name(weave):
    """A ``WeaveType`` name from either a name or a member."""
    if isinstance(weave, WeaveType):
        return weave.name
    return WeaveType[weave].name


def make_lamina(doc, name, label, angle, thickness, weave, material, uuid,
                volume_fraction):
    """One fibre-composite ply, as the document object a laminate links.

    ``material`` is the fibre card (a dict); its ``uuid`` and the fibre
    ``volume_fraction`` are stored alongside, because the card a material
    library happens to hold under a uuid is not the same thing as the card
    this laminate was designed with.
    """
    ply = doc.addObject("App::FeaturePython", name)
    FibreCompositeLaminaFP(ply)
    attach_view_provider(ply, ViewProviderFibreCompositeLamina)
    ply.FibreMaterial = material
    ply.FibreMaterialUUID = uuid
    ply.FibreVolumeFraction = volume_fraction
    ply.Thickness = thickness
    ply.Angle = angle
    ply.WeaveType = _weave_name(weave)
    ply.Label = label
    return ply


def build_skin_laminate(doc, fibre, stack, prefix="Skin", thickness_factor=1.0,
                        uuid=None, volume_fraction=None,
                        laminate_volume_fraction=None, resin=None,
                        resin_uuid=None):
    """One asymmetric negative-mould skin laminate from ``stack``.

    ``stack`` is a sequence of ``(label, angle, weave_name, thickness)``
    piles.  ``fibre`` is the fibre card, so a part built from another fibre
    passes a different card here and needs no other change; ``thickness_factor``
    scales every ply, which is how a thickness schedule is bought without
    repeating the stack.

    ``volume_fraction`` is what the plies carry; ``laminate_volume_fraction``
    is what the laminate declares, and defaults to the same.  A schedule that
    reinforces one zone with a different fibre card can therefore state the
    laminate's design fraction separately from the plies' own.
    """
    declared_volume_fraction = (volume_fraction
                                if laminate_volume_fraction is None
                                else laminate_volume_fraction)
    plies = []
    for idx, (label, angle, weave_name, thickness) in enumerate(stack):
        plies.append(make_lamina(
            doc,
            f"{prefix}Ply{idx:02d}",
            f"{prefix}_{label}_{idx}",
            angle,
            thickness * thickness_factor,
            weave_name,
            dict(fibre),
            uuid,
            volume_fraction,
        ))
    laminate = doc.addObject("App::FeaturePython", f"{prefix}Laminate")
    CompositeLaminateFP(laminate, laminae=plies)
    attach_view_provider(laminate, ViewProviderCompositeLaminate)
    laminate.ResinMaterial = dict(resin)
    laminate.ResinMaterialUUID = resin_uuid
    laminate.FibreVolumeFraction = declared_volume_fraction
    laminate.Symmetry = SymmetryType.Assymmetric.name
    return laminate, plies


def build_frame_laminate(doc, fibre, prefix="Frame", stack_blocks=1,
                         thickness_factor=1.0, ply_thickness=None, uuid=None,
                         volume_fraction=None, ply_label="QI", extra_plies=(),
                         angles=QI_ANGLES, resin=None, resin_uuid=None):
    """QI ``[angles]s`` laminate, declared IsotropicEquivalent.

    ``stack_blocks`` repeats the symmetric QI stack: ``angles`` is the stack
    once, so ``stack_blocks=2`` is two blocks.  Every ply is
    ``ply_thickness`` times ``thickness_factor``, and the fibre card, its
    uuid and the volume fraction are parameters so the carbon parts come out
    of the same builder the glass frames do.

    ``extra_plies`` are ``(angle, material, uuid, volume fraction, label)``
    tuples appended to the declared half-stack, at the QI plies' own
    thickness.  The Even symmetry mirrors them, so a declared ±45 pair lands
    as a centred ±45s block.  Extra plies make the stack a mix of
    stiffnesses, which is not quasi-isotropic however the plies are angled,
    so a laminate carrying them is declared as what it is and written
    layered.
    """
    plies = []
    declared = [(angle, ply_thickness * thickness_factor, fibre, uuid,
                 volume_fraction, ply_label)
                for angle in list(angles) * stack_blocks]
    declared += [(angle, ply_thickness * thickness_factor, material,
                  ply_uuid, ply_vf, label)
                 for angle, material, ply_uuid, ply_vf, label in extra_plies]
    for idx, (angle, thickness, material, ply_uuid, ply_vf, label) in \
            enumerate(declared):
        plies.append(make_lamina(
            doc,
            f"{prefix}Ply{idx:02d}",
            # The laminate's prefix in the label: two laminates declaring
            # the same ply material would otherwise carry identical
            # labels (Glass220UD_0 four times over).
            f"{prefix}_{label}_{idx}",
            angle,
            thickness,
            "UD",
            dict(material),
            ply_uuid,
            ply_vf,
        ))
    laminate = doc.addObject("App::FeaturePython", f"{prefix}QILaminate")
    CompositeLaminateFP(laminate, laminae=plies)
    attach_view_provider(laminate, ViewProviderCompositeLaminate)
    laminate.ResinMaterial = dict(resin)
    laminate.ResinMaterialUUID = resin_uuid
    laminate.FibreVolumeFraction = volume_fraction
    # A QI stack must be symmetric (B = 0) for isotropic presentation.
    laminate.Symmetry = SymmetryType.Even.name
    # Extra plies mix stiffnesses into the stack, and the QI angles alone do
    # not make the mix quasi-isotropic, so a mixed-fibre stack is declared as
    # what it is and written layered.  Consequence (D8): such a member's web
    # is a draped shell, not an undraped QI one.
    laminate.IsotropicEquivalent = not extra_plies
    return laminate, plies
