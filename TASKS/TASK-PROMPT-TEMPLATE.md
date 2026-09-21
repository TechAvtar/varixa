# Claude Code Task Prompt

Use this template for every implementation task.

## Context
You are working on Verixa. Read:
- README.md
- relevant architecture/spec files
- existing source code
- existing tests

## Objective
Implement the requested task without changing unrelated architecture.

## Required process
1. Inspect existing code.
2. Identify affected modules.
3. Create/update tests first where practical.
4. Implement the smallest production-ready solution.
5. Add migration if schema changes.
6. Run formatter/linter/type checks/tests.
7. Fix failures.
8. Update documentation if behavior changed.

## Quality requirements
- typed code
- input validation
- authorization
- safe errors
- no secret logging
- no raw-content logging
- deterministic behavior where possible
- provider abstraction
- evidence traceability

## Completion response
Return:
- summary
- files changed
- tests run
- migration details
- environment variables added
- known limitations
- recommended next task
