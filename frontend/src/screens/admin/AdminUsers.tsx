import { useEffect, useState } from "react"
import { ScreenId } from "@/lib/constants"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import { adminApi, type AdminUserRow } from "@/services/api"

interface Props { onNav: (s: ScreenId) => void }

const ROLES = ["public", "court_official", "interpreter", "admin"] as const

function formatLastActive(iso: string | null): string {
  if (!iso) return "Never"
  const d = new Date(iso)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - d.getTime()) / 86_400_000)
  if (diffDays === 0) return "Today"
  if (diffDays === 1) return "Yesterday"
  if (diffDays < 7) return `${diffDays}d ago`
  return d.toLocaleDateString([], { month: "short", day: "numeric" })
}

const PAGE_SIZE = 50

export default function AdminUsers({ onNav }: Props) {
  const [users, setUsers] = useState<AdminUserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [search, setSearch] = useState("")
  // userId → currently-selected role in the inline editor
  const [editing, setEditing] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<string | null>(null)

  async function fetchUsers(p: number) {
    setLoading(true)
    setError(null)
    try {
      const rows = await adminApi.listUsers(p, PAGE_SIZE)
      setUsers(rows)
      setHasMore(rows.length === PAGE_SIZE)
    } catch {
      setError("Failed to load users. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void fetchUsers(page) }, [page])

  async function handleSaveRole(userId: string) {
    const newRole = editing[userId]
    if (!newRole) return
    setSaving(userId)
    try {
      const updated = await adminApi.setUserRole(userId, newRole)
      setUsers((prev) =>
        prev.map((u) => (u.user_id === userId ? { ...u, role: updated.role } : u))
      )
      setEditing((prev) => { const next = { ...prev }; delete next[userId]; return next })
    } catch {
      setError(`Failed to update role for user.`)
    } finally {
      setSaving(null)
    }
  }

  const filtered = search.trim()
    ? users.filter(
        (u) =>
          u.name.toLowerCase().includes(search.toLowerCase()) ||
          u.email.toLowerCase().includes(search.toLowerCase())
      )
    : users

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />
      <div className="max-w-3xl mx-auto px-5 py-6">
        <div className="flex items-center justify-between mb-5">
          <h1 className="text-xl font-bold"
            style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
            User Management
          </h1>
          <div className="flex items-center gap-2">
            <input
              type="search"
              placeholder="Search name or email…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="text-xs px-3 py-1.5 rounded-md"
              style={{ border: "1.5px solid #E2E6EC", color: "#1A2332", background: "#fff", width: 200 }}
            />
            <span className="text-xs" style={{ color: "#8494A7" }}>
              Users register via the app
            </span>
          </div>
        </div>

        {error && (
          <div className="rounded-md px-3 py-2 text-xs mb-4"
            style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#991B1B" }}>
            {error}
          </div>
        )}

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
                {loading && (
                  <tr>
                    <td colSpan={6} className="px-4 py-6 text-center text-xs" style={{ color: "#8494A7" }}>
                      Loading…
                    </td>
                  </tr>
                )}
                {!loading && filtered.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-6 text-center text-xs" style={{ color: "#8494A7" }}>
                      {search ? "No users match your search." : "No users found."}
                    </td>
                  </tr>
                )}
                {!loading && filtered.map((u) => {
                  const isEditingThis = u.user_id in editing
                  const isSavingThis = saving === u.user_id
                  return (
                    <tr key={u.user_id} style={{ borderBottom: "1px solid #E2E6EC" }}>
                      <td className="px-4 py-3">
                        <div className="font-medium" style={{ color: "#1A2332" }}>{u.name}</div>
                        <div className="text-[11px]" style={{ color: "#8494A7" }}>{u.email}</div>
                      </td>
                      <td className="px-4 py-3">
                        {isEditingThis ? (
                          <select
                            value={editing[u.user_id]}
                            onChange={(e) => setEditing((prev) => ({ ...prev, [u.user_id]: e.target.value }))}
                            className="text-[11px] px-1.5 py-0.5 rounded"
                            style={{ border: "1.5px solid #C8963E", color: "#1A2332", background: "#fff" }}
                          >
                            {ROLES.map((r) => (
                              <option key={r} value={r}>{r.replace("_", " ")}</option>
                            ))}
                          </select>
                        ) : (
                          <span className="text-[10px] font-semibold px-2 py-0.5 rounded"
                            style={{ background: "#F5EDE0", color: "#C8963E" }}>
                            {u.role.replace("_", " ")}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3" style={{ color: "#8494A7" }}>
                        {formatLastActive(u.last_login_at)}
                      </td>
                      <td className="px-4 py-3" style={{ color: "#1A2332" }}>{u.session_count}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <div className="w-2 h-2 rounded-full"
                            style={{ background: u.is_active ? "#16a34a" : "#8494A7" }} />
                          <span style={{ color: "#8494A7" }}>{u.is_active ? "active" : "inactive"}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {isEditingThis ? (
                          <div className="flex gap-1.5">
                            <Button
                              size="sm"
                              className="cursor-pointer text-xs"
                              style={{ background: "#0B1D3A" }}
                              disabled={isSavingThis}
                              onClick={() => void handleSaveRole(u.user_id)}
                            >
                              {isSavingThis ? "…" : "Save"}
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              className="cursor-pointer text-xs"
                              disabled={isSavingThis}
                              onClick={() => setEditing((prev) => { const next = { ...prev }; delete next[u.user_id]; return next })}
                            >
                              ✕
                            </Button>
                          </div>
                        ) : (
                          <Button
                            size="sm"
                            variant="outline"
                            className="cursor-pointer text-xs"
                            onClick={() => setEditing((prev) => ({ ...prev, [u.user_id]: u.role }))}
                          >
                            Edit
                          </Button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>

        {/* Pagination */}
        {!loading && (hasMore || page > 1) && (
          <div className="flex items-center justify-between mt-3 text-xs" style={{ color: "#8494A7" }}>
            <span>Page {page}</span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                className="cursor-pointer text-xs"
                disabled={page === 1}
                onClick={() => setPage((p) => p - 1)}
              >
                ← Previous
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="cursor-pointer text-xs"
                disabled={!hasMore}
                onClick={() => setPage((p) => p + 1)}
              >
                Next →
              </Button>
            </div>
          </div>
        )}
      </div>
      <ScreenLabel name="ADMIN — USER MANAGEMENT" />
    </div>
  )
}
