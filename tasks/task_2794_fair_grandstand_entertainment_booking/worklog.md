# Worklog — task_2794_fair_grandstand_entertainment_booking

## Step 1: Create Task Directory — 2026-09-04T22:27:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2794_fair_grandstand_entertainment_booking` and its `workspace/` subdirectory. Index 2794 was pre-assigned by the invoking pipeline (no scan of ./tasks/ performed, per instructions, to avoid collision with the ~32 concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-05T00:38:00.000Z

All three scaffold artifacts are complete and lint-clean.

### Verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2794_fair_grandstand_entertainment_booking/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2794_fair_grandstand_entertainment_booking/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2794_fair_grandstand_entertainment_booking/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     15
  §1.8 instances scanned:     22
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  1680

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Files

- `SCAFFOLD.yaml` — 2895 lines (13 top-level keys; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2311 lines (single key `scaffold_difficulty_design`, 22 instances)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 6819 lines (single key `scaffold_corner_design`, 86 instances: 67 full recipes + 19 `excluded_because` stubs)

§1.9 section breakdown: entities 12, state_machines 18, calculations 13, validations 9, endpoints 5, errors 18, rbac 4, cross_cutting_complexity_layers 5, consistency_model 2.

### Work completed

Wrote the last four §1.9 sections: `errors` (11 full `error_triggerable` recipes covering all 48 catalogued codes not already reached elsewhere — auth/role/identity layering, a 12-probe distinct-404 sweep, state codes, fair-run and replacement-date rules, the 31-before-44 announce ordering, settlement timing/uniqueness/negative payout, sponsorship exclusivity + stage naming, refund-vs-net-units — plus 7 stubs citing §1.8), `rbac` (exclusive_operations happy path across all seven roles, cross-role denial matrix, the three named holes in the shared read surface proved by 403-vs-404 contrast, and segregation of duties incl. the reject-is-not-duties-constrained nuance), `cross_cutting_complexity_layers` (ShowBooking OCC across all three tokened endpoints, Offer OCC on revise, all-or-nothing cancellation cascade, derived-field reconciliation, plus a `dual_variant_calculation` stub), and `consistency_model` (accept cascade and sponsorship-revenue confirm/cancel visible in-request).

Defects found and fixed while grounding against SCAFFOLD.yaml: `rejection_reason_code: "FIGURES_DISPUTED"` was not in the declared enum (→ `GROSS_MISMATCH`); an activation cancelled from PROPOSED was asserted to book a make-good of 1000000 (correct: `make_good_credit_cents == 0`, `net_fee_cents == 1100000` after the 0.10 high-demand premium); an assert said `round_count == 2` after send+counter+revise (send itself stamps round 1, so 3); six pre-existing stub instances were missing `distinguishing_aspect` and now have one. All money literals in the new sections were computed before writing (e.g. the underwater settlement's `total_artist_settlement_cents == -1525000`, `gross_potential_cents` running sums 11866075 / 34203325 / 37973325, activation net fees 1100000 / 880000 / 750000 / 525000, refund reserve overrun 3347500 vs a 1000000 reserve).

Orchestrator verification: all three files present; `grep -rn "harder than expert"` over the task dir returns nothing, so the difficulty directive did not leak into any artifact.

## Step 3: Copy Shared Files — 2026-09-05T00:39:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T00:58:00.000Z

PRD generation is complete. Final artifact: `workspace/PRD.md` — **481 lines** (108,521 bytes; long prose paragraphs), last heading exactly `## 5. Error Code Catalogue`, ending on the complete error table (final row `| ERR_SETTLEMENT_NEGATIVE_PAYOUT | 422 |`), no audit footer.

Structure delivered: §1 Introduction; §2 with ten subsections (2.1 RBAC over the 7 roles, 2.2 verbatim response-structure block, 2.3 Pagination, 2.4 Logical Show Clock, 2.5 Identity/Timestamps/Version, 2.6 Money & Rounding, 2.7 Stale-Read Protection, 2.8 Derived Ledgers & Cascades, 2.9 Nested Paths, 2.10 the ordered 1–48 rejection precedence); §3 with ten workflow subsections following the business timeline (setup → offer gates → negotiation → acceptance spine → production advance → show calendar → box office → sponsorship → weather contingency → settlement waterfall/rescoring/report); §4 with all 56 endpoints in a 4-column table; §5 with all 48 error IDs in a 2-column table.

Hard Contract reports (verified programmatically against SCAFFOLD.yaml):

```
Field coverage check:
- entities[].fields: 153 required, 153 present, 0 missing
- endpoints[].request_body: 79 required, 79 present, 0 missing
- endpoints[].query_params: 28 required, 28 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 48 checked, 48 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 4 checked, 4 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 35 checked, 35 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 48 checked, 48 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 30 checked, 30 expressed, 0 missing
- entities[].fields[] structured content: 153 checked, 153 reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked, 7 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1008
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Supporting verification: all 28 transition state names, both OCC field names, all 48 error IDs, all 20 computed-read output keys, and every numeric constant (0.0575, 0.60, 0.25, 2,500,000, 0.035, 0.20/0.30/0.05, 2,500, 25,000, 750,000, 10,000,000, 1.30, 0.60/40.0, 0.40/60.0/500, 7, 4, 1.10, 0.35) appear in the prose either as figures or as exact words. Zero fuzzy-language hits; only the two §2.2 fenced blocks exist (no pseudocode elsewhere); §4 rows are uniformly 4 columns (56 endpoints) and §5 rows 2 columns (48 errors).

Two judgement calls flagged by the generator: (1) the fair-editions list is documented as the single newest-first exception to the global ascending-`created_at` default, per scaffold fidelity; (2) the scaffold's POSTPONE side-effects name only `RAIN_CHECK` and `FULL_REFUND` explicitly, so §3.9 states those two verbatim and completes the `NO_REFUND_AFTER_DOORS` case consistently with the refund-rate table (box-office dimension to `REFUNDING` carrying the computed liability, with the `REFUNDING → REFUNDED` auto-close when that liability is 0).

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read.

### Orchestrator verification (truncation guard)

`tail -25` confirms the document terminates on the last row of the §5 error table — a real section boundary, not a mid-sentence cut. Counted 48 `ERR_` table rows and 56 endpoint rows (58 lines incl. header + separator), matching the generator's claim. No regeneration needed.

Orchestrator edit (1 word): §2.1 contained the phrase "where the scaffolded workflow demands an audit trail" — a stray reference to the internal scaffold artifact in implementer-facing prose. Replaced "the scaffolded workflow" with "the workflow". No behavioral content changed; this is not a truncation hand-patch.

## Step 5: Generate Unit Tests — 2026-09-05T01:52:00.000Z

Test infrastructure and test suite for task 2794 are complete.

### What was produced

**`test_helpers/`** — 9 files, 2,527 lines (Stage 1): `types.py` (483), `api_client.py` (330, one method per endpoint, `/grandstand` prefix baked in), `api_errors.py` (132, all 48 error IDs + HTTP status registration), `assertions.py` (437), `constants.py` (128), `factories.py` (247), `fixtures.py` (635, API-only scenario builders), `test_users.py` (81), `__init__.py` (54).

**`test_suite/`** — `conftest.py` plus 15 test files, 7,922 lines total, **138 test functions / 147 collected cases**:

| file | lines | file | lines |
|---|---|---|---|
| test_01_offer_negotiation_lifecycle | 291 | test_09_entity_records_and_defaults | 660 |
| test_02_offer_send_scheduling_gates | 728 | test_10_state_machine_transitions | 870 |
| test_03_stage_slot_saturation_cascade | 97 | test_11_money_calculations | 536 |
| test_04_production_advance_rulings | 258 | test_12_field_validation_rules | 521 |
| test_05_ticket_scaling_and_box_office | 321 | test_13_endpoint_surface_and_consistency | 567 |
| test_06_sponsorship_activation_pricing | 397 | test_14_error_catalogue | 917 |
| test_07_weather_contingency_cascade | 229 | test_15_access_control_and_layered_flows | 1019 |
| test_08_settlement_waterfall_and_rescoring | 449 | | |

### Audit results (all run against the files on disk)

- **Coverage: 88 of 89 non-stub design instances translated.** All 22 queue-A instances carry >=2 tests except the one skip; all 67 non-stub queue-B instances carry >=1. Zero tags point at the 19 `excluded_because:` stubs; zero unknown tags.
- **Citations C1–C4: 0 defects.** Every one of the 138 tests has exactly one `Design:` line as the final docstring line, and every docstring contains a >=8-word PRD fragment that survives a literal substring match against `PRD.md`.
- **Scaffold-citation pass: 0 leaks** — no reference to the scaffold, the design yamls, or design metadata anywhere outside the mandated `Design:` lines.
- `py_compile` clean on all 24 files; `pytest --collect-only` collects 147 tests with no import or fixture errors. Caches removed; `workspace/` and `worklog.md` untouched.

### The one gap (deliberate, per the design-index contract)

`Difficulty/resource_temporal_overlap/artist_radius_closed_asymmetric_day_window` was skipped: its two pinned outcomes are the exact inverse of what the PRD derives. PRD §3.2 centres the exclusion window on **the candidate's** date using **the blocking offer's** half-widths ("the window running from the candidate's performance date minus that other offer's `radius_days_before` through the candidate's performance date plus that other offer's `radius_days_after`"). With the recipe's asymmetric 3/1 widths, candidate 2026-08-19 is admitted where the yaml asserts `ERR_RADIUS_CLAUSE_CONFLICT`, and candidate 2026-08-25 is refused where the yaml asserts success. Verified against the PRD directly. The instance fails the unique-derivability condition, so it produced no output rather than a weakened test.

### Design-index defects worth relaying to whoever owns the yamls

Agents flagged these and asserted only PRD-derivable facts rather than adjusting any pinned number:

- Undeclared enum members in recipes: genre `JAZZ`, segment `ADULT` (substituted with `COMEDY` / `ADULT_45_PLUS`, all literals preserved); ticket-scale statuses `ON_SALE_PENDING`, `ON_SALE`, and `TICKETING_NOT_STARTED`, none of which are declared members.
- Undeclared field names: `gross_potential_at_creation_cents` on the activation (prose-only snapshot), plus `sold_units` -> `sold_seats`, `advance_status`/`scale_status` -> `status`.
- Two instances assert the settlement waterfall figures on the *created* record, but §3.10 leaves all eleven at 0 until submission; those were asserted via the submit step or the preview endpoint instead.
- One activation instance pins `net_fee_cents == 400000` / `sponsorship_revenue_cents == 1000000` on a booking whose gross potential (11,866,075) is over the 10,000,000 high-demand threshold, so §3.8 uniquely derives 440,000 / 1,100,000.

## Step 6: Generate Implementation — 2026-09-05T01:38:00.000Z

Done. The implementation is complete, compiles clean, and both smoke passes are validated. (Launched in the SAME assistant message as Step 5, so the impl generator started before `test_suite/` existed on disk — physical isolation preserved.)

### What was built

`workspace/implementation/` — Python + Flask, all routes mounted under `/grandstand`, storage in-memory only (dicts in `db.py`, empty on every boot, no seeded data, no file/SQLite/tmp persistence), logical clock starting at `2026-08-01T00:00:00Z` as the sole timestamp source.

Per-file line counts (`COMPILE_OK` on all 20 modules, 3577 Python lines):

| file | lines | file | lines |
|---|---|---|---|
| `response.py` | 59 | `db.py` | 217 |
| `lookup.py` | 61 | `routes/settlements.py` | 222 |
| `errors.py` | 69 | `schema.py` | 257 |
| `authz.py` | 74 | `routes/bookings.py` | 297 |
| `app.py` | 86 | `routes/core.py` | 298 |
| `spine.py` | 160 | `ledgers.py` | 306 |
| `routes/boxoffice.py` | 169 | `calc.py` | 330 |
| `routes/production.py` | 199 | `routes/offers.py` | 374 |
| `routes/sponsorship.py` | 199 | `routes/__init__.py` | 1 |
| `scheduling.py` | 199 | `start.sh` (+x) / `requirements.txt` | 7 / 1 |

`start.sh` is the skill's guarded launcher (installs flask only if missing, then `exec python3 app.py`); `app.py` honours `PORT` and runs `threaded=True` with a global request lock so ledger recomputation always reads consistent state.

### Smoke verification

Ran on port 47913 (server killed by exact PID 1281686, port confirmed released; no pattern kill used at any point).

- **Pass 1** — full happy path plus 14 negative cases: offer negotiate/counter/revise/accept, booking, scaling, advance, sponsorship, sale batches, performance, settlement waterfall and approval. `FAILURES: none`. Spot figures: `adjusted_gross` 20,829,250; `artist_payout` 15,516,113; `base_promoter_expense` 2,900,000; merch floor yielding `merch_artist_share_cents` -25,000 at zero merch gross; `genre_diversity_index` 0.1964.
- **Pass 2 (weather contingency)** — reschedule self-exclusion, `ERR_SHOW_DATE_OUTSIDE_FAIR_RUN`, `ERR_CURFEW_VIOLATION`, POSTPONE from `DATE_HELD` with replacement-booking creation (time-of-day preserved, deal terms copied, new `ADVANCE_PENDING` + seed STAGING line), original advance `ADVANCE_CANCELLED`, stage `held_show_count` netting flat, action on a `POSTPONED` booking -> 409, `ERR_ALLOTMENT_EXCEEDS_STAGE_CAPACITY`, COMP batches excluded from `paid_attendance`, `ERR_REFUND_EXCEEDS_SOLD_UNITS`, `ERR_REFUND_RESERVE_EXCEEDED` (with the booking left untouched by the refusal), CANCEL cascade -> `CANCELLED`/`REFUNDING` with tiers `REFUND_DUE`, advance voided, stage released, edition `refund_liability_committed_cents` reconciled, and post-cancel sales refused with `ERR_INVALID_TICKETING_STATE`. All green.

Four apparent failures in pass 2 were errors in the generator's *expectations*, not the code, each confirmed against the PRD: refund units exclude complimentary batches (PRD §321 — 100 non-COMP sales - 60 refunds = 40 x 5,300 = 212,000, not 265,000), and `committed_guarantee_total_cents` is derived purely from offer statuses (§119/§211), so a booking cancellation correctly leaves it standing. Three earlier failures came from the smoke script passing an invalid `channel` value (`WALKUP`; the enum is `ONLINE`/`BOX_OFFICE`/`PHONE`/`COMP`) and cascaded from that.

Nothing outside `implementation/` was created, modified, or read — `worklog.md`, `PRD.md`, `test_helpers/` and `test_suite/` were untouched.

### Orchestrator verification after Steps 5+6

`find workspace -maxdepth 2 -type d -name "test_*"` returns nothing — `test_helpers/` (2,527 lines) and `test_suite/` (7,922 lines) both landed at the task root as required, not under `workspace/`. `find . -name worklog.md` returns exactly one file (the task-root worklog), so no cwd-drift stray was created. `start.sh` present and correct.

## Step 7: Run Tests and Iterate — 2026-09-05T03:26:00.000Z

Clean 8-round parallel sweep achieved: **147/147 passed in all 8 rounds** (no flakiness, no skips).

### Summary

**Iterations run:** 2

**Iteration 1 result:** 144/147 in all 8 rounds — the same 3 tests failed deterministically in every round (no flakiness, no load-induced failures, no reaping).

**Tests deleted:** none. All three failures traced to verbatim PRD rules and survived the STEP 1a/1b coverage + unique-derivability checks.

**Fixes applied to `test_suite/`:**
- `test_suite/test_14_error_catalogue.py` — `test_confirm_on_cancelled_activation_and_approve_on_draft_settlement_are_state_errors`: the test marked the booking `PERFORMED` *before* probing confirm/cancel on the already-`CANCELLED` activation. PRD §2.10 orders the booking contractual-state check (rank 19, `ERR_INVALID_BOOKING_STATE`) ahead of the activation-state check (rank 22), and §3.8 requires the booking to be `DATE_HELD`/`ANNOUNCED` for confirmation — so the PRD-faithful implementation correctly reported `ERR_INVALID_BOOKING_STATE`. Moved the two activation-state probes to before `mark_performed`, where the booking still reads `ANNOUNCED` and the activation's terminal status is the only rejection that can fire. Every assertion preserved; nothing weakened.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py`, `setup_draft_offer` — the fixture passed `world["artist"]["id"]` positionally into `create_offer` while forwarding `**offer_overrides`, so any scenario wanting a second act on the same world (`setup_accepted_booking(world, artist_id=...)`) died with `TypeError: create_offer() got multiple values for argument 'artist_id'` (hit `test_sponsor_category_and_stage_naming_exclusivity_conflicts_are_rejected`). Now pops `fair_edition_id` / `artist_id` / `target_stage_id` out of the overrides and defaults them to the world's records, so one world can carry offers for several acts or stages.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/bookings.py`, `create_contingency_action` — the `POSTPONE` branch omitted `spine.cancel_activations(booking)`, so a postponed show kept its `sponsorship_revenue_cents` and left confirmed activations `CONFIRMED` with no make-good credit. PRD §3.9: "A `POSTPONE` shares that whole voiding cascade on the original records but adds a replacement", and the CANCEL cascade it refers to states "Every sponsorship activation on the booking whose status is `PROPOSED` or `CONFIRMED` becomes `CANCELLED` with its `make_good_credit_cents` set to its `net_fee_cents`, and the booking's `sponsorship_revenue_cents` is recomputed to 0." Added the call (advance voiding and the flat stage-slot netting were already correct).

Note: `worklog.md` was not created, edited, or touched by the subagent.

### Orchestrator verification of the sweep artifacts

Independently parsed all 8 `results.$i.json`: every round reports `passed=147 total=147 failed=0 skipped=0`. `find workspace/implementation -name "*.py" -newer results.1.json` returns nothing, so the green sweep post-dates every implementation edit (not a stale pre-fix artifact). `grep -rn "pytest.mark.skip\|pytest.mark.xfail" test_suite/` returns nothing, so the pass was not bought with skips. Step 8 is NOT skipped: Step 7 applied 1 `implementation/` fix, 1 `test_suite/` fix and 1 `test_helpers/` fix.

## Step 8: Finalize PRD — 2026-09-05T03:34:00.000Z

Done. `PRD_FINALIZED.md` is a 2-line patch of `PRD.md`.

### Counts
- PRD.md: 481 lines / 108,510 bytes
- PRD_FINALIZED.md: 481 lines / 109,286 bytes (0.0% line delta, +776 bytes; 2 lines revised, 0 added/removed)
- Tail verified: ends at `## 5. Error Code Catalogue` with all 48 `ERR_*` table rows intact.

### Changes
- §3.9 (Weather Contingency, POSTPONE paragraph) — revise — spelled out the two halves of the shared voiding cascade that the vague "shares that whole voiding cascade" left open: every `PROPOSED`/`CONFIRMED` activation on the original booking becomes `CANCELLED` with `make_good_credit_cents = net_fee_cents` and `sponsorship_revenue_cents` recomputes to 0; and the price tiers are explicitly excluded (they keep their existing `status`, never `REFUND_DUE`, whatever the refund policy) — `implementation/routes/bookings.py:270-284`, `implementation/spine.py:127-134`.
- §3.8 (Sponsorship, cancellation paragraph) — insert — pinned that activation cancellation weighs only the activation's own status and, unlike confirmation, imposes no `DATE_HELD`/`ANNOUNCED` booking gate, so a still-`PROPOSED` activation on a performed show is cancellable — `implementation/routes/sponsorship.py:185-199` (no booking lookup) vs `:162-170` (confirm does gate).

No PRD change for the `test_helpers/fixtures.py` `setup_draft_offer` fix (pure `TypeError` from positional `artist_id` colliding with `**offer_overrides`; no behavior claim involved). No PRD change for the §2.10 rank-19-before-rank-22 reasoning behind the `test_14` reordering — PRD already states that ordering and the confirm-time `DATE_HELD`/`ANNOUNCED` requirement verbatim, and impl matches; prose left untouched.

### Per-edit pre-edit search log

**Edit 1 — §3.9 POSTPONE cascade**
- (a) Subject: the exact set of records a POSTPONE voids on the original booking — sponsorship activations, price tiers, advance/rider lines, derived ledgers.
- (b) Enumerated/read: `routes/bookings.py:193-286` (both CANCEL and POSTPONE branches of `create_contingency_action`, ordering of `mark_scales_refund_due` / `cancel_activations` / `void_advance` / `create_replacement_booking` / `recompute_stage_ledger`); `spine.py` in full (`cancel_activations`, `mark_scales_refund_due`, `close_scales`, `fulfil_activations`, `void_advance`, `create_replacement_booking`, `create_advance_with_seed`); `ledgers.py` in full (`recompute_booking_sponsorship_revenue` with `LIVE_ACTIVATION_STATUSES`, `recompute_stage_ledger`/`stage_held_count` with `HELD_BOOKING_STATUSES`, `recompute_advance_ledgers`, `recompute_booking_recoupable`, `recompute_booking_refund_liability`, `recompute_edition_refund_committed`); grepped every `REFUND_DUE` / `CLOSED` / `ON_SALE_ELIGIBLE` / `SCALE_STATUSES` site across `implementation/` (only `spine.mark_scales_refund_due`, `spine.close_scales`, tier creation in `routes/boxoffice.py:76`, and the `status` list filter) plus `routes/bookings.py:161-180` (announce / mark_performed) to confirm no other writer of tier status; `routes/boxoffice.py:128` to confirm post-postpone batch writes are already blocked by the `ON_SALE` ticketing gate.
- (c) Adjustment: scoped the sponsorship sentence to "the original booking" so it cannot be read as touching the replacement, and phrased the tier exclusion as "keeps the `status` it already carries" rather than naming `ON_SALE_ELIGIBLE`, since a tier reaching a POSTPONE could already be `REFUND_DUE` (from an earlier CANCEL-shaped path) or `CLOSED`; also verified "recomputed to 0" stays true under the impl's sum-over-`CONFIRMED`/`FULFILLED` recompute, because `FULFILLED` is only reachable from `PERFORMED`, a state POSTPONE cannot start from.

**Edit 2 — §3.8 activation cancellation gating**
- (a) Subject: which state dimensions the activation `cancel` trigger tests (activation status only, vs. the booking's contractual status).
- (b) Enumerated/read: `routes/sponsorship.py` in full — `cancel_activation` (`:185-199`, no `lookup.get_booking`, no `require_booking_status`), `confirm_activation` (`:162-182`, gates on `DATE_HELD`/`ANNOUNCED` before the activation check), `create_activation` (`:93-127`, same booking gate), `require_activation_status`, `check_category_exclusivity`, `check_stage_naming`; `spine.cancel_activations` and `spine.fulfil_activations` as the cascade-driven writers of activation status; `routes/bookings.py` `require_booking_status`/`mark_performed`; PRD §2.10 ranks 19/22 and §3.9's "CANCELLED and POSTPONED admit no further booking trigger of any kind".
- (c) Adjustment: narrowed the illustrative case to a `PROPOSED` activation on a performed show — the only state combination actually reachable, since the CANCEL/POSTPONE cascades already drive every `PROPOSED`/`CONFIRMED` activation on a cancelled or postponed booking to terminal `CANCELLED`; avoided a blanket "regardless of booking state" phrasing that would have implied reachable behavior the impl never exhibits.

### Orchestrator verification

`diff PRD.md PRD_FINALIZED.md` yields 8 diff lines (2 revised lines) — a real patch, not a byte-identical copy. `tail` confirms the document still ends on the last row of the §5 table; 48 `ERR_` rows and 28 headings in both files, so no section was lost during editing.

### Step 9 execution decision (orchestrator judgement, recorded per AUTONOMY)

Step 9 will be run as **three sequential, module-partitioned passes** over one shared `PRD_COMPLETED.md` rather than a single subagent scan. Rationale: a single agent asked to walk 20 modules / 3,577 lines against a 108KB PRD reliably either exhausts its budget mid-scan or emits a byte-identical copy, and the partitioned form gives each pass a small enough impl surface to walk exhaustively. Pass 1 performs the `cp PRD_FINALIZED.md PRD_COMPLETED.md` and covers the offer/negotiation + core surface; passes 2 and 3 must NOT re-copy (that would discard the previous pass's edits) and cover bookings/production/scheduling and boxoffice/sponsorship/settlement/calc/ledgers respectively. Passes run strictly one after another because they edit the same file.

## Step 9: Complete PRD — 2026-09-05T04:12:00.000Z

Run as three sequential, module-partitioned passes over one shared `PRD_COMPLETED.md`, per the decision recorded under Step 8. Pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying and both confirmed they edited in place. Net result: **481 lines / 119,951 bytes** (from 481 lines / 109,286 bytes), 44 lines changed versus `PRD_FINALIZED.md`, 45 edits total (32 ambiguity-pins, 8 mismatch-revisions from the passes, plus 2 orchestrator boundary edits and the pass counts below). Structure intact: 28 headings, 48 `ERR_*` rows, ends at `## 5. Error Code Catalogue`.

### Pass 1 — app / authz / db / errors / response / lookup / schema / routes.core / routes.offers

`cp` done. 481 lines / 109,286 chars -> 481 lines / 113,056 chars (+3,770). **18 ambiguity-pins, 2 mismatch-revisions.**

- §2.1 — revise — ambiguity — a header carrying only whitespace counts as empty for the 401 check — `authz.py:46-49`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus twenty upper-case-alphanumeric characters — `response.py:10-14`
- §2.3 — revise — ambiguity — a `limit`/`offset` that is empty or not an integer at all is also a 400, not only out-of-band values — `schema.py:200-225`
- §2.3 — insert — ambiguity — ties on the ordering key resolve by creation order (earliest first ascending, latest first for the descending edition list); important because the manual clock makes shared `created_at` the norm — `db.py:215-217`, `response.py:55-59`
- §2.5 — insert — ambiguity — a client-supplied `_utc` instant is stored/echoed verbatim, not re-rendered to three fractional digits — `schema.py:172-179`
- §2.6 — revise — ambiguity — a JSON number with a zero fractional part (`250000.0`) is accepted as the integer it names; booleans are refused — `schema.py:86-96`
- §2.6 — insert — ambiguity — the stated decimal places on `_pct`/draw-score fields are convention, not validation; only the band is enforced — `schema.py:115-131`
- §2.8 — insert — ambiguity — a cascade hop finding a derived figure already reconciled writes nothing and does not bump `updated_at`/`version`; and no record's `version` moves more than once per request — `ledgers.py:99-104`, `db.py:189-205`
- §2.9 — insert — ambiguity — a query-filter identifier is resolved only where its own operation says so; otherwise an unmatched value yields an empty page, not a 404 — `routes/offers.py:170-171`, `routes/core.py:187-188`
- §2.10 step 3 — revise — **mismatch** — `slot_soft_cap` and `max_shows_per_day` are minimum 1 (not 0), and `response_window_hours` is minimum 1 (not 0); §2.10 contradicted both §3.1/§3.2 and the impl — `routes/core.py:65,150`, `routes/offers.py:113`
- §2.10 step 3 — insert — ambiguity — explicit JSON `null` == omission; undeclared body keys ignored; blank query filter is a 400; `_utc` fractional part optional (only trailing `Z` required) — `schema.py:78-83,191-193,228-234`, `db.py:77-100`
- §3.1 — revise — ambiguity — year band, duplicate year and inverted run window are all `ERR_INVALID_REQUEST` — `routes/core.py:58,70-74`
- §3.1 — revise — ambiguity — duplicate stage name within an edition is `ERR_INVALID_REQUEST` — `routes/core.py:153-155`
- §3.1 — revise — ambiguity — stage list `fair_edition_id` filter is resolved -> `ERR_FAIR_EDITION_NOT_FOUND` — `routes/core.py:187-188`
- §3.1 — revise — ambiguity — duplicate agent `user_id` is `ERR_INVALID_REQUEST`; `contact_email` is never shape-checked — `routes/core.py:207-212`
- §3.1 — revise — ambiguity — artist list `agent_id` filter is resolved -> `ERR_TALENT_AGENT_NOT_FOUND` — `routes/core.py:287-288`
- §3.2 — revise — ambiguity — offer draft resolves all three ids but does not require the stage to belong to the named edition — `routes/offers.py:115-117`
- §3.2 — revise — ambiguity — of the four offer-list filters only `artist_id` is resolved; unmatched edition/stage filters return an empty page — `routes/offers.py:170-182`
- §3.2 — revise — ambiguity — the round written by a send carries `note` null — `routes/offers.py:236-243`
- §4 intro / §5 intro — insert + revise — **mismatch** — an unrouted path answers `ERR_NOT_FOUND` (404) and a disallowed method `ERR_METHOD_NOT_ALLOWED` (405); §5's "one of the identifiers below" now excepts those two routing-level ids (catalogue table left at 48 rows) — `app.py:62-70`, `errors.py:52-53`

Verified with no change needed: all 48 catalogue statuses match `errors.py` exactly; §2.10's rejection order matches every gate sequence in `offers.py`; the send-gate order (curfew -> slot -> radius -> genre -> day capacity -> budget); every role list in §4 matches its decorator; the expiry auto-transition, withdraw-from-`DRAFT` no-op, and `ACCEPTED`-excluded stage-hold arithmetic are already uniquely pinned.

### Pass 2 — routes.bookings / routes.production / scheduling / spine

No copy made; all 20 of pass 1's edits verified still present. 481 lines / 113,056 bytes -> 481 lines / 115,815 bytes. **7 ambiguity-pins, 3 mismatch-revisions.**

- §3.2 (fifth gate, per-day capacity) — revise — **mismatch** — "across every stage of the edition" was false for the offer half: held offers are counted through their own `fair_edition_id` whatever stage they target, bookings through the edition their stage belongs to; candidate excluded from the tally and counted as `+1` — `scheduling.py:146-169`
- §3.4 — insert — ambiguity — pinned which list filters resolve: `stage_id`/`offer_id` -> `ERR_STAGE_NOT_FOUND`/`ERR_OFFER_NOT_FOUND`, `postponed_from_booking_id` unresolved (empty page), advances' `booking_id` -> `ERR_SHOW_BOOKING_NOT_FOUND`, and an out-of-enum status filter -> `ERR_INVALID_REQUEST` — `routes/bookings.py:75-78`, `routes/production.py:56-57`
- §3.5 — insert — ambiguity — `description` must be a non-blank string — `routes/production.py:98`
- §3.5 — insert — ambiguity — both `substituted_cost_cents` failures are `ERR_INVALID_REQUEST`, but only presence is decided at §2.10 step 3; the <= `requested_cost_cents` comparison runs *after* the advance state check, so `ERR_INVALID_ADVANCE_STATE` wins — `routes/production.py:160-172`
- §3.5 — revise — **mismatch** — PRD claimed `APPROVED`/`SUBSTITUTED` "on any line" loops `ADVANCE_IN_REVIEW -> ADVANCE_IN_REVIEW`; impl only unblocks on `SUBSTITUTED`, so an `APPROVED` ruling on the denied critical line leaves `ADVANCE_BLOCKED` + `DENIED_CRITICAL_ITEM` standing, and a `DENIED` re-ruling of a critical line not in `REQUESTED` never blocks. Also pinned that `MISSING_STAGE_PLOT` is declared but never written — `routes/production.py:185-195`
- §3.5 — insert — ambiguity — the seed staging line is the earliest-created `STAGING` + `is_critical` line of the advance — `routes/production.py:31-37`
- §3.6 (reschedule) — revise — ambiguity — the booking *and the accepted offer it was born of* are both excluded from the candidate sets — `scheduling.py:172-199`
- §3.9 (postpone gates) — insert — ambiguity — the re-tested coordinates are the load-in/load-out instants advanced by the whole-day replacement delta (time of day preserved), the offer is excluded too, and radius, window well-formedness and curfew are not re-checked — `routes/bookings.py:219-231`
- §3.9 (postpone refund policies) — revise — **mismatch** — the `REFUNDING -> REFUNDED` zero-liability auto-close applies under `FULL_REFUND` as well as `NO_REFUND_AFTER_DOORS` — `routes/bookings.py:270-276`
- §3.9 (replacement booking) — insert — ambiguity — the replacement carries the same `offer_id` as the original, with `doors_time_utc`/`announced_at_utc` null and all five derived ledgers at 0 — `spine.py:78-106`

Audited and already uniquely pinned (no change): announce gate set and its §2.10 positions, mark-performed cascade, `pre_doors` strictness, cancel cascade ordering and stage-ledger release, booking/edition refund-liability recomputes and their orderings, advance/seed construction at acceptance, rider-line add gates and per-addition version bump, contingency-action append-only shape, and all §4 role columns for these endpoints.

### Pass 3 — routes.boxoffice / routes.sponsorship / routes.settlements / calc / ledgers

No copy made; all 30 prior edits verified present (diff against `PRD_FINALIZED.md` touched 42 distinct lines: 12 pass 1, 17 pass 2, 13 pass 3). 481 lines / 115,815 bytes -> 481 lines / 119,415 bytes. **12 ambiguity-pins, 3 mismatch-revisions.**

- §3.6 — insert — ambiguity — duplicate `tier_name` is refused with `ERR_INVALID_REQUEST`, and because the test reads stored tiers it runs after the booking's two state checks and version check, before the allotment ceiling — `routes/boxoffice.py:47`
- §3.7 — insert — ambiguity — a `REFUND` batch's `gross_cents` is positive; batch kind never flips the sign — `calc.py:92`
- §3.7 — insert — ambiguity — `sold_seats` counts complimentary batches alongside every other channel, and nothing caps a `SALE` against remaining allotment, so a tier may be oversold and `available_seats` may go negative — `ledgers.py:266`, `routes/boxoffice.py:120`
- §3.7 — insert — ambiguity — the refund guard tests the tier's stored `sold_seats` (comps included) and is indifferent to the candidate batch's own `channel` — `routes/boxoffice.py:131`
- §3.8 — insert — ambiguity — `exclusivity_category` is not required to equal the sponsor's registered `category` — `routes/sponsorship.py:102`
- §3.8 — revise — **mismatch** — confirmation bumps the booking's `version` only where `sponsorship_revenue_cents` actually moves (a zero-fee activation leaves it untouched); PRD claimed it always increments — `routes/sponsorship.py:181`, `ledgers.py:296`
- §3.8 — revise — **mismatch** — same correction for cancellation from `CONFIRMED` — `routes/sponsorship.py:197`
- §3.8 — insert — ambiguity — activation list is `created_at` ascending; `booking_id` and `sponsor_id` are resolved (404), `rights`/`status` are not — `routes/sponsorship.py:144`
- §3.10 — insert — ambiguity — settlement creation writes only the new row; the booking is not touched and its `version` does not move — `routes/settlements.py:84`
- §3.10 — insert — ambiguity — submission carries no payload; `basis`/`merch_gross_cents`/`merch_seller` are frozen at creation, and `revision_count` plus any leftover `rejection_reason_code` are preserved — `routes/settlements.py:158`
- §3.10 — insert — ambiguity — `net_pool_cents` is **not** floored (unlike step four) and is reported negative when the provisional pool was floored to 0 — `calc.py:192`
- §3.10 — insert — ambiguity — the preview is gated by nothing but booking existence, and its three inputs arrive as query parameters — `routes/settlements.py:103`
- §3.10 — insert — ambiguity — the rescoring write is unconditional, not a §2.8 derived-ledger recompute: the artist's `version` bumps even when the score is unchanged — `routes/settlements.py:199`
- §3.10 — revise — **mismatch** — the zero-allotment branch sets `draw_score_next_year` to `base_draw_score` **rounded half up to two places**, not echoed verbatim — `calc.py:277`
- §3.10 — insert — ambiguity — settlement list is `created_at` ascending; only `booking_id` is resolved — `routes/settlements.py:138`

Pass 3 also confirmed no `PATCH`/`PUT` route exists anywhere in `implementation/`, so the edition's `gate_admission_price_cents` is immutable and the live-vs-snapshot gate-credit question in `calc.py:76` is moot.

### Orchestrator closing edits (2 inserts) — the one residual false universal

Pass 3 flagged, and pass 2 had deliberately left, a genuine residual mismatch: both show-concluded gates (`routes/bookings.py:176` mark-performed, `routes/settlements.py:76` settlement creation) compare instants with a raw Python string comparison, `now_str() < booking["load_out_end_utc"]`. Since pass 1 pinned in §2.5 that a client-supplied `_utc` value is stored and echoed verbatim, a `load_out_end_utc` written without a fractional part makes the clock sitting exactly at load-out compare as *earlier* (`".000Z"` sorts before `"Z"`), so `ERR_SHOW_NOT_YET_CONCLUDED` fires at the boundary — contradicting §3.6's flat claim that "a clock reading exactly `load_out_end_utc` is admitted".

Neither pass would touch it (pass 2 to avoid contradicting itself, pass 3 to avoid contradicting pass 2), so the orchestrator resolved it rather than leave a known divergence in the completed PRD:
- §3.6 (mark performed) — insert — mismatch — added that the "at or after" test is a character-by-character comparison of the clock's canonical rendering against the stored `load_out_end_utc` text as supplied, so equality is admitted only when the stored instant carries the same three-fractional-digit rendering, and a shorter rendering of the same moment sorts as later and is refused at the boundary — `routes/bookings.py:176`, `db.py:137-139`
- §3.10 (settlement creation, third gate) — insert — mismatch — cross-referenced that gate to the same character-by-character comparison — `routes/settlements.py:76`

### Final verification

`PRD.md` 481 lines / 108,510 bytes -> `PRD_FINALIZED.md` 481 lines / 109,286 bytes -> `PRD_COMPLETED.md` 481 lines / 119,951 bytes (+10,665 bytes over PRD_FINALIZED, 44 lines changed). `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md`, so the scan genuinely ran. 48 `ERR_*` rows and 28 headings preserved in all three files; `PRD_COMPLETED.md` ends on the last row of the §5 catalogue table. `implementation/` was not modified by Steps 8 or 9, so the Step 7 green sweep (147/147 in all 8 rounds) remains the valid result of record.

## Pipeline complete — 2026-09-05T04:12:00.000Z

Steps 1–9 all executed. Final state: 3 scaffold artifacts, `test_helpers/` (9 files / 2,527 lines), `test_suite/` (16 files / 7,922 lines, 147 collected tests), `workspace/implementation/` (20 modules / 3,577 lines, in-memory only), and the PRD lineage `PRD.md` -> `PRD_FINALIZED.md` -> `PRD_COMPLETED.md`, with `results.{1..8}.json` recording 147/147 in all eight rounds.
