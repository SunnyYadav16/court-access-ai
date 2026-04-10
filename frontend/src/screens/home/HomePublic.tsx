import { ScreenId, SCREENS } from "@/lib/constants"
import { Card, CardContent } from "@/components/ui/card"
import TopBar from "@/components/shared/TopBar"
import ScreenLabel from "@/components/shared/ScreenLabel"
import WelcomeBanner from "@/components/shared/WelcomeBanner"
import { useAuth } from "@/hooks/useAuth"
import { getFirstName } from "@/lib/utils"

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

export default function HomePublic({ onNav }: Props) {
  const { backendUser } = useAuth()
  const firstName = getFirstName(backendUser?.name, backendUser?.email)

  return (
    <div className="min-h-screen" style={{ background: "#F6F7F9" }}>
      <TopBar onNav={onNav} />

      <WelcomeBanner
        firstName={firstName}
        roleDescription="As a public user, you can upload legal documents for translation or browse pre-translated court forms in Spanish and Portuguese using the services below."
      />

      <div className="max-w-7xl mx-auto px-5 py-8">
        <h1 className="text-2xl font-bold mb-1"
          style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}>
          Document Translation
        </h1>
        <p className="text-sm mb-6" style={{ color: "#4A5568" }}>
          Translate legal documents into Spanish or Portuguese
        </p>

        <div className="flex flex-col gap-3">
          <FeatureCard icon="📄" title="Upload Document"
            desc="Upload a legal PDF document for AI-powered translation"
            onClick={() => onNav(SCREENS.DOC_UPLOAD)} />
          <FeatureCard icon="🏛" title="Government Forms"
            desc="Browse pre-translated Massachusetts court forms"
            onClick={() => onNav(SCREENS.FORMS_LIBRARY)} />
        </div>

        <Card className="mt-6" style={{ background: "#F5EDE0", border: "1px solid rgba(200,150,62,0.2)" }}>
          <CardContent className="p-4">
            <p className="text-xs leading-relaxed" style={{ color: "#4A5568" }}>
              <strong style={{ color: "#1A2332" }}>⚠ Important Notice:</strong> All translations are
              machine-generated for convenience only. They are NOT legal advice and NOT the official
              court record. Always verify with a qualified interpreter for legal proceedings.
            </p>
          </CardContent>
        </Card>
      </div>
      <ScreenLabel name="HOME — PUBLIC USER" />
    </div>
  )
}
