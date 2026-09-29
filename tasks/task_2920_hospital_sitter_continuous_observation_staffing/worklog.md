# Worklog — task_2920_hospital_sitter_continuous_observation_staffing

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `tasks/task_2920_hospital_sitter_continuous_observation_staffing/` and `tasks/task_2920_hospital_sitter_continuous_observation_staffing/workspace/`. Index 2920 was pre-assigned by the invoker; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T18:25:00.000Z

All three scaffold artifacts for task 2920 are complete and lint-clean.

**Files** (all under `tasks/task_2920_hospital_sitter_continuous_observation_staffing/`)

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 2050 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1419 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3128 |

`SCAFFOLD.yaml` top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears in it, and each design file has its single required top-level key.

**§1.0–§1.7 counts:** 11 entities (Unit, Patient, Staff, ObservationOrder, SitterAssignment, MonitoringStation, VideoFeed, Reassessment, HandoffRecord, SafetyEvent, CostEntry) · 55 endpoints (28 GET / 27 POST) · 48 error codes · 7 roles (Sitter and RemoteObserver `entity_backed: Staff`) · 8 state machines · 1 `concurrency_rules` entry (`sitter-assignment-create-stale-order`, `expected_order_version`, `ERR_STALE_ORDER_VERSION` 412) · 10 calculations · 29 ordered validations · `difficulty_level: expert_plus`.

**§1.8 rules — 9 rules × 2 instances = 18:** `dual_variant_calc` 2, `combinatorial_formula` 2, `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 2, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2.

**§1.9 sections — 9 sections, 76 instances (52 full recipes + 24 `excluded_because` stubs):** entities 11 (10+1) · state_machines 13 (8+5) · calculations 9 (5+4) · validations 15 (8+7) · endpoints 7 (4+3) · errors 8 (8+0) · rbac 6 (6+0) · cross_cutting_layers 5 (2+3) · consistency_model 2 (1+1).

**Verification performed:** all three files parse under `yaml.safe_load`; zero duplicate `name` values across the union of both design files; all 24 stub `difficulty_instance` refs resolve to real §1.8 instance names and no stub carries a `test_recipe`; zero unbound `${...}` placeholders across all 672 calls and asserts; every recipe instance has non-empty `setup`/`trigger`/`assert` plus `distinguishing_aspect` (five instances carry a deliberate empty `setup_api_calls: []` — fresh-server not-found and create-from-nothing probes).

One lint fix was needed on this pass: the role-denial matrix instance had to be renamed `every_exclusive_write_refuses_...` → `every_exclusive_write_rejects_the_roles_that_do_not_own_it`, because `scaffold_lint.py` only exempts intentional role violations when the instance name matches its `_NEGATIVE_NAME_RE` (`_rejects_`, `_cannot_`, `_returns_4XX`, …).

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5. (55 endpoints declared, 11 entities declared, 18 §1.8 instances scanned, 52 §1.9 instances scanned, 672 calls scanned)

**Orchestrator post-step action:** the scaffold generator had copied the difficulty directive line ("Generate task harder than expert level!") into `SCAFFOLD.yaml`'s `scenario:` block. That line was stripped by the orchestrator so it cannot reach PRD.md via the doc generator, which reads SCAFFOLD.yaml. Re-verified `yaml.safe_load` after the edit; `scenario` now begins "2920. Hospital Sitter & Continuous Observation Staffing …".

## Step 3: Copy shared files — 2026-09-05T18:26:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T18:41:00.000Z

**Output:** `workspace/PRD.md` — 428 lines / 93,789 characters
**Final section heading:** `## 5. Error Code Catalogue` (line 377) — document ends at a completed section boundary, on the last table row `| ERR_UNIT_RESTRICTED_AGENCY_BLOCKED | 402 Payment Required |`. No mid-sentence truncation.

**Structure (27 headings):** §1 Introduction; §2 Global Specifications & System-Wide Principles (11 subsections: RBAC; API Response Structure; Pagination; Common Resource Properties and the Logical Clock; Path Resolution and Reference Validation Order; The Enforcement Ladder; Numeric Precision; Optimistic Concurrency on the Observation Order; Cascade Discipline and Version Bookkeeping; The Unit Observation Ledger as a Conserved Quantity; Half-Open Windows); §3 Business Logic & Workflows (9 workflow subsections); §4 Endpoint Definitions (55-row, 4-column table); §5 Error Code Catalogue (48-row, 2-column table).

### Hard Contract reports

**Contract 1 — Field-Name Coverage:** 119 required, 119 present, 0 missing. **PASS**

**Contract 2 — Rule Coverage:** 29 validations with priority expressed as an explicit ordered ladder in §2.6 (plus 3 operation-specific rules); 1 `concurrency_rules` OCC rejection fully expressed (sitter-assignment creation + `expected_order_version` + `ERR_STALE_ORDER_VERSION` + 412); all transitions across all 8 state machines expressed including every cascade hop and the load-bearing "suspension applied last" ordering; all 11 calculations expressed with constants embedded in business context; every validation condition matchable to its `error_id`; all endpoint `side_effects` and every `applies_to` scope enumerated in full; sibling-branch groups rendered at equal prose density. **PASS**

**Contract 3 — §3 Path Purity:** 833 backtick tokens scanned inside §3; 0 tokens containing `/`, 0 bare HTTP-method tokens, 0 method+path combinations. **PASS**

