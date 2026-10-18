# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

from typing import List

from ..objects.lamina import Lamina
from ..util.geometry_util import format_layer, normalise_orientation
from .stack_model import merge_clt
from .stack_model_type import StackModelType


def merge_layers(
    prefix: str,
    layers: List[Lamina],
    exclude_core: bool,
) -> List[Lamina]:
    if len(layers) == 1:
        return layers

    has_core = sum([lay.core for lay in layers])

    if exclude_core and has_core:
        res = []
        buf = layers.copy()
        k = 0
        while buf:
            try:
                i = [lay.core for lay in buf].index(True)
                res.append(
                    merge_clt(
                        format_layer(prefix, k),
                        buf[0:i],
                    )
                )
                res.append(buf[i])
                if len(buf) > 1 + i:
                    buf = buf[i + 1 :]  # noqa
                else:
                    buf = []
            except Exception:
                res.append(
                    merge_clt(
                        format_layer(prefix, k),
                        buf,
                    )
                )
                buf = []
            k += 1
        return res
    elif has_core:
        return [merge_clt(prefix, layers, sandwich=True)]
    else:
        return [merge_clt(prefix, layers)]


def _is_palindromic(plies: List[Lamina]) -> bool:
    for a, b in zip(plies, plies[::-1]):
        if (
            normalise_orientation(a.orientation)
            != normalise_orientation(b.orientation)
            or a.thickness != b.thickness
            or a.core != b.core
        ):
            return False
    return True


def _group_sizes(plies: List[Lamina], groups: int) -> List[int]:
    """Ply counts per band: contiguous, roughly equal thickness, at most
    `groups` bands."""
    n = len(plies)
    if n == 0 or groups <= 1:
        return [n]
    if n <= groups:
        return [1] * n
    target = sum(ply.thickness for ply in plies) / groups
    sizes, count, acc = [], 0, 0.0
    for i, ply in enumerate(plies):
        count += 1
        acc += ply.thickness
        remaining, bands_left = n - (i + 1), groups - 1
        # start a new band when the current one has reached the target and
        # enough plies remain to fill the remaining bands
        if acc >= target and remaining >= bands_left:
            sizes.append(count)
            count, acc = 0, 0.0
    if count:
        sizes.append(count)
    return sizes


def _mirror_counts(counts: List[int], center: bool) -> List[int]:
    mirrored = counts[::-1]
    if center:
        # the mid ply rides with the inner band on its side
        mirrored[0] += 1
    return mirrored


def _split(plies: List[Lamina], counts: List[int]) -> List[List[Lamina]]:
    out, start = [], 0
    for count in counts:
        out.append(plies[start : start + count])
        start += count
    return out


def _partition_stack_groups(plies: List[Lamina], groups: int) -> List[int]:
    """Band sizes for a core-free stack: palindromic inputs get mirrored
    boundaries so band i holds the mirror of band n-1-i (B stays ~ 0, as
    the discrete stack has it)."""
    if len(plies) > groups and groups % 2 == 0 and _is_palindromic(plies):
        center = len(plies) % 2 == 1
        half = plies[: len(plies) // 2]
        left = _group_sizes(half, groups // 2)
        return left + _mirror_counts(left, center)
    return _group_sizes(plies, groups)


def merge_layers_grouped(
    prefix: str,
    layers: List[Lamina],
    groups: int = 4,
) -> List[Lamina]:
    """Merge a flat stack into `groups` layers, a core staying its own layer.

    Bands are contiguous and roughly equal in thickness (position, not
    angle): lumping like angles together would move stiffness through the
    thickness and degrade D, which is the whole point of not using
    `Smeared`.  Cores are emitted unmerged and do not count against
    `groups`, so a cored stack presents `groups + 1` layers.
    """
    core_mask = [lay.core for lay in layers]
    counts = _partition_stack_groups([lay for lay in layers if not lay.core], groups)
    res, band, k, b = [], [], 0, 0
    for i, lay in enumerate(layers):
        if core_mask[i]:
            if band:
                res.append(
                    merge_clt(
                        format_layer(prefix, k),
                        band,
                        sandwich=True,
                    )
                )
                k, b = k + 1, b + 1
                band = []
            # a core is presented as itself, unmerged (merge_layers does
            # the same with exclude_core)
            res.append(lay)
            k += 1
        else:
            band.append(lay)
            if len(band) == counts[b]:
                res.append(
                    merge_clt(
                        format_layer(prefix, k),
                        band,
                        sandwich=any(ply.core for ply in band),
                    )
                )
                k, b = k + 1, b + 1
                band = []
    if band:
        res.append(
            merge_clt(
                format_layer(prefix, k),
                band,
                sandwich=any(ply.core for ply in band),
            )
        )
    return res


def flatten_nested(
    prefix: str,
    layers: List[Lamina],
    res: List[Lamina],
    merge_depth: int = 0,
    depth: int = 0,
    exclude_core: bool = False,
):
    res_list = []
    k = 0
    for la in layers:
        if type(la) is list:
            res_inner = []
            flatten_nested(
                format_layer(prefix, k),
                la,
                res_inner,
                merge_depth=merge_depth,
                depth=depth + 1,
                exclude_core=exclude_core,
            )
            k += 1
            res_list.extend(res_inner)
        else:
            res_list.append(la)

    if depth == merge_depth:
        res_list = merge_layers(
            prefix,
            res_list,
            exclude_core=exclude_core,
        )
    res.extend(res_list)


def calc_stack_model(
    prefix: str,
    model_type: StackModelType,
    layers: List[Lamina],
) -> List[Lamina]:
    res = []
    if StackModelType.Discrete == model_type:
        # full expansion, no merging
        flatten_nested(prefix, layers, res, -1)
    elif StackModelType.SmearedFabric == model_type:
        flatten_nested(prefix, layers, res, 1)
    elif StackModelType.SmearedCore == model_type:
        flatten_nested(prefix, layers, res, 0, exclude_core=True)
    elif StackModelType.Smeared == model_type:
        flatten_nested(prefix, layers, res, 0, exclude_core=False)
    elif StackModelType.SmearedGroups == model_type:
        # full expansion to plies, then merge into `groups` positional bands
        flatten_nested(prefix, layers, res, -1)
        res = merge_layers_grouped(prefix, res)
    else:
        raise ValueError(f"Unhandled model_type {model_type}")

    return res
