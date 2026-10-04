# Worklog — task_3110_independent_practice_affiliation_into_single_medical_group

## Step 1: Create Task Directory — 2026-09-29T23:56:00.000Z

Task directory `./tasks/task_3110_independent_practice_affiliation_into_single_medical_group/` was pre-allocated (per command args) with `workspace/` inside; verified it exists. No new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T00:39:00.000Z

All checks pass. Final lint verdict block (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

Generated the scaffold for `task_3110_independent_practice_affiliation_into_single_medical_group` (Privia Health-style practice affiliation) at maximum (Expert+) difficulty. Three files written:

- `/home/ubuntu/github/CodingPRD/tasks/task_3110_independent_practice_affiliation_into_single_medical_group/SCAFFOLD.yaml` — §1.0–§1.7
- `/home/ubuntu/github/CodingPRD/tasks/task_3110_independent_practice_affiliation_into_single_medical_group/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, 18 instances (9 rules × 2)
- `/home/ubuntu/github/CodingPRD/tasks/task_3110_independent_practice_affiliation_into_single_medical_group/SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, 42 instances across all 9 taxonomy sections

**Counts**: 15 entities, 74 endpoints, 44 error codes, 9 roles, 14 state machines, 8 calculations, 12 validation priorities, 3 OCC concurrency rules. 991 setup/trigger calls across both design files, all lint-verified against §1.5.

**Difficulty design choices** (user asked for harder-than-expert):
- **Archetype**: ledger reconciliation (collections net of shared-services fee, provisional-vs-final distribution variants) + compliance/audit secondary (segregation of duties, credentialing sequencing); flat topology; segregation-of-duties role model (DistributionAccountant settles batches but can never finalize statements — enforced by role AND by same-user-id check; committee chair opens motions but cannot vote).
- **Dual-variant calcs**: statement provisional (includes POSTED batches at posted amount) vs final (settled amounts only); departure penalty estimated (assumed exit) vs final (clock-inclusive actual exit).
- **Combinatorial formulas in all three modes**: (a) tiered shared-services fee with agreement-override branch and chronological tier fill; (b) incentive pool floor-then-remainder waterfall with pinned tie-break order; (c) hold/carry-forward with pinned evaluation order (circular-looking: carry-in feeds payable, threshold decides carry-out).
- **Non-linear machines on different entities**: Practice suspend/reinstate cycle, DepartureCase dispute/resettle cycle, wave IN_CUTOVER→LOCKED rollback, statement FINAL→AMENDED→REISSUED loop.
- **Depth-3 cascade**: wave complete → practice AFFILIATED → enrollment EFFECTIVE → provider ACTIVE; plus depth-2 departure-settle cascade (practice DEPARTED → enrollments terminated + agreement terminated + providers deactivated).
- **Boundary precision**: hold threshold (payable 5,000 pays, 4,999 holds); quality threshold (60.0 eligible, 59.9 not); uplift gate inclusive at exactly 0.0800.
- **Temporal overlap with differing interval semantics**: wave cutover windows half-open [start, end) (shared boundary allowed) vs enrollment windows closed [effective, termination] (termination day occupied).
- **Compensating invariants on different conserved quantities**: period dollars (gross = fee + net across adjust/amend/reissue) and provider headcount (affiliate 0→2, depart 2→0).
- **OCC** on Practice.version (agreement create-with-supersede), ImplementationWave.version (lock), DistributionStatement.version (amend) — all 412 ERR_STALE_VERSION.
- Logical clock test endpoint with mandated default 2026-09-01T00:00:00Z; all numeric asserts are precomputed literals.

No sibling task directories were inspected; the design was derived solely from the scenario text and the skill specification.

## Step 3: Copy Shared Files — 2026-09-30T00:40:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3110_independent_practice_affiliation_into_single_medical_group/workspace/INSTRUCTION.md` (1424 bytes, verified present).

## Step 4: Generate PRD — 2026-09-30T00:51:00.000Z

All three hard contracts pass.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3110_independent_practice_affiliation_into_single_medical_group/workspace/PRD.md` (333 lines).

**Section coverage:**
- §1 Introduction — 3 paragraphs framing affiliation-without-acquisition, single-TIN contracting, distribution economics, waves, credentialing, governance, and departure.
- §2 Global Specifications — 10 subsections: RBAC (with per-role identity binding), API Response Structure (verbatim block), Pagination, Common Resource Properties (incl. `status` enum-bearing note), Logical Clock (default `2026-09-01T00:00:00Z`, `to_iso8601`), Monetary Precision (integer cents, per-batch round-half-up, 4dp uplift, 6dp weight), OCC (three rules: `expected_practice_version` on agreement draft, `expected_wave_version` on wave lock, `expected_statement_version` on statement amend — all `ERR_STALE_VERSION`/412), Hierarchical Consistency & Cascades, Validation Order (12-step priority chain), Periods/Windows (half-open wave windows vs closed enrollment windows).
- §3 Business Logic — 9 subsections covering group/market formation, practice recruitment (agreement draft/execute + wave selector), wave lifecycle + affiliation cascade (3-hop), provider rostering + credentialing (STANDARD 90d / EXPEDITED 30d+45d span), payer contracting + physician governance (vote snapshot, auto-close majority, uplift ≥ 0.08 gate), collections/batches/monthly distribution (provisional vs final variants, tiered fee with pinned per-batch rounding, hold/carry-forward with inclusive threshold), incentive pools (floor + remainder waterfall), departure (notice/dispute/settle + penalty two variants), suspension/reinstatement.
- §4 Endpoint Definitions — 74-row table, 4 columns.
- §5 Error Code Catalogue — 44-row table, 2 columns.

**Hard-contract results:**
- Contract 1 (Field-Name Coverage): 106/106 required identifiers present in backticks — PASS (one pass needed a `status` addition).
- Contract 2 (Rule Coverage): all 13 state machines' transitions + side effects expressed; all 8 calculations rendered in pinned-order prose (tiered fee, dual-variant distribution net, hold/carry-forward, weighted share with remainder waterfall, avg uplift, credentialing effective date, departure penalty with estimated/final variants, market capacity); all 12 validation priorities ordered in §2.9 with identity-binding and segregation-of-duties explicit; all 3 OCC rules named with `write_endpoint` + `expected_<parent>_version` + `ERR_STALE_VERSION`/412; all 44 error IDs mentioned in §1–§4 — PASS.
- Contract 3 (§3 Path Purity): 546 §3 backtick tokens scanned, zero paths/methods/combos — PASS.

**Notable Zero-Silence decisions:**
- All 13 resource-specific `ERR_*_NOT_FOUND` IDs enumerated inline in §2.9 rather than exemplified.
- The departure cascade's responsibility boundary (provider deactivation on last-enrollment termination lives in the departure cascade, not enrollment terminate) stated explicitly.
- The wave-selector tie-break (lowest `cutover_start_date`, then earliest `created_at`) and the selector-empty failure mode (`ERR_NO_WAVE_IN_CUTOVER`) both surfaced.
- The circular-looking carry-forward resolution (`carried_forward_in` reads only `FINAL_ISSUED`/`REISSUED` prior-month statements) and the inclusive paying-side threshold boundary are both pinned in prose.
- Contract activation's four gates given in fixed evaluation order so `ERR_INVALID_TRANSITION` masks the ratification, clock, and uplift gates.

## Step 5: Generate Unit Tests — 2026-09-30T01:25:00.000Z

Generation complete for `task_3110_independent_practice_affiliation_into_single_medical_group`.

## test_helpers/ (10 files)
- `types.py` — status enums for all 13 state machines + `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (clock, groups, markets, practices, providers, agreements, waves, contracts, rates, enrollments, batches, statements, pools, allocations, departure cases, votes)
- `api_errors.py` — all 44 error IDs + HTTP map, registered via `set_error_http_status_map`
- `constants.py` — thresholds (tier rates/cap, hold 5000, notice 180d, penalty constants, lags 90/30, 45-day cap, quality 60) + canonical clock values + opaque operator IDs
- `test_users.py` — `TEST_USERS` shared constants plus per-instance builders for the three entity-backed roles (`make_practice_executive_headers`, `make_market_committee_chair_headers`, `make_physician_board_member_headers`)
- `factories.py`, `assertions.py`, `fixtures.py` (tiered composites: `setup_group_market` → `setup_wave_in_cutover` → `setup_practice_onboarding` → `setup_onboarding_with_active_contract` → `setup_affiliated` / `setup_two_affiliated_practices`, `setup_departure_settlement_pending`, `setup_practice_departed`), `__init__.py` barrel

## test_suite/ (8 test files + conftest, 77 tests)
- Queue A (difficulty): all 18 instances × 2 tests = **36 tests**
- Queue B (corner): **41 tests** covering all 42 non-stub instances except one skip

## Instances skipped (1)
- `Corner/endpoints/enrollment_list_supports_provider_and_contract_filters` — its claim rests on entity-specific list query filters (`provider_id`, `payer_contract_id`, `status`). The PRD documents only `limit`/`offset` for list endpoints (§2.3); filters appear nowhere in PRD prose, so the instance fails the PRD-coverage condition. Related filter usages elsewhere were rewritten to unfiltered list calls (safe: the runner restarts the server with an empty DB before every test).

## Stage 2 lint verdict
PASS (with the one deliberate skip above). Verified by script: every test has exactly one `Design:` tag resolving to a real instance; every difficulty instance has ≥2 tests, every covered corner instance ≥1; every docstring citation contains a quote that survives a whitespace-normalized verbatim substring check against `workspace/PRD.md` (backtick-exact); no `skip`/`skipif`/`xfail` markers; all files byte-compile; pytest collects 77 tests cleanly.

## Step 6: Generate Implementation — 2026-09-30T01:55:00.000Z

Implementation complete.

## Summary

**Files written** in `/home/ubuntu/github/CodingPRD/tasks/task_3110_independent_practice_affiliation_into_single_medical_group/workspace/implementation/`:

| File | Lines | Purpose |
|---|---|---|
| `app.py` | 56 | Flask entry, blueprint registration, error handlers, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 36 | In-memory store; logical clock defaults to exactly `2026-09-01T00:00:00Z` |
| `errors.py` | 130 | ApiError + all 40 catalog error constructors with exact IDs/HTTP codes |
| `middleware.py` | 37 | `X-User-ID`/`X-User-Role` validation, 9-role RBAC |
| `response.py` | 115 | Envelope (`meta`/`response_type`/`data`), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10/min 1/max 100), `id`/`created_at`/`updated_at`/`version` system fields |
| `validate.py` | 133 | Body shape, enums, `YYYY-MM` periods, ISO dates, ISO instant parsing |
| `services.py` | 267 | Shared-services fee (override + tiered with per-batch ROUND_HALF_UP-then-sum), provisional/final distribution variants, hold/carry-forward (inclusive threshold boundary), departure penalty (whole-month tenure), cascades (wave-complete 3-hop affiliation, departure settle, contract termination) |
| `routes_core.py` | 313 | Clock, MedicalGroup, Market (capacity), Practice (suspend/reinstate), Provider |
| `routes_agreements_waves.py` | 278 | Agreements (OCC `expected_practice_version`, supersede-on-execute, wave selector with tie-break), Waves (half-open overlap, lock OCC, window gates, rollback, completion cascade) |
| `routes_contracts.py` | 386 | PayerContract (OPERATING gate, ratification + effective-date + avg-uplift≥0.08 gates, termination cascade), FeeScheduleRate (uplift_pct 4dp ROUND_HALF_UP, PROPOSED supersede), CredentialingEnrollment (STANDARD 90d / EXPEDITED 30d+45d span, closed-interval overlap, ONBOARDING→APPROVED vs AFFILIATED→EFFECTIVE landing) |
| `routes_revenue.py` | 300 | CollectionBatch (settle/adjust, dup per practice+contract+period, EFFECTIVE-enrollment linkage), DistributionStatement (provisional at create, finalize with SoD + settled-batch gate, amend with OCC + version increment, reissue) |
| `routes_incentives.py` | 299 | Pools (ACTIVE + value-eligible gates) and allocations (quality threshold, weight 6dp, floor + one-cent remainder waterfall ordered by frac DESC / quality DESC / created_at ASC, exact `allocated_total_cents == pool_amount_cents`) |
| `routes_governance.py` | 294 | DepartureCase (notice/earliest/assumed dates, estimated penalty, dispute loop, settle with `ERR_EXIT_DATE_NOT_REACHED` + full cascade, rescind), CommitteeVote (eligible-voter snapshot, one ballot per provider, majority auto-close incl. exhaustion rule) |
| `start.sh` | 9 | Guarded install + `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0` |

