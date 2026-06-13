#!/usr/bin/env node
// Minimal FD-bench room runner.
//
// Does exactly what a human QA run does, nothing more:
//   1. open the interview room
//   2. click 답변 시작
//   3. play the dataset clip into the mic (the one unavoidable trick:
//      getUserMedia audio is swapped for a WebAudio stream so the clip starts
//      at the click and goes silent at the annotated turn end)
//   4. click 답변 종료
//   5. read the page's own #event-log timestamps and report latencies
//
// No fetch/data-channel hooks: the service already logs every stage with ms
// timestamps (full_mmm_ready received / response requested / first_audio marker).
//
// The SpatialReal avatar bundle is blocked: it is an excluded boundary for
// product-path runs and its splat renderer blocks the headless software-GL
// main thread (~1.2s per frame), which distorts every number.
//
// Usage:
//   node fdbench_room_minimal.mjs --audio <input.wav> --turn-end-s 5.63 \
//     [--base-url http://127.0.0.1:8081] [--interview-id fdbench-min-1] [--headed]
import { execFileSync } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

// padMs: gap between clip end and the 답변 종료 click. Must exceed the server-VAD
// silence window (~2.2s): a single-segment answer only gets transcribed at the
// final VAD commit, and the app cuts mic frames at the click — clicking earlier
// strands the segment and the turn is blocked ("answer ended without transcript").
const args = { baseUrl: "http://127.0.0.1:8081", interviewId: `fdbench-min-${Date.now() % 100000}`, headed: false, waitS: 60, padMs: 3000 };
for (let i = 2; i < process.argv.length; i += 1) {
  const a = process.argv[i];
  if (a === "--audio") args.audio = process.argv[++i];
  else if (a === "--turn-end-s") args.turnEndS = Number(process.argv[++i]);
  else if (a === "--base-url") args.baseUrl = process.argv[++i];
  else if (a === "--interview-id") args.interviewId = process.argv[++i];
  else if (a === "--wait-s") args.waitS = Number(process.argv[++i]);
  else if (a === "--pad-ms") args.padMs = Number(process.argv[++i]);
  else if (a === "--headed") args.headed = true;
  else throw new Error(`unknown arg: ${a}`);
}
if (!args.audio || !Number.isFinite(args.turnEndS)) throw new Error("--audio and --turn-end-s are required");

// Decode the clip to mono float32 PCM, truncated at the annotated turn end.
const SAMPLE_RATE = 16000;
const pcm = execFileSync("ffmpeg", ["-v", "error", "-i", args.audio, "-f", "f32le", "-ac", "1", "-ar", String(SAMPLE_RATE), "-t", String(args.turnEndS), "-"], { maxBuffer: 1 << 30 });
// Append a faint room-tone tail instead of digital zeros: WebRTC opus DTX stops
// sending packets on pure silence, so OpenAI's server VAD never sees the end of
// a single-segment answer and its input transcription never completes (a real
// mic always carries room noise). ~-54dBFS noise keeps packets flowing.
const clip = new Float32Array(pcm.buffer, pcm.byteOffset, Math.floor(pcm.length / 4));
const tailSamples = Math.round((args.padMs / 1000 + 10) * SAMPLE_RATE);
const samples = new Float32Array(clip.length + tailSamples);
samples.set(clip);
for (let i = clip.length; i < samples.length; i += 1) samples[i] = (Math.random() * 2 - 1) * 0.002;
const audioB64 = Buffer.from(samples.buffer, 0, samples.length * 4).toString("base64");

const { chromium } = await import(pathToFileURL(path.resolve(path.dirname(new URL(import.meta.url).pathname), "../data/cache/browser-tools/node_modules/playwright/index.mjs")).href);
const browser = await chromium.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: !args.headed,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
});

