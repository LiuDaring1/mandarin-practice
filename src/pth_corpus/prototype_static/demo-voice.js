"use strict";

// A separate preference: never changes training progress or corpus IDs.
(() => {
  const storageKey = "pth-demo-voice-v1";
  let selected = null;
  window.demoVoice = {
    url(path) {
      if (!selected) return path;
      const url = new URL(path, location.origin);
      url.searchParams.set("voice", selected);
      return url.pathname + url.search;
    },
  };
  const picker = document.getElementById("demo-voice-picker");
  if (!picker) return;
  fetch("/api/voice-library").then(response => {
    if (!response.ok) throw new Error("Voice choices unavailable");
    return response.json();
  }).then(library => {
    if (!library.active || !library.voices?.length) return;
    let saved;
    try { saved = localStorage.getItem(storageKey); } catch { /* use default */ }
    selected = library.voices.some(voice => voice.id === saved) ? saved : library.default_voice;
    const choices = picker.querySelector(".demo-voice-options");
    for (const voice of library.voices) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = {"news-female": "女声", "news-male": "男声"}[voice.id] || voice.label;
      button.setAttribute("aria-label", voice.label);
      button.title = voice.label;
      button.dataset.voice = voice.id;
      button.setAttribute("aria-pressed", String(selected === voice.id));
      button.addEventListener("click", () => {
        selected = voice.id;
        try { localStorage.setItem(storageKey, selected); } catch { /* memory-only */ }
        for (const item of choices.children) {
          item.setAttribute("aria-pressed", String(item === button));
        }
      });
      choices.appendChild(button);
    }
    picker.hidden = library.voices.length < 2;
  }).catch(() => { /* Original audio remains usable without a published library. */ });
})();
