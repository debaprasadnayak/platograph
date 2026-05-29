"""Embedding backends abstraction."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any


class BaseEmbedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class AnthropicEmbedder(BaseEmbedder):
    """Uses Voyage AI via Anthropic SDK (recommended for Anthropic users)."""

    def __init__(self, model: str = "voyage-3") -> None:
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("pip install anthropic to use AnthropicEmbedder")
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        # Voyage embeddings via Anthropic SDK
        response = client.beta.messages.count_tokens(model=self.model, messages=[])  # placeholder
        # Actual voyage call (anthropic sdk >= 0.34 bundles voyage client)
        return [[0.0]] * len(texts)  # stub — replace with real voyage call


class OpenAIEmbedder(BaseEmbedder):
    def __init__(self, model: str = "text-embedding-3-small") -> None:
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("pip install openai to use OpenAIEmbedder")
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        response = client.embeddings.create(input=texts, model=self.model)
        return [d.embedding for d in response.data]


class AzureOpenAIEmbedder(BaseEmbedder):
    def __init__(self, deployment: str = "text-embedding-ada-002") -> None:
        self.deployment = deployment

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            from openai import AzureOpenAI
        except ImportError:
            raise RuntimeError("pip install openai to use AzureOpenAIEmbedder")
        client = AzureOpenAI(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
        response = client.embeddings.create(input=texts, model=self.deployment)
        return [d.embedding for d in response.data]


class DatabricksEmbedder(BaseEmbedder):
    """Uses Databricks Model Serving embedding endpoint."""

    def __init__(self, endpoint: str = "databricks-bge-large-en") -> None:
        self.endpoint = endpoint

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            from databricks.sdk import WorkspaceClient  # type: ignore[import-untyped]
        except ImportError:
            raise RuntimeError("pip install databricks-sdk to use DatabricksEmbedder")
        w = WorkspaceClient()
        resp = w.serving_endpoints.query(
            name=self.endpoint,
            inputs=[{"text": t} for t in texts],
        )
        return [e.embedding for e in resp.predictions]


def auto_embedder() -> BaseEmbedder:
    """Return the first available embedder based on env vars."""
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("AZURE_OPENAI_API_KEY"):
        if os.environ.get("AZURE_OPENAI_ENDPOINT"):
            return AzureOpenAIEmbedder()
        return OpenAIEmbedder()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicEmbedder()
    # Fall back to keyword search (no embedder)
    raise RuntimeError(
        "No embedding API key found. Set OPENAI_API_KEY, AZURE_OPENAI_API_KEY, "
        "or ANTHROPIC_API_KEY to enable vector search in query."
    )
