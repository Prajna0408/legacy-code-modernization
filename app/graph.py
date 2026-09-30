from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.parser import parse_sources
from app.splitting_agent import SplittingAgent
from app.documentation_agent import DocumentationAgent
from app.evaluation_agent import EvaluationAgent
from app.coding_agent import CodingAgent
from app.testing_agent import TestingAgent
from app.dashboard import DashboardBuilder
from app.state import PipelineState
from app.supervisor_agent import SupervisorAgent


class GraphState(TypedDict, total=False):
    """
    LangGraph transport state.

    PipelineState continues to hold the actual pipeline artifacts.
    The supervisor fields are routing metadata only.
    """

    run_id: str
    raw_source_files: list[dict[str, str]]
    artifacts: dict[str, Any]
    events: list[dict[str, Any]]
    status: str

    evaluation_retries: int
    max_evaluation_retries: int
    testing_retries: int
    max_testing_retries: int

    current_agent: str
    next_agent: str
    supervisor_reason: str
    supervisor_confidence: float
    supervisor_decisions: list[dict[str, Any]]
    supervisor_steps: int
    max_supervisor_steps: int


# this function converts a GraphState dictionary into a PipelineState object, preserving artifacts and audit events. It is used to bridge the gap between the LangGraph transport state and the internal pipeline state representation.
def _to_pipeline_state(state: GraphState) -> PipelineState:
    pipeline_state = PipelineState(
        run_id=state.get("run_id", "default-run"),
        artifacts=dict(state.get("artifacts", {})),
    )

    # Preserve existing audit events across LangGraph node boundaries.
    # PipelineState stores StateEvent objects, while GraphState transports
    # dictionaries.
    for event in state.get("events", []):
        try:
            from app.state import StateEvent

            pipeline_state.events.append(
                StateEvent(
                    stage=str(event["stage"]),
                    action=str(event["action"]),
                    artifact=str(event["artifact"]),
                    timestamp=str(event["timestamp"]),
                )
            )
        except (KeyError, TypeError):
            continue

    return pipeline_state


def _serialize_pipeline_state(
    pipeline_state: PipelineState,
) -> dict[str, Any]:
    return {
        "artifacts": pipeline_state.artifacts,
        "events": pipeline_state.audit_log(),
    }


def _passthrough_retry_fields(
    state: GraphState,
) -> dict[str, Any]:
    return {
        "evaluation_retries": state.get("evaluation_retries", 0),
        "max_evaluation_retries": state.get(
            "max_evaluation_retries", 2
        ),
        "testing_retries": state.get("testing_retries", 0),
        "max_testing_retries": state.get(
            "max_testing_retries", 2
        ),
    }


# ---------------------------------------------------------------------------
# Existing pipeline agent nodes
# ---------------------------------------------------------------------------

def parser_node(state: GraphState) -> GraphState:
    pipeline_state = _to_pipeline_state(state)

    parser_output = parse_sources(
        state.get("raw_source_files", [])
    )

    pipeline_state.write_artifact(
        "parser_output",
        parser_output,
        stage="parser",
    )

    serialized = _serialize_pipeline_state(pipeline_state)

    return {
        "artifacts": serialized["artifacts"],
        "events": serialized["events"],
        "status": "PARSER_COMPLETE",
        "current_agent": "parser",
        **_passthrough_retry_fields(state),
    }


def splitting_node(state: GraphState) -> GraphState:
    pipeline_state = _to_pipeline_state(state)

    SplittingAgent().run(pipeline_state)

    serialized = _serialize_pipeline_state(pipeline_state)

    return {
        "artifacts": serialized["artifacts"],
        "events": serialized["events"],
        "status": "DECOMPOSED",
        "current_agent": "splitting_agent",
        **_passthrough_retry_fields(state),
    }


