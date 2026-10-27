// ===========================================================================
// app.js — dashboard SPA logic. Talks to the Flask JSON API in app.py.
// ===========================================================================

const STATUS_COLORS = {
  SAFE: "#22C55E",
  WARNING: "#FACC15",
  HIGH: "#FB923C",
  CRITICAL: "#EF4444",
};

let currentJobId = null;
let pollTimer = null;
let charts = {};

// ---------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------
function goToPage(pageId) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-item[data-page]").forEach(n => n.classList.remove("active"));
  const page = document.getElementById("page-" + pageId);
  if (page) page.classList.add("active");
  document.querySelectorAll(`.nav-item[data-page="${pageId}"]`).forEach(n => n.classList.add("active"));

  const titles = {
    dashboard: "Dashboard", upload: "Upload Video", analysis: "Analysis",
    reports: "Reports", history: "History", settings: "Settings",
  };
  document.getElementById("pageTitle").textContent = titles[pageId] || "Dashboard";

  if (pageId === "dashboard") loadDashboardSummary();
  if (pageId === "history") loadHistory();
  if (pageId === "reports") loadReportVideoOptions();

  closeUserDropdown();
  closeNotifPanel();
}

document.querySelectorAll(".nav-item[data-page]").forEach(el => {
  el.addEventListener("click", e => {
    e.preventDefault();
    goToPage(el.dataset.page);
  });
});
document.querySelectorAll("[data-nav]").forEach(el => {
  el.addEventListener("click", () => goToPage(el.dataset.nav));
});

// sidebar collapse
document.getElementById("sidebarToggle").addEventListener("click", () => {
  document.getElementById("appShell").classList.toggle("collapsed");
});

// user dropdown
const userChip = document.getElementById("userChip");
const userDropdown = document.getElementById("userDropdown");
userChip.addEventListener("click", e => {
  e.stopPropagation();
  userDropdown.hidden = !userDropdown.hidden;
});
function closeUserDropdown() { userDropdown.hidden = true; }
document.addEventListener("click", closeUserDropdown);

// notifications
const notifBtn = document.getElementById("notifBtn");
const notifPanel = document.getElementById("notifPanel");
notifBtn.addEventListener("click", e => {
  e.stopPropagation();
  notifPanel.hidden = !notifPanel.hidden;
});
function closeNotifPanel() { notifPanel.hidden = true; }
document.addEventListener("click", closeNotifPanel);

