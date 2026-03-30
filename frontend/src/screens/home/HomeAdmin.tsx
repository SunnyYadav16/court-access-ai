import { ScreenId, SCREENS } from "@/lib/constants"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import WelcomeBanner from "@/components/shared/WelcomeBanner"
import { useAuth } from "@/hooks/useAuth"
import { getFirstName } from "@/lib/utils"

interface Props { onNav: (s: ScreenId) => void }

const FeatureCard = ({ icon, title, desc, onClick }: {
  icon: string, title: string, desc: string, onClick: () => void
}) => (
  <Card onClick={onClick} className="cursor-pointer hover:shadow-md transition-shadow">
    <CardContent className="p-4 flex items-center gap-4">
      <div className="w-12 h-12 rounded-lg flex items-center justify-center text-2xl flex-shrink-0"
        style={{ background: "#F5EDE0" }}>
        {icon}
      </div>
      <div className="flex-1">
        <h3 className="text-sm font-semibold" style={{ color: "#1A2332" }}>{title}</h3>
        <p className="text-xs mt-0.5" style={{ color: "#4A5568" }}>{desc}</p>
      </div>
      <span className="text-lg" style={{ color: "#8494A7" }}>›</span>
    </CardContent>
  </Card>
)

export default function HomeAdmin({ onNav }: Props) {
  const { backendUser } = useAuth()
  const firstName = getFirstName(backendUser?.name, backendUser?.email)

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />

      <WelcomeBanner
        firstName={firstName}
        roleDescription="You have full system access — monitor pipeline health and model metrics, manage users and roles, oversee form translations, and access all services below."
      />

      <div className="max-w-7xl mx-auto px-5 py-8">
        <h1 className="text-2xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
          System Administration
        </h1>
        <p className="text-sm mb-6" style={{ color: "#4A5568" }}>
          Manage users, monitor system health, and configure settings
        </p>
        <div className="grid grid-cols-2 gap-3">
          <FeatureCard icon="📊" title="Monitoring Dashboard"
            desc="System health, model metrics, alerts"
            onClick={() => onNav(SCREENS.ADMIN_DASHBOARD)} />
          <FeatureCard icon="👥" title="User Management"
            desc="Manage roles and access control"
            onClick={() => onNav(SCREENS.ADMIN_USERS)} />
          <FeatureCard icon="🏛" title="Form Management"
            desc="Manage scraped forms and translations"
            onClick={() => onNav(SCREENS.ADMIN_FORMS)} />
          <FeatureCard icon="🎙" title="Real-Time Translation"
            desc="Start a live interpretation session"
            onClick={() => onNav(SCREENS.REALTIME_SETUP)} />
          <FeatureCard icon="📄" title="Upload Document"
            desc="Translate a legal document"
            onClick={() => onNav(SCREENS.DOC_UPLOAD)} />
          <FeatureCard icon="🏛" title="Government Forms"
            desc="Browse pre-translated forms"
            onClick={() => onNav(SCREENS.FORMS_LIBRARY)} />
        </div>
      </div>
      <ScreenLabel name="HOME — ADMIN" />
    </div>
  )
}
