## Step 1: Create task directory — 2026-09-05T16:11:02.179175023Z

Created tasks/task_2916_esports_organization_player_contracts_team_operations/ and its workspace/ subdirectory (pre-assigned path; no index scan performed).


## Step 2: Generate scaffold — 2026-09-05T18:02:47.530315768Z

**Task 2916 — Esports Organization Player Contracts & Team Operations — Step 2 scaffold generated**

Files (all in `tasks/task_2916_esports_organization_player_contracts_team_operations/`):
- `SCAFFOLD.yaml` — 3364 lines, §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1931 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3934 lines, single key `scaffold_corner_design`

**§1.0–§1.7 coverage.** 12 entities (League, Organization, Player, ContractOffer, PlayerContract, TeamHouse, PracticeBlock, SponsorshipDeal, DeliverableAssignment, PrizeDistribution, PrizeAllocation, RosterMove); 9 state machines (PlayerContract runs parallel `contract_status` × `obligation_status` dimensions; ContractOffer is cyclic via counter/revise with a round cap); 2 OCC rules (`deliverable-create-stale-deal` → ERR_DEAL_VERSION_STALE 412 on `POST /sponsorship-deals/{id}/deliverables`; `roster-move-create-stale-org` → ERR_ORGANIZATION_VERSION_STALE 412 on `POST /roster-moves`); 14 calculations (dual-variant `salary_cap_charge` prorated vs full-season, dual-variant `burnout_score` rolling-7day vs season-cumulative, nested `weekly_hour_cap` with minor/guardian/education branches, `prize_allocation` waterfall with floor-then-remainder plus resident/non-resident withholding and minor escrow, `transfer_settlement` with a gross-keyed commission tier, interval-merge room/player booking, ledger-conservation invariants for salary and prize); 64 validations over 13 priorities (auth → ownership → shape → path/body existence → state → safety → capacity → SoD → fiscal); 63 endpoints; 58 error ids; 10 roles (5 entity-backed, 5 opaque) under a segregation-of-duties model with a mandatory logical clock defaulting to 2026-08-01T00:00:00Z.

**§1.8 difficulty design.** 9 rules × 20 instances (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2).

**§1.9 corner design.** All 9 claim-extraction-guide sections walked: entities 10, state_machines 10, calculations 12, validations 12, endpoints 5, errors 1, rbac 4, cross-cutting complexity layers 4, consistency model 1 = **59 instances (41 executable recipes + 18 `excluded_because` stubs)**. Verified mechanically: all **63/63** endpoints are exercised by at least one §1.8/§1.9 call, all **58/58** error ids appear in at least one *assert* of an executable recipe (not merely in `grounds`), all 79 instance names are unique across both design files, every stub cites a real §1.8 instance and carries no `test_recipe`.

**Design adjudications made.**
1. Fixed a scaffold self-inconsistency: `POST /contracts/{id}/wellness-report` side_effects claimed the wellness hold and `wellness_flag_count` were stamped on any escalation out of COMPLIANT, contradicting the PlayerContract state machine (BREACH-only) and §1.8's "hold is still null after the 70 escalation". Rewrote so the block-cancellation cascade fires on every escalation but hold/flag are BREACH-only.
2. `RosterMove.contract_id` is required for every `move_type` (including SIGN); SIGN execution fires none of the four RELEASE cascade links and writes no money field.
3. Added priority-10 `ERR_BLOCK_NOT_FINISHED` (409) — the SCHEDULED→HELD precondition previously had no error id.
4. Priority-8 `ERR_CONTRACT_NOT_ACTIVE` on `POST /practice-blocks` is scoped per participant, so TRYOUT blocks for contract-less PROSPECTs stay implementable; `weekly_hour_cap.streaming_minutes()` gained an explicit 0 branch for contract-less players.
5. §1.9 `errors` section is a real recipe (`error_envelope_shape_is_uniform_across_status_classes` walking 404/422/409/412/403 plus no-partial-write proofs) rather than a coverage ledger, since the guide's Table 6 only demands triggerability and SKILL.md forbids stubbing a corner no §1.8 instance covers.
6. Intentionally-negative calls are marked per-call with `captures: {e_n: $.data.error_id}` instead of via `_returns_4xx` instance names, so the linter keeps verifying roles/payloads on the surrounding positive calls. The 7 pre-existing name-bypassed instances were re-verified by hand: the only role/payload deviation is the deliberate missing-required-field call in `malformed_bodies_and_bad_enums_return_invalid_request`.
7. Numeric literals were all pre-computed from §1.3 (e.g. provisional cap charge 12328767 and 3945205, final 12500000, committed 16273972, uncommitted 37671233; prize waterfall on 10000000 gross → levy 250000 / org share 3412500 / allocated 6337500 / withholding 950625; deliverable fee shares 500000 and 1000000).

**Lint verdict (verbatim):**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     41
  Calls scanned (§1.8+§1.9):  873

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory was read at any point. All three files parse as YAML and end on a complete `assert` list.

Orchestrator verification: all three files present and non-empty; grep for the difficulty directive ("harder than expert", "Generate task") across all three scaffold files returned zero hits, so no leak path into PRD.md.

## Step 3: Copy shared files — 2026-09-05T18:02:47.555648157Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (bash only, no subagent).

## Step 4: Generate PRD — 2026-09-05T18:17:28.575Z

**Output:** `workspace/PRD.md` — **413 lines**, ends at a real section boundary (final §5 table row `| ERR_NO_ELIGIBLE_CONTRACTS | 422 |`), no truncation. Written as 1 `Write` + 6 `cat >>` heredoc appends, `wc -l`/`tail` verified after each.

