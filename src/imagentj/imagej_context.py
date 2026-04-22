import imagej
from pathlib import Path
from typing import Optional
from config.imagej_config import FIJI_JAVA_HOME
import scyjava

_ij_instance: Optional["imagej.ImageJ"] = None


scyjava.config.add_options('-Xmx6g') 

def _has_bundled_imglyb_support(fiji_dir: Path) -> bool:
    jars_dir = fiji_dir / "jars"
    if not jars_dir.is_dir():
        return False

    jar_names = [jar.name for jar in jars_dir.glob("*.jar")]
    required = ("imglib2-imglyb", "imglib2-unsafe")
    return all(any(name in jar_name for jar_name in jar_names) for name in required)

def get_ij():
    global _ij_instance
    if _ij_instance is None:
        init_target = FIJI_JAVA_HOME
        fiji_dir = Path(FIJI_JAVA_HOME).expanduser()
        if fiji_dir.is_dir():
            init_target = str(fiji_dir)
            # Avoid a runtime Maven fetch when the helper jars are already
            # bundled into the local Fiji installation.
            if _has_bundled_imglyb_support(fiji_dir):
                scyjava.config.endpoints.clear()

        _ij_instance = imagej.init(init_target, mode='interactive')
    return _ij_instance
