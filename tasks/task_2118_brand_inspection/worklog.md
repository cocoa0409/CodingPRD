# Worklog — task_2118_brand_inspection

## Step 1: Create task directory — 2026-08-17T00:00:00.000Z

Created `./tasks/task_2118_brand_inspection/` and `./tasks/task_2118_brand_inspection/workspace/`. Index 2118 derived from highest existing `task_NNNN_*` (2117) + 1. Short label: `brand_inspection`.

## Step 3: Copy shared files — 2026-08-17T00:05:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2118_brand_inspection/workspace/INSTRUCTION.md` (1424 bytes). (Executed early — bash-only step with no dependency on Step 2.)

## Step 2: Generate scaffold — 2026-08-17T01:05:00.000Z

Generated all three scaffold artifacts in `/home/ubuntu/github/CodingPRD/tasks/task_2118_brand_inspection/`, built only from the scenario text and the scaffold-generator skill (no sibling task was read).

**Lint verdict (verbatim)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  758

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## SCAFFOLD.yaml (§1.0–§1.7) — 2582 lines
Profile: **compliance_audit** primary x **temporal_windowing** secondary; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint; topology **graph** (self-referential `superseded_by_registration_id`, many-to-many AnimalLot<->BrandRegistration/BillOfSale); shape **cyclic** + two independent state dimensions on one row; role model **segregation_of_duties**; consistency immediate. Expert-plus band.

- **12 entities**: Owner, Territory, Inspector, BrandApplication, BrandRegistration, BrandConflictClaim, InspectionOrder, AnimalLot, BillOfSale (`common_fields: false`, immutable), EstrayCase, TheftInvestigation, FeeRemittance. 24 FKs, all reverse-reachable.
- **9 state machines**: BrandApplication (cyclic return->resubmit, bounded at MAX_CORRECTION_ROUNDS 2), BrandRegistration (ACTIVE/GRACE/ENCUMBERED/LAPSED/SUPERSEDED/REVOKED), InspectionOrder x2 (`schedule_status` and `fee_status` evolving independently), EstrayCase (claim-denied cycle), TheftInvestigation (bounded reopen cycle), BrandConflictClaim, FeeRemittance (SHORT_PAID->SUBMITTED cycle), AnimalLot (`match_status`).
- **2 concurrency rules** (OCC only): `renewal-application-stale-registration` on BrandRegistration.version (412), `schedule-order-stale-inspector` on Inspector.version (412).
- **8 calculations**: `inspection_fee_assessment` (marginal head bands, per-lot rounding order pinned — 10601 vs 10600), `estray_proceeds_distribution` (PROVISIONAL/FINAL variants, capped handling fee with pinned evaluation order), `owner_arrears_and_standing` (POSTED/PROJECTED variants, >=25000 suspension), `brand_priority_ranking` (affidavit gate x 10-year cap x backdating), `renewal_filing_fee` (30/90-day stepped penalties), `remittance_waterfall_application` (ordered, no skip-ahead), `inspector_window_occupancy` (conditional 45-min travel buffer), `facility_occupancy_projection` (aggregate capacity at every instant).
- **25 validations**, priorities 10->84, three distinct conflict pairs: (state, business_fiscal), (business_temporal, business_constraint), (business_safety, business_referential).
- **60 endpoints** under `/brand-inspection`, incl. `POST /_clock/set_current_utc` (default clock `2026-08-01T00:00:00Z`) and `POST /_ops/delinquency-sweep`.
- **46 errors**, every one referenced by a validation/transition *and* asserted by at least one design instance.
- **6 roles**: LivestockOwner (`entity_backed:Owner`), FieldInspector (`entity_backed:Inspector`), BrandRecorder, FeeAdministrator, TheftInvestigator, BoardAdmin (all `opaque`); SoD enforced via `examined_by_user_id != recorded_by_user_id`.

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 18 instances
9 rule_ids x 2 each: dual_variant_calc (EstrayCase money vs Owner standing), combinatorial_formula (mode b rounding order + mode a non-linear backdating), non_linear_state_machine (BrandApplication cycle + InspectionOrder two dimensions), transitive_cascade (depth-4 finding->investigation->encumbrance->CONFLICT_HOLD; depth-3 claim-sustain->revoke->UNVERIFIABLE->unschedule), priority_pair_validation_conflict, boundary_precision_check (25000 exactly vs empty-lot set), cross_entity_state_dependency (Order->Inspector, Application->Registration), resource_temporal_overlap (Inspector buffered pairwise vs Territory aggregate capacity), compensating_invariant (money ledger via void-assessment; head-count via estray disbursement).

## SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 70 instances (62 with recipes, 8 `excluded_because` stubs)
Sections: entities 12, state_machines 9, calculations 7, validations 13, endpoints 3, errors 17, rbac 4, cross_cutting_layers 4, consistency_model 1.

**Verified beyond the lint**: 88 unique instance names across both files, zero unbound `${var}` placeholders, all `grounds:` refs resolve into §1.1–§1.7, all 8 stub targets exist in §1.8, every error asserted somewhere, all OCC payload values are `${var}` references, and no forbidden concurrency vocabulary anywhere. All formula-derived assert values (7450, 10601, 2624, 14144, 23706, 25000/24999, 15000/21000, 66000/22800/91200, 102300/11540/46160, 5551/20551) were computed in code before being written as literals.

## Step 4: Generate PRD — 2026-08-17T01:20:00.000Z

The PRD is complete and verified on disk.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2118_brand_inspection/workspace/PRD.md` — **398 lines / 88,644 bytes**, generated from the 2,582-line scaffold. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Structure

5 top-level sections (`## 1`–`## 5`), matching the skill's mandated template:

- **§1 Introduction** — 3 paragraphs framing the board's four intertwined lifecycles (recording, inspection, disposition, fiscal).
- **§2 Global Specifications** — 10 domain-derived subsections: 2.1 Board Users and RBAC · 2.2 API Response Structure (emitted **byte-verbatim** from `section-2.2-response-structure.md`, confirmed by substring match) · 2.3 Pagination · 2.4 Common Record Properties and the Version Token · 2.5 The Board's Logical Clock · 2.6 Money, Head Counts and Rounding Discipline · 2.7 Stale-Record Protection · 2.8 The Order in Which a Request Is Evaluated · 2.9 Cascade Discipline · 2.10 Segregation of Duties.
- **§3 Business Logic** — 9 subsections grouped by board lifecycle: standing registry -> filing/recording -> priority, renewal, lapse -> conflict contests -> scheduling -> field findings -> theft investigations -> estray disposition -> fee dimension.
- **§4** — 60-row endpoint table, 4 columns. **§5** — 46-row error table, 2 columns.

## Scattering strategy

Section 1 written with `Write`; **12 further `cat >>` appends**, never a whole-file write: §2.2 verbatim · §2.3–2.7 · §2.8–2.10 · §3.1–3.2 · §3.3–3.4 · §3.5–3.6 · §3.7–3.8 · §3.9 · §4 header + 4 endpoint chunks (18/18/14/10 rows, generated from the scaffold by script so paths are byte-exact) · §5 header + 2 error chunks (24/22 rows).

Content scattering: the validation ladder lives in §2.8 while its individual triggers live in the §3 workflows they guard; the facility-capacity projection is specified in §3.8 and referenced from §3.6; the after-hours premium and the per-lot rounding pin live in §3.9 while the `scheduled_start_at` they read is set in §3.5; OCC tokens appear both in §2.7 and inside the two workflows that require them.

## Verification (verbatim output)

