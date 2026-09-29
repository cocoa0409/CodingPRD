# Worklog — task_2872_independent_sales_organization_residual_accounting

## Step 1: Create task directory — 2026-09-05T09:45:40.821Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2872_independent_sales_organization_residual_accounting/` and `.../workspace/`. Index 2872 was pre-assigned by the invoker; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T11:38:00.000Z

Done — all three scaffold artifacts for task 2872 are complete and lint-clean.

### Output (`tasks/task_2872_independent_sales_organization_residual_accounting/`)

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2,636 | 144,495 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1,626 | 106,713 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4,705 | 322,880 |

### Contents

- **SCAFFOLD.yaml** (§1.0–§1.7 only, no design keys): 11 entities, 6 state machines (`parallel` shape), 3 `concurrency_rules`, 11 calculations, 61 endpoints, 54 validations in 13 priority bands, 53 errors, 4 roles (IsoAdmin / ResidualAnalyst / ResidualController opaque + Agent `entity_backed:Agent`, `segregation_of_duties`). Complexity layers: optimistic_concurrency, dual_variant_calculation, cascading_side_effects, rate_threshold_triggers; consistency `immediate`.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (single key `scaffold_difficulty_design`): 9 rule_ids / 20 instances.
- **SCAFFOLD_CORNER_DESIGN.yaml** (single key `scaffold_corner_design`): 82 instances across all nine `section:` values — entities 11, state_machines 19, calculations 15, validations 13, endpoints 5, errors 6, rbac 4, cross_cutting_complexity_layers 8, consistency_model 1. 68 carry full `test_recipe`s; 14 are `excluded_because` stubs (no `test_recipe`) citing §1.8 instances that exist by name.

### Verification run

- `scaffold_lint.py`: **clean lint** — 1,131 calls scanned across §1.8+§1.9, all conform to §1.5, all §1.1 FKs reverse-reachable.
- All three files parse as YAML; `scaffold_difficulty_design` / `scaffold_corner_design` appear only as the sole top-level key of their own file and never inside `SCAFFOLD.yaml`.
- **All 53 declared error ids** are triggered or stub-mapped across §1.8+§1.9 (0 uncovered).
- **All 61 endpoints** are exercised by at least one call (added `GET /residual-lines`, `GET /residual-batches`, `GET /processor-programs` to close the last three gaps).
- Every declared calculation is grounded, and each of the 6 declared `algorithm` types has a matching `claim_type` instance (added an `aggregation` instance, `batch_totals_are_round_then_sum_and_survive_a_recall_and_an_append`, which pins 11978-not-11979 and 17967-not-17968 via the exact 4.5-cent buy-rate rounding split).
- Instance names unique across the union of both design files; no stub has a `test_recipe`.
- Forbidden concurrency vocabulary swept: removed the one "simultaneously" in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` line 787 ("is both un-issued AND worth only 32 cents").

### Notes for the orchestrator

1. `SCAFFOLD.yaml` line 8 still contains the verbatim directive line `Generate task harder than expert level!` inside the `scenario:` block, because the scenario was specified as verbatim. **Strip that single line before Step 3** so it cannot reach `PRD.md`.
2. Work completed this session: the `errors`, `rbac`, `cross_cutting_complexity_layers` and `consistency_model` sections plus the `aggregation` calculation instance. Two lint fixes were needed along the way — a hardcoded `expected_statement_version: 999` (replaced by a genuinely-stale captured `${sv2}`, with the setup extended so an analyst proposal bumps the version first) and an OCC/payload mismatch resolved earlier.

**Orchestrator follow-up applied:** per the known difficulty-directive leak, the line `Generate task harder than expert level!` was stripped from `SCAFFOLD.yaml`'s `scenario:` block immediately after this step. `grep -rn "harder than expert"` over the whole task dir now returns nothing, so the directive cannot reach PRD.md.

## Step 3: Copy shared files — 2026-09-05T11:39:06.499Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). All three scaffold YAMLs re-verified as parseable with the expected top-level keys.

## Step 4: Generate PRD — 2026-09-05T11:51:57.861Z

PRD generated at `workspace/PRD.md` — **478 lines / 99,127 characters**, built in 8 incremental appends (no single-Write truncation risk). The document ends at a genuine boundary: the last section is **`## 5. Error Code Catalogue`**, closing on its final table row `| `ERR_CLAWBACK_REVERSAL_EXCEEDS_CLAWBACK` | 409 |`.

