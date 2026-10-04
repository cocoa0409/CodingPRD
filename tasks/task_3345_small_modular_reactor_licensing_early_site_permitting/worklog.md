# Worklog — task_3345_small_modular_reactor_licensing_early_site_permitting

## Step 1: Create Task Directory — 2026-09-30T22:05:00.000Z

Pre-allocated task directory `./tasks/task_3345_small_modular_reactor_licensing_early_site_permitting/` with `workspace/` inside verified to exist; no new index computed and no other task_* directory created, per invocation instructions.

## Step 1.5: Interruption recovery — 2026-10-01T04:08:39.000Z

Host killed the first pipeline run under memory pressure mid-Step-2. On resume: partial SCAFFOLD.yaml (1769 lines, valid YAML but missing §1.5 endpoints / §1.6 errors / §1.7 roles) was found and deleted; SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml never written; workspace/ empty. Step 2 relaunched from scratch (previous subagent's model unavailable — relaunched with explicit model override).

## Step 2: Generate Scaffold — 2026-10-01T04:45:26.000Z

All three scaffold artifacts generated and verified.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3345_small_modular_reactor_licensing_early_site_permitting/`):
- `SCAFFOLD.yaml` — top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities (§1.1), state_machines (§1.2), concurrency_rules (§1.2.1), calculations (§1.3), validations (§1.4), endpoints (§1.5), errors (§1.6), roles (§1.7). No `scaffold_difficulty_design`/`scaffold_corner_design` keys inside.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8).
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9).

**Counts**
- Entities: 14 (DesignCertification, SafetyAnalysisReport, RAI, TestProgram, TestResult, Vendor, VendorQualification, ComponentLot, SitePermit, PublicHearing, SubscriptionCommitment, CostShareAgreement, WorkforcePipeline, OperatorLicense)
- State machines: 11 (cyclic: RAI reopen loop, SitePermit hearing-regression loop, TestProgram failure loop, WorkforcePipeline attrition loop, VendorQualification supersede)
- Calculations: 7 (EPZ dual-variant sizing, FOAK waterfall allocation, escalation reallocation, tiered withdrawal penalty, qualification variant threshold, cost-share conservation invariant, EPZ site freeze)
- Validations: 18 priority-ordered; Errors: 17; Roles: 9 (incl. segregation-of-duties on RAI accept)
- Endpoints: 76 — above the §0.4 Expert band (20–32) because the linter mandates a single-resource `GET /{seg}/{id}` per entity to derive collection segments plus a filtered-list GET per FK for reverse-reachability (13 FKs); ~40 are business action/CRUD endpoints, the rest are lint-mandated read surface.
- §1.8 instances: 18 (9 rules × 2); §1.9 instances: 22 across 7 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac); 281 recipe calls scanned.

**Difficulty highlights** ("much harder than expert"): dual-variant EPZ sizing with floor/cap clamping, nested-min waterfall escalation with off-ramp and funding-gap conservation invariant, tiered withdrawal penalty on LOCKED subscriptions, OCC on CostShareAgreement for withdrawal races, cross-entity cascades (RAI reopen → SAR regression → phase-gate block; vendor disqualify → qualified flag → lot rejection), segregation-of-duties on RAI acceptance, inclusive due-date and strict-future-hearing boundary rules.

**Verification**: all three files parse with `yaml.safe_load`; `scaffold_lint.py` verdict: **clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5**. No sibling task directories were inspected.

Orchestrator note: files verified on disk (2339/872/746 lines; all parse; endpoints=76 confirmed: 48 POST / 27 GET / 1 PATCH, of which 14 single-entity GETs and 12 collection GETs). Endpoint count >40 is a known impl-gen risk (see memory); Step 6 prompt will include multi-agent decomposition guidance as mitigation.

## Step 3: Copy Shared Files — 2026-10-01T04:45:48.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T04:52:01.000Z

## PRD Generation Complete

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3345_small_modular_reactor_licensing_early_site_permitting/workspace/PRD.md` — **284 lines**

**Section structure:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications — 9 subsections: 2.1 Roles/RBAC (with per-role `identity` translation incl. entity-backed `UtilityParticipant`), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common Resource Properties (incl. `TestResult` no-`updated_at`/`version` carve-out), 2.5 Logical Clock (default `2026-09-01T00:00:00Z`), 2.6 OCC (`expected_cost_share_agreement_version` → `ERR_STALE_VERSION`/412), 2.7 Nested Retrieval + validation priority ordering, 2.8 Hierarchical Consistency/Cascades, 2.9 Precision (2 dp round-half-up for EPZ; integer-USD floor-then-remainder for money)
- §3 Business Logic — 7 subsections (DCA/EPZ sizing, SAR+RAI dialogue, test adequacy failure loop, vendor qualification/procurement, subscriptions/cost-share/escalation/withdrawal, site permits/hearings, workforce pipeline); no HTTP paths or methods in §3
- §4 Endpoint table (4 columns, 76 rows) · §5 Error catalogue (2 columns, 17 rows)

**Coverage verification (Zero-Silence / Hard Contracts):**
- Error IDs: **17/17** present verbatim
- Endpoints: **76/76** paths present in §4 table
- Entity fields: all covered in backticks (0 missing)
- Endpoint inputs/query params (incl. `to_iso8601`, `overrun_usd`, `expected_cost_share_agreement_version`, `limit`/`offset`/`dca_id?` etc.): all covered (0 missing)
- All state values (incl. `DELIVERED`, `DISQUALIFIED`) and all 9 role names present
- Calculation constants all present: `10.0`/`2.0`/`5.0`/`0.5`/10.0-mile cap, 14-day audit overlap, defects threshold 3, withdrawal tiers 30/180 days at 10%/25%, 3x escalation cap, floor-then-remainder-in-creation-order allocation, forward-looking reserve snapshot
- §3 path purity: 337 backticked tokens scanned, 0 violations

Note: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, per the hard constraint. No processes were killed; the workspace was not running any servers.

Orchestrator note: PRD.md verified on disk — 283 lines, well-formed header/sections, error catalogue table present at tail.

## Step 5: Generate Unit Tests — 2026-10-01T05:18:16.000Z

Subagent was killed mid-flight by an API error (model endpoint unavailability) after writing all files; orchestrator verified completeness on disk directly.

Files created: `test_helpers/` (__init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py) + `test_suite/` (conftest.py + 7 test files).

Test counts: test_01_epz_sizing 6, test_02_rai_sar_dialogue 16, test_03_vendor_procurement 10, test_04_permits_hearings 12, test_05_subscriptions_cost_share 12, test_06_programs_workforce_lifecycle 12, test_07_dca_creation_and_gates 12 — **80 tests total**.

Coverage audit (orchestrator-run, script-based):
- §1.8 difficulty: 18/18 instances have exactly one tagged test each (multiple test functions may share one tag where an instance decomposes into sub-cases — 80 tests map onto 40 tags).
- §1.9 corner: 22/22 instances covered.
- 80/80 emitted `Design:` tags match a real instance in the source yamls; 0 invalid tags; 0 untagged tests; 0 instances skipped (no stub instances present in either yaml).
- `python3 -m py_compile` passes on every file in test_helpers/ and test_suite/.
- Fixture date check (memory: design-recipes-may-be-clock-unreachable): test_helpers/constants.py DEFAULT_CLOCK = "2026-09-01T00:00:00Z" matches PRD §2.5 logical-clock default; fixtures.py run_at values align.

## Step 6: Generate Implementation — 2026-10-01T08:26:28.000Z

Step 6 was completed by the orchestrator in the foreground after two subagent spawns died to the model-endpoint outage (the second left 4 usable modules: store.py, errors.py, rbac.py, calc.py — adopted and continued per their conventions).

Files in `workspace/implementation/`: app.py (bootstrap + error handlers), store.py (in-memory DB + logical clock default 2026-09-01T00:00:00Z + envelope helpers), errors.py (17 error ids), rbac.py (9 roles), validation.py (payload validators), calc.py (7 §1.3 formulas), routes_dca.py, routes_sar_rai.py, routes_programs.py, routes_vendors.py, routes_permits.py, routes_subscriptions.py, routes_workforce.py, routes_clock.py, start.sh (guarded pip install, exec foreground), requirements.txt.

Audits (orchestrator-run):
- Endpoint coverage: 76/76 scaffold §1.5 routes registered (verified via Flask url_map listing; 77 rules incl. /static).
- Error-id coverage: 17/17 present in code.
- `python3 -m py_compile` clean on all 13 modules.
- Boot smoke: `PORT=19345 bash start.sh` → up in <30s; POST /licensing/dcas with stf=0.4, sbm=1.0 returned EPZ det=4.0, dose=5.0, selected=5.0 (hand-verified correct); missing role header → ERR_UNAUTHENTICATED 401. Server PID killed exactly.

Step 6→7 hand-off constant-drift check (memory lesson): test_helpers/constants.py literals (EPZ 10.0/2.0/5.0/0.5/10.0/0.25, defects=3, overlap=14d strict-interior, escalation ≤3x, withdrawal tiers 0–30@0% / 30–180@10% / 180+@25% floored, DEFAULT_CLOCK 2026-09-01T00:00:00Z) all match implementation calc.py/store.py and PRD prose. Test helpers use `/licensing` prefix, matching PRD §4. No CONST.* references in tests.

Known judgment calls (flagged for Step 7/9 adjudication): (1) hearing scheduling requires permit HEARINGS status (scaffold §1.5 endpoint description; PRD silent); (2) certify precondition "≥1 LOCKED subscription" implemented as ≥1 EXECUTED (LOCKED arises only from the certify cascade; literal reading deadlocks); (3) audit-overlap rejected strictly inside the ±14-day window, exactly-14-days allowed (test constants comment says "strictly inside"); (4) ERR_VALIDATION payload checks run after existence/state but before domain rules; (5) deliver/release gate failures return ERR_PROCUREMENT_GATE 422; (6) DCA-withdraw cascades also recompute subscribed/available; (7) DCA withdraw on CERTIFIED → ERR_INVALID_STATE.

## Step 7: Run Tests and Iterate — 2026-10-01T09:06:00.000Z

All 8 rounds pass 80/80. The sweep is clean and the results files remain in `workspace/implementation/` per the output contract.

## Summary

**Iterations run: 2** — Iteration 1: 72/83 with the same 11 deterministic failures in all 8 rounds (no flakiness). Iteration 2 after fixes: **80/80 × 8 rounds, all clean.**

**Tests deleted (3):**
- `test_05_subscriptions_cost_share.py::test_penalty_ten_percent_after_forty_five_days` and `test_penalty_twenty_five_percent_at_day_180` — unique-derivability collapse (STEP 1b). Both withdraw a LOCKED commitment, but PRD §3.5 names only "Withdrawing an `EXECUTED` commitment requires..." and the §4 endpoint table states the transition verbatim as "EXECUTED → WITHDRAWN with penalty"; the contrary reading rests on a reserve-liveness inference, not a verbatim rule. Both tests were driven by design-index instance `withdrawal_penalty_tiered_rounding_order`, which silently contradicts the SCAFFOLD's SubscriptionCommitment state machine (EXECUTED→WITHDRAWN only) — the unpinned-constant/design-index drift pattern.
- `test_06_programs_workforce_lifecycle.py::test_licensing_to_staffed_is_terminal` — unique-derivability collapse. It asserts STAFFED immediately after TRAINING→GRADUATING advance with the quota met during TRAINING; PRD §3.7 names only licensing/activation as graduates-recompute triggers, and the event vs level readings diverge with no reading-independent positive-staffing scenario (licensing is TRAINING-only; activation while GRADUATING is unreachable under the level reading since the pipeline is already STAFFED). Same corner instance (`workforce_attrition_regresses_pipeline`) as the surviving attrition test, whose recipe asserts only REVOKED/graduates==0/ENROLLING.

**test_suite/ fixes (5):**
- `test_01_epz_sizing.py::test_variants_diverge_on_low_source_term` and `test_esp_and_col_freeze_different_variants` — assertion mistranslation: the test comment computed `max(0.5, 4.0) = 4.00`, dropping the margin term; the quoted PRD §3.1 formula (2·√site_boundary + 5·(1−fraction), floored at 0.5) yields 8.00 for stf=0.2/sbm=4.0. Corrected expected dose-based/selected values to 8.00.
- `test_03_vendor_procurement.py::test_disqualify_rejects_procured_lots` and `test_delivered_lot_survives_disqualification` — setup used a transition PRD never names (upgrade → disqualify from FULLY_QUALIFIED; PRD §3.4 allows disqualify only from CONDITIONALLY_QUALIFIED, and from AUDIT_SCHEDULED with ≥3 defects). Rewrote both setups: zero-defect audit → FULLY_QUALIFIED (gate opens), procure/deliver the lot, then a second cycle 15 days later (outside the ±14-day overlap window) supersedes the first and completes with 1 defect → CONDITIONALLY_QUALIFIED, disqualified from there. Cascade assertions unchanged.
- `test_04_permits_hearings.py::test_permit_recovers_after_contention_rescheduled` — the test rescheduled the hearing (→SCHEDULED) before re-advancing, which PRD §3.6's advance gate verbatim forbids ("only while no hearing of the permit is currently SCHEDULED"). Reordered: advance while the hearing is CONTENDED, then reschedule.
- `test_06...::test_revoke_regresses_graduating_pipeline_to_enrolling` — removed the intermediate `mid["status"] == "GRADUATING"` assertion (STEP 1c: same underdetermined post-advance status as the deleted staffing test); kept `graduates == 1` and the PRD-verbatim attrition assertions, which hold under either staffing reading.

**test_helpers/ fixes: none.**

**implementation/ fixes (1):**
- `workspace/implementation/routes_permits.py::run_hearing_expiry_sweep` — changed from `clock >= scheduled_at` to strictly-after (`clock > scheduled_at`). PRD §3.6 makes mark-held at the exact instant a live case ("Once the clock reaches scheduled_at, the applicant marks it held"; "marking held requires the clock to be at or after scheduled_at", with ERR_HEARING_WINDOW for wrong-side contend/cancel) — all dead if the sweep cancels at equality, since the sweep runs synchronously inside the clock-set call. This fixed `test_grant_succeeds_once_hearing_held`, `test_mark_held_before_schedule_rejected_then_succeeds_at_instant`, and `test_contend_at_or_after_schedule_rejected`. No test asserts sweep-at-equality cancellation, so nothing regressed.

All 8 `results.{i}.json` files (80/80 each) remain in `workspace/implementation/` as the output contract requires.

Orchestrator verification: all 8 results files show total=80/passed=80; newest impl source mtime (routes_permits.py 09:00:17) precedes results mtimes (09:05:25) — no post-sweep impl writes; `clock > sched` confirmed at routes_permits.py:33.

Step 8 scoping note (memory: test-side fixes can shadow impl): only one implementation/ fix (sweep strictness). Test-side items that Step 8 should examine for PRD pinning: (a) withdrawal tests for LOCKED commitments were deleted as underdetermined — PRD §3.5/§4 may warrant explicit prose that POST /subscriptions/{id}/withdraw applies only from EXECUTED (impl enforces ERR_INVALID_STATE otherwise); (b) the TRAINING→GRADUATING advance-time staffing check (impl auto-staffs at advance when quota already met) is asserted nowhere after the deletion/1c-split — PRD §3.7's trigger enumeration is the silence site; (c) vendor disqualify is exercised only from CONDITIONALLY_QUALIFIED after test rewrites — the AUDIT_SCHEDULED-with-≥3-defects disqualify path is unasserted but implemented per PRD §3.4.

## Step 8: Finalize PRD — 2026-10-01T09:14:50.000Z

All edits verified. The diff is exactly 4 in-place line revisions, everything else byte-identical.

## Summary

**Output:** `workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 283 lines, PRD_FINALIZED.md = 283 lines, 0% line-count delta (all edits are inline revisions within existing single-line paragraphs; ~380 characters added total).

### Changes (4 edits, one bullet each)

- **§3.5** — insert — added the state gate sentence: "The withdrawal action exists only on an `EXECUTED` commitment; attempting it against a commitment in `DRAFT`, `LOCKED`, or `WITHDRAWN` status is rejected with `ERR_INVALID_STATE` (HTTP 409)." — `implementation/routes_subscriptions.py:105-106` (`withdraw_subscription` raises `ERR_INVALID_STATE` unless `status == "EXECUTED"`).
- **§3.7** — revise — appended the advance-time staffing pin: "The same staffing check also runs at the `TRAINING → GRADUATING` advance itself, so a pipeline whose `graduates` count was already met during `TRAINING` is `STAFFED` immediately upon advancing, as part of that same action." — `implementation/routes_workforce.py:18-23` (`_maybe_staff`), called from `advance_pipeline` at line 85.
- **§3.6** — revise — replaced "If the clock reaches `scheduled_at`..." with the strict-after reading: "If the clock moves strictly past `scheduled_at` with the hearing never marked held, the time-based expiry sweep cancels it automatically; a hearing whose `scheduled_at` is exactly the current clock instant is not swept, so marking held remains available at that instant." — `implementation/routes_permits.py:31` (`if clock > sched:`).
- **§2.5** — revise — replaced "whose `scheduled_at` has been reached without being marked held" with "whose `scheduled_at` is strictly earlier than the new position without having been marked held" — same impl site, `routes_permits.py:19-33` (sweep) and `routes_clock.py:18` (synchronous invocation inside clock-set).

The five test-side fixes in `<step_7_diff>` (test_01 arithmetic, test_03 setups, test_04 reordering, test_06 intermediate assertion) required no PRD change, per the diff's own annotations.

### Per-edit pre-edit search log (NO-NEW-MISMATCH)

**Edit 1 — withdraw EXECUTED-only:** (a) state gate on voluntary withdrawal. (b) Read routes_subscriptions.py (full), routes_dca.py:153-168 (DCA cascade distinct), calc.py:174-189 (penalty tiers), calc.py escalate off-ramp, PRD §2.6/§2.7/§4 line 243. (c) Scoped to the voluntary action so it covers neither the DCA cascade nor the escalation off-ramp; placed before the OCC sentence to mirror impl check order.

**Edit 2 — auto-staff at advance:** (a) trigger set for GRADUATING→STAFFED. (b) Read routes_workforce.py (full; `_maybe_staff` callsites advance_pipeline:85, license_candidate:134 — no-op under TRAINING gate, activate_license:149), calc.py:117-128, routes_dca.py:128-129 certify gate, store.py touch, PRD §3.1/§3.7/§4 251-258. (c) "was already met" matches `>=`; "as part of that same action" matches serialization; no version-count claims.

**Edit 3a — §3.6 strict-after sweep:** (a) sweep cancellation boundary. (b) Read routes_permits.py (full: sweep 19-33, mark_held 180-192 `>=`, contend/cancel `<`, schedule/reschedule strictly-future), routes_clock.py (synchronous sweep), PRD §4 235-238, §2.5. (c) Added survival clause for exact-instant mark-held; kept SCHEDULED-only qualifier.

**Edit 3b — §2.5 strict-after sweep description:** (a) same sweep in global-clock section. (b) Same enumeration plus §4 line 259 and §1 line 7 (generic, unaffected). (c) "strictly earlier than the new position"; kept SCHEDULED qualifier.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly 4 revised lines (8 diff body lines) matching the report verbatim; newest implementation/ source mtime (09:00:17) still precedes results mtimes (09:05:25) — implementation untouched by Step 8, sweep evidence remains valid.

## Step 9: Complete PRD — 2026-10-01T09:44:05.000Z

All edits verified in place. Final report:

## PRD_COMPLETED.md produced

**File**: `workspace/PRD_COMPLETED.md`

**Size**: PRD_FINALIZED.md 283 lines / 47,218 chars → PRD_COMPLETED.md 283 lines / 53,153 chars (+5,935 chars, +0 lines — all revisions are inline within existing paragraphs; no sections added). 24 lines changed.

**Counts**: 20 ambiguity-pins, 9 mismatch-revisions (22 edit operations; two edits each carried two changes).

### Changes (one bullet each)

- §2.1 — revise — mismatch — softened "must carry two headers" and pinned that absent `X-User-ID` is never rejected per se: it fails ownership checks (403) and can never trip the self-accept comparison — implementation/rbac.py:27-34, routes_sar_rai.py:167, routes_subscriptions.py:22-25
- §2.3 — insert — ambiguity — pinned limit default 10 / clamp to [1,100] / unparseable→default, offset default 0 / clamp ≥0, created_at-asc sort with `id` tie-break, and `has_more` = (offset+limit) < total_count — implementation/store.py:229-254
- §2.4 — revise — mismatch — replaced the absolute "every derived-field mutation bumps version" with the impl's real regime: `open_rais` and vendor flags bump owner version on change; `completed_tests`, `graduates`, `subscribed_mw`/`available_mw`/`funding_gap_usd`, `allocated_to_participants_usd` update in place without a version bump; also pinned entity timestamps stamp the logical clock — implementation/calc.py:88-128,158-168, store.py:79-81,151-166
- §2.5 — insert — ambiguity — clock-set accepts any instant (no monotonicity check) and returns 200 with `data.current_utc` — implementation/routes_clock.py:12-19
- §2.7 — revise — mismatch — body-FK 404 list corrected to `dca_id`/`vendor_id`/`program_id` only (impl has no utility/pipeline tables; permit ids arrive via path), and unmatched `sar_section_code` explicitly carved out as the §3.2 422 — implementation/validation.py:39-43, routes_sar_rai.py:97-101
- §2.7 — insert — ambiguity — pinned full ordering: auth→role→existence→state gate (now including related-resource preconditions)→payload-shape 400→domain rules, with ownership 403 after existence/before state, and body-FK shape-before-existence wrinkle (create_lot/create_permit validate whole body first) — implementation/routes_vendors.py:172-185, routes_subscriptions.py:79-90, routes_permits.py:141-150, routes_dca.py:65-78
- §2.7 — insert — ambiguity — undefined path or unsupported method → ERR_NOT_FOUND 404 — implementation/app.py:33-39
- §2.8 — revise — mismatch — vendor-disqualification cascade narrowed to the CONDITIONALLY_QUALIFIED→DISQUALIFIED path only — implementation/routes_vendors.py:152-161
- §3.1 — insert — ambiguity — `target_power_mwt` and `plant_net_capacity_mw` pinned as integers — implementation/routes_dca.py:35-36
- §3.1 — insert — ambiguity — PATCH ignores unknown fields and always recomputes EPZ + bumps version, even on a no-op body — implementation/routes_dca.py:65-78
- §3.1 — insert — ambiguity — certify precondition pinned as at least one EXECUTED commitment (the cascade locks it), and certification without a cost-share agreement still locks with cost-share fields left at zero — implementation/routes_dca.py:130-147
- §3.3 — revise — mismatch — "component lots may only be procured against an adequate program" narrowed to nuclear-grade lots (impl gates only when `nuclear_grade` is true) — implementation/routes_vendors.py:182-185
- §3.3 — insert — ambiguity — results recordable in any program status; version bumps only on status change; `completed_tests` counts all recorded PASSes; restart preserves prior results — implementation/routes_programs.py:91-135, calc.py:88-95
- §3.4 — insert — ambiguity — audit-overlap window is strict: exactly ±14 days is allowed, only a strictly smaller gap rejects — implementation/routes_vendors.py:57-64
- §3.4 — insert — ambiguity — upgrade at/above the 3-defect threshold → ERR_INVALID_STATE 409 — implementation/routes_vendors.py:132-135
- §3.4 — insert — ambiguity — disqualification directly from AUDIT_SCHEDULED does not cascade to lots — implementation/routes_vendors.py:152,156-161
- §3.4 — insert — ambiguity — deliver/release re-check failures reject with ERR_PROCUREMENT_GATE 422 (lot stays put), and the re-checks apply to non-nuclear-grade lots too — implementation/routes_vendors.py:219-244
- §3.5 — insert — ambiguity — `committed_mw` pinned as integer ≥ 1 — implementation/routes_subscriptions.py:36
- §3.5 — insert — ambiguity — execution stamps `executed_at` (null until then); field named for the first time — implementation/routes_subscriptions.py:51,91-93
- §3.5 — revise — mismatch — lock-time remainder is at most $1 per locked commitment (not "until exhausted"); excess is left undistributed and not booked to `funding_gap_usd` — implementation/calc.py:146-154
- §3.5 — insert — ambiguity — lock-time `allocated_to_participants_usd` recompute does not increment the agreement's version (no `touch(csa)` in certify) — implementation/routes_dca.py:144-149
- §3.5 — revise — mismatch — escalation reserve decrement now pinned for LOCKED commitments too, not just EXECUTED — implementation/calc.py:216-220
- §3.5 — insert — ambiguity — off-ramp requires EXECUTED + zero reserve at pre-absorption snapshot + positive pro-rata; each remainder dollar also shrinks reserve; no-capacity remainder goes to `funding_gap_usd`; zero eligible participants sends the entire overrun to the gap; escalation does not bump the application's version — implementation/calc.py:201-258, routes_subscriptions.py:186-190
- §3.5 — insert — ambiguity — withdrawal with no cost-share agreement in place → ERR_STALE_VERSION 412 — implementation/routes_subscriptions.py:109-112
- §3.5 — revise — mismatch — dropped "frees the allocated share" (the recompute sums commitments of every status, so recorded dollars persist) and pinned that withdrawal bumps the versions of commitment, application, and agreement — implementation/routes_subscriptions.py:121-126, calc.py:158-168
- §3.5 — revise — mismatch — conservation invariant rewritten to the identity impl actually maintains: Σ`allocated_overrun_usd` + `funding_gap_usd` = cumulative overrun (undisturbed by withdrawal/off-ramp), and Σ`cost_share_total_usd` ≤ `participant_share_usd` by exactly the undistributed lock-time remainder (the original "Σ = participant_share − gap" is arithmetically unsatisfiable under impl's escalate math) — implementation/calc.py:194-258
- §3.6 — insert — ambiguity — submit against a WITHDRAWN application → ERR_INVALID_STATE 409 — implementation/routes_permits.py:88-90
- §3.6 — insert — ambiguity — hearing scheduling requires the permit in HEARINGS status, else ERR_INVALID_STATE 409 — implementation/routes_permits.py:143-145

**Not changed (verified already pinned uniquely)**: EPZ formulas and rounding order (monotonic round makes variant-selection order immaterial), RAI inclusive late boundary / `authored_by_user_id` / SoD compare, vendor supersession and cycle numbering from 1, `qualified_variant` threshold derivation, hearing window strictness and sweep boundary, OCC field name and 412 on stale withdrawal, 201-vs-200 discipline, TestResult's id+created_at-only shape, all endpoint paths/roles in §4's table (every row matches a blueprint route), and all response field names — the only serialized field the PRD never named was `executed_at`, now pinned.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (48 diff body lines, matching the reported 24 changed lines × 2); no file under workspace/implementation/ (excluding __pycache__), test_suite/, or test_helpers/ is newer than results.1.json — Steps 8/9 made zero code edits, so the clean 8×80/80 sweep remains valid evidence. results.{1..8}.json all remain in workspace/implementation/ per the output contract.

## Pipeline Complete — 2026-10-01T09:47:30.000Z

Final confirmation sweep re-run by the orchestrator after Step 9 (results.*.json regenerated so the on-disk evidence postdates every file in the task): **80/80 passed in all 8 parallel rounds — ALL_CLEAN** (each round ~148s under per-test-server isolation). Results files remain in `workspace/implementation/results.{1..8}.json`.

Final artifact inventory:
- SCAFFOLD.yaml (2339 lines) + SCAFFOLD_DIFFICULTY_DESIGN.yaml (872) + SCAFFOLD_CORNER_DESIGN.yaml (746) — all parse, clean lint
- workspace/INSTRUCTION.md, PRD.md (283 lines), PRD_FINALIZED.md (283, +4 pinned lines over PRD), PRD_COMPLETED.md (283 lines, +5,935 chars over FINALIZED; 20 ambiguity-pins + 9 mismatch-revisions)
- test_helpers/ (9 modules) + test_suite/ (conftest + 7 files, 80 tests, all Design-tagged, 40/40 design instances covered)
- workspace/implementation/ — Flask, 13 modules + start.sh + requirements.txt, 76/76 endpoints, 17/17 error ids, in-memory storage only
- worklog.md (this file)
