# Worklog — task_3101_electronic_health_record_implementation_go_live_command

Scenario: Electronic Health Record Implementation & Go-Live Command Center (Epic Systems)

## Step 1: Create task directory — 2026-09-29T23:05:00.000Z

Task directory was pre-allocated by the caller: `./tasks/task_3101_electronic_health_record_implementation_go_live_command/` with an empty `workspace/` inside. Verified present; no new index computed and no other `task_*` directory created. Initialized this worklog.

## Step 2: Generate Scaffold — 2026-09-29T23:34:00.000Z

All three artifacts are written and the skill's linter reports clean. No sibling task directories were read; everything was generated from the scenario text plus the scaffold-generator spec.

### Files written

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 2371 | `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles` |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1160 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1320 | `scaffold_corner_design` only |

Neither design key appears inside `SCAFFOLD.yaml`.

### Counts
- **Entities:** 18 (`common_fields: true` on all but `InterfaceMessage`).
- **State machines:** 19 entity blocks (18 distinct entities — `PatientOrder` carries two parallel dimensions), 99 transitions, 19 initial states, 32 terminal states, with cyclic loops on `SystemBuildItem`/`Department`/`TestDefect`/`InterfaceChannel`, a `posture_driven` loop, and a parallel-dimension machine.
- **Concurrency rules:** 3 (all OCC on a parent `version`; each write endpoint takes its `expected_*_version` and bumps the parent version).
- **Calculations:** 12 (8 with variants). **Validations:** 44. **Endpoints:** 137. **Errors:** 43 (all reachable — 0 unreferenced). **Roles:** 14.
- **§1.8:** 9 rules / 22 instances (each rule ≥ 2, differentiation clauses honored: distinct entity domains, distinct formula modes (a)/(b)/(a), distinct error-category pairs, distinct interval semantics, distinct conserved quantities, etc.).
- **§1.9:** 9 sections / 39 instances (e.g. entities, state_machines, calculations, validations, endpoints, errors, rbac, cross-cutting layers, consistency_model) + 2 `excluded_because` stubs citing real §1.8 instance names.

### Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
Coverage
  §1.5 endpoints declared:    137
  §1.1 entities declared:     18
  §1.8 instances scanned:     22
  §1.9 instances scanned:     37
  Calls scanned (§1.8+§1.9):  509
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
I also verified separately: zero forbidden concurrency vocabulary, every `grounds` reference resolves, every error id is referenced, all `${var}` placeholders close, OCC version inputs are `${var}`-backed (never literals), and all formula-derived asserts were computed as literals by executing the formulas (e.g. `readiness_score==60.00`, `optimistic==95.00`, `customization_risk_points==92.00`, `provisional_charge_cents==14814.01`, `final==12875.00`, `variance==1.00`, `sla==33`/`66`, ratio `80.00`, trainer count 2→0, order balance 0→1→0).

### Difficulty and corner-design coverage
The scaffold is pushed to the Expert band with a dense, tightly-coupled surface: the archetype is **posture-driven gating** (derived `readiness_posture` on `EhrImplementation` gates its whole child tree, recomputed by a multi-stage weighted calculation whose channel term *replaces* the per-department term) blended with **temporal windowing**, over four difficulty layers (OCC, cascading side effects, dual-variant calculation, ops-run checkpoint). Difficulty comes from ≥4 transitive cascades (the depth-4 defect-resolution chain TestDefect→TestScenario→SystemBuildItem→Department→Facility, the depth-3 go-live chain program→facility→department, the depth-2 message-rejection chain) each spelled out hop-by-hop in `side_effects`; two dual-variant calculations on different domains (readiness posture vs charge-capture) plus a third (conversion variance); combinatorial formulas in ≥2 distinct modes (tiered-marginal allocation with an order-of-operations weight/depth/round chain, and per-line-rounding-then-sum where a one-cent divergence is the trap); three parallel/cyclic state machines; priority conflicts across three different error-category pairs (state-vs-safety, state-vs-fiscal, business_constraint-vs-temporal); boundary precision on a staffing percentage and on an empty-set pass-rate; cross-entity state dependencies across two different entity pairs; temporal-overlap rules with genuinely different interval semantics (facility cutover timeline vs per-person shift capacity); and two compensating invariants over different conserved quantities (an order-unit balance and a trainer headcount). Corner coverage is broad but not weaker: it audits §1.5 for reachability of creation/retrieval/listing/pagination, defaults, enum and type constraints, not-found error specificity, invalid-from and terminal-lockdown rejections, idempotent replays, GSOD denial and segregation-of-duties enforcement, catalog completeness, self-referential FK reverse-lookup, rollback compensation, and immediate-consistency visibility — every corner carrying an executable empty-DB recovery chain, and the two corners already owned by §1.8 emitted as `excluded_because` stubs rather than duplicated tests.

