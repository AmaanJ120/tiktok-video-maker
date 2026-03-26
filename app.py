import os
import uuid
import subprocess
from datetime import datetime
from flask import Flask, request, jsonify, send_file, render_template, abort

app = Flask(__name__)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
FONT_FILE = os.path.join(os.path.dirname(__file__), "fonts", "Roboto-Bold.ttf")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


def get_ffmpeg_font_path():
    """Return font path in FFmpeg drawtext-safe format for Windows."""
    abs_path = os.path.abspath(FONT_FILE)
    # Forward slashes, then escape the drive colon: C:/ -> C\:/
    forward = abs_path.replace("\\", "/")
    escaped = forward.replace(":/", "\\:/", 1)
    return escaped


def sanitize_for_drawtext(text):
    """Escape characters that break FFmpeg drawtext filter."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\u2019")   # straight apostrophe -> curly (safe)
    text = text.replace(":", "\\:")
    text = text.replace("%", "\\%")
    return text


def has_audio_stream(file_path):
    """Return True if the file contains at least one audio stream."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "audio"


def build_clip_filter(clip, index, font_path, font_size, text_y, clip_has_audio):
    """
    Build the filter_complex segment for one clip.
    - Trims to [start, start+duration]
    - Scales + crops to 1080x1920 (TikTok vertical)
    - Draws title text at the top
    - Handles clips with no audio by generating silence
    """
    start = float(clip.get("start", 0))
    duration = float(clip.get("duration", 15))
    label = sanitize_for_drawtext(clip.get("label", ""))
    i = index

    # Scale: enlarge so the video covers 1080x1920, then crop the overflow.
    # force_original_aspect_ratio=increase ensures no letterboxing.
    video_filter = (
        f"[{i}:v]"
        f"trim=start={start}:duration={duration},"
        f"setpts=PTS-STARTPTS,"
        f"scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,"
        f"fps=30,"
        f"drawtext="
            f"fontfile='{font_path}':"
            f"text='{label}':"
            f"fontsize={font_size}:"
            f"fontcolor=white:"
            f"borderw=4:"
            f"bordercolor=black@0.8:"
            f"x=(w-text_w)/2:"
            f"y={text_y}:"
            f"shadowx=2:shadowy=2:shadowcolor=black@0.6"
        f"[v{i}];"
    )

    if clip_has_audio:
        audio_filter = (
            f"[{i}:a]"
            f"atrim=start={start}:duration={duration},"
            f"asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=44100:channel_layouts=stereo"
            f"[a{i}];"
        )
    else:
        # Generate silent audio for clips with no audio track
        audio_filter = (
            f"aevalsrc=0:c=stereo:r=44100:d={duration}"
            f"[a{i}];"
        )

    return video_filter + audio_filter


def build_concat_command(clips, clip_audio_flags, output_path, font_size, text_y):
    """Build the full FFmpeg subprocess argument list for N clips."""
    font_path = get_ffmpeg_font_path()
    n = len(clips)

    inputs = []
    for clip in clips:
        file_path = os.path.join(UPLOAD_DIR, clip["upload_id"] + ".mp4")
        inputs += ["-i", file_path]

    filter_parts = []
    for i, (clip, has_audio) in enumerate(zip(clips, clip_audio_flags)):
        filter_parts.append(
            build_clip_filter(clip, i, font_path, font_size, text_y, has_audio)
        )

    # concat expects streams interleaved per segment: [v0][a0][v1][a1]...
    interleaved = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_parts.append(
        f"{interleaved}concat=n={n}:v=1:a=1[vout][aout]"
    )

    filter_complex = "".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output_path,
    ]
    return cmd


def generate_video(job):
    """Run FFmpeg to produce the final video. Returns output filename."""
    clips = job["clips"]
    font_size = int(job.get("font_size", 72))
    text_y = int(job.get("text_y", 80))

    # Validate files and detect audio streams
    clip_audio_flags = []
    for clip in clips:
        uid = clip.get("upload_id", "")
        path = os.path.join(UPLOAD_DIR, uid + ".mp4")
        if not os.path.isfile(path):
            raise ValueError(f"Upload not found: {uid}")
        clip_audio_flags.append(has_audio_stream(path))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"tiktok_{timestamp}.mp4"
    output_path = os.path.join(OUTPUT_DIR, output_filename)

    cmd = build_concat_command(clips, clip_audio_flags, output_path, font_size, text_y)

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Return full stderr so the user can see exactly what went wrong
        raise RuntimeError(result.stderr[-3000:])  # last 3000 chars (most relevant)

    return output_filename


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Unsupported file type: {ext}"}), 400

    upload_id = uuid.uuid4().hex
    save_path = os.path.join(UPLOAD_DIR, upload_id + ".mp4")
    f.save(save_path)

    return jsonify({
        "status": "ok",
        "upload_id": upload_id,
        "original_name": f.filename,
    })


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json()
    if not data or not data.get("clips"):
        return jsonify({"error": "No clips provided"}), 400

    try:
        output_filename = generate_video(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "status": "done",
        "download_url": f"/api/download/{output_filename}",
        "filename": output_filename,
    })


@app.route("/api/download/<filename>")
def download(filename):
    if "/" in filename or "\\" in filename or ".." in filename:
        abort(400)
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=filename)


@app.route("/api/check-ffmpeg")
def check_ffmpeg():
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=5
        )
        ok = result.returncode == 0
        version_line = result.stdout.splitlines()[0] if ok else ""
        return jsonify({"ok": ok, "version": version_line})
    except FileNotFoundError:
        return jsonify({"ok": False, "version": "ffmpeg not found on PATH"})


@app.route("/api/check-font")
def check_font():
    exists = os.path.isfile(FONT_FILE)
    return jsonify({"ok": exists, "path": FONT_FILE})


if __name__ == "__main__":
    print("Starting TikTok Video Maker...")
    print("Open your browser at: http://localhost:5000")
    app.run(debug=False, port=5000)
