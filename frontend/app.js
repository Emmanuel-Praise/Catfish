const state = {
  participants: [],
  activeParticipantId: null,
  conversationId: null,
  lastMessageId: 0,
  sending: false,
  pollTimer: null,
};

const $ = (id) => document.getElementById(id);

const els = {
  list: $("participantList"),
  messages: $("messages"),
  empty: $("emptyState"),
  input: $("input"),
  send: $("sendBtn"),
  typing: $("typing"),
  chatName: $("chatName"),
  chatMeta: $("chatMeta"),
  chatAvatar: $("chatAvatar"),
  proactive: $("proactiveBtn"),
  memory: $("memoryBtn"),
  toast: $("toast"),
  llmStatus: $("llmStatus"),
};

function toast(text) {
  els.toast.textContent = text;
  els.toast.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => els.toast.classList.add("hidden"), 3200);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function initials(name) {
  return name
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/* ---------- Participants ---------- */
async function loadParticipants() {
  state.participants = await api("/api/participants");
  renderParticipants();
}

function renderParticipants() {
  els.list.innerHTML = "";
  if (!state.participants.length) {
    els.list.innerHTML = '<li style="color:var(--muted);font-size:.82rem;padding:8px;">No participants yet.</li>';
    return;
  }
  for (const p of state.participants) {
    const li = document.createElement("li");
    li.className = "participant-item" + (p.id === state.activeParticipantId ? " active" : "");
    li.innerHTML = `
      <div class="avatar">${initials(p.name)}</div>
      <div class="info">
        <strong>${escapeHtml(p.name)}</strong>
        <span>${p.conversation_count || 0} chats · ${p.memory_count || 0} memories</span>
      </div>
      <span class="opt-dot ${p.opted_in ? "" : "off"}" title="${p.opted_in ? "Opted in" : "Not opted in"}"></span>`;
    li.onclick = () => selectParticipant(p.id);
    els.list.appendChild(li);
  }
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

/* ---------- Conversation ---------- */
async function selectParticipant(id) {
  state.activeParticipantId = id;
  const p = state.participants.find((x) => x.id === id);
  els.chatName.textContent = p.name;
  els.chatAvatar.textContent = initials(p.name);
  els.chatMeta.textContent = p.opted_in ? "Opted in · web channel" : "Not opted in · web channel";
  els.input.disabled = false;
  els.send.disabled = false;
  renderParticipants();

  const conv = await api(`/api/participants/${id}/conversation`);
  state.conversationId = conv.id;
  state.lastMessageId = 0;
  els.chatMeta.textContent = `${conv.channel === "whatsapp" ? "WhatsApp" : "Web"} channel · ${p.opted_in ? "opted in" : "not opted in"}`;
  els.messages.innerHTML = "";
  await pollMessages(true);
  startPolling();
  els.input.focus();
}

function appendMessage(msg) {
  if ($(`msg-${msg.id}`)) return;
  els.empty?.classList.add("hidden");
  const div = document.createElement("div");
  div.className = `msg ${msg.role === "kile" ? "kile" : "user"}`;
  div.id = `msg-${msg.id}`;
  div.innerHTML = `${escapeHtml(msg.content)}<span class="time">${fmtTime(msg.created_at)}</span>`;
  els.messages.appendChild(div);
  els.messages.scrollTop = els.messages.scrollHeight;
}

async function pollMessages(initial = false) {
  if (!state.conversationId) return;
  try {
    const msgs = await api(
      `/api/conversations/${state.conversationId}/messages?after_id=${state.lastMessageId}`
    );
    if (msgs.length) {
      for (const m of msgs) appendMessage(m);
      state.lastMessageId = msgs[msgs.length - 1].id;
    } else if (initial) {
      els.empty.classList.remove("hidden");
    }
  } catch (err) {
    if (initial) toast(err.message);
  }
}

function startPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(() => pollMessages(false), 2500);
}

async function sendMessage() {
  const text = els.input.value.trim();
  if (!text || state.sending || !state.conversationId) return;
  state.sending = true;
  els.send.disabled = true;
  els.input.value = "";
  els.input.style.height = "auto";

  // Optimistic bubble so the message shows immediately
  els.empty?.classList.add("hidden");
  const temp = document.createElement("div");
  temp.className = "msg user";
  temp.innerHTML = `${escapeHtml(text)}<span class="time">sending…</span>`;
  els.messages.appendChild(temp);
  els.messages.scrollTop = els.messages.scrollHeight;

  setTimeout(() => {
    if (state.sending) els.typing.classList.remove("hidden");
  }, 1200);

  try {
    const res = await api(`/api/conversations/${state.conversationId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content: text }),
    });
    if (res.kile_reply) {
      appendMessage(res.kile_reply);
      state.lastMessageId = Math.max(state.lastMessageId, res.kile_reply.id);
    }
    await loadParticipants();
  } catch (err) {
    temp.remove();
    toast(err.message);
    els.input.value = text;
  } finally {
    els.typing.classList.add("hidden");
    state.sending = false;
    els.send.disabled = false;
    els.input.focus();
  }
}

/* ---------- Actions ---------- */
async function proactiveInitiate() {
  if (!state.activeParticipantId) return toast("Select a participant first");
  els.proactive.disabled = true;
  try {
    const msg = await api("/api/proactive/trigger", {
      method: "POST",
      body: JSON.stringify({ participant_id: state.activeParticipantId }),
    });
    if (msg.conversation_id && msg.conversation_id !== state.conversationId) {
      await selectParticipant(state.activeParticipantId);
    } else {
      appendMessage(msg);
      state.lastMessageId = Math.max(state.lastMessageId, msg.id);
    }
    toast("Kile initiated the conversation");
    await loadParticipants();
  } catch (err) {
    toast(err.message);
  } finally {
    els.proactive.disabled = false;
  }
}

async function showMemories() {
  if (!state.activeParticipantId) return toast("Select a participant first");
  try {
    const memories = await api(`/api/participants/${state.activeParticipantId}/memories`);
    const list = $("memoryList");
    list.innerHTML = memories.length
      ? memories
          .map(
            (m) =>
              `<li><span class="kind">${escapeHtml(m.kind)} · ${m.importance}/5</span>${escapeHtml(m.content)}</li>`
          )
          .join("")
      : '<li style="color:var(--muted)">Nothing remembered yet — chat a bit first.</li>';
    $("memoryDialog").showModal();
  } catch (err) {
    toast(err.message);
  }
}

async function checkHealth() {
  try {
    await api("/api/health");
    els.llmStatus.textContent = "API: server ok";
    els.llmStatus.className = "status-pill status-ok";
  } catch {
    els.llmStatus.textContent = "API: unreachable";
    els.llmStatus.className = "status-pill status-bad";
  }
}

/* ---------- Wire up ---------- */
$("newParticipantBtn").onclick = () => $("newParticipantDialog").showModal();
$("bulkParticipantBtn").onclick = () => $("bulkParticipantDialog").showModal();

$("bulkParticipantForm").onsubmit = async (e) => {
  if (e.submitter && e.submitter.value === "cancel") return;
  e.preventDefault();
  const form = e.target;
  try {
    const res = await api("/api/participants/bulk", {
      method: "POST",
      body: JSON.stringify({ text: form.text.value }),
    });
    $("bulkParticipantDialog").close();
    form.reset();
    await loadParticipants();
    const skipped = res.skipped.length ? `, ${res.skipped.length} skipped` : "";
    toast(`Added ${res.created.length} contact${res.created.length === 1 ? "" : "s"}${skipped}`);
  } catch (err) {
    toast(err.message);
  }
};

$("newParticipantForm").onsubmit = async (e) => {
  if (e.submitter && e.submitter.value === "cancel") return;
  e.preventDefault();
  const form = e.target;
  try {
    const created = await api("/api/participants", {
      method: "POST",
      body: JSON.stringify({
        name: form.name.value.trim(),
        contact_ref: form.contact_ref.value.trim() || null,
        notes: form.notes.value.trim(),
        opted_in: form.opted_in.checked,
      }),
    });
    $("newParticipantDialog").close();
    form.reset();
    form.opted_in.checked = true;
    await loadParticipants();
    await selectParticipant(created.id);
    toast("Participant created");
  } catch (err) {
    toast(err.message);
  }
};

els.send.onclick = sendMessage;
els.input.onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
};
els.input.oninput = () => {
  els.input.style.height = "auto";
  els.input.style.height = Math.min(els.input.scrollHeight, 140) + "px";
};

els.proactive.onclick = proactiveInitiate;
els.memory.onclick = showMemories;
$("closeMemoryBtn").onclick = () => $("memoryDialog").close();

(async function init() {
  await checkHealth();
  await loadParticipants();
})();
