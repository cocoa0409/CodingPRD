# Worklog — task_2857_packaging_extended_producer_responsibility_reporting

## Step 1: Create task directory — 2026-09-05T07:31:40.636Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2857_packaging_extended_producer_responsibility_reporting` and its `workspace/` subdirectory. Index 2857 was pre-assigned by the orchestrator invocation; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-05T09:13:54.576Z

All three scaffold artifacts are complete and lint-clean.

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2857_packaging_extended_producer_responsibility_reporting/`):
- `SCAFFOLD.yaml` — 2696 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3009 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5781 lines

SCAFFOLD.yaml counts (§1.0–§1.7):
- 12 entities, 9 state machines (PackagingReport carries two parallel dimensions), 2 concurrency rules
- 12 calculations, 53 ordered validations, 60 endpoints, 63 errors, 4 roles
- Top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — neither design key present

Design files:
- §1.8: 9 difficulty rule_ids x 24 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant)
- §1.9: 87 instances across all nine guide sections — 53 with full `test_recipe`s and 34 `excluded_because` stubs (entities 11/11, state_machines 7/15, calculations 7/16, validations 5/11, endpoints 4/5, errors 11/17, rbac 4/4, cross_cutting_complexity_layers 3/7, consistency_model 1/1)

Verification:
- `scaffold_lint.py` -> `VERDICT: clean lint` (1528 calls scanned across §1.8+§1.9; 60 endpoints, 12 entities; all FKs reverse-reachable)
- All 63 declared error codes are exercised by at least one §1.8 or §1.9 instance; no undeclared `ERR_*` is referenced
- Every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name; no stub carries a `test_recipe`; instance names unique across both design files; every `${placeholder}` bound by an earlier `captures:`

Two internal facts worth flagging to the PRD/test stages: `ERR_REPORT_NOT_UNDER_VERIFICATION` (priority 11) and the publish-time truncation of an open-ended `PUBLISHED` fee schedule are both unreachable through the public API (priority 38 and validation 32 respectively pre-empt them); rather than weaken the design, both facts are stated explicitly in the corner instances that come closest to them (`engagement_start_and_second_opinion_after_opinion_issued_rejected`, `pinned_fee_schedule_prices_the_report_after_a_later_schedule_is_published`). One inconsistency was fixed in `SCAFFOLD.yaml` during authoring: validation priority 46's `applies_to` said `decision == ABANDON`, which is not a declared close decision, and is now `decision == REJECT`.

Orchestrator check: `grep -rn "harder than expert"` over the task dir returned nothing — the difficulty directive did not leak into any scaffold artifact.

## Step 3: Copy shared files — 2026-09-05T09:14:10.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T09:25:46.905Z

PRD generated at `workspace/PRD.md` — **466 lines / 12,912 words / 95,944 bytes**, built with 8 chunked appends. Ends cleanly at the last row of the §5 error table; no audit footer. Neither design file was opened, and no sibling task directory was read.

Sections:
- §1 Introduction (3 paragraphs: state-by-state divergence pain, system scope, two design commitments)
- §2 Global Specifications — 2.1 Access Control · 2.2 Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Properties & Logical Clock · 2.5 Request Admission Order · 2.6 Weights, Money and Rounding · 2.7 Multi-State Policy Triple · 2.8 Version Pinning and OCC · 2.9 Cascades & Conserved Aggregates · 2.10 Rule Evaluation Priority · 2.11 Segregation of Duties
- §3 Business Logic — 9 subsections: Obligated Party · SKU Material Data · State Programs & Periods · PROs & Fee Schedules · Registration & Exemption · Membership · Filing/Verification/Correction · Pricing & Eco-Modulation · Invoicing, Conservation & Redesign
- §4 Endpoint Definitions (4 columns) · §5 Error Code Catalogue (2 columns)

Hard contracts reported by the generator:

```
Field coverage check:
- entities[].fields: 90 required, 90 present, 0 missing
- endpoints[].request_body: 66 required, 66 present, 0 missing
- endpoints[].query_params: 25 required, 25 present, 0 missing
- nested array element / computed-output keys: 25 required, 25 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 53 checked, 53 expressed in prose (§2.5 steps 1-7 + §2.10 seven ordered groups), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_pro_version / expected_registration_version + error_id + 412), 0 missing
- state_machines[].transitions: 9 machines / 44 transitions checked, 44 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed (incl. all 6 variant pairs and all 11 constants embedded in business context), 0 missing
- validations[] conditions: 53 checked, 53 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 60 endpoints checked, all side effects and applies_to sets expressed, 0 missing
- entities[].fields[] structured content: 90 checked, 90 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (PROVISIONAL/FINAL, ENTITY_LEVEL/GROUP_LEVEL, BASELINE_UNITS/PROJECTED_UNITS, PER_LINE_THEN_SUM/SUM_THEN_ROUND, ACCEPT/REJECT, APPROVE/REJECT, FINALIZE/REJECT, UNQUALIFIED vs QUALIFIED/ADVERSE), 8 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 927
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 byte-identical to `section-2.2-response-structure.md` (diff clean); §4 table contains exactly 60 rows matching scaffold method+path with per-row role sets verified against `endpoints[].roles`; §5 table contains exactly 63 error rows with matching HTTP statuses; all 63 error IDs also appear in §2/§3 narrative; all state values, enum values and the 4 role names present verbatim; no fuzzy/approximating words (only two non-numeric uses of "about").

