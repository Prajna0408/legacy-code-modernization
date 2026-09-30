from __future__ import annotations

import ast as pyast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
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


# this protocol defines the interface for a JSON-based LLM client, which is used by the Testing Agent to interact with an LLM (e.g., Azure OpenAI) for generating test code from Gherkin scenarios. The chat_json method takes a system prompt and a user prompt as input and returns a dictionary representing the JSON response from the LLM.
class JsonLLM(Protocol):
    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        ...

# this class is a small adapter for interacting with Azure OpenAI's API, specifically for generating JSON responses. It reads configuration from environment variables (endpoint, API key, deployment name, etc.) and provides a method chat_json to send prompts to the LLM and receive structured JSON output. It handles errors such as missing configuration or invalid JSON responses.
class AzureOpenAIJsonClient:
    """Small Azure OpenAI adapter used by the Testing Agent.

    Mirrors the adapter used by the other agents so every LLM-backed agent
    in the pipeline resolves credentials identically from the environment
    (the user's own .env file, never hard-coded keys).
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

#this method sends a chat request to the Azure OpenAI API with the provided system and user prompts, expecting a JSON response. It handles the request, parses the response, and returns it as a dictionary. If the response is not valid JSON or not a dictionary, it raises a RuntimeError.
    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        print(
            "[Testing] Sending Azure OpenAI request..."
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
            "[Testing] Azure OpenAI response received."
        )
        return result


class TestingAgent:
    """
    Agent 5: Testing Agent.

    Built strictly from Testing agent Logic and the sequence diagram
    (SequenceDiagram3):

        CentralState ->> Agent5: Fetch Gherkin Scenarios & Target Python Code
        Agent5 ->> Agent5: Generate pytest Suite & Execute in Sandbox
        alt pytest Executions Fail (Tests Failed)
            Agent5 ->> CentralState: Append Execution Stack Trace
            CentralState ->> Agent4: Trigger Self-Healing Loop
            Agent4 ->> Agent4: Fix Python Logic using Stack Trace
            Agent4 ->> CentralState: Save Updated Target Code
        else pytest Executions Pass (100% Parity Verified)
            Agent5 ->> CentralState: Mark Pipeline State as VERIFIED
        end
        CentralState ->> User/System: Deliver Verified Modern Target
            Application & Test Suite

    Input:
        - Gherkin Scenarios (from Agent 2 / documentation_output)
        - Generated Target Python Source Code (from Agent 4 / target_output)

    Internal processing logic:
        1. Test Suite Generation:
               Translates Gherkin GIVEN-WHEN-THEN scenarios into
               executable pytest functions.
        2. Sandboxed Test Execution:
               Spawns an isolated subprocess in a disposable temp
               directory and executes pytest against the generated
               target code.

        3. Parity Verification & Self-Healing Loop:
               - Tests Pass (100%)  -> VERIFIED, pipeline can terminate.
               - Tests Fail         -> exact stderr stack traces are
                 captured into `testing_output.feedback` for the
                 Feedback Edge back to Agent 4.

    Output:
        - Executable pytest file(s)
        - Test execution report (JUnit XML + JSON + Markdown)
        - Final parity verification status (`testing_output` artifact)

    Important constraint (mirrors Agent 4): this agent's test-generation
    step reads only the approved Gherkin scenarios and the already
    generated target Python code -- it never reads parser_output or
    splitting_output.
    """

    STAGE = "testing_agent"

    def __init__(
        self,
        llm: JsonLLM | None = None,
        output_dir: str | Path = "outputs",
        sandbox_timeout_seconds: float = 120.0,
    ) -> None:
        self._llm = llm
        self.output_dir = Path(output_dir)
        self.sandbox_timeout_seconds = sandbox_timeout_seconds

    # ------------------------------------------------------------------
    # Shared-state entry point
    # ------------------------------------------------------------------

# this method is the main entry point for the Testing Agent. It takes the current pipeline state, checks for the presence of the target output artifact (generated code from Agent 4), and reads both the target output and documentation output (Gherkin scenarios). It then builds the testing input, processes it to generate and execute tests, and writes the testing output back to the pipeline state. Finally, it returns the updated pipeline state.
    def run(
        self,
        state: PipelineState,
    ) -> PipelineState:
        if not state.has_artifact("target_output"):
            raise ValueError(
                "Agent 5 (Testing Agent) requires target_output "
                "(Agent 4's generated code) before it can run."
            )

        target_output = state.read_artifact(
            "target_output"
        )
        documentation_output = state.read_artifact(
            "documentation_output"
        )

        testing_input = self.build_testing_input(
            documentation_output.get("gherkin_scenarios", []),
            target_output,
        )

        testing_output = self.process(
            testing_input
        )

        if state.has_artifact("testing_output"):
            state.replace_artifact(
                "testing_output",
                testing_output,
                stage=self.STAGE,
            )
        else:
            state.write_artifact(
                "testing_output",
                testing_output,
                stage=self.STAGE,
            )

        return state

    # ------------------------------------------------------------------
    # Compact Agent-5 input
    # ------------------------------------------------------------------

# this static method builds a compact input dictionary for the Testing Agent, containing the Gherkin scenarios and the generated target code (schemas, service, router, main). It extracts the relevant code from the target output artifact and returns a dictionary that can be used as input for the Testing Agent's processing logic.
    @staticmethod
    def build_testing_input(
        gherkin_scenarios: Any,
        target_output: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "gherkin_scenarios": gherkin_scenarios,
            "schemas_code": target_output.get("schemas_code", ""),
            "service_code": target_output.get("service_code", ""),
            "router_code": target_output.get("router_code", ""),
            "main_code": target_output.get("main_code", ""),
        }

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------

# this method orchestrates the Testing Agent's main processing logic. It generates a pytest test suite from the provided testing input, validates the generated code's syntax, executes the tests in a sandboxed environment, and builds a result dictionary containing the test execution summary and any artifacts produced. It returns this result dictionary for further processing or storage in the pipeline state.
    def process(
        self,
        testing_input: dict[str, Any],
    ) -> dict[str, Any]:
        test_code = self._generate_test_suite(
            testing_input
        )

        syntax_validation = self._validate_python_syntax(
            test_code
        )

        if not syntax_validation["valid"]:
            print(
                "[Testing] Generated test suite failed syntax "
                "validation: " + syntax_validation["message"]
            )
            execution_result = {
                "verified": False,
                "summary": {
                    "total_tests": 0,
                    "passed": 0,
                    "failed": 0,
                    "errors": 0,
                    "pass_rate": 0.0,
                },
                "test_results": [],
                "execution_error": (
                    "Generated pytest suite is not valid Python: "
                    + syntax_validation["message"]
                ),
                "stdout": "",
                "stderr": "",
                "junit_xml_path": None,
            }
        else:
            execution_result = self._execute_in_sandbox(
                testing_input,
                test_code,
            )

        result = self._build_result(
            execution_result,
            test_code,
        )

        files_written = self._write_bau_artifacts(
            testing_input,
            test_code,
            execution_result,
            result,
        )
        result["artifacts"] = files_written

        return result

    # ------------------------------------------------------------------
    # Step 1: Test Suite Generation
    # ------------------------------------------------------------------

#this method generates the pytest test suite by invoking the LLM with the provided Gherkin scenarios and the generated target code (schemas, service, router). It constructs a system prompt and user prompt for the LLM, sends them to the LLM via the chat_json method, and retrieves the generated test code. The method returns a string containing the full contents of the pytest test file.
    def _generate_test_suite(
        self,
        testing_input: dict[str, Any],
    ) -> str:
        print(
            "[Testing] Test Suite Generation: translating Gherkin "
            "GIVEN-WHEN-THEN scenarios into pytest functions..."
        )
        llm = self._llm or AzureOpenAIJsonClient()

        response = llm.chat_json(
            self._test_generation_system_prompt(),
            json.dumps(
                {
                    "gherkin_scenarios": testing_input.get(
                        "gherkin_scenarios",
                        [],
                    ),
                    "schemas_code": testing_input.get(
                        "schemas_code",
                        "",
                    ),
                    "service_code": testing_input.get(
                        "service_code",
                        "",
                    ),
                    "router_code": testing_input.get(
                        "router_code",
                        "",
                    ),
                },
                indent=2,
            ),
        )

        return str(
            response.get("test_code", "")
        ).strip()

    @staticmethod
    def _test_generation_system_prompt() -> str:
        return """
