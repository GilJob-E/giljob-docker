#!/usr/bin/env node
// Command adapter bridge from benchmark runners to qa/runs/_tools/productpath_signals.mjs.
//
// The benchmark runner sends JSON on stdin. This adapter turns audio-only inputs
// into a temporary black-video MP4, drives the real interview room product path,
// stores product-path artifacts under the benchmark run directory, and prints a
// single response string on stdout for the runner's evaluator.

import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { benchmarkPromptProfile } from "./productpath_prompt_profiles.mjs";

const args = {
  audioRoles: "all",
  baseUrl: "http://127.0.0.1:8081",
  dryRun: false,
  headed: false,
  outSubdir: "_productpath",
  padMs: 3000,
  responseField: "answer-text",
  responseInstructions: "",
  responseInstructionsFile: "",
  sessionInstructions: "",
  sessionInstructionsFile: "",
  taskPrompt: "auto",
  waitS: 90,
};

for (let i = 2; i < process.argv.length; i += 1) {
  const a = process.argv[i];
  if (a === "--audio-roles") args.audioRoles = process.argv[++i];
  else if (a === "--base-url") args.baseUrl = process.argv[++i];
  else if (a === "--dry-run") args.dryRun = true;
  else if (a === "--headed") args.headed = true;
  else if (a === "--interview-id") args.interviewId = process.argv[++i];
  else if (a === "--label") args.label = process.argv[++i];
  else if (a === "--out-dir") args.outDir = process.argv[++i];
  else if (a === "--out-subdir") args.outSubdir = process.argv[++i];
  else if (a === "--pad-ms") args.padMs = Number(process.argv[++i]);
  else if (a === "--response-field") args.responseField = process.argv[++i];
  else if (a === "--response-instructions") args.responseInstructions = process.argv[++i];
  else if (a === "--response-instructions-file") args.responseInstructionsFile = process.argv[++i];
  else if (a === "--session-instructions") args.sessionInstructions = process.argv[++i];
  else if (a === "--session-instructions-file") args.sessionInstructionsFile = process.argv[++i];
  else if (a === "--task-prompt") args.taskPrompt = process.argv[++i];
  else if (a === "--wait-s") args.waitS = Number(process.argv[++i]);
  else throw new Error(`unknown arg: ${a}`);
}

const SCRIPT_PATH = fileURLToPath(import.meta.url);

function findRepoRoot(startPath) {
  let cur = path.resolve(startPath);
  if (fs.statSync(cur).isFile()) cur = path.dirname(cur);
  for (;;) {
    if (fs.existsSync(path.join(cur, "AGENTS.md"))) return cur;
    const next = path.dirname(cur);
    if (next === cur) return path.resolve(process.cwd());
    cur = next;
  }
}

const repoRoot = findRepoRoot(SCRIPT_PATH);
const PRODUCTPATH = path.join(repoRoot, "qa/runs/_tools/productpath_signals.mjs");

function safeId(value) {
  const safe = String(value || "example").replace(/[^A-Za-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "");
  return safe || "example";
}

function redactObviousSecrets(text) {
  return String(text)
    .replace(/(api[_-]?key|token|jwt|secret|password)\s*[:=]\s*([^\s,;]+)/gi, "$1=[REDACTED]")
    .replace(/eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}/g, "[REDACTED]")
    .replace(/\bsk-[A-Za-z0-9_-]{20,}\b/g, "[REDACTED]");
}

function readStdin() {
  return fs.readFileSync(0, "utf8");
}

function parsePayload(stdinText) {
  const trimmed = stdinText.trim();
  if (!trimmed) return {};
  try {
    return JSON.parse(trimmed);
  } catch {
    return { prompt: stdinText };
  }
}

function resolveInputPath(inputPath) {
  const raw = String(inputPath || "");
  if (!raw) throw new Error("empty input path");
  return path.isAbsolute(raw) ? raw : path.resolve(repoRoot, raw);
}

