# Worklog — task_2909_global_payroll_aggregation_in_country_provider_management

> RECONSTRUCTION NOTE (orchestrator, 2026-09-05T18:36:43.000Z). Entries for Steps 1–7 below were originally appended one at a time, immediately after each step, exactly as the skill requires. However, the orchestrator used a Python one-liner of the form `open(p,'w').write(open(p).read().replace(...))` to substitute the ISO timestamp into each freshly appended heading. CPython evaluates the callable `open(p,'w')` — which truncates the file — *before* it evaluates the argument `open(p).read()`, so that read returned the empty string and the file was progressively destroyed; by the time the Step 7 entry was appended, `worklog.md` was 0 bytes. Every entry below is restored **verbatim** from the orchestrator's own record of the appended text and the subagents' returned summaries, which the orchestrator still held in full. Nothing is paraphrased and nothing is lost. Step timestamps for Steps 2, 4, 5, 6 and 7 were not recoverable to the millisecond and have been reconstructed from the mtimes of each step's output artifacts; they are marked `(reconstructed from artifact mtime)`. Steps 1 and 3 retain their original exact timestamps. From this point on, timestamps are written literally into the heredoc heading and the substitution one-liner is never used again.

## Step 1: Create task directory — 2026-09-05T15:13:31.217Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2909_global_payroll_aggregation_in_country_provider_management and its workspace/ subdirectory. Index 2909 was pre-assigned by the invoking command; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-05T16:26:30.000Z (reconstructed from artifact mtime)

Task 2909 scaffold artifacts are complete and lint-clean.

Files written (all under the task dir)

| File | Lines | Top-level keys |
|---|---|---|
| `SCAFFOLD.yaml` | 3330 | `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles` — **no** design keys |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1729 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3718 | `scaffold_corner_design` only |

`worklog.md` and `workspace/` untouched; scratch confined to `workspace/.scratch2909/`.

Lint verdict (verbatim, first run, no iterations needed)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2909_global_payroll_aggregation_in_country_provider_management/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2909_global_payroll_aggregation_in_country_provider_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2909_global_payroll_aggregation_in_country_provider_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  762

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Inventory (SCAFFOLD.yaml)

- `api_prefix: /payroll`; consistency `immediate`; role model `segregation_of_duties`; complexity layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`.
- **11 entities**: CountryProfile, Provider, Engagement, LocalBankAccount, PayrollCycle, InputFile, GrossToNetRun, FundingInstruction, StatutoryFiling, SlaIncident, AuditEvidenceItem (last is immutable, no version).
- **9 state machines** (Engagement, PayrollCycle, InputFile, GrossToNetRun, FundingInstruction, StatutoryFiling with a parallel penalty dimension, SlaIncident, Provider, LocalBankAccount).
- **9 calculations**: `input_cutoff_resolution`, `statutory_due_date`, `input_validation_outcome`, `gross_to_net_variance` (dual-variant ABSOLUTE_TOTAL / HEADCOUNT_NORMALIZED), `provider_service_score` (dual-variant lifetime / rolling window), `funding_requirement_conversion`, `filing_penalty_allocation` (tiered, indemnity-capped), `treasury_commitment_reconciliation`, `country_obligation_reconciliation`.
- **70 validations** across priority bands 15/20/30/40/50/60/70; **64 errors**; **51 endpoints**; **6 roles**; **2 concurrency rules** (`gtn-run-create-stale-cycle` → ERR_STALE_CYCLE_VERSION, `transition-plan-stale-engagement` → ERR_STALE_ENGAGEMENT_VERSION).

Design instance counts

- **§1.8 difficulty**: 9 dimensions × 2 = **18 instances** (dual-variant, precision/rounding, cyclic+parallel state, cascades, priority conflicts, threshold boundaries, guarded transitions, interval/adjacency, compensation).
- **§1.9 corner**: **77 instances = 64 full test recipes + 13 `excluded_because` stubs**, spread over all nine guide sections — entities 12/0 stubs, state_machines 16/5, calculations 12/3, validations 11/2, endpoints 6/0, errors 8/0, rbac 6/0, cross_cutting_complexity_layers 5/3, consistency_model 1/0.
- Every stub cites a §1.8 instance that exists by name; instance names are unique across both design files (verified programmatically, zero collisions).

ORCHESTRATOR NOTE: SCAFFOLD.yaml's `scenario:` block contained the verbatim line "Generate task harder than expert level!" (the known difficulty-directive leak). The orchestrator deleted that line (and its trailing blank) from SCAFFOLD.yaml after Step 2 so it cannot reach PRD.md via the doc generator. YAML re-parse confirmed valid; 13 top-level keys intact. workspace/.scratch2909/ removed.

## Step 3: Copy shared files — 2026-09-05T16:27:11.665Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T16:43:40.000Z (reconstructed from artifact mtime)

PRD.md is complete.

**Artifact:** `workspace/PRD.md` — **456 lines, 101,851 characters, 14,238 words.**

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Actors and RBAC; 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination; 2.4 Resource Identity, Timestamps and Versioning; 2.5 The Logical Clock; 2.6 Minor Units, Percentages and Rounding Discipline; 2.7 Optimistic Concurrency Control; 2.8 Validation Order and Error Precedence; 2.9 Data Residency and Payroll Privacy; 2.10 Nested Paths and Sub-Resource Reads; 2.11 Segregation of Duties Across the Payroll Chain; 2.12 Cascades, Conserved Aggregates and Reconciliation
- §3 Business Logic & Workflows — 3.1 Standing Up the Estate; 3.2 Engagement Formation; 3.3 Cycles, Cutoffs and Holds; 3.4 Standardizing HR Input and Locking the Period; 3.5 Gross-to-Net Results and Variance Analysis; 3.6 Funding, Treasury Dual Authorization and Recall; 3.7 Statutory Filing, Late Sweeps and Penalty Ownership; 3.8 Service Level Monitoring, Provider Standing and Transition; 3.9 Global Controls, Evidence, Closure and Cancellation
- §4 Endpoint Definitions (4-column table)
- §5 Error Code Catalogue (2-column table)

**Coverage (verified programmatically against SCAFFOLD.yaml, not by eye)**
- **Endpoints: 51 / 51 documented.** Every scaffold `method + path` pair matches a §4 row exactly; §4 has exactly 51 data rows.
- **Errors: 64 / 64.** Every `error_id` + `status_code` pair matches a §5 row exactly (64 rows), and all 64 also appear in §2/§3 prose at their triggering rule — zero errors that exist only in the catalogue.
- **Calculations: 9 / 9** described in prose. Every constant *value* from all 9 calculations appears in the prose (internal constant names such as `TIER2_PCT` are deliberately rendered as prose values rather than symbols; `REGION_ELEMENT_SETS` is spelled out for all five regions and `WORKING_WEEKDAYS` as "Monday through Friday" with `local_holidays` exclusion).
- **State machines: 9 / 9**, all 66 transitions covered (38 with explicit `FROM → TO` arrows, the other 28 in narrative form — each of those 28 was individually spot-checked in the text).
- **Validations: 70 / 70.** All 30 validations whose `error_id` is shared across multiple scopes were checked scope-by-scope; each distinct scope is stated in its own endpoint's prose with its priority-derived ordering.

**Hard Contracts**
- **Contract 1 — Field-Name Coverage: PASS.** All 129 required identifiers (every `entities[].fields[].name` plus every endpoint `input`/`request_body`/`query_params`/`path_params` key) appear verbatim in backticks. Missing count: 0.
- **Contract 2 — Rule Coverage: PASS.** Validation priority bands (shape gate → 10 existence → 15 auth/SoD → 20 residency/scope → 30 state → 40 temporal → 50 referential → 60 fiscal → 70 uniqueness) are stated in §2.8; both `concurrency_rules[]` are stated in §2.7 with write endpoint, `expected_cycle_version` / `expected_engagement_version`, error ID and HTTP 412, plus an explicit statement that no other endpoint takes a version field; all cross-entity side effects, `applies_to` scopes, field-level content rules and sibling-branch symmetry (e.g. ABORT-from-`TRANSITION_PLANNED` vs from `TRANSITION_IN_PROGRESS`, `CLEARED` vs `ESCALATED` approval) are covered.
- **Contract 3 — §3 Path Purity: PASS.** Scanned every backticked token between `## 3.` and `## 4.`: zero tokens start with `/`, zero are bare HTTP methods, zero are method+path combinations.

