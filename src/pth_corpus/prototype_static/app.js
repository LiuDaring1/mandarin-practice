"use strict";

// Sound assets are replaceable through sounds/manifest.json; training is independent of audio availability.
const sfx = window.appSfx || {unlock(){},play(){},stop(){},stopBus(){},beginTeaching(){return ()=>{};},settlement(){}};

const TIMING_KEY = "pth-prototype-timing-v1";
const PROGRESS_KEY = "pth-nasal-progress-v1";
const SENTENCE_PINYIN_KEY = "pth-sentence-pinyin-v1";
const WRONG_BOOK_KEY = "pth-discrim-wrongbook-v1";
const reading = window.readingAssessment;
const READING_SPEED_KEY = "pth-reading-speed-v1";
let sentenceSpeed = .85;
try { const saved=Number(localStorage.getItem(READING_SPEED_KEY)); if ([.75,.85,1].includes(saved)) sentenceSpeed=saved; } catch { /* optional preference */ }
function initReadingControls() {
  const update = () => document.querySelectorAll('[data-reading-speed-picker]').forEach(group => {
    group.replaceChildren();
    for (const speed of [.75,.85,1]) {
      const button=document.createElement('button');button.type='button';
      button.textContent=`${speed === 1 ? '原速' : speed === .85 ? '舒适' : '慢速'} ${speed}×`;
      button.setAttribute('aria-pressed',String(sentenceSpeed===speed));
      button.onclick=()=>{
        sentenceSpeed=speed;try{localStorage.setItem(READING_SPEED_KEY,String(speed));}catch{}
        els.sentencePlayer.preservesPitch=true;els.sentencePlayer.playbackRate=speed;update();
      };group.append(button);
    }
  });
  update();
  document.getElementById('reading-done-sentence').onclick=sentenceFollowDone;
  document.getElementById('reading-done-word').onclick=followDone;
  document.getElementById('reading-review-btn').onclick=()=>{
    resetToHome();setView('complete');
    reading.mountReview(els.completeBody,()=>startSentenceSession('mixed',10,true),resetToHome);
  };
}
const discrimAudio = new Audio();
let discrimAudioRelease = null;
let discrimAudioToken = 0;

const TONES = {
  teal: { main: "#149e91", deep: "#077d73", soft: "#e1f4ed" },
  orange: { main: "#ed963e", deep: "#aa5814", soft: "#fff0d9" },
  violet: { main: "#9170d7", deep: "#7151b3", soft: "#f0e9fc" },
  green: { main: "#36a78a", deep: "#187c61", soft: "#e5f5e9" },
};

const SENTENCE_FILTERS = [
  { id: "front", label: "前鼻为主", desc: "前鼻音节多 · 侧重 en · in" },
  { id: "back", label: "后鼻为主", desc: "后鼻音节多 · 侧重 eng · ing" },
  { id: "mixed", label: "前后都有", desc: "同句前后鼻对比 · 侧重 en / in / eng / ing" },
];

const SENTENCE_FILTER_LABELS = {
  front: "前鼻为主", back: "后鼻为主", mixed: "前后都有",
};
const SENTENCE_COUNT_DEFAULT = 10;

// 听辨练习：整词答完统一反馈后 1.6s 自动下一词
const DISCRIM_FEEDBACK_MS = 700;
const DISCRIM_PAIR_LABELS = {
  en_eng: { front: "前鼻 en", back: "后鼻 eng" },
  in_ing: { front: "前鼻 in", back: "后鼻 ing" },
};
// 字下答题位只填拼音本身（与反馈后的彩色韵母一致）
const DISCRIM_PAIR_FINALS = {
  en_eng: { front: "en", back: "eng" },
  in_ing: { front: "in", back: "ing" },
};

const els = {
  app: document.getElementById("app"),
  viewHome: document.getElementById("view-home"),
  viewTraining: document.getElementById("view-training"),
  viewComplete: document.getElementById("view-complete"),
  viewCalibration: document.getElementById("view-calibration"),
  viewWall: document.getElementById("view-wall"),
  viewHistory: document.getElementById("view-history"),
  historyLink: document.getElementById("history-link"),
  wallLink: document.getElementById("wall-link"),
  statToday: document.getElementById("stat-today"),
  statTotal: document.getElementById("stat-total"),
  statStreak: document.getElementById("stat-streak"),
  trioBar: document.getElementById("trio-bar"),
  entryList: document.getElementById("entry-list"),
  durationOptions: document.getElementById("duration-options"),
  rewardHint: document.getElementById("reward-hint"),
  startBtn: document.getElementById("start-btn"),
  startLabel: document.getElementById("start-label"),
  tabWords: document.getElementById("tab-words"),
  tabSentence: document.getElementById("tab-sentence"),
  tabDiscrim: document.getElementById("tab-discrim"),
  paneWords: document.getElementById("pane-words"),
  paneSentence: document.getElementById("pane-sentence"),
  paneDiscrim: document.getElementById("pane-discrim"),
  sentenceFilterOptions: document.getElementById("sentence-filter-options"),
  sentenceDurationHint: document.getElementById("sentence-duration-hint"),
  sentenceDurationOptions: document.getElementById("sentence-duration-options"),
  sentenceStartBtn: document.getElementById("sentence-start-btn"),
  sentenceStartLabel: document.getElementById("sentence-start-label"),
  discrimCard: document.getElementById("discrim-card"),
  discrimSizeBlock: document.getElementById("discrim-size-block"),
  discrimSizeHint: document.getElementById("discrim-size-hint"),
  discrimSizeOptions: document.getElementById("discrim-size-options"),
  discrimStartBtn: document.getElementById("discrim-start-btn"),
  discrimStartLabel: document.getElementById("discrim-start-label"),
  discrimReviewCard: document.getElementById("discrim-review-card"),
  discrimReviewBtn: document.getElementById("discrim-review-btn"),
  discrimReviewLabel: document.getElementById("discrim-review-label"),
  discrimSkip: document.getElementById("discrim-skip"),
  readyHint: document.getElementById("ready-hint"),
  exitBtn: document.getElementById("exit-btn"),
  timer: document.getElementById("timer"),
  progressTrack: document.getElementById("progress-track"),
  progressFill: document.getElementById("progress-fill"),
  progressBead: document.getElementById("progress-bead"),
  word: document.getElementById("word"),
  pinyin: document.getElementById("pinyin"),
  status: document.getElementById("status"),
  replayBtn: document.getElementById("replay-btn"),
  pauseBtn: document.getElementById("pause-btn"),
  pauseIcon: document.querySelector("#pause-btn .ctl-icon"),
  pauseLabel: document.querySelector("#pause-btn .ctl-label"),
  completeBody: document.getElementById("complete-body"),
  calLink: document.getElementById("cal-link"),
  calBack: document.getElementById("cal-back"),
  calGroups: document.getElementById("cal-groups"),
  calTabs: document.getElementById("cal-tabs"),
  calStop: document.getElementById("cal-stop"),
  calStatus: document.getElementById("cal-status"),
  wallBack: document.getElementById("wall-back"),
  wallBody: document.getElementById("wall-body"),
  historyBack: document.getElementById("history-back"),
  historyBody: document.getElementById("history-body"),
  pickerOverlay: document.getElementById("picker-overlay"),
  pickerBody: document.getElementById("picker-body"),
  detailOverlay: document.getElementById("detail-overlay"),
  detailBody: document.getElementById("detail-body"),
  filterOverlay: document.getElementById("filter-overlay"),
  filterBody: document.getElementById("filter-body"),
  exitDialog: document.getElementById("exit-dialog"),
  continueBtn: document.getElementById("continue-btn"),
  endBtn: document.getElementById("end-btn"),
  debugPanel: document.getElementById("debug-panel"),
  debugToggle: document.getElementById("debug-toggle"),
  debugClose: document.getElementById("debug-close"),
  dbgProfile: document.getElementById("dbg-profile"),
  dbgSession: document.getElementById("dbg-session"),
  dbgSeed: document.getElementById("dbg-seed"),
  dbgItem: document.getElementById("dbg-item"),
  dbgIndex: document.getElementById("dbg-index"),
  dbgClip: document.getElementById("dbg-clip"),
  dbgEst: document.getElementById("dbg-est"),
  dbgFinals: document.getElementById("dbg-finals"),
  dbgExtra: document.getElementById("dbg-extra"),
  dbgMin: document.getElementById("dbg-min"),
  dbgTransition: document.getElementById("dbg-transition"),
  dbgSkip: document.getElementById("dbg-skip"),
  dbgFinish: document.getElementById("dbg-finish"),
  dbgReset: document.getElementById("dbg-reset"),
  player: document.getElementById("player"),
  sentencePlayer: document.getElementById("sentence-player"),
  viewSentence: document.getElementById("view-sentence"),
  sentenceExitBtn: document.getElementById("sentence-exit-btn"),
  sentenceProgressText: document.getElementById("sentence-progress-text"),
  sentenceProgressFill: document.getElementById("sentence-progress-fill"),
  sentenceProgressBead: document.getElementById("sentence-progress-bead"),
  sentenceFilterTag: document.getElementById("sentence-filter-tag"),
  sentenceSource: document.getElementById("sentence-source"),
  sentenceText: document.getElementById("sentence-text"),
  sentenceStatus: document.getElementById("sentence-status"),
  sentenceLegend: document.getElementById("sentence-legend"),
  sentencePinyinToggle: document.getElementById("sentence-pinyin-toggle"),
  sentenceReplayBtn: document.getElementById("sentence-replay-btn"),
  sentencePauseBtn: document.getElementById("sentence-pause-btn"),
  sentencePauseIcon: document.querySelector("#sentence-pause-btn .ctl-icon"),
  sentencePauseLabel: document.querySelector("#sentence-pause-btn .ctl-label"),
  sentenceFilterOverlay: document.getElementById("sentence-filter-overlay"),
  sentenceFilterBody: document.getElementById("sentence-filter-body"),
  viewDiscrim: document.getElementById("view-discrim"),
  discrimExitBtn: document.getElementById("discrim-exit-btn"),
  discrimProgressText: document.getElementById("discrim-progress-text"),
  discrimProgressFill: document.getElementById("discrim-progress-fill"),
  discrimProgressBead: document.getElementById("discrim-progress-bead"),
  discrimStage: document.getElementById("discrim-stage"),
  discrimWord: document.getElementById("discrim-word"),
  discrimStatus: document.getElementById("discrim-status"),
  discrimAlert: document.getElementById("discrim-alert"),
  discrimFrontBtn: document.getElementById("discrim-front-btn"),
  discrimBackBtn: document.getElementById("discrim-back-btn"),
};

const state = {
  home: null,
  activeTab: "words",
  achievement: null,
  artworks: [],
  calibration: null,
  calibrationSpeed: "normal",
  calibrationGroup: "an_ang",
  progress: loadProgress(),
  timingDefaults: { extra_follow_sec: 0.8, min_follow_sec: 1.8, transition_sec: 0.3 },
  entryId: null,
  profileId: null,
  profileLabel: null,
  duration: 10,
  pickerMode: null,
  pickerChoice: null,
  filterDraft: [],
  session: null,
  index: 0,
  mode: "idle",
  resumeFrom: null,
  followTimeout: null,
  followDeadline: 0,
  followRemainingMs: 0,
  tickTimer: null,
  lastTick: 0,
  timerRemainingMs: 0,
  startTime: null,
  replayCount: 0,
  pauseCount: 0,
  completedItems: 0,
  // 句子练习（独立于生成器，不写 Profile/拼豆）
  sentenceSession: null,
  sentenceIndex: 0,
  sentenceFilter: "front",
  sentenceMode: "idle",
  sentenceReplayCount: 0,
  sentencePauseCount: 0,
  sentenceCompleted: 0,
  sentenceStartTime: null,
  sentenceElapsedMs: 0,
  sentenceTickTimer: null,
  sentenceLastTick: 0,
  sentenceFollowTimeout: null,
  sentenceFollowDeadline: 0,
  sentenceFollowRemainingMs: 0,
  sentenceResumeFrom: null,
  sentencePass: 1,
  sentencePinyin: loadSentencePinyin(),
  sentenceCount: SENTENCE_COUNT_DEFAULT,
  // 听辨练习（主词库持续覆盖 + 趁热巩固 + 错题复习）
  discrimInfo: null,
  discrimPracticeSize: 50,
  discrimSession: null,
  discrimKind: null, // "library" | "warmup" | "review"
  discrimQueue: null, // 趁热/复习队列（词条对象数组，客户端管理顺序）
  discrimIndex: 0,
  discrimPointIndex: 0,
  discrimAnswers: [],
  discrimWordResults: [],
  discrimMode: "idle",
  discrimStartTime: null,
  discrimElapsedMs: 0,
  discrimTickTimer: null,
  discrimLastTick: 0,
  discrimFeedbackTimeout: null,
  discrimConsecutive: 0,
  discrimConsecutivePeak: 0,
  discrimPerfectWords: 0,
  discrimCorrectPoints: 0,
  discrimPointCount: 0,
  discrimPlannedPoints: 0,      // 本轮计划判断总数（词库 + 趁热），用于完成比例
  discrimAcc: null,
  discrimLastApplyResult: null,
  discrimLastLibrary: null,   // 最近一次主词库结果（游标/总数）
  discrimWarmupTotal: 0,      // 本轮错词数（结算页展示趁热巩固）
  discrimReviewWrongFlags: {}, // 复习轮内答错过的词（最终答对时上报重置）
  discrimReviewDone: 0,        // 本次复习已过关词数（去重）
  discrimReviewDoneIds: {},    // 本次复习已过关词 id 集合
};

/* ---------- 持久化 ---------- */

function emptyProgress() {
  return {
    version: 2,
    onboardingDone: false,
    beadBalance: 0,
    currentArtworkId: null,
    artworks: {},
    sessions: [],
    entryFilters: {},
    comboAwardedDayKey: null,
  };
}

function loadProgress() {
  try {
    const saved = JSON.parse(localStorage.getItem(PROGRESS_KEY));
    if (saved && typeof saved === "object" && saved.version >= 1) {
      const base = emptyProgress();
      const progress = Object.assign(base, saved, {
        artworks: saved.artworks && typeof saved.artworks === "object" ? saved.artworks : {},
        sessions: Array.isArray(saved.sessions) ? saved.sessions : [],
        entryFilters:
          saved.entryFilters && typeof saved.entryFilters === "object" ? saved.entryFilters : {},
      });
      // 迁移到新版（100×100 猫猫系列经济）：历史 session 保留；
      // 旧作品记录按 id 保留（不匹配新目录的自然忽略），不主动删除用户数据。
      progress.version = 3;
      if (saved.comboAwardedDayKey === undefined) progress.comboAwardedDayKey = null;
      // v3（2026-08-27）：作品记录拆分 placedBeads（已亲手拼入）/ pendingBeads（待拼）；
      // 旧 earnedBeads（自动入账）整体迁移为已拼入，行为与迁移前视觉一致。
      Object.values(progress.artworks).forEach((rec) => {
        if (!rec || typeof rec !== "object") return;
        if (rec.placedBeads === undefined) {
          rec.placedBeads = Number(rec.earnedBeads || 0);
          delete rec.earnedBeads;
        }
        if (rec.pendingBeads === undefined) rec.pendingBeads = 0;
      });
      return progress;
    }
  } catch {
    /* ignore corrupt storage */
  }
  return emptyProgress();
}

function saveProgress() {
  try {
    localStorage.setItem(PROGRESS_KEY, JSON.stringify(state.progress));
  } catch {
    /* storage full or unavailable */
  }
}

/* ---------- 错题本（听辨答错的判断点） ---------- */

// 旧版错题本（localStorage）一次性迁移进服务端活跃错题池
async function migrateOldWrongBook() {
  try {
    const raw = localStorage.getItem(WRONG_BOOK_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    const ids = Array.from(
      new Set((parsed.items || []).map((entry) => entry.itemId).filter(Boolean))
    );
    localStorage.removeItem(WRONG_BOOK_KEY);
    if (!ids.length) return;
    await fetchJson("/api/discrim/seed-mistakes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_ids: ids }),
    });
  } catch (err) {
    console.warn("wrongbook migration failed", err);
  }
}

function newArtRecord() {
  return {
    startedAt: null,
    completedAt: null,
    placedBeads: 0,
    pendingBeads: 0,
    totalMinutes: 0,
    sessionCount: 0,
    frontNasalMinutes: 0,
    backNasalMinutes: 0,
    contrastMinutes: 0,
  };
}

function ensureArtRecord(id) {
  if (!state.progress.artworks[id]) {
    state.progress.artworks[id] = newArtRecord();
  }
  return state.progress.artworks[id];
}

function loadTiming() {
  try {
    const saved = JSON.parse(localStorage.getItem(TIMING_KEY));
    if (saved && typeof saved === "object") return saved;
  } catch {
    /* ignore corrupt storage */
  }
  return null;
}

function loadSentencePinyin() {
  try {
    const saved = localStorage.getItem(SENTENCE_PINYIN_KEY);
    if (saved === "false") return false;
  } catch {
    /* ignore corrupt storage */
  }
  return true;
}

function timing() {
  const saved = loadTiming() || {};
  return {
    extra_follow_sec:
      Number.isFinite(saved.extra_follow_sec) ? saved.extra_follow_sec : state.timingDefaults.extra_follow_sec,
    min_follow_sec:
      Number.isFinite(saved.min_follow_sec) ? saved.min_follow_sec : state.timingDefaults.min_follow_sec,
    transition_sec:
      Number.isFinite(saved.transition_sec) ? saved.transition_sec : state.timingDefaults.transition_sec,
  };
}

function saveTiming() {
  localStorage.setItem(
    TIMING_KEY,
    JSON.stringify({
      extra_follow_sec: Number(els.dbgExtra.value),
      min_follow_sec: Number(els.dbgMin.value),
      transition_sec: Number(els.dbgTransition.value),
    })
  );
}

/* ---------- 工具 ---------- */

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    let detail = res.statusText;
    if (data && data.detail) {
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    }
    throw new Error(detail);
  }
  return data;
}

function clamp01(value) {
  return Math.max(0, Math.min(1, value));
}

