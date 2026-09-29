# Worklog — task_2989_recipe_costing_menu_engineering_plate_cost_management

## Step 1: Create task directory — 2026-09-06T02:26:40.948Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2989_recipe_costing_menu_engineering_plate_cost_management/` and its `workspace/` subdirectory. Index 2989 was pre-assigned by the orchestrating command (no scan/allocation performed, per concurrency constraint).

## Step 2: Generate scaffold — 2026-09-06T04:47:00.000Z

All three artifacts are complete and lint-clean.

Lint verdict (verbatim, final run):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  1197

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Domain surface (`SCAFFOLD.yaml`, §1.0–§1.7 only — no design keys present): 14 entities, 63 endpoints, 8 state machines, 9 calculations, 49 validations, 48 error codes, 5 roles, 4 concurrency rules, 27 constants. `complexity_profile`: entity_topology graph, state_machine_shape cyclic, role_model peer_roles + segregation of duties, consistency_model immediate, complexity_layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation. Scenario string is the caller's verbatim text; the difficulty directive does not appear anywhere in the file (verified by scan).

§1.8 (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`) — 9 rule_ids × 2 instances = 18:
dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

§1.9 (`SCAFFOLD_CORNER_DESIGN.yaml`) — 9 sections, 71 instances (56 with full `test_recipe`, 15 `excluded_because` stubs):
entities 13, state_machines 17, calculations 15, validations 8, endpoints 6, errors 3, rbac 3, cross_cutting_complexity_layers 5, consistency_model 1.

Final files (all end on a real YAML boundary; all three parse with `yaml.safe_load`):
- `.../SCAFFOLD.yaml` — 3088 lines
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1843 lines
- `.../SCAFFOLD_CORNER_DESIGN.yaml` — 4163 lines

Cross-checks passed: all 48 error ids are triggered somewhere across the two design files (0 uncovered); all 89 instance `name`s unique across both files; every stub's `difficulty_instance` resolves to a real §1.8 instance name (6 older citations normalised to bare names) and no stub carries a `test_recipe`. Only the agent's own `.scratch/step2/` was removed; parent `.scratch/`, `workspace/` and `worklog.md` untouched; no sibling task directory read or created.

Orchestrator verification: leak scan for the difficulty directive across the whole task dir returned zero hits; `workspace/` survived Step 2 intact.

## Step 3: Copy shared files — 2026-09-06T04:48:05.390Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T05:10:00.000Z

PRD complete and verified.

## Deliverable
`workspace/PRD.md` — **526 lines**, 121192 bytes.

- **Last heading:** `## 5. Error Code Catalogue` (line 475)
- **Last line:** `` | `ERR_NO_PUBLISHED_PRICE`          | 422 Unprocessable Entity | ``
- Ends at a real section boundary (final row of the §5 table); no audit footer, no contract report inside the file.

## Section map (line ranges)
| Section | Lines |
|---|---|
| Title | 1 |
| §1 Introduction | 3–10 |
| §2 Global Specifications & System-Wide Principles | 11–200 |
| §2.1 User and Role-Based Access Control | 13–22 |
| §2.2 API Response Structure (verbatim) | 23–71 |
| §2.3 Pagination | 72–79 |
| §2.4 Common Resource Properties, the Audit Stamp and the Logical Clock | 80–92 |
| §2.5 Integer Arithmetic, Units of Measure and Rounding | 93–109 |
| §2.6 Cost Freshness: the STALE and FRESH Contract | 110–117 |
| §2.7 Expected-Version Guards on Specification and Promotion Writes | 118–128 |
| §2.8 Regional Cost and Price Parameters | 129–136 |
| §2.9 Allergen Bitmasks and Nutrition Roll-Up Units | 137–142 |
| §2.10 Path Resolution and Validation Ordering | 143–200 |
| §3 Business Logic & Workflows | 201–404 |
| §3.1 The Purchasing Catalogue: Stores and Ingredients | 203–214 |
| §3.2 Distributor Price Feeds and the Five-Hop Publication Cascade | 215–236 |
| §3.3 Composing the Recipe Graph and Rolling Up Its Cost | 237–274 |
| §3.4 Review, Activation, Prep Guides and Retirement of a Recipe | 275–284 |
| §3.5 Menu Items: From Portion Cost to Plate Cost | 285–304 |
| §3.6 Specification Change Orders: Approval, the Four-Hop Cascade, Rollback and Propagation | 305–340 |
| §3.7 Price Change Proposals and the Elasticity Projection | 341–360 |
| §3.8 Period Reviews: Menu Mix Engineering, Physical Counts and Variance | 361–382 |
| §3.9 Limited-Time Offers: Costing, Launch Capacity and the Post-Promotion Verdict | 383–404 |
| §4 Endpoint Definitions | 405–474 |
| §5 Error Code Catalogue | 475–526 |

§2 has 10 domain-derived subsections (spec allows 8–12); §3 has 9 (spec allows 5–9).

## Coverage: documented vs. declared in scaffold
| Item | Declared | Documented |
|---|---|---|
| Entities | 14 | 14 |
| Endpoints (§4 table rows) | 63 | 63 |
| State machines | 8 | 8 |
| State transitions | 32 | 32 |
| Calculations | 9 | 9 |
| Validation rows (§2.10 ordered list) | 49 | 49 |
| Errors (§5 table rows) | 48 | 48 |
| Roles | 5 | 5 |
| Constants | 23 | 23 (by value in business context) |

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS** (mechanical, 2 runs of a scaffold-vs-PRD differ)
- `entities[].fields[].name`: 136 required / 136 present / 0 missing
- `endpoints[].input` (request-body identifiers): 62 / 62 / 0 missing — includes all four OCC fields (`expected_recipe_version`, `expected_menu_item_version`) and `to_iso8601`
- `query_params`: 2 / 2 / 0 missing (`limit`, `offset`)
- `path_params`: 11 / 11 / 0 missing
- `errors[].id`: 48 / 48 / 0 missing; `roles[].name`: 5 / 5 / 0 missing
- Constants: 4 of 23 names appear as literal symbols; the other 19 are embedded as **values** in business prose per SKILL.md line 194. Each of the 19 was individually confirmed present as a value: 300 bps cap relief, 14 whole days cooling-off, 1000 default baseline, 150 bps garnish / 8000-micro floor, 640000 µg kids sodium, 8000 bps attainment / 0-cent contribution, 300 bps LTO support, 300-cent margin floor, two concurrent promotions per region, four-level depth, two revision rounds, 1200 bps single increase, 200 bps plate waste, 7000 bps popularity factor, 300 bps variance tolerance, ninety-day weighted-average window, and the eight allergen bit values 1–128.
- Note: the first check run reported false negatives because the naive backtick regex mis-paired against §2.2's fenced JSON blocks; the checker was fixed to strip fences before extracting tokens.

**Contract 2 — Rule Coverage: PASS**
- Validation priority ordering: §2.10 reproduces all 49 rows in priority order with condition → error_id → HTTP status, plus explicit call-outs of the three consequential inversions (empty-specification recipe gate at 18 above the freshness gate at 26; recipe-status gate above segregation of duties at 27; market cap at 47 above margin floor at 48).
- `concurrency_rules[]`: all 4 stated in §2.7 with write endpoint, OCC field name, error_id and 412 status, plus the explicit negative — proposal creation takes no OCC field and no other endpoint accepts one.
- Cross-entity cascades: price-feed publication's five hops (§3.2) and the change-order four hops plus rollback compensation (§3.6) are fully enumerated, including the direct-vs-transitive asymmetry (transitively staled ancestors keep their own roll-up figures; their menu items keep allergen/sodium copies) and the LTO de-costing reverse edge.
- `validations[].applies_to`: §2.10 names the full endpoint set for each shared gate (not-found chain, state gates, freshness gate, OCC, unit scope).
- Field-level structured content/defaults: enum members, ranges, uniqueness, null-vs-required-per-`change_type` triads, and every creation-time initial value are stated per entity.
- Sibling-branch symmetry: equal prose density given to `DRAFT → UNDER_REVIEW` vs `ACTIVE → UNDER_REVIEW`; `DRAFT → ACTIVE` vs `SUSPENDED → ACTIVE`; `DRAFT → SUBMITTED` vs `REVISION_REQUESTED → SUBMITTED`; the two request-revision outcomes; the two propagate targets from each of two origins; and the `RENEW` vs `RETIRE` arms.
- Tail: 32/32 transitions, 9/9 calculation formulas (each with pinned evaluation order and rounding sites), 49/49 validation check→error_id pairs, and every endpoint side effect including version bumps and counter increments/decrements.

**Contract 3 — §3 Path Purity: PASS** (mechanical scan of §3, lines 201–404)
- 1155 backticked tokens in §3; 0 start with `/`, 0 are bare HTTP methods, 0 are method+path combinations. Endpoints in §3 are named by state-transition framing, role + action verb, or capability description. Paths appear only in §2.7 (required by the OCC contract) and in the §4 table.

## Constraints honoured
`SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task directory was read. No scaffold worked-example numbers or fixture codes were reproduced — only the rules they illustrate. `worklog.md` was not touched. Scratch was confined to `.scratch/step4/` and only that subdir was removed.

Orchestrator anti-truncation verification (independent of the subagent's own report): 526 lines; headings §1–§5 all present and in order; final line is a complete markdown table row, not mid-sentence. Mechanical cross-check against SCAFFOLD.yaml: all 48 declared error ids appear in §5 (0 missing, 0 extra) and all 63 declared endpoint paths appear in §4 (0 missing). Not truncated — no regeneration needed. Difficulty-directive leak scan of PRD.md: 0 hits.

## Step 5: Generate unit tests — 2026-09-06T07:26:00.000Z

Step 5 is complete. `test_18_consistency.py` finished the queue-B pass.

## Files written (all at the task root, nothing under `workspace/`)

**`test_helpers/`** — 3,023 lines total
`__init__.py` 164, `api_client.py` 449, `api_errors.py` 119, `assertions.py` 459, `constants.py` 110, `factories.py` 388, `fixtures.py` 786, `test_users.py` 126, `types.py` 420

**`test_suite/`** — 13,177 lines total, `conftest.py` 17
Queue A: `test_01_dual_variant_calculations.py` 350/9 tests, `test_02_combinatorial_formulas.py` 415/9, `test_03_non_linear_state_machines.py` 553/16, `test_04_transitive_cascades.py` 516/12, `test_05_validation_priority_pairs.py` 303/8, `test_06_boundary_precision.py` 411/12, `test_07_cross_entity_state_dependencies.py` 296/10, `test_08_resource_temporal_overlap.py` 372/11, `test_09_compensating_invariants.py` 489/13
Queue B: `test_10_entities.py` 832/22, `test_11_state_machines.py` 1650/53, `test_12_calculations.py` 1586/41, `test_13_validations.py` 1548/46, `test_14_endpoints.py` 1419/38, `test_15_errors.py` 593/24, `test_16_rbac.py` 659/23, `test_17_cross_cutting.py` 792/23, `test_18_consistency.py` 378/11

## Tests emitted: 381

Queue A (Difficulty, 9 rule_ids): **18/18 instances translated, 0 skipped** → 100 tests.
Queue B (Corner, 9 sections): **56/56 non-stub instances translated, 0 skipped** → 281 tests. The remaining 15 `- name:` entries in `SCAFFOLD_CORNER_DESIGN.yaml` are self-excluded stubs — each carries only `claim_type`/`grounds`/`excluded_because` with **no `test_recipe`** — so they are correctly not translated: `recipe_and_menu_item_are_never_immutable_entities`, `proposal_revision_loop_termination`, `spec_change_order_two_independent_state_dimensions`, `price_feed_publication_cascades_down_five_levels`, `spec_change_rollback_reverses_every_side_effect`, `menu_item_activation_is_guarded_by_the_recipe_status`, `recipe_cost_rollup_dual_variant_divergence_on_one_recipe`, `theoretical_food_cost_variant_divergence_on_one_review`, `recipe_cost_rollup_rounds_each_component_before_summing`, `price_change_projection_cap_relief_ordering`, `recipe_cost_rollup_ignores_removed_components`, `menu_mix_classification_at_the_popularity_threshold`, `action_endpoint_state_transition_with_cross_entity_preconditions`, `n_level_cascade_ordering_and_partial_reach`, `both_cost_variants_and_the_switch_delta`.

**No instance was skipped on PRD-first grounds.** Individual assertions inside otherwise-translated instances were dropped or corrected where the PRD does not uniquely derive them:
- `pre_change_batch_cost_micros == 0` asserted instead of the design's `null`.
- Mix-line `margin_class == UNCLASSIFIED` and `mix_pct_bps`/`cm_per_unit_cents` at load omitted (PRD says they are written later, without naming a value at load).
- `mix_line_count` omitted — not a PRD field.
- Count-line `synced_spec_version` omitted — not uniquely derivable in a two-recipe graph.
- Design's `projected_contribution_delta_cents == 270` corrected to 97; design's mix-line `plate0 == 103` corrected to 100; design's self-flagged `p_sodium_after == 620500` asserted as 620000.
- `ERR_REVIEW_INVALID_STATE` for a count line into a `CLASSIFIED` review omitted — the PRD never enumerates which review statuses admit count-line loading.
- One review `version + 2` assertion softened to `>` (PRD does not fix the increment count).

## Verification

- `.scratch/step5/verify.py` (AST walk over all 18 files): **`tests: 381`, `issues: 0`** — every test has exactly one `Design:` line, it is the docstring's last line, its instance name exists in one of the two yamls, every `PRD n.n: "…"` quote survives a whitespace-normalised substring match against `PRD.md`, and no docstring mentions the scaffold or its section numbers.
- `python3 -m py_compile` on all 9 helper + 19 suite files: clean. `import test_helpers` / `test_helpers.fixtures` / `test_helpers.factories`: clean. `pyflakes` on `test_suite/*.py` and `test_helpers/fixtures.py`: exit 0 (two dead imports removed from `fixtures.py` this pass).
- Both directories confirmed at the task root; `find` over `workspace/` (excluding `implementation/`, which was never read) shows no `test_helpers/`, `test_suite/` or `conftest.py`. `__pycache__` dirs removed; only `.scratch/step5` deleted, the `.scratch` parent left in place; `worklog.md` untouched.

`test_18_consistency.py` translates the single `consistency_model` instance into 11 tests: the count-line POST body carrying `used_base_units` 10200 / `expected_base_units` 10000 / `variance_base_units` 200 / `sync_state CURRENT` / `valued_usage_micros` 0, the explosion arithmetic (`floor_div(100 * round_half_up(400 * 1_000_000, 4), 1_000_000)`), the classify response's own `popularity_threshold_bps` 7000 and `margin_threshold_cents` 300, the immediately following item read showing `STAR`/100/`FRESH`, the second feed's line waiting in `PENDING`, the publish response's whole first hop (`published_at` == the logical clock, `superseded_price_count` 1, `affected_recipe_count` 1, `affected_menu_item_count` 1), the very next recipe read `STALE` with `batch_cost_micros` still 3880071, the very next item read `UNCLASSIFIED`/`STALE`/100, and the two negatives — the count sheet still `CURRENT` at 10000 and the mix line still `STAR` with snapshot 100.

Orchestrator verification: `test_helpers/` and `test_suite/` are both at the task root (nothing test-shaped under `workspace/`); 381 test functions counted independently; `python3 -m py_compile` clean over all 28 files.

## Step 6: Generate implementation — 2026-09-06T07:03:00.000Z

(Launched concurrently with Step 5 in a single assistant message, so the impl generator was physically unable to read `test_suite/` — that directory did not exist when it started.)

All work is complete and verified.

## Deliverable
`workspace/implementation/`

| Module | Lines | Role |
|---|---|---|
| `start.sh` | 10 | reads `$PORT` (default 8080), binds `0.0.0.0`, runs `python3 app.py` in the foreground via `exec` |
| `requirements.txt` | 1 | `flask` |
| `app.py` | 48 | app factory, blueprint registration, `ApiError`/`HTTPException`/catch-all handlers |
| `core.py` | 180 | constants, enums, integer helpers (`rhu`, `ceil_div`, `floor_div`), the in-memory `Store` (14 dicts) and the logical clock |
| `errors.py` | 64 | the 48-code → HTTP status table, `ApiError`, `fail` |
| `envelope.py` | 43 | `ok` / `created` / `listing` / `error` envelope builders |
| `guards.py` | 295 | auth, body/query coercion + range checks, pagination, the ten `find_*` 404 helpers |
| `serial.py` | 168 | per-entity field lists and the 14 serialisers |
| `graph.py` | 384 | component graph (`reaches`, ancestors, depth), price selection, yields, allergen/nutrition profile, cost rollup |
| `calc.py` | 242 | plate cost, price projection, classification, review close, count-line refresh, LTO costing/post-promo |
| `cascade.py` | 112 | STALE/FRESH upward-transitive invalidation, menu-item and campaign knock-on, prep-guide/count-sheet `OUT_OF_DATE` |
| `routes/__init__.py` | 20 | blueprint registry |
| `routes/catalogue.py` | 145 | units, ingredients, clock |
| `routes/feeds.py` | 179 | price feeds, lines, publish, price history |
| `routes/recipes.py` | 354 | recipes, components, rollup, review/activate/retire, prep guides |
| `routes/menu_items.py` | 162 | menu items, plate cost, activation, mix history |
| `routes/proposals.py` | 209 | price-change proposals (draft → submit → revise/approve → apply) |
| `routes/spec_orders.py` | 360 | spec change orders, four-hop approval cascade, propagation grid, rollback |
| `routes/reviews.py` | 234 | period reviews, mix lines, count lines, classify, close |
| `routes/ltos.py` | 204 | LTO campaigns, cost, launch capacity, close-review, renew/retire |

3414 lines total; every module passes `python3 -m py_compile`, and `__pycache__` was removed afterwards.

## Endpoints
**63 implemented / 63 declared.** Dumped `app.url_map` and compared path-for-path against the PRD §4 table — exact match, no extras. The PRD declares no collection GET for units/ingredients/recipes/price-feeds, and those paths correctly return a 404 `ERR_INVALID_REQUEST` envelope rather than a list.

## Behaviour implemented
- **8 state machines**: Recipe (`DRAFT→UNDER_REVIEW→ACTIVE→RETIRED`), RecipeComponent (`ACTIVE/REMOVED`), MenuItem, PriceFeed (`DRAFT→PUBLISHED`), PriceChangeProposal (incl. the bounded revision loop), MenuPeriodReview (`OPEN→MIX_LOADED→CLASSIFIED→CLOSED`), LtoCampaign (`PLANNED→COSTED→LAUNCHED→CLOSED→RENEWED/RETIRED`), SpecChangeOrder — plus its independent `propagation_status` dimension as a second axis.
- **9 calculations**, all integer-only with the contractual round-then-sum: net yield (trim × shrink, `floor_div`), AP from EP (`ceil_div`), 90-day weighted-average unit cost, batch/portion cost rollup, plate cost with the regional differential, elasticity price projection, menu classification thresholds, theoretical-vs-actual food-cost variance, and LTO forecast/post-promotion figures.
- **49 ordered validations / 48 error codes**, sequenced by PRD §2.10's global ascending order (which overrides the §3 narrative order), with path identifiers resolved strictly left-to-right ahead of body identifiers.
- **OCC** on exactly the 4 declared endpoints; **STALE/FRESH** upward-transitive invalidation that stops at already-STALE nodes and never clears figures; the SCO four-hop cascade and a rollback that restores the spec plus both snapshots and leaves the recipe STALE.

## Boot and smoke verification
Booted with `PORT=$((20000 + RANDOM % 20000))` → 27832, server PID identified via `ss -ltnp` and killed by PID only (no pattern kills).

- Envelope matches §2.2 exactly: `{"meta": {api_request_id, api_request_timestamp}, "response_type", "data"}`; list meta adds `limit/offset/total_count/has_more`; errors carry `{error_id, message}` with `response_type: "error"`.
- 98/98 smoke assertions passed, including the scaffold's published worked example: an NE menu item off a 2695590-micro portion cost yields `plate_cost_micros = 2958189`, `plate_cost_cents = 296`, `food_cost_bps = 2963`. Also verified end-to-end: rollup, activation + prep-guide minting, clock monotonicity (422 on backwards), review classify/close with `OVER_TOLERANCE` variance, proposal submit→approve→apply (with the 409 before the effective date), SCO approve → cascade → double-propagate 409 → rollback restoring `component_count` and `batch_cost_micros`, and the LTO launch/close/renew chain minting an abutting successor.
- **No seeded data**: after `kill` + relaunch, every collection GET reported `total_count: 0`. Fresh process, empty domain.
- `.scratch/step6` removed; sibling `.scratch/step5` untouched; `worklog.md` never modified; port 27832 confirmed free.

Orchestrator note: a pre-written, quoting-safe sweep runner (`workspace/sweep.sh`, ends by touching `workspace/SWEEP_DONE`) and a schema-correct results summariser (`workspace/summarize_sweep.py`, keyed on `tests[].status`/`error_message` with a total-minus-passed cross-check) were prepared for Step 7 so the fix agent cannot hit the inline-heredoc quoting bug or the early-return relaunch trap.

## Step 7: Run tests and iterate — 2026-09-06T08:02:00.000Z

All 381 tests pass in all 8 rounds. Notably, **zero implementation changes were required** — every one of the 25 failures was a defect in the test artifact.

## Summary

**Iterations run:** 2 sweeps (iteration 1 = diagnosis at 356/381; iteration 2 = verification at 381/381). All 25 failures were deterministic in all 8 rounds — no flakiness, no load-induced noise.

**Tests deleted:** none. Two over-reaching *assertions* were split off per STEP 1c, but no test was removed.

**Fixes to `test_helpers/`**

- `test_helpers/api_client.py` — `ApiClient._request`: added a DELETE branch that sends a dict payload as a real JSON body. **This single fix resolved 14 of the 25 failures.** The runner's `GenericApiClient._request` folds DELETE payloads into the *query string*, but PRD §2.7 makes `expected_recipe_version` "a non-optional **body** field" on `DELETE /culinary/recipe-components/{id}`. The PRD-faithful server was correctly reporting the field as missing (`ERR_INVALID_REQUEST`), which also masked three ordering tests that expected `ERR_COMPONENT_NOT_FOUND`, `ERR_RECIPE_NOT_MUTABLE` and `ERR_STALE_RECIPE_VERSION`. Also renamed the `delete_recipe_component` parameter `params` → `payload` to stop the misnomer inviting the bug back.

**Fixes to `test_suite/`**

- `test_12_calculations.py`, `_campaign_a_launched` / `_campaign_b_launched` (9 failures) — the fixtures called `set_clock` to `2026-06-15` and `2026-07-31`, both *before* the logical clock's `2026-08-01T00:00:00Z` epoch, so the strictly-monotonic clock (PRD §2.4) correctly returned `ERR_CLOCK_NOT_MONOTONIC` in setup. Shifted both campaign windows forward one month (A: Aug→Sep, B: Sep→Oct) preserving the original abutting-window design, so capacity semantics per PRD §3.9 are unchanged; updated the dependent `reviewed_at` assertion to `2026-09-01`.
- `test_12_calculations.py`, `_sauce_weighted_under_an_uncosted_plate` — removed the same backwards clock set. Verified the assertion is clock-independent: the single published window (effective from `2026-07-01`, open-ended) is the sole candidate under both `LATEST_PUBLISHED` and the 90-day lookback at the epoch, so `batch_cost_micros=1_268_499` is unaffected.
- `test_12_calculations.py`, `test_the_uplift_region_rounds_between_the_uplift_and_the_waste` — the hand-typed counterfactual constant `collapsed` was arithmetically wrong (`1_063_333`; the correct value is `1_047_619`). This literal is computed test-side and never sent to the server; all six server-facing assertions were already correct. Corrected the constant and the docstring. The test's actual point — that the uplift and waste factors must not be collapsed into one multiplier — still holds.
- `test_11_state_machines.py`, `test_the_retire_arm_mints_no_successor_campaign` — dropped a `decision=RETIRE` assertion on the campaign *response*. PRD §3.9 enumerates the campaign's persisted attributes exhaustively and never lists `decision`; it appears only as a request-body input on `/decide`, and §3.9 states the two arms "share no side effect beyond the version bump", so a faithful implementer would record the fork in `status` alone. STEP 1c split — the PRD-verbatim `status=RETIRED` assertion is retained.
- `test_14_endpoints.py`, `test_the_parents_persisted_profile_is_left_behind` — the test expected the parent recipe to stay `FRESH` at an unchanged `version` after its child gained a component. PRD §2.6 mandates the opposite: "A recipe holding an active sub-recipe component whose child recipe just went stale is itself stale", and §2.4 makes every cascade hop a version increment. Corrected to `cost_state=STALE` / `version + 1`. The test's genuine point (the parent's persisted `allergen_mask`, kcal and sodium are *not* recomputed, so its profile is left behind) is preserved intact.

**Fixes to `implementation/`:** none. Verified by mtime that no implementation file was touched.

**Final per-round results:** rounds 1–8 each `passed=381 / total=381`, 8/8 `results.*.json` on disk in `workspace/implementation/` (deliverables retained, along with `sweep.sh` and `summarize_sweep.py`). `worklog.md` was not modified; `.scratch/step7` removed, the parent `.scratch` tree left in place.

Orchestrator verification (independent of the subagent's report): re-ran `workspace/summarize_sweep.py` against the on-disk artifacts — 8/8 results files present, every round `passed=381 total=381`, union of failures empty, total-minus-passed cross-check agrees. Sweep artifacts are real, not claimed.

Orchestrator decision on Step 8: the skip condition (zero iterations beyond baseline) does NOT apply — Step 7 ran 2 iterations with 1 `test_helpers/` fix and 5 `test_suite/` fixes. Step 8 therefore runs, even though `implementation/` was untouched; the test-artifact fixes still mark places worth checking for PRD silence (notably the campaign `decision` field and the DELETE-body OCC contract). A byte-identical `PRD_FINALIZED.md` would be a legitimate outcome here given 0 implementation fixes.

## Step 8: Finalize PRD — 2026-09-06T08:13:00.000Z

Done. PRD_FINALIZED.md is a one-line patch of PRD.md.

## Counts
- PRD.md: 526 lines / 121192 bytes. PRD_FINALIZED.md: 526 lines / 121390 bytes.
- Line delta: 0 lines (0.00%); +198 bytes (+0.16%).
- `diff` shows exactly one changed line (399, §3.9 prose). All 48 `ERR_` ids present in both; §4 table row count and unique `/culinary…` path count identical (62 rows / 53 unique paths in both); both files end on the same real boundary, `| ERR_NO_PUBLISHED_PRICE | 422 Unprocessable Entity |`.

## Change
- §3.9 (LTO decision paragraph) — revise — added "The `decision` is a request-body input only: the campaign stores no attribute of that name, and which arm was taken is afterwards read from the campaign's own `status` (`RENEWED` versus `RETIRED`)." — `implementation/routes/ltos.py:175,187-204` + `implementation/serial.py:88-96`.

### Pre-edit search log (mandatory per-edit)
(a) Subject: the campaign's persisted attribute set, specifically whether the `/decide` request field `decision` is stored/echoed on the LTOCampaign resource.
(b) Impl paths enumerated: `grep -rn "decision" implementation/*.py implementation/routes/*.py` → only three hits, all in `routes/ltos.py::decide_campaign` (`req_enum` read at :175, the RENEW verdict guard at :180, the arm branch at :187), never a write to the row; `serial.py` `FIELDS["lto_campaign"]` (:88-96) — no `decision` key, and `_ser` emits only the listed keys plus the four common ones, so no endpoint can leak it; `routes/ltos.py::_blank_campaign` (:21-40) — the row's full key set at birth, no `decision`; `calc.py::lto_costing` (:213-221) and `calc.py::lto_post_promo` (:224-242) — the only other writers of campaign fields, neither adds `decision`; `cascade.py::revert_costed_campaigns` (:37-49) — resets three costing fields only. Also confirmed the campaign list endpoint (`routes/ltos.py:74-91`) filters on `status`/`region_code`/`menu_item_id` only, so nothing reads a `decision` attribute anywhere.
(c) Wording adjustment: scoped the claim to the campaign row and to "the campaign's own `status`" rather than saying the fork is recorded "in `status` alone" — the RETIRE arm does have side effects on the backing menu item (`status=SUSPENDED`, `margin_class=UNCLASSIFIED`, `is_lto=false`, version bump at `routes/ltos.py:198-203`) and the RENEW arm mints a successor and bumps `open_lto_count` (:187-196), all of which the surrounding paragraphs already describe. The narrower phrasing avoids contradicting those paths and leaves the existing "two arms share no side effect beyond the version bump" sentence verbatim and in place.

## Per-item verdicts on `<step_7_diff>`
1. **`api_client._request` DELETE JSON body** — no edit. §2.7 already states, in bold, that `expected_recipe_version` is "a non-optional **body** field" on `DELETE /culinary/recipe-components/{id}`, and `guards.get_body()` reads only the parsed JSON body (query args are never consulted for body fields on any endpoint). The three masked ordering results (`ERR_COMPONENT_NOT_FOUND` / `ERR_RECIPE_NOT_MUTABLE` / `ERR_STALE_RECIPE_VERSION`) also match §2.10 exactly: `req_int` at position 3, `find_component` at 8, version at 15, mutability at 17, already-removed at 28 (`routes/recipes.py:229-251`). Pure runner/test-artifact bug.
2. **`_campaign_a_launched` / `_campaign_b_launched` backwards clock** — no edit. §2.4 pins the pre-write clock reading to exactly `2026-08-01T00:00:00Z` and strict monotonicity with `ERR_CLOCK_NOT_MONOTONIC`/422; §2.10 #46 restates it as "at or after". `core.INITIAL_CLOCK` (:47) is that instant. Fixture bug.
3. **`_sauce_weighted_under_an_uncosted_plate` clock removal** — no edit. Same epoch/monotonicity text; the `LATEST_PUBLISHED` selection and the 90-day window in §3.3 are unchanged by the fix and already fully determine the asserted `batch_cost_micros`.
4. **`collapsed` counterfactual constant** — no edit. Test-side arithmetic typo in a literal that is never sent to the server; §2.5's "order of rounding is part of the specification" already pins the uplift-then-waste sequencing the test demonstrates.
5. **`decision=RETIRE` assertion dropped from the campaign response** — **edit made** (the single change above). PRD §3.9 introduces `decision` only as a `/decide` request field and never says whether it is persisted; no PRD sentence declares any entity's attribute list closed, and the test suite has no exhaustive field-set check for campaigns. The impl deliberately does not store it, so this was a genuine silence a fresh implementer could resolve either way.
6. **Parent recipe `STALE` / `version + 1` after the child gains a component** — no edit. §2.6 ("A recipe holding an active sub-recipe component whose child recipe just went stale is itself stale") plus §2.4 ("Every cascade hop … increments the `version` of every row it touches") already mandate what `cascade.propagate_upward` (:18-34, via `routes/recipes.py::_spec_changed` :47-53) does. The surviving half of the test — the ancestor's `allergen_mask`/`kcal`/`sodium` not being recomputed — is likewise already determined: §3.3 scopes the five-derived-field recompute to "the owning recipe", and `apply_profile` is called only on that recipe, never on the ancestors flipped by `propagate_upward`.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (399) and both files are 526 lines ending on the same §5 table row. A near-identical PRD_FINALIZED.md is the expected and legitimate outcome given Step 7 applied zero `implementation/` fixes.

Orchestrator plan for Step 9: run as **four sequential, module-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 performs the `cp` from PRD_FINALIZED.md; passes 2–4 must not). Partition: pass 1 = infrastructure + catalogue + feeds (`app.py`, `core.py`, `errors.py`, `envelope.py`, `guards.py`, `serial.py`, `routes/__init__.py`, `routes/catalogue.py`, `routes/feeds.py`); pass 2 = recipe graph, cascade, menu items (`graph.py`, `cascade.py`, `routes/recipes.py`, `routes/menu_items.py`); pass 3 = calculations, proposals, spec orders, reviews, LTOs (`calc.py`, `routes/proposals.py`, `routes/spec_orders.py`, `routes/reviews.py`, `routes/ltos.py`); pass 4 = narrow reconciliation pass that closes contradictions the earlier passes introduced against each other. Rationale: a single-agent full-impl scan of a 3414-line implementation against a 121KB PRD reliably under-scans or silently no-ops (a byte-identical PRD_COMPLETED.md means the scan never ran), and partitioned passes are known to report cross-pass contradictions rather than fix them — hence the mandatory 4th pass.

## Step 9: Complete PRD — 2026-09-06T09:32:00.000Z

Run as four sequential, module-partitioned passes over one shared `PRD_COMPLETED.md`; pass 1 performed the `cp` from `PRD_FINALIZED.md`, passes 2–4 edited in place. 47 edits total (42 diff hunks vs `PRD_FINALIZED.md`), 526 → 526 lines, 121390 → 141442 bytes (+20052 chars, +16.5%).

### Pass 1 — infrastructure, catalogue, price feeds (`app.py`, `core.py`, `errors.py`, `envelope.py`, `guards.py`, `serial.py`, `routes/{__init__,catalogue,feeds}.py`)
12 edits: 11 ambiguity-pins, 1 mismatch-revision. 121390 → 127282 bytes.
- §2.1 L15 — revise — ambiguity — a whitespace-only header counts as empty for `ERR_UNAUTHENTICATED` — `guards.py:19-22`
- §2.2 L44 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case alphanumerics — `core.py:154-158`
- §2.2 L45 — revise — ambiguity — `api_request_timestamp` comes from the host's real UTC clock, the only timestamp not from the logical clock — `envelope.py:10`
- §2.3 L76 — insert — ambiguity — every list ordering breaks residual ties by row creation order (ascending even under a descending lead key); needed because the logical clock makes `created_at` collide en masse — `core.py:179-180`, `guards.py:223`
- §2.4 L91 — insert ×2 — ambiguity — the clock endpoint answers 200 with an empty `data` object; client-supplied stored instants are normalised to UTC and read back in the canonical 3-digit form — `catalogue.py:32`, `core.py:85-109`
- §2.10 item 3 L149 — insert — ambiguity — seven coercion readings (empty/absent body = empty JSON object; non-object body malformed; explicit `null` == absent; empty-string identifier is 400 not 404; no type coercion; instants accept `Z`/offset/no-zone; `limit`/`offset` must be base-10; out-of-enumeration filter values rejected while undefined query params ignored; only the two named window pairs are ordering-compared) — `guards.py:36-52,69-76,93-102,160-166,174-176,180-210`, `core.py:93-109`
- §2.10 closing L199 — revise — **mismatch** — positions 4–13 do not promote a body identifier over a path identifier: all path ids resolve before any body id — `feeds.py:60-61`, `recipes.py:144-150`, `reviews.py:146-147,97-98`, `spec_orders.py:60-64`
- §2.10 closing L199 — insert — ambiguity — undefined path → `ERR_INVALID_REQUEST` 404, unsupported method → `ERR_INVALID_REQUEST` 405, both ahead of rule 1 — `app.py:26-34`
- §3.1 L213 — insert — ambiguity — an ingredient's cross-review count-line list exists, `created_at` ASC, filterable by `sync_state` — `catalogue.py:133-145`
- §3.2 L217 — revise — ambiguity — `feed_date` is a required ISO 8601 instant with no comparison against the clock or the feed's lines — `feeds.py:30`
- §3.2 L227 — revise — ambiguity — hop-1 truncation processes lines in load order and only truncates rows from *other* feeds — `feeds.py:98,118,140`
- §3.2 L233 — insert — ambiguity — the fifth hop also fires the §3.9 `COSTED`→`PLANNED` reverse edge; an already-`STALE` item is untouched — `cascade.py:59-69`, `feeds.py:176`
Clean cross-checks (no edit): §5 table ↔ `errors.HTTP_STATUS` all 48 ids/statuses match; §4 table ↔ Flask url_map 63/63 method+path and all 63 role columns match the `authenticate(...)` tuples; all 14 serialisers' fields appear in the PRD; all 22 `core.py` constants have their values in PRD prose; the price-window overlap gate already matches §3.2's three readings.

### Pass 2 — recipe graph, cascade, recipes, menu items (`graph.py`, `cascade.py`, `routes/{recipes,menu_items}.py`)
12 edits: 11 ambiguity-pins, 1 mismatch-revision. 127282 → 132702 bytes.
- §3.3 L259 — insert — ambiguity — `LATEST_PUBLISHED` residual tie-break after `effective_from` DESC / `created_at` ASC (earlier-created row wins) — `graph.py:103-105`
- §3.3 L243 — insert — ambiguity — `sequence_no` carries no uniqueness constraint — `recipes.py:133,29`, `graph.py:15`
- §3.3 L247 — insert — ambiguity — the three add-constraints are exhaustive: a `SUB_RECIPE` line's child is constrained by neither `recipe_type` nor `status`; the ACTIVE-child rule bites only at activation — `recipes.py:144-169` vs `296-304`
- §3.3 L249 — insert — ambiguity — direct component edit: upward transitive staling with ancestors' five derived fields untouched; only `FRESH` items touched; flipped items revert `COSTED` campaigns; no re-copy of `allergen_mask`/`sodium_mcg_per_portion`, no prep-guide/count-line `sync_state` change — `recipes.py:47-53`, `cascade.py:52-81`
- §3.3 L253 — insert — ambiguity — component-list identifier filters are literal, never resolved; unknown ids yield an empty page — `recipes.py:212-221`
- §3.3 L255 — insert — ambiguity — roll-up has no recipe-status gate; a `RETIRED` recipe may be rolled up back to `FRESH` — `recipes.py:257-264`
- §3.3 L267 — insert — ambiguity — a child's allergen contribution is recomputed from the child's live component set, not its persisted `allergen_mask` — `graph.py:171-175`
- §3.4 L283 — revise — **mismatch** — retirement's flip to `STALE` does not propagate: no parent walk, no menu-item invalidation — `recipes.py:351-354`
- §3.5 L287 — insert — ambiguity — a non-`PLATED` `recipe_id` is refused `ERR_INVALID_REQUEST`/400 after position 7 and before position 37; the backing recipe's `status` is not examined at creation — `menu_items.py:39-45`
- §3.5 L303 — insert — ambiguity — item mix-line list ordering fully pinned (review `period_end` DESC, then review creation order, then line creation order) — `menu_items.py:156-159`
- §3.6 L323 — insert — ambiguity — hop 2's count-line marking keys on ingredients named **directly** by the recipe's active `INGREDIENT` components, not transitively — `cascade.py:93-101`
- §3.6 L325 — insert — ambiguity — hop 3 already-`STALE` asymmetry: an item of the changed recipe is rewritten regardless of prior state; an ancestor's item only when currently `FRESH` — `cascade.py:59-69,72-81`
Pass-1 hand-off verdicts: (1) `graph.py:103-104` tie-break — genuine silence, pinned; (2) duplicate `sequence_no` — made explicit; (3) `_seq` burned by a rejected depth check — left alone as unobservable (deleting a row leaves a gap but never reorders survivors).

### Pass 3 — calculations, proposals, spec orders, reviews, LTOs (`calc.py`, `routes/{proposals,spec_orders,reviews,ltos}.py`)
17 edits: 12 ambiguity-pins, 5 mismatch-revisions. 132702 → 137080 bytes.
- §2.7 — insert — ambiguity — the four expected-version fields carry no range constraint, so 0/negative is a well-formed 412, not a 400 — `guards.py:55`, `recipes.py:134,233`, `spec_orders.py:38`, `ltos.py:52`
- §3.6 submission — insert — ambiguity — "the same RecipeDeveloper's act" narrowed to role-not-identity; the caller is the SoD-excluded identity — `spec_orders.py:136,145`
- §3.6 rejection — insert — ambiguity — `rejection_reason` required, no length constraint — `spec_orders.py:155`
- §3.6 hop 1 — insert — ambiguity — a `COMPONENT_ADD` component opens with `unit_cost_micros_used`/`pack_base_units_snapshot` 0 and a null `removed_at` — `spec_orders.py:221-235`
- §3.6 rollback — insert — ambiguity — rollback's menu-item/promotion pass *is* hops 3–4, same asymmetry and `COSTED`→`PLANNED` revert — `spec_orders.py:359`, `cascade.py:52-81`
- §3.7 create — insert — ambiguity — the eight projection fields read back as **null**, not 0, until first submission — `proposals.py:39-50`, `serial.py:106-112`
- §3.7 submission — revise — **mismatch** — gates read the freshly computed figures; a failed gate persists nothing — `proposals.py:124-140`
- §3.7 step four — insert — ambiguity — baseline search spans every closed review (not scoped to `unit_id`) and reads the earliest-created line on a tie — `calc.py:39-53`
- §3.7 revision — insert — ambiguity — `last_revision_reason` required, no length constraint — `proposals.py:148`
- §3.7 list — insert — ambiguity — proposals list ordered `created_at` ascending — `proposals.py:72`
- §3.8 create — revise — ambiguity — `variance_flag` explicitly null until close — `reviews.py:54`
- §3.8 counts — insert — ambiguity — `synced_spec_version` = `version` of the first recipe directly naming the ingredient (mix lines in `created_at` order, within each the backing recipe then sub-recipes breadth-first by `sequence_no`), **0** when nothing consumes it; count-line creation bumps the review's `version` — `reviews.py:158-165,180`, `graph.py:341-367`
- §3.8 valuation — revise+insert — **mismatch**+ambiguity — the divisor is the **selected price row's** `pack_base_units_snapshot` (a count line has none); no selectable price row values the line at 0 and never raises `ERR_NO_PUBLISHED_PRICE` — `calc.py:164-173`, `serial.py:82-87`
- §3.8 classification — revise — **mismatch** — deleted the false "a line with zero units is rejected at mix-line creation"; pinned `cm_per_unit_cents` 0 with no division, `mix_pct_bps` 0 and `margin_threshold_cents` 0 when `total_units_sold` is 0 — `calc.py:114-127`, `reviews.py:95`
- §3.8 quadrants — revise+insert — **mismatch**+ambiguity — the "single-line review always yields a STAR" universal now excepts a lone `units_sold` 0 line (`PUZZLE`); duplicate mix lines for one item are allowed and the item keeps the last such line's class — `calc.py:129-145`
- §3.8 close — insert+revise — ambiguity+**mismatch** — close bumps each count line's `version` under either basis; `USAGE_BASED` divisor corrected to the price row's snapshot; a priceless line contributes 0 — `calc.py:159-181`
Pass-2 hand-off verdicts: `synced_spec_version` choice/0 case — genuine silence, pinned; valuation divisor — genuine mismatch, confirmed and revised in both §3.8 places; §2.7 no minimum — genuine silence, worded once generally for all four guarded writes; `used_base_units` clamp — already pinned, no edit; `graph.valued_usage` — confirmed dead code, deliberately not documented.

### Pass 4 — reconciliation (narrow; closes cross-pass contradictions rather than re-scanning)
6 edits. 137080 → 141442 bytes. All 38 pre-existing hunks survive at identical line numbers; 4 new hunk locations (116, 387, 391, 393) → 42 total.
- §2.6 L116 — insert — contradiction — the universal "invalidation continues sideways into the menu items" now defers to two exceptions (already-`STALE` items skipped except for the changed recipe's own items; retirement propagates nowhere) — `cascade.py:52-69`, `recipes.py:351-354`
- §2.10 closing L199 — revise — wrong-pin (over-broad universal) — path precedence scoped to the identifier rules; the everywhere-true chain added: rule 1 → rule 2 → all of rule 3 → path identifiers left to right → body identifiers per positions 4–13 → position 14 downward — `guards.py:16-29,36-43,180-210`, `recipes.py:129-148`, `feeds.py:56-61`, `reviews.py:93-98,141-147`, `ltos.py:46-54`, `catalogue.py:117-120`
- §3.9 L391 — revise — contradiction/under-determination — reverse edge re-derived from the only four `stale_menu_items_of` call sites; the FRESH-only vs unconditional split stated; retirement excluded — `cascade.py:37-81`, `feeds.py:176`, `recipes.py:53,351-354`, `spec_orders.py:254,359`
- §3.9 L387 — insert — wrong-pin (missing gate) — campaign creation checks neither item `status` nor `plate_cost_state` — `ltos.py:43-65`
- §3.9 L393 — insert — wrong-pin (missing gate) — launch checks neither, only campaign `COSTED` + window not elapsed + region capacity — `ltos.py:115-145`
- §3.7 L359 — insert — wrong-pin (missing gate) — proposal application checks neither item `status` nor `plate_cost_state` — `proposals.py:184-208`
Open-item verdicts: (1) pass-1's "outranks the numbering above" was false at *every* endpoint, not just the three pass 2 named — fixed. (2) §3.9 L391 rewritten from the complete call-site truth table — fixed. (3) §3.6 L325↔L329 cross-reference is sound (rollback makes the identical `stale_menu_items_of` call as approval) — no change. (4) three unchecked menu-item `status` gates — pinned rather than resting on §2.10 position 20 being exhaustive, since launch and application both mutate the item. (5) §3.8 L367→L369 "the explosion described next" resolves correctly. (6) §3.6 L323/L325 assert distinct behaviours and compose readably — no double assertion.

### Orchestrator verification
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` — 42 diff hunks, +20052 bytes — so the scan demonstrably ran.
- Integrity: 526 lines, all 48 `ERR_` ids present, all 63 scaffold endpoint paths present, file ends on the same real §5 table boundary (`| ERR_NO_PUBLISHED_PRICE | 422 Unprocessable Entity |`), no truncation.
- Difficulty-directive leak scan of `PRD_COMPLETED.md`: 0 hits.
- Step 9 touched only PRD prose — no implementation or test file was modified after the clean sweep, so the 8-round 381/381 result stands as the final verification.
- Housekeeping: `.scratch/` removed (all four passes cleaned their own subdirs), `__pycache__` dirs removed, `SWEEP_DONE` sentinel removed. `worklog.md` is the single worklog at the task root (no strays under `workspace/`). Retained deliverables: `workspace/sweep.sh`, `workspace/summarize_sweep.py`, `workspace/sweep.log` and the 8 passing `workspace/implementation/results.{1..8}.json`.

Pipeline complete: Steps 1–9 all executed, `workspace/PRD_COMPLETED.md` written.