## Step 3: Copy Shared Files — 2026-09-29T23:35:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-29T23:46:00.000Z

Done. PRD generated and verified.

### Output

`workspace/PRD.md` — 538 lines.

Note: `workspace/INSTRUCTION.md` already existed; I did not touch it. The task's `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, and all sibling tasks were left unread.

### Section headings

- `# Ehr Implementation Go Live API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` → 2.1 User and Role-Based Access Control · 2.2 API Response Structure · 2.3 Pagination · 2.4 Common Resource Properties and Identifier Conventions · 2.5 Readiness Posture and Gating of Child Operations · 2.6 The Ops-Run Epoch and the Logical Clock · 2.7 Optimistic Concurrency on Version-Carrying Writes · 2.8 Nested Resource Retrieval and Existence Ordering · 2.9 Precision, Rounding and Representation of Numeric Values · 2.10 Segregation of Duties and Trainer Credentialing Safeguards · 2.11 Validation Priority Ladder · 2.12 Foundation Content, Local Customization and the Risk Ceiling · 2.13 The Training and Certification Floors · 2.14 Conserved Quantities
- `## 3. Business Logic & Workflows` → 3.1 Program Lifecycle and Readiness Posture · 3.2 Facility Rollout, Data Conversion and Cutover Readiness · 3.3 Department Structure, Build Items and Customization Risk · 3.4 Role-Based Training, Proficiency Gating and Trainer Credentialing · 3.5 Test Cycles, Defect Remediation and the Blocking Chain · 3.6 Interface Build, Message Validation and Cutover Readiness · 3.7 Patient Orders: Conversion, Charge Capture and Paper Backfill · 3.8 Revenue Cycle Stabilization and the Denial Revert · 3.9 Cutover Planning, Downtime and the Go/No-Go Decision · 3.10 Command Center Staffing and Issue Triage · 3.11 Post-Live Optimization Backlog
- `## 4. Endpoint Definitions` (8 domain-grouped sub-tables: 4.1 Implementation Programs · 4.2 Facilities and Cutover · 4.3 Departments and System Build Items · 4.4 Staff, Training, Trainers and Proficiency · 4.5 Test Scenarios and Defects · 4.6 Data Conversion and Patient Orders · 4.7 Interfaces and Messages · 4.8 Command Center Tickets, Staffing and Optimization Backlog)
- `## 5. Error Code Catalogue`

### Hard-contract reports

```
Field coverage check:
- entities[].fields: 124 distinct required (170 field entries), 124 present, 0 missing
- endpoints[].request_body: 71 required body identifiers, 71 present, 0 missing
- endpoints[].query_params: 28 optional identifiers, 28 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 44 checked, 44 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 99 checked, 99 fully expressed (from/to + preconditions paired with error_id + side_effects), 0 missing
- calculations[]: 12 checked, 12 fully expressed (formula, constants, precision, algorithm, variants), 0 missing
- validations[] conditions: 44 checked, 44 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 87 non-empty side_effect sets + all applies_to scopes checked, 87 expressed, 0 missing
- entities[].fields[] structured content: 170 entries checked, 170 reconstructible from prose, 0 missing
- sibling-branch symmetry: 25 same-from-state sibling groups (plus 1 parallel-dimension pair) checked, 25 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 765
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional mechanical checks: §2.2 emitted byte-verbatim from `section-2.2-response-structure.md` (including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`); §4 carries all 137 scaffold endpoints in 4-column tables; §5 carries all 43 error IDs in a 2-column table; all 14 roles, all state/enum strings, and all 43 error IDs appear as exact backticked tokens; no audit footer in the file.

### Adjudications

