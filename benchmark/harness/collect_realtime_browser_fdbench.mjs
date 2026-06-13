#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

function parseArgs(argv) {
  const args = {
    answerPaddingMs: 250,
    baseUrl: process.env.GILJOB_WEB_URL || "http://127.0.0.1",
    chromeBin: process.env.CHROME_BIN || "/usr/bin/google-chrome",
    firstDeltaTimeoutMs: 45000,
    headless: true,
    interviewPrefix: "fdbench-browser",
    joinTimeoutMs: 60000,
    playwrightPath: "",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = () => argv[++index];
    if (arg === "--base-url") args.baseUrl = next();
    else if (arg === "--chrome-bin") args.chromeBin = next();
    else if (arg === "--headed") args.headless = false;
    else if (arg === "--interview-prefix") args.interviewPrefix = next();
    else if (arg === "--join-timeout-ms") args.joinTimeoutMs = Number(next());
    else if (arg === "--first-delta-timeout-ms") args.firstDeltaTimeoutMs = Number(next());
    else if (arg === "--answer-padding-ms") args.answerPaddingMs = Number(next());
    else if (arg === "--playwright-path") args.playwrightPath = next();
    else if (arg === "--disable-gpu") args.disableGpu = true;
    else if (arg === "--keep-avatar") args.keepAvatar = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  return args;
}

function repoRootFromHere() {
  let current = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..");
  for (;;) {
    if (fs.existsSync(path.join(current, "AGENTS.md"))) return current;
    const parent = path.dirname(current);
    if (parent === current) return process.cwd();
    current = parent;
  }
}

async function loadPlaywright(explicitPath) {
  if (explicitPath) {
    return import(pathToFileURL(path.resolve(explicitPath)).href);
  }
  try {
    return await import("playwright");
  } catch {
    const repoRoot = repoRootFromHere();
    const cached = path.join(repoRoot, "benchmark/data/cache/browser-tools/node_modules/playwright/index.mjs");
    return import(pathToFileURL(cached).href);
  }
}

function safeInterviewId(prefix, exampleId) {
  let value = `${prefix}-${exampleId}`.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
  if (!/^[A-Za-z0-9]/.test(value)) value = `bench-${value}`;
  return value.slice(0, 96);
}

function redact(value) {
  return String(value)
    .replace(/access_token=[^'"\s&]+/g, "access_token=<redacted>")
    .replace(/join_request=[^'"\s&]+/g, "join_request=<redacted>")
    .replace(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, "<jwt-redacted>")
    .replace(/gj_(session|report)_[A-Za-z0-9._-]+/g, "gj_$1_<redacted>")
    .replace(/rt[A-Za-z0-9_-]*_[A-Za-z0-9._-]+/g, "rt_<redacted>")
    .replace(/eph[_-][A-Za-z0-9._-]+/g, "eph_<redacted>")
    .slice(0, 500);
}

function decodeWavMonoFloat32(filePath, maxSeconds) {
  const buffer = fs.readFileSync(filePath);
  if (buffer.toString("ascii", 0, 4) !== "RIFF" || buffer.toString("ascii", 8, 12) !== "WAVE") {
    throw new Error("payload.audio_path is not a RIFF/WAVE file");
  }
  let offset = 12;
  let fmt = null;
  let dataStart = -1;
  let dataSize = 0;
  while (offset + 8 <= buffer.length) {
    const chunkId = buffer.toString("ascii", offset, offset + 4);
    const chunkSize = buffer.readUInt32LE(offset + 4);
    if (chunkId === "fmt ") {
      fmt = {
        audioFormat: buffer.readUInt16LE(offset + 8),
        numChannels: buffer.readUInt16LE(offset + 10),
        sampleRate: buffer.readUInt32LE(offset + 12),
        bitsPerSample: buffer.readUInt16LE(offset + 22),
      };
    } else if (chunkId === "data") {
      dataStart = offset + 8;
      dataSize = Math.min(chunkSize, buffer.length - dataStart);
    }
    offset += 8 + chunkSize + (chunkSize % 2);
  }
  if (!fmt || dataStart < 0) throw new Error("wav fmt/data chunk missing");
  const bytesPerFrame = (fmt.bitsPerSample / 8) * fmt.numChannels;
  const frameCount = Math.floor(dataSize / bytesPerFrame);
  const keepFrames = Math.min(frameCount, Math.max(1, Math.round(maxSeconds * fmt.sampleRate)));
  const samples = new Float32Array(keepFrames);
  for (let frame = 0; frame < keepFrames; frame += 1) {
    const sampleOffset = dataStart + frame * bytesPerFrame;
    if (fmt.audioFormat === 3 && fmt.bitsPerSample === 32) {
      samples[frame] = buffer.readFloatLE(sampleOffset);
    } else if (fmt.audioFormat === 1 && fmt.bitsPerSample === 16) {
      samples[frame] = buffer.readInt16LE(sampleOffset) / 32768;
    } else {
      throw new Error(`unsupported wav format ${fmt.audioFormat}/${fmt.bitsPerSample}bit`);
    }
  }
  return { sampleRate: fmt.sampleRate, samples };
}

function firstAfter(marks, name, thresholdS) {
  return (marks[name] || []).find((entry) => entry.t_s >= thresholdS) || null;
}

function firstAfterMark(marks, name, mark) {
  if (!mark) return null;
  return (marks[name] || []).find((entry) => entry.hr >= mark.hr) || null;
}

function markDetailValue(mark, key) {
  return mark && Object.prototype.hasOwnProperty.call(mark.detail || {}, key) ? mark.detail[key] : undefined;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const payload = JSON.parse(await new Promise((resolve) => {
    let input = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => { input += chunk; });
    process.stdin.on("end", () => resolve(input || "{}"));
  }));
  const exampleId = String(payload.example_id || "example");
  const userAudioEndS = Number(payload.t_user_audio_end_s);
  const audioPath = path.resolve(String(payload.audio_path || ""));
  if (!Number.isFinite(userAudioEndS)) throw new Error("payload.t_user_audio_end_s is required");
  if (!audioPath || !fs.existsSync(audioPath)) throw new Error("payload.audio_path must point to an existing wav file");
  // Truncate at the annotated turn end: after this point the injected mic goes
  // silent, like a candidate who stopped speaking.
  const answerAudio = decodeWavMonoFloat32(audioPath, userAudioEndS);
  const answerAudioBase64 = Buffer.from(
    answerAudio.samples.buffer,
    answerAudio.samples.byteOffset,
    answerAudio.samples.length * 4,
  ).toString("base64");

  const interviewId = safeInterviewId(args.interviewPrefix, exampleId);
  const targetUrl = new URL(`/interviews/${encodeURIComponent(interviewId)}/room`, args.baseUrl).toString();
  const { chromium } = await loadPlaywright(args.playwrightPath);
  const marks = {};
  const diagnostics = [];
  let answerStartHr = null;
  let page = null;
  let stage = "init";

  function benchSeconds(hr) {
    if (!answerStartHr) return null;
    return Number(hr - answerStartHr) / 1e9;
  }

  function recordMark(name, detail = {}) {
    const hr = process.hrtime.bigint();
    const entry = { detail, hr, t_s: benchSeconds(hr) };
    marks[name] = marks[name] || [];
    marks[name].push(entry);
  }

  const browser = await chromium.launch({
    executablePath: args.chromeBin,
    headless: args.headless,
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      "--autoplay-policy=no-user-gesture-required",
      // The page runs short-interval gate polls (mmm-ready, signals); Chrome's
      // background/occluded throttling stretches those timers and inflates every
      // measured stage, so disable it for the benchmark browser.
      "--disable-background-timer-throttling",
      "--disable-backgrounding-occluded-windows",
      "--disable-renderer-backgrounding",
      "--disable-ipc-flooding-protection",
      ...(args.disableGpu ? ["--disable-gpu"] : []),
    ],
  });

  const currentPageSnapshot = async () => {
    if (!page) return {};
    try {
      return await page.evaluate(() => ({
        eventLog: (document.querySelector("#event-log")?.textContent || "").slice(0, 4000),
        eventLogTail: (document.querySelector("#event-log")?.textContent || "").slice(-2500),
        roomMode: document.querySelector("#room-shell")?.getAttribute("data-mode") || "",
        status: document.querySelector("#status")?.textContent || "",
        toggleMicDisabled: Boolean(document.querySelector("#toggle-mic")?.disabled),
        toggleMicText: document.querySelector("#toggle-mic")?.textContent || "",
      }));
    } catch {
      return {};
    }
  };

  const buildObservedRow = async (extra = {}) => {
    const afterEnd = userAudioEndS - 0.05;
    const sessionReady = (marks.realtime_session_ready || [])[0] || null;
    const inputCommit = firstAfter(marks, "turn_answer_end_post", afterEnd) || firstAfter(marks, "answer_end_click", afterEnd);
    const transcriptReady = firstAfter(marks, "transcript_completed_post", afterEnd);
    const mmmReady = firstAfter(marks, "mmm_ready", afterEnd);
    const responseCreate = firstAfterMark(marks, "response_create", mmmReady) || firstAfter(marks, "response_create", userAudioEndS);
    const firstAudio = firstAfterMark(marks, "first_audio_delta", responseCreate);
    const firstText = firstAfterMark(marks, "first_text_delta", responseCreate);
    const responseDone = firstAfterMark(marks, "response_done", responseCreate);
    const sdpAttachOk = (marks.sdp_attach_ok || [])[0] || null;
    const sdpAttachFailed = (marks.sdp_attach_failed || [])[0] || null;
    const stalls = marks.main_thread_stall || [];
    const realtimeEventCounts = {};
    const realtimeEventFirstTs = {};
    for (const entry of marks.realtime_server_event || []) {
      const type = String(entry.detail?.type || "unknown");
      realtimeEventCounts[type] = (realtimeEventCounts[type] || 0) + 1;
      if (!(type in realtimeEventFirstTs) && entry.t_s !== null) {
        realtimeEventFirstTs[type] = Math.round(entry.t_s * 1000) / 1000;
      }
    }
    const snapshot = await currentPageSnapshot();
    const row = {
      adapter: "realtime-browser-product-path",
      adapter_boundary: "realtime-product-path",
      avatar_render_blocked: !args.keepAvatar,
      browser_webrtc_observed: Boolean(sdpAttachOk),
      data_channel_created: Boolean((marks.data_channel_created || []).length),
      data_channel_open: Boolean((marks.data_channel_open || []).length),
      data_channel_close_count: (marks.data_channel_close || []).length,
      data_channel_error_count: (marks.data_channel_error || []).length,
      client_secret_shape_observed: Boolean(markDetailValue(sessionReady, "hasClientSecret")),
      diagnostics: [
        ...diagnostics,
        ...(snapshot.status ? [`STATUS:${redact(snapshot.status)}`] : []),
        ...(snapshot.eventLog ? [`EVENT_LOG:${String(snapshot.eventLog).slice(0, 4000)}`] : []),
        ...(snapshot.eventLogTail ? [`EVENT_LOG_TAIL:${String(snapshot.eventLogTail).slice(0, 2500)}`] : []),
      ],
      example_id: exampleId,
      full_product_path_observed: Boolean(mmmReady && responseCreate && (firstAudio || firstText)),
      interview_id: interviewId,
      main_thread_stall_count: stalls.length,
      main_thread_stall_max_ms: stalls.length
        ? Math.max(...stalls.map((entry) => Number(entry.detail?.gap_ms) || 0))
        : 0,
      raw_media_logged: false,
      realtime_event_counts: realtimeEventCounts,
      realtime_event_first_t_s: realtimeEventFirstTs,
      room_mode: snapshot.roomMode || "",
      sdp_attach_failed_status: markDetailValue(sdpAttachFailed, "status"),
      sdp_body_logged: false,
      stage,
      standard_openai_key_observed: false,
      t_user_audio_end_s: userAudioEndS,
      toggle_mic_disabled: snapshot.toggleMicDisabled,
      toggle_mic_text: snapshot.toggleMicText ? redact(snapshot.toggleMicText) : "",
      ...extra,
    };
    if (sessionReady?.t_s !== null) row.t_realtime_session_ready_s = sessionReady.t_s;
    if (inputCommit) row.t_realtime_input_commit_s = inputCommit.t_s;
    if (transcriptReady) row.t_transcript_ready_s = transcriptReady.t_s;
    if (mmmReady) row.t_mmm_ready_s = mmmReady.t_s;
    if (responseCreate) row.t_response_create_s = responseCreate.t_s;
    if (firstAudio) row.t_realtime_first_audio_delta_s = firstAudio.t_s;
    if (firstText) row.t_realtime_first_text_delta_s = firstText.t_s;
    if (responseDone) row.t_realtime_response_done_s = responseDone.t_s;
    if (!firstAudio && !firstText) {
      row.no_first_delta_reason = diagnostics.find((entry) => /SDP|Realtime|error|failed/i.test(entry)) || "first_delta_not_observed";
    }
    return row;
  };

  try {
    const context = await browser.newContext();
    await context.grantPermissions(["microphone", "camera"], { origin: new URL(args.baseUrl).origin });
    if (!args.keepAvatar) {
      // SpatialReal avatar render is an excluded boundary in the product-path
      // measurement contract, and its Gaussian-splat renderer blocks the headless
      // software-GL main thread ~1.2s per frame, inflating every measured stage.
      // Blocking the SDK import sends the app down its degraded-avatar path.
      await context.route("**/vendor/@spatialwalk/**", (route) => route.abort());
    }
    page = await context.newPage();
    await page.exposeFunction("__giljobBenchMark", (name, detail) => {
      recordMark(String(name || "unknown"), detail && typeof detail === "object" ? detail : {});
    });
    page.on("pageerror", (error) => diagnostics.push(`PAGE_ERROR:${redact(error.message)}`));
    page.on("console", (message) => {
      if (["error", "warning"].includes(message.type())) {
        diagnostics.push(`BROWSER_${message.type().toUpperCase()}:${redact(message.text())}`);
      }
    });

    await page.addInitScript(() => {
      const mark = (name, detail = {}) => {
        try {
          window.__giljobBenchMark?.(name, detail);
        } catch {
          // best-effort benchmark probe only
        }
      };
      const safeJson = (value) => {
        if (typeof value !== "string") return null;
        try {
          return JSON.parse(value);
        } catch {
          return null;
        }
      };
      const originalFetch = window.fetch;
      window.fetch = async function patchedFetch(input, init = {}) {
        const url = typeof input === "string" ? input : input?.url || "";
        const method = String(init?.method || input?.method || "GET").toUpperCase();
        const body = typeof init?.body === "string" ? init.body : "";
        const requestBody = safeJson(body);
        const requestType = requestBody?.type || requestBody?.normalizedType || "";
        const isSession = /\/api\/interviews\/[^/]+\/realtime\/session\/?$/.test(url);
        const isMmmReady = /\/api\/interviews\/[^/]+\/turns\/\d+\/mmm-ready\/?$/.test(url);
        const isTurnEvents = /\/api\/interviews\/[^/]+\/turns\/\d+\/events\/?$/.test(url);
        const isVisionEvents = /\/api\/interviews\/[^/]+\/turns\/\d+\/vision-events\/?$/.test(url);
        const isSdpAttach = /\/v1\/realtime\/calls/.test(url) || /\/realtime\/calls/.test(url) || /\/api\/interviews\/[^/]+\/realtime\/call\/?$/.test(url);
        if (isTurnEvents && method === "POST") {
          if (requestType === "analysis.transcript.completed" || requestBody?.normalizedType === "transcript.completed") {
            mark("transcript_completed_post", {});
          }
          if (requestType === "turn.answer.end" || requestBody?.normalizedType === "turn.answer_ended") {
            mark("turn_answer_end_post", {});
          }
          if (requestType === "realtime.response.create") {
            mark("response_create_sideband_post", {});
          }
        }
        if (isVisionEvents && method === "POST") {
          mark("vision_event_post", {});
        }
        if (isSdpAttach && method === "POST") {
          mark("sdp_attach_request", {});
        }
        const response = await originalFetch.apply(this, arguments);
        if (isSession) {
          response.clone().json().then((payload) => {
            const secret = payload?.client_secret || payload?.clientSecret;
            mark("realtime_session_ready", {
              hasClientSecret: Boolean(typeof secret === "string" ? secret : secret?.value),
              status: response.status,
            });
          }).catch(() => mark("realtime_session_ready", { status: response.status }));
        }
        if (isMmmReady) {
          response.clone().json().then((payload) => {
            if (payload?.full_mmm_ready === true) {
              mark("mmm_ready", { status: response.status });
            }
          }).catch(() => {});
        }
        if (isSdpAttach && method === "POST") {
          mark(response.ok ? "sdp_attach_ok" : "sdp_attach_failed", { status: response.status });
        }
        return response;
      };

      const originalCreateDataChannel = window.RTCPeerConnection?.prototype?.createDataChannel;
      if (originalCreateDataChannel) {
        window.RTCPeerConnection.prototype.createDataChannel = function patchedCreateDataChannel(...createArgs) {
          const channel = originalCreateDataChannel.apply(this, createArgs);
          mark("data_channel_created", { label: String(createArgs[0] || "") });
          channel.addEventListener("open", () => mark("data_channel_open", {}));
          channel.addEventListener("close", () => mark("data_channel_close", {}));
          channel.addEventListener("error", () => mark("data_channel_error", {}));
          return channel;
        };
      }

      const originalSend = window.RTCDataChannel?.prototype?.send;
      if (originalSend) {
        window.RTCDataChannel.prototype.send = function patchedSend(data) {
          const payload = safeJson(String(data || ""));
          const type = String(payload?.type || "");
          if (type === "response.create") {
            mark("response_create", {});
          }
          return originalSend.apply(this, arguments);
        };
      }

      const originalAddEventListener = window.EventTarget.prototype.addEventListener;
      window.EventTarget.prototype.addEventListener = function patchedAddEventListener(type, listener, options) {
        if (type === "message" && typeof listener === "function") {
          const wrapped = function wrappedMessageListener(event) {
            const payload = safeJson(event?.data);
            const eventType = String(payload?.type || "");
            if (eventType) {
              mark("realtime_server_event", { type: eventType });
            }
            if (["response.audio.delta", "response.output_audio.delta", "response.audio_transcript.delta", "response.output_audio_transcript.delta"].includes(eventType)) {
              mark("first_audio_delta", { type: eventType });
            }
            if (["response.text.delta", "response.output_text.delta", "response.audio_transcript.delta", "response.output_audio_transcript.delta"].includes(eventType)) {
              mark("first_text_delta", { type: eventType });
            }
            if (eventType === "response.done") {
              mark("response_done", {});
            }
            return listener.apply(this, arguments);
          };
          return originalAddEventListener.call(this, type, wrapped, options);
        }
        return originalAddEventListener.call(this, type, listener, options);
      };
    });

    // Benchmark-controlled microphone. Chrome's --use-file-for-fake-audio-capture
    // starts playing at getUserMedia time (room join) and loops, so the clip is
    // misaligned with the answer window. Replace every captured audio track with a
    // WebAudio stream that stays silent until the harness starts the clip at the
    // 답변 시작 click, and goes silent again after the annotated turn end.
    await page.addInitScript(() => {
      const state = { ctx: null, destination: null, samples: null, sampleRate: 16000 };
      const ensureInjectedAudio = () => {
        if (!state.ctx) {
          state.ctx = new (window.AudioContext || window.webkitAudioContext)();
          state.destination = state.ctx.createMediaStreamDestination();
        }
        return state;
      };
      window.__fdbenchLoadAnswerAudio = (base64, sampleRate) => {
        const raw = atob(base64);
        const bytes = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
        state.samples = new Float32Array(bytes.buffer);
        state.sampleRate = Number(sampleRate) || 16000;
        return state.samples.length;
      };
      window.__fdbenchStartAnswerAudio = async () => {
        const injected = ensureInjectedAudio();
        if (!state.samples || !state.samples.length) throw new Error("benchmark answer audio not loaded");
        await injected.ctx.resume();
        const audioBuffer = injected.ctx.createBuffer(1, state.samples.length, state.sampleRate);
        audioBuffer.copyToChannel(state.samples, 0);
        const source = injected.ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(injected.destination);
        source.start();
        window.__giljobBenchMark?.("bench_audio_started", { samples: state.samples.length });
        return state.samples.length / state.sampleRate;
      };
      // Main-thread starvation probe: in software-GL headless runs, canvas/WebGL
      // readbacks can block the event loop for seconds, delaying every measured
      // stage. Record any heartbeat gap above 1s so stalls are visible per run.
      let lastBeat = performance.now();
      setInterval(() => {
        const now = performance.now();
        const gap = now - lastBeat;
        if (gap > 1000) {
          window.__giljobBenchMark?.("main_thread_stall", { gap_ms: Math.round(gap) });
        }
        lastBeat = now;
      }, 250);
      const mediaDevices = navigator.mediaDevices;
      if (mediaDevices?.getUserMedia) {
        const originalGetUserMedia = mediaDevices.getUserMedia.bind(mediaDevices);
        mediaDevices.getUserMedia = async (constraints) => {
          const stream = await originalGetUserMedia(constraints);
          if (constraints?.audio) {
            const injected = ensureInjectedAudio();
            stream.getAudioTracks().forEach((track) => {
              stream.removeTrack(track);
              track.stop();
            });
            // Clone per call so consumers (Realtime peer, LiveKit publish) keep
            // independent enabled/mute state like real per-call capture tracks.
            stream.addTrack(injected.destination.stream.getAudioTracks()[0].clone());
          }
          return stream;
        };
      }
    });

    stage = "goto";
    await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: args.joinTimeoutMs });
    stage = "wait_room_shell";
    await page.waitForSelector("#room-shell", { timeout: 15000 });
    stage = "wait_realtime_connected";
    await page.waitForFunction(() => {
      const text = document.querySelector("#status")?.textContent?.toLowerCase() || "";
      return text.includes("realtime connected") || text.includes("connected");
    }, null, { timeout: args.joinTimeoutMs });
    stage = "wait_answer_enabled";
    await page.waitForFunction(() => {
      const button = document.querySelector("#toggle-mic");
      return button && !button.disabled && button.getAttribute("aria-disabled") !== "true";
    }, null, { timeout: args.joinTimeoutMs });

    stage = "load_answer_audio";
    await page.evaluate(
      ([base64, sampleRate]) => window.__fdbenchLoadAnswerAudio(base64, sampleRate),
      [answerAudioBase64, answerAudio.sampleRate],
    );

    stage = "start_answer";
    await page.click("#toggle-mic");
    await page.waitForFunction(() => {
      const button = document.querySelector("#toggle-mic");
      return button?.getAttribute("aria-pressed") === "true" || /종료|recording/i.test(button?.textContent || "");
    }, null, { timeout: 10000 });
    // Let the app finish enabling the mic tracks before speech begins so the
    // clip head is not clipped by a disabled track.
    await page.waitForTimeout(300);
    await page.evaluate(() => window.__fdbenchStartAnswerAudio());
    answerStartHr = process.hrtime.bigint();
    recordMark("answer_start", {});

    stage = "wait_user_audio_end";
    await page.waitForTimeout(Math.max(0, userAudioEndS * 1000 + args.answerPaddingMs));
    recordMark("answer_end_click", {});
    stage = "finish_answer";
    await page.click("#toggle-mic");

    stage = "wait_first_delta";
    const deadline = Date.now() + args.firstDeltaTimeoutMs;
    while (Date.now() < deadline) {
      const afterEnd = userAudioEndS - 0.05;
      const mmm = firstAfter(marks, "mmm_ready", afterEnd);
      const responseCreate = firstAfterMark(marks, "response_create", mmm) || firstAfter(marks, "response_create", userAudioEndS);
      const firstAudio = firstAfterMark(marks, "first_audio_delta", responseCreate);
      const firstText = firstAfterMark(marks, "first_text_delta", responseCreate);
      const done = firstAfterMark(marks, "response_done", responseCreate);
      if ((firstAudio || firstText) && (done || Date.now() > deadline - 2000)) {
        break;
      }
      await page.waitForTimeout(250);
    }

    const row = await buildObservedRow();
    console.log(JSON.stringify(row, Object.keys(row).sort()));
  } catch (error) {
    const row = await buildObservedRow({
      error: redact(error?.message || error),
      full_product_path_observed: false,
    });
    console.log(JSON.stringify(row, Object.keys(row).sort()));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.log(JSON.stringify({
    adapter: "realtime-browser-product-path",
    adapter_boundary: "realtime-product-path",
    error: redact(error?.message || error),
    full_product_path_observed: false,
    raw_media_logged: false,
    sdp_body_logged: false,
    standard_openai_key_observed: false,
  }, null, 0));
  process.exit(0);
});
