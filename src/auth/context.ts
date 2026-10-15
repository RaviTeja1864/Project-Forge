import { createContext } from "react";
import type { User } from "../types";

export type AuthContextValue = {
  user: User | null;
  loading: boolean;
  error: string | null;
  retry: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);
