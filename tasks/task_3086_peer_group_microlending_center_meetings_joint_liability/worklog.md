# Worklog — task_3086_peer_group_microlending_center_meetings_joint_liability

## Step 1: Create Task Directory — 2026-09-29T21:24:58.778Z

Task directory pre-allocated per command args: `tasks/task_3086_peer_group_microlending_center_meetings_joint_liability/` with `workspace/` inside. Verified existence; no new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-29T21:24:58.778Z

Done. All three scaffold artifacts are written and pass `scaffold_lint.py` with a clean verdict.

Files written:

- `SCAFFOLD.yaml` (§1.0–§1.7; 1784 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single `scaffold_difficulty_design` key; 1653 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single `scaffold_corner_design` key; 1656 lines)

Counts:

- 16 entities, 66 endpoints, 10 state machines + 1 OCC concurrency rule, 10 calculations, 10 validation priority rows, 65 error codes, 5 roles
- §1.8: 9 rules × 2 instances = 18 instances; §1.9: 36 scannable instances + 3 `excluded_because` stubs; 1348 calls linted, all conforming

Lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notable design decisions (beyond-expert difficulty levers):

- **Joint-liability contagion as a depth-3 cascade**: delinquency sweep → Loan DELINQUENT → PeerGroup RESTRICTED → sibling VOTING applications EXPIRED + ladder freeze; cure reverses the whole chain. A second depth-3 cascade from a different trigger: meeting close → auto-absence → strike → VOTING application auto-REJECTED.
- **Dual-variant pair on different domains**: loan ladder (STANDARD vs REHABILITATED, 200000c vs 100000c ceilings for identical repaid principal) and credit score (provisional 720 vs final 845 for the same loan).
- **Two genuinely different interval semantics**: center meetings use half-open `[start,end)` (adjacency allowed) while manager training slots use closed intervals + 30-minute buffer (adjacency rejected).
- **Segregation of duties**: meeting closer (entity-backed CenterManager) cannot reconcile; reconciliation by the same user id yields `ERR_SEGREGATION_OF_DUTIES` — distinct from the role-level denial.
- **OCC create-with-supersede**: `POST /loans/{id}/restructures` with `expected_loan_version` (412), the only sanctioned race.
- **Pinned arithmetic everywhere**: per-transaction rounding before aggregation (reconciliation is exact-equality against rounded components), flat-rate waterfall (savings → arrears → current → prepayment, overpayment rejected), circular-looking expansion feasibility broken by evaluating tier from CURRENT members.
- **Logical clock** with mandatory default `2026-09-01T00:00:00Z`; sweeps (delinquency at ≥8 days, default at ≥30, vote expiry strictly after deadline) run on clock moves, giving deterministic boundary tests at day 7/8 and streak 1/2.
- Replayed every setup chain against §1.2/§1.4/§1.6 during authoring (including replaying cascade side effects into `setup:` claims); all 57 instance names unique across both design files.

## Step 3: Copy Shared Files — 2026-09-29T22:40:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3086_peer_group_microlending_center_meetings_joint_liability/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T22:40:00.000Z

PRD generated and audited.

**Output:** `workspace/PRD.md` (381 lines)

**Section list:**
- §1 Introduction (2 paragraphs, domain-context framing)
- §2 Global Specifications — 2.1 RBAC with per-role identity prose, 2.2 verbatim response envelope block, 2.3 Pagination, 2.4 Logical Time & Sweeps, 2.5 Common Resource Properties (incl. the three append-only record types without `updated_at`/`version`), 2.6 Monetary Representation & Rounding, 2.7 OCC on loan restructuring (`expected_loan_version` → `ERR_STALE_LOAN_VERSION` 412), 2.8 Validation Order & Error Precedence (10-tier pinned ordering), 2.9 Resource Addressing & list filters, 2.10 Segregation of Duties
- §3 Business Logic (10 subsections): 3.1 branch/staffing/caseload capacity & tier derivation, 3.2 recruitment & formation training (closed-interval + 30-min buffer), 3.3 applications & unanimous consensus (deadline asymmetry: vote invalid at deadline, sweep expires only strictly after), 3.4 disbursement, dual-variant ladder, provisional/final credit scoring, 3.5 meetings & the 4-bucket collection waterfall (half-open overlap), 3.6 delinquency sweep & 3-hop joint-liability contagion / cure / default / payoff, 3.7 close-out, reconciliation, SoD, voids, 3.8 savings locks/withdrawals/closure, 3.9 restructures (create-with-supersede, OCC), 3.10 expansion feasibility (7-step pinned evaluation)
- §4 Endpoint table (4 columns, all 38 distinct scaffold endpoints)
- §5 Error catalogue (2 columns, all 65 error IDs)

