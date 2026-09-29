# Worklog — task_2851_institutional_research_federal_data_reporting

## Step 1: Create task directory — 2026-09-05T06:56:00.000Z

Created `tasks/task_2851_institutional_research_federal_data_reporting/` and `tasks/task_2851_institutional_research_federal_data_reporting/workspace/`. Index 2851 was pre-assigned by the orchestrating invocation; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold (subagent) — 2026-09-05T08:29:00.000Z

All three scaffold artifacts are complete, parse cleanly, and the linter reports `VERDICT: clean lint`.

Output files (`tasks/task_2851_institutional_research_federal_data_reporting/`)

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 3223 | §1.0–§1.7 only (no `scaffold_difficulty_design`, no `scaffold_corner_design`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1500 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4629 | `scaffold_corner_design` |

SCAFFOLD.yaml inventory: `api_prefix: /ir` — 14 entities, 13 state machines, 2 OCC concurrency rules (§1.2.1), 14 calculations, 31 ordered validations, 66 endpoints, 68 errors, 5 roles (IRAnalyst, IRDirector, RegistrarOfficer, DataSteward, DisclosureOfficer, all `identity: opaque`). Complexity profile: layers [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers], `consistency_model: immediate`, `entity_topology: graph`, `state_machine_shape: cyclic`, `role_model: segregation_of_duties`, `difficulty_level: expert_plus`.

Two §1.1/§1.6 corrections made while writing §1.9:
- Removed `ERR_INVALID_CELL_STATE` (69 → 68 errors) and its mention in the priority-11 check text: no declared endpoint path can reach it, so it would have broken "every error code is triggerable".
- Added the computed field `ReportingCycle.frozen_file_count`, which `calculations.cycle_active_record_count` already wrote but §1.1 never declared.

Verified: all 68 error ids are now referenced by at least one §1.8/§1.9 instance (0 uncovered).

§1.8 — 9 rule_ids × 2 instances = 18: `dual_variant_calc` 2, `combinatorial_formula` 2, `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 2, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2.

§1.9 — 9 sections, 81 instances (67 with `test_recipe`, 14 `excluded_because` stubs): entities 14 (1 stub) · state_machines 15 (3) · calculations 11 (2) · validations 18 (4) · endpoints 5 (0) · errors 6 (0) · rbac 5 (1) · cross_cutting_complexity_layers 5 (3) · consistency_model 2 (0).

Section names are all from the claim-extraction guide's nine; every stub cites a §1.8 instance that exists by name and carries no `test_recipe`; all 99 instance names across the two design files are unique.

Lint: `scaffold_lint.py` scanned 962 calls across §1.8+§1.9 against the 66 declared endpoints: every call's path, role, payload keys, required inputs and captures resolve, no OCC literal versions, and all 14 entities' FKs have reverse-reachability.

Orchestrator check: grepped all three scaffold files for the difficulty directive line ("harder than expert level") — 0 hits, so no leak into the scenario key or downstream to PRD.md.

## Step 3: Copy shared files — 2026-09-05T08:30:00.000Z

Copied `INSTRUCTION.md` from project root to `tasks/task_2851_institutional_research_federal_data_reporting/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-05T08:48:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — 512 lines, 123,153 bytes, built via 8 chunked `cat >>` appends (no single call anywhere near the 64k cap). Last heading is `## 5. Error Code Catalogue`; the document ends at the final row of the completed error table (`| ERR_REJECTION_REASON_REQUIRED | 422 Unprocessable Entity |`), a real section boundary, with no audit footer.

**Sections written (28 headings):**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications, 12 subsections: 2.1 RBAC · 2.2 API Response Structure (byte-identical to the skill's contract file, verified by `diff`) · 2.3 Pagination and Deterministic List Ordering · 2.4 Common Resource Properties and the Immutable Definition Library · 2.5 The Logical Clock, the Census Date and the Collection Deadline · 2.6 Snapshot Posture · 2.7 Hierarchical Consistency and Cascade Discipline · 2.8 Optimistic Concurrency Control · 2.9 Numeric Precision and Rounding · 2.10 Segregation of Duties · 2.11 Interval Geometry: Two Windows, Two Different Rules · 2.12 Left-to-Right Path Resolution and Validation Precedence (full 1–31 priority list)
- §3 Business Logic, 9 subsections: 3.1 cycle open + census seal · 3.2 federal definition library + element mapping · 3.3 component assembly, per-FTE expense, preparation + edit-check generation · 3.4 edit-check resolution + `edit_status` derivation · 3.5 certification, submission, freeze, reopen, reversion · 3.6 cohorts + two rate variants · 3.7 publication + restatement change control · 3.8 external reconciliation + transmission · 3.9 data requests + disclosure avoidance
- §4 Endpoint Definitions (4-column table) · §5 Error Code Catalogue (2-column table)

**Coverage:** 66/66 endpoints, 68/68 errors, 14/14 entities, 5 roles, 2 OCC rules, 14/14 calculations, 31/31 validations, 64/64 state transitions.

**Hard Contract reports**

- **Contract 1 — Field-Name Coverage: PASS.** Re-derived the required set directly from the scaffold with PyYAML (all `entities[].fields[].name`, all `endpoints[].input`/computed-read output keys, all path params, plus `id`/`created_at`/`updated_at`/`version`) = 153 identifiers. All 153 appear verbatim in backticks in PRD.md; 0 missing.
- **Contract 2 — Rule Coverage: PASS.** All 68 error IDs appear in §1–§4 prose (not merely in the §5 table); all 64 scaffold transitions appear in explicit `FROM → TO` arrow form; all 14 calculations narrated with their pinned evaluation orders (round-per-category-then-sum for `core_expense_per_fte_cents`, single-pass 1→5 tiering for `submission_reconciliation`, two-pass small-cell suppression, difference-of-already-rounded-variants for `rate_divergence_pp`); all 31 validations enumerated in priority order in §2.12 with error IDs and statuses, and re-stated in context; §4 table verified programmatically against the scaffold for exact method/path pairs and exact role sets (0 mismatches), §5 table for exact error IDs and HTTP statuses (0 mismatches).
- **Contract 3 — §3 Path Purity: PASS.** Extracted §3 through the §4 heading (66,739 chars) and scanned: 0 backticked tokens beginning with `/`, 0 containing `/ir/`, 0 bare or embedded HTTP method tokens, and 0 unbackticked `/ir/` mentions. §3 uses state-transition and role+action-verb framing throughout.

**Two scaffold-internal inconsistencies corrected in the §4 descriptions** (the scaffold's own enums are authoritative): `POST /ir/survey-components` said "HUMAN_RESOURCES" where the `component_code` enum is `HR`; `PATCH /ir/cohort-members/{member_id}` said "TRANSFERRED, WITHDRAWN" where the `outcome` enum values are `TRANSFERRED_OUT` and `NO_LONGER_ENROLLED`.

**One judgment call:** the scaffold requires a survey component's referenced extract `domain` to equal its `component_code` but declares no dedicated error, so §3.3 expresses the mismatch as a wrong-parent case yielding `ERR_FROZEN_FILE_NOT_FOUND`, consistent with validation priority 5, rather than inventing an error ID.

The two withheld design-index files were never opened, grepped, or referenced; no sibling task directory was read. Scratch work lived in `/tmp/task_2851_ir_fed_prd/`.

Orchestrator anti-truncation check: `wc -l` = 512; `tail -12` shows the §5 error-code table completing normally at `ERR_REJECTION_REASON_REQUIRED`. Ends at a real section boundary, not mid-sentence. No regeneration needed.

## Step 6: Generate implementation (subagent) — 2026-09-05T09:28:00.000Z

The implementation is complete and verified. Smoke server on port 18510 has been stopped (killed by port, `fuser -k 18510/tcp`; port now free).

## Modules written — `workspace/implementation/`

| file | lines | file | lines |
|---|---|---|---|
| `start.sh` (exec, guarded pip) | 8 | `routes_cycle.py` | 202 |
| `requirements.txt` | 1 | `routes_component.py` | 339 |
| `app.py` | 74 | `routes_cohort.py` | 238 |
| `util.py` | 113 | `routes_library.py` | 181 |
| `errors.py` | 84 | `routes_external.py` | 166 |
| `db.py` | 112 | `routes_pub.py` | 187 |
| `response.py` | 105 | `routes_disclosure.py` | 169 |
| `validation.py` | 176 | `svc_common.py` | 140 |
| `auth.py` | 38 | `svc_cycle.py` | 105 |
| `svc_component.py` | 151 | `svc_pub.py` | 87 |
| `svc_cohort.py` | 74 | `svc_disclosure.py` | 70 |

2820 lines of Python total, 23 files. `python3 -m py_compile *.py` → ALL_COMPILE_OK (nothing truncated; `__pycache__` removed).

## Coverage
- **Endpoints: 66/66.** `app.url_map` registers exactly the 66 scaffold paths (65 under `/ir` + `POST /_clock/set_current_utc`), no extras.
- **Errors: 68/68.** Every catalog ID is present in `ERROR_STATUS` with the scaffold's HTTP status (zero mismatches), and a static cross-check confirms every one of the 68 is actually raised by a `fail(...)` call somewhere — no dead entries, no ad-hoc IDs.
- **Constraints honoured:** in-memory dicts only (no `open()`, no sqlite, no `/tmp`, no dumps), store empty at boot with no seeding, no reads of `test_helpers/`, `test_suite/`, or any sibling task dir.

## Smoke tests (four scripts under `/tmp/task_2851_ir_fed_impl/`, port 18510)
All green. Highlights from the final two runs:
- **Frozen files / census:** coverage overlap → `ERR_COVERAGE_WINDOW_OVERLAP`; out-of-reporting-year window → `ERR_INVALID_COVERAGE_WINDOW` (1 Jul y-1 … 30 Jun y); identical window re-registration supersedes the incumbent (`SUPERSEDED` + `supersedes_frozen_file_id` set), census-lock counts only the ACTIVE extract.
- **Components:** per-FTE 500007+100001+200002 over 6 FTE → `133336` (whole-cent truncation-free ROUND_HALF_UP), prepare with no raised checks → `edit_status CLEARED`, certify → freeze → submit bubbles the cycle `FROZEN → ARCHIVED`.
- **Publications:** half-open adjacency allowed (`2026-12-01` start against a window ending `2026-12-01` → PUBLISHED), interior start → `ERR_PUBLICATION_WINDOW_OVERLAP`, zero-length → `ERR_INVALID_EFFECTIVE_WINDOW`.
- **Disclosure (all six branches):** refuse branch stamps `AGGREGATE_BELOW_MINIMUM` with the cell left `PENDING`/`released_count` null at `version` 1; single-primary group with no candidate raises `residual_disclosure_risk`, which blocks a MEDIA release with `ERR_SMALL_CELL_DISCLOSURE` but is tolerated for INTERNAL; two primaries in one group mask each other (no victim, `SUPPRESSED_RELEASE`); controlled rounding gives 3→5, 0→0, 2→0, 7→5, 12→10; post-screen cell add → `ERR_INVALID_DATA_REQUEST_STATE`.
- **Envelope/auth/pagination:** unknown nested id → `ERR_DATA_REQUEST_NOT_FOUND` 404; missing or unrecognised `X-User-Role` → `ERR_UNAUTHENTICATED` 401 ahead of routing; valid-but-wrong role → `ERR_ROLE_NOT_PERMITTED` 403; `limit=0`/`limit=101` → `ERR_INVALID_REQUEST`; list meta reports `limit/offset/total_count/has_more` correctly.

Only two bugs were found and fixed all session, both mine: four `req_number(..., minimum=0)` keyword mismatches (now positional), corrected before the final runs. Every other red line in the smoke output traced to a defect in the smoke script itself (wrong `expected_cycle_version`, a `collection_year` inconsistent with its coverage dates, `dimension_group` under the 2-char minimum, and an assumed `GET /ir/reporting-cycles` list endpoint that the scaffold does not declare) — each of those responses was the PRD-correct behaviour.

## Step 5: Generate unit tests (subagent) — 2026-09-05T10:42:00.000Z

Test generation for task_2851 is complete. All 17 test modules plus the shared infrastructure are written, syntactically clean, and fully design-tagged.

## Files written (task root, nothing under `workspace/`)

`test_helpers/`
- `__init__.py` 85, `api_client.py` 374, `api_errors.py` 203, `assertions.py` 558, `constants.py` 313, `factories.py` 479, `fixtures.py` 633, `test_users.py` 113, `types.py` 312

`test_suite/`
- `conftest.py` 53
- `test_01_reporting_cycles_and_census_extracts.py` 520 (10 tests), `test_02_census_lock_and_cycle_posture.py` 379 (7), `test_03_survey_components_and_metrics.py` 394 (6), `test_04_preparation_and_edit_check_generation.py` 552 (8), `test_05_edit_check_resolution.py` 655 (6), `test_06_certification_freeze_and_submission.py` 496 (7), `test_07_definitions_and_element_mappings.py` 386 (4), `test_08_cohorts_and_the_student_roster.py` 365 (5), `test_09_exclusions_and_the_two_rate_variants.py` 634 (7), `test_10_publications_and_the_restatement_ledger.py` 737 (8), `test_11_external_submissions_and_reconciliation.py` 629 (7), `test_12_data_requests_and_the_screening_gate.py` 396 (5), `test_13_suppression_variants_and_controlled_rounding.py` 419 (5), `test_14_the_reopen_lap_and_cascade_visibility.py` 634 (5), `test_15_reopen_and_exclusion_cascades.py` 521 (4), `test_16_error_identity_and_uniqueness.py` 729 (6), `test_17_role_permissions_and_segregation_of_duties.py` 517 (4)

Total 12,086 lines; **104 tests**.

## Design-queue coverage
- Queue A (Difficulty, §1.8): 18 non-stub instances, 0 stubs → **36 tests, exactly 2 per instance**.
- Queue B (Corner, §1.9): 81 instances, 14 stubs (`excluded_because:`) → 67 non-stub → **68 tests** (one instance carries 2).
- `check_design.py`: distinct instances covered **85 / 85** (queue A 18, queue B 67). Every test has exactly one trailing `Design:` line; no untagged, dual-tagged, or dangling tags.

## SKIPPED instances
**None.** All 85 non-stub instances passed the PRD-first two-condition filter. The 14 stubs were excluded by the design yaml itself, not by me.

## Verification
- `check_citations.py`: tests 104, problems 0 (every `PRD n.n: "…"` quote greps verbatim into the owning PRD line).
- `check_sections.py`: 0 problems (claimed section number matches the owning header).
- `check_calls.py`: 0 problems (every call site binds against `inspect.signature`; no helper builds its own headers).
- `python3 -m py_compile` on all 27 emitted `.py`: clean. `pyflakes` on the whole suite: zero findings outside the deliberate re-exports in `test_helpers/__init__.py`.
- Attribute audit: every `K.*`, `f.*`, `fx.*`, `ApiErrorId.*`, and `from test_helpers import …` name resolves.
- No `test_helpers/` or `test_suite/` anywhere under `workspace/`; `implementation/` never read, written, or listed; scratch confined to `/tmp/task_2851_ir_fed_tests/`.

## Deviations from the design yaml (PRD always won)
1. **corner 3976** — yaml's `value_domain: []` violates §3.2 ("array of 1 to 40 strings"); used `["HEADCOUNT"]`.
2. **corner 4051** — asserted a reporting-cycles list `total_count`, but PRD §4 has no `GET /ir/reporting-cycles`; substituted a registrar re-create of the freed `IPEDS-2028` code expecting 201, citing §3.1's `cycle_code` uniqueness.
3. **corner 4216** and the SoD test in test_17 — yaml published without freezing, which §2.6 forbids (`ERR_CYCLE_NOT_FROZEN`); a director freeze is inserted before the publication.
4. **corner 3859** — yaml's post-freeze FIN mapping proved nothing about precedence; used the *duplicate* SIS triple so `ERR_CYCLE_FROZEN` (priority 6) visibly outranks `ERR_DUPLICATE_MAPPING` (27).
5. **corner 3474** — definition-path 404 family adjusted to the reachable path/body reference actually declared in §4.
6. **corner 4498** — `variance_pct` / `version` expectations corrected to the §3.4 formula and the actual write count.
7. **corner 4554** — cohort `version` corrected to the number of mutating writes.
8. **difficulty 624** — denial-cascade step substituted with the PRD-derivable equivalent.
9. **corner 2615** — `certified_at` echo asserted through `assert_instant_equals` (sub-second width canonicalised in `api_client`) rather than raw string compare.
10. **275→250 reversal** — `public_notice_required` assertion omitted where §3.7 does not uniquely derive it at that step.

Orchestrator placement check: `workspace/test_suite` and `workspace/test_helpers` do not exist (no stray copies); task root has 18 files in `test_suite/` (17 modules + conftest) and 9 in `test_helpers/`; 104 `def test_` functions and 104 `Design:` tags — 1:1.

## Step 7: Run tests and iterate (long-lived subagent) — 2026-09-05T11:00:00.000Z

Green sweep achieved. Final state: **all 8 parallel rounds pass 104/104**.

## Summary

**Iterations run:** 2 (baseline sweep + one fix batch, then verification sweep).

Iteration 1 was deterministic, not flaky: every one of the 8 rounds failed exactly the same 4 tests. No load-induced failures appeared in either sweep.

**Tests deleted:** none. One *assertion* was removed under STEP 1c (partial coverage), noted below.

**Fixes applied to `test_helpers/`:** none. The fixture/factory layer traced cleanly to PRD (money and counts already JSON numbers, calendar dates vs. instants already split correctly, no envelope double-unwrap).

**Fixes applied to `test_suite/`** (all four failures were test bugs; the implementation was PRD-faithful in every case):

1. `test_suite/test_03_survey_components_and_metrics.py` — `TestMetricCorrection::test_a_correction_recomputes_the_variance_and_the_restated_flag_never_clears`: removed the single assertion `reverted["restatement_note"] == note` (DEFAULT-VALUE SILENCE). PRD §3.3 says only "the supplied note is stored"; with `restatement_note` omitted on the second correction, one faithful reader clears it to null and another leaves the prior note standing. The covered assertions (value overwritten, `variance_pct` recomputed, `restated` never clears, `version` climbs) were kept. Scaffold rule that drove it: `corner_ep_metric_patch_recomputes_variance_and_flags_the_row_restated`.

2. `test_06_certification_freeze_and_submission.py` — `TestFrozenCycleOutranksTheDuplicateKey::test_the_losing_uniqueness_rule_still_fires_on_a_cycle_that_is_not_frozen`: the test builds two cycles in one test but both took the default `cycle_code`, so setup died at `ERR_DUPLICATE_CYCLE_CODE` (PRD §3.1 requires `cycle_code` unique across all cycles). Passed `cycle_code=K.CYCLE_CODE_ALT` to the second `fx.component_on_locked_cycle`.

3. `test_11_external_submissions_and_reconciliation.py` — `TestTransmissionHasTwoIndependentGates::test_a_draft_submission_and_an_unfrozen_cycle_block_transmission_with_different_ids`: the test transmitted a `DRAFT` submission on a `CENSUS_LOCKED` cycle and expected `ERR_INVALID_SUBMISSION_STATE`. That request is wrong in two ways, and PRD §2.12 pins the answer: posture gating (priority 8, `ERR_CYCLE_NOT_FROZEN` — transmission is one of the five post-freeze operations of §2.6) precedes the row's own state check (priority 11). Corrected that assertion to `ERR_CYCLE_NOT_FROZEN`, and to keep the test's "two independent gates" coverage intact, added a second never-reconciled `DRAFT` submission created *after* the freeze whose transmit attempt isolates `ERR_INVALID_SUBMISSION_STATE` with the posture gate satisfied. Both error-id assertions remain exact — nothing was downgraded to an HTTP-status check.

4. `test_14_the_reopen_lap_and_cascade_visibility.py` — `TestCascadedRowsAreReadableOnTheVeryNextGet::test_the_cohort_is_already_locked_and_rated_when_the_freeze_answers`: the test asserted `federal_rate_pct`/`ranking_rate_pct` were null on a `DRAFT` cohort that already had two members seated. PRD §3.6 states that adding a member recomputes "the parent cohort's counts and both rate variants", and with `adjusted_count` 2 and one `COMPLETED_150` both variants are 50.0. Replaced the two null assertions with `assert_rate_variants(untouched, 50.0, 50.0)`; the census-lock's actual claim (cohort stays `DRAFT`, `locked_at` still null) is preserved.

**Fixes applied to `implementation/`:** none — no PRD-traceable implementation defect was found. Nothing was added to, removed from, or weakened in `workspace/implementation/`, and `worklog.md` was not touched.

### Orchestrator verification of the sweep artifacts (not taken on trust)

Independently re-read all 8 per-round result files rather than accepting the subagent's claim:

```
results.1.json 104 / 104 failed: 0
results.2.json 104 / 104 failed: 0
results.3.json 104 / 104 failed: 0
results.4.json 104 / 104 failed: 0
results.5.json 104 / 104 failed: 0
results.6.json 104 / 104 failed: 0
results.7.json 104 / 104 failed: 0
results.8.json 104 / 104 failed: 0
```

All eight files present and timestamped 10:59, `workspace/sweep.done` = `2026-09-05T10:59:06Z`. Test count is still 104 `def test_` functions, confirming the reported "0 tests deleted" (only one assertion was dropped, not a test). The sweep ran under `setsid` via the pre-written `workspace/run_sweep.sh`, so no reaping artifacts; per-round stdout went to separate `workspace/round.$i.log` files rather than the spliced shared `sweep.log`.

### Step 8 gating decision

Step 7 reports 0 deletions / 0 `test_helpers/` fixes / 0 `implementation/` fixes but **4 `test_suite/` fixes**, so the skip condition (which requires all four counts to be zero) is not met. Step 8 runs, with the four test_suite fixes as its `<step_7_diff>` focus list. Note in advance for Step 9: because Step 7 made no implementation fixes, a byte-identical `PRD_FINALIZED.md` would be a legitimate Step 8 outcome here if none of the four sites turns out to be a genuine PRD silence — but Step 9 must still produce a real diff.

## Step 8: Finalize PRD (subagent) — 2026-09-05T11:11:00.000Z

PRD_FINALIZED.md is written. One edit, from one of the four Step 7 sites; the other three were already uniquely determined by PRD.md.

**Line counts:** PRD.md 512 lines / PRD_FINALIZED.md 512 lines — 1 line revised, 0 added, 0 removed (0% line delta; 1 line changed = 0.2% of the file).

**Change:**
- §3.3 (Assembling a Survey Component — metric correction) — revise — `the supplied note is stored` → `restatement_note` is overwritten with the supplied note, **and overwritten with null when the correction omits `restatement_note` or sends it as null**, so a later correction carrying no note clears the earlier note. Pins the default-value silence Step 7 item 1 exposed. Impl: `implementation/routes_component.py:242` (`opt_string(body, "restatement_note", 1, 500)`, default `None`) and `:252` (unconditional `metric["restatement_note"] = note`); `implementation/validation.py:25-38` (`_present` treats an explicit JSON `null` as absent, so null and omission collapse to the same `None`).

**Per-edit pre-edit search log (edit 1, the only edit):**
- (a) Subject: the lifecycle of the `restatement_note` field on a component metric — specifically who writes it, and with what value, on every write path.
- (b) Paths enumerated: `grep -rn "restatement_note" implementation/*.py` returned exactly three sites — `routes_component.py:213` (row creation, explicit `None`), `:242` (payload read), `:252` (correction assignment). No prepare, certify, revert-to-draft, freeze, reopen or cascade path touches the field (checked `svc_component.py`, `svc_cycle.py`, `svc_pub.py`, `svc_cohort.py` via the same grep). Also read `serialize_metric` (`routes_component.py:25`, plain `public(row)` — no defaulting or field suppression at the boundary) and `validation.py:25-48` to establish that omitted and explicit-null are indistinguishable. Cross-checked the neighbouring field `restated` (`grep '"restated"'` → only `:212` False at creation, `:251` True on correction) to confirm the new clause does not accidentally imply symmetric clearing of `restated`.
- (c) Wording adjustment: scoped the null-write to the *correction* operation only (not "any write") so `:213`'s creation default still reads as its own already-stated sentence on line 235; and spelled out "omits ... or sends it as null" rather than just "omits", because `validation.py:_present` treats both identically. Deliberately said nothing about `restated`, which never clears.

**Sites that needed no PRD edit (verified against impl, PRD already determines them):**
- Item 2 (`cycle_code` collision): pure fixture bug. PRD §3.1 already states `cycle_code` is "unique across all cycles under case-sensitive comparison, with a collision reported as `ERR_DUPLICATE_CYCLE_CODE`".
- Item 3 (transmit on a DRAFT submission over an unfrozen cycle): PRD §2.6 already lists "transmitting an external submission" among the five post-freeze operations, and §2.12 pins priority 8 (`ERR_CYCLE_NOT_FROZEN`) ahead of priority 11 (`ERR_INVALID_SUBMISSION_STATE`), with an explicit closing paragraph emphasizing that ordering. `routes_external.py:156-159` calls `require_frozen(cycle)` before the status check — exactly as written.
- Item 4 (cohort rates on a DRAFT cohort with seated members): PRD §3.6 already says adding a member recomputes "the parent cohort's counts and both rate variants". `svc_cohort.py:8-36` (`recompute_cohort`) is called unconditionally from `routes_cohort.py:88` on member add, with no `status`/`locked_at` guard, so 50.0/50.0 follows from the PRD text; the test's null assertions were the defect.

Orchestrator check: PRD_FINALIZED.md is NOT byte-identical to PRD.md (123,374 vs 123,153 bytes; exactly one line differs), so Step 8 genuinely ran. Step 9 proceeds from PRD_FINALIZED.md.

## Step 9: Complete PRD (three sequential module-partitioned subagent passes) — 2026-09-05T11:35:00.000Z

Orchestrator decision: the implementation is 23 modules / ~2820 lines, too large for one reliable full scan, so Step 9 was split into **three sequential passes partitioned by implementation module**, all editing the SAME `workspace/PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to copy anything (a re-`cp` would silently destroy prior passes' edits) and were each told which subjects earlier passes had already pinned so they would not duplicate or revert them. Total: **41 changes across 32 lines** — 35 ambiguity-pins, 6 mismatch-revisions.

### Pass 1 of 3 — cross-cutting infra + cycles/census + definitions/mappings
Partition: `app.py`, `util.py`, `errors.py`, `db.py`, `response.py`, `validation.py`, `auth.py`, `svc_common.py`, `routes_cycle.py`, `svc_cycle.py`, `routes_library.py`.

Setup: `cp workspace/PRD_FINALIZED.md → workspace/PRD_COMPLETED.md` done once, at the start, before any edit. Source = `PRD_FINALIZED.md` (Step 8 output).

Size: PRD_FINALIZED.md 512 lines / 123,374 chars → 512 lines / 126,820 chars (+3,446 chars, 0 lines added/removed — every change is an in-paragraph replacement; no new sections).

Counts: 14 ambiguity-pins, 2 mismatch-revisions (12 distinct lines touched: 44-45, 76, 78, 80, 97, 101, 165, 171, 207, 223, 227, 283).

- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-letter/digit characters — `util.py:25-27`
- §2.2 — insert — ambiguity — `api_request_timestamp` is real wall-clock UTC, explicitly *not* the logical clock — `response.py:15-21`
- §2.3 — insert — ambiguity — `limit`/`offset` omitted or empty take defaults; non-integer or out-of-range → `ERR_INVALID_REQUEST` (400) — `response.py:47-68`
- §2.3 — insert — ambiguity — `created_at` ties are broken by server insertion sequence, for listings and for cascade sibling walks alike — `db.py:103-105`, `svc_common.py:70-74`
- §2.3 — insert — ambiguity — absent/empty filter ignored; boolean attributes accept `true`/`false`; literal `null` matches null attributes (e.g. `supersedes_frozen_file_id=null`) — `response.py:78-104`
- §2.5 — insert — ambiguity — the clock accepts any instant including one earlier than its current reading — `app.py:38-45`
- §2.5 — insert — ambiguity — client-supplied dates/instants are stored and echoed verbatim (never re-formatted), only server-written stamps are canonicalised; instants accept 0-9 fractional digits, optional seconds, numeric offsets, and a bare `YYYY-MM-DD` as midnight UTC — `util.py:43-79`, `routes_cycle.py:44-56`
- §2.12 — revise — mismatch — the body-FK list claimed census-extract registration resolves a body `cycle_id`; it arrives in the path. Also pinned two-FK resolution order (`cycle_id` before `definition_id`) — `routes_cycle.py:127-137`, `routes_library.py:88-89`
- §2.12 pri 3 — insert — ambiguity — absent body reads as `{}`, non-object body rejected; a field sent as JSON `null` counts as absent (required → 400, optional → declared default) — `validation.py:10-26`
- §2.12 pri 3 — revise — mismatch — only the *minimum* lengths defer to priorities 30/31; `rejection_reason` > 500 chars is `ERR_INVALID_REQUEST` at priority 3, < 10 chars is `ERR_REJECTION_REASON_REQUIRED` — `routes_library.py:135,150-152`
- §3.1 — insert — ambiguity — `collection_deadline` ≤ census midnight is `ERR_INVALID_REQUEST`, evaluated before the `cycle_code` uniqueness scan — `routes_cycle.py:38-43`
- §3.2 — insert — ambiguity — every `value_map` key and value must be a string — `validation.py:148-159`
- §3.2 — insert — ambiguity — a revision keeps `validated_by_user_id` (the rejecting steward) and cannot change `local_system_code` / `local_field_path` — `routes_library.py:160-180`
- §3.5 — insert — ambiguity — reopen level two also forces `fatal_open_count` to 0 and deliberately leaves `prepared_by_user_id` in place (unlike direct revert-to-draft); `reopen_reason` persists and is never cleared by a later lock/freeze/archive — `svc_cycle.py:74-87`, `routes_cycle.py:112-124`

Integrity: `wc -l` = 512; last line = the §5 table's `ERR_REJECTION_REASON_REQUIRED` row — no truncation. `worklog.md` untouched; scratch confined to `/tmp/task_2851_ir_fed_step9p1/`. Noted that §5's error/status table matches `errors.py:ERROR_STATUS` exactly (no edit needed). Two items handed forward: §2.6's "Twelve operations" list actually enumerates 13 items, and unmatched routes/methods return `ERR_INVALID_REQUEST` with 404/405 (`app.py:53-61`), which no test exercises.

### Pass 2 of 3 — survey components/metrics/edit checks + cohorts/exclusions/rates
Partition: `routes_component.py`, `svc_component.py`, `routes_cohort.py`, `svc_cohort.py`.

Integrity confirmation: did NOT `cp` or overwrite `PRD_COMPLETED.md` — every change a surgical `Edit`. Pass 1's edits all survive: grepped `req_` (3 hits), `"the sequence in which the server created them"` (1), `"followed by exactly 20 characters drawn from the uppercase letters"` (1), `"deliberately *not* read from the logical clock"` (1).

Size: 512 lines before → 512 after; 126,820 → 129,748 chars (+2,928).

Counts: 11 ambiguity-pins, 3 mismatch-revisions (14 edits).

- §2.6 band 4 — revise — mismatch — "Twelve operations declare this band explicitly" → "Thirteen", matching the 13 items actually enumerated (the item handed forward by pass 1) — `svc_cycle.py:35-46`, `routes_cohort.py:81,197,221`
- §2.3 — insert — ambiguity — the two single-key list overrides (`metric_key`, `sequence_no`) tie on an unfiltered listing; tie falls back to `created_at` then insertion order — `routes_component.py:230-232,270-272`
- §3.3 (component creation) — insert — ambiguity — the named extract's `status` is not examined at creation, so a `SUPERSEDED` extract may be named; refusal comes only at prepare — `routes_component.py:41-46`
- §3.3 (metric payload) — insert — ambiguity — `reported_value`/`prior_year_value` are plain JSON numbers bounded only below by 0; fractional values accepted even for cent-denominated keys — `routes_component.py:189-190`, `validation.py:98-105`
- §3.3 (metric domain) — insert — mismatch — a `metric_key` in no domain set at all is `ERR_INVALID_REQUEST` (priority-3 enum), `ERR_METRIC_DOMAIN_MISMATCH` only for a real key foreign to this component — `routes_component.py:188,199`
- §3.3 (correction) — revise — ambiguity — `restatement_note` bounded 1–500 characters when supplied — `routes_component.py:242`
- §3.3 (correction) — insert — ambiguity — correction is unconditional: `restated` true, variance recomputed, `version`++ even when the value is unchanged — `routes_component.py:250-254`
- §3.3 (preparation) — insert — ambiguity — preparation rewrites each metric's `variance_pct` without refreshing that metric's `updated_at`/`version` (only recomputation that doesn't version its row) — `routes_component.py:107-108`
- §3.4 (adjudication) — insert — ambiguity — `adjudication_note` on ACCEPT/WAIVE has no minimum, max 500, and is stored on all three branches (waiver included), null when omitted — `routes_component.py:311,324,327`
- §3.6 (headcounts) — insert — ambiguity — `entry_status` filters no headcount and neither rate; `RETENTION_FT` reads FULL_TIME and PART_TIME alike — `svc_cohort.py:14-32`
- §3.6 (divergence) — revise — ambiguity — `rate_divergence_pp` is derived, absent from the cohort row, and the rate-summary `data` is exactly eight named fields (no `id`/`status`/`version`), read without recomputation — `routes_cohort.py:100-113`, `svc_cohort.py:40-46`
- §3.6 (exclusion claim) — insert — ambiguity — a `DENIED → CLAIMED` refiling replaces only code and note, leaving `exclusion_reviewed_by_user_id`/`review_note` standing; a claim never recomputes or versions the cohort — `routes_cohort.py:204-208`
- §3.6 (exclusion review) — revise — ambiguity — `review_note` bounded 1–500 characters when supplied — `routes_cohort.py:217,231-232`
- §3.6 (cascade trigger) — revise — mismatch — cascade fires on any approval or reversal-of-approval on a LOCKED cohort regardless of whether `federal_rate_pct` actually changed; a denial of a merely CLAIMED exclusion never fires it — `routes_cohort.py:236-237`, `svc_cohort.py:65-68`

No truncation: `wc -l` = 512; last line = the `ERR_REJECTION_REASON_REQUIRED` row. Verified as already uniquely pinned (no change): variance formula and inclusive 10.0/25.0 thresholds, round-then-sum per-FTE expense and its null cases, the five-branch edit-check cascade plus the trailing `UNMAPPED_ELEMENTS` check, `edit_status` derivation with the zero-checks→CLEARED special case and `fatal_open_count`, certify/submit/revert precondition ordering, `bubble_archive`, coverage computation, all five cohort headcounts and both rate variants, lock preconditions and their evaluation order, and every list filter set in the partition.

### Pass 3 of 3 — external submissions/reconciliation + publications/restatements + disclosure avoidance
Partition: `routes_external.py`, `routes_pub.py`, `svc_pub.py`, `routes_disclosure.py`, `svc_disclosure.py`.

Integrity confirmation: did **not** `cp`, `Write`, or overwrite `PRD_COMPLETED.md`. All 11 changes were surgical `Edit` calls. Pass 1's edit survives (`followed by exactly 20 characters drawn from the uppercase letters` → 1 hit); pass 2's survives (`Thirteen operations declare this band explicitly` → 1 hit; the §2.6 insert was appended after that sentence, not over it). §5 table intact: 68 `ERR_` rows.

Size: 512 lines before → 512 after; 129,748 → 131,992 chars (+2,244).

Counts: 10 ambiguity-pins, 1 mismatch-revision.

- §2.3 — insert — ambiguity — crosstab-cell listings: a `(dimension_group, dimension_key)` tie (only possible across requests in an unfiltered list) falls straight to the insertion-order tie-break, not to `created_at` — `routes_disclosure.py:165`, `svc_disclosure.py:7`
- §2.6 (fourth band) — revise — mismatch — the blanket "any mutation of any child of an `ARCHIVED` cycle" is scoped: the four bands are exhaustive, and reconcile, variance-override, publication withdrawal, restatement filing/approve/reject and cell creation consult posture not at all, staying available at every posture including `ARCHIVED` — `routes_external.py:94,133`, `routes_pub.py:80,100,138,163`, `routes_disclosure.py:124` (no `require_*` call in any of them)
- §3.7 (publish) — insert — ambiguity — publication inspects neither the component's `prep_status` nor the survey domain of `metric_key` (free 3–64-char string, need not name a reported metric), and `published_value` may be any JSON number incl. negative — `routes_pub.py:32-39`
- §3.7 (filing) — insert — ambiguity — `proposed_value` is any JSON number, unbounded in sign/magnitude — `routes_pub.py:104`
- §3.7 (filing) — insert — ambiguity — a publication already at `RESTATEMENT_PENDING` accepts a further filing, stays there, still advances `version`, incumbent superseded — `routes_pub.py:111-118`
- §3.7 (materiality) — insert — ambiguity — a null `proposed_value` (only the cohort cascade can supply one, when the recomputed rate is null) yields null `delta_pct` and `public_notice_required` false — `svc_pub.py:9-10`
- §3.7 (reject) — insert — ambiguity — rejection asks nothing of the publication's `publication_status`; only the request's `SUBMITTED` state is checked (unlike approval) — `routes_pub.py:170-173`
- §3.7 (reject) — insert — ambiguity — both approve and reject answer with the restatement request in `data`, never the publication — `routes_pub.py:160,187`
- §3.8 (create) — insert — ambiguity — the uniqueness triple is compared exactly and case-sensitively, with `target_type` playing no part in the scan — `routes_external.py:49-54`
- §3.9 (cells) — insert — ambiguity — cell uniqueness is exact/case-sensitive, and the `RECEIVED` state is the operation's only gate (no posture check, so cells are still accepted after a reopen) — `routes_disclosure.py:131-139`
- §3.9 (release) — insert — ambiguity — `release_note` is bounded at 1 to 2000 characters — `routes_disclosure.py:103`

Deliberately left alone (already pinned uniquely and matching impl): allowance tiering on the raw delta, the five-step reconciliation pass, tolerance table, transmit gates and deadline equality, half-open overlap geometry excluding `WITHDRAWN`, the ledger arithmetic at 1 dp, supersede/void fates, screening's refusal branch computing nothing, both suppression passes with their victim tie-break and residual-risk rule, controlled rounding to base 5, the release branch split and the `EXTERNAL`/`MEDIA` safety gate, all listing filters, and every error code/status. No other PRD-contradicts-impl case found beyond the §2.6 archived-mutation over-claim.

### Orchestrator verification of the final artifact

- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (131,992 vs 123,374 chars) — the scan genuinely ran.
- 32 lines differ from `PRD_FINALIZED.md` (64 diff lines = 32 changed pairs), consistent with the three passes' reported edit counts; line count held at 512 throughout, so no pass added or dropped structure.
- All three passes' edits coexist in the final file: pass-1 marker phrase 1 hit, pass-2 marker phrase 1 hit, pass-3 `release_note` present. No pass clobbered another.
- Document still ends at the §5 error-code table's final row (`ERR_REJECTION_REASON_REQUIRED`) with all 68 `ERR_` rows present — no truncation.
- Step 9 edits documentation only; `implementation/` and `test_suite/` were untouched after Step 7, so the verified 8/8 × 104/104 green sweep still stands.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` written; all 9 steps done.
