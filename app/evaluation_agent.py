"""
Evaluation Agent - Agent 3

Purpose
-------
Validates the functional documentation produced by Agent 2 against the
legacy parser's AST ground truth.

Processing flow
---------------
1. Read Gherkin/OpenAPI artifacts from Agent 2.
2. Read conditional AST branches from the Parser.
3. Use Azure OpenAI as an LLM-as-a-Judge to compare branches with the
   generated Gherkin scenarios.
4. Calculate the weighted quality score:
       S = (0.40 * S_Business)
         + (0.25 * S_Edge)
         + (0.20 * S_Data)
         + (0.15 * S_Consistency)
5. If S >= 85:
       APPROVED -> route to Agent 4.
   Otherwise:
       REJECTED -> create structured feedback and route to Agent 2.

The implementation uses only the artifacts required by this agent. It does
not send the complete parser_splitting_documentation JSON file to the LLM.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    from openai import AzureOpenAI
except ImportError:  # pragma: no cover
    AzureOpenAI = None


if load_dotenv is not None:
    load_dotenv()


# ---------------------------------------------------------------------------
# Evaluation configuration
# ---------------------------------------------------------------------------

APPROVAL_THRESHOLD = 85.0

WEIGHTS = {
    "business": 0.40,
    "edge": 0.25,
    "data": 0.20,
    "consistency": 0.15,
}

# Keep LLM requests bounded. This is particularly important for the team's
# large lines of legacy code, which can produce thousands of conditional branches. The LLM is not expected to handle more than 40 branches at a time, so we batch them into groups of 40. The LLM is expected to return a JSON object with the evaluation results
BRANCH_BATCH_SIZE = 40 # conditional branches per LLM request
MAX_SNIPPET_CHARS = 1800 #characters of legacy code snippet to send to LLM for evaluation. Longer snippets are truncated to avoid overwhelming the LLM and to keep the request size manageable.


# ---------------------------------------------------------------------------
# Azure OpenAI wrapper
# ---------------------------------------------------------------------------

# this wrapper is used to encapsulate the Azure OpenAI client and provide a method for sending chat requests and receiving JSON responses. It handles the necessary environment variable checks and client initialization.
@dataclass
class AzureJudge:
    client: Any
    deployment: str


# create an instance of AzureJudge from environment variables. It checks for the required environment variables and raises an error if any are missing. It initializes the AzureOpenAI client with the provided endpoint, API key, and API version.
    @classmethod
    def from_environment(cls) -> "AzureJudge":
        if AzureOpenAI is None:
            raise RuntimeError(
                "openai package is not installed. "
                "Install dependencies from requirements.txt."
            )

        endpoint = os.getenv("azure_endpoint")
        api_key = os.getenv("AZURE_OPENAI_KEY")
        api_version = os.getenv("api_version")
        deployment = os.getenv("model")

        missing = [
            name
            for name, value in {
                "azure_endpoint": endpoint,
                "AZURE_OPENAI_KEY": api_key,
                "api_version": api_version,
                "model": deployment,
            }.items()
            if not value
        ]

        if missing:
            raise RuntimeError(
                "Missing Azure OpenAI environment variables: "
                + ", ".join(missing)
            )

        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )

        return cls(
            client=client,
            deployment=deployment,
        )

# this method sends a chat request to the Azure OpenAI service with a system prompt and user payload. It formats the user payload as JSON and specifies that the response should be in JSON format. The method attempts to parse the response content as JSON and returns it as a dictionary. If parsing fails, it returns an empty dictionary.
    def chat_json(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
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
        )

        content = response.choices[0].message.content or "{}"

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}


# ---------------------------------------------------------------------------
# Evaluation Agent
# ---------------------------------------------------------------------------

class EvaluationAgent:
    """
    Agent 3 - Evaluation / Quality Gate.

    Expected Central Shared State artifacts:

    From Agent 2:
        documentation_output
            - gherkin_scenarios
            - openapi_spec

    From Parser:
        parser_output
            - files
            - each file's AST

    Produced artifacts:
        evaluation_output
        evaluation_feedback   # written when score < 85
    """

# initializes the EvaluationAgent with an optional AzureJudge instance and a threshold score for approval. If no AzureJudge is provided, it creates one from environment variables. The threshold is converted to a float for consistency.
    def __init__(
        self,
        judge: AzureJudge | None = None,
        threshold: float = APPROVAL_THRESHOLD,
    ):
        self.judge = judge or AzureJudge.from_environment()
        self.threshold = float(threshold)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

#this method executes the evaluation process using the provided Central Shared State. It reads the necessary artifacts from the state, extracts conditional branches from the parser output, and evaluates the documentation against the branches. The evaluation result is written back to the state, and if the evaluation is rejected, feedback is also written to the state for further refinement.
    def run(self, state: Any) -> dict[str, Any]:
        """
        Execute Agent 3 using the Central Shared State.

        The state is expected to provide:
            read_artifact(name)
            write_artifact(name, value)
        """

        documentation_output = state.read_artifact(
            "documentation_output"
        )

        parser_output = state.read_artifact(
            "parser_output"
        )

        gherkin = documentation_output.get(
            "gherkin_scenarios",
            [],
        )

        openapi_spec = documentation_output.get(
            "openapi_spec",
            {},
        )

        branches = self._extract_conditional_branches(
            parser_output
        )

        evaluation = self.evaluate(
            gherkin_scenarios=gherkin,
            openapi_spec=openapi_spec,
            branches=branches,
        )

        if state.has_artifact("evaluation_output"):
            state.replace_artifact(
            "evaluation_output",
            evaluation,
            stage="evaluation_agent",
        )
        else:
            state.write_artifact(
            "evaluation_output",
            evaluation,
            stage="evaluation_agent",
        )


        if evaluation["status"] == "REJECTED":
            if state.has_artifact("evaluation_feedback"):
                state.replace_artifact(
                "evaluation_feedback",
                evaluation["feedback"],
                stage="evaluation_agent",
            )
            else:
                state.write_artifact(
                "evaluation_feedback",
                evaluation["feedback"],
                stage="evaluation_agent",
            )

        return evaluation

    # ------------------------------------------------------------------
    # Main evaluation flow
    # ------------------------------------------------------------------
# this method evaluates the documentation against the extracted conditional branches. It handles cases where there are no branches by performing a documentation/data consistency check. If branches are present, it processes them in batches, sending them to the LLM for evaluation. The results are aggregated, normalized, and scored. Based on the score and threshold, it determines whether the evaluation is approved or rejected and prepares feedback accordingly.

    def evaluate(
        self,
        gherkin_scenarios: Any,
        openapi_spec: dict[str, Any],
        branches: list[dict[str, Any]],
    ) -> dict[str, Any]:

        if not branches:
            # No conditional branches were found in the parser AST.
            # We still perform a documentation/data consistency check based on different categories.
            judge_result = self._judge_empty_branch_case(
                gherkin_scenarios,
                openapi_spec,
            )
            branch_results = []
        else:
            branch_results = []

            batches = [
                branches[i:i + BRANCH_BATCH_SIZE]
                for i in range(
                    0,
                    len(branches),
                    BRANCH_BATCH_SIZE,
                )
            ]

            for batch_number, batch in enumerate(
                batches,
                start=1,
            ):
                print(
                    f"[Evaluation] Auditing branch batch "
                    f"{batch_number}/{len(batches)} "
                    f"({len(batch)} branches)..."
                )

                result = self._judge_branch_batch(
                    batch=batch,
                    gherkin_scenarios=gherkin_scenarios,
                )

                branch_results.extend(
                    result.get("branch_results", [])
                )

            judge_result = self._aggregate_branch_results(
                branch_results
            )

        category_scores = self._normalise_scores(
            judge_result.get("category_scores", {})
        )

        score = self._calculate_score(
            category_scores
        )

        approved = score >= self.threshold

        if approved:
            feedback = {}
            route = "agent_4"
            status = "APPROVED"
        else:
            feedback = self._build_feedback(
                score=score,
                category_scores=category_scores,
                branch_results=branch_results,
            )
            route = "agent_2"
            status = "REJECTED"

        return {
            "status": status,
            "approved": approved,
            "overall_score": round(score, 2),
            "threshold": self.threshold,
            "category_scores": category_scores,
            "branch_audit": branch_results,
            "route": route,
            "evaluation_report": {
                "summary": (
                    "Documentation passed the quality gate."
                    if approved
                    else
                    "Documentation failed the quality gate "
                    "and requires targeted refinement."
                ),
                "business_coverage": category_scores["business"],
                "edge_coverage": category_scores["edge"],
                "data_coverage": category_scores["data"],
                "consistency": category_scores["consistency"],
            },
            "feedback": feedback,
        }

    # ------------------------------------------------------------------
    # LLM judge prompts
    # ------------------------------------------------------------------
# this method evaluates a batch of conditional branches against the provided Gherkin scenarios using the Azure OpenAI service. It constructs a system prompt that instructs the LLM to compare the branches with the scenarios and determine coverage, scores, and consistency. The method sends the prompt and payload to the LLM and returns the evaluation results as a dictionary.

    def _judge_branch_batch(
        self,
        batch: list[dict[str, Any]],
        gherkin_scenarios: Any,
    ) -> dict[str, Any]:

        system_prompt = """
