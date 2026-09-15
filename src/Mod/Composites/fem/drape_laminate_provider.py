# SPDX-License-Identifier: LGPL-2.1-or-later


def _is_isotropic_shell(compshell_obj):
    # Lazy import: this module loads during Composites package init, where
    # the feature modules are not importable yet.
    from ..features.CompositeShell import is_isotropic_shell

    return is_isotropic_shell(compshell_obj)


def _is_isotropic_laminate(laminate):
    from ..features.Laminate import is_isotropic_laminate

    return is_isotropic_laminate(laminate)


def _format_material_name(name, prefix):
    from ..util.fem_util import format_material_name

    return format_material_name(name, prefix=prefix)


def get_compshell_obj(shellth_obj):
    if len(shellth_obj.References) >= 1:
        refobj = shellth_obj.References[0][0]
        if not hasattr(refobj, "Proxy"):
            return None
        if not refobj.Proxy:
            return None
        if refobj.Proxy.Type == "Composite::Shell":
            return refobj
    return None


def get_drape_lcs(compshell_obj, femmesh_obj, elements):
    def element_info(e):
        element_nodes = femmesh_obj.getElementNodes(e)
        if len(element_nodes) in [3, 6]:
            face_def = {1: [0, 1, 2]}
        else:  # quad element
            face_def = {1: [0, 1, 2, 3]}

        for key in face_def:
            tris = []
            for node_idx in face_def[key]:
                n = femmesh_obj.getNodeById(element_nodes[node_idx])
                tris.append(n)
            return compshell_obj.Proxy.get_drape_lcs(tris)

    return {e: element_info(e) for e in elements}


def get_laminate(shellth_obj):
    compshell_obj = get_compshell_obj(shellth_obj)
    if not compshell_obj:
        return None
    return compshell_obj.Laminate


def get_laminate_materials(geos):
    def get_lam(o):
        obj = o["Object"]
        return get_laminate(obj)

    return [get_lam(o) for o in geos if get_lam(o)]


def shell_orientation_provider(shellth_obj, femmesh_obj, elements, orientation):
    if femmesh_obj is None:
        return {}
    compshell_obj = get_compshell_obj(shellth_obj)
    if not compshell_obj:
        return {}
    if _is_isotropic_shell(compshell_obj):
        # D5: a QI shell has no drape frame — zero per-element work (no
        # mesh walk). The explicit None also clobbers any LCS orientation
        # the FEM material carries, so the writer takes the
        # plain-material path (no *ORIENTATION block).
        return {"orientation": None}
    return {
        "orientation": get_drape_lcs(compshell_obj, femmesh_obj, elements),
        "element_ids": elements,
    }


def shell_section_provider(shellth_obj, matgeoset, orientation_name):
    laminate = get_laminate(shellth_obj)
    if not laminate:
        return None
    if _is_isotropic_laminate(laminate):
        # D5: single-layer plain section; the referenced material is the
        # laminate's equivalent isotropic layer (written by the indirect
        # material provider), never a COMPOSITE orientation.
        layers = getattr(laminate.Proxy, "FEMLayers", None) or []
        if len(layers) != 1:
            raise ValueError(
                f"{laminate.Name}: declared isotropic but has "
                f"{len(layers)} merged layers"
            )
        layer = layers[0]
        material_name = _format_material_name(
            layer.description,
            prefix=laminate.Name,
        )
        return {
            # The override replaces the whole header MATERIAL chunk.
            "material": f"MATERIAL={material_name}",
            "section_geo": f"{layer.thickness:.13G}\n",
        }
    return {
        "material": f"COMPOSITE,ORIENTATION={orientation_name}",
        "section_geo": laminate.Proxy.write_shell_section(laminate),
    }


def indirect_material_provider(geos_shellthickness):
    return get_laminate_materials(geos_shellthickness)


def register_drape_laminate_providers():
    try:
        from femtools.fem_extension_registry import (
            register_indirect_material_provider,
            register_shell_orientation_provider,
            register_shell_section_provider,
        )
    except Exception:
        return False

    register_shell_orientation_provider("compositeswb.drape", shell_orientation_provider)
    register_shell_section_provider("compositeswb.laminate", shell_section_provider)
    register_indirect_material_provider("compositeswb.laminate", indirect_material_provider)
    return True
