from __future__ import annotations

import ast as pyast
import json
import os
import re
from pathlib import Path
from typing import Any, Protocol

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore

try:
    from openai import AzureOpenAI
except ImportError:  # pragma: no cover
    AzureOpenAI = None  # type: ignore

from .state import PipelineState


class JsonLLM(Protocol):
    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        ...


class AzureOpenAIJsonClient:
    """Small Azure OpenAI adapter used by the Coding Agent.

    Mirrors the adapter used by DocumentationAgent / SplittingAgent so all
    LLM-backed agents in the pipeline resolve credentials identically from
    the environment (the user's own .env file, never hard-coded keys).
    """

    def __init__(self) -> None:
        if load_dotenv is not None:
            load_dotenv()

        if AzureOpenAI is None:
            raise RuntimeError(
                "The 'openai' package is required."
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
                "Missing Azure OpenAI configuration: "
                + ", ".join(missing)
            )

        self.client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
        )
        self.deployment = deployment
        self.timeout = float(
            os.getenv(
                "AZURE_OPENAI_TIMEOUT_SECONDS",
                "60",
            )
        )

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        print(
            "[Coding] Sending Azure OpenAI request..."
        )

        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            temperature=0,
            response_format={
                "type": "json_object"
            },
            timeout=self.timeout,
        )

        content = (
            response.choices[0].message.content
            or "{}"
        )

        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Azure OpenAI returned invalid JSON."
            ) from exc

        if not isinstance(result, dict):
            raise RuntimeError(
                "Azure OpenAI response must be a JSON object."
            )

        print(
            "[Coding] Azure OpenAI response received."
        )
        return result


class CodingAgent:
    """
    Agent 4: Target Code Agent.

    Sequence-diagram contract (Agents Interaction / SequenceDiagram2):
        CentralState ->> Agent4: Fetch Approved OpenAPI Specs & Gherkin Rules
        Agent4 ->> Agent4: Synthesize Modern Target Code (Python FastAPI)
        Agent4 ->> CentralState: Save Target Code
            (schemas.py, service.py, router.py)

    Self-healing loop (SequenceDiagram3):
        CentralState ->> Agent4: Trigger Self-Healing Loop
        Agent4 ->> Agent4: Fix Python Logic using Stack Trace
        Agent4 ->> CentralState: Save Updated Target Code

    Input contract (Codingagent_logic):
        - Approved OpenAPI Specs
        - Gherkin Scenarios (from Agent 2/3)
        - Target Language Style Rules (Python FastAPI)

    Important constraint: Agent 4 reads ONLY the approved specifications
    (documentation_output), never the original legacy syntax. This is
    enforced structurally: this agent never reads parser_output or
    splitting_output from shared state.

    Internal processing logic:
        1. Target Architecture Mapping   -> schemas.py  (Pydantic models)
        2. Service Layer Synthesis       -> service.py  (business logic)
        3. API Router Synthesis          -> router.py   (FastAPI routes)

    Output: generated modern target codebase (FastAPI Router, Service
    Layer, Pydantic Schemas), written to shared state as `target_output`
    and to disk under output_dir/target_code/ so the codebase is runnable.
    """

    STAGE = "coding_agent"

    TARGET_LANGUAGE = "python"
    TARGET_FRAMEWORK = "fastapi"

    def __init__(
        self,
        llm: JsonLLM | None = None,
        output_dir: str | Path = "outputs",
    ) -> None:
        self._llm = llm
        self.output_dir = Path(output_dir)

    # ------------------------------------------------------------------
    # Shared-state entry point
    # ------------------------------------------------------------------

