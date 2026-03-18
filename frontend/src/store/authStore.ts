/**
 * store/authStore.ts
 *
 * Firebase-native Zustand store for authentication state management.
 *
 * Uses onAuthStateChanged to drive a state machine:
 *   loading → unauthenticated / needs_email_verification / authenticated
 *
 * Email/password users are kept signed in after signup but gated behind
 * emailVerified. OAuth users skip verification entirely.
 */

import { create } from "zustand";
import type { User as FirebaseUser, Unsubscribe } from "firebase/auth";
import {
  onAuthStateChanged,
  signInWithPopup,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  sendEmailVerification,
  sendPasswordResetEmail,
  signOut as firebaseSignOut,
  updateProfile,
  GoogleAuthProvider,
  OAuthProvider,
} from "firebase/auth";
import { auth } from "@/config/firebase";
import { authApi } from "@/services/api";
import {
  type AuthState,
  type AuthModalView,
  type UserRole,
  getFirebaseErrorMessage,
} from "@/lib/constants";

// ── Types ────────────────────────────────────────────────────────────────────

export interface BackendUser {
  user_id: string;
  email: string;
  name: string;
  role: UserRole | null;
}

interface AuthStoreState {
  // Core auth state
  user: FirebaseUser | null;
  authState: AuthState;
  role: UserRole | null;
  backendUser: BackendUser | null;

  // Modal state
  authModalOpen: boolean;
  authModalView: AuthModalView;

  // UI state
  isLoading: boolean;
  error: string | null;

  // Pending verification email (for display in verify view)
  pendingVerificationEmail: string | null;
}

interface AuthStoreActions {
  // Lifecycle
  initialize: () => Unsubscribe;
  handleAuthStateChange: (user: FirebaseUser | null) => Promise<void>;

  // Auth methods
  signInWithGoogle: () => Promise<void>;
  signInWithMicrosoft: () => Promise<void>;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  createAccount: (
    email: string,
    password: string,
    displayName: string
  ) => Promise<void>;
  signOut: () => Promise<void>;
  sendPasswordReset: (email: string) => Promise<void>;
  resendVerificationEmail: () => Promise<void>;

  // Modal control
  openAuthModal: (view: AuthModalView) => void;
  closeAuthModal: () => void;
  setAuthModalView: (view: AuthModalView) => void;

  // Utility
  clearError: () => void;
  fetchBackendUser: () => Promise<void>;
}

type AuthStore = AuthStoreState & AuthStoreActions;

// ── Helpers ──────────────────────────────────────────────────────────────────

const googleProvider = new GoogleAuthProvider();
const microsoftProvider = new OAuthProvider("microsoft.com");

/**
 * Determine whether a Firebase user signed in using an OAuth provider.
 *
 * @returns `true` if the user's primary provider is Google or Microsoft, `false` otherwise.
 */
function isOAuthUser(user: FirebaseUser): boolean {
  const providerId = user.providerData[0]?.providerId;
  return providerId === "google.com" || providerId === "microsoft.com";
}

// ── Store ────────────────────────────────────────────────────────────────────

