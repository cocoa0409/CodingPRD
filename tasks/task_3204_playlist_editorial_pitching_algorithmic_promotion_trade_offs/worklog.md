# Worklog — task_3204_playlist_editorial_pitching_algorithmic_promotion_trade_offs

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3204_playlist_editorial_pitching_algorithmic_promotion_trade_offs/` was pre-allocated by the user (workspace/ inside); verified it exists and ensured `workspace/` is present. No new index computed.

## Step 2: Generate scaffold — 2026-09-30T10:33:00.000Z

All checks pass. The scaffold is complete and lint-clean.

## Summary

Generated a much-harder-than-expert scaffold for the Spotify-style playlist editorial pitching & algorithmic promotion trade-offs scenario at `/home/ubuntu/github/CodingPRD/tasks/task_3204_playlist_editorial_pitching_algorithmic_promotion_trade_offs/`.

**Files written:**
- `SCAFFOLD.yaml` — §1.0–§1.7 (no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**Counts:**
- Entities: 13 (Artist, Release, Track, PitchSubmission, EditorialPlaylist, PlaylistPlacement, PromotionEnrollment, StreamEvent, FraudCase, RoyaltyPeriod, RoyaltyStatement, ProfileModule, PreSave)
- State machines: 9 (two cyclic: pitch revision loop with MAX_REVISION_ROUNDS cap; placement rotate-out/reinstate cadence cycle; plus parallel-ish fraud/promotion/release/period machines)
- Endpoints: 60 (incl. `/_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z startup default)
- Errors: 20; Validations: 20 (ordered priorities 1–20); Calculations: 6; Roles: 5 (RightsHolder entity-backed by Artist; others opaque)
- Difficulty instances (§1.8): 18 (2 per each of the 9 rules)
- Corner instances (§1.9): 28 across all 9 claim-guide sections

**Harder-than-expert levers used:** ledger-reconciliation archetype with a GROSS vs EFFECTIVE royalty-share dual variant (promotion discount factor reshapes pool shares); combinatorial boost formula with follower-tier branches + inclusive cap + negative floor + COLD_START halving; pinned per-artist-floor-then-remainder-waterfall rounding order with `created_at` tie-break; inclusive fraud-confirm boundary (0.8400 vs exactly 0.8500); two OCC rules (`expected_release_version` on change-date, `expected_period_version` on close, both 412); depth-3 cascades (fraud CONFIRM → taint → share redistribution + clawback; third strike → artist TERMINATED → release/track/module cascade); half-open enrollment-window overlap vs discrete-slot occupation with ROTATED_OUT grace (two distinct interval semantics); priority-conflict pairs (state vs business_temporal, business_safety vs business_fiscal).

All §1.8/§1.9 numeric asserts were pre-computed with Python (e.g. 55560/22220/22220 EFFECTIVE vs 60000/20000/20000 GROSS; waterfall remainder cent 38889/38888; boost scores 28/21/0/86/90). `scaffold_lint.py` verdict: **clean lint** — all 448 calls conform to §1.5, all FKs reverse-reachable.

## Step 3: Copy shared files — 2026-09-30T10:34:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3204_playlist_editorial_pitching_algorithmic_promotion_trade_offs/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T10:44:00.000Z

All checks pass. PRD generation complete.

**Summary**

- **Output written**: `/home/ubuntu/github/CodingPRD/tasks/task_3204_playlist_editorial_pitching_algorithmic_promotion_trade_offs/workspace/PRD.md` — 293 lines.
- **Sections covered**: §1 Introduction (3 paragraphs); §2 Global Specifications with ten domain-derived subsections (2.1 RBAC with per-role identity semantics, 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Logical Clock & time-driven transitions, 2.5 Common Resource Properties incl. the `common_fields: false` exceptions for StreamEvent/PreSave, 2.6 Validation Order with explicit priority narrative, 2.7 OCC for `expected_release_version`/`expected_period_version` with `ERR_STALE_VERSION`/412, 2.8 Precision & Money, 2.9 Cascading Consistency, 2.10 Nested Resource Retrieval); §3 Business Logic in eight subsections (artist registry/strikes, releases-tracks-territories-presaves, pitching cycle, playlist slots & rotation, promotion enrollment & disclosure token, streams/royalty waterfall with GROSS vs EFFECTIVE variants and pinned floor-then-remainder ordering, fraud scoring/adjudication/clawback cascade, boost scoring with tier multipliers & COLD_START halving plus profile modules); §4 endpoint table (61 endpoints, 4 columns); §5 error catalogue (20 errors, 2 columns).
- **Hard contract results**:
  - Contract 1 Field-Name Coverage: 76/76 required identifiers present in backticks, 0 missing — PASS.
  - Contract 2 Rule Coverage: all state machine transitions, calculations (royalty waterfall, boost score, fraud confidence, clawback, slot selector, presave conversion), validation priorities, OCC rules, and cascade side-effects expressed in prose; every error ID appears in §2/§3 narrative; all enum/state values present (a missing `CONFIRMED` literal was caught and fixed) — PASS.
  - Contract 3 §3 Path Purity: 428 backtick tokens scanned in §3, 0 path/HTTP-method violations — PASS.
