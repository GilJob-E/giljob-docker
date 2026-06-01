# services/stt-whisper

Local faster-whisper STT service for GilJob v2 answer turns.

Default runtime contract:

```env
STT_PROVIDER=local-whisper
WHISPER_MODEL=Systran/faster-whisper-large-v3
WHISPER_DEVICE=cuda
WHISPER_DEVICE_INDEX=0
WHISPER_HOST_GPU_DEVICE_ID=1
WHISPER_COMPUTE_TYPE=float16
STT_LANGUAGE=ko
```

Docker Compose reserves host GPU `1` for this service. Inside the container that selected GPU is used as CUDA device index `0`.

Endpoints:

- `GET /healthz`
- `POST /transcribe?interviewId=local-demo&turnIndex=1&language=ko`

The service accepts raw audio bytes, writes them to a temporary file, transcribes with faster-whisper, deletes the temporary file, and returns JSON transcript text plus segment timestamps. It must not log raw audio, raw transcript text, JWTs, or secret env values.
