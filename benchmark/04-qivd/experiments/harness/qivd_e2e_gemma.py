"""QIVD 공식 행 end-to-end — video frames + audio(spoken question) → gemma-4-E4B → 답 → 채점.
1% 랜덤 29문항(seed 42). 질문은 오디오로만 제공(순수 video+audio QA). 채점=정규화+gemma judge.
"""
import base64, json, re, subprocess, urllib.request
QIVD = "/home/kio/workspace/giljob-docker/benchmark/data/raw/qivd"
URL = "http://127.0.0.1:8001/v1/chat/completions"
MODEL = "google/gemma-4-E4B-it"
sample = json.load(open("/tmp/qivd_run/sample.json"))

def gemma(content, max_tokens=64):
    body = json.dumps({"model": MODEL, "max_tokens": max_tokens, "temperature": 0,
                       "messages": [{"role": "user", "content": content}]}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    for _ in range(2):
        try:
            r = urllib.request.urlopen(req, timeout=120)
            return json.load(r)["choices"][0]["message"]["content"].strip()
        except Exception as e:
            last = f"ERR {type(e).__name__}: {getattr(e,'read',lambda:b'')()[:150] if hasattr(e,'read') else e}"
    return last

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
        if raw: out.append(base64.b64encode(raw).decode())
    return out

def audio_b64(vid):
    wav = subprocess.run(["ffmpeg","-v","error","-i",vid,"-f","wav","-acodec","pcm_s16le",
                          "-ac","1","-ar","16000","-"], capture_output=True).stdout
    return base64.b64encode(wav).decode() if wav else None

def normalize(s):
    return re.sub(r"[^a-z0-9 ]","",str(s).lower()).strip()

def norm_match(ref, ans):
    r, a = normalize(ref), normalize(ans)
    if not r: return None
    if r in {"yes","no"}:
        toks = a.split()
        return r == (toks[0] if toks else "")
    return r in a or any(w in a.split() for w in r.split() if len(w) > 2)

def judge(ref, ans):
    v = gemma([{"type":"text","text":
        f'Reference answer: "{ref}"\nCandidate answer: "{ans}"\n'
        'Do they mean essentially the same thing for a video QA task? Reply only yes or no.'}], 8)
    return normalize(v).startswith("yes")

results = []
for i, s in enumerate(sample):
    vid = f"{QIVD}/videos/{s['video']}"
    content = [{"type":"text","text":
        "You are answering a spoken question about a short video. "
        "Listen to the question in the audio and look at the video frames. "
        "Give only a short, direct answer."}]
    for b in frames_b64(vid):
        content.append({"type":"image_url","image_url":{"url":"data:image/jpeg;base64,"+b}})
    ab = audio_b64(vid)
    if ab:
        content.append({"type":"input_audio","input_audio":{"data":ab,"format":"wav"}})
    ans = gemma(content)
    ref = s.get("short_answer") or s.get("answer") or ""
    nm = norm_match(ref, ans)
    jp = nm if nm else judge(ref, ans)
    results.append({"video":s["video"],"cat":s["category"],"q":s["question"],
                    "ref":ref,"ans":ans,"norm":nm,"pass":bool(jp)})
    print(f"[{i+1}/29] {s['category'][:18]:18} ref={ref[:18]!r:20} ans={ans[:40]!r} -> {'O' if jp else 'X'}")

n = len(results); p = sum(r["pass"] for r in results)
print(f"\n== QIVD 1% (29문항) video+audio → gemma-4-E4B ==")
print(f"Accuracy: {p}/{n} = {p/n*100:.1f}%")
from collections import Counter
byc = {}
for r in results:
    byc.setdefault(r["cat"], [0,0])
    byc[r["cat"]][1]+=1; byc[r["cat"]][0]+= r["pass"]
print("카테고리별:")
for c,(ok,tot) in sorted(byc.items(), key=lambda x:-x[1][1]):
    print(f"  {c}: {ok}/{tot}")
json.dump(results, open("/tmp/qivd_run/results.json","w"), ensure_ascii=False, indent=2)
