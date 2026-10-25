/* Room settings: the cog under the header chips in a room view.

   Top: the room's Room Temperature settings (as in Nook's room dialog). Below: the TRV's
   own simple settings — numbers, switches and buttons its integration files under
   Configuration. No option lists, text or times: a wall panel is for quick changes,
   the rest stays in Nook's room dialog. Everything is sized for a finger: big −/+ that
   repeat while held, whole-row toggles, no keyboard. Each change is sent on its own
   (room fields to Nook, TRV settings straight to the TRV), nothing to save. */

const SEND_AFTER_MS = 900; // a pause in −/+ taps before a value is sent
const REPEAT_DELAY_MS = 450;
const REPEAT_EVERY_MS = 110;
const TOAST_MS = 2600;

const HOLD_ENDS = [
  ["house_change", "The next house change"],
  ["block_change", "The next schedule block"],
  ["manual", "The room is changed again"],
];

const ICON = {
  minus: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M19 13H5v-2h14z"/></svg>`,
  plus: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>`,
  tick: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" d="M5 12.5l4.5 4.5L19 7.5"/></svg>`,
};

function el(id) {
  return document.getElementById(id);
}

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Decimals a step needs: 0.5 → 1, 1 → 0, 0.01 → 2. */
function decimalsFor(step) {
  const s = String(step);
  return s.includes(".") ? Math.min(3, s.split(".")[1].length) : 0;
}

function fmt(value, step, unit = "", signed = false) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "--";
  const text = n.toFixed(decimalsFor(step));
  return `${signed && n > 0 ? "+" : ""}${text}${unit}`;
}

export class RoomSettings {
  /**
   * @param {object} opts
   * @param {() => any} opts.getClient  the HA client (request + callService)
   * @param {() => void} [opts.onClose]
   */
  constructor({ getClient, onClose }) {
    this.getClient = getClient;
    this.onClose = onClose;
    this.page = el("roomSettings");
    this.body = el("rsBody");
    this.toastEl = el("rsToast");
    this.roomId = null;
    this.data = null;
    this.timers = new Map(); // pending sends by key
    this.repeat = null;
    this.toastTimer = null;
    this.loadSeq = 0;

    el("rsBack")?.addEventListener("click", () => this.close());
    this.body.addEventListener("click", (ev) => this.onClick(ev));
    // Hold −/+ to keep going.
    this.body.addEventListener("pointerdown", (ev) => this.onStepDown(ev));
    // A held −/+ stops wherever the finger lifts (or the page starts scrolling).
    for (const type of ["pointerup", "pointercancel"]) {
      window.addEventListener(type, () => this.stopRepeat(), true);
    }
    this.page.addEventListener("scroll", () => this.stopRepeat(), { passive: true });
  }

  get isOpen() {
    return !this.page.hidden;
  }

  async open(roomId, name) {
    this.roomId = roomId;
    this.data = null;
    el("rsName").textContent = name || "Room";
    this.body.innerHTML = `<p class="rs-note">Loading…</p>`;
    this.page.hidden = false;
    this.page.scrollTop = 0;
    await this.load();
  }

  close() {
    if (this.page.hidden) return;
    this.flush();
    this.stopRepeat();
    this.page.hidden = true;
    this.roomId = null;
    this.onClose?.();
  }

  async load() {
    const seq = ++this.loadSeq;
    try {
      const data = await this.getClient()?.request("nook/get_wall_room_settings", { room_id: this.roomId });
      if (seq !== this.loadSeq || !this.isOpen) return;
      this.data = data;
      this.render();
    } catch (err) {
      if (seq !== this.loadSeq) return;
      this.body.innerHTML = `<p class="rs-note">Couldn't load this room's settings (${esc(err?.message || err)}).</p>`;
    }
  }

  /* —— Drawing —— */

