# Worklog — task_2859_dam_safety_inspection_emergency_action_planning

## Step 1: Create task directory — 2026-09-05T07:42:34.175Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2859_dam_safety_inspection_emergency_action_planning` and its `workspace/` subdirectory. Index 2859 was pre-assigned by the invocation (no scan of ./tasks/ performed, per the orchestrator instructions — concurrent pipelines on this host would collide with auto-allocation).

## Step 2: Generate Scaffold — 2026-09-05T08:45:00.000Z

All three scaffold artifacts are complete and the linter is clean.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5

Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  935
```

Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2859_dam_safety_inspection_emergency_action_planning/`):
- `SCAFFOLD.yaml` — 3342 lines, 167,003 bytes. Top-level keys only §1.0–§1.7; verified it contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1516 lines, 106,946 bytes. Single key `scaffold_difficulty_design`, 9 rules × 2 = 18 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4392 lines, 281,946 bytes. Single key `scaffold_corner_design`, all 9 sections, 71 instances (63 with `test_recipe`, 8 with `excluded_because`).
- `worklog.md` and `workspace/` untouched (not read, not written).

Domain model (`domain_name: dam-safety-program`, `api_prefix: ""`, `difficulty_level: expert_plus`)
- 15 entities: Owner, Engineer, RiverReach, Dam, ConsequenceAssessment, Inspection, Deficiency, RemediationOrder, EmergencyActionPlan, EapExercise, Permit, HighWaterEvent, ElevationReading, DrawdownOrder, FeeLedgerEntry.
- 10 state-machine dimensions, incl. Dam's two independent dimensions: `safety_status` (UNRATED → the accepted inspection's `condition_rating`, advanced only by `POST /inspections/{id}/accept`, no terminal state) and `regulatory_status` (REGISTERED ↔ UNDER_ENFORCEMENT, → REMOVAL_PERMITTED / STATE_INTERVENTION → terminal BREACHED). Others: ConsequenceAssessment DRAFT→CERTIFIED→SUPERSEDED; Inspection SCHEDULED/RETURNED→SUBMITTED→RETURNED|ACCEPTED; Deficiency OPEN/ESCALATED→ORDERED→REMEDIATION_SUBMITTED→CLOSED_VERIFIED|ORDERED; RemediationOrder ISSUED↔RESPONSE_FILED→SATISFIED|DEFAULTED→REFERRED_FOR_ENFORCEMENT; EAP DRAFT/REVISION_REQUIRED→SUBMITTED→APPROVED→REVISION_REQUIRED|SUPERSEDED|EXPIRED; Permit SUBMITTED→UNDER_ENGINEERING_REVIEW→ISSUED|DENIED|RETURNED_FOR_REVISION→SUBMITTED; HighWaterEvent MONITORING→EMERGENCY|STOOD_DOWN; DrawdownOrder REQUESTED→COORDINATED→ACTIVE→COMPLETED, any non-terminal→CANCELLED.
- 2 OCC rules (`eap-create-stale-dam` on `expected_dam_version`; `drawdown-coordinate-stale-reach` on `expected_reach_version`), 14 calculations, 42 priority-ordered validations, 62 endpoints, 52 error codes, 4 roles (ProgramAdmin, Engineer, DamOwner, EmergencyCoordinator; the latter two/Engineer entity-backed).
- Key formulas: hazard classification from a capped-component consequence score with screening vs. certified variants driving reclassification; inspection interval by class (HIGH 24 / SIGNIFICANT 60? — as declared, LOW and UNCLASSIFIED share 60 months) rebased on `performed_at`; remediation deadline `max(MIN, min(MAX, floor(base_days × hazard_factor)))` capped at 5 days for EMERGENCY_ORDER, with `daily_penalty_rate = round_half_up(DAILY_BASE[severity] × PENALTY_HAZARD_FACTOR[class])`; civil-penalty accrual as a per-day tier ladder (×1.0 / ×1.15 / ×1.3225) capped at 5,000,000 cents *before* the 25% good-faith abatement, exposed as provisional_preview vs. final_assessment; permit fees = tiered base + engineering review fee (capped 750,000) − volume credit decided on the pre-credit total; EAP exercise evaluation with an ordered failure-reason cascade and class-scoped permitted types/participant minimums; reach capacity and dam conservation-storage commitment via `cfs × hours` acre-feet conversion; owner ledger running balance with a 25,000-cent inclusive delinquency threshold.

§1.8 — 9 rules × 2 instances = 18: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

§1.9 — 71 instances across all 9 sections: entities 10, state_machines 9 (1 excluded), calculations 10 (2 excluded), validations 14 (2 excluded), endpoints 5, errors 9, rbac 5, cross_cutting_complexity_layers 7 (3 excluded), consistency_model 2. All 8 `excluded_because.difficulty_instance` references resolve verbatim to §1.8 names; no name collides across the two design files.

Note: the "Generate task harder than expert level!" directive line was deliberately kept out of `scenario:` (it is encoded only as `difficulty_level: expert_plus`), so it cannot leak into PRD.md. No sibling task directory was read at any point.

**Orchestrator verification**: `grep -i "harder than expert"` over all three files returns nothing — the difficulty directive did not leak. All three files parse as valid YAML with the expected top-level keys, and each ends at a real structural boundary.

## Step 3: Copy Shared Files — 2026-09-05T09:13:12.329Z

Copied `./INSTRUCTION.md` → `tasks/task_2859_dam_safety_inspection_emergency_action_planning/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T09:29:00.000Z

PRD complete and verified.

**Artifact:** `workspace/PRD.md` — **489 lines**, 107,890 bytes. `workspace/INSTRUCTION.md` untouched; nothing else added to the directory. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` nor `worklog.md` nor any sibling task dir was read.

