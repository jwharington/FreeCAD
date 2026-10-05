"""A seam joint must not recompute while its document is being restored.

The joint recomputes itself on every reference change, because a plain
value change does not propagate through ``doc.recompute()``.  Document
restore writes those same references, and they arrive *before* the
joint's own properties — so the recompute executed against an object
that could not answer for itself, and a saved document opened with
those joints in error (six of them, on the fuselage).
"""
import pytest

from Composites.features.SeamCompositeLaminate import SeamCompositeLaminateFP


class _Wired:
    """A joint with every reference in place, counting recomputes."""

    def __init__(self, restoring=True, wired=True):
        self.Document = _Document(restoring)
        self.Master = _Master() if wired else None
        self.Attachment = object() if wired else None
        self.SeamRegion = object() if wired else None
        self.MasterTransfer = object() if wired else None
        self.AttachmentTransfer = object() if wired else None
        self.recomputes = 0

    def recompute(self):
        self.recomputes += 1


class _Document:
    def __init__(self, restoring):
        self.Restoring = restoring


class _Master:
    """A panel shell: the joint reads its laminate back off it."""


def proxy():
    # onChanged reads no instance state of its own, so the class body can
    # be exercised without building a document object around it.
    return SeamCompositeLaminateFP.__new__(SeamCompositeLaminateFP)


@pytest.mark.parametrize("prop", [
    "Master",
    "Attachment",
    "SeamRegion",
    "MasterTransfer",
    "AttachmentTransfer",
])
def test_a_reference_written_mid_restore_recomputes_nothing(prop):
    joint = _Wired(restoring=True)
    proxy().onChanged(joint, prop)
    assert joint.recomputes == 0


@pytest.mark.parametrize("prop", [
    "Master",
    "Attachment",
    "SeamRegion",
    "MasterTransfer",
    "AttachmentTransfer",
])
def test_the_same_reference_after_restore_recomputes_once(prop):
    joint = _Wired(restoring=False)
    proxy().onChanged(joint, prop)
    assert joint.recomputes == 1


def test_a_half_wired_joint_recomputes_nothing():
    joint = _Wired(restoring=False, wired=False)
    proxy().onChanged(joint, "Master")
    assert joint.recomputes == 0


def test_an_unrelated_property_recomputes_nothing():
    joint = _Wired(restoring=False)
    proxy().onChanged(joint, "Label")
    assert joint.recomputes == 0
