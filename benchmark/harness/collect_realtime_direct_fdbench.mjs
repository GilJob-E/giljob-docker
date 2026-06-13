#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

function parseArgs(argv) {
  const args = {
    answerPaddingMs: 250,
    analysisInlineFixture: false,
    baseUrl: process.env.GILJOB_WEB_URL || "http://127.0.0.1",
    chromeBin: process.env.CHROME_BIN || "/usr/bin/google-chrome",
    firstDeltaTimeoutMs: 45000,
    forwardApiCommandOnBrowserChannel: false,
    headless: true,
    interviewPrefix: "fdbench-direct",
    playwrightPath: "",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = () => argv[++index];
    if (arg === "--base-url") args.baseUrl = next();
    else if (arg === "--analysis-inline-fixture") args.analysisInlineFixture = true;
    else if (arg === "--chrome-bin") args.chromeBin = next();
    else if (arg === "--forward-api-command-on-browser-channel") args.forwardApiCommandOnBrowserChannel = true;
    else if (arg === "--headed") args.headless = false;
    else if (arg === "--interview-prefix") args.interviewPrefix = next();
    else if (arg === "--first-delta-timeout-ms") args.firstDeltaTimeoutMs = Number(next());
    else if (arg === "--answer-padding-ms") args.answerPaddingMs = Number(next());
    else if (arg === "--playwright-path") args.playwrightPath = next();
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
  if (explicitPath) return import(pathToFileURL(path.resolve(explicitPath)).href);
  try {
    return await import("playwright");
  } catch {
    const cached = path.join(repoRootFromHere(), "benchmark/data/cache/browser-tools/node_modules/playwright/index.mjs");
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
    .replace(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, "<jwt-redacted>")
    .replace(/rt[A-Za-z0-9_-]*_[A-Za-z0-9._-]+/g, "rt_<redacted>")
    .replace(/eph[_-][A-Za-z0-9._-]+/g, "eph_<redacted>")
    .replace(/sk-[A-Za-z0-9_-]{20,}/g, "sk-<redacted>")
    .slice(0, 500);
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

  const interviewId = safeInterviewId(args.interviewPrefix, exampleId);
  const { chromium } = await loadPlaywright(args.playwrightPath);
  const browser = await chromium.launch({
    executablePath: args.chromeBin,
    headless: args.headless,
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-audio-capture=${audioPath}`,
      "--autoplay-policy=no-user-gesture-required",
    ],
  });

  try {
    const context = await browser.newContext();
    await context.grantPermissions(["microphone"], { origin: new URL(args.baseUrl).origin });
    const page = await context.newPage();
    const normalizedBaseUrl = args.baseUrl.replace(/\/$/, "");
    await page.goto(new URL("/", normalizedBaseUrl).toString(), { waitUntil: "domcontentloaded", timeout: 15000 });
    const result = await page.evaluate(async ({
      analysisInlineFixture,
      answerPaddingMs,
      baseUrl,
      firstDeltaTimeoutMs,
      forwardApiCommandOnBrowserChannel,
      interviewId,
      userAudioEndS,
    }) => {
      const marks = {};
      const diagnostics = [];
      let stage = "init";
      const mark = (name) => {
        if (!marks[name]) marks[name] = performance.now();
      };
      const bench = (name) => marks[name] === undefined || marks.answer_start === undefined ? undefined : (marks[name] - marks.answer_start) / 1000;
      const postJson = async (path, body) => {
        const response = await fetch(`${baseUrl}${path}`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(body),
        });
        const payload = await response.json().catch(() => ({}));
        return { payload, status: response.status, ok: response.ok };
      };
      const getJson = async (path) => {
        const response = await fetch(`${baseUrl}${path}`, { headers: { Accept: "application/json" } });
        const payload = await response.json().catch(() => ({}));
        return { payload, status: response.status, ok: response.ok };
      };
      const waitFor = (predicate, timeoutMs, intervalMs = 50) => new Promise((resolve, reject) => {
        const start = performance.now();
        const timer = setInterval(() => {
          if (predicate()) {
            clearInterval(timer);
            resolve(true);
            return;
          }
          if (performance.now() - start > timeoutMs) {
            clearInterval(timer);
            reject(new Error("timeout"));
          }
        }, intervalMs);
      });

      let pc = null;
      let dc = null;
      let localStream = null;
      let apiCallBrokerObserved = false;
      let apiResponseCreateObserved = false;
      let responseCommandForwardedByProbe = false;
      let responseCreateRequested = false;
      let clientSecretShapeObserved = false;
      let realtimeSessionContractObserved = false;
      let sdpAttachStatus = null;
      let fullMmmReady = false;
      try {
        stage = "realtime_session";
        const session = await postJson(`/api/interviews/${encodeURIComponent(interviewId)}/realtime/session`, {
          benchmark: "fdbench-v1-product-path",
          interviewId,
          role: "candidate",
          transport: "webrtc",
        });
        mark("realtime_session_ready");
        const secret = session.payload?.client_secret || session.payload?.clientSecret;
        const secretValue = typeof secret === "string" ? secret : secret?.value;
        clientSecretShapeObserved = Boolean(secretValue);
        realtimeSessionContractObserved = Boolean(
          session.ok && (
            clientSecretShapeObserved
            || session.payload?.webrtc
            || session.payload?.delivery
          )
        );
        if (!session.ok) {
          diagnostics.push(`realtime_session_status:${session.status}`);
          throw new Error("realtime_session_unavailable");
        }
        const sdpEndpoint = session.payload?.webrtc?.sdpEndpoint || session.payload?.sdpEndpoint || "https://api.openai.com/v1/realtime/calls";
        const callEndpoint = session.payload?.callEndpoint || session.payload?.webrtc?.callEndpoint || `/api/interviews/${encodeURIComponent(interviewId)}/realtime/call`;
        const responseEndpoint = session.payload?.responseCreateEndpoint || session.payload?.responseEndpoint || `/api/interviews/${encodeURIComponent(interviewId)}/turns/1/realtime/response`;
        const sessionId = session.payload?.sessionId || session.payload?.id || interviewId;

        stage = "peer_connection";
        pc = new RTCPeerConnection();
        dc = pc.createDataChannel("oai-events");
        dc.addEventListener("message", (event) => {
          let payload = null;
          try {
            payload = JSON.parse(String(event.data || ""));
          } catch {
            return;
          }
          const type = String(payload?.type || "");
          if (["response.audio.delta", "response.output_audio.delta", "response.audio_transcript.delta", "response.output_audio_transcript.delta"].includes(type)) {
            if (responseCreateRequested) mark("first_audio_delta");
          }
          if (["response.text.delta", "response.output_text.delta", "response.audio_transcript.delta", "response.output_audio_transcript.delta"].includes(type)) {
            if (responseCreateRequested) mark("first_text_delta");
          }
          if (type === "response.done") {
            if (responseCreateRequested) mark("response_done");
          }
        });
        localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        localStream.getAudioTracks().forEach((track) => {
          track.enabled = false;
          pc.addTrack(track, localStream);
        });
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        mark("sdp_attach_request");
        let answerSdp = "";
        if (secretValue) {
          stage = "sdp_attach_direct";
          const sdpResponse = await fetch(sdpEndpoint, {
            method: "POST",
            headers: {
              Authorization: `Bearer ${secretValue}`,
              "Content-Type": "application/sdp",
            },
            body: offer.sdp,
          });
          sdpAttachStatus = sdpResponse.status;
          answerSdp = await sdpResponse.text();
          if (!sdpResponse.ok || !answerSdp.trim()) {
            diagnostics.push(`sdp_attach_status:${sdpResponse.status}`);
            throw new Error("sdp_attach_failed");
          }
        } else {
          stage = "sdp_attach_api_broker";
          const call = await postJson(callEndpoint, {
            sdp: offer.sdp,
            sessionId,
            model: session.payload?.model,
            voice: session.payload?.voice,
          });
          sdpAttachStatus = call.status;
          apiCallBrokerObserved = true;
          const answer = call.payload?.sdpAnswer || call.payload?.answer;
          answerSdp = typeof answer === "string" ? answer : answer?.sdp;
          if (!call.ok || !String(answerSdp || "").trim()) {
            diagnostics.push(`sdp_attach_broker_status:${call.status}:${call.payload?.error || "unknown"}`);
            throw new Error("sdp_attach_broker_failed");
          }
        }
        await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
        mark("sdp_attach_ok");
        stage = "data_channel_open";
        await waitFor(() => dc.readyState === "open", 10000);
        const postConnectUpdate = session.payload?.webrtc?.postConnectSessionUpdate;
        if (postConnectUpdate?.type === "session.update" && typeof postConnectUpdate.session === "object") {
          dc.send(JSON.stringify(postConnectUpdate));
          mark("post_connect_session_update");
        }

        stage = "candidate_audio";
        mark("answer_start");
        localStream.getAudioTracks().forEach((track) => { track.enabled = true; });
        await new Promise((resolve) => setTimeout(resolve, Math.max(0, userAudioEndS * 1000 + answerPaddingMs)));
        localStream.getAudioTracks().forEach((track) => { track.enabled = false; });
        mark("answer_audio_end");

        stage = "sideband_mmm";
        await postJson(`/api/interviews/${encodeURIComponent(interviewId)}/turns/1/events`, {
          type: "analysis.transcript.completed",
          transcript: "benchmark answer transcript",
          rawMediaIncluded: false,
        });
        mark("transcript_completed_post");
        await postJson(`/api/interviews/${encodeURIComponent(interviewId)}/turns/1/events`, {
          type: "turn.answer.end",
          detail: { transcriptAvailable: true },
          rawMediaIncluded: false,
        });
        mark("turn_answer_end_post");
        await postJson(`/api/interviews/${encodeURIComponent(interviewId)}/turns/1/events`, {
          type: "prosody.window_metrics",
          rawMediaIncluded: false,
        });
        await postJson(`/api/interviews/${encodeURIComponent(interviewId)}/turns/1/vision-events`, {
          type: "vision.frame_metrics",
          rawFrameIncluded: false,
          rawMediaIncluded: false,
        });
        const ready = await getJson(`/api/interviews/${encodeURIComponent(interviewId)}/turns/1/mmm-ready`);
        fullMmmReady = Boolean(ready.payload?.full_mmm_ready);
        if (!fullMmmReady) {
          diagnostics.push(`mmm_ready_status:${ready.status}:${ready.payload?.reason || "not_ready"}`);
          throw new Error("mmm_not_ready");
        }
        mark("mmm_ready");
        stage = "response_create";
        const responseBody = {
          reason: "fdbench-full-mmm-ready",
          sessionId,
          response: {
            outputModalities: ["audio"],
            instructions: "한국어 면접관으로서 내부 구현을 언급하지 말고 짧은 후속 질문 하나만 하세요.",
          },
        };
        if (analysisInlineFixture) {
          responseBody.analysisResult = {
            schemaVersion: "giljob-benchmark-inline-analysis/v0",
            status: "ready",
            confidence: 0,
            latencyMs: 0,
            candidatePromptFragment: "지원자의 최근 답변에서 핵심 선택과 본인의 역할을 더 구체적으로 묻는 짧은 한국어 후속 질문을 하세요.",
            rawTranscriptLogged: false,
            rawMediaAccepted: false,
          };
        }
        responseCreateRequested = true;
        const response = await postJson(responseEndpoint, responseBody);
        apiResponseCreateObserved = true;
        if (!response.ok) {
          diagnostics.push(`response_create_status:${response.status}:${response.payload?.error || "unknown"}:${response.payload?.responseCreate?.reason || "unknown"}`);
          throw new Error("response_create_failed");
        }
        await postJson(`/api/interviews/${encodeURIComponent(interviewId)}/turns/1/events`, {
          type: "realtime.response.create",
          detail: { reason: "fdbench-full-mmm-ready", owner: "api" },
          rawMediaIncluded: false,
        });
        mark("response_create");
        if (forwardApiCommandOnBrowserChannel) {
          const command = response.payload?.sideband?.command;
          if (command?.type === "response.create" && dc?.readyState === "open") {
            dc.send(JSON.stringify(command));
            responseCommandForwardedByProbe = true;
          } else {
            diagnostics.push("response_command_forward_skipped");
          }
        }
        stage = "first_delta";
        await waitFor(() => marks.first_audio_delta !== undefined || marks.first_text_delta !== undefined || marks.response_done !== undefined, firstDeltaTimeoutMs, 100);
      } catch (error) {
        diagnostics.push(`stage_error:${stage}:${error?.message || String(error)}`);
      } finally {
        localStream?.getTracks().forEach((track) => track.stop());
        pc?.close();
      }
      const firstDeltaObserved = marks.first_audio_delta !== undefined || marks.first_text_delta !== undefined;
      const row = {
        adapter: "realtime-direct-browser-product-path",
        adapter_boundary: "realtime-product-path",
        analysis_inline_fixture_used: analysisInlineFixture,
        api_call_broker_observed: apiCallBrokerObserved,
        api_response_create_observed: apiResponseCreateObserved,
        browser_webrtc_observed: marks.sdp_attach_ok !== undefined,
        client_secret_shape_observed: clientSecretShapeObserved,
        diagnostics,
        full_mmm_ready: fullMmmReady,
        full_product_path_observed: Boolean(fullMmmReady && marks.response_create !== undefined && firstDeltaObserved && !analysisInlineFixture && !responseCommandForwardedByProbe),
        raw_media_logged: false,
        realtime_session_contract_observed: realtimeSessionContractObserved,
        response_command_forwarded_by_probe: responseCommandForwardedByProbe,
        sdp_attach_failed_status: marks.sdp_attach_ok === undefined ? sdpAttachStatus : undefined,
        sdp_body_logged: false,
        stage,
        standard_openai_key_observed: false,
        technical_realtime_first_delta_observed: firstDeltaObserved,
        t_user_audio_end_s: userAudioEndS,
      };
      if (bench("realtime_session_ready") !== undefined) row.t_realtime_session_ready_s = bench("realtime_session_ready");
      if (bench("answer_audio_end") !== undefined) row.t_realtime_input_commit_s = bench("answer_audio_end");
      if (bench("transcript_completed_post") !== undefined) row.t_transcript_ready_s = bench("transcript_completed_post");
      if (bench("mmm_ready") !== undefined) row.t_mmm_ready_s = bench("mmm_ready");
      if (bench("response_create") !== undefined) row.t_response_create_s = bench("response_create");
      if (bench("first_audio_delta") !== undefined) row.t_realtime_first_audio_delta_s = bench("first_audio_delta");
      if (bench("first_text_delta") !== undefined) row.t_realtime_first_text_delta_s = bench("first_text_delta");
      if (bench("response_done") !== undefined) row.t_realtime_response_done_s = bench("response_done");
      return row;
    }, {
      analysisInlineFixture: args.analysisInlineFixture,
      answerPaddingMs: args.answerPaddingMs,
      baseUrl: args.baseUrl.replace(/\/$/, ""),
      firstDeltaTimeoutMs: args.firstDeltaTimeoutMs,
      forwardApiCommandOnBrowserChannel: args.forwardApiCommandOnBrowserChannel,
      interviewId,
      userAudioEndS,
    });
    result.example_id = exampleId;
    result.interview_id = interviewId;
    console.log(JSON.stringify(result, Object.keys(result).sort()));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.log(JSON.stringify({
    adapter: "realtime-direct-browser-product-path",
    adapter_boundary: "realtime-product-path",
    error: redact(error?.message || error),
    full_product_path_observed: false,
    raw_media_logged: false,
    sdp_body_logged: false,
    standard_openai_key_observed: false,
  }));
  process.exit(0);
});
