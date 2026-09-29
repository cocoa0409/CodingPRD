## Step 1: Create task directory — 2026-09-05T00:23:00.000Z

Created `tasks/task_2808_master_patient_index_duplicate_resolution_identity_integrity/` and its `workspace/` subdirectory. Output path was pre-assigned by the orchestrating command (index fixed at 2808); no index allocation scan was performed, per instruction that concurrent pipelines share this host.

## Step 2: Generate scaffold — 2026-09-05T02:24:00.000Z

All three scaffold artifacts are complete and the lint is clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2808_master_patient_index_duplicate_resolution_identity_integrity/`)

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 3193 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1534 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4165 |

**SCAFFOLD.yaml (§1.0–§1.7 only; no design keys)** — `domain_name: master-patient-index-identity-integrity`, `api_prefix: /mpi`, `difficulty_level: expert`; profile: primary `graph_constraint`, secondary `compliance_audit`, layers `[cascading_side_effects, dual_variant_calculation, optimistic_concurrency, derived_field_reconciliation, conditional_feature_flags]`, topology `graph`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.
- 14 entities (3 immutable), 11 state machines + 2 §1.2.1 concurrency rules, 11 calculations, **47 validation rules**, **56 endpoints**, 47 error codes, 5 roles, 24 global constants.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — 9 difficulty rules × **19 instances** (>=2 per rule).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — **99 instances** across the nine mandated sections: entities 12, state_machines 14, calculations 22, validations 27, endpoints 6, errors 3, rbac 7, cross_cutting_complexity_layers 7, consistency_model 1. Of these, **73 carry full `test_recipe`s and 26 are `excluded_because` stubs** citing difficulty instances by name (all references resolve; no name collides across the two design files).

**Lint verdict (verbatim, first run clean):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    56
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     73
  Calls scanned (§1.8+§1.9):  810
```

Notable fixes made while writing the corner design (both in `SCAFFOLD.yaml`, which had internal contradictions the lint cannot see): the `POST /mpi/contamination-remediations/{id}/quarantine` side effect wrongly decremented the subject record's `clinical_element_count` (the state machine and `clinical_element_conservation` put that decrement on `reassign`, so elements were being subtracted twice) — quarantine is now record-neutral and reassign moves them. Also verified every asserted literal against the actual formulas, which caught three wrong numbers in my own draft (a TOLERANT external score of 75.00 -> 77.50, a re-scored pair 92.50 -> 77.50, and a MANUAL investigation `risk_score` 25.00 -> 2.00, since the insurance component requires a non-null `pair_id`). No sibling task directory was read at any point.

**Orchestrator verification:** all three files present; `grep -rn "harder than expert"` over the task dir returns nothing, and `grep -n "Generate task" SCAFFOLD.yaml` is empty — the difficulty directive did not leak into the scaffold's `scenario:` key, so it cannot reach PRD.md.

## Step 3: Copy shared files — 2026-09-05T02:25:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2808_master_patient_index_duplicate_resolution_identity_integrity/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T02:43:00.000Z

PRD.md is complete and verified.

**Output:** `workspace/PRD.md` — **419 lines, 106,087 bytes**, built with 13 chunked `cat >>` appends. Ends at the final `ERR_REMEDIATION_COUNT_INVALID | 422` table row — a real section boundary, no truncation.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 11 subsections: 2.1 Operators, Roles and Identity Scoping · 2.2 API Response Structure · 2.3 Pagination and List Ordering · 2.4 Resource Metadata, Immutable Event Records and the Logical Clock · 2.5 Score Precision, Rounding Order and Interval Arithmetic · 2.6 Optimistic Concurrency on Supersede Operations · 2.7 Nested Path Resolution · 2.8 Validation Precedence: One Error, Chosen by Rank · 2.9 The Two Independent Condition Dimensions of a Patient Record · 2.10 Cascade Discipline and Derived Counter Reconciliation · 2.11 Duty Separation Between Recommendation and Execution
- §3 Business Logic & Workflows — 9 subsections: 3.1 Configuring the Index · 3.2 The Registration Desk · 3.3 Detecting Duplicates (incl. external exchange matching) · 3.4 The Triage Work Queue · 3.5 Approval, Merge and Cluster Compression · 3.6 Downstream Propagation and Merge Completion · 3.7 Reversal and the Conservation Guarantees · 3.8 Overlay Correction and Contamination Remediation · 3.9 Fraud Adjudication and Site Duplicate-Rate Measurement
- §4 Endpoint Definitions
- §5 Error Code Catalogue

