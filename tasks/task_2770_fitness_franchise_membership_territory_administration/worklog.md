# Worklog — task_2770_fitness_franchise_membership_territory_administration

## Step 1: Create task directory — 2026-09-04T18:46:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2770_fitness_franchise_membership_territory_administration` and its `workspace/` subdirectory. Index 2770 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T20:31:00.000Z

All three scaffold artifacts are complete and lint-clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    71
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     82
  Calls scanned (§1.8+§1.9):  1130

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `tasks/task_2770_fitness_franchise_membership_territory_administration/`):
- `SCAFFOLD.yaml` — 2896 lines / 166 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1892 lines / 122 KB
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5364 lines / 320 KB

SCAFFOLD.yaml (§1.0–§1.7), domain `fitness-franchise-membership-territory-administration`, prefix `/franchise`:
- 15 entities: Franchisee, Territory, Club, RelocationRequest, MembershipPlanTemplate, Promotion, Member, CorporateAccount, MembershipAgreement, TransferRequest, GuestUsageEvent (append-only), UsageSettlement, BillingEvent (append-only), RoyaltyReport, FacilityInspection
- 14 state machines, 2 §1.2.1 concurrency rules (`agreement-create-stale-club` / `expected_club_version` → ERR_STALE_CLUB_VERSION; `transfer-create-stale-agreement` / `expected_agreement_version` → ERR_STALE_AGREEMENT_VERSION)
- 11 calculations, 15-rung validation priority ladder, 71 endpoints (41 POST + 30 GET), 53 errors, 6 roles (BrandAdministrator, FranchiseOwner, ClubManager, ComplianceAuditor, BillingPartner, Member)
- complexity profile: compliance/audit + temporal windowing, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, graph topology, cyclic state machines, segregation-of-duties role model, immediate consistency
- Neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears in it

§1.8 (18 instances = 9 rule families × 2): `dual_variant_calc` (royalty reported vs verified basis; inspection standard vs accelerated refresh cycle), `combinatorial_formula` (per-component dues rounding; rebate tier keyed on net-before-rebate), `non_linear_state_machine` (relocation CHANGES_REQUESTED loop to the revision limit; independent agreement_status / dues_status dimensions), `transitive_cascade` (inspection → club → franchisee → promotion withdrawal; one delinquent agreement → club watch → compliance score), `priority_pair_validation_conflict` (safety gate over price floor; discount cap over promo window), `boundary_precision_check` (zero-km territory slack; rebate tier at the exact 50 000-cent floor), `cross_entity_state_dependency` (transfer gated on receiving-club compliance; promotion gated on franchisee probation), `resource_temporal_overlap` (radial buffer rejecting disjoint circles; 7-day promo cooling gap both sides), `compensating_invariant` (settlement post/reverse zero-sum ledger; corporate allocate/recall conserving lifetime funded).

§1.9 (98 instances across all nine claim-extraction-guide sections; 82 with full test recipes, 16 `excluded_because` stubs citing a §1.8 instance by name):
entities 13 · state_machines 15 (2 stubs) · calculations 14 (4) · validations 11 (3) · endpoints 6 · errors 25 (5) · rbac 7 · cross_cutting_complexity_layers 5 (2) · consistency_model 2.

Verified invariants: instance names unique across the union of both design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name; no stub carries a `test_recipe` and no non-stub lacks one; all 53 §1.6 error codes are referenced by at least one recipe (the last two, ERR_STALE_AGREEMENT_VERSION and ERR_COLLECTIONS_THRESHOLD_NOT_MET, were closed by the cross-cutting OCC and 59-vs-60-day collections-threshold corners). No sibling task directory was read.

Orchestrator verification: all three files present and non-trivial; `grep -rn "harder than expert"` over all three returned no hits, so the Step-2-only difficulty directive did not leak into the scaffold's `scenario:` key (a known failure mode).

## Step 3: Copy shared files — 2026-09-04T20:31:30.000Z

Copied `INSTRUCTION.md` (1424 bytes) to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T20:49:00.000Z

The PRD is complete and verified.

**Output:** `workspace/PRD.md` — **469 lines**, built incrementally (one `Write` plus heredoc appends), ending cleanly at the last row of the §5 error table.

**Section list**
- `# Fitness Franchise Membership & Territory Administration API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Role-Based Access Control, 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, including its two `####` sub-headings), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties and Immutable Ledgers, 2.6 Nested Retrieval and the Order of Validation, 2.7 Optimistic Concurrency Control, 2.8 Money, Rounding and Conserved Quantities, 2.9 State Health-Club Statutes, 2.10 Cascade Discipline and Franchisee Standing
- `## 3. Business Logic & Workflows` — 3.1 The Franchise Spine (franchisees, territories, clubs, relocation), 3.2 Plan Standardization and Promotional Pricing Governance, 3.3 Signing a Membership Agreement, 3.4 The Dues Ledger, Delinquency and Collections, 3.5 Freezes, Cancellation Rights and Settlement, 3.6 Moving a Membership Between Clubs, 3.7 Cross-Club Guest Usage and Inter-Club Settlement, 3.8 National Accounts and Corporate Revenue Allocation, 3.9 Facility Inspections, Franchisee Standing and Royalty Reporting
- `## 4. API Endpoints` (4-column table)
- `## 5. Error Codes` (2-column table)

**Coverage confirmation (machine-checked against SCAFFOLD.yaml)**
- All **71** §1.5 endpoints appear in the §4 table (paths matched programmatically, 0 missing); each row carries method, backticked path, description and the exact authorized-role list.
- All **53** §1.6 errors appear in the §5 table, and independently **all 53 error IDs also appear in the §1–§3 prose** (0 missing) — every error is raised by a described rule, not just catalogued.

