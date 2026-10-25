/* Usage page: the last 24 hours of heating, gas/energy and Leaf, one swipe left of the dial.

   The page sits to the dial's right: a finger moving right-to-left brings it in, left-to-right
   (or tapping the first page dot) returns. Never from the left edge: that swipe opens Fully's menu. It always comes back to the dial on its own after a minute,
   and when the screen sleeps or wakes, so nobody walks up to a report. */

const RETURN_AFTER_MS = 60000;
const REFRESH_MS = 60000;
// How far a finger must travel (share of the width) or how fast, to turn the page.
const COMMIT_SHARE = 0.25;
const COMMIT_SPEED = 0.5; // px per ms
const SLOP_PX = 12;
// Fully Kiosk opens its menu on a swipe from the left edge; leave those alone.
const LEFT_EDGE_PX = 28;

// Two-tone icons on white badges: cartoon-bright on the coloured tiles.
const ICONS = {
  heat: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#FF7A1A" d="M12 1.8c.6 3.4-1.7 5.3-3.4 7.3C7.1 10.9 5.6 12.8 5.6 15.6a6.4 6.4 0 0 0 12.8 0c0-2.8-1.4-4.9-2.8-6.5-.3 1.7-1.2 2.9-2.5 3.4.7-4-.3-8.1-1.1-10.7z"/><path fill="#FFC53D" d="M12 11.2c.3 1.8-.9 2.8-1.8 3.8-.7.8-1.3 1.6-1.3 2.8a3.1 3.1 0 0 0 6.2 0c0-1.5-.8-2.6-1.6-3.4-.2.8-.6 1.3-1.2 1.6.3-1.8-.1-3.6-.3-4.8z"/></svg>`,
  // Blue Bunsen-burner flame: light outer flame, deeper blue core.
  gas: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#7FD3FF" d="M12 1.6c2.6 3.3 6.2 7.4 6.2 12.2a6.2 6.2 0 0 1-12.4 0c0-2.6 1.1-4.7 2.5-6.6.3 1.6 1.1 2.7 2.2 3.2-.6-3.3.4-6.3 1.5-8.8z"/><path fill="#1E6FE0" d="M12 9.4c1.4 1.9 3.1 3.9 3.1 6.3a3.1 3.1 0 0 1-6.2 0c0-1.4.6-2.5 1.4-3.5.2.8.6 1.4 1.1 1.7-.2-1.7.1-3.1.6-4.5z"/></svg>`,
  leaf: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#6CC24A" d="M6.6 17.4C4.6 9.9 10.6 4.3 20 4z"/><path fill="#3E9B34" d="M20 4c.3 9.4-5.4 15.4-13.4 13.4z"/><path fill="none" stroke="#2F7D2A" stroke-width="1.7" stroke-linecap="round" d="M3.6 20.4 7.4 16.6"/></svg>`,
  leafSmall: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M6.6 17.4C4.6 9.9 10.6 4.3 20 4z"/><path fill="currentColor" opacity=".68" d="M20 4c.3 9.4-5.4 15.4-13.4 13.4z"/><path fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" d="M3.6 20.4 7.4 16.6"/></svg>`,
};

const DAY_LETTERS = ["S", "M", "T", "W", "T", "F", "S"];

function el(id) {
  return document.getElementById(id);
}

function fmtDuration(minutes) {
  const m = Math.max(0, Math.round(Number(minutes) || 0));
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return m % 60 ? `${h}h ${m % 60}m` : `${h}h`;
}

// A meter in kWh or gas volume (m³, ft³, CCF): small volumes need more decimals.
function fmtAmount(value, unit = "kWh") {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return "--";
  if (n >= 100) return n.toFixed(0);
  if (unit !== "kWh" && n < 10) return n.toFixed(2);
  return n.toFixed(1);
}

// The chart's smallest full scale, about 0.5 kWh of gas in each unit, so a quiet
// night doesn't fill the chart with tall bars.
const CHART_FLOOR = { kWh: 0.5, "m³": 0.05, "ft³": 1.6, CCF: 0.016, MCF: 0.0016 };

function svgEl(name, attrs, parent) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  parent?.appendChild(node);
  return node;
}

export class UsagePage {
  /**
   * @param {object} opts
   * @param {HTMLElement} opts.dialPage  the thermostat page (.app)
   * @param {() => any} opts.getClient   the HA client (needs request())
   * @param {(ev: Event) => boolean} opts.swipeAllowed  false where a drag means something else
   */
  constructor({ dialPage, getClient, swipeAllowed }) {
    this.dialPage = dialPage;
    this.page = el("usagePage");
    this.getClient = getClient;
    this.swipeAllowed = swipeAllowed || (() => true);
    this.open = false;
    this.data = null;
    this.returnTimer = null;
    this.refreshTimer = null;
    this.gesture = null;
    this.swallowClick = false;

    el("usageHeatIcon").innerHTML = ICONS.heat;
    el("usageGasIcon").innerHTML = ICONS.gas;
    el("usageLeafIcon").innerHTML = ICONS.leaf;

    for (const dot of document.querySelectorAll(".page-dot")) {
      dot.addEventListener("click", () => this.show(dot.dataset.go === "usage"));
    }
    this.page.addEventListener("pointerdown", () => this.armReturn(), true);

    document.addEventListener("pointerdown", (ev) => this.onDown(ev), true);
    document.addEventListener("pointermove", (ev) => this.onMove(ev), true);
    document.addEventListener("pointerup", (ev) => this.onUp(ev), true);
    document.addEventListener("pointercancel", () => this.onCancel(), true);
    // A swipe that started on a button must not also press it.
    document.addEventListener(
      "click",
      (ev) => {
        if (!this.swallowClick) return;
        this.swallowClick = false;
        ev.stopPropagation();
        ev.preventDefault();
      },
      true
    );

    if (typeof ResizeObserver === "function") {
      new ResizeObserver(() => this.open && this.drawChart()).observe(el("usageChart"));
    }
  }

  /* —— Paging —— */

  show(open, { animate = true } = {}) {
    clearTimeout(this.returnTimer);
    clearInterval(this.refreshTimer);
    this.open = open;
    this.page.hidden = false;
    this.setOffset(open ? 1 : 0, animate);
    if (open) {
      this.armReturn();
      this.refresh();
      this.refreshTimer = setInterval(() => this.refresh(), REFRESH_MS);
      requestAnimationFrame(() => this.drawChart());
    } else {
      // Off screen and idle: take it out of the layout.
      const hide = () => {
        if (!this.open) this.page.hidden = true;
      };
      if (animate) setTimeout(hide, 320);
      else hide();
    }
  }

  /** 0 = dial on screen, 1 = usage on screen. */
  setOffset(p, animate) {
    const w = window.innerWidth;
    const t = animate ? "transform 0.3s cubic-bezier(0.2, 0.8, 0.2, 1)" : "none";
    this.page.style.transition = t;
    this.dialPage.style.transition = t;
    this.page.style.transform = `translate3d(${((1 - p) * w).toFixed(1)}px,0,0)`;
    this.dialPage.style.transform = p > 0 ? `translate3d(${(-p * w).toFixed(1)}px,0,0)` : "";
  }

  armReturn() {
    clearTimeout(this.returnTimer);
    if (this.open) this.returnTimer = setTimeout(() => this.show(false), RETURN_AFTER_MS);
  }

  /** Screen asleep, woken, or the screensaver: always back on the dial. */
  resetToDial() {
    if (this.open) this.show(false, { animate: false });
  }

  /* —— Swipe —— */

  onDown(ev) {
    this.gesture = null;
    if (ev.pointerType === "mouse" && ev.button !== 0) return;
    if (this.dialPage.hidden) return;
    if (ev.clientX < LEFT_EDGE_PX) return;
    if (!this.open && !this.swipeAllowed(ev)) return;
    this.gesture = { x: ev.clientX, y: ev.clientY, t: performance.now(), id: ev.pointerId, locked: false, dx: 0 };
  }

  onMove(ev) {
    const g = this.gesture;
    if (!g || ev.pointerId !== g.id) return;
    const dx = ev.clientX - g.x;
    const dy = ev.clientY - g.y;
    if (!g.locked) {
      if (Math.abs(dx) < SLOP_PX && Math.abs(dy) < SLOP_PX) return;
      // Sideways, and the way that leads somewhere: leftwards from the dial, rightwards from usage.
      const sideways = Math.abs(dx) > Math.abs(dy) * 1.5;
      const towards = this.open ? dx > 0 : dx < 0;
      if (!sideways || !towards) {
        this.gesture = null;
        return;
      }
      g.locked = true;
      this.page.hidden = false;
      if (!this.open) this.refresh();
    }
    g.dx = dx;
    const w = window.innerWidth || 1;
    const p = this.open ? 1 - Math.max(0, dx) / w : Math.max(0, -dx) / w;
    this.setOffset(Math.min(1, Math.max(0, p)), false);
  }

  onUp(ev) {
    const g = this.gesture;
    this.gesture = null;
    if (!g || !g.locked || ev.pointerId !== g.id) return;
    this.swallowClick = true;
    setTimeout(() => (this.swallowClick = false), 400);
    const w = window.innerWidth || 1;
    const speed = Math.abs(g.dx) / Math.max(1, performance.now() - g.t);
    const far = Math.abs(g.dx) > w * COMMIT_SHARE || speed > COMMIT_SPEED;
    this.show(far ? !this.open : this.open);
  }

  onCancel() {
    const g = this.gesture;
    this.gesture = null;
    if (g?.locked) this.show(this.open);
  }

  /* —— Data —— */

  async refresh() {
    const client = this.getClient();
    if (!client?.request) return;
    try {
      this.data = await client.request("nook/get_wall_usage");
      this.render();
    } catch {
      // Keep what's on screen; the next refresh tries again.
    }
  }

  render() {
    const d = this.data;
    if (!d) return;
    el("usageLive")?.classList.toggle("hidden", !d.heating_now);

    el("usageOn").textContent = fmtDuration(d.on_minutes);
    const runs = Number(d.run_count) || 0;
    const diff = Math.round((Number(d.on_minutes) || 0) - (Number(d.prev_on_minutes) || 0));
    const vs =
      d.prev_on_minutes == null || Math.abs(diff) < 5
        ? ""
        : ` · ${diff < 0 ? "▼" : "▲"} ${fmtDuration(Math.abs(diff))}`;
    el("usageRuns").textContent = `${runs} ${runs === 1 ? "run" : "runs"}${vs}`;

    const energy = d.energy;
    el("usageGasTile")?.classList.toggle("hidden", !energy);
    if (energy) {
      const unit = energy.unit || "kWh";
      el("usageKwh").textContent = fmtAmount(energy.today, unit);
      el("usageUnit").textContent = unit;
      const gas = energy.kind === "volume" || /gas/i.test(`${energy.entity_id} ${energy.name}`);
      el("usageKwhLabel").textContent = gas ? "Gas today" : "Energy today";
      const y = energy.yesterday;
      if (y == null) {
        el("usageKwhSub").textContent = "";
      } else {
        const delta = Number(energy.today) - Number(y);
        el("usageKwhSub").textContent =
          Math.abs(delta) < (CHART_FLOOR[unit] || 0.5) / 10 ? "Same as yesterday" : `${delta < 0 ? "▼" : "▲"} ${fmtAmount(Math.abs(delta), unit)} vs yesterday`;
      }
    }

    const leaf = d.leaf || {};
    const leafOn = leaf.enabled !== false;
    el("usageLeafTile")?.classList.toggle("hidden", !leafOn);
    el("usageWeek")?.classList.toggle("hidden", !leafOn);
    this.page.classList.toggle("no-leaf", !leafOn);
    this.page.classList.toggle("no-energy", !energy);
    if (leafOn) this.renderLeaf(leaf);
    this.drawChart();
  }

  renderLeaf(leaf) {
    const today = Number(leaf.minutes_today) || 0;
    const goal = Number(leaf.goal_minutes) || 30;
    el("usageLeafToday").textContent = fmtDuration(today);
    el("usageLeafSub").textContent =
      today >= goal ? "Leaf earned today ✓" : `${Math.ceil(goal - today)}m to go for a leaf`;

    const streak = Number(leaf.days_streak) || 0;
    el("usageStreak").textContent = String(streak);

    const box = el("usageWeekDays");
    box.innerHTML = "";
    const days = leaf.week_days || [];
    days.forEach((day, i) => {
      const isToday = i === days.length - 1;
      const share = Math.min(1, (Number(day.minutes) || 0) / goal);
      const cell = document.createElement("div");
      cell.className = `week-day${day.earned ? " earned" : ""}${isToday ? " today" : ""}`;
      const date = new Date(`${day.date}T12:00:00`);
      const letter = Number.isNaN(date.getTime()) ? "" : DAY_LETTERS[date.getDay()];
      // Today fills a ring towards its leaf; earned days are solid green.
      const ring =
        isToday && !day.earned
          ? `<svg class="day-ring" viewBox="0 0 36 36"><circle cx="18" cy="18" r="16" pathLength="100" stroke-dasharray="${(share * 100).toFixed(1)} 100"/></svg>`
          : "";
      cell.innerHTML = `<span class="day-dot">${ring}${ICONS.leafSmall}</span><span class="day-letter">${letter}</span>`;
      box.appendChild(cell);
    });
  }

  /* —— Chart: drawn in real pixels (no stretched viewBox — that makes jagged steps) —— */

  drawChart() {
    const host = el("usageChart");
    const svg = el("usageChartSvg");
    const d = this.data;
    if (!host || !svg || this.page.hidden) return;
    const W = Math.round(svg.clientWidth || host.clientWidth);
    const H = Math.round(svg.clientHeight || host.clientHeight);
    if (!W || !H) return;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML = "";

    const vmin = Math.min(window.innerWidth, window.innerHeight) / 100;
    const font = Math.max(10, 2.5 * vmin);
    const padL = 1.5 * vmin;
    const padR = 1.5 * vmin;
    // The legend sits over the chart's top-left corner: start the plot below it, with
    // room for the value label above the tallest bar (it used to land on "Target").
    const legend = el("usageLegend");
    const sp = d?.setpoints || [];
    if (legend) {
      legend.innerHTML = d
        ? [
            d.energy ? `<span class="lg lg-gas">${d.energy.unit || "kWh"}</span>` : "",
            `<span class="lg lg-run">Boiler on</span>`,
            sp.length ? `<span class="lg lg-target">Target</span>` : "",
          ].join("")
        : "";
    }
    const legendBottom = legend && legend.offsetHeight ? legend.offsetTop + legend.offsetHeight : 3.2 * vmin;
    const padT = legendBottom + font * 1.3 + 0.6 * vmin;
    const axisH = font * 1.7;
    const stripH = Math.max(6, 2.2 * vmin);
    const plotW = W - padL - padR;
    const top = padT;
    const bottom = H - axisH - stripH - 0.8 * vmin; // bars stand on this line
    const plotH = Math.max(10, bottom - top);
    const span = Number(d?.window_minutes) || 1440;
    const x = (m) => padL + (Math.min(span, Math.max(0, m)) / span) * plotW;

    const defs = svgEl("defs", {}, svg);
    const grad = svgEl("linearGradient", { id: "uBar", x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    svgEl("stop", { offset: 0, "stop-color": "#6FD0FF" }, grad);
    svgEl("stop", { offset: 1, "stop-color": "#1E6FE0" }, grad);
    const heatGrad = svgEl("linearGradient", { id: "uHeat", x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    svgEl("stop", { offset: 0, "stop-color": "#FF9800", "stop-opacity": 0.32 }, heatGrad);
    svgEl("stop", { offset: 1, "stop-color": "#FF9800", "stop-opacity": 0.06 }, heatGrad);

    // Hour grid every 6 h, on the local clock.
    const now = Date.now();
    const start = now - span * 60000;
    const first = new Date(start);
    first.setMinutes(0, 0, 0);
    const labels = [];
    for (let t = first.getTime() + 3600000; t < now; t += 3600000) {
      const h = new Date(t).getHours();
      if (h % 6) continue;
      const m = (t - start) / 60000;
      svgEl("line", { x1: x(m), x2: x(m), y1: top, y2: bottom + stripH + 0.8 * vmin, class: "u-grid" }, svg);
      labels.push({ m, text: `${String(h).padStart(2, "0")}:00` });
    }
    svgEl("line", { x1: padL, x2: W - padR, y1: bottom, y2: bottom, class: "u-base" }, svg);

    if (!d) return;
    const chips = [];
    const runs = d.runs || [];
    const energy = d.energy;

    // Boiler on: a warm wash behind everything, and a bright strip underneath.
    for (const r of runs) {
      const x0 = x(r.s);
      const w = Math.max(2, x(r.e) - x0);
      if (energy) svgEl("rect", { x: x0, y: top, width: w, height: bottom - top, fill: "url(#uHeat)" }, svg);
      svgEl("rect", { x: x0, y: bottom + 0.8 * vmin, width: w, height: stripH, rx: stripH / 2, class: "u-run" }, svg);
    }

    if (energy) {
      // Used per hour.
      const hourly = (energy.hourly || []).filter((h) => h.m + 60 > 0);
      const unit = energy.unit || "kWh";
      const max = Math.max(CHART_FLOOR[unit] ?? 0.5, ...hourly.map((h) => Number(h.v) || 0));
      const slot = (60 / span) * plotW;
      const gap = Math.max(1.5, slot * 0.18);
      for (const h of hourly) {
        const v = Number(h.v) || 0;
        if (v <= 0) continue;
        const x0 = x(h.m) + gap / 2;
        const x1 = x(h.m + 60) - gap / 2;
        if (x1 <= x0) continue;
        const bh = Math.max(2, (v / max) * plotH * 0.92);
        const r = Math.min(4, (x1 - x0) / 2);
        // Rounded top, square base.
        svgEl(
          "path",
          {
            d: `M${x0},${bottom} V${bottom - bh + r} Q${x0},${bottom - bh} ${x0 + r},${bottom - bh} H${x1 - r} Q${x1},${bottom - bh} ${x1},${bottom - bh + r} V${bottom} Z`,
            fill: "url(#uBar)",
          },
          svg
        );
      }
      // Name the busiest hour on top of its bar.
      const busiest = hourly.reduce((a, h) => ((Number(h.v) || 0) > (Number(a?.v) || 0) ? h : a), null);
      if (busiest && Number(busiest.v) > 0) {
        const cx = (x(busiest.m) + x(busiest.m + 60)) / 2;
        const ty = bottom - Math.max(2, (Number(busiest.v) / max) * plotH * 0.92) - 0.8 * vmin;
        chips.push({ x: Math.min(W - padR - font, Math.max(padL + font, cx)), y: ty, text: fmtAmount(busiest.v, unit), anchor: "middle", cls: "u-note" });
      }
    } else {
      // No meter: the runs themselves are the chart.
      for (const r of runs) {
        const x0 = x(r.s);
        const w = Math.max(2, x(r.e) - x0);
        svgEl("rect", { x: x0, y: top + plotH * 0.08, width: w, height: plotH * 0.92, rx: Math.min(3, w / 2), class: "u-run-tall" }, svg);
      }
    }

    // Target: a step line in its own band at the top of the plot.
    if (sp.length) {
      const temps = sp.map((s) => Number(s.t));
      const lo = Math.min(...temps) - 1;
      const hi = Math.max(...temps) + 1;
      const band = plotH * 0.55;
      const y = (t) => top + band - ((t - lo) / (hi - lo || 1)) * band;
      let path = `M${x(sp[0].m)},${y(sp[0].t)}`;
      for (let i = 1; i < sp.length; i += 1) path += ` H${x(sp[i].m)} V${y(sp[i].t)}`;
      path += ` H${x(span)}`;
      svgEl("path", { d: path, class: "u-target" }, svg);
      const last = sp[sp.length - 1];
      chips.push({ x: W - padR, y: y(last.t) - 0.9 * vmin, text: `${Number(last.t).toFixed(1).replace(/\.0$/, "")}°`, anchor: "end", cls: "u-target-text" });
    }

    // Value labels on a dark backing, after the lines, so a line never runs through them.
    for (const chip of chips) {
      const text = svgEl("text", { x: chip.x, y: chip.y, class: chip.cls, "text-anchor": chip.anchor, "font-size": font }, svg);
      text.textContent = chip.text;
      let box = null;
      try {
        box = text.getBBox();
      } catch {
        // Not laid out (hidden): no backing.
      }
      if (box && box.width) {
        const pad = 0.6 * vmin;
        const back = svgEl("rect", { x: box.x - pad, y: box.y - pad / 2, width: box.width + pad * 2, height: box.height + pad, rx: (box.height + pad) / 2, class: "u-chip" });
        svg.insertBefore(back, text);
      }
    }

    // Axis labels last, so nothing draws over them.
    const ay = H - axisH * 0.3;
    for (const l of labels) {
      if (x(l.m) > W - padR - font * 3.2 || x(l.m) < padL + font * 1.6) continue; // no clipped labels, room for "Now"
      const t = svgEl("text", { x: x(l.m), y: ay, class: "u-axis", "text-anchor": "middle", "font-size": font }, svg);
      t.textContent = l.text;
    }
    const nowLabel = svgEl("text", { x: W - padR, y: ay, class: "u-axis u-now", "text-anchor": "end", "font-size": font }, svg);
    nowLabel.textContent = "Now";
  }
}