async function refreshNotifications() {
  try {
    const res = await fetch("/api/history");
    const rows = await res.json();
    const alertRows = rows.filter(r => r.total_alerts > 0).slice(0, 6);
    const list = document.getElementById("notifList");
    if (!alertRows.length) {
      list.innerHTML = '<div class="empty-hint">No alerts yet.</div>';
      document.getElementById("notifDot").hidden = true;
      return;
    }
    document.getElementById("notifDot").hidden = false;
    list.innerHTML = alertRows.map(r => `
      <div class="notif-row">
        <b>${escapeHtml(r.original_filename)}</b>
        ${r.total_alerts} overcrowding event(s) · peak ${r.max_count} people
      </div>`).join("");
  } catch (e) { /* non-fatal */ }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString();
}
function fmtDuration(sec) {
  sec = Math.round(sec || 0);
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${m}m ${s}s`;
}

// ---------------------------------------------------------------------
// Dashboard page
// ---------------------------------------------------------------------
async function loadDashboardSummary() {
  try {
    updateDashboardQrWidget();
    const res = await fetch("/api/dashboard_summary");
    const data = await res.json();
    document.getElementById("mVideos").textContent = data.videos_analyzed;
    document.getElementById("mMaxCrowd").textContent = data.max_crowd;
    document.getElementById("mAvgCrowd").textContent = data.avg_crowd;
    document.getElementById("mAlerts").textContent = data.total_alerts;

    const list = document.getElementById("dashRecentList");
    if (!data.recent.length) {
      list.innerHTML = '<div class="empty-hint">No videos analyzed yet — upload one to get started.</div>';
    } else {
      list.innerHTML = data.recent.map(r => `
        <div class="recent-row">
          <div>
            <div class="rname">${escapeHtml(r.original_filename)}</div>
            <div class="rmeta">${fmtDate(r.processed_at)}</div>
          </div>
          <span class="badge badge-${r.overall_risk}">${r.overall_risk}</span>
        </div>`).join("");
    }
  } catch (e) { console.error(e); }
}

// ---------------------------------------------------------------------
// Area Configuration & Upload page
// ---------------------------------------------------------------------
let calculatedThreshold = 0;

const calcThresholdSpan = document.getElementById("calcThreshold");
const dropzone = document.getElementById("dropzone");

dropzone.classList.remove('disabled');
const fileInput = document.getElementById("fileInput");
const browseBtn = document.getElementById("browseBtn");
let selectedFile = null;

browseBtn.addEventListener("click", () => {
  if (dropzone.classList.contains('disabled')) return;
  fileInput.click();
});
dropzone.addEventListener("click", () => {
  if (dropzone.classList.contains('disabled')) return;
  fileInput.click();
});
["dragenter", "dragover"].forEach(evt =>
  dropzone.addEventListener(evt, e => { 
    e.preventDefault(); 
    if (!dropzone.classList.contains('disabled')) dropzone.classList.add("dragover"); 
  }));
["dragleave", "drop"].forEach(evt =>
  dropzone.addEventListener(evt, e => { 
    e.preventDefault(); 
    dropzone.classList.remove("dragover"); 
  }));
dropzone.addEventListener("drop", e => {
  if (dropzone.classList.contains('disabled')) return;
  const file = e.dataTransfer.files[0];
  if (file) handleFileSelected(file);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) handleFileSelected(fileInput.files[0]);
});

function handleFileSelected(file) {
  const allowed = ["mp4", "avi", "mov", "mkv"];
  const ext = file.name.split(".").pop().toLowerCase();
  if (!allowed.includes(ext)) {
    alert("Unsupported format. Please use MP4, AVI, MOV, or MKV.");
    return;
  }
  selectedFile = file;
  document.getElementById("fileName").textContent = file.name;
  document.getElementById("fileMeta").textContent =
    `${(file.size / (1024 * 1024)).toFixed(1)} MB`;
  document.getElementById("fileInfoRow").hidden = false;
}

document.getElementById("startUploadBtn").addEventListener("click", () => {
  if (!selectedFile) return;
  uploadVideo(selectedFile);
});

function uploadVideo(file) {
  const form = new FormData();
  form.append("video", file);
  form.append("area", 0);
  form.append("threshold", calculatedThreshold || 20);

  const progressBlock = document.getElementById("uploadProgressBlock");
  const fill = document.getElementById("uploadProgressFill");
  const pct = document.getElementById("uploadPct");
  progressBlock.hidden = false;
  document.getElementById("startUploadBtn").disabled = true;

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload");
  xhr.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    const p = Math.round((e.loaded / e.total) * 100);
    fill.style.width = p + "%";
    pct.textContent = p + "%";
  };
  xhr.onload = () => {
    document.getElementById("startUploadBtn").disabled = false;
    if (xhr.status !== 200) {
      alert("Upload failed: " + xhr.responseText);
      return;
    }
    const data = JSON.parse(xhr.responseText);
    currentJobId = data.job_id;
    document.getElementById("processingCard").hidden = false;
    // Fetch QR code URL and video filename for this job
    fetch(`/api/public_info/${data.job_id}`)
      .then(r => r.json())
      .then(info => {
        const qrImg = document.getElementById('processingQrImg');
        qrImg.src = info.qr_code_url;
        document.getElementById('processingQrBox').hidden = false;
        if (info.video_filename) {
          const fnElem = document.getElementById('processingVideoFilename');
          if (fnElem) fnElem.textContent = `Video: ${info.video_filename}`;
        }
      })
      .catch(e => console.error('Failed to load QR info', e));
    pollJobStatus(data.job_id);
  };
  xhr.onerror = () => alert("Upload failed — please try again.");
  xhr.send(form);
}

function pollJobStatus(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/status/${jobId}`);
      if (!res.ok) return;
      const s = await res.json();
      updateProcessingUI(s);
      if (s.status === "done") {
        clearInterval(pollTimer);
        await openAnalysis(jobId);
        goToPage("analysis");
      } else if (s.status === "error") {
        clearInterval(pollTimer);
        alert("Processing failed: " + (s.error || "unknown error"));
      }
    } catch (e) { /* keep polling */ }
  }, 1200);
}

function updateProcessingUI(s) {
  const pct = s.progress || 0;

  // Update progress bar
  document.getElementById("procProgressFill").style.width = pct + "%";
  document.getElementById("procProgressPct").textContent = pct + "%";

  // Update stats grid
  document.getElementById("pFrames").textContent = `${s.frames_processed || 0} / ${s.total_frames || 0}`;
  document.getElementById("pCount").textContent = s.current_count || 0;
  document.getElementById("pEta").textContent = s.eta_seconds != null ? `${Math.round(s.eta_seconds)}s` : "—";
  document.getElementById("pStatus").textContent =
    s.status === "processing" ? "Processing" : s.status === "queued" ? "Queued" : s.status;

  // Update live preview image (cache-bust with timestamp)
  if (s.status === "processing" && currentJobId) {
    const previewImg = document.getElementById("livePreviewImg");
    if (previewImg) {
      const newSrc = `/api/preview/${currentJobId}?t=${Date.now()}`;
      // Use a temp image to avoid flickering
      const tmp = new Image();
      tmp.onload = () => { previewImg.src = tmp.src; };
      tmp.src = newSrc;
    }
  }

  // Update status badge
  const statusText = document.getElementById("previewStatusText");
  const badge = document.getElementById("previewBadge");
  if (statusText) {
    statusText.textContent = s.status === "processing" ? "Processing" : s.status === "queued" ? "Queued" : s.status;
  }
}

// ---------------------------------------------------------------------
// Analysis page — dual-video sync, live stats, frame navigation
// ---------------------------------------------------------------------
let frameData = null;   // { fps, total_frames, frames: [ {frame, t, count, status, ...} ] }
let videoFps = 25;
let totalVideoFrames = 0;
let isSyncing = false;  // guard against recursive sync events
let isPlaying = false;
let currentAlarmStatus = "SAFE";
let isAlarmMuted = true;

