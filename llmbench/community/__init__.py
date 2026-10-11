"""Offline, sanitised community-result exports.

This package deliberately projects persisted summaries through a small public
contract.  It never uploads a result and does not share the private ZIP export.
"""

from .io import export_inputs, validate_document

__all__ = ["export_inputs", "validate_document"]
