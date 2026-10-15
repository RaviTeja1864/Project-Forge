import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  EvidenceSource,
  Paginated,
  ProblemStatement,
  SimilarProblems,
} from "../types";

function formatSector(sector: string) {
  return sector || "Sector not specified";
}

function isSafeSourceUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password;
  } catch {
    return false;
  }
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function ProblemDiscoveryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryString = searchParams.toString();
  const query = searchParams.get("q") ?? "";
  const sector = searchParams.get("sector") ?? "";
  const difficulty = searchParams.get("difficulty") ?? "";
  const dateFrom = searchParams.get("source_date_from") ?? "";
  const dateTo = searchParams.get("source_date_to") ?? "";
  const parsedPage = Number(searchParams.get("page") ?? "1");
  const page = Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1;
  const [searchText, setSearchText] = useState(query);
  const [reloadKey, setReloadKey] = useState(0);
  const [data, setData] = useState<Paginated<ProblemStatement> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setSearchText(query);
  }, [query]);

  useEffect(() => {
    if (searchText.trim() === query) return;
    const timeout = window.setTimeout(() => {
      const next = new URLSearchParams(queryString);
      if (searchText.trim()) next.set("q", searchText.trim());
      else next.delete("q");
      next.delete("page");
      setSearchParams(next);
    }, 350);
    return () => window.clearTimeout(timeout);
  }, [query, queryString, searchText, setSearchParams]);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams(queryString);
    if (!params.has("page")) params.set("page", "1");
    setLoading(true);
    setError("");

    api.get<Paginated<ProblemStatement>>(`/problems/?${params}`, {
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setError(getErrorMessage(requestError, "The problem catalogue could not be loaded."));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [queryString, reloadKey]);

  function updateFilter(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("page");
    setSearchParams(next);
  }

  function changePage(nextPage: number) {
    const next = new URLSearchParams(searchParams);
    if (nextPage > 1) next.set("page", String(nextPage));
    else next.delete("page");
    setSearchParams(next);
  }

  function clearFilters() {
    setSearchText("");
    setSearchParams({});
  }

  const hasFilters = Boolean(query || sector || difficulty || dateFrom || dateTo);

  return (
    <section className="discovery-page">
      <header className="discovery-heading">
        <div>
          <span className="eyebrow">PROBLEM CATALOGUE</span>
          <h1>Find a problem worth solving.</h1>
          <p>Explore real-world challenges with traceable source material behind every entry.</p>
        </div>
        {data && <span className="catalogue-total">{data.count} sourced {data.count === 1 ? "problem" : "problems"}</span>}
      </header>

      <form className="discovery-filters" role="search" onSubmit={(event) => event.preventDefault()}>
        <label className="discovery-search">
          <span>Search problems and evidence</span>
          <input
            type="search"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            placeholder="Search titles, descriptions, publishers..."
            aria-label="Search problems and evidence"
          />
        </label>
        <label>
          <span>Sector (exact)</span>
          <input
            value={sector}
            onChange={(event) => updateFilter("sector", event.target.value)}
            placeholder="Any sector"
            aria-label="Filter by sector"
          />
        </label>
        <label>
          <span>Difficulty</span>
          <select
            value={difficulty}
            onChange={(event) => updateFilter("difficulty", event.target.value)}
            aria-label="Filter by difficulty"
          >
            <option value="">Any difficulty</option>
            <option value="unspecified">Not specified</option>
            <option value="beginner">Beginner</option>
            <option value="intermediate">Intermediate</option>
            <option value="advanced">Advanced</option>
          </select>
        </label>
        <label>
          <span>Source published from</span>
          <input
            type="date"
            value={dateFrom}
            onChange={(event) => updateFilter("source_date_from", event.target.value)}
            aria-label="Source publication date from"
          />
        </label>
        <label>
          <span>Source published to</span>
          <input
            type="date"
            value={dateTo}
            onChange={(event) => updateFilter("source_date_to", event.target.value)}
            aria-label="Source publication date to"
          />
        </label>
        <button
          className="button button-secondary clear-filters"
          type="button"
          onClick={clearFilters}
          disabled={!hasFilters && page === 1}
        >
          Clear filters
        </button>
      </form>

      {loading && (
        <div className="loading-card" role="status">
          <span className="spinner" /> Loading the problem catalogue...
        </div>
      )}

      {error && (
        <div className="error-card" role="alert">
          <p>{error}</p>
          <button className="button button-secondary" onClick={() => setReloadKey((key) => key + 1)}>
            Try again
          </button>
        </div>
      )}

      {!loading && !error && data?.results.length === 0 && (
        <div className="catalogue-empty">
          <span className="eyebrow">{hasFilters ? "NO MATCHING PROBLEMS" : "NOTHING PUBLISHED YET"}</span>
          <h2>{hasFilters ? "No problems match these filters." : "The catalogue is waiting for its first sources."}</h2>
          <p>{hasFilters
            ? "Adjust or clear the filters to see other source-backed problems."
            : "Problem statements appear here after source material has been ingested and checked. No sample problems are shown."}</p>
          {hasFilters && <button className="button button-secondary" onClick={clearFilters}>Clear filters</button>}
        </div>
      )}

      {!loading && !error && data && data.results.length > 0 && (
        <>
          <div className="problem-grid">
            {data.results.map((problem) => (
              <article className="problem-card" key={problem.id}>
                <div className="problem-card-meta">
                  <span className="problem-sector">{formatSector(problem.sector)}</span>
                  <span className="problem-source-count">
                    {problem.evidence_source_count} {problem.evidence_source_count === 1 ? "source" : "sources"}
                  </span>
                </div>
                <h2><Link to={`/app/problems/${problem.id}`}>{problem.title}</Link></h2>
                <p>{problem.description}</p>
                <div className="problem-card-footer">
                  <span>Difficulty: {problem.difficulty === "unspecified" ? "Not specified" : problem.difficulty}</span>
                  <Link to={`/app/problems/${problem.id}`} aria-label={`View evidence for ${problem.title}`}>
                    Explore evidence <span aria-hidden="true">↗</span>
                  </Link>
                </div>
              </article>
            ))}
          </div>
          {(data.previous || data.next) && (
            <nav className="pagination" aria-label="Problem catalogue pages">
              <button className="button button-secondary" disabled={!data.previous} onClick={() => changePage(page - 1)}>
                Previous
              </button>
              <span>Page {page}</span>
              <button className="button button-secondary" disabled={!data.next} onClick={() => changePage(page + 1)}>
                Next
              </button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}

export function ProblemDetailPage() {
  const { problemId = "" } = useParams();
  const [problem, setProblem] = useState<ProblemStatement | null>(null);
  const [sources, setSources] = useState<Paginated<EvidenceSource> | null>(null);
  const [similar, setSimilar] = useState<SimilarProblems | null>(null);
  const [sourcePage, setSourcePage] = useState(1);
  const [problemLoading, setProblemLoading] = useState(true);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [similarLoading, setSimilarLoading] = useState(true);
  const [problemError, setProblemError] = useState("");
  const [sourcesError, setSourcesError] = useState("");
  const [similarError, setSimilarError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setProblem(null);
    setProblemLoading(true);
    setProblemError("");
    api.get<ProblemStatement>(`/problems/${problemId}/`, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setProblem(result);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setProblemError(getErrorMessage(error, "Problem details could not be loaded."));
      })
      .finally(() => {
        if (!controller.signal.aborted) setProblemLoading(false);
      });
    return () => controller.abort();
  }, [problemId, reloadKey]);

  useEffect(() => {
    const controller = new AbortController();
    setSources(null);
    setSourcesLoading(true);
    setSourcesError("");
    api.get<Paginated<EvidenceSource>>(
      `/problems/${problemId}/sources/?page=${sourcePage}`,
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted) setSources(result);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setSourcesError(getErrorMessage(error, "Evidence sources could not be loaded."));
      })
      .finally(() => {
        if (!controller.signal.aborted) setSourcesLoading(false);
      });
    return () => controller.abort();
  }, [problemId, reloadKey, sourcePage]);

  useEffect(() => {
    const controller = new AbortController();
    setSimilar(null);
    setSimilarLoading(true);
    setSimilarError("");
    api.get<SimilarProblems>(`/problems/${problemId}/similar/`, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setSimilar(result);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setSimilarError(getErrorMessage(error, "Similar problems could not be loaded."));
      })
      .finally(() => {
        if (!controller.signal.aborted) setSimilarLoading(false);
      });
    return () => controller.abort();
  }, [problemId, reloadKey]);

  if (problemLoading) {
    return <div className="page-state" role="status"><span className="spinner" /> Loading problem details...</div>;
  }

  if (problemError || !problem) {
    return (
      <div className="page-state">
        <p className="form-error" role="alert">{problemError || "This problem is not available."}</p>
        {problemError && <button className="button button-secondary" onClick={() => setReloadKey((key) => key + 1)}>Try again</button>}
        <Link className="button button-secondary" to="/app/discover">Back to discovery</Link>
      </div>
    );
  }

  return (
    <section className="problem-detail-page">
      <Link className="back-link" to="/app/discover">← Back to discovery</Link>
      <header className="problem-detail-heading">
        <span className="eyebrow">SOURCED PROBLEM STATEMENT</span>
        <h1>{problem.title}</h1>
        <div className="problem-detail-tags">
          <span className="problem-sector">{formatSector(problem.sector)}</span>
          <span>Difficulty: {problem.difficulty === "unspecified" ? "Not specified" : problem.difficulty}</span>
        </div>
        <p>{problem.description}</p>
      </header>

      <section aria-labelledby="evidence-heading">
        <div className="section-heading problem-sources-heading">
          <div><span className="eyebrow">PROVENANCE</span><h2 id="evidence-heading">Evidence sources</h2></div>
          {sources && <span className="muted">{sources.count} {sources.count === 1 ? "source" : "sources"}</span>}
        </div>

        {sourcesLoading && <div className="loading-card" role="status">Loading evidence sources...</div>}
        {sourcesError && (
          <div className="error-card" role="alert">
            <p>{sourcesError}</p>
            <button className="button button-secondary" onClick={() => setReloadKey((key) => key + 1)}>Try again</button>
          </div>
        )}
        {!sourcesLoading && !sourcesError && sources?.results.length === 0 && (
          <div className="catalogue-empty">
            <h2>No evidence sources are attached.</h2>
            <p>Source metadata is shown only when it is available in the catalogue.</p>
          </div>
        )}

        <div className="evidence-list">
          {sources?.results.map((source) => (
            <article className="evidence-card" key={source.id}>
              <div className="evidence-card-header">
                <div>
                  <span className="eyebrow">{source.source_type.replaceAll("_", " ").toUpperCase()}</span>
                  <h3>
                    {isSafeSourceUrl(source.source_url)
                      ? <a href={source.source_url} target="_blank" rel="noopener noreferrer">{source.source_title} <span aria-hidden="true">↗</span></a>
                      : source.source_title}
                  </h3>
                </div>
                <span className="evidence-publisher">{source.publisher || "Publisher not provided"}</span>
              </div>
              {source.relevant_excerpt
                ? <blockquote><span className="evidence-label">Source excerpt</span>{source.relevant_excerpt}</blockquote>
                : <p className="muted evidence-missing">No excerpt is available for this source.</p>}
              <div className="evidence-card-footer">
                <span>Published: {source.publication_date ?? "Date not provided by source"}</span>
                <span>Retrieved: {new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(source.retrieved_at))}</span>
              </div>
            </article>
          ))}
        </div>
        {sources && (sources.previous || sources.next) && (
          <nav className="pagination" aria-label="Evidence source pages">
            <button
              className="button button-secondary"
              disabled={!sources.previous}
              onClick={() => setSourcePage((value) => value - 1)}
            >
              Previous
            </button>
            <span>Page {sourcePage}</span>
            <button
              className="button button-secondary"
              disabled={!sources.next}
              onClick={() => setSourcePage((value) => value + 1)}
            >
              Next
            </button>
          </nav>
        )}
      </section>

      <section aria-labelledby="similar-heading">
        <div className="section-heading problem-sources-heading">
          <div><span className="eyebrow">TEXT-BASED MATCHES</span><h2 id="similar-heading">Similar problems</h2></div>
          {similar && <span className="muted">{similar.count} candidates</span>}
        </div>
        <p className="similarity-disclaimer">Similarity scores are text-matching signals, not probabilities or proof of duplication.</p>
        {similarLoading && <div className="loading-card" role="status">Checking for similar problems...</div>}
        {similarError && (
          <div className="error-card" role="alert">
            <p>{similarError}</p>
            <button className="button button-secondary" onClick={() => setReloadKey((key) => key + 1)}>Try again</button>
          </div>
        )}
        {!similarLoading && !similarError && similar?.results.length === 0 && (
          <div className="catalogue-empty">
            <h2>No similar published problems found.</h2>
            <p>Only candidates above the configured text-similarity threshold are shown.</p>
          </div>
        )}
        <div className="similar-problem-list">
          {similar?.results.map((candidate) => (
            <article className="similar-problem-card" key={candidate.problem.id}>
              <div>
                <h3><Link to={`/app/problems/${candidate.problem.id}`}>{candidate.problem.title}</Link></h3>
                <p>{candidate.matching_signals.join(" · ")}</p>
              </div>
              <span className="similarity-score" aria-label={`Similarity score ${candidate.similarity_score.toFixed(2)}`}>
                Score {candidate.similarity_score.toFixed(2)}
              </span>
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}
