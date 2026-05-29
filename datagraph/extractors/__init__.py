"""Extractor package — import all sub-packages to trigger registration."""

from datagraph.extractors.base import BaseExtractor, get_all_extractors, register

# Import sub-packages to trigger @register decorators
from datagraph.extractors import transformation  # noqa: F401
from datagraph.extractors import storage         # noqa: F401
from datagraph.extractors import orchestration   # noqa: F401
from datagraph.extractors import bi              # noqa: F401

__all__ = ["BaseExtractor", "get_all_extractors", "register"]
