from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.graph import run_full_pipeline


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "sample_input"
OUTPUT_DIR = BASE_DIR / "outputs"

SUPPORTED_EXTENSIONS = {
    ".java",
    ".cbl",
    ".cob",
    ".cpy",
    ".py",
    ".js",
    ".mjs",
    ".ts",
    ".tsx",
    ".c",
    ".h",
    ".cpp",
    ".cc",
    ".hpp",
}


def load_source_files() -> list[dict[str, str]]:
    files = []

    for path in sorted(INPUT_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(
                {
                    "path": path.name,
                    "content": path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    ),
                }
            )

    return files


def main() -> None:
    load_dotenv()

    source_files = load_source_files()

    if not source_files:
        print(
            f"No supported source files found in: {INPUT_DIR}"
        )
        sys.exit(1)

    print("=" * 70)
    print(
        "LEGACY CODE MODERNIZATION PIPELINE — "
        "AGENTIC PARSER THROUGH DASHBOARD"
    )
    print("=" * 70)

    print(f"\nFound {len(source_files)} source file(s):")
    for source in source_files:
        print(f"  - {source['path']}")

    result = run_full_pipeline(
        run_id="parser-to-dashboard-agentic-test",
        source_files=source_files,
        max_evaluation_retries=2,
        max_testing_retries=2,
    )

    artifacts = result.get("artifacts", {})

    parser_output = artifacts.get(
        "parser_output",
        {},
    )
    call_graph = parser_output.get(
        "dependency_call_graph",
        {},
    )
    splitting = artifacts.get(
        "splitting_output",
        {},
    )
    documentation = artifacts.get(
        "documentation_output",
        {},
    )
    evaluation = artifacts.get(
        "evaluation_output",
        {},
    )
    target = artifacts.get(
        "target_output",
        {},
    )
    testing = artifacts.get(
        "testing_output",
        {},
    )
    dashboard = artifacts.get(
        "dashboard_report",
        {},
    )

    print("\n[1] Parser")
    print(
        f"  Files parsed        : "
        f"{len(parser_output.get('files', []))}"
    )
    print(
        "  Grammar slices      : "
        f"{sum(len(f.get('grammar_slices', [])) for f in parser_output.get('files', []))}"
    )
    print(
        f"  Call graph nodes    : "
        f"{len(call_graph.get('nodes', []))}"
    )
    print(
        f"  Call graph edges    : "
        f"{len(call_graph.get('edges', []))}"
    )

    print("\n[2] Splitting Agent")
    print(
        f"  Modules             : "
        f"{len(splitting.get('modules', []))}"
    )
    print(
        f"  Execution paths     : "
        f"{len(splitting.get('execution_paths', []))}"
    )
    print(
        f"  Module dependencies : "
        f"{len(splitting.get('module_dependencies', []))}"
    )

    print("\n[3] Documentation Agent")
    print(
        f"  Gherkin features    : "
        f"{len(documentation.get('gherkin_scenarios', []))}"
    )
    print(
        f"  OpenAPI generated   : "
        f"{bool(documentation.get('openapi_spec'))}"
    )
    print(
        "  OpenAPI valid       : "
        f"{documentation.get('openapi_validation', {}).get('valid')}"
    )

    print("\n[4] Evaluation Agent")
    print(
        f"  Status              : "
        f"{evaluation.get('status')}"
    )
    print(
        f"  Overall score       : "
        f"{evaluation.get('overall_score')}"
    )
    print(
        f"  Threshold           : "
        f"{evaluation.get('threshold')}"
    )
    print(
        "  Documentation retries used: "
        f"{result.get('evaluation_retries')} / "
        f"{result.get('max_evaluation_retries')}"
    )

    print("\n[5] Coding Agent (Agent 4 — Target Code)")
    if target:
        print(
            f"  Mode                : "
            f"{target.get('mode')}"
        )
        syntax_validation = target.get(
            "syntax_validation",
            {},
        )
        print(
            f"  Syntax valid        : "
            f"{syntax_validation.get('valid')}"
        )

        for key, value in target.get(
            "artifacts",
            {},
        ).items():
            print(f"    - {key}: {value}")
    else:
        print(
            "  Skipped — documentation quality gate "
            "did not reach approval."
        )

    print("\n[6] Testing Agent (Agent 5 — pytest Verification)")
    if testing:
        summary = testing.get(
            "summary",
            {},
        )
        print(
            f"  Status              : "
            f"{testing.get('status')}"
        )
        print(
            f"  Total tests         : "
            f"{summary.get('total_tests')}"
        )
        print(
            f"  Passed              : "
            f"{summary.get('passed')}"
        )
        print(
            f"  Failed              : "
            f"{summary.get('failed')}"
        )
        print(
            f"  Errors              : "
            f"{summary.get('errors')}"
        )
        print(
            f"  Pass rate           : "
            f"{summary.get('pass_rate')}%"
        )
        print(
            "  Testing retries used: "
            f"{result.get('testing_retries')} / "
            f"{result.get('max_testing_retries')}"
        )

        for key, value in testing.get(
            "artifacts",
            {},
        ).items():
            print(f"    - {key}: {value}")
    else:
        print(
            "  Skipped — Coding Agent did not produce target_output."
        )

    print("\n[7] Dashboard")
    if dashboard:
        print(
            f"  Overall pipeline status : "
            f"{dashboard.get('overall_pipeline_status')}"
        )

        doc_gate = dashboard.get(
            "documentation_quality_gate",
            {},
        )
        test_gate = dashboard.get(
            "testing_quality_gate",
            {},
        )

        print(
            "  Documentation gate      : "
            f"{doc_gate.get('final_status')} "
            f"({len(doc_gate.get('areas_requiring_manual_review', []))} "
            "area(s) flagged for manual cross-check)"
        )

        print(
            "  Testing gate            : "
            f"{test_gate.get('final_status')} "
            f"({len(test_gate.get('areas_requiring_manual_review', []))} "
            "area(s) flagged for manual review)"
        )

        print(
            "  Dashboard HTML          : "
            f"{dashboard.get('artifacts', {}).get('dashboard_html')}"
        )
    else:
        print(
            "  Not generated."
        )

    print("\n[8] Supervisor Decisions")
    for decision in result.get(
        "supervisor_decisions",
        [],
    ):
        print(
            f"  Step {decision.get('step')}: "
            f"{decision.get('from_agent')} -> "
            f"{decision.get('next_agent')} | "
            f"{decision.get('reason')}"
        )

    print("\n[9] Final State Artifacts")
    for name in sorted(artifacts):
        print(f"  - {name}")

    print("\n[10] State Audit Events")
    for event in result.get(
        "events",
        [],
    ):
        print(
            f"  {event['stage']:<20} "
            f"{event['action']:<8} "
            f"{event['artifact']}"
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        OUTPUT_DIR
        / "full_agentic_pipeline_with_dashboard_output.json"
    )

    output_path.write_text(
        json.dumps(
            result,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nFinal pipeline state written to:")
    print(output_path)

    print("\n" + "=" * 70)
    print("AGENTIC PIPELINE COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    main()
