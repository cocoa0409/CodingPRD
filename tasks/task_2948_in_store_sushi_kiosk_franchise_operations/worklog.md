# Worklog — task_2948_in_store_sushi_kiosk_franchise_operations

## Step 1: Create task directory — 2026-09-05T20:37:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2948_in_store_sushi_kiosk_franchise_operations` and `.../workspace`. Index was pre-assigned (2948) by the invoking pipeline; no scan of ./tasks/ was performed, per instruction (32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T21:57:30.000Z

All three scaffold artifacts are complete and the lint is clean.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2948_in_store_sushi_kiosk_franchise_operations/`)

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3719 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2409 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6161 |

`worklog.md` and `workspace/` untouched; generators left in `.scratch/step2/` (`gen.py` for §1.8, `gen19.py` for §1.9).

## SCAFFOLD.yaml (§1.0–§1.7)
`domain_name: sushi-kiosk-franchise-ops`, `api_prefix: /kiosk-ops`. 15 entities, 13 state machines / 81 transitions, 2 concurrency rules (kiosk-version OCC on plan create, license-version OCC on statement create), 13 calculations, 14 validations, 84 endpoints, 54 errors, 4 roles (FranchisorOps, HostStoreManager, FranchiseChef, QualityAuditor) + a segregation-of-duties block. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears in it.

## §1.8 — 9 rule ids, 22 instances
dual_variant_calc 2 · combinatorial_formula 3 · non_linear_state_machine 2 · transitive_cascade 2 · priority_pair_validation_conflict 2 · boundary_precision_check 3 · cross_entity_state_dependency 3 · resource_temporal_overlap 3 · compensating_invariant 2.

## §1.9 — 9 sections, 74 instances (65 active + 9 `excluded_because` stubs)
entities 12 · state_machines 12 · calculations 8 · validations 6 · endpoints 5 · errors 16 (9 active + 7 stubs) · rbac 6 · cross_cutting_complexity_layers 7 (5 active + 2 stubs) · consistency_model 2. All `claim_type` values come from `claim-extraction-guide.md` rows only.

## Verification
- `scaffold_lint.py` verbatim verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (84 endpoints, 15 entities, 22 §1.8 + 65 §1.9 instances, 1645 calls scanned).
- All three files `yaml.safe_load` cleanly; 96 instance names unique across the union of both design files; all 9 stub `difficulty_instance` refs resolve to real §1.8 instances (qualified as `rule_id / name`) and carry no `test_recipe`.
- Independent placeholder-closure audit: zero unbound `${var}` in any payload, `as_user_id`, path template, or assert across both design files.
- Zero hits for the forbidden concurrency vocabulary and zero hits for the difficulty directive; the recorded `scenario` is the "2948. In-Store Sushi Kiosk Franchise Operations…" paragraph only.

Two SCAFFOLD.yaml self-consistency defects found and fixed while grounding §1.9: the `closure_outcome` enum was widened to `PASS | PASS_AFTER_CORRECTION | ESCALATED` (side effects wrote values the enum did not declare, including a stray `KIOSK_CLOSED`), and the three ProductionPlan `→ VOIDED` triggers now name `POST /kiosk-ops/production-plans/{id}/void` with `actor: FranchisorOps` so that declared endpoint is reachable from §1.2. Also corrected a §1.8 arithmetic slip (traffic forecast 5600 → 5650 so the asserted `planned_pack_count 101` is exact) and a flow-scalar quoting bug in the emitter that broke YAML for `$.data[N].field` captures and for asserts containing embedded double quotes.

**Orchestrator verification:** all three files present; `grep -n "harder than expert\|expert level"` over all three returned zero hits, so the difficulty directive did not leak. `worklog.md` and `workspace/` survived Step 2 intact.

## Step 3: Copy shared files — 2026-09-05T21:58:20.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T22:17:00.000Z

Step 4 complete. `workspace/PRD.md` is finished, verified, and ends at a genuine section boundary.

## Deliverable
`workspace/PRD.md` — **488 lines**, 113,885 bytes.

## Top-level sections, in order
1. `# Sushi Kiosk Franchise Ops API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC / 2.2 API Response Structure (verbatim skill block) / 2.3 Pagination / 2.4 Resource Identity, Timestamps and Record Versioning / 2.5 The Logical Clock and Its Two Sweeps / 2.6 The Order in Which a Request Is Rejected / 2.7 Optimistic Concurrency on Parent Records / 2.8 Money, Mass and Rounding / 2.9 Binding Numbers and Advisory Numbers / 2.10 Cascade Discipline / 2.11 Nested Paths and Filtered Reads
4. `## 3. Business Logic & Workflows` — 9 subsections: 3.1 Host store + licensing, 3.2 Chef training/certification/placement, 3.3 Kiosk commissioning and its two postures, 3.4 Production planning, 3.5 Rice acidification + HACCP variance, 3.6 Fish sourcing, parasite destruction, cold chain, 3.7 Pack lots, markdown, discard, 3.8 Register feeds + revenue-share settlement, 3.9 Audits, corrective action, escalation
5. `## 4. API Endpoints`
6. `## 5. Error Codes`