**Sections emitted**
- `## 1. Introduction` (3 paragraphs; angle = spreadsheet-and-DM chaos -> an opinionated arithmetic/authority engine with conservation and minor-protection invariants)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Common Resource Properties, Timestamps and Versioning · 2.5 The Logical Clock and Instant Conventions · 2.6 Order of Evaluation for Rejections (13 numbered bands) · 2.7 Money, Basis Points and Rounding Discipline · 2.8 Optimistic Concurrency on Parent Versions · 2.9 Cascades, Conserved Quantities and Deliberate Asymmetries · 2.10 Nested Paths and Reverse-Reachability Reads
- `## 3. Business Logic & Workflows` — 3.1 The League Charter and the Organizations Competing Under It · 3.2 Scouting, Age Derivation and the Protection of Minors · 3.3 Negotiating Terms: Offers, Counters, Revisions and Expiry · 3.4 Acceptance: Turning an Offer into a Contract · 3.5 Team Houses, Practice Scheduling and Weekly Workload Limits · 3.6 Wellness Monitoring, Burnout Escalation and Contract Suspension · 3.7 Sponsorship Deals and the Deliverables Placed Across a Roster · 3.8 Prize Money: the Waterfall, its Sign-off and its Undoing · 3.9 Roster Changes: Filing, League Decision, Execution and Reversal
- `## 4. Endpoint Definitions` — intro paragraph + 4-column table, **63 rows**
- `## 5. Error Code Catalogue` — intro paragraph + 2-column table, **58 rows**

**Coverage:** endpoints 63/63; error ids 58/58 (all also referenced with their trigger condition in §2/§3); calculations 14/14 (incl. both `salary_cap_charge` variants and both `burnout_score` variants); validations 64/64 across all 13 priority bands, each with its `applies_to` scope; state machines 9/9 (incl. both PlayerContract dimensions); concurrency rules 2/2; roles 10/10; required field/param names 156/156.

**Hard Contract reports**
1. **Field-Name Coverage — PASS.** 156 required names extracted from `entities[].fields[].name` + all endpoint `input` identifiers (`?` stripped) + dict-`output` keys; 156 present verbatim in backticks; **0 missing**. Also verified: all state values present, all enum values present, all role names present.
2. **Rule Coverage — PASS.** Every validation priority/condition/scope, both concurrency rules, all 9 state machines (every transition, precondition and side effect), all 14 calculations translated to prose (no `>=`/`IN`/`round()`/`floor()`/`+=` left as pseudocode), all endpoint `side_effects`, all field defaults, and all sibling-branch symmetries (`WARNED` vs `BREACH`, `APPROVE` vs `REJECT`, `SIGN`/`RELEASE`/`TRANSFER_OUT` execution, counter vs revise, `ASSIGNED->VOIDED` vs `APPROVED->VOIDED`, `CALCULATED->VOIDED` vs `APPROVED->VOIDED`). **0 missing.**
3. **§3 Path Purity — PASS.** 904 backticked tokens scanned between `## 3.` and `## 4.`: **0** slash-prefixed, **0** bare HTTP methods, **0** method+path combinations. §3 uses state-transition, role+action-verb and capability framing throughout; both OCC rules name their paths in §2.8, where paths are permitted.

