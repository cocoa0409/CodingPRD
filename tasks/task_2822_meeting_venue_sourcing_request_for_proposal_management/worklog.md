# Worklog — task_2822_meeting_venue_sourcing_request_for_proposal_management

## Step 1: Create task directory — 2026-09-05T02:34:00.000Z

Created `tasks/task_2822_meeting_venue_sourcing_request_for_proposal_management/` and `tasks/task_2822_meeting_venue_sourcing_request_for_proposal_management/workspace/` (pre-assigned path; no index auto-allocation).

## Step 2: Generate scaffold — 2026-09-05T04:22:00.000Z

Clean lint achieved. All three artifacts are complete.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    58
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1221

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files: SCAFFOLD.yaml 2949 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 2049 lines, SCAFFOLD_CORNER_DESIGN.yaml 5713 lines.

Scaffold surface (§1.0–§1.7):
- `domain_name: meeting-venue-sourcing-rfp`, `api_prefix: /sourcing`, archetypes multi_party_negotiation / pricing_engine, topology `graph`, state-machine shape `cyclic`, role_model `segregation_of_duties`, consistency `immediate`, layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.
- 14 entities (MeetingEvent, RateBenchmark, Venue, VenueShortlistEntry, SiteInspection, Rfp, Proposal, BidEvaluation, NegotiationCounter, Contract, ApprovalStep, DepositInstallment, PostEventReport, SupplierPerformanceReview), 9 state machines, 2 concurrency rules (award-with-stale-event, counter-with-stale-proposal), 11 calculations, 51 validations, 58 endpoints, 63 errors, 5 roles.

Design files:
- §1.8: 9 rule_ids × 2 = 18 instances.
- §1.9: 9 sections / 79 instances — 63 with full `test_recipe`, 16 `excluded_because` stubs (each cites an existing §1.8 instance by name). Breakdown: entities 12, state_machines 16, calculations 11, validations 9, endpoints 6, errors 13, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1.
- Error coverage audit: all 63 declared error ids triggered by at least one instance.

Two SCAFFOLD.yaml edits made to keep codes reachable:
1. Validation priority 40 now reads `IN {CONTRACTED, COMPLETED} for post-event-report` (COMPLETED admitted only so priority 84 can report `ERR_POST_EVENT_REPORT_EXISTS`).
2. Four sub-resource GET paths renamed to the `{id}` parent-placeholder form: `/sourcing/proposals/{id}/bid-evaluations`, `/sourcing/proposals/{id}/negotiation-counters`, `/sourcing/contracts/{id}/approval-steps`, `/sourcing/contracts/{id}/deposit-installments`.

All numeric asserts are literals produced by executing the formulas (contracted 447844.84 vs actualized 422797.82, deposits 129651.08 → 44081.37/42784.86/42784.85, rebate boundary 150000.00 → 147000.00 vs 149999.99 → 149999.99, post-event realized 427203.31 / savings 72796.69, AV tier grid, ps-grid 69722.61 at variance −0.0524, rate-299 grid 487568.31 at variance 0.1500). No sibling task directory was read.

Orchestrator check: grepped all three scaffold files for the difficulty directive text ("harder than expert") — zero hits, so no leak path into PRD.md. workspace/ and worklog.md survived Step 2 intact.

## Step 3: Copy shared files — 2026-09-05T04:23:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T04:44:00.000Z

PRD generation for task 2822 is complete.

**Output:** `workspace/PRD.md`
- **Final line count: 521 lines** (117,976 bytes)
- **Last section heading: `## 5. Error Code Catalogue`** — the file ends on the last row of the 63-row error table (`| \`ERR_ACTUALS_EXCEED_CONTRACT\` | 422 |`), a real section boundary, no audit footer.
- Structure: §1 Introduction, §2.1–§2.11 (11 global subsections, §2.2 byte-identical to `section-2.2-response-structure.md`), §3.1–§3.9 (9 workflow subsections), §4 with all 58 endpoints, §5 with all 63 errors.
- Written incrementally via `cat >> PRD.md` heredoc appends plus targeted edits; §4/§5 tables generated programmatically from `SCAFFOLD.yaml` to eliminate transcription error.
- Constraints honoured: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or grepped, and no sibling task directory was read.

Hard Contract reports:

```
Field-name coverage check (Contract 1):
- names required (entity fields + common fields + request/query inputs + path params + output_schema keys): 195
- names present verbatim in backticks: 195
- missing: 0
Status: PASS
```

