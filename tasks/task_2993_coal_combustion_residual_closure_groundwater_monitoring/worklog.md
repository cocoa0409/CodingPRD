# Worklog — task_2993_coal_combustion_residual_closure_groundwater_monitoring

## Step 1: Create task directory — 2026-09-06T03:18:25.540Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2993_coal_combustion_residual_closure_groundwater_monitoring` and its `workspace/` subdirectory. Index 2993 was fixed by the scenario number (no ./tasks/ scan performed, per orchestration instructions — concurrent pipelines on this host make auto-allocation unsafe).

## Step 2: Generate scaffold — 2026-09-06T04:57:01.730Z

Step 2 is complete. All three scaffold artifacts are written, parse cleanly, and the linter is clean.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2993_coal_combustion_residual_closure_groundwater_monitoring/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3602 | 173,882 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1663 | 122,890 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3028 | 223,511 |

**SCAFFOLD.yaml (§1.0–§1.7)** — api_prefix `/ccr`, 14 entities, 11 state machines, 3 `concurrency_rules`, 20 calculations, 57 priority-ordered validations, 65 endpoints (29 GET / 35 POST / 1 PATCH), 55 errors, 7 roles. complexity_profile: `compliance_audit` / `posture_driven_gating`, cyclic state machines, flat topology, `segregation_of_duties` role model, immediate consistency, layers = rate_threshold_triggers, cascading_side_effects, dual_variant_calculation, optimistic_concurrency. Contains **neither** `scaffold_difficulty_design:` nor `scaffold_corner_design:` (grep exit 1).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — single top-level key; all 9 canonical rule_ids × 2 instances = 18.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — single top-level key; all 9 guide sections, 75 instances = **47 active** test recipes + 28 `excluded_because` stubs: entities 12/0, state_machines 8/5, calculations 8/8, validations 4/4, endpoints 4/1, errors 3/8, rbac 3/0, complexity_layers 4/2, consistency_model 1/0. All 75 names unique across the union with §1.8; every stub cites a real §1.8 instance. `bulk_action` omitted (no bulk endpoints exist).

**Lint:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (657 calls scanned across 18 + 47 instances). Two lint fixes were needed on the final section: a list-output capture (`$.data.total_count` -> `"$.data[0].id"`), which also had to be quoted for flow-mapping YAML.

**Things the orchestrator should know**
1. The directive line "Generate task harder than expert level!" was deliberately **not** copied into `scenario:` (it is encoded as `complexity_profile.difficulty_level: expert_plus`), so it cannot leak into PRD.md via the scaffold.
2. Four consistency patches were made to SCAFFOLD.yaml this session, all to remove internal contradictions the design files depend on: `stability_posting_due_date` is now unconditional and always re-derived from the *governing* assessment (field description + endpoint side effect); `GET /ccr/units/{id}/compliance-summary` now pins its cost fields/`recommended_method` to the unit's APPROVED plan (null otherwise) and defines `open_ssi_count`; and an `ASD_APPROVED` slip was corrected to `ASD_ACCEPTED`.
3. Three earlier edits improved reachability: priority-18 wording (so a missing plan reports `ERR_NO_APPROVED_CLOSURE_PLAN`, not `ERR_INVALID_UNIT_STATE`), the frozen-posture clause, and `closure_timeliness`.
4. No sibling task directory was read at any point; `.scratch/step2/` was removed and the parent `.scratch/` left intact; `worklog.md` was not touched.

**Orchestrator verification**: line counts confirmed (3602 / 1663 / 3028); grep confirms no difficulty-directive text and no design keys in SCAFFOLD.yaml.

## Step 3: Copy shared files — 2026-09-06T04:57:21.523235715Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (bash only, no subagent).

## Step 4: Generate PRD — 2026-09-06T05:15:40.848080938Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **532 lines**, written incrementally via `cat >>` appends (no one-shot Write), ending cleanly on the last row of the §5 table with no audit footer.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Actors, Identity Headers and Access Control · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Resource Identity, Mutation Counters and Append-Only Records · 2.5 The Logical Regulatory Clock · 2.6 Money, Measurement Precision and Rounding Discipline · 2.7 Stale-Version Rejection on Tonnage and Laboratory Appends · 2.8 The Compliance Posture Gate · 2.9 Licence Standing, Discipline Gating and Two-Signature Controls · 2.10 Reference Resolution and the Order of Refusals (full 57-step precedence chain)
- §3 Business Logic & Workflows — 3.1 Bringing a Disposal Unit into the Program · 3.2 The Professional Roster and Structural Stability Certification · 3.3 Designing and Certifying the Groundwater Monitoring Network · 3.4 Sampling Rounds and Laboratory Data Capture · 3.5 Statistical Evaluation, the Monitoring Phase Cycle and Alternate Source Demonstrations · 3.6 Closure Planning, Approval, Deadlines and Execution · 3.7 Beneficial Reuse of Ash and the Tonnage Ledger · 3.8 Post-Closure Care and Cap Integrity · 3.9 The Public Operating Record and Community Engagement
- §4 Endpoint Definitions (4-column table, all 65 rows)
- §5 Error Code Catalogue (2-column table, all 55 rows)

