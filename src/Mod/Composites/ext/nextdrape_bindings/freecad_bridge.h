// freecad_bridge.h — PyCXX bridge to FreeCAD Part module.
//
// Extracts TopoDS_Shape* from a Part.Shape PyObject* by walking
// PyCXX's internal layout: PyObject → PythonClassInstance →
// m_pycxx_object (TopoShapePy*) → getTopoShapePtr() → TopoShape*
// → getShape() → TopoDS_Shape*.
//
// Minimal declarations — no need to include FreeCAD's generated headers.

#pragma once

#include <Python.h>
#include <cstring>

// ── PyCXX internal layout (from ExtensionType.hxx) ──────────────
struct PyCXX_PythonClassInstance {
    PyObject_HEAD
    void* m_pycxx_object;  // actually TopoShapePy*
};

// ── Minimal FreeCAD type declarations ──────────────────────────
// These match the actual FreeCAD layout (verified against generated headers).

namespace Data {
    class ComplexGeoData {};  // base class placeholder
}

namespace Part {

// TopoShape — the C++ shape container
class TopoShape : public Data::ComplexGeoData {
public:
    virtual ~TopoShape() = default;
    virtual const class TopoDS_Shape& getShape() const;
};

// TopoShapePy — PyCXX-wrapped Python type for Part.Shape objects.
// Layout matches FreeCAD's generated TopoShapePy.h.
class TopoShapePy {
public:
    virtual ~TopoShapePy();
    virtual TopoShape* getTopoShapePtr() const;
    virtual TopoShape* getTwinPtr() const;
    static PyTypeObject Type;
};

} // namespace Part

// ── Bridge function ────────────────────────────────────────────
inline TopoDS_Shape* extract_topods_shape(PyObject* obj) {
    // Step 1: Unwrap Part::Feature → .Shape
    PyObject* shape_obj = obj;
    PyObject* shape_attr = PyObject_GetAttrString(obj, "Shape");
    if (shape_attr && shape_attr != obj) {
        shape_obj = shape_attr;
    } else if (shape_attr) {
        Py_DECREF(shape_attr);
    }

    // Step 2: Verify type name — Part.Shape derivatives have names like
    // "Part.Solid", "Part.Face", "Part.Wire", "Part.Compound", etc.
    PyTypeObject* typ = Py_TYPE(shape_obj);
    if (!typ || !typ->tp_name) return nullptr;
    const char* tn = typ->tp_name;
    if (!tn || std::strncmp(tn, "Part.", 5) != 0) return nullptr;

    // Step 3: Walk PyCXX layout → TopoShapePy*
    PyCXX_PythonClassInstance* pci =
        reinterpret_cast<PyCXX_PythonClassInstance*>(shape_obj);
    if (!pci || !pci->m_pycxx_object) return nullptr;

    Part::TopoShapePy* topo_py =
        reinterpret_cast<Part::TopoShapePy*>(pci->m_pycxx_object);

    // Step 4: Get TopoShape* → TopoDS_Shape*
    Part::TopoShape* topo = topo_py->getTopoShapePtr();
    if (!topo) return nullptr;

    return const_cast<TopoDS_Shape*>(&topo->getShape());
}
