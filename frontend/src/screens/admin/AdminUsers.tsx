import { ScreenId } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"

interface Props { onNav: (s: ScreenId) => void }

const users = [
  { name: "Judge Thompson", email: "judge.thompson@mass.gov", role: "court_official", active: "Today", sessions: 142, status: "active" },
  { name: "Maria Santos", email: "maria.santos@gmail.com", role: "public", active: "Today", sessions: 8, status: "active" },
  { name: "Ana Garcia", email: "ana.garcia@interpreter.org", role: "interpreter", active: "Yesterday", sessions: 67, status: "active" },
  { name: "Clerk Wilson", email: "clerk.wilson@mass.gov", role: "court_official", active: "Feb 19", sessions: 34, status: "active" },
  { name: "John Doe", email: "john.doe@gmail.com", role: "public", active: "Feb 10", sessions: 2, status: "inactive" },
]

export default function AdminUsers({ onNav }: Props) {
  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar user="admin@mass.gov" role="admin" onNav={onNav} />
      <div className="max-w-3xl mx-auto px-5 py-6">
        <div className="flex items-center justify-between mb-5">
          <h1 className="text-xl font-bold"
            style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
            User Management
          </h1>
          <Button size="sm" style={{ background: "#0B1D3A" }} className="cursor-pointer">
            ＋ Add User
          </Button>
        </div>

        <Card>
          <CardContent className="p-0">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr style={{ borderBottom: "2px solid #E2E6EC" }}>
                  {["User", "Role", "Last Active", "Sessions", "Status", ""].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-[11px] uppercase tracking-wide font-semibold"
                      style={{ color: "#8494A7" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.map((u, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid #E2E6EC" }}>
                    <td className="px-4 py-3">
                      <div className="font-medium" style={{ color: "#1A2332" }}>{u.name}</div>
                      <div className="text-[11px]" style={{ color: "#8494A7" }}>{u.email}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded"
                        style={{ background: "#F5EDE0", color: "#C8963E" }}>
                        {u.role.replace("_", " ")}
                      </span>
                    </td>
                    <td className="px-4 py-3" style={{ color: "#8494A7" }}>{u.active}</td>
                    <td className="px-4 py-3" style={{ color: "#1A2332" }}>{u.sessions}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <div className="w-2 h-2 rounded-full"
                          style={{ background: u.status === "active" ? "#16a34a" : "#8494A7" }} />
                        <span style={{ color: "#8494A7" }}>{u.status}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Button size="sm" variant="outline" className="cursor-pointer text-xs">
                        Edit
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="ADMIN — USER MANAGEMENT" />
    </div>
  )
}
