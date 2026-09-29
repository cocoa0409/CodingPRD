# Worklog — task_2939_venue_music_performance_licensing_repertoire_reporting

## Step 1: Create task directory — 2026-09-05T19:03:27.415Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2939_venue_music_performance_licensing_repertoire_reporting` and `workspace/` (pre-assigned path from the orchestration args; no index scan performed, since up to 32 pipelines run concurrently on this host and auto-allocation would collide).

## Step 2: Generate scaffold (prd-bench-scaffold-generator subagent) — 2026-09-05T20:29:25.555Z

Step 2 scaffold generation for task 2939 is complete. All three files are written, parse under `yaml.safe_load`, and the linter is clean.

**Lint verdict (verbatim)**
```
Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     11
  §1.8 instances scanned:     19
  §1.9 instances scanned:     70
  Calls scanned (§1.8+§1.9):  935

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Deliverables** (in `/home/ubuntu/github/CodingPRD/tasks/task_2939_venue_music_performance_licensing_repertoire_reporting/`)
| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 1901 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1632 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4253 |

**SCAFFOLD.yaml counts** — 13 top-level keys (no `scaffold_*_design` keys): 11 entities, 8 state machines, 2 concurrency rules, 13 calculations, 23 validations (46 rule rows in total across those four tables), 54 endpoints, 40 errors, 4 roles. Complexity profile: flat topology, cyclic state machines, `segregation_of_duties`, `immediate` consistency, layers = dual_variant_calculation / cascading_side_effects / rate_threshold_triggers / optimistic_concurrency.

**§1.8** — 9 rules / 19 instances (one pair per rule, plus a third for `combinatorial_formula` and `non_linear_state_machine`).

**§1.9** — 9 sections / 105 instances (70 with full `test_recipe`, 35 `excluded_because` stubs, every cited `difficulty_instance` resolving to a real §1.8 name; no name collisions across the two design files): entities 11, state_machines 14, calculations 24, validations 26, endpoints 14, errors 3, rbac 4, cross_cutting_complexity_layers 7, consistency_model 2.

**Internal defects found in SCAFFOLD.yaml and fixed while grounding §1.9 asserts**
- `ERR_REVISION_LIMIT_EXCEEDED` was untriggerable: §1.2/§1.5 make a 4th `RETURN_FOR_REVISION` auto-DECLINE with `decline_reason REVISION_LIMIT_EXCEEDED`, while validation 19 claimed a 409. Removed the error, scoped validation 19 to `ERR_DISPUTE_LIMIT_REACHED`, and re-pointed the corresponding §1.9 stub (errors now 40).
- Validation 16 checked a nonexistent field `renewed_into_license_id`; retargeted to the declared `renewal_issued_at` (this was also the single lint violation, via a capture path).
- `PerformanceReport.period_end` was documented as an inclusive/closed interval while every validation treats `[period_start, period_end)` as half-open; made the field half-open.
- Activate's side effects said a FeeAssessment is issued unconditionally, contradicting §1.2's `license_type != BGM_EXEMPT` carve-out, and used `term_start + 30 days` for `due_date` against §1.1/§1.2's clock-instant + 30 days. Both aligned to §1.2, and the BGM §1.9 assert tightened to "no assessment, billing_status stays UNBILLED".
- `MAX_REVISION_ROUNDS` / `MAX_DISPUTE_ROUNDS` had no numeric values (now inlined as 3 and 2 in the checks, error conditions and preconditions).
- A §1.9 instance used `venue_category: THEATER`, outside the declared enum (now `HOTEL`); another posted a duplicate `ANNUAL_TERM` coverage window that activation already auto-creates (rewritten around a `SEASONAL_EVENT_RIDER`, covered_day_count 15).

Scratch was confined to `.scratch/step2/` and deleted at the end (parent `.scratch/` left in place); `worklog.md` (5 lines) and `workspace/` were not touched.

**Orchestrator verification**: all three files present (1901 / 1632 / 4253 lines). Difficulty-directive leak check ran `grep -rniE "harder than expert|expert level"` across all three scaffold files — no matches, so no strip was needed.

## Step 3: Copy shared files — 2026-09-05T20:29:25.555Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (prd-bench-doc-generator subagent) — 2026-09-05T20:47:23.704Z

PRD.md is complete and verified.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2939_venue_music_performance_licensing_repertoire_reporting/workspace/PRD.md`

- **524 lines, 112,264 bytes**
- Built incrementally across 13 appends (one `Write` + 12 heredoc `cat >>`), so no chunk approached the 64k output cap.

## Top-level sections, in order

1. `# Venue Music Licensing API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 Acting Users, Roles and Identity · 2.2 API Response Structure · 2.3 Pagination · 2.4 The Logical Licensing Clock · 2.5 Row Identity, Timestamps and Revision Counters · 2.6 Cents, Basis Points and the Rounding Discipline · 2.7 Stale-Parent Guards on Application Filing and Renewal · 2.8 Half-Open Intervals and Left-to-Right Path Resolution · 2.9 The Venue Fee Ledger and the Delinquency Tolerance · 2.10 Multi-Society Coverage Posture and Gap Risk · 2.11 Cascade Discipline and the Two Licence State Dimensions · 2.12 The Order in Which Requests Are Rejected
4. `## 3. Business Logic & Workflows` — 3.1 Societies and the Registered Repertoire · 3.2 Rate Schedules and the Rate-Change Cascade · 3.3 Venue Survey Records and the Background-Music Exemption · 3.4 Filing, Revising and Reviewing a Licence Application · 3.5 How the Annual Fee Is Derived · 3.6 Activating Coverage: Annual Terms, Windows and Riders · 3.7 Suspension, Reinstatement, Termination and Renewal · 3.8 Setlist Reporting and the Repertoire Gap Cascade · 3.9 Audit Cases, Settlement Negotiation and Collecting the Money
5. `## 4. Endpoint Definitions`
6. `## 5. Error Code Catalogue`

**Tail completeness:** the file ends at `| ERR_PAYMENT_EXCEEDS_BALANCE | 409 |` — the last row of the §5 table, a real section boundary. No audit footer, no truncated sentence, no partial table row.

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** 135 of 135 `entities[].fields[].name` identifiers appear verbatim in backticks; 85 of 85 endpoint `input` / path-parameter identifiers (optional `?` markers stripped) appear verbatim in backticks. 0 missing.

