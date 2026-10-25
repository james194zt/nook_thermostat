import { HomeAssistantClient } from "./ha-client.js";
import {
  DEFAULT_HA_URL,
  loadLocalSecrets,
  saveLocalSecrets,
} from "./config.js";
import { getStoredDeviceId, setStoredDeviceId, slugifyDeviceId } from "./device-registry.js";

const panelList = document.getElementById("panelList");
const setupStatus = document.getElementById("setupStatus");
const connectionStatus = document.getElementById("connectionStatus");
const currentPanelHint = document.getElementById("currentPanelHint");
const haUrlInput = document.getElementById("haUrl");
const accessTokenInput = document.getElementById("accessToken");

let haClient = null;
let panels = [];

function showStatus(message, isError = false) {
  setupStatus.textContent = message;
  setupStatus.classList.remove("hidden");
  setupStatus.style.background = isError
    ? "rgba(255, 92, 92, 0.16)"
    : "rgba(37, 177, 246, 0.15)";
  setupStatus.style.color = isError ? "#ffb4b4" : "#9edcff";
}

function setConnectionState(text, kind = "") {
  connectionStatus.textContent = text;
  connectionStatus.classList.remove("ok", "err");
  if (kind) connectionStatus.classList.add(kind);
}

function updateCurrentHint() {
  const id = getStoredDeviceId();
  currentPanelHint.textContent = id
    ? `This screen is assigned to: ${id}`
    : "This screen is not assigned yet.";
}

function renderPanels() {
  panelList.innerHTML = "";
  const selected = getStoredDeviceId();

  if (!panels.length) {
    const li = document.createElement("li");
    li.className = "panel-pick-empty";
    li.textContent =
      "No wall panels found. Add them in Home Assistant → Nook → Wall panels.";
    panelList.appendChild(li);
    return;
  }

  for (const panel of panels) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `panel-pick-btn${panel.id === selected ? " selected" : ""}`;
    btn.innerHTML = `
      <span class="panel-pick-label">${panel.label || panel.id}</span>
      <span class="panel-pick-id">${panel.id}</span>
    `;
    btn.addEventListener("click", () => selectPanel(panel.id));
    li.appendChild(btn);
    panelList.appendChild(li);
  }
}

function selectPanel(panelId) {
  const id = slugifyDeviceId(panelId);
  if (!id) return;
  setStoredDeviceId(id);
  updateCurrentHint();
  renderPanels();
  showStatus(`Assigned to “${id}”. Opening thermostat…`);
  setTimeout(() => {
    window.location.href = "index.html";
  }, 600);
}

async function waitConnected(client, timeoutMs = 8000) {
  if (client.connected) return;
  await new Promise((resolve, reject) => {
    const started = Date.now();
    const prev = client.onConnectionChange;
    client.onConnectionChange = (connected) => {
      prev?.(connected);
      if (connected) {
        client.onConnectionChange = prev;
        resolve();
      } else if (Date.now() - started > timeoutMs) {
        client.onConnectionChange = prev;
        reject(new Error("Connection timed out"));
      }
    };
    const tick = setInterval(() => {
      if (client.connected) {
        clearInterval(tick);
        client.onConnectionChange = prev;
        resolve();
      } else if (Date.now() - started > timeoutMs) {
        clearInterval(tick);
        client.onConnectionChange = prev;
        reject(new Error("Connection timed out"));
      }
    }, 200);
  });
}

async function connectAndLoad() {
  const haUrl = haUrlInput.value.trim() || DEFAULT_HA_URL;
  const accessToken = accessTokenInput.value.trim();
  if (!accessToken) {
    showStatus("Access token required", true);
    setConnectionState("Missing token", "err");
    return;
  }

  saveLocalSecrets({ haUrl, accessToken });
  haClient?.disconnect();
  haClient = new HomeAssistantClient({
    url: haUrl,
    token: accessToken,
    onConnectionChange: (ok) => {
      setConnectionState(ok ? "Connected" : "Disconnected", ok ? "ok" : "err");
    },
  });
  haClient.connect();

  try {
    await waitConnected(haClient);
    const result = await haClient.request("nook/list_wall_panels");
    panels = result?.wall_panels || [];
    renderPanels();
    showStatus(
      panels.length
        ? `Loaded ${panels.length} wall panel${panels.length === 1 ? "" : "s"} from Nook.`
        : "Connected, but no wall panels are defined yet in Nook."
    );
  } catch (err) {
    panels = [];
    renderPanels();
    showStatus(
      `Could not load wall panels: ${err.message || err}. Is Nook installed and set up?`,
      true
    );
    setConnectionState("Error", "err");
  }
}

function init() {
  const secrets = loadLocalSecrets();
  haUrlInput.value = secrets.haUrl || DEFAULT_HA_URL;
  accessTokenInput.value = secrets.accessToken || "";
  updateCurrentHint();
  renderPanels();
  document.getElementById("connectHa").addEventListener("click", connectAndLoad);

  if (secrets.accessToken) {
    connectAndLoad();
  }
}

init();
