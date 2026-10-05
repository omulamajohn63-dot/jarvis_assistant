"use strict";

/**
 * The browser half of Jarvis. Everything it knows comes from the server, so
 * the page never decides what a command means.
 */

const el = {
  log: document.getElementById("log"),
  form: document.getElementById("form"),
  input: document.getElementById("input"),
  mic: document.getElementById("mic"),
  level: document.getElementById("level"),
  results: document.getElementById("results"),
  article: document.getElementById("article"),
  articlePanel: document.getElementById("articlePanel"),
  console: document.getElementById("console"),
  chips: document.getElementById("chips"),
  orb: document.getElementById("orb"),
  tag: document.getElementById("tagline"),
  title: document.getElementById("title"),
  mute: document.getElementById("mute"),
  stop: document.getElementById("stop"),
  volume: document.getElementById("volume"),
};

const state = {
  rate: 16000,
  maxSeconds: 12,
  muted: false,
  volume: 0.8,
  busy: false,
};

const DANGEROUS = /\b(shutdown|restart)\b/;

const CHIPS = [
  "what is python",
  "who is einstein",
  "what is the time",
  "what is the date",
  "tell me a joke",
  "open my cv",
  "read my cv",
  "open informatics",
  "read book1",
  "open chrome",
  "play oh jah",
  "screenshot",
];

/* ------------------------------------------------------------------ audio */

let queue = [];
let playing = false;

function speak(text) {
  if (!text || state.muted || state.volume === 0) return;
  queue.push(text);
  if (!playing) next();
}

function next() {
  const text = queue.shift();
  if (!text) { playing = false; return; }
  playing = true;

  fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  })
    .then((response) => (response.ok ? response.blob() : Promise.reject()))
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.volume = state.volume;
      audio.onended = () => { URL.revokeObjectURL(url); next(); };
      audio.onerror = () => { URL.revokeObjectURL(url); next(); };
      audio.play().catch(next);
    })
    .catch(next);
}

/** Stops talking at once and forgets anything still queued. */
function hush() {
  queue = [];
}

/* ---------------------------------------------------------------- typing */

// How long a reply takes to type out. Short answers stay quick and long ones
// do not crawl, so the time is scaled to the length rather than per character.
const TYPING_FLOOR_MS = 700;
const TYPING_CEILING_MS = 4000;

// Someone who has asked their system for less motion gets the whole reply at
// once instead.
const CALM =
  window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let typing = null;

/** Reveals text a character at a time. Click the bubble to skip to the end. */
function typeInto(bubble, text, onDone) {
  // Only one reply types at a time, so a new command finishes the last one
  // rather than leaving half a sentence on screen.
  if (typing) typing.finish();
  if (CALM) return finishNow(bubble, text, onDone);

  const characters = Array.from(text);
  if (characters.length < 2) return finishNow(bubble, text, onDone);

  const total = Math.min(
    TYPING_CEILING_MS,
    Math.max(TYPING_FLOOR_MS, characters.length * 24)
  );
  const started = performance.now();
  let shown = 0;
  let frame = 0;
  let done = false;

  function finish() {
    if (done) return;
    done = true;
    cancelAnimationFrame(frame);
    bubble.classList.remove("typing");
    bubble.textContent = text;
    typing = null;
    if (onDone) onDone();
  }

  function step(now) {
    const progress = Math.min(1, (now - started) / total);
    const count = Math.round(progress * characters.length);
    if (count !== shown) {
      shown = count;
      bubble.textContent = characters.slice(0, count).join("");
    }
    if (progress >= 1) return finish();
    frame = requestAnimationFrame(step);
  }

  typing = { finish };
  bubble.classList.add("typing");
  bubble.addEventListener("click", finish, { once: true });
  frame = requestAnimationFrame(step);
  return undefined;
}

function finishNow(bubble, text, onDone) {
  bubble.textContent = text;
  if (onDone) onDone();
  return undefined;
}

/* -------------------------------------------------------------- transcript */

function say(who, text, kind) {
  const bubble = document.createElement("div");
  bubble.className = "bubble " + (kind || who);
  el.log.appendChild(bubble);
  el.log.scrollTop = el.log.scrollHeight;

  const typed = who !== "you";
  if (!typed) bubble.textContent = text;
  else typeInto(bubble, text);
  return bubble;
}

/* ---------------------------------------------------------------- results */