function todayKey(date) {
  const d = date || new Date();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${month}-${day}`;
}

/* ---------- 连续训练天数（streak，只记有效训练日，不发拼点） ---------- */

// 有效训练：任一正式训练（字词/句子/辨音）达到 ≥20% 有效门槛
function isValidSession(session) {
  if (!session || !session.dayKey) return false;
  if (session.type === "word") {
    const ratio = Number(session.ratio || 0);
    if (ratio > 0) return ratio >= 0.2;
    return !session.exitEarly; // 旧记录兜底：完整完成即有效
  }
  if (session.type === "sentence") {
    if (Number(session.sentenceTotal || 0) > 0) {
      return Number(session.sentenceCount || 0) / Number(session.sentenceTotal) >= 0.2;
    }
    return !session.exitEarly;
  }
  if (session.type === "discrim") {
    if (Number(session.discrimTotal || 0) > 0) {
      return Number(session.discrimPoints || 0) / Number(session.discrimTotal) >= 0.2;
    }
    return !session.exitEarly;
  }
  return false; // 错题复习不计入 streak / 累计训练日
}

function validSessionDayKeys() {
  const set = new Set();
  (state.progress.sessions || []).forEach((session) => {
    if (isValidSession(session)) set.add(session.dayKey);
  });
  return set;
}

function computeStreak() {
  const days = validSessionDayKeys();
  const has = (key) => days.has(key);
  const walk = (startDate) => {
    let count = 0;
    const cursor = new Date(startDate);
    let guard = 0;
    while (has(todayKey(cursor)) && guard < 400) {
      count += 1;
      cursor.setDate(cursor.getDate() - 1);
      guard += 1;
    }
    return count;
  };
  if (has(todayKey())) return { days: walk(new Date()), trainedToday: true };
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (has(todayKey(yesterday))) {
    return { days: walk(yesterday), trainedToday: false };
  }
  return { days: 0, trainedToday: false };
}

function streakAfterToday() {
  const streak = computeStreak();
  // Today's session either extends yesterday's run or starts a new one.
  return streak.trainedToday ? streak.days : streak.days + 1;
}

/* ---------- 统一拼点结算（字词 / 句子 / 听辨 共用） ---------- */

function completedToday(type) {
  const key = todayKey();
  return (state.progress.sessions || []).some(
    (session) => session.dayKey === key && session.type === type && !session.exitEarly
  );
}

function comboAwardedToday() {
  return state.progress.comboAwardedDayKey === todayKey();
}

async function settleActivity(payload) {
  try {
    return await fetchJson("/api/achievement/settle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    console.warn("reward settle failed", err);
    return null;
  }
}

/* ---------- 统一入账反馈（三类共用） ---------- */

function rewardBurstHtml(beads) {
  const icons = ["teal", "orange", "violet", "green", "pink", "yellow"];
  // 小数余量只在内部累计，用户端展示整数
  const shown = Math.floor(Math.max(0, Number(beads) || 0));
  const count = Math.min(Math.max(0, shown), icons.length);
  const beadIcons = icons
    .slice(0, count)
    .map((tone) => `<i class="bead ${tone}"></i>`)
    .join("");
  return (
    '<div class="reward-burst">' +
    `<span class="reward-beads" aria-hidden="true">${beadIcons}</span>` +
    `<span class="reward-amount">+${shown}</span>` +
    '<span class="reward-unit">拼点</span>' +
    "</div>"
  );
}

function trioLineHtml(reward) {
  const bonus = reward ? Number(reward.trio_bonus || 0) : 0;
  return bonus > 0
    ? `<p class="discrim-perfect-note">✨ 今日三练达成 · +${bonus} 拼点</p>`
    : "";
}

function trioProgressHtml() {
  const word = completedToday("word");
  const sentence = completedToday("sentence");
  const discrim = completedToday("discrim");
  const mark = (ok) => (ok ? "✓" : "○");
  const bonus = trioBonusCfg();
  if (comboAwardedToday()) {
    return `<p class="combo-progress">今日三练已完成 · +${bonus} 拼点已入账</p>`;
  }
  const missing = [word, sentence, discrim].filter((ok) => !ok).length;
  return (
    '<p class="combo-progress">今日三练：字词 ' +
    mark(word) +
    " · 句子 " +
    mark(sentence) +
    " · 辨音 " +
    mark(discrim) +
    (missing > 0 ? `（再完成 ${missing} 项 +${bonus} 拼点）` : `（完成结算后 +${bonus} 拼点）`) +
    "</p>"
  );
}

function escAttr(value) {
  return String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

function artworkById(id) {
  return state.artworks.find((a) => a.artwork_id === id) || null;
}

function currentEntry() {
  if (!state.home) return null;
  return state.home.entries.find((e) => e.id === state.entryId) || null;
}

function entryById(entryId) {
  if (!entryId || !state.home) return null;
  return state.home.entries.find((e) => e.id === entryId) || null;
}

function entryLabel(entryId) {
  const entry = entryById(entryId);
  return entry ? entry.short_label || entry.label : "训练";
}

function entryToneOf(entryId) {
  const entry = entryById(entryId);
  return entry && entry.tone ? entry.tone : "teal";
}

/* ---------- 音筛选（练哪些音） ---------- */

function filterGroupsOf(entry) {
  return entry && Array.isArray(entry.filter_groups) && entry.filter_groups.length
    ? entry.filter_groups
    : null;
}

function allFinalsOf(entry) {
  const groups = filterGroupsOf(entry);
  if (!groups) return [];
  const finals = [];
  groups.forEach((group) => {
    (group.finals || []).forEach((final) => {
      if (!finals.includes(final)) finals.push(final);
    });
  });
  return finals;
}

function selectedFinalsFor(entryId) {
  const entry = entryById(entryId);
  if (!entry) return [];
  const all = allFinalsOf(entry);
  const saved = (state.progress.entryFilters || {})[entryId];
  if (!Array.isArray(saved)) return all.slice();
  return all.filter((final) => saved.includes(final));
}

function saveSelectedFinals(entryId, finals) {
  state.progress.entryFilters = state.progress.entryFilters || {};
  state.progress.entryFilters[entryId] = finals.slice();
  saveProgress();
}

function entryScopeHint(entry) {
  const groups = filterGroupsOf(entry);
  if (!groups) return entry.pinyin_hint || entry.blurb || "";
  const selected = new Set(selectedFinalsFor(entry.id));
  const labels = groups
    .filter((group) => (group.finals || []).every((final) => selected.has(final)))
    .map((group) => group.label);
  return labels.slice(0, entry.id === "contrast" ? 2 : 3).join(" · ") +
    (labels.length > (entry.id === "contrast" ? 2 : 3) ? "…" : "") + " · 点选调整";
}

function openFilter() {
  const entry = currentEntry();
  if (!filterGroupsOf(entry)) return;
  state.filterDraft = selectedFinalsFor(entry.id).slice();
  renderFilterSheet(entry);
  els.filterOverlay.classList.remove("hidden");
}

function renderFilterSheet(entry) {
  const tone = toneOf(entry);
  els.filterBody.style.setProperty("--entry", tone.main);
  els.filterBody.style.setProperty("--entry-deep", tone.deep);
  els.filterBody.style.setProperty("--entry-soft", tone.soft);
  const groups = filterGroupsOf(entry);
  const selected = new Set(state.filterDraft || []);
  const all = allFinalsOf(entry);
  const allOn = selected.size === all.length;
  els.filterBody.innerHTML =
    '<div class="filter-head">' +
    '<button id="filter-close" class="detail-close" type="button" aria-label="关闭">×</button>' +
    '<div class="filter-head-text">' +
    `<h2>${entry.short_label || entry.label} · 练哪些音</h2>` +
    "<p>点一下切换，改动立即生效；至少保留一个</p>" +
    "</div>" +
    `<button id="filter-all" class="filter-link${allOn ? " on" : ""}" type="button">全选</button>` +
    "</div>" +
    `<div class="filter-grid${groups.length === 5 ? " cols-3" : ""}"></div>` +
    `<button id="filter-done" class="primary-btn tone-${entry.tone}" type="button">完成</button>`;
  const grid = els.filterBody.querySelector(".filter-grid");
  groups.forEach((group) => {
    const groupOn = (group.finals || []).every((final) => selected.has(final));
    const lastOne = groupOn && selected.size === (group.finals || []).length;
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "filter-chip" + (groupOn ? " on" : "");
    chip.setAttribute("aria-pressed", String(groupOn));
    chip.disabled = lastOne;
    chip.innerHTML =
      `<span class="filter-chip-final">${group.label}</span>` +
      `<span class="filter-chip-example">${group.example || ""}</span>`;
    chip.addEventListener("click", () => {
      const target = new Set(state.filterDraft || []);
      (group.finals || []).forEach((final) => {
        if (groupOn) target.delete(final);
        else target.add(final);
      });
      if (!target.size) return;
      state.filterDraft = [...target];
      saveSelectedFinals(entry.id, state.filterDraft);
      renderFilterSheet(entry);
      renderEntries();
      els.filterBody.querySelectorAll(".filter-chip")[groups.indexOf(group)]?.focus({ preventScroll: true });
    });
    grid.appendChild(chip);
  });
  els.filterBody.querySelector("#filter-close").addEventListener("click", closeFilter);
  els.filterBody.querySelector("#filter-all").addEventListener("click", () => {
    state.filterDraft = all.slice();
    saveSelectedFinals(entry.id, state.filterDraft);
    renderFilterSheet(entry);
    renderEntries();
    els.filterBody.querySelector("#filter-all")?.focus({ preventScroll: true });
  });
  els.filterBody.querySelector("#filter-done").addEventListener("click", closeFilter);
}

function closeFilter() {
  els.filterOverlay.classList.add("hidden");
  state.filterDraft = [];
}

function toneOf(entry) {
  return TONES[entry && entry.tone ? entry.tone : "teal"];
}

function rewardBase(minutes) {
  const cfg = state.achievement ? state.achievement.achievement_config : null;
  if (!cfg) return 0;
  return Number((cfg.tiers && cfg.tiers.word && cfg.tiers.word[String(minutes)]) || 0);
}

/* ---------- 句子 / 听辨的拼点明示（与服务端结算口径一致，档位制） ---------- */

function tierValue(activity, key) {
  const cfg = state.achievement ? state.achievement.achievement_config : null;
  if (!cfg || !cfg.tiers || !cfg.tiers[activity]) return 0;
  return Number(cfg.tiers[activity][String(key)] || 0);
}

// 句子整轮完成的拼点：按句数档位（10 句 = 600、15 句 = 900）
function sentenceBaseBeads(count) {
  return tierValue("sentence", count);
}

// 辨音整轮完成的拼点：按词数档位（50 = 300、100 = 600、150 = 900）
function discrimTierBase(size) {
  return tierValue("discrim", size);
}

function reviewRewardCfg() {
  const cfg = state.achievement ? state.achievement.achievement_config : null;
  return cfg ? Number(cfg.review_reward || 0) : 0;
}

function trioBonusCfg() {
  const cfg = state.achievement ? state.achievement.achievement_config : null;
  return cfg ? Number(cfg.trio_bonus || 0) : 0;
}

function completedArtworkIds() {
  return Object.entries(state.progress.artworks)
    .filter(([, record]) => record.completedAt)
    .map(([id]) => id);
}

// 系列内全部完成（用于 6/6 庆祝）
function seriesCompletedCount() {
  const done = new Set(completedArtworkIds());
  return state.artworks.filter((art) => art.series_id && done.has(art.artwork_id)).length;
}

function seriesTotalCount() {
  return state.artworks.filter((art) => art.series_id).length;
}

/* ---------- 拼豆作品 SVG（100×100 网格：grid 为 null/#HEX，fill_order 驱动） ---------- */

function beadArtworkSvg(art, filledCount, opts) {
  const options = opts || {};
  const animate = Boolean(options.animate);
  const from = Number(options.from || 0);
  const light = Boolean(options.light);
  const cell = 10;
  const width = Number(art.width || art.canvas_width || 0) * cell;
  const height = Number(art.height || art.canvas_height || 0) * cell;
  const order = Array.isArray(art.fill_order) ? art.fill_order : [];
  const big = Number(art.active_bead_count || 0) > 600;
  const step = big ? 12 : 70;          // 大作品每颗更快
  const cap = big ? 1600 : Infinity;   // 大作品动画总时长上限（避免分钟级）
  let out =
    `<svg class="bead-art${animate ? " anim" : ""} ${options.className || ""}" ` +
    `viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" ` +
    `role="img" aria-label="${escAttr(art.name)}">`;
  order.forEach((position, index) => {
    const row = Number(position[0]);
    const col = Number(position[1]);
    const color = art.grid && art.grid[row] ? art.grid[row][col] : null;
    if (!color) return; // 防御：fill_order 只含非空格
    const on = index < filledCount;
    const delay = animate ? Math.min(cap, Math.max(0, (index - from) * step)) : 0;
    out +=
      `<rect class="bead${on ? " on" : ""}" ` +
      `x="${(col * cell + 1.5).toFixed(2)}" y="${(row * cell + 1.5).toFixed(2)}" ` +
      `width="${(cell - 3).toFixed(2)}" height="${(cell - 3).toFixed(2)}" ` +
      `rx="${(cell * 0.32).toFixed(2)}" fill="${color}" ` +
      `stroke="rgba(38,34,27,.12)" stroke-width="0.5" style="--d:${delay}ms"/>`;
    if (!light && on) {
      out +=
        `<ellipse class="glint" cx="${(col * cell + cell * 0.3).toFixed(2)}" ` +
        `cy="${(row * cell + cell * 0.28).toFixed(2)}" rx="${(cell * 0.24).toFixed(2)}" ` +
        `ry="${(cell * 0.18).toFixed(2)}" fill="rgba(255,255,255,.68)" style="--d:${delay}ms"/>`;
      out +=
        `<circle class="hole" cx="${(col * cell + cell / 2).toFixed(2)}" ` +
        `cy="${(row * cell + cell / 2).toFixed(2)}" r="${(cell * 0.22).toFixed(2)}" ` +
        `fill="rgba(45,42,50,.22)"/>`;
      out +=
        `<circle class="hole-core" cx="${(col * cell + cell / 2).toFixed(2)}" ` +
        `cy="${(row * cell + cell / 2).toFixed(2)}" r="${(cell * 0.13).toFixed(2)}" ` +
        `fill="rgba(45,42,50,.42)"/>`;
      out +=
        `<circle class="shade" cx="${(col * cell + cell * 0.74).toFixed(2)}" ` +
        `cy="${(row * cell + cell * 0.76).toFixed(2)}" r="${(cell * 0.2).toFixed(2)}" ` +
        `fill="rgba(0,0,0,.1)"/>`;
    }
  });
  out += "</svg>";
  return out;
}

/* ---------- 视图切换 ---------- */

function setView(name) {
  sfx.stop();
  cancelIronCeremony();
  stopPlacement();
  if (document.body.dataset.view === "calibration" && name !== "calibration") stopCalVideos();
  document.body.dataset.view = name;
  window.scrollTo({ top: 0, behavior: "instant" });
  ["home", "training", "complete", "calibration", "wall", "history", "sentence", "discrim"].forEach((view) => {
    els["view" + view[0].toUpperCase() + view.slice(1)].classList.add("hidden");
  });
  els["view" + name[0].toUpperCase() + name.slice(1)].classList.remove("hidden");
}

let statusFade = null;
function setStatus(text) {
  els.status.textContent = text;
  els.status.classList.add("show");
  clearTimeout(statusFade);
  statusFade = setTimeout(() => els.status.classList.remove("show"), 1500);
}

function setMode(mode) {
  state.mode = mode;
  document.getElementById('reading-done-word').disabled = mode !== 'waiting_follow';
  const interactive =
    mode === "playing_reference" || mode === "waiting_follow" || mode === "paused";
  els.pauseBtn.disabled = !interactive;
  els.replayBtn.disabled = !(interactive || mode === "error");
  if (mode !== "paused") {
    els.pauseIcon.innerHTML = uiIcon("pause");
    els.pauseLabel.textContent = "暂停";
    els.pauseBtn.setAttribute("aria-label", "暂停");
  }
}

function renderTimer() {
  const totalSec = Math.max(0, Math.round(state.timerRemainingMs / 1000));
  const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  els.timer.textContent = `${mm}:${ss}`;
}

function startTick() {
  if (state.tickTimer) return;
  state.lastTick = performance.now();
  state.tickTimer = setInterval(tick, 200);
}

function stopTick() {
  if (state.tickTimer) {
    clearInterval(state.tickTimer);
    state.tickTimer = null;
  }
}

function tick() {
  const now = performance.now();
  state.timerRemainingMs = Math.max(0, state.timerRemainingMs - (now - state.lastTick));
  state.lastTick = now;
  renderTimer();
}

function stopAudio(player) {
  const audio = player || els.player;
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
}

function currentItem() {
  if (!state.session || !state.session.items) return null;
  return state.session.items[state.index] || null;
}

/* ---------- 首页 ---------- */

function renderEntries() {
  els.entryList.textContent = "";
  (state.home.entries || []).forEach((entry) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "entry-btn tone-" + entry.tone;
    const isSelected = entry.id === state.entryId;
    btn.setAttribute("aria-pressed", String(isSelected));
    btn.innerHTML =
      uiEntryArt(entry.tone) +
      '<span class="entry-main">' +
      `<span class="entry-name">${entry.label}</span>` +
      `<span class="entry-hint${isSelected ? " active" : ""}">${entryScopeHint(entry)}</span>` +
      "</span>" +
      `<span class="entry-arrow" aria-hidden="true">${uiIcon(isSelected ? 'check' : 'arrow')}</span>`;
    btn.addEventListener("click", () => {
      state.entryId = entry.id;
      state.profileId = entry.profile_id;
      state.profileLabel = entry.label;
      renderEntries();
      updateRewardHint();
      updateStartBtn();
      els.entryList.querySelector('[aria-pressed="true"]')?.focus({ preventScroll: true });
      openFilter();
    });
    els.entryList.appendChild(btn);
  });
}

/* ---------- 首页三 Tab（字词 / 句子 / 辨音） ---------- */

function setTab(name) {
  state.activeTab = name;
  els.viewHome.dataset.tab = name;
  ["words", "sentence", "discrim"].forEach((tab) => {
    const pane = els["pane" + tab[0].toUpperCase() + tab.slice(1)];
    const btn = els["tab" + tab[0].toUpperCase() + tab.slice(1)];
    const active = tab === name;
    pane.classList.toggle("active", active);
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-current", active ? "page" : "false");
  });
  if (name === "sentence") renderSentenceFilterOptions();
}

/* ---------- 辨音 Tab（主词库 + 趁热巩固 + 错题复习，双卡片） ---------- */

function discrimChipHtml(tone = "violet") {
  return uiEntryArt(tone);
}

function discrimInfo() {
  return state.discrimInfo || {
    library: { round: 1, cursor: 0, total: 0 },
    review: { due_today: 0, pending: 0, intervals: [1, 3, 7] },
  };
}

// 主词库一次练习的拼点明示：按词数档位（50/100/150 = 300/600/900，无轮次递减）
function discrimSessionBaseBeads() {
  return discrimTierBase(state.discrimPracticeSize);
}

const REVIEW_AWARD_KEY = "pth-review-award-v1";

function reviewAwardedToday() {
  return localStorage.getItem(REVIEW_AWARD_KEY) === todayKey();
}

function markReviewAwarded() {
  try {
    localStorage.setItem(REVIEW_AWARD_KEY, todayKey());
  } catch {
    /* ignore */
  }
}

async function refreshDiscrimState() {
  try {
    state.discrimInfo = await fetchJson("/api/discrim/state");
  } catch {
    /* 拉不到就保留旧值 */
  }
  renderDiscrimPane();
}

function renderDiscrimSizes() {
  const info = discrimInfo();
  const sizes = (info.practice_sizes && info.practice_sizes.length)
    ? info.practice_sizes
    : [50, 100, 150];
  if (!sizes.includes(state.discrimPracticeSize)) {
    state.discrimPracticeSize = Number(info.default_practice_size || sizes[0]);
  }
  els.discrimSizeOptions.textContent = "";
  sizes.forEach((size) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "duration-btn";
    btn.textContent = `${size} 词`;
    btn.setAttribute("aria-pressed", String(size === state.discrimPracticeSize));
    btn.addEventListener("click", () => {
      state.discrimPracticeSize = size;
      renderDiscrimSizes();
    });
    els.discrimSizeOptions.appendChild(btn);
  });
  els.discrimSizeHint.textContent =
    `${state.discrimPracticeSize} 词 · 完成 +${discrimSessionBaseBeads()} 拼点`;
  els.discrimStartLabel.textContent = `开始 · 词库练习 ${state.discrimPracticeSize} 词`;
}

function renderDiscrimPane() {
  const info = discrimInfo();
  const lib = info.library || { round: 1, cursor: 0, total: 0 };
  const review = info.review || { due_today: 0, pending: 0 };
  const due = Number(review.due_today || 0);

  // 卡片 1：词库练习（持续覆盖主线）
  els.discrimCard.textContent = "";
  const card = document.createElement("div");
  card.className = "entry-btn tone-violet";
  card.innerHTML =
    discrimChipHtml() +
    '<span class="entry-main">' +
    '<span class="entry-name">词库练习</span>' +
    `<span class="entry-hint">本轮已练 ${lib.cursor} 词 · 接着上次继续</span>` +
    "</span>";
  els.discrimCard.appendChild(card);
  renderDiscrimSizes();

  // 卡片 2：错题复习（间隔重考，今日到期）
  els.discrimReviewCard.textContent = "";
  const reviewCard = document.createElement("div");
  reviewCard.className = "entry-btn tone-orange" + (due ? "" : " wb-empty");
  reviewCard.innerHTML =
    discrimChipHtml("orange") +
    '<span class="entry-main">' +
    '<span class="entry-name">错题复习</span>' +
    `<span class="entry-hint">${due
      ? `今日待复习 ${due} 个 · 完成今日复习 +${reviewRewardCfg()} 拼点`
      : "今日暂无待复习"}</span>` +
    "</span>";
  els.discrimReviewCard.appendChild(reviewCard);
  els.discrimReviewBtn.disabled = due === 0;
  els.discrimReviewLabel.textContent = due
    ? `开始复习 · ${due} 个`
    : "今日暂无待复习";
}

/* 句子 Tab：项目选择（三档）+ 练多久（句数） */

