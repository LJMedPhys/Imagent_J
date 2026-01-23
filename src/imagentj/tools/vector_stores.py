from .utils import init_vec_store

# Initialize vector stores
vec_store_docs = init_vec_store(
    collection_name="BioimageAnalysisDocs",
    path="./qdrant_data",
)

vec_store_mistakes = init_vec_store(
    path="./qdrant_data",
    collection_name="codingerrors_and_solutions",
)