const useAuthStore = create<AuthStore>((set, get) => ({
  // Initial state
  user: null,
  authState: "loading",
  role: null,
  backendUser: null,
  authModalOpen: false,
  authModalView: null,
  isLoading: false,
  error: null,
  pendingVerificationEmail: null,

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  initialize: () => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      get().handleAuthStateChange(user);
    });
    return unsubscribe;
  },

  handleAuthStateChange: async (user) => {
    if (!user) {
      set({
        user: null,
        authState: "unauthenticated",
        role: null,
        backendUser: null,
      });
      return;
    }

    // User exists — determine auth path
    set({ user });

    // CASE: email/password user with unverified email → gate to verify view
    if (!isOAuthUser(user) && !user.emailVerified) {
      set({
        authState: "needs_email_verification",
        pendingVerificationEmail: user.email,
        authModalOpen: true,
        authModalView: "verify_email",
      });
      return;
    }

    // CASE: OAuth user OR verified email/password user → fetch backend profile
    try {
      await get().fetchBackendUser();
    } catch {
      // Backend unreachable or rejected token — sign out
      await firebaseSignOut(auth);
      set({
        authState: "unauthenticated",
        user: null,
        role: null,
        backendUser: null,
        error: "Unable to verify your account. Please try again.",
      });
    }
  },

  // ── Auth Methods ───────────────────────────────────────────────────────────

  signInWithGoogle: async () => {
    set({ isLoading: true, error: null });
    try {
      await signInWithPopup(auth, googleProvider);
      // onAuthStateChanged will handle the rest
    } catch (err: unknown) {
      const code = (err as { code?: string }).code ?? "";
      set({ error: getFirebaseErrorMessage(code) });
    } finally {
      set({ isLoading: false });
    }
  },

  signInWithMicrosoft: async () => {
    set({ isLoading: true, error: null });
    try {
      await signInWithPopup(auth, microsoftProvider);
      // onAuthStateChanged will handle the rest
    } catch (err: unknown) {
      const code = (err as { code?: string }).code ?? "";
      set({ error: getFirebaseErrorMessage(code) });
    } finally {
      set({ isLoading: false });
    }
  },

  signInWithEmail: async (email, password) => {
    set({ isLoading: true, error: null });
    try {
      await signInWithEmailAndPassword(auth, email, password);
      // onAuthStateChanged will handle the rest:
      // - If emailVerified === false → gates to verify_email view
      // - If emailVerified === true → fetches backend user
    } catch (err: unknown) {
      const code = (err as { code?: string }).code ?? "";
      set({ error: getFirebaseErrorMessage(code) });
    } finally {
      set({ isLoading: false });
    }
  },

  createAccount: async (email, password, displayName) => {
    set({ isLoading: true, error: null });
    try {
      const cred = await createUserWithEmailAndPassword(auth, email, password);

      // Set the display name
      await updateProfile(cred.user, { displayName });

      // Send verification email
      await sendEmailVerification(cred.user);

      // User stays signed in. onAuthStateChanged will fire and detect
      // emailVerified === false → authState = "needs_email_verification"
      // The verify_email view will be shown automatically.
      set({
        pendingVerificationEmail: email,
      });
    } catch (err: unknown) {
      const code = (err as { code?: string }).code ?? "";
      set({ error: getFirebaseErrorMessage(code) });
    } finally {
      set({ isLoading: false });
    }
  },

  signOut: async () => {
    try {
      await firebaseSignOut(auth);
    } catch {
      // Ignore sign-out errors
    }
    set({
      user: null,
      authState: "unauthenticated",
      role: null,
      backendUser: null,
      error: null,
      authModalOpen: false,
      authModalView: null,
      pendingVerificationEmail: null,
    });
  },

  sendPasswordReset: async (email) => {
    set({ isLoading: true, error: null });
    try {
      await sendPasswordResetEmail(auth, email);
      // Always show success to prevent email enumeration attacks
      set({ authModalView: "reset_sent" });
    } catch (err: unknown) {
      const code = (err as { code?: string }).code ?? "";
      // Still show success for auth/user-not-found (email enumeration protection)
      if (code === "auth/user-not-found") {
        set({ authModalView: "reset_sent" });
      } else {
        set({ error: getFirebaseErrorMessage(code) });
      }
    } finally {
      set({ isLoading: false });
    }
  },

  resendVerificationEmail: async () => {
    const user = auth.currentUser;
    if (!user) {
      set({
        error: "No active session. Please sign in again to resend the email.",
      });
      return;
    }
    set({ isLoading: true, error: null });
    try {
      await sendEmailVerification(user);
    } catch (err: unknown) {
      const code = (err as { code?: string }).code ?? "";
      set({ error: getFirebaseErrorMessage(code) });
    } finally {
      set({ isLoading: false });
    }
  },

  // ── Modal Control ──────────────────────────────────────────────────────────

  openAuthModal: (view) => {
    set({ authModalOpen: true, authModalView: view, error: null });
  },

  closeAuthModal: () => {
    // Prevent closing when on verify_email view
    if (get().authModalView === "verify_email") return;
    set({ authModalOpen: false, authModalView: null, error: null });
  },

  setAuthModalView: (view) => {
    set({ authModalView: view, error: null });
  },

  // ── Utility ────────────────────────────────────────────────────────────────

  clearError: () => set({ error: null }),

  fetchBackendUser: async () => {
    try {
      const data = await authApi.me();
      const userRole = (data.role as UserRole) || null;
      set({
        backendUser: {
          user_id: data.user_id,
          email: data.email,
          name: data.name,
          role: userRole,
        },
        role: userRole,
        authState: userRole ? "authenticated" : "needs_role_selection",
        authModalOpen: false,
        authModalView: null,
      });
    } catch {
      throw new Error("Backend user fetch failed");
    }
  },
}));

// Listen for forced logout from Axios interceptor
if (typeof window !== "undefined") {
  window.addEventListener("auth:logout", () => {
    useAuthStore.getState().signOut();
  });
}

export default useAuthStore;