## Coverage (mechanically verified against SCAFFOLD.yaml)
| Item | Scaffold | Documented |
|---|---|---|
| Entities | 15 | 15 (each has a home §3 subsection) |
| Endpoints | 84 | 84 table rows, exactly 4 columns |
| State machines | 13 (incl. both Kiosk dimensions) | 13; all 81 transitions and every state name present |
| Calculations | 13 | 13, all formulas reconstructible in prose |
| Validations | 14 (12 priorities + 2 priority pairs) | 14, as the §2.6 ladder plus both pairs stated outright |
| Errors | 54 | 54 table rows (2 columns) **and** all 54 raised in §2/§3 prose |
| Roles | 4 | 4, with identity binding + SoD |
| Concurrency rules | 2 | 2 (`expected_kiosk_version`, `expected_license_agreement_version`) |

## Hard Contracts (reported here only, never written into PRD.md)
- **Contract 1 — Field-Name Coverage: PASS.** All 183 required names appear verbatim in backticks. Two gaps found on the first scan (`certification_id`, `finding_id`) and fixed by extending §2.11 with the second-segment path-parameter rule.
- **Contract 2 — Rule Coverage: PASS.** All transitions, side effects, cascades, defaults, `applies_to` scopes, both dual-variant calculations, both OCC rules, all enum values (0 missing), and every numeric constant are documented. Sibling-branch symmetry stated explicitly for `RECEIVED`/`RELEASED` quarantine, `ON_SHELF`/`MARKED_DOWN` discard, and the four `→ VOID` settlement edges.
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 begin with `/` or are/start with an HTTP method; §3 contains 0 occurrences of `/kiosk-ops`, `POST`, or `GET`.

## Scaffold self-contradictions resolved (implementer-visible decisions)
- `parasite_destruction_required`: followed the calculation (`AQUACULTURE_EXEMPT` OR species in {`TUNA_YELLOWFIN`, `SHRIMP_COOKED`}), not the entity blurb.
- `round_count` starts at **0** (endpoint side-effect), not 1 — with `MAX_CORRECTIVE_ROUNDS` 2 a start of 1 makes the `REVERIFICATION → CORRECTIVE_ACTION_PENDING` cycle edge unreachable.
- Kiosk suspend does **not** touch `sanitation_posture` (state machine wins over the endpoint blurb); only audit `ESCALATED_CLOSURE` forces `LOCKDOWN`.
- `freeze_effective_hours`: whole hours, fraction discarded.
- `lifetime_share_accrued_cents` accrues `binding_share_cents`.
- License termination blocked by live statements now names `ERR_LICENSE_INVALID_STATE` (scaffold declared no error for that precondition).
- Also corrected one authoring slip found in verification: a non-existent posture value `HEIGHTENED` in §3.7 replaced with `CLEAR`/`WATCH`/`RESTRICTED`.

## No-truncation evidence
Last two lines, verbatim:
```
| ERR_INSUFFICIENT_FISH_INVENTORY | 422 |
| ERR_SPACE_OBLIGATION_DEFICIENT | 422 |
```

**Orchestrator verification:** independently confirmed 488 lines; `grep "^## "` returns exactly the 5 expected top-level sections (1 Introduction, 2 Global Specifications, 3 Business Logic, 4 API Endpoints, 5 Error Codes); `tail -25` shows the file ending on a complete two-column error-table row with trailing newline, i.e. a genuine section boundary, NOT mid-sentence. No truncation. Difficulty-directive leak check on PRD.md: 0 hits.

## Step 6: Generate implementation — 2026-09-05T23:20:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, so the impl generator could not see `test_suite/`. Step 6 returned first; the Step 5 entry follows below out of numeric order.)

The implementation is complete, verified, and the smoke server is shut down.

## Deliverables — `workspace/implementation/`

| file | lines |
|---|---|
| `start.sh` | 11 |
| `requirements.txt` | 1 |
| `app.py` | 62 |
| `core.py` | 177 |
| `db.py` | 88 |
| `errors.py` | 143 |
| `middleware.py` | 263 |
| `response.py` | 55 |
| `routes/__init__.py` | 0 |
| `routes/base.py` | 105 |
| `routes/clock.py` | 20 |
| `routes/stores.py` | 266 |
| `routes/chefs.py` | 142 |
| `routes/kiosks.py` | 189 |
| `routes/plans.py` | 196 |
| `routes/rice.py` | 225 |
| `routes/fish.py` | 221 |
| `routes/packs.py` | 213 |
| `routes/settlement.py` | 411 |
| `routes/audits.py` | 300 |
| `services/__init__.py` | 0 |
| `services/calc.py` | 330 |
| `services/domain.py` | 822 |
| **total** | **4240** |

Nothing outside `workspace/implementation/` was created or modified except scratch dir `.scratch/step6/`. `__pycache__` removed. `compileall` clean.

## Endpoint count
`TOTAL 84`, counted in-process from `app.url_map` — matches PRD §4's 84 rows. All under the `/kiosk-ops` prefix, including the unauthenticated `POST /kiosk-ops/_clock/set_current_utc`.

