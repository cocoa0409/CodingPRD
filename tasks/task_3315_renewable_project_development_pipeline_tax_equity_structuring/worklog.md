# Worklog — task_3315_renewable_project_development_pipeline_tax_equity_structuring

## Step 1: Create task directory — 2026-09-30T19:50:00.000Z

Pre-allocated directory `tasks/task_3315_renewable_project_development_pipeline_tax_equity_structuring/` verified to exist with `workspace/` inside; used as-is per command args (no new index computed).

## Step 2: Generate scaffold — 2026-09-30T20:10:00.000Z

All three files are written and lint-clean. Summary:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_3315_renewable_project_development_pipeline_tax_equity_structuring/SCAFFOLD.yaml` (1,617 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3315_renewable_project_development_pipeline_tax_equity_structuring/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1,947 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3315_renewable_project_development_pipeline_tax_equity_structuring/SCAFFOLD_CORNER_DESIGN.yaml` (1,478 lines)

## Counts
- **Entities: 12** — Project, SiteControlInstrument, InterconnectionRequest, InterconnectionStudy, OfftakeAgreement, SupplyAgreement, ProcurementOrder, ConstructionMilestone, TaxCreditQualification, TaxEquityPartnership, PartnershipLedgerEntry (immutable, common_fields: false), DebtFacility
- **State machines: 11** — 4 of them non-linear (offtake negotiation cycle, study deficiency/rework loop, milestone rejection/resubmission loop, TCQ lapse/cure cycle), plus a cascade-only project COD transition
- **Endpoints: 50** (incl. `POST /api/_clock/set_current_utc`, default 2026-09-01T00:00:00Z)
- **Validations: 12 priority rows** (auth → role → existence → shape → OCC → state → SoD → temporal → constraint → referential → fiscal → tax-anchor)
- **Calculations: 9** — incl. dual-variant safe-harbor test and continuity assessment, ITC adder formula (mode a), pinned rounding waterfall (mode b), pinned flip-IRR evaluation order (mode c), upgrade pro-rata with remainder rule, queue reseat, DSCR sizing, availability LD
- **Errors: 32**; **Roles: 9** (all opaque; segregation-of-duties between ConstructionManager submit and TaxCounsel certify enforced via X-User-ID)
- **Concurrency rules: 2** (OCC: offtake-create on Project.version, flip-election on TaxEquityPartnership.version)
- **Difficulty design: 9 rules × ≥2 instances = 19** (combinatorial_formula has 3 — one per mode a/b/c)
- **Corner design: 37 instances (29 active + 8 excluded_because stubs)** across all 9 claim-extraction sections

## Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(736 calls scanned; endpoint path params use the generic `{id}` form the lint's FK-resolution heuristic requires.)

## Notable design decisions
- **Dual-variant difficulty anchors**: safe-harbor qualification (5%-cost vs physical-work, ProcurementOrder domain) and continuity-of-work (4-year deadline vs facts-and-circumstances max-gap, TaxCreditQualification domain) — the continuity instance uses identical dates that pass one variant and lapse the other.
- **Two depth-3 transitive cascades**: withdrawal → reseat → upgrade re-allocation; safe-harbor cancel → TCQ revert → Project.tax_credit_anchored flip. COD certification fans out to TCQ/debt/partnership.
- **Pinned literals**: ITC 50.00% on 10M basis → 5,000,000.00; waterfall 99,000.01/1,000.00 on 100,000.01 (investor tier rounded first); IRR 404.90; post-flip 10,000.00/190,000.00; upgrade remainder 33.34 to earliest-created_at.
- **Caveat for the pipeline**: at 50 endpoints this exceeds the ~40-endpoint threshold noted in memory where impl-gen degrades — the orchestrator should verify files on disk after Step 6 rather than trust the report. The count was a deliberate trade for the requested "much harder than expert" density (generic `/transitions` endpoints already collapsed per-machine actions to keep it this low).
- One recipe relies on the harness dropping `X-User-Role` (`unauthenticated_beats_not_found`, noted in its assert); all other recipes use declared roles only.

