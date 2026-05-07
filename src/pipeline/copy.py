from __future__ import annotations

from pathlib import Path

from .llm import generate_copy_llm
from .vocab import BANNED_COPY_PHRASES, INTERVENTIONS


def _check_banned(text: str) -> list[str]:
    lower = text.lower()
    return [phrase for phrase in BANNED_COPY_PHRASES if phrase in lower]


def generate_and_save_copy(
    output_dir: Path,
    mock: bool = False,
) -> dict[str, str]:
    """
    Generate one message per intervention type, validate for banned phrases,
    retry once on failure, then write to messages/{type}.md.
    """
    intervention_types = sorted(INTERVENTIONS)
    copy = generate_copy_llm(intervention_types, mock=mock)

    for itype in intervention_types:
        text = copy.get(itype, "")
        banned = _check_banned(text)
        if banned and not mock:
            # Retry once
            copy2 = generate_copy_llm(intervention_types, mock=mock)
            text2 = copy2.get(itype, "")
            if not _check_banned(text2):
                copy[itype] = text2

    output_dir.mkdir(parents=True, exist_ok=True)
    for itype, text in copy.items():
        (output_dir / f"{itype}.md").write_text(text + "\n", encoding="utf-8")

    return copy