def documentation_node(state: GraphState) -> GraphState:
    pipeline_state = _to_pipeline_state(state)

    # Preserve the retry payload that the original graph prepared before
    # calling DocumentationAgent. This is an adapter in the graph only; the
    # DocumentationAgent implementation itself is unchanged.
    evaluation_output = pipeline_state.read_artifact(
        "evaluation_output"
    ) if pipeline_state.has_artifact("evaluation_output") else None

    evaluation_feedback = pipeline_state.read_artifact(
        "evaluation_feedback"
    ) if pipeline_state.has_artifact("evaluation_feedback") else None

    if (
        state.get("current_agent") == "evaluation_agent"
        and isinstance(evaluation_output, dict)
        and evaluation_output.get("status") == "REJECTED"
        and isinstance(evaluation_feedback, dict)
    ):
        retry_payload = dict(evaluation_output)
        retry_payload.update(evaluation_feedback)

        if "previous_gherkin_scenarios" not in retry_payload:
            previous_documentation = (
                pipeline_state.read_artifact("documentation_output")
                if pipeline_state.has_artifact("documentation_output")
                else {}
            )
            retry_payload["previous_gherkin_scenarios"] = (
                previous_documentation.get("gherkin_scenarios", [])
            )
            retry_payload["previous_openapi_spec"] = (
                previous_documentation.get("openapi_spec", {})
            )
            retry_payload["previous_technical_documentation"] = (
                previous_documentation.get(
                    "technical_documentation",
                    "",
                )
            )

        pipeline_state.replace_artifact(
            "evaluation_output",
            retry_payload,
            stage="supervisor",
        )

    DocumentationAgent(output_dir="outputs").run(
        pipeline_state
    )

    serialized = _serialize_pipeline_state(pipeline_state)

    status = (
        "DOCUMENTATION_REFINED"
        if "evaluation_output" in pipeline_state.artifacts
        else "DOCUMENTED"
    )

    return {
        "artifacts": serialized["artifacts"],
        "events": serialized["events"],
        "status": status,
        "current_agent": "documentation_agent",
        **_passthrough_retry_fields(state),
    }


def evaluation_node(state: GraphState) -> GraphState:
    pipeline_state = _to_pipeline_state(state)

    agent = EvaluationAgent()
    evaluation = agent.run(pipeline_state)

    serialized = _serialize_pipeline_state(pipeline_state)

    return {
        "artifacts": serialized["artifacts"],
        "events": serialized["events"],
        "status": (
            "EVALUATION_APPROVED"
            if evaluation.get("status") == "APPROVED"
            else "EVALUATION_REJECTED"
        ),
        "current_agent": "evaluation_agent",
        **_passthrough_retry_fields(state),
    }


def coding_node(state: GraphState) -> GraphState:
    pipeline_state = _to_pipeline_state(state)

    CodingAgent(output_dir="outputs").run(
        pipeline_state
    )

    serialized = _serialize_pipeline_state(pipeline_state)

    return {
        "artifacts": serialized["artifacts"],
        "events": serialized["events"],
        "status": "TARGET_CODE_GENERATED",
        "current_agent": "coding_agent",
        **_passthrough_retry_fields(state),
    }


def testing_node(state: GraphState) -> GraphState:
    pipeline_state = _to_pipeline_state(state)

    TestingAgent(output_dir="outputs").run(
        pipeline_state
    )

    serialized = _serialize_pipeline_state(pipeline_state)
    testing_output = pipeline_state.read_artifact(
        "testing_output"
    )

    status = (
        "TESTING_VERIFIED"
        if testing_output.get("status") == "VERIFIED"
        else "TESTING_FAILED"
    )

    return {
        "artifacts": serialized["artifacts"],
        "events": serialized["events"],
        "status": status,
        "current_agent": "testing_agent",
        **_passthrough_retry_fields(state),
    }


def dashboard_node(state: GraphState) -> GraphState:
    pipeline_state = _to_pipeline_state(state)

    builder = DashboardBuilder(output_dir="outputs")

    report = builder.build(
        pipeline_state,
        evaluation_retries=int(
            state.get("evaluation_retries", 0)
        ),
        max_evaluation_retries=int(
            state.get("max_evaluation_retries", 2)
        ),
        testing_retries=int(
            state.get("testing_retries", 0)
        ),
        max_testing_retries=int(
            state.get("max_testing_retries", 2)
        ),
    )

    if pipeline_state.has_artifact("dashboard_report"):
        pipeline_state.replace_artifact(
            "dashboard_report",
            report,
            stage=DashboardBuilder.STAGE,
        )
    else:
        pipeline_state.write_artifact(
            "dashboard_report",
            report,
            stage=DashboardBuilder.STAGE,
        )

    serialized = _serialize_pipeline_state(pipeline_state)

    return {
        "artifacts": serialized["artifacts"],
        "events": serialized["events"],
        "status": report.get(
            "overall_pipeline_status",
            "COMPLETED",
        ),
        "current_agent": "dashboard",
        **_passthrough_retry_fields(state),
    }


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