function showResults(view) {
  el.results.replaceChildren();

  if (!view) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "Nothing found yet. Say “open my cv”.";
    el.results.appendChild(p);
    return;
  }

  const head = document.createElement("p");
  head.className = "empty";
  head.textContent =
    view.total + " match" + (view.total === 1 ? "" : "es") +
    " for “" + view.query + "” on " + view.drives.join(", ");
  el.results.appendChild(head);

  let group = null;
  let key = null;
  view.rows.forEach((row) => {
    // A list of articles has no drive or folder, so it gets no heading.
    const here = row.drive || row.folder ? row.drive + "|" + row.folder : "";
    if (here !== key) {
      key = here;
      group = document.createElement("div");
      group.className = "group";
      if (here) {
        const title = document.createElement("h3");
        title.textContent = row.drive + "  " + row.folder;
        group.appendChild(title);
      }
      el.results.appendChild(group);
    }

    const button = document.createElement("button");
    button.className = "row";
    button.title = row.path;

    const number = document.createElement("span");
    number.className = "n";
    number.textContent = row.n;

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = row.label;

    const meta = document.createElement("span");
    meta.className = "meta";
    // A list of articles has no file type or size to show.
    if (row.ext || row.size) meta.textContent = row.ext + " · " + row.size;

    button.append(number, name);
    if (row.ext || row.size) button.appendChild(meta);
    button.addEventListener("click", () => send(String(row.n)));
    group.appendChild(button);
  });

  if (view.remaining > 0) {
    const more = document.createElement("button");
    more.className = "more";
    more.textContent = "… " + view.remaining + " more — show more";
    more.addEventListener("click", () => send("more"));
    el.results.appendChild(more);
  }
}

function showArticle(lookup) {
  // Only the newest article is kept, so an old one cannot be mistaken for the
  // answer to the question just asked.
  el.article.replaceChildren();
  el.articlePanel.hidden = !lookup;
  if (!lookup) return;

  const title = document.createElement("h4");
  title.textContent = lookup.title;

  const body = document.createElement("p");
  body.textContent = lookup.summary;

  const link = document.createElement("a");
  link.href = lookup.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "Read more on Wikipedia";

  el.article.append(title, body, link);
}

function markOpened(paths) {
  if (!paths.length) return;
  const wanted = new Set(paths.map((p) => p.toLowerCase()));
  el.results.querySelectorAll(".row").forEach((row) => {
    if (wanted.has(row.title.toLowerCase())) row.classList.add("opened");
  });
}

/* --------------------------------------------------------------- commands */

function busy(on) {
  state.busy = on;
  el.orb.classList.toggle("busy", on);
  el.tag.textContent = on ? "working" : "ready";
}

async function send(text) {
  text = (text || "").trim().toLowerCase();
  if (!text || state.busy) return;

  if (DANGEROUS.test(text) &&
      !window.confirm("That will " + text + " this computer. Go ahead?")) {
    return;
  }

  say("you", text);
  el.input.value = "";
  busy(true);
  hush();

  try {
    const response = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await response.json();

    if (!response.ok) {
      say("jarvis", data.error || "Something went wrong.", "jarvis error");
      return;
    }
    if (data.prompt) {
      await askName(data.prompt);
      return;
    }
    if (data.text) say("jarvis", data.text);
    else say("jarvis", "Okay.", "jarvis note");

    el.console.textContent = (data.lines || []).join("\n");
    showResults(data.results);
    showArticle(data.lookup);
    markOpened(data.opened || []);

    if (data.text) speak(data.text);
    if (data.stop) window.setTimeout(shut, 900);
  } catch (error) {
    say("jarvis", "Lost the connection to Jarvis.", "jarvis error");
  } finally {
    busy(false);
  }
}

async function askName(prompt) {
  say("jarvis", prompt);
  const name = window.prompt(prompt);
  if (name === null) {
    say("you", "never mind", "you");
    return;
  }
  say("you", name.trim());
  if (!name.trim()) return;

  busy(true);
  try {
    const response = await fetch("/api/name", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    const data = await response.json();
    say("jarvis", data.text || data.error, data.error ? "jarvis error" : "jarvis");
    if (data.text) {
      el.title.textContent = name.trim();
      speak(data.text);
    }
  } finally {
    busy(false);
  }
}

async function shut() {
  say("jarvis", "Closing the interface. Start it again with python webapp.py.",
      "jarvis note");
  try {
    await fetch("/api/shutdown", { method: "POST" });
  } catch (error) { /* the server stops mid response, which is expected */ }
}

/* ----------------------------------------------------------- microphone */

const mic = {
  stream: null,
  context: null,
  source: null,
  processor: null,
  analyser: null,
  chunks: [],
  timer: null,
  frames: 0,
  rate: 0,
};

async function startListening() {
  if (mic.stream || state.busy) return;

  try {
    mic.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  } catch (error) {
    say("jarvis",
        "I could not reach the microphone. Check the browser's permission.",
        "jarvis error");
    return;
  }

  mic.context = new (window.AudioContext || window.webkitAudioContext)();
  // The rate the microphone gave us is usually 44.1 or 48 kHz, and it has to
  // be remembered because the context is torn down before the audio is
  // converted.
  mic.rate = mic.context.sampleRate;
  mic.source = mic.context.createMediaStreamSource(mic.stream);
  mic.analyser = mic.context.createAnalyser();
  mic.analyser.fftSize = 1024;
  mic.source.connect(mic.analyser);

  mic.chunks = [];
  mic.frames = 0;
  mic.processor = mic.context.createScriptProcessor(4096, 1, 1);
  mic.processor.onaudioprocess = (event) => {
    // The input buffer is reused every callback, so it has to be copied.
    mic.chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    mic.frames += event.inputBuffer.length;
  };

  // Chrome only pumps a node that reaches the destination, but the graph is
  // muted so nothing is played back while recording.
  const mute = mic.context.createGain();
  mute.gain.value = 0;
  mic.source.connect(mic.processor);
  mic.processor.connect(mute);
  mute.connect(mic.context.destination);

  mic.timer = window.setInterval(watch, 60);
  el.mic.classList.add("live");
  el.orb.classList.add("listening");
  el.tag.textContent = "listening — release to send";
}

function watch() {
  const data = new Uint8Array(mic.analyser.fftSize);
  mic.analyser.getByteTimeDomainData(data);

  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    const value = (data[i] - 128) / 128;
    sum += value * value;
  }
  const rms = Math.sqrt(sum / data.length);
  el.level.style.width = Math.min(100, rms * 320) + "%";

  if (mic.frames / mic.rate >= state.maxSeconds) stopListening();
}