**Check 1 — `grep -c '^## ' PRD.md`** -> `5` (the exact top-level count my skill's template mandates: Introduction, Global Specifications, Business Logic, Endpoint Definitions, Error Code Catalogue).

**Check 2 — `tail -20 PRD.md`** -> ends on a complete final catalogue row, not a mid-sentence stop:
```
| `ERR_REMITTANCE_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_DOCUMENT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_BADGE_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_TERRITORY_CODE` | 409 Conflict |
```

**Check 3 — all 60 §1.5 endpoints:**
```
endpoints in scaffold: 60
matched in PRD.md (backticked path): 60
missing: NONE
```
Independently confirmed: `awk '/^## 4\./,/^## 5\./' | grep -c '^| \(POST\|GET\) '` -> `60`.

**Check 4 — all 46 §1.6 error ids:**
```
errors in scaffold: 46
matched in PRD.md: 46
missing: NONE
```
Independently confirmed: ``awk '/^## 5\./,0' | grep -c '^| `ERR_'`` -> `46`.

## Hard Contract reports (transcript only — not written into PRD.md)

```
Field coverage check:
- entities[].fields: 94 required, 94 present, 0 missing
- endpoints[].request_body: 44 required, 44 present, 0 missing
- endpoints[].query_params: 35 required, 35 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 25 checked, 25 expressed in prose (full ladder ordered in §2.8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 63 checked, 63 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (no operators, no fuzzy words), 0 missing
- validations[] conditions: 25 checked, 25 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 60 checked, 60 expressed, 0 missing
- entities[].fields[] structured content: 94 checked, 94 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (3 findings, APPROVED/DENIED, SUSTAIN/DISMISS,
  UNFOUNDED/SUBSTANTIATED, PROVISIONAL/FINAL, RECONCILED/SHORT_PAID, return->RETURN vs return->REJECT,
  DISBURSED/FORFEITED), 8 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 759
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two Contract-2 strengthening edits were applied after the first pass and re-verified: §2.7 now names both OCC write endpoints explicitly (allowed — Contract 3 polices §3 only), and §3.9 now states that the `REMITTED` transition requires `hold_flag` false, explaining why the theft-hold gate sits at tender time. PRD.md ends at §5 with no audit footer.

**Orchestrator on-disk re-verification:** `wc -l` = 398, `grep -c '^## '` = 5, `tail` shows a complete final error-catalogue row. PASS.

## Step 6: Generate implementation — 2026-08-17T01:55:00.000Z

Implementation complete and verified.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2118_brand_inspection/workspace/implementation/` (~3,050 lines of Python across 26 modules):

**Root:** `start.sh` (guarded `pip install`, `exec python3 app.py`), `requirements.txt`, `app.py` (blueprint registration, error handlers, global request-serialization WSGI middleware), `db.py` (in-memory dicts + logical clock), `errors.py` (46-entry error catalogue), `response.py` (envelope + pagination), `middleware.py` (auth/authz/ownership rungs), `util.py` (ISO-8601, half-up rounding, floor day math), `validation.py` (request-shape rung).

**`services/`:** `constants.py`, `aggregates.py` (owner arrears/standing, territory occupancy, encumbrance, head counts, assignment counts), `calculations.py` (priority ranking, renewal fee, tiered inspection fee, estray waterfall, window occupancy, facility projection), `cascades.py` (theft, conflict, supersession, lapse cascades).

**`routes/`:** `lookup.py` plus one module per resource group — owners, territories, inspectors, brand_applications (incl. nested renewal route), brand_registrations, conflict_claims, bills_of_sale, inspection_orders, animal_lots, estray_cases, theft_investigations, fee_remittances, ops.

## Endpoints
**60 implemented** — exactly matching the PRD §4 routing table (verified route-by-route against the registered URL map).

## Boot check
`PORT=19311 bash start.sh` from a fresh process: HTTP-ready in **2 s**, bound `0.0.0.0`. `GET /brand-inspection/inspectors` returned `{"data":[],...,"total_count":0}` (**store empty on boot — nothing seeded**), the logical clock read `2026-08-01T00:00:00.000Z`, owner create + statement returned correct envelopes, a headerless request returned 401. Server killed cleanly, port released. Storage is pure in-memory dicts — an audit for `sqlite|open(|json.dump|/tmp|pickle|seed` found only comment text.

## Correctness verification
Four smoke suites (~150 assertions) against live servers, all passing: brand priority/backdating/conflict contest with rank demotion, correction-round ceiling, segregation of duties, renewal OCC + supersession, renewal fee at the 0/30/31/91-day boundaries, scheduling gates (unavailable -> window conflict -> daily limit -> territory mismatch -> 402 standing) with the cross-district 45-min buffer, per-lot surcharge rounding and cumulative head bands, after-hours boundaries (06:59/07:00/18:00), depth-4 theft cascade + UNFOUNDED release / SUBSTANTIATED revoke / single reopen, estray impound with the aggregate capacity projection, provisional vs final distribution, forfeiture, conflict-claim 3-hop cascade releasing inspectors, delinquency sweep (ACTIVE->GRACE->LAPSED in one pass, suspension stamps), remittance waterfall with no skip-ahead, short-pay/top-up, overpayment refusal, void-assessment restoring pre-assessment aggregates, and ladder ordering (400->404->403->409->412). A concurrency probe (8 parallel schedules on one OCC token) yielded exactly one 200 and seven 412s.

Two judgement calls worth flagging: (1) `active_assignment_count` is refreshed silently on completion and on reads so it never goes stale, but only the PRD-declared mutations (assignment, withdrawal, cascade release, status change) advance the inspector's `version` — otherwise completing an order would invalidate a caller's scheduling token. (2) Per the §2.8 ladder, the ownership rung fires above the state rung, so a `FieldInspector` calling `begin`/`lots`/`complete` on an unassigned (`inspector_id: null`) order gets `ERR_NOT_RESOURCE_OWNER`, not `ERR_ORDER_INVALID_STATE`.

**Isolation note (orchestrator):** Steps 5 and 6 ran concurrently, so `test_suite/`/`test_helpers/` could appear on disk during Step 6. The impl-gen subagent was given an explicit hard prohibition on reading those directories and both design YAMLs, preserving the contract that directory non-existence normally enforces.

## Step 5: Generate unit tests — 2026-08-17T02:05:00.000Z

Test infrastructure and suite are complete.

## Files written

**`test_helpers/`** (9 modules, ~2,800 lines)
- `types.py` — 20 status/role enums + entity TypedDicts. `BillOfSale` deliberately carries only `id` + `created_at` (no `updated_at`, no `version`).
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD §4 endpoint (60 methods, `/brand-inspection` prefix).
- `api_errors.py` — 46 error IDs + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, `assert_arrears_consistent`, `assert_estray_distribution_conserved`, `assert_instant_equals`, `assert_three_fraction_digit_timestamp`.
- `factories.py`, `constants.py`, `test_users.py` (per-instance builders `make_livestock_owner_headers` / `make_field_inspector_headers` for the two entity-backed roles), `__init__.py`.
- `fixtures.py` (1,264 lines) — 7 tiers, from single-call primitives up to scenario builders that the depth tests share (`setup_arrears_boundary_pair`, `setup_two_order_arrears_scenario`, `setup_void_assessment_scenario`, `setup_estray_sold_unclaimed`, `setup_theft_cascade`, `setup_contest_under_adjudication`, `setup_three_open_fees_for_waterfall`, `setup_prior_use_priority_contest`, …).

**`test_suite/`** — `conftest.py` + 7 domain-named files, **98 tests**, all collecting cleanly.

## Coverage (verified programmatically)

| Queue | Instances | Translated | Skipped |
|---|---|---|---|
| A — Difficulty | 18 | 18 (36 tests, >=2 each) | 0 |
| B — Corner (non-stub) | 62 | 62 (62 tests) | 0 |
| B — `excluded_because:` stubs | 8 | not translated (correct) | — |

All 8 stub `difficulty_instance` cross-references resolve to real names in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`. No shortfall, no unknown tags, no untagged/dual-tagged tests, no `skip`/`xfail`, no scaffold references in emitted code.

Every PRD quotation (>=8 words) was machine-checked against a whitespace-normalised `PRD.md` — **0 non-verbatim citations**. Every docstring ends with exactly one `Design:` line. All literal expected values were independently recomputed (10601 vs 10600 per-lot rounding, 2624, 14144, 23706, 66000/22800/91200 provisional vs 102300/11540/46160 final, 15000/21000 grace boundary, 2016-08-04 backdating, 2031-07-31 expiry, 5551 shortfall) and match the design indices.

## One PRD-vs-design conflict found

`Corner/state_machines/corner_substantiated_close_revokes_registration_and_marks_lots` asserts that a `SUBSTANTIATED` theft close pulls a `SCHEDULED`/`IN_FIELD` order back to `REQUESTED`. **PRD §3.7 states the opposite verbatim**: *"This path stops at the lots; unlike a sustained conflict contest (§3.4), a substantiated theft close does not pull scheduled orders back to `REQUESTED`."* The instance is still translated (its distinguishing claim — record -> `REVOKED`, presented lots -> `UNVERIFIABLE` — is fully PRD-covered), but the contradicting assertion is dropped and replaced with the PRD-stated inverse (`schedule_status == "IN_FIELD"`). This is a corner-design bug, not a PRD gap.

## PRD-silence gaps

None forced a skip. Two near-misses worth flagging for the PRD author:
- **Lot recording outside `IN_FIELD`** — §3.6 says lots may only be recorded while the order reads `IN_FIELD` but never names the error there. Translated as `ERR_ORDER_INVALID_STATE`, derivable only because §3.5 explicitly binds `ERR_ORDER_NOT_SCHEDULABLE` to the schedule call and §2.8 lists `ERR_ORDER_INVALID_STATE` as the order's state-rung code. Naming the code in §3.6 would remove the inference.
- **`priority_rank` after a renewal is recorded** — the PRD does not order the supersession of the prior record against the group-wide rank re-derivation. The asserted rank 1 follows only from reading `priority_rank` declaratively over the final `ACTIVE`/`GRACE` membership; an explicit "the retired record leaves the group before ranks are re-derived" would make it airtight.

Tests were not executed end-to-end — `workspace/implementation/` is being generated concurrently and was neither read nor written.

## Step 7: Run tests and iterate — 2026-08-17T02:12:00.000Z

All 8 parallel rounds passed on the first sweep. Verification complete.

## Summary

**Iterations run: 1** (one 8-round parallel stability sweep; exit condition met immediately).

### Sweep result
| Round | Passed | Total | Failed | Skipped | Duration |
|---|---|---|---|---|---|
| 1–8 (all) | 98 | 98 | 0 | 0 | ~124 s each (concurrent) |

All eight rounds ran to completion under `--isolation per-test-server` (server rebooted via `start.sh` before each of the 98 tests). Union of failing tests across all rounds is **empty** — no flakiness surfaced, so the diagnostic protocol (STEP 0–3) was never entered.

### Tests deleted
**None.** No test failed either sub-check of STEP 1, because no test failed at all.

### Fixes applied to `test_helpers/`
**None required.**

### Fixes applied to `implementation/`
**None required.**

### Integrity checks performed (to rule out a false green)
- **Collection is complete**: 98 `def test_` functions across the seven `test_suite/test_0*.py` files; 98 collected; 98 passed. No test silently uncollected.
- **No suppression**: zero `pytest.mark.skip` / `xfail` markers anywhere in `test_suite/` or `test_helpers/`; `skipped == 0` in every results file. (The single grep hit for "skip" is prose inside a PRD §2.3 pagination docstring.)
- **No seeded data / no on-disk state**: `implementation/db.py` defines `Store` as plain dicts that start empty on every boot, with the logical clock initialised to the PRD §2.5 instant `2026-08-01T00:00:00Z`. Grep for `sqlite|pickle|shelve|json.dump|/tmp|redis|sqlalchemy` over `implementation/` returns nothing — per-test `start.sh` reboots genuinely wipe all state.
- **Concurrency handled deterministically**: `app.py` wraps the WSGI app in `SerializedMiddleware` (a global `RLock`), and `db.py` tie-breaks `created_at` ordering with an insertion sequence `_seq` — necessary because the logical clock is frozen between explicit moves, so `created_at` alone is not a total order. This is why the fan-out ordering tests (PRD §2.9) are stable rather than luck-of-the-draw.

### Note on the context hint
The reported PRD-vs-design conflict and the two near-miss PRD silences never surfaced as failures, so per instructions no action was taken on them and no worklog/SCAFFOLD file was read.

Artifacts: `results.1.json` … `results.8.json` are in `workspace/implementation/`.

**Orchestrator independent re-verification:** parsed all 8 results files directly — every one reports `passed=98 total=98 failed=0 skipped=0`. `grep -o 'def test_[a-z0-9_]*' test_suite/*.py | sort -u | wc -l` = 98 (unique test functions match the collected count, so no test was silently uncollected or duplicated). `grep -rn 'mark.skip\|mark.xfail' test_suite/ test_helpers/` = 0 hits. PASS.

## Step 8: Finalize PRD — SKIPPED — 2026-08-17T02:14:00.000Z

Skip condition from the entrance skill is met exactly: Step 7 exited on its first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations beyond the baseline. There is no `<step_7_diff>` to hand off, so no subagent was spawned and `PRD_FINALIZED.md` is deliberately absent. Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-17T02:25:00.000Z

`PRD_COMPLETED.md` is written. Final verification passed: same 398 lines, identical section headers, identical 110 table rows — 28 lines revised in place, no new sections or paragraphs.

## Summary

**Files** — source `workspace/PRD.md`: 398 lines / 88,644 chars. Output `workspace/PRD_COMPLETED.md`: 398 lines / 98,582 chars. Char delta **+9,879 (+11.2%)**, 28 lines changed in place.

**Counts** — 23 ambiguity-pins, 5 mismatch-revisions.

**Method notes** — I walked all 26 modules and cross-checked every raise site (34 distinct error codes) plus a scripted diff of all 60 endpoint paths and role lists against the §4 table (zero drift there — paths and roles matched exactly). Judgement calls: I left `ERR_FEE_INVALID_STATE`-before-`ERR_ORDER_HOLD_ACTIVE` alone because §2.8's ladder already pins it despite §3.9 listing them in the other order; I left defensive-only raises (`ERR_ORDER_NOT_FOUND` in `record_finding`, `ERR_TERRITORY_NOT_FOUND` in `_no_legible_brand`) unpinned as unreachable; and I fixed one §4 table description that was a straight copy-paste of the POST row's text.

**Changes**

- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall clock — `response.py:18`
- §2.3 — insert — ambiguity — non-integer / out-of-range `limit`, negative `offset` -> `ERR_INVALID_REQUEST`; empty string treated as omitted — `response.py:54-79`
- §2.4 — revise — **mismatch** — a derived recompute mutates the row only when the value actually changes; `active_assignment_count` never advances the inspector's own token — `aggregates.py:16-21,39-43,53-55,64-66`, `calculations.py:58-61`
- §2.5 — insert — ambiguity — `to_iso8601` required, `data` carries only `current_utc`, target may move backwards — `ops.py:20-27`
- §2.8 — insert — ambiguity — window-containment check runs after path resolution but before `inspector_id` body resolution — `inspection_orders.py:111-119`
- §2.9 — insert — ambiguity — `created_at` ties break by insertion sequence (clock is frozen between moves) — `db.py:67-74`
- §3.1 — insert — ambiguity — statement returns exactly six keys; `open_order_count` = `ASSESSED`/`DELINQUENT`; `contact_email` unvalidated — `owners.py:47-61`
- §3.1 — revise — ambiguity — inspector status assignment is unrestricted and always bumps `version` — `inspectors.py:73-79`
- §3.2 — insert — ambiguity — free-standing route also admits `RENEWAL` (renewal pricing, `ERR_REGISTRATION_UNRENEWABLE`, no token/supersession); `prior_registration_id` optional for every type — `brand_applications.py:77,89-97`
- §3.2 — insert — ambiguity — the 201 answers with the new registration, not the filing — `brand_applications.py:318`
- §3.3 — insert — ambiguity — the four group keys compare as exact case-sensitive strings — `calculations.py:21-22`
- §3.3 — insert — ambiguity — ranks re-derive only on recording; departed records keep a frozen rank; only movers are mutated — `calculations.py:47-62`
- §3.3 — revise — **mismatch** — prior-use inputs are *not* inherited on renewal; they default to 0 / false — `brand_applications.py:130-131`
- §3.4 — insert — ambiguity — an omitted `decision_note` is written as null — `conflict_claims.py:84,97,102`
- §3.5 — insert — ambiguity — a lapsed commission at open time yields `ERR_INSPECTOR_UNAVAILABLE`, after the `SCHEDULED` check — `inspection_orders.py:164-168`
- §3.6 — insert — ambiguity — `sale_date` is an instant echoed as full ISO; `head_count` floored at 1 — `bills_of_sale.py:22-23`, `util.py:23-34`
- §3.6 — insert — ambiguity — finding/lot contradictions all yield `ERR_ORDER_INVALID_STATE`; a `bill_of_sale_id` is resolved but ignored outside `MATCH_CONFIRMED`; response is the lot — `animal_lots.py:50,60-61,73-76,89-100,135-136`
- §3.7 — insert — ambiguity — substantiated close revokes regardless of remaining open cases and releases no frozen filings — `theft_investigations.py:86-90`, `cascades.py:92-98`
- §3.7 — insert — ambiguity — a reopen does not re-freeze pending filings — `theft_investigations.py:112-124`
- §3.8 — insert — ambiguity — both intake gates test the parent order's `territory_id` — `animal_lots.py:138-146`
- §3.8 — insert — ambiguity — `claimant_owner_id` stamped from `X-User-ID` unresolved; claiming carries no ownership rung — `estray_cases.py:42-51`
- §3.8 — insert — ambiguity — `estimated_gross_cents` / `gross_proceeds_cents` carry no positivity bound — `estray_cases.py:92,111`
- §3.8 — insert — ambiguity — close-out leaves `match_status` at `UNMATCHED`; forfeiture is not floored at zero — `estray_cases.py:136-151`
- §3.9 — revise — **mismatch** — assessment recomputes the owner in full (both flavours, `standing`, `suspended_since`), not just `projected_arrears_cents` — `inspection_orders.py:241`
- §3.9 — revise — **mismatch** — sweep stage 3 recomputes *every* owner on file, not only those touched; plus counter semantics, `swept_at`, no request body — `ops.py:33,75-88`
- §3.9 — insert — ambiguity — covered orders are resolved and hold-tested but not checked for belonging to the remitting owner — `fee_remittances.py:26-33`
- §3.9 — insert — ambiguity — top-up leaves `applied_cents` and `shortfall_cents` untouched until the next pass — `fee_remittances.py:129-131`
- §4 — revise — **mismatch** — `GET /brand-applications` row carried the POST row's description; now describes the list operation and its filters — `brand_applications.py:180-192`

**Orchestrator independent re-verification:** `PRD.md` 398 lines / 88,644 chars vs `PRD_COMPLETED.md` 398 lines / 98,582 chars; `grep -c '^## '` = 5 (no sections added); `diff` reports exactly 28 changed lines (matches the claimed 28 in-place revisions, confirming no line-count drift or appended paragraphs); file still ends on a complete error-catalogue row. `PRD_FINALIZED.md` correctly absent. PASS.