```
Rule coverage check (Contract 2):
- validations[] with priority: 51 checked, 51 expressed in prose (19-band ordered ladder in §2.8 + §3 restatement), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (award/expected_event_version/ERR_STALE_EVENT_VERSION 412; counter/expected_proposal_version/ERR_STALE_PROPOSAL_VERSION 412), 0 missing
- state_machines[].transitions: 61 checked across 9 machines, 61 fully expressed, 0 missing; all 61 states/terminal states named in backticks
- calculations[]: 11 checked, 11 fully expressed with constants, evaluation order, rounding and inclusivity; both dual-variant pairs (CONTRACTED_BASIS/ACTUALIZED_BASIS, RECENCY_WEIGHTED/SIMPLE_MEAN) rendered, 0 missing
- validations[] conditions: 51 checked, 51 matchable to their error_id outside the §5 table, 0 missing
- endpoints[].side_effects / applies_to: 58 endpoints checked, every side_effect and every applies_to set expressed, 0 missing
- entities[].fields[] structured content: 195 checked (defaults, initial values, null-at-creation, enum constraint sets — all 100% of enum literals present), 0 missing
- sibling-branch symmetry: 8 groups checked, 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1193
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two scaffold-fidelity defects found and repaired during verification:
1. §3.7 originally said a bid was awardable from `SUBMITTED`, `UNDER_REVIEW`, `COUNTERED` or `REVISED` and invented an error id `ERR_PROPOSAL_NOT_AWARDABLE`. The scaffold admits only `UNDER_REVIEW` and reports `ERR_PROPOSAL_STATE_INVALID` (priority 43). Corrected.
2. The award-time guards `ERR_VENUE_SUSPENDED`, `ERR_PREFERRED_PROGRAM_REQUIRED`, `ERR_RATE_BENCHMARK_NON_COMPLIANT`, `ERR_BID_EVALUATION_REQUIRED` and `ERR_BUDGET_CEILING_EXCEEDED` were only in the §2.8 ladder; a dedicated §3.7 paragraph now states each with its inclusivity semantics (notably that the budget-ceiling test uses the pre-rebate total).

Orchestrator truncation guard (per known doc-generator failure mode): read the PRD tail and the full heading list. File ends mid-table-but-complete at `| `ERR_ACTUALS_EXCEED_CONTRACT` | 422 |`, the 63rd error row — a real section boundary, not a mid-sentence cut. All 27 expected headings present through §5. Grepped PRD.md for "harder than expert", "expert level" and "scaffold" — zero hits, so the Step 2 difficulty directive did not leak into the implementer-facing contract. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T05:21:00.000Z

Stage 5 is complete. Both output directories are at the task root, fully audited.

**Stage 1 — `test_helpers/`** (9 files, 2167 lines)

| file | lines |
|---|---|
| `api_errors.py` | 167 (all 63 error ids + `set_error_http_status_map` registration at import) |
| `constants.py` | 161 |
| `test_users.py` | 99 (incl. mandatory `make_venue_rep_headers(venue_id)`) |
| `api_client.py` | 396 (one method per PRD endpoint, all 58 rows) |
| `types.py` | 151 |
| `factories.py` | 292 (money as JSON numbers, instants full ISO-8601 `.000Z`) |
| `assertions.py` | 224 |
| `fixtures.py` | 593 (5 tiers, 10 `build_*` world builders) |
| `__init__.py` | 84 |

**Stage 2 — `test_suite/`** (conftest + 12 files, 8755 lines, 334 tests collected, 0 collection errors)

| file | lines | tests |
|---|---|---|
| `conftest.py` | 28 | — |
| `test_01_bid_pricing_and_award_arithmetic.py` | 489 | 25 |
| `test_02_negotiation_and_award_cascades.py` | 733 | 44 |
| `test_03_guard_precedence_and_boundaries.py` | 740 | 30 |
| `test_04_temporal_windows_and_conserved_quantities.py` | 1010 | 47 |
| `test_05_resource_shapes_and_defaults.py` | 789 | 30 |
| `test_06_lifecycle_transitions.py` | 941 | 32 |
| `test_07_pricing_and_scoring_formulas.py` | 564 | 13 |
| `test_08_validation_ladder.py` | 494 | 14 |
| `test_09_endpoint_behaviours.py` | 556 | 17 |
| `test_10_error_catalogue.py` | 1331 | 52 |
| `test_11_access_control_and_separation_of_duties.py` | 492 | 17 |
| `test_12_concurrency_and_consistency.py` | 588 | 13 |

Coverage against the two design indices:
- Queue A (difficulty): 18/18 live instances translated, 0 skipped. Every instance got >=6 tests (minimum required was 2).
- Queue B (corner): 63/63 live non-stub instances translated, 0 skipped. All 16 `excluded_because:` stubs correctly emitted nothing, and every stub's `difficulty_instance` cross-reference resolves.
- 319 test functions / 334 collected items (the delta is `parametrize` expansion).

Audit results (scripts at `/tmp/task_2822_testgen/audit_tags.py`, `audit_citations.py`):
- Tag audit: 0 problems. Every test carries exactly one `Design:` line, it is the last docstring line, and all 81 distinct tags resolve to a real live instance — no untagged, dual-tagged, dangling, or stub-pointing tags.
- Citation audit: 319/319 tests contain a verbatim PRD fragment. One is only 39 chars (`test_02:379`) but is a complete PRD sentence (`The event moves `AWARDED -> CONTRACTED`.`), so C3 holds.
- Scaffold-leak scan: 0 occurrences of `scaffold`/`SCAFFOLD` anywhere in `test_suite/`.
- Hygiene: nothing written under `workspace/`, `workspace/implementation/` never read or created, `worklog.md` untouched, no `__pycache__` left behind, no server started, no `pkill` run.

Assertions deliberately narrowed under the PRD-first filter (worth knowing at Step 7). No whole instance was skipped, but sub-assertions the PRD does not uniquely derive were dropped rather than weakened. The recurring pattern is `created_at`/`updated_at`/`completed_at` pinned to the logical clock: PRD §2.5/§2.6 enumerate exactly which instants are clock-stamped (`issued_at`, `closed_at`, `submitted_at`, `evaluated_at`, `resolved_at`, `decided_at`, `executed_at`, `terminated_at`, `paid_at`) and these are not among them, so tests assert format + version ladder instead of the literal. Three substantive design-vs-PRD conflicts flagged:
1. `Corner/calculations/cancellation_fee_at_exactly_181_days_...` expects `approval_state == CANCELLED` and `signature_state == EXECUTED` post-termination; the PRD says termination moves `signature_state EXECUTED -> TERMINATED` (the `CANCELLED`/`VOIDED` pairing belongs to supersede). The test asserts `TERMINATED` and omits `approval_state`.
2. `Difficulty/transitive_cascade/award_cascade_four_hops_...` expects `shortlisted_venue_count == 2` after the runner-up cascades `RFP_ISSUED -> ELIMINATED`; PRD §3.2 uniquely derives 1. That single assertion is absent; the instance's other 12 facts are covered.
3. `Corner/errors/executed_contract_...` expects `cancellation_fee_usd == 0.00` on a fresh contract; PRD §3.7 says it starts null. The test asserts null.

## Step 6: Generate implementation — 2026-09-05T05:21:00.000Z

All modules are written and verified. Killed both smoke servers by PID; ports 57312/57488 are free.

Modules written (per-file line counts). Root (`workspace/implementation/`): `start.sh` 10, `requirements.txt` 1, `app.py` 109, `errors.py` 90, `clock.py` 92, `money.py` 44, `db.py` 63, `response.py` 57, `middleware.py` 75, `validate.py` 321, `enums.py` 84, `lookup.py` 180, `serializers.py` 304. `services/`: `calc.py` 309, `flows.py` 192, `rollups.py` 97, `__init__.py` 0. `routes/`: `contracts.py` 455, `proposals.py` 328, `rfps.py` 213, `venues.py` 171, `inspections.py` 164, `events.py` 144, `shortlist.py` 142, `reports.py` 109, `benchmarks.py` 65, `clock_routes.py` 18, `__init__.py` 0. Total 3,837 lines. Every file >200 lines was built with chunked `cat >>` appends and `wc -l`-checked.

Endpoint coverage: 58 / 58 declared endpoints implemented, zero extra — extracted the `(method, path)` pairs from `SCAFFOLD.yaml`'s `endpoints:` block, normalised path params, and diffed against Flask's `url_map`: `declared 58, implemented 58`, empty symmetric difference. (An earlier "56 declared" note was a miscount.)

Machine-verified RBAC: for all 58 endpoints x 5 roles, probed live and compared `ERR_FORBIDDEN_ROLE` against the scaffold's `roles:` list — 0 mismatches. Diffed every `error_id -> HTTP status` pair in PRD §5 (63 codes) against `errors.py`: one real bug found and fixed (`ERR_VENUE_ROOM_BLOCK_CAPACITY_EXCEEDED` was 409, PRD says 422).

Fresh-boot smoke test: passed. `bash start.sh` on a fresh process (high random port) was serving in 0.56 s; store empty on boot (all 10 list endpoints return `[]` with `total_count 0`), logical clock at the mandated default `2026-08-01T00:00:00.000Z`, no seeding anywhere.

Two scripted end-to-end runs against a clean boot, all assertions green:
- Happy path — benchmark -> 2 venues -> event -> lock -> 2 shortlist entries -> promote -> RFP -> issue (2 `INVITED` shells) -> 2 submissions -> close -> 2 evaluations -> cost-comparison -> stale-version award refused 412 -> award 201 -> route (`MANAGER`,`VP`) -> decide both -> sign -> countersign -> `EXECUTED` -> deposit schedule -> duplicate refused 409 -> out-of-sequence pay 409 -> wrong-amount pay 422 -> pay -> clock advance -> post-event report 201 -> duplicate report 409 -> performance review.
- Edge paths — counter/revise cycle (OCC 412 on `expected_proposal_version`), approval rejection cascade (`REJECTED`/`VOIDED`, event back to `BID_REVIEW`, `committed_spend_usd` -> 0.00, pending steps `SKIPPED`), out-of-order/role-mismatch/segregation-of-duties/duplicate-approver guards, `ERR_CONTRACT_ALREADY_EXECUTED` on re-award, termination (fee + rebooking credit, installments cancelled, room nights released, event `CANCELLED`), decline/withdraw + ownership 403.

Spot-checked arithmetic matches the PRD's pinned orders: comp nights `700/40 = 17` -> 683 paid; rebate tier `0.035` on `460842.35` -> `444712.87`; `peak_rooms_per_night = ceil(683/3) = 228`; deposit `133413.86` split `45360.71 / 44026.57 / 44026.58` (residual on installment 3) with due dates at -180/-90/-30 days; cancellation fee `88200.00 x 0.25 = 22050.00` with credit `8820.00`; money identity held to the cent through award, reject, terminate and closeout.

Three "FAIL" lines in the second script's output were the agent's own wrong expectations, not defects — `ERR_APPROVAL_LEVEL_ROLE_MISMATCH` and `ERR_SEGREGATION_OF_DUTIES` are 403 and `ERR_DUPLICATE_APPROVER` is 409 in PRD §5, which is what the server returned.

Two fidelity notes on PRD-internal conflicts, resolved toward §2.8's explicit ladder: (1) §3.9 lists `ERR_BENCHMARK_NOT_CONFIGURED` fourth in the post-event-report ladder while §2.8 puts it at band 15 — unreachable either way, since submission already required the benchmark and benchmarks are immutable, so followed §3.9's local order; (2) §3.9 mentions `ERR_DEPOSIT_ALREADY_SCHEDULED` before the `EXECUTED` state check, but §2.8 band 10 explicitly orders `ERR_CONTRACT_STATE_INVALID` first, so state wins (reachable only on a terminated contract that already has a schedule).

`worklog.md` untouched by the subagent, no sibling task read, no broad `pkill`. Scratch lived in `/tmp/task_2822_implgen/`.

Orchestrator layout check after Steps 5+6: `test_helpers/` (9 files) and `test_suite/` (13 files) are at the task root, not under `workspace/`; `workspace/` holds only INSTRUCTION.md, PRD.md, implementation/; exactly one `worklog.md` in the tree. Steps 5 and 6 were launched in a single assistant message so the impl generator's process began before `test_suite/` existed on disk.

## Step 7: Run tests and iterate — 2026-09-05T05:47:00.000Z

Loop complete — the suite is green.

**Iterations run:** 2 (each an 8-round parallel `setsid nohup` sweep, `--isolation per-test-server`, 334 tests/round).

**Iteration 1 findings:** 3 failures, identical in all 8 rounds (fully deterministic, no flakiness anywhere in the suite).

**Tests deleted:** none. All three failures survived STEP 1 (PRD verbatim-covers the rule and uniquely determines the outcome) and were resolved at STEP 2 as test bugs.

**Fixes applied to `test_helpers/`:** none — the fixture/factory layer was already PRD-faithful (money as JSON numbers, 3-fractional-digit instants, `VenueRep` headers carrying the venue `id`, distinct approver identities per control level).

**Fixes applied to `test_suite/`:**
- `test_suite/test_05_resource_shapes_and_defaults.py` — added the missing `PROGRAM_ADMIN_HEADERS` name to the `from test_helpers import (...)` block. Both tests in `TestVenuePreferredStatusDefault` (`test_registering_without_a_preferred_status_stores_none`, `test_defaulted_venue_is_discoverable_through_the_status_filter`) died at collection-time-equivalent `NameError`, never reaching an assertion. The identifier exists and is exported by `test_helpers/__init__.py`; the import list simply omitted it. No assertion was weakened.
- `test_suite/test_06_lifecycle_transitions.py` — `test_locked_event_admits_the_same_shortlist_entry` asserted the meeting event stood at `version` 2 after create -> lock -> add-entry. PRD §3.2 states verbatim "Creating an entry also advances the parent meeting event's `version` by 1", and §2.4 confirms cross-aggregate writes advance the touched row's version, so the correct expectation is 3 (create=1, lock=2, entry=3). The implementation returned 3 and was right; the assertion was a mistranslation. Corrected to 3 with the PRD quote inline. The sibling assertion at line 183 (`test_locking_an_already_locked_requirement_is_refused`, expecting 2 after a refused second lock) is correct and was left alone.

**Fixes applied to `implementation/`:** none. No PRD-required check was removed or weakened, no endpoint/field/side-effect was added, and storage remains in-memory dicts only.

**Final sweep — all 8 rounds green:** round 1: 334/334, round 2: 334/334, round 3: 334/334, round 4: 334/334, round 5: 334/334, round 6: 334/334, round 7: 334/334, round 8: 334/334. Zero failures, zero errors, zero skips in every round.

Orchestrator verification of the sweep artifacts (not taken on the subagent's word): all eight `workspace/implementation/results.{1..8}.json` exist on disk, ~116 KB each, written 05:46, and each independently parses to `passed=334 total=334 failed=0 errors=0 skipped=0`. The sweep genuinely ran.

Step 8 skip decision: NOT skipped. The skip condition requires zero deletions AND zero `test_suite/` fixes AND zero `test_helpers/` fixes AND zero `implementation/` fixes; Step 7 made 2 `test_suite/` fixes across 2 iterations, so Step 8 runs. Noting for expectation-setting that neither fix indicates PRD silence — one was a pure Python `NameError` (missing import) and the other a test-side mistranslation of a rule the PRD already pins verbatim — and `implementation/` was never touched, so a byte-identical or near-identical `PRD_FINALIZED.md` is the legitimate outcome here.

## Step 8: Finalize PRD — 2026-09-05T05:50:00.000Z

Done. Verified all three Step 7 items against `implementation/` and concluded no PRD edit is warranted; `PRD_FINALIZED.md` is byte-identical to `PRD.md`.

**Line counts:** PRD.md 521 lines / PRD_FINALIZED.md 521 lines — 0.0% delta (md5 identical: `215ead5fd8765493c9f51fe43e44f81c`).

**Changes:** none. Every `<step_7_diff>` item traces to a test-side defect over behavior the PRD already determines verbatim, and Step 7 applied zero `implementation/` fixes and zero deletions.

Per-item verification (subject -> impl paths enumerated -> wording adjustment):

1. `test_05_resource_shapes_and_defaults.py` missing `PROGRAM_ADMIN_HEADERS` import
   - (a) Subject: the default value of `preferred_supplier_status` on venue registration, and the venue-collection equality filter on that field.
   - (b) Impl paths enumerated (grepped `preferred_supplier_status` across the whole tree, then read): `routes/venues.py:30-31` (`validate.opt_enum(..., "NONE")` default), `:42` (row write), `:57-59` (standing-change endpoint), `:75-85` (exact-equality list filter); plus every consumer of the field: `routes/shortlist.py:48,64,90`, `routes/inspections.py:51`, `routes/contracts.py:185`, `services/flows.py:124,133`, `services/calc.py:132-144` (compliance tiering), `services/calc.py:202-207` (approval routing), `serializers.py:62`.
   - Finding: impl stores the literal string `"NONE"`, exactly as PRD §3.1 states ("when the field is omitted the venue is registered as `NONE`"), and the filter is plain equality, exactly as PRD §2.3 states. This item is a pure Python import bug — not a PRD defect.
   - (c) No wording adjustment (no edit).

2. `test_06_lifecycle_transitions.py::test_locked_event_admits_the_same_shortlist_entry` — expected `version` 2, impl returns 3
   - (a) Subject: how many times a meeting event's `version` advances across create -> lock-requirements -> add-shortlist-entry.
   - (b) Impl paths enumerated: `routes/events.py:56-72` (create seeds row, version 1, no extra touch), `:75-84` (`lock_requirements` — status flip plus a single `touch(event)`, no child-row writes), `routes/shortlist.py:20-73` (`create_entry` — writes the entry then `rollups.refresh_shortlisted_count(event)` + `touch(event)`); also the sibling event-touching paths a version-wording edit would have to remain true for: `shortlist.py:76-100` (`promote_entry`), `:103-118` (`eliminate`), and the generic `db.touch` helper.
   - Finding: 1 + 1 + 1 = 3 is uniquely determined by PRD §3.2 ("The event's `version` advances by 1" on lock; "Creating an entry also advances the parent meeting event's `version` by 1") reinforced by §2.4's per-row independent version rule. The assertion was a mistranslation; impl is right and PRD already pins it.
   - (c) No wording adjustment (no edit).

3. Sibling assertion left alone (`test_locking_an_already_locked_requirement_is_refused`, expecting 2)
   - (a) Subject: whether a refused lock mutates the event's `version`.
   - (b) Impl path: `routes/events.py:78-81` — `ERR_EVENT_STATE_INVALID` is raised before `touch(event)`, so no version bump; consistent with PRD §3.2's "requires the event to be in `DRAFT`" plus §2.4's "increases by exactly 1 on every mutation".
   - (c) No wording adjustment (no edit).

Also checked in passing that PRD §3.1's stated `NONE` default doesn't conflict with any downstream reader (compliance tiering treats `NONE` as its own branch at `services/calc.py:144`; approval routing keys off `PROGRAM_COMPLIANCE_STATUSES` at `:207`) — no latent §3.1 mismatch to pin either.

Orchestrator note: a byte-identical `PRD_FINALIZED.md` is the correct Step 8 outcome when Step 7 made no `implementation/` fixes — the finalizer's mandate is a minimal diff over the Step 7 fix sites, and both fix sites turned out to be test-side defects (a missing Python import; a mistranslated version count) over rules the PRD already pins verbatim. Manufacturing edits here would have introduced fresh mismatch. Step 9 (which always runs, and does a full impl scan rather than a Step-7-scoped one) is the step that must not come back identical.

Step 9 plan: run as THREE sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (3,837 lines of implementation across 24 modules is too much for one scan to cover exhaustively). Pass 1 does the `cp` from `PRD_FINALIZED.md` and owns the cross-cutting/global modules; passes 2 and 3 must NOT re-copy, and edit the same file in place.
- Pass 1 (global/cross-cutting): app.py, middleware.py, errors.py, response.py, db.py, clock.py, money.py, validate.py, enums.py, lookup.py, serializers.py, routes/clock_routes.py.
- Pass 2 (sourcing front half): routes/venues.py, routes/benchmarks.py, routes/events.py, routes/shortlist.py, routes/inspections.py, routes/rfps.py, services/rollups.py.
- Pass 3 (bidding + contracting back half): routes/proposals.py, routes/contracts.py, routes/reports.py, services/calc.py, services/flows.py.

## Step 9: Complete PRD — 2026-09-05T06:15:00.000Z

Run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place with targeted `Edit` calls and did not re-copy. Aggregate: **62 changes — 42 ambiguity-pins, 20 mismatch-revisions.** `PRD_FINALIZED.md` 521 lines / 117,976 chars -> `PRD_COMPLETED.md` 523 lines / 134,768 chars (+2 lines, +16,792 chars, +14.2%). Heading structure byte-identical to `PRD.md` (verified by diffing the `^#` line sets) — no new sections were added by any pass.