## Module → PRD map
`routes/clock.py`→§2.5 (two sweeps, in order); `stores.py`→§3.1 (12); `chefs.py`→§3.2 (8); `kiosks.py`→§3.3 (8); `plans.py`→§3.4 (7); `rice.py`→§3.5 (8); `fish.py`→§3.6 (8); `packs.py`→§3.7 (7); `settlement.py`→§3.8 (14); `audits.py`→§3.9 (11). `middleware.py`→§2.1 RBAC, §2.3 pagination, ladder rungs 1–5; `response.py`→§2.2 envelope; `errors.py`→§5 (all 54 ids, byte-exact); `services/calc.py`→§2.8 rounding + §2.9 binding/advisory + the 13 named calculations; `services/domain.py`→§2.10 cascades, derived aggregates, risk/posture re-derivation.

## Fixes made during generation
1. **`GET /kiosks/{id}/risk-summary` leaked an undeclared field.** It returned `domain.risk_breakdown()` verbatim, including the internal `unresolved_critical_count`. Now popped, and the same value drives both `posture_forced_by_critical` and `calc.posture_band(...)`, so the computed read agrees with the stored `sanitation_posture`. Response is now exactly the 11 declared fields.
2. **`meta.api_request_timestamp` was the host wall clock.** PRD §2.5 is absolute — "Nothing in this system reads the host machine's wall clock". Switched to `logical_now_iso()`. `grep` confirms zero `datetime.now` / `utcnow` / `time.time` reads remain anywhere in the implementation.

## Smoke-test evidence
Fresh boot, `PORT=21903 bash start.sh`: Flask serving on 0.0.0.0:21903.

**No seeded data** — all 11 collections empty on a fresh process (`total_count=0`, `rows=0` each).

Envelope + error shape confirmed: unauthenticated POST → 401 `ERR_UNAUTHENTICATED`; authenticated POST → 201 with `version:1`, `pos_integration_status:NOT_CONNECTED`, `space_compliance_state:UNVERIFIED`; list → `response_type:array` with `has_more/limit/offset/total_count` meta and logical-clock timestamp. Also: `GET /host-stores/nope`→404 `ERR_HOST_STORE_NOT_FOUND`; `?limit=101`→400 `ERR_INVALID_REQUEST`; `?offset=50` past end→empty array; stale OCC→412 `ERR_STALE_LICENSE_VERSION`; activate without CONNECTED POS→422 `ERR_POS_NOT_CONNECTED`.

**Two driver runs against a fresh build, both `FAILURES: 0`:** a 60+ call end-to-end chain through licensing → chef → kiosk → plan → rice → fish → packs → feed → settlement → audit, and a CRITICAL-finding posture probe. Both smoke servers killed by exact PID; ports 21847/21903 confirmed free. No `pkill` was ever run.

## Key ambiguities resolved (PRD wins over SCAFFOLD)
- `lifetime_share_accrued_cents` = sum of `binding_share_cents` over ISSUED/ACKNOWLEDGED/PAID, recomputed from scratch on every settlement mutation.
- `open_critical_finding_count` counts CRITICAL findings that are OPEN or CORRECTED (§3.9 decrements only at PASS). Risk points come only from submitted audits; the critical count comes from all audits.
- Audit `score = max(0, 100 − 2×MINOR − 8×MAJOR − 20×CRITICAL)` over all findings regardless of status.
- Kiosk `suspend` does not touch `sanitation_posture`; only audit `ESCALATED_CLOSURE` forces LOCKDOWN.
- `parasite_destruction_required` false for `AQUACULTURE_EXEMPT` or species in {TUNA_YELLOWFIN, SHRIMP_COOKED}; `freeze_effective_hours` = whole hours floored.
- `DiscardEvent.unit_value_cents` = `markdown_price_cents` when the lot was MARKED_DOWN, else `list_price_cents`.
- Ownership-vs-existence: direct body-FK string comparison → 403 before 404; indirect targets resolve first (404) then 403.
- Time-ordered UUIDs so the `created_at`/`id` tie-break equals creation order under a frozen logical clock.
- Unnamed-error fallbacks: duplicate `kiosk_code` in an agreement, `markdown_sales_cents > gross_sales_cents`, unknown route/method → `ERR_INVALID_REQUEST`; blocked transitions → matching `ERR_*_INVALID_STATE`; feed line over `unsold_count` → `ERR_PACK_CAP_EXCEEDED`; feed line naming an unknown lot → `ERR_PRODUCTION_RECORD_NOT_FOUND`.

## Step 5: Generate unit tests — 2026-09-06T00:55:00.000Z

(Launched concurrently with Step 6; returned second. See the Step 6 note above.)

Step 5 is complete. Test infrastructure and the full test suite are generated at the task root.

## Files written

`test_helpers/` — 2,884 lines
`__init__.py` 44 · `api_client.py` 432 · `api_errors.py` 128 · `assertions.py` 477 · `constants.py` 269 · `factories.py` 454 · `fixtures.py` 669 · `test_users.py` 95 · `types.py` 316