# It reads the approved evaluation output from the shared state and checks if it is approved. If not, it raises a ValueError. It then reads the documentation output and any execution feedback or previous target output if available. The method builds the target input using the documentation output, execution feedback, and previous target output, and processes it to generate the target code. Finally, it writes or replaces the target output in the shared state and returns the updated state.
    def run(
        self,
        state: PipelineState,
    ) -> PipelineState:
        evaluation_output = state.read_artifact(
            "evaluation_output"
        )

        if evaluation_output.get("status") != "APPROVED":
            raise ValueError(
                "Agent 4 (Coding Agent) requires an APPROVED "
                "evaluation_output before generating target code. "
                f"Current status: {evaluation_output.get('status')!r}."
            )

        documentation_output = state.read_artifact(
            "documentation_output"
        )

        execution_feedback = None
        previous_target_output = None

        if state.has_artifact("testing_output"):
            testing_output = state.read_artifact(
                "testing_output"
            )
            if testing_output.get("status") == "FAILED":
                execution_feedback = testing_output.get(
                    "feedback",
                    testing_output,
                )
                if state.has_artifact("target_output"):
                    previous_target_output = state.read_artifact(
                        "target_output"
                    )

        target_input = self.build_target_input(
            documentation_output,
            execution_feedback,
            previous_target_output,
        )

        target_output = self.process(target_input)

        if state.has_artifact("target_output"):
            state.replace_artifact(
                "target_output",
                target_output,
                stage=self.STAGE,
            )
        else:
            state.write_artifact(
                "target_output",
                target_output,
                stage=self.STAGE,
            )

        return state

    # ------------------------------------------------------------------
    # Compact Agent-4 input
    # ------------------------------------------------------------------


