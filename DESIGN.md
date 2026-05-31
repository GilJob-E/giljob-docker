# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-05-30
- Primary product surfaces: GilJob v2 landing page, production-style interview flow routes (`/interviews/new`, `/interviews/:id/lobby`, `/interviews/:id/room`, `/interviews/:id/report`), auto-joining local LiveKit room UI, hidden session diagnostics, local media pipeline explanation, documentation/runbooks.
- Evidence reviewed:
  - User-provided Cal.com-style marketing design brief in the 2026-05-30 design request.
  - Existing UI source: `apps/web/static/index.html`, `apps/web/static/styles.css`, `apps/web/static/app.js`.
  - Current scope docs: `README.md`, `docs/runbooks/local-livekit-media.md`, `docs/implementation-plan.md`.

## Brand
- Personality: clean, calm, confidently engineered, modern SaaS, product-first, not flashy.
- Trust signals: clear self-hosted architecture boundaries on setup/lobby/docs, token security copy, real session/LiveKit status, explicit out-of-scope placeholders outside the actual room.
- Avoid: dark dashboard aesthetic, blue primary CTAs, glassmorphism, heavy shadows, overly rounded consumer-app cards, fake marketing illustrations.

## Product goals
- Goals:
  - Make the local self-hosted LiveKit slice understandable at a glance.
  - Keep the landing page as a product entry point, not a long scroll into the room.
  - Shape the route contract like production: setup -> lobby -> room -> report under an interview id.
  - Let the dedicated room route auto-create a session and join LiveKit, while setup/lobby own pre-join readiness.
  - Make candidate audio turn-taking explicit: after an interviewer question finishes, enable `답변 시작`; the candidate presses it, speaks, then presses `답변 종료`; do not rely on VAD as the product boundary.
  - Show product UI fragments directly: room tiles, hidden-by-default question/transcript/signal drawer, hidden diagnostics, pipeline map.
- Non-goals:
  - Full Zoom/Google Meet replacement feature set such as screen sharing, participant management, recording, chat, or production meeting infra.
  - VAD-driven answer boundary detection for the candidate answer turn.
  - Real CV/job parsing, Main LLM, avatar/TTS, multimodal analysis, final report, production TLS/domain.
- Success signals:
  - User can identify the production route shape without the room reading like a setup page.
  - Primary action is obvious before room entry; the room itself connects and then offers media/leave/report controls.
  - Raw tokens are never shown in visible UI or logs.

## Personas and jobs
- Primary personas:
  - Builder/operator validating the GilJob v2 media-room foundation.
  - Product owner reviewing whether the LiveKit slice is ready for next feature layers.
- User jobs:
  - Confirm API can issue a LiveKit room token.
  - Confirm browser can join/leave the self-hosted LiveKit room.
  - Understand which interview-pipeline parts are still reserved without turning the actual room into a development checklist.
- Key contexts of use: local Mac via SSH tunnel, single-server Docker Compose, desktop browser first, responsive enough for tablet/mobile review.

## Information architecture
- Primary navigation: simple top nav with brand, production-flow route links, and state/status where useful.
- Core routes/screens: `/` landing/entry page, `/interviews/new` setup placeholder, `/interviews/:id/lobby` pre-join placeholder, `/interviews/:id/room` dedicated LiveKit Interview Room, `/interviews/:id/report` final-report placeholder. Legacy `/interview-room.html` remains as a compatibility alias.
- Content hierarchy:
  1. Landing hero: purpose and primary action to start a new interview.
  2. New interview setup placeholder: CV/job/persona inputs are reserved but disabled.
  3. Lobby placeholder: readiness/pre-join gate before media starts.
  4. Dedicated room route: no-scroll light media room with auto-joined candidate/interviewer tiles, active-speaker affordance, mic/camera/panel/leave/report controls, and hidden-by-default context drawer.
  5. Report placeholder: final-report surface reserved after the room.
  6. Dark footer close.

## Design principles
- Product chrome over illustration: show real controls and media tiles; keep question/transcript/signal details in a Drawer so the default room reads as a meeting room, not a dashboard.
- Monochrome action layer: primary CTA is near-black, not blue.
- Clear scope honesty: setup/lobby/report can label future placeholders; the actual room should use production empty states rather than marketing/dev explanation copy.
- Calm hierarchy: use whitespace, display scale, and card rhythm before color or decoration.
- Security by presentation: token redaction is a visible product constraint, not hidden implementation detail.

## Visual language
- Color:
  - Canvas `#ffffff`.
  - Primary/ink `#111111`; pressed `#242424`.
  - Light card `#f5f5f5`; soft surface `#f8f9fa`; hairline `#e5e7eb`.
  - Muted body `#374151`, secondary `#6b7280`, tertiary `#898989`.
  - Sparse accent blue `#3b82f6` only for minor badge/link moments.
  - Dark footer `#101010` with soft text `#a1a1aa`.
- Typography:
  - Use Cal Sans behavior for h1/h2/h3: Inter fallback at 600 with negative tracking.
  - Body/buttons/nav use Inter/system sans.
  - Display weights stay 600, never 700.
- Spacing/layout rhythm:
  - Max content width ~1200px.
  - Major vertical bands use 96px rhythm on desktop, reduced on mobile.
  - Cards use 24-32px internal padding.
- Shape/radius/elevation:
  - Buttons/inputs 8px, content cards 12px, hero app mockup 16px, badges pill.
  - Use hairlines and very subtle shadows only.