async function openAnalysis(jobId) {
  try {
    const res = await fetch(`/api/analysis/${jobId}`);
    if (!res.ok) { alert("Could not load analysis."); return; }
    const data = await res.json();

    // fetch per-frame data
    try {
      const fdRes = await fetch(`/api/frame_data/${jobId}`);
      if (fdRes.ok) {
        frameData = await fdRes.json();
        videoFps = frameData.fps || 25;
        totalVideoFrames = frameData.total_frames || 0;
      } else {
        frameData = null;
      }
    } catch (e) { frameData = null; }

    renderAnalysis(data);
  } catch (e) { console.error(e); }
}

// ---------------------------------------------------------------------
// Alarm System (Web Audio API)
// ---------------------------------------------------------------------
const AlarmSystem = (() => {
  let ctx = null;
  let oscillator = null;
  let gainNode = null;
  let currentInterval = null;

  function initCtx() {
    if (!ctx) {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (ctx.state === "suspended") {
      ctx.resume();
    }
  }

  function stopSound() {
    if (currentInterval) {
      clearInterval(currentInterval);
      currentInterval = null;
    }
    if (oscillator) {
      try { oscillator.stop(); } catch(e){}
      oscillator.disconnect();
      oscillator = null;
    }
    if (gainNode) {
      gainNode.disconnect();
      gainNode = null;
    }
  }

  function playTone(freq, type = 'sine', durationMs = null) {
    stopSound();
    initCtx();

    oscillator = ctx.createOscillator();
    gainNode = ctx.createGain();
    
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(freq, ctx.currentTime);
    
    gainNode.gain.setValueAtTime(0, ctx.currentTime);
    gainNode.gain.linearRampToValueAtTime(0.3, ctx.currentTime + 0.05);
    
    oscillator.connect(gainNode);
    gainNode.connect(ctx.destination);
    
    oscillator.start();

    if (durationMs) {
      gainNode.gain.setValueAtTime(0.3, ctx.currentTime + (durationMs / 1000) - 0.05);
      gainNode.gain.linearRampToValueAtTime(0, ctx.currentTime + (durationMs / 1000));
      setTimeout(() => stopSound(), durationMs);
    }
  }

  return {
    play: (status) => {
      stopSound();
      if (isAlarmMuted) return;

      if (status === "WARNING") {
        // Short beep
        playTone(600, 'sine', 300);
      } else if (status === "HIGH") {
        // Repeated warning beeps
        let on = true;
        currentInterval = setInterval(() => {
          if (on) playTone(750, 'square');
          else stopSound();
          on = !on;
        }, 400);
        playTone(750, 'square'); // start immediately
      } else if (status === "CRITICAL") {
        // Continuous emergency siren
        initCtx();
        oscillator = ctx.createOscillator();
        gainNode = ctx.createGain();
        oscillator.type = 'sawtooth';
        gainNode.gain.value = 0.3;
        
        // Modulate frequency to create siren effect
        const modFreq = 2; // 2Hz modulation
        const depth = 300;
        const baseFreq = 700;
        
        let t = 0;
        currentInterval = setInterval(() => {
          if (!oscillator) return;
          const f = baseFreq + Math.sin(t * Math.PI * 2) * depth;
          oscillator.frequency.setTargetAtTime(f, ctx.currentTime, 0.1);
          t += 0.1 * modFreq;
        }, 100);

        oscillator.connect(gainNode);
        gainNode.connect(ctx.destination);
        oscillator.start();
      }
    },
    stop: () => stopSound()
  };
})();

function renderAnalysis(data) {
  currentJobId = data.job_id;
  document.getElementById("analysisEmpty").hidden = true;
  document.getElementById("analysisContent").hidden = false;

  document.getElementById("analysisVideoName").textContent = data.original_filename;
  const badge = document.getElementById("analysisRiskBadge");
  badge.textContent = data.summary.overall_risk;
  badge.className = "risk-badge " + data.summary.overall_risk;

  // set video fps from analysis data
  videoFps = data.video.fps || 25;
  totalVideoFrames = data.video.total_frames || 0;

  // --- setup dual videos ---
  const originalVid = document.getElementById("originalVideo");
  const detectionVid = document.getElementById("analysisVideo");

  // set sources
  detectionVid.src = data.video.processed_url;
  const hasOriginal = !!data.video.uploaded_url;
  if (hasOriginal) {
    originalVid.src = data.video.uploaded_url;
    originalVid.parentElement.style.display = "";
  } else {
    originalVid.src = "";
    originalVid.parentElement.style.display = "none";
  }

  // reset state
  isPlaying = false;
  updatePlayPauseIcon();

  // initialize sync engine once the detection video metadata loads
  // (don't wait for original — it may not exist or may fail)
  const onDetectionReady = () => {
    initSyncEngine(originalVid, detectionVid, hasOriginal);
  };

  detectionVid.addEventListener("loadedmetadata", onDetectionReady, { once: true });
  // fallback if already cached
  if (detectionVid.readyState >= 1) {
    detectionVid.removeEventListener("loadedmetadata", onDetectionReady);
    onDetectionReady();
  }

  // error handling
  detectionVid.onerror = () => {
    console.warn("Detection video failed to load:", detectionVid.error);
  };
  originalVid.onerror = () => {
    console.warn("Original video failed to load:", originalVid.error);
  };

  // summary
  const summary = data.summary, vid = data.video;
  document.getElementById("summaryList").innerHTML = `
    ${summaryRow("Video Name", data.original_filename)}
    ${summaryRow("Duration", fmtDuration(vid.duration_sec))}
    ${summaryRow("Resolution", vid.resolution)}
    ${summaryRow("Total Frames", vid.total_frames)}
    ${summaryRow("FPS", vid.fps)}
    ${summaryRow("Average Crowd", summary.avg_count)}
    ${summaryRow("Maximum Crowd", summary.max_count)}
    ${summaryRow("Peak Crowd Time", fmtDuration(summary.peak_time_sec))}
    ${summaryRow("Total Alerts", summary.total_alerts)}
    ${summaryRow("Overall Risk Level", summary.overall_risk)}
  `;

  renderCharts(data);
  renderTimeline(data.timeseries, data.events, vid.duration_sec);
  renderEventsTable(data.events);
  document.getElementById("heatmapImg").src = data.heatmap_url || "";
  renderKeyframes(data.keyframes);
}

// --- Sync Engine ---
function initSyncEngine(origVid, detVid, hasOriginal) {
  const seekSlider = document.getElementById("seekSlider");
  const currentTimeDisplay = document.getElementById("currentTimeDisplay");
  const durationDisplay = document.getElementById("durationDisplay");
  const playPauseBtn = document.getElementById("playPauseBtn");
  const speedSelect = document.getElementById("playbackSpeed");
  const fullscreenBtn = document.getElementById("fullscreenBtn");

  // set duration display
  const duration = detVid.duration || 0;
  durationDisplay.textContent = fmtTime(duration);
  seekSlider.max = duration || 100;
  seekSlider.value = 0;

  // update frame display
  document.getElementById("frameCurrentDisplay").textContent = `Frame: 0 / ${totalVideoFrames}`;
  document.getElementById("jumpFrameInput").max = totalVideoFrames;

  // remove old listeners by cloning buttons
  const newPlayBtn = playPauseBtn ? playPauseBtn.cloneNode(true) : null;
  if (newPlayBtn) playPauseBtn.parentNode.replaceChild(newPlayBtn, playPauseBtn);

  const newFullBtn = fullscreenBtn ? fullscreenBtn.cloneNode(true) : null;
  if (newFullBtn) fullscreenBtn.parentNode.replaceChild(newFullBtn, fullscreenBtn);

  const alarmToggleBtn = document.getElementById("alarmToggleBtn");
  const newAlarmBtn = alarmToggleBtn ? alarmToggleBtn.cloneNode(true) : null;
  if (newAlarmBtn) alarmToggleBtn.parentNode.replaceChild(newAlarmBtn, alarmToggleBtn);

  // Play/Pause
  if (newPlayBtn) {
    newPlayBtn.addEventListener("click", () => {
      if (isPlaying) {
        if (hasOriginal) origVid.pause();
        detVid.pause();
        isPlaying = false;
        AlarmSystem.stop();
      } else {
        if (hasOriginal) origVid.play().catch(() => {});
        detVid.play().catch(() => {});
        isPlaying = true;
        AlarmSystem.play(currentAlarmStatus);
      }
      updatePlayPauseIcon();
    });
  }

  // Alarm Mute Toggle
  updateAlarmIcon();
  if (newAlarmBtn) {
    newAlarmBtn.addEventListener("click", () => {
      isAlarmMuted = !isAlarmMuted;
      if (isAlarmMuted) {
        AlarmSystem.stop();
      } else if (isPlaying) {
        AlarmSystem.play(currentAlarmStatus);
      }
      updateAlarmIcon();
    });
  }

  // Sync on timeupdate from detection video (primary)
  detVid.ontimeupdate = () => {
    if (isSyncing) return;
    const t = detVid.currentTime;
    currentTimeDisplay.textContent = fmtTime(t);
    seekSlider.value = t;

    // sync original video if drifted more than 0.15s
    if (hasOriginal && Math.abs(origVid.currentTime - t) > 0.15) {
      isSyncing = true;
      origVid.currentTime = t;
      isSyncing = false;
    }

    // update live stats and frame display
    updateLiveStats(t);
    updateFrameDisplay(t);
  };

  // Seek slider
  seekSlider.oninput = () => {
    const t = parseFloat(seekSlider.value);
    isSyncing = true;
    detVid.currentTime = t;
    if (hasOriginal) origVid.currentTime = t;
    isSyncing = false;
    currentTimeDisplay.textContent = fmtTime(t);
    updateLiveStats(t);
    updateFrameDisplay(t);
  };

  // Speed control
  speedSelect.onchange = () => {
    const rate = parseFloat(speedSelect.value);
    detVid.playbackRate = rate;
    if (hasOriginal) origVid.playbackRate = rate;
  };

  // Fullscreen
  newFullBtn.addEventListener("click", () => {
    detVid.requestFullscreen?.();
  });

  // Handle video ending
  detVid.onended = () => {
    isPlaying = false;
    AlarmSystem.stop();
    updatePlayPauseIcon();
  };
  detVid.onpause = () => {
    if (!isSyncing) { 
      if (hasOriginal) origVid.pause(); 
      isPlaying = false; 
      AlarmSystem.stop();
      updatePlayPauseIcon(); 
    }
  };
  detVid.onplay = () => {
    if (!isSyncing) { 
      if (hasOriginal) origVid.play().catch(() => {}); 
      isPlaying = true; 
      AlarmSystem.play(currentAlarmStatus);
      updatePlayPauseIcon(); 
    }
  };

  // --- Frame Navigation ---
  const prevBtn = document.getElementById("prevFrameBtn");
  const nextBtn = document.getElementById("nextFrameBtn");
  const jumpInput = document.getElementById("jumpFrameInput");
  const jumpBtn = document.getElementById("jumpFrameBtn");

  // clone to remove old listeners
  const newPrev = prevBtn.cloneNode(true);
  prevBtn.parentNode.replaceChild(newPrev, prevBtn);
  const newNext = nextBtn.cloneNode(true);
  nextBtn.parentNode.replaceChild(newNext, nextBtn);
  const newJumpBtn = jumpBtn.cloneNode(true);
  jumpBtn.parentNode.replaceChild(newJumpBtn, jumpBtn);

  newPrev.addEventListener("click", () => stepFrame(-1, origVid, detVid, hasOriginal));
  newNext.addEventListener("click", () => stepFrame(1, origVid, detVid, hasOriginal));
  newJumpBtn.addEventListener("click", () => {
    const n = parseInt(jumpInput.value);
    if (!isNaN(n) && n >= 1 && n <= totalVideoFrames) {
      jumpToFrame(n, origVid, detVid, hasOriginal);
    }
  });
  jumpInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") newJumpBtn.click();
  });

  // initialize live stats to frame 0
  updateLiveStats(0);
}

