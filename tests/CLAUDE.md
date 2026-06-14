# Claude Notes for tests

Read the local `AGENTS.md` first.

Claude reminders:
- Keep contract tests deterministic and security-focused.
- Do not print secrets or raw tokens in failures.
- Prefer path-specific assertions for documentation contracts.
- For Realtime/MMM contracts, assert route shape and redaction without printing client secrets, SDP, or raw media.