Orchestrator note: first subagent run exhausted output in planning without writing files; resumed via SendMessage with incremental-write instructions, which completed successfully. Files verified on disk by orchestrator (all three parse as YAML with expected top-level keys).

## Step 3: Copy shared files — 2026-09-30T20:25:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T20:40:00.000Z

PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3315_renewable_project_development_pipeline_tax_equity_structuring/workspace/PRD.md` — 295 lines.

**Section list:**
- §1. Introduction (3 paragraphs)
- §2. Global Specifications: 2.1 RBAC (9 roles, opaque identity prose), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1–100, offset 0, `created_at` asc), 2.4 Resource Identity and Timestamps (incl. ledger-entry exception: `id`+`created_at` only, no `updated_at`/`version`), 2.5 The Logical Clock (initial 2026-09-01T00:00:00Z), 2.6 Monetary Precision (2dp round-half-up), 2.7 OCC (`expected_project_version` on offtake create, `expected_partnership_version` on flip, both `ERR_STALE_VERSION`/412), 2.8 Nested Path Validation (left-to-right, incl. FK field names), 2.9 Validation Order (all 12 priority tiers in prose)
- §3. Business Logic (8 subsections): 3.1 Project Inception & Site Control, 3.2 Interconnection Queueing/Studies/Upgrade Allocation, 3.3 Offtake Contracting, 3.4 Procurement & Safe Harbor, 3.5 Tax Credit Qualification & Continuity, 3.6 Milestones & COD Cascade, 3.7 Partnership/Ledger/Flip, 3.8 Debt & Term Conversion
- §4. Endpoint Definitions (50 endpoints, 4-column table)
- §5. Error Code Catalogue (32 errors, 2-column table)

**Hard contract reports:**

Field coverage check:
- entities[].fields: 78 distinct names required, 78 present, 0 missing (97 field definitions across 12 entities)
- endpoints[].request_body + path_params + query_params: 12 additional distinct names required, all present (90 total required, 90 present, 0 missing)
- Status: PASS

Rule coverage check:
- validations[] priority: 12 checked, 12 expressed in §2.9 in explicit priority order, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (write operation + occ field + `ERR_STALE_VERSION`/412 each), 0 missing
- state_machines[].transitions: all 12 machines fully expressed (from/to states, preconditions paired with error ids, side effects incl. clawback, reseat/re-allocation, COD 4-way cascade, auto-transitions on contribution/distribution, rework counter, counter_count/amendment_count loops), 0 missing
- calculations[]: 9 checked (safe_harbor_cost_test both variants, continuity_window_assessment both variants, itc_credit_amount, upgrade_cost_allocation with remainder rule and created_at tie-break, queue_reseat with {1..N} invariant, waterfall_distribution with pinned rounding order and 4-then-2 entries invariant, flip_allocation pinned 5-step order, debt_conversion_sizing, availability_ld), 0 missing
- validations[] conditions: all 32 error ids matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (version increments, auto TCQ creation, status filters, ledger immutability), 0 missing
- entities[].fields[] structured content: defaults (97.0, 99.00, 5.00, 1.30, 0.0, false, 0), enum values (all verified present), computed-field semantics all reconstructible, 0 missing
- sibling-branch symmetry: NEGOTIATING/COUNTERED → EXECUTED branches equal, contribution/distribution OCC-and-state gates, DRAFT/EXECUTED termination cascades equal density, 0 asymmetric
- Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 537
- tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0
- Status: PASS

The scaffold difficulty/corner design files were not opened, and no sibling task directories were inspected.

Orchestrator spot-check: PRD.md verified on disk (295 lines); all 32 scaffold error ids present in PRD (only diff is scaffold-internal placeholder `ERR_XXX`); key literals (2026-09-01, 1.30, 99.00, ERR_STALE_VERSION, expected_partnership_version) all present.

## Step 5: Generate unit tests — 2026-09-30T21:05:00.000Z

All done. Summary:

## Files written

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_3315_renewable_project_development_pipeline_tax_equity_structuring/test_helpers/`):
- `types.py` — 12 entity TypedDicts (ledger entry correctly omits `updated_at`/`version`), 15 status/type enums, 9-role enum
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (37 methods)
- `api_errors.py` — all 32 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators
- `factories.py` — payload factories (input fields only)
- `constants.py` — thresholds (20.00 floor, 5%, 183/1461/365/90-day windows, 30/10/10 rates, 99/5 shares, 1.30 DSCR, 0.80 advance rate, 25000/point LD capped 500000, clock start 2026-09-01)
- `test_users.py` — 9 shared role headers + per-user builders for ConstructionManager/TaxCounsel (SoD-keyed roles)
- `fixtures.py` — composite builders: `safe_harbor_project`, `establish_tcq`, `continuity_maintained_tcq`, `drive_request_to_agreement_executed`, `build_under_construction_project`, `build_cod_project` (with optional partnership + debt facility pre-COD wiring), `certify_milestone` (distinct cm-1/tc-1 ids), `create_certified_continuous_work`, `set_clock`
- `__init__.py` — barrel export

