"use client";

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { api, ApiError, eventsUrl } from "./api";
import { type CaseEvent, parseEvent, TERMINAL } from "./events";
import { type CaseView, fold } from "./reducer";
import { replayDelay } from "./timeline";

export type StreamState = "connecting" | "open" | "reconnecting" | "ended" | "failed";

/** A burst of events, as a replay sends, draws once and not once per event. */
const BATCH_MS = 40;

/** Every event of a case, live or finished. The server sends both the same way. */
export function useCaseEvents(id: string) {
  const [events, setEvents] = useState<CaseEvent[]>([]);
  const [state, setState] = useState<StreamState>("connecting");
  const [unreadable, setUnreadable] = useState(0);

  useEffect(() => {
    const source = new EventSource(eventsUrl(id));
    let pending: CaseEvent[] = [];
    let timer: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      timer = null;
      const batch = pending;
      pending = [];
      setEvents((current) => [...current, ...batch]);
    };
    source.onopen = () => setState("open");
    source.onmessage = (message: MessageEvent<string>) => {
      const event = parseEvent(message.data);
      if (!event) {
        setUnreadable((count) => count + 1);
        return;
      }
      pending.push(event);
      timer ??= setTimeout(flush, BATCH_MS);
      if (TERMINAL.has(event.type)) {
        source.close();
        setState("ended");
      }
    };
    source.onerror = () =>
      setState(source.readyState === EventSource.CLOSED ? "failed" : "reconnecting");
    return () => {
      source.close();
      if (timer !== null) clearTimeout(timer);
    };
  }, [id]);

  return { events, state, unreadable };
}

function subscribeToVisibility(notify: () => void) {
  document.addEventListener("visibilitychange", notify);
  return () => document.removeEventListener("visibilitychange", notify);
}

/** True while the tab cannot be seen. Replay stops, and so do the room's animations. */
export function useTabHidden(): boolean {
  const hidden = useSyncExternalStore(
    subscribeToVisibility,
    () => document.hidden,
    () => false,
  );
  useEffect(() => {
    document.documentElement.toggleAttribute("data-hidden", hidden);
  }, [hidden]);
  return hidden;
}

export interface Playback {
  /** How many events are shown. */
  position: number;
  playing: boolean;
  speed: number;
  /** Showing each event as it arrives, rather than a chosen point in the case. */
  following: boolean;
  setSpeed: (speed: number) => void;
  seek: (position: number) => void;
  toggle: () => void;
  follow: () => void;
}

/** Replay and live share this: the cursor is a count of events, and `null` means "the latest". */
export function usePlayback(
  events: CaseEvent[],
  ended: boolean,
  startFromTheTop: boolean,
): Playback {
  const [cursor, setCursor] = useState<number | null>(startFromTheTop ? 0 : null);
  const [playing, setPlaying] = useState(startFromTheTop);
  const [speed, setSpeed] = useState(1);
  const hidden = useTabHidden();
  const position = Math.min(cursor ?? events.length, events.length);

  useEffect(() => {
    if (!playing || hidden || cursor === null || cursor >= events.length) return;
    const delay = replayDelay(events[cursor - 1], events[cursor]) / speed;
    const timer = setTimeout(() => {
      const next = cursor + 1;
      if (next < events.length) {
        setCursor(next);
        return;
      }
      // Caught up: a live case carries on as it arrives, and a finished one stops here.
      setPlaying(false);
      setCursor(ended ? next : null);
    }, delay);
    return () => clearTimeout(timer);
  }, [playing, hidden, cursor, events, ended, speed]);

  const seek = useCallback((next: number) => {
    setPlaying(false);
    setCursor(next);
  }, []);

  const toggle = useCallback(() => {
    if (playing) {
      setPlaying(false);
      return;
    }
    // Pressing play at the end means "show me that again".
    setCursor((current) => {
      const from = current ?? events.length;
      return from >= events.length ? 0 : from;
    });
    setPlaying(true);
  }, [playing, events.length]);

  const follow = useCallback(() => {
    setPlaying(false);
    setCursor(null);
  }, []);

  return {
    position,
    playing,
    speed,
    following: cursor === null,
    setSpeed,
    seek,
    toggle,
    follow,
  };
}

/** The view at a position. A case has hundreds of events, so folding them again is cheap. */
export function useFoldedView(events: readonly CaseEvent[], position: number): CaseView {
  return useMemo(() => fold(events.slice(0, position)), [events, position]);
}

export interface Load<T> {
  data: T | null;
  error: ApiError | null;
  reload: () => void;
}

/** Read something from the local API. `load` must be stable: a change to it reads again. */
export function useLoad<T>(load: () => Promise<T>): Load<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let current = true;
    load()
      .then((value) => {
        if (current) {
          setData(value);
          setError(null);
        }
      })
      .catch((problem: unknown) => {
        if (current) {
          setError(problem instanceof ApiError ? problem : new ApiError(String(problem), 0));
        }
      });
    return () => {
      current = false;
    };
    // `nonce` is how `reload` asks again.
  }, [load, nonce]);
  const reload = useCallback(() => setNonce((value) => value + 1), []);
  return { data, error, reload };
}

export const useStatus = () => useLoad(api.status);