Structure (domain-derived, not copied from the example): §1 three-paragraph introduction; §2 with ten subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Resource Identity/Versioning, 2.5 The Cent Convention, 2.6 The Logical Clock, 2.7 OCC on the Three Guarded Writes, 2.8 The Order in Which a Request Is Refused, 2.9 Derived Totals/Cascades/Compensating Reversals, 2.10 Nested Paths and Reverse-Reachability); §3 with nine lifecycle-and-money-flow subsections; §4 endpoint table (61 rows, 4 columns); §5 error table (53 rows, 2 columns).

Hard Contract reports:

```
Field coverage check:
- entities[].fields: 102 required, 102 present, 0 missing
- endpoints[].request_body: 64 required, 64 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 54 checked, 54 expressed in prose (13 ordered bands in §2.8, plus the two
  ordering call-outs: state-before-segregation on approve, state-before-shape on restructure), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_agent_version /
  expected_merchant_version / expected_statement_version + ERR_STALE_*_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 24 checked, 24 fully expressed (ResidualBatch 4, AgentStatement 6 across two
  parallel dimensions, StatementAdjustment 5 with the INFO_REQUESTED loop, Merchant 3, Agent 4 incl. the
  DEPARTED self-loop, AgentAdvance 2 auto-transitions), 0 missing
- calculations[]: 11 checked, 11 fully expressed in prose with pinned rounding order and all 13 constants
  embedded in business context, 0 missing
- validations[] conditions: 54 checked, all 53 error ids matchable to a condition in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 38 endpoints with side effects checked, 38 expressed, 0 missing
- entities[].fields[] structured content: 102 checked, defaults / initial values / enum sets / range
  constraints reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (NET_REVENUE_SPLIT vs GROSS_SPLIT; PERCENT_OF_RESIDUAL vs
  STRAIGHT_LINE_AMORTIZATION; DRAFT vs ISSUED net-payable variants; the two chargeback filters;
  profit_cents vs agent_basis_cents; the three equipment-proration branches; hold/release/settle;
  approve/reject), all with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 885
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Notes worth relaying:
- §2.2 was appended by `cat`-ing `section-2.2-response-structure.md` directly and verified byte-identical with `diff`.
- The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no sibling task directory was read.
- One scaffold internal inconsistency was resolved toward the majority: `ERR_PERIOD_LOCKED`'s §1.6 blurb says reverse is blocked only by a `FINALIZED` statement, while §1.4 priority 11 and the `POSTED → REVERSED` precondition both say `ISSUED` **or** `FINALIZED`. The PRD states `ISSUED` or `FINALIZED` for both post and reverse.
- `POST /agent-statements/{id}/adjustments` is scoped in the entity table to client-proposable `DISPUTE_CREDIT`/`MANUAL_DEBIT`, yet the endpoint description and `ERR_CLAWBACK_REVERSAL_EXCEEDS_CLAWBACK` both admit a proposed `CLAWBACK_REVERSAL`. Since no error code exists for "proposed a system-only kind", the PRD validates the full five-value `kind` enum plus sign discipline plus the reversal ceiling, and separately states that `BONUS_CLAWBACK`, `CLAWBACK_REVERSAL` and `VESTED_BUYOUT` are the kinds the system's own cascades create already `APPLIED`.

**Orchestrator truncation check (per the known doc-generator failure mode):** independently verified — `wc -l` = 478, final heading is `## 5. Error Code Catalogue` at line 420, and the file's last line is a complete markdown table row. Not truncated; no regeneration needed. Also grepped PRD.md for `harder than expert`, `scaffold_difficulty`, `scaffold_corner`, `test_recipe` — zero hits, so neither the difficulty directive nor the withheld design indices leaked.

## Step 5: Generate unit tests — 2026-09-05T12:40:39.000Z

Test generation for task 2872 is complete.

### Output

**`test_helpers/`** (2,184 lines, unchanged from Stage 1)
`__init__.py` 43 · `api_client.py` 260 · `api_errors.py` 121 · `assertions.py` 355 · `constants.py` 86 · `factories.py` 221 · `fixtures.py` 724 · `test_users.py` 51 · `types.py` 323

**`test_suite/`** — 40 (conftest) + 10,469 lines of tests, **138 tests**