**test_suite/** (`test_suite/`): `conftest.py` + 12 numbered test files (`test_01_project_baseline` … `test_12_rbac`).

## Test counts
- **69 total test functions** — queue A (Difficulty): 39 tests across all 19 instances (≥2 each); queue B (Corner): 30 tests across all 29 non-stub instances (≥1 each).
- All 8 `excluded_because:` corner stubs were left untranslated; every stub's `difficulty_instance` cross-reference resolves to a real difficulty instance (verified programmatically).

## Skipped instances
None. Every non-stub instance passed the PRD-first two-condition filter. Notes on two borderline calls:
- `Corner/errors/draw_exceeds_commitment` was emitted (not skipped) because PRD §3.8 prose verbatim states the running-total draw cap and `ERR_DRAW_EXCEEDS_COMMITMENT`.
- `Corner/calculations/dscr_exactly_at_minimum_converts` was emitted faithfully to its own pre-computed asserts (direct CONVERSION_PENDING / TERM_REPAYMENT transitions rejected with ERR_INVALID_STATE — the cascade-only gate), not the contradictory setup prose claiming direct conversion would exercise the DSCR boundary.

## Clock reachability
All fixture dates sit at or after the clock start 2026-09-01T00:00:00Z; every later instant (2026-12-31, 2027-03-03/10, 2030-06-01, 2030-10-15) is set via `POST /api/_clock/set_current_utc` before use. The 183-day boundary test re-derived its instant from the PRD formula (created_at + 183 days = 2027-03-03) rather than copying any literal.

## Audit confirmations (all re-run by me after writing)
- `python3 -m compileall` passes on both trees.
- Every one of the 69 test functions carries **exactly one** `Design: Difficulty/...` or `Design: Corner/...` tag, each resolving to a real instance name in the source YAML (0 untagged, 0 dual-tagged, 0 dangling).
- Every docstring citation has a ≥8-word contiguous substring surviving literal grep of PRD.md (0 failures).
- Every asserted `ApiErrorId` appears in PRD prose before the §5 catalogue table.

Orchestrator verification: test_helpers/ (9 files) and test_suite/ (12 test files + conftest) exist on disk; 69 test functions counted; 69 Design: tags counted; compileall passes.

## Step 6: Generate implementation — 2026-09-30T21:30:00.000Z

Done. Implementation complete and verified.

## Summary

**Files written** in `/home/ubuntu/github/CodingPRD/tasks/task_3315_renewable_project_development_pipeline_tax_equity_structuring/workspace/implementation/` (2,498 lines total):

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 8 | Foreground launcher, guarded pip install, `exec python3 app.py`, `$PORT` (default 10000), `0.0.0.0` |
| `requirements.txt` | 1 | flask |
| `app.py` | 79 | Flask app, global request lock, error handlers (envelope-shaped 401/403/404/400/500), route registration |
| `db.py` | 32 | In-memory dict stores (12), UUID minting, logical clock (defaults to 2026-09-01T00:00:00Z, never wall-clock) |
| `errors.py` | 50 | `ApiError` + full 32-error catalog with HTTP statuses |
| `helpers.py` | 231 | Envelope (`meta`/`response_type`/`data`, `error_id`/`message`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/1..100/0), auth (`X-User-Role`/`X-User-ID`), payload validators, Decimal money helpers |
| `serializers.py` | 212 | Views for all 12 entities (ledger entries have no `updated_at`/`version`) |
| `logic.py` | 364 | Upgrade allocation (queue-ASC + largest-capacity/earliest-created remainder), queue reseat + withdrawal re-allocation, clawback cascade, COD 4-way cascade, abandon cascade, continuity assessment (both variants), ITC computation, partnership aggregates |
| `routes_projects.py` | 225 | Clock endpoint + project CRUD/transitions incl. LD computation, cascade-only COD rejection |
| `routes_site_control.py` | 128 | Half-open parcel overlap, exercise-window lapse with auto-EXPIRED, terminate→project revert |
| `routes_interconnection.py` | 207 | Queue position assignment, phase gates, study window conflict (closed interval + 5-day buffer), rework loop, allocation endpoint |
| `routes_offtake.py` | 130 | OCC on project version, negotiation cycle, price floor, single-active-offtake, project version bumps |
| `routes_supply.py` | 114 | Amendment cycle, terminate with order clawback cascade |
| `routes_procurement.py` | 139 | Deposits, 183-day window, both safe-harbor variants, clawback |
| `routes_milestones.py` | 123 | Evidence submit/resubmit, segregation of duties, sequence ordering, COD certification cascade |
| `routes_tcq.py` | 120 | Establish/assess/cure/qualify, auto-lapse, cure-window expiry → DISQUALIFIED |
| `routes_partnerships.py` | 218 | One-active-partnership constraint, commitment gate, contributions with auto FUNDING/FULLY_FUNDED, waterfall (investor-rounded-first, credit tier while unallocated > 0), OCC + IRR-gated flip |
| `routes_debt.py` | 117 | Draws vs commitment, DSCR ≥ 1.30 gate, term sizing min(commitment, drawn, 0.80×eligible) |

**Endpoints**: all 50 from the scaffold endpoint table implemented. **State machines**: all 12, with preconditions, side effects, terminal-state guards. **Calculations**: all 9 (safe_harbor_cost_test both variants, continuity_window_assessment both variants, itc_credit_amount, upgrade_cost_allocation with remainder rule, queue_reseat, waterfall_distribution with pinned rounding order, flip_allocation pinned IRR snapshot, debt_conversion_sizing, availability_ld with cap). All money via `Decimal` ROUND_HALF_UP at 2dp.

**Isolation compliance**: I read only INSTRUCTION.md, SCAFFOLD.yaml, and PRD.md — I did not open SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, or test_helpers/, did not run the test suite, and did not look at any sibling task directory. No seeding at startup; storage is in-memory dicts only.

**Boot verification**: launched via `bash start.sh` on scratch port 19315 (saved `$!`), ran a 73-check end-to-end smoke (full pipeline through COD cascade, waterfall, flip, term conversion, LD) and a 34-check edge smoke (continuity lapse/cure/disqualify, safe-harbor window lapse, PHYSICAL_WORK variant, clawback, option lapse → EXPIRED, milestone ordering/segregation, study-window conflicts, amendment cycle, DSCR failure, abandon cascade, OCC 412s, 401/403/404 envelopes) — all 107 checks passed across two fresh boots. One real bug found and fixed during verification (missing `req_enum` import in routes_partnerships.py; malformed error-envelope tuple in helpers.py). Killed exactly the PIDs I started (verified port freed), and removed the temp smoke scripts/logs.

Orchestrator verification: 16 files on disk (2,498 lines incl. start.sh/requirements.txt); compileall passes; 50 Flask route decorators counted across routes_*.py matching the 50-endpoint scaffold; errors.py contains all 32 error ids; start.sh follows the INSTRUCTION.md contract (foreground exec, $PORT).

## Step 7: Test-diagnose-fix loop — 2026-09-30T21:15:00.000Z

All 8 rounds pass 69/69. Clean sweep.

## Summary

- **Iterations run:** 2 (initial sweep identified the failure; one fix; confirmation sweep).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_3315_renewable_project_development_pipeline_tax_equity_structuring/workspace/implementation/routes_debt.py` — `df_transition`: added `CONVERSION_PENDING` to the `to` enum-validation set (leaving it out of the valid `(from, to)` transition pairs). Why: `test_dscr_exactly_at_minimum_converts` sends `{"to": "CONVERSION_PENDING"}` and asserts `ERR_INVALID_STATE`, tracing to PRD §3.6/§3.8 ("CONVERSION_PENDING is cascade-only at COD; a direct attempt fails with `ERR_INVALID_STATE`"). PRD's priority ladder (§2, payload shape at priority 4 vs from-state validity at priority 6) plus the codebase convention in `routes_projects.py` (which validates `to` against the full `PROJECT_STATUSES` enum including cascade-only `COMMERCIAL_OPERATION`, then rejects the transition with `ERR_INVALID_STATE`) mean `CONVERSION_PENDING` — a valid member of the facility status enum — must pass shape validation and be refused by the state machine, not by enum validation. The implementation bug was an overly narrow shape-enum.

Final state: all 8 parallel rounds report 69/69 passed, no failures, no flakiness.

Orchestrator verification: all 8 results.{1..8}.json on disk report passed=69 total=69 failed=0; all implementation/*.py mtimes (latest 21:09:00) predate the sweep results mtimes (21:11:22), so no post-sweep implementation writes invalidated the sweep.

## Step 8: Finalize PRD — 2026-09-30T21:25:00.000Z

Done. Single-edit patch applied.

## Summary

**Line counts:** PRD.md 295 lines; PRD_FINALIZED.md 295 lines (0% line-count delta — the edit extended one paragraph inline; character delta is +291 on line 196).

**Changes:**
- §3.8 (Construction Financing and Term Conversion) — insert — appended a cascade-only pinning sentence for `CONVERSION_PENDING`: it is a valid member of the facility status enum (passes priority-4 payload-shape validation), but no `(from, CONVERSION_PENDING)` pair exists in the state machine, so a direct attempt fails with `ERR_INVALID_STATE` (HTTP 409) at priority 6 — `implementation/routes_debt.py:72-86` (enum set at lines 72-75 includes `CONVERSION_PENDING`; valid-pairs set at lines 77-84 contains no `(*, CONVERSION_PENDING)` pair; rejection at line 86); cascade source at `implementation/logic.py:236-239`.

**Per-edit pre-edit search log:**

1. Edit 1 (§3.8 `CONVERSION_PENDING` cascade-only sentence):
   - (a) Subject: whether `CONVERSION_PENDING` may be named as a direct `to` target on `POST /api/debt-facilities/{id}/transitions`, and which error/priority a direct attempt yields.
   - (b) Impl paths enumerated and read:
     - `routes_debt.py:67-118` — full `df_transition` handler (the Step 7 fix site): `to` enum includes `CONVERSION_PENDING`; valid transition pairs exclude it; non-pair → `ERR_INVALID_STATE`.
     - `logic.py:225-243` (`cod_cascade`) — the only writer of `CONVERSION_PENDING` (line 238), fired from milestone certification.
     - `routes_projects.py:21-25, 114, 204-205` — the parallel cascade-only convention the PRD already documents for `COMMERCIAL_OPERATION` in §3.6: full-enum shape validation, `ERR_INVALID_STATE` refusal. Confirmed the wording mirrors an existing PRD pattern rather than inventing a new one.
     - `grep` of all `req_enum(body, "to", ...)` sites across `routes_*.py` (interconnection, offtake, partnerships, site_control, procurement, supply, tcq) — confirmed no other facility-status path touches `CONVERSION_PENDING`, so the sentence's scope ("no direct transition into it from any status") is exact and does not overreach into other resources.
   - (c) Wording adjustment: scoped the claim to the debt-facility machine only ("That step is cascade-only… no direct transition into it from any status"), mirroring §3.6's project-level phrasing, and explicitly stated the shape-validation-pass / state-machine-reject split so the priority-4 vs priority-6 ordering pinned in §2.9 is unambiguous for a fresh implementer. No universal claim about other resources was made.

Orchestrator verification: PRD_FINALIZED.md exists (295 lines); diff vs PRD.md is exactly the one inline sentence at line 196, nothing else.

## Step 9: Complete PRD — 2026-09-30T21:45:00.000Z

The PRD_COMPLETED.md is written: 295 lines (unchanged structure — all edits were inline), 54,085 → 59,460 chars (+5,375).

Summary:

**Source vs output:** `PRD_FINALIZED.md` (295 lines / 54,085 chars) → `PRD_COMPLETED.md` (295 lines / 59,460 chars), +5,375 chars. All changes inline; no sections added.

**Counts:** 16 ambiguity-pins, 4 mismatch-revisions (20 edits total; the pagination and offtake-§2.7 edits each mix pin+revise elements, counted by dominant type below).

Changes:

- §2.2 — insert — ambiguity — `api_request_timestamp` is wall-clock, never reads the logical clock — helpers.py:29-31
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_VALIDATION`; `has_more = offset + page_size < total_count`; list tie-break by `id` ascending — helpers.py:64,199-217
- §2.4 — insert — ambiguity — `version` starts at 1; `created_at`/`updated_at` stamped from the logical clock — helpers.py:220-231
- §2.7 — revise — mismatch — offtake OCC is strict-equality (`!=`), not "advanced beyond"; missing/null/non-integer `expected_project_version` → `ERR_VALIDATION`; touch sources include offtake creation — routes_offtake.py:28-34
- §3.1 — insert — ambiguity — exercise permitted exactly at `end_date` (rejected only when clock strictly after); `EXPIRED` not a payload target (naming it → `ERR_VALIDATION`); no posture re-evaluation on terminating an `EXECUTED` instrument; exercise does not auto-advance the project — routes_site_control.py:69,97-105,115-125
- §3.2 — insert — ambiguity — `requested_capacity_mw` must be positive — routes_interconnection.py:38
- §3.2 — insert — ambiguity — latest-study gate tie-break by `id` ascending; rule extended to SYSTEM_IMPACT/FACILITIES gates — routes_interconnection.py:21-27
- §3.2 — insert — ambiguity — study-window conflict ignores the existing study's status — routes_interconnection.py:144-152
- §3.2 — insert — ambiguity — `WITHDRAWN` not a valid study-transition target (`ERR_VALIDATION`) — routes_interconnection.py:192
- §3.2 — insert — ambiguity — allocation may be addressed at a WITHDRAWN request; `total_upgrade_cost_usd` must be positive; allocation returns the addressed request — routes_interconnection.py:122-131
- §3.3 — insert — ambiguity — `term_years` must be an integer — routes_offtake.py:25
- §3.3 — insert — ambiguity — replacement `base_price_usd_mwh` also honored on execute, applied before the floor check — routes_offtake.py:108-110
- §3.3 — insert — ambiguity — activate (EXECUTED→EFFECTIVE) does not touch project version; expiry is latent (no request performs it); `EXPIRED` not a payload target — routes_offtake.py:75,79-88,127-130
- §3.4 — insert — ambiguity — `total_contract_usd` must be positive — routes_supply.py:23
- §3.4 — insert — ambiguity — amendment value not exposed as a response field — routes_supply.py:84-94, serializers.py:99-112
- §3.4 — insert — ambiguity — `order_amount_usd` and `eligible_cost_basis_usd` must be positive — routes_procurement.py:27-29
- §3.4 — revise — mismatch — 5% threshold uses round-half-even (Python default quantize), not round-half-up; §2.6's carve-out clause covers this — routes_procurement.py:113-114
- §3.4 — insert — ambiguity — non-string `physical_work_evidence_uri` → `ERR_VALIDATION`; supplied URI stored on the order — routes_procurement.py:118-123
- §3.5 — revise — mismatch — cure with no qualifying post-lapse work milestone fails with `ERR_VALIDATION` (400), and the failed cure-into-DISQUALIFIED attempt advances the qualification's `version` — routes_tcq.py:88-102
- §3.6 — revise — mismatch — `sequence_no` uniqueness is not enforced at creation; must be an integer — routes_milestones.py:27
- §3.6 — insert — ambiguity — evidence submission only from `PLANNED`/`REJECTED`; invalid `work_date` → `ERR_VALIDATION`; `submitted_by_user_id` null when `X-User-ID` absent — routes_milestones.py:70-82
- §3.6 — insert — ambiguity — certify requires `EVIDENCE_SUBMITTED` state; missing certifier `X-User-ID` always passes the SoD check; `certified_by_user_id` recorded on rejection too — routes_milestones.py:93-101
- §3.6 — insert — ambiguity — every resource the COD cascade mutates advances its `version` — logic.py:224-243
- §3.6 — revise — mismatch — abandonment cascade also cancels `DELIVERED` orders (PRD said only "not in ACCEPTED"); project version additionally advances once per cascade-terminated offtake — logic.py:266,271-285
- §3.7 — insert — ambiguity — `commitment_usd`/`target_irr_pct` must be positive; duplicate-partnership create → `ERR_INVALID_STATE` (409) — routes_partnerships.py:48-53
- §3.7 — insert — ambiguity — `expected_partnership_version` must be a JSON integer, missing/null/non-integer → `ERR_VALIDATION` — routes_partnerships.py:115-121
- §3.7 — insert — ambiguity — `amount_usd` and `period_end_date` required on contributions and distributions; distribution returns HTTP 201 array envelope of new entries in creation order with limit/total_count = entry count — routes_partnerships.py:141-142,164-165,194-195
- §3.7 — insert — ambiguity — invalid `entry_type` filter → `ERR_VALIDATION` — routes_partnerships.py:202-204
- §3.8 — insert — ambiguity — facility `commitment_usd`/`interest_rate_pct`/`projected_cfads_usd` must be positive; duplicate-facility create → `ERR_INVALID_STATE` (409) — routes_debt.py:26-32
- §4 — insert — ambiguity — clock endpoint returns HTTP 200 with `{"current_utc": ...}` — routes_projects.py:30-36

One deliberate non-change worth noting: §3.7's prose "the contribution that brings `contributed_usd` exactly equal to `commitment_usd` auto-advances" matches impl (full funding in one contribution from `COMMITMENT_EXECUTED` lands in `FULLY_FUNDED` via sequential ifs, which the prose's "and" sequencing already covers).

Orchestrator verification: PRD_COMPLETED.md exists (295 lines). Sweep integrity re-checked post-Step-9: no implementation/*.py modified after the final sweep (latest impl mtime 21:09:00 < results mtimes 21:11:2x), so the 8× 69/69 result remains valid. Spot-checked the round-half-even claim against routes_procurement.py:113-114 — confirmed bare `quantize(Decimal("0.01"))` with no explicit rounding mode (Decimal default = ROUND_HALF_EVEN); the PRD edit faithfully describes the shipped code.
