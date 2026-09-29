import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";

export function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

export const PAGE_SIZE = 10;

/** List screens keep their filters in the URL, so reload and Back keep them.
 * Changing any filter goes back to page 1. */
export function useListParams<K extends string>(keys: readonly K[], defaults: Partial<Record<K, string>> = {}) {
  const [params, setParams] = useSearchParams();
  const defaultsRef = useRef(defaults);
  const keysRef = useRef(keys);

  const values = useMemo(() => {
    const out = {} as Record<K, string>;
    for (const k of keysRef.current) out[k] = params.get(k) ?? defaultsRef.current[k] ?? "";
    return out;
  }, [params]);

  const page = Math.max(1, Number(params.get("page")) || 1);

  const set = useCallback(
    (patch: Partial<Record<K | "page", string>>) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          const defaults = defaultsRef.current as Record<string, string | undefined>;
          for (const [k, v] of Object.entries(patch) as [string, string | undefined][]) {
            if (v === undefined || v === defaults[k] || (v === "" && !defaults[k])) next.delete(k);
            else next.set(k, v);
          }
          if (!("page" in patch)) next.delete("page");
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  return { values, page, set, offset: (page - 1) * PAGE_SIZE, limit: PAGE_SIZE };
}

/** A search box bound to a URL param, debounced. Typing never waits on the
 * URL; a change from outside (Back, a cleared filter) resets the box. */
export function useSearchParam(current: string, apply: (q: string) => void, ms = 350) {
  const [text, setText] = useState(current);
  const debounced = useDebounced(text, ms);
  const lastApplied = useRef(current);
  const applyRef = useRef(apply);
  applyRef.current = apply;

  useEffect(() => {
    if (debounced !== lastApplied.current) {
      lastApplied.current = debounced;
      applyRef.current(debounced);
    }
  }, [debounced]);

  useEffect(() => {
    if (current !== lastApplied.current) {
      lastApplied.current = current;
      setText(current);
    }
  }, [current]);

  return [text, setText] as const;
}

export function useNow(intervalMs: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}
