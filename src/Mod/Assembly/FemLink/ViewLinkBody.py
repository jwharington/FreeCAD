import FreeCAD as App
import FreeCADGui as Gui
import numpy as np
import UtilsAssembly
from pivy import coin

from FemLink.LinkBody import LineType
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
            # Assembly joint reactions are exposed in N.
            text.string.setValue(f"F: {mag:.2E} N")

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
            # Assembly/FEM model units are mm, N, s; convert N*mm -> N.m for display.
            text.string.setValue(f"T: {mag / 1000.0:.2E} N.m")
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

        frame_prop = obj.addProperty(
            "App::PropertyEnumeration",
            "Frame",
            "Rendering frame for symbols",
            locked=True,
        )
        frame_prop.Frame = ["Body", "Global"]
        frame_prop.Frame = "Body"

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

    def _setPlacementForFrame(self):
        frame = getattr(self.Object.ViewObject, "Frame", "Body")
        if frame == "Global":
            matrix = App.Matrix()
        else:
            matrix = self.Object.Proxy.getBodyPlacement(self.Object.Body).Matrix
        self.transform.matrix.setValue(*matrix.transposed().A)

    @staticmethod
    def _to_numpy_xyz(point):
        if hasattr(point, "x"):
            return np.array([point.x, point.y, point.z], dtype=float)
        return np.array([point[0], point[1], point[2]], dtype=float)

    def _find_jig_supports(self):
        body = getattr(self.Object, "Body", None)
        if body is None or not hasattr(body, "getLinkedObject"):
            return []

        body_obj = body.getLinkedObject()
        if body_obj is None:
            return []

        doc = getattr(self.Object, "Document", None)
        if doc is None:
            return []

        for obj in getattr(doc, "Objects", []):
            proxy = getattr(obj, "Proxy", None)
            if not proxy or getattr(proxy, "Type", "") != "Fem::ConstraintJig321":
                continue

            refs = getattr(obj, "References", [])
            for ref in refs:
                if not ref:
                    continue
                ref_obj = ref[0] if isinstance(ref, (tuple, list)) else None
                if ref_obj != body_obj:
                    continue

                supports = getattr(obj, "Supports", [])
                if supports and len(supports) >= 3:
                    return supports
        return []

    def _add_jig_arrow(self, origin, direction, color, arr_len, arr_head):
        sep = coin.SoSeparator()
        mat = coin.SoBaseColor()
        mat.rgb.setValue(color)
        sep.addChild(mat)

        draw_style = coin.SoDrawStyle()
        draw_style.lineWidth = 2.0
        sep.addChild(draw_style)

        end = origin + direction * arr_len
        coords = coin.SoCoordinate3()
        coords.point.set1Value(0, *origin)
        coords.point.set1Value(1, *end)
        sep.addChild(coords)

        line = coin.SoLineSet()
        line.numVertices.setValue(2)
        sep.addChild(line)

        side = np.cross(direction, np.array([0.2, 0.2, 0.2], dtype=float))
        if np.linalg.norm(side) <= 1.0e-12:
            side = np.cross(direction, np.array([0.0, 0.0, 1.0], dtype=float))
        side_norm = np.linalg.norm(side)
        if side_norm > 1.0e-12:
            side = side / side_norm

        head1 = end - direction * arr_head + side * (arr_head * 0.5)
        head2 = end - direction * arr_head - side * (arr_head * 0.5)

        head_coords = coin.SoCoordinate3()
        head_coords.point.set1Value(0, *end)
        head_coords.point.set1Value(1, *head1)
        head_coords.point.set1Value(2, *end)
        head_coords.point.set1Value(3, *head2)
        sep.addChild(head_coords)

        head_lines = coin.SoLineSet()
        head_lines.numVertices.setValues(0, 2, [2, 2])
        sep.addChild(head_lines)

        self.symbols.append(sep)
        self.symbol_set.addChild(sep)

    def _add_jig_point_marker(self, origin, color, radius):
        sep = coin.SoSeparator()
        mat = coin.SoBaseColor()
        mat.rgb.setValue(color)
        sep.addChild(mat)

        tr = coin.SoTranslation()
        tr.translation.setValue(float(origin[0]), float(origin[1]), float(origin[2]))
        sep.addChild(tr)

        sphere = coin.SoSphere()
        sphere.radius = radius
        sep.addChild(sphere)

        self.symbols.append(sep)
        self.symbol_set.addChild(sep)

    def _render_jig321_symbols(self):
        supports = self._find_jig_supports()
        if len(supports) < 3:
            return

        # Keep the same convention as VPConstraintJig321:
        # 3 = supports[0], 2 = supports[1], 1 = supports[2].
        p3 = self._to_numpy_xyz(supports[0])
        p2 = self._to_numpy_xyz(supports[1])
        p1 = self._to_numpy_xyz(supports[2])

        x_axis = p3 - p2
        x_norm = np.linalg.norm(x_axis)
        x_axis = x_axis / x_norm if x_norm > 1.0e-12 else np.array([1.0, 0.0, 0.0])

        y_axis = p3 - p1
        y_axis = y_axis - np.dot(y_axis, x_axis) * x_axis
        y_norm = np.linalg.norm(y_axis)
        y_axis = y_axis / y_norm if y_norm > 1.0e-12 else np.array([0.0, 1.0, 0.0])

        z_axis = np.cross(x_axis, y_axis)
        z_norm = np.linalg.norm(z_axis)
        z_axis = z_axis / z_norm if z_norm > 1.0e-12 else np.array([0.0, 0.0, 1.0])

        support_span = max(
            np.linalg.norm(p3 - p2),
            np.linalg.norm(p3 - p1),
            np.linalg.norm(p2 - p1),
        )
        arr_len = max(25.0, 0.15 * support_span)
        arr_head = 0.2 * arr_len

        # Draw at p3: x, y, z
        self._add_jig_arrow(p3, x_axis, (1, 0, 0), arr_len, arr_head)
        self._add_jig_arrow(p3, y_axis, (0, 1, 0), arr_len, arr_head)
        self._add_jig_arrow(p3, z_axis, (0, 0, 1), arr_len, arr_head)
        # Draw at p2: y, z
        self._add_jig_arrow(p2, y_axis, (0, 1, 0), arr_len, arr_head)
        self._add_jig_arrow(p2, z_axis, (0, 0, 1), arr_len, arr_head)
        # Draw at p1: z
        self._add_jig_arrow(p1, z_axis, (0, 0, 1), arr_len, arr_head)

        marker_radius = max(3.0, 0.06 * arr_len)
        self._add_jig_point_marker(p3, (1, 1, 0), marker_radius)
        self._add_jig_point_marker(p2, (1, 1, 0), marker_radius)
        self._add_jig_point_marker(p1, (1, 1, 0), marker_radius)

    def onChanged(self, vobj, prop):
        if prop in {"Frame", "ForceScale", "TorqueScale", "AccelerationScale"}:
            self.updateData(self.Object, prop)

    def updateData(self, vobj, prop):
        self._setPlacementForFrame()

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
                    acc_vec = -(v * self.Object.ViewObject.AccelerationScale * mass)
                    # Keep very small acceleration arrows readable.
                    # (Force arrows already have larger cone heads; accel uses a small sphere.)
                    min_visual_length = 2.0
                    if v.Length > 0.0 and acc_vec.Length < min_visual_length:
                        acc_vec *= min_visual_length / max(acc_vec.Length, 1.0e-16)
                    p1 += acc_vec
                case _:
                    pass

            text_color_rgb = _adaptive_text_color_rgb()
            sep = make_symbol(p0, p1, v.Length, line_type, text_color_rgb, short=is_short())
            self.symbols.append(sep)
            self.symbol_set.addChild(sep)

        self._render_jig321_symbols()

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

        # Scale force and acceleration independently so one channel cannot
        # collapse the other to near-zero visual length.
        if force_max > 0:
            vobj.ForceScale = physical_scale / force_max
        elif linear_acceleration_max > 0:
            # Fallback keeps force vectors visible when force_max is unavailable.
            vobj.ForceScale = physical_scale / linear_acceleration_max

        if linear_acceleration_max > 0:
            vobj.AccelerationScale = physical_scale / linear_acceleration_max
        elif force_max > 0:
            # Fallback keeps acceleration vectors visible when only forces exist.
            vobj.AccelerationScale = physical_scale / force_max

        if torque_max > 0:
            vobj.TorqueScale = physical_scale / torque_max