Two content notes for downstream stages: the scaffold's validation priority 14 lists a Producer status `REGISTERED` that is not a declared Producer enum value — the PRD states only the `OBLIGATION_DETERMINED` requirement. And `ERR_REPORT_NOT_UNDER_VERIFICATION` and the publish-time truncation of an open-ended `PUBLISHED` schedule are pre-empted by higher-priority rules; both are nonetheless expressed in the PRD (§2.10, §3.4, §3.7) so an implementer can reach them.

Orchestrator truncation guard: verified independently — `wc -l` = 466, tail ends at the final `ERR_FINDINGS_NOTE_REQUIRED` table row (a real section boundary, not mid-sentence); `grep -c "^| \`ERR_"` = 63 error rows; endpoint table = 60 method rows; no difficulty-directive text present. PRD accepted without regeneration.

## Step 6: Generate implementation — 2026-09-05T09:56:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill's isolation requirement. Step 6 returned first, so its entry is recorded here ahead of Step 5's.)

Implementation is complete and verified.

Modules emitted (2,903 lines total, all `py_compile`-clean). Root at `workspace/implementation/`:

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | guarded `pip install`, `exec python3 app.py` |
| `app.py` | 67 | blueprint registration, `ApiError`/HTTPException handlers, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 94 | in-memory dicts for the 12 collections, logical clock (starts `2026-08-01T00:00:00Z`), id/seq/instant helpers |
| `errors.py` | 101 | 63-code catalogue + `ERR_NOT_FOUND` fallback, `ApiError`, `fail()` |
| `envelope.py` | 75 | `meta`/`response_type`/`data` envelope, pagination meta, Decimal->JSON, `_`-prefixed internals stripped |
| `validation.py` | 190 | shape layer (all failures `ERR_INVALID_REQUEST`), enum tables, decimal-precision checks |
| `auth.py` | 129 | header auth, RBAC decorator, ownership/verifier checks, per-request `version` dedupe |
| `calc.py` | 548 | rollups, posture, exemption analysis, membership fee, eco-modulation, tier selection, both assessment variants, rounding orders, admin fee, redesign projection |
| `routes/common.py` | 70 | pagination window + filters |
| `routes/producers.py` `skus.py` `programs.py` `pros.py` `registrations.py` `memberships.py` `reports.py` `engagements.py` `invoices.py` `misc.py` | 1,529 | the endpoint surface |

Coverage:
- **60 endpoints registered** (matches the §4 table exactly, verified via `app.url_map`).
- **64 error ids** (all 63 catalogued codes plus a 404 `ERR_NOT_FOUND` fallback for unmatched routes).
- Store is empty at boot (all 12 collections: 0), no seeding anywhere; logical clock reads `2026-08-01T00:00:00Z` on a fresh process.

Smoke test (port 29548, killed by recorded pid only): full happy path passed end to end — producer -> sku + component -> activate -> determine-obligation -> state program + period -> pro -> fee schedule + publish (OCC on `expected_pro_version`) -> registration submit/decide -> membership create (OCC on `expected_registration_version`) / approve / pay -> report + line -> clock set -> submit -> PROVISIONAL assess -> fee-breakdown -> engagement -> start -> UNQUALIFIED opinion -> FINAL assess -> invoice -> close FINALIZE -> invoice void.

Spot-checked arithmetic all correct: 20 000 units x 12.50 g = 250.000 kg; PCR 40 % -> bonus 20 %, malus 0, net -20 % -> line 2 000 cents; admin 500 bps -> 100 cents, total 2 100; membership fee 100 000 + ceil((1250-500)/1000) x 50 000 = 150 000; `fee_schedule_version_pinned` = 2; producer balance returned to exactly 0 after the void (conservation holds).

