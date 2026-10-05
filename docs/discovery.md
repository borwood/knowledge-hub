# Document discovery and inquiry

The bounded document collection supports the local ingestion and question workflow. Sign in, search by filename or upload ID, optionally choose All/Ready/Processing/Failed, then use **Open document**. The inquiry shows independently retrieved metadata and the two existing question patterns. Failed and processing documents can be inspected; only ready documents can answer. An upload offers **Open uploaded document** and **Show in collection** (clears criteria and returns to newest page 1).

The collection shows at most ten records with result count, page position and Previous/Next buttons. Each record includes filename, UTC timestamp to seconds, readable/exact bytes, full upload ID, ingestion state/failure and synthetic indication. Search submission or state changes reset page 1. A no-match message differs from an empty collection. Retrieval failures have a retry action and are separate from upload outcomes.

**Back to documents** and browser Back restore submitted search, filter, page, scroll and opener focus; Forward retrieves the selected document again. Changing documents or leaving inquiry clears answers and PDF resources. Refresh deliberately returns to newest page 1 with search/filter/selection/answers cleared; persisted documents remain available. History stores only opaque navigation keys: criteria and document IDs stay in memory for the page lifetime, with no localStorage or URL navigation data. Logout/expiry clears protected state and invalidates history. Authentication polling does not refetch the collection or erase criteria.

## Collection HTTP contract

The existing authenticated `GET /documents` without collection parameters retains `{documents:[...]}`. Browser discovery always calls the bounded variant through `/api/documents`:

```text
GET /documents?page=1&page_size=10&q=invoice&state=ready
```

Any of `page`, `page_size`, `q`, `state` opts into `{documents,total,page,page_size,total_pages}`. `page` is a positive integer (default 1); `page_size` is 1..50 (default 10). Out-of-range pages clamp to the last page. An empty result reports page 1 and total_pages 0. Invalid integers, states or oversized queries return 422 with `INVALID_COLLECTION_QUERY`.

`q` is trimmed and limited to 200 characters, matching literal filename or upload-ID substrings. SQLite performs ASCII case folding; other Unicode remains literal. Percent, underscore and backslash have no wildcard meaning. `state` accepts ready/processing/failed; absent/empty selects all. Count and rows use the same bound owner/filter predicate in one SQLite read snapshot. Ordering is created_at descending, then ID descending for ties. SQL counts and LIMIT/OFFSET bound row retrieval; the UI never downloads the legacy full collection. An additive owner/created_at/ID index preserves existing records and schema compatibility.

## Acceptance evidence

`tests/integration/test_collection.py` uses real Keycloak sessions, HTTP and SQLite for 0/1/25/1000 matching owned records, duplicate filenames/timestamps, literal search, filters, page bounds, validation, legacy compatibility and owner isolation. `tests/e2e/test_collection_browser.py` exercises real Chromium on desktop and 375px, keyboard navigation, history/refresh, bounded 1000-record browsing, non-ready states, failures, retry, empty/no-match and delayed collection/detail responses. Existing ingestion, query and PDF regressions remain required.

Bulk fixtures use unique test prefixes and delete only matching test-created IDs in `finally`; no demo record or volume is deleted. Controlled browser interception supplies empty/error/delayed delivery; authorization and scale are also exercised against the actual backend. Observed local API retrievals for 0/1/25/1000 records were 6.1/4.0/4.0/4.4ms on the first green run. These are observations, not a timing SLA. The acceptance bound is returned/rendered record count, with one search submission and one selection sufficient to find a known ID.

No full-text search, document deletion, cloud extraction, arbitrary natural-language generation or deployment is introduced. Legacy no-parameter API callers can still request an unbounded list for compatibility.
