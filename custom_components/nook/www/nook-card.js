/**
 * Nook — dashboard card (type: custom:nook-card).
 * Loaded automatically by the integration; pick "Nook" in the card list.
 * Everything comes from the Nook climate entities, so it updates live with no polling.
 */
const NOOK_CARD_VERSION = "0.7.5";

const NC_STYLES = `
:host { display: block; }
ha-card { overflow: hidden; }
.nc {
  --nc-heat: #F57C00; --nc-heat-soft: #FF9800; --nc-teal: #08979C; --nc-teal-hi: #19D4DE;
  --nc-green: #52C41A; --nc-amber: #FA8C16; --nc-red: #e53935;
  --nc-tint: var(--nc-teal-hi);
  position: relative; padding: 16px;
  background: radial-gradient(80% 120% at 0% 0%, color-mix(in srgb, var(--nc-tint) 12%, transparent), transparent 65%);
  color: var(--primary-text-color); font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, Roboto, sans-serif));
}
.nc.heating { --nc-tint: var(--nc-heat-soft); }
.nc.off { --nc-tint: #9aa0a6; }
.nc-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.nc-name { font-size: 18px; font-weight: 600; letter-spacing: -0.01em; margin: 0; cursor: pointer; }
.nc-status { font-size: 13px; color: var(--secondary-text-color); margin-top: 2px; }
.nc.heating .nc-status { color: var(--nc-heat-soft); }
.nc-pills { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
.nc-pill {
  display: inline-flex; align-items: center; gap: 5px; padding: 4px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 600; white-space: nowrap;
  background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); color: var(--secondary-text-color);
}
.nc-pill svg { width: 13px; height: 13px; }
.nc-pill.heat { background: color-mix(in srgb, var(--nc-heat) 16%, transparent); color: var(--nc-heat-soft); }
.nc-pill.leaf { background: color-mix(in srgb, var(--nc-green) 16%, transparent); color: var(--nc-green); }
.nc-pill.warn { background: color-mix(in srgb, var(--nc-amber) 16%, transparent); color: var(--nc-amber); }
.nc-pill.bad { background: color-mix(in srgb, var(--nc-red) 16%, transparent); color: var(--nc-red); }

.nc-main { display: flex; flex-direction: column; align-items: center; gap: 14px; margin-top: 8px; }
.nc-dial { position: relative; width: 100%; max-width: 260px; aspect-ratio: 1; touch-action: none; user-select: none; -webkit-user-select: none; }
.nc-dial > svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.nc-dial .track { stroke: color-mix(in srgb, var(--primary-text-color) 10%, transparent); }
.nc-dial { cursor: default; }
.nc-dial .ring { cursor: grab; }
.nc-dial.dragging .ring { cursor: grabbing; }
.nc-dial .knob {
  fill: #fff; stroke: color-mix(in srgb, #000 22%, transparent); stroke-width: 1; cursor: grab;
  filter: drop-shadow(0 1px 3px rgba(0,0,0,0.4)); transition: r 0.12s ease;
}
.nc-dial.dragging .knob { cursor: grabbing; }
.nc.heating .nc-dial .knob { filter: drop-shadow(0 0 6px rgba(255,120,30,0.85)); }
/* Indoor temperature: a small dot on the track, so it doesn't look like a handle. */
.nc-dial .now-dot { fill: var(--primary-text-color); opacity: 0.75; pointer-events: none; }
.nc-core { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; pointer-events: none; text-align: center; }
.nc-caption { font-size: 11px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--secondary-text-color); }
.nc.heating .nc-caption { color: var(--nc-heat-soft); }
.nc-target { font-size: 60px; font-weight: 300; line-height: 1; letter-spacing: -0.04em; margin: 4px 0; font-variant-numeric: tabular-nums; }
.nc-target sup { font-size: 0.36em; font-weight: 400; vertical-align: top; position: relative; top: 0.35em; margin-left: 2px; }
.nc-target.pending { color: var(--nc-heat-soft); }
.nc-sub { font-size: 13px; color: var(--secondary-text-color); }
.nc-eta { font-size: 12px; font-weight: 600; color: var(--nc-heat-soft); margin-top: 2px; }
.nc-steps { position: absolute; left: 50%; bottom: 2%; transform: translateX(-50%); display: flex; gap: 44px; }
.nc-step {
  width: 42px; height: 42px; border-radius: 50%; display: grid; place-items: center; cursor: pointer; padding: 0;
  border: 1px solid color-mix(in srgb, var(--primary-text-color) 14%, transparent);
  background: color-mix(in srgb, var(--primary-text-color) 6%, var(--card-background-color, var(--ha-card-background, #fff)));
  color: var(--primary-text-color); transition: transform 0.1s ease, background 0.15s ease;
}
.nc-step svg { width: 22px; height: 22px; }
.nc-step:hover { background: color-mix(in srgb, var(--primary-text-color) 12%, var(--card-background-color, #fff)); }
.nc-step:active { transform: scale(0.92); }
.nc-step:disabled { opacity: 0.35; cursor: default; }
.nc-step:focus-visible, .nc-mode:focus-visible, .nc-room:focus-visible { outline: 2px solid var(--nc-teal-hi); outline-offset: 2px; }

.nc-modes { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; width: 100%; }
.nc-seg { display: inline-flex; padding: 3px; border-radius: 999px; background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); }
.nc-mode {
  border: 0; background: transparent; color: var(--secondary-text-color); cursor: pointer;
  padding: 7px 14px; border-radius: 999px; font: inherit; font-size: 13px; font-weight: 600;
  display: inline-flex; align-items: center; gap: 6px;
}
.nc-mode svg { width: 15px; height: 15px; }
.nc-mode.active { background: var(--card-background-color, var(--ha-card-background, #fff)); color: var(--primary-text-color); box-shadow: 0 1px 3px rgba(0,0,0,0.2); }
.nc-mode.active.heat { color: var(--nc-heat-soft); }
.nc-mode.active.eco { color: var(--nc-green); }
.nc-mode.active.boost { color: var(--nc-heat-soft); }
.nc-mode.active.away { color: var(--nc-teal-hi); }

.nc-rooms { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 8px; margin-top: 16px; }
.nc-room {
  display: flex; flex-direction: column; gap: 1px; padding: 10px 12px; border-radius: 12px; cursor: pointer; text-align: left;
  font: inherit; color: inherit;
  background: color-mix(in srgb, var(--primary-text-color) 5%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary-text-color) 8%, transparent);
}
.nc-room:hover { background: color-mix(in srgb, var(--primary-text-color) 9%, transparent); }
.nc-room.heat { background: color-mix(in srgb, var(--nc-heat) 10%, transparent); border-color: color-mix(in srgb, var(--nc-heat) 35%, transparent); }
.nc-room-top { display: flex; justify-content: space-between; align-items: center; gap: 4px; }
.nc-room-name { font-size: 12px; font-weight: 600; color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nc-room-top svg { width: 13px; height: 13px; color: var(--nc-heat-soft); flex-shrink: 0; }
.nc-off {
  flex-shrink: 0; padding: 1px 7px; border-radius: 999px; font-size: 10px; font-weight: 700;
  background: color-mix(in srgb, var(--nc-red) 16%, transparent); color: var(--nc-red);
}
.nc-room-set .nc-off { display: inline-block; margin-top: 2px; }
.nc-room-temp { font-size: 22px; font-weight: 400; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
.nc-room-temp.unknown { color: var(--secondary-text-color); }
.nc-room-set { font-size: 11px; color: var(--secondary-text-color); }
.nc-room.heat .nc-room-set { color: var(--nc-heat-soft); }
.nc-empty { padding: 24px 16px; color: var(--secondary-text-color); font-size: 14px; }

/* Compact: dial left, controls right. */
.nc.compact .nc-main { flex-direction: row; align-items: center; gap: 16px; margin-top: 4px; }
.nc.compact .nc-dial { max-width: 150px; flex-shrink: 0; }
.nc.compact .nc-target { font-size: 40px; }
.nc.compact .nc-caption { font-size: 9px; }
.nc.compact .nc-sub, .nc.compact .nc-eta { font-size: 11px; }
.nc.compact .nc-steps { gap: 30px; bottom: 0; }
.nc.compact .nc-step { width: 32px; height: 32px; }
.nc.compact .nc-step svg { width: 18px; height: 18px; }
.nc.compact .nc-modes { justify-content: flex-start; }
.nc.compact .nc-mode { padding: 6px 10px; font-size: 12px; }
.nc-side { display: flex; flex-direction: column; gap: 10px; min-width: 0; flex: 1; }
`;