**Per-area coverage**
- **Entities** 14/14 rendered; all 126 entity field names appear verbatim in backticks. All 14 type names backticked.
- **State machines** 11/11; all 49 transitions covered (32 as explicit `FROM -> TO` arrows, 17 in prose — incl. the two system create-time branches `NEW -> RECOMMENDED_MERGE` / `NEW -> ESCALATED_FRAUD` and the derived `integrity_state` moves).
- **Calculations** 11/11, all with pinned evaluation order in natural language (round-then-sum scoring, 4-step band chain with pre-evidence multiplier, strict-precedence integrity derivation, 4-component fraud score, single-rounding bps rate, search evaluation, element transfer, both conservation identities, half-open dispatch occupancy, closed metric exclusivity).
- **Validations** 47/47 as a numbered rank list in §2.8, each with condition + `error_id` + HTTP status + full `applies_to` endpoint enumeration. Both `concurrency_rules` in §2.6.
- **Endpoints** 56/56 in the §4 table — machine-diffed against the scaffold: zero missing, zero extra, method+path exact.
- **Roles per endpoint** machine-diffed against scaffold `roles:` lists — exact match on all 56 rows.
- **Errors** 47/47 in §5, statuses machine-extracted from the scaffold; every id also referenced in §2.8.
- **Roles** 5/5 in §2.1 with headers, `cannot` lists and all identity-scoping translations (`SiteRegistrar` entity-backed scope -> `ERR_SITE_SCOPE_VIOLATION`).
- **Constants** 25/25 rendered as literal values or natural-language equivalents; no constant identifiers leak into prose.

**Hard Contract reports**
1. **Field-Name Coverage — PASS.** 133 required names checked against 414 distinct inline-backticked strings: **0 missing**.
2. **Rule Coverage — PASS.** All 47 validations with priority ordering and applies_to scopes; both OCC rules with their `expected_*` fields and 412 errors; all 49 transitions with preconditions and cross-entity side effects; all 11 calculations; sibling-branch symmetry written out explicitly (MERGE/DISTINCT recommendation branches, MATCHED/NO_MATCH external branches, both attribution variants, STRICT/TOLERANT, substantiate/unsubstantiate/refer); structured field content covered.
3. **§3 Path Purity — PASS.** 976 backticked tokens in §3 (279 unique) scanned: 0 leading-slash tokens, 0 bare HTTP methods, 0 method+path combinations, 0 raw `/mpi` occurrences anywhere in §3.

Also verified: §2.2 byte-identical to the canonical response-structure section; §4 table exactly 4 columns, §5 exactly 2; neither design YAML was ever opened, grepped or referenced; no sibling task directory read.

One scaffold inconsistency reconciled: the `PropagationTask` machine declares only `QUEUED -> CANCELLED` on unmerge while the unmerge endpoint's side effects say "`QUEUED` or `FAILED` -> `CANCELLED`". §3.7 uses the inclusive endpoint form.

**Orchestrator truncation check (per the known doc-generator failure mode):** independently ran `wc -l` (419), `tail -12` (ends on a complete `| \`ERR_...\` | 422 |` row), and counted §5 error rows = 47 and §4 endpoint rows = 56 — both match the scaffold exactly, so no trailing section was dropped. No regeneration needed. Leak grep for "harder than expert" / "scaffold" in PRD.md: no hits.

## Step 6: Generate implementation — 2026-09-05T03:12:00.000Z

Implementation for task 2808 is complete, compiling, and smoke-verified. Server has been shut down (killed by PID; port 18808 confirmed free).