**Section structure**
- `# Dam Safety Program API — Product Requirements Document`
- `## 1. Introduction` (L3) — consequence-management framing; the three design problems (server-owned arithmetic, propagating reclassification, safety under contention)
- `## 2. Global Specifications & System-Wide Principles` (L11) — 2.1 Program Actors and RBAC · 2.2 API Response Structure (verbatim skill block) · 2.3 Pagination · 2.4 Resource Identity, Timestamps, Versioning and the Logical Clock · 2.5 Rejection Precedence (all 42 rungs as an ordered ladder) · 2.6 Precision, Rounding and Units · 2.7 Stale-View Protection · 2.8 Hazard Class as the Program's Master Dial · 2.9 Cascade Discipline and Derived-Field Reconciliation · 2.10 Licensure, Certification and Segregation of Duties
- `## 3. Business Logic & Workflows` (L196) — 3.1 Inventory (owners/engineers/reaches/dams + compliance summary) · 3.2 Consequence scoring and reclassification · 3.3 Periodic inspection cycle · 3.4 Deficiencies, orders and the enforcement ladder · 3.5 EAPs, inundation maps, annual exercise · 3.6 Permitting · 3.7 High-water monitoring and coordinated drawdown · 3.8 Owner financial responsibility and the fee ledger · 3.9 State intervention, abandonment and the compliance sweep
- `## 4. Endpoint Definitions` (L363) — intro paragraph on 201-vs-200 and shared pagination, then a 4-column table with **62 rows** (verified by count)
- `## 5. Error Code Catalogue` (L432) — 2-column table with **52 rows** (verified by count)

**Coverage confirmation**
- All **15 entities** described in prose in §3.
- All **62 endpoints** present in §4 with method, path, description and authorized roles, generated programmatically from `endpoints[]` (no transcription risk); all appear behaviourally in §3.
- All **42 validations** rendered as §2.5's explicitly ordered precedence ladder with error ID, HTTP status and applies_to scope, plus the scaffold's outranking notes.
- All **52 errors** in §5, and all 52 IDs also appear verbatim in the prose (mechanically checked, zero missing).
- All **10 state-machine dimensions** covered including the two independent Dam dimensions; every state and transition target appears verbatim (`CERTIFIED`, `DENIED`, `REFERRED_FOR_ENFORCEMENT` appear inside transition pairs such as `UNDER_ENGINEERING_REVIEW → DENIED`).
- All **14 calculations** described with their constants; a numeric sweep of every scaffold constant found only formatting-level differences (45.0→`45.00`, 1.1→1.10, 3.0→`3.00`), no omissions.
- Both concurrency rules, all cascades (four-link certification cascade, four-link enforcement cascade, stand-down cancellation, breach-order closure, conservation invariant) and all counter reconciliations are covered.

**Hard Contract results**
- **Contract 1 (Field-Name Coverage): PASS** — 160 required identifiers (entity fields + write-body fields + query params, `?` suffixes stripped) checked against the PRD's backticked token set: **0 missing**. A separate sweep of all endpoint `output` keys: 0 missing. One repair was needed and made — `eap_id` was added to §3.5 ("the exercise's `eap_id` is taken from the plan it is logged against").
- **Contract 2 (Rule Coverage): PASS** — 52/52 error IDs, all states/transitions, all enum members, all calculation constants present; priority ordering, OCC rules, cross-entity cascades, applies_to scopes and sibling-branch symmetry (ISSUE/DENY/RETURN, APPROVE/REVISE, SATISFIED/REJECTED, three cancel sources) all rendered.
- **Contract 3 (§3 Path Purity): PASS** — 359 distinct backtick tokens between `## 3.` and `## 4.`; **0 violations** (no leading `/`, no bare HTTP method, no method+path). A prose-level scan for unbacktciked collection paths in §3 also found none.
- Style checks: no fuzzy quantifiers, no pseudocode operators inside backticks, no `if/elif/return` lines.

**Verbatim last 3 lines**
```
| `ERR_LEDGER_SIGN_MISMATCH` | 422 |
| `ERR_EVENT_DAM_MISMATCH` | 422 |
| `ERR_CLOCK_NOT_MONOTONIC` | 422 |
```
The document ends at a real section boundary — the final row of §5's table, a complete table row, not mid-sentence. No audit footer was written into PRD.md.

One scaffold inconsistency worth flagging to the pipeline: the `Dam.next_inspection_due_at` field description says it is null while `hazard_class` is `UNCLASSIFIED`, but the dam-registration side effects and `inspection_due_schedule` both set it from a 60-month `UNCLASSIFIED` interval. The PRD adopts the 60-month reading decisively and never states the null reading, so the document is self-consistent.

**Orchestrator verification (truncation guard)**: independently confirmed `wc -l` = 489, the 5 top-level sections are present in order, and `tail -25` ends on a complete `| ERR_CLOCK_NOT_MONOTONIC | 422 |` table row — a real section boundary, not a mid-sentence cut. `grep -i "harder than expert\|expert_plus\|scaffold"` over PRD.md returns nothing: the difficulty directive did not leak. No regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-05T11:17:00.000Z

Both stages are complete. The test suite now covers every non-stub instance in both design indices except one.

## Files created (task root, not `workspace/`)

`test_helpers/` — 2574 lines
`__init__.py` 88, `api_client.py` 369, `api_errors.py` 152, `assertions.py` 171, `constants.py` 289, `factories.py` 520, `fixtures.py` 579, `test_users.py` 103, `types.py` 303

`test_suite/` — 7977 lines
`conftest.py` 18; `test_01_dual_variant_calculations.py` 180, `test_02_combinatorial_formulas.py` 240, `test_03_non_linear_state_machines.py` 336, `test_04_transitive_cascades.py` 316, `test_05_priority_pair_validation_conflicts.py` 203, `test_06_boundary_precision_checks.py` 200, `test_07_cross_entity_state_dependencies.py` 287, `test_08_resource_temporal_overlaps.py` 252, `test_09_compensating_invariants.py` 237, `test_10_entities.py` 693, `test_11_state_machines.py` 803, `test_12_calculations.py` 846, `test_13_validations.py` 883, `test_14_endpoints.py` 515, `test_15_errors.py` 816, `test_16_rbac.py` 394, `test_17_cross_cutting_layers.py` 515, `test_18_consistency_model.py` 243

## Coverage

209 tests, 80 distinct `Design:` tags, every test tagged exactly once.

