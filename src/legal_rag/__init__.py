"""Competitive legal retrieval MVP.

The package is intentionally dependency-light so the provincial-competition
prototype can run against the supplied XLSX seed corpus without a vector DB.
"""

from .pipeline import LegalRAGPipeline

__all__ = ["LegalRAGPipeline"]
