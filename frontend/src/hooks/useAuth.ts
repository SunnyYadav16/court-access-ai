import { useState, useEffect, useCallback } from "react";
import {
  onAuthStateChanged,
  signInWithPopup,
  signInWithRedirect,
  getRedirectResult,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  sendEmailVerification,
  sendPasswordResetEmail,
  signOut as firebaseSignOut,
  GoogleAuthProvider,
  OAuthProvider,
  browserLocalPersistence,
  setPersistence,
  User as FirebaseUser,
} from "firebase/auth";
import { auth } from "@/config/firebase";
import api from "@/services/api";

export type AuthState =
  | "loading"
  | "unauthenticated"
  | "needs_email_verification"
  | "needs_role_selection"
  | "authenticated";

export interface AuthHook {
  user: FirebaseUser | null;
  authState: AuthState;
  role: string | null;
  error: string | null;
  setError: (e: string | null) => void;
  signInWithGoogle: () => Promise<void>;
  signInWithMicrosoft: () => Promise<void>;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  createAccount: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  resendVerificationEmail: () => Promise<void>;
  checkEmailVerified: () => Promise<void>;
  getToken: () => Promise<string | null>;
  sendPasswordReset: (email: string) => Promise<boolean>;
}

export function useAuth(): AuthHook {
  const [user, setUser] = useState<FirebaseUser | null>(null);
  const [authState, setAuthState] = useState<AuthState>("loading");
  const [role, setRole] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Handle redirect result on page load (after Google/Microsoft redirect)
  useEffect(() => {
    // Set persistence to LOCAL so auth survives page reloads
    setPersistence(auth, browserLocalPersistence).catch(console.error);

    getRedirectResult(auth)
      .then((result) => {
        if (result?.user) {
          console.log("Redirect sign-in successful:", result.user.email);
        }
      })
      .catch((e) => {
        console.error("Redirect error:", e);
        setError(friendlyError(e.code));
      });
  }, []);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (firebaseUser) => {
      setError(null);

      if (!firebaseUser) {
        setUser(null);
        setRole(null);
        setAuthState("unauthenticated");
        return;
      }

      setUser(firebaseUser);

      // Email/password users must verify before proceeding
      if (
        !firebaseUser.emailVerified &&
        firebaseUser.providerData[0]?.providerId === "password"
      ) {
        setAuthState("needs_email_verification");
        return;
      }

      // Force fresh token
      try {
        const token = await firebaseUser.getIdToken(true);
        console.log("Got token for:", firebaseUser.email, "token length:", token.length);
      } catch (e) {
        console.error("Token error:", e);
        setAuthState("unauthenticated");
        return;
      }

      // Call backend to get role info
      try {
        const { data } = await api.get("/auth/me");
        console.log("auth/me response:", data);
        setRole(data.user.role);
        if (data.requires_role_selection) {
          setAuthState("needs_role_selection");
        } else {
          setAuthState("authenticated");
        }
      } catch (e) {
        console.error("auth/me error:", e);
        setAuthState("unauthenticated");
      }
    });

    return () => unsubscribe();
  }, []);

  const signInWithGoogle = useCallback(async () => {
    setError(null);
    try {
      await signInWithRedirect(auth, new GoogleAuthProvider());
    } catch (e: any) {
      setError(friendlyError(e.code));
    }
  }, []);

  const signInWithMicrosoft = useCallback(async () => {
    setError(null);
    try {
      await signInWithRedirect(auth, new OAuthProvider("microsoft.com"));
    } catch (e: any) {
      setError(friendlyError(e.code));
    }
  }, []);

  const signInWithEmail = useCallback(async (email: string, password: string) => {
    setError(null);
    try {
      await signInWithEmailAndPassword(auth, email, password);
    } catch (e: any) {
      setError(friendlyError(e.code));
    }
  }, []);

  const createAccount = useCallback(async (email: string, password: string) => {
    setError(null);
    try {
      const { user: newUser } = await createUserWithEmailAndPassword(auth, email, password);
      await sendEmailVerification(newUser);
    } catch (e: any) {
      setError(friendlyError(e.code));
    }
  }, []);

  const signOut = useCallback(async () => {
    await firebaseSignOut(auth);
  }, []);

  const resendVerificationEmail = useCallback(async () => {
    if (auth.currentUser) await sendEmailVerification(auth.currentUser);
  }, []);

  const checkEmailVerified = useCallback(async () => {
    if (auth.currentUser) {
      await auth.currentUser.reload();
      if (auth.currentUser.emailVerified) {
        setUser({ ...auth.currentUser });
        setAuthState("needs_role_selection");
      }
    }
  }, []);

  const getToken = useCallback(async () => {
    return auth.currentUser?.getIdToken() ?? null;
  }, []);

  const sendPasswordReset = useCallback(async (email: string): Promise<boolean> => {
    setError(null);
    try {
      const { data } = await api.get(`/auth/check-email?email=${encodeURIComponent(email)}`);
      if (!data.exists) {
        setError("No account found with this email address.");
        return false;
      }
      await sendPasswordResetEmail(auth, email);
      return true;
    } catch (e: any) {
      setError(friendlyError(e.code));
      return false;
    }
  }, []);

  return {
    user, authState, role, error, setError,
    signInWithGoogle, signInWithMicrosoft, signInWithEmail,
    createAccount, signOut, resendVerificationEmail,
    checkEmailVerified, getToken, sendPasswordReset,
  };
}

function friendlyError(code: string): string {
  const map: Record<string, string> = {
    "auth/wrong-password":        "Incorrect password. Please try again.",
    "auth/user-not-found":        "No account found with this email address.",
    "auth/email-already-in-use":  "An account with this email already exists.",
    "auth/weak-password":         "Password must be at least 6 characters.",
    "auth/invalid-email":         "Please enter a valid email address.",
    "auth/too-many-requests":     "Too many attempts. Please try again later.",
    "auth/popup-closed-by-user":  "Sign-in cancelled.",
    "auth/network-request-failed":"Network error. Check your connection.",
  };
  return map[code] ?? "Something went wrong. Please try again.";
}