**Coverage check — nothing missing, nothing had to be back-filled for coverage**
- Endpoints: 65/65 present in §4 (includes `/_clock/set_current_utc`); every list endpoint's filter set named in §3 prose (all 36 distinct filter identifiers verified present).
- Errors: 55/55 in §5, and all 55 also appear in §1–§4 prose at their point of use; 0 duplicate rows. Every one of the 57 validations' `error_id` values appear in prose.
- Entities: 14/14 covered (12 by name, `StabilityAssessment` and `CapInspection` by natural-language phrase).
- Roles: 7/7 (`UtilityAdmin`, `ProfessionalEngineer`, `Hydrogeologist`, `StatisticalReviewer`, `ComplianceOfficer`, `Regulator`, `PublicViewer`).
- Calculations: all 17 covered by content (including the corrective-action assurance band/oversight ordering, both cost variants, the reuse score weights, and the posting obligation roll-ups).
- Concurrency: all 3 OCC rules in §2.7 with write operation, OCC field, error id and 412.
- State machines: 0 gaps — every state and every transition of all 6 machines appears, transitions in explicit `FROM -> TO` form.

**Hard Contract reports**
- **Contract 1 (Field-Name Coverage): PASS** — required set 200 names (189 entity/output fields + 11 endpoint-only identifiers incl. `expected_unit_version`, `expected_sampling_event_version`, `to_iso8601`, `limit`, `offset`); 200/200 present in backticks, 0 missing.
- **Contract 2 (Rule Coverage): PASS** — 57/57 validations, 17/17 calculations, 6/6 state machines (all states + all transitions), 3/3 concurrency rules, 55/55 errors.
- **Contract 3 (§3 Path Purity): PASS** — 0 violations across §3 (lines 220–399): no backtick token starts with `/`, no bare HTTP method, no method+path combination. The only slash-prefixed token anywhere outside §4 is the `/ccr` mount statement in §1.

**Two things worth flagging to the implementation step** (internal SCAFFOLD contradictions the doc generator adjudicated):
1. `cost_variance_pct` — entity field says `/ min(...)`, §1.3 calculation says `/ max(...)`. Resolved to **max** (calculations block is authoritative and carries the precision notes); PRD reads "as a percentage of the larger of the two present values".
2. `extension_demonstration_due_date` — entity field says 14 days, both the endpoint side effect and `EXTENSION_DEMONSTRATION_WINDOW_DAYS` say 30. Resolved to **30 days**.
3. `closure_initiated_on` — transition says "current clock date", endpoint says `= initiated_on`. Resolved to the endpoint's explicit request->field mapping.
4. `community_meeting_held_on` is optional at posting creation (input marks it optional) even though the field description calls it "required for EXTENSION_DEMONSTRATION"; the requirement is actually enforced later at extension-grant time via `ERR_COMMUNITY_ENGAGEMENT_INCOMPLETE`. PRD states it that way.
5. `governing cap inspection` is used by the segregation-of-duties rule but never defined in the scaffold; PRD projects the same convention the scaffold defines for the governing stability assessment (latest `inspected_on`, ties broken by later `created_at`).

Scratch dir `.scratch/step4/` was used and removed; the parent `.scratch/` was not touched. No sibling task dirs, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or `worklog.md` were read or written.

**Orchestrator truncation check (mandated)**: `tail -15` shows PRD.md ending on the final `ERR_LICENSE_NOT_ACTIVE | 422` row of the §5 catalogue — a real section boundary, not a mid-sentence cut. Independently verified: 55 error-table rows, 55 unique ERR ids, 65 `/ccr` paths in §4, and no scaffold/difficulty-directive text anywhere in the file. No regeneration needed.

## Step 6: Generate implementation — 2026-09-06T05:55:36.561692446Z

Implementation complete and verified.

## Modules written (`workspace/implementation/`, 3527 lines total)

| File | Lines | Role |
|---|---|---|
| `store.py` | 156 | in-memory dicts, logical regulatory clock, id/seq/version/date maths |
| `errors.py` | 80 | all 57 error ids -> HTTP status + default messages |
| `envelope.py` | 102 | `meta`/`response_type`/`data` envelope, pagination params, Decimal encoder |
| `guards.py` | 72 | 7 roles, header auth (empty == absent), entity-backed role resolution, license/discipline gates |
| `shape.py` | 178 | declarative payload validator (types, ranges, decimal places, regexes, unknown-field rejection) |
| `calc.py` | 552 | every PRD calculation + posture derivation |
| `derive.py` | 297 | read-time re-derivation, agreement suspension cascade, 14 explicit serializers |
| `common.py` | 214 | lookups, state gates, segregation of duties, filters |
| `routes_read.py` | 323 | all 29 GETs incl. compliance-summary |
| `routes_units.py` | 278 | units, professionals, stability, closure lifecycle, `/_clock/set_current_utc` |
| `routes_monitoring.py` | 336 | wells, program config/certification, rounds, results, validate/reopen |
| `routes_stats.py` | 184 | evaluations, escalation cascade, ASD submission/decision |
| `routes_closure.py` | 325 | plans (certification diamond, approve, return-to-draft), extensions |
| `routes_reuse.py` | 211 | agreements, qualification/activation, shipments + returns (OCC) |
| `routes_care.py` | 121 | cap inspections, public postings, withdrawal |
| `app.py` | 87 | blueprint registration, request lock, error handlers, `0.0.0.0:$PORT` |
| `start.sh` | 10 | foreground `exec python3 app.py`, guarded pip install |

