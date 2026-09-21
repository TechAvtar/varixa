# T010-IMAGE-UPLOAD.md

## Objective
Build secure image upload endpoint and UI. Validate file type, magic bytes, size, dimensions, and store original privately. Calculate SHA-256.

## Instructions
Use `TASKS/TASK-PROMPT-TEMPLATE.md` and all relevant specification files.

Before implementation:
- inspect current repository state
- identify dependencies
- identify security/privacy implications
- identify DB changes

After implementation:
- run tests
- run lint/type checks
- update documentation
- do not implement unrelated features

## Acceptance criteria
- feature works end-to-end where applicable
- errors are handled
- authorization is enforced
- tests cover core behavior
- no secrets are committed
- no private content is logged
- implementation matches Verixa evidence principles