const NC_ICONS = {
  flame: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2c.5 3.2-1.6 5-3.2 6.9C7.4 10.6 6 12.4 6 15a6 6 0 0 0 12 0c0-2.6-1.3-4.6-2.6-6.1-.3 1.6-1.1 2.7-2.3 3.2.6-3.7-.3-7.6-1.1-10.1z"/></svg>`,
  leaf: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M6.6 17.4C4.6 9.9 10.6 4.3 20 4z"/><path fill="currentColor" opacity=".68" d="M20 4c.3 9.4-5.4 15.4-13.4 13.4z"/><path fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" d="M3.6 20.4 7.4 16.6"/></svg>`,
  power: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" d="M12 3v8M6.4 6.6a8 8 0 1 0 11.2 0"/></svg>`,
  minus: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M19 13H5v-2h14z"/></svg>`,
  plus: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>`,
};

const NC_ARC = "M40.6 159.4 A84 84 0 1 1 159.4 159.4";

function ncFmt(v) {
  if (v == null || Number.isNaN(Number(v))) return null;
  const n = Math.round(Number(v) * 10) / 10;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function ncClock(ts) {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function ncEsc(s) {
  return String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

/** Nook's house climate: a Nook climate that reports boiler_demand. */
function ncFindHome(hass) {
  const ids = Object.keys(hass?.entities || {}).filter(
    (id) => id.startsWith("climate.") && hass.entities[id]?.platform === "nook"
  );
  return ids.find((id) => hass.states[id]?.attributes?.boiler_demand !== undefined) || ids[0] || "";
}

class NookCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("nook-card-editor");
  }

  static getStubConfig(hass) {
    return { entity: ncFindHome(hass) };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._pending = null;
    this._pendingAt = 0;
    this._sendTimer = null;
    this._dragging = false;
    this._lastKey = "";
  }

  setConfig(config) {
    if (!config) throw new Error("Invalid configuration");
    this._config = { layout: "full", show_status: true, show_modes: true, show_rooms: true, ...config };
    this._lastKey = "";
    this._build();
    this._update(true);
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  getCardSize() {
    if (this._config?.layout === "compact") return this._config.show_rooms ? 5 : 3;
    return this._config?.show_rooms ? 9 : 7;
  }

  getGridOptions() {
    return this._config?.layout === "compact"
      ? { columns: 12, min_columns: 6, rows: "auto" }
      : { columns: 6, min_columns: 4, rows: "auto" };
  }

  get _entityId() {
    // A configured entity that no longer exists (deleted or renamed) falls back to Nook's
    // house climate rather than showing an empty card.
    const configured = this._config?.entity;
    if (configured && (!this._hass || this._hass.states[configured])) return configured;
    return ncFindHome(this._hass) || configured || "";
  }

  _build() {
    const compact = this._config.layout === "compact";
    const dial = `
      <div class="nc-dial">
        <svg viewBox="0 0 200 200" aria-hidden="true">
          <defs>
            <linearGradient id="ncGrad" x1="0" y1="1" x2="1" y2="0">
              <stop class="g0" offset="0"/><stop class="g1" offset="1"/>
            </linearGradient>
          </defs>
          <path class="track" d="${NC_ARC}" fill="none" stroke-width="12" stroke-linecap="round"/>
          <path class="fill" d="${NC_ARC}" pathLength="100" fill="none" stroke="url(#ncGrad)" stroke-width="12" stroke-linecap="round"/>
          <path class="ring" d="${NC_ARC}" fill="none" stroke="transparent" stroke-width="40"/>
          <circle class="now-dot" r="3.5"/>
          <circle class="knob" r="10"/>
        </svg>
        <div class="nc-core">
          <div class="nc-caption"></div>
          <div class="nc-target"></div>
          <div class="nc-sub"></div>
          <div class="nc-eta"></div>
        </div>
        <div class="nc-steps">
          <button class="nc-step" data-step="-1" aria-label="Lower the temperature">${NC_ICONS.minus}</button>
          <button class="nc-step" data-step="1" aria-label="Raise the temperature">${NC_ICONS.plus}</button>
        </div>
      </div>`;
    const modes = this._config.show_modes
      ? `<div class="nc-modes">
          <div class="nc-seg">
            <button class="nc-mode heat" data-hvac="heat">${NC_ICONS.flame}Heat</button>
            <button class="nc-mode" data-hvac="off">${NC_ICONS.power}Off</button>
          </div>
          <div class="nc-seg">
            <button class="nc-mode eco" data-preset="eco">Eco</button>
            <button class="nc-mode boost" data-preset="boost">Boost</button>
            <button class="nc-mode away" data-preset="away">Away</button>
          </div>
        </div>`
      : "";
    this.shadowRoot.innerHTML = `
      <style>${NC_STYLES}</style>
      <ha-card>
        <div class="nc${compact ? " compact" : ""}">
          <div class="nc-head">
            <div><p class="nc-name"></p><div class="nc-status"></div></div>
            ${this._config.show_status ? `<div class="nc-pills"></div>` : ""}
          </div>
          <div class="nc-main">
            ${dial}
            ${compact ? `<div class="nc-side">${modes}</div>` : modes}
          </div>
          ${this._config.show_rooms ? `<div class="nc-rooms"></div>` : ""}
        </div>
      </ha-card>`;
    this._bind();
  }

  _bind() {
    const root = this.shadowRoot;
    root.querySelectorAll(".nc-step").forEach((b) => b.addEventListener("click", () => this._step(Number(b.dataset.step))));
    root.querySelectorAll("[data-hvac]").forEach((b) =>
      b.addEventListener("click", () => this._call("set_hvac_mode", { hvac_mode: b.dataset.hvac }).catch(() => {}))
    );
    root.querySelectorAll("[data-preset]").forEach((b) =>
      b.addEventListener("click", () => {
        const current = this._hass?.states[this._entityId]?.attributes?.preset_mode;
        // Tapping the active preset turns it off again.
        this._call("set_preset_mode", { preset_mode: current === b.dataset.preset ? "none" : b.dataset.preset }).catch(() => {});
      })
    );
    root.querySelector(".nc-name")?.addEventListener("click", () => this._moreInfo(this._entityId));
    const rooms = root.querySelector(".nc-rooms");
    rooms?.addEventListener("click", (ev) => {
      const tile = ev.target.closest("[data-entity]");
      if (tile) this._moreInfo(tile.dataset.entity);
    });

    // Drag along the arc to set the temperature.
    const dial = root.querySelector(".nc-dial");
    const ring = root.querySelector(".ring");
    const knob = root.querySelector(".knob");
    void ring;
    const local = (ev) => {
      const r = dial.getBoundingClientRect();
      return { x: ((ev.clientX - r.left) / r.width) * 200 - 100, y: ((ev.clientY - r.top) / r.height) * 200 - 100 };
    };
    const fromPointer = (ev) => {
      const { x, y } = local(ev);
      let rel = ((Math.atan2(y, x) * 180) / Math.PI - 135 + 720) % 360;
      // In the open gap at the bottom, stay at the end the drag came from — snapping to the
      // nearer end made the value flip between min and max on tiny movements.
      if (rel > 270) rel = (this._dragRel ?? 135) > 135 ? 270 : 0;
      this._dragRel = rel;
      const { lo, hi, step } = this._limits();
      return Math.min(hi, Math.max(lo, Math.round((lo + (rel / 270) * (hi - lo)) / step) * step));
    };
    dial.addEventListener("pointerdown", (ev) => {
      if ((ev.button !== undefined && ev.button !== 0) || ev.target.closest(".nc-step")) return;
      // Only the ring band (and the handle) starts a drag, not the numbers in the middle.
      const { x, y } = local(ev);
      const dist = Math.hypot(x, y);
      if (ev.target !== knob && (dist < 62 || dist > 104)) return;
      ev.preventDefault();
      const { lo, hi } = this._limits();
      const cur = Number(this._shownTarget() ?? lo);
      this._dragRel = ((cur - lo) / (hi - lo)) * 270;
      this._dragging = true;
      dial.classList.add("dragging");
      knob.setAttribute("r", "13");
      try {
        dial.setPointerCapture(ev.pointerId);
      } catch {
        // pointer already gone
      }
      this._setPending(fromPointer(ev), false);
    });
    dial.addEventListener("pointermove", (ev) => {
      if (!this._dragging) return;
      const value = fromPointer(ev);
      if (value !== this._pending) this._setPending(value, false);
    });
    const end = () => {
      if (!this._dragging) return;
      this._dragging = false;
      dial.classList.remove("dragging");
      knob.setAttribute("r", "10");
      this._update(true);
      this._queueSend(0);
    };
    dial.addEventListener("pointerup", end);
    dial.addEventListener("pointercancel", end);
  }

  _limits() {
    const a = this._hass?.states[this._entityId]?.attributes || {};
    return { lo: Number(a.min_temp ?? 7), hi: Number(a.max_temp ?? 30), step: Number(a.target_temp_step) || 0.5 };
  }

  _shownTarget() {
    const home = this._hass?.states[this._entityId];
    const reported = home?.attributes?.temperature;
    if (this._pending != null) {
      const idle = !this._sendTimer && !this._dragging && !this._sending;
      const matches = reported != null && Number(reported) === this._pending;
      // HA wrote a new state after our call: show what Nook actually set (no 15 s wait then jump).
      const echoed = this._sentStamp != null && home?.last_updated !== this._sentStamp;
      if (idle && (matches || echoed || Date.now() - this._pendingAt > 15000)) {
        this._pending = null;
        this._sentStamp = null;
      } else return this._pending;
    }
    return reported;
  }

  _step(direction) {
    const { lo, hi, step } = this._limits();
    const base = Number(this._shownTarget() ?? 20);
    this._setPending(Math.min(hi, Math.max(lo, Math.round((base + direction * step) / step) * step)), true);
  }

  _setPending(value, send) {
    this._pending = value;
    this._pendingAt = Date.now();
    this._update(true, this._dragging);
    if (send) this._queueSend(700);
  }

  _queueSend(delay) {
    clearTimeout(this._sendTimer);
    this._sendTimer = setTimeout(async () => {
      this._sendTimer = null;
      if (this._pending == null) return;
      this._sending = true;
      this._sentStamp = this._hass?.states[this._entityId]?.last_updated ?? null;
      try {
        await this._call("set_temperature", { temperature: this._pending }, false);
        this._pendingAt = Date.now();
      } catch {
        this._pending = null;
        this._sentStamp = null;
      } finally {
        this._sending = false;
        this._update(true);
      }
    }, delay);
  }

  async _call(service, data, toastOnError = true) {
    if (!this._hass || !this._entityId) return;
    try {
      await this._hass.callService("climate", service, { entity_id: this._entityId, ...data });
    } catch (e) {
      if (toastOnError) {
        this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message: `Nook: ${e?.message || e}` }, bubbles: true, composed: true }));
      }
      throw e;
    }
  }

  _moreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  _roomIds(home) {
    const listed = home?.attributes?.room_entities;
    if (Array.isArray(listed)) return listed;
    return Object.keys(this._hass?.entities || {}).filter(
      (id) => id !== this._entityId && id.startsWith("climate.") && this._hass.entities[id]?.platform === "nook"
    );
  }

  _update(force = false, dialOnly = false) {
    if (!this._config || !this._hass || !this.shadowRoot.querySelector(".nc")) return;
    const id = this._entityId;
    const home = this._hass.states[id];
    const roomIds = this._config.show_rooms ? this._roomIds(home) : [];
    // Only redraw when something we show changed (hass updates arrive constantly).
    const key = [
      home?.last_updated,
      ...roomIds.map((r) => {
        const st = this._hass.states[r];
        const trv = st?.attributes?.trv_entity;
        return `${st?.last_updated}/${trv ? this._hass.states[trv]?.state : ""}`;
      }),
    ].join("|");
    if (!force && key === this._lastKey) return;
    if (!force && this._dragging) return; // don't fight the user's drag
    this._lastKey = key;

    const root = this.shadowRoot;
    const card = root.querySelector(".nc");
    if (!home) {
      root.querySelector(".nc-name").textContent = this._config.name || "Nook";
      root.querySelector(".nc-status").textContent = id ? `${id} isn't available` : "No Nook thermostat found — pick one in the card settings.";
      return;
    }
    const a = home.attributes;
    const off = home.state === "off";
    const heating = !off && a.hvac_action === "heating";
    const target = this._shownTarget();
    const { lo, hi } = this._limits();
    const pos = (t) => (t == null || !Number.isFinite(Number(t)) ? null : Math.min(1, Math.max(0, (Number(t) - lo) / (hi - lo))));

    card.classList.toggle("heating", heating);
    card.classList.toggle("off", off);
    root.querySelector(".nc-name").textContent = this._config.name || "Home";

    // Minimum on/off time: the boiler is held against what Nook wants until then.
    const holdUntil = !off && a.boiler_hold_until ? ncClock(a.boiler_hold_until) : "";
    const finishing = Boolean(holdUntil) && heating && !a.boiler_demand;
    let status = "Holding temperature";
    if (off) status = "Heating is off";
    else if (holdUntil) status = heating ? `Boiler off at ${holdUntil}` : `Boiler on at ${holdUntil}`;
    else if (a.summer_mode) status = "Summer mode — heating paused";
    else if (a.window_open) status = "Window open — heating paused";
    else if (a.preheating) status = `Preheating for ${a.preheat_for || "the schedule"}`;
    else if (heating) status = "Warming the house";
    else if (a.current_temperature != null && target != null && Number(a.current_temperature) >= Number(target)) status = "Up to temperature";
    root.querySelector(".nc-status").textContent = status;

    // Dial
    const fill = (pos(target) ?? 0) * 100;
    const fillEl = root.querySelector(".fill");
    fillEl.setAttribute("stroke-dasharray", `${fill.toFixed(1)} 100`);
    fillEl.style.display = fill > 0 ? "" : "none";
    // Warm, Nest-like: amber in Heat, deep orange while actually heating, grey when off.
    const [c0, c1] = off ? ["#5f656b", "#8a9096"] : heating ? ["#FFB74D", "#F4511E"] : ["#FFD180", "#FF9800"];
    root.querySelector(".g0").setAttribute("stop-color", c0);
    root.querySelector(".g1").setAttribute("stop-color", c1);
    const place = (el, p) => {
      if (p == null) {
        el.style.display = "none";
        return;
      }
      const ang = ((135 + 270 * p) * Math.PI) / 180;
      el.style.display = "";
      el.setAttribute("cx", (100 + 84 * Math.cos(ang)).toFixed(1));
      el.setAttribute("cy", (100 + 84 * Math.sin(ang)).toFixed(1));
    };
    place(root.querySelector(".now-dot"), pos(a.current_temperature));
    place(root.querySelector(".knob"), pos(target));

    root.querySelector(".nc-caption").textContent = off ? "Off" : a.preheating ? "Preheating to" : heating && !finishing ? "Heating to" : "Set to";
    const t = root.querySelector(".nc-target");
    const shown = ncFmt(target);
    t.innerHTML = shown == null ? "—" : `${ncEsc(shown)}<sup>°C</sup>`;
    t.classList.toggle("pending", this._pending != null);
    const now = ncFmt(a.current_temperature);
    root.querySelector(".nc-sub").textContent = now == null ? "" : `Indoor ${now}°`;
    const eta = heating && a.time_to_temp_minutes != null ? Math.round(Number(a.time_to_temp_minutes)) : null;
    root.querySelector(".nc-eta").textContent =
      eta == null ? "" : eta < 60 ? `~${eta} min to go` : `~${Math.floor(eta / 60)}h ${eta % 60 ? `${eta % 60}m ` : ""}to go`;
    const [minus, plus] = root.querySelectorAll(".nc-step");
    minus.disabled = target != null && Number(target) <= lo;
    plus.disabled = target != null && Number(target) >= hi;

    if (dialOnly) return;

    // Modes
    root.querySelectorAll("[data-hvac]").forEach((b) => b.classList.toggle("active", b.dataset.hvac === home.state));
    root.querySelectorAll("[data-preset]").forEach((b) => b.classList.toggle("active", b.dataset.preset === a.preset_mode));

    // Status pills
    const pills = root.querySelector(".nc-pills");
    if (pills) {
      const out = [];
      const pill = (cls, text, icon = "") => out.push(`<span class="nc-pill ${cls}">${icon}${ncEsc(text)}</span>`);
      if (a.heater_available === false) pill("bad", "Boiler relay offline");
      if (a.heating_fault) pill("bad", "Not warming up");
      if (a.safety_active) pill("heat", "Safety heat", NC_ICONS.flame);
      else if (a.boiler_on) pill("heat", "Boiler on", NC_ICONS.flame);
      if (a.leaf) pill("leaf", "Leaf", NC_ICONS.leaf);
      if (a.away_mode) pill("warn", "Away");
      if (a.window_open) pill("warn", "Window open");
      if (a.summer_mode) pill("warn", "Summer");
      const html = out.join("");
      if (pills.innerHTML !== html) pills.innerHTML = html; // unchanged → leave the DOM alone (no flicker)
    }

    // Rooms
    const rooms = root.querySelector(".nc-rooms");
    if (rooms) {
      const html = roomIds
        .map((rid) => {
          const st = this._hass.states[rid];
          if (!st) return "";
          const ra = st.attributes;
          const name = ra.room_name || String(ra.friendly_name || rid).replace(/^Nook /, "");
          const cur = ncFmt(ra.current_temperature);
          const set = ncFmt(ra.temperature);
          const heat = ra.hvac_action === "heating";
          const trv = ra.trv_entity ? this._hass.states[ra.trv_entity] : null;
          const offline = st.state === "unavailable" || (ra.trv_entity && (!trv || trv.state === "unavailable" || trv.state === "unknown"));
          return `
            <button class="nc-room${heat ? " heat" : ""}${offline ? " offline" : ""}" data-entity="${ncEsc(rid)}" title="${ncEsc(offline ? `${name} — TRV offline` : name)}">
              <span class="nc-room-top"><span class="nc-room-name">${ncEsc(name)}</span>${!offline && heat ? NC_ICONS.flame : ""}</span>
              <span class="nc-room-temp${cur == null ? " unknown" : ""}">${cur == null ? "—" : `${ncEsc(cur)}°`}</span>
              ${offline
                ? `<span class="nc-room-set"><span class="nc-off">Offline</span></span>`
                : `<span class="nc-room-set">${st.state === "off" ? "Off" : `${heat ? "Heating to" : "Set"} ${ncEsc(set ?? "—")}°`}</span>`}
            </button>`;
        })
        .join("");
      if (html !== this._roomsHtml) {
        rooms.innerHTML = html;
        this._roomsHtml = html;
      }
      rooms.style.display = roomIds.length ? "" : "none";
    }
  }
}

class NookCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
    else this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) =>
        ({
          entity: "Nook thermostat",
          name: "Name",
          layout: "Layout",
          show_status: "Show status pills",
          show_modes: "Show mode buttons",
          show_rooms: "Show rooms",
        })[s.name] || s.name;
      this._form.addEventListener("value-changed", (ev) => {
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: ev.detail.value }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = [
      { name: "entity", selector: { entity: { domain: "climate", integration: "nook" } } },
      { name: "name", selector: { text: {} } },
      {
        name: "layout",
        selector: { select: { mode: "dropdown", options: [{ value: "full", label: "Full" }, { value: "compact", label: "Compact" }] } },
      },
      { name: "show_status", selector: { boolean: {} } },
      { name: "show_modes", selector: { boolean: {} } },
      { name: "show_rooms", selector: { boolean: {} } },
    ];
    this._form.data = { layout: "full", show_status: true, show_modes: true, show_rooms: true, ...this._config };
  }
}

/* ------------------------------------------------------------------------------------------
 * Radiators card (type: custom:nook-radiators-card): every Nook room / TRV in one card.
 * Controls go through the Nook room climates — Nook owns the TRV setpoints and would put a
 * TRV changed directly straight back. TRV status (online, battery, valve) is read from the
 * TRV and the other entities on its device.
 * ---------------------------------------------------------------------------------------- */

