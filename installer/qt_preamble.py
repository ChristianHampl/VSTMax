# Wird vom Installer vor dem Start der App ausgeführt (Qt findet sonst seine Plattform-Plug-ins nicht).
import os
from pathlib import Path

_root = Path(__file__).resolve().parent
_plugins = _root / "pkgs" / "PySide6" / "plugins"
os.environ.setdefault("QT_PLUGIN_PATH", str(_plugins))
os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(_plugins / "platforms"))
