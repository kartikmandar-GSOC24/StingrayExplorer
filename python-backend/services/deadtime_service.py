"""
Dead-time service for dead-time model and FAD corrections.

Implemented per docs/superpowers/plans/2026-07-29-quicklook-remaining-pages.md.
"""

from .base_service import BaseService


class DeadtimeService(BaseService):
    """Service for dead-time correction operations. Implementation lands in Phase 1."""