- One prose bug was found and fixed during verification: the `CONFIRMED` verdict enum value was initially absent from narrative; it is now stated in §3.7's adjudication paragraph.
- The two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

## Step 5: Generate unit tests — 2026-09-30T10:58:00.000Z

Done. Full generation completed for task_3204_playlist_editorial_pitching_algorithmic_promotion_trade_offs.

## Summary

**Test counts**
- Total: **65 tests** across 7 files (`test_01` catalog/access, `test_02` pitching, `test_03` placement/rotation/presaves, `test_04` boost scoring, `test_05` royalty ledger, `test_06` fraud pipeline, `test_07` promotions/cascades/change-date)
- Queue A (Difficulty): **36 tests** covering all **18/18 instances** at ≥2 tests each
- Queue B (Corner): **29 tests** covering all **28/28 non-stub instances** (zero `excluded_because:` stubs exist in this task's corner index)

**Instances skipped: none.** Every instance passed the PRD-first two-condition filter — the PRD states each asserted rule verbatim (validation priority via §2.6 prose, OCC via §2.7, strike limits 2/3 and lead days 7 via §3 prose, boost cap 90 / tiers / COLD_START via §3.8, waterfall order via §3.6, clawback rate 0.40 and thresholds 0.7000/0.8500 via §3.7).

**Helper files written** under `/home/ubuntu/github/CodingPRD/tasks/task_3204_playlist_editorial_pitching_algorithmic_promotion_trade_offs/test_helpers/`: `__init__.py`, `types.py` (status enums + TypedDicts; StreamEvent/PreSave correctly omit `updated_at`/`version` per common_fields: false), `api_client.py` (all 43 endpoints incl. `_clock/set_current_utc`), `api_errors.py` (20 error IDs registered with `set_error_http_status_map`), `assertions.py`, `constants.py`, `factories.py`, `test_users.py` (RightsHolder is entity-backed → `make_rights_holder_headers(artist_id)` used for every ownership-gated call), `fixtures.py` (5 tiers: clock/entity basics, pitch pipeline, accepted/active placement composites, fraud confirm, period close/statement lookup). Plus `test_suite/conftest.py`.

**Stage 2 self-check results**
- All 65 tests collect under pytest without errors
- Tag audit: every test has exactly one `Design:` tag; all tags resolve to real instances with correct rule_id/section; difficulty ≥2 and corner ≥1 coverage complete
- Verbatim-grep pass: a distinctive ≥8-word window from every test's PRD citation matches PRD.md literally
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code

## Step 6: Generate implementation — 2026-09-30T11:26:00.000Z

All verified. Server processes stopped; port free.

## Summary

**Task**: task_3204_playlist_editorial_pitching_algorithmic_promotion_trade_offs — full Python + Flask implementation written to `/home/ubuntu/github/CodingPRD/tasks/task_3204_playlist_editorial_pitching_algorithmic_promotion_trade_offs/workspace/implementation/`.

**Files written**:
- `start.sh` — foreground launcher: `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), guarded `pip install` (no-op once Flask importable, safe for per-test reboots)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app factory, ApiError/404/405/generic exception handlers returning the scaffold envelope
- `util.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; error body `error_id`/`message`; pagination `limit`/`offset`/`total_count`/`has_more` with defaults 10/0, min 1, max 100), auth (X-User-ID/X-User-Role, 5 declared roles), field/datetime validators
- `store.py` — empty in-memory store; logical clock pinned at `2026-09-01T00:00:00Z` until set (no seeding)
- `services.py` — constants, cascades (artist suspend/terminate, track removal, playlist retire, release go-live + presave conversion), calculations (royalty waterfall with GROSS/EFFECTIVE variants, per-stream 2dp half-up weights, integer bps shares, floor-then-remainder cent distribution; boost score with tier multiplier, cap 90, COLD_START halving; fraud confidence 4dp; clawback 0.40 cents/stream), clock-advance transitions in creation order
- `routes_core.py`, `routes_editorial.py`, `routes_program.py`, `routes_royalty.py`, `routes_misc.py` — route handlers