Second pass exercised the hard paths: `ERR_VERIFIER_ROTATION_REQUIRED` (prior FINALIZED report's verifier), `ERR_FINDINGS_NOTE_REQUIRED`, and the full six-hop QUALIFIED cascade — report `CORRECTION_REQUIRED` + `fee_status VOIDED`, `correction_due_at` = opinion instant + 10 days, ytd fell 300 -> 250, posture `AT_RISK`, membership -> `PROBATION` — then resubmit restored `correction_round` 1, `fee_variant_applied NONE`, ytd 300, posture `COMPLIANT`, membership back to `ACTIVE`.

Two judgement calls worth flagging: for line mutations the impl ordered `ERR_REGISTRATION_NOT_ACTIVE` before `ERR_REPORT_NOT_IN_DRAFT` (per §2.10 group 1 and scaffold priorities 8 < 10, against §3.7's sentence order — only observable for a BLOCKED report under a SUSPENDED registration); and numeric weight/money fields reject JSON strings as `ERR_INVALID_REQUEST` per §2.5's type rule.

## Step 5: Generate unit tests — 2026-09-05T10:53:06.000Z

(Launched concurrently with Step 6; returned second.)

All closing verification passes are green. Final state.

Output locations (verified at the TASK ROOT, not under `workspace/`):
- `test_helpers/` — 9 files, 2736 lines: `__init__.py` 260, `api_client.py` 384, `api_errors.py` 163, `assertions.py` 421, `constants.py` 103, `factories.py` 339, `fixtures.py` 665, `test_users.py` 70, `types.py` 331
- `test_suite/` — `conftest.py` 48 + 18 test modules, 7515 test lines

`find workspace -name test_suite -o -name test_helpers` returns nothing; `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `sweep.sh`, `implementation/` (never opened).

Test modules (106 tests total).

Queue A — difficulty, 49 tests:
| file | lines | tests |
|---|---|---|
| test_01_dual_variant_calculations.py | 408 | 6 |
| test_02_combinatorial_formulas.py | 401 | 6 |
| test_03_non_linear_state_machines.py | 247 | 4 |
| test_04_transitive_cascades.py | 298 | 4 |
| test_05_validation_priority_conflicts.py | 309 | 6 |
| test_06_boundary_precision.py | 481 | 7 |
| test_07_cross_entity_state_dependency.py | 355 | 6 |
| test_08_resource_temporal_overlap.py | 419 | 6 |
| test_09_compensating_invariants.py | 330 | 4 |

Queue B — corner, 57 tests:
| file | lines | tests | corner section |
|---|---|---|---|
| test_10_entity_lifecycle.py | 696 | 11 | entities (11) |
| test_11_state_machines.py | 506 | 8 | state_machines (7) |
| test_12_calculations.py | 550 | 7 | calculations (7) |
| test_13_validation_gates.py | 413 | 6 | validations (5) |
| test_14_endpoint_behaviour.py | 341 | 4 | endpoints (4) |
| test_15_error_catalogue.py | 1071 | 13 | errors (11) |
| test_16_role_authorization.py | 316 | 4 | rbac (4) |
| test_17_concurrency_and_pinning.py | 273 | 3 | cross_cutting_complexity_layers (3) |
| test_18_read_after_write_consistency.py | 101 | 1 | consistency_model (1) |

Coverage / tag audit:
- 77 non-stub design instances (24 queue A + 53 queue B); 106 `Design:` lines; **0 dangling tags, 0 uncovered instances**.
- Every test carries exactly one `Design:` line (per-file `def test_` count == `Design:` count in all 18 files) and it is the final docstring line in all 106 cases (0 violations).
- Every difficulty instance has >=2 tests (23 have 2, `group_revenue_exactly_at_small_producer_threshold` has 3); every corner instance has >=1.
- **SKIPPED instances: none.** Two needed PRD-legal setup substitutions rather than a skip: corner `assessment_refuses_a_material_type_absent_from_the_pinned_schedule` (the design's `restate_revenue` route leaves the registration permanently unable to file, so it was rebuilt as two activated SKUs under one determination, ytd 7.500 kg) and corner `fee_schedule_tier_shape_and_empty_rate_set...` (closed `[2026-01-01, 2026-03-31]` window to dodge a DRAFT-overlap ambiguity). `excluded_because:` stubs were not translated.
- Design-vs-PRD conflicts resolved in the PRD's favour: `FOOD` -> `FOOD_DRY`; fieldwork instants -> `YYYY-MM-DD`; an invoice inserted before every close `FINALIZE` (PRD §3.9 requires `fee_status == INVOICED` on both paths); `ERR_OBLIGATION_NOT_DETERMINED` at 409, not 422.

Hygiene:
- `python3 -m py_compile` over all 27 emitted `.py` files: COMPILED. `python3 -m pyflakes`: fully clean.
- One helper fix this pass: `test_helpers/__init__.py` had an `__all__` covering only the framework primitives, so pyflakes flagged all 118 domain re-exports as unused. `__all__` now lists all 118 names (`import test_helpers` verified).
- `grep -rin scaffold test_suite/ test_helpers/`: no matches — docstrings cite the PRD only.
- `__pycache__` dirs from the compile checks were removed. No `pkill`, no worklog edit, scratch confined to `/tmp/task_2857_epr_scratch/`.

Orchestrator check: confirmed `test_helpers/` and `test_suite/` are at the task root (not under `workspace/`); 106 `Design:` tags == 106 `def test_` functions.

## Step 7: Run tests and iterate — 2026-09-05T11:31:49.000Z

All 8 rounds are green. Final report:

Iterations run: 3
- **Iteration 1** — 95/106 in every round, 11 deterministic failures (no flakiness, no load artifacts).
- **Iteration 2** — regression from the fix agent's own fixture edit (a missing `extra_skus` parameter on `deep_ca_chain`); all 11 original targets confirmed fixed.
- **Iteration 3** — 106/106 in all 8 rounds.

Tests deleted: **None.** No test failed the PRD-coverage or unique-derivability gate outright.

Fixes applied to `test_suite/`:
- **`test_13_validation_gates.py` :: `test_the_line_append_answers_each_layer_in_its_declared_order`** — the third call sent an unknown `sku_id` to a `SUBMITTED` report and expected `ERR_REPORT_NOT_IN_DRAFT`. §2.5 fixes body foreign-key existence at step 5 and state at step 7, so `ERR_SKU_NOT_FOUND` must win. Split into two faithful calls: submitted report + unknown unit -> `ERR_SKU_NOT_FOUND` (404), then submitted report + valid own unit -> `ERR_REPORT_NOT_IN_DRAFT` (409). Docstring corrected to state the PRD order.
- **`test_15_error_catalogue.py` :: `test_assessment_refuses_a_material_the_pinned_schedule_does_not_price`** and **`test_assessment_refuses_a_pinned_schedule_whose_window_ended_too_early`** — dropped the `tier_basis_kg=None` / `fee_variant_applied=None` kwargs (DEFAULT-VALUE SILENCE, design tags `Corner/errors/assessment_refuses_a_material_type_absent_from_the_pinned_schedule` and `.../assessment_refuses_a_pinned_schedule_that_was_not_effective_for_the_period`). PRD only says these fields are "cleared back to their defaults" and never says what those defaults are, so `null` vs `0`/`"NONE"` is not derivable. The covered assertions (`fee_status=UNASSESSED`, `fee_subtotal_cents=0`, `line_fee_cents=0`, the error id itself) were kept.
- **`test_02_combinatorial_formulas.py` :: `_two_component_report`** — used the new `extra_skus` fixture hook instead of re-running `determine-obligation` on an already-determined producer (see below).

Fixes applied to `test_helpers/`:
- **`fixtures.py` — `determined_producer` / `_build_chain` / `base_ca_chain` / `deep_ca_chain`** — added an `extra_skus` hook that creates and activates additional stock keeping units *before* the single obligation determination. The old `test_02` helper built its second SKU after the chain had already determined the producer and then called `determine-obligation` a second time, which PRD §3.1 refuses with `ERR_INVALID_STATE` ("It may only be performed while the producer is in `DRAFT`"). That was a fixture precondition violation, not an implementation bug; the two affected tests' expected figures (39600 / 23100 / 62700 cents, rollup 2000.000 kg) were already correct and now pass unchanged.

Fixes applied to `implementation/`:
- **`routes/pros.py` — `windows_conflict`** — was widening the candidate window by one day at each end, so two abutting fee-schedule windows were rejected as an overlap. PRD §3.3 defines "touch" as "one ending exactly where the next begins" (same date value); with §3.4's inclusive-at-both-ends windows that case is already an intersection, and §3.4's own publication truncation deliberately produces abutting windows (`effective_to` = new `effective_from` minus one day), so abutting must be legal. Now a plain inclusive-interval intersection test. Fixed 4 tests.
- **`routes/engagements.py` — `create_engagement`** — the "report must be `SUBMITTED`" guard ran before the one-engagement-per-report check, which made `ERR_ENGAGEMENT_ALREADY_OPEN` unreachable (an open engagement always implies the report already sits in `UNDER_VERIFICATION`). Moved the guard after the duplicate check, matching §2.10's priority-5 placement of that error; segregation and rotation still precede both.
- **`routes/reports.py` — `close_report`** — now `touch(registration)` unconditionally. Close-out is one of the ten operations that recompute `compliance_posture`, and §2.4 states a derived-field refresh is itself a mutation that advances `version`; without it the registration's version did not move, so the subsequent stale-version membership create was wrongly accepted.

No endpoint, field, side effect or seeded data was added, and no PRD-required check was weakened.

Final sweep evidence:
| results file | passed / total |
| --- | --- |
| results.1.json | 106 / 106 |
| results.2.json | 106 / 106 |
| results.3.json | 106 / 106 |
| results.4.json | 106 / 106 |
| results.5.json | 106 / 106 |
| results.6.json | 106 / 106 |
| results.7.json | 106 / 106 |
| results.8.json | 106 / 106 |

`worklog.md` was not touched by the subagent. Orchestrator independently confirmed all 8 `results.$i.json` read 106/106 (baseline sweep had been 95/106 in all 8 rounds), and that the suite still holds 106 tests (0 deletions).

## Step 8: Finalize PRD — 2026-09-05T11:43:02.000Z

Step 8 was NOT skipped: Step 7 applied 3 `implementation/` fixes plus test_suite/test_helpers fixes, so the skip condition (zero fixes) did not hold.

PRD_FINALIZED.md is written. Both files are 466 lines (no truncation); the patch touches 5 sentences across 4 subjects.

Line counts:
- PRD.md: 466 lines / 95,944 bytes
- PRD_FINALIZED.md: 466 lines / 97,594 bytes
- Line-count delta: 0% (5 hunks, 10 changed lines = 2.1% of lines; +1.7% bytes)

Changes:
- **§3.4 (fee-schedule effective windows)** — *revise* — replaced "may neither overlap nor even touch" with a plain inclusive-interval intersection rule: sharing the single boundary day is a collision, but two windows that abut without sharing a day (one ending the day before the next begins) are accepted; kept the open-ended blocking clause verbatim — `implementation/routes/pros.py:80-93` (`windows_conflict`), used at `pros.py:117`.
- **§3.7 (report creation)** — *insert* — pinned the three fee-figure defaults: `tier_basis_kg` `0.000`, `fee_subtotal_cents` 0, `fee_variant_applied` `NONE`, and stated that a refused assessment writes none of them — `implementation/routes/reports.py:76-88`.
- **§3.7 (resubmission)** — *revise* — "cleared back to their defaults" now names the values: 0, `0.000`, `NONE` — `implementation/routes/reports.py:303-305`.
- **§3.7 (verifier assignment)** — *insert* — the report-must-be-`SUBMITTED` check is answered with generic `ERR_INVALID_STATE` (409) and runs *after* segregation, rotation and the one-open-engagement check (and before the capacity count), because otherwise `ERR_ENGAGEMENT_ALREADY_OPEN` is unreachable — `implementation/routes/engagements.py:57-69`.
- **§3.7 (close-out)** — *insert* — the registration's `version` advances by exactly 1 on every close-out, even when the recomputed posture equals the stored one — `implementation/routes/reports.py:338-343`.

No PRD edit for the two fixture/test-only items: the test_13 admission-order fix is already uniquely determined by §2.5 (body FK at step 5, state at step 7), and the `extra_skus` fixture hook was a precondition violation of §3.1's DRAFT-only determination rule.

Per-edit pre-edit search log:

**Edit 1 — §3.4 window conflict.** (a) Subject: fee-schedule effective-window conflict semantics and `ERR_FEE_SCHEDULE_EFFECTIVE_OVERLAP`. (b) Enumerated: `routes/pros.py:80-93` `windows_conflict` (inclusive intersection, null-end handling both directions); its only callsite `pros.py:114-120` in `create_fee_schedule` (iterates all schedules of the pairing regardless of `status`); `pros.py:112` (`effective_to < effective_from` -> `ERR_INVALID_REQUEST`); `pros.py:181-194` publish truncation (`effective_to` = new `effective_from` - 1 day, producing exactly the abutting shape); `routes/reports.py:261-266` + §3.8's separate effective-window-vs-period check (a different rule, untouched); `routes/programs.py:104-107` half-open period overlap, to verify the "stricter than reporting periods" comparison is still true; grepped `EFFECTIVE_OVERLAP` across `test_suite/` (`test_08:169-275` confirms same-day refused, day-adjacent accepted, open-ended blocks later). (c) Adjustment: kept the rule status-agnostic ("an existing window of the same pairing", no `status` qualifier) since the impl ignores schedule status; re-anchored the "stricter" claim on the inclusive-vs-half-open distinction instead of on the deleted "touch" prohibition, so it stays true; used "intersect" rather than "overlap in days" so the null-end cases keep reading correctly.

**Edit 2 — §3.7 report fee-figure defaults.** (a) Subject: initial/default values of `tier_basis_kg`, `fee_subtotal_cents`, `fee_variant_applied`. (b) Enumerated: `routes/reports.py:69-89` (creation literals `0.000`/0/`NONE`); `routes/reports.py:303-305` (resubmit clears to the same three); `calc.py:435-438` (`assess_report` writes them); `calc.py:458-468` (`fee_breakdown` echoes the stored `fee_variant_applied`, so it returns `NONE` for an unpriced report); all `fail()` sites in `routes/reports.py:242-266` and `calc.py:379-385` to confirm every assessment refusal precedes any write (`check_material_rates` runs before `assess_report`, making the inner `calc.py:415` fail unreachable); `validation.py` enum lists (no `fee_variant` enum constrains the stored field); §4 endpoint table (no field-level defaults declared anywhere else); `test_suite/test_03:146-155` (surviving assertion of `NONE` after resubmission). (c) Adjustment: avoided the tempting universal "`NONE` means no assessment has ever succeeded" — false after a correction/resubmit cycle — and phrased the refusal case as "reads exactly the values it held before the attempt", which is true both for never-priced and previously-`PROVISIONAL` reports. Also limited the pinning to the three fee fields rather than all creation literals, since the weight/count/null fields are already derivable.

**Edit 3 — §3.7 verifier-assignment check order.** (a) Subject: placement and error code of the report-position guard at engagement creation. (b) Enumerated: `routes/engagements.py:50-101` full check sequence (report resolution -> segregation -> rotation -> already-open -> report `SUBMITTED` -> capacity -> fieldwork window); `engagements.py:136-139` and `156-157` (start / issue-opinion use the distinct `ERR_REPORT_NOT_UNDER_VERIFICATION`); `errors.py:25` (`ERR_INVALID_STATE` -> 409); §2.5 step 7 and §2.10 priorities 1/3/5 to check for contradiction. (c) Adjustment: scoped the sentence to the assignment endpoint only and added the explicit "not the §2.5 step-7 placement" note, so the generic §2.5/§2.10 statements and the two engagement actions that use `ERR_REPORT_NOT_UNDER_VERIFICATION` are not redefined.

**Edit 4 — §3.7 close-out registration version.** (a) Subject: whether a posture refresh advances `Registration.version` when the verdict is unchanged. (b) Enumerated: `routes/reports.py:338-343` (unconditional `touch(registration)`); `calc.py:249-255` `set_posture` (touches only on change) and `calc.py:236-246` `reconcile_memberships` (touches memberships only on change); `auth.py:81-90` `touch` (per-request idempotent, so the bump is exactly 1); every other `set_posture` callsite — `reports.py:225,308` and `engagements.py:183` (via `calc.recompute_ytd`, which touches unconditionally at `calc.py:190`), `registrations.py:113,131,135,151,171,198`, `memberships.py:59,121`, `producers.py:117` — all of which already touch the registration for an independent reason. (c) Adjustment: scoped the claim to close-out and to "advances by exactly 1", rather than asserting the general rule that any posture recomputation bumps the version — the general form would misdescribe `set_posture`'s conditional touch if it were ever reached alone.

Orchestrator check: PRD_FINALIZED.md is 466 lines / 97,594 bytes vs PRD.md's 466 lines / 95,944 bytes — a real patch, not a byte-identical copy.

## Step 9: Complete PRD — 2026-09-05T12:06:38.592Z

Step 9 always runs. Orchestrator decision (recorded per the autonomy directive): rather than one subagent scanning all 19 implementation modules against a 466-line PRD — a shape that historically produces a byte-identical `PRD_COMPLETED.md` because the scan never really happens — Step 9 was run as **three sequential passes partitioned by implementation module**, all editing the one shared `workspace/PRD_COMPLETED.md`. Pass 1 alone performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to copy and were told to read the current text of `PRD_COMPLETED.md` before editing any paragraph an earlier pass had touched, so no pass reverted another. Net effect: 54 edits (17 + 15 + 22), +13,185 chars over PRD_FINALIZED.md.

### Pass 1 — `app.py`, `store.py`, `errors.py`, `envelope.py`, `validation.py`, `auth.py`, `routes/common.py`, `routes/producers.py`, `routes/skus.py`, `routes/programs.py`, `routes/misc.py`

Step 0 confirmation: pass 1 ran `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` after verifying PRD_FINALIZED.md was exactly 466 lines.

PRD_FINALIZED.md 466 lines / 97,594 chars -> PRD_COMPLETED.md 466 lines / 102,356 chars (+4,762 chars). All edits in-paragraph; no new lines, paragraphs or sections. 17 changes — 16 ambiguity-pins, 1 mismatch-revision.

- §2.1 — revise — ambiguity — ownership comparisons bind only their own role; regulator/verifier never refused for ownership — `auth.py:96-104`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — `envelope.py:10,14`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from host real time, not the logical clock — `envelope.py:20`, `store.py:63-68`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion sequence — `store.py:92-94`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` and bad booleans are 400; blank query values treated as omitted; identifier filters are not resolved, so a nonexistent id yields an empty page not a 404 — `routes/common.py:13-61`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are wall-clock audit stamps, outside the logical clock's reach — `auth.py:89,122-126`
- §2.4 — insert — ambiguity — a row's `version` advances at most once per request; a row minted by the request stays at 1 — `auth.py:75-90`
- §2.4 — insert — ambiguity — clock-set response `data` carries the single field `current_utc`, three fractional digits — `routes/misc.py:18`
- §2.5 step 3 — insert — ambiguity — body must be a JSON object; endpoints with no declared fields accept an absent body; numbers must not be strings; over-precision rejected; offset-bearing instants converted to UTC, naive read as UTC; `null` == omitted — `validation.py:38-47,108-127,168-180`
- §2.6 — insert — ambiguity — decimals travel as JSON numbers, so declared precision is not a trailing-zero promise (`0.0`, not `"0.000"`) — `envelope.py:24-32`
- §3.1 — insert — ambiguity — nonexistent `parent_producer_id` -> `ERR_PRODUCER_NOT_FOUND` — `routes/producers.py:26-27`
- §3.2 — insert — ambiguity — duplicate `gtin` within a producer -> `ERR_INVALID_REQUEST`, checked after producer resolution and ownership; `units_sold_annual_estimate` non-negative — `routes/skus.py:49-54`
- §3.2 — insert — ambiguity — `component_seq` starts at 1 and continues past superseded rows; append is admitted in any unit status and touches only the unit (no producer rollup, no `determination_stale`); `unit_weight_grams` non-negative — `routes/skus.py:20,33-38,95-107`
- §3.2 — insert — ambiguity — empty `components` on revise-packaging -> `ERR_INVALID_REQUEST` before the unit is resolved, never `ERR_SKU_HAS_NO_COMPONENTS` — `routes/skus.py:132-141`
- §3.3 — insert — ambiguity — duplicate/malformed `state_code` -> `ERR_INVALID_REQUEST`; `exempt_product_categories` required though it may be empty, entries validated against the five categories — `routes/programs.py:24-48`
- §3.3 — insert — ambiguity — duplicate `period_label` -> `ERR_INVALID_REQUEST`, answered before the overlap check; no ordering enforced between window endpoints — `routes/programs.py:101-107`
- §3.3 — **revise — mismatch** — the per-program reporting-period list was described as a "reverse list"; impl returns default `created_at` ascending — `routes/programs.py:130-136`, `routes/common.py:64-70`
- §3.9 — insert — ambiguity — `candidate_components` is required but may be empty (projected side prices to zero) — `routes/skus.py:169`

Deliberately left unpinned: `app.py`'s out-of-contract fallbacks (unknown path -> `ERR_NOT_FOUND` 404, bad method -> `ERR_INVALID_REQUEST` 405) are outside the declared endpoint surface, and adding `ERR_NOT_FOUND` to the §5 catalogue would have cut against the "twelve type-specific 404 codes" claim in §2.5.

### Pass 2 — `routes/pros.py`, `routes/registrations.py`, `routes/memberships.py`, `routes/invoices.py`

466 lines / 102,356 chars -> 466 lines / 105,574 chars. 15 edits — 12 ambiguity-pins, 3 mismatch-revisions. No `cp` run; all surgical Edits.

- §2.6 — revise — mismatch — "one deliberate exception" to whole-cent integers became two: `rate_cents_per_kg` is a per-kilogram price accepted/carried at up to four decimals, on the rate band and in the audit rows that echo it — `routes/pros.py:50`, `calc.py:339`
- §3.4 ¶1 — revise — ambiguity — duplicate PRO `name` refused with `ERR_INVALID_REQUEST`; `contact_email` validated only as a non-empty string — `routes/pros.py:24-27`
- §3.4 ¶2 — revise — ambiguity — `effective_to` before `effective_from` -> `ERR_INVALID_REQUEST`, answered only after FK resolution and ownership; `material_rates` required but may be empty, so a rate-less draft is legal and the contiguity rule has nothing to check — `routes/pros.py:107,112-113,121`
- §3.4 ¶3 — revise — ambiguity — each rate row must be a JSON object; `tier_min_kg`/`tier_max_kg` non-negative at three decimals, `rate_cents_per_kg` non-negative at up to four — `routes/pros.py:44-56`
- §3.4 publication — revise — mismatch — reordered the guards to the enforced order: `DRAFT` -> `ERR_STALE_PRO_VERSION` -> `ERR_FEE_SCHEDULE_HAS_NO_RATES` (prose previously read rates before the version guard) — `routes/pros.py:172-178`
- §3.4 truncation — revise — ambiguity — scan covers every other `PUBLISHED` open-ended schedule of the pairing in ascending `created_at` order (at most one can qualify); version increments pinned to "the published one always, the truncated one when truncation fires" — `routes/pros.py:181-195`
- §3.5 submit — revise — ambiguity — takes no body; the `DRAFT` self-guard inserted into the guard list, and the stale "Four guards" count replaced by an explicit ordered list (six items) — `routes/registrations.py:93-109`
- §3.5 decide — revise — ambiguity — `reason` must be non-empty when supplied; the registration carries no decision-reason field, so the text is never persisted and is ignored on `ACCEPT` — `routes/registrations.py:122-137`
- §3.5 withdraw — revise — ambiguity — `reason` required and non-empty but not persisted anywhere — `routes/registrations.py:184`
- §3.6 ¶1 — revise — ambiguity — the registration's own status is not examined at application time (any status, including terminal, may be applied against) — `routes/memberships.py:24-38`
- §3.6 ¶1 — revise — mismatch — `ERR_STALE_REGISTRATION_VERSION` fires immediately after the schedule's `PUBLISHED` check and ahead of the determination-staleness and mismatch refusals, though prose lists it last — `routes/memberships.py:28-38`
- §3.6 decide — revise — ambiguity — a `reason` sent with `APPROVE` is ignored; posture reconciliation can carry a just-approved membership straight to `PROBATION` in the same request — `routes/memberships.py:107-122`
- §3.6 payment — revise — ambiguity — `amount_cents` is a non-negative integer; re-recording the same exact amount on an already-`PAID` membership succeeds and just advances `version` — `routes/memberships.py:130-137`
- §3.9 ¶1 — revise — ambiguity — the named membership's `status`, `fee_payment_status` and `fee_schedule_version_pinned` are not examined; brackets read from `fee_schedule_id` — `routes/invoices.py:28-36`
- §3.9 void — revise — ambiguity — the report's submission dimension is never examined (a `FINALIZED` report's invoice can still be voided) and the report's `version` advances regardless of whether the fee dimension changed — `routes/invoices.py:87-96`

Verified in-partition and already uniquely pinned (no change): all list filter sets and role lists for pros/fee-schedules/registrations/memberships/invoices; tier-partition rule incl. the mandatory open-ended top band; window-collision semantics; registration create defaults and blocking-status set; suspend/reinstate report BLOCKED<->DRAFT cascades and the `ERR_DETERMINATION_STALE` answer at reinstatement; membership creation supersession and defaults; membership fee formula; admin-fee bracket keyed on the pre-admin subtotal; balance recompute-from-set.

### Pass 3 — `calc.py`, `routes/reports.py`, `routes/engagements.py`

466 lines / 105,574 chars -> 466 lines / 110,779 chars. 22 changes — 13 ambiguity-pins, 9 mismatch-revisions. No `cp` run; passes 1/2 and Step 8's five pinned items verified intact by grep and not reverted.

- §3.7 — insert — ambiguity — added the non-fee creation defaults (`total_weight_kg`/`fee_basis_weight_kg` `0.000`, `line_count` 0, `verification_required` false, `correction_round` 0, null `correction_due_at`/`submitted_at`/`submitted_by_user_id`) around Step 8's fee-figure sentence — reports.py:76-88
- §3.7 — insert — ambiguity — `units_sold` is a non-negative integer — reports.py:124
- §3.7 — revise — mismatch — line append: registration-`ACTIVE` guard answered **before** the report's `DRAFT` position, and a `BLOCKED` report therefore reports `ERR_REGISTRATION_NOT_ACTIVE`, not `ERR_REPORT_NOT_IN_DRAFT` (PRD previously claimed the opposite) — reports.py:129-132
- §3.7 — revise — ambiguity — line removal is behind the same registration-`ACTIVE` guard, in the same order — reports.py:186-189
- §3.7 — revise — mismatch — submission: ownership first, then the `DRAFT` gate, whose failure is the **generic `ERR_INVALID_STATE`** (`ERR_REPORT_NOT_IN_DRAFT` is reserved for line mutations) — reports.py:202-204
- §3.7 — revise — ambiguity — named the report field `submitted_at` — reports.py:223
- §3.7 — insert — mismatch — `ERR_INVALID_FIELDWORK_WINDOW` is answered **after** segregation/rotation/report-position/capacity — engagements.py:80-81
- §3.7 — insert — ambiguity — "immediately preceding `FINALIZED` report" defined as latest `created_at`, and inside it the latest opinion-issued engagement; no such report => no rotation constraint — engagements.py:28-45
- §3.7 — revise — mismatch — start-fieldwork and issue-opinion examine the **engagement's own** status first (generic `ERR_INVALID_STATE`), then the report position, then segregation, then `ERR_NOT_ASSIGNED_VERIFIER` — engagements.py:136-161
- §3.7 — insert — ambiguity — `findings_note` stored as supplied (kept on `UNQUALIFIED`, null when omitted); both engagement actions answer with the **engagement** row — engagements.py:164-173
- §3.7 — revise — mismatch — correction cascade: report/registration/producer versions always advance (producer even with no invoice), invoice and membership only when those rows actually moved — engagements.py:180-191
- §3.7 — revise — mismatch — resubmit guard order rewritten to the observed structural->temporal->fiscal sequence (`ERR_REPORT_HAS_NO_LINES` before `ERR_CORRECTION_WINDOW_EXPIRED`, ownership first, generic `ERR_INVALID_STATE` for the position) — reports.py:286-295
- §3.7 — revise — mismatch — resubmit keeps the original `submitted_at`; membership `version` advances only when the reconciliation actually moved it — reports.py:306, calc.py:236-254
- §3.7 — insert — ambiguity — close-out `reason` may be empty and is never persisted — reports.py:318
- §3.7 — insert — ambiguity — `FINALIZE` and `REJECT` from any other submission position give the generic `ERR_INVALID_STATE` — reports.py:322,330-331
- §3.8 — revise — mismatch — ownership is compared only when a live membership exists; `ERR_NO_ACTIVE_MEMBERSHIP` is deferred until after the variant position gates (fiscal-last) — reports.py:239-256
- §3.8 — revise — mismatch — fee dimension checked before submission dimension; wrong fee dimension (incl. `FINAL`/`INVOICED`/`VOIDED` under a `FINAL` request) is `ERR_INVALID_STATE`, not `ERR_VERIFICATION_REQUIRED` — reports.py:242-254
- §3.8 — revise — ambiguity — `ERR_MATERIAL_RATE_MISSING` means no row **covering `tier_basis_kg`**, gathered in line `created_at` order, and is raised ahead of the effective-window refusal — calc.py:379-385, reports.py:260-266
- §3.8 — insert — ambiguity — audit-row `comp_fee_exact_cents` is 4-dp-rounded for display while the sum uses unrounded contributions — calc.py:343
- §3.8 — revise — ambiguity — fee-breakdown payload pinned: `packaging_report_id`, `line_count`, `lines[]` (`report_line_id`/`sku_id`/`fee_exempt`/exact/rounded, exempt lines included), `sum_of_line_fee_cents`, `reconciliation_delta_cents` = sum - subtotal; works on a never-priced report; no ownership check — calc.py:443-468
- §3.9 — revise — ambiguity — redesign response pinned: echoes plus `baseline_*` figures, `eco_mod_policy_applied`, `projected_units` as the effective count, the three detail keys (`baseline_eco_mod_detail`/`projected_eco_mod_detail`/`eco_mod_detail`), and `ERR_MATERIAL_RATE_MISSING` from either set with the baseline priced first — calc.py:487-541

Residual note from pass 3: posture computation, exemption analysis (both variants and the one-level group set), membership-fee surcharge arithmetic, eco-modulation order/clamp, tier selection, both rounding orders and the admin-fee bracket were all walked and already pinned uniquely by the existing prose — no edits needed there.

### Orchestrator verification of Step 9 output

- `PRD.md` 466 lines / 95,944 chars; `PRD_FINALIZED.md` 466 lines / 97,594 chars; `PRD_COMPLETED.md` 466 lines / 110,779 chars.
- `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` — 90 changed lines. The scan genuinely ran.
- Structure intact: 5 `##` sections, 63 error-catalogue rows, file ends at the final `ERR_FINDINGS_NOTE_REQUIRED | 422` row — no truncation.
- Hygiene: only one `worklog.md` in the task tree (at the task root, no drift into `workspace/`); `test_helpers/` and `test_suite/` are at the task root, not under `workspace/`; all 8 `results.*.json` from the final green sweep are retained under `workspace/implementation/`.

Pipeline complete: Steps 1-9 all executed, Step 9 wrote `workspace/PRD_COMPLETED.md`.