| file | lines | tests | queue |
|---|---|---|---|
| conftest.py | 40 | — | — |
| test_01_normalization_variants_and_rounding.py | 180 | 4 | A |
| test_02_posting_cascade_and_profitability.py | 180 | 4 | A |
| test_03_statement_issue_and_recoupment.py | 256 | 6 | A |
| test_04_batch_and_statement_loops.py | 170 | 4 | A |
| test_05_compensating_reversals.py | 153 | 4 | A |
| test_06_attrition_departure_and_minimums.py | 273 | 6 | A |
| test_07_refusal_precedence.py | 241 | 6 | A |
| test_08_cross_entity_gates_and_windows.py | 310 | 6 | A |
| test_20_entity_records_and_defaults.py | 839 | 11 | B |
| test_21_lifecycle_state_machines.py | 1125 | 24 | B |
| test_22_cascades_and_period_locks.py | 1211 | 18 | B |
| test_23_profitability_and_allocation_math.py | 957 | 6 | B |
| test_24_advance_and_statement_math.py | 664 | 5 | B |
| test_25_window_and_shape_validations.py | 823 | 7 | B |
| test_26_fiscal_and_state_validations.py | 746 | 6 | B |
| test_27_endpoint_projections_and_visibility.py | 1170 | 13 | B |
| test_28_access_control.py | 675 | 4 | B |
| test_29_optimistic_concurrency_and_thresholds.py | 496 | 4 | B |

### Design coverage

- Queue A (§1.8): **20/20 instances covered, 0 skipped** — 40 tests (two per instance: the depth assertion plus its control/divergence half).
- Queue B (§1.9): **68/68 non-stub instances covered, 0 skipped** — 98 tests. The 14 stub instances that carry no `test_recipe` (4 `calculations`, 6 `errors`, 4 `cross_cutting_complexity_layers`) are by construction redirects to named §1.8 instances and correctly get no test of their own.
- **Total design instances skipped for PRD-filter failure: 0.**

### Verification run

- `python3 -m py_compile` clean over all 9 helper modules and all 19 test modules.
- All 18 test modules import successfully with `PYTHONPATH` at the task root, so every `from test_helpers import (...)` name resolves; an AST sweep confirms every `api_client.<method>` referenced exists on `ApiClient`.
- Tag audit: 138 tests / 138 `Design:` lines, each the last line of its docstring, exactly one per test, every tag resolving to a real instance name in the correct yaml; no duplicate test names within any module.
- Citation audit: every test carries at least one verbatim >=8-word PRD substring (whitespace-normalised literal match against `workspace/PRD.md`).
- No stray `test_helpers/` or `test_suite/` under `workspace/`; nothing written into `workspace/`; `__pycache__` cleaned up.

### Repairs made during the final audit

- Six subagent-authored docstrings in `test_20`, `test_23`, `test_24` cited PRD text that had been stitched from multiple spans (joined by "and"/"Separately,"/"rounds the same way:") and was therefore not grep-survivable. Each was replaced with the actual verbatim PRD sentence(s), split into separate blocks where they come from different paragraphs.
- Two deliberate, PRD-driven deviations from the difficulty design recipes:
  - `batch_ingest_overlap_and_duplicate_checksum_...`: the recipe's overlapping payload used `period_month: 2026-08` with `coverage_start: 2026-07-15`, which violates the §11 window-shape rule ("`coverage_start` must fall inside the accounting month") and would legitimately return `ERR_COVERAGE_WINDOW_INVALID` before the overlap check. Changed to `period_month: 2026-07`, preserving the band-11-over-band-12 assertion.
  - `batch_post_gated_by_processor_program_status`: the recipe asserts `gross_allocation_cents == 14643`, but its own setup books no chargebacks, so the PRD derives basis 40939 - 0 - 3900 = 37039 and 0.45 x 37039 = 16667.5 -> **16668**. The test asserts the PRD-derived value.
- Also from earlier in the run: `/statement-adjustments` has no PRD-documented `kind` filter, so `test_06` counts adjustment kinds client-side instead of using the design's query parameter.

## Step 6: Generate implementation — 2026-09-05T12:31:05.000Z

The implementation is complete and verified.

### Deliverable

`workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | `PORT` (default 10000), binds `0.0.0.0`, guarded pip install, `exec python3 app.py` (foreground) |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 62 | Flask app, 9 blueprints, `before_request` auth, `ApiError`/`HTTPException`/`Exception` handlers |
| `store.py` | 183 | PRD constants, in-memory `Store` (11 empty dicts), logical clock, `stamp_new`/`touch`/`ordered` |
| `apierrors.py` | 69 | 53-entry error-id -> HTTP-status table, `fail()` |
| `envelope.py` | 76 | meta/response_type/data envelope, pagination, shared list filters |
| `auth.py` | 51 | header auth, role authz, the 11 Agent-scope operations |
| `shapes.py` | 139 | band-4/5 coercion and domain checks |
| `serial.py` | 226 | 13 serializers (field order pinned) |
| `calc.py` | 624 | normalization, allocation waterfall, minimum true-up, advance recoupment, vesting, clawback, attrition cascade, statement recompute |
| `routes_clock.py` | 22 | clock control |
| `routes_programs.py` | 104 | 6 endpoints |
| `routes_agents.py` | 285 | 9 endpoints |
| `routes_merchants.py` | 290 | 11 endpoints |
| `routes_batches.py` | 238 | 9 endpoints |
| `routes_ledger.py` | 72 | 6 endpoints |
| `routes_statements.py` | 168 | 9 endpoints |
| `routes_adjustments.py` | 229 | 8 endpoints |
| `routes_advances.py` | 207 | 4 endpoints |

3054 lines total, 18 Python modules. `python3 -m py_compile *.py` -> COMPILE OK. `__pycache__` removed.

### Endpoint count

`app.url_map` dumps exactly **61 endpoints**, matching the 61 endpoint rows in `SCAFFOLD.yaml` one-for-one.

### Verification

- Fresh boot on a high port: all 11 collections return `total_count 0`, clock at the mandated `2026-08-01T00:00:00.000Z`, `api_request_id` matching `req_<20 uppercase alnum>`. Nothing is seeded, and storage is Python dicts only (no sqlite, no file I/O, no /tmp cache).
- Roughly 70 smoke assertions across five scripts now pass: envelope shape, auth/authz/Agent-scope refusals, pagination bounds, the three coverage-window shapes, overlap vs touching windows, duplicate checksum/MID/line, program mismatch, batch recall/post/reverse cascades, period lock, `ERR_BATCHES_NOT_POSTED`, issue -> finalize -> settle, hold/release with the residual-hold interlock, `ERR_BELOW_MIN_PAYOUT`, the full adjustment review loop (review -> request-info -> resubmit -> approve/reject), segregation of duties, sign discipline, clawback-reversal ceiling, attrition->hold cascade at 2500 bps, reactivation reversal, notice/depart/vesting, transfer-portfolio, advance funding/restructure/exposure ceiling, and all three OCC 412s.
- One real bug was found and fixed this round: the attrition cascade bumped a statement's `version` twice when it both booked a `BONUS_CLAWBACK` and moved the same statement to `HELD`. `apply_hold_cascade(agent_id, already_touched)` in `calc.py` now skips rows the same write already touched, so every successful mutation bumps each row exactly once.
- The FAIL lines in the intermediate smoke runs were all script defects, confirmed against the PRD: one re-issued a statement whose batch was legitimately still unposted, and one passed the same principal id as both proposer and approver, so `ERR_SEGREGATION_OF_DUTIES` was correct. Re-run with distinct principals, every one passes.
- Both smoke ports (51873, 49337) are confirmed free; servers were killed by `lsof -ti :<port>` PID only, never with a broad `pkill`.

**Orchestrator layout check:** `test_helpers/` and `test_suite/` are both at the task root (no strays under `workspace/`), 18 test modules / 138 tests, and `workspace/implementation/` holds 18 modules plus `start.sh` and `requirements.txt`. Steps 5 and 6 were launched in a single assistant message, so the impl generator could not see `test_suite/` (it did not exist at its spawn time).

## Step 7: Run tests and iterate — 2026-09-05T13:01:44.598Z

Clean. `worklog.md` untouched (mtime 12:41, predates my run); no stray files added.

**Iterations run:** 2 (one diagnostic sweep, one fix, one verification sweep).

**Tests deleted:** none. No test failed STEP 1a (PRD coverage) or STEP 1b (unique derivability).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. No implementation defect was found — the sole failure was a test-artifact defect, so STEP 3 was never reached.

**Fixes applied to `test_suite/`:**
- `test_suite/test_29_optimistic_concurrency_and_thresholds.py`, local helper `_percent_advance` inside `test_occ_agent_version_guards_advance_funding` — the helper passed `funded_on="2026-08-01"` as an explicit keyword *and* forwarded `**overrides`, so the test's own later call `_percent_advance(second_version, funded_on="2026-08-02")` raised `TypeError: create_percent_advance_payload() got multiple values for keyword argument 'funded_on'` before any request was issued. Rewrote the baseline as a dict updated by `overrides` (the same pattern the module's sibling helper `_board_merchant` already uses).

**Diagnostic trace for that one failure:**
- STEP 0: identical deterministic `TypeError` in all 8 rounds — a Python-level crash in the test body, not an API response.
- STEP 1a: the asserted rule is verbatim in PRD §2.7 — *"`POST /agents/{id}/advances` requires `expected_agent_version` ... If it does not equal that agent's current `version`, the funding request is rejected with `ERR_STALE_AGENT_VERSION` (HTTP 412)."*
- STEP 1b: uniquely derivable — a pure equality test against the parent's current `version`; no divergent PRD-faithful reading exists.
- STEP 2: TEST IS WRONG at the Python level. The fix makes the test *more* faithful — it previously could not reach its own assertions at all. No assertion was weakened, relaxed, skipped or xfailed; the exact `error_id` + 412 checks and every version/exposure/row-count assertion are unchanged.

**Evidence — final sweep, per-round `passed/total` read from the 8 `results.$i.json` files:**

| round | passed/total | failed | errors |
|---|---|---|---|
| 1 | 142/142 | 0 | 0 |
| 2 | 142/142 | 0 | 0 |
| 3 | 142/142 | 0 | 0 |
| 4 | 142/142 | 0 | 0 |
| 5 | 142/142 | 0 | 0 |
| 6 | 142/142 | 0 | 0 |
| 7 | 142/142 | 0 | 0 |
| 8 | 142/142 | 0 | 0 |

Union of failing tests across all 8 rounds is empty, so there is no flakiness signal either. Note for the orchestrator: the artifact was already in very good shape — 141/142 on the first sweep with the single failure being a test-side crash, meaning the generated implementation needed no changes at all.

**Orchestrator independent verification (per the known "subagent claims a clean sweep with no artifacts" failure mode):** re-read all 8 `workspace/implementation/results.$i.json` directly — all exist, ~45.8 KB each, mtime 12:55 (i.e. written by the final sweep, not stale), and every one reports `passed=142 total=142 failed=0 errors=0`. Also grepped `test_suite/` + `test_helpers/` for `pytest.mark.skip` / `pytest.mark.xfail` — zero hits, so the green sweep was not bought with skips.

**Step 8 skip decision:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; Step 7 ran 2 iterations and applied 1 `test_suite/` fix, so Step 8 is spawned. Because that single fix was a pure Python `TypeError` in the test body — not evidence of any PRD silence or PRD/impl mismatch — a byte-identical `PRD_FINALIZED.md` is the legitimate expected outcome here, and Step 9 will do the substantive work.

## Step 8: Finalize PRD — 2026-09-05T13:03:00.000Z

`workspace/PRD_FINALIZED.md` created as a **byte-identical copy** of `PRD.md`. No edit is warranted — and I am stating that plainly rather than manufacturing one.

**Line counts:** PRD.md 478 -> PRD_FINALIZED.md 478 (0.0% delta, md5 `045b999a84ad8e8e59b89fa8b758c0a1` for both).

**Change list:** none.

**Verification actually performed on the single `<step_7_diff>` item** (subject: OCC-on-advance-funding, `expected_agent_version` / `ERR_STALE_AGENT_VERSION`):

(a) Subject identified: the behavior the repaired test exercises — the version guard on `POST /agents/{id}/advances`, plus every assertion the test could not previously reach (agent version bump on success, no bump on refusal, `advance_outstanding_cents` stacking, zero `AgentAdvance` rows left by a 412, and the `funded_on`-related window rule the fixed keyword feeds).

(b) Impl paths enumerated and read:
- `implementation/routes_advances.py:72-149` (`fund_advance`) — OCC at line 111 is a pure `!=` equality against `agent["version"]`, placed after the band-6 agent lookup (107-109) and before the band-9 `status != "ACTIVE"` check (116-117); `touch(agent)` at 148 only on the success path.
- `implementation/routes_advances.py:51-63` (`_check_window`) and `:168-207` (`restructure_advance`, the parallel caller of the same window/cap helpers).
- `implementation/store.py:156-177` (`stamp_new`, `touch`) — version starts at 1, `+1` per mutation, refused calls mutate nothing.
- `implementation/apierrors.py:24` — `ERR_STALE_AGENT_VERSION` -> 412.
- Grepped the whole workspace for `expected_agent_version` / `ERR_STALE_AGENT_VERSION` to confirm no second callsite exists.

Cross-checked against PRD: §2.7 line 118 states the field, the 412 and the error id verbatim; §2.7 line 122 pins it as "a pure equality test against the parent's current `version`... priority band 8 — after the addressed resource has been confirmed to exist ... but before any state precondition"; §2.8 band 8 agrees; §3.6 line 271 pins the success-path effects ("`advance_outstanding_cents` rises by the principal and its `version` is bumped"); §2.4 line 90/94 pins version semantics (start at 1, +1 per mutation, funding an advance bumps the agent). §3.6 line 267's three-part window rule matches `_check_window` clause for clause, including `first_recoupment_month >= ` the calendar month of `funded_on`. Every choice the impl makes here is already uniquely determined by PRD.md.

(c) Wording adjustment: none — no edit was made, because there was no PRD silence or PRD/impl divergence to pin. The Step 7 item was a Python-level `TypeError` (duplicate `funded_on` keyword in a test-local helper) that prevented the test body from issuing any request; it is a pure test-artifact defect, with zero implementation fixes, zero test deletions and zero `test_helpers/` fixes in the diff.

**Orchestrator note:** a byte-identical `PRD_FINALIZED.md` is the legitimate expected result for this Step 7 diff (0 impl fixes / 0 deletions / 0 test_helpers fixes). The identity check that *does* matter is Step 9's — `PRD_COMPLETED.md` must not come back byte-identical, since that would mean the full impl scan never ran. Step 9 is therefore being run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`, with only pass 1 performing the `cp`.

