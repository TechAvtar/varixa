# Verixa Testing and QA

## Test layers

### Unit
Test:
- hashing
- metadata normalization
- evidence rules
- confidence calculations
- text normalization
- fingerprinting
- timeline construction

### Integration
Test:
- DB repositories
- storage
- provider adapters
- complete image pipeline
- complete text pipeline

### API
Test:
- authentication
- validation
- authorization
- status transitions
- error responses

### E2E
Playwright:
- signup/login
- image upload
- text analysis
- report viewing
- report export
- deletion

## Golden dataset

Create a local test dataset containing:
1. normal camera image
2. edited JPEG
3. image with metadata removed
4. image with known C2PA
5. screenshot
6. synthetic/generated image samples
7. recompressed image
8. simple manipulated image
9. normal human-written text
10. AI-assisted text samples
11. duplicated/near-duplicated text
12. source-matching text samples

Do not hardcode vendor-specific detector expectations as permanent truth.

## Evidence tests
For every evidence rule:
- positive case
- negative case
- boundary case
- conflicting evidence case

## Provider tests
Use mocks for normal CI.
Keep provider integration tests separately gated because they cost money and can change.

## Regression rule
Any change to evidence scoring requires:
- updated unit tests
- updated explanation expectations
- changelog entry

## QA checklist
- no console errors
- no broken loading states
- no inaccessible controls
- no unauthorized data
- no raw secrets
- no stale report data
- deletion works
- provider failure does not destroy successful evidence
