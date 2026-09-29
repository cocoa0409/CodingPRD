# Worklog — task_2931_self_order_kiosk_digital_menu_board_content_management

## Step 1: Create task directory — 2026-09-05T18:00:21.914Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2931_self_order_kiosk_digital_menu_board_content_management` and its `workspace/` subdirectory. Index 2931 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide on auto-allocation).

## Step 2: Generate Scaffold — 2026-09-05T19:24:42.569716683Z

Subagent summary (verbatim):

Both remaining sections are in and the whole scaffold lints clean.

## Files

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2790 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1693 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3549 |

`SCAFFOLD.yaml` holds only §1.0–§1.7 (top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, constants_global, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles); each design file has exactly one top-level key. `worklog.md` and `workspace/` are untouched; scratch lives in `.scratch/step2/`.

## SCAFFOLD.yaml counts

12 entities · 7 state machines · 2 concurrency rules (OCC) · 9 calculations · 36 ordered validations · 46 endpoints · 36 errors · 7 roles. Profile: `beyond_expert`, entity_topology `graph`, state_machine_shape `cyclic`, role_model `segregation_of_duties`, consistency_model `immediate`, layers [optimistic_concurrency, cascading_side_effects, derived_field_reconciliation, rate_threshold_triggers], api_prefix `/kiosk-ops`.

## Design indexes

- §1.8: 20 instances across all 9 rules (2–3 differentiated instances per rule).
- §1.9: 75 instances across 9 sections — 57 full `test_recipe`s + 18 `excluded_because` stubs: entities 12, state_machines 18, calculations 17, validations 8, endpoints 5, errors 3, rbac 6, complexity_layers 5, consistency_model 1.

Independent cross-checks I ran (script at `.scratch/step2/verify.py`): 95 unique instance names across both files, 0 unresolved `grounds` references, 0 unbound `${var}` placeholders, all 36 error ids caused by at least one instance, no stub carrying a `test_recipe`, every stub's `difficulty_instance` resolving to a real §1.8 name. `bulk_action` is the only guide row deliberately skipped — §1.5 declares no bulk endpoint.

Bugs fixed while finishing: `effective_date_utc`→`effective_from_utc` + missing `justification` on two PriceChangeRequest calls; `health_score`→`rolling_health_score`; `published_version_no`→`bundle_version`; `calculations.required_approvals_for_price_change`→`price_uplift_and_approval_tier`; `PriceZone.active_override_total_cents`→`MenuItem.zone_override_total_cents`; `rbac.*` grounds renamed to the real `roles.*` / `complexity_profile.role_model` keys. Two pre-existing wrong numbers in the corner file were corrected — `worst_case_health_score` had been asserted equal to the base at missed 0, but the formula charges `PROJECTED_MISSES` (2 × 15) unconditionally, so base 80 → 50 and bases 100/50 → 70/20.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    46
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  867

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

One thing for the orchestrator: because the scenario was to be copied verbatim, `SCAFFOLD.yaml`'s `scenario:` key still opens with the line `Generate task harder than expert level!`. That line reaches PRD.md downstream, so strip it from the scenario key before Step 3 (the `difficulty_level: beyond_expert` field already carries the intent).

**Orchestrator action taken on that last point:** stripped the `Generate task harder than expert level!` line (and its trailing blank line) from the `scenario:` block of SCAFFOLD.yaml. SCAFFOLD.yaml is now 2788 lines, re-parses cleanly as YAML with 14 top-level keys, and `grep -c "harder than expert"` returns 0 across all three scaffold files. The difficulty directive therefore cannot reach PRD.md via the scenario key.

## Step 3: Copy shared files — 2026-09-05T19:24:47.499658621Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (53 lines).

## Step 4: Generate PRD — 2026-09-05T19:42:25.41941563Z

Subagent summary (verbatim):

PRD generation for task_2931 is complete.

**Output**: `workspace/PRD.md` — **471 lines**, written in 9 incremental `cat >>` appends (no truncation).

**Final state (verified by `wc -l` + `tail -40`)**
- Final heading: `## 5. Error Code Catalogue` (line 430)
- Final line: `` | `ERR_UPLIFT_CAP_EXCEEDED` | 422 | `` — the last row of the 36-row error table; the file ends at a complete table boundary, not mid-sentence.

