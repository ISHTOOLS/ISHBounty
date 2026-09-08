from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

import requests

GITHUB_API = "https://api.github.com"


def token() -> str:
    return os.environ["ISHB_AGENT_TOKEN"]


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def gh(method: str, url: str, **kwargs: Any) -> Any:
    response = requests.request(method, url, headers=headers(), timeout=30, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def open_agent_prs() -> list[dict[str, Any]]:
    data = gh(
        "GET",
        f"{GITHUB_API}/search/issues",
        params={"q": "is:pr is:open head:agent/issue-", "per_page": 30},
    )
    return [item for item in data.get("items", []) if "pull_request" in item]


def failed_run(repo: str, sha: str) -> int | None:
    checks = gh("GET", f"{GITHUB_API}/repos/{repo}/commits/{sha}/check-runs", params={"per_page": 100})
    failed_names = {
        check.get("name")
        for check in checks.get("check_runs", [])
        if check.get("conclusion") in {"failure", "cancelled", "timed_out", "action_required"}
    }
    if not failed_names:
        return None
    runs = gh(
        "GET",
        f"{GITHUB_API}/repos/{repo}/actions/runs",
        params={"head_sha": sha, "per_page": 30},
    )
    for run in runs.get("workflow_runs", []):
        if run.get("conclusion") in {"failure", "cancelled", "timed_out"}:
            return int(run["id"])
    return None


def main() -> int:
    limit = max(1, int(os.getenv("ISHB_AGENT_MAX_REPAIR_PRS", "5")))
    repaired = 0
    for item in open_agent_prs()[:limit]:
        repo = item["repository_url"].split("/repos/")[-1]
        number = int(item["number"])
        pr = gh("GET", f"{GITHUB_API}/repos/{repo}/pulls/{number}")
        head_sha = pr["head"]["sha"]
        run_id = failed_run(repo, head_sha)
        if run_id is None:
            continue
        result = subprocess.run(
            [sys.executable, "agent/repair_agent.py", "--repo", repo, "--pr", str(number), "--run-id", str(run_id)],
            check=False,
        )
        if result.returncode == 0:
            repaired += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
