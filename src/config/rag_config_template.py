# RAG (Retrieval-Augmented Generation) Configuration Template
# Copy this file to rag_config.py and customize the settings

# Vector Database Settings
QDRANT_DATA_PATH = "./qdrant_data"

# Collection Names
DOCS_COLLECTION_NAME = "BioimageAnalysisDocs"
MISTAKES_COLLECTION_NAME = "codingerrors_and_solutions"

# Document Ingestion Settings
# Folders to scan for documents to add to the RAG system
# The system will recursively scan these folders for PDFs, notebooks, code files, etc.
INGESTION_FOLDERS = [
    # Add your document folders here
    # Example: r"C:\path\to\your\knowledge\database"
    # Example: r"C:\Users\username\Documents\BioimageAnalysisPapers"
    # Example: r"C:\path\to\research\notes"
]

# Embedding Model Settings
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSION = 3072  # Dimension for text-embedding-3-large

# Chunking Settings
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# Batch Processing
BATCH_SIZE = 50  # Number of chunks to process at once

# File Processing Settings
# Files/folders to skip during ingestion
SKIP_PATTERNS = [
    ".ipynb_checkpoints",
    "__pycache__",
    ".git",
    "node_modules",
    ".DS_Store"
]

# Supported file types for ingestion
SUPPORTED_EXTENSIONS = {
    'documents': ['.pdf', '.md', '.txt'],
    'code': ['.py', '.js', '.java', '.groovy'],
    'notebooks': ['.ipynb']
}