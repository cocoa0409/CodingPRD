# Worklog — task_2771_government_surplus_property_disposal

## Step 1: Create task directory — 2026-09-04T19:13:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2771_government_surplus_property_disposal` and its `workspace/` subdirectory. Index 2771 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-04T21:18:00.000Z

Task complete. All three scaffold artifacts for task 2771 exist and pass lint.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2771_government_surplus_property_disposal/`):

| file | lines | bytes | top-level key(s) |
|---|---|---|---|
| `SCAFFOLD.yaml` | 3181 | 158006 | scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2890 | 187269 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6494 | 393176 | `scaffold_corner_design` only |

**What was finished this session** — the remaining `SCAFFOLD_CORNER_DESIGN.yaml` sections, written with chunked `cat >>` appends and YAML-parsed after each chunk:
- `rbac` completed to 9 instances (added the closer-vs-poster segregation pair on `POST /proceeds-distributions/{id}/post`, bidding/deposit exclusivity vs the three staff roles, AgencyOfficer and Bidder cross-scope refusals with `ERR_FORBIDDEN_AGENCY_SCOPE` / `ERR_FORBIDDEN_BIDDER_SCOPE`, and a shared-operation instance driving all five multi-role endpoints from both declared roles).
- `cross_cutting_complexity_layers` (6): two optimistic-concurrency instances (`ERR_STALE_ASSET_VERSION` with priority 10 `ERR_FUTURE_DATE` outranking it; `ERR_STALE_LOT_VERSION` sandwiched between priority 13 not-found and priority 88 basis-availability), a `selector_policy` instance where the close-time selector skips a RETRACTED top bid, a pagination/filter-composition instance including the three `ERR_INVALID_PAGINATION` bounds, plus two stubs citing `tc_bidder_debarment_five_hop_unwind` and `dv_asset_value_transfer_basis_vs_auction_reserve`.
- `consistency_model` (2): read-your-writes across the whole sale chain, and cross-aggregate visibility of the single release call's three-aggregate cascade through filtered list reads.

Final section census: entities 16, state_machines 22, calculations 15, validations 26, endpoints 4, errors 3, rbac 9, cross_cutting_complexity_layers 6, consistency_model 2 — 103 instances (79 with full `test_recipe`, 24 stubs citing §1.8 instances by name).

One forbidden-vocabulary hit found in a final sweep and fixed: "violates all three rules simultaneously" -> "violates all three rules in one payload" in `SCAFFOLD_DIFFICULTY_DESIGN.yaml:1537`. Re-grep for the banned phrase list now returns nothing across all three files.

Lint verdict (re-run after that edit), verbatim:

```
  SCAFFOLD:           tasks/task_2771_government_surplus_property_disposal/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2771_government_surplus_property_disposal/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2771_government_surplus_property_disposal/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     14
  §1.8 instances scanned:     24
  §1.9 instances scanned:     79
  Calls scanned (§1.8+§1.9):  1458

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Constraints honoured: no sibling task directory was read at any point; nothing was written into `workspace/` and `worklog.md` was not created or modified; no single giant Write was used.

Orchestrator verification: all three files present; `grep -n "harder than expert" SCAFFOLD.yaml` returns nothing, so the difficulty directive did not leak into the scaffold's scenario key.

## Step 3: Copy shared files — 2026-09-04T21:19:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T21:40:00.000Z

The PRD is complete and verified.

**Output:** `workspace/PRD.md` — 495 lines, ~104 KB, written in nine chunked appends. Structure: §1 Introduction, §2.1–§2.13 (RBAC, verbatim response envelope, pagination, logical clock, identity/version counters, money & rounding, OCC, the two lifecycle axes, cascades & ordering, segregation of duties, path resolution, validation precedence, conserved quantities), §3.1–§3.9 (registries; turn-in intake; assessment/valuation/federal use period; screening ladder; transfer orders & tier pricing; auction listing & bidding; lot close, invoice settlement, default, debarment; clearance/demil/release; proceeds distribution & ledger), §4 with all 62 endpoints, §5 with all 58 error codes. File ends at the final error row — no truncation, no audit footer, worklog.md untouched, and neither withheld design file was opened.

**Field coverage check:**
- entities[].fields: 124 required, 124 present, 0 missing
- endpoints[].request_body: 71 required, 71 present, 0 missing
- endpoints[].query_params: 24 required, 24 present, 0 missing
- Status: PASS

**Rule coverage check:**
- validations[] with priority: 51 checked, 51 expressed in prose, 0 missing (47 unique error ids, all present in §2/§3 body text ahead of the §5 table; all 58 catalogue ids likewise appear in the body)
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (`expected_asset_version` -> `ERR_STALE_ASSET_VERSION`, `expected_auction_lot_version` -> `ERR_STALE_LOT_VERSION`, both 412), 0 missing
- state_machines[].transitions: 75 checked across 13 machines, 75 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed with constants, evaluation order and precision, 0 missing
- validations[] conditions: 51 checked, 51 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 62 endpoints checked, all side effects and both scope-restriction enumerations expressed, 0 missing
- entities[].fields[] structured content: 84 enum values, defaults, constraints and null-initialisations checked, all reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (3 tier factors, 3 handling-fee bands, 7 condition factors, 3 service-fee slices, 2 distribution bases, 2 close outcomes, default vs void, 2 release source states, 4 destruction source states), 0 asymmetric
- Status: PASS

