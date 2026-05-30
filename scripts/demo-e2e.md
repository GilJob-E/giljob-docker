# Demo E2E Runbook

## Required evidence before demo-ready

1. Public `/healthz` passes; public `/readyz` returns 404; container-internal API `/readyz` passes.
2. Browser joins LiveKit room from normal network.
3. Browser joins LiveKit room from hotspot/external network.
4. Engine participant subscribes to candidate media track.
5. Fake STT, fake Agent1, fake Agent2 complete 3 turns.
6. Report page displays.
7. Logs show each step.
8. coturn allocation evidence is captured when relay fallback is used.

## 3-turn scenario

- Start interview.
- Candidate answers opening question.
- System produces follow-up 1.
- Candidate answers.
- System produces follow-up 2.
- Candidate answers.
- End session and display report.


## Local media room pre-demo smoke

Before the full 3-turn demo exists, run:

```bash
./scripts/smoke.sh config
./scripts/smoke.sh media-up
```

Then, if manual browser evidence is needed, keep the stack with `KEEP_STACK=1`, start Caddy, open the web UI, and join/leave a LiveKit room. This still does not prove CV parsing, Main LLM, multimodal analysis, or final report behavior.