**Tail check:** the document ends at a real section boundary — the last line is the final `| ERR_AUDIT_EVIDENCE_INCOMPLETE | 409 |` row of the §5 table, with no audit footer and no truncated sentence.

**Housekeeping:** `workspace/.scratch2909-prd/` was removed (workspace now contains only `INSTRUCTION.md` and `PRD.md`). `worklog.md`, all three `SCAFFOLD*.yaml` files and `workspace/INSTRUCTION.md` are untouched; the two withheld design indices were never opened, no sibling task directory was inspected, and no `pkill` was run.

One judgment call worth relaying: the scaffold spells the identity header inconsistently (`X-User-ID` 14x, `X-User-Id` 7x). The PRD uses the majority form `X-User-ID` and adds one clause in §2.1 stating that header *names* match case-insensitively per HTTP while the role *value* is case-sensitive — so a test suite sending either casing will pass.

ORCHESTRATOR VERIFICATION: independently confirmed 456 lines / 101,851 chars; `tail -25` ends on the final §5 error-catalogue row (a real section boundary, not mid-sentence) — no truncation, so no regeneration was needed. Grep for "expert level", "scaffold", "test_recipe" in PRD.md returned zero hits: the difficulty directive did not leak and the design indices are not referenced.

## Step 5: Generate unit tests — 2026-09-05T18:05:00.000Z (reconstructed; Steps 5 and 6 ran concurrently, Step 5 returned second)

Stage 2 is complete. The three remaining queue-B modules are written, compiled, import-verified and tag-verified, and the whole suite now stands at 100 tests.

**Files written this session** (all at the task root):

| file | lines | tests |
|---|---|---|
| `test_suite/test_15_errors.py` | 339 | 8 |
| `test_suite/test_16_rbac.py` | 289 | 6 |
| `test_suite/test_17_cross_cutting.py` | 217 | 3 |

**Full inventory** — `test_helpers/` 9 files (2382 lines: `__init__` 54, `api_client` 321, `api_errors` 168, `assertions` 279, `constants` 224, `factories` 487, `fixtures` 727, `test_users` 88, `types` 234); `test_suite/` `conftest.py` 80 + 17 test modules, 5029 lines, **100 tests**: test_01...test_09 = 4 each (36 queue A), test_10 12, test_11 11, test_12 9, test_13 9, test_14 6, test_15 8, test_16 6, test_17 3 (64 queue B).

**Design coverage** (verified by script against both yamls):
- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 18 non-stub instances, **18/18 translated, 0 uncovered**. Note the structure inherited from the earlier files: each depth instance is translated by a pair of tests (its two halves — accept/reject, variant A/variant B), so 18 instances -> 36 tagged tests. Every test carries exactly one tag; no test is untagged, dual-tagged or dangling.
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 77 instance names, **64 translated 1:1** (entities 12, state_machines 11, calculations 9, validations 9, endpoints 6, errors 8, rbac 6, cross_cutting 2, consistency_model 1). The 13 untranslated are exactly the design's own stubs and `EXCLUDED` rows (3 calculations, 2 validations stubs; `cascading_side_effect_chain_from_filing_sweep_to_cycle_hold`, `dual_variant_variance_basis_produces_two_different_verdicts`, `rate_threshold_boundary_on_the_materiality_gate` and the remaining state_machines/calculations/errors stubs that defer to a named difficulty instance).

