import axios from "axios";
import { auth } from "@/config/firebase";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000",
  timeout: 30000,
});

// Attach Firebase Bearer token to every request
api.interceptors.request.use(async (config) => {
  const user = auth.currentUser;
  console.log("API interceptor — currentUser:", user?.email ?? "null");
  if (user) {
    const token = await user.getIdToken();
    console.log("Token obtained, first 20 chars:", token.substring(0, 20));
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle auth errors globally
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status;
    const detail = err.response?.data?.detail;
    if (status === 401) {
      auth.signOut();
      window.location.href = "/";
    } else if (status === 403) {
      err.message = detail ?? "You don't have permission to do this.";
    }
    return Promise.reject(err);
  }
);

export default api;