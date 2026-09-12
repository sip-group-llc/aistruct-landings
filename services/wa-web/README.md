# wa-web

Small private WhatsApp client over Evolution. FastAPI serves the HTML, CSS and JavaScript; no frontend build step.

## Configuration

Required: `EVOLUTION_URL`, `EVOLUTION_APIKEY`, `WA_PASSWORD`. Optional: `EVOLUTION_INSTANCE` (defaults to solaris), `WA_SECRET` (stable value preserves signed sessions across restarts), `TRANSCRIBER_URL`, `TRANSCRIBER_TOKEN`. Keep values in the deployment environment, never in this repository.

Run with uvicorn on port 80; see Dockerfile. The existing service requires HTTPS for its secure cookie. CSS and JS must be included when deploying.

## UI behavior

- Conversations: all, unread, groups, pending and favorites; search normalizes names and formatted numbers.
- Drafts are scoped per contact and stored in sessionStorage. Signing out clears them. Favorites and pending flags are device-local preferences stored in localStorage; opening a conversation never completes a pending item.
- Navigation preserves loaded history and reading position during a tab session. Browser back returns to the conversation list.
- Message search explicitly covers loaded messages and available transcripts, not an indexed global archive.
- Audio has speed controls and optional transcription. Transcripts are cached in bounded server memory and remain in the client conversation cache; server restart clears the server cache.
- Image viewer supports enlarge, fit, download and keyboard dismissal. Received quotes and reactions are displayed when present in the normalized data. Sending is text-only.
- Sending captures the intended recipient, locks duplicate submissions and displays a pending bubble. Unknown outcomes offer verification/copy instead of automatic resending. Delivery/read receipts use returned status only.
- Reading is marked only for incoming messages observed in the visible timeline. The server receives the original message JID/participant. The unread badge is refreshed from the server rather than optimistically reset.

## Pagination and operational limits

`GET /api/messages?jid=...&extra=...` returns up to 50 chronological messages and an opaque `cursor`. Pass the cursor for older messages. Each JID has its own buffered frontier and upstream page number, so old sent messages are not limited to the first sibling page. Retries advance a copy of the saved cursor state.

Cursors are cached in process memory (128 entries, 30-minute validity). Restart, eviction or expiration returns HTTP 410 with a recoverable UI message. Pagination follows upstream page-based history; edits/deletions and new traffic can change that upstream history. Duplicate message IDs are deduplicated.

`POST /api/send` accepts an optional `requestId`. Identical concurrent requests share one operation in the process; conflicting payloads return 409. Cache is bounded to 512 operations and is not durable across restarts. The UI never automatically retries an uncertain send.

`GET /api/session` validates authentication independently of upstream connection and exposes whether transcription is configured. `GET /api/state` checks WhatsApp connectivity. Last successful inbox synchronization is tracked separately in the UI. `GET /healthz` includes a release version.

## Verification

From this directory, run `uv run --with fastapi --with httpx python -B test_app.py`. Six tests use synthetic records and mocked upstream calls: auth/assets, merged chronological pagination, skewed histories, repeated/concurrent send, original read keys/failure, and quote/status/transcript normalization. They never send real messages.

Browser regressions should cover 375 px portrait, 812 px landscape and desktop; double submit; switching chats while older history loads; drafts after navigation/reload; failed read/list requests; search; long text and names; and keyboard navigation. Real mobile keyboards and real media playback need device verification separately.
