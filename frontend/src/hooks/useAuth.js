/**
 * hooks/useAuth.js
 *
 * Convenience hook consuming the Zustand authStore.
 * Also handles hydrating the user profile on initial mount.
 *
 * Usage:
 *   const { user, isAuthenticated, login, logout } = useAuth();
 */

import { useEffect } from "react";
import useAuthStore from "@/store/authStore";

export function useAuth() {
    const {
        user,
        isAuthenticated,
        isLoading,
        error,
        login,
        register,
        logout,
        fetchMe,
        clearError,
    } = useAuthStore();

    // Hydrate user profile if we have a token but no user yet
    useEffect(() => {
        if (isAuthenticated && !user) {
            fetchMe();
        }
    }, [isAuthenticated, user, fetchMe]);

    return {
        user,
        isAuthenticated,
        isLoading,
        error,
        login,
        register,
        logout,
        clearError,
        /** True if user has one of the given roles  */
        hasRole: (...roles) => roles.includes(user?.role),
    };
}

export default useAuth;
