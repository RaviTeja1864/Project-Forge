import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { DashboardPage } from "./DashboardPage";

const workspace = {
  id: "5a4b3c2d-1111-4444-8888-123456789abc",
  name: "Heat-safe neighborhoods",
  description: "Explore community cooling spaces.",
  status: "in_progress" as const,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
  access_role: "owner" as const,
};

function mockApi(workspaces: unknown) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const data = url.endsWith("/auth/me/")
      ? { id: 1, email: "person@example.com", date_joined: "2026-01-01" }
      : workspaces;
    const failed = data instanceof Error;
    return new Response(JSON.stringify(failed ? { detail: data.message } : data), {
      status: failed ? 500 : 200,
      headers: { "Content-Type": "application/json" },
    });
  }));
}

describe("DashboardPage", () => {
  it("shows real workspace data and count", async () => {
    mockApi({ count: 1, next: null, previous: null, results: [workspace] });
    render(<MemoryRouter><AuthProvider><DashboardPage /></AuthProvider></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Heat-safe neighborhoods" })).toBeInTheDocument();
    expect(screen.getAllByText("1", { selector: "strong" })).toHaveLength(2);
    expect(screen.getByText("In progress")).toBeInTheDocument();
  });

  it("shows an explicit empty state for a new account", async () => {
    mockApi({ count: 0, next: null, previous: null, results: [] });
    render(<MemoryRouter><AuthProvider><DashboardPage /></AuthProvider></MemoryRouter>);
    expect(await screen.findByText(/your first project starts with a question/i)).toBeInTheDocument();
  });

  it("shows an error and retry action when workspaces cannot be loaded", async () => {
    mockApi(new Error("Network unavailable"));
    render(<MemoryRouter><AuthProvider><DashboardPage /></AuthProvider></MemoryRouter>);
    expect(await screen.findByText("Network unavailable")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument());
  });
});
