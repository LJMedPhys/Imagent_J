from langchain.tools import tool
from langchain_core.documents import Document
from .utils import init_vec_store
from .vector_stores import vec_store_docs, vec_store_mistakes

__all__ = ['rag_retrieve_docs', 'rag_retrieve_mistakes', 'save_coding_experience']


@tool("rag_retrieve")
def rag_retrieve_docs(query: str) -> str:
    """
    Retrieve relevant context from the document RAG.
    Input should be a precise information-seeking query.
    """

    retriever = vec_store_docs.as_retriever(
        search_type="mmr",  # or "similarity"
        search_kwargs={
            "k": 8,
            "fetch_k": 30,
        },
    )
    docs = retriever.invoke(query)

    results = []
    for d in docs:
        results.append(
            {
                "content": d.page_content,
                "source": d.metadata.get("source"),
                "page": d.metadata.get("page"),
            }
        )

    return results


@tool("rag_retrieve_mistakes")
def rag_retrieve_mistakes(query: str) -> str:
    """
    Retrieve relevant context from the coding errors and solutions RAG.
    Input should be a precise information-seeking query.
    """
    retriever = vec_store_mistakes.as_retriever(
        search_type="mmr",  # or "similarity"
        search_kwargs={
            "k": 8,
            "fetch_k": 30,
        },
    )
    docs = retriever.invoke(query)

    results = []
    for d in docs:
        results.append(
            {
                "content": d.page_content,
                "source": d.metadata.get("source"),
                "page": d.metadata.get("page"),
            }
        )

    return results


@tool("save_coding_experience")
def save_coding_experience(error_description: str, failed_code: str, working_code: str, class_involved: str):
    """
    Saves a successful fix to the persistent Memory RAG.
    Use this after the debugger fixes a script to prevent the error from happening again.
    """
    # Create a structured text block for the embedding
    content = f"""
    PROBLEM: {error_description}
    FAILED CODE: {failed_code}
    WORKING SOLUTION:
    {working_code}
    CLASS INVOLVED: {class_involved}
    """

    doc = Document(
        page_content=content,
        metadata={
            "type": "lesson_learned",
            "class": class_involved,
            "error_type": "MissingMethod" if "MissingMethod" in error_description else "Logic"
        }
    )

    # Use your existing vector_store logic to add this to a NEW collection
    # Recommended collection name: "AgentMemory"
    vec_store_mistakes.add_documents([doc])
    return "Experience saved successfully. I will remember this for future tasks."