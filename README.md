# TikTok Video Maker

A local web app that automatically assembles TikTok-style countdown videos (e.g. "Top 5 Anime Openings"). Upload your clips, set titles and trim points, and get a single vertical MP4 ready to post.

## Features

- Drag-and-drop video uploads
- Per-clip labels, start time, and duration controls
- Reorder clips with up/down buttons
- Auto-scales any video to 9:16 (1080×1920) — works with landscape or portrait source clips
- Bold title text overlay at the top of each clip
- Handles clips with no audio track automatically

## Requirements

- **Python 3.10+** — [python.org/downloads](https://www.python.org/downloads/)
- **FFmpeg** — [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) (download `ffmpeg-release-essentials.zip`, extract, add `bin\` to your system PATH)
- **Roboto Bold font** — [fonts.google.com/specimen/Roboto](https://fonts.google.com/specimen/Roboto) — download, extract, place `Roboto-Bold.ttf` in the `fonts/` folder

## Setup & Run

**Windows — double-click `start.bat`**

It will create a virtual environment, install dependencies, and open the app in your browser automatically.

Or manually:

```bat
pip install -r requirements.txt
python app.py
```

Then open [http://localhost:5000](http://localhost:5000).

## Usage

1. Drop your video clips onto the page
2. Edit each clip's label (e.g. `#5 - Attack on Titan OP1`)
3. Set start time and duration to pick the exact segment
4. Use ▲ ▼ to reorder clips
5. Click **Generate Video**
6. Download your finished MP4
