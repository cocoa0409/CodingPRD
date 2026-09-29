# Worklog — task_2918_reverse_logistics_returns_processing_center

## Step 1: Create task directory — 2026-09-05T16:33:59.218Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2918_reverse_logistics_returns_processing_center` and its `workspace/` subdirectory. Index 2918 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed and no index was self-allocated (32 pipelines run concurrently on this host, so auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-05T18:52:00.000Z

All three scaffold artifacts for task 2918 are complete and pass the linter.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2918_reverse_logistics_returns_processing_center/`)
- `SCAFFOLD.yaml` — 3267 lines, 176 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2163 lines, 150 KB
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5084 lines, 320 KB

**SCAFFOLD.yaml (§1.0–§1.7)** — no `scaffold_difficulty_design` / `scaffold_corner_design` keys present
- 14 entities, 5 state machines (ReturnAuthorization.status, ReturnLine.disposition_state, ReturnLine.financial_state, RefurbWorkOrder.status, DispositionOrder.status — parallel shape on ReturnLine), 2 concurrency rules, 16 calculations, 55 validations (one global priority ladder 1–61), 64 endpoints, 56 errors, 7 roles.
- complexity_profile: workflow_orchestration + compliance_audit, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation]`, flat topology, segregation_of_duties role model, immediate consistency, difficulty_level `expert_plus`.
- Concurrency rules: `rma-reissue-stale-version` (`expected_rma_version` -> ERR_STALE_RMA_VERSION 412) and `disposition-order-create-stale-line` (`expected_return_line_version` -> ERR_STALE_RETURN_LINE_VERSION 412).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — 21 instances over 9 rule ids: dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — 112 instances (80 full recipes + 32 `excluded_because` stubs), all nine mandated sections and no invented ones: entities 14, state_machines 20 (7 stubs), calculations 19 (8), validations 25 (3), endpoints 5, errors 12 (10), rbac 10 (2), cross_cutting_complexity_layers 6 (2), consistency_model 1.

