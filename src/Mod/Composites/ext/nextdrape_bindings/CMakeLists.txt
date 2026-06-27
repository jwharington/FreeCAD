# SPDX-License-Identifier: LGPL-2.1-or-later
# CMake build for nextdrape pybind11 extension module.
#
# Builds nextdrape_core as a static library and links it into a
# Python extension module (drape_nextdrape) via pybind11.
#
# Usage outside FreeCAD pixi environment:
#   mkdir build && cd build
#   cmake -DPython3_ROOT_DIR=/path/to/freecad \
#         -DOCC_ROOT=/path/to/occt \
#         -DCMAKE_INSTALL_PREFIX=<install-prefix> \
#         ..
#   make && make install

cmake_minimum_required(VERSION 3.18)
project(composites_nextdrape LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)

# Derive OCC_ROOT from CMAKE_PREFIX_PATH if not explicitly provided
if(NOT OCC_ROOT AND CMAKE_PREFIX_PATH)
    foreach(_p ${CMAKE_PREFIX_PATH})
        if(EXISTS "${_p}/lib/cmake/opencascade/OpenCASCADEConfig.cmake")
            set(OCC_ROOT "${_p}" CACHE PATH "OpenCASCADE root directory")
            break()
        elseif(EXISTS "${_p}/lib/cmake/OCCT/OCCTConfig.cmake")
            set(OCC_ROOT "${_p}" CACHE PATH "OCCT root directory")
            break()
        endif()
    endforeach()
endif()
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ── Locate dependencies ────────────────────────────────────────────

# Python / pybind11
find_package(pybind11 CONFIG REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Development)

# OpenCASCADE – try cmake config first, fall back to manual paths
set(OCC_FOUND FALSE)
if(EXISTS "${OCC_ROOT}/lib/cmake/opencascade/OpenCASCADEConfig.cmake")
    list(APPEND CMAKE_MODULE_PATH "${OCC_ROOT}/lib/cmake/opencascade")
    find_package(OpenCASCADE CONFIG REQUIRED COMPONENTS
        FoundationClasses
        ModelingData
        ModelingAlgorithms
    )
    if(TARGET OpenCASCADE::FoundationClasses)
        set(OCC_FOUND TRUE)
    endif()
elseif(EXISTS "${OCC_ROOT}/lib/cmake/OCCT/OCCTConfig.cmake")
    list(APPEND CMAKE_MODULE_PATH "${OCC_ROOT}/lib/cmake/OCCT")
    find_package(OCCT CONFIG REQUIRED)
    if(TARGET OCCT::OCCT)
        set(OCC_FOUND TRUE)
    endif()
endif()

if(NOT OCC_FOUND)
    # Manual detection – common FreeCAD pixi / conda layout
    if(NOT OCC_INCLUDE_DIR)
        set(OCC_INCLUDE_DIR "${OCC_ROOT}/include/opencascade")
    endif()
    if(NOT OCC_LIBRARY_DIR)
        set(OCC_LIBRARY_DIR "${OCC_ROOT}/lib")
    endif()

    file(GLOB OCC_LIBS "${OCC_LIBRARY_DIR}/libTK*.so" "${OCC_LIBRARY_DIR}/libTK*.so.*")
    list(REMOVE_DUPLICATES OCC_LIBS)

    if(NOT OCC_LIBS)
        message(FATAL_ERROR "Cannot find libTK*.so in ${OCC_LIBRARY_DIR}")
    endif()

    message(STATUS "OpenCASCADE headers: ${OCC_INCLUDE_DIR}")
    message(STATUS "OpenCASCADE libs: ${OCC_LIBS}")
endif()

# Eigen3
if(NOT EIGEN3_ROOT)
    set(EIGEN3_ROOT "${EIGEN_ROOT}" CACHE PATH "Eigen3 root directory")
endif()
if(EXISTS "${EIGEN3_ROOT}/include/eigen3")
    set(EIGEN3_INCLUDE_DIR "${EIGEN3_ROOT}/include/eigen3")
else()
    find_package(Eigen3 QUIET)
    if(NOT Eigen3_FOUND)
        set(EIGEN3_INCLUDE_DIR "${EIGEN3_ROOT}/include" CACHE PATH "")
    endif()
endif()

# ── nextdrape_core static library ──────────────────────────────────

set(NEXTDRAPE_SRC
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/DrapeEngine.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/SurfaceNavigator.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/ChebyshevNetSolver.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/ChebyshevNetGrowthPlanner.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/LatticeBuilder.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/LatticeNodePlacer.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/QuadBuilder.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/LatticeFrontier.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/SurfaceProjection.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/GeodesicIntegrator.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/GeodesicMetric.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/GeodesicStepper.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/LatticeMetrics.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/TexturePlanBuilder.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/ResultExporter.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/src/HtmlReportBuilder.cpp
)

add_library(nextdrape_core STATIC ${NEXTDRAPE_SRC})
set_property(TARGET nextdrape_core PROPERTY POSITION_INDEPENDENT_CODE ON)

target_include_directories(nextdrape_core PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/include
    ${EIGEN3_INCLUDE_DIR}
    ${OCC_INCLUDE_DIR}
)

if(OCC_FOUND AND TARGET OpenCASCADE::OpenCASCADE)
    target_link_libraries(nextdrape_core PUBLIC
        OpenCASCADE::FoundationClasses
        OpenCASCADE::ModelingData
        OpenCASCADE::ModelingAlgorithms
    )
elseif(OCC_FOUND AND TARGET OCCT::OCCT)
    target_link_libraries(nextdrape_core PUBLIC OCCT::OCCT)
else()
    target_link_libraries(nextdrape_core PUBLIC ${OCC_LIBS})
endif()

target_compile_definitions(nextdrape_core PRIVATE
    EIGEN_USE_STL_ALLOCATOR
)
set_target_properties(nextdrape_core PROPERTIES LINK_FLAGS "-Wl,--allow-shlib-undefined")

# Essential TK libraries for nextdrape (resolved at runtime via RPATH)
set(NEXTDRAPE_TK_LIBS
    TKernel
    TKMath
    TKG2d
    TKG3d
    TKGeomBase
    TKBRep
    TKGeomAlgo
    TKTopAlgo
    TKPrim
    TKBO
    TKShHealing
    TKBool
    TKFillet
    TKOffset
    TKFeat
    TKMesh
    TKXMesh
)

# ── Python extension module ────────────────────────────────────────

pybind11_add_module(drape_nextdrape binding.cpp)

target_include_directories(drape_nextdrape PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../../src/3rdParty/nextdrape/include
    ${EIGEN3_INCLUDE_DIR}
    ${OCC_INCLUDE_DIR}
)

target_link_libraries(drape_nextdrape PRIVATE nextdrape_core)
# Link TK libs so symbols resolve at load time
foreach(_tklib IN LISTS NEXTDRAPE_TK_LIBS)
    target_link_libraries(drape_nextdrape PRIVATE "${OCC_ROOT}/lib/lib${_tklib}.so")
endforeach()
# Do NOT link TK libraries directly — they conflict with FreeCAD's OCC.
# Rely on --allow-shlib-undefined so FreeCAD's OCC provides symbols at runtime.
target_link_options(drape_nextdrape PRIVATE "-Wl,--allow-shlib-undefined")

# ── Install ────────────────────────────────────────────────────────

install(TARGETS drape_nextdrape
    LIBRARY DESTINATION ../ext
)
