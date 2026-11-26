"""Standalone Google Veo pilot. Dry-run by default; no production routing."""
import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prompt", default="A static studio still life, subtle natural light movement.")
    p.add_argument("--model", choices=["veo-3.1-fast-generate-001", "veo-3.1-generate-001"], default="veo-3.1-fast-generate-001")
    p.add_argument("--aspect", choices=["9:16", "16:9"], default="9:16")
    p.add_argument("--image", help="Optional gs:// URI of an authorized PNG or JPEG")
    p.add_argument("--output", default=os.getenv("VEO_OUTPUT_GCS_URI", ""))
    p.add_argument("--job", type=Path, default=Path("veo-job.json"))
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--submit-paid", action="store_true")
    mode.add_argument("--resume", action="store_true")
    a = p.parse_args()
    if a.image and (not a.image.startswith("gs://") or not a.image.lower().endswith((".png", ".jpg", ".jpeg"))):
        p.error("image must be a gs:// PNG or JPEG URI")
    ready = bool(os.getenv("GOOGLE_CLOUD_PROJECT") and a.output.startswith("gs://") and importlib.util.find_spec("google") and importlib.util.find_spec("google.genai"))
    if not (a.submit_paid or a.resume):
        print(json.dumps({"mode": "dry-run", "model": a.model, "aspect": a.aspect, "configuration_present": ready, "live_access_verified": False, "paid_request_sent": False}))
        return
    if not ready:
        p.error("Set project and output URI, and install google-genai; verify ADC and billing separately")
    from google import genai
    from google.genai import types
    client = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"], location=os.getenv("GOOGLE_CLOUD_LOCATION") or "global")
    if a.resume:
        state = json.loads(a.job.read_text())
        if not state.get("name"):
            p.error("Submission outcome unknown; inspect provider operations before retrying")
        op = types.GenerateVideosOperation(name=state["name"])
    else:
        if a.job.exists():
            p.error("Job file exists; resume or inspect it before another paid submission")
        # Exclusive checkpoint prevents accidental duplicate submissions on this path.
        with a.job.open("x") as f:
            json.dump({"status": "submission_pending_or_unknown"}, f)
        kwargs = {}
        if a.image:
            mime = "image/png" if a.image.lower().endswith(".png") else "image/jpeg"
            kwargs["image"] = types.Image(gcs_uri=a.image, mime_type=mime)
        op = client.models.generate_videos(model=a.model, prompt=a.prompt, config=types.GenerateVideosConfig(aspect_ratio=a.aspect, output_gcs_uri=a.output, number_of_videos=1), **kwargs)
        a.job.write_text(json.dumps({"name": op.name, "status": "submitted"}))
    for _ in range(80):
        if op.done:
            break
        time.sleep(15)
        op = client.operations.get(op)
    if not op.done:
        print("Pending: resume the existing job without submitting again.", file=sys.stderr)
        return
    if op.error:
        raise RuntimeError(str(op.error))
    videos = getattr(op.response, "generated_videos", None) or []
    uris = [v.video.uri for v in videos if v.video and v.video.uri]
    if not uris:
        raise RuntimeError("No video returned; inspect operation")
    a.job.write_text(json.dumps({"name": op.name, "status": "completed", "uris": uris}))
    print(json.dumps({"uris": uris}))

if __name__ == "__main__":
    main()
