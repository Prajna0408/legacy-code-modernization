from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Protocol

from app import state

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore

try:
    from openai import AzureOpenAI
except ImportError:  # pragma: no cover
    AzureOpenAI = None  # type: ignore

try:
    from openapi_spec_validator import validate
except ImportError:  # pragma: no cover
    validate = None  # type: ignore

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

from .state import PipelineState

# this protocol defines the interface for a JSON-based LLM client that can send system and user prompts and receive a JSON response. It is used by the Documentation Agent to interact with the LLM for generating and refining documentation.
class JsonLLM(Protocol):
    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        ...

# this class is an adapter for the Azure OpenAI API, allowing the Documentation Agent to send prompts and receive structured JSON responses. It handles configuration via environment variables, constructs the request, and validates the response format.
class AzureOpenAIJsonClient:
    """Small Azure OpenAI adapter used by the Documentation Agent."""

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
# this method sends a chat request to the Azure OpenAI API with the provided system and user prompts, expecting a JSON response. It handles the request, checks for valid JSON, and returns the parsed result as a dictionary.
    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        print(
            "[Documentation] Sending Azure OpenAI request..."
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
            "[Documentation] Azure OpenAI response received."
        )
        return result


class DocumentationAgent:
    """
    Agent 2: Documentation Agent.

    Runtime flow:
        splitting_output
            +
        optional evaluation_output
            ↓
        documentation_input
            ↓
        initial generation OR targeted refinement
            ↓
        OpenAPI validation
            ↓
        documentation_output in PipelineState
            ↓
        human-facing documentation artifacts on disk

    BAU-friendly files written under output_dir:
        documentation/
            documentation_summary.md
            gherkin/
                <module>.feature
            openapi/
                openapi.yaml
    """

    STAGE = "documentation_agent"

# the constructor initializes the Documentation Agent with an optional JSON-based LLM client and an output directory for storing generated documentation artifacts. If no LLM client is provided, it can default to using the Azure OpenAI adapter.
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

# the run method orchestrates the documentation generation process. It reads the splitting output and optional evaluation feedback from the pipeline state, builds the documentation input, processes it to generate or refine documentation, validates the OpenAPI specification, and writes the results back to the pipeline state.
    def run(
        self,
        state: PipelineState,
    ) -> PipelineState:
        splitting_output = state.read_artifact(
            "splitting_output"
        )

        evaluation_feedback = None
        if state.has_artifact(
            "evaluation_output"
        ):
            evaluation_feedback = state.read_artifact(
                "evaluation_output"
            )

        documentation_input = (
            self.build_documentation_input(
                splitting_output,
                evaluation_feedback,
            )
        )

        if state.has_artifact("documentation_input"):
            state.replace_artifact(
                "documentation_input",
                documentation_input,
                stage=self.STAGE,
            )
        else:
            state.write_artifact(
                "documentation_input",
                documentation_input,
                stage=self.STAGE,
            )

        documentation_output = self.process(
            documentation_input
        )

        if state.has_artifact("documentation_output"):
            state.replace_artifact(
            "documentation_output",
            documentation_output,
            stage=self.STAGE,
        )
        else:
            state.write_artifact(
            "documentation_output",
            documentation_output,
            stage=self.STAGE,
        )

        return state

    # ------------------------------------------------------------------
    # Compact Agent-2 input
    # ------------------------------------------------------------------