You are Agent 5: Testing Agent in a legacy-code modernization pipeline,
performing the Test Suite Generation step.

Input: approved Gherkin GIVEN-WHEN-THEN scenarios, and the already
generated target Python modules (schemas_code, service_code,
router_code) for context only.

Task:
Translate every Gherkin scenario into one executable pytest test
function that exercises the corresponding behavior in the generated
target code.

Import convention (the generated code will be placed in a package
named `target_app` in the sandbox, alongside your test file):
- from target_app.schemas import ...
- from target_app.service import ...
- from target_app.router import router
- from target_app.main import app

Prefer testing service-layer functions directly. Where a scenario is
best exercised through the HTTP API, use FastAPI's TestClient:
    from fastapi.testclient import TestClient
    from target_app.main import app
    client = TestClient(app)

Rules:
- Output a single, complete, syntactically valid Python module usable
  as a pytest test file (functions named test_*).
- Include all necessary imports at the top of the file.
- One test function per Gherkin scenario at minimum; use the scenario
  name (converted to snake_case) in the test function name.
- Assert on the behavior described by the scenario's THEN steps.
- Do not invent behavior that is not described by a Gherkin scenario.
- Do not include markdown code fences.

Return JSON only:
{
  "test_code": "string containing the full contents of the pytest file"
}
""".strip()

    # ------------------------------------------------------------------
    # Step 2: Sandboxed Test Execution
    # ------------------------------------------------------------------

# this method executes the generated pytest test suite in a sandboxed environment. It creates a temporary directory, writes the target code and test code into it, and runs pytest as a subprocess. It captures the output, including stdout, stderr, and the JUnit XML report. The method returns a dictionary containing the test execution results, including whether the tests passed, any errors encountered, and paths to artifacts.
    def _execute_in_sandbox(
        self,
        testing_input: dict[str, Any],
        test_code: str,
    ) -> dict[str, Any]:
        print(
            "[Testing] Sandboxed Test Execution: spawning an isolated "
            "subprocess and executing pytest..."
        )

        sandbox_dir = Path(
            tempfile.mkdtemp(prefix="pipeline_sandbox_")
        )

        try:
            package_dir = sandbox_dir / "target_app"
            package_dir.mkdir(parents=True, exist_ok=True)

            (package_dir / "__init__.py").write_text(
                "",
                encoding="utf-8",
            )
            (package_dir / "schemas.py").write_text(
                self._ensure_trailing_newline(
                    testing_input.get("schemas_code", "")
                ),
                encoding="utf-8",
            )
            (package_dir / "service.py").write_text(
                self._ensure_trailing_newline(
                    testing_input.get("service_code", "")
                ),
                encoding="utf-8",
            )
            (package_dir / "router.py").write_text(
                self._ensure_trailing_newline(
                    testing_input.get("router_code", "")
                ),
                encoding="utf-8",
            )
            (package_dir / "main.py").write_text(
                self._ensure_trailing_newline(
                    testing_input.get("main_code", "")
                ),
                encoding="utf-8",
            )

            test_file = sandbox_dir / "test_generated.py"
            test_file.write_text(
                self._ensure_trailing_newline(test_code),
                encoding="utf-8",
            )

            junit_path = sandbox_dir / "report.xml"

            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        str(test_file),
                        f"--junitxml={junit_path}",
                        "-q",
                    ],
                    cwd=str(sandbox_dir),
                    capture_output=True,
                    text=True,
                    timeout=self.sandbox_timeout_seconds,
                )
                stdout, stderr = completed.stdout, completed.stderr
                timed_out = False
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout or ""
                stderr = exc.stderr or ""
                timed_out = True

            if timed_out:
                return {
                    "verified": False,
                    "summary": {
                        "total_tests": 0,
                        "passed": 0,
                        "failed": 0,
                        "errors": 0,
                        "pass_rate": 0.0,
                    },
                    "test_results": [],
                    "execution_error": (
                        "pytest execution timed out after "
                        f"{self.sandbox_timeout_seconds} seconds."
                    ),
                    "stdout": stdout,
                    "stderr": stderr,
                    "junit_xml_path": None,
                    "_sandbox_dir": str(sandbox_dir),
                }

            if not junit_path.exists():
                return {
                    "verified": False,
                    "summary": {
                        "total_tests": 0,
                        "passed": 0,
                        "failed": 0,
                        "errors": 0,
                        "pass_rate": 0.0,
                    },
                    "test_results": [],
                    "execution_error": (
                        "pytest did not produce a JUnit report "
                        "(likely a collection/import error). "
                        "See stdout/stderr for details."
                    ),
                    "stdout": stdout,
                    "stderr": stderr,
                    "junit_xml_path": None,
                    "_sandbox_dir": str(sandbox_dir),
                }

            summary, test_results = self._parse_junit_report(
                junit_path
            )

            verified = (
                summary["total_tests"] > 0
                and summary["failed"] == 0
                and summary["errors"] == 0
            )

            return {
                "verified": verified,
                "summary": summary,
                "test_results": test_results,
                "execution_error": None,
                "stdout": stdout,
                "stderr": stderr,
                "junit_xml_path": str(junit_path),
                "_sandbox_dir": str(sandbox_dir),
            }
        except Exception:
            # Unexpected failure while preparing/running the sandbox.
            # Clean up immediately since _write_bau_artifacts will
            # never get a chance to snapshot it.
            shutil.rmtree(sandbox_dir, ignore_errors=True)
            raise


# This method parses the JUnit XML report and extracts test results. It returns a summary dictionary containing total tests, passed, failed, errors, skipped, and pass rate, along with a list of individual test result dictionaries containing test name, classname, outcome, message, and stderr.
    @staticmethod
    def _parse_junit_report(
        junit_path: Path,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        tree = ET.parse(junit_path)
        root = tree.getroot()

        # JUnit XML root can be <testsuite> or <testsuites><testsuite>...
        testcases = root.findall(".//testcase")

        total = len(testcases)
        failed = 0
        errors = 0
        skipped = 0
        test_results: list[dict[str, Any]] = []

        for case in testcases:
            name = case.get("name", "unknown_test")
            classname = case.get("classname", "")
            outcome = "passed"
            message = ""
            stderr_text = ""

            failure = case.find("failure")
            error = case.find("error")
            skip = case.find("skipped")

            if failure is not None:
                outcome = "failed"
                failed += 1
                message = failure.get("message", "")
                stderr_text = (failure.text or "").strip()
            elif error is not None:
                outcome = "error"
                errors += 1
                message = error.get("message", "")
                stderr_text = (error.text or "").strip()
            elif skip is not None:
                outcome = "skipped"
                skipped += 1
                message = skip.get("message", "")

            test_results.append(
                {
                    "test_name": (
                        f"{classname}::{name}" if classname else name
                    ),
                    "classname": classname,
                    "outcome": outcome,
                    "message": message,
                    "stderr": stderr_text,
                }
            )

        passed = total - failed - errors - skipped
        pass_rate = (
            round((passed / total) * 100, 2) if total else 0.0
        )

        summary = {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "pass_rate": pass_rate,
        }

        return summary, test_results

    # ------------------------------------------------------------------
    # Step 3: Parity Verification
    # ------------------------------------------------------------------

# This method builds the final result dictionary containing the test execution results and any feedback for the Agent 4. It checks whether the tests passed (verified) or failed, and captures stack traces and failing test details for feedback. The result includes status, mode, test code, summary, test results, and feedback information.
    def _build_result(
        self,
        execution_result: dict[str, Any],
        test_code: str,
    ) -> dict[str, Any]:
        verified = bool(
            execution_result.get("verified")
        )

        result: dict[str, Any] = {
            "status": "VERIFIED" if verified else "FAILED",
            "mode": "sandboxed_pytest_execution",
            "test_code": test_code,
            "summary": execution_result.get(
                "summary",
                {
                    "total_tests": 0,
                    "passed": 0,
                    "failed": 0,
                    "errors": 0,
                    "pass_rate": 0.0,
                },
            ),
            "test_results": execution_result.get(
                "test_results",
                [],
            ),
        }

        if verified:
            print(
                "[Testing] pytest executions pass (100% parity "
                "verified). Marking pipeline state as VERIFIED."
            )
            return result

        print(
            "[Testing] pytest executions failed. Capturing exact "
            "stderr stack traces for the Agent 4 feedback edge."
        )

        failing_details = [
            item
            for item in execution_result.get("test_results", [])
            if item.get("outcome") in {"failed", "error"}
        ]

        if execution_result.get("execution_error"):
            combined_stack_trace = (
                execution_result["execution_error"]
                + "\n\n--- stdout ---\n"
                + execution_result.get("stdout", "")
                + "\n\n--- stderr ---\n"
                + execution_result.get("stderr", "")
            )
            failing_test_names = []
        else:
            combined_stack_trace = "\n\n".join(
                f"{item['test_name']}:\n"
                f"{item.get('stderr') or item.get('message') or ''}"
                for item in failing_details
            )
            failing_test_names = [
                item["test_name"] for item in failing_details
            ]

        result["feedback"] = {
            "stack_trace": combined_stack_trace,
            "failing_tests": failing_test_names,
            "failing_test_details": failing_details,
            "execution_error": execution_result.get(
                "execution_error"
            ),
        }

        return result

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

# This method validates the syntax of the generated pytest code.
    @staticmethod
    def _validate_python_syntax(
        test_code: str,
    ) -> dict[str, Any]:
        if not test_code.strip():
            return {
                "valid": False,
                "message": "No pytest code was generated.",
            }
        try:
            pyast.parse(test_code, filename="test_generated.py")
        except SyntaxError as exc:
            return {
                "valid": False,
                "message": (
                    f"{exc.msg} (line {exc.lineno}, col {exc.offset})"
                ),
            }
        return {
            "valid": True,
            "message": "Generated pytest module passed syntax validation.",
        }

    # ------------------------------------------------------------------
    # BAU artifact persistence
    # ------------------------------------------------------------------

# This method persists the testing artifacts in human/team-friendly formats.
    def _write_bau_artifacts(
        self,
        testing_input: dict[str, Any],
        test_code: str,
        execution_result: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Persist testing artifacts in human/team-friendly formats.

        Output:
            outputs/testing/
                tests/test_generated.py
                sandbox_snapshot/   (copy of what was actually executed)
                report.xml          (JUnit XML, if produced)
                execution_log.txt   (stdout + stderr)
                test_execution_report.json
                testing_summary.md
        """
        testing_dir = self.output_dir / "testing"
        tests_dir = testing_dir / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)

        test_file_path = tests_dir / "test_generated.py"
        test_file_path.write_text(
            self._ensure_trailing_newline(test_code),
            encoding="utf-8",
        )

        written: dict[str, Any] = {
            "test_file": str(test_file_path),
        }

        sandbox_dir = execution_result.get("_sandbox_dir")
        if sandbox_dir and Path(sandbox_dir).exists():
            snapshot_dir = testing_dir / "sandbox_snapshot"
            if snapshot_dir.exists():
                shutil.rmtree(snapshot_dir)
            shutil.copytree(sandbox_dir, snapshot_dir)
            written["sandbox_snapshot_directory"] = str(snapshot_dir)

            junit_source = Path(sandbox_dir) / "report.xml"
            if junit_source.exists():
                junit_dest = testing_dir / "report.xml"
                shutil.copyfile(junit_source, junit_dest)
                written["junit_report"] = str(junit_dest)

            # Sandbox is disposable; clean it up now that we have a
            # persisted snapshot under output_dir.
            shutil.rmtree(sandbox_dir, ignore_errors=True)

        execution_log_path = testing_dir / "execution_log.txt"
        execution_log_path.write_text(
            (
                "--- stdout ---\n"
                + execution_result.get("stdout", "")
                + "\n\n--- stderr ---\n"
                + execution_result.get("stderr", "")
            ),
            encoding="utf-8",
        )
        written["execution_log"] = str(execution_log_path)

        report_path = testing_dir / "test_execution_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "status": result["status"],
                    "summary": result["summary"],
                    "test_results": result["test_results"],
                    "feedback": result.get("feedback"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        written["test_execution_report"] = str(report_path)

        summary_path = testing_dir / "testing_summary.md"
        summary_path.write_text(
            self._markdown_summary(result),
            encoding="utf-8",
        )
        written["summary_markdown"] = str(summary_path)

        written["testing_directory"] = str(testing_dir)

        return written

# This method builds a markdown summary of the test execution results.
    @staticmethod
    def _markdown_summary(
        result: dict[str, Any],
    ) -> str:
        summary = result.get("summary", {})
        lines = [
            "# Test Execution Report",
            "",
            f"- Status: **{result.get('status')}**",
            f"- Total tests: {summary.get('total_tests', 0)}",
            f"- Passed: {summary.get('passed', 0)}",
            f"- Failed: {summary.get('failed', 0)}",
            f"- Errors: {summary.get('errors', 0)}",
            f"- Skipped: {summary.get('skipped', 0)}",
            f"- Pass rate: {summary.get('pass_rate', 0.0)}%",
            "",
        ]

        if result.get("status") != "VERIFIED":
            lines.append("## Failing Tests")
            lines.append("")
            feedback = result.get("feedback", {}) or {}
            for item in feedback.get("failing_test_details", []):
                lines.append(f"### {item.get('test_name')}")
                lines.append("")
                lines.append(f"- Outcome: {item.get('outcome')}")
                lines.append(f"- Message: {item.get('message')}")
                lines.append("")
                lines.append("```")
                lines.append(item.get("stderr", ""))
                lines.append("```")
                lines.append("")

            if feedback.get("execution_error"):
                lines.append("## Execution Error")
                lines.append("")
                lines.append("```")
                lines.append(str(feedback.get("execution_error")))
                lines.append("```")
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _ensure_trailing_newline(text: str) -> str:
        text = str(text).strip("\n")
        return (text + "\n") if text else ""


__all__ = [
    "TestingAgent",
    "AzureOpenAIJsonClient",
    "JsonLLM",
]