const NR_STYLES = `
:host { display: block; }
ha-card { overflow: hidden; }
.nr {
  --nc-heat: #F57C00; --nc-heat-soft: #FF9800; --nc-teal-hi: #19D4DE;
  --nc-green: #52C41A; --nc-amber: #FA8C16; --nc-red: #e53935;
  --nc-tint: var(--nc-teal-hi);
  padding: 16px;
  background: radial-gradient(80% 120% at 0% 0%, color-mix(in srgb, var(--nc-tint) 12%, transparent), transparent 65%);
  color: var(--primary-text-color); font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, Roboto, sans-serif));
}
.nr.heating { --nc-tint: var(--nc-heat-soft); }
.nr.off { --nc-tint: #9aa0a6; }
.nr-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.nr-title { font-size: 18px; font-weight: 600; letter-spacing: -0.01em; margin: 0; }
.nr-summary { font-size: 13px; color: var(--secondary-text-color); margin-top: 2px; }
.nr.heating .nr-summary { color: var(--nc-heat-soft); }
.nr-pills, .nr-trv { display: flex; flex-wrap: wrap; gap: 6px; }
.nr-pills { justify-content: flex-end; }
.nc-pill {
  display: inline-flex; align-items: center; gap: 5px; padding: 4px 10px; border-radius: 999px;
  font: inherit; font-size: 12px; font-weight: 600; white-space: nowrap; border: 0;
  background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); color: var(--secondary-text-color);
}
.nr-trv .nc-pill { padding: 2px 8px; font-size: 11px; cursor: pointer; }
.nc-pill svg { width: 13px; height: 13px; }
.nr-trv .nc-pill svg { width: 12px; height: 12px; }
.nc-pill.heat { background: color-mix(in srgb, var(--nc-heat) 16%, transparent); color: var(--nc-heat-soft); }
.nc-pill.ok { background: color-mix(in srgb, var(--nc-green) 16%, transparent); color: var(--nc-green); }
.nc-pill.warn { background: color-mix(in srgb, var(--nc-amber) 16%, transparent); color: var(--nc-amber); }
.nc-pill.bad { background: color-mix(in srgb, var(--nc-red) 16%, transparent); color: var(--nc-red); }

.nr-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 10px; margin-top: 14px; }
.nr-room {
  display: flex; gap: 12px; align-items: center; padding: 12px; border-radius: 14px; min-width: 0;
  background: color-mix(in srgb, var(--primary-text-color) 5%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary-text-color) 8%, transparent);
  transition: background 0.2s ease, border-color 0.2s ease;
}
.nr-room.heat { background: color-mix(in srgb, var(--nc-heat) 9%, transparent); border-color: color-mix(in srgb, var(--nc-heat) 35%, transparent); }
.nr-room.gone { opacity: 0.6; }

.nr-dial { position: relative; width: 104px; aspect-ratio: 1; flex-shrink: 0; touch-action: none; user-select: none; -webkit-user-select: none; }
.nr-dial > svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.nr-dial .track { stroke: color-mix(in srgb, var(--primary-text-color) 10%, transparent); }
.nr-dial .ring { cursor: grab; }
.nr-dial.dragging .ring, .nr-dial.dragging .knob { cursor: grabbing; }
.nr-dial .knob { fill: #fff; stroke: color-mix(in srgb, #000 22%, transparent); stroke-width: 1.5; cursor: grab; filter: drop-shadow(0 1px 2px rgba(0,0,0,0.4)); }
.nr-room.heat .nr-dial .knob { filter: drop-shadow(0 0 5px rgba(255,120,30,0.85)); }
.nr-dial .now-dot { fill: var(--primary-text-color); opacity: 0.75; pointer-events: none; }
.nr-core { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; pointer-events: none; }
.nr-target { font-size: 28px; font-weight: 300; line-height: 1; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; }
.nr-target sup { font-size: 0.45em; vertical-align: top; position: relative; top: 0.2em; margin-left: 1px; }
.nr-target.pending { color: var(--nc-heat-soft); }
.nr-now { font-size: 11px; color: var(--secondary-text-color); margin-top: 3px; font-variant-numeric: tabular-nums; }

.nr-info { display: flex; flex-direction: column; gap: 6px; min-width: 0; flex: 1; }
.nr-top { display: flex; align-items: center; gap: 6px; min-width: 0; }
.nr-name {
  font: inherit; font-size: 15px; font-weight: 600; color: inherit; background: none; border: 0; padding: 0; cursor: pointer;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; min-width: 0;
}
.nr-top svg { width: 15px; height: 15px; color: var(--nc-heat-soft); flex-shrink: 0; }
.nr-status { font-size: 12px; color: var(--secondary-text-color); margin-top: -4px; }
.nr-room.heat .nr-status { color: var(--nc-heat-soft); }
.nr-ctrl { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.nr-steps { display: inline-flex; gap: 6px; }
.nr-step {
  width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; cursor: pointer; padding: 0;
  border: 1px solid color-mix(in srgb, var(--primary-text-color) 14%, transparent);
  background: color-mix(in srgb, var(--primary-text-color) 6%, var(--card-background-color, var(--ha-card-background, #fff)));
  color: var(--primary-text-color); transition: transform 0.1s ease;
}
.nr-step svg { width: 18px; height: 18px; }
.nr-step:active { transform: scale(0.92); }
.nr-step:disabled { opacity: 0.35; cursor: default; }
.nc-seg { display: inline-flex; padding: 2px; border-radius: 999px; background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); }
.nc-mode {
  border: 0; background: transparent; color: var(--secondary-text-color); cursor: pointer;
  padding: 6px 10px; border-radius: 999px; font: inherit; font-size: 12px; font-weight: 600;
  display: inline-flex; align-items: center; gap: 4px;
}
.nc-mode svg { width: 13px; height: 13px; }
.nc-mode.active { background: var(--card-background-color, var(--ha-card-background, #fff)); color: var(--primary-text-color); box-shadow: 0 1px 3px rgba(0,0,0,0.2); }
.nc-mode.active.heat, .nc-mode.active.boost { color: var(--nc-heat-soft); }
.nc-mode.active.eco { color: var(--nc-green); }
.nr-step:focus-visible, .nc-mode:focus-visible, .nr-name:focus-visible, .nr-trv .nc-pill:focus-visible { outline: 2px solid var(--nc-teal-hi); outline-offset: 2px; }
.nr-empty { padding: 20px 4px 4px; color: var(--secondary-text-color); font-size: 14px; }
`;