**Coverage audit results (all PASS):**
- Contract 1 (field names): 73 required (all entity fields + endpoint inputs + common/envelope fields), 73 present, 0 missing
- Contract 2 (rules): all 65 error IDs present in prose with conditions; every state-machine transition, calculation formula (pinned evaluation orders, exact thresholds — 8-day delinquency boundary, 30-day default, exactly-2 strike, ≥1 contagion, 1.5× rehab cap floored, 600-base 300–850-clamped scores), priority orderings, side-effect cascades, and sibling branches expressed; 0 missing
- Contract 3 (§3 path purity): 462 backtick tokens scanned in §3, 0 path/method violations
- Role names, all state enum values (`RECRUITED…BLACKLISTED`, `FORMING…DISSOLVED`, `DRAFT…DISBURSED`, `ACTIVE/DELINQUENT/DEFAULTED/PAID_OFF`, `PROPOSED/ACTIVE/SUPERSEDED`, dual meeting dimensions, `POSTED/VOIDED`, `OPEN/FROZEN/CLOSED`, plan states), and tier/enum values all present verbatim

The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened or referenced. No servers were started or killed.

## Step 5: Generate Unit Tests — 2026-09-29T23:10:00.000Z

Generated complete test infrastructure and test cases, translating exactly the instances in the two design indices (no freelance test discovery).

**Files written**

`test_helpers/` (9 files):
- `types.py` — 15 status enums + entity TypedDicts; the three append-only records (`ConsensusVote`, `MeetingAttendance`, `CreditBureauReport`) carry only `id`/`created_at` per PRD §2.5.
- `api_client.py` — 47 endpoint methods (one per §1.5 endpoint, deduped).
- `api_errors.py` — full `ApiErrorId` enum + HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions with append-only vs common-field branching.
- `factories.py` — input-field-only payload factories.
- `constants.py` — rate/percentage/tier/score/day thresholds and cycle-1 reference numbers (4600/200/110600/720).
- `test_users.py` — shared headers + `make_center_manager_headers` / `make_member_headers` entity-backed builders.
- `fixtures.py` — composite setup tiers: `setup_org`, `setup_active_group`, `setup_two_active_groups`, application lifecycle helpers, meeting/attendance/collection helpers, `setup_open_meeting_with_loan`, payoff helpers.
- `__init__.py` — barrel export.

