"""One text call and one image call to Muse Glimmer on the NVIDIA free endpoint. Needs NVIDIA_NIM_API_KEY; prints no secrets."""
import base64, json, os, sys, time, urllib.request, urllib.error
sys.path.insert(0, "scripts")
from mesh_baseline import SYSTEM
from mesh_validate import validate
key = os.environ.get("NVIDIA_NIM_API_KEY")
if not key:
    sys.exit("NVIDIA_NIM_API_KEY not set in this shell")
URL = "https://integrate.api.nvidia.com/v1/chat/completions"
def call(messages, max_tokens):
    body = {"model": "meta/muse-glimmer-30b", "messages": messages, "max_tokens": max_tokens, "temperature": 0.7}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json", "Authorization": "Bearer " + key})
    t = time.time()
    try:
        r = json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:300]}, time.time() - t
    return r, time.time() - t
r, dt = call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "a wooden chair"}], 6000)
if "error" in r: print("text call failed", r)
else:
    m = r["choices"][0]["message"]; u = r.get("usage", {})
    ok, why, st = validate(m.get("content") or "")
    print(f"text: {dt:.0f}s usage={u} reasoning_field={'reasoning_content' in m or 'reasoning' in m} validate={why} {st}")
png = base64.b64encode(open("data/mesh/preview.png", "rb").read()).decode()
r, dt = call([{"role": "user", "content": [{"type": "text", "text": "List the objects you can see in this image in one short line."},
              {"type": "image_url", "image_url": {"url": "data:image/png;base64," + png}}]}], 300)
if "error" in r: print("image call failed", r)
else: print(f"image: {dt:.0f}s ->", (r["choices"][0]["message"].get("content") or "")[:300])
