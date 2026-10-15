import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { Brand } from "./Brand";

export function AppShell() {
  const { user, signOut } = useAuth();
  const [signOutError, setSignOutError] = useState("");
  async function handleSignOut() {
    try {
      await signOut();
    } catch (error) {
      setSignOutError(error instanceof Error ? error.message : "Sign out failed. Please try again.");
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <Brand />
        <nav className="main-nav" aria-label="Main navigation">
          <NavLink to="/app" end className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            Overview
          </NavLink>
          <NavLink to="/app/workspaces/new" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            New workspace
          </NavLink>
          <NavLink to="/app/discover" className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            Discover problems
          </NavLink>
        </nav>
        <div className="topbar-account">
          <span className="avatar" aria-hidden="true">{user?.email.slice(0, 1).toUpperCase()}</span>
          <span className="account-email">{user?.email}</span>
          <button className="button button-quiet signout-button" type="button" onClick={() => void handleSignOut()}>
            Sign out
          </button>
        </div>
      </header>
      {signOutError && <p className="form-error signout-error" role="alert">{signOutError}</p>}
      <main className="app-main"><Outlet /></main>
      <footer className="app-footer">
        <Brand linked={false} />
        <span>Thoughtful engineering starts with better questions.</span>
      </footer>
    </div>
  );
}