**Section list**: 1. Introduction; 2. Global Specifications (2.1 RBAC 7 roles, 2.2 Response Structure, 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties, 2.6 Money/Basis Points/Rounding, 2.7 OCC, 2.8 Addressing/Cluster Inheritance/Path Resolution, 2.9 Cascade Discipline/Derived Store Posture, 2.10 Append-Only Audit Trail, 2.11 Validation Precedence — all 36 checks priority-ordered + 3 conflict-pair outcomes); 3. Business Logic (3.1 Chain Topology, 3.2 Menu Catalogue/Accessibility Copy/Zone Pricing, 3.3 Price Change Approval Cycle, 3.4 Content Bundles: Slot Geometry/Validation Fork/Publication, 3.5 Daypart Resolution & Store Projection, 3.6 Store Inventory/86 List/Suggestion Rules, 3.7 Promotional Campaign Versioning, 3.8 Kiosk Hardware: Heartbeats/Health Bands/Cache/Payment Attestation, 3.9 Order Capture/Pricing/Kitchen Handoff); 4. API Endpoint Definitions (46 rows); 5. Error Code Catalogue (36 rows).

**Hard Contract results (machine-verified)**
- Contract 1 — Field-Name Coverage: PASS. All 166 required identifiers appear verbatim in backticks. One real gap found and fixed during verification: `cache_state` was described only as "content dimension"; §3.8 now names `health_state`, `cache_state` and `payment_compliance_state` explicitly.
- Contract 2 — Rule Coverage: PASS. All 36 error ids have prose trigger conditions before §4. All 7 state machines, 9 calculations, both OCC rules, the 5-link cascades, `applies_to` scopes and sibling-branch symmetry are in prose. §4 method+path set is an exact bijection with the 46 scaffold endpoints; §5 an exact bijection with the 36-entry catalogue, zero status-code mismatches.
- Contract 3 — §3 Path Purity: PASS. Zero backtick tokens in §3 start with `/` or name an HTTP method; `/kiosk-ops` occurs 0 times in §3.

Withheld files were never opened (no read/grep of either design index or any sibling task dir). Leak scan for "beyond_expert", "expert level", "difficulty", "test_recipe" returns nothing.

**Scaffold contradictions resolved (all representable — nothing dropped)**
- Resubmission: `baseline_price_cents`/`uplift_bp`/`required_approvals` are never re-derived; a resubmission may carry a revised `proposed_price_cents`.
- `accessibility_audit_state` enum = {PENDING, PASSED, FAILED}; endpoint mentions of NOT_AUDITED/REQUIRES_REVIEW mapped to PENDING.
- `chain_depth`: root cluster = 1.
- `Store.content_posture`: derivation is authoritative — new store reads OPEN once its chain resolves a published bundle, FROZEN before that.
- `snapshot_item_ids` = items whose `category` is in a slot's `category_codes`.
- Payment-compliance gate scoped to `CARD` only; scaffold silent on MOBILE_WALLET.
- Audit tokens: `DEVICE_ATTESTED` over PAYMENT_ATTESTED; `subject_kind` values from the entity enum (ITEM_AVAILABILITY, CAMPAIGN_VERSION).
- Errors inferred where the scaffold assigned none: ERR_STALE_MENU_ITEM_VERSION, ERR_UNAUTHORIZED_ROLE, ERR_SELF_APPROVAL_FORBIDDEN, ERR_SCREEN_READER_TEXT_MISSING, ERR_BUNDLE_NOT_PUBLISHED.
- `psychological_rounding` has no declared default; prose states a zone created without it applies no psychological rounding (NONE).

**Orchestrator verification of the known truncation failure mode:** independently ran `wc -l -c` (471 lines / 102167 chars), `tail -12`, and a heading dump. The file ends with a complete final error-table row at a real section boundary. Endpoint and error table row counts confirmed. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-05T20:33:11.351065656Z

Subagent summary (verbatim):

All four smoke suites now pass on freshly booted servers and the implementation is final.

## Files (`workspace/implementation/`)

start.sh (exec, 0755) 10 · requirements.txt (`Flask==3.0.3`) 1 · app.py 53 · auth.py 56 · constants.py 61 · errors.py 52 · logical_clock.py 66 · response.py 82 · shapes.py 161 · db.py 89 · serialize.py 85 · calc.py 348 · derive.py 418 · routes/__init__.py 0 · routes/common.py 66 · routes/topology.py 138 · routes/menu.py 85 · routes/pricing.py 235 · routes/bundles.py 275 · routes/availability.py 145 · routes/upsell.py 89 · routes/campaigns.py 136 · routes/devices.py 176 · routes/orders.py 235 · routes/misc.py 124 — **total 3186**

Storage is plain module-level dicts in `db.py`; no SQLite, no file/JSON persistence, no preloaded entity. Verified on a cold boot: all 12 collections return `data: []`, `total_count: 0`, `limit: 10`, `offset: 0`, `has_more: false`, and the clock reads exactly `2026-08-01T00:00:00.000Z`.

## Endpoints: 46 / 46

Programmatic diff of the PRD §4 table against Flask's `url_map` (path params normalised): `missing: []`, `extra: []`. All mounted under `/kiosk-ops` with `strict_slashes = False`.

