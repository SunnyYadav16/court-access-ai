import { ScreenId, SCREENS } from "@/lib/constants"

interface TopBarProps {
  user: string
  role: string
  onNav: (s: ScreenId) => void
}

export default function TopBar({ user, role, onNav }: TopBarProps) {
  const homeScreen = () => {
    if (role === "public") return SCREENS.HOME_PUBLIC
    if (role === "court_official") return SCREENS.HOME_OFFICIAL
    if (role === "interpreter") return SCREENS.HOME_INTERPRETER
    return SCREENS.HOME_ADMIN
  }

  return (
    <div className="h-14 px-6 flex items-center justify-between"
      style={{ background: "#0B1D3A", color: "#fff" }}>
      <div className="flex items-center gap-3 cursor-pointer"
        onClick={() => onNav(homeScreen())}>
        <span className="text-lg font-bold tracking-wide font-serif">⚖ CourtAccess AI</span>
        <span className="text-[10px] font-semibold px-2 py-0.5 rounded tracking-wide"
          style={{ background: "rgba(200,150,62,0.25)", color: "#C8963E" }}>BETA</span>
      </div>
      <div className="flex items-center gap-4 text-xs">
        <span style={{ color: "rgba(255,255,255,0.6)" }}>{user}</span>
        <span className="px-2 py-0.5 rounded text-[10px] font-semibold tracking-wide"
          style={{ background: "rgba(255,255,255,0.12)", color: "#fff" }}>
          {role.replace("_", " ").toUpperCase()}
        </span>
        <button
          onClick={() => onNav(SCREENS.LOGIN)}
          className="px-3 py-1 rounded text-[11px] cursor-pointer"
          style={{ background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.15)", color: "#fff" }}>
          Sign Out
        </button>
      </div>
    </div>
  )
}