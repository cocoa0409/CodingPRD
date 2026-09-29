# Worklog — task_2984_temporary_fencing_site_security_rental

## Step 1: Create task directory — 2026-09-06T01:31:40.641Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2984_temporary_fencing_site_security_rental and its workspace/ subdirectory. Index 2984 was pre-assigned by the orchestrating command (no ./tasks/ scan, no auto-allocation) because up to 32 pipelines run concurrently on this host and auto-allocation would collide.

## Step 2: Generate Scaffold — 2026-09-06T03:09:37.869649318Z

Step 2 complete. All three scaffold artifacts are written, parse cleanly, and the linter is green.

## Deliverables

`/home/ubuntu/github/CodingPRD/tasks/task_2984_temporary_fencing_site_security_rental/`

| File | Lines | Top-level keys |
|---|---|---|
| `SCAFFOLD.yaml` | 2697 | `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither `scaffold_difficulty_design` nor `scaffold_corner_design` present |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2482 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4552 | `scaffold_corner_design` only |

Each file ends at a real structural boundary (final `test_user_ids` list item / final `assert` list item), verified with `tail`.

## Counts

- **SCAFFOLD.yaml (§1.0–§1.7):** 11 entities, 6 state machines, 2 concurrency rules, 8 calculations, 26 validations, 46 endpoints, 41 errors, 6 roles. Profile: `api_prefix /fence-rentals`, `difficulty_level expert_plus`, primary `pricing_engine`, secondary `temporal_windowing`, layers `[dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers]`, topology `flat`, shape `parallel`, role model `segregation_of_duties`, consistency `immediate`.
- **§1.8:** 9 rules × 2 instances = **18 instances**.
- **§1.9:** all **9 guide sections**, **70 instances** — entities 11, state_machines 16, calculations 11, validations 9, endpoints 5, errors 7, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1. Of these, 50 carry a full `test_recipe` and 20 are `excluded_because` stubs citing existing §1.8 instances (all 20 references resolve; instance names are unique across the union of both design files).
- All 41 error codes are reachable; the corner file carries a comment block mapping every code to the instance that triggers it.

## Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2984_temporary_fencing_site_security_rental/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2984_temporary_fencing_site_security_rental/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2984_temporary_fencing_site_security_rental/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    46
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  1021

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two lint fixes were needed on this pass: the unauthenticated-header instance used a literal `expected_jobsite_version: "1"` (now a captured `${j1_v}` from a real jobsite while the path keeps the unknown UUID), and I normalised all 18 pre-existing `difficulty_instance:` stub references from the composite `rule_id / instance_name` form to the bare instance `name` the skill spec requires.

## Two things for you

1. **The difficulty directive is still in `SCAFFOLD.yaml`.** Line 8 of the `scenario:` block reads `Generate task harder than expert level!`, because you told me to keep the scenario description verbatim. Per the known leak path (scenario → PRD.md), strip that one line before Step 4.
2. **Housekeeping:** `.scratch/step2/` removed, parent `.scratch/` left in place; `workspace/` and `worklog.md` untouched (I wrote no worklog entry — that stays yours).

**Orchestrator note (post-subagent action):** acted on point 1 immediately — deleted line 8 (`Generate task harder than expert level!`) and its trailing blank line from `SCAFFOLD.yaml`'s `scenario:` block, leaving the scenario starting at `2984. Temporary Fencing & Site Security Rental...`. Re-verified: `grep "harder than expert"` returns nothing, `yaml.safe_load` still yields all 13 top-level keys, file is now 2695 lines. The difficulty directive therefore cannot reach PRD.md via the scenario key in Step 4.

## Step 3: Copy Shared Files — 2026-09-06T03:09:37.880936541Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T03:25:13.521360239Z

Step 4 complete.

## Deliverable

`workspace/PRD.md`

- **Final line count: 433 lines** (95,411 bytes)
- **Last section heading: `## 5. Error Code Catalogue`** — the file ends with the complete final table row `| \`ERR_PAYMENT_EXCEEDS_BALANCE\` | 402/409 |`, a genuine section boundary. No mid-sentence, mid-table, or mid-list truncation.
- Written incrementally: one `Write` + one verbatim `cat` of the fixed §2.2 block + 8 quoted-heredoc appends, with `wc -l` + `tail` verification after every append.

## Section structure

§1 Introduction · §2 Global Specifications (2.1 RBAC, 2.2 verbatim response envelope, 2.3 pagination/ordering, 2.4 identity & version counter, 2.5 money/hours/rounding, 2.6 logical clock & half-open windows, 2.7 the validation ladder, 2.8 stale-version protection, 2.9 four-eyes & customer scoping, 2.10 fleet & ledger conservation, 2.11 reference-data uniqueness) · §3 Business Logic (3.1–3.9) · §4 Endpoint Definitions (46-row table) · §5 Error Code Catalogue (41-row table).

## Coverage self-audit — no gaps

| Dimension | Covered |
| --- | --- |
| Entities | 11 / 11 (all `common_fields` expanded) |
| State machines / transitions | 6 / 6 machines, 37 / 37 transitions (incl. the parallel `lifecycle_status` × `billing_status` contract machine) |
| Concurrency rules | 2 / 2 (`expected_jobsite_version`, `expected_contract_version` → `ERR_STALE_VERSION` / 412 at rung 8) |
| Calculations | 8 / 8, every constant and rounding position stated (quote pricing 13 steps, dual-variant period charge, total rollup, loss assessment, crew labor hours, closure-corridor utilization, cancellation fee, account exposure waterfall) |
| Validations | 26 / 26 rungs, with the explicit strict-ascending, first-violation-wins ordering |
| Endpoints | 46 / 46 |
| Errors | 41 / 41 — each also triggered by a §2/§3 prose rule, not only listed in §5 |
| Roles | 6 / 6 (5 opaque + `CustomerContact` entity-backed to `CustomerAccount`) |

## Hard Contracts

- **Contract 1 — Field-Name Coverage: PASS.** 116 entity fields, 76 endpoint input identifiers, 10 nested JSON keys — all appear in backticks; missing sets all empty (verified by script diffing scaffold-extracted names against every backticked token in PRD.md).
- **Contract 2 — Rule Coverage: PASS.** All 26 rungs, 2 OCC rules, 37 transitions, 8 calculations, every endpoint `side_effects` list, and all field defaults/constraints/initial values expressed in prose.
- **Contract 3 — §3 Path Purity: PASS.** 900 backtick tokens (253 unique) scanned in §3: 0 starting with `/`, 0 bare HTTP methods, 0 method+path pairs. All §3 endpoint references use state-transition, role+verb, or capability framing.