### Pass 1 — cross-cutting / global layer (app, middleware, errors, response, db, clock, money, validate, enums, lookup, serializers, clock_routes)

13 ambiguity-pins, 4 mismatch-revisions. 14 in-place line revisions plus one 2-line paragraph insert in §5.

- §2.2 success bullets — insert — ambiguity — `api_request_id` is literally `req_` + exactly 20 chars from `A`-`Z`/`0`-`9` — `response.py:9,18`
- §2.2 success bullets — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall clock — `response.py:24`
- §2.2 error format — revise — mismatch — envelope covers the 5xx fallback too, not "4xx" only — `app.py:87-95`
- §2.3 pagination — insert — ambiguity — unparseable/empty `limit`/`offset` also `ERR_INVALID_PAGINATION`; `offset` unbounded; past-end page returns empty `data` with full `total_count` and `has_more` false — `validate.py:301-315`, `response.py:45`
- §2.3 ordering — insert — ambiguity — `created_at` ties (common under a frozen clock) break by write order, never by `id` — `db.py:61-63`
- §2.3 filters — insert — ambiguity — bad enum filter value is `ERR_INVALID_REQUEST` (400); empty filter value is ignored; exact-equality matching only — `validate.py:256-270`
- §2.4 identity — insert — ambiguity — `id` is a lowercase canonical v4 UUID; the store is empty at boot with nothing pre-seeded — `db.py:26-29,38-39`
- §2.4 audit fields — insert — ambiguity — `created_at`/`updated_at` come from the logical clock, so an unmoved clock yields `updated_at == created_at` with `version` already advanced — `db.py:42-58`
- §2.5 request shape — insert — ambiguity — absent/whitespace body = `{}`; non-JSON or non-object body = `ERR_INVALID_REQUEST`; no `Content-Type` requirement; explicit `null` == omitted; required strings non-empty; numeric strings/bools are type failures; the 2-dp cap is money-only (percentages carry any scale) — `validate.py:18-28,31-51,56-73,112-170`
- §2.6 clock — insert — ambiguity — accepted instant grammar for `current_utc` and every instant body field (`T` or space, 1-9 fractional digits, optional `Z`/`+-HH:MM`, missing designator = UTC) — `clock.py:15-18,56-73`
- §2.8 band 3 — insert — ambiguity — ownership compares the addressed resource's `venue_id`, so a nonexistent id gives the band-4 404, and ownership precedes body shape checks — `proposals.py:51-52`, `contracts.py:298-299`
- §2.8 band 7 — revise — mismatch — band 6/7 order is not uniform: the 8 primary collections check the enum filter first, while contracts, bid-evaluations, negotiation-counters, approval-steps and deposit-installments check pagination first; path resolution always precedes pagination — `contracts.py:154-158,212-213,358-359`, `proposals.py:310-311,323-324` vs `venues.py:71-78`
- §2.10 cascades — insert — ambiguity — requests are serialised, so no caller sees a half-applied cascade — `app.py:27,49-60`
- §3.1 venue fields — insert — ambiguity — venue projection repeats the simple mean under a second key `simple_mean_score` — `serializers.py:64-65`
- §3.7 award guards — revise — mismatch — `ABOVE_BENCHMARK` is not a compliance verdict; awardable set is `COMPLIANT` / `COMPLIANT_WITH_VARIANCE` — `enums.py:38-40`
- §3.7 award cascade L4 — revise — mismatch — `NO_SHOW` is not an inspection status; only `COMPLETED`/`CANCELLED` exist beside `PLANNED` — `enums.py:23`
- §5 catalogue intro — insert — ambiguity — three transport fallbacks outside the table (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500) and trailing-slash-insensitive routing — `app.py:32,66-95`, `errors.py:75-77`

