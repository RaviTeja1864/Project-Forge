import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { ProjectWorkflow } from "../components/ProjectWorkflow";
import { WorkspaceForm } from "../components/WorkspaceForm";
import type { Workspace, WorkspaceCollaborator, WorkspaceInput } from "../types";

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

export function CreateWorkspacePage() {
  const navigate = useNavigate();
  return (
    <section className="form-page">
      <Link className="back-link" to="/app">← Back to overview</Link>
      <div className="form-page-heading"><span className="eyebrow">A NEW BEGINNING</span><h1>Create a workspace</h1><p>Give your idea a clear starting point. You can shape the details as you go.</p></div>
      <div className="form-panel">
        <WorkspaceForm submitLabel="Create workspace" onSubmit={async (input) => {
          const workspace = await api.post<Workspace>("/workspaces/", input);
          navigate(`/app/workspaces/${workspace.id}`);
        }} />
      </div>
    </section>
  );
}

export function WorkspaceDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [notice, setNotice] = useState("");
  const isOwner = workspace?.access_role !== "collaborator";

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api.get<Workspace>(`/workspaces/${id}/`).then((result) => {
      if (active) setWorkspace(result);
    }).catch((loadError: unknown) => {
      if (!active) return;
      if (loadError instanceof ApiError && loadError.status === 404) setError("This workspace isn't available. It may have been deleted.");
      else setError(loadError instanceof Error ? loadError.message : "This workspace could not be loaded.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id]);

  async function updateWorkspace(input: WorkspaceInput) {
    const updated = await api.patch<Workspace>(`/workspaces/${id}/`, input);
    setWorkspace(updated);
    setEditing(false);
    setNotice("Workspace changes saved.");
  }

  async function deleteWorkspace() {
    if (!window.confirm("Delete this workspace? This permanently removes the workspace and cannot be undone.")) return;
    setDeleting(true);
    setError("");
    try {
      await api.delete<void>(`/workspaces/${id}/`);
      navigate("/app", { replace: true });
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Workspace could not be deleted.");
      setDeleting(false);
    }
  }

  if (loading) return <div className="page-state" role="status"><span className="spinner" /> Loading workspace...</div>;
  if (!workspace) return <div className="page-state"><p className="form-error" role="alert">{error}</p><Link className="button button-secondary" to="/app">Back to overview</Link></div>;

  return (
    <section className="detail-page">
      <Link className="back-link" to="/app">← Back to overview</Link>
      {notice && <p className="success-message" role="status">{notice}</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
      {editing ? (
        <>
          <div className="form-page-heading"><span className="eyebrow">WORKSPACE SETTINGS</span><h1>Edit workspace</h1><p>Update the framing as your idea becomes clearer.</p></div>
          <div className="form-panel"><WorkspaceForm initial={{ name: workspace.name, description: workspace.description, status: workspace.status }} submitLabel="Save changes" onSubmit={updateWorkspace} /><button className="button button-quiet cancel-edit" type="button" onClick={() => setEditing(false)}>Cancel</button></div>
        </>
      ) : (
        <>
          <div className="detail-heading">
            <div><span className="eyebrow">{isOwner ? "PROJECT WORKSPACE" : "SHARED WORKSPACE · READ ONLY"}</span><h1>{workspace.name}</h1><StatusBadge status={workspace.status} /></div>
            {isOwner && <div className="detail-actions"><button className="button button-secondary" onClick={() => { setNotice(""); setEditing(true); }}>Edit workspace</button><button className="button button-danger" disabled={deleting} onClick={() => void deleteWorkspace()}>{deleting ? "Deleting..." : "Delete"}</button></div>}
          </div>
          <div className="detail-content">
            <article className="detail-card"><span className="eyebrow">PROJECT BRIEF</span><h2>What are you exploring?</h2><p className="description-text">{workspace.description || "No description yet. Add a few notes about the problem you want to explore."}</p></article>
            <aside className="detail-card detail-meta"><span className="eyebrow">WORKSPACE DETAILS</span><dl><div><dt>Created</dt><dd>{formatDate(workspace.created_at)}</dd></div><div><dt>Last updated</dt><dd>{formatDate(workspace.updated_at)}</dd></div></dl></aside>
          </div>
          {isOwner && <WorkspaceSharingPanel workspaceId={workspace.id} />}
          {!isOwner && <p className="muted">You can view approved workspace artifacts and specifications. Editing, approvals, generation, and sharing are owner-only.</p>}
          <ProjectWorkflow workspace={workspace} />
        </>
      )}
    </section>
  );
}

function WorkspaceSharingPanel({ workspaceId }: { workspaceId: string }) {
  const [collaborators, setCollaborators] = useState<WorkspaceCollaborator[]>([]);
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api.get<WorkspaceCollaborator[]>(`/workspaces/${workspaceId}/collaborators/`)
      .then((result) => { if (active) setCollaborators(result); })
      .catch((loadError: unknown) => {
        if (active) setError(loadError instanceof Error ? loadError.message : "Collaborators could not be loaded.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [workspaceId, reloadKey]);

  async function grantAccess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.post<WorkspaceCollaborator>(`/workspaces/${workspaceId}/collaborators/`, { email });
      setEmail("");
      setReloadKey((key) => key + 1);
    } catch (grantError) {
      setError(grantError instanceof Error ? grantError.message : "Read-only access could not be granted.");
    } finally {
      setBusy(false);
    }
  }

  async function revokeAccess(grant: WorkspaceCollaborator) {
    if (!window.confirm(`Revoke read-only access for ${grant.email}?`)) return;
    setBusy(true);
    setError("");
    try {
      await api.delete<void>(`/workspaces/${workspaceId}/collaborators/${grant.id}/`);
      setReloadKey((key) => key + 1);
    } catch (revokeError) {
      setError(revokeError instanceof Error ? revokeError.message : "Access could not be revoked.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="detail-card" aria-labelledby="sharing-heading">
      <span className="eyebrow">PRIVATE WORKSPACE</span>
      <h2 id="sharing-heading">Read-only sharing</h2>
      <p>Grant access to an existing ProjectForge account. Collaborators cannot edit, generate, approve, or share workspace content.</p>
      <form className="workspace-sharing-form" onSubmit={(event) => void grantAccess(event)}>
        <label htmlFor="collaborator-email">Account email</label>
        <input id="collaborator-email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
        <button className="button button-primary" type="submit" disabled={busy || !email.trim()}>{busy ? "Updating access..." : "Grant read-only access"}</button>
      </form>
      {loading && <p role="status">Loading collaborators...</p>}
      {error && <div className="error-card" role="alert"><p>{error}</p><button className="button button-secondary" type="button" onClick={() => setReloadKey((key) => key + 1)}>Try again</button></div>}
      {!loading && !error && collaborators.length === 0 && <p className="muted">No collaborators have been added.</p>}
      {!loading && collaborators.length > 0 && (
        <ul className="workspace-collaborator-list">
          {collaborators.map((grant) => (
            <li key={grant.id}>
              <span>{grant.email} · {grant.access_status} · granted {formatDate(grant.granted_at)}</span>
              {grant.access_status === "active" && <button className="button button-danger" type="button" disabled={busy} onClick={() => void revokeAccess(grant)}>Revoke</button>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