function stepFrame(direction, origVid, detVid, hasOriginal) {
  if (hasOriginal) origVid.pause();
  detVid.pause();
  isPlaying = false;
  AlarmSystem.stop();
  updatePlayPauseIcon();

  const step = 1 / videoFps;
  const newTime = Math.max(0, Math.min(detVid.duration, detVid.currentTime + direction * step));

  isSyncing = true;
  detVid.currentTime = newTime;
  if (hasOriginal) origVid.currentTime = newTime;
  isSyncing = false;

  document.getElementById("seekSlider").value = newTime;
  document.getElementById("currentTimeDisplay").textContent = fmtTime(newTime);
  updateLiveStats(newTime);
  updateFrameDisplay(newTime);
}

function jumpToFrame(frameNum, origVid, detVid, hasOriginal) {
  if (hasOriginal) origVid.pause();
  detVid.pause();
  isPlaying = false;
  AlarmSystem.stop();
  updatePlayPauseIcon();

  const newTime = (frameNum - 1) / videoFps;
  isSyncing = true;
  detVid.currentTime = newTime;
  if (hasOriginal) origVid.currentTime = newTime;
  isSyncing = false;

  document.getElementById("seekSlider").value = newTime;
  document.getElementById("currentTimeDisplay").textContent = fmtTime(newTime);
  updateLiveStats(newTime);
  updateFrameDisplay(newTime);
}

