import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Workspace, WorkspaceArtifact } from "../types";

type TaskStatus = "todo" | "in_progress" | "blocked" | "completed";
type TaskPriority = "low" | "medium" | "high";
type EvidenceType =
  | "test_result"
  | "test_description"
  | "repository_path"
  | "api_endpoint"
  | "manual_review"
  | "verification_check";
type EvidenceResult = "passed" | "failed" | "inconclusive" | "absent";
type ReviewBasis = "self_reported" | "manually_reviewed";

type ImplementationTask = {
  id: number;
  source_requirements_artifact_id: string;
  source_requirements_version: number;
  source_requirement_id: string;
  acceptance_criteria_ids: string[];
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  dependency_ids: number[];
  is_outdated: boolean;
  created_at: string;
  updated_at: string;
};

type ImplementationEvidence = {
  id: number;
  requirement_id: string;
  acceptance_criterion_id: string;
  task_id: number | null;
  evidence_type: EvidenceType;
  description: string;
  source_reference: string;
  result: EvidenceResult;
  review_basis: ReviewBasis;
  trust_label: string;
  supersedes_id: number | null;
  author_id: number | null;
  created_at: string;
};

type RequirementVerification = {
  id?: string;
  requirement_id: string;
  requirements_version: number;
  status: "unverified" | "partially_implemented" | "verified" | "missing";
  recorded_status?: string | null;
  is_outdated: boolean;
  rationale: string;
  evidence_ids: string[];
  criterion_results: Array<{
    acceptance_criterion_id: string;
    result: string;
    evidence_ids: string[];
  }>;
  actor_id: number | null;
  created_at: string | null;
};

type EvidenceInput = {
  evidence_type: EvidenceType;
  acceptance_criterion_id: string;
  description: string;
  source_reference: string;
  result: EvidenceResult;
  review_basis: ReviewBasis;
};

type UnmappedRequirement = {
  requirement_id: string | null;
  reason: string;
};

const blankEvidence: EvidenceInput = {
  evidence_type: "verification_check",
  acceptance_criterion_id: "",
  description: "",
  source_reference: "",
  result: "inconclusive",
  review_basis: "self_reported",
};

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "The implementation request failed.";
}

function requirementsForArtifact(artifact: WorkspaceArtifact | undefined, requirementId: string) {
  if (!artifact) return null;
  const content = artifact.content;
  const requirements = [
    ...(Array.isArray(content.functional_requirements) ? content.functional_requirements : []),
    ...(Array.isArray(content.non_functional_requirements) ? content.non_functional_requirements : []),
  ];
  return requirements.find((item) =>
    typeof item === "object" && item !== null && "id" in item && item.id === requirementId,
  ) ?? null;
}

