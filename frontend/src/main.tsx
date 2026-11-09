import "@fontsource/geist-mono/400.css";
import "./app.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// The service worker (public/sw.js) makes CodeSeat installable and keeps its
// shell for offline starts. Production only: in development it would hold on
// to files that live reload has just replaced.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Without it the site works the same; it is only not installable.
    });
  });
}