Modules pass 1 found already fully pinned: `money.py` (2-dp ROUND_HALF_UP, 4-dp variance, floor/ceil night counts, JSON numbers — all pinned by §2.5); `lookup.py` (every path/FK 404 code and sub-collection ordering matches §2.7/§2.3); `routes/clock_routes.py` (all-roles gating, 200 + empty data object; only the parser grammar in `clock.py` was silent); `errors.py` (status map matches the §5 table for all 61 catalogued ids; only the 3 uncatalogued fallbacks were missing); `enums.py` (every literal set exactly as declared — the two edits fixed PRD prose citing literals the enums never had); `middleware.py` (role sets match the §4 authorization column on all 60 routes, and the 5 ownership operations match §2.1/§2.8 band 3; only blank/trim/case header semantics were silent).

### Pass 2 — sourcing front half (venues, benchmarks, events, shortlist, inspections, rfps, rollups)

10 ambiguity-pins, 3 mismatch-revisions; 13 targeted `Edit` calls, 0 line delta (all in-paragraph). Claims verified against a running server (bound to a high random port, killed by PID).

- §2.3 — revise — mismatch — pass 1 asserted "a filter supplied with an empty value is treated as absent"; true only for identifier filters. `?destination_tier=` returns `ERR_INVALID_REQUEST` (verified 400). Scoped to identifier-typed filters and pinned empty enum values as unrecognized — `validate.py:256-263` vs `266-270`
- §2.3 — insert — ambiguity — cost-comparison ties beyond `created_at` break by write order — `routes/events.py:123`
- §2.5 — insert — ambiguity — four operations never parse the body at all (lock-requirements, promote entry, issue round, close round), so a malformed payload is ignored not rejected (verified: `{not json` -> 200) — `routes/events.py:77`, `routes/shortlist.py:79`, `routes/rfps.py:122,170`
- §2.7 — insert — mismatch — the body-FK list omitted `shortlist_entry_id` on planning a site inspection -> `ERR_SHORTLIST_ENTRY_NOT_FOUND` (verified 404, ahead of shape) — `routes/inspections.py:33`
- §2.7 — insert — ambiguity — a body FK arriving as a non-string is a shape failure (`ERR_INVALID_REQUEST`), not that key's 404 (verified 400); same pattern in all six FK sites — `routes/inspections.py:31`
- §2.8 band 5 — revise — mismatch — "five operations" -> "six operations" to match the corrected §2.7 list
- §3.1 — insert — ambiguity — `country` is a free-text non-empty string stored as supplied; no alpha-2 length or membership check (verified: `"UNITED STATES OF AMERICA"` accepted) — `routes/venues.py:25`
- §3.1 — insert — ambiguity — the standing PATCH reads only `preferred_supplier_status`, it is required, and restating the current standing is accepted and still bumps `version` (verified 1->2) — `routes/venues.py:57-60`
- §3.2 — insert — ambiguity — both uniqueness tests scan every entry the event has ever carried, so an `ELIMINATED` entry still reserves its venue and its `rank_seq` (verified both 409) — `routes/shortlist.py:37-42`
- §3.3 — insert — ambiguity — the event-overlap test reads the bare window (buffer excluded) with both ends inclusive, so merely touching the event interval intersects (verified: `window_end` == start_date 00:00:00.000Z -> 422) — `routes/inspections.py:57`
- §3.3 — insert — ambiguity — completing an inspection whose entry has moved past `INSPECTION_SCHEDULED` (e.g. to `RFP_ISSUED`) leaves the entry's status alone but still refreshes `inspection_count` and advances `version` — `routes/inspections.py:110-113`
- §3.3 — insert — ambiguity — cancel leaves the entry's status alone in the same "already left `INSPECTION_SCHEDULED`" case — `routes/inspections.py:135-136`
- §3.4 — insert — ambiguity — the minted `INVITED` shell's field values: every quoted term and derived figure null, `negotiation_round_count` 0, `submitted_at` null, `compliance_status` `NOT_EVALUATED` — `routes/rfps.py:84-115`