## Step 9: Complete PRD — 2026-09-05T13:38:09.863Z

Run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 did the `cp`; passes 2 and 3 were explicitly forbidden from copying, so neither could clobber its predecessors). Rationale: a single subagent scanning 18 impl modules + a 478-line PRD in one context has historically produced a byte-identical `PRD_COMPLETED.md` — i.e. the scan silently never ran.

**Aggregate: source 478 lines / 99,446 chars -> PRD_COMPLETED.md 479 lines / 125,957 chars (+1 line, +26,511 chars, +26.7%). 56 edits total: 45 ambiguity-pins, 11 mismatch-revisions.** Line count barely moves because every patch is an in-paragraph insert or sentence-level revision — no new sections, no new paragraphs.

### Pass 1 — cross-cutting / infrastructure (app.py, auth.py, envelope.py, apierrors.py, store.py, serial.py, shapes.py, routes_clock.py)

479 lines / 107,110 chars (+7,664). 11 ambiguity-pins, 2 mismatch-revisions across 13 edits:

- §2.1 auth — revise — ambiguity — empty header value counts as absent; auth never verifies an `Agent`'s `X-User-ID` names a real agent row; auth precedes routing, so an unauthenticated call to an undefined path is 401 not 404 — `auth.py:11-18`, `app.py:40-43`
- §2.1 scope — insert — ambiguity — split the eleven scoped ops into the two that compare the path `{id}` directly versus the nine that must resolve a resource first — `auth.py:31-51`
- §2.2 `api_request_id` — revise — ambiguity — `req_` + exactly 20 chars from `A-Z0-9` — `store.py:49-51`
- §2.2 `api_request_timestamp` — revise — **mismatch** — read from the logical clock, not host wall time — `envelope.py:13-14`
- §2.2 error format — insert — **mismatch** — undefined path -> `ERR_INVALID_REQUEST` at **404**, undefined method at **405** (not the 400 §5 pairs with that id), trailing slash accepted, no 5xx ever — `app.py:26,51-58`
- §2.3 pagination — insert — ambiguity — `limit`/`offset` must be optionally-signed digit runs; `limit=`/`abc`/`10.0` all 400; past-the-end offset returns an empty page with a real `total_count` — `envelope.py:31-49`
- §2.3 ordering — insert — ambiguity — tiebreak on shared `created_at` is server insertion sequence — `store.py:181-183`
- §2.4 versioning — revise — ambiguity — `updated_at` = current logical instant + (`version` - 1) ms, evaluated after the increment; version 1 => `updated_at == created_at` — `store.py:156-178`
- §2.5 percentages — insert — ambiguity — pct fields are JSON numbers in shortest exact form (`0.35`, never a string) — `serial.py:7-10`
- §2.6 clock — insert — ambiguity — accepted `current_utc` forms, sub-ms truncated to 3 digits, unparseable -> 400 with clock unchanged — `routes_clock.py:13-22`, `store.py:54-74`
- §2.8 band 3 — insert — ambiguity — band 3 fully precedes band 6 only for the two path-id checks and four list-filter checks — `routes_adjustments.py:44-47,167-179`, `routes_ledger.py:67-71`
- §2.8 band 4 — insert — ambiguity — `Content-Type` unenforced; absent/empty body = empty object; explicit `null` == omitted; undeclared fields ignored; ints reject bools and `25.0` — `shapes.py:10-98`
- §2.8 band 5 — insert — ambiguity — only a string month reaches band 5 — `shapes.py:101-130`
- §2.10 filters — insert — ambiguity — exact case-sensitive match, conjunctive, wrong-cased enum returns empty page, unknown params ignored, filter before paginate — `envelope.py:69-76`
- §3.2 portfolio snapshot — insert — ambiguity — those ten fields are the whole payload — `serial.py:58-72`