const NR_ICONS = {
  ...NC_ICONS,
  battery: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M16 4h-1.5V2h-5v2H8a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1zm-1 16H9V6h6z"/><rect fill="currentColor" x="10" class="lvl" y="12" width="4" height="7"/></svg>`,
  valve: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M4 9h3V7h2v2h6V7h2v2h3v2h-2v8h-2v-8H9v8H7v-8H4z"/></svg>`,
  radio: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M5 12a7 7 0 0 1 14 0M8.5 12a3.5 3.5 0 0 1 7 0"/><circle cx="12" cy="15" r="1.8" fill="currentColor"/></svg>`,
};

const NR_GONE = new Set(["unavailable", "unknown"]);

function nrTime(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return "";
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return time;
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  if (d.toDateString() === tomorrow.toDateString()) return `tomorrow ${time}`;
  return `${d.toLocaleDateString([], { weekday: "short" })} ${time}`;
}

class NookRadiatorsCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("nook-radiators-card-editor");
  }

  static getStubConfig() {
    return {};
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._pend = new Map(); // room entity → { value, at, timer, sending, sentStamp }
    this._drag = null; // { id, rel }
    this._ids = null;
    this._lastKey = "";
    this._extrasFor = null;
    this._extras = new Map();
  }

  setConfig(config) {
    if (!config) throw new Error("Invalid configuration");
    if (config.entities != null && !Array.isArray(config.entities)) throw new Error("entities must be a list");
    this._config = { show_trv: true, show_modes: true, ...config };
    this._ids = null;
    this._lastKey = "";
    this._buildShell();
    this._update(true);
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  getCardSize() {
    return 2 + 3 * (this._ids?.length || 1);
  }

  getGridOptions() {
    return { columns: 6, min_columns: 4, rows: "auto" };
  }

  /** Nook room climates to show: the configured list, else every room in Nook's order. */
  _roomIds() {
    const hass = this._hass;
    if (Array.isArray(this._config.entities) && this._config.entities.length) {
      return this._config.entities.map((e) => (typeof e === "string" ? e : e?.entity)).filter(Boolean);
    }
    const home = hass.states[ncFindHome(hass)];
    if (Array.isArray(home?.attributes?.room_entities)) return home.attributes.room_entities;
    return Object.keys(hass.entities || {}).filter(
      (id) => id.startsWith("climate.") && hass.entities[id]?.platform === "nook" && hass.states[id]?.attributes?.room_id
    );
  }

  /** Battery and valve-opening entities on the TRV's device (cached until the registry changes). */
  _trvExtras(trvId) {
    const hass = this._hass;
    if (this._extrasFor !== hass.entities) {
      this._extrasFor = hass.entities;
      this._extras.clear();
    }
    if (this._extras.has(trvId)) return this._extras.get(trvId);
    const out = {};
    const dev = hass.entities?.[trvId]?.device_id;
    if (dev) {
      for (const [id, ent] of Object.entries(hass.entities)) {
        if (ent.device_id !== dev || id === trvId || ent.hidden) continue;
        const st = hass.states[id];
        if (!st) continue;
        const pct = st.attributes.unit_of_measurement === "%";
        if (!out.battery && id.startsWith("sensor.") && st.attributes.device_class === "battery" && pct) out.battery = id;
        else if (!out.valve && /^(sensor|number)\./.test(id) && pct && /valve|position|heating_demand|opening/.test(id)) out.valve = id;
      }
    }
    this._extras.set(trvId, out);
    return out;
  }

  _buildShell() {
    this.shadowRoot.innerHTML = `
      <style>${NR_STYLES}</style>
      <ha-card>
        <div class="nr">
          <div class="nr-head">
            <div><p class="nr-title"></p><div class="nr-summary"></div></div>
            <div class="nr-pills"></div>
          </div>
          <div class="nr-list"></div>
        </div>
      </ha-card>`;
    const list = this.shadowRoot.querySelector(".nr-list");
    list.addEventListener("click", (ev) => this._onClick(ev));
  }

  _buildRooms(ids) {
    const list = this.shadowRoot.querySelector(".nr-list");
    const modes = this._config.show_modes;
    list.innerHTML = ids.length
      ? ids
          .map(
            (id, i) => `
        <div class="nr-room" data-id="${ncEsc(id)}">
          <div class="nr-dial">
            <svg viewBox="0 0 200 200" aria-hidden="true">
              <defs><linearGradient id="nrg${i}" x1="0" y1="1" x2="1" y2="0"><stop class="g0" offset="0"/><stop class="g1" offset="1"/></linearGradient></defs>
              <path class="track" d="${NC_ARC}" fill="none" stroke-width="14" stroke-linecap="round"/>
              <path class="fill" d="${NC_ARC}" pathLength="100" fill="none" stroke="url(#nrg${i})" stroke-width="14" stroke-linecap="round"/>
              <path class="ring" d="${NC_ARC}" fill="none" stroke="transparent" stroke-width="44"/>
              <circle class="now-dot" r="6"/>
              <circle class="knob" r="15"/>
            </svg>
            <div class="nr-core"><div class="nr-target"></div><div class="nr-now"></div></div>
          </div>
          <div class="nr-info">
            <div class="nr-top"><button class="nr-name" data-act="info"></button><span class="nr-flame"></span></div>
            <div class="nr-status"></div>
            ${this._config.show_trv ? `<div class="nr-trv"></div>` : ""}
            <div class="nr-ctrl">
              <span class="nr-steps">
                <button class="nr-step" data-act="step" data-step="-1" aria-label="Lower">${NC_ICONS.minus}</button>
                <button class="nr-step" data-act="step" data-step="1" aria-label="Raise">${NC_ICONS.plus}</button>
              </span>
              ${modes
                ? `<span class="nc-seg">
                    <button class="nc-mode heat" data-act="hvac" data-hvac="heat">${NC_ICONS.flame}Heat</button>
                    <button class="nc-mode" data-act="hvac" data-hvac="off">${NC_ICONS.power}Off</button>
                  </span>
                  <span class="nc-seg">
                    <button class="nc-mode eco" data-act="preset" data-preset="eco">Eco</button>
                    <button class="nc-mode boost" data-act="preset" data-preset="boost">Boost</button>
                  </span>`
                : ""}
            </div>
          </div>
        </div>`
          )
          .join("")
      : `<div class="nr-empty">No Nook rooms yet — add rooms with their TRVs in Nook → Settings → Rooms.</div>`;
    list.querySelectorAll(".nr-room").forEach((row) => this._bindDial(row));
  }

  _onClick(ev) {
    const btn = ev.target.closest("[data-act]");
    const row = ev.target.closest(".nr-room");
    if (!btn || !row) return;
    const id = row.dataset.id;
    const act = btn.dataset.act;
    if (act === "info") this._moreInfo(id);
    else if (act === "trv") this._moreInfo(btn.dataset.entity);
    else if (act === "step") this._step(id, Number(btn.dataset.step));
    else if (act === "hvac") this._call(id, "set_hvac_mode", { hvac_mode: btn.dataset.hvac }).catch(() => {});
    else if (act === "preset") {
      const current = this._hass?.states[id]?.attributes?.preset_mode;
      // Tapping the active preset turns it off again.
      this._call(id, "set_preset_mode", { preset_mode: current === btn.dataset.preset ? "none" : btn.dataset.preset }).catch(() => {});
    }
  }

  _bindDial(row) {
    const id = row.dataset.id;
    const dial = row.querySelector(".nr-dial");
    const knob = row.querySelector(".knob");
    const local = (ev) => {
      const r = dial.getBoundingClientRect();
      return { x: ((ev.clientX - r.left) / r.width) * 200 - 100, y: ((ev.clientY - r.top) / r.height) * 200 - 100 };
    };
    const fromPointer = (ev) => {
      const { x, y } = local(ev);
      let rel = ((Math.atan2(y, x) * 180) / Math.PI - 135 + 720) % 360;
      // In the open gap at the bottom, stay at the end the drag came from (no min↔max flicker).
      if (rel > 270) rel = (this._drag?.rel ?? 135) > 135 ? 270 : 0;
      this._drag.rel = rel;
      const { lo, hi, step } = this._limits(id);
      return Math.min(hi, Math.max(lo, Math.round((lo + (rel / 270) * (hi - lo)) / step) * step));
    };
    dial.addEventListener("pointerdown", (ev) => {
      if (ev.button !== undefined && ev.button !== 0) return;
      // Only the ring band (and the handle) starts a drag, not the numbers in the middle.
      const { x, y } = local(ev);
      const dist = Math.hypot(x, y);
      if (ev.target !== knob && (dist < 58 || dist > 108)) return;
      ev.preventDefault();
      const { lo, hi } = this._limits(id);
      const cur = Number(this._shownTarget(id) ?? lo);
      this._drag = { id, rel: ((cur - lo) / (hi - lo)) * 270 };
      dial.classList.add("dragging");
      knob.setAttribute("r", "19");
      try {
        dial.setPointerCapture(ev.pointerId);
      } catch {
        // pointer already gone
      }
      this._setPending(id, fromPointer(ev), false);
    });
    dial.addEventListener("pointermove", (ev) => {
      if (this._drag?.id !== id) return;
      const value = fromPointer(ev);
      if (value !== this._pend.get(id)?.value) this._setPending(id, value, false);
    });
    const end = () => {
      if (this._drag?.id !== id) return;
      this._drag = null;
      dial.classList.remove("dragging");
      knob.setAttribute("r", "15");
      this._update(true);
      this._queueSend(id, 0);
    };
    dial.addEventListener("pointerup", end);
    dial.addEventListener("pointercancel", end);
  }

  _limits(id) {
    const a = this._hass?.states[id]?.attributes || {};
    return { lo: Number(a.min_temp ?? 7), hi: Number(a.max_temp ?? 30), step: Number(a.target_temp_step) || 0.5 };
  }

  _shownTarget(id) {
    const st = this._hass?.states[id];
    const reported = st?.attributes?.temperature;
    const p = this._pend.get(id);
    if (p) {
      const idle = !p.timer && !p.sending && this._drag?.id !== id;
      const matches = reported != null && Number(reported) === p.value;
      // HA wrote a new state after our call: show what Nook actually set.
      const echoed = p.sentStamp != null && st?.last_updated !== p.sentStamp;
      if (idle && (matches || echoed || Date.now() - p.at > 15000)) this._pend.delete(id);
      else return p.value;
    }
    return reported;
  }

  _step(id, direction) {
    const { lo, hi, step } = this._limits(id);
    const base = Number(this._shownTarget(id) ?? 20);
    this._setPending(id, Math.min(hi, Math.max(lo, Math.round((base + direction * step) / step) * step)), true);
  }

  _setPending(id, value, send) {
    // Mutate in place: a queued send holds this object and must see the latest value.
    const p = this._pend.get(id) || {};
    p.value = value;
    p.at = Date.now();
    this._pend.set(id, p);
    this._paintRoom(id, true);
    if (send) this._queueSend(id, 700);
  }

  _queueSend(id, delay) {
    const p = this._pend.get(id);
    if (!p) return;
    clearTimeout(p.timer);
    p.timer = setTimeout(async () => {
      p.timer = null;
      if (this._pend.get(id) !== p) return;
      p.sending = true;
      p.sentStamp = this._hass?.states[id]?.last_updated ?? null;
      try {
        await this._call(id, "set_temperature", { temperature: p.value }, false);
        p.at = Date.now();
      } catch {
        this._pend.delete(id);
      } finally {
        p.sending = false;
        this._update(true);
      }
    }, delay);
  }

  async _call(id, service, data, toastOnError = true) {
    if (!this._hass || !id) return;
    try {
      await this._hass.callService("climate", service, { entity_id: id, ...data });
    } catch (e) {
      if (toastOnError) {
        this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message: `Nook: ${e?.message || e}` }, bubbles: true, composed: true }));
      }
      throw e;
    }
  }

  _moreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  _update(force = false) {
    if (!this._config || !this._hass || !this.shadowRoot.querySelector(".nr")) return;
    const hass = this._hass;
    const ids = this._roomIds();
    // Only redraw when something shown changed (hass updates arrive constantly).
    const key = [
      ids.join(","),
      hass.states[ncFindHome(hass)]?.last_updated, // house state drives the header and tint
      ...ids.map((id) => {
        const st = hass.states[id];
        const trv = st?.attributes?.trv_entity;
        if (!trv) return `${st?.last_updated}`;
        const ex = this._config.show_trv ? this._trvExtras(trv) : {};
        return [st?.last_updated, hass.states[trv]?.last_updated, ex.battery && hass.states[ex.battery]?.state, ex.valve && hass.states[ex.valve]?.state].join("/");
      }),
    ].join("|");
    if (!force && key === this._lastKey) return;
    if (!force && this._drag) return; // don't fight the user's drag
    this._lastKey = key;

    if (!this._ids || this._ids.join(",") !== ids.join(",")) {
      this._ids = ids;
      this._buildRooms(ids);
    }
    ids.forEach((id) => this._paintRoom(id));
    this._paintHead(ids);
  }

  _paintHead(ids) {
    const hass = this._hass;
    const root = this.shadowRoot;
    root.querySelector(".nr-title").textContent = this._config.title || "Radiators";
    let heating = 0;
    let offline = 0;
    let open = 0;
    ids.forEach((id) => {
      const st = hass.states[id];
      const trvId = st?.attributes?.trv_entity;
      const trv = trvId ? hass.states[trvId] : null;
      if (!st || NR_GONE.has(st.state) || (trvId && (!trv || NR_GONE.has(trv.state)))) offline += 1;
      else if (st.state !== "off" && st.attributes.hvac_action === "heating") heating += 1;
      if (st?.attributes?.window_open) open += 1;
    });
    // Same background tint as the house card next to it: grey when the house is off,
    // warm while heating, teal otherwise.
    const home = hass.states[ncFindHome(hass)];
    const houseOff = home?.state === "off";
    const card = root.querySelector(".nr");
    card.classList.toggle("off", houseOff);
    card.classList.toggle("heating", !houseOff && (heating > 0 || home?.attributes?.hvac_action === "heating"));
    const n = ids.length;
    root.querySelector(".nr-summary").textContent = !n
      ? ""
      : heating
        ? `${heating} of ${n} room${n === 1 ? "" : "s"} heating`
        : `${n} room${n === 1 ? "" : "s"} · none heating`;
    const out = [];
    if (offline) out.push(`<span class="nc-pill bad">${NR_ICONS.radio}${offline} TRV${offline === 1 ? "" : "s"} offline</span>`);
    if (open) out.push(`<span class="nc-pill warn">Window open</span>`);
    if (home?.attributes?.boiler_on) out.push(`<span class="nc-pill heat">${NC_ICONS.flame}Boiler on</span>`);
    if (home?.attributes?.summer_mode) out.push(`<span class="nc-pill warn">Summer</span>`);
    const pills = root.querySelector(".nr-pills");
    const html = out.join("");
    if (pills.innerHTML !== html) pills.innerHTML = html;
  }

  _paintRoom(id, dialOnly = false) {
    const row = [...this.shadowRoot.querySelectorAll(".nr-room")].find((r) => r.dataset.id === id);
    if (!row) return;
    const hass = this._hass;
    const st = hass.states[id];
    const a = st?.attributes || {};
    const gone = !st || NR_GONE.has(st.state);
    const off = !gone && st.state === "off";
    const heating = !gone && !off && a.hvac_action === "heating";
    const target = gone ? null : this._shownTarget(id);
    const { lo, hi } = this._limits(id);
    const pos = (t) => (t == null || !Number.isFinite(Number(t)) ? null : Math.min(1, Math.max(0, (Number(t) - lo) / (hi - lo))));

    row.classList.toggle("heat", heating);
    row.classList.toggle("gone", gone);

    // Dial
    const fill = (pos(target) ?? 0) * 100;
    const fillEl = row.querySelector(".fill");
    fillEl.setAttribute("stroke-dasharray", `${fill.toFixed(1)} 100`);
    fillEl.style.display = fill > 0 ? "" : "none";
    const [c0, c1] = off || gone ? ["#5f656b", "#8a9096"] : heating ? ["#FFB74D", "#F4511E"] : ["#FFD180", "#FF9800"];
    row.querySelector(".g0").setAttribute("stop-color", c0);
    row.querySelector(".g1").setAttribute("stop-color", c1);
    const place = (el, p) => {
      if (p == null) {
        el.style.display = "none";
        return;
      }
      const ang = ((135 + 270 * p) * Math.PI) / 180;
      el.style.display = "";
      el.setAttribute("cx", (100 + 84 * Math.cos(ang)).toFixed(1));
      el.setAttribute("cy", (100 + 84 * Math.sin(ang)).toFixed(1));
    };
    place(row.querySelector(".now-dot"), gone ? null : pos(a.current_temperature));
    place(row.querySelector(".knob"), gone || off ? null : pos(target));
    const t = row.querySelector(".nr-target");
    const shown = ncFmt(target);
    t.innerHTML = gone ? "—" : off ? "Off" : shown == null ? "—" : `${ncEsc(shown)}<sup>°</sup>`;
    t.classList.toggle("pending", this._pend.has(id));
    const now = ncFmt(a.current_temperature);
    row.querySelector(".nr-now").textContent = gone || now == null ? "" : `Now ${now}°`;
    const [minus, plus] = row.querySelectorAll(".nr-step");
    minus.disabled = gone || off || (target != null && Number(target) <= lo);
    plus.disabled = gone || off || (target != null && Number(target) >= hi);

    if (dialOnly) return;

    const name = a.room_name || String(a.friendly_name || id).replace(/^Nook /, "");
    const nameEl = row.querySelector(".nr-name");
    if (nameEl.textContent !== name) nameEl.textContent = name;
    nameEl.title = `${name} — more settings`;
    row.querySelector(".nr-flame").innerHTML = heating ? NC_ICONS.flame : "";

    // TRV state
    const trvId = a.trv_entity;
    const trv = trvId ? hass.states[trvId] : null;
    const trvGone = !!trvId && (!trv || NR_GONE.has(trv.state));

    let status;
    if (gone) status = "Unavailable";
    else if (off) status = "Off";
    else if (a.summer_mode) status = "Summer mode — paused";
    else if (a.window_open) status = "Window open — paused";
    else if (heating) status = `Heating to ${ncFmt(target) ?? "—"}°`;
    else if (trvGone) status = `Set to ${ncFmt(target) ?? "—"}°`; // the TRV pill says why nothing happens
    else if (a.calls_for_heat === false && trv?.attributes?.hvac_action === "heating") status = "Valve open (doesn't call the boiler)";
    else if (a.current_temperature != null && target != null && Number(a.current_temperature) >= Number(target)) status = "Up to temperature";
    else status = `Set to ${ncFmt(target) ?? "—"}°`;
    if (!gone && !off) {
      if (a.preset_mode === "boost") status += " · Boost";
      else if (a.preset_mode === "eco") status += " · Eco";
      else if (a.hold_until) status += ` · until ${nrTime(a.hold_until)}`;
    }
    row.querySelector(".nr-status").textContent = status;

    const trvBox = row.querySelector(".nr-trv");
    if (trvBox) {
      const out = [];
      const pill = (cls, icon, text, entity, title) =>
        out.push(`<button class="nc-pill ${cls}" data-act="trv" data-entity="${ncEsc(entity)}" title="${ncEsc(title)}">${icon}${ncEsc(text)}</button>`);
      if (!trvId) {
        // Room without a TRV: nothing to report.
      } else if (trvGone) {
        pill("bad", NR_ICONS.radio, "TRV offline", trvId, `${trvId} is ${trv ? trv.state : "missing"} — Nook can't move the valve`);
      } else {
        pill("ok", NR_ICONS.radio, "TRV online", trvId, trvId);
        const ex = this._trvExtras(trvId);
        const bat = ex.battery ? Number(hass.states[ex.battery]?.state) : NaN;
        if (Number.isFinite(bat)) pill(bat <= 20 ? "bad" : bat <= 35 ? "warn" : "", NR_ICONS.battery, `${Math.round(bat)}%`, ex.battery, "Battery");
        const valveRaw = ex.valve ? hass.states[ex.valve]?.state : trv.attributes.pi_heating_demand ?? trv.attributes.valve_position;
        const valve = Number(valveRaw);
        if (valveRaw != null && valveRaw !== "" && Number.isFinite(valve)) {
          pill(valve > 0 ? "heat" : "", NR_ICONS.valve, `Valve ${Math.round(valve)}%`, ex.valve || trvId, "Valve opening");
        } else if (trv.attributes.hvac_action === "heating") {
          pill("heat", NR_ICONS.valve, "Valve open", trvId, "The TRV reports it is heating");
        }
        // Nook pushes its setpoint to the TRV; show when they don't match yet.
        const trvSet = Number(trv.attributes.temperature);
        const nookSet = Number(st?.attributes?.temperature);
        if (!gone && !off && !a.window_open && !a.summer_mode && Number.isFinite(trvSet) && Number.isFinite(nookSet) && Math.abs(trvSet - nookSet) >= 0.05) {
          pill("warn", "", `TRV at ${ncFmt(trvSet)}°`, trvId, `Nook is setting the TRV to ${ncFmt(nookSet)}°`);
        }
      }
      const html = out.join("");
      if (trvBox.innerHTML !== html) trvBox.innerHTML = html;
      trvBox.style.display = html ? "" : "none";
    }

    row.querySelectorAll("[data-hvac]").forEach((b) => {
      b.classList.toggle("active", !gone && b.dataset.hvac === st.state);
      b.disabled = gone;
    });
    row.querySelectorAll("[data-preset]").forEach((b) => {
      b.classList.toggle("active", !gone && b.dataset.preset === a.preset_mode);
      b.disabled = gone;
    });
  }
}

class NookRadiatorsCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
    else this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) =>
        ({ title: "Title", entities: "Rooms (blank = all, in Nook's order)", show_trv: "Show TRV status (online, battery, valve)", show_modes: "Show mode buttons" })[s.name] ||
        s.name;
      this._form.addEventListener("value-changed", (ev) => {
        const config = { ...ev.detail.value };
        if (Array.isArray(config.entities) && !config.entities.length) delete config.entities;
        if (!config.title) delete config.title;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = [
      { name: "title", selector: { text: {} } },
      { name: "entities", selector: { entity: { multiple: true, domain: "climate", integration: "nook" } } },
      { name: "show_trv", selector: { boolean: {} } },
      { name: "show_modes", selector: { boolean: {} } },
    ];
    this._form.data = { show_trv: true, show_modes: true, ...this._config };
  }
}

const NC_ELEMENTS = {
  "nook-card": NookCard,
  "nook-card-editor": NookCardEditor,
  "nook-radiators-card": NookRadiatorsCard,
  "nook-radiators-card-editor": NookRadiatorsCardEditor,
};

function ncDefineElements() {
  // Read window.customElements now, not when the script started: see below.
  const registry = window.customElements;
  for (const [tag, cls] of Object.entries(NC_ELEMENTS)) {
    if (!registry.get(tag)) registry.define(tag, cls);
  }
}

