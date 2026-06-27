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
option(COMPOSITES_BUILD_CPP "Build C++ draping extension" ON)
if(COMPOSITES_BUILD_CPP)
    set(Composites_CPP_SRCS
        App/CompositesDrape.cpp
    )
    
    add_library(Composites_drape MODULE ${Composites_CPP_SRCS})
    
    target_include_directories(Composites_drape
        PRIVATE
            ${CMAKE_BINARY_DIR}/src
            ${CMAKE_SOURCE_DIR}/src
            ${CMAKE_CURRENT_SOURCE_DIR}
            ${CMAKE_CURRENT_BINARY_DIR}
    )
    
    target_link_libraries(Composites_drape ${Composites_LIBS})
    
    SET_PYTHON_PREFIX_SUFFIX(Composites_drape)
    
    set_target_properties(Composites_drape PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/Mod/Composites
    )
    
    message(STATUS "Composites: C++ extension configured")
endif()

# ── Python sources (collect recursively) ────────────────────────
file(GLOB_RECURSE Composites_PY_SRCS_ALL
    "*.py"
    "*.svg"
    "*.ui"
    "*.xml"
    "*.qrc"
    "*.css"
)

# ── Install Python files ────────────────────────────────────────
fc_copy_sources(Composites "${CMAKE_BINARY_DIR}/Mod/Composites" ${Composites_PY_SRCS_ALL})
fc_copy_sources(Composites "${CMAKE_BINARY_DIR}/${CMAKE_INSTALL_DATADIR}/Mod/Composites" ${Composites_PY_SRCS_ALL})

message(STATUS "Composites module configured")