  render() {
    const { room, trv, settings } = this.data;
    const parts = [];
    parts.push(`<div class="rs-section"><div class="rs-title">Room Temperature</div>`);
    parts.push(this.toggleRow("room:follow_house", "Follow the house", room.follow_house,
      room.follow_house ? "Uses the house temperature plus the offset below." : "This room has its own temperatures."));
    if (room.follow_house) {
      parts.push(this.stepRow("room:house_offset", "Offset from the house", room.house_offset,
        { min: -5, max: 5, step: 0.5, unit: "°", signed: true }));
    } else {
      parts.push(this.stepRow("room:target_temp", "Comfort", room.target_temp, { min: 5, max: 30, step: 0.5, unit: "°" }));
      parts.push(this.stepRow("room:eco_temp", "Eco", room.eco_temp, { min: 5, max: 30, step: 0.5, unit: "°" }));
    }
    parts.push(`<div class="rs-field"><div class="rs-label">A change made on this room lasts until</div><div class="rs-choices">`);
    for (const [value, label] of HOLD_ENDS) {
      const on = room.hold_ends === value;
      parts.push(`<button type="button" class="rs-choice${on ? " on" : ""}" data-choice="room:hold_ends" data-value="${value}" aria-pressed="${on}">
        <span class="rs-radio">${on ? ICON.tick : ""}</span><span>${label}</span></button>`);
    }
    parts.push(`</div></div></div>`);

    parts.push(`<div class="rs-section"><div class="rs-title">TRV Settings</div>`);
    if (!trv.entity_id) {
      parts.push(`<p class="rs-note">This room has no TRV.</p>`);
    } else if (!settings.length) {
      parts.push(`<p class="rs-note">This TRV has no simple settings to change here.</p>`);
    } else {
      if (!trv.available) parts.push(`<p class="rs-note warn">The TRV is offline — its settings can't be changed now.</p>`);
      for (const s of settings) parts.push(this.trvRow(s, trv.available));
    }
    parts.push(`</div>`);
    this.body.innerHTML = parts.join("");
  }

  toggleRow(key, name, on, desc = "", disabled = false) {
    return `<button type="button" class="rs-row rs-toggle${on ? " on" : ""}" data-toggle="${esc(key)}" aria-pressed="${Boolean(on)}" ${disabled ? "disabled" : ""}>
      <span class="rs-text"><span class="rs-name">${esc(name)}</span>${desc ? `<span class="rs-desc">${esc(desc)}</span>` : ""}</span>
      <span class="rs-switch"><span></span></span></button>`;
  }

  stepRow(key, name, value, { min, max, step, unit = "", signed = false }, disabled = false) {
    const known = value !== null && value !== "" && Number.isFinite(Number(value));
    return `<div class="rs-row rs-stepper" data-step-row="${esc(key)}" data-min="${min ?? ""}" data-max="${max ?? ""}" data-step="${step}" data-unit="${esc(unit)}" data-signed="${signed ? 1 : 0}" data-value="${known ? Number(value) : ""}">
      <span class="rs-text"><span class="rs-name">${esc(name)}</span></span>
      <span class="rs-steps">
        <button type="button" class="rs-step" data-dir="-1" aria-label="Lower ${esc(name)}" ${disabled || !known ? "disabled" : ""}>${ICON.minus}</button>
        <span class="rs-value">${known ? fmt(value, step, unit, signed) : "--"}</span>
        <button type="button" class="rs-step" data-dir="1" aria-label="Raise ${esc(name)}" ${disabled || !known ? "disabled" : ""}>${ICON.plus}</button>
      </span></div>`;
  }

  trvRow(s, available) {
    const off = !available || s.state === "unavailable";
    const key = `trv:${s.entity_id}`;
    if (s.domain === "switch") return this.toggleRow(key, s.name, s.state === "on", "", off);
    if (s.domain === "number") {
      const step = Number(s.step) > 0 ? Number(s.step) : 1;
      const unit = s.unit ? (s.unit === "°C" || s.unit === "°F" ? "°" : ` ${s.unit}`) : "";
      return this.stepRow(key, s.name, s.state, { min: s.min, max: s.max, step, unit }, off);
    }
    return `<div class="rs-row"><span class="rs-text"><span class="rs-name">${esc(s.name)}</span></span>
      <button type="button" class="rs-press" data-press="${esc(s.entity_id)}" ${off ? "disabled" : ""}>Press</button></div>`;
  }

  /* —— Touch —— */

  onClick(ev) {
    const toggle = ev.target.closest("[data-toggle]");
    if (toggle && !toggle.disabled) {
      const on = !toggle.classList.contains("on");
      toggle.classList.toggle("on", on);
      toggle.setAttribute("aria-pressed", String(on));
      this.change(toggle.dataset.toggle, on, { now: true });
      return;
    }
    const choice = ev.target.closest("[data-choice]");
    if (choice) {
      for (const b of this.body.querySelectorAll(`[data-choice="${choice.dataset.choice}"]`)) {
        const on = b === choice;
        b.classList.toggle("on", on);
        b.setAttribute("aria-pressed", String(on));
        b.querySelector(".rs-radio").innerHTML = on ? ICON.tick : "";
      }
      this.change(choice.dataset.choice, choice.dataset.value, { now: true });
      return;
    }
    const press = ev.target.closest("[data-press]");
    if (press && !press.disabled) this.pressButton(press);
  }

