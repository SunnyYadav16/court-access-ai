import { ScreenId } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

const scenarios = [
  { label: "Scenario A", val: "2", sub: "New Forms", color: "#16a34a" },
  { label: "Scenario B", val: "1", sub: "Updated", color: "#2563eb" },
  { label: "Scenario C", val: "0", sub: "Deleted (404)", color: "#8494A7" },
  { label: "Scenario D", val: "1", sub: "Renamed", color: "#d97706" },
  { label: "Scenario E", val: "41", sub: "No Changes", color: "#8494A7" },
]

const pendingForms = [
  { name: "Restraining Order Application (209A)", langs: "ES", since: "Feb 10" },
  { name: "Small Claims Statement", langs: "ES", since: "Jan 30" },
  { name: "Petition for Guardianship of Minor", langs: "ES, PT", since: "Feb 17" },
  { name: "Request for Interpreter Services", langs: "ES, PT", since: "Feb 17" },
]

export default function AdminForms({ onNav }: Props) {
  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar user="admin@mass.gov" role="admin" onNav={onNav} />
      <div className="max-w-3xl mx-auto px-5 py-6">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-xl font-bold mb-0.5"
              style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
              Form Scraper Management
            </h1>
            <p className="text-xs" style={{ color: "#8494A7" }}>
              Airflow DAG: form_scraper_dag · Last run: Monday, Feb 17, 2026
            </p>
          </div>
          <Button size="sm" style={{ background: "#0B1D3A" }} className="cursor-pointer">
            🔄 Trigger Manual Scrape
          </Button>
        </div>

        {/* Scrape summary */}
        <Card className="mb-3">
          <CardContent className="p-5">
            <div className="text-sm font-semibold mb-4" style={{ color: "#1A2332" }}>
              Last Scrape Results (Feb 17)
            </div>
            <div className="grid grid-cols-5 gap-3">
              {scenarios.map((s, i) => (
                <div key={i} className="text-center">
                  <div className="text-2xl font-bold mb-0.5"
                    style={{ color: s.color, fontFamily: "Palatino, Georgia, serif" }}>
                    {s.val}
                  </div>
                  <div className="text-[10px]" style={{ color: "#8494A7" }}>{s.label}</div>
                  <div className="text-[10px]" style={{ color: "#8494A7" }}>{s.sub}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Pending review */}
        <Card>
          <CardContent className="p-5">
            <div className="text-sm font-semibold mb-3" style={{ color: "#1A2332" }}>
              Pending Human Review (6 forms)
            </div>
            {pendingForms.map((f, i) => (
              <div key={i} className="flex items-center justify-between py-2.5 text-xs"
                style={{ borderTop: i ? "1px solid #E2E6EC" : "none" }}>
                <div>
                  <span className="font-medium" style={{ color: "#1A2332" }}>{f.name}</span>
                  <span className="ml-2" style={{ color: "#8494A7" }}>{f.langs} · since {f.since}</span>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" className="cursor-pointer text-xs">Review</Button>
                  <Button size="sm" className="cursor-pointer text-xs" style={{ background: "#0B1D3A" }}>Approve</Button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="ADMIN — FORM SCRAPER MANAGEMENT" />
    </div>
  )
}