**Lint verdict** (verbatim):
```
Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     14
  §1.8 instances scanned:     21
  §1.9 instances scanned:     80
  Calls scanned (§1.8+§1.9):  1009

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Independent checks run beyond the linter**: zero duplicate instance names across §1.8 ∪ §1.9; every stub carries `excluded_because` with a citation resolving to a real (rule_id, instance) pair and no `test_recipe`; every full instance has grounds, claim_type, distinguishing_aspect, setup, structured setup_api_calls, trigger and asserts; zero unbound `${var}` references across 1009 calls; all 45 OCC `expected_*_version` payload values are `${…}`-templated; **all 56 declared error ids are triggered or stubbed**.

Two things worth flagging to the caller: (1) `api_prefix` is the empty string — §1.5 paths and all 1009 recipe calls are root-relative and mutually consistent, so a later step that prepends a prefix would have to rewrite every call; (2) the "Generate task harder than expert level!" directive did **not** leak into `scenario` (or anywhere else in the three files), so the usual post-Step-2 strip is unnecessary here. `worklog.md` was left untouched (still Step 1 only).

**Orchestrator verification**: independently grepped all three YAMLs for "harder than expert" / "expert level" — zero hits, leak confirmed absent. `workspace/` survived Step 2 intact (only a `.scratch_step2/` scratch dir was left behind; removed).

## Step 3: Copy shared files — 2026-09-05T18:54:29.315Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T19:10:00.000Z

PRD.md is complete at `workspace/PRD.md` — **439 lines / 116,732 bytes**, written in 12 chunked appends (no single giant Write). Scratch dir `workspace/.scratch_step4/` removed; worklog.md untouched; neither withheld design file was opened.

**Heading list (27 headings)**
```
#   Reverse Logistics & Returns Processing Center API — Product Requirements Document
##  1. Introduction
##  2. Global Specifications & System-Wide Principles
### 2.1. Operator Identity and Role-Based Access Control
### 2.2. API Response Structure  (#### Standard Success Response Format / #### Standard Error Response Format)
### 2.3. Pagination
### 2.4. Resource Identity, Timestamps and the Logical Clock
### 2.5. Money, Percentages and Rounding Discipline
### 2.6. Validation Order and the First-Violation Rule
### 2.7. Segregation of Duties
### 2.8. Optimistic Concurrency Control
### 2.9. Two Independent State Dimensions and the Cascade Chain
### 2.10. Client Posture, Suspension and Exposure Governance
### 2.11. Nested Retrieval, Filtered Reads and Status Codes
##  3. Business Logic & Workflows
### 3.1. Standing Up a Client: Contracts, Catalogue, Bays and Channels
### 3.2. Authorizing a Return, and the Four Ways an Authorization Ends
### 3.3. The Dock: Cartons, Scanned Unit Lines and Receipt-Stage Fraud Checks
### 3.4. Quarantine, Condition Grading and the Disposition Decision Matrix
### 3.5. Refurbishment: Work Orders, Bay Windows, Test Cycles and Repackaging
### 3.6. Routing Units to Market: Disposition Orders, Channel Selection and Pricing Feedback
### 3.7. The Money Axis: Holds, Releases, Denials and Clawbacks
### 3.8. Recall Cascades, the Shrink Ledger, Conservation and Audit Reporting
##  4. API Endpoint Definitions
##  5. Error Code Catalogue
```

**Coverage (all machine-verified against SCAFFOLD.yaml)**
- **Endpoints 64/64** — §4 table diffed against `endpoints[]`: zero missing, zero extra, method+path exact. Table is exactly 4 columns.
- **Errors 56/56** — §5 table diffed against `errors[]`: zero missing, zero extra, **zero HTTP-status mismatches**. Table is exactly 2 columns. All 56 identifiers also appear in §1–§4 prose near the rule they guard.
- **Validations 55/55** — full ladder in §2.6; every scaffold priority 1–61 (with the scaffold's gaps at 39, 51–54, 59) explicitly named, every `error_id` present.
- **Calculations 16/16** — including both `return_line_recovery_value` variants (`provisional_at_grade` with the round-per-unit-before-multiplying rule, `final_at_execution`), both `client_settlement_balance` variants (booked vs projected), and all 23 `disposition_audit_report` output fields.
- **State machines 5/5, transitions 45/45** — every from->to pair co-located in prose (`PASSED_QA -> REPACKAGED` is in §3.5 line 249; the automated co-occurrence check only flagged it on sentence-window distance).
- **Roles 7/7** — all named in backticks; `ClientRep` scoping in §2.1/§2.6.
- **Concurrency rules 2/2** — `expected_rma_version`/`ERR_STALE_RMA_VERSION` and `expected_return_line_version`/`ERR_STALE_RETURN_LINE_VERSION`, both 412.
- **§2.2 is byte-identical** to `section-2.2-response-structure.md` (diff clean).
- **Clean boundary:** file ends on the final `| ERR_REFUND_EXCEEDS_EXPOSURE_CAP | 409 |` table row — no audit footer, no mid-sentence cut.

**Hard Contract reports**

- **Contract 1 — Field-Name Coverage: PASS.** 163/163 required identifiers (all 147 `entities[].fields[].name` rows deduped, all `endpoints[].input` keys with `?` stripped, all `{path_param}` names, all computed `output` keys) appear verbatim in backticks. Missing set empty.
- **Contract 2 — Rule Coverage: PASS.** All 55 ordered validations with their `applies_to` scopes named endpoint-by-endpoint in §2.6; both OCC rules; all 45 transitions with triggers reframed per Contract 3; all 16 calculations with constants inline (`0.075` handling share, `750` destruction fee, 95 cents/minute labour, 15 percent overhead, grade multipliers `0.85/0.65/0.40/0.20/0.00`, reason penalties, surcharge bands `+0.06 / 0.00 / -0.04`, fee clamp `0.00-0.40`, price-index clamp `0.5000-1.5000`); all cross-entity cascades (5-link execute cascade, 4-link mandatory-recall cascade in the scaffold's own link order, void/expiry shrink sweeps); sibling-branch symmetry (repackage vs abandon, approve->execute vs cancel, release vs deny vs reverse); and the two exact-equality conservation invariants.
- **Contract 3 — §3 Path Purity: PASS.** 1,005 backtick tokens (296 unique) inside §3 enumerated; zero start with `/`, zero are bare HTTP methods, zero combine method+path. Every endpoint is named by state-transition framing, role + action verb, or capability description.

One scaffold tension resolved in prose rather than by narrowing: the receipt endpoint lists `ISSUED -> PARTIALLY_RECEIVED` as its own side effect while the state machine attributes re-derivation to line scanning — §3.3 says creating a receipt "begins partial receiving" but that the authoritative `status` is always the value re-derived from line rollups, satisfying both readings.

**Orchestrator verification (truncation guard)**: independently ran `wc -lc` (439 lines / 116,732 bytes), counted 27 headings, and read `tail -12` — the file terminates on the final error-catalogue table row `| ERR_REFUND_EXCEEDS_EXPOSURE_CAP | 409 |`, a real section boundary, not a mid-sentence cut. No regeneration needed. Also grepped PRD.md for "harder than expert" / "expert level" / "scaffold": zero hits, so the Step 2 difficulty directive did not reach the PRD.

## Step 6: Generate implementation — 2026-09-05T19:52:00.000Z

Implementation complete. All 64 endpoints are live, the module set byte-compiles, and an end-to-end smoke boot passed on a private port with only my own PID killed.

## Modules written (all under `.../task_2918_reverse_logistics_returns_processing_center/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
`app.py` | 66 | Flask app, 7 blueprint registrations, `ApiError`/404/405/500 handlers, `0.0.0.0:$PORT` (default 10000), foreground |
`db.py` | 136 | in-memory dicts, logical clock pinned to `2026-08-01T00:00:00.000Z`, id/timestamp/version stamping |
`errors.py` | 134 | `ApiError` + status map (56 declared ids + 3 internal) |
`response.py` | 136 | `meta`/`response_type`/`data` envelope, `req_`+20-char request ids, clamped `limit`/`offset` pagination |
`middleware.py` | 65 | `X-User-ID`/`X-User-Role`, 7 roles, ClientRep scoping/narrowing |
`shapes.py` | 199 | priority-4 shape validators (enums, ints, 2/4-dp percentages, ISO instants, windows) |
`refs.py` | 118 | parent-chain resolution helpers |
`constants.py` | 178 | every enum plus all pinned coefficients/thresholds |
`calc.py` | 263 | 16 calculations, `Decimal` + `ROUND_HALF_UP` only |
`aggregates.py` | 195 | derived-on-read balances/buckets/rollups, ledger append + auto suspend/reinstate |
`serialize.py` | 263 | per-entity serializers (append-only entities carry only `id`/`created_at`) |
`services.py` | 508 | existence guards, fraud checks, disposition matrix, refurb costing, 5-link execute cascade, 4-link mandatory-recall cascade, expiry sweep, bay/channel window rules, channel selector |
`query.py` | 29 | list-filter helpers |
`routes/`: clients 198, catalog 224, rma 247, receipts 220, lines 267, refurb 216, dispositions 386 | | 64 endpoints |
`requirements.txt` 1, `start.sh` 10 | | guarded `pip install`, `exec python3 app.py` |

Total ~4,059 lines across 22 files.

## Verification