**Hard Contracts**
- **Contract 1 — Field-Name Coverage: PASS.** 140 required identifiers (132 `entities[].fields[].name` plus the 8 endpoint-only inputs `agency_reference`, `current_utc`, `decision`, `expected_agreement_version`, `expected_club_version`, `limit`, `note`, `offset`); all 140 present verbatim in backticks, 0 missing. Extra: all 56 entity enum values and all state-machine states (initial/terminal/from/to) also appear backticked, 0 missing.
- **Contract 2 — Rule Coverage: PASS.** All 15 validation bands are enumerated in §2.6 with their error IDs and `applies_to` scopes; both `concurrency_rules` are given full OCC framing in §2.7 (`expected_club_version`/`ERR_STALE_CLUB_VERSION`/412 and `expected_agreement_version`/`ERR_STALE_AGREEMENT_VERSION`/412); all 11 calculations are translated as reconstructable prose with pinned step order (notably the settlement waterfall keying `rebate_pct` only on `net_before_rebate_cents`, the corporate-allocation floor-division plus one-cent remainder ordered by weight DESC then `created_at` ASC, `refresh_pts` rounded to an integer *before* weighting, and royalty sum-then-round); every state-machine transition, cascade link and endpoint side effect (including `version` increments and cross-entity counter recomputations) is stated.
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 begin with `/`, contain a `/`, or are bare/prefixed HTTP methods (the three `POST` grep hits inside §3 are the state name `POSTED`).

Two isolation constraints were honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or grepped, and no sibling task directory was read.

Judgement calls flagged by the generator: the scaffold's franchisee-list description says "newest first" but the skill's fixed contract mandates `created_at` ascending, so the PRD states ascending and the §4 row omits the phrase; `signed_on` is described as client-stated but always pinned to the logical clock; and three preconditions with no scaffold-declared error ID were assigned the closest existing IDs — plan-template publish floor check to `ERR_PRICE_BELOW_FLOOR`, transfer-completion home-club drift to `ERR_HOME_CLUB_MISMATCH`, and a still-deficient franchisee reinstatement to `ERR_FRANCHISEE_ON_PROBATION`.

Orchestrator truncation check (known generator failure mode): `wc -l` = 469; `tail -20` ends on the final `ERR_NO_ELIGIBLE_FRANCHISEE | 409` row of the §5 table — a real section boundary, not mid-sentence. `## ` headings enumerate §1–§5 in order. Grep for `harder than expert` / `expert level` / `scaffold` in PRD.md returned no hits, so the difficulty directive did not reach the PRD. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T23:35:00.000Z

Both queues are now fully translated and the suite is complete.

## Output (all at the TASK ROOT, nothing under `workspace/`)

`test_helpers/` (Stage 1, unchanged this session)

| file | lines |
|---|---|
| `__init__.py` | 38 |
| `api_client.py` | 385 |
| `api_errors.py` | 142 |
| `assertions.py` | 446 |
| `constants.py` | 106 |
| `factories.py` | 342 |
| `fixtures.py` | 862 |
| `test_users.py` | 68 |
| `types.py` | 445 |

`test_suite/`

| file | lines |
|---|---|
| `conftest.py` | 51 |
| `test_01_royalty_report_dual_basis.py` | 182 |
| `test_02_inspection_refresh_cycle_variants.py` | 152 |
| `test_03_agreement_pricing_composition.py` | 153 |
| `test_04_usage_settlement_waterfall.py` | 324 |
| `test_05_relocation_review_cycle.py` | 261 |
| `test_06_agreement_dues_dimensions.py` | 282 |
| `test_07_franchisee_standing_cascade.py` | 286 |
| `test_08_validation_precedence.py` | 281 |
| `test_09_territory_grant_protection.py` | 149 |
| `test_10_membership_transfer_compliance_gate.py` | 175 |
| `test_11_promotion_window_cooling_gap.py` | 190 |
| `test_12_corporate_pool_conservation.py` | 180 |
| `test_13_entity_shapes_and_defaults.py` | 648 |
| `test_14_state_machine_edges.py` | 906 |
| `test_15_calculation_corners.py` | 958 |
| `test_16_validation_corners.py` | 690 |
| `test_17_endpoint_surface.py` | 661 |
| `test_18_error_catalog_paths.py` | 801 |
| `test_19_error_catalog_money_and_ops.py` | 750 |
| `test_20_role_boundaries.py` | 642 |
| `test_21_concurrency_and_consistency.py` | 496 |

Total 12,052 lines across both directories.

## Coverage

- **272 tests**, 100 distinct `Design:` tags = 18 difficulty + 82 corner instances.
- **Queue A (§1.8 difficulty): 18/18**, minimum 3 tests per instance (target was ≥2). By rule id: dual_variant_calc 10, cross_entity_state_dependency 9, priority_pair_validation_conflict 9, transitive_cascade 9, boundary_precision_check 8, combinatorial_formula 8, compensating_invariant 8, non_linear_state_machine 8, resource_temporal_overlap 8.
- **Queue B (§1.9 corner): 82/82 non-stub**, minimum 1 test per instance. By section: errors 20 instances / 44 tests, calculations 10 / 34, state_machines 13 / 27, validations 8 / 22, entities 13 / 21, endpoints 6 / 20, rbac 7 / 15, cross_cutting_complexity_layers 3 / 7, consistency_model 2 / 5.
- The 16 `excluded_because:` corner stubs were never translated (the audit resolves every tag against the non-stub instance set, so a stub tag would fail).
- **PRD-first filter: zero instances skipped.** Every non-stub instance had verbatim PRD coverage that uniquely derives its asserted outcome.

## Verification

- `/tmp/check_citations.py`: `all citations and tags OK` — every test has exactly one `Design:` tag resolving to a real non-stub instance, exactly one `PRD <section>: "…"` block, each span >=8 normalized words and verbatim in the normalized PRD.
- `/tmp/check_labels.py`: `label mismatches 0` (one label bug caught and fixed: a §3.3 span was labelled 3.2).
- `python3 -m compileall` clean; `pyflakes` clean over `test_suite/*.py` (removed one unused `read_agreement_version` import left in `test_18`).
- No `skip` / `skipif` / `xfail` markers, no docstring mentions "scaffold", no `__pycache__` left behind, and `find workspace -name test_helpers -o -name test_suite` returns nothing.
- Note: the suite was never executed — the implementation under `workspace/implementation/` was left unread per the isolation constraint, so validation here is static only.

