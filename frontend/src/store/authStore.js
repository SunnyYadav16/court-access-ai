/**
 * store/authStore.js
 *
 * Zustand store for user authentication state.
 *
 * Persists tokens to localStorage automatically.
 * Listens for 'auth:logout' events dispatched by the Axios interceptor.
 */

import { create } from "zustand";
import { authApi } from "@/services/api";

const useAuthStore = create((set, get) => ({
    user: null,
    accessToken: localStorage.getItem("access_token") ?? null,
    refreshToken: localStorage.getItem("refresh_token") ?? null,
    isAuthenticated: !!localStorage.getItem("access_token"),
    isLoading: false,
    error: null,

    // ── Actions ─────────────────────────────────────────────────────────────────

    login: async (username, password) => {
        set({ isLoading: true, error: null });
        try {
            const data = await authApi.login({ username, password });
            localStorage.setItem("access_token", data.access_token);
            localStorage.setItem("refresh_token", data.refresh_token);

            // Fetch user profile after login
            const user = await authApi.me();
            set({
                accessToken: data.access_token,
                refreshToken: data.refresh_token,
                isAuthenticated: true,
                user,
                isLoading: false,
            });
            return { success: true };
        } catch (err) {
            const message = err.response?.data?.detail ?? "Login failed";
            set({ isLoading: false, error: message });
            return { success: false, error: message };
        }
    },

    register: async (formData) => {
        set({ isLoading: true, error: null });
        try {
            const user = await authApi.register(formData);
            set({ isLoading: false });
            return { success: true, user };
        } catch (err) {
            const message = err.response?.data?.detail ?? "Registration failed";
            set({ isLoading: false, error: message });
            return { success: false, error: message };
        }
    },

    logout: async () => {
        const { refreshToken } = get();
        try {
            if (refreshToken) await authApi.logout(refreshToken);
        } catch (_) {
            // Ignore logout API errors
        }
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        set({ user: null, accessToken: null, refreshToken: null, isAuthenticated: false, error: null });
    },

    fetchMe: async () => {
        try {
            const user = await authApi.me();
            set({ user, isAuthenticated: true });
        } catch (_) {
            get().logout();
        }
    },

    clearError: () => set({ error: null }),
}));

// Listen for forced logout from Axios interceptor
window.addEventListener("auth:logout", () => {
    useAuthStore.getState().logout();
});

export default useAuthStore;
