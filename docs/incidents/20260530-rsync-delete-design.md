# Incident — DESIGN.md removed during G001 source-doc sync

- Time: 2026-05-30T05:19Z UTC approx.
- Context: Ultragoal G001 copied approved local docs/planning artifacts into `/home/hoddukzoa/GilJob_v2`.
- Incident: pre-sync listing showed `/home/hoddukzoa/GilJob_v2/DESIGN.md`. The sync used `rsync --delete`, which removed files outside the staged docs set, including `DESIGN.md`.
- Recovery status: no backup copy was found under `/home/hoddukzoa` by `find ~ -maxdepth 4 -name DESIGN.md -o -name "*DESIGN*"` except legacy `/home/hoddukzoa/GilJob/_design/CLAUDE_DESIGN_HANDOFF.md`.
- Mitigation: future sync commands for `GilJob_v2` must not use `--delete` unless explicitly scoped to a generated subdirectory and reviewed first.
- Follow-up: if the deleted `DESIGN.md` content is needed, restore from external/user copy before continuing implementation that depends on it.