**Endpoints**: all 60 from the scaffold endpoint table implemented (artists 5, releases 5, tracks 4, playlists 4, pitches 8, placements 5, promotions 6, streams 3, fraud-cases 4, royalty-periods 5, royalty-statements 2, profile-modules 4, presaves 4, clock 1).

**Key behaviors verified by live smoke tests** (~90 checks passed): validation priority order (401 → 403 → 404 → 400 → 409-state → business), PRD-ordered pitch checks (window → pitchable → fit → fraud hold), OCC 412 on change-date and period-close, full fraud CONFIRM cascade (taint, clawback into CLOSED statement or swept into next generated statement, enrollment termination, placement eviction, strike → suspend at 2 / terminate at 3), GROSS vs EFFECTIVE share math incl. remainder waterfall, auto go-live with presave territory conversion, auto rotation at cadence end, disclosure-token 403, slot selector + ERR_NO_FREE_SLOT, and clean per-boot state reset with pinned default clock — matching the `--isolation per-test-server` contract.

One deliberate judgment call: where PRD narrative and scaffold priority table disagreed on business-rule order (pitch submit; promotion enroll: overlap before fraud hold), the PRD prose was implemented, per the skill's fidelity rule.

## Step 7: Run tests and iterate — 2026-09-30T11:54:00.000Z

All 8 rounds pass 63/63. Clean exit.

## Summary

**Iterations run:** 4 sweeps of 8 parallel rounds each (32 runs total). Round 1 baseline: 16 deterministic failures; final sweep: 63/63 passing in all 8 rounds with zero flakiness.

**Fixes applied to `workspace/implementation/`:**
- `services.py` `confirm_case()` — `clawback_cents` was double-quantized and cast to `int`, truncating 0.40 → 0; changed to `float(total.quantize(0.01, HALF_UP))` to match PRD §3.7 ("multiplied by the per-stream rate of 0.40 cents, and the products are summed and rounded half-up to 2 decimal places"). This single bug was behind 5 failures (clawback rate, tainted-stream exclusion, pool conservation ×2, confirm-taints).

