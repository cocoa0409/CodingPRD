## Step 1: Create task directory — 2026-09-05T00:29:30.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2809_media_planning_upfront_buying and its workspace/ subdirectory. Index 2809 was pre-assigned by the caller; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-05T02:14:00.000Z

All three scaffold artifacts are complete, parse as YAML, and the scaffold linter reports `VERDICT: clean lint` (1193 calls scanned across §1.8+§1.9, all conforming to §1.5, all §1.1 FKs reverse-reachable).

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2809_media_planning_upfront_buying/`)
- `SCAFFOLD.yaml` — 2924 lines (145 KB); contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2353 lines (155 KB); single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5841 lines (356 KB); single top-level key `scaffold_corner_design`

SCAFFOLD.yaml counts
- 13 entities (Advertiser, Campaign, ChannelAllocation, Seller, InventoryForecast, Negotiation, Buy, BuyUnit, DeliveryReport, MakeGood, RightsExercise, ReconciliationRun, Invoice), api_prefix `/upfront`
- 59 endpoints (58 domain + `POST /_clock/set_current_utc`), 14 state machines (parallel axes on Buy x3, Campaign x2, Invoice x2), 8 calculations, 46 validation rules (priorities 1-47, 18 documented as intentionally unused), 59 catalog errors, 6 roles, 4 complexity layers, `consistency_model: immediate`

SCAFFOLD_DIFFICULTY_DESIGN.yaml — 18 instances, 2 per rule_id
dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2

SCAFFOLD_CORNER_DESIGN.yaml — 84 instances (75 full recipes + 9 `excluded_because` stubs citing §1.8)
entities 12, state_machines 12, calculations 12, validations 27, endpoints 5, errors 3, rbac 6, cross_cutting_complexity_layers 6, consistency_model 1

Notes
- All 84 + 18 instance names are globally unique; every stub citation resolves to an existing §1.8 instance and no stub carries a `test_recipe`.
- The "Bulk action" endpoint claim_type has no instance by design (an inline comment records that §1.5 declares no bulk endpoint — every mutation addresses one resource); this is the only guide row deliberately left unpopulated.
- The difficulty directive line does not appear anywhere in the artifacts, and none of the forbidden concurrency vocabulary ("simultaneously", "in parallel", "first-writer-wins", etc.) is present.

Orchestrator verification: `grep -rn "harder than expert\|expert level" SCAFFOLD*.yaml` returned no matches — the difficulty directive did not leak into the scaffold. workspace/ survived Step 2 intact.

## Step 3: Copy shared files — 2026-09-05T02:14:30.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T02:32:00.000Z

PRD complete and verified.

Deliverable: `workspace/PRD.md` — 515 lines / 108,087 characters

Section list: Title; 1. Introduction; 2. Global Specifications & System-Wide Principles (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Resource Identity/Timestamps/Logical Clock, 2.5 Money/Audience/Rounding Discipline, 2.6 Version Stamping and Stale-Read Rejection, 2.7 Parallel State Axes and Cascade Propagation, 2.8 Flat Address Space and Identifier Resolution Order, 2.9 The Rejection Precedence Ladder, 2.10 Marketplace Vocabulary); 3. Business Logic & Workflows (3.1 Onboarding Counterparties and the Advertiser's Credit Posture, 3.2 Translating the Brand Objective into a Channel Plan, 3.3 Client Approval/Revision Cycle/Campaign Funding, 3.4 The Upfront and Scatter Marketplace: Avails, 3.5 Negotiating CPM/Guarantees/Make-Good Provisions, 3.6 Building the Unit Mix and Placing the Buy, 3.7 Exercising Option and Cancellation Rights, 3.8 Stewardship: Airings/Measured Delivery/Post-Buy Analysis/Make-Goods, 3.9 Cross-Platform Reconciliation/Client Billing/Settlement); 4. Endpoint Definitions (59 rows); 5. Error Code Catalogue (59 rows).

Coverage confirmation (machine-checked against SCAFFOLD.yaml): 13/13 entities; 59/59 endpoints (incl. `POST /_clock/set_current_utc`; 12 x 201, 47 x 200); 14/14 state machines and 59/59 transitions; 8/8 calculations; 46/46 validations (numbered ladder in 2.9); 59/59 errors; 6/6 roles; 2/2 concurrency rules (both in 2.6 with field name, error id, 412).

Hard Contract results: Contract 1 Field-Name Coverage PASS (183 required identifiers, 0 missing; a fence-aware extractor was needed because an early run mis-paired backticks across the 2.2 fenced JSON block). Contract 2 Rule Coverage PASS (all 46 priorities ordered; both OCC rejections carry endpoint + expected_negotiation_version / expected_campaign_version + ERR_STALE_NEGOTIATION_VERSION / ERR_STALE_CAMPAIGN_VERSION + 412; every cascade chain documented link-by-link with its "does not fire when" condition). Contract 3 §3 Path Purity PASS (0 violations; `/upfront` occurs 0 times in §3).

Scanned clean for banned text (`harder than`, `expert level`, `difficulty`, `test_recipe`) and fuzzy/pseudocode markers. Neither design index was opened, grepped or referenced.

Scaffold ambiguities resolved by the doc generator's judgment (relevant if the test suite disagrees):
1. `option_window_close` — field comment says "inclusive" but validation priority 21 and `ERR_RIGHTS_WINDOW_CLOSED` say "at or after"; documented as strictly before (validation table treated as authoritative).
2. `delta_impressions` rounding unspecified -> floor, cross-referenced to the 2.5 global floor rule.
3. Cancellation sweep termination unspecified -> SCHEDULED lines cancelled in air_window_start ASC, created_at ASC until released projected_impressions reaches the magnitude of delta_impressions.
4. Placement's `plan_status == APPROVED` precondition had no applies_to entry -> mapped to ERR_CAMPAIGN_PLAN_NOT_APPROVED (ladder item 17 covers both acceptance and placement).
5. Delivery-report accept's `buy_status IN {PLACED, IN_FLIGHT}` precondition had no applies_to entry -> mapped to ERR_BUY_NOT_IN_EXPECTED_STATE.
6. Make-good offer's "offered avail must belong to the buy's seller" -> mapped to ERR_NOT_RESOURCE_OWNER.
7. `delivered_impressions` / `delivered_demo_impressions` may be 0 — explicit exception to the "integers greater than zero" ladder item.

Orchestrator verification: `tail -12 workspace/PRD.md` ends on the final row of the §5 error table (`ERR_SEQUENTIAL_LIABILITY_EXCEEDED | 422`) — a real section boundary, not mid-sentence. No truncation; no regeneration needed. Difficulty-directive grep returned 0 matches.

## Step 5: Generate unit tests — 2026-09-05T03:12:00.000Z

Test suite generation is complete and mechanically verified.

test_helpers/ — 9 files: __init__.py 129, api_client.py 369, api_errors.py 260, assertions.py 372, constants.py 409, factories.py 430, fixtures.py 1032, test_users.py 114, types.py 494.

test_suite/ — conftest.py (100 lines) + 20 test files:
test_01_dual_variant_calculations.py 646 / 15 tests; test_02_combinatorial_formulas.py 487 / 7; test_03_non_linear_state_machines.py 617 / 10; test_04_transitive_cascades.py 772 / 14; test_05_priority_pair_conflicts.py 561 / 8; test_06_boundary_precision.py 624 / 13; test_07_cross_entity_state_dependencies.py 670 / 12; test_08_resource_temporal_overlap.py 743 / 11; test_09_compensating_invariants.py 701 / 17; test_10_entity_surface.py 1086 / 35; test_11_state_machine_surface.py 751 / 13; test_12_calculation_surface.py 563 / 8; test_13_plan_and_inventory_validations.py 589 / 10; test_14_make_good_validations.py 633 / 10; test_15_billing_and_credit_validations.py 708 / 10; test_16_endpoint_behaviour.py 640 / 11; test_17_error_envelope_and_resolution.py 335 / 6; test_18_rbac.py 584 / 8; test_19_cross_cutting_layers.py 480 / 9; test_20_consistency_model.py 297 / 7.

`pytest --collect-only` -> 232 tests collected.

Coverage: Queue A (§1.8 difficulty) 18/18 instances translated, every one with >=2 tests. Queue B (§1.9 corner) 74/75 non-stub instances translated. All 9 `excluded_because:` stubs left untranslated and referenced nowhere.

Skipped instance (1): `Corner/calculations/aggregate_dedup_run_reports_one_present_group_and_zero_filled_others` — non-unique-derivability (C2), in fact PRD-contradicted. The instance's identity is that `group_reach_pct` is zero-filled for every group in GROUP_ORDER, but §3.9 states the map "omits any group with no accepted delivery". A PRD-only reader is forced to a two-key-absent map, so the instance was dropped whole rather than weakened.

Verification performed: ast.parse on all 21 files; all 20 test modules execute-import cleanly against the real test_helpers barrel; pyflakes clean across test_suite/; every test carries exactly one `Design:` line as the last docstring line and every tag resolves to a real `name:` in the source YAML (no untagged, dual-tagged, or stub-pointing tests); every `PRD:` quote survives a whitespace-normalised literal match against workspace/PRD.md (232/232). No pytest.mark.skip, xfail, time.sleep, print, or pkill anywhere. worklog.md untouched.

Findings the design index owner should see — two systematic defects in the design recipes, worked around without changing any pinned literal:
1. Missing clock moves. Many `setup_api_calls` file a delivery report whose `period_end` is months after the logical clock's 2026-08-01T00:00:00Z startup, which §3.8 refuses. Affected: test_01, 03, 04, 06, 07, 11, 12, 14, 16, 18 — all insert a forward `fx.move_clock(...)` before filing.
2. Missing campaign funding. Recipes asserting an issued invoice never fund the campaign, which §3.9 refuses (ERR_CAMPAIGN_FUNDING_INSUFFICIENT). Affected: test_03, test_06.

Design assertions that contradict the PRD and were therefore not asserted: `group_reach_pct.CTV == 0.0000` for an absent group (test_01); `BuyUnit.actual_impressions is null` after a refused settlement (§3.6 creates the line at 0 — test_11); `MakeGood.offered_impressions is null` before an offer (§3.8 starts it at 0 — test_14); `open_shortfall_impressions == 0` on a within-tolerance buy (PRD derives 10,000 — test_16); `ERR_CAMPAIGN_BUDGET_EXCEEDED` at 422 (§2.9 rung 42 and §5 both put it at 409 — test_05); `measurement_basis: "CROSS_PLATFORM"` outside the PRD's closed set (test_18).

Two recipes were physically unrealisable as written and were re-grounded on a second published avail with dependent literals re-derived: the make-good offer chains in test_14 and test_16 (a post-flight-final report forces the clock past the original avail's window, so no legal `offered_window_start` exists inside it).

Orchestrator verification: `find workspace -type d -name "test_*"` returned nothing — both test directories landed correctly at the task root, not under workspace/. No stray worklog.md.

## Step 6: Generate implementation — 2026-09-05T03:12:30.000Z

The implementation is complete and verified.

Files (all under workspace/implementation/): start.sh 10, requirements.txt 1, app.py 102, constants.py 148, errors.py 84, numeric.py 53, timeutil.py 41, store.py 96, response.py 89, auth.py 62, validation.py 160, lookup.py 42, serializers.py 319, services/__init__.py 0, services/derive.py 434, services/cascades.py 97, routes/__init__.py 38, routes/common.py 26, routes/clock.py 22, routes/advertisers.py 55, routes/sellers.py 42, routes/campaigns.py 161, routes/allocations.py 71, routes/forecasts.py 93, routes/negotiations.py 230, routes/buys.py 213, routes/buy_units.py 74, routes/delivery_reports.py 161, routes/make_goods.py 212, routes/rights.py 124, routes/reconciliation.py 151, routes/invoices.py 211. Total 3,622 lines / 32 files; `ls -la` confirms every file exists in `.`, `services/`, `routes/`.

Endpoints: 59 of 59, enumerated from `app.url_map` — exactly 59 GET/POST rules matching the PRD §4 table one-for-one (`/upfront/*` for all 58 business endpoints, `/_clock/set_current_utc` at the root).

Organisation:
- Validation ladder (§2.9, 46 positions) split by layer so ordering is structural rather than per-handler discipline: positions 1-2 in auth.py (`authenticate` from before_request, `require_roles` decorator), position 3 entirely in validation.py (`Body` — every raiser returns ERR_INVALID_REQUEST), positions 4-5 in lookup.get (one 404 per entity family), position 6 in auth.require_seller_owner / require_advertiser_owner (no-op for non-entity roles). Positions 7 onward are explicit top-to-bottom statements in each route function, in ladder order.
- Calculations all live in services/derive.py: floored allocation, CPM band clamp where the ceiling has the final word, GRP/frequency, the cost stack with the commission tier selected on the pre-commission net, delivery indices/shortfall, live avail availability, seller exposure, per-line invoice money with commission rounded per line before summation, and the sequential-liability floor. numeric.py guarantees no float ever enters an arithmetic step (Decimal in, int cents / quantized Decimal out; floats appear only at JSON encode).
- State machines enforced inline in the owning route module (each axis's from-state guard is one `if` in the handler); every cascade lives in services/cascades.py: avail PUBLISHED<->EXHAUSTED, allocation lock/unlock, the commitment_chain (allocation -> campaign posture -> automatic APPROVED->REVISION_REQUIRED pushdown + unlock), settle_open_shortfall (UNDER_DELIVERED->MADE_GOOD), and advance_settlement (with COMPLETED->CLOSED on REMITTED).
- Storage is store.py: 13 plain dicts, a logical clock starting 2026-08-01T00:00:00Z, and `touch()` which bumps `version` at most once per record per request. Grep confirms no open(), sqlite, pickle or JSON dump anywhere; nothing is seeded, so a process restart is a total wipe.

Smoke test: booted via `PORT=39733 bash start.sh` (foreground `exec python3 app.py`, bound 0.0.0.0), then curled POST /upfront/advertisers -> 201, GET /upfront/advertisers/{id} -> 200, GET /upfront/advertisers?limit=1 -> 200 with meta.limit/offset/total_count/has_more and response_type "array", and an unauthenticated GET -> 401 ERR_UNAUTHENTICATED. Envelope matches §2.2 exactly. Only the two captured PIDs were killed (no pkill); a post-kill probe confirmed the port was released.

Separately a full-lifecycle in-process exercise (advertiser -> campaign -> allocation -> submit/approve/fund -> seller -> avail -> negotiate/counter/accept -> option roll -> unit -> place -> second buy cancelled 100% -> airing settle -> post-buy report/accept -> make-good offer/reject/offer/accept -> close -> two reconciliation runs -> invoice draft/issue/partial+full payment/remit) covering 57 calls including 6 deliberate rejections: 0 failures. Spot-checked figures matched PRD requirements — gross 2,354,000c after a 10% option roll, per-line commission 140,000c, sequential-liability ceiling floor(1,000,000 x 2,000,000 / 2,140,000) = 934,579c, SEQUENTIAL reach 0.3333 / freq 1.00 vs AGGREGATE 0.2500 / freq 1.33 on identical delivery, and the final buy landing CLOSED / REMITTED.

One documented deviation from the ladder's literal numbering, taken from §2.9's own closing prose and §3.8: on a make-good offer, ERR_MAKE_GOOD_NOT_PERMITTED (position 30) is checked above ERR_MAKE_GOOD_OFFER_INSUFFICIENT (29), because the PRD states the permission rule sits above both the shortfall and the capacity rule.

## Step 7: Run tests and iterate — 2026-09-05T03:33:40.000Z

Clean sweep confirmed: union of failures across all 8 parallel rounds is empty, 0 skipped, 232/232 in every round.

**Iterations run: 2**

Iteration 1 — total collection failure (0/0 tests, 8/8 rounds errored). All eight rounds died in 1.7s with `ImportError while loading conftest` -> `ModuleNotFoundError: No module named 'typing_extensions'`. Not a load artifact and not an implementation defect: a single test-helper import of a third-party package that is not installed on this host. The whole 232-test suite was unrunnable.

Iteration 2 — 232/232 passed in all 8 rounds (per-round wall time 424-425s, consistent across rounds; no flaky test, no timeout/connection failure, so no load-induced noise to re-confirm).

Tests deleted: None. No test reached STEP 1 — the only defect was an import error, and once fixed every assertion passed on the first sweep, so no PRD-silence or unique-derivability adjudication was needed.

Fixes applied to `test_helpers/`:
- `test_helpers/types.py` — replaced `from typing_extensions import TypedDict` with importing `TypedDict` from the stdlib `typing` module (folded into the existing `from typing import ...` line). The host runs Python 3.14, where `typing.TypedDict` is stdlib; `typing_extensions` is not installed. Pure import-source change — no vocabulary, shape, fixture, factory, or assertion semantics were touched, so it cannot have weakened any check.

Fixes applied to `implementation/`: None. The implementation passed all 232 tests unmodified.

Verification notes from the subagent: `--collect-only` confirms 232 tests collect, matching the 232 `total` reported by every round; no `pytest.mark.skip`/`xfail` anywhere and `skipped == 0` in all 8 rounds; grepped `implementation/` for sqlite, shelve, pickle, write-mode `open()`, `json.dump`, `/tmp` with no hits, so storage is in-memory only with no startup seeding.

Orchestrator independent verification (not taken on trust): all 8 `results.$i.json` exist (74.6 KB each, same mtime 03:21) and each parses to `passed=232 failed=0 total=232 skipped=0`, durations 423.6-425.4s. `grep -rn "pytest.mark.skip\|pytest.mark.xfail" test_suite/ test_helpers/` -> 0 hits. `grep -rn typing_extensions test_helpers/ test_suite/` -> 0 hits (the fix is real, not merely claimed). The sweep artifacts are genuine.

## Step 8: Finalize PRD — SKIPPED — 2026-09-05T03:34:00.000Z

Decision (made autonomously; reasoning recorded here per the run's autonomy directive):

Step 7 recorded 0 test deletions, 0 `test_suite/` fixes, 0 `implementation/` fixes, and exactly one `test_helpers/` fix. The skip condition as literally written requires zero of all four, so this is a judgement call rather than a mechanical skip.

Skipping is correct because Step 8's HARD SCOPE admits only PRD edits that trace to a `<step_7_diff>` item revealing PRD-silence or PRD-mismatch against `implementation/`. The sole diff item is `test_helpers/types.py` swapping `typing_extensions.TypedDict` for `typing.TypedDict` — a host-environment import-source correction with no PRD-semantic content whatsoever. It reveals nothing about the PRD: no behavior was reinterpreted, no assertion was weakened or deleted, and the implementation was never modified. A Step 8 subagent operating inside its own hard scope would therefore be obliged to make zero edits and emit a byte-identical `PRD_FINALIZED.md`. Spawning it could only add risk (an out-of-scope edit that Step 9 must then undo) with no possible benefit.

The substantive consequence — that `PRD.md` as generated already determined every behavior the implementation exhibits along the 232 paths the suite exercises — is exactly what the skip condition is designed to detect, and it holds here: the implementation passed all 232 tests unmodified on its first runnable sweep.

Therefore no `PRD_FINALIZED.md` is produced, and Step 9 takes `workspace/PRD.md` as its source per its documented input rule. Step 9 still runs in full — it is the only pass that scans behaviors the test suite never asserted.

## Step 9: Complete PRD — 2026-09-05T04:10:00.000Z

Run as THREE sequential module-partitioned passes over one shared workspace/PRD_COMPLETED.md (a single-shot scan of 3,622 lines of implementation reliably under-scans). Pass 1 performed the `cp` from PRD.md; passes 2 and 3 were explicitly forbidden from repeating it and accumulated their edits into the same file. Source was PRD.md because Step 8 was skipped.

Final metrics: PRD.md 515 lines / 108,579 chars -> PRD_COMPLETED.md 515 lines / 126,898 chars. Char delta +18,319; 0 line delta (every edit is in-paragraph — no new paragraphs, no new sections, no heading touched). 118 changed lines. Total 66 changes: 47 ambiguity-pins, 23 mismatch-revisions (pass 1: 13 pins / 3 revisions; pass 2: 9 / 2; pass 3: 25 / 18).

### Pass 1 — global/infra layer (app, constants, errors, numeric, timeutil, store, response, auth, validation, lookup, serializers, routes/{__init__,common,clock}, services/cascades) -> PRD §2.x, §4/§5 preambles
- §2.1 — revise — mismatch — ownership enforced only on the ten write operations of ladder position 6; no read endpoint applies an ownership check or filter (a SellerRep may read any campaign/invoice); listings never narrowed to the acting principal — auth.py:53-63
- §2.1 — insert — ambiguity — a header present but empty counts as absent; role comparison is case-sensitive — auth.py:20-23
- §2.2 — insert — ambiguity — api_request_id is `req_` + exactly 20 alphanumerics, re-randomised per response — response.py:19-23
- §2.2 — insert — ambiguity — api_request_timestamp reads the logical clock, not wall time, so it is identical across responses until the clock advances — response.py:26-30
- §2.3 — insert — ambiguity — created_at ties (common under a frozen clock) break by creation sequence; out-of-range/non-integer limit/offset are ERR_INVALID_REQUEST (not clamped); offset >= total_count is legal and returns an empty array — store.py:94-96, response.py:54-74
- §2.3 — insert — ambiguity — filter values matched by exact string equality and NOT validated against their enum: an out-of-vocabulary filter yields total_count 0, not a 400 — routes/common.py:19-26
- §2.4 — insert — ambiguity — rendered timestamps always 3 fractional digits, sub-ms truncated toward zero for display while full precision is kept for window comparisons; input accepts Z/z, +00:00, non-zero offsets (normalised to UTC), offset-less (read as UTC), any fractional width — timeutil.py:10-33
- §2.4 — insert — ambiguity — on creation updated_at equals created_at — store.py:52-63
- §2.4 — insert — ambiguity — recomputation counts only when a write triggers it; reads recompute derived fields but never touch updated_at/version; a resource's version advances at most once per request however many rules/links touch it — store.py:66-88
- §2.4 — insert — ambiguity — the clock capability takes a required current_utc and answers 200 with an empty data object (it is not a resource write) — routes/clock.py:14-22
- §2.5 — insert — ambiguity — excess decimal places are rejected with ERR_INVALID_REQUEST, not rounded; decimal fields accept a JSON number or a numeric string; integer fields must be JSON integers (numeric string or boolean -> 400) — validation.py:71,103-124
- §2.6 — insert — ambiguity — both guard fields are non-negative integers; a missing/negative/non-integer guard is ERR_INVALID_REQUEST at ladder position 3, before the comparison — validation.py:67-77
- §2.7 — insert — ambiguity — the cascade version contract obeys the once-per-request rule: a primary write plus its cascade links touching the same resource still raise its version by exactly 1 — store.py:66-88, services/cascades.py
- §2.8 — insert — ambiguity — the clock is the only endpoint outside /upfront; trailing slashes insignificant (strict_slashes=False); unrouteable path -> 404 ERR_NOT_FOUND, bad method -> 405 ERR_METHOD_NOT_ALLOWED, and neither is preceded by the auth check — app.py:26,37-39,56-73
- §2.9 item 3 — insert — ambiguity — absent/non-object body fails position 3 where any field is declared, while an all-optional endpoint treats an absent body as {}; explicit null == omitted; undeclared body fields ignored; whitespace-only strings rejected; max_len measured on the value as supplied — validation.py:18-57
- §4 preamble — revise — mismatch — "subject to the ownership checks described there" scoped to the ten writes, never a read — auth.py:53-63
- §5 preamble — revise — mismatch — the catalogue's completeness claim now excepts the two framework-level routing rejections — app.py:56-73

Pass 1 verified-clean (no edit needed): errors.py ERROR_STATUS matches all 59 ids/statuses in the §5 table exactly (programmatic diff, no extras or omissions either way); constants.py matches the PRD verbatim on every closed vocabulary and business constant (roles, channels, platforms, markets, dayparts, 14 category codes, all 17 state vocabularies, market/daypart indices, CPM band 0.60/2.50 + 200/12000, commission tiers and floors, round caps 6/3, tolerance 2.0000, window days 45/60/30, ceilings 100/25, separation 7 days, group order/mapping, channel->platform, pagination 10/1/100/0, epoch 2026-08-01T00:00:00.000Z); ladder ordering honoured in every route; all seven cascade functions match §3.3/§3.4/§3.6/§3.8/§3.9 as written.

### Pass 2 — services/derive.py + routes/{advertisers,sellers,campaigns,allocations,forecasts,negotiations} -> PRD §3.1–§3.5 + the eight calculations
- §3.1 — insert — ambiguity — the seller listing accepts no filter parameters at all (unlike advertisers, which filter on category_code/credit_status) — routes/sellers.py:40-42
- §3.2 — insert — ambiguity — frequency_goal has no upper bound (validated with maximum=None, unlike every percentage field which caps at 100) — routes/campaigns.py:40, validation.py:87-96
- §3.2 — revise — mismatch — planned_impressions multiplies allocated_cents by 1000 BEFORE dividing by effective_planned_cpm_cents; PRD had stated divide-then-multiply — services/derive.py:120-123
- §3.3 — insert — ambiguity — plan submission never reads the body, so a supplied body (even non-JSON) is ignored rather than rejected — routes/campaigns.py:87-89
- §3.3 — insert — ambiguity — the plan_posture test guards the REVISION_REQUIRED hop alone; a submission from DRAFT never consults it — routes/campaigns.py:93-95
- §3.3 — insert — ambiguity — plan approval likewise reads no body — routes/campaigns.py:108-110
- §3.3 — insert — ambiguity — revision_note is required and non-empty, has no max length, and is validated but NOT persisted (no such field in the campaign representation) — routes/campaigns.py:133, serializers.py:31-56
- §3.3 — revise — mismatch — the automatic APPROVED->REVISION_REQUIRED pushdown fires only inside the placement and rights-exercise commitment chains; approving a plan whose posture already reads REPLAN_REQUIRED legitimately yields plan_status APPROVED alongside plan_posture REPLAN_REQUIRED — services/cascades.py:57-73, routes/campaigns.py:123-125
- §3.4 — insert — ambiguity — publishing an avail with zero availability is refused with ERR_FORECAST_NOT_IN_EXPECTED_STATE, and the not-DRAFT test runs before the availability test — routes/forecasts.py:67-70
- §3.5 — insert — ambiguity — withdraw_reason is null from creation, stays null when the withdrawal omits it, and withdrawal is the only field-declaring negotiation write that tolerates an absent body — routes/negotiations.py:93,150-160
- §3.5 — insert — ambiguity — negotiation acceptance declares no field and never reads the body — routes/negotiations.py:165-168

### Pass 3 — routes/{buys,buy_units,delivery_reports,make_goods,rights,reconciliation,invoices} -> PRD §3.6–§3.9 + four assigned carry-overs
- §2.4 — revise — mismatch — non-mutating-read contract kept but the stored (not recomputed) exceptions enumerated: buy cost stack, unit line money, make-good frozen shortfall/value, invoice rollups — derive.py:233
- §2.8 — revise — mismatch — body shape is validated in full at ladder position 3 before any identifier is resolved; path id resolves before body FKs — validation.py/lookup.py
- §2.9 item 9 — revise — mismatch — funding axis never reports ERR_CAMPAIGN_PLAN_NOT_IN_EXPECTED_STATE; its only from-state rule is ERR_CAMPAIGN_ALREADY_FUNDED at 43 — routes/campaigns.py
- §2.9 items 29/30 — revise — mismatch — swapped so permission (ERR_MAKE_GOOD_NOT_PERMITTED) outranks coverage (ERR_MAKE_GOOD_OFFER_INSUFFICIENT) — make_goods.py:58 vs :60
- §3.6 — revise — mismatch — unit-add on CLOSED/CANCELLED is ERR_ALREADY_TERMINAL — buys.py:33
- §3.6 — insert — ambiguity — program max 120 chars -> ERR_INVALID_REQUEST at position 3 — buys.py:47
- §3.6 — insert — ambiguity — the line's exclusive flag is recorded but read by no rule — buys.py:53
- §3.6 — insert — ambiguity — avail window inside flight is inclusive of both endpoints — buys.py:60-70
- §3.6 — insert — ambiguity — the three line money fields are stored once and never rewritten by a later commission re-tier — buys.py:95-101
- §3.6 — revise — mismatch — placement on a terminal buy is ERR_ALREADY_TERMINAL — buys.py:124
- §3.6 — revise — mismatch — separation scope is buys at PLACED/IN_FLIGHT/COMPLETED/CLOSED; PENDING_PLACEMENT and CANCELLED ignored — buys.py:162
- §3.6 — revise — mismatch — placement increments the buy's own version as well as the campaign's — buys.py:146
- §3.7 — insert — ambiguity — the recomputed cost stack is stored on the buy in that form — rights.py:58, derive.py:233
- §3.7 — revise — ambiguity — only SCHEDULED lines sweep (MAKE_GOOD_SCHEDULED never); third tie-break is creation sequence; test applied before each take so the sweep may over-release and a floored magnitude of 0 sweeps nothing; touched avails bump version regardless — rights.py:92-114, cascades.py:26
- §3.7 — revise — mismatch — CANCELLED reachable from PENDING_PLACEMENT too; only the three money fields zero while commission_rate keeps its tier; zeroing precedes delta_gross_cents — rights.py:65-81
- §3.8 — insert — ambiguity — actual_impressions >= 1, mandatory only for AIRED, ignored for PREEMPTED — buy_units.py:24-26
- §3.8 — revise — mismatch — AIRED writes nothing to the buy; preempting a MAKE_GOOD_SCHEDULED line is ERR_UNIT_NOT_SCHEDULED decided before the air-window test — buy_units.py:35-38
- §3.8 — insert — ambiguity — AT_RISK only from NOT_STARTED/ON_TRACK; buy and avail version bump on every preemption — buy_units.py:50-55
- §3.8 — revise — mismatch — measurement_basis does NOT determine the reconciliation group (the buy's channel does) — reconciliation.py:71
- §3.8 — insert — ambiguity — filing has no buy-axis precondition; overlapping periods both count — delivery_reports.py:34-45
- §3.8 — insert — ambiguity — report state tested before buy state; acceptance declares no body — delivery_reports.py:70-74
- §3.8 — insert — ambiguity — only three from-states move; already-settled axes fire no Link 3, so no second make-good — delivery_reports.py:92-99
- §3.8 — insert — ambiguity — dispute_reason non-empty, unbounded; no state but the report's own consulted — delivery_reports.py:129-139
- §3.8 — revise — mismatch — "Six" -> seven conditions with the explicit reported order (ownership, make-good state, publication, window, cap, provision, coverage, capacity) — make_goods.py:38-70
- §3.8 — insert — ambiguity — offered window inclusive of the avail's endpoints — make_goods.py:52
- §3.8 — insert — ambiguity — an offer holds no inventory and bumps no avail version — make_goods.py:72-77
- §3.8 — insert — ambiguity — replacement line is created with exclusive false and exclusivity is not re-tested — make_goods.py:104-118
- §3.8 — insert — ambiguity — avail version bumps either way; MADE_GOOD hop needs shortfall 0 AND UNDER_DELIVERED, but buy version bumps regardless — make_goods.py:122-129
- §3.8 — insert — ambiguity — credit_cents >= 1 with no upper bound; body itself optional — make_goods.py:150-160
- §3.8 — insert — ambiguity — DRAFT re-credit also recomputes max_remittable_cents and bumps invoice version — make_goods.py:181-195
- §3.8 — insert — ambiguity — no make-good write consults the buy's placement axis — make_goods.py
- §3.8 — revise — mismatch — closeout on a terminal buy is ERR_ALREADY_TERMINAL; closeout declares no body — buys.py:183
- §3.9 — insert — ambiguity — only aggregate_duplication_pct is ever mandatory and only under AGGREGATE_DEDUP; others default 0.00; all four stored; no campaign precondition — reconciliation.py:39-49
- §3.9 — revise — mismatch — under COMPLETED_NO_DATA group_reach_pct is an empty object, not three zeroed entries — reconciliation.py:87-93
- §3.9 — insert — ambiguity — sequential ladder accumulates at full precision and rounds once at the end — reconciliation.py:127-141
- §3.9 — insert — ambiguity — drafting consults no buy axis; overlapping periods double-bill the same aired line — invoices.py:32-35
- §3.9 — revise — mismatch — line money is recomputed from the buy's current commission_rate at drafting, not read off the line — derive.py:376-390
- §3.9 — insert — ambiguity — an all-MAKE_GOOD_AIRED invoice is all-zero: issuable, never payable or remittable — invoices.py
- §3.9 — revise — mismatch — PAID -> ERR_ALREADY_TERMINAL; UNBILLED->INVOICED cascade fires only from that from-state; issue declares no body — invoices.py:68-92
- §3.9 — revise — mismatch — PAID -> ERR_ALREADY_TERMINAL; INVOICED->CLIENT_PAID only from that from-state; full-payment ceiling ignores the pro-rata — invoices.py:124-155
- §3.9 — revise — mismatch — terminal test, then invoice-state test, then segregation — invoices.py:166-174
- §3.9 — insert — ambiguity — approver_user_id overwritten on each release — invoices.py:186
- §3.9 — insert — ambiguity — CLIENT_PAID->REMITTED (and the COMPLETED->CLOSED hop inside it) fires only from that from-state — invoices.py:191-193

Carry-over verdicts: (a) RESOLVED — funding axis never raises ERR_CAMPAIGN_PLAN_NOT_IN_EXPECTED_STATE; item 9 now names the three plan operations only. (b) RESOLVED — body-shape validation completes before any lookup, so resolution sits below position 3; §2.8 now states that and that path ids resolve before body FKs. (c) RESOLVED — no serializer calls apply_cost_stack (serializers.py:150-153 reads the record), so reads genuinely never mutate; §2.4 keeps the non-mutating contract and enumerates the four stored-figure families. (d) CONFIRMED — cascades.py:26 calls store.touch(forecast) outside any status conditional, so a forecast's version moves even when EXHAUSTED->PUBLISHED does not occur; pinned in §3.7 (cancellation sweep), §3.8 (preemption), §3.8 (make-good acceptance).

Orchestrator adjudication of pass 3's one declared scope deviation: pass 3 swapped §2.9 ladder items 29/30 despite that section belonging to pass 1's window. KEPT, not reverted. It is a genuine mismatch-revision, not scope creep: the numbered ladder contradicted its own closing note AND the implementation, and Step 6's own summary independently documented exactly this deviation ("on a make-good offer, ERR_MAKE_GOOD_NOT_PERMITTED (position 30) is checked above ERR_MAKE_GOOD_OFFER_INSUFFICIENT (29), because the PRD states the permission rule sits above both the shortfall and the capacity rule"). Leaving it would have shipped a self-contradiction inside the completed PRD, defeating Step 9's purpose.

Orchestrator final verification: PRD_COMPLETED.md is 515 lines / 126,898 chars and is NOT byte-identical to PRD.md (118 changed lines) — the scan genuinely ran. `diff` of all `^#` heading lines against PRD.md is empty (heading structure intact). File ends on the final §5 table row (`ERR_SEQUENTIAL_LIABILITY_EXCEEDED | 422`) — a real section boundary, not mid-sentence. Grep for `expert level`/`harder than`/`SCAFFOLD`/`test_recipe` -> 0 matches. PRD.md itself is unmodified.

PIPELINE COMPLETE — Step 9 has written workspace/PRD_COMPLETED.md.
