import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoutes, PublicOnlyRoutes } from "./components/Routes";
import { AuthPage } from "./pages/AuthPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LandingPage } from "./pages/LandingPage";
import { ProblemDetailPage, ProblemDiscoveryPage } from "./pages/ProblemDiscoveryPage";
import { CreateWorkspacePage, WorkspaceDetailPage } from "./pages/WorkspacePages";

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route element={<PublicOnlyRoutes />}>
            <Route path="/login" element={<AuthPage mode="login" />} />
            <Route path="/register" element={<AuthPage mode="register" />} />
          </Route>
          <Route path="/app" element={<ProtectedRoutes />}>
            <Route index element={<DashboardPage />} />
            <Route path="workspaces/new" element={<CreateWorkspacePage />} />
            <Route path="workspaces/:id" element={<WorkspaceDetailPage />} />
            <Route path="discover" element={<ProblemDiscoveryPage />} />
            <Route path="problems/:problemId" element={<ProblemDetailPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