Verified with no change needed: all 53 error ids in `apierrors.py` match §5 statuses *and row order*; all 13 serializers' key sets are PRD-named; every `authorize(...)` set matches the §4 role table; all 15 `store.py` constants match the §3 narrative. Left un-pinned: JSON key order, `threaded=False`/`PORT`, exact error `message` wording (§2.2 already declares it free text).

### Pass 2 — money engine and ledger/batch flow (calc.py, routes_batches.py, routes_ledger.py)

479 lines / 112,196 chars (+5,086). 10 ambiguity-pins, 3 mismatch-revisions across 13 edits:

- §3.7 — insert — ambiguity — minimum true-up and advance recoupment are evaluated **exactly once, by the issue**; a later recompute of an `ISSUED`/`FINALIZED` statement carries both forward unchanged (no double-recoupment); a `DRAFT` recompute forces both to 0 — `calc.py:238-240`
- §3.6 — insert — ambiguity — an advance whose take is <= 0 is left completely untouched: no `months_recouped` increment, no `version` bump, not among the takes a recall compensates — `calc.py:341-342`
- §3.7 — revise — **mismatch** — PRD claimed "at most one such line can exist"; pinned that when two posted batches of the month both carry a line for the merchant, the **earliest by `created_at`** is read — `calc.py:265-274`
- §3.7 — insert — ambiguity — the minimum-fee share uses the **live `split_pct`** at issue time, not the allocation's frozen `applied_pct`, with **no vesting scaling** even for a `DEPARTED` agent — `calc.py:299`
- §3.5 — insert — ambiguity — post cascade bump counts: a pre-existing statement bumps **exactly once** per post regardless of allocation count; a statement the post created is **not bumped at all** — `calc.py:549-553,476-507`
- §3.5 — insert — ambiguity — reversal bumps each affected statement exactly once and leaves all pricing fields intact (reversal unwinds posting, not pricing) — `calc.py:561-581`
- §3.4 — insert — ambiguity — normalization bumps **every processed line's `version`** plus the batch's — `calc.py:396-413`
- §3.4 — insert — ambiguity — recall bumps every line again plus the batch, gated **only** by `NORMALIZED` — neither program suspension nor the period lock applies — `calc.py:417-427`, `routes_batches.py:203-210`
- §3.4 — insert — ambiguity — line-append band-12 order: program suspension -> duplicate line -> program mismatch — `routes_batches.py:164-171`
- §3.4 — insert — ambiguity — on ingest, suspension is evaluated **before** checksum uniqueness within band 12 — `routes_batches.py:99-106`
- §2.10 — revise — **mismatch** — the path parent resolves before any **body foreign key**, but the request-shape band still precedes both — `routes_batches.py:146-155`, `shapes.py:10-16`
- §3.5 — insert — ambiguity — a tier that pays nothing and withholds nothing creates **no statement** — `calc.py:485-487`
- §3.8 — insert — ambiguity — system-generated adjustments carry `reason` = `System-generated <kind>` with null `approved_by_user_id`/`info_request_note` — `calc.py:373-388`

