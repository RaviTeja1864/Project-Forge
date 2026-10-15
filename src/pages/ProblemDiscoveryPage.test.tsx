import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProblemDetailPage, ProblemDiscoveryPage } from "./ProblemDiscoveryPage";

const problem = {
  id: "9bf61b27-ff63-4776-9b98-10475df22a82",
  title: "Drought resilience in rural communities",
  description: "A source-backed summary of reported water access challenges.",
  sector: "Water Sanitation Hygiene",
  difficulty: "unspecified" as const,
  status: "published" as const,
  evidence_source_count: 2,
  created_at: "2026-03-10T10:00:00Z",
  updated_at: "2026-03-10T10:00:00Z",
};

const source = {
  id: "8833d4c2-06bc-4e0d-b902-f6d7018a20a3",
  source_url: "https://reliefweb.int/report/example/water-access",
  source_title: "Water access in rural districts",
  publisher: "Example Ministry",
  publication_date: "2026-02-14",
  retrieved_at: "2026-03-10T10:00:00Z",
  relevant_excerpt: "Residents need access to safe drinking water.",
  source_type: "report" as const,
};

const similarResults = {
  threshold: 0.35,
  count: 1,
  results: [{
    problem: { ...problem, id: "9bf61b27-ff63-4776-9b98-10475df22a83", title: "Rural water resilience" },
    similarity_score: 0.72,
    matching_signals: ["Titles share 2 normalized term(s)"],
  }],
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function detailFetch(sourceBody: unknown = {
  count: 1,
  next: null,
  previous: null,
  results: [source],
}) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/sources/?page=")) {
      return Promise.resolve(jsonResponse(sourceBody));
    }
    if (url.includes("/similar/")) {
      return Promise.resolve(jsonResponse(similarResults));
    }
    return Promise.resolve(jsonResponse(problem));
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ProblemDiscoveryPage", () => {
  it("renders API-backed problems and source counts", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      count: 1,
      next: null,
      previous: null,
      results: [problem],
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter><ProblemDiscoveryPage /></MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: problem.title })).toBeInTheDocument();
    expect(screen.getByText("2 sources")).toBeInTheDocument();
    expect(screen.getByText("Water Sanitation Hygiene")).toBeInTheDocument();
    expect(screen.getByText("Difficulty: Not specified")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/problems/?page=1"),
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("shows an honest empty state when no problems have been ingested", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      count: 0,
      next: null,
      previous: null,
      results: [],
    })));
    render(<MemoryRouter><ProblemDiscoveryPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: /catalogue is waiting/i })).toBeInTheDocument();
    expect(screen.getByText(/no sample problems are shown/i)).toBeInTheDocument();
  });

  it("shows API errors and retries without replacing them with sample problems", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "Authentication required." }, 403))
      .mockResolvedValueOnce(jsonResponse({ count: 0, next: null, previous: null, results: [] }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><ProblemDiscoveryPage /></MemoryRouter>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Authentication required.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: /catalogue is waiting/i })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("debounces keyword search and applies filter changes to the API and URL", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({
      count: 0,
      next: null,
      previous: null,
      results: [],
    })));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={["/app/discover"]}>
        <Routes>
          <Route path="/app/discover" element={<ProblemDiscoveryPage />} />
        </Routes>
      </MemoryRouter>,
    );
    const search = screen.getByRole("searchbox", { name: "Search problems and evidence" });
    fireEvent.change(search, { target: { value: "water" } });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("q=water"),
        expect.objectContaining({ credentials: "include" }),
      );
    }, { timeout: 2500 });
    fireEvent.change(screen.getByRole("textbox", { name: "Filter by sector" }), {
      target: { value: "Water Sanitation Hygiene" },
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("sector=Water+Sanitation+Hygiene"),
      expect.objectContaining({ credentials: "include" }),
    ));
  });

  it("does not let an older response replace newer filtered results", async () => {
    let resolveInitial: ((response: Response) => void) | undefined;
    let resolveFiltered: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn((input: RequestInfo | URL) => new Promise<Response>((resolve) => {
      if (String(input).includes("sector=")) resolveFiltered = resolve;
      else resolveInitial = resolve;
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={["/app/discover"]}>
        <Routes><Route path="/app/discover" element={<ProblemDiscoveryPage />} /></Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(resolveInitial).toBeDefined());
    fireEvent.change(screen.getByRole("textbox", { name: "Filter by sector" }), {
      target: { value: "Water" },
    });
    await waitFor(() => expect(resolveFiltered).toBeDefined());
    await act(async () => {
      resolveFiltered?.(jsonResponse({
        count: 1,
        next: null,
        previous: null,
        results: [{ ...problem, title: "Newest filtered result" }],
      }));
    });
    expect(await screen.findByRole("heading", { name: "Newest filtered result" })).toBeInTheDocument();
    await act(async () => {
      resolveInitial?.(jsonResponse({
        count: 1,
        next: null,
        previous: null,
        results: [{ ...problem, title: "Stale unfiltered result" }],
      }));
    });
    expect(screen.getByRole("heading", { name: "Newest filtered result" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Stale unfiltered result" })).not.toBeInTheDocument();
  });
});

describe("ProblemDetailPage", () => {
  it("shows source excerpts, known metadata, and an attributed external link", async () => {
    vi.stubGlobal("fetch", detailFetch());
    render(
      <MemoryRouter initialEntries={[`/app/problems/${problem.id}`]}>
        <Routes><Route path="/app/problems/:problemId" element={<ProblemDetailPage />} /></Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: problem.title })).toBeInTheDocument();
    expect(screen.getByText(source.relevant_excerpt)).toBeInTheDocument();
    expect(screen.getByText("Example Ministry")).toBeInTheDocument();
    const sourceLink = screen.getByRole("link", { name: /water access in rural districts/i });
    expect(sourceLink).toHaveAttribute("href", source.source_url);
    expect(sourceLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByRole("heading", { name: "Similar problems" })).toBeInTheDocument();
    expect(screen.getByText("Score 0.72")).toBeInTheDocument();
    expect(screen.getByText("Titles share 2 normalized term(s)")).toBeInTheDocument();
  });

  it("preserves missing source dates instead of inventing dates", async () => {
    vi.stubGlobal("fetch", detailFetch({
      count: 1,
      next: null,
      previous: null,
      results: [{ ...source, publication_date: null, publisher: "" }],
    }));
    render(
      <MemoryRouter initialEntries={[`/app/problems/${problem.id}`]}>
        <Routes><Route path="/app/problems/:problemId" element={<ProblemDetailPage />} /></Routes>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { name: problem.title });
    expect(screen.getByText("Published: Date not provided by source")).toBeInTheDocument();
    expect(screen.getByText("Publisher not provided")).toBeInTheDocument();
  });

  it("shows detail loading and API failures with a discovery escape route", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/sources/")) {
        return Promise.resolve(jsonResponse({ count: 0, next: null, previous: null, results: [] }));
      }
      if (url.includes("/similar/")) {
        return Promise.resolve(jsonResponse({ threshold: 0.35, count: 0, results: [] }));
      }
      return Promise.reject(new Error("Catalogue unavailable"));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={[`/app/problems/${problem.id}`]}>
        <Routes>
          <Route path="/app/problems/:problemId" element={<ProblemDetailPage />} />
          <Route path="/app/discover" element={<h1>Problem discovery</h1>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading problem details");
    expect(await screen.findByRole("alert")).toHaveTextContent("Catalogue unavailable");
    expect(screen.getByRole("link", { name: /back to discovery/i })).toHaveAttribute("href", "/app/discover");
  });

  it("shows an explicit state when a problem has no evidence rows", async () => {
    vi.stubGlobal("fetch", detailFetch({
      count: 0,
      next: null,
      previous: null,
      results: [],
    }));
    render(
      <MemoryRouter initialEntries={[`/app/problems/${problem.id}`]}>
        <Routes><Route path="/app/problems/:problemId" element={<ProblemDetailPage />} /></Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: /no evidence sources are attached/i })).toBeInTheDocument();
  });

  it("does not render an untrusted non-HTTPS source URL as a link", async () => {
    vi.stubGlobal("fetch", detailFetch({
      count: 1,
      next: null,
      previous: null,
      results: [{ ...source, source_url: "javascript:alert(1)" }],
    }));
    render(
      <MemoryRouter initialEntries={[`/app/problems/${problem.id}`]}>
        <Routes><Route path="/app/problems/:problemId" element={<ProblemDetailPage />} /></Routes>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { name: problem.title });
    expect(screen.getByRole("heading", { name: source.source_title })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /water access in rural districts/i })).not.toBeInTheDocument();
  });

  it("shows independent evidence and similarity failures", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/sources/")) return Promise.reject(new Error("Evidence unavailable"));
      if (url.includes("/similar/")) return Promise.reject(new Error("Similarity unavailable"));
      return Promise.resolve(jsonResponse(problem));
    }));
    render(
      <MemoryRouter initialEntries={[`/app/problems/${problem.id}`]}>
        <Routes><Route path="/app/problems/:problemId" element={<ProblemDetailPage />} /></Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Evidence unavailable")).toBeInTheDocument();
    expect(await screen.findByText("Similarity unavailable")).toBeInTheDocument();
  });
});