async function renderSentenceFilterOptions() {
  // 优先拉最新计数，缓存首载异常（瞬态失败）时不至于卡死入口
  let info = (state.home && state.home.sentence) || {};
  try {
    info = await fetchJson("/api/sentence/home");
  } catch {
    /* 拉不到就用 home 缓存 */
  }
  if (!info || !info.available) {
    els.sentenceFilterOptions.innerHTML =
      '<p class="pane-empty">句子库准备中，稍后再试</p>';
    return;
  }
  const sourceHint = document.querySelector("#pane-sentence > .section-head .section-hint");
  if (sourceHint) sourceHint.textContent = info.source_counts?.news ? "散文与新闻 · 整句跟读" : "整句跟读 · 三档可选";
  els.sentenceFilterOptions.textContent = "";
  SENTENCE_FILTERS.forEach((f) => {
    const selected = state.sentenceFilter === f.id;
    const btn = document.createElement("button");
    btn.type = "button";
    const cardTone = { front: "teal", back: "orange", mixed: "violet" }[f.id];
    btn.className = "entry-btn tone-" + cardTone;
    btn.setAttribute("aria-pressed", String(selected));
    btn.innerHTML =
      uiEntryArt(cardTone) +
      '<span class="entry-main">' +
      `<span class="entry-name">${f.label}</span>` +
      `<span class="entry-hint">${f.desc}</span>` +
      "</span>" +
      `<span class="entry-arrow" aria-hidden="true">${uiIcon(selected ? 'check' : 'arrow')}</span>`;
    btn.addEventListener("click", () => {
      state.sentenceFilter = f.id;
      renderSentenceFilterOptions();
      updateSentenceStart();
    });
    els.sentenceFilterOptions.appendChild(btn);
  });
}

const SENTENCE_DURATIONS = [
  { count: 10, hint: "10 句 · 约 4 分钟" },
  { count: 15, hint: "15 句 · 约 6 分钟" },
];

function renderSentenceDurations() {
  els.sentenceDurationOptions.textContent = "";
  SENTENCE_DURATIONS.forEach((option) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "duration-btn";
    btn.textContent = `${option.count} 句`;
    btn.setAttribute("aria-pressed", String(option.count === state.sentenceCount));
    btn.addEventListener("click", () => {
      state.sentenceCount = option.count;
      renderSentenceDurations();
      updateSentenceStart();
    });
    els.sentenceDurationOptions.appendChild(btn);
  });
  updateSentenceStart();
}

function updateSentenceStart() {
  const option = SENTENCE_DURATIONS.find((d) => d.count === state.sentenceCount)
    || SENTENCE_DURATIONS[1];
  els.sentenceDurationHint.textContent =
    `${option.count} 句 · 两遍跟读 · +${sentenceBaseBeads(state.sentenceCount)} 拼点`;
  const filter = SENTENCE_FILTERS.find((f) => f.id === state.sentenceFilter) || SENTENCE_FILTERS[0];
  els.sentenceStartLabel.textContent = `开始 · ${filter.label} ${state.sentenceCount} 句`;
}

function renderDurations() {
  els.durationOptions.textContent = "";
  (state.home.durations || [5, 10]).forEach((minutes) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "duration-btn";
    btn.textContent = `${minutes} 分钟`;
    btn.setAttribute("aria-pressed", String(minutes === state.duration));
    btn.addEventListener("click", () => {
      state.duration = minutes;
      renderDurations();
      updateRewardHint();
      updateStartBtn();
    });
    els.durationOptions.appendChild(btn);
  });
}

function updateRewardHint() {
  els.rewardHint.textContent = `${state.duration} 分钟 · +${rewardBase(state.duration)} 拼点`;
}

function updateStartBtn() {
  const entry = currentEntry();
  const enabled = Boolean(entry);
  els.startBtn.disabled = !enabled;
  els.startBtn.classList.remove("tone-teal", "tone-orange", "tone-violet");
  if (entry) {
    els.startBtn.classList.add("tone-" + entry.tone);
    els.startLabel.textContent = `开始 · ${entry.short_label} ${state.duration} 分钟`;
  } else {
    els.startLabel.textContent = "开始训练";
  }
}

function computeStats() {
  const key = todayKey();
  let today = 0;
  let total = 0;
  const trainedDays = new Set();
  (state.progress.sessions || []).forEach((session) => {
    total += Number(session.actualMinutes || 0);
    if (session.dayKey === key) today += Number(session.actualMinutes || 0);
    if (isValidSession(session)) trainedDays.add(session.dayKey);
  });
  return { today, total, trainedDays: trainedDays.size };
}

function renderStats() {
  const stats = computeStats();
  els.statToday.textContent = String(Math.round(stats.today));
  els.statTotal.textContent = String(stats.trainedDays);
  const streak = computeStreak();
  els.statStreak.textContent = String(streak.days);
  renderTrioBar();
}

/* ---------- 首页「今日三练」全局状态条 ---------- */

const TRIO_ITEMS = [
  { key: "word", label: "字词", tone: "teal" },
  { key: "sentence", label: "句子", tone: "orange" },
  { key: "discrim", label: "辨音", tone: "violet" },
];

// 与「连续训练」分家：三练 = 三大类各完整完成一次（不计提前退出），齐了发 trio_bonus。
// 连续训练只看「当天是否有 ≥20% 的有效训练」，由 computeStreak 单独推导，互不代表对方。
// UI 纪律：只展示三项状态本身——不放假奖励说明、不放「再完成 X」提示（完成瞬间的反馈在结算页）；
// 全部完成后整条淡出，不再抢注意力。
function renderTrioBar() {
  if (!els.trioBar) return;
  if (comboAwardedToday()) {
    els.trioBar.classList.add("done");
    els.trioBar.innerHTML = '<span class="trio-title">今日三练完成 ✓</span>';
    return;
  }
  els.trioBar.classList.remove("done");
  const itemsHtml = TRIO_ITEMS.map((item) => {
    const ok = completedToday(item.key);
    return (
      `<span class="trio-item tone-${item.tone}${ok ? " done" : ""}">` +
      '<i class="trio-dot" aria-hidden="true"></i>' +
      `${item.label}</span>`
    );
  }).join("");
  els.trioBar.innerHTML = '<span class="trio-title">今日三练</span>' + itemsHtml;
}

/* ---------- 句子练习（第四入口，与生成器解耦） ---------- */

async function openSentenceFilter() {
  // 优先拉最新计数，缓存首载异常（瞬态失败）时不至于卡死入口
  let info = (state.home && state.home.sentence) || {};
  try {
    info = await fetchJson("/api/sentence/home");
  } catch {
    /* 拉不到就用 home 缓存 */
  }
  if (!info || !info.available) {
    els.readyHint.hidden = false;
    els.readyHint.textContent = "句子库准备中，稍后再试";
    setTimeout(() => {
      els.readyHint.hidden = true;
    }, 2500);
    return;
  }
  renderSentenceFilter(info);
  els.sentenceFilterOverlay.classList.remove("hidden");
}

function renderSentenceFilter(info) {
  if (!info || !info.available) return;
  const counts = info.filter_counts || {};
  els.sentenceFilterBody.innerHTML =
    '<div class="filter-head"><div class="filter-head-text">' +
    "<h2>练哪种句子</h2>" +
    "<p>每句听读两遍 · 从看拼音读到自己读</p>" +
    "</div>" +
    '<button id="sentence-filter-close" class="detail-close icon-btn" type="button" aria-label="关闭">×</button>' +
    "</div>" +
    SENTENCE_FILTERS.map(
      (f) =>
        `<button class="sentence-filter-row" data-filter="${f.id}" type="button">` +
        '<span class="sentence-filter-main">' +
        `<strong>${f.label}</strong>` +
        `<small>${f.desc}</small>` +
        "</span>" +
        `<span class="sentence-filter-count" aria-hidden="true">${uiIcon("arrow")}</span>` +
        "</button>"
    ).join("") +
    '<button id="sentence-filter-cancel" class="ghost-btn sentence-filter-cancel" type="button">取消</button>';
  els.sentenceFilterBody
    .querySelectorAll(".sentence-filter-row[data-filter]")
    .forEach((row) => {
      row.addEventListener("click", () => {
        const filterId = row.getAttribute("data-filter");
        closeSentenceFilter();
        startSentenceSession(filterId, SENTENCE_COUNT_DEFAULT);
      });
    });
  els.sentenceFilterBody
    .querySelector("#sentence-filter-close")
    .addEventListener("click", closeSentenceFilter);
  els.sentenceFilterBody
    .querySelector("#sentence-filter-cancel")
    .addEventListener("click", closeSentenceFilter);
}

function closeSentenceFilter() {
  els.sentenceFilterOverlay.classList.add("hidden");
}

function currentSentenceItem() {
  if (!state.sentenceSession || !state.sentenceSession.items) return null;
  return state.sentenceSession.items[state.sentenceIndex] || null;
}

function setSentenceStatus(text) {
  els.sentenceStatus.textContent = text;
  els.sentenceStatus.classList.add("show");
  clearTimeout(statusFade);
  statusFade = setTimeout(() => els.sentenceStatus.classList.remove("show"), 1500);
}

function setSentenceMode(mode) {
  state.sentenceMode = mode;
  document.getElementById('reading-done-sentence').disabled = mode !== 'following';
  const interactive = mode === "previewing" || mode === "playing" || mode === "following" || mode === "paused";
  els.sentencePauseBtn.disabled = !interactive;
  els.sentenceReplayBtn.disabled = !(interactive || mode === "error");
  if (mode !== "paused") {
    els.sentencePauseIcon.innerHTML = uiIcon("pause");
    els.sentencePauseLabel.textContent = "暂停";
    els.sentencePauseBtn.setAttribute("aria-label", "暂停");
  }
}

function startSentenceTick() {
  if (state.sentenceTickTimer) return;
  state.sentenceLastTick = performance.now();
  state.sentenceTickTimer = setInterval(sentenceTick, 200);
}

function stopSentenceTick() {
  if (state.sentenceTickTimer) {
    clearInterval(state.sentenceTickTimer);
    state.sentenceTickTimer = null;
  }
}

function sentenceTick() {
  const now = performance.now();
  state.sentenceElapsedMs += now - state.sentenceLastTick;
  state.sentenceLastTick = now;
}

async function startSentenceSession(filterId, count, review = false) {
  if (state.sentenceMode === "preparing") return;
  state.sentenceMode = "preparing"; els.sentenceStartBtn.disabled = true;
  await reading.prepare();
  els.sentenceStartBtn.disabled = false;
  sfx.unlock();
  stopSentenceTick();
  clearTimeout(state.sentenceFollowTimeout);
  state.sentenceFilter = filterId || "front";
  state.sentenceSession = null;
  state.sentenceIndex = 0;
  state.sentenceCompleted = 0;
  state.sentenceReplayCount = 0;
  state.sentencePauseCount = 0;
  state.sentenceElapsedMs = 0;
  stopAudio(els.sentencePlayer);
  els.viewSentence.style.setProperty("--session-tone", TONES.green.main);
  els.sentenceFilterTag.textContent = SENTENCE_FILTER_LABELS[state.sentenceFilter] || "前鼻为主";
  setView("sentence");
  renderSentenceProgress();
  setSentenceMode("loading");
  setSentenceStatus("正在准备…");
  els.sentenceText.textContent = "";
  els.sentenceSource.textContent = "";
  try {
    const session = await fetchJson("/api/sentence/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        count: count || SENTENCE_COUNT_DEFAULT,
        filter: state.sentenceFilter,
        review,
      }),
    });
    state.sentenceSession = session;
    if(review)els.sentenceFilterTag.textContent='鼻音专项复练';
    sfx.play("training.start");
    state.sentenceStartTime = new Date().toISOString();
    startSentenceTick();
    playSentence(0);
  } catch (err) {
    setSentenceMode("error");
    setSentenceStatus(`生成失败：${err.message}`);
  }
}

function renderSentenceProgress() {
  const total = state.sentenceSession ? state.sentenceSession.items.length : 0;
  els.sentenceProgressText.textContent = total
    ? `${Math.min(state.sentenceIndex + 1, total)} / ${total}`
    : "- / -";
  const pct = total > 0 ? Math.min(100, (state.sentenceIndex / total) * 100) : 0;
  els.sentenceProgressFill.style.width = `${pct}%`;
  els.sentenceProgressBead.style.left = `${pct}%`;
}

function renderSentenceItem(item) {
  els.sentenceSource.textContent = `${item.genre === "news" ? "新闻 · " : ""}选自《${item.article_title}》`;
  // 整句每个字都带悬浮小字拼音（白字不加色，均衡；前鼻青 / 后鼻橙标色），
  // 标点直接排入句流，自然折行
  const wrap = document.createElement("p");
  wrap.className = "sentence-chars";
  (item.units || []).forEach((u) => {
    if (!u.label) {
      wrap.appendChild(document.createTextNode(u.ch));
      return;
    }
    const span = document.createElement("span");
    span.className =
      "sc-inline" +
      (u.label === "F" ? " nasal-front" : u.label === "B" ? " nasal-back" : " sc-plain");
    const py = document.createElement("i");
    py.className = "py";
    py.textContent = u.py || "";
    const ch = document.createElement("span");
    ch.className = "ch";
    ch.textContent = u.ch;
    span.appendChild(py);
    span.appendChild(ch);
    wrap.appendChild(span);
  });
  els.sentenceText.textContent = "";
  els.sentenceText.appendChild(wrap);
  applySentencePinyin();
}

function applySentencePinyin() {
  const on = state.sentencePinyin;
  els.sentenceText.classList.toggle("no-pinyin", !on);
  // 第 2 遍：统一颜色，前后鼻字只加粗不标色
  els.sentenceText.classList.toggle("pass2", state.sentencePass === 2);
  els.sentencePinyinToggle.textContent = on ? "拼音：开" : "拼音：关";
}

function toggleSentencePinyin() {
  state.sentencePinyin = !state.sentencePinyin;
  try {
    localStorage.setItem(SENTENCE_PINYIN_KEY, String(state.sentencePinyin));
  } catch {
    /* ignore */
  }
  applySentencePinyin();
}

function playSentence(index) {
  reading.cancel();
  const session = state.sentenceSession;
  if (!session || !session.items || index >= session.items.length) return;
  state.sentenceIndex = index;
  const item = session.items[index];
  // 两遍对比读：第 1 遍拼音开，第 2 遍拼音关（前后鼻颜色两遍都保留）
  state.sentencePass = 1;
  state.sentenceReadValid = false;
  state.sentencePinyin = true;
  renderSentenceItem(item);
  renderSentenceProgress();
  updateDebug();
  setSentenceMode("previewing");
  setSentenceStatus("先看一下句子，再听示范");
  els.sentencePlayer.src = window.demoVoice.url(item.clip_url);
  els.sentencePlayer.preservesPitch = true;
  els.sentencePlayer.playbackRate = sentenceSpeed;
  clearTimeout(state.sentenceFollowTimeout);
  state.sentenceFollowTimeout=setTimeout(()=>{
    if(state.sentenceMode!=='previewing'||currentSentenceItem()!==item)return;
    setSentenceMode('playing');setSentenceStatus('正在播放示范音');
    playSentenceAudio();
  },1600);
}

function playSentenceAudio() {
  const item=currentSentenceItem();
  els.sentencePlayer.play().catch(()=>{
    if(currentSentenceItem()!==item || state.sentenceMode!=='playing')return;
    setSentenceMode('error');setSentenceStatus('示范音暂时无法播放，请点重播');
  });
}

function enterSentenceFollow() {
  const item = currentSentenceItem();
  if (!item) return;
  // Independent learner time: generous window at the selected demo speed.
  // "读完了" ends early; never exceed the recording API's 59s local cap.
  const followMs = Math.min(59000, Math.max(7000, Number(item.clip_duration || 3) / sentenceSpeed * 1700 + 2000));
  setSentenceMode("following");
  state.sentencePinyin = state.sentencePass === 1;
  applySentencePinyin();
  setSentenceStatus("请跟读");
  state.uiSentenceFollowTotalMs = followMs;
  state.sentenceFollowDeadline = performance.now() + followMs;
  clearTimeout(state.sentenceFollowTimeout);
  reading.start("sentence");
  state.sentenceFollowTimeout = setTimeout(sentenceFollowDone, followMs);
}

async function sentenceFollowDone() {
  if(state.sentenceMode!=='following')return;
  clearTimeout(state.sentenceFollowTimeout);
  const id = currentSentenceItem()?.sentence_id;
  setSentenceMode("finishing"); stopSentenceTick();
  const result = await reading.grade("sentence", id, replaySentence, state.sentencePass);
  if (!result.advance || currentSentenceItem()?.sentence_id !== id || state.sentenceMode !== "finishing") return;
  state.sentenceReadValid = Boolean(state.sentenceReadValid || result.complete);
  startSentenceTick();
  if (state.sentencePass === 1) {
    // 第 1 遍读完 → 自动关拼音，再放一遍示范音读第 2 遍
    state.sentencePass = 2;
    state.sentencePinyin = false;
    applySentencePinyin();
    setSentenceMode("playing");
    setSentenceStatus("正在播放示范音");
    els.sentencePlayer.currentTime = 0;
    playSentenceAudio();
    return;  // 'ended' 事件会进入第 2 遍跟读
  }
  state.sentencePass = 1;
  state.sentenceCompleted += state.sentenceReadValid ? 1 : 0;
  state.sentenceReadValid = false;
  if (
    state.sentenceSession &&
    state.sentenceIndex + 1 < state.sentenceSession.items.length
  ) {
    playSentence(state.sentenceIndex + 1);
  } else {
    finishSentenceSession(false);
  }
}

function skipSentence() {
  reading.cancel();
  if (!state.sentenceSession || !state.sentenceSession.items) return;
  clearTimeout(state.sentenceFollowTimeout);
  state.sentencePass = 1;
  state.sentencePinyin = true;
  applySentencePinyin();
  state.sentenceReadValid = false;
  if (state.sentenceIndex + 1 < state.sentenceSession.items.length) {
    playSentence(state.sentenceIndex + 1);
  } else {
    finishSentenceSession(false);
  }
}

function toggleSentencePause() {
  sfx.stop();
  if (state.sentenceMode === "paused") {
    resumeSentence();
    return;
  }
  if (!["previewing", "playing", "following"].includes(state.sentenceMode)) return;
  reading.cancel();
  state.sentencePauseCount += 1;
  state.sentenceResumeFrom = state.sentenceMode;
  clearTimeout(state.sentenceFollowTimeout);
  stopSentenceTick();
  if (state.sentenceMode === "playing") {
    els.sentencePlayer.pause();
  } else {
    state.sentenceFollowRemainingMs = Math.max(
      0,
      state.sentenceFollowDeadline - performance.now()
    );
  }
  setSentenceMode("paused");
  setSentenceStatus("已暂停");
  els.sentencePauseIcon.innerHTML = uiIcon("play");
  els.sentencePauseLabel.textContent = "继续";
  els.sentencePauseBtn.setAttribute("aria-label", "继续");
}

function resumeSentence() {
  if (state.sentenceMode !== "paused") return;
  const from = state.sentenceResumeFrom;
  state.sentenceResumeFrom = null;
  startSentenceTick();
  if (from === "playing" || from === "previewing") {
    setSentenceMode("playing");
    setSentenceStatus("正在播放示范音");
    playSentenceAudio();
  } else {
    enterSentenceFollow();
  }
}

function replaySentence() {
  reading.cancel();
  if (!state.sentenceSession && state.sentenceMode === "error") {
    startSentenceSession(state.sentenceFilter, state.sentenceCount);
    return;
  }
  if (
    !state.sentenceSession ||
    state.sentenceMode === "loading" ||
    state.sentenceMode === "completed"
  ) {
    return;
  }
  state.sentenceReplayCount += 1;
  clearTimeout(state.sentenceFollowTimeout);
  startSentenceTick();
  setSentenceMode("playing");
  setSentenceStatus("正在播放示范音");
  els.sentencePlayer.currentTime = 0;
  playSentenceAudio();
}