function hasVideoStream(mediaPath) {
  try {
    const out = execFileSync("ffprobe", [
      "-v",
      "error",
      "-select_streams",
      "v:0",
      "-show_entries",
      "stream=codec_type",
      "-of",
      "csv=p=0",
      mediaPath,
    ], { encoding: "utf8" });
    return out.trim() === "video";
  } catch {
    return false;
  }
}

function collectMedia(payload) {
  if (payload.video_path || payload.video) {
    const videoPath = resolveInputPath(payload.video_path || payload.video);
    if (!fs.existsSync(videoPath)) throw new Error(`video input missing: ${videoPath}`);
    return { videoPath, audioPaths: [] };
  }

  const audioPaths = [];
  const roleFilter = new Set(
    args.audioRoles === "all"
      ? []
      : args.audioRoles.split(",").map((item) => item.trim()).filter(Boolean),
  );

  const pushAudio = (entry) => {
    const audioPath = typeof entry === "string" ? entry : entry?.audio_path || entry?.path;
    if (!audioPath) return;
    const role = typeof entry === "string" ? null : entry?.role;
    if (roleFilter.size && !roleFilter.has(String(role))) return;
    const resolved = resolveInputPath(audioPath);
    if (!fs.existsSync(resolved)) throw new Error(`audio input missing: ${resolved}`);
    audioPaths.push(resolved);
  };

  if (payload.audio_path || payload.audio) pushAudio(payload.audio_path || payload.audio);
  for (const entry of payload.audio_paths || []) pushAudio(entry);
  for (const entry of payload.speech_dialogue_audio || []) pushAudio(entry);

  if (!audioPaths.length) {
    throw new Error("No audio/video path in payload. Text benchmarks should use productpath_fragment_text_adapter.py.");
  }
  return { videoPath: null, audioPaths };
}

function ffmpeg(argsList, options = {}) {
  try {
    execFileSync("ffmpeg", argsList, { stdio: ["ignore", "pipe", "pipe"], maxBuffer: 128 * 1024 * 1024, ...options });
  } catch (error) {
    const stderr = error.stderr ? error.stderr.toString("utf8") : String(error);
    throw new Error(`ffmpeg failed: ${redactObviousSecrets(stderr.slice(0, 1200))}`);
  }
}

function buildClipFromAudio(audioPaths, tmpDir) {
  fs.mkdirSync(tmpDir, { recursive: true });
  const wavParts = [];
  for (let index = 0; index < audioPaths.length; index += 1) {
    const partPath = path.join(tmpDir, `part-${String(index).padStart(4, "0")}.wav`);
    ffmpeg([
      "-v",
      "error",
      "-y",
      "-i",
      audioPaths[index],
      "-vn",
      "-ac",
      "1",
      "-ar",
      "16000",
      "-c:a",
      "pcm_s16le",
      partPath,
    ]);
    wavParts.push(partPath);
  }

  const combinedWav = path.join(tmpDir, "combined.wav");
  if (wavParts.length === 1) {
    fs.copyFileSync(wavParts[0], combinedWav);
  } else {
    const concatList = path.join(tmpDir, "concat.txt");
    fs.writeFileSync(concatList, wavParts.map((part) => `file '${part}'`).join("\n") + "\n");
    ffmpeg(["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", concatList, "-c:a", "pcm_s16le", combinedWav]);
  }

  const clipPath = path.join(tmpDir, "productpath-input.mp4");
  ffmpeg([
    "-v",
    "error",
    "-y",
    "-f",
    "lavfi",
    "-i",
    "color=c=black:s=640x480:r=15",
    "-i",
    combinedWav,
    "-shortest",
    "-c:v",
    "libx264",
    "-preset",
    "ultrafast",
    "-pix_fmt",
    "yuv420p",
    "-c:a",
    "aac",
    "-b:a",
    "96k",
    clipPath,
  ]);
  return clipPath;
}

