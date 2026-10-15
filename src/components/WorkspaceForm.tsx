import { useState, type FormEvent } from "react";
import type { WorkspaceInput, WorkspaceStatus } from "../types";
import { ApiError } from "../api/client";

const statuses: WorkspaceStatus[] = ["planning", "in_progress", "completed"];
const statusLabels: Record<WorkspaceStatus, string> = {
  planning: "Planning",
  in_progress: "In progress",
  completed: "Completed",
};

function errorMessage(error: unknown) {
  if (error instanceof ApiError && typeof error.data === "object" && error.data !== null) {
    const fields = Object.values(error.data).flatMap((value) =>
      Array.isArray(value) ? value.map(String) : [],
    );
    if (fields.length) return fields.join(" ");
  }
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

export function WorkspaceForm({
  initial,
  submitLabel,
  onSubmit,
}: {
  initial?: WorkspaceInput;
  submitLabel: string;
  onSubmit: (input: WorkspaceInput) => Promise<void>;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [status, setStatus] = useState<WorkspaceStatus>(initial?.status ?? "planning");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!name.trim()) {
      setError("Give your workspace a name to continue.");
      return;
    }
    setSaving(true);
    try {
      await onSubmit({ name: name.trim(), description: description.trim(), status });
    } catch (submitError) {
      setError(errorMessage(submitError));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="workspace-form" onSubmit={handleSubmit} noValidate>
      <label htmlFor="workspace-name">Workspace name</label>
      <input
        id="workspace-name"
        name="name"
        autoFocus
        required
        maxLength={120}
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="e.g. Cleaner streets, smarter cities"
      />
      <span className="field-hint">A clear name helps keep your work focused.</span>

      <label htmlFor="workspace-description">Description <span className="optional">(optional)</span></label>
      <textarea
        id="workspace-description"
        name="description"
        maxLength={2000}
        rows={5}
        value={description}
        onChange={(event) => setDescription(event.target.value)}
        placeholder="What problem are you exploring?"
      />
      <label htmlFor="workspace-status">Status</label>
      <select
        id="workspace-status"
        value={status}
        onChange={(event) => setStatus(event.target.value as WorkspaceStatus)}
      >
        {statuses.map((item) => <option key={item} value={item}>{statusLabels[item]}</option>)}
      </select>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="form-actions">
        <button className="button button-primary" type="submit" disabled={saving}>
          {saving ? "Saving..." : submitLabel}
        </button>
      </div>
    </form>
  );
}
