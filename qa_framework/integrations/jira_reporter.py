"""JIRA REST API v3 defect triage, ADF payload builder, and deduplicated reporting client."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from qa_framework.reporting.collector import QASuiteSummary


@dataclass(frozen=True)
class JiraConfig:
    """Connection and project configuration for JIRA REST API v3."""

    base_url: str
    user_email: str
    api_token: str
    project_key: str = "AEGISQA"
    issue_type: str = "Bug"

    @classmethod
    def from_env(cls) -> JiraConfig | None:
        base_url = os.getenv("JIRA_BASE_URL", "").strip().rstrip("/")
        user_email = os.getenv("JIRA_USER_EMAIL", "").strip()
        api_token = os.getenv("JIRA_API_TOKEN", "").strip()
        project_key = os.getenv("JIRA_PROJECT_KEY", "AEGISQA").strip()
        if not (base_url and user_email and api_token):
            return None
        return cls(
            base_url=base_url,
            user_email=user_email,
            api_token=api_token,
            project_key=project_key,
        )


@dataclass(frozen=True)
class DefectTicketSpec:
    """Structured defect specification generated from a failed QA check."""

    fingerprint: str
    layer: str
    sublayer: str
    nodeid: str
    priority: str
    summary: str
    reproduction_cmd: str
    environment: dict[str, str]
    failure_excerpt: str
    attachments: tuple[str, ...] = ()


@dataclass(frozen=True)
class JiraSubmissionResult:
    """Result of submitting or dry-running a JIRA defect ticket."""

    fingerprint: str
    issue_key: str
    status: str  # "created" | "deduplicated" | "dry_run"
    payload: dict[str, Any]


def compute_defect_fingerprint(nodeid: str, failure_excerpt: str) -> str:
    """Compute a deterministic 12-char fingerprint to deduplicate recurring CI failures."""
    first_line = failure_excerpt.strip().splitlines()[0] if failure_excerpt.strip() else "unknown"
    raw = f"{nodeid}::{first_line[:160]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def infer_priority(layer: str, failure_excerpt: str) -> str:
    """Map QA layer severity and crash signatures to JIRA priority levels."""
    lowered = failure_excerpt.lower()
    if any(tok in lowered for tok in ("fatal", "conservation", "privilege", "anr")):
        return "Highest"
    if layer.startswith("Layer 1") or layer.startswith("Layer 4"):
        return "Highest"
    if layer.startswith("Layer 2") or layer.startswith("Layer 3"):
        return "High"
    return "Medium"


def build_adf_issue_payload(spec: DefectTicketSpec, *, project_key: str) -> dict[str, Any]:
    """Construct a valid JIRA REST v3 Atlassian Document Format (ADF) create-issue body."""
    env_lines = "\n".join(f"{k}: {v}" for k, v in sorted(spec.environment.items()))
    return {
        "fields": {
            "project": {"key": project_key},
            "summary": spec.summary[:240],
            "issuetype": {"name": "Bug"},
            "priority": {"name": spec.priority},
            "labels": [
                "qa-automation",
                f"fp-{spec.fingerprint}",
                spec.layer.split(":")[0].lower().replace(" ", "-"),
            ],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "heading",
                        "attrs": {"level": 3},
                        "content": [{"type": "text", "text": "Automated QA Failure Report"}],
                    },
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": f"Layer: {spec.layer} ({spec.sublayer})\n"},
                            {"type": "text", "text": f"Node ID: {spec.nodeid}\n"},
                            {"type": "text", "text": f"Fingerprint: qa-{spec.fingerprint}"},
                        ],
                    },
                    {
                        "type": "heading",
                        "attrs": {"level": 4},
                        "content": [{"type": "text", "text": "Reproduction Command"}],
                    },
                    {
                        "type": "codeBlock",
                        "attrs": {"language": "bash"},
                        "content": [{"type": "text", "text": spec.reproduction_cmd}],
                    },
                    {
                        "type": "heading",
                        "attrs": {"level": 4},
                        "content": [{"type": "text", "text": "Observed Failure & Environment"}],
                    },
                    {
                        "type": "codeBlock",
                        "attrs": {"language": "text"},
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"{spec.failure_excerpt.strip()}\n\n--- ENV ---\n{env_lines}"
                                ),
                            }
                        ],
                    },
                ],
            },
        }
    }


class JiraDefectClient:
    """JIRA Cloud REST v3 client with fingerprint deduplication and dry-run export."""

    def __init__(
        self,
        config: JiraConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._client = httpx.Client(
            base_url=config.base_url,
            auth=(config.user_email, config.api_token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=15.0,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def find_existing_by_fingerprint(self, fingerprint: str) -> str | None:
        """Query JQL for an open defect matching `fp-<fingerprint>`."""
        jql = (
            f'project = "{self._config.project_key}" '
            f'AND labels = "fp-{fingerprint}" '
            "AND statusCategory != Done"
        )
        resp = self._client.get(
            "/rest/api/3/search/jql",
            params={"jql": jql, "maxResults": 1, "fields": "key"},
        )
        resp.raise_for_status()
        issues = resp.json().get("issues", [])
        if issues:
            return str(issues[0]["key"])
        return None

    def attach_files(self, issue_key: str, file_paths: tuple[str, ...]) -> list[str]:
        """Upload screenshot or logcat attachments to an existing JIRA issue."""
        uploaded: list[str] = []
        for raw_path in file_paths:
            path = Path(raw_path)
            if not path.is_file():
                continue
            with path.open("rb") as fh:
                resp = self._client.post(
                    f"/rest/api/3/issue/{issue_key}/attachments",
                    headers={"X-Atlassian-Token": "no-check"},
                    files={"file": (path.name, fh, "application/octet-stream")},
                )
            resp.raise_for_status()
            uploaded.append(path.name)
        return uploaded

    def submit_defect(
        self,
        spec: DefectTicketSpec,
        *,
        dry_run: bool = False,
    ) -> JiraSubmissionResult:
        payload = build_adf_issue_payload(spec, project_key=self._config.project_key)
        if dry_run:
            return JiraSubmissionResult(
                fingerprint=spec.fingerprint,
                issue_key=f"{self._config.project_key}-DRY-{spec.fingerprint[:6].upper()}",
                status="dry_run",
                payload=payload,
            )

        existing = self.find_existing_by_fingerprint(spec.fingerprint)
        if existing is not None:
            return JiraSubmissionResult(
                fingerprint=spec.fingerprint,
                issue_key=existing,
                status="deduplicated",
                payload=payload,
            )

        create_resp = self._client.post("/rest/api/3/issue", json=payload)
        create_resp.raise_for_status()
        issue_key = str(create_resp.json()["key"])
        if spec.attachments:
            self.attach_files(issue_key, spec.attachments)

        return JiraSubmissionResult(
            fingerprint=spec.fingerprint,
            issue_key=issue_key,
            status="created",
            payload=payload,
        )


def build_defects_from_summary(
    summary: QASuiteSummary,
    *,
    environment: dict[str, str] | None = None,
    attachments: tuple[str, ...] = (),
) -> list[DefectTicketSpec]:
    """Convert any failed test cases in a QASuiteSummary into DefectTicketSpec items."""
    env = environment or {"qa_suite_wall_s": f"{summary.wall_duration_s:.3f}"}
    specs: list[DefectTicketSpec] = []
    for tc in summary.tests:
        if tc.outcome not in ("failed", "error"):
            continue
        excerpt = f"Test {tc.nodeid} exited with outcome={tc.outcome} ({tc.duration_ms:.2f} ms)"
        fp = compute_defect_fingerprint(tc.nodeid, excerpt)
        specs.append(
            DefectTicketSpec(
                fingerprint=fp,
                layer=tc.layer,
                sublayer=tc.sublayer,
                nodeid=tc.nodeid,
                priority=infer_priority(tc.layer, excerpt),
                summary=f"[QA][{tc.layer}] Failure in {tc.nodeid.split('::')[-1]}",
                reproduction_cmd=f"pytest {tc.nodeid} -v",
                environment=env,
                failure_excerpt=excerpt,
                attachments=attachments,
            )
        )
    return specs


def export_dry_run_defects(
    results: list[JiraSubmissionResult],
    output_path: Path,
) -> None:
    """Persist structured JIRA dry-run payloads for CI triage inspection."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = [asdict(r) for r in results]
    output_path.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
