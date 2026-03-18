/**
 * hooks/useAuth.ts
 *
 * Convenience hook wrapping the Zustand auth store.
 * Sets up the onAuthStateChanged listener on first mount.
 *
 * Usage:
 *   const { user, authState, signInWithGoogle, openAuthModal } = useAuth();
 */

import { useEffect, useRef } from "react";
import useAuthStore from "@/store/authStore";
import type { UserRole, AuthModalView } from "@/lib/constants";
import type { Unsubscribe } from "firebase/auth";

export function useAuth() {
  const store = useAuthStore();
  const unsubRef = useRef<Unsubscribe | null>(null);

  // Initialize onAuthStateChanged listener on first mount
  useEffect(() => {
    if (!unsubRef.current) {
      unsubRef.current = store.initialize();
    }
    return () => {
      if (unsubRef.current) {
        unsubRef.current();
        unsubRef.current = null;
      }
    };
    // Only run on mount/unmount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    // State
    user: store.user,
    authState: store.authState,
    role: store.role,
    backendUser: store.backendUser,
    isLoading: store.isLoading,
    error: store.error,
    authModalOpen: store.authModalOpen,
    authModalView: store.authModalView,
    pendingVerificationEmail: store.pendingVerificationEmail,

    // Auth actions
    signInWithGoogle: store.signInWithGoogle,
    signInWithMicrosoft: store.signInWithMicrosoft,
    signInWithEmail: store.signInWithEmail,
    createAccount: store.createAccount,
    signOut: store.signOut,
    sendPasswordReset: store.sendPasswordReset,
    resendVerificationEmail: store.resendVerificationEmail,

    // Modal actions
    openAuthModal: store.openAuthModal,
    closeAuthModal: store.closeAuthModal,
    setAuthModalView: store.setAuthModalView,

    // Utilities
    clearError: store.clearError,

    /** Check if user has one of the given roles */
    hasRole: (...roles: UserRole[]) =>
      store.role !== null && roles.includes(store.role),

    /** Opens auth modal if not authenticated, otherwise runs callback */
    requireAuth: (callback?: () => void) => {
      if (store.authState === "authenticated") {
        callback?.();
      } else {
        store.openAuthModal("login" as AuthModalView);
      }
    },
  };
}

export default useAuth;