**Total: 2654 lines.**

**start.sh**: `set -euo pipefail`, `cd` to script dir, installs deps only when `python3 -c "import flask"` fails (guarded so per-test reboots skip pip), then `exec python3 app.py` in the foreground. `app.py` reads `PORT` (default 10000) and binds `0.0.0.0`.

**Boot smoke test**: server booted via `bash start.sh` on a test port; verified create-group 201 envelope shape, list pagination meta, missing-header → `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` 400; then exercised the full happy path (activate group → market → practice → wave plan/lock/start-cutover → agreement draft with OCC → execute (wave selector, PROSPECT→ONBOARDING) → wave complete → cascade to AFFILIATED with `affiliation_effective_date` from the logical clock). A second fresh boot confirmed the store starts empty (`total_count: 0`), satisfying per-test-server isolation. No entities are seeded at startup; all state is built through the declared API surface. Only self-started PIDs were killed.

## Step 7: Run Tests and Iterate — 2026-09-30T02:38:22.736590021Z

NOTE (orchestrator): The first Step 7 subagent (launched ~01:55 UTC) was interrupted mid-flight when the host session ended. Its stale sweep results (77 total / 70 passed / 7 failed, identical across all 8 rounds) were on disk, along with unlogged fixes applied between 01:58–02:01 UTC to: implementation/routes_contracts.py, test_helpers/fixtures.py, test_suite/test_03_calculations.py, test_suite/test_04_workflows_cascades.py. A fresh Step 7 subagent was spawned to discard the stale results and re-verify the current state with a clean 8-round sweep. Its report follows verbatim:

