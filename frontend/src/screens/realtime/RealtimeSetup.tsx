import { useEffect, useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import useRealtimeStore from "@/store/realtimeStore"
import { useRealtimeWebSocket } from "@/hooks/useRealtimeWebSocket"

// ── Constants ─────────────────────────────────────────────────────────────────

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "es", label: "Spanish (Español)" },
  { value: "pt", label: "Portuguese (Português)" },
] as const

type LangCode = "en" | "es" | "pt"

const COURT_DIVISIONS = [
  "Boston Municipal Court",
  "Worcester District Court",
  "Suffolk Superior Court",
  "Springfield District Court",
]

const COURTROOMS = [
  "Courtroom 3",
  "Courtroom 5A",
  "Courtroom 7",
  "Courtroom 12",
  "Courtroom 14B",
]

// ── Shared field wrapper ──────────────────────────────────────────────────────

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label
        className="text-xs font-semibold block mb-1.5"
        style={{ color: "#4A5568" }}
      >
        {label}
      </label>
      {children}
    </div>
  )
}

function StyledSelect({
  value,
  onChange,
  children,
}: {
  value: string
  onChange: (v: string) => void
  children: React.ReactNode
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full px-3 py-2.5 rounded-md text-sm"
      style={{ border: "1.5px solid #E2E6EC", color: "#1A2332", background: "#fff" }}
    >
      {children}
    </select>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props { onNav: (s: ScreenId) => void }

export default function RealtimeSetup({ onNav }: Props) {
  // Store
  const phase        = useRealtimeStore((s) => s.phase)
  const error        = useRealtimeStore((s) => s.error)
  const setError     = useRealtimeStore((s) => s.setError)
  const setCourtInfo = useRealtimeStore((s) => s.setCourtInfo)
  const setMyName    = useRealtimeStore((s) => s.setMyName)

  // Create-room form state
  const [createName, setCreateName]   = useState("")
  const [myLang, setMyLang]           = useState<LangCode>("en")
  const [partnerLang, setPartnerLang] = useState<LangCode>("es")
  const [division, setDivision]       = useState(COURT_DIVISIONS[0])
  const [courtroom, setCourtroom]     = useState(COURTROOMS[0])
  const [docket, setDocket]           = useState("")
  const [consent, setConsent]         = useState(false)

  // Join-room form state
  const [joinName, setJoinName] = useState("")
  const [joinCode, setJoinCode] = useState("")

  // WS hook — enqueueTts is a no-op in lobby (no audio sent in this phase)
  const { connect } = useRealtimeWebSocket({ enqueueTts: () => {} })

  // ── Navigation trigger ──────────────────────────────────────────────────────
  // When the server confirms room creation/join, phase becomes 'waiting' or
  // 'ready'. Disconnect the setup WS (RealtimeSession creates its own) then
  // navigate. This prevents orphan dual-connections.

  useEffect(() => {
    // Navigate to the session screen once the server confirms room creation/join.
    // Do NOT disconnect here — the open WebSocket keeps the room alive on the server.
    // RealtimeSession's wsRef is a module-level singleton so it will inherit the
    // live connection that was opened here.
    if (phase === "waiting" || phase === "ready" || phase === "active") {
      onNav(SCREENS.REALTIME_SESSION)
    }
  }, [phase, onNav])

  // ── Handlers ────────────────────────────────────────────────────────────────

  function handleCreate() {
    if (!createName.trim()) {
      setError("Please enter your name")
      return
    }
    if (myLang === partnerLang) {
      setError("You and your partner must speak different languages")
      return
    }
    if (!consent) {
      setError("Both parties must consent to AI-assisted interpretation")
      return
    }
    setError(null)
    setMyName(createName.trim())
    setCourtInfo(division, courtroom, docket.trim())
    connect({ name: createName.trim(), myLang, partnerLang })
  }

  function handleJoin() {
    const code = joinCode.trim().toUpperCase()
    if (!joinName.trim()) {
      setError("Please enter your name")
      return
    }
    if (code.length !== 6) {
      setError("Room code must be exactly 6 characters")
      return
    }
    setError(null)
    setMyName(joinName.trim())
    connect({ roomId: code, name: joinName.trim() })
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />

      <div className="max-w-4xl mx-auto px-5 py-8">
        <h1
          className="text-xl font-bold mb-2"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
        >
          Real-Time Interpretation
        </h1>
        <p className="text-sm mb-6" style={{ color: "#4A5568" }}>
          Create a new session room or join an existing one with a room code.
        </p>

        {/* Error banner */}
        {error && (
          <div
            className="rounded-md p-3 mb-4 text-sm"
            style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#991B1B" }}
          >
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">

          {/* ── Left: Create Room ──────────────────────────────────────────── */}
          <Card>
            <CardContent className="p-6 flex flex-col gap-4">
              <div>
                <h2
                  className="text-base font-semibold"
                  style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
                >
                  Create a Room
                </h2>
                <p className="text-xs mt-0.5" style={{ color: "#6B7280" }}>
                  You are the court official. Set the language pair and start a session.
                </p>
              </div>

              <Field label="Your name">
                <Input
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  placeholder="e.g. Judge Smith"
                  maxLength={40}
                />
              </Field>

              {/* Language pair picker */}
              <div>
                <label
                  className="text-xs font-semibold block mb-1.5"
                  style={{ color: "#4A5568" }}
                >
                  Language pair
                </label>
                <div className="flex items-center gap-2">
                  <div className="flex-1">
                    <p className="text-xs mb-1" style={{ color: "#6B7280" }}>You speak</p>
                    <StyledSelect value={myLang} onChange={(v) => setMyLang(v as LangCode)}>
                      {LANGUAGES.map((l) => (
                        <option key={l.value} value={l.value}>{l.label}</option>
                      ))}
                    </StyledSelect>
                  </div>
                  <span
                    className="mt-5 text-base font-semibold select-none"
                    style={{ color: "#6B7280" }}
                  >
                    ↔
                  </span>
                  <div className="flex-1">
                    <p className="text-xs mb-1" style={{ color: "#6B7280" }}>They speak</p>
                    <StyledSelect value={partnerLang} onChange={(v) => setPartnerLang(v as LangCode)}>
                      {LANGUAGES.map((l) => (
                        <option key={l.value} value={l.value}>{l.label}</option>
                      ))}
                    </StyledSelect>
                  </div>
                </div>
              </div>

              <Field label="Court division">
                <StyledSelect value={division} onChange={setDivision}>
                  {COURT_DIVISIONS.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </StyledSelect>
              </Field>

              <Field label="Courtroom">
                <StyledSelect value={courtroom} onChange={setCourtroom}>
                  {COURTROOMS.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </StyledSelect>
              </Field>

              <Field label="Case docket (optional)">
                <Input
                  value={docket}
                  onChange={(e) => setDocket(e.target.value)}
                  placeholder="e.g. 2026-CR-001234"
                />
              </Field>

              {/* Mic info banner */}
              <div
                className="rounded-md p-3"
                style={{ background: "#EFF6FF", border: "1px solid #BFDBFE" }}
              >
                <p className="text-xs leading-relaxed" style={{ color: "#1e40af" }}>
                  <strong>Microphone required.</strong> Grant browser mic permission when
                  prompted. Both participants need a working microphone and speakers.
                </p>
              </div>

              {/* Consent checkbox */}
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  className="mt-0.5 accent-slate-800"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                />
                <span className="text-xs leading-relaxed" style={{ color: "#4A5568" }}>
                  Both parties consent to AI-assisted interpretation for the purpose of
                  court proceedings.
                </span>
              </label>

              <Button
                className="w-full cursor-pointer"
                style={{ background: "#0B1D3A" }}
                onClick={handleCreate}
              >
                Create room
              </Button>
            </CardContent>
          </Card>

          {/* ── Right: Join Room ───────────────────────────────────────────── */}
          <Card>
            <CardContent className="p-6 flex flex-col gap-4">
              <div>
                <h2
                  className="text-base font-semibold"
                  style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
                >
                  Join a Room
                </h2>
                <p className="text-xs mt-0.5" style={{ color: "#6B7280" }}>
                  You are the respondent. Enter the room code provided by the court official.
                </p>
              </div>

              <Field label="Your name">
                <Input
                  value={joinName}
                  onChange={(e) => setJoinName(e.target.value)}
                  placeholder="e.g. Maria García"
                  maxLength={40}
                />
              </Field>

              <Field label="Room code">
                <Input
                  value={joinCode}
                  onChange={(e) => setJoinCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
                  placeholder="ABC123"
                  maxLength={6}
                  className="text-center tracking-widest font-mono text-lg uppercase"
                  style={{ letterSpacing: "0.25em" }}
                />
              </Field>

              <p className="text-xs" style={{ color: "#6B7280" }}>
                Ask the court official for the 6-character room code displayed on their screen.
              </p>

              {/* Spacer to visually align the Join button near the bottom */}
              <div className="flex-1" />

              {/* Mic info banner — mirrored for consistency */}
              <div
                className="rounded-md p-3"
                style={{ background: "#EFF6FF", border: "1px solid #BFDBFE" }}
              >
                <p className="text-xs leading-relaxed" style={{ color: "#1e40af" }}>
                  <strong>Microphone required.</strong> Grant browser mic permission when
                  prompted. You will hear the AI interpretation through your speakers.
                </p>
              </div>

              <Button
                className="w-full cursor-pointer"
                style={{ background: "#0B1D3A" }}
                onClick={handleJoin}
              >
                Join room
              </Button>
            </CardContent>
          </Card>

        </div>
      </div>

      <ScreenLabel name="REAL-TIME — SESSION SETUP" />
    </div>
  )
}
