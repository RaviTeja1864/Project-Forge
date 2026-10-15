import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type {
  OllamaStatus,
  Paginated,
  ProblemStatement,
  Workspace,
  WorkspaceArtifact,
  WorkspaceArtifactKind,
  WorkspaceArtifactVersionComparison,
  WorkspaceSpecificationInputs,
} from "../types";
import { ImplementationPlanning } from "./ImplementationPlanning";

const phases: Array<{ kind: WorkspaceArtifactKind; title: string; description: string }> = [
  { kind: "research", title: "Evidence-grounded research", description: "Synthesize the selected catalogue problem and its linked source records." },
  { kind: "requirements", title: "Project requirements", description: "Create editable objectives, users, scope, requirements, and acceptance criteria." },
  { kind: "technology", title: "Technology comparison", description: "Compare alternatives you choose using qualitative project criteria." },
  { kind: "design", title: "System and database design", description: "Draft an architecture, API, data model, and Mermaid diagrams as a proposal." },
];

function sourceLinkIsSafe(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password;
  } catch {
    return false;
  }
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "The project workflow request failed.";
}

function asObject(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function ProjectWorkflow({ workspace }: { workspace: Workspace }) {
  const collaboratorReadOnly = workspace.access_role === "collaborator";
  const [artifacts, setArtifacts] = useState<WorkspaceArtifact[]>([]);
  const [problems, setProblems] = useState<ProblemStatement[]>([]);
  const [selectedProblemId, setSelectedProblemId] = useState("");
  const [selectedArtifacts, setSelectedArtifacts] = useState<Partial<Record<WorkspaceArtifactKind, string>>>({});
  const [ollama, setOllama] = useState<OllamaStatus | null>(null);
  const [optionsText, setOptionsText] = useState("");
  const [editorTexts, setEditorTexts] = useState<Record<string, string>>({});
  const [versionHistory, setVersionHistory] = useState<WorkspaceArtifact[]>([]);
  const [historyFor, setHistoryFor] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [compareLeft, setCompareLeft] = useState("");
  const [compareRight, setCompareRight] = useState("");
  const [comparison, setComparison] = useState<WorkspaceArtifactVersionComparison | null>(null);
  const [comparisonError, setComparisonError] = useState("");
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [specificationInputs, setSpecificationInputs] = useState<WorkspaceSpecificationInputs | null>(null);
  const [specificationInputsLoading, setSpecificationInputsLoading] = useState(false);
  const [specificationInputsError, setSpecificationInputsError] = useState("");
  const [specificationBusy, setSpecificationBusy] = useState(false);
  const [specificationError, setSpecificationError] = useState("");
  const [exportBusy, setExportBusy] = useState("");
  const [exportError, setExportError] = useState("");
  const [exportFormat, setExportFormat] = useState<"md" | "pdf">("md");
  const [loading, setLoading] = useState(true);
  const [loadingError, setLoadingError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  const reload = useCallback(async () => {
    setLoading(true);
    setLoadingError("");
    try {
      const [artifactResult, problemResult, statusResult] = await Promise.all([
        api.get<WorkspaceArtifact[]>(`/workspaces/${workspace.id}/artifacts/`),
        api.get<Paginated<ProblemStatement>>("/problems/?page_size=50"),
        api.get<OllamaStatus>("/workspaces/llm/status/"),
      ]);
      setArtifacts(Array.isArray(artifactResult) ? artifactResult : []);
      setProblems(Array.isArray(problemResult?.results) ? problemResult.results : []);
      setOllama(statusResult);
    } catch (error) {
      setLoadingError(errorText(error));
    } finally {
      setLoading(false);
    }
  }, [workspace.id]);

  useEffect(() => {
    void reload();
  }, [reload, reloadKey]);

  const artifactFor = useCallback((kind: WorkspaceArtifactKind) => {
    const selected = artifacts.find((item) => item.id === selectedArtifacts[kind]);
    if (selected?.kind === kind) return selected;
    return artifacts
      .filter((item) => item.kind === kind)
      .sort((left, right) => right.version_number - left.version_number)[0] ?? null;
  }, [artifacts, selectedArtifacts]);

  const approved = useMemo(() => ({
    research: artifacts.some((artifact) => artifact.kind === "research" && artifact.status === "approved"),
    requirements: artifacts.some((artifact) => artifact.kind === "requirements" && artifact.status === "approved"),
    technology: artifacts.some((artifact) => artifact.kind === "technology" && artifact.status === "approved"),
  }), [artifacts]);
  const specificationVersions = artifacts
    .filter((artifact) => artifact.kind === "specification")
    .sort((left, right) => right.version_number - left.version_number);
  const specification = artifactFor("specification");

  function updateArtifact(updated: WorkspaceArtifact) {
    setArtifacts((current) => [
      updated,
      ...current.filter((artifact) => artifact.id !== updated.id),
    ]);
    if (historyFor === updated.lineage_root_id) {
      setVersionHistory((current) => [
        ...current.filter((version) => version.id !== updated.id),
        updated,
      ].sort((left, right) => left.version_number - right.version_number));
    }
    setSelectedArtifacts((current) => ({ ...current, [updated.kind]: updated.id }));
  }

  async function generate(kind: WorkspaceArtifactKind) {
    setBusy(kind);
    setActionError("");
    try {
      let result: WorkspaceArtifact;
      if (kind === "research") {
        if (!selectedProblemId) throw new Error("Choose a catalogue problem before generating research.");
        result = await api.post<WorkspaceArtifact>(
          `/workspaces/${workspace.id}/generate/research/`,
          { problem_id: selectedProblemId },
        );
      } else if (kind === "requirements") {
        result = await api.post<WorkspaceArtifact>(
          `/workspaces/${workspace.id}/generate/requirements/`,
          {},
        );
      } else if (kind === "technology") {
        const options = optionsText.split(/[\n,]/).map((option) => option.trim()).filter(Boolean);
        if (options.length < 2) throw new Error("Enter at least two technology options to compare.");
        result = await api.post<WorkspaceArtifact>(
          `/workspaces/${workspace.id}/generate/technology/`,
          { options },
        );
      } else {
        result = await api.post<WorkspaceArtifact>(
          `/workspaces/${workspace.id}/generate/design/`,
          {},
        );
      }
      updateArtifact(result);
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setBusy("");
    }
  }

  async function saveDraft(artifact: WorkspaceArtifact) {
    setBusy(`save-${artifact.id}`);
    setActionError("");
    try {
      const content: unknown = JSON.parse(
        editorTexts[artifact.id] ?? JSON.stringify(artifact.content, null, 2),
      );
      const updated = await api.patch<WorkspaceArtifact>(
        `/workspaces/${workspace.id}/artifacts/${artifact.id}/`,
        { content },
      );
      updateArtifact(updated);
    } catch (error) {
      setActionError(error instanceof SyntaxError ? "The draft must be valid JSON before it can be saved." : errorText(error));
    } finally {
      setBusy("");
    }
  }

  async function approve(artifact: WorkspaceArtifact) {
    setBusy(`approve-${artifact.id}`);
    setActionError("");
    try {
      const updated = await api.patch<WorkspaceArtifact>(
        `/workspaces/${workspace.id}/artifacts/${artifact.id}/`,
        { status: "approved" },
      );
      updateArtifact(updated);
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setBusy("");
    }
  }

  async function revise(artifact: WorkspaceArtifact) {
    setBusy(`revise-${artifact.id}`);
    setActionError("");
    try {
      const revision = await api.post<WorkspaceArtifact>(
        `/workspaces/${workspace.id}/artifacts/${artifact.id}/revise/`,
        {},
      );
      updateArtifact(revision);
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setBusy("");
    }
  }

  async function loadVersionHistory(artifact: WorkspaceArtifact) {
    setHistoryLoading(true);
    setHistoryError("");
    setHistoryFor(artifact.lineage_root_id);
    setVersionHistory([]);
    setComparison(null);
    setComparisonError("");
    try {
      const history = await api.get<WorkspaceArtifact[]>(
        `/workspaces/${workspace.id}/artifacts/${artifact.id}/versions/`,
      );
      setVersionHistory(history);
      setCompareLeft(history[0]?.id ?? "");
      setCompareRight(history.at(-1)?.id ?? "");
    } catch (error) {
      setHistoryError(errorText(error));
    } finally {
      setHistoryLoading(false);
    }
  }

  async function compareArtifactVersions(artifact: WorkspaceArtifact) {
    setComparisonLoading(true);
    setComparisonError("");
    setComparison(null);
    try {
      const query = new URLSearchParams({
        left_version: compareLeft,
        right_version: compareRight,
      });
      const result = await api.get<WorkspaceArtifactVersionComparison>(
        `/workspaces/${workspace.id}/artifacts/${artifact.id}/versions/compare/?${query}`,
      );
      setComparison(result);
    } catch (error) {
      setComparisonError(errorText(error));
    } finally {
      setComparisonLoading(false);
    }
  }

  async function generateSpecification() {
    setSpecificationBusy(true);
    setSpecificationError("");
    setSpecificationInputs(null);
    try {
      const specification = await api.post<WorkspaceArtifact>(
        `/workspaces/${workspace.id}/specifications/`,
        {},
      );
      updateArtifact(specification);
    } catch (error) {
      setSpecificationError(errorText(error));
    } finally {
      setSpecificationBusy(false);
    }
  }

  async function loadSpecificationInputs(specification: WorkspaceArtifact) {
    setSpecificationInputsLoading(true);
    setSpecificationInputsError("");
    try {
      const result = await api.get<WorkspaceSpecificationInputs>(
        `/workspaces/${workspace.id}/specifications/${specification.id}/inputs/`,
      );
      setSpecificationInputs(result);
    } catch (error) {
      setSpecificationInputsError(errorText(error));
    } finally {
      setSpecificationInputsLoading(false);
    }
  }

  async function downloadSpecification(specification: WorkspaceArtifact, format: "md" | "pdf") {
    const actionKey = `${specification.id}-${format}`;
    setExportFormat(format);
    setExportBusy(actionKey);
    setExportError("");
    try {
      const { blob, filename } = await api.download(
        `/workspaces/${workspace.id}/specifications/${specification.id}/export.${format}`,
      );
      const objectUrl = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement("a");
        anchor.href = objectUrl;
        anchor.download = filename;
        anchor.click();
      } finally {
        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      }
    } catch (error) {
      setExportError(errorText(error));
    } finally {
      setExportBusy("");
    }
  }

  if (loading) {
    return <section className="project-workflow" aria-labelledby="workflow-heading"><div className="section-heading"><h2 id="workflow-heading">Project development</h2></div><div className="loading-card" role="status">Loading project tools...</div></section>;
  }

  return (
    <section className="project-workflow" aria-labelledby="workflow-heading">
      <div className="section-heading workflow-heading">
        <div><span className="eyebrow">PHASE 3 · REVIEW BEFORE APPROVAL</span><h2 id="workflow-heading">Project development</h2></div>
        <button className="button button-secondary" type="button" onClick={() => setReloadKey((value) => value + 1)}>Refresh</button>
      </div>
      {loadingError && (
        <div className="error-card" role="alert"><p>{loadingError}</p><button className="button button-secondary" onClick={() => setReloadKey((value) => value + 1)}>Try again</button></div>
      )}
      {!loadingError && (
        <>
          {!collaboratorReadOnly && <div className={`model-status ${ollama?.available ? "model-online" : "model-offline"}`} role="status">
            <span className="model-status-dot" aria-hidden="true" />
            Local model: {ollama?.model ?? "status unknown"} · {ollama?.available ? "available" : ollama?.state?.replaceAll("_", " ") ?? "checking"}
            {!ollama?.available && <span>Start the configured local Ollama service and ensure its model is installed.</span>}
          </div>}
          {actionError && <div className="error-card workflow-error" role="alert"><p>{actionError}</p><button className="button button-quiet" onClick={() => setActionError("")}>Dismiss</button></div>}
          <div className="workflow-phase-list">
            {phases.map((phase, index) => {
              const artifact = artifactFor(phase.kind);
              const versions = artifacts
                .filter((item) => item.kind === phase.kind)
                .sort((left, right) => right.version_number - left.version_number);
              const lineageVersions = artifact
                ? artifacts
                  .filter((item) => item.lineage_root_id === artifact.lineage_root_id)
                  .sort((left, right) => left.version_number - right.version_number)
                : [];
              const latestVersionNumber = lineageVersions.at(-1)?.version_number ?? artifact?.version_number;
              const isHistorical = Boolean(
                artifact && latestVersionNumber && artifact.version_number < latestVersionNumber,
              );
              const currentApprovedVersion = lineageVersions
                .filter((item) => item.status === "approved")
                .at(-1);
              const historyIsOpen = Boolean(
                artifact && historyFor === artifact.lineage_root_id,
              );
              const readOnly = collaboratorReadOnly || artifact?.status === "approved" || isHistorical;
              const blocked = phase.kind === "requirements"
                ? !approved.research
                : phase.kind === "technology"
                  ? !approved.requirements
                  : phase.kind === "design"
                    ? !approved.technology
                    : false;
              const parsedContent = asObject(artifact?.content);
              return (
                <article className="workflow-phase" key={phase.kind}>
                  <header className="workflow-phase-header">
                    <div className="workflow-phase-number">0{index + 1}</div>
                    <div><span className="eyebrow">{phase.kind.toUpperCase()}</span><h3>{phase.title}</h3><p>{phase.description}</p></div>
                    {artifact && <span className={`artifact-status artifact-${artifact.status}`}>{artifact.status}</span>}
                  </header>

                  {!collaboratorReadOnly && phase.kind === "research" && (
                    <div className="workflow-input">
                      <label htmlFor={`problem-select-${workspace.id}`}>Catalogue problem</label>
                      <select
                        id={`problem-select-${workspace.id}`}
                        value={selectedProblemId}
                        onChange={(event) => setSelectedProblemId(event.target.value)}
                      >
                        <option value="">Select a sourced problem</option>
                        {problems.map((problem) => <option key={problem.id} value={problem.id}>{problem.title}</option>)}
                      </select>
                      {problems.length === 0 && <p className="muted">No published catalogue problems are available. <Link to="/app/discover">Explore the problem catalogue</Link>.</p>}
                    </div>
                  )}
                  {!collaboratorReadOnly && phase.kind === "technology" && (
                    <div className="workflow-input">
                      <label htmlFor={`technology-options-${workspace.id}`}>Technology alternatives (comma or newline separated)</label>
                      <textarea
                        id={`technology-options-${workspace.id}`}
                        value={optionsText}
                        onChange={(event) => setOptionsText(event.target.value)}
                        rows={2}
                        placeholder="Enter at least two options to compare"
                      />
                    </div>
                  )}

                  {!collaboratorReadOnly && <div className="workflow-actions">
                    <button
                      className="button button-primary"
                      type="button"
                      disabled={Boolean(busy) || blocked || (phase.kind === "research" && !selectedProblemId)}
                      onClick={() => void generate(phase.kind)}
                    >
                      {busy === phase.kind ? "Generating..." : artifact ? "Generate new draft" : "Generate draft"}
                    </button>
                    {blocked && <span className="muted">Approve the preceding phase before generating this one.</span>}
                  </div>}

                  {versions.length > 1 && (
                    <label className="workflow-version">
                      Artifact version or lineage
                      <select
                        value={artifact?.id ?? ""}
                        onChange={(event) => setSelectedArtifacts((current) => ({ ...current, [phase.kind]: event.target.value }))}
                      >
                        {versions.map((version) => (
                          <option key={version.id} value={version.id}>
                            v{version.version_number} · {version.status} · {new Date(version.created_at).toLocaleString()}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}

                  {artifact && (
                    <div className="artifact-review">
                      <div className="artifact-review-heading">
                        <h4>
                          Version {artifact.version_number} · {artifact.status}
                          {artifact.id === currentApprovedVersion?.id ? " · Current approved version" : ""}
                          {isHistorical ? " · Historical, read-only" : ""}
                        </h4>
                        {artifact.source_problem_id && <Link to={`/app/problems/${artifact.source_problem_id}`}>View selected problem and evidence</Link>}
                      </div>
                      <p className="artifact-version-meta">
                        Created {new Date(artifact.created_at).toLocaleString()}
                        {artifact.revision_of_id
                          ? <> · Revision of <code>{artifact.revision_of_id}</code></>
                          : " · Initial version"}
                        {artifact.author_id !== null && <> · Author ID {artifact.author_id}</>}
                      </p>
                      <div className="workflow-actions">
                        <button
                          className="button button-secondary"
                          type="button"
                          disabled={historyLoading}
                          onClick={() => void loadVersionHistory(artifact)}
                        >
                          {historyLoading && historyFor === artifact.lineage_root_id ? "Loading history..." : "View version history"}
                        </button>
                      </div>
                      {historyIsOpen && (
                        <div className="artifact-version-history">
                          <h5>Version history</h5>
                          {historyError && <p className="error-card" role="alert">{historyError}</p>}
                          {historyLoading && <p role="status">Loading version history...</p>}
                          {!historyLoading && !historyError && versionHistory.length === 0 && (
                            <p className="muted">No versions are available for this artifact.</p>
                          )}
                          {!historyLoading && !historyError && versionHistory.length > 0 && (
                            <>
                              <ol>
                                {versionHistory.map((version) => (
                                  <li key={version.id}>
                                    <button
                                      type="button"
                                      className="artifact-history-open"
                                      aria-current={artifact.id === version.id ? "page" : undefined}
                                      onClick={() => setSelectedArtifacts((current) => ({ ...current, [phase.kind]: version.id }))}
                                    >
                                      v{version.version_number} · {version.status}
                                      {version.id === currentApprovedVersion?.id ? " · Current approved" : ""}
                                      {version.revision_of_id ? ` · revises v${versionHistory.find((item) => item.id === version.revision_of_id)?.version_number ?? "earlier"}` : " · initial"}
                                      {" · "}{new Date(version.created_at).toLocaleString()}
                                    </button>
                                  </li>
                                ))}
                              </ol>
                              {versionHistory.length > 1 && (
                                <div className="artifact-version-compare">
                                  <label>
                                    Compare version
                                    <select value={compareLeft} onChange={(event) => setCompareLeft(event.target.value)}>
                                      {versionHistory.map((version) => <option key={version.id} value={version.id}>v{version.version_number}</option>)}
                                    </select>
                                  </label>
                                  <label>
                                    With version
                                    <select value={compareRight} onChange={(event) => setCompareRight(event.target.value)}>
                                      {versionHistory.map((version) => <option key={version.id} value={version.id}>v{version.version_number}</option>)}
                                    </select>
                                  </label>
                                  <button
                                    className="button button-secondary"
                                    type="button"
                                    disabled={comparisonLoading || !compareLeft || !compareRight || compareLeft === compareRight}
                                    onClick={() => void compareArtifactVersions(artifact)}
                                  >
                                    {comparisonLoading ? "Comparing..." : "Compare versions"}
                                  </button>
                                  {comparisonError && <p className="error-card" role="alert">{comparisonError}</p>}
                                  {comparison && (
                                    <div className="artifact-comparison" aria-live="polite">
                                      <strong>Changes from v{comparison.left_version.version_number} to v{comparison.right_version.version_number}</strong>
                                      {comparison.changes.length === 0
                                        ? <p>No content or evidence changes.</p>
                                        : <ul>{comparison.changes.map((change) => (
                                          <li key={change.path}>
                                            <code>{change.path}</code>
                                            <pre>{JSON.stringify(change.before)} → {JSON.stringify(change.after)}</pre>
                                          </li>
                                        ))}</ul>}
                                    </div>
                                  )}
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      )}
                      {artifact.kind === "research" && (
                        <>
                          <h5>Source records supplied to research</h5>
                          {artifact.source_snapshot.length === 0
                            ? <p className="muted">No catalogue evidence was available; this draft reports the resulting gap.</p>
                            : <ul className="workflow-source-list">
                              {artifact.source_snapshot.map((source) => (
                                <li key={source.id}>
                                  {sourceLinkIsSafe(source.source_url)
                                    ? <a href={source.source_url} target="_blank" rel="noopener noreferrer">{source.source_title}</a>
                                    : source.source_title}
                                  <span>{source.publisher || "Publisher not provided"} · Published {source.publication_date ?? "date unknown"}</span>
                                  <code>{source.id}</code>
                                </li>
                              ))}
                            </ul>}
                          {Array.isArray(parsedContent.key_claims) && parsedContent.key_claims.map((value, claimIndex) => {
                            const claim = asObject(value);
                            return <p className="workflow-claim" key={`${claimIndex}-${String(claim.claim)}`}><strong>{String(claim.support_status ?? "Unclassified")}:</strong> {String(claim.claim ?? "")} <span>Sources: {Array.isArray(claim.evidence_source_ids) && claim.evidence_source_ids.length ? claim.evidence_source_ids.join(", ") : "None cited"}</span></p>;
                          })}
                        </>
                      )}
                      {!readOnly ? (
                        <>
                          <label className="artifact-editor-label" htmlFor={`artifact-editor-${artifact.id}`}>Editable structured JSON</label>
                          <textarea
                            id={`artifact-editor-${artifact.id}`}
                            className="artifact-editor"
                            value={editorTexts[artifact.id] ?? JSON.stringify(artifact.content, null, 2)}
                            onChange={(event) => {
                              setSelectedArtifacts((current) => ({ ...current, [phase.kind]: artifact.id }));
                              setEditorTexts((current) => ({ ...current, [artifact.id]: event.target.value }));
                            }}
                            rows={12}
                            spellCheck={false}
                          />
                          <div className="workflow-actions">
                            <button className="button button-secondary" disabled={Boolean(busy)} onClick={() => void saveDraft(artifact)}>{busy === `save-${artifact.id}` ? "Saving..." : "Save edits"}</button>
                            <button className="button button-primary" disabled={Boolean(busy)} onClick={() => void approve(artifact)}>{busy === `approve-${artifact.id}` ? "Approving..." : "Approve this artifact"}</button>
                          </div>
                        </>
                      ) : (
                        <div className="approved-artifact-summary">
                          <p>{collaboratorReadOnly ? "Shared artifact content is read-only." : isHistorical ? "Historical versions are read-only and preserved." : "This approved artifact is preserved. Create a revision to make changes."}</p>
                          {!collaboratorReadOnly && <button className="button button-secondary" disabled={Boolean(busy)} onClick={() => void revise(artifact)}>{busy === `revise-${artifact.id}` ? "Creating revision..." : `Create revision from v${artifact.version_number}`}</button>}
                          <details><summary>View approved structured content</summary><pre>{JSON.stringify(artifact.content, null, 2)}</pre></details>
                        </div>
                      )}
                      {artifact.kind !== "research" && artifact.source_snapshot.length > 0 && (
                        <details className="artifact-citations"><summary>Evidence available to this artifact ({artifact.source_snapshot.length})</summary>
                          <ul className="workflow-source-list">
                            {artifact.source_snapshot.map((source) => (
                              <li key={source.id}>{source.source_title}<span>{source.publisher || "Publisher not provided"} · {source.publication_date ?? "Date unknown"}</span><code>{source.id}</code></li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
          <ImplementationPlanning workspace={workspace} artifacts={artifacts} />
          <section className="unified-specification" aria-labelledby="specification-heading">
            <header className="workflow-phase-header">
              <div className="workflow-phase-number">05</div>
              <div>
                <span className="eyebrow">COMPOSED SNAPSHOT</span>
                <h3 id="specification-heading">Unified engineering specification</h3>
                <p>Compose the exact approved research, requirements, technology, and design versions without an additional model rewrite.</p>
              </div>
              {specification && (
                <span className={`artifact-status artifact-${specification.status}`}>
                  {specification.status}
                </span>
              )}
            </header>
            {!collaboratorReadOnly && <div className="workflow-actions">
              <button
                className="button button-primary"
                type="button"
                disabled={specificationBusy || Boolean(busy)}
                onClick={() => void generateSpecification()}
              >
                {specificationBusy ? "Composing specification..." : "Generate specification snapshot"}
              </button>
              {specification?.is_outdated && (
                <span className="specification-outdated" role="status">
                  Inputs have newer approved versions. This snapshot is unchanged; generate a new one after reviewing them.
                </span>
              )}
            </div>}
            {specificationError && (
              <div className="error-card" role="alert">
                <p>{specificationError}</p>
                <button className="button button-secondary" onClick={() => void generateSpecification()}>
                  Try again
                </button>
              </div>
            )}
            {specificationVersions.length === 0 && !specificationBusy && (
              <p className="muted">No specification snapshots yet. Approve all four input artifacts, then generate one.</p>
            )}
            {specificationVersions.length > 1 && (
              <label className="workflow-version">
                Specification snapshot history
                <select
                  value={specification?.id ?? ""}
                  onChange={(event) => setSelectedArtifacts((current) => ({
                    ...current,
                    specification: event.target.value,
                  }))}
                >
                  {specificationVersions.map((version) => (
                    <option key={version.id} value={version.id}>
                      v{version.version_number} · {version.status}
                      {version.is_outdated ? " · Outdated" : " · Current inputs"}
                      {" · "}{new Date(version.created_at).toLocaleString()}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {specification && (
              <div className="artifact-review specification-review">
                <div className="artifact-review-heading">
                  <h4>
                    Snapshot v{specification.version_number} · {specification.status}
                    {specification.is_outdated ? " · Potentially outdated" : ""}
                  </h4>
                  <span>Generated {new Date(specification.content.generated_at as string).toLocaleString()}</span>
                </div>
                <p className="artifact-version-meta">
                  Specification snapshots are immutable. Regeneration creates a new version.
                  {specification.revision_of_id ? <> · Revision of <code>{specification.revision_of_id}</code></> : " · Initial snapshot"}
                </p>
                <div className="workflow-actions specification-export-actions">
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={Boolean(exportBusy)}
                    onClick={() => void downloadSpecification(specification, "md")}
                  >
                    {exportBusy === `${specification.id}-md` ? "Preparing Markdown..." : "Download Markdown"}
                  </button>
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={Boolean(exportBusy)}
                    onClick={() => void downloadSpecification(specification, "pdf")}
                  >
                    {exportBusy === `${specification.id}-pdf` ? "Preparing PDF..." : "Download PDF"}
                  </button>
                </div>
                {exportError && (
                  <div className="error-card" role="alert">
                    <p>{exportError}</p>
                    <button
                      className="button button-secondary"
                      onClick={() => void downloadSpecification(
                        specification,
                        exportFormat,
                      )}
                    >
                      Try download again
                    </button>
                  </div>
                )}
                {!collaboratorReadOnly && specification.status === "draft" && (
                  <div className="workflow-actions">
                    <button
                      className="button button-primary"
                      type="button"
                      disabled={Boolean(busy)}
                      onClick={() => void approve(specification)}
                    >
                      {busy === `approve-${specification.id}` ? "Approving..." : "Approve this specification snapshot"}
                    </button>
                  </div>
                )}
                <div className="workflow-actions">
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={specificationInputsLoading}
                    onClick={() => void loadSpecificationInputs(specification)}
                  >
                    {specificationInputsLoading ? "Loading inputs..." : "Inspect exact inputs and validation"}
                  </button>
                </div>
                {specificationInputsError && (
                  <div className="error-card" role="alert">
                    <p>{specificationInputsError}</p>
                    <button
                      className="button button-secondary"
                      onClick={() => void loadSpecificationInputs(specification)}
                    >
                      Try again
                    </button>
                  </div>
                )}
                {specificationInputs && (
                  <div className="specification-inputs">
                    <h5>Exact approved input versions</h5>
                    <ul>
                      {specificationInputs.input_artifacts.map((input) => (
                        <li key={input.id}>
                          {input.kind} v{input.version_number} · {input.status}
                          {" · "}{input.id}
                        </li>
                      ))}
                    </ul>
                    {specificationInputs.validation_findings.length > 0 ? (
                      <>
                        <h5>Validation findings</h5>
                        <ul className="specification-findings">
                          {specificationInputs.validation_findings.map((finding, index) => (
                            <li key={`${finding.code}-${index}`}>
                              <strong>{finding.severity}: {finding.code}</strong>
                              <span>{finding.message}</span>
                            </li>
                          ))}
                        </ul>
                      </>
                    ) : <p className="muted">No cross-reference conflicts were found during composition.</p>}
                  </div>
                )}
                {specification.is_outdated && (
                  <p className="specification-outdated">
                    One or more input kinds now have a newer approved version. This snapshot remains preserved. Review the inputs above, then generate a new snapshot.
                  </p>
                )}
                {Array.isArray(specification.content.validation_findings) &&
                  specification.content.validation_findings.length > 0 && (
                    <div className="specification-findings">
                      <h5>Composition findings</h5>
                      <ul>
                        {specification.content.validation_findings.map((value, index) => {
                          const finding = asObject(value);
                          return (
                            <li key={`${String(finding.code)}-${index}`}>
                              <strong>{String(finding.severity)}: {String(finding.code)}</strong>
                              <span>{String(finding.message)}</span>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  )}
                <nav className="specification-toc" aria-label="Specification sections">
                  {Object.entries(specification.content)
                    .filter(([key]) => !["generated_at", "input_artifacts", "validation_findings", "specification_status"].includes(key))
                    .map(([key]) => (
                      <a key={key} href={`#spec-${specification.id}-${key}`}>{key.replaceAll("_", " ")}</a>
                    ))}
                </nav>
                {Object.entries(specification.content)
                  .filter(([key]) => !["generated_at", "input_artifacts", "validation_findings", "specification_status"].includes(key))
                  .map(([key, value]) => (
                    <details className="specification-section" id={`spec-${specification.id}-${key}`} key={key} open={key === "project"}>
                      <summary>{key.replaceAll("_", " ")}</summary>
                      <pre>{JSON.stringify(value, null, 2)}</pre>
                    </details>
                  ))}
                {specification.source_snapshot.length > 0 && (
                  <div className="specification-evidence">
                    <h5>Preserved evidence and citations</h5>
                    <ul className="workflow-source-list">
                      {specification.source_snapshot.map((source) => (
                        <li key={source.id}>
                          {sourceLinkIsSafe(source.source_url)
                            ? <a href={source.source_url} target="_blank" rel="noopener noreferrer">{source.source_title}</a>
                            : source.source_title}
                          <span>{source.publisher || "Publisher not provided"} · Published {source.publication_date ?? "date unknown"} · Retrieved {source.retrieved_at ?? "timestamp unavailable"}</span>
                          {source.relevant_excerpt && <span>{source.relevant_excerpt}</span>}
                          <code>{source.id}</code>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </section>
        </>
      )}
    </section>
  );
}
