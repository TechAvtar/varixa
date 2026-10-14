"""Build the Verixa product demo video.

    python demo/make_demo.py voice    # ElevenLabs narration per scene + word timestamps
    node   demo/record.mjs            # Playwright recording paced to the narration
    python demo/make_demo.py edit     # music, mix, subtitles, final render

Run with the OpenMontage virtualenv (it provides the tools used here):
    C:/Users/Shivam/tools/OpenMontage/.venv/Scripts/python demo/make_demo.py <step>

Tools from OpenMontage: elevenlabs_tts (narration with character alignment), music_gen
(ElevenLabs instrumental), subtitle_gen (cues from word timestamps), audio_mixer (narration over
ducked music, loudness normalised). ffmpeg does the video edit.

Sync: every scene's video is cut from the recording, waiting time removed, and held until the
scene's narration has finished. The narration clip for a scene starts LEAD seconds after the
scene's first frame, and every subtitle word is that scene's ElevenLabs timestamp plus the same
offset, so picture, voice and subtitles share one timeline.

The API key is read from demo/.env and never printed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
VOICE = OUT / "voice"
RAW = OUT / "raw"
WORK = OUT / "work"
OPENMONTAGE = Path(os.environ.get("OPENMONTAGE_DIR", r"C:\Users\Shivam\tools\OpenMontage"))
sys.path.insert(0, str(OPENMONTAGE))

FPS = 30
LEAD = 0.25  # narration starts this long after the scene's first frame
MUSIC_PROMPT = (
    "Calm, modern, minimal instrumental for a software product walkthrough: soft felt piano, "
    "warm synth pads, light plucked arpeggio, gentle pulse around 90 BPM, optimistic and focused, "
    "no drums build-ups, no vocals, unobtrusive background under narration"
)


def load_env() -> None:
    for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if value.strip():
                os.environ[key.strip()] = value.strip().strip('"').strip("'")
    if not os.environ.get("ELEVENLABS_API_KEY"):
        sys.exit("demo/.env has no ELEVENLABS_API_KEY")


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(list(args), check=True, cwd=cwd)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return float(out.strip())


def script() -> dict:
    return json.loads((HERE / "script.json").read_text(encoding="utf-8"))


# -- step 1: narration ---------------------------------------------------------------------------


def voice() -> None:
    load_env()
    from tools.audio.elevenlabs_tts import ElevenLabsTTS

    data = script()
    settings = data["voice"]
    tts = ElevenLabsTTS()
    VOICE.mkdir(parents=True, exist_ok=True)
    durations: dict[str, float] = {}
    scenes = data["scenes"]
    for i, scene in enumerate(scenes):
        out = VOICE / f"{scene['id']}.mp3"
        inputs = {
            "text": scene["text"],
            "voice_id": os.environ["ELEVENLABS_VOICE_ID"],
            "model_id": settings["model_id"],
            "stability": settings["stability"],
            "similarity_boost": settings["similarity_boost"],
            "style": settings["style"],
            "speed": settings["speed"],
            "with_timestamps": True,
            "output_path": str(out),
            "seed": 4242,
        }
        # Neighbouring lines keep intonation continuous across separately generated clips.
        if i > 0:
            inputs["previous_text"] = scenes[i - 1]["text"]
        if i + 1 < len(scenes):
            inputs["next_text"] = scenes[i + 1]["text"]
        result = tts.execute(inputs)
        if not result.success:
            sys.exit(f"{scene['id']}: {result.error}")
        durations[scene["id"]] = round(probe_duration(out), 3)
        words = result.data["word_timestamps"]
        print(f"{scene['id']}: {durations[scene['id']]:.2f}s, {len(words)} words")
    (VOICE / "durations.json").write_text(json.dumps(durations, indent=2), encoding="utf-8")
    print(f"total narration {sum(durations.values()):.1f}s")


# -- step 3: edit ----------------------------------------------------------------------------------


def build_master(frames: list[dict], t_first: float, t_last: float) -> Path:
    """Variable-rate screencast frames -> constant 30 fps video on the recording clock.

    Output frame k shows whichever screencast frame was on screen at t_first + k/30. The JPEGs are
    piped to ffmpeg one per output frame; the concat demuxer cannot be used because it rounds
    every frame shorter than 1/25 s up to 1/25 s, and the drift accumulates over the recording.
    """
    WORK.mkdir(parents=True, exist_ok=True)
    master = WORK / "master.mp4"
    total = int((t_last - t_first) * FPS)
    proc = subprocess.Popen(
        [
            "ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS),
            "-c:v", "mjpeg", "-i", "-",
            "-vf", "scale=1920:1080:flags=lanczos,format=yuv420p",
            "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-r", str(FPS), str(master),
        ],
        stdin=subprocess.PIPE,
    )
    assert proc.stdin is not None
    idx = 0
    cache: tuple[int, bytes] | None = None
    for k in range(total):
        t = t_first + k / FPS
        while idx + 1 < len(frames) and frames[idx + 1]["t"] <= t:
            idx += 1
        if cache is None or cache[0] != idx:
            cache = (idx, (RAW / "frames" / frames[idx]["file"]).read_bytes())
        proc.stdin.write(cache[1])
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg failed while assembling the master video")
    return master


def scene_pieces(scene: dict, excluded: list[dict]) -> list[tuple[float, float]]:
    """The scene's time range minus the excluded (waiting) intervals inside it."""
    pieces = [(scene["start"], scene["end"])]
    for ex in sorted(excluded, key=lambda e: e["start"]):
        nxt = []
        for a, b in pieces:
            if ex["end"] <= a or ex["start"] >= b:
                nxt.append((a, b))
                continue
            if ex["start"] > a:
                nxt.append((a, ex["start"]))
            if ex["end"] < b:
                nxt.append((ex["end"], b))
        pieces = nxt
    return [(a, b) for a, b in pieces if b - a > 0.05]


