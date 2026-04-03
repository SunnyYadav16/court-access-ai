/**
 * hooks/useTtsPlayback.ts
 *
 * TTS audio playback queue hook.
 *
 * Decodes WAV ArrayBuffers received over the WebSocket binary channel and
 * plays them sequentially through the Web Audio API.  Tracks playback state
 * in realtimeStore so the UI can show a "speaking" indicator.
 *
 * Usage:
 *   const { enqueue, clearQueue } = useTtsPlayback();
 *
 *   // Inside WebSocket onmessage:
 *   if (frame is TTS audio) enqueue(event.data as ArrayBuffer);
 */

import { useCallback, useEffect, useRef } from "react";
import useRealtimeStore from "@/store/realtimeStore";

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useTtsPlayback() {
  const setIsPlayingTts = useRealtimeStore((s) => s.setIsPlayingTts);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const queueRef = useRef<ArrayBuffer[]>([]);
  const playingRef = useRef(false);

  // ── Core playback loop ───────────────────────────────────────────────────

  const playNext = useCallback(async () => {
    if (playingRef.current) return;

    const buf = queueRef.current.shift();
    if (!buf) {
      setIsPlayingTts(false);
      return;
    }

    playingRef.current = true;
    setIsPlayingTts(true);

    try {
      // Lazy-create AudioContext on first use (satisfies browser autoplay policy)
      if (!audioCtxRef.current) {
        audioCtxRef.current = new AudioContext();
      }
      const ctx = audioCtxRef.current;

      // Resume if suspended — required after a user-gesture gate
      if (ctx.state === "suspended") {
        await ctx.resume();
      }

      // slice(0) passes a copy — decodeAudioData detaches the original buffer
      const decoded = await ctx.decodeAudioData(buf.slice(0));

      const source = ctx.createBufferSource();
      source.buffer = decoded;
      source.connect(ctx.destination);
      source.onended = () => {
        playingRef.current = false;
        playNext();
      };
      source.start();
    } catch (err) {
      console.error("[useTtsPlayback] Playback error:", err);
      playingRef.current = false;
      setIsPlayingTts(false);
      // Skip the failed buffer and try the next one
      playNext();
    }
  }, [setIsPlayingTts]);

  // ── Public API ────────────────────────────────────────────────────────────

  /** Enqueue a raw WAV ArrayBuffer for sequential playback. */
  const enqueue = useCallback(
    (buffer: ArrayBuffer) => {
      queueRef.current.push(buffer);
      playNext();
    },
    [playNext]
  );

  /** Drain the queue and stop playback immediately. */
  const clearQueue = useCallback(() => {
    queueRef.current = [];
    playingRef.current = false;
    setIsPlayingTts(false);
  }, [setIsPlayingTts]);

  // ── Cleanup on unmount ────────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      clearQueue();
      audioCtxRef.current?.close();
      audioCtxRef.current = null;
    };
    // clearQueue is stable (only depends on setIsPlayingTts from Zustand)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { enqueue, clearQueue };
}
