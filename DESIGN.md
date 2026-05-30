# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-05-30
- Primary product surfaces: GilJob v2 landing page, separate Interview Room page, local LiveKit room smoke UI, session summary, local media pipeline explanation, event log, documentation/runbooks.
- Evidence reviewed:
  - User-provided Cal.com-style marketing design brief in the 2026-05-30 design request.
  - Existing UI source: `apps/web/static/index.html`, `apps/web/static/styles.css`, `apps/web/static/app.js`.
  - Current scope docs: `README.md`, `docs/runbooks/local-livekit-media.md`, `docs/implementation-plan.md`.

## Brand
- Personality: clean, calm, confidently engineered, modern SaaS, product-first, not flashy.
- Trust signals: visible self-hosted architecture boundaries, token security copy, real session/LiveKit status, explicit out-of-scope placeholders.
- Avoid: dark dashboard aesthetic, blue primary CTAs, glassmorphism, heavy shadows, overly rounded consumer-app cards, fake marketing illustrations.

## Product goals
- Goals:
  - Make the local self-hosted LiveKit slice understandable at a glance.
  - Keep the landing page as a product entry point, not a long scroll into the room.
  - Let a user create a session and join/leave the LiveKit room from a dedicated Interview Room page.
  - Show product UI fragments directly: session form, room summary, pipeline map, event log.
- Non-goals:
  - Zoom/Google Meet replacement UI.
  - Real CV/job parsing, Main LLM, avatar/TTS, multimodal analysis, final report, production TLS/domain.
- Success signals:
  - User can identify that this is a local media-room scaffold.
  - Primary action is obvious: create/join room.
  - Raw tokens are never shown in visible UI or logs.

## Personas and jobs
- Primary personas:
  - Builder/operator validating the GilJob v2 media-room foundation.
  - Product owner reviewing whether the LiveKit slice is ready for next feature layers.
- User jobs:
  - Confirm API can issue a LiveKit room token.
  - Confirm browser can join/leave the self-hosted LiveKit room.
  - Understand which interview-pipeline parts are still placeholders.
- Key contexts of use: local Mac via SSH tunnel, single-server Docker Compose, desktop browser first, responsive enough for tablet/mobile review.

## Information architecture
- Primary navigation: simple top nav with brand, local mode, architecture anchor, docs anchor, and primary join CTA.
- Core routes/screens: `/` landing/entry page and `/interview-room.html` dedicated LiveKit Interview Room page.
- Content hierarchy:
  1. Landing hero: purpose and primary action to open the room.
  2. Landing product fragment: visual preview/link for the Interview Room.
  3. Dedicated room hero: pre-join preview and session/create/join controls.
  4. Room shell: candidate/interviewer tiles plus question/transcript placeholders.
  5. Room support cards: session summary, pipeline map, event log.
  6. Dark footer close.

## Design principles
- Product chrome over illustration: show real controls, summaries, and pipeline fragments in cards.
- Monochrome action layer: primary CTA is near-black, not blue.
- Clear scope honesty: placeholders are labeled as placeholders; do not imply complete interview product behavior.
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
  - Session form: `#join-form`, `#api-endpoint`, `#role`, `#publish-media`, `#create-session`, `#join-room`, `#leave-room`.
  - Status: `#status` with `data-state`.
  - Session summary: `#session-summary`.
  - Event log: `#event-log`.
- New/changed components:
  - `top-nav`, `hero-band`, `hero-app-mockup-card`, `feature-card`, `product-mockup-card`, `nav-pill-group`, `footer`.
  - `landing-room-card`: lightweight homepage product fragment that links to the real room without starting media.
  - `interview-room-shell`: dedicated `/interview-room.html` room-first surface adapted for GilJob; it places candidate/interviewer tiles and pre-join controls above the fold instead of below a long landing scroll, with question/transcript/analysis panels and bottom control bar.
- Variants and states:
  - Primary/secondary buttons, disabled button, connected/connecting/error status badges.
  - Mic/camera control buttons use `aria-pressed` and explicit on/off labels; permission failures render through the redacted status/log path.
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
- Loading: status badge says creating/connecting.
- Empty: session summary uses `-` values.
- Error: status/log redacts sensitive text before rendering.
- Success: connected status badge uses success green; session summary shows room and participant.
- Disabled: leave button disabled before room join.
- Offline/slow network: errors appear in status/log with token redaction.

## Content voice
- Tone: direct, calm, bilingual where useful; Korean explanation for user-facing scope, English for protocol labels.
- Terminology: “local media room”, “self-hosted LiveKit”, “session”, “candidate”, “placeholder”, “scope 밖”.
- Microcopy rules:
  - Never show raw tokens.
  - State that Zoom/Meet-like features are not included yet.
  - Keep CTA labels short and action-oriented.

## Implementation constraints
- Framework/styling system: vanilla HTML/CSS/JS served by Python static server; no build step for CSS.
- Design-token constraints: CSS variables only; do not add Tailwind or a component library.
- Performance constraints: keep page lightweight; no external fonts/scripts required for local smoke.
- Compatibility constraints: modern Chromium/Safari/Firefox; LiveKit client vendored via Docker build.
- Test/screenshot expectations:
  - Existing contract tests must continue to pass.
  - Browser smoke must navigate to `/interview-room.html`, connect/disconnect, and check token non-exposure.
  - After visual changes, capture a local screenshot through the SSH tunnel when available.

## Open questions
- [ ] Should the next UI slice add local camera preview and participant tiles, or keep the smoke UI non-video until interviewer bot work starts? / owner: product / impact: next frontend milestone
- [ ] Should GilJob get its own brand type/color system later instead of the temporary Cal.com-inspired contract? / owner: product/design / impact: future brand differentiation
