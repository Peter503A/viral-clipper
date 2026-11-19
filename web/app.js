"use strict";

const $ = (id) => document.getElementById(id);

// --- Live layout preview ----------------------------------------------------
const camH = $("cam-h");
const camBand = $("cam-band");
const subtitleDemo = document.querySelector(".subtitle-demo");

function syncPreview() {
  const pct = Number(camH.value);
  $("cam-h-val").textContent = pct;
  camBand.style.height = pct + "%";
  subtitleDemo.style.top = `calc(${pct}% - 14px)`;
}
camH.addEventListener("input", syncPreview);
syncPreview();

// --- Helpers ----------------------------------------------------------------
const frac = (id) => Math.max(0, Math.min(1, Number($(id).value) / 100));

function buildPayload() {
  return {
    url: $("url").value.trim(),
    upload_id: clipUploadId,
    num_clips: Number($("num").value),
    min_seconds: Number($("min").value),
    max_seconds: Number($("max").value),
    cam_height_fraction: Number(camH.value) / 100,
    cam_region: { x: frac("cam-x"), y: frac("cam-y"), w: frac("cam-w"), h: frac("cam-h2") },
    game_region: { x: frac("game-x"), y: frac("game-y"), w: frac("game-w"), h: frac("game-h") },
    subtitles: $("subs").checked,
    subtitle_style: currentStyle,
    trim_silence: $("trim").checked,
    hook: $("hook").checked,
    hook_text: $("hook-text").value.trim(),
    color_correction: $("color").checked,
  };
}

// --- Clip-mode recipe controls ---------------------------------------------
let clipUploadId = "";
let currentStyle = "karaoke";

// Subtitle style picker
document.querySelectorAll(".style-opt").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".style-opt").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentStyle = btn.dataset.style;
  });
});

// Hook text row visibility
$("hook").addEventListener("change", () => {
  $("hook-text-row").style.display = $("hook").checked ? "block" : "none";
});

// Upload a source file for clipping
$("clip-file").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  const nameEl = $("clip-file-name");
  nameEl.textContent = "Uploading…";
  try {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      nameEl.textContent = "";
      alert(err.detail || "Upload failed.");
      return;
    }
    const data = await res.json();
    clipUploadId = data.upload_id;
    nameEl.textContent = "✓ " + (data.name || "uploaded");
    $("url").value = ""; // uploaded file takes priority
  } catch (e) {
    nameEl.textContent = "";
    alert("Upload failed.");
  }
});

// Clearing the upload if the user types a URL again
$("url").addEventListener("input", () => {
  if ($("url").value.trim()) {
    clipUploadId = "";
    $("clip-file-name").textContent = "";
  }
});

const STATE_TITLES = {
  queued: "Queued…",
  downloading: "Downloading video…",
  analyzing: "Finding viral moments…",
  transcribing: "Generating subtitles…",
  rendering: "Rendering clips…",
  done: "Done!",
  error: "Something went wrong",
};

function showError(msg) {
  const card = $("progress-card");
  card.classList.remove("hidden");
  $("status-title").textContent = "Something went wrong";
  let box = card.querySelector(".error-box");
  if (!box) {
    box = document.createElement("div");
    box.className = "error-box";
    card.appendChild(box);
  }
  box.textContent = msg;
}

// --- Job lifecycle ----------------------------------------------------------
let pollTimer = null;

async function startJob() {
  const payload = buildPayload();
  if (!payload.url && !payload.upload_id) {
    alert("Paste a video URL or upload a file first.");
    return;
  }

  $("start").disabled = true;
  $("results-card").classList.add("hidden");
  $("clips").innerHTML = "";
  const existingErr = document.querySelector(".error-box");
  if (existingErr) existingErr.remove();

  $("progress-card").classList.remove("hidden");
  $("status-title").textContent = "Queued…";
  $("bar-fill").style.width = "0%";
  $("status-msg").textContent = "";

  let job;
  try {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    job = await res.json();
  } catch (e) {
    showError(e.message);
    $("start").disabled = false;
    return;
  }

  pollTimer = setInterval(() => pollJob(job.id), 1200);
  pollJob(job.id);
}

async function pollJob(id) {
  let job;
  try {
    const res = await fetch(`/api/jobs/${id}`);
    if (!res.ok) throw new Error(`Status failed (${res.status})`);
    job = await res.json();
  } catch (e) {
    return; // transient; keep polling
  }

  $("status-title").textContent = STATE_TITLES[job.state] || job.state;
  $("bar-fill").style.width = Math.round((job.progress || 0) * 100) + "%";
  $("status-msg").textContent = job.message || "";

  if (job.state === "error") {
    clearInterval(pollTimer);
    showError(job.error || "Unknown error.");
    $("start").disabled = false;
    return;
  }

  if (job.state === "done") {
    clearInterval(pollTimer);
    renderClips(id, job.clips);
    $("start").disabled = false;
  }
}