- **Endpoints: 64/64.** A programmatic diff of Flask's `url_map` against the PRD §4 table shows zero missing and zero extra (method + path both matched).
- **Errors: 56/56 wired**, every HTTP status matching the PRD §5 catalogue exactly (45 raised as literals, 11 not-found ids via the `services.must_*` wrappers). Three extra non-PRD ids (`ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`, `ERR_INTERNAL`) exist only for unrouted paths/methods and unexpected exceptions.
- **Byte-compile:** `python3 -m py_compile` over all 21 `.py` files returned clean (`COMPILE_OK`); `__pycache__` dirs were then removed so `implementation/` holds only source.
- **No seeding:** the store is built empty by `db.reset()` at import; the only `seed`/`preload` hits in the tree are docstrings saying it never happens. A restart demonstrably wiped state (the second smoke run re-created `client_code=ACME` that had been rejected as a duplicate before the reboot).
- **Smoke boot:** `PORT=39181 bash start.sh` came up in ~3s; a 36-step end-to-end script exercised auth/RBAC/shape failures, client->item->bay->channel->RMA->issue->receipt->scan->grade->propose->approve->execute->pricing-feedback->clock->release->reverse->audit, pagination clamping, and 404/405 handling. **35/36 matched expectations; the single mismatch was my script's own wrong guess** (it expected 409 for `ERR_STALE_RETURN_LINE_VERSION`, and the PRD line 415 says 412 — the server returned 412, which is correct). Spot-checked economics all tie out: recovery `20000x0.40x0.90=7200/unit`, frozen `unit_price 7200`, gross `18000`, band surcharge `+0.06 -> fee_pct 0.16`, fee `2880`, net `15120`, recovery credit `15120-1134=13986`, `variance_pct 0.25`, re-indexed `price_index_pct 1.2500`, and the audit reported `unit_conservation_ok`/`money_conservation_ok` both true.
- **Shutdown:** killed by captured PID only (`kill 761528` plus its `exec`'d child), confirmed `port 39181 free`. No `pkill -f` was ever run.
- **Constraints honoured:** nothing was written outside `implementation/`; `test_suite/`, `test_helpers/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never read, listed, globbed or grepped; `worklog.md` untouched; `.scratch_step6/` removed (the `.scratch_step5` dir and `sweep.sh` in `workspace/` are other steps' artifacts, not mine).

Two recorded interpretation decisions worth relaying: validation ordering follows the PRD's **numeric priority ladder** wherever it conflicts with the "path ids first" prose (e.g. p8 channel resolves before p14 order on pricing-feedback), and uniqueness collisions (duplicate `client_code`, `tracking_reference` per RMA) map to `ERR_INVALID_REQUEST` since the catalogue declares no dedicated conflict code.

**Orchestrator note**: Steps 5 and 6 were launched concurrently in a single message, so this implementation generator started before `test_suite/` existed on disk — physical isolation from the test artifacts, in addition to the explicit prohibition it confirms it honoured.

## Step 5: Generate unit tests — 2026-09-05T20:47:00.000Z

Step 5 is complete.

## Output paths (confirmed at the task root, nothing under `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2918_reverse_logistics_returns_processing_center/test_helpers/` and `.../test_suite/`. `workspace/test_helpers` and `workspace/test_suite` do not exist. Nothing under `workspace/implementation/` was read or written; scratch dir `workspace/.scratch_step5/` was deleted.

## Files written (line counts)

test_helpers: `__init__.py` 17, `api_client.py` 410, `api_errors.py` 149, `assertions.py` 381, `constants.py` 332, `factories.py` 388, `fixtures.py` 693, `test_users.py` 92, `types.py` 239.

test_suite: `conftest.py` 22, `test_01_recovery_value_variants` 206 (5 tests), `test_02_settlement_rounding_and_fee_bands` 161 (4), `test_03_parallel_state_dimensions_and_rework_cycles` 459 (9), `test_04_execute_and_recall_cascades` 426 (8), `test_05_validation_priority_conflicts` 328 (8), `test_06_boundary_precision` 365 (9), `test_07_cross_entity_state_dependencies` 318 (6), `test_08_bay_and_channel_window_overlap` 336 (5), `test_09_compensating_invariants` 270 (5), `test_10_entities` 519 (14), `test_11_state_machines` 574 (13), `test_12_calculations` 661 (11), `test_13_validations` 1277 (22), `test_14_endpoints` 402 (5), `test_15_errors` 105 (2), `test_16_rbac` 456 (8), `test_17_cross_cutting` 350 (4), `test_18_consistency` 109 (1). Total 10,045 lines.

## Totals and coverage

- **139 tests, 139 `Design:` lines** — machine-verified exactly one tag per test, zero unknown tags, zero dual-tagged or untagged tests, no docstring mentions "scaffold", every docstring carries a PRD citation.
- **Queue A (§1.8): 21/21 non-stub instances translated** (59 tests, test_01–test_09).
- **Queue B (§1.9): 80/80 non-stub instances translated** (80 tests, test_10–test_18). The 32 instances carrying `excluded_because` got no test, as required.
- Every file parses (`ast.parse`); pyflakes is clean except the two known-benign warnings (`test_suite/conftest.py` re-exporting `api_errors`, `test_helpers/factories.py` `HAZARD_NONE`).
- No skip/xfail/mock/monkeypatch anywhere.

## Instances SKIPPED entirely

None — every non-stub instance in both queues yielded a test.

## Partial omissions (design sub-assertion dropped, PRD-first reason)

1. `Difficulty/boundary_precision_check/empty_box_weight_threshold_exact_sixty_percent_not_suspected` — dropped the RMA-status sub-assertion; the PRD does not uniquely derive the authorization status at that point.
2. `Difficulty/cross_entity_state_dependency/receipt_creation_blocked_by_suspended_client` — dropped the post-reinstatement `PARTIALLY_RECEIVED` claim; §3.2 re-derives RMA status only "every time a unit is scanned", and no scan occurs after reinstatement.
3. `Corner/validations/corner_val_open_work_order_cannot_start_after_a_mandatory_recall` — dropped `disposition_state == DISPOSITION_ASSIGNED`; §3.8 states an `OPEN` work order is deliberately not swept, so the PRD does not fix that value.
4. `Corner/validations/corner_val_receipt_at_exactly_expires_at_is_rejected_as_expired` — restructured to a forward-only clock with a sibling control RMA; the design's "rewind one millisecond and expect 201" contradicts §3.2's permanent `EXPIRED` sweep.
5. `Corner/rbac/corner_rbac_grading_inspector_cannot_create_a_disposition_order` — dropped `effective_fee_pct == 0.18` / `net_recovery_cents == 5904` at proposal (§3.6: realized-economics fields "start at zero"; asserted the zeroes instead); also corrected the design's non-enum `channel_type: LIQUIDATION` to `BULK_LIQUIDATOR` and its non-PRD `disposition_state == GRADED` to `DISPOSITION_ASSIGNED`.
6. `Corner/rbac/corner_rbac_center_admin_break_glass_stops_at_the_money_axis` — dropped `refund-releases … total_count == 0`; §3.4 says grading creates the line's single `RefundRelease`. Asserted instead that the one release exists with `released_at` and `released_by_user_id` null.
7. `Corner/cross_cutting_complexity_layers/corner_ccl_stale_expected_return_line_version_blocks_the_order_create` — the design's final "re-send with DONATE on the liquidation channel -> 201" would hit priority 48 (`ERR_CHANNEL_GRADE_NOT_ACCEPTED`, channel type must serve the disposition), so the re-send names a `DONATION_PARTNER` channel; the design's `LIQUIDATION` channel_type and `disposition_state == GRADED` were likewise corrected to the declared enum members.

**Orchestrator verification**: `ls -d` confirms `test_helpers/` and `test_suite/` sit at the task root and that no `workspace/test_helpers` or `workspace/test_suite` stray exists; both scratch dirs are gone. Independently counted 139 test functions and 139 `Design:` tags (59 Difficulty + 80 Corner) and grepped for `skip`/`xfail` — the only hit is the word "skipping" inside an English docstring sentence, no pytest markers.

## Step 7: Run tests and iterate — 2026-09-05T21:47:00.000Z

Scratch removed. Final state verified clean.

## Summary

**Iterations run: 3** (each a full 8-round parallel sweep under `setsid`, using the pre-existing `workspace/sweep.sh` + `SWEEP_DONE` sentinel).

- Iteration 1: 122/139 in all 8 rounds — 17 deterministic failures, zero flakiness (identical failure set every round).
- Iteration 2: 138/139 in all 8 rounds — 1 remaining.
- Iteration 3: **139/139 passed in all 8 rounds**, 0 failed / 0 errors / 0 skipped.

**Tests deleted: none.** Every failing assertion traced to a verbatim PRD sentence; no PRD-silence or unique-derivability collapse was found.

### Fixes applied to `test_suite/`
- `test_04_execute_and_recall_cascades.py`, `test_06_boundary_precision.py` — client codes `CLRECALL2/3/4`, `CLBOUND1B/1C` were 9 characters, violating PRD §3.1 "a short operator-facing `client_code` of three to eight uppercase alphanumeric characters". Shortened to `CLREC2/3/4`, `CLBND1B/1C`. (This one fixture-literal bug caused 5 of the 17 failures as shared setup errors.)
- `test_05_validation_priority_conflicts.py` — two `disposition_order_payload` calls omitted `channel_window_start_at`/`channel_window_end_at`, which PRD §3.6 makes mandatory "for every non-restock order"; the PRD-faithful shape gate at priority 4 correctly answered `ERR_INVALID_REQUEST` before the priority-30 recall lock the tests were probing. Added the lot window.
- `test_13_validations.py:1157`, `test_09_compensating_invariants.py:249` — minority call sites read `released_at` / `reversed_at` off the *ReturnLine* returned by `release-refund` / `reverse-refund`, but PRD §2.4 places both "on a refund release". Made them match the majority pattern (`fx.refund_release_for_line`), which `test_12` already used.
- `test_16_rbac.py:394` — asserted `ERR_CLIENT_SCOPE_VIOLATION` for a ClientRep passing another client's `receipt_id` as a **query filter**, contradicting the sentence the test's own docstring cites: "Filtered list reads are silently narrowed to the caller's own client rather than erroring — ... but an explicit **path** identifier belonging to another client is rejected". Corrected to assert the narrowed empty page.

### Fixes applied to `test_helpers/`
- `types.py` — added `released_by_user_id` to the `RefundRelease` TypedDict (PRD §2.1 places it there; the TypedDict omitted it while tests read it).

### Fixes applied to `implementation/`
- `serialize.py` / `services.py` / `routes/lines.py` (`refund_release` row, serializer, `release_refund`) — `released_by_user_id` was stamped and exposed only on the `ReturnLine`. PRD §2.1: "for `RefundAnalyst`, recorded as `released_by_user_id` **on refund releases**". Added to the RefundRelease row, initialised null, stamped on release, and serialized.
- `routes/receipts.py` (`create_receipt`) and `routes/rma.py` (`reissue_rma`) — an `EXPIRED` authorization fell through the priority-20 generic state gate and answered `ERR_RMA_INVALID_STATE`. PRD §3.2: "Once an authorization is `EXPIRED`, any attempt to receive against it or reissue it fails with `ERR_RMA_EXPIRED`". Made the expiry answer outrank the generic state answer on exactly these two endpoints.
- `services.py` (`recall_cascade`, link three) — the mandatory-recall sweep abandoned the live work order but left the line stranded in `IN_REFURB`, a dead-end state with no remaining exit. PRD §2.9: "a line routed to refurbishment leaves `DISPOSITION_ASSIGNED` for `IN_REFURB` and comes back to `DISPOSITION_ASSIGNED` when the work order closes", plus §3.5's abandonment definition. The swept line now returns to `DISPOSITION_ASSIGNED` with refurbishment availability forced false (link one's `DESTROY` already pinned).
- `routes/lines.py` (`reverse_refund`) — the `REVERSAL` ledger entry's memo dropped the caller's text. PRD §3.7: the entry's "memo carries the supplied text". Now includes `reversal_memo`.

### Notes for the record
- No flakiness was observed at any iteration — all three sweeps produced byte-identical pass/fail sets across their 8 concurrent rounds, so no load-induced or timing-sensitive defect is hiding here.
- No assertion was weakened to an HTTP-status check, no `skip`/`xfail` was added, no PRD-required implementation check was removed, and no endpoint, response field or seeded data was added that does not trace to a verbatim PRD sentence.
- I did not touch `worklog.md`; `workspace/.scratch_step7/` has been removed.

**Orchestrator verification**: independently parsed all 8 `results.*.json` — every round reads `passed 139 / failed 0 / errors 0 / skipped 0 / total 139`. Test function count is still 139, matching Step 5's output exactly, which corroborates the "zero deletions" claim. Zero `pytest.mark.skip`/`xfail` markers in `test_suite/`. Also independently observed the iteration-1 baseline myself (122/139 identical in all 8 rounds) before the agent began diagnosing, confirming the deterministic, non-load-induced failure set.

Step 8 is NOT skipped: Step 7 applied 5 `implementation/` fixes (plus test-layer fixes), so PRD.md left behaviours unpinned that the implementation has now committed to.

## Step 8: Finalize PRD — 2026-09-05T21:19:00.000Z

## Result

`workspace/PRD_FINALIZED.md` written: **439 lines / 117,670 bytes** vs PRD.md **439 lines / 116,732 bytes** — 3 of 439 lines revised (0.68% of lines, +0.80% bytes). File ends on the same final error-catalogue row (`ERR_REFUND_EXCEEDS_EXPOSURE_CAP | 409`); PRD.md, `implementation/`, `test_suite/`, `test_helpers/` and `worklog.md` untouched; no scratch dir created.

### Change set (3 edits, one per Step-7 impl fix)

- **§2.1 (line 21) — revise** — `released_by_user_id` is now stated to live *both* on refund releases and on the `ReturnLine` whose refund is released, null on each until a release stamps it — `serialize.py:161` + `serialize.py:247`, `routes/lines.py:176,179`, `routes/receipts.py:158`, `services.py:201`.
- **§2.6, priorities 19–27 (line 110) — insert** — priority 20 now defers exactly one status, `EXPIRED`, to priority 21 on the two endpoints priority 21 guards (receipt creation, reissue), so those answer `ERR_RMA_EXPIRED`; every other authorization action still reports `ERR_RMA_INVALID_STATE` for `EXPIRED`. This removes the standing PRD self-contradiction between the ladder and §3.2's verbatim sentence — `routes/receipts.py:51-60`, `routes/rma.py:212-218`.
- **§3.8, recall link three (line 291) — insert** — a line whose live work order the mandatory-recall sweep abandons returns from `IN_REFURB` to `DISPOSITION_ASSIGNED` with refurbishment availability forced false, version advancing a second time, grade/recovery/refund untouched, link one's `DESTROY` standing — `services.py:377-388`.

### Pre-edit search log (NO-NEW-MISMATCH)

1. **§2.1 edit** — (a) subject: placement/stamping of the six opaque role identity fields, `released_by_user_id` in particular. (b) enumerated: grep of `released_by_user_id|released_at|reversed_at` across all impl modules (6 sites, both rows); serializers for receipt/line/work-order/order/refund (`serialize.py:120-251`) to confirm the sentence's other claims still hold — `scanned_by_user_id` receipt-only, `graded_by_user_id` line-only, `assigned_technician_user_id`/`qa_user_id` work-order-only, `approved_by_user_id`/`executed_by_user_id` order-only; `deny_refund` (`lines.py:191`) and `reverse_refund` (`lines.py:216`) checked — neither stamps nor clears the field. (c) adjustment: scoped the addition to "the `ReturnLine` whose refund it releases" so denial and reversal are not implied, and added the "null until a release stamps it" clause rather than touching §3.3's opening-value list.
2. **§2.6 edit** — (a) subject: relative rank of `ERR_RMA_EXPIRED` vs `ERR_RMA_INVALID_STATE`. (b) enumerated: every raise site of both codes (`routes/rma.py:114` declare-line, `:173` issue, `:192` void, `:213/215/218` reissue; `routes/receipts.py:55/57/60` create-receipt) plus `errors.py:33-34`; confirmed only the two endpoints invert, and that declare/issue/void still answer `ERR_RMA_INVALID_STATE` for an `EXPIRED` source. (c) adjustment: added the explicit "on every other authorization action … ordinary priority-20 violation" clause so the exception cannot be read as global.
3. **§3.8 edit** — (a) subject: `disposition_state` transitions out of `IN_REFURB` and the forced-false refurbishment availability. (b) enumerated: all eight writers of `disposition_state` and both writers of `_refurb_forfeited` (grep): scan init, quarantine, grade, `create_work_order`, `repackage`, `abandon`, `execute_cascade`, `recall_cascade`; read `refurb.py:200-216` (voluntary abandon re-runs the matrix) vs `services.py:377-388` (sweep does not re-run it), and `services.refurb_available` (`:249`). (c) adjustment: dropped an earlier "same exit as a voluntary abandonment" phrasing that would have implied a matrix re-run; stated the state move, forfeited availability and untouched grade/recovery/refund directly, and worded the anti-stranding clause so the deliberately unswept `OPEN` work-order case (which legitimately leaves its line in `IN_REFURB` with an abandonable order) is not contradicted.

### Considered and deliberately not patched

- **Lot-window fixture fix (§3.6)** — pure test-fixture bug; PRD already makes the window mandatory for non-restock orders and the impl answers the same `ERR_INVALID_REQUEST`. The impl does evaluate the *presence* half of that rule after the line's existence/posture/state/version guards and just ahead of the priority-30 recall lock (`dispositions.py:58-62`), rather than at priority 4 — logically unavoidable for a conditional field, unexercised by any test, and outside what this Step-7 item revealed. Flagging for Step 9 rather than pinning it here.
- **`client_code` 3–8 chars** (`shapes.req_code`, only used for `client_code`), **`released_at`/`reversed_at` on the refund release**, **ClientRep filter narrowing vs path rejection**, and the **`REVERSAL` memo** (`"refund reversed: " + text`, satisfying both §3.7's "carries the supplied text" and §3.8's "machine-generated … naming the triggering transition") are all already uniquely determined by existing PRD prose — left verbatim.

**Orchestrator verification**: `wc -lc` confirms 439 lines / 117,670 bytes vs PRD.md's 439 / 116,732; `diff` shows 6 changed lines (3 replaced pairs), so PRD_FINALIZED.md is genuinely distinct from PRD.md and not a byte-identical copy; `tail -3` confirms it still terminates on the final error-catalogue row. Step 8 was correctly NOT skipped because Step 7 applied 5 implementation fixes.

## Step 9: Complete PRD — 2026-09-05T21:56:00.000Z

**Orchestrator design decision (recorded per the autonomy directive).** Step 9 was executed as **four sequential passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module**, rather than as the single whole-repo scan the skill describes. Rationale: the implementation is 4,079 lines across 21 modules, and a single-pass exhaustive scan of that surface reliably exhausts a subagent's working room and returns a file byte-identical to its source — which is a silent pipeline failure, since a byte-identical PRD_COMPLETED.md means the scan never happened. Pass 1 performed the `cp`; passes 2-4 were explicitly forbidden to copy and were each told which subjects earlier passes had already pinned, so no pass re-litigated another's ground and no pass could clobber the shared file (targeted Edit calls only, never a whole-file Write). Partition:

- **Pass 1 — infrastructure/cross-cutting** (app, db, errors, response, middleware, shapes, refs, constants, query, serialize; 1,325 lines): 12 ambiguity-pins + 2 mismatch-revisions.
- **Pass 2 — calculations/aggregates/services** (calc, aggregates, services; 977 lines): 10 ambiguity-pins + 3 mismatch-revisions.
- **Pass 3 — routes part 1** (clients, catalog, rma, receipts; 902 lines): 10 ambiguity-pins + 5 mismatch-revisions.
- **Pass 4 — routes part 2** (lines, refurb, dispositions; 875 lines): 17 ambiguity-pins + 10 mismatch-revisions.

**Totals: 69 edits — 49 ambiguity-pins, 20 mismatch-revisions.** Each pass handed its out-of-partition findings forward as an explicit leftover list, and pass 4 returned a verdict on every one (see below), so nothing was dropped between partitions.

### Pass 1 change set (infrastructure)
- §2.1 ClientRep scoping — insert — a `client_id` *query filter* naming a foreign client is silently overridden (own rows, no 403) while a nonexistent one still 404s; collections without a `client_id` column are narrowed by walking the parent chain — `middleware.py:45`, `routes/receipts.py:191`, `refs.py:36`.
- §2.2 — insert — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9`, regenerated per response including errors — `response.py:14`.
- §2.2 — insert — pagination `meta` keys are absent (not null) on object/error responses; `has_more` = `offset + len(data) < total_count` — `response.py:47`.
- §2.2 — insert — `message` wording is non-contractual; only `error_id` + status bind — `errors.py:9,73`, `shapes.py:12`.
- §2.3 — **revise (mismatch)** — `limit`/`offset` bounds are enforced by **clamping**, never rejection; unparseable/empty falls back to 10/0; `meta` echoes effective clamped values — `response.py:97-125`.
- §2.3 — insert — `created_at` ties break by insertion order; filter applied before paging — `db.py:110`.
- §2.4 — insert — `updated_at` == `created_at` at creation; eight free-text reason/note fields are validated then discarded, `reversal_memo` surviving only inside the `REVERSAL` ledger memo — `db.py:123`, `serialize.py:*`.
- §2.4 — insert — the logical clock has no monotonicity guard; may be set backward or to its current value, re-running the sweep — `db.py:88`.
- §2.5 — insert — percentages travel as JSON **numbers**, so rendered width may be shorter than declared scale (`0.30`->`0.3`) — `serialize.py:9`.
- §2.6 p3 — insert — priority 3 precedes shape validation only for a body `client_id` resolving to a *real* foreign client; unknown ids fall to p5 — `middleware.py:52`.
- §2.6 p4 — insert — the whole priority-4 layer: `null` ≡ absent; absent body ≡ `{}`; strings non-empty after trim; no int/bool coercion; percentages quantized half up rather than rejected; instants normalised to UTC with 3 fractional digits; enum arrays de-duplicated in first-supplied order — `shapes.py:22-199`.
- §2.11 — insert — filters are trimmed exact matches, empty ≡ absent, non-member enum matches nothing (200 + empty array), booleans accept `true/1/yes`/`false/0/no`, conjunctive, duplicates take the first — `query.py:6-29`.
- §4 preamble — **revise (mismatch)** — impl never resolves `X-User-ID`, so only missing/empty headers or an undeclared role are 401; an unknown `ClientRep` id authenticates and owns nothing — `middleware.py:22-36`.
- §5 preamble — insert — three uncatalogued transport codes (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500), added to the intro paragraph so the file still ends on the required final table row — `app.py:33-50`.

### Pass 2 change set (calc/aggregates/services)
- §3.3 — **revise (mismatch)** — the `SERIAL_MISMATCH` row is always written (a zero-point `PASS` noting the item is unserialized), reconciling PRD's own "precisely two rows" claim — `services.py:109-120`.
- §3.4 — insert — the quarantine overlap scan covers every other line with both instants set in that bay, no state filter, no regard to the clock, so a historical occupation reserves that interval indefinitely — `services.py:419-430`.
- §3.4 — revise+insert — the overridden disposition is not an input to the provisional formula; the `RefundRelease` is recomputed and re-stamped, advancing `version`, despite identical amounts — `services.py:209-227`.
- §3.5 — **revise (mismatch)** — test-window overlap is **half-open** on the buffer-widened interval (matching p56), so with `buffer_minutes` 0 abutting windows do not collide; scan ignores work-order `status` — `services.py:433-447`.
- §3.6 — insert — the frozen per-unit quotient is **not** pre-rounded before the index; exact quotient x `price_index_pct` rounded once, unlike the restock price — `calc.py:183-191`.
- §3.6 — insert — a projection is gross less fee only (no refurb cost); `DONATE`/`DESTROY` candidates project zero, qualifying only at `min_lot_value_cents` 0 — `calc.py:186-187`, `services.py:504`.
- §3.6 — insert — a `DONATE`/`DESTROY` execution lands in the small-lot band, reporting a non-zero `effective_fee_pct` against a zero `channel_fee_cents` — `calc.py:194-217`.
- §3.6 — insert — re-indexing re-stamps the channel and advances its `version` on every accepted report, even when the index is unchanged — `routes/dispositions.py:277-287`.
- §3.7 — insert — each recomputation stores the **greater** of stored and freshly summed fraud score, making it monotonically non-decreasing — `services.py:163-170`.
- §2.10 — insert — auto-reinstatement fires only on a reversal; auto-suspension runs on every append; both only from the opposite status; suspension is strict below the negated cap while reinstatement accepts equality — `aggregates.py:37-68`.
- §3.8 — insert — recall link one writes `disposition` only (no state/grade/recovery/refund recompute, matrix not re-run), the set is collected `created_at` ascending, and each link completes across the whole set before the next — `services.py:345-391`.
- §3.8 — insert — a ledger `memo`'s exact wording is server-chosen and non-contractual, the sole constraint being the `REVERSAL` embed — `aggregates.py:37-50`.
- §3.8 — insert — the six disposition counts count **lines**, not units, with no state filter, so they sum to the client's total return lines — `routes/clients.py:140-141`.

### Pass 3 change set (routes clients/catalog/rma/receipts)
- §2.6 p4 — insert — all five uniqueness collisions answer `ERR_INVALID_REQUEST`, tested *after* every existence/scope/state gate (so a duplicate `tracking_reference` on an expired RMA yields `ERR_RMA_EXPIRED`); only `client_code` is pattern-checked.
- §2.6 p5-17 — **revise (mismatch)** — "path first, then body" replaced by the ascending-numeric-priority rule, naming the two endpoints where a body FK outranks the path id — `rma.py:106-107`, `receipts.py:121-122`.
- §2.6 p18 — revise — a declare-line `catalog_item_id` owned by another client answers `ERR_LINE_RMA_MISMATCH` — `rma.py:109-110`.
- §2.1 — **revise (mismatch)** — added authorization lines to the client-id-less collections whose narrowing walks the parent chain — `rma.py:154-155`.
- §2.10 — **revise (mismatch)** — the suspension-blocked set is exactly eight endpoints (grading was missing); replaced the false "one write remains available" claim — `services.py:78`.
- §2.10 — insert — suspend/reinstate have no state precondition (idempotent 200, still bumping `version`); reinstate and resume take no input — `clients.py:92-110`.
- §3.1 — insert — only `name`/`client_code`/`service_level`/`inventory_ownership` required; `max_refund_exposure_cents` may not be negative — `clients.py:33-47`.
- §3.1 — **revise (mismatch)** — `restock_grade_floor` accepts the full grade enum including `SCRAP` — `clients.py:37`.
- §3.1 — **revise (mismatch)** — `hazard_class` domain corrected to include `CORROSIVE` — `catalog.py:43`.
- §3.1 — insert — catalogue required-vs-optional list; `sku` uniqueness tested after `client_id` resolves — `catalog.py:35-50`.
- §3.1 — insert — recall notices have no state precondition and no monotonicity; walking back never undoes a forced `DESTROY`; re-filing `MANDATORY` re-runs the cascade — `catalog.py:98-108`.
- §3.1 — insert — all nine channel registration inputs required, no defaults; pause/resume have no state gate — `catalog.py:154-224`.
- §3.2 — insert — rollups are derived on read, so declaring a line leaves the parent's `updated_at`/`version` untouched — `rma.py:117-127`.
- §3.2 — **revise (mismatch)** — the `ERR_RMA_ALREADY_RECEIVING` test counts `Receipt` rows, not `received_unit_total` (§3.2 contradicted p22; impl follows p22) — `rma.py:219-220`.
- §3.2 — insert — reissue returns 201 with the replacement at `version` 1 and fresh line rows; no client-posture gate on reissue or void — `rma.py:225-252`.
- §3.3 — insert — scanning has no authorization-status/expiry gate (only client-ACTIVE), so a scan into a receipt whose RMA has moved on is accepted and re-derivation leaves that status untouched while still bumping `version` — `receipts.py:113-164`.

### Pass 4 change set (routes lines/refurb/dispositions)
- §2.3 — **revise (mismatch)** — shrink-ledger listing orders by `sequence_no`, then `created_at`, then insertion, so cross-client reads group by counter value — `dispositions.py:368`.
- §2.6 p36 — **revise (mismatch)** — dropped order execution from p36's guard list; execution's only identity separation is p35 dual signoff — `dispositions.py:213-219`.
- §3.4 — insert — an auto-denied line's `RefundRelease` is already at `version` 2 on first read — `lines.py:81-84`.
- §3.4 — revise — `override-disposition` accepts the full six-member enum incl. `PENDING`/`REFURBISH` — `lines.py:97`.
- §3.4 — **revise (mismatch)** — the `DONATE` refusal covers all three p32 conditions, not just `regulated_flag` — `lines.py:105-110`.
- §3.4 — revise — "unavailable once executed" has no separate test; it is the p23 state error — `lines.py:101-102`.
- §3.4 — **revise (mismatch)** — override cancels only orders whose frozen disposition now *differs*; an agreeing order stays live — `lines.py:119`.
- §3.5 — **revise (mismatch)** — wrong-state/wrong-disposition is `ERR_LINE_INVALID_DISPOSITION_STATE`; `ERR_LINE_NOT_REFURBISHABLE` is the p44 case only — `refurb.py:44-49`.
- §3.5 — **revise (mismatch)** — one-live-order-per-line is the p23 state gate, not a count; the forfeit flag gates only the matrix, so an override back to `REFURBISH` can open a second order — `refurb.py:44-49`.
- §3.5 — insert — `labor_minutes` required >= 0; `parts_cost_cents` optional >= 0 default 0 — `refurb.py:140-141`.
- §3.5 — **revise (mismatch)** — a zero `total_cost_cents` appends no `REFURB_COST` entry; `packaging_cost_cents` required >= 0 — `refurb.py:161,179`.
- §3.5 — insert — abandon leaves `recovery_value_cents` and the refund untouched; no duty separation, no recall bar — `refurb.py:200-215`.
- §3.6 — insert — echoed `disposition` restricted to the four orderable values; echoed `quantity` 1-999 — `dispositions.py:37-38`.
- §3.6 — insert — the echoed `disposition` *is* the input to p30/p32, which fire ahead of `ERR_DISPOSITION_DRIFT` — `dispositions.py:64-72`.
- §3.6 — **revise (mismatch)** — the conditional window *requirement* is evaluated after existence/posture/state/channel-status and the p29 OCC guard, so a windowless non-restock proposal answers `ERR_CLIENT_SUSPENDED`/`ERR_STALE_RETURN_LINE_VERSION`, not `ERR_INVALID_REQUEST`; only start<=end is p4 — `dispositions.py:58-62`.
- §3.6 — revise — second-live-order codes: `ERR_DISPOSITION_DRIFT` for `PROPOSED`/`APPROVED`, p23 state error for `EXECUTED` — `dispositions.py:48-51`.
- §3.6 — insert — a restock proposal's `channel_id` is still resolved (404) then discarded, no `ERR_CHANNEL_PAUSED`, null stored `channel_id`; supplied windows stored verbatim — `dispositions.py:43,54`.
- §3.6 — insert — the five specific channel errors are reachable only with an explicit `channel_id`; omitting it collapses them into `ERR_NO_ELIGIBLE_CHANNEL` — `dispositions.py:74-114`.
- §3.6 — insert — approve carries no input fields — `dispositions.py:182`.
- §3.6 — insert — `realized_unit_price_cents` >= 0; omitted or `null` falls back to the frozen price — `dispositions.py:202`.
- §3.6 — insert — execute step four takes the newest `REPACKAGED` work order by `created_at` — `dispositions.py:229-231`.
- §3.6 — insert — a line not in `HOLD_PENDING_DISPOSITION` gets no `release_eligible_at`; the line's `version` advances exactly 1 across the whole cascade — `dispositions.py:246-248`.
- §3.7 — insert — release carries no input fields — `lines.py:148`.
- §3.7 — insert — the exposure cap sums only *other* refunds whose line is currently `REFUNDED` — `lines.py:164-172`.
- §4 — insert — multi-row transitions return the path-addressed resource (7 return-line actions -> `ReturnLine`, 4 work-order actions -> `RefurbWorkOrder`, approve/execute/cancel -> `DispositionOrder`).
- §4 — **revise (mismatch)** — the clear-fraud-hold row described only the `RELEASE_PENDING` branch — `lines.py:133-139`.
- §4 — **revise (mismatch)** — the quarantine row's applicability is hazard/recall, not `regulated_flag` — `lines.py:42-43`.

### Pass 4's verdicts on the six cross-partition leftovers
1. **Exposure-cap arithmetic — PINNED** (§3.7 release paragraph): cumulative released is read out of live state, so `CLAWED_BACK` stops consuming and `DENIED` never consumes.
2. **`override-disposition` enum breadth — PINNED** (§3.4), with its sibling (the proposal *echo* restricted to four orderable values) pinned in §3.6.
3. **Capacity-before-min-lot and the `ERR_CHANNEL_NOT_HAZARD_CERTIFIED` reuse — JUDGED ALREADY-DETERMINED** by §2.6's strictly-ascending-priority sentence (p57 < p60) and by p34's existing wording respectively.
4. **Grading's matrix-before-`build_refund` order — JUDGED UNOBSERVABLE, no pin**: `run_matrix` writes only `line["disposition"]`; `build_refund` reads a disjoint field set, so no answer can change.
5. **Global shrink-ledger `sequence_no` sort — PINNED** (§2.3, final ordering sentence).
6. **Pricing-feedback window ordering — JUDGED ALREADY-DETERMINED**: the impl's ascending sort + last-3 slice selects the same set as the PRD's "newest three by `sequence_no` descending", and a mean is order-independent.

### Pass 4's completeness judgement
Step 9 is complete for observable behaviour. Three residual items were deliberately left, none an implementation mismatch: (a) §3.6 says "Four fields are optional" then lists five names because the window pair counts as one — internal prose arithmetic, no behavioural ambiguity; (b) §2.6 p3's "every endpoint whose authorized roles include `ClientRep`" is narrowed by §2.1's explicit ten-type enumeration, which omits `PricingFeedback`; (c) three impl branches are unreachable dead code (`ERR_REFUND_RELEASE_NOT_FOUND` on release/reverse, `ERR_CATALOG_ITEM_NOT_FOUND` on work-order creation, and the `release_eligible_at is None` arm of the hold test) — the PRD was left silent rather than documenting behaviour no request can reach.

**Orchestrator verification**: `wc -lc` gives PRD.md 439/116,732, PRD_FINALIZED.md 439/117,670, PRD_COMPLETED.md 439/144,111 — so PRD_COMPLETED.md is **+26,441 chars over PRD_FINALIZED.md and demonstrably NOT byte-identical** to it (98 changed lines / 49 hunks), which is the signal that the scan genuinely ran. `diff` of the heading lists of PRD.md and PRD_COMPLETED.md is empty, confirming all 69 edits are in-paragraph with no section added or removed. `tail -2` confirms the file still ends on the final error-catalogue row `| ERR_REFUND_EXCEEDS_EXPOSURE_CAP | 409 |`, so nothing was truncated across four passes. Grep for "harder than expert"/"expert level" returns zero — the Step 2 difficulty directive never reached any PRD variant. No `.scratch_step9_*` directories remain.

## Pipeline complete — 2026-09-05T21:56:00.000Z

All nine steps finished. Final state: 139/139 tests passing in all 8 rounds of the last stability sweep (`workspace/implementation/results.{1..8}.json`, each `passed 139 / failed 0 / errors 0 / skipped 0`), zero tests deleted, and the full PRD chain PRD.md -> PRD_FINALIZED.md -> PRD_COMPLETED.md present in `workspace/`.