`test_suite/` (9 files + `conftest.py`), 72 tests total:
- `test_01_entities_and_access.py` (11) — branch creation defaults, pagination, 404, required-field/duplicate national_id, append-only vote shape, empty savings reverse lookup, RBAC denials, missing-header 400-before-403.
- `test_02_formation_and_temporal.py` (6) — meeting half-open overlap, training 30-min buffer (20/40/0-minute gaps), weekday match, manager-center mismatch.
- `test_03_consensus_voting.py` (5) — resubmit, vote on REJECTED/DRAFT/DISBURSED, double vote.
- `test_04_disbursement_ladder_scoring.py` (8) — standard-vs-rehabilitated ladder (175000c both directions), rehab penalty installment split (4667/200/112008), provisional-vs-final score (720/845/842 readings), disbursement fan-out, immediate consistency.
- `test_05_delinquency_contagion.py` (9) — day-7/8 and day-29/30 boundaries, multi-due sweep to DEFAULTED, cure cycle (9400c = 200+4600+4600), contagion hops 1–3 with deadline isolation, ERR_GROUP_RESTRICTED disbursement block and cure-restores.
- `test_06_meetings_attendance.py` (9) — parallel state dimensions, close-twice, cancel-OPEN, strike cascade to VOTING rejection, PRESENT-reset, streak-1 submit pass vs streak-2 `ERR_ATTENDANCE_INELIGIBLE`.
- `test_07_collections_voids.py` (9) — savings floor (4692/4800 rejected, 4801 accepted), 6000c waterfall (200/4600/5800, outstanding 104800), post-and-void invariant (110600 restoration, savings 200→0, score back to 720), double-void, closed-meeting collections, attendance upsert, dissolve guard.
- `test_08_savings_occ_expansion.py` (14) — savings close/frozen-withdrawal/unfreeze guards, OCC restructure happy path, expansion feasibility (180/181 boundary, center-slot axis), caseload conservation under reassignment, blacklist-beats-already-in-group priority (default path + sub-300 FINAL-score path), state-beats-fiscal at disbursement (VOTING and DRAFT), member-scoped filter composition.
- `test_09_branch_footprint.py` (1) — anchor-chain branch counters round-trip.

**Coverage audit (automated):** all 18 difficulty instances have ≥2 tests; all 36 non-stub corner instances have ≥1 test; the 3 `excluded_because` stubs were not translated and their difficulty cross-references verified to resolve. Every test's docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line copied verbatim from the source YAML. An automated grep pass confirmed every docstring citation contains an 8+-word substring that matches PRD.md verbatim. No `skip`/`xfail` markers, no scaffold references in generated code.

**Skipped instances:** none — every non-stub instance passed the PRD-first two-condition filter (PRD verbatim coverage plus unique derivability). One pin discrepancy was adjudicated rather than emitted: the corner instance `fixture_anchor_chain_not_a_test` self-describes as an anchor holder but carries a real branch round-trip recipe, so it was translated as a genuine test (its asserted counts are PRD-derivable). For `credit_score_provisional_vs_final_same_loan`, the design's `845` pin was used only in the primary test; the second test derives a different exact value (842, no strikes) from the same PRD formula, avoiding reliance on the pin's arithmetic where the PRD alone drives it.

## Step 6: Generate Implementation — 2026-09-30T00:10:00.000Z

(First spawn exited mid-analysis before writing files; respawned with that analysis context. Final report below.)

**Files written** (all under `workspace/implementation/`):
- `start.sh` — executable launcher; guarded `pip install` (no-op when Flask present), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, envelope helpers (`meta`/`response_type`/`data`, `req_` ids, 3-fractional-digit request timestamps), header auth + RBAC table, error handlers, `0.0.0.0:$PORT` (default 10000)
- `core.py` — in-memory store (empty at every boot, no seeding), logical clock (default 2026-09-01T00:00:00Z), all calculations (installment/savings split with rehab rate steps, 4-bucket collection waterfall, standard/rehabilitated ladder ceiling, provisional/final credit scores with 300-850 clamp, delinquency sweep with 8-day/30-day boundaries, reconciliation, expansion feasibility, caseload, savings locks), cascades (contagion, cure, payoff, strike, blacklist), serializers
- `routes_admin.py` + `routes_lending.py` — the 50 endpoints

**Endpoint count:** 50 routes implemented (all from the §4 table: clock, branches, expansion plans, managers, centers + reassign, peer groups + members + dissolve, members, savings withdraw/unfreeze/close, bureau reports, training sessions + complete/cancel, loan applications + submit/votes/disburse/loan, loans + restructures, meetings + open/cancel/attendance/collections/close/reconcile, transactions + void).

