# SPDX-License-Identifier: LGPL-2.1-or-later


def get_drape_lcs(compshell_obj, femmesh_obj, elements):

    def element_info(e):
        element_nodes = femmesh_obj.getElementNodes(e)
        if len(element_nodes) in [3, 6]:
            faceDef = {1: [0, 1, 2]}
        else:  # quad element
            faceDef = {1: [0, 1, 2, 3]}

        for key in faceDef:
            tris = []
            for nodeIdx in faceDef[key]:
                n = femmesh_obj.getNodeById(element_nodes[nodeIdx])
                tris.append(n)
            return compshell_obj.Proxy.get_drape_lcs(tris)

    return {e: element_info(e) for e in elements}


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
