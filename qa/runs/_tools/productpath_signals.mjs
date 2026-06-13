#!/usr/bin/env node
// Product-path signals runner — drives the REAL OpenAI Realtime interview room
// for one candidate answer turn and captures the per-turn analysis signals.
//
// Same room-driving path as benchmark/04-qivd/.../qivd_room_smoke.mjs (the
// service is treated as ONE model, exactly like a human QA run):
//   1. open the interview room (QA stack)
//   2. wait for the opener question to end (mic button enables)
//   3. camera ON (vision lanes need a published video track)
//   4. 답변 시작 -> stream clip: video -> fake camera, audio -> injected WebAudio mic
//   5. 답변 종료 -> full stack runs (Realtime STT + MMM/RNAS lanes -> fragment -> gate)
//   6. read the interviewer's spoken-answer transcript (page #current-question-body)
//   7. NEW: poll /analysis/realtime/turn-results for the answer turn (objective
//      vision/prosody/transcript lanes) + legacy /analysis/signals, write to out-dir.
//
// transcript_feed = openai-realtime (REAL text). Avatar bundle blocked (headless GL).
//
// Usage:
//   node productpath_signals.mjs --video <clip.mp4> --out-dir <dir> [--label <s>]
//     [--base-url http://127.0.0.1:8081] [--interview-id <id>] [--wait-s 90]
//     [--pad-ms 3000] [--headed]
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

const args = {
  baseUrl: "http://127.0.0.1:8081",
  interviewId: `qa-pp-${Date.now() % 100000}`,
  headed: false, waitS: 90, padMs: 3000, label: "",
};
for (let i = 2; i < process.argv.length; i += 1) {
  const a = process.argv[i];
  if (a === "--video") args.video = process.argv[++i];
  else if (a === "--out-dir") args.outDir = process.argv[++i];
  else if (a === "--label") args.label = process.argv[++i];
  else if (a === "--base-url") args.baseUrl = process.argv[++i];
  else if (a === "--interview-id") args.interviewId = process.argv[++i];
  else if (a === "--wait-s") args.waitS = Number(process.argv[++i]);
  else if (a === "--pad-ms") args.padMs = Number(process.argv[++i]);
  else if (a === "--headed") args.headed = true;
  else throw new Error(`unknown arg: ${a}`);
}
if (!args.video) throw new Error("--video is required");
if (!args.outDir) throw new Error("--out-dir is required");
fs.mkdirSync(args.outDir, { recursive: true });

const PLAYWRIGHT = "/home/kio/workspace/giljob-docker/benchmark/data/cache/browser-tools/node_modules/playwright/index.mjs";
const workDir = "/tmp/qa-productpath";
fs.mkdirSync(workDir, { recursive: true });

const probe = execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", args.video], { encoding: "utf8" });
const clipDurS = Number(probe.trim()) || 6;

// Fake camera: Chrome loops a y4m file. GilJob camera shape 640x480 @15fps.
const y4mPath = path.join(workDir, `${path.basename(args.video, ".mp4")}.y4m`);
execFileSync("ffmpeg", ["-v", "error", "-y", "-i", args.video,
  "-vf", "scale=640:480:force_original_aspect_ratio=decrease,pad=640:480:(ow-iw)/2:(oh-ih)/2,fps=15",
  "-pix_fmt", "yuv420p", y4mPath]);

// Mic: full clip audio (mono f32 @16k) + faint room-tone tail so opus DTX keeps
// sending packets (digital silence -> VAD never closes).
const SAMPLE_RATE = 16000;
const pcm = execFileSync("ffmpeg", ["-v", "error", "-i", args.video, "-f", "f32le", "-ac", "1", "-ar", String(SAMPLE_RATE), "-"], { maxBuffer: 1 << 30 });
const clip = new Float32Array(pcm.buffer, pcm.byteOffset, Math.floor(pcm.length / 4));
const tailSamples = Math.round((args.padMs / 1000 + 10) * SAMPLE_RATE);
const samples = new Float32Array(clip.length + tailSamples);
samples.set(clip);
for (let i = clip.length; i < samples.length; i += 1) samples[i] = (Math.random() * 2 - 1) * 0.002;
const audioB64 = Buffer.from(samples.buffer, 0, samples.length * 4).toString("base64");

