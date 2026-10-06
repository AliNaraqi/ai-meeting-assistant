# Optional integrations (Phase 8)

Shipped in this repo:

| Capability | How |
| --- | --- |
| Shareable meeting pages | `POST /api/v1/meetings/{id}/share-links` → public `/share/{token}` |
| Calendar metadata import | `POST /api/v1/meetings/from-ics` with ICS text |
| Slack / Notion / task CSV exports | `POST .../exports` with `format=slack\|notion\|actions_csv` |
| Template catalog | `GET /api/v1/templates` |
| Tab/system audio capture | New-meeting checkbox → `getDisplayMedia` (browser-dependent) |

Still deferred (by design for portfolio scope):

- Multi-user team workspaces and RBAC
- Live OAuth writes into Notion/Slack/Linear
- Real-time streaming transcription