try {
  const context = await browser.newContext();
  await context.grantPermissions(["microphone", "camera"], { origin: new URL(args.baseUrl).origin });
  await context.route("**/vendor/@spatialwalk/**", (route) => route.abort());

  const page = await context.newPage();
  await page.addInitScript(() => {
    // Swap getUserMedia audio for an injectable WebAudio stream.
    const state = {};
    const ensure = () => {
      if (!state.ctx) {
        state.ctx = new AudioContext();
        state.dest = state.ctx.createMediaStreamDestination();
      }
      return state;
    };
    window.__playAnswer = async (b64, rate) => {
      const { ctx, dest } = ensure();
      const raw = atob(b64);
      const bytes = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
      const samples = new Float32Array(bytes.buffer);
      await ctx.resume();
      const buf = ctx.createBuffer(1, samples.length, rate);
      buf.copyToChannel(samples, 0);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(dest);
      src.start();
    };
    const orig = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await orig(constraints);
      if (constraints?.audio) {
        stream.getAudioTracks().forEach((t) => { stream.removeTrack(t); t.stop(); });
        stream.addTrack(ensure().dest.stream.getAudioTracks()[0].clone());
      }
      return stream;
    };
  });

  // 1. open the room, wait until the answer button is usable
  await page.goto(`${args.baseUrl}/interviews/${encodeURIComponent(args.interviewId)}/room`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForFunction(() => {
    const b = document.querySelector("#toggle-mic");
    return b && !b.disabled;
  }, null, { timeout: 60000 });

  // 2. 답변 시작 + 3. inject the clip
  await page.click("#toggle-mic");
  await page.waitForTimeout(300); // let the app enable the mic track
  await page.evaluate(([b64, rate]) => window.__playAnswer(b64, rate), [audioB64, SAMPLE_RATE]);
  const tAudioStart = Date.now();

  // 4. clip done -> trailing silence keeps flowing -> 답변 종료
  await page.waitForTimeout(args.turnEndS * 1000 + args.padMs);
  await page.click("#toggle-mic");
  const tEndClick = Date.now();

  // 5. wait until the service log shows the next question's audio, then read the log
  await page.waitForFunction((sinceIso) => {
    const text = document.querySelector("#event-log")?.textContent || "";
    const m = text.match(/^([0-9T:.Z-]+) realtime\.first_audio marker emitted/m);
    return m && m[1] > sinceIso;
  }, new Date(tEndClick).toISOString(), { timeout: args.waitS * 1000 }).catch(() => {});

  const logText = await page.evaluate(() => document.querySelector("#event-log")?.textContent || "");
  const lines = logText.split("\n").map((l) => l.match(/^([0-9T:.Z-]+) (.*)$/)).filter(Boolean)
    .map((m) => ({ ts: Date.parse(m[1]), iso: m[1], msg: m[2] })).reverse(); // oldest first

  const tAnswerEnd = tAudioStart + args.turnEndS * 1000;
  const after = (re) => lines.find((l) => l.ts >= tAnswerEnd - 100 && re.test(l.msg));
  const gate = after(/full_mmm_ready received/);
  const create = after(/response requested through API control plane: candidate-answer-ended/);
  const firstAudio = after(/realtime\.first_audio marker emitted/);
  const questionStarted = after(/interviewer question started/);

  const ms = (l) => (l ? Math.round(l.ts - tAnswerEnd) : null);
  console.log(JSON.stringify({
    interview_id: args.interviewId,
    turn_end_s: args.turnEndS,
    end_click_after_audio_end_ms: tEndClick - Math.round(tAnswerEnd),
    full_mmm_ready_ms: ms(gate),
    response_create_ms: ms(create),
    next_question_started_ms: ms(questionStarted),
    first_audio_ms: ms(firstAudio),
    log_after_answer_end: lines.filter((l) => l.ts >= tAnswerEnd - 100 && !/vision event sent/.test(l.msg)).map((l) => `${l.iso} ${l.msg}`),
  }, null, 2));
} finally {
  await browser.close();
}
