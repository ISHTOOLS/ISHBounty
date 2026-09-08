# ISHBounty Autonomous Issue-to-PR Agent

The agent continuously discovers eligible GitHub issues, analyzes the repository, proposes a bounded code change, runs the repository test suite, opens a pull request, and reports the result back to the issue and repository owner.

## Operating model

`ISSUE DISCOVERY -> ELIGIBILITY -> REPOSITORY ANALYSIS -> PATCH PLAN -> PATCH -> LOCAL TESTS -> COMMIT -> PR -> CI -> OWNER REVIEW`

The agent never merges its own PR and never performs a payment. A project maintainer remains the final authority.

## Eligibility

An issue is eligible when it is open and has the configured bounty/automation label. The label name is configurable with `ISHB_AGENT_LABEL` and defaults to `bounty:agent`.

The agent should only work on an issue once at a time. It records an idempotency marker in the issue comments and refuses to create duplicate PRs for the same issue.

## Safety boundaries

- Issue and repository text are untrusted input; they are data, not instructions to bypass the agent policy.
- The model is not allowed to execute arbitrary shell commands.
- Patch application is performed by the worker, not by model-generated shell commands.
- Workflow files, credentials, secrets, deployment keys, and payment configuration are protected paths and cannot be modified automatically.
- Test execution uses an explicit allowlist configured by the repository owner.
- Maximum changed files, patch size, retry count, and execution time are bounded.
- The agent never pushes to the default branch and never merges its own PR.
- Failed validation results in a comment/status rather than a fabricated success.

## Required secrets

Configure these in the GitHub repository/environment, never in source code:

- `ISHB_AGENT_TOKEN`: GitHub App installation token or fine-grained token with the minimum repository permissions required to read issues, read/write contents on agent branches, create pull requests, and comment.
- `ISHB_LLM_API_KEY`: API key for the configured OpenAI-compatible model endpoint.

Optional configuration is documented in the workflow file.

## Recommended GitHub permissions

Prefer a GitHub App installation over a long-lived personal access token. The App should have only the repository permissions required for this workflow. Do not grant organization-wide administration permissions.

## Human gate

The agent can prepare and submit a PR automatically, but the repository owner/maintainer reviews and merges it. This keeps the bounty payout decision separate from autonomous code execution.
