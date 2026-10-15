import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { AppShell } from "./AppShell";

export function ProtectedRoutes() {
  const { user, loading, error, retry } = useAuth();
  if (loading) return <div className="page-state" role="status">Checking your session...</div>;
  if (error) {
    return (
      <div className="page-state">
        <p className="form-error" role="alert">{error}</p>
        <button className="button button-secondary" onClick={() => void retry()}>Try again</button>
      </div>
    );
  }
  return user ? <AppShell /> : <Navigate to="/login" replace />;
}

export function PublicOnlyRoutes() {
  const { user, loading, error, retry } = useAuth();
  if (loading) return <div className="page-state" role="status">Loading ProjectForge...</div>;
  if (error) {
    return (
      <div className="page-state">
        <p className="form-error" role="alert">{error}</p>
        <button className="button button-secondary" onClick={() => void retry()}>Try again</button>
      </div>
    );
  }
  return user ? <Navigate to="/app" replace /> : <Outlet />;
}
