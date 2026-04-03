/**
 * store/realtimeStore.ts
 *
 * Zustand store for real-time interpretation session state.
 *
 * Replaces the 25+ useState calls that lived in the POC's monolith component.
 * Covers the full session lifecycle:
 *   idle → lobby → waiting → ready → active → ended
 *
 * Consumed by:
 *   - RealtimeSetup.tsx    (phase, roomCode, myName, myLanguage, courtInfo)
 *   - RealtimeSession.tsx  (messages, isMuted, micLocked, isSpeaking, …)
 *   - useRealtimeWebSocket (setPhase, addMessage, setLivePartial, …)
 *   - useAudioCapture      (isMuted, micLocked, setIsSpeaking)
 *   - useTtsPlayback       (isPlayingTts, setIsPlayingTts)
 */

import { create } from "zustand";

// ── Types ─────────────────────────────────────────────────────────────────────

export type SessionPhase =
  | "idle"
  | "lobby"
  | "waiting"
  | "ready"
  | "active"
  | "ended";

export interface ChatMessage {
  id: number;
  speaker: "self" | "partner";
  speakerName?: string;
  text: string;
  language: string;
  translation?: string;
  targetLanguage?: string;
  verifiedTranslation?: string;
  accuracyScore?: number;
  accuracyNote?: string;
  usedFallback?: boolean;
  duration?: number;
  timestamp: Date;
}

interface PartnerInfo {
  name: string;
  language: string;
}

interface LivePartial {
  speaker: "self" | "partner";
  text: string;
  translation?: string;
}

// ── Store types ───────────────────────────────────────────────────────────────

interface RealtimeState {
  // Session lifecycle
  phase: SessionPhase;
  roomCode: string;

  // Identity
  myName: string;
  myLanguage: string;
  isCreator: boolean;

  // Partner
  partner: PartnerInfo | null;
  partnerMuted: boolean;

  // Mic / audio state
  isMuted: boolean;
  micLocked: boolean;
  isRecording: boolean;
  isSpeaking: boolean;

  // Session meta
  duration: number;

  // Transcript
  messages: ChatMessage[];
  livePartial: LivePartial | null;

  // TTS playback
  isPlayingTts: boolean;

  // Error
  error: string | null;

  // Court metadata
  courtDivision: string;
  courtroom: string;
  caseDocket: string;
}

interface RealtimeActions {
  setPhase: (phase: SessionPhase) => void;
  setRoomCode: (code: string) => void;
  setMyName: (name: string) => void;
  setMyLanguage: (lang: string) => void;
  setIsCreator: (val: boolean) => void;
  setPartner: (info: PartnerInfo | null) => void;
  setPartnerMuted: (val: boolean) => void;
  toggleMute: () => void;
  setMicLocked: (val: boolean) => void;
  setIsRecording: (val: boolean) => void;
  setIsSpeaking: (val: boolean) => void;
  incrementDuration: () => void;
  addMessage: (msg: Omit<ChatMessage, "id">) => void;
  setLivePartial: (partial: LivePartial | null) => void;
  setIsPlayingTts: (val: boolean) => void;
  setError: (msg: string | null) => void;
  setCourtInfo: (division: string, courtroom: string, docket: string) => void;
  reset: () => void;
}

type RealtimeStore = RealtimeState & RealtimeActions;

// ── Default state ─────────────────────────────────────────────────────────────

const defaultState: RealtimeState = {
  phase: "idle",
  roomCode: "",
  myName: "",
  myLanguage: "en",
  isCreator: false,
  partner: null,
  partnerMuted: false,
  isMuted: false,
  micLocked: false,
  isRecording: false,
  isSpeaking: false,
  duration: 0,
  messages: [],
  livePartial: null,
  isPlayingTts: false,
  error: null,
  courtDivision: "",
  courtroom: "",
  caseDocket: "",
};

// ── Store ─────────────────────────────────────────────────────────────────────

const useRealtimeStore = create<RealtimeStore>((set, _get) => ({
  ...defaultState,

  // ── Session lifecycle ──────────────────────────────────────────────────────

  setPhase: (phase) => set({ phase }),

  setRoomCode: (code) => set({ roomCode: code }),

  // ── Identity ───────────────────────────────────────────────────────────────

  setMyName: (name) => set({ myName: name }),

  setMyLanguage: (lang) => set({ myLanguage: lang }),

  setIsCreator: (val) => set({ isCreator: val }),

  // ── Partner ────────────────────────────────────────────────────────────────

  setPartner: (info) => set({ partner: info }),

  setPartnerMuted: (val) => set({ partnerMuted: val }),

  // ── Mic / audio ────────────────────────────────────────────────────────────

  toggleMute: () => set((state) => ({ isMuted: !state.isMuted })),

  setMicLocked: (val) => set({ micLocked: val }),

  setIsRecording: (val) => set({ isRecording: val }),

  setIsSpeaking: (val) => set({ isSpeaking: val }),

  // ── Session timer ──────────────────────────────────────────────────────────

  incrementDuration: () => set((state) => ({ duration: state.duration + 1 })),

  // ── Transcript ─────────────────────────────────────────────────────────────

  addMessage: (msg) =>
    set((state) => {
      const id =
        state.messages.length > 0
          ? state.messages[state.messages.length - 1].id + 1
          : 1;
      return { messages: [...state.messages, { ...msg, id }] };
    }),

  setLivePartial: (partial) => set({ livePartial: partial }),

  // ── TTS playback ───────────────────────────────────────────────────────────

  setIsPlayingTts: (val) => set({ isPlayingTts: val }),

  // ── Error ──────────────────────────────────────────────────────────────────

  setError: (msg) => set({ error: msg }),

  // ── Court metadata ─────────────────────────────────────────────────────────

  setCourtInfo: (division, courtroom, docket) =>
    set({ courtDivision: division, courtroom, caseDocket: docket }),

  // ── Reset ──────────────────────────────────────────────────────────────────

  reset: () => set({ ...defaultState }),
}));

export default useRealtimeStore;
