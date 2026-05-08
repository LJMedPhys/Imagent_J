# ImageJ/Fiji Configuration
# Docker sets FIJI_PATH to /opt/Fiji.app via docker-compose.
# For local (non-Docker) runs, set FIJI_PATH in your environment to point at
# your Fiji installation, e.g.:
#   Linux/macOS:  export FIJI_PATH=/path/to/Fiji.app
#   Windows:      set FIJI_PATH=C:\path\to\Fiji.app
import os
FIJI_JAVA_HOME = os.environ.get("FIJI_PATH", "/opt/Fiji.app")
