# Worklog — task_2965_fresh_department_date_code_markdown_shrink_management

## Step 1: Create task directory — 2026-09-05T23:09:27.438Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2965_fresh_department_date_code_markdown_shrink_management` and its `workspace/` subdirectory. Index 2965 was pre-assigned by the invoking command; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide with auto-allocation).

## Step 2: Generate Scaffold — 2026-09-06T00:56:30.000Z

Subagent summary (verbatim):

Lint is clean and all three artifacts are complete.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Coverage
  §1.5 endpoints declared:    71
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     55   (the linter counts only instances carrying a test_recipe)
  Calls scanned (§1.8+§1.9):  907
```

## Deliverables (`/home/ubuntu/github/CodingPRD/tasks/task_2965_fresh_department_date_code_markdown_shrink_management/`)

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 2946 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1486 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4186 |

`SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — no `scaffold_difficulty_design` / `scaffold_corner_design` keys. The other two files each have exactly one top-level key. `worklog.md` and `workspace/` untouched; scratch confined to `.scratch/step2/calc.py`.

## §1.0–§1.7 scale
`domain_name: fresh-date-code-markdown-shrink`, `api_prefix: /fresh`. 14 entities, 71 endpoints, 68 errors, 42 validations (single strict priority ladder 1–42), 17 calculations, 10 state-machine dimensions, 2 `concurrency_rules`, 5 roles. `complexity_profile`: primary `pricing_engine`, secondary `compliance_audit`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, topology `flat`, shape `cyclic`, role_model `segregation_of_duties`, consistency `immediate`.

## §1.8 — 9 rule_ids × 2 instances = 18
`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant` (instance names as listed in the file).

## §1.9 — 9 sections, 83 instances (55 full + 28 `excluded_because` stubs)
entities 11 (11/0) · state_machines 15 (9/6) · calculations 13 (7/6) · validations 9 (7/2) · endpoints 6 (6/0) · errors 21 (9/12) · rbac 3 (3/0) · complexity_layers 4 (2/2) · consistency_model 1 (1/0).

Sections finished this session: **rbac** — `callers_cannot_act_without_a_valid_role_header_or_outside_their_role` (401 on empty headers, 403 on an unknown role, plus one cross-role 403 per role), `shared_operations_accept_either_declared_role`, `recorder_cannot_verify_his_own_shrink_nor_approve_his_own_markdown`. **complexity_layers** — `each_concurrency_rule_rejects_its_own_stale_parent_version` (one OCC test per `concurrency_rules` entry: ERR_STALE_LOT_VERSION and ERR_STALE_ITEM_VERSION, plus version-increment ladder 1→2→3 on both parents), `shrink_budget_trigger_is_strict_and_its_lookback_window_is_closed` (ratio 19.99 against budgets 19.99/19.98/20.00, then the closed 7-day lower bound at exactly 2026-08-19T08:00:00.000Z vs +1 ms). **consistency_model** — `every_cascade_is_already_visible_in_the_response_that_caused_it`.