All 8 rounds pass cleanly — 77/77 in every round. The fixes from the interrupted previous attempt (applied 01:58–02:01 UTC) resolved the 7 failures from the stale 01:55 UTC results.

**Summary**

- **Iterations run:** 1 fresh 8-round parallel sweep (the previous interrupted attempt's fix edits were already on disk; my first action was to discard the stale results and re-verify, per instructions).
- **Result:** 77/77 passed in all 8 rounds, zero failures, zero flakiness signals.
- **Tests deleted:** none this session.
- **Fixes applied to `test_suite/`:** none this session.
- **Fixes applied to `test_helpers/`:** none this session.
- **Fixes applied to `implementation/`:** none this session.

The prior attempt's unlogged edits (test_suite/, test_helpers/fixtures.py, and implementation/ files modified between 01:58–02:01 UTC) are confirmed effective by the fresh sweep. Exit criteria met — no further diagnosis needed.

**Reconstructed interrupted-attempt fix record (for Step 8 hand-off):** the 7 tests that failed in the stale sweep were: test_shared_services_fee_override_branch_uses_flat_rate, test_distribution_provisional_and_final_variants_diverge_on_posted_batch, test_distribution_provisional_counts_posted_at_gross_while_final_excludes, test_shared_services_fee_tier_straddle_with_chronological_batch_order, test_statement_finalize_gated_by_batch_settlement_states, test_contract_termination_cascades_enrollment_terminations, test_enrollment_window_termination_day_itself_is_occupied. Files modified in the fix window (01:58–02:01 UTC): implementation/routes_contracts.py (01:58), test_helpers/fixtures.py (01:59), test_suite/test_03_calculations.py (02:00), test_suite/test_04_workflows_cascades.py (02:01). The interrupted subagent's deletion/fix notes were lost with its context; no deletions are evident (test count stayed 77 across sweeps).

## Step 8: Finalize PRD — 2026-09-30T02:42:46.400222718Z

PRD_FINALIZED.md is complete: exactly two surgical edits, everything else verbatim. Summary below.

## Summary

**Line counts / delta:** PRD.md 333 lines (53,189 chars) vs PRD_FINALIZED.md 333 lines (53,573 chars) — +384 chars, +0.72%. Two in-place sentence revisions; no new sections, no other changes.

### Analysis of the 7 Step-7 failing tests (reconstruction of the interrupted fix agent's changes)

- **test_shared_services_fee_override_branch_uses_flat_rate** (test_03) — impl `services.py:75-94` `shared_services_fee` already matches PRD §3.6 exactly (single half-up rounding of gross × override rate; per-batch rounding for tiered). Failure was a test/setup-side defect fixed in `test_helpers/fixtures.py` / `test_03_calculations.py`. **No PRD edit.**
- **test_distribution_provisional_and_final_variants_diverge_on_posted_batch** and **test_distribution_provisional_counts_posted_at_gross_while_final_excludes** (test_03) — impl `services.py:111-135` `compute_provisional`/`compute_final` matches PRD §3.6 verbatim (POSTED at full posted amount in provisional, excluded from final). Test-side fixes only. **No PRD edit.**
- **test_shared_services_fee_tier_straddle_with_chronological_batch_order** (test_03) — impl `services.py:84-94` tiered loop matches PRD's pinned algorithm; the single-batch straddle test (same algorithm, untouched by the fix window) already passed. Test-side fix only. **No PRD edit.**
- **test_statement_finalize_gated_by_batch_settlement_states** (test_04) — impl `routes_revenue.py:260-262` skips the SoD comparison when `settled_by_user_id is None`; a blanket reading of PRD §3.6 ("differ from the `settled_by_user_id` of every covered batch") would reject finalization when the finalizer's id is null or compare against a null. PRD silence pinned → **Edit 2**.
- **test_contract_termination_cascades_enrollment_terminations** (test_04) — impl `routes_contracts.py:324-337` `_check_window_overlap` includes TERMINATED enrollments (with `termination_date`) in the overlap check; PRD §3.4 said "non-`TERMINATED` enrollment," which excluded them and made the cascade'd enrollment invisible to the check. PRD mismatch → **Edit 1**.
- **test_enrollment_window_termination_day_itself_is_occupied** (test_05) — same `_check_window_overlap` fix: closed-interval occupancy through the termination day applies to terminated enrollments too. Covered by **Edit 1**. (Note: this test lives in test_05; the step_7_diff attributed it to test_04, but it is the same behavior and the same fix.)

### Changes (one bullet each)

- **§3.4 (Approval/window exclusivity)** — revise — replaced "must not overlap any other non-`TERMINATED` enrollment" with: the new enrollment's window is unbounded on the right at approval (`termination_date` null), and the check applies to any same-provider/contract enrollment already assigned an `effective_date` (i.e. not still `SUBMITTED`); a `TERMINATED` enrollment still occupies its closed window through its `termination_date` — `implementation/routes_contracts.py:313-337` (`_check_window_overlap`).
- **§3.6 (Statement finalization, SoD check)** — revise — finalizer's `X-User-ID` must differ from the *non-null* `settled_by_user_id` of every covered batch; a batch with null `settled_by_user_id` is not compared — `implementation/routes_revenue.py:260-262`.

### Per-edit pre-edit search log (NO-NEW-MISMATCH rule)

**Edit 1 — subject: enrollment window-overlap check at approval.**
- (b) Paths enumerated and read: the only overlap check is `_check_window_overlap` in `routes_contracts.py:313-337`, called solely from `approve_enrollment` (`routes_contracts.py:357`). All writers of `termination_date`: manual terminate (`routes_contracts.py:371-386`, explicit client date), departure cascade (`services.py:209-236`, `practice_depart`, sets `termination_date = actual_exit_date`), contract-termination cascade (`services.py:239-249`, `contract_terminate_cascade`, sets `termination_date = clock date`). Departure cascade also terminates `SUBMITTED` enrollments without an `effective_date` — the new wording's condition "has already been assigned an `effective_date`" (not status-based) correctly keeps such rows out of the check. Also consistent with §2.10's closed-interval sentence and with the departure/contract cascade prose, which does not mention overlap.
- (c) Wording adjustment: deliberately avoided the impl's internal "skip SUBMITTED" phrasing in favor of the observable condition "assigned an `effective_date`," which is equivalent for every reachable state (APPROVED/EFFECTIVE/TERMINATED all have `effective_date`; SUBMITTED never does) and avoids a false universal claim tied to status names.

**Edit 2 — subject: segregation-of-duties comparison at statement finalization.**
- (b) Paths enumerated and read: SoD is enforced only in `finalize_statement` (`routes_revenue.py:243-267`); amend (`routes_revenue.py:270-287`) and reissue (`routes_revenue.py:290-300`) do no SoD check — wording scoped to finalization only. Writers of `settled_by_user_id`: initialized null at batch creation (`routes_revenue.py:74`), set to the settling accountant's `X-User-ID` at settle (`routes_revenue.py:128`); never reset by adjust (`routes_revenue.py:133-151`). The finalize loop only runs when no POSTED batch exists (the `ERR_UNSETTLED_BATCHES_EXIST` check precedes it). The cross-reference in §2.1 and §2.9 step 3 mention SoD but not the per-batch comparison, so no conflict.
- (c) Wording adjustment: added "non-null" plus the explicit carve-out "a batch whose `settled_by_user_id` is null is not compared" to describe impl exactly without claiming anything about amend/reissue.

**Verification:** The verification sweep in step_7_diff already confirmed the post-fix implementation passes 77/77 in all 8 rounds; the two edits align PRD_FINALIZED.md with that exact implementation behavior.

## Step 9: Complete PRD — 2026-09-30T02:56:58.626740443Z

Section structure is identical (only line numbers shifted by the single new paragraph in §2.2). Done.

## Summary

- **Source**: `workspace/PRD_FINALIZED.md` (333 lines, 53,793 chars)
- **Output**: `workspace/PRD_COMPLETED.md` (335 lines, 58,448 chars; +4,655 chars, +2 lines from one inserted paragraph in §2.2). No sections added or removed.
- **Counts**: 19 ambiguity-pins (inserts), 7 mismatch-revisions (26 edits total).

Changes (section — kind — class — what — impl ref):

- §2.1 — revise — mismatch — "malformed header" pinned to blank/whitespace `X-User-ID` or unrecognized role spelling — middleware.py:25-28
- §2.1 — revise — mismatch — ballot eligibility checked against a live recomputation of the eligible-voter population, not the creation snapshot — routes_governance.py:276-278
- §2.2 — insert — ambiguity — unrecognized routes → `ERR_INVALID_REQUEST`/404, unsupported method → 405, unexpected failure → `ERR_INVALID_REQUEST` — app.py:33-47
- §2.3 — insert — ambiguity — list sort tie-break by `id` ascending after `created_at` — response.py:98
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — response.py:111
- §2.6 — insert — ambiguity — fee modes compute from the exact decimal rate value, never a pre-rounded form (override × aggregate gross in one rounding) — services.py:79-82
- §2.7 — insert — ambiguity — wave lock: OCC checked before the `PLANNED` state check — routes_agreements_waves.py:219-225
- §2.7 — insert — ambiguity — statement amend: OCC checked before the status check — routes_revenue.py:274-283
- §2.9 — revise — mismatch — identity binding on path-addressed resources (execute/dispute/rescind) runs after path resolution; body-field binding runs before existence — routes_agreements_waves.py:110-114, routes_governance.py:121-123,174-176
- §2.9 — insert — ambiguity — amount-positivity enforced at the shape stage on all endpoints — routes_revenue.py:45-46, routes_incentives.py:46-47, routes_contracts.py:174-177
- §2.9 — insert — ambiguity — within stage 7, own-state check precedes cross-entity gates (settle denial bounds after `POSTED` check; allocation pool-state before practice affiliation) — routes_revenue.py:120-123, routes_incentives.py:243-245
- §2.9 — insert — ambiguity — stage-10 intra-ordering pinned (uniqueness < capacity < window-overlap; org_npi convention never fails) — (documentation-level; no impl counterpart by design)
- §2.9 — insert — ambiguity — fiscal gates run in endpoint-declared order (unsettled-batches before SoD) — routes_revenue.py:256-262
- §3.1 — revise — mismatch — group `tin` uniqueness is a business convention, not validated — routes_core.py:63-76
- §3.1 — revise — mismatch — `ERR_GROUP_NOT_OPERATING` applies to any non-OPERATING status, not just FORMING — routes_contracts.py:58-61
- §3.1 — revise — mismatch — `state_code` validated only as a non-empty string — routes_core.py:118
- §3.1 — insert — ambiguity — market capacity checked after group/market existence — routes_core.py:171-182
- §3.2 — insert — ambiguity — agreement-draft ownership check precedes practice-existence resolution — routes_agreements_waves.py:61-65
- §3.2 — revise — mismatch — `org_npi` uniqueness is a convention, not validated — routes_core.py:170-197
- §3.2 — insert — ambiguity — `non_compete_accepted` checked after OCC — routes_agreements_waves.py:66-69
- §3.2 — insert — ambiguity — wave selector final tie-break by wave `id`; `ERR_NO_WAVE_IN_CUTOVER` applies no side effects — routes_agreements_waves.py:122-147
- §3.3 — revise — mismatch — `wave_code` uniqueness is a convention, not validated — routes_agreements_waves.py:159-186
- §3.4 — revise — mismatch — provider `npi` uniqueness not validated — routes_core.py:264-287
- §3.4 — insert — ambiguity — new enrollment's `effective_date`/`termination_date` are null; EXPEDITED span of exactly 45 days accepted — routes_contracts.py:263-277
- §3.4 — insert — ambiguity — approval requires practice ONBOARDING/AFFILIATED at approval time — routes_contracts.py:354-355
- §3.4 — insert — ambiguity — manual termination requires explicit `termination_date` (absence → `ERR_INVALID_REQUEST`); empty windows (term < effective) accepted — routes_contracts.py:375-385, services.py:330-336
- §3.5 — insert — ambiguity — `legacy_rate_cents`/`group_rate_cents` must be strictly positive — routes_contracts.py:174-177
- §3.5 — insert — ambiguity — the vote snapshot fixes only `eligible_voter_count`; cast-time eligibility is live — routes_governance.py:222-235, 276
- §3.5 — insert — ambiguity — exhaustion closes when cast ballots reach `eligible_voter_count`; casts on a closed vote → `ERR_INVALID_TRANSITION` — routes_governance.py:274-292
- §3.6 — insert — ambiguity — new batch has `settled_amount_cents`/`net_settled_cents` null until settlement — routes_revenue.py:64-76
- §3.6 — insert — ambiguity — statements may be created for batch-less periods; tiered fee mode also applies when no EXECUTED agreement exists — routes_revenue.py:176-178, services.py:79-80
- §3.7 — insert — ambiguity — share-waterfall ordering gains final tie-break by allocation `id` ascending — routes_incentives.py:151-159
- §3.8 — insert — ambiguity — second non-terminal departure case rejected with `ERR_INVALID_TRANSITION`; non-terminal statuses enumerated — routes_governance.py:30, 46-48

Notable false leads verified against impl and left unchanged: hold/carry boundary is inclusive (PRD already correct), departure notice sufficiency is inclusive (`>=` in both), and batch duplicate-check-before-linkage ordering matches §2.9's stage 10 < stage 11.
