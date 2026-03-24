import { ScreenId, SCREENS } from "@/lib/constants"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

const forms = [
  { name: "Notice of Appearance", div: "All Divisions", langs: ["ES","PT"], review: false, archived: false, updated: "Feb 18, 2026" },
  { name: "Affidavit of Indigency", div: "District Court", langs: ["ES","PT"], review: false, archived: false, updated: "Feb 15, 2026" },
  { name: "Restraining Order Application (209A)", div: "Probate & Family", langs: ["ES"], review: true, archived: false, updated: "Feb 10, 2026" },
  { name: "Motion to Continue", div: "Superior Court", langs: ["ES","PT"], review: false, archived: false, updated: "Feb 8, 2026" },
  { name: "Small Claims Statement", div: "District Court", langs: ["ES"], review: true, archived: false, updated: "Jan 30, 2026" },
  { name: "Complaint for Divorce (1A)", div: "Probate & Family", langs: ["ES","PT"], review: false, archived: false, updated: "Jan 22, 2026" },
  { name: "Petition for Name Change", div: "Probate & Family", langs: ["ES"], review: false, archived: true, updated: "Jan 15, 2026" },
]

export default function FormsLibrary({ onNav }: Props) {
  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />
      <div className="max-w-2xl mx-auto px-5 py-8">
        <h1 className="text-xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
          Government Forms Library
        </h1>
        <p className="text-xs mb-5" style={{ color: "#8494A7" }}>
          Pre-translated Massachusetts court forms · 45 forms available
        </p>

        {/* Filters */}
        <div className="flex gap-2 mb-4">
          <div className="flex-1">
            <Input placeholder="🔍 Search forms..." />
          </div>
          <select className="px-3 py-2 rounded-md text-xs"
            style={{ border: "1.5px solid #E2E6EC", color: "#1A2332", background: "#fff" }}>
            <option>All Divisions</option>
            <option>District Court</option>
            <option>Superior Court</option>
            <option>Probate & Family</option>
          </select>
          <select className="px-3 py-2 rounded-md text-xs"
            style={{ border: "1.5px solid #E2E6EC", color: "#1A2332", background: "#fff" }}>
            <option>All Languages</option>
            <option>Spanish</option>
            <option>Portuguese</option>
          </select>
        </div>

        {/* Form list */}
        <div className="flex flex-col gap-2">
          {forms.map((f, i) => (
            <Card key={i} onClick={() => onNav(SCREENS.FORM_DETAIL)}
              className="cursor-pointer hover:shadow-md transition-shadow">
              <CardContent className="p-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-xl" style={{ color: "#8494A7" }}>📋</span>
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium" style={{ color: "#1A2332" }}>{f.name}</span>
                      {f.review && (
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded"
                          style={{ background: "#FEF3C7", color: "#d97706" }}>
                          PENDING REVIEW
                        </span>
                      )}
                      {f.archived && (
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded"
                          style={{ background: "#FEE2E2", color: "#dc2626" }}>
                          ARCHIVED
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] mt-0.5 flex items-center gap-1" style={{ color: "#8494A7" }}>
                      {f.div} · Updated {f.updated} ·{" "}
                      {f.langs.map(l => (
                        <span key={l} className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                          style={{ background: "#E5E7EB", color: "#4A5568" }}>
                          {l}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
                <span style={{ color: "#8494A7" }}>›</span>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
      <ScreenLabel name="GOVERNMENT FORMS LIBRARY" />
    </div>
  )
}