`test_suite/` — 6,024 lines, **118 test functions**
`conftest.py` 45 · `test_01_registry_defaults_and_shapes` 460/13 · `test_02_lifecycle_transitions` 510/12 · `test_03_derived_money_and_risk_arithmetic` 301/8 · `test_04_gate_ordering_and_capacity_limits` 272/6 · `test_05_endpoint_behaviours` 278/5 · `test_06_error_catalogue` 607/9 · `test_07_role_access_control` 388/6 · `test_08_concurrency_and_counters` 476/7 · `test_09_dual_variant_divergence` 189/5 · `test_10_combinatorial_formulas` 302/7 · `test_11_parallel_state_dimensions` 300/5 · `test_12_transitive_cascades` 298/5 · `test_13_rejection_priority_pairs` 256/5 · `test_14_inclusive_limit_boundaries` 319/7 · `test_15_parent_state_gates` 246/6 · `test_16_shared_resource_windows` 446/6 · `test_17_compensating_reversals` 331/6

## Design-index coverage

- **§1.8 difficulty: 22/22 instances translated, 0 skipped.** All 9 rules, one file each (09–17), every instance carrying ≥2 tests.
- **§1.9 corner: 65/65 non-stub instances translated, 0 skipped.** The only 9 uncovered instances are exactly the declared stubs (`errors/error_rice_batch_not_approved_on_pack_lot_create`, `error_case_capacity_exceeded_across_kiosks`, `error_no_settleable_sales_on_issue`, `error_kiosk_posture_lockdown_on_plan_create`, `error_acidification_window_overlap_on_rice_create`, `error_settlement_period_overlap_on_create`, `error_settlement_invalid_state_on_issue_of_void_statement`, `cross_cutting_complexity_layers/audit_escalation_cascade_ordering`, `cross_cutting_complexity_layers/settlement_dual_variant_delta`).

## Verification performed

- Every test has exactly **one** trailing `Design:` line; all 87 distinct tags resolve to real instance names in the two design yamls (machine-checked against the parsed yaml).
- **157/157** quoted docstring fragments are verbatim substrings of `workspace/PRD.md`. Five paraphrases found in the audit were rewritten to the exact PRD wording (`test_01`: `planned_rice_kg`, `consumed_fish_kg`/`shelf_expiry_at`, settlement-statement defaults, chef placement; `test_08`: `posture_factor_applied`).
- `import test_helpers` succeeds and every symbol imported by all 17 suite files exists in the barrel (0 missing); all 26 files `ast.parse` clean; no unused imports.
- No `pytest.mark.skip/skipif/xfail` anywhere; no scaffold or design-index references in generated code.

## Location proof

`test_helpers/` and `test_suite/` exist at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — `workspace/test_helpers` and `workspace/test_suite` do not exist. `workspace/implementation/` was never read or touched, `worklog.md` was never touched, all scratch stayed in `.scratch/step5/` (now removed; siblings step2/step4/step6/step7 intact), no `pkill` was run.

Two notes for Step 7: `test_16` and `test_17` rely on `attested_case_linear_ft` 20.0 → store-wide 180-pack case aggregate, and on the sibling-kiosk plan at `traffic_forecast` 5612 → `planned_pack_count` 101, which is what isolates `ERR_CASE_CAPACITY_EXCEEDED` from `ERR_PACK_CAP_EXCEEDED`.

**Orchestrator verification:** independently confirmed `test_helpers/` (9 files) and `test_suite/` (18 files) are at the TASK ROOT; `workspace/test_helpers` and `workspace/test_suite` both confirmed absent; 118 `def test_` functions counted; `.scratch/{step2,step4,step6,step7}` all still present and `.scratch/step7/sweep.sh` intact.

## Step 7: Run tests and iterate — 2026-09-06T00:40:00.000Z

Fully green. All 8 rounds report 118/118.

**Summary**

**Iterations run:** 3 full 8-round sweeps (iteration 1: 2/118 per round; iteration 2: 115/118 per round; iteration 3: 118/118 in every round).

**Tests deleted:** none. Every failure traced either to a test-artifact bug or to an implementation defect against a verbatim PRD sentence; no test asserted a scaffold-only rule, and no assertion was weakened, skipped or downgraded.

**Fixes to `test_helpers/`:**
- `assertions.py::assert_rice_batch` — `exposure_minutes` is only computed when the time/temperature control record is verified, so the shape assertion now tolerates null on a `MIXING`/`ACIDIFYING` batch instead of demanding an int.
- `fixtures.py::discard_pack_lot_as_auditor` — the discard call answers with the updated pack lot (PRD §4: state-transition endpoints return the updated parent), so the fixture now reads the appended event back from `GET /pack-lots/{id}/discard-events`.