- **Queue A (§1.8, difficulty): 18/18 instances** — 2 per rule across all 9 rules (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant), 51 tests.
- **Queue B (§1.9, corner): 62/63 non-stub instances**, 158 tests — entities 10/10, state_machines 8/8, calculations 8/8, validations 11/12, endpoints 5/5, errors 9/9, rbac 5/5, cross_cutting_complexity_layers 4/4, consistency_model 2/2. (8 further instances carry `excluded_because` stubs and were correctly never translated.)

## Skipped instances

- `Corner/validations/certification_rejected_when_the_breach_analysis_is_incomplete` — fails condition 2. §3.2 requires `breach_peak_outflow_cfs`, `breach_travel_time_minutes` and `inundation_area_acres` to be strictly positive **at filing**, and §2.5 rung 3 rejects a zero with `ERR_INVALID_REQUEST` (400). No DRAFT row carrying a zero can therefore exist, so the instance's asserted 422 `ERR_BREACH_ANALYSIS_INCOMPLETE` at certification is not uniquely derivable from the PRD. Left as a gap, with no placeholder, xfail or weakened assertion.

## Design-vs-PRD adjustments in this final pass

- `consistency_model` instance 1 asserts a reach field `available_capacity_cfs`; no such field exists in the PRD, so the test asserts `channel_capacity_cfs` 1200 minus `committed_release_cfs` 200 equals 1000 — same discriminating content, PRD-derived fields only.
- `consistency_model` instance 2 asserts `delinquency_status` on the fee-adjustment response and an owner field `outstanding_penalty_cents`. §3.8 enumerates the ledger-entry fields (no status) and `outstanding_penalty_cents` is a compliance-summary key, so the tests assert the recomputed `fee_balance_cents`/`delinquency_status` on the owner read taken immediately after each posting, and use `sequence_no` (the PRD's field name, not `sequence_number`).
- `cross_cutting` instance 4 uses category `INSTRUMENTATION`, which is not a PRD deficiency category; substituted `OPERATIONAL`.

## Verification

`python3 /tmp/task_2859_tests/verify.py` → `MISSING: 0 TOTAL TESTS: 209 DISTINCT TAGS: 80`, with no BADCONST / UNUSED / BADTAG / NOQUOTE findings — every PRD quote survives a literal grep against `workspace/PRD.md`. All six new tag names were grep-confirmed against `SCAFFOLD_CORNER_DESIGN.yaml`. `python3 -m py_compile test_suite/*.py test_helpers/*.py` → COMPILE_OK on all 28 files (`__pycache__` removed afterwards). Both directories sit at the task root; nothing was written under `workspace/`, and `workspace/implementation/`, `worklog.md` and `workspace/INSTRUCTION.md` were never read or touched.

## Step 6: Generate Implementation — 2026-09-05T10:00:00.000Z

Implementation complete. All work is confined to `workspace/implementation/`; nothing outside it was created or modified, and I never read `test_suite/`, `test_helpers/`, the design scaffolds, or any sibling task.

## Module layout (3,721 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | harness contract: guarded `pip install`, `exec python3 app.py`, foreground |
| `requirements.txt` | 1 | `Flask>=2.0` |
| `app.py` | 74 | app factory, `strict_slashes=False`, 7 blueprints, `ApiError`/404/405/400/500 handlers, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")))` |
| `common.py` | 430 | 52-entry error catalogue → HTTP status, `ApiError`, success/list/error envelopes, ISO-8601 3-digit formatting, `Decimal`+`ROUND_HALF_UP` helpers, all body/query validators, pagination |
| `store.py` | 156 | the empty in-memory `Store` (15 dicts) + logical clock, `insert`/`touch`/`insertion_order`/`pick_greatest`, per-parent index helpers |
| `calc.py` | 359 | every constant and the 14 calculations (consequence score, hazard bands, response days, penalty accrual, permit fee schedule, exercise grading, window conflict, freeboard/alert, acre-foot conversion) |
| `derive.py` | 596 | all `source: computed` fields, ledger replay, and the 15 serializers — derive-on-read, never stored |
| `guards.py` | 280 | one helper per precedence rung |
| `services.py` | 112 | shared cascades: ledger posting, system deficiencies, drawdown cancellation, enforcement enter/exit |
| `routes_registry.py` | 313 | owners, ledger, engineers, reaches, dams, compliance-summary, state-intervention |
| `routes_assessment.py` | 138 | assessments + the 4-link certify cascade |
| `routes_inspection.py` | 384 | inspections, deficiencies, remediation orders, penalty preview, verify |
| `routes_eap.py` | 211 | plans, submit/review, exercises |
| `routes_permit.py` | 207 | permits, assign-review, decision, resubmit |
| `routes_emergency.py` | 320 | events, elevation readings, stand-down cascade, 6 drawdown endpoints |
| `routes_program.py` | 130 | compliance sweep (4 stages) + `_clock/set_current_utc` |

Endpoint parity verified programmatically: **62 PRD endpoints, 62 implemented, 0 missing, 0 extra.**

## How the 42-rung precedence is enforced
There is no framework-level pipeline; each handler calls the rung helpers from `guards.py` in strict ascending rung order, so the lowest-numbered failure raises first and short-circuits. Fixed skeleton: `authenticate` (rungs 1–2, before any body parse, so a wrong role beats a broken payload) → body validators (rung 3, syntactic) → path existence (rung 4) → body FK resolution in field-declaration order (rung 5) → `check_identity` (6) → `check_resource_owner`/`check_assigned_engineer` (7–8) → the per-entity state guard (9–16) → `check_dam_operable` (17) → version guards (18–19) → licence/certification (20–21) → business rungs 22–37 inline in numeric order → uniqueness (38–39) → ledger sign (40) → event/dam match (41) → clock monotonicity (42). Two spec subtleties are implemented as written: rung 8 is skipped entirely when `review_engineer_id` is null (rung 14 reports instead), and rung 19 outranks both scarcity checks at coordination.

## State machines and cascades
Statuses are plain string fields; each transition endpoint asserts the legal `from` set via its `check_*_state` guard and then writes the `to` status plus its stamp. The Dam carries two independent dimensions (`safety_status`, derived from the latest accepted inspection; `regulatory_status`, a stored system field) that never touch each other. Cascades are single-request and explicit: certify supersedes the prior CERTIFIED assessment, recomputes the certified score/class, knocks APPROVED plans on a stale inundation map to REVISION_REQUIRED (clearing `expires_at`), and opens an EAP_MISSING deficiency only if a plan actually moved, with exactly one `touch(dam)`; the sweep runs the four-link enforcement chain where each link is conditional on the previous (penalty → CIVIL_PENALTY ledger entry → CURRENT→DELINQUENT flip → REGISTERED→UNDER_ENFORCEMENT), then referrals, then plan expiry, then overdue recount. Conserved quantities (`committed_release_cfs`, `committed_drawdown_acre_ft`) are never incremented — they are re-summed from COORDINATED/ACTIVE orders, so coordinate/cancel round-trips are exact; only the `version` counters are bumped.

## Verification
- `python3 -m py_compile` passes on all 14 `.py` files (re-run after the final edit); `__pycache__` removed.
- **Bug found and fixed during the smoke test:** `app.py`'s error handlers wrapped `common.error_body()` in a second `jsonify()`, but `error_body` already returns `(Response, status)`. Every 4xx was therefore turning into an HTML 500. The handlers now unpack the tuple. After the fix a full replay produced **zero tracebacks** and correct codes: 401 no-headers, 403 wrong role, 403 unknown identity, 404 missing resource / unknown path, 400 malformed body and out-of-range `limit`, 422 clock-backwards, 409 REMOVAL_PERMITTED permit block, plus `ERR_STALE_REACH_VERSION`, `ERR_REACH_CAPACITY_EXCEEDED`, `ERR_INSUFFICIENT_STORAGE`, `ERR_EVENT_NOT_IN_EMERGENCY` and `ERR_OWNER_DELINQUENT` on the right paths.
- Smoke boots: high ports picked by the subagent itself (41783, 42917, 43619). Two full end-to-end scenarios covering all 7 blueprints. Each server stopped with `kill <exact pid>`; **no `pkill`, `killall` or pattern-based kill was ever issued**.
- The last boot was through `bash start.sh` with `PORT=43619`, and all 12 collection endpoints returned `total_count=0` on that fresh process: **nothing is seeded, registered or hardcoded at startup**, storage is in-memory dicts only (no SQLite, no JSON file, no /tmp cache), so each `start.sh` re-invocation under `--isolation per-test-server` starts from a genuinely empty store with the clock at `2026-08-01T00:00:00Z`.

**Orchestrator verification for Steps 5+6**: `test_helpers/` (2574 lines) and `test_suite/` (7977 lines) are both at the task ROOT — confirmed `workspace/test_helpers` and `workspace/test_suite` do not exist. `workspace/implementation/` holds 3710 lines of Python plus `start.sh` and `requirements.txt`. `python3 -m py_compile` over all 42 generated .py files → COMPILE_OK, so nothing was truncated mid-statement by the 64k output cap. Steps 5 and 6 were launched in a single assistant message, so the implementation subagent started before `test_suite/` existed on disk — physical isolation held. Only one `worklog.md` exists (task root); no cwd-drift strays. The orchestrator also pre-wrote `workspace/sweep.sh` for Step 7 to use as a script file rather than an inline quoted one-liner.

## Step 7: Run Tests and Iterate — 2026-09-05T12:20:00.000Z

Clean sweep achieved — all 8 rounds 209/209.

## Summary

**Iterations run:** 2 (iteration 1: 199/209 in all 8 rounds, fully deterministic, no flakiness; iteration 2: 209/209 in all 8 rounds).

**Tests deleted:** none. All 10 failures were test-artifact bugs; 5 assertions were removed/replaced under STEP 1c partial-coverage splits (the enclosing tests stayed).

**Assertions removed for PRD silence (STEP 1a → COMPUTED-FIELD SILENCE):** the PRD never names a `decided_at` field on a permit (§3.6 enumerates `revision_count`, `review_engineer_id`, `decision_findings`, `conditions`, `issued_at`) nor a `submitted_at` field on an emergency action plan (§3.5 enumerates `review_findings`, `approved_at`, `expires_at`, `last_accepted_exercise_at`, `accepted_exercise_count`, `exercise_current`). Five assertions on those two invented fields were dropped; the surrounding error_id/state assertions were kept intact.

**Fixes applied to `test_suite/`:**
- `test_03_non_linear_state_machines.py`, fixture `returned_permit` — the 430,000-cent intake fee its own application posts makes the owner `DELINQUENT` (rung 35 blocks *any* decision, "not just an issuance"), so the RETURN decision was correctly rejected; the fixture now settles the fee first. Downstream expectations in `test_resubmission_reprices_the_schedule_and_posts_only_the_difference` and `test_the_repriced_permit_can_be_reassigned_and_issued` were recomputed on the PRD's five-movement schedule (surcharge 0 not 24,900; total 166,000 not 190,900; `FEE_VOID` delta −264,000; ledger 3 rows; final balance −264,000, `CURRENT` per §3.8's negative-balance rule).
- `test_05_priority_pair_validation_conflicts.py` — two `decided_at` assertions dropped (one replaced by the PRD-declared `issued_at is None`).
- `test_07_cross_entity_state_dependencies.py`, `test_a_construction_permit_cannot_be_decided_on_an_unsatisfactory_dam` — `decided_at` assertion replaced by `decision_findings is None`, which §3.6 does declare null at intake.
- `test_11_state_machines.py`, `test_standing_down_cancels_the_requested_order_without_touching_the_reach` — asserted `planned_release_acre_ft is None` on a `REQUESTED` order, contradicting §3.7 ("What is computed at request time is `planned_release_acre_ft`"; the null list covers `coordinated_at`…`actual_release_acre_ft`, not this field). Now asserts 198.347 (6 h × 400 cfs × 0.0826446).
- `test_13_validations.py` — two `submitted_at` assertions dropped.
- `test_15_errors.py`, fixture `served_order` — captured the deficiency *before* issuing the order and then asserted `ORDERED` on that stale snapshot; the fixture now re-reads the stored row after issuance.