**Contract 2 — Rule Coverage: PASS.** All 40 catalogued error identifiers appear in the document; all 23 priority-ordered validations are rendered as the numbered ladder in §2.12 with their `applies_to` sets enumerated endpoint by endpoint (the only checker flags were pipe-joined multi-id validation rows, each constituent id individually confirmed present). All 38 declared state transitions and every state name across the 6 state machines are covered in §3.2–§3.9. Both `concurrency_rules` (`expected_venue_version` / `ERR_STALE_VENUE_VERSION`, `expected_license_version` / `ERR_STALE_LICENSE_VERSION`) are described in §2.7 with their 412 semantics. All 65 endpoint `side_effects` clauses are covered; the only identifiers not present verbatim are the 13 scaffold-internal calculation *names* (`annual_license_fee`, `final_verified`, `repertoire_gap_share`, `settlement_target`, `back_license_exposure`, `rate_schedule_selection`, etc.), which are deliberately expressed as prose logic rather than named symbols — their output fields are all covered under Contract 1. Sibling-branch symmetry is stated explicitly for the four asymmetric pairs (provisional vs verified fee, unmatched vs uncovered share, full vs part payment, findings vs close).

**Contract 3 — §3 Path Purity: PASS.** §3 spans lines 207–417 and contains 258 distinct backticked tokens; 0 begin with `/`, 0 are a bare HTTP method, 0 combine method with path, and 0 embed a URL path fragment. Method-and-path strings appear only in §2.7, §2.12 and the §4 table, where they are needed to pin `applies_to` scopes unambiguously.

## Other checks

- §2.2 is byte-identical to `section-2.2-response-structure.md` (verified by `diff`), including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING` and `"data": { }`.
- §4 table holds exactly 54 rows matching the 54 scaffold endpoints — no missing rows, no invented ones.
- Zero occurrences of difficulty meta-text, internal cascade labels (`CASCADE-A`/`CASCADE-B`), scaffold section references (`§1.x`), Hard Contract/PASS text, or fuzzy quantifiers (`approximately`, `roughly`, `conservatively`).
- Scratch dir `.scratch/step4/` was used and removed with `rm -rf .scratch/step4` only; `.scratch/` itself, `worklog.md`, `INSTRUCTION.md` and all `SCAFFOLD*.yaml` files were untouched. Neither design index was read.

## Scaffold inconsistencies resolved (implementer-visible choices)

Where SCAFFOLD.yaml contradicted itself I followed the majority of sources so the PRD is self-consistent: licence termination departs from ACTIVE or SUSPENDED (per validation 8 and the error condition); application withdrawal departs from DRAFT, SUBMITTED or RETURNED_FOR_REVISION (per the state machine); application creation supersedes any prior row in DRAFT, SUBMITTED, UNDER_REVIEW or RETURNED_FOR_REVISION (the broader state-machine set). Three preconditions with no declared error id are stated as preconditions without inventing identifiers. `gap_exposure_cents`, which had a description but no formula, is specified as `annual_fee_cents` times `uncovered_share_pct` divided by 100, rounded half up.

**Orchestrator verification (truncation guard) [Step 4]**: independently ran `wc -l -c`, `grep -n '^#'`, and `tail -25` on PRD.md. 524 lines / 112264 bytes; 28 headings ending at `## 5. Error Code Catalogue`; tail ends on the final complete table row `| ``ERR_PAYMENT_EXCEEDS_BALANCE`` | 409 |`. Not truncated — no regeneration needed. Difficulty-leak grep over PRD.md also clean.

## Step 5: Generate unit tests (prd-bench-unit-test-generator subagent) — 2026-09-05T21:55:17.808Z

Launched concurrently with Step 6 in a single assistant message, so the implementation generator was physically unable to read `test_suite/` (the directory did not exist when it started).

Step 5 complete and verified.

## Deliverables

**`test_helpers/`** (task root, Stage 1 — written earlier, unchanged this pass, 2767 lines total)
`__init__.py` 175 · `api_client.py` 439 · `api_errors.py` 118 · `assertions.py` 382 · `constants.py` 295 · `factories.py` 544 · `fixtures.py` 481 · `test_users.py` 124 · `types.py` 209

**`test_suite/`** (task root, Stage 2 — 18 test modules + pre-existing `conftest.py` (28), 9704 lines, **127 tests**)

| File | Lines | Tests |
|---|---|---|
| test_01_license_fee_and_gap_share_variants.py | 451 | 6 |
| test_02_audit_exposure_and_settlement_waterfall.py | 432 | 7 |
| test_03_application_revision_and_license_dimensions.py | 315 | 6 |
| test_04_rate_publication_and_report_submission_cascades.py | 464 | 6 |
| test_05_validation_priority_conflicts.py | 386 | 6 |
| test_06_cross_entity_gating.py | 395 | 6 |
| test_07_coverage_and_gap_risk_boundaries.py | 443 | 7 |
| test_08_licence_terms_and_rider_window_overlap.py | 450 | 7 |
| test_09_ledger_and_coverage_invariants.py | 456 | 6 |
| test_10_row_shapes_and_registry_reads.py | 584 | 11 |
| test_11_lifecycle_transition_guards.py | 586 | 7 |
| test_12_exemption_and_fee_derivation_corners.py | 517 | 5 |
| test_13_gap_risk_selection_and_rollup_corners.py | 974 | 9 |
| test_14_request_shape_and_reference_validations.py | 603 | 9 |
| test_15_temporal_and_fiscal_validations.py | 849 | 10 |
| test_16_endpoint_behaviour_contracts.py | 716 | 8 |
| test_17_error_resolution_and_access_control.py | 622 | 8→7 |
| test_18_optimistic_concurrency_and_derived_reads.py | 433 | 4 |

## Coverage

- **Queue A (depth): 19/19 instances → 57 tests**, every instance ≥2 (distribution 2–5; e.g. `overlap_rider_windows_scoped_by_window_kind_inside_the_term` 5, `boundary_covered_share_bp_exactly_at_full_coverage_threshold` 4).
- **Queue B (breadth): 70/70 non-stub instances → 70 tests**, exactly one each. The 35 `excluded_because:` stubs were correctly not translated.
- Live-instance inventory re-derived mechanically from both YAMLs (entities 11, state_machines 7, calculations 14, validations 19, endpoints 8, errors 3, rbac 4, cross_cutting 3, consistency_model 1).

## Skipped instances

**None.** All 19 queue-A and all 70 live queue-B instances passed the PRD-first two-condition filter as whole instances. Nine individual **sub-assertions** were dropped (instance kept):