**Key spec decisions traced to PRD verbatim:**
- Domain timestamps (`voting_deadline`, `next_due_date`, meeting/training times) render without fractional seconds when microseconds are 0; `created_at`/`updated_at` always carry 3 digits.
- On full payoff, remaining unconsumed scheduled installments count as on-time when the payoff posting time is on/before each due date (PRD §3.4/3.5 literal reading) — verified: immediate payoff of a 24-week loan gives `installments_on_time == 24`.
- Final score implemented exactly as PRD formula: 600 + 10·on_time − 30·missed + 2·attended − 15·strikes, clamped. Verified payoff case yields 840 (24 on-time, 1 attended, 0 strikes). The prior attempt's 845 test constant is not derivable from the PRD formula and was intentionally not special-cased.
- Reconcile mismatch returns 409 `ERR_RECONCILIATION_MISMATCH` while moving settlement to DISPUTED (retryable); SoD rejects closer-as-reconciler; OCC `expected_loan_version` → 412 `ERR_STALE_LOAN_VERSION`.

**Boot verification:** started twice via `bash start.sh` on free ports (19877/19878); exercised the full lifecycle (branch → manager → center → group → 5 members → training → ACTIVE group → draft → submit (deadline `2026-09-08T00:00:00Z`) → 4 unanimous votes → disburse (4567/200/109608) → sweep delinquency at day 8 → group RESTRICTED → default at day 30 → BLACKLISTED → FINAL report) and a second fresh-boot pass for payoff + attendance cascade + reconcile dispute/retry. Both test server PIDs (439867, 448410) were killed exactly; no broad kill patterns used.

## Step 7: Run Tests and Iterate — 2026-09-30T01:05:00.000Z

All 8 parallel rounds pass 72/72. Final summary:

**Iterations run:** 3 eight-round parallel sweeps (48/72 → 64/72 → 72/72 in every round, no flakiness).

**Tests deleted:** None. (Per STEP 1c, the non-derivable half of `test_training_slot_buffer_rejects_20_min_gap_allows_40` was removed rather than the test: the PRD sentence "closed intervals padded by a 30-minute buffer on both sides … whose padded interval intersects it" admits two faithful readings at a 40-minute gap — unpadded-intersect (allows) vs padded-intersect (rejects) — so "allows 40" fails unique derivability; the PRD-pinned "rejects 20" half was kept.)

**Fixes applied to `test_helpers/`:**
- `constants.py` — corrected the cycle-1 reference constants to the PRD formula's true values: `weekly_installment_cents` 4600→4567 (100000×1.096/24 = 4566.66… rounds half-up to 4567; the 4600 pin was a float-slip by the generator), `principal_outstanding` 110600→109608, canonical collection 4801→4768, full payoff 110800→109808, locked 11060→10961.
- `fixtures.py` — `setup_two_active_groups`: spaced G2's training sessions to 11:30 (from 11:00) so they clear the same-manager padded-buffer rule (30 min padding on both sides makes a 60-minute gap collide at the padded boundary).

**Fixes applied to `test_suite/`:**
- `test_02_formation_and_temporal.py` — renamed to `test_training_slot_buffer_rejects_20_min_gap` and removed the "allows 40-minute gap" half (see above).
- `test_04_disbursement_ladder_scoring.py` — added missing `ctx["loan"]` assignments in three tests (KeyError); `_pay_off_clean`/`_pay_off_after_one_cure` now set the logical clock to the meeting day so collections post inside the intended due windows; corrected arithmetic pins (9134→9133, 4600→4567 etc.); disbursed m2's loan before m1's clock move so both loans share the 09-08 first due; `test_credit_score_provisional_vs_final_same_loan` now asserts member `credit_score` 827 (strike re-evaluation at read) and FINAL report 840 (filed at the payoff instant, before the payoff meeting closes) — replacing the underivable 845 pin flagged in the known-context note.
- `test_05_delinquency_contagion.py` — added the missing `validate_success` import; corrected sweep counts (4 consumed dues, `next_due_date` 2026-10-06 — the test had consumed-count arithmetic wrong); cure collection amounts 9400→9334.
- `test_07_collections_voids.py` — `test_savings_floor_200_beats_two_percent_of_installment`: the "under" amount is now 200 (the PRD minimum is savings+1 = 201; the old 4692 was a legal collection); installment/principal split pins corrected (installment capped at 4567, extra cent is prepayment). `test_collection_amount_exactly_at_floor_passes` rewritten as `test_collection_amount_at_savings_minimum_exactly_is_refused` (200 refused, 201 posts). Void-invariant amounts updated to the 4768/109608 basis.
- `test_08_savings_occ_expansion.py` — payoff amounts 110800→109808, collection 4801→4768. `test_priority_safety_blacklist_beats_referential_membership_low_final_score` rewritten: 20 attendance strikes accumulated pre-loan via ABSENT-ABSENT-PRESENT triples (PRD §3.7 pins strikes to the streak-reaching-2 transition, one per unbroken absence run), logical clock tracks the meeting calendar, and the FINAL report is asserted at the clamped floor of exactly 300 — because PRD §3.4's 300–850 hard clamp makes a sub-300 FINAL report unreachable, the screen's `<300` branch can never fire and the test exercises the screen via the BLACKLISTED-status branch.
- `test_09_branch_footprint.py` — payoff amount 110800→109808.

