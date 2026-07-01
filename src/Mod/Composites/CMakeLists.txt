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
        LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/Mod/Composites/ext/_native
    )

    add_custom_command(TARGET Composites_drape POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory
            ${CMAKE_BINARY_DIR}/Mod/Composites/ext/_native
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:Composites_drape>
            ${CMAKE_BINARY_DIR}/Mod/Composites/ext/_native/$<TARGET_FILE_NAME:Composites_drape>
        VERBATIM
    )

    install(TARGETS Composites_drape
        LIBRARY DESTINATION Mod/Composites/ext/_native
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
    "*.FCMat"
)

# ── Copy to build tree for development ──────────────────────────
fc_copy_sources(Composites "${CMAKE_BINARY_DIR}/Mod/Composites" ${Composites_PY_SRCS_ALL})

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
    PATTERN "__pycache__" EXCLUDE
    PATTERN "*.pyc" EXCLUDE
    PATTERN ".git" EXCLUDE
)

message(STATUS "Composites module configured")
