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
from .CompositeShell import is_composite_shell, is_isotropic_shell
from .Laminate import is_isotropic_laminate
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

    import time as _time
    _t = _time.perf_counter()
    web_shell = _build_web_shell(doc, fp, sweep)
    print("[wire] %s web_shell %.1fs" % (fp.Name, _time.perf_counter() - _t), flush=True)
    _t = _time.perf_counter()
    _record_joint_remainder(doc, fp, panel, sweep)
    print("[wire] %s remainder %.1fs" % (fp.Name, _time.perf_counter() - _t), flush=True)
    _t = _time.perf_counter()
    _build_foot_strip(doc, fp, panel, web_shell, sweep)
    print("[wire] %s foot_strip %.1fs" % (fp.Name, _time.perf_counter() - _t), flush=True)
    _hide_compound_filters(doc, fp)


def _record_joint_remainder(doc, fp, panel, sweep) -> None:
    """Record the stiffener's seat remainder — the joint's master side.

    Lap joint (owner decision 2026-09-30, replacing the weave-exclusivity
    re-support): the panel drapes once, before any stiffener, on its own
    full support, and its weave runs continuously under every foot — a
    re-drape of the panel on the cut remainder was what produced the
    multi-island coverage defect (one island dead on a boundary seed).
    What the joint machinery still needs is the seat's cut geometry as
    the master-side surface of THIS joint — the remainder's cut edges are
    what the foot shares — so the sweep's remainders are recorded on
    ``<stiffener>_RemainderSupport`` and handed to the combined laminate
    through ``MasterSupport``.  The panel's Support pointer never moves.

    ``SupportBase`` still captures the panel's support at first wiring
    (the sweep reads it); under the common drape it is the panel's own
    support for every stiffener, so the old remainder-chain healing
    paths are inert.
    """
    rem_name = f"{fp.Name}_RemainderSupport"
    rem_sup = doc.getObject(rem_name)
    if rem_sup is None:
        rem_sup = doc.addObject("Part::Feature", rem_name)
        _hide(rem_sup)
    rem_sup.Shape = Part.makeCompound(sweep.remainders)
    if getattr(fp, "SupportBase", None) is None:
        fp.SupportBase = panel.Support


def _is_remainder_support(obj) -> bool:
    """Whether the object is a stiffener flow's remainder support.

    Name-based, like every lookup in this flow — the remainder objects
    are created as ``<stiffener>_RemainderSupport``.
    """
    return getattr(obj, "Name", "").endswith("_RemainderSupport")


def _remainder_owner_gone(obj) -> bool:
    """Whether a remainder support's owning stiffener was deleted.

    The remainder object outlives its owner; the chain below the
    deleted stiffener is dead and the pointer must not be treated as a
    living link.
    """
    if not _is_remainder_support(obj):
        return False
    return (
        obj.Document is None
        or obj.Document.getObject(obj.Name[: -len("_RemainderSupport")]) is None
    )


def chain_base_is_orphaned(fp) -> bool:
    """Whether the stiffener's SupportBase belonged to a deleted
    stiffener.  A remainder whose owning stiffener no longer exists is
    an orphan: it still holds a shape, but that shape no longer
    reflects the document.
    """
    base = getattr(fp, "SupportBase", None)
    if base is None or fp.Document is None:
        return False
    return _remainder_owner_gone(base)


def panel_support_is_orphaned(panel) -> bool:
    """Whether the panel's Support points at an orphaned remainder
    (its owning stiffener was deleted).  The chain below the deleted
    stiffener is dead; the deepest living stiffener must re-claim the
    pointer onto its own remainder.
    """
    return panel is not None and _remainder_owner_gone(
        getattr(panel, "Support", None)
    )