### Additional checks
- All 48 scaffold error IDs present in §5 with no extras, and each also appears in §2/§3/§4 prose (not table-only).
- §2.2 byte-identical to the canonical `section-2.2-response-structure.md`.
- No numeric hedging language.

### Two self-caught Contract-2 fidelity fixes
1. §3.3 — added explicit sentence that all three occasions using the rolling reading (reassessment, incident-review open, safety-event close) set `risk_score_variant` to `ROLLING_EVENT_WEIGHTED` and recompute `reassessment_interval_hours`.
2. §3.5 — replaced a bare "are all recomputed" with defining aggregations for `watch_segment_count` and `watched_minutes`.

### Constraints honored
Neither design index was opened/grepped/referenced; no sibling task read; PRD.md built via 11 chunked heredoc appends (no single large Write); no `pkill`.

**Orchestrator verification (independent of the subagent's own report):** re-ran `wc -l -c` (428 / 93789), listed all top-level headings (§1–§5 all present and in order), read the tail (ends on a complete markdown table row, not mid-sentence), and grepped for `harder than expert|scaffold|test_recipe|difficulty_level` — zero hits, so the difficulty directive and the design indices did not leak into the PRD. No regeneration needed.

## Steps 5 & 6: Generate unit tests + implementation — 2026-09-05T18:42:00.000Z (launched)

Launched concurrently in a single assistant message (two Agent tool uses) so that the implementation generator is physically unable to read `test_suite/` — the directory does not exist at its spawn time. Step 5 writes `test_helpers/` + `test_suite/` at the task root; Step 6 writes `workspace/implementation/`. Both were given explicit operational guards carried over from prior pipeline runs: chunked heredoc appends instead of one giant Write (64k output cap loses all work), no broad `pkill` (32 concurrent pipelines on this host), task-scoped `/tmp` scratch dirs, no touching `worklog.md`, and — for Step 5 — output paths pinned at the task root rather than under `workspace/`. Summaries appended below on completion.

## Step 6: Generate implementation — 2026-09-05T19:15:00.000Z

(Step 5 was still running when this completed; its summary is appended below out of numeric order to preserve append-only semantics.)

Implementation complete and verified.

## Files written

All in `workspace/implementation/`

| file | lines | bytes |
|---|---|---|
| `app.py` | 66 | 2042 |
| `db.py` | 261 | 8070 |
| `errors.py` | 85 | 3277 |
| `response.py` | 45 | 1168 |
| `validation.py` | 222 | 7763 |
| `calc.py` | 342 | 10985 |
| `serializers.py` | 209 | 7745 |
| `services.py` | 278 | 10855 |
| `routes_reads.py` | 415 | 14594 |
| `routes_core.py` | 197 | 7387 |
| `routes_orders.py` | 184 | 7548 |
| `routes_assignments.py` | 371 | 16610 |
| `routes_stations.py` | 157 | 6643 |
| `routes_events.py` | 216 | 8744 |
| `start.sh` (0775) | 10 | 375 |
| `requirements.txt` | 1 | 11 |
| **total** | **3059** | |

All 14 modules pass `python3 -m py_compile`. `__pycache__` removed; no other files in the dir. Storage is dicts on a single `Store` instance — `grep` confirms zero `sqlite`/`open(`/`json.dump`/`/tmp` references and no seeding (only two comments asserting the absence). A fresh boot returns `total_count: 0` for units, staff and orders.

## Endpoints: 55 implemented vs 55 declared

Mechanically diffed the PRD §4 table against `@bp.get`/`@bp.post` decorators after normalising path params: **exact set equality, 28 GET + 27 POST both sides, zero missing, zero extra.**

## Smoke testing

Five suites (~150 assertions) on `PORT=51920`, each launched with `setsid bash start.sh`, the listener PID read from `ss -ltnp`, and killed by that exact PID (`kill 645548`, `649110`, `660236`, `662977`, `666007`) — no broad `pkill` at any point. Port confirmed free at the end. All five end at `FAILURES: 0`, covering: envelope/meta shape and `req_`+20-char ids; clock-start `2026-08-01T00:00:00.000Z` with 3-digit millis everywhere; auth rungs 1-3; duplicate identifiers; risk-score baseline/rolling variants, the 10.0 cap and all four interval tiers; the video gate's three conditions and its strict `< 6.0` boundary; OCC 412 including replay; overlap/rest-buffer (479 rejected, exactly 480 accepted)/720-minute window boundaries; float authorization; all five fitness gates; provisional vs per-segment final costing with the 1.15 night differential (`10350` for a 180-min segment from 00:00) and the AGENCY 1.45 multiplier (`46400`) and VOLUNTEER 0.00; break eligibility 120/15; handoff draft → countersign → `HANDOFF_SIGNED` → `HANDOFF_COMPLETE`, and `SHIFT_END_NO_SUCCESSOR` → `WAIVED` + `coverage_gap_flag`; both discontinuation branches with SoD and the REJECT clock restart; discharge and lapse cascades; ledger reversal semantics and unit-head recompute as a conserved quantity; span-of-control 409 and station offline gating; the incident-review cascade in PRD order with `SUSPENDED` applied last; escalate-response inertness; reassessment sweep marking then lapsing with the 6h grace; the surcharge tier 0.04 → `20800`; the agency block on a lapse-restricted unit and the budget-lift path; pagination defaults/limits and enum filter rejection.

## Genuinely ambiguous PRD passages and the interpretation chosen

1. **Rung 22 (span of control) vs rung 24 (duplicate active feed).** §3.7's prose narrates the duplicate-feed rule after the span rule but the §2.6 numbered ladder ranks span at 22. I followed the numbered ladder — a second feed on an over-capacity console reports `ERR_SPAN_OF_CONTROL_EXCEEDED`, verified in smoke.
2. **Rung 15 (recent safety event) vs rung 16 (segregation of duties) on `discontinuation-decision` APPROVE.** §3.9 narrates SoD first and the scaffold preconditions list it first; the ladder numbers it second. I evaluate the trailing-24h window first on the APPROVE branch, SoD second (SoD is still first and only check on REJECT).
3. **Ordering inside rung 8, which the PRD leaves unranked.** For start-watch I check order state before assignment state (the rung-8 error list and §3.5 both lead with the order). For handoff draft I check the three state preconditions before the rung-27 linkage check, so `outgoing == incoming` surfaces `ERR_INVALID_ASSIGNMENT_STATE` rather than `ERR_HANDOFF_ORDER_MISMATCH`.
4. **Query-shape failures vs path 404s on GETs.** §2 declares a bad filter enum a request-shape failure (rung 3) and existence is rung 4, so pagination/filter validation runs before the parent 404 on nested list endpoints.
5. **`monitor_end_at <= monitor_start_at`.** §3.7 requires "the end must be strictly later than the start" without naming an error id; there is no `ERR_INVALID_FEED_WINDOW` in the catalog, so I map it to `ERR_INVALID_REQUEST` (request-shape, rung 3).
6. **Whitespace-only `float_authorization_code`.** §3.10 rejects only "omitting it, or supplying an empty string". I took that literally: `""` is rejected, `"   "` is accepted as non-empty. This is the one place I'd expect a test to disagree; the fix would be a single `.strip()` in the scheduling route.
7. **No order-state gate on feed admission or event reporting.** §3.7/§3.8 list gates that never mention order status, unlike scheduling and start-watch which say so explicitly, so a feed or event on a terminal order is not blocked by the implementation.
8. **Empty arrays for `interventions_used` and `response_actions`.** The PRD declares non-empty/duplicate-free explicitly for `risk_categories` and `risk_categories_after` but not for these two, so `[]` is accepted (duplicates are still rejected).
9. **Expired certification submitted to a non-suspended observer.** §3.3 says both fields are written and only describes reinstatement as conditional, never a rejection, so `POST /staff/{id}/certifications` accepts an already-expired instant with 200 and simply leaves a `SUSPENDED` observer suspended (verified). No `ERR_DEESCALATION_CERT_EXPIRED` is raised on this endpoint — that rung belongs to scheduling and feed admission.
10. **Version bumps on derived-field-only mutations.** Derived figures are recomputed at read time in the serializers, but the PRD calls a derived-field change (e.g. a unit's `open_order_count`) a mutation of the row, so `touch()` still fires exactly once per row per request at those points; `void` bumps the assignment and unit but not the staff row, since no staff field or posture moves.

## Step 5: Generate unit tests — 2026-09-05T20:52:00.000Z

All 95 tests are in place and every audit is green.

## Files written

`test_helpers/` (Stage 1)
```
 61  __init__.py       343  api_client.py     123  api_errors.py
260  assertions.py     336  constants.py      385  factories.py
715  fixtures.py       117  test_users.py     188  types.py
```

`test_suite/` (Stage 2)
```
  18  conftest.py
 406  test_01_labor_cost_and_risk_score_variants.py     5 tests
 353  test_02_combinatorial_cost_formulas.py            4
 380  test_03_non_linear_state_machines.py              4
 436  test_04_transitive_cascades.py                    5
 329  test_05_validation_priority_conflicts.py          4
 374  test_06_boundary_precision.py                     5
 348  test_07_cross_entity_state_dependency.py          4
 431  test_08_resource_temporal_overlap.py              6
 431  test_09_compensating_invariants.py                6
 573  test_10_entity_shapes_and_lookups.py             10
 695  test_11_state_machine_edges.py                    8
 534  test_12_calculation_boundaries.py                 5
1116  test_13_validation_gates.py                       8
 625  test_14_endpoint_behaviours.py                    4
1381  test_15_error_codes.py                            8
1240  test_16_role_and_identity_enforcement.py          6
 581  test_17_cross_cutting_and_consistency.py          3
```
12,779 lines total across both directories. `__pycache__` removed from both.

## Tests per source queue

- **Queue A (§1.8 difficulty):** 43 tests covering all **18** live instances (each instance's recipe split into 2–3 focused tests, one `Design:` tag each) — test_01…test_09.
- **Queue B (§1.9 corner):** 52 tests, exactly **1 per live instance**, all 52 live instances covered — test_10…test_17. The 24 `excluded_because` stubs produced no tests, as required.

## Verification (all clean)

- `py_compile` + `pyflakes` exit 0 on every file.
- Citation audit: **non-verbatim citations: 0** (308 citations checked); section audit: **section mismatches/missing: 0**.
- Tag resolver against both yamls: 95 tags, **0 unresolved, 0 pointing at a stub, 0 live instances uncovered, 0 duplicate corner tags**.
- No `skip`/`skipif`/`xfail`/`pytest.mark` anywhere.
- Nothing written under `workspace/`; `workspace/implementation/` never created, read, written or listed; `worklog.md` untouched; no server started; no `pkill`; scratch confined to `/tmp/task2920_tests/`.

## Instances SKIPPED

**None.** Every live instance in both indices passed the two-condition PRD filter and produced at least one test. Adjustments where the design recipe and the PRD disagreed and the PRD won:

Dropped sub-assertions (non-uniquely-derivable — the rest of the instance still carries its distinguishing aspect):
1. `Corner/rbac/a_sitter_holding_both_watches_cannot_countersign_their_own_handoff` — probes 3–4 dropped: drafting needs that watch `ON_WATCH`, but §3.5 rung 9 refuses a start-watch for an observer already `ON_ASSIGNMENT`, and the only escape (completing watch 1) posts FINAL_SEGMENT rows that destroy the instance's own "48000 == three PROVISIONAL rows of 16000" assertion. Probes 1–2 alone prove rung 6 before rung 16.
2. `Corner/…/handoff_incoming_watch_must_sit_on_the_outgoing_watchs_order` — probe 2 dropped: rung 8 (state) fires before rung 27, so the recipe's expected error is unreachable.
3. The float instance's `float_authorization_code == "FLOAT-7788"` echo dropped: PRD never enumerates the assignment response's float fields.

Recipe values corrected to the PRD's derivation:
4. `Corner/entities/new_order_starts_active_with_the_admission_baseline_variant` — recipe says risk 3.5; §3.3 derives **4.5** (FALL 1.5 + ELOPEMENT 2.5 + age ≥75 +1.0). Asserted 4.5.
5. `Corner/…/cost_close_subtotal_excludes_reversed_and_boundary_entries` — recipe hard-codes `unit_version == 2`; PRD does not fix an absolute number, so asserted `close["unit_version"] == read_unit(...)["version"]`.
6. Two handoff instances start the outgoing watch first and assert `ON_WATCH` / `countersigned_at == 2026-08-01T08:00:00.000Z`: §3.6 requires the outgoing watch to be `ON_WATCH` or `ON_BREAK`, which the recipes' `SCHEDULED` posture contradicts.

**Orchestrator verification:** confirmed `test_helpers/` and `test_suite/` sit at the task root with no stray copies under `workspace/` (a known failure mode of this step); `python3 -m pytest test_suite/ --collect-only -q` reports **95 tests collected** with zero collection errors; 95 `Design:` tags found (one per test); zero `pytest.mark` occurrences.

## Step 7: Run tests and iterate — 2026-09-05T21:05:00.000Z

All green. `worklog.md`, `PRD.md`, and `SCAFFOLD.yaml` are untouched (mtimes predate the fix session), and the only file modified is the one test.

## Summary

**Iterations run:** 2 sweeps (8 rounds each, 16 runs total).

**Sweep 1 result:** 94/95 in every one of the 8 rounds — a single deterministic failure, identical in all rounds, so definitionally a real defect rather than CPU contention:

```
test_09_compensating_invariants.py::TestVoidReturnsTheUnitLedgerHeadToZero::
  test_the_voided_watch_keeps_the_figure_it_was_charged
AssertionError: the voided watch.final_cost_cents must be an integer count of cents, got None
```

**Tests deleted:** none. The single failure survived STEP 1 (PRD covers `final_cost_cents` on both the create and the void path verbatim) and was resolved at STEP 2 as a test bug.

**Fixes applied to `test_suite/`** (1):

- `test_suite/test_09_compensating_invariants.py`, `TestVoidReturnsTheUnitLedgerHeadToZero::test_the_voided_watch_keeps_the_figure_it_was_charged` — the assertion expected `final_cost_cents=0` on a voided watch; PRD requires `None`. Changed to `final_cost_cents=None` and rewrote the docstring rationale to cite the two governing sentences.

**Why the test was wrong, not the implementation.** PRD §3.4 lands a new assignment with "`final_cost_cents`, `current_segment_started_at`, `break_started_at`, `completion_reason` and `voided_at` all null", and §3.5's void paragraph enumerates the void's effects exhaustively — "Voiding stamps `voided_at`, moves `documentation_status` `PENDING → WAIVED`, and sets the assignment's `PROVISIONAL` ledger row to `REVERSED`" — without naming `final_cost_cents`. The only writer of that field in the PRD is a completion ("`final_cost_cents` is then set to the sum of `amount_cents` across this assignment's `FINAL_SEGMENT` rows"), which a never-started watch never reaches. So `None` is the unique PRD-faithful value and the implementation (`services.system_void_assignment`) was already correct. This was the minority-symbol masquerade from the triage hints: the sibling assertions at `test_11_state_machine_edges.py:675`, `test_13_validation_gates.py:252`, `test_15_error_codes.py:578`, `test_17_cross_cutting_and_consistency.py:535` and `test_01:155` all already expected `None`, so the one outlier was made to match the majority rather than teaching the implementation to zero the field.

**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `implementation/`:** none — no implementation defect was found; all 14 modules are unmodified.

**Note on the three flagged ambiguities.** None of them was implicated. No test collided with the whitespace-only `float_authorization_code` reading, the span-of-control vs duplicate-active-feed rung order, or the order-status gating of feed admission / event reporting, so the implementation generator's recorded readings stand unchallenged by the suite.

**Final tally: 95 / 95 passing.** All 8 `results.$i.json` from the final sweep show `passed == total == 95, failed == 0`.

**Orchestrator verification (independent):** parsed all 8 `results.$i.json` myself — every round reports `95 / 95`; mtimes all 20:47 and the `SWEEP_DONE` sentinel is present, so this was a genuine complete 8-round sweep, not stale artifacts. The sweep was run from the pre-written `workspace/sweep.sh` under `setsid nohup` with a `SWEEP_DONE` sentinel, which is why no reaping (`Terminated` server logs / synchronised round deaths) occurred and no relaunch-on-early-return happened.

**Step 8 skip decision:** NOT skipped. The skill's skip condition requires zero deletions AND zero `test_suite/` fixes AND zero `test_helpers/` fixes AND zero `implementation/` fixes. Step 7 made 1 `test_suite/` fix, so the condition is not met and Step 8 runs. Note the expected outcome, however: the single fix was a test-side correction at a site where the PRD *already* uniquely determined the value (`final_cost_cents` stays null on a void), i.e. a pure test-artifact bug rather than a PRD silence or PRD/impl mismatch. Step 8 is therefore likely to be a no-op or near-no-op, and a byte-identical `PRD_FINALIZED.md` is a legitimate result for Step 8 specifically (it is only Step 9 that must never be identical). Step 8 is instructed to patch only where impl pinned a choice PRD left open, so it should decline to invent an edit here.

## Step 8: Finalize PRD — 2026-09-05T21:12:00.000Z

Step 8 complete. `PRD_FINALIZED.md` is byte-identical to `PRD.md` — the single Step 7 item was a pure test-artifact bug at a site the PRD already uniquely determines, so there was nothing to pin.

**Line counts:** PRD.md 428 lines / 93,789 bytes; PRD_FINALIZED.md 428 lines / 93,789 bytes. **Delta: 0.0%** (identical md5 `6e5589fd…`).

**Changes:** none.

**Pre-edit search log (for the one candidate edit considered and rejected):**

- (a) **Subject identified:** the value of `final_cost_cents` on an assignment that reaches `VOIDED` without ever starting a watch (the Step 7 failure site).
- (b) **Impl paths enumerated** — `grep -rn "final_cost_cents" implementation/*.py` returned exactly four sites, all read in full:
  - `routes_assignments.py:127` — the create/schedule handler seeds `"final_cost_cents": None` alongside `voided_at: None`.
  - `routes_assignments.py:263` — the caller-driven completion handler (`ON_WATCH → COMPLETED`) sets it from `calc.final_cost_from_ledger(assignment)` after `close_open_segment` + `reverse_provisional`.
  - `services.py:208` — `system_complete_assignment` (the `ORDER_DISCONTINUED` cascade completion) sets it the same way.
  - `serializers.py:103` — pass-through in `assignment_json`, no defaulting or coalescing to 0.
  - Plus the void writer itself, `services.py:190` `system_void_assignment` (reached from the `POST …/void` route at `routes_assignments.py:284` and from `discontinue_order` at `services.py:229`): it writes `watch_status`, `voided_at`, `waive_documentation`, `reverse_provisional`, `touch` — and never touches `final_cost_cents`, so the field keeps the `None` it was seeded with. Both void entry points share this one writer, so there is no divergent void path.
- (c) **Wording adjustment:** none needed — no edit was made. PRD §3.4 (line 227) already lands the row with "`final_cost_cents` … all null"; §3.5's void paragraph (line 252) enumerates the void's effects exhaustively without naming the field; and the field's only PRD-sanctioned writers are the two completion paths (§3.5 line 250, §3.9 lines 304/308), none of which a never-started watch reaches. `None` is therefore the unique PRD-faithful value and the implementation already matches. Editing here would have added a redundant (and possibly narrowing) sentence for zero alignment gain.

No PRD silence or PRD/impl mismatch existed in the diff's scope. `PRD.md`, `implementation/`, `test_suite/`, `test_helpers/` and `worklog.md` were untouched; no `pkill` was run.

**Orchestrator note:** a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 result — Step 8's scope is hard-bounded to the `<step_7_diff>` items, and this diff's sole item was a test-artifact bug rather than a PRD silence or PRD/impl mismatch. Manufacturing an edit to look productive would have violated Step 8's HARD SCOPE and NO-NEW-MISMATCH rules. The identical-output constraint applies to Step 9, not Step 8, and Step 9 is where the residual silences the test suite never asserted get closed.

## Step 9: Complete PRD — 2026-09-05T21:13:00.000Z (launched, 3 sequential passes)

Step 9's scan is the pipeline's only exhaustive PRD-vs-impl comparison, and running it as one subagent over 3,059 lines of implementation reliably under-scans (a prior symptom: `PRD_COMPLETED.md` coming back byte-identical to its source, proving the walk never happened). It is therefore split into three **sequential** passes, each partitioned by implementation module, all editing the one shared `workspace/PRD_COMPLETED.md`:

- **Pass 1** — `app.py`, `db.py`, `errors.py`, `response.py`, `validation.py`, `serializers.py` (envelope/meta shape, error-id→status mapping, the validation ladder's mechanics, common fields and version bookkeeping, response field shapes and null/omission conventions). Pass 1 alone performs the `cp PRD_FINALIZED.md PRD_COMPLETED.md`.
- **Pass 2** — `calc.py`, `services.py` (all formulas, rounding, thresholds and tiers; cascade ordering; system-initiated state transitions).
- **Pass 3** — `routes_core.py`, `routes_orders.py`, `routes_assignments.py`, `routes_stations.py`, `routes_events.py`, `routes_reads.py` (per-endpoint gating order, RBAC/ownership scoping, pagination and filter semantics, request-shape acceptance, per-route side effects).

Passes 2 and 3 are explicitly forbidden from re-running the `cp`, which would discard the previous pass's edits. Sequential rather than concurrent for the same reason: three agents editing one file concurrently would clobber each other.

## Step 9: Complete PRD — 2026-09-05T22:05:00.000Z

Three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`. Final: **435 lines / 117,725 chars** vs the 428-line / 93,789-char source (`PRD_FINALIZED.md`) — **+7 lines, +23,936 chars (+25.5%)**, 103 changed lines. Total across passes: **54 ambiguity-pins, 7 mismatch-revisions**.

### Pass 1 — app.py, db.py, errors.py, response.py, validation.py, serializers.py
+3 lines / +7,350 chars. 13 ambiguity-pins, 2 mismatch-revisions. Pass 1 performed the one `cp PRD_FINALIZED.md PRD_COMPLETED.md`.
- **§2.1** — revise — mismatch — PRD said only an empty-string header counts as absent; impl (`validation.py:28-31`) also treats whitespace-only as absent. Also pinned case-sensitive role matching with no trimming — `validation.py:26-33`
- **§2.2** — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A–Z0–9` (24 total) — `response.py:10-14`
- **§2.2** — insert — ambiguity — `api_request_timestamp` comes from the host's real clock, not the logical clock — `response.py:20`
- **§2.2** — insert — ambiguity — resource objects always carry every declared field, absent values as explicit JSON `null`, never omitted — `serializers.py:14-209`
- **§2.2** — revise — mismatch — error envelope is emitted for 5xx as well as 4xx — `app.py:54-56`
- **§2.2** — insert — ambiguity — messages non-contractual; HTTP-layer failures use the same envelope with ids outside §5 (`ERR_NOT_FOUND`/404, `ERR_METHOD_NOT_ALLOWED`/405, `ERR_INVALID_REQUEST`/400, `ERR_INTERNAL`/500); trailing slashes insignificant — `app.py:24, 41-56`
- **§2.3 ¶1** — insert — ambiguity — out-of-range `limit` rejected not clamped; non-integer literals rejected; negative `offset` rejected but no upper bound; empty-string params fall back to defaults; `created_at` ties broken by ascending creation order — `validation.py:184-205`, `db.py:219-220`, `services.py:40-42`
- **§2.3 ¶2** — insert — ambiguity — reported `limit`/`offset` are post-default effective values; `total_count` is post-filter pre-paging; `has_more` ⇔ `offset + len(page) < total_count` — `response.py:29-36`
- **§2.3 ¶3** — insert — ambiguity — empty-string filter narrows nothing; enum filters exact/case-sensitive; `home_unit_id`/`patient_id` exact string equality with no 404 for unknown ids; undeclared query params ignored — `validation.py:208-222`, `routes_reads.py:158,167`
- **§2.4 ¶1** — insert/revise — ambiguity — `id` is a lowercase UUIDv4; rendered instants are 3-fraction-digit `Z` form with sub-millisecond parts **truncated** not rounded; `updated_at` equals `created_at` on a fresh row — `db.py:139-161, 250-261`
- **§2.4** — insert — ambiguity — the 12 derived fields are recomputed from the store on every read, not stored; storage process-local and in-memory, empty at boot — `serializers.py:23-127`, `db.py:114-136`
- **§2.6 rung 3** — insert — ambiguity — the full generic-validator contract: no type coercion; JSON `null` == omitted; no trimming in length/non-empty checks (whitespace-only passes, only `""` fails `float_authorization_code`/`review_findings`); non-empty+duplicate-free bind only `risk_categories`/`risk_categories_after` while `interventions_used`/`response_actions` accept empty and duplicates; member order preserved; undeclared keys ignored; absent/empty body == `{}`; non-object JSON rejected; `Content-Type` never consulted; and the exact accepted ISO-8601 grammar (`T`/`t`/space separator, optional seconds, 1–9 fractional digits with `.` or `,`, optional `Z`/`z`/`±HH:MM`/`±HHMM` defaulting to UTC; date-only, non-string and impossible dates rejected) — `validation.py:42-178`, `db.py:164-193`
- **§2.7** — insert — ambiguity — risk scores and acuity weights are JSON numbers, never strings, and render a zero decimal as `4.0` — `serializers.py:7-11`
- **§2.9 ¶1** — insert — ambiguity — `version` increments once per row per request regardless of hop count; `updated_at` set once from the logical clock; a row created by the same request is exempt — `db.py:228-261`
Cross-check: §5 catalogue compared row-by-row against `errors.py:ERROR_HTTP` — all ids and statuses match, no catalogue revision needed.

### Pass 2 — calc.py, services.py
+0 lines / +3,554 chars (all in-paragraph, hence no line growth). 9 ambiguity-pins, 1 mismatch-revision. Did not re-copy the file.
- **§3.3** — insert — ambiguity — the sweep runs in full even on a `current_utc` equal to the current clock, so it does not depend on the clock advancing — `services.py:259`, `routes_events.py:205-211`
- **§3.3** — insert — ambiguity — orders are the only rows the sweep examines: no assignment auto-completes at `shift_end_at`, no feed auto-releases at `monitor_end_at` — `services.py:259-278`
- **§3.3** — insert — ambiguity — an already-`RESTRICTED` unit keeps its existing `restriction_reason` and does not advance `version`; lapsing touches no assignment, closes no segment, moves no ledger row, does not re-evaluate the budget — `services.py:119-126, 248-253`
- **§3.3** — **revise — mismatch** — PRD claimed the rolling reading is "strictly higher whenever any safety event exists"; impl gives an equal score when the only events are escalating kinds aged out of the 24h window, or when the category+age total already hits the 10.0 cap — `calc.py:218-247`
- **§3.5** — insert — ambiguity — the `PROVISIONAL` row stays `POSTED` at break-start (reversed only at completion/void), so the ledger head carries provisional and closed segments simultaneously — `services.py:81-106` vs `200-215`
- **§3.5** — insert — ambiguity — a zero-minute segment still posts a `FINAL_SEGMENT` row (`segment_minutes` 0, `amount_cents` 0) and consumes the next `segment_index` — `services.py:86-104`
- **§3.9** — insert — ambiguity — the system void stamps `voided_at` and leaves `final_cost_cents` null — `services.py:190-197`
- **§3.9** — insert — ambiguity — completion clears both `current_segment_started_at` and `break_started_at`; a `SUSPENDED` observer is not reinstated; `coverage_gap_flag` is not set by this cascade — `services.py:200-215`
- **§3.9** — insert — ambiguity — hops are two separate passes (order row → `SCHEDULED` voids by `created_at` → running completions by `created_at` → feeds → unit), and the unit hop fires **only** when at least one ledger row moved — `services.py:221-242`
- **§3.9** — insert — ambiguity — each discharged patient's order cascades in the same pinned sequence, feeds after watches, conditional unit hop last — `routes_core.py:143` → `services.py:221-242`
Left already-pinned and untouched: score formula and 10.0 cap-before-round, four interval tiers and their inclusive senses, the video gate's strict `< 6.0`, `is_night`'s 23:00–06:59-by-segment-start rule, provisional (round once) vs per-segment final (round per segment) costing, `whole_minutes` flooring, acuity-weight/span-penalty/`SPAN_FLOOR` arithmetic, aggregate span occupancy, the three surcharge tiers, the strict `posted_at < close_through_utc` bound, full-recompute ledger head, `shift_peers`' VOIDED exclusion, the sweep's sort key and one-transition-per-order rule.

### Pass 3 — routes_core.py, routes_orders.py, routes_assignments.py, routes_stations.py, routes_events.py, routes_reads.py
+4 lines / +13,032 chars. 32 ambiguity-pins, 4 mismatch-revisions. Did not re-copy the file; verified pass-1 and pass-2 signature strings still present.
- §2.1 — insert — ambiguity — caller's own `Staff` row resolved at the ownership rung, so a resource 404 beats `ERR_STAFF_NOT_FOUND` — `services.py:17-34`, `routes_events.py:62`
- §2.3 — insert — ambiguity — query-string shape (rung 3) precedes parent path 404 (rung 4) on nested listings — `routes_reads.py:69-73`
- §2.6 rung 3 — insert — ambiguity — among several malformed fields the endpoint's first-declared field wins — `routes_assignments.py:49-54`
- §2.8 — insert — ambiguity — `expected_order_version` has no declared range; 0/negative clears rung 3 and fails rung 7 — `routes_assignments.py:53`
- §3.1 — insert — ambiguity — admitting a patient / registering staff / opening a console touches no referenced row — `routes_core.py:108,163`, `routes_stations.py:39`
- §3.1 — revise — ambiguity — a `SUSPENDED` observer with a non-current expiry keeps the suspension, both fields still written — `routes_core.py:190-196`
- §3.2 — insert — ambiguity — `ordering_provider_user_id` stored verbatim, never compared to `X-User-ID`; unit posture/budget not consulted; concurrent orders per patient allowed — `routes_orders.py:45,64`
- §3.3 — insert — ambiguity — order-state gate precedes the patient gate, making `ERR_PATIENT_DISCHARGED` unreachable at reassessment — `routes_orders.py:99-104`
- §3.4 — insert — ambiguity — `required_modality` not consulted; overlapping watches per order allowed across different observers — `routes_assignments.py:84-96`
- §3.4 — insert — ambiguity — shift-window sanity (rung 19) sits below the overlap/rest-buffer rules — `routes_assignments.py:84-98`
- §3.4 — insert — ambiguity — float code stored verbatim even when not required; null when omitted — `routes_assignments.py:123`
- §3.5 — insert (new ¶) — ambiguity — break-start/break-end/complete/void read no order status and no duty posture — `routes_assignments.py:201,229,253,289`
- §3.5 — **revise — mismatch** — start-watch also refuses `DISCONTINUATION_REVIEW`, not just terminal; order-state gate precedes assignment-state gate — `routes_assignments.py:174-177`
- §3.5 — insert — ambiguity — break-end touches neither observer nor unit — `routes_assignments.py:236-240`
- §3.5 — insert — ambiguity — caller-supplied `ORDER_DISCONTINUED` is `ERR_INVALID_REQUEST` at rung 3 — `routes_assignments.py:250`
- §3.5 — insert — ambiguity — a `SUSPENDED` observer stays suspended at completion but is still touched — `routes_assignments.py:271-274`
- §3.5 — insert — ambiguity — `coverage_gap_flag` is never cleared once true — `routes_assignments.py:267-269`
- §3.5 — insert — ambiguity — void touches neither the observer (despite `last_shift_end_at`) nor the order — `routes_assignments.py:291-293`
- §3.6 — insert — ambiguity — the four draft gates run in the documented order, doc-state first; incoming assignment never written; two outgoing watches may name one incoming — `routes_assignments.py:317-325`
- §3.6 — revise — ambiguity — outgoing always touched, incoming untouched, `countersigned_by_staff_id` = raw `X-User-ID` — `routes_assignments.py:364-370`
- §3.7 — insert — ambiguity — console creation applies no observer fitness gate and touches no row — `routes_stations.py:36-47`
- §3.7 — insert — ambiguity — feed window sanity is rung-3 `ERR_INVALID_REQUEST`, ahead of both 404s — `routes_stations.py:85-87`
- §3.7 — insert — ambiguity — **deferred (b)**: the three-condition modality gate is exhaustive; neither `required_modality` nor order status is consulted — `routes_stations.py:107-110`
- §3.7 — **revise — mismatch** — span of control (rung 22) is evaluated before duplicate-active-feed (rung 24), reversing the prose order — `routes_stations.py:111-120`
- §3.7 — insert — ambiguity — station version advances on every admission; the order is not mutated — `routes_stations.py:132-138`
- §3.8 — insert — ambiguity — **deferred (b)**: the cited assignment need not belong to the order and may be in any `watch_status`; reporting is not gated on order status at all — `routes_events.py:54-64`
- §3.8 — insert — ambiguity — escalation fires only from `ACTIVE`/`REASSESSMENT_DUE`; every other status leaves the order and its version alone — `routes_events.py:82`
- §3.8 — insert — ambiguity — `response_actions` is required though it may be empty — `routes_events.py:95`
- §3.8 — insert — ambiguity — the incident-review cascade is unconditional on order status; suspension applies from any posture; the assignment row is never mutated — `routes_events.py:126-143`
- §3.8 — **insert — mismatch** — segregation of duties (rung 16) is reached before `ERR_REVIEW_FINDINGS_REQUIRED`, reversing the prose order — `routes_events.py:161-169`
- §3.8 — insert (new ¶) — ambiguity — **deferred (a)**: closure's three order reach-backs are unconditional on order status — `routes_events.py:176-192`
- §3.9 — insert — ambiguity — review-open state gate precedes the reassessment-count gate; no SoD, patient or window check — `routes_orders.py:137-142`
- §3.9 — insert — ambiguity — `rationale` is validated then discarded, persisted and echoed nowhere — `routes_orders.py:158`
- §3.9 — insert — ambiguity — the trailing-24h window counts events whatever their own status, `CLOSED` included — `routes_orders.py:169-172`
- §3.9 — insert — ambiguity — `budget_increase_cents` must be ≥ 0; the close is gated on nothing but role and unit existence — `routes_core.py:66-73`
- §4 table — **revise — mismatch** — `/sitter-assignments/{id}/safety-events` filters on the event's own `assignment_id`, not on the shift window — `routes_reads.py:348-349`

### Deferred items resolved
**(a) `routes_events.py:183-192`** — confirmed no non-terminal guard. A new §3.8 paragraph pins that all three reach-backs (un-escalation; score/variant/interval/`next_reassessment_due_at` recompute; `MODALITY_ESCALATED` modality forcing + feed release) run on a `DISCONTINUED` or `LAPSED` order too, explicitly contrasted with `complete_watch`'s guarded `coverage_gap_flag`. Also pinned that the order's `version` advances on *every* close, because the recompute always rewrites `risk_score_variant`.

**(b) Order-status gating of feed admission and event reporting** — confirmed **neither is gated on order status**. `admit_feed` never reads `order["status"]` and its modality gate (`calc.video_permitted`) reads only the unit flag, `SELF_HARM` membership and the persisted score — so it does not read `required_modality` either. `report_event` reads `order["status"]` only inside the escalation branch. Both pinned inline in §3.7 and §3.8 as exhaustive gate lists plus an explicit "and the order's status never".

### Other flagged items
- Whitespace-only `float_authorization_code` at scheduling: already pinned by pass 1 at rung 3 and consistent with §3.4 — no further change (`routes_assignments.py:106`).
- Span-of-control vs duplicate-active-feed: impl follows the numbered ladder (22 then 24); the §3.7 *prose* had them backwards, so the prose was revised.
- `base_entity(versioned=False)` at `routes_orders.py:111`: already pinned by pass 1 at §2.4 and confirmed against `serializers.reassessment_json` — no change needed.

### Orchestrator final verification
- `PRD_COMPLETED.md` = 435 lines / 117,725 chars; `cmp` against `PRD_FINALIZED.md` **differs** (103 changed lines), so the scan genuinely ran — the byte-identical failure mode did not occur. Note that pass 2 contributed **+0 lines but +3,554 chars**, which is why char-delta rather than line-delta is the reliable completeness signal for this step.
- All five top-level sections (§1–§5) present and in order; 28 headings; document ends on a complete markdown table row in §5, not mid-sentence.
- Leak scan for `harder than expert|SCAFFOLD|test_recipe|excluded_because|difficulty_instance` over `PRD_COMPLETED.md`: **zero hits**.
- `find` confirms **no `.py` file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` was modified after `results.1.json` was written**, so the green 8-round sweep (95/95 × 8) still describes exactly the code and tests being shipped. Steps 8 and 9 touched only PRD derivatives, as required.

**PIPELINE COMPLETE.**
