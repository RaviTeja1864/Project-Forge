import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { StatusBadge } from "../components/StatusBadge";
import type { Paginated, Workspace } from "../types";

function dateLabel(date: string) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(date));
}

export function DashboardPage() {
  const { user, retry } = useAuth();
  const [data, setData] = useState<Paginated<Workspace> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [page, setPage] = useState(1);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");

    async function load() {
      try {
        const result = await api.get<Paginated<Workspace>>(`/workspaces/?page=${page}`);
        if (current) setData(result);
      } catch (loadError) {
        if (loadError instanceof ApiError && (loadError.status === 401 || loadError.status === 403)) {
          await retry();
          return;
        }
        if (current) setError(loadError instanceof Error ? loadError.message : "Your workspaces could not be loaded.");
      } finally {
        if (current) setLoading(false);
      }
    }
    void load();
    return () => { current = false; };
  }, [page, reloadKey, retry]);

  const workspaces = data?.results ?? [];
  const activeCount = workspaces.filter((workspace) => workspace.status === "in_progress").length;

  return (
    <section className="dashboard-page">
      <div className="dashboard-heading">
        <div><span className="eyebrow">YOUR PROJECT SPACE</span><h1>Good to see you{user?.email ? `, ${user.email.split("@")[0]}` : ""}.</h1><p>Pick up a project or make room for a new idea.</p></div>
        <Link className="button button-primary" to="/app/workspaces/new"><span aria-hidden="true">+</span> New workspace</Link>
      </div>
      {!loading && !error && data && (
        <div className="dashboard-stats" aria-label="Workspace overview">
          <article className="stat-card"><span className="stat-label">ALL WORKSPACES</span><strong>{data.count}</strong><span className="stat-caption">Your projects, in one place</span></article>
          <article className="stat-card"><span className="stat-label">IN PROGRESS</span><strong>{activeCount}</strong><span className="stat-caption">On this page</span></article>
          <article className="stat-card stat-card-note"><span className="stat-label">A GOOD PLACE TO START</span><strong className="stat-phrase">Stay curious.</strong><span className="stat-caption">The best projects start with a question.</span></article>
        </div>
      )}
      <div className="section-heading"><div><span className="eyebrow">YOUR WORK</span><h2>Workspaces available to you</h2></div>{data && data.count > 0 && <span className="muted">Page {page} · {data.count} total</span>}</div>
      {loading && <div className="loading-card" role="status"><span className="spinner" /> Loading your workspaces...</div>}
      {error && <div className="error-card" role="alert"><p>{error}</p><button className="button button-secondary" onClick={() => setReloadKey((key) => key + 1)}>Try again</button></div>}
      {!loading && !error && data && workspaces.length === 0 && (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">P</div>
          <span className="eyebrow">A FRESH PAGE</span>
          <h3>Your first project starts with a question.</h3>
          <p>Create a private workspace to shape an idea into a thoughtful engineering project.</p>
          <Link className="button button-primary" to="/app/workspaces/new">Create your first workspace <span aria-hidden="true">↗</span></Link>
        </div>
      )}
      {!loading && !error && workspaces.length > 0 && (
        <>
          <div className="workspace-grid">
            {workspaces.map((workspace) => (
              <Link className="workspace-card" to={`/app/workspaces/${workspace.id}`} key={workspace.id}>
                <div className="workspace-card-top"><span className="workspace-mark">P</span><StatusBadge status={workspace.status} /></div>
                <h3>{workspace.name}</h3>
                {workspace.access_role === "collaborator" && <span className="eyebrow">SHARED WITH YOU · READ ONLY</span>}
                <p>{workspace.description || "No description yet. Open this workspace to add more detail."}</p>
                <div className="workspace-card-foot"><span>UPDATED {dateLabel(workspace.updated_at).toUpperCase()}</span><span aria-hidden="true">↗</span></div>
              </Link>
            ))}
          </div>
          {(data?.previous || data?.next) && (
            <nav className="pagination" aria-label="Workspace pages">
              <button className="button button-secondary" disabled={!data.previous} onClick={() => setPage((value) => value - 1)}>Previous</button>
              <span>Page {page}</span>
              <button className="button button-secondary" disabled={!data.next} onClick={() => setPage((value) => value + 1)}>Next</button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}
