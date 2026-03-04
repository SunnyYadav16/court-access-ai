/**
 * components/Navbar.jsx
 *
 * Sticky navigation bar for CourtAccess AI.
 * Renders different nav links depending on authentication state.
 */

import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

export default function Navbar() {
    const { isAuthenticated, user, logout } = useAuth();
    const navigate = useNavigate();

    const handleLogout = async () => {
        await logout();
        navigate("/login");
    };

    return (
        <header className="navbar" role="banner">
            <div className="navbar__inner">
                {/* Logo */}
                <NavLink to="/" className="navbar__logo" aria-label="CourtAccess AI home">
                    ⚖️ Court<span>Access</span> AI
                </NavLink>

                {/* Nav links */}
                <nav aria-label="Main navigation">
                    <ul className="navbar__links">
                        <li>
                            <NavLink to="/forms" className={({ isActive }) => `navbar__link${isActive ? " active" : ""}`}>
                                Court Forms
                            </NavLink>
                        </li>

                        {isAuthenticated && (
                            <>
                                <li>
                                    <NavLink to="/sessions/new" className={({ isActive }) => `navbar__link${isActive ? " active" : ""}`}>
                                        Live Interpret
                                    </NavLink>
                                </li>
                                <li>
                                    <NavLink to="/documents" className={({ isActive }) => `navbar__link${isActive ? " active" : ""}`}>
                                        My Documents
                                    </NavLink>
                                </li>
                            </>
                        )}

                        {user?.role === "admin" || user?.role === "court_official" ? (
                            <li>
                                <NavLink to="/admin" className={({ isActive }) => `navbar__link${isActive ? " active" : ""}`}>
                                    Admin
                                </NavLink>
                            </li>
                        ) : null}
                    </ul>
                </nav>

                {/* Auth actions */}
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                    {isAuthenticated ? (
                        <>
                            <NavLink to="/dashboard" className="btn btn-ghost btn--sm">
                                {user?.username ?? "Dashboard"}
                            </NavLink>
                            <button id="btn-logout" className="btn btn-secondary btn--sm" onClick={handleLogout}>
                                Log out
                            </button>
                        </>
                    ) : (
                        <>
                            <NavLink to="/login" className="btn btn-ghost btn--sm" id="btn-login-nav">
                                Log in
                            </NavLink>
                            <NavLink to="/register" className="btn btn-primary btn--sm" id="btn-register-nav">
                                Register
                            </NavLink>
                        </>
                    )}
                </div>
            </div>
        </header>
    );
}