def render_scene(master: Path, t_first: float, pieces, hold_to: float, out: Path) -> float:
    """Cut the pieces from the master, join them, and freeze the last frame up to hold_to s."""
    parts = []
    filters = []
    for k, (a, b) in enumerate(pieces):
        filters.append(
            f"[0:v]trim=start={a - t_first:.3f}:end={b - t_first:.3f},setpts=PTS-STARTPTS[p{k}]"
        )
        parts.append(f"[p{k}]")
    length = sum(b - a for a, b in pieces)
    pad = max(hold_to - length, 0)
    filters.append(
        f"{''.join(parts)}concat=n={len(parts)}:v=1:a=0,"
        f"tpad=stop_mode=clone:stop_duration={pad:.3f},fps={FPS},format=yuv420p[v]"
    )
    run(
        "ffmpeg", "-v", "error", "-y", "-i", str(master), "-filter_complex", ";".join(filters),
        "-map", "[v]", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-r", str(FPS),
        str(out),
    )
    return probe_duration(out)


def edit() -> None:
    load_env()
    from tools.audio.audio_mixer import AudioMixer
    from tools.audio.music_gen import MusicGen
    from tools.subtitle.subtitle_gen import SubtitleGen

    data = script()
    gap = data.get("gap_after_seconds", 0.6)
    durations = json.loads((VOICE / "durations.json").read_text(encoding="utf-8"))
    frames = json.loads((RAW / "frames.json").read_text(encoding="utf-8"))
    marks = json.loads((RAW / "marks.json").read_text(encoding="utf-8"))
    frames.sort(key=lambda f: f["t"])
    t_first = frames[0]["t"]
    t_last = marks.get("recording_end", frames[-1]["t"] + 1)

    silent = WORK / "silent.mp4"
    timeline_file = OUT / "timeline.json"
    reuse = os.environ.get("DEMO_REUSE_CUT") == "1" and silent.exists() and timeline_file.exists()
    timeline = []
    offset = 0.0
    if reuse:
        print("1-2/6 reusing the cut scenes (DEMO_REUSE_CUT=1)")
        timeline = json.loads(timeline_file.read_text(encoding="utf-8"))
        offset = sum(t["length"] for t in timeline)
    else:
        print("1/6 assembling the screencast frames")
        master = build_master(frames, t_first, t_last)
        print("2/6 cutting scenes to the narration")
        scene_dir = WORK / "scenes"
        shutil.rmtree(scene_dir, ignore_errors=True)
        scene_dir.mkdir(parents=True)
    for idx, scene in enumerate([] if reuse else marks["scenes"]):
        pieces = scene_pieces(scene, marks["excluded"])
        need = LEAD + durations[scene["id"]] + gap
        clip = scene_dir / f"{idx:02d}_{scene['id']}.mp4"
        length = render_scene(master, t_first, pieces, need, clip)
        timeline.append({"id": scene["id"], "start": offset, "length": length, "clip": clip})
        print(f"   {scene['id']:16s} at {offset:6.2f}s  video {length:5.2f}s  voice {durations[scene['id']]:5.2f}s")
        offset += length
    total = offset

    if not reuse:
        listing = WORK / "scenes.txt"
        listing.write_text("\n".join(f"file '{Path(t['clip']).as_posix()}'" for t in timeline), encoding="utf-8")
        run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent))

    print("3/6 subtitles from the ElevenLabs word timestamps")
    # One subtitle run per scene: cues must never span the pause between two narration clips,
    # or the next scene's first words would appear before they are spoken.
    cue_blocks: list[str] = []
    for t in timeline:
        align = json.loads((VOICE / f"{t['id']}.mp3.alignment.json").read_text(encoding="utf-8"))
        base = t["start"] + LEAD
        words = [
            {"word": w["word"], "start": round(base + w["start"], 3), "end": round(base + w["end"], 3)}
            for w in align["words"]
        ]
        segment = {"start": words[0]["start"], "end": words[-1]["end"], "text": " ".join(w["word"] for w in words), "words": words}
        part = WORK / f"subs_{t['id']}.srt"
        result = SubtitleGen().execute(
            {"segments": [segment], "format": "srt", "output_path": str(part), "max_words_per_cue": 9, "max_chars_per_line": 48}
        )
        if not result.success:
            sys.exit(f"subtitles: {result.error}")
        for block in part.read_text(encoding="utf-8").strip().split("\n\n"):
            cue_blocks.append("\n".join(block.splitlines()[1:]))  # drop the per-file cue number
    srt = OUT / "verixa-demo.srt"
    srt.write_text("\n\n".join(f"{i}\n{b}" for i, b in enumerate(cue_blocks, 1)) + "\n", encoding="utf-8")

    print("4/6 background music (ElevenLabs)")
    music = OUT / "music.mp3"
    if not music.exists() or probe_duration(music) < total:
        result = MusicGen().execute(
            {"prompt": MUSIC_PROMPT, "duration_seconds": min(round(total + 2), 600), "output_path": str(music), "force_instrumental": True}
        )
        if not result.success:
            sys.exit(f"music: {result.error}")

    print("5/6 mixing narration over ducked music")
    tracks = [
        {"path": str(VOICE / f"{t['id']}.mp3"), "role": "speech", "start_seconds": round(t["start"] + LEAD, 3)}
        for t in timeline
    ]
    tracks.append({"path": str(music), "role": "music", "volume": 0.32, "fade_in_seconds": 1.5, "fade_out_seconds": 3.0})
    mixed = WORK / "mix.wav"
    result = AudioMixer().execute(
        {
            "operation": "full_mix",
            "tracks": tracks,
            "ducking": {"enabled": True, "music_volume_during_speech": 0.12, "attack_ms": 150, "release_ms": 600},
            "normalize": True,
            "loudnorm_target": -16,
            "target_duration": round(total, 3),
            "output_path": str(mixed),
        }
    )
    if not result.success:
        sys.exit(f"mix: {result.error}")

    print("6/6 final render with burned-in subtitles")
    final = OUT / "verixa-demo.mp4"
    style = (
        "FontName=Segoe UI,FontSize=15,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,"
        "BackColour=&H96000000,BorderStyle=4,Outline=0,Shadow=0,MarginV=22,Alignment=2"
    )
    # The subtitles filter is run from OUT with a relative path: a Windows drive colon would
    # otherwise be parsed as a filter option separator.
    vf = f"subtitles={srt.name}:force_style='{style}',fade=t=in:st=0:d=0.6,fade=t=out:st={total - 1.2:.2f}:d=1.2"
    run(
        "ffmpeg", "-v", "error", "-y", "-i", str(silent), "-i", str(mixed), "-vf", vf,
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
        str(final.name), cwd=OUT,
    )
    (OUT / "timeline.json").write_text(
        json.dumps([{k: (str(v) if isinstance(v, Path) else v) for k, v in t.items()} for t in timeline], indent=2),
        encoding="utf-8",
    )
    print(f"done: {final}  ({probe_duration(final):.1f}s)")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    {"voice": voice, "edit": edit}.get(step, lambda: sys.exit(__doc__))()
