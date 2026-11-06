import { useEffect, useRef } from "react";

/**
 * Sends `text` as it changes, at most once per interval, always ending with
 * the latest value. This is what makes an editor feel live without sending
 * a message for every keystroke.
 */
export function useThrottledSend(
  text: string,
  enabled: boolean,
  send: (text: string) => void,
  interval = 200,
): void {
  const lastSent = useRef(0);
  const sendRef = useRef(send);
  sendRef.current = send;

  useEffect(() => {
    if (!enabled) return;
    const wait = Math.max(0, interval - (performance.now() - lastSent.current));
    const timer = window.setTimeout(() => {
      lastSent.current = performance.now();
      sendRef.current(text);
    }, wait);
    return () => window.clearTimeout(timer);
  }, [text, enabled, interval]);
}