## PRD section -> module

- §2.1–2.3 base path, envelope, pagination -> `app.py`, `response.py`; §2.5 headers/roles and precedence positions 1–4 -> `auth.py`; §2.11 position 7 shape checks -> `shapes.py`; §2.6/§5 error catalogue -> `errors.py`; §2.4 logical clock -> `logical_clock.py` + `routes/misc.py`; §2.10 audit trail (polymorphic subject, per-subject `sequence_no`) -> `db.py` + `routes/misc.py`.
- §2.7 money/rounding, §2.8 health scoring, §3.2 pricing math, §3.5 daypart resolution -> `calc.py`; §2.9 store posture and every cross-entity cascade (apply chain §3.3, fork-join publication §3.4, availability §3.6, campaign advancement §3.7, device rescoring §3.8) -> `derive.py`; entity field projections -> `serialize.py`.
- §3.1 -> `routes/topology.py`; §3.2 -> `routes/menu.py`; §3.3 -> `routes/pricing.py`; §3.4 -> `routes/bundles.py`; §3.5 + §2.10 + §2.4 -> `routes/misc.py`; §3.6 -> `routes/availability.py` and `routes/upsell.py`; §3.7 -> `routes/campaigns.py`; §3.8 -> `routes/devices.py`; §3.9 -> `routes/orders.py`.

## Smoke test

Four scenario suites, **242 checks, 0 failures**: 58 (port 41931), 42 (43287), 80 (44911), 62 (45613), plus a bare-boot probe on 46337 and a final cold boot on 47159 confirming `0.0.0.0` binding and `200` on `/kiosk-ops/stores`. Every server was started with `PORT=<n> bash start.sh` and killed by its PID file; `ss -ltn` confirms all six ports are free and no server process remains. No broad `pkill` was ever issued.

Three real defects were found and fixed by these runs: manual `EIGHTY_SIX` wrongly required `until_utc` (scaffold marks it `until_utc?`); the clock did not auto-apply `APPROVED` price requests whose `effective_from_utc` had been reached (§3.3: "the system also applies an approved request of its own accord"), now done in `derive.auto_apply_due_requests()`; and the apply cascade is now shared by the manual verb and the clock path so both write the same override, audit row and drift cascade.

## Ambiguities resolved

1. **`APPLY` on an already-`APPLIED` request** — §3.3 says "an attempt on any other state is refused with `ERR_REQUEST_NOT_APPROVED`", but §2.11 position 12 enumerates only `DRAFT`, `PENDING_APPROVAL`, `CHANGES_REQUESTED` and defers to the generic check at position 13. Chose §2.11: `ERR_INVALID_STATE_TRANSITION` (409). `APPLIED` is not terminal (rollback is declared out of it), so position 11 does not apply.
2. **Auto-apply is not a reported counter** — the clock response declares exactly three counters, so a clock-driven apply is invisible in the response body and observable only on the request row.
3. **Menu-board attestation** — `pin_pad_firmware_version` is a required input of the endpoint (§3.8), so shape validation (position 7) fires before device-kind support (position 27); omitting it on a `MENU_BOARD` yields `ERR_INVALID_REQUEST`, not `ERR_DEVICE_KIND_NOT_SUPPORTED`.
4. **Attestation audit token** — PRD emits `DEVICE_ATTESTED`; the scaffold's endpoint note says `PAYMENT_ATTESTED`. Followed the PRD's action-token list.
5. **Projection `items[]` element shape** is unspecified; emits `menu_item_id`, `sku`, `display_name`, `category`, `board_display_price_cents`, `availability_state`.
6. **`audit_result` token** — accepts `PASS`/`PASSED`/`true`; anything else is treated as a failed audit.
7. Unresolvable `device_id` on the projection query is ignored rather than 404; `devices_rescored` counts every device, not only those whose band moved; minute 1439 can never be covered by a slot (`end_minute_of_day` is exclusive), so a projection there legitimately falls back to `STATIC_FALLBACK`/`FALLBACK`; a `MANUAL_86` is never lapsed by the clock; a non-requesting analyst's `SUBMIT`/`WITHDRAW` returns `ERR_UNAUTHORIZED_ROLE` (403) since the catalogue has no requester-identity error; a bundle published on a cluster whose stores all live in child clusters gets an empty `price_snapshot`.

## Step 5: Generate Unit Tests — 2026-09-05T20:43:26.728235850Z

Subagent summary (verbatim):

All work is complete. Final verification pass results below.

## Deliverables

`test_helpers/` (task root, 9 files, 1,574 lines): `__init__.py` 1 · `types.py` 8 · `api_errors.py` 81 · `test_users.py` 87 · `assertions.py` 216 · `api_client.py` 257 · `fixtures.py` 288 · `constants.py` 310 · `factories.py` 326