async function finishSentenceSession(exitEarly) {
  reading.close();
  clearTimeout(state.sentenceFollowTimeout);
  stopSentenceTick();
  stopAudio(els.sentencePlayer);
  const session = state.sentenceSession;
  const elapsedSec = Math.round(state.sentenceElapsedMs / 1000);
  const minutes = Math.max(0.1, Math.round(state.sentenceElapsedMs / 6000) / 10);
  setSentenceMode("completed");
  const event = {
    session_id: session ? session.session_id : `sent-local-${Date.now()}`,
    filter: state.sentenceFilter,
    start_time: state.sentenceStartTime || new Date().toISOString(),
    end_time: new Date().toISOString(),
    sentence_count: session ? session.items.length : 0,
    completed_sentence_count: state.sentenceCompleted,
    exit_early: exitEarly,
    replay_count: state.sentenceReplayCount,
    pause_count: state.sentencePauseCount,
    actual_duration_sec: elapsedSec,
  };

  // 统一拼豆结算：句子档位制（10 句 = 600、15 句 = 900），≥20% 按比例
  const totalCount = session ? session.items.length : 0;
  const completed = Math.min(state.sentenceCompleted, totalCount);
  const newStreakDays = streakAfterToday();
  const reward = await settleActivity({
    activity: "sentence",
    sentence_count: totalCount,
    completed_sentence_count: completed,
    streak_days: newStreakDays,
    word_completed_today: completedToday("word"),
    sentence_completed_today: completedToday("sentence"),
    discrim_completed_today: completedToday("discrim"),
    trio_awarded_today: comboAwardedToday(),
  });
  const rewardResult = applyReward(reward, {
    exitEarly,
    actualSec: elapsedSec,
    streakDays: newStreakDays,
    streakBonus: reward ? Number(reward.streak_bonus || 0) : 0,
    type: "sentence",
    sessionId: session ? session.session_id : null,
    sentenceCount: completed,
    sentenceTotal: totalCount,
  });
  // 事件补拼点字段（数值复盘用）
  event.beads_awarded = reward ? Number(reward.total_beads || 0) : 0;
  event.trio_bonus = reward ? Number(reward.trio_bonus || 0) : 0;
  fetch("/api/sentence/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(event),
  }).catch(() => {});
  renderSentenceComplete({
    count: state.sentenceCompleted,
    minutes,
    exitEarly,
    reward,
    rewardResult,
  });
  sfx.settlement(rewardResult, `sentence:${event.session_id}`);
}

function renderSentenceComplete(result) {
  els.viewComplete.dataset.activity = "sentence";
  const tone = TONES.green;
  els.viewComplete.style.setProperty("--entry", tone.main);
  els.viewComplete.style.setProperty("--entry-deep", tone.deep);
  els.viewComplete.style.setProperty("--entry-soft", tone.soft);
  const reward = result.reward;
  const beads = reward ? Number(reward.total_beads || 0) : 0;
  const rewardHtml = beads > 0 ? rewardBurstHtml(beads) : "";
  const noRewardHtml =
    reward && reward.eligible === false
      ? '<p class="discrim-score-note">完成不足 20%，本次没有拼点</p>'
      : "";
  els.completeBody.innerHTML =
    '<div class="complete-top">' +
    '<div class="complete-mark">✓</div>' +
    `<h1>${result.exitEarly ? "本次结束" : "句子练完啦"}</h1>` +
    `<p class="complete-sub">句子练习 · ${SENTENCE_FILTER_LABELS[state.sentenceFilter] || "全部"}</p>` +
    "</div>" +
    '<div class="sentence-summary">' +
    `<span class="sentence-summary-num">${result.count}</span>` +
    '<span class="sentence-summary-unit">句</span>' +
    '<span class="sentence-summary-sep">·</span>' +
    `<span class="sentence-summary-num">${result.minutes}</span>` +
    '<span class="sentence-summary-unit">分钟</span>' +
    "</div>" +
    rewardHtml +
    noRewardHtml +
    trioLineHtml(reward) +
    trioProgressHtml() +
    pendingReadyHtml(result.rewardResult) +
    '<div class="complete-actions">' +
    '<button id="sentence-again-btn" class="primary-btn tone-green" type="button">再来一组</button>' +
    '<button id="sentence-home-btn" class="ghost-btn" type="button">返回首页</button>' +
    "</div>";
  els.completeBody.querySelector("#sentence-again-btn").addEventListener("click", () => {
    startSentenceSession(state.sentenceFilter, state.sentenceCount);
  });
  els.completeBody.querySelector("#sentence-home-btn").addEventListener("click", resetToHome);
  setView("complete");
  reading.mountSummary(els.completeBody,()=>startSentenceSession('mixed',10,true));
}

/* ---------- 听辨练习（前后鼻音逐字判断，无示范音） ---------- */

function currentDiscrimItem() {
  if (state.discrimKind === "library") {
    if (!state.discrimSession || !state.discrimSession.items) return null;
    return state.discrimSession.items[state.discrimIndex] || null;
  }
  return (state.discrimQueue && state.discrimQueue[state.discrimIndex]) || null;
}

function setDiscrimStatus(text) {
  els.discrimStatus.textContent = text;
  els.discrimStatus.classList.add("show");
  clearTimeout(statusFade);
  statusFade = setTimeout(() => els.discrimStatus.classList.remove("show"), 1500);
}

function startDiscrimTick() {
  if (state.discrimTickTimer) return;
  state.discrimLastTick = performance.now();
  state.discrimTickTimer = setInterval(discrimTick, 200);
}

function stopDiscrimTick() {
  if (state.discrimTickTimer) {
    clearInterval(state.discrimTickTimer);
    state.discrimTickTimer = null;
  }
}

function discrimTick() {
  const now = performance.now();
  state.discrimElapsedMs += now - state.discrimLastTick;
  state.discrimLastTick = now;
}

function resetDiscrimSessionStats() {
  state.discrimSession = null;
  state.discrimQueue = null;
  state.discrimQueueTotal = 0;
  state.discrimIndex = 0;
  state.discrimPointIndex = 0;
  state.discrimAnswers = [];
  state.discrimWordResults = [];
  state.discrimLibraryCompleted = 0;
  state.discrimConsecutive = 0;
  state.discrimConsecutivePeak = 0;
  state.discrimPerfectWords = 0;
  state.discrimCorrectPoints = 0;
  state.discrimPointCount = 0;
  state.discrimPlannedPoints = 0;
  state.discrimAcc = {
    correct: 0,
    points: 0,
    perfectWords: 0,
    words: 0,
    peak: 0,
    rewardSum: 0,
    perfectBonus: 0,
    comboBonus: 0,
    streakBonus: 0,
    streakDays: 0,
    capped: false,
  };
  state.discrimLastApplyResult = null;
  state.discrimLastLibrary = null;
  state.discrimWarmupIds = [];
  state.discrimWarmupTotal = 0;
  state.discrimReviewWrongFlags = {};
  state.discrimReviewDone = 0;
  state.discrimLastReviewResult = null;
  els.discrimAlert.classList.add("hidden");
  els.discrimSkip.classList.add("hidden");
}

function discrimRemaining() {
  if (!state.discrimQueue) return 0;
  return Math.max(0, state.discrimQueue.length - state.discrimIndex);
}

async function startLibraryPractice() {
  sfx.unlock();
  stopDiscrimTick();
  clearTimeout(state.discrimFeedbackTimeout);
  resetDiscrimSessionStats();
  state.discrimKind = "library";
  state.discrimStartTime = new Date().toISOString();
  state.discrimElapsedMs = 0;
  els.viewDiscrim.style.setProperty("--session-tone", TONES.violet.main);
  document.getElementById("discrim-tag").textContent = "词库练习";
  setView("discrim");
  startDiscrimTick();
  await loadDiscrimSession({ count: state.discrimPracticeSize });
}

async function startReviewPractice() {
  sfx.unlock();
  stopDiscrimTick();
  clearTimeout(state.discrimFeedbackTimeout);
  resetDiscrimSessionStats();
  state.discrimKind = "review";
  state.discrimStartTime = new Date().toISOString();
  state.discrimElapsedMs = 0;
  els.viewDiscrim.style.setProperty("--session-tone", TONES.orange.main);
  document.getElementById("discrim-tag").textContent = "今日复习";
  setView("discrim");
  startDiscrimTick();
  await loadDiscrimSession({ review: true });
}

async function startWarmupPhase() {
  // 趁热巩固：本轮错词重测一遍（答对出队、答错排队尾）
  state.discrimKind = "warmup";
  state.discrimIndex = 0;
  state.discrimPointIndex = 0;
  state.discrimAnswers = [];
  state.discrimMode = "loading";
  els.discrimWord.classList.remove("flash-green", "flash-red");
  document.getElementById("discrim-tag").textContent = `趁热巩固 · 剩 ${state.discrimWarmupIds.length}`;
  setDiscrimStatus("趁热巩固 · 刚才错的再来一遍");
  try {
    const session = await fetchJson("/api/discrim/warmup/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_ids: state.discrimWarmupIds }),
    });
    state.discrimSession = session;
    state.discrimQueue = session.items.slice();
    state.discrimQueueTotal = session.items.length;
    state.discrimPlannedPoints += plannedDiscrimPoints(session.items);
    state.discrimMode = "answering";
    sfx.play("training.start");
    renderDiscrimWord();
    updateDebug();
  } catch (err) {
    state.discrimMode = "error";
    setDiscrimButtons(null);
    setDiscrimStatus(`趁热巩固出题失败：${err.message}`);
  }
}

// 一批词的计划判断总数（完成比例分母）
function plannedDiscrimPoints(items) {
  return (items || []).reduce(
    (sum, item) => sum + (Array.isArray(item.points) ? item.points.length : 0),
    0
  );
}

async function loadDiscrimSession(opts) {
  state.discrimMode = "loading";
  setDiscrimStatus("正在出题…");
  els.discrimWord.textContent = "";
  els.discrimWord.classList.remove("flash-green", "flash-red");
  try {
    let session;
    if (opts.review) {
      // 错题复习：今日到期词（固定顺序，重进不换序）
      session = await fetchJson("/api/discrim/review/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      state.discrimQueue = session.items.slice();
      state.discrimQueueTotal = session.items.length;
      document.getElementById("discrim-tag").textContent =
        `今日复习 · 剩 ${session.meta.due_remaining}`;
    } else {
      session = await fetchJson("/api/discrim/library/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ count: opts.count }),
      });
      state.discrimPlannedPoints += plannedDiscrimPoints(session.items);
    }
    state.discrimSession = session;
    state.discrimMode = "answering";
    sfx.play("training.start");
    renderDiscrimWord();
    updateDebug();
  } catch (err) {
    state.discrimMode = "error";
    setDiscrimButtons(null);
    setDiscrimStatus(`出题失败：${err.message}`);
  }
}

function renderDiscrimProgress() {
  let index = state.discrimIndex;
  let total;
  if (state.discrimKind === "library") {
    total = state.discrimSession ? state.discrimSession.items.length : 0;
  } else {
    total = state.discrimQueueTotal || (state.discrimQueue ? state.discrimQueue.length : 0);
    if (state.discrimQueue && state.discrimQueue.length > total) {
      // 答错重排导致队列变长：进度按「已消灭/总数」显示
      index = total - discrimRemaining();
    }
  }
  els.discrimProgressText.textContent = total
    ? `${Math.min(index + 1, total)} / ${total}`
    : "- / -";
  const pct = total > 0 ? Math.min(100, (index / total) * 100) : 0;
  els.discrimProgressFill.style.width = `${pct}%`;
  els.discrimProgressBead.style.left = `${pct}%`;
}

// 词条渲染：每个字一个方块，判断点下方留答题位；非判断点随词展示。
// 横杠光标（dcursor）挂在当前判断点的答题位上。
function renderDiscrimWord() {
  const item = currentDiscrimItem();
  if (!item) return;
  const points = item.points || [];
  const pointByChar = new Map(points.map((p) => [p.char_index, p]));
  const current = state.discrimAnswers.length < points.length
    ? points[state.discrimAnswers.length]
    : null;
  const wrap = document.createElement("div");
  wrap.className = "discrim-chars" + (item.word.length >= 4 ? " word-long" : "");
  const chars = Array.from(item.word);
  chars.forEach((ch, index) => {
    const point = pointByChar.get(index);
    const dchar = document.createElement("span");
    dchar.className = "dchar";
    if (point) {
      dchar.classList.add("judged");
      const chosen = state.discrimAnswers[points.indexOf(point)];
      if (chosen) dchar.classList.add("answered");
      dchar.innerHTML =
        `<i class="dch">${ch}</i>` +
        `<i class="dslot" data-point="${points.indexOf(point)}">${
          chosen ? `<span class="slot-label">${DISCRIM_PAIR_FINALS[point.pair][chosen]}</span>` : ""
        }</i>`;
      if (current === point) {
        dchar.classList.add("current");
        dchar.querySelector(".dslot").insertAdjacentHTML("beforeend", '<i class="dcursor" aria-hidden="true"></i>');
      }
    } else {
      dchar.innerHTML = `<i class="dch">${ch}</i><i class="dslot blank"></i>`;
    }
    wrap.appendChild(dchar);
  });
  els.discrimWord.textContent = "";
  els.discrimWord.appendChild(wrap);
  setDiscrimButtons(current ? current.pair : null);
  renderDiscrimProgress();
  if (state.discrimMode === "answering") setDiscrimStatus("选出横杠所指字的韵母");
}

function setDiscrimButtons(pair) {
  const labels = pair ? DISCRIM_PAIR_LABELS[pair] : null;
  els.discrimFrontBtn.textContent = labels ? labels.front : "前鼻";
  els.discrimBackBtn.textContent = labels ? labels.back : "后鼻";
  const enabled = Boolean(pair) && state.discrimMode === "answering";
  els.discrimFrontBtn.disabled = !enabled;
  els.discrimBackBtn.disabled = !enabled;
}

function answerDiscrim(side) {
  if (state.discrimMode !== "answering") return;
  const item = currentDiscrimItem();
  if (!item || !item.points) return;
  if (state.discrimAnswers.length >= item.points.length) return;
  state.discrimAnswers.push(side);
  if (state.discrimAnswers.length < item.points.length) {
    // 还有判断点：光标跳到下一个待判断字，按钮随新字的韵母对切换
    renderDiscrimWord();
    return;
  }
  // 整词判断点答完：统一判定 + 反馈
  judgeDiscrimWord();
}

async function judgeDiscrimWord() {
  const item = currentDiscrimItem();
  if (!item) return;
  state.discrimMode = "judging";
  setDiscrimButtons(null);
  try {
    const payload = await fetchJson("/api/discrim/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.discrimSession.session_id,
        item_id: item.item_id,
        answers: state.discrimAnswers,
      }),
    });
    applyDiscrimFeedback(payload);
  } catch (err) {
    // 判定请求失败：退回最后一个判断点，允许重答
    state.discrimAnswers.pop();
    state.discrimMode = "answering";
    renderDiscrimWord();
    setDiscrimStatus(`判定失败，再点一次：${err.message}`);
  }
}

function wrongPointHint(results) {
  // ✕ 正确：前鼻 en · běn（逐点给正确韵母与拼音）
  const parts = (results || [])
    .filter((r) => !r.correct)
    .map((r) => {
      const side = r.front ? "前鼻" : "后鼻";
      return `${side} ${r.final}${r.pinyin ? ` · ${r.pinyin}` : ""}`;
    });
  return parts.join("、");
}

async function reportDiscrimResult(allCorrect) {
  const item = currentDiscrimItem();
  if (!item || !state.discrimSession) return null;
  const base = {
    session_id: state.discrimSession.session_id,
    item_id: item.item_id,
  };
  if (state.discrimKind === "review") {
    const result = await fetchJson("/api/discrim/review/result", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...base,
        correct: allCorrect,
        had_wrong_this_round: Boolean(state.discrimReviewWrongFlags[item.item_id]),
      }),
    });
    state.discrimLastReviewResult = result;
    return result;
  }
  const result = await fetchJson("/api/discrim/library/result", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...base, correct: allCorrect }),
  });
  state.discrimLastLibrary = result;
  return result;
}

function applyDiscrimFeedback(payload) {
  const results = payload.results || [];
  const allCorrect = Boolean(payload.all_correct);
  const wordCorrectCount = results.filter((r) => r.correct).length;
  const item = currentDiscrimItem();
  if (allCorrect) sfx.play("answer.correct", {
    eventKey: `answer:${state.discrimSession?.session_id}:${state.discrimKind}:${state.discrimIndex}`,
  });
  state.discrimPointCount += results.length;
  state.discrimCorrectPoints += wordCorrectCount;
  state.discrimWordResults.push(results);
  const wordWrong = wordCorrectCount < results.length;
  if (wordWrong) {
    state.discrimConsecutive += 1;
    state.discrimConsecutivePeak = Math.max(
      state.discrimConsecutivePeak,
      state.discrimConsecutive
    );
  } else {
    state.discrimPerfectWords += 1;
    state.discrimConsecutive = 0;
  }
  // 连错 ≥2：警报条（整组保持显示）
  if (state.discrimConsecutive >= 2) {
    els.discrimAlert.classList.remove("hidden");
  }
  // 会话级累计（结算页汇总用）
  const acc = state.discrimAcc;
  if (acc) {
    acc.correct += wordCorrectCount;
    acc.points += results.length;
    acc.words += 1;
    if (wordWrong) {
      acc.peak = Math.max(acc.peak, state.discrimConsecutivePeak);
    } else {
      acc.perfectWords += 1;
    }
  }

  // 闪：全对绿闪；有错红闪 + 逐字标正确韵母（前鼻青 / 后鼻橙，错字加红标记）
  els.discrimWord.classList.remove("flash-green", "flash-red");
  void els.discrimWord.offsetWidth; // 重置动画
  els.discrimWord.classList.add(allCorrect ? "flash-green" : "flash-red");
  markDiscrimFeedback(results, allCorrect);

  // 客户端队列簿记（同步做，反馈计时器 700ms + 轻触跳过都依赖它）
  let statusFallback = allCorrect ? "全对 ✓" : "有错 · 正确韵母已标出";
  if (state.discrimKind === "library") {
    state.discrimLibraryCompleted += 1;
    if (item && wordWrong) {
      state.discrimWarmupIds.push(item.item_id);
      state.discrimWarmupTotal = state.discrimWarmupIds.length;
    }
    reportDiscrimResult(allCorrect).catch(() => setDiscrimStatus(statusFallback));
    setDiscrimStatus(statusFallback);
  } else if (state.discrimKind === "warmup") {
    if (wordWrong) {
      statusFallback = `✕ 正确：${wrongPointHint(results)}`;
      // 答错重排队尾，稍后复现
      state.discrimQueue.push(item);
      document.getElementById("discrim-tag").textContent =
        `趁热巩固 · 剩 ${discrimRemaining()}`;
    } else {
      statusFallback = "✓ 过关";
    }
    setDiscrimStatus(statusFallback);
  } else if (state.discrimKind === "review") {
    if (wordWrong) {
      statusFallback = `✕ 正确：${wrongPointHint(results)}`;
      state.discrimReviewWrongFlags[item.item_id] = true;
      // 答错重排队尾，滚完一遍后复现
      state.discrimQueue.push(item);
    } else {
      const hadWrong = Boolean(state.discrimReviewWrongFlags[item.item_id]);
      if (!state.discrimReviewDoneIds[item.item_id]) {
        state.discrimReviewDoneIds[item.item_id] = true;
        state.discrimReviewDone += 1;
      }
      statusFallback = hadWrong ? "✓ 已纠正 · 明天再复习" : "✓ 过关";
      // 上报在删除 flag 之前同步读取 had_wrong_this_round
      const reportPromise = reportDiscrimResult(allCorrect);
      delete state.discrimReviewWrongFlags[item.item_id];
      reportPromise
        .then((result) => {
          if (result && result.correct && !hadWrong) {
            if (result.mastered) {
              setDiscrimStatus("✓ 已掌握");
            } else if (result.scheduled_in_days) {
              setDiscrimStatus(`✓ 已安排 ${result.scheduled_in_days} 天后复习`);
            }
          }
          document.getElementById("discrim-tag").textContent =
            `今日复习 · 剩 ${result ? result.due_remaining : discrimRemaining()}`;
        })
        .catch(() => setDiscrimStatus(statusFallback));
    }
    setDiscrimStatus(statusFallback);
  }

  state.discrimMode = "feedback";
  els.discrimSkip.classList.remove("hidden");
  clearTimeout(state.discrimFeedbackTimeout);
  if (allCorrect) state.discrimFeedbackTimeout = setTimeout(nextDiscrimWord, DISCRIM_FEEDBACK_MS);
  else playDiscrimVoice(item);
}

function markDiscrimFeedback(results, allCorrect) {
  const item = currentDiscrimItem();
  if (!item) return;
  const points = item.points || [];
  results.forEach((result) => {
    const pointIndex = points.findIndex(
      (p) => p.char_index === result.char_index
    );
    const slot = els.discrimWord.querySelector(`.dslot[data-point="${pointIndex}"]`);
    if (!slot) return;
    const front = Boolean(result.front);
    const finalText = result.final;
    slot.textContent = "";
    const span = document.createElement("span");
    span.className =
      "slot-final" + (front ? " nasal-front" : " nasal-back") + (result.correct ? "" : " wrong");
    span.textContent = (result.correct ? "" : "✗ ") + finalText;
    slot.appendChild(span);
  });
  if (!allCorrect) {
    // 错字额外红标：把错判断点的字也标红
    results
      .filter((r) => !r.correct)
      .forEach((result) => {
        const pointIndex = points.findIndex(
          (p) => p.char_index === result.char_index
        );
        const dchar = els.discrimWord.querySelector(
          `.dchar .dslot[data-point="${pointIndex}"]`
        );
        if (dchar && dchar.parentElement) {
          dchar.parentElement.classList.add("wrong-char");
        }
      });
  }
}

