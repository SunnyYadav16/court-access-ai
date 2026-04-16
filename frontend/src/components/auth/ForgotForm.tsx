/**
 * components/auth/ForgotForm.tsx
 *
 * Forgot password form rendered inside AuthModal.
 * Sends a Firebase password reset email.
 */

import { useState, type FormEvent } from "react";
import useAuthStore from "@/store/authStore";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function ForgotForm() {
  const { isLoading, error, sendPasswordReset, setAuthModalView } =
    useAuthStore();

  const [email, setEmail] = useState("");
  const [validationError, setValidationError] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setValidationError("");

    if (!email.trim()) {
      setValidationError("Email is required.");
      return;
    }
    if (!/\S+@\S+\.\S+/.test(email)) {
      setValidationError("Please enter a valid email address.");
      return;
    }

    await sendPasswordReset(email);
  };

  const displayError = validationError || error;

  return (
    <div className="text-center">
      <div
        className="w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-4"
        style={{ background: "#EFF6FF", border: "1px solid #BFDBFE" }}
      >
        <span className="text-2xl">🔑</span>
      </div>

      <h2
        className="text-xl font-bold mb-2"
        style={{ fontFamily: "Palatino, Georgia, serif", color: "#1A2332" }}
      >
        Forgot your password?
      </h2>
      <p
        className="text-xs mb-5 leading-relaxed"
        style={{ color: "#8494A7" }}
      >
        Enter your email and we'll send you a secure link to reset your
        password.
      </p>

      {displayError && (
        <div
          className="rounded-md p-3 mb-4 text-xs leading-relaxed text-left"
          style={{
            background: "#FEF2F2",
            border: "1px solid #FECACA",
            color: "#b91c1c",
          }}
        >
          {displayError}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="text-left mb-4">
          <label
            className="text-xs font-semibold block mb-1"
            style={{ color: "#4A5568" }}
          >
            Email address
          </label>
          <Input
            placeholder="name@mass.gov"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={isLoading}
          />
        </div>

        <Button
          type="submit"
          className="w-full cursor-pointer"
          style={{ background: "#1D4ED8" }}
          disabled={isLoading}
        >
          {isLoading ? (
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
              Sending…
            </span>
          ) : (
            "Send Reset Link"
          )}
        </Button>
      </form>

      <button
        onClick={() => setAuthModalView("login")}
        className="mt-4 text-xs font-medium flex items-center gap-1 mx-auto cursor-pointer"
        style={{ color: "#2563eb", background: "none", border: "none" }}
      >
        ← Back to sign in
      </button>
    </div>
  );
}
