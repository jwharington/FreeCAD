def InitGui(self):
    from PySide.QtCore import QT_TRANSLATE_NOOP

    from . import CommandLinkBody

    cmdList = [
        "FemLink_LinkBody",
    ]

    self.appendToolbar(QT_TRANSLATE_NOOP("Workbench", "FemLink"), cmdList)

    self.appendMenu(
        [QT_TRANSLATE_NOOP("Workbench", "&FemLink")],
        cmdList,
    )
