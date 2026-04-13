import FreeCAD as App
import FreeCADGui as Gui
import numpy as np
import UtilsAssembly
from FreeCAD import Console
from pivy import coin

from FemLink.LinkBody import LineType, LinkBody
from FemLink.TaskAssemblyLinkBody import TaskAssemblyLinkBody

from .FPBase import VPBase

colors = {
    LineType.FORCE: (1.0, 0.0, 0.0),
    LineType.TORQUE: (0.0, 1.0, 0.0),
    LineType.LINEAR_ACCELERATION: (0.0, 0.0, 1.0),
}


def _rgba_to_rgb255(color_rgba):
    return (
        (color_rgba >> 24) & 0xFF,
        (color_rgba >> 16) & 0xFF,
        (color_rgba >> 8) & 0xFF,
    )


def _view_background_luma_255():
    view_params = App.ParamGet("User parameter:BaseApp/Preferences/View")

    if view_params.GetBool("Gradient", False):
        r1, g1, b1 = _rgba_to_rgb255(view_params.GetUnsigned("BackgroundColor2", 0xC8DCF0FF))
        r2, g2, b2 = _rgba_to_rgb255(view_params.GetUnsigned("BackgroundColor3", 0x445566FF))
        r = (r1 + r2) / 2.0
        g = (g1 + g2) / 2.0
        b = (b1 + b2) / 2.0
    else:
        r, g, b = _rgba_to_rgb255(view_params.GetUnsigned("BackgroundColor", 0xFFFFFFFF))

    # Relative luminance approximation in 0..255 space.
    return r * 0.299 + g * 0.587 + b * 0.114


def _adaptive_text_color_rgb():
    # Dark background -> bright text, bright background -> dark text.
    if _view_background_luma_255() < 128.0:
        return (0.95, 0.95, 0.95)
    return (0.10, 0.10, 0.10)


def make_symbol(p0, p1, mag, line_type: LineType, text_color_rgb, short=False):
    sep = coin.SoSeparator()

    pick = coin.SoPickStyle()
    pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
    sep.addChild(pick)

    color = coin.SoBaseColor()
    color.rgb = colors[line_type]
    sep.addChild(color)

    v1 = np.array(p1) - np.array(p0)
    l1 = np.linalg.norm(v1)

    v0 = np.array([0.0, 1.0, 0.0])

    trans = coin.SbMatrix()
    trans.setTranslate(coin.SbVec3f(*p0))

    rot = coin.SbRotation(coin.SbVec3f(*v0), coin.SbVec3f(*v1))
    rot_mat = coin.SbMatrix()
    rot_mat.setRotate(rot)

    final_mat = rot_mat * trans

    mat_transform = coin.SoMatrixTransform()
    mat_transform.matrix.setValue(final_mat)

    sep.addChild(mat_transform)

    arrow = coin.SoSeparator()

    trans = coin.SoTransform()
    trans.translation.setValue(0.0, l1 / 2, 0.0)
    arrow.addChild(trans)

    text = coin.SoText2()

    match line_type:
        case LineType.FORCE:
            # Assembly dynamics stores force-like terms in kN-equivalent model units.
            text.string.setValue(f"F: {mag * 1000.0:.2E} N")

            cylinder = coin.SoCylinder()
            cylinder.radius.setValue(0.25)
            cylinder.height.setValue(l1)
            arrow.addChild(cylinder)

            trans = coin.SoTransform()
            trans.translation.setValue(0.0, l1 / 2, 0.0)
            arrow.addChild(trans)

            cone = coin.SoCone()
            cone.bottomRadius.setValue(1.0)
            cone.height.setValue(3.0)
            arrow.addChild(cone)

            trans = coin.SoTransform()
            trans.translation.setValue(0.0, 4.0, 0.0)
            arrow.addChild(trans)

        case LineType.TORQUE:
            # Torque-like terms are already in N.m-equivalent model units.
            text.string.setValue(f"T: {mag:.2E} N.m")
            cylinder = coin.SoCylinder()
            cylinder.radius.setValue(0.25)
            cylinder.height.setValue(l1)
            arrow.addChild(cylinder)

            trans = coin.SoTransform()
            trans.translation.setValue(0.0, l1 / 2 - 2.0, 0.0)
            arrow.addChild(trans)

            cone = coin.SoCone()
            cone.bottomRadius.setValue(1.0)
            cone.height.setValue(3.0)
            arrow.addChild(cone)

            trans = coin.SoTransform()
            trans.translation.setValue(0.0, 2.0, 0.0)
            arrow.addChild(trans)

            cone = coin.SoCone()
            cone.bottomRadius.setValue(1.0)
            cone.height.setValue(3.0)
            arrow.addChild(cone)

            trans = coin.SoTransform()
            trans.translation.setValue(0.0, 3.0, 0.0)
            arrow.addChild(trans)

        case _:
            text.string.setValue(f"a: {mag / 1000.0:.2E} m/s/s")

            cylinder = coin.SoCylinder()
            cylinder.radius.setValue(0.25)
            cylinder.height.setValue(l1)
            arrow.addChild(cylinder)

            trans = coin.SoTransform()
            trans.translation.setValue(0.0, l1 / 2, 0.0)
            arrow.addChild(trans)

            sphere = coin.SoSphere()
            sphere.radius.setValue(1.0)
            arrow.addChild(sphere)

            trans = coin.SoTransform()
            trans.translation.setValue(0.0, 1.0, 0.0)
            arrow.addChild(trans)

    color = coin.SoBaseColor()
    color.rgb = text_color_rgb
    arrow.addChild(color)
    arrow.addChild(text)
    sep.addChild(arrow)

    return sep


