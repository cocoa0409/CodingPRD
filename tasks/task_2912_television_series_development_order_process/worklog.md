## Step 1: Create task directory — 2026-09-05T15:51:22.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2912_television_series_development_order_process and workspace/ (pre-assigned index 2912, no auto-allocation).

## Step 2: Generate scaffold — 2026-09-05T17:36:54.000Z

All three scaffold artifacts are complete and the linter is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2912_television_series_development_order_process/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2912_television_series_development_order_process/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2912_television_series_development_order_process/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     78
  Calls scanned (§1.8+§1.9):  1309

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

- **SCAFFOLD.yaml** (3092 lines) — 13 entities, 9 state machines, 2 concurrency rules, 8 calculations, 47 ordered validations, 49 endpoints, 55 error codes, 7 roles. Top-level keys only: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — no `scaffold_*_design` keys. Profile: `multi_party_negotiation` / `quota_allocation`, graph topology, cyclic state machines, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_deferred_actions`, `role_model: segregation_of_duties`, `consistency_model: immediate`.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1721 lines) — single key `scaffold_difficulty_design`; 9 rule_ids × 2 = **18 instances**.
- **SCAFFOLD_CORNER_DESIGN.yaml** (5071 lines) — single key `scaffold_corner_design`; **96 instances (78 real + 18 `excluded_because` stubs)** across all nine guide sections: entities 13, state_machines 18, calculations 10, validations 11, endpoints 7, errors 19, rbac 8, cross-cutting complexity layers 8, consistency model 2.

## Verification performed beyond the linter

- **Error coverage**: all 55 §1.6 error ids are triggered by at least one instance (0 uncovered).
- **Endpoint coverage**: all 49 §1.5 endpoints appear as an actual `call:` (0 never called) — closed the last 8 GET-only gaps with two new endpoints-section instances.
- **Grounds resolvability**: every `grounds[*]` entry in both design files resolves to a declared §1.1–§1.7 element (0 dangling). Fixed 9 dangling refs, e.g. a non-existent `ContingencyClearance` entity, `constants.*` names that are only inlined in prose (`MAX_NOTES_ROUNDS`, `MIN_TEST_PANEL_SIZE`, `RIGHTS_QUIET_BUFFER_DAYS`, `MAX_OPEN_STEPS_PER_WRITER`, `HANDLING_FEE_TIERS`), and `entities.DevelopmentProject.fields.version` (version is an implicit system field, not declared in §1.1).
- **Placeholder closure**: 0 unbound `${var}` across payloads, `as_user_id`, path templates, asserts and setup prose.
- **Names**: unique across the union of both design files; all 18 stub `difficulty_instance` refs resolve by name; stubs carry name + claim_type + grounds + excluded_because and no test_recipe.
- **Banned vocabulary**: removed the one "simultaneously" occurrence (instance renamed to `a_third_open_step_for_one_writer_exceeds_the_step_load`).

## Scaffold defects found and fixed while authoring §1.9

1. `response_envelope` never said where pagination fields live → added `pagination_placement` prose (meta.limit/offset/total_count/has_more).
2. Option-period boundary contradicted itself: validation priority 30 said "on or after" (permits equality) while the DealStep precondition said `now < option_expires_at` and the error condition said "strictly before". Aligned all three on the half-open window; a new instance pins the boundary (refused at exactly `option_expires_at`, accepted one second earlier).
3. TestScreening listed CERTIFIED as terminal while the fielding side-effect invalidates CERTIFIED screenings → the transition note now states CERTIFIED is terminal for every client-driven write, with system supersession as its only exit.

## Notes for the orchestrator

- The `scenario:` key contains the description **verbatim**, including the leading "Generate task harder than expert level!" line as instructed — strip that line before Step 3 if the usual leak-prevention step applies.
- No sibling task directory was read; `worklog.md` was not touched; the task-scoped scratch dir was removed and `workspace/` is empty.

**Orchestrator post-step action:** stripped the "Generate task harder than expert level!" difficulty-directive line (and its blank line) from `SCAFFOLD.yaml`'s `scenario:` block so it cannot reach PRD.md. Verified 0 remaining occurrences of the directive anywhere in the task dir, and re-validated all three YAML files parse with the expected top-level keys.

## Step 3: Copy shared files — 2026-09-05T17:36:58.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T17:50:05.000Z

The PRD is complete and verified.

**Deliverable:** `workspace/PRD.md` — **452 lines**

**Section list (16 sections):** §1 Introduction; §2 Global Specifications & System-Wide Principles (2.1 Identity, Roles and the Separation of Duties; 2.2 API Response Structure (verbatim fixed block, both success and error formats); 2.3 Pagination and List Ordering; 2.4 The Logical Development Clock; 2.5 Common Resource Properties; 2.6 Path Resolution and Referential Integrity; 2.7 Money, Basis Points and Rounding; 2.8 Slate Ledgers: Development Dollars and Episode Inventory; 2.9 Stale-Read Protection on Filed Requests; 2.10 Cascades and Cross-Aggregate Consistency; 2.11 The Order in Which a Request Is Refused (all 47 rules, priority-ordered)); §3 Business Logic & Workflows (3.1 The Standing Registry: Slates, Agencies and Writers; 3.2 Pitch Intake: Coverage, Clearance and Advancement; 3.3 Holding Deals and Writer Exclusivity; 3.4 Step Deals: the Guaranteed Floor, the Option Ladder and the Notes Cycle; 3.5 Pilot Orders and the Two Contingency Dimensions; 3.6 Testing and Research on a Wrapped Pilot; 3.7 Series-Order Negotiation with the Studio; 3.8 Feasibility Economics and the Greenlight Fork-Join; 3.9 Abandonment, Write-Offs and Turnaround Rights); §4 Endpoint Definitions (49-row, 4-column table); §5 Error Code Catalogue (55-row, 2-column table).

**Tail check:** `tail -30` ends on the final row of the §5 table, `| ERR_FEASIBILITY_FAILED | 422 |` — a complete table row closing a complete section. No mid-sentence truncation, no audit footer, no trailing prose.

**Hard Contract reports**

Contract 1 — Field-Name Coverage: **PASS** — `entities[].fields`: 120 required / 120 present / 0 missing; `endpoints[].request_body`: 67/67/0; `endpoints[].query_params`: 15/15/0; computed/response-only fields (`per_episode_cost_cents`, `tier_factor_bps`, `license_fee_final_cents`, `deficit_per_episode_cents`, `total_deficit_cents`, `verdict`, `current_utc`, `basis`, `episode_count`): 9/9/0; all 55 `errors[].id` present.

Contract 2 — Rule Coverage: **PASS** across all eight sub-categories (state machines with every transition and guard; all 7 calculations reconstructible step-for-step including pinned rounding order and the provisional-deficit tier order; both concurrency rules with their 412 codes; all 47 validations in priority order; every cascade link; every computed field's derivation; role/permission matrix; window and expiry boundaries stated as strict/inclusive). Four hardening edits were applied after the first walk: explicit `project_cumulative_dev_cost` formula in §2.8, "required, never optional" wording for both `expected_*_version` fields in §2.9, and the pre-abandonment zero/null baseline for the write-off fields in §3.9.

Contract 3 — §3 Path Purity: **PASS** — 849 backtick tokens scanned in §3; 0 begin with `/`, 0 are bare HTTP-method tokens, 0 are method+path pairs.

**Scaffold contradictions resolved** (each written as one unambiguous reading): rights-clear gate follows the two-source majority (most recent `RightsCheck` by `created_at` must be `CLEAR`, so a later filing supersedes an earlier one); `RightsCheck.result` is fixed at filing and never re-derived by the clock, while `term_state`, `exclusivity_status`, `turnaround_window_open` and holdback blocking are all clock-derived reads; the turnaround window is strictly before the instant 180 days after `turnaround_offered_at`; and the `FAILED`-contingency path keeps both the production-status gate and the dimension-still-`PENDING` gate rather than collapsing them.

Constraints honoured: neither design yaml was opened, grepped or referenced; no sibling task directory and no `worklog.md` was read or written; scratch confined to `workspace/.scratch2912-prd/`; no `pkill` run.

**Orchestrator verification:** independently confirmed 452 lines, tail ends at the final `ERR_FEASIBILITY_FAILED` table row (real section boundary, not truncated), all 5 top-level sections + 20 subsections present, and 0 occurrences of the difficulty directive / "scaffold" / "test_recipe" in PRD.md. Removed the generator's scratch dir.

## Step 5: Generate unit tests — 2026-09-05T19:08:28.000Z

Stage 2 is complete. Final state of the generation:

## Coverage — 114 tests, every non-stub design instance translated exactly once

An AST audit over `test_suite/` extracted the `Design:` line from every test docstring and diffed it against both design indices:

- **Dangling tags: 0.** **Missing instances: 0.** **Untagged/dual-tagged tests: 0.**
- **Queue A (Difficulty):** 18/18 instances → 36 tests (`test_01`–`test_09`), 2 tests per instance.
- **Queue B (Corner):** 78/78 non-stub instances → 78 tests (`test_10`–`test_18`): entities 13, state_machines 14, calculations 5, validations 6, endpoints 7, errors 19, rbac 8, cross-cutting complexity layers 4, consistency model 2.
- **Skipped: only the 18 `excluded_because` stubs** (4 state_machines, 5 calculations, 5 validations, 4 cross-cutting) — each one the design itself marks as already covered by a named queue-A instance, so translating them would have duplicated an existing test. No instance was skipped for a PRD-coverage failure, and no placeholder/xfail was emitted.
- `pytest --collect-only` collects all 114 with no import errors or name collisions; every module passes `py_compile` and has zero unused imports.

## Work completed this session

- `test_suite/test_15_errors.py` finished (613 lines, 19 tests) — added the greenlight-state, committee-already-decided, closed turnaround window, episode-capacity, `ERR_FEASIBILITY_FAILED` (finance-approval-only re-evaluation, with the INFEASIBLE projection 35737500/9000/30000000/5737500/57375000 read back and the FINANCE `REJECTED` vote then accepted), and negotiation/project mismatch cases.
- `test_suite/test_16_rbac.py` (343 lines, 8 tests) — 401 with no headers and with `""` headers; the 403s that outrank path resolution (ResearchAnalyst ordering a pilot, PlatformAdmin reading feasibility, FinanceController voting CREATIVE); `ERR_AGENCY_SCOPE_VIOLATION`; the `WAIVED`-only split on contingencies; `ERR_SEGREGATION_OF_DUTIES` on both a second and a third committee; and the all-seven-roles greenlit walk ending in `SERIES_ORDERED` with three distinct deciders.
- `test_suite/test_17_concurrency_layers.py` (302 lines, 4 tests) — both 412 guards (each followed by the same body at the current parent version being accepted, and only then the supersession/invalidation landing), the project version ladder (+1 across the wrap cascade, unchanged across repeated reads, `updated_at` = the clock at the last write), and the one-second option window (`2026-09-29T23:59:59Z` exercises, `2026-09-30T00:00:00.000Z` is `ERR_OPTION_PERIOD_EXPIRED`).
- `test_suite/test_18_consistency_model.py` (129 lines, 2 tests) — the advance response is the created project and the immediate re-read is field-for-field identical; the third approving vote's own 200 already carries `APPROVED`/`decided_at`, with project, deal and both slate ledgers settled in the same instant and stable on repeat.

## Fixes and judgement calls

- The one-second option-expiry claim could not be tested by rewinding the clock, so it is tested with two identical ladders built at `2026-08-01` and exercised in clock order (23:59:59 first, then the expiry instant) — no backwards clock move.
- Ran a verbatim-citation pass over all 18 modules (normalising em dashes, arrows, section marks): every quoted fragment matches `workspace/PRD.md`, differing only where a quote is truncated and closed with a period.
- Reworded one `test_10` docstring that opened with a quoted literal, producing a 4-quote-prefixed docstring.
- Zero occurrences of "scaffold" anywhere in `test_helpers/` or `test_suite/`.

## Path discipline

`ls -d` confirms `test_helpers/` and `test_suite/` at the task root; `ls -a workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation/`, and a recursive `find` shows no test directory anywhere under `workspace/`. The `workspace/.scratch2912-tests/` scratch dir and all `__pycache__` dirs were removed. `workspace/implementation/` was never read or written, no sibling task dir was touched, and `worklog.md` was not modified.

Files: `test_helpers/` 9 files / 2033 lines (unchanged this session); `test_suite/` `conftest.py` 23 + 18 test modules / 5315 lines.

**Orchestrator verification:** confirmed `test_helpers/` (2033 lines) and `test_suite/` (5338 lines, 19 files incl. conftest) sit at the TASK ROOT, `workspace/` contains only INSTRUCTION.md + PRD.md + implementation/, a recursive find under workspace/ found no stray test dir, and `pytest --collect-only` collects 114 tests cleanly.

## Step 6: Generate implementation — 2026-09-05T19:08:28.000Z

Implementation complete and smoke-verified.

## Modules (`workspace/implementation/`, 3057 lines total)

| File | Lines | Role |
|---|---|---|
| `domain.py` | 916 | constants, computed fields, all 8 calculations, 13 serializers, 4 cascades |
| `routes_series.py` | 292 | negotiations + greenlight fork-join |
| `routes_deal.py` | 266 | script deals, step ladder, notes cycle, cutoff |
| `routes_registry.py` | 246 | agencies, slates, writers, holding deals, logical clock |
| `routes_pilot.py` | 218 | pilot orders, contingencies, wrap, research |
| `validators.py` | 211 | request-shape validation (`ERR_INVALID_REQUEST`) |
| `routes_pitch.py` | 205 | pitch intake, coverage, rights checks, advance |
| `routes_project.py` | 149 | project reads, feasibility, abandon, turnaround |
| `store.py` | 148 | in-memory dicts + logical clock + row helpers |
| `errors.py` | 143 | all 56 PRD error ids to HTTP status + default message |
| `responses.py` | 105 | envelope, pagination |
| `auth.py` | 82 | roles, headers, agency scope, committee/role map |
| `app.py` | 64 | blueprint wiring, error handlers, `0.0.0.0:$PORT` |
| `start.sh` | 11 | guarded pip install, `exec python3 app.py` (foreground) |

## Endpoints: 49/49
Verified by enumerating `app.url_map` — exactly the 49 rows of PRD §4, no extras.

## Smoke test (PORT=51912, killed by that port only)
Full happy path plus refusal probes, all as expected:
- registry → holding deal (writer flips `HOLDING_DEAL`) → terminate (ledger restored to the cent)
- pitch → coverage → rights check → advance refused `ERR_RIGHTS_HOLDBACK_CONFLICT` inside the 90-day quiet buffer, accepted after
- step deal: `HIGH`-tier `STORY` floor came back **4,375,000** cents; exercise/deliver/review x2 bubbled the project to `SCRIPT_COMPLETE`
- pilot: `budget_variance_bps` 500; `WAIVED` from `DevelopmentExec` → 403 ahead of everything; wrap refused `ERR_SHOOT_WINDOW_NOT_ELAPSED` then accepted
- screening: `weighted_raw_score` **75.79** (36.40 + 20.83 + 18.56 — per-component round-half-up, then summed), `norm_adjusted_score` 75.8
- negotiation: self-accept → `ERR_ACCEPT_BY_OFFERING_SIDE`; studio counter; network accept
- greenlight: same user voting a second committee → `ERR_SEGREGATION_OF_DUTIES`; third approval fired the cascade → project `SERIES_ORDERED`
- an under-funded finance approval correctly returned `ERR_FEASIBILITY_FAILED` (tight test data; it confirmed gate 47)
- abandon → write-off 5,000,000 frozen; turnaround recoupment at +3 months = **5,362,500** (interest 112,500 + handling 250,000, under the 6,750,000 cap); exercise created the successor
- slate invariant held exactly: `available 66,625,000 + committed 433,375,000 = total 500,000,000`
- envelope/auth spot checks: 401 missing headers, 403 wrong role, 404 unknown id, 405, 400 on malformed JSON and `limit=0`

Final result line: **SMOKE PASS**. A second fresh boot returned empty arrays with the clock at its startup default `2026-08-01T00:00:00.000Z`, confirming zero seeded state per `start.sh` invocation. Port 51912 released; scratch dir removed.

Two things worth flagging for whoever runs Step 7:
- **PRD §2.11 was treated as authoritative** wherever it disagrees with the scaffold state machines or the §3.x narrative order — most visibly on `POST /negotiations` (posture → term sheet → license cap → certified test → score floor → capacity) and on greenlight filing (project state before negotiation state).
- **Four rules have no catalogue error code**, so the nearest was chosen: holding-deal terminate on non-`ACTIVE` → `ERR_INVALID_DEAL_STATE`; turnaround offer when `turnaround_status != NONE` → `ERR_INVALID_PROJECT_STATE`; wrong-side counter → `ERR_INVALID_NEGOTIATION_STATE`; duplicate `agency_code` → `ERR_INVALID_REQUEST`.

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single message, so the implementation generator started before `test_suite/` existed on disk — physical isolation from the tests is guaranteed.

## Step 7: Run tests and iterate — 2026-09-05T19:21:38.000Z

All 8 rounds are green at 114/114, verified from the per-round `results.$i.json` files (all freshly written, all reporting 114 tests, failing union empty).

## Summary

**Iterations run:** 2 (baseline sweep 111/114 on all 8 rounds; verification sweep 114/114 on all 8 rounds).

The baseline sweep was already deterministic — the same 3 tests failed in 8/8 rounds, with no load-induced or timeout noise anywhere. All 3 failed with a client-side `KeyError` (`'kind'`, `'kind'`, `'cutoff_reason'`), i.e. the tests read response fields the server never returned, rather than the server returning anything wrong.

**Tests deleted:** none. All 3 failures were STEP 1c partial-coverage cases, so only the uncovered assertion in each was removed and every PRD-covered assertion in those tests was kept.

**Fixes applied to `test_suite/`:**
- `test_11_state_machines.py` — `test_one_failed_casting_clearance_collapses_the_pilot_and_returns_its_budget`: dropped `failed["kind"]`/`failed["resolution"]`, replaced with `failed["production_status"] == COLLAPSED`. RESPONSE-SHAPE SILENCE: PRD §3.5 names `kind`/`resolution` only as clearance *inputs*, §2.5 lists no contingency-clearance entity, and §4 classes the clearance as an operation that modifies an existing resource — which §2.2 says returns the updated resource, i.e. the PilotOrder.
- `test_11_state_machines.py` — `test_a_waived_location_is_as_green_as_a_satisfied_one`: same substitution, asserting `waived["location_status"] == WAIVED`.
- `test_15_errors.py` — `test_a_second_cutoff_on_a_cut_off_deal_does_not_release_the_money_twice`: dropped `deal["cutoff_reason"]`. RESPONSE-FIELD SILENCE: PRD §3.4 has BusinessAffairs "*submits* a `cutoff_reason`" and its enumeration of cutoff effects lists the transitions, the fee release and three version bumps but never that the reason is stored — in pointed contrast to §3.3, which explicitly says the holding deal's "`termination_reason` is null for as long as the deal remains `ACTIVE`". The refusal is still asserted via `ERR_INVALID_DEAL_STATE`, terminal `CUT_OFF`, step statuses, `encumbered_cents` and the slate ledger.

**Fixes applied to `test_helpers/`:** none needed — fixtures already sent money as integer cents, date-only fields as `YYYY-MM-DD`, the clock as a full ISO-8601 instant, blank headers as `""`, and `api_client.canonical_instant` already normalised sub-second width.

**Fixes applied to `implementation/`:** none. The implementation was correct on all three counts; adding `kind`, `resolution`, or `cutoff_reason` to its serializers would have made the tests pass but would have violated the cardinal rule against introducing a response field that does not trace to a verbatim PRD sentence. `worklog.md` was left untouched.

**Orchestrator verification:** independently parsed all 8 `workspace/implementation/results.$i.json` (all written 19:19, ~34 KB each): every round reports `passed=114 total=114` with an empty failing set. `pytest --collect-only` still collects 114 tests, confirming no test was dropped. The sweep ran via the pre-written `workspace/sweep.sh` (setsid-detached, script file rather than an inline one-liner, so neither reaping nor the nested-quote `--start-command` corruption could occur).

## Step 8: Finalize PRD — 2026-09-05T19:24:53.000Z

`PRD_FINALIZED.md` is written. Two surgical edits, both traceable to the three Step 7 test fixes; no implementation changes were needed by Step 7, so nothing else was touched.

## Line counts
- `PRD.md`: 452 lines / 89,871 bytes
- `PRD_FINALIZED.md`: 452 lines / 90,462 bytes
- Lines changed: 2 of 452 (**0.44%** of lines); byte delta **+0.66%**. No lines added or removed — both edits are in-paragraph sentence insertions.

## Changes
- **§3.5 (line 270) — insert — pinned the contingency-clearance response shape**: a clearance is not itself a persisted resource, the submitted `note` is retained nowhere, and the response body is the updated `PilotOrder`, on which the recorded resolution shows up as `casting_status`/`location_status` rather than as an echoed `kind`/`resolution`. — `implementation/routes_pilot.py:90-125`, `implementation/domain.py:737-752`
- **§3.4 (line 260) — insert — pinned `cutoff_reason` as input-only**: unlike the holding deal's `termination_reason`, the script deal carries no `cutoff_reason` field and the response body (the updated script deal) never echoes it. — `implementation/routes_deal.py:239-266`, `implementation/domain.py:702-715`

## Pre-edit search log

**Edit 1 — §3.5 clearance response shape**
- (a) Subject: what a contingency clearance persists and what it returns.
- (b) Paths enumerated: `routes_pilot.py:90-125` (`clear_contingency` — both exit paths, FAILED and non-FAILED, return `serialize_pilot_order`); `domain.py:816-830` (`cascade_pilot_collapse`, the FAILED path's callee); `domain.py:737-752` (`serialize_pilot_order` — the only pilot serializer, shared by the POST, `GET /pilot-orders/{id}` and `GET /development-projects/{id}/pilot-orders`; carries no `kind`, `resolution` or `note`); `routes_pilot.py:102` (the `note` is validated then discarded); `store.py:18-33` (no `clearances` collection exists — nothing to list or read back); grep for `clearance` across all of `implementation/` — only the one POST route, no GET.
- (c) Adjustment: the first draft said the `kind`/`resolution`/`note` are "inputs only". That would have contradicted `domain.py:824` and `domain.py:912`, where the failing `kind` *is* recorded as `collapsed_reason` (and `PROJECT_ABANDONED` on the abandonment path). Re-scoped the claim to "no clearance record hangs off the pilot order" plus "no echoed `kind` or `resolution` **field**" on the response, leaving the existing `collapsed_reason` sentence two paragraphs down untouched and uncontradicted. Also kept "the `note` is retained nowhere" narrow to `note`, which is the only one of the three genuinely discarded.

**Edit 2 — §3.4 `cutoff_reason`**
- (a) Subject: whether the deal-level cutoff reason is part of the `ScriptDeal` representation.
- (b) Paths enumerated: `routes_deal.py:244` (required non-blank string, max 500) and `:260` (assigned to the row) and `:266` (returns `serialize_script_deal`); `domain.py:702-715` (`serialize_script_deal` — the sole script-deal serializer, shared by create/read/list/cutoff; no `cutoff_reason`); grep `cutoff_reason` across `implementation/` — only those two `routes_deal.py` lines, so neither `cascade_greenlight_approved` (`domain.py:863-885`, sets `COMPLETED`) nor `cascade_abandon` (`domain.py:888-916`, sets `TERMINATED`) writes it; parallel reason fields that *are* exposed, to avoid over-generalising: `termination_reason` (`domain.py:645`), `abandon_reason` (`:695`), `collapsed_reason` (`:750`), `withdrawn_reason` (`:787`), `notes_summary` (`:732`).
- (c) Adjustment: scoped the negative claim strictly to the script deal and explicitly contrasted it with `termination_reason` so it cannot be read as a general rule about `_reason` fields (which would have mis-described the four exposed ones above). Also dropped a draft clause asserting the "required non-blank, at most 500 characters" validation, since that is outside the Step 7 item and §2.11 rule 9 already covers request-shape generically.

**Orchestrator note:** Step 8 was NOT skipped — the skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes, and Step 7 applied 3 `test_suite/` fixes. Verified the diff is exactly 2 changed lines (both in-paragraph inserts, no lines added/removed), both files are 452 lines, and `PRD_FINALIZED.md` still ends at the final `ERR_FEASIBILITY_FAILED` catalogue row.

## Step 9: Complete PRD — 2026-09-05T19:47:43.000Z

Run as **three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`** (pass 1 did the `cp` from PRD_FINALIZED.md; passes 2 and 3 were forbidden from copying so earlier edits survived). Partition: pass 1 = app/responses/auth/errors/validators/store/routes_registry/routes_pitch; pass 2 = routes_deal/routes_pilot/routes_project; pass 3 = routes_series + domain.py (formulas, constants, 13 serializers, 4 cascades).