## Module inventory
`workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `core.py` | 548 | constants, error->HTTP table, Decimal/ISO helpers, logical clock, in-memory `Store`, envelope, auth/site-scope, field validators, pagination |
| `routes_merge.py` | 361 | merge approve/unmerge + propagation task send/ack/fail |
| `routes_pairs.py` | 323 | pair create/rescore/triage/review/evidence/recommend/resolve-distinct |
| `routes_records.py` | 299 | search attempts, patient records, duplicate metric runs |
| `routes_overlay.py` | 262 | overlay corrections + contamination remediations |
| `scoring.py` | 243 | attribute agreement, raw/match score, conflict flags, band chain, fraud risk score, bps rate |
| `serializers.py` | 233 | one serializer per entity, event-record vs audited shapes |
| `routes_config.py` | 221 | clock endpoint, sites, rule sets, downstream systems |
| `routes_fraud.py` | 201 | fraud investigations + external match requests |
| `domain.py` | 190 | derived counters, `integrity_state` derivation, pair escalation sweeps, fan-out, merge completion |
| `app.py` | 55 | app factory, blueprint registration, error handlers, `PORT`/`0.0.0.0` bind |
| `start.sh` | 8 | conditional pip install, `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask==3.0.3` |

~2,945 lines total. `python3 -m py_compile *.py` -> COMPILE_OK; `__pycache__` removed.

## Coverage
- **56 endpoints** — enumerated from `app.url_map`, exactly 56 non-static routes, one-for-one with PRD §4.
- **47 validation rules** — 47 distinct `ERR_*` identifiers referenced across the route modules, matching the PRD's 47-rank global precedence list.
- In-memory dicts only; store starts empty on every boot, nothing seeded. Logical clock defaults to `2026-08-01T00:00:00Z`.

## Smoke-test result (all pass)
Four scripted suites over a fresh server on port 18808, driven by PID-only lifecycle management (no pattern-kills).

Config/registration: `ERR_WEIGHTS_SUM_INVALID`, `ERR_THRESHOLD_ORDER_INVALID`, duplicate `site_code`/`system_code` -> `ERR_INVALID_REQUEST`, re-activate non-DRAFT -> `ERR_INVALID_REQUEST`, `ERR_SITE_SCOPE_VIOLATION`, `ERR_SEARCH_ATTEMPT_REQUIRED`, `ERR_DUPLICATE_MRN`, `ERR_DUPLICATE_CREATION_BLOCKED`, `ERR_SEARCH_ATTEMPT_EXPIRED`, `ERR_SITE_SUSPENDED`.

Scoring/queue: DOB day-month transposition scored 10.00 of 20 (half credit); AUTO_LINK pair minted straight into `RECOMMENDED_MERGE` with a null recommender; TOLERANT null credit verified exactly (external score 70.00 = 60 exact + 1.25 + 5 + 2.5 + 1.25); band chain P1 with pre-evidence multiplier.

Merge/propagation: `ERR_PAIR_INVALID_STATE` before recommend, `ERR_SEGREGATION_OF_DUTIES`, `ERR_PAIR_RECORD_MISMATCH`, `ERR_INSUFFICIENT_REVIEW_EVIDENCE` (1 of 2 evidence), pair -> `RESOLVED_MERGED`, deadlines +24h SYNCHRONOUS / +72h BATCH, `ERR_PROPAGATION_IN_FLIGHT`, fail->resend->ack bubbling merge to `COMPLETED`, `ERR_PROPAGATION_WINDOW_EXPIRED`, `ERR_MERGE_INVALID_STATE` on double unmerge, unmerge fan-out producing fresh UNMERGE tasks. Dispatch capacity: overlapping window -> `ERR_DISPATCH_CAPACITY_EXCEEDED`, adjacent window accepted — confirming half-open `[start, end)` semantics.

Remediation: auto-opened when a merge moved 30 > 25 elements; `close`/`reassign` before quarantine -> `ERR_REMEDIATION_INVALID_STATE`; over-count -> `ERR_REMEDIATION_COUNT_INVALID` (both against subject and against quarantined); same-cluster target -> `ERR_REASSIGN_TARGET_INVALID`; quarantine moves no record fields; element conservation held exactly (100 -> 100 across reassign); close returned the record to `CLEAR`.

Fraud/exchange: auto SYSTEM investigation at `risk_score` 92.00, substantiate -> `FRAUD_CONFIRMED` -> refer, unsubstantiate restoring `CLEAR` and de-escalating pairs; `ERR_EXCHANGE_CONSENT_MISSING`; role gating matched the PRD exactly (external match is `IdentityAnalyst`-only, remediation reassign/close `PrivacyOfficer`-only).

Cross-cutting: 401 on unknown role and empty user, 404 discrimination per entity (incl. GET external-match-request -> `ERR_RECORD_NOT_FOUND`), pagination meta correct.

No implementation defects were found in this pass — every initially surprising response traced back to a wrong field name or role in the throwaway smoke script, and each was confirmed against the PRD text as the implementation being right.

(Note: Steps 5 and 6 were launched concurrently in a single orchestrator message, so the impl generator started before `test_suite/` existed. Step 6 returned first; Step 5 was still running when this entry was written, which is why the Step 6 entry precedes Step 5 in this log.)

## Step 5: Generate unit tests — 2026-09-05T04:40:00.000Z

Generation is complete. Both output trees are at the task root (nothing was written under `workspace/`).

**Files written** (all under the task root)

`test_helpers/` — 2291 lines total: `__init__.py` 44, `api_client.py` 354, `api_errors.py` 122, `assertions.py` 272, `constants.py` 220, `factories.py` 400, `fixtures.py` 539, `test_users.py` 77, `types.py` 263.

`test_suite/` — 7538 lines total: `conftest.py` 51, `test_01_dual_variant_scoring.py` 312, `test_02_score_formula_precision.py` 369, `test_03_lifecycle_cycles.py` 276, `test_04_transitive_cascades.py` 319, `test_05_validation_precedence.py` 321, `test_06_cross_entity_state.py` 317, `test_07_temporal_overlap.py` 284, `test_08_compensating_invariants.py` 437, `test_09_entity_shapes.py` 416, `test_10_state_machines.py` 549, `test_11_scoring_calculations.py` 277, `test_12_metric_and_derivation.py` 466, `test_13_configuration_and_uniqueness_rules.py` 270, `test_14_cross_entity_refusals.py` 441, `test_15_threshold_and_window_refusals.py` 603, `test_16_endpoint_behaviours.py` 488, `test_17_error_taxonomy.py` 282, `test_18_role_boundaries.py` 556, `test_19_concurrency_counters_and_consistency.py` 504.

**Test counts by queue** — 127 tests total, collected cleanly by pytest (`127 tests collected`).
- Queue A (§1.8 difficulty): 54 tests covering all 19 rule instances, every instance with >=2 tests.
- Queue B (§1.9 corner): 73 tests covering all 73 non-stub instances across `entities` (11), `state_machines` (9), `calculations` (11), `validations` (21), `endpoints` (6), `errors` (3), `rbac` (7), `cross_cutting_complexity_layers` (4), `consistency_model` (1). The 26 `excluded_because:` stubs emitted nothing, as required.

**Skipped instances** — none. Every non-stub instance in both design indices passed the PRD-first two-condition filter and is represented. Two individual assertions inside otherwise-covered instances were dropped rather than weakened where the PRD did not uniquely derive them (the suspended-site `version` and the external-match `version` in queue B), and one evidence-list ordering recipe was made PRD-derivable by advancing the logical clock between writes instead of relaxing the assertion.

**Tag integrity** — a mechanical audit over the AST of all 20 suite files confirms: 127 tests, 127 `Design:` lines, exactly one per test, always the last docstring line; 92 distinct tags = 19 difficulty + 73 corner; zero missing expected tags, zero tags pointing at a non-existent or stub instance. Every docstring citation was re-checked as a verbatim substring of `workspace/PRD.md` (whitespace-normalised) — zero non-verbatim citations, zero uncited tests. `python3 -m py_compile` passes over all 29 generated files, a helper-import probe reports 0 problems, and no generated comment or docstring mentions the scaffold.

**Orchestrator verification:** `test_helpers/` (9 files) and `test_suite/` (20 files) both live at the task root; `find workspace -name "test_*"` returns nothing, so the known "test dirs land under workspace/" failure did not occur. `grep -c "def test_"` across the suite totals 127, matching the reported count.

## Step 7: Run tests and iterate — 2026-09-05T05:03:00.000Z

Clean. No skip/xfail markers, worklog.md untouched (04:12, before the first sweep), storage is in-memory only.

## Summary

**Iterations run:** 3 (three full 8-round parallel sweeps).

**Tests deleted:** none. All 127 tests survive.

**Assertions removed for failing STEP 1b unique-derivability** (partial-coverage split per cardinal rule 1c):
- `test_suite/test_19_concurrency_counters_and_consistency.py` -> `TestVersionDiscipline::test_every_write_bumps_one_version_and_event_rows_carry_none`: dropped `A.assert_version(after_record, 3)`, the claim that a site's own `version` advances when `active_record_count` is refreshed by a record creation. PRD §3.5 enumerates the version-advancing rows exhaustively ("Every row this touches advances its own `version` by 1: the subsumed record, the survivor, and each re-pointed record") and then lists "both member sites' `active_record_count` values are recomputed" *separately, with no version claim* — same pattern in §3.7 and §3.9 ("The record's `version` advances by 1 and the subject's site `flagged_record_count` is recomputed"). A faithful reader can therefore legitimately derive the counters at read time and never mutate the site row. The counter-value assertion (`active_record_count=1`) was kept.
- `test_suite/test_02_score_formula_precision.py` -> `test_a_half_cent_product_rounds_up_rather_than_to_even`: the trailing evidence-list assertion asserted an exact order `[4.00, 4.15]`. Both rows share one logical-clock `created_at`, and PRD §2.3 declares only "ordered by `created_at` ascending" with no tie-break for the evidence collection (the `evidence_type`/`outcome` tie-break in §3.4 governs the *summation*, not the list endpoint). Relaxed to the multiset via `sorted(...)`, preserving the PRD-verbatim "stored exactly as supplied" magnitude check.

**Fixes applied to `test_helpers/`:**
- `assertions.py`, `assert_error_envelope` — read `response_type` from the envelope root instead of from inside `meta`, and expect `meta` to hold exactly `{api_request_id, api_request_timestamp}`. PRD §2.2 puts `response_type` as a top-level sibling of `meta`/`data` and states "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`." This single helper bug accounted for 49 of the 51 failures (`KeyError: 'response_type'`); the implementation was already PRD-faithful.

