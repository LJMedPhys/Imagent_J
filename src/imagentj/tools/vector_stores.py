from .utils import init_vec_store
from config.rag_config import QDRANT_DATA_PATH, DOCS_COLLECTION_NAME, MISTAKES_COLLECTION_NAME

# Initialize vector stores
vec_store_docs = init_vec_store(
    collection_name=DOCS_COLLECTION_NAME,
    path=QDRANT_DATA_PATH,
)

vec_store_mistakes = init_vec_store(
    path=QDRANT_DATA_PATH,
    collection_name=MISTAKES_COLLECTION_NAME,
)