**PRD-first deviations applied while translating the last 17 instances** (design text was not uniquely derivable, so I used the PRD's own vocabulary rather than weakening or skipping):
- Funding status: design says `PENDING_APPROVAL`; the PRD enum is `DRAFT -> APPROVED -> RELEASED`, so the auditor-refusal test asserts `DRAFT` with `approver_user_id`/`releaser_user_id` null.
- Cycle status after a run is submitted: design says `RESULTS_PENDING`, which is not a PRD cycle status — asserted `INPUTS_LOCKED` (consistent with test_12/test_13).
- Run status before review: design says `SUBMITTED`; the PRD scores variance in the same request, so the baseline run is `CLEARED`, and the second controller's `APPROVE` yields `APPROVED` (design said "200 with status CLEARED").
- Evidence `evidence_type "EXTERNAL_REFERENCE"` and `incident_type "SERVICE_BREACH"` are not PRD enum members — used `DOCUMENT_HASH` and `DATA_INCIDENT`, matching the earlier files.
- The blank-auth case sends `X-User-ID: ""` via `test_users.headers_with_empty_user_id`, never whitespace.

**Verification**
- `python3 -m py_compile test_helpers/*.py test_suite/*.py` -> `ALL_COMPILED`.
- `PYTHONPATH=. importlib` load of all 17 modules -> `ALL_IMPORTED 100 tests` (proves every constant, error id, factory, fixture and api_client method referenced actually exists).
- Tag audit: per-file test count == `Design:` tag count in all 17 files; every tag name resolves verbatim to a `name:` in the source yaml; no dangling tags.
- Money sent as JSON ints in minor units throughout; instants full ISO-8601 (`2026-08-26T17:00:00.001Z`, `2026-08-01T00:00:00.001Z`), date-only fields date-only (`2026-10-01`); no `["data"]` re-indexing after `validate_success`.
- Paths: `ls -d` confirms `.../task_2909_.../test_helpers` and `.../test_suite` exist at the task root; a `find` under `workspace/` returns nothing for `test_helpers`, `test_suite` or the scratch dir. `workspace/.scratch2909-tests/` and all `__pycache__` dirs removed. Nothing under `workspace/implementation/` was read or touched; `worklog.md`, `PRD.md`, `INSTRUCTION.md` and the `SCAFFOLD*.yaml` files are unmodified (the yamls were read only); no server was started and no pkill was run.

ORCHESTRATOR VERIFICATION (Steps 5+6): `test_helpers/` and `test_suite/` both confirmed at the TASK ROOT, with no stray copies anywhere under `workspace/`. 18 files in `test_suite/` (conftest + 17 modules); 100 `Design:` tags against 100 test functions (the 101st `^def test_` match is `conftest.py`'s `test_users` pytest *fixture*, not a test). `python3 -m py_compile` over all `test_helpers/*.py` + `test_suite/*.py` -> COMPILE_OK. All `__pycache__` dirs and every `.scratch*` dir removed. `workspace/implementation/start.sh` confirmed to honour `$PORT` and `exec python3 app.py` in the foreground.

## Step 6: Generate implementation — 2026-09-05T17:05:30.000Z (reconstructed from artifact mtime; Steps 5 and 6 ran concurrently)

(Steps 5 and 6 were launched concurrently in a single orchestrator message, per the skill, so that the implementation generator could not read test_suite/ — the directory did not exist when it started. Step 6 returned first.)

Done. Implementation complete, verified, smoke-tested, and torn down.

## Deliverable
`workspace/implementation/`

| module | lines |
|---|---|
| `common.py` (enums, 64-error catalogue, logical clock, rounding) | 351 |
| `store.py` (11 in-memory dict collections, `_seq`, `touch`) | 157 |
| `validate.py` (typed shape validators, pagination, query filters) | 330 |
| `serial.py` (per-entity serializers) | 220 |
| `services.py` (scoring, standing cascades, evidence, system incidents) | 220 |
| `calc.py` (9 calculations) | 203 |
| `app.py` (blueprint wiring, envelope error handlers) | 77 |
| `auth.py` (header auth + role gate + global `RLock`) | 60 |
| `response.py` (meta/response_type/data envelope) | 52 |
| `routes/cycles.py` 389, `routes/engagements.py` 276, `routes/gtn.py` 256, `routes/funding.py` 241, `routes/filings.py` 211, `routes/estate.py` 178, `routes/inputs.py` 150, `routes/incidents.py` 153, `routes/evidence.py` 52, `routes/clock.py` 18, `routes/__init__.py` 0 | |
| `start.sh` 10, `requirements.txt` 1 | |

Total 3,605 lines. `python3 -m py_compile` on all 21 `.py` files → COMPILE_OK. No `__pycache__`, no scratch dir, no on-disk state (in-memory dicts only, nothing seeded at startup).

## Coverage verified mechanically
- **Endpoints: 51/51.** A script parsed the PRD §4 table (51 rows) and the `@bp.get/post` + `@require` decorator pairs: zero missing, zero extra, and the allowed-role set matches the table exactly for all 51 (including `/_clock/set_current_utc`, which correctly excludes ProviderUser).
- **Errors: 64** entries in `common.ERRORS`.

## Smoke test
Port **21122** (chosen by probing `/dev/tcp` for a free port — first random pick 32980 was taken by another pipeline). Server launched with `PORT=21122 bash start.sh`, bound `0.0.0.0`. Two scripted suites, ~120 assertions, run against a freshly restarted process: **both ended `FAILURES: none`**.

Suite 1 (48 asserts): full happy path clock -> country -> provider -> engagement -> residency approve -> bank account + verify -> cycle -> input file -> validate -> lock-inputs -> GTN run -> review approve -> funding draft/approve/release -> file/confirm -> close -> audit-evidence, plus 401/403/422/404 negatives. Statuses seen: 200, 201, 204, 401, 403, 404, 409, 422.

Suite 2 (~70 asserts): HEADCOUNT_NORMALIZED variance (drift 5.00, variance 14.29, material, ESCALATED), justification-required + SoD + return/resubmit + `expected_cycle_version` 412, filing sweep penalties (late_days 2, base 65000, surcharge 6500, total 71500, indemnity headroom splitting the second filing 28500/43000 -> SHARED), dispute REJECT then UPHOLD (WAIVED, exposure 100000 -> 28500), incident scoring 100 -> 75 -> 62.5 -> 22.5 -> SUSPENDED with the three-level cascade, `ERR_HOLD_CAUSE_ACTIVE`, recovery + hold release, transition plan/approve/complete with provider reassignment and OFFBOARDED outgoing provider, cancellation.

**One real defect found and fixed** (`services.py`): the recovery cascade only ran on a provider *status transition* into ACTIVE, so an engagement whose last incident was remediated *after* the provider had already climbed back over 55.00 stayed stuck in `REMEDIATION_REQUIRED` forever. Per PRD line 305 the gating condition is per-engagement ("every engagement ... that has no remaining incident in `CONFIRMED` or `ESCALATED`"), so `derive_provider_status` now also runs `_recover` when the provider is already ACTIVE (idempotent no-op otherwise; holds are still never auto-released).

Two initial suite-2 failures on `open_filing_obligation_count` were **my test script's expectations**, not impl bugs — filings are minted at `lock-inputs` (PRD line 219), so both cycles' obligations were live; the implementation's counts (4, then 3 after one lodgement) are correct.

The server was killed by its own pid (`kill 22755`, plus the earlier `kill 4157866` resolved from `ss -ltnp` for port 21122 specifically); `ss -ltn | grep :21122` now reports the port free. No `pkill` was ever used. `.scratch2909-impl/` removed.

## Step 7: Run tests and iterate — 2026-09-05T18:34:23.000Z (reconstructed from final sweep artifact mtime)

Clean sweep. Done.

## Summary

**Iterations run:** 2 (iteration 1: 97/100 in all 8 rounds, 3 deterministic failures; iteration 2: 100/100 in all 8 rounds).

**Tests deleted:** none. All three failures traced to test artifacts that mis-expressed a rule the PRD verbatim covers, so all were repaired to be *more* faithful rather than dropped.

**Fixes applied to `test_helpers/`:** none — the fixture/factory layer was already type-correct (integers for `_minor`, date-only for calendar fields, `""` for blank headers, single `data` unwrap).

**Fixes applied to `test_suite/`:**

1. `test_suite/test_15_errors.py` — `test_extract_describing_no_employee_records_is_refused` sent `gross_declared_minor=0` alongside `record_count=0`. PRD 3.4 declares `gross_declared_minor` "in local minor units and **strictly greater than zero**", so a 0 there is a shape failure and the PRD-faithful implementation correctly reported `ERR_INVALID_REQUEST` at the shape gate, pre-empting the business-rule `ERR_EMPTY_INPUT_FILE` the test was aiming at. Dropped the `gross_declared_minor=0` override so only `record_count=0` is out of line; the exact-`error_id` assertion is unchanged.

2. `test_suite/test_17_cross_cutting.py` — `test_stale_expected_cycle_version_on_run_creation_is_refused_then_retried` and `test_lock_inputs_response_already_carries_every_side_effect` both asserted the cycle sits at `version == 2` after `lock-inputs`. That undercounts by one: PRD 3.4 says the extract submission "is written onto the cycle as `input_submitter_user_id`", and PRD 2.4 says `version` "increases by exactly 1 on **every mutation of that row**" (reinforced by 2.12: a row touched by a cascade is versioned "exactly as if it had been written directly"). So the enumeration is creation -> 1, extract submission -> 2, lock -> 3. Corrected the expected versions to 3 (post-lock) and 4 (post-run-creation), and in the concurrency test captured `version_before_the_lock` from a live re-read so the "exactly one behind" narrative the stale-version assertion depends on still holds. All `ERR_STALE_CYCLE_VERSION` / nothing-written / replay-rejected assertions are untouched.

**Fixes applied to `implementation/`:** none. No PRD-required check was relaxed and no endpoint, field, or side effect was added.

**Final sweep numbers:** rounds 1-8 all `100/100 passed`, 0 failed, 0 errors (~180 s per round, run concurrently under `setsid`).

**Note on the version-count call:** this was the one genuine two-reader question. I resolved it toward the blanket PRD 2.4 rule because a reader would have to argue that writing a field onto the cycle row is not a "mutation of that row" to reach the test's original number — and PRD 2.12 explicitly closes that door for side-effect writes. If the orchestrator prefers the opposite reading, the change is localised to four assertions in `test_17_cross_cutting.py`.

ORCHESTRATOR VERIFICATION: independently parsed all eight `workspace/implementation/results.{1..8}.json` — every round reports `passed: 100, failed: 0, errors: 0, skipped: 0, total: 100`, all eight written within one second of each other (18:34:22-18:34:23), i.e. a genuine concurrent 8-round sweep rather than a stale or partial artifact. `test_suite/` still holds 100 test functions, consistent with the subagent's "0 deletions". The subagent did not touch `worklog.md`.

ORCHESTRATOR ADJUDICATION on the version-count call: the subagent's reading is accepted. PRD 2.4's "increases by exactly 1 on every mutation of that row" plus 2.12's cascade-versioning clause jointly pin the count, and the implementation was NOT modified to accommodate the test — the test was corrected toward the PRD. Step 8 therefore has no implementation fix to document at that site; the item is carried into `<step_7_diff>` only so Step 8 can judge whether PRD 3.4 should state the `input_submitter_user_id` write's version effect more explicitly.

ORCHESTRATOR NOTE on Step 8 skip condition: NOT skipped. Step 7 ran 2 iterations with 2 `test_suite/` fixes, so the baseline-clean skip condition (0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes) does not hold.

## Step 8: Finalize PRD — 2026-09-05T18:46:33.000Z

Verification complete. One edit made.

**PRD.md vs PRD_FINALIZED.md:** 456 lines vs 456 lines (0.0% line delta; one line revised in place, +3 sentences of prose).

**Changes**
- PRD 3.4 (input submission, line 205) — revise — added that writing `input_submitter_user_id` onto the cycle is itself a mutation of the cycle row, refreshing `updated_at` and increasing `version` by exactly 1 (so an opened cycle fed one accepted extract stands at `version` 2), and that validating or resubmitting an extract writes nothing to the cycle row and leaves its `version` alone — `implementation/routes/inputs.py:71-72`, `implementation/store.py:39-44`.

**Per-edit pre-edit search log**

Edit 1 — PRD 3.4 cycle-version effect of the extract submission
- (a) Subject: mutations of the payroll-cycle row and their `version`/`updated_at` effect, specifically during the input phase.
- (b) Impl paths enumerated: `store.touch` (`store.py:39-44`, refreshes `updated_at`, `version += 1`); `store.new_row` (`version` starts at 1); grepped every cycle-row write / `touch(cycle)` site — `routes/inputs.py:71-72` (submission, exactly one touch, unconditional), `routes/inputs.py:76-120` (validate: touches only extracts, no cycle touch), `routes/inputs.py:123-150` (resubmit: touches only the extract), `routes/cycles.py:202-203` (lock), `:223-225` (release-hold), `:257-259` (cancel), `:308-309` (close), `routes/cycles.py:320-362` (filing-sweep: no cycle touch), `routes/gtn.py:124` (run creation), `:194-196` (review approve), `:251` (run resubmit), `routes/filings.py:137-139` (confirm), `routes/funding.py:205-206` (release), `:239-240` (recall), `services.py:113-131` (`_degrade` hold cascade — verified the relabel loop cannot double-touch a cycle it just held, since `hold_reason == reason`), `services.py:167-192` (`mint_system_evidence`/`record_evidence` — creates an evidence row, never touches the cycle). Every path touches a given cycle at most once per request, so the blanket "exactly 1 per mutation" claim holds globally.
- (c) Wording adjustments: scoped the increment to the *creation* of an extract only (impl's resubmit does not rewrite `input_submitter_user_id`, matching PRD 2.11's "each newly created extract"); added the explicit negative for validate/resubmit only after confirming neither writes to the cycle row nor mints evidence onto it; hedged the concrete "`version` 2" example with "with nothing else having touched it" so it does not become a false universal.

**Items judged to need no PRD change**
- `test_15_errors.py` fix (`gross_declared_minor=0` pre-empting `ERR_EMPTY_INPUT_FILE`): pure test-fixture bug. `validate.req_int(body, "gross_declared_minor", 1)` (`routes/inputs.py:36`, `validate.py:66-91`) rejects 0 at the shape gate, which PRD 3.4 ("strictly greater than zero") plus PRD 2.8 ("a numeric field outside its declared range ... `ERR_INVALID_REQUEST`, before any business rule") already uniquely determine. The `record_count == 0 -> ERR_EMPTY_INPUT_FILE` business check runs fourth, after residency/state/cutoff, exactly as PRD 3.4 orders it.
- `test_17_cross_cutting.py` version counts: the implementation matches PRD 2.4 + 2.12 as written; only the reader-level explicitness at the PRD 3.4 site was improved (the edit above). No implementation fix existed to document.

No scratch directory was created; PRD.md, `implementation/`, `test_suite/`, `test_helpers/` were left untouched.

ORCHESTRATOR VERIFICATION: `diff PRD.md PRD_FINALIZED.md` confirms exactly one changed line (PRD 3.4, line 205), 101,851 -> 102,261 chars (+410). PRD_FINALIZED.md is NOT byte-identical to PRD.md, which is consistent with Step 7 having made two test_suite fixes; the single edit is in scope for the `<step_7_diff>` version-count item and the subagent's pre-edit global search over every `touch(cycle)` callsite is recorded above.

## Step 9: Complete PRD — 2026-09-05T19:18:41.000Z

Run as THREE SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 were forbidden to copy and edited in place). Partition: pass 1 = the cross-cutting/global layer (`app.py`, `response.py`, `auth.py`, `validate.py`, `store.py`, `common.py`, `serial.py`) plus `routes/clock.py`, `routes/estate.py`, `routes/engagements.py`; pass 2 = `routes/cycles.py`, `routes/inputs.py`, `routes/gtn.py` and the `input_cutoff_resolution` / `statutory_due_date` / `input_validation_outcome` / `gross_to_net_variance` calculations; pass 3 = `routes/funding.py`, `routes/filings.py`, `routes/incidents.py`, `routes/evidence.py`, `services.py` and the `provider_service_score` / `funding_requirement_conversion` / `filing_penalty_allocation` / `treasury_commitment_reconciliation` / `country_obligation_reconciliation` calculations.

### Cumulative result

| file | lines | chars |
|---|---|---|
| PRD.md | 456 | 101,851 |
| PRD_FINALIZED.md | 456 | 102,261 |
| PRD_COMPLETED.md (after all three passes) | 457 | 122,251 |

Total Step 9 delta versus PRD_FINALIZED.md: **+1 line, +19,990 chars, 109 changed lines across 55 diff hunks**. Heading count unchanged at 29 in both files — no new sections and (except one §2.2 bullet added by pass 1) no new paragraphs; every other edit is in-paragraph. **58 edits total: 47 ambiguity-pins, 9 mismatch-revisions** (pass 1: 17 + 3; pass 2: 17 + 3; pass 3: 13 + 3).

### Pass 1 — global layer + estate + engagements (ambiguity-pins 17, mismatch-revisions 3; +7,697 chars)

- §2.1 Actors/RBAC — revise — ambiguity — header values are trimmed before use (trimmed form is what is compared and recorded); a whitespace-only header counts as empty -> 401; a role outside the six spellings is authorized nowhere -> 403 — `auth.py:13-46`
- §2.2 Success envelope — revise — ambiguity — `api_request_id` is `req_` + exactly twenty uppercase-alphanumeric characters — `common.py:215`
- §2.2 Success envelope — revise — ambiguity — the four pagination fields appear on list endpoints only (always all four), never on reads/creations/actions/clock — `response.py:7,30`
- §2.2 Error envelope — insert — ambiguity — new bullet: unrouted path -> `ERR_INVALID_REQUEST` at 404, undefined method -> `ERR_INVALID_REQUEST` at 405 (the only non-422 uses of that id), decided during routing so returned even without auth headers; trailing slash insignificant — `app.py:29,50-63`
- §2.3 Pagination — revise — ambiguity — empty-string `limit`/`offset` = omitted; non-integer literal -> 422; no upper bound on `offset`; query-param validation precedes path-resource existence; undefined query params ignored — `validate.py:294-314`
- §2.3 Pagination — revise — ambiguity — ties on `created_at` (common, because it comes from the logical clock) break by creation sequence — `store.py:47-49`
- §2.4 Identity/timestamps — revise — ambiguity — sub-millisecond instants keep precision for comparison but render truncated, not rounded — `common.py:220-235`
- §2.4 Identity/timestamps — revise — ambiguity — `updated_at` equals `created_at` until the first mutation — `store.py:26-36`
- §2.4 Dates — revise — **mismatch** — input parsing is lenient: a date field also accepts a full instant (calendar date taken), an instant field accepts a bare date (midnight UTC), plus space separator, lower-case `t`/`z`, omitted seconds, 1-9 fractional digits, `Z`/numeric offset (normalized)/no offset; unparseable or impossible dates -> 422 — `common.py:238-298`
- §2.5 Logical clock — revise — ambiguity — `to_iso8601` is required, the clock may move backwards, and it is one process-wide value — `routes/clock.py:15-18`, `common.py:200`
- §2.6 Minor units — revise — ambiguity — integer inputs accept integral-valued numbers (`25000.0`) but reject fractional numbers, numeric strings and booleans — `validate.py:78-91`
- §2.6 Percentages/rates — revise — **mismatch** — percentages/rates must be JSON numbers and are quantized (2dp / 6dp, half up) *before* range and positivity bounds are tested (0.005 -> 0.01 passes; `fx_rate` 0.0000004 -> rejected); rendered as plain JSON numbers, so `100.00` renders `100.0` — `validate.py:110-138`, `common.py:347-351`
- §2.7 Optimistic concurrency — insert — ambiguity — both expected-version fields accept any integer (zero/negative included) at the shape gate and fail the comparison instead — `validate.py:66-91`
- §2.8 Validation order — revise — ambiguity — body must be a JSON object (absent/empty where a required field is declared, unparseable, or non-object -> 422; all-optional or no-payload endpoints accept no body); explicit `null` == omitted; undeclared fields ignored; duplicate list entries are a shape failure; string lengths untrimmed — `validate.py:19-34,163-181`
- §2.10 Sub-resource reads/filters — revise — ambiguity — filters are conjunctive exact matches, an id filter naming no row yields an empty page rather than 404, empty-string filter = absent, out-of-enumeration filter value -> 422 — `validate.py:317-330`, `routes/engagements.py:111-126`
- §3.1 Country profiles — revise — ambiguity — `local_holidays` entries must each parse as a date, must be distinct as supplied, and are stored/echoed exactly as written — `validate.py:238-251`, `serial.py:25`
- §3.1 Local accounts — revise — ambiguity — the engagement must exist (404) but its `status` is not examined, so accounts may be registered against `DRAFT`/`REJECTED` engagements — `routes/estate.py:125`
- §3.1 Local accounts — revise — **mismatch** — verification carries no payload and is not status-gated: re-verifying a `VERIFIED` account succeeds, keeps `VERIFIED`, and still bumps `updated_at`/`version` — `routes/estate.py:160-166`
- §3.2 Engagement formation — insert — ambiguity — body FKs resolve in payload order, `country_profile_id` before `provider_id`, so a doubly-bad request reports `ERR_COUNTRY_PROFILE_NOT_FOUND` — `routes/engagements.py:43-44`
- §3.2 Residency decision — revise — ambiguity — `rejection_note` is validated but not persisted (no field exists) and the provider score is not recomputed on the REJECT branch — `routes/engagements.py:142,157-159`
- §3.8 Transition planning — insert — ambiguity — the incoming provider is resolved at the existence rank, so `ERR_PROVIDER_NOT_FOUND` precedes both the engagement state check and the stale-version check — `routes/engagements.py:176-188`

Pass 1 deliberately left un-pinned: `app.py:65-67` catch-all 500 handler (defensive, unreachable via any documented path — pinning it would make an internal-fault shape contractual); `response.py:24` `array_response` (dead code, no route calls it); the global request lock in `auth.py:47` (serialization is not externally observable); per-entity response field lists in `serial.py` (verified programmatically that every serialized field name for all eleven entities already appears in PRD prose, and the §3.3-§3.9 narratives belong to passes 2/3 — duplicating field lists there would risk cross-pass conflict); field-by-field evaluation order within one shape gate (unobservable, every shape failure carries the same `error_id`); `store._fetch`'s non-string-identifier branch (unreachable).

### Pass 2 — cycles + inputs + gross-to-net (ambiguity-pins 17, mismatch-revisions 3; +7,049 chars)

- §2.2 success-envelope bullet — revise — **mismatch** — the bullet claimed *no* state-transition action carries pagination `meta`; carved out the cycle filing sweep, which does — `routes/cycles.py:323,362`
- §4 preamble — revise — **mismatch** — preamble claimed every state-transition action returns the updated resource as an `object`; named the filing sweep as the one array/paginated exception — `routes/cycles.py:362`
- §3.4 (resubmit extract) — revise — **mismatch** — "Two guards apply in order" was exhaustive but impl has a third, `record_count` 0 -> `ERR_EMPTY_INPUT_FILE` (422); also pinned that only the three supplied fields are rewritten — `routes/inputs.py:140,143-148`
- §3.3 — insert — ambiguity — FK resolution order for cycle creation: `engagement_id` then `prior_cycle_id`; an unknown prior cycle is `ERR_CYCLE_NOT_FOUND`, not the baseline-coherence error — `routes/cycles.py:55-56`
- §3.3 — insert — ambiguity — a baseline cycle's own status is not examined (a `CANCELLED` or never-approved prior cycle is legal) — `routes/cycles.py:78-85`
- §3.3 — insert — ambiguity — `period_label` uniqueness counts every cycle of the engagement whatever its status, so a `CANCELLED` cycle's label stays taken (unlike the overlap check, which skips `CANCELLED`) — `routes/cycles.py:92-97`
- §3.3 — insert — ambiguity — an empty/inverted period has a day count <= 0, falls outside every band and takes `ERR_PERIOD_FREQUENCY_MISMATCH` — `calc.py:197-203`
- §3.3 — insert — ambiguity — cutoff walk recognises a holiday only by exact `YYYY-MM-DD` string equality against the stored entries — `calc.py:33`
- §3.3 — insert — ambiguity — release-hold tests cycle state before hold cause, so a non-`ON_HOLD` cycle reports `ERR_CYCLE_INVALID_STATE` — `routes/cycles.py:214-222`
- §3.4 — insert — ambiguity — neither submission nor validation examines the owning engagement's status, only the cycle's — `routes/inputs.py:48-49,81-85`
- §3.4 — insert — ambiguity — submitting a further extract supersedes nothing; several `RECEIVED` extracts may coexist and a `VALIDATED` one stays validated — `routes/inputs.py:55-73`
- §3.4 — insert — ambiguity — on the drift-rejection branch only `status`/`rejection_code` change: `validated_record_count` still 0, nothing superseded, no evidence minted — `routes/inputs.py:103-107`
- §3.4 — insert — ambiguity — filings are minted in stored `required_filing_types` order (= their creation-sequence order), and each opens with all penalty fields 0 / `NONE`, `dispute_round` 0, refs null — `routes/cycles.py:167-193`
- §3.5 — insert — ambiguity — `cycle_id` resolves before `input_file_id` at the existence rank — `routes/gtn.py:59-60`
- §3.5 — insert — ambiguity — the stale-version check is last within the state group, so a stale request from a suspended provider reports `ERR_PROVIDER_SUSPENDED` — `routes/gtn.py:69-83`
- §3.5 — insert — ambiguity — the variance re-branch is part of creation, so a new run returns at `version` 1 with `updated_at == created_at` despite already reading `CLEARED`/`ESCALATED` — `routes/gtn.py:105-128`
- §3.5 — insert — ambiguity — `return_reason`'s 10-char floor is a shape-gate rule (422 ahead of SoD/state), and `variance_justification` must be non-empty when present — `routes/gtn.py:159-164`
- §3.5 — insert — ambiguity — on `RETURN` the cycle row is not written at all (version unchanged) and a supplied `variance_justification` is discarded — `routes/gtn.py:198-204`
- §3.5 — insert — ambiguity — four ordered guards with `ERR_CYCLE_INVALID_STATE` named for the cycle check; tolerance, net<=gross, extract identity and provider standing are *not* re-checked; the run's `version` rises exactly 1 — `routes/gtn.py:219-255`
- §3.7 — insert — ambiguity — sweep triggers only strictly past `due_at`; walks filings in minting order so indemnity headroom is consumed in that order; returns *all* filings as a paginated array — `routes/cycles.py:335-362`
- §3.9 — insert — ambiguity — `cancel_reason` is required, >=1 char, no upper bound, validated then discarded (no field holds it) — `routes/cycles.py:236`
- §3.9 — insert — ambiguity — the three cancellation cascades run filings -> funding -> runs and are the whole clean-up: extracts untouched, no evidence withdrawn, no score recompute — `routes/cycles.py:257-281`

Pass 2 deliberately left un-pinned: "must not name the cycle being created" in §3.3 has no counterpart in impl but is unreachable (ids are server-minted after validation), so the prose is vacuous rather than wrong; the empty `country_elements` object at submission (impl accepts `{}` at the shape gate and defers required-key checking to validation, which §3.4 already locates unambiguously); the country-profile row version bump when `open_filing_obligation_count` changes (already covered globally by §2.12's cascade rule); `review` not checking cycle status (impl has no such guard, §3.5's guard list already excludes one, and the state is unreachable because supersession removes reviewable runs from cancelled cycles).

### Pass 3 — funding + filings + incidents + evidence + services (ambiguity-pins 13, mismatch-revisions 3; +5,204 chars)

- §3.6 — insert — ambiguity — `value_date` is never compared to the logical clock; past or far-future value dates are accepted — `routes/funding.py:32`
- §3.6 — insert — ambiguity — FK existence order `cycle_id` then `bank_account_id` (-> `ERR_CYCLE_NOT_FOUND` when both unknown) — `routes/funding.py:36-37`
- §3.6 — insert — ambiguity — a null `approver_user_id` can never be equalled, so the dual-auth guard never fires on a non-`APPROVED` instruction, which falls through to `ERR_FUNDING_INVALID_STATE` — `routes/funding.py:146-156`
- §3.6 — insert — ambiguity — `CTRL_FUNDING_DUAL_AUTH` is not re-minted when the cycle already carries that control (second release after a recall) — `services.py:167-172`, `routes/funding.py:207`
- §3.6 — insert — ambiguity — the 10-char `recall_reason` floor is a shape-gate check (422 before either state rule); no upper bound — `routes/funding.py:215`
- §3.7 — insert — ambiguity — `submission_ref` is >=1 char with no upper bound — `routes/filings.py:71`
- §3.7 — revise — **mismatch** — a `ProviderUser` that is not the engaged provider lodging a `PROVIDER`-responsible filing gets `ERR_FILING_RESPONSIBILITY_MISMATCH`, not `ERR_PROVIDER_SCOPE_VIOLATION` — `routes/filings.py:76-81`
- §3.7 — insert — ambiguity — confirm applies the provider-ownership check (`ERR_PROVIDER_SCOPE_VIOLATION`) ahead of the state rule, is independent of `responsibility`, and does not examine the cycle's status — `routes/filings.py:126-132`
- §3.7 — insert — ambiguity — the penalty-probation drop is taken only from `ACTIVE`; a zero `provider_share_minor` leaves the provider row entirely unwritten and runs no standing check — `routes/cycles.py:348-355`, `services.py:102`
- §3.7 — insert — ambiguity — `dispute_reason` >=1 char, no upper bound; ownership check precedes both guards — `routes/filings.py:151,156`
- §3.7 — insert — ambiguity — `decision_note` >=1 char, validated then discarded — `routes/filings.py:179`
- §3.7 — revise — **mismatch** — on `UPHOLD` the exposure is floored at zero and only the *standing* is re-derived from the stored `service_score` (no recompute); an already-`ACTIVE` provider still gets the recovery pass — `routes/filings.py:206-210`, `services.py:76-99`
- §3.8 — insert — ambiguity — `note` >=1 char/no upper bound/null default; FK existence order `engagement_id` then `cycle_id`; system-raised incidents carry the triggering `cycle_id`, a null `note`, `occurred_at` at the clock, and rescore nothing — `routes/incidents.py:41-44`, `services.py:204-220`
- §3.8 — insert — ambiguity — `escalation_note` >=1 char, validated then discarded, and the escalate body may be omitted entirely — `routes/incidents.py:120-121`
- §3.8 — insert — ambiguity — the 0.00 floor is applied after rounding, and a recompute landing on the same score *and* variant does not write the provider row (no `updated_at`/`version` movement), though the standing re-derivation always runs — `services.py:63-72`
- §3.8 — insert — ambiguity — degradation cascades only on an actual change of standing; a re-derivation that leaves a provider at the same `PROBATION`/`SUSPENDED` re-labels no hold, and an `OFFBOARDED` provider cascades nothing — `services.py:79-98`
- §3.8 — revise — **mismatch** — the recovery pass also runs when a re-derivation lands on `ACTIVE` for a provider that was already `ACTIVE` (releases an engagement whose last finding was just remediated) — `services.py:94-98`
- §3.9 — insert — ambiguity — system-minted evidence always carries `evidence_type` `SYSTEM_ATTESTATION` and a synthesized `payload_hash` of `sys:<control_ref>:<cycle id>` — `services.py:173-180`

Pass 3 deliberately left un-pinned: the unreachable "no approved run" guard in funding draft (`routes/funding.py:61-66` — a cycle in `RESULTS_APPROVED` always has an `APPROVED` run and approved runs are never superseded, so documenting it would add unobservable behavior); `penalty_owner` `NONE` (unreachable at assessment because base is always >= 25000 and `penalty_daily_rate_minor` > 0, and §3.7 already states the rule); a recompute reaching an `OFFBOARDED` provider still storing a new `service_score` (`services.py:63-72` runs before the `OFFBOARDED` early return — observable only through a very deep corner, and pinning it risked contradicting §3.8's "frozen at its last computed value", which was pass 1's territory, so only the safe half was pinned: that no standing change or cascade occurs); provider-scope-free reads of filings/incidents/funding by any role (§2.1 already confines ownership checks to the named write acts).

### Cross-pass integrity (each pass verified, then re-verified by the orchestrator)

Pass 2 confirmed it ran no `cp` and that pass 1's 19 hunks all survived (greps for "trimmed of surrounding whitespace", the `created_at` creation-sequence tie-break, the `has_more` clause and "truncated, not rounded" each returned their expected hit). Pass 3 confirmed the same for both earlier passes: `diff PRD_FINALIZED.md PRD_COMPLETED.md` grew to 55 hunks with all 39 pre-existing hunks still in place and pass 3's 16 interleaved among them.

ORCHESTRATOR VERIFICATION: `PRD_COMPLETED.md` is 457 lines / 122,251 chars and is NOT byte-identical to `PRD_FINALIZED.md` (109 changed lines) — the scan genuinely ran rather than degenerating into a bare copy. Heading count is 29 in both files, confirming "no new sections". The file ends on the final `ERR_AUDIT_EVIDENCE_INCOMPLETE | 409` row of the §5 catalogue — a real section boundary, not a truncation. Grep for "expert level" returns 0: the difficulty directive never reached any PRD variant. A `find -newermt` sweep confirms that no `.py` or `.sh` file under `workspace/implementation/`, `test_suite/` or `test_helpers/` was modified after the 18:34:23 green sweep, so the eight `results.{1..8}.json` files (100/100 each) remain valid evidence for exactly the code that is on disk now; Steps 8 and 9 touched only PRD variants. All `__pycache__` directories and every `.scratch*` directory were removed. Pipeline complete.

HOUSEKEEPING: `workspace/sweep.log` (the interleaved 8-round stdout, spliced garbage by construction since all eight rounds share one fd) was deleted. `workspace/sweep.sh` is retained deliberately — it is the exact script that produced the green sweep, and keeping it as a file rather than an inline one-liner is what avoids the `--start-command` quote-injection failure mode.
