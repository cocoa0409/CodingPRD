# Worklog — task_2882_equity_award_administration_trading_plan_oversight

## Step 1: Create task directory — 2026-09-05T11:01:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2882_equity_award_administration_trading_plan_oversight` and its `workspace/` subdirectory. Index 2882 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed and no index was auto-allocated.

## Step 2: Generate scaffold — 2026-09-05T12:44:00.000Z

Subagent summary (verbatim):

All three artifacts are complete and the linter is clean.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    63
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     74
  Calls scanned (§1.8+§1.9):  865
```

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3560 | 185393 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1715 | 105599 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4791 | 273615 |

**SCAFFOLD.yaml (§1.0–§1.7)** — `domain_name: equity-award-administration`, `api_prefix: "/"`, difficulty `expert_plus`. **13 domain entities**, **63 endpoints**, 10 state machines, 2 §1.2.1 OCC rules, 14 calculations, 35 ordered validations, 60 errors, 6 roles (PlanAdministrator, BoardMember, DelegatedOfficer, ComplianceOfficer, Participant, Auditor). Complexity profile: flat topology, branching state-machine shape, segregation_of_duties role model, immediate consistency, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`. Verified to contain neither `scaffold_difficulty_design` nor `scaffold_corner_design`.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — single top-level key; **9 rules × 2 instances = 18 instances** (dual_variant_calc, combinatorial_formula, circular_dependency_pin, state_cycle_revisit, cascade_depth, priority_collision, boundary_precision_check, empty_set_semantics, inclusive_exclusive_boundary).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — single top-level key; **9 sections, 81 instances** (74 full recipes + 7 `excluded_because:` stubs): entities 13, state_machines 13, calculations 10, validations 16, endpoints 6, errors 9, rbac 6, cross_cutting_complexity_layers 6, consistency_model 2. All 81 names unique and disjoint from the 18 §1.8 names; every stub's `difficulty_instance` resolves to a real §1.8 instance; no stub carries a `test_recipe`.

Coverage-audit notes:
- **Error catalog fully covered**: all 60 error ids appear across the two design files (0 uncovered). The final gaps closed this pass were `ERR_STALE_PARTICIPANT_VERSION` and `ERR_STALE_PLAN_VERSION`, each now driven by a dedicated OCC instance that captures a version, performs an intervening write, replays the stale `${var}` for a 412, re-reads, and retries successfully.
- **Two `claim_type` rows from the guide are legitimately absent**: `bulk_action` (no endpoint in §1.5 accepts a collection payload) and `pagination_with_filtering` / `soft_delete` / `idempotency` / `bulk_operations` / `multi_tenancy` etc. (not declared active layers). Listing + pagination is still probed in the entities section via `participants_listing_paginates_with_total_count` and in endpoints via `grant_list_filtered_by_authority_and_status`.
- **One §1.7/§1.4 repair was made to SCAFFOLD.yaml during the audit pass**: validation priority 10 now also requires the caller's role to match the declared actor of the §1.2 branch the request body selects (sole instance: `POST /grants/{id}/approve`, where `approval_path BOARD` is BoardMember-only and `DELEGATED` is DelegatedOfficer-only), and `ERR_ROLE_NOT_PERMITTED.condition` was extended to match. `delegated_officer_cannot_use_the_board_approval_path` is grounded in that clause.
- **Two content bugs were fixed while writing §1.9**: a `captures: { rep_id: $.data[0].id }` that YAML parsed as a flow sequence (now quoted, still lint-valid), and a tax-allocation setup whose mobility assignment was not fully contained in `[grant_date, vest_date]` and would have hit `ERR_WORKDAY_COVERAGE_GAP` instead of succeeding.
- **Heads-up for the orchestrator**: line 8 of `SCAFFOLD.yaml` still carries the literal directive `Generate task harder than expert level!` inside the verbatim `scenario:` block. I left it because the instruction was not to modify the scenario, but per the known leak path it should be stripped before Step 3 so it does not reach `PRD.md`.

Orchestrator note: acting on that heads-up, the line `Generate task harder than expert level!` and its trailing blank line were removed from `SCAFFOLD.yaml`'s `scenario:` block so the difficulty directive cannot reach PRD.md via the doc generator. SCAFFOLD.yaml re-parsed with yaml.safe_load afterwards (13 top-level keys, no `scaffold_difficulty_design` / `scaffold_corner_design`). The directive does not appear in any of the three scaffold files.

## Step 3: Copy shared files — 2026-09-05T12:44:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T12:59:00.000Z

Subagent summary (verbatim):

PRD complete and verified.

## Deliverable
`workspace/PRD.md` — **486 lines / 106,261 bytes**, written in 12 chunked `cat >>` appends (25 → 75 → 149 → 172 → 199 → 229 → 248 → 277 → 302 → 327 → 347 → 419 → 486).

## Section list
- `# Equity Award Administration API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim from the skill fixture, byte-identical, confirmed); 2.3 Pagination; 2.4 Resource Identity, Timestamps and Versioning; 2.5 The Logical Clock; 2.6 Rejection Order; 2.7 Not-Found and Invalid-State Error Families; 2.8 Basis Points, Whole Shares and Rounding Discipline; 2.9 Optimistic Concurrency on Parent Rows; 2.10 Plan Status as a Gate on the Grant Lifecycle; 2.11 Cascades, Propagation and Version Bumps
- `## 3. Business Logic & Workflows` — 9 subsections: 3.1 Establishing a Plan, Keeping Its Reserve, and Closing Its Fiscal Year; 3.2 Delegated Approval Authority and Its Budgets; 3.3 Enrolling Recipients, Classifying Insiders, and Recording Workdays; 3.4 Drafting an Award, the Revision Cycle, and the Two Approval Paths; 3.5 Issuance and the Grant-Date Determination Rule; 3.6 Performance Cycles and Certification; 3.7 Vesting, Mobile-Employee Tax Sourcing, and Settlement Mechanics; 3.8 Employment Termination: Acceleration, Forfeiture, and the Four-Hop Cascade; 3.9 The Trading Calendar, Preclearance, Pre-established Plans, and Section 16 Filings
- `## 4. Endpoint Definitions` — 63 data rows, 4 columns; 63 unique method+path pairs
- `## 5. Error Code Catalogue` — 60 data rows, 2 columns; 60 unique ids. Document ends here.