**Fixes applied to `test_helpers/`:** `types.py` only — dropped the non-PRD `submitted_at` (EmergencyActionPlan) and `decided_at` (Permit) TypedDict members. The file is documentation-only (imported nowhere), so this is cosmetic PRD-fidelity, not a behavioural fix.

**Fixes applied to `implementation/`:** none. Every failure traced to the test artifact; no PRD-required check was weakened and no endpoint, field or side effect was added.

**Final round tallies:** rounds 1–8 all `209/209` passed (0 failed, 0 errors), ~375 s per round.

Notable for the orchestrator: a byte-identical `PRD_FINALIZED.md` is legitimate here since no implementation fix was made. `worklog.md` was not touched (mtime still 11:19:08, pre-session).

**Orchestrator verification**: independently re-read all 8 `workspace/implementation/results.$i.json` (all present, ~62 KB each, written 11:49) and confirmed each reports `passed=209, failed=0, errors=0, total=209`. The clean sweep is real, not merely claimed.

**Step 8 skip decision**: NOT skipped. The skip condition requires all four of {deletions, test_suite fixes, test_helpers fixes, implementation fixes} to be zero; here there were 6 `test_suite/` fixes and 1 `test_helpers/` fix. Step 8 runs with the above entry inlined as `<step_7_diff>`. Since `implementation/` received zero fixes, a byte-identical or near-identical `PRD_FINALIZED.md` is a legitimate outcome — the Step 7 items are test-artifact bugs and PRD silences about fields the implementation never exposed, so most of them imply no PRD edit at all.

