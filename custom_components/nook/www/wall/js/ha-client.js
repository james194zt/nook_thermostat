export class HomeAssistantClient {
  constructor({ url, token, onStateChange, onConnectionChange }) {
    this.url = url.replace(/\/$/, "");
    this.token = token;
    this.onStateChange = onStateChange;
    this.onConnectionChange = onConnectionChange;
    this.ws = null;
    this.messageId = 1;
    this.pending = new Map();
    this.states = new Map();
    this.connected = false;
    this.reconnectTimer = null;
    // While the page is visible, check now and then that the socket is really alive:
    // after the panel sleeps, HA has often dropped it while it still looks open here.
    this.heartbeat = setInterval(() => {
      if (!document.hidden) this.checkAlive();
    }, 30000);
  }

  connect() {
    const wsUrl = this.url.replace(/^http/, "ws") + "/api/websocket";
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {};

    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      this.handleMessage(message);
    };

    this.ws.onclose = () => {
      this.setConnected(false);
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  scheduleReconnect() {
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => this.connect(), 3000);
  }

  /**
   * Make sure the connection is live — call on wake (screen on, page visible again).
   * A ping HA must answer within a moment; no answer, or no socket, means reconnect
   * right away rather than showing stale numbers until the network notices.
   */
  checkAlive(timeoutMs = 1500) {
    if (this.ws?.readyState === WebSocket.CONNECTING) return; // already on its way
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN || !this.connected) {
      this.reconnectNow();
      return;
    }
    if (this.pingPending) return;
    const id = this.messageId++;
    this.pingPending = true;
    const timer = setTimeout(() => {
      this.pending.delete(id);
      this.pingPending = false;
      this.reconnectNow();
    }, timeoutMs);
    this.pending.set(id, {
      resolve: () => {
        clearTimeout(timer);
        this.pingPending = false;
      },
      reject: () => {
        clearTimeout(timer);
        this.pingPending = false;
      },
    });
    this.sendRaw({ id, type: "ping" });
  }

  /** Drop the old socket (without its 3 s retry) and connect again now. */
  reconnectNow() {
    clearTimeout(this.reconnectTimer);
    const old = this.ws;
    this.ws = null;
    if (old) {
      old.onclose = null;
      old.onerror = null;
      old.onmessage = null;
      try {
        old.close();
      } catch {
        // Already closed.
      }
    }
    // Requests sent on the dead socket will never be answered.
    for (const { reject } of this.pending.values()) reject(new Error("Reconnecting to Home Assistant"));
    this.pending.clear();
    this.pingPending = false;
    this.setConnected(false);
    this.connect();
  }

  setConnected(value) {
    if (this.connected === value) return;
    this.connected = value;
    this.onConnectionChange?.(value);
  }

  handleMessage(message) {
    if (message.type === "auth_required") {
      this.sendRaw({ type: "auth", access_token: this.token });
      return;
    }

    if (message.type === "auth_ok") {
      this.setConnected(true);
      this.subscribeEvents();
      this.fetchStates();
      return;
    }

    if (message.type === "auth_invalid") {
      this.setConnected(false);
      throw new Error("Invalid Home Assistant access token");
    }

    if (message.type === "pong" && this.pending.has(message.id)) {
      const { resolve } = this.pending.get(message.id);
      this.pending.delete(message.id);
      resolve();
      return;
    }

    if (message.type === "result" && message.id && this.pending.has(message.id)) {
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.success) resolve(message.result);
      else reject(new Error(message.error?.message || "Home Assistant request failed"));
      return;
    }

    if (message.type === "event" && message.event?.event_type === "state_changed") {
      const { entity_id: entityId, new_state: newState } = message.event.data;
      if (!newState) {
        this.states.delete(entityId);
      } else {
        this.states.set(entityId, newState);
      }
      this.onStateChange?.(entityId, this.states.get(entityId));
    }
  }

  sendRaw(payload) {
    this.ws?.send(JSON.stringify(payload));
  }

  request(type, payload = {}) {
    const id = this.messageId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.sendRaw({ id, type, ...payload });
    });
  }

  async subscribeEvents() {
    await this.request("subscribe_events", { event_type: "state_changed" });
  }

  async fetchStates() {
    const states = await this.request("get_states");
    for (const state of states) {
      this.states.set(state.entity_id, state);
      this.onStateChange?.(state.entity_id, state);
    }
  }

  getState(entityId) {
    return this.states.get(entityId);
  }

  listEntityIds() {
    return [...this.states.keys()];
  }

  async getUserData(key) {
    const result = await this.request("frontend/get_user_data", { key });
    return result?.value ?? null;
  }

  async setUserData(key, value) {
    await this.request("frontend/set_user_data", { key, value });
  }

  async callService(domain, service, serviceData = {}) {
    return this.request("call_service", {
      domain,
      service,
      service_data: serviceData,
    });
  }

  async setTemperature(entityId, temperature) {
    return this.callService("climate", "set_temperature", {
      entity_id: entityId,
      temperature,
    });
  }

  async setHvacMode(entityId, hvacMode) {
    return this.callService("climate", "set_hvac_mode", {
      entity_id: entityId,
      hvac_mode: hvacMode,
    });
  }

  async setPresetMode(entityId, presetMode) {
    return this.callService("climate", "set_preset_mode", {
      entity_id: entityId,
      preset_mode: presetMode,
    });
  }

  disconnect() {
    clearTimeout(this.reconnectTimer);
    clearInterval(this.heartbeat);
    this.ws?.close();
    this.ws = null;
    this.setConnected(false);
  }
}