Modules pass 2 found already fully pinned: `routes/benchmarks.py` (publish/read/list, uniqueness, immutability, ranges, filters — zero edits); `services/rollups.py` (every counter — `shortlisted_venue_count`, `inspection_count`, `submitted_count`, `best_total_cost_usd` incl. the cross-round live set and tie-break, `budget_remaining_usd` — already stated as maintained invariants, zero edits); `routes/events.py` (only the tie-break nit).

### Pass 3 — bidding and contracting back half (proposals, contracts, reports, calc, flows)

19 ambiguity-pins, 13 mismatch-revisions; 0 line delta, +8,361 chars.

- §2.5 — revise — mismatch — "four operations never parse the body" was wrong; it is six, now enumerated (lock, promote, issue, close, decline, withdraw), plus the note that every `contracts.py` action does call `validate.body()` even when it reads no field — `routes/proposals.py:87,100`
- §3.4 — revise — ambiguity — pinned the exact set of ops that move `best_total_cost_usd`, and that decline/evaluate leave it alone — `services/rollups.py:37`
- §3.5 — insert — ambiguity — `room_nights_offered` is an integer >= 0 — `routes/proposals.py:27`
- §3.5 — insert — ambiguity — `service_charge_pct` has no upper bound (>1 accepted) — `routes/proposals.py:32`
- §3.5 — insert — ambiguity — `tax_pct` likewise unbounded above — `routes/proposals.py:33`
- §3.5 — revise — mismatch — full `cancellation_schedule` shape rules: non-empty array of objects, integer `days_before_arrival_min` >= 0, numeric `fee_pct` >= 0 unbounded and not 2dp-restricted, no sort requirement, duplicates allowed, no 0-tier requirement — `validate.py:req_schedule`
- §3.5 — revise — ambiguity — submission precondition order fixed to INVITED -> round ISSUED -> benchmark -> deadline, with the benchmark-beats-deadline consequence — `routes/proposals.py:56-70`
- §3.5 — revise — mismatch — decline's true side-effect scope (entry stays `RFP_ISSUED`, round and event unwritten) and the corrected rationale (declined venues are not re-invited, since `RFP_ISSUED` is not in `RFP_ELIGIBLE_ENTRY_STATUSES`) — `routes/proposals.py:87-95`
- §3.6 — revise — mismatch — numeric/text pairing by `term_category` is a form convention, not a validated rule — `routes/proposals.py:172-175`
- §3.6 — insert — ambiguity — `proposed_numeric_value` is <=2dp, unbounded, may be negative; text/note unconstrained — `routes/proposals.py:172`
- §3.6 — revise — mismatch — "nine optional fields" -> exactly eight, plus the explicit non-revisable list and explicit-`null`-as-omitted — `routes/proposals.py:209-236`
- §3.6 — insert — ambiguity — withdrawal advances the round's own `version` — `routes/proposals.py:110-111`
- §3.7 — insert — ambiguity — `award_note` is validated then discarded — `routes/contracts.py:40`
- §3.7 — insert — ambiguity — a foreign bid yields `ERR_PROPOSAL_NOT_FOUND` in the body-FK band, ahead of `ERR_EVENT_STATE_INVALID` — `routes/contracts.py:34-36`
- §3.7 — revise — mismatch — `concession_applied_usd` comes from step 11 of the re-run cost model (capped), not from a bid field — `routes/contracts.py:111`
- §3.7 — insert — ambiguity — cascade L1: `committed_spend_usd` set outright; `best_total_cost_usd`/`shortlisted_venue_count` recomputed; best falls to null unless an earlier round's live bid survives — `routes/contracts.py:136-141`
- §3.7 — insert — ambiguity — cascade L2 is scoped to the winner's own round; `submitted_count` recomputed (winner stays counted); round `version` advances only if the number changes — `services/flows.py:153`, `routes/contracts.py:131-134`
- §3.7 — insert — ambiguity — the superseded contract is the most recently created live one (not TERMINATED/VOIDED/REJECTED/CANCELLED) — `lookup.py:167-173`
- §3.8 — insert — ambiguity — rejection L3 recomputes `best_total_cost_usd`/`shortlisted_venue_count` and restores nothing — `services/flows.py:186-192`
- §3.8 — insert — ambiguity — `planner_signatory_name` required, non-empty, <=160 — `routes/contracts.py:284`
- §3.8 — insert — ambiguity — `venue_signatory_name` required, non-empty, <=160 — `routes/contracts.py:301`
- §3.8 — insert — ambiguity — the `RFP_ISSUED -> AWARDED` entry move is conditional on the entry still being `RFP_ISSUED` (an entry eliminated post-award stays `ELIMINATED`); `shortlisted_venue_count` refreshed at execution; event moves only from `AWARDED` — `services/flows.py:68-77`
- §3.9 — revise — mismatch — deposit-schedule guard order: `signature_state` EXECUTED (`ERR_CONTRACT_STATE_INVALID`) is checked before `deposit_total_usd is null` (`ERR_DEPOSIT_ALREADY_SCHEDULED`) — `routes/contracts.py:322-327`
- §3.9 — insert — ambiguity — `payment_reference` optional string <=120, empty string accepted — `routes/contracts.py:379`, `validate.py:56`
- §3.9 — insert — ambiguity — `termination_reason` required, non-empty, <=500 — `routes/contracts.py:409`
- §3.9 — revise — mismatch — cancellation tier: duplicate `days_before_arrival_min` resolves to the earlier array position (strict `>`); the "every schedule has a 0 tier so some tier always applies" claim replaced with the real fallback — no tier => fee `0.00` => credit `0.00` — `services/calc.py:185-199`
- §3.9 — insert — mismatch — the termination zeroing of `deposit_outstanding_usd` applies only to a contract that carries a schedule; otherwise it stays null — `routes/contracts.py:436-438`
- §3.9 — insert — ambiguity — `actual_room_nights` integer >=0 vs money fields; `notes` optional <=1000 — `routes/reports.py:26-29`
- §3.9 — revise — mismatch — post-event report admits `CONTRACTED` or `COMPLETED` (which is what makes the later `ERR_POST_EVENT_REPORT_EXISTS` sentence coherent) — `routes/reports.py:18,31`
- §3.9 — revise — mismatch — dropped the backticked `RECENCY_WEIGHTED` token (no such literal exists) — `services/calc.py:230-251`
- §3.9 — revise — mismatch — dropped the backticked `SIMPLE_MEAN` token, same reason — `services/calc.py:251`
- §2.8 — revise — mismatch — band 15's benchmark check is evaluated out of band for the post-event report, below band 17 (`ERR_EVENT_NOT_CONCLUDED`) and band 18 (`ERR_POST_EVENT_REPORT_EXISTS`); it keeps its band position on bid submission — `routes/reports.py:31-48`

