# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bat
# Windows — installs deps and opens browser automatically
start.bat

# Or manually
venv\Scripts\activate
pip install -r requirements.txt
python app.py
# → http://localhost:5000
```

There are no tests and no linter configured.

## Architecture

All logic lives in a single Flask app (`app.py`). The browser (`static/main.js`) uploads clips one at a time to `/api/upload`, then POSTs a job to `/api/generate` which runs FFmpeg synchronously (blocking the request) and returns a download URL.

### Video pipeline (`app.py`)

`generate_video` → `build_concat_command` → `build_clip_filter` (called once per clip) → single `subprocess.run(ffmpeg ...)`.

Each clip produces one `filter_complex` segment built by `build_clip_filter`. The segment order is:

1. `split=2` — duplicate the input stream (required; FFmpeg forbids using the same input twice without split)
2. `[iv_bg]` branch → scale-to-fill + `boxblur` → `[bg]`
3. `[iv_fg]` branch → scale-to-fit + `pad` with black bars → `[fg]`
4. `overlay` fg on bg → `[base]`
5. `drawbox` (separator line) + `drawtext` chain (title header + rank list) → `[v]`
6. Audio: `atrim`/`asetpts`/`aformat` if audio stream exists, else `aevalsrc=0` for silence

All per-clip `[v][a]` streams are joined with `concat=n=N:v=1:a=1`. The concat filter requires **interleaved** input order: `[v0][a0][v1][a1]…` — not all-video then all-audio.

### Layout constants (top of `app.py`)

All pixel positions are hardcoded as module-level constants for 1080×1920:

| Constant | Value | Purpose |
|---|---|---|
| `RANK_AREA_TOP/BOTTOM` | 250 / 800 | Y range for the rank list |
| `VIDEO_W/H/X/Y` | 1080 / 608 / 0 / 850 | Full-width 16:9 video box |
| `RANK_NUM_X` | 50 | X of rank numbers |
| `RANK_TITLE_X` | 155 | X of clip title text |

### FFmpeg gotchas on Windows

- **Font path**: `get_ffmpeg_font_path()` converts `C:\path` → `C\:/path` (colon must be escaped inside `filter_complex` strings)
- **drawtext escaping**: `sanitize_for_drawtext()` must escape `\`, `'`, `:`, `%` — in that order
- **Font file**: `FONT_FILE` points to `fonts/Roboto-Bold.ttf` (one level up from `fonts/Roboto/static/`). Pillow and FFmpeg both read from this same path.

### Multi-colour title (`*word*` = red)

`parse_title_template` splits on `*...*` regex. `build_title_drawtext` measures each segment's pixel width via `PIL.ImageFont.getlength` (falls back to `len × 0.56 × fontsize` if Pillow is unavailable), then places segments left-to-right starting from a centred offset.

### Progressive rank reveal

`build_clip_filter` receives the full `all_clips` list. For clip at index `i`: rows `< i` are revealed (grey), row `== i` is active (white), rows `> i` are hidden (very dark). This creates the "titles appear as each clip plays" effect.

### Frontend state

`clips[]` array in `main.js` is the single source of truth. Each entry holds `upload_id` (set after the POST to `/api/upload` completes), `label`, `start`, `duration`. The UI is rebuilt by `renderClips()` on every mutation (add, remove, reorder).
