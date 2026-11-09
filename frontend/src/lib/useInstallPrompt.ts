import { useCallback, useEffect, useState } from "react";

/** Chromium's event for an app the browser is willing to install. Not in the DOM typings. */
type InstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

/**
 * The browser's offer to install CodeSeat, held back so the page can show its
 * own button. `canInstall` stays false where browsers make no such offer (iOS,
 * or once the app is installed), and the button simply does not appear.
 */
export function useInstallPrompt() {
  const [offer, setOffer] = useState<InstallPromptEvent | null>(null);

  useEffect(() => {
    const onOffer = (event: Event) => {
      event.preventDefault();
      setOffer(event as InstallPromptEvent);
    };
    const onInstalled = () => setOffer(null);
    window.addEventListener("beforeinstallprompt", onOffer);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onOffer);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  const install = useCallback(async () => {
    if (!offer) return;
    setOffer(null); // an offer can be used once, whatever the answer
    await offer.prompt();
    await offer.userChoice;
  }, [offer]);

  return { canInstall: offer !== null, install };
}
