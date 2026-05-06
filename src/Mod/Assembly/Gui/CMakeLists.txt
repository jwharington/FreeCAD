# SPDX-License-Identifier: LGPL-2.1-or-later


set(AssemblyGui_LIBS
    Assembly
    PartDesign
    PartGui
    Spreadsheet
    SpreadsheetGui
    FreeCADGui
)

# Track .ui panel files explicitly so Assembly_rc.py is regenerated when any panel changes.
# PYSIDE_WRAP_RC only tracks the .qrc manifest (not the files it references), so we inline
# the equivalent custom command here with an explicit DEPENDS on the panel .ui files.
file(GLOB Assembly_Panel_UIs "${CMAKE_CURRENT_SOURCE_DIR}/Resources/panels/*.ui")
set(_assembly_rc_py "${CMAKE_CURRENT_BINARY_DIR}/Assembly_rc.py")
set(_assembly_qrc  "${CMAKE_CURRENT_SOURCE_DIR}/Resources/Assembly.qrc")
add_custom_command(OUTPUT "${_assembly_rc_py}"
    COMMAND "${PYSIDE_RCC_EXECUTABLE}" ${RCCOPTIONS} "${_assembly_qrc}" ${PY_ATTRIBUTE} -o "${_assembly_rc_py}"
    MAIN_DEPENDENCY "${_assembly_qrc}"
    DEPENDS ${Assembly_Panel_UIs}
    COMMENT "Generating Assembly_rc.py"
)
list(APPEND Assembly_QRC_SRCS "${_assembly_rc_py}")

set (Assembly_TR_QRC ${CMAKE_CURRENT_BINARY_DIR}/Resources/Assembly_translation.qrc)
qt_find_and_add_translation(QM_SRCS "Resources/translations/*_*.ts"
    ${CMAKE_CURRENT_BINARY_DIR}/Resources/translations)
qt_create_resource_file(${Assembly_TR_QRC} ${QM_SRCS})
qt_add_resources(AssemblyResource_SRCS Resources/Assembly.qrc ${Assembly_TR_QRC})

SOURCE_GROUP("Resources" FILES ${AssemblyResource_SRCS})

generate_from_py(ViewProviderAssembly)

set(AssemblyGui_UIC_SRCS
    TaskAssemblyCreateBom.ui
    TaskAssemblyCreateJoint.ui
    TaskAssemblyCreateForce.ui
    TaskAssemblyCreateSimulation.ui
    TaskAssemblyCreateView.ui
    TaskAssemblyInsertLink.ui
    TaskAssemblyLinkBody.ui
    Assembly.ui
)

SET(Python_SRCS
    ViewProviderAssembly.pyi
    ViewProviderAssemblyPyImp.cpp
)
SOURCE_GROUP("Python" FILES ${Python_SRCS})

SET(AssemblyGui_SRCS_Module
    AppAssemblyGui.cpp
    AppAssemblyGuiPy.cpp
    PreCompiled.h
    Commands.cpp
    Commands.h
    TaskAssemblyMessages.cpp
    TaskAssemblyMessages.h
    ViewProviderAssembly.cpp
    ViewProviderAssembly.h
    ViewProviderAssemblyLink.cpp
    ViewProviderAssemblyLink.h
    ViewProviderBom.cpp
    ViewProviderBom.h
    ViewProviderBomGroup.cpp
    ViewProviderBomGroup.h
    ViewProviderJointGroup.cpp
    ViewProviderJointGroup.h
    ViewProviderForceGroup.cpp
    ViewProviderForceGroup.h
    ViewProviderViewGroup.cpp
    ViewProviderViewGroup.h
    ViewProviderSimulationGroup.cpp
    ViewProviderSimulationGroup.h
    ${Assembly_QRC_SRCS}
)

SOURCE_GROUP("Module" FILES ${AssemblyGui_SRCS_Module})


SET(AssemblyGui_SRCS
    ${AssemblyResource_SRCS}
    ${AssemblyGui_UIC_HDRS}
    ${AssemblyGui_SRCS_Module}
    ${Python_SRCS}
)

SET(AssemblyGuiIcon_SVG
    Resources/icons/AssemblyWorkbench.svg
)

add_library(AssemblyGui SHARED ${AssemblyGui_SRCS} ${AssemblyGuiIcon_SVG})

if(FREECAD_USE_PCH)
    target_precompile_headers(AssemblyGui PRIVATE
            $<$<COMPILE_LANGUAGE:CXX>:"${CMAKE_CURRENT_LIST_DIR}/PreCompiled.h">
    )
endif(FREECAD_USE_PCH)

target_include_directories(
    AssemblyGui
    PRIVATE
    ${CMAKE_BINARY_DIR}
    ${CMAKE_CURRENT_BINARY_DIR}
)

if(WIN32)
    target_compile_definitions(AssemblyGui PRIVATE _USE_MATH_DEFINES)
endif(WIN32)

target_link_libraries(AssemblyGui ${AssemblyGui_LIBS})
if (FREECAD_WARN_ERROR)
    target_compile_warn_error(AssemblyGui)
endif()

SET_BIN_DIR(AssemblyGui AssemblyGui /Mod/Assembly)
SET_PYTHON_PREFIX_SUFFIX(AssemblyGui)

fc_copy_sources(AssemblyGui "${CMAKE_BINARY_DIR}/${CMAKE_INSTALL_DATADIR}/Mod/Assembly" ${AssemblyGuiIcon_SVG})
fc_target_copy_resource(AssemblyGui
        ${CMAKE_CURRENT_BINARY_DIR}
        ${CMAKE_BINARY_DIR}/Mod/Assembly
        Assembly_rc.py)

INSTALL(TARGETS AssemblyGui DESTINATION ${CMAKE_INSTALL_LIBDIR})
INSTALL(FILES ${AssemblyGuiIcon_SVG} DESTINATION "${CMAKE_INSTALL_DATADIR}/Mod/Assembly/Resources/icons")
INSTALL(FILES ${Assembly_QRC_SRCS} DESTINATION Mod/Assembly
)