**Path purity check (§3 only):**
- backtick tokens scanned: 1052 (278 unique)
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0 (no token in §3 contains a slash at all)
- Status: PASS

One scaffold inconsistency carried forward as a deliberate decision: `ERR_LEDGER_WOULD_GO_NEGATIVE` appears in the `ProceedsDistribution` `POSTED` -> `REVERSED` preconditions but is absent from the scaffold's `errors[]` catalogue. It is stated in §3.9 prose as a 409 Conflict but has no §5 row, since §5 is generated strictly from `errors[]`.

Orchestrator truncation check (per the known doc-generator failure mode): `tail -20 PRD.md` ends on the final `| ERR_DISTRIBUTION_ALREADY_POSTED | 409 |` row of the §5 table — a real section boundary, not mid-sentence. `grep -c "^| \`ERR_"` = 58, matching the declared catalogue size. Section headings present: §1–§5, all top-level. No regeneration needed. Leak check for "harder than expert" / "expert level" / "SCAFFOLD" in PRD.md returns nothing.

## Step 6: Generate implementation — 2026-09-04T22:35:00.000Z

Implementation complete.

## What was produced

`workspace/implementation/` — 3,107 lines across 25 files, all `py_compile`-clean:

- `start.sh` (executable, guarded `pip install`, `exec python3 app.py`), `requirements.txt`
- `app.py` — registers all 12 route modules, `ApiError` / `HTTPException` / generic handlers emitting the error envelope, `app.run(host="0.0.0.0", port=int(os.environ["PORT"] or 10000))`. **No seeding** — verified the 14 store dicts are empty at import and the logical clock reads exactly `2026-08-01T00:00:00`.
- `db.py`, `response.py`, `middleware.py`, `errors.py`
- `services/` — `enums.py`, `calc.py`, `serialize.py`, `rollups.py`, `cascades.py`
- `routes/` — `agencies, turnins, assets, release, screening, transfers, venues, lots, bidders, invoices, finance, clock`

## Modules finished this session

`routes/bidders.py`, `routes/invoices.py`, `routes/finance.py`, `routes/clock.py`, `app.py`, plus two corrections traced back to PRD prose: bidder `email` uniqueness is now case-insensitive (PRD §3.6), and `rollups.recompute_bidder_wins` now counts only the bidder's `WINNING` bids (the extra lot-status filter contradicted the +1-at-close / -1-per-retraction semantics of PRD §3.7).

## Verification

**Endpoint coverage: 62 routes registered = 62 rows in the PRD §4 table = 62 `method:` entries in SCAFFOLD §1.5.**

Two end-to-end smoke runs on a self-chosen port (51771, killed afterwards by recorded PID; port confirmed free) exercised and matched hand-computed expectations for:
- full happy path agency -> turn-in -> asset -> assessment -> submit -> accept -> de-minimis lot -> open -> bidder register/deposit/bid -> close -> invoice -> settle -> distribution -> post -> reverse -> release
- invoice pricing: hammer 30,000 -> premium 3,000 -> tax on 33,000 = 1,650 -> total 34,650 (pinned per-line rounding), `due_at` = `closed_at` + 7 days
- marginal service fee: 34,650 x 0.125 = 4,331.25 -> 4,331 (ROUND_HALF_UP)
- `lot_number` = `NY<code>-0001` (4-digit zero pad)
- deposit custody identity `paid = held + applied + forfeited` held after deposit, partial payment with `use_deposit`, and default forfeiture
- `ERR_PAYMENT_EXCEEDS_BALANCE` on cash+deposit overshoot; premature `default` on/before `due_at` -> 409; `ERR_SEGREGATION_OF_DUTIES` when the lot closer posts the distribution; `ERR_STALE_LOT_VERSION` on a second create against the same lot version; prior `CALCULATED` -> `SUPERSEDED`; CASH base 7,000 vs ACCRUAL base 10,000 on the same defaulted lot; post/reverse ledger returning to 0/0 exactly
- full debarment cascade: bidder `DEBARRED`, `winning_lot_count` 0, deposit returned to held, lot `CLOSED_NO_SALE` with `high_bid_cents`/`bid_count` re-derived to 0, invoice `VOIDED` with `void_reason="WINNER_DEBARRED"`, asset `SOLD` -> `AUCTION_ELIGIBLE`, then `DEBARRED` terminal -> 409

## Spec judgements worth flagging

