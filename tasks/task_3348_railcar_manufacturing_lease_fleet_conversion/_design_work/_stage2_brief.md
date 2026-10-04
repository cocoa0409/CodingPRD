# Shared brief — Stage 2 (queue B: corner translations)

You are translating §1.9 corner instances into pytest tests for one PRD-benchmark task.

Task directory: `/home/ubuntu/github/CodingPRD/tasks/task_3348_railcar_manufacturing_lease_fleet_conversion`

## Read first

1. `/home/ubuntu/github/CodingPRD/skills/prd-bench-unit-test-generator/SKILL.md` IN FULL — especially
   "Stage 2: Generate test_suite/", the "Mandatory PRD citation (C1/C2/C3) + Scaffold citation (C4)"
   rule, the "Silence patterns" rule, and the docstring/tagging requirements.
2. `workspace/PRD.md` — the contract under test.
3. The Stage-1 helpers you must REUSE (never re-invent a setup chain inline):
   `test_helpers/__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`,
   `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (1649 lines, 53 composite fixtures).
4. `test_suite/conftest.py` — already written; it exposes one fixture per role plus `api`.
5. The already-written difficulty tests `test_suite/test_difficulty_*.py` — read one or two to match
   the established style, citation format, and fixture usage.
6. `SCAFFOLD_CORNER_DESIGN.yaml` — your ONLY test source for this queue. It is ~895 KB: do NOT read
   it wholesale. Extract YOUR section's instances programmatically with Python (yaml.safe_load, then
   filter by `section`), and print only the instances you are assigned.

## Your output

One or more `test_suite/test_<section>_*.py` files translating **every non-stub instance** in your
assigned section(s) — exactly one test per instance. Instances carrying `excluded_because:` are
STUBS: they have no `test_recipe` and must NOT produce a test.

## Tagging contract (hard)

Every test's docstring MUST end with one line of the form:
  `Design: Corner/<section>/<instance.name>`
copied verbatim from the source yaml's `name:`. Untagged tests, dual-tagged tests, or tags pointing
to non-existent instances are Stage 2 failures.

## Translation rules

- Each structured `setup_api_calls` entry becomes an `ApiClient` method call inside the test or a
  reused `fixtures.py` helper; `${var}` resolves against earlier `captures:`.
- `trigger` becomes the API call under test; each `assert:` line becomes an assertion.
- Prefer an existing `fixtures.py` composite fixture over an inline chain whenever one matches.
- Where a recipe's asserted literal derives from a PRD formula, RECOMPUTE it from PRD.md's stated
  formula before asserting. If your recomputation disagrees with the recipe's literal, STOP and
  report the discrepancy — do not silently adopt either value.
- **PRD-first filter:** if an instance's asserted rule has no verbatim PRD coverage, or the PRD does
  not uniquely determine the outcome, SKIP it and report why. Do not weaken, do not mark
  skip/xfail, do not emit a placeholder.
- Comments and docstrings must NEVER mention "scaffold", "§1.x", "Table N", or any scaffold label —
  reference only the PRD.

## Clock reachability (mandatory)

The PRD's logical clock starts at `2026-09-01T00:00:00Z` and is driven only via the operator
clock-set endpoint. For every recipe whose dates matter, verify the pinned clock position is
reachable and the asserted dates are consistent with the PRD's date arithmetic from that start.
Flag any recipe whose fixture would need a clock position the PRD's rules cannot produce.

## Known cross-cutting ambiguity — do not re-litigate

An earlier queue found that PRD §3.4/§2.9/§3.9 admit two readings of `capital_allocation_cents`
(capital = live cars × unit_price, vs. the lessor-equity figure). The adopted reading is
**capital = live cars × unit_price**, and `capital_allocation_cents` holds that figure. If one of
your instances asserts the lessor-equity value against `capital_allocation_cents`, treat it as a
recipe bug: assert the adopted reading, and report the instance name so it can be reconciled.

## Output budget — CRITICAL

This endpoint caps output per message and silently truncates oversized tool calls. Write **ONE FILE
PER ASSISTANT MESSAGE**, exactly ONE tool call per message. For a file too large for one message,
Write the first part then Edit-append. Never batch two tool calls into one message.

## Do NOT

- Do not run the test suite — there is no `workspace/implementation/` yet, so tests cannot execute.
- Do not modify `SCAFFOLD*.yaml` or anything under `workspace/`.
- Do not read any sibling `task_*/` directory.

## Before finishing

- Confirm every file AST-parses (`python3 -c "import ast;ast.parse(open(f).read())"`).
- Confirm your `Design:` tags all resolve to real instance names in your section.
- Report: files written with line counts, tests emitted per instance, any skipped instances with
  reasons, and any recipe/PRD literal discrepancy found.
