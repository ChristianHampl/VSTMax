# Wird vom Installer vor dem Start der App ausgeführt.
# Qt sucht sein Plattform-Plug-in sonst am falschen Ort und beendet sich ohne Fenster,
# weil der Start über pythonw.exe keine Konsole hat.
import os
from pathlib import Path


def configure_qt(install_dir) -> str | None:
    """Setzt die Qt-Plug-in-Pfade, wenn das Paket sie enthält. Sonst bleibt der Qt-Standardpfad."""
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
