import { useState } from "react"

interface WelcomeBannerProps {
  firstName: string
  roleDescription: string
}

export default function WelcomeBanner({ firstName, roleDescription }: WelcomeBannerProps) {
  const [showBanner, setShowBanner] = useState(true)

  if (!showBanner) return null

  return (
    <div className="px-5 py-3" style={{ background: "#EFF6FF", borderBottom: "1px solid #BFDBFE" }}>
      <div className="max-w-7xl mx-auto flex items-start justify-between gap-4 px-6">
        <p className="text-xs leading-relaxed flex-1" style={{ color: "#1e40af" }}>
          👋 <strong>Welcome, {firstName}.</strong> {roleDescription}
        </p>
        <button
          onClick={() => setShowBanner(false)}
          className="flex-shrink-0 text-xl leading-none hover:opacity-70 transition-opacity mt-0.5"
          style={{ color: "#1e40af" }}
          aria-label="Dismiss welcome banner"
        >
          ×
        </button>
      </div>
    </div>
  )
}