# defines which agents are currently available for selection by the Supervisor, based on the current state of artifacts and retry counts
def _available_agents(
    state: GraphState,
) -> list[str]:
    """
    Determine capabilities that are currently executable.

    This is NOT the workflow. It only prevents the LLM from selecting an
    agent whose input contract cannot currently be satisfied.
    """
    artifacts = state.get("artifacts", {})
    current = state.get("current_agent", "")
    evaluation = artifacts.get("evaluation_output", {}) or {}
    testing = artifacts.get("testing_output", {}) or {}

    available: list[str] = []

    # Splitting is available after Parser and only before a splitting result
    # exists. It can also be selected if a future agentic decision explicitly
    # requires a new decomposition, but we avoid unnecessary repetition.
    if (
        "parser_output" in artifacts
        and "splitting_output" not in artifacts
    ):
        available.append("splitting_agent")

    # Documentation is available after splitting. Re-running it is allowed
    # only when evaluation rejected the documentation and retry budget remains.
    evaluation_rejected = (
        evaluation.get("status") == "REJECTED"
    )
    evaluation_retry_available = (
        int(state.get("evaluation_retries", 0))
        < int(state.get("max_evaluation_retries", 2))
    )

    if "splitting_output" in artifacts:
        if "documentation_output" not in artifacts:
            available.append("documentation_agent")
        elif (
            current == "evaluation_agent"
            and evaluation_rejected
            and evaluation_retry_available
        ):
            available.append("documentation_agent")

    # Evaluation is available whenever documentation exists.
    # This permits the supervisor to return to the quality gate after a
    # documentation refinement.
    if "documentation_output" in artifacts:
        if current == "documentation_agent" or "evaluation_output" not in artifacts:
            available.append("evaluation_agent")

    # Coding is available after an approved evaluation. It is also available
    # after a failed testing run while the testing retry budget remains.
    evaluation_approved = (
        evaluation.get("status") == "APPROVED"
    )
    testing_failed = (
        testing.get("status") == "FAILED"
    )
    testing_retry_available = (
        int(state.get("testing_retries", 0))
        < int(state.get("max_testing_retries", 2))
    )

    if evaluation_approved:
        if "target_output" not in artifacts:
            available.append("coding_agent")
        elif (
            current == "testing_agent"
            and testing_failed
            and testing_retry_available
        ):
            available.append("coding_agent")

    # Testing is available after target code exists. Re-testing after coding
    # self-healing is allowed.
    if "target_output" in artifacts:
        if "testing_output" not in artifacts:
            available.append("testing_agent")
        elif (
            current == "coding_agent"
            and testing_failed
        ):
            available.append("testing_agent")

    # Dashboard is the terminal reporting capability. It becomes available
    # after a verified test result or after either quality gate exhausts its
    # retry budget.
    evaluation_retry_limit = (
        evaluation.get("status") == "REJECTED"
        and int(state.get("evaluation_retries", 0))
        >= int(state.get("max_evaluation_retries", 2))
    )
    testing_retry_limit = (
        testing.get("status") == "FAILED"
        and int(state.get("testing_retries", 0))
        >= int(state.get("max_testing_retries", 2))
    )
    testing_verified = testing.get("status") == "VERIFIED"

    if (
        testing_verified
        or evaluation_retry_limit
        or testing_retry_limit
    ):
        available.append("dashboard")

    # Preserve order only for stable prompt presentation; the Supervisor,
    # not this function, chooses the next capability.
    return list(dict.fromkeys(available))