Supplementary: §2.2 block byte-identical to source; 68 enum/state/decision values present verbatim; zero hits for forbidden phrases (`harder than`, `expert level`, `difficulty`, `scaffold`, `test_recipe`, `approximately`, `roughly`, `conservatively`); no audit footer in PRD.md.

## Zero-Silence pins worth flagging to later steps

Where the scaffold was silent I pinned behavior explicitly in prose: `priced_lines` composition; invoice `lines` conventions for all seven line types; `billable_days` stored as the raw whole-day window count (the EVENT 3-day minimum affects only money); rung-9 from-sets for planning/phase-move (`PENDING_MOBILIZATION`|`ACTIVE`), billing runs (`ACTIVE`|`DEMOBILIZING`), and contract cancel (`PENDING_MOBILIZATION`); `RESET` and `phase_from`/`phase_to` rejected with `ERR_VALIDATION` on the generic planning capability; `SUPERSEDES` predecessor relation targeting the most recently created displaced order; quote acceptance past `valid_through_utc` → `ERR_QUOTE_STATE`; `DEMOBILIZING → CLOSED` re-evaluated at the end of any payment, void, or reconciliation finalization; add-on units move `available → deployed` at activation and never occupy `reserved_count`; clock endpoint exempt from header and role checks.

## Safety

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. `SCAFFOLD.yaml`, `worklog.md`, and `workspace/INSTRUCTION.md` are untouched (verified by listing). Scratch lived only in `.scratch/step4/` and I removed exactly that subdir; the parent `.scratch/` survives.

**Orchestrator verification (independent of the subagent's own claims):** `wc -l` = 433 / 95,411 bytes confirmed. Section headings enumerated — the document runs §1 → §5 with §2.1–§2.11 and §3.1–§3.9 all present. Tail inspected: ends mid-nothing, on the complete error-catalogue row `| `ERR_PAYMENT_EXCEEDS_BALANCE` | 409 |` (the subagent's summary wrote the status as `402/409`; the file itself says `409` — cosmetic discrepancy in the summary only). Machine cross-check against SCAFFOLD.yaml: all 41 `error_id`s appear in PRD.md (0 missing) and all 46 endpoint `path`s appear in PRD.md (0 missing); the §5 table has exactly 41 `ERR_` rows. Leak grep for `harder than|expert level|scaffold|test_recipe|difficulty` returns zero hits. PRD is not truncated; no regeneration needed.

## Step 6: Generate Implementation — 2026-09-06T03:55:58.968234685Z

Implementation is complete and verified.

## Modules (all under `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `app.py` | 73 | Flask factory, 6 blueprints, `ApiError`/`HTTPException`/catch-all envelope handlers, `app.run(host="0.0.0.0", port=$PORT)` |
| `store.py` | 92 | in-memory dicts for the 11 collections, logical clock, `new_row`/`touch` housekeeping |
| `errors.py` | 88 | all 41 `error_id`→status pairs from PRD §5, not-found/state maps, `ApiError`/`fail` |
| `validation.py` | 235 | ISO-8601 instant parsing, ordered body-shape checker (unknown keys rejected), pagination/query coercion |
| `envelope.py` | 42 | `meta`/`response_type`/`data` envelope, `req_<20 uppercase alnum>` ids, ms-precision timestamps |
| `calc.py` | 241 | the 8 calculations: tier pricing, quote rollup, labor hours, period charge, invoice rollup, depreciation, loss assessment, cancellation fee |
| `serialize.py` | 209 | the 11 entity projections |
| `services.py` | 547 | identity/roles/scope, aggregates, fleet moves, ledger recompute, invoice issuance, payment waterfall, mobilize/demobilize/close cascades |
| `web.py` | 21 | JSON body parsing + list pagination helper |
| `routes_reference.py` | 352 | clock hook, municipalities, accounts + payments, products, crews, jobsites |
| `routes_quotes.py` | 180 | quote pricing, supersession, issue, accept |
| `routes_permits.py` | 176 | permit draft/submit/decision, corridor cap, lead time, revision rounds |
| `routes_contracts.py` | 306 | conversion, planning, phase moves, cancellation, billing runs |
| `routes_work_orders.py` | 245 | dispatch (gates 10/12/14/15/19/25), completion, abort, cancel |
| `routes_ledger.py` | 199 | invoices, voids, reconciliations, finalize |
| **total** | **3006** | plus `start.sh` and `requirements.txt` |