**Fixes applied to `test_suite/`:**
- `test_01` `test_artist_create_returns_system_fields_and_active_status` — asserted `created_at == "2026-09-01T00:00:00Z"`, conflating the §2.4 clock literal with the §2.5 rule that `created_at` carries three fractional digits; corrected to `"2026-09-01T00:00:00.000Z"` (implementation was correct).
- `test_03` — 4 tests had setups violating PRD's pinned 7-day pitch lead (release_date only 2–4 days out at pitch time) or accept/rotation preconditions: `test_playlist_retire_evicts_all_non_terminal_placements` and `test_clock_advance_fires_release_and_rotation_transitions` moved release dates to 09-09; `test_second_accept_succeeds_after_first_rotates_out` rewritten as `test_second_accept_after_rotation_blocked_by_live_release` (rotation frees the slot per §3.4, but accept then correctly fails because the release went LIVE — §3.3 requires SCHEDULED).
- `test_04` `test_boost_score_cap_is_inclusive_at_ninety` — release date 09-05 → 09-09 (pitch lead).
- `test_05` `test_gross_close_freezes_variant_and_computes_shares` — `effective_streams` expected 2.50 via a scaffold-only "only ALGORITHMIC-source streams get discounted" rule; PRD §3.6's weight rule has no source condition, so all 3 in-window streams are discounted → 1.50.
- `test_06` — `test_confirm_below_threshold_rejected_and_state_unchanged` had arithmetically wrong confidence (0.84 vs PRD formula's 0.79 for signals 1.0/0.4/1.0); `test_confirm_then_close_shifts_statement_shares_and_lands_clawback` share/payout expectations computed under the same scaffold-only taint rule (expected B 5000 bps; PRD-pinned input set yields A 3333/25923, B 6667/51854, net 51853.60).
- `test_07` `test_termination_removes_release_track_and_disables_module` — split per §1c: PRD §3.1's termination cascade names tracks/placements/enrollments/modules but never releases, and §3.2 restricts fraud-cascade release removal to LIVE releases; dropped the SCHEDULED-release→REMOVED assertion (renamed test, asserts release stays SCHEDULED), kept track-REMOVED and module-DISABLED.

**Tests deleted (2):**
- `test_rotate_after_cadence_then_reinstate_restarts_window` (test_03) — unique-derivability collapse: PRD §2.4+§3.4 pin that the clock reaching `scheduled_rotation_on` auto-rotates an ACTIVE placement, so a manual rotate at/after cadence end always lands on an already-ROTATED_OUT placement; no PRD-faithful implementation can serve the test's setup.
- `test_second_accept_blocked_while_first_placement_active` (test_03) — same class: triggering `ERR_NO_FREE_SLOT` on accept requires an ACTIVE slot occupant (requires release LIVE per §3.4) while the accept itself requires the second pitch's release still SCHEDULED (§3.3); one shared logical clock makes both unreachable simultaneously, and PRD gives no rule that would order them otherwise.

No checks were weakened to HTTP-status-only, no skips/xfails added, and no PRD-required implementation checks were removed.

## Step 8: Finalize PRD — 2026-09-30T12:00:00.000Z

The diff is exactly three lines changed, 292 → 292 lines (0% delta). All edits are minimal inline revisions, no new sections. Done.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3204_playlist_editorial_pitching_algorithmic_promotion_trade_offs/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 292 lines → PRD_FINALIZED.md 292 lines (0.0% delta; 3 lines modified in place).

### Changes (one bullet each)

- **§3.1 (Artist termination cascade)** — revise — added "every `LIVE` release of the artist becomes `REMOVED` (a `SCHEDULED` release of the artist is left untouched by this cascade and remains `SCHEDULED`)" to the termination cascade list — `implementation/services.py:213-216` (terminate_artist flips only `LIVE` releases; SCHEDULED untouched).
- **§3.4 (Rotation cycle)** — revise — after the `ERR_ROTATION_TOO_EARLY` sentence, pinned that because auto-rotation fires when the clock reaches `scheduled_rotation_on` (§2.4), a manual rotate at/after cadence end finds the placement already `ROTATED_OUT` and is rejected with `ERR_INVALID_STATE` — `implementation/services.py:395-400` (advance_clock auto-rotation) + `implementation/routes_editorial.py:392-404` (rotate_placement: ERR_INVALID_STATE unless ACTIVE/REINSTATED; ERR_ROTATION_TOO_EARLY only when clock < scheduled instant).
- **§3.7 (Confirm cascade step 2)** — revise — pinned that the case's `clawback_cents` amount is fractional, rounded half-up to 2 decimal places, as an explicit exception to §2.8's integer-cents rule — `implementation/services.py:250-254` (float after quantize(0.01)); consistent with `services.py:262,263,324,334,335` and `routes_program.py:274`.

### Step 7 items judged not to need PRD edits

- **test_01 created_at literal** — pure fixture bug; §2.4/§2.5 already pin three-fractional-digit `created_at`; impl matched PRD.
- **test_03/test_04 fixture setups (release dates, accept-after-rotation-blocked rewrite)** — fixture bugs; §3.3's 7-day pitch lead and §3.3 accept precondition (release SCHEDULED) were already pinned and the impl matches.
- **test_05 `effective_streams` 2.50→1.50** — the scaffold-only "only ALGORITHMIC-source streams get discounted" rule has no basis in PRD §3.6, whose weight rule already has no source condition; impl matches PRD as written. No silence.
- **test_06 confidence 0.84→0.79 and share/payout numbers** — fixture arithmetic errors against already-pinned formulas (§3.7 confidence weights, §3.6 waterfall). PRD already determines these.
- **Deleted `test_second_accept_blocked_while_first_placement_active`** — unique-derivability collapse of test setup, not a PRD silence: §3.3 (accept requires release SCHEDULED) and §3.4 (ACTIVE occupant requires release LIVE) are each correctly pinned; the impl behavior at both sites matches the PRD.

### Per-edit pre-edit search log

**Edit 1 (clawback fractional cents):**
- (a) Subject: type/representation of the fraud-case `clawback_cents` amount.
- (b) Paths enumerated: `services.py:250-254` (computation — float, quantize 0.01 HALF_UP), `routes_program.py:274` (init to 0), `services.py:262-264` (accrual onto CLOSED statement, net recompute), `services.py:319-335` (pending-clawback sweep into newly generated statements incl. `clawback_cents`/`net_payout_cents` fields). Grep for `clawback` across `services.py`/`routes_program.py` confirmed no other sites.
- (c) Wording scoped to "the resulting `clawback_cents` amount" of the confirm computation and framed as an exception to §2.8 rather than amending §2.8's pool/payout list, so statement/gross/net fields are not claimed fractional universally (statement `clawback_cents` inherits fractionality only through accrual, which the edited sentence's context covers).