export function ImplementationPlanning({
  workspace,
  artifacts,
}: {
  workspace: Workspace;
  artifacts: WorkspaceArtifact[];
}) {
  const isOwner = workspace.access_role !== "collaborator";
  const approvedRequirements = useMemo(
    () => artifacts
      .filter((artifact) => artifact.kind === "requirements" && artifact.status === "approved")
      .sort((left, right) => right.version_number - left.version_number),
    [artifacts],
  );
  const [selectedRequirementsId, setSelectedRequirementsId] = useState("");
  const [tasks, setTasks] = useState<ImplementationTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [planNotice, setPlanNotice] = useState("");
  const [unmappedRequirements, setUnmappedRequirements] = useState<UnmappedRequirement[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Partial<ImplementationTask>>({});
  const [evidence, setEvidence] = useState<ImplementationEvidence[]>([]);
  const [verification, setVerification] = useState<RequirementVerification | null>(null);
  const [verificationHistory, setVerificationHistory] = useState<RequirementVerification[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailLoadFailed, setDetailLoadFailed] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");
  const [correctingEvidenceId, setCorrectingEvidenceId] = useState<number | null>(null);
  const [evidenceInput, setEvidenceInput] = useState<EvidenceInput>(blankEvidence);

  const selectedTask = tasks.find((task) => task.id === selectedTaskId) ?? null;
  const sourceArtifact = approvedRequirements.find(
    (artifact) => artifact.id === selectedTask?.source_requirements_artifact_id,
  );
  const selectedRequirement = selectedTask
    ? requirementsForArtifact(sourceArtifact, selectedTask.source_requirement_id)
    : null;
  const criteria = sourceArtifact && selectedTask
    ? (Array.isArray(sourceArtifact.content.acceptance_criteria)
      ? sourceArtifact.content.acceptance_criteria
      : []).filter((criterion) =>
        typeof criterion === "object"
        && criterion !== null
        && "id" in criterion
        && selectedTask.acceptance_criteria_ids.includes(String(criterion.id)),
      )
    : [];

  useEffect(() => {
    const latest = approvedRequirements[0];
    if (latest && !selectedRequirementsId) setSelectedRequirementsId(latest.id);
  }, [approvedRequirements, selectedRequirementsId]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api.get<ImplementationTask[]>(`/workspaces/${workspace.id}/implementation/tasks/`)
      .then((result) => {
        if (!Array.isArray(result)) throw new Error("The implementation task response was invalid.");
        if (active) setTasks(result);
      })
      .catch((loadError: unknown) => { if (active) setError(errorMessage(loadError)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [workspace.id, reloadKey]);

  async function generatePlan() {
    if (!selectedRequirementsId) return;
    setBusy("plan");
    setError("");
    setPlanNotice("");
    setUnmappedRequirements([]);
    try {
      const result = await api.post<{
        tasks: ImplementationTask[];
        created_count: number;
        existing_count: number;
        unmapped_requirements: UnmappedRequirement[];
      }>(
        `/workspaces/${workspace.id}/implementation/tasks/generate/`,
        { requirements_artifact_id: selectedRequirementsId },
      );
      if (
        !Array.isArray(result.tasks)
        || !Array.isArray(result.unmapped_requirements)
        || typeof result.created_count !== "number"
        || typeof result.existing_count !== "number"
      ) {
        throw new Error("The generated task plan response was invalid.");
      }
      setTasks((current) => [
        ...current.filter((task) => !result.tasks.some((planned) => planned.id === task.id)),
        ...result.tasks,
      ]);
      setUnmappedRequirements(result.unmapped_requirements);
      setPlanNotice(
        `Plan processed: ${result.created_count} new task(s), ${result.existing_count} existing task(s).`,
      );
      setSelectedTaskId(null);
    } catch (planError) {
      setError(errorMessage(planError));
    } finally {
      setBusy("");
    }
  }

  async function openTask(task: ImplementationTask) {
    setSelectedTaskId(task.id);
    setEvidence([]);
    setVerification(null);
    setVerificationHistory([]);
    setCorrectingEvidenceId(null);
    setEvidenceInput(blankEvidence);
    setDraft({
      title: task.title,
      description: task.description,
      status: task.status,
      priority: task.priority,
      dependency_ids: task.dependency_ids,
    });
    setEvidenceError("");
    setDetailLoadFailed(false);
    setDetailLoading(true);
    const base = `/workspaces/${workspace.id}/requirements/${task.source_requirements_artifact_id}/${task.source_requirement_id}/`;
    try {
      const [records, current, history] = await Promise.all([
        api.get<ImplementationEvidence[]>(`${base}evidence/`),
        api.get<RequirementVerification>(`${base}verification/`),
        api.get<RequirementVerification[]>(`${base}verification/history/`),
      ]);
      setEvidence(records);
      setVerification(current);
      setVerificationHistory(history);
    } catch (detailError) {
      setEvidenceError(errorMessage(detailError));
      setDetailLoadFailed(true);
    } finally {
      setDetailLoading(false);
    }
  }

  async function saveTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedTask) return;
    setBusy(`task-${selectedTask.id}`);
    setEvidenceError("");
    try {
      const updated = await api.patch<ImplementationTask>(
        `/workspaces/${workspace.id}/implementation/tasks/${selectedTask.id}/`,
        draft,
      );
      setTasks((current) => current.map((task) => task.id === updated.id ? updated : task));
      setDraft({
        title: updated.title,
        description: updated.description,
        status: updated.status,
        priority: updated.priority,
        dependency_ids: updated.dependency_ids,
      });
    } catch (saveError) {
      setEvidenceError(errorMessage(saveError));
    } finally {
      setBusy("");
    }
  }

  async function recordEvidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedTask) return;
    setBusy("evidence");
    setEvidenceError("");
    const base = `/workspaces/${workspace.id}/requirements/${selectedTask.source_requirements_artifact_id}/${selectedTask.source_requirement_id}/evidence/`;
    try {
      const saved = await api.post<ImplementationEvidence>(base, {
        ...evidenceInput,
        requirement_id: selectedTask.source_requirement_id,
        task_id: selectedTask.id,
        supersedes_id: correctingEvidenceId,
      });
      setEvidence((current) => [...current, saved]);
      setEvidenceInput(blankEvidence);
      setCorrectingEvidenceId(null);
      const current = await api.get<RequirementVerification>(
        `${base.replace(/evidence\/$/, "")}verification/`,
      );
      setVerification(current);
    } catch (recordError) {
      setEvidenceError(errorMessage(recordError));
    } finally {
      setBusy("");
    }
  }

  async function runVerification() {
    if (!selectedTask) return;
    setBusy("verification");
    setEvidenceError("");
    const base = `/workspaces/${workspace.id}/requirements/${selectedTask.source_requirements_artifact_id}/${selectedTask.source_requirement_id}/`;
    try {
      const result = await api.post<RequirementVerification>(`${base}verification/`, {});
      setVerification(result);
      setVerificationHistory(await api.get<RequirementVerification[]>(`${base}verification/history/`));
    } catch (verificationError) {
      setEvidenceError(errorMessage(verificationError));
    } finally {
      setBusy("");
    }
  }

  const hasRequirements = approvedRequirements.length > 0;
  return (
    <section className="implementation-planning" aria-labelledby={`implementation-heading-${workspace.id}`}>
      <header className="workflow-phase-header">
        <div className="workflow-phase-number">06</div>
        <div>
          <span className="eyebrow">PHASE 5 · TASKS AND EVIDENCE</span>
          <h3 id={`implementation-heading-${workspace.id}`}>Implementation planning and verification</h3>
          <p>Tasks preserve approved requirement IDs. Verification uses recorded evidence only; no commands, repository paths, or URLs are executed or fetched.</p>
        </div>
      </header>

      {isOwner && (
        <div className="implementation-plan-controls">
          <label htmlFor={`requirements-version-${workspace.id}`}>Approved requirements version</label>
          <select
            id={`requirements-version-${workspace.id}`}
            value={selectedRequirementsId}
            onChange={(event) => setSelectedRequirementsId(event.target.value)}
            disabled={!hasRequirements}
          >
            {approvedRequirements.map((artifact) => (
              <option key={artifact.id} value={artifact.id}>
                v{artifact.version_number} · {artifact.id}
              </option>
            ))}
          </select>
          <button
            className="button button-primary"
            type="button"
            disabled={!hasRequirements || !selectedRequirementsId || Boolean(busy)}
            onClick={() => void generatePlan()}
          >
            {busy === "plan" ? "Generating tasks..." : "Generate tasks from requirements"}
          </button>
        </div>
      )}
      {planNotice && <p className="success-message" role="status">{planNotice}</p>}
      {unmappedRequirements.length > 0 && (
        <div className="error-card" role="alert">
          <div>
            <strong>Some requirements could not be mapped</strong>
            <ul>{unmappedRequirements.map((item, index) => (
              <li key={`${item.requirement_id}-${index}`}>
                {item.requirement_id || "Requirement without an ID"}: {item.reason}
              </li>
            ))}</ul>
          </div>
        </div>
      )}
      {!hasRequirements && (
        <p className="muted">Approve a requirements artifact before planning implementation tasks.</p>
      )}
      {loading && <p role="status">Loading implementation tasks...</p>}
      {error && (
        <div className="error-card" role="alert">
          <p>{error}</p>
          <button className="button button-secondary" type="button" onClick={() => setReloadKey((key) => key + 1)}>Try again</button>
        </div>
      )}
      {!loading && !error && tasks.length === 0 && hasRequirements && (
        <p className="muted">{isOwner ? "No implementation tasks yet. Generate a plan from an approved requirements version." : "No implementation tasks have been shared for this workspace yet."}</p>
      )}
      {!loading && !error && tasks.length > 0 && (
        <div className="implementation-task-layout">
          <ul className="implementation-task-list">
            {tasks.map((task) => (
              <li key={task.id}>
                <button
                  className="implementation-task-link"
                  type="button"
                  aria-current={selectedTaskId === task.id ? "true" : undefined}
                  onClick={() => void openTask(task)}
                >
                  <strong>{task.title}</strong>
                  <span>{task.source_requirement_id} · {task.status.replaceAll("_", " ")} · {task.priority}</span>
                  <span>{task.dependency_ids.length} dependencies · criteria {task.acceptance_criteria_ids.join(", ") || "none mapped"}</span>
                  {task.is_outdated && <span className="implementation-outdated">Source requirements have a newer version</span>}
                </button>
              </li>
            ))}
          </ul>
          {selectedTask && (
            <article className="implementation-task-detail" aria-label={`Task ${selectedTask.source_requirement_id}`}>
              <h4>{selectedTask.source_requirement_id}: {selectedRequirement && "statement" in selectedRequirement ? String(selectedRequirement.statement) : selectedTask.title}</h4>
              <p className="muted">Requirements v{selectedTask.source_requirements_version} · Acceptance criteria: {selectedTask.acceptance_criteria_ids.join(", ") || "none mapped"}</p>
              {selectedTask.is_outdated && <p className="implementation-outdated" role="status">This task is tied to an older requirements version. Its source has not been rewritten.</p>}
              {detailLoading && <p role="status">Loading evidence and verification history...</p>}
              {evidenceError && (
                <div className="error-card" role="alert">
                  <p>{evidenceError}</p>
                  {detailLoadFailed && <button className="button button-secondary" type="button" onClick={() => void openTask(selectedTask)}>Retry loading detail</button>}
                </div>
              )}

              {isOwner && (
                <form className="implementation-task-form" onSubmit={(event) => void saveTask(event)}>
                  <label>Task title<input value={String(draft.title ?? "")} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} maxLength={200} required /></label>
                  <label>Description<textarea value={String(draft.description ?? "")} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} maxLength={4000} rows={3} required /></label>
                  <div className="implementation-task-fields">
                    <label>Status<select value={String(draft.status ?? "todo")} onChange={(event) => setDraft((current) => ({ ...current, status: event.target.value as TaskStatus }))}>
                      <option value="todo">To do</option><option value="in_progress">In progress</option><option value="blocked">Blocked</option><option value="completed">Completed</option>
                    </select></label>
                    <label>Priority<select value={String(draft.priority ?? "medium")} onChange={(event) => setDraft((current) => ({ ...current, priority: event.target.value as TaskPriority }))}>
                      <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
                    </select></label>
                  </div>
                  <label>Dependencies<select
                    multiple
                    value={(draft.dependency_ids ?? []).map(String)}
                    onChange={(event) => setDraft((current) => ({
                      ...current,
                      dependency_ids: Array.from(event.target.selectedOptions, (option) => Number(option.value)),
                    }))}
                  >
                    {tasks.filter((task) => task.id !== selectedTask.id).map((task) => (
                      <option key={task.id} value={task.id}>{task.source_requirement_id}: {task.title}</option>
                    ))}
                  </select></label>
                  <button className="button button-secondary" type="submit" disabled={Boolean(busy)}>{busy === `task-${selectedTask.id}` ? "Saving..." : "Save task"}</button>
                </form>
              )}

              <h5>Evidence and requirement verification</h5>
              {selectedTask.acceptance_criteria_ids.length > 0 && (
                <ul className="implementation-criteria-list">
                  {criteria.map((criterion) => {
                    const item = criterion as Record<string, unknown>;
                    return <li key={String(item.id)}><strong>{String(item.id)}</strong> {String(item.criterion)}</li>;
                  })}
                </ul>
              )}
              {verification && (
                <div className={`verification-status verification-${verification.status}`} role="status">
                  <strong>{verification.status.replaceAll("_", " ")}</strong>
                  {!verification.id && <span> · computed preview; no decision is recorded</span>}
                  {verification.is_outdated && <span> · stale; re-verify</span>}
                  <p>{verification.rationale}</p>
                </div>
              )}
              {evidence.length === 0 && !detailLoading && <p className="muted">No evidence has been recorded for this requirement.</p>}
              <ul className="implementation-evidence-list">
                {evidence.map((item) => (
                  <li key={item.id}>
                    <strong>{item.evidence_type.replaceAll("_", " ")} · {item.result} · {item.review_basis.replaceAll("_", " ")}</strong>
                    <p>{item.description}</p>
                    {item.source_reference && <code>{item.source_reference}</code>}
                    <span>{item.trust_label} · {new Date(item.created_at).toLocaleString()}{item.supersedes_id ? ` · Corrects evidence ${item.supersedes_id}` : ""}</span>
                    {isOwner && !evidence.some((entry) => entry.supersedes_id === item.id) && <button className="button button-quiet" type="button" onClick={() => {
                      setCorrectingEvidenceId(item.id);
                      setEvidenceInput({
                        evidence_type: item.evidence_type,
                        acceptance_criterion_id: item.acceptance_criterion_id,
                        description: "",
                        source_reference: item.source_reference,
                        result: "inconclusive",
                        review_basis: "self_reported",
                      });
                    }}>Record correction</button>}
                  </li>
                ))}
              </ul>

              {isOwner && (
                <>
                  <form className="implementation-evidence-form" onSubmit={(event) => void recordEvidence(event)}>
                    <h5>{correctingEvidenceId ? `Correct evidence ${correctingEvidenceId}` : "Record implementation evidence"}</h5>
                    <label>Evidence type<select value={evidenceInput.evidence_type} onChange={(event) => setEvidenceInput((current) => ({ ...current, evidence_type: event.target.value as EvidenceType }))}>
                      <option value="verification_check">Verification check</option><option value="test_result">Test result</option><option value="test_description">Test description</option><option value="repository_path">Repository path</option><option value="api_endpoint">API endpoint</option><option value="manual_review">Manual review</option>
                    </select></label>
                    <label>Acceptance criterion<select value={evidenceInput.acceptance_criterion_id} onChange={(event) => setEvidenceInput((current) => ({ ...current, acceptance_criterion_id: event.target.value }))}>
                      <option value="">Requirement-level evidence</option>
                      {selectedTask.acceptance_criteria_ids.map((criterionId) => <option key={criterionId} value={criterionId}>{criterionId}</option>)}
                    </select></label>
                    <label>Description<textarea value={evidenceInput.description} onChange={(event) => setEvidenceInput((current) => ({ ...current, description: event.target.value }))} maxLength={4000} rows={2} required /></label>
                    <label>Source reference (recorded only; not opened or executed)<input value={evidenceInput.source_reference} onChange={(event) => setEvidenceInput((current) => ({ ...current, source_reference: event.target.value }))} maxLength={1000} /></label>
                    <div className="implementation-task-fields">
                      <label>Result<select value={evidenceInput.result} onChange={(event) => setEvidenceInput((current) => ({ ...current, result: event.target.value as EvidenceResult }))}>
                        <option value="inconclusive">Inconclusive</option><option value="passed">Passed</option><option value="failed">Failed</option><option value="absent">Absent</option>
                      </select></label>
                      <label>Review basis<select value={evidenceInput.review_basis} onChange={(event) => setEvidenceInput((current) => ({ ...current, review_basis: event.target.value as ReviewBasis }))}>
                        <option value="self_reported">Self-reported</option><option value="manually_reviewed">Manually reviewed</option>
                      </select></label>
                    </div>
                    <p className="muted">Self-reported claims do not establish verification. Manually reviewed results are not represented as automated checks.</p>
                    <button className="button button-secondary" type="submit" disabled={Boolean(busy)}>{busy === "evidence" ? "Recording..." : "Save evidence"}</button>
                    {correctingEvidenceId !== null && <button className="button button-quiet" type="button" onClick={() => { setCorrectingEvidenceId(null); setEvidenceInput(blankEvidence); }}>Cancel correction</button>}
                  </form>
                  <button className="button button-primary" type="button" disabled={Boolean(busy)} onClick={() => void runVerification()}>{busy === "verification" ? "Verifying..." : "Record verification decision"}</button>
                </>
              )}
              {verificationHistory.length > 0 && (
                <details className="verification-history">
                  <summary>Verification history ({verificationHistory.length})</summary>
                  <ol>{verificationHistory.map((entry) => (
                    <li key={entry.id ?? `${entry.status}-${entry.created_at}`}>
                      <strong>{entry.recorded_status ?? entry.status}</strong>
                      {entry.is_outdated && " · outdated"}
                      <span>{entry.created_at ? new Date(entry.created_at).toLocaleString() : "No decision recorded"}</span>
                      <p>{entry.rationale}</p>
                    </li>
                  ))}</ol>
                </details>
              )}
            </article>
          )}
        </div>
      )}
    </section>
  );
}
