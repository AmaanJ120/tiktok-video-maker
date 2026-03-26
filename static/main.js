// State: array of { upload_id, original_name, label, start, duration }
const clips = [];

// ── Startup checks ────────────────────────────────────────────────────────

window.addEventListener("DOMContentLoaded", async () => {
  await checkEnvironment();
});

async function checkEnvironment() {
  const bar = document.getElementById("status-bar");
  const issues = [];

  try {
    const ffRes = await fetch("/api/check-ffmpeg");
    const ff = await ffRes.json();
    if (!ff.ok) issues.push("FFmpeg not found — make sure ffmpeg is on your PATH.");
  } catch (_) {
    issues.push("Could not reach server (is app.py running?).");
  }

  try {
    const fontRes = await fetch("/api/check-font");
    const font = await fontRes.json();
    if (!font.ok) {
      issues.push("Font file missing — download Roboto-Bold.ttf and put it in the fonts/ folder.");
    }
  } catch (_) {}

  bar.classList.remove("hidden");
  if (issues.length === 0) {
    bar.textContent = "Ready. FFmpeg and font detected.";
  } else {
    bar.classList.add("error");
    bar.innerHTML = "<strong>Setup issue:</strong> " + issues.join(" | ");
  }
}

// ── Drop / File input ─────────────────────────────────────────────────────

function handleDrop(event) {
  event.preventDefault();
  document.getElementById("drop-zone").classList.remove("drag-over");
  const files = Array.from(event.dataTransfer.files).filter(isVideo);
  files.forEach(uploadFile);
}

function handleFileInput(fileList) {
  Array.from(fileList).filter(isVideo).forEach(uploadFile);
}

function isVideo(file) {
  return /\.(mp4|mov|webm|mkv|avi)$/i.test(file.name);
}

// ── Upload ────────────────────────────────────────────────────────────────

async function uploadFile(file) {
  // Create a placeholder clip entry immediately so the UI feels instant
  const tempId = "pending_" + Math.random().toString(36).slice(2);
  const clip = {
    upload_id: null,
    _temp_id: tempId,
    original_name: file.name,
    label: guessLabel(clips.length + 1, file.name),
    start: 0,
    duration: 15,
    uploading: true,
  };
  clips.push(clip);
  renderClips();

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/upload", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Upload failed");

    clip.upload_id = data.upload_id;
    clip.uploading = false;
    renderClips();
    showGenerateSection();
  } catch (err) {
    clips.splice(clips.indexOf(clip), 1);
    renderClips();
    alert("Upload failed: " + err.message);
  }
}

function guessLabel(position, filename) {
  // Strip extension and common suffixes, prepend ranking
  const base = filename.replace(/\.[^.]+$/, "").replace(/[_-]/g, " ");
  return `#${position} - ${base}`;
}

// ── Render clip list ──────────────────────────────────────────────────────

function renderClips() {
  const list = document.getElementById("clip-list");
  list.innerHTML = "";

  clips.forEach((clip, i) => {
    const card = document.createElement("div");
    card.className = "clip-card" + (clip.uploading ? " uploading" : "");
    card.dataset.index = i;

    const badge = clip.uploading
      ? `<span class="upload-badge">Uploading...</span>`
      : `<span class="upload-badge done">Ready</span>`;

    card.innerHTML = `
      <div class="clip-header">
        <span class="clip-num">#${i + 1}</span>
        <input
          type="text"
          value="${escapeHtml(clip.label)}"
          placeholder="Label (e.g. #5 - Attack on Titan OP1)"
          oninput="updateClip(${i}, 'label', this.value)"
        />
        ${badge}
        <div class="clip-controls">
          <button onclick="moveClip(${i}, -1)" title="Move up" ${i === 0 ? "disabled" : ""}>▲</button>
          <button onclick="moveClip(${i}, 1)" title="Move down" ${i === clips.length - 1 ? "disabled" : ""}>▼</button>
          <button class="btn-remove" onclick="removeClip(${i})">✕</button>
        </div>
      </div>
      <div class="clip-timing">
        <label>
          Start (sec)
          <input type="number" value="${clip.start}" min="0" step="0.5"
            oninput="updateClip(${i}, 'start', parseFloat(this.value) || 0)" />
        </label>
        <label>
          Duration (sec)
          <input type="number" value="${clip.duration}" min="1" max="300" step="0.5"
            oninput="updateClip(${i}, 'duration', parseFloat(this.value) || 15)" />
        </label>
      </div>
      <div class="clip-filename">${escapeHtml(clip.original_name)}</div>
    `;

    list.appendChild(card);
  });

  // Show/hide clips section
  const clipsSection = document.getElementById("clips-section");
  clipsSection.style.display = clips.length > 0 ? "block" : "none";
}

function updateClip(index, field, value) {
  if (clips[index]) clips[index][field] = value;
}

function moveClip(index, direction) {
  const newIndex = index + direction;
  if (newIndex < 0 || newIndex >= clips.length) return;
  [clips[index], clips[newIndex]] = [clips[newIndex], clips[index]];
  // Re-number labels only if they still match the auto-format
  clips.forEach((c, i) => {
    c.label = c.label.replace(/^#\d+/, `#${i + 1}`);
  });
  renderClips();
}

function removeClip(index) {
  clips.splice(index, 1);
  // Re-number labels
  clips.forEach((c, i) => {
    c.label = c.label.replace(/^#\d+/, `#${i + 1}`);
  });
  renderClips();
  if (clips.length === 0) {
    document.getElementById("generate-section").style.display = "none";
  }
}

function showGenerateSection() {
  document.getElementById("generate-section").style.display = "block";
}

// ── Generate ──────────────────────────────────────────────────────────────

async function submitJob() {
  const readyClips = clips.filter(c => !c.uploading && c.upload_id);
  if (readyClips.length === 0) {
    alert("No clips ready yet. Wait for uploads to finish.");
    return;
  }

  const btn = document.getElementById("generate-btn");
  btn.disabled = true;

  document.getElementById("progress-area").classList.remove("hidden");
  document.getElementById("download-area").classList.add("hidden");
  document.getElementById("progress-text").textContent =
    `Processing ${readyClips.length} clip(s)... this may take a minute.`;

  const payload = {
    clips: readyClips.map(c => ({
      upload_id: c.upload_id,
      label: c.label,
      start: c.start,
      duration: c.duration,
    })),
    list_title: document.getElementById("list-title").value.trim() || "TOP 5",
  };

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    document.getElementById("progress-area").classList.add("hidden");

    if (!res.ok || data.error) {
      document.getElementById("error-area").classList.remove("hidden");
      document.getElementById("error-text").textContent = data.error || "Unknown error";
      return;
    }

    document.getElementById("error-area").classList.add("hidden");
    const dl = document.getElementById("download-area");
    dl.classList.remove("hidden");
    const link = document.getElementById("download-link");
    link.href = data.download_url;
    link.download = data.filename;
    link.textContent = `Download ${data.filename}`;

  } catch (err) {
    document.getElementById("progress-area").classList.add("hidden");
    document.getElementById("error-area").classList.remove("hidden");
    document.getElementById("error-text").textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
