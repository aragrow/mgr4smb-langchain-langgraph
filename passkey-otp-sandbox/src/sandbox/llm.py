"""Shared LLM + embeddings factories — all agents use these singletons."""

from __future__ import annotations

import logging

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from sandbox.config import settings

logger = logging.getLogger(__name__)

_llm: ChatGoogleGenerativeAI | None = None
_embeddings: GoogleGenerativeAIEmbeddings | None = None


def get_llm() -> ChatGoogleGenerativeAI:
    """Return a process-wide ChatGoogleGenerativeAI configured for agent use.

    temperature=0.2 is important for agent routing stability — the default
    (~1.0) occasionally produces finish_reason=STOP with zero tokens, which
    triggers the retry-on-empty path in graph.run_turn and slows every turn.
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
    """Return a singleton GoogleGenerativeAIEmbeddings.

    Model, dimensions, and task type are read from settings (env-driven)
    so the same vectors are interchangeable between the sandbox's local
    JSON store and a MongoDB Atlas vector index in production.
    """
    global _embeddings
    if _embeddings is None:
        _embeddings = GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model,
            google_api_key=settings.google_api_key,
            task_type=settings.embedding_task_type,
            output_dimensionality=settings.embedding_dimensions,
        )
        logger.info(
            "Embeddings initialised model=%s dims=%d task_type=%s",
            settings.embedding_model,
            settings.embedding_dimensions,
            settings.embedding_task_type,
        )
    return _embeddings
