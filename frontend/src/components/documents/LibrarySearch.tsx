"use client";

import { useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import { librarySearchHitHref, searchAgreementText, type LibrarySearchResult } from "@/lib/librarySearch";
import styles from "./LibrarySearch.module.css";

/** An explicit, unpaid source-text search, separate from the filename filter. */
export function LibrarySearch() {
  const [query, setQuery] = useState("");
  const [searchedQuery, setSearchedQuery] = useState("");
  const [result, setResult] = useState<LibrarySearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const requestId = useRef(0);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = query.trim();
    requestId.current += 1;
    const currentRequest = requestId.current;
    setResult(null);
    setError(null);
    setSearchedQuery("");
    if (text.length < 2 || text.length > 200) {
      setSearching(false);
      setError("Enter between 2 and 200 characters to search agreement text.");
      return;
    }
    setSearching(true);
    try {
      const next = await searchAgreementText(text);
      if (currentRequest !== requestId.current) return;
      setResult(next);
      setSearchedQuery(text);
    } catch (failure) {
      if (currentRequest !== requestId.current) return;
      setError(failure instanceof Error ? failure.message : "Agreement text search failed.");
    } finally {
      if (currentRequest === requestId.current) setSearching(false);
    }
  }

  function changeQuery(value: string) {
    requestId.current += 1; // A response to old wording must never replace newer input.
    setQuery(value);
    setResult(null);
    setSearchedQuery("");
    setError(null);
    setSearching(false);
  }

  const coverage = result?.coverage;
  return <section className={styles.search} aria-labelledby="agreement-text-search-heading">
    <div className={styles.heading}>
      <div><h2 id="agreement-text-search-heading">Search agreement text</h2><p>Find passages across saved PDFs. Local search; no AI call.</p></div>
    </div>
    <form className={styles.form} onSubmit={event => void submit(event)} role="search" noValidate>
      <label className={styles.inputWrap}><Search size={17} aria-hidden="true" />
        <span className={styles.srOnly}>Search agreement text</span>
        <input type="search" value={query} onChange={event => changeQuery(event.target.value)}
          placeholder="Clause, defined term or phrase" minLength={2} maxLength={200} />
      </label>
      <button type="submit" disabled={searching}>{searching ? "Searching…" : "Search text"}</button>
    </form>
    {searching && <p className={styles.feedback} role="status">Searching saved source text…</p>}
    {error && <p className={styles.error} role="alert">{error}</p>}
    {result && coverage && <div className={styles.results} aria-live="polite">
      <div className={styles.resultHeading}>
        <h3>{result.results.length ? `${result.results.length} ${result.results.length === 1 ? "passage" : "passages"} for “${searchedQuery}”` : `No passages for “${searchedQuery}”`}</h3>
        <p>{coverage.scan_truncated
          ? `Scanned ${coverage.documents_scanned} of ${coverage.documents_in_library} agreements; ${coverage.documents_not_examined} were not examined.`
          : `Scanned ${coverage.documents_scanned} ${coverage.documents_scanned === 1 ? "agreement" : "agreements"}.`}
          {coverage.documents_unsearchable > 0 && ` ${coverage.documents_unsearchable} could not be searched.`}
          {coverage.documents_partial > 0 && ` ${coverage.documents_partial} had partial text.`}
          {coverage.results_truncated && " More matches exist; refine the search to see them."}</p>
      </div>
      {result.results.length > 0 && <ol className={styles.list} aria-label="Agreement text results">
        {result.results.map((hit, index) => {
          const href = librarySearchHitHref(hit);
          return <li key={`${hit.document_id}:${hit.source_revision_id}:${hit.passage_id}:${index}`} className={styles.hit}>
            <div className={styles.hitMeta}>
              <p className={styles.filename}>{hit.filename}</p>
              <p>Page {hit.page_number}{hit.source_incomplete ? " · Incomplete extraction" : ""}</p>
              {href ? <Link href={href}>View page {hit.page_number} <span aria-hidden="true">→</span></Link>
                : <span className={styles.unavailable}>Source link unavailable</span>}
            </div>
            <div className={styles.excerpt}><blockquote>{hit.excerpt}</blockquote>
              {hit.excerpt_partial && <p>Excerpt clipped from source passage</p>}</div>
          </li>;
        })}
      </ol>}
    </div>}
  </section>;
}