- **Zero-Silence Rule / no-omission.** The scaffold has no `Zero-Silence`-named construct, so I applied the rule as its general form (no scaffold rule may be silently dropped). Every scaffold entry is expressed in prose: I verified mechanically that the identifier sets (entity fields, endpoint inputs, error IDs, role names, state values) are fully covered and that no §2/§3 subsection omits a rule. Field names that had no natural narrative home — filter keys (e.g. `ehr_implementation_id`, `proctor…`, `linked_test_defect_id`), `target_epoch`, `posture_view`, `to_iso8601`, `sent_utc`, `reconciled_count` — were given **natural homes** rather than a dumping-ground list: filter keys into the §2.8 nested-retrieval paragraph, `target_epoch` into §3.11, `posture_view` into §3.1, `to_iso8601` into §2.6. The two mechanically-detected gaps (`balance_cents`, `test_scenario_id`) were repaired in-place in §3.5/§3.2 and the diff re-run to empty (two passes).
- **Contract 2 framing for OCC.** Per the skill's explicit prohibition, the three `concurrency_rules` are written purely as staleness guards ("a mismatch with the parent's current `version`"), never as "simultaneously"/"race" language.
- **Rule precedence.** The scaffold has two validation rows (priority 11 posture and priority 9 state) whose relative order matters; I stated the ladder order in §2.11 and called out two explicit precedence consequences.
- **No pseudocode.** All formulas were translated to natural language (e.g. the four-tier customization risk, the per-line-then-sum charge capture ordering, the waterfall allocator). No operator syntax, no "approximately"/"roughly"/"~". Spelling/grammar slips found on self-review were corrected (`ERROR_BLOCKS_DEPARTMENT` → `ERR_DEFECT_BLOCKS_DEPARTMENT`; "*unrounded*"/"Rounded" → "unrounded"/"rounded"; missing sentence opener after an edit).
- **No report files created.** The three PASS reports above live only in this message; nothing was appended to `PRD.md` or any sibling file. No `SCAFFOLD_*_DESIGN.yaml`, sibling task, or `SCAFFOLD_DIFFICULTY_DESIGN.yaml`/`SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-09-30T01:24:00.000Z

All audits pass. Here is the summary.

### Files written

**`test_helpers/`** (9 files, 2,357 lines)
| File | Lines |
|---|---|
| `__init__.py` | 30 |
| `types.py` | 588 |
| `api_client.py` | 482 |
| `api_errors.py` | 107 |
| `assertions.py` | 227 |
| `factories.py` | 221 |
| `constants.py` | 100 |
| `test_users.py` | 46 |
| `fixtures.py` | 556 |

**`test_suite/`** (15 files, 3,753 lines)
| File | Lines |
|---|---|
| `conftest.py` | 75 |
| `test_01_dual_variant_calculations.py` | 295 |
| `test_02_combinatorial_formula.py` | 236 |
| `test_03_non_linear_state_machines.py` | 163 |
| `test_04_transitive_cascades.py` | 155 |
| `test_05_priority_pairs.py` | 232 |
| `test_06_boundary_precision.py` | 175 |
| `test_07_cross_entity_dependencies.py` | 200 |
| `test_08_resource_temporal_overlap.py` | 156 |
| `test_09_compensating_invariants.py` | 184 |
| `test_20_corner_resource_creation.py` | 452 |
| `test_21_corner_listing_and_initial_state.py` | 175 |
| `test_22_corner_terminal_states.py` | 171 |
| `test_23_corner_calculations.py` | 145 |
| `test_24_corner_validations.py` | 396 |
| `test_25_corner_rbac_and_sod.py` | 404 |
| `test_26_corner_concurrency_layers.py` | 288 |
| `test_27_corner_cross_aggregate.py` | 305 |

### Test count and breakdown

- **117 test functions** collected cleanly (`pytest --collect-only`).
- **Queue A (Difficulty): 44 tests** — all 22 instances across all 9 rules carry exactly 2.
- **Queue B (Corner): 73 tests** — all 37 non-stub instances carry ≥1; the 2 `excluded_because:` stubs were verified to resolve to real difficulty instances and were not translated.
- Zero untagged, dual-tagged, or dangling design tags. Zero `skip`/`skipif`/`xfail`. 247/247 PRD citations survive a literal grep. `api_client` covers all 137 scaffold endpoints exactly.

### Skipped instances — NONE

Every instance in both indices passed the PRD-first two-condition filter and was translated. No instance was dropped for lack of verbatim coverage or unique derivability.

### Adjudications

1. **`R<hash>` for SOD** — `c_trainer_cannot_both_proctor_result_and_certify` never reaches the segregation rung if the caller presents the `CredentialedTrainer` role, because the authorization rung (priority 2) fires first. The certifying call is therefore made with role `TrainingCoordinator` carrying `X-User-ID = trainer_id`, which is exactly the "same principal, different capacity" shape PRD §2.10 describes. The setup also keeps the trainer's own record **uncertified** to avoid inventing an unsupported same-staff certificate flow.

2. **`ERROR_PRECEDENCE` avoidance** — instance `r5b` has the state rung (9/12) ahead of the fiscal rung (29), so the sibling `load` **error code** is uniquely derivable; but the post-failure batch status `FAILED` (which PRD §3.2 equates with "allowed to fail on its own") is *not* derivable from the sticky VALIDATING state machine, so that sub-assertion was omitted and the status assertion states the derivable outcome (`VALIDATING`).

3. **Excluded a non-derivable assertion** in the patient-order corner: PRD does not state whether `final_charge_cents` is populated before reconciliation, so no test asserts it; the divergence is asserted only on `charge_variance_cents` after reconciliation, which is exactly the `final - provisional` definition the PRD pins.

4. **`c_revenue_cycle_index_tracks_denial_and_recovery`** is pinned only on a facility that is *not* yet `LIVE`, since the `LIVE → STABILIZATION_AT_RISK → LIVE` revert is a system-driven transition the PRD does not offer an entry point to force from empty DB.

5. **Observation floors** — PRD §2.13 names an observation floor but never states its numeric value, so no test asserts a specific STANDARD/ADVANCED hour figure; the floor tests use values the PRD itself supplies (recertify-from-EXPIRED, and an obviously short 3-hour record).

6. **SLA coverage** — the difficulty instance's "covered" branch was translated using an `AT_THE_ELBOW` shift whose window sits ahead of the logical clock, which is the only coverage shape its own `coverage_modifier` definition admits; it does not depend on the separately-specified shift-activation credential rule.

## Step 6: Generate Implementation — 2026-09-30T01:46:00.000Z

Implementation complete and verified.

### Files written

Under `workspace/implementation/`:

| Lines | File |
|---|---|
| 76 | `app.py` — Flask entry point, blueprint registration, error handlers |
| 226 | `db.py` — in-memory store, logical clock, pinned constants |
| 103 | `errors.py` — full error catalog + `ApiError`/rounding helpers |
| 185 | `request_utils.py` — shape gate, auth, pagination, filters |
| 44 | `response.py` — `meta`/`response_type`/`data` envelope |
| 261 | `routes/build_items.py` |
| 520 | `routes/command_center.py` |
| 518 | `routes/conversion.py` |
| 219 | `routes/departments.py` |
| 483 | `routes/facilities.py` |
| 334 | `routes/interfaces.py` |
| 329 | `routes/programs.py` |
| 707 | `routes/staff.py` |
| 332 | `routes/testing.py` |
| 318 | `services/calculations.py` — all 13 calculation rules |
| 121 | `services/core.py` — lookups, serialization |
| 24 | `services/lookups.py` |
| 293 | `services/recompute.py` — derived fields + event-driven cascades |
| 10 | `start.sh` (guarded dep install + `exec python3 app.py`) |
| 1 | `requirements.txt` |

**Endpoint count: 137/137** — programmatically cross-checked against the scaffold §1.5 table; zero missing, zero extra.

### Structure

- **OCC**: only the three §1.7/§2.7 writes take a version field (`expected_facility_version`, `expected_staff_version`, `expected_ehr_implementation_version`), compared against the stored value → `ERR_STALE_VERSION` (412). A version field on any other endpoint is `ERR_INVALID_REQUEST` (400).
- **State machines**: each transition is guarded at the single endpoint that fires it, and every guard runs in the PRD §2.11 ladder order (auth → authz → SoD → trainer credential → path FKs → body FKs → polymorphic ref → from-state → terminal → posture → epoch → safety → temporal → referential → capacity). `ERR_INVALID_STATE` is used for both "wrong from-state" and failed named preconditions (the PRD defines only that one state error).
- **Cascades**: implemented as *named event hooks* (`on_blocking_defect_change`, `on_department_rejection_change`, `on_proficiency_ratio_change`, `on_facility_entered_live`, `on_facility_billing_change`) invoked from the one operation that triggers them, plus full derivation recompute on epoch advance / clock set / reads. The go-live cascade runs depth-3 (`EhrImplementation → Facility → Department`); defect resolve runs its 4 links; message rejection runs depth-2. Every cascaded row gets its own `updated_at`/`version` bump; `InterfaceMessage` correctly has neither.
- **Calculations**: `Decimal`/`ROUND_HALF_UP` throughout; charge capture rounds per-line then sums (unrounded total only for the PROCEDURE gap line); customization risk rounds once at the end; readiness uses max-per-department with the interchannel term as a *replacement*; both readiness variants are published.
- **Storage**: process-local dicts only. Verified no seeding, no disk I/O, and `total_count: 0` after a fresh `start.sh` boot.

### Ambiguous passages and resolutions

1. **`RETEST_COOLDOWN_HOURS`** is named but never valued in PRD or scaffold. Chose 24. Also, the PRD only says a *failed attempt* sets `next_attempt_eligible_utc`, so I make a newly scheduled retake **inherit** the prior attempt's cooldown — otherwise the `ERR_RETEST_COOLDOWN_ACTIVE` rung would be unreachable, since a fresh row starts with the field null.
2. **Observation floors** (`ERR_TRAINER_OBSERVATION_INSUFFICIENT`) are never given values. Chose STANDARD 8h / ADVANCED 16h.
3. **`waiver_reason_min_hours(waiver_reason)`** has no table. Implemented as a keyed table defaulting to a 0-hour floor for any non-empty reason, so the non-empty-reason precondition is the effective gate.
4. **`command_center_escalation_minutes`** is referenced by two transitions but never valued or exposed by any endpoint. Chose 30 and evaluated it on read/clock-set; the two `ESCALATED` rows are unreachable without a value.
5. **User self-asserted transitions not in the declared tables.** Two derived values *cannot* be reached by any declared transition: (a) once a department is `BUILD_PENDING`, `proficiency_gate_open` going true can never advance it, because `BUILD_PENDING → BUILD_COMPLETE` only requires a built item — so the whole downstream flow (facility validation → go-live → stabilization) is unreachable; (b) no facility trigger exists for `BUILD_CONFIGURED → VALIDATED`. I deliberately did **not** invent either. I tried an auto-advance for (b) mid-way and reverted it, since the PRD's `status` vocabulary does not admit those edges. The two declared facility self-transitions (`BUILD_CONFIGURED ↔ REMEDIATION_REQUIRED`, `STABILIZATION_AT_RISK ↔ LIVE`) are event-triggered and working.
6. **Paper backfill**: "placed during the downtime window" is undefined. Used `encounter_utc <= go-live instant` for the (conservative) population of pre-cutover orders that get staged into `PAPER_BACKFILL_REQUIRED`; equal instants count as inside the window.
7. **`PROCEDURE` reconciliation credential**: "a credentialed charge-capture role" is unnamed; treated `OrderReconciler` and `RevenueCycleAnalyst` as credentialed (a default-deny here would make PROCEDURE orders unreconcilable).
8. **`order_reconciliation_balance`** is specified as two mutually exclusive credited paths; `ROUNDED_BACK` batches are `ERR_ALREADY_TERMINAL` per the error catalog rather than proceeding.
9. **Interface counters after `return-to-build`**: the scaffold zeroes the counters but the pass rate must remain 0.00 immediately after, which conflicts with recomputing them from live message rows. Resolved with a per-channel validation-cycle marker so the discarded cycle's messages stop counting while epoch scoping is preserved.
10. **`customization_risk_points` exceeds 40.00** is checked only at complete-build / complete-validation (the two endpoints the validation table names), not on `start-build`.

## Step 7: Run Tests and Iterate — 2026-09-30T01:51:00.000Z

Done. All 118 tests pass in a clean 8/8 parallel sweep (confirmed twice consecutively, plus a third clean run after the last comment-only edit).

### Summary

**Iterations run:** 8 parallel sweeps. Iteration 1 baseline: 96/117. Final: 118/118 on all 8 rounds.

**Tests deleted:** 1
- `test_adding_a_facility_moves_the_program_version_exactly_once` (test_26) — **UNIQUE-DERIVABILITY collapse**. It asserted `program.version` equals exactly 2 after a facility create because PRD §2.4 says `version` "increments by exactly one on every mutation of that row". PRD §2.7 explicitly *names* the mutations that move a program between reads — "epoch advances and department-tree mutations" — and enumerates the version-carrying writes as exactly three operations, none of which is facility registration. A faithful PRD-only reader can reasonably treat "that row" as the mutated row and bump the facility, not the program. Replaced by a sibling test asserting only PRD-derivable facts (PLANNING status, epoch 0, score unchanged and in range). The two other tests in that block were kept.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` `setup_rejected_build_item_with_sev1_defect` — moved the department-build close to after the item enters `IN_TESTING`. It was closed while the item was still `DRAFT`, which PRD §3.3 forbids ("requires that at least one of its build items has reached `BUILD_COMPLETE`, `IN_TESTING` or `VALIDATION_COMPLETE`"). This single fixture bug cascaded into 12 tests.