Orchestrator verification: `find workspace` for stray `test_helpers`/`test_suite` returned nothing (a known Step 5 failure mode); both directories are at the task root. `Design:` tag census across `test_suite/`: 77 Difficulty + 195 Corner = 272 tags, matching the reported test count exactly.

## Step 6: Generate implementation — 2026-09-04T23:35:30.000Z

The implementation is complete, boots cleanly from a fresh process, and answers requests.

## Files written
All under `workspace/implementation/`:

| File | Lines | Role |
|---|---|---|
| `start.sh` (executable) | 10 | guarded `pip install`, `exec python3 app.py`, honours `PORT` (default 10000) |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 67 | app factory, 5 blueprints, `ApiError`/404/405/500 envelope handlers, binds `0.0.0.0:$PORT` |
| `config.py` | 83 | every pinned domain constant (statute table, rates, thresholds, caps, state sets) |
| `errors.py` | 122 | 52-code catalog with HTTP status + default messages |
| `store.py` | 135 | in-memory `Store` (15 dicts), logical clock, date/ISO helpers, common/ledger field factories |
| `envelope.py` | 58 | `meta`/`response_type`/`data` envelope, `req_` request ids, pagination meta |
| `auth.py` | 33 | header authentication, role authorization, ownership guard |
| `validate.py` | 279 | band-4 schema layer (typed getters, enums, dates, months, pagination, filters) |
| `calc.py` | 203 | the 11 pinned calculations with `Decimal`/ROUND_HALF_UP at exactly the PRD's rounding points |
| `cascade.py` | 237 | ledger projection, club counters, franchisee compliance chain, member/corporate recompute |
| `helpers.py` | 104 | per-family 404 lookups, shared state gates, list plumbing |
| `routes/spine.py` | 403 | clock, franchisees, territories, clubs, relocation requests |
| `routes/plans.py` | 370 | plan templates, promotions, members, corporate accounts |
| `routes/memberships.py` | 519 | agreements, cancellation settlement, dues ledger, transfers |
| `routes/usage.py` | 194 | guest usage batches, usage settlements |
| `routes/compliance.py` | 266 | royalty reports, facility inspections |

3084 lines total. Every file was written in chunks and verified with `wc -l` + `ast.parse`.

## Endpoint coverage
**71 (method, path) pairs — exact parity with the PRD §4 table** (41 POST, 30 GET), verified programmatically against the table: zero missing, zero extra.

## Smoke tests
Three scripted end-to-end suites (~110 assertions) against a live server on port 21473/21851, killed only by that port's PID — **all pass, 0 failures, no 500s, no tracebacks**. Covered: envelope/meta shape and `req_` id, pagination bounds, all six roles, ownership 403s, all four 404 families, both OCC 412s, encroachment geometry, territory occupancy, the full relocation lifecycle with revision limit and SoD, statute notice limit at NY, floor gate, promotion cap/cooling-gap/withdrawal-on-probation, pricing three-component rounding, first-payment activation, FIFO ageing to PAST_DUE/DELINQUENT/collections/write-off/sticky escape, both cancellation branches with the ETF cap, cross-franchise transfer with fee row and dual-club recompute, the settlement waterfall with `sum settlement_ledger_cents == 0` and clean reversal, corporate fund/allocate/recall conservation, inspection scoring on both refresh cycles with club suspension/recovery, and reinstatement.

## Two bugs found and fixed during smoke
- `routes/memberships.py` read `statute["prorates"]` and `statute["cross_state_allowed"]`; the real `config.STATE_STATUTES` keys are `prorate_on_cancel` and `cross_state_transfer_allowed` (transfer creation was a 500).
- The catch-all handler now prints the traceback to stderr so a future 500 is diagnosable from the server log instead of being silently swallowed.

## Notes on spec interpretation
Storage is in-memory only (no sqlite, no disk, no `/tmp`), nothing is seeded — a fresh boot returns `total_count: 0` for all 14 collections and a clock of `2026-08-01T00:00:00Z`. Validation follows §2.6's 15-band precedence globally, which required ordering body-schema checks (band 4) ahead of path-record existence lookups (band 5) on every sub-action endpoint. Ownership (band 3) resolves its record silently so a missing record still yields the band-5 404. `request-changes` does not enforce SoD (PRD band 8 guards exactly two operations); `waive-remediation` checks SoD before `ERR_REMEDIATION_NOT_REQUIRED`. I did not read `test_helpers/`, `test_suite/`, either `SCAFFOLD_*_DESIGN.yaml`, or any sibling task directory.

Orchestrator note: Steps 5 and 6 were launched close together rather than in one message; physical isolation held anyway — the impl generator finished before most of `test_suite/` existed and reports never reading it, and the test generator reports never reading `implementation/`.

## Step 7: Run tests and iterate — 2026-09-04T23:10:30.000Z

Loop complete — clean 8-round parallel sweep.

## Summary

**Iterations run:** 2 (iteration 1: 265/272 in all 8 rounds, 7 deterministic failures, zero flakiness; iteration 2: clean).

**Tests deleted (2)**

- `test_05_relocation_review_cycle.py::test_submission_is_refused_when_the_proposal_sits_inside_the_protection_buffer` — **STEP 1b, two-reader collapse.** PRD §3.1's submit paragraph says submission "computes and **stores** the proposed circle's clearance into `encroachment_km`" and names only `ERR_RELOCATION_REVISION_LIMIT` / `ERR_INVALID_RELOCATION_STATE` as submit refusals; the decide paragraph then says an approval-time negative clearance "is refused with `ERR_TERRITORY_ENCROACHMENT` even though the request passed at submission time." §2.6 band 12 lists "submitting a relocation request" among the eight operations that band guards, but the band holds seven codes and is fully satisfied by the revision-limit gate alone. Both "submit gates on clearance" and "submit merely records clearance, approval is the only gate" are PRD-faithful. Drove from scaffold rule `Difficulty/resource_temporal_overlap/territory_radial_buffer_rejects_physically_disjoint_circles_on_relocation`.
- `test_09_territory_grant_protection.py::test_the_first_grant_of_all_stores_a_null_clearance` — **STEP 1b, COMPUTED-FIELD SILENCE.** PRD names `encroachment_km` as a stored/response-visible attribute only on `RelocationRequest` (§3.1 and the `GET /franchise/relocation-requests/{id}` row). For a territory grant the clearance is described purely as a pre-write measurement ("Before the grant is written, the server measures..."), the created-state sentence lists only `RESERVED` + `relocation_count` 0, and the territory GET row promises only "its current centre, `protected_radius_km` and `relocation_count`". Whole test body was those two assertions, so nothing survived. Scaffold rule `Difficulty/boundary_precision_check/territory_protection_slack_of_exactly_zero_km_is_accepted`.