1. **`amount_cents > 0` on payments** returns `ERR_PAYMENT_EXCEEDS_BALANCE` (422), not `ERR_INVALID_REQUEST`. PRD §3.7 groups the positivity requirement into the same sentence as the two overshoot rules, and SCAFFOLD validation priority 86 states the check literally as "`amount_cents` must be > 0 and <= `balance_due_cents`" with that error id. This is the one genuinely ambiguous precedence call in the new modules.
2. **AgencyOfficer list narrowing not implemented.** SCAFFOLD role notes (line 3119) claim `GET /proceeds-distributions`, `GET /screening-requests` etc. are "narrowed to its own agency", but PRD §2.1 enumerates the scope-checked operations exhaustively and includes only *single*-row reads. PRD wins, so list endpoints return unnarrowed rows.
3. **Scope-before-existence** where the scope key is the path id itself (agency read, bidder read, bidder bids, deposits — precedence 5 outranks 11); **deferred until after resolution** where the key lives on the row (invoice read/payment, transfer order, screening request), since resolution is a precondition of the comparison.
4. `ERR_LEDGER_WOULD_GO_NEGATIVE` (409) is implemented for reversal even though it appears only in PRD §3.9 prose and in neither error catalogue.

## Step 5: Generate unit tests — 2026-09-04T22:50:00.000Z

Stage 2 complete. Final report:

## What was built

**Stage 1 — `test_helpers/`** (9 files, ~2,570 lines): `types.py` (27 enums + 14 entity TypedDicts), `api_client.py` (`ApiClient` with one method per endpoint), `api_errors.py` (58 error ids + HTTP status map registered with the framework), `constants.py`, `factories.py`, `test_users.py`, `assertions.py` (per-entity + 5 invariant helpers), `fixtures.py` (5-tier composite setup chains), `__init__.py` barrel.

**Stage 2 — `test_suite/`**: `conftest.py` + **18 test files, 198 tests, 16,641 lines**, produced by 10 parallel translators over disjoint files with `test_helpers/` frozen (so no shared-file conflicts).

| queue | files | tests |
|---|---|---|
| A (difficulty) | `test_01`-`test_08` | 79 |
| B (corner) | `test_10`-`test_19` | 119 |

## Coverage and audit

- **103 / 103 non-stub design instances covered.** All 24 difficulty instances have >=2 tests (range 2-6); all 79 corner instances >=1. **Zero instances skipped entirely.**
- The 24 `excluded_because:` corner stubs produced no output; their `difficulty_instance:` cross-references were verified to resolve (24/24, none dangling).
- **Design-citation pass** (script at `/tmp/task2771_audit.py`, exit 0): every test has exactly one `Design:` line, it is the last docstring line, and it resolves to a real non-stub instance. No stub-pointing tags, no `skip`/`skipif`/`xfail` anywhere.
- **PRD-citation pass**: every one of the 198 docstrings contains a >=8-word span that survives literal whitespace-normalised matching against `workspace/PRD.md`.
- **Interface cross-check**: 0 missing `test_helpers` exports, 0 missing `ApiClient` methods, 0 missing `ApiErrorId` members across all 18 files; all 28 `.py` files `ast.parse` clean.
- Constraints honoured: nothing written under `workspace/` (still only `INSTRUCTION.md`, `PRD.md`, `implementation/`), no stray `test_helpers/`/`test_suite/` there, `worklog.md` untouched by me or my translators, no pytest/server/`pkill`.

## Findings that matter for Step 7