You are Agent 3, the Evaluation Agent in a legacy-code modernization
pipeline.

You are an LLM-as-a-Judge. Compare the Parser AST conditional branches
(the ground truth) against the Gherkin scenarios generated by Agent 2.

For every branch, determine:
- whether the business rule is represented,
- whether the branch/edge is represented,
- whether important data used by the branch is represented,
- whether the Gherkin behavior is consistent with the legacy branch.

A branch can be:
  covered, partially_covered, or missing.

Do not invent business rules.
Do not use legacy implementation details as business requirements.
Use only the supplied AST branch information and Gherkin scenarios.

Return JSON only:

{
  "branch_results": [
    {
      "ast_node_id": "...",
      "source_location": "...",
      "legacy_code_snippet": "...",
      "coverage": "covered|partially_covered|missing",
      "business_score": 0-100,
      "edge_score": 0-100,
      "data_score": 0-100,
      "consistency_score": 0-100,
      "missing_rule_description": "...",
      "failure_category": "...",
      "matched_gherkin": ["..."]
    }
  ]
}
"""

        payload = {
            "branches": batch,
            "gherkin_scenarios": gherkin_scenarios,
        }

        return self.judge.chat_json(
            system_prompt,
            payload,
        )


# this method handles the case where no conditional branches are found in the parser AST. It sends a system prompt to the Azure OpenAI service instructing the LLM to evaluate the generated documentation for data and consistency quality. The method returns the evaluation results as a dictionary containing category scores for business, edge, data, and consistency.
    def _judge_empty_branch_case(
        self,
        gherkin_scenarios: Any,
        openapi_spec: dict[str, Any],
    ) -> dict[str, Any]:

        system_prompt = """