function stopDiscrimVoice() {
  discrimAudioToken++;
  clearTimeout(state.discrimFeedbackTimeout);
  discrimAudio.onended = null; discrimAudio.onerror = null;
  discrimAudio.pause(); discrimAudio.removeAttribute("src"); discrimAudio.load();
  if (discrimAudioRelease) discrimAudioRelease();
  discrimAudioRelease = null;
}

function playDiscrimVoice(item) {
  stopDiscrimVoice();
  if (!item) return;
  const token = discrimAudioToken;
  discrimAudioRelease = sfx.beginTeaching();
  const done = () => {
    if (token !== discrimAudioToken || state.discrimMode !== "feedback") return;
    clearTimeout(state.discrimFeedbackTimeout);
    if (discrimAudioRelease) discrimAudioRelease();
    discrimAudioRelease = null;
    state.discrimFeedbackTimeout = setTimeout(nextDiscrimWord, 300);
  };
  discrimAudio.onended = done; discrimAudio.onerror = done;
  discrimAudio.src = window.demoVoice.url(`/api/clips/${item.item_id}`);
  state.discrimFeedbackTimeout = setTimeout(done, 12000);
  discrimAudio.play().catch(done);
}

async function nextDiscrimWord() {
  if (state.discrimMode !== "feedback") return;
  stopDiscrimVoice();
  state.discrimFeedbackTimeout = null;
  els.discrimSkip.classList.add("hidden");
  const total = state.discrimKind === "library"
    ? (state.discrimSession ? state.discrimSession.items.length : 0)
    : (state.discrimQueue ? state.discrimQueue.length : 0);
  if (state.discrimIndex + 1 < total) {
    state.discrimIndex += 1;
    state.discrimPointIndex = 0;
    state.discrimAnswers = [];
    state.discrimMode = "answering";
    els.discrimWord.classList.remove("flash-green", "flash-red");
    renderDiscrimWord();
    updateDebug();
    return;
  }
  // 本批完成
  if (state.discrimKind === "library") {
    if (state.discrimWarmupIds.length) {
      await startWarmupPhase();
    } else {
      await finishLibrarySession(false);
    }
    return;
  }
  if (state.discrimKind === "warmup") {
    await finishLibrarySession(false);
    return;
  }
  // review：队列滚完 → 今日复习完成
  await finishReviewSession();
}

function discrimPenalty(peak) {
  return Math.max(0, peak - 1);
}

function postDiscrimEvent(exitEarly, reward) {
  const peak = state.discrimConsecutivePeak;
  fetch("/api/discrim/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: state.discrimSession
        ? state.discrimSession.session_id
        : `disc-local-${Date.now()}`,
      source: state.discrimKind === "review" ? "review" : "library",
      start_time: state.discrimStartTime || new Date().toISOString(),
      end_time: new Date().toISOString(),
      exit_early: Boolean(exitEarly),
      item_count: state.discrimKind === "library"
        ? (state.discrimSession ? state.discrimSession.items.length : 0)
        : (state.discrimQueueTotal || 0),
      point_count: state.discrimPointCount,
      correct_points: state.discrimCorrectPoints,
      wrong_points: state.discrimPointCount - state.discrimCorrectPoints,
      perfect_words: state.discrimPerfectWords,
      consecutive_peak: peak,
      penalty: discrimPenalty(peak),
      actual_duration_sec: Math.round(state.discrimElapsedMs / 1000),
      beads_awarded: reward ? Number(reward.total_beads || 0) : 0,
      trio_bonus: reward ? Number(reward.trio_bonus || 0) : 0,
    }),
  }).catch(() => {});
}

async function settleLibraryReward(exitEarly) {
  clearTimeout(state.discrimFeedbackTimeout);
  stopDiscrimTick();
  state.discrimMode = "completed";
  const newStreakDays = streakAfterToday();
  const planned = Math.max(state.discrimPlannedPoints, state.discrimPointCount);
  let reward = null;
  if (state.discrimPointCount > 0) {
    reward = await settleActivity({
      activity: "discrim",
      // The existing API calls these "points", but its v2 tiers are word counts.
      // Extra judged syllables and warmup repeats must not change the selected tier.
      completed_points: Math.min(state.discrimLibraryCompleted, state.discrimPracticeSize),
      total_points: state.discrimPracticeSize,
      streak_days: newStreakDays,
      word_completed_today: completedToday("word"),
      sentence_completed_today: completedToday("sentence"),
      discrim_completed_today: completedToday("discrim"),
      trio_awarded_today: comboAwardedToday(),
    });
  }
  state.discrimLastApplyResult = applyReward(reward, {
    exitEarly,
    actualSec: Math.round(state.discrimElapsedMs / 1000),
    streakDays: newStreakDays,
    streakBonus: reward ? Number(reward.streak_bonus || 0) : 0,
    type: "discrim",
    sessionId: state.discrimSession ? state.discrimSession.session_id : null,
    correctPoints: state.discrimCorrectPoints,
    totalPoints: planned,
    discrimPoints: state.discrimPointCount,
    perfect: false,
  });
  const acc = state.discrimAcc;
  if (acc && reward) {
    acc.rewardSum += Number(reward.total_beads || 0);
    acc.perfectBonus += Number(reward.perfect_bonus || 0);
    acc.comboBonus += Number(reward.trio_bonus || 0);
    acc.streakBonus += Number(reward.streak_bonus || 0);
    acc.streakDays = reward.streak_days;
    acc.capped = acc.capped || Boolean(reward.capped);
  }
  postDiscrimEvent(exitEarly, reward);
  return reward;
}

async function finishLibrarySession(exitEarly) {
  const reward = await settleLibraryReward(exitEarly);
  await refreshDiscrimState();
  renderLibraryComplete({ exitEarly, reward });
  sfx.settlement(state.discrimLastApplyResult, `discrim:${state.discrimSession?.session_id}`);
}

async function finishDiscrimSessionEarly() {
  stopDiscrimVoice();
  // 复习：进度已存服务端、无逐次结算，直接回首页；
  // 词库/趁热：按已完成情况结算（趁热巩固中途退出按完整批次结算）
  if (state.discrimKind === "review") {
    await refreshDiscrimState();
    resetToHome();
    return;
  }
  const batchDone = state.discrimKind === "warmup";
  await finishLibrarySession(!batchDone);
}

async function finishReviewSession() {
  const last = state.discrimLastReviewResult || {};
  const dueRemaining = Number(last.due_remaining != null ? last.due_remaining : -1);
  if (dueRemaining > 0) {
    // 罕见兜底：还有到期词（理论不该发生），继续滚
    state.discrimIndex = 0;
    state.discrimPointIndex = 0;
    state.discrimAnswers = [];
    state.discrimMode = "loading";
    els.discrimWord.textContent = "";
    setDiscrimStatus("还有到期词 · 继续复习");
    await loadDiscrimSession({ review: true });
    return;
  }
  stopDiscrimTick();
  // 完成今日复习：一次性固定奖励（当日一次）
  let reward = null;
  if (!reviewAwardedToday()) {
    try {
      reward = await settleActivity({
        activity: "review",
      });
      markReviewAwarded();
    } catch (err) {
      console.warn("review reward settle failed", err);
    }
  }
  state.discrimLastApplyResult = applyReward(reward, {
    exitEarly: false,
    actualSec: Math.round(state.discrimElapsedMs / 1000),
    streakDays: computeStreak().days,
    streakBonus: 0,
    type: "review",
    sessionId: state.discrimSession ? state.discrimSession.session_id : null,
  });
  postDiscrimEvent(false, reward);
  await refreshDiscrimState();
  renderReviewComplete({ done: state.discrimReviewDone, reward });
  sfx.settlement(state.discrimLastApplyResult, `review:${todayKey()}`);
}

function renderLibraryComplete(result) {
  els.viewComplete.dataset.activity = "discrim";
  const tone = TONES.violet;
  els.viewComplete.style.setProperty("--entry", tone.main);
  els.viewComplete.style.setProperty("--entry-deep", tone.deep);
  els.viewComplete.style.setProperty("--entry-soft", tone.soft);
  const acc = state.discrimAcc || {};
  const exitEarly = Boolean(result.exitEarly);
  const reward = result.reward;
  const beads = reward ? Number(reward.total_beads || 0) : 0;
  const penalty = discrimPenalty(acc.peak || 0);
  const last = state.discrimLastLibrary || {};
  const lib = discrimInfo().library || {};
  const cursor = Number(last.cursor != null ? last.cursor : lib.cursor || 0);
  const total = Number(last.total != null ? last.total : lib.total || 0);
  const due = Number((discrimInfo().review || {}).due_today || 0);
  const warmupLine = state.discrimWarmupTotal > 0
    ? `<p class="discrim-score-note">趁热巩固 <strong>${state.discrimWarmupTotal}</strong> 个错词 ✓</p>`
    : "";
  const penaltyHtml =
    penalty > 0
      ? `<p class="discrim-penalty-note">⚠ 连错 ${acc.peak || 0} 词触发警报 · 扣 ${penalty} 分</p>`
      : "";
  const scoreHtml =
    penalty > 0
      ? `<p class="discrim-score-note">本次得分 ${acc.correct - penalty} / ${acc.points}</p>`
      : "";
  const rewardHtml = beads > 0 ? rewardBurstHtml(beads) : "";
  const noRewardHtml =
    reward && reward.eligible === false
      ? '<p class="discrim-score-note">完成不足 20%，本次没有拼点</p>'
      : "";
  els.completeBody.innerHTML =
    '<div class="complete-top">' +
    `<div class="complete-mark">${exitEarly ? "×" : acc.points > 0 && acc.correct === acc.points ? "✦" : "✓"}</div>` +
    `<h1>${exitEarly ? "本次结束" : "词库练习完成"}</h1>` +
    '<p class="complete-sub">听辨练习 · en / eng · in / ing 逐字判断</p>' +
    "</div>" +
    '<div class="discrim-summary">' +
    `<span class="discrim-summary-line">判断正确 <strong>${acc.correct || 0}</strong> / ${acc.points || 0} 音节</span>` +
    `<span class="discrim-summary-line">全对词 <strong>${acc.perfectWords || 0}</strong> / ${acc.words || 0}</span>` +
    `<span class="discrim-summary-line">用时 <strong>${Math.round(state.discrimElapsedMs / 1000)}</strong> 秒</span>` +
    "</div>" +
    rewardHtml +
    noRewardHtml +
    penaltyHtml +
    scoreHtml +
    warmupLine +
    `<p class="discrim-score-note">本轮已练 <strong>${cursor}</strong> 词 · 今日待复习 ${due} 个</p>` +
    trioLineHtml(reward) +
    trioProgressHtml() +
    pendingReadyHtml(state.discrimLastApplyResult) +
    '<div class="complete-actions">' +
    '<button id="discrim-again-btn" class="primary-btn tone-violet" type="button">继续词库练习</button>' +
    '<button id="discrim-home-btn" class="ghost-btn" type="button">返回首页</button>' +
    "</div>";
  els.completeBody.querySelector("#discrim-again-btn").addEventListener("click", () => {
    startLibraryPractice();
  });
  els.completeBody.querySelector("#discrim-home-btn").addEventListener("click", resetToHome);
  setView("complete");
}

function renderReviewComplete(result) {
  els.viewComplete.dataset.activity = "review";
  const tone = TONES.orange;
  els.viewComplete.style.setProperty("--entry", tone.main);
  els.viewComplete.style.setProperty("--entry-deep", tone.deep);
  els.viewComplete.style.setProperty("--entry-soft", tone.soft);
  const reward = result.reward;
  const beads = reward ? Number(reward.total_beads || 0) : 0;
  const rewardHtml = beads > 0 ? rewardBurstHtml(beads) : "";
  els.completeBody.innerHTML =
    '<div class="complete-top">' +
    '<div class="complete-mark">✦</div>' +
    "<h1>今日复习完成</h1>" +
    '<p class="complete-sub">错题复习 · 间隔重考</p>' +
    "</div>" +
    '<div class="discrim-summary">' +
    `<span class="discrim-summary-line">复习过关 <strong>${result.done}</strong> 个错词</span>` +
    `<span class="discrim-summary-line">下次复习已按 1 / 3 / 7 天排好</span>` +
    "</div>" +
    rewardHtml +
    pendingReadyHtml(state.discrimLastApplyResult) +
    '<div class="complete-actions">' +
    '<button id="discrim-home-btn" class="primary-btn tone-orange" type="button">返回首页</button>' +
    "</div>";
  els.completeBody.querySelector("#discrim-home-btn").addEventListener("click", resetToHome);
  setView("complete");
}

/* ---------- 训练流 ---------- */

async function startSession(profileId, duration, entryId, seed) {
  if (els.startBtn.disabled && state.mode === "preparing") return;
  els.startBtn.disabled = true; state.mode = "preparing";
  await reading.prepare();
  els.startBtn.disabled = false;
  sfx.unlock();
  state.profileId = profileId;
  state.duration = duration;
  if (entryId) state.entryId = entryId;
  state.session = null;
  state.index = 0;
  state.replayCount = 0;
  state.pauseCount = 0;
  state.completedItems = 0;
  state.timerRemainingMs = duration * 60 * 1000;
  renderTimer();
  applySessionTone();
  setView("training");
  setMode("loading_session");
  setStatus("正在准备…");
  els.word.textContent = "";
  els.pinyin.textContent = "";
  stopAudio();
  renderProgress(0, 1);
  updateDebug();
  try {
    const entry = entryById(entryId);
    const includeFinals =
      entry && filterGroupsOf(entry) ? selectedFinalsFor(entryId) : null;
    const session = await fetchJson("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profile_id: profileId,
        duration_minutes: duration,
        seed: seed ?? null,
        include_finals: includeFinals,
      }),
    });
    state.session = session;
    sfx.play("training.start");
    state.startTime = new Date().toISOString();
    state.timerRemainingMs = Math.max(0, Math.round(session.estimated_duration_sec * 1000));
    renderTimer();
    startTick();
    playItem(0);
  } catch (err) {
    setMode("error");
    setStatus(`生成失败：${err.message}`);
    els.pauseBtn.disabled = true;
    els.replayBtn.disabled = false;
  }
}

function applySessionTone() {
  const tone = toneOf(currentEntry());
  els.viewTraining.style.setProperty("--session-tone", tone.main);
  els.viewTraining.style.setProperty("--entry", tone.main);
  els.viewTraining.style.setProperty("--entry-deep", tone.deep);
  els.viewTraining.style.setProperty("--entry-soft", tone.soft);
}

function renderProgress(index, total) {
  const pct = total > 0 ? Math.min(100, (index / total) * 100) : 0;
  els.progressFill.style.width = `${pct}%`;
  els.progressBead.style.left = `${pct}%`;
}

function playItem(index) {
  reading.cancel();
  const session = state.session;
  if (!session || !session.items || index >= session.items.length) return;
  state.index = index;
  const item = session.items[index];
  els.word.textContent = item.word;
  els.word.classList.toggle("word-long", item.word.length >= 4);
  els.pinyin.textContent = item.pinyin;
  renderProgress(index + 1, session.items.length);
  updateDebug();
  setMode("playing_reference");
  setStatus("正在播放");
  els.player.src = window.demoVoice.url(`/api/clips/${item.item_id}`);
  els.player.play().catch(() => {
    /* 'error' event handles failures */
  });
}

function enterFollow() {
  const item = currentItem();
  if (!item) return;
  const t = timing();
  const followMs = Math.max(
    item.clip_duration_ms + t.extra_follow_sec * 1000,
    t.min_follow_sec * 1000
  );
  const transitionMs = t.transition_sec * 1000;
  setMode("waiting_follow");
  setStatus("请跟读");
  state.uiFollowTotalMs = followMs + transitionMs;
  state.followDeadline = performance.now() + followMs + transitionMs;
  clearTimeout(state.followTimeout);
  reading.start("word");
  state.followTimeout = setTimeout(followDone, followMs + transitionMs);
}

async function followDone() {
  if(state.mode!=='waiting_follow')return;
  clearTimeout(state.followTimeout);
  const id = currentItem()?.item_id;
  setMode("finishing"); stopTick();
  const result = await reading.grade("word", id, replay);
  if (!result.advance || currentItem()?.item_id !== id || state.mode !== "finishing") return;
  state.completedItems += result.complete ? 1 : 0;
  startTick();
  if (state.index + 1 < state.session.items.length) {
    playItem(state.index + 1);
  } else {
    finishSession(false);
  }
}

function togglePause() {
  sfx.stop();
  if (state.mode === "paused") {
    resume();
    return;
  }
  if (state.mode !== "playing_reference" && state.mode !== "waiting_follow") return;
  reading.cancel();
  state.pauseCount += 1;
  state.resumeFrom = state.mode;
  clearTimeout(state.followTimeout);
  stopTick();
  if (state.mode === "playing_reference") {
    els.player.pause();
  } else {
    state.followRemainingMs = Math.max(0, state.followDeadline - performance.now());
  }
  setMode("paused");
  setStatus("已暂停");
  els.pauseIcon.innerHTML = uiIcon("play");
  els.pauseLabel.textContent = "继续";
  els.pauseBtn.setAttribute("aria-label", "继续");
}

function resume() {
  if (state.mode !== "paused") return;
  const from = state.resumeFrom;
  state.resumeFrom = null;
  startTick();
  if (from === "playing_reference") {
    setMode("playing_reference");
    setStatus("正在播放");
    els.player.play().catch(() => {});
  } else {
    enterFollow();
  }
}

function replay() {
  reading.cancel();
  if (!state.session && state.mode === "error") {
    startSession(state.profileId, state.duration, state.entryId);
    return;
  }
  if (!state.session || state.mode === "loading_session" || state.mode === "completed") return;
  state.replayCount += 1;
  clearTimeout(state.followTimeout);
  startTick();
  setMode("playing_reference");
  setStatus("正在播放");
  els.player.currentTime = 0;
  els.player.play().catch(() => {});
  updateDebug();
}

function skipCurrent() {
  reading.cancel();
  if (!state.session || !state.session.items) return;
  clearTimeout(state.followTimeout);
  if (state.index + 1 < state.session.items.length) {
    playItem(state.index + 1);
  } else {
    finishSession(false);
  }
}

async function finishSession(exitEarly) {
  const measured = reading.required;
  reading.close();
  clearTimeout(state.followTimeout);
  stopTick();
  stopAudio();
  const session = state.session;
  const plannedMs = state.duration * 60 * 1000;
  const remainingMs = Number.isFinite(state.timerRemainingMs) ? state.timerRemainingMs : plannedMs;
  const elapsedMs = Math.min(plannedMs, Math.max(0, plannedMs - remainingMs));
  const ratio = measured
    ? clamp01(state.completedItems / Math.max(1, session?.items?.length || 0))
    : exitEarly ? clamp01(elapsedMs / plannedMs) : 1.0;
  const actualSec = Math.round(elapsedMs / 1000);
  setMode("completed");

  // Streak 只记录持续回来（X 天展示），不再发放拼点
  const newStreakDays = streakAfterToday();

  let reward = null;
  try {
    reward = await settleActivity({
      activity: "word",
      planned_duration_minutes: state.duration,
      completion_ratio: ratio,
      streak_days: newStreakDays,
      word_completed_today: completedToday("word"),
      sentence_completed_today: completedToday("sentence"),
      discrim_completed_today: completedToday("discrim"),
      trio_awarded_today: comboAwardedToday(),
    });
  } catch (err) {
    console.warn("reward settle failed", err);
  }

  const meta = {
    exitEarly,
    actualSec,
    ratio,
    streakDays: newStreakDays,
    streakBonus: reward ? Number(reward.streak_bonus || 0) : 0,
    type: "word",
    sessionId: session ? session.session_id : null,
  };
  const result = applyReward(reward, meta);
  recordEvent(reward, meta);
  renderComplete(result);
  sfx.settlement(result, `word:${session?.session_id || state.startTime}`);
}

