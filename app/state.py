from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

ARTIFACT_NAMES = (
    "parser_output",
    "splitting_input",
    "splitting_output",
    "documentation_input",
    "documentation_output",
    "evaluation_output",
    "evaluation_feedback",
    "target_output",
    "testing_output",
    "dashboard_report",
)

@dataclass(frozen=True)
class StateEvent:
    stage: str
    action: str
    artifact: str
    timestamp: str

@dataclass
class PipelineState:
    run_id: str = "default-run"
    artifacts: dict[str, Any] = field(default_factory=dict)
    events: list[StateEvent] = field(default_factory=list)

    def write_artifact(self, name: str, value: Any, *, stage: str) -> None:
        self._validate_name(name)
        if name in self.artifacts:
            raise ValueError(
                f"Artifact '{name}' already exists. Use replace_artifact() for an intentional refinement."
            )
        self.artifacts[name] = deepcopy(value)
        self._record(stage, "write", name)

    def replace_artifact(self, name: str, value: Any, *, stage: str) -> None:
        self._validate_name(name)
        self.artifacts[name] = deepcopy(value)
        self._record(stage, "replace", name)

    def read_artifact(self, name: str) -> Any:
        self._validate_name(name)
        if name not in self.artifacts:
            raise KeyError(f"Artifact '{name}' is not available in shared state.")
        return deepcopy(self.artifacts[name])

    def has_artifact(self, name: str) -> bool:
        self._validate_name(name)
        return name in self.artifacts

    def available_artifacts(self) -> list[str]:
        return sorted(self.artifacts)

    def audit_log(self) -> list[dict[str, str]]:
        return [
            {
                "stage": e.stage,
                "action": e.action,
                "artifact": e.artifact,
                "timestamp": e.timestamp,
            }
            for e in self.events
        ]

    def _record(self, stage: str, action: str, artifact: str) -> None:
        self.events.append(
            StateEvent(
                stage=stage,
                action=action,
                artifact=artifact,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )

    @staticmethod
    def _validate_name(name: str) -> None:
        if name not in ARTIFACT_NAMES:
            raise ValueError(
                f"Unsupported artifact '{name}'. Expected one of: "
                + ", ".join(ARTIFACT_NAMES)
            )

__all__ = ["PipelineState", "StateEvent", "ARTIFACT_NAMES"]
