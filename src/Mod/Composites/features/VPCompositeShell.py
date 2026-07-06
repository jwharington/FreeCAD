# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""ViewProvider for the CompositeShell feature.

Hosts the draped-mesh Coin3D geometry in a dedicated SoSwitch
(``drape_host``) on the ViewProvider's own RootNode, and manages
the GLSL grid shader overlay.
"""

from pivy import coin

from .. import COMPOSITE_SHELL_TOOL_ICON


class ViewProviderCompositeShell:
    def __init__(self, obj):
        # Lazy import to avoid GUI dependency in headless mode
        from ..shaders.MeshGridShader import MeshGridShader

        self.grid_shader = MeshGridShader()
        self._last_offset_angle_deg = None

        obj.addProperty(
            "App::PropertyFloatConstraint",
            "Darken",
            "AnalysisOptions",
            "Grid darkness",
        )
        obj.Darken = 0.5

        obj.addProperty(
            "App::PropertyBool",
            "ShowRosette",
            "Rosette",
            "Show fibre orientation rosette symbol in 3D view",
        )
        obj.ShowRosette = True

        obj.addProperty(
            "App::PropertyFloat",
            "RosetteScale",
            "Rosette",
            "Radius of fibre orientation rosette symbol (mm)",
        )
        obj.RosetteScale = 20.0

        obj.Proxy = self

    def setDisplayMode(self, mode):
        return mode

    def getDisplayModes(self, obj):
        return [
            "Shaded",
            "Wireframe",
            "Flat Lines",
            "Points",
            "Strain XX",
            "Strain YY",
            "Strain XY",
        ]

    def getDefaultDisplayMode(self):
        return "Shaded"

    def getIcon(self):
        return COMPOSITE_SHELL_TOOL_ICON

    def claimChildren(self):
        children = []
        if hasattr(self.Object, "Rosette") and self.Object.Rosette:
            children.append(self.Object.Rosette)
        if hasattr(self.Object, "LocalCoordinateSystem") and self.Object.LocalCoordinateSystem:
            children.append(self.Object.LocalCoordinateSystem)
        return children

    def attach(self, obj):
        self.Active = False

        self.ViewObject = obj
        self.Object = obj.Object

        # Lazily create grid_shader if deserialized from file (__init__ skipped)
        if not hasattr(self, "grid_shader"):
            from ..shaders.MeshGridShader import MeshGridShader
            self.grid_shader = MeshGridShader()
        if not hasattr(self, "_last_offset_angle_deg"):
            self._last_offset_angle_deg = None

        # Drape geometry + shader live in a dedicated SoSwitch on this
        # ViewProvider's RootNode (Part ViewProvider only rebuilds the
        # display-mode Switch, not direct RootNode children).
        self.drape_host = coin.SoSwitch()
        self.drape_host.setName("DrapeHost")
        self.drape_host.whichChild = coin.SO_SWITCH_ALL
        try:
            obj.RootNode.addChild(self.drape_host)
        except AttributeError:
            pass  # RootNode not available in non-GUI / test environments

        # Always hide the native LCS symbology (planes + 3D arrows);
        # the rosette disk+arrows provide the same orientation info
        # without cluttering the view.
        self._hide_lcs(obj.Object)

        # Add DisplayLayer property to ViewObject (enumeration for layer
        # selection dropdown). Must be added here because FreeCAD mirrors
        # App::PropertyEnumeration from the FeaturePython to the ViewObject
        # but adds the 'hidden' flag on mirroring.
        if not hasattr(obj, "DisplayLayer"):
            obj.addProperty(
                "App::PropertyEnumeration",
                "DisplayLayer",
                "AnalysisOptions",
                "Select layer to display",
            )
            obj.DisplayLayer = ["0"]
            obj.DisplayLayer = "0"

        # Fibre orientation rosette: always-visible overlay on the root node
        from .RosetteSymbol import RosetteSymbol

        self.rosette = RosetteSymbol()
        self.rosette_switch = coin.SoSwitch()
        self.rosette_switch.addChild(self.rosette.separator)
        self.rosette_switch.whichChild = 0  # visible by default
        try:
            obj.RootNode.addChild(self.rosette_switch)
        except AttributeError:
            pass  # RootNode not available in non-GUI / test environments

        # needed to trigger color update
        self.onChanged(obj, "Color")

    def update_display_layer(self, fp):
        if not hasattr(fp.ViewObject, "DisplayLayer"):
            return
        display_layer_opts = list(fp.Laminate.StackOrientation.keys())
        sel = fp.ViewObject.DisplayLayer
        fp.ViewObject.DisplayLayer = display_layer_opts
        if sel in display_layer_opts:
            return
        if display_layer_opts:
            fp.ViewObject.DisplayLayer = display_layer_opts[0]

    def _hide_lcs(self, fp):
        """Always hide the native LCS symbology (planes + 3D arrows)."""
        lcs = fp.LocalCoordinateSystem
        if lcs is None and fp.Rosette:
            lcs = fp.Rosette.LocalCoordinateSystem
        if lcs is None:
            return
        lcs_vobj = getattr(lcs, "ViewObject", None)
        if lcs_vobj is not None:
            lcs_vobj.Visibility = False

    def update_visibility(self, vobj):
        visible = vobj.Visibility
        drape_host = getattr(self, "drape_host", None)
        if drape_host is not None:
            try:
                drape_host.whichChild = coin.SO_SWITCH_ALL if visible else coin.SO_SWITCH_NONE
            except Exception:
                pass
        self._set_shell_transparency(vobj)
        if self.Object.Support:
            self.Object.Support.Visibility = visible

    def _set_shell_transparency(self, vobj):
        """Make the shell semi-transparent when drape geometry is present."""
        has_drape = getattr(self, "drape_host", None) is not None and self.drape_host.getNumChildren() > 0
        try:
            vobj.Transparency = 50 if has_drape else 0
        except Exception:
            pass

    def update_mesh_material(self, vobj):
        """Update strain visualization colors based on display mode."""
        self.update_visibility(vobj)
        
        # Get the current display mode and map to strain component
        display_mode = getattr(vobj, "DisplayMode", "")
        if display_mode not in ("Strain XX", "Strain YY", "Strain XY"):
            return
        
        # Get strain data from the backend
        obj = vobj.Object
        if not hasattr(obj, "Proxy") or not hasattr(obj.Proxy, "_backend"):
            return
        backend = obj.Proxy._backend
        if not backend or not backend.is_valid():
            return
        
        strains = backend.strains
        if strains is None or strains.size == 0:
            return
        
        # Map display mode to strain component
        mode_map = {"Strain XX": "XX", "Strain YY": "YY", "Strain XY": "XY"}
        mode = mode_map.get(display_mode, "XX")
        
        # Apply strain colors to the shader
        if hasattr(self, "grid_shader") and self.grid_shader:
            self.grid_shader.set_strain_colors(strains, mode)

    def updateData(self, fp, prop):
        match prop:
            case "LocalCoordinateSystem" | "Support" | "Rosette":
                self.update_rosette(self.ViewObject)
            case "Laminate":
                if fp.Laminate:
                    self.update_display_layer(fp)
                self.update_rosette(self.ViewObject)
            case _:
                return

        if prop == "Laminate" and self._apply_layer_orientation(fp):
            return

        self.reload_shader()

    def update_rosette(self, vobj):
        """Rebuild the rosette symbol from the current laminate and LCS."""
        if not hasattr(self, "rosette"):
            return
        obj = vobj.Object
        laminate = obj.Laminate
        if not laminate or not hasattr(laminate, "StackOrientation"):
            return
        stack_orientation = laminate.StackOrientation
        if not hasattr(stack_orientation, "values"):
            return

        orientations = list(stack_orientation.values())
        if not orientations:
            return

        lcs = None
        if obj.Rosette:
            lcs = obj.Rosette.LocalCoordinateSystem
        elif obj.LocalCoordinateSystem:
            lcs = obj.LocalCoordinateSystem

        if lcs:
            base = lcs.Placement.Base
            position = (base.x, base.y, base.z)
            q = lcs.Placement.Rotation.Q
            rotation = (q[0], q[1], q[2], q[3])
        else:
            position = (0.0, 0.0, 0.0)
            rotation = (0.0, 0.0, 0.0, 1.0)

        scale = vobj.RosetteScale if hasattr(vobj, "RosetteScale") else 20.0
        self.rosette.update(orientations, position, rotation, scale)

    def onChanged(self, vobj, prop):
        match prop:
            case "Visibility":
                self.update_visibility(vobj)
            case "DisplayMode":
                self.update_mesh_material(vobj)
            case "Darken":
                pass
            case "DisplayLayer":
                feature_obj = getattr(vobj, "Object", None) or getattr(self, "Object", None)
                if feature_obj is None or not self._apply_layer_orientation(feature_obj):
                    self.reload_shader()
            case "ShapeAppearance":
                self._set_shell_transparency(vobj)
            case "ShowRosette":
                if hasattr(self, "rosette_switch"):
                    self.rosette_switch.whichChild = (
                        0 if vobj.ShowRosette else coin.SO_SWITCH_NONE
                    )
            case "RosetteScale":
                self.update_rosette(vobj)
            case _:
                pass

    def onDelete(self, vobj, sub):
        self.remove_shader()
        return True

    def reload_shader(self):
        if getattr(self, "_reloading", False):
            return
        self._reloading = True
        try:
            self.remove_shader()
            self.load_shader()
        finally:
            self._reloading = False

    def get_offset_angle(self, vobj):
        if not hasattr(vobj.ViewObject, "DisplayLayer"):
            return 0.0
        if not vobj.Laminate:
            return 0.0

        layer = vobj.ViewObject.DisplayLayer
        stack_orientation = getattr(vobj.Laminate, "StackOrientation", {}) or {}

        key = None
        if layer in stack_orientation:
            key = layer
        else:
            layer_str = str(layer)
            if layer_str in stack_orientation:
                key = layer_str
            else:
                for existing_key in stack_orientation.keys():
                    if str(existing_key) == layer_str:
                        key = existing_key
                        break

        if key is None:
            return 0.0

        try:
            return float(stack_orientation[key])
        except (TypeError, ValueError):
            return 0.0

    def _apply_layer_orientation(self, vobj):
        """Update UV rotation in-place when shader is already attached."""
        shader = getattr(self, "grid_shader", None)
        if shader is None or not getattr(shader, "_attached", False):
            return False

        offset_angle_deg = self.get_offset_angle(vobj)
        if self._last_offset_angle_deg is not None and abs(self._last_offset_angle_deg - offset_angle_deg) < 1e-9:
            return True

        shader.set_offset_angle(offset_angle_deg)
        self._last_offset_angle_deg = offset_angle_deg

        view_obj = getattr(vobj, "ViewObject", None)
        if view_obj is not None:
            try:
                view_obj.update()
            except Exception:
                pass
        return True

    def load_shader(self):
        try:
            if self.Active:
                return
            if hasattr(self, "grid_shader") and self.grid_shader and self.grid_shader._attached:
                return
            vobj = self.Object
            obj = vobj.Proxy

            if not hasattr(obj, "_backend") or obj._backend is None:
                return

            drape_host = getattr(self, "drape_host", None)
            if drape_host is None:
                return

            tex_coords = obj._backend.get_tex_coords()
            if tex_coords is None or len(tex_coords) == 0:
                return

            offset_angle_deg = self.get_offset_angle(vobj)
            if not hasattr(self, "grid_shader"):
                from ..shaders.MeshGridShader import MeshGridShader
                self.grid_shader = MeshGridShader()
            if self.grid_shader:
                self.grid_shader.attach(
                    drape_host,
                    tex_coords,
                    offset_angle_deg,
                )
                self._last_offset_angle_deg = offset_angle_deg
                self.Active = True
                import FreeCADGui

                FreeCADGui.Selection.addObserver(self)
        except Exception as e:
            import traceback
            print(f'load_shader ERROR: {e}')
            traceback.print_exc()

    def remove_shader(self):
        if not self.Active:
            return
        if hasattr(self, "grid_shader"):
            try:
                self.grid_shader.detach()
            except Exception:
                pass
        self.Active = False
        self._last_offset_angle_deg = None
        try:
            import FreeCADGui
            FreeCADGui.Selection.removeObserver(self)
        except Exception:
            pass

    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        return None
