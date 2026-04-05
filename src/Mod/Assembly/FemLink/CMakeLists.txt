# SPDX-License-Identifier: LGPL-2.1-or-later

SET(FemLink_SRCS
    __init__.py
    CommandLinkBody.py
    LinkBody.py
    ViewLinkBody.py
    FPBase.py
    UtilsFemLink.py
    UtilsAnalysis.py
    TaskAssemblyLinkBody.py
)

INSTALL(
    FILES
        ${FemLink_SRCS}
    DESTINATION
        Mod/Assembly/FemLink
)

SET(all_files
    ${FemLink_SRCS}
)

ADD_CUSTOM_TARGET(FemLink ALL
    SOURCES ${all_files}
)

fc_copy_sources(FemLink "${CMAKE_BINARY_DIR}/Mod/Assembly/FemLink" ${all_files})
