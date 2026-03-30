import { ScreenId } from "@/lib/constants"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import { useAuth } from "@/hooks/useAuth"
import { getInitials } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

const InfoRow = ({ label, value, valueColor = "#1A2332" }: {
  label: string
  value: string | React.ReactNode
  valueColor?: string
}) => (
  <div className="flex items-center justify-between py-3 border-b last:border-b-0"
    style={{ borderColor: "#E2E6EC" }}>
    <span className="text-sm font-medium" style={{ color: "#8494A7" }}>{label}</span>
    <span className="text-sm font-medium" style={{ color: valueColor }}>{value}</span>
  </div>
)

export default function Settings({ onNav }: Props) {
  const { backendUser, role, signOut } = useAuth()

  const initials = getInitials(backendUser?.name, backendUser?.email)
  const displayRole = role?.replace("_", " ").toUpperCase() ?? "PUBLIC"

  const getProviderName = (provider: string) => {
    if (provider === "google.com") return "Google"
    if (provider === "microsoft.com") return "Microsoft"
    if (provider === "password") return "Email/Password"
    return provider
  }

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return "Never"
    const date = new Date(dateString)
    return date.toLocaleDateString("en-US", { year: "numeric", month: "long" })
  }

  const formatDateTime = (dateString?: string | null) => {
    if (!dateString) return "Never"
    const date = new Date(dateString)
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    })
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
  }

  const truncateUserId = (id: string) => {
    return id.slice(0, 8) + "..." + id.slice(-4)
  }

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />

      <div className="max-w-xl mx-auto px-5 py-8">
        <h1 className="text-2xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
          Settings
        </h1>
        <p className="text-sm mb-6" style={{ color: "#4A5568" }}>
          Manage your account and preferences
        </p>

        {/* Profile Card */}
        <Card className="mb-4">
          <CardContent className="p-6">
            <div className="flex items-center gap-4 mb-4">
              <div
                className="w-16 h-16 rounded-full flex items-center justify-center text-white text-xl font-bold flex-shrink-0"
                style={{ background: "#C8963E" }}
              >
                {initials}
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-lg font-bold truncate" style={{ color: "#1A2332" }}>
                  {backendUser?.name || "User"}
                </h2>
                <p className="text-sm truncate" style={{ color: "#8494A7" }}>
                  {backendUser?.email}
                </p>
                <div className="flex items-center gap-2 mt-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold tracking-wide"
                    style={{ background: "rgba(11, 29, 58, 0.08)", color: "#0B1D3A" }}>
                    {displayRole}
                  </span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold tracking-wide"
                    style={{ background: "#F5EDE0", color: "#C8963E" }}>
                    {getProviderName(backendUser?.auth_provider || "")}
                  </span>
                </div>
              </div>
            </div>
            <div className="text-xs" style={{ color: "#8494A7" }}>
              Member since {formatDate(backendUser?.created_at)}
            </div>
          </CardContent>
        </Card>

        {/* Account Details Card */}
        <Card className="mb-4">
          <CardContent className="p-6">
            <h3 className="text-sm font-bold mb-4" style={{ color: "#1A2332" }}>
              Account Details
            </h3>
            <div>
              <InfoRow
                label="User ID"
                value={
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs">
                      {truncateUserId(backendUser?.user_id || "")}
                    </span>
                    <button
                      onClick={() => copyToClipboard(backendUser?.user_id || "")}
                      className="text-xs hover:opacity-70"
                      style={{ color: "#2563eb" }}
                      title="Copy full User ID"
                    >
                      📋
                    </button>
                  </div>
                }
              />
              <InfoRow label="Email" value={backendUser?.email || ""} />
              <InfoRow
                label="Email Verified"
                value={
                  backendUser?.email_verified ? (
                    <span className="flex items-center gap-1" style={{ color: "#16a34a" }}>
                      <span>✓</span> Verified
                    </span>
                  ) : (
                    <span className="flex items-center gap-1" style={{ color: "#dc2626" }}>
                      <span>✗</span> Not Verified
                    </span>
                  )
                }
              />
              <InfoRow
                label="MFA Status"
                value={backendUser?.mfa_enabled ? "Enabled" : "Not Enabled"}
              />
              <InfoRow
                label="Role"
                value={
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold tracking-wide"
                    style={{ background: "rgba(11, 29, 58, 0.08)", color: "#0B1D3A" }}>
                    {displayRole}
                  </span>
                }
              />
              <InfoRow
                label="Auth Provider"
                value={getProviderName(backendUser?.auth_provider || "")}
              />
              <InfoRow
                label="Last Login"
                value={formatDateTime(backendUser?.last_login_at)}
              />
            </div>
          </CardContent>
        </Card>

        {/* Actions Card */}
        <Card>
          <CardContent className="p-6">
            <h3 className="text-sm font-bold mb-4" style={{ color: "#1A2332" }}>
              Account Actions
            </h3>
            <div className="flex flex-col gap-3">
              <button
                onClick={() => signOut()}
                className="w-full px-4 py-2.5 rounded text-sm font-medium transition-colors"
                style={{
                  background: "#fff",
                  border: "1px solid #dc2626",
                  color: "#dc2626"
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "#fef2f2"
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "#fff"
                }}
              >
                Sign Out
              </button>
              <button
                disabled
                title="Contact administrator to delete your account"
                className="w-full px-4 py-2.5 rounded text-sm font-medium cursor-not-allowed opacity-50"
                style={{
                  background: "#fff",
                  border: "1px solid #dc2626",
                  color: "#dc2626"
                }}
              >
                Delete Account
              </button>
              <p className="text-xs text-center" style={{ color: "#8494A7" }}>
                Account deletion requires administrator approval
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="SETTINGS" />
    </div>
  )
}
