# Worklog — task_2968_immersive_pop_up_experience_operations

## Step 1: Create task directory — 2026-09-05T23:14:19.925Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2968_immersive_pop_up_experience_operations` and `.../workspace` (pre-assigned path; no index auto-allocation, per orchestration instructions).

## Step 2: Generate Scaffold — 2026-09-06T02:12:14.635Z

Subagent summary (verbatim):

Scenario 2968's scaffold is complete and lints clean.

## Deliverables
All under `/home/ubuntu/github/CodingPRD/tasks/task_2968_immersive_pop_up_experience_operations/`:

- `SCAFFOLD.yaml` — 3,978 lines. §1.0–§1.7 only; neither `scaffold_difficulty_design` nor `scaffold_corner_design` present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3,699 lines, single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 7,412 lines, single top-level key `scaffold_corner_design`.

All three parse under `yaml.safe_load`; non-ASCII limited to the intentional `§`, `–`, `—`. `.scratch/step2/` (my own subdir) removed; nothing outside it touched. No sibling task directory was read at any point.

## Counts
**SCAFFOLD.yaml:** 13 entities, 13 state machines, 73 endpoints, 82 errors, 7 roles, 14 calculations, 17 validation priority rungs (10→150), 2 OCC concurrency rules. `complexity_profile`: temporal_windowing / multi_party_negotiation, layers [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers], graph topology, cyclic machines, `segregation_of_duties`, `immediate`.

**§1.8:** 9 rule blocks, 25 instances.

