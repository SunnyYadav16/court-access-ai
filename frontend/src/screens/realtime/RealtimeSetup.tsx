import { useState } from "react"
import { ScreenId, SCREENS } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import useRealtimeStore from "@/store/realtimeStore"
import { realtimeApi } from "@/services/api"
import { useAuth } from "@/hooks/useAuth"
import { getFirstName } from "@/lib/utils"

// ── Constants ─────────────────────────────────────────────────────────────────

const PARTNER_LANGUAGES = [
  { value: "es", label: "Spanish (Español)" },
  { value: "pt", label: "Portuguese (Português)" },
] as const

type PartnerLang = "es" | "pt"

const COURT_DIVISIONS = [
  "Boston Municipal Court",
  "Worcester District Court",
  "Suffolk Superior Court",
  "Springfield District Court",
  "Cambridge District Court",
  "Middlesex Superior Court",
]

const COURTROOMS = [
  "Courtroom 1",
  "Courtroom 3",
  "Courtroom 5A",
  "Courtroom 7",
  "Courtroom 12",
  "Courtroom 14B",
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function Field({ label, required, children }: {
  label: string
  required?: boolean
  children: React.ReactNode
}) {
  return (
    <div>
      <label className="text-xs font-semibold block mb-1.5" style={{ color: "#4A5568" }}>
        {label}
        {required && <span className="ml-0.5" style={{ color: "#DC2626" }}>*</span>}
      </label>
      {children}
    </div>
  )
}

function StyledSelect({ value, onChange, children }: {
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
  const { backendUser } = useAuth()
  const officialName = getFirstName(backendUser?.name, backendUser?.email)

  // Store
  const setMyName    = useRealtimeStore((s) => s.setMyName)
  const setMyLanguage = useRealtimeStore((s) => s.setMyLanguage)
  const setCourtInfo = useRealtimeStore((s) => s.setCourtInfo)
  const setLobbyInfo = useRealtimeStore((s) => s.setLobbyInfo)

  // Form state
  const [partnerLang, setPartnerLang] = useState<PartnerLang>("es")
  const [division, setDivision]       = useState(COURT_DIVISIONS[0])
  const [courtroom, setCourtroom]     = useState(COURTROOMS[0])
  const [docket, setDocket]           = useState("")
  const [partnerName, setPartnerName] = useState("")
  const [consent, setConsent]         = useState(false)

  // Submission state
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)

  // ── Submit ───────────────────────────────────────────────────────────────────

  async function handleSubmit() {
    if (!partnerName.trim()) {
      setError("Please enter the LEP individual's name.")
      return
    }
    if (!consent) {
      setError("Both parties must be informed before starting the session.")
      return
    }

    setError(null)
    setLoading(true)

    try {
      const res = await realtimeApi.createRoom({
        target_language: partnerLang,
        court_division: division,
        courtroom,
        case_docket: docket.trim() || null,
        partner_name: partnerName.trim(),
        consent_acknowledged: true,
      })

      // Seed store so the lobby and session screens have the correct context
      setMyName(backendUser?.name ?? officialName)
      setMyLanguage("en")
      setCourtInfo(division, courtroom, docket.trim())
      setLobbyInfo(res.session_id, res.room_code, res.join_url, res.room_code_expires_at, partnerName.trim(), partnerLang)

      onNav(SCREENS.REALTIME_LOBBY)
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : "Failed to create room. Please try again."
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />

      <div className="max-w-lg mx-auto px-5 py-8">
        <h1
          className="text-xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
        >
          Start Interpretation Session
        </h1>
        <p className="text-sm mb-6" style={{ color: "#4A5568" }}>
          Fill in the session details. A join code will be generated for the LEP individual.
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

        <Card>
          <CardContent className="p-6 flex flex-col gap-5">

            {/* LEP Individual's Name */}
            <Field label="LEP Individual's Name" required>
              <Input
                value={partnerName}
                onChange={(e) => setPartnerName(e.target.value)}
                placeholder="e.g. Maria García"
                maxLength={100}
                disabled={loading}
              />
            </Field>

            {/* Partner language */}
            <Field label="LEP Individual's Language" required>
              <StyledSelect value={partnerLang} onChange={(v) => setPartnerLang(v as PartnerLang)}>
                {PARTNER_LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>{l.label}</option>
                ))}
              </StyledSelect>
              <p className="text-[11px] mt-1" style={{ color: "#8494A7" }}>
                Court official (you) will speak English.
              </p>
            </Field>

            {/* Court Division */}
            <Field label="Court Division" required>
              <StyledSelect value={division} onChange={setDivision}>
                {COURT_DIVISIONS.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </StyledSelect>
            </Field>

            {/* Courtroom */}
            <Field label="Courtroom" required>
              <StyledSelect value={courtroom} onChange={setCourtroom}>
                {COURTROOMS.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </StyledSelect>
            </Field>

            {/* Case Docket */}
            <Field label="Case Docket (optional)">
              <Input
                value={docket}
                onChange={(e) => setDocket(e.target.value)}
                placeholder="e.g. 2026-CR-001234"
                maxLength={50}
                disabled={loading}
              />
            </Field>

            {/* Consent */}
            <label className="flex items-start gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                className="mt-0.5 accent-slate-800"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                disabled={loading}
              />
              <span className="text-xs leading-relaxed" style={{ color: "#4A5568" }}>
                Both parties have been informed this session uses AI-assisted interpretation
                and have consented to its use for court proceedings.
              </span>
            </label>

            <Button
              className="w-full cursor-pointer"
              style={{ background: "#0B1D3A" }}
              onClick={handleSubmit}
              disabled={loading}
            >
              {loading ? "Creating session…" : "Create Session"}
            </Button>

          </CardContent>
        </Card>

        {/* Mic notice */}
        <div
          className="mt-4 rounded-md p-3"
          style={{ background: "#EFF6FF", border: "1px solid #BFDBFE" }}
        >
          <p className="text-xs leading-relaxed" style={{ color: "#1e40af" }}>
            <strong>Microphone required.</strong> After creating the session, grant browser mic
            permission when prompted. Both participants need a working microphone and speakers.
          </p>
        </div>
      </div>

      <ScreenLabel name="REAL-TIME — SESSION SETUP" />
    </div>
  )
}
