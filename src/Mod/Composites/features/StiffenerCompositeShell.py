# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Stiffener composite flow — the stiffener as a configured layup.

A stiffener is a swept shell laid over a support panel.  In
**geometry-only** mode (no ``Laminate`` linked) it stays pure geometry —
the documented generic Part behaviour.  In **full composite** mode
(``Laminate`` linked) the stiffener is configured with its own laminate
and rosette (standard ``Composite::Shell`` property names), the swept
shell is partitioned into a web shell and a foot shell, and the lap
joint where the base row runs along the panel gets the combined
stiffener⊕panel stack — the ``SeamCompositeLaminateFP`` machinery,
reused unchanged and wired by this flow (Master = panel, Attachment =
web shell, SeamRegion = foot shell).

Design records: docs/stiffener_composite_shell.md (PRD),
docs/adr/0002-stiffener-region-split-and-render-ownership.md, and the
domain decisions inherited from the seam PRD
(docs/seam_composite_laminate.md, ADR-0001): transfers are solved,
never copied; symmetric double transfer per joint edge; loud failures
with a recorded ``last_error`` — a silent wrong stack is the one
unacceptable outcome.
"""

import Part

from ..util.geometry_util import shape_fingerprint
from .CompositeShell import is_composite_shell
from .Rosette import RosetteFP
from .SeamCompositeLaminate import CombinationModel, SeamCompositeLaminateFP
from .SeamExtraction import SeamGeometryFP, SeamShellFP
from .TransferRosette import (
    AnalysisTransferRosetteFP,
    TransferRosetteFP,
    attach_rosette_view_provider,
)

# Drape-pitch scaling bounds (mirrors the seam shell's scaling): a
# default 20 mm pitch cannot drape a 15 mm flange, and a sub-millimetre
# pitch cannot drape anything at all.
MIN_PITCH = 0.5
MAX_PITCH = 20.0

_FOOT_OBJECT_SUFFIXES = (
    "_Foot",
    "_PanelFootTransfer",
    "_StiffenerFootTransfer",
    "_CombinedLaminate",
    "_Foot_Support",
)


def is_stiffener_composite(fp) -> bool:
    """True when the stiffener is in full composite mode (Laminate linked)."""
    return getattr(fp, "Laminate", None) is not None


def _is_rosette(obj) -> bool:
    """Proxy-type rosette check.

    Rosette features may be created as Part::FeaturePython (the seam flow
    creates its transfer rosettes that way), so the TypeId-based
    ``is_comp_type`` check does not match them — compare the proxy type.
    """
    from .SeamCompositeLaminate import SeamCompositeLaminateFP

    return SeamCompositeLaminateFP._is_rosette(obj)


def _feature_label(fp) -> str:
    return f"StiffenerCompositeShell '{fp.Name}'"


def validate_composite_wiring(fp) -> None:
    """Raise on every violated structural invariant (PRD §3.2).

    Full composite mode computes a lap joint against the panel, so the
    wiring must be complete: a panel without a laminate is genuinely
    uncomputable (no middle mode — partial wiring fails loudly).  A
    missing stiffener rosette is *not* a failure: the web face it lives
    on only exists after the first build, so the flow auto-creates it
    (never overwriting a user-linked one); a linked non-rosette is.
    """
    support = getattr(fp, "Support", None)
    if support is None or not is_composite_shell(support):
        raise ValueError(
            f"{_feature_label(fp)}: full composite mode requires the "
            f"support to be a Composite::Shell, got {support}"
        )
    panel_layers = getattr(support.Laminate, "Layers", None)
    if not panel_layers:
        raise ValueError(
            f"{_feature_label(fp)}: the support panel has no laminate "
            f"layers to bond the stiffener to"
        )
    stiffener_layers = getattr(fp.Laminate, "Layers", None)
    if not stiffener_layers:
        raise ValueError(
            f"{_feature_label(fp)}: the stiffener laminate has no layers"
        )
    rosette = getattr(fp, "Rosette", None)
    if rosette is not None and not _is_rosette(rosette):
        raise ValueError(
            f"{_feature_label(fp)}: Rosette must be a rosette feature, "
            f"got {rosette}"
        )


def stiffener_claimed_children(fp):
    """Document objects created by a stiffener's composite flow, tree order.

    App-level (works headless, where ViewProviders do not exist) so the
    ViewProvider's claimChildren and the tests share one source of
    truth.  Names not yet created resolve to None and are skipped, so
    the helper is safe before the first composite build.
    """
    doc = getattr(fp, "Document", None)
    if doc is None or not hasattr(doc, "getObject"):
        return []
    get = doc.getObject
    name = fp.Name
    ordered = (
        f"{name}_Web",                    # web shell (stiffener's own laminate)
        f"{name}_Foot",                   # foot shell (combined laminate)
        f"{name}_PanelFootTransfer",      # solved transfer panel → foot
        f"{name}_StiffenerFootTransfer",  # solved transfer stiffener → foot
        f"{name}_WebRosette",             # auto-created web rosette
        f"{name}_CombinedLaminate",       # combined layup (SeamCompositeLaminate)
        # internals last — hidden in 3D, tree-tidy at the bottom
        f"{name}_Web_Support",
        f"{name}_Foot_Support",
        f"{name}_RemainderSupport",
    )
    return [o for o in (get(n) for n in ordered) if o is not None]


# ── the composite flow ────────────────────────────────────────────


def wire_composite_stiffener(host, fp, sweep) -> None:
    """Build/update the composite flow's children for a composite stiffener.

    Called from ``StiffenerFP.execute`` after the sweep and the wiring
    validation.  Skipped entirely when the sweep and the material links
    haven't changed — the child shells' own fingerprints guard their
    drape solves.
    """
    current = _flow_fingerprint(fp, sweep)
    if current == getattr(host, "_last_flow_fingerprint", None):
        return
    host._last_flow_fingerprint = current

    doc = fp.Document
    panel = fp.Support

    web_shell = _build_web_shell(doc, fp, sweep)
    _resupport_panel(doc, fp, panel, sweep)
    # The panel's weave must re-cover the fresh remainder: execute
    # directly (self-guarding — the fingerprint fast path no-ops when
    # the remainder is unchanged), since reassigning nothing would
    # never wake it.
    panel.Proxy.execute(panel)
    _build_foot_strip(doc, fp, panel, web_shell, sweep)
    _hide_compound_filters(doc, fp)


def _resupport_panel(doc, fp, panel, sweep) -> None:
    """Weave exclusivity on the panel (PRD §6.3): re-support the panel
    on the support remainder — the panel minus the stiffener seat — so
    its weave is exclusive of the foot strip by construction, exactly
    as the seam flow re-supports its attachment.  The pre-stiffener
    geometry is preserved in ``SupportBase`` and drives every recompute
    (idempotence).

    With several stiffeners on one panel the remainders chain: a later
    stiffener captures the earlier one's remainder as its SupportBase,
    so each remainder is a pure cut of its own capture and the panel
    weaves on the deepest link.  The panel's Support pointer therefore
    moves only at wiring time — a later recompute of an earlier
    stiffener refreshes its own remainder's geometry but must not steal
    the pointer down to its shallower link, which would resurrect a
    later stiffener's seat into the panel weave.
    """
    rem_name = f"{fp.Name}_RemainderSupport"
    rem_sup = doc.getObject(rem_name)
    if rem_sup is None:
        rem_sup = doc.addObject("Part::Feature", rem_name)
        _hide(rem_sup)
    rem_sup.Shape = Part.makeCompound(sweep.remainders)
    if getattr(fp, "SupportBase", None) is None:
        # First wiring: capture and claim the panel's support.
        fp.SupportBase = panel.Support
        panel.Support = rem_sup
    elif panel.Support is fp.SupportBase or not _is_remainder_support(
        panel.Support
    ):
        # This stiffener is the chain tip (nobody chained beyond it), or
        # the panel's support was restored/changed outside the chain —
        # (re-)claim it.  When a later stiffener owns the pointer, leave
        # it: only this stiffener's remainder geometry was refreshed.
        panel.Support = rem_sup


def _is_remainder_support(obj) -> bool:
    """Whether the object is a stiffener flow's remainder support.

    Name-based, like every lookup in this flow — the remainder objects
    are created as ``<stiffener>_RemainderSupport``.
    """
    return getattr(obj, "Name", "").endswith("_RemainderSupport")


def teardown_composite_stiffener(host, fp) -> None:
    """Undo the composite wiring on a switch to geometry-only mode.

    Restores the panel's original support, hides the flow's children
    and brings the CompoundFilters back — in geometry-only mode they
    are the render, per ADR-0002.  Re-linking a Laminate rebuilds
    everything (the flow fingerprint is reset)."""
    doc = fp.Document
    if doc is None:
        return
    base = fp.SupportBase
    panel = fp.Support
    if panel is not None and base is not None:
        panel.Support = base
    fp.SupportBase = None
    for suffix in ("_Web", "_Foot", "_PanelFootTransfer",
                   "_StiffenerFootTransfer", "_CombinedLaminate",
                   "_WebRosette"):
        obj = doc.getObject(f"{fp.Name}{suffix}")
        if obj is not None:
            _hide(obj)
    rem_sup = doc.getObject(f"{fp.Name}_RemainderSupport")
    if rem_sup is not None:
        _hide(rem_sup)
    for name in (f"{fp.Name}Parts", f"{fp.Name}Remainder"):
        obj = doc.getObject(name)
        if obj is not None:
            _unhide(obj)
    host._last_flow_fingerprint = None


def _flow_fingerprint(fp, sweep) -> str:
    """Hash everything the composite wiring depends on.

    The swept shell's content fingerprint covers the geometry (support,
    cut surface, profile, mirror all express themselves through it); the
    material links are named so a swap re-wires the web shell.
    """
    import hashlib

    parts = [shape_fingerprint(sweep.shell)]
    for prop in ("Laminate", "Rosette"):
        parts.append(getattr(getattr(fp, prop, None), "Name", "None"))
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode())
    return h.hexdigest()


def _build_web_shell(doc, fp, sweep):
    """Create/update the web shell child (the stiffener's own layup).

    The web faces carry the stiffener's own laminate and rosette — the
    stiffener's plies above the base rows (ADR-0002 render ownership).
    """
    if not sweep.web_faces:
        raise ValueError(
            f"{_feature_label(fp)}: the profile produces no web faces — "
            f"nothing rises above the base row, so there is no "
            f"stiffener to lay up"
        )
    web_shell = _ensure_shell_child(doc, fp, "_Web")
    web_shape = Part.makeCompound(sweep.web_faces)
    _set_pitch(web_shell, _scaled_pitch(sweep.web_height))
    # Recenter only the auto-created rosette: a user-linked rosette's LCS
    # position is the user's datum — moving it would be silent vandalism.
    rosette = getattr(fp, "Rosette", None)
    recenter = rosette is not None and rosette.Name == f"{fp.Name}_WebRosette"
    web_shell.Proxy.update(web_shell, web_shape, fp.Laminate, rosette, recenter_lcs=recenter)
    if rosette is None:
        rosette = _ensure_web_rosette(doc, fp, web_shell)
        fp.Rosette = rosette
        web_shell.Rosette = rosette
        SeamGeometryFP._recenter_lcs(web_shape, rosette)
    _ensure_draped(web_shell)
    return web_shell


def _ensure_web_rosette(doc, fp, web_shell):
    """Create (once) the auto rosette on the web shell (PRD §3.2.2)."""
    name = f"{fp.Name}_WebRosette"
    rosette = doc.getObject(name)
    if rosette is None:
        rosette = doc.addObject("Part::FeaturePython", name)
        RosetteFP(rosette, support=(web_shell.Support, ["Face1"]))
        rosette.Angle = 0.0
        attach_rosette_view_provider(rosette)
    rosette.recompute()
    return rosette


def _build_foot_strip(doc, fp, panel, web_shell, sweep):
    """Create/update the foot shell and the combined joint layup.

    The foot faces are the base-row lofts — the part of the stiffener
    that runs along the support.  Two solved transfers onto the foot
    (panel → foot seeds the foot drape; stiffener → foot is
    analysis-only) feed the combined laminate, exactly as the seam flow
    wires its two solved rosettes (ADR-0001).  A profile with no base
    edge degrades gracefully: no foot, no transfers, no joint (§3.2.3).
    """
    if not sweep.foot_faces:
        _drop_foot_strip(doc, fp)
        return None

    foot_shell = _ensure_shell_child(doc, fp, "_Foot")
    foot_shape = Part.makeCompound(sweep.foot_faces)
    _set_pitch(foot_shell, _scaled_pitch(sweep.foot_width))
    # Bootstrap: the foot is part of the stiffener surface, so the
    # stiffener's own laminate is the physically correct stand-in until
    # the combined laminate exists (the seam bootstraps from its
    # attachment's laminate for the same reason).  No explicit drape
    # here: the panel → foot transfer solve drives the foot shell's
    # drape directly, and it wires its rosette first.
    foot_shell.Proxy.update(foot_shell, foot_shape, fp.Laminate, None, recenter_lcs=False)
    _ensure_draped(panel)

    panel_foot = _ensure_panel_foot_transfer(doc, fp, panel, foot_shell)
    stiffener_foot = _ensure_stiffener_foot_transfer(doc, fp, web_shell, foot_shell)
    scl = _ensure_combined_laminate(
        doc, fp, panel, web_shell, foot_shell, panel_foot, stiffener_foot
    )

    foot_shell.Proxy.update(foot_shell, foot_shape, scl, panel_foot)
    for obj in (foot_shell, panel_foot, stiffener_foot, scl):
        _unhide(obj)
    return foot_shell


def _drop_foot_strip(doc, fp) -> None:
    """Graceful degradation when the profile loses its base edge.

    The foot shell and its joint machinery are hidden and inert (the
    foot shell's laminate is released, so it renders nothing); the web
    weave persists.  Restoring a base edge rebuilds and unhides them.
    """
    foot_shell = doc.getObject(f"{fp.Name}_Foot")
    if foot_shell is not None:
        foot_shell.Laminate = None
    for suffix in _FOOT_OBJECT_SUFFIXES:
        obj = doc.getObject(f"{fp.Name}{suffix}")
        if obj is not None:
            _hide(obj)


def _ensure_panel_foot_transfer(doc, fp, panel, foot_shell):
    """Create/update the solved TransferRosette panel → foot.

    The TransferRosette constructor runs the warp-continuity solve and
    wires itself as the foot shell's Rosette, seeding the foot shell's
    drape with the panel's fibre direction at the base-row edge.
    """
    name = f"{fp.Name}_PanelFootTransfer"
    transfer = doc.getObject(name)
    if transfer is None:
        transfer = doc.addObject("Part::FeaturePython", name)
        TransferRosetteFP(
            transfer,
            support=(foot_shell.Support, ["Face1"]),
            master_shell=panel,
            attachment_shell=foot_shell,
        )
        attach_rosette_view_provider(transfer)
    return transfer


def _ensure_stiffener_foot_transfer(doc, fp, web_shell, foot_shell):
    """Create/update the solved stiffener → foot analysis rosette.

    Analysis-only (ADR-0001): it translates the web's lamina directions
    into the foot frame at the fold.  It never becomes the foot shell's
    Rosette, which belongs to the panel → foot transfer.
    """
    name = f"{fp.Name}_StiffenerFootTransfer"
    rosette = doc.getObject(name)
    if rosette is None:
        rosette = doc.addObject("Part::FeaturePython", name)
        AnalysisTransferRosetteFP(
            rosette,
            support=(foot_shell.Support, ["Face1"]),
            master_shell=web_shell,
            attachment_shell=foot_shell,
        )
        attach_rosette_view_provider(rosette)
    return rosette


def _ensure_combined_laminate(
    doc, fp, panel, web_shell, foot_shell, panel_foot, stiffener_foot
):
    """Create/update the SeamCompositeLaminate carrying the joint stack.

    The seam machinery is reused unchanged: Master = panel (stays
    whole), Attachment = web shell (stiffener's own laminate),
    SeamRegion = foot shell.
    """
    name = f"{fp.Name}_CombinedLaminate"
    scl = doc.getObject(name)
    created = False
    if scl is None:
        scl = doc.addObject("App::FeaturePython", name)
        SeamCompositeLaminateFP(scl)
        created = True
        _hide(scl)
    # Resin BEFORE the references: wiring the last visible ref fires the
    # SCL's onChanged recompute, and it must not run against an empty
    # resin (the combined plies' matrix fallback) — that transient
    # failure healed on the next recompute but logged a traceback.
    scl.ResinMaterial = SeamShellFP._side_resin(panel, web_shell)
    scl.Master = panel
    scl.Attachment = web_shell
    scl.SeamRegion = foot_shell
    scl.MasterTransfer = panel_foot
    scl.AttachmentTransfer = stiffener_foot
    if created:
        # Physical default: the stiffener's plies are laid onto the
        # panel — a wiring choice made by this flow, not a class
        # difference (PRD Q4).  The seam flow's default stays untouched.
        scl.CombinationModel = CombinationModel.StackAttachmentOverMaster
    scl.recompute()
    return scl


def ensure_stiffener_shells_visible(fp) -> None:
    """Make the weave shells visible after the creating recompute.

    Shells born inside a recompute are left invisible by the GUI's
    new-object handling — an in-execute ``Visibility = True`` is
    overridden when the recompute settles, so the caller must set it
    after ``doc.recompute()`` returns (examples and command do).  The
    foot shell only shows when the joint exists.
    """
    doc = getattr(fp, "Document", None)
    if doc is None:
        return
    web_shell = doc.getObject(f"{fp.Name}_Web")
    if web_shell is not None:
        _unhide(web_shell)
    foot_shell = doc.getObject(f"{fp.Name}_Foot")
    if foot_shell is not None and getattr(foot_shell, "Laminate", None) is not None:
        _unhide(foot_shell)


# ── helpers ───────────────────────────────────────────────────────


def _ensure_shell_child(doc, fp, suffix):
    name = f"{fp.Name}{suffix}"
    child = doc.getObject(name)
    if child is None:
        child = doc.addObject("Part::FeaturePython", name)
        SeamGeometryFP(child, doc)
    return child


def _scaled_pitch(width_mm) -> float:
    return max(MIN_PITCH, min(MAX_PITCH, width_mm / 4.0))


def _set_pitch(shell, pitch) -> None:
    try:
        if abs(float(shell.DrapePitch) - pitch) > 1e-9:
            shell.DrapePitch = pitch
    except Exception:
        pass


def _ensure_draped(shell) -> None:
    """Drive the shell's drape directly when its backend is not valid.

    The transfer solves read the draper of the master side; a shell that
    has not draped yet (fresh build) must drape before the solve, and a
    direct drive is the only reliable way inside another object's
    execute (a nested doc.recompute() would not re-execute it).
    """
    proxy = getattr(shell, "Proxy", None)
    backend = getattr(proxy, "_backend", None)
    if backend is not None and backend.is_valid():
        return
    proxy.execute(shell)


def _hide_compound_filters(doc, fp) -> None:
    """Composite-mode render split (ADR-0002): every visible surface is
    a weave.  The filters' native faces coincide with the weave shells
    and would z-fight; in geometry-only mode they render as before."""
    for name in (f"{fp.Name}Parts", f"{fp.Name}Remainder"):
        obj = doc.getObject(name)
        if obj is not None:
            _hide(obj)


def _hide(obj) -> None:
    try:
        obj.Visibility = False
    except Exception:
        view_object = getattr(obj, "ViewObject", None)
        if view_object is not None:
            view_object.Visibility = False


def _unhide(obj) -> None:
    try:
        obj.Visibility = True
    except Exception:
        view_object = getattr(obj, "ViewObject", None)
        if view_object is not None:
            view_object.Visibility = True