`test_suite/` (task root, 17 files, 4,456 lines / tests): `conftest.py` 12 · `test_01_board_price_versus_charge_price_and_health_scores.py` 184/4 · `test_02_per_line_rounding_and_pinned_uplift_order.py` 182/4 · `test_03_approval_cycle_and_bundle_fork_join.py` 154/4 · `test_04_price_and_availability_cascades.py` 224/4 · `test_05_validation_precedence_pairs.py` 216/6 · `test_06_boundary_precision.py` 205/6 · `test_07_cross_entity_state_gates.py` 183/4 · `test_08_temporal_overlap.py` 186/4 · `test_09_compensating_invariants.py` 220/4 · `test_10_corner_entities.py` 413/12 · `test_11_corner_state_machines.py` 405/10 · `test_12_corner_calculations.py` 489/10 · `test_13_corner_validations.py` 342/7 · `test_14_corner_endpoints_and_errors.py` 424/8 · `test_15_corner_rbac.py` 311/6 · `test_16_corner_complexity_and_consistency.py` 306/4

Neither directory exists anywhere under `workspace/`. Only `.scratch/step5/` was used for scratch; `worklog.md`, `workspace/PRD.md`, `workspace/INSTRUCTION.md` and the three SCAFFOLD files are untouched.

## Coverage

**97 tests, 77 distinct design instances, zero skipped, zero untagged, zero dual-tagged.** Automated audit (AST walk over every `test_*` function) confirms: first docstring line is always a `PRD: "…"` verbatim citation, last line is always exactly one `Design:` tag, and every tag's instance name resolves to a real `name:` in the corresponding yaml.

- Queue A (§1.8 difficulty): 20 / 20 instances -> 40 tests (2 each), spanning all 9 rules: `boundary_precision_check` 3, `priority_pair_validation_conflict` 3, `combinatorial_formula` 2, `compensating_invariant` 2, `cross_entity_state_dependency` 2, `dual_variant_calc` 2, `non_linear_state_machine` 2, `resource_temporal_overlap` 2, `transitive_cascade` 2.
- Queue B (§1.9 corner): 57 / 57 non-stub instances -> 57 tests (1 each): entities 12, state_machines 10, calculations 10, validations 7, rbac 6, endpoints 5, errors 3, complexity_layers 3, consistency_model 1. The yaml holds 75 instances; the 18 carrying `excluded_because:` are stubs deferred to §1.8 and are excluded by design, not by the PRD-first filter.

**Skipped by the PRD-first filter: none.** `pytest --collect-only -q` collects exactly 97 tests; every file compiles and passes an unused-import check.

## Design-index corrections applied (index contradicted the PRD; assertion re-derived from PRD text, instance shape preserved)

- PlatformAdmin attestation — index expected `PlatformAdmin` attesting -> 403, but PRD §4 and line 357 authorise `ComplianceOfficer` **or** `PlatformAdmin`. Used `ContentManager` as the refused peer role.
- Untouched device health — index expected ONLINE/100; PRD makes a device with null `last_heartbeat_utc` `OFFLINE` with base score 0. Asserted 0 / `OFFLINE` / null beat.
- Apply with a future effective date — PRD line 241 refuses that with `ERR_EFFECTIVE_DATE_IN_PAST`, so the verb-partition test uses `CLOCK_T0` as the effective instant.
- Carried forward from earlier files: first bundle version 1; root `chain_depth` 1 (deepest 5); second store reads `FROZEN` until its chain resolves a PUBLISHED bundle; technical validation does enforce accessibility, so the validate/publish cascade is re-ordered; low-stock rollup is `LIMITED`; `tier` REGION/CHAIN/NATIONAL -> `STANDARD`; audit tokens `PRICE_OVERRIDE_APPLIED`, `PRICE_REQUEST_APPROVAL_RECORDED` then `PRICE_REQUEST_APPROVED`; priced-line field `gross_line_cents`; new bundle `accessibility_audit_state` is `PENDING`.
- One field the index implied does not exist in the PRD (`captured_at_utc` on an order handoff); the immediacy assertion uses the PRD-declared `created_at` plus `receipt_hash`, `pinned_bundle_version` and `daypart_code`.

Fixture discipline was held throughout: money is always JSON integer cents, instants always full ISO-8601 with sub-second canonicalisation centralised in `api_client.canonical_instant`, blank headers sent as `""` (never spaces), distinct `X-User-ID` per owner (`u_analyst_1` vs `u_approver_1`/`u_approver_2` drives the self-approval and dual-approval tests), a single unwrap layer, and every enum defined once in `constants.py`.

## Step 7: Run Tests and Iterate — 2026-09-05T21:04:43.560933590Z

Subagent summary (verbatim):

All 8 rounds pass 97/97 with the full 97-test suite intact (no tests deleted).