- Motion: no decorative animation required; keep state changes instant and readable.
- Imagery/iconography: use tiny product-status glyphs and UI fragments, not stock illustrations.

## Components
- Existing components to reuse:
  - Legacy/session-form support in JS: `#join-form`, `#api-endpoint`, `#role`, `#publish-media`, `#create-session`, `#join-room`, `#leave-room` when a compatibility surface renders those elements.
  - Status: `#status` with `data-state`.
  - Session summary: `#session-summary` for diagnostics; hidden on the production room surface.
  - Event log: `#event-log` for diagnostics; hidden on the production room surface.
- New/changed components:
  - `top-nav`, `hero-band`, `hero-app-mockup-card`, `feature-card`, `product-mockup-card`, `nav-pill-group`, `footer`.
  - `landing-room-card`: lightweight homepage product fragment that links to the production flow without starting media.
  - `interview-new`: setup placeholder for CV/job/persona route contract.
  - `interview-lobby`: readiness/pre-join route contract; actual device check belongs here, not inside the room route.
  - `interview-room-shell`: dedicated `/interviews/:id/room` production room surface adapted for GilJob; it auto-joins LiveKit, fills a no-scroll light media stage with candidate/interviewer tiles, and keeps mic/camera/context-drawer/leave/report controls in the bottom dock.
  - `room-context-drawer`: hidden by default; opens from the bottom dock and contains current question, transcript, and multimodal state without occupying the default meeting view.
  - `interview-report`: report placeholder surface for post-interview analysis.
- Variants and states:
  - Primary/secondary buttons, disabled button, connected/connecting/error status badges.
  - Candidate answer button uses the existing microphone publish path but labels the user action as `답변 시작` / `답변 종료`; it remains disabled until the interviewer-question-ended event, and `aria-pressed=true` means the candidate is currently answering.
  - Camera control remains independent; permission failures render through the redacted status/log path.
  - LiveKit SDK console logging is set to silent; GilJob-owned diagnostics stay redacted and hidden on the production room route.
  - Featured pipeline step is the current LiveKit room shell; future steps are placeholder/disabled-looking.
- Token/component ownership: CSS custom properties in `apps/web/static/styles.css`; no external design-system package yet.

## Accessibility
- Target standard: practical WCAG AA for contrast, focus, forms, and semantics.
- Keyboard/focus behavior: all inputs/buttons remain native focusable; visible focus rings are required.
- Contrast/readability: black-on-white/light-gray; dark footer uses soft but legible text.
- Screen-reader semantics: status uses `role="status"`; event log uses `aria-live="polite"`; sections are labelled.
- Reduced motion and sensory considerations: no required motion; avoid flashing or autoplay media.

## Responsive behavior
- Supported breakpoints/devices: mobile `<768px`, tablet `768-1024px`, desktop `>1024px`.
- Layout adaptations:
  - Hero 7/5 grid collapses to single column.
  - Feature cards collapse 3 -> 1.
  - Session/pipeline cards collapse 2 -> 1.
  - Top nav secondary links hide/wrap on mobile.
- Touch/hover differences: buttons remain at least 40px tall; no hover-only affordances.

## Interaction states
- Loading: room status badge says creating/connecting and room state shows Connecting.
- Empty: production room uses waiting/ready empty states for interviewer/question/transcript/signal; hidden diagnostics use `-` values.
- Error: status/log redacts sensitive text before rendering.
- Success: connected status badge uses success green; session summary shows room and participant. Candidate answer state switches from `답변 대기` to `답변 중` only after the interviewer question has ended and the candidate presses the answer button.
- Disabled: leave button disabled before room join.
- Offline/slow network: errors appear in status/log with token redaction.

## Content voice
- Tone: direct, calm, bilingual where useful; Korean explanation for user-facing scope, English for protocol labels.
- Terminology: “interview room”, “self-hosted LiveKit” outside the room, “session”, “candidate”, “scope 밖”.
- Microcopy rules:
  - Never show raw tokens.
  - Do not put pre-join, setup, or marketing explanation copy in `/interviews/:id/room`.
  - State that full Zoom/Meet feature parity is not included yet on landing/docs/lobby; room chrome may use familiar media-room affordances without claiming feature parity.
  - Keep CTA labels short and action-oriented.
  - Do not describe the candidate answer control as passive VAD; it is an explicit answer-turn button.

## Implementation constraints
- Framework/styling system: vanilla HTML/CSS/JS served by Python static server; no build step for CSS.
- Design-token constraints: CSS variables only; do not add Tailwind or a component library.
- Performance constraints: keep page lightweight; no external fonts/scripts required for local smoke.
- Compatibility constraints: modern Chromium/Safari/Firefox; LiveKit client vendored via Docker build.
- Test/screenshot expectations:
  - Existing contract tests must continue to pass.
  - Browser smoke must navigate to `/interviews/local-demo/room`, connect/disconnect, check token non-exposure, and confirm the default room does not page-scroll.
  - After visual changes, capture a local screenshot through the SSH tunnel when available.

## Open questions
- [ ] Should the lobby get a full device readiness check before room entry, or stay as a lightweight route placeholder until interviewer bot work starts? / owner: product / impact: next frontend milestone
- [ ] Should GilJob get its own brand type/color system later instead of the temporary Cal.com-inspired contract? / owner: product/design / impact: future brand differentiation
