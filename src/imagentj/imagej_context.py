import imagej
from typing import Optional
from config.imagej_config import FIJI_JAVA_HOME
import scyjava

_ij_instance: Optional["imagej.ImageJ"] = None


scyjava.config.add_options('-Xmx6g')
# Force Metal L&F so all Swing component UI delegates (including JFormattedTextField
# used by JSpinner) are registered before any plugin creates GUI components.
# Without this, plugins that build Swing widgets on non-EDT threads (e.g.
# CircleSkinner) fail with "no ComponentUI class for JFormattedTextField".
scyjava.config.add_options('-Dswing.defaultlaf=javax.swing.plaf.metal.MetalLookAndFeel')
# Local Fiji installation is complete — no network calls needed at JVM startup.
# Without this, scyjava tries to download Maven from archive.apache.org if mvn
# is not on PATH, which fails in restricted/flaky network environments.
scyjava.config.set_java_constraints(fetch='never')

def get_ij():
    global _ij_instance
    if _ij_instance is None:
        _ij_instance = imagej.init(FIJI_JAVA_HOME, mode='interactive')
    return _ij_instance
