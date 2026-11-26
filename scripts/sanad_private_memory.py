"""SANAD STUDIO private memory pilot; no GitHub media, cache, or publishing."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["OPENMONTAGE_ASSET_CACHE"] = "0"
PROMPT = """A single authentic home-video shot, horizontal 16:9. Reference 1 is the exact opening composition of a happy family group in their living room; preserve every person, clothing, relative placement and warm light. Reference 2 is the adult man who is missing from the group, preserve his recognizable face and clothes. At once, he enters naturally from the right, smiles, and says in natural Saudi Arabic exactly: أبي أصوّر. Complete that spoken line before second 3.5. The family smiles and makes space for him; he joins the group without covering anyone. Camera stays fixed; hold the happy group by second 4.5. No text, subtitles, music, cuts, new people, or face morphing. Only quiet room ambience and this single spoken line. Reconstructed memory, not documentary footage."""
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    p.add_argument("--group", type=Path)
    p.add_argument("--person", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--approve-generation", action="store_true")
    a = p.parse_args()
    from tools.video.veo_video import VeoVideo
    from tools.google_credentials import resolve_project_id, resolve_google_location
    tool = VeoVideo()
    config = {"backend":"google","operation":"reference_to_video","model_variant":"veo3.1/fast",
              "duration":"8s","resolution":"720p","aspect_ratio":"16:9",
              "generate_audio":True,"auto_fix":False}
    vertex_flag = any(os.getenv(k,"").lower() in ("true","1") for k in
                      ("GOOGLE_GENAI_USE_VERTEXAI","GOOGLE_GENAI_USE_ENTERPRISE"))
    adc_file = Path(os.getenv("GOOGLE_APPLICATION_CREDENTIALS","/nonexistent"))
    try:
        sdk = importlib.util.find_spec("google.genai") is not None
    except ModuleNotFoundError:
        sdk = False
    readiness = {"vertex_configured": vertex_flag or adc_file.is_file(),
                 "project_configured":bool(resolve_project_id()),"google_sdk":sdk,
                 "ffmpeg":bool(shutil.which("ffmpeg")),"ffprobe":bool(shutil.which("ffprobe")),
                 "region":resolve_google_location(),"live_generation_verified":False,
                 "generation_submitted":False}
    print(json.dumps(readiness),flush=True)
    if a.check:
        return
    if not a.approve_generation:
        p.error("Explicit approval of provider generation and any cost is required.")
    if not all(readiness[k] for k in ("vertex_configured","project_configured","google_sdk","ffmpeg","ffprobe")):
        p.error("Run --check and configure Vertex before generation.")
    if not all((a.group,a.person,a.output)):
        p.error("Provide two local images and a private output path.")
    private = (Path.home()/".sanad-private").resolve()
    private.mkdir(mode=0o700,exist_ok=True)
    group,person,out = (x.resolve() for x in (a.group,a.person,a.output))
    if any(not x.is_relative_to(private) for x in (group,person,out)):
        p.error("All media must be within ~/.sanad-private, never the repository.")
    if out.suffix.lower()!=".mp4" or out.exists():
        p.error("Use a new MP4 output path.")
    for x in (group,person):
        if not x.is_file() or x.suffix.lower() not in (".jpg",".jpeg",".png") or x.stat().st_size>10_000_000:
            p.error("Expected local JPG or PNG, maximum 10 MB each.")
    from PIL import Image
    for x in (group,person):
        with Image.open(x) as im: im.verify()
    # Single submission per run; never automatically retry uncertain provider outcomes.
    with tempfile.TemporaryDirectory(prefix="memory-",dir=private) as tmp:
        raw=Path(tmp)/"raw.mp4"
        result=tool.execute(dict(config,prompt=PROMPT,reference_image_paths=[str(group),str(person)],output_path=str(raw)))
        if not result.success or not raw.is_file():
            raise SystemExit("Veo generation failed or outcome unknown; no fallback or automatic retry.")
        clip=Path(tmp)/"final.mp4"
        # Use original photo for the opening 0.5s, followed by 4.5s of generated footage.
        scale="scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,format=yuv420p"
        vf="[0:v]"+scale+",trim=duration=0.5,setpts=PTS-STARTPTS[v0];[1:v]"+scale+",trim=duration=4.5,setpts=PTS-STARTPTS[v1];[v0][v1]concat=n=2:v=1:a=0[v];[1:a]atrim=duration=4.5,asetpts=PTS-STARTPTS,adelay=500:all=1,apad=whole_dur=5[a]"
        subprocess.run(["ffmpeg","-nostdin","-v","error","-loop","1","-framerate","24","-i",str(group),"-i",str(raw),"-filter_complex",vf,"-map","[v]","-map","[a]","-t","5","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-movflags","+faststart",str(clip)],check=True,timeout=120)
        probe=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration:stream=codec_type","-of","json",str(clip)],text=True))
        if abs(float(probe["format"]["duration"])-5)>0.06 or {s["codec_type"] for s in probe["streams"]}!={"audio","video"}:
            raise SystemExit("Final clip failed technical quality check")
        out.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with out.open("xb") as dst,clip.open("rb") as src:
            os.chmod(out,0o600)
            shutil.copyfileobj(src,dst)
    print(json.dumps({"technical_check":"passed","duration_seconds":5,"output":str(out),"needs_visual_and_dialogue_review":True,"published":False,"cached":False}),flush=True)
if __name__=="__main__":
    main()