**Fixes to `test_suite/`:**
- `test_02_lifecycle_transitions.py`, `test_03_derived_money_and_risk_arithmetic.py`, `test_07_role_access_control.py` — three sites bound the discard response directly to an event variable and then read `unit_value_cents` / `discarded_count` off it. Corrected to consume the transition response and source the event from the nested discard-event list (`expected_total=1`), with both money assertions kept intact. `test_16` already asserted lot fields off that same response, so the lot-returning reading is the majority one.
- `test_17_compensating_reversals.py::test_two_draws_and_one_reversal_keep_the_lot_ledger_balanced` — the fixture drew two pack lots from one rice batch, which PRD §3.5 forbids ("a batch is spent by exactly one pack lot"). The second draw now comes off its own approved batch in a non-overlapping hold window.

**Fixes to `implementation/`:**
- `routes/chefs.py::place_chef` — accepted only `kiosk_id`; PRD names the placement field `assigned_kiosk_id` (this was the iteration-1 wipeout, 116 tests).
- `routes/chefs.py::log_training` — hard-set the chef to `TRAINEE`; PRD §3.2 makes `status` a function of hours plus the two mandatory certifications ("exactly 24 hours is enough"), so it now re-applies the readiness rule.
- `services/domain.py::recompute_cold_chain` — the lot's `received_at`/`receiving_temp_c` origin point was excluded from breach attribution, contradicting §3.6 ("the lot's own `received_at` with `receiving_temp_c` is the origin of the series"); the origin interval is now attributed while the first reading's `interval_minutes_from_previous` stays null.
- `services/domain.py::void_pack_lot` — zeroed `unsold_count`, breaking §3.7's "without exception" conservation invariant.
- `routes/fish.py::list_readings` — sorted by `recorded_at`; §2.11 declares the reading list ordered by `created_at` ascending.
- `routes/fish.py::release_lot` / `destroy_lot` — clearing a `COLD_CHAIN_BREACH` quarantine changes a §3.3 risk input, so the kiosk posture is now re-derived.
- `routes/settlement.py::submit_feed` — no POS gate; §2.2: "A store whose integration is anything other than `CONNECTED` cannot have a sales feed accepted — the attempt is refused with `ERR_POS_NOT_CONNECTED`."
- `routes/stores.py` suspend/terminate agreement + `services/domain.py` `suspend_kiosk`/`decommission_kiosk` (new `refresh_agreement` flag) — the cascaded kiosks each re-derived `active_kiosk_count` on the agreement, so one licence suspension bumped the agreement's `version` twice; §3.1 gives exactly one increment per request. Direct kiosk suspension/decommission still bumps the agreement as §2.10 requires.

**Final per-round results** (`workspace/implementation/results.{1..8}.json`, left in place): rounds 1–8 all `118 / 118`, 0 failed, 0 errors, 0 skipped.

**Orchestrator verification:** independently parsed all eight `results.$i.json` — every round reports `passed=118, total=118`. The sweep ran under the pre-written `.scratch/step7/sweep.sh` (setsid + `SWEEP_DONE` sentinel), so no round was reaped mid-request; iteration 1's uniform 2/118 across all 8 rounds was a genuine single-cluster fixture/impl mismatch (`ERR_INVALID_REQUEST - kiosk_id is required`), not load-induced flakiness. Step 7 made 8 `implementation/` fix groups, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-06T00:47:00.000Z