**Edit 2 (manual rotate after cadence end):**
- (a) Subject: state of a placement when a manual rotate is requested at/after `scheduled_rotation_on`.
- (b) Paths enumerated: `routes_editorial.py:392-404` (`rotate_placement` — ERR_INVALID_STATE for non-ACTIVE/REINSTATED; ERR_ROTATION_TOO_EARLY only when `clock < _srot_dt`; sets `_deactivated_on`), `services.py:395-400` (`advance_clock` auto-rotation at `_srot_dt <= clock`), `routes_editorial.py:407-420` (`reinstate_placement` — requires ROTATED_OUT; unaffected), `services.py:142-158` (eviction paths — unaffected; wording makes no claim about EVICTED).
- (c) First draft contained a convoluted tail sentence ("in practice ... effectively never succeeds"); revised to the tighter, purely behavioral claim (auto-rotation fires at the instant; manual rotate then yields ERR_INVALID_STATE) to avoid implying anything about clock-advance internals beyond what §2.4 already pins.

**Edit 3 (termination cascade removes LIVE releases only):**
- (a) Subject: which releases the artist-termination cascade removes.
- (b) Paths enumerated: `services.py:195-216` (`terminate_artist` — LIVE-only release flip), `routes_core.py:221-253` (`remove_release` — RightsHolder requires SCHEDULED; FraudAnalyst may remove any non-REMOVED release, including SCHEDULED), `services.py:185-192` (`suspend_artist` — no release effect), `routes_core.py:90-98` (suspend endpoint), §3.2 removal paragraph (already covers FraudAnalyst-invoked removal separately).
- (c) Wording added as one more item inside the termination cascade list ("every `LIVE` release ... becomes `REMOVED`") with a parenthetical scoped to "this cascade", so it does not narrow the separately specified FraudAnalyst `/remove` endpoint (which may also remove SCHEDULED releases) and does not contradict §3.2's statement that a LIVE release is removed only via the fraud path.

## Step 9: Complete PRD — 2026-09-30T12:16:00.000Z

All pins are present. Final diff stat: PRD_COMPLETED.md has 292 lines and 51,796 chars vs the source PRD_FINALIZED.md at 292 lines / 47,225 chars (+4,571 chars).

**Source**: `PRD_FINALIZED.md` → `PRD_COMPLETED.md` (both in `/home/ubuntu/github/CodingPRD/tasks/task_3204_playlist_editorial_pitching_algorithmic_promotion_trade_offs/workspace/`); 292 lines each; char delta +4,571 (47,225 → 51,796).

**Counts**: 17 change sites — 1 mismatch-revision (§2.8), 16 ambiguity-pins.

**Change bullets** (one per Edit):

