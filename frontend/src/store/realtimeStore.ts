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
import { persist, createJSONStorage } from "zustand/middleware";
import type { RoomCreateResponse } from "@/services/api";

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
  isGuest: boolean;

  // Guest auth
  roomToken: string | null;

  // Partner
  partner: PartnerInfo | null;
  partnerName: string;
  partnerMuted: boolean;

  // Mic / audio state
  isMuted: boolean;
  micLocked: boolean;
  isRecording: boolean;
  isSpeaking: boolean;

  // Lobby (after room creation, before WS connect)
  sessionId: string | null;
  joinUrl: string;
  roomCodeExpiresAt: string | null;

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
  setLobbyInfo: (sessionId: string, roomCode: string, joinUrl: string, roomCodeExpiresAt: string, partnerName: string, partnerLanguage: string) => void;
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
  setRoomCreated: (response: RoomCreateResponse) => void;
  setPartnerJoined: () => void;
  setRoomToken: (token: string) => void;
  endSession: () => void;
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
  isGuest: false,
  roomToken: null,
  partner: null,
  partnerName: "",
  partnerMuted: false,
  isMuted: false,
  micLocked: false,
  isRecording: false,
  isSpeaking: false,
  sessionId: null,
  joinUrl: "",
  roomCodeExpiresAt: null,
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

const useRealtimeStore = create<RealtimeStore>()(
  persist(
    (set, _get) => ({
      ...defaultState,

  // ── Session lifecycle ──────────────────────────────────────────────────────

  setPhase: (phase) => set({ phase }),

  setRoomCode: (code) => set({ roomCode: code }),

  // ── Identity ───────────────────────────────────────────────────────────────

  setMyName: (name) => set({ myName: name }),

  setMyLanguage: (lang) => set({ myLanguage: lang }),

  setIsCreator: (val) => set({ isCreator: val }),

  setLobbyInfo: (sessionId, roomCode, joinUrl, roomCodeExpiresAt, partnerName, partnerLanguage) =>
    set({
      sessionId,
      roomCode,
      joinUrl,
      roomCodeExpiresAt,
      phase: "lobby",
      isCreator: true,
      partner: { name: partnerName, language: partnerLanguage },
    }),

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

  // ── New room lifecycle ─────────────────────────────────────────────────────

  setRoomCreated: (response) =>
    set({
      sessionId: response.session_id,
      roomCode: response.room_code,
      joinUrl: response.join_url,
      roomCodeExpiresAt: response.room_code_expires_at,
      phase: "lobby",
      isCreator: true,
    }),

  setPartnerJoined: () => set({ phase: "active" }),

  setRoomToken: (token) => set({ roomToken: token }),

  endSession: () => set({ phase: "ended" }),

  // ── Reset ──────────────────────────────────────────────────────────────────

  reset: () => set({ ...defaultState }),
    }),
    {
      name: "realtime-storage",
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        phase: state.phase,
        sessionId: state.sessionId,
        roomCode: state.roomCode,
        joinUrl: state.joinUrl,
        roomCodeExpiresAt: state.roomCodeExpiresAt,
        myName: state.myName,
        myLanguage: state.myLanguage,
        isCreator: state.isCreator,
        partner: state.partner,
        courtDivision: state.courtDivision,
        courtroom: state.courtroom,
        caseDocket: state.caseDocket,
        messages: state.messages,
      }),
      onRehydrateStorage: () => (state) => {
        // JSON serialises Date → ISO string; convert back so
        // timestamp.toLocaleTimeString() doesn't crash after a page refresh.
        if (state?.messages) {
          state.messages = state.messages.map((m) => ({
            ...m,
            timestamp: new Date(m.timestamp as unknown as string),
          }));
        }
      },
    }
  )
);

export default useRealtimeStore;