**Partial-coverage splits (STEP 1c) — same COMPUTED-FIELD SILENCE, covered assertions kept**

- `test_09::test_a_circle_at_exact_tangency_is_granted_with_a_clearance_of_zero` — dropped `granted["encroachment_km"] == 0.0`; kept the 201, `RESERVED`, `protected_radius_km`, `relocation_count` assertions that carry the PRD rule (a tangent circle is accepted).
- `test_09::test_a_second_circle_for_the_same_operator_may_sit_right_on_top_of_the_first` — dropped `second["encroachment_km"] is None`; replaced with the PRD-covered `protected_radius_km` / `relocation_count` created-state assertions, so the test still proves self-overlap is granted.
- Removed the now-unused `read_territory` import from `test_09`.

**Fixes applied to `test_suite/` (3)**

- `test_20_role_boundaries.py`, two assertions in `test_one_member_cannot_tear_up_another_members_contract` and `test_the_holders_own_cancellation_unwinds_the_contract_inside_the_cooling_off_window` — the tests read `agreement["contract_status"]`, which is PRD *prose* wording ("the contract dimension"); PRD §3.3 names the field verbatim as `agreement_status`. Renamed to `agreement_status` — strictly more PRD-faithful, no assertion weakened.
- `test_17_endpoint_surface.py::test_the_flag_is_the_only_difference_and_it_costs_one_and_a_half_percent` — **fixture-precondition bug.** The test called `_membership_at_a_club_with_a_sibling()` twice, and that helper hardcodes a franchise whose home territory sits at (34.0, −118.0) r=5.0. The second call therefore asked for a *different* franchisee's circle directly on top of the first's, which the PRD-faithful implementation correctly refuses (`ERR_TERRITORY_ENCROACHMENT`, clearance −10.5) — a setup error, not an impl defect. Rewrote it to sign a second member's agreement at the *same* club on the *same* published template with `multi_club_access=True`, so the flag really is the only difference. All four asserted values (0 / 4500 / 68 / 4432) are unchanged and still trace to PRD §3.3's round-each-component rule.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:** none. Every one of the 7 failures traced to the test artifact; verified positively that the implementation is PRD-correct on both contested points — `routes/spine.py` carries `encroachment_km` only on the relocation-request record (lines 270, 315), never on `Territory`, and `routes/memberships.py` uses `agreement_status` throughout.

**Final sweep, per round (quoted from `workspace/implementation/results.$i.json`)**

| round | passed | failed | errors | total |
|---|---|---|---|---|
| 1 | 270 | 0 | 0 | 270 |
| 2 | 270 | 0 | 0 | 270 |
| 3 | 270 | 0 | 0 | 270 |
| 4 | 270 | 0 | 0 | 270 |
| 5 | 270 | 0 | 0 | 270 |
| 6 | 270 | 0 | 0 | 270 |
| 7 | 270 | 0 | 0 | 270 |
| 8 | 270 | 0 | 0 | 270 |

Notably, iteration 1 produced *identical* 7-test failure sets in all 8 rounds — no load-induced timeout or connection noise appeared in either sweep, so no re-run was needed to separate flakiness from real defects. `worklog.md` was not touched (mtime still 22:39, pre-dating my first sweep).

