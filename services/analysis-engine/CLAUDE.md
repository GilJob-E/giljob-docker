# services/analysis-engine

- Owns the GilJobE-backed STT/multimodal analysis service boundary.
- Keep token handling redacted; never log raw LiveKit tokens/JWTs/API secrets.
- Default mode is standby until the LiveKit hidden-subscriber runtime is explicitly enabled.
- Local Whisper is not an STT path for this service.
