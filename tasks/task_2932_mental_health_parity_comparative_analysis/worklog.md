## Step 1: Create task directory — 2026-09-05T18:11:15.275Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2932_mental_health_parity_comparative_analysis and its workspace/ subdirectory. Index 2932 was pre-assigned by the orchestrating caller; no index scan or auto-allocation performed.


## Step 2: Generate scaffold — 2026-09-05T19:24:48.831689775Z

Step 2 complete for task 2932. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_2932_mental_health_parity_comparative_analysis/`; `worklog.md` and `workspace/` were left untouched, scratch confined to `.scratch/step2/`.

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2932_mental_health_parity_comparative_analysis/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2932_mental_health_parity_comparative_analysis/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2932_mental_health_parity_comparative_analysis/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    41
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  654

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**SCAFFOLD.yaml** (2275 lines, 127 KB) — `api_prefix: /parity`, no `scaffold_difficulty_design` / `scaffold_corner_design` keys present. 12 entities (Administrator, PlanYear, BenefitClassification, TreatmentLimitation, ParityTest, NqtlItem, ComparativeAnalysis, VendorDataRequest, DataSubmission, CorrectiveActionPlan, RegulatorRequest, ParticipantNotice), 9 state machines, 2 concurrency rules, 9 calculations, 34 validations (single total priority order), 41 endpoints, 53 errors, 4 roles (PlanSponsor / Administrator / ComplianceOfficer / Regulator, `segregation_of_duties`). Profile: `compliance_audit` + `ledger_reconciliation`, layers `dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency`, flat topology, cyclic state shape, immediate consistency. The "harder than expert level" directive did not leak into the `scenario` key.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1643 lines) — single top-level key, all 9 rules, 20 instances: `dual_variant_calc` 2, `combinatorial_formula` 3, `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 2, `boundary_precision_check` 3, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2.

**SCAFFOLD_CORNER_DESIGN.yaml** (3332 lines) — single top-level key, all 9 guide sections, 73 instances (51 full test recipes + 22 `excluded_because` stubs each citing a covering §1.8 instance): entities 12, state_machines 13, calculations 12, validations 15, endpoints 6, errors 4, rbac 5, cross_cutting_layers 5, consistency_model 1.

Independent coverage checks beyond the lint: all 53 error codes are triggered by at least one instance, and all 41 declared endpoints are exercised by at least one structured `call:` (added `every_declared_read_endpoint_returns_its_row_or_collection` to close the last 12 read-only endpoints). Note for later steps: flow-style `captures:` values indexing a collection must be quoted (`"$.data[0].id"`) — unquoted `[` breaks YAML flow mappings.

## Step 3: Copy shared files — 2026-09-05T19:24:48.841464190Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md ($(wc -c < workspace/INSTRUCTION.md) bytes).

## Step 4: Generate PRD — 2026-09-05T19:36:34.441252924Z

PRD generated and verified.

## Output
`workspace/PRD.md` — **442 lines**, built incrementally (one `Write` for §1–§2, four heredoc appends for §3, one generated append for §4–§5).

## Top-level sections
1. Introduction
2. Global Specifications & System-Wide Principles — 2.1 Actors and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Compliance Clock · 2.6 Numeric Precision and Rounding · 2.7 Plan-Year Gating · 2.8 Cascade Propagation and Derived Values · 2.9 Segregation of Duties · 2.10 Stale-Version Guards · 2.11 Request Validation Order
3. Business Logic & Workflows — 3.1 Standing Up the Review · 3.2 Benefit Classifications and Limitation Levels · 3.3 Substantially-All and Predominant Standards · 3.4 NQTL Inventory and Comparative Analyses · 3.5 Vendor Production: Requests, Deadlines and Escalation · 3.6 As-Applied Evidence and Automatic Validation · 3.7 Stringency in Operation and the Parity Determination · 3.8 Corrective Action and the Remediation Liability Ledger · 3.9 Answering the Regulator
4. Endpoint Definitions
5. Error Code Catalogue

