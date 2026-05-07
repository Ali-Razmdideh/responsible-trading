from __future__ import annotations

from typing import Any

from .llm import generate_regulatory_llm
from .vocab import INTERVENTIONS


def generate_regulatory_mapping(mock: bool = False) -> list[dict[str, Any]]:
    """Generate regulatory mapping for all intervention types."""
    intervention_types = sorted(INTERVENTIONS)
    return generate_regulatory_llm(intervention_types, mock=mock)
