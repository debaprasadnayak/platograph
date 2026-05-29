"""Base extractor ABC and extractor registry."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from datagraph.models import DataLayer, Edge, Node

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type["BaseExtractor"]] = {}


def register(cls: type["BaseExtractor"]) -> type["BaseExtractor"]:
    """Decorator that registers an extractor by its class name."""
    _REGISTRY[cls.__name__] = cls
    return cls


def get_all_extractors() -> list["BaseExtractor"]:
    return [cls() for cls in _REGISTRY.values()]


class BaseExtractor(ABC):
    """
    An extractor scans one or more files and returns lists of Nodes and Edges.
    Extractors MUST be stateless. They MUST never raise — catch all exceptions,
    log a warning, and return empty lists.
    """

    #: file extensions this extractor handles (empty = directory-level extractor)
    supported_extensions: ClassVar[list[str]] = []

    @abstractmethod
    def extract(self, path: Path, project_root: Path) -> tuple[list[Node], list[Edge]]:
        """
        Extract nodes and edges from *path*.
        *project_root* is provided for relative-path calculations.
        """
        ...

    # ------------------------------------------------------------------
    # Helpers shared across all extractors
    # ------------------------------------------------------------------

    def make_node_id(self, *parts: str) -> str:
        return "::".join(p.lower().strip() for p in parts if p)

    def relative_path(self, path: Path, root: Path) -> str:
        try:
            return str(path.relative_to(root))
        except ValueError:
            return str(path)

    def safe_extract(
        self, path: Path, project_root: Path
    ) -> tuple[list[Node], list[Edge]]:
        """Wrapper that swallows all exceptions and logs them."""
        try:
            return self.extract(path, project_root)
        except Exception:
            logger.warning("Extractor %s failed on %s", self.__class__.__name__, path, exc_info=True)
            return [], []

    def infer_layer_from_path(self, path: str, layer_paths: dict[str, list[str]]) -> DataLayer:
        lower = path.lower()
        layer_map = {
            "source": DataLayer.SOURCE,
            "bronze": DataLayer.BRONZE,
            "silver": DataLayer.SILVER,
            "gold": DataLayer.GOLD,
            "datamart": DataLayer.DATAMART,
            "reporting": DataLayer.REPORTING,
        }
        for layer_name, patterns in layer_paths.items():
            for pattern in patterns:
                if pattern.lower() in lower:
                    return layer_map.get(layer_name, DataLayer.UNKNOWN)
        return DataLayer.UNKNOWN
