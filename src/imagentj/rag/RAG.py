"""
RAG (Retrieval-Augmented Generation) System for ImageJ Agent

This module provides functionality to:
1. Initialize Qdrant vector databases for document storage
2. Ingest documents from configured folders
3. Process different file types (PDFs, notebooks, code files, etc.)
4. Create searchable embeddings for AI-powered document retrieval

The RAG system enables the agent to search through documentation,
research papers, code examples, and other knowledge sources to provide
contextually relevant information for ImageJ/Fiji scripting tasks.
"""

# Add src directory to Python path when running script directly
import sys
from pathlib import Path

script_dir = Path(__file__).resolve()
# Check if we're running from the rag directory or from project root
if script_dir.parent.name == 'rag':
    # Running from rag directory, go up to src
    src_dir = script_dir.parent.parent.parent
else:
    # Running from project root with full path
    src_dir = script_dir.parent.parent.parent.parent

if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from qdrant_client import QdrantClient
from qdrant_client.http.models import VectorParams, Distance
from langchain_qdrant import QdrantVectorStore
from langchain_openai import OpenAIEmbeddings
import os
from langchain_community.document_loaders import TextLoader
from imagentj.rag.loaders import get_smart_splitter, get_docling_converter, load_and_split_ipynb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_docling import DoclingLoader
from langchain_docling.loader import ExportType
from config.rag_config import (
    QDRANT_DATA_PATH, DOCS_COLLECTION_NAME, MISTAKES_COLLECTION_NAME,
    INGESTION_FOLDERS, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP,
    BATCH_SIZE, SKIP_PATTERNS, SUPPORTED_EXTENSIONS
)
from config.keys import gpt_key

def init_vector_store(collection_name: str, client: QdrantClient = None, embedding_model: str = EMBEDDING_MODEL):
    """
    Initialize a Qdrant vector store for document storage.

    Args:
        collection_name: Name of the Qdrant collection
        client: QdrantClient instance (optional, will create if None)
        embedding_model: OpenAI embedding model to use

    Returns:
        QdrantVectorStore: Initialized vector store
    """
    if client is None:
        client = QdrantClient(path=QDRANT_DATA_PATH)

    if not client.collection_exists(collection_name=collection_name):
        print(f"Creating new Qdrant collection: {collection_name}")

        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=3072, distance=Distance.COSINE),
        )
    else:
        print(f"Qdrant collection '{collection_name}' already exists. Adding to existing collection.")

    embeddings = OpenAIEmbeddings(model=embedding_model, api_key=gpt_key)

    vector_store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )

    return vector_store
        


def load_folder_recursively(folders: list = None, vector_store=None, collection_name: str = DOCS_COLLECTION_NAME):
    """
    Recursively load and process documents from configured folders.

    Args:
        folders: List of folder paths to scan (uses config if None)
        vector_store: Vector store to add documents to
        collection_name: Name of the collection to use
    """
    if folders is None:
        folders = INGESTION_FOLDERS

    if vector_store is None:
        vector_store = init_vector_store(collection_name)

    if not folders:
        print("No ingestion folders configured. Please add folders to INGESTION_FOLDERS in rag_config.py")
        return

    # 1. Warm up the engine once
    converter = get_docling_converter()

    # 2. Safety splitter for chunks that exceed embedding limits
    safety_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)

    all_chunks = []

    for folder_path in folders:
        print(f"Processing folder: {folder_path}")

        if not os.path.exists(folder_path):
            print(f"Warning: Folder does not exist: {folder_path}")
            continue

        for root, _, files in os.walk(folder_path):
            # Skip unwanted directories
            if any(skip_pattern in root for skip_pattern in SKIP_PATTERNS):
                continue

            for file in files:
                file_path = os.path.join(root, file)
                ext = Path(file).suffix.lower()

                # Check if file type is supported
                supported = any(ext in SUPPORTED_EXTENSIONS[category] for category in SUPPORTED_EXTENSIONS)
                if not supported:
                    continue

                try:
                    print(f"Processing: {file_path}")

                    # --- PDF Logic (Docling) ---
                    if ext == ".pdf":
                        loader = DoclingLoader(file_path=file_path, converter=converter, export_type=ExportType.DOC_CHUNKS)
                        raw_chunks = loader.load()
                        final_splits = safety_splitter.split_documents(raw_chunks)

                    # --- Notebook Logic ---
                    elif ext == ".ipynb":
                        final_splits = load_and_split_ipynb(file_path)

                    # --- Code/Text Logic ---
                    elif ext in SUPPORTED_EXTENSIONS['code'] + SUPPORTED_EXTENSIONS['documents']:
                        loader = TextLoader(file_path, encoding="utf-8")
                        splitter = get_smart_splitter(ext)
                        final_splits = splitter.split_documents(loader.load())

                    else:
                        continue

                    all_chunks.extend(final_splits)

                    # 3. Batch Upload to Vector Store
                    if len(all_chunks) >= BATCH_SIZE:
                        print(f"Uploading batch of {len(all_chunks)} chunks to Qdrant...")
                        vector_store.add_documents(all_chunks)
                        all_chunks = []  # Clear memory

                except Exception as e:
                    print(f"Error processing {file_path}: {e}")

    # Upload remaining chunks
    if all_chunks:
        print(f"Uploading final batch of {len(all_chunks)} chunks to Qdrant...")
        vector_store.add_documents(all_chunks)

    print("Document ingestion completed!")


def initialize_rag_system():
    """
    Initialize the complete RAG system with both document collections.
    This function creates the necessary vector stores and can be called
    to set up the RAG system for the first time.
    """
    print("Initializing RAG system...")

    # Create a single Qdrant client for all collections
    client = QdrantClient(path=QDRANT_DATA_PATH)

    # Initialize document collection
    docs_store = init_vector_store(DOCS_COLLECTION_NAME, client=client)
    print(f"✓ Initialized document collection: {DOCS_COLLECTION_NAME}")

    # Initialize mistakes/coding experience collection
    mistakes_store = init_vector_store(MISTAKES_COLLECTION_NAME, client=client)
    print(f"✓ Initialized coding experience collection: {MISTAKES_COLLECTION_NAME}")

    print("RAG system initialized successfully!")
    print(f"Vector database location: {QDRANT_DATA_PATH}")
    return docs_store, mistakes_store


def ingest_documents():
    """
    Ingest documents from configured folders into the RAG system.
    Call this function after setting up your INGESTION_FOLDERS in rag_config.py.
    """
    print("Starting document ingestion...")

    if not INGESTION_FOLDERS:
        print("❌ No ingestion folders configured!")
        print("Please add folder paths to INGESTION_FOLDERS in src/config/rag_config.py")
        return

    # Initialize the document store
    docs_store = init_vector_store(DOCS_COLLECTION_NAME)

    # Load documents from all configured folders
    load_folder_recursively(INGESTION_FOLDERS, docs_store, DOCS_COLLECTION_NAME)

    print("✅ Document ingestion completed!")


if __name__ == "__main__":
    print("RAG System Setup")
    print("================")

    # Initialize the RAG system
    initialize_rag_system()

    # Ingest documents if folders are configured
    if INGESTION_FOLDERS:
        print("\nStarting document ingestion...")
        ingest_documents()
    else:
        print("\n⚠️  No ingestion folders configured.")
        print("To add documents to the RAG system:")
        print("1. Edit src/config/rag_config.py")
        print("2. Add folder paths to INGESTION_FOLDERS")
        print("3. Run this script again or call ingest_documents()")

    print("\nRAG system setup complete!")