1. **Timestamp precision trap pre-empted.** PRD §2.4/§2.5 mandate three fractional digits on instants, the design indices write them bare, and `test_helpers` has no canonicaliser. All 18 files independently compare instants via private `_instant` helpers; a grep confirms **zero** bare-second string-equality comparisons suite-wide. Consider adding a canonicaliser to Stage 1 for future tasks.
2. **PRD defect: `ERR_LEDGER_WOULD_GO_NEGATIVE`** is specified in §3.9 prose with "(HTTP 409 Conflict)" but is **absent from the §5 error catalogue** — reported independently by four translators. Worth fixing in Step 8/9. `api_errors.py` already registers it at 409.
3. **Design-index literals that contradict the PRD; translators followed the PRD** (so tests are PRD-faithful and the index is what's wrong): several absolute `version` counts omit mandated bumps (screening-cycle version after a filing that recomputes `open_request_count`; asset version 4 vs 5 on the release chain; lot version after a distribution create, where §3.9 explicitly says it increments); `reserve_source: "DERIVED"` is not a PRD value (`COMPUTED`); `ERR_ASSET_NOT_ASSESSABLE` where §3.2 derives `ERR_INVALID_STATE`; a body-FK 404 expected where §2.12 ranks conditional-field checks higher; `ERR_BIDDER_NOT_FOUND` unreachable as a body-FK failure because bidder own-row scope sits at priority 5; `ERR_BIDDER_NOT_REGISTERED` where the closed lot's state outranks bidder standing. Affected tests assert version *deltas* rather than absolutes where the absolute is contested.
4. **Sub-assertions dropped under Silence rules** (instance still covered): venue reopen-via-status (endpoint's input enum set undeclared), the debarment cascade's invoice `deposit_applied_cents`/`amount_paid_cents` hybrid (matches neither faithful reading), `created_at` fractional width, `remarks` null default, absence of PATCH/PUT/DELETE routes, pre-close roll-up after a retracted bid, `OUTBID` at bid placement.
5. **Two further PRD gaps**: `POST /sale-invoices/{id}/payments` has no derivable success status (no `Payment` entity), so those calls use the lenient `get_success_data`; and the PRD defines no idempotency-key mechanism at all, so nothing was emitted for one.
6. Cosmetic: `test_15_validation_rules_disposal.py` is 1,118 lines (over the ~700-line guidance) because of mandatory full-sentence citations; no instance was dropped to fit.

Orchestrator note: Steps 5 and 6 were launched in separate messages rather than one, so the impl generator's physical isolation from `test_suite/` was not guaranteed by absence alone; it was instead enforced by an explicit absolute prohibition in the Step 6 prompt against reading `test_helpers/`, `test_suite/`, or either design yaml. The impl agent's own report cites only INSTRUCTION.md, SCAFFOLD.yaml, and PRD.md as sources.

## Step 7: Run tests and iterate — 2026-09-04T23:07:00.000Z

Clean sweep. Final state verified: `worklog.md` untouched, no stray test dirs under `workspace/`.

## Summary

**Iterations run:** 2 (iteration 1: 205/214 passing in all 8 rounds with 9 identical failures — deterministic, not flaky; iteration 2: **214/214 passing in all 8 rounds**).

**Tests deleted:** none. Every one of the 9 failures traced to a verbatim PRD sentence, so all 9 survived STEP 1a/1b and were resolved as either test-faithfulness bugs (STEP 2) or an implementation defect (STEP 3).

**Fixes applied to `test_helpers/`:** none — no fixture, factory or header builder was at fault.

**Fixes applied to `test_suite/`** (STEP 2 — each makes the test *more* faithful to PRD):

- `test_02_lifecycle_state_machines.py` — added the missing `assert_clearance_certificate` import (the helper existed in `test_helpers/assertions.py`; the test crashed with `NameError` before reaching any assertion).
- `test_06_cross_entity_dependencies.py` :: `test_asset_creation_on_submitted_turn_in_rejected` — the roll-up re-read called `GET /assets` as `AgencyOfficer`, a role PRD §4 does not list for that endpoint; switched to `ProgramAdmin`. The 403 was the implementation being correct.
- `test_13_endpoint_surface.py` :: `test_clock_action_stamps_no_entity_and_returns_an_empty_data_object` — same class of bug: `GET /turn-ins` called as `AgencyOfficer`, which PRD §4 authorises only for `ProgramAdmin`/`DisposalOfficer`/`SurplusAssessor`. Switched to `ProgramAdmin`.
- `test_11_state_machine_corners.py` :: three tests (`test_submit_moves_draft_to_submitted_and_opens_the_assessment_gate`, `test_accept_of_a_turn_in_with_an_unvalued_asset_is_refused`, `test_second_submit_is_refused_and_does_not_restamp_submitted_at`) — all hardcoded turn-in versions on the assumption that asset creation does not mutate the parent. PRD §2.5 says version increments "on every mutation of that row ... **including recomputation of derived fields**", and §3.2 has asset creation recompute `asset_count`, so the parent legitimately reaches version 2 before submission. Rewrote as relative assertions anchored on the live version, preserving the actual rule under test (a *refused* operation applies no hops).
- `test_11_state_machine_corners.py` :: `test_rejected_turn_in_refuses_every_further_trigger` — sent `expected_asset_version=2` after the rejection cascade had already moved the asset to `RETAINED` (version 3), so the server correctly answered `ERR_STALE_ASSET_VERSION`, which PRD §2.12 ranks at level 14, ahead of the level-16 state codes the probe was after. Now reads the asset's live version so the intended state gate is what gets exercised.
- `test_14_validation_rules_intake.py` :: `test_dates_equal_to_the_clock_date_pass_and_the_next_day_fails` — expected asset version 2 after both an accepted assessment *and* an accepted clearance certificate. PRD §3.8: "Each accepted certificate ... increment[s] the asset's `version` by 1 either way." Corrected to 3.

**Fixes applied to `implementation/`:**

- `workspace/implementation/errors.py`, the `STATUS` map — the key was misspelled `ERR_INVOICE_NOT_FOUND` instead of PRD §5's `ERR_SALE_INVOICE_NOT_FOUND`. The routes raised the correct id, but it missed the table and fell through to `ApiError`'s 400 default, so every unresolvable sale-invoice path answered HTTP 400 with a 404-family `error_id`. I then diffed the full `STATUS` map against PRD §5 programmatically (58 catalogue rows) and against every `ERR_*` literal in the implementation: no other id is missing, mis-statused, or referenced-but-unmapped.

Orchestrator verification (per the "Step 7 subagent may claim a sweep it did not run" hazard): I read the 8 result files myself. Baseline sweep at 22:44 showed 205/214 in every round; the final sweep at 23:07 shows `passed == total == 214` in all of results.1..8.json. Step 8 is NOT skipped — Step 7 applied 1 `implementation/` fix and 7 `test_suite/` fixes.

## Step 8: Finalize PRD — 2026-09-04T23:10:00.000Z

`PRD_FINALIZED.md` is written. Two edits, both tracing to the same Step 7 finding (the three rewritten `test_11` version tests).

**Size:** PRD.md 495 lines / 104,320 B -> PRD_FINALIZED.md 495 lines / 104,835 B (line delta 0%, byte delta +0.49%).

## Changes

- **§3.2 (asset creation)** — *insert* — after "recomputes the parent turn-in's `asset_count`", added that this recomputation is itself a mutation of the turn-in row in the sense of §2.5, refreshing `updated_at` and incrementing the turn-in's `version` by 1 even though `status` does not move, so a `DRAFT` turn-in with one item already stands at `version` 2 before submission — `implementation/routes/assets.py:107` -> `implementation/services/rollups.py:82-90` -> `implementation/db.py:157-167`.
- **§3.3 (assessment recording)** — *insert* — the sentence "the parent turn-in's `appraised_total_cents` is recomputed" now also states that this recomputation refreshes the turn-in's `updated_at` and increments the turn-in's `version` by 1, exactly as adding an item does — `implementation/routes/assets.py:179` -> `implementation/services/rollups.py:82-90`.

## Pre-edit search log

**Edit 1** — (a) Subject: whether recomputing a parent `TurnIn` roll-up bumps that parent's `version`/`updated_at`, and specifically the turn-in version trajectory around asset creation. (b) Enumerated: `grep -rn "recompute_turn_in\|bubble_up_turn_in" implementation/` -> exactly three callsites (`routes/assets.py:107` asset creation, `routes/assets.py:179` assessment recording, `routes/turnins.py:105` review/ACCEPT) plus the `bubble_up_turn_in` callers (`services/cascades.py:51`, `routes/release.py:97`); read `services/rollups.py` in full (`recompute_turn_in`, `revalue_asset`, `bubble_up_turn_in`, `evaluate_clearance`), `db.py` `Touched.touch` (per-request dedupe, so one operation bumps a row at most once), `routes/assets.py` in full (create/assess/certificate), `routes/turnins.py:64-115` (submit does *not* recompute; review/ACCEPT recomputes then touches once -> +1; REJECT touches turn-in once and each `INTAKE`/`ASSESSED` child once), and `grep -n "asset_count" PRD.md` (lines 134, 203, 211, 221). (c) Adjustment: scoped the claim to "that recomputation ... in the sense of §2.5" rather than asserting a new universal rule, so `submit` (+1, no recompute), `review` (+1 total, not +2 despite recompute-then-touch) and the upward `ACCEPTED -> CLOSED` closure all remain correctly described. Also verified `appraised_total_cents` cannot change during `DRAFT` (assessment requires `SUBMITTED`), so `appraised_total_cents` was deliberately not named here.

**Edit 2** — (a) Subject: the same parent-recompute-bumps-parent-version rule at the §3.3 site, added to avoid an expressio-unius reading where §3.2 states it and §3.3's silence implies the opposite. (b) Enumerated: `routes/assets.py:135-180` (`create_assessment`: `revalue_asset` touches the asset, the explicit `ctx.touch(asset)` is deduped, `recompute_turn_in` touches the turn-in — so exactly asset +1 and turn-in +1 on success), `services/rollups.py:93-104` (`revalue_asset` returns early for `RETAINED`/`DESTROYED` and when no governing assessment exists — the asset is still touched by the caller), `services/calc.py` selector usage, and the same three `recompute_turn_in` callsites as above; confirmed the turn-in is guaranteed non-`None` at that point (earlier `ERR_INVALID_STATE`). (c) Adjustment: wrote it as a parenthetical anchored to §3.2 ("exactly as when an item is added") and left the existing "the asset's `version` increments by 1" clause verbatim, so the first-assessment vs re-assessment split and the no-revaluation cases are untouched.

## Items deliberately left unpatched (PRD already determines the behavior)

- `errors.py` `ERR_INVOICE_NOT_FOUND` -> `ERR_SALE_INVOICE_NOT_FOUND`: PRD §2.11 and the §5 catalogue already spell the id and pair it with 404. Pure impl defect, no PRD silence. (Re-verified the whole §5 table against `implementation/errors.py`'s `STATUS` map: the only id in the map absent from §5 is `ERR_LEDGER_WOULD_GO_NEGATIVE`, which §3.9 pins in prose at HTTP 409 — pre-existing and outside Step 7's scope, so untouched.)
- `GET /assets` and `GET /turn-ins` role lists: §4 already excludes `AgencyOfficer` from both; the 403s were the implementation being right and the tests wrong.
- Asset `version` after an assessment plus a clearance certificate (test_14 fix to 3), the `ERR_STALE_ASSET_VERSION`-outranks-state-codes ordering (test_11 fix), and the "a refused operation applies no hops" premise: pinned verbatim by §3.3, §3.8, §2.12 rank 14/16 and §2.9 respectively.
- The missing `assert_clearance_certificate` import: test-only `NameError`; the helper's asserted field set matches `services/serialize.py:78-81`, which §3.8 plus §2.5's append-only rule already determine.

## Step 9: Complete PRD — 2026-09-04T23:41:00.000Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying and edited in place). Partition: pass 1 = core + services (`app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `services/*`); pass 2 = intake/screening/transfer routes (`agencies, turnins, assets, release, screening, transfers, venues`); pass 3 = auction/finance routes (`lots, bidders, invoices, finance, clock`). Totals: 495 -> 496 lines, 104,835 -> 122,103 chars (+16.5%), 42 diff hunks, 42 pins/revisions (33 ambiguity-pins, 8 mismatch-revisions, one edit carrying both).

### Pass 1 — CORE + SERVICES (11 ambiguity-pins, 4 mismatch-revisions)

- §2.2 success envelope — revise — ambiguity — `api_request_id` spelled as `req_` + 32 lowercase hex; `api_request_timestamp` read from the logical clock, not wall clock — `response.py:24-27`
- §2.3 pagination — revise — ambiguity — empty-string `limit`/`offset` treated as absent; `offset` has no upper bound and may exceed `total_count` — `middleware.py:261-279`, `response.py:50-63`
- §2.3 ordering — revise — mismatch — identical `created_at` is routine under the logical clock, so every ordering falls back to ascending server insertion order, never `id` — `db.py:170-175` (`_seq`)
- §2.3 filters — insert — ambiguity — filters are exact case-sensitive equality, conjunctive, empty string ignored — `middleware.py:248-289`
- §2.4 instants — insert — ambiguity — input accepts any ISO 8601 spelling (`Z`, numeric offset normalised to UTC, or no designator = UTC), any/no fractional digits; output always 3 digits — `db.py:88-100`, `db.py:72-79`
- §2.5 version/`updated_at` — insert — mismatch — a single call bumps a given row at most once regardless of how many hops touch it; `updated_at` is the one clock instant of that call — `db.py:149-167`
- §2.6 rates — revise — mismatch — rates are exact decimals internally but echoed as JSON numbers with insignificant trailing zeros dropped (`0.10`->`0.1`, integer `0`->`0.0`) — `middleware.py:179-192`, `response.py:16-19`
- §2.9 cascades — revise — mismatch — reconciles "each hop increments by 1" with the once-per-row rule — `db.py:157-167`
- §2.11 routing — insert — ambiguity — unknown path -> `ERR_INVALID_REQUEST` 404, undeclared method -> `ERR_INVALID_REQUEST` 405 (only non-400 uses of that id), trailing slash equivalent, unanticipated failure -> `ERR_INTERNAL` 500 — `app.py:35`, `app.py:44-56`
- §2.12 rule 6 — insert — ambiguity — body must be a JSON object (absent/empty/`null` = `{}`; unparseable or non-object = 400); explicit `null` in an optional field = omission; bool<->number strictness; fractional `_cents` and unparseable date/instant fail here; non-string enum fails here not at rule 7; no string trimming — `middleware.py:107-225`
- §3.3 governing-assessment selector — revise — mismatch — the "millisecond precision makes it total" claim replaced by descending insertion order as the completing tie-break — `calc.py:80-90`
- §3.7 debarment hop three — revise — ambiguity — `bid_count` re-derived by §3.6 rules (retracted winner drops out, `OUTBID` still counts); voided invoice's `amount_paid_cents` and `deposit_applied_cents` zeroed and balance restored to total; lots where only an `ACTIVE` bid was retracted are also re-derived and version-bumped in `created_at` order — `cascades.py:74-98`
- §3.8 destruction / cycle cancellation — insert — ambiguity — cancelled cycle's `open_request_count` recomputed to 0 — `cascades.py:19`
- §3.8 destruction / lot cancellation — revise — ambiguity — retracting bidders' `winning_lot_count` and the cancelled lot's `high_bid_cents`/`bid_count` also recomputed — `cascades.py:30-41`
- §5 catalogue — insert — ambiguity — added the missing `ERR_LEDGER_WOULD_GO_NEGATIVE` -> 409 row (prose in §3.9 already pinned 409; the table claimed completeness) — `errors.py:82`

Verified-aligned, no edit needed: all enum value sets (`enums.py`), every `calc.py` constant/formula/rounding order (FMV, reserve floor, deposit, tier discounts, handling bands, invoice lines, tiered service fee, cost recovery, use-period months, de-minimis, bid increment, 24h relist cooldown), `round_half_up` semantics, all `serialize.py` projections (including the two append-only records with no `updated_at`/`version`), every roll-up recompute rule, `bubble_up_turn_in`, and the whole `errors.py` id->status map.

### Pass 2 — INTAKE / SCREENING / TRANSFER ROUTES (16 ambiguity-pins, 2 mismatch-revisions)

- §4 preamble — insert — ambiguity — enumerated the exactly nine endpoints on which `AgencyOfficer` own-organisation narrowing is applied, that body-sourced narrowing precedes shape validation (non-string value read as absent) while row-sourced narrowing follows the 404, and that assets/assessments/cycles/list-endpoints/proceeds are unnarrowed — `middleware.py:72`, `agencies.py:53`, `turnins.py:18,49,69`, `screening.py:159,207,247`, `transfers.py:72,92`
- §3.1 organisations — insert — ambiguity — donee-certification: status mandatory, expiry optional; `NONE` clears, supplied value overwrites, `CERTIFIED`/`SUSPENDED` without a date retains the stored expiry (no conditional-field guard); no state gate, version always bumps — `agencies.py:86-102`
- §3.1 venues — insert — ambiguity — `ACTIVE`->`CLOSED` is the only admitted transition; naming `ACTIVE` (any current status) or `CLOSED` on an already-closed venue is `ERR_INVALID_STATE` — `venues.py:67`
- §3.2 intake attributes — insert — ambiguity — a `federal_use_period_start_on` on a non-federal item is stored as given (only the derived end date stays null), unlike `demil_code`/vehicle triple which are nulled — `assets.py:89-93`
- §3.2 turn-in review — insert — ambiguity — a `REJECT` without `rejection_reason` is `ERR_INVALID_REQUEST` (400) evaluated before the turn-in resolves, not `ERR_CONDITIONAL_FIELD_REQUIRED`; a reason sent with `ACCEPT` is ignored and left null — `turnins.py:87-91`
- §3.4 request filing — revise — mismatch — "Three checks" became four: the cycle's `OPEN` state (`ERR_INVALID_STATE`) is checked ahead of the suspension check — `screening.py:172-177`
- §3.4 request-info / resubmit — insert — ambiguity — resubmission re-examines neither organisation `status` nor `current_tier` and has no lower bound against `tier_opened_at`; request-info is not window-gated at all — `screening.py:231,249-255`
- §3.4 tier advance — insert — ambiguity — every advance refreshes `open_request_count` — `screening.py:95`
- §3.4 exhaustion — insert — ambiguity — `current_tier` stays `PUBLIC_SALE` and `tier_opened_at`/`tier_deadline_at` are not reset — `screening.py:97-102`
- §3.4 award — insert — ambiguity — the request id is resolved only after the cycle `OPEN` check, so a bad id on a non-OPEN cycle reports `ERR_INVALID_STATE` — `screening.py:120-123`
- §3.4 award — insert — ambiguity — the award recomputes `open_request_count`, which lands at 0 — `screening.py:149`
- §3.5 issuance — insert — ambiguity — writes nothing outside the new order (no asset/request version move), never inspects the asset's `disposition_status`, and is neither idempotent nor exclusive — `transfers.py:51-66`
- §3.5 voiding — revise — mismatch — the "four hops" are conditional, not unconditional: hop 2 needs the request still `APPROVED`, hop 3 the cycle still `AWARDED`, hop 4 the asset still `AWARDED_TRANSFER`; a second void stops at hop one. Also pinned that the reopened cycle's `tier_advance_count` is untouched and `open_request_count` recomputed — `transfers.py:119-137`
- §3.8 clearance axis — insert — ambiguity — a `serials_verified: false` certificate against an asset already `RELEASED`+`CLEARED` is `ERR_INVALID_STATE` (409), after the applicability rule — `assets.py:229-232`
- §3.8 destruction — insert — ambiguity — a `DESTROY` certificate from any other disposition state is `ERR_INVALID_STATE` (409), checked after both the method-family and applicability rules — `assets.py:225-228`
- §3.8 release — insert — ambiguity — which rows the two paths select: latest-created `CLOSED_MET`/`SETTLED` lot plus its single non-`VOIDED` invoice; latest-created `ACKNOWLEDGED` order — `release.py:11-23`
- §3.8 release — insert — ambiguity — absence of any qualifying lot/invoice/order is also `ERR_INVALID_STATE` — `release.py:42-49`
- §3.8 release — insert — ambiguity — the three documentation fields are written only when supplied (omitted ones keep null), and the `SOLD` path leaves lot and invoice untouched — `release.py:83-88`

Pass 2 deliberately did NOT pin `transfers.py:48`'s `fair_market_value_cents or 0`: the path is unreachable (a cycle cannot open on an unvalued asset), and pinning it would document behaviour the API cannot exhibit.

### Pass 3 — AUCTION / BIDDING / FINANCE ROUTES (15 ambiguity-pins, 2 mismatch-revisions)

- §2.4 — insert — ambiguity — `current_utc` is mandatory and any instant is accepted, including one strictly earlier than the current reading (no monotonicity requirement) — `routes/clock.py:16-18`
- §3.1 (bidder registry) — insert — ambiguity — `email` is 1-254 characters — `routes/bidders.py:31`
- §3.1 — insert — ambiguity — the five listed moves are the whole status machine; every other target, including a no-op restatement of the current status and any move out of `PENDING` other than to `REGISTERED`, is `ERR_INVALID_STATE` — `routes/bidders.py:14-20,82`
- §3.1 — insert — ambiguity — end-use-certificate call: date mandatory, past dates allowed (rule-10 guard does not reach it), overwrites the stored value, no state precondition at all, `version` +1 — `routes/bidders.py:93-104`
- §3.1 — insert — ambiguity — deposit `amount_cents` >= 1, a non-positive deposit being `ERR_INVALID_REQUEST` (400) — `routes/bidders.py:112`
- §3.6 — revise — ambiguity — the 2,500-cent floor is enforced on the officer override as an input range check (`ERR_INVALID_REQUEST` 400), *not* by clamping up to the floor; an accepted override is stored verbatim with no upper bound — `routes/lots.py:24,73-75`
- §3.6 — insert — ambiguity — open-lot check order (`DRAFT` -> venue -> window), so a closed venue outranks a clock-outside-window complaint, and opening touches only the lot (venue row untouched; `active_lot_count` spans `DRAFT`+`OPEN` so it cannot change) — `routes/lots.py:125-135`
- §3.6 — insert — ambiguity — bid `amount_cents` <= 0 is `ERR_INVALID_REQUEST` (400), not a fiscal code — `routes/lots.py:146`
- §3.6 — insert — ambiguity — one bidder may bid repeatedly on a lot, including over its own leading bid; earlier bids stay `ACTIVE` and keep counting in `bid_count` — `routes/lots.py:170-174`
- §3.7 — insert — ambiguity — on the no-sale branch no bid moves: below-reserve bids stay `ACTIVE`, their rows and bidders are untouched, and the re-derived `high_bid_cents`/`bid_count` still count them (venue count recomputed as on the met branch) — `routes/lots.py:261-268`
- §3.7 — revise — mismatch — a zero/negative payment `amount_cents` reports `ERR_PAYMENT_EXCEEDS_BALANCE` (422), not a rule-6 `ERR_INVALID_REQUEST` — `routes/invoices.py:41,57`
- §3.7 — insert — ambiguity — payment side effects: bidder `version` +1 even on pure cash, lot `version` only on the settling call, and the response is HTTP 200 with the updated `SaleInvoice` (a payment is not a stored resource) — `routes/invoices.py:67-80`
- §3.7 — insert — ambiguity — default records the forfeiture on the bidder only: the invoice's own `deposit_applied_cents` and `balance_due_cents` are left as they stood, and the bidder's `version` +1 regardless — `routes/invoices.py:100-106`
- §3.7 — insert — ambiguity — void re-derives `balance_due_cents` back to `total_due_cents`, bumps the bidder's `version` regardless, and moves nothing else (lot stays put, asset stays `SOLD`) — `routes/invoices.py:127-137`
- §3.7 — insert — ambiguity — a lot carries at most one `SaleInvoice` for its whole life, so "*the* lot's non-`VOIDED` invoice" (§3.8 release, §3.9 cash basis) names at most one row — `services/rollups.py:62-66`, `routes/lots.py:237`
- §3.9 — insert — mismatch — posting reads no request body at all, so a body that is unparseable or not an object is ignored rather than failing §2.12 rule 6 — `routes/finance.py:101-104`
- §4 preamble — insert — ambiguity — the `Bidder` own-row narrowing set is exactly six endpoints (`GET /bidders/{id}`, `POST /bidders/{id}/deposits`, `GET /bidders/{id}/bids`, `POST /auction-lots/{id}/bids`, `GET /sale-invoices/{id}`, `POST /sale-invoices/{id}/payments`), with placement pinned (path-read -> 403 before 404; body-read on bid placement -> before shape validation, non-string treated as absent; row-read on invoices -> 404 first), and no other endpoint narrows a Bidder — notably `GET /sale-invoices` is unfiltered — `middleware.py:83-91` + the six handlers

Pass 3's verdict on the two handed-over items: (1) the null-FMV reserve path at `routes/lots.py:77` is UNREACHABLE and was deliberately NOT pinned — `revalue_asset` writes a non-null FMV on the only route out of `INTAKE`, so every listable state already has FMV set; only the reachable half (the override range check) was documented. The `live_invoice_of_lot` "most recently created" tie-break is likewise unreachable (a lot closes once, so <=1 invoice ever exists), so the reachable *uniqueness* fact was pinned instead. (2) Pass 2's §4 sentence about `GET /proceeds-distributions{,/{id}}` applying no `AgencyOfficer` narrowing is correct (`finance.py:82-99` calls neither `agency_scope` nor a beneficiary filter) and was left untouched.

### Orchestrator verification

- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` -> differs (the "byte-identical means the scan never ran" failure mode did not occur); `diff` reports 42 hunks.
- Sizes: PRD.md 495 lines/104,320 B; PRD_FINALIZED.md 495/104,835; PRD_COMPLETED.md 496/122,103.
- Structure intact: all five top-level sections present at lines 3/11/185/363/432; §5 error table now 59 rows, ending on `| ERR_LEDGER_WOULD_GO_NEGATIVE | 409 |` — a real boundary, no mid-sentence truncation.
- Step 9 edited documentation only; `implementation/` was untouched after Step 7, so the final 8-round sweep result (214/214 in all of results.1..8.json) still stands as the pipeline's test evidence.

Pipeline complete through Step 9.