function stopListening() {
  if (!mic.stream) return;

  window.clearInterval(mic.timer);
  const seconds = mic.frames / mic.rate;
  const chunks = mic.chunks;
  const rate = mic.rate;

  if (mic.processor) { mic.processor.disconnect(); mic.processor.onaudioprocess = null; }
  mic.stream.getTracks().forEach((track) => track.stop());
  if (mic.context && mic.context.state !== "closed") mic.context.close().catch(() => {});

  mic.stream = null;
  mic.processor = null;
  mic.context = null;
  mic.analyser = null;
  mic.rate = 0;

  el.mic.classList.remove("live");
  el.orb.classList.remove("listening");
  el.level.style.width = "0";
  el.tag.textContent = "ready";

  if (seconds < 0.2) {  // too short to hold a word
    say("jarvis", "I did not hear anything.", "jarvis note");
    return;
  }
  upload(encode(chunks, rate));
}

/** Mixes the recorded chunks, resamples to 16 kHz and packs them as PCM16. */
function encode(chunks, rate) {
  const merged = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let at = 0;
  chunks.forEach((chunk) => { merged.set(chunk, at); at += chunk.length; });

  const resampled = rate && rate !== state.rate
    ? resampleTo(merged, rate, state.rate)
    : merged;

  const pcm = new Int16Array(resampled.length);
  for (let i = 0; i < resampled.length; i++) {
    const sample = Math.max(-1, Math.min(1, resampled[i]));
    pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return pcm.buffer;
}

/** Linear resampling, which is good enough for speech recognition. */
function resampleTo(input, from, to) {
  const ratio = from / to;
  const length = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    const position = i * ratio;
    const index = Math.floor(position);
    const rest = position - index;
    const a = input[index] || 0;
    const b = input[index + 1] !== undefined ? input[index + 1] : a;
    output[i] = a + (b - a) * rest;
  }
  return output;
}

async function upload(pcm) {
  busy(true);
  try {
    const response = await fetch("/api/listen", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: pcm,
    });
    const data = await response.json();
    if (!data.text) {
      say("jarvis", data.error || "Sorry, I did not understand that.", "jarvis note");
      return;
    }
    await send(data.text);
  } catch (error) {
    say("jarvis", "I could not send that recording.", "jarvis error");
  } finally {
    busy(false);
  }
}

/* ------------------------------------------------------------------ setup */

el.form.addEventListener("submit", (event) => {
  event.preventDefault();
  send(el.input.value);
});

el.mic.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  // Capturing the pointer means the release is still seen even if the cursor
  // has wandered off the button.
  el.mic.setPointerCapture(event.pointerId);
  startListening();
});
["pointerup", "pointercancel"].forEach((name) => {
  el.mic.addEventListener(name, stopListening);
});
el.mic.addEventListener("keydown", (event) => {
  if ((event.key === " " || event.key === "Enter") && !event.repeat) startListening();
});
el.mic.addEventListener("keyup", stopListening);

el.volume.addEventListener("input", () => {
  state.volume = Number(el.volume.value) / 100;
  if (player && player.audio) player.audio.volume = state.volume;
});

el.mute.addEventListener("click", () => {
  state.muted = !state.muted;
  el.mute.textContent = state.muted ? "sound off" : "sound on";
  if (state.muted) hush();
});

el.stop.addEventListener("click", shut);

CHIPS.forEach((text) => {
  const chip = document.createElement("button");
  chip.textContent = text;
  chip.addEventListener("click", () => send(text));
  el.chips.appendChild(chip);
});

fetch("/api/state")
  .then((r) => r.json())
  .then((data) => {
    state.rate = data.sampleRate || state.rate;
    state.maxSeconds = data.maxSeconds || state.maxSeconds;
    el.title.textContent = data.name || "Jarvis";
    say("jarvis", "Ready. Hold the microphone and speak, or type below.");
  })
  .catch(() => say("jarvis", "Could not reach Jarvis on the server.", "jarvis error"));

if (!navigator.mediaDevices) {
  el.mic.classList.add("dead");
  el.mic.title = "This browser cannot record audio";
}