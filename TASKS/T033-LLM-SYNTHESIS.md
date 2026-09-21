# T033-LLM-SYNTHESIS.md

## Objective
Implement an LLM evidence-synthesis adapter. Send only structured evidence. Require grounded output, explicit unknowns, conflicts, and evidence references. Never let the model create evidence.

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