def recover_deleted_chain_predecessor(fp) -> bool:
    """Heal a stiffener whose chain predecessor was deleted.

    The deleted stiffener's remainder (this stiffener's ``SupportBase``)
    is deleted or orphaned, so the captured geometry can no longer drive
    the sweep — sweeping from the panel's re-pointed support (this
    stiffener's own remainder) would be garbage.  Restore the panel's
    original support (captured at the first wiring) and re-capture it
    here: the remainder is re-cut without the deleted stiffener's seat,
    and that seat returns to the panel weave.  Returns True when healed.
    """
    panel = fp.Support
    if panel is None or fp.Document is None:
        return False
    own_remainder = fp.Document.getObject(f"{fp.Name}_RemainderSupport")
    wired = own_remainder is not None and panel.Support is own_remainder
    damaged = getattr(fp, "SupportBase", None) is None or chain_base_is_orphaned(fp)
    if not wired or not damaged:
        return False
    backup = getattr(panel, "SupportBackup", None)
    if backup is None:
        return False
    # Step the panel back to the original support; the wiring below
    # re-claims it onto the refreshed remainder.
    panel.Support = backup
    fp.SupportBase = backup
    return True


def teardown_composite_stiffener(host, fp) -> None:
    """Undo the composite wiring on a switch to geometry-only mode.

    The panel was never re-pointed (common drape), so restoring its
    support is a no-op identity write; the flow's children are hidden
    and the CompoundFilters return — in geometry-only mode they are the
    render, per ADR-0002.  Re-linking a Laminate rebuilds everything
    (the flow fingerprint is reset).
    """
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


def _apply_trim_tool(fp, shape):
    """Geometry-first trim (owner): cut the shell's support faces by the
    stiffener's TrimTool (the engine-bay solid) before the CompositeShell
    exists. The drape is untouched — it was solved (or borrowed) on the
    uncut support, and the trimmed shell takes its weave from there over
    the trimmed region via its DrapeSource link."""
    tool = getattr(fp, "TrimTool", None)
    if tool is None or tool.Shape is None or tool.Shape.isNull():
        return shape
    trimmed = shape.cut(tool.Shape)
    if not trimmed.Faces:
        raise ValueError(
            f"{_feature_label(fp)}: the trim tool removes the whole "
            f"support ({len(shape.Faces)} faces) — nothing left to lay up"
        )
    return Part.makeCompound(trimmed.Faces)


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
    web_shape = _apply_trim_tool(fp, Part.makeCompound(sweep.web_faces))
    _set_pitch(web_shell, _scaled_pitch(sweep.web_height))
    # Recenter only the auto-created rosette: a user-linked rosette's LCS
    # position is the user's datum — moving it would be silent vandalism.
    rosette = getattr(fp, "Rosette", None)
    recenter = rosette is not None and rosette.Name == f"{fp.Name}_WebRosette"
    web_shell.Proxy.update(web_shell, web_shape, fp.Laminate, rosette, recenter_lcs=recenter)
    if is_isotropic_shell(web_shell):
        # D8: a QI web laminate takes no rosette (none can attach to an
        # isotropic shell) and no drape — the web shell's own execute
        # bypasses draping; leave fp.Rosette as None.
        return web_shell
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
    foot_shape = _apply_trim_tool(fp, Part.makeCompound(sweep.foot_faces))
    _set_pitch(foot_shell, _scaled_pitch(sweep.foot_width))
    # The foot's laminate is the combined stack (SCL): the panel's
    # directional plies continue under it plus the ring plies — the foot is
    # NOT quasi-isotropic.  It does not run its own drape solve: the
    # support's common drape already covers the band (the lap joint), and
    # the foot takes its drape coordinates from that solved drape via its
    # DrapeSource link (see CompositeShellFP.DrapeSource).
    # Wiring stand-in: the panel's directional stack seeds nothing here —
    # DrapeSource (set immediately below) routes the foot's execute to the
    # borrowed weave before any laminate branch can run — but the stand-in
    # keeps the foot non-isotropic through the wiring, where the transfer
    # attaches its rosette (an isotropic shell takes no rosette, PRD §5.3).
    # The final update below sets the combined stack (SCL).
    foot_shell.Proxy.update(foot_shell, foot_shape, panel.Laminate, None,
                            recenter_lcs=False)
    foot_shell.DrapeSource = panel
    if not is_isotropic_shell(panel):
        _ensure_draped(panel)

    # Transfers (D8): a QI side has no fibre frame to translate — the
    # panel → foot transfer is kept whenever the panel is draped, the
    # web → foot analysis transfer is meaningless for a QI web.
    panel_foot = (
        _ensure_panel_foot_transfer(doc, fp, panel, foot_shell)
        if not is_isotropic_shell(panel)
        else None
    )
    stiffener_foot = (
        _ensure_stiffener_foot_transfer(doc, fp, web_shell, foot_shell)
        if not is_isotropic_shell(web_shell)
        else None
    )
    scl = _ensure_combined_laminate(
        doc, fp, panel, web_shell, foot_shell, panel_foot, stiffener_foot
    )

    # The foot's laminate stays the combined stack (SCL — see above) and it
    # never drapes its own solve: its drape coordinates come from the
    # support's solved drape over the band, via the DrapeSource link.
    foot_shell.Proxy.update(foot_shell, foot_shape, scl, panel_foot)
    foot_shell.DrapeSource = panel
    for obj in (foot_shell, panel_foot, stiffener_foot, scl):
        if obj is not None:
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


