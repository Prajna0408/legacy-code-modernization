from __future__ import annotations

import json
import os
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore

try:
    from openai import AzureOpenAI
except ImportError:  # pragma: no cover
    AzureOpenAI = None  # type: ignore


AGENT_NAMES = (
    "splitting_agent",
    "documentation_agent",
    "evaluation_agent",
    "coding_agent",
    "testing_agent",
    "dashboard",
)


class SupervisorAgent:
    """
    Agentic controller for the legacy-code-modernization pipeline.

    This class does NOT execute any pipeline agent. It only observes the
    current pipeline state and chooses the next available capability.

    The existing Parser, Splitting, Documentation, Evaluation, Coding,
    Testing and Dashboard implementations remain unchanged.
    """

    STAGE = "supervisor"

    def __init__(self) -> None:
        if load_dotenv is not None:
            load_dotenv()

        if AzureOpenAI is None:
            raise RuntimeError(
                "The 'openai' package is required for SupervisorAgent."
            )

        endpoint = (
            os.getenv("AZURE_OPENAI_ENDPOINT")
            or os.getenv("azure_endpoint")
        )
        api_key = (
            os.getenv("AZURE_OPENAI_API_KEY")
            or os.getenv("AZURE_OPENAI_KEY")
        )
        api_version = (
            os.getenv("AZURE_OPENAI_API_VERSION")
            or os.getenv("api_version")
            or "2024-12-01-preview"
        )
        deployment = (
            os.getenv("AZURE_OPENAI_DEPLOYMENT")
            or os.getenv("model")
        )

        missing = [
            name
            for name, value in (
                ("endpoint", endpoint),
                ("api_key", api_key),
                ("deployment", deployment),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Missing Azure OpenAI configuration for SupervisorAgent: "
                + ", ".join(missing)
            )

        self.client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
        )
        self.deployment = deployment
        self.timeout = float(
            os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "60")
        )

    def decide(
        self,
        *,
        current_agent: str,
        status: str,
        artifacts: dict[str, Any],
        evaluation_retries: int,
        max_evaluation_retries: int,
        testing_retries: int,
        max_testing_retries: int,
        available_agents: list[str],
        decision_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Ask the LLM which available capability should execute next.

        The LLM receives state summaries, not the complete large artifacts.
        This keeps the supervisor inexpensive and prevents it from becoming
        another processing agent.
        """
        artifact_summary = self._summarize_artifacts(artifacts)

        system_prompt = """
You are the Supervisor Agent for a legacy-code modernization system.

Your ONLY responsibility is to decide which ONE available agent/capability
should execute next. You do not perform the work yourself.

The processing agents already exist and must not be redesigned.

Important:
- Do NOT assume a fixed sequence such as splitting -> documentation ->
  evaluation -> coding -> testing.
- Decide from the CURRENT STATE and the latest agent result.
- You may choose any capability listed in available_agents.
- Never choose an unavailable capability.
- Do not repeat an already completed capability unless the current state
  clearly indicates that refinement/self-healing is required.
- Evaluation rejection can require Documentation refinement.
- Testing failure can require Coding self-healing.
- A retry budget must never be exceeded.
- Choose dashboard when a quality gate has exhausted its retry budget or
  testing has been verified and no further processing is required.
- Do not choose parser: Parser is the fixed entry point of this pipeline.
- Return JSON only.

Required response:
{
  "next_agent": "one value from available_agents",
  "reason": "short explanation based on current state",
  "confidence": 0.0
}
""".strip()

        user_payload = {
            "current_agent": current_agent,
            "status": status,
            "available_agents": available_agents,
            "artifacts_present": sorted(artifacts.keys()),
            "artifact_summary": artifact_summary,
            "evaluation_retries": evaluation_retries,
            "max_evaluation_retries": max_evaluation_retries,
            "testing_retries": testing_retries,
            "max_testing_retries": max_testing_retries,
            "recent_decisions": decision_history[-5:],
        }

        print("[Supervisor] Deciding next agent...")
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        user_payload,
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=self.timeout,
        )

        content = response.choices[0].message.content or "{}"
        try:
            decision = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Supervisor returned invalid JSON."
            ) from exc

        if not isinstance(decision, dict):
            raise RuntimeError(
                "Supervisor response must be a JSON object."
            )

        next_agent = decision.get("next_agent")
        if next_agent not in available_agents:
            raise ValueError(
                "Supervisor selected an unavailable agent: "
                f"{next_agent!r}; available={available_agents!r}"
            )

        reason = str(decision.get("reason") or "No reason supplied.")
        try:
            confidence = float(decision.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        print(
            f"[Supervisor] Next agent: {next_agent} | "
            f"Reason: {reason}"
        )

        return {
            "next_agent": next_agent,
            "reason": reason,
            "confidence": max(0.0, min(1.0, confidence)),
        }

    @staticmethod
    def _summarize_artifacts(
        artifacts: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Give the supervisor useful state signals without sending the full
        parser/splitting/evaluation/code/test payloads to the LLM.
        """
        summary: dict[str, Any] = {}

        parser = artifacts.get("parser_output")
        if isinstance(parser, dict):
            summary["parser"] = {
                "files": len(parser.get("files", [])),
                "dependency_edges": len(
                    (parser.get("dependency_call_graph") or {}).get(
                        "edges", []
                    )
                ),
            }

        splitting = artifacts.get("splitting_output")
        if isinstance(splitting, dict):
            summary["splitting"] = {
                "modules": len(splitting.get("modules", [])),
                "execution_paths": len(
                    splitting.get("execution_paths", [])
                ),
                "module_dependencies": len(
                    splitting.get("module_dependencies", [])
                ),
            }

        documentation = artifacts.get("documentation_output")
        if isinstance(documentation, dict):
            summary["documentation"] = {
                "mode": documentation.get("mode"),
                "gherkin_features": len(
                    documentation.get("gherkin_scenarios", [])
                ),
                "has_openapi": bool(
                    documentation.get("openapi_spec")
                ),
            }

        evaluation = artifacts.get("evaluation_output")
        if isinstance(evaluation, dict):
            summary["evaluation"] = {
                "status": evaluation.get("status"),
                "score": evaluation.get("overall_score"),
                "threshold": evaluation.get("threshold"),
            }

        target = artifacts.get("target_output")
        if isinstance(target, dict):
            summary["coding"] = {
                "mode": target.get("mode"),
                "syntax_valid": (
                    target.get("syntax_validation", {}).get("valid")
                    if isinstance(
                        target.get("syntax_validation"), dict
                    )
                    else None
                ),
            }

        testing = artifacts.get("testing_output")
        if isinstance(testing, dict):
            test_summary = testing.get("summary", {})
            summary["testing"] = {
                "status": testing.get("status"),
                "total_tests": test_summary.get("total_tests"),
                "passed": test_summary.get("passed"),
                "failed": test_summary.get("failed"),
                "errors": test_summary.get("errors"),
                "pass_rate": test_summary.get("pass_rate"),
            }

        if "evaluation_feedback" in artifacts:
            summary["evaluation_feedback"] = "present"

        return summary


__all__ = ["SupervisorAgent", "AGENT_NAMES"]