## Design adjudications
- **68 errors → 9 multi-trigger `violation_to_error` instances + 12 stubs**, rather than ~39 near-duplicate recipes; one combined instance covers all 11 entity-specific NOT_FOUND codes. Verified programmatically that every one of the 68 error_ids appears in §1.8 or §1.9.
- **One §1.5 fix**: `POST /fresh/shrink-events/{shrinkEventId}/dispute` declared `roles: [DepartmentManager]` while §1.7 declares it shared with ComplianceAuditor (and `withdraw`/`remediate` already list both). Added `ComplianceAuditor` to the endpoint's roles; §1.8's dispute instance uses DepartmentManager, so nothing else shifted.
- **Lint mechanics**: RBAC-denial calls are only lawful inside an instance whose name matches `is_negative_trigger()`, hence the `_cannot_` naming on the denial-matrix instance. Query-string params must *also* appear in `payload` (four `margin-report`/`margin-rollup` calls failed check (c) on the first run and were fixed).
- **Ambiguity traps removed while designing**: a single-rung `MEAT-SWEEP-2026` ladder for the sweep instance (so `lots_auto_marked_down` can't hit an approval-gated rung); withdrawal moved inside the 24 h posting lag so `shrink_events_posted` stays 1; lot sizes chosen so no dispute has to un-deplete a lot; no assertion on `compliance_status` between a `shrink_budget_pct` PATCH and the next declared recompute trigger (PATCH is deliberately not one).
- Skipped guide rows, deliberately: entities "Parent Relationships" (every entity is `parent: null`), calculations "Variant Selection" (subsumed by the reconciliation instance), state-machine `parallel` shape (shape is `cyclic`; the two DonationPickup dimensions are already asserted in §1.8).
- Note for Step 3/4: per instruction the `scenario:` key holds the raw text verbatim, including the leading "Generate task harder than expert level!" line — strip that line before it can reach PRD.md.

**Orchestrator post-step action:** the scaffold generator correctly flagged that the difficulty directive had been embedded verbatim in `SCAFFOLD.yaml`'s `scenario:` key. Per the known leak path (scaffold `scenario` → doc generator → PRD.md), the orchestrator stripped line 2 ("Generate task harder than expert level!") and the following blank line from `SCAFFOLD.yaml` before Step 4. Verified: `grep -c "harder than expert" SCAFFOLD.yaml` → 0; file is now 2944 lines and `scenario:` begins directly with "2965. Fresh Department Date-Code…". The directive was never forwarded to any downstream subagent.

## Step 3: Copy Shared Files — 2026-09-06T00:57:57.913Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T01:16:10.000Z

Subagent summary (verbatim):

PRD generation complete.

**Deliverable:** `.../workspace/PRD.md` — **565 lines**, built in 10 chunked `cat >>` appends (no single giant Write), verified with `wc -l` after each chunk. Document ends cleanly on the last row of the §5 table; `head` confirms the title and §1 are intact.

**Top-level sections (all present, in order):**
- `## 1. Introduction` (line 3)
- `## 2. Global Specifications & System-Wide Principles` (line 11) — 11 domain-derived subsections: 2.1 RBAC, 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Identity/Timestamps/Versioning/Logical Clock, 2.5 Nested Reads & Path Resolution, 2.6 Money/Percentages/Rounding, 2.7 Optimistic Concurrency, 2.8 Compliance Posture as Write Gate, 2.9 Cascades & Unit Conservation, 2.10 Four Kinds of Time Window, 2.11 Order of Rejection (all 42 validation priorities)
- `## 3. Business Logic & Workflows` (line 213) — 9 freely-grouped subsections (registry; lot receipt & sell-by; markdown ladder; labels & scan-price enforcement; sales/withdrawal/depletion; shrink lifecycle; donation dock windows/manifests/credit; past-date audits/findings/escalation/remediation; order recommendations, margin reporting & nightly ops run)
- `## 4. Endpoint Definitions` (line 412) — exactly 4 columns, 71 endpoint rows
- `## 5. Error Code Catalogue` (line 492) — exactly 2 columns, 68 error rows

**Hard Contract results (reported here only, never written into PRD.md):**
- **Contract 1 — Field-Name Coverage: PASS.** All 154 identifiers (every `entities[].fields[].name`, every endpoint `input` name with `?` stripped, every `{pathParam}`) appear verbatim in backticks. Extended passes also confirmed 0 missing across computed-endpoint `output` object keys, all state-machine state names, and every entity field `enum` value. (First run showed a false 133-miss; cause was my checker's backtick pairing being desynchronised by the ```json fences in §2.2 — re-run with fences stripped gives 0.)
- **Contract 2 — Rule Coverage: PASS.** All 68 error IDs appear in §1–§4 prose before the §5 table; all 42 validations' `error_id` values appear in prose; all 10 state machines' transitions verified present with from-state and to-state co-located; both `concurrency_rules` documented in §2.7 (`expected_lot_version`/`ERR_STALE_LOT_VERSION`, `expected_item_version`/`ERR_STALE_ITEM_VERSION`, both 412); all 17 calculations narrated including both `markdown_price` variant trios and both `shrink_history_order_feedback` variants with their sibling-branch asymmetries called out; all 15 declared constant values present verbatim (62.5 / 72.5 / 80, 50000, 200000, 3.5, 25, 30, 48, 20, 10, 40, 7, 3). Endpoint table roles match the scaffold exactly for all 71 endpoints (automated role-set diff, zero mismatches); method/path sets diff to zero both directions.
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 contain `/`, and zero bare or leading HTTP-method tokens appear in §3 either inside or outside backticks. Every endpoint is referred to by capability name. §2 mentions the `/fresh` prefix once (line 100), which is outside Contract 3's scope.
- Style: no pseudocode, no symbolic operators (`==`, `>=`, `+=`, `floor(`, `round_half_up(`), no fuzzy quantifiers. One rhetorical "approximately" was reworded to "partially" so the fuzzy-word scan is clean.

**Zero-Silence adjudications** (scaffold self-contradictions resolved in prose):
1. Manifest-line creation gate: entity transition said `logistics_status == SCHEDULED and manifest_status == DRAFT`, validation priority 11 said `DRAFT` manifest only. Followed the validation table; PRD states explicitly that `logistics_status` is deliberately not consulted, justified by the two-independent-dimensions design.
2. `Item.donation_eligible` false, and zero-unit assignment, have no declared code → both mapped to `ERR_LOT_NOT_PRICEABLE` (409).
3. Sealing a manifest whose `logistics_status` already reached `COMPLETED`/`CANCELLED`/`MISSED` has no declared code → mapped to `ERR_PICKUP_NOT_COMPLETABLE` (409).
4. `BLOCKED` gate scope: entity text listed 3 operations, validation 13 and the escalate endpoint listed 4 → used the 4-operation set (markdown creation, markdown void, sale posting, manifest-line creation).
5. `DEPLETED` declared terminal yet reachable outbound via shrink dispute → documented the transitions faithfully instead of asserting strict terminality.
6. Escalation of an unswept audit has no declared code → derived `ERR_ESCALATION_NOT_WARRANTED` (an unswept audit's `severity` is `NONE`, not `CRITICAL`); escalation of a swept audit with no `OPEN` findings → `ERR_FINDING_ALREADY_RESOLVED` (409), matching priority 12's declared code set.
7. Waiver actor: the finding transition names `ComplianceAuditor` while the endpoint lists both roles → PRD reserves `waive` to `ComplianceAuditor` (`ERR_UNAUTHORIZED`, 403, for a manager) while allowing both roles to remediate by withdrawal.

Scratch: used and then removed `.scratch/step4/` only; the sibling `.scratch/step2/` is untouched. No other file in the task dir was created, modified, or deleted — `worklog.md`, `SCAFFOLD*.yaml`, and `workspace/INSTRUCTION.md` were not touched, and neither difficulty/corner design file was opened.

**Orchestrator truncation check (per the known doc-generator failure mode):** PASS. `PRD.md` is 565 lines; `grep '^## '` returns exactly the 5 expected top-level sections; the file's final line is a complete §5 table row (`| ERR_PRICE_BELOW_COST_FLOOR | 422 |`), not a mid-sentence cut. §4 contains 73 pipe rows (71 endpoints + header + separator) and §5 contains 68 `ERR_` rows, matching the scaffold's declared counts. Difficulty-directive leak scan (`grep -in "harder than expert|expert level|scaffold"`) returns nothing. No regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-06T02:44:00.000Z

Subagent summary (verbatim):

Step 5 is complete. All test infrastructure and test cases are on disk at the **task root** (not under `workspace/`).

## Files written

`test_helpers/` — 9 files, 2452 lines
`__init__.py` 70, `types.py` 444, `api_errors.py` 151, `api_client.py` 364, `constants.py` 128, `test_users.py` 127, `factories.py` 285, `assertions.py` 237, `fixtures.py` 646

`test_suite/` — 12 files, 6528 lines
`conftest.py` 41; `test_01_pricing_variant_readings.py` 465 (8 tests), `test_02_state_loops_and_rejection_order.py` 433 (8), `test_03_cascades_and_boundaries.py` 452 (8), `test_04_cross_entity_overlap_and_compensation.py` 653 (12), `test_05_entity_shapes.py` 492 (11), `test_06_state_machines.py` 568 (9), `test_07_calculations.py` 606 (7), `test_08_validations.py` 480 (7), `test_09_endpoints.py` 559 (5), `test_10_errors.py` 988 (8), `test_11_rbac_and_consistency.py` 791 (6)

**Total: 89 tests.**

## Design-index coverage

- **Queue A (SCAFFOLD_DIFFICULTY_DESIGN.yaml):** 18 non-stub instances, **18/18 translated, 0 skipped** (36 tests — each instance is a two-arm variant-against-variant design, split into one test per arm, both tagged to that instance).
- **Queue B (SCAFFOLD_CORNER_DESIGN.yaml):** 83 instances, 28 are `excluded_because:` stubs (never translated), **55 non-stub → 53 translated, 2 skipped** (53 tests).

Verified mechanically: 89 `Design:` tags for 89 tests, **0 dangling, 0 dual-tagged, 0 untagged, 0 stub-tagged**; no `skip`/`skipif`/`xfail` anywhere; every file compiles; no unused imports.

## Skipped instances (2, gaps left as gaps)

1. `endpoints/store_create_read_update_and_filtered_list_round_trip` — the recipe PATCHes a store to `status: "CLOSED"` expecting 200, but PRD §3.1 declares store `status` is only `ACTIVE` or `SUSPENDED`, so the PRD derives a 400, not the asserted round-trip.
2. `errors/the_same_lot_cannot_be_manifested_twice_on_one_pickup` — after the first pledge the lot is `DONATION_PENDING`, and §2.11 check 8 (lot state suitability on manifest-line creation → `ERR_LOT_NOT_PRICEABLE` 409) precedes check 36, so the PRD derives a different code than `ERR_DUPLICATE_LOT_ASSIGNMENT`. I checked the alternate routes (cancel/unwind gives 201 because the old line is `REJECTED`; partial completion needs a `SEALED` manifest, which check 11 refuses first) — the asserted code is unreachable.

## Design-index defects corrected in this final file (each narrated in the test docstring)

- `complexity_layers/shrink_budget_trigger...` and `consistency_model/every_cascade...` both specify a **single-rung ladder**, which PRD §3.1 refuses (`rungs` must hold 2–6 entries). Both use the standard two-rung MEAT ladder; rung selection and every asserted figure are unchanged.
- `complexity_layers/each_concurrency_rule...` names the label price field `price_cents`; PRD §3.3 calls it `to_price_cents`.
- The same recipe claims a `shrink_budget_pct` PATCH is not a recompute trigger, while PRD line 437 says it recomputes the posture. The recipe asserts nothing between a PATCH and the next declared trigger, and neither does the test.

## Other repairs made during the final verification passes

- Six paraphrased PRD citations in `test_05`, `test_06`, `test_08`, `test_09`, `test_10` and `test_11` were replaced with verbatim text (e.g. §2.11 item 4 is "validated left to right", not "strictly left to right"; §2.9's unit-conservation sentence; §2.11 item 12's full wording). An automated verbatim-substring check over every docstring quotation now passes.
- Removed one unused `Optional` import from `test_helpers/factories.py`.

Nothing under `workspace/` was created, modified, read or listed (it still holds only `INSTRUCTION.md`, `PRD.md`, `implementation`); `worklog.md` was not touched; `.scratch/step5` was removed and the `.scratch` parent left intact.

## Step 6: Generate Implementation — 2026-09-06T02:44:00.000Z

(Launched concurrently with Step 5 in a single orchestrator message, so the implementation generator could not see `test_suite/` — the directory did not exist when it started.)

Subagent summary (verbatim):

Implementation complete and verified.

## Files written — `workspace/implementation/`

| File | Lines |
|---|---|
| `app.py` | 75 |
| `util.py` | 135 |
| `errors.py` | 94 |
| `db.py` | 63 |
| `response.py` | 56 |
| `middleware.py` | 57 |
| `records.py` | 163 |
| `validate.py` | 235 |
| `calc.py` | 316 |
| `services.py` | 356 |
| `routes/__init__.py` | 0 |
| `routes/common.py` | 50 |
| `routes/registry.py` | 299 |
| `routes/departments.py` | 297 |
| `routes/lots.py` | 426 |
| `routes/donations.py` | 334 |
| `routes/shrink.py` | 196 |
| `routes/compliance.py` | 249 |
| `routes/orders.py` | 122 |
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| **total** | **3534** |

No stray files, no `__pycache__`, no data files. Everything built with chunked `cat >>` appends.

## Endpoint parity
**71 route/method pairs registered** — programmatically diffed against `SCAFFOLD.yaml`'s endpoint list: `missing in impl: []`, `extra in impl: []`. That is the 70 `/fresh/...` endpoints plus `POST /_clock/set_current_utc`.

## Structure

- **Storage / clock**: `db.py` holds 14 plain dicts inside a `Store` object, all empty at boot; nothing is seeded or hardcoded. The logical clock starts at exactly `2026-08-01T00:00:00Z` and is only moved by `POST /_clock/set_current_utc`; host wall-clock time is never read. Every ordering uses `(created_at, _seq)` so equal logical timestamps stay insertion-stable.
- **Envelope**: `response.py` builds `meta.api_request_id` (`req_` + 20 uppercase alnum) and `api_request_timestamp` from the clock, with 3-digit fractional ISO-8601 UTC everywhere; pagination meta added by `routes/common.listing`.
- **Validation priority ladder**: `middleware.authenticate` covers rungs 1–2, `validate.py` rung 3 (body shape, enums, integer ranges, dates/instants, `limit` 1–100, `offset` ≥ 0), `records.*_by_id` rungs 4–5, `require_pickup_ownership` rung 6. Rungs 7–42 are expressed as literal top-to-bottom statement order inside each handler, in the PRD's numeric order — no helper reorders them. The two explicitly-called-out consequences hold (stale beats blocked; self-approval beats the fiscal caps).
- **Optimistic concurrency**: `expected_lot_version` on markdown creation (→ `ERR_STALE_LOT_VERSION` 412) and `expected_item_version` on recommendation creation (→ `ERR_STALE_ITEM_VERSION` 412), both checked at rung 7 before any state gate; omission is a rung-3 400. `records.touch()` bumps `version`/`updated_at` and is idempotent per request.
- **State machines**: `services.py` centralises every cascade — dual-dimension pickups (`logistics_status` × `manifest_status`, neither constraining the other), the cyclic shrink machine RECORDED→VERIFIED→DISPUTED→RECORDED with compensating unit movement, the six-step withdrawal cascade (synthetic `WITHDRAWAL_AUTO` shrink → unit move → label voids → manifest-line rejections → lot `WITHDRAWN` → department aggregates/posture), donation completion with partial-pickup unwind, and audit finding bubble-up to `REMEDIATED`.
- **Calculations**: `calc.py` only, `Decimal` + `ROUND_HALF_UP` on magnitude with sign preserved; no float or `round()`. Covers sell-by instant, `days_remaining`/`hours_past_date` floor division, expected sell-through (profile multiplier + promo lift, capped 100), ladder rung selection and shortfall steps, markdown price with cost floor, per-lot-then-sum margin lines, shrink cost ratio over the 7-day lookback, severity multiplier/points/band, donation credit tiers, and the two order-feedback methods.

## Smoke-test result
Three cold-boot rounds on high random ports (each killed by its exact PID via `ss -tlnp`; no `pkill` used).

- Round 1 (~60 happy-path assertions across every subsystem): **0 failures**, with hand-checked arithmetic — markdown quote 584/450, `total_discount_pct` 35.04, seal 5840 @ 62.5 % → 3650 credit, shrink 2070/2336, audit 23 units × 3 = 69 points → CRITICAL, margin −17781 / −608.94 %, ops-run posting of 2 aged events.
- Round 2 (negative paths, rungs, supersession, scan-price enforcement, pagination, recommendations): all correct; the 5 reported mismatches were traced to a wrong assumption in my own script about which lot `?status=FRESH` returns first.
- Round 3 (referential 404s, dock/cold-chain/department gates, deplete-via-sale, cancel-release, nightly sweep, label void, withdrawal, disabled programme, suspended partner, ladder retire): 2 reported mismatches, both confirmed against PRD §2.11 as correct precedence rather than defects (see ambiguities).
- Final cold boot: `GET /fresh/stores` returns an empty array with `api_request_timestamp` `2026-08-01T00:00:00.000Z`; unauthenticated request → 401.

## PRD ambiguities resolved
1. **`ERR_DUPLICATE_LOT_ASSIGNMENT` (rung 36) is unreachable under the literal ladder.** Rung 8 rejects a `DONATION_PENDING` lot with `ERR_LOT_NOT_PRICEABLE`, and any second line for the same lot presupposes that status. I kept the PRD-literal order (rung 8 wins), since §2.11 states no later check may mask an earlier one. Both return 409, only the `error_id` differs. Flagging this as the single highest-risk divergence if the test suite exercises the duplicate path.
2. **Version-bump scope**: enumeration-strict. Department aggregates (liability, shrink ratio, posture, open-finding count), partner counters, `past_date_flag`-only writes and other lots' `expected_sell_through_pct` are recomputed without bumping `version`/`updated_at`. Assignment lines are touched on status change but not for seal/reconcile `line_credit_cents` rewrites.
3. **Escalation precedence**: rung 12's `ERR_FINDING_ALREADY_RESOLVED` fires only for a `SWEPT` audit with no OPEN finding, so an unswept audit falls through to `ERR_ESCALATION_NOT_WARRANTED` (rung 38), which also catches `disposition_status != PENDING`.
4. **31-day report window** read inclusively: `(end - start).days + 1 <= 31`.
5. **`FORWARD_LOOKING_PROJECTED`** projects over all still-open lots of the item, not only lots inside the window.
6. **Withdrawal's synthetic shrink event** is created already `VERIFIED` with `verified_at` = clock and `verified_by_user_id` = `"system"`, so the nightly posting step can reach it after the 24-hour lag.
7. **`provisional_value_cents`** is recomputed on assignment creation, withdrawal-driven line rejection, seal and reconcile — not on complete/cancel/miss (those only move `units_picked_up_total` / `assignment_count`).
8. **Shrink verification that drains a `DONATION_PENDING` lot** leaves the lot pledged rather than forcing `DEPLETED` (`deplete_if_empty` applies to `FRESH`/`MARKED_DOWN` only), so the manifest line stays coherent — a deliberate reading of the PRD's blanket "becomes DEPLETED".
9. **Requests are serialised** by a WSGI lock wrapper so derived aggregates can never interleave; Flask still runs threaded for socket handling.

**Orchestrator layout verification:** `test_helpers/` and `test_suite/` are at the task root (not under `workspace/`); `workspace/` contains exactly `INSTRUCTION.md`, `PRD.md`, `implementation/` (plus the orchestrator-written `sweep.sh`). 89 test functions confirmed across 11 test files. Notable convergence: Step 5 and Step 6 independently and without seeing each other's output reached the same conclusion about `ERR_DUPLICATE_LOT_ASSIGNMENT` being unreachable under the literal §2.11 ladder — Step 5 skipped the instance, Step 6 kept the PRD-literal rung-8 precedence. This agreement means the highest-risk divergence each flagged is already neutralised and should produce no Step 7 failure.

**Orchestrator pre-Step-7 action:** wrote `workspace/sweep.sh` (executable), a pre-canned 8-round sweep launcher that Step 7 must use verbatim. It exists to defeat three known sweep failure modes on this host: (a) SIGTERM reaping of backgrounded rounds — solved by launching the script under `setsid nohup`; (b) literal-quote injection into `--start-command` from nesting a for-loop inside `setsid nohup bash -c '...'` — solved by having no inline quoting layer at all; (c) the wrapper returning in ~1 min while rounds still run, tempting a relaunch — solved by a `SWEEP_DONE` sentinel touched only after `wait`, which Step 7 polls for. The script also writes per-round `round.$i.log` files, since one shared `sweep.log` fd across 8 concurrent rounds produces spliced, undiagnosable output.

## Step 7: Run Tests and Iterate — 2026-09-06T03:02:00.000Z

Subagent summary (verbatim):

Loop complete — all 8 rounds pass 89/89.

## Iterations run
2 (one diagnostic sweep, one confirming sweep).

## Final sweep evidence
`results.1.json` … `results.8.json`: **89/89 passed, 0 failed, 0 errors** in every round.

Iteration-1 baseline was 87/89 in all 8 rounds, with the same two tests failing deterministically in every round (so nothing here was load-induced — no timeouts, no connection resets, no `Terminated` in any `round.$i.log`).

## Tests deleted
None. Both failures resolved without deleting a test.

## Fixes applied to `test_suite/`

**1. `test_suite/test_09_endpoints.py`** — `test_the_nightly_run_skips_every_row_that_does_not_qualify_in_each_phase` (STEP 2, test request inconsistent with PRD).

The test built its ladder with `rungs=[MEAT_TWO_RUNGS[0]]` — a **one-rung** array. PRD §3.1 states verbatim that a ladder's rungs are "an ordered array of between 2 and 6 objects", and activation "re-checks that the rung array holds at least two entries". The implementation correctly answered `ERR_INVALID_REQUEST` ("Field 'rungs' has too few entries"), so the whole scenario collapsed at setup. Fixed the malformed payload, not the PRD-required check.

The test needs lot A (days remaining 4 at the sweep instant) to reach **no** rung and past-date lot B (days remaining −2) to land on **rung 0** at 15%. That forces `max(days_remaining_max) ≤ 3` and the deeper rung's `days_remaining_max < −2`, so the second rung is parked at `days_remaining_max: -3, discount_pct: 50`. This is PRD-legal — §3.1 bounds a rung only by strictly-decreasing `days_remaining_max` / strictly-increasing `discount_pct` (and `0 < discount_pct < 100`), and §3.2 states days remaining "is an integer and may be negative". Every asserted number in the test (509 / rung 0 / 15.03, `lots_flagged_past_date=1`, `lots_auto_marked_down=1`, `shrink_events_posted=1`, `pickups_missed=1`, liability 540, ratio 44.45, `compliance_status=WATCH`) is preserved unchanged.

**2. `test_suite/test_06_state_machines.py`** — `test_cancelling_a_pickup_only_unwinds_the_line_that_is_still_assigned` (STEP 1b/1c, **branch-asymmetric side effect**, partial coverage).

Failure: `provisional_value_cents expected 0, got 5990`. PRD §3.5 explicitly says the *withdrawal* rejection path decrements `assignment_count` and recomputes `provisional_value_cents`. PRD §3.7's *cancellation* clause is a closed enumeration of its own effects — "moves `logistics_status` to `CANCELLED`, turns every `ASSIGNED` line into `REJECTED`, releases the dock window …, recomputes `markdown_liability_cents` for every affected department, and increments `version` by one" — and names neither counter, even though it does bother to name one recomputation. So two faithful readings exist (stored field mutated only where PRD says so → 5990; field re-derived from its `ASSIGNED`-line definition → 0), which breaks unique derivability. Per §1c I removed only the two uncovered post-cancel assertions (`assignment_count=0`, `provisional_value_cents=0`) and kept everything covered: `logistics_status=CANCELLED`, `manifest_status=DRAFT`, both lines `REJECTED`, lot P1 stays `WITHDRAWN` at 0 units, lot P2 unwinds to `FRESH` at rung −1 with 10 on hand, and unit conservation. The earlier `assignment_count == 2` (after two pledges) and `== 1` (after the withdrawal) assertions are verbatim-covered and were kept. Rationale recorded in the docstring.

## Fixes applied to `test_helpers/`
None needed.

## Fixes applied to `implementation/`
None. Notably I did **not** add a `provisional_value_cents` recompute to `services.reject_open_lines` — that would be adding a side effect with no verbatim PRD sentence behind it, which the cardinal rules forbid, even though it would have made the failing assertion pass and would have made the implementation internally symmetric with `services.withdraw_lot`.

## Load-induced findings
None. Both iteration-1 failures were deterministic across all 8 rounds, with real assertion/response evidence (a 400 error body and a concrete money mismatch) rather than timeout or connection signatures. I additionally spot-checked each fix against a manually booted server on a random high port before committing to the confirming sweep, killing only that PID.

**Orchestrator independent verification of the Step 7 sweep** (prior runs have seen a Step 7 subagent claim a clean sweep with no artifacts behind it, so the orchestrator re-checks the evidence rather than trusting the report):
- All 8 `workspace/implementation/results.$i.json` files exist. Parsed each: every round reports `passed=89, total=89, failed=0, errors=0`. Confirmed.
- 89 `def test_` functions on disk across `test_suite/*.py` — matches the 89 the sweep ran and the 89 Step 5 generated, i.e. the two Step 7 repairs were in-place edits and no test was silently dropped.
- `grep -rn "pytest.mark.skip\|xfail" test_suite/ test_helpers/` → no matches. No test was neutralised instead of fixed.
- `grep -l "Terminated" workspace/round.*.log` → no matches, corroborating that no round was SIGTERM-reaped and the results are from complete runs.

**Orchestrator Step 8 skip-condition adjudication:** Step 7 ran 2 iterations with 2 `test_suite/` fixes, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is not met — Step 8 runs. It is worth noting *why* it should run despite 0 implementation fixes: Step 7's second fix is a textbook PRD silence, not a fixture bug. The implementation resolved cancellation's effect on `assignment_count` / `provisional_value_cents` one way (leave both alone), a second faithful reader would resolve it the other way (re-derive from `ASSIGNED` lines), and Step 7 could only respond by removing the two assertions. That silence is exactly what Step 8 exists to pin. Step 7's first fix, by contrast, was a pure malformed-payload fixture bug with no PRD ambiguity behind it, and Step 8 is expected to make no edit for it.

## Step 8: Finalize PRD — 2026-09-06T03:08:30.000Z

Subagent summary (verbatim):

Done. One edit, one line changed.

## Line counts
- `PRD.md`: 565 lines; `PRD_FINALIZED.md`: 565 lines — 0% line delta (one line rewritten in place, +3 sentences).

## Changes
- **§3.7 ("When the truck does not come.")** — *insert* — pinned which pickup counters a cancellation re-derives: `assignment_count` is re-derived from the surviving lines and therefore lands at 0, while `provisional_value_cents` is **not** re-run and keeps the value it already held; also stated that the nightly run's `MISSED` route applies the identical effects, counters included — `implementation/services.py:120-133` (`reject_open_lines` → `recompute_pickup_rollups` only, no `revalue_manifest`), `implementation/routes/donations.py:310`, `implementation/services.py:334-337`.

## Per-edit pre-edit search log

**Edit 1 — §3.7 cancellation counters**
- **(a) Subject identified:** which pickup-level derived fields (`assignment_count`, `provisional_value_cents`) each pickup/manifest/lot operation re-derives, and specifically what the cancellation and lapsed-window routes do to them.
- **(b) Impl paths enumerated (grepped `assignment_count|provisional_value_cents|reject_open_lines|recompute_pickup_rollups|revalue_manifest` across `implementation/`, then read each site):**
  - `routes/donations.py:131-145` `create_pickup` — both initialised to 0 (matches PRD §3.7 verbatim, untouched).
  - `routes/donations.py:211-213` `create_assignment` — `recompute_pickup_rollups` + `revalue_manifest(ASSIGNED, write_lines=False)`; both fields move (matches PRD §3.7 pledge clause, untouched).
  - `routes/donations.py:229` `seal` — reads `assignment_count` for `ERR_EMPTY_MANIFEST`; `revalue_manifest(ASSIGNED)` full (matches PRD, untouched).
  - `routes/donations.py:289` `complete` — `recompute_pickup_rollups` only; `provisional_value_cents` deliberately *not* re-run (unchanged value is arithmetically identical since sealed ASSIGNED lines become the PICKED_UP set, so no PRD wording needed).
  - `routes/donations.py:310` `cancel` → `services.reject_open_lines` — **the Step 7 site**.
  - `routes/donations.py:332` `reconcile` — `revalue_manifest(PICKED_UP)` rewrites provisional/credit fields; `assignment_count` not recomputed (value already final either way).
  - `services.py:62-69` `recompute_pickup_rollups` — the single definition of `assignment_count` (count of `ASSIGNED` or `PICKED_UP`) and `units_picked_up_total`.
  - `services.py:120-133` `reject_open_lines` — calls `recompute_pickup_rollups` but **not** `revalue_manifest`; used by both `cancel` and the sweep's `MISSED` path.
  - `services.py:173-180` `withdraw_lot` step 5 — the *parallel* rejection path, which calls **both** `recompute_pickup_rollups` and `revalue_manifest(..., write_lines=False)`; this is why PRD §3.5 step 5 is already correct and was left verbatim.
  - `services.py:327-337` `run_department_sweep` step 4 (`MISSED`) — `touch(pickup)` + `reject_open_lines` + per-department `recompute_liability`; confirms the "same effects, counters included" claim including dock release (`MISSED` is outside `LIVE_LOGISTICS` at `routes/donations.py:121`) and lot unwind (`services.py:105-117`).
  - `services.py:201-224` `revalue_manifest` — confirmed `write_lines=False` writes only `provisional_value_cents`, leaving `credit_rate_pct`/`manifest_credit_cents`/`line_credit_cents` alone.
- **(c) Wording adjustments made:** (i) dropped an earlier draft that spelled out `assignment_count` as "the number of lines still in `ASSIGNED` or `PICKED_UP`" — a correct global definition, but a broader universal than the Step 7 evidence supports; replaced with the weaker, still fully determinate "re-derives … from the lines that survive the rejection … so it lands at 0". (ii) dropped a draft clause claiming `credit_rate_pct` and `manifest_credit_cents` are also left untouched and that "only a later reconciliation rewrites them" — true of the impl, but an unnecessary widening beyond the Step 7 item and PRD is already silent there, so behaviour is unaffected. (iii) changed "keeps whatever value the last pledge or sealing left" to "keeps whatever value it already held", because a prior `withdraw_lot` can also be the writer that last set it (`services.py:180`).

## Not patched (deliberately)
- **Step 7 item 1** (test_09 one-rung ladder) is a pure fixture bug, not a PRD silence: §3.1 already states verbatim that `rungs` holds "between 2 and 6 objects" and that activation re-checks "at least two entries", and `routes/registry.py:198` enforces exactly `min_items=2, max_items=6` with `ERR_INVALID_REQUEST`. The test's negative `days_remaining_max: -3` rung is legal under §3.1 (only strict monotonicity and `0 < discount_pct < 100` are bounded; `routes/registry.py:200-225` adds no range check) and its rung-0 landing for a lot at days-remaining −2 follows §3.3's inclusive `>=` candidate rule as implemented in `calc.base_rung_index`. No PRD edit traces to it.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (351), both files 565 lines, and the files are not byte-identical. The change is confined to §3.7's "When the truck does not come." paragraph and does precisely what was reported: it pins the asymmetric counter treatment on cancellation (`assignment_count` re-derived to 0, `provisional_value_cents` left as-is) and extends the same statement to the nightly `MISSED` route. This is the correct Step 8 outcome — the single Step 7 finding that was a genuine PRD unique-derivability collapse got pinned, and the fixture-only finding correctly produced no edit.

## Step 9: Complete PRD — 2026-09-06T03:45:00.000Z

**Orchestrator design decision.** Step 9 is a full PRD-vs-`implementation/` scan, and the implementation here is 3534 lines across 19 modules. A single subagent reliably under-scans at that size (the known failure mode is a `PRD_COMPLETED.md` byte-identical to its input, i.e. the scan never actually ran). The orchestrator therefore partitioned the scan by implementation module into four **sequential** passes over one shared `PRD_COMPLETED.md` — sequential, not concurrent, because all four edit the same file. Pass 1 alone performed the `cp` that creates the file; passes 2–4 were explicitly forbidden from re-running it, and each was told the current line count so it could detect an accidental overwrite. Every pass was forbidden from re-emitting the document with a whole-file Write (64k output cap → silent truncation) and required to verify section/table integrity before exiting. Pass 4 is a dedicated reconciliation pass, added because a partitioned scan systematically produces one defect class of its own: a pass pins a specific rule in its own section while a general claim elsewhere — owned by another pass — still overstates. Pass 4 was the only pass permitted to edit across partition boundaries, and was explicitly instructed to *fix* rather than merely re-report the cross-pass referrals.

Partition:
- **Pass 1 — cross-cutting core**: `app.py`, `util.py`, `errors.py`, `db.py`, `response.py`, `middleware.py`, `records.py`, `validate.py`, `routes/common.py`, `start.sh`. Subjects: envelope/`meta`, `api_request_id` format, timestamp precision, logical clock, id format, `version`/`created_at`/`updated_at`, pagination and ordering, auth and rungs 1–2, generic shape validation and rung 3, referential 404s and rungs 4–5, ownership at rung 6, error body shape.
- **Pass 2 — registry / departments / lots / calculations**: `routes/registry.py`, `routes/departments.py`, `routes/lots.py`, `calc.py`.
- **Pass 3 — donations / shrink / compliance / orders / cascades**: `routes/donations.py`, `routes/shrink.py`, `routes/compliance.py`, `routes/orders.py`, `services.py`.
- **Pass 4 — reconciliation**: no new coverage; closes cross-pass contradictions and runs a targeted self-contradiction sweep.

### Pass 1 summary (verbatim)

Pass 1 complete. Ran `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md`. Line count 565 → 567. `grep -c '^## '` → 5 (§1–§5 intact at lines 3/11/215/414/494).

Counts: **13 ambiguity-pins, 5 mismatch-revisions** (18 discrete changes).

Changes: §2.2 `api_request_id` is `req_` + exactly 20 chars from `A`–`Z`/`0`–`9` (response.py:13-14); §2.2 `api_request_timestamp` read from the logical clock, not wall time (response.py:20); §2.3 non-integer `limit`/`offset` → 400, no upper bound on `offset`, empty-string query param treated as omitted (validate.py:167-193); §2.3 `created_at`-ascending ties broken by server insertion order, governing every "created_at ascending" walk in the doc (db.py:48-59); §2.3 `total_count` computed after the `DonationPartner` narrowing, `has_more` = `offset + len(page) < total_count`, empty filter match → 200 not 404 (response.py:45, routes/common.py:41-50); §2.4 `id` is a canonical lowercase 36-char v4 UUID, a non-UUID path id gets the resource 404 not a 400 (db.py:44, records.py:47-53); §2.4 **mismatch** — "Every instant this API accepts or emits uses that same format" was false: emission is always 3 fractional digits but input accepts 0–9 digits and `Z`/`z`/`+00:00`, extra digits truncated not rounded on echo (util.py:68-114); §2.4 clock endpoint pinned — `POST /_clock/set_current_utc`, all five roles, `current_utc` required, 200, echo re-serialised to 3 digits, backwards moves legal (routes/orders.py:115-122); §2.6 the two-decimal limit binds inputs — >2 fractional digits is `ERR_INVALID_REQUEST`, never silent rounding (validate.py:80-84); §2.6 percentages emitted as JSON numbers with no meaningful spelling (`60` not `60.00`) (util.py:59-64); §2.9 new paragraph — `version` bumped once per request however many cascade steps touch a row, and a row the request created stays at 1 (records.py:17-44); §2.11 rung 3 — absent/empty body accepted as `{}` on all-optional endpoints, non-object/invalid JSON is 400, undeclared keys ignored (validate.py:10-27); §2.1 **mismatch** — ownership guards the pickup resource only, "any pickup or manifest resource" was wrong (middleware.py:51-57, donations.py:58-61); §2.1 **mismatch** — list narrowing applies to pickups only, manifest lines neither ownership-checked nor narrowed (donations.py:64-76); §4 preamble **mismatch** — partner restriction scoped to donation-pickup endpoints, the two donation-assignment reads exempt; §4 preamble **mismatch** — "path not-found before any body validation" contradicted §2.11 and impl, every route runs shape validation before the path lookup so a bad body + bad path id yields 400 (lots.py:136-148, departments.py:148-153); §4 preamble malformed filter values are 400, bool case-insensitive `true|false|1|0`, margin report/rollup require both window params; §5 intro an unrouted path or unsupported method returns the error envelope with `ERR_INVALID_REQUEST` but 404/405 rather than 400 (app.py:49-58).

Already correctly pinned (evidence the scan ran): envelope shapes; the error-id → HTTP status map is **byte-for-byte identical** to §5's 68-row table (programmatic diff of errors.py vs the table — no extras, no gaps, no status mismatch); auth rungs 1–2 including empty-header handling; rung 6 ordering after role check and pickup 404 and before every state gate; logical clock boots at exactly `2026-08-01T00:00:00Z` with no wall-clock fallback; `ScanPriceCheck` as the sole row created with neither `updated_at` nor `version`; `limit` default 10 range 1–100, `offset` default 0, ordering never overridable; all emitted instants go through `fmt_instant`, every `isoformat()` is on a `date`; ROUND_HALF_UP sign-preserving magnitude rounding, money as integer cents, no `Decimal` reaching `jsonify`; body-FK 404 codes and left-to-right path resolution.

Referrals to later passes: lots.py:314 `label_barcode_snapshot` newest-`APPLIED` selection; lots.py:325-326 `LOT_WITHDRAWN` cascade guarded by lot status; departments.py:139 unchanged-`shrink_budget_pct` PATCH skipping the posture recompute; orders.py:105-107 issuance `ERR_INSUFFICIENT_SHRINK_HISTORY` unnamed in §3.9.

### Pass 2 summary (verbatim)

567 lines before → 567 after (all 26 edits in-paragraph). `grep -c '^## '` = 5. Did NOT `cp` or recreate the file; pass 1's 18 edits verified intact, error catalogue byte-identical, 141 table rows intact.

Counts: **11 ambiguity-pins, 15 mismatch-revisions** (26 changes).

Changes: §2.8 posture-recompute trigger list now names "`shrink_budget_pct` revised to a value it did not already hold" and states markdown/void/sale/lot receipt/manifest line/pickup cancellation do not recompute posture (departments.py:143-144); §2.9 carved derived roll-ups out of the universal version-bump rule — department aggregates and `sweep_epoch`, a lot's lone `expected_sell_through_pct` refresh, a pickup's counter re-derivation during withdrawal, and partner counters never bump `version`/`updated_at`, and a Department bumps only on PATCH (records.py:33, departments.py:142 as the only `touch(department)` site); §2.9 `markdown_liability_cents` trigger list extended with lot receipt, manifest-line creation, pickup cancellation, lapse into MISSED; §3.1 `dock_door_codes` repeats not rejected but an explicit empty array is a shape violation; §3.1 every PATCH bumps `version` unconditionally even with no recognised field or an unchanged value; §3.1 `contact_email` 1-200 chars, partner `service_region_code` carries no charset restriction unlike a store's `region_code`; §3.1 rung `requires_manager_approval` may be omitted (then false), `days_remaining_max` has no range beyond integer; §3.1 **mismatch** ladder activation re-validates nothing (rungs immutable after creation), retirement leaves `activated_at` as stamped; §3.1 **mismatch** (referral 3) posture recompute fires only on a genuinely different `shrink_budget_pct` while an unchanged re-send still bumps `version`; §3.2 EST-refresh list extended with markdown void, withdrawal, donation completion, the nightly run refreshing every lot of the department, and the refresh re-reading the clock; §3.2 **mismatch** cap wording "exactly 100.00" → "exactly 100", rounding before the cap; §3.1 `shrink_budget_pct` default written 2.5 not 2.50; §3.3 markdown accepts only FRESH/MARKED_DOWN with units else `ERR_LOT_NOT_PRICEABLE` 409; §3.3 **mismatch** SELL_THROUGH price is "no higher", strictly lower except when the base rung is already last or the cost floor caps both; §3.3 `override_price_cents`/`expected_lot_version` integers ≥ 0, an override outranks any `pricing_variant`; §3.3 the self-approval check is unconditional on approval being needed, an approver on a non-gated markdown is discarded and `approved_by_user_id` stays null; §3.3 **mismatch** barcode zero-padding is a *minimum* width of 5, not exactly 5 (services.py:251); §3.3 a successful markdown returns the **label**, not the lot, at 201; §3.3 the deepening comparison runs on every markdown including the first (incumbent = rung −1 / base retail); §3.3 the quote's only business refusal is `ERR_RUNG_NOT_REACHED`; §3.4 label application checks label lifecycle first then lot status; §3.4 **mismatch** voiding recomputes EST unconditionally and neither apply nor void bumps the lot's version; §3.4 (referral 1) `label_barcode_snapshot` takes the newest APPLIED label, a check may be recorded against a lot in any status and in a BLOCKED department; §3.4 **mismatch** (referral 2) the `LOT_WITHDRAWN` cascade runs only while the lot is FRESH/MARKED_DOWN/DONATION_PENDING, otherwise the check is still written with that action and still answers 201 with no cascade; §3.9 **mismatch** FORWARD_LOOKING_PROJECTED yields `recommended_order_units` "never higher" not strictly lower; §3.9 **mismatch** the rollup reports eight (not nine) money/pct figures and no `lot_count`, only the five money lines plus `gross_margin_cents` are exact sums while both percentages are recomputed from store-wide totals, and a store with zero departments reports all zeros.

Referral verdicts: **lots.py:314** — plausible but *unreachable*, since every re-ladder voids the label it supersedes, so the ordering is unobservable; pinned anyway as a harmless true statement. **lots.py:325-326** — CONFIRMED and fixed. **departments.py:139** — CONFIRMED and fixed, and the referral over-reached on one point: the `version` bump does *not* depend on the value changing (`touch(department)` is unconditional); both halves pinned.

Already correctly pinned: `create_markdown`'s ten-step check order matches §2.11 exactly; `base_rung_index` max-of-candidates selection and `shortfall_steps` 20 %-per-step arithmetic; cost floor at 40 % of `unit_cost_cents`; `total_discount_pct` at 2 dp; sell-by via `end_of_day_utc` (23:59:59.999) with item-over-department shelf-life precedence; `days_remaining` floor division and `hours_past_date`/`past_date_flag` tolerance semantics; unit conservation across sale/withdraw/deplete; `margin_lines` round-then-sum with the 3.5 % waste surcharge; `margin_totals` zero-denominator → 0; the closed trailing-7-day `shrink_cost_ratio_pct` window; duplicate-key errors; ladder rung monotonicity and 2–6 bounds; label print price-match guard; the scan-check decision table including the 25¢ threshold and `PRICE_CORRECTION` for undercharge.

### Pass 3 summary (verbatim)

567 lines before → 567 after (every edit in-paragraph). `grep -c '^## '` = 5 before and after; all 9 §3 subsections present. Edited in place — no `cp`, no recreate, no whole-file Write.

Counts: **14 ambiguity-pins, 9 mismatch-revisions** (23 edits).

Changes: §3.5 step 1 the synthesised `WITHDRAWAL_AUTO` event's remaining fields (`verified_at` stamped, `posted_at`/`note` null, all three valuations captured as a manual record does) (services.py:136-156); §3.5 step 5 pickup rollups re-derived in full while `credit_rate_pct`/`manifest_credit_cents`/`line_credit_cents` are explicitly not re-run, so a sealed manifest keeps stale credit (services.py:173-180); §3.6 recording never consults the lot's `status` (a `DONATION_PENDING` lot accepts shrink; an off-shelf lot fails on `ERR_INSUFFICIENT_UNITS`); §3.6 verification recomputes `cost_value_cents` from the frozen snapshot but not `retail_value_cents`; §3.6 **mismatch** `DEPLETED` reachable only from FRESH/MARKED_DOWN — a `DONATION_PENDING` lot drained to zero stays pledged and keeps its labels; §3.6 **mismatch** a `RECORDED` dispute leaves the lot untouched in full, adding `expected_sell_through_pct`, `version` and department `shrink_cost_ratio_pct` to the untouched list; §3.6 **mismatch** resubmission rewrites `note` only when the key is present (omit = keep, explicit null = clear) and reprices `retail_value_cents` at the lot's live price; §3.7 pledge rollup definitions pinned, `credit_rate_pct`/`manifest_credit_cents` stay 0, adding a line bumps no pickup `version`; §3.7 **mismatch** completion leaves `assignment_count` unchanged, re-derives partner counters in full rather than incrementing, and does not re-run the sealed valuation; §3.7 **mismatch** a lot held back by a surviving live pledge takes no `version` bump from the release; §3.7 `REJECTED` lines keep the `line_credit_cents` sealing wrote, and a manifest with no `PICKED_UP` line lands provisional 0, credit 0, `credit_rate_pct` **62.50** (not 0); §3.8 **mismatch** sweep rollup recomputes `open_finding_count` in full, sets `past_date_flag` with no lot version bump, and leaves liability/ratio/`sweep_epoch` untouched; §3.8 escalation — the closed-findings refusal is evaluated first on a swept audit whatever its severity, a `REMEDIATED` audit gets `ERR_FINDING_ALREADY_RESOLVED`, an already-`ESCALATED` audit gets `ERR_ESCALATION_NOT_WARRANTED` (not idempotent); §3.8 closing a finding — `remediation` enum is `NONE`/`WITHDRAWN`, `WITHDRAWN` outranks `waive` when both are sent, `NONE` or `waive:false` is the same `ERR_REMEDIATION_NOT_PERMITTED`; §3.8 the auditor-only 403 fires inside the waiver path after the finding resolves and is found `OPEN`; §3.8 two edits **mismatch** `open_finding_count` "decremented" → recomputed in full; §3.9 only the newest `ISSUED` row is superseded when several coexist, and issuance's `received_units > 0` re-check is `ERR_INSUFFICIENT_SHRINK_HISTORY`/422; §3.9 step 1 `lots_flagged_past_date` counts only lots newly flipped false→true and the flag bumps no lot version; §3.9 step 2 gated on an `ACTIVE` ladder and every disqualification is a silent skip (no `ERR_RUNG_NOT_REACHED`/`ERR_RUNG_NOT_DEEPER`/`ERR_MAX_DISCOUNT_EXCEEDED`), `requires_manager_approval`/posture/versions all ignored so it cuts even in a `BLOCKED` department, `reason` `RE_LADDER` vs `LADDER_AUTO`; §3.9 step 3 scoped to this department's lots and posts any `cause_code`/`origin`; §3.9 step 4 **strictly** past `scheduled_window_end`, sweeps the whole store, recomputes liability for other departments too; §3.9 step 5 **mismatch** "every touched lot" → every lot of the department.

Referral verdicts: **orders.py:105-107** CONFIRMED and edited (error id named, positioned after `ERR_RECOMMENDATION_NOT_ISSUABLE`). **Nightly-run step 2** CONFIRMED and edited; the *department* `version`/`sweep_epoch` half needed no edit since §2.9 already pins it. **compliance.py:163 `open_finding_count`** CONFIRMED and edited — behaviourally equivalent (impossible for the stored count to be stale) but now consistent with §2.9's full-recompute framing. **§3.7 partner counters** CONFIRMED and edited.

Already correctly pinned: dock-window overlap (same store + same dock door, SCHEDULED/CONFIRMED only, 30-min buffer, both comparisons inclusive); pickup creation's five referential checks and their order; manifest-line eligibility's seven conditions with check order matching §2.11 items 8→11→13→14→15→20→27→34→36 exactly; duplicate-lot guard scoped to ASSIGNED/PICKED_UP; seal's four valuation steps with tiers 62.5/72.5/80 at the 50,000 and 200,000-cent floors, per-line rounding then exact integer sum; confirm's gates; completion's drained-vs-partial branches; cancel's effects; unwind's "no other live ASSIGNED pledge" guard; shrink recording's four cause codes with the SAMPLING gate before the units gate; verify's four-level cascade and self-verification 403; the compensating dispute (VERIFIED + MANUAL only) with unit restoration and `DEPLETED` reopen by `current_rung_index`, `WITHDRAWAL_AUTO`/`POSTED` refused; the inclusive 24-hour posting-lag boundary; audit opening's strict-after window and half-open unbuffered overlap with abutting accepted; the sweep's once-only gate, lot selection, `created_at` order, `hours_past_date` floor, multiplier bands 1/3/6 against `past_date_tolerance_hours` and 48 h, severity bands 0/1-9/10-29/30+; waiver requiring `severity_multiplier` 1; bubble-up to `REMEDIATED`; order recommendation's 31-day inclusive span, `received_units` 0 → 422, SAMPLING excluded from forecast shrink, projection over all the item's open lots, the 3-day horizon with the rounded `shrink_rate_pct` dampener floored at 0.

Referrals for pass 4: six items, all of the same shape — a general §2 claim that a §3 paragraph now contradicts.

### Pass 4 summary — reconciliation (verbatim)

Pass 4 complete. **14 targeted Edit-tool edits**, no whole-file rewrite, no `cp`.

**R1 CONFIRMED, fixed.** `shrink.py:126-156`: `compensating = status == "VERIFIED" and event["origin"] == "MANUAL"`; only inside `if compensating:` is `refresh_expected_sell_through` called. §3.2's refresh list narrowed to "on every shrink verification, on every compensating dispute of a `VERIFIED` shrink event whose `origin` is `MANUAL` — but never on the dispute of a merely `RECORDED` event".

**R2 CONFIRMED, fixed (2 edits).** §2.9's `markdown_liability_cents` and `shrink_cost_ratio_pct` bullets both narrowed to the compensating case, plus a positive statement that a cancellation and a `MISSED` lapse recompute liability but not the ratio (verified donations.py:310-315 and services.py:332-337 loop only `recompute_liability`).

**R3 CONFIRMED, fixed.** donations.py:277-284 + services.py:105-117: a partially drained lot goes to `unwind_from_donation`, which returns before `touch(lot)` when any ASSIGNED line of that lot sits on a SCHEDULED/CONFIRMED pickup, and the following `refresh_expected_sell_through` does not touch. §2.9 now says the completion bumps "every lot whose status the completion actually resolved", naming the still-pledged exception.

**R4 CONFIRMED, fixed.** §2.9's exemption generalised to "whenever some other operation reaches the pickup's manifest without transitioning the pickup itself", naming both call sites (donations.py:211-214, services.py:179-180).

**R5 CONFIRMED, fixed.** orders.py:97-111: `ERR_RECOMMENDATION_NOT_ISSUABLE` then `ERR_INSUFFICIENT_SHRINK_HISTORY`. Item 39 extended to issuance with the step-12-wins tie-break stated.

**R6 CONFIRMED, fixed.** compliance.py:204-233: `authenticate(ROLE_AUDITOR, ROLE_MANAGER)` admits a manager at step 2, then 404, then the OPEN check, then the waiver branch's auditor-only 403. Item 2 now carries that exception, including that a manager waiving a resolved finding gets `ERR_FINDING_ALREADY_RESOLVED` and a bad id gets 404.

**R7 CONFIRMED, fixed and worth doing.** `ERR_LOT_NOT_PRICEABLE` is raised at lots.py:153 (markdown), 229 (void), 254 (sales), 284 (withdraw), **405 (apply_label)** and donations.py:162 (manifest line) — item 8's list was missing label application. Added *with* the inversion flagged: there alone the lot-state refusal sits below step 9, matching §3.4's pinned order. Naming it without the caveat would have created a fresh contradiction.

Additional contradictions found and resolved (6): (1) §2.8 line 127 said posture is recomputed when "a shrink event is verified or disputed" — narrowed to the VERIFIED+MANUAL dispute, and resubmission and void added to the "no other call recomputes it" list (verified shrink.py:159-197 call neither recompute). (2) §2.6's two-decimal *input* universal is false for a ladder rung's `discount_pct`: registry.py:206-211 validates only `0 < discount_pct < 100` with no `decimals` gate, while `field_number` gates the other four at 2 dp — narrowed to the four genuinely gated inputs and named `discount_pct` as the exception (`12.345` accepted and stored as given). This one changes a *behavioural* claim, not just prose. (3) §2.11 item 30 omitted the store margin rollup, which runs the same `_check_window` raising `ERR_RECOMMENDATION_WINDOW_INVALID` (departments.py:172-176) — item 30 extended plus the shape-then-path-then-window ordering stated. (4) §2.5's flat-topology universal ("no resource identifier appears nested inside another resource's collection path") contradicted §4's own table (`POST /fresh/lots/{lotId}/markdowns`, `/sales`, `/scan-price-checks`, `POST /fresh/donation-pickups/{pickupId}/assignments`) — scoped to reads with the write nesting made explicit. (5) §1 carried the same claim more broadly — scoped to reads to match. (6) §3.9 step 5 was silent on version bumps, leaving §2.9's universal to imply the nightly run bumps every lot; services.py:262-344 never touches a lot in step 1 or 5 and departments.py:209-213 never touches the department despite the `sweep_epoch` increment — now stated outright.

Final integrity verification: `wc -l` 567; `grep -n '^## '` exactly 5 sections at lines 3/11/215/414/494; `grep -c '^### '` 20 (§2.1–2.11 + §3.1–3.9); `grep -c '^| \`ERR'` exactly 68; §4 endpoint rows 71; `tail -3` ends on complete §5 table rows. Nothing regressed. Cumulative divergence from `PRD_FINALIZED.md` is now **64 changed lines** (was 57). `.scratch/step9p4` was empty and removed; siblings untouched. `worklog.md`, `PRD.md`, `PRD_FINALIZED.md`, `implementation/`, `test_suite/`, `test_helpers/` not modified.

### Orchestrator final verification of Step 9

- `workspace/PRD_COMPLETED.md` exists, 567 lines, and is **not** byte-identical to `PRD_FINALIZED.md` (64 changed lines) — so the scan demonstrably ran, ruling out the known "identical output" failure.
- Integrity confirmed independently: exactly 5 top-level `##` sections, exactly 68 `ERR_` rows in §5, 71 endpoint rows in §4, file ends on a complete table row. No truncation.
- `find workspace/implementation test_suite test_helpers -newer workspace/implementation/results.8.json` returns nothing, confirming **no Step 9 pass modified the implementation or the tests**. The green 8-round sweep (89/89 in all 8 rounds) therefore still describes the delivered artifacts exactly.
- Totals across the four passes: **81 edits** (38 ambiguity-pins, 29 mismatch-revisions, 14 reconciliation edits), touching 64 of 567 lines — an 11.3 % line delta, consistent with a minimal-patch mandate over a document that was already largely faithful.

**Pipeline complete.** Steps 1–9 all finished; `workspace/PRD_COMPLETED.md` is written.