function updatePlayPauseIcon() {
  const icon = document.getElementById("playIcon");
  if (!icon) return;
  if (isPlaying) {
    // pause icon (two bars)
    icon.innerHTML = '<rect x="6" y="4" width="4" height="16" fill="white" stroke="none" rx="1"/><rect x="14" y="4" width="4" height="16" fill="white" stroke="none" rx="1"/>';
  } else {
    // play icon (triangle)
    icon.innerHTML = '<polygon points="6,3 20,12 6,21" fill="white" stroke="none"/>';
  }
}

function updateAlarmIcon() {
  const icon = document.getElementById("alarmIcon");
  if (!icon) return;
  if (isAlarmMuted) {
    // Muted icon (speaker with X)
    icon.innerHTML = '<path d="M11 5L6 9H2v6h4l5 4V5z M23 9l-6 6 M17 9l6 6" stroke="white" fill="none" stroke-width="2"/>';
  } else {
    // Unmuted icon (speaker with waves)
    icon.innerHTML = '<path d="M11 5L6 9H2v6h4l5 4V5z M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07" stroke="white" fill="none" stroke-width="2"/>';
  }
}

// --- Live Stats Panel ---
function updateLiveStats(currentTime) {
  if (!frameData || !frameData.frames || !frameData.frames.length) return;

  // binary search for closest frame
  const frames = frameData.frames;
  let lo = 0, hi = frames.length - 1, best = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].t <= currentTime) {
      best = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }

  const f = frames[best];
  setLiveStatValue("lsFrame", f.frame);
  setLiveStatValue("lsTimestamp", fmtTime(f.t));
  setLiveStatValue("lsCount", f.count);
  setLiveStatValue("lsDensity", f.density_pct + "%");
  setLiveStatValue("lsThreshold", f.threshold);
  setLiveStatValue("lsOccupancy", f.occupancy_pct + "%");

  const riskEl = document.getElementById("lsRisk");
  if (riskEl && riskEl.textContent !== f.status) {
    riskEl.textContent = f.status;
    riskEl.style.color = STATUS_COLORS[f.status] || "inherit";
    riskEl.classList.remove("pulse");
    void riskEl.offsetWidth; // force reflow
    riskEl.classList.add("pulse");
  }
  
  if (currentAlarmStatus !== f.status) {
    currentAlarmStatus = f.status;
    if (isPlaying && !isAlarmMuted) {
      AlarmSystem.play(currentAlarmStatus);
    }
  }

  setLiveStatValue("lsInference", f.inference_ms + " ms");
}

