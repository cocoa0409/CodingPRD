# Worklog — task_2907_crime_laboratory_case_management_backlog_reduction

## Step 1: Create task directory — 2026-09-05T14:49:51.56951697Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2907_crime_laboratory_case_management_backlog_reduction and its workspace/ subdirectory. Index 2907 pre-assigned by the orchestrator invocation (no scan of ./tasks/).

## Step 2: Generate scaffold — 2026-09-05T16:39:48.738071750Z

Subagent summary (verbatim):

Done. The three scaffold artifacts are complete and lint-clean.

**Output** (`/home/ubuntu/github/CodingPRD/tasks/task_2907_crime_laboratory_case_management_backlog_reduction/`):

| file | lines |
|---|---|
| `SCAFFOLD.yaml` (§1.0–§1.7) | 2930 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single key `scaffold_difficulty_design`) | 1975 |
| `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single key `scaffold_corner_design`) | 4068 |

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2907_crime_laboratory_case_management_backlog_reduction/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2907_crime_laboratory_case_management_backlog_reduction/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2907_crime_laboratory_case_management_backlog_reduction/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  956

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(clean on the first run; no lint iterations were needed)

**Composition**
- §1.8: 22 instances across all 9 difficulty rules (2–3 each, ≥2 satisfied everywhere).
- §1.9: 72 instances over all nine guide sections — entities 12, state_machines 14, calculations 13, validations 9, endpoints 5, errors 11, rbac 1, cross_cutting_complexity_layers 6, consistency_model 1. 56 carry full `test_recipe`s; 16 are `excluded_because:` stubs, every cited `difficulty_instance` resolving by name in the §1.8 file and none carrying a `test_recipe`.
- Sections finished this session: `errors` (10 instances batching the 33 previously untouched error ids), `rbac` (role-level segregation-of-duties denial matrix plus the Analyst-vs-list shared-read asymmetry), `cross_cutting_complexity_layers` (real OCC instances for **both** §1.2.1 concurrency rules, a real `rate_threshold_triggers` counter-reset instance, plus stubs for cascading side effects / dual variants / the instantaneous backlog threshold), `consistency_model` (`immediate` read-after-write).

**Verified invariants**
- All 61 error ids in §1.6 are now referenced by at least one design instance (0 uncovered).
- Instance names unique across the union of both design files; `SCAFFOLD.yaml` contains neither design key; each design file has exactly one top-level key.
- No forbidden concurrency vocabulary anywhere in the three files.

**Notable scaffold corrections made while writing recipes:** four constants that were referenced but never valued got inline values (MIN_VALIDATION_STUDY_ITEMS 12, MAX_VALIDATION_CV_PCT 5.00, TRAVEL_BUFFER_MINUTES 60, MIN_TESTIMONY_NOTICE_DAYS 7); `ERR_ANALYST_COMPETENCY_INSUFFICIENT` was rewritten to the integer 1..5 scale; the `item_count` upper bound was assigned solely to validations[priority=24]; `VendorEngagement.custody_days` now says `round_half_up(`. One YAML gotcha worth remembering: list-index captures must be quoted in flow mappings (`captures: { n1: "$.data[0].id" }`) or the parser reads `[` as a flow sequence.

`worklog.md` was not touched.

Orchestrator note: verified all three YAML files exist; grepped SCAFFOLD.yaml for the "harder than expert level" difficulty directive — no leak (the `scenario:` key holds only the verbatim scenario text; `difficulty_level: expert` is the scaffold's own normal field).

## Step 3: Copy shared files — 2026-09-05T16:39:53.223866144Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T16:59:02.243894335Z

Subagent summary (verbatim):

PRD generation is complete. All three Hard Contracts pass.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2907_crime_laboratory_case_management_backlog_reduction/workspace/PRD.md` — **474 lines**, written incrementally in 11 heredoc appends (no single-Write truncation risk).

Last 5 lines verbatim:

```
| `ERR_VENDOR_NOT_ACCREDITED` | 409 |
| `ERR_VENDOR_SUSPENDED` | 409 |
| `ERR_VENDOR_CAPACITY_EXCEEDED` | 409 |
| `ERR_VENDOR_CEILING_EXCEEDED` | 402 |
| `ERR_INSUFFICIENT_TESTIMONY_NOTICE` | 422 |
```

The document ends at a real section boundary: the final row of the §5 Error Code Catalogue table, which is the last section of the mandated skeleton.

## Structure

Title + §1 Introduction; §2 Global Specifications with 11 domain-named subsections (2.1 Operator Identity and Role Authority, 2.2 API Response Structure verbatim, 2.3 Pagination and Default Ordering, 2.4 Record Identity/Audit Stamps/Versioning, 2.5 The Logical Laboratory Clock, 2.6 Numeric Precision, 2.7 Stale-Record Protection, 2.8 The Normative Rule Evaluation Order, 2.9 Path Identifier Resolution, 2.10 Cascading Reconciliation, 2.11 Standing Ledger Invariants); §3 Business Logic with 9 subsections following a custody-to-courtroom arc (intake/priority scoring → accreditation scope → queue entry → staffing and auto-balancing → bench work → review gates → vendor outsourcing → quality system → reporting/turnaround/backlog/discovery/testimony); §4 Endpoint Definitions (4 columns); §5 Error Code Catalogue (2 columns).

## Hard Contract verification (mechanical, scripts in `workspace/scratch_step4/`)

- **Contract 1 — Field-Name Coverage: PASS.** 150 unique required identifiers extracted from the scaffold (129 entity fields, 80 request-body, 26 query-param, 12 path-param, deduped); 0 missing from backticked prose. Fenced code blocks were excluded from the backtick-pairing scan.
- **Contract 2 — Rule Coverage: PASS.** All 27 validation priorities appear as numbered rules 1–27 in §2.8 with matching error ids (plus the two out-of-band 422 checks). All 61 error ids are described in §2/§3 prose, not only tabled. All 11 calculations, both concurrency rules, and every transition of all 11 state machines (including the system cascades: method-retire, case-reject, PROBATION_RELEASE/FULL_RELEASE, REOPEN_HOLD, nonconformance voiding, `PROBATION → QUALIFIED` via all three routes) are covered. All scaffold numeric literals appear except four that exist only in a non-normative scaffold note about the unreachable ceiling of the priority score.
- **Contract 3 — §3 Path Purity: PASS.** 0 violations across §3 (lines 180–335): no backtick token starts with `/`, is a bare HTTP method, is a method+path pair, or embeds `/lab`; no raw un-backticked path text either. Endpoints are referenced by state-transition framing, role + action verb, or capability description.

Table exactness was script-generated from the scaffold and re-verified: §4 has 64 rows matching the scaffold's `(method, path)` set exactly; §5 has 61 unique rows with zero HTTP status mismatches.

## Two deliberate resolutions of scaffold ambiguity

1. The scaffold's validation text names the role header `X-Role`; the skill mandates `X-User-Role`. I used `X-User-Role` (and `X-User-ID`) throughout — no occurrence of `X-Role` remains.
2. `ERR_INVALID_INTERVAL` and `ERR_METHOD_VALIDATION_INSUFFICIENT` have no slot in the 1–27 priority table, so I stated them in §2.8 as out-of-band 422 checks without pinning them against the neighbouring gates, rather than inventing an order.
3. Where `analyst_workload_variants` reports 0.00 utilisation at zero available hours but priority 25's note says such an examiner refuses every assignment, I wrote both behaviours explicitly (read reports 0.00; capacity gate refuses with `ERR_ANALYST_CAPACITY_EXCEEDED`).

Note for cleanup: the scratch directory `workspace/scratch_step4/` (extraction and contract-check scripts, `required.json`, and the generated `section4.md`/`section5.md` fragments) sits inside the implementer-facing `workspace/`. It contains no forbidden material, but you may want to remove it before handing the workspace to the implementation step. The two withheld design files were never opened.

Orchestrator truncation check: PRD.md is 474 lines and its tail is the complete final row of the §5 error table (`| \`ERR_INSUFFICIENT_TESTIMONY_NOTICE\` | 422 |`) — a real section boundary, not a mid-sentence cut. No regeneration needed. Grepped PRD.md for the difficulty directive and for scaffold/design-file references: zero hits. Removed workspace/scratch_step2/ and workspace/scratch_step4/ so Steps 5/6 see only INSTRUCTION.md and PRD.md in workspace/.

## Step 6: Generate implementation — 2026-09-05T17:39:56.837508015Z

(Steps 5 and 6 were launched concurrently in a single message; Step 6 returned first, so it is logged here ahead of Step 5. Step 5 entry follows below.)

Subagent summary (verbatim):

Step 6 implementation is complete.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2907_crime_laboratory_case_management_backlog_reduction/workspace/implementation/` — 18 files, 3,504 lines, Python 3 + Flask, in-memory dicts only.

| File | Lines | Role |
|---|---|---|
| `app.py` | 76 | app factory, 7 blueprint registrations, `ApiError`/`HTTPException`/catch-all handlers, `0.0.0.0:$PORT` |
| `start.sh` | 10 | guarded flask install, `exec python3 app.py` in the foreground (chmod +x) |
| `requirements.txt` | 1 | `Flask>=2.0.0` |
| `errors.py` | 138 | 61-entry error catalogue + HTTP status map |
| `util.py` | 97 | Decimal/ROUND_HALF_UP helpers, instant parse/format (3 fractional digits), whole-day floor, fractional days |
| `store.py` | 78 | 12 in-memory tables, logical clock pinned at `2026-08-01T00:00:00Z`, seq/audit/touch |
| `envelope.py` | 113 | meta/object/array/error envelopes, `limit`/`offset` validation |
| `auth.py` | 58 | `X-User-ID`/`X-User-Role`, 401 vs 403, role decorator |
| `validate.py` | 167 | declarative field schema, unknown-key and missing-required rejection |
| `serialize.py` | 281 | per-entity field-order renderers for all 12 entities |
| `services.py` | 697 | domain core: priority scoring, rollups, cascades, utilisation, pricing chain, turnaround merge, backlog report |
| `routes_registry.py` | 290 | clock, analysts, methods, vendors |
| `routes_intake.py` | 240 | cases, priority overrides, discovery axis, evidence items |
| `routes_casework.py` | 442 | requests, assignments, auto-assign, bench work, three review gates |
| `routes_vendor.py` | 187 | award/ship/return/cancel + ledger |
| `routes_quality.py` | 231 | proficiency tests, qualification cascade, nonconformances/CAPA |
| `routes_court.py` | 117 | testimony blocks with travel-buffer calendar |
| `routes_reads.py` | 281 | 12 GET singles, 9 GET lists, workload, backlog report |

## Verification

- **Route parity:** a programmatic diff of the Flask URL map against PRD §4 shows all **64 endpoints present, 0 missing, 0 extra** (method + path exact).
- **Fresh-boot cleanliness:** launched through `start.sh`; every list read returns `total_count: 0` and the backlog report echoes `as_of_utc: 2026-08-01T00:00:00.000Z`. Zero seeded data, zero wall-clock fallback.
- **No persistence:** grep confirms no `open()`, sqlite, pickle, `json.dump(`, or `/tmp` use anywhere.
- **Two smoke suites** (`scratch_step6/smoke.py`, `smoke2.py`, ~130 assertions) exercised: pinned priority scoring (HOMICIDE + custody + deadline -> 87.50/P1_STATUTORY), method validation gates and retire cascade, six-step vendor pricing (120000 -> +25% rush -> 150000 tier basis -> 0.04 tier -> 144000 award) with closed-interval capacity clash, ceiling 402 and suspension, custody_days 13.13, reassignment/supersede hour transfer, both OCC 412s, full DISAGREE cascade (NC opened MAJOR/30d -> probation -> UPHOLD_ANALYST voids the NC and restores QUALIFIED; UPHOLD_REVIEWER/RETURN increments `revision_round` and reopens the hold to IN_ANALYSIS), SoD refusals at all three gates, PT ladder QUALIFIED->PROBATION->SUSPENDED with auto-findings, CAPA double-rejection escalating MAJOR->CRITICAL and recomputing `due_utc` from the original `opened_at_utc`, testimony travel-buffer conflict and notice floor, pagination bounds, filter leniency, 401/403/404/405. No 500s and no tracebacks in the server log.
- **Every remaining smoke "FAIL" was my own expectation, not an implementation defect** — 8 cases where I guessed 422 for codes the PRD §5 table pins at 409 (`ERR_SEGREGATION_OF_DUTIES`, `ERR_COURT_EVENT_NOT_ELAPSED`, `ERR_PROBATION_PRIORITY_RESTRICTED`, `ERR_REFERENTIAL_MISMATCH`, `ERR_ANALYST_CAPACITY_EXCEEDED`, `ERR_METHOD_NOT_VALIDATED`, `ERR_OPEN_NONCONFORMANCE_BLOCKS_REINSTATEMENT`); each was checked line-by-line against the PRD table and the implementation is right.

Smoke server was killed by its own port (39073); no broad `pkill` was ever issued and port 39073 is confirmed free. `__pycache__` removed. `worklog.md`, `test_suite/` and `test_helpers/` were never read or touched.

## Step 5: Generate unit tests — 2026-09-05T18:15:31.602141460Z

Subagent summary (verbatim):

Step 5 is complete. Both output directories sit at the task root; `workspace/` was never written to.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2907_crime_laboratory_case_management_backlog_reduction/test_helpers/` — 2,885 lines
```
__init__.py 27   api_client.py 584   api_errors.py 192   assertions.py 323
constants.py 202  factories.py 492   fixtures.py 674     test_users.py 133   types.py 258
```

`/home/ubuntu/github/CodingPRD/tasks/task_2907_crime_laboratory_case_management_backlog_reduction/test_suite/` — 8,885 lines, **100 test functions**
```
conftest.py 12
test_01_workload_and_turnaround_variants.py 313   test_11_state_transitions.py 879
test_02_pinned_formula_orders.py 283              test_12_calculations.py 794
test_03_cyclic_state_machines.py 422              test_13_validations.py 732
test_04_transitive_cascades.py 388                test_14_endpoint_contracts.py 347
test_05_rule_order_conflicts.py 385               test_15_error_taxonomy.py 154
test_06_inclusive_boundaries.py 388               test_16_lifecycle_refusals.py 565
test_07_cross_entity_gates.py 272                 test_17_standing_and_identity_refusals.py 823
test_08_interval_conventions.py 355               test_18_role_partition.py 171
test_09_compensating_actions.py 316               test_19_stale_versions_and_counters.py 418
test_10_entity_shapes.py 708                      test_20_read_after_write.py 160
```

## Verification (all green)

- **Design-tag audit** (`scratch_step5/audit_tags.py`): 100 tagged tests / 78 distinct tags = 22 difficulty instances (>=2 tests each, none thin) + 56 non-stub corner instances (>=1 each). Zero untagged, zero dual-tagged, zero dangling, zero uncovered. All 16 `EXCLUDED:` corner stubs skipped.
- **Citations** (`scratch_step5/check_citations.py`): 185 citations, 0 non-verbatim (each whitespace-normalised citation is a substring of `workspace/PRD.md`).
- **Imports**: 0 files with unused imports. No `skip`/`skipif`/`xfail`, no TODO/placeholder, no "scaffold"/§1.x/design-vocabulary leakage anywhere in `test_suite/` or `test_helpers/`.
- **pytest collection** with `cwd=test_suite` and PYTHONPATH at the task root: **100 tests collected**, no import errors.

## Two findings worth relaying

1. **Latent collection bug found and fixed**: pytest's default `python_functions = test*` collected the imported factory `testimony_completion_payload` in `test_16` as a 101st "test" (it would have errored as a fixture-less test). Now imported as `testimony_completion_payload as _completion_payload`. An audit across all suite files confirms no other imported name starts with `test`.
2. **One design literal contradicted the PRD and was corrected to the PRD's value**: corner instance `consecutive_failure_counter_resets_on_a_pass_...` asserts `consecutive_pt_failures == 1` after closing the PT_FAILURE finding, but PRD §3.9/§3.8 closure restoration states that when the finding names the analyst and no other live finding remains, they move `PROBATION -> QUALIFIED` **and** `consecutive_pt_failures` resets to 0. `test_19` asserts 0 there; the instance's headline claim (pass resets the run, third failure lands at 1 -> PROBATION, `suspended_at_utc` null, `late_submission` false) is asserted intact. Recorded in `scratch_step5/progress.txt`. (Earlier, the same treatment was applied to the corner instance declaring `rush_surcharge_pct: 20.0`, out of the PRD's 0.00–0.50 range -> registered at 0.20; the asserted award is unaffected since `rush_flag` is never set.)

`worklog.md` was not touched; scratch lives only in `scratch_step5/`.

Orchestrator note: verified test_helpers/ (9 files) and test_suite/ (21 files) are at the TASK ROOT, not under workspace/ — no stray copies inside workspace/. Steps 5 and 6 were launched concurrently in one message, so the impl generator was physically unable to read test_suite/ (it did not exist at its spawn time).

## Step 7: Run tests and iterate — 2026-09-05T18:27:56.765724011Z

Subagent summary (verbatim):

Clean sweep achieved. worklog.md untouched (timestamp 18:15, predates my work), scratch dir removed.

## Summary

**Iterations run:** 2 (initial sweep 99/100 in all 8 rounds; second sweep 100/100 in all 8 rounds).

**Tests deleted:** none. The single failure passed both STEP 1a (PRD verbatim-covers) and STEP 1b (uniquely derivable), so no deletion was warranted.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. The implementation was already correct.

**Fixes applied to `test_suite/`** — one assertion mis-translation:
- `test_suite/test_12_calculations.py`, `test_the_balancer_ranks_on_utilisation_percent_not_on_free_hours`: the `assert_workload` call asserted `realized_load_hours=0.00` / `realized_utilization_pct=0.00` after an auto-assignment created one `ACTIVE` 8.00-hour assignment. Corrected to `8.00` / `25.00`, and added the governing PRD §3.4 quote to the docstring.

**Diagnosis (the load-bearing detail):** PRD §3.4 states the realized numerator "ranges over the examiner's assignments whose `status` is `ACTIVE` or `COMPLETED` and takes, for each one, the owning request's `actual_hours_logged` whenever that figure is not null and the assignment's snapshotted `estimated_hours` otherwise." The fresh `ACTIVE` assignment had no logged hours, so it contributes its snapshotted 8.00 estimate — giving 8.00 and 8/32x100 = 25.00. `services.py:realized_load_hours` implements exactly that sentence, statuses and null-fallback included, so the 8.00 it returned was correct and the test was wrong.

Two independent corroborations that the test, not the implementation, was the defect:
1. The failing test contradicted its own file. The sibling test `test_completion_moves_the_hours_from_the_projected_variant_to_the_realized_one` asserts `realized_load_hours=12.00` for two `ACTIVE` assignments *before* any completion, and it passed in all 8 rounds. Both tests cannot be right about whether `ACTIVE` assignments count toward the realized variant.
2. The failing test's own docstring quoted only the available-hours and candidate-ordering sentences, never the realized-variant sentence — the assertion had no PRD citation behind it. The generator appears to have assumed "realized" means "completed work only", which the PRD explicitly does not say.

Because the implementation matched PRD prose verbatim, this was a STEP 2 fix (test made more faithful to PRD), not a STEP 3 implementation change. No assertion was weakened, no `error_id` downgraded, and no skip/xfail added.

**Final per-round results**, quoted from `workspace/implementation/results.*.json`:

| Round | passed/total |
| --- | --- |
| 1 | 100/100 |
| 2 | 100/100 |
| 3 | 100/100 |
| 4 | 100/100 |
| 5 | 100/100 |
| 6 | 100/100 |
| 7 | 100/100 |
| 8 | 100/100 |

All 8 rounds report `failed=0 errors=0 skipped=0`.

Orchestrator verification (independent, not taken on trust): all 8 results.$i.json files exist in workspace/implementation/ (~31 KB each, timestamped 18:25) and were re-parsed directly — every round reports passed=100 total=100 failed=0 errors=0 skipped=0. The sweep artifacts are real, so the clean-sweep claim is confirmed.

Orchestrator decision on Step 8: NOT skipped. The skip condition requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes; Step 7 made one test_suite assertion fix, so Step 8 runs. Note that Step 7 made 0 implementation fixes, so a byte-identical PRD_FINALIZED.md is a legitimate outcome here (the one test_suite fix was a pure test-side mis-translation of a PRD sentence the PRD already states verbatim, revealing no PRD silence to patch).

## Step 8: Finalize PRD — 2026-09-05T18:30:15.644540231Z

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` exists and is **byte-identical to `PRD.md`** — no edits were warranted.

**Line counts:** PRD.md 474 lines / 108245 bytes; PRD_FINALIZED.md 474 lines / 108245 bytes. Delta: **0 lines, 0.00%**. `diff` reports no differences.

**Changes:** none.

**Why no edit was justified**

The Step 7 diff contains zero implementation fixes, zero deletions, zero `test_helpers/` fixes, and exactly one `test_suite/` assertion correction (`test_12_calculations.py::test_the_balancer_ranks_on_utilisation_percent_not_on_free_hours`). I verified the diagnosis independently against the code:

- `implementation/services.py:333-348` (`realized_load_hours`) iterates the examiner's assignments, keeps `status in ("ACTIVE", "COMPLETED")`, adds the owning request's `actual_hours_logged` when non-null and the assignment's snapshotted `estimated_hours` otherwise, then `q2()` (= `ROUND_HALF_UP` to 2dp, `util.py:26`). That is a clause-for-clause match of the PRD §3.4 realized-variant sentence, statuses and null-fallback included. The 8.00 / 25.00 the impl returned was correct; the test's 0.00 / 0.00 had no PRD citation behind it.
- `projected_load_hours` (`services.py:325`) restricts to `ACTIVE` only, so PRD's "`SUPERSEDED` or `RELEASED` are excluded from both variants entirely" holds, and `utilization_pct` (`services.py:351`) returns exactly `0.00` when available is `0.00` — both as written.
- `available_hours` (`services.py:318`) floors at 0.00 after subtracting training hours, matching PRD verbatim.

So the PRD already determines the Step 7 site uniquely; per the method, prose was kept verbatim.

**Pre-edit search log:** no edits were committed, so there is no per-edit log. The one candidate subject I traced (the realized/projected utilisation variants and the balancer's ranking figure) was enumerated across every impl path that touches it — `services.py` `available_hours`, `projected_load_hours`, `realized_load_hours`, `utilization_pct`, `active_assignment_count`, `workload_document`, `post_assignment_utilization`, `capacity_admits`; `routes_casework.py:166-205` (auto-assign candidate filter and 4-key sort) and `:261` (the sole `actual_hours_logged` write); `routes_casework.py:87` (its `None` initialisation); `routes_reads.py:246-250` (workload serialisation); `serialize.py:93`; `util.py` `q2`/`dec`. Every one is already consistent with the existing PRD §3.4 and §3.5 prose, so no wording adjustment was needed.

Two out-of-scope observations, deliberately **not** patched because they trace to no Step 7 diff item (flagging them only so the orchestrator knows they were seen and skipped):

1. `routes_casework.py:197` appends `analyst["_seq"]` as a fourth sort key after `created_at`. PRD §3.4 stops at `created_at` ascending, so a `created_at` tie is resolved by insertion order rather than by anything the PRD names. PRD does say "Examiner identifiers are never a tie-break", and `_seq` is an insertion counter rather than an identifier, so there is no contradiction — just residual silence.
2. `actual_hours_logged` is never cleared when a revision round returns a request to `IN_ANALYSIS`; a later completion simply overwrites it. That is consistent with PRD §3.5's "is stored on the request as `actual_hours_logged`", but the PRD does not state it explicitly.

Note: `implementation/__pycache__/` disappeared between my first and second directory listings (an external cleanup — I ran no deletions there). All 18 source files are intact and unmodified at their original 17:0x-17:33 timestamps. The only file I wrote was `PRD_FINALIZED.md`; the `scratch_step8/` directory I created went unused and was removed. `worklog.md` was not touched, and I read no `SCAFFOLD*.yaml` or sibling task directories.

Orchestrator notes: confirmed by `diff -q` that PRD_FINALIZED.md is byte-identical to PRD.md. This is a legitimate Step 8 outcome, not a failed run — Step 7 applied zero implementation fixes, so there was no impl-pinned choice for Step 8 to write down. (The __pycache__ removal the subagent noticed was mine, run from the orchestrator while cleaning the generators' scratch directories; no source file was touched.) The two residual silences the subagent flagged as out-of-scope (the `_seq` fourth sort key in auto-assign tie-breaking, and `actual_hours_logged` surviving a revision round) are exactly Step 9's remit and are being handed to it.

## Step 9: Complete PRD — 2026-09-05T19:02:52.935545411Z

Orchestrator note: Step 9 was run as THREE sequential passes over one shared PRD_COMPLETED.md, partitioned by implementation module, so no single subagent had to hold 3,500 lines of implementation plus a 474-line PRD. Pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden from repeating it and each was handed the list of line numbers already edited, to avoid stale Edit anchors. Total 60 edits (21 + 23 + 16) touching 52 distinct lines.

### Pass 1 of 3 — infrastructure, registry, intake (subagent summary, verbatim)

Pass 1 complete.

## File integrity
- Before: 474 lines / 108,245 bytes. After: **474 lines / 115,512 bytes** (all 21 edits were in-place single-line replacements — `diff` shows 21 `NcN` hunks, zero line-count drift).
- Tail intact: line 473 is `| \`ERR_INSUFFICIENT_TESTIMONY_NOTICE\` | 422 |`, followed by the original trailing blank line. §5 table and all section headings untouched.
- Setup `cp PRD_FINALIZED.md -> PRD_COMPLETED.md` done (passes 2/3 must NOT repeat it). PRD.md and PRD_FINALIZED.md untouched.

## Counts
17 ambiguity-pins, 4 mismatch-revisions (21 edited lines).

## Changes (impl paths are under `workspace/implementation/`)
- §2.1 — insert — ambiguity — only a literally empty header counts as absent; whitespace-only `X-User-Role` -> 403, whitespace-only `X-User-ID` is accepted — auth.py:30
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + exactly 20 upper-case-alnum chars — envelope.py:20
- §2.2 — revise — mismatch — `api_request_timestamp` is the one wall-clock instant, deliberately not the logical clock — envelope.py:24
- §2.3 — insert — ambiguity — non-integer/empty/fractional `limit`/`offset` is also 400; surrounding whitespace stripped — envelope.py:78
- §2.3 — insert — ambiguity — identical `created_at` ties (static logical clock) broken by insertion order — store.py:76
- §2.3 — insert — ambiguity — `has_more` = `offset + len(data) < total_count`; object/computed `meta` carries no pagination keys — envelope.py:55
- §2.4 — insert — ambiguity — client instants need date+time+zone (`Z` or numeric offset, normalised to UTC); date-only/zoneless is 400; sub-ms truncated, not rounded — util.py:35
- §2.5 — revise — mismatch — wall-clock ban carves out the envelope stamp; clock may be wound backwards or re-set to the same instant; the call returns a one-field `{current_utc}` document, not a resource — routes_registry.py:19
- §2.6 — insert — ambiguity — >2dp inputs are range-checked as supplied then rounded half up on write; 2dp figures render as JSON numbers with no trailing zeros (`43.5`, `0.0`) — util.py:25, serialize.py:212
- §2.6 — revise — mismatch — whole-day floor quotient goes toward negative infinity (past instants yield negatives) — util.py:79
- §2.8 rule 4 — insert — ambiguity — `Content-Type` ignored; absent/empty/`null` body = `{}`; non-object body 400; explicit `null` only for nullable fields; bool/fractional never satisfies integer; undeclared-range text fields accept `""` — validate.py:16,138
- §2.9 — insert — mismatch — undeclared path -> 404 and undeclared method -> 405, both with `error_id` `ERR_INVALID_REQUEST` (the only two departures from §5's 400), before the header check; trailing slash insignificant — app.py:41, app.py:25
- §3.1 — insert — ambiguity — agency/case-number key checked across all cases whatever the status; rejection does not free it — routes_intake.py:34
- §3.1 — insert — ambiguity — priority override admissible in any `workflow_status` (version check is the only extra gate) — routes_intake.py:106
- §3.1 — insert — ambiguity — no-evidence then seal, both after the `SUBMITTED` state guard — routes_intake.py:74
- §3.2 — insert — ambiguity — registration records the three optional validation figures verbatim, applies no minima/expiry test — routes_registry.py:150
- §3.2 — insert — ambiguity — validate order pinned: DRAFT guard -> study minima -> `expires_at_utc` vs clock — routes_registry.py:195
- §3.4 — insert — ambiguity — PATCH is a mutation even when empty/no-op (version +1); training-vs-capacity ceiling tested against post-adjustment values — routes_registry.py:79
- §3.7 — insert — ambiguity — `suspension_reason` changes only when supplied (survives a return to `ACTIVE`); setting the current status is admissible — routes_registry.py:278
- §3.8 — revise — mismatch — reinstatement `rationale` is required, 1 to 500 characters — routes_registry.py:109
- §3.9 — insert — ambiguity — the DENY `response_note` requirement is schema-class, settled before the `RECEIVED` guard — routes_intake.py:174

## Deliberately left for passes 2/3
- All of `routes_casework.py`, `routes_vendor.py` (pass 2) and `routes_quality.py`, `routes_court.py`, `routes_reads.py` (pass 3).
- The rest of `services.py`: workload/capacity gate details, balancer ranking, probation/full release, hold reopening, vendor pricing chain and custody days, PT/NC cascades, backlog report.
- List-endpoint filter sets, the four declared queue orderings and their tie behaviour, and `array_response` usage specifics (only the generic `has_more`/`meta` shape is now pinned in §2.3).
- Per-entity serializer field sets for the 8 entities outside intake/registry; JSON key order was judged not worth pinning anywhere.

### Pass 2 of 3 — casework and vendor outsourcing (subagent summary, verbatim)

Pass 2 complete. Everything was done with surgical `Edit` calls on the existing `PRD_COMPLETED.md` — **no `cp` was run**, and pass 1's 21 lines are untouched.

## File integrity
- **Before:** 474 lines / 115,512 bytes. **After:** 474 lines / 121,596 bytes.
- Tail confirmed intact: last content line is `| \`ERR_INSUFFICIENT_TESTIMONY_NOTICE\` | 422 |`, and the final 60 bytes are byte-identical to `PRD_FINALIZED.md`'s. Heading structure identical to `PRD_FINALIZED.md`; line count unchanged (all edits in-paragraph, no new sections).
- Total lines differing from `PRD_FINALIZED.md` is now 38 = pass 1's 21 + my 17.

## Counts
23 edits: **20 ambiguity-pins**, **3 mismatch-revisions**.

## Changes
- §2.10 — insert — ambiguity — hold-reopening candidate: `assigned_at_utc` tie -> earlier `created_at` -> **insertion order** (routinely the deciding key under the static clock) — services.py:512
- §2.10 — revise — **mismatch** — the reopen re-checkout is unconditional: writes `IN_ANALYSIS` + `checkout_count`+1 from *any* custody position, `CONSUMED` included; rule 8's custody guard governs client checkouts only — services.py:523-527
- §3.5 — revise — **mismatch** — paired caveat that `CONSUMED` is terminal only for client-driven movement, the §2.10 cascade being the exception — services.py:525
- §3.3 — insert — ambiguity — body FKs resolved in written order `case_id` -> `evidence_item_id` -> `method_id` — routes_casework.py:54-56
- §3.3 — insert — ambiguity — `released_at_utc` null on a new request — routes_casework.py:91
- §3.4 — insert — ambiguity — the eligibility battery is exhaustive: neither assignment nor the balancer re-tests method `validation_status`/expiry or the item's custody/seal — routes_casework.py:28-41, 174-191
- §3.4 — insert — ambiguity — auto-assign admissible only from `QUEUED`, else `ERR_EXAM_REQUEST_INVALID_STATE` — routes_casework.py:169
- §3.4 — revise — ambiguity — **handed silence #1**: balancer's 4th sort key is insertion order after `created_at` — routes_casework.py:196
- §3.5 — revise — **mismatch** — "Finally the property must be available" corrected: custody position (rule 8) and seal (rule 11) are tested *before* the method and standing checks — routes_casework.py:219-231
- §3.5 — insert — ambiguity — both bench-work calls answer 200 with the updated `ExaminationRequest` — routes_casework.py:241, 281
- §3.5 — insert — ambiguity — **handed silence #2**: `actual_hours_logged` survives a revision round, is never cleared to null, and is only overwritten by the next completion — routes_casework.py:261
- §3.6 — insert — ambiguity — the acting reviewer must resolve to an `Analyst` row (`ERR_ANALYST_NOT_FOUND`, after schema, before the state guard) — routes_casework.py:330
- §3.6 — insert — ambiguity — reviewer `employment_status`/`DECERTIFIED` tests, ranked ahead of the segregation check — routes_casework.py:333-340
- §3.6 — insert — ambiguity — hops three/four run only if the implicated examiner is `QUALIFIED`; already-`PROBATION` is left unstamped with no second release; a holderless (vendor-returned) request yields a null-`analyst_id` finding; `description` is server-generated — routes_casework.py:362-371
- §3.6 — revise — ambiguity — `UPHOLD_ANALYST` voids **every** `TECHNICAL_DISAGREEMENT` finding of the request in `OPEN`/`ROOT_CAUSE_SUBMITTED` and restores each finding's own `analyst_id` — routes_casework.py:399-408
- §3.6 — insert — ambiguity — the resolution record is written before the `revision_round` increment, so `revision_round_snapshot` is the closing round — routes_casework.py:389/410
- §3.6 — revise — **mismatch** — the requeue-branch list was non-exhaustive: added below-minimum-training probation and the no-holder (vendor-return) case — services.py:514-516
- §3.7 — insert — ambiguity — `shipped_at_utc`, `returned_at_utc`, `custody_days`, `final_invoice_cents`, `variance_cents`, `cancellation_reason` all start null; every engagement operation answers with the engagement — routes_vendor.py:60-67, 80/105/154/187
- §3.7 — insert — ambiguity — `ERR_INVALID_INTERVAL` sits behind the request state guard and ahead of all four award gates — routes_vendor.py:30-36
- §3.7 — insert — ambiguity — `shipment_note` is accepted but neither persisted nor echoed — routes_vendor.py:88
- §3.7 — insert — ambiguity — the engagement state guard precedes the item custody check, so a second confirm-shipment reports `ERR_VENDOR_ENGAGEMENT_INVALID_STATE` — routes_vendor.py:89-96
- §3.7 — insert — ambiguity — the contract ceiling is an award-time gate only; an over-ceiling final invoice is recorded — routes_vendor.py:125-131
- §3.7 — insert — ambiguity — the `VENDOR_VARIANCE` finding carries a server-generated `description` — routes_vendor.py:147-150

## Deliberately left for pass 3
- §3.8/§3.9 and everything in `routes_quality.py`, `routes_court.py`, `routes_reads.py` (incl. the `GET /workload` and `GET /backlog-report` endpoint contracts — I verified the *formulas* in §3.4/§2.10 against `services.py` but did not touch the read-endpoint prose).
- §2.8 rule 5's global body-FK ordering: I scoped the pin to §3.3 (the only multi-FK body in my partition) rather than editing the shared rule.
- `restore_to_qualified`'s field effects are already pinned in §3.8 line 294, so §3.6 relies on that; pass 3 owns line 294.
- Rank of `ERR_METHOD_NOT_CONSUMPTIVE` within §2.8 is still unranked (it only ever collides with the state guard, which impl checks first) — left as-is.

### Pass 3 of 3 — quality system, court, reads (subagent summary, verbatim)

Pass 3 complete. All 16 edits landed in place; no `cp` was run.

## Before / after
- Before: 474 lines, 121,596 bytes
- After: **474 lines, 127,820 bytes** (line count unchanged — every edit was an in-paragraph insert/revise)

## Counts
- Ambiguity-pins: **13**
- Mismatch-revisions: **3**

## Changes
- `§2.3` — insert — ambiguity — list-filter semantics: each declared query param is an exact-equality string match on the same-named field, conjunctive; a value outside the enum domain empties the page (200, `total_count` 0) rather than 400; undeclared query params are ignored — `routes_reads.py:20-27`
- `§2.3` — insert — ambiguity — all four declared queue orderings break a surviving tie by insertion order, and `id` is never a tie-break — `routes_reads.py:128-129,160-161,185,234`
- `§2.8 rule 5` — insert — ambiguity — generalised body-FK resolution order beyond §3.3: resolved in the order §3 writes them (`analyst_id`->`method_id` for PT; `examination_request_id`->`analyst_id` for findings and court events) — `routes_quality.py:26-27,154-158`, `routes_court.py:38-39`
- `§2.8 rule 6` — insert — ambiguity — the analyst-identity binding applies to exactly three writes and to **no** read; an Analyst may read any examiner's record/workload/PT — `routes_reads.py:38-114`, `routes_quality.py:56`
- `§3.8` — revise — mismatch — PT assignment applies no gate at all: PRD had named a nonexistent `employment_status` `INACTIVE`, and neither the standing battery nor the method-validation gate is consulted (a `DRAFT`/`RETIRED` method and a `DECERTIFIED` examiner are both admissible) — `routes_quality.py:19-32`
- `§3.8` — insert — ambiguity — the mark is rounded to 2dp *before* grading, so 89.995 grades `PASS` — `routes_quality.py:116-117`
- `§3.8` — insert — ambiguity — a `FAIL` by a `DECERTIFIED` examiner increments the counter but moves/sheds nothing; and per-stage `version` semantics (0 increments for `INCONCLUSIVE` or a no-op `PASS`, 2 for a `PASS` that clears a counter then restores, 2 for a `FAIL` from `QUALIFIED`) — `routes_quality.py:78-102`, `services.py:469-479`
- `§3.8` — insert — ambiguity — PT-generated findings carry `examination_request_id` null, are opened after the cascade, and are not a second trigger of the probation move — `routes_quality.py:123-137`
- `§3.8` — insert — ambiguity — the MAJOR/CRITICAL probation move fires only from `QUALIFIED` (no re-stamp of `probation_entered_at_utc`, no move up from `SUSPENDED`/`DECERTIFIED`), and the finding is written before the move — `routes_quality.py:159-165`, `services.py:458-466`
- `§3.8` — insert — ambiguity — CAPA escalation fires on exactly the second rejection; a third or later rejection counts and clears but leaves `severity`/`due_utc` alone — `routes_quality.py:207-211`
- `§3.8` — insert — ambiguity — `closure_note` is length-unconstrained and not persisted on the finding — `routes_quality.py:221`
- `§3.9` — insert — ambiguity — malformed `as_of_utc` -> `ERR_INVALID_REQUEST` (400); `discipline` is never checked against the enum, so an unknown one returns a zeroed report — `routes_reads.py:260-270`, `services.py:657-663`
- `§3.9` — insert — ambiguity — ages are never clamped: a past `as_of_utc` yields negative ages that weight/average normally (index can go below zero) and land in the first bucket — `services.py:669-682`
- `§3.9` — insert — ambiguity — court-event creation: `testimony_note`/`cancellation_reason` start null, `notice_days` may be negative, the six-way rule order (duplicate -> `RELEASED` guard -> interval -> referential -> calendar -> notice), and no standing battery on scheduling/confirming/testifying — `routes_court.py:40-60`
- `§4` (PT row) — revise — mismatch — "on a validated method" -> "on any registered method, whatever its validation status" — `routes_quality.py:19-27`
- `§4` (evidence-item list row) — revise — mismatch — filter set completed with the undocumented `item_type` — `routes_reads.py:136-140`

Verified-and-unchanged in my partition (no edit needed): the calendar guard's +/-60-min extended-interval semantics, the notice floor and subpoena waiver, all 12 single-read and 9 list-read role sets against §4, the workload document's 9-field set and every one of its formulas (§3.4 already exhaustive), the turnaround merge logic, the backlog buckets/index/threshold, `restore_to_qualified`'s field effects at line 294, and read-time `overdue` recomputation.

## Closing integrity check
- Line count 474, byte count 127,820 — **pass**
- Last content line is `| \`ERR_INSUFFICIENT_TESTIMONY_NOTICE\` | 422 |` (line 473) — **pass**
- §4 endpoint table has 64 data rows — **pass**
- §5 error catalogue has 61 data rows — **pass**
- PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (127,820 vs 108,245; 52 changed lines across all three passes) — **pass**
- PRD.md and PRD_FINALIZED.md unmodified: still byte-identical to each other at 108,245 bytes, mtimes 16:57 and 18:28, both predating this pass — **pass**
- No `cp` was executed at any point; every change went through the Edit tool on the existing PRD_COMPLETED.md — **confirmed**

### Step 9 orchestrator verification (independent)

Re-checked all of pass 3's closing claims myself rather than accepting them: PRD_COMPLETED.md is 474 lines / 127,820 bytes; `diff PRD_FINALIZED.md PRD_COMPLETED.md` reports 52 changed lines (so the scan definitively landed — a byte-identical PRD_COMPLETED.md would have meant the scan never ran); the §4 endpoint table still holds exactly 64 data rows and §5 exactly 61; the tail is the intact final error row. PRD.md and PRD_FINALIZED.md remain at 108,245 bytes each. Also confirmed via `find -newer` that no .py file under implementation/, test_suite/, or test_helpers/ was modified after the green sweep wrote results.1.json at 18:25 — Steps 8 and 9 were documentation-only, so the 8x 100/100 sweep result still describes the shipped artifacts exactly. Removed the three Step 9 scratch directories and all __pycache__.

Pipeline complete: workspace/PRD_COMPLETED.md is written.
