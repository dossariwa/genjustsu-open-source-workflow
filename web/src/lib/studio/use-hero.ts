"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { HERO_DEFAULT_ALT, HERO_DEFAULT_SRC } from "./constants";

/*
 * Artwork is browser-local decoration: it never joins job FormData or uploads.
 * IndexedDB keeps animated GIFs intact without base64/localStorage limits.
 * Same database/store/key as static/app.js, so a saved banner carries over.
 */
const DB = "genjustsu-studio";
const STORE = "appearance";
const KEY = "hero";
const TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];
const MAX_BYTES = 12 * 1024 * 1024;

function heroStore<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result;
      const transaction = db.transaction(STORE, mode);
      const operation = action(transaction.objectStore(STORE));
      transaction.oncomplete = () => {
        db.close();
        resolve(operation.result);
      };
      transaction.onerror = transaction.onabort = () => {
        db.close();
        reject(transaction.error);
      };
    };
  });
}

export const HERO_STATUS_DEFAULT = "Your reference stays in this browser. Never sent with a generation. PNG, JPEG, WebP or GIF.";

export function useHeroBanner() {
  const [src, setSrc] = useState(HERO_DEFAULT_SRC);
  const [custom, setCustom] = useState(false);
  const [failed, setFailed] = useState(false);
  const [statusText, setStatusText] = useState(HERO_STATUS_DEFAULT);
  const version = useRef(0);
  const objectUrl = useRef<string | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  const display = useCallback((blob: Blob | null) => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = blob ? URL.createObjectURL(blob) : null;
    setFailed(false);
    setCustom(!!blob);
    setSrc(objectUrl.current || HERO_DEFAULT_SRC);
  }, []);

  // Keep a rapid upload/reset/upload sequence in the same order on disk.
  const persist = useCallback(<T,>(action: (store: IDBObjectStore) => IDBRequest<T>) => {
    queue.current = queue.current.catch(() => {}).then(() => heroStore("readwrite", action));
    return queue.current;
  }, []);

  useEffect(() => {
    const initial = version.current;
    heroStore("readonly", (store) => store.get(KEY))
      .then((blob) => {
        if (blob instanceof Blob && initial === version.current) {
          display(blob);
          setStatusText("Your saved reference · stored in this browser only.");
        }
      })
      .catch(() => {});
    return () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    };
  }, [display]);

  const upload = useCallback(
    async (file: File) => {
      const current = ++version.current;
      if (!TYPES.includes(file.type) || file.size > MAX_BYTES) {
        setStatusText("Choose a PNG, JPEG, WebP or GIF up to 12 MB. Your current banner is unchanged.");
        return;
      }
      const probeUrl = URL.createObjectURL(file);
      try {
        await new Promise((resolve, reject) => {
          const probe = new Image();
          probe.onload = resolve;
          probe.onerror = reject;
          probe.src = probeUrl;
        });
        if (current !== version.current) return;
        display(file);
        try {
          await persist((store) => store.put(file, KEY));
          if (current === version.current) setStatusText(`${file.name} · saved in this browser only. Never sent with a generation.`);
        } catch {
          if (current === version.current) setStatusText(`${file.name} · preview only; browser storage is unavailable.`);
        }
      } catch {
        if (current === version.current) setStatusText("This file could not be displayed. Your current banner is unchanged.");
      } finally {
        URL.revokeObjectURL(probeUrl);
      }
    },
    [display, persist],
  );

  const reset = useCallback(async () => {
    const current = ++version.current;
    display(null);
    try {
      await persist((store) => store.delete(KEY));
      if (current === version.current) setStatusText("Default reference restored. Your banner stays separate from generation references.");
    } catch {
      if (current === version.current) setStatusText("Default shown for this session; saved banner could not be cleared.");
    }
  }, [display, persist]);

  const onError = useCallback(() => {
    setFailed(true);
    setStatusText("Default artwork unavailable. Choose a local image or GIF to customize this space.");
  }, []);

  return {
    src,
    alt: custom ? "Your custom studio visual reference" : HERO_DEFAULT_ALT,
    origin: custom ? "YOUR REFERENCE" : "LOCAL ASSET",
    custom,
    failed,
    statusText,
    upload,
    reset,
    onError,
  };
}

export type HeroBanner = ReturnType<typeof useHeroBanner>;