## Summary

**Iterations run:** 2 (iteration 1: 91/97 in all 8 rounds, 6 stable failures identical in every round — no flakiness anywhere; iteration 2: clean).

**Tests deleted:** none. Every failing test was PRD-covered and uniquely derivable at STEP 1; all six resolved at STEP 2/STEP 3.

**Fixes applied to `test_suite/`:**
- `test_11_corner_state_machines.py` — `test_submitting_a_draft_request_opens_the_approval_queue`: asserted `pinned_menu_item_version == item_version` (the version read *before* the create). PRD §3.3: "A successful creation increments the item's `version` by 1 ... pins `pinned_menu_item_version` to the item's **new** version" -> `item_version + 1`.
- same file — `test_the_three_device_dimensions_move_one_at_a_time`: expected `DEGRADED` posture for a store whose only kiosk is `ONLINE`/`COMPLIANT` with a `MISSING` cache. PRD §2.9 names a **stale** cache in both the degraded test and the `OPEN` clause; `MISSING` is a distinct enum member, so `OPEN` is the uniquely derivable answer. Changed to `POSTURE_OPEN`.
- `test_07_cross_entity_state_gates.py` — `test_the_freeze_is_audited_by_the_system_and_costs_no_order_number`: demanded exactly 1 `STORE_CONTENT_FROZEN` row. The fixture crosses into `FROZEN` twice, both PRD-mandated: registering the store's first KIOSK (which starts `OFFLINE`, and "Registration also re-derives the owning store's `content_posture`") and later the clock quarantining it. Raised to `count=2` and asserted both rows are system-attributed.
- `test_16_corner_complexity_and_consistency.py` — `test_quarantine_bites_at_the_third_miss_and_the_next_beat_clears_it`: expected `worst_case_health_score == 100` right after a heartbeat. PRD §3.8 says the worst-case score "charges **two additional** hypothetical misses" unconditionally -> 100 - 2x15 = 70. (Aligns it with `test_rolling_and_worst_case_scores_disagree_on_one_device_row`, already passing on the same reading.)
- `test_09_compensating_invariants.py` — `test_rolling_back_refreshes_the_cascade_without_erasing_the_audit_trail`: read the projection item's board price under the invented key `board_price_cents` (a minority spelling; `test_01` used `price_cents`). Aligned to `price_cents`.

