"""QIVD 공식 행 (GilJob 소비자 LLM) — gpt-realtime-2 video+audio → 답 → 채점.
동일 29문항(seed 42). 프레임 균등 3장 + audio(질문 음성, buffer). 채점=gemma judge(동일).
문항마다 새 Realtime 세션(컨텍스트 오염 방지).
"""
import asyncio, base64, json, re, subprocess, urllib.request, urllib.error
import websockets

OPENAI_KEY = None
for line in open("/home/kio/workspace/giljob-docker/.env"):
    if line.startswith("OPENAI_API_KEY="):
        OPENAI_KEY = line.split("=", 1)[1].strip(); break
MODEL = "gpt-realtime-2"
QIVD = "/home/kio/workspace/giljob-docker/benchmark/data/raw/qivd"
GEMMA = "http://127.0.0.1:8001/v1/chat/completions"
sample = json.load(open("/tmp/qivd_run/sample.json"))

def dur(vid):
    out = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                          "-of","default=nw=1:nk=1", vid], capture_output=True, text=True).stdout
    try: return float(out.strip())
    except: return 5.0

def frames_b64(vid, n=3):
    d = dur(vid); out = []
    for k in range(n):
        t = d * (k + 0.5) / n
        raw = subprocess.run(["ffmpeg","-v","error","-ss",f"{t}","-i",vid,"-frames:v","1",
                              "-vf","scale=448:-1","-f","image2","-vcodec","mjpeg","-"],
                             capture_output=True).stdout
        if raw: out.append("data:image/jpeg;base64," + base64.b64encode(raw).decode())
    return out

def audio_b64(vid):
    pcm = subprocess.run(["ffmpeg","-v","error","-i",vid,"-f","s16le","-acodec","pcm_s16le",
                          "-ac","1","-ar","24000","-"], capture_output=True).stdout
    return base64.b64encode(pcm).decode() if pcm else None

async def realtime_answer(frames, aud):
    url = f"wss://api.openai.com/v1/realtime?model={MODEL}"
    async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                                  max_size=16_000_000) as ws:
        await ws.send(json.dumps({"type":"session.update","session":{
            "type":"realtime","output_modalities":["text"],
            "instructions":"Listen to the spoken question and look at the video frames. Give only a short, direct answer.",
            "audio":{"input":{"turn_detection":None}}}}))
        if aud:
            await ws.send(json.dumps({"type":"input_audio_buffer.append","audio":aud}))
            await ws.send(json.dumps({"type":"input_audio_buffer.commit"}))
        content = [{"type":"input_image","image_url":u} for u in frames]
        await ws.send(json.dumps({"type":"conversation.item.create",
                                  "item":{"type":"message","role":"user","content":content}}))
        await ws.send(json.dumps({"type":"response.create"}))
        txt = ""
        async for msg in ws:
            ev = json.loads(msg); t = ev.get("type","")
            if t == "error": return f"[error:{ev.get('error',{}).get('code','?')}]"
            if t.endswith("text.delta"): txt += ev.get("delta","")
            if t == "response.done": break
        return txt.strip()

def gemma(content, mt=8):
    body = json.dumps({"model":"google/gemma-4-E4B-it","max_tokens":mt,"temperature":0,
                       "messages":[{"role":"user","content":content}]}).encode()
    req = urllib.request.Request(GEMMA, data=body, headers={"Content-Type":"application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"ERR {e}"

def normalize(s): return re.sub(r"[^a-z0-9 ]","",str(s).lower()).strip()
def norm_match(ref, ans):
    r,a = normalize(ref), normalize(ans)
    if not r: return None
    if r in {"yes","no"}:
        toks=a.split(); return r==(toks[0] if toks else "")
    return r in a or any(w in a.split() for w in r.split() if len(w)>2)
def judge(ref, ans):
    v = gemma([{"type":"text","text":
        f'Reference answer: "{ref}"\nCandidate answer: "{ans}"\n'
        'Do they mean essentially the same thing for a video QA task? Reply only yes or no.'}])
    return normalize(v).startswith("yes")

async def main():
    results=[]
    for i,s in enumerate(sample):
        vid=f"{QIVD}/videos/{s['video']}"
        fr=frames_b64(vid); ab=audio_b64(vid)
        try:
            ans=await asyncio.wait_for(realtime_answer(fr,ab), timeout=70)
        except Exception as e:
            ans=f"[conn-err:{type(e).__name__}]"
        ref=s.get("short_answer") or s.get("answer") or ""
        nm=norm_match(ref,ans)
        jp=nm if nm else judge(ref,ans)
        results.append({"video":s["video"],"cat":s["category"],"q":s["question"],
                        "ref":ref,"ans":ans,"pass":bool(jp)})
        print(f"[{i+1}/29] {s['category'][:18]:18} ref={ref[:16]!r:18} ans={ans[:42]!r} -> {'O' if jp else 'X'}")
    n=len(results); p=sum(r["pass"] for r in results)
    print(f"\n== QIVD 1% (29) video+audio → gpt-realtime-2 (GilJob 소비자 LLM) ==")
    print(f"Accuracy: {p}/{n} = {p/n*100:.1f}%")
    byc={}
    for r in results:
        byc.setdefault(r["cat"],[0,0]); byc[r["cat"]][1]+=1; byc[r["cat"]][0]+=r["pass"]
    for c,(ok,tot) in sorted(byc.items(),key=lambda x:-x[1][1]):
        print(f"  {c}: {ok}/{tot}")
    json.dump(results, open("/tmp/qivd_run/results_realtime.json","w"), ensure_ascii=False, indent=2)

asyncio.run(main())