# the Supervisor node is responsible for deciding which agent to invoke next based on the current state of the pipeline, including artifacts, status, and retry counts. It also tracks the number of steps taken to prevent infinite loops.
def _supervisor_node(
    state: GraphState,
) -> GraphState:
    supervisor = SupervisorAgent()

    steps = int(state.get("supervisor_steps", 0)) + 1
    maximum_steps = int(
        state.get("max_supervisor_steps", 20)
    )

    if steps > maximum_steps:
        raise RuntimeError(
            "Supervisor exceeded the maximum number of routing steps. "
            "Pipeline stopped to prevent an infinite agentic loop."
        )

    artifacts = state.get("artifacts", {})
    available = _available_agents(state)

    if not available:
        raise RuntimeError(
            "Supervisor has no executable capability for the current state. "
            f"current_agent={state.get('current_agent')!r}, "
            f"status={state.get('status')!r}, "
            f"artifacts={sorted(artifacts.keys())!r}"
        )

    decision = supervisor.decide(
        current_agent=state.get("current_agent", "parser"),
        status=state.get("status", "RUNNING"),
        artifacts=artifacts,
        evaluation_retries=int(
            state.get("evaluation_retries", 0)
        ),
        max_evaluation_retries=int(
            state.get("max_evaluation_retries", 2)
        ),
        testing_retries=int(
            state.get("testing_retries", 0)
        ),
        max_testing_retries=int(
            state.get("max_testing_retries", 2)
        ),
        available_agents=available,
        decision_history=state.get(
            "supervisor_decisions",
            [],
        ),
    )

    decision_record = {
        "step": steps,
        "from_agent": state.get("current_agent", "parser"),
        "next_agent": decision["next_agent"],
        "reason": decision["reason"],
        "confidence": decision["confidence"],
    }

    history = list(
        state.get("supervisor_decisions", [])
    )
    history.append(decision_record)

    # Retry counters are updated only when the Supervisor actually chooses
    # the corresponding refinement/self-healing action.
    evaluation_retries = int(
        state.get("evaluation_retries", 0)
    )
    testing_retries = int(
        state.get("testing_retries", 0)
    )

    if (
        decision["next_agent"] == "documentation_agent"
        and state.get("current_agent") == "evaluation_agent"
        and (
            artifacts.get("evaluation_output", {}) or {}
        ).get("status") == "REJECTED"
    ):
        evaluation_retries += 1

    if (
        decision["next_agent"] == "coding_agent"
        and state.get("current_agent") == "testing_agent"
        and (
            artifacts.get("testing_output", {}) or {}
        ).get("status") == "FAILED"
    ):
        testing_retries += 1

    return {
        "status": "SUPERVISING",
        "next_agent": decision["next_agent"],
        "supervisor_reason": decision["reason"],
        "supervisor_confidence": decision["confidence"],
        "supervisor_decisions": history,
        "supervisor_steps": steps,
        "max_supervisor_steps": maximum_steps,
        "evaluation_retries": evaluation_retries,
        "max_evaluation_retries": state.get(
            "max_evaluation_retries", 2
        ),
        "testing_retries": testing_retries,
        "max_testing_retries": state.get(
            "max_testing_retries", 2
        ),
        "artifacts": state.get("artifacts", {}),
        "events": state.get("events", []),
    }


# this function is used to determine the next agent to invoke based on the supervisor's decision. It validates that the next agent is one of the allowed agents and raises an error if it is not.
def _route_from_supervisor(
    state: GraphState,
) -> str:
    next_agent = state.get("next_agent")

    if next_agent not in {
        "splitting_agent",
        "documentation_agent",
        "evaluation_agent",
        "coding_agent",
        "testing_agent",
        "dashboard",
    }:
        raise ValueError(
            "Supervisor produced an invalid next_agent: "
            f"{next_agent!r}"
        )

    return next_agent


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph():
    builder = StateGraph(GraphState)

    builder.add_node("parser", parser_node)
    builder.add_node("supervisor", _supervisor_node)
    builder.add_node("splitting_agent", splitting_node)
    builder.add_node("documentation_agent", documentation_node)
    builder.add_node("evaluation_agent", evaluation_node)
    builder.add_node("coding_agent", coding_node)
    builder.add_node("testing_agent", testing_node)
    builder.add_node("dashboard", dashboard_node)

    # Parser remains the fixed entry point. Everything after Parser is
    # selected by the Supervisor.
    builder.add_edge(START, "parser")
    builder.add_edge("parser", "supervisor")

    # Every processing agent returns control to the Supervisor.
    builder.add_edge("splitting_agent", "supervisor")
    builder.add_edge("documentation_agent", "supervisor")
    builder.add_edge("evaluation_agent", "supervisor")
    builder.add_edge("coding_agent", "supervisor")
    builder.add_edge("testing_agent", "supervisor")

    # Supervisor dynamically dispatches to whichever capability it selected.
    builder.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "splitting_agent": "splitting_agent",
            "documentation_agent": "documentation_agent",
            "evaluation_agent": "evaluation_agent",
            "coding_agent": "coding_agent",
            "testing_agent": "testing_agent",
            "dashboard": "dashboard",
        },
    )

    builder.add_edge("dashboard", END)

    return builder.compile()


graph = build_graph()


def run_full_pipeline(
    run_id: str,
    source_files: list[dict[str, str]],
    max_evaluation_retries: int = 2,
    max_testing_retries: int = 2,
) -> GraphState:
    initial_state: GraphState = {
        "run_id": run_id,
        "raw_source_files": source_files,
        "artifacts": {},
        "events": [],
        "status": "RUNNING",
        "evaluation_retries": 0,
        "max_evaluation_retries": max_evaluation_retries,
        "testing_retries": 0,
        "max_testing_retries": max_testing_retries,
        "current_agent": "parser",
        "supervisor_steps": 0,
        "max_supervisor_steps": 20,
        "supervisor_decisions": [],
    }

    return graph.invoke(initial_state)


__all__ = [
    "GraphState",
    "build_graph",
    "graph",
    "run_full_pipeline",
]