You are Agent 3, the Evaluation Agent.

No conditional branches were found in the Parser AST.

Evaluate the generated documentation for data and consistency quality.
Do not invent missing AST branches.

Return JSON only:

{
  "category_scores": {
    "business": 0-100,
    "edge": 0-100,
    "data": 0-100,
    "consistency": 0-100
  }
}
"""

        return self.judge.chat_json(
            system_prompt,
            {
                "gherkin_scenarios": gherkin_scenarios,
                "openapi_spec": openapi_spec,
            },
        )

    # ------------------------------------------------------------------
    # Score calculation
    # ------------------------------------------------------------------

# this method aggregates the evaluation results from multiple branches and calculates the average scores for each category (business, edge, data, consistency). It returns a dictionary containing the averaged category scores. If no branch results are provided, it returns zero scores for all categories.
    def _aggregate_branch_results(
        self,
        branch_results: list[dict[str, Any]],
    ) -> dict[str, Any]:

        if not branch_results:
            return {
                "category_scores": {
                    "business": 0,
                    "edge": 0,
                    "data": 0,
                    "consistency": 0,
                }
            }

        def average(key: str) -> float:
            values = [
                float(item.get(key, 0))
                for item in branch_results
            ]
            return sum(values) / len(values)

        return {
            "category_scores": {
                "business": average("business_score"),
                "edge": average("edge_score"),
                "data": average("data_score"),
                "consistency": average("consistency_score"),
            }
        }

# this method normalizes the category scores to ensure they fall within the range of 0 to 100. It clamps each score to this range and returns a dictionary containing the normalized scores for business, edge, data, and consistency categories.
    def _normalise_scores(
        self,
        scores: dict[str, Any],
    ) -> dict[str, float]:

        return {
            "business": self._clamp(
                scores.get("business", 0)
            ),
            "edge": self._clamp(
                scores.get("edge", 0)
            ),
            "data": self._clamp(
                scores.get("data", 0)
            ),
            "consistency": self._clamp(
                scores.get("consistency", 0)
            ),
        }


# this method calculates the overall weighted score based on the normalized category scores. It applies predefined weights to each category and returns the final score as a float.
    @staticmethod
    def _calculate_score(
        scores: dict[str, float],
    ) -> float:

        return (
            WEIGHTS["business"] * scores["business"]
            + WEIGHTS["edge"] * scores["edge"]
            + WEIGHTS["data"] * scores["data"]
            + WEIGHTS["consistency"] * scores["consistency"]
        )

# this method clamps a given value to ensure it falls within the range of 0 to 100. It attempts to convert the value to a float and returns 0.0 if the conversion fails. The clamped value is returned as a float.
    @staticmethod
    def _clamp(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0

        return max(0.0, min(100.0, number))

    # ------------------------------------------------------------------
    # Feedback for Agent 2 retry loop
    # ------------------------------------------------------------------

#this method builds structured feedback for Agent 2 when the evaluation score is below the approval threshold. It identifies missing or partially covered branches, provides remediation instructions based on category scores, and returns a dictionary containing the overall score, threshold, category scores, unmapped branches, actionable remediation instructions, and evaluator retry count.
    def _build_feedback(
        self,
        score: float,
        category_scores: dict[str, float],
        branch_results: list[dict[str, Any]],
    ) -> dict[str, Any]:

        missing = [
            item
            for item in branch_results
            if item.get("coverage")
            in {"missing", "partially_covered"}
        ]

        unmapped_branches = []

        for item in missing:
            unmapped_branches.append(
                {
                    "ast_node_id": item.get(
                        "ast_node_id"
                    ),
                    "source_location": item.get(
                        "source_location"
                    ),
                    "legacy_code_snippet": item.get(
                        "legacy_code_snippet"
                    ),
                    "missing_rule_description": item.get(
                        "missing_rule_description"
                    ),
                    "failure_category": item.get(
                        "failure_category"
                    ),
                }
            )

        remediation = []

        if category_scores["business"] < 85:
            remediation.append(
                "Review missing business rules and add "
                "corresponding Gherkin scenarios."
            )

        if category_scores["edge"] < 85:
            remediation.append(
                "Add scenarios for missing if/else, "
                "switch/case, or equivalent branch paths."
            )

        if category_scores["data"] < 85:
            remediation.append(
                "Review inputs, outputs, and data used by "
                "the missing branches."
            )

        if category_scores["consistency"] < 85:
            remediation.append(
                "Correct Gherkin rules that do not match "
                "the Parser AST ground truth."
            )

        return {
            "overall_score": round(score, 2),
            "threshold": self.threshold,
            "category_scores": category_scores,
            "unmapped_branches": unmapped_branches,
            "actionable_remediation_instructions": remediation,
            "evaluator_retry_count": 0,
        }

    # ------------------------------------------------------------------
    # Parser AST extraction
    # ------------------------------------------------------------------

#This method extracts conditional branches from the parser output. It iterates through the files in the parser output, retrieves the AST for each file, and walks through the AST to identify conditional nodes. The extracted branches are collected in a list and returned as a list of dictionaries containing branch information.
    def _extract_conditional_branches(
        self,
        parser_output: dict[str, Any],
    ) -> list[dict[str, Any]]:

        branches: list[dict[str, Any]] = []

        for file_info in parser_output.get(
            "files",
            [],
        ):
            path = file_info.get(
                "path",
                "<unknown>",
            )

            ast = file_info.get(
                "ast"
            )

            if ast is None:
                continue

            self._walk_ast(
                ast=ast,
                path=path,
                branches=branches,
            )

        return branches

    def _walk_ast(
        self,
        ast: Any,
        path: str,
        branches: list[dict[str, Any]],
    ) -> None:

        if isinstance(ast, list):
            for item in ast:
                self._walk_ast(
                    item,
                    path,
                    branches,
                )
            return

        if not isinstance(ast, dict):
            return

        node_type = str(
            ast.get(
                "type",
                ast.get(
                    "grammar_node",
                    "",
                ),
            )
        ).lower()

        conditional_types = {
            "if_statement",
            "if_expression",
            "else_clause",
            "switch_statement",
            "switch_case",
            "case_statement",
            "case_clause",
            "conditional_expression",
            "when_clause",
            "evaluate_statement",
        }

        if node_type in conditional_types:
            snippet = (
                ast.get("text")
                or ast.get("source")
                or ast.get("code")
                or ""
            )

            snippet = str(snippet)

            if len(snippet) > MAX_SNIPPET_CHARS:
                snippet = (
                    snippet[:MAX_SNIPPET_CHARS]
                    + "\n...[truncated]"
                )

            start = ast.get(
                "start_point",
                ast.get(
                    "start",
                    None,
                ),
            )

            end = ast.get(
                "end_point",
                ast.get(
                    "end",
                    None,
                ),
            )

            node_id = (
                ast.get("node_id")
                or ast.get("ast_node_id")
                or f"{path}:{len(branches) + 1}"
            )

            branches.append(
                {
                    "ast_node_id": node_id,
                    "source_location": {
                        "file": path,
                        "start": start,
                        "end": end,
                    },
                    "legacy_code_snippet": snippet,
                    "grammar_node": node_type,
                }
            )

        for value in ast.values():
            if isinstance(value, (dict, list)):
                self._walk_ast(
                    value,
                    path,
                    branches,
                )


# ---------------------------------------------------------------------------
# Simple local test / standalone execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(
        "EvaluationAgent is designed to run through the "
        "Central Shared State."
    )
    print(
        "Use EvaluationAgent().run(state) after the "
        "Documentation Agent has populated documentation_output."
    )