# this static method constructs the input for the Documentation Agent by extracting relevant information from the splitting output and optional evaluation feedback. It organizes the data into a structured dictionary containing module details and any feedback for refinement.
    @staticmethod
    def build_documentation_input(
        splitting_output: dict[str, Any],
        evaluation_feedback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        modules = []

        for module in splitting_output.get(
            "modules",
            [],
        ):
            if not isinstance(module, dict):
                continue

            modules.append(
                {
                    "module_name": module.get(
                        "module_name",
                        "",
                    ),
                    "domain_context": module.get(
                        "domain_context",
                        "",
                    ),
                    "input_contract": module.get(
                        "input_contract",
                        {},
                    ),
                    "output_contract": module.get(
                        "output_contract",
                        {},
                    ),
                    "business_rules": module.get(
                        "business_rules",
                        [],
                    ),
                    "source_slices": module.get(
                        "source_slices",
                        [],
                    ),
                    "source_files": module.get(
                        "source_files",
                        [],
                    ),
                }
            )

        return {
            "modules": modules,
            "evaluation_feedback": (
                evaluation_feedback
                if isinstance(
                    evaluation_feedback,
                    dict,
                )
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------

# this method determines whether to perform an initial documentation generation or a targeted refinement based on the presence of evaluation feedback. It processes the input, validates the generated OpenAPI specification, and writes the resulting artifacts to disk.
    def process(
        self,
        documentation_input: dict[str, Any],
    ) -> dict[str, Any]:
        evaluation_feedback = documentation_input.get(
            "evaluation_feedback"
        )

        is_retry = bool(
            evaluation_feedback
        )

        if is_retry:
            print(
                "[Documentation] Evaluation feedback found. "
                "Running targeted refinement."
            )
            result = (
                self._refine_previous_documentation(
                    documentation_input
                )
            )
        else:
            print(
                "[Documentation] No evaluation feedback. "
                "Running initial documentation generation."
            )
            result = (
                self._generate_initial_documentation(
                    documentation_input
                )
            )

        openapi_spec = result.get(
            "openapi_spec",
            {},
        )

        validation = self._validate_openapi(
            openapi_spec
        )
        result["openapi_validation"] = validation
        result["modules"] = documentation_input.get(
            "modules",
            [],
        )

        if not validation["valid"]:
            raise ValueError(
                "Generated OpenAPI specification failed validation: "
                + validation["message"]
            )

        files_written = self._write_bau_artifacts(
            result
        )
        result["artifacts"] = files_written

        return result

    # ------------------------------------------------------------------
    # Initial generation
    # ------------------------------------------------------------------

# This method generates the initial documentation for the given modules. It uses the LLM to produce Gherkin scenarios and an OpenAPI specification based on the provided module contracts. The output is structured as a dictionary containing the generated documentation and a mode indicator.
    def _generate_initial_documentation(
        self,
        documentation_input: dict[str, Any],
    ) -> dict[str, Any]:
        llm = self._llm or AzureOpenAIJsonClient()

        response = llm.chat_json(
            self._initial_system_prompt(),
            json.dumps(
                {
                    "modules": documentation_input.get(
                        "modules",
                        [],
                    )
                },
                indent=2,
            ),
        )

        return {
            "gherkin_scenarios": response.get(
                "gherkin_scenarios",
                [],
            ),
            "openapi_spec": response.get(
                "openapi_spec",
                {},
            ),
            "technical_documentation": response.get(
                "technical_documentation",
                "",
            ),
            "mode": "initial",
        }

    # ------------------------------------------------------------------
    # Targeted refinement / retry
    # ------------------------------------------------------------------

# This method refines the previous documentation based on evaluation feedback. It uses the LLM to update Gherkin scenarios and the OpenAPI specification. The method constructs a payload containing the previous documentation, unmapped branches, code snippets, and remediation instructions, and sends it to the LLM for refinement. The output is structured as a dictionary containing the refined documentation and a mode indicator.
    def _refine_previous_documentation(
        self,
        documentation_input: dict[str, Any],
    ) -> dict[str, Any]:
        llm = self._llm or AzureOpenAIJsonClient()

        feedback = (
            documentation_input.get(
                "evaluation_feedback",
                {},
            )
        )

        previous_gherkin = feedback.get(
            "previous_gherkin_scenarios",
            [],
        )
        previous_openapi = feedback.get(
            "previous_openapi_spec",
            {},
        )

        payload = {
            "modules": documentation_input.get(
                "modules",
                [],
            ),
            "previous_gherkin_scenarios": previous_gherkin,
            "previous_openapi_spec": previous_openapi,
            "unmapped_branches": feedback.get(
                "unmapped_branches",
                [],
            ),
            "code_snippets": feedback.get(
                "code_snippets",
                [],
            ),
            "remediation_instructions": feedback.get(
                "remediation_instructions",
                [],
            ),
        }

        response = llm.chat_json(
            self._refinement_system_prompt(),
            json.dumps(
                payload,
                indent=2,
            ),
        )

        return {
            "gherkin_scenarios": response.get(
                "gherkin_scenarios",
                previous_gherkin,
            ),
            "openapi_spec": response.get(
                "openapi_spec",
                previous_openapi,
            ),
            "technical_documentation": response.get(
                "technical_documentation",
                feedback.get("previous_technical_documentation", ""),
            ),
            "mode": "refinement",
        }

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------

# this static method returns the initial system prompt for the Documentation Agent, which instructs the LLM to generate Gherkin feature scenarios and an OpenAPI 3.0 REST interface specification based on the provided module contracts. The prompt includes rules for both Gherkin and OpenAPI generation, emphasizing technology-agnostic documentation and avoiding legacy implementation details.
    @staticmethod
    def _initial_system_prompt() -> str:
        return """
You are Agent 2: Documentation Agent in a legacy-code modernization pipeline.
Strictly follow the given instructions and rules. 

Purpose:
Translate the decomposed legacy source-code contracts into professional,
human-readable software documentation. you are generating 1.purpose and scope, 2.system overview 
at the top of the documentation.md without proper format and then again generating the 
1.purpose and scope, 2.system overview with proper format later so remove the 
1.purpose and scope, 2.system overview which you've generated at the top of the documentation.md and keep the 1.purpose and scope, 2.system overview which is generated with proper format.
In the beginning, 1.purpose and scope, 2.system overview are 
coming in different style and color from rest of the documentation. keep everything in same style and color.
follow the same format for purpose and scope and system overview as rest of the documentation.

Produce three outputs:

1. Gherkin feature scenarios.
2. OpenAPI 3.0 REST interface specification.
3. Professional technical documentation for engineers and maintainers.

Technical documentation rules:
- Explain the purpose and responsibility of every logical module.
- Cover supported source files, source-code traceability, inputs, outputs,
  processing flow, business rules, validations, calculations, decision
  points, dependencies/interactions, error paths, and relevant legacy
  implementation characteristics.
- Use only information supported by the supplied module contracts and
  source slices.
- Clearly distinguish facts from inference.
- Never invent systems, tables, files, APIs, queues, algorithms, fields,
  business rules, or dependencies.
- Do not copy large blocks of legacy source code; summarize it and use
  concise source references.
- Write technical documentation as an engineering handover document,
  not as a list of Gherkin scenarios or an OpenAPI specification.

Gherkin rules:
- Express business behavior, not implementation details.
- Use clear Feature and Scenario names.
- Use GIVEN, WHEN and THEN semantics.
- Preserve supported branches and business rules.
- Do not invent behavior.

OpenAPI rules:
- Generate a valid OpenAPI 3.0.x document.
- Create paths only when supported by the supplied module contracts.
- Define request and response schemas from the supplied contracts.
- Use HTTP 200, 400 and 500 where applicable.
- Add path/query parameters only when supported by the input.
- Do not invent fields.

Return JSON only:
{
  "gherkin_scenarios": [...],
  "openapi_spec": {
    "openapi": "3.0.3",
    "info": {
      "title": "string",
      "version": "1.0.0"
    },
    "paths": {}
  },
  "technical_documentation": "Markdown content only; do not include a top-level # title."
}
""".strip()

    @staticmethod
    def _refinement_system_prompt() -> str:
        return """
You are Agent 2: Documentation Agent running in a targeted retry loop.

A Quality Gate / Evaluation Agent has identified documentation gaps.

Patch the previous approved documentation instead of blindly rewriting it.

Use:
- previous_gherkin_scenarios
- previous_openapi_spec
- previous_technical_documentation
- unmapped_branches
- code_snippets
- remediation_instructions
- current module contracts and source slices

Rules:
- Preserve previously correct scenarios and API definitions.
- Add or refine only what is needed to address the supplied feedback.
- Preserve supported source-code facts and technical traceability.
- Update technical documentation only where feedback or current source
  evidence requires it.
- Never invent business behavior, implementation details, dependencies, or
  API fields.
- Return complete updated Gherkin, OpenAPI, and technical documentation.

Return JSON only:
{
  "gherkin_scenarios": [...],
  "openapi_spec": {...},
  "technical_documentation": "Markdown content only; do not include a top-level # title."
}
""".strip()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

# this static method validates the generated OpenAPI specification. It checks that the specification is a JSON object, declares an OpenAPI 3.0.x version, and contains the required 'info' and 'paths' objects. If the openapi_spec_validator package is available, it also performs a full validation of the specification. The method returns a dictionary indicating whether the specification is valid and any associated messages.
    @staticmethod
    def _validate_openapi(
        openapi_spec: Any,
    ) -> dict[str, Any]:
        if not isinstance(
            openapi_spec,
            dict,
        ):
            return {
                "valid": False,
                "message": (
                    "OpenAPI output is not a JSON object."
                ),
            }

        if not str(
            openapi_spec.get(
                "openapi",
                "",
            )
        ).startswith("3.0"):
            return {
                "valid": False,
                "message": (
                    "OpenAPI document must declare "
                    "an OpenAPI 3.0.x version."
                ),
            }

        if not isinstance(
            openapi_spec.get(
                "info"
            ),
            dict,
        ):
            return {
                "valid": False,
                "message": (
                    "OpenAPI 'info' object is missing."
                ),
            }

        if not isinstance(
            openapi_spec.get(
                "paths"
            ),
            dict,
        ):
            return {
                "valid": False,
                "message": (
                    "OpenAPI 'paths' object is missing."
                ),
            }

        if validate is not None:
            try:
                validate(
                    openapi_spec
                )
            except Exception as exc:
                return {
                    "valid": False,
                    "message": str(exc),
                }

        return {
            "valid": True,
            "message": (
                "OpenAPI specification passed validation."
            ),
        }

    # ------------------------------------------------------------------
    # BAU artifact generation
    # ------------------------------------------------------------------

# this method writes the generated documentation artifacts to disk in a structured format. It creates directories for Gherkin feature files and OpenAPI specifications, writes the Gherkin scenarios to .feature files, saves the OpenAPI specification in both JSON and YAML formats, and generates a summary markdown file. The method returns a dictionary containing paths to the written artifacts.
    def _write_bau_artifacts(
        self,
        documentation_output: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Persist documentation in human/team-friendly formats.

        Output:
            outputs/documentation/
                documentation_summary.md
                gherkin/
                    <feature>.feature
                openapi/
                    openapi.yaml
                    openapi.json
        """
        documentation_dir = (
            self.output_dir
            / "documentation"
        )
        gherkin_dir = (
            documentation_dir
            / "gherkin"
        )
        openapi_dir = (
            documentation_dir
            / "openapi"
        )

        gherkin_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        openapi_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        gherkin_groups = documentation_output.get(
            "gherkin_scenarios",
            [],
        )

        feature_files = []

        for index, feature_group in enumerate(
            gherkin_groups,
            start=1,
        ):
            feature_name = str(
                feature_group.get(
                    "feature",
                    f"Feature_{index}",
                )
            )

            filename = (
                self._safe_filename(
                    feature_name
                )
                + ".feature"
            )

            path = (
                gherkin_dir
                / filename
            )

            path.write_text(
                self._gherkin_text(
                    feature_name,
                    feature_group.get(
                        "scenarios",
                        [],
                    ),
                ),
                encoding="utf-8",
            )

            feature_files.append(
                str(
                    path
                )
            )

        openapi_spec = documentation_output.get(
            "openapi_spec",
            {},
        )

        openapi_json_path = (
            openapi_dir
            / "openapi.json"
        )
        openapi_json_path.write_text(
            json.dumps(
                openapi_spec,
                indent=2,
            ),
            encoding="utf-8",
        )

        openapi_yaml_path = (
            openapi_dir
            / "openapi.yaml"
        )

        if yaml is not None:
            openapi_yaml_path.write_text(
                yaml.safe_dump(
                    openapi_spec,
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
        else:
            # Keep a usable fallback rather than silently dropping
            # the YAML artifact.
            openapi_yaml_path.write_text(
                (
                    "# PyYAML is not installed.\n"
                    "# Install with: pip install pyyaml\n\n"
                    + json.dumps(
                        openapi_spec,
                        indent=2,
                    )
                ),
                encoding="utf-8",
            )

        summary_path = (
            documentation_dir
            / "documentation_summary.md"
        )
        summary_path.write_text(
            self._markdown_summary(
                documentation_output,
                feature_files,
                openapi_yaml_path,
            ),
            encoding="utf-8",
        )

        return {
            "documentation_directory": str(
                documentation_dir
            ),
            "summary_markdown": str(
                summary_path
            ),
            "gherkin_feature_files": feature_files,
            "openapi_yaml": str(
                openapi_yaml_path
            ),
            "openapi_json": str(
                openapi_json_path
            ),
        }


# this static method sanitizes a string to create a safe filename by replacing non-alphanumeric characters with underscores and truncating the result to a maximum of 120 characters. If the cleaned string is empty, it defaults to "feature".
    @staticmethod
    def _safe_filename(
        value: str,
    ) -> str:
        cleaned = re.sub(
            r"[^A-Za-z0-9._-]+",
            "_",
            value.strip(),
        )
        return (
            cleaned[:120]
            or "feature"
        )


# this static method generates Gherkin text from a feature name and a list of scenarios. It constructs the Gherkin syntax with proper indentation and formatting, including the Feature and Scenario headers, as well as the Given, When, and Then steps for each scenario. The resulting Gherkin text is returned as a string.
    @staticmethod
    def _gherkin_text(
        feature_name: str,
        scenarios: list[dict[str, Any]],
    ) -> str:
        lines = [
            "Feature: "
            + feature_name,
            "",
        ]

        for scenario in scenarios:
            lines.append(
                "  Scenario: "
                + str(
                    scenario.get(
                        "name",
                        "Unnamed scenario",
                    )
                )
            )

            for step in scenario.get(
                "given",
                [],
            ):
                lines.append(
                    "    Given "
                    + str(step)
                )

            for step in scenario.get(
                "when",
                [],
            ):
                lines.append(
                    "    When "
                    + str(step)
                )

            for step in scenario.get(
                "then",
                [],
            ):
                lines.append(
                    "    Then "
                    + str(step)
                )

            lines.append("")

        return (
            "\n".join(
                lines
            ).rstrip()
            + "\n"
        )


# this static method generates a markdown summary of the generated documentation, including the purpose, Gherkin features, OpenAPI validation status, and a list of generated files. It formats the information into a structured markdown document and returns it as a string.
    @staticmethod
    def _markdown_summary(
        output: dict[str, Any],
        feature_files: list[str],
        openapi_yaml_path: Path,
    ) -> str:
        """
        Build the human-readable engineering document.

        Gherkin and OpenAPI stay in their own artifacts. This Markdown is
        intentionally focused on helping engineers understand the existing
        legacy implementation and its traceability.
        """
        technical_doc = str(
            output.get("technical_documentation", "") or ""
        ).strip()

        # Keep internal slice identifiers out of the human-facing summary only.
        # This does not change Gherkin, OpenAPI, pipeline state, or agent inputs.
        technical_doc = "\n".join(
            line for line in technical_doc.splitlines()
            if not re.search(r"\bslice[_ -]?ids?\b", line, flags=re.IGNORECASE)
        ).strip()

        # Avoid duplicate document title when the model returns one.
        technical_doc = re.sub(
            r"^\s*#\s+.+?\n+",
            "",
            technical_doc,
            count=1,
        ).strip()

        modules = output.get("modules", [])
        if not isinstance(modules, list):
            modules = []

        def to_text(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, str):
                return value.strip()
            try:
                return json.dumps(
                    value,
                    indent=2,
                    ensure_ascii=False,
                )
            except TypeError:
                return str(value)

        def as_list(value: Any) -> list[Any]:
            if value is None:
                return []
            return value if isinstance(value, list) else [value]

        def add_contract(
            result: list[str],
            title: str,
            contract: Any,
        ) -> None:
            result.extend([f"### {title}", ""])
            if not contract:
                result.extend(
                    ["No contract details were provided.", ""]
                )
                return

            if isinstance(contract, dict):
                for key, value in contract.items():
                    label = (
                        str(key)
                        .replace("_", " ")
                        .strip()
                        .title()
                    )
                    value_text = to_text(value) or "Not specified."
                    result.append(
                        f"- **{label}:** {value_text}"
                    )
            else:
                for item in as_list(contract):
                    result.append(
                        f"- {to_text(item)}"
                    )
            result.append("")

        lines = [
            "# Legacy System Technical Documentation",
            "",
            "## 1. Purpose and Scope",
            "",
            "This document provides the human-readable engineering view of "
            "the legacy application derived from the source-code "
            "decomposition performed upstream in the modernization pipeline.",
            "",
            "It is intended for developers, technical leads, architects, "
            "testers, and maintainers who need to understand the existing "
            "system before implementing the target solution.",
            "",
            "Gherkin and OpenAPI are intentionally kept as separate artifacts; "
            "this document focuses on technical understanding and traceability.",
            "",
            "## 2. System Overview",
            "",
        ]

        if technical_doc:
            lines.extend([technical_doc, ""])
        else:
            lines.extend(
                [
                    "The Documentation Agent did not return a narrative "
                    "technical summary. The structured module documentation "
                    "below is generated directly from the available pipeline "
                    "data.",
                    "",
                ]
            )

        lines.extend(
            [
                "## 3. Logical Module Inventory",
                "",
            ]
        )

        if modules:
            lines.extend(
                [
                    "| Module | Source File(s) | Responsibility |",
                    "|---|---|---|",
                ]
            )
            for index, module in enumerate(modules, start=1):
                if not isinstance(module, dict):
                    continue

                name = (
                    to_text(module.get("module_name"))
                    or f"Module {index}"
                )
                files = [
                    to_text(item)
                    for item in as_list(
                        module.get("source_files")
                    )
                    if to_text(item)
                ]
                responsibility = (
                    to_text(module.get("domain_context"))
                    or "Not specified."
                )

                lines.append(
                    "| "
                    + name.replace("|", "\\|")
                    + " | "
                    + (
                        ", ".join(
                            f"`{item}`"
                            for item in files
                        )
                        or "Not specified."
                    )
                    + " | "
                    + responsibility.replace("|", "\\|")
                    + " |"
                )
            lines.append("")
        else:
            lines.extend(
                [
                    "No logical module information was provided.",
                    "",
                ]
            )

        lines.extend(
            [
                "## 4. Detailed Module Documentation",
                "",
            ]
        )

        for index, module in enumerate(modules, start=1):
            if not isinstance(module, dict):
                continue

            name = (
                to_text(module.get("module_name"))
                or f"Module {index}"
            )
            domain = (
                to_text(module.get("domain_context"))
                or "Not specified."
            )
            source_files = [
                to_text(item)
                for item in as_list(
                    module.get("source_files")
                )
                if to_text(item)
            ]
            business_rules = as_list(
                module.get("business_rules")
            )
            source_slices = as_list(
                module.get("source_slices")
            )

            lines.extend(
                [
                    f"### 4.{index} {name}",
                    "",
                    "**Responsibility / Domain Context**",
                    "",
                    domain,
                    "",
                    "**Legacy Source Files**",
                    "",
                ]
            )

            if source_files:
                lines.extend(
                    f"- `{item}`"
                    for item in source_files
                )
            else:
                lines.append(
                    "- No source-file names were provided."
                )
            lines.append("")

            add_contract(
                lines,
                "Input Contract",
                module.get("input_contract"),
            )
            add_contract(
                lines,
                "Output Contract",
                module.get("output_contract"),
            )

            lines.extend(
                [
                    "### Business Rules",
                    "",
                ]
            )
            if business_rules:
                for rule in business_rules:
                    rule_text = to_text(rule)
                    if rule_text:
                        lines.append(f"- {rule_text}")
            else:
                lines.append(
                    "No explicit business rules were provided."
                )
            lines.append("")

        lines.extend(
            [
                "## 5. End-to-End Processing Flow",
                "",
                "The legacy modernization flow represented by this stage is:",
                "",
                "1. Legacy source files are parsed/analyzed upstream.",
                "2. The Splitting Agent decomposes the source into logical "
                "modules and source slices.",
                "3. The Documentation Agent consumes module contracts, "
                "business rules, source references, and evaluation feedback "
                "when a retry is required.",
                "4. Gherkin scenarios are produced as behavior-oriented "
                "verification specifications.",
                "5. An OpenAPI 3.0 interface is produced from supported "
                "module contracts and validated.",
                "6. This document provides the human-readable engineering "
                "explanation.",
                "",
                "## 6. Interface Summary",
                "",
            ]
        )

        openapi_spec = output.get("openapi_spec", {})
        if isinstance(openapi_spec, dict):
            info = openapi_spec.get("info", {})
            if isinstance(info, dict):
                if info.get("title"):
                    lines.append(
                        f"- **API Title:** {to_text(info.get('title'))}"
                    )
                if info.get("version"):
                    lines.append(
                        f"- **API Version:** {to_text(info.get('version'))}"
                    )

            paths = openapi_spec.get("paths", {})
            if isinstance(paths, dict) and paths:
                lines.extend(
                    [
                        "",
                        "| Method | Path | Operation |",
                        "|---|---|---|",
                    ]
                )
                for path, item in paths.items():
                    if not isinstance(item, dict):
                        continue
                    for method, operation in item.items():
                        method_name = str(method).lower()
                        if method_name not in {
                            "get", "post", "put", "patch",
                            "delete", "head", "options", "trace",
                        }:
                            continue
                        operation_name = ""
                        if isinstance(operation, dict):
                            operation_name = to_text(
                                operation.get("summary")
                                or operation.get("operationId")
                            )
                        lines.append(
                            "| "
                            + method_name.upper()
                            + " | "
                            + str(path).replace("|", "\\|")
                            + " | "
                            + (
                                operation_name.replace("|", "\\|")
                                if operation_name
                                else "Not specified."
                            )
                            + " |"
                        )
            else:
                lines.append("No OpenAPI paths were generated.")
        else:
            lines.append(
                "No OpenAPI interface summary is available."
            )

        validation = output.get(
            "openapi_validation",
            {},
        )
        lines.extend(
            [
                "",
                f"**OpenAPI validation status:** "
                f"{validation.get('valid', False)}",
                "",
                "The complete OpenAPI specification remains in the separate "
                f"`{openapi_yaml_path.name}` artifact.",
                "",
                "## 7. Related Verification Artifacts",
                "",
                "Detailed Gherkin scenario text is deliberately not embedded "
                "here. The generated feature files remain the dedicated "
                "behavior-specification artifacts.",
                "",
            ]
        )

        if feature_files:
            lines.extend(
                f"- `{Path(path).name}`"
                for path in feature_files
            )
        else:
            lines.append(
                "- No Gherkin feature files were generated."
            )

        lines.extend(
            [
                "",
                "## 8. Modernization Notes",
                "",
                "Use the source traceability, module contracts, and business "
                "rules as evidence when implementing the target system. "
                "Behavior that is not represented in the decomposed input "
                "should be verified against the original legacy source "
                "before it is carried forward.",
                "",
                "This document is descriptive technical documentation. "
                "Gherkin remains the behavior specification and OpenAPI "
                "remains the service-interface specification.",
                "",
            ]
        )

        return "\n".join(lines)



__all__ = [
    "DocumentationAgent",
    "AzureOpenAIJsonClient",
    "JsonLLM",
]