Left un-pinned: `vesting_pct_at_clock` returning 0 for an absent `vesting_start_date`, `minimum_fee_reconciliation` on a missing agent, `build_profitability` on a missing merchant, and `advance_recoupment_schedule`'s None fallbacks — all unreachable given band-4/5/7 validation, so pinning them would document behavior the API cannot exhibit. All remaining arithmetic (buy-rate normalization rounding order, equipment proration, the two divergent bottom lines, the differential override waterfall, the aggregate 50% cap, straight-line final-instalment absorption, bonus clawback, the departure buyout's two roundings, attrition bps) was already uniquely pinned.

### Pass 3 — entity lifecycle routes (routes_programs, routes_agents, routes_merchants, routes_statements, routes_adjustments, routes_advances — 47 endpoints)

479 lines / 125,957 chars (+13,761). 24 ambiguity-pins, 6 mismatch-revisions across 30 edits. Highlights:

- §2.6 — revise — **mismatch** — `first_recoupment_month` is compared to the calendar month of the supplied `funded_on`, so `funded_on` is never clock-bounded — `routes_advances.py:56,82`
- §2.8 band 4 — insert — **mismatch** — three carve-outs where explicit `null` is NOT omission: `parent_agent_id` (detaches), `recoupment_pct`, `amortization_months` (clear) — `routes_agents.py:150`, `routes_advances.py:186-189`
- §2.8 band 5 — revise — **mismatch** — `ERR_INVALID_PERIOD_MONTH` covers an advance only at funding; restructure enforces month shape in band 4 as `ERR_INVALID_REQUEST` — `routes_advances.py:177-179`
- §3.2 — insert — **mismatch** — monotonicity is re-tested on the parent edge *and every child edge* on every amendment, even edges the write did not move — `routes_agents.py:55-70,174`
- §3.2 — insert — **mismatch** — explicit-null `parent_agent_id` detaches to depth 0; descendants' `hierarchy_depth` is rewritten with **no** version/`updated_at` bump — `routes_agents.py:150,183-186`, `calc.py:171-178`
- §3.3 — revise — **mismatch** — an unknown `new_agent_id` on reassignment is band-7 `ERR_REFERENCED_AGENT_NOT_FOUND`, not `ERR_AGENT_STATE_INVALID`; self-reassignment succeeds — `routes_merchants.py:227-241`
- §3.6 — insert — **mismatch** — restructure does not re-apply the band-5 range check, so a negative pct is stored as supplied and only the 0.5 cap binds — `routes_advances.py:168-207`
- §3.9 — revise — **mismatch** — transfer: target existence is band-7 `ERR_REFERENCED_AGENT_NOT_FOUND` reported *ahead* of the `DEPARTED` precondition, while non-ACTIVE or self-target is band-12 `ERR_TRANSFER_TARGET_INVALID`; the response body is the *departing* agent — `routes_agents.py:259-285`
- Plus 22 ambiguity-pins covering: program band-4 rate ceilings, precondition-free idempotent suspend/reinstate that still bump `version`, agent band-12 order (cycle -> depth -> monotonicity) and band-5 order (`split_pct` before `override_pct`), no-op PATCHes that still bump, activation/attrition/reactivation check order, chargeback `amount_cents <= 0` as band-4 ahead of band-5 month shape, advance `principal_cents <= 0` as band-4 vs `recoupment_pct == 0` as band-5, issue bumping the statement once despite two recompute passes, recall reporting the authoring dimension first (opposite of hold/settle), `source_merchant_id` resolved in band 7 then discarded to null for non-merchant kinds, the adjustment's own state consulted before its parent statement, parent-statement check (band 9) preceding segregation of duties (band 10), **no segregation of duties on rejection** (the proposer may reject their own adjustment), `hold_reason`/`info_request_note` min length 1 with no max, settle's four conditions in exact order, `paid_on` never clock-bounded, and departure/transfer version bookkeeping.

