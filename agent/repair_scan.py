from __future__ import annotations

import base64
import os
import subprocess
import sys
import time
from typing import Any

import jwt
import requests

GITHUB_API = "https://api.github.com"
MARKER = "<!-- ishbounty-repair-attempt -->"
MAX_ATTEMPTS = max(1, int(os.getenv("ISHB_AGENT_MAX_REPAIR_ATTEMPTS", "3")))
_app_token: tuple[str, float] | None = None
_current_repo = os.getenv("ISHB_AGENT_DISCOVERY_REPO", "")


def target_repo() -> str:
    if not _current_repo:
        raise RuntimeError("target repository context is not initialized")
    return _current_repo


def token() -> str:
    global _app_token
    app_id = os.getenv("ISHB_GITHUB_APP_ID")
    private_key = os.getenv("ISHB_GITHUB_APP_PRIVATE_KEY")
    if not app_id or not private_key:
        return os.environ["ISHB_AGENT_TOKEN"]
    now = int(time.time())
    if _app_token and _app_token[1] > now + 60:
        return _app_token[0]
    key = private_key.replace("\\n", "\n")
    assertion = jwt.encode({"iat": now - 30, "exp": now + 540, "iss": str(app_id)}, key, algorithm="RS256")
    response = requests.get(
        f"{GITHUB_API}/repos/{target_repo()}/installation",
        headers={"Authorization": f"Bearer {assertion}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        timeout=30,
    )
    response.raise_for_status()
    installation_id = response.json()["id"]
    response = requests.post(
        f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
        headers={"Authorization": f"Bearer {assertion}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        json={},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    _app_token = (data["token"], float(time.time() + 3300))
    return _app_token[0]


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def gh(method: str, url: str, **kwargs: Any) -> Any:
    response = requests.request(method, url, headers=headers(), timeout=30, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def open_agent_prs() -> list[dict[str, Any]]:
    data = gh("GET", f"{GITHUB_API}/search/issues", params={"q": "is:pr is:open head:agent/issue-", "per_page": 30})
    return [item for item in data.get("items", []) if "pull_request" in item]


def failed_run(repo: str, sha: str) -> int | None:
    checks = gh("GET", f"{GITHUB_API}/repos/{repo}/commits/{sha}/check-runs", params={"per_page": 100})
    failed_names = {
        check.get("name") for check in checks.get("check_runs", [])
        if check.get("conclusion") in {"failure", "cancelled", "timed_out", "action_required"}
    }
    if not failed_names:
        return None
    runs = gh("GET", f"{GITHUB_API}/repos/{repo}/actions/runs", params={"head_sha": sha, "per_page": 30})
    for run in runs.get("workflow_runs", []):
        if run.get("conclusion") in {"failure", "cancelled", "timed_out"}:
            return int(run["id"])
    return None


def repair_attempts(repo: str, number: int, head_sha: str) -> int:
    comments = gh("GET", f"{GITHUB_API}/repos/{repo}/issues/{number}/comments", params={"per_page": 100})
    prefix = f"{MARKER}\nhead_sha: {head_sha}\n"
    return sum((item.get("body") or "").startswith(prefix) for item in comments)


def mark_attempt(repo: str, number: int, run_id: int, head_sha: str) -> None:
    gh("POST", f"{GITHUB_API}/repos/{repo}/issues/{number}/comments", json={"body": f"{MARKER}\nhead_sha: {head_sha}\nAutomated repair attempt for workflow run `{run_id}`."})


def main() -> int:
    global _current_repo, _app_token
    limit = max(1, int(os.getenv("ISHB_AGENT_MAX_REPAIR_PRS", "5")))
    repaired = 0
    failures = 0
    for item in open_agent_prs()[:limit]:
        repo = item["repository_url"].split("/repos/")[-1]
        _current_repo = repo
        _app_token = None
        number = int(item["number"])
        pr = gh("GET", f"{GITHUB_API}/repos/{repo}/pulls/{number}")
        if pr.get("state") != "open":
            continue
        head_sha = pr["head"]["sha"]
        run_id = failed_run(repo, head_sha)
        if run_id is None or repair_attempts(repo, number, head_sha) >= MAX_ATTEMPTS:
            continue
        mark_attempt(repo, number, run_id, head_sha)
        result = subprocess.run([sys.executable, "agent/repair_agent.py", "--repo", repo, "--pr", str(number), "--run-id", str(run_id)], check=False)
        if result.returncode == 0:
            repaired += 1
        else:
            failures += 1
    return 1 if failures and repaired == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
