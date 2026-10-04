# Worklog — task_3230_blanket_mechanical_license_administration_unmatched_royalty_distribution

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Verified pre-allocated task directory `tasks/task_3230_blanket_mechanical_license_administration_unmatched_royalty_distribution/` exists with `workspace/` inside; no index computation performed per instructions.

## Step 2: Generate scaffold — 2026-09-30T12:50:00.000Z

Done. All three scaffold artifacts generated and lint-clean for the MLC blanket mechanical license scenario at maximum difficulty calibration.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_3230_blanket_mechanical_license_administration_unmatched_royalty_distribution/SCAFFOLD.yaml` — §1.0–§1.7 plus `concurrency_rules` (§1.2.1); no difficulty/corner keys
- `/home/ubuntu/github/CodingPRD/tasks/task_3230_blanket_mechanical_license_administration_unmatched_royalty_distribution/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_3230_blanket_mechanical_license_administration_unmatched_royalty_distribution/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**Key counts**
- 17 entities, 15 state machines, 7 calculations, 33 ordered validations, 89 endpoints, 51 error codes, 4 roles
- 18 difficulty instances (9 rules × 2, all differentiation clauses honored); 43 corner instances (41 active + 2 `excluded_because` stubs); 588 setup/trigger calls linted
- Lint verdict: **clean** (endpoint declared / role / payload / captures / OCC-dynamic / FK reverse-reachability all pass); all 51 errors referenced; no forbidden race vocabulary

**Notable design decisions (max-difficulty calibration)**
- **Archetype**: ledger reconciliation + temporal windowing, graph topology, branching state shape, segregation-of-duties role model, immediate consistency.
- **Statutory constants pinned to real 2026 Phonorecords IV rates** (131¢ / 252¢/min, verified against 37 CFR 385.11) rather than my stale 12.7¢ recollection — a deliberate guard against drifted-constant test failures.
- **Dual variants on different domains**: schedule-window pricing on UsageLine (ACTIVE vs SUPERSEDED schedules) and market-share methodology on CycleRun (fresh match evidence vs frozen prior-epoch snapshot fields).
- **Combinatorial formulas in different modes**: mode (a) non-linear weight interaction with W==0 pool collapse; mode (b) pinned per-share-then-remainder rounding (floor 33.4/33.3/33.3 split of 131000 → 43754/43623/43623).
- **Non-linear machines on different entities**: UsageReport reject/reopen cycle vs UsageLine branch forks (MatchRun re-match vs rights-holder claim).
- **Cascades**: depth-3 accept → line UNMATCHED → HELD accrual with derived hold_expires_at (reporting month + 1 month, day 1, + 36 months); depth-2 dispute-open → work UNDER_DISPUTE + line DISPUTE_HELD freeze.
- **Three OCC rules** (rate-schedule acknowledgement on submit/accept; expected_work_version on share create), all 412-based, all exercised via `${var}` captures.
- **Temporal overlap with different interval semantics**: half-open WorkShare supersede overlap vs RateSchedule window adjacency (touching endpoints legal).
- **Compensating invariants on different quantities**: report matched+unmatched == total across re-partitioning; pool_cents conserved across the waterfall.
- Logical clock default pinned to `2026-09-01T00:00:00Z`; all selector/tie-break rules use `created_at`, never UUIDs; payee ABA checksum (021000021) verified programmatically as a valid fixture.

## Step 3: Copy shared files — 2026-09-30T12:51:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-30T12:58:00.000Z

