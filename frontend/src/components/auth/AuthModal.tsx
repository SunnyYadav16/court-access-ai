/**
 * components/auth/AuthModal.tsx
 *
 * Main auth modal shell — renders as a fixed overlay on top of the landing page.
 * Switches between login, signup, forgot, reset_sent, and verify_email views.
 *
 * Non-dismissable when showing verify_email (user must verify before proceeding).
 */

import { useEffect } from "react";
import useAuthStore from "@/store/authStore";
import LoginForm from "./LoginForm";
import SignupForm from "./SignupForm";
import ForgotForm from "./ForgotForm";
import ResetSentView from "./ResetSentView";
import VerifyEmailView from "./VerifyEmailView";

/**
 * Render the authentication modal overlay with selectable views for login, signup, forgot password, reset-sent, and email verification.
 *
 * Locks document body scrolling while mounted. Shows a dismiss button and allows backdrop click or Escape to close the modal unless the active view is `"verify_email"`, in which case the modal is non-dismissable (no close button, backdrop clicks and Escape are ignored).
 *
 * @returns The modal's JSX element.
 */
export default function AuthModal() {
  const { authModalView, closeAuthModal } = useAuthStore();

  const isVerifyEmail = authModalView === "verify_email";
  const isDismissable = !isVerifyEmail;

  // Lock body scroll when modal is open
  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

  // ESC key closes modal (unless verify_email)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isDismissable) closeAuthModal();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isDismissable, closeAuthModal]);

  const renderView = () => {
    switch (authModalView) {
      case "login":
        return <LoginForm />;
      case "signup":
        return <SignupForm />;
      case "forgot":
        return <ForgotForm />;
      case "reset_sent":
        return <ResetSentView />;
      case "verify_email":
        return <VerifyEmailView />;
      default:
        return <LoginForm />;
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ animation: "authModalFadeIn 0.2s ease-out" }}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0"
        style={{
          background: "rgba(6, 16, 31, 0.7)",
          backdropFilter: "blur(4px)",
          WebkitBackdropFilter: "blur(4px)",
        }}
        onClick={isDismissable ? closeAuthModal : undefined}
      />

      {/* Modal card */}
      <div
        className="relative w-full max-w-md mx-4 rounded-xl shadow-2xl"
        style={{
          background: "#fff",
          maxHeight: "90vh",
          overflowY: "auto",
          animation: "authModalSlideUp 0.25s ease-out",
        }}
      >
        {/* Close button — hidden during verify_email */}
        {isDismissable && (
          <button
            onClick={closeAuthModal}
            className="absolute top-4 right-4 w-8 h-8 flex items-center justify-center rounded-full cursor-pointer transition-colors"
            style={{
              color: "#8494A7",
              background: "transparent",
              border: "none",
            }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.background = "#F1F5F9")
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.background = "transparent")
            }
            aria-label="Close"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <line x1="4" y1="4" x2="12" y2="12" />
              <line x1="12" y1="4" x2="4" y2="12" />
            </svg>
          </button>
        )}

        {/* Logo header */}
        <div className="text-center pt-7 pb-2 px-7">
          <span className="text-3xl">⚖</span>
          <h1
            className="text-lg font-bold tracking-wide mt-1"
            style={{
              fontFamily: "Palatino, Georgia, serif",
              color: "#0B1D3A",
            }}
          >
            CourtAccess AI
          </h1>
        </div>

        {/* Dynamic view content */}
        <div className="px-7 pb-7">{renderView()}</div>

        {/* Footer */}
        <div
          className="text-center text-[10px] py-4 px-7"
          style={{
            color: "#8494A7",
            borderTop: "1px solid #E2E6EC",
          }}
        >
          Protected system · All translations are AI-generated and not official
          legal records
        </div>
      </div>

      {/* Inline keyframe animations */}
      <style>{`
        @keyframes authModalFadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes authModalSlideUp {
          from { opacity: 0; transform: translateY(16px) scale(0.98); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
      `}</style>
    </div>
  );
}
