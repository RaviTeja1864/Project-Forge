import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, refreshCsrfToken } from "../api/client";
import type { User } from "../types";
import { AuthContext } from "./context";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadUser = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setUser(await api.get<User>("/auth/me/"));
    } catch (error) {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        setUser(null);
      } else {
        setError("We couldn't connect to ProjectForge. Check your connection and try again.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUser();
  }, [loadUser]);

  const signIn = async (email: string, password: string) => {
    await refreshCsrfToken();
    const signedIn = await api.post<User>("/auth/login/", { email, password });
    await refreshCsrfToken();
    setUser(signedIn);
  };

  const signUp = async (email: string, password: string) => {
    await refreshCsrfToken();
    const registered = await api.post<User>("/auth/register/", { email, password });
    await refreshCsrfToken();
    setUser(registered);
  };

  const signOut = async () => {
    await api.post<void>("/auth/logout/");
    setUser(null);
  };

  const value = useMemo(
    () => ({ user, loading, error, retry: loadUser, signIn, signUp, signOut }),
    [user, loading, error, loadUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
