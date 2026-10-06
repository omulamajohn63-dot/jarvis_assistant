/*
  JARVIS DASHBOARD — API CLIENT
  ------------------------------
  Written against web/api/routes.py. The pinned shapes live in
  tests/v2/test_payloads.py; run it after you change anything here.

  Two rules this file follows without exception:
    1. No build step. Plain ES2020, no imports, no bundler, served as-is.
    2. textContent for anything the server sends. Jarvis replies with file
       names, search results and remembered facts, all of which are untrusted.
       Every node here is built with createElement, so nothing is ever parsed
       as markup, and server URLs are only made clickable when http(s).
*/
const API = {
  base: "",
  endpoints: {
    chat: "/api/chat",
    confirm: "/api/confirm",
    voice: "/api/voice",
    tts: "/api/tts",
    history: "/api/history",
    historyClear: "/api/history/clear",
    skills: "/api/skills",
    settings: "/api/settings",
    memory: "/api/memory",
    activity: "/api/activity",
    status: "/api/status",
    state: "/api/state"
  },
  async request(path, options = {}) {
    const init = { method: options.method || "GET", ...options };
    init.headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    const res = await fetch(this.base + path, init);
    if (!res.ok) {
      let detail = "";
      try {
        const body = await res.json();
        detail = body && body.error ? body.error : "";
      } catch (error) {
        detail = "";
      }
      throw new Error(detail || `API ${res.status}`);
    }
    return res.status === 204 ? null : res.json();
  }
};

const state = {
  busy: false,
  sound: true,
  confirming: null,
  view: "assistant",
  assistant: { name: "Jarvis", sampleRate: 16000, maxSeconds: 8 }
};

const $ = id => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

// A server value, flattened for a muted line. Booleans are rendered as
// yes/no rather than "true"/"false" so a false never reads like a true.
function describeValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.length ? `${value.length} item(s)` : "none";
  if (typeof value === "object") return Object.keys(value).length ? "details" : "none";
  const text = String(value);
  return text.length > 120 ? `${text.slice(0, 117)}...` : text;
}

// Only http(s) links from the server are made clickable.
function safeUrl(value) {
  const url = String(value || "").trim();
  return /^https?:\/\//i.test(url) ? url : "";
}

// ----------------------------------------------------------------------
// Conversation
// ----------------------------------------------------------------------
function messageNode(role, text) {
  const article = el("article", `message ${role}`);
  article.appendChild(el("div", "message-avatar", role === "assistant" ? "J" : "S"));
  const body = el("div", "message-body");
  body.appendChild(el("div", "message-meta", `${role === "assistant" ? "JARVIS" : "YOU"} · NOW`));
  if (text !== undefined && text !== null) body.appendChild(el("p", null, text));
  article.appendChild(body);
  return article;
}

function scrollChat() {
  const box = $("messages");
  if (box) box.scrollTop = box.scrollHeight;
}

function addMessage(role, text, meta) {
  const box = $("messages");
  const node = messageNode(role, text);
  if (meta) node.querySelector(".message-meta").textContent = meta;
  box.appendChild(node);
  scrollChat();
  return node;
}

function setTyping(on) {
  const box = $("messages");
  if (!box) return;
  const existing = $("typingIndicator");
  if (!on) {
    if (existing) existing.remove();
    return;
  }
  if (existing) return;
  const node = messageNode("assistant", null);
  node.id = "typingIndicator";
  node.querySelector(".message-meta").textContent = "JARVIS · THINKING";
  const dots = el("p", "typing");
  dots.append(el("i"), el("i"), el("i"));
  node.querySelector(".message-body").appendChild(dots);
  box.appendChild(node);
  scrollChat();
}

function renderChoices(choices, body) {
  if (!Array.isArray(choices) || !choices.length) return;
  const list = el("div", "choice-list");
  choices.forEach(choice => {
    const row = el("button", "choice-row");
    row.type = "button";
    row.appendChild(el("span", "choice-n", choice.n));
    const text = el("span", "choice-text");
    text.appendChild(el("strong", null, choice.label));
    if (choice.detail) text.appendChild(el("small", null, choice.detail));
    row.appendChild(text);
    row.addEventListener("click", () => sendCommand(String(choice.n)));
    list.appendChild(row);
  });
  body.appendChild(list);
}

