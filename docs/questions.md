# Invoice questions and source evidence

The local upload-to-answer demonstration answers bounded questions. It uses persisted SQLite fields, entity attributes and the invoice-issued-by-vendor relationship. It does not call an LLM, Textract or another cloud service. Only the supplied synthetic invoice is extractable; names, values and confidence scores are invented. This is a local demo, not a production or hosted service.

## Browser demo

Start Compose as described in the README, sign in as Alice, and upload `fixtures/invoice/invoice.pdf`. Choose **Open uploaded document**, or search the collection by filename/ID and use **Open document**. The inquiry carries that exact upload into **Invoice questions**. Ask **What is the invoice total and currency?** to see `USD 125.00`. Open **View total evidence** and **View currency evidence** separately: each renders the authenticated original page and highlights its supporting line. Ask **Who issued this invoice?** to see `Juniper Example Supplies`; vendor evidence also names its relationship ID.

Text below each citation exposes field/entity/relationship IDs, document hash, page/block, normalized bounding box, extraction method and invented confidence. Canvas is supplementary. The PDF.js worker is locked with its package and served locally; no third-party viewer or public storage URL is used. Retry a failed source load or use **Download original PDF**. A source outage does not pretend the page rendered successfully.

Refresh returns to newest page 1 with cleared criteria and inquiry. Search and open the persisted upload again. See [discovery and return behavior](discovery.md). Sign out, confirm Keycloak logout, and sign in as Bob: Alice's uploads and answers must be absent. Bob can upload the same bytes and gets a different document ID. With Bob's authenticated API client, querying Alice's ID returns the same `NOT_FOUND` response as a nonexistent ID. Unsupported valid PDFs remain failed ingestion records and cannot be queried.

Tab/Enter operate the selects, submit and individual evidence buttons. The layout fits 375px screens. Pending/error messages are announced. Changing the document or question clears results and cancels requests. Logout, session expiry/revocation and identity changes clear protected answers and PDF resources; delayed responses cannot restore them.

## GraphQL HTTP contract

POST `/graphql` on the API, or `/api/graphql` through the same-origin browser proxy. Send JSON, the opaque `hub_session` cookie, `Origin: http://127.0.0.1:3000`, and the current `X-CSRF-Token` from `/auth/me`. Never paste real credentials into documentation, issue comments or logs. The browser sends this fixed typed operation:

```graphql
query Answer($id: ID!, $question: InvoiceQuestion!) {
  invoiceAnswer(documentId: $id, question: $question) {
    documentId question text sourceKind
    evidence {
      fieldId entityId relationshipId fieldName value documentSha256
      page blockId boundingBox { left top width height }
      method confidence confidenceKind
    }
  }
}
```

Variables are `{"id":"YOUR_UPLOAD_ID","question":"INVOICE_TOTAL"}` or the same ID with `INVOICE_VENDOR`. Total preserves decimal strings and cites both total and currency. Vendor verifies an invoice-to-vendor relationship and its supporting vendor field. Source kind is `synthetic`; confidence kind is `invented_not_calibrated`, not answer certainty. No arbitrary questions, cross-document joins, generated answers or mutations exist.

Success is HTTP 200 with `data.invoiceAnswer`. Errors return `data: null` and `errors: [{message: CODE, extensions: {code: CODE}}]`, without partial answers or sensitive diagnostics.

| HTTP | Code | Meaning |
| --- | --- | --- |
| 401 | UNAUTHENTICATED | Missing, expired or revoked session; sign in again |
| 403 | CSRF_REJECTED | Origin or CSRF token mismatch |
| 404 | NOT_FOUND | Missing document or different owner, identically |
| 409 | DOCUMENT_NOT_READY | Processing or failed ingestion |
| 422 | MISSING_EVIDENCE | Missing or inconsistent supporting records/provenance |
| 503 | DEPENDENCY_UNAVAILABLE | Database or unexpected resolver failure; retry after recovery |
| 400 | GRAPHQL_VALIDATION_FAILED | Invalid syntax, enum, variables or schema selection |
| 400 | INVALID_REQUEST | Non-object/batch payload or invalid request shape |
| 400 | QUERY_LIMIT_EXCEEDED | Excessive depth/fields, fragments or multiple operations/top-level selections |
| 400 | UNSUPPORTED_OPERATION | Mutation or subscription |
| 405 | POST_REQUIRED | Business query attempted over GET |
| 413 | REQUEST_TOO_LARGE | Body/GET URL exceeds 16 KiB |
| 415 | UNSUPPORTED_MEDIA_TYPE | POST is not JSON |

The transport accepts one query operation with one top-level selection, at most 60 field nodes, depth 6 and 1000 parser tokens. Fragments, batch arrays, WebSocket subscriptions and multipart transports are unsupported. HTTP health queries remain public; they contain no invoice data. All responses use `no-store`. GraphQL errors do not log input query text or variables. The source REST endpoint independently authorizes and verifies original bytes; a temporary source-storage outage can leave the persisted answer available while the viewer reports failure.

## Validation and limits

Run `python scripts/check_frontend.py` and `python -m pytest tests/integration tests/e2e -q` with the README prerequisites and shared Compose runtime idle. `tests/integration/test_answers.py` exercises actual login, persisted facts, relationship traversal, owner isolation, restart, corrupted/missing evidence, malformed/bounded transport, CSRF, session expiry/revocation and database failure. `tests/e2e/test_answers_browser.py` and `test_answer_recovery.py` use actual Chromium for fresh upload/query, all citations, rendered ink and highlight geometry, mobile, keyboard, source retry, refresh and stale-result clearing. Existing auth, ingestion and runtime suites remain required. Browser interception controls delivery timing/failure only; actual HTTP tests establish authorization. Screenshots are in ignored `test-results/`.

PDF coordinates follow the current synthetic adapter's unrotated source-page contract, normalized from the top-left; support for other extraction methods or arbitrary rotated documents needs a separately approved input/normalization contract. No schema migration, cloud extraction, deployment or CI activation is included.