## Endpoints
**46 declared endpoints wired, exactly matching the PRD §4 table** (47 rules registered including Flask's built-in `/static`). Verified programmatically by diffing `app.url_map` against PRD lines 340–385.

## start.sh contract
`cd "$(dirname "$0")"` first, reads `$PORT` from the environment with no hardcoded port, binds `0.0.0.0`, `exec python3 app.py` in the foreground, `debug=False`/`use_reloader=False`. Confirmed by a cold boot launched from `cwd=/tmp` with `__pycache__` removed — served an empty list on the first request. Flask is only pip-installed when the import fails, avoiding boot contention across 8 concurrent rounds.

## Smoke-test results
Reference path first (municipality create 201 → read-back → list → duplicate code 409 → wrong role 403 → missing headers 401 → unknown id 404 `ERR_MUNICIPALITY_NOT_FOUND`), then two full end-to-end walks covering all 11 entities:

- **Quote pricing** — 600 ft CONSTRUCTION + MESH_70 + 2 gates: 50 panels, tier 47¢/ft, monthly 44740, install labor 89000, permit handling 12500, one-time 120000. 240 ft EVENT: 20 panels, 62¢/ft, monthly 18600, labor 50400.
- **Dispatch** — labor 5.5 h → `scheduled_end_utc` 13:30, 50 panels available→reserved; a visit outside the approved closure window correctly refused `ERR_PERMIT_WINDOW_ELAPSED` (409).
- **Mobilization** — contract ACTIVE/CURRENT, `billing_anchor_utc` set, MOBILIZATION invoice `INSTALL_LABOR 89000 + DELIVERY 18500 + PERMIT_HANDLING 12500 = 130500`.
- **Billing run** — 31 days → RENTAL 49534, tax at 875 bp → 55826.
- **Ledger** — payment waterfall settled the mobilization invoice; overpayment refused in full (`ERR_PAYMENT_EXCEEDS_BALANCE`); void by the issuing identity refused `ERR_SEGREGATION_OF_DUTIES` (403), void by a second AccountManager succeeded and credited back.
- **Reconciliation** — snapshot `[PANEL-6X12:50, GATE-STD:2]`, variant `REPLACEMENT_COST`, damage 26600, FINAL invoice raised; mismatched counts refused `ERR_PANEL_COUNT_MISMATCH`.
- **Cancellation** — EVENT with 24 h notice → 18600/2 + 50400 = **59700**, CANCELLATION invoice issued, account flipped to `credit_hold_flag: true`, cascaded work order CANCELLED with `crew_id` cleared and reservations released; a null-`scheduled_start_utc` reference visit correctly yielded fee 0 and no invoice.
- **Credit hold** — subsequent dispatch refused `ERR_ACCOUNT_CREDIT_HOLD` (402).
- **Conservation** — fleet sums held exactly (`500 = 499+0+0+1+0`, `30 = 29+0+0+1+0`); quote supersession, phase-range/`phase_to == current_phase` (both 409 `ERR_INVALID_PHASE_MOVE`), footage bounds, unknown body field, and `limit=0`/`limit=101` all correct.

Eight status codes initially differed from my *script's* guesses — every one was the script being wrong: the implementation returns 409 for `ERR_BELOW_MINIMUM_TERM`, `ERR_PERMIT_LEAD_TIME_NOT_MET`, `ERR_PERMIT_WINDOW_ELAPSED`, `ERR_BILLING_PERIOD_INVALID`, `ERR_PAYMENT_EXCEEDS_BALANCE`, `ERR_PANEL_COUNT_MISMATCH` and 403 for `ERR_SEGREGATION_OF_DUTIES`, which I re-verified line-by-line against PRD §5 (lines 408–433). **Zero real defects found.**

## Shutdown and hygiene
Both smoke servers were killed **by captured PID** (`kill $PID`, then a port-resolved fallback via `ss -lptn "sport = :$P"`). No `pkill` of any kind was ever run. Post-kill probe returned `000` on a closed port.

No entity data is seeded: `store.py` initialises every collection to `{}`, and a grep for `sqlite3`, `open(`, `json.dump`, `pickle`, `shelve`, `/tmp/` and `.db` across all 15 modules returns nothing — storage is process-local dicts only, so each `start.sh` relaunch starts empty (confirmed by the cold boot returning `total_count: 0`).

I wrote only inside `implementation/` plus my own `.scratch/step6` (now removed; sibling `step5`/`step7` dirs untouched). `worklog.md`, all three `SCAFFOLD*.yaml`, `workspace/PRD.md` and `workspace/INSTRUCTION.md` are intact, and I never read `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single message, so this agent could not have read `test_suite/` — the directory did not exist at its spawn. Step 5 was still running when this entry was written.

## Step 5: Generate Unit Tests — 2026-09-06T04:45:39.237892566Z

Step 5 is complete. All 14 test-suite files and the 9 helper modules are in place at the task root.

## Deliverables (absolute paths)

`test_helpers/`

| file | lines |
|---|---|
| `__init__.py` | 1 |
| `api_client.py` | 267 |
| `api_errors.py` | 115 |
| `assertions.py` | 273 |
| `constants.py` | 316 |
| `factories.py` | 362 |
| `fixtures.py` | 571 |
| `test_users.py` | 107 |
| `types.py` | 209 |

`test_suite/`

| file | lines | tests |
|---|---|---|
| `conftest.py` | 3 | — |
| `test_01_dual_variant_and_combinatorial_pricing.py` | 411 | 4 |
| `test_02_state_machines_and_cascades.py` | 365 | 4 |
| `test_03_validation_priority_and_boundaries.py` | 394 | 8 |
| `test_04_cross_entity_and_temporal_overlap.py` | 479 | 9 |
| `test_05_conservation_invariants.py` | 299 | 4 |
| `test_06_entities.py` | 579 | 11 |
| `test_07_state_machines.py` | 428 | 9 |
| `test_08_calculations.py` | 345 | 4 |
| `test_09_validations.py` | 386 | 6 |
| `test_10_endpoints.py` | 296 | 4 |
| `test_11_errors.py` | 545 | 7 |
| `test_12_rbac.py` | 492 | 5 |
| `test_13_cross_cutting.py` | 307 | 3 |
| `test_14_consistency_model.py` | 121 | 1 |

**79 tests total** (7,671 lines across both dirs).

## Design-index coverage

- **§1.8 (queue A): 18 of 18 non-stub instances translated. 0 skipped.**
- **§1.9 (queue B): 50 of 50 non-stub instances translated. 0 skipped.** The 20 `excluded_because` stubs produce no test; each was verified to cross-reference a real §1.8 instance (stub counts: state_machines 7, calculations 7, validations 3, endpoints 1, cross_cutting 2).
- **No instance failed the PRD-first two-condition filter**, so there are no skips to report and no `skip`/`skipif`/`xfail` markers anywhere in either directory (grep-verified).

## Tag integrity

Machine-verified by loading both YAMLs and matching every tag against the parsed instance names: **79 tests, 79 `Design:` tags, one per test, zero malformed, zero unknown, zero pointing at a stub.** They cover 68 distinct instances — 9 instances are split across two tests and 1 (`Difficulty/cross_entity_state_dependency/dispatch_requires_approved_permit_covering_the_whole_order`) across three, all inside the queue-A files `test_01`–`test_05`; queue B is strictly 1 test : 1 instance.

## PRD-over-design corrections applied

1. `phase_from`/`phase_to` omitted when planning RELOCATION/REMOVAL (PRD §3.5 makes supplying either `ERR_VALIDATION`).
2. `deployed_linear_feet` asserted per its PRD definition (sum over COMPLETED/PARTIAL `DELIVERY_INSTALL` visits).
3. No `committed_closure_linear_feet` value asserted at a clock instant for which the PRD supplies no formula.
4. Dropped the rbac design's "DispatchCoordinator sets the clock → 403 `ERR_FORBIDDEN_ROLE`" trigger: PRD §2.1 and the §4 clock row make the hook exempt from both the auth and role checks.
5. The credit-hold design expects **201** for `POST /accounts/{id}/payments`; PRD §4 says paying returns **200**, so the test asserts 200.

Also corrected against the PRD while writing `test_13`: a `PLANNED` visit carries `completed_linear_feet` **0**, not null (PRD §3.5), so the "refusal left no trace" assertion checks 0.

## Verification run

`python3 -m py_compile` on all 24 `.py` files: clean. `pyflakes`: clean apart from the three intentional fixture re-exports in `conftest.py`. AST checks confirmed every `C.`/`F.`/`FX.`/`U.`/`api.` attribute referenced by the suite exists, and that every call to an `api_client`, factory, fixture or assertion helper binds against its real signature (0 arity problems). No pytest run was attempted (the runner has no `-k` selector; verification belongs to Step 7's sweep).

Paths and isolation: both dirs are directly under the task root (`ls -d` confirmed); `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` — no test dirs leaked, and `workspace/implementation/` was never read or listed. `worklog.md`, `SCAFFOLD*.yaml`, `workspace/PRD.md` and `workspace/INSTRUCTION.md` are untouched. `.scratch/step5` was removed; the parent `.scratch` and its siblings were left alone. `__pycache__` dirs created by the compile checks were cleaned up.

**Orchestrator verification:** independently confirmed `test_helpers/` and `test_suite/` sit at the task root and that `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no leak. `grep -h "^def test_" test_suite/*.py | wc -l` = 79, matching the reported count.

## Step 7: Run Tests and Iterate — 2026-09-06T04:57:27.838758351Z

All 8 rounds clean. Final summary for the worklog:

## Step 7 — Test/Fix Iteration Loop: COMPLETE

**Iterations run: 2** (2 full 8-round sweeps).

Iteration 1 baseline was unusually healthy: **76/79 in all 8 rounds, with only 3 deterministic failures and zero flakiness** — no load-induced noise, no fixture-bug cluster. The known fixture-bug signatures were all checked and all absent: `factories.py` sends money/counts as JSON integers and instants as full ISO-8601 `Z` timestamps, `test_users.py` uses `""` (not `" "`) for blank headers, `api_client.py` already canonicalises instant precision, and `assertions.py` already carries an `assert_unpaginated` variant.

### Tests deleted
None. All three failures were resolved without deleting a test — two by STEP 1c partial-coverage assertion removal, one by an implementation fix.

### Fixes applied to `test_suite/`
Both are STEP 1a **PRD-SILENCE** (field-presence silence) on a work-order field named `completed_at_utc`. The token appears **nowhere in PRD.md** and nowhere in the implementation. PRD §3.6 enumerates exhaustively what a completion report stores — *"Either way the visit stores the reported `completed_linear_feet`, stores the acting `X-User-ID` as `completed_by_user_id`, and advances its `version` by 1"* — and §3.5 enumerates the null fields of a freshly planned visit as *"`abort_reason_code` and `cancel_reason_code` null"*. Neither list contains a completion timestamp. Per STEP 1c the surrounding assertions are all verbatim-covered and were kept; only the uncovered ones were removed.

- `test_13_cross_cutting.py::test_a_refused_completion_leaves_none_of_its_five_side_effects` — removed 2 assertions (`refused["completed_at_utc"] is None`, and `assert_instant(completed["completed_at_utc"], ...)`). The five-hop no-side-effect audit and the full mobilization-cascade assertions are retained.
- `test_14_consistency_model.py::test_every_derived_value_is_visible_in_the_same_response_that_caused_it` — removed 1 assertion (`assert_instant(completed["completed_at_utc"], ...)`). The immediate-consistency audit across contract, product, invoice, account and the derived closure-corridor aggregate is retained.

### Fixes applied to `test_helpers/`
None — no fixture, factory, or role-header bug was found.

### Fixes applied to `implementation/`
- **`routes_contracts.py` / `run_billing()`** — moved the billing-window inversion check from rung 16 to rung 3 and changed its error from `ERR_BILLING_PERIOD_INVALID` to `ERR_VALIDATION`, positioning it after `check_body` but **before** `lookup("contracts", …)` so it also outranks rung 4.
  - **Behavioral choice:** an inverted or zero-length `period_start_utc`/`period_end_utc` pair is a request-shape failure (`ERR_VALIDATION`/400), not a billing-window failure (409). PRD §2.6 states *"Every window submitted to this API must satisfy end strictly after start; an inverted or zero-length window is rejected with `ERR_VALIDATION`"*, and §2.7 rung 3 lists *"when an instant is malformed or a window is inverted"* among the `ERR_VALIDATION` family.
  - **Note for Step 8:** the PRD names this one condition **twice** — at rung 3 (as `ERR_VALIDATION`) and again as the first of the four rung-16 counts (*"`period_end_utc` must be strictly after `period_start_utc`"* → `ERR_BILLING_PERIOD_INVALID`). The strict-ladder rule of §2.7 (*"The first rule whose condition is violated determines the response, and no later rule is evaluated"*) resolves the overlap deterministically in favour of rung 3, which makes rung 16's first count permanently unreachable — so it was removed as dead code. The remaining three rung-16 counts (anchor floor, clock ceiling, no-double-billing floor) are unchanged. **This duplicated condition is the one genuinely under-determined-looking passage in the PRD** and is worth Step 8's attention. The permit endpoints (`routes_permits.py` lines 47 and 123) already handled their closure-window inversion correctly at rung 3; billing was the lone inconsistency.

### Final sweep evidence (iteration 2)
| Round | Passed / Total | Status |
|---|---|---|
| 1 | 79 / 79 | CLEAN |
| 2 | 79 / 79 | CLEAN |
| 3 | 79 / 79 | CLEAN |
| 4 | 79 / 79 | CLEAN |
| 5 | 79 / 79 | CLEAN |
| 6 | 79 / 79 | CLEAN |
| 7 | 79 / 79 | CLEAN |
| 8 | 79 / 79 | CLEAN |

Union of failing tests across all 8 rounds: **0**. The summarizer's `total - passed` cross-check reconciled against the non-passed entry count in every round, so these are real clean rounds and not a schema mismatch.

The 8 passing `results.{1..8}.json` are left in `workspace/implementation/`. Transient `round.*.log`, `sweep.log`, `SWEEP_DONE` and `__pycache__` were cleaned; `.scratch/step7/sweep.sh` and `summarize.py` are intact for later steps. `PRD.md`, `INSTRUCTION.md`, `SCAFFOLD*.yaml` and `worklog.md` were not modified.

**Orchestrator verification (not taken on trust):** re-ran the summarizer against the on-disk artifacts. All 8 `results.$i.json` exist (~23.6 KB each, same mtime 04:53), each reports `passed=79 total=79` with 0 non-passed `tests[]` entries, and `total - passed` reconciles with the entry count in every round — so this is a genuine clean sweep, not a missing-artifact or schema-mismatch false positive. Union of failures across rounds: 0. Step 8 will run (Step 7 applied 1 implementation fix, so the skip condition does not hold).

## Step 8: Finalize PRD — 2026-09-06T05:05:35.818118923Z

`PRD_FINALIZED.md` written. Two targeted edits, both traceable to `<step_7_diff>`.

## Size
- PRD.md: 433 lines / 95,411 bytes
- PRD_FINALIZED.md: 433 lines / 96,030 bytes (+619 bytes, 0 % line delta; ends at `## 5. Error Code Catalogue`, last row `ERR_PAYMENT_EXCEEDS_BALANCE`)
- `diff` shows exactly 2 changed lines (256, 304), nothing lost.

## Changes
- **§3.8 (line 304) — revise — billing-window inversion moved out of rung 16 into rung 3** — the rung-16 list is now three counts (anchor floor, clock ceiling, no-double-billing floor), all still `ERR_BILLING_PERIOD_INVALID`; a `period_end_utc` not strictly after `period_start_utc` is now stated as an `ERR_VALIDATION` rung-3 failure judged right after body-shape integrity and **before** the path contract is resolved, explicitly outranking contract-not-found, contract-state and the billing-window failures — `implementation/routes_contracts.py:277-298` (check at 282-283, `lookup` at 284, state at 285-286, the three remaining rung-16 checks at 290-298).
- **§3.6 (line 256) — insert — a visit has no completion-timestamp field** — the completion report writes `completed_linear_feet`, `completed_by_user_id`, the status move and `version`; the only instant it refreshes on the visit is the housekeeping `updated_at` — `implementation/routes_work_orders.py:199-202`, `implementation/serialize.py:149-170`, `implementation/routes_contracts.py:53-70`.

## Per-edit pre-edit search log

**Edit 1 — subject: rejection of an inverted/zero-length submitted time window and its ladder position.**
(b) Paths enumerated: grepped all of `implementation/*.py` for `_end_utc"] <=`, `strictly after`, `inverted` — exactly three sites: `routes_contracts.py:282` (billing, before `lookup`), `routes_permits.py:47` (`create_permit`, before the `jobsites` FK lookup) and `routes_permits.py:122` (`submit_permit`, **after** the path `lookup` at 118 but before the state check at 124). Also read `BILLING_SPEC` (routes_contracts.py:45-48), `next_billing_floor` (services.py:539-547) to confirm "most recent `PERIODIC` invoice" semantics unchanged, `SUBMIT_SPEC`/`corridor_committed_feet` and permits rungs 13/17/18, and confirmed no generic window rule lives in `validation.py`'s `check_body`.
(c) Adjustment: the "before the path entity is resolved" claim is deliberately scoped with "on this endpoint" / "the path contract", because `submit_permit` checks inversion *after* resolving the permit id (an inverted window on a nonexistent permit yields `ERR_PERMIT_NOT_FOUND`). A generalized rung-3-beats-rung-4 statement would have created a new mismatch at `routes_permits.py:118-123`; §2.6's pre-existing global sentence was left verbatim.

**Edit 2 — subject: what a completion report persists on a work order, specifically timestamp fields.**
(b) Paths enumerated: `complete_work_order` (routes_work_orders.py:179-215), `install_fleet_hop` (162-175), `abort_work_order`/cancel (218+), `new_work_order` row template (routes_contracts.py:53-70), `work_order_out` + `_house` (serialize.py:6-11, 149-170), and a repo-wide grep for `completed_at` (zero hits anywhere in `implementation/`). Confirmed the row carries only `scheduled_start_utc`/`scheduled_end_utc` plus house `created_at`/`updated_at`.
(c) Adjustment: my first wording ("that is the whole of what the report writes onto the visit") was withdrawn — the report also writes `status`, and `reserved_unit_counts` is deliberately *left intact* after completion, so a closed-list claim would have been a false universal. Final wording asserts only the absence of a completion-timestamp field plus the `updated_at` refresh.

Note for Step 9: the §2.7 rung-16 label ("billing-window validity") and the `ERR_BILLING_PERIOD_INVALID`/409 catalogue row are still correct under the three-count reading and were left verbatim.

**Orchestrator verification:** `wc` confirms 433 lines in both files, PRD_FINALIZED.md +619 bytes; `diff` reports exactly 2 changed lines (256 and 304) and nothing else — no dropped content. Both files end on the identical final row `| `ERR_PAYMENT_EXCEEDS_BALANCE` | 409 |`, so PRD_FINALIZED.md is not truncated. PRD.md itself is unmodified.

## Step 9: Complete PRD — 2026-09-06T05:41:20.754046659Z

**Orchestrator decision (recorded per the autonomy directive):** Step 9 was run as **four sequential passes over one shared `PRD_COMPLETED.md`**, rather than as the single subagent the skill's prompt describes. Rationale: a single agent asked to scan a 3006-line / 15-module implementation against a 433-line PRD reliably under-covers, and the documented failure mode is a `PRD_COMPLETED.md` that comes back byte-identical to its source (i.e. the scan never really ran). Partitioning by implementation module bounds each agent's reading load; pass 1 alone performs the `cp` and passes 2–4 are forbidden from repeating it, so no pass clobbers its predecessors. A partitioned pass may not patch prose whose subject another pass owns, so a 4th reconciliation pass adjudicates the deferred cross-partition items — otherwise those findings would be reported and never fixed. Each pass verified the shared file's line/byte count on entry and confirmed its predecessors' hunks survived.

Partition: **P1** = app/store/errors/validation/envelope/web/serialize/routes_reference · **P2** = calc/routes_quotes/routes_permits/routes_contracts · **P3** = routes_work_orders/routes_ledger/services · **P4** = reconciliation + global coherence.

---

### PASS 1 — infrastructure and reference layer

STEP A: `cp workspace/PRD_FINALIZED.md → workspace/PRD_COMPLETED.md` done and verified (source 433 lines / 96,030 bytes, correct final line).

Counts: **ambiguity-pins 14, mismatch-revisions 1** — 16 change sites (15 in-line revisions + 1 new paragraph inside §2.7).

- §2.2 (success envelope) — revise — ambiguity — pinned `api_request_id` as `req_` + exactly 20 chars `A`–`Z`/`0`–`9` — `envelope.py:9,14`
- §2.2 (pagination meta) — revise — ambiguity — pagination meta on list endpoints only; every §4 collection endpoint paginated with `response_type` `"array"`; single-resource `meta` holds just id+timestamp — `envelope.py:19-29`, `web.py:19-21`
- §2.3 ¶1 — revise — ambiguity — non-integer/empty `limit`/`offset` is `ERR_VALIDATION`, validated at rung 3 ahead of filter resolution — `validation.py:186-209`
- §2.3 ¶3 — revise — ambiguity — boolean filters accept only literal `true`/`false`; enum filters must name a declared member; string filters match exactly; **undefined query parameters are ignored, not rejected** — `validation.py:212-235`
- §2.4 ¶1 — revise — ambiguity — `created_at`/`updated_at` come from **real server time, not the logical clock**, strictly increasing system-wide so `created_at ASC` is exact creation order — `store.py:45-57`
- §2.5 ¶3 — revise — **mismatch** — PRD said crew daily capacity is "carried to one decimal place"; impl applies no quantisation and echoes the supplied JSON number verbatim — `routes_reference.py:250`, `serialize.py:77`
- §2.6 ¶1 — revise — ambiguity — clock hook takes exactly one required field `current_utc`, answers 200 with `data` = `{"current_utc": …}`, succeeds even for an unrecognised role — `routes_reference.py:36-40`
- §2.6 ¶2 — revise — ambiguity — pinned the accepted instant grammar and the rejected forms (date-only, missing `T`/`Z`, `+00:00`, lower-case `z`, calendar-invalid, non-string) — `validation.py:13,26-41`
- §2.7 (new paragraph) — insert — ambiguity — unparseable/non-object body fails rung 3, absent body reads as `{}`; booleans never satisfy int/number; int rejects `5.0`; explicit `null` accepted for only `panel_length_ft` and `wind_load_rating_mph` — `web.py:9-16`, `validation.py:58-63,70-112`
- §2.9 ¶2 — revise — ambiguity — customer scope **narrows collection reads silently** (incl. `total_count`) and only raises `ERR_ACCOUNT_SCOPE_VIOLATION` when an identifier filter resolves to another account's row — `routes_reference.py:341-351` + uniform across all five other route modules
- §2.11 ¶1 — revise — ambiguity — product `code` charset unconstrained; length/charset violations are rung-3 ahead of rung-20; `crew_code`/`depot_code`/jurisdiction `name`/`site_label`/`billing_email` carry no uniqueness constraint — `routes_reference.py:49-50,172,197-199`
- §2.11 ¶2 — revise — ambiguity — omitted `wind_load_rating_mph` ≡ null; the three category-shape rules are rung-3 `ERR_VALIDATION`, before the duplicate-code check — `routes_reference.py:188-199`
- §3.1 (aggregate) — revise — ambiguity — `committed_closure_linear_feet` never an accepted input; projected on create, single read and every list row — `routes_reference.py:59-60,81,88,98`
- §3.1 (account) — revise — ambiguity — `billing_email` validated only as a non-null JSON string, no address syntax — `routes_reference.py:107`
- §3.1 (jobsite) — revise — ambiguity — rung-5 order is `customer_account_id` then `municipality_id`, so a doubly-unresolvable body yields `ERR_ACCOUNT_NOT_FOUND` — `routes_reference.py:311-312`
- §4 (payments row) — revise — ambiguity — the payment endpoint answers with the updated **account**, not the invoices it touched — `routes_reference.py:164`

Result: 435 lines / 102,204 bytes. Deferred to reconciliation: app.py's 404/405/500 → `ERR_VALIDATION` at non-400 statuses; `estimated_labor_hours` as JSON float vs §2.5; nested fleet/commitment entry shapes; `store.touch` firing only on real change; cascade-raised not-found errors.

---

### PASS 2 — pricing, quoting, permitting, contract lifecycle

Pre-edit 435 / 102,204 → post-edit 435 / 109,387. All 16 of pass 1's sites verified intact.

Counts: **ambiguity-pins 12, mismatch-revisions 1** (13 edited lines, 14 pins).

- §3.2 — insert — ambiguity — `priced_lines` order pinned (PANEL_RENTAL, WIND_SCREEN when present, ADDON_RENTAL); duplicate `addon_lines[].product_code` neither merged nor rejected, each yields its own line — `calc.py:124-143`
- §3.3 — insert — ambiguity — `terms_acknowledged_by` stored verbatim and echoed on read — `routes_contracts.py:113`
- §3.3 — insert — ambiguity — the panel entry is always element 0 of `fleet_commitments` with add-ons following in quote order (later rules read positionally) — `routes_contracts.py:87-91`
- §3.4 — insert — ambiguity — submission overrides merge field-by-field and §2.6's orientation rule judges the **merged** window; that check precedes the status check, outranking `ERR_PERMIT_STATE` — `routes_permits.py:119-126`
- §3.4 — insert — ambiguity — `required_change_summary` is the *only* field cleared on resubmission; `reviewer_note`, `decided_at_utc`, `revision_round` survive — `routes_permits.py:143-149`
- §3.4 — insert — ambiguity — `DENY` accepts but discards `reviewer_note`; `required_change_summary` stored only by `REQUEST_REVISION`, discarded (not refused) with `APPROVE`/`DENY` — `routes_permits.py:161-173`
- §3.5 — insert — ambiguity — the `phase_from`/`phase_to`/`RESET` refusals are rung-3 body-only and precede rung 4; the footage-vs-contract bound sits after rung 4 and **before** the rung-9 state check — `routes_contracts.py:164-172`
- §3.5 — insert — ambiguity — on a phase move the footage bound is judged **above the rung-8 stale-version check**, so over-long footage beats `ERR_STALE_VERSION` — `routes_contracts.py:183-188`
- §3.5 — insert — ambiguity — `current_phase` is not moved by ordering the move (the `version` bump records participation); it moves only on a full `RESET` completion — `routes_contracts.py:214`
- §3.8 — revise — ambiguity — "most recent `PERIODIC` invoice" = most recently **issued** (issuance sequence, not latest window end) and status-independent: a **voided** `PERIODIC` still bars its window — `services.py:539-547`
- §3.8 — insert — ambiguity — raw day count is elapsed seconds ÷ 86,400 truncated; a sub-day window is legal with raw count 0 → 0-cent construction invoice, while the event variant still charges 3 days against `billable_days` 0 — `calc.py:169-181`
- §3.8 — revise — **mismatch** — the `CURRENT → PAST_DUE` re-evaluation runs before the rollup, so the late fee reads the post-re-evaluation status: a run that itself discovers the first overdue invoice charges the late fee on the very invoice it issues. Version accounting pinned (2 on such a run, else 1) — `routes_contracts.py:303-309`
- §3.9 — insert — ambiguity — `cancel_reason_code` is mandatory but unstored; not copied onto swept visits (whose own `cancel_reason_code` stay null) — `routes_contracts.py:243-263`
- §3.9 — insert — ambiguity — `version` advances by 2 when a fee is charged, by 1 for a free cancellation; a cancelled contract never reaches `CLOSED` — `routes_contracts.py:265-270`

Deferred: the `FENCE_PANEL` literal-zero rate rule; §3.4's "recomputes `committed_closure_linear_feet`" (derived live, not stored); permit creation not touching jobsite `version`; rung-16's internal order (unobservable — same id and status); `billing_anchor_utc` null (unreachable).

---

### PASS 3 — field work, ledger, shared service layer

Pre-edit 435 / 109,387 → post-edit 435 / 116,648. All 29 hunks from passes 1–2 verified intact.

Counts: **ambiguity-pins 13, mismatch-revisions 3.**

- §3.5 — insert — ambiguity — multiple `APPROVED` permits are considered in turn; any one covering the whole interval admits the dispatch, `ERR_PERMIT_WINDOW_ELAPSED` only when none does — `routes_work_orders.py:81-91`
- §3.5 — revise — **mismatch** — dispatch also stores the request's `scheduled_start_utc`, overwriting whatever planning left there — `routes_work_orders.py:149`
- §3.6 — insert — ambiguity — the footage `> 0` bound is rung 3 (outranks rung 4); the `ordered_linear_feet` ceiling is judged after rung 4 and **before** the rung-9 state check, so an over-range report on a non-`SCHEDULED` visit is `ERR_VALIDATION` not `ERR_WORK_ORDER_STATE` — `routes_work_orders.py:181-189`
- §3.6 — insert — ambiguity — completion never empties `reserved_unit_counts`; only abort/cancel clear it — `routes_work_orders.py:162-175` vs `services.py:504-509`
- §3.6 — insert — ambiguity — the partial-install remainder visit is minted **after** the contract transition and its invoice — `routes_work_orders.py:204-209`
- §3.6 — revise — **mismatch** — `deployed_linear_feet` is written **only** at mobilization and never re-derived, so a remainder install leaves it frozen and §3.7 snapshots the frozen figure — `services.py:420` (sole write site)
- §3.6 — insert — ambiguity — the contract carries no permit-fee field; the fee is `one_time_cents − install_labor_cents − 18,500` — `services.py:409-411`
- §3.6 — revise — **mismatch** — mobilization advances `version` by **2**, not 1 (lifecycle mutation + the `NOT_BILLED → CURRENT` money edge) — `services.py:418-422` + `:361`
- §3.6 — insert — ambiguity — the contract-`ACTIVE` gate on removal sits **below** rung 9, fires only on a full report, and never applies to `DELIVERY_INSTALL` — `routes_work_orders.py:188-197`
- §3.6 — insert — ambiguity — the `RESET` phase write is +1 on the contract; a full `RELOCATION` writes nothing and leaves `version` alone — `routes_work_orders.py:210-214`
- §3.6 — insert — ambiguity — `scheduled_*`/`estimated_labor_hours` survive an abort; `completed_*` stay 0/null — `routes_work_orders.py:225-229`
- §3.6 — insert — ambiguity — same schedule-field retention on cancel — `routes_work_orders.py:240-244`
- §3.7 — insert — ambiguity — every `unit_returns[].product_code` resolves at rung 5, ahead of the rung-7 four-eyes and rung-9 state checks — `routes_ledger.py:155-165`
- §3.7 — insert — ambiguity — the three counts need only be JSON integers with no rung-3 bound; the snapshot sum is the sole arithmetic constraint — `routes_ledger.py:25-30`
- §3.7 — insert — ambiguity — variant "present" means *supplied*, content never inspected (empty string counts); each non-zero bucket transition is a separate product mutation (`version` +3/+1/+0); closure runs **after** the `FINAL` issuance, and because that issuance re-opens `SETTLED → CURRENT`, a money-assessing finalization can never close the contract in the same request — `routes_ledger.py:170-198`, `services.py:204-209,309-315`
- §3.8 — insert — ambiguity — a zero-open `ISSUED` invoice absorbs nothing, is not touched, stays `ISSUED` forever and blocks `SETTLED`/`CLOSED` until voided — `services.py:380-381`
- §3.8 — revise — ambiguity — narrowed "billing_status re-evaluated" on a void to the single `→ SETTLED` edge; a void never moves a contract between `CURRENT` and `PAST_DUE` — `services.py:304-307`

Deferred: §2.5 vs the `float` labor-hours projection; §2.10's conservation claim vs `move_fleet`'s unchecked arithmetic; §2.9's scope key identity; `addons_deployed` never resetting.

---

### PASS 4 — reconciliation and global coherence

Pre-edit 435 / 116,648 → post-edit **439 lines / 125,457 bytes**. Section headings byte-identical to `PRD_FINALIZED.md` (28, none added); 49 hunks (up from 45); all sampled pass-1/2/3 markers present.

Verdicts on the deferred items:

- **A — patched.** `app.py:50-63` reachably returns `ERR_VALIDATION` at 404/405, contradicting §4's universal "that identifier's HTTP status from §5". Scoped that promise to declared method+path pairs and pinned the off-contract 404/405 without weakening §5's 400 for declared endpoints. (`json_body()` uses `silent=True, force=True`, so the Werkzeug-400 branch is unreachable; the 500 fallback was not pinned.)
- **B — patched.** Both passes were right. `serialize.py:161` emits `float(hours)`, so `2.00` → `2.0`. Checked every other decimal-hours site (`daily_capacity_hours` already correct; `calc.py:63-66,156-166` the only producer). Separated the quarter-hour *value* rule from JSON *spelling* and disclaimed §3.5's `2.00`/`5.75` illustrations rather than editing them.
- **C — patched; pass 3's mechanism was wrong, a different one is real.** Pass 3's path does not reach a negative `deployed_count`: `deployed_linear_feet` is snapshotted once (`services.py:420`, early return at `:416`), so the snapshot always equals the first install's ceiling and is ≤ accrued. Sum conservation is genuinely exact (`move_fleet` the sole mutator of all five buckets, grep-verified). What *is* reachable: (1) `available_count` negative — add-ons checked at dispatch (`routes_work_orders.py:138-142`) but withdrawn at mobilization (`services.py:425`), so two contracts clear the same stock; (2) `deployed_count` negative — `unit_returns` counts carry no rung-3 lower bound and `move_fleet`'s `count <= 0` guard *skips* rather than reverses; (3) units stranded in `deployed_count` on multi-visit installs. Softened §2.10 to claim only the sum and documented all three.
- **D — patched.** `services.py:121` / `routes_reference.py:133` confirm `X-User-ID` *is* the account id. Stated outright, plus the consequences (unknown identity scopes out silently; permit scoping via jobsite, which §2.9 had omitted).
- **E — no change needed.** Pass 1's §2.11 already pins the exact-0 `unit_monthly_rate_cents` rule; step five (`calc.py:93-97`) iterates `addon_lines` only, which rung 21 forces to non-panel categories, so the panel product cannot reach step five at all.
- **F — patched.** No code path ever touches a municipality row, so combined with §2.4 the "recomputes" wording predicted a jurisdiction `version` bump that never happens. Rewrote both occurrences plus a shorthand disclaimer for §3.4's other "releases footage" phrasings.
- **G — patched.** `services.py:186-192`, `:205-206`, `:280`. "That mutates a row" was ambiguous between "is applied to" and "actually changes"; made the converse explicit with the zero-cent-invoice void as the worked case.
- **H — patched.** `addons_deployed` is written in exactly two places (`routes_contracts.py:106` false, `services.py:421` true) — documented as a write-once latch, including the never-mobilized case.
- **I — no change needed.** The derivation is fully stated in §3.6 and §3.3 states the verbatim copies; no forward reference required.
- **J — pass 2 was right on all three.** Permit creation touches only the permit row (and §3.4, unlike §3.2, claims no jobsite bump). The three `ERR_BILLING_PERIOD_INVALID` checks share id *and* status (`errors.py:34`), differing only in `message`, which §5 never pins. `billing_anchor_utc` null is unreachable in `run_billing`: the lifecycle gate admits only `ACTIVE`/`DEMOBILIZING`, both downstream of the stamp at `services.py:419`.
- **K — no change needed.** Verified every nested key set the API exposes — `fleet_commitments[]`/`reserved_unit_counts[]`/`deployed_snapshot[]` = `{product_code, unit_count}`; `unit_returns[]` = `{product_code, returned, damaged, missing}`; `lines[]`/`priced_lines[]` = `{line_type, product_code, quantity, amount_cents}`; `addon_lines[]` = `{product_code, quantity}`; list `meta` = `{limit, offset, total_count, has_more}` — each already named in §3.3, §3.5, §3.7, §3.8, §3.2 and §2.3.

Coherence check: no contradictions between passes. All 32 distinct rung references across §2/§3 match §2.7's ladder; §3.5's six ordinal dispatch gates match §2.7's order. Re-derived every version-count claim from source (mobilization +2; fee-bearing cancellation +2 / free +1; billing run +2 when it flips `CURRENT→PAST_DUE` else +1; reconciliation product +3/+1). Spot-checked the boldest universals from earlier passes — all hold. The two contradictions fixed were pre-existing: §4-vs-§5's status universal (item A) and §2.4-vs-§3.4's jurisdiction version bump (item F).

Pass 4 changes:
- §2.4 — revise — ambiguity — no-op converse made explicit (unchanged rows are not touched; unstored derived figures cannot bump a row) — `services.py:186-192`, `store.py:76-80`
- §2.5 — revise — mismatch — quarter-hour value rule separated from JSON spelling; no fixed fractional digits, no trailing zeros — `serialize.py:161`
- §2.9 — revise — ambiguity — a `CustomerContact`'s `X-User-ID` *is* its `CustomerAccount` id; added the permit scoping path — `services.py:119-123`
- §2.10 — insert — mismatch — conservation scoped to the sum; unclamped transfers, negative `available_count`/`deployed_count` and stranded units documented — `services.py:204-209`, `routes_work_orders.py:138-142`
- §2.10 — revise — mismatch — non-positive hops are skipped, not reversed — `services.py:205-206`
- §3.4 — revise ×2 — mismatch — removed the "recomputes" stored-aggregate framing; no permit operation writes to the jurisdiction row — `services.py:138-150`
- §3.6 — revise — ambiguity — `addons_deployed` is a write-once latch, never cleared — `services.py:421`
- §3.7 — revise — mismatch — a zero *or negative* count moves and mutates nothing; negative counts can leave `deployed_count` below zero — `routes_ledger.py:185-189`
- §4 — insert — mismatch — id→status promise scoped to declared pairs; `ERR_VALIDATION` at 404/405 pinned off that set — `app.py:50-59`
- §5 — revise — mismatch — the same single exception recorded in the catalogue preamble — `app.py:52-55`

---

### Step 9 totals and orchestrator verification

Across the four passes: **PRD_FINALIZED.md 433 lines / 96,030 bytes → PRD_COMPLETED.md 439 lines / 125,457 bytes** (+6 lines, +29,427 bytes, +30.6 %), **49 diff hunks**, **~55 pins/revisions** (P1 15, P2 13, P3 16, P4 10 + 3 no-change verdicts).

Independently verified on disk: 439 lines / 125,457 bytes; **not** byte-identical to either `PRD_FINALIZED.md` or `PRD.md` (so the scan demonstrably ran); 28 `^#` headings in both source and output, so no section was added or lost; final line is still `| `ERR_PAYMENT_EXCEEDS_BALANCE` | 409 |`, so no truncation. Machine cross-check against SCAFFOLD.yaml: all 41 `error_id`s and all 46 endpoint paths are still present in `PRD_COMPLETED.md` — no coverage was lost to the edits.

Regression safety: mtime comparison confirms every `implementation/*.py`, `start.sh`, `test_suite/*.py` and `test_helpers/*.py` file predates `results.1.json` (04:53:59) — the newest code change is `routes_contracts.py` at 04:51:16. Steps 8 and 9 modified only `workspace/PRD_FINALIZED.md` and `workspace/PRD_COMPLETED.md`, so the clean 8×79/79 sweep recorded in Step 7 still describes the final shipped code and tests.

**Pipeline complete.** Step 9 has written `workspace/PRD_COMPLETED.md`.