**Fixes applied to `test_suite/`:**
- `test_17_error_taxonomy.py`, `TestReplayedTransitions::test_each_lifecycle_reports_its_own_invalid_state_code` — `assert len(merge_tasks) == 1` corrected to 2, split into the cancelled `MERGE` task plus the newly raised `QUEUED` `UNMERGE` task. PRD §3.6 says `merge_operation_id` is populated for kind `MERGE` **or** `UNMERGE`, and §3.7 raises "one fresh task with `operation_kind` of `UNMERGE` ... per downstream system whose `status` is `ACTIVE`" while cancelling the original — so filtering by `merge_operation_id` must return both. The already-passing sibling test in `test_08_compensating_invariants.py` asserts exactly this shape, confirming the mis-translation. Added the `OPERATION_MERGE` / `OPERATION_UNMERGE` imports.

**Fixes applied to `implementation/`:** none — no implementation defect was found. All 51 failures traced to the test artifact.

**Final sweep, per-round figures** (quoted from `workspace/implementation/results.$i.json`): rounds 1-8 all `127/127` — 0 failed, 0 errors, 0 skipped in every round. No flakiness appeared at any iteration; failure sets were byte-identical across all 8 concurrent rounds each time, which also rules out load-induced noise.

**Orchestrator verification (per the known "clean sweep with no artifacts" failure mode):** independently re-read all eight `workspace/implementation/results.$i.json` files (all present, ~43.7 KB each, timestamped 04:33) and parsed each — every one reports `passed=127 total=127 failed=0 errors=0 skipped=0`. `grep -rn "pytest.mark.skip\|xfail"` over `test_suite/` and `test_helpers/` returns nothing, confirming no failure was dodged by a marker.

