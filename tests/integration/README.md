# tests/integration

Integration tests for GilJob v2 are not yet a full production e2e suite. Current reliable runtime coverage lives mostly in:

- `tests/contract/` for API/web/provider/ingress contracts.
- `scripts/smoke.sh config` for compose rendering checks.
- `scripts/smoke.sh media-up` for local LiveKit media-stack smoke.
- `scripts/smoke.sh browser-join` for headless browser join/leave smoke when Chrome is available.

## Known missing integration coverage

- `services/analysis-engine` Docker build and runtime health are blocked until the native build-toolchain issue is fixed.
- `/analysis/*` should be tested behind authenticated API broker routes after that boundary is implemented.
- SpatialReal avatar media e2e requires public LiveKit signaling/media reachable from SpatialReal cloud and is not proven by local-only tests.
- Postgres runtime persistence is not wired yet, so there is no DB-backed session lifecycle integration suite.

Follow:
- `docs/runbooks/verification.md`
- `docs/runbooks/local-livekit-media.md`
- `docs/reviews/main-branch-readiness-20260611.md`
