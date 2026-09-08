from __future__ import annotations

import os
import subprocess
from typing import Any

import requests

API = "https://api.github.com"


def headers() -> dict[str, str]:
    token = os.environ["ISHB_AGENT_TOKEN"]
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def get(url: str, **kwargs: Any) -> Any:
    r = requests.get(url, headers=headers(), timeout=30, **kwargs)
    r.raise_for_status()
    return r.json()


def main() -> int:
    query = "is:pr is:open head:agent/issue-"
    data = get(f"{API}/search/issues", params={"q": query, "per_page": 30, "sort": "updated", "order": "desc"})
    max_prs = int(os.getenv("ISHB_AGENT_MAX_REPAIR_PRS", "5"))
    repaired = 0
    for item in data.get("items", [])[:max_prs]:
        repo_url = item.get("repository_url", "")
        repo = repo_url.split("/repos/")[-1]
        if not repo:
            continue
        pr = get(f"{API}/repos/{repo}/pulls/{item['number']}")
        if pr.get("state") != "open" or not pr.get("head", {}).get("ref", "").startswith("agent/issue-"):
            continue
        sha = pr["head"]["sha"]
        runs = get(f"{API}/repos/{repo}/commits/{sha}/check-runs", params={"per_page": 100}).get("check_runs", [])
        failed = [x for x in runs if x.get("status") == "completed" and x.get("conclusion") in {"failure", "timed_out", "cancelled"}]
        if not failed:
            continue
        run_id = failed[0].get("check_suite", {}).get("id")
        # check_suite.id is not a workflow-run id; resolve workflow runs for the commit instead.
        workflow_runs = get(f"{API}/repos/{repo}/actions/runs", params={"head_sha": sha, "per_page": 100}).get("workflow_runs", [])
        failed_runs = [r for r in workflow_runs if r.get("status") == "completed" and r.get("conclusion") in {"failure", "timed_out", "cancelled"}]
        if not failed_runs:
            continue
        run_id = failed_runs[0]["id"]
        env = os.environ.copy()
        env["ISHB_REPAIR_REPO"] = repo
        env["ISHB_REPAIR_PR"] = str(item["number"])
        env["ISHB_REPAIR_RUN_ID"] = str(run_id)
        subprocess.run(["python", "agent/repair_agent.py", "--repo", repo, "--pr", str(item["number"]), "--run-id", str(run_id)], check=False, env=env, timeout=1800)
        repaired += 1
    return 0 if repaired >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