- §2.1 Roles — insert — ambiguity — pinned that `RightsHolder` ownership is enforced on reads as well as writes, with list endpoints scoping to owned resources (and `artist_id` filter still usable within scope) — implementation/routes_core.py:70-71,179-180; routes_editorial.py:164-165,177-178,315-316,329-330; routes_program.py:92-93,104-105; routes_royalty.py:115-116,127-128; routes_misc.py:69-70,83-84,151-152,163-164.
- §2.5 Common Properties — insert — ambiguity — pinned that `created_at`/`updated_at` are stamped from the logical clock, and `version` starts at 1 — implementation/services.py:50-56,59-63.
- §2.8 Precision, Rounding, and Money — revise — mismatch — `clawback_cents`/`net_payout_cents` are fractional cents once a clawback lands (not whole cents as the PRD claimed) — implementation/services.py:253-254,262-263,334-335.
- §3.1 Artist Registry (suspension) — insert — ambiguity — suspend of non-ACTIVE is `ERR_INVALID_STATE`; suspension cascade terminates only `ENROLLED` enrollments and evicts only `ACTIVE`/`REINSTATED` placements; reinstate of non-SUSPENDED is `ERR_INVALID_STATE` — implementation/routes_core.py:95-96,106-109; services.py:185-192.
- §3.1 Artist Registry (termination) — insert — ambiguity — artist termination cascade evicts `SCHEDULED`/`ACTIVE`/`REINSTATED`/`ROTATED_OUT` placements — implementation/services.py:207.
- §3.2 Releases (change-date) — insert — ambiguity — all temporal/count guards combine into a single `ERR_DATE_CHANGE_WINDOW`; stale-version check runs after they pass — implementation/routes_core.py:200-206.
- §3.2 Releases (change-date sweep) — insert — ambiguity — release `version` advances once for the date change and once per withdrawn pitch — implementation/routes_core.py:210; services.py:132-139.
- §3.2 Releases (removal) — insert — ambiguity — RH removal of non-SCHEDULED is `ERR_INVALID_STATE`; SCHEDULED removal also evicts placements/terminates enrollments via track removal; LIVE removal evicts `ROTATED_OUT` rows too; FraudAnalyst may remove any non-`REMOVED` release — implementation/routes_core.py:226-253.
- §3.2 Pre-saves — insert — ambiguity — `presave_count` defined as count of `SAVED`+`CONVERTED`; recomputation counts as a release mutation; malformed territory also yields `ERR_TERRITORY_RESTRICTED`; only `SAVED` pre-save cancellable — implementation/routes_misc.py:125-133,179-181; services.py:122-129.
- §3.3 Pitch submit — insert — ambiguity — body FK existence checked `track_id` then `target_playlist_id` — implementation/routes_editorial.py:113-119.
- §3.3 Pitch claim — insert — ambiguity — `submitted_days_before_release` via floor division on whole days; only `PITCHED` claimable, state check precedes team check — implementation/routes_editorial.py:145,195-199.
- §3.5 Enroll — insert — ambiguity — non-terminal for overlap = `ENROLLED`/`SUSPENDED`; `disclosure_token` format `disc_<hex>` — implementation/routes_program.py:66,80.
- §3.5 Resume — insert — ambiguity — pinned resume check order (state → window-ended → overlap → artist-active → fraud-hold) with both state errors as `ERR_INVALID_STATE` — implementation/routes_program.py:139-153.
- §3.6 Statements — insert — ambiguity — `effective_streams` reported as a decimal number — implementation/services.py:331.
- §3.6 Statements — insert — ambiguity — remainder waterfall cycles through the ordering; residual `created_at` tie broken by artist registration order — implementation/services.py:309-317.
- §3.7 Clawback — insert — ambiguity — earliest-generated CLOSED statement absorbs the clawback and its `version` advances; swept clawbacks seed the next statement's `clawback_cents` — implementation/services.py:255-265,318-335.
- §3.7 Confirm cascade — insert — ambiguity — confirm leaves `SCHEDULED` placements untouched; a strike count reaching 3 ends `TERMINATED` directly — implementation/services.py:268,272-275.
- §3.8 Boost variant — insert — ambiguity — "held a placement during the window" = activated before window end and not deactivated at/before window start — implementation/services.py:354-364.
- §3.8 Profile modules — insert — ambiguity — `CANVAS.track_id` may reference any existing track; `MERCH` stored with no `track_id` — implementation/routes_misc.py:45-49,56.
- §2.4 Logical clock — insert — ambiguity — clock-set response echoes `current_utc` — implementation/routes_misc.py:197-199.