# This class method constructs the input for the Coding Agent (Agent 4) by extracting relevant information from the documentation output, execution feedback, and previous target output. It returns a dictionary containing the Gherkin scenarios, OpenAPI specification, target language and framework, execution feedback (if any), and previous target output (if any). This structured input is then used by the process method to generate or self-heal the target codebase.
    @classmethod
    def build_target_input(
        cls,
        documentation_output: dict[str, Any],
        execution_feedback: dict[str, Any] | None = None,
        previous_target_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "gherkin_scenarios": documentation_output.get(
                "gherkin_scenarios",
                [],
            ),
            "openapi_spec": documentation_output.get(
                "openapi_spec",
                {},
            ),
            "target_language": cls.TARGET_LANGUAGE,
            "target_framework": cls.TARGET_FRAMEWORK,
            "execution_feedback": (
                execution_feedback
                if isinstance(execution_feedback, dict)
                else None
            ),
            "previous_target_output": (
                previous_target_output
                if isinstance(previous_target_output, dict)
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------


# this method processes the target input to generate or self-heal the target codebase. It checks if execution feedback is present to determine whether to run the self-healing loop or the initial code synthesis. It validates the generated code for Python syntax and raises a ValueError if any syntax errors are found. Finally, it writes the generated code to disk and returns a dictionary containing the results, including syntax validation and file paths of the written code.
    def process(
        self,
        target_input: dict[str, Any],
    ) -> dict[str, Any]:
        is_self_healing = bool(
            target_input.get("execution_feedback")
        )

        if is_self_healing:
            print(
                "[Coding] Execution feedback found. "
                "Running self-healing loop."
            )
            result = self._self_heal(
                target_input
            )
        else:
            print(
                "[Coding] No execution feedback. "
                "Running initial target code synthesis."
            )
            result = self._generate_initial_codebase(
                target_input
            )

        syntax_validation = self._validate_python_syntax(
            result
        )
        result["syntax_validation"] = syntax_validation

        if not syntax_validation["valid"]:
            raise ValueError(
                "Generated target code failed Python syntax "
                "validation: " + syntax_validation["message"]
            )

        files_written = self._write_target_codebase(
            result
        )
        result["artifacts"] = files_written

        return result

    # ------------------------------------------------------------------
    # Initial generation (Target Architecture Mapping / Service Layer
    # Synthesis / API Router Synthesis)
    # ------------------------------------------------------------------

# this method generates the initial target codebase by invoking the LLM to synthesize Pydantic schemas, service layer functions, and FastAPI router endpoints based on the provided OpenAPI specification and Gherkin scenarios. It returns a dictionary containing the generated code for schemas.py, service.py, router.py, main.py, and a mode indicator set to "initial".
    def _generate_initial_codebase(
        self,
        target_input: dict[str, Any],
    ) -> dict[str, Any]:
        llm = self._llm or AzureOpenAIJsonClient()

        openapi_spec = target_input.get(
            "openapi_spec",
            {},
        )
        gherkin_scenarios = target_input.get(
            "gherkin_scenarios",
            [],
        )

        schemas_code = self._generate_schemas(
            llm,
            openapi_spec,
        )
        service_code = self._generate_service_layer(
            llm,
            gherkin_scenarios,
            openapi_spec,
        )
        router_code = self._generate_router(
            llm,
            openapi_spec,
            schemas_code,
            service_code,
        )
        main_code = self._build_entrypoint(
            openapi_spec
        )

        return {
            "schemas_code": schemas_code,
            "service_code": service_code,
            "router_code": router_code,
            "main_code": main_code,
            "mode": "initial",
        }

# this method generates Pydantic schemas by invoking the LLM with the provided OpenAPI specification. It returns a string containing the generated code for schemas.py, which includes data models representing the schemas defined in the OpenAPI spec.
    def _generate_schemas(
        self,
        llm: JsonLLM,
        openapi_spec: dict[str, Any],
    ) -> str:
        print(
            "[Coding] Target Architecture Mapping: "
            "generating Pydantic schemas..."
        )
        response = llm.chat_json(
            self._schemas_system_prompt(),
            json.dumps(
                {"openapi_spec": openapi_spec},
                indent=2,
            ),
        )
        return str(
            response.get("schemas_code", "")
        ).strip()

# this method generates the service layer code by invoking the LLM with the provided Gherkin scenarios and OpenAPI specification. It returns a string containing the generated code for service.py, which includes business logic functions implementing the behavior defined in the Gherkin scenarios.
    def _generate_service_layer(
        self,
        llm: JsonLLM,
        gherkin_scenarios: Any,
        openapi_spec: dict[str, Any],
    ) -> str:
        print(
            "[Coding] Service Layer Synthesis: "
            "generating business logic..."
        )
        response = llm.chat_json(
            self._service_system_prompt(),
            json.dumps(
                {
                    "gherkin_scenarios": gherkin_scenarios,
                    "openapi_spec": openapi_spec,
                },
                indent=2,
            ),
        )
        return str(
            response.get("service_code", "")
        ).strip()

# this method generates the router code by invoking the LLM with the provided OpenAPI specification, schemas code, and service layer code. It returns a string containing the generated code for router.py, which includes FastAPI endpoint controllers that delegate business logic to the service layer functions and use the Pydantic schemas for request/response validation.
    def _generate_router(
        self,
        llm: JsonLLM,
        openapi_spec: dict[str, Any],
        schemas_code: str,
        service_code: str,
    ) -> str:
        print(
            "[Coding] API Router Synthesis: "
            "generating FastAPI endpoint controllers..."
        )
        response = llm.chat_json(
            self._router_system_prompt(),
            json.dumps(
                {
                    "openapi_spec": openapi_spec,
                    "schemas_code": schemas_code,
                    "service_code": service_code,
                },
                indent=2,
            ),
        )
        return str(
            response.get("router_code", "")
        ).strip()

# This method builds the entrypoint for the FastAPI application by constructing the necessary import statements and app initialization code based on the OpenAPI specification.
    @staticmethod
    def _build_entrypoint(
        openapi_spec: dict[str, Any],
    ) -> str:
        """Deterministic FastAPI app entrypoint (no LLM call needed).

        Wires schemas.py/service.py/router.py together into a runnable
        application, satisfying the "code should be runnable in target
        architecture" requirement without depending on generated text.
        """
        info = openapi_spec.get("info", {}) if isinstance(openapi_spec, dict) else {}
        title = str(info.get("title") or "Modernized Application")
        version = str(info.get("version") or "1.0.0")
        title_literal = json.dumps(title)
        version_literal = json.dumps(version)

        return (
            "from fastapi import FastAPI\n\n"
            "from .router import router\n\n"
            f"app = FastAPI(title={title_literal}, version={version_literal})\n"
            "app.include_router(router)\n"
        )

    # ------------------------------------------------------------------
    # Self-healing / retry (Agent 5 execution feedback)
    # ------------------------------------------------------------------

# this method handles the self-healing process for the target codebase when execution feedback indicates that the generated code has failed tests or contains errors. It invokes the LLM to analyze the previous generated code, execution stack trace, and failing tests, and generates updated code for schemas.py, service.py, and router.py. The method returns a dictionary containing the updated code and a mode indicator set to "self_healing".
    def _self_heal(
        self,
        target_input: dict[str, Any],
    ) -> dict[str, Any]:
        llm = self._llm or AzureOpenAIJsonClient()

        feedback = target_input.get(
            "execution_feedback"
        ) or {}
        previous = target_input.get(
            "previous_target_output"
        ) or {}

        payload = {
            "openapi_spec": target_input.get(
                "openapi_spec",
                {},
            ),
            "gherkin_scenarios": target_input.get(
                "gherkin_scenarios",
                [],
            ),
            "previous_schemas_code": previous.get(
                "schemas_code",
                "",
            ),
            "previous_service_code": previous.get(
                "service_code",
                "",
            ),
            "previous_router_code": previous.get(
                "router_code",
                "",
            ),
            "execution_stack_trace": (
                feedback.get("stack_trace")
                or feedback.get("execution_stack_trace")
                or feedback
            ),
            "failing_tests": feedback.get(
                "failing_tests",
                [],
            ),
        }

        response = llm.chat_json(
            self._self_heal_system_prompt(),
            json.dumps(
                payload,
                indent=2,
            ),
        )

        main_code = previous.get(
            "main_code"
        ) or self._build_entrypoint(
            target_input.get("openapi_spec", {})
        )

        return {
            "schemas_code": str(
                response.get(
                    "schemas_code",
                    previous.get("schemas_code", ""),
                )
            ).strip(),
            "service_code": str(
                response.get(
                    "service_code",
                    previous.get("service_code", ""),
                )
            ).strip(),
            "router_code": str(
                response.get(
                    "router_code",
                    previous.get("router_code", ""),
                )
            ).strip(),
            "main_code": main_code,
            "mode": "self_healing",
        }

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------

    @staticmethod
    def _schemas_system_prompt() -> str:
        return """
You are Agent 4: Target Code Agent in a legacy-code modernization
pipeline, performing the Target Architecture Mapping step.

Input: an approved OpenAPI 3.0 specification.
Important constraint: you have NOT been given, and must NOT assume,
any original legacy source code. Use only the supplied OpenAPI spec.

Task:
Generate modern Python Pydantic (v2 style, `from pydantic import
BaseModel`) data models representing every schema referenced under
components/schemas and inline request/response bodies in the OpenAPI
spec. Do not invent fields that are not present in the spec.

Rules:
- Output a single, complete, syntactically valid Python module.
- Include all necessary imports at the top of the file.
- Use type hints for every field.
- Do not include markdown code fences.

Return JSON only:
{
  "schemas_code": "string containing the full contents of schemas.py"
}
""".strip()

    @staticmethod
    def _service_system_prompt() -> str:
        return """
You are Agent 4: Target Code Agent in a legacy-code modernization
pipeline, performing the Service Layer Synthesis step.

Input: approved Gherkin feature scenarios and the approved OpenAPI
specification.
Important constraint: you have NOT been given, and must NOT assume,
any original legacy source code. Use only the supplied Gherkin
scenarios and OpenAPI spec as the source of business behavior.

Task:
Convert each Gherkin scenario's Given/When/Then behavior directly into
idiomatic, modern Python service functions implementing that business
logic. Group related functions logically. Do not invent business rules
that are not represented by a Gherkin scenario.

Rules:
- Output a single, complete, syntactically valid Python module.
- Include all necessary imports at the top of the file.
- Use type hints and docstrings referencing the originating scenario.
- Functions should be independent of any web framework (no FastAPI
  imports here); the router layer will call into this module.
- Do not include markdown code fences.

Return JSON only:
{
  "service_code": "string containing the full contents of service.py"
}
""".strip()

    @staticmethod
    def _router_system_prompt() -> str:
        return """
You are Agent 4: Target Code Agent in a legacy-code modernization
pipeline, performing the API Router Synthesis step.

Input: the approved OpenAPI specification, the generated Pydantic
schemas module (schemas_code) and the generated service layer module
(service_code).
Important constraint: you have NOT been given, and must NOT assume,
any original legacy source code.

Task:
Generate a FastAPI `APIRouter` exposing one REST endpoint per path/
operation defined in the OpenAPI spec. Each endpoint must:
- Use the request/response models already defined in schemas_code
  (import them with `from .schemas import ...`).
- Delegate all business logic to the functions already defined in
  service_code (import them with `from .service import ...`).
- Use the HTTP method and status codes declared in the OpenAPI spec.

Rules:
- Output a single, complete, syntactically valid Python module.
- Include all necessary imports at the top of the file, including
  `from fastapi import APIRouter` and a module-level
  `router = APIRouter()`.
- Do not redefine schemas or business logic already present in
  schemas_code/service_code; import and reuse them.
- Do not include markdown code fences.

Return JSON only:
{
  "router_code": "string containing the full contents of router.py"
}
""".strip()

    @staticmethod
    def _self_heal_system_prompt() -> str:
        return """
You are Agent 4: Target Code Agent running in a self-healing retry
loop, triggered because the Testing Agent's pytest execution failed.

Patch the previous generated codebase instead of blindly rewriting it.

Use:
- previous_schemas_code
- previous_service_code
- previous_router_code
- execution_stack_trace
- failing_tests
- openapi_spec / gherkin_scenarios (source of truth for intended
  behavior)

Rules:
- Preserve everything that is already correct.
- Fix only what the stack trace / failing tests indicate is broken.
- Do not remove functionality that is unrelated to the failure.
- Do not invent business behavior or API fields not present in the
  OpenAPI spec / Gherkin scenarios.
- Return the complete updated contents of each of the three files
  (not a diff/patch).
- Do not include markdown code fences.

Return JSON only:
{
  "schemas_code": "string containing the full updated schemas.py",
  "service_code": "string containing the full updated service.py",
  "router_code": "string containing the full updated router.py"
}
""".strip()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_python_syntax(
        result: dict[str, Any],
    ) -> dict[str, Any]:
        files = {
            "schemas.py": result.get("schemas_code", ""),
            "service.py": result.get("service_code", ""),
            "router.py": result.get("router_code", ""),
            "main.py": result.get("main_code", ""),
        }

        errors = []
        for filename, code in files.items():
            if not str(code).strip():
                errors.append(
                    f"{filename}: no code was generated."
                )
                continue
            try:
                pyast.parse(code, filename=filename)
            except SyntaxError as exc:
                errors.append(
                    f"{filename}: {exc.msg} "
                    f"(line {exc.lineno}, col {exc.offset})"
                )

        if errors:
            return {
                "valid": False,
                "message": "; ".join(errors),
            }

        return {
            "valid": True,
            "message": "All generated modules passed Python syntax validation.",
        }

    # ------------------------------------------------------------------
    # Target codebase persistence
    # ------------------------------------------------------------------

    def _write_target_codebase(
        self,
        target_output: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Persist the generated modern target codebase to disk.

        Output:
            outputs/target_code/
                schemas.py
                service.py
                router.py
                main.py
                __init__.py
        """
        target_code_dir = (
            self.output_dir
            / "target_code"
        )
        target_code_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        init_path = target_code_dir / "__init__.py"
        if not init_path.exists():
            init_path.write_text("", encoding="utf-8")

        file_map = {
            "schemas.py": target_output.get("schemas_code", ""),
            "service.py": target_output.get("service_code", ""),
            "router.py": target_output.get("router_code", ""),
            "main.py": target_output.get("main_code", ""),
        }

        written = {}
        for filename, code in file_map.items():
            path = target_code_dir / filename
            path.write_text(
                self._ensure_trailing_newline(str(code)),
                encoding="utf-8",
            )
            written[filename.replace(".py", "_py")] = str(path)

        written["target_code_directory"] = str(
            target_code_dir
        )

        return written

    @staticmethod
    def _ensure_trailing_newline(text: str) -> str:
        text = text.strip("\n")
        return (text + "\n") if text else ""

    @staticmethod
    def _safe_filename(value: str) -> str:
        cleaned = re.sub(
            r"[^A-Za-z0-9._-]+",
            "_",
            value.strip(),
        )
        return cleaned[:120] or "module"


__all__ = [
    "CodingAgent",
    "AzureOpenAIJsonClient",
    "JsonLLM",
]
