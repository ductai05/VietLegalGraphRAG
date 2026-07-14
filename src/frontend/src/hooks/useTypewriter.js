import { useEffect, useRef, useState } from "react";

// Ports the ".type-text" typewriter effect from app.js: reveals `text`
// character by character after an initial delay.
export function useTypewriter(text, { speed = 32, startDelay = 400 } = {}) {
  const [shown, setShown] = useState("");
  const timers = useRef([]);

  useEffect(() => {
    setShown("");
    timers.current.forEach((id) => window.clearTimeout(id));
    timers.current = [];

    let i = 0;
    const tick = () => {
      i += 1;
      setShown(text.slice(0, i));
      if (i < text.length) {
        timers.current.push(window.setTimeout(tick, speed));
      }
    };
    timers.current.push(window.setTimeout(tick, startDelay));

    return () => {
      timers.current.forEach((id) => window.clearTimeout(id));
      timers.current = [];
    };
  }, [text, speed, startDelay]);

  return shown;
}