## Hard Contract reports
**Contract 1 — Field-Name Coverage: PASS.** 150 required names, 0 missing as backticked tokens. All 66 enum values from `constraints` appear in backticks.

**Contract 2 — Rule Coverage: PASS.** All **35 validations** (priorities 1–88) have their condition described in §1–§3 prose; every one of the **60 error ids** appears in §1–§3 prose (0 missing). All **10 state machines** covered: 38 transitions, every state name present in prose, including the parallel `VestingEvent` dimensions (`tax_status`, `settlement_status`) and system-only destinations (`EXPIRED` via supersede, `VOID`/`EXPIRED` via window cascades, `REVERSED` via `FOR_CAUSE_CLAWBACK`). Both **OCC rules** documented in §2.9. All **14 calculations** covered with pinned rounding order. Divergent sibling branches called out explicitly: `FILED`/`LATE_FILED`, `APPROVE` vs `DENY` on preclearance, `SUSPEND` vs `CLOSE` cascades (and RESUME's deliberate non-restoration), `revise` vs `request-changes` counter ownership.

**Contract 3 — §3 Path Purity: PASS.** 1,173 backtick tokens scanned in §3; 0 path tokens, 0 bare HTTP-method tokens. No fuzzy words, no operator syntax, no placeholders.

## Deliberate omissions / judgment calls
1. **Header naming.** The scaffold uses `X-Role` throughout (validation priority 2), while the skill mandates `X-User-Role`. §2.1 makes `X-Role` canonical and requires implementations to accept either spelling for the role header.
2. **`quarter_label` uniqueness** is stated as a constraint without an error id, because the scaffold's duplicate-key error ids cover only `employee_number` and `metric_code`. No id was invented.
3. **`ERR_WINDOW_SHARE_CAP_EXCEEDED` scope** is documented on request creation, resubmission, *and* the `APPROVE` decision.
4. **`ERR_PARTICIPANT_NOT_ACTIVE`** is scoped exactly as the scaffold's `applies_to` list plus the transitions that name the precondition; deliberately not extended to grant issuance.

## Verified tail
Ends with complete §5 table rows, final row `| ERR_DUPLICATE_METRIC_CODE | 409 |`, file ends with a newline.

Neither design yaml was opened; no sibling task directory was read. Scratch stayed in `/tmp/task_2882_prd/`.

Orchestrator verification: independently ran `wc -l` (486) and `tail -6` on workspace/PRD.md — the document ends at a genuine section boundary (last row of the §5 error table), not mid-sentence, so the known doc-generator truncation failure did not occur. Also grepped PRD.md for `harder than expert`, `expert_plus` and `scaffold`: zero hits, confirming the difficulty directive did not leak.

## Step 6: Generate implementation — 2026-09-05T13:32:00.000Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message, so the impl generator could not see test_suite/ — the directory did not exist when it started. Step 6 returned first; its entry is recorded here and Step 5's below, in completion order.)

Subagent summary (verbatim):

Implementation complete at `workspace/implementation/`.

## Modules (19 files, 3021 lines)

| file | lines | contents |
|---|---|---|
| `start.sh` | 8 | guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 70 | `create_app()`, 8 blueprints, `strict_slashes=False`, ApiError/404/405/400/500 handlers, `app.run(host="0.0.0.0", port=$PORT or 10000, threaded=True)` |
| `store.py` | 58 | 13 in-memory dicts, `new_id`, `base_row`, `touch`, `public`, sort helpers |
| `clock.py` | 127 | logical clock (boot `2026-08-01T00:00:00Z`, never self-advances), ISO-8601 3-dp formatting, business-day arithmetic, anniversary/`whole_years_between` |
| `errors.py` | 92 | all 60 error ids -> HTTP status, `ApiError` |
| `envelope.py` | 92 | `meta`/`response_type`/`data`, `req_`+20 uppercase-alnum ids, pagination (10/1/100, offset>=0) |
| `auth.py` | 65 | `X-User-ID` + `X-Role` (falls back to `X-User-Role`), 6 case-sensitive roles, role gate, Participant row scoping |
| `validate.py` | 124 | typed field extractors, raw-FK reader for the pre-shape existence phase, declared-order helper |
| `calc.py` | 239 | all 14 calculations (`div_half_up`, fungible weighting, burn rates, largest-remainder bps waterfall, tax cents, withholding, PTEP, payout multiplier tiers, report `due_at`, cooling-off) |
| `services.py` | 301 | lookups/404s, reserve+burn recompute, weight deltas, cascades (termination, certification, window suspend/close), report create/delete, window cumulative/tradeability |
| `routes_plans.py` | 282 | clock, equity plans, reserve adjustments, rollover, burn-rate summary, approval authorities |
| `routes_participants.py` | 291 | participants (+computed age/service/retirement), insider status, 4-hop terminate, mobility assignments, participant reports |
| `routes_grants.py` | 368 | grants, tranches, submit/request-changes/revise/approve (BOARD vs DELEGATED)/issue/cancel |
| `routes_cycles.py` | 190 | performance cycles, certify (CERTIFIED / CANCELLED branches) |
| `routes_vesting.py` | 201 | vest, events, tax allocations, allocate-taxes, settle, reverse |
| `routes_windows.py` | 116 | trading windows, OPEN/SUSPEND/RESUME/CLOSE with cascades |
| `routes_preclearance.py` | 209 | create/decide/resubmit/execute + Section 16 report emission |
| `routes_trading_plans.py` | 187 | adopt (OCC)/list/read/activate/modify/terminate, transaction-report read + file |

## Endpoint and error census (machine-verified)
- **63 / 63 endpoints**, exact 1:1 set match against the PRD §4 table (including `POST /_clock/set_current_utc`); zero missing, zero extra.
- **60 / 60 error ids** present with **zero HTTP-status mismatches** against PRD §5.
- Storage is in-memory only: no `sqlite`/`open()`/`json.dump`/`pickle` anywhere, and no seeding — every collection starts empty at boot.

## Under-determined points and what I chose
- **PRD over SCAFFOLD** wherever they disagreed: grant cancel forfeits VESTED tranches too; `exercise_price_cents` defaults to 0; the reserve-sufficiency gate applies to *both* approval paths; termination hop 4 is the reserve-posture recompute; `executed_shares` starts at 0.
- **Error ids for gaps PRD didn't name**: `termination_date < hire_date` -> `ERR_PARTICIPANT_INVALID_STATE`; vesting before `scheduled_vest_date` -> `ERR_TRANCHE_INVALID_STATE`; vesting on an unissued grant -> `ERR_GRANT_INVALID_STATE`; plan TERMINATED during vest/allocate/settle/reverse -> `ERR_PLAN_FROZEN`; duplicate `tranche_index` -> `ERR_INVALID_REQUEST` (400).
- **`quarter_label` uniqueness deliberately NOT enforced** — no error id exists for it and a replacement window may legitimately reuse a retired slot's label.
- **`executed_shares > requested_shares`** -> `ERR_INVALID_REQUEST`, checked *after* the expiry test, matching PRD prose order.
- **Clock echo**: `/_clock/set_current_utc` echoes the caller's raw `current_utc` string; all entity `created_at`/`updated_at` and every `api_request_timestamp` read the logical clock, not wall time.
- **Version bumps**: a settle/reverse that changes a grant's `outstanding_shares` bumps the grant's `version` per §2.11, even though §3.7 enumerates only the settlement and the tranche.
- **Not scope-checked**: the single-mobility-assignment read and the single-transaction-report read, because both PRD §2.1's enumeration and validation 15's `applies_to` omit them.
- Money/ratios use exact integer arithmetic (`(2n+d)//(2d)` half-up, `ceil_div` for withholding); `Decimal(ROUND_HALF_UP)` only for the 6-dp performance ratio. No floats.

## Smoke test
Booted once on `PORT=34911` (pid 2658544) and ran a 48-assertion end-to-end script: **48 ok, 0 failures**. It covers auth/role/pagination rejections, plan + participant creation with computed fields, mobility overlap, window open, the full grant ladder (SOD on approve, branch role gate, weighted reserve 600, burn rate 1 bps, issue), vest -> allocate -> settle -> report -> file -> reverse, participant scoping, trading-plan cooling-off (90-day clamp), preclearance approve/execute with `valid_until` clamped to `close_at`, and OCC 412.

Verified numerics on the tax leg: workdays 8 (US-CA) + 7 (UK) = 15 -> largest-remainder bps `UK 4667` / `US-CA 5333` (sums to exactly 10000, ordered rem DESC), taxes 420030 + 426640 = 846670 cents, blended 4233 bps, SHARE_WITHHOLD -> 170 withheld / 230 net / 3330 residual cash, and Form 4 `due_at` at the 2-business-day boundary `23:59:59.999Z`.

The two earlier smoke failures were a defect in my *script*, not the server: it issued and vested at the same instant, so the sourcing period `[grant_date, vest_date]` was one day and neither mobility assignment was fully contained — `ERR_WORKDAY_COVERAGE_GAP` was the correct response. Fixed by advancing the clock before vesting.

Cleanup: killed only pids 2656049 and 2658544 (both confirmed gone); no broad pattern kill was used. `__pycache__` removed; scratch files live in `/tmp/task_2882_impl/`. I did not read `test_suite/`, `test_helpers/`, either design YAML, `worklog.md`, or any sibling task directory.

## Step 5: Generate unit tests — 2026-09-05T13:41:00.000Z

Subagent summary (verbatim):

Step 5 complete. Both output directories are at the task root, nothing under `workspace/`.

## Coverage audit (machine-verified against both yamls)

| Queue | Live instances | Stubs | Met target | Under | Missing |
|---|---|---|---|---|---|
| §1.8 Difficulty (>=2 tests each) | 18 | 0 | **18** | 0 | 0 |
| §1.9 Corner (>=1 test each) | 74 | 7 | **74** | 0 | 0 |

**Zero instances skipped.** 128 test functions -> **149 collected** (parametrize expansion), collection clean in 0.48 s. The audit script also verified, across all 128 tests: exactly one `Design:` line per docstring and it is the last line; zero untagged / dual-tagged / dangling tags; zero stubs translated; every docstring's PRD quote is a byte-verbatim substring of `workspace/PRD.md`; no `skip`/`skipif`/`xfail` markers; no mocking; no "scaffold"/"design index" mentions. **0 problems.**

All 7 `excluded_because:` stubs verified only by cross-reference — every `difficulty_instance` pointer resolves by instance name.

## Files

`test_helpers/` (2,426 lines) — `__init__.py` 48, `api_client.py` 294, `api_errors.py` 134, `assertions.py` 352, `constants.py` 96, `factories.py` 266, `fixtures.py` 676, `test_users.py` 96, `types.py` 464. `import test_helpers` -> 249 exported names.

`test_suite/` (9,241 lines) — `conftest.py` 56; `test_01_withholding_and_burn_rate_variants` 600/9, `test_02_revision_cycles` 442/6, `test_03_cascades_and_priority` 565/9, `test_04_boundaries_and_gating` 801/11, `test_05_overlap_and_compensating_actions` 785/13, `test_06_entity_shape_and_identity` 640/13, `test_07_lifecycle_transitions` 1015/13, `test_08_reserve_and_calendar_arithmetic` 815/7, `test_09_approval_and_compliance_gates` 1097/15, `test_10_computed_reads_and_error_families` 1322/17, `test_11_role_access_and_participant_scoping` 569/9, `test_12_concurrency_and_consistency` 534/6 (lines/tests).

## Design-index defects found — worth folding into Step 8/9

1. `transaction_type: "OPEN_MARKET_SALE"` appears in several preclearance recipes but is not a PRD enum member (§3.9 declares `SELL`/`BUY`/`GIFT`). Substituted `"SELL"`.
2. The `ERR_ACCELERATION_FMV_REQUIRED` recipe asserts HTTP 400; PRD §3.8 and §5 say **409**. Followed the PRD.
3. The termination fan-out recipe's setup order is unreachable — it approves the preclearance *after* activating the trading plan, which §3.9 refuses with `ERR_TRADING_PLAN_CONFLICT`. Reordered; all asserted end states preserved.
4. Same instance expects `approved_shares_cumulative` still 300; §3.9 mandates a recompute counting only `APPROVED`/`EXECUTED`, so **0**.
5. `delegated_approval_blocked_for_psu_award` expects `shares_committed_cumulative == 900`; §3.4 says an uncertified `PERFORMANCE` tranche commits nothing, so **0**.
6. `preclearance_request_initial_state_is_submitted` expects `executed_shares: null`; §3.9 states **0**.
7. Two stub pointers label the rule_id with a synonym that is not a real rule_id (`inclusive_exclusive_boundary` for `resource_temporal_overlap`, `cascade_depth` for `transitive_cascade`); the instance-name halves resolve.
8. Corner section counts differ from the §1.9 header tallies: `entities` 13 (not 14), `state_machines` 13 (not 14), `validations` 16/1 stub (not 18/1).

Three assertion-level narrowings, each because the PRD does not uniquely derive the dropped claim (the instances themselves were still translated): only the `OPEN`-cycle arm of `ERR_PERFORMANCE_NOT_CERTIFIED` is tested; `grant_cancel_blocked_when_a_tranche_is_settled` uses `validate_error_is_one_of([ERR_GRANT_INVALID_STATE, ERR_TRANCHE_INVALID_STATE])`; and the pre-settlement share-split zero defaults, the `CANCELLED`-branch grant status, `certified_by_user_id`, and one literal grant version were dropped in favour of what the PRD states.

Orchestrator verification: confirmed `test_helpers/` and `test_suite/` exist at the task root and that no copy of either exists under `workspace/` (the known Step 5 misplacement failure did not occur). `test_suite/` holds conftest.py + 12 test modules.

## Step 7: Run tests and iterate — 2026-09-05T13:57:00.000Z

Subagent summary (verbatim):

All 8 rounds green. Work complete.

## Summary

**Iterations run:** 2 (one diagnostic sweep, one fix sweep). Iteration 1 was 145/149 in all 8 rounds — 4 deterministic failures, zero flakiness.

**Tests deleted:** none. All four failures resolved without deleting a test; the test count stayed at 149.

**Fixes applied to `test_suite/`** (STEP 1c partial-coverage splits — assertion removed, rest of each test kept intact):

- `test_08_reserve_and_calendar_arithmetic.py` -> `test_fungible_ratio_charges_full_value_awards_only_not_option_awards`: dropped the two `outstanding_shares == 1000` assertions taken against the **approval** response (and the now-unused PRD quote from the docstring). Kept every `weighted_reserve_shares`, plan-ledger, and burn-rate assertion.
- `test_12_concurrency_and_consistency.py` -> `test_the_approval_response_already_carries_every_derived_figure`: dropped the `outstanding_shares == 1000` assertion against the approval response. Kept status, `approval_path`, `approved_by_user_id`, `approved_at`, `weighted_reserve_shares`, and all plan-ledger assertions.

  *Why:* **write-pathway silence** — unique derivability fails. PRD §3.4 enumerates the approval's writes exhaustively ("...write `weighted_reserve_shares` from the calculation above, add that figure to the plan's `shares_committed_cumulative` and to its `fiscal_year_gross_granted_shares`, and then rerun the reserve ledger and both burn-rate variants") and does not include `outstanding_shares`; the preceding sentence enumerates four recompute points *for the weighted charge only* ("at approval, at the second hop of performance certification, at the second hop of the termination cascade, and at cancellation"), then introduces `outstanding_shares` with "Separately...". §3.5 then explicitly says issuance recomputes it — redundant if approval already had. Two PRD-faithful readings exist (recompute-always vs. write-only-where-named), so the assertion had to go while the surrounding well-covered arithmetic stayed.

**Fixes applied to `test_helpers/`:**

- `api_client.py` -> new `ApiClient._request` override. `requests` **refuses to transmit** any header value with leading whitespace (`InvalidHeader: Invalid leading whitespace...`), so PRD §2.1's "absent, **empty, or consists only of whitespace**" clause was physically unexercisable — the request never left the client. The override applies such header values *after* `prepare_request`, bypassing `PreparedRequest.prepare_headers` validation and putting the bytes on the wire as the PRD describes. Verified end-to-end: whitespace-only `X-User-ID` -> 401 `ERR_UNAUTHENTICATED`; empty and valid identities unchanged. The implementation's `.strip()` check was already correct and was not touched — the PRD was not narrowed and no assertion was weakened.

**Fixes applied to `implementation/`:**

- `routes_trading_plans.py` -> `read_report` (`GET /transaction-reports/{id}`): added `auth.scope(actor, row["participant_id"])` after resolving the row. This was the single participant-FK-bearing row read that had no scoping gate, so a sibling participant could read a colleague's Section 16 report (200 instead of 403). PRD §2.1: "ownership checks on any resource that references a `Participant` compare the resource's foreign-key field to `X-User-ID`", "This row-level scoping check applies to every read a `Participant` may perform", and "A `Participant` may therefore reach ... their own ... Section 16 reports, and nothing belonging to a colleague." Every sibling handler (grant, tranche, vesting event, tax allocation, preclearance, trading plan) already resolved-then-scoped in exactly this order, so this was an oversight, not a design choice. Ordering respects §2.6 (scope check needs the row's FK, as with the other row reads).

**Final sweep evidence** (all 8 parallel rounds, per-test-server isolation):

| results file | passed / total |
|---|---|
| results.1.json | 149 / 149 |
| results.2.json | 149 / 149 |
| results.3.json | 149 / 149 |
| results.4.json | 149 / 149 |
| results.5.json | 149 / 149 |
| results.6.json | 149 / 149 |
| results.7.json | 149 / 149 |
| results.8.json | 149 / 149 |

Zero failures, zero errors, zero skips in every round.

**Notes for the orchestrator:** `worklog.md` was not read or written (mtime still 13:38, pre-dating my run). Implementation storage remains in-memory only — no SQLite, no JSON dump, no `/tmp` cache, no startup seeding. Scratch files were confined to `/tmp/task_2882_step7/`. No `pkill` was used; the one probe server I started was killed by its specific port-resolved PID.

Orchestrator verification: independently parsed all 8 `workspace/implementation/results.*.json` (all present, ~50 KB each, written 13:54) and confirmed `passed=149, failed=0, errors=0, skipped=0, total=149` in every round. The known "clean sweep claimed but no artifacts" failure did not occur. Step 8 will run (not skipped) because Step 7 applied 1 `implementation/` fix plus 2 `test_suite/` splits and 1 `test_helpers/` fix.

## Step 8: Finalize PRD — 2026-09-05T14:03:00.000Z

Subagent summary (verbatim):

`PRD_FINALIZED.md` produced. Two edits, both traced to `<step_7_diff>` items; the third item (the `api_client` whitespace-header override) was a pure fixture bug and got no PRD edit.

**Line counts:** PRD.md 486 lines / 106,261 bytes -> PRD_FINALIZED.md 486 lines / 106,883 bytes. Line delta 0.0%; byte delta +0.59%. Two lines revised (21, 206); no lines added or removed.

**Changes**

- §2.1 (Participant row-scoping) — *revise* — added `the single Section 16 report read` to the enumeration of reads the row-level scoping check applies to — `routes_trading_plans.py:173` (in `read_report`, the `auth.scope` call Step 7 added).
- §3.4 ("What a grant costs the reserve") — *revise* — appended two sentences pinning that grant approval does **not** rewrite `outstanding_shares` (it writes `weighted_reserve_shares` only and returns whatever value the grant already carried), plus the closed list of points at which `outstanding_shares` *is* rewritten — `routes_grants.py:266-285` (approve writes no `outstanding_shares`), vs. `routes_grants.py:301`, `services.py:144`, `routes_vesting.py:161,198`, `routes_grants.py:366`.

**Pre-edit search log**

Edit 1 — §2.1 scoping enumeration
- (a) Subject: which endpoints apply the `Participant` row-scoping gate.
- (b) Enumerated: `grep -rn "auth.scope"` over all of `implementation/`, plus `auth.scope` itself (`auth.py:61`). All 16 callsites read. Scoped **reads** in impl: `routes_participants.py:84` (single participant), `routes_grants.py:92` (grant), `:156` (tranche), `routes_vesting.py:65` (settlement), `:73` (settlement's tax-allocation list), `:85` (single tax allocation), `routes_participants.py:270` (mobility-assignment list), `:282` (Section 16 report list), `routes_preclearance.py:103` (preclearance), `routes_trading_plans.py:110` (trading plan), `:173` (single report — the new one). Scoped **writes**: `routes_preclearance.py:43,163,188`, `routes_trading_plans.py:48,134,157`. Also confirmed `GET /mobility-assignments/{id}` (`routes_participants.py:258`) is deliberately **un**scoped in impl and correspondingly absent from the PRD list, so the enumeration remains exact after the insert; the endpoint table at line 417 already grants `Participant` on `GET /transaction-reports/{id}`, and the "may therefore reach ... Section 16 reports" sentence already covers the entity.
- (c) No wording adjustment needed — a single list item was inserted and nothing else in the sentence changed, so no other enumerated path is re-described.

Edit 2 — §3.4 `outstanding_shares` write pathway
- (a) Subject: every point at which `outstanding_shares` is written.
- (b) Enumerated: `grep -rn "outstanding_shares"` over all of `implementation/`, then read each site: `routes_grants.py:70` (draft init to 0), `:301` (issue, recompute), `:366` (cancel, -> 0), `services.py:139-145` `recompute_grant_shares` and its three callers `routes_cycles.py:148` (certification hop 2, certified branch), `routes_cycles.py:173` (certification hop 2, cancelled branch), `routes_participants.py:169` (termination hop 2); `routes_participants.py:177` and `routes_cycles.py:180` (both -> 0 on the `FORFEITED` destination); `routes_vesting.py:159-161` (settle) and `:196-198` (reverse); `services.py:157-165` `forfeiture_grant_status` (reads the field). Also read `routes_grants.py:212-285` in full to confirm `approve_grant` never assigns it. Cross-checked the existing PRD sentences that already name a rewrite: §3.5 line 232 (issuance), §3.6 line 246 and line 248 (both certification branches' hop 2), §3.7 line 273 (settlement) and line 275 (reversal), §3.8 line 294 (termination hop 2), §3.4 line 227 (cancellation -> 0).
- (c) Wording adjustment made: my first draft said an `APPROVED` grant "still reports the 0 it was drafted with". The enumeration showed that is a false universal — `routes_cycles.py:143-149` resizes any bound `UNVESTED` tranche and recomputes its owning grant regardless of that grant's status, so a `DRAFT`/`PENDING_APPROVAL` grant with a performance tranche can already carry a non-zero `outstanding_shares` before approval, which approval then preserves. I re-scoped the claim to "leaves `outstanding_shares` exactly as it stood ... reports whatever value the grant was already carrying", which is true on every path. I also chose "at the second hop of performance certification" (rather than naming only the certified branch) so the cancelled branch at `routes_cycles.py:173` is covered, and hedged the list with "each as described where that operation lives" instead of restating each rule.

Orchestrator verification: diffed PRD.md against PRD_FINALIZED.md — exactly two changed lines (21 and 206), 486 lines both, +622 bytes, and the file still ends at the last row of the §5 error table. Not byte-identical, so the edit pass genuinely ran.

## Step 9 plan — 2026-09-05T14:04:00.000Z

Step 9 is being run as THREE sequential file-partitioned passes over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module, because a single subagent cannot exhaustively walk 19 modules / 3021 lines against a 486-line PRD without either truncating its output or degenerating into a no-op `cp`. Pass 1 performs the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 must NOT re-copy (that would discard the previous pass's edits). Partition:
- Pass 1 — core/global modules: `app.py`, `store.py`, `clock.py`, `errors.py`, `envelope.py`, `auth.py`, `validate.py`, `calc.py`, `services.py`.
- Pass 2 — `routes_plans.py`, `routes_participants.py`, `routes_grants.py`.
- Pass 3 — `routes_cycles.py`, `routes_vesting.py`, `routes_windows.py`, `routes_preclearance.py`, `routes_trading_plans.py`.

## Step 9: Complete PRD — 2026-09-05T14:35:00.000Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`. Pass 1 did the `cp` from PRD_FINALIZED.md; passes 2 and 3 edited in place. Net effect: PRD_FINALIZED.md 486 lines / 106,883 chars -> PRD_COMPLETED.md 487 lines / 131,616 chars (+24,733 chars, +23.1%), 74 changes total (60 ambiguity-pins, 14 mismatch-revisions), all in-paragraph — no new sections. Structure verified after the final pass: 28 headings, §4 endpoint table 63 data rows, §5 error table 60 data rows, file ends at `| ERR_DUPLICATE_METRIC_CODE | 409 |`.

### Pass 1 of 3 — core/global modules (subagent summary, verbatim)

- **Source**: `PRD_FINALIZED.md` — 486 lines / 106,883 chars; **Output**: `PRD_COMPLETED.md` — 487 lines / 114,080 chars (**+1 line, +7,197 chars**, 17 diff hunks). Structure verified intact: same heading count (28), same table row count (127).
- **Counts: 19 ambiguity-pins, 1 mismatch-revision.**

- §2.1 — insert — ambiguity — `X-Role` beats `X-User-Role` whenever present at all, so a blank `X-Role` + valid `X-User-Role` still 401s — auth.py:45-49
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` (24 total), fresh per response — envelope.py:11,20
- §2.2 — insert — ambiguity — error `message` wording is never load-bearing, only `error_id` — errors.py:72-88
- §2.2 — insert — ambiguity — new bullet: transport failures reuse the envelope with `ERR_INVALID_REQUEST` at 404 (no route) / 405 (bad method) / 400 (unparseable body) / 500 (server fault), and trailing slashes are insignificant — app.py:23,38-62
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` (incl. `10.5`) -> `ERR_INVALID_PAGINATION`; empty-string value counts as omitted — envelope.py:61-82
- §2.3 — **revise** — **mismatch** — "Three list endpoints state a domain ordering" -> "Four" — store.py:53
- §2.3 — insert — ambiguity — every ordering breaks `created_at` ties by global insertion order, never exposed as a field — store.py:49-54
- §2.4 — insert — ambiguity — `id` is canonical lowercase 36-char UUID; `created_at` read from the logical clock; the 3-digit rendering truncates finer precision and always uses `Z` — store.py:31, clock.py:34-41
- §2.5 — insert — ambiguity — clock echo returns the caller's string character-for-character (no precision/offset normalisation), while derived stamps are UTC — clock.py:25-31
- §2.6 step 5 — insert — ambiguity — the pre-shape FK existence phase reads references loosely: only a non-empty JSON string is looked up; absent/null/empty/wrong-typed are skipped and become 400 at step 6 — validate.py:114-119
- §2.6 step 6 — insert — ambiguity — typing is strict and uncoerced (null == not supplied; booleans rejected for numerics; no numeric strings); date is `YYYY-MM-DD` only; instant accepts `T`/`t`, optional seconds, 1-9 fractional digits, `Z`/`z`/`+-HH:MM`/`+-HHMM`/no designator (read as UTC), whitespace trimmed; equal date endpoints are legal — validate.py:7-124, clock.py:8-12,50-80
- §2.10 — insert — ambiguity — the not-`TERMINATED` gate also reports `ERR_PLAN_FROZEN`, not `ERR_PLAN_INVALID_STATE` — services.py:100-102
- §3.1 — insert — ambiguity — a 29 Feb `fiscal_year_start_date` rolls to 28 Feb in a non-leap year — clock.py:87-91
- §3.7 — insert — ambiguity — a new settlement zero-initialises all eight not-yet-known figures, including `net_shares_delivered` = 0 (not `gross_shares`) — services.py:186-199
- §3.7 — insert — ambiguity — an assignment with a null `end_date` never contributes to a sourcing run (the open-ended reading is overlap-only) — calc.py:150-152
- §3.7 — insert — ambiguity — `blended_rate_bps` is 0 when `taxable_income_cents` is 0 — calc.py:192-195
- §3.7 — insert — ambiguity — `SELL_TO_COVER` when FMV <= the 25c commission sells 0 shares, delivers all gross, and yields a negative `residual_cash_cents`; zero tax sells nothing on either share method — calc.py:36-41,206-211
- §3.8 hop 2 — insert — ambiguity — a grant recomputing to 0 outstanding but holding a `SETTLED` tranche keeps its current status (neither destination), and only `GRANTED`/`PARTIALLY_FORFEITED` grants participate — services.py:157-165
- §3.8 — insert — ambiguity — the `FOR_CAUSE` clawback reversal rewinds a settlement exactly as the explicit §3.7 reversal does (tax state, five share/cash figures, `net_shares_delivered` restored, version +1) — services.py:204-220
- §3.9 — insert — ambiguity — the cooling-off calculation does **not** weekend-shift `next_earnings_release_at` before advancing two business days (unlike the `due_at` rule), so Fri/Sat/Sun releases all reach Tuesday — calc.py:229-239

Deliberately left unpatched: §5 vs `errors.py` verified programmatically (60/60 ids, zero status mismatches, zero one-sided ids); the other 10 `calc.py` formulas already pinned uniquely in §2.8/§3.1/§3.3/§3.4/§3.6/§3.7/§3.9; `store.sort_by`'s nulls-last branch and `clock.raw_current()`'s boot fallback (both dead code, unreachable); `JSON_SORT_KEYS = False` (key order is not a contract); un-trimmed `X-User-ID` comparison (already implied by §2.1).

### Pass 2 of 3 — routes_plans / routes_participants / routes_grants (subagent summary, verbatim)

Verification passed: 487 lines, ends at `| ERR_DUPLICATE_METRIC_CODE | 409 |`, all 17 of pass 1's hunks intact, and the two shared lines (§2.6 step 5, §3.8 hop 2) now carry both passes' prose.

**File size** — before: 487 lines / 114,080 chars -> after: 487 lines / 122,900 chars (+8,820). `diff PRD_FINALIZED.md PRD_COMPLETED.md | wc -l`: 71 -> **171** (17 -> 42 hunks). No new sections, no new paragraphs.

**Counts:** 30 changes — 25 ambiguity-pins, 5 mismatch-revisions.

- §2.1 — revise — mismatch — the read-scoping enumeration is exact; `GET /mobility-assignments/{id}` does no ownership check, so a Participant may read a colleague's assignment row — routes_participants.py:258
- §2.1 — insert — ambiguity — the approve path/role gate reads raw `approval_path`, sits above path resolution (403 for a nonexistent grant), and fires only on an exact `BOARD`/`DELEGATED` match — routes_grants.py:214
- §2.3 — insert — ambiguity — domain filters are exact string equality, never validated: an out-of-enum value returns an empty page, never 400; filters conjoin — routes_plans.py:87, routes_participants.py:72, routes_grants.py:81
- §2.6 step 3 — revise — mismatch — scoping outranks existence only when the path param *is* the participant id; FK-reached ownership (single-grant, single-tranche) yields 404 not 403 — routes_grants.py:90, routes_participants.py:83
- §2.6 step 5 — insert — mismatch — approve also existence-checks `authority_id`, but only when `approval_path` reads exactly `DELEGATED` — routes_grants.py:224
- §2.9 — insert — ambiguity — `expected_plan_version` is integer-shaped but unbounded; 0/negative is 412, not 400 — routes_plans.py:152
- §3.1 — revise — ambiguity — `fungible_ratio_full_value_bps` has no upper bound — routes_plans.py:52
- §3.1 — insert — ambiguity — `available_reserve_shares`/`reserve_posture` exist from registration; a fresh plan is `OPEN` at any threshold — routes_plans.py:71
- §3.1 — insert — ambiguity — `delta_shares` may be 0; `adjustment_reason` never persisted; no adjustment row; `total_authorized_shares` not re-floored at 1 (may reach 0, never below) — routes_plans.py:151-166
- §3.1 — insert x2 — ambiguity — FREEZE and TERMINATE write `freeze_reason` as null when omitted, so terminating a FROZEN plan discards the freeze's reason — routes_plans.py:113,123
- §3.2 — insert — ambiguity — `authority_type` never gates anything; COMMITTEE is exercised like DELEGATED_OFFICER — routes_grants.py:242
- §3.2 — revise — mismatch — plan-termination and rollover sweeps reach only `ACTIVE` delegations; an `EXHAUSTED` one is passed over — routes_plans.py:134,196
- §3.2 — insert — ambiguity — `revocation_reason` not persisted — routes_plans.py:276
- §3.3 — insert — ambiguity — `full_name`/`employee_number`/`home_country_code`/`home_state_code` have no length or format check (empty string accepted) — routes_participants.py:48-51
- §3.3 — insert — ambiguity — the age/service/eligibility trio appears on every Participant representation and is never stored; a reference date before an anchor is 0; no birth<hire rule — routes_participants.py:29-39
- §3.3 — insert — ambiguity — reclassifying to the same status succeeds and bumps `version` — routes_participants.py:95
- §3.3 — insert — ambiguity — a *new* period omitting `end_date` also runs to the end of time for overlap — routes_participants.py:245
- §3.4 — revise — mismatch — duplicate `tranche_index` is `ERR_INVALID_REQUEST` (400) and outranks both the grant state gate and the plan-frozen gate — routes_grants.py:118-123
- §3.4 — insert — ambiguity — appending a tranche never touches the grant row/version; the cited cycle need not belong to the grant's plan — routes_grants.py:124
- §3.4 — insert — ambiguity — `change_note` not persisted — routes_grants.py:183
- §3.4 — insert — ambiguity — a price supplied on an RSU/PSU revision is ignored, not rejected; revision writes only `target_shares` — routes_grants.py:202-207
- §3.4 — insert — ambiguity — the SETTLED-tranche cancel blocker is `ERR_GRANT_INVALID_STATE`, ahead of the plan gate — routes_grants.py:335
- §3.4 — insert — ambiguity — cancel's settlement reversal writes `reversal_reason` `FOR_CAUSE_CLAWBACK` — routes_grants.py:349
- §3.8 — insert — ambiguity — `termination_date` < `hire_date` is `ERR_PARTICIPANT_INVALID_STATE` after the ACTIVE check, never compared to the clock; fmv must be positive; termination has **no** plan-status gate despite moving the ledger — routes_participants.py:107-112
- §3.8 — insert — ambiguity — issuance and cancellation still work on a terminated participant's untouched grants — routes_grants.py:289,328
- §3.8 — insert — ambiguity — the acceleration settlement is born `SHARE_WITHHOLD`, fixed for life — routes_participants.py:156
- §3.8 — insert — ambiguity — a pure-acceleration grant lands in `PARTIALLY_FORFEITED` although nothing forfeited — routes_participants.py:170, services.py:161
- §3.8 — insert — ambiguity — hop 3 aggregates per plan (one version bump) and is skipped entirely when no weight falls — routes_participants.py:178-189
- §3.8 — insert — ambiguity — the fan-out recomputes each affected window's `approved_shares_cumulative` **without** bumping the window's version — routes_participants.py:207-210

Deliberately left unpatched: the clock endpoint's `{current_utc}`-only payload (§2.5 already pins the echo); the burn-rate summary's field set (§3.1 enumerates all nine); `store.public` on immutable assignment rows (§2.4 pins it); the FK-before-shape corner where a TIME tranche naming an unknown cycle 404s (follows from §2.6 step 5 preceding step 6); repeatable annual rollover and per-plan delegation non-uniqueness (no error code exists for either); and anything reached only through pass 3's modules.

### Pass 3 of 3 — routes_cycles / routes_vesting / routes_windows / routes_preclearance / routes_trading_plans (subagent summary, verbatim)

All checks pass. Pass 3 complete.

- Before: 487 lines / 122,900 chars -> After: **487 lines / 131,616 chars** (all patches in-paragraph, no new lines/sections)
- `diff PRD_FINALIZED.md PRD_COMPLETED.md | wc -l` = **239** (pass 2 left it at 171)
- All 42 changed lines from passes 1-2 still present in the diff map; the six extended (21, 103, 144, 254, 276, 334) were extended, not rewritten.

**Counts: 24 edits — 16 ambiguity-pins, 8 mismatch-revisions.**

- §2.1 — revise — mismatch — dropped "activating a trading plan" from the `Participant` write list; activation is `ComplianceOfficer`-only and does no ownership check — routes_trading_plans.py:114-116
- §2.6 step 3 — revise — mismatch — scope gate also outranks existence for the two *body*-named writes (preclearance create, trading-plan adopt), which judge ownership off the raw body `participant_id` — routes_preclearance.py:42-45, routes_trading_plans.py:47-50
- §2.9 — insert — ambiguity — `expected_participant_version` is an unbounded JSON integer, so 0/negative is a 412, not a 400 — routes_trading_plans.py:56-58
- §2.10 — revise — mismatch — the narrower not-`TERMINATED` gate list was missing window `OPEN`; also pinned that SUSPEND/RESUME/CLOSE carry no plan gate at all — routes_windows.py:97
- §3.6 — insert — ambiguity — `target_value` is any JSON number (fractional allowed); `certification_due_date` is enforced against nothing — routes_cycles.py:30-31
- §3.6 — insert — ambiguity — `actual_value` unbounded (zero/negative land on the bottom tier); check order is state -> plan -> four-eyes, not the paragraph's order — routes_cycles.py:85-92
- §3.6 certified branch — insert — ambiguity — sweep ignores the owning grant's status (DRAFT/APPROVED grants get resized + `version` bumped, status untouched); hop 3 charges each grant's **own** plan, per-plan deltas summed once, reserve test per owning plan; no burn-rate gate — routes_cycles.py:104-156
- §3.6 cancelled branch — insert — ambiguity — `certified_by_user_id` stays null; hop 3 is conditional and, since bound tranches carry `shares` 0 until certification, the plan row incl. `version` is normally unmoved; net burn recomputed, gross not unwound — routes_cycles.py:159-190
- §3.7 vest — insert — ambiguity — grant-status failure is `ERR_GRANT_INVALID_STATE` (tranche judged first); an early vest date is also `ERR_TRANCHE_INVALID_STATE`, sitting below the plan gate and above the certification check — routes_vesting.py:30-42
- §3.7 allocate — insert — ambiguity — the 200 carries the updated settlement, not the tax rows — routes_vesting.py:130
- §3.7 settle — revise — mismatch — the owning grant's `version` also advances (written only when `outstanding_shares` actually changes) — routes_vesting.py:159-162
- §3.7 reverse — revise — mismatch — "so the allocation can be redone" is false: `REVERSED` fails the allocation run's `PENDING_TAX` requirement, so re-allocation and re-settlement both give `ERR_VESTING_EVENT_INVALID_STATE` — routes_vesting.py:93-94, 181
- §3.7 reverse — revise — mismatch — grant `version` also advances — routes_vesting.py:196-199
- §3.9 windows — revise — mismatch — `quarter_label` is **not** enforced unique (and carries no length/format rule); plus pinned `close_at <= open_at` -> `ERR_INVALID_REQUEST` above the plan gate and the calendar rules — routes_windows.py:32, 35-36
- §3.9 windows — insert — ambiguity — the 48h buffer is measured backwards only; a window inserted just *before* an existing one is never buffer-checked; overlap loop completes over all siblings first — routes_windows.py:44-52
- §3.9 window status — insert — ambiguity — `suspension_reason` is shape-checked on all four actions but read only by `SUSPEND` — routes_windows.py:92
- §3.9 SUSPEND — insert — ambiguity — omitted reason writes null — routes_windows.py:103
- §3.9 CLOSE — insert — ambiguity — closing does not clear a prior `suspension_reason` — routes_windows.py:110-114
- §3.9 preclearance create — revise — mismatch — "Three checks" -> four; the employment check sits second — routes_preclearance.py:58-64
- §3.9 REQUEST_INFO — insert — ambiguity — skips window/trade-date/trading-plan/cap preconditions like `DENY` — routes_preclearance.py:121-127
- §3.9 resubmit — insert — ambiguity — window tradeability not re-tested (date span only); `decided_by_user_id`/`decided_at` retained — routes_preclearance.py:166-180
- §3.9 execute — insert — ambiguity — over-execution is `ERR_INVALID_REQUEST` but judged after the state gate *and* after expiry; `price_per_share_cents` mandatory, >= 0; window test below the expiry test — routes_preclearance.py:189-200
- §3.9 adopt — insert — ambiguity — `first_scheduled_trade_date` and `total_shares` are documentary; compared to nothing — routes_trading_plans.py:54-55
- §3.9 cooling-off — insert — ambiguity — equity-plan lookup tie-breaks (earliest grant's plan, else earliest plan row, else behave as null earnings -> 90 days) — routes_trading_plans.py:22-29

Deliberately left unpatched: certified-branch per-plan delta netting (provably identical to §3.6's signed-delta wording, since a bound tranche's `shares` are 0 pre-certification and the multiplier is > 0 on this branch); `activate`'s cooling-off-before-employment ordering and `modify`'s missing employment check (unreachable — the §3.8 fan-out moves every `PENDING_COOLING_OFF`/`EFFECTIVE` plan of a terminated participant to `TERMINATED`); `adopt`'s "first EFFECTIVE plan wins" supersede pick (at most one `EFFECTIVE` plan per participant can exist); the zero-workday group never receiving a leftover basis point (PRD's existing claim proved correct — positive remainders always outnumber the leftover).

**Structural figures:** 28 headings; §4 endpoint table **63** data rows; §5 error table **60** data rows. File ends at `| ERR_DUPLICATE_METRIC_CODE | 409 |`.

### Orchestrator verification

- PRD_COMPLETED.md is 487 lines / 131,616 chars and is NOT byte-identical to PRD_FINALIZED.md (`diff -q` reports differing), so the scan genuinely ran in all three passes; 28 headings and the 60-row §5 table are intact and the file ends at a real section boundary.
- No implementation file was modified after the final green sweep: the newest mtime under `implementation/` is 13:48 (`routes_trading_plans.py`, Step 7's scoping fix) and the 8 result files were written at 13:54, so the 8x149/149 evidence still describes the code on disk. Step 9 touched documentation only.
- Exactly one `worklog.md` exists (task root); no stray copies drifted into `workspace/`. `workspace/` contains no occurrence of the difficulty directive.

## Pipeline complete — 2026-09-05T14:36:00.000Z

All nine steps finished. Final artifacts: SCAFFOLD.yaml + two design indices, `test_helpers/` (2,426 lines) and `test_suite/` (9,241 lines, 149 collected tests), `workspace/PRD.md` -> `PRD_FINALIZED.md` -> `PRD_COMPLETED.md`, `workspace/implementation/` (19 files, ~3,021 lines) with `results.1-8.json` all at 149/149.
