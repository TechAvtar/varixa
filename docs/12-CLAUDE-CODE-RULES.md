# Claude Code Rules for Verixa

You are developing Verixa, a production-minded multimodal content forensics SaaS.

## Absolute rules

1. Do not rewrite working architecture without a clear reason.
2. Read relevant files before editing.
3. Never invent APIs, SDK methods, database columns, or provider capabilities.
4. If an external provider is required and credentials are unavailable, implement the adapter interface and a safe mock.
5. Keep provider-specific logic inside `providers/`.
6. Keep business logic inside `services/`.
7. Keep route handlers thin.
8. Use Pydantic schemas for API boundaries.
9. Use SQLAlchemy models and Alembic migrations.
10. Add tests for meaningful behavior.
11. Never expose secrets.
12. Never log raw uploaded content.
13. Never treat AI detection as proof.
14. Never treat missing C2PA as proof of manipulation.
15. Never invent previous versions or history.
16. Preserve raw evidence.
17. Version provider/model outputs.
18. Do not silently discard contradictory evidence.
19. Keep thresholds configurable.
20. Do not add video/audio/mobile/browser-extension functionality during MVP.

## Before coding
- inspect repository
- inspect related module
- inspect tests
- identify dependencies
- identify migration impact
- identify security impact

## After coding
Run:
- formatter
- linter
- type checks
- unit tests
- integration tests where relevant
- build

Fix failures before declaring completion.

## Coding style
Prefer:
- small functions
- typed interfaces
- explicit names
- dependency injection
- clear error types
- deterministic pure functions where possible

Avoid:
- giant service classes
- hidden global state
- duplicated provider logic
- premature abstraction
- magic numbers

## Evidence-specific rule
Do not modify evidence levels simply to make a report look more decisive.

## UI-specific rule
Do not create fake progress.
Do not show unavailable data as if it exists.
Always provide uncertainty/limitation text where appropriate.

## Database rule
Every schema modification requires an Alembic migration.

## Provider rule
Every provider call must record:
- provider
- operation
- model/version if applicable
- status
- latency
- request hash where safe
- estimated cost
- timestamp

## Security rule
Assume all uploaded content is hostile/untrusted.

## Git
Use small commits with meaningful messages.
Do not commit secrets, generated private uploads, local DB files, or credentials.