const ANALYSIS = `${args.baseUrl}/analysis`;
async function getJson(url) {
  try {
    const r = await fetch(url, { headers: { accept: "application/json" } });
    return await r.json();
  } catch (e) {
    return { _fetchError: String(e) };
  }
}

const { chromium } = await import(pathToFileURL(PLAYWRIGHT).href);
const browser = await chromium.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: !args.headed,
  args: [
    "--no-sandbox", "--disable-dev-shm-usage",
    "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
    `--use-file-for-fake-video-capture=${y4mPath}`,
    "--autoplay-policy=no-user-gesture-required",
  ],
});

let out = {};
try {
  const context = await browser.newContext();
  await context.grantPermissions(["microphone", "camera"], { origin: new URL(args.baseUrl).origin });
  await context.route("**/vendor/@spatialwalk/**", (route) => route.abort());

  const page = await context.newPage();
  await page.addInitScript(() => {
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

  // 1+2. open room; answer button enables once opener ended
  await page.goto(`${args.baseUrl}/interviews/${encodeURIComponent(args.interviewId)}/room`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForFunction(() => {
    const b = document.querySelector("#toggle-mic");
    return b && !b.disabled;
  }, null, { timeout: 60000 });
  const openerText = await page.evaluate(() => document.querySelector("#current-question-body")?.textContent?.trim() || "");

  // 2b. camera ON
  await page.click("#toggle-camera");
  await page.waitForFunction(() => document.querySelector("#toggle-camera")?.getAttribute("aria-pressed") === "true", null, { timeout: 15000 });
  await page.waitForTimeout(1000);

  // 3. 답변 시작 + stream clip
  await page.click("#toggle-mic");
  await page.waitForTimeout(300);
  await page.evaluate(([b64, rate]) => window.__playAnswer(b64, rate), [audioB64, SAMPLE_RATE]);

  // 4. clip done -> trailing room tone -> 답변 종료
  await page.waitForTimeout(clipDurS * 1000 + args.padMs);
  await page.click("#toggle-mic");
  const tEndClick = Date.now();

  // 5. wait for the service's answer transcript (differs from opener, settled 2.5s)
  let answer = "";
  let lastChange = Date.now();
  let prev = "";
  const deadline = tEndClick + args.waitS * 1000;
  while (Date.now() < deadline) {
    const cur = await page.evaluate(() => document.querySelector("#current-question-body")?.textContent?.trim() || "");
    if (cur !== prev) { prev = cur; lastChange = Date.now(); }
    const settled = Date.now() - lastChange > 2500;
    if (cur && cur !== openerText && !/Realtime 음성 질문을 재생/.test(cur) && settled) { answer = cur; break; }
    await page.waitForTimeout(400);
  }
  if (!answer && prev && prev !== openerText) answer = prev;

  // 6. capture analysis signals. With pin f817f81 the GilJobE engine owns
  //    turn-events and exposes the rich per-turn analysis (records + turnHandoff
  //    with objective speech/visual/nonverbal lanes) via the legacy /analysis/signals
  //    payload — that IS the canonical signals.json shape every prior run saved.
  //    Poll it until the turnHandoff lands (the answer-end MMM gate fired).
  let signals = null;
  const sigDeadline = Date.now() + 25000;
  while (Date.now() < sigDeadline) {
    signals = await getJson(`${ANALYSIS}/signals?sessionId=${encodeURIComponent(args.interviewId)}`);
    if (signals && (signals.turnHandoff || (signals.recordCount || 0) > 0)) break;
    await page.waitForTimeout(1500);
  }
  // candidate-safe fragment route (thin, gate-facing) — secondary artifact.
  const probed = {};
  for (const ti of [0, 1, 2, 3]) {
    probed[ti] = await getJson(`${ANALYSIS}/realtime/turn-results?interviewId=${encodeURIComponent(args.interviewId)}&turnIndex=${ti}`);
  }
  const readyFragment = Object.entries(probed).find(([, v]) => v?.result?.status === "ready" || v?.status === "ready");

  const logText = await page.evaluate(() => document.querySelector("#event-log")?.textContent || "");
  const logLines = logText.split("\n").filter((l) => l.trim() && !/vision event sent/.test(l)).slice(0, 60).reverse();

  const th = signals?.turnHandoff || null;
  // signals.json = the canonical /analysis/signals payload (records + turnHandoff = objective lanes)
  fs.writeFileSync(path.join(args.outDir, "signals.json"), JSON.stringify(signals ?? {}, null, 2) + "\n");
  fs.writeFileSync(path.join(args.outDir, "candidate-fragment.json"), JSON.stringify({ readyTurnIndex: readyFragment?.[0] ?? null, probed }, null, 2) + "\n");

  out = {
    interview_id: args.interviewId,
    video: path.basename(args.video),
    clip_dur_s: clipDurS,
    opener_text: openerText,
    answer_text: answer,
    answer_latency_after_click_ms: answer ? lastChange - tEndClick : null,
    record_count: signals?.recordCount ?? 0,
    transcript_full_chars: (signals?.transcriptFull || "").length,
    turn_handoff_present: Boolean(th),
    handoff_coverage: th?.meta?.coverage ?? null,
    speech_windows: th?.speech?.windows ?? null,
    visual_face_frames: th?.visual?.face_frames ?? null,
    visual_hand_seen_ratio: th?.visual?.hand_seen_ratio ?? null,
    nonverbal_states: th?.nonverbal?.states ?? null,
    fragment_ready_turn: readyFragment?.[0] ?? null,
    log_tail: logLines,
  };
  fs.writeFileSync(path.join(args.outDir, "run.json"), JSON.stringify(out, null, 2) + "\n");

  const chromeVer = execFileSync("/usr/bin/google-chrome", ["--version"], { encoding: "utf8" }).trim();
  const meta = {
    date: new Date().toISOString().slice(0, 10),
    purpose: `${path.basename(args.video)} product-path 객관 레인(speech/visual/nonverbal) — 실 OpenAI Realtime 전사 포함 풀스택`,
    engine: { container: "giljob-qa-analysis-engine-1", pin: "f817f81 (GilJobE — turn-events/turn-results 소유)" },
    media: `${args.video} (${clipDurS.toFixed(1)}s, 원본 1920x1080) → fake cam ${y4mPath} (640x480@15fps loop) + 주입 mic (clip audio mono f32@16k + room-tone tail ${args.padMs}ms)`,
    publish_path: "product-path-room (Chrome fake camera + injected WebAudio mic, 실 WebRTC)",
    transcript_feed: "openai-realtime (실 전사 — REAL text)",
    stack: "giljob-qa",
    interview_id: args.interviewId,
    publisher: `${chromeVer}, playwright(chromium 드라이브), SpatialReal avatar 번들 차단(headless GL 왜곡 방지)`,
    harness: "qa/runs/_tools/productpath_signals.mjs (qivd_room_smoke 룸 구동 경로 재사용 + /analysis/signals 캡처)",
    caveat: "y4m은 캡처 시작부터 루프(clip+pad 동안 재생). 답변=면접 1턴(turnIndex 0). signals.json=/analysis/signals 정본 페이로드(records+turnHandoff). candidate-fragment.json=게이트용 thin 프래그먼트.",
  };
  fs.writeFileSync(path.join(args.outDir, "meta.json"), JSON.stringify(meta, null, 2) + "\n");
  console.log(JSON.stringify({ ...out, log_tail: `(${logLines.length} lines)` }, null, 2));
} finally {
  await browser.close();
}