**Fixes applied to `test_helpers/`:** none needed — no shared-fixture failure cluster appeared.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/misc.py`, `menu_projection` — renamed the projection item's board price key from `board_display_price_cents` to `price_cents`. PRD §3.5 says the item carries "its board display price read out of that bundle's frozen `price_snapshot`", and `price_cents` is the only key PRD declares for those snapshot entries, so it is the PRD-anchored spelling. No field was added or removed.

**Final sweep evidence:** rounds 1–8 all `97 / 97`.

**Orchestrator verification (independent of the subagent's claim):** read all 8 `results.$i.json` directly — each reports `passed=97, total=97, failed=0, errors=0`, all written at 20:54:44Z, with `workspace/SWEEP_DONE` bearing the same timestamp. The sweep artifacts exist and match the reported outcome.

## Step 8: Finalize PRD — 2026-09-05T21:15:13.58952884Z

Subagent summary (verbatim):

`PRD_FINALIZED.md` is written. Four lines touched, three subjects pinned; two of the five Step 7 sites needed no PRD change.

**Line counts:** PRD.md 471 lines / 102,167 chars -> PRD_FINALIZED.md 471 lines / 104,225 chars. 4 lines revised (0.85% of lines), +2.01% characters. No sections added or removed.

**Changes**

- §2.9 clause 1 — revise — pinned when the `STORE_CONTENT_FROZEN` audit row is emitted: on **every** re-derivation that moves the posture into `FROZEN` from a non-`FROZEN` posture (so repeat freezes each get a row, and a re-derivation finding it already `FROZEN` appends nothing), and **not** at store creation, whose initial derivation is part of the create — no audit row and no move off `version` 1. — `derive.py:202-212`, `routes/topology.py:122`.
- §2.9 clause 2 — revise — pinned "stale content cache" to `cache_state` of exactly `STALE`; a `MISSING` cache (never pulled a bundle) does not degrade the store, with a pointer that the §2.11 operability gate still refuses that device an order. — `derive.py:185`, `routes/orders.py:85`.
- §2.9 clause 3 — revise — the `OPEN` clause reworded symmetrically ("no device whose `cache_state` is `STALE`"). — `derive.py:184-190`.
- §3.5 stage four — revise — pinned the projection `items[]` element shape: one object per resolvable `snapshot_item_ids` entry in that order, exactly six keys (`menu_item_id`, `sku`, `display_name`, `category`, `price_cents`, `availability_state`); `price_cents` taken verbatim from the frozen `price_snapshot` entry matching the item and the store's own zone and null when absent; `availability_state` from the row at this store, `UNAVAILABLE` when there is none; array empty when the chain resolves no published bundle. — `routes/misc.py:57-78`.

**No-change decisions (Step 7 sites that were pure test-artifact bugs):**
- §3.3 `pinned_menu_item_version` — PRD already says "the item's **new** version"; `routes/pricing.py:51,66` does `touch(item)` then pins the post-increment version. Verbatim kept.
- §3.8 `worst_case_health_score` — PRD already says "charges **two additional** hypothetical misses" unconditionally; `calc.py:244` adds `PROJECTED_MISSES` with no guard. Verbatim kept.

**Pre-edit search log**

1. *Audit-row emission on entry to `FROZEN`.* Subject: who appends `STORE_CONTENT_FROZEN` and on which transitions. Enumerated/read: `derive.recompute_store` (sole emitter, guarded by `posture == "FROZEN" and was != "FROZEN"`), and every caller found by `grep -rn "recompute_store"` — `routes/topology.py:122` (create, `audit=False`), `topology.py:137` (single-store GET, audits), `routes/devices.py:66,108,149,175`, `routes/orders.py:168,211,232`, `derive.reconcile():225`. Also checked `routes/common.py:listing` to confirm the list endpoint does not re-derive. Adjustment: first draft attributed the row to "a plain read of the store"; narrowed to "a read of that single store" so the sentence does not imply `GET /stores` re-derives, and kept the trigger list generic since nine distinct callsites can fire it.
2. *`MISSING` vs `STALE`.* Subject: which `cache_state` values affect posture. Enumerated/read via `grep -rn "cache_state"`: `derive.cache_state_of` (sole producer of MISSING/FRESH/STALE), `derive.recompute_device_cache`, `derive.store_posture:185` (tests `== "STALE"` only), `routes/devices.py:57` (registration default `MISSING`), `routes/devices.py:138`, `routes/orders.py:85` (capture gate rejects `MISSING`), `serialize.py:40`. Adjustment: scoped the exclusion to "for the purposes of this test" and added the explicit cross-reference to the §2.11 operability gate, so the new sentence cannot be read as making a `MISSING` cache harmless everywhere.
3. *`OPEN` clause rewording.* Enumerated: `derive.store_posture:180-190` in full, confirming the `OPEN` fall-through requires no `STALE` cache, no `DEGRADED` band, no kiosk in the three payment bands, and (when kiosks exist) one kiosk not `OFFLINE`/`QUARANTINED`. Adjustment: none — only the cache clause was made explicit.
4. *Projection `items[]` element shape.* Enumerated/read: `routes/misc.py:57-78` (sole producer), `routes/bundles.py:155-168` `_freeze_price_snapshot` (snapshot entries hold `menu_item_id`/`price_zone_id`/`price_cents`, matching the key PRD §3.4 already declares), `derive.live_price_checksum:78-86`, `calc.availability_row`, `calc.resolved_bundle_for_store` / `published_bundle_of_cluster` (the resolved bundle may belong to an *ancestor* cluster, whose snapshot need not contain the store's own zone). Adjustment: because of that ancestor-bundle path added "null when the frozen snapshot holds no entry for that pair" rather than asserting a price is always present, added the skip for `snapshot_item_ids` entries whose item no longer resolves, and added the empty-array case for a store with no published bundle on its chain — all three are real branches in `misc.py`.

## Step 9: Complete PRD — 2026-09-05T22:04:59.240551387Z

Orchestrator decision (recorded per the autonomy directive): Step 9 was run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` rather than a single subagent. A 3,186-line / 25-module implementation reliably under-scans in one pass, and the known failure mode is a PRD_COMPLETED.md byte-identical to its source. Pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from copying so they could not wipe their predecessors. Partition: pass 1 = infra (app/auth/response/shapes/errors/constants/db/serialize/logical_clock) + routes common/topology/menu/pricing; pass 2 = calc.py + routes bundles/availability/upsell/campaigns; pass 3 = derive.py + routes devices/orders/misc, plus a whole-document contradiction reconciliation as the final pass.

### Pass 1 summary (verbatim)