*Not uniquely derivable from the PRD:* re-running exemption analysis with an extra body key ⇒ `ERR_INVALID_REQUEST`; "no PATCH or DELETE is declared for setlist entries"; "term containment is checked before overlap" (PRD §2.12 rule 13 bundles both error ids with no stated order); "none of these derived fields is accepted as an input"; the `ERR_UNAUTHORIZED` probe (not a PRD error id — narrowed to an admin call so `ERR_ASSESSMENT_NOT_FOUND` is uniquely derived); `corner_endpoint_withdraw_only_departs_from_draft`'s SUBMITTED-refusal (PRD §3.4 permits withdrawal from DRAFT, SUBMITTED *and* RETURNED_FOR_REVISION, so the premise is wrong).

*PRD-silent:* `paid_at` (only `paid_amount_cents` exists); `renewed_into_license_id` (replaced by `renewal_issued_at is None` + `?renewal_of_license_id=` `total_count == 0`); "`reported_entry_count` stays 0 until submission" (PRD §3.8 says appending an entry increments it).

## Design-index defects corrected while translating

- Five "HTTP 422" claims are wrong — PRD §4/§5 say **409** for `ERR_WINDOW_OUTSIDE_TERM`, `ERR_COVERAGE_WINDOW_OVERLAP`, `ERR_RENEWAL_TERM_MISMATCH`, `ERR_ENTRY_OUTSIDE_PERIOD`, `ERR_SETTLEMENT_BELOW_FLOOR`; tests pass only the error id and let `validate_error` cross-check the frozen catalogue.
- `corner_validation_second_renewal_of_same_license_rejected` asserted successor `term_end == 2028-08-01` from `term_start == 2027-08-01`; 2028 is a leap year so +365 days is 2028-07-31 → replaced with `assert_days_apart(..., 365)`.
- `corner_validation_outstanding_balance_blocks_renewal_rejected` reused a licence version captured before a part payment (which bumps `version`) → re-read the licence, assert the rejected renewal left `version`/`updated_at` untouched.
- `corner_license_type_bgm_exempt_zeroes_the_whole_fee` named near-misses 1476/30000 presuming a 500 bp society while its setup uses BMI at 4600 bp → substituted the correctly derived 13800/13579.

## Confirmations

