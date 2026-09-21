# Verixa 6-Week Development Plan

## Week 1 — Foundation
- initialize monorepo
- Next.js app
- FastAPI app
- PostgreSQL
- SQLAlchemy
- Alembic
- authentication
- base UI
- object storage
- analysis entity
- upload endpoint
- dashboard
- CI

Deliverable: user can sign in and create an analysis.

## Week 2 — Image Core
- image validation
- SHA-256
- metadata extraction
- normalized metadata
- C2PA inspection
- pHash/dHash/aHash
- image statistics
- report metadata UI

Deliverable: complete deterministic image analysis.

## Week 3 — Text + AI Providers
- text input
- normalization
- statistics
- text fingerprints
- AI detector adapters
- source search adapters
- provider call logging
- caching

Deliverable: text analysis and external AI signals.

## Week 4 — Forensics
- ELA
- compression
- resampling
- noise
- basic copy-move
- forensic artifacts
- image visualizations
- error isolation

Deliverable: forensic analysis panel.

## Week 5 — Evidence Intelligence
- evidence normalization
- evidence levels
- conflict handling
- timeline
- source/reverse matches
- AI synthesis
- overview report
- compare UI where useful

Deliverable: evidence-based report.

## Week 6 — Production MVP
- PDF reports
- retention
- deletion
- usage limits
- security hardening
- E2E tests
- observability
- landing page
- onboarding
- beta polish

Deliverable: private beta.

## Development sequence
Do not jump directly to the next week if the previous week's acceptance tests are failing.

## Cost control
- local deterministic processing first
- cache provider calls
- use provider adapters
- avoid sending repeated content to LLM
- use cheaper models for classification/synthesis where quality is acceptable
- record estimated cost per analysis
