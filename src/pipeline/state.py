from __future__ import annotations

import datetime
import json
from enum import Enum
from pathlib import Path

from .io import ROOT


class Stage(str, Enum):
    INIT = "INIT"
    INPUTS_LOADED = "INPUTS_LOADED"
    DATASET_EXTENDED_OR_VALIDATED = "DATASET_EXTENDED_OR_VALIDATED"
    FEATURES_COMPUTED = "FEATURES_COMPUTED"
    PATTERNS_CLASSIFIED = "PATTERNS_CLASSIFIED"
    RISK_SCORES_COMPUTED = "RISK_SCORES_COMPUTED"
    INTERVENTIONS_GENERATED = "INTERVENTIONS_GENERATED"
    VALIDATION_COMPLETE = "VALIDATION_COMPLETE"
    RESULTS_FINALISED = "RESULTS_FINALISED"


STAGE_ORDER: list[Stage] = [
    Stage.INIT,
    Stage.INPUTS_LOADED,
    Stage.DATASET_EXTENDED_OR_VALIDATED,
    Stage.FEATURES_COMPUTED,
    Stage.PATTERNS_CLASSIFIED,
    Stage.RISK_SCORES_COMPUTED,
    Stage.INTERVENTIONS_GENERATED,
    Stage.VALIDATION_COMPLETE,
    Stage.RESULTS_FINALISED,
]


def _guards(base_dir: Path) -> dict[Stage, list[Path]]:
    return {
        Stage.INPUTS_LOADED: [
            base_dir / "trades.json",
            base_dir / "economic_calendar.json",
        ],
        Stage.DATASET_EXTENDED_OR_VALIDATED: [base_dir / "trades.json"],
        Stage.FEATURES_COMPUTED: [base_dir / "features"],
        Stage.PATTERNS_CLASSIFIED: [base_dir / "patterns.json"],
        Stage.RISK_SCORES_COMPUTED: [base_dir / "risk_scores.json"],
        Stage.INTERVENTIONS_GENERATED: [base_dir / "interventions.json"],
        Stage.VALIDATION_COMPLETE: [],
        Stage.RESULTS_FINALISED: [],
    }


class StateMachine:
    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = Path(base_dir) if base_dir else ROOT
        self._state_file = self._base / ".pipeline_state.json"
        self._current: Stage = Stage.INIT
        self._history: list[dict[str, str]] = []
        self._load()

    def _load(self) -> None:
        if not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text())
            self._current = Stage(data.get("current_stage", "INIT"))
            self._history = data.get("history", [])
        except Exception:
            pass

    def _save(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "current_stage": self._current.value,
            "history": self._history,
        }
        tmp = self._state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._state_file)

    @property
    def current_stage(self) -> Stage:
        return self._current

    def _index(self, stage: Stage) -> int:
        return STAGE_ORDER.index(stage)

    def is_complete(self, stage: Stage) -> bool:
        return self._index(stage) <= self._index(self._current)

    def advance(self, target: Stage | str) -> None:
        if isinstance(target, str):
            target = Stage(target)

        target_idx = self._index(target)
        current_idx = self._index(self._current)

        if target_idx <= current_idx:
            return  # idempotent

        prev = STAGE_ORDER[target_idx - 1] if target_idx > 0 else None
        if prev and not self.is_complete(prev):
            raise RuntimeError(
                f"Cannot advance to {target.value}: "
                f"predecessor {prev.value} not complete."
            )

        for guard in _guards(self._base).get(target, []):
            if not guard.exists():
                raise RuntimeError(
                    f"Cannot advance to {target.value}: "
                    f"required artifact missing: {guard}"
                )
            if guard.is_dir() and not any(guard.glob("*.json")):
                raise RuntimeError(
                    f"Cannot advance to {target.value}: "
                    f"required directory empty: {guard}"
                )

        self._current = target
        self._history.append(
            {
                "stage": target.value,
                "completed_at": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
            }
        )
        self._save()
        print(f"[state] → {target.value}")

    def reset(self) -> None:
        self._current = Stage.INIT
        self._history = []
        self._save()
