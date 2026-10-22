# Laeuft vor dem App-Start. Nur ASCII: pynsist schreibt das Startskript auf Windows
# in der System-Codepage (ue oft als Byte FC). Python 3 liest .py als UTF-8 und
# bricht dann mit SyntaxError ab, bevor ein Fenster oder ein Log entsteht.
import os
from pathlib import Path


def configure_qt(install_dir) -> str | None:
    """Qt-Plugin-Pfad setzen, wenn der Ordner existiert. Sonst Qt-Standardpfad."""
    pkg = Path(install_dir) / "pkgs" / "PySide6"
    # Windows-Rad 6.12: PySide6/plugins. Linux-Rad: PySide6/Qt/plugins.
    for plugins in (pkg / "plugins", pkg / "Qt" / "plugins"):
        platforms = plugins / "platforms"
        if platforms.is_dir() and any(platforms.iterdir()):
            os.environ["QT_PLUGIN_PATH"] = str(plugins)
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platforms)
            if os.name == "nt":
                os.environ["PATH"] = str(pkg) + os.pathsep + os.environ.get("PATH", "")
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(str(pkg))
            return str(plugins)
    return None


_found = configure_qt(Path(__file__).resolve().parent)
print("Qt-Plugins:", _found or "Ordner nicht gefunden, Qt sucht selbst")
