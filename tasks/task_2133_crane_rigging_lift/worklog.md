# Worklog — task_2133_crane_rigging_lift

## Step 1: Create task directory — 2026-08-22T00:00:00.000Z

Created `tasks/task_2133_crane_rigging_lift/` and `tasks/task_2133_crane_rigging_lift/workspace/` (index 2133 = highest existing 2132 + 1).

## Step 2: Generate scaffold — 2026-08-22T11:20:00.000Z

All three artifacts are written and verified. Final lint verdict, pasted verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  1032

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Files (all under `tasks/task_2133_crane_rigging_lift/`):
- `SCAFFOLD.yaml` — §1.0–§1.7, 2289 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 2144 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 3258 lines

## Scaffold contents

**Profile**: `compliance_audit` × `pricing_engine`; **flat** topology, **parallel** state-machine shape, **segregation_of_duties** roles, `immediate` consistency. Layers: cascading side effects, dual-variant calculation, OCC, rate/threshold triggers.

**13 entities**: Customer, Site, Crane, LoadChartEntry, Personnel (polymorphic OPERATOR/RIGGER/ENGINEER), RiggingGear, GearInspection, LiftPlan, GearAssignment (M:N junction), EngineeringReview, Permit, StandbyEvent, Invoice.

**7 state machines**: LiftPlan carries **two parallel dimensions** (`plan_status` 8 states × `field_status` 6 states with a LIFTING<->WIND_HOLD cycle); EngineeringReview, Permit, Crane and RiggingGear are all cyclic; Invoice has an ISSUED<->DISPUTED loop. **3 OCC rules** (LiftPlan version on configure and on invoice create; RiggingGear version on gear assignment).

**13 calculations**, **23 ordered validations**, **59 endpoints** (incl. `POST /_clock/set_current_utc`, default clock `2026-08-01T00:00:00Z`), **49 error codes**, **7 roles**.

## Difficulty spine (all literals executed in Python, not estimated)

- Load-chart **ceiling lookup** feeding `min(chart_gross, max_line_pull x parts)` — 100000 vs 80000 -> net 78000 -> util 94.23.
- **Ground bearing dual-variant**: same inputs give 2271.88 psf / 8 mats (PROVISIONAL_SURVEY) vs 5997.75 psf / 16 mats (FINAL_ENGINEERED at PE stamp).
- **Invoice dual-variant**: identical closed job = 1 011 734 c HOURLY vs 974 016 c LUMP_SUM.
- **Rounding order pinned**: round-per-line-then-sum gives subtotal 945546; sum-then-round gives 945545 (one cent apart).
- **Circular fee/discount pinned**: tier keyed on the pre-surcharge subtotal -> discount_pct 0.00 and total 1 011 734, not the 991 499 the circular reading yields.
- Two **4-hop cascades** from different triggers: gear FAIL -> assignment VOIDED -> plan demoted -> review SUPERSEDED; plan cancel -> permit VOIDED (58000 c) -> system invoice ISSUED (62060 c) -> customer receivable.
- Two **overlap rules with different interval semantics**: crane half-open window + 12 h trailing buffer vs operator per-UTC-day clipped 12.0 h aggregate cap.
- Three **priority-conflict pairs** on distinct categories: state<->safety, safety<->fiscal, referential<->temporal.

## Index sizes

- §1.8: **20 instances** across all 9 rule_ids (dual_variant 2, combinatorial 3 covering modes a/b/c, non_linear 2, cascade 2, priority 3, boundary 2, cross_entity 2, temporal 2, compensating 2).
- §1.9: **65 instances** (62 with full recipes + 3 `excluded_because` stubs) across all nine claim-extraction sections.

Verified beyond the linter: zero unbound `${var}` across both design files, names unique across the union, all `grounds` refs resolve into §1.1–§1.7, every one of the 49 error codes is referenced outside the catalog, all stub targets exist in §1.8, and no forbidden concurrency vocabulary anywhere.

## Step 3: Copy shared files — 2026-08-22T11:20:30.000Z