// This file is loaded with add_extra_js_url, so from cache it can run before
// HA's frontend boots. The frontend swaps in its own custom-element registry
// as it starts, and anything defined in the old one is invisible to Lovelace
// ("Custom element doesn't exist" until a lucky refresh). So wait until the
// app element is registered in the current registry, then define there;
// cards already drawn as errors rebuild themselves once their tag appears.
(function ncRegisterWhenReady(started = Date.now()) {
  if (window.customElements.get("home-assistant") || Date.now() - started > 15000) {
    ncDefineElements();
    return;
  }
  setTimeout(() => ncRegisterWhenReady(started), 25);
})();

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "nook-card")) {
  window.customCards.push({
    type: "nook-card",
    name: "Nook",
    description: "Dial with setpoint control, modes, status and rooms for Nook.",
    preview: true,
    documentationURL: "https://github.com/james194zt/nook_thermostat",
  });
}
if (!window.customCards.some((c) => c.type === "nook-radiators-card")) {
  window.customCards.push({
    type: "nook-radiators-card",
    name: "Nook Radiators",
    description: "Every Nook room's radiator / TRV: setpoint, Heat/Off, Eco/Boost and TRV status (online, battery, valve).",
    preview: true,
    documentationURL: "https://github.com/james194zt/nook_thermostat",
  });
}
console.info(`%c NOOK-CARD %c ${NOOK_CARD_VERSION} `, "color:#fff;background:#08979C;border-radius:3px 0 0 3px", "color:#08979C;background:#e6f7f7;border-radius:0 3px 3px 0");
