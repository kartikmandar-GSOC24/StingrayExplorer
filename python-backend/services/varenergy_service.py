"""
Var-energy service for energy-dependent variability spectra.

Implemented per docs/superpowers/plans/2026-07-29-quicklook-remaining-pages.md.
"""

from .base_service import BaseService


class VarEnergyService(BaseService):
    """Service for rms/lag/excess-variance/covariance energy spectra. Implementation lands in Phase 1."""
