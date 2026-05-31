# services/ai-engine

Initial scaffold placeholder for GilJob v2.

Follow:
- docs/implementation-plan.md
- docs/decisions/0001-state-stack.md
- docs/decisions/0002-ingress-stack.md

## Main LLM env contract

Gemini is the selected Main LLM provider for the next interview-controller slice.
Copy `.env.example` to `.env`, then set:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-google-ai-studio-key
GEMINI_MODEL=gemini-3.5-flash
GEMINI_TIMEOUT_SECONDS=30
```

The official Gemini quickstart expects the API key in `GEMINI_API_KEY`.
Do not commit `.env` or real API keys.
