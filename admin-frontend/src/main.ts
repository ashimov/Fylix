import { createApp } from "vue";
import { createPinia } from "pinia";
import * as Sentry from "@sentry/vue";
import App from "./App.vue";
import { router } from "./router";
import "./styles/reset.css";
import "./styles/tokens.css";

const app = createApp(App);

const sentryDsn = import.meta.env.VITE_SENTRY_DSN;
if (sentryDsn) {
  Sentry.init({
    app,
    dsn: sentryDsn,
    environment: import.meta.env.MODE,
    release: "fylix-admin-frontend",
    integrations: [Sentry.browserTracingIntegration({ router })],
    tracesSampleRate: 0.1,
    sendDefaultPii: false,
    initialScope: { tags: { service: "admin" } },
    beforeSend(event) {
      if (event.request?.data && typeof event.request.data === "object") {
        const data = event.request.data as Record<string, unknown>;
        for (const k of ["passphrase", "password", "totp", "email"]) {
          if (k in data) data[k] = "[redacted]";
        }
      }
      return event;
    },
  });
}

app.use(createPinia());
app.use(router);
app.mount("#app");