PRD_FINALIZED.md 471 lines / 104,225 chars -> PRD_COMPLETED.md 471 lines / 113,296 chars (+9,071 chars, 0 lines — every edit in-paragraph). 28 changes over 27 lines — **24 ambiguity-pins, 4 mismatch-revisions**. Highlights: §2.1 whitespace-only headers count as blank and both header values are trimmed (`auth.py:19-26`); §2.2 `api_request_id` is `req_` + 20 uppercase-alnum chars and `api_request_timestamp` reads the logical clock (`response.py:18-26`); §2.3 bad/out-of-range `limit`/`offset` -> `ERR_INVALID_REQUEST` 400, `total_count` post-filter/pre-page, filters are exact case-sensitive matches, unknown query params ignored, no list endpoint re-derives (`response.py:42-82`, `routes/common.py:25-39`); §2.4 client instants accept `Z`/offset/naive/bare date and persisted instants are re-rendered canonically (`logical_clock.py:25-52`); §2.8 the cluster cycle branch is unreachable, only the five-cluster length check fires (`routes/topology.py:67-69`); §2.9 **mismatch** — the posture trigger list was incomplete (accessibility rewrite and availability cascades also re-derive) and re-derivation never re-scores device health/payment; §2.11 pos 7 absent/unparseable body treated as `{}` and integer fields reject booleans/fractions (`shapes.py`); §2.11 pos 9 **mismatch** — the apply's `pinned_menu_item_version` check runs after effectivity (28) and before approval count (35); §2.11 pos 17 **mismatch** — the "not already in `approval_user_ids`" half guards `APPROVE` only; §3.1/§3.2 single reads re-derive and may bump `version` while creation stays at 1; §3.2 **mismatch** — `contrast_ratio` accepts any number in 0–21, one-decimal precision is not enforced; §3.3 negative uplift ties round away from zero, per-verb role narrowing at position 2, `PlatformAdmin` exempt from the requester check, revised proposal never re-tested against `max_uplift_bp`, any `PricingAnalyst` may apply, stale-override rollback refusal is `ERR_INVALID_STATE_TRANSITION` 409; §4 trailing slash tolerated, unknown path and undeclared method both -> `ERR_RESOURCE_NOT_FOUND` 404, routing precedes authentication. `errors.py` status table verified identical to §5 (all 36 ids) — no change needed.

### Pass 2 summary (verbatim)

Before 471 / 113,296 -> after 471 / **123,253** (+9,957 chars). **3 mismatch-revisions, 28 ambiguity-pins** across 27 paragraphs. Pass 1's 28 edits verified still present (line-for-line diff: 54 differing lines, 27 pass 1's, 27 pass 2's). Highlights: §2.11 pos 29 **mismatch** — drafting tests `end <= now`, scheduling strictly `end < now`; §3.3 `round_half_up` is half-away-from-zero (-250.5 -> -251); §3.4 bundle-creation defaults (`bundle_version` highest+1, DRAFT, PENDING audit, empty arrays, checksums 0), slot bounds (codes 1–24 chars, minutes 0–1439, `category_codes` defaults `[]`), appends only in DRAFT/VALIDATED with a ROLLED_BACK bundle reporting `ERR_INVALID_STATE_TRANSITION`, `validation_findings` ordering pinned, `ACCESSIBILITY_AUDIT` only from DRAFT/VALIDATED with `audit_result` accepting a boolean or trimmed/upper PASS/PASSED, publication supersedes every PUBLISHED sibling oldest-first with operator attribution; §3.4 **mismatch** — staleness tests any *currently* SUSPENDED rule of the cluster, so a bundle published while one is suspended is drifted immediately; §3.5 first-seen-daypart shadowing applies within one bundle too, local minute of day = hour×60+minute with seconds discarded plus offset mod 1440, candidacy half-open, fallback triple (null/STATIC_FALLBACK/FALLBACK), ranking narrowest -> earliest start -> creation -> insertion, TRANSITIONING at `end - buffer_minutes`; §3.6 attach derives stock fields at creation and runs the reconcile tail but fires no auto-86, `reserved_units` on SYNC_ON_HAND defaults to the stored value not 0; §3.6 **mismatch** — auto-86 fires on any sync leaving the sellable count <= 0 while `listing_state` is LISTED (not a LOW->DEPLETED transition), and an already-EIGHTY_SIXED row runs links 2–5 only; §3.6 auto-86 audit is operator-attributed, a single read releases an elapsed AUTO_86 hold with a system-attributed `ITEM_AUTO_86_LAPSED`, DISCONTINUE clears `eighty_six_state` to NONE but leaves `eighty_six_until_utc`/`eighty_six_reason`, an upsell rule has no action endpoint and no read-time re-derivation; suggestion selection pinned end to end (cap 2 with a working screen reader else 3); §3.7 scheduling needs `published_bundle_version` >= 1, window-end test after the stacking-conflict loop, supersession spans clusters, clock literals and expiry-before-activation, campaign tie-break by `priority_rank` then larger `discount_value` then creation then insertion; §3.8 missed count = whole minutes since `last_heartbeat_utc` / 5 truncated with elapsed minutes floored at 0 (a backwards clock reads 0), 15 points per miss capped 60, worst case charges two extra misses. All four pass-1 deferrals addressed; no pass-1 edit needed correcting.

