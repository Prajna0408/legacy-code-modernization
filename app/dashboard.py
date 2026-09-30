from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from state import PipelineState
except ImportError:  # pragma: no cover - supports direct Streamlit execution
    from app.state import PipelineState

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore


class DashboardBuilder:
    """
    Builds the pipeline dashboard required by the problem statement:

        "Final evaluation report for the documentation should be
        available as a dashboard indicating the areas to be manually
        cross checked."

    Extended per the same principle to the Testing Agent's quality
    gate: parts of the generated code that still fail pytest after the
    self-healing retry limit is exhausted are surfaced here too, with
    their stderr feedback logs, for manual review.

    This is not an "agent" in the LLM sense -- it performs no LLM
    calls. It purely aggregates artifacts already produced by
    EvaluationAgent (Agent 3) and TestingAgent (Agent 5) and renders
    them into a `dashboard_report` artifact plus BAU files on disk
    (JSON + a static, self-contained HTML dashboard).

    Retry-limit semantics (both gates use the same rule, per the
    user's instructions):
        - max retries = 2 for each gate.
        - If the gate is satisfied (evaluation APPROVED / testing
          VERIFIED) at any point within the retry budget, no manual
          review is required for that gate.
        - If the retry budget is exhausted and the gate is still not
          satisfied, the still-failing areas are listed under
          `areas_requiring_manual_review` for that gate.
    """

    STAGE = "dashboard"

    def __init__(self, output_dir: str | Path = "outputs") -> None:
        self.output_dir = Path(output_dir)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(
        self,
        state: PipelineState,
        *,
        evaluation_retries: int,
        max_evaluation_retries: int,
        testing_retries: int,
        max_testing_retries: int,
    ) -> dict[str, Any]:
        documentation_section = self._build_documentation_section(
            state,
            evaluation_retries,
            max_evaluation_retries,
        )
        testing_section = self._build_testing_section(
            state,
            testing_retries,
            max_testing_retries,
        )

        overall_status = self._overall_status(
            documentation_section,
            testing_section,
        )

        report: dict[str, Any] = {
            "run_id": state.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "documentation_quality_gate": documentation_section,
            "testing_quality_gate": testing_section,
            "overall_pipeline_status": overall_status,
        }

        files_written = self._write_bau_artifacts(report)
        report["artifacts"] = files_written

        return report

    # ------------------------------------------------------------------
    # Documentation quality gate section (Agent 3 / Evaluation Agent)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_documentation_section(
        state: PipelineState,
        retries: int,
        max_retries: int,
    ) -> dict[str, Any]:
        if not state.has_artifact("evaluation_output"):
            return {
                "final_status": "NOT_RUN",
                "final_score": None,
                "threshold": None,
                "retries_used": retries,
                "max_retries": max_retries,
                "areas_requiring_manual_review": [],
            }

        evaluation_output = state.read_artifact(
            "evaluation_output"
        )
        status = evaluation_output.get("status")

        if status == "APPROVED":
            return {
                "final_status": "APPROVED",
                "final_score": evaluation_output.get("overall_score"),
                "threshold": evaluation_output.get("threshold"),
                "retries_used": retries,
                "max_retries": max_retries,
                "areas_requiring_manual_review": [],
            }

        # Only reachable via the "retry_limit" route: the score is
        # still below threshold after exhausting the retry budget.
        feedback = evaluation_output.get("feedback", {}) or {}
        unmapped_branches = feedback.get("unmapped_branches", [])
        unmapped_branches = DashboardBuilder._enrich_manual_review_items(
            state,
            unmapped_branches,
        )

        return {
            "final_status": "RETRY_LIMIT_REACHED",
            "final_score": evaluation_output.get("overall_score"),
            "threshold": evaluation_output.get("threshold"),
            "retries_used": retries,
            "max_retries": max_retries,
            "category_scores": evaluation_output.get(
                "category_scores",
                {},
            ),
            "areas_requiring_manual_review": unmapped_branches,
        }

    @staticmethod
    def _enrich_manual_review_items(
        state: PipelineState,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Fill missing legacy_code_snippet values from the Parser output.

        EvaluationAgent already asks for the source snippet, but the Parser's
        AST stores source text only on leaf nodes. Conditional nodes instead
        retain their exact text in grammar_slices. The dashboard uses those
        existing parser artifacts to recover the source text without changing
        the Parser or Evaluation Agent.
        """
        if not items or not state.has_artifact("parser_output"):
            return items

        parser_output = state.read_artifact("parser_output")
        files = parser_output.get("files", []) or []

        # Index grammar slices by file and source range. The Parser creates
        # control-flow slices with the exact source text.
        slice_index: dict[tuple[str, tuple[Any, ...], tuple[Any, ...]], str] = {}
        for file_info in files:
            path = str(file_info.get("path", ""))
            for slice_item in file_info.get("grammar_slices", []) or []:
                start = slice_item.get("start")
                end = slice_item.get("end")
                snippet = slice_item.get("text")
                if path and start is not None and end is not None and snippet:
                    slice_index[
                        (path, tuple(start), tuple(end))
                    ] = str(snippet)

        enriched: list[dict[str, Any]] = []
        for item in items:
            updated = dict(item)
            snippet = str(updated.get("legacy_code_snippet") or "").strip()

            if not snippet:
                location = updated.get("source_location") or {}
                file_name = str(location.get("file") or "")
                start = location.get("start")
                end = location.get("end")

                if file_name and start is not None and end is not None:
                    snippet = slice_index.get(
                        (file_name, tuple(start), tuple(end)),
                        "",
                    )

                # If the Evaluation Agent supplied a fallback node identifier
                # but the source range is still usable, try the same file's
                # control-flow slices by source range before giving up.
                if not snippet and file_name:
                    for (path, slice_start, slice_end), slice_text in slice_index.items():
                        if path != file_name:
                            continue
                        if start is not None and tuple(start) == slice_start:
                            snippet = slice_text
                            break

            updated["legacy_code_snippet"] = snippet
            enriched.append(updated)

        return enriched

    # ------------------------------------------------------------------
    # Testing quality gate section (Agent 5 / Testing Agent)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_testing_section(
        state: PipelineState,
        retries: int,
        max_retries: int,
    ) -> dict[str, Any]:
        if not state.has_artifact("testing_output"):
            return {
                "final_status": "NOT_RUN",
                "summary": {},
                "retries_used": retries,
                "max_retries": max_retries,
                "areas_requiring_manual_review": [],
            }

        testing_output = state.read_artifact(
            "testing_output"
        )
        status = testing_output.get("status")

        if status == "VERIFIED":
            return {
                "final_status": "VERIFIED",
                "summary": testing_output.get("summary", {}),
                "retries_used": retries,
                "max_retries": max_retries,
                "areas_requiring_manual_review": [],
            }

        # Only reachable via the "retry_limit" route: tests are still
        # failing after exhausting the retry budget.
        feedback = testing_output.get("feedback", {}) or {}

        return {
            "final_status": "RETRY_LIMIT_REACHED",
            "summary": testing_output.get("summary", {}),
            "retries_used": retries,
            "max_retries": max_retries,
            "areas_requiring_manual_review": feedback.get(
                "failing_test_details",
                [],
            ),
            "execution_error": feedback.get("execution_error"),
        }

    # ------------------------------------------------------------------
    # Overall status
    # ------------------------------------------------------------------

    @staticmethod
    def _overall_status(
        documentation_section: dict[str, Any],
        testing_section: dict[str, Any],
    ) -> str:
        doc_status = documentation_section["final_status"]
        test_status = testing_section["final_status"]

        if doc_status == "APPROVED" and test_status == "VERIFIED":
            return "VERIFIED"
        if doc_status == "RETRY_LIMIT_REACHED":
            return "MANUAL_REVIEW_REQUIRED_DOCUMENTATION"
        if test_status == "RETRY_LIMIT_REACHED":
            return "MANUAL_REVIEW_REQUIRED_TESTING"
        return "INCOMPLETE"

    # ------------------------------------------------------------------
    # BAU artifact persistence
    # ------------------------------------------------------------------

    def _write_bau_artifacts(
        self,
        report: dict[str, Any],
    ) -> dict[str, Any]:
        dashboard_dir = self.output_dir / "dashboard"
        dashboard_dir.mkdir(parents=True, exist_ok=True)

        json_path = dashboard_dir / "dashboard_report.json"
        json_path.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

        html_path = dashboard_dir / "dashboard.html"
        html_path.write_text(
            self._render_html(report),
            encoding="utf-8",
        )

        manual_review_path = dashboard_dir / "manual_review_required_documentation.md"
        manual_review_path.write_text(
            self._render_manual_review_markdown(report),
            encoding="utf-8",
        )

        return {
            "dashboard_json": str(json_path),
            "dashboard_html": str(html_path),
            "manual_review_required_documentation": str(manual_review_path),
            "dashboard_directory": str(dashboard_dir),
        }

    @staticmethod
    def _render_manual_review_markdown(report: dict[str, Any]) -> str:
        """Render documentation failures as a human-readable Markdown report."""
        doc = report.get("documentation_quality_gate", {}) or {}
        areas = doc.get("areas_requiring_manual_review", []) or []

        lines = [
            "# Manual Review Required — Documentation",
            "",
            "The following legacy source-code areas do not have complete "
            "Gherkin coverage and require manual review.",
            "",
        ]

        if not areas:
            lines.extend([
                "No documentation areas require manual review.",
                "",
            ])
            return "\n".join(lines)

        for index, item in enumerate(areas, start=1):
            location = item.get("source_location") or {}
            file_name = str(location.get("file") or "Unknown source file")
            snippet = str(item.get("legacy_code_snippet") or "").strip()
            issue = str(
                item.get("missing_rule_description")
                or "No Gherkin scenario provided to represent this branch."
            ).strip()

            start = location.get("start")
            end = location.get("end")
            line_info = ""
            if isinstance(start, (list, tuple)) and start:
                start_line = start[0]
                end_line = end[0] if isinstance(end, (list, tuple)) and end else start_line
                line_info = (
                    f" (lines {start_line}-{end_line})"
                    if start_line != end_line
                    else f" (line {start_line})"
                )

            lines.extend([
                f"## {index}. Missing Gherkin scenario",
                "",
                f"**Legacy source:** `{file_name}`{line_info}",
                "",
                "**Source code requiring a Gherkin scenario:**",
                "",
                "```text",
                snippet or "[Source code text was not available in the parser output.]",
                "```",
                "",
                f"**Issue:** {issue}",
                "",
                "---",
                "",
            ])

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Developer UI
    # ------------------------------------------------------------------

    def render_ui(self, report: dict[str, Any]) -> None:
        """
        Render the existing dashboard report as a compact developer UI.

        This is presentation-only. It does not modify PipelineState, retry
        handling, quality gates, or the dashboard artifacts written to disk.
        """
        if st is None:
            raise RuntimeError(
                "Streamlit is required for the dashboard UI. "
                "Install it with: pip install streamlit"
            )

        doc = report.get("documentation_quality_gate", {}) or {}
        test = report.get("testing_quality_gate", {}) or {}
        overall = str(report.get("overall_pipeline_status", "INCOMPLETE"))

        status_icons = {
            "VERIFIED": "✓",
            "APPROVED": "✓",
            "RETRY_LIMIT_REACHED": "✕",
            "MANUAL_REVIEW_REQUIRED_DOCUMENTATION": "!",
            "MANUAL_REVIEW_REQUIRED_TESTING": "!",
            "NOT_RUN": "–",
            "INCOMPLETE": "!",
        }

        def status_class(value: str) -> str:
            if value in {"VERIFIED", "APPROVED"}:
                return "ok"
            if value in {
                "RETRY_LIMIT_REACHED",
                "MANUAL_REVIEW_REQUIRED_DOCUMENTATION",
                "MANUAL_REVIEW_REQUIRED_TESTING",
            }:
                return "bad"
            if value == "INCOMPLETE":
                return "warn"
            return "neutral"

        doc_status = str(doc.get("final_status", "NOT_RUN"))
        test_status = str(test.get("final_status", "NOT_RUN"))
        doc_areas = doc.get("areas_requiring_manual_review", []) or []
        test_areas = test.get("areas_requiring_manual_review", []) or []
        test_summary = test.get("summary", {}) or {}

        st.markdown(
            """
            <style>
            .block-container {
                max-width: 1500px;
                padding-top: 1rem;
                padding-bottom: 0.5rem;
                padding-left: 2rem;
                padding-right: 2rem;
            }

            header[data-testid="stHeader"] {
                height: 0;
            }

            h1 {
                font-size: 2rem !important;
                margin: 0 0 0.15rem 0 !important;
            }

            h2 {
                font-size: 1.15rem !important;
                margin: 0.25rem 0 0.35rem 0 !important;
            }

            h3 {
                font-size: 0.95rem !important;
                margin: 0.15rem 0 0.25rem 0 !important;
            }

            [data-testid="stMetric"] {
                padding: 0.35rem 0.55rem;
            }

            [data-testid="stMetricLabel"] {
                font-size: 0.75rem !important;
            }

            [data-testid="stMetricValue"] {
                font-size: 1.35rem !important;
            }

            .dashboard-meta {
                color: #6b7280;
                font-size: 0.78rem;
                margin-bottom: 0.55rem;
            }

            .status-card {
                border: 1px solid #d9dee7;
                border-radius: 10px;
                padding: 0.7rem 0.9rem;
                background: #ffffff;
                height: 100%;
            }

            .status-title {
                font-size: 0.78rem;
                color: #6b7280;
                margin-bottom: 0.15rem;
            }

            .status-value {
                font-size: 1.05rem;
                font-weight: 600;
            }

            .ok { color: #16803c; }
            .bad { color: #b42318; }
            .warn { color: #b54708; }
            .neutral { color: #6b7280; }

            .review-count {
                font-size: 0.8rem;
                color: #6b7280;
                margin: 0.25rem 0 0.4rem 0;
            }

            .review-item {
                border-top: 1px solid #edf0f4;
                padding: 0.35rem 0;
                font-size: 0.75rem;
                line-height: 1.25;
            }

            .footer-note {
                color: #6b7280;
                font-size: 0.72rem;
                margin-top: 0.35rem;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        # Single dashboard title; the problem statement is not repeated.
        st.title("Legacy Modernization Dashboard")
        st.markdown(
            f'<div class="dashboard-meta">Run: '
            f'{html.escape(str(report.get("run_id", "")))}'
            f' &nbsp;|&nbsp; Generated: '
            f'{html.escape(str(report.get("generated_at", "")))}</div>',
            unsafe_allow_html=True,
        )

        # The modernization flow described in the problem statement is shown
        # as a compact visual pipeline. No new pipeline behavior is introduced.

        top1, top2, top3 = st.columns([1.2, 1, 1])

        with top1:
            st.markdown(
                f"""
                <div class="status-card">
                    <div class="status-title">Overall Pipeline Status</div>
                    <div class="status-value {status_class(overall)}">
                        {status_icons.get(overall, "•")} {html.escape(overall)}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with top2:
            st.markdown(
                f"""
                <div class="status-card">
                    <div class="status-title">Documentation Quality Gate</div>
                    <div class="status-value {status_class(doc_status)}">
                        {status_icons.get(doc_status, "•")}
                        {html.escape(doc_status)}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with top3:
            st.markdown(
                f"""
                <div class="status-card">
                    <div class="status-title">Testing Quality Gate</div>
                    <div class="status-value {status_class(test_status)}">
                        {status_icons.get(test_status, "•")}
                        {html.escape(test_status)}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        left, right = st.columns(2)

        with left:
            with st.container(border=True):
                st.markdown("### Documentation Review")

                d1, d2, d3 = st.columns(3)
                d1.metric("Score", doc.get("final_score", "-"))
                d2.metric("Threshold", doc.get("threshold", "-"))
                d3.metric(
                    "Retries",
                    f"{doc.get('retries_used', 0)}/{doc.get('max_retries', 0)}",
                )

                if doc_areas:
                    st.markdown(
                        f'<div class="review-count">'
                        f'{len(doc_areas)} area(s) require manual cross-check</div>',
                        unsafe_allow_html=True,
                    )

                    for item in doc_areas[:3]:
                        location = item.get("source_location") or {}
                        file_name = location.get("file", "")
                        failure = item.get("failure_category", "")
                        rule = item.get("missing_rule_description", "")

                        st.markdown(
                            f'<div class="review-item">'
                            f'<b>{html.escape(str(file_name))}</b> — '
                            f'{html.escape(str(failure))}<br>'
                            f'{html.escape(str(rule))}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                    if len(doc_areas) > 3:
                        st.caption(
                            f"{len(doc_areas) - 3} additional item(s) are in "
                            "the generated dashboard report."
                        )
                else:
                    st.success("No documentation areas pending manual review.")

        with right:
            with st.container(border=True):
                st.markdown("### Testing Review")

                t1, t2, t3 = st.columns(3)
                t1.metric("Pass rate %", test_summary.get("pass_rate", "-"))
                t2.metric("Failed", test_summary.get("failed", "-"))
                t3.metric(
                    "Retries",
                    f"{test.get('retries_used', 0)}/{test.get('max_retries', 0)}",
                )

                if test_areas:
                    st.markdown(
                        f'<div class="review-count">'
                        f'{len(test_areas)} test(s) require manual review</div>',
                        unsafe_allow_html=True,
                    )

                    for item in test_areas[:3]:
                        test_name = item.get("test_name", "")
                        outcome = item.get("outcome", "")
                        message = item.get("stderr") or item.get("message") or ""

                        st.markdown(
                            f'<div class="review-item">'
                            f'<b>{html.escape(str(test_name))}</b> — '
                            f'{html.escape(str(outcome))}<br>'
                            f'{html.escape(str(message))}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                    if len(test_areas) > 3:
                        st.caption(
                            f"{len(test_areas) - 3} additional item(s) are in "
                            "the generated dashboard report."
                        )
                else:
                    st.success("No test failures pending manual review.")

                execution_error = test.get("execution_error")
                if execution_error:
                    st.error(f"Testing execution error: {execution_error}")

        st.markdown(
            '<div class="footer-note">'
            'The complete machine-readable report remains available in '
            'outputs/dashboard/dashboard_report.json.'
            '</div>',
            unsafe_allow_html=True,
        )

    @classmethod
    def run_ui(
        cls,
        report_path: str | Path = "outputs/dashboard/dashboard_report.json",
    ) -> None:
        """
        Streamlit entry point.

        The normal pipeline continues to write:
            outputs/dashboard/dashboard_report.json
            outputs/dashboard/dashboard.html

        The UI reads the JSON report and displays it on screen.
        """
        if st is None:
            raise RuntimeError(
                "Streamlit is required for the dashboard UI. "
                "Install it with: pip install streamlit"
            )

        st.set_page_config(
            page_title="Legacy Modernization Dashboard",
            page_icon="📊",
            layout="wide",
            initial_sidebar_state="collapsed",
        )

        report_file = Path(report_path)

        if not report_file.exists():
            st.title("Legacy Modernization Dashboard")
            st.warning(
                f"No dashboard report found at: {report_file}. "
                "Run the modernization pipeline first so the dashboard "
                "report can be generated."
            )
            return

        try:
            report = json.loads(
                report_file.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            st.title("Legacy Modernization Dashboard")
            st.error(f"Unable to read dashboard report: {exc}")
            return

        cls().render_ui(report)

    # ------------------------------------------------------------------
    # HTML rendering (self-contained, no external assets/network)
    # ------------------------------------------------------------------

    def _render_html(self, report: dict[str, Any]) -> str:
        doc = report["documentation_quality_gate"]
        test = report["testing_quality_gate"]
        overall = report["overall_pipeline_status"]

        status_colors = {
            "VERIFIED": "#1a7f37",
            "APPROVED": "#1a7f37",
            "RETRY_LIMIT_REACHED": "#b42318",
            "MANUAL_REVIEW_REQUIRED_DOCUMENTATION": "#b42318",
            "MANUAL_REVIEW_REQUIRED_TESTING": "#b42318",
            "NOT_RUN": "#6b7280",
            "INCOMPLETE": "#b54708",
        }

        def status_badge(value: str) -> str:
            color = status_colors.get(value, "#6b7280")
            return (
                f'<span style="background:{color};color:#fff;'
                f'padding:2px 10px;border-radius:12px;font-size:13px;">'
                f"{html.escape(value)}</span>"
            )

        def doc_rows() -> str:
            areas = doc.get("areas_requiring_manual_review", [])
            if not areas:
                return (
                    '<tr><td colspan="5" style="color:#6b7280;">'
                    "No documentation areas pending manual review."
                    "</td></tr>"
                )
            rows = []
            for item in areas:
                location = item.get("source_location") or {}
                rows.append(
                    "<tr>"
                    f"<td>{html.escape(str(item.get('ast_node_id', '')))}</td>"
                    f"<td>{html.escape(str(location.get('file', '')))}</td>"
                    f"<td>{html.escape(str(item.get('failure_category', '')))}</td>"
                    f"<td>{html.escape(str(item.get('missing_rule_description', '')))}</td>"
                    "<td><pre style=\"white-space:pre-wrap;margin:0;\">"
                    f"{html.escape(str(item.get('legacy_code_snippet', '')))}"
                    "</pre></td>"
                    "</tr>"
                )
            return "".join(rows)

        def test_rows() -> str:
            areas = test.get("areas_requiring_manual_review", [])
            if not areas:
                return (
                    '<tr><td colspan="3" style="color:#6b7280;">'
                    "No test failures pending manual review."
                    "</td></tr>"
                )
            rows = []
            for item in areas:
                rows.append(
                    "<tr>"
                    f"<td>{html.escape(str(item.get('test_name', '')))}</td>"
                    f"<td>{html.escape(str(item.get('outcome', '')))}</td>"
                    "<td><pre style=\"white-space:pre-wrap;margin:0;\">"
                    f"{html.escape(str(item.get('stderr') or item.get('message') or ''))}"
                    "</pre></td>"
                    "</tr>"
                )
            return "".join(rows)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Legacy Modernization Pipeline Dashboard</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 32px; color: #1f2328; background: #f6f8fa; }}
  h1 {{ margin-bottom: 4px; }}
  .meta {{ color: #6b7280; margin-bottom: 24px; }}
  .card {{ background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 20px; margin-bottom: 24px; }}
  .card h2 {{ margin-top: 0; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #e5e7eb; vertical-align: top; font-size: 13px; }}
  th {{ background: #f6f8fa; }}
  .stat {{ display: inline-block; margin-right: 24px; }}
  .stat b {{ display: block; font-size: 20px; }}
</style>
</head>
<body>
  <h1>Legacy Modernization Pipeline Dashboard</h1>
  <div class="meta">
    Run: {html.escape(str(report.get('run_id', '')))} &middot;
    Generated: {html.escape(str(report.get('generated_at', '')))} &middot;
    Overall status: {status_badge(overall)}
  </div>

  <div class="card">
    <h2>Documentation Quality Gate (Agent 3 &rarr; Agent 2 loop) {status_badge(doc.get('final_status', 'NOT_RUN'))}</h2>
    <div>
      <div class="stat"><b>{doc.get('final_score')}</b>Score</div>
      <div class="stat"><b>{doc.get('threshold')}</b>Threshold</div>
      <div class="stat"><b>{doc.get('retries_used')}/{doc.get('max_retries')}</b>Retries used</div>
    </div>
    <h3>Areas requiring manual cross-check</h3>
    <table>
      <thead><tr><th>AST Node</th><th>File</th><th>Failure category</th><th>Missing rule</th><th>Legacy snippet</th></tr></thead>
      <tbody>{doc_rows()}</tbody>
    </table>
  </div>

  <div class="card">
    <h2>Testing Quality Gate (Agent 5 &rarr; Agent 4 loop) {status_badge(test.get('final_status', 'NOT_RUN'))}</h2>
    <div>
      <div class="stat"><b>{(test.get('summary') or {}).get('pass_rate', '-')}</b>Pass rate %</div>
      <div class="stat"><b>{(test.get('summary') or {}).get('failed', '-')}</b>Failed</div>
      <div class="stat"><b>{test.get('retries_used')}/{test.get('max_retries')}</b>Retries used</div>
    </div>
    <h3>Failing tests requiring manual review</h3>
    <table>
      <thead><tr><th>Test</th><th>Outcome</th><th>stderr / message</th></tr></thead>
      <tbody>{test_rows()}</tbody>
    </table>
  </div>
</body>
</html>
"""


__all__ = ["DashboardBuilder"]


if __name__ == "__main__":
    DashboardBuilder.run_ui()