**Fixes applied to `test_suite/`** (fixture/assertion corrections toward PRD, no assertion weakened):
- `test_07` `_staffer_verified_but_not_credentialed` — the department-build close was issued with the item in `DRAFT`; now walks DRAFT→BUILD_COMPLETE first. Also moved the logical clock to each shift's `start_utc` before activation, which PRD §3.10 requires alongside the credential.
- `test_25` `_trainer_record_for` — the second trainer record was created on a stale `Staff.version`; now re-reads the staff's current version (PRD §2.7 guard).
- `test_02` / `test_24` customization tests — the 12-field `LOCAL_CUSTOM` profile scores 92.00, which PRD §2.12 makes inadmissible "either out of build or out of validation". Re-profiled to `FOUNDATION_ADAPTED` (69.00, below the 40-weight-adjusted ceiling) so the tier-ladder and rounding assertions still exercise the formula; the over-limit cases now assert the ceiling on the rung it actually guards.
- `test_06` — added a sibling for the gate close from `REMEDIATION_REQUIRED`.

**Fixes applied to `implementation/`:**
- `routes/command_center.py` — `create_ticket` referenced an undefined `program_id` (NameError → every ticket create 500).
- `routes/conversion.py` — load ×0exit over the ceiling left the batch `FAILED`; PRD §3.2 says the refusal happens *instead of* the batch failing on its own, so it now stays `VALIDATING`. Also publishes `variance_penalty_points` at begin-validation, and moved the claim-submit state rung ahead of the reconciliation constraint per PRD §2.11's ladder.
- `routes/interfaces.py` — close-validation refusal used `ERR_INVALID_STATE`; PRD §3.6 names `ERR_CHANNEL_NOT_VALIDATED`.
- `routes/facilities.py` — a cutover step starting exactly on the preceding step's `planned_end_utc` was refused as overlapping the whole handoff buffer; §3.9's windows are half-open, so adjacency is admitted with the derived duration.
- `routes/build_items.py` — `customization_risk_points` is now published on the item resource (a pure function of the item's own recorded fields) and the §2.12 ceiling guards create and start-build as well as complete-build/validation.
- `routes/departments.py` — the gate close is admissible from `REMEDIATION_REQUIRED` as well as `TRAINING_IN_PROGRESS` (PRD §3.4 makes the close the declared recovery from the slide).
- `routes/staff.py` — a recorded attempt now clears the retest cooldown (PRD §2.13 scopes the cooldown to "before the logical clock reaches it"); a passing result certifies the acting trainer's `PENDING_OBSERVATION` record for the exam's application, which is the record PRD §3.4's credential precondition reads; the undocumented `ADVANCED` observation floor was removed.

**Note on one non-obvious rule I had to implement:** the `test_09` reconcile+backfill conservation pair requires a paper slip to be backfillable against an already-`RECONCILED` order. PRD §3.7 scopes the extra charge gap to "a procedure order only", so a PROCEDURE order that already paid the gap at reconciliation cannot re-pay it at backfill — the pair is reachable exactly for the non-PROCEDURE types the test uses, and the backfill path now admits that second precondition.

**Confirmation sweep:** the subagent's own first clean sweep left no `results.{1..8}.json` on disk (its shell had `rm -f`'d them at the head of the final iteration). The orchestrator re-ran the identical 8-round parallel sweep to regenerate the required per-round evidence artifacts. Result — all 8 rounds `passed=118 / total=118 / failed=0`; written to `workspace/implementation/results.{1..8}.json`.
## Step 8: Finalize PRD — 2026-09-30T02:51:27.000Z

