"""Passive/controlled scanner for explicitly authorized GitHub repositories.

Repositories must be supplied through ISHB_AUTHORIZED_REPOSITORIES as a
comma-separated owner/name allow-list. Findings are created as GitHub issues;
this scanner never exploits, modifies, or executes target code.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import requests

API = "https://api.github.com"


def gh_headers() -> dict[str, str]:
    token = os.environ["ISHB_AGENT_TOKEN"]
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def api_get(url: str):
    response = requests.get(url, headers=gh_headers(), timeout=30)
    response.raise_for_status()
    return response.json()


def issue_exists(repo: str, fingerprint: str) -> bool:
    data = api_get(f"{API}/repos/{repo}/issues",)
    return any(fingerprint in (item.get("body") or "") for item in data if "pull_request" not in item)


def create_issue(repo: str, title: str, body: str) -> None:
    response = requests.post(f"{API}/repos/{repo}/issues", headers=gh_headers(), json={"title": title, "body": body, "labels": ["bounty:agent"]}, timeout=30)
    response.raise_for_status()


def scan(repo: str) -> int:
    with tempfile.TemporaryDirectory(prefix="ishb-scan-") as tmp:
        target = Path(tmp) / repo.replace("/", "-")
        clone_url = f"https://x-access-token:{os.environ['ISHB_AGENT_TOKEN']}@github.com/{repo}.git"
        subprocess.run(["git", "clone", "--depth", "1", clone_url, str(target)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        output = subprocess.run(["semgrep", "scan", "--config", "auto", "--json", "--error", str(target)], capture_output=True, text=True, timeout=900, check=False)
        try:
            report = json.loads(output.stdout or "{}")
        except json.JSONDecodeError:
            return 0
        findings = report.get("results", [])
        created = 0
        for finding in findings[: int(os.getenv("ISHB_MAX_FINDINGS_PER_REPO", "20"))]:
            check = finding.get("check_id", "unknown")
            path = finding.get("path", "unknown")
            line = finding.get("start", {}).get("line", "?")
            fingerprint = f"ISHB-SCAN:{repo}:{check}:{path}:{line}"
            if issue_exists(repo, fingerprint):
                continue
            extra = finding.get("extra", {})
            severity = extra.get("severity", "INFO")
            message = extra.get("message", "Semgrep finding")
            body = f"{fingerprint}\n\nAuthorized passive scan finding.\n\n- Rule: `{check}`\n- Severity: `{severity}`\n- Location: `{path}:{line}`\n- Message: {message}\n\nNo exploit or target modification was performed."
            create_issue(repo, f"[ISHBounty] {severity}: {check}", body)
            created += 1
        return created


def main() -> int:
    repos = [x.strip() for x in os.getenv("ISHB_AUTHORIZED_REPOSITORIES", "").split(",") if x.strip()]
    if not repos:
        return 0
    for repo in repos:
        if not repo.count("/") == 1:
            raise SystemExit(f"invalid authorized repository: {repo}")
        scan(repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