- (i) **Every one of the 127 tests carries exactly one `Design:` line, as the last docstring line, naming an instance that exists verbatim in the source YAML** — verified by AST audit (`tag discipline OK`, A=19/19, B=70/70, no duplicate test-function names suite-wide, zero case-insensitive "scaffold" hits anywhere in either directory).
- (ii) **All files compile** — `python3 -m compileall -q test_helpers test_suite` clean; `__pycache__` removed from both dirs.
- (iii) **Nothing was written under `workspace/`** — `find . -name test_helpers -o -name test_suite` returns only `./test_helpers` and `./test_suite`; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation`.
- `workspace/implementation/` was never read, written, listed or globbed. No pytest run, no server started, no `pkill`. `worklog.md`, `PRD.md`, `INSTRUCTION.md` and all `SCAFFOLD*.yaml` untouched. Scratch confined to `.scratch/step5/`, now removed with `rm -rf .scratch/step5` only (`.scratch/` itself intact and empty of siblings).

**Orchestrator verification [Step 5]**: `test_helpers/` (9 files) and `test_suite/` (conftest + 18 modules) both confirmed at the TASK ROOT; `find workspace -name test_helpers -o -name test_suite` returned nothing, so no stray copies under `workspace/`. Per-file `def test_` counts sum to 127.

## Step 6: Generate implementation (prd-bench-implementation-generator subagent) — 2026-09-05T21:55:17.808Z

Implementation complete.

## Module layout
All under `/home/ubuntu/github/CodingPRD/tasks/task_2939_venue_music_performance_licensing_repertoire_reporting/workspace/implementation/`

| file | lines | contents |
|---|---|---|
| `core.py` | 537 | constants/enums/thresholds, `ApiError` + factories, instant parse/format (`.mmmZ`), `rhu` half-up, envelope (`respond_object/list/error`), `Ladder`, `authenticate`, `validate_fields`, pagination helpers |
| `db.py` | 188 | in-memory dict store, logical clock (`2026-08-01T00:00:00Z`), `new_row`/`new_thin_row`/`touch`, ordered/where accessors |
| `serializers.py` | 251 | one `*_json` per entity; `licensed_venue_count`/`pinned_license_count` derived at read time; `*_pct`/`gap_risk_score` emitted from integer hundredths |
| `calc.py` | 474 | all 13 calculations (schedule selection, 5-step annual fee, licence-type assignment, BGM exemption, coverage posture, ledger, rider fee, true-up, match/coverage/weights/shares, gap risk, month walk, penalty/goodwill/settlement waterfall) |
| `services.py` | 330 | `recompute_venue`, billing dimension, delinquency sweep, relief sweeps, `issue_assessment`, CASCADE-A (`publish_schedule`), CASCADE-B (`submit_report`), `reopen_report` |
| `access.py` | 92 | error-id table, venue resolution per table, `fetch()` (rule 2 before rule 3), `narrow_rows` |
| `routes_reference.py` | 436 | clock, societies (3), rate-schedules (4), venues (5), repertoire-works (3) |
| `routes_applications.py` | 408 | applications (7) + shared `terms_overlap` / `duplicate_active_license` |
| `routes_licenses.py` | 575 | licences (9, incl. activate's six steps and renewal creation) + coverage-windows (2) |
| `routes_reports.py` | 342 | performance-reports (7) + setlist-entries (2) |
| `routes_audit.py` | 480 | audit-cases (8) + fee-assessments (3) |
| `app.py` | 62 | blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers → envelope, `PORT` env (default 10000), `0.0.0.0`, no reloader |
| `start.sh`, `requirements.txt` | — | guarded `import flask` check then `exec python3 app.py`, foreground |

## Endpoints
**54 implemented, exactly matching the PRD §4 table** (verified by enumerating `app.url_map`): clock 1, societies 3, rate-schedules 4, venues 5, license-applications 7, licenses 9, coverage-windows 2, repertoire-works 3, performance-reports 7, setlist-entries 2, audit-cases 8, fee-assessments 3.

## §2.12 ladder structure
One shared mechanism, not per-endpoint ordering: `core.py` defines a named priority constant per PRD rule (`P_AUTHENTICATION=1` … `P_PAYMENT_CEILING=23`), plus fractional priorities for the preconditions §3 states but §2.12 does not number (`P_VENUE_OPERATING=8.5`, `P_SCHEDULE_PUBLISHABLE=8.6`, `P_LOOKBACK_ELAPSED=8.7`, `P_SETTLE_ASSESSMENT=10.5`, `P_EXEMPTION_ANALYSED=17.7`). Each mutating handler builds a `Ladder`, registers closures with `@ladder.check(P_*)` in any source order, and calls `ladder.run()`, which sorts by `(priority, registration index)` and executes until the first raiser. Rules 1–2a live in `authenticate()`; rule 2b/3 in `access.fetch()` (ownership evaluated before existence, so a foreign row is 403 and a missing row is 404). Both documented shadowing pairs fall out automatically: report submit registers licence-active at 7 and period-overlap at 12; renew registers audit-hold at 9 and the balance gate at 20.

## Smoke test
Booted once via `bash start.sh` on `PORT=28584` (random high port), then ran a 46-call script covering the full happy path plus error probes: clock set, society (+duplicate 409), rate-schedule create/publish, venue create/read, application create/submit/accept-for-review/approve, licence list/activate/read, festival rider window (+cross-licence window list), work register, report open, two entries, submit, entry list, accept review, venue read, audit case open/findings/offer(409 below floor, then at floor)/dispute/re-offer/settle, assessment list/pay/(409 not issued), venue ledger read, and auth ladder checks (401 blank header, 403 wrong role, 404 unknown id, 422 bad enum, 422 `limit=0`). All expectations met (`SMOKE OK`). Cross-checks: ledger identity held (`330506 = 5183 + 325323 + 0`), `gap_risk_score = 25.39` and `gap_exposure_cents = 48528` matched hand-computed weights, `covered_day_count 7` rider produced a 5183-cent `SEASONAL_RIDER` assessment.

Teardown: identified the listener with `ss -ltnp | grep ":28584 "` → pid 1569166, then `kill 1569166` only. **No `pkill`/`killall` was ever run**; port confirmed free and the pid gone afterwards. Scratch used `.scratch/step6/` only and was removed with `rm -rf .scratch/step6` (sibling `.scratch/step5` untouched); `__pycache__` removed. `python3 -m compileall -q` passes over the whole directory.

**Orchestrator verification [Step 6]**: `workspace/implementation/` contains 12 Python modules plus `start.sh` and `requirements.txt`; no stray results files or seed data files present.

## Step 7: Run tests and iterate to green (long-lived fix subagent) — 2026-09-05T22:32:45.759Z

Step 7 is complete: all 8 parallel sweep rounds pass 127/127.

## Iterations run: 3 full 8-round sweeps

| Sweep | Result per round (i = 1..8) |
|---|---|
| 1 (baseline) | 116/127 in all 8 rounds — 11 failures, byte-identical across rounds (zero flakiness, so no load-contention noise to filter) |
| 2 (after first fix batch) | 126/127 in all 8 rounds — 1 failure, same test in all 8 |
| 3 (final) | **127/127, 127/127, 127/127, 127/127, 127/127, 127/127, 127/127, 127/127** — 0 failed, 0 errors, ~231 s per round |

Final `results.{1..8}.json` are left in `/home/ubuntu/github/CodingPRD/tasks/task_2939_venue_music_performance_licensing_repertoire_reporting/workspace/implementation/`.

## Tests deleted: none
No test was PRD-silent as a whole. One test had *partial* coverage and was handled by the STEP 1c split rather than deletion:
- `test_suite/test_16_endpoint_behaviour_contracts.py::test_endpoint_nested_coverage_window_list_is_scoped_to_its_licence` — the assertion that the nested `GET /licenses/{id}/coverage-windows` honours a `window_kind` filter was removed (PRD §3.6 attaches `license_id`/`window_kind`/`status` narrowing to the **cross-licence** listing only, and §4 grants the nested route no filters — FILTER-SILENCE on that route). The covered part was kept and the `window_kind` coverage was preserved by exercising it on `GET /coverage-windows`, plus an `ERR_LICENSE_NOT_FOUND` check on the nested route.

## Fixes to `test_suite/`
- `test_08_licence_terms_and_rider_window_overlap.py` — `_SUCCESSOR_TERM_END` corrected to `2028-07-31T00:00:00Z` (PRD §3.4 "365 days after `term_start`"; 2028 is a leap year); coverage-window create now expects **201** (PRD §4 lists a coverage window among the 201 creates).
- `test_09_ledger_and_coverage_invariants.py` — same leap-year correction for the successor `term_end`; `_build_pending_renewal`'s renewal now expects **201** (PRD §4 names "a successor licence" a 201 create). Fixed 3 failing tests.
- `test_13_gap_risk_selection_and_rollup_corners.py` — `test_calc_match_case_insensitive_oldest_registration_wins` advanced the logical clock one second between the two registrations. Both works were registered at the frozen clock instant, so they shared `created_at`, the primary "`created_at` ascending" key tied, and PRD §3.8's share tie-break correctly picked BMI; the setup could not express the test's own premise.
- `test_16_endpoint_behaviour_contracts.py` — the partial-coverage split above.
- `test_18_optimistic_concurrency_and_derived_reads.py` — `test_layer_stale_venue_version_blocks_application_filing` re-reads the venue after the accepted filing. PRD §3.4 is explicit: "Filing has two side effects beyond creating the row. The named venue's `version` increments by 1." The test had assumed only its own `update_venue` moved the counter.

## Fixes to `test_helpers/`
- `factories.py` — added `_society_shorthand` so `bmi_payload`/`ascap_payload`/`sesac_payload`/`gmr_payload` pop `society_code`/`display_name`/`repertoire_share_bp` out of `**overrides` instead of colliding with the positional args (the duplicate-society-code conflict test crashed with `TypeError: society_payload() got multiple values for argument 'display_name'`).
- `factories.py` — `matching_application_payload` now pops `expected_venue_version` from overrides (same `TypeError` shape in the stale-version test).

## Fixes to `implementation/`
One genuine defect: the licence `version` advanced twice on activation and on termination, because the billing-dimension write called `db.touch` on a row the same request had already touched. PRD §3.6 documents exactly one increment for activation (the re-rate) and §3.7 exactly one for termination (the coverage move); the paired billing moves (`UNBILLED`→`INVOICED`, →`WRITTEN_OFF`) carry no documented increment, and §2.11's "each documented increment applies" exists precisely to stop double counting.
- `services.py` — `_set_billing(..., touch=True)` and `bill_on_activation(..., touch=True)` gained an opt-out.
- `routes_licenses.py` — `activate_license` folds the billing move into the re-rate mutation (`bill_on_activation(..., touch=False)` before the single `db.touch`) and drops the later duplicate call; `terminate_license` writes `WRITTEN_OFF` into the coverage-move mutation instead of touching again. The legitimate single increments where a billing move *is* the whole mutation (delinquency sweep, post-payment relief, venue-wide settlement relief, and the priced-rider path) are untouched.

No changes to `PRD.md`, `SCAFFOLD*.yaml`, `INSTRUCTION.md`, or `worklog.md`; storage remains in-memory dicts only; `.scratch/step7/` and stray `__pycache__` dirs cleaned up.

**Orchestrator verification [Step 7]**: independently re-read all eight `results.$i.json` (all written 22:26, 41 KB each) — every round reports `passed 127 / failed 0 / errors 0 / total 127 / skipped 0`. The sweep was driven by the pre-written `workspace/sweep.sh` under `setsid nohup` with a `SWEEP_DONE` sentinel, so no round was reaped and no relaunch-on-early-return occurred.

**Step 8 decision**: NOT skipped. Step 7 applied 2 `implementation/` fixes (`services.py`, `routes_licenses.py`), 5 `test_suite/` fixes, 2 `test_helpers/` fixes and 1 partial-coverage split — the skip condition (zero iterations beyond baseline) does not hold.

## Step 8: Finalize PRD — align documentation to implementation (subagent) — 2026-09-05T22:37:59.487Z

PRD_FINALIZED.md is written and verified intact.

## Line counts
- PRD.md: 524 lines / 112,264 bytes
- PRD_FINALIZED.md: 524 lines / 113,482 bytes (0.00% line delta, +1.1% bytes; 4 lines revised in place, no lines added/removed, 29 `^#` headings ending at `## 5. Error Code Catalogue`, final row `| ERR_PAYMENT_EXCEEDS_BALANCE | 409 |` present)

