# SPDX-License-Identifier: LGPL-2.1-or-later
# Composites module — draping simulation for composite layup

# ── nextdrape submodule (out-of-tree, needs explicit bin dir) ───
if(EXISTS "${CMAKE_SOURCE_DIR}/src/3rdParty/nextdrape/CMakeLists.txt")
    add_subdirectory(
        ${CMAKE_SOURCE_DIR}/src/3rdParty/nextdrape
        ${CMAKE_BINARY_DIR}/src/3rdParty/nextdrape
    )
    add_definitions(-DHAVE_NEXTDRAPE)
    message(STATUS "Composites: nextdrape submodule found")
else()
    message(WARNING "Composites: nextdrape submodule not found at src/3rdParty/nextdrape/")
endif()

# ── Library targets ─────────────────────────────────────────────
set(Composites_LIBS
    Part
    FreeCADApp
    FreeCADBase
)

if(TARGET nextdrape_core)
    list(APPEND Composites_LIBS nextdrape_core)
    message(STATUS "Composites: nextdrape_core linked")
else()
    message(STATUS "Composites: nextdrape_core not available")
endif()

# ── C++ extension ───────────────────────────────────────────────
# ARCHITECTURE NOTE — DO NOT REVERT TO CUSTOM LOADER
#
# Composites_drape.so is a pybind11 Python extension providing the
# nextdrape draping solver and seam extraction. It follows the standard
# FreeCAD pattern used by Fem, Part, and Materials:
#
#   1. SET_BIN_DIR places the .so in ${CMAKE_BINARY_DIR}/lib/ during
#      build, which is on sys.path for FreeCADCmd.
#   2. INSTALL places it in ${CMAKE_INSTALL_LIBDIR} (lib/) in the install
#      prefix, also on sys.path for the GUI FreeCAD.
#   3. Python imports it via standard `import Composites_drape` — no
#      custom loader, no spec_from_file_location, no nested subdirectory.
#
# PREVIOUS FAILURE: The old approach nested the .so in
# Mod/Composites/ext/_native/ and used a custom importlib loader
# (spec_from_file_location) in ext/_native/__init__.py. Modules created
# via spec_from_file_location are not properly registered in sys.modules,
# causing interpreter-shutdown crashes (double-free / cleanup-order bugs).
# See commit history for the migration away from that pattern.
#
# If you change the output directory or introduce a custom loader again,
# you will reproduce the shutdown crash. Use SET_BIN_DIR without a third
# argument (defaults to lib/) and INSTALL to ${CMAKE_INSTALL_LIBDIR}.
option(COMPOSITES_BUILD_CPP "Build C++ draping extension" ON)
if(COMPOSITES_BUILD_CPP)
    # Shared include dirs + libs for both pybind11 module targets.
    set(Composites_CPP_INC
        PRIVATE
            ${CMAKE_BINARY_DIR}/src
            ${CMAKE_SOURCE_DIR}/src
            ${CMAKE_CURRENT_SOURCE_DIR}
            ${CMAKE_CURRENT_BINARY_DIR}
            ${CMAKE_SOURCE_DIR}/src/3rdParty/libkdtree
    )

    # ── Composites_drape: the draping solver + seam extraction binding ──
    add_library(Composites_drape MODULE App/CompositesDrape.cpp)
    target_include_directories(Composites_drape ${Composites_CPP_INC})
    target_link_libraries(Composites_drape ${Composites_LIBS})
    SET_BIN_DIR(Composites_drape Composites_drape)
    SET_PYTHON_PREFIX_SUFFIX(Composites_drape)
    install(TARGETS Composites_drape
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    )

    # ── Composites_parting: the non-planar parting solver binding ──
    # Same pattern as Composites_drape (standard pybind11 MODULE, SET_BIN_DIR
    # -> lib/, INSTALL to ${CMAKE_INSTALL_LIBDIR}). Do NOT introduce a custom
    # loader — see the architecture note above Composites_drape.
    add_library(Composites_parting MODULE App/CompositesParting.cpp)
    # No Qt in this target — disable AUTOMOC/AUTOUIC so it doesn't collide with
    # Composites_drape's autogen output paths (both would otherwise generate
    # the same ui_*.h under the shared Composites autogen dir).
    set_target_properties(Composites_parting PROPERTIES AUTOMOC OFF AUTOUIC OFF AUTORCC OFF)
    target_include_directories(Composites_parting ${Composites_CPP_INC})
    target_link_libraries(Composites_parting ${Composites_LIBS})
    SET_BIN_DIR(Composites_parting Composites_parting)
    SET_PYTHON_PREFIX_SUFFIX(Composites_parting)
    install(TARGETS Composites_parting
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    )

    message(STATUS "Composites: C++ extensions configured (drape, parting)")
endif()

# ── Python sources (collect recursively) ────────────────────────
# RELATIVE so fc_copy_sources builds dest paths as <build>/Mod/Composites/<rel>
# instead of nesting the absolute source path under the dest.
file(GLOB_RECURSE Composites_PY_SRCS_ALL RELATIVE ${CMAKE_CURRENT_SOURCE_DIR}
    "*.py"
    "*.svg"
    "*.ui"
    "*.xml"
    "*.qrc"
    "*.css"
    "*.FCMat"
)

# ── Copy to build tree for development ──────────────────────────
# FreeCAD loads Python from the build tree during development, so the
# sources must be copied there whenever they change. fc_copy_sources ties
# the copy commands to a target via add_file_dependencies; without an
# actual target the commands are orphaned and never run, leaving the
# build tree stale. Mirror the Fem convention (FemScriptsTarget) so
# `cmake --build <build> --target CompositesScripts` syncs the tree.
add_custom_target(CompositesScripts ALL
    SOURCES ${Composites_PY_SRCS_ALL}
)
fc_copy_sources(CompositesScripts "${CMAKE_BINARY_DIR}/Mod/Composites" ${Composites_PY_SRCS_ALL})

# ── Install like other workbenches ──────────────────────────────
# Preserve the package layout so FreeCAD can import Composites from the
# installed prefix exactly like Part, CAM, and other workbenches.
install(
    DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/
    DESTINATION Mod/Composites
    FILES_MATCHING
        PATTERN "*.py"
        PATTERN "*.svg"
        PATTERN "*.ui"
        PATTERN "*.xml"
        PATTERN "*.qrc"
        PATTERN "*.css"
        PATTERN "*.FCMat"
        PATTERN "*.glsl"
        PATTERN "*.FCStd"
    PATTERN "__pycache__" EXCLUDE
    PATTERN "*.pyc" EXCLUDE
    PATTERN ".git" EXCLUDE
)

message(STATUS "Composites module configured")
