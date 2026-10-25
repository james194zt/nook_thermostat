export class DisplayPower {
  constructor({ client, config, onInteraction, onVisualSleep }) {
    this.client = client;
    this.config = config.display ?? {};
    this.onInteraction = onInteraction;
    this.onVisualSleep = onVisualSleep;
    this.idleMs = this.config.idleMs ?? 30000;
    this.timer = null;
    this.asleep = false;
    this.bindEvents();
    this.resetTimer();
  }

  bindEvents() {
    const reset = () => this.resetTimer();
    for (const eventName of ["pointerdown", "touchstart", "keydown", "click"]) {
      document.addEventListener(eventName, reset, { passive: true });
    }
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        this.resetTimer();
      }
    });
    this.bindFullyMotion();
  }

  // Fully Kiosk Browser's motion detection (camera, or the proximity sensor with
  // "Enable Proximity Motion Detection") reaches the page via its JS interface.
  // fully.bind() takes code to eval, so it calls a global that points at the
  // current instance; bind only once per page load.
  bindFullyMotion() {
    window.__nookWake = () => this.resetTimer();
    if (window.__nookFullyBound || typeof window.fully?.bind !== "function") return;
    try {
      window.fully.bind("onMotion", "window.__nookWake && window.__nookWake();");
      window.fully.bind(
        "screenOn",
        "window.__nookWake && window.__nookWake(); window.__nookScreenOn && window.__nookScreenOn();",
      );
      window.__nookFullyBound = true;
    } catch {
      // Not Fully, or JS interface disabled.
    }
  }

  resetTimer() {
    this.onInteraction?.();
    clearTimeout(this.timer);

    if (this.asleep) {
      this.asleep = false;
    }

    this.timer = setTimeout(() => this.sleep(), this.idleMs);
  }

  async sleep() {
    this.asleep = true;
    const panelEntity = this.config.panelEntity;

    if (panelEntity && this.client) {
      try {
        const state = this.client.getState(panelEntity);
        if (state?.entity_id?.startsWith("select.")) {
          await this.client.callService("select", "select_option", {
            entity_id: panelEntity,
            option: "sleep",
          });
          return;
        }

        if (state?.entity_id?.startsWith("button.")) {
          await this.client.callService("button", "press", {
            entity_id: panelEntity,
          });
          return;
        }
      } catch {
        // Fall back to the on-screen overlay if the panel command fails.
      }
    }

    this.onVisualSleep?.();
  }

  destroy() {
    clearTimeout(this.timer);
    window.__nookWake = null;
  }
}
