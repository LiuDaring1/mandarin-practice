"use strict";

// Shared presentation helpers. These never write training or reward progress.
const UI_ICONS = {
  words: '<path d="M5 5h14v11H9l-4 4V5Z"/><path d="M9 9h6M9 12h4"/>',
  sentence: '<path d="M4 5h16v12H9l-5 3V5Z"/><path d="M8 9h8M8 13h6"/>',
  headphones: '<path d="M4 14v-3a8 8 0 0 1 16 0v3"/><rect x="3" y="11" width="4" height="9" rx="2"/><rect x="17" y="11" width="4" height="9" rx="2"/>',
  gallery: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  speaker: '<path d="m11 4-6 5H2v6h3l6 5V4ZM15 8a6 6 0 0 1 0 8M18 5a10 10 0 0 1 0 14"/>',
  mic: '<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4M8 22h8"/>',
  replay: '<path d="M4 10a8 8 0 1 1 1 8M4 4v6h6"/>',
  play: '<path d="m8 4 12 8-12 8V4Z"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  arrow: '<path d="m9 5 7 7-7 7"/>',
  back: '<path d="m15 5-7 7 7 7"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  star: '<path d="m12 2 3 6.5 7 .9-5.2 5 1.3 7.1-6.1-3.4-6.1 3.4 1.3-7.1-5.2-5 7-.9L12 2Z"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 2v6M17 2v6M3 11h18M8 15h2M14 15h2"/>',
};

function uiIcon(name) {
  return `<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${UI_ICONS[name] || UI_ICONS.star}</svg>`;
}

function uiMascot(name, className = "") {
  return `<img class="ui-mascot ${className}" src="/assets/illustrations/${name}.webp" width="256" height="256" alt="" aria-hidden="true" decoding="async" draggable="false">`;
}

function uiEntryArt(tone) {
  const name = tone === "orange" ? "orange" : tone === "violet" ? "violet" : "welcome";
  return `<span class="entry-portrait" aria-hidden="true">${uiMascot(name)}</span>`;
}

function uiPhaseMarkup(kind) {
  return `<div class="practice-phase" id="${kind}-phase" data-phase="idle">
    <div class="phase-steps"><span data-step="reference">${uiIcon("speaker")}示范音</span><i></i><span data-step="follow">${uiIcon("mic")}跟读计时</span></div>
    <div class="phase-meter" aria-hidden="true"><span></span></div>
    <p class="phase-caption" aria-live="off">准备好，跟着示范慢慢读</p>
  </div>`;
}

function uiRenderPhase(kind, info) {
  const box = document.getElementById(`${kind}-phase`);
  if (!box || !info) return;
  const mode = info.mode;
  const phase = mode === "playing_reference" || mode === "playing" ? "reference"
    : mode === "waiting_follow" || mode === "following" ? "follow" : mode;
  box.dataset.phase = phase;
  let pct = 0;
  let caption = "准备好，跟着示范慢慢读";
  if (phase === "reference") {
    pct = info.audio.duration > 0 ? info.audio.currentTime / info.audio.duration : 0;
    caption = kind === "sentence" ? `第 ${info.pass || 1} 遍 · 听示范音` : "听示范音，留意收尾的声音";
  } else if (phase === "follow") {
    const remaining = Math.max(0, info.deadline - performance.now());
    pct = info.total > 0 ? 1 - remaining / info.total : 0;
    caption = `跟读计时 · 剩余 ${(remaining / 1000).toFixed(1)} 秒`;
  } else if (phase === "previewing") {
    caption = "先看一下句子，再听示范";
  } else if (phase === "finishing") {
    caption = "正在收好这一段录音…";
  } else if (phase === "paused") {
    caption = ["following", "waiting_follow"].includes(info.resumeFrom)
      ? "已暂停 · 这一遍将重新跟读" : "已暂停 · 准备好后继续";
    pct = Number(box.dataset.progress || 0);
  } else if (phase === "error") caption = info.errorMessage || "音频暂时无法播放，请点重播再试";
  else if (phase === "loading_session" || phase === "loading") caption = "正在准备本次练习…";
  pct = Math.max(0, Math.min(1, pct));
  box.dataset.progress = String(pct);
  box.querySelector(".phase-meter span").style.width = `${pct * 100}%`;
  const text = box.querySelector(".phase-caption");
  if (text.textContent !== caption) text.textContent = caption;
}

// Keep modal keyboard focus on the visible dialog, including after a redraw.
function uiInit(readPractice) {
  document.querySelectorAll("[data-icon]").forEach((el) => { el.innerHTML = uiIcon(el.dataset.icon); });
  document.querySelectorAll("[data-phase-slot]").forEach((el) => { el.innerHTML = uiPhaseMarkup(el.dataset.phaseSlot); });
  setInterval(() => {
    if (document.hidden) return;
    const data = readPractice();
    if (data) uiRenderPhase(data.kind, data);
  }, 100);

  const layers = [...document.querySelectorAll(".overlay, .dialog-backdrop")];
  const returnFocus = new WeakMap();
  const focusable = (layer) => [...layer.querySelectorAll('button:not(:disabled), input:not(:disabled), [tabindex="0"]')]
    .filter((el) => el.getClientRects().length > 0);
  const observer = new MutationObserver((mutations) => {
    const open = layers.some((layer) => !layer.classList.contains("hidden"));
    document.body.classList.toggle("modal-open", open);
    document.getElementById("app").inert = open;
    for (const { target, oldValue } of mutations) {
      const wasHidden = /\bhidden\b/.test(oldValue || "");
      const hidden = target.classList.contains("hidden");
      if (wasHidden && !hidden) {
        returnFocus.set(target, document.activeElement);
        requestAnimationFrame(() => focusable(target)[0]?.focus({ preventScroll: true }));
      } else if (!wasHidden && hidden) {
        const prev = returnFocus.get(target);
        const next = prev?.isConnected ? prev
          : prev?.id ? document.getElementById(prev.id)
          : prev?.dataset.detail ? document.querySelector(`[data-detail="${CSS.escape(prev.dataset.detail)}"]`)
          : prev?.classList.contains("entry-btn") ? document.querySelector('#entry-list [aria-pressed="true"]') : null;
        next?.focus({ preventScroll: true });
      }
    }
  });
  layers.forEach((layer) => observer.observe(layer, { attributes: true, attributeFilter: ["class"], attributeOldValue: true }));
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const layer = [...layers].reverse().find((el) => !el.classList.contains("hidden"));
    if (!layer) return;
    const items = focusable(layer);
    if (!items.length) { event.preventDefault(); return; }
    const first = items[0], last = items[items.length - 1];
    if (!layer.contains(document.activeElement) || (event.shiftKey && document.activeElement === first)) {
      event.preventDefault(); (event.shiftKey ? last : first).focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  });
}