### Pass 3 summary (verbatim)

Before 471 / 123,253 -> **after 471 / 134,174** (+10,921 chars). **14 ambiguity-pins, 9 mismatch-revisions** over 23 locations (35 Edit calls; three of them fixed pass 3's own first wording where it was a false universal or added a new paragraph). Highlights: §2.4 the five-stage clock order pinned (auto-apply due price requests -> per-device rescore incl. payment band in creation order -> release holds -> advance campaigns -> shared tail), exactly three counters, `devices_rescored` counts every device visited, auto-applied price changes reported by no counter; §2.9 **mismatch** — the shared tail is **four** sweeps, the cluster sweep sits between devices and stores; §2.9 `STORE_CONTENT_FROZEN` carries the single literal `NO_PUBLISHED_CONTENT_OR_ALL_KIOSKS_DOWN` with `actor_role` `system` and null user; §2.10 audit listing ordered by `sequence_no` ascending, stable tie-break, after filters and before the page window; §2.11 pos 11 the `action` enum is shape-checked before terminality while single-verb body fields are checked after, with the price-change endpoint the sole exception; §2.11 pos 14 **mismatch** — a store projection cannot raise `ERR_BUNDLE_NOT_PUBLISHED`; §3.3 link 3 **mismatch** — an apply landing on the price already charged leaves `stale_flag` false and does not touch the bundle; §3.3 the clock skips an APPROVED request whose item `version` drifted off `pinned_menu_item_version` or whose approvals fall short; §3.5 `at_minute_of_day` trimmed and must be a whole integer 0–1439; §3.5 the projection's six item keys, unknown `device_id` ignored, `cart_item_ids` repeatable/comma-splittable/trimmed/deduped with each id a quantity-1 line, eleven top-level keys, no re-derivation; §3.6 link 4 **mismatch** — an already-drifted PUBLISHED bundle is not re-versioned by a further suspension; §3.8 registration checks the `StoreOperator` scope against the **body** `store_id` before resolution and both health scores start at 0; `DEVICE_QUARANTINED` carries `WORST_CASE_HEALTH_BELOW_THRESHOLD` on entry only, never by a heartbeat; §3.8 **mismatch** — a device read recomputes health scores/band and payment band but leaves the content dimension and does not re-derive store posture (the §4 table row was corrected too); §3.8 **mismatch** — cache-pull gate order is publication -> capacity -> kiosk accessibility certification, flush releases offline orders oldest-first raising `version` by exactly 1; §3.8 attestation emits a second `DEVICE_NON_COMPLIANT` row when the band lands non-compliant; §3.9 the publication gate bites only a device that actually holds a cached bundle, gates judge stored values with no rescore, `unit_price_cents` recomputed from **live** item data rather than the snapshot, `AMOUNT_OFF` capped at its own line, rounding once per line; the `receipt_hash` canonical string and field order, `pinned_bundle_version` from `cached_bundle_version`, `daypart_code` null on static fallback; kitchen ack moves both dimensions in one request leaving `open_order_count` unchanged; §3.9 void **mismatch** — the void returns the row's stock numbers but not its listing, so an auto-86 the capture itself fired is not reinstated.

Whole-document consistency read (final pass): 7 contradictions found and reconciled toward `implementation/` — (1) §2.3 + §4 claimed a device read recomputes all three dimensions; (2) §2.11 pos 14's projection error; (3) §3.3 link 3 and §3.6 link 4's unconditional `stale_flag`/version bump, both qualified to "only where the value actually moved"; (4) §3.8's cache-pull gate order vs §2.11 positions 26/30; (5) §3.9's void claiming an exact pre-capture restore; (6) pass 3's own "the one field of this API" false universal, generalised once in §2.11 pos 11; (7) §2.3 omitting the auto-86 lapse an availability read performs. Verified already-consistent: clock stage order and counters vs §4, audit sort/filter/pagination order, store-read vs store-creation posture handling, the four `version`-1-on-creation exemptions, §2.5's "row that changed" qualifier, all §4 role columns vs every `auth.enter` call, and the monotonic §2.11 position ordering of the capture chain (14->15->16->18->26->31->33->34) and cache-sync chain (14->26->30).

### Orchestrator verification

`PRD_COMPLETED.md` is 471 lines / 134,174 chars, is **not** byte-identical to `PRD_FINALIZED.md` (146 differing diff lines across the three passes), and ends at the final row of the §5 error table. `find` confirms no file under `implementation/`, `test_suite/`, or `test_helpers/` was modified after the passing sweep at 20:54:44Z, so the 8× 97/97 result stands for the shipped code. No stray `test_suite/`/`test_helpers/` under `workspace/`; exactly one `worklog.md` in the task tree.

**Pipeline complete.**