**Adjudications / Zero-Silence decisions (all resolved in prose, none left implicit)**
1. Header spelling: scaffold `X-User-Id` vs skill-mandated `X-User-ID` -> documented `X-User-ID`, with a note that HTTP header names match case-insensitively.
2. `round_number` is incremented by *revise* only (3 scaffold sources agree); *counter* does not increment it but is still gated on the same ceiling -> `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`. That error also assigned to revise's ceiling precondition, which had no error id in the scaffold.
3. `minor_permitted` is derived false for `ENERGY_DRINK`, `BETTING`, `CRYPTO`, but `ERR_MINOR_CATEGORY_FORBIDDEN` covers only `BETTING`/`CRYPTO` -> flag documented as advisory, prohibition documented as strictly narrower.
4. `prize_payable_cents` increases at calculate, is **unchanged** at approve (already counted while `CALCULATED`), and is withdrawn at void.
5. PrizeAllocation persisted keys are `net_cents` and `escrow_holdback_cents` (the formula's `net_payout_cents`/`escrow_cents` are intermediates, not stored names).
6. `RosterMove.contract_id` documented as required for every `move_type` (entity description wins over the endpoint's `contract_id?`).
7. Accept's `effective_at` documented as omissible, defaulting to the current logical instant.
8. Transfer-window eligibility stated at **both** filing and execution; roster-lock stated at **both** `SIGN` filing and the league decision.
9. Reversal's `uncommitted_salary_cents >= released_cap_cents` precondition had no error id -> mapped to `ERR_SALARY_CAP_EXCEEDED`.
10. Cap-summary `provisional_committed_cents` / `final_committed_cents` defined as the two `salary_cap_charge` variants summed over `ACTIVE` + `SUSPENDED` contracts.
11. `ERR_BLOCK_NOT_SCHEDULED` stated explicitly for *cancel* as well as *complete* (scaffold `applies_to` listed both; the cancel branch originally only implied it).

**Isolation compliance:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced; no sibling task directory was read. Scratch files are task-scoped under `workspace/scratch_prd/`.

Orchestrator truncation check: PRD.md is 413 lines, `grep -n '^## '` shows all five top-level sections present in order, §4 table has 63 rows and §5 has 58 rows, and the file ends on a complete error-catalogue table row — not mid-sentence. No regeneration needed. Grep for "scaffold" / "harder than expert" / "test_recipe" in PRD.md returned zero hits.

## Step 6: Generate implementation — 2026-09-05T18:46:02.649Z

**Output:** `workspace/implementation/`

**Modules (3,679 lines of Python + launcher):**

| file | lines | role |
|---|---|---|
| `errors.py` | 92 | all 59 PRD error ids -> HTTP status map, `ApiError`, `fail()` |
| `db.py` | 205 | in-memory `Store` (12 dicts), logical clock (epoch `2026-08-01T00:00:00Z`), ISO-8601 3-digit formatting/parsing, duration + `Decimal` ROUND_HALF_UP helpers, `insert`/`touch`/`in_creation_order` |
| `response.py` | 83 | `meta`/`response_type`/`data` envelope, `req_<20 upper-alnum>` ids, pagination meta |
| `auth.py` | 99 | 10 roles, org-backed vs player-backed vs opaque subjects, `endpoint(roles)` decorator, ownership helpers |
| `validation.py` | 278 | shape coercion (str/int/bp/bool/enum/instant/date/id-list), query filters, 11 `find_*` FK resolvers each mapped to its own `ERR_*_NOT_FOUND` |
| `calc.py` | 638 | every SCAFFOLD §1.3 calculation: league windows, minor/consent status, cap-charge variants, weekly hour cap, burnout score, facility conflict with turnaround padding, deliverable fee share, exclusivity, prize waterfall, transfer settlement |
| `serializers.py` | 337 | 13 projections; all counters derived on read |
| `cascade.py` | 142 | block cancellation, burnout escalation, assignment voiding, contract termination + exact reversal |
| `routes_core.py` | 330 | clock, leagues, organizations, players, guardian consent, cap-summary |
| `routes_offers.py` | 437 | offer negotiation lifecycle + acceptance four-link cascade, contract reads/suspend/wellness |
| `routes_practice.py` | 281 | team houses, practice blocks, complete/cancel |
| `routes_sponsorship.py` | 286 | deals, deliverable placement, assignment submit/review |
| `routes_prizes.py` | 186 | distribution create/calculate/approve/void/allocations |
| `routes_moves.py` | 220 | roster-move file/decision/execute/reverse |
| `app.py` | 65 | app factory, 6 blueprints, `ApiError`/`HTTPException`/`Exception` envelope handlers |
| `start.sh` | 10 | foreground `exec python3 app.py`, `$PORT`, binds `0.0.0.0`, guarded pip install |

**Endpoints: 63** registered — exactly matching the 63 rows of PRD §4 (verified by enumerating `app.url_map`). Storage is in-memory only; a fresh boot lists `total_count: 0` for every collection (verified) and nothing is ever seeded.

**Structure.** Every mutating handler walks the PRD §2.6 13-band ladder in source order with explicit `# ---- band N ----` markers: auth -> authz -> path existence left-to-right -> ownership (read from the *raw* body value before shape validation, so band 4 genuinely precedes band 5) -> shape -> body/query FKs in the §2.6 listing order -> OCC on the parent version only -> state preconditions (lazy offer expiry evaluated before any status guard) -> minor/education/wellness in the six-error internal order -> league calendar -> facility/quota/roster size -> exclusivity + segregation of duties -> fiscal. Practice-block placement uses check-outer/participant-inner loops so all band-8 contract checks precede all band-9 consent checks, which precede cap checks, which precede wellness holds. State machines are table-driven guards in the route modules; the cyclic ones (offer SENT<->COUNTERED, assignment SUBMITTED->REJECTED->SUBMITTED, player SIGNED->FREE_AGENT->TRYOUT_INVITED->SIGNED, deal ACTIVE<->FULFILLED bubbling from child counts) never lose their round/rejection tallies. Money is integer cents throughout with `Decimal` + ROUND_HALF_UP, and the two truncating exceptions (per-deliverable fee share, per-row prize floor share) are isolated in `calc.floor_div` call sites.

**Smoke test: 90/90 assertions pass.** Ran `scratch_impl/smoke.py` against our own server. The first attempt bound port 47311, already held by another pipeline, so start.sh correctly reported "Address already in use"; re-launched on 53187, confirmed ownership via `/proc/<pid>/cwd`, and killed each PID individually (549968, 577032, 586265, 587911 — no leftover servers, port released, no pattern kills used). Covered: the 3 auth/authz rejections, league/org/player creation and derivations, offer counter/revise/accept, the exact cap arithmetic (`provisional 11,404,110` vs `final 12,500,000`), the budget conservation identity, guardian consent gate then grant, facility buffer conflict at exactly ±30 min, both weekly-cap error variants, burnout scoring after a completed block and after a wellness report, obligation-summary key set, deal activation + OCC stale token + fee-share residue + FULFILLED bubbling, the full prize waterfall (levy 25,000 / org 341,250 / pool 633,750 with the 88-cent remainder landing on the largest floor row, resident 1500bp vs non-resident 3000bp withholding, minor escrow) and the ledger identity, segregation of duties on both approve paths, and a RELEASE move filed -> decided -> executed -> reversed with the asymmetric cascade (assignments stay VOIDED, deal reverts to ACTIVE, committed salary returns to its exact pre-execution value).

**Adjudications where the PRD was ambiguous:**
- Band 4 on `Player` resources checks player-backed roles only; org-backed roles are not matched against `Player.current_organization_id`. Org ownership applies wherever a resource carries a primary organization FK.
- Body-supplied `organization_id` is ownership-checked from the raw value before shape validation, so band 4 precedes band 5 even for creates.
- Band 8 internal order follows the §2.6 enumeration: `ERR_DEAL_NOT_ACTIVE` before `ERR_CONTRACT_NOT_ACTIVE` for deliverable placement; `ERR_CONTRACT_NOT_ACTIVE` before `ERR_ASSIGNMENT_NOT_SUBMITTED` on submit (both are true at once after a termination cascade).
- Exclusivity at activation is evaluated over the deal's own non-VOIDED deliverables — vacuously empty for a DRAFT deal, which is precisely why "DRAFT deals never conflict".
- A `supersedes_offer_id` pointing at a terminal offer is retired silently; only SENT/COUNTERED move to SUPERSEDED.
- Termination cancels future blocks with `cancel_reason = CONTRACT_SUSPENDED` (the enum has no TERMINATED member).
- `per_deliverable_fee_cents` and `earned_fee_cents` are exposed as extra derived fields on the deal projection although SCAFFOLD lists no such stored fields.
- A wellness report omitting `reported_streaming_minutes_7d` retains the stored value rather than resetting it to 0.
- Prize floor-share remainder ties break to the earliest `created_at` (strict `>` over a creation-ordered row list).

## Step 5: Generate unit tests — 2026-09-05T19:45:48.825Z

## Files written (task root)

**`test_helpers/` — 9 files, 2,502 lines**
`__init__.py` 51 · `api_client.py` 316 · `api_errors.py` 147 · `assertions.py` 321 · `constants.py` 109 · `factories.py` 287 · `fixtures.py` 747 · `test_users.py` 127 · `types.py` 397

**`test_suite/` — conftest 77 lines + 18 test modules, 6,599 lines**
`test_01_dual_variant_cap_and_burnout.py` 239 (6 tests) · `test_02_combinatorial_formulas.py` 327 (7) · `test_03_non_linear_state_machines.py` 307 (6) · `test_04_transitive_cascades.py` 238 (4) · `test_05_precedence_pairs.py` 199 (4) · `test_06_boundary_precision.py` 268 (6) · `test_07_cross_entity_state.py` 217 (4) · `test_08_resource_temporal_overlap.py` 197 (4) · `test_09_compensating_invariants.py` 300 (4) · `test_10_entities.py` 705 (10) · `test_11_state_machines.py` 714 (6) · `test_12_calculations.py` 397 (5) · `test_13_validations.py` 973 (8) · `test_14_endpoints.py` 591 (5) · `test_15_errors.py` 158 (1) · `test_16_rbac.py` 441 (4) · `test_17_cross_cutting.py` 151 (1) · `test_18_consistency.py` 177 (1)

## Tests emitted per queue

- **Queue A (Difficulty, §1.8): 45 tests** across test_01–test_09, covering **all 20** difficulty instances (2–3 tests each; the five dual-variant/nested-formula rules get 3).
- **Queue B (Corner, §1.9): 41 tests** across test_10–test_18 — entities 10, state_machines 6, calculations 5, validations 8, endpoints 5, errors 1, rbac 4, cross-cutting 1, consistency model 1. Every one of the **41 non-stub** corner instances has >=1 test.
- **Total: 86 tagged tests**, exactly one `Design:` line each.

`test_17_cross_cutting.py` covers both parent-version tokens on one fixture (stale `expected_deal_version` -> 412 `ERR_DEAL_VERSION_STALE` on an otherwise-legal replay, refreshed token -> 201, then stale `expected_organization_version` -> 412 `ERR_ORGANIZATION_VERSION_STALE` with `total_count == 0`, refreshed -> 201 PENDING). `test_18_consistency.py` covers the acceptance four-link cascade and the final deliverable approval, each asserted in the response body *and* in the immediately following read of every touched resource — no retries, polls or sleeps.

## Verification run

- `check_quotes.py test_suite/test_*.py` -> **PROBLEMS: 0** (all PRD quotes verbatim after whitespace normalisation; exactly one trailing `Design:` tag per test; every tag name exists in its index).
- `check_refs.py` over `test_suite/*.py` + `test_helpers/*.py` -> **MISSING: none** (every `api_client.` / `fixtures.` / `factories.` / `assertions.` / `ApiErrorId.` attribute and every `from test_helpers import` name resolves).
- Coverage audit: **0 uncovered non-stub instances, 0 `excluded_because:` stubs tagged, 0 extra tags**.
- All 18 modules import cleanly under `python3 -c importlib`; no `pytest.skip` / `xfail` / `skipif` anywhere; the string "scaffold" appears nowhere in generated code.
- `ls -la` confirms both directories are at the task root; `workspace/test_helpers` and `workspace/test_suite` **do not exist**.

## SKIPPED design instances

**None.** No instance failed the PRD-first two-condition filter. The 18 corner entries carrying `excluded_because:` are index stubs pointing back at queue A and were correctly never translated.

## Adjudications

1. Three difficulty-index `rule_id` aliases are stale (`cascading_state_transition`, `dual_variant_divergence`, `threshold_boundary`); tags use the real rule ids `transitive_cascade`, `dual_variant_calc`, `boundary_precision_check`.
2. `ERR_DEAL_NOT_ACTIVE` on placement is derived from §3.7's activation sentence rather than a placement-specific one; asserted as 409.
3. Omitted the design's post-reversal `released_cap_cents` assertion — the PRD does not uniquely derive whether the field is cleared or retained on reversal.
4. Corner arithmetic corrected 11835615 -> **11671232** in `prize_allocation_input_set_excludes_suspended_and_late_effective_contracts` (design's figure did not follow from the PRD's proration).
5. Pagination-bound refusals asserted as **400**, not the design's 422 (PRD line 74 states `ERR_INVALID_REQUEST` HTTP 400 explicitly).
6. Missing-`region_code` refusal asserted as **400**, not 422 (band 5, PRD line 100).
7. Scratch tool only: widened the `Design:` regex in `workspace/scratch_tests/check_quotes.py` to accept section names containing spaces — audit tooling, not a deliverable.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator could not read `test_suite/` (the directory did not exist when it started). Verified after both exited: `workspace/test_helpers` and `workspace/test_suite` do not exist — both directories are correctly at the task root.

## Step 7: Run tests and iterate — 2026-09-05T20:06:31.099Z

Clean 8-round sweep achieved. Both failure clusters were test-artifact defects; the implementation needed no changes.

**Iterations run:** 2 (sweep 1 diagnosed, fixes applied, sweep 2 verified clean).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence and was uniquely derivable, so all 86 tests survive.

**Fixes applied to `test_helpers/`:** none — the fixtures, factories and role-header builders were already PRD-faithful.

**Fixes applied to `implementation/`:** none. Both clusters were the test artifact diverging from PRD, not the server.

**Fixes applied to `test_suite/`** (8 assertion sites + 2 setup instants):

*Cluster 1 — ISO fractional-second width (6 tests, 8 sites).* PRD §2.5 requires instants "with three fractional digits", so the server correctly returns `2026-08-01T00:00:00.000Z`. These sites compared it with raw `==` against no-fraction literals/constants (`"2026-08-24T00:00:00Z"`, `ROSTER_LOCK_AT`, `payload[field]`). The suite already has `assert_instant_equals` / `canonical_instant` in `test_helpers/api_client.py` for exactly this, and 4 other test modules already use it — these 8 sites were the drift. Converted each to `assert_instant_equals`, which keeps the equality exact and only normalises fractional width:
- `test_10_entities.py:63` (league registration echo, all five calendar instants)
- `test_12_calculations.py:333` (`roster_lock_at`)
- `test_13_validations.py` x4 (`free_agency_window_ends_at` x2, `wellness_hold_until` x2)
- `test_14_endpoints.py:550-551` (`roster_lock_at`, `transfer_window_close_at`)

*Cluster 2 — weekly window setup defect (2 tests).* `test_the_summary_reports_the_week_sitting_exactly_on_its_cap` and `test_both_of_the_players_blocks_are_charged_to_the_same_week` both parked the clock at `2026-08-09T00:00:00Z` — **a Sunday** — then asserted the obligation summary charged 2700 / 240 minutes for blocks starting `2026-08-10` through `2026-08-12`. Per PRD §3.5 the week is Monday-anchored, so the clock's week was `[08-03, 08-10)` while every block started in `[08-10, 08-17)`; the server correctly reported 0. Since a computed read has no candidate block, the only defensible "instant being examined" is the current one, so the impl is faithful and the test setup was self-contradictory (its own quoted PRD line says "whose `starts_at` falls inside that week window"). Added a `fixtures.set_clock` into the blocks' week before the summary read (`2026-08-11T23:00:00Z` and `2026-08-12T09:00:00Z`). Blocks stay `SCHEDULED` because PRD §2.5 guarantees moving the clock mutates nothing eagerly. The sibling test `test_the_cap_admits_the_exact_minute_and_refuses_the_next_one`, which shares the setup helper and was already passing, was left untouched.

**Final sweep evidence** (`workspace/implementation/results.{1..8}.json`, all written 20:00): **86/86, 86/86, 86/86, 86/86, 86/86, 86/86, 86/86, 86/86** — zero failures, zero flakiness.

Orchestrator independent verification (not taken on the subagent's word): all 8 `results.$i.json` exist on disk with timestamps 20:00, and a fresh `json.load` of each reports `passed=86 total=86 failed=0 errors=0`. Sweep was launched via the pre-written `workspace/run_sweep.sh` under `setsid nohup`, so no reaping artifacts. Step 8 is NOT skipped: although `implementation/` fixes were 0, Step 7 ran 2 iterations and applied 10 `test_suite/` fixes, so the skip condition (all four counts zero) does not hold.

## Step 8: Finalize PRD — 2026-09-05T20:10:17.891Z

`workspace/PRD_FINALIZED.md` written with two minimal edits.

**Line counts:** `PRD.md` 413 lines — `PRD_FINALIZED.md` 413 lines (0% line delta; 2 lines revised in place, no lines added/removed).

**Changes**
- **§2.5 (line 90) — revise** — after the existing "three fractional digits … comparisons are exact" sentence, pinned that the three-digit form is the *rendering* the server applies to every instant it returns (including one echoed back from the request that supplied it), and that an inbound instant is read for the moment it denotes and is never refused for the width of its fractional part — `implementation/db.py:76-91` (`iso`, `"%…%02d.%03dZ"`) and `implementation/db.py:94-109` (`parse_instant`, no width check).
- **§3.6 (line 232) — insert** — one sentence after the obligation-summary field list: the read supplies no candidate block to §3.5's weekly arithmetic, so the instant examined is the current one and the charged week is the Monday-anchored window containing it; blocks starting in another week are not counted — `implementation/serializers.py:177-180` (`calc.weekly_committed_minutes(player_record, db.now(), …)`).

**Per-edit pre-edit search log**

*Edit 1 — subject: ISO instant rendering on output and instant tolerance on input.*
(b) Paths enumerated: `db.iso` (db.py:76) and every caller — all 22 instant fields in `serializers.py` (`league`, `player.free_agency_window_ends_at`, offer `sent_at`/`expires_at`, contract `effective_at`/`ends_at`/`wellness_hold_until`, obligation-summary `wellness_hold_until`, block/deal `starts_at`/`ends_at`, assignment `due_at`, distribution `tournament_end_at`, allocation, plus base `created_at`/`updated_at`), `response.py:28` (`api_request_timestamp`), `routes_core.py:30` (clock echo `current_utc`); input side: `validation.req_instant` / `opt_instant` / `instant_filter` -> `db.parse_instant`, and all their callsites (`routes_core.py:28,54-58,104`, `routes_offers.py:256`, `routes_practice.py:122-123,209-210`, `routes_sponsorship.py:41-42,127`, `routes_prizes.py:29`, `routes_moves.py:37`). Also checked `serializers.py:85` `birth_date` and `validation.req_date` — a *date*, echoed raw and length-checked at exactly 10 chars.
(c) Adjustment: scoped the claim to "instants" (not dates, so `birth_date`'s strict `YYYY-MM-DD` rule is untouched), and phrased input tolerance negatively ("never refused merely because its fractional part …") rather than enumerating accepted forms, because `parse_instant` also accepts non-`Z` offsets and other `fromisoformat` spellings — an exhaustive positive list would have excluded behavior the impl exhibits.

*Edit 2 — subject: which instant anchors the weekly window.*
(b) Paths enumerated: `calc.scheduled_minutes` / `calc.weekly_committed_minutes` / `db.week_start` and *both* of their callers — `routes_practice.py:97-112` `_weekly_cap_gate`, which anchors on `candidate["starts_at"]` and passes the candidate as `extra_blocks`, and `serializers.py:168-192` `obligation_summary`, which anchors on `db.now()` with no extra block. Also checked the neighbouring non-week anchors so the wording would not bleed into them: `calc.rolling_practice_minutes` (a `(now-7d, now]` window, not a week), `calc.season_burnout_score` (elapsed weeks from `effective_at`), `calc.cap_minutes` and `calc.streaming_minutes_charged` (no time anchor at all).
(c) Adjustment: kept the pin inside the §3.6 obligation-summary paragraph and did **not** touch §3.5's general "the instant being examined" wording — editing §3.5 would have contradicted the booking gate, which legitimately examines the candidate block's `starts_at` rather than the clock. Also reworded from an inline mid-list clause into a following sentence so the field enumeration reads unbroken, and justified the choice by the absence of a candidate block so the sentence explains rather than overrides §3.5.

Step 7 applied no implementation fixes and no deletions; both edits pin genuine PRD silences the impl resolved (output canonicalisation / input tolerance for instant precision, and the summary's week anchor). No other Step 7 item required a PRD change.

Orchestrator note: Step 8 was run (not skipped) because Step 7 ran 2 iterations with 10 `test_suite/` fixes; the skip condition requires all four fix counts to be zero. Orchestrator verified `PRD_FINALIZED.md` is NOT byte-identical to `PRD.md` — diff shows exactly the two revised lines claimed above.

## Step 9: Complete PRD — 2026-09-05T20:40:29.835Z

`workspace/PRD_COMPLETED.md` produced by three sequential, implementation-module-partitioned passes over one shared file (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to re-copy, and each confirmed it ran no `cp`). **62 edits total — 56 ambiguity-pins, 6 mismatch-revisions.** All edits are in-paragraph inserts/revisions: 413 lines in, 413 lines out, 101,631 -> 119,137 chars (+17,506; +17.2%), 102 lines differing from `PRD.md`.

### Pass 1 — app.py, response.py, errors.py, auth.py, db.py, validation.py, routes_core.py (20 edits: 17 ambiguity, 3 mismatch)
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars; `api_request_timestamp` read from the logical clock, not wall-clock — `response.py:22,28`
- §2.3 ¶1 — insert — ambiguity — non-integer `limit`/`offset` refused; empty-string value takes the default — `response.py:56-67`
- §2.3 ¶2 — insert — ambiguity — insertion order is the tiebreak when records share a `created_at` — `db.py:199`
- §2.3 ¶2 — insert — ambiguity — empty-string filter treated as absent; unoffered query params ignored — `validation.py:196-221`
- §2.4 — insert — ambiguity — unrecognised body keys ignored; explicit `null` == key omitted; a PATCH with no recognised field still bumps `updated_at`/`version` — `validation.py:34-35`, `routes_core.py:126,195,311`
- §2.5 — insert — ambiguity — clock may move backwards; response `data` is the single `current_utc` field — `routes_core.py:24-30`
- §2.5 — insert — ambiguity — non-zero UTC offsets converted, zone-less values read as UTC, unparseable refused with `ERR_INVALID_REQUEST` — `db.py:94-109`, `validation.py:152-167`
- §2.6 band 4 — insert — ambiguity — top-level list endpoints run no ownership check and are not implicitly narrowed to the caller — `routes_core.py:277`, `routes_offers.py:146`, `routes_moves.py:101`
- §2.6 band 5 — insert — ambiguity — league range/ordering cross-checks are band-5 `ERR_INVALID_REQUEST`, after single-field checks and re-checked on the merged record — `routes_core.py:37-45,124`
- §2.6 band 5 — insert — ambiguity — body parsed regardless of Content-Type; absent/empty body == `{}`; non-object JSON fails band 5 — `validation.py:15-27`
- §2.10 — insert — ambiguity — trailing slash tolerated on every path — `app.py:24`
- §3.1 — insert — ambiguity — `education_reserved_minutes` must be >= 0 — `routes_core.py:71`
- §3.1 — insert — ambiguity — PATCH re-checks each range and the merged orderings; non-listed charter terms ignored — `routes_core.py:102-126`
- §3.1 — insert — ambiguity — budget may be lowered below commitment; `uncommitted_salary_cents` goes negative rather than the PATCH being refused — `routes_core.py:190-196`
- §3.1 — revise — **mismatch** — counters are re-derived on every read (not "recomputed at four contract events"); prize figure also moves on calculate/approve/void; `wellness_flag_count` alone is stored, advanced only by a BREACH escalation — `serializers.py:59-73`, `calc.py:161-187`, `cascade.py:61`
- §3.1 — revise — **mismatch** — cap-summary returns `organization_id` and its counters on the same derived basis as the organization read (not "as stored"), and carries no `id`/`created_at`/`updated_at`/`version` — `routes_core.py:214-231`
- §3.2 — insert — ambiguity — `birth_date` is exactly ten characters, any other spelling refused, returned verbatim — `db.py:112-122`, `serializers.py:85`
- §3.2 — insert — ambiguity — `guardian_name` 1-120, `guardian_email` 1-320 with no format check — `routes_core.py:250-251`
- §3.2 — insert — ambiguity — with no current organization and none in the request, `is_minor` falls back to the 18-year default threshold — `calc.py:118-140`
- §3.2 — insert — ambiguity — consent overwrites both guardian fields, leaves an existing weekly cap untouched when omitted, and is accepted for a non-minor / when already on file — `routes_core.py:315-330`
- §5 — revise — **mismatch** — "every rejection" softened to rules-produced rejections, plus the unrouted-path `ERR_NOT_FOUND` (404) and unsupported-method `ERR_METHOD_NOT_ALLOWED` (405) which are absent from the table — `app.py:38-51`

Left alone deliberately (already pinned uniquely, non-obvious): §2.5 half-open vs deadline conventions; the three-condition free-agency cooldown incl. `last_release_organization_id`; `committed_salary_cents` summing frozen charges over ACTIVE+SUSPENDED while `active_roster_count` counts only ACTIVE; `final_committed_cents` over the same set; age-anniversary-counts-as-reached; the §4 role lists for all 17 pass-1 endpoints (verified decorator-by-decorator); the §2.7 round-half-up/basis-point/duration constants.

### Pass 2 — routes_offers.py, routes_practice.py, cascade.py (24 edits: 21 ambiguity, 3 mismatch)
- §3.3 — insert — ambiguity — offer-creation ownership judged from the body's `organization_id` before the shape band; body FKs resolved org -> player -> supersedes; no calendar/lifecycle gate at send time — `routes_offers.py:71-95`
- §3.3 — revise — ambiguity — lazy expiry on a list read sweeps the whole offer collection before filters/paging, so a status filter matches post-sweep statuses; the transition bumps `updated_at`/`version` on a read — `routes_offers.py:151-153,30-36`
- §3.3 — insert — ambiguity — counter fields bound by their headline ranges (>=0 / 0-10000 bp / 0-80 h) — `routes_offers.py:175-177`
- §3.3 — insert — ambiguity — openness guard settled before the round ceiling (revise on a re-`SENT` exhausted offer -> `ERR_OFFER_NOT_OPEN`) — `routes_offers.py:207-210`
- §3.3 — revise — **mismatch** — "an agent gets three bites" was wrong: with ceiling 3 a counter is permitted at `round_number` 1 or 2 -> two counters and two revisions, `round_number` topping out at 3 — `routes_offers.py:182,224`
- §3.3 — insert — ambiguity — band-13 internal order: salary floor -> prize-split floor -> streaming ceiling, all before the §3.4 cap test — `routes_offers.py:47-60,287-293`
- §3.3 — revise — ambiguity — a named `supersedes_offer_id` is swept for expiry first (lands `EXPIRED`, not `SUPERSEDED`); a terminal target is left as-is and the new offer is created either way — `routes_offers.py:125-129`
- §3.4 — insert — ambiguity — the acceptance cascade versions the organization record despite its derived counters — `routes_offers.py:334`
- §3.4 — revise — ambiguity — sibling supersession spans every organization and is *not* preceded by lazy expiry — `routes_offers.py:336-344`
- §3.5 — revise — ambiguity — `timezone` mandatory, 1-64 chars, unvalidated beyond that — `routes_practice.py:36`
- §3.5 — insert — ambiguity — `timezone` is not amendable; supplying it in a PATCH is ignored — `routes_practice.py:70-76`
- §3.5 — insert — ambiguity — booking FKs resolved org -> participants in array order -> team house, with no cross-check — `routes_practice.py:130-132`
- §3.5 — revise — ambiguity — `starts_from`/`starts_to` bound `starts_at` inclusively — `routes_practice.py:220-223`
- §3.5 — insert — ambiguity — gates run check-by-check across the whole attendee list (employment -> consent -> weekly cap -> wellness hold), attendees in `participant_player_ids` order — `routes_practice.py:142-156`
- §3.5 — insert — ambiguity — the cap's ceilings come from the league §3.2 resolves for the player — `calc.py:99-104,118-128`
- §3.5 — insert — ambiguity — the education subtraction is not floored at zero; a negative cap refuses every booking and is reported verbatim by the obligation summary — `calc.py:285-291`
- §3.5 — insert — ambiguity — any coaching-staff caller may complete/cancel; an omitted/null `coach_note` keeps the booking note — `routes_practice.py:229-241,265-280`
- §3.5 — revise — **mismatch** — cancellation fires on *any* escalation, including `WARNED`->`BREACH` (not only departures from `COMPLIANT`), spans any house/org; a non-escalating completion cancels nothing — `cascade.py:49-65`
- §3.5 — revise — **mismatch** — `CONTRACT_SUSPENDED` is also written by the §3.9 termination cascade, not just suspension — `cascade.py:120`
- §3.6 — insert — ambiguity — omitting/nulling `reported_streaming_minutes_7d` keeps the last figure; `last_self_reported_load` is always overwritten — `routes_offers.py:414-416`
- §3.6 — insert — ambiguity — a cap of zero or below skips the division: practice component 1 if any minutes were counted, else 0 — `calc.py:318-321`
- §3.6 — insert — ambiguity — suspension versions the organization record — `routes_offers.py:397-400`
- §3.6 — insert — ambiguity — the obligation summary derives *both* burnout figures afresh (its rolling value can differ from the persisted `burnout_score`) and never escalates — `serializers.py:184-185`
- §3.9 — revise — ambiguity — termination's block cancellation is limited to `starts_at` strictly in the future, spans any house/org, writes `cancel_reason` `CONTRACT_SUSPENDED` — `cascade.py:16-32,120`

Left alone deliberately: association terms skipped on a counter but applied on revise/accept; the education-vs-workload tie-break; candidate-only turnaround padding vs unpadded participant overlap and the exact-capacity allowance; `scheduled_minutes` counting SCHEDULED+HELD across all orgs with the candidate included, and the minor-only streaming charge; the rolling `(now-7d, now]` window and the season variant's ceil-to-week floored at 1; the `>=70`/`>=85` escalation-only ladder and the BREACH-only hold/flag asymmetry.

### Pass 3 — routes_sponsorship.py, routes_prizes.py, routes_moves.py (18 edits: 18 ambiguity, 0 mismatch)
- §3.7 — insert — ambiguity — which contract is "at issue" for exclusivity: payload contract at placement vs. each contract this deal already carries a non-VOIDED deliverable on at activation (empty set => a first activation never conflicts) — `calc.py:484`
- §3.7 — insert — ambiguity — deal creation judges ownership from the body's `organization_id` before shape validation — `routes_sponsorship.py:32`
- §3.7 — insert — ambiguity — the placed deliverable's contract need not belong to the deal's organization; no cross-org comparison and no error — `routes_sponsorship.py:121`
- §3.7 — insert — ambiguity — named the derived deal field `per_deliverable_fee_cents` — `serializers.py:247`
- §3.7 — revise — ambiguity — named the derived deal field `earned_fee_cents` — `serializers.py:248`
- §3.7 — insert — ambiguity — on submit the contract's ACTIVE requirement precedes the assignment's own status guard; review imposes no contract requirement — `routes_sponsorship.py:249`
- §3.7 — insert — ambiguity — an omitted/null `submission_note` or `review_note` leaves the earlier round's note in place — `routes_sponsorship.py:253`
- §3.7 — insert — ambiguity — every approval advances the parent deal's `version`; a rejection touches only the assignment — `routes_sponsorship.py:281`
- §3.7 — insert — ambiguity — single-assignment endpoints accept an org-backed caller matching *either* parent org, and require a player-backed caller to match the contract's player — `routes_sponsorship.py:202`
- §3.8 — insert — ambiguity — distribution creation resolves `league_id` before `organization_id` in band 6 — `routes_prizes.py:32`
- §3.8 — insert — ambiguity — a zero weight total is not an error/division: all floor shares are 0 and the remainder step gives the whole pool to one row — `calc.py:531`
- §3.8 — insert — ambiguity — allocation rows are inserted in the eligible contracts' `created_at` order, which is the read order — `routes_prizes.py:100`
- §3.8 — insert — ambiguity — a void does not wind back `calculated_by_user_id` / `approved_by_user_id` — `routes_prizes.py:151`
- §3.8 — insert — ambiguity — the distribution-scoped allocations read performs no ownership check, unlike the contract-scoped read — `routes_prizes.py:178` vs `routes_offers.py:432`
- §3.9 — insert — ambiguity — filing judges ownership from the body before shape validation; FKs resolved org, transfer-to org, player, contract — `routes_moves.py:27`
- §3.9 — insert — ambiguity — `effective_at` is audit-only: never season-validated, never read by a settlement/cap/window figure — `routes_moves.py:79`
- §3.9 — insert — ambiguity — a RELEASE filing is subject to neither calendar check; filing verifies no contract<->org/player consistency and allows several concurrent PENDING moves; the single move read is ownership-checked on both `organization_id` and `player_id` — `routes_moves.py:58,89`
- §3.9 — insert — ambiguity — the SIGN cap re-test substitution is pure arithmetic whether or not the contract currently contributes to `committed_salary_cents` — `routes_moves.py:142`
- §3.9 — insert — ambiguity — no roster-lock re-test at execution; no stage of a move tests the contract's own `contract_status` — `routes_moves.py:158`
- §3.9 — insert — ambiguity — a TRANSFER_OUT is settled entirely on the releasing side: the receiving org is recorded only, gets no contract, no counter change, no version bump — `routes_moves.py:183`, `cascade.py:98`
- §3.9 — insert — ambiguity — enumerated the five settlement fields a reversal zeroes and pinned that `gross_transfer_fee_cents`, `effective_at` and both audit stamps survive — `cascade.py:138`

Left alone deliberately: the `active_roster_count` - 1 >= `min_roster_size` departure test, which the impl matches literally even when the terminating contract is already SUSPENDED; reversal restoring a previously-SUSPENDED contract to ACTIVE (§3.9 already states TERMINATED -> ACTIVE unconditionally); `placement` recorded but never entering the waterfall; the commission tier selected from a possibly-negative gross settlement; §2.6's band-4 sentence already covering top-level list reads.

### Structural verification (pass 3's final-pass duty, re-checked independently by the orchestrator)
Well-formed markdown; five top-level sections `## 1`-`## 5` present and in order at lines 3/11/144/280/350; all subsections §2.1-§2.10 and §3.1-§3.9 in order; §4 endpoint table = **63 rows** (65 pipe-lines incl. header + separator); §5 error table = **58 rows**, statuses cross-checked against `errors.py::ERROR_STATUS` — all match; file ends on the complete final table row `| ERR_NO_ELIGIBLE_CONTRACTS | 422 |`, not mid-sentence.

Orchestrator verification: `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (102 differing lines, +17,506 chars), so the scan genuinely ran — the known failure mode where Step 9 only performs the `cp` did not occur. The §4 and §5 tables are byte-identical to `PRD.md`'s apart from pass 1's §5 preamble revision, confirming no table was disturbed. Step 9 touched neither `implementation/` nor the tests, so the clean 8-round sweep from Step 7 (8x 86/86) remains the standing evidence; no re-sweep was required.

## Pipeline complete — 2916 delivered
All nine steps finished. Final artifact set: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files) + test_suite/ (conftest + 18 modules, 86 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (16 modules + start.sh), results.{1..8}.json}.