## Changes (all 4 trace to the single genuine `implementation/` fix in the Step 7 diff, plus the one FILTER-SILENCE split)
- §2.11 — revise — after "each documented increment applies", pinned that a billing move belonging to the same act as a `coverage_status` move (activation's `UNBILLED → INVOICED`, termination's `WRITTEN_OFF`) rides inside that one mutation and adds no second licence `version` increment, while every other billing move (delinquency sweep, post-payment/post-settlement relief, `PAID → INVOICED` on a true-up or rider) is its own mutation and does increment — `services.py:69-83`, `routes_licenses.py:136-143`, `routes_licenses.py:284-290`
- §3.6 (activation, third step) — revise — the `UNBILLED → INVOICED` move is written into the re-rate's mutation, no second increment — `routes_licenses.py:141-143`, `services.py:92-95`
- §3.6 (window listing sentence) — revise — the per-licence coverage-window listing accepts only `limit`/`offset` and declares no filter parameters, returning every window of the licence regardless of `window_kind`/`status`; the cross-licence listing keeps its three filters verbatim — `routes_licenses.py:515-522` vs `routes_licenses.py:525-542`
- §3.7 (termination switch) — revise — `WRITTEN_OFF` is written inside the coverage-move mutation, no second licence increment — `routes_licenses.py:284-290`

## Per-edit pre-edit search log
1. **§2.11 increment rule.** (a) Subject: how many `version` increments a licence row gains when its billing dimension moves. (b) Enumerated: `grep` for `billing_status|_set_billing|bill_on_|relieve_|delinquency_sweep|db.touch` across all five route modules + `services.py`; read `services._set_billing/bill_on_activation/bill_on_extra_assessment/delinquency_sweep/relieve_license_billing/relieve_venue_billing`, `db.touch`, `routes_licenses.activate_license`, `terminate_license`, `suspend_license`, `reinstate_license`, `create_window` (rider path), `services.publish_schedule` Links 2–4, `routes_audit` findings (line 206 sweep), settle (368), pay (438-446), `routes_reports` review (267-274). Activation and termination are the only two sites that move both dimensions in one act, and they are the only two `touch=False` call sites; every other billing move touches. (c) Adjustment: dropped the tempting universal "activation advances the licence's `version` by exactly 1" — activation's step-5 delinquency sweep can add a further increment on the same licence (`services.delinquency_sweep` → `_set_billing(..., touch=True)`), so the wording was narrowed to "advances once **for that act**" plus an explicit "every other billing move ... including a move made later in the same request" clause; the examples list was phrased as illustrative so the rider path's `bill_on_activation(license_row)` (touch=True, `routes_licenses.py:505`) is also covered.
2. **§3.6 activation billing.** (a) Subject: the activation `UNBILLED → INVOICED` transition. (b) Enumerated: `routes_licenses.activate_license` steps 1–6, `services.bill_on_activation` (both call sites: activation `touch=False`, rider `touch=True`), the BGM_EXEMPT branch (no billing move, `billing_status` stays `UNBILLED`), the `annual_fee_cents >= 1` assessment guard, `services.delinquency_sweep`. (c) Adjustment: scoped the sentence to "that move" (the `UNBILLED → INVOICED` one) rather than to activation as a whole, so the sweep's later `DELINQUENT` move and the exempt branch remain untouched.
3. **§3.6 window listing.** (a) Subject: query parameters honoured by `GET /licenses/{id}/coverage-windows`. (b) Enumerated: `routes_licenses.list_windows_of_license` (pagination only, `access.fetch` with operator narrowing), `routes_licenses.list_windows` (three filters via `query_str`/`query_enum`), `read_window`, and the parallel nested/flat pair `routes_reports.list_entries_of_report` (no filters) vs `list_entries` (four filters) to confirm the nested-route convention. (c) Adjustment: said "declares no filter parameters of its own" rather than "narrows on nothing", so §4's role narrowing (a `VenueOperator` still gets 403 on a foreign licence) is not contradicted; kept the cross-licence filter list byte-identical.
4. **§3.7 termination `WRITTEN_OFF`.** (a) Subject: the `WRITTEN_OFF` write on terminate. (b) Enumerated: `routes_licenses.terminate_license` (single `db.touch(license_row)` at 290; window voids and assessment voids touch other rows; `recompute_venue` touches the venue), the §2.11 `INVOICED → WRITTEN_OFF` precondition bullet, `services.relieve_*` (never reached on terminate). (c) Adjustment: confined the parenthetical to the increment count and deliberately said nothing about departure preconditions — the impl writes `WRITTEN_OFF` whenever `void_unpaid_assessments` is true, matching §3.7's existing unconditional prose, so no precondition wording was added or narrowed.