function renderClips(jobId, clips) {
  $("results-card").classList.remove("hidden");
  $("clip-count").textContent = `(${clips.length})`;
  const container = $("clips");
  container.innerHTML = "";

  clips.forEach((c) => {
    const url = `/api/clips/${jobId}/${encodeURIComponent(c.filename)}`;
    const card = document.createElement("div");
    card.className = "clip";
    card.innerHTML = `
      <video src="${url}" controls preload="metadata"></video>
      <div class="meta">
        <h3>${c.title}</h3>
        <p>${c.duration}s · source ${c.start}s–${c.end}s · score ${c.score}</p>
      </div>
      <a class="dl" href="${url}" download="${c.filename}">⬇ Download</a>
    `;
    container.appendChild(card);
  });
}

$("start").addEventListener("click", startJob);

// ===========================================================================
// Mode switching
// ===========================================================================
const modeButtons = document.querySelectorAll(".mode-btn");
const panels = document.querySelectorAll(".mode-panel");

function setMode(mode) {
  modeButtons.forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  panels.forEach((p) => p.classList.toggle("hidden", p.dataset.mode !== mode));
  // Hide stale progress/results when switching modes.
  $("progress-card").classList.add("hidden");
  $("results-card").classList.add("hidden");
  if (mode === "commentary") loadLibrary();
}
modeButtons.forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

// ===========================================================================
// Commentary: media library
// ===========================================================================
const subPos = $("sub-pos");
subPos.addEventListener("input", () => ($("sub-pos-val").textContent = subPos.value));

async function loadLibrary() {
  let items = [];
  try {
    const res = await fetch("/api/library");
    items = await res.json();
  } catch (e) {
    return;
  }
  const grid = $("library");
  const select = $("bg-select");

  // Rebuild the dropdown (keep the random option).
  select.innerHTML = '<option value="">🎲 Random from library</option>';
  items.forEach((it) => {
    const opt = document.createElement("option");
    opt.value = it.id;
    opt.textContent = it.name;
    select.appendChild(opt);
  });

  if (items.length === 0) {
    grid.innerHTML = '<p class="lib-empty">No gameplay videos yet. Add one above.</p>';
    return;
  }
  grid.innerHTML = "";
  items.forEach((it) => {
    const card = document.createElement("div");
    card.className = "lib-item";
    const dur = it.duration ? `${Math.round(it.duration)}s · ` : "";
    card.innerHTML = `
      <button class="lib-del" title="Remove" data-id="${it.id}">✕</button>
      <video src="/api/library/${it.id}/video" muted preload="metadata"></video>
      <div class="lib-name" title="${it.name}">${it.name}</div>
      <div class="lib-meta">${dur}${it.width}×${it.height}</div>
    `;
    grid.appendChild(card);
  });

  grid.querySelectorAll(".lib-del").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Remove this gameplay video?")) return;
      await fetch(`/api/library/${btn.dataset.id}`, { method: "DELETE" });
      loadLibrary();
    });
  });
}

async function handleUpload(ev) {
  const input = ev.target;
  const file = input.files[0];
  if (!file) return;
  const label = input.closest(".upload-btn");
  const text = label.childNodes[0];
  const original = text.textContent;
  text.textContent = "Uploading… ";
  try {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/library", { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || "Upload failed.");
    }
  } finally {
    text.textContent = original;
    input.value = "";
    loadLibrary();
  }
}
$("lib-file").addEventListener("change", handleUpload);

// ===========================================================================
// Commentary: start job
// ===========================================================================
async function startCommentary() {
  const script = $("script").value.trim();
  if (!script) {
    alert("Please enter a script first.");
    return;
  }
  const payload = {
    script,
    background_id: $("bg-select").value,
    voice: $("voice").value.trim(),
    subtitles: $("c-subs").checked,
    subtitle_position: Number(subPos.value) / 100,
  };

  $("start-commentary").disabled = true;
  $("results-card").classList.add("hidden");
  $("clips").innerHTML = "";
  const existingErr = document.querySelector(".error-box");
  if (existingErr) existingErr.remove();

  $("progress-card").classList.remove("hidden");
  $("status-title").textContent = "Queued…";
  $("bar-fill").style.width = "0%";
  $("status-msg").textContent = "";

  let job;
  try {
    const res = await fetch("/api/commentary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    job = await res.json();
  } catch (e) {
    showError(e.message);
    $("start-commentary").disabled = false;
    return;
  }

  pollTimer = setInterval(() => pollCommentary(job.id), 1200);
  pollCommentary(job.id);
}

async function pollCommentary(id) {
  let job;
  try {
    const res = await fetch(`/api/jobs/${id}`);
    job = await res.json();
  } catch (e) {
    return;
  }
  $("status-title").textContent = STATE_TITLES[job.state] || job.state;
  $("bar-fill").style.width = Math.round((job.progress || 0) * 100) + "%";
  $("status-msg").textContent = job.message || "";

  if (job.state === "error") {
    clearInterval(pollTimer);
    showError(job.error || "Unknown error.");
    $("start-commentary").disabled = false;
  } else if (job.state === "done") {
    clearInterval(pollTimer);
    renderClips(id, job.clips);
    $("start-commentary").disabled = false;
  }
}

$("start-commentary").addEventListener("click", startCommentary);

// Add commentary states to the title map.
STATE_TITLES.synthesizing = "Generating AI voiceover…";