**Step 8 decision:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; Step 7 made 1 `test_helpers/` fix, 1 `test_suite/` fix and 2 unique-derivability assertion removals, so Step 8 runs on that diff. Note that with 0 implementation fixes it is legitimate for Step 8 to conclude that most or all diff items are pure test-artifact bugs rather than PRD silences, in which case `PRD_FINALIZED.md` may be identical or near-identical to `PRD.md`.

## Step 8: Finalize PRD — 2026-09-05T05:08:00.000Z

Done. `PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 419 lines
- `PRD_FINALIZED.md`: 421 lines (+2 lines, +0.48%)

## Changes (2)

- **§2.3 (Pagination and List Ordering)** — *revise* — added a global rule that any tie a collection's declared ordering keys leave unresolved is broken by creation order (persistence sequence), corrected "Two collections declare otherwise" -> "Three", and declared the review-evidence collection's read order as `created_at` asc, then `evidence_type` asc, then `outcome` asc — `implementation/scoring.py:166` (`evidence_of_pair`), consumed by `implementation/routes_pairs.py:265`.
- **§2.10 (Cascade Discipline and Derived Counter Reconciliation)** — *insert* — new paragraph pinning that recomputing any of the five derived counters is not itself a mutation of the publishing row, so it never advances that row's `version` or refreshes `updated_at`; a row mutated in the same request for another reason still bumps by 1 — `implementation/serializers.py:23-24,60,177` + `implementation/domain.py:16-39` (read-time derivation; no `touch`).

## Pre-edit search log

**Edit 1 — subject: list/collection result ordering and tie-breaks.**
(b) Enumerated every ordering site in `implementation/` via `grep -n "\.sort(\|sorted(\|ordered("`: `routes_pairs.py:161` (pairs queue: `priority_band`, `-effective_score`, `created_at`, `subject_record_mrn` over an insertion-ordered list => stable residual = creation order), `routes_merge.py:271` and `domain.py:155` (tasks: `created_at`, `id`), `scoring.py:166` (evidence: `created_at`, `evidence_type`, `outcome`, `_seq`), `routes_records.py:113` (search attempts), `:214` (records), `:296` (metric runs), `routes_merge.py:156` (merges), `routes_overlay.py:94` (overlays), `:182` (remediations), `routes_fraud.py:62` (investigations), `:197` (external matches) — all `(created_at, _seq)`; plus non-endpoint orderings `routes_merge.py:93` (`created_at`, `mrn`, `_seq`) and `domain.py:113` (`system_code`, `_seq`). Read `core.py:249-264` to confirm `_seq` is a monotonic persistence counter.
(c) Wording adjustment: phrased the fallback as breaking only ties "that a collection's declared ordering keys leave unresolved" rather than "ties on `created_at`", so it does not contradict the propagation-task collection's declared `id` stabiliser or the pairs queue's `subject_record_mrn` key; scoped it to list results so the merge's `recompressed_record_mrns` ordering claim in §3.5 is untouched.

**Edit 2 — subject: derived counters vs. `version`/`updated_at` on the publishing row.**
(b) Read `domain.py:16-39` (`active_record_count`, `flagged_record_count` -> `scoring.py:200`, `subsumed_member_count`, `unacked_task_count` — all pure read-time sums, no writes), `serializers.py:16-25,40-61,169-178` (counters projected at read time), and enumerated every `touch(...)` callsite in the service: `routes_config.py:81` (PATCH site), `:146` (retiring rule set), `:211` (PATCH downstream system); `routes_merge.py:99,102,107,112,195,203,206,218,227,237,245,324,337,360`; `routes_overlay.py:115,120,163,203,237,240,243,258`; `routes_pairs.py:195-322`; `routes_fraud.py:80,100,120,181`; `domain.py:65,98,105,150`. No `touch` of a site or downstream-system row exists outside its PATCH endpoint, and `routes_records.py` never touches a site on record creation. Also read `routes_merge.py:68-141` to confirm `propagation_task_count` is assigned inside the creating request with no separate bump.
(c) Wording adjustment: added the closing sentence exempting rows mutated for another reason in the same request (survivor's `clinical_element_count` at `routes_merge.py:101-102`/`205-206`, reassignment targets at `routes_overlay.py:240-243`, administrator site amendment at `routes_config.py:81`), so the new sentence does not read as "these rows never bump"; and included `propagation_task_count` explicitly so the merge row's stable `version` of 1 on a `PENDING_PROPAGATION` create is not mis-described.

**No PRD change** for the other two Step 7 items: the `assert_error_envelope` helper bug (PRD §2.2 already fixes `response_type` at envelope root and `meta` = exactly `{api_request_id, api_request_timestamp}`; `core.py:300-306` is faithful) and the `merge_tasks` count 1->2 (PRD §3.6 + §3.7 already determine that the cancelled `MERGE` task and the fresh `UNMERGE` task both carry `merge_operation_id`; `routes_merge.py:242-247` matches).

## Step 9: Complete PRD — 2026-09-05T05:30:00.000Z

Run as THREE sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (a single monolithic scan of a 421-line PRD against ~2,900 lines of implementation reliably under-scans). Pass 1 owned the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden from copying so they could not destroy earlier edits.

### Pass 1 — cross-cutting + computation modules (`core.py`, `app.py`, `scoring.py`, `domain.py`, `serializers.py`)
`PRD_FINALIZED.md` 421 lines / 107,408 chars -> `PRD_COMPLETED.md` 422 lines / 110,920 chars (+1 line, +3,512 chars). 11 diff hunks, 12 edits, all in-paragraph. **10 ambiguity-pins, 2 mismatch-revisions.**
- §2.1 — revise — ambiguity — an empty `X-User-ID`/`X-User-Role` header value counts as absent for `ERR_UNAUTHENTICATED` — core.py:313-316
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric characters — core.py:270-272
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not host time, so it equals the `created_at` the request mints — core.py:276
- §2.2 — insert — ambiguity — unmatched route / unsupported method are reported in the error envelope as `ERR_INVALID_REQUEST` on the framework's own 404/405 rather than 400; trailing slash accepted — app.py:37-46, app.py:23
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; `offset` has no upper bound and an over-range offset yields an empty page with unwindowed `total_count` and `has_more` false — core.py:505-538
- §2.4 — revise — ambiguity — on a freshly created resource `updated_at` equals `created_at` exactly — core.py:249-255
- §2.4 — insert — ambiguity — pinned the accepted ISO input grammar (`T` or space separator, optional seconds, 1-9 fractional digits, `Z` or no designator read as UTC, explicit offset converted to UTC) and that output truncates rather than rounds sub-millisecond precision — core.py:162-196
- §2.5 — insert — ambiguity — scores are emitted as JSON numbers, so a 2dp value with zero trailing digits may render shorter (`85.0`) without being a precision change — core.py:152-156
- §2.8 rank 4 — insert — **mismatch** — explicit `null` is treated as absent; numeric fields accept decimal strings and reject booleans; integer fields accept zero-fraction numbers; strings carry no implicit minimum length (so `""` satisfies a required string); an omitted body equals `{}`. Critically, list-**filter query parameters are exempt** from the enum check the rank claimed — they are exact string matches, so an unknown filter value returns an empty page, not 400 — core.py:357-499, core.py:541-548
- §3.3 step one — insert — ambiguity — half agreement on `last_name`/`first_name`/`postal_code` requires both values >=3 characters, so shorter values score only 1 or 0 — scoring.py:34-40
- §3.3 step three — insert — ambiguity — the three conflict comparisons use the same trim-and-lowercase normalisation as the agreement step, so case/whitespace-only differences in a biometric hash, SSN4 or member id are not contradictions — scoring.py:84-90, scoring.py:25-31
- §3.9 — revise — **mismatch** — the record's `version` advances only when the re-derivation changes the value; a second investigation on a record already `FRAUD_SUSPECTED` leaves `version`/`updated_at` untouched (PRD previously asserted it advances unconditionally) — domain.py:60-67, domain.py:187

Pass 1 confirmed `routes_records.py:109/292` and `routes_pairs.py:263` call `pagination()` ahead of parent-existence lookup, so §2.8's rank 4 -> rank 5 order already held. It deferred two route-owned questions to pass 2: which score the registration search publishes as `top_score`, and the clock endpoint's echo shape.

### Pass 2 — `routes_config.py`, `routes_records.py`, `routes_pairs.py`
422 lines / 110,920 chars -> 422 lines / 114,080 chars (+3,160 chars, 0 lines). **13 ambiguity-pins, 3 mismatch-revisions.**
- §2.4 — revise — ambiguity — clock endpoint contract: `current_utc` required string, unparseable/non-string -> `ERR_INVALID_REQUEST`, reply is 200 OK whose `data` is an object with exactly the one field `current_utc` in canonical 3-digit form and no `id`/audit fields — routes_config.py:22-33
- §2.7 — revise — **mismatch** — old text claimed a nonexistent path parent outranks a malformed window; impl validates rank 4 first. Now: parent existence precedes every business rule but rank 4 keeps precedence over the parent lookup — routes_records.py:232-240, routes_pairs.py:263-264
- §2.8 consequences — revise — **mismatch** — old text claimed "the parent in the URL is resolved before any body-referenced entity of a different type"; impl resolves strictly by rank number, so rescore reports `ERR_RULE_SET_NOT_FOUND` (rank 6) before the missing path pair (rank 9) — routes_pairs.py:182-185
- §3.1 — revise — ambiguity — duplicate `site_code` is `ERR_INVALID_REQUEST` — routes_config.py:51-52
- §3.1 — revise — **mismatch** — site `status` moves had a stated origin-state precondition impl does not implement (and §5 has no site-state error); now: no precondition, re-supplying the same `status` or supplying no field at all is a no-op that still bumps `version`/`updated_at` — routes_config.py:65-82
- §3.1 — insert — ambiguity — the weights-sum-to-100.00 test is taken over the supplied values, before each weight is stored at 2dp — routes_config.py:106,114,124
- §3.1 — insert — ambiguity — promoting a non-`DRAFT` rule set is `ERR_INVALID_REQUEST`, evaluated after the rule-set 404 — routes_config.py:141-142
- §3.1 — revise — ambiguity — `system_code` has no character-set restriction; duplicate is `ERR_INVALID_REQUEST` — routes_config.py:175,180-181
- §3.1 — revise — ambiguity — a downstream `PATCH` bumps `version`/`updated_at` even when it re-supplies an existing value or supplies nothing — routes_config.py:211
- §3.2 — revise — ambiguity — `searched_ssn_last4`, when supplied, is exactly four digits — routes_records.py:37-38
- §3.2 — revise — ambiguity — **deferred (a)**: all four published search values read the penalised `match_score`, not `raw_score` — routes_records.py:72-83
- §3.2 — insert — ambiguity — with no `ACTIVE` rule set the search is still recorded, as `result_count` 0, `top_score` 0.00, `top_match_record_mrn` null, `blocked_creation` false, `rule_set_version_label` null — routes_records.py:61-67
- §3.2 — insert — ambiguity — the cited `origin_search_attempt_id` need not have been recorded at the record's own `site_id` — routes_records.py:148-175
- §3.3 — revise — ambiguity — rescore's `rule_set_id` is required and `score_variant` optional defaulting to `STRICT`, so omitting it resets a `TOLERANT` pair to `STRICT` — routes_pairs.py:178-179
- §3.4 — revise — ambiguity — `triage_note` is required on triage — routes_pairs.py:206
- §3.4 — revise — ambiguity — return-to-review's optional `triage_note` overwrites when supplied and leaves the existing note untouched when omitted (never blanks it) — routes_pairs.py:300-301
- §3.4 — revise — ambiguity — resolve-distinct's `resolution_note` is validated but persisted on no pair field, so it appears nowhere in the response — routes_pairs.py:313
- §3.9 — revise — ambiguity — a metric run's `rule_set_version_label` is null when no rule set was `ACTIVE` — routes_records.py:282

Deferred-item resolutions: (a) `top_score` = `match_score` (`routes_records.py:72-83`); a virtual search record can only ever raise `SSN4_CONFLICT` since its biometric hash and insurance id are hard-coded null at `routes_records.py:57-58`. (b) clock echo = 200 OK with `data == {"current_utc": "<canonical .SSSZ UTC>"}`, one field only.

### Pass 3 — `routes_merge.py`, `routes_overlay.py`, `routes_fraud.py`
422 lines / 114,080 chars -> 422 lines / 116,464 chars (+2,384 chars, 0 lines). **14 ambiguity-pins, 0 mismatch-revisions** — every behavior the PRD already pinned for these three modules matched the implementation exactly; the merge/unmerge/propagation, overlay/remediation and fraud/external-match state machines, validation ranks, cascade effects and list orderings were all already correct, so the gaps were all silences.
- §2.8 rank 8 — insert — ambiguity — `ERR_RECORD_NOT_FOUND` also answers `GET /mpi/external-match-requests/{id}` for an unknown id, that resource having no not-found code of its own — routes_fraud.py:190
- §3.3 — insert — ambiguity — keys outside the seven scored ones in `external_demographics` are accepted, stored/echoed verbatim, and ignored by the scorer — routes_fraud.py:140,157
- §3.3 — insert — ambiguity — `external_score` is the penalised `match_score`, so a contradicting partner `ssn_last4` costs `conflict_penalty_points`, while the partner feed carries no biometric/insurance value so those conflicts can never arise — routes_fraud.py:158-163
- §3.3 — insert — ambiguity — with no `ACTIVE` rule set the request is still recorded, `external_score` 0.00, no-match branch — routes_fraud.py:161-168
- §3.3 — insert — ambiguity — retrieval of an unknown request id reports `ERR_RECORD_NOT_FOUND` (404) — routes_fraud.py:190
- §3.7 — insert — ambiguity — a reversal leaves `completed_at` and `reversal_deadline_at` exactly as they stood — routes_merge.py:192-195
- §3.7 — insert — ambiguity — each `recompressed_record_mrns` entry re-points exactly one record (earliest-created carrier of that `mrn` still pointing at the survivor and still `MERGED_SUBSUMED`); an entry matching none re-points nothing — routes_merge.py:208-219
- §3.8 — insert — ambiguity — snapshot values get no per-key type/format check and an empty `corrected_field_snapshot` map is accepted — routes_overlay.py:43-44,66
- §3.8 — insert — ambiguity — the record's `version` advances by 1 even when the snapshot carries no keys — routes_overlay.py:117-120
- §3.8 — insert — ambiguity — a still-live remediation is reported with `ERR_OVERLAY_INVALID_STATE`, evaluated immediately after the state precondition — routes_overlay.py:152-159
- §3.8 — insert — ambiguity — `reassigned_to_record_mrn` and `closure_note` open as null — routes_merge.py:127-130 / routes_overlay.py:133-136
- §3.8 — insert — ambiguity — `element_count_quarantined` is an integer of zero or more — routes_overlay.py:193
- §3.8 — insert — ambiguity — `element_count_reassigned` is likewise an integer of zero or more — routes_overlay.py:212
- §3.9 — insert — ambiguity — a supplied `pair_id` need only exist; membership of the subject in that pair is never checked — routes_fraud.py:45-46
- §3.9 — insert — ambiguity — substantiation is the only outcome that refreshes `risk_score`; unsubstantiation and referral leave it untouched — routes_fraud.py:84 vs 98-124

### Totals and final consistency
`PRD_FINALIZED.md` 421 lines / 107,408 chars -> final `PRD_COMPLETED.md` 422 lines / 116,464 chars (**+1 line, +9,056 chars**). Aggregate across the three passes: **37 ambiguity-pins, 5 mismatch-revisions**.

Pass 3's whole-document read: not truncated (ends at the §5 table's last row `| \`ERR_REMEDIATION_COUNT_INVALID\` | 422 |`); 56 endpoint rows in §4 and 47 error rows in §5 both intact; section skeleton §1, §2.1-2.11, §3.1-3.9, §4, §5 all present with no new sections and no reflow of untouched prose; **no cross-pass contradiction found** — pass 3 reviewed passes 1-2's edits and changed nothing outside its own partition except the §2.8 rank-8 sentence, which exists only to keep its §3.3 404 pin from reading as contradicting rank 8's operation list.

**Orchestrator verification:** `PRD_COMPLETED.md` is 422 lines / 116,464 bytes and `cmp` against `PRD_FINALIZED.md` reports a difference, so the scan genuinely ran (a byte-identical Step 9 output would mean it did not). `tail` ends on a complete error-table row and `grep -c '^| \`ERR_'` = 47. `find workspace/implementation test_suite test_helpers -name "*.py" -newermt "2026-09-05 04:34"` returns nothing: no implementation or test file changed after the clean sweep at 04:33, so the verified 127/127 × 8 rounds result still describes the shipped artifacts exactly. Step 9 edits documentation only.

## Pipeline complete — 2026-09-05T05:30:00.000Z

All nine steps finished. Final state: SCAFFOLD trio + `test_helpers/` (9 files, 2,291 lines) + `test_suite/` (20 files, 7,538 lines, 127 tests) + `workspace/implementation/` (13 files, ~2,945 lines, 56 endpoints, 47 validations) + `workspace/PRD.md` (419 lines) -> `PRD_FINALIZED.md` (421) -> `PRD_COMPLETED.md` (422). Test status: 127/127 in all 8 rounds of the final parallel sweep, 0 tests deleted, 0 implementation fixes required.