function setLiveStatValue(elId, value) {
  const el = document.getElementById(elId);
  if (!el) return;
  const strVal = String(value);
  if (el.textContent !== strVal) {
    el.textContent = strVal;
    el.classList.remove("pulse");
    void el.offsetWidth;
    el.classList.add("pulse");
  }
}

function updateFrameDisplay(currentTime) {
  const currentFrame = Math.max(1, Math.min(totalVideoFrames, Math.round(currentTime * videoFps) + 1));
  document.getElementById("frameCurrentDisplay").textContent = `Frame: ${currentFrame} / ${totalVideoFrames}`;
}

function fmtTime(sec) {
  sec = sec || 0;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  const ms = Math.floor((sec % 1) * 10);
  return `${m}:${String(s).padStart(2, "0")}.${ms}`;
}

function summaryRow(label, value) {
  return `<div class="summary-row"><span>${label}</span><b>${escapeHtml(value)}</b></div>`;
}

function destroyChart(key) { if (charts[key]) { charts[key].destroy(); delete charts[key]; } }

function renderCharts(data) {
  const ts = data.timeseries;
  const labels = ts.map(p => fmtDuration(p.t));
  const counts = ts.map(p => p.count);
  const colors = ts.map(p => STATUS_COLORS[p.status]);

  ["chartCountTime", "chartDensity", "chartOccupancy", "chartAlertFreq", "chartDistribution"]
    .forEach(destroyChart);

  const ctx1 = document.getElementById("chartCountTime");
  charts.chartCountTime = new Chart(ctx1, {
    type: "line",
    data: { labels, datasets: [{ data: counts, borderColor: "#2563EB", backgroundColor: "rgba(37,99,235,.08)", fill: true, tension: .3, pointRadius: 0 }] },
    options: baseChartOptions(),
  });

  const ctx2 = document.getElementById("chartDensity");
  charts.chartDensity = new Chart(ctx2, {
    type: "bar",
    data: { labels, datasets: [{ data: counts, backgroundColor: colors, borderRadius: 3 }] },
    options: baseChartOptions(),
  });

  const ctx3 = document.getElementById("chartOccupancy");
  charts.chartOccupancy = new Chart(ctx3, {
    type: "line",
    data: { labels, datasets: [{ data: counts, borderColor: "#22C55E", backgroundColor: "rgba(34,197,94,.08)", fill: true, tension: .4, pointRadius: 0, borderWidth: 2 }] },
    options: baseChartOptions(),
  });

  const sevCount = { WARNING: 0, HIGH: 0, CRITICAL: 0 };
  data.events.forEach(e => { sevCount[e.severity] = (sevCount[e.severity] || 0) + 1; });
  const ctx4 = document.getElementById("chartAlertFreq");
  charts.chartAlertFreq = new Chart(ctx4, {
    type: "bar",
    data: {
      labels: ["Warning", "High", "Critical"],
      datasets: [{ data: [sevCount.WARNING, sevCount.HIGH, sevCount.CRITICAL],
        backgroundColor: [STATUS_COLORS.WARNING, STATUS_COLORS.HIGH, STATUS_COLORS.CRITICAL], borderRadius: 6 }],
    },
    options: baseChartOptions(),
  });

  const buckets = {};
  counts.forEach(c => {
    const b = Math.floor(c / 5) * 5;
    const key = `${b}-${b + 4}`;
    buckets[key] = (buckets[key] || 0) + 1;
  });
  const bucketKeys = Object.keys(buckets).sort((a, b) => parseInt(a) - parseInt(b));
  const ctx5 = document.getElementById("chartDistribution");
  charts.chartDistribution = new Chart(ctx5, {
    type: "bar",
    data: { labels: bucketKeys, datasets: [{ data: bucketKeys.map(k => buckets[k]), backgroundColor: "#2563EB", borderRadius: 4 }] },
    options: baseChartOptions(),
  });
}

function baseChartOptions() {
  return {
    responsive: true,
    maintainAspectRatio: true,
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { maxTicksLimit: 8, font: { size: 10 } }, grid: { display: false } },
      y: { ticks: { font: { size: 10 } }, grid: { color: "#EEF2F7" } },
    },
  };
}

