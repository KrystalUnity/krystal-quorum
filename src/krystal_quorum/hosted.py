from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from textwrap import shorten
from typing import Any

import httpx

from krystal_quorum import __version__
from krystal_quorum.persist import plan_sha256

HOSTED_PACKS = {"quick", "standard", "council"}
TERMINAL_STATUSES = {"completed", "degraded", "failed_no_charge", "failed"}


class HostedReviewError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        response: dict[str, Any] | None = None,
        run_dir: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.response = response
        self.run_dir = run_dir


def hosted_pack_from_reviewers(reviewers: str) -> str | None:
    parts = [part.strip() for part in reviewers.split(",") if part.strip()]
    hosted = [part for part in parts if part.lower().startswith("hosted:")]
    if not hosted:
        return None
    if len(parts) != 1:
        raise HostedReviewError("hosted reviewers cannot be mixed with local reviewers")
    pack = hosted[0].split(":", 1)[1].strip().lower()
    if pack not in HOSTED_PACKS:
        raise HostedReviewError(f"unknown hosted review pack: hosted:{pack}")
    return pack


def client_version() -> str:
    return f"krystal-quorum/{__version__}"


def run_hosted_review(
    *,
    plan_path: Path,
    plan_text: str,
    pack_key: str,
    out_dir: Path,
    api_token: str,
    api_base_url: str | None,
    poll_interval_s: float = 2.0,
    timeout_s: float = 1800.0,
) -> tuple[dict[str, Any], Path]:
    base_url = (
        api_base_url or os.getenv("KRYSTAL_QUORUM_API_BASE") or "https://krystalunity.com"
    ).rstrip("/")
    headers = {"Authorization": f"Bearer {api_token}"}
    request_payload = {
        "plan_markdown": plan_text,
        "pack_key": pack_key,
        "source": "cli",
        "client_version": client_version(),
    }

    with httpx.Client(timeout=30.0) as client:
        try:
            response = client.post(
                f"{base_url}/api/quorum/reviews", headers=headers, json=request_payload
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HostedReviewError(f"hosted review request failed: {exc}") from exc
        current = response.json()
        deadline = time.monotonic() + timeout_s
        while str(current.get("status") or "") not in TERMINAL_STATUSES:
            if time.monotonic() >= deadline:
                raise HostedReviewError("hosted review timed out")
            time.sleep(poll_interval_s)
            poll_url = _absolute_url(base_url, str(current.get("poll_url") or ""))
            try:
                response = client.get(poll_url, headers=headers)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise HostedReviewError(f"hosted review poll failed: {exc}") from exc
            current = response.json()

    status = str(current.get("status") or "")
    if status in {"failed", "failed_no_charge"}:
        run_dir = _persist_hosted_response(
            out_dir=out_dir,
            plan_path=plan_path,
            plan_text=plan_text,
            response=current,
        )
        message = str(current.get("error") or "hosted review failed")
        if status == "failed_no_charge":
            message = f"{message}\nNo credits were charged."
        message = f"{message}\nArtifacts: {run_dir}"
        raise HostedReviewError(message, response=current, run_dir=run_dir)
    run_dir = _persist_hosted_response(
        out_dir=out_dir, plan_path=plan_path, plan_text=plan_text, response=current
    )
    return current, run_dir


def hosted_json_output(response: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    reconciled = response.get("reconciled") if isinstance(response.get("reconciled"), dict) else {}
    return {
        "schema_version": reconciled.get("schema_version") or "ku-quorum-hosted.v1",
        "verdict": response.get("verdict") or reconciled.get("merged_verdict") or "ABSTAIN",
        "confidence": response.get("confidence") or reconciled.get("confidence") or 0,
        "reviewers_used": response.get("reviewers") or reconciled.get("reviewers_used") or [],
        "status": response.get("status"),
        "hosted": True,
        "output_dir": str(run_dir),
        "credits_charged": response.get("credits_charged"),
        "credits_remaining": response.get("credits_remaining"),
    }


def hosted_pretty_output(response: dict[str, Any], run_dir: Path, *, width: int = 78) -> str:
    output = hosted_json_output(response, run_dir)
    reconciled = response.get("reconciled") if isinstance(response.get("reconciled"), dict) else {}
    verdict = str(output["verdict"])
    confidence = _as_float(output.get("confidence"))
    reviewers = output.get("reviewers_used") or ["hosted"]
    status = str(output.get("status") or "unknown")
    abstained = _string_list(reconciled.get("abstained_reviewers"))
    unresolved = _string_list(reconciled.get("unresolved_for_human"))

    lines = [
        _rule("Krystal Quorum Hosted", width),
        f"VERDICT: {verdict} | Confidence: {confidence:.2f}",
        f"Reviewers: {', '.join(str(reviewer) for reviewer in reviewers)}",
        f"Status: {status}",
    ]
    credits = _credits_line(output)
    if credits:
        lines.append(credits)
    if abstained:
        lines.append(f"Abstained: {', '.join(abstained)}")

    lines.extend(["", _section("Human Triage", len(unresolved))])
    if unresolved:
        for item in unresolved:
            lines.append("- " + shorten(item, width=max(20, width - 2), placeholder="..."))
    else:
        lines.append("- none")

    lines.extend(["", f"Artifacts: {run_dir}", _rule("", width)])
    return "\n".join(lines)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _credits_line(output: dict[str, Any]) -> str:
    charged = output.get("credits_charged")
    remaining = output.get("credits_remaining")
    if charged is None and remaining is None:
        return ""
    if charged is None:
        return f"Credits: remaining {remaining}"
    if remaining is None:
        return f"Credits: charged {charged}"
    return f"Credits: charged {charged}, remaining {remaining}"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _section(label: str, count: int) -> str:
    return f"{label} ({count})"


def _rule(title: str, width: int) -> str:
    if not title:
        return "+" + "-" * (width - 2) + "+"
    label = f" {title} "
    remaining = max(0, width - 2 - len(label))
    return "+" + label + "-" * remaining + "+"


def _absolute_url(base_url: str, poll_url: str) -> str:
    if poll_url.startswith(("http://", "https://")):
        return poll_url
    if not poll_url.startswith("/"):
        poll_url = f"/{poll_url}"
    return f"{base_url}{poll_url}"


def _persist_hosted_response(
    *,
    out_dir: Path,
    plan_path: Path,
    plan_text: str,
    response: dict[str, Any],
) -> Path:
    run_dir = _run_dir(out_dir, plan_path)
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "plan_input.md").write_text(plan_text, encoding="utf-8")
    (run_dir / "plan_input.sha256").write_text(f"{plan_sha256(plan_text)}\n", encoding="utf-8")
    (run_dir / "hosted-response.json").write_text(json.dumps(response, indent=2), encoding="utf-8")

    reconciled = response.get("reconciled")
    if isinstance(reconciled, dict):
        (run_dir / "reconciled.json").write_text(json.dumps(reconciled, indent=2), encoding="utf-8")
    else:
        (run_dir / "reconciled.json").write_text(json.dumps(response, indent=2), encoding="utf-8")

    wrote_summary = False
    for artifact in response.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        name = _safe_artifact_name(str(artifact.get("name") or "artifact.json"))
        content = str(artifact.get("content") or "")
        path = run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        wrote_summary = wrote_summary or name == "summary.md"

    if not wrote_summary:
        summary = response.get("summary") or f"Hosted review verdict: {response.get('verdict', 'ABSTAIN')}\n"
        (run_dir / "summary.md").write_text(str(summary), encoding="utf-8")
    return run_dir


def _run_dir(out_dir: Path, plan_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    stem = plan_path.stem or "plan"
    candidate = out_dir / f"{stem}_{stamp}"
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = out_dir / f"{stem}_{stamp}_{suffix}"
    return candidate


def _safe_artifact_name(name: str) -> str:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise HostedReviewError(f"unsafe hosted artifact path: {name}")
    cleaned = path.as_posix().strip("/")
    return cleaned or "artifact.json"
