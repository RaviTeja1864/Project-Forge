import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CreateWorkspacePage, WorkspaceDetailPage } from "./WorkspacePages";

const workspace = {
  id: "5a4b3c2d-1111-4444-8888-123456789abc",
  name: "Heat-safe neighborhoods",
  description: "Explore community cooling spaces.",
  status: "planning" as const,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  access_role: "owner" as const,
};

function response(body: unknown, status = 200) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkspacePages", () => {
  it("creates a workspace and opens its detail page", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/implementation/tasks/")) return response([]);
      if (url.endsWith("/auth/csrf/")) return response({ csrfToken: "test-token" });
      if (url.endsWith("/workspaces/")) return response(workspace, 201);
      return response(workspace);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={["/app/workspaces/new"]}>
        <Routes>
          <Route path="/app/workspaces/new" element={<CreateWorkspacePage />} />
          <Route path="/app/workspaces/:id" element={<WorkspaceDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Workspace name"), { target: { value: "Heat-safe neighborhoods" } });
    fireEvent.click(screen.getByRole("button", { name: /create workspace/i }));
    expect(await screen.findByRole("heading", { name: "Heat-safe neighborhoods" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/workspaces/"),
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  it("saves workspace edits and reports success", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input);
      if (url.includes("/implementation/tasks/")) return response([]);
      if (url.endsWith("/auth/csrf/")) return response({ csrfToken: "test-token" });
      if (options?.method === "PATCH") {
        return response({ ...workspace, name: "Cooler neighborhoods" });
      }
      return response(workspace);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={[`/app/workspaces/${workspace.id}`]}>
        <Routes><Route path="/app/workspaces/:id" element={<WorkspaceDetailPage />} /></Routes>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Edit workspace" }));
    const nameInput = screen.getByLabelText("Workspace name");
    fireEvent.change(nameInput, { target: { value: "Cooler neighborhoods" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("heading", { name: "Cooler neighborhoods" })).toBeInTheDocument();
    expect(await screen.findByText("Workspace changes saved.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/workspaces/${workspace.id}/`),
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("confirms deletion and removes a workspace", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input);
      if (url.includes("/implementation/tasks/")) return response([]);
      if (url.endsWith("/auth/csrf/")) return response({ csrfToken: "test-token" });
      return options?.method === "DELETE" ? response(undefined, 204) : response(workspace);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn(() => true));
    render(
      <MemoryRouter initialEntries={[`/app/workspaces/${workspace.id}`]}>
        <Routes>
          <Route path="/app/workspaces/:id" element={<WorkspaceDetailPage />} />
          <Route path="/app" element={<h1>Workspace overview</h1>} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("heading", { name: "Workspace overview" })).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/workspaces/${workspace.id}/`),
      expect.objectContaining({ method: "DELETE" }),
    ));
  });

  it("shows collaborators only the shared read-only workspace experience", async () => {
    const sharedWorkspace = { ...workspace, access_role: "collaborator" as const };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/implementation/tasks/")) return response([]);
      if (url.endsWith("/auth/csrf/")) return response({ csrfToken: "test-token" });
      if (url.endsWith(`/workspaces/${workspace.id}/`)) return response(sharedWorkspace);
      if (url.endsWith("/artifacts/")) return response([]);
      if (url.includes("/problems/")) return response({ count: 0, next: null, previous: null, results: [] });
      if (url.endsWith("/llm/status/")) return response({ available: false, model: "qwen3:4b", state: "offline" });
      return response([]);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={[`/app/workspaces/${workspace.id}`]}>
        <Routes><Route path="/app/workspaces/:id" element={<WorkspaceDetailPage />} /></Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("SHARED WORKSPACE · READ ONLY")).toBeInTheDocument();
    expect(screen.getByText(/editing, approvals, generation, and sharing are owner-only/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit workspace" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Read-only sharing" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate draft" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Catalogue problem")).not.toBeInTheDocument();
  });

  it("lets an owner grant an existing account read-only access", async () => {
    let grants: Array<{
      id: number;
      email: string;
      granted_by_email: string;
      granted_at: string;
      revoked_at: string | null;
      access_status: "active" | "revoked";
    }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input);
      if (url.includes("/implementation/tasks/")) return response([]);
      if (url.endsWith("/auth/csrf/")) return response({ csrfToken: "test-token" });
      if (url.endsWith("/collaborators/7/") && options?.method === "DELETE") {
        grants = grants.map((grant) => ({
          ...grant,
          revoked_at: "2026-02-02T00:00:00Z",
          access_status: "revoked",
        }));
        return response(undefined, 204);
      }
      if (url.endsWith(`/workspaces/${workspace.id}/collaborators/`)) {
        if (options?.method === "POST") {
          grants = [{
            id: 7,
            email: "reader@example.com",
            granted_by_email: "owner@example.com",
            granted_at: "2026-02-01T00:00:00Z",
            revoked_at: null,
            access_status: "active",
          }];
          return response(grants[0], 201);
        }
        return response(grants);
      }
      if (url.endsWith("/artifacts/")) return response([]);
      if (url.includes("/problems/")) return response({ count: 0, next: null, previous: null, results: [] });
      if (url.endsWith("/llm/status/")) return response({ available: false, model: "qwen3:4b", state: "offline" });
      return response(workspace);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={[`/app/workspaces/${workspace.id}`]}>
        <Routes><Route path="/app/workspaces/:id" element={<WorkspaceDetailPage />} /></Routes>
      </MemoryRouter>,
    );
    fireEvent.change(await screen.findByLabelText("Account email"), {
      target: { value: "reader@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Grant read-only access" }));
    expect(await screen.findByRole("listitem")).toHaveTextContent(/reader@example.com.*active/);
    vi.stubGlobal("confirm", vi.fn(() => true));
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() =>
      expect(screen.getByRole("listitem")).toHaveTextContent(/reader@example.com.*revoked/),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/workspaces/${workspace.id}/collaborators/`),
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/workspaces/${workspace.id}/collaborators/7/`),
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
