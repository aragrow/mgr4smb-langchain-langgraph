"""Shared LLM and embeddings factory — all agents use these."""

import logging

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from mgr4smb.config import settings

logger = logging.getLogger(__name__)

_llm: ChatGoogleGenerativeAI | None = None
_embeddings: GoogleGenerativeAIEmbeddings | None = None


def get_llm() -> ChatGoogleGenerativeAI:
    """Return a singleton ChatGoogleGenerativeAI (gemini-2.5-flash).

    temperature=0.2 is important for agent orchestration: the default (~1.0)
    occasionally causes Gemini to emit an empty response with finish_reason=STOP
    when deciding between tool calls. Low temperature keeps tool-routing stable.
    """
    global _llm
    if _llm is None:
        _llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=settings.google_api_key,
            temperature=0.2,
        )
        logger.info("LLM initialised model=gemini-2.5-flash temperature=0.2")
    return _llm


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    """Return a singleton GoogleGenerativeAIEmbeddings (gemini-embedding-001, 768 dims)."""
    global _embeddings
    if _embeddings is None:
        _embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key=settings.google_api_key,
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=768,  # Match MongoDB Atlas index (768 dims, not default 3072)
        )
        logger.info("Embeddings initialised model=models/gemini-embedding-001")
    return _embeddings