**Totals: 53 edits — 42 ambiguity-pins, 11 mismatch-revisions.** PRD_FINALIZED.md 452 lines / 90,462 bytes → PRD_COMPLETED.md 456 lines / 107,580 bytes (+4 lines, +18.9% bytes).

### Pass 1 (18 changes: 16 ambiguity, 2 mismatch)
- §2.1 — insert — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` counts as empty (401); role matched exactly, case-sensitively, untrimmed; `X-User-ID` taken verbatim — auth.py:54-57
- §2.1 — insert — ambiguity — missing/null/non-string `agency_id` in a payload yields `ERR_AGENCY_SCOPE_VIOLATION` not `ERR_INVALID_REQUEST`; the two list endpoints scope on the `agency_id` *query parameter* and silently narrow to the caller when omitted; the acting id is never resolved as a row, so a matching pair of unknown ids falls through to `ERR_AGENCY_NOT_FOUND` — auth.py:77-82, routes_registry.py:103-105,131-134, routes_pitch.py:43-47,94-97
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A–Z/0–9; `api_request_timestamp` read from the logical clock, so responses at one clock setting share it — responses.py:19-27
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` literals are `ERR_INVALID_REQUEST`; whitespace and leading zeroes tolerated; an over-run `offset` returns an empty page, not an error — responses.py:69-98
- §2.3 — insert — ambiguity — `created_at` ties (the norm under a stationary clock) break by write order, making the ordering total and stable — store.py:146-148
- §2.3 — insert — ambiguity — filter query params matched literally, never validated against their enum: an out-of-set value returns an empty 200 page rather than 400/404 — routes_registry.py:126-141,200-213, routes_pitch.py:90-108
- §2.4 — insert — ambiguity — `to_iso8601` required and ISO-8601-parseable (`Z`/offset normalised to UTC, zoneless read as UTC, sub-ms truncated); `current_utc` is the whole of `data`; the clock may move backwards or be re-set to its current value — routes_registry.py:238-246, store.py:75-90
- §2.6 — insert — ambiguity — an absent/null/non-string body FK draws that entity's 404, not 400, because key resolution precedes shape validation; multi-key resolution order pinned (pitch agency→slate, holding deal writer→slate, greenlight project→negotiation) — domain.py:108-114, routes_registry.py:157-158, routes_pitch.py:47-48
- §2.11 item 9 — insert — ambiguity — strict typing with no coercion (int rejects `"5"`/`5.0`/bool; bool rejects `0`/`1`; date only 10-char `YYYY-MM-DD`); blank test after stripping but length measured raw; non-object/unparseable body is this step's error; date-range end-side rule added — validators.py:17-40,54-150
- §2.11 item 12 — revise — mismatch — `ERR_INVALID_DEAL_STATE` at that position also carries the holding deal's "must still be `ACTIVE`" requirement — routes_registry.py:222-223
- §3.1 — insert — ambiguity — slates are not unique on `(platform, season_year)` — routes_registry.py:63-84
- §3.1 — insert — ambiguity — a duplicate `agency_code`, like a malformed one, is `ERR_INVALID_REQUEST` — routes_registry.py:31-39
- §3.1 — insert — mismatch — `GET /agencies/{id}` reports `submissions_used_count` unfiltered across every season (no slate in play), so it can exceed the figure the cap check used — domain.py:591, domain.py:418-430
- §3.2 — insert — ambiguity — `packaging_elements` entries capped at 200 chars; an explicit null defaults to `[]` — routes_pitch.py:52-53, validators.py:165-178
- §3.2 — insert — ambiguity — `coverage_score` echoed as a JSON number carrying its decimal place (`75` reads back `75.0`) — domain.py:660, validators.py:181-185
- §3.2 — insert — ambiguity — a check's `underlying_ip_key` is recorded as submitted, never cross-checked against the pitch's own key — routes_pitch.py:142,150-159
- §3.2 — insert — ambiguity — when several checks share the highest `created_at`, the last filed governs — routes_pitch.py:185-188, store.py:146-148
- §3.3 — insert — ambiguity — `termination_reason` required, non-blank, ≤500 chars; a second termination is `ERR_INVALID_DEAL_STATE` and loses to the body-shape check — routes_registry.py:220-223
- §4 preamble — insert — ambiguity — a trailing slash is equivalent to its absence — app.py:25
- §5 preamble — insert — ambiguity — framework-level `ERR_NOT_FOUND` 404 (unrouted path), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500, all in the standard error envelope — app.py:39-54, errors.py:79-81