function extractCandidateFragment(outDir) {
  const fragmentPath = path.join(outDir, "candidate-fragment.json");
  if (!fs.existsSync(fragmentPath)) return "";
  const fragmentJson = JSON.parse(fs.readFileSync(fragmentPath, "utf8"));
  const ready = fragmentJson.readyTurnIndex;
  if (ready != null) {
    const value = fragmentJson.probed?.[String(ready)]?.result?.candidatePromptFragment;
    if (value) return String(value);
  }
  for (const value of Object.values(fragmentJson.probed || {})) {
    const fragment = value?.result?.candidatePromptFragment;
    if (fragment) return String(fragment);
  }
  return "";
}

function selectResponse(outDir) {
  const runPath = path.join(outDir, "run.json");
  const signalsPath = path.join(outDir, "signals.json");
  const run = fs.existsSync(runPath) ? JSON.parse(fs.readFileSync(runPath, "utf8")) : {};
  const signals = fs.existsSync(signalsPath) ? JSON.parse(fs.readFileSync(signalsPath, "utf8")) : {};
  if (args.responseField === "answer-text") return String(run.answer_text || "");
  if (args.responseField === "transcript-full") return String(signals.transcriptFull || "");
  if (args.responseField === "candidate-fragment") return extractCandidateFragment(outDir);
  if (args.responseField === "run-json") return JSON.stringify(run);
  throw new Error(`unsupported --response-field: ${args.responseField}`);
}

function writeAdapterMeta(outDir, value) {
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, "adapter-meta.json"), JSON.stringify(value, null, 2) + "\n");
}

function readOptionalText(value, filePath) {
  if (filePath) return fs.readFileSync(resolveInputPath(filePath), "utf8").trim();
  return value ? String(value).trim() : "";
}

function profileForTask(payload) {
  if (args.taskPrompt === "none") return benchmarkPromptProfile({ benchmark_id: "" });
  if (args.taskPrompt === "bigbench-audio") return benchmarkPromptProfile({ ...payload, benchmark_id: "06-bigbench-audio" });
  if (args.taskPrompt === "voicebench-ifeval") return benchmarkPromptProfile({ ...payload, benchmark_id: "07-ifeval-voicebench" });
  if (args.taskPrompt === "auto") return benchmarkPromptProfile(payload);
  throw new Error(`unsupported --task-prompt: ${args.taskPrompt}`);
}

function autoTaskPrompt(payload, profile) {
  const benchmarkId = String(payload.benchmark_id || process.env.BENCHMARK_ID || "");
  if (profile?.responseInstructions) return profile.responseInstructions;
  if (benchmarkId === "06-bigbench-audio") {
    return [
      "Answer the standalone spoken task from the user's audio.",
      "Use only what you heard in the audio and the conversation so far.",
      "Return only the final answer, with no explanation.",
      "If the final answer is yes, no, valid, invalid, or a number, output exactly that answer.",
      "Do not mention interviews, scoring, labels, transcripts, rubrics, or internal systems.",
    ].join(" ");
  }
  if (benchmarkId === "07-ifeval-voicebench") {
    return [
      "Follow the spoken instruction from the user's audio exactly.",
      "Produce only the requested response.",
      "Preserve every formatting, wording, length, punctuation, and content constraint stated in the audio.",
      "Do not explain your reasoning and do not mention scoring, labels, transcripts, rubrics, or internal systems.",
    ].join(" ");
  }
  return "";
}

function taskInstructions(payload) {
  const explicit = readOptionalText(args.responseInstructions, args.responseInstructionsFile);
  if (explicit) return explicit;
  if (args.taskPrompt === "none") return "";
  return autoTaskPrompt(payload, profileForTask(payload));
}

function sessionInstructionsForTask(payload) {
  const explicit = readOptionalText(args.sessionInstructions, args.sessionInstructionsFile);
  if (explicit) return explicit;
  return profileForTask(payload).sessionInstructions || "";
}

function initialInstructionsForTask(payload, responseInstructions) {
  if (!responseInstructions) return "";
  return profileForTask(payload).initialInstructions || "Say exactly: Ready.";
}