Copied `./INSTRUCTION.md` -> `tasks/task_2133_crane_rigging_lift/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-22T11:32:00.000Z

PRD generated at `workspace/PRD.md`.

## Result

**423 lines.** Built incrementally (16 separate Write/append calls) — no single-call output-cap risk. Verified complete: file ends at the §5 error table with 49 rows, no audit footer.

### Sections present
- §1 Introduction (4 paragraphs — domain framing, dual-dimension state machine, money conservation, flat topology)
- §2.1 Crew Identity and RBAC · §2.2 API Response Structure (verbatim) · §2.3 Pagination · §2.4 Common Resource Properties and the Logical Clock · §2.5 Stale-View Protection · §2.6 Measurement Precision and Rounding · §2.7 The Order of Rejection · §2.8 Path Resolution for Reverse Lookups · §2.9 Cascade Discipline and Conserved Ledgers
- §3.1 Accounts, Ground, Iron and Crew · §3.2 Rigging Gear Integrity, Derate and Retirement · §3.3 Opening a Lift Plan and Confirming the Ground · §3.4 Committing Rigging, Configuring the Machine and Holding the Schedule · §3.5 Ground Bearing, Matting and the Wind Envelope · §3.6 Engineering Review of Critical Lifts · §3.7 Permits, Escorts and Road Closures · §3.8 Sign-Off, Release and the Day of the Lift · §3.9 Cancellation, Billing and the Receivable Ledger
- §4 Endpoint table (4 columns, **59 rows**) · §5 Error table (2 columns, **49 rows**)

### Hard contract reports

```
Field coverage check:
- entities[].fields: 144 required, 144 present, 0 missing
- endpoints[].request_body/input: 89 required, 89 present, 0 missing
- endpoints[].query_params (limit/offset + all filters): present, 0 missing
- errors[].id mentioned in prose: 49/49 · roles: 7/7 · state values: 33/33 · enum values: all present
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 23 checked, 23 expressed as an explicit ordered ladder in §2.7 (with applies_to scopes enumerated), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_lift_plan_version / expected_gear_version + ERR_STALE_PLAN_VERSION / ERR_STALE_GEAR_VERSION + 412), 0 missing
- state_machines[].transitions: 54 checked across 7 machines, 54 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed in prose (no pseudocode), 0 missing
- validations[] conditions: 23 checked, all matchable to error_id, 0 missing
- endpoints[].side_effects: 35 checked, 35 expressed, 0 missing
- entities[].fields[] structured content: 144 checked (types/defaults/initial values/derivation precedence), 0 missing
- sibling-branch symmetry: 8 groups checked (configure STANDARD vs CRITICAL fork; PROVISIONAL_SURVEY vs FINAL_ENGINEERED; HOURLY vs LUMP_SUM; 4 gear-inspection results; 3 review decision actions; 5 field-status actions; 3 permit types; 4 wind-derate tiers), 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 303
- tokens starting with `/`: 0 · bare HTTP-method tokens: 0 · method+path tokens: 0
Status: PASS
```

### Key coverage notes
- **All 13 calculations** are in precise prose with the traps preserved: exact-boom/ceiling-radius chart lookup with `created_at` tie-break, nested `min()` capacity, the 75.00/90.00 boundaries compared on the *rounded* utilization, the two ground-bearing variants (divide-by-4 vs 0.60 x 1.10), round-per-line-then-sum across the seven invoice lines, discount tier keyed on the **pre**-surcharge subtotal, half-open interval merge with zero-gap adjacency, and clipped per-day operator hours.
- **All four cascades** stated hop by hop (crane->plan->permit depth 3; gear->assignment->plan->review depth 4; plan-cancel->permit->invoice->customer depth 4; plus the demotion teardown field list).
- §2.7 explicitly calls out three ordering traps (OCC before own-state; credit hold last; jurisdiction before lead time).
- `LoadChartEntry` and `GearInspection` are explicitly stated to carry only `id` and `created_at` — no `updated_at`, no `version`.
- §2.2 confirmed byte-identical to `section-2.2-response-structure.md`.
- Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

## Step 6: Generate implementation — 2026-08-22T11:52:00.000Z

Implementation complete at `workspace/implementation/`.

## Modules (16 files, 2,623 lines)

| File | Lines | Role |
|---|---|---|
| `core.py` | 224 | Logical clock (starts `2026-08-01T00:00:00Z`), in-memory `Store`, Decimal rounding helpers (`rhu`/`floor`/`ceil`), 49-entry error catalog + `ApiError`, response envelope (`meta`/`response_type`/`data`, `req_` + 20 alnum id, 3-digit-ms ISO stamps) |
| `guards.py` | 222 | Ladder steps 1-6: `auth()` (X-User-ID/X-User-Role, 7 roles), `must_exist()` per-collection 404 mapping, typed `Body` reader, pagination/query-enum validation |
| `derive.py` | 332 | All computed fields (crane status precedence + reserved ledger, personnel status/peak daily hours, gear posture overlay + derate, customer receivable, plan invoice count) and 13 serializers |
| `calc.py` | 191 | 13 calculations: chart ceiling lookup, dual-variant ground bearing, sling tension, gear derate, wind derate tiers, standby interval merge, permit fee/lead, invoice line rounding, discount/surcharge order, crane hours, operator day hours, lift class, cancellation fee |
| `cascades.py` | 158 | The 4 transitive cascades + `build_invoice` |
| `routes_setup / gear / plan / review / permit / standby / invoice / clock` | 1,438 | 59 endpoints |
| `app.py`, `start.sh`, `requirements.txt` | 63 | Entry point, guarded-install foreground launcher |

**59/59 endpoints registered** (verified by dumping `url_map`). Store is empty at boot — no seeding anywhere.

## Key fidelity decisions
- Conserved ledgers (crane hours/plan count/status, gear commitment count, customer receivable, plan invoice count, personnel peak hours) are **derived on read**, so compensating actions return exact prior values by construction.
- The §2.7 23-step rejection ladder is coded explicitly per handler (OCC before own-state; credit hold last; jurisdiction before lead time; capacity gates before scheduling before fiscal).
- Configure is fully **atomic** — every value is computed into locals and validated before a single plan field is written.
- `created_at`/`updated_at` are wall-clock; every expiry/lead-time/window/inspection comparison uses the logical clock. List ordering uses an internal insertion sequence so `created_at` ties can't reorder results.
- Ambiguities resolved conservatively: closing a non-OPEN standby -> `ERR_INVALID_FIELD_STATE` (only 409 state code that fits); pulling an already-OOS crane -> `ERR_CRANE_OUT_OF_SERVICE`; return-to-service has no state gate (PRD states only the date requirement).

## Smoke tests (3 scenarios, all green against `bash start.sh`)
- **Envelope**: success `{meta{api_request_id, api_request_timestamp}, response_type, data}`; list meta adds `limit/offset/total_count/has_more`; errors `response_type:"error"` + `data{error_id,message}`; unknown route -> 404 in-envelope. 401/403/404 all correct.
- **Scenario 1** (standard lift): util 50.33 %, provisional bearing 52 550.00 lb / 2 102.00 psf, leg tension 8 720 lb, crane `AVAILABLE->RESERVED->IN_SERVICE->AVAILABLE`, standby 1.1667 h -> billable 1.25 h, HOURLY invoice subtotal 866 088 -> total 926 714, issue-then-void returned receivable to 0 with `invoice_count` 1.
- **Scenario 2** (critical lift): stale-version beats state, chart ceiling picks the correct row, `CRITICAL`->`PENDING_ENGINEERING`, SoD both directions, revision limit **fails 409 yet persists REJECTED**, STAMP wrote FINAL_ENGINEERED (150 480.00 lb / 6 019.20 psf / 61 sqft / 8 mats) and advanced the plan to APPROVED; permit fees 145 000/lead 15 with escort; crane-OOS depth-3 and gear-FAIL depth-4 cascades verified end-to-end; cancel chain minted the system invoice (34 000 fee -> 36 380 total) and moved the receivable.
- **Scenario 3**: proximity override, window conflict with the 12 h buffer, operator 12 h/day cap, zero-gap standby adjacency merge, LUMP_SUM discount tier 5 % (3 002 850 -> 3 052 396), draft-supersede, dispute/re-issue/pay ledger, duplicate tag/chart row, pagination and enum-filter 400s.

Two arithmetic errors surfaced during smoke testing were in my *test expectations*, not the server — the implementation's values were correct on re-derivation.

## Step 5: Generate unit tests — 2026-08-22T12:00:00.000Z

Test infrastructure and suite generated. All files parse, none truncated, and the runner collects 106 test items.

## Files written

**`test_helpers/` — 2,178 lines**
| file | lines |
|---|---|
| `__init__.py` | 40 |
| `types.py` | 451 |
| `api_client.py` | 227 (all 59 endpoints) |
| `api_errors.py` | 113 (all 49 errors + status map registration) |
| `assertions.py` | 276 |
| `factories.py` | 213 |
| `constants.py` | 137 |
| `test_users.py` | 56 |
| `fixtures.py` | 665 |

`types.py` correctly gives `LoadChartEntry` and `GearInspection` only `id`/`created_at` (append-only). `fixtures.py` exposes two canonical worlds (`build_standard_world` = 150-ton STANDARD path, `build_critical_world` = 275-ton CRITICAL path + two engineers) plus 11 lifecycle composites through `setup_closed_standard_job` / `setup_closed_critical_job` / `setup_stamped_critical_plan`. Identity is threaded via `make_engineer_headers` / `make_operator_headers` / `make_customer_headers` for the three entity-backed roles.

**`test_suite/` — 3,318 lines across conftest + 11 themed files** (`test_01_entities_and_records`, `02_state_machines`, `03_calculations`, `04_validations`, `05_endpoints_errors_and_roles`, `06_concurrency_and_consistency`, `07_capacity_and_classification`, `08_ground_bearing_and_engineering`, `09_billing_and_receivables`, `10_cascades_and_ledgers`, `11_rejection_order`).

## Coverage

- **Queue A (Difficulty)**: 40 tests — exactly 2 per each of the 20 instances. 0 shortfalls.
- **Queue B (Corner)**: 62 tests — 1 per each of the 62 non-stub instances. 0 shortfalls.
- 102 test functions, every one carrying exactly one `Design:` line resolving to a real instance; no untagged, dual-tagged, or dangling tags; no `skip`/`skipif`/`xfail`.
- Automated verbatim check: all **577** quoted PRD fragments of >=8 words survive a literal grep of `PRD.md`.

## Instances skipped

**None.** All 20 difficulty and all 62 non-stub corner instances passed the PRD-first two-condition filter. The 3 `excluded_because` stubs (`ground_bearing_variant_divergence_between_survey_and_stamp`, `invoice_variant_divergence_between_hourly_and_lump_sum`, `invoice_precision_round_each_line_before_summing`) were not translated; their `difficulty_instance` cross-references all resolve.

## Reconciliation notes (PRD won)

1. **Corner `gear_retirement_cascade_skips_a_plan_that_is_already_mobilized`** — dropped the index's `rigging_verified == true` assertion. PRD §3.2 ("left alone at every hop") and §3.4 ("`rigging_verified`... remains only while the plan holds at least one active commitment") leave two PRD-only readers free to disagree. The instance's core claim (VOIDed commitment, plan stays RELEASED/MOBILIZED) is fully tested.
2. **Corner `stamping_an_already_stamped_review_returns_invalid_review_state`** — the index drives the second STAMP as the *author*, which under the §2.7 ladder (step 7 segregation precedes step 9 state) would return `ERR_SEGREGATION_OF_DUTIES` and mask the asserted error. Test uses a non-author engineer so the state check is genuinely the first failing rule; the asserted `ERR_INVALID_REVIEW_STATE`/409 is preserved.
3. **Corner `crane_return_to_service_recomputes_posture_to_reserved_not_available`** — asserts `annual_inspection_expires_on` starts with `2027-12-31` rather than exact string equality; the PRD pins the three-fractional-digit format only for `created_at`/`updated_at`, not for this echoed input datetime.

No numeric conflicts were found between the indices and the PRD: every literal asserted (bearing 90875.00/2271.88/8 vs 239910.00/5997.75/16, capacity 100000/80000/78000, utilization 94.23/75.00/74.99/100.51, tensions 21223/21387/30250, derate 28500/27000/21000, wind 21/25, permits 145000/15, 85000/10, 25000/3, cancellation 58000/34000, invoice 945546/1011734/910295/974016/431500/461705/3120250/3171734/62060/36380) re-derives from PRD prose.

## Step 7: Run tests and iterate — 2026-08-22T12:12:00.000Z

## Summary

**Iterations run:** 2 (baseline sweep + one fix round). Final sweep: all 8 parallel rounds **106/106 passed**, zero flakiness.

**Tests deleted:** none. No test failed STEP 1 (PRD coverage / unique derivability) — the only failures were a mechanical test-helper defect, resolved under STEP 2.

**Fixes applied to `test_helpers/`:**

- `test_helpers/fixtures.py` — `open_plan()`: it forwarded the world default as an explicit keyword *and* splatted caller overrides into the same factory call, so any test that overrode that field raised `TypeError: create_lift_plan_payload() got multiple values for keyword argument 'load_weight_lb'` before a request was ever issued. Now the world default and the overrides are merged into one dict (overrides win) before the factory call.
- Same file, `survey_plan()` — identical latent collision on `confirmed_soil_bearing_capacity_psf`; merged the same way pre-emptively. No test triggers it today, but it would have detonated the same way on the first test that overrode the confirmed soil capacity through this helper.

**Fixes applied to `implementation/`:** none. The three failures (`test_a_radius_beyond_the_chart_leaves_the_candidate_set_empty`, `test_utilization_above_the_ceiling_returns_capacity_exceeded`, `test_utilization_just_below_the_boundary_stays_standard`) all aborted during fixture setup and never reached the server — a single upstream helper bug masquerading as three independent implementation bugs, exactly the triage-hint pattern. The implementation was correct throughout and is unmodified.

One note worth flagging for whoever maintains the fixture layer: the deleted-vs-fixed distinction here rested entirely on the failures being pre-request `TypeError`s, which is unambiguous. A helper that instead built a *valid but PRD-inconsistent* payload would have produced real 4xx responses and looked far more like an implementation bug — the same `world_default=..., **overrides` idiom appears in `commit_gear()` and `configure_body()`, which handle it correctly via `dict.update`, but the two sites I fixed show the idiom is not applied consistently across the file.

## Step 7b: Orchestrator verification sweep — 2026-08-22T12:30:00.000Z

Orchestrator independently re-ran the stability sweep (8 rounds, batched 2-concurrent to avoid OOM under host contention with a concurrent task_2134 pipeline). Result: all 8 rounds `passed=106 failed=0 total=106`. Note: the fix agent's original `results.*.json` were destroyed by the orchestrator's own re-invocation of `sweep.sh`, whose first line is `rm -f results.*.json`; the files present now are from this verification sweep.

## Step 8: Finalize PRD — 2026-08-22T12:35:00.000Z

Done. `PRD_FINALIZED.md` is written and is byte-identical to `PRD.md`.

## Result

- `workspace/PRD_FINALIZED.md` — 423 lines vs `PRD.md` 423 lines, **0.0% delta**, identical md5.
- **Zero edits.**

## Why zero

`<step_7_diff>` lists exactly two changes, both in `test_helpers/fixtures.py`, both pure Python keyword-collision bugs (`world_default=..., **overrides` splatted into the same factory call -> `TypeError` before any HTTP request). Zero implementation fixes, zero test deletions, zero weakened assertions. Under HARD SCOPE, the only candidate PRD subjects are the two fields those sites touch. Both verified against PRD prose and impl:

**Site 1 — `load_weight_lb` on `open_plan()` / `POST /lift-plans`**
- Impl paths enumerated and read: `routes_plan.py:32` (`b.integer("load_weight_lb", exclusive_min=0)` — required, integer, strictly positive), `:53` (stored verbatim on the record), `:209` (`total_load_lb = load_weight_lb + rigging_weight_lb`), `:269` (fed to the wind-derate sail-area ratio), `derive.py:246` (included in the plan JSON projection).
- PRD coverage: §3.3 line 189 names the field, marks it required, "the weight of the load itself in pounds, excluding rigging, which must be positive"; line 108 pins weights as whole pounds; line 209 pins `total_load_lb`; line 235 pins the sail-ratio use, including the zero-weight degenerate case. Name, type, required shape, positivity, and every downstream use are already uniquely determined. No edit.

**Site 2 — `confirmed_soil_bearing_capacity_psf` on `survey_plan()` / `POST /lift-plans/{id}/site-survey`**
- Impl paths enumerated and read: `routes_plan.py:129` (`b.integer(..., exclusive_min=0)` — required, integer, strictly positive), `:137` (overwrites `site["soil_bearing_capacity_psf"]`), plus the parallel write site `routes_setup.py:80,88` (site creation, identical `integer/exclusive_min=0` contract), the read sites `calc.py:38` (matting / mat-area basis) and `derive.py:163` (site JSON projection).
- PRD coverage: §3.3 line 193 names it as one of three required survey inputs and states it "overwrites the site's stored `soil_bearing_capacity_psf`"; line 161 pins that target field as strictly greater than zero, so the overwrite inherits the same contract; line 233 pins the matting/mat-area consumption. Consistent across both write paths and both read paths. No edit.

Both fixture bugs aborted pre-request, so they expose no server behavior at all — no PRD silence, no PRD/impl mismatch. Manufacturing an edit here would have added a new claim traceable to nothing in the diff, which Step 9 would have to undo.

## Step 9: Complete PRD — 2026-08-22T12:48:00.000Z

Verified: 423 lines in, 423 lines out — every change is an in-paragraph insert or revision, no new paragraphs or sections.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 423 lines / 87,360 chars -> `PRD_COMPLETED.md` 423 lines / 92,798 chars (**+5,438 chars**, 31 lines touched by 40 string-level edits).

**Counts:** 34 ambiguity-pins, 6 mismatch-revisions.

### Mismatch revisions (PRD described behavior impl does not exhibit)
- §2.1 — revise — mismatch — "Customer may read only what belongs to it" -> scope enforced on exactly the three listed operations; a Customer reading any site or lift plan is unchecked — `routes_setup.py:100-104`, `routes_plan.py:91-96`
- §2.4 — revise — mismatch — clock move does not write person/gear postures (derived on read; clock may run backwards, restoring `SERVICEABLE`); only the crane expiry cascade acts eagerly — `routes_clock.py:14-20`, `derive.py:95-101`, `cascades.py:86-92`
- §2.7 ladder step 10 — revise — mismatch — gates re-attached per endpoint; configure enforces **only** the crane gate and never re-tests already-committed gear serviceability — `routes_plan.py:180-182` vs `routes_plan.py:314-324`
- §3.1 — revise — mismatch — out-of-service is legal from every posture except `OUT_OF_SERVICE` (including `IN_SERVICE`), not "AVAILABLE or RESERVED"; repeat attempt -> `ERR_CRANE_OUT_OF_SERVICE` 409 — `routes_setup.py:173-184`
- §3.2 — revise — mismatch — gear cascade hop 2 is unconditional: commitments held by mobilized plans are still `VOIDED` — `cascades.py:44-53`
- §3.2 — revise — mismatch — "left alone at every hop" -> left alone **from hop three onward** — `cascades.py:55-66`

### Ambiguity pins
- §2.3 — insert — insertion order breaks `created_at` ties — `core.py:167-172`
- §2.4 — insert — `created_at`/`updated_at` are wall-clock, not logical-clock, stamps — `core.py:175-187`
- §3.1 — insert — `rated_max_wind_mph` must be positive; all crane figures whole numbers except fractional `outrigger_pad_area_sqft` — `routes_setup.py:128-136`
- §3.1 — insert — out-of-service `reason` required but not persisted — `routes_setup.py:177-178`
- §3.1 — insert — return-to-service legal from any posture; bad date -> `ERR_INVALID_REQUEST` 400 — `routes_setup.py:187-199`
- §3.2 — insert — `inspector_note` required, may be empty string — `routes_gear.py:93`
- §3.2 — insert — `FAIL`/`RETIRE` leave `next_inspection_due_at` untouched — `routes_gear.py:107-112`
- §3.2 — insert — outright retire: `reason` required/not persisted, legal from any posture but `RETIRED` (`ERR_INVALID_GEAR_STATE`) — `routes_gear.py:72-83`
- §3.2 — insert — teardown also resets `escort_required`/`permit_required`, and deliberately leaves `allowable_wind_mph` plus the recorded configure inputs standing — `cascades.py:19-41`
- §3.2 — insert — gear listing `status` filter matches the clock-derived posture — `routes_gear.py:57-69`
- §3.3 — insert — `load_weight_lb` whole pounds; `sail_area_sqft` may be fractional — `routes_plan.py:32-33`
- §3.3 — insert — survey bumps the site's `version` as well as the plan's — `routes_plan.py:136-145`
- §3.4 — insert — commitments are ungated by plan readiness posture — `routes_gear.py:145-179`
- §3.4 — insert — commit bumps gear `version` only, never the plan's — `routes_gear.py:177-178`
- §3.4 — insert — withdrawal bumps only the commitment's `version`, not the gear's — `routes_gear.py:207-214`
- §3.4 — insert — configure FKs resolved `crane_id` -> `operator_id` -> `rigger_id` — `routes_plan.py:166-168`
- §3.4 — insert — reserved-hours rounding applied once to the finished sum, not per plan — `derive.py:24-29`
- §3.4 — insert — `peak_daily_assigned_hours` derived on read; non-`OPERATOR` always 0 — `derive.py:85-91`
- §3.6 — insert — `analysis_notes` required, may be empty — `routes_review.py:21`
- §3.6 — insert — new review carries `final_bearing_pressure_psf`/`final_mat_count` at 0; submission ungated by plan state — `routes_review.py:26-38`
- §3.6 — insert — revision-limit `decision_note` is exactly `revision limit exceeded` — `routes_review.py:129-134`
- §3.7 — insert — permit creation ungated by plan state and by `permit_required` — `routes_permit.py:18-44`
- §3.7 — insert — approval writes supplied `agency_reference`, null when absent — `routes_permit.py:113-116`
- §3.7 — insert — denial stores `agency_reference` when supplied, else leaves prior value — `routes_permit.py:117-120`
- §3.8 — insert — all three approve conditions fail as `ERR_INVALID_PLAN_STATE` 409 — `routes_plan.py:286-299`
- §3.8 — insert — MOBILIZE: non-`RELEASED` -> `ERR_INVALID_PLAN_STATE` 409; order = field posture, readiness, crane — `routes_plan.py:377-395`
- §3.8 — insert — standby may be opened against any plan posture — `routes_standby.py:18-49`
- §3.8 — insert — `forced_wind_hold` stays false unless the plan was actually `LIFTING` — `routes_standby.py:32-36`
- §3.8 — insert — `ended_at` ordering -> `ERR_INVALID_REQUEST` 400, checked before posture; non-`OPEN` close -> `ERR_INVALID_FIELD_STATE` 409 — `routes_standby.py:84-89`
- §3.9 — insert — minted cancellation invoice is costed by the full `LUMP_SUM` rules (standby line, discount, surcharge) and voids no prior draft — `cascades.py:129-158`, `calc.py:127-191`
- §3.9 — insert — invoice drafting ungated by plan posture; plan `invoice_count` spans all statuses; figures frozen at creation — `routes_invoice.py:15-43`, `derive.py:127-128`
- §3.9 — insert — crane-less plan bills at rate 0 and `line_mobdemob_cents` 0 — `calc.py:128-130`
- §3.9 — insert — `dispute_reason` required but persisted nowhere — `routes_invoice.py:100-112`
- §3.9 — insert — void `reason` required but not persisted — `routes_invoice.py:87-97`
