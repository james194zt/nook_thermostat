import { App } from "@capacitor/app";

const HA_URL = "http://192.168.1.10:8123/local/nspanel-thermostat/index.html";

async function bootstrapNativeShell() {
  if (!window.Capacitor?.isNativePlatform?.()) {
    return;
  }

  if (!window.location.pathname.includes("/local/nspanel-thermostat/")) {
    window.location.replace(HA_URL);
  }

  App.addListener("appStateChange", () => {});
}

bootstrapNativeShell();