Orchestrator verification (independent of the subagent's report): all 8 `results.$i.json` present and each reads `270 / 270`; the earlier baseline set read `265 / 272` in all 8 rounds, matching the reported iteration-1 signal. Note: the wall-clock timestamps in Steps 1–6 above were written from an estimated clock and run slightly ahead of the host clock (`date -u` at the clean sweep was 2026-09-04T23:09:53Z); step ordering is unaffected.

Step 8 skip condition NOT met (2 deletions + 3 `test_suite/` fixes), so Step 8 will run.

## Step 8: Finalize PRD — 2026-09-04T23:18:00.000Z

Done. `PRD_FINALIZED.md` written with three surgical inline edits.

**Line counts:** PRD.md 469 lines / 109,191 bytes → PRD_FINALIZED.md 469 lines / 110,124 bytes. Line delta 0 (+0.0%); byte delta +933 (+0.85%). 3 lines modified (lines 120, 169, 175).

**Changes**

- §3.1 (line 175, relocation submit paragraph) — insert — states that submission only records the measured clearance: a negative clearance is stored in `encroachment_km` as computed, the request still moves to `SUBMITTED`, no `ERR_TERRITORY_ENCROACHMENT` at submit; protection is enforced only at the approval gate — `implementation/routes/spine.py:279-319` (no gate; `record["encroachment_km"] = ...`, `record["status"] = "SUBMITTED"` unconditionally) vs. `spine.py:351-354` (approval gate).
- §3.1 (line 169, grant/measurement paragraph) — insert — states that the grant-time clearance is a pre-write check only and is never persisted on a `Territory` (no clearance attribute on creation or after a relocation rewrites geometry); `encroachment_km` belongs to `RelocationRequest` alone — `implementation/routes/spine.py:110-126`, `spine.py:355-361`, `spine.py:262-274`.
- §2.6 band 12 (line 120) — revise — added a scoped parenthetical that for "submitting a relocation request" the band contributes only `ERR_RELOCATION_REVISION_LIMIT`, since submission never checks territory protection. This is where Step 7's two-reader ambiguity originated — `implementation/routes/spine.py:296-301`.

**Per-edit pre-edit search log**

1. *Submit-time encroachment gate.* (a) Subject: which relocation operations enforce territory protection, and what submit stores/returns. (b) Enumerated: `grep -rn "ERR_TERRITORY_ENCROACHMENT|encroachment_clearance"` across all of `implementation/` — exactly two gates exist (`spine.py:112-113` territory grant, `spine.py:353-354` relocation approve); read `submit_relocation` (`spine.py:279-319`), `_clearance_for` (`spine.py:230-237`), `_candidate_territories` (`spine.py:91-95`), `create_relocation` (`spine.py:240-276`), `decide_relocation` (`spine.py:336-373`), `calc.encroachment_clearance` (`calc.py:171`), `errors.py:48,104`. (c) Adjustment: I deliberately did **not** write "the only refusals at submission are the revision-limit and state gates" — submit still raises auth, ownership (`require_owner`), schema (`v.opt_decimal`/`req_radius`), and not-found errors. Narrowed the claim to the encroachment code only, and phrased the storage clause as "stored exactly as computed" so it also covers the null case (empty candidate set) already described upstream.

2. *Non-persistence of clearance on `Territory`.* (a) Subject: every place a territory record is created, mutated, or serialized, and every place a clearance value is persisted. (b) Enumerated: `create_territory` field dict (`spine.py:115-126`), the relocation-approve territory rewrite (`spine.py:355-361` — sets `center_lat`/`center_lng`/`protected_radius_km`/`relocation_count`, no clearance), `open_club`'s `RESERVED → ACTIVE` flip (`spine.py:207-210`), `read_territory`/`list_territories` (`spine.py:129-138`), `store.common_fields`/`touch`/`public` (`store.py:103-131` — `public()` emits every non-underscore key, so absence in the record means absence in responses), and both `encroachment_km` writes (`spine.py:270`, `315`, relocation-request only). (c) Adjustment: added "not on creation, not when a later relocation rewrites its geometry" so the sentence also covers the approve path Step 7 never exercised, and said "no clearance value appears in a territory's created or retrieved representation" rather than naming a specific absent field on the GET row, avoiding a claim about the response envelope that `public()` derives structurally.

3. *§2.6 band 12 op list.* (a) Subject: which band-12 codes each listed operation can actually emit, specifically for submit. (b) Enumerated: `submit_relocation` (`spine.py:296-301`) — only `ERR_RELOCATION_REVISION_LIMIT` from that band (state error is band 7); confirmed the band's other codes are raised elsewhere — `ERR_TERRITORY_ENCROACHMENT` (`spine.py:113`, `354`), `ERR_TERRITORY_OCCUPIED` (`spine.py:165`), `ERR_RELOCATION_PENDING` (`spine.py:203`, `259`), and the promotion/settlement/royalty codes in `routes/plans.py`, `routes/usage.py`, `routes/compliance.py` (grepped, untouched by this wording). (c) Adjustment: scoped the parenthetical strictly to the submit entry with an em-dash aside so the other seven listed operations keep their original unqualified meaning; the eight-operation count and every code name in the band are left verbatim.

No PRD edits were made for the two Step 7 test-artifact fixes (`agreement_status` rename — PRD §3.3 line 211 already names the field verbatim, so the tests were simply wrong; and the `test_17` fixture-precondition bug — the old helper reuse produced a genuine `ERR_TERRITORY_ENCROACHMENT` that the PRD already determines).

Orchestrator note: `PRD_FINALIZED.md` is present and NOT byte-identical to `PRD.md` (109,191 → 110,124 bytes), so the pass genuinely ran.

Orchestrator decision for Step 9: the implementation is 3,084 lines across 17 modules, which a single scan subagent has historically failed to cover (the known failure mode is `PRD_COMPLETED.md` coming back byte-identical to its source because the scan never really walked the code). Step 9 will therefore be run as THREE SEQUENTIAL passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module: pass 1 = core/global layer + `routes/spine.py` (and it alone does the `cp`); pass 2 = `routes/plans.py` + `routes/memberships.py`; pass 3 = `routes/usage.py` + `routes/compliance.py` + `calc.py` + `cascade.py`. Passes are strictly sequential so they cannot clobber each other's edits.

## Step 9: Complete PRD — 2026-09-04T23:55:00.000Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place. 84 patches total (22 + 38 + 24).

### Pass 1 of 3 — core/global layer + `routes/spine.py`

**`cp` confirmation:** performed `cp PRD_FINALIZED.md PRD_COMPLETED.md` as Step 0.

**Line/char counts:** `PRD_FINALIZED.md` 469 lines / 110124 bytes → `PRD_COMPLETED.md` 469 lines / 115590 bytes. Char delta **+5438**.

**Counts:** ambiguity-pins **20**, mismatch-revisions **2**.

**Files scanned (all of the partition, exhaustively):** `app.py`, `config.py`, `errors.py`, `store.py`, `envelope.py`, `auth.py`, `validate.py`, `helpers.py`, `routes/spine.py`. `calc.encroachment_clearance` and `cascade.recompute_franchisee` read for context only. Machine-verified that `errors.ERROR_HTTP` matches the §5 table exactly — no missing rows, no status mismatches, so §5's table needed no edits.

**Changes:**
- §2.1 — revise — ambiguity — empty-string `X-User-ID`/`X-User-Role` also yields `ERR_UNAUTHENTICATED`, and the role comparison is exact/case-sensitive — auth.py:12
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars; `api_request_timestamp` reads the logical clock, not wall time — envelope.py:12-20
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected, empty-string values treated as omitted, undeclared query params ignored — validate.py:224-244
- §2.3 — insert — ambiguity — list ordering ties broken by creation sequence (the frozen clock makes whole fixture chains share one `created_at`) — store.py:134, helpers.py:97
- §2.3 — insert — ambiguity — filters compare by exact equality, booleans accept `true/1/false/0` any case, empty string = omitted, unmatched/ill-formed value returns an empty page not an error — validate.py:247-279
- §2.4 — insert — ambiguity — `current_utc` required, accepted with or without trailing `Z` and read as UTC when offset-less; response `data` is the single-key object echoing the supplied string verbatim — spine.py:23-29
- §2.5 — revise — ambiguity — `created_at`/`updated_at` read the logical clock; a pre-move record carries exactly `2026-08-01T00:00:00.000Z` — store.py:51-54, 103-127
- §2.6 band 3 — insert — ambiguity — ownership band is skipped when the named record is absent; the request falls through to the 404 of band 5 — spine.py:150-155, 245-248, 282-286
- §2.6 band 4 — **revise — mismatch** — radius rule was "greater than 0"; impl rejects anything outside 0.5–50.0 with 400 — validate.py:135-140
- §2.6 band 4 — insert — ambiguity — absent/unparseable body = `{}`; non-object body = 400; explicit `null` treated as absent; undeclared body fields ignored — validate.py:15-27
- §2.8 — **revise — mismatch** — the geometry decimal counts read as a server rounding contract, but impl persists/echoes supplied lat/lng/radius verbatim; only derived distances/clearances are quantized — spine.py:117-120, 264-266
- §3.1 — insert — ambiguity — `contact_email` required but only checked for non-emptiness; no format, no uniqueness — spine.py:40
- §3.1 — insert — ambiguity — neither a territory grant nor the club shell/opening is gated on the franchisee's `PROBATION` standing — spine.py:98-126, 144-186
- §3.1 — revise — ambiguity — club `name` is any non-empty string with no length/uniqueness bound; `opened_on` is never compared to the logical clock (future dates accepted) — spine.py:157-158
- §3.1 — insert — ambiguity — club-open's optional `note` is validated but not persisted — spine.py:196
- §3.1 — insert — ambiguity — drafting a relocation applies no club-status gate (`PRE_OPENING`/`OPEN`/`SUSPENDED` all eligible) — spine.py:256
- §3.1 — revise — ambiguity — a new draft is created with `encroachment_km`, `submitted_by_user_id`, `decided_by_user_id`, `reviewer_note` all null — spine.py:270-273
- §3.1 — insert — ambiguity — resubmission leaves the bounce's `reviewer_note` in place and restamps `submitted_by_user_id` with the current submitter — spine.py:316-317
- §3.1 — revise — ambiguity — withdraw's optional `reason` is validated but not persisted — spine.py:385
- §3.1 — insert — ambiguity — an approval re-derives no `state_code` (territory's or club's) from the new geometry and leaves both `status` values alone — spine.py:355-364
- §3.9 — insert — ambiguity — reinstating a non-`PROBATION` franchisee also yields `ERR_FRANCHISEE_ON_PROBATION`; the opening recomputation persists counters/score (and can demote an `ACTIVE` franchisee plus withdraw its promotions) even on the refusal path, but never bumps `version` — only a successful reinstatement does; `note` validated, not stored — spine.py:64-73, cascade.py:166-199
- §4 preamble — insert — ambiguity — a trailing slash routes to the same endpoint — app.py:23
- §5 preamble — insert — ambiguity — two transport-level refusals outside the bands and the table: unknown path → 404 `ERR_NOT_FOUND`, wrong method on a served path → 405 `ERR_INVALID_REQUEST`, neither consulting the auth headers — app.py:36-43

**Left for passes 2/3:** the `discount_pct`/`corporate_credit_pct`/`variance_pct` precision clauses in §2.8, all of §3.2–§3.8, and the inspection/royalty body of §3.9.

### Pass 2 of 3 — `routes/plans.py` + `routes/memberships.py`

**File metrics:** before 469 lines / 115,590 chars → after 469 lines / 125,226 chars (+9,636 chars; line count unchanged, all edits in-paragraph). No new sections; still 5 top-level / 9 §3 subsections.

**Counts:** 38 Edit patches — **25 ambiguity-pins**, **13 mismatch-revisions**.

**Changes:**
- §2.6 band 3 — insert — mismatch — pinned the two exceptions to the "absent record falls through to 404" rule: ClubManager `home_club_id` at signing and `from_club_id` at transfer creation are compared as plain strings, so a non-existent club id yields `ERR_NOT_RESOURCE_OWNER` — memberships.py:34-37, 383-385
- §2.6 band 4 — revise — mismatch — schema range was "0 through 1" for both percentages; impl caps `discount_pct` at 0.500 and `corporate_credit_pct` at 0.100 in the schema band — plans.py:121, 267
- §2.6 band 15 — revise — mismatch — operation list grew from seven to nine: added publishing a plan template (`ERR_PRICE_BELOW_FLOOR`) and deciding a transfer request (`ERR_TRANSFER_BLOCKED_BY_ARREARS`) — plans.py:64, memberships.py:457
- §2.6 band 12 — revise — mismatch — added reviewing a promotion (approval re-applies `ERR_DISCOUNT_CAP_EXCEEDED`) — plans.py:165
- §2.6 band 14 — revise — mismatch — added reviewing a promotion (approval re-applies `ERR_PROMO_WINDOW_CONFLICT`) — plans.py:170
- §2.6 band 11 — revise — mismatch — added completing a transfer request (`ERR_HOME_CLUB_MISMATCH`) — memberships.py:482
- §2.6 band 10 — revise — mismatch — added deciding a transfer request (destination safety gate re-applied) — memberships.py:456
- §2.8 — insert — ambiguity — `discount_pct` / `corporate_credit_pct` are persisted and returned verbatim, never re-quantized to 3 dp, and extra precision flows at full precision into the discount arithmetic — plans.py:142, 275; calc.py:41-45
- §3.2 templates — insert — ambiguity — bad `code` charset and duplicate `code` are both schema-band `ERR_INVALID_REQUEST` (400) — plans.py:31-40
- §3.2 publish — insert — ambiguity — optional `note` validated but not persisted — plans.py:60
- §3.2 filing — insert — ambiguity — promotion `code` is any non-empty string (no charset, length or uniqueness rule); filing is not gated on franchisee standing; created with `reviewed_by_user_id` and `withdrawn_reason` null — plans.py:120, 146-147
- §3.2 review — insert — ambiguity — optional `note` validated then discarded — plans.py:158
- §3.3 members — insert — ambiguity — `full_name` any non-empty string, `email` checked only for non-emptiness plus uniqueness with no format validation, duplicate → `ERR_INVALID_REQUEST` (400) — plans.py:201-206
- §3.3 references — insert — ambiguity — franchisee standing is never consulted at signing, member `status` is not gated, and concurrent agreements are unrestricted — memberships.py:57-74
- §3.3 cascade — revise — mismatch — corporate enrolment recompute list corrected: a notice-period cancellation request recomputes nothing (only cooling-off cancellation, finalization, freeze, unfreeze do) — memberships.py:239-253
- §3.3 cascade — insert — ambiguity — `enrolled_agreement_count` moves without any `version`/`updated_at` bump on the `CorporateAccount`, at signing and at every later recomputation — memberships.py:129-130; cascade.py:209-215
- §3.4 event types — insert — ambiguity — three schema-band 400s pinned (system-only `event_type`, `due_on` on a non-`DUES_POSTED`, non-zero `PAYMENT_FAILED`), and zero amounts on the other types are legal — memberships.py:308-316
- §3.4 projection order — insert — ambiguity — creation sequence is the final tie-break in both the entry ordering and the charge ordering — cascade.py:20, 25
- §3.4 cascades — revise (x2) — mismatch — `DELINQUENT → PAST_DUE` and the moves to `CURRENT` also increment the franchisee's `version`, and all three bumps are unconditional on every append even when nothing moved — memberships.py:353-354
- §3.4 first payment — revise — mismatch — the franchisee's `version` increments too — memberships.py:354
- §3.4 collections — insert — ambiguity — `COLLECTION_PLACED` row shape (`due_on` null, `occurred_on` = clock date, balance snapshot), no projection re-run, no club/franchisee `version` bump, `agency_reference` discarded — memberships.py:280-296
- §3.4 ledger listing — insert — ambiguity — creation-sequence tie-break in the list ordering — cascade.py:20
- §3.5 freeze — insert — ambiguity — `reason` validated then discarded — memberships.py:165
- §3.5 unfreeze — insert — ambiguity — `note` validated then discarded — memberships.py:184
- §3.5 cancellation request — insert — ambiguity — `reason` validated then discarded — memberships.py:218
- §3.5 branch A — insert — ambiguity — club and member `version` bump unconditionally; the franchisee's score/status/promotion withdrawal happen with no franchisee `version` bump — memberships.py:203-208
- §3.5 finalize / terminality — revise — mismatch — `CANCELLED` does not block transfers (impl gates transfers on `dues_status` only); plus franchisee no-bump and discarded `note` — memberships.py:378-429, 470-507
- §3.6 opening — insert — ambiguity — the releasing club's status/compliance is never examined and the agreement's contract dimension is not gated at all — memberships.py:393-414
- §3.6 decide — insert — ambiguity — approval leaves the agreement untouched, cross-state is not re-checked, `note` discarded — memberships.py:451-467
- §3.6 complete — insert — ambiguity — both clubs bump unconditionally, neither franchisee bumps, `note` discarded, destination posture not re-checked — memberships.py:488-506
- §3.8 create — insert — ambiguity — `corporate_credit_pct` above 0.100 → `ERR_INVALID_REQUEST` (400); `name` any non-empty string — plans.py:266-268
- §3.8 fund — insert — ambiguity — funding is ungated by `status` (a `SUSPENDED` account may be funded) and a zero `amount_cents` is accepted, still bumping `version` — plans.py:288-296
- §3.8 allocate — insert — ambiguity — optional `note` discarded — plans.py:303
- §3.8 allocate — insert — ambiguity — remainder ordering's final tie-break is creation sequence, and each receiving franchisee's own `version` increments — calc.py:199-202; plans.py:316-317
- §3.8 recall — revise — mismatch — recall re-runs the waterfall over the eligible set *as it now stands* rather than replaying history, succeeds with nobody eligible (no `ERR_NO_ELIGIBLE_FRANCHISEE`), ignores account `status`, and discards `reason` — plans.py:325-345
- §3.8 suspend — insert — ambiguity — re-suspending a `SUSPENDED` account → `ERR_CORPORATE_ACCOUNT_SUSPENDED` (409); `reason` discarded — plans.py:352-356

**Confirmations:** did **not** `cp` over `PRD_COMPLETED.md`; every change an in-place `Edit`. Scanned both partition files end to end (`routes/plans.py` all 370 lines, `routes/memberships.py` all 519 lines). Left `usage.py`, `compliance.py`, §3.7 and the inspection/royalty body of §3.9 for pass 3, and deliberately did *not* edit §2.10's general cascade sentence since the franchisee version-bump matrix is per-operation and pass 3's operations bump differently. No pass-1 or Step 8 edit weakened.

### Pass 3 of 3 — `routes/usage.py` + `routes/compliance.py` + `calc.py` + `cascade.py`

**Size:** 469 lines / 125,226 chars **before** → 469 lines / 135,275 chars **after** (+10,049 chars, 0 lines — every patch an in-paragraph insert or revision).

**Counts:** 24 patches — **19 ambiguity-pins**, **5 mismatch-revisions**.

**Changes:**
- §2.1 — revise — mismatch — `ClubManager` bullet claimed `GuestUsageEvent` writes are ownership-scoped to `host_club_id`; impl performs no ownership check at all, so the bullet now pins recording as the one deliberately un-scoped `ClubManager` write — `routes/usage.py:22`
- §2.6 band 3 — revise — mismatch — dropped `GuestUsageEvent` from the ownership-band entity list — `routes/usage.py:22`
- §2.6 band 3 — revise — mismatch — "Two writes are deliberate exceptions" → **three**, adding the `FranchiseOwner` royalty-report case, plus the pinned fact that the plain-string comparison only fires when the field arrived as a string — `routes/compliance.py:44-46`, `routes/memberships.py:34-37,383-385`
- §2.8 — insert — ambiguity — added the settlement `rebate_pct` to the 2-decimal non-monetary precision list and pinned both it and `variance_pct` as server-quantized — `calc.py:120`, `calc.py:68`
- §2.10 — insert — ambiguity — the general cascade sentence's blanket "every touched entity's `version` increments" replaced by the re-derivation-vs-bump distinction, naming `CorporateAccount.enrolled_agreement_count` and the `Franchisee` as the two habitual exceptions, with a forward reference to §3.9's complete bump list; the withdrawn-promotion bump stays unconditional — `cascade.py:196-199,166,209-215`
- §3.7 — insert — ambiguity — `visit_count` has no upper bound; recording is not ownership-scoped — `routes/usage.py:22,27`
- §3.7 — insert — ambiguity — the three recording gates are evaluated in §2.6 band order (host-club operational first, `period_month` last), the agreement's `agreement_status`/`dues_status` are never consulted, the home club is read for its identifier only, the `period_month` test is a lower bound only, and no `version` anywhere moves — `routes/usage.py:32-43,45-57`
- §3.7 — insert — ambiguity — sweep tie-break is creation sequence behind `created_at`; "no zero-value settlement" corrected to "no *empty* settlement" since a zero-fee one is reachable; neither club's posture is consulted; `home_club_id` resolves before `host_club_id` — `routes/usage.py:90,103-111`
- §3.7 — insert — ambiguity — the duplicate triple is ordered, not symmetric, and `REVERSED` never blocks — `routes/usage.py:96-101`
- §3.7 — revise — mismatch — "it requires `net_payable_cents` to be at least 0" implied a gate impl does not have; revised to no amount gate, non-negative by construction, plus `note` discarded, both club bumps unconditional in the zero-value case, and nothing else disturbed — `routes/usage.py:137-157`
- §3.7 — insert — ambiguity — reversal's `reason` is a non-empty string, discarded; no counters/standing re-derived; released batches are identified by stored `settlement_id`, not by replaying the sweep criteria — `routes/usage.py:160-182,76-79`
- §3.9 — insert — ambiguity — scheduling consults nothing about the club beyond existence, does not touch it, allows any number of concurrent `SCHEDULED` inspections, and the future-date 400 comes after the club existence 404 — `routes/compliance.py:133-163`
- §3.9 — insert — ambiguity — the club-live requirement at scoring is refused with `ERR_CLUB_NOT_OPERATIONAL`, tested after the inspection's own state gate — `routes/compliance.py:176-181`
- §3.9 — revise — mismatch — `SCORED → CLOSED` / `SCORED → REMEDIATION_REQUIRED` implied an observable `SCORED` state; revised to pin `SCORED` as never persisted or returned, plus the `PRE_OPENING`/re-failing-`SUSPENDED` club `status` non-moves and the unconditional club/franchisee bumps — `routes/compliance.py:196-209`
- §3.9 — insert — ambiguity — waiver's segregation test runs ahead of the remediation gate; a null `score` also fails the gate; a `SCHEDULED` inspection passes segregation vacuously — `routes/compliance.py:220-225`
- §3.9 — insert — ambiguity — the waiver bumps exactly two records; the franchisee is re-derived (demotion and promotion withdrawals included) with no `version` of its own — `routes/compliance.py:238`
- §3.9 — insert — ambiguity — closing an inspection discards its `note` and cascades nowhere (no club write, no franchisee re-derivation, no streak change, since all four scored states feed the walk alike) — `routes/compliance.py:242-254`, `cascade.py:139`
- §3.9 — insert — ambiguity — the complete four-item list of paths where a franchisee recomputation bumps its own `version` (score inspection, append billing event, royalty→`DISPUTED`, adjudicate), and the explicit no-bump list for every other path; reinstatement added to the recompute trigger list — `cascade.py:196-199` against all 10 `recompute_franchisee` call sites
- §3.9 — insert — ambiguity — fail-streak walk tie-break extended to creation sequence — `cascade.py:148`
- §3.9 — insert — ambiguity — royalty `franchisee_id` must equal `X-User-ID` by plain string compare before lookup (403, never 404); duplicate test is status-blind and precedes the closed-period test — `routes/compliance.py:44-60`
- §3.9 — insert — ambiguity — report created with `adjusted_royalty_cents`/`adjudicated_by_user_id` null; `SUBMITTED` never observable; the `ACCEPTED` path still re-derives and can still demote/withdraw, without a franchisee `version` bump — `routes/compliance.py:80-89`
- §3.9 — insert — ambiguity — the adjudication band comparison is applied after the state gate, not in the schema band; schema only requires an integer >= 0; `note` discarded — `routes/compliance.py:97-108`
- §3.9 — insert — ambiguity — royalty rounding happens once at the end of the whole `basis x bps / 10000` expression, and `royalty_rate_bps` is read live at submission rather than replayed — `calc.py:60`, `routes/compliance.py:66`

**Structural sanity check — PASS.** All five `## ` top-level sections present; all nine `### 3.x` subsections present (19 `###` total: 10 in §2 + 9 in §3); file still ends at a real section boundary (`| ERR_NO_ELIGIBLE_FRANCHISEE | 409 |`); **not** byte-identical to `PRD_FINALIZED.md` (71 lines differ across all three passes); no unbalanced inline backticks introduced.

**Confirmations:** did **not** `cp` over `PRD_COMPLETED.md`; all 22 pass-1 and 38 pass-2 patches intact. Scanned all four partition files end to end: `routes/usage.py` (194), `routes/compliance.py` (266), `calc.py` (203), `cascade.py` (237). Two `calc.py` findings needed no patch: `notice_refund`'s `effective_monthly_dues_cents <= 0` guard is unreachable (dues base >= 100 with max total discount 41.5%), and `append_system_event`'s hardcoded `resulting_outstanding_balance_cents: 0` is overwritten by every caller with the real balance snapshot, so §3.4's existing wording is correct.

### Orchestrator final verification

- `PRD.md` 469 lines / 109,191 bytes (md5 `e383c31b…`); `PRD_FINALIZED.md` 469 / 110,124 (md5 `e09efb4e…`); `PRD_COMPLETED.md` 469 / 135,275 (md5 `d743c5b3…`). All three distinct — `PRD_COMPLETED.md` is NOT byte-identical to its source, so the scan genuinely ran (the known Step 9 failure mode).
- `PRD_COMPLETED.md`: 5 `## ` sections, 9 `### 3.x` subsections, ends on the final §5 error-table row; 142 diff lines (71 changed line pairs) against `PRD_FINALIZED.md`.
- Final Step 7 sweep artifacts still intact and green: all 8 `workspace/implementation/results.$i.json` read `270 / 270`, `failed=0`, `errors=0`.

Pipeline complete through Step 9.