Items deliberately **not** patched (PRD already uniquely determines them; the Step 7 change was a test/fixture bug): the 365-day `term_end` leap-year arithmetic (§3.4, `core.plus_days`), 201 on coverage-window and successor-licence creates (§4 already enumerates both), the §3.8 match tie-break `created_at` asc → share desc → `society_code` asc (`calc.match_work` follows it exactly), the venue `version` increment on application filing (§3.4 explicit), and both `factories.py` `**overrides` `TypeError` fixes.

**Orchestrator verification [Step 8]**: `diff PRD.md PRD_FINALIZED.md` shows exactly 4 single-line in-place revisions (lines 175, 326, 340, 350) and no other change; 524 lines in both files, tail still the final `ERR_PAYMENT_EXCEEDS_BALANCE` row, so the file was not truncated by a full rewrite. Note the byte-identical case would also have been legitimate here, but it did not arise — there were real edits.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch (3 module-partitioned sequential subagent passes) — 2026-09-05T23:12:17.210Z

**Orchestrator decision (recorded per the AUTONOMY directive)**: Step 9 was run as three *sequential* passes over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module rather than as a single subagent. A single agent cannot hold 12 modules plus a 524-line PRD and still make surgical edits; the failure mode is a byte-identical PRD_COMPLETED.md, which means the scan never really ran. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying so they could not clobber earlier edits. Partition: pass 1 = `core.py`, `db.py`, `app.py`, `access.py`, `serializers.py`; pass 2 = `calc.py`, `services.py`; pass 3 = the five `routes_*.py` modules.

### Pass 1 of 3 — core.py / db.py / app.py / access.py / serializers.py

Copy + integrity: `cp PRD_FINALIZED.md → PRD_COMPLETED.md` done as the first action. PRD_FINALIZED.md 524 lines / 113,482 bytes → PRD_COMPLETED.md 526 lines / 118,476 bytes (+2 lines, +4,994 chars). 29 headings; tail ends with `| ERR_PAYMENT_EXCEEDS_BALANCE | 409 |`; `diff` = 20 changed line-pairs (18 edits, two spanning two lines). All 8 `results.*.json`, `sweep.sh` and `round.*.log` untouched.

Counts: **ambiguity pins 13, mismatch revisions 5.**

- §2.1 (operator ownership bullet) — revise — mismatch — "does not resolve → 403" now reads "exists but does not resolve → 403; an identifier matching no row answers the matching 404 even for a `VenueOperator`" — access.py:73-81
- §2.2 success bullets — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alnum chars; `api_request_timestamp` is the one wall-clock reading and decides nothing — core.py:243-254
- §2.2 error-format intro — revise — mismatch — "(4xx status codes)" → "(4xx and 5xx status codes)" — app.py:49-51
- §2.3 — insert — ambiguity — `offset` must be an integer ≥ 0; negative or non-plain-decimal `limit`/`offset` → `ERR_INVALID_REQUEST` — core.py:494-502
- §2.3 — insert — ambiguity — rows tying on `created_at` order by insertion sequence; same tie-break governs cascade walks — db.py:100-102
- §2.3 — insert — ambiguity — `total_count` is counted after `VenueOperator` role narrowing — access.py:89-92
- §2.4 — revise — mismatch — "Nothing reads the wall clock" → "…for a business decision", naming `api_request_timestamp` as the sole exception — core.py:250-254
- §2.5 — insert — ambiguity — `created_at`/`updated_at` come from the logical clock, so a start-up row carries `2026-08-01T00:00:00.000Z` and an unmoved-clock mutation leaves `updated_at` equal to `created_at` — db.py:71-91
- §2.6 — insert — ambiguity — the three pct/score fields are the only non-integers emitted and always carry a fractional part (`0.0`, `60.0`, never `0`/`60`) — core.py:233-237, serializers.py:100,188-189
- §2.8 — insert — ambiguity — fractional seconds optional and of any width (digits past microseconds ignored); `+00:00`, lower-case `z`, date-only all malformed — core.py:172,190-207
- §2.12 rule 2 — revise — mismatch — ownership evaluated only "when it exists"; a missing path id falls through to rule 3's 404 — access.py:73-81
- §2.12 rule 4 — insert — ambiguity — a body FK that is absent/null/non-string/empty falls to rule 5 (`ERR_INVALID_REQUEST`); rule 4 fires only on a non-empty string naming no row — core.py:452-468
- §2.12 rule 5 — insert — ambiguity — JSON `null` accepted only where the field has a documented null default/resting value — core.py:415-418
- §2.12 (new paragraph before the shadowing pairs) — insert — ambiguity — placement of the five unnumbered §3 preconditions: venue-`OPERATING`, schedule-publishable, lookback-elapsed between rules 8 and 9; settle-assessment-`ISSUED` between 10 and 11; exemption-analysed between 17 and 18 — core.py:302-315
- §2.10 — revise — mismatch — `licensed_venue_count` is derived at read time, not stored; lifecycle events change it without mutating the `Society` row, its `updated_at` or its `version` — serializers.py:31,36-42
- §3.2 (end of cascade) — revise — mismatch — `pinned_license_count` likewise read-time-derived; a re-pin never mutates the `RateSchedule` row or advances its `version` — serializers.py:45-51,65
- §3.4 (approval) — revise — mismatch — "`pinned_license_count` increases by 1" → the read-time count picks up the new licence, leaving the schedule row untouched — serializers.py:45-51
- §4 intro — insert — ambiguity — empty-string filter treated as absent; enum filters must carry declared values; boolean filters must read `true`/`false` case-insensitively and trimmed; trailing slash resolves to the same endpoint — core.py:506-532, app.py:30
- §5 intro — insert — ambiguity — unknown path → 404, undeclared method → 405, unhandled failure → 500, all with `error_id` `ERR_INVALID_REQUEST` — app.py:20-51

Already uniquely pinned (checked, no change): header names and the four role values; all 27 enum lists; every numeric constant (250000 / 100000 / 100000 / 9500 / 3 / 2 / 365 / 13500 / 60.00 / 6000 bp / 30 days, all four tier tables, use-profile multipliers, 250 bp uplift, weight cap 10, LIVE 100 / RECORDED 40, 6-point per-affiliation penalty, 3750 / 2000 sq ft, 6 / 4 speakers); `DEFAULT_CLOCK` = `2026-08-01T00:00:00Z`; every `ApiError` factory's id→status pairing against the §5 table; `iso()` three-fractional-digit format; half-up-away-from-zero `rhu`; envelope key order and the `meta`/`response_type`/`data` shape; `has_more` semantics; uuid4 ids; `authenticate`'s 401-before-403 order and unrecognised-role→401; pagination defaults 10/0 and the 1–100 bound; empty unseeded store; `new_row` audit triplet; `new_thin_row` for `RepertoireWork`/`SetlistEntry`; `touch`; blueprint mounting under `/licensing` plus `/_clock`; access.py's error-id table and venue resolution per table; `narrow_rows`; and the complete response field set for all eleven entities.