## Endpoints: 65 / 65

Programmatic diff of the Flask url_map against the PRD's endpoint table: **65 in PRD, 65 implemented, zero missing, zero extra** (29 GET, 35 `/ccr` writes, 1 `/_clock/set_current_utc`).

## Coverage

- **Calculations**: location restriction verdict, stability verdict + deficient criteria + governing/superseded, closure deadline (with extensions), post-closure care end, PV/nominal cost variants + variance + recommended method, background statistics (n/mean/stdev/upper limit) for INTERWELL and INTRAWELL, ASD deadline, network counts, sampling schedule, ASTM C618 spec test + qualification score, commitment exposure, ash mass balance, overdue/late postings, compliance posture. All money is integer cents; `Decimal` + ROUND_HALF_UP throughout.
- **State machines**: `closure_state` and `cap_integrity_state` as independent dimensions, cyclic program `phase` with escalation cascade and ASD-accept rollback, the plan fork-join diamond with return-to-draft clearing both halves and incrementing `return_count`, agreement DRAFT->QUALIFIED/DISQUALIFIED->ACTIVE<->SUSPENDED, shipment SHIPPED->RETURNED, event DRAFT<->REJECTED->VALIDATED, extension REQUESTED->GRANTED->RESCINDED/DENIED, posting POSTED->WITHDRAWN.
- **Validations**: the 57-position global refusal precedence chain, OCC on both `expected_unit_version` and `expected_sampling_event_version` (412), all 3 segregation-of-duties controls, license-active and discipline gates, future-date and uniqueness rules, FROZEN/RESTRICTED posture gates.

## Smoke test

Booted on port 33979 and ran four scripted end-to-end scenarios spanning ~90 calls: unit creation with cascade-created monitoring program, well network + certification, 4 background rounds + compliance round + validation, statistical evaluation producing `SSL_EXCEEDANCE` with the full DETECTION->ASSESSMENT escalation, ASD submit/accept and rollback to DETECTION/SEMIANNUAL, the plan certification diamond including return-to-draft, approval -> CLOSURE_PLANNED, extension grant/rescind returning the deadline to its exact pre-grant value, reuse qualify/activate/ship/return with correct 412 on a stale unit version, begin/complete closure, cap inspections DEFICIENT->PASS, posting withdrawal, license suspension gating, and pagination/404/405/401/403 envelopes. Every unexpected status traced to a defect in the throwaway test script (wrong field name, wrong role, or data that legitimately tripped a PRD gate) — each was confirmed against the PRD sentence and the implementation was correct in all cases; **no implementation change was needed**.

A second server on port 34771 confirmed zero persistence and zero seeding: fresh boot returned `total_count: 0` for units and professionals while the first server still held 10 units. Both servers were stopped by deriving a single PID from each exact port via `ss -ltnpH "sport = :$P"`; no `pkill`/`killall` was used. All 16 `.py` files ast-parse cleanly; `__pycache__` removed and no log/pid files remain in `implementation/`; `.scratch/step6` deleted with the sibling `step5` untouched.

## Step 5: Generate unit tests — 2026-09-06T06:25:14.599741223Z

Step 5 is complete. Everything is on disk at the task root; nothing landed under `workspace/` (which still contains only `INSTRUCTION.md`, `PRD.md`, `implementation`).

**`test_helpers/` — 9 files, 2482 lines**
`__init__.py` 24, `api_client.py` 379, `api_errors.py` 147, `assertions.py` 175, `constants.py` 310, `factories.py` 539, `fixtures.py` 742, `test_users.py` 128, `types.py` 38.

**`test_suite/` — 19 files, 4029 lines**
`conftest.py` 22.
Queue A (§1.8, 9 files, 37 tests): `test_difficulty_dual_variant_calc.py` 202, `test_difficulty_combinatorial_formula.py` 130, `test_difficulty_transitive_cascade.py` 185, `test_difficulty_boundary_precision_check.py` 138, `test_difficulty_cross_entity_state_dependency.py` 187, `test_difficulty_non_linear_state_machine.py` 222, `test_difficulty_priority_pair_validation_conflict.py` 154, `test_difficulty_resource_temporal_overlap.py` 164, `test_difficulty_compensating_invariant.py` 171.
Queue B (§1.9, 9 files, 45 tests): `test_corner_entities.py` 424, `test_corner_state_machines.py` 375, `test_corner_calculations.py` 483, `test_corner_validations.py` 279, `test_corner_endpoints.py` 240, `test_corner_errors.py` 155, `test_corner_rbac.py` 163, `test_corner_complexity_layers.py` 278, `test_corner_consistency.py` 57.

**Coverage — verified mechanically, not by eye.** A script re-parsed both design yamls and every test docstring: 82 test functions, 82 with exactly one `Design:` tag, zero malformed, zero dual-tagged, zero dangling (every tag resolves to a real `name:` in the yaml).
- §1.8: 18 non-stub instances, **18/18 translated** (37 tests — several instances carry multiple discriminating probes).
- §1.9: 47 non-stub instances (of 75 total; 28 are stubs), **45/47 translated**, per-section entities 10/12, state_machines 8/8, calculations 8/8, validations 4/4, endpoints 4/4, errors 3/3, rbac 3/3, complexity_layers 4/4, consistency_model 1/1.

