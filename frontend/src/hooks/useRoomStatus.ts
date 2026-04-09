/**
 * hooks/useRoomStatus.ts
 *
 * Polls GET /api/realtime/rooms/{room_code}/status every 3 seconds.
 * Fires onPartnerJoined when the room phase transitions from "waiting" to "active".
 * Stops polling once the session becomes active or on component unmount.
 *
 * Usage:
 *   useRoomStatus({
 *     roomCode: "ABC123",
 *     onPartnerJoined: () => navigate("/session"),
 *   });
 */

import { useEffect, useRef } from "react";
import { realtimeApi } from "@/services/api";
import type { RoomStatusResponse } from "@/services/api";

const POLL_INTERVAL_MS = 3_000;

export interface UseRoomStatusOptions {
  /** Room code to poll. Pass null/undefined to skip polling. */
  roomCode: string | null | undefined;
  /** Fired once when the phase transitions from "waiting" → "active". */
  onPartnerJoined: () => void;
  /** Optional: called on every successful poll response. */
  onStatusUpdate?: (status: RoomStatusResponse) => void;
  /** Optional: called when the poll request fails. */
  onError?: (err: unknown) => void;
}

export function useRoomStatus({
  roomCode,
  onPartnerJoined,
  onStatusUpdate,
  onError,
}: UseRoomStatusOptions): void {
  // Guard against firing onPartnerJoined more than once.
  const firedRef = useRef(false);

  useEffect(() => {
    if (!roomCode) return;

    // Reset per-effect state in case the room code changes.
    firedRef.current = false;

    let active = true; // set to false when the effect cleans up

    const poll = async () => {
      try {
        const status = await realtimeApi.getRoomStatus(roomCode);
        if (!active) return;

        onStatusUpdate?.(status);

        // Fire once when the partner has joined (joining = JWT issued,
        // active = WebSocket connected). Both mean the partner arrived.
        if (!firedRef.current && (status.phase === "joining" || status.phase === "active")) {
          firedRef.current = true;
          onPartnerJoined();
        }

        // Stop polling once the session is active or has ended.
        if (status.phase === "active" || status.phase === "ended") {
          clearInterval(intervalId);
        }
      } catch (err) {
        if (active) onError?.(err);
      }
    };

    // Run immediately, then on each interval tick.
    poll();
    const intervalId = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      active = false;
      clearInterval(intervalId);
    };
  }, [roomCode, onPartnerJoined, onStatusUpdate, onError]);
}

export default useRoomStatus;