function renderArticle(article, body) {
  if (!article || !article.title) return;
  const card = el("a", "article-card");
  const url = safeUrl(article.url);
  card.href = url || "#";
  if (url) {
    card.target = "_blank";
    card.rel = "noopener noreferrer";
  }
  card.appendChild(el("strong", null, article.title));
  if (url) card.appendChild(el("small", null, url));
  body.appendChild(card);
}

function renderNotes(reply, body) {
  const notes = [];
  (reply.opened || []).forEach(item => notes.push(`opened ${item}`));
  (reply.actions || []).forEach(item => notes.push(describeValue(item)));
  if (!notes.length) return;
  body.appendChild(el("p", "reply-notes", notes.join(" · ")));
}

function renderSources(sources, body) {
  if (!Array.isArray(sources) || !sources.length) return;
  const box = el("div", "reply-sources");
  sources.forEach(source => {
    const url = safeUrl(source && source.url);
    const label = (source && source.title) || url;
    if (!label) return;
    if (!url) {
      box.appendChild(el("span", "source-link", label));
      return;
    }
    const link = el("a", "source-link", label);
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    box.appendChild(link);
  });
  if (box.children.length) body.appendChild(box);
}

function renderReply(reply) {
  if (!reply) return;
  if (reply.error) {
    addMessage("assistant", String(reply.error), "JARVIS · ERROR");
    return;
  }
  const text = reply.text || reply.question || "";
  const node = addMessage("assistant", text);
  const meta = node.querySelector(".message-meta");
  if (typeof reply.took === "number" && reply.took > 0) {
    meta.textContent = `JARVIS · ${Math.round(reply.took * 1000)}MS`;
  }
  const body = node.querySelector(".message-body");
  (reply.lines || []).forEach(line => body.appendChild(el("p", "reply-line", line)));
  renderChoices(reply.choices, body);
  renderArticle(reply.metadata && reply.metadata.article, body);
  renderNotes(reply, body);
  renderSources(reply.sources, body);
  if (reply.prompt) addMessage("assistant", String(reply.prompt));

  const pending = (reply.choices || []).length;
  setEyebrow(pending ? `${pending} OPTION${pending > 1 ? "S" : ""} WAITING` : "SYSTEM ONLINE");
  if (reply.confirmation) openConfirmation(reply.confirmation);
  if (text) speak(text);
}

async function sendCommand(text) {
  text = String(text || "").trim();
  if (!text || state.busy) return;
  state.busy = true;
  addMessage("user", text);
  $("commandInput").value = "";
  setTyping(true);
  try {
    const reply = await API.request(API.endpoints.chat, {
      method: "POST",
      body: JSON.stringify({ text })
    });
    renderReply(reply);
  } catch (error) {
    addMessage("assistant", `No reply from Jarvis: ${error.message}`, "JARVIS · ERROR");
  } finally {
    setTyping(false);
    state.busy = false;
  }
}

async function loadHistory() {
  try {
    const data = await API.request(`${API.endpoints.history}?limit=50`);
    const turns = (data && data.turns) || [];
    if (!turns.length) return;
    const box = $("messages");
    box.replaceChildren();
    turns.forEach(turn => {
      addMessage("user", turn.request);
      addMessage("assistant", turn.reply);
    });
  } catch (error) {
    // Nothing recorded yet, or the page loaded before the assistant was ready.
  }
}

// ----------------------------------------------------------------------
// Confirmations
// ----------------------------------------------------------------------
function openConfirmation(question) {
  if (!question || !question.id) return;
  state.confirming = question;
  $("confirmTitle").textContent = question.prompt || "Are you sure?";
  const parts = [];
  if (question.action) parts.push(question.action);
  if (question.risk) parts.push(`${question.risk} risk`);
  $("confirmText").textContent = parts.join(" · ") || "This action can change your system.";
  $("confirmModal").classList.remove("hidden");
}

async function resolveConfirmation(approved) {
  const question = state.confirming;
  state.confirming = null;
  $("confirmModal").classList.add("hidden");
  if (!question) return;
  setTyping(true);
  try {
    const reply = await API.request(API.endpoints.confirm, {
      method: "POST",
      body: JSON.stringify({ id: question.id, approved })
    });
    renderReply(reply);
  } catch (error) {
    addMessage("assistant", `Could not answer that: ${error.message}`, "JARVIS · ERROR");
  } finally {
    setTyping(false);
  }
}

// ----------------------------------------------------------------------
// Voice: hold to talk, then read the reply out
// ----------------------------------------------------------------------
const mic = { active: false, ctx: null, stream: null, node: null, chunks: [], timer: null };

function setLevel(level) {
  document.body.style.setProperty("--mic-level", String(level));
}