**2 skipped, both in `entities`, both for the same reason** (condition 2 of the PRD-first filter — outcome not uniquely derived):
- `unit_ash_in_place_tons_is_recomputed_and_a_supplied_value_is_input_ignored` — asserts 201 with a client-supplied computed field silently ignored, but PRD priority 4 (line 163) permits `ERR_INVALID_REQUEST` for unknown fields carrying business meaning, so 201 vs 422 is not determined.
- `posting_identity_and_audit_fields_are_server_minted_and_input_ignored` — identical shape, identical ambiguity.
Neither was weakened, marked xfail, or stubbed; the gaps stay gaps.

**Health checks:** `python3 -m pyflakes test_helpers/*.py test_suite/*.py` -> rc=0, no output. `pytest test_suite --collect-only -q` -> **82 tests collected in 0.46s**, no import or collection errors.

**Design-literal correction worth flagging to Step 7:** the corner-errors instance `begin_closure_separates_the_missing_plan_from_the_missed_deadline` asserts `closure_timeliness == LATE` after a *refused* begin-closure, which contradicts PRD line 342 (timeliness is `PENDING` while `closure_initiated_on` is null). The test asserts `TIMELINESS_PENDING` and `closure_initiated_on is None`; the instance's discriminating claim (`ERR_NO_APPROVED_CLOSURE_PLAN` vs `ERR_CLOSURE_DEADLINE_MISSED`, never `ERR_UNIT_FROZEN`) is preserved intact.

Cleanup was scoped: only `.scratch/step5` was removed (the parent `.scratch/` and every sibling subdir are untouched), plus the two `__pycache__` dirs and `.pytest_cache` created by its own checks. No process-killing command was run, and `worklog.md`, `workspace/PRD.md` and `workspace/implementation/` were never read or written.

**Orchestrator verification**: test_helpers/ + test_suite/ total 6511 lines at the task root (no stray copies under `workspace/`); `pytest test_suite --collect-only -q` re-confirmed 82 tests collected with no import errors. Steps 5 and 6 were launched concurrently in a single message, so the implementation generator never saw `test_suite/`.

## Step 7: Run tests and iterate — 2026-09-06T06:46:54.203145595Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2 (baseline sweep, one batch of fixes, confirming sweep).

**Baseline:** 76/82 passing in all 8 rounds — 6 deterministic failures, all in the union set across every round (no flakiness, no load-induced failures).

**Tests deleted:** none. Every failing test's asserted rule was verbatim in PRD.md and uniquely derivable; all 6 were test-artifact bugs caught at STEP 2.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `seed_roster()` made idempotent (reads the roster via `list_professionals` and only registers licensees whose `license_number` is absent). PRD §2.10 makes `license_number` unique per `license_state`, so any test calling `seed_unit()`/`seed_roster()` twice (to build two units) collided with itself on `ERR_DUPLICATE_CODE` during setup. Also added the `MAX_LIMIT` import. This is the "bundled fixture helper invalidates its own first hop on reuse" signature — 2 tests fixed.

**Fixes applied to `test_suite/`:**
- `test_corner_state_machines.py` — two assertions read `unit["cap_condition_state"]`; PRD names the field `cap_integrity_state` (as the rest of the suite already does). Symbol bug, renamed both — 2 tests fixed.
- `test_corner_validations.py` (`test_a_duplicate_code_is_refused_in_its_own_scope_and_nowhere_else`) — the "untouched after a duplicate refusal" assertion pinned 22.00/42.00, but the setup installed the well through `fixtures.install_well()`, whose factory default is 20.00/40.00. Corrected the expected literals to the values actually installed; the rule under test (a duplicate refusal mutates nothing) is unchanged.
- `test_corner_complexity_layers.py` (`test_a_return_must_quote_the_version_the_later_shipment_produced`) — second shipment used `shipped_on = "2026-08-02"` while the logical clock sat on its documented default `2026-08-01`. PRD §2.5 lists a shipment's `shipped_on` among the dates that may not be future-dated, so the PRD-faithful implementation correctly returned `ERR_FUTURE_DATE_NOT_ALLOWED`. Changed to `2026-08-01`; the version-guard assertions (`third_version == second_version + 1`, stale 412, successful return) are untouched.

**Fixes applied to `implementation/`:** none — zero implementation defects found. The 65-endpoint implementation was already fully PRD-conformant.

**Final sweep (all 8 parallel rounds):** 82/82 passed in rounds 1, 2, 3, 4, 5, 6, 7 and 8. `total - passed == 0` cross-checks against 0 non-`passed` entries in every file. `results.{1..8}.json` left in place in `workspace/implementation/`.

`worklog.md` was not read or written; `workspace/PRD.md` and `workspace/sweep.sh` are unmodified; `.scratch/step7/` was removed and no sibling scratch dirs were touched.

