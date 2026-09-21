# Verixa Architecture

## Architecture

```text
Browser
  |
  v
Next.js Web
  |
  v
FastAPI
  |
  +--> PostgreSQL
  +--> Private Object Storage
  +--> Analysis Services
          |
          +--> Metadata Engine
          +--> C2PA Engine
          +--> Fingerprint Engine
          +--> Forensics Engine
          +--> Text Engine
          +--> AI Provider Adapters
          +--> Search Provider Adapters
          +--> Evidence Engine
          +--> Report Engine
```

## Repository

```text
verixa/
├── apps/web/
├── services/api/
├── packages/shared-types/
├── infra/
├── docs/
└── TASKS/
```

## Backend modules

```text
services/api/app/
├── main.py
├── config.py
├── api/v1/
├── models/
├── schemas/
├── repositories/
├── services/
│   ├── analysis/
│   ├── image/
│   ├── text/
│   ├── provenance/
│   ├── ai/
│   ├── search/
│   ├── evidence/
│   └── reports/
├── providers/
├── workers/
└── utils/
```

## Rules
- Controllers/routes orchestrate only.
- Services own business logic.
- Repositories own persistence.
- Providers own external API integration.
- Schemas define external contracts.
- Models define persistence.
- Evidence records should remain traceable to raw observations.
- Provider-specific fields must not leak into core domain models when avoidable.

## Processing model
Start with a job-oriented architecture even if MVP executes some jobs synchronously.

Every analysis has:
- queued
- processing
- completed
- failed

Each processing step should be independently identifiable.

## Provider abstraction

```python
class AIDetector(Protocol):
    async def analyze(self, content: bytes, metadata: dict) -> DetectionResult: ...

class SourceSearchProvider(Protocol):
    async def search_image(self, content: bytes) -> list[SourceMatch]: ...

class TextSourceProvider(Protocol):
    async def search(self, text: str) -> list[TextSourceMatch]: ...
```

Never call a provider directly from an API route.

## Failure isolation
If one provider fails:
- retain all successful evidence
- record provider failure
- mark that evidence category unavailable
- do not fail the entire analysis unless a core local step fails

## Idempotency
Use content SHA-256 and provider/model/version to cache safe repeatable operations where possible.
