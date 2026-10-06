# Threat model (initial)

This is a living document for Phase 0+. Detailed controls are specified in
PROJECT_PLAN.md §13 and DATA_AND_API_SPEC.md.

## Assets

- Meeting audio objects
- Transcripts and structured insights
- Auth tokens and service credentials
- User identity and meeting ownership links

## Top threats

| Threat | Mitigation direction |
| --- | --- |
| Cross-user meeting access via guessed IDs | Server-side owner checks; return 404 |
| Public or guessable storage paths | Private bucket; random keys; signed URLs |
| Secrets in frontend or repo | Server-only env vars; secret scanning |
| Malicious uploads | MIME/size/duration limits; ffprobe validation |
| Prompt injection in transcripts | Treat transcript as data; schema + evidence validation |
| HTML injection in UI | Render with `textContent`; sanitize exports |
| Stale signed URLs after delete | Short TTL; delete storage objects on meeting delete |

## Out of scope for MVP

- Formal penetration test report
- Compliance certifications
- Meeting-platform bot capture