Done. `PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

### Summary

**Line counts:** PRD.md 538 lines / 92,994 bytes → PRD_FINALIZED.md 538 lines / 96,679 bytes (0.00% line delta; +3.96% byte delta). 14 of 538 paragraphs edited; no sections added, no prose reordered.

All 14 edits trace to the `<step_7_diff>` items and were validated empirically against a live instance of `implementation/` (started on a scratch port, then killed by saved PID).

### Change log

- **§2.4 — revise** — pinned that registering a facility or adding a department bumps the owning program's `version` by 1 (reframes it as a parent mutation, removing the "every mutation of that row" false universal) — `routes/facilities.py:129`, `routes/departments.py:103`, `db.py:182-185`.
- **§2.7 — revise** — replaced the "department-tree mutations" example with facility/department creation plus epoch advance, so the program's version actually moves for the stated reason — `routes/facilities.py:129`, `routes/departments.py:103`, `routes/programs.py:123`.
- **§2.9 — insert** — `customization_risk_points` is published on every read of a build item, not only on scoring operations — `routes/build_items.py:59-78,143,157,165`.
- **§2.12 — revise** — ceiling enforced at *begin build* as well as complete-build/close-validation; refusals leave the item in place; `FOUNDATION_ADAPTED` declared outside the ceiling's scope (only `LOCAL_CUSTOM` is gated) — `routes/build_items.py:191,206,240,85`.
- **§2.13 — revise** — observation floor pinned: `STANDARD` = 8 proctored hours, `ADVANCED` = 0; eight hours certify a STANDARD trainer exactly, three hours refuse — `routes/staff.py:111-124,555-560`.
- **§3.2 — revise** ×2 — `variance_penalty_points` published at begin-validation (not only at load) — `routes/conversion.py:185-193`; a ceiling refusal leaves the batch in `VALIDATING` instead of `FAILED` — `routes/conversion.py:218-225`.
- **§3.3 — insert** — ceiling governs begin-build, complete-build and close-validation — `routes/build_items.py:187-250`.
- **§3.4 — revise** ×5 — exam inherits the latest cooldown from prior same-pair exams — `routes/staff.py:615-623`; a passing result certifies the acting proctor's own `PENDING_OBSERVATION` record for that staff member/application — `routes/staff.py:719-729`; a recorded attempt consumes the cooldown — `routes/staff.py:702-707`; `PROFICIENCY_FAILED` is **not** set by record-result and is recovered by `reassign-training` — `routes/staff.py:730-741,279-293`; issue-credential counts CERTIFIED records over any application — `routes/staff.py:267`; gate close admissible from `REMEDIATION_REQUIRED` — `routes/departments.py:201`.
- **§3.6 — insert** / **§2.9/§3.5 — none** — an early close-validation refusal names `ERR_CHANNEL_NOT_VALIDATED` — `routes/interfaces.py:191-199`.
- **§3.7 — revise** — a paper slip is backfillable against a `RECONCILED` order as well as `PAPER_BACKFILL_REQUIRED` — `routes/conversion.py:425-430`.
- **§3.9 — revise** — replaced the "30-minute handoff buffer clear after the preceding step" claim with the actual half-open adjacency rule (start ≥ preceding end; end ≤ following start) — `routes/facilities.py:325-343`.

No `implementation/` edit was made (fixes in the diff were already applied); the two fixture-only items (department-build close, staff-version re-read) required no PRD text.

### Pre-edit search log (subject → paths enumerated → wording adjustment)

1. **Program `version` bump** — enumerated: `routes/facilities.py:129`, `routes/departments.py:103`, `routes/command_center.py:413`, `services/core.py:114-121`, `db.py:182-185`; confirmed via live probe (create→1, facility→2, department→3). Adjustment: framed as parent-row mutation rather than editing the global "every mutation of that row" invariant.
2. **§2.7 program-version rationale** — same paths; adjustment: replaced the enumerated "epoch advances and department-tree mutations" list.
3. **`customization_risk_points` publication** — `routes/build_items.py` `_score` callsites (126, 143, 157, 165) and `_customization_ceiling` (191, 206, 240); adjustment: none.
4. **Ceiling reach & scope** — `_customization_ceiling` at 191/206/240, plus `_score` at create; verified live (create publishes 92.0, start-build → 422). Adjustment: "not exposed to this ceiling at all" (covers both foundation classes without admitting untested negative cases).
5. **Observation floor** — `_observation_floor` (111-124), `MIN_OBSERVATION_HOURS` in `db.py:51` (defined, unused by the live path), fixtures/tests using STANDARD=8 and ADVANCED=8/12. Adjustment: numeric tier only (8 for STANDARD, 0 for ADVANCED), softening a first draft that over-claimed about non-negative validation.
6. **Begin-validation publication** — `begin_batch_validation` (185-193) vs `load_batch` (213-217); live probe confirmed create→0.0, begin-validation→1.0. Adjustment: none.
7. **Ceiling refusal state** — `load_batch` (218-225), `reconcile` (251), `rollback` (272), `FAILED` never assigned; live probe confirmed stays `VALIDATING`. Adjustment: none.
8. **§3.3 ceiling cascade** — all three callsites; adjustment: described as "begin build / complete its build / close validation", not a new transition.
9. **Exam cooldown inheritance** — `create_exam` (610-633), `record_result` (696-707), `mark_no_show` (758-761); live probe confirmed exam2 inherits cooldown, pass clears it, exam3 re-inherits the earlier instant. Adjustment: "latest cooldown instant any earlier exam … has left behind" (does not claim only the immediately preceding exam).
10. **Proctor-record certification on pass** — `record_result` 719-729, `issue_credential` 267; verified live that a proctor's own PENDING record flips to CERTIFIED on the pass. Adjustment: none.
11. **Cooldown consumption** — `record_result` 702-707; live probe confirmed. Adjustment: none.
12. **`PROFICIENCY_FAILED` reach** — only reader `reassign_training` (284) and the explanatory comment; no writer. Adjustment: de-linked from the failure path and attached to the recovery action.
13. **Issue-credential CERTIFIED scope** — `any(t["status"]=="CERTIFIED" for t in L.staff_trainers)`; adjustment: added "over every trainer record on file for them whatever the application".
14. **Gate close from `REMEDIATION_REQUIRED`** — `departments.py:201`; adjustment: none.
15. **Channel close error code** — `interfaces.py:191-199`, distinct from §3.6's other cutover `ERR_CHANNEL_NOT_VALIDATED` sites (`facilities.py:246`, `programs.py:197`, `facilities.py:445`). Adjustment: none.
16. **Backfill from `RECONCILED`** — `backfill_order` 425; verified live (reconcile→backfill leaves balance at 0). Adjustment: dropped an off-scope sentence about reopen-claim that I had initially added.
17. **Cutover adjacency** — `create_cutover_task` 325-343 and `HANDOFF_BUFFER_MINUTES` elsewhere. Adjustment: reworded to state the pure overlap rule (adjacency; end ≤ next start) rather than the "30-minute clear buffer" claim, preserving the constant where it genuinely appears.

Every edit's wording was checked against all enumerated callsites, including paths Step 7 never exercised (e.g. `FOUNDATION_ADAPTED` ceiling, other `ERR_CHANNEL_NOT_VALIDATED` sites, reopen-claim).

## Step 9: Complete PRD — 2026-09-30T02:58:20.000Z

PRD_COMPLETED.md written.

### Summary

**Source → output**: `workspace/PRD_FINALIZED.md` (538 lines, 96,679 chars) → `workspace/PRD_COMPLETED.md` (538 lines, 99,130 chars). Delta **+2,451 chars**, no lines added or removed (13 edited lines, inline inserts/revisions only; no new sections, no new paragraphs).

**Counts**: 13 changes total — **13 ambiguity-pins, 0 mismatch-revisions**. (The implementation matches finalized PRD on every point I checked; the only divergences were places PRD left two readings open.)

### Changes (one bullet each)

- §3.1 program lifecycle — insert — ambiguity — go-live's `GO_NO_GO_DECISION` precondition stated for "the facility's" task; pinned that any one facility's decision task being `COMPLETE` suffices (a program-wide search, not a specific facility) — `implementation/routes/programs.py:222-236`
- §3.1 readiness score — insert — ambiguity — department contribution given only for same-severity defects; pinned that a mixed `SEV1`+`SEV2` department takes the 40-point `SEV1` max, and an orphaned defect contributes nothing — `implementation/services/calculations.py:64-84`
- §2.8 existence ordering — insert — ambiguity — body FK order given but ticket `department_id` timing unstated; pinned that all creating-endpoint FKs are validated at creation — `implementation/routes/command_center.py:95-98`
- §3.2 facility registration — insert — ambiguity — `rollout_wave` said "1-based" without saying whether 0 is accepted; pinned that wave 0 is refused as invalid — `implementation/routes/facilities.py:106-107`
- §3.2 conversion batches — insert — ambiguity — "an `attempt_epoch` the client may not choose freely" leaves the enforcement point open; pinned that staging requires `attempt_epoch == current_epoch_index`, refused `ERR_BATCH_SIZE_INVALID` before the row exists — `implementation/routes/conversion.py:86-135`
- §3.3 build item creation — insert — ambiguity — `customization_depth` domain and risk-points publication timing unstated; pinned non-negative integer and score published at creation — `implementation/routes/build_items.py:109-128`
- §3.4 staff registration — insert — ambiguity — unstated that `primary_facility_id` must belong to the registration program and `department_id` to that facility — `implementation/routes/staff.py:176-183`
- §3.7 order reconciliation — insert — ambiguity — "an actor without the charge-capture credential" never names who holds it; pinned it to `OrderReconciler` and `RevenueCycleAnalyst`, and noted reconciliation republishes the provisional charge — `implementation/routes/conversion.py:385-399`
- §3.8 claim response — revise — ambiguity — prose capped recording at `CLAIM_SUBMITTED` while also describing payment moving an accepted claim to paid; pinned the admitted states to `CLAIM_SUBMITTED` **or** `CLAIM_ACCEPTED` — `implementation/routes/conversion.py:504-530`
- §3.9 cutover plan — insert — ambiguity — unstated rejection shape for a window that ends at or before it starts; pinned invalid request — `implementation/routes/facilities.py:322-323`
- §3.10 tickets — revise — ambiguity — `target_ref` listed a patient order, but the documented §2.8 unresolved-ref error and impl resolution cover department/facility/channel only; pinned those three and named the `at_the_elbow_zone` enum — `implementation/routes/command_center.py:99-108`
- §3.10 staffing shifts — insert — ambiguity — unstated whether closed shifts still occupy the roster; pinned that `COMPLETED`/`NO_SHOW`/`REASSIGNED` shifts impose no overlap restriction — `implementation/routes/command_center.py:257-273`
- §3.11 backlog scheduling — insert — ambiguity — "items already `SCHEDULED` for that same epoch" leaves two readings; pinned that consumed capacity counts items `SCHEDULED`, `IN_PROGRESS` or `RELEASED`, budget measured only for the named epoch, and "exceeds a whole epoch" compared strictly against 30 — `implementation/services/calculations.py:308-318`, `implementation/routes/command_center.py:476-480`

**Not changed despite looking unpinned** (documented in impl comments as deliberately left open, and not decidable from the PRD): the retest cooldown length (`RETEST_COOLDOWN_HOURS = 24`), the waiver-reason hour floors, and the ADVANCED observation floor — PRD §2.13 already states ADVANCED carries no floor beyond non-negativity, which impl honors via `_observation_floor`. The `error_id`/status pairs for `bed_count`, `department_code` uniqueness, and cutover `block_reason` are not in PRD but are already swept up by §2.11's generic "malformed payload → `ERR_INVALID_REQUEST`" clause.
