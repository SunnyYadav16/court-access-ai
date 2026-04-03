/**
 * hooks/useAudioCapture.ts
 *
 * MediaRecorder-based microphone capture hook with energy-based speaking detection.
 *
 * Manages the full mic lifecycle:
 *   startCapture() → getUserMedia → MediaRecorder → sendAudio callback
 *   stopCapture()  → stop recorder, release tracks, cancel timers
 *
 * The MediaRecorder is restarted every 30 s so the server receives a fresh
 * WebM header periodically.  Without this, the server's AudioStreamDecoder
 * accumulates chunks that require re-decoding from the start — O(N²) cost.
 *
 * Energy-based speaking detection uses an AnalyserNode to compute average
 * frequency energy per animation frame.  Three consecutive frames above the
 * threshold sets isSpeaking; the counter decays on silence.
 *
 * Usage:
 *   const { startCapture, stopCapture } = useAudioCapture();
 *
 *   // Wire to the WebSocket hook:
 *   useRealtimeWebSocket({
 *     enqueueTts: enqueue,
 *     onStartCapture: () => startCapture(sendAudio),
 *     onStopCapture: stopCapture,
 *   });
 */

import { useCallback, useEffect, useRef } from "react";
import useRealtimeStore from "@/store/realtimeStore";

// ── Constants ─────────────────────────────────────────────────────────────────

const RECORDER_TIMESLICE_MS = 250;
const RESTART_INTERVAL_MS = 30_000;
const ENERGY_THRESHOLD = 30;
const SPEECH_FRAMES_REQUIRED = 3;

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useAudioCapture() {
  const setIsRecording = useRealtimeStore((s) => s.setIsRecording);
  const setIsSpeaking = useRealtimeStore((s) => s.setIsSpeaking);
  const incrementDuration = useRealtimeStore((s) => s.incrementDuration);
  const setMicLocked = useRealtimeStore((s) => s.setMicLocked);
  const setError = useRealtimeStore((s) => s.setError);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const recorderRestartRef = useRef<number | null>(null);
  const durationTimerRef = useRef<number | null>(null);

  // ── Audio analysis ────────────────────────────────────────────────────────

  const stopAudioAnalysis = useCallback(() => {
    if (animationFrameRef.current !== null) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    analyserRef.current = null;
    audioCtxRef.current?.close();
    audioCtxRef.current = null;
    setIsSpeaking(false);
  }, [setIsSpeaking]);

  const startAudioAnalysis = useCallback(
    (stream: MediaStream) => {
      // Close previous AudioContext if any (prevents leak on re-start)
      audioCtxRef.current?.close();
      const audioCtx = new AudioContext();
      audioCtxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      source.connect(analyser);
      analyserRef.current = analyser;

      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      let speechFrames = 0;

      const analyze = () => {
        if (!analyserRef.current) return;
        analyserRef.current.getByteFrequencyData(dataArray);
        const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;

        if (avg > ENERGY_THRESHOLD) {
          speechFrames++;
          if (speechFrames >= SPEECH_FRAMES_REQUIRED) setIsSpeaking(true);
        } else {
          speechFrames = Math.max(0, speechFrames - 1);
          if (speechFrames === 0) setIsSpeaking(false);
        }

        animationFrameRef.current = requestAnimationFrame(analyze);
      };

      analyze();
    },
    [setIsSpeaking]
  );

  // ── Public API ────────────────────────────────────────────────────────────

  const stopCapture = useCallback(() => {
    stopAudioAnalysis();

    if (durationTimerRef.current !== null) {
      clearInterval(durationTimerRef.current);
      durationTimerRef.current = null;
    }

    if (recorderRestartRef.current !== null) {
      clearInterval(recorderRestartRef.current);
      recorderRestartRef.current = null;
    }

    if (mediaRecorderRef.current?.state !== "inactive") {
      mediaRecorderRef.current?.stop();
    }
    mediaRecorderRef.current = null;

    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;

    setIsRecording(false);
    setIsSpeaking(false);
    setMicLocked(false);
  }, [stopAudioAnalysis, setIsRecording, setIsSpeaking, setMicLocked]);

  const startCapture = useCallback(
    async (sendAudio: (data: Blob) => void) => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            sampleRate: 48000,
          },
        });
        streamRef.current = stream;

        startAudioAnalysis(stream);

        const recorder = new MediaRecorder(stream, {
          mimeType: "audio/webm;codecs=opus",
          audioBitsPerSecond: 128_000,
        });
        mediaRecorderRef.current = recorder;

        recorder.ondataavailable = (e) => {
          // Read isMuted directly from store — avoids stale closure, no ref mirror needed
          if (e.data.size > 0 && !useRealtimeStore.getState().isMuted) {
            sendAudio(e.data);
          }
        };

        recorder.start(RECORDER_TIMESLICE_MS);
        setIsRecording(true);

        // Duration counter — increments every second while recording
        durationTimerRef.current = window.setInterval(() => {
          incrementDuration();
        }, 1000);

        // Restart MediaRecorder every 30 s to emit a fresh WebM header.
        // Without this the server's AudioStreamDecoder must re-decode the
        // entire accumulated buffer on every new chunk — O(N²) cost.
        // We create a new MediaRecorder to avoid Firefox/Safari
        // InvalidStateError from stop→start on the same instance.
        recorderRestartRef.current = window.setInterval(() => {
          const rec = mediaRecorderRef.current;
          const currentStream = streamRef.current;
          if (rec && rec.state === "recording" && currentStream) {
            rec.stop();
            const newRec = new MediaRecorder(currentStream, {
              mimeType: "audio/webm;codecs=opus",
              audioBitsPerSecond: 128_000,
            });
            newRec.ondataavailable = rec.ondataavailable;
            newRec.start(RECORDER_TIMESLICE_MS);
            mediaRecorderRef.current = newRec;
          }
        }, RESTART_INTERVAL_MS);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Microphone access denied"
        );
      }
    },
    [startAudioAnalysis, setIsRecording, incrementDuration, setError]
  );

  // ── Cleanup on unmount ────────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      stopCapture();
    };
    // stopCapture is stable — deps are all Zustand actions
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { startCapture, stopCapture };
}

export default useAudioCapture;
