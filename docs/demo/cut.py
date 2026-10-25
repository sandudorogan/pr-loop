"""Cuts WORK/cards and WORK/frames into docs/demo.mp4 (fades) and docs/demo.gif (hard cuts, 8 fps).

Usage: cut.py WORK
"""
import os, shutil, subprocess, sys

DOCS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.abspath(sys.argv[1])
CLIPS = f"{WORK}/clips"

# (card, seconds) or (caption card, frames folder, frame ranges[, seconds]); footage plays at 12 fps.
# With seconds, the window keeps a readable width: its top half, a quick glide, then its bottom half.
SCENES = [
    ("title", 4),
    ("what", 9),
    ("cap-queue", "queue", [(1, 49)]),
    ("cap-inspect", "inspect", [(1, 70)]),
    ("cap-live", "live", [(1, 133)]),
    ("cap-fix", "fix", [(1, 40), (100, 120)]),
    ("how", 10),
    ("round", 11),
    ("covers", 10),
    ("cap-project", "project", [(1, 54)]),
    ("cap-lanes", "settings-lanes", [(1, 48)], 6.5),
    ("cap-reviewers", "settings-reviewers", [(1, 48)], 6.5),
    ("cap-fixer", "settings-fixer", [(1, 48)], 6.5),
    ("expect", 10),
    ("cap-history", "history", [(1, 54)]),
    ("cli", 7),
    ("install", 6),
]


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def card(out, fades, name, secs):
    ff("-loop", "1", "-framerate", "30", "-t", str(secs), "-i", f"{WORK}/cards/{name}.png",
       "-vf", f"format=yuv420p,{fades(secs)}", "-c:v", "libx264", "-crf", "20", out)


def footage(out, fades, name, src, ranges, pan=None):
    seq = out.removesuffix(".mp4")
    os.makedirs(seq)
    frames = [n for a, b in ranges for n in range(a, b + 1)]
    for k, n in enumerate(frames, 1):
        os.symlink(f"{WORK}/frames/{src}/{n:05d}.png", f"{seq}/{k:05d}.png")
    secs = pan or len(frames) / 12 + 0.6
    glide = f"(ih-oh)*clip((t-{secs / 2 - 0.3})/0.6,0,1)"
    size = (f"scale=w=1100:h=-2:flags=lanczos,crop=h='min(ih,870)':y='{glide}'" if pan
            else "scale=w=1800:h=870:force_original_aspect_ratio=decrease:flags=lanczos")
    ff("-loop", "1", "-framerate", "30", "-i", f"{WORK}/cards/{name}.png", "-framerate", "12", "-i", f"{seq}/%05d.png",
       "-filter_complex",
       f"[1]fps=30,tpad=stop_mode=clone:stop_duration=10,{size}[w];[0][w]overlay=x=(W-w)/2:y=190+(870-h)/2,"
       f"trim=duration={secs},format=yuv420p,{fades(secs)}",
       "-c:v", "libx264", "-crf", "20", "-r", "30", out)


def cut(out, fade):
    fades = lambda secs: f"fade=in:d={fade},fade=out:st={secs - fade}:d={fade}" if fade else "null"
    shutil.rmtree(CLIPS, ignore_errors=True)
    os.makedirs(CLIPS)
    clips = [f"{CLIPS}/{i:02d}.mp4" for i in range(len(SCENES))]
    for clip, s in zip(clips, SCENES):
        (card if len(s) == 2 else footage)(clip, fades, *s)
    with open(f"{CLIPS}/list.txt", "w") as f:
        f.writelines(f"file '{c}'\n" for c in clips)
    ff("-f", "concat", "-safe", "0", "-i", f"{CLIPS}/list.txt", "-c:v", "libx264", "-preset", "slow", "-crf", "26",
       "-pix_fmt", "yuv420p", "-movflags", "+faststart", out)


cut(f"{DOCS}/demo.mp4", 0.35)
cut(f"{WORK}/hard.mp4", 0)  # a fade repaints every pixel of every GIF frame: 4x the size
ff("-i", f"{WORK}/hard.mp4", "-filter_complex",
   "fps=8,scale=1200:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];"
   "[b][p]paletteuse=dither=none:diff_mode=rectangle", f"{DOCS}/demo.gif")