def _foot_contact_edge_support(foot_shell):
    """The foot shell's support, addressed at a boundary edge of the foot
    strip rather than its face.

    A transfer rosette supported on the foot *face* takes its frame from
    that face's U direction, which on a narrow strip runs **across** the
    strip — radially, i.e. along the panel normal — so the "warp" the
    direct contact measurement reads is not a tangential fibre direction at
    all.  Measured consequence: for the attachment side both ``warp x
    tangent`` and ``warp . tangent`` vanish, ``atan2(0, 0)`` returns +/-pi,
    and the residual starts on the fold cut (+pi/2 instead of -pi/2) with a
    solve slope of -0.0012 rad/deg instead of 0.0175.

    A boundary edge of the strip lies along the contact line, so its U
    direction is the line's direction: the frame is tangential, and its
    midpoint is a point on the contact line, which is exactly where the
    insertion measurement wants to be.
    """
    support = getattr(foot_shell, "Support", None)
    shape = getattr(support, "Shape", None)
    if shape is not None and len(getattr(shape, "Edges", [])) >= 1:
        return (support, ["Edge1"])
    return (support, ["Face1"])


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
            support=_foot_contact_edge_support(foot_shell),
            master_shell=panel,
            attachment_shell=foot_shell,
            direct_contact=True,
            # The foot band is cut from the panel's own faces: one surface,
            # one weave — the rosette is the master's frame by construction,
            # and the warp-continuity solve has nothing to solve.
            shared_surface=True,
        )
        attach_rosette_view_provider(transfer)
    elif hasattr(transfer, "DirectContact"):
        # Existing (e.g. reloaded) transfer: a stiffener insertion is a
        # direct-contact joint, so adopt the cheaper measurement.
        transfer.DirectContact = True
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
            support=_foot_contact_edge_support(foot_shell),
            master_shell=web_shell,
            attachment_shell=foot_shell,
            direct_contact=True,
        )
        attach_rosette_view_provider(rosette)
    elif hasattr(rosette, "DirectContact"):
        rosette.DirectContact = True
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
    # The seam belongs to one joint, so hand it the panel-side surface that
    # joint was cut into.  The panel's own Support pointer chains to the
    # deepest remainder — and is restored to the root while an earlier
    # stiffener re-wires — so the master's live shape can be a surface this
    # joint never touches.  Left unset when the seat consumed the whole
    # support (no remainder), where the live support is the right thing.
    remainder = doc.getObject(f"{fp.Name}_RemainderSupport")
    scl.MasterSupport = (
        remainder
        if remainder is not None and bool(remainder.Shape.Faces)
        else None
    )
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
