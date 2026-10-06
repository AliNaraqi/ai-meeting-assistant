# ADR 0001 — AI transcription and extraction provider

- **Status:** Accepted
- **Date:** 2026-08-05
- **Deciders:** Project owner

## Context

The product needs speech-to-text with optional speaker labels, plus schema-valid
meeting intelligence (summaries, decisions, actions, risks, questions) grounded
in transcript evidence. Training custom speech or language models is out of
scope for the MVP.

## Decision

Use OpenAI APIs behind Python provider interfaces:

- Transcription / diarization via the Audio Transcriptions API
- Meeting intelligence via the Responses API with Structured Outputs
- Embeddings (semantic Q&A phase) via a configurable embedding model

Store model names and prompt versions with each job/result. Select concrete
model IDs through environment variables, not hard-coded constants in business
logic. Ship mock providers so CI never spends API credits.

## Consequences

- Fast path to a portfolio-quality demo with strong structured extraction
- Vendor dependency mitigated by `TranscriptionProvider`,
  `MeetingIntelligenceProvider`, and `EmbeddingProvider` protocols
- Operating cost and rate limits must be controlled with auth, quotas, and
  duration caps
- Evaluation fixtures and citation validation are required to keep outputs
  trustworthy
