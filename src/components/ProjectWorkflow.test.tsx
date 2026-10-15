import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProjectWorkflow } from "./ProjectWorkflow";
import type { WorkspaceArtifact } from "../types";

const workspace = {
  id: "5a4b3c2d-1111-4444-8888-123456789abc",
  name: "Water access project",
  description: "Explore safe water access.",
  status: "planning" as const,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  access_role: "owner" as const,
};

const problem = {
  id: "9bf61b27-ff63-4776-9b98-10475df22a82",
  title: "Safe water access",
  description: "Residents report water access difficulties.",
  sector: "Water",
  difficulty: "unspecified" as const,
  status: "published" as const,
  evidence_source_count: 1,
  created_at: "2026-03-10T10:00:00Z",
  updated_at: "2026-03-10T10:00:00Z",
};

const draft: WorkspaceArtifact = {
  id: "8833d4c2-06bc-4e0d-b902-f6d7018a20a3",
  kind: "research",
  status: "draft",
  is_outdated: false,
  version_number: 1,
  lineage_root_id: "8833d4c2-06bc-4e0d-b902-f6d7018a20a3",
  revision_of_id: null,
  author_id: 1,
  content: {
    problem_summary: "Report describes water access needs.",
    key_claims: [{
      claim: "Residents need access to safe water.",
      support_status: "supported",
      evidence_source_ids: ["source-1"],
    }],
    evidence_limitations: [],
    conflicting_information: [],
    unknown_or_unsupported_details: ["Affected population is unknown."],
    research_gaps: [],
    interpretations_and_recommendations: [],
    omitted_evidence_count: 0,
  },
  source_snapshot: [{
    id: "source-1",
    source_url: "https://example.org/water",
    source_title: "Water access report",
    publisher: "Public agency",
    publication_date: null,
    relevant_excerpt: "Residents need safe water.",
  }],
  source_problem_id: problem.id,
  input_artifact_ids: [],
  created_at: "2026-03-10T10:00:00Z",
  updated_at: "2026-03-10T10:00:00Z",
};

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderWorkflow() {
  return render(
    <MemoryRouter>
      <ProjectWorkflow workspace={workspace} />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ProjectWorkflow", () => {
  it("loads local model availability and generates, edits, and approves a sourced draft", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input);
      if (url.includes("/implementation/tasks/")) return response([]);
      if (url.endsWith("/auth/csrf/")) return response({ csrfToken: "token" });
      if (url.endsWith("/artifacts/")) return response([]);
      if (url.includes("/problems/")) {
        return response({ count: 1, next: null, previous: null, results: [problem] });
      }
      if (url.endsWith("/llm/status/")) {
        return response({ available: true, model: "qwen3:4b", state: "available" });
      }
      if (url.endsWith("/generate/research/")) {
        return response(draft, 201);
      }
      if (options?.method === "PATCH") {
        const body = JSON.parse(String(options.body)) as { content?: Record<string, unknown>; status?: string };
        return response({
          ...draft,
          content: body.content ?? draft.content,
          status: body.status ?? draft.status,
        });
      }
      return response({ detail: "Unexpected request" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWorkflow();

    expect(await screen.findByText(/Local model: qwen3:4b · available/)).toBeInTheDocument();
    const research = screen.getByRole("heading", { name: "Evidence-grounded research" }).closest("article");
    expect(research).not.toBeNull();
    fireEvent.change(within(research as HTMLElement).getByLabelText("Catalogue problem"), {
      target: { value: problem.id },
    });
    fireEvent.click(within(research as HTMLElement).getByRole("button", { name: "Generate draft" }));
    expect(await screen.findByText("Water access report")).toBeInTheDocument();
    expect(screen.getByText("Residents need access to safe water.").closest("p")).toHaveTextContent("supported");
    expect(screen.getByRole("link", { name: "View selected problem and evidence" })).toHaveAttribute(
      "href",
      `/app/problems/${problem.id}`,
    );

    const editor = screen.getByLabelText("Editable structured JSON");
    const edited = { ...draft.content, problem_summary: "Edited and reviewed summary." };
    fireEvent.change(editor, { target: { value: JSON.stringify(edited, null, 2) } });
    fireEvent.click(screen.getByRole("button", { name: "Save edits" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/artifacts/${draft.id}/`),
      expect.objectContaining({ method: "PATCH" }),
    ));
    fireEvent.click(screen.getByRole("button", { name: "Approve this artifact" }));
    expect(await screen.findByText("approved")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/artifacts/${draft.id}/`),
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("shows an explicit offline state, generation error, and retryable page load failure", async () => {
    let failLoad = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/implementation/tasks/")) return response([]);
      if (url.endsWith("/artifacts/") && failLoad) {
        failLoad = false;
        return response({ detail: "Workspace tools unavailable" }, 503);
      }
      if (url.endsWith("/artifacts/")) return response([]);
      if (url.includes("/problems/")) {
        return response({ count: 1, next: null, previous: null, results: [problem] });
      }
      if (url.endsWith("/llm/status/")) {
        return response({ available: false, model: "qwen3:4b", state: "offline" });
      }
      if (url.endsWith("/generate/research/")) {
        return response({ detail: "The local model service is offline or unreachable." }, 503);
      }
      return response({ csrfToken: "token" });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWorkflow();
    expect(await screen.findByRole("alert")).toHaveTextContent("Workspace tools unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/Local model: qwen3:4b · offline/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Catalogue problem"), {
      target: { value: problem.id },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Generate draft" })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent("The local model service is offline");
  });

  it("loads lineage history, opens prior versions read-only, and compares their content", async () => {
    const first: WorkspaceArtifact = {
      ...draft,
      id: "8833d4c2-06bc-4e0d-b902-f6d7018a20a4",
      status: "approved",
      version_number: 1,
      lineage_root_id: "8833d4c2-06bc-4e0d-b902-f6d7018a20a4",
      revision_of_id: null,
    };
    const second: WorkspaceArtifact = {
      ...draft,
      version_number: 2,
      lineage_root_id: first.id,
      revision_of_id: first.id,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/implementation/tasks/")) return response([]);
      if (url.endsWith("/artifacts/")) return response([second, first]);
      if (url.includes("/versions/compare/")) {
        return response({
          left_version: first,
          right_version: second,
          changed_fields: ["content.problem_summary"],
          changes: [{
            path: "content.problem_summary",
            before: "Earlier summary.",
            after: "Revised summary.",
          }],
        });
      }
      if (url.endsWith(`/artifacts/${first.id}/revise/`)) {
        return response({
          ...second,
          id: "8833d4c2-06bc-4e0d-b902-f6d7018a20a5",
          version_number: 3,
          revision_of_id: first.id,
        }, 201);
      }
      if (url.endsWith("/versions/")) return response([first, second]);
      if (url.endsWith("/problems/?page_size=50")) {
        return response({ count: 1, next: null, previous: null, results: [problem] });
      }
      if (url.endsWith("/llm/status/")) {
        return response({ available: true, model: "qwen3:4b", state: "available" });
      }
      return response({ csrfToken: "token" });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWorkflow();

    expect(await screen.findByText(/Version 2 · draft/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View version history" }));
    expect(await screen.findByText("Version history")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/artifacts/${second.id}/versions/`),
      expect.anything(),
    );
    fireEvent.click(screen.getByRole("button", { name: /v1 · approved/ }));
    expect(await screen.findByText(/Historical, read-only/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Editable structured JSON")).not.toBeInTheDocument();
    expect(screen.getByText(/Current approved version/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Compare version"), { target: { value: first.id } });
    fireEvent.change(screen.getByLabelText("With version"), { target: { value: second.id } });
    fireEvent.click(screen.getByRole("button", { name: "Compare versions" }));
    expect(await screen.findByText("content.problem_summary")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("versions/compare/?left_version="),
      expect.anything(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Create revision from v1" }));
    expect(await screen.findByText(/Version 3 · draft/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/artifacts/${first.id}/revise/`),
      expect.anything(),
    );
  });

  it("reports a retryable version-history loading failure", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/implementation/tasks/")) return response([]);
      if (url.endsWith("/artifacts/")) return response([draft]);
      if (url.endsWith(`/artifacts/${draft.id}/versions/`)) {
        return response({ detail: "Version history is unavailable." }, 503);
      }
      if (url.endsWith("/problems/?page_size=50")) {
        return response({ count: 1, next: null, previous: null, results: [problem] });
      }
      if (url.endsWith("/llm/status/")) {
        return response({ available: true, model: "qwen3:4b", state: "available" });
      }
      return response({ csrfToken: "token" });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWorkflow();
    expect(await screen.findByText(/Version 1 · draft/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View version history" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Version history is unavailable.");
  });

  it("composes, displays, approves, and inspects a specification snapshot", async () => {
    const specification: WorkspaceArtifact = {
      ...draft,
      id: "8833d4c2-06bc-4e0d-b902-f6d7018a20a6",
      kind: "specification",
      status: "draft",
      is_outdated: true,
      content: {
        specification_status: "review_required",
        generated_at: "2026-10-16T00:00:00Z",
        project: { title: "Water access project", problem_statement: "Improve access." },
        research: { key_claims: [{ claim: "Evidence-backed claim." }] },
        requirements: { functional_requirements: [] },
        technology: { recommendation: { option: "Django" } },
        architecture: { architecture_diagram: "flowchart LR\n  Client --> API" },
        security_and_reliability: { security: ["Enforce ownership."] },
        constraints: [],
        risks: [],
        assumptions: [],
        unresolved_information: { research_gaps: ["Population data unknown."] },
        tradeoffs: {},
        validation_findings: [{
          severity: "warning",
          code: "technology_decision_conflict",
          path: "technology.recommendation.option",
          message: "Approved decisions disagree.",
        }],
        input_artifacts: [{
          kind: "research",
          artifact_id: draft.id,
          version_number: 1,
          status: "approved",
          lineage_root_id: draft.id,
        }],
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input);
      if (url.includes("/implementation/tasks/")) return response([]);
      if (url.endsWith("/artifacts/")) return response([]);
      if (url.endsWith("/problems/?page_size=50")) {
        return response({ count: 1, next: null, previous: null, results: [problem] });
      }
      if (url.endsWith("/llm/status/")) {
        return response({ available: false, model: "qwen3:4b", state: "offline" });
      }
      if (url.endsWith("/specifications/") && options?.method === "POST") {
        return response(specification, 201);
      }
      if (url.endsWith(`/specifications/${specification.id}/inputs/`)) {
        return response({
          specification_id: specification.id,
          is_outdated: true,
          input_artifacts: [{ ...draft, status: "approved" }],
          validation_findings: specification.content.validation_findings,
        });
      }
      if (options?.method === "PATCH") {
        return response({ ...specification, status: "approved" });
      }
      return response({ csrfToken: "token" });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWorkflow();

    fireEvent.click(await screen.findByRole("button", { name: "Generate specification snapshot" }));
    expect(await screen.findByText("Unified engineering specification")).toBeInTheDocument();
    expect(await screen.findByText(/Potentially outdated/)).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Specification sections" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("architecture")[1]);
    expect(screen.getByText(/flowchart LR/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve this specification snapshot" }));
    expect(await screen.findByText(/Snapshot v1 · approved/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Inspect exact inputs and validation" }));
    expect(await screen.findByText(/research v1 · approved/)).toBeInTheDocument();
    expect(screen.getAllByText(/Approved decisions disagree/)).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/specifications/${specification.id}/inputs/`),
      expect.anything(),
    );
  });

  it("shows actionable missing-input errors when specification generation fails", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input);
      if (url.includes("/implementation/tasks/")) return response([]);
      if (url.endsWith("/artifacts/")) return response([]);
      if (url.endsWith("/problems/?page_size=50")) {
        return response({ count: 0, next: null, previous: null, results: [] });
      }
      if (url.endsWith("/llm/status/")) {
        return response({ available: true, model: "qwen3:4b", state: "available" });
      }
      if (url.endsWith("/specifications/") && options?.method === "POST") {
        return response({ detail: "Approve a design artifact in this workspace before generating a specification." }, 400);
      }
      return response({ csrfToken: "token" });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWorkflow();
    fireEvent.click(await screen.findByRole("button", { name: "Generate specification snapshot" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Approve a design artifact");
    expect(screen.getByText(/No specification snapshots yet/)).toBeInTheDocument();
  });

  it("downloads the selected snapshot in Markdown or PDF with retryable errors", async () => {
    const specification: WorkspaceArtifact = {
      ...draft,
      kind: "specification",
      content: { ...draft.content, generated_at: "2026-10-16T00:00:00Z" },
    };
    let failPdf = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/implementation/tasks/")) return response([]);
      if (url.endsWith("/artifacts/")) return response([specification]);
      if (url.endsWith("/problems/?page_size=50")) {
        return response({ count: 1, next: null, previous: null, results: [problem] });
      }
      if (url.endsWith("/llm/status/")) {
        return response({ available: true, model: "qwen3:4b", state: "available" });
      }
      if (url.endsWith(`/specifications/${specification.id}/export.md`)) {
        return new Response("# UTF-8 specification", {
          status: 200,
          headers: {
            "Content-Type": "text/markdown; charset=utf-8",
            "Content-Disposition": 'attachment; filename="water-v1.md"',
          },
        });
      }
      if (url.endsWith(`/specifications/${specification.id}/export.pdf`)) {
        if (failPdf) {
          failPdf = false;
          return response({ detail: "PDF export could not be prepared." }, 503);
        }
        return new Response(new Uint8Array([37, 80, 68, 70]), {
          status: 200,
          headers: {
            "Content-Type": "application/pdf",
            "Content-Disposition": 'attachment; filename="water-v1.pdf"',
          },
        });
      }
      return response({ csrfToken: "token" });
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", class TestURL extends URL {
      static createObjectURL = vi.fn(() => "blob:specification");
      static revokeObjectURL = vi.fn();
    });
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderWorkflow();

    expect(await screen.findByText(/Snapshot v1 · draft/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download Markdown" }));
    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/specifications/${specification.id}/export.md`),
      expect.objectContaining({ credentials: "include" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("PDF export could not be prepared.");
    fireEvent.click(screen.getByRole("button", { name: "Try download again" }));
    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(2));
    expect(fetchMock).toHaveBeenCalledTimes(7);
  });
});