function applyReward(reward, meta) {
  const progress = state.progress;
  const beads = reward ? Number(reward.total_beads || 0) : 0;
  progress.beadBalance = Number(progress.beadBalance || 0) + beads;

  const art = progress.currentArtworkId ? artworkById(progress.currentArtworkId) : null;
  const record = art ? ensureArtRecord(art.artwork_id) : null;
  const minutes = meta.actualSec / 60;
  const type = meta.type || "word";

  if (record) {
    if (type === "sentence") {
      record.sentenceMinutes = Number(record.sentenceMinutes || 0) + minutes;
    } else if (type === "discrim") {
      record.discrimMinutes = Number(record.discrimMinutes || 0) + minutes;
    } else {
      const minutesKey =
        { front_nasal: "frontNasalMinutes", back_nasal: "backNasalMinutes", contrast: "contrastMinutes" }[
          state.entryId
        ] || "contrastMinutes";
      record[minutesKey] = Number(record[minutesKey] || 0) + minutes;
    }
    record.totalMinutes = Number(record.totalMinutes || 0) + minutes;
    record.sessionCount = Number(record.sessionCount || 0) + 1;
  }

  // v3：拼点不再自动入作品——整颗进当前作品的「待拼」，由用户在作品详情亲手拼入；
  // 未满 1 颗的余量继续留在口袋（内部允许小数累计）。
  // 注意：beadBalance 的入账只在函数开头（第 2517 行附近）做一次，这里不再重复加。
  const placedBefore = record ? Math.min(Number(record.placedBeads || 0), art.active_bead_count) : 0;
  const pendingBefore = record ? Number(record.pendingBeads || 0) : 0;
  const pendingAdded = earmarkPending();
  const pendingTotal = record ? Number(record.pendingBeads || 0) : 0;

  const sessionRecord = {
    id: meta.sessionId || `s-${Date.now()}`,
    type,
    entryId: type === "word" ? state.entryId : null,
    plannedMinutes: type === "word" ? state.duration : null,
    actualMinutes: Math.round(minutes * 10) / 10,
    dayKey: todayKey(),
    ratio: type === "word" ? Math.round(meta.ratio * 100) / 100 : null,
    beads,
    exitEarly: meta.exitEarly,
    streakDays: meta.streakDays,
    streakBonus: meta.streakBonus,
    completedAt: new Date().toISOString(),
  };
  if (type === "sentence") {
    sessionRecord.sentenceCount = meta.sentenceCount || 0;
    sessionRecord.sentenceTotal = meta.sentenceTotal || 0;
  }
  if (type === "discrim") {
    sessionRecord.correctPoints = meta.correctPoints || 0;
    sessionRecord.totalPoints = meta.totalPoints || 0;
    sessionRecord.discrimPoints = meta.discrimPoints || 0;
    sessionRecord.discrimTotal = meta.totalPoints || 0;
    sessionRecord.perfect = Boolean(meta.perfect);
  }
  const trioBonus = reward ? Number(reward.trio_bonus || 0) : 0;
  sessionRecord.comboBonus = trioBonus;
  if (trioBonus > 0) {
    progress.comboAwardedDayKey = todayKey();
  }
  progress.sessions.push(sessionRecord);
  if (progress.sessions.length > 300) {
    progress.sessions = progress.sessions.slice(-300);
  }
  saveProgress();
  return {
    beads,
    pendingAdded,
    pendingTotal,
    placedBefore,
    pendingBefore,
    art,
    record,
    minutes,
    exitEarly: meta.exitEarly,
    streakDays: meta.streakDays,
    streakBonus: meta.streakBonus,
    type,
    capped: reward ? Boolean(reward.capped) : false,
    trioBonus,
  };
}

function recordEvent(reward, meta) {
  const session = state.session;
  if (!session || !state.startTime) return;
  const event = {
    session_id: session.session_id,
    profile_id: session.profile_id,
    duration_minutes: state.duration,
    start_time: state.startTime,
    end_time: new Date().toISOString(),
    completed_item_count: state.completedItems,
    exit_early: meta.exitEarly,
    replay_count: state.replayCount,
    pause_count: state.pauseCount,
    seed: session.seed,
    item_count: session.item_count,
    actual_duration_sec: meta.actualSec,
    completion_ratio: meta.ratio,
    beads_awarded: reward ? Number(reward.total_beads || 0) : 0,
    streak_days: meta.streakDays ?? null,
    streak_bonus_awarded: meta.streakBonus ?? null,
  };
  fetch("/api/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(event),
  }).catch(() => {});
}

/* ---------- 完成 / 拼点结算页 ---------- */

function renderComplete(result) {
  els.viewComplete.dataset.activity = "word";
  const entry = currentEntry();
  const tone = toneOf(entry);
  els.viewComplete.style.setProperty("--entry", tone.main);
  els.viewComplete.style.setProperty("--entry-deep", tone.deep);
  els.viewComplete.style.setProperty("--entry-soft", tone.soft);

  const art = result.art;
  const toneClass = entry ? entry.tone : "teal";
  const rewardHtml = result.beads > 0
    ? '<div class="reward-burst">' +
      '<span class="reward-beads" aria-hidden="true"><i class="bead teal"></i><i class="bead orange"></i><i class="bead violet"></i><i class="bead yellow"></i></span>' +
      `<span class="reward-amount">+${Math.floor(result.beads)}</span>` +
      '<span class="reward-unit">拼点</span>' +
      "</div>"
    : '<div class="reward-burst"><p class="complete-sub" style="margin:0">完成度不足 20%，这次没有拼点</p></div>';
  els.completeBody.innerHTML =
    '<div class="complete-top">' +
    '<div class="complete-mark">✓</div>' +
    `<h1>${result.exitEarly ? "本次结束" : "训练完成"}</h1>` +
    `<p class="complete-sub">${entry ? entry.label : "训练"} · ${state.duration} 分钟` +
    (result.exitEarly ? ` · 实际练了 ${Math.round(result.minutes)} 分钟` : "") +
    "</p>" +
    "</div>" +
    rewardHtml +
    (result.trioBonus > 0
      ? `<p class="discrim-perfect-note">✨ 今日三练达成 · +${result.trioBonus} 拼点</p>`
      : "") +
    pendingReadyHtml(result) +
    trioProgressHtml() +
    '<div class="complete-actions">' +
    `<button id="again-btn" class="primary-btn tone-${toneClass}" type="button">再来一组</button>` +
    '<button id="complete-home-btn" class="ghost-btn" type="button">返回首页</button>' +
    "</div>";
  els.completeBody.querySelector("#again-btn").addEventListener("click", () => {
    if (state.profileId) startSession(state.profileId, state.duration, state.entryId);
  });
  els.completeBody.querySelector("#complete-home-btn").addEventListener("click", resetToHome);
  setView("complete");
  reading.mountSummary(els.completeBody,()=>startSentenceSession('mixed',10,true));
}

// 结算后的「待拼」轻提示：作品保持训练前状态，等用户进详情亲手拼入
function pendingReadyHtml(result) {
  const art = result && result.art;
  const record = result && result.record;
  const pendingAdded = Number(result?.pendingAdded || 0);
  if (!art || pendingAdded <= 0) return "";
  const placed = Math.min(Number(record?.placedBeads || 0), art.active_bead_count);
  const pendingTotal = Number(record?.pendingBeads || 0);
  return (
    '<div class="complete-art ready">' +
    '<div class="plate-head"><span class="plate-title">待拼 · ' + art.name + "</span>" +
    `<span class="plate-percent">+${pendingAdded}</span></div>` +
    `<div class="plate-art">${beadArtworkSvg(art, placed, { light: true })}</div>` +
    `<p class="art-delta">已准备好继续拼「${art.name}」· 待拼 <strong>${pendingTotal}</strong> 颗</p>` +
    `<button type="button" class="place-link" data-place-art="${art.artwork_id}">去拼入 ${uiIcon("arrow")}</button>` +
    "</div>"
  );
}

function resetToHome() {
  reading.close();
  stopDiscrimVoice();
  clearTimeout(state.followTimeout);
  clearTimeout(state.sentenceFollowTimeout);
  clearTimeout(state.discrimFeedbackTimeout);
  stopTick();
  stopSentenceTick();
  stopDiscrimTick();
  stopAudio();
  stopAudio(els.sentencePlayer);
  state.session = null;
  state.sentenceSession = null;
  state.discrimSession = null;
  state.mode = "idle";
  state.sentenceMode = "idle";
  state.discrimMode = "idle";
  renderStats();
  refreshDiscrimState();
  updateSentenceStart();
  setView("home");
  els.pauseIcon.innerHTML = uiIcon("pause");
  els.pauseLabel.textContent = "暂停";
  els.pauseBtn.setAttribute("aria-label", "暂停");
  els.pauseBtn.disabled = true;
  els.replayBtn.disabled = true;
  els.sentencePauseIcon.innerHTML = uiIcon("pause");
  els.sentencePauseLabel.textContent = "暂停";
  els.sentencePauseBtn.disabled = true;
  els.sentenceReplayBtn.disabled = true;
  updateDebug();
}

/* ---------- 选作品 ---------- */

function openPicker(mode) {
  state.pickerMode = mode;
  state.pickerChoice = null;
  // 系列 6 件全部明牌可选（无解锁）；新手作品固定，不参与三选一
  const ids = state.artworks
    .map((art) => art.artwork_id)
    .filter((id) => {
      if (id === state.progress.currentArtworkId) return false;
      const record = state.progress.artworks[id];
      return !record || !record.completedAt;
    });

  if (!ids.length) {
    els.pickerBody.innerHTML =
      '<div class="picker-head"><h2>都拼好啦</h2>' +
      "<p>先把拼点攒起来，多练几组，新作品很快就能开始拼。</p></div>" +
      '<button id="picker-close" class="picker-confirm" type="button">知道了</button>';
    els.pickerBody.querySelector("#picker-close").addEventListener("click", closePicker);
  } else {
    els.pickerBody.innerHTML =
      '<div class="picker-head">' +
      "<h2>选择下一张作品</h2>" +
      "<p>选好作品，积攒拼点后亲手拼入。随时可切换，进度会保留。</p>" +
      "</div>" +
      `<div class="picker-grid${ids.length <= 2 ? " cols-2" : ""}"></div>` +
      '<button id="picker-confirm" class="picker-confirm" type="button" disabled>开始拼这张</button>';
    const grid = els.pickerBody.querySelector(".picker-grid");
    const confirmBtn = els.pickerBody.querySelector("#picker-confirm");
    ids.forEach((id) => {
      const art = artworkById(id);
      const rec = state.progress.artworks[id];
      const optionPlaced = rec ? Math.min(Number(rec.placedBeads || 0), art.active_bead_count) : 0;
      const option = document.createElement("button");
      option.type = "button";
      option.className = "picker-option";
      option.setAttribute("aria-pressed", "false");
      option.innerHTML =
        beadArtworkSvg(art, optionPlaced, { light: true }) +
        `<span class="picker-option-name">${art.name}</span>` +
        `<span class="picker-option-tag">${art.tagline || ""}</span>`;
      option.addEventListener("click", () => {
        state.pickerChoice = id;
        grid.querySelectorAll(".picker-option").forEach((item) => {
          item.setAttribute("aria-pressed", String(item === option));
        });
        confirmBtn.disabled = false;
      });
      grid.appendChild(option);
    });
    confirmBtn.addEventListener("click", confirmPick);
  }
  els.pickerOverlay.classList.remove("hidden");
}

function confirmPick() {
  const id = state.pickerChoice;
  if (!id) return;
  const progress = state.progress;
  progress.currentArtworkId = id;
  const record = ensureArtRecord(id);
  if (!record.startedAt) record.startedAt = new Date().toISOString();
  progress.onboardingDone = true;
  earmarkPending();
  saveProgress();
  closePicker();
  renderStats();
}

// 把口袋里的整颗拼点预登记为当前作品的「待拼」（pendingBeads）。
// 只登记、不点亮：placedBeads 只在用户于作品详情主动拼入时增加。
// 作品完成后口袋余量保留，等切换下一张时再登记给它。
function earmarkPending() {
  const progress = state.progress;
  if (!progress.currentArtworkId) return 0;
  const art = artworkById(progress.currentArtworkId);
  const record = ensureArtRecord(progress.currentArtworkId);
  if (!art || record.completedAt) return 0;
  const room =
    art.active_bead_count - Number(record.placedBeads || 0) - Number(record.pendingBeads || 0);
  const grant = Math.floor(Math.min(Math.max(0, room), Math.floor(Number(progress.beadBalance || 0))));
  if (grant <= 0) return 0;
  record.pendingBeads = Number(record.pendingBeads || 0) + grant;
  progress.beadBalance = Number(progress.beadBalance || 0) - grant;
  return grant;
}

function closePicker() {
  els.pickerOverlay.classList.add("hidden");
  els.pickerBody.textContent = "";
  state.pickerMode = null;
  state.pickerChoice = null;
}

/* ---------- 校音页（分组单画面，正常 / 音画同步半速） ---------- */

const CALIBRATION_VERSION = "2026-09-12-mobile-v3";
let calRunId = 0;
let calLoadTimer = null;
let calSoundRelease = null;

function calVideoUrl(finalName) {
  // 两种速度都用交付正常有声文件，让浏览器同步放慢同一段音画。
  return `/assets/calibration/${finalName}.mp4?v=${CALIBRATION_VERSION}`;
}

function calModeLabel() {
  return state.calibrationSpeed === "slow" ? "半速 · 音画同步放慢" : "正常速度";
}

function renderCalibration() {
  stopCalVideos();
  els.calGroups.textContent = "";
  els.calTabs.textContent = "";
  (state.calibration.groups || []).forEach((group) => {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.dataset.calGroup = group.id;
    tab.textContent = `${group.a.final} / ${group.b.final}`;
    tab.setAttribute("aria-controls", `cal-panel-${group.id}`);
    tab.setAttribute("aria-pressed", String(group.id === state.calibrationGroup));
    tab.addEventListener("click", () => selectCalibrationGroup(group.id));
    els.calTabs.appendChild(tab);
    const section = document.createElement("section");
    section.className = "cal-group";
    section.id = `cal-panel-${group.id}`;
    section.hidden = group.id !== state.calibrationGroup;
    section.setAttribute("aria-label", group.label);
    section.innerHTML =
      `<h3 class="cal-group-label"><span class="cal-current-final">${group.a.final}</span><span class="cal-current-type">前鼻音 · 舌尖收 n</span></h3>` +
      '<div class="cal-pair">' +
      calibrationCard(group, "a") + calibrationCard(group, "b") +
      "</div>" +
      '<div class="cal-seq">' +
      `<button type="button" data-group="${group.id}" data-seq="a" aria-pressed="false">${group.a.final}</button>` +
      `<button type="button" data-group="${group.id}" data-seq="b" aria-pressed="false">${group.b.final}</button>` +
      `<button type="button" data-group="${group.id}" data-seq="ab" aria-pressed="false">${group.a.final} → ${group.b.final}</button>` +
      `<button type="button" data-group="${group.id}" data-seq="ba" aria-pressed="false">${group.b.final} → ${group.a.final}</button>` +
      "</div>";
    section.querySelectorAll("[data-seq]").forEach((btn) => {
      btn.addEventListener("click", () => playCalibration(group.id, btn.dataset.seq));
    });
    els.calGroups.appendChild(section);
  });
}

function calibrationCard(group, side) {
  const item = group[side];
  const tone = TONES[item.tone] || TONES.teal;
  return (
    `<div class="cal-card" data-group="${group.id}" data-side="${side}" style="--card-tone:${tone.main}"${side === "b" ? " hidden" : ""}>` +
    '<div class="cal-video">' +
    `<video data-final="${item.final}" aria-label="${item.final} 发音动画" src="${calVideoUrl(item.final)}" ` +
    `poster="/assets/calibration/${item.final}-poster.webp?v=${CALIBRATION_VERSION}" ` +
    `preload="metadata" playsinline webkit-playsinline disablepictureinpicture></video>` +
    "</div></div>"
  );
}

function getCalVideo(groupId, side) {
  return els.calGroups.querySelector(`.cal-card[data-group="${groupId}"][data-side="${side}"] video`);
}

function selectCalibrationGroup(groupId) {
  if (!(state.calibration.groups || []).some(group => group.id === groupId)) return;
  if (groupId === state.calibrationGroup) return;
  stopCalVideos();
  state.calibrationGroup = groupId;
  els.calTabs.querySelectorAll("button").forEach(btn => {
    btn.setAttribute("aria-pressed", String(btn.dataset.calGroup === groupId));
  });
  els.calGroups.querySelectorAll(".cal-group").forEach(section => {
    section.hidden = section.id !== `cal-panel-${groupId}`;
  });
  els.calStatus.textContent = "点音名听示范，点箭头依次对比";
}

function setCalibrationSpeed(speed) {
  if (!["normal", "slow"].includes(speed) || speed === state.calibrationSpeed) return;
  stopCalVideos();
  state.calibrationSpeed = speed;
  document.querySelectorAll("[data-cal-speed]").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.calSpeed === speed));
  });
  els.calGroups.querySelectorAll("video").forEach((video) => {
    video.muted = false;
    video.defaultPlaybackRate = video.playbackRate = speed === "slow" ? 0.5 : 1;
    video.preservesPitch = true;
  });
  els.calStatus.textContent = `已切换${calModeLabel()}，点音名开始播放`;
}

function playCalibration(groupId, seq) {
  const group = (state.calibration.groups || []).find((g) => g.id === groupId);
  if (!group || !["a", "b", "ab", "ba"].includes(seq)) return;
  selectCalibrationGroup(groupId);
  stopCalVideos();
  const runId = calRunId;
  calSoundRelease = sfx.beginTeaching();
  const sides = seq.split("");
  const button = els.calGroups.querySelector(`[data-group="${groupId}"][data-seq="${seq}"]`);
  button.classList.add("active");
  button.setAttribute("aria-pressed", "true");
  els.calStop.disabled = false;
  let cursor = 0;
  const currentRun = () => runId === calRunId && document.body.dataset.view === "calibration";
  const fail = (message) => {
    if (currentRun()) stopCalVideos(`${message}，请点音名或箭头重试`);
  };
  const playNext = () => {
    if (!currentRun()) return;
    clearTimeout(calLoadTimer);
    if (cursor >= sides.length) {
      stopCalVideos(`播放完毕 · ${calModeLabel()}，可再次点按重播`);
      return;
    }
    const side = sides[cursor++];
    const video = getCalVideo(groupId, side);
    if (!video) return fail("动画暂时不可用");
    const step = cursor;
    markCalPlaying(groupId, side);
    els.calStatus.textContent = `正在加载 ${group[side].final} · ${calModeLabel()}`;
    video.muted = false;
    video.volume = 1;
    video.playbackRate = state.calibrationSpeed === "slow" ? 0.5 : 1;
    video.preservesPitch = true;
    video.onended = () => {
      if (!currentRun() || cursor !== step || !video.ended) return;
      video.onended = video.onplaying = video.onerror = video.onwaiting = null;
      playNext();
    };
    video.onplaying = () => {
      if (!currentRun() || cursor !== step) return;
      clearTimeout(calLoadTimer);
      els.calStatus.textContent = `正在播放 ${group[side].final} · ${calModeLabel()}${sides.length > 1 ? `（${step}/2）` : ""}`;
    };
    const waitForMedia = () => {
      if (!currentRun() || cursor !== step) return;
      clearTimeout(calLoadTimer);
      calLoadTimer = setTimeout(() => fail("动画加载超时"), 12000);
    };
    video.onwaiting = waitForMedia;
    video.onerror = () => fail("动画加载失败");
    waitForMedia();
    try {
      if (video.error) video.load();
      video.currentTime = 0;
      video.play().catch((err) => {
        // 切换或停止会取消旧 play Promise；旧回调不能改新一轮状态。
        if (!currentRun() || cursor !== step) return;
        fail(err.name === "NotAllowedError" ? "浏览器未允许播放" : "动画播放失败");
      });
    } catch {
      fail("动画播放失败");
    }
  };
  playNext();
}

function markCalPlaying(groupId, side) {
  const group = state.calibration.groups.find(g => g.id === groupId);
  els.calGroups.querySelectorAll(".cal-card").forEach((card) => {
    const active = card.dataset.group === groupId && card.dataset.side === side;
    card.classList.toggle("playing", active);
    if (card.dataset.group === groupId) card.hidden = !active;
  });
  const section = document.getElementById(`cal-panel-${groupId}`);
  section.querySelector(".cal-current-final").textContent = group[side].final;
  section.querySelector(".cal-current-type").textContent = side === "a" ? "前鼻音 · 舌尖收 n" : "后鼻音 · 舌后部收 ng";
  section.dataset.side = side;
}

