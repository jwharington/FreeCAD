# SPDX-License-Identifier: LGPL-2.1-or-later
import math
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
            "App::PropertyBool",
            "ScreenSpaceGrid",
            "Rosette",
            "Use screen-space zoom-stable grid lines",
        )
        obj.ScreenSpaceGrid = True

        obj.addProperty(
            "App::PropertyFloat",
            "RosetteScale",
            "Rosette",
            "Radius of fibre orientation rosette symbol (mm)",
        )
        obj.RosetteScale = 20.0

        obj.Proxy = self
        self.attach(obj)

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
        if not hasattr(self, "Object"):
            return children
        lcs = getattr(self.Object, "LocalCoordinateSystem", None)
        if lcs is None and self.Object.Rosette:
            lcs = getattr(self.Object.Rosette, "LocalCoordinateSystem", None)
        if lcs is not None:
            children.append(lcs)
        return children

    def attach(self, obj):
        # Idempotent: skip if already attached (e.g. __init__ called attach,
        # then FreeCAD's C++ machinery calls attach() again).
        if hasattr(self, "drape_host") and self.drape_host is not None:
            return

        self.Active = False

        self.ViewObject = obj
        self.Object = obj.Object

        # Lazily create grid_shader if deserialized from file (__init__ skipped)
        if not hasattr(self, "grid_shader"):
            from ..shaders.MeshGridShader import MeshGridShader
            self.grid_shader = MeshGridShader()

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
        lcs = getattr(fp, "LocalCoordinateSystem", None)
        if lcs is None and fp.Rosette:
            lcs = getattr(fp.Rosette, "LocalCoordinateSystem", None)
        if lcs is None:
            return
        lcs_vobj = getattr(lcs, "ViewObject", None)
        if lcs_vobj is not None:
            lcs_vobj.Visibility = False

    def update_visibility(self, vobj):
        if not hasattr(self, "Object"):
            return
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
        """Make the shell semi-transparent when drape geometry is present.

        Skip when the shader is active — the fragment shader controls
        per-fragment alpha (grid lines opaque, background transparent).
        Setting vobj.Transparency forces FILTER mode which overrides
        the shader's BLEND transparency and kills per-fragment alpha.
        """
        has_shader = getattr(self, "grid_shader", None) is not None and getattr(self.grid_shader, "_attached", False)
        has_drape = getattr(self, "drape_host", None) is not None and self.drape_host.getNumChildren() > 0
        try:
            vobj.Transparency = 0 if has_shader else (50 if has_drape else 0)
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
        if not hasattr(self, "ViewObject"):
            return
        match prop:
            case "LocalCoordinateSystem" | "Support" | "Rosette":
                self.update_rosette(self.ViewObject)
            case "Laminate":
                if fp.Laminate:
                    self.update_display_layer(fp)
                self.update_rosette(self.ViewObject)
            case _:
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
            lcs = getattr(obj.Rosette, "LocalCoordinateSystem", None)
        if lcs is None:
            lcs = getattr(obj, "LocalCoordinateSystem", None)

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
                self.reload_shader()
            case "ShapeAppearance":
                self._set_shell_transparency(vobj)
            case "ScreenSpaceGrid":
                if hasattr(self, "grid_shader") and self.grid_shader:
                    self.grid_shader.detach()
                    self.grid_shader._attached = False
                self.Active = False
                self.load_shader()
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
            return 0
        layer = vobj.ViewObject.DisplayLayer
        if not vobj.Laminate:
            return 0
        if layer in vobj.Laminate.StackOrientation:
            return int(vobj.Laminate.StackOrientation[layer])
        return 0

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
                self.grid_shader.ScreenSpace = bool(self.ViewObject.ScreenSpaceGrid)
                self.grid_shader.attach(
                    drape_host,
                    tex_coords,
                    offset_angle_deg,
                )
                self.Active = True
                # Expose the shader_state group for geometry injection
                self._shader_grp = self.grid_shader.grp
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
        # Clear the shader group reference so geometry injection stops
        if hasattr(self, "_shader_grp"):
            del self._shader_grp
        try:
            import FreeCADGui
            FreeCADGui.Selection.removeObserver(self)
        except Exception:
            pass

    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        return None
