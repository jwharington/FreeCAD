from .VPCompositeBase import (
    CompositeBaseFP,
    VPCompositeBase,
)


class CompositePartFP(CompositeBaseFP):
    pass


class VPCompositePart(VPCompositeBase):
    def attach(self, vobj):
        # Chain the base attach: it registers a display-mode branch
        # ("Standard") on the view provider. Without it no branch exists
        # and the C++ ModeSwitch can point at a nonexistent mode — the
        # feature's shape then renders nothing (the texture plan greys
        # out, seen 2026-09-18).
        super().attach(vobj)
        self.Object = vobj.Object
        self.ViewObject = vobj

    def getDisplayModes(self, obj):
        return ["Flat Lines", "Wireframe"]

    def getDefaultDisplayMode(self) -> str:
        return "Flat Lines"

    def setDisplayMode(self, mode):
        return mode