function stopCalVideos(message = "点音名听示范，点箭头依次对比") {
  calSoundRelease?.();
  calSoundRelease = null;
  // 先使所有已排队回调失效，再暂停；保护快速重播、换组和换模式。
  calRunId += 1;
  clearTimeout(calLoadTimer);
  els.calGroups.querySelectorAll("video").forEach((video) => {
    video.onended = video.onplaying = video.onerror = video.onwaiting = null;
    video.pause();
    try { video.currentTime = 0; } catch { /* metadata may not be loaded */ }
  });
  els.calGroups.querySelectorAll(".cal-card").forEach((card) => card.classList.remove("playing"));
  els.calGroups.querySelectorAll(".cal-seq button").forEach((btn) => {
    btn.classList.remove("active");
    btn.setAttribute("aria-pressed", "false");
  });
  els.calStop.disabled = true;
  els.calStatus.textContent = message;
}

/* ---------- 作品墙（新手作品 + 猫猫系列 X/6） ---------- */

function renderWall() {
  const progress = state.progress;
  const inProgress = [];
  const completed = [];
  const available = [];
  const locked = []; // 保留占位（当前目录全解锁，产物为空）

  state.artworks.forEach((art) => {
    const record = progress.artworks[art.artwork_id];
    if (record && record.completedAt) {
      completed.push({ art, record });
    } else if (art.artwork_id === progress.currentArtworkId) {
      inProgress.push({ art, record });
    } else {
      available.push({ art, record });
    }
  });

  const beginner = state.artworks.filter((art) => !art.series_id);
  const seriesArts = state.artworks.filter((art) => art.series_id);
  const doneSet = new Set(completed.map((item) => item.art.artwork_id));
  const seriesDone = seriesArts.filter((art) => doneSet.has(art.artwork_id)).length;
  const seriesComplete = seriesDone >= seriesArts.length;

  const tilesOf = (arts) => {
    const entries = [];
    arts.forEach((art) => {
      const record = progress.artworks[art.artwork_id];
      if (record && record.completedAt) entries.push({ art, record });
    });
    inProgress.forEach((item) => {
      if (arts.some((art) => art.artwork_id === item.art.artwork_id)) entries.push(item);
    });
    available.forEach((item) => {
      if (arts.some((art) => art.artwork_id === item.art.artwork_id)) entries.push(item);
    });
    return entries;
  };

  let html = "";
  if (beginner.length) {
    html += '<h3 class="wall-section-title">新手作品</h3>';
    html += '<div class="wall-grid">' + tilesOf(beginner).map(wallTile).join("") + "</div>";
  }
  if (seriesArts.length) {
    html +=
      '<div class="wall-series-head">' +
      `<h3 class="wall-section-title">猫猫系列 <strong>${seriesDone}/${seriesArts.length}</strong></h3>` +
      (seriesComplete ? '<span class="series-done-tag">✦ 已集齐</span>' : "") +
      "</div>";
    html += '<div class="wall-grid">' + tilesOf(seriesArts).map(wallTile).join("") + "</div>";
  }
  if (!inProgress.length && !available.length && !completed.length) {
    html += '<div class="wall-empty">还没有作品，先选一张开始吧。</div>';
  }
  if (locked.length) {
    html += '<h3 class="wall-section-title">未解锁</h3>';
    html += '<div class="wall-grid">' + locked.map(wallTileLocked).join("") + "</div>";
  }
  els.wallBody.innerHTML = html;

  els.wallBody.querySelectorAll("[data-detail]").forEach((btn) => {
    btn.addEventListener("click", () => {
      openDetail(btn.getAttribute("data-detail"));
    });
  });
}

function wallTile(entry) {
  const { art, record } = entry;
  const total = art.active_bead_count;
  const done = Boolean(record && record.completedAt);
  const placed = record ? Math.min(Number(record.placedBeads || 0), total) : 0;
  const pending = record && !done ? Number(record.pendingBeads || 0) : 0;
  const pct = Math.round((placed / total) * 100);
  // 未开始：只显示毛坯点阵轮廓（看不到内容）；进行中：已拼颗数亮 + 毛坯点；完成：全亮
  const svg = record
    ? beadArtworkSvg(art, done ? total : placed, { light: true })
    : beadArtworkSvg(art, 0, { light: true });
  const meta = done
    ? `${Math.round(record.totalMinutes)} 分钟拼成`
    : record
      ? `${placed} / ${total} · ${pct}%` + (pending > 0 ? ` · 待拼 ${pending}` : "")
      : "开始拼";
  const doneTag = done ? '<span class="done-tag">✓</span>' : "";
  const currentTag =
    !done && art.artwork_id === state.progress.currentArtworkId
      ? '<span class="current-tag">正在拼</span>'
      : "";
  const pendingTag =
    !done && pending > 0 ? `<span class="pending-tag">待拼 +${pending}</span>` : "";
  return (
    `<button class="wall-tile" type="button" data-detail="${art.artwork_id}">` +
    currentTag +
    doneTag +
    pendingTag +
    svg +
    `<span class="wall-tile-name">${art.name}</span>` +
    `<span class="wall-tile-meta">${meta}</span>` +
    "</button>"
  );
}

function wallTileLocked(art) {
  return (
    `<button class="wall-tile locked" type="button" data-detail="${art.artwork_id}">` +
    '<span class="lock-tag">🔒</span>' +
    beadArtworkSvg(art, art.active_bead_count, { className: "silhouette", light: true }) +
    `<span class="wall-tile-name">${art.name}</span>` +
    '<span class="wall-tile-meta">完成 1 件作品后解锁</span>' +
    "</button>"
  );
}

/* ---------- 作品详情弹层（含「亲手拼入」交互） ---------- */

function openDetail(artworkId) {
  const art = artworkById(artworkId);
  if (!art) return;
  renderDetail(art);
  els.detailOverlay.classList.remove("hidden");
}

function closeDetail() {
  cancelIronCeremony();
  sfx.stop();
  stopPlacement();
  placement = null;
  els.detailOverlay.classList.add("hidden");
  els.detailBody.textContent = "";
  saveProgress();
  renderWall(); // 拼入后回列表要看到最新块面
  renderStats();
}

function formatDayLabel(dayKey) {
  if (!dayKey || !/^\d{4}-\d{2}-\d{2}$/.test(dayKey)) return dayKey || "—";
  const d = new Date(dayKey + "T00:00:00");
  const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
  const prefix = dayKey === todayKey() ? "今天 · " : "";
  return `${prefix}${d.getMonth() + 1}月${d.getDate()}日 周${weekdays[d.getDay()]}`;
}

function formatMonthDay(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

function renderDetail(art) {
  cancelIronCeremony();
  const progress = state.progress;
  stopPlacement();
  placement = null;
  const record = progress.artworks[art.artwork_id] || null;
  const completed = Boolean(record && record.completedAt);
  const isCurrent = progress.currentArtworkId === art.artwork_id;
  const total = art.active_bead_count;
  const placed = record ? Math.min(Number(record.placedBeads || 0), total) : 0;
  const pending = record && !completed ? Number(record.pendingBeads || 0) : 0;
  const started = Boolean(record && (record.startedAt || placed > 0));
  const pct = Math.min(100, Math.round((placed / total) * 100));
  const seriesLabel = art.series_id ? "猫猫系列" : "新手作品";

  // 未拼入：毛坯点阵轮廓（看不到内容）；进行中：已拼颗数亮 + 毛坯点；完成：全亮
  const svg = completed
    ? beadArtworkSvg(art, total, {})
    : placed > 0
      ? beadArtworkSvg(art, placed, { className: "anim" })
      : beadArtworkSvg(art, 0, {});

  let statusHtml = "";
  let actionsHtml = "";
  if (completed) {
    statusHtml =
      '<div class="detail-status done">✓ 已于 ' +
      formatMonthDay(record.completedAt) +
      " 完成 · 第 " +
      (record.completedNumber || 1) +
      " 件作品</div>";
    actionsHtml =
      '<button id="detail-close-btn" class="primary-btn" type="button">知道了</button>';
  } else if (pending > 0) {
    statusHtml =
      `<div class="detail-status current"><span>已拼 <strong>${placed}</strong> / ${total} · ${pct}%</span><span class="pending-count">待拼 <strong>${pending}</strong> 颗</span></div>`;
    actionsHtml =
      '<button id="detail-place-btn" class="primary-btn place-btn" type="button">按住拼入 · 剩 ' +
      pending +
      " 颗</button>" +
      '<p class="place-hint">轻点拼一颗 · 长按连续拼</p>';
  } else if (!started) {
    statusHtml =
      `<div class="detail-status current">还没开始 · 共 ${total} 颗拼豆</div>`;
    actionsHtml = isCurrent
      ? '<button id="detail-train-btn" class="ghost-btn" type="button">去训练赚拼点</button>'
      : '<button id="detail-start-btn" class="primary-btn" type="button">开始拼这张</button>';
  } else {
    statusHtml =
      `<div class="detail-status current">已拼 ${placed} / ${total} · ${pct}%</div>`;
    actionsHtml = isCurrent
      ? '<button id="detail-train-btn" class="ghost-btn" type="button">去训练赚拼点</button>'
      : '<button id="detail-start-btn" class="primary-btn" type="button">设为当前作品</button>';
  }

  const progressHtml = !completed
    ? '<div class="detail-progress bead-progress">' +
      `<div class="fill" style="width:${pct}%"></div>` +
      `<span class="tip" style="left:${pct}%"></span>` +
      "</div>"
    : "";

  els.detailBody.innerHTML =
    '<button id="detail-close" class="detail-close" type="button" aria-label="关闭">×</button>' +
    `<div class="detail-art">${svg}</div>` +
    '<div class="detail-head">' +
    `<h2>${art.name}</h2>` +
    `<span class="detail-category">${seriesLabel}</span>` +
    "</div>" +
    `<p class="detail-tagline">${art.tagline || ""}</p>` +
    statusHtml +
    progressHtml +
    '<div class="detail-actions">' + actionsHtml + "</div>";

  els.detailBody.querySelector("#detail-close").addEventListener("click", closeDetail);
  const closeBtn = els.detailBody.querySelector("#detail-close-btn");
  if (closeBtn) closeBtn.addEventListener("click", closeDetail);

  const startBtn = els.detailBody.querySelector("#detail-start-btn");
  if (startBtn) {
    startBtn.addEventListener("click", () => {
      state.progress.currentArtworkId = art.artwork_id;
      const rec = ensureArtRecord(art.artwork_id);
      if (!rec.startedAt) rec.startedAt = new Date().toISOString();
      earmarkPending();
      saveProgress();
      renderStats();
      renderDetail(art); // 就地刷新（可能立刻有新待拼）
    });
  }

  const trainBtn = els.detailBody.querySelector("#detail-train-btn");
  if (trainBtn) {
    trainBtn.addEventListener("click", () => {
      closeDetail();
      resetToHome();
    });
  }

  const placeBtn = els.detailBody.querySelector("#detail-place-btn");
  if (placeBtn) bindPlacement(placeBtn, art, record);
}

/* ---------- 亲手拼入：单击一颗 / 长按加速连拼 ---------- */

let placement = null;

function stopPlacement() {
  sfx.stopBus("bead");
  if (!placement) return;
  placement.holding = false;
  clearTimeout(placement.holdTimer);
  cancelAnimationFrame(placement.raf);
}

function bindPlacement(btn, art, record) {
  const svgEl = els.detailBody.querySelector(".bead-art");
  placement = {
    art,
    record,
    rects: svgEl ? svgEl.querySelectorAll(".bead") : [],
    holding: false,
    raf: 0,
    holdTimer: 0,
    holdStart: 0,
    last: 0,
    acc: 0,
  };
  btn.addEventListener("contextmenu", (event) => event.preventDefault());
  const begin = (event) => {
    event.preventDefault();
    try {
      if (event.pointerId != null) btn.setPointerCapture(event.pointerId);
    } catch {
      /* ignore */
    }
    ensureAudio();
    if (!placement) return;
    btn.classList.add("holding");
    placeBeads(1);
    // placeBeads 可能因待拼耗尽/拼满而重渲染详情（placement 置空），此时不再排长按
    if (!placement) return;
    clearTimeout(placement.holdTimer);
    placement.holdTimer = setTimeout(startHold, 320);
  };
  btn.addEventListener("pointerdown", begin);
  const stop = (event) => {
    // A tap keeps its 66ms tick; releasing a repeating hold stops the bead bus.
    if (placement?.holding || ["pointercancel", "blur"].includes(event?.type)) sfx.stopBus("bead");
    btn.classList.remove("holding");
    clearTimeout(placement?.holdTimer);
    if (placement) placement.holding = false;
    cancelAnimationFrame(placement?.raf || 0);
    updatePlacementUi();
    saveProgress();
  };
  btn.addEventListener("pointerup", stop);
  btn.addEventListener("pointercancel", stop);
  btn.addEventListener("lostpointercapture", stop);
  btn.addEventListener("blur", stop);
  btn.addEventListener("keydown", (event) => {
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      if (!event.repeat) begin(event);
    }
  });
  btn.addEventListener("keyup", (event) => {
    if (event.key === " " || event.key === "Enter") { event.preventDefault(); stop(); }
  });
}

function startHold() {
  if (!placement || placement.record.completedAt) return;
  placement.holding = true;
  placement.holdStart = performance.now();
  placement.last = placement.holdStart;
  placement.acc = 0;
  const loop = (now) => {
    if (!placement || !placement.holding) return;
    const dt = Math.min(0.1, (now - placement.last) / 1000);
    placement.last = now;
    const t = (now - placement.holdStart) / 1000;
    // 起步 8 颗/秒、2.5 秒升到 ~52 颗/秒（小堆保持颗粒感）；
    // 待拼越多自动越快（大堆可到 ~240 颗/秒），快拼完时自动减速收尾。
    const remaining = Number(placement.record.pendingBeads || 0);
    const rate =
      8 +
      44 * Math.min(1, t / 2.5) +
      Math.min(220, Math.max(0, (remaining - 200) / 12));
    placement.acc += dt * rate;
    const n = Math.floor(placement.acc);
    if (n > 0) {
      placement.acc -= n;
      placeBeads(n);
    }
    if (placement && placement.holding) placement.raf = requestAnimationFrame(loop);
  };
  placement.raf = requestAnimationFrame(loop);
}

function placeBeads(count) {
  const p = placement;
  if (!p || p.record.completedAt) return;
  const total = p.art.active_bead_count;
  const room = Math.min(count, total - p.record.placedBeads, p.record.pendingBeads);
  if (room <= 0) {
    updatePlacementUi();
    return;
  }
  for (let i = 0; i < room; i++) {
    const rect = p.rects[p.record.placedBeads + i];
    if (rect) rect.classList.add("on");
  }
  p.record.placedBeads += room;
  p.record.pendingBeads -= room;
  playPlaceTick(room);
  if (p.record.placedBeads >= total) {
    updatePlacementUi();
    finishPlacedArtwork();
    return;
  }
  updatePlacementUi();
  // 待拼耗尽：就地切到「去训练赚拼点」态，避免按钮停留在过期的「剩 N 颗」上
  if (p.record.pendingBeads <= 0) renderDetail(p.art);
}

function updatePlacementUi() {
  const p = placement;
  if (!p) return;
  const total = p.art.active_bead_count;
  const placed = Math.min(Number(p.record.placedBeads || 0), total);
  const pending = Number(p.record.pendingBeads || 0);
  const pct = Math.min(100, Math.round((placed / total) * 100));
  const status = els.detailBody.querySelector(".detail-status");
  if (status) {
    status.textContent =
      pending > 0
        ? `已拼 ${placed} / ${total} · ${pct}% · 待拼 +${pending}`
        : `已拼 ${placed} / ${total} · ${pct}%`;
  }
  const fill = els.detailBody.querySelector(".bead-progress .fill");
  if (fill) fill.style.width = pct + "%";
  const tip = els.detailBody.querySelector(".bead-progress .tip");
  if (tip) tip.style.left = pct + "%";
  const btn = els.detailBody.querySelector("#detail-place-btn");
  if (btn && pending > 0) btn.textContent = `按住拼入 · 剩 ${pending} 颗`;
}

function finishPlacedArtwork() {
  const p = placement;
  if (!p || p.record.completedAt) return;
  stopPlacement();
  const { art, record } = p;
  placement = null;
  record.completedAt = new Date().toISOString();
  record.completedNumber = completedArtworkIds().length;
  saveProgress();
  renderStats();
  showIronCeremony(art, record);
}

/* ---------- 拼入轻反馈（音效 / 震动）与熨烫仪式 ---------- */

let placeTickLast = 0;

function ensureAudio() {
  sfx.unlock();
}

function playPlaceTick(count) {
  sfx.play("bead.place");
  const now = performance.now();
  if (count > 1 && now - placeTickLast < 70) return; // 高速连拼时限频
  placeTickLast = now;
  if (navigator.vibrate) navigator.vibrate(8);
}

let ironRun = 0, ironTimer = null, ironAudible = false;
function cancelIronCeremony() {
  ironRun++;
  clearTimeout(ironTimer);
  sfx.stopBus("texture");
  sfx.stopBus("celebration");
}

// 单件拼满：详情弹层内直接走「熨烫 / 融合」仪式（约 1.8s）→ 成品；
// 系列第 6 件在此触发「猫猫系列 6/6 完成」庆祝（一次）。
function showIronCeremony(art, record) {
  cancelIronCeremony();
  const own = ironRun;
  ironAudible = !document.hidden;
  sfx.play("artwork.fuse");
  const seriesDone = art.series_id ? seriesCompletedCount() : 0;
  const seriesTotal = art.series_id ? seriesTotalCount() : 0;
  const isSeriesComplete = Boolean(art.series_id) && seriesDone >= seriesTotal;
  els.detailBody.innerHTML =
    '<div class="iron-stage">' +
    `<div class="iron-mark" aria-hidden="true">${uiMascot("beading")}</div>` +
    '<p class="iron-caption">熨烫中 · 拼豆正在融成一幅画…</p>' +
    "</div>";
  ironTimer = setTimeout(() => {
    if (own !== ironRun || els.detailOverlay.classList.contains("hidden")) return;
    const headHtml = isSeriesComplete
      ? "<h1>猫猫系列 · 6/6 完成</h1>" +
        `<p class="complete-sub">${art.name} 拼好了 · 系列集齐啦</p>`
      : "<h1>熨烫完成！</h1>" + `<p class="complete-sub">${art.name} 拼好了</p>`;
    els.detailBody.innerHTML =
      '<button id="detail-close" class="detail-close" type="button" aria-label="关闭">×</button>' +
      '<div class="detail-ceremony">' +
      '<div class="complete-top"><div class="complete-mark">✦</div>' + headHtml + "</div>" +
      '<div class="complete-art celebrate">' +
      `<div class="plate-art">${beadArtworkSvg(art, art.active_bead_count, { animate: true, from: art.active_bead_count - 1 })}</div>` +
      `<div class="plate-name">${art.name}</div>` +
      '<p class="complete-copy">这是你的第 ' +
      (record.completedNumber || 1) +
      ' 件拼豆作品。<br>这张作品由 <strong>' +
      Math.round(record.totalMinutes) +
      "</strong> 分钟真实训练慢慢拼成。</p>" +
      "</div></div>" +
      '<div class="detail-actions">' +
      '<button id="detail-wall-btn" class="primary-btn" type="button">收进作品墙</button>' +
      "</div>";
    if (ironAudible) sfx.play(isSeriesComplete ? "series.complete" : "artwork.complete", {
      eventKey: `artwork:${art.artwork_id}:${record.completedAt}`,
    });
    els.detailBody.querySelector("#detail-close").addEventListener("click", closeDetail);
    els.detailBody
      .querySelector("#detail-wall-btn")
      .addEventListener("click", () => {
        closeDetail();
        setView("wall");
        renderWall();
      });
  }, 1800);
}