function setListening(active) {
  document.body.classList.toggle("listening", active);
  $("listeningState").textContent = active ? "LISTENING" : "READY";
  $("orbHint").textContent = active ? "Release to send" : "Press and hold to talk";
  $("talkText").textContent = active ? "Listening..." : "Hold to talk";
}

function voiceFailed(reason) {
  setListening(false);
  addMessage("assistant", reason, "JARVIS · VOICE");
}

async function startListening() {
  if (mic.active || state.busy) return;
  const devices = navigator.mediaDevices;
  if (!devices || !devices.getUserMedia) {
    voiceFailed("This browser will not give the page a microphone.");
    return;
  }
  try {
    mic.stream = await devices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
    });
  } catch (error) {
    voiceFailed("The microphone was not available.");
    return;
  }

  const Ctx = window.AudioContext || window.webkitAudioContext;
  const rate = state.assistant.sampleRate || 16000;
  mic.chunks = [];
  mic.ctx = new Ctx({ sampleRate: rate });
  await mic.ctx.resume().catch(() => {});

  const source = mic.ctx.createMediaStreamSource(mic.stream);
  const silent = mic.ctx.createGain();
  silent.gain.value = 0;
  const create = mic.ctx.createScriptProcessor || mic.ctx.createJavaScriptNode;
  mic.node = create.call(mic.ctx, 4096, 1, 1);
  mic.node.onaudioprocess = event => {
    const input = event.inputBuffer.getChannelData(0);
    const pcm = new Int16Array(input.length);
    let sum = 0;
    for (let i = 0; i < input.length; i++) {
      const sample = Math.max(-1, Math.min(1, input[i]));
      pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      sum += sample * sample;
    }
    mic.chunks.push(pcm);
    setLevel(Math.min(1, Math.sqrt(sum / input.length) * 6));
  };
  source.connect(mic.node);
  mic.node.connect(silent);
  silent.connect(mic.ctx.destination);

  mic.active = true;
  setListening(true);
  const limit = (state.assistant.maxSeconds || 8) * 1000;
  mic.timer = setTimeout(stopListening, limit);
}

async function stopListening() {
  if (!mic.active) return;
  mic.active = false;
  clearTimeout(mic.timer);
  setListening(false);
  setLevel(0);
  if (mic.node) mic.node.onaudioprocess = null;
  if (mic.stream) mic.stream.getTracks().forEach(track => track.stop());
  if (mic.ctx) mic.ctx.close().catch(() => {});
  mic.node = null;
  mic.stream = null;
  mic.ctx = null;

  const frames = mic.chunks;
  mic.chunks = [];
  const total = frames.reduce((sum, chunk) => sum + chunk.length, 0);
  if (total < 1600) return;

  const pcm = new Int16Array(total);
  let at = 0;
  frames.forEach(chunk => {
    pcm.set(chunk, at);
    at += chunk.length;
  });

  state.busy = true;
  setTyping(true);
  try {
    const res = await fetch(API.base + API.endpoints.voice, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: pcm.buffer
    });
    renderReply(await res.json());
  } catch (error) {
    voiceFailed("That recording did not reach Jarvis.");
  } finally {
    setTyping(false);
    state.busy = false;
  }
}

