from config.rag_config import (
    QDRANT_DATA_PATH, DOCS_COLLECTION_NAME, PLUGINS_COLLECTION_NAME,
)

# Lazy single-collection RAG: only the static documentation store. The agent's
# learning memory (pitfalls + recipes) is file-based in learned_memory.py.
vec_store_docs = None
_rag_initialized = False
_sparse_rag_available = False


def _try_init_vector_stores():
    """Attempt to initialize the docs vector store. Returns silently if RAG deps are unavailable."""
    global vec_store_docs, _rag_initialized, _sparse_rag_available
    if _rag_initialized:
        return
    _rag_initialized = True
    try:
        from ..qdrant_client_singleton import get_qdrant_client
        client = get_qdrant_client(path=QDRANT_DATA_PATH)
        # Local Kimi runs have no text-embedding-3-large endpoint.  The
        # shipped collection still has a complete sparse BM25 index, and the
        # search path knows how to use it without constructing a hybrid store.
        import os
        local_provider = bool(os.getenv("LOCAL_LLM_BASE_URL"))
        if local_provider:
            if not client.collection_exists(collection_name=DOCS_COLLECTION_NAME):
                raise RuntimeError(f"Qdrant collection {DOCS_COLLECTION_NAME!r} is missing")
            # Keep the writable vector-store object unset: smart_file_reader
            # must not try to ingest new documents without a compatible dense
            # embedding model. Static documentation retrieval still works.
            vec_store_docs = None
            _sparse_rag_available = True
        else:
            from ..rag.RAG import init_vector_store
            vec_store_docs = init_vector_store(
                collection_name=DOCS_COLLECTION_NAME, client=client
            )
        print("RAG system initialized successfully.")
    except Exception as e:
        print(f"RAG system unavailable (running without RAG): {e}")
        # The Qdrant stores are tracked with Git-LFS in this repository. When
        # they appear on disk as tiny Git-LFS pointer stubs instead of real
        # SQLite files, surface an actionable hint (this is what actually kills
        # RAG on a fresh checkout, not an actual dependency problem).
        store_hint = ""
        try:
            import pathlib
            root = pathlib.Path(QDRANT_DATA_PATH).parent
            for stub in root.rglob("storage.sqlite"):
                try:
                    if stub.stat().st_size < 4096 and stub.read_text(errors="ignore").startswith("version https://git-lfs"):
                        store_hint = (
                            f" Note: {stub} is an unfetched Git-LFS pointer stub "
                            "(contains an 'oid sha256:' line, not a database). "
                            "Enable git-lfs (`git lfs pull`) or restore the Qdrant "
                            "snapshot to re-enable documentation RAG."
                        )
                        break
                except Exception:
                    pass
        except Exception:
            pass
        if store_hint:
            print(store_hint)
        vec_store_docs = None


def get_vec_store_docs():
    """Get the docs vector store, initializing on first access."""
    _try_init_vector_stores()
    return vec_store_docs


def is_rag_available():
    """Check if the documentation RAG is available."""
    _try_init_vector_stores()
    return vec_store_docs is not None or _sparse_rag_available


def is_plugin_db_available():
    """Check if the fiji_plugins collection exists in Qdrant."""
    try:
        from ..qdrant_client_singleton import get_qdrant_client
        client = get_qdrant_client(path=QDRANT_DATA_PATH)
        return client.collection_exists(collection_name=PLUGINS_COLLECTION_NAME)
    except Exception:
        return False


def reset_vector_stores_for_test(docs=None):
    """Reset the lazy-init globals; tests use this to inject an in-memory store."""
    global vec_store_docs, _rag_initialized, _sparse_rag_available
    vec_store_docs = docs
    _rag_initialized = True
    _sparse_rag_available = False