/* ---------- 训练历史页 ---------- */

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function historyRow(session) {
  if (session.type === "sentence") return sentenceHistoryRow(session);
  if (session.type === "discrim") return discrimHistoryRow(session);
  if (session.type === "review") return reviewHistoryRow(session);
  const tone = entryToneOf(session.entryId);
  const label = entryLabel(session.entryId);
  const ratioPct = Math.round(Number(session.ratio || 0) * 100);
  const beads = Number(session.beads || 0);
  const detail = session.exitEarly
    ? `实际 ${Math.round(Number(session.actualMinutes || 0))} 分钟 · ${ratioPct}%`
    : `${session.plannedMinutes} 分钟 · 完成`;
  const comboBadge =
    Number(session.comboBonus || 0) > 0
      ? `<span class="history-streak" style="color:var(--green-deep);background:var(--green-soft)">三练 +${session.comboBonus}</span>`
      : "";
  return (
    '<div class="history-row">' +
    `<span class="history-dot tone-${tone}" aria-hidden="true">${uiIcon("words")}</span>` +
    '<span class="history-main">' +
    `<span class="history-name">${label} · ${session.plannedMinutes || "—"} 分钟</span>` +
    `<span class="history-meta">${detail}${comboBadge}</span>` +
    "</span>" +
    '<span class="history-side">' +
    `<span class="history-beads${beads > 0 ? "" : " zero"}">${beads > 0 ? "+" + Math.floor(beads) : "—"}</span>` +
    `<span class="history-time">${formatTime(session.completedAt)}</span>` +
    "</span>" +
    "</div>"
  );
}

function sentenceHistoryRow(session) {
  const beads = Number(session.beads || 0);
  const minutes = Math.round(Number(session.actualMinutes || 0));
  const detail =
    `${session.sentenceCount || 0} 句 · ${minutes} 分钟` +
    (session.exitEarly ? " · 提前结束" : "");
  const comboBadge =
    Number(session.comboBonus || 0) > 0
      ? `<span class="history-streak" style="color:var(--green-deep);background:var(--green-soft)">三练 +${session.comboBonus}</span>`
      : "";
  return (
    '<div class="history-row">' +
    `<span class="history-dot tone-green" aria-hidden="true">${uiIcon("sentence")}</span>` +
    '<span class="history-main">' +
    '<span class="history-name">句子练习</span>' +
    `<span class="history-meta">${detail}${comboBadge}</span>` +
    "</span>" +
    '<span class="history-side">' +
    `<span class="history-beads${beads > 0 ? "" : " zero"}">${beads > 0 ? "+" + Math.floor(beads) : "—"}</span>` +
    `<span class="history-time">${formatTime(session.completedAt)}</span>` +
    "</span>" +
    "</div>"
  );
}

function discrimHistoryRow(session) {
  const beads = Number(session.beads || 0);
  const minutes = Math.round(Number(session.actualMinutes || 0));
  const perfectBadge = session.perfect
    ? '<span class="history-streak" style="color:var(--violet-deep);background:var(--violet-soft)">✦ 全对</span>'
    : "";
  const detail =
    `正确 ${session.correctPoints || 0} / ${session.totalPoints || 0} 音节 · ${minutes} 分钟` +
    (session.exitEarly ? " · 提前结束" : "");
  const comboBadge =
    Number(session.comboBonus || 0) > 0
      ? `<span class="history-streak" style="color:var(--green-deep);background:var(--green-soft)">三练 +${session.comboBonus}</span>`
      : "";
  return (
    '<div class="history-row">' +
    `<span class="history-dot tone-violet" aria-hidden="true">${uiIcon("headphones")}</span>` +
    '<span class="history-main">' +
    '<span class="history-name">听辨练习</span>' +
    `<span class="history-meta">${detail}${perfectBadge}${comboBadge}</span>` +
    "</span>" +
    '<span class="history-side">' +
    `<span class="history-beads${beads > 0 ? "" : " zero"}">${beads > 0 ? "+" + Math.floor(beads) : "—"}</span>` +
    `<span class="history-time">${formatTime(session.completedAt)}</span>` +
    "</span>" +
    "</div>"
  );
}

function reviewHistoryRow(session) {
  const beads = Number(session.beads || 0);
  return (
    '<div class="history-row">' +
    `<span class="history-dot tone-orange" aria-hidden="true">${uiIcon("replay")}</span>` +
    '<span class="history-main">' +
    '<span class="history-name">错题复习</span>' +
    '<span class="history-meta">今日复习完成</span>' +
    "</span>" +
    '<span class="history-side">' +
    `<span class="history-beads${beads > 0 ? "" : " zero"}">${beads > 0 ? "+" + beads : "—"}</span>` +
    `<span class="history-time">${formatTime(session.completedAt)}</span>` +
    "</span>" +
    "</div>"
  );
}

function renderHistory() {
  const sessions = [...(state.progress.sessions || [])].reverse();
  if (!sessions.length) {
    els.historyBody.innerHTML =
      '<div class="wall-empty">' + uiMascot('welcome') + '<h3>从第一组练习开始</h3><p>每一次开口，都会留在这里。</p><button id="history-empty-start" class="primary-btn" type="button">去练一组</button></div>';
    document.getElementById('history-empty-start').addEventListener('click', resetToHome);
    return;
  }

  const stats = computeStats();
  const streak = computeStreak();
  const totalBeads = sessions.reduce((sum, s) => sum + Number(s.beads || 0), 0);
  let html =
    '<section class="history-summary">' +
    `<div class="history-summary-item"><span class="hs-value">${sessions.length}</span><span class="hs-label">训练组数</span></div>` +
    `<div class="history-summary-item"><span class="hs-value">${Math.round(stats.total)}</span><span class="hs-label">累计分钟</span></div>` +
    `<div class="history-summary-item"><span class="hs-value">${totalBeads}</span><span class="hs-label">拼点</span></div>` +
    `<div class="history-summary-item"><span class="hs-value">${streak.days}</span><span class="hs-label">连续天数</span></div>` +
    "</section>";

  const groups = new Map();
  sessions.forEach((session) => {
    const key = session.dayKey || "—";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(session);
  });
  const orderedDays = [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  orderedDays.forEach(([key, list]) => {
    const dayMinutes = list.reduce((sum, s) => sum + Number(s.actualMinutes || 0), 0);
    const dayBeads = list.reduce((sum, s) => sum + Number(s.beads || 0), 0);
    html +=
      '<section class="history-day">' +
      '<div class="history-day-head">' +
      `<span class="history-date">${formatDayLabel(key)}</span>` +
      `<span class="history-day-total">${Math.round(dayMinutes)} 分钟 · +${dayBeads} 拼点</span>` +
      "</div>" +
      '<div class="history-list">' +
      list.map(historyRow).join("") +
      "</div>" +
      "</section>";
  });

  els.historyBody.innerHTML = html;
}

/* ---------- 退出对话框 ---------- */

function showExitDialog(show) {
  if (show) sfx.stop();
  els.exitDialog.classList.toggle("hidden", !show);
}

/* ---------- 调试面板 ---------- */

function toggleDebug(force) {
  const open = force !== undefined ? force : els.debugPanel.classList.contains("hidden");
  els.debugPanel.classList.toggle("hidden", !open);
  if (open) syncDebugInputs();
}

function syncDebugInputs() {
  const t = timing();
  els.dbgExtra.value = t.extra_follow_sec;
  els.dbgMin.value = t.min_follow_sec;
  els.dbgTransition.value = t.transition_sec;
}

function updateDebug() {
  if (state.discrimSession) {
    const dItem = currentDiscrimItem();
    els.dbgProfile.textContent =
      state.discrimKind === "review" ? "错题复习" : "听辨练习";
    els.dbgSession.textContent = state.discrimSession.session_id;
    els.dbgSeed.textContent = "—";
    els.dbgItem.textContent = dItem ? dItem.item_id : "-";
    const dbgTotal = state.discrimKind === "library"
      ? (state.discrimSession.items ? state.discrimSession.items.length : 0)
      : (state.discrimQueue ? state.discrimQueue.length : 0);
    els.dbgIndex.textContent = `${state.discrimIndex + 1} / ${dbgTotal}`;
    els.dbgClip.textContent = "-";
    els.dbgEst.textContent = "-";
    els.dbgFinals.textContent = dItem
      ? (dItem.points || []).map((p) => p.pair).join(" ")
      : "-";
    if (!els.debugPanel.classList.contains("hidden")) syncDebugInputs();
    return;
  }
  if (state.sentenceSession) {
    const sItem = currentSentenceItem();
    els.dbgProfile.textContent = "句子练习";
    els.dbgSession.textContent = state.sentenceSession.session_id;
    els.dbgSeed.textContent = `filter=${state.sentenceFilter}`;
    els.dbgItem.textContent = sItem ? sItem.sentence_id : "-";
    els.dbgIndex.textContent = `${state.sentenceIndex + 1} / ${state.sentenceSession.items.length}`;
    els.dbgClip.textContent = sItem ? `${Math.round(sItem.clip_duration * 10) / 10}s` : "-";
    els.dbgEst.textContent = "-";
    els.dbgFinals.textContent = sItem ? sItem.label_seq : "-";
    if (!els.debugPanel.classList.contains("hidden")) syncDebugInputs();
    return;
  }
  const item = currentItem();
  const session = state.session;
  els.dbgProfile.textContent = session ? session.profile_id : "-";
  els.dbgSession.textContent = session ? session.session_id : "-";
  els.dbgSeed.textContent = session ? String(session.seed) : "-";
  els.dbgItem.textContent = item ? item.item_id : "-";
  els.dbgIndex.textContent = session ? `${state.index + 1} / ${session.items.length}` : "-";
  els.dbgClip.textContent = item ? `${Math.round(item.clip_duration_ms / 100) / 10}s` : "-";
  els.dbgEst.textContent = item ? `${item.estimated_item_duration_sec}s` : "-";
  els.dbgFinals.textContent =
    session && Array.isArray(session.include_finals)
      ? session.include_finals.join(" ") || "（全部）"
      : session
        ? "（全部）"
        : "-";
  if (!els.debugPanel.classList.contains("hidden")) syncDebugInputs();
}

/* ---------- 事件绑定 ---------- */

function bindEvents() {
  els.startBtn.addEventListener("click", () => {
    if (state.profileId) startSession(state.profileId, state.duration, state.entryId);
  });
  els.exitBtn.addEventListener("click", () => showExitDialog(true));
  els.continueBtn.addEventListener("click", () => showExitDialog(false));
  els.endBtn.addEventListener("click", () => {
    showExitDialog(false);
    finishSession(true);
  });
  els.exitDialog.addEventListener("click", (event) => {
    if (event.target === els.exitDialog) showExitDialog(false);
  });
  els.pauseBtn.addEventListener("click", togglePause);
  els.replayBtn.addEventListener("click", replay);
  els.wallLink.addEventListener("click", () => {
    setView("wall");
    renderWall();
  });
  els.wallBack.addEventListener("click", resetToHome);
  els.historyLink.addEventListener("click", () => {
    setView("history");
    renderHistory();
  });
  els.historyBack.addEventListener("click", resetToHome);
  els.filterOverlay.addEventListener("click", (event) => {
    if (event.target === els.filterOverlay) closeFilter();
  });
  els.detailOverlay.addEventListener("click", (event) => {
    if (event.target === els.detailOverlay) closeDetail();
  });
  els.calStop.addEventListener("click", () => stopCalVideos(`已停止 · ${calModeLabel()}`));
  document.querySelectorAll("[data-cal-speed]").forEach((btn) => {
    btn.addEventListener("click", () => setCalibrationSpeed(btn.dataset.calSpeed));
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopPlacement(); ironAudible = false; sfx.stop();
      if (["playing_reference", "waiting_follow"].includes(state.mode)) togglePause();
      if (["previewing", "playing", "following"].includes(state.sentenceMode)) toggleSentencePause();
      if (state.mode === "finishing") { reading.cancel(); setMode("error"); setStatus("已暂停，点重播继续"); }
      if (state.sentenceMode === "finishing") { reading.cancel(); setSentenceMode("error"); setSentenceStatus("已暂停，点重播继续"); }
      if (state.discrimMode === "feedback") {stopDiscrimVoice();state.discrimFeedbackTimeout=setTimeout(nextDiscrimWord,700);}
    }
    if (document.hidden && document.body.dataset.view === "calibration") stopCalVideos("已停止，点音名或箭头重新播放");
  });
  window.addEventListener("blur", () => { stopPlacement(); ironAudible = false; sfx.stop(); });
  window.addEventListener("pagehide", () => {stopCalVideos();reading.close();stopDiscrimVoice();});
  els.calLink.addEventListener("click", () => {
    setView("calibration");
    renderCalibration();
  });
  els.calBack.addEventListener("click", () => {
    stopCalVideos();
    resetToHome();
  });
  els.pickerOverlay.addEventListener("click", (event) => {
    if (event.target === els.pickerOverlay && state.pickerMode !== "first") closePicker();
  });

  // 首页三 Tab
  els.tabWords.addEventListener("click", () => setTab("words"));
  els.tabSentence.addEventListener("click", () => setTab("sentence"));
  els.tabDiscrim.addEventListener("click", () => setTab("discrim"));
  els.sentenceStartBtn.addEventListener("click", () => {
    startSentenceSession(state.sentenceFilter, state.sentenceCount);
  });
  els.discrimStartBtn.addEventListener("click", () => startLibraryPractice());
  els.discrimReviewBtn.addEventListener("click", () => startReviewPractice());
  // 反馈期轻触跳过：立即进入下一词
  els.discrimSkip.addEventListener("pointerdown", () => {
    if (state.discrimMode === "feedback" && state.discrimFeedbackTimeout) {
      clearTimeout(state.discrimFeedbackTimeout);
      nextDiscrimWord();
    }
  });

  // 句子练习
  els.sentencePinyinToggle.addEventListener("click", toggleSentencePinyin);
  els.sentenceExitBtn.addEventListener("click", () => {
    if (state.sentenceSession) finishSentenceSession(true);
    else resetToHome();
  });
  els.sentencePauseBtn.addEventListener("click", toggleSentencePause);
  els.sentenceReplayBtn.addEventListener("click", replaySentence);
  els.sentenceFilterOverlay.addEventListener("click", (event) => {
    if (event.target === els.sentenceFilterOverlay) closeSentenceFilter();
  });
  els.sentencePlayer.addEventListener("ended", () => {
    if (state.sentenceMode === "playing") enterSentenceFollow();
  });
  els.sentencePlayer.addEventListener("error", () => {
    if (["previewing", "playing", "paused"].includes(state.sentenceMode)) {
      clearTimeout(state.sentenceFollowTimeout);
      setSentenceMode("error");
      setSentenceStatus("无法播放，点重播重试");
    }
  });

  // 听辨练习
  els.discrimExitBtn.addEventListener("click", () => {
    if (state.discrimSession && state.discrimMode !== "completed") {
      finishDiscrimSessionEarly();
    } else resetToHome();
  });
  els.discrimFrontBtn.addEventListener("click", () => answerDiscrim("front"));
  els.discrimBackBtn.addEventListener("click", () => answerDiscrim("back"));

  els.player.addEventListener("ended", () => {
    if (state.mode === "playing_reference") enterFollow();
  });
  els.player.addEventListener("error", () => {
    if (state.mode === "playing_reference" || state.mode === "paused") {
      setMode("error");
      setStatus("无法播放，点重播重试");
    }
  });

  els.debugToggle.addEventListener("click", () => toggleDebug());
  els.debugClose.addEventListener("click", () => toggleDebug(false));
  [els.dbgExtra, els.dbgMin, els.dbgTransition].forEach((input) => {
    input.addEventListener("change", () => {
      saveTiming();
      syncDebugInputs();
    });
  });
  els.dbgReset.addEventListener("click", () => {
    localStorage.removeItem(TIMING_KEY);
    syncDebugInputs();
  });
  els.dbgSkip.addEventListener("click", () => {
    if (state.sentenceSession && state.sentenceMode !== "completed") {
      skipSentence();
      return;
    }
    skipCurrent();
  });
  els.dbgFinish.addEventListener("click", () => {
    if (state.session) finishSession(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key.toLowerCase() === "d" && !event.metaKey && !event.ctrlKey && !event.altKey) {
      toggleDebug();
    }
    if (event.key === "Escape") {
      toggleDebug(false);
      showExitDialog(false);
      closePicker();
      closeDetail();
      closeFilter();
      closeSentenceFilter();
    }
  });
}

/* ---------- 加载 ---------- */

async function pollReady() {
  try {
    const health = await fetchJson("/api/health");
    if (health.ready || health.warm_error) {
      els.readyHint.hidden = true;
      return;
    }
  } catch {
    /* server still booting; retry */
  }
  els.readyHint.hidden = false;
  els.readyHint.textContent = "语料准备中，请稍候…";
  setTimeout(pollReady, 1500);
}

// 首次进入 / 数据迁移：保证有且仅有一个「当前正在拼」作品。
// 新手期固定为「麦克风」（快速跑通 训练→得拼点→拼入→完成→收藏 闭环）；
// 之后所有作品全部明牌可选，随时可切换，进度永久保留。
function ensureCurrentArtwork() {
  const progress = state.progress;
  const current = progress.currentArtworkId ? artworkById(progress.currentArtworkId) : null;
  if (current) {
    const record = progress.artworks[current.artwork_id];
    if (!record || !record.completedAt) return; // 有效且未完成 → 保持
  }
  const pick = state.artworks.find((art) => {
    const record = progress.artworks[art.artwork_id];
    return !record || !record.completedAt;
  });
  if (pick) {
    progress.currentArtworkId = pick.artwork_id;
    const record = ensureArtRecord(pick.artwork_id);
    if (!record.startedAt) record.startedAt = new Date().toISOString();
  } else {
    progress.currentArtworkId = null;
  }
  progress.onboardingDone = true;
  earmarkPending();
  saveProgress();
}

let eventsBound = false;
async function init() {
  if (!eventsBound) { bindEvents(); eventsBound = true; }
  els.readyHint.hidden = false;
  els.readyHint.textContent = "正在准备练习…";
  setMode("idle");
  renderTimer();
  try {
    const [home, achievement, calibration] = await Promise.all([
      fetchJson("/api/home"),
      fetchJson("/api/achievement"),
      fetchJson("/api/calibration"),
    ]);
    state.home = home;
    state.achievement = achievement;
    state.artworks = achievement.artworks || [];
    state.calibration = calibration;
    state.duration = home.default_duration_minutes || 10;
    const firstEntry = home.entries?.[0];
    if (!state.entryId && firstEntry) {
      state.entryId = firstEntry.id;
      state.profileId = firstEntry.profile_id;
      state.profileLabel = firstEntry.label;
    }
    if (home.tagline) {
      /* 标语「听清 · 分清 · 读准」已从首页头部移除（2026-08-27），保留字段仅为兼容接口 */
    }
    ensureCurrentArtwork();
    renderEntries();
    renderDurations();
    renderSentenceDurations();
    renderStats();
    setTab("words");
    updateRewardHint();
    updateStartBtn();
    pollReady();
    fetchJson("/api/assessment/status").then(status => {
      if (!status.available) return;
      [els.startBtn, els.sentenceStartBtn].forEach(btn => {
        if (btn.parentElement.querySelector(".assessment-notice")) return;
        const notice = document.createElement("p"); notice.className = "assessment-notice";
        notice.textContent = "跟读时录音评测 · 录音发送至腾讯云";btn.after(notice);
      });
    }).catch(() => {});
    await migrateOldWrongBook();
    await refreshDiscrimState();
    if (new URLSearchParams(location.search).get("view") === "calibration") {
      setView("calibration");
      renderCalibration();
    }
  } catch (err) {
    els.readyHint.hidden = false;
    els.readyHint.textContent = "暂时没能加载练习，请稍后重试。";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.id = "home-retry-btn";
    retry.className = "ghost-btn";
    retry.textContent = "重新加载";
    retry.addEventListener("click", init);
    els.readyHint.appendChild(retry);
  }
}

uiInit(() => {
  if (!els.viewTraining.classList.contains("hidden")) return {
    kind: "word", mode: state.mode, audio: els.player,
    errorMessage: state.session ? "示范音暂时无法播放，请点重播再试" : "练习暂时没准备好，请点重播再试",
    deadline: state.followDeadline, total: state.uiFollowTotalMs,
  };
  if (!els.viewSentence.classList.contains("hidden")) return {
    kind: "sentence", mode: state.sentenceMode, audio: els.sentencePlayer,
    errorMessage: state.sentenceSession ? "示范音暂时无法播放，请点重播再试" : "练习暂时没准备好，请点重播再试",
    deadline: state.sentenceFollowDeadline, total: state.uiSentenceFollowTotalMs, pass: state.sentencePass,
  };
  return null;
});
els.completeBody.addEventListener("click", (event) => {
  const button = event.target.closest("[data-place-art]");
  if (button) openDetail(button.dataset.placeArt);
});
initReadingControls();
init();
