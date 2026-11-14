"""Tests for JIRA REST API v3 defect triage, ADF payload builder, and deduplication."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from qa_framework.integrations.jira_reporter import (
    JiraConfig,
    JiraDefectClient,
    build_defects_from_summary,
    export_dry_run_defects,
)
from qa_framework.reporting.collector import LayerSummary, QASuiteSummary, TestCaseTelemetry

pytestmark = pytest.mark.api


def _sample_failed_summary() -> QASuiteSummary:
    return QASuiteSummary(
        generated_at_utc="2026-11-13T21:30:00+00:00",
        total_tests=2,
        passed=1,
        failed=1,
        skipped=0,
        pass_rate_pct=50.0,
        wall_duration_s=1.25,
        layers=[
            LayerSummary(
                layer="Layer 1: API & Property",
                total=2,
                passed=1,
                failed=1,
                skipped=0,
                pass_rate_pct=50.0,
                total_duration_ms=42.0,
                p50_ms=21.0,
                p95_ms=39.9,
                max_ms=40.0,
            )
        ],
        tests=[
            TestCaseTelemetry(
                nodeid="tests/api/test_auth_rbac.py::test_register_login_and_me_lifecycle",
                layer="Layer 1: API & Property",
                sublayer="API Contract & RBAC",
                outcome="passed",
                duration_ms=2.0,
            ),
            TestCaseTelemetry(
                nodeid="tests/api/test_orders_idempotency.py::test_idempotency_key_replay_and_conflict",
                layer="Layer 1: API & Property",
                sublayer="API Contract & RBAC",
                outcome="failed",
                duration_ms=40.0,
            ),
        ],
    )


def test_jira_dry_run_builds_valid_adf_and_exports_json(tmp_path: Path) -> None:
    summary = _sample_failed_summary()
    specs = build_defects_from_summary(
        summary,
        environment={"os": "Windows-11", "qa_mobile_mode": "mock"},
    )
    assert len(specs) == 1
    spec = specs[0]
    assert spec.priority == "Highest"
    assert len(spec.fingerprint) == 12

    cfg = JiraConfig(
        base_url="https://example.atlassian.net",
        user_email="qa@aegispay.dev",
        api_token="mock-token",
        project_key="AEGIS",
    )
    client = JiraDefectClient(cfg)
    try:
        result = client.submit_defect(spec, dry_run=True)
    finally:
        client.close()

    assert result.status == "dry_run"
    assert result.issue_key.startswith("AEGIS-DRY-")
    assert result.payload["fields"]["description"]["type"] == "doc"
    assert result.payload["fields"]["description"]["version"] == 1

    out_file = tmp_path / "jira-defects.json"
    export_dry_run_defects([result], out_file)
    loaded = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(loaded) == 1
    assert loaded[0]["issue_key"] == result.issue_key


def test_jira_client_creates_and_deduplicates_via_mock_transport(tmp_path: Path) -> None:
    attachment = tmp_path / "failure.png"
    attachment.write_bytes(b"\x89PNG\r\n\x1a\n")

    seen_requests: list[tuple[str, str]] = []
    search_hits: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append((request.method, request.url.path))
        if request.url.path == "/rest/api/3/search/jql":
            return httpx.Response(200, json={"issues": search_hits})
        if request.url.path == "/rest/api/3/issue":
            return httpx.Response(201, json={"key": "AEGIS-402"})
        if request.url.path == "/rest/api/3/issue/AEGIS-402/attachments":
            return httpx.Response(200, json=[{"id": "1001", "filename": "failure.png"}])
        return httpx.Response(404)

    cfg = JiraConfig(
        base_url="https://example.atlassian.net",
        user_email="qa@aegispay.dev",
        api_token="mock-token",
        project_key="AEGIS",
    )
    spec = build_defects_from_summary(
        _sample_failed_summary(),
        attachments=(str(attachment),),
    )[0]

    client = JiraDefectClient(cfg, transport=httpx.MockTransport(handler))
    try:
        created = client.submit_defect(spec, dry_run=False)
        assert created.status == "created"
        assert created.issue_key == "AEGIS-402"

        # Simulate open issue now returned by JQL search on second CI run
        search_hits.append({"key": "AEGIS-402"})
        deduped = client.submit_defect(spec, dry_run=False)
        assert deduped.status == "deduplicated"
        assert deduped.issue_key == "AEGIS-402"
    finally:
        client.close()

    assert ("POST", "/rest/api/3/issue") in seen_requests
    assert ("POST", "/rest/api/3/issue/AEGIS-402/attachments") in seen_requests