**Handoff item 1 (from pass 1) — resolved:** §2.10's filter inventory now records that `GET /statement-adjustments` accepts `agent_id` alongside `statement_id`, `source_merchant_id`, `kind` and `state`, with pinned join semantics — the server collects the ids of every statement whose `agent_id` equals the value, then keeps adjustments whose `statement_id` is in that set; a value matching no statement yields an empty list, not an error; available to all four reading roles and conjunctive with the other four.

**Handoff item 2 (from pass 2) — resolved:** §3.3's attrition-cascade closing sentence is now an explicit one-bump-per-row-per-write rule with three cases: (a) a pre-existing statement hit by both the `BONUS_CLAWBACK` adjustment and the attrition hold advances `version` exactly once, not twice — the hold cascade skips rows the clawback branch already touched; (b) a statement the clawback branch newly *created* stays at `version` 1 with `updated_at == created_at` even after `settlement_state = HELD` and `hold_reason = PORTFOLIO_ATTRITION_THRESHOLD` are written; (c) every other swept statement bumps once.

Left un-pinned: `vesting_start_date` is not bounded against the clock on agent create/amend (PRD silent, negligible interpretive risk, and the vesting arithmetic is pass 2's partition).

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` is **479 lines / 125,957 chars vs the 478 / 99,446 source — `cmp` confirms NOT byte-identical** (52 changed lines), so the scan demonstrably ran. This was the one identity check that mattered.
- Tail intact: the file still ends inside `## 5. Error Code Catalogue` on the complete row `| ERR_CLAWBACK_REVERSAL_EXCEEDS_CLAWBACK | 409 |`; all five `## ` sections present and in order; no pass truncated the document.
- Leak check: grepped `PRD_COMPLETED.md` for `harder than expert`, `SCAFFOLD`, `test_recipe`, `worklog` — zero hits.
- `find`-checked that no file under `implementation/`, `test_suite/` or `test_helpers/` has an mtime after the 12:55 green sweep, so the 8x 142/142 evidence still describes exactly the artifact on disk. Steps 8 and 9 touched only the PRD variants.

## Pipeline complete — 2026-09-05T13:38:09.863Z

All nine steps done. Final state: 3 scaffold YAMLs; `test_helpers/` (9 modules, 2,184 lines) and `test_suite/` (18 test modules + conftest, 142 collected tests) at the task root; `workspace/` holding `INSTRUCTION.md`, `PRD.md` (478 lines), `PRD_FINALIZED.md` (byte-identical, legitimately), `PRD_COMPLETED.md` (479 lines / 125,957 chars, 56 pins), `implementation/` (18 Python modules + `start.sh` + `requirements.txt`, 61 endpoints, 3,054 lines), `sweep.sh`, and `results.{1..8}.json` all reporting 142/142.