const payload = parsePayload(readStdin());
const benchmarkId = process.env.BENCHMARK_ID || payload.benchmark_id || "benchmark";
const exampleId = process.env.BENCHMARK_EXAMPLE_ID || payload.example_id || payload.question_id || payload.key || "example";
const safeExample = safeId(exampleId);
const runDir = process.env.BENCHMARK_RUN_DIR || null;
const outDir = path.resolve(args.outDir || (runDir ? path.join(runDir, args.outSubdir, safeExample) : path.join(process.cwd(), args.outSubdir, safeExample)));
const tmpDir = path.join("/tmp/giljob-benchmark-productpath", `${safeId(benchmarkId)}-${safeExample}-${process.pid}`);

const media = collectMedia(payload);
const promptProfile = profileForTask(payload);
const sessionInstructions = sessionInstructionsForTask(payload);
const instructions = taskInstructions(payload);
const initialInstructions = initialInstructionsForTask(payload, instructions);
let clipPath = media.videoPath;
if (clipPath && !hasVideoStream(clipPath)) {
  media.audioPaths = [clipPath];
  clipPath = null;
}
if (!clipPath) clipPath = buildClipFromAudio(media.audioPaths, tmpDir);

const label = args.label || `${benchmarkId}-${safeExample}`;
const interviewId = args.interviewId || `bench-${safeId(benchmarkId)}-${safeExample}-${Date.now() % 100000}`;
writeAdapterMeta(outDir, {
  adapter: "productpath-signals-adapter",
  audio_roles: args.audioRoles,
  benchmark_id: benchmarkId,
  example_id: String(exampleId),
  input_media_count: media.audioPaths.length || 1,
  interview_id: interviewId,
  productpath_script: "qa/runs/_tools/productpath_signals.mjs",
  response_field: args.responseField,
  prompt_profile: promptProfile.id,
  initial_instructions_present: Boolean(initialInstructions),
  response_instructions_present: Boolean(instructions),
  session_instructions_present: Boolean(sessionInstructions),
  task_prompt: args.taskPrompt,
  synthesized_video: !media.videoPath,
});

if (!args.dryRun) {
  const productArgs = [
    PRODUCTPATH,
    "--video",
    clipPath,
    "--out-dir",
    outDir,
    "--label",
    label,
    "--base-url",
    args.baseUrl,
    "--interview-id",
    interviewId,
    "--wait-s",
    String(args.waitS),
    "--pad-ms",
    String(args.padMs),
  ];
  let instructionsFile = "";
  if (sessionInstructions) {
    const sessionInstructionsFile = path.join(outDir, "session-instructions.txt");
    fs.writeFileSync(sessionInstructionsFile, sessionInstructions);
    productArgs.push("--session-instructions-file", sessionInstructionsFile);
  }
  if (instructions) {
    const initialInstructionsFile = path.join(outDir, "initial-instructions.txt");
    fs.writeFileSync(initialInstructionsFile, initialInstructions);
    instructionsFile = path.join(outDir, "response-instructions.txt");
    fs.writeFileSync(instructionsFile, instructions);
    productArgs.push(
      "--initial-instructions-file",
      initialInstructionsFile,
      "--response-instructions-file",
      instructionsFile,
      "--analysis-fragment-mode",
      "omit",
    );
  }
  if (args.headed) productArgs.push("--headed");
  const completed = spawnSync(process.execPath, productArgs, {
    cwd: repoRoot,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  if (completed.status !== 0) {
    const stderr = redactObviousSecrets(completed.stderr || completed.stdout || `exit ${completed.status}`);
    throw new Error(stderr.slice(0, 2000));
  }
} else {
  fs.writeFileSync(path.join(outDir, "run.json"), JSON.stringify({
    answer_text: "DRY_RUN_PRODUCT_PATH_RESPONSE",
    interview_id: interviewId,
    video: path.basename(clipPath),
  }, null, 2) + "\n");
  fs.writeFileSync(path.join(outDir, "signals.json"), JSON.stringify({}, null, 2) + "\n");
  fs.writeFileSync(path.join(outDir, "candidate-fragment.json"), JSON.stringify({ readyTurnIndex: null, probed: {} }, null, 2) + "\n");
}

process.stdout.write(selectResponse(outDir));
