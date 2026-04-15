/**
 * components/auth/VerifyEmailView.tsx
 *
 * Email verification view rendered inside AuthModal.
 * Shown when an email/password user has emailVerified === false.
 *
 * Non-dismissable — AuthModal hides the X button and ignores backdrop clicks.
 * User stays signed in (gated from all app routes by emailVerified check).
 *
 * Uses Firebase link-based verification (no 6-digit code).
 */

import { useState, useEffect, useCallback } from "react";
import useAuthStore from "@/store/authStore";
import { auth } from "@/config/firebase";
import { Button } from "@/components/ui/button";

export default function VerifyEmailView() {
  const {
    isLoading,
    error,
    pendingVerificationEmail,
    resendVerificationEmail,
    signOut,
    setAuthModalView,
    clearError,
  } = useAuthStore();

  const [resendCooldown, setResendCooldown] = useState(0);
  const [checking, setChecking] = useState(false);
  const [checkMessage, setCheckMessage] = useState("");

  // Cooldown timer
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const timer = setInterval(() => {
      setResendCooldown((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [resendCooldown]);

  const handleResend = useCallback(async () => {
    if (resendCooldown > 0) return;
    clearError();
    await resendVerificationEmail();
    setResendCooldown(60);
  }, [resendCooldown, resendVerificationEmail, clearError]);

  const handleCheckVerified = useCallback(async () => {
    setChecking(true);
    setCheckMessage("");

    try {
      const user = auth.currentUser;
      if (!user) {
        setCheckMessage("No active session. Please sign in again.");
        setChecking(false);
        return;
      }

      // Reload user data from Firebase to get fresh emailVerified status
      await user.reload();

      if (user.emailVerified) {
        // Force a token refresh so the backend gets the updated emailVerified claim
        await user.getIdToken(true);
        // Re-trigger the auth state change to proceed with authentication
        // The store's handleAuthStateChange will see emailVerified === true
        // and proceed to fetch the backend user profile
        const store = useAuthStore.getState();
        await store.fetchBackendUser();
      } else {
        setCheckMessage(
          "Your email hasn't been verified yet. Please click the link in your email."
        );
      }
    } catch {
      setCheckMessage("Something went wrong. Please try again.");
    } finally {
      setChecking(false);
    }
  }, []);

  const handleWrongEmail = async () => {
    await signOut();
    setAuthModalView("signup");
  };

  const displayEmail =
    pendingVerificationEmail || auth.currentUser?.email || "your email";

  return (
    <div className="text-center">
      <div
        className="w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4"
        style={{ background: "#DCFCE7", border: "1px solid #86efac" }}
      >
        <span className="text-2xl">✉️</span>
      </div>

      <h2
        className="text-xl font-bold mb-2"
        style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
      >
        Check your email
      </h2>
      <p className="text-sm leading-relaxed mb-4" style={{ color: "#8494A7" }}>
        We sent a verification link to
        <br />
        <strong style={{ color: "#1A2332" }}>{displayEmail}</strong>
      </p>

      <div
        className="rounded-md p-3 mb-5 text-left"
        style={{ background: "#EFF6FF", border: "1px solid #BFDBFE" }}
      >
        <p className="text-xs leading-relaxed" style={{ color: "#1e40af" }}>
          <strong>Click the link in the email to verify your account.</strong>{" "}
          The link expires in 24 hours.
        </p>
      </div>

      {/* Error display */}
      {error && (
        <div
          className="rounded-md p-3 mb-4 text-xs leading-relaxed text-left"
          style={{
            background: "#FEF2F2",
            border: "1px solid #FECACA",
            color: "#b91c1c",
          }}
        >
          {error}
        </div>
      )}

      {/* Check message */}
      {checkMessage && (
        <div
          className="rounded-md p-3 mb-4 text-xs leading-relaxed text-left"
          style={{
            background: "#FFFBEB",
            border: "1px solid #FDE68A",
            color: "#92400e",
          }}
        >
          {checkMessage}
        </div>
      )}

      {/* I've verified button */}
      <Button
        onClick={handleCheckVerified}
        className="w-full cursor-pointer mb-3"
        style={{ background: "#1D4ED8" }}
        disabled={checking || isLoading}
      >
        {checking ? (
          <span className="flex items-center gap-2 justify-center">
            <svg
              className="animate-spin h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            Checking…
          </span>
        ) : (
          "I've verified my email"
        )}
      </Button>

      {/* Actions */}
      <div className="flex flex-col gap-2 items-center">
        <span className="text-xs" style={{ color: "#8494A7" }}>
          Didn't receive it?{" "}
          <button
            onClick={handleResend}
            disabled={resendCooldown > 0 || isLoading}
            className="font-medium cursor-pointer disabled:cursor-not-allowed"
            style={{
              color: resendCooldown > 0 ? "#8494A7" : "#2563eb",
              background: "none",
              border: "none",
            }}
          >
            {resendCooldown > 0
              ? `Resend in ${resendCooldown}s`
              : "Resend verification email"}
          </button>
        </span>

        <button
          onClick={handleWrongEmail}
          className="text-xs cursor-pointer"
          style={{ color: "#8494A7", background: "none", border: "none" }}
        >
          Wrong email?{" "}
          <span style={{ color: "#2563eb", fontWeight: 600 }}>
            Change address
          </span>
        </button>
      </div>
    </div>
  );
}