## Coverage
- **Endpoints: 41 / 41** present in §4 (4 columns: Method, Path, Description, Authorized Role(s)); programmatically verified each scaffold `path` appears as a table cell.
- **Error codes: 53 / 53** present in §5 (2 columns: Error ID, HTTP Status); additionally **all 53** are mentioned by name in §2 or §3 narrative, so §5 needs no conditions column.
- 12 entities, 35 state transitions across 9 machines, 9 calculations (with pinned evaluation order, constants and rounding), 34 validations (full ordered ladder in §2.11), 2 OCC rules.

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 101 required, 101 present, 0 missing
- endpoints[].request_body: 58 required, 58 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
Status: PASS
```
(Two passes run; second pass used exact backtick-token matching rather than word-splitting — still 0 missing.)

```
Rule coverage check:
- validations[] with priority: 34 checked, 34 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_plan_year_version / expected_nqtl_item_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 35 checked, 35 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 34 checked, 34 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 41 checked, 41 expressed, 0 missing
- entities[].fields[] structured content: 101 checked, 101 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (review CERTIFIED/INSUFFICIENT, determination COMPLIANT/VIOLATION, decision APPROVED/REJECTED, closure COMPLETED/ABANDONED, submission VALIDATED/REJECTED, escalation NOTICE_SENT/BREACH_DECLARED, adjudicate ACCEPTED/INSUFFICIENT, three WITHDRAWN legs, predominant single-level/combination), 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 887
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is a byte-identical match to `section-2.2-response-structure.md`; no fuzzy/approximating words ("approximately", "roughly", "conservatively", "about", …) anywhere; no meta-commentary (the only "benchmark" hits are the domain's own reimbursement-benchmark submission type).

## Tail completeness
The file ends inside §5's table at a complete row boundary. Last two lines, quoted verbatim:

```
| `ERR_NO_REQUESTED_ITEMS` | 409 |
| `ERR_LIABILITY_CAP_EXCEEDED` | 409 |
```

`ERR_LIABILITY_CAP_EXCEEDED` is the final entry in the scaffold's `errors[]` list, so the document ends exactly where §5 should end — no truncation, no audit footer.

## One judgement call worth flagging
Scaffold validation priority 19 (`ERR_APPROVER_IS_DETERMINER`) has `applies_to: "POST /parity/corrective-action-plans/{id}/decision"` with no outcome qualifier, while the state-machine table lists the segregation-of-duties precondition only on the `DRAFT → APPROVED` leg. I followed the validations table (the priority-ordered authority, which qualifies by outcome elsewhere — e.g. priority 34 says "with outcome == APPROVED") and wrote the independence check as applying to **both** decision branches. The liability-cap check remains approval-only, per priority 34.

Nothing outside `workspace/PRD.md` was written; scratch artifacts live in `.scratch/step4/` and neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

ORCHESTRATOR VERIFICATION: independently confirmed 442 lines, 5 top-level sections, tail ends at the final `ERR_LIABILITY_CAP_EXCEEDED` row (a real section boundary, not mid-sentence). Grep for "harder than expert" / "expert level" / "scaffold" / "test_recipe" in PRD.md returned nothing — no difficulty-directive or scaffold leak.

## Step 6: Generate implementation — 2026-09-05T20:07:26.525007456Z

(Steps 5 and 6 were launched concurrently in a single assistant message, so Step 6's impl generator never saw test_suite/. Step 6 returned first; its summary is recorded here, Step 5's below.)

Both smoke suites are green and all my smoke servers are shut down (individually, by PID; no `pkill` was ever used).

## Deliverable

`workspace/implementation/`

| file | lines | file | lines |
|---|---|---|---|
| `app.py` | 91 | `routes/__init__.py` | 1 |
| `auth.py` | 39 | `routes/administrators.py` | 50 |
| `calc.py` | 348 | `routes/plan_years.py` | 139 |
| `enums.py` | 60 | `routes/classifications.py` | 119 |
| `envelope.py` | 100 | `routes/nqtl_items.py` | 140 |
| `errors.py` | 133 | `routes/analyses.py` | 200 |
| `helpers.py` | 34 | `routes/vendor_requests.py` | 246 |
| `recompute.py` | 151 | `routes/data_submissions.py` | 27 |
| `serialize.py` | 197 | `routes/corrective_action_plans.py` | 138 |
| `shape.py` | 178 | `routes/regulator_requests.py` | 136 |
| `store.py` | 156 | `routes/clock.py` | 30 |
| `start.sh` | 16 | `requirements.txt` | 1 |

2713 lines of Python across 22 modules; every module compiles (`py_compile`); stale `__pycache__` removed. Storage is plain module-level dicts in `store.py`, nothing seeded — a fresh boot returns `total_count: 0` / `data: []` on every list endpoint.

## Coverage, verified mechanically against the PRD

- **Endpoints: 41 declared, 41 registered.** I diffed `app.url_map` against the §4 table; the only differences are path-parameter *names* (`<item_id>` vs the PRD's `{id}`), so the route set matches exactly. `GET /parity/administrators` (no list endpoint exists in §4) correctly returns 405.
- **Error codes: 53 declared in §5, 53 in `errors.py`, exact set match** — no missing, no extra.
- 9 calculations, 9 state machines, the §2.11 ladder and both OCC guards (`expected_plan_year_version`, `expected_nqtl_item_version`) implemented; no endpoints, fields or behaviours beyond the PRD.

## Smoke results (two passes, fresh boots via `bash start.sh`)

Pass 1 (~75 assertions) — **0 failures.** Full happy path plus: substantially-all ratio 0.9 / predominant 20 / PASS; denial rates 0.075337 vs 0.037114 → disparity 2.0298 with `as_applied_flag` true; network gap 0.28; index 10.00 without credit and 8.45 with 4 factors + 5 standards; 45-day `due_at` 2026-09-15 vs 30-day `regulatory_due_at` 2026-08-31; VIOLATION → notice → REMEDIATION; CAP approval freezing 1,655,433 cents and closure releasing it to 0; regulator ACCEPTED → plan year CLOSED → child write refused; clock monotonicity + inline recomputation report.

Pass 2 (57 assertions, `smoke2.py`) — **0 failures.** Deliberately adversarial paths: `ERR_NOT_YET_OVERDUE` at `due_at` exactly and at the grace boundary exactly; NOTICE_SENT then BREACH_DECLARED then `ERR_ESCALATION_ALREADY_DECLARED`; cooperation 85.00 COOPERATIVE → 60.00 DELINQUENT with the regulatory basis diverging (100.00 → 75.00 → 60.00); a breach degrading a plan year the request never scoped; `ERR_PRODUCTION_WINDOW_CLOSED` vs `ERR_REQUEST_ALREADY_FULFILLED`; the bounded revision loop (rounds 1-3 then `ERR_REVISION_LIMIT_REACHED`); supersession → WITHDRAWN → `ERR_ANALYSIS_ALREADY_SUPERSEDED`; `ERR_IN_OPERATION_DATA_MISSING` vs a successful certification; `ERR_STALE_PLAN_YEAR_VERSION` and state-before-version precedence; `ERR_APPROVER_IS_DETERMINER` reported *before* `ERR_LIABILITY_CAP_EXCEEDED`; tier-A credit clamping completeness to 100.00; the 14-day insufficiency extension and `ERR_RESPONSE_WINDOW_EXPIRED`; pagination `meta` (`limit`/`offset`/`total_count`/`has_more`) across three rows and `limit=0` → `ERR_VALIDATION`; blank `X-User-ID` → 401 `ERR_MISSING_IDENTITY_HEADERS`.

Three "failures" during development were all defects in my own smoke expectations, not the implementation: a two-day measurement-period gap that the normative formula legitimately accepts, an assumption that an item lacked a CERTIFIED analysis when the certification had in fact succeeded on validated denial-rate evidence, and `MH_SUD_ONLY` instead of the PRD's `MENTAL_HEALTH_SUD_ONLY` (which the server correctly rejected with 422). One real implementation fix was made earlier: the determination guard is state-only (`ANALYSIS_SUBMITTED` or `COMPLIANT`), not outcome-dependent.

I did not read, list or glob `test_suite/`, `test_helpers/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`; nothing outside `implementation/` and `.scratch/step6/` was created or modified.

## Step 5: Generate unit tests — 2026-09-05T21:17:55.760243599Z

(Launched concurrently with Step 6. The generator subagent DIED mid-run on a transient API error after finishing queue A and part of queue B. Per the known failure mode, the orchestrator did NOT respawn a fresh generator — it computed the exact remaining-instance to-do list itself and resumed the SAME agent via SendMessage, so the suite stayed self-consistent. Its delta summary follows.)

Step 5 is complete. All 7 remaining instances are written, and the whole suite compiles and is pyflakes-clean.

## Delta summary — resumed run

**Files created/appended (task root, nothing under `workspace/`)**

| File | Lines | Tests | Instances |
| --- | --- | --- | --- |
| `test_suite/test_13_validations.py` (appended) | 1069 | 16 | all 10 non-stub `validations` instances |
| `test_suite/test_14_endpoints.py` (new) | 618 | 4 | 4 `endpoints` |
| `test_suite/test_15_errors.py` (new) | 285 | 4 | 4 `errors` |
| `test_suite/test_16_rbac.py` (new) | 427 | 4 | 4 `rbac` |
| `test_suite/test_17_cross_cutting_layers.py` (new) | 243 | 2 | 2 `cross_cutting_layers` |
| `test_suite/test_18_consistency_model.py` (new) | 134 | 1 | 1 `consistency_model` |

**New tests emitted for the 17 assigned instances: 17** (one per instance). No `test_helpers/` file was forked or changed — every new test reuses the existing factories, fixtures, constants and role-header builders.

**Skipped instances: none.** All 17 passed the PRD-first two-condition filter — each has a verbatim rule-bearing PRD sentence and a uniquely derivable outcome.

**Suite totals:** `test_suite/` 7562 lines / 106 tests, `test_helpers/` 2438 lines. A tag audit confirms every non-stub design instance in both queues has a matching `Design:` line and no test carries a tag absent from the yaml. `ls -d workspace/test_*` -> nothing; no strays to relocate.

## Design/PRD conflicts — I asserted the PRD, never a weakened assertion

- `Corner/cross_cutting_layers/version_increments_on_every_write_and_never_on_a_read` — design asserts `stringency_in_operation_index == 0.55`, but its own parenthetical (`0.3 * 0.9235 * 10`) and PRD §3.8's worked contrast case both give 2.7705, and with no analysis there is no documentation credit. Asserted **2.77**. The same instance asserts "`updated_at` advances with the version"; the logical clock is frozen at `2026-08-01T00:00:00Z` and the PRD never pins `updated_at` to it, so I asserted what is derivable — both stamps ISO-8601, `updated_at` never preceding `created_at` — plus the exact version arithmetic (`1` at creation, unchanged across two reads, exactly `2` after the sibling submission).
- `Corner/validations/determination_outcome_contradicting_the_evidence_rejected` — design asserts `AT_RISK`; PRD §3.1's ladder uniquely derives `COMPLIANT`. Asserted COMPLIANT/OPEN.
- `Corner/validations/rewinding_the_logical_clock_rejected` — design asserts `data == null`; PRD line 94 declares an inline report object. Asserted the report shape.
- `Corner/endpoints/every_declared_read_endpoint_returns_its_row_or_collection` — design opens the regulator request *after* the VIOLATION determination, but PRD §3.9 only declares the `OPEN -> UNDER_REGULATOR_REVIEW` leg. Reordered the setup to open it first (§3.1 explicitly allows `UNDER_REGULATOR_REVIEW -> REMEDIATION`); no assertion changed.
- Carried forward from earlier sessions: `Difficulty/resource_temporal_overlap/production_window_is_half_open_so_adjacency_is_accepted` (design 85.00/1-late vs PRD-derived 100.00/0), `Corner/state_machines/adjudicating_accepted_closes_the_plan_year_and_locks_further_writes` (its setup leaves an AT_RISK year, so PRD 334 derives "status left exactly as it was"), `Corner/state_machines/rerunning_a_parity_test_supersedes_the_prior_computation` (its corrective write is refused by `ERR_PLAN_YEAR_NOT_OPEN`).

ORCHESTRATOR VERIFICATION (independent of the subagent): 106 test functions across 17 test files; 123 `Design:` tag occurrences resolving to all 20 difficulty + all 51 corner non-stub instances with ZERO missing and ZERO orphan tags; every test function carries EXACTLY ONE tag (0 dual-tagged, 0 untagged); `compileall` clean on both directories; grep for `pytest.mark.skip` / `xfail` returns nothing; no `workspace/test_*` strays.

## Step 7: Run tests and iterate — 2026-09-05T21:28:04.430065965Z

All 8 rounds green: 106/106 passed in every round.

## Summary

**Iterations run:** 2 sweeps (baseline + verification). Baseline: 104/106 in all 8 rounds, 2 deterministic failures. Verification after fix: 106/106 in all 8 rounds, 0 failed / 0 errors / 0 skipped, ~191s per round.

**Tests deleted:** None. No test failed STEP 1 (PRD coverage) or STEP 1b (unique derivability).

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — the implementation was PRD-faithful on both failures.

**Fixes applied to `test_suite/` (STEP 2, test-vs-PRD consistency):**
- `test_suite/test_14_endpoints.py` — `test_the_compliant_branch_answers_with_the_item_and_mints_no_disclosure`: added the missing `201` argument to `validate_success(...)` on the `POST /parity/nqtl-items/{id}/determinations` call.
- `test_suite/test_17_cross_cutting_layers.py` — `test_both_declared_concurrency_guards_answer_412_and_clear_after_a_re_read`: same fix on its post-re-read determination call.

**Diagnosis:** both tests failed with `AssertionError: Expected 200, got 201` on the determination endpoint. `validate_success` defaults `expected_status=200`, and these two call sites omitted the explicit status. PRD.md line 338 settles it verbatim: *"Operations that bring a new resource into existence — ... or recording a parity determination — return `201 Created`. ... A determination is a creation in this sense even though the resource returned in `data` is the updated NQTL item, because the determination itself is a new fact on the record."* The implementation's 201 is correct; these were the minority call sites — `test_03_transitive_cascades.py:74` already passed `201` explicitly for the same endpoint, and `fixtures.record_determination` uses `get_success_data` (status-agnostic). Classic minority-call-site symbol/argument drift in the test artifact, so the minority was made to match the PRD-backed majority. No assertion was weakened; the fix tightened both tests to assert the PRD-declared status code.

**Note:** the `Killed` string visible in `workspace/round.*.log` is unrelated host-level noise interleaved into runner stdout, not a server or test death — all rounds booted, ran, and reported cleanly.

ORCHESTRATOR VERIFICATION: all 8 `workspace/implementation/results.$i.json` files exist and each independently reports `passed=106 total=106 failed=0 errors=0 skipped=0`; `workspace/SWEEP_DONE` sentinel written at 2026-09-05T21:27:15Z with all 8 rounds accounted for. The sweep ran under `setsid nohup bash sweep.sh` from the pre-written script, so no reaping occurred.

ORCHESTRATOR DECISION on Step 8: NOT skipped. The skip condition requires all four counts to be zero; Step 7 made 0 deletions, 0 `test_helpers/` fixes and 0 `implementation/` fixes, but 2 `test_suite/` fixes, so Step 8 runs with those two items as its `<step_7_diff>`. Both are pure test-artifact argument drift against a PRD sentence that already pins 201, so a byte-identical or near-identical PRD_FINALIZED.md is a legitimate outcome here and is not evidence Step 8 failed to run.

## Step 8: Finalize PRD — 2026-09-05T21:30:08.434506752Z

Done. `PRD_FINALIZED.md` is byte-identical to `PRD.md`, and that is the correct output here.

## Line counts
- `PRD.md`: 442 lines — `PRD_FINALIZED.md`: 442 lines — **0.0% delta** (identical md5 `977d46d0e208d96a73885631f30e3c31`).

## Changes
- **None.** Both `<step_7_diff>` items were pure test-artifact argument drift, not PRD silence and not PRD/impl mismatch.

## Per-item verification log

**Item 1 & 2 (single shared subject): `test_14_endpoints.py` and `test_17_cross_cutting_layers.py` — missing `201` argument on `validate_success(...)` for `POST /parity/nqtl-items/{id}/determinations`**

(a) **Subject identified:** the HTTP success status code returned by the determination endpoint, and by extension the create-vs-modify status-code rule for every POST in the API.

(b) **Impl paths enumerated (read/grepped):**
- `routes/nqtl_items.py:132` — the Step 7 site: `return success(serialize.nqtl_item(item), 201)`.
- `envelope.py:35` — `def success(data, status=200)`; the 201 is explicit at the callsite, not incidental.
- All 12 explicit `201` callsites, cross-checked one-to-one against the 12 operations PRD.md line 338 enumerates: `administrators.py:43`, `plan_years.py:55` (plan year), `plan_years.py:116` (classification), `classifications.py:61` (treatment limitation), `classifications.py:109` (parity test), `nqtl_items.py:72` (inventory), `nqtl_items.py:132` (determination), `analyses.py:85` (draft analysis), `vendor_requests.py:79` (production request), `vendor_requests.py:207` (data submission), `corrective_action_plans.py:53` (CAP), `regulator_requests.py:56` (regulator request). Exact bijection — no impl 201 is unnamed by the PRD, and no PRD-named creation returns something else.
- All remaining POST routes (`vendor_requests.py:97` escalate, `analyses.py:102/130/182` submit/review/reopen, `corrective_action_plans.py:70/111` decision/closure, `regulator_requests.py:73/105` respond/adjudicate, `clock.py:16`) — all fall through to `success(...)` default 200, matching the PRD's "advance or modify an existing resource, and every read, return `200 OK`".
- Test-side confirmation of the drift diagnosis: `test_14_endpoints.py:217` and `test_17_cross_cutting_layers.py:135` now pass `201`; `test_helpers/assertions.py:150` already hard-codes `201` in its creation helper, so the majority convention was PRD-backed all along.

(c) **Wording adjustment:** none needed. PRD.md line 338 already uniquely determines the behavior — it names "recording a parity determination" in the 201 list and then removes the only plausible ambiguity explicitly: *"A determination is a creation in this sense even though the resource returned in `data` is the updated NQTL item, because the determination itself is a new fact on the record."* A fresh implementer reading that sentence cannot land on 200. Any edit here would have been redundant restatement at best, and a NO-NEW-MISMATCH risk at worst (e.g. singling out determinations would have implicitly de-emphasized the other 11 creations that share the same rule).

Consistent with the note in my instructions: no implementation fix and no test deletion occurred in Step 7, the only test change tightened two minority callsites toward an already-pinned PRD sentence, so there is no PRD-silence or PRD-mismatch to patch. I did not scope-creep beyond `<step_7_diff>` to manufacture an edit.

ORCHESTRATOR NOTE: byte-identity verified independently by md5sum. This is a legitimate Step 8 outcome — Step 7 applied zero `implementation/` fixes and zero deletions, so there was no PRD-silence site to patch. Step 9, by contrast, must NOT be identical, and is being run as three sequential module-partitioned passes over one shared PRD_COMPLETED.md (pass 1 does the `cp`; passes 2 and 3 must not).

## Step 9: Complete PRD — 2026-09-05T21:57:01.161171080Z

Run as THREE sequential module-partitioned passes over one shared PRD_COMPLETED.md (pass 1 did the `cp`; passes 2 and 3 edited in place after verifying the inherited md5). Combined: 43 edits, 442 -> 446 lines, 98,173 -> 115,200 chars (+17,027, +17.3%).

### Pass 1 — cross-cutting core (app, auth, envelope, errors, shape, helpers, store, serialize, enums)

Source `PRD_FINALIZED.md` 442 lines / 98,173 chars -> `PRD_COMPLETED.md` 444 lines / 106,010 chars (+2 lines, +7,837 chars), md5 `258d5688e13595b2011929bce09a4554`. **15 ambiguity-pins, 2 mismatch-revisions.**

- §2.1 — insert — ambiguity — only a wholly empty header counts as empty; a whitespace-only value is present and non-empty, so a whitespace `X-User-Role` fails role recognition rather than the missing-header check — `auth.py:16-19`
- §2.1 — insert — ambiguity — the `Administrator` identity binding is documentary; `X-User-ID` is never resolved against the administrator collection and an unknown value never yields a 404 — `auth.py:13-24`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 characters from `A`-`Z` and `0`-`9` — `envelope.py:12,16`
- §2.2 — insert — ambiguity — `review_note` / `rationale` / `decision_note` / `closure_note` / `response_note` / `adjudication_note` are validated but never persisted or echoed; `rationale` required non-empty, other five optional non-empty, no max length — `serialize.py:102-184`
- §2.2 — revise — mismatch — the error envelope covers 5xx too, not "4xx status codes" only — `app.py:77-81`
- §2.3 — insert — ambiguity — an empty, fractional or non-numeric `limit`/`offset` is `ERR_VALIDATION`; surrounding whitespace tolerated; a valueless parameter is not an omitted one — `envelope.py:67-91`
- §2.3 — insert — ambiguity — rows sharing a `created_at` are ordered by server write sequence, so ordering is total and stable — `helpers.py:31`, `store.py:138-139`
- §2.3 — insert — ambiguity — filters are exact-match on the stored value, applied before ordering and windowing; an out-of-set value matches nothing rather than failing validation; booleans matched as `true`/`false`; undeclared query params ignored; the four pagination `meta` fields appear only on list endpoints — `helpers.py:9-34`, `envelope.py:25-55`
- §2.4 — insert — ambiguity — nothing is seeded or preloaded; the store starts empty and lists return `total_count` 0 — `store.py:1-5,27-49`
- §2.5 — insert — ambiguity — instants truncated (not rounded) to 3 fractional digits; `api_request_timestamp`, `created_at` and `updated_at` are wall-clock and never compared to deadlines; client-supplied dates stored/returned verbatim — `store.py:56-59,105-134`, `envelope.py:19-22`
- §2.5 — insert — ambiguity — "advanced by N calendar days" means exactly N x 24h in UTC — `store.py:101-102`
- §2.5 — revise — mismatch — `is_overdue` is derived at render time, not stored, so a clock move neither refreshes a vendor request's `updated_at` nor increments its `version`; only administrators and plan years are re-stamped, and only when a derived value actually moves — `serialize.py:118-119`
- §2.5 — insert — ambiguity — `current_utc` re-rendered canonically rather than echoed; `recomputed_administrator_count`/`recomputed_plan_year_count` are the totals visited, not the number changed; 0 when none exist; HTTP 200 — `routes/clock.py:26-30`, `recompute.py:151`
- §2.6 — insert — ambiguity — non-monetary decimals are JSON numbers; stated precision fixes the rounding scale, not the printed form (`100.0`, `2.0`, whole `level_value`); compare numerically — `envelope.py:94-100`, `serialize.py:24`
- §2.11 step 6 — insert — ambiguity — absent/empty/unparseable body = empty object; non-object body = `ERR_VALIDATION`; optional `null` = absent and takes the default while required `null` fails its type check; undeclared fields (including a client `id`) ignored; strict typing; instants accept `T`/`t`, any or no fractional digits, `Z`/`z`/zero offset, never a non-zero offset — `shape.py:13-19,26-27,76-111,155-160`, `store.py:21-24,66-98`
- §2.11 closing paragraph — insert — ambiguity — a body FK that is absent, `null`, empty-string or non-string skips step 5 and is reported at step 6 as `ERR_VALIDATION`, reserving the nine 404s for well-formed identifiers that name nothing — `shape.py:30-35`
- §5 — insert — ambiguity — `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) sit outside the catalogue; the routing pair is decided before identity headers; trailing slashes are not significant — `app.py:45,68-81`

Verified already correct, no edit needed: all 53 error ids and statuses in `errors.py` match §5 exactly in both directions; every one of the 103 field names emitted by `serialize.py` and every enum literal in `enums.py` already appears in the PRD; the `auth.py` ladder order, §2.4 id/version/touch semantics, clock epoch `2026-08-01T00:00:00Z`, participant-notice shape, and `has_more`/`total_count` semantics were already uniquely pinned.

### Pass 2 — calculation engine and classification/NQTL/analysis routes (calc, recompute, routes/classifications, routes/nqtl_items, routes/analyses)

444 lines / 106,010 chars -> 446 lines / 112,550 chars, md5 `b0724a4248c6552cef46988c6afef6b1`. **10 ambiguity-pins, 4 mismatch-revisions.**

- §2.8 — insert — ambiguity — pinned the conditional-recompute rule: re-deriving an existing row's derived fields re-stamps it only when a value actually moves; the version increments §3 states outright are unconditional; creation-time derivation is not a mutation — `recompute.py:67-69,101-104,111-117`
- §2.8 — revise — mismatch — "every affected row's `updated_at` is refreshed" -> "every row the request actually changes", since a no-op recompute re-stamps nothing — `recompute.py:67`
- §3.2 — insert — ambiguity — `level_value` compared numerically for supersession (`20` = `20.0`); recording a limitation level re-stamps nothing but the superseded row — `routes/classifications.py:42-61`
- §3.3 — revise — mismatch — prose claimed parity tests "may be read individually per classification"; no such endpoint exists (only the list route, matching §4) — `routes/classifications.py:112-119`
- §3.3 — insert — ambiguity — the plan-year recompute runs on *every* test creation, not only superseding ones, and supersession is evaluated after the arithmetic, so `ERR_EMPTY_TEST_POPULATION` leaves the earlier test in `COMPUTED` — `routes/classifications.py:87-108`
- §3.4 — insert — ambiguity — a new NQTL item is returned with `version` 1 even when pre-existing evidence gives it a non-zero index and a true flag on the spot — `routes/nqtl_items.py:64-70`
- §3.4 — insert — ambiguity — analysis creation bumps the item's `version` unconditionally regardless of status; `INVENTORIED` (plus the supersede-`SUBMITTED` leg) is the only status the cascade advances; the just-written `DRAFT` is immediately the analysis the index reads — `routes/analyses.py:75-82`
- §3.4 — insert — ambiguity — the supersede-`SUBMITTED` item reset requires *both* the superseded row in `SUBMITTED` **and** the item still in `ANALYSIS_SUBMITTED` — `routes/analyses.py:80-81`
- §3.4 — revise — mismatch — submission required "the owning item to be in `ANALYSIS_DRAFTED`"; impl never checks the item and forces its status to `ANALYSIS_SUBMITTED` from whatever it held. Also added the plan-year recompute the impl performs — `routes/analyses.py:104-126`
- §3.4 — insert — ambiguity — review branches diverge in re-stamping: certification touches the item only if the index/flag actually moves and never recomputes the plan year; the insufficient branch bumps the item unconditionally and does recompute the plan year — `routes/analyses.py:152-167`
- §3.7 — insert — ambiguity — latest-analysis selector's third tie-break is write order (later write first), and the ranking is status-blind beyond excluding `WITHDRAWN`, so a newer draft displaces an older certified analysis as the credit source — `calc.py:220-227`
- §3.7 — revise — mismatch — "an item already in `COMPLIANT`, which may be re-determined to `VIOLATION`" implied only that outcome; impl admits both outcomes from both starting states, so `COMPLIANT`->`COMPLIANT` is accepted and still re-stamps the actor and bumps both versions — `routes/nqtl_items.py:102`
- §3.7 — insert — ambiguity — the certified-analysis precondition uses the *same* selector as the documentation credit (not `created_at` alone), only that one analysis is consulted, and it is evaluated at ladder step 22 ahead of the agreement check at step 23 — `routes/nqtl_items.py:112-121`, `calc.py:220`
- §3.7 — insert — ambiguity — the five recompute points are exhaustive and are besides the inventory-time computation; reopening, a rejected submission and the clock sweep all leave the index and `stringency_flag` untouched — `recompute.py:145-151`

### Pass 3 — remaining route modules (administrators, plan_years, vendor_requests, data_submissions, corrective_action_plans, regulator_requests, clock) + final integrity check

446 lines / 112,550 chars -> 446 lines / 115,200 chars, md5 `e55d2e3efb93aae9e06173b9e90c9b24`. **10 ambiguity-pins, 2 mismatch-revisions**, all in-paragraph.

- §2.8 — revise — mismatch (cross-pass seam) — "deciding a corrective action plan ... re-stamps the plan year outright" narrowed to "approving", because only the approval branch bumps unconditionally while rejection recomputes conditionally and re-stamps nothing — `routes/corrective_action_plans.py:102` vs `:107`
- §3.1 — insert — ambiguity — `contact_email` has min length 1, no maximum, and a value lacking `@` is `ERR_VALIDATION` (422) — `routes/administrators.py:25-27`
- §3.5 — insert — ambiguity — on the terminal `FULFILLED`+breach combination the breach check wins: `ERR_ESCALATION_ALREADY_DECLARED` — `routes/vendor_requests.py:107-110`
- §3.5 — revise — mismatch — the per-plan-year `version` increment on the breach cascade is conditional per §2.8, not outright; a year already `VIOLATION`/`AT_RISK` is left untouched — `routes/vendor_requests.py:129-131`, `recompute.py:102`
- §3.6 — insert — ambiguity — opposite precedence for submissions: `ERR_REQUEST_ALREADY_FULFILLED` before `ERR_PRODUCTION_WINDOW_CLOSED` — `routes/vendor_requests.py:170-173`
- §3.6 — insert — ambiguity — the denials<=claims check is not scoped to `DENIAL_RATES`; it runs on every submission type — `routes/vendor_requests.py:159`
- §3.6 — insert — ambiguity — a `REJECTED` submission fires no cascade at all: request, administrator, NQTL items and plan year keep their `updated_at`/`version` — `routes/vendor_requests.py:205-206`
- §3.8 — insert — ambiguity — on a CAP decision the plan's own status is checked before the item's, so a decided plan whose item was remediated reports `ERR_CAP_NOT_DRAFT` — `routes/corrective_action_plans.py:83-86`
- §3.9 — insert — ambiguity — a new regulator request starts with `requested_item_count`/`covered_item_count` at 0; the plan-year move fires only from `OPEN`; a second concurrent request is allowed and does not re-stamp a year already `UNDER_REGULATOR_REVIEW` or in `REMEDIATION` — `routes/regulator_requests.py:37-55`
- §3.9 — revise — ambiguity — certified-analysis selector tie-break: `created_at` desc then later write, `version` playing no part (the gap pass 2 delegated) — `calc.py:276`
- §3.9 — insert — ambiguity — an `INSUFFICIENT` adjudication leaves the last response's counts/score/sufficiency standing rather than clearing them — `routes/regulator_requests.py:121-127`
- §3.9 — revise — ambiguity — the plan-year close on `ACCEPTED` requires both `COMPLIANT` posture **and** the year standing in `UNDER_REGULATOR_REVIEW` — `routes/regulator_requests.py:131-135`

**Pass 3 integrity check:** 28 headings byte-identical to PRD_FINALIZED's heading set; §4 endpoint table and §5 error catalogue byte-identical (98 table rows); tail still `| ERR_LIABILITY_CAP_EXCEEDED | 409 |`. Scripted scan over 560 sentences found no duplicated sentence. One seam contradiction found and fixed (§2.8's outright-bump list vs §3.8's rejection branch); one nested-em-dash construction rewritten for readability. §3.5's "recomputed ... at every escalation" left alone: impl skips the administrator recompute on the notice rung, but counters are provably current there, so it is unobservable. Pass 2's two delegated items resolved.

ORCHESTRATOR VERIFICATION: PRD_COMPLETED.md is 446 lines / 115,200 chars, md5 `e55d2e3efb93aae9e06173b9e90c9b24`, and is NOT byte-identical to PRD_FINALIZED.md (`cmp` differs) — so the scan demonstrably ran. Heading count 28 and table-row count 98 both match PRD_FINALIZED exactly; tail ends at the final error-catalogue row.

## Pipeline complete
All 9 steps finished. Final state: 8/8 sweep rounds at 106/106, PRD.md 442 lines, PRD_FINALIZED.md byte-identical to PRD.md (legitimate — Step 7 made zero implementation fixes), PRD_COMPLETED.md 446 lines with 43 ambiguity/mismatch edits across three module-partitioned passes.