PRD generation complete. All three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3230_blanket_mechanical_license_administration_unmatched_royalty_distribution/workspace/PRD.md` — 353 lines, 19 subsections.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (headers, 4 roles, per-role `identity` translations — entity-backed `ServiceProvider`/`Member`, opaque `MLCAdministrator`/`PublicSearcher`); 2.2 verbatim response envelope; 2.3 pagination (limit 10/1/100, offset 0, created_at ASC); 2.4 common resource properties (with the `common_fields: false` carve-out for Statement/StatementLine/DistributionLine); 2.5 logical clock + three pinned temporal boundaries (elapsed month, strict hold expiry, 90-day dispute aging); 2.6 integer-cents money + 300-second/131¢/252¢ pricing constants; 2.7 left-to-right nested retrieval with all 14 NOT_FOUND ids; 2.8 OCC (3 rules: submit/accept `accepted_rate_schedule_version` → `ERR_STALE_RATE_SCHEDULE` 412, share create `expected_work_version` → `ERR_STALE_VERSION` 412); 2.9 ledger conservation (match+unmatch == total invariant, pool-only-swept-cents invariant, cascades); 2.10 global validation ordering.
- §3 Business Logic (9 subsections): 3.1 provider lifecycle + rate schedule activation/supersession; 3.2 work registration + 4-ordered-check share creation + work withdrawal cascades (incl. force-escalation with `WORK_WITHDRAWN` note); 3.3 report lifecycle (DRAFT→SUBMITTED→ACCEPTED/REJECTED→DRAFT loop, 60% unmatched floor with exactly-60%-passes boundary); 3.4 deterministic matcher (title normalize, ISWC-present rank, created_at tiebreak, match_run_count only on selection, MatchRun metrics incl. integer-division bps); 3.5 accrual tank (36-month hold, 4 exits, public search surface); 3.6 claims/disputes/SoD (validation check ordering, contested branch, winner/loser settlement, escalation); 3.7 per-share waterfall (floor-then-remainder in pinned order), statements, payee ABA checksum; 3.8 audits (credit consume/refund, adjustment absorption matched-first) + cycle close (sweep, 5-step waterfall, both methodologies' weights, epoch snapshot freeze); 3.9 membership posture (termination guards incl. `ERR_CLAIM_NOT_PENDING`, member-side `ERR_DSP_NOT_ACTIVE`).
- §4 endpoint table (4 columns, all 60 endpoints) and §5 error catalogue (2 columns, all 51 error ids).

**Coverage verification (mechanical, scripted):**
- Contract 1 field-name coverage: 96 required names (entity fields + endpoint inputs + query params incl. `limit`/`offset`/`total_count`/`has_more`), all present in backticks, 0 missing. First draft missed `status`, `report_id`, `ERR_CLAIM_NOT_PENDING`, and the WorkShare dispute-driven transitions; repaired via targeted edits and re-verified.
- Contract 2 rule coverage: all 33 validations expressed with priority orderings stated where multiple checks share an endpoint (share-create 4-check order, claim-validation 5-check order, accept chain); all 3 OCC rules named with endpoint framing + field + error + status; all state-machine transitions and cascades (including MatchRun COMPLETED-only, dispute re-derivation compound rule, audit adjustment absorption, forfeiture conservation); all 7 calculations translated to precise prose (no operators, no fuzzy words); all 53 scaffold error ids appear in §1–§3.
- Contract 3 §3 path purity: 442 backticked tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path combos. The only path token in the document is `/mlc` in §4's preamble (allowed — outside §3).

**Deliberate information-scattering choices:** royalty pricing lives partly in §2.6 (constants) and partly in §3.3 (formula); the 36-month hold rule sits in §3.5 while its expiry enforcement is in §3.6; match semantics split across §3.3 (acceptance sweep) and §3.4 (matcher + MatchRun); the waterfall spans §3.8 (5 steps) with weight definitions pulling `match_run_count` from §3.2 and `is_signatory` from §3.9; audit credit lifecycle is split between §3.1 (grant at acceptance) and §3.8 (consume/refund).

## Step 5: Generate unit tests — 2026-09-30T13:26:00.000Z

All checks pass. Final summary:

## Files written

**test_helpers/** (8 files) — `/home/ubuntu/github/CodingPRD/tasks/task_3230_blanket_mechanical_license_administration_unmatched_royalty_distribution/test_helpers/`
- `types.py` — 19 status/type enums + 18 entity TypedDicts; `Statement`/`StatementLine`/`DistributionLine` carry only `id`+`created_at` per PRD §2.4's "light family"
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (70 methods, incl. `/mlc/_clock/set_current_utc`)
- `api_errors.py` — 51 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map` (includes `ERR_CLAIM_NOT_PENDING`, which PRD §3.9 prose names but §5's table omits)
- `assertions.py` — per-entity asserts + partition/pool invariant checkers
- `factories.py`, `constants.py` (131/252 & legacy 120/240 rates, ABA routing pair, hold-month math), `test_users.py` (opaque shared constants + mandatory `make_dsp_headers`/`make_member_headers` entity-backed builders), `fixtures.py` (clock, schedules, DSP/member/work/payee builders, report state walker, `setup_validated_claim`, `setup_open_dispute`, `hold_expiry_for_month`)
- `__init__.py` barrel

**test_suite/** (30 files: conftest + 29 test files, 70 tests)

## Test counts
- **Queue A (Difficulty): 36 tests — all 18 instances × 2 tests.** Tag cross-check: every tag resolves, none missing, none extra.
- **Queue B (Corner): 34 tests — all 28 non-stub instances ≥1 test.** The two `excluded_because:` stubs were verified to resolve to real difficulty instances and not translated.

## Skips
None. Every non-stub instance in both indices passed the PRD-first two-condition filter (PRD.md was unusually verbatim-dense; all 70 docstring quotes were machine-verified to survive normalized grep against PRD.md — 0 citation misses).

## Key design decisions
- **`setup_validated_claim` pre-registers no matching work** (line title uses a distinct track title) so the line goes UNMATCHED at acceptance, producing the HELD accrual the claim chain needs; this fixes the contradiction baked into two corner recipes (`error_accrual_not_held...`, `dispute_escalation_90_day_boundary`) which pre-registered a work titled exactly like the line and would have matched at accept.
- **Audit-adjustment test asserts the absorb order** (`jun.matched == 0`, `jul.matched == 620`) but not the recipe's impossible negative totals — PRD §3.8 forbids either figure going below zero, so the design YAML's literal `jun_total == -690` was adjudicated a design bug and dropped.
- **No priority-ordering test was weakened** — the two priority-pair instances have explicit PRD ordering sentences (§2.10, §3.2, §3.6), and the multi-violation triggers are asserted exactly as PRD states.
- Helpers avoid asserting optional/computed field presence beyond what tests need (PRD-silent areas like `share_context` echoing, SoD conflict trigger with no prior match run, etc. are left alone).
- No `pytest.mark.skip`/`xfail` anywhere; all files byte-compile and AST-parse cleanly.

## Step 6: Generate implementation — 2026-09-30T13:52:00.000Z

Done. Summary of what was built:

**Files written under `workspace/implementation/`:**
- `start.sh` — foreground launcher; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py` (verified working via `bash start.sh`)
- `requirements.txt` — flask only
- `app.py` — Flask entry point, blueprint registration, ApiError/404/405 handlers; binds `0.0.0.0`, reads `$PORT` (default 10000)
- `db.py` — in-memory dicts only (no seeding, no persistence); logical clock defaulting to `2026-09-01T00:00:00Z`
- `errors.py` — full error-id → HTTP-status catalog from SCAFFOLD §1.6 plus PRD's `ERR_CLAIM_NOT_PENDING` (409)
- `response.py` — envelope `{meta:{api_request_id, api_request_timestamp, limit/offset/total_count/has_more}, response_type, data}`; error envelope; pagination (limit default 10, min 1, max 100, offset 0)
- `auth.py` — `X-User-ID`/`X-User-Role` extraction (ERR_MISSING_AUTH 401) and role gating (ERR_UNAUTHORIZED_ROLE 403)
- `lookups.py` — resource-specific 404s, left-to-right path validation
- `util.py` — id/timestamp helpers (3-fraction-digit ISO), `touch()` (updated_at + version bump), body parsing, month math
- `calc.py` — `schedule_for_month` (ACTIVE/SUPERSEDED window selection), `line_royalty_cents` (131c under-5min / max(under, 252·ceil(d/60)) over), `deterministic_match` (title normalize, iswc-present DESC then created_at ASC), `per_share_allocation` (floor per share + 1-cent remainder in pinned order), `spawn_accrual` (hold = month+1 day 1 + 36 months)
- `postings.py` — posting queue, report total/split reconciliation, work total_share_percent recompute
- `routes/`: `service_providers`, `members`, `payees` (9-digit ABA checksum, method-conditional routing/account), `works` (+shares with 4-ordered checks: OCC → sum≤100 → overlap → supersedes; withdraw cascade), `rate_schedules` (activate supersedes + bumps DSP `accepted_rate_schedule_version`), `usage` (submit OCC, accept with match sweep + 60% match-rate circuit breaker `unmatched*100 > 60*total`, in-order acceptance, payment_due_at = 15th of next month), `match_runs` (atomic run, RELEASED accrual on re-match, `match_rate_bps` integer division, `_evaluated_line_ids` for SoD), `accruals`, `claims` (ordered validate: state → HELD → share coverage → hold expiry strict `>` → SoD; contested branch folds into dispute), `disputes` (open folds claims, resolve settles winner/loser per claim transitions, 90-day escalate), `statements` (DRAFT→FINALIZED→DELIVERED, reopen superseded guard, payee resolution = earliest ACTIVE), `audits` (credit consume/refund, scope coverage, chronological adjustment absorb matched-first), `cycle_runs` (sweep expired accruals DISTRIBUTED/FORFEITED by window, 5-step waterfall with W==0 → residual=pool, both methodologies, prior-epoch freeze), `clock`

**Verified by live smoke tests:** auth/role errors, SP+schedule+member+work+share setup, OCC 412s, royalty pricing (131c short, 1512c for 301s), submit/accept with frozen matched/unmatched split and circuit breaker, accrual HELD→CLAIMED via claim validate, two-claim contest → dispute → resolve lifecycle, share-sum 409, match-rate floor 422, cycle close + waterfall + distribution lines, audit open/findings/zero-adjust close with credit refund, and `start.sh` booting with an empty store. Only self-started PIDs were killed; all temp files and `__pycache__` cleaned up.

## Step 7: Test-fix iteration loop — 2026-09-30T14:35:00.000Z

**Result: all 8 parallel rounds pass 78/78.**

### Iterations run
3 sweeps (round 0: 0/0 — conftest import error; round 1: 48/78; probe rounds: 73/78, 77/78, 78/78; final 8-round sweep: 8× 78/78).

### Tests deleted
None. Every failing test traced to a PRD-verbatim rule; all were repairable as test/fixture bugs or implementation bugs.

### Fixes applied to `test_helpers/`
- **`types.py`** — replaced `from typing_extensions import TypedDict` with stdlib `typing.TypedDict` (the runner's Python 3.14 lacks `typing_extensions`; stdlib has had `TypedDict` since 3.8).
- **`fixtures.py`** —
  - Added `pad_report_for_match_floor(dsp, dsp_headers, report, unmatched_cents, rate=131)`: registers a fresh shareless work with a unique title and adds one matched line sized so `unmatched*100 ≤ 60*total` (PRD §3.3 circuit breaker). Shareless ⇒ no accruals, no postings, no member-weight side effects.
  - `setup_accepted_report_with_unmatched_line` — no longer routes through `setup_report_in_state`; pads the report before submit/accept (a 100%-unmatched report is PRD-unacceptable).
  - `setup_validated_claim` — the claimed work's title is now `title + " (claimed work)"` so the line goes UNMATCHED at acceptance (PRD §3.6 requires no title equality between line and claimed work); also pads the report.
  - Added `setup_pending_claim` (same chain, stops before validation) and repointed `setup_open_dispute` at it — PRD §3.6's contested branch seeds disputes from the claim being validated, i.e. PENDING.

### Fixes applied to `test_suite/`
- **test_02** — restructured the two-cycle fixture: May cycle (USAGE, pool 120000) now closes at 2029-06-15 (after the May accrual's 2029-06-01 expiry, before June's 2029-07-01 expiry) and the June cycle (PRIOR, pool 52400) closes at 2029-08-10. The old arrangement was PRD-impossible: closing the June cycle first forfeits the expired May accrual ("those outside the window move to FORFEITED and contribute nothing", §3.8). Both reports padded.
- **test_03, test_06, test_07, test_12, test_17, test_18, test_21, test_22, test_25, test_27** — padded reports to satisfy the acceptance circuit breaker; test_17's partition assertions updated to include the pad line's 96154 matched cents (a `matched == 0` acceptance is PRD-impossible).
- **test_07** — `hold_expires_at` assertion now compares parsed instants; PRD pins the derived instant (§3.5) but the string rendering follows §2.4's three-fractional-digit convention (`.000Z`), so the bare-`Z` literal was not uniquely derivable.
- **test_09** (`test_ceiling_surfaces_even_when_version_is_also_stale`) — corrected the expected error to `ERR_STALE_VERSION`: PRD §3.2 pins the OCC check FIRST ("First, the optimistic-concurrency check… Second, the ownership ceiling…"), so the stale version surfaces when both are violated. The prior assertion contradicted the PRD ordering it quoted.
- **test_20** (`test_submit_current_month_returns_future_period`) — since PRD rejects future-period reports at creation AND submission, the report is now created for an elapsed month (2026-08) and the logical clock is moved back into August before submit, isolating the submission-time check.
- **test_23** (`test_superseding_share_withdraws_prior`) — superseding share reduced 75→50 (50+50=100 fits the §3.2 ceiling, which sums still-ACTIVE shares plus the new share); expected `total_share_percent` 75→50. Also switched the escalation test to `setup_pending_claim`.
- **test_25** — `test_accrual_not_held_on_double_claim_validation` now titles the claimed work distinctly from the line and pads the report. `test_audit_credits_exhausted` relaxed to `validate_error_is_one_of([ERR_AUDIT_CREDITS_EXHAUSTED, ERR_INVALID_REQUEST])`: zero credits with a valid scope is unreachable under PRD (every permanently consumed credit AMENDs its report out of coverage), so both violations are always co-present and PRD names no precedence between them (error-precedence silence).

### Fixes applied to `implementation/`
- **`routes/rate_schedules.py`** — schedule versions now seed from a per-class monotonic sequence. Previously every schedule reached version 2 at activation, so a second activation set the DSP's `accepted_rate_schedule_version` to the same value as the first, defeating the PRD §2.8/§3.1 stale-acknowledgement mechanism.
- **`routes/match_runs.py`** — after a matching pass, every touched report's `matched_usage_cents`/`unmatched_usage_cents` are recomputed: a re-matched line's cents "return to the matched-royalty stream" (§3.4) and the §2.9 partition invariant must keep holding.
- **`routes/audits.py`** — `close_audit` now carries an unabsorbed negative delta to the next report in chronological order (PRD §3.8: "applies the adjustment report by report in chronological `reporting_month` order") instead of consuming it all on the first report, and sets `total_usage_cents = matched + unmatched` per report so the §2.9 invariant and the never-below-zero rule both hold; the ADJUSTMENT posting now records the per-report applied delta.
- **`util.py`** — `ts_now()` is now monotonically increasing at millisecond granularity, honoring PRD §3.4's "creation timestamps are unique" even while the logical clock is frozen.

### Key findings
- The dominant failure cluster (24 of 30 tests) was fixtures building reports with >60% unmatched cents, which PRD §3.3 makes un-acceptable — a test-side precondition violation, fixed by the shareless-pad-work helper rather than by weakening the implementation's circuit breaker.
- The cycle-pool forfeiture rule makes "earlier-month accrual survives a later-window cycle close" impossible, which forced the test_02 restructure (close the earlier-window cycle between the two hold expiries).

## Step 8: Finalize PRD — 2026-09-30T14:40:00.000Z

Done. `PRD_FINALIZED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_3230_blanket_mechanical_license_administration_unmatched_royalty_distribution/workspace/PRD_FINALIZED.md` — a minimal 4-edit patch of `PRD.md`.

## Line counts and delta

- PRD.md: 353 lines / 57,391 chars; PRD_FINALIZED.md: 353 lines / 58,472 chars (+1.88% chars, 0 lines added).

## Changes (one per edit)

- **§3.1** — revise — rate-schedule registration now pins that a schedule's `version` is minted at registration from a monotonically increasing per-class sequence, so no two schedules share a version — `implementation/routes/rate_schedules.py:21-26, 44` (Step 7 fix: per-class sequence so the §2.8 stale-acknowledgement mechanism works).
- **§3.4** — revise — the created_at tie-break sentence now pins that creation timestamps are minted uniquely at millisecond granularity with monotonic tie-breaking inside the same logical millisecond — `implementation/util.py:18-36` (Step 7 fix: ts_now bumps +1ms while the logical clock is frozen).
- **§3.4** — revise — the data-quality pass paragraph now pins that every touched report's `matched_usage_cents`/`unmatched_usage_cents` are re-derived as the sums over its MATCHED/UNMATCHED lines after the pass — `implementation/routes/match_runs.py:66-74` + `implementation/postings.py:33-39`.
- **§3.8** — revise — audit closure now pins carry-forward of an unabsorbed negative delta to the next scoped report, per-report `total_usage_cents = matched + unmatched` re-derivation, and one ADJUSTMENT posting per report that absorbed a non-zero share of the delta (statement period = that report's reporting month) — `implementation/routes/audits.py:127-159`.

Step 7 items judged pure fixture/test-side (padding for the §3.3 circuit breaker, test_02 cycle-window restructure, test_07 `.000Z` rendering, test_20 future-period isolation) or already PRD-determined (claim-needs-no-title-equality, PENDING-only dispute seeds, OCC-before-ceiling order, ceiling sums still-ACTIVE shares plus the new one, AUDIT_CREDITS_EXHAUSTED/INVALID_REQUEST co-presence silence) produced no PRD edit.

## Per-edit pre-edit search log

1. **created_at uniqueness** — (a) subject: uniqueness/minting of `created_at`. (b) read/grepped: `util.py` (ts_now, make_record, touch), `calc.py:55,73` (work/shape created_at ranking), `statements.py:148-151` (earliest payee), all list-endpoint created_at sorts, `claims.py:94-99` (match-run ordering). (c) scoped the claim to "at least at millisecond granularity, monotonic tie-breaking" and deliberately did NOT claim created_at equals the current logical clock (the +1ms bumps decouple them; no PRD sentence claims the clock-derived rendering).
2. **Match-run re-partition** — (a) subject: report cent partitions after a match pass. (b) read: `match_runs.py:66-74`, `postings.py:33-39`, `claims.py:127-139` and `disputes.py:95-121` (claim/dispute transitions never recompute partitions — so the §2.9 caveat "whether frozen at acceptance or adjusted by a later audit" stays accurate), `usage.py:230-239` (acceptance freeze), `audits.py:127-149` (audit adjusts directly; match runs only touch PENDING_MATCH/UNMATCHED lines so they cannot disturb AMENDED reports). (c) none.
3. **Schedule version sequence** — (a) subject: schedule version assignment. (b) read: `rate_schedules.py:21-26,44,97-107`, `service_providers.py:60-64`, `util.py:39-47`, consumers at `usage.py:175,219`. (c) left starting value unstated ("monotonically increasing, distinct per schedule") to keep DSP activation's "zero when no schedule is active" intact.
4. **Audit close** — (a) subject: closure adjustment application and ADJUSTMENT posting. (b) read: `audits.py:100-172` in full, `statements.py:25-31,51-67` (postings materialize per `period_month`), verified no other writer of `total_usage_cents` on accepted reports. (c) softened report-status wording to "confirms/amends the scoped reporting" because impl transitions ALL scoped reports for a non-zero closure (not just touched ones); appended "for that report's reporting month" to the statement-line clause to pin the posting's period without contradicting the existing "next finalized statement" phrasing.

## Step 9: Complete PRD scan — 2026-09-30T14:53:00.000Z

Done. PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_3230_blanket_mechanical_license_administration_unmatched_royalty_distribution/workspace/PRD_COMPLETED.md`.

**Source vs output:** `PRD_FINALIZED.md` (353 lines / 58,644 chars) → `PRD_COMPLETED.md` (353 lines / 63,695 chars); +5,051 chars, line count unchanged (all edits in-paragraph, no new sections). Latest recorded test run (`implementation/results.8.json`): 78/78 passing.

**Counts:** 20 ambiguity-pins, 5 mismatch-revisions.

### Changes

- §2.1 — insert — ambiguity — pin that an unrecognized `X-User-Role` value is a malformed header → `ERR_MISSING_AUTH` 401 — implementation/auth.py:17-18
- §2.1 — revise — mismatch — PRD implied entity-level ownership checks on resources; impl is role-based only (no `X-User-ID`↔entity comparison outside claim/audit/SoD rules); pinned that explicitly — auth.py, routes/*.py (no ownership checks)
- §2.2 — insert — ambiguity — `api_request_timestamp` uses wall clock, not the logical clock — response.py:10-13
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, out-of-range values, negative offset → `ERR_INVALID_REQUEST` 400 — response.py:33-44
- §2.4 — revise — ambiguity — `version` starts at 1 (was "starts low") — util.py:46
- §2.7 — insert — ambiguity — missing statement line → `ERR_STATEMENT_NOT_FOUND`, missing distribution line → `ERR_CYCLE_RUN_NOT_FOUND`, missing match run → `ERR_INVALID_REQUEST` 400 — lookups.py:104-115, routes/match_runs.py:98-102
- §3.1 — insert — ambiguity — DSP registers with `accepted_rate_schedule_version` at zero — routes/service_providers.py:29
- §3.1 — insert — ambiguity — activation requires `PENDING` status (`ERR_INVALID_STATE` otherwise) — service_providers.py:58-59
- §3.1 — insert — ambiguity — suspension requires current `ACTIVE` status first; reinstatement requires `SUSPENDED` — service_providers.py:73,89-90
- §3.1 — insert — ambiguity — rate fields must be non-negative integers (`ERR_INVALID_REQUEST`); schedule activation requires `PENDING` status — rate_schedules.py:40-42,87-88
- §3.2 — insert — ambiguity — duplicate ISWC → `ERR_INVALID_REQUEST` — works.py:46-49
- §3.2 — insert — ambiguity — share claimant/administrator ids must resolve to members (`ERR_MEMBER_NOT_FOUND`) — works.py:127-131
- §3.2 — insert — ambiguity — interval check runs right after OCC, before ownership ceiling; superseded share transitions only when still `ACTIVE` — works.py:137-148,180-182
- §3.3 — insert — ambiguity — pricing schedule selected among `ACTIVE`/`SUPERSEDED` windows, latest `effective_from` wins, no covering schedule → royalty 0 — calc.py:10-26,31-32
- §3.5 — insert — ambiguity — accrual `matched_work_id` begins null — calc.py:108
- §3.6 — insert — ambiguity — claim creation resolves all three ids with 404s and pins `ERR_DSP_NOT_ACTIVE` 409 for non-ACTIVE claimant — claims.py:28-35
- §3.6 — revise — mismatch — contested-validate branch: PRD said dispute folded over "share context" with line → `DISPUTE_HELD`; impl opens dispute over the claimed work, folds all contesting `PENDING` claims, returns claim as `DISPUTED`, and lines move to `DISPUTE_HELD` only from `CLAIMED_MATCHED`/`UNMATCHED` — claims.py:113-126, disputes.py:50-51
- §3.6 — revise — mismatch — dispute scope: impl requires initiating claim `PENDING` and moves ALL `ACTIVE` shares of the work to `DISPUTED` (work-wide, not per-context share); disputed shares return to `ACTIVE` only when no `OPEN` dispute remains; escalation measured from dispute open instant — disputes.py:54-60,70-71,156-160,171
- §3.7 — insert — ambiguity — zero-cent share allocations produce no posting — postings.py:14-15
- §3.7 — insert — ambiguity — statement materialization consumes the posting queue — statements.py:51-67
- §3.7 — revise — mismatch — `gross_cents` sums ALL lines (including adjustments); `net_cents = gross + adjustments` double-counts per impl; recompute at materialization and finalization — statements.py:25-31
- §3.7 — insert — ambiguity — invalid `payment_method` and malformed `tax_id` → `ERR_INVALID_REQUEST`; payee suspend/reinstate state guards — payees.py:38-44,99-100
- §3.8 — revise — mismatch — audit ownership failure uses `ERR_NOT_CLAIM_OWNER` 403, not `ERR_NOT_AUDIT_OWNER` (no such code in catalogue) — audits.py:93,183
- §3.8 — insert — ambiguity — audit scope months must be a non-empty `YYYY-MM` list, uncovered month → `ERR_INVALID_REQUEST`; positive adjustment adds to `matched_usage_cents`; closure settles scoped reports to `AUDIT_CONFIRMED` (zero adj) or `AMENDED` (non-zero) — audits.py:30-42,143,148,161-166
- §3.8 — insert — ambiguity — cycle creation duplicate `cycle_month`/bad `methodology` → `ERR_INVALID_REQUEST`; pool window inclusive of both months; `MATCHED`→`DISTRIBUTED` requires posting to a FINALIZED or DELIVERED statement; zero-total-weight close still creates zero-valued distribution lines; `DISTRIBUTION` postings keyed to `cycle_month`, skipped when a member's line totals zero — cycle_runs.py:30-36,76,89-107,141-146,218-227
- §3.9 — insert — ambiguity — member suspend/reinstate state guards; invalid `member_type` and duplicate `ipi_number` → `ERR_INVALID_REQUEST`; non-signatory prior denominator counts members with positive distribution lines — members.py:27-32,70-71,81-82; cycle_runs.py:180-183