## Step 8: Finalize PRD — 2026-09-05T12:30:00.000Z

`PRD_FINALIZED.md` written. Exactly **one** edit was warranted; everything else in `<step_7_diff>` was a test-artifact bug over prose the PRD already determines.

## Counts
- `PRD.md`: 489 lines / 107,890 bytes
- `PRD_FINALIZED.md`: 489 lines / 108,310 bytes (line delta 0.0%; byte delta +420, +0.39%)
- Ends at the real §5 boundary (`| ERR_CLOCK_NOT_MONOTONIC | 422 |`).

## Change
- **§3.6 (last paragraph, resubmission) — revise** — the sentence "The full five-movement fee schedule is then re-evaluated on the revised cost and the dam's current hazard class" enumerated only two inputs; movement three's trigger (`delinquency_status` "at the moment of application") was undefined for a resubmission, and the fate of the stored component fields was unstated. Now pins: re-evaluated on the revised cost, the dam's current hazard class **and the owner's `delinquency_status` as it stands at the moment of resubmission** (15% surcharge exactly when delinquent right then, 0 otherwise, regardless of what was charged at intake); movement four re-decides the volume credit on the new pre-credit total; all four component fields plus the total are overwritten. — `implementation/routes_permit.py:193-195` (`calc.permit_fees(..., owner_is_delinquent(owner["id"]))` then `permit.update(fees)`), `implementation/calc.py:259-278`.

## Pre-edit search log (the one edit)
- **(a) Subject:** permit fee schedule recomputation inputs — specifically which delinquency snapshot movement three reads, and which stored fields get refreshed.
- **(b) Impl paths enumerated (grepped `permit_fees|delinquency_surcharge|owner_is_delinquent|owner_delinquency_status` across all modules, then read each hit):** `calc.py:259-278` (sole fee function; surcharge/credit/total arithmetic); `routes_permit.py:42-56` (application — reads delinquency *before* posting the intake fee); `routes_permit.py:193-206` (resubmission — same read, before posting the delta); `routes_permit.py:21-23` `_price()` (dead helper, zero callers — confirmed by repo-wide grep, so it cannot contradict the wording); `guards.py:269-272` (rung 35 gate — a *decision* check, not a pricing path); `services.py:108` (§3.4 `UNDER_ENFORCEMENT → REGISTERED` cycle-back — unrelated to pricing); `derive.py:42-47,67,465,582` and `routes_registry.py:65`, `routes_program.py:52-58` (pure read/serialize/filter of delinquency). No cascade anywhere re-prices an existing permit.
- **(c) Wording adjustment:** scoped the new clause strictly to *resubmission* ("as it stands at the moment of resubmission") rather than a general "at pricing time" claim, so it cannot be read back onto the application path (where the read precedes the intake posting) or onto the rung-35/§3.4 delinquency consumers. Kept "whatever was charged at intake" descriptive rather than prescribing any carry-over rule, and said "all four component fields plus the total are overwritten" (matching `permit.update(fees)`) instead of naming individual fields.

## Step 7 items that implied NO edit
1. **`returned_permit` fixture / rung 35 blocking a RETURN decision** — already pinned: §3.6 states "all four gates guard the decision itself, not just an issuance: a delinquent owner's permit cannot even be denied on the merits until the balance is settled", and §3.8 says delinquency "blocks any permit decision". `guards.check_owner_not_delinquent` is called unconditionally in `routes_permit.py:153`, before the decision branch. Prose verbatim.
2. **FEE_VOID delta / 3 ledger rows / total 166,000** — §3.6's "only the **difference** … a negative difference as a `FEE_VOID` entry" already determines a single delta row; `routes_permit.py:198-206` matches. The numeric recomputation in the test followed from the surcharge input, covered by the one edit above.
3. **Final balance −264,000 reported `CURRENT`** — §3.8 already states verbatim "A balance may go negative, representing a credit with the state, and a negative balance is `CURRENT`" (`derive.py:42-47`). No edit.
4. **`planned_release_acre_ft` on a `REQUESTED`/`CANCELLED` order (198.347)** — §3.7 already states "What is computed at request time is `planned_release_acre_ft`" and its null-at-request list deliberately excludes it. Impl computes it at request (`routes_emergency.py:193`) and never clears it — the only other references are the storage check, the conservation sum and the serializer. No edit.
5. **`served_order` fixture stale-snapshot bug (deficiency `ORDERED`)** — §3.4 already states issuing an order moves the deficiency `OPEN → ORDERED`. Pure fixture bug. No edit.
6. **Dropped `decided_at` (Permit) and `submitted_at` (EmergencyActionPlan) assertions, and the matching `test_helpers/types.py` trim** — the PRD never names either field, and the implementation never exposes them (`derive.serialize_permit:453-476`, `derive.serialize_plan:412-431` both lack them). Adding a negative statement would invent spec; the existing field enumerations in §3.5/§3.6 already match the serializers. No edit.
7. **`implementation/` fixes** — none existed in Step 7, so no impl-driven mismatch to pin beyond the site above.