### Pass 2 of 3 — calc.py / services.py

No re-copy performed; every change an in-place `Edit`. PRD_COMPLETED.md 526 lines / 118,476 bytes → 526 lines / 123,036 bytes (+4,560 chars), 29 headings, tail intact.

Counts: **14 edits — 11 ambiguity pins, 3 mismatch revisions.**

- §2.5 (row identity) — revise — ambiguity — one `recompute_venue` call refreshing several derived groups is a single venue mutation/increment while two separately documented recomputations in one request each carry their own; a no-op recomputation still increments — services.py:50-61
- §3.2 Link 1 — insert — mismatch — the incumbent candidate set is resolved *before* the published schedule joins `EFFECTIVE` (never its own incumbent), and supersession is unconditional/positional — services.py:171-184, calc.py:57-72
- §3.2 Link 2 — insert — ambiguity — Links 3 and 4 run *inside* the Link 2 walk, per licence — services.py:192-212
- §3.2 Link 3 — revise — ambiguity — whole days discard part days; a day count of 0 **or negative** yields no assessment — calc.py:291-299
- §3.2 Link 4 — revise — mismatch — `Venue.version` increments once per true-up assessment; a licence that raised no assessment skips the link; the `PAID → INVOICED` return is written *after* the sweep — services.py:204-212
- §3.8 Link 1 (matching) — insert — ambiguity — residual full tie resolved by insertion order, earliest first — calc.py:323-333
- §3.8 Link 1 (coverage) — insert — ambiguity — licence/window statuses read at submission time, only the window *span* tested against `performance_datetime`; any `window_kind` qualifies — calc.py:336-350
- §3.8 `gap_exposure_cents` — insert — ambiguity — multiplier is the already-rounded two-decimal `uncovered_share_pct` (a second stacked rounding); `annual_fee_cents` read at submission — calc.py:368-369, services.py:270-272
- §3.8 Link 2 — revise — ambiguity — source-report ranking gains a final "most recently inserted first" tie-break — calc.py:386
- §3.8 Link 3 — insert — ambiguity — the escalated case's resting values, and the `audit_hold` recomputation is a *second* venue mutation (so an escalating submission advances `Venue.version` twice) — services.py:295-320
- §3.8 Link 4 — insert — ambiguity — the decline branch leaves `revision_round` and `return_reason` untouched — services.py:227-233
- §3.9 exposure walk — insert — ambiguity — exact whole-calendar-month rule (month start ≥ `lookback_start` **and** next month's start ≤ `lookback_end`), worked example, and the no-whole-month degenerate case — calc.py:408-425
- §3.9 settlement relief — insert — ambiguity — the venue-wide relief sweep examines `DELINQUENT` licences only — services.py:129-139
- §3.9 payment — insert — ambiguity — an assessment with null `license_id` has no owning licence, so relief runs venue-wide on settlement-acceptance terms — services.py:113-139

Already uniquely pinned: tier boundaries and `tier_for`; max(seating, standing) occupancy; all three Step-1/2 roundings, the combined-bp Step 3, the pre-apportionment clamp and the Step-5 share; the `BGM_EXEMPT` → 0 short circuit and both fee variants; the licence-type decision table and `reporting_required`; all six BGM-exemption clauses with inclusive boundaries; `select_schedule` eligibility and descending rank keys; `covered_share_bp` distinctness and `posture_for` thresholds; the four ledger totals; the single-rounding rider fee; `_norm`; duration weight (ceil-to-minute, cap 10) and 100/40 use weights; `share_pct_h`'s zero-total short circuit; `gap_risk_score` (×0.8, +6 per distinct uncovered affiliation, cap after rounding); `month_covered`'s four-status set; penalty/goodwill tiers; the waterfall order with the tier selected once from the pre-credit total; `billing_status` transition preconditions and the delinquency-sweep tolerance; `issue_assessment`; `reopen_report`'s reset set.

### Pass 3 of 3 — routes_reference.py / routes_applications.py / routes_licenses.py / routes_reports.py / routes_audit.py

No re-copy performed; `Edit` only, and all 32 earlier edits verified intact by spot-check. PRD_COMPLETED.md 526 lines / 123,036 bytes → **526 lines / 132,239 bytes (+9,203 chars)**, 0 net lines (every change an in-paragraph insert or revision), 29 headings, tail ends with `| ERR_PAYMENT_EXCEEDS_BALANCE | 409 |`.

Counts: **35 changes — 20 ambiguity pins, 15 mismatch revisions.**

- §2.4 — insert — ambiguity — clock endpoint requires `current_utc`, rejects malformed/missing/non-object with `ERR_INVALID_REQUEST`, ignores extra keys, answers 200 with an empty object — routes_reference.py:55-64
- §2.10 — revise — mismatch — `audit_hold` gates **five** operations, not four — routes_applications.py:302-305
- §2.12 rule 8 — revise — mismatch — application-review departure state is disposition-dependent (`SUBMITTED` only for `ACCEPT_FOR_REVIEW`) — routes_applications.py:294-300
- §2.12 rule 8 — revise — mismatch — rule 8 does **not** apply to "every PATCH": venue PATCH and venue exemption-analysis declare no departure state — routes_reference.py:315-346
- §2.12 rule 9 — revise — mismatch — five operations, review hold-gated only for `APPROVE` — routes_applications.py:302-305
- §2.12 rule 11 — revise — mismatch — filing declares one instant only, so it never returns `ERR_INVALID_INTERVAL` — routes_applications.py:56-63
- §3.1 — revise — mismatch — `iswc` uniqueness is a convention, not enforced; duplicates accepted — routes_reference.py:383-388
- §3.1 — insert — ambiguity — works `title` filter is exact, case-sensitive, untrimmed (unlike §3.8 matching) — routes_reference.py:420
- §3.2 — insert — ambiguity — `effective_from: null` → `ERR_INVALID_INTERVAL`, ahead of every other shape check — routes_reference.py:156-159
- §3.2 — insert — ambiguity — ceiling ≤ floor → `ERR_INVALID_REQUEST`, only after per-field validation — routes_reference.py:160-164
- §3.2 — insert — ambiguity — publish's future-`effective_from` refusal also carries `ERR_RATE_SCHEDULE_NOT_DRAFT`; publication carries no body — routes_reference.py:203-208
- §3.3 — insert — ambiguity — venue PATCH with empty/absent body succeeds (version + verdict discard); `legal_name` and unknown keys ignored; only four fields nullable — routes_reference.py:270-278, 315-334
- §3.3 — insert — ambiguity — exemption analysis takes no body, has no departure gate, is re-runnable from any verdict, ignores venue `status`, increments `version` when unchanged — routes_reference.py:337-346
- §3.4 — insert — ambiguity — `expected_venue_version` is an integer ≥ 0; operator ownership compares the body `venue_id` at rule 2, so `ERR_FORBIDDEN_ROLE` precedes `ERR_VENUE_NOT_FOUND` — routes_applications.py:90-100
- §3.4 — insert — ambiguity — revision accepts an empty/absent body, ignores undeclared keys, accepts no `null`s; rule 5 precedes rule 8 — routes_applications.py:65-73, 160-172
- §3.4 — insert — ambiguity — submit's venue-`OPERATING` gate answers `ERR_APPLICATION_STATE_INVALID` (409) — routes_applications.py:194-199
- §3.4 — insert — ambiguity — the `BGM_EXEMPT` exemption-analysed precondition also answers `ERR_APPLICATION_STATE_INVALID` (409) — routes_applications.py:321-334
- §3.4 — insert — ambiguity — a reason field supplied with a disposition that does not require it is neither rejected nor stored — routes_applications.py:75-79, 286-292
- §3.4 — insert — ambiguity — the revision-limit conversion leaves `revision_round` untouched and writes no `return_reason` — routes_applications.py:356-364
- §3.4 — insert — ambiguity — approval answers 200 with the updated application in `data`; the created licence is not echoed — routes_applications.py:374-408
- §3.6 — insert — ambiguity — activation's venue-`OPERATING` gate answers `ERR_LICENSE_STATE_INVALID` (409) — routes_licenses.py:91-94
- §3.6 — insert — ambiguity — a non-exempt licence whose recomputed `annual_fee_cents` is 0 writes no assessment yet still advances to `INVOICED` and still recomputes the ledger — routes_licenses.py:141-167
- §3.6 — insert — ambiguity — a rider whose `rider_fee_cents` is 0 (and any `ANNUAL_TERM` window) issues nothing, recomputes nothing and leaves `billing_status` untouched — routes_licenses.py:500-507
- §3.7 — revise — mismatch — termination recomputes venue coverage **once** for the whole termination, not once per voided window — routes_licenses.py:293-307
- §3.7 — insert — ambiguity — the renewal body declares exactly two keys; `expected_license_version` is a required integer ≥ 0 — routes_licenses.py:60-63
- §3.8 — revise — mismatch — the per-report setlist-entry listing accepts only `limit`/`offset` and declares no filters — routes_reports.py:281-288
- §3.8 — insert — ambiguity — a `rejection_reason` on an `ACCEPT` is neither rejected nor stored — routes_reports.py:61-64, 250-254
- §3.8 — insert — mismatch — report review recomputes the score only: neither disposition re-runs Link 3 escalation or Link 4 pushback — routes_reports.py:262-278
- §3.9 — revise — mismatch — opening a case by hand raises the hold (blocking an approving review too) but runs **no** Link 4 pushback — routes_audit.py:99-126
- §3.9 — insert — ambiguity — the lookback-elapsed precondition answers `ERR_AUDIT_CASE_STATE_INVALID` (409) — routes_audit.py:144-150
- §3.9 — insert — ambiguity — `offer_amount_cents` is an integer ≥ 0; `payment_plan_months` is an integer ≥ 1 or explicit `null`, resting at null — routes_audit.py:62-65
- §3.9 — insert — ambiguity — settle's assessment precondition answers `ERR_ASSESSMENT_NOT_ISSUED` (409), including when `pre_credit_total_cents` was 0 — routes_audit.py:344-352
- §3.9 — insert — ambiguity — `amount_cents` on a payment is an integer ≥ 0 and a 0 payment is accepted, taking the short-payment branch — routes_audit.py:66, 433-447
- §3.9 — revise — mismatch — short-payment bullet no longer says "strictly greater than nothing" — routes_audit.py:66
- §4 — revise — mismatch — the empty string is treated as absent only for free-text/identifier filters; an empty enum or boolean filter is itself `ERR_INVALID_REQUEST` — `query_str` vs `query_enum`/`query_flag` call sites across all five route modules

Already uniquely pinned: ladder registration sets for all 54 endpoints against §2.12 rules 1–23 (rule 4's five-endpoint list, rule 7's three, rule 12's two, rule 17's four, rule 18's four all match); society/venue/work/schedule/report/entry/window/case body specs and ranges; report-create ownership at rule 2; `SUSPEND_SPEC`/`TERMINATE_SPEC`; reinstate/withdraw carrying no body; `bgm_service_provider` forced null when `uses_licensed_bgm_service` is false; venue creation resting values; the cross-licence list filter sets; suspend/reinstate single coverage recompute; `iswc` empty-string rejection; 201-vs-200 across all creating endpoints.

Remaining gaps declared by pass 3: none behaviorally significant. Two trivia left unpinned deliberately — the implicit 100,000-character upper bound `validate_fields` imposes on strings with no explicit `max` (that is `core.py`, pass 1's partition), and the visit order of the supersession sweep that withdraws sibling applications on filing (insertion order, unobservable).

### Orchestrator verification [Step 9]

`workspace/PRD_COMPLETED.md` is **526 lines / 132,239 bytes** vs PRD_FINALIZED.md's 524 / 113,482 — `cmp` confirms the two files DIFFER (118 changed lines in `diff`), so the byte-identical failure mode did not occur and the scan genuinely ran. 29 headings; tail ends on the final complete `| ERR_PAYMENT_EXCEEDS_BALANCE | 409 |` row, so no pass truncated the document. Cumulative across the three passes: **67 edits — 44 ambiguity pins, 23 mismatch revisions.**

`find implementation -newer implementation/results.1.json -name '*.py'` returns nothing, so no Step 8 or Step 9 pass modified the implementation — the green 8×127/127 sweep from Step 7 remains the valid evidence for the final code base. Pipeline complete.