class VPLinkBody(VPBase):

    def __init__(self, obj):
        super().__init__(obj)

        obj.addProperty(
            "App::PropertyFloat",
            "ForceScale",
            "Scaling of force arrows",
            locked=True,
        ).ForceScale = 1.0

        obj.addProperty(
            "App::PropertyFloat",
            "TorqueScale",
            "Scaling of torque arrows",
            locked=True,
        ).TorqueScale = 1.0

        obj.addProperty(
            "App::PropertyFloat",
            "AccelerationScale",
            "Scaling of acceleration arrows",
            locked=True,
        ).AccelerationScale = 1.0

    def getIcon(self):
        return ":/icons/FemLink_LinkBody.svg"

    def doubleClicked(self, vobj):
        App.closeActiveTransaction(True)  # Close the auto-transaction

        task = Gui.Control.activeTaskDialog()
        if task:
            task.reject()

        assembly = vobj.Object.Proxy.getAssembly(vobj.Object)

        if assembly is None:
            return False

        if UtilsAssembly.activeAssembly() != assembly:
            vobj.Document.setEdit(assembly)

        panel = TaskAssemblyLinkBody(vobj.Object)
        dialog = Gui.Control.showDialog(panel)
        if dialog is not None:
            dialog.setAutoCloseOnTransactionChange(True)
            dialog.setAutoCloseOnDeletedDocument(True)
            dialog.setDocumentName(App.ActiveDocument.Name)

        return True

    def attach(self, vobj):
        self.Object = vobj.Object
        self.ViewObject = vobj
        group = coin.SoGroup()
        # self.switch = coin.SoSwitch()
        self.symbol_set = coin.SoSeparator()
        # self.switch.addChild(self.symbol_set)
        # group.addChild(self.switch)
        self.font = coin.SoFont()
        self.font.name = "osifont:Italic"
        self.font.size.setValue(32.0)
        group.addChild(self.font)

        sep = coin.SoSeparator()
        self.transform = coin.SoMatrixTransform()
        sep.addChild(self.transform)
        self.pick = coin.SoPickStyle()
        self.setPickableState(False)
        sep.addChild(self.pick)
        sep.addChild(self.symbol_set)
        group.addChild(sep)

        vobj.addDisplayMode(group, "Symbol")
        self.symbols = []

    def setPickableState(self, state: bool):
        if not state:
            self.pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
        else:
            self.pick.style.setValue(coin.SoPickStyle.SHAPE_ON_TOP)

    def updateData(self, vobj, prop):
        def setPlacement():
            placement = self.Object.Proxy.getBodyPlacement(self.Object.Body)
            self.transform.matrix.setValue(*placement.Matrix.transposed().A)

        setPlacement()

        for symbol in self.symbols:
            self.symbol_set.removeChild(symbol)
        self.symbols = []

        for p0, v, line_type in getattr(self.Object.Proxy, "line_info", []):
            p1 = p0

            def is_short():
                return (p1 - p0).Length < 1.0

            match line_type:
                case LineType.FORCE:
                    p1 += v * self.Object.ViewObject.ForceScale
                case LineType.TORQUE:
                    p1 += v * self.Object.ViewObject.TorqueScale
                    if is_short():
                        continue
                case LineType.LINEAR_ACCELERATION:
                    mass = self.Object.Proxy.getMass(self.Object)
                    p1 -= v * self.Object.ViewObject.AccelerationScale * mass
                case _:
                    pass

            text_color_rgb = _adaptive_text_color_rgb()
            sep = make_symbol(p0, p1, v.Length, line_type, text_color_rgb, short=is_short())
            self.symbols.append(sep)
            self.symbol_set.addChild(sep)

    def getDisplayModes(self, obj):
        modes = ["Symbol"]
        return modes

    def getDefaultDisplayMode(self):
        return "Symbol"

    def setDisplayMode(self, mode):
        return mode

    def show_coin(self, show):
        if show:
            self.switch.whichChild.setValue(coin.SO_SWITCH_ALL)
        else:
            self.switch.whichChild.setValue(coin.SO_SWITCH_NONE)

    def scale(
        self,
        force_max: float = 0,
        torque_max: float = 0,
        linear_acceleration_max: float = 0,
        physical_scale: float = 100.0,
    ):
        vobj = self.ViewObject
        f_max = max(force_max, linear_acceleration_max)
        if f_max > 0:
            vobj.ForceScale = physical_scale / f_max
            vobj.AccelerationScale = physical_scale / f_max
        if torque_max > 0:
            vobj.TorqueScale = physical_scale / torque_max