**§1.9:** 9 sections — entities 11, state_machines 19, calculations 12, validations 16, endpoints 5, errors 4, rbac 5, cross_cutting 4, consistency_model 1 — **77 instances total: 59 active recipes + 18 `excluded_because` stubs** (each citing the §1.8 instance that already owns the corner; all 18 cited names were cross-checked against the §1.8 name set and three wrong citations were corrected).

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    73
  §1.1 entities declared:     13
  §1.8 instances scanned:     25
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  1893

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications
1. **`TimedEntrySlot.held_capacity`** contradicted itself (§1.1 said "0 or released_capacity" while every PENDING order adds `party_size`). Fixed §1.1 to `0..released_capacity` with buyout wording; corrected an already-written assert to match.
2. **New error `ERR_VENUE_HAS_ACTIVE_RUN` (409)** — nothing refused ending a lease under a live run. Added to §1.6 and to the P80 rung with `applies_to POST /venues/{venueId}/end-lease`.
3. **P50 scoped-FK clause** — a `StaffShift.themed_room_id` naming a room in a *different* run had no error id; P50 and `ERR_ROOM_NOT_FOUND` now declare that an out-of-scope FK is "unresolved", rather than weakening the §1.9 instance.
4. **P150 reordered** so the demand floor (`EXTENSION_DEMAND_MIN`) is evaluated *before* the lease-extension budget, matching §1.2; the §1.8 extension instance now cites `validations[priority 150]`.
5. **Lint rule (e)** — the deliberately-stale OCC literals (`999`, `1`) were replaced with genuinely stale *captured* versions (`${run_v0}` read before the statement create that bumps `run.version`; `${run_v}` for the 404-path probe), preserving the 412-vs-404/422/409 priority proofs.
6. **RBAC negative instances are named to match the linter's negative-trigger regex** (`..._are_rejected_in_priority_order`, `..._is_rejected_on_every_hop`) so their deliberately wrong `as:` roles, blank `X-User-ID`/`X-User-Role` and undeclared-role calls are exempt from rules (b)/(c) instead of forcing me to soften the scenarios.
7. **Non-applicable §1.9 rows are recorded as YAML comments rather than faked**: `bulk_operations`/`bulk_action` (no endpoint takes an array), `soft_delete` (nothing is deleted; `GuestAccount RESTRICTED` is a strike consequence with its own reinstate), `multi_tenancy`, `conditional_feature_flags`, and eventual/saga consistency (no 202, nothing queued).
8. **Banned concurrency vocabulary swept** — two uses of "simultaneously" reworded to "both"; a grep over all three files for the full banned list is now empty.
9. **Accepted design point:** `ExperienceRun` can only start closing from OPEN/EXTENDED, so a PLANNED run has no path to CLOSED (and therefore its venue's lease cannot be ended). Left as designed; every recipe drives the reachable OPEN → CLOSING → CLOSED path.
10. **Timestamp constraints** are written as ISO-8601 instants without mandating a fixed sub-second width, to avoid manufacturing format-precision failures downstream.

## One thing for the orchestrator
`SCAFFOLD.yaml`'s `scenario:` key retains the literal first line `Generate task harder than expert level!` because the instruction was to use the scenario verbatim. Per the known leak path (scenario → PRD.md), that single line should be stripped from `SCAFFOLD.yaml` before Step 4 runs.

Orchestrator note: acted on the subagent's closing advice — stripped the `Generate task harder than expert level!` line (and its trailing blank) from `SCAFFOLD.yaml`'s `scenario:` block before Step 4. A repo-wide grep for "harder than expert" under the task dir now returns nothing, and all three YAMLs still parse under `yaml.safe_load`. Removed the leftover `.scratch/step2/` dir.

## Step 3: Copy shared files — 2026-09-06T02:12:40.859Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T02:31:00.000Z

Subagent summary (verbatim):

PRD.md is complete at **/home/ubuntu/github/CodingPRD/tasks/task_2968_immersive_pop_up_experience_operations/workspace/PRD.md** — **478 lines**, built incrementally (1 Write + 9 heredoc/`cat` appends, `wc -l` after each), ending cleanly on the final row of the §5 error table.

## Sections
- `# Immersive Pop-Up Experience Operations API — Product Requirements Document`
- **§1 Introduction** (3 paragraphs: borrowed rooms/rented time, system of record, the two design decisions — explicit logical clock, compliance as a separate state dimension)
- **§2 Global Specifications & System-Wide Principles** — 2.1 RBAC (7 roles, 6 opaque operator identities + the entity-backed `Guest`), 2.2 Response Structure (byte-identical, verified by substring match against `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Logical Clock, 2.5 Money, Precision and Conserved Quantities, 2.6 Stale-Version Guards, 2.7 The Rejection Ladder (17 rungs), 2.8 Path Parameters/Filters/Reverse Reachability, 2.9 Cascade Discipline, 2.10 Segregation of Duties and Ownership
- **§3 Business Logic & Workflows** — 3.1 venue/permit/buildout waterfall, 3.2 licensing + submission negotiation/supersession, 3.3 run design/rooms/capacity/two standings, 3.4 roster/readiness variants/shift geometry, 3.5 slots/overlap load/dynamic pricing/buyout, 3.6 guests/order money/attendance/refund ladder, 3.7 inspections (derived verdict, three disjoint cascades), 3.8 demand/extension/closure/kit decay-refurb-localise, 3.9 royalty accrual variants/true-up/MG proration
- **§4 Endpoint Definitions** — intro paragraph + 4-column table, **73 rows**
- **§5 Error Code Catalogue** — 2-column table, **82 rows**

## Coverage (machine-verified)
- 13 entities / 171 field names + 119 endpoint body-and-path identifiers = **198 required identifiers, 0 missing**, and all 198 appear as *standalone* backticked tokens (not merely inside path tokens).
- **82/82 error IDs appear in §1–§3 prose** (not only in the §5 table); 82/82 catalogue rows match scaffold HTTP statuses; 73/73 endpoints match method+path.
- 14 calculations rendered in precise prose with every constant value present; 79 state-machine transitions covered (48 as explicit `FROM → TO` arrows, 31 in prose form — each re-checked by hand); both OCC rules rendered with write operation, occ field, parent version, error ID and 412; 17 validation rungs with their scopes.
- Zero pseudocode/operator tokens (`>=`, `min(`, `round_half_up`, `SUM(` …) and zero fuzzy words in §1–§3.

## Hard Contracts
- **Contract 1 (Field-Name Coverage): PASS** — 198/198.
- **Contract 2 (Rule Coverage): PASS** — priority ordering, OCC rejections, cross-entity side effects, applies_to scopes, field types/defaults/initial values, sibling-branch symmetry (three inspection outcomes; kit refurbish-vs-retire; statement DRAFT self-loop vs true-up; lift-suspension → CLEARED vs UNCLEARED; guest-cancel vs FAIL-override refund), all transitions, all calculations, all validation conditions matched to error IDs, all endpoint side effects.
- **Contract 3 (§3 Path Purity): PASS** — 1124 backticked tokens in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path pairs, and no plain-text path or method mentions either.

## Adjudications made (scaffold conflicts / gaps)
1. **Training records — accumulate vs replace.** The endpoint's side effects say `training_score` "is replaced" and the rehearsal counts "are replaced when supplied"; the state machine says `training_score = max(existing, submitted)` with `+=` on both counters, its note reasons explicitly about monotonicity, and both count fields are described as "Cumulative". Adjudicated **in favour of max + accumulate** (two of three sources).
2. **FAIL cascade hop 3 slot scope.** The endpoint text includes `HELD_FOR_BUYOUT`; the inspection state machine and the slot machine both admit `SUSPENDED` only from `{OPEN, SOLD_OUT}` (no `HELD_FOR_BUYOUT → SUSPENDED` transition exists). Adjudicated to **`OPEN`/`SOLD_OUT` only**.
3. **CONDITIONAL cascade slot scope.** Endpoint text suspends every `OPEN`/`SOLD_OUT` slot; the state machine suspends only those whose `base_capacity` exceeds the new cap. Adjudicated to the **more specific state-machine rule**.
4. **Buildout draws on a terminal venue.** `ERR_VENUE_INVALID_STATE` lists buildout-draws in its scope but no transition declares the admissible states. Adjudicated as **refused when the venue is `PERMIT_DENIED` or `LEASE_ENDED`**, admissible otherwise.
5. **Run-creation window errors split.** `scheduled_close_date` after `venue.lease_end_date` is `ERR_SLOT_OUTSIDE_RUN_WINDOW` (per that error's own condition), while an inverted run span is `ERR_INVALID_WINDOW`.
6. **`requested_extension_days`** has no declared upper bound in the scaffold; rendered as "at least one day", bounded in practice by the venue's remaining `lease_extension_option_days`.
7. **ThemedRoom common fields** (`common_fields: false`) rendered as carrying `id` and `created_at` only — no `updated_at`, no `version`, no status.

Scratch: `.scratch/step4/` deleted (parent `.scratch/` left in place). `worklog.md` untouched. One sanitisation: the clock endpoint's description in §4 had the word "scaffold" replaced with "specification"; no other scaffold-internal references (`§1.x`, `test_recipe`) appear anywhere in the document.

Orchestrator truncation check: `wc -l` = 478; tail shows the §5 table's last row (`ERR_STATEMENT_PERIOD_ISSUED | 409`) as a complete table line at a real section boundary — not truncated. §5 spans lines 393–478 = header + separator + 82 error rows, matching the declared count. Grep for the difficulty directive in PRD.md returns 0 hits.

## Step 6: Generate Implementation — 2026-09-06T03:26:00.000Z

(Launched concurrently with Step 5 in a single orchestrator message, so the impl generator was physically isolated from `test_suite/` — that directory did not exist when it started.)

Subagent summary (verbatim):

Implementation complete. All servers killed by recorded PID, `.scratch/step6` removed (sibling `.scratch/step5` untouched), `worklog.md` untouched.

## Deliverables — `workspace/implementation/` (3869 lines, 26 files)

| Module | Lines |
|---|---|
`app.py` | 70 (14 blueprints, error handlers, `0.0.0.0:$PORT`)
`start.sh` | 10 (executable, foreground `exec python3 app.py`)
`requirements.txt` | 1 (Flask==3.0.3)
`db.py` | 124 (in-memory `Store`, logical clock, `public()`)
`errors.py` | 198 (all 82 codes + HTTP statuses)
`middleware.py` | 67 (7 roles, `roles()` decorator)
`response.py` | 73
`services/validate.py` | 235
`services/calc.py` | 333 (14 calculations + constants)
`services/derive.py` | 344 (re-derivations, geometry sweeps, cascade helpers)
`routes/clock.py` | 23
`routes/venues.py` | 209
`routes/agreements.py` | 121
`routes/submissions.py` | 193
`routes/runs.py` | 352
`routes/rooms.py` | 80
`routes/slots.py` | 210
`routes/guests.py` | 89
`routes/orders.py` | 314
`routes/staff.py` | 161
`routes/shifts.py` | 101
`routes/inspections.py` | 182
`routes/kits.py` | 126
`routes/statements.py` | 253

**Endpoints: 73 implemented** — `app.url_map` yields exactly 73 rules, and a set-diff against the PRD endpoint table is empty in both directions (`declared not impl: []`, `impl not declared: []`). Paths are bare (`api_prefix: ""`). Storage is in-memory dicts only; nothing is seeded — a fresh boot answers `GET /venues` with `{"data":[]}`. No `.db`/`.json`/`.sqlite` artifacts. Verified a cold `PORT=… ./start.sh` boot with no `__pycache__` present.

**Validation:** two smoke suites, both **0 failures**. `smoke.py` covers the happy path end to end (permit -> lease -> agreement -> kit -> run -> rooms -> submissions -> staff clearance -> shifts -> slots -> order money `{unit 8450, gross 48168, net 37732}` -> SOLD_OUT -> check-in/no-show -> extension -> statement issue/settle -> CONDITIONAL cap -> FAIL cascade -> suspension lift -> CLOSE -> kit decay). `smoke2.py` covers the negative and fork paths (buyout hold/release, refund ladder 1.00/0.50/0.00 with credits, three strikes -> RESTRICTED -> reinstate, slot SUSPEND/RESUME, statement 412 stale-version, supersession, true-up fork with truedown 1725, demand-floor 409).

## PRD ambiguities resolved

1. **training-records semantics** — scaffold says "replaced", PRD says max-of-scores + additive rehearsals; PRD wins.
2. **lift-suspension slot cascade** — dropped the scaffold's `slot_start_utc > current_utc` filter; implemented the PRD's SOLD_OUT branch.
3. **Conditionally-required `note`** (permit CONDITIONS/DENIED, submission REJECTED/CHANGES_REQUESTED) enforced at rung 4 as `ERR_VALIDATION` 422.
4. **Inspection `findings_note`** required when the *derived* outcome != PASS (checked after derivation); `ERR_SEVERITY_FINDINGS_MISMATCH` fires first.
5. **run open** — roomless -> `ERR_RUN_HAS_NO_ROOMS`; capacity 0 / no OPEN slot -> `ERR_RUN_INVALID_STATE`.
6. **`ERR_RUN_HAS_NO_ROOMS` placement** — raised inside capacity derivation, before the slot overlap check.
7. **Order-confirm capacity gate** — the literal "available_capacity >= party_size" makes the OPEN->SOLD_OUT transition unreachable (held->sold leaves `available` unchanged), so the gate is `released_capacity - sold_capacity >= party_size`; state machine beats the prose, commented in-code.
8. **Statement supersession** — refuse when a same-period row is ISSUED/SETTLED/**SUPERSEDED**; supersede DRAFT/UNDER_TRUEUP peers.
9. **Timestamps** — always the logical clock, never wall-clock.
10. **Instant echo** — client input echoed verbatim (raw string stored, parsed copy under `_` keys); server-minted stamps canonicalised to 3 fractional digits.
11. **List filters** — `limit`/`offset` validated; unknown filter enum values match nothing rather than 422.
12. **Accessibility (rung 14)** checked at order create *and* confirm against the per-order `sensory_accommodations`.
13. **REJECTED submission** drops a CLEARED run to UNCLEARED unconditionally; APPROVED/create use the gate-based re-derivation.
14. **Extension clearance gate** has no dedicated code -> `ERR_RUN_INVALID_STATE`.
15. **RESUME on a slot whose run is SUSPENDED** -> `ERR_RUN_SUSPENDED`.
16. **"finalized later than"** compares `(_finalized_at, _seq)` tuples so a static clock still orders deterministically.
17. **Reinstate on a non-RESTRICTED guest** -> `ERR_VALIDATION` (`ERR_GUEST_INVALID_STATE` is not a declared code).
18. **Confirm at/after `slot_start_utc`** -> `ERR_SLOT_INVALID_STATE` (rung 12 declares no confirm-specific code).
19. **Rung 14 before rung 15 on order create** — the ladder beats §3.6's narrative ordering.
20. **Staff enrolment** — `cert_coverage_pct` starts at 0.00 per PRD §3.4 even though the scaffold describes it as derived from `certifications`; the first training record derives it.
21. **CONDITIONAL cascade** recomputes capacity with `tolerate_empty=True` so a roomless run cannot raise `ERR_RUN_HAS_NO_ROOMS` from a cascade.
22. **FAIL-cascade refunds** use refund_pct 1.00 -> whole `net_collected_cents` refunded, credit 0 (operator fault); slot seat counters deliberately preserved.

One intrinsic spec dead end, left as declared rather than "fixed": a kit that closes out with `condition_score >= 60` lands `IN_TRANSIT`/`LOCALIZED`, and since `localize` requires `localization_status == PENDING` while deployment requires `READY`, it can never be redeployed. The BuildKit state machine in SCAFFOLD.yaml declares exactly these transitions, so the implementation mirrors it verbatim.

## Step 5: Generate Unit Tests — 2026-09-06T04:40:53.603Z

Orchestrator note on an infra failure and how it was handled: the Step 5 agent was killed mid-append by an API error ("Agent terminated early due to an API error") while writing its last chunk. Rather than respawning a fresh generator — which would make the suite diverge from itself — the orchestrator audited on-disk state (all files byte-compiled clean; 119 tagged tests; queue A 25/25; queue B 55/59) and SendMessage'd the SAME agent a computed to-do list naming only the 4 uncovered §1.9 instances. It resumed with full context and finished.

Subagent summary (verbatim, from the resumed run):

Step 5 is complete. All four remaining §1.9 instances are resolved: three emitted, one skipped.

## The four instances

**1. `each_role_performs_the_operations_it_owns` — EMITTED** (`test_suite/test_10_platform_conventions.py`, class `TestEachRolePerformsTheOperationsItOwns`)
- `test_the_six_staff_roles_each_reach_the_endpoints_that_name_them` — VOM draws buildout (allowance 500000 / credit 0 / capex 0 / spend 500000), LM opens a DRAFT statement, REP starts the review, PRODUCER creates and releases the window, OFFICER books an ACCESSIBILITY inspection, AGENT opens a guest account.
- `test_the_guest_owns_no_endpoint_and_still_buys_reads_and_cancels` — the Guest's empty exclusive list still buys (PENDING, unit 35833, gross 71666, held 2 / available 18), quotes (`lead_days` 24, MEMBER per-guest 34041, net 68082) and cancels its own order (refund_pct 0.00, ledger back to 20/0/0/20); AGENT reads the venue it can never write; REP lists the statement it cannot create.

**2. `unauthenticated_and_unauthorized_calls_are_rejected_in_priority_order` — EMITTED** (same file, class `TestUnauthenticatedAndUnauthorizedInPriorityOrder`)
- `test_a_bad_header_is_never_a_forbidden_call_and_neither_hides_a_missing_row` — blank `X-User-ID`, blank `X-User-Role` and the undeclared `MerchandisingLead` all give 401 `ERR_UNAUTHENTICATED`; PRODUCER creating a venue gives 403; AGENT drawing on a phantom venue id gives 403 not 404 (rung 2 over rung 3); Guest refused on guest-account create and statement list; venue list still totals 1.
- `test_identity_answers_after_the_role_and_the_owner_still_gets_through` — `rep-2` -> `ERR_LICENSOR_REP_MISMATCH` with the submission byte-inert, then `rep-1` -> IN_REVIEW; guest_b ordering onto and cancelling guest_a's order -> `ERR_GUEST_OWNERSHIP_MISMATCH` with the ledger and order row untouched; guest_a's own cancel succeeds.

**3. `every_write_is_visible_to_the_very_next_read` — EMITTED** (same file, class `TestEveryWriteIsVisibleToTheVeryNextRead`)
- `test_the_order_and_the_window_agree_at_every_hop_and_the_aggregate_is_pure` — the create response already carries the frozen money (35833 / 107499), the next slot read is already 3 held / 17 available at release+1, confirm returns `net_collected_cents` 107499, the re-read is field-for-field identical, the slot is 0 held / 3 sold / 17 available at release+2 and still OPEN, and `demand-index` returns 15.00 identically from PRODUCER and LM while the run row stays byte-inert across both telemetry reads.
- `test_an_enrolment_is_already_derived_and_already_listed_in_its_own_response` — the create response already carries `cert_coverage_pct` / both readiness variants at 0.00 in CANDIDATE at version 1, and the very next list already includes it.
- **PRD divergence:** the design asserts the run's stored `demand_index` equals what the telemetry endpoint returns. PRD 285 says `demand_index` "is written only on a successful extension; the read-only telemetry view computes the same figure and stores nothing", and PRD 207 says the view "persists nothing, writes no field and never advances the run's `version`". I asserted the PRD's version: endpoint 15.00, stored 0.00, run row inert.

**4. `lifting_a_suspension_resumes_only_the_slots_that_still_fit` — SKIPPED** (failed the second filter condition: PRD does not uniquely derive the asserted outcome — it contradicts it). PRD line 279 makes the lift fan-out unconditional: "On success `suspended_at` and `suspending_inspection_id` are both cleared, and every slot of the run still in `SUSPENDED` returns to `OPEN`, landing in `SOLD_OUT` instead where its `available_capacity` is already 0." The instance's distinguishing claim is the opposite — a capacity filter where the 110-seat slot "STILL SUSPENDED ... the fan-out skipped it" while the 20-seat one resumes. PRD's only conditional on that hop is OPEN vs SOLD_OUT by `available_capacity`, never `base_capacity` vs the tightened cap. And because no slot survives the lift in `SUSPENDED`, the recipe's last probe (a hand-driven RESUME returning `ERR_SLOT_CAPACITY_ABOVE_RUN`) has no reachable precondition. Writing it would have required asserting the scaffold against the PRD, so the gap stays a gap. Nothing was weakened, and no skip/xfail marker or placeholder was emitted.

## Final state

- `python3 -m compileall -q test_helpers test_suite` is **silent**; `__pycache__` dirs removed afterwards.
- `test_helpers/` and `test_suite/` are both at the task root; `find workspace -name test_helpers -o -name test_suite` returns nothing.
- **128 tests** across `test_suite/test_01..test_10` (test_10 grew from 8 to 14 tests, 736 -> 1228 lines). Per file: 12 / 13 / 15 / 14 / 12 / 21 / 9 / 9 / 6 / 14.
- **Coverage: queue A 25/25 §1.8 instances, all with >=2 tests. Queue B 58/59 active §1.9 recipes** (18 `excluded_because:` stubs correctly untranslated), the single gap being #4 above. Zero untagged, dual-tagged, stub-pointing or nonexistent-instance tags.
- **No `test_helpers/` edits were needed** — every one of the six new tests reuses the existing fixtures, factories and header builders (`BLANK_USER_ID_HEADERS`, `BLANK_ROLE_HEADERS`, `UNDECLARED_ROLE_HEADERS`, `make_guest_headers`, `selling_world`, `run_with_room`, `place_order`, `draft_statement`, `read_*`).
- Scratch: `rm -rf .scratch/step5` only; the parent `.scratch/` and any sibling subdirs were left alone. `worklog.md` untouched, `workspace/implementation/` never read or written, no sibling task dir read.

One caveat worth flagging to whoever runs Step 7: the guest-facing money figures (35833 / 34041 / 68082 / 71666 / 107499) and `lead_days` 24 are derived from a clock at `2026-08-01T00:00:00Z` against a `2026-08-25T14:00Z` STANDARD window, so if a failure clusters on those numbers, check the clock position before suspecting the pricing implementation.

Orchestrator verification: `find workspace -name test_helpers -o -name test_suite` returns nothing (both dirs correctly at the task root, not under workspace/). `compileall` silent. Independent AST-ish audit counts **125 test functions, 0 untagged** — the subagent's "128" is a slight miscount, but the property that matters (every test function carries exactly one Design tag, no tag pointing at a nonexistent or stub instance) holds. Pre-wrote `workspace/sweep.sh` (script file with a `SWEEP_DONE` sentinel after `wait`) for Step 7 to use, to avoid the inline-quoting and early-return-relaunch traps.

## Step 7: Run Tests and Iterate — 2026-09-06T05:24:00.000Z

Subagent summary (verbatim):

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 3 (each an 8-round parallel sweep under `setsid`, joined via `SWEEP_DONE` sentinel)

- Iteration 1: 121/125 in all 8 rounds — 4 deterministic failures (no flakiness anywhere; no load-induced noise)
- Iteration 2: 124/125 in all 8 rounds — 1 deterministic failure
- Iteration 3: **125/125 in all 8 rounds**

**Tests deleted:** none. All four failures resolved as either partial-coverage trims (§1c) or test-vs-PRD faithfulness fixes (STEP 2), plus two genuine implementation bugs (STEP 3).

**Fixes applied to `test_suite/`:**

- `test_suite/test_02_licensing_and_submissions.py` — `TestAgreementTerminalStates::test_activation_is_refused_the_second_time`: dropped the `activated_at` presence/stability assertions. PRD §2.4 gives an exhaustive list of clock-stamped fields and there is no agreement-level `activated_at` (only the venue's `lease_activated_at`); a PRD-only implementer would not serialize such a field. Per §1c the covered part was kept and strengthened — the repeat now asserts `ERR_AGREEMENT_INVALID_STATE`/409 plus `assert_row_inert(activated, after)` and `version == 2`.
- `test_suite/test_06_orders_attendance_and_refunds.py` — `test_the_flip_fires_on_the_confirmation_that_empties_the_hold`: the test placed three holds that exhausted the window (held 20, available 0) and then expected the slot to stay `OPEN` through the first two confirms. That contradicts verbatim PRD §3.6 ("the slot moves to `SOLD_OUT` when that leaves nothing available") and is unreachable anyway, since a confirm only moves seats held->sold and therefore never changes `available_capacity`. Restructured to hold-then-confirm each party in turn, so the flip genuinely fires on the confirmation whose recomputation leaves nothing available. All money expectations (64500 / 367650 / 183825) are unchanged and order-independent.
- `test_suite/test_07_inspections_and_suspension.py` — `test_each_refusal_names_the_row_it_actually_read`: the `ERR_AGREEMENT_NOT_ACTIVE` probe filed a submission naming a **DRAFT agreement plus a run staged under a different agreement**. PRD §2.7 rung 5 scopes body foreign keys ("resolves within the scope its owning rule declares") and sits above rung 9, so `ERR_RUN_NOT_FOUND` was the correct answer — a test-setup bug, not an implementation bug. Rewritten to expire the run's *own* agreement (clock forward, expire, clock reset) so the submission create legitimately reaches the rung-9 licence gate.
- `test_suite/test_09_royalty_statements.py` — `test_true_up_refuses_a_third_recompute_and_still_issues`: expected `mg_prorated_cents == 39061`, but the PRD formula gives `192790 x 31 / 153 = 39062.0261...` -> 39062 half-up. Corrected to 39062 / shortfall 30104 / amount_due 39062. Cross-checked against the already-passing sibling test whose 30-day period asserts 37802 — the same formula and the same implementation produce both, confirming the impl was right and the literal was wrong.

**Fixes applied to `test_helpers/`:** none required — no shared fixture/factory bug surfaced.

**Fixes applied to `implementation/`:**

- `workspace/implementation/routes/statements.py` — `recompute_provisional`: the own-state gate used `SUPERSEDABLE = ("DRAFT", "UNDER_TRUEUP")`, so an `UNDER_TRUEUP` statement could be recomputed again. PRD §3.9 declares the recompute only out of `DRAFT` (both destinations are `DRAFT -> DRAFT` and `DRAFT -> UNDER_TRUEUP`; the endpoint table says "Re-run the provisional accrual on a **draft** statement"), and contrasts with finalisation, which names `UNDER_TRUEUP` as a source explicitly. Tightened to `!= "DRAFT"` -> `ERR_STATEMENT_INVALID_STATE`.

**Final round tallies (iteration 3):** rounds 1-8 all `passed=125 / total=125`.

Nothing was weakened: no `skip`/`xfail` added, no `error_id` assertion downgraded to an HTTP-status check, no PRD-required implementation check removed, no endpoint/field/side-effect added that does not trace to PRD prose. `worklog.md` was not touched; `.scratch/step7/` removed (parent `.scratch/` left intact).

Orchestrator verification: independently re-read all 8 `workspace/implementation/results.$i.json` keyed on `"status"`/`passed`/`total` — every round reports `passed=125 total=125`. Step 8 is therefore NOT skipped (1 `implementation/` fix + 4 `test_suite/` fixes > 0).

## Step 8: Finalize PRD — 2026-09-06T05:29:00.000Z

Not skipped: Step 7 applied 1 `implementation/` fix and 4 `test_suite/` fixes, so the skip condition (zero iterations beyond baseline) did not hold.

Subagent summary (verbatim):

Step 8 complete. `PRD_FINALIZED.md` written with three surgical inline edits.

## Line counts
- PRD.md: 478 lines / 111,290 chars
- PRD_FINALIZED.md: 478 lines / 112,125 chars
- **Delta: 0 lines (0.00%), +826 chars (+0.745%)** — all three edits are inline inside existing long paragraphs; no new sections, no reflowing.

## Changes

- **§3.6 (order confirmation)** — *revise* — the confirm-time seat gate was PRD-mismatched: PRD said "the slot to be `OPEN` with `available_capacity` at least `party_size`". Impl instead measures `released_capacity - sold_capacity >= party_size` (the order's own hold is not counted against it) and refuses with `ERR_SLOT_CAPACITY_EXCEEDED`. Rewrote the clause to match; left the `OPEN`/`HELD_FOR_BUYOUT` mirror-pair clause verbatim and left the creation-time gate (which really is `available_capacity`) untouched. — `implementation/routes/orders.py:160-162`
- **§3.9 (recompute-provisional)** — *insert* — one sentence pinning the own-state gate: recompute is declared only out of `DRAFT`; any other state, including `UNDER_TRUEUP`, earns `ERR_STATEMENT_INVALID_STATE`, explicitly contrasted with finalisation. This is the Step 7 implementation fix (`SUPERSEDABLE` -> `!= "DRAFT"`), which the original implementer got wrong reading only PRD prose. — `implementation/routes/statements.py:176-181`
- **§3.2 (creative submission create)** — *insert* — PRD stated "the named run must be one staged under that same agreement" but named no error code and no precedence. Pinned it as a rung-5 body-foreign-key failure earning `ERR_RUN_NOT_FOUND`, decided before the version guard and before the agreement's own state. — `implementation/routes/submissions.py:37-49`

**No edit for item 1** (`activated_at` on an agreement): the impl has no such field (`routes/agreements.py:37-56`, `activate_agreement` only flips status and touches the row), and §2.4's clock-stamped-field list already omits any agreement-level `activated_at`. Pure test-artifact over-assertion; PRD already determines it. Likewise **no edit for the §3.9 `mg_prorated_cents` literal** (39062) — pure test-literal arithmetic bug; PRD's formula and `calc.mg_prorated_cents` already agree.

## Per-edit pre-edit search log

**Edit 1 — §3.6 confirm gate**
(a) Subject: confirm-time slot capacity gate; the slot ledger quartet (`released/held/sold/available_capacity`); `ERR_SLOT_CAPACITY_EXCEEDED`; the `OPEN`/`HELD_FOR_BUYOUT` -> `SOLD_OUT` flip.
(b) Enumerated/read: `routes/orders.py` in full — `place_order` (creation gate at :68 uses `available_capacity`, untouched by my wording), `confirm_order` (:140-174), `release_sold_seats` (:222-235), `cancel_order` (:266-291); `services/derive.py:244-248` `recompute_available`; `routes/slots.py` in full — `release` (:135-139 sets `released_capacity = base_capacity`, so a buyout's `released - sold` equals `party_size` exactly), `status-decisions` SUSPEND/RESUME/CANCEL/CLOSE_OUT (:152-183); `routes/runs.py:230, 348-349` (lift-suspension re-derivation); `routes/inspections.py:20` (`SUSPENDABLE_SLOTS`); grep for `ERR_SLOT_CAPACITY_EXCEEDED` across `implementation/` -> exactly two sites (creation, confirmation), matching §2.7 rung 15's "order creation, order confirmation"; cross-checked PRD §3.5 para 239 (buyout mirror pair) and para 241 ("a confirmation that drives `available_capacity` to 0 moves the slot `OPEN -> SOLD_OUT`") and §2.5's conserved slot identity.
(c) Adjustment: scoped the new measure to *confirmation only* and phrased it as "the hold this order itself took at creation ... is not counted against it" rather than a general re-definition of `available_capacity`, so the creation gate, the buyout branch (where `released - sold == party_size`), §2.5 conservation and the §3.5 sold-out prose all stay true. Deliberately left the slot-state refusal code unnamed (impl uses `ERR_SLOT_INVALID_STATE`, out of Step 7 scope).

**Edit 2 — §3.9 recompute own-state gate**
(a) Subject: royalty-statement own-state gates, specifically the source state of `recompute-provisional`.
(b) Enumerated/read: `routes/statements.py` in full — `recompute_provisional` (:180), `finalize_statement` (:209, accepts `DRAFT` and `UNDER_TRUEUP`), `settle_statement` (:250, `ISSUED` only), `open_statement` supersession (`SUPERSEDABLE` at :136) and `CLOSED_OUT_PERIOD` (:107); grep for `ERR_STATEMENT_INVALID_STATE` -> three sites, all in `statements.py`; §2.7 rung 8 and the §4 endpoint row "Re-run the provisional accrual on a draft statement".
(c) Adjustment: added the explicit "in contrast with finalisation below, which names `UNDER_TRUEUP` as a source" so the new sentence cannot be read as narrowing finalisation's two accepted sources; said nothing about `SUPERSEDED`/`ISSUED`/`SETTLED` beyond the generic "any other state", which is exactly what `!= "DRAFT"` does.

**Edit 3 — §3.2 submission run-scope code**
(a) Subject: body-foreign-key scoping of `run_id` on submission creation, and its precedence against the version guard and the licence-state gate.
(b) Enumerated/read: `routes/submissions.py:28-53` (resolve agreement, resolve run, scope check -> `ERR_RUN_NOT_FOUND`, then rung 7 version, then rung 9 `ERR_AGREEMENT_NOT_ACTIVE`, then rung 16 scope); grep for `ERR_RUN_NOT_FOUND` across `implementation/` -> only `routes/submissions.py:41` plus the generic `services/derive.py:22` fetch table, so no other endpoint imposes a run-scope narrowing I would be over-generalising; checked the other body `run_id` callsites for contrast — `routes/statements.py:89` (run only; `license_agreement_id` is copied from the run, so no scope test exists there), plus rooms/slots/orders/staff/shifts/inspections/kits; re-read §2.7 rung 5 (its `themed_room_id` example and its `ERR_RUN_NOT_FOUND` availability) and rung 7/rung 9.
(c) Adjustment: kept the sentence strictly local to submission creation and expressed precedence via the rung-5 reference plus a concrete "before the version guard and before the agreement's own state," rather than asserting any general rule about run-scoped foreign keys elsewhere in the API.

Scratch dir `.scratch/step8` removed (parent untouched). `PRD.md`, `implementation/`, `test_suite/`, `test_helpers/` and `worklog.md` were not modified.

Orchestrator verification: PRD_FINALIZED.md is 478 lines with an intact §5 tail; `diff` against PRD.md shows exactly 6 changed lines (3 revise/insert pairs), and the md5sums differ (`4b929c65...` vs `fa75eabf...`) — so the file is a genuine minimal patch, not an unedited copy and not truncated.

## Step 9: Complete PRD — 2026-09-06T07:16:00.000Z

Orchestrator decision (recorded per the autonomy instruction): Step 9 was run as **four sequential module-partitioned passes over one shared `PRD_COMPLETED.md`**, rather than a single scan. Rationale: with 73 endpoints, 82 errors, 13 entities, 14 calculations and a 17-rung ladder, a one-shot scan cannot hold the whole surface in context and reliably emits a byte-identical file — i.e. the scan silently never ran. Pass 1 performed the one-time `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2-4 were explicitly forbidden from repeating it. Partition: pass 1 = platform (app/db/errors/middleware/response/validate) + clock/venues/agreements/submissions; pass 2 = runs/rooms/slots/staff/shifts + derive.py; pass 3 = guests/orders/inspections/kits/statements + calc.py; pass 4 = reconciliation only. Each pass wrote `.scratch/step9/passN_notes.md` handing its cross-partition findings to the next; pass 4 existed because partitioned passes *report* cross-pass contradictions instead of fixing them.

Edit totals: pass 1 = 18 (14 ambiguity-pins, 4 mismatch-revisions), pass 2 = 36 (30 pins, 6 mismatches), pass 3 = 32 (28 pins, 3 mismatches, 1 self-correction), pass 4 = 2 reconciliation edits. **88 edits total, 138 of 478 lines changed.**

### Pass 4 (reconciliation) summary, verbatim:

Pass 4 (reconciliation) complete. **2 edits**, both in §2.5, both landing on lines passes 1-3 had already touched — so the cumulative diff is unchanged at 138 lines.

**(a) — `CLOSED_OUT` seat identity follow-on. EDITED (§2.5, line 105).** Verified in code: `release_sold_seats` (`routes/orders.py:222-235`) has no slot-status gate, and neither does the `PENDING` branch of `cancel_order` (`orders.py:265-281`) — both call `derive.recompute_available` unconditionally. A `CONFIRMED` order on a `CLOSED_OUT` slot is reachable. Pass 3's handoff said "cancellation of a `CONFIRMED` order"; I found it is **both** paths, so I pinned the general form. Reworded to "is deliberately left, **at that moment**, with `released_capacity` above the sum of the other three" plus a sentence that the relaxation is not permanent. This also removes the conflict with pass 3's §3.6 sentence (line 259).

**(b) — two-decimal serialisation. EDITED (§2.5, line 100).** `two_dp` is `float(rhu(value,2))` (`services/calc.py:119-121`) and all nine figures are stored as Python floats, so the whole family serialises as bare JSON numbers with trailing zeros dropped — not just `refund_pct`. Pinned uniformly: plain JSON number never a string, two decimals is a rounding rule not a rendering rule, `1.0` not `1.00`. The one exception — a `SCHEDULED` inspection's integer `measured_egress_width_cm` of `0` (`inspections.py:42`) — is named explicitly, closing pass 1's item 2 in the document rather than only in the notes.

**(c) — rung 12's code list. NO EDIT; §3 prose left authoritative.** Both §3.2 (line 181) and §3.6 (line 255) already carry an explicit forward reference ("which is why ... is absent from rung 12 of §2.7"), and rung 12's guard list never claims either endpoint. The document does not say two different things; consolidating would have meant editing three passages to gain nothing.

**(d) — `derive.require_rooms`. NO EDIT; re-confirmed.** `grep -rn require_rooms` returns exactly one hit, the definition at `services/derive.py:191`. The only `ERR_RUN_HAS_NO_ROOMS` raiser is `compute_effective_capacity` with `tolerate_empty=False`, reached from exactly four call sites — `slots.py:71`, `:130`, `:163`, `runs.py:168` — precisely the list §3.3 and rung 15 already give.

**Sweep 1. Seat-capacity identity and status scoping — no contradictions beyond (a).** Compared §2.5 line 105 against §3.5 lines 231/233/239/241/243, §3.6 lines 253/255/259, §3.7 lines 273/275/279, §3.8 lines 283/287, against `slots.py:174-183`, `runs.py:19-20`, `runs.py:220-239`, `runs.py:345-350`, `inspections.py:20,74-86`, `inspections.py:88-109`, `derive.py:244-248`. All agree.

**Sweep 2. Rung ordering — no contradictions.** Checked rung 6 vs 8/9 (`rooms.py:34-43`), rung 13 vs 15 (`slots.py:32-39,71-72,130-132`), rung 8 vs §3.6 line 257 (`guests.py:80-85`), rung 9 vs §3.8 line 285, rung 10 vs §3.2 line 159 and §3.7 line 279, §3.4 line 213 (`staff.py:95-101`), §3.8 line 289. Two rung-placement *gaps* (not contradictions) left alone as out of scope: the run-state gates on inspection booking and themed-room creation are cross-entity gates rung 9 does not list, but rung 9 asserts no order the §3 prose contradicts and on both endpoints the gate is the only state test.

**Sweep 3. Free-text persistence — no contradictions.** Audited all 19 `note`/`memo`/`reason`/`package_note` inputs. Every discard claim is backed by a `body.string(...)` call whose return value is never bound. The three persistence sites are `venues.py:145,149`, `submissions.py:149,156`, `inspections.py:177`. Pass 3's self-corrected line 277 correctly omits all three persisting families.

**Verification numbers:** `wc -l` = 478; `diff | grep -c '^[<>]'` = 138 in 67 hunks, all balanced 1-for-1; `tail -5` still ends on `| ERR_STATEMENT_PERIOD_ISSUED | 409 |`; §5 catalogue 82 rows in both files, `grep -c '^#'` = 27 in both with an empty heading diff. `.scratch/step9` removed; parent `.scratch/` left in place.

### Orchestrator final verification

- `workspace/PRD_COMPLETED.md` — 478 lines / 133,462 chars, md5 `aeb509e5...` vs PRD_FINALIZED's `fa75eabf...`. **Not byte-identical**, so the scan genuinely ran (the known failure mode). 138 changed lines, 27 headings in both files, tail intact on the last §5 row — not truncated.
- PRD chain sizes: PRD.md 111,290 -> PRD_FINALIZED.md 112,125 (+826) -> PRD_COMPLETED.md 133,462 (+21,337).
- `find workspace/implementation -name '*.py' -newer workspace/SWEEP_DONE` is EMPTY — Steps 8 and 9 were documentation-only and did not touch the implementation, so the green sweep still describes the shipped code.
- Re-read all 8 `workspace/implementation/results.$i.json`: every round `passed=125 total=125`.

PIPELINE COMPLETE.
