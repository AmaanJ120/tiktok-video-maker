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

# ── Layout constants (1080x1920 canvas) ───────────────────────────────────────
CANVAS_W = 1080
CANVAS_H = 1920

# Rank list sits in the upper portion
RANK_AREA_TOP    = 250   # y where the rank list starts
RANK_AREA_BOTTOM = 800   # y where the rank list ends

# Video box: full width, placed just below the rank list
VIDEO_W = 1080
VIDEO_H = 608            # 16:9  (1080 × 9/16 = 607.5 → 608)
VIDEO_X = 0
VIDEO_Y = RANK_AREA_BOTTOM + 50       # = 850

RANK_NUM_X   = 50    # x position of the rank number glyph
RANK_TITLE_X = 155   # x position of the title text next to the number


def get_ffmpeg_font_path():
    """Font path in FFmpeg drawtext-safe format for Windows."""
    abs_path = os.path.abspath(FONT_FILE)
    forward  = abs_path.replace("\\", "/")
    return forward.replace(":/", "\\:/", 1)   # C:/ → C\:/


def sanitize_for_drawtext(text):
    """Escape characters that break FFmpeg drawtext."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'",  "\u2019")   # curly apostrophe (safe in drawtext)
    text = text.replace(":",  "\\:")
    text = text.replace("%",  "\\%")
    return text


def parse_title_template(template):
    """
    Parse a title template where *word* marks red text.
    e.g. "TOP *5* ANIME OPENINGS" → [("TOP ", "white"), ("5", "red"), (" ANIME OPENINGS", "white")]
    """
    import re
    parts = []
    for idx, segment in enumerate(re.split(r'\*([^*]+)\*', template)):
        if segment:
            parts.append((segment, "red" if idx % 2 == 1 else "white"))
    return parts


def measure_text_width(text, fontsize):
    """Return the exact advance width (px) of text using the actual font file."""
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(os.path.abspath(FONT_FILE), fontsize)
        # getlength returns the advance width — correct for sequential placement
        return font.getlength(text)
    except Exception:
        # Fallback if Pillow is unavailable
        return len(text) * fontsize * 0.56


def build_title_drawtext(parts, font_path, fontsize, y):
    """
    Build drawtext filter strings for a multi-colour title line.
    Segments are placed side-by-side using exact font metrics, then centred.
    """
    total_w = sum(measure_text_width(text, fontsize) for text, _ in parts)
    x = (CANVAS_W - total_w) / 2

    filters = []
    for text, color in parts:
        safe = sanitize_for_drawtext(text)
        filters.append(
            f"drawtext=fontfile='{font_path}':"
            f"text='{safe}':"
            f"fontsize={fontsize}:"
            f"fontcolor={color}:"
            f"borderw=3:bordercolor=black@0.9:"
            f"x={int(x)}:y={y}:"
            f"shadowx=2:shadowy=2:shadowcolor=black@0.8"
        )
        x += measure_text_width(text, fontsize)
    return filters


def has_audio_stream(file_path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type",
         "-of", "default=noprint_wrappers=1:nokey=1", file_path],
        capture_output=True, text=True,
    )
    return result.stdout.strip() == "audio"


def build_clip_filter(clip_index, all_clips, has_audio, font_path, list_title):
    """
    Build the filter_complex segment for clip at clip_index.

    Visual layout (1080 × 1920):
      ┌──────────────────────────┐  y=0
      │   LIST TITLE (header)   │  y=80
      │                          │
      │  [N]  title revealed     │  y=250..800  rank list
      │  [N-1]                   │    (progressive reveal as clips play)
      │  ...                     │
      │  [1]                     │
      │                          │
      │  ┌──────────────────┐    │  y=850  video box (1000×562, 16:9)
      │  │   VIDEO CLIP     │    │
      │  └──────────────────┘    │  y=1412
      │   blurred bg below       │
      └──────────────────────────┘  y=1920
    """
    clip  = all_clips[clip_index]
    i     = clip_index
    N     = len(all_clips)

    start    = float(clip.get("start",    0))
    duration = float(clip.get("duration", 15))

    rank_area_h = RANK_AREA_BOTTOM - RANK_AREA_TOP   # 550
    entry_h     = rank_area_h / N                     # height per rank row

    # ── 1. Split input so we can use it for both bg and fg ────────────────
    # FFmpeg does not allow referencing the same input stream twice without split
    split = f"[{i}:v]split=2[{i}v_bg][{i}v_fg];"

    # ── 2. Background: fill canvas, heavy blur, darken ────────────────────
    bg = (
        f"[{i}v_bg]trim=start={start}:duration={duration},"
        f"setpts=PTS-STARTPTS,"
        f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
        f"crop={CANVAS_W}:{CANVAS_H},"
        f"boxblur=30:5"
        f"[bg{i}];"
    )

    # ── 3. Foreground: fit inside video box, black letterbox bars ─────────
    fg = (
        f"[{i}v_fg]trim=start={start}:duration={duration},"
        f"setpts=PTS-STARTPTS,"
        f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_W}:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2:color=black"
        f"[fg{i}];"
    )

    # ── 3. Composite: overlay fg on blurred bg ────────────────────────────
    overlay = (
        f"[bg{i}][fg{i}]overlay=x={VIDEO_X}:y={VIDEO_Y}[base{i}];"
    )

    # ── 4. Graphics / text chain ──────────────────────────────────────────
    parts = []

    # Thin separator line between rank list and video
    parts.append(
        f"drawbox=x=0:y={VIDEO_Y - 2}:w={CANVAS_W}:h=2:"
        f"color=white@0.25:t=fill"
    )

    # List title header — supports *word* syntax for red segments
    title_segments = parse_title_template(list_title)
    parts.extend(build_title_drawtext(title_segments, font_path, 64, 90))

    # Rank list  (row 0 = rank N = first to play, row N-1 = rank 1 = last to play)
    for row in range(N):
        row_rank    = N - row
        center_y    = RANK_AREA_TOP + row * entry_h + entry_h / 2
        row_clip    = all_clips[row]
        row_label   = sanitize_for_drawtext(row_clip.get("label", ""))

        is_active   = (row == i)
        is_revealed = (row < i)    # already played

        if is_active:
            num_sz, num_col  = 76, "white"
            ttl_sz, ttl_col  = 50, "white"
            show_title       = True
        elif is_revealed:
            num_sz, num_col  = 60, "0xcccccc"
            ttl_sz, ttl_col  = 44, "0xcccccc"
            show_title       = True
        else:
            # Future rank: dim, no title
            num_sz, num_col  = 60, "0x3a3a3a"
            show_title       = False

        num_y = int(center_y - num_sz / 2)
        parts.append(
            f"drawtext=fontfile='{font_path}':"
            f"text='{row_rank}':"
            f"fontsize={num_sz}:"
            f"fontcolor={num_col}:"
            f"borderw=2:bordercolor=black@0.8:"
            f"x={RANK_NUM_X}:y={num_y}"
        )

        if show_title:
            ttl_y = int(center_y - ttl_sz / 2)
            parts.append(
                f"drawtext=fontfile='{font_path}':"
                f"text='{row_label}':"
                f"fontsize={ttl_sz}:"
                f"fontcolor={ttl_col}:"
                f"borderw=2:bordercolor=black@0.8:"
                f"x={RANK_TITLE_X}:y={ttl_y}:"
                f"fix_bounds=1"
            )

    text_chain  = ",".join(parts)
    text_filter = f"[base{i}]{text_chain}[v{i}];"

    # ── 5. Audio ──────────────────────────────────────────────────────────
    if has_audio:
        audio = (
            f"[{i}:a]atrim=start={start}:duration={duration},"
            f"asetpts=PTS-STARTPTS,"
            f"aformat=sample_rates=44100:channel_layouts=stereo[a{i}];"
        )
    else:
        audio = f"aevalsrc=0:c=stereo:r=44100:d={duration}[a{i}];"

    return split + bg + fg + overlay + text_filter + audio


def build_concat_command(clips, clip_audio_flags, output_path, list_title):
    font_path = get_ffmpeg_font_path()
    n = len(clips)

    inputs = []
    for clip in clips:
        inputs += ["-i", os.path.join(UPLOAD_DIR, clip["upload_id"] + ".mp4")]

    filter_parts = []
    for i, (clip, has_audio) in enumerate(zip(clips, clip_audio_flags)):
        filter_parts.append(
            build_clip_filter(i, clips, has_audio, font_path, list_title)
        )

    # concat expects interleaved: [v0][a0][v1][a1]...
    interleaved = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_parts.append(f"{interleaved}concat=n={n}:v=1:a=1[vout][aout]")

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", "".join(filter_parts),
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
    clips      = job["clips"]
    list_title = job.get("list_title", "TOP 5")

    clip_audio_flags = []
    for clip in clips:
        path = os.path.join(UPLOAD_DIR, clip.get("upload_id", "") + ".mp4")
        if not os.path.isfile(path):
            raise ValueError(f"Upload not found: {clip.get('upload_id')}")
        clip_audio_flags.append(has_audio_stream(path))

    timestamp       = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"tiktok_{timestamp}.mp4"
    output_path     = os.path.join(OUTPUT_DIR, output_filename)

    cmd    = build_concat_command(clips, clip_audio_flags, output_path, list_title)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(result.stderr[-3000:])

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
    f.save(os.path.join(UPLOAD_DIR, upload_id + ".mp4"))
    return jsonify({"status": "ok", "upload_id": upload_id, "original_name": f.filename})


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
        result = subprocess.run(["ffmpeg", "-version"],
                                capture_output=True, text=True, timeout=5)
        ok = result.returncode == 0
        return jsonify({"ok": ok, "version": result.stdout.splitlines()[0] if ok else ""})
    except FileNotFoundError:
        return jsonify({"ok": False, "version": "ffmpeg not found on PATH"})


@app.route("/api/check-font")
def check_font():
    return jsonify({"ok": os.path.isfile(FONT_FILE), "path": FONT_FILE})


if __name__ == "__main__":
    print("Starting TikTok Video Maker...")
    print("Open your browser at: http://localhost:5000")
    app.run(debug=False, port=5000)