async function speak(text) {
  if (!state.sound || !text || text.length > 2000) return;
  try {
    const res = await fetch(API.base + API.endpoints.tts, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    if (!res.ok) return;
    const url = URL.createObjectURL(await res.blob());
    const audio = new Audio(url);
    audio.addEventListener("ended", () => URL.revokeObjectURL(url));
    await audio.play().catch(() => {});
  } catch (error) {
    // No speech engine, or the browser blocked playback. Text is enough.
  }
}

// ----------------------------------------------------------------------
// Panels
// ----------------------------------------------------------------------
function eventIcon(name) {
  if (!name) return "•";
  if (name === "tool_failed" || name === "error") return "!";
  if (name === "tool_completed" || name === "assistant_response") return "✓";
  if (name === "confirmation_required") return "?";
  if (name === "memory_saved") return "◇";
  return "•";
}

function renderActivity(entries) {
  const list = $("activityList");
  if (!list) return;
  list.replaceChildren();
  if (!entries.length) {
    list.appendChild(el("div", "empty", "No activity yet."));
    return;
  }
  entries
    .slice()
    .reverse()
    .forEach(entry => {
      const row = el("div", "activity-row");
      row.appendChild(el("span", "activity-icon", eventIcon(entry.event)));
      const body = el("div");
      body.appendChild(el("strong", null, entry.event));
      const details = Object.keys(entry)
        .filter(key => key !== "event")
        .map(key => `${key}: ${describeValue(entry[key])}`)
        .join(" · ");
      body.appendChild(el("small", null, details || "—"));
      row.appendChild(body);
      list.appendChild(row);
    });
}

async function loadActivity() {
  try {
    const data = await API.request(API.endpoints.activity);
    renderActivity((data && data.recent) || []);
  } catch (error) {
    // The panel stays as it was.
  }
}

function skillCard(name, description, risk, actions) {
  const card = el("div", "skill-card");
  const head = el("div", "skill-head");
  head.appendChild(el("strong", null, name));
  if (risk) {
    const chip = el("span", "skill-risk", risk);
    chip.dataset.risk = risk;
    head.appendChild(chip);
  }
  card.appendChild(head);
  if (description) card.appendChild(el("p", null, description));
  if (Array.isArray(actions) && actions.length) {
    card.appendChild(el("small", "skill-actions", actions.map(describeValue).join(" · ")));
  }
  return card;
}

async function loadSkills() {
  const grid = $("skillGrid");
  if (!grid) return;
  try {
    const data = await API.request(API.endpoints.skills);
    grid.replaceChildren();
    (data.skills || []).forEach(skill =>
      grid.appendChild(skillCard(skill.name, skill.description, skill.risk, skill.actions))
    );
    const steps = (data.automation && data.automation.steps) || [];
    steps.forEach(step =>
      grid.appendChild(skillCard(step.name, step.description, step.risk, [step.argument]))
    );
    if (!grid.children.length) {
      grid.appendChild(el("div", "empty", "No skills returned by the backend."));
    }
  } catch (error) {
    grid.replaceChildren(el("div", "empty", "Could not reach /api/skills."));
  }
}

async function loadMemory() {
  const list = $("memoryList");
  if (!list) return;
  try {
    const data = await API.request(API.endpoints.memory);
    const facts = (data && data.facts) || [];
    list.replaceChildren();
    if (!facts.length) {
      list.appendChild(
        el("div", "empty", data && data.enabled === false ? "Memory is switched off." : "Nothing remembered yet.")
      );
      return;
    }
    facts.forEach(fact => {
      const row = el("div", "activity-row");
      row.appendChild(el("span", "activity-icon", "◇"));
      const body = el("div");
      body.appendChild(el("strong", null, fact.key || fact.value));
      if (fact.key && fact.value) body.appendChild(el("small", null, fact.value));
      if (fact.at) body.appendChild(el("small", null, new Date(fact.at * 1000).toLocaleString()));
      row.appendChild(body);
      list.appendChild(row);
    });
  } catch (error) {
    list.replaceChildren(el("div", "empty", "Could not reach /api/memory."));
  }
}

const TOGGLES = [
  { id: "voiceSetting", key: "voiceEnabled" },
  { id: "wakeSetting", key: "wakeWordEnabled" },
  { id: "memorySetting", key: "memoryEnabled" },
  { id: "confirmSetting", key: "confirmDangerousActions" }
];

async function loadSettings() {
  try {
    const data = await API.request(API.endpoints.settings);
    TOGGLES.forEach(toggle => {
      const box = $(toggle.id);
      if (box && typeof data[toggle.key] === "boolean") box.checked = data[toggle.key];
    });
    if (data.assistantName) state.assistant.name = data.assistantName;
  } catch (error) {
    // Leave the controls as they are.
  }
}

async function updateSetting(key, value) {
  try {
    await API.request(API.endpoints.settings, {
      method: "POST",
      body: JSON.stringify({ [key]: value })
    });
    if (key === "memoryEnabled" && value === false) loadMemory();
  } catch (error) {
    addMessage("assistant", `Could not change that setting: ${error.message}`, "JARVIS · ERROR");
    loadSettings();
  }
}

async function loadStatus() {
  try {
    const data = await API.request(API.endpoints.status);
    if (!data) return;
    state.assistant.name = data.name || state.assistant.name;
    document.title = `${state.assistant.name} — Personal Assistant`;
    const name = $("connectionText");
    if (name) name.textContent = state.assistant.name;
    const host = document.querySelector(".connection-card small");
    if (host) {
      const parts = [`${describeValue(data.skills)} skills`];
      if (data.aiProvider) parts.push(String(data.aiProvider));
      parts.push(location.host || "127.0.0.1");
      host.textContent = parts.join(" · ");
    }
  } catch (error) {
    // The assistant is still starting, or the page is opened on its own.
  }
}

async function pollState() {
  try {
    const data = await API.request(API.endpoints.state);
    if (!data) return;
    if (data.sampleRate) state.assistant.sampleRate = data.sampleRate;
    if (data.maxSeconds) state.assistant.maxSeconds = data.maxSeconds;
    if (data.name) state.assistant.name = data.name;
    if (data.confirmation && !state.confirming) openConfirmation(data.confirmation);
    if (data.pending && data.pending.count && !state.busy) {
      setEyebrow(`${data.pending.count} OPTION${data.pending.count > 1 ? "S" : ""} WAITING`);
    }
  } catch (error) {
    // Between polls nothing is known; leave the last state on screen.
  }
}

// ----------------------------------------------------------------------
// Views
// ----------------------------------------------------------------------
function setEyebrow(text) {
  const eyebrow = $("viewEyebrow");
  if (eyebrow) eyebrow.textContent = text;
}

function greeting() {
  const hour = new Date().getHours();
  const part = hour < 12 ? "Good morning" : hour < 16 ? "Good afternoon" : "Good evening";
  // The configured name rather than a fixed word, since anyone can rename it.
  return `${part}. How can I help?`;
}

function showView(name) {
  state.view = name;
  document.querySelectorAll(".view").forEach(view => view.classList.remove("active"));
  const target = $(`${name}View`);
  if (target) target.classList.add("active");
  document.querySelectorAll(".nav-item").forEach(item => item.classList.remove("active"));
  document.querySelectorAll(`[data-view="${name}"]`).forEach(item => item.classList.add("active"));
  $("viewTitle").textContent =
    name === "assistant"
      ? greeting()
      : name[0].toUpperCase() + name.slice(1);
  if (name !== "assistant") setEyebrow("SYSTEM ONLINE");
  if (name === "activity") loadActivity();
  if (name === "skills") loadSkills();
  if (name === "memory") loadMemory();
  if (name === "settings") loadSettings();
  if (name === "assistant") scrollChat();
}

// ----------------------------------------------------------------------
// Wiring
// ----------------------------------------------------------------------
$("composer").addEventListener("submit", event => {
  event.preventDefault();
  sendCommand($("commandInput").value);
});

document.querySelectorAll(".quick-actions button").forEach(button =>
  button.addEventListener("click", () => sendCommand(button.dataset.command))
);

document.querySelectorAll("[data-view]").forEach(button =>
  button.addEventListener("click", () => showView(button.dataset.view))
);

TOGGLES.forEach(toggle => {
  const box = $(toggle.id);
  if (box) box.addEventListener("change", () => updateSetting(toggle.key, box.checked));
});

$("clearChat").onclick = async () => {
  $("messages").replaceChildren();
  setEyebrow("SYSTEM ONLINE");
  try {
    await API.request(API.endpoints.historyClear, { method: "POST" });
  } catch (error) {
    // The transcript is cleared on screen either way.
  }
};

$("soundToggle").onclick = () => {
  state.sound = !state.sound;
  $("soundToggle").textContent = state.sound ? "◉" : "○";
};

$("cancelConfirm").onclick = () => resolveConfirmation(false);
$("approveConfirm").onclick = () => resolveConfirmation(true);

$("clearMemory").onclick = async () => {
  if (!confirm("Clear Jarvis memory?")) return;
  try {
    await API.request(API.endpoints.memory, { method: "DELETE" });
    $("memoryList").replaceChildren(el("div", "empty", "Memory cleared."));
  } catch (error) {
    $("memoryList").replaceChildren(el("div", "empty", error.message));
  }
};

const talk = $("talkButton");
talk.addEventListener("pointerdown", event => {
  event.preventDefault();
  startListening();
});
["pointerup", "pointercancel", "pointerleave"].forEach(name =>
  talk.addEventListener(name, stopListening)
);
talk.addEventListener("keydown", event => {
  if (event.key === " " || event.key === "Enter") {
    event.preventDefault();
    startListening();
  }
});
talk.addEventListener("keyup", event => {
  if (event.key === " " || event.key === "Enter") stopListening();
});

window.addEventListener("pointerup", () => {
  if (mic.active) stopListening();
});

// Boot: status and state are asked for once, then state is polled.
loadStatus();
loadSettings();
loadHistory();
pollState();
setInterval(pollState, 2500);
setInterval(() => {
  if (state.view === "activity") loadActivity();
}, 3000);