**Fixes applied to `implementation/`:**
- `core.py` — added `recompute_caseloads(branch_id)` (recomputes `active_member_count`, each manager's `current_caseload`, and `total_manager_caseload`; they were never updated before); `sweep` default check now uses oldest consumed-**unpaid** due (`installments_missed − arrears_retired`) per PRD §3.6 and triggers caseload recompute on blacklist; `final_score` attendance window now runs on the logical clock (disbursement instant → terminal transition) per PRD §2.4, fixing the incommensurable wall-clock `created_at` vs logical-clock close comparison.
- `routes_admin.py` — center reassignment, group-member add, and group dissolve now call `recompute_caseloads` (PRD §3.1).
- `routes_lending.py` — `apply_collection`: the current-installment bucket now applies even during partial arrears repayment (PRD §3.5's pinned waterfall has no gating between buckets), and the cure condition is arrears-fully-retired (`missed == arrears_retired`) firing independently of payoff (PRD §3.5 names both chains separately); disburse records the loan's logical-clock disbursement instant for the score window, and files the PROVISIONAL report with the pinned at-disbursement score (720 at zero activity) rather than a post-cascade recompute.

## Step 8: Finalize PRD — 2026-09-30T01:30:00.000Z

`PRD_FINALIZED.md` written with a minimal 3-line in-place patch.

## Line counts
- `PRD.md`: 381 lines; `PRD_FINALIZED.md`: 381 lines; 0% line-count delta (3 lines revised in place, no insertions/deletions of lines).

## Changes (one bullet per edit)
- **§3.2 (Formation training, line 153)** — revise — pinned the training-slot collision semantics: both the new and existing sessions are padded 30 min on each side, padded intervals are closed so a shared boundary instant collides (a raw 60-minute gap collides at the padded boundary; the 40-minute gap is rejected under padded-intersect) — `implementation/routes_admin.py:521-535` (`training_overlaps`: `new_lo = start−pad`, `new_hi = end+pad`, collide iff `new_lo <= ex_hi and ex_lo <= new_hi`).
- **§3.4 (readable credit_score, line 177)** — revise — pinned that with no open loan the readable `credit_score` re-evaluates the final-score formula at read time (current `attendance_strikes`, newly CLOSED in-window meetings) rather than replaying the filed FINAL report's frozen value — `implementation/core.py:486-496` (`compute_credit_score` → live `final_score`).
- **§3.4 (final-score window and filing, line 179)** — revise — replaced the wall-clock `created_at` window start with the loan's disbursement instant on the logical clock (terminal transition also on the logical clock), and pinned that a filed FINAL report is evaluated against state at the filing instant, so the payoff meeting — still OPEN when the payoff collection files the report — never counts toward the report but does count toward read-time re-evaluation once its CLOSED transition lands inside the inclusive window — `implementation/core.py:463-483` (`final_score`: `disbursed_at_dt`→`terminal_at_dt`, `status == "CLOSED"` filter), `core.py:588-605` (`loan_payoff` files before meeting close), `routes_lending.py:195` (`disbursed_at_dt = logical_now()`), `routes_lending.py:530` (`closed_at_dt = logical_now()`).

## Per-edit pre-edit search log
1. **Training-slot edit** — (a) subject: training-session overlap semantics. (b) enumerated: `routes_admin.py:521-535` (`training_overlaps`), call site `routes_admin.py:559`, `core.py:41` (`TRAINING_BUFFER_MINUTES`), complete/cancel at `routes_admin.py:590-619` (no re-check), and the parallel center-meeting half-open rule at `routes_lending.py:315-320` (already pinned half-open in PRD — confirmed the new wording is scoped to sessions only and cannot be read as redefining meeting overlap). (c) wording scoped explicitly to training sessions ("Sessions occupy their facilitator's calendar…"), preserving the PRD's deliberate contrast with the meeting rule.
2. **Readable-score edit** — (a) subject: readable `credit_score` with no open loan. (b) enumerated: `core.py:486-496` (`compute_credit_score`), `core.py:463-483` (`final_score` live re-evaluation), `core.py:447-460` (provisional branch), `core.py:748-759` (`ser_member` computes at read on every member read — GET `/members`, `/members/{id}`, group-member lists). (c) wording says "re-evaluated at read time through the final-score formula" without pinning the impl's internal tie-break ordering, keeping it consistent across all member-read paths.
3. **Final-window/filing edit** — (a) subject: FINAL attendance window endpoints and filing-time evaluation. (b) enumerated: `core.py:463-483`, `core.py:588-605` (payoff path), `core.py:661-675` (default path in sweep — also files at the terminal instant), `routes_lending.py:182-215` (disburse records logical `disbursed_at_dt` and files PROVISIONAL before any cascade), `routes_lending.py:521-557` (close stamps logical `closed_at_dt`), cross-checked PRD §2.4 (logical clock governs every time-dependent rule). (c) replaced only "`created_at`" with "disbursement instant on the logical clock" and added a filing-instant sentence phrased behaviorally ("evaluated against the state of the world at the filing instant") rather than mechanically, so it covers both the payoff path and the default path without over-specifying internal fields.

## Step-7 items judged to require no PRD edit (already PRD-determined or pure fixture bugs)
- `constants.py` arithmetic corrections (4567/109608/4768/109808/10961): pinned by §3.4's half-up formula; the 4600 pin was a generator float-slip.
- `fixtures.py` 11:30 spacing and test_04/test_05 fixture fixes (`ctx["loan"]` assignments, clock placement, sweep-count arithmetic, cure amounts, disburse-ordering): fixture bugs, not PRD silences.
- Caseload recomputation (`recompute_caseloads`, admin call sites): already pinned by §3.1/§3.2/§3.6.
- Sweep default on oldest consumed-**unpaid** due: already pinned by §3.6 ("oldest consumed-but-unpaid due").
- Waterfall bucket independence and cure-fires-independently-of-payoff: already pinned by §3.5's ungated waterfall and its separate naming of the two chains.
- Savings-minimum floor (200 refused / 201 posts): already pinned by §3.5 ("less than `savings_required_cents` plus 1").
- Strike-per-absence-run semantics and the unreachable sub-300 FINAL screen branch: already pinned by §3.7 ("streak reaches exactly 2") and §3.4's 300–850 clamp.
- PROVISIONAL filed with the at-disbursement score (720 at zero activity): already pinned by §3.4's formula and worked example; disburse triggers no score-relevant cascade before filing, so filing-vs-recompute is unobservable.

## Step 9: Complete PRD — 2026-09-30T01:50:00.000Z

**File**: `workspace/PRD_COMPLETED.md`

- **Source**: PRD_FINALIZED.md — 381 lines, 57,014 chars
- **Result**: PRD_COMPLETED.md — 381 lines, 62,405 chars (**+5,391 chars**, line count unchanged; all edits in-paragraph, no new sections)
- **Counts**: 17 ambiguity-pins, 5 mismatch-revisions (22 changed passages total)

### Changes

**Ambiguity pins (PRD silent, impl pins the behavior):**
- §2.2 — insert — ambiguity — `response_type` discriminator pinned as structural ("array" iff `data` is an array, even empty) — app.py:36
- §2.3 — insert — ambiguity — invalid `limit`/`offset` query params → `ERR_INVALID_REQUEST`; sort tie-break by `id` ascending — core.py:294–319, routes_admin.py:16
- §2.5 — insert — ambiguity — `created_at`/`updated_at` are wall-clock, never logical clock — core.py:202,208
- §2.5 — insert — ambiguity — caller-supplied timestamps echoed at caller's precision (no fractional seconds when none given) — core.py:143–148
- §3.1 — insert — ambiguity — hiring a manager requires existing `branch_id` (`ERR_BRANCH_NOT_FOUND`) — routes_admin.py:154
- §3.1 — insert — ambiguity — cross-branch center create/reassign → `ERR_INVALID_REQUEST` — routes_admin.py:213–214, 250–251
- §3.2 — insert — ambiguity — add-member intra-step check order (NOT_RECRUITED before ALREADY_IN_GROUP) — routes_admin.py:344–347
- §3.2 — insert — ambiguity — membership is irrevocable: no removal endpoint; `DISSOLVED` members keep `peer_group_id` and can never re-join any group — routes_admin.py:346, 371
- §3.2 — insert — ambiguity — `completed_training_sessions` may exceed 2; graduation fires only while group is `TRAINING` — routes_admin.py:599–608
- §3.3 — insert — ambiguity — unanimous-APPROVE under a non-ACTIVE group leaves the application `VOTING`; REJECT kills unconditionally — routes_lending.py:131–144
- §3.4 — insert — ambiguity — provisional-score remaining-installments term floored at zero; lifetime `attendance_strikes` feed every score; multi-terminated-loan selection is most-recent-by-terminal-time, ties by creation — core.py:454–455, 479–482, 493–496
- §3.4/§3.9 — insert — ambiguity — savings percentage uses the loan's snapshot `cycle_level` (matters at restructure) — routes_lending.py:265–266
- §3.5 — insert — ambiguity — meeting cancel carries no center-ownership check (unlike open/close); attendance re-record overwrites the existing row — routes_lending.py:366–373, 394–401
- §3.5 — insert — ambiguity — prepayment bucket cap only binds on negative remainder (inert in practice); installments covered while posting past `next_due_date` count as neither on-time nor missed — routes_lending.py:431–432, 438–440
- §3.5 — insert — ambiguity — whole-installment coverage is measured cumulatively across a loan's history (two partials can complete one unit) — routes_lending.py:435–436
- §3.7 — insert — ambiguity — reconcile ordering: `ERR_ALREADY_RECONCILED` outranks `ERR_SEGREGATION_OF_DUTIES` — routes_lending.py:568–573
- §3.8 — insert — ambiguity — zero `amount_cents` withdrawal succeeds when `withdrawable_cents` is zero — routes_admin.py:473–475
- §3.9 — insert — ambiguity — "installments already applied" means cumulative whole units; `next_due_date`/counters/outstanding unchanged by restructure — routes_lending.py:253–256, 267–269

**Mismatch revisions (PRD described behavior differing from impl):**
- §2.8 step 7 — revise — mismatch — removed `ERR_MEMBER_ALREADY_IN_GROUP` from the referential-coherence tier (impl raises it in the structural tier, after blacklist per step 6) — routes_admin.py:342–347
- §3.2 — revise — mismatch — session scheduling: facilitator-mismatch check fires *before* the time-range check (PRD listed time-range first) — routes_admin.py:554–558
- §3.3 — revise — mismatch — drafting copies the group from the URL path (PRD: from the member); no group-state or member-status gate at draft — routes_lending.py:29–47
- §3.3 — revise — mismatch — submission gate order: blacklist screen precedes applicant-eligibility (PRD had it listed last) — routes_lending.py:74–82
- §3.4 — revise — mismatch — rehabilitated ceiling uses the most recently *created* `PAID_OFF` loan (PRD: "most recent") — core.py:430–431