function renderTimeline(timeseries, events, duration) {
  const el = document.getElementById("eventTimeline");
  if (!timeseries.length) { el.innerHTML = ""; return; }
  el.innerHTML = timeseries.map(p => {
    const widthPct = Math.max(100 / timeseries.length, 0.4);
    return `<div class="tl-marker" style="background:${STATUS_COLORS[p.status]};flex-basis:${widthPct}%"
              title="${fmtDuration(p.t)} — ${p.status} (${p.count} people)"
              data-t="${p.t}"></div>`;
  }).join("");
  el.querySelectorAll(".tl-marker").forEach(m => {
    m.addEventListener("click", () => {
      const t = parseFloat(m.dataset.t);
      const video = document.getElementById("analysisVideo");
      const origVideo = document.getElementById("originalVideo");
      video.currentTime = t;
      if (origVideo) origVideo.currentTime = t;
      video.play();
      if (origVideo) origVideo.play().catch(() => {});
      isPlaying = true;
      updatePlayPauseIcon();
      updateLiveStats(t);
      updateFrameDisplay(t);
      if (!isAlarmMuted) AlarmSystem.play(currentAlarmStatus);
    });
  });
}

function renderEventsTable(events) {
  const body = document.getElementById("eventsTableBody");
  if (!events.length) {
    body.innerHTML = `<tr><td colspan="8" class="empty-hint">No overcrowding events detected in this video.</td></tr>`;
    return;
  }
  body.innerHTML = events.map(e => `
    <tr class="severity-${e.severity}">
      <td>${fmtDuration(e.start_t)}</td>
      <td>${fmtDuration(e.end_t)}</td>
      <td>${e.duration}s</td>
      <td>${e.peak_count}</td>
      <td>${e.density_pct}%</td>
      <td><span class="badge badge-${e.severity}">${e.severity}</span></td>
      <td>${e.status}</td>
      <td><button class="link-btn" data-t="${e.start_t}">View</button></td>
    </tr>`).join("");
  body.querySelectorAll(".link-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const t = parseFloat(btn.dataset.t);
      const video = document.getElementById("analysisVideo");
      const origVideo = document.getElementById("originalVideo");
      video.currentTime = t;
      if (origVideo) origVideo.currentTime = t;
      video.play();
      if (origVideo) origVideo.play().catch(() => {});
      isPlaying = true;
      updatePlayPauseIcon();
      updateLiveStats(t);
      updateFrameDisplay(t);
      if (!isAlarmMuted) AlarmSystem.play(currentAlarmStatus);
      video.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
}

function renderKeyframes(keyframes) {
  const grid = document.getElementById("keyframeGrid");
  if (!keyframes.length) {
    grid.innerHTML = '<div class="empty-hint">No significant overcrowding moments captured.</div>';
    return;
  }
  grid.innerHTML = keyframes.map(k => `
    <div class="keyframe-card">
      <img src="${k.url}" alt="Overcrowding snapshot at ${fmtDuration(k.t)}">
      <div class="keyframe-meta">
        <div class="keyframe-time">${fmtDuration(k.t)}</div>
        <div class="keyframe-count">${k.count} people</div>
        <span class="badge badge-${k.severity}">${k.severity}</span>
      </div>
    </div>`).join("");
}

// ---------------------------------------------------------------------
// Reports page
// ---------------------------------------------------------------------
async function loadReportVideoOptions() {
  const select = document.getElementById("reportVideoSelect");
  try {
    const res = await fetch("/api/history");
    const rows = await res.json();
    if (!rows.length) {
      select.innerHTML = `<option>No analyzed videos yet</option>`;
      document.getElementById("exportButtons").hidden = true;
      document.getElementById("reportMeta").hidden = true;
      return;
    }
    select.innerHTML = rows.map(r =>
      `<option value="${r.job_id}">${escapeHtml(r.original_filename)} — ${fmtDate(r.processed_at)}</option>`).join("");
    select.onchange = () => updateReportPanel(select.value, rows);
    updateReportPanel(select.value, rows);
  } catch (e) { console.error(e); }
}

function updateReportPanel(jobId, rows) {
  const row = rows.find(r => r.job_id === jobId);
  if (!row) return;
  document.getElementById("reportMeta").hidden = false;
  document.getElementById("exportButtons").hidden = false;
  document.getElementById("reportDate").textContent = fmtDate(row.processed_at);
  document.getElementById("reportDuration").textContent = fmtDuration(row.duration_sec);
  document.getElementById("reportRisk").textContent = row.overall_risk;

  document.getElementById("exportPdf").onclick = () => window.open(`/api/report/pdf/${jobId}`, "_blank");
  document.getElementById("exportExcel").onclick = () => window.open(`/api/report/excel/${jobId}`, "_blank");
  document.getElementById("exportCsv").onclick = () => window.open(`/api/report/csv/${jobId}`, "_blank");
}

// ---------------------------------------------------------------------
// History page
// ---------------------------------------------------------------------
let historyRows = [];
async function loadHistory() {
  try {
    const res = await fetch("/api/history");
    historyRows = await res.json();
    renderHistoryTable(historyRows);
  } catch (e) { console.error(e); }
}

function renderHistoryTable(rows) {
  const body = document.getElementById("historyTableBody");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="6" class="empty-hint">No videos analyzed yet.</td></tr>`;
    return;
  }
  body.innerHTML = rows.map(r => `
    <tr>
      <td>${escapeHtml(r.original_filename)}</td>
      <td>${fmtDate(r.processed_at)}</td>
      <td><span class="badge badge-SAFE">Done</span></td>
      <td>${r.max_count}</td>
      <td>${r.total_alerts}</td>
      <td><button class="link-btn" data-id="${r.job_id}">View Analysis</button></td>
    </tr>`).join("");
  body.querySelectorAll(".link-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      await openAnalysis(btn.dataset.id);
      goToPage("analysis");
    });
  });
}

document.getElementById("historySearch").addEventListener("input", e => {
  const q = e.target.value.toLowerCase();
  renderHistoryTable(historyRows.filter(r => r.original_filename.toLowerCase().includes(q)));
});

// ---------------------------------------------------------------------
// Public Crowd Safety QR Code & Modal System
// ---------------------------------------------------------------------
let publicInfoCache = null;

async function fetchPublicInfo(jobId = null) {
  const url = jobId ? `/api/public_info/${jobId}` : `/api/public_info`;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to fetch public info");
    return await res.json();
  } catch (err) {
    console.error("Public info fetch error:", err);
    return null;
  }
}

async function updateDashboardQrWidget() {
  const info = await fetchPublicInfo();
  if (!info) return;
  publicInfoCache = info;

  const urlText = document.getElementById("dashPublicUrlText");
  const openLink = document.getElementById("dashOpenPublicLink");
  const dlLink = document.getElementById("dashDownloadQrLink");
  const qrImg = document.getElementById("dashQrImg");

  if (urlText) urlText.textContent = info.public_url;
  if (openLink) openLink.href = info.public_url;
  if (dlLink) dlLink.href = info.qr_code_url;
  if (qrImg) qrImg.src = info.qr_code_url + "?_t=" + Date.now();
}

async function openQrModal(jobId = null) {
  const backdrop = document.getElementById("qrModalBackdrop");
  if (!backdrop) return;

  const modalImg = document.getElementById("modalQrImg");
  const modalUrlText = document.getElementById("modalQrUrlText");
  const modalOpenBtn = document.getElementById("modalOpenUrlBtn");
  const modalDlBtn = document.getElementById("modalDownloadQrBtn");

  modalUrlText.textContent = "Generating QR Code...";
  backdrop.hidden = false;

  const info = await fetchPublicInfo(jobId);
  if (!info) {
    modalUrlText.textContent = "Could not load public URL";
    return;
  }

  modalUrlText.textContent = info.public_url;
  modalImg.src = info.qr_code_url + "?_t=" + Date.now();
  modalOpenBtn.href = info.public_url;
  modalDlBtn.href = info.qr_code_url;
}

function closeQrModal() {
  const backdrop = document.getElementById("qrModalBackdrop");
  if (backdrop) backdrop.hidden = true;
}

function setupQrCodeHandlers() {
  // Topbar open button
  const topbarBtn = document.getElementById("openQrModalBtn");
  if (topbarBtn) {
    topbarBtn.addEventListener("click", () => openQrModal(currentJobId));
  }

  // Dashboard card thumbnail click
  const dashThumb = document.getElementById("dashQrThumbnail");
  if (dashThumb) {
    dashThumb.addEventListener("click", () => openQrModal(null));
  }

  // Analysis page QR button
  const analysisQrBtn = document.getElementById("analysisQrBtn");
  if (analysisQrBtn) {
    analysisQrBtn.addEventListener("click", () => openQrModal(currentJobId));
  }

  // Modal close buttons
  const closeBtn = document.getElementById("closeQrModalBtn");
  if (closeBtn) {
    closeBtn.addEventListener("click", closeQrModal);
  }

  const backdrop = document.getElementById("qrModalBackdrop");
  if (backdrop) {
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeQrModal();
    });
  }

  // Copy buttons
  const copyDashBtn = document.getElementById("copyPublicUrlBtn");
  if (copyDashBtn) {
    copyDashBtn.addEventListener("click", () => {
      const url = document.getElementById("dashPublicUrlText")?.textContent;
      if (url) {
        navigator.clipboard.writeText(url).then(() => {
          const label = document.getElementById("copyBtnLabel");
          if (label) {
            const old = label.textContent;
            label.textContent = "Copied!";
            setTimeout(() => { label.textContent = old; }, 2000);
          }
        });
      }
    });
  }

  const copyModalBtn = document.getElementById("modalCopyUrlBtn");
  if (copyModalBtn) {
    copyModalBtn.addEventListener("click", () => {
      const url = document.getElementById("modalQrUrlText")?.textContent;
      if (url && url !== "Loading..." && url !== "Generating QR Code...") {
        navigator.clipboard.writeText(url).then(() => {
          const old = copyModalBtn.textContent;
          copyModalBtn.textContent = "Copied!";
          setTimeout(() => { copyModalBtn.textContent = old; }, 2000);
        });
      }
    });
  }

  // Esc key to close modal
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && backdrop && !backdrop.hidden) {
      closeQrModal();
    }
  });

  updateDashboardQrWidget();
}

// ---------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------
loadDashboardSummary();
refreshNotifications();
setInterval(refreshNotifications, 30000);
setupQrCodeHandlers();