**Orchestrator verification**: `wc -l -c` confirms 489/107,890 → 489/108,310, and `diff PRD.md PRD_FINALIZED.md` shows exactly one changed hunk at line 307 (the §3.6 resubmission paragraph) — a genuinely minimal patch, not a rewrite. `PRD_FINALIZED.md` still ends on the complete `| ERR_CLOCK_NOT_MONOTONIC | 422 |` row, so no truncation.

## Step 9: Complete PRD — 2026-09-05T13:35:00.000Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place and were explicitly forbidden to copy or overwrite. Partitioning was chosen because a single agent cannot hold the whole 3,710-line implementation plus the 108 KB PRD without the scan degenerating into a no-op that leaves the output byte-identical to its input.

### Pass 1 — global layer (`app.py`, `common.py`, `store.py`, `guards.py`, `calc.py`)

`cp workspace/PRD_FINALIZED.md → workspace/PRD_COMPLETED.md` (source was PRD_FINALIZED.md; PRD.md not used). 489/108,310 → 490/113,732 (+5,422 chars, +1 line, 14 localized hunks). **12 ambiguity-pins, 2 mismatch-revisions.**

- §2.1 — revise — ambiguity — a whitespace-only identity header counts as empty for `ERR_UNAUTHENTICATED` — guards.py:27
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A–Z0–9` — common.py:202
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the host wall clock, not the logical clock — common.py:203
- §2.2 — revise + insert — ambiguity — pre-dispatch failures pinned: unmatched path → `ERR_INVALID_REQUEST` @404, bad method @405, malformed @400, unexpected fault @500 (the only 5xx emitted); trailing-slash insignificance — app.py:26,42–64
- §2.2 — revise — ambiguity — `message` is free text and carries no contract — common.py:86
- §2.3 — revise — ambiguity — `created_at` ties fall through to insertion order (earlier row first) — store.py:70
- §2.3 — revise — ambiguity — id-valued filters matched literally, never existence-checked: unknown id yields an empty page, not 404 — common.py:418
- §2.4 — revise — ambiguity — `created_at` stamped from the **logical** clock; universal 3-fractional-digit-`Z` rendering; naive input read as UTC, offsets converted, sub-second truncated at microseconds — store.py:52, common.py:94–135
- §2.5 rung 3 — revise — ambiguity — present-but-`null` == omitted; scalar coercion rules; absent/unparseable body read as `{}`, non-object rejected; `limit` validated before `offset` — common.py:241–246,266–353,232–238,392–406
- §2.5 rung 7 — revise — ambiguity — ownership check evaluated only when `X-User-Role` is `DamOwner`; a `ProgramAdmin` is never subject to it — guards.py:144–147
- §2.5 rung 17 — revise — **mismatch** — the `REMOVAL_PERMITTED` half blocks a new consequence assessment **and a permit application of any type** (was "no new construction permits"); does not block inspection scheduling, plan drafting, event declaration, drawdown request, or certifying an assessment already on file — guards.py:205–212
- §2.6 — revise — ambiguity — all three precision regimes travel as JSON numbers, trailing zeros not preserved (`45.00` → `45.0`) — common.py:184–190
- §2.6 — revise — ambiguity — calendar-month arithmetic clamps the day down to the target month's last day, never carrying forward — common.py:138–144
- §2.9 — revise — ambiguity — `latest_eap_status` tie broken by insertion order with the later insertion winning; blanket rule that every "latest" tie-break falls through to insertion order, never `id` — store.py:73–100
- §3.6 — revise — **mismatch** — coherence with rung 17: after `REMOVAL` issuance no further permit application *of any type* may be filed (was "construction permit") — guards.py:205–212

Left alone: **`calc.py` is fully pinned, every literal** — consequence-score weights/caps and cap-before-sum, the three travel-time bands with both screening/certified variants, hazard bands and their five-step order with inclusive thresholds, inspection intervals 12/24/60/60, base response days and compression with floor-then-clamp(5,365) and the `EMERGENCY_ORDER` cap of 5, daily penalty bases and hazard factors, penalty tiers 1.0/1.15/1.3225 with once-per-day rounding, cap 5,000,000 *then* 25% abatement, the four base-fee tiers and review-fee percentages with round-then-cap at 750,000, the 15% surcharge and one-shot 10% credit at 500,000, the exercise grading cascade, the 365-day currency window, the 120-minute travel buffer, freeboard bands, the 0.0826446 acre-ft conversion, the inclusive 25,000-cent delinquency threshold and 25,000,000 HIGH bond floor, the 30-day referral period, all 30 enum tuples. Also already pinned: the 52-entry error catalogue (verified programmatically identical in membership *and* status to `common.ERROR_STATUS`, zero drift), envelope shapes, `has_more`/`total_count`, limit/offset bounds, UUID ids, `version` from 1 by +1, journal-row shape, initial clock `2026-08-01T00:00:00Z` with equality a no-op, ROUND_HALF_UP everywhere, and every guard's error_id/status/rung position.

### Pass 2 — derivation + registry/assessment/inspection (`derive.py`, `services.py`, `routes_registry.py`, `routes_assessment.py`, `routes_inspection.py`)

No `cp`, no `Write` — 21 surgical `Edit`s in place. 490/113,732 → 490/117,504 (+3,772 chars, zero new lines). Pass 1's edits verified intact by 13-phrase spot-check. **20 ambiguity-pins, 1 mismatch-revision.**

- §3.1 — insert — ambiguity — `certified_hazard_classes` echoed exactly as supplied (order preserved, duplicates not collapsed) — derive.py:111
- §3.1 — revise — ambiguity — `channel_capacity_cfs` must be a whole number ≥ 1 — routes_registry.py:161
- §3.1 — insert — ambiguity — `normal_pool_elevation_ft < crest_elevation_ft` is a rung-3 `ERR_INVALID_REQUEST`, judged before `owner_id`/`river_reach_id` resolve — routes_registry.py:206–210
- §3.1 — insert — ambiguity — dam registration advances the **owner's** `updated_at` and `version` by 1 — routes_registry.py:228
- §3.1 — revise — ambiguity — owners filterable by `owner_type`; river reaches take no filter; **no list or single read is implicitly narrowed to the acting user** — routes_registry.py:59–65,178–184,48–52,132–137
- §4 (`GET /owners`) — revise — ambiguity — added the `owner_type` filter — routes_registry.py:59
- §4 (`GET /owners/{id}/fee-ledger-entries`) — revise — **mismatch** — row claimed "in sequence_no order", contradicting pass 1's §2.3 rule and the impl, which paginates on insertion order; reworded to "each carrying its replayed running balance, in the §2.3 order" — routes_registry.py:100–103
- §3.2 — revise — ambiguity — `breach_travel_time_minutes` is a whole number of minutes ≥ 1 — routes_assessment.py:30
- §3.2 — insert — ambiguity — the certify response body is the **assessment**, not the reclassified dam — routes_assessment.py:138
- §3.2 (link 4) — insert — ambiguity — `eap_required` read after link 2 on the newly certified class, so a downgrade to `LOW` moves the plan under link 3 but opens no deficiency — services.py:65–71, derive.py:222
- §3.3 — insert — ambiguity — an inspection-born deficiency starts with `remediation_due_at`/`closed_at` null and `order_count` 0 — routes_inspection.py:155–156, derive.py:344
- §3.3 — insert — ambiguity — `EAP_MISSING`/`EAP_EXERCISE` in a submitted `deficiencies` element is `ERR_INVALID_REQUEST` — routes_inspection.py:114
- §3.3 — insert — ambiguity — returning an inspection writes nothing on the dam — routes_inspection.py:185–195
- §3.4 — insert — ambiguity — `completed_at` temporally unconstrained; `corrective_action_summary` and `completed_at` both overwritten by a re-response — routes_inspection.py:337,345–346
- §3.8 — insert — ambiguity — a fee adjustment writes only the journal row: the owner's `updated_at`/`version` stay put even though balance and delinquency moved — routes_registry.py:83–85, services.py:19–27
- §3.9 — insert — ambiguity — `justification` must be non-empty but is not persisted; the call returns the updated dam — routes_registry.py:283,313
- §3.9 — insert — ambiguity — `ABANDONMENT_TAKEOVER`/`EMERGENCY_REPAIR` legal only from `REGISTERED`/`UNDER_ENFORCEMENT`; anything else (incl. an already-`STATE_INTERVENTION` dam) is `ERR_DAM_NOT_OPERABLE` 409 — a second takeover is not idempotent — routes_registry.py:298–300
- §3.9 — insert — ambiguity — only `COORDINATED`/`ACTIVE` cancellation moves a reach, version-bumped exactly once per request however many orders were cancelled — routes_registry.py:302–311, services.py:81
- §3.9 — insert — ambiguity — `BREACH_ORDER` legal from those three postures and nowhere else — routes_registry.py:286–289
- §3.9 — insert — ambiguity — a breach order cancels no drawdown orders and writes no reach, unlike the two intervention types — routes_registry.py:286–296
- §3.9 (sweep link 4) — insert — ambiguity — the posture move is written only for a dam on `REGISTERED` — services.py:93–98

Left alone: consequence scoring and every threshold; the remediation-window/penalty-rate/tiered-accrual arithmetic and the preview's 5-key shape; the 120-minute buffer; `performed_at` window/future boundaries and their rung order; resubmission semantics; acceptance stamps and the `PERIODIC`-only schedule rebuild with its tie-break; segregation of duties; the compliance summary's exact 16-key set and order; every serializer field set; the four certification links with a single dam version bump; `EAP_MISSING` once-per-category suppression; `response_filed_at` write-once; the `+2` dam version when verification also releases enforcement; ledger sign rules and `sequence_no` replay.

### Pass 3 — remaining routes (`routes_eap.py`, `routes_permit.py`, `routes_emergency.py`, `routes_program.py`)

No `cp`, no `Write` — 31 surgical `Edit`s in place. 490/117,504 → 490/127,591 (+10,087 chars, zero new lines). Passes 1 and 2 verified intact by spot-check of 9 phrases. **21 ambiguity-pins, 10 mismatch-revisions.**

Inherited §2.4-vs-§2.5 item **resolved**: §2.4 said the leftmost `{id}` resolves "before any deeper segment, body field or business rule", but §2.5's authoritative ladder puts rung 3 (body syntax) before rung 4 (path existence), which is what every handler does (`body_dict()` + `v_*` validators precede the first `guards.get_*`). §2.4 was narrowed — path id resolves before any deeper segment, any body **reference** or any business rule — and now states explicitly that this resolution "is rung 4 of the ladder in §2.5 and therefore sits *after* the whole syntactic layer rather than before it: a request whose body is malformed and whose path id is also unknown reports `ERR_INVALID_REQUEST`". §2.5 was left as the authority. No multi-id path exists, so the "left to right" clause was vacuous either way.

- §2.4 — revise — mismatch — path resolution is rung 4, after the syntactic layer (the inherited item) — routes_permit.py:129–133
- §2.4 — insert — ambiguity — the clock endpoint takes no headers, but a present-and-non-blank pair must read `ProgramAdmin` or it is 403 (a lone `X-User-ID` is 403, not 401); returns 200 with empty `data` — routes_program.py:118–130
- §2.5 rung 3 — insert — ambiguity — `reading_at` ≤ clock added to the syntactic enumeration, contrasted against rungs 27/34 — routes_emergency.py:86
- §2.7 — insert — ambiguity — both version fields are bare unbounded integers, so a zero/negative expectation is 412 not 400; the check is pure equality — guards.py:219–234
- §3.5 submit — revise — mismatch — supplied refs feed the checks but persist only once both pass, so a rejected submission writes nothing; submission does not re-check operability — routes_eap.py:93–121
- §3.5 review — insert — ambiguity — `APPROVE` also stores `findings` in `review_findings` — routes_eap.py:136
- §3.5 exercise — insert — ambiguity — the deficiency carries null `inspection_id`/`remediation_due_at`/`closed_at` and is **never** suppressed by an existing unclosed `EAP_EXERCISE` — routes_eap.py:184–194
- §3.5 currency — insert — ambiguity — logging an exercise never writes the plan row; only a deficient outcome writes the dam — routes_eap.py:183–195
- §3.6 apply — insert — ambiguity — `proposed_start_date` never compared to the clock — routes_permit.py:34
- §3.6 apply — insert — ambiguity — the intake ledger entry's `source_ref` names the permit; owner row untouched — routes_permit.py:63–67
- §3.6 assign — insert — ambiguity — "latest accepted inspection" = §2.9's `safety_status` row, any `inspection_type`; no accepted inspection means no collision; writes only the permit — routes_permit.py:116–122
- §3.6 decision — insert — ambiguity — `conditions` stored on `ISSUE` only, discarded on `DENY`/`RETURN` — routes_permit.py:160
- §3.6 ISSUE — revise — ambiguity — the `REMOVAL_PERMITTED` move is written only from `REGISTERED` — routes_permit.py:162–164
- §3.6 resubmit — insert — ambiguity — delta entries name the permit in `source_ref`; no operability/classification re-check — routes_permit.py:183–206
- §3.7 declare — insert — ambiguity — `declared_at` never clock-checked; an `UNCLASSIFIED` dam may have an event declared — routes_emergency.py:35–39
- §3.7 reading — insert — mismatch — a future `reading_at` is `ERR_INVALID_REQUEST` 400 raised *before* `get_event`, so it beats `ERR_EVENT_NOT_FOUND`; `pool_elevation_ft` unbounded — routes_emergency.py:84–88
- §3.7 reading — insert — ambiguity — derivations of `reading_count`/`current_alert_level`/`peak_pool_elevation_ft`; every reading refreshes the event's `updated_at` but only an escalating one bumps `version` — routes_emergency.py:110–115, derive.py:487–514
- §3.7 stand-down — insert — ambiguity — reach and dam `version` advance **once per released order**, the opposite convention to §3.9's intervention (which collapses per reach) — routes_emergency.py:145–155
- §3.7 request — revise — mismatch — gates re-ordered to ladder order (operable → EAP → unclassified), body refs resolved dam-then-event, `latest_eap_status` semantics pinned (newest plan by `created_at`, so a fresh draft closes the gate again) — routes_emergency.py:174–185, derive.py:212–214
- §3.7 coordinate — revise — mismatch — coordination re-checks nothing about the event; the `REQUESTED` status alone is the precondition and it never emits `ERR_EVENT_INVALID_STATE` — routes_emergency.py:243–247
- §3.7 activate — revise — ambiguity — no body is read; neither reach nor dam is written — routes_emergency.py:270–282
- §3.7 complete — insert — ambiguity — `actual_release_acre_ft` echoed exactly as supplied, not quantised to 3 dp — routes_emergency.py:289–296, derive.py:549
- §3.8 — revise — mismatch — **pass-2 refinement**: narrowed "appending an entry writes only that journal row" to hand-posted and permit-fee entries, naming the sweep's civil penalty as the one exception — routes_program.py:57
- §3.9 sweep intro — insert — ambiguity — no body is read, so a supplied body is ignored — routes_program.py:17–19
- §3.9 Link 1 — insert — mismatch — the deficiency escalates **only** from `ORDERED`; a `REMEDIATION_SUBMITTED` deficiency is passed over and adds nothing to `escalated_deficiency_count` — routes_program.py:44–48
- §3.9 Link 2 — revise — mismatch — Link 2 requires a penalty strictly > 0; an order less than a full day overdue defaults with 0 and links 2–4 stay silent — routes_program.py:31–51
- §3.9 Link 2 — insert — mismatch — this posting also writes the owner row, bumping `updated_at` and `version` — routes_program.py:57
- §3.9 stage 2 — insert — ambiguity — an order defaulted by this same run can never be referred by it; `assessed_penalty_cents` left standing — routes_program.py:67–73
- §3.9 stage 3 — insert — ambiguity — the dam's `version` bumps even when suppression opened nothing; the `eap_required`-false branch refreshes `updated_at` without bumping `version` — routes_program.py:88–92
- §3.9 stage 4 — revise — mismatch — nothing is recomputed or written; the stage only counts — routes_program.py:96–98
- §3.9 report — revise — ambiguity — `overdue_inspection_count` is inventory-wide and unfiltered; `swept_at` is the unmoving run clock — routes_program.py:19,100–111

Left alone: the permit five-movement fee schedule and all rounding; exercise grading order, participant minima and permitted formats; the currency window's exclusive-lower/inclusive-upper bounds and `SUPERSEDED`/`EXPIRED` exclusion; freeboard bands and the `rising` predecessor tie-break; the closed-interval capacity check and the storage conservation law; every §4 list filter set and role list (verified against the route decorators); rung-17's carve-outs; rung-8's skip on an unassigned permit; `defaulted_order_ids` ordering; the sweep's exact response key set; the `EAP_VALIDITY_MONTHS`/`MIN_NOTIFICATION_CONTACTS` tables.

### Step 9 totals

**66 edits across three passes: 53 ambiguity-pins, 13 mismatch-revisions.** `PRD.md` 489 lines / 107,890 bytes → `PRD_COMPLETED.md` 490 lines / 127,591 bytes (+19,701 bytes, +18.3%; +1 line).

**Orchestrator verification**: `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (55 diff hunks), so the scan genuinely ran rather than degenerating into a no-op `cp`. Structure holds: 5 `##` sections, 19 `###` subsections, all 52 `ERR_` rows in §5, and the file still ends on the complete `| ERR_CLOCK_NOT_MONOTONIC | 422 |` row — no 64k-cap truncation. Every file in `workspace/implementation/` has an mtime of 09:39–09:58, well before the 11:49 green sweep, confirming Steps 8 and 9 edited only PRD prose and that the 8× 209/209 `results.$i.json` still describe exactly the shipped implementation. No re-run of the sweep was required.

**PIPELINE COMPLETE** — all nine steps finished; `workspace/PRD_COMPLETED.md` written.
