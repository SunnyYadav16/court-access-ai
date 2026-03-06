import { ScreenId, SCREENS } from "@/lib/constants"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

const FeatureCard = ({ icon, title, desc, badge, onClick }: {
  icon: string, title: string, desc: string, badge?: string, onClick: () => void
}) => (
  <Card onClick={onClick} className="cursor-pointer hover:shadow-md transition-shadow">
    <CardContent className="p-4 flex items-center gap-4">
      <div className="w-12 h-12 rounded-lg flex items-center justify-center text-2xl flex-shrink-0"
        style={{ background: "#F5EDE0" }}>
        {icon}
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold" style={{ color: "#1A2332" }}>{title}</h3>
          {badge && (
            <span className="text-[10px] font-semibold px-2 py-0.5 rounded tracking-wide"
              style={{ background: "#F5EDE0", color: "#C8963E" }}>
              {badge}
            </span>
          )}
        </div>
        <p className="text-xs mt-0.5 leading-relaxed" style={{ color: "#4A5568" }}>{desc}</p>
      </div>
      <span className="text-lg" style={{ color: "#8494A7" }}>›</span>
    </CardContent>
  </Card>
)

const sessions = [
  { id: "S-20260222-001", lang: "Spanish", type: "Real-Time", time: "Today, 9:15 AM", dur: "42 min" },
  { id: "S-20260221-014", lang: "Portuguese", type: "Document", time: "Yesterday, 2:30 PM", dur: "—" },
  { id: "S-20260220-008", lang: "Spanish", type: "Real-Time", time: "Feb 20, 10:00 AM", dur: "1h 15m" },
]

export default function HomeOfficial({ onNav }: Props) {
  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar user="judge.thompson@mass.gov" role="court_official" onNav={onNav} />

      {/* Welcome banner */}
      <div className="px-5 py-3" style={{ background: "#EFF6FF", borderBottom: "1px solid #BFDBFE" }}>
        <div className="max-w-xl mx-auto">
          <p className="text-xs leading-relaxed" style={{ color: "#1e40af" }}>
            👋 <strong>Welcome back, Judge Thompson.</strong> As a court official, you can start
            live real-time interpretation sessions, upload documents for translation, or access
            pre-translated court forms using the services below.
          </p>
        </div>
      </div>

      <div className="max-w-xl mx-auto px-5 py-8">
        <h1 className="text-2xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
          Welcome, Judge Thompson
        </h1>
        <p className="text-sm mb-6" style={{ color: "#4A5568" }}>
          Court translation and interpretation services
        </p>

        <div className="flex flex-col gap-3 mb-5">
          <FeatureCard icon="🎙" title="Real-Time Translation"
            desc="Start a live courtroom interpretation session with bidirectional speech translation"
            badge="LIVE" onClick={() => onNav(SCREENS.REALTIME_SETUP)} />
          <FeatureCard icon="📄" title="Upload Document"
            desc="Upload a legal PDF document for AI-powered translation"
            onClick={() => onNav(SCREENS.DOC_UPLOAD)} />
          <FeatureCard icon="🏛" title="Government Forms"
            desc="Browse pre-translated Massachusetts court forms"
            badge="45 FORMS" onClick={() => onNav(SCREENS.FORMS_LIBRARY)} />
        </div>

        <Card>
          <CardContent className="p-4">
            <div className="text-xs font-semibold mb-3" style={{ color: "#1A2332" }}>
              Recent Sessions
            </div>
            {sessions.map((s, i) => (
              <div key={i} className="flex items-center justify-between py-2 text-xs"
                style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}>
                <div>
                  <span className="font-medium" style={{ color: "#1A2332" }}>{s.id}</span>
                  <span className="ml-2" style={{ color: "#8494A7" }}>{s.type} · {s.lang}</span>
                </div>
                <div className="text-right" style={{ color: "#8494A7" }}>
                  <div>{s.time}</div>
                  {s.dur !== "—" && <div className="text-[11px]">{s.dur}</div>}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="HOME — COURT OFFICIAL" />
    </div>
  )
}