  onStepDown(ev) {
    const btn = ev.target.closest(".rs-step");
    if (!btn || btn.disabled) return;
    ev.preventDefault();
    this.stopRepeat();
    const go = () => this.stepBy(btn);
    go();
    this.repeat = setTimeout(() => {
      this.repeat = setInterval(go, REPEAT_EVERY_MS);
    }, REPEAT_DELAY_MS);
  }

  stopRepeat() {
    clearTimeout(this.repeat);
    clearInterval(this.repeat);
    this.repeat = null;
  }

  stepBy(btn) {
    const row = btn.closest("[data-step-row]");
    const step = Number(row.dataset.step) || 1;
    const min = row.dataset.min === "" ? -Infinity : Number(row.dataset.min);
    const max = row.dataset.max === "" ? Infinity : Number(row.dataset.max);
    const current = Number(row.dataset.value);
    // Snap to the step grid (counted from min when there is one) so 0.1-noise never creeps in.
    const base = Number.isFinite(min) ? min : 0;
    let next = base + Math.round((current + Number(btn.dataset.dir) * step - base) / step) * step;
    next = Number(Math.min(max, Math.max(min, next)).toFixed(decimalsFor(step)));
    if (next === current) return;
    row.dataset.value = String(next);
    row.querySelector(".rs-value").textContent = fmt(next, step, row.dataset.unit, row.dataset.signed === "1");
    this.change(row.dataset.stepRow, next);
  }

  /* —— Sending —— */

  /** Keep the last value per setting; send after a pause (toggles and choices at once). */
  change(key, value, { now = false } = {}) {
    clearTimeout(this.timers.get(key)?.timer);
    const send = () => {
      this.timers.delete(key);
      this.send(key, value);
    };
    if (now) {
      this.timers.delete(key);
      this.send(key, value);
      return;
    }
    this.timers.set(key, { timer: setTimeout(send, SEND_AFTER_MS), send });
  }

  /** Closing the page sends what's still waiting. */
  flush() {
    for (const { timer, send } of [...this.timers.values()]) {
      clearTimeout(timer);
      send();
    }
    this.timers.clear();
  }

  async send(key, value) {
    const client = this.getClient();
    const roomId = this.roomId || this.data?.room?.id;
    if (!client || !roomId) return;
    const [kind, id] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
    try {
      if (kind === "room") {
        const data = await client.request("nook/update_wall_room", { room_id: roomId, [id]: value });
        if (!this.isOpen || this.roomId !== roomId) return;
        this.data = data;
        // Follow the house swaps the fields below it; otherwise leave the page as the finger left it.
        if (id === "follow_house" && !this.timers.size) this.render();
        this.toast("Saved");
      } else {
        const name = this.data?.settings?.find((s) => s.entity_id === id)?.name || id;
        const domain = id.split(".")[0];
        if (domain === "switch") await client.callService("switch", value ? "turn_on" : "turn_off", { entity_id: id });
        else await client.callService("number", "set_value", { entity_id: id, value });
        const item = this.data?.settings?.find((s) => s.entity_id === id);
        if (item) item.state = domain === "switch" ? (value ? "on" : "off") : String(value);
        this.toast(`${name}: sent to the TRV`);
      }
    } catch (err) {
      this.toast(`Didn't save (${err?.message || err})`, true);
      if (this.isOpen) this.load(); // show what's really set
    }
  }

  async pressButton(btn) {
    const id = btn.dataset.press;
    const name = this.data?.settings?.find((s) => s.entity_id === id)?.name || id;
    try {
      await this.getClient()?.callService("button", "press", { entity_id: id });
      this.toast(`${name}: pressed`);
    } catch (err) {
      this.toast(`${name}: the TRV didn't take it (${err?.message || err})`, true);
    }
  }

  toast(text, bad = false) {
    if (!this.toastEl) return;
    clearTimeout(this.toastTimer);
    this.toastEl.textContent = text;
    this.toastEl.classList.toggle("bad", bad);
    this.toastEl.classList.remove("hidden");
    this.toastTimer = setTimeout(() => this.toastEl.classList.add("hidden"), TOAST_MS);
  }
}