Disposition of the five items earlier passes deferred to pass 3:
1. Undocumented `max_len` caps — all five resolved: 160/160 in §3.8 (sign, countersign), 120 in §3.9 (`payment_reference`), 500 in §3.9 (`termination_reason`), 1000 in §3.9 (`notes`). `validate.req_str` carries `min_len=1` (so "non-empty" is right for the three required ones) while `opt_str` has no lower bound, so the empty string being accepted for `payment_reference` was documented explicitly.
2. §3.5's 0-tier claim — resolved in both locations. §3.5 now says a 0 tier is not required by validation and forward-references §3.9; §3.9 pins the real fallback (fee `0.00`) instead of asserting some tier always applies.
3. `RECENCY_WEIGHTED`/`SIMPLE_MEAN` — resolved as mismatch. Grep across the whole implementation shows no such literal (only the constant `RECENCY_DECAY = 0.7`); the tokens were backticked as if they were emitted values, so both were removed and the variants now read as descriptive labels.
4. §3.5 decline rationale — resolved. The factual half is kept; the misleading "so a later negotiation round may still invite the same venue" is replaced by the true consequence.
5. §2.5 body-less ops — resolved. Extended from four to six to include `decline` and `withdraw`, with the explicit contrast that every `contracts.py` action parses the body even when it reads nothing from it.

