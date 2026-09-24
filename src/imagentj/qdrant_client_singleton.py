# qdrant_client_singleton.py
import threading

from qdrant_client import QdrantClient

_qdrant_client = None

# The embedded client (QdrantClient(path=...)) is not thread-safe for writes: it
# shares one sqlite connection across threads, and two concurrent upserts raise
# "sqlite3.InterfaceError: bad parameter or other API misuse". The tool node runs
# parallel tool calls on separate threads, so two smart_file_reader calls on large
# files did exactly that. Hold this around every runtime write.
write_lock = threading.Lock()

def get_qdrant_client(path: str):
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(path=path)
    return _qdrant_client
