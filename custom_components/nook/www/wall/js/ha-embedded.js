/**
 * Runs the wall app inside Home Assistant (e.g. the Nook panel's preview iframe),
 * borrowing the parent page's logged-in `hass` instead of a token.
 *
 * `hass.connection` is home-assistant-js-websocket's Connection: it has
 * subscribeEvents / sendMessagePromise, but no subscribeEntities (that is a
 * separate library function). HA also swaps in a new `hass` object on every
 * update, so always read the parent's current one.
 */
export class EmbeddedHomeAssistantClient {
  constructor({ onStateChange, onConnectionChange }) {
    this.onStateChange = onStateChange;
    this.onConnectionChange = onConnectionChange;
    this.hass = null;
    this.unsubscribe = null;
    this.connected = false;
  }

  async connect() {
    this.hass = await this.waitForParentHass();
    if (!this.hass) {
      throw new Error("Could not connect to Home Assistant dashboard session");
    }

    const unsub = await this.hass.connection.subscribeEvents((event) => {
      const { entity_id: entityId, new_state: state } = event?.data || {};
      if (entityId && state) this.onStateChange?.(entityId, state);
    }, "state_changed");
    this.unsubscribe = unsub;

    this.setConnected(true);
    for (const [entityId, state] of Object.entries(this.currentHass().states)) {
      this.onStateChange?.(entityId, state);
    }
  }

  parentHass() {
    try {
      const hass = window.parent?.document?.querySelector("home-assistant")?.hass;
      return hass?.states ? hass : null;
    } catch {
      // Cross-origin parent: not embedded in HA after all.
      return null;
    }
  }

  currentHass() {
    return this.parentHass() || this.hass;
  }

  async waitForParentHass(timeoutMs = 15000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const hass = this.parentHass();
      if (hass) return hass;
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    return null;
  }

  setConnected(value) {
    if (this.connected === value) return;
    this.connected = value;
    this.onConnectionChange?.(value);
  }

  getState(entityId) {
    return this.currentHass()?.states?.[entityId] ?? null;
  }

  listEntityIds() {
    return Object.keys(this.currentHass()?.states ?? {});
  }

  async getUserData(key) {
    const result = await this.currentHass().connection.sendMessagePromise({
      type: "frontend/get_user_data",
      key,
    });
    return result?.value ?? null;
  }

  async setUserData(key, value) {
    await this.currentHass().connection.sendMessagePromise({
      type: "frontend/set_user_data",
      key,
      value,
    });
  }

  async callService(domain, service, serviceData = {}) {
    // Plain call_service: asking for a response (return_response) makes HA
    // reject services such as climate.set_temperature that return none.
    await this.currentHass().connection.sendMessagePromise({
      type: "call_service",
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

  async request(type, payload = {}) {
    return this.currentHass().connection.sendMessagePromise({ type, ...payload });
  }

  disconnect() {
    const unsub = this.unsubscribe;
    this.unsubscribe = null;
    try {
      unsub?.();
    } catch {
      // Connection already gone.
    }
    this.hass = null;
    this.setConnected(false);
  }
}
