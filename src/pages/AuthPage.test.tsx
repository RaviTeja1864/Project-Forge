import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { AuthPage } from "./AuthPage";

describe("AuthPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Authentication credentials were not provided." }),
    }));
  });

  it("validates password confirmation before submitting registration", async () => {
    render(<MemoryRouter><AuthProvider><AuthPage mode="register" /></AuthProvider></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "person@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a-long-password" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "different-password" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /create account/i })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your passwords do not match.");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("shows the generic server response for invalid login credentials", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/me/")) {
        return new Response(JSON.stringify({ detail: "Authentication credentials were not provided." }), { status: 403 });
      }
      if (url.endsWith("/auth/csrf/")) {
        return new Response(JSON.stringify({ csrfToken: "test-token" }), { status: 200 });
      }
      return new Response(JSON.stringify({ non_field_errors: ["Invalid email or password."] }), { status: 400 });
    }));
    render(<MemoryRouter><AuthProvider><AuthPage mode="login" /></AuthProvider></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "person@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "incorrect-password" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /sign in/i })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
  });

  it("refreshes the CSRF token after registration establishes a session", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/me/")) {
        return new Response(JSON.stringify({ detail: "Authentication credentials were not provided." }), { status: 403 });
      }
      if (url.endsWith("/auth/csrf/")) {
        return new Response(JSON.stringify({ csrfToken: "fresh-token" }), { status: 200 });
      }
      return new Response(
        JSON.stringify({ id: 2, email: "builder@example.test", date_joined: "2026-01-01" }),
        { status: 201 },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={["/register"]}>
        <AuthProvider>
          <Routes>
            <Route path="/register" element={<AuthPage mode="register" />} />
            <Route path="/app" element={<h1>Authenticated dashboard</h1>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "builder@example.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Long-and-unique-26!" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "Long-and-unique-26!" } });
    await waitFor(() => expect(screen.getByRole("button", { name: /create account/i })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByRole("heading", { name: "Authenticated dashboard" })).toBeInTheDocument();
    const paths = fetchMock.mock.calls.map(([input]) => String(input));
    expect(paths.filter((path) => path.endsWith("/auth/csrf/"))).toHaveLength(2);
    expect(paths[2]).toContain("/auth/register/");
  });
});