### Pass 2 (18 changes: 14 ambiguity, 4 mismatch)
- §2.6 — insert — ambiguity — script-deal body FK order pinned as `writer_id` before `project_id` (the writer's guild tier floors the step fees), so a deal naming neither key answers `ERR_WRITER_NOT_FOUND` — routes_deal.py:46-47
- §2.8 — revise — mismatch — the "`LOCKED` slate takes no new development, pilot or series commitment" sentence narrowed to the three operations that actually consult the gate (pitch advance, pilot order, negotiation open); step-deal execution and option exercise explicitly proceed on a `LOCKED` slate — routes_pitch.py:199, routes_pilot.py:39, routes_series.py:70 vs. no call in routes_deal.py
- §2.11 item 9 — revise — mismatch — "comparable-title norm index greater than zero" → "within its declared 50.0 to 150.0 band" — routes_pilot.py:159
- §3.4 — insert — ambiguity — the three execution gates are exhaustive; no posture gate on a step deal — routes_deal.py:54-71
- §3.4 — insert — ambiguity — every step action's response body is the updated deal step — routes_deal.py:177,192,236
- §3.4 — insert — mismatch — delivery requires the parent deal still `EXECUTED` and reports `ERR_INVALID_DEAL_STATE` ahead of the step-status check; delivery touches only the step — routes_deal.py:185-191
- §3.4 — insert — mismatch — review likewise checks the deal's state first; `notes_summary` ≤1000 chars, non-blank, persisted as the step's own field (null until supplied), recorded on `ACCEPT` as on `NOTES`, and omitted/null leaves the prior value in place — routes_deal.py:202-225,95
- §3.4 — insert — ambiguity — version movement per outcome: `NOTES` touches the step alone; `ACCEPT` touches step + deal, plus project only when it reaches `SCRIPT_COMPLETE`; slate never — routes_deal.py:218-235
- §3.4 — insert — ambiguity — `cutoff_reason` required, non-blank, ≤500 chars — routes_deal.py:244
- §3.5 — insert — ambiguity — both contingency deadlines required `YYYY-MM-DD`, unconstrained against each other/the shoot window, and never read by any rule — routes_pilot.py:26-27
- §3.5 — insert — ambiguity — `note` ≤500 chars, non-blank when supplied, validated then discarded — routes_pilot.py:102
- §3.5 — insert — ambiguity — wrap reads no request body, so an absent/unparseable/non-object payload is ignored rather than `ERR_INVALID_REQUEST` — routes_pilot.py:130-136
- §3.6 — insert — ambiguity — `expected_pilot_order_version` must be a non-negative integer; a negative one is `ERR_INVALID_REQUEST` before any comparison — routes_pilot.py:161
- §3.6 — insert — ambiguity — the pilot's `version` increments on *every* fielding, even with nothing to invalidate — routes_pilot.py:188-189
- §3.6 — insert — ambiguity — certify reads no body and touches only the screening; pilot-order and project versions unchanged — routes_pilot.py:207-217
- §3.8 — insert — ambiguity — §2.3's tolerant-filter rule does not apply to the feasibility read: a `basis` other than exactly `PATTERN`/`LICENSE` and an `episode_count` that is not an integer literal ≥1 are `ERR_INVALID_REQUEST`; the response also reports `project_id` — routes_project.py:51-60, domain.py:515
- §3.9 — insert — ambiguity — `abandon_reason` required, non-blank, ≤500 chars — routes_project.py:95
- §3.9 — insert — ambiguity — both turnaround-offer state requirements are `ERR_INVALID_PROJECT_STATE` with `dev_status` read first; no body read; only the project's version increments — routes_project.py:106-112
- §3.9 — insert — ambiguity — `months_elapsed` day-of-month rule spelled out and the clamp at zero pinned (clock before `abandoned_at` ⇒ 0, never a credit) — store.py:116-121
- §3.9 — insert — ambiguity — `successor_title` required, non-blank, ≤160 chars; `turnaround_status` `OFFERED` is the whole state gate, `dev_status` not re-examined — routes_project.py:121-124
- §4 table — revise — mismatch — `GET /development-projects/{id}/negotiations` also accepts a `status` filter — routes_project.py:76-78

### Pass 3 (17 changes: 12 ambiguity, 5 mismatch)
- §2.6 — insert — mismatch — body-key resolution runs only on a readable payload: a present-but-unparseable / non-object body is `ERR_INVALID_REQUEST` *before* any body FK resolves, while a wholly absent body is read as `{}` and still draws the FK's 404 — routes_series.py:59,170
- §2.11 item 4 — insert — ambiguity — the committee/role check reads the raw submitted value, so a `committee` outside the three names has no role to mismatch and falls through to step 9 — routes_series.py:240-242
- §2.11 item 6 — insert — mismatch — the segregation-of-duties check must read a stored row, so it is evaluated after the path greenlight resolves (unknown id → `ERR_GREENLIGHT_NOT_FOUND`) — routes_series.py:244-249
- §3.7 — revise — mismatch — the two research gates are not first: they sit after term-sheet coherence and license-cap and before episode inventory; also pinned the certified-screening sub-tie (highest `certified_at`, then lowest `created_at`, then earliest written) — routes_series.py:72-83, domain.py:474-482
- §3.7 — revise — mismatch — commercial-gate ordering reworded to bracket the research gates; the `episode_count ≥ 1` coherence clause marked unreachable (shape validation reports `ERR_INVALID_REQUEST` first) — routes_series.py:27,39-49
- §3.7 — insert — ambiguity — opening writes only the slate (project `version` untouched), and a project may hold several standing negotiations, each reserving its own `episode_count` — routes_series.py:85-96
- §3.7 — insert — ambiguity — countering out of turn (Studio on a `STUDIO_COUNTER`, BusinessAffairs on its own `NETWORK_OFFER`) is `ERR_INVALID_NEGOTIATION_STATE`, not an authorisation error — routes_series.py:109-112
- §3.7 — insert — ambiguity — accept reads no request body (any payload ignored), leaves `round_number`/`last_offer_side` untouched, and neither accept nor counter writes the project row — routes_series.py:142-160
- §3.8 — revise — mismatch — greenlight-filing gates reordered to project state → negotiation `AGREED` → version guard → project mismatch, and `expected_project_version` pinned as an integer ≥ 0 (negative = `ERR_INVALID_REQUEST` before the 412) — routes_series.py:173-189
- §3.8 — insert — ambiguity — decision `note`: ≤1000 chars, non-blank when supplied, explicit null accepted, validated then discarded — routes_series.py:254
- §3.8 — insert — ambiguity — a non-final vote increments only the request's `version`; project, negotiation and slate untouched — routes_series.py:289-292
- §3.8 — insert — ambiguity — the approval cascade also bumps every completed deal and cut-off step, and never writes the negotiation — domain.py:861-879
- §3.8 — insert — ambiguity — a `REJECTED` vote moves only the request's own `version`; no other row or ledger figure changes — routes_series.py:278-282
- §2.7 — revise — ambiguity — basis-point scaling divides downward (largest integer ≤ true quotient), so negative quotients round away from zero — domain.py:89-96,437-438
- §3.6 — insert — ambiguity — `expected_pilot_order_version` is input-only and is not echoed on the screening — domain.py:755-769
- §3.6 — insert — ambiguity — the two score decimals and `comp_norm_index` are emitted as JSON numbers with no trailing-zero precision (`100` → `100.0`, `62.00` → `62.0`) — domain.py:763-765, validators.py:181-185
- §3.9 — insert — ambiguity — the abandonment cascade also bumps every terminated deal, cut-off step, withdrawn negotiation and collapsed pilot — domain.py:882-916

**Verified by pass 3 with no change needed:** all 8 formulas and every constant (guild floors/tier factors, weights 4550/2975/2475, platform factors, deficit tier breakpoint 1,500,000 and factors 10000/9500/9000, 900 bps / 180 days / handling tiers / 13500 bps cap, posture 6000 bps, round ceiling 4, score floor 62.0); the feasibility response field set and its four-step order; all 13 serializers (a programmatic sweep confirmed every emitted field name is named somewhere in the PRD) and every nullable field's pre-event baseline; `cascade_pilot_collapse` and `supersede_screenings`/`supersede_greenlights` side-effect sets.

**Orchestrator verification:** PRD_COMPLETED.md is 456 lines / 107,580 bytes and is NOT byte-identical to PRD_FINALIZED.md (`cmp` differs at byte 2572), so the scan demonstrably ran. All 26 headings present (§1–§5 with §2.1–2.11 and §3.1–3.9 contiguous), §4 endpoint table has exactly 49 data rows, §5 catalogue exactly 55 data rows, and the file still ends at `| ERR_FEASIBILITY_FAILED | 422 |`. No difficulty-directive / "scaffold" / "test_recipe" leakage. Only one worklog.md exists (task root — no cwd-drift stray under workspace/). Newest `implementation/` source mtime 18:07 and newest test mtime 19:15 both predate the 19:19 green sweep results, confirming Steps 8 and 9 changed only PRD prose and the 8/8 × 114/114 result still stands.