**Orchestrator verification (independent, using the runner's real `tests[].status` key)**: all 8 `results.$i.json` present; each reports `passed=82 total=82`, 82 test entries, 0 non-passed, and `total - passed == len(non-passed)` cross-checks CONSISTENT in every file. The sweep was launched via the pre-written `workspace/sweep.sh` under `setsid nohup` with a `SWEEP_DONE` sentinel, so neither the reaping bug nor the early-return relaunch bug applies.

**Step 8 decision**: Step 7 reports 0 `implementation/` fixes but NOT zero iterations — it ran 2 iterations with 1 `test_helpers/` fix and 3 `test_suite/` fixes. The skip condition requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes, so it is not met. Step 8 therefore runs. Note for Step 8's scope: all four diff items are test-artifact bugs (a self-colliding fixture, a field-name typo, two wrong test literals), so most or all may turn out not to be PRD silences at all; a byte-identical PRD_FINALIZED.md would be a legitimate outcome here.

## Step 8: Finalize PRD — 2026-09-06T06:54:57.705139092Z

## Result: zero edits — `PRD_FINALIZED.md` is byte-identical to `PRD.md`

`workspace/PRD_FINALIZED.md` created by `cp`. Verified identical (`cksum 2028981328` both files).

- PRD.md: 532 lines / 115017 bytes
- PRD_FINALIZED.md: 532 lines / 115017 bytes
- Delta: 0 lines, 0.00%

## Change list

None. All four `<step_7_diff>` items are pure test-artifact bugs whose asserted rule is already verbatim and uniquely determined in PRD.md, and the implementation matches the PRD text exactly at each site. No PRD silence and no PRD/impl mismatch was reachable from any of them.

## Per-item verification log

**1. `fixtures.seed_roster()` made idempotent (self-collision on `ERR_DUPLICATE_CODE`)**
- (a) Subject: uniqueness scope of `license_number` on professional registration, plus the list-endpoint `limit` ceiling the fix relies on.
- (b) Impl paths read: `routes_units.py:103-127` (`PROFESSIONAL_SPEC`, `create_professional`, `unique_code(..., "license_state", ...)`), `common.py:110-118` (`unique_code` scope semantics), `routes_units.py:130-145` (`set_license_status`, the parallel write on the same entity), `derive.py:108` (`PROFESSIONAL_FIELDS`), `envelope.py:49-92` (`listing`, `PAGE_LIMIT_MIN/MAX`). Grepped `license_number` across all of `implementation/`.
- Finding: PRD §2.10 line 218 ("`license_number` is unique per `license_state`") and §3 line 242 ("unique within its licensing state") both pin it; impl scopes on `license_state` exactly. PRD line 84 / position 5 pins `limit` max 100, matching `PAGE_LIMIT_MAX`. Nothing under-determined.
- (c) No wording adjustment (no edit).

**2. `test_corner_state_machines.py` — `cap_condition_state` -> `cap_integrity_state`**
- (a) Subject: the canonical field name of the unit's second lifecycle dimension.
- (b) Impl paths read/grepped: `routes_units.py:54` (init `NOT_APPLICABLE`), `:232-233` (closure completion `NOT_APPLICABLE -> ADEQUATE`), `:254` (care-completion gate), `routes_care.py:43,52` (`DEFICIENT` / return-to-`ADEQUATE`), `calc.py:531,547` (frozen and watch predicates), `derive.py:89` (unit serializer), `routes_read.py:65` (compliance rollup). Grepped for `cap_condition_state` — zero hits anywhere in `implementation/`.
- Finding: PRD already uses `cap_integrity_state` at lines 136, 140, 190, 230, 236, 344; the typo existed only in two test assertions. Pure symbol bug.
- (c) No wording adjustment (no edit).

**3. `test_corner_validations.py` — expected `22.00/42.00` corrected to `20.00/40.00`**
- (a) Subject: `screen_top_ft` / `screen_bottom_ft` values, and the "a duplicate refusal mutates nothing" property.
- (b) Impl/test paths read: PRD line 258 (well install contract), `test_helpers/factories.py:178-211` (`well_payload` defaults 20.00/40.00; the background-well derived factory overrides to 22.00/42.00, the downgradient one to 20.00/40.00 — the fixture used the plain/downgradient path), `common.py:110-118` (`unique_code` raises before any mutation or version bump).
- Finding: the screen depths are free client inputs the PRD only bounds (top >= 0, bottom strictly deeper, <=2 decimals) — it never prescribes particular values, and it must not. The test simply asserted the wrong factory default. PRD §2.10 already scopes `well_code` uniqueness per unit, and no impl path mutates state on that refusal.
- (c) No wording adjustment (no edit). Deliberately did not add any statement about failed-write atomicity: that would be a new global claim across all 65 endpoints, far outside this item's scope, and is Step 9's territory if it matters at all.

**4. `test_corner_complexity_layers.py` — second shipment `shipped_on` `2026-08-02` -> `2026-08-01`**
- (a) Subject: future-date rejection of `shipped_on` and the logical clock's pre-set default.
- (b) Impl paths read: `routes_reuse.py:121` (`shipped_on` spec), `:132` (`common.no_future_date`), `:144-147` (commitment-window gate, ordered after the future-date check), `common.py:100-108` (`no_future_date` against `store.today()`), `store.py:36-53` (`CLOCK_DEFAULT`, `clock_now`, `today`), `routes_units.py:272-278` (`/_clock/set_current_utc`), `app.py:4`. Grepped `FUTURE_DATE` across `implementation/`.
- Finding: PRD §2.5 line 102 pins the default clock to exactly `2026-08-01T00:00:00Z` and forbids wall-clock fallback; line 106 names `shipped_on` in the no-future-dating group with `ERR_FUTURE_DATE_NOT_ALLOWED` (422); position 12 (line 171) orders it ahead of the §3 shipment gates (line 362, "after the posture gates"). Impl is exactly conformant — Step 7's own note confirms the impl was right and the test was wrong.
- (c) No wording adjustment (no edit).

Step 7 applied zero implementation fixes and deleted zero tests, so there was no impl-side behavioral choice to pin. Reporting zero edits honestly rather than manufacturing changes; the exhaustive scan for PRD silences elsewhere belongs to Step 9.

**Orchestrator note**: a byte-identical `PRD_FINALIZED.md` is the correct outcome here — the skip condition was not formally met (2 iterations, 4 test-artifact fixes), but Step 7 applied 0 implementation fixes, so there was no impl-pinned choice for Step 8 to document. Step 9 is unaffected and must NOT be identical; it runs the exhaustive PRD-vs-implementation scan and is partitioned by implementation module into sequential passes.

## Step 9: Complete PRD — 2026-09-06T07:38:45.47634838Z

Step 9 was run as **four sequential file-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module (pass 1 owned the `cp`; passes 2–4 edited in place). Result: **532 -> 536 lines**, 104 changed lines vs `PRD_FINALIZED.md`, **55 edits total** (51 from passes 1–3, 4 reconciliation edits from pass 4). Counts: ~36 ambiguity-pins, ~15 mismatch-revisions, 4 reconciliation fixes.

### Pass 1 — app.py, envelope.py, errors.py, guards.py, shape.py, store.py, common.py, routes_read.py (16 edits: 14 ambiguity-pins, 2 mismatch-revisions)
- §2.1 — insert — ambiguity — header emptiness is judged literally, so a whitespace-only header is *not* empty — `guards.py:44`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `store.py:74-76`
- §2.2 — insert — ambiguity — `api_request_timestamp` is real wall-clock, independent of the logical clock — `envelope.py:26`
- §2.2 — insert — ambiguity — pagination `meta` keys are absent entirely from non-list responses — `envelope.py:41-42`
- §2.3 — insert — ambiguity — pagination integers parsed after whitespace trim; `""` and fractional forms are non-integers; empty-string query param counts as omitted; unrecognised query params ignored, not refused — `envelope.py:95-102`
- §2.3 — insert — ambiguity — `created_at` ties keep insertion order; filters are exact string equality; the only two boolean filters are `network_certified`/`superseded`; derived filters refreshed per candidate row before filtering — `store.py:99-105`, `common.py:195-210`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are real wall-clock, not logical-clock — `store.py:80-96`
- §2.5 — insert — ambiguity — the eight future-date-barred fields are exhaustive — `common.py:103`
- §2.6 — insert — ambiguity — rounded decimals emitted as JSON numbers (`1.25`, not `1.2500`) — `envelope.py:16-20`
- §2.6 — insert — ambiguity — decimal places read from the literal as written; a numeric field must be a JSON number, not a quoted string — `shape.py:81-103`
- §2.9 — **revise** — **mismatch** — the licence and discipline gates apply on **writes only**; a SUSPENDED/LAPSED professional still resolves as an identity for reads — `guards.py:57`
- §2.10 positions 14/15 — revise — mismatch — both prefixed "On a write"
- §2.10 — insert — ambiguity — StabilityAssessment/CapInspection have no family error id — `routes_read.py:113-115`
- §2.10 position 4 — insert — ambiguity — dates must name a real calendar day; no string may be blank (whitespace-only counts as blank); all unknown keys refused; explicit `null` reads as omitted; absent body = `{}`; non-object body refused — `shape.py:37-49,150-166`
- §3.1 — insert — ambiguity — with more than one approved plan the earliest-created is read — `common.py:172-176`
- §4/§5 preambles — insert — ambiguity — trailing slash addresses the same route; three out-of-catalogue envelope refusals (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405 pre-auth, `ERR_INTERNAL` 500) — `app.py:24,52-80`
- Verified already-pinned: all 55 `errors.py` status mappings match §5 byte-for-byte; all 14 list filter sets and all 29 GET role sets match §3/§4 exactly; the 23-field compliance-summary body matches §3.1; all 8 `unique_code` scopes match §2.10.

### Pass 2 — calc.py, derive.py, routes_units.py, routes_monitoring.py (19 edits: 12 ambiguity-pins, 7 mismatch-revisions)
- §2.4 — insert — ambiguity — closed enumeration of every value recomputed per read (unit 10 fields, program 4, `result_count`, `shipped_tons_total`, `superseded`, `satisfied_obligation`/`days_late`) plus the three groups that only *look* derived but are stored snapshots (plan costs/`cost_variance_pct`/`recommended_method`, `effective_value`, `closure_timeliness`) — `derive.py:11-46,180-227`
- §2.5 — **revise** — **mismatch** — clock moves do not re-derive `closure_timeliness`; the `ON_TIME -> LATE` claim removed — `routes_units.py:60,207`
- §2.5 — insert — ambiguity — `to_iso8601` accepts 1–9 fractional digits and `Z` **or** numeric `±HH:MM`, refuses naive; response renders at 3 fractional digits — `shape.py:28`, `store.py:56,116`
- §2.8 — **revise** — **mismatch** — "a FROZEN unit accepts only remedial writes" was false; recast as the exact 7 frozen-gated and 2 restricted-gated writes, naming the non-remedial writes admitted while frozen — `calc.py:521-552`
- §3.1 — insert — ambiguity — the four siting numerics are `min: 0`, unbounded above, 2 dp (feet) / 3 dp (`seismic_pga_g`)
- §3.1 — **revise** — **mismatch** — registration posture is not decided by siting alone: an old `cessation_date` makes a brand-new ACTIVE unit immediately FROZEN — `calc.py:530-537`
- §3.2 — insert — ambiguity — licence-status path id -> `ERR_PROFESSIONAL_NOT_FOUND` 404; restating the same status still bumps `version`; `effective_on` not clock-checked — `routes_units.py:137-145`
- §3.2/§3.4/§3.5 — insert — ambiguity — governing-assessment, schedule and comparison-measurement tie-breaks all fall back to write order — `calc.py:153,192,281-284`
- §3.3 — insert — ambiguity — `patch_program`: explicit null == omitted, unknown key refused, empty body still bumps `version`, ordering checked on the *effective* pair, `ERR_INVALID_REQUEST` fires **after** the phase gate — `routes_monitoring.py:103-126`
- §3.3 — insert — ambiguity — `certify_network`: unconfigured window is `ERR_INVALID_REQUEST` and is the **last** of three checks; certification is neither one-shot nor phase-gated — `routes_monitoring.py:132-156`
- §3.4 — insert — ambiguity — round creation has no phase gate; `event_type` is descriptive/filterable only — `routes_monitoring.py:184-221`
- §3.4 — **revise** — **mismatch** — `unit_of_measure` is never cross-checked against `parameter_code`; `reporting_limit > 0` applies whenever present, including on DETECTED — `routes_monitoring.py:227-247`
- §3.4 — insert — ambiguity — on rejection the supplied `validated_on` is discarded; `NO_RESULTS` precedes `WELL_DECOMMISSIONED` — `routes_monitoring.py:300-314`
- §3.5 — insert — ambiguity — only `assurance_amount_usd_cents` is retained; re-filing allowed and overwrites — `routes_monitoring.py:166-181`
- §3.6 — **revise** — **mismatch** — `closure_timeliness` is a stored field written twice (`PENDING`, `ON_TIME`); `LATE` is unreachable by any code path — `routes_units.py:60,207`
- §3.7 — **revise** — **mismatch** — LOI and fineness score components are strictly proportional, not stepped to whole percentage points (2.50 % LOI deducts 25, not 20) — `calc.py:443-445`
- §3.7 — **revise** — **mismatch** — the suspension cascade suspends on `RESTRICTED` **or** `FROZEN`, restores only on `WATCH`/`COMPLIANT`, and is **write-time only** (exhaustive trigger list), so a clock move plus reads never moves an agreement — `derive.py:48-71`

### Pass 3 — routes_stats.py, routes_closure.py, routes_reuse.py, routes_care.py (16 edits: 10 ambiguity-pins, 6 mismatch-revisions)
- §3.5 — **revise** — **mismatch** — posture lands on `RESTRICTED` *unless a §2.8 freezing clause also holds*; the fourth hop fires on `RESTRICTED` or `FROZEN`; second escalation leaves `ssi_notice_due_date` alone; an SSI issued while already in ASSESSMENT escalates nothing — `routes_stats.py:91-106`
- §3.5 — insert — ambiguity — the ASD's named `certifying_professional_id` need only exist: neither the licence nor the discipline gate reaches it — `routes_stats.py:124`
- §3.5 — **revise** — **mismatch** — restoration conditioned on the recomputed posture reading WATCH/COMPLIANT; the unwind is conditional on the program actually being in ASSESSMENT/CORRECTIVE_ACTION; `asd_deadline_date` is not cleared — `routes_stats.py:170-183`
- §3.6 — **revise** — **mismatch** — the "recommendation can have drifted by approval" rationale was false: there is no unit PATCH endpoint at all, so `recommended_method` can never drift and the approval-time justification refusal is unreachable — `routes_closure.py:32-46,131,166`
- §3.6 — insert — ambiguity — no stage of a plan's life consults `closure_state` beyond the CARE_COMPLETE bar; a unit may hold more than one APPROVED plan; a second approval advances `closure_state` only if still ACTIVE but always rewrites `closure_plan_posting_due_date` — `routes_closure.py:146,151,171-175`
- §3.6 — **revise** — **mismatch** — extension-request posture reads WATCH *unless the restricted predicate also holds* — `routes_closure.py:219-233`
- §3.6 — insert — ambiguity — omitted/null `granted_months` reads as 0 and a zero-month grant is an ordinary success; deciding requires only not-CARE_COMPLETE — `routes_closure.py:251,257`
- §3.6 — insert — ambiguity — where several POSTED demonstrations exist, the earliest-created one alone is examined for `community_meeting_held_on` — `routes_closure.py:259-271`
- §3.6 — **revise** — **mismatch** — the frozen gate sits on the *decision*, so a DENY is refused too, and it follows the request's status check — `routes_closure.py:252-255`
- §3.6 — **revise** — **mismatch** — extension denial "leaves the unit completely untouched" tightened: it writes nothing and does not advance `version`, but the §3.7 reconciliation still runs and can move an agreement — `routes_closure.py:290-295`
- §3.7 — insert — ambiguity — reversed commitment window is `ERR_INVALID_REQUEST` 400 at position 4, ahead of the unit lookup (contrasted with §3.3's deferred check); the reuse lifecycle is gated only by the CARE_COMPLETE bar — `routes_reuse.py:40-45`
- §3.7 — insert — ambiguity — the qualification recomputation necessarily reproduces the stored pair, its six inputs being unmodifiable — `routes_reuse.py:76-78`
- §3.7 — insert — ambiguity — qualification is the one professional signature the discipline gate does not reach (licence gate still applies) — `routes_reuse.py:66-70`
- §3.7 — insert — ambiguity — a shipment or return advances the owning agreement's `version` whether or not its status moved — `routes_reuse.py:170,208`
- §3.8 — insert — ambiguity — the cadence escalation touches the program only when it was not already QUARTERLY — `routes_care.py:47-50`
- §3.9 — insert — ambiguity — `community_meeting_held_on` after `posted_on` is `ERR_INVALID_REQUEST` 400 at position 4, ahead of the unit lookup and the future-date rule — `routes_care.py:79-82`

### Pass 4 — reconciliation (4 edits)
- **ITEM A (cross-pass contradiction, resolved from source).** Pass 1 had written that nothing in the compliance-summary is cached and every field is re-derived at read time; pass 2 flagged this as misleading and left it for adjudication. Field-by-field from `routes_read.py:47-88`: genuinely re-derived are `compliance_posture`, `governing_stability_verdict`, `closure_deadline_date`, `post_closure_care_end_date`, `ash_in_place_tons`, `ash_mass_balance_ok`, `overdue_posting_types`, `late_posting_count`, `next_sampling_due_date`, `open_ssi_count`; echoed as last written are the identity/state fields, `granted_extension_months`, the four cost figures and `recommended_method`. `derive.plan` is a pure field copy and `approve_plan` does not re-cost (`_recost` runs only in `create_plan` and `cost_certification`). §3.1 was rewritten to split derived from echoed, cross-referencing §2.4.
- **ITEM C follow-on**: the §4 endpoint-table row for `/compliance-summary` still carried the old "every field is re-derived" claim — fixed to match §3.1.
- **ITEM C**: §3.9's withdrawal paragraph attributed the suspension cascade to §2.8 (which describes only the posture gates); repointed to §3.7 and labelled write-time. The 17 `common.settle(...)` call sites were verified against §3.7's enumerated trigger list.
- **ITEM B (latent implementation defect — PRD wording narrowed, implementation deliberately untouched).** `routes_read.py:110-116` (mirrored at `289-295`) uses `common.get_unit(record_id)` purely as a raiser when a stability-assessment (or cap-inspection) id matches no record. When the id resolves to nothing this raises `ERR_UNIT_NOT_FOUND` 404 as pass 1 pinned — but when the id happens to be a valid `DisposalUnit` id the lookup *succeeds* and execution falls through to `derive.stability(None)`, raising `TypeError` and rendering `ERR_INTERNAL` **500** via `app.py:61-65`. Rather than document a crash as a requirement, §2.10's sentence was narrowed to "…matches no record of the family it addresses, and resolves to no `DisposalUnit` either, reports `ERR_UNIT_NOT_FOUND`", which is true of every path the code honours. **Recorded as a real latent implementation defect**: `GET /ccr/stability-assessments/{id}` and `GET /ccr/cap-inspections/{id}` answer 500 instead of 404 when the path id is a valid unit id. The passing 82-test suite never exercises that id collision. Step 9's mandate is PRD-only, so `implementation/` was not modified and the 8/8 clean sweep remains valid.
- **ITEM C, no contradiction found** on: the suspension-cascade mechanism (§2.8/§3.5/§3.7 agree); `closure_timeliness` (§2.4/§2.5/§3.1/§3.6 agree, and it correctly appears in neither §3.1's compliance-summary field list nor the §4 table); posture RESTRICTED-vs-FROZEN (§2.8/§3.5/§3.6/§3.8 agree with `calc.compliance_posture`); licence/discipline gates write-only (§2.9/§2.10/§3.2/§3.5/§3.7 agree; `routes_read.py` never calls the gates); the eight future-date-barred fields being exhaustive (§2.5's list is exactly the eight `common.no_future_date` call sites, and no §3 passage contradicts it).

### Orchestrator verification
`workspace/PRD_COMPLETED.md`: 536 lines (vs 532 for both `PRD.md` and `PRD_FINALIZED.md`), 135,513 chars. Confirmed **not** byte-identical to `PRD_FINALIZED.md` — 104 differing lines. Structure intact: 5 top-level sections, 65 `/ccr` endpoint paths in §4, 55 error rows in §5, and the file ends on a complete `ERR_LICENSE_NOT_ACTIVE | 422` table row (a real section boundary, not a mid-sentence cut). Pipeline complete.
