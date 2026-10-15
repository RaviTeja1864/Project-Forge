import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImplementationPlanning } from "./ImplementationPlanning";
import type { Workspace, WorkspaceArtifact } from "../types";

const workspace: Workspace = {
  id: "5a4b3c2d-1111-4444-8888-123456789abc",
  name: "Water project",
  description: "",
  status: "planning",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  access_role: "owner",
};

const requirements: WorkspaceArtifact = {
  id: "8833d4c2-06bc-4e0d-b902-f6d7018a20a3",
  kind: "requirements",
  status: "approved",
  is_outdated: false,
  version_number: 1,
  lineage_root_id: "8833d4c2-06bc-4e0d-b902-f6d7018a20a3",
  revision_of_id: null,
  author_id: 1,
  content: {
    functional_requirements: [{ id: "FR-001", statement: "Display cited sources." }],
    non_functional_requirements: [],
    acceptance_criteria: [{
      id: "AC-001",
      criterion: "A cited source link opens.",
      requirement_ids: ["FR-001"],
    }],
  },
  source_snapshot: [],
  source_problem_id: null,
  input_artifact_ids: [],
  created_at: "2026-01-03T00:00:00Z",
  updated_at: "2026-01-03T00:00:00Z",
};

const task = {
  id: 12,
  source_requirements_artifact_id: requirements.id,
  source_requirements_version: 1,
  source_requirement_id: "FR-001",
  acceptance_criteria_ids: ["AC-001"],
  title: "Implement: Display cited sources.",
  description: "Implement requirement FR-001.",
  status: "todo" as const,
  priority: "medium" as const,
  dependency_ids: [],
  is_outdated: false,
  created_at: "2026-01-04T00:00:00Z",
  updated_at: "2026-01-04T00:00:00Z",
};

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ImplementationPlanning", () => {
  it("generates a plan, records reviewed evidence, and displays the resulting decision", async () => {
    let taskList = [] as typeof task[];
    const verification = {
      id: "verification-1",
      requirements_artifact_id: requirements.id,
      requirements_version: 1,
      requirement_id: "FR-001",
      status: "unverified" as const,
      recorded_status: "unverified",
      is_outdated: false,
      rationale: "Evidence is absent.",
      evidence_ids: [],
      criterion_results: [],
      actor_id: 1,
      created_at: "2026-01-05T00:00:00Z",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf/")) return response({ csrfToken: "test-token" });
      if (url.includes("/implementation/tasks/generate/") && options?.method === "POST") {
        taskList = [task];
        return response({
          tasks: taskList,
          created_count: 1,
          existing_count: 0,
          unmapped_requirements: [],
        });
      }
      if (url.endsWith("/implementation/tasks/")) return response(taskList);
      if (url.endsWith("/evidence/") && options?.method === "POST") {
        return response({
          id: 31,
          requirement_id: "FR-001",
          acceptance_criterion_id: "AC-001",
          task_id: task.id,
          evidence_type: "verification_check",
          description: "Source opens.",
          source_reference: "tests/test_sources.py",
          result: "passed",
          review_basis: "manually_reviewed",
          trust_label: "recorded as manually reviewed; not an automated verification",
          supersedes_id: null,
          author_id: 1,
          created_at: "2026-01-05T00:00:00Z",
        }, 201);
      }
      if (url.endsWith("/verification/") && options?.method === "POST") {
        return response({ ...verification, status: "verified", recorded_status: "verified" }, 201);
      }
      if (url.endsWith("/verification/history/")) return response([]);
      if (url.endsWith("/evidence/")) return response([]);
      if (url.endsWith("/verification/")) return response(verification);
      return response({ detail: "Unexpected request" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ImplementationPlanning workspace={workspace} artifacts={[requirements]} />);

    fireEvent.click(await screen.findByRole("button", { name: "Generate tasks from requirements" }));
    fireEvent.click(await screen.findByRole("button", { name: /Implement: Display cited sources/ }));
    expect(await screen.findByText(/unverified/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Acceptance criterion"), { target: { value: "AC-001" } });
    fireEvent.change(screen.getAllByLabelText("Description")[1], { target: { value: "Source link opened in manual review." } });
    fireEvent.change(screen.getByLabelText("Review basis"), { target: { value: "manually_reviewed" } });
    fireEvent.change(screen.getByLabelText("Result"), { target: { value: "passed" } });
    fireEvent.click(screen.getByRole("button", { name: "Save evidence" }));
    expect(await screen.findByText(/recorded as manually reviewed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Record verification decision" }));
    await waitFor(() => expect(screen.getByText("verified", { selector: "strong" })).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/requirements/${requirements.id}/FR-001/verification/`),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("lets collaborators inspect tasks without owner mutation controls", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/evidence/")) return response([]);
      if (url.endsWith("/verification/history/")) return response([]);
      if (url.endsWith("/verification/")) return response({
        requirement_id: "FR-001",
        requirements_version: 1,
        status: "unverified",
        is_outdated: false,
        rationale: "No evidence.",
        evidence_ids: [],
        criterion_results: [],
        actor_id: null,
        created_at: null,
      });
      return response([task]);
    }));
    render(
      <ImplementationPlanning
        workspace={{ ...workspace, access_role: "collaborator" }}
        artifacts={[requirements]}
      />,
    );
    expect(await screen.findByRole("button", { name: /Implement: Display cited sources/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate tasks from requirements" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Implement: Display cited sources/ }));
    expect(await screen.findByText("FR-001: Display cited sources.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save evidence" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record verification decision" })).not.toBeInTheDocument();
  });
});