Pass 3 partition-module status: none of the five modules was already fully pinned — each produced at least one change. All five are pinned as of exit. Deliberately NOT documented as unreachable dead code: `require_benchmark` on `revise`, the installment-cancel loops in `unwind_contract`/`reject_contract_cascade` (a non-EXECUTED contract can never own installments), `peak_rooms_per_night`'s zero-span fallback, `terminate`'s event-status conditional, `evaluate`'s null `benchmark_adr_usd`, and `reports.py:44-46`'s missing-contract branch.

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` exists, 523 lines / 134,768 chars, md5 `0fa9b3d89bc97d734b80ec1e8bb63e9a` — NOT byte-identical to `PRD_FINALIZED.md` (md5 `215ead5fd8765493c9f51fe43e44f81c`), confirming the scan actually ran rather than only performing the `cp`.
- Ends at a real section boundary: the final row of §5's error table (`| `ERR_ACTUALS_EXCEED_CONTRACT` | 422 |`), not a mid-sentence cut.
- `diff` of the `^#` heading line sets between `PRD.md` and `PRD_COMPLETED.md` is empty — no pass added, removed or renamed a section, as required.
- Grepped `PRD_COMPLETED.md` for "scaffold" and "harder than expert": 0 hits. The Step 2 difficulty directive never reached any implementer-facing document.
- Newest file under `implementation/`, `test_suite/`, `test_helpers/` is timestamped 05:35, while the all-green `results.{1..8}.json` were written 05:46 — the green sweep postdates every code edit, and Steps 8/9 touched only PRD documents, so the 8/8 × 334/334 result still describes the shipped artifact. No re-run needed.
- Removed the `__pycache__` directories the sweep left under `test_suite/`, `test_helpers/` and `implementation/`.

Pipeline complete through Step 9.