Done. `PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 488 lines; `PRD_FINALIZED.md`: 488 lines (0.0% line delta — all 10 edits are inline within existing paragraphs/table rows; 9 lines changed). File still ends at the §5 error-code table boundary.

## Changes (one bullet each)

- **§3.1 (suspend)** — insert — pinned that a licence suspension writes the agreement **exactly once**: cascaded kiosk suspensions do not each re-derive `active_kiosk_count`, so `version` moves by exactly 1 — `routes/stores.py:224-231`, `services/domain.py:758-779`.
- **§3.1 (terminate)** — revise — same single-increment pin for termination's cascaded decommissions — `routes/stores.py:265-273`, `services/domain.py:782-798`.
- **§3.2 (training)** — revise — each training entry re-applies the certification-readiness rule, so an entry that carries a chef holding both mandatory certs over 24 h promotes straight to `CERTIFIED` — `routes/chefs.py:62-78`, `services/domain.py:205-247`.
- **§3.2 (readiness triggers)** — revise — readiness re-evaluated "after every issuance, **after every training entry** and after every clock movement" — `routes/chefs.py:77`.
- **§3.2 (placement)** — insert — placement body names the kiosk in `assigned_kiosk_id` (`kiosk_id` accepted as an equivalent spelling) — `routes/chefs.py:139-144`.
- **§3.3 (posture triggers)** — revise — added "released or destroyed out of that quarantine" to the risk-input event list — `routes/fish.py:212-214,232-234`.
- **§3.6 (cold chain)** — revise — replaced "`breach_minutes_attributed` … is 0 for the first reading" with the origin-interval attribution: the earliest reading carries the `received_at`/`receiving_temp_c` → reading interval, while its `interval_minutes_from_previous` stays null — `services/domain.py:477-511`.
- **§3.6 (release)** — insert — release recomputes the kiosk risk total and re-derives `sanitation_posture` — `routes/fish.py:205-214`.
- **§3.6 (destroy)** — insert — destroy likewise re-derives the posture — `routes/fish.py:227-234`.
- **§3.8 (feed submit)** — insert — submission gated on `pos_integration_status == CONNECTED` with `ERR_POS_NOT_CONNECTED`, evaluated **before** the duplicate-feed check — `routes/settlement.py:74-84`.
- **§4 (table row)** — revise — reading-list ordering restated as §2.3 `created_at` ascending (the table row previously said `recorded_at` ascending, which the impl does not sort by) — `routes/fish.py:174-184`, `db.py:86-88`.

## Per-edit pre-edit search log

1. **Agreement version (suspend/terminate).** (a) Subject: agreement `version`/`active_kiosk_count` writes per request. (b) Grepped all `refresh_active_kiosk_count(` callers → `routes/kiosks.py:132,172` (commission/reinstate, direct), `domain.py:777,797` (suspend_kiosk/decommission_kiosk, flag-gated); read `db.touch`/`db.apply_changes`; read `stores.py` activate/reinstate. (c) Deliberately scoped the claim to the licence-driven suspend/terminate paths only rather than a global "one increment per request" — `activate_agreement` calls `apply_space_derivation` after `db.touch`, which can bump the agreement a second time, and direct kiosk suspend/decommission legitimately bumps the agreement.
2. **Training readiness.** (a) Subject: chef `status` recomputation. (b) All `refresh_chef(` callers: `chefs.py:77` (training), `:102` (issue), `:130` (revoke), `domain.py:838` (clock sweep); read `refresh_chef` (SUSPENDED sticky; CERTIFIED→SUSPENDED on loss). (c) Phrased as "re-applies the certification-readiness rule below" plus an exception clause so existing CANDIDATE/TRAINEE sentences stay true.
3. **Placement field.** (a) Subject: placement request-body kiosk reference. (b) Grepped every `assigned_kiosk_id` write/read: `chefs.py:28,49,150`, `domain.py:253,791-792`. (c) Added the "`kiosk_id` accepted as an equivalent spelling" clause because `chefs.py:142` accepts both.
4. **Posture triggers list (§3.3).** (a) Subject: posture re-derivation triggers. (b) All 13 `rederive_kiosk(` callsites enumerated. (c) Worded as an addition to an illustrative list so a no-op re-derivation is not mis-described.
5. **Cold-chain origin attribution.** (a) Subject: `breach_minutes_attributed` / `interval_minutes_from_previous` on the earliest reading. (b) Read `domain.recompute_cold_chain`, `calc.interval_breach_minutes`, `fish.append_reading`, §2.11's reading-list sentence. (c) Softened to "0 only when the three-way rule itself attributes nothing to the origin interval" and reconciled the preceding "null for the very first appended reading" sentence.
6. **Fish release / destroy posture.** (a) Subject: posture side effect of clearing a quarantine. (b) `fish.release_lot`, `fish.destroy_lot`, `fish.append_reading`, `domain.rederive_kiosk`, `domain.risk_breakdown`. (c) Wrote the re-derivation unconditionally (matching impl) but avoided claiming destroy clears `quarantine_reason`.
7. **Feed-submission POS gate.** (a) Subject: `ERR_POS_NOT_CONNECTED` on feed submit and its rung order. (b) All four raise sites: `settlement.py:79`, `:132`, `stores.py:189`, `kiosks.py:111`. (c) Cross-reference written as §3.1; ordering claim limited to "before the duplicate-feed check that follows".
8. **Reading-list ordering (§4 row).** (a) Subject: sort order of `GET /fish-lots/{id}/cold-chain-readings`. (b) `fish.list_readings` → `base.paginate` → `db.ordered` (`created_at`, then `id`). (c) Kept §2.11's sentence verbatim and made the table row defer to it.

**Non-silences left unpatched (justified):** `void_pack_lot` not zeroing `unsold_count` is already forced by §3.7's "without exception" conservation invariant plus void's `sold_count == 0` precondition; `list_readings` ordering was already pinned in §2.11 (only the §4 row needed aligning); the feed POS gate rule text already existed verbatim in §3.1 (only its locality/order was silent). The `test_helpers` and `test_suite` items are pure test-artifact bugs against behavior §3.5/§3.7/§4 already determine, so they produced no PRD edits.

**Orchestrator verification:** `PRD_FINALIZED.md` is NOT byte-identical to `PRD.md` — `diff` reports 22 changed lines (11 `<` / 11 `>`), both files 488 lines, 5 top-level sections preserved, and the file still ends on a complete §5 error-table row.

## Step 9: Complete PRD — 2026-09-06T01:40:00.000Z

**Orchestrator decision (recorded per the autonomy directive):** Step 9 was run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`, rather than a single subagent. A single pass over 4,240 lines of implementation plus a 488-line PRD reliably under-scans and, in the worst case, returns a byte-identical file. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying (that would have destroyed the earlier passes' edits) and were told the running line/char counts so a shrink would be detectable. Partition by impl module: pass 1 = platform layer + §3.1–§3.3; pass 2 = §3.4–§3.7 + `services/calc.py`; pass 3 = §3.8–§3.9 + the settlement/audit half of `services/domain.py`.

### Pass 1 of 3 — platform + licensing/chefs/kiosks

- `PRD_FINALIZED.md` 488 lines / 115,935 chars → `PRD_COMPLETED.md` 490 lines / 131,822 chars (+2 lines, +15,887 chars), 28 diff hunks.
- **25 ambiguity-pins, 5 mismatch-revisions** (§2.4 no-op version rule, §3.1 activation double version bump, §3.2 SUSPENDED stickiness, §3.3 + §4 provisioning needs no ACTIVE agreement, §4 nested-child transition return shape).
- Notable pins: whitespace-only header counts as empty for `ERR_UNAUTHENTICATED` (middleware.py:56); unresolvable `X-User-ID` → `ERR_OWNERSHIP_MISMATCH` not 404 (middleware.py:85-98); `api_request_timestamp` served from the logical clock (response.py:8-15); non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`, unknown params ignored (middleware.py:244-251); `id`s minted so lexicographic order equals creation order (core.py:59-71); a write that moves no value is not a mutation (db.py:68-78); clock-sweep discard events carry null `recorded_by_user_id` (domain.py:813-822); §2.6 rung 3 ownership pre-empts existence only where the path id *is* the owning entity's id; body FK missing/blank/wrong-typed falls to the 400 rung (base.py:96-105); space derivation runs over every ACTIVE agreement, vacuously COMPLIANT with none (domain.py:391-416); cascaded kiosks record fixed `LICENSE_SUSPENDED`/`LICENSE_TERMINATED` reasons; `termination_reason` stored in the `suspension_reason` slot; commission's optional body `lead_chef_id` override and the five reinstatement refusals in order (kiosks.py:100-165); risk points come only from submitted audits while `open_critical_finding_count` counts OPEN/CORRECTED criticals across all audits (domain.py:143-150, 312-323); risk-summary is a pure eleven-key read (kiosks.py:82-92); undeclared path/method and server faults answer in the same envelope with `ERR_INVALID_REQUEST` at 404/405/500 (app.py:36-51).
- Found already fully pinned: `errors.py` (whole catalogue matches §5 row-for-row incl. HTTP statuses), `routes/base.py` existence-code mapping, §2.7 OCC / §2.8 rounding / §2.10 cascade prose, and `calc.py`'s shared constants (`PACKS_PER_LINEAR_FT` 9, risk 1/4/10, clamp 0–40, posture bands 8/18/30).

### Pass 2 of 3 — production planning, rice/HACCP, fish/cold chain, packs, `calc.py`

- 490 lines / 131,822 chars → 490 lines / 137,569 chars (+5,747 chars; all edits in-paragraph). 5 `## ` + 20 `### ` sections verified intact.
- **18 ambiguity-pins, 1 mismatch-revision.**
- The mismatch: §3.5 variance filing gates on the chef's derived `haccp_cert_expires_at` being strictly after the logical clock, **not** merely holding a `VALID` cert — a `VALID`-but-past-expiry cert does not qualify (rice.py:160,166-168).
- Notable pins: `traffic_forecast` must be a JSON integer (plans.py:44); plan create consults neither kiosk `operational_state` nor agreement `status`, only term dates (plans.py:47-56); chef ownership decided from body `kiosk_id` before the existence rung → 403 not 404 (plans.py:37-40); the three candidate ceilings are not persisted; multiple prior drafts all voided with `superseded_plan_id` = last in `created_at`/`id` order (plans.py:59-64); release/lock error ids (`ERR_PLAN_INVALID_STATE` vs `ERR_KIOSK_INVALID_STATE`); `exposure_minutes` discards the fractional minute and is recorded on the `REJECTED` branch too (rice.py:145-148); `remaining_kg` starts at full `net_weight_kg` (fish.py:69); parasite record filable from `RECEIVED`/`QUARANTINED`, re-filable, does not move `status`, attester needs no certification (fish.py:116-122); readings appendable in every state but `DESTROYED`, each append replaying the whole series from the origin (fish.py:145-156, domain.py:477-517); pack build ownership comes from the *rice batch's* kiosk (packs.py:43-48) and never examines `operational_state`, only posture; "live" = `ON_SHELF`/`MARKED_DOWN` only, with sold-out/discarded/voided lots releasing headroom (domain.py:167-198); discard `reason` is an enum of exactly four values.
- Found already fully pinned: **`services/calc.py` in full** — `daily_production_allocation` (0.018 attach, 9/linear ft, 200/chef, floor semantics, DEMAND→CASE_CAPACITY→STAFFING tie-break, 0.12 kg/pack at 2 dp), `rice_acidification_disposition` (4.20/4.60, 240/300, 21.0, single-failure rule), `rice_yield_ceiling`, `interval_breach_minutes` (three-way rule, 4.4 °C, round-before-sum), `parasite_destruction_required`/`_compliant` (−35/15 h, −35/24 h, −20/168 h, inclusive), `pack_markdown_price` (30 % floor, prorated over 720, 50 % flat, floor-raise, binding/advisory), `discard_valuation`, `forecast_variance_pct`, `space_shortfall`; plus plan reconcile/void cascades, rice start/acidify/variance/revoke gating, fish release/destroy/quarantine, pack gate order and void conservation, and every §4 role list for those endpoints.

### Pass 3 of 3 — settlement, audits, settlement/audit half of `domain.py`

- 490 lines / 137,569 chars → **492 lines / 146,656 chars** (+2 lines, +9,087 chars).
- **17 ambiguity-pins, 4 mismatch-revisions.**
- The four mismatches: superseded draft's `void_reason` is the literal `SUPERSEDED` (settlement.py:244); `variance_cents` is non-negative/non-positive by model and exactly zero when no markdown was rung, not "positive"/"negative" (calc.py:253-259); the space credit reads the **agreement's** `space_shortfall_sqft`, not the store's (domain.py:663); `period_discard_value_cents` covers only the **agreement's own** discard events matched on the event's `created_at` date — sales are store-scoped while discards are agreement-scoped (domain.py:619-634). Also revised: `lifetime_share_accrued_cents` is recomputed wholesale over ISSUED/ACKNOWLEDGED/PAID after every statement write, not incremented (domain.py:717-727).
- Notable pins: `markdown_sales_cents > gross_sales_cents` → `ERR_INVALID_REQUEST` at the schema rung, ahead of the POS gate (settlement.py:71); `full_price_units`/`markdown_units`/`was_markdown` are disclosure-only and never feed a settlement figure; body `host_store_id` compared to `X-User-ID` before the store lookup → 403 not 404/400 (settlement.py:61); unresolvable `pack_lot_id` → `ERR_PRODUCTION_RECORD_NOT_FOUND`; unit cap is `ERR_PACK_CAP_EXCEEDED` tested per lot on units summed across lines; resolution pass strictly precedes the cap pass and reconciliation is all-or-nothing (settlement.py:134-153); zero-unit lines count toward `reconciled_unit_total` but leave the lot's `version` untouched; `period_end` strictly after `period_start`; the six derivation steps run at draft time so an empty period yields a valid all-zero draft; the post-draft fourth-link cascade touches only `DRAFT` statements of the lot's own agreement and rewrites steps 5–6 against the *stored* figures (domain.py:684-714); `ERR_NO_SETTLEABLE_SALES` beats `ERR_SEGREGATION_OF_DUTIES` on issue (settlement.py:310-319); audit scheduling is unconstrained (any kiosk state, past dates, concurrent audits); `verification_note` required but never persisted; non-terminal `FAIL` leaves `verified_by_user_id` null; escalation decrements `active_kiosk_count` and on a non-`OPERATING` kiosk only forces `LOCKDOWN` without suspending (audits.py:282-299).
- One cross-partition clause was added in §2.6 rung 6 (otherwise pass 1's territory) because the impl's `ESCALATED_CLOSURE` check precedes the state check (audits.py:235-238), contradicting the pre-existing blanket claim that a terminal-state target is always a state error. The clause only points at §3.9's stated exception; nothing pass 1 pinned was removed.
- Found already fully pinned: settlement feed state machine and terminality, duplicate-feed ordering, POS gate on both submit and reconcile, tier-ladder constants and rounding order, both credit caps, `net_due` floor, draft OCC, closed-interval period overlap, statement state machine, `revision_round` bound of 3 with `ERR_CORRECTIVE_ROUNDS_EXHAUSTED`, exact-payment rule; audit start-due check, `IN_PROGRESS`-only finding entry, 1/4/10 risk points vs 2/8/20 score weights, both submit branches incl. forced lockdown and `consecutive_clean_audits`, correction not lifting risk, waiver removing risk, reverification precondition, SoD on verify, all three verify outcomes; `domain.py`'s `reconciled_feeds`, `compute_statement_money` step order, `refresh_audit_counts`, `kiosk_has_live_audit`, `suspend_kiosk`'s four-link chain.

### Final orchestrator verification

- `PRD.md` 488 lines / 113,885 chars → `PRD_FINALIZED.md` 488 lines / 115,935 chars → `PRD_COMPLETED.md` **492 lines / 146,656 chars**. `PRD_COMPLETED.md` is **NOT** byte-identical to `PRD_FINALIZED.md` (`cmp` → DIFFERENT), so the scan genuinely ran across all three passes. Totals: **60 ambiguity-pins + 10 mismatch-revisions across the three passes.**
- `PRD_COMPLETED.md` retains its 5 top-level sections and ends on the complete `| ERR_SPACE_OBLIGATION_DEFICIENT | 422 |` row — no truncation.
- `find` over `workspace/implementation/`, `test_suite/` and `test_helpers/` for files newer than the green sweep's `SWEEP_DONE` sentinel returns **nothing**: no Step 8 or Step 9 pass modified the implementation or the tests, so the final `results.{1..8}.json` (all `118/118`) still describes the shipped code exactly. All 8 result files are in place.
- `.scratch/` retains `step2/ step4/ step6/ step7/ step8/` with `.scratch/step7/sweep.sh` intact; the three Step 9 pass scratch dirs cleaned themselves up without touching siblings.

**PIPELINE COMPLETE.** Step 9 wrote `workspace/PRD_COMPLETED.md`.
