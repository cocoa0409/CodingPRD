# Worklog — task_2832_inland_marine_equipment_floater_underwriting

## Step 1: Create task directory — 2026-09-05T03:50:53.918Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2832_inland_marine_equipment_floater_underwriting` and its `workspace/` subdirectory. Index 2832 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-05T05:50:00.000Z

Done. All three scaffold artifacts are complete and lint-clean.

## Output (all under `/home/ubuntu/github/CodingPRD/tasks/task_2832_inland_marine_equipment_floater_underwriting/`)

| file | lines | top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 3461 | §1.0–§1.7 only (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2093 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4789 | `scaffold_corner_design` |

## SCAFFOLD.yaml shape
11 entities (Policy, CoveragePart, RateRule, EquipmentItem, Jobsite, InstallationFloater, Vehicle, TransitShipment, ValueReport, Claim, LedgerEntry), 9 state machines (Claim carries two parallel axes), 2 concurrency rules (Policy.version on schedule adds, CoveragePart.version on value-report filing), 17 calculations, 67 validations with pinned priorities, 56 endpoints, 63 errors, 5 roles (`segregation_of_duties`). Complexity layers: `dual_variant_calculation`, `rate_threshold_triggers`, `cascading_side_effects`, `optimistic_concurrency`; `consistency_model: immediate`; `entity_topology: hybrid`.

Rule families covered: scheduled-vs-blanket dual rating, four valuation bases (ACV depreciation floor, RC index, agreed value, stated amount), five-factor combinatorial equipment premium with geo/jobsite credits and a 2500 bp cap, jobsite security tiering (credit on equipment, multiplier on floaters), installation-floater acceptance-vs-occupancy termination, transit limits with catastrophe-zone capping and conveyance windows, reporting forms with underreporting penalty and delinquency sweep/suspension, repair-vs-total-loss settlement with loss-of-use and salvage, short-rate vs pro-rata cancellation, referral thresholds (premium `>=`, TIV `>`), and a conserved aggregate-capacity invariant.

## Design indices
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: 9 rule families, **23 instances** — dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 4, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 2.
- `SCAFFOLD_CORNER_DESIGN.yaml`: 9 sections, **84 instances** (71 with full test recipes + 13 `excluded_because` stubs): entities 11, state_machines 17 (3 stubs), calculations 11 (4), validations 18 (4), endpoints 7, errors 5, rbac 6 (1), cross_cutting_complexity_layers 7 (1), consistency_model 2.

## This session's closing work
Closed the last three untested behaviours by splicing three new instances (python splice-before-marker, so nothing mis-nested): `corner_referral_decline_voids_parts_and_pending_floaters`, `corner_salvage_waived_branch_credits_nothing_and_still_closes` (both into `state_machines`) and `corner_loss_of_use_extension_truncates_at_the_part_max_days` (into `calculations`).

Authoring the DECLINE instance exposed a real §1.4 defect: the DECLINE cascade VOIDs every coverage part, so my earlier priority-41 prose claiming `ERR_POLICY_NOT_MUTABLE` was observable "on a DECLINED or EXPIRED policy (whose parts stay ACTIVE)" was false. Fixed both the priority-41 and priority-40 checks in `SCAFFOLD.yaml`: part-scoped paths are observable only on an EXPIRED policy; a CANCELLED **or DECLINED** policy's part hits `ERR_PART_VOID` first; the policy-scoped `POST /policies/{id}/coverage-parts` has no part target and yields `ERR_POLICY_NOT_MUTABLE` on all three terminal statuses. The existing `errors`/`state_machines` instances that assert `ERR_POLICY_NOT_MUTABLE` all use the policy-scoped path, so they remain correct.

Verification: error-id/HTTP-status cross-check against §1.6 shows 0 real mismatches (one regex false positive on prose that says 400 "never the 422 family") and 0 of the 63 catalog errors unreferenced.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    56
  §1.1 entities declared:     11
  §1.8 instances scanned:     23
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  1066
```

Note on the scenario text: per the known leak hazard, only the substantive "2832. Inland Marine & Equipment Floater Underwriting …" paragraph went verbatim into `scenario:`; the meta-directive line "Generate task harder than expert level!" was deliberately omitted so it cannot propagate into PRD.md. The hard constraint held — no sibling task directory was listed, read, or grepped at any point.

**Orchestrator verification:** all three files present and parse as valid YAML; `SCAFFOLD.yaml` carries neither `scaffold_difficulty_design` nor `scaffold_corner_design`; `grep -rn "harder than expert"` over the task dir returns nothing, so the difficulty directive did not leak via the scaffold.

## Step 3: Copy shared files — 2026-09-05T05:51:50.936Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T06:10:00.000Z

PRD generation for task_2832 is complete.

**Artifact:** `workspace/PRD.md` — **507 lines**, built with 11 chunked `cat >>` appends (no single giant Write). Ends at a real section boundary: the final line is the last row of the §5 catalogue, `| ERR_AGGREGATE_LIMIT_EXHAUSTED | 422 |`. No audit footer, no contract reports written into the file.

**Section list**
- §1 Introduction (3 paragraphs + prefix note)
- §2 Global Specifications: 2.1 Underwriting Roles and Request Authentication · 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination, Ordering and List Filters · 2.4 Common Resource Properties · 2.5 The Logical Clock and Date Arithmetic · 2.6 Money, Basis Points and the Single-Rounding Rule · 2.7 Resource Versions and Stale-Version Guards · 2.8 Validation Precedence and Nested Path Resolution (30-rung ordered ladder) · 2.9 The Premium and Loss Ledgers as Conserved Quantities · 2.10 Aggregate Capacity as Conserved Capacity · 2.11 Re-Rating Cascades and Hierarchical Consistency
- §3 Business Logic: 3.1 Opening a Policy and Structuring Its Coverage Parts · 3.2 Rate Development and the Equipment Schedule · 3.3 Jobsites, Theft Controls and the Release Cascade · 3.4 From Schedule to Quote · 3.5 Referral, Binding, Activation, Cancellation and Expiry · 3.6 Installation Floaters · 3.7 Transit · 3.8 Reporting Forms · 3.9 Loss Adjustment (9 subsections, within the 5–9 limit)
- §4 Endpoint Definitions (intro paragraph on status codes + 4-column table)
- §5 Error Code Catalogue (2-column table)

**Completeness check (scripted against SCAFFOLD.yaml)**
- 56/56 endpoints in the §4 table (4 columns, 56 data rows)
- 63/63 errors in the §5 table (2 columns, 63 data rows); all 63 IDs also appear in the §1–§4 prose, not only in the catalogue
- 67/67 validations represented — every validation's error ID appears in prose and the whole priority ladder 10→75 is rendered as one ordered list in §2.8
- 17/17 calculations described in prose, with every declared constant present numerically (0 misses)
- 9/9 state machines: all 52 transitions across both Claim axes represented; every state name appears in backticks (0 misses)
- 5/5 roles named in §2.1 with their `identity:` semantics translated (4 opaque operator identities, `Policyholder` entity-backed to `Policy`)
- 11/11 entities covered, including `LedgerEntry`'s `common_fields: false` exception (only `id` and `created_at`)

**Hard Contract 1 — Field-Name Coverage: PASS.** 163 distinct identifiers checked against backticked tokens outside fenced code blocks: 0 missing.

**Hard Contract 2 — Rule Coverage: PASS.** Priorities expressed as the explicit §2.8 ladder including the two spelled-out consequences (`ERR_PART_VOID` before `ERR_POLICY_NOT_MUTABLE`; mutable-vs-in-force split). Both OCC rules (`expected_policy_version`/412, `expected_coverage_part_version`/412) in §2.7 with rationale. Cross-entity side effects written as numbered hop cascades (jobsite release 4 hops, total-loss settlement 4 hops, referral decline, cancellation, sweep suspension). `applies_to` scopes stated per rule. Field-level defaults stated at each creation point. Sibling-branch symmetry explicit on all divergent pairs: ACCEPTANCE vs OCCUPANCY, ACCEPTED vs PENALIZED, REPAIR vs TOTAL_LOSS, RECOVERED vs WAIVED, INSURED_REQUEST vs insurer-initiated cancellation. No-pseudocode scan: zero occurrences of `==`, `>=`, `min(`, `round_half_up`, `IN {` outside fenced blocks; zero fuzzy words.

**Hard Contract 3 — §3 Path Purity: PASS.** No backticked token in §3 (lines 190–377) starts with `/`, is a bare HTTP method, or combines method+path.

**Constraint honored:** neither design index was opened, grepped, or referenced; a case-insensitive scan of PRD.md for `difficulty`, `corner`, `test_recipe` and `expert level` returns 0 hits.

**Three scaffold ambiguities resolved with explicit deterministic rulings in the prose:** (1) reporting periods are not defined anywhere in the scaffold, so §3.8 pins them as calendar-month/quarter tiles forward from the policy `effective_date` with end-of-month clamping and truncation at `expiration_date`; (2) `claim_loss_valuation` has no case for a subject-less `REPORTING_FORM` claim, so §3.9 rules `valuation_at_loss_cents` = `actual_value_at_loss_cents` in that case, and factor = 10000 when `actual_value_at_loss_cents` is zero; (3) where the governing claim-limit field is undeclared on the part, the cap does not bind. Also, the scaffold conflicts on `cancel_effective_date` and `loss_date` interval closure (state machine/entity say half-open at `expiration_date`, the validations table writes a closed bracket); the generator followed the three explicit half-open statements over the single loose bracket.

**Orchestrator verification (truncation guard):** `wc -l` = 507; heading scan shows §1 → §5 all present in order; `tail -25` ends on the final error-catalogue row `| ERR_AGGREGATE_LIMIT_EXHAUSTED | 422 |`, a real section boundary rather than a mid-sentence cut. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T06:49:00.000Z

(Recorded ahead of Step 5's entry because Steps 5 and 6 ran concurrently and Step 6 returned first.)

The implementation is complete.

## Files written (`workspace/implementation/`)

| file | lines | role |
|---|---|---|
`start.sh` | 10 | guarded pip install, `exec python3 app.py` (foreground, `$PORT`, default 10000, binds 0.0.0.0) |
`requirements.txt` | 1 | flask |
`app.py` | 43 | app factory, envelope error handlers, `PORT` reader |
`common.py` | 385 | logical clock (epoch 2026-08-01T00:00:00Z), envelope, 63-entry error catalog, auth/ownership/SoD helpers, parsers, pagination |
`store.py` | 176 | in-memory dicts + ledger append (no disk, no seed) |
`rating.py` | 561 | exact `Fraction` arithmetic, round-half-up, rate-cell selection, all premium/claim formulas |
`views.py` | 111 | serialisation; every `computed` field derived at read time |
`cascades.py` | 169 | endorsement proration, geo-tracking guard, jobsite re-rate cascade, void/expiry cascades, delinquency cure |
`routes/__init__.py` | 18 | `BLUEPRINTS` (11 blueprints) |
`routes/policies.py` | 331 | 12 endpoints |
`routes/coverage_parts.py` | 441 | 9 endpoints |
`routes/claims.py` | 358 | 9 endpoints |
`routes/equipment_items.py` | 107 | 5 |
`routes/installation_floaters.py` | 99 | 4 |
`routes/transit_shipments.py` | 88 | 4 |
`routes/value_reports.py` | 79 | 3 |
`routes/jobsites.py` | 74 | 3 |
`routes/rate_rules.py` | 72 | 3 |
`routes/vehicles.py` | 67 | 3 |
`routes/clock.py` | 23 | 1 (`POST /_clock/set_current_utc`, outside the prefix) |

Total 3213 lines.

## Verification

- **Endpoint count: 56**, and a programmatic diff of the Flask URL map against the PRD §4 table gives `MISSING: []`, `EXTRA: []` (method + path exact).
- **Error catalog:** all 63 PRD §5 error ids present with byte-identical HTTP statuses (`missing: []`, `mismatches: {}`); only two extra internal ids for unrouted paths/unexpected errors.
- **Boot smoke test** on `PORT=48321` (shut down by captured PID only; port confirmed free afterwards): **74 assertions pass, 0 failures, 0 HTTP 500s.** Coverage included the full quote→bind→activate→endorse→cancel/expiry lifecycle, OCC 412s, pagination 400, 401/403/404 ladder rungs, ownership + both SoD points, reporting-form file/adjudicate/sweep, floater open/activate/terminate + jobsite release cascade, transit plan/depart, and both claim branches (REPAIR closing in one call; TOTAL_LOSS resting at SETTLED with the 4-hop cascade, `TOTALED`/`LOST` subjects, `ENDORSEMENT_RETURN`, salvage RECOVERED capped at paid and WAIVED).
- **Fresh-boot isolation confirmed** (a second boot on 48322 returns empty collections and clock exactly `2026-08-01T00:00:00.000Z`), so the `per-test-server` isolation mode is satisfied; storage is dict-only, nothing seeded, nothing written to disk.

Three defects were fixed while finishing: rate-rule publication now retires competing cells; VOIDED floaters no longer get a `termination_date` and carry `unearned_return_cents = 0`; and the release cascade no longer re-rolls a DECLINED/CANCELLED policy's premium. Scratch files were kept in `/tmp/task_2832_impl_scratch/`; `test_suite/`, `test_helpers/`, the difficulty/corner design files and `worklog.md` were not read or touched.

## Step 5: Generate unit tests — 2026-09-05T08:27:00.000Z

(Launched concurrently with Step 6 in a single assistant message, so the implementation generator never saw `test_suite/`; Step 5 returned second and is recorded after Step 6.)

Stage 2 is complete. Final state of the generated suite for task 2832:

## Files written

**`test_helpers/`** — 9 files, 2576 lines
`__init__.py` 112, `api_client.py` 323, `api_errors.py` 178, `assertions.py` 249, `constants.py` 144, `factories.py` 422, `fixtures.py` 460, `test_users.py` 99, `types.py` 589

**`test_suite/`** — 17 files, 5660 lines
`conftest.py` 23; `test_01_dual_basis_variants.py` 165, `test_02_premium_factor_products.py` 153, `test_03_cycles_and_axes.py` 197, `test_04_cascades.py` 179, `test_05_rule_precedence.py` 225, `test_06_inclusive_boundaries.py` 289, `test_07_cross_entity_gates.py` 233, `test_08_temporal_overlap.py` 207, `test_09_conserved_quantities.py` 180, `test_10_entity_shapes.py` 334, `test_11_state_machine_walks.py` 602, `test_12_calculation_branches.py` 568, `test_13_validation_rules.py` 479, `test_14_validation_gates.py` 431, `test_15_endpoints_and_errors.py` 737, `test_16_authority_and_layers.py` 658

## Tests emitted: 128

## Per-queue design-index coverage
- **Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, §1.8):** 23 non-stub instances, **23 translated, 0 skipped**; every instance carries ≥2 tests (46+ of the 128).
- **Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`, §1.9):** 71 non-stub instances, **71 translated, 0 skipped**; every instance carries ≥1 test. The 13 instances bearing `excluded_because:` are stubs by construction (each delegates its assertions to a named queue-A instance) and were correctly not translated: `corner_policy_suspend_and_cure_cycle`, `corner_claim_dual_axis_join_at_closed`, `corner_item_activation_guarded_by_policy_state`, `corner_scheduled_versus_blanket_part_premium`, `corner_underreporting_penalty_factor_at_threshold`, `corner_transit_catastrophe_tier_selection`, `corner_equipment_item_premium_credit_cap`, `corner_jobsite_security_gate_versus_floater_aggregate`, `corner_floater_term_versus_jobsite_occupancy_overlap`, `corner_constructive_total_loss_blocks_repair`, `corner_quote_requires_ratable_coverage`, `corner_claim_settlement_segregation_of_duties`, `corner_scheduled_versus_blanket_dual_variant`.

**No instance was skipped for PRD-filter reasons.** Three design assertions that contradicted the PRD were narrowed rather than dropped (each instance still translated): the item-level `valuation_basis` copy-down on `corner_patch_coverage_part_defers_repricing_to_the_next_quote` (PRD line 212 vs the recipe's "stays null"), a `coverage_part_id` field asserted on a ledger row the PRD's field list (line 172) does not define, and `settlement_amount_cents == 0` on an inspected claim where PRD line 344 says null.

## Verification run
- `python3 -m py_compile` clean on all 26 generated files.
- AST unused-import scan clean on the two new files.
- Citation audit: every `PRD:` line in all 16 test files is a literal substring of `workspace/PRD.md` (one fabricated citation found and fixed in `test_08_temporal_overlap.py:188`).
- Design-tag audit: exactly one `Design:` line per test, always the docstring's last line; all 128 tags resolve to a real non-stub instance and the middle segment matches that instance's own `rule_id`/`section`.
- No `skip`/`skipif`/`xfail`, no mocking, no "scaffold" reference in generated code (only `SCAFFOLDING`, a PRD `equipment_type` enum member).
- `ls -la` confirms `test_helpers/` and `test_suite/` sit at the task root; `workspace/` holds only `INSTRUCTION.md`, `PRD.md` and the untouched `implementation/`.

**Orchestrator verification:** `find workspace -type d -name "test_*"` returns nothing, so neither test directory drifted under `workspace/` (a known failure mode for this step). `PYTHONPATH=. python3 -m pytest test_suite --collect-only -q` reports **132 tests collected in 0.87s** with zero collection errors — the subagent's own count of 128 was of design-tagged test functions; the collector's 132 includes parametrised expansions.

## Step 7: Run tests and iterate — 2026-09-05T08:53:00.000Z

Clean. Done.

## Summary

**Iterations run: 2** (each an 8-round parallel `setsid nohup` sweep, 132 collected tests per round).

Iteration 1 found **5 failures, deterministic in all 8 rounds** (no flakiness anywhere in the suite). Iteration 2 was fully green.

### Tests deleted
None. One assertion was removed under STEP 1c partial-coverage handling:

- `test_14_validation_gates.py::test_the_settlement_is_tested_against_remaining_aggregate_not_the_item_limit` — dropped `assert claim["claim_limit_cents"] == 20000000` (**COMPUTED-FIELD SILENCE**). PRD names `claim_limit_cents` only as an inspection intermediate (§3.9 "Second, the claim limit…") and as a **worksheet** field (§3.9 "The worksheet … returns … `claim_limit_cents` …"); it is absent from the claim resource's own field list at PRD line 344. A faithful reader may legitimately omit it from the claim serializer. The covered assertion on the worksheet (line 327) was kept, so the rule still has coverage — as it also does in test_01, test_06, test_12 and test_15, all of which read it off the worksheet.

### Fixes applied to `test_helpers/`
- `test_helpers/test_users.py` — `headers_with_blank_user_id` / `headers_with_blank_role`: blank value changed from `"   "` to `""`. `requests.utils.check_header_validity` refuses a whitespace-only header value client-side (`InvalidHeader`), so the request never reached the service; the empty string is transmitted and is exactly the blank header PRD §2.1 rejects with `ERR_UNAUTHENTICATED`. Implementation already strips and 401s on it.

### Fixes applied to `test_suite/` (all STEP 2 test-vs-PRD consistency bugs; implementation was correct in every case)
- `test_11_state_machine_walks.py::test_publishing_a_second_cell_on_the_same_key_retires_the_first` — the test used `fixtures.build_scheduled_file`, which publishes a **third** cell on the same {type, territory, age band} key, so per PRD §3.2 that cell retired the challenger and won selection. Replaced with direct `create_policy`/`create_part`/`schedule_item` so the challenger stays the newest `PUBLISHED` candidate.
- `test_11_state_machine_walks.py::test_declining_the_referral_voids_both_parts_and_the_pending_floater` — the final `ERR_PART_VOID` probe posted an item to an `AGREED_VALUE` part while omitting `stated_value_cents`, which PRD §3.2 makes required on that basis; rung 9 (shape) legitimately pre-empted rung 11 (`ERR_PART_VOID`). Added `stated_value_cents` (plus matching `equipment_type`/`original_cost_cents`) so the payload is well-shaped and the part-void rung is the one under test.
- `test_13_validation_rules.py` `plan()` helper + `test_one_coastal_endpoint_shrinks_the_limit_the_same_declared_value_must_clear` — all four planned runs reused one identical `departure_at`/`arrival_at`, so once the second run was `PLANNED` the conveyance-window check (rung 25) answered before the limit test (rung 30), yielding `ERR_VEHICLE_WINDOW_CONFLICT`. `plan()` now takes an explicit window and the two coastal runs use `22:00→23:00`, clear of the first run's `[08:00, 22:00)` occupation-plus-turnaround interval.

### Fixes applied to `implementation/`
**None.** All four defects were test-side; no PRD-required check was weakened and no implementation file was touched.

### Final per-round numbers (quoted from `workspace/implementation/results.$i.json`)
```
round 1: passed=132/132 failed=0 errors=0 skipped=0
round 2: passed=132/132 failed=0 errors=0 skipped=0
round 3: passed=132/132 failed=0 errors=0 skipped=0
round 4: passed=132/132 failed=0 errors=0 skipped=0
round 5: passed=132/132 failed=0 errors=0 skipped=0
round 6: passed=132/132 failed=0 errors=0 skipped=0
round 7: passed=132/132 failed=0 errors=0 skipped=0
round 8: passed=132/132 failed=0 errors=0 skipped=0
```
Hygiene verified: no `results.*.json` outside `workspace/implementation/`, no test directory drift under `workspace/`, no `skip`/`xfail` anywhere in the suite, nothing committed to git, and `worklog.md` untouched.

**Orchestrator verification (sweep-artifact guard):** re-read all 8 `results.$i.json` directly — 8 files present, all mtime 08:45:11–08:45:12 (a single genuine concurrent sweep, not serial re-runs), each reporting `passed=132 failed=0 errors=0 skipped=0 total=132`. The claim of a clean sweep is confirmed by artifact, not taken on trust.

**Step 8 skip-condition adjudication:** Step 7 ran 2 iterations with 1 assertion removal, 1 `test_helpers/` fix and 3 `test_suite/` fixes, so the zero-change skip condition does NOT hold and Step 8 runs. Note that `implementation/` fixes were zero, so Step 8's legitimate output may well be a byte-identical `PRD_FINALIZED.md` — the only Step 7 item that reveals a genuine PRD silence is the `claim_limit_cents` computed-field omission, and that silence is on the *test's* side (PRD correctly declines to promise the field on the claim resource, which is what the implementation does). A byte-identical Step 8 result is therefore acceptable here; Step 9 is the step that must not be identical.

## Step 8: Finalize PRD — 2026-09-05T08:57:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- `PRD.md`: 507 lines — `PRD_FINALIZED.md`: 507 lines (0.00% line delta; 1 line revised, +363 chars, +0.31% bytes).

## Changes
- **§3.9 (Inspection, "Second, the claim limit", line 352)** — *revise* — appended one sentence pinning that `claim_limit_cents` is an intermediate of the settlement formulas, is **not** a stored field of the claim resource, is re-derived from the governing part and loss subject on each use, and appears in no response body other than the settlement worksheet. — `implementation/routes/claims.py:43-48` (`_store_derived` deliberately omits `claim_limit_cents` from the six keys it writes onto the claim) and `implementation/routes/claims.py:112-139` (the claim row is minted without the key), vs `implementation/routes/claims.py:199` (the sole emission site, the worksheet).

## Per-edit pre-edit search log

**Edit 1 — §3.9 claim limit**
- **(a) Subject:** the field `claim_limit_cents` — where it is computed, whether it is persisted on the claim, and every response that carries it.
- **(b) Impl paths enumerated:** `grep -rn claim_limit_cents implementation/` → only two hits, both in `routes/claims.py`. Read in full: `_derive` (claims.py:23-40, returns it in the derived dict), `_store_derived` (43-48, the six keys it writes — `claim_limit_cents` excluded), `report_claim` row construction (112-139, key absent), `inspect_claim` (209-228, calls `_store_derived`), `adjust_claim` (231-265, both branches call `_store_derived`), `settle_claim` and `record_salvage` (268-358, never write it), `settlement_worksheet` (184-206, the one emission site), `views.claim_view` → `store.serialize` (views.py:106-107, store.py:64-65 — emits only keys present on the row), `rating.claim_limit` (rating.py:487-499, pure function over part + subject) and its consumer `rating.claim_settlement_variants` (525-536). Also cross-checked which sibling derivations *are* stored, to keep the "other three derivations" clause true: `valuation_at_loss_cents`, `constructive_total_loss_threshold_cents`, `underreporting_factor_bp`, `repair_basis_settlement_cents`, `total_loss_basis_settlement_cents` all appear in `_store_derived` and in PRD's claim field list at line 344.
- **(c) Wording adjustment:** phrased as "re-derived … each time it is needed" rather than naming a fixed set of calls, because `_derive` runs it at inspection, at adjustment (twice per branch) and on every worksheet read; and "the only response body in which it appears is the settlement worksheet" rather than "it is not returned anywhere", since the worksheet emission at claims.py:199 is genuine and PRD line 376 already lists it there.

## Items that warranted no patch
- **`test_helpers` blank-header fix** — pure fixture bug (`requests` refuses a whitespace-only header client-side). `common.py:202-207` strips and 401s on both `""` and `"   "`, so PRD §2.1's "absent or blank" is already exact and correct at both widths. Narrowing it to the empty string would have been a new mismatch.
- **test_11 second-cell publish** — pure fixture bug. `routes/rate_rules.py:43-65` (retire on identical 4-tuple) and `rating.py:107-121` (PUBLISHED-only candidates, `published_at` desc over a `created_at`-ascending stable order) already match PRD §3.2 verbatim.
- **test_11 `ERR_PART_VOID` probe** — pure fixture bug. `routes/coverage_parts.py:129-133` requires `stated_value_cents` on an `AGREED_VALUE`/`STATED_AMOUNT` effective basis *before* `_guard_part_and_policy` at line 132→134, exactly as PRD §2.8 rung 9 precedes rung 11 and PRD §3.2 line 212 requires the field.
- **test_13 conveyance-window fix** — pure fixture bug. `routes/coverage_parts.py:268-296` evaluates window conflict → daily capacity → transit value limit, matching PRD §2.8 rungs 25, 26, 30, with the four-hour turnaround of PRD §3.7 line 308.

**Orchestrator note:** `PRD_FINALIZED.md` is 116745 bytes vs `PRD.md`'s 116382, so the file is genuinely a patch and not an unmodified copy.

**Step 9 plan (orchestrator decision, recorded because there is no user to consult):** the implementation is 3213 lines across 20 modules, which is more than one scan pass can hold with the fidelity Step 9 requires — a single-agent Step 9 on a codebase this size reliably degrades into a shallow skim whose output is byte-identical to its input. Step 9 will therefore run as **four sequential, module-partitioned passes over one shared `PRD_COMPLETED.md`**, each pass reading the file the previous pass left behind. Pass 1 performs the `cp` from `PRD_FINALIZED.md`; passes 2–4 must not, or they would discard their predecessors' edits. Partition:
- **Pass 1 — foundations:** `app.py`, `common.py`, `store.py`, `views.py`, `routes/__init__.py`, `routes/clock.py` (envelope, auth/RBAC, error catalogue, pagination, clock, serialisation).
- **Pass 2 — computation:** `rating.py`, `cascades.py` (all premium/claim formulas, rounding, rate-cell selection, proration, cascades).
- **Pass 3 — policy & schedule lifecycle routes:** `routes/policies.py`, `routes/coverage_parts.py`, `routes/rate_rules.py`, `routes/equipment_items.py`, `routes/jobsites.py`.
- **Pass 4 — claims, floaters, transit, reporting:** `routes/claims.py`, `routes/installation_floaters.py`, `routes/transit_shipments.py`, `routes/value_reports.py`, `routes/vehicles.py`.

## Step 9: Complete PRD — 2026-09-05T09:52:00.000Z

Run as four sequential, module-partitioned passes over one shared `PRD_COMPLETED.md`, per the Step 8 entry's plan. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2–4 were explicitly forbidden from copying and edited in place. Every pass used targeted `Edit` calls rather than a wholesale rewrite, so no pass could truncate the file or discard its predecessors' work. Each pass was handed the prior passes' committed edit count and line/char count so it could verify on exit that nothing was lost.

### Pass 1 — foundations (`app.py`, `common.py`, `store.py`, `views.py`, `routes/__init__.py`, `routes/clock.py`)
507 lines / 116,745 chars → **509 lines / 123,596 chars**. 13 ambiguity-pins, 4 mismatch-revisions (17 changes over 14 diff sites).
- §2.2 — revise — ambiguity — `api_request_id` pinned as literal `req_` + exactly 16 chars from `a`–`z`/`0`–`9`, minted per response, never stored — `common.py:161-169`
- §2.2 — revise — ambiguity — `api_request_timestamp` read from the logical clock, so it repeats byte-identically until the clock moves and reads `2026-08-01T00:00:00.000Z` before the first set — `common.py:132-133,105`
- §2.2 — revise — ambiguity — pagination keys appear in `meta` for list responses only, after the two id keys; object responses carry exactly those two — `common.py:172-184`
- §2.3 — revise — **mismatch** — PRD required integrality only of `offset`; impl rejects a non-integer `limit` too. Pinned: empty/decimal/non-numeric either parameter → `ERR_INVALID_PAGINATION`, whitespace and an explicit `+`/`-` sign tolerated, `offset` uncapped, over-range offset yields an empty page with true `total_count` and `has_more` false — `common.py:233-251`
- §2.3 — insert — ambiguity — `created_at` ties (common, since the clock only moves on request) break by creation order, so lists are always in creation order — `store.py:68-69`
- §2.3 — revise — **mismatch** — `ledger` filter accepted only on a *policy's* ledger entries; a claim's ledger-entry listing accepts `entry_type` only — `routes/claims.py:174-180` vs `routes/policies.py:105-113`
- §2.3 — insert — ambiguity — filters are exact case-sensitive string matches, never enum-validated (unknown value ⇒ empty page, not an error); unrecognised query params ignored — `store.py:72-84`, `routes/equipment_items.py:26-31`
- §2.4 — insert — ambiguity — declared fields always present from creation, emitted as JSON `null` when unset (never omitted, never `""`) — `store.py:56-65`, `routes/policies.py:26-52`
- §2.5 — insert — ambiguity — the clock is set unconditionally (backwards moves accepted, nothing reversed), the expiry sweep runs on every set, both id arrays always present and in creation order, `current_utc` echoed normalised — `routes/clock.py:10-23`, `common.py:113-115`
- §2.5 — insert — ambiguity — accepted date shape (strict zero-padded, real calendar day) and the tolerant instant grammar (`T`/`t`, optional seconds, 1–9 fractional digits, `Z`/`z`/`±HH:MM`/`±HHMM`/absent → UTC); all emitted instants normalised to millisecond precision by **truncation** — `common.py:329-381,125-139`
- §2.1 — insert — ambiguity — whitespace-only header counts as blank; role matching is case-sensitive and untrimmed — `common.py:202-214`
- §2.8 rung 4 — insert — ambiguity — ownership is an exact string compare, skipped for non-Policyholders; on the five policy-path operations it precedes the 404, on the two transitively-owned ones a missing target makes it vacuous so rung 7's 404 wins — `common.py:217-227`, `routes/claims.py:147-148`, `routes/coverage_parts.py:319-320`
- §2.8 rung 9 — insert — ambiguity — absent/empty body = empty object; non-object or unparseable JSON = `ERR_INVALID_REQUEST`; explicit `null` ≡ omitted; no cross-type coercion; length bounds applied untrimmed; undeclared body fields ignored — `common.py:262-326`
- §2.8 preamble — revise — **mismatch** — "no partial mutation is retained" scoped to admit the §3.7 carrier-approval lapse that suspends the vehicle while refusing the departure — `routes/transit_shipments.py:53-58`
- §2.9 — revise — **mismatch** — `premium_balance_cents`/`incurred_loss_cents` derived from the ledger at serialisation time, not accumulated counters — `views.py:6-13,56-61`
- §2.10 — insert — ambiguity — `aggregate_paid_net_cents`/`aggregate_available_cents` derived at read from the part's claims, making the identity structural — `views.py:16-25,64-71`
- §4 — revise — ambiguity — unmatched path *and* unsupported method both return `ERR_NOT_FOUND` / 404 (never 405), stated as outside the §5 catalogue; trailing slashes insignificant — `app.py:21-31,12`

Verified-not-changed: all 63 §5 error ids and statuses match `ERROR_STATUS` exactly; round-half-up `rhu` matches §2.6 including negatives; the `LedgerEntry` `updated_at`/`version` exemption matches §2.4/§2.9; §2.4's ten-entity list matches every `store.make` callsite.

### Pass 2 — computation (`rating.py`, `cascades.py`)
509 lines / 123,596 chars → **509 lines / 126,699 chars**. 6 ambiguity-pins, 2 mismatch-revisions.
- §3.3 — revise — **mismatch** — a `RELEASED` jobsite yields a security credit of zero whatever tier it still carries, on every rating and not only on the release cascade — `rating.py:142-149`
- §3.3 — insert — ambiguity — the grade-A theft control reads the grade the cell selection would return against the *jobsite's* `territory_code` and the unit's current age; with no `PUBLISHED` cell for that combination the control is vacuous and passes — `cascades.py:36-43`
- §3.3 — revise — ambiguity — the release re-rate sweep skips items whose owning policy is `DECLINED`/`CANCELLED` and items with no published cell in the site's territory; the ledger movement is one prorated entry per affected policy for the net delta — `cascades.py:49-82`
- §3.2 — insert — ambiguity — proration is computed on the non-negative magnitude with the sign applied after rounding (differs by a cent from rounding a negative rational on a half); a zero amount books no entry — `cascades.py:15-20`, `rating.py:542-549`
- §3.4 — revise — ambiguity — `minimum_premium_applied` is true only when the loaded figure is **strictly** less than the minimum; "derives on the fly" scoped to re-running sum/load/floor/thresholds, never re-selecting a cell — `rating.py:359-383`
- §3.6 — revise — ambiguity — floater expiry fires when the clock reaches a date strictly after `coverage_end_date` — `cascades.py:138`
- §3.6 — insert — ambiguity — a `VOIDED` floater records no `termination_date` and leaves `earned_premium_cents` at zero; no elapsed-day proration on that path — `cascades.py:100-119`
- §3.9 hop three — revise — **mismatch** — the total-loss `ENDORSEMENT_RETURN` is booked unconditionally whatever the policy's status, suppressed only at a zero amount — `routes/claims.py:321-324`, `cascades.py:13`

### Pass 3 — policy & schedule lifecycle routes (`policies.py`, `coverage_parts.py`, `rate_rules.py`, `equipment_items.py`, `jobsites.py`)
509 lines / 126,699 chars → **509 lines / 131,213 chars**. 16 ambiguity-pins, 6 mismatch-revisions (22 pins over 20 Edit calls).
- §2.7 — insert — ambiguity — both `expected_*_version` fields are plain non-negative integers, so omitted/null/non-integer/negative fails shape with `ERR_INVALID_REQUEST` before any comparison — `coverage_parts.py:125,329`
- §2.8 preamble — revise — **mismatch** — one partial-mutation exception became two: re-siting writes `assigned_jobsite_id` before rating, so it survives an `ERR_NO_PUBLISHED_RATE_RULE` refusal — `equipment_items.py:59-60`
- §2.8 rung 9 — revise — **mismatch** — floater `coverage_end_date` and report `period_end_date` are "strictly after", not "not earlier than" (rung 9 contradicted §3.6/§3.8 and the code) — `coverage_parts.py:200,325`
- §3.2 — revise — **mismatch** — `stated_value_cents` under `ACV`/`REPLACEMENT_COST` is stored and echoed if supplied, null only if omitted (not "ignored") — `coverage_parts.py:132,146`
- §3.2 — insert — ambiguity — item removal tests policy mutability but not part status → `ERR_POLICY_NOT_MUTABLE`, not `ERR_PART_VOID` — `equipment_items.py:93-98`
- §3.3 — revise — **mismatch** — jobsite `name` is 1 to **200** characters — `jobsites.py:17`
- §3.3 — insert — ambiguity — a new jobsite's four theft-control booleans open `false`, not null — `jobsites.py:22-25`
- §3.3 — insert — ambiguity — all four survey booleans are required fields — `jobsites.py:48-51`
- §3.3 — insert — ambiguity — on assign-jobsite an omitted/null/non-string `jobsite_id` is `ERR_JOBSITE_NOT_FOUND`, never `ERR_INVALID_REQUEST` — `equipment_items.py:47-50`
- §3.3 — insert — ambiguity — re-siting tests only the item's own status: not the part's `VOID`, not the policy's mutability — `equipment_items.py:51-57`
- §3.3 — insert — ambiguity — re-siting books no entry outside `IN_FORCE` (`SUSPENDED` included) and none on a zero delta — `equipment_items.py:66-68`
- §3.3 — insert — ambiguity — the grade-A survey veto scans every `RATED`/`ACTIVE` item whatever its policy's status, unlike the re-rating sweep — `jobsites.py:57-62`
- §3.5 — insert — ambiguity — `referral_note` is a ≤500-char string, validated and discarded (no policy field records it) — `policies.py:221`
- §3.5 — insert — ambiguity — a referral decline re-derives no money; roll-ups and voided parts' `rated_premium_cents` keep their last-quote values — `policies.py:254-258`
- §3.5 — revise — ambiguity — activation also refuses with `ERR_POLICY_NOT_ACTIVATABLE` when the clock has reached `expiration_date` — `policies.py:287-290`
- §3.5 — insert — ambiguity — `CANCELLATION_RETURN` carries `effective_date` = `cancel_effective_date`; a zero return books no entry — `policies.py:311-317`
- §3.5 — insert — ambiguity — cancellation re-derives no roll-ups or TIV despite emptying the schedule; only ledger-derived `premium_balance_cents` moves — `policies.py:318-330`
- §3.6 — insert — ambiguity — floater `jobsite_id` present-but-not-a-string is `ERR_JOBSITE_NOT_FOUND`; only omitted/null is `ERR_INVALID_REQUEST` — `coverage_parts.py:102-110,193-195`
- §3.7 — insert — ambiguity — shipment `vehicle_id` omitted/null/non-string is `ERR_VEHICLE_NOT_FOUND`, never `ERR_INVALID_REQUEST` — `coverage_parts.py:253-256`
- §3.8 — insert — ambiguity — a zero-valued superseded-report backout writes no ledger entry — `coverage_parts.py:382-386`
- §3.8 — insert — **mismatch** — the sweep never tests part status, so a `VOID` part yields `ERR_POLICY_NOT_IN_FORCE`, never `ERR_PART_VOID` — `coverage_parts.py:396-404`
- §3.8 — revise — **mismatch** — deleted the claim that the sweep *sets* `latest_report_period_end_date`; it stays the derived greatest end date, so a sweep minting nothing leaves it unchanged — `coverage_parts.py:395-441`, `views.py:34-42`

All three pass-2 hand-offs resolved: the §3.8 self-contradiction, the jobsite `name` 120→200 mismatch, and zero-amount ledger suppression verified and pinned at both route sites (`policies.py:314`, `coverage_parts.py:383`).

### Pass 4 — claims, floaters, transit, reporting (`claims.py`, `installation_floaters.py`, `transit_shipments.py`, `value_reports.py`, `vehicles.py`) + closing consistency sweep
509 lines / 131,213 chars → **509 lines / 139,990 chars**. 24 partition edits (16 ambiguity-pins, 8 mismatch-revisions) + 9 closing-sweep edits = 33.
- §2.3 — insert — ambiguity — `status` filter scoped; the superseded-reports listing takes no filter of its own — `value_reports.py:26-34`
- §2.8 rung 9 — insert — ambiguity — the eleven bodyless write endpoints ignore any body, unparseable ones included — `installation_floaters.py:40`, `transit_shipments.py:39/75`, `value_reports.py:37`
- §2.8 on-risk paragraph — insert — ambiguity — a third group tests policy status not at all: re-siting, floater termination, delivery, adjudication, every claim write
- §3.6 — insert — ambiguity — activation re-rolls neither part nor policy, touching only the floater — `installation_floaters.py:60-64`
- §3.6 — insert — ambiguity — `ENDORSEMENT_RETURN` suppressed at zero, unconditional otherwise — `installation_floaters.py:87-91`
- §3.6 — insert — ambiguity — `termination_trigger` verbatim from the reason; four values across the four exits — `rating.py:289-307`
- §3.6 — insert — ambiguity — part then policy re-rolled *before* the four-hop cascade — `installation_floaters.py:96-98`
- §3.6 — insert — ambiguity — the acceptance return row always precedes any release entry
- §3.7 — revise — **mismatch** — vehicle `unit_label` and `carrier_name` are one to **two hundred** chars (PRD said sixty) — `vehicles.py:16-20`
- §3.7 — revise — **mismatch** — departure rewrites both derived fields but never re-tests `declared_value_cents`; `ERR_TRANSIT_VALUE_EXCEEDS_LIMIT` is planning-time only — `transit_shipments.py:62-67`
- §3.7 — insert — ambiguity — departure rewrites `catastrophe_zone`/`applicable_limit_cents`
- §3.8 — revise — **mismatch** — removed the false service-wide zero-suppression generalisation, scoped to §3.2/§3.5 with an explicit exception pointer
- §3.8 — insert — **mismatch** — adjudication books its entries unsuppressed at zero (one, two when late) — `value_reports.py:59-63`
- §3.9 — revise — **mismatch** — reporting-form subjects may be null; a named subject is still belongs-to-part tested; non-string ids → `ERR_LOSS_SUBJECT_NOT_FOUND`; missing `coverage_part_id` reported only after subjects resolve; subject status never examined — `claims.py:66-96`
- §3.9 — insert — ambiguity — the three actor fields are null at creation — `claims.py:136-138`
- §3.9 — revise — **mismatch** — deleted the false policy-status list on inspection; both fields required ints ≥ 0 — `claims.py:209-228`
- §3.9 — insert — ambiguity — exactly six derived fields stored, `loss_of_use_paid_cents` among them — `claims.py:43-48`
- §3.9 — insert — ambiguity — the loss-of-use eligibility test precedes the basis choice — `claims.py:242-245`
- §3.9 — revise — ambiguity — all six fields recomputed live; the CTL gate reads the fresh threshold — `claims.py:246-258`
- §3.9 — insert — ambiguity — the supplied `loss_of_use_days_claimed` is never stored — `claims.py:257-263`
- §3.9 hop two — insert — ambiguity — `removed_at` on the TOTALED item; shipment→LOST only while `IN_TRANSIT`; a complete no-op for floater/subjectless claims — `claims.py:305-317`
- §3.9 hop four — revise — **mismatch** — a full policy re-roll, on every total-loss settlement — `claims.py:326`, `rating.py:386-393`
- §3.9 — revise — ambiguity — salvage proceeds a required int ≥ 0; positive proceeds with a zero credit still reach `RECOVERED` with no entry — `claims.py:330-358`
- §3.9 — revise — **mismatch** — `repair_basis_selectable` is the CTL gate alone and ignores `adjustment_status`; the worksheet is readable at every status; nulls before inspection; every figure re-derived live — `claims.py:50-57,184-206`

**Closing consistency sweep** over §2.7–§2.11 and §3.2–§3.9 plus the §4 table. Five cross-pass collisions found, all fixed:
1. §2.8 rung 9's "exactly one loss subject" contradicted the reporting-form revision → rung 9 now reads "at most one, and exactly one unless the part is `REPORTING_FORM`"; rung 8 softened to match.
2. The §4 table's claim-create blurb said "against exactly one insured subject" → revised to admit the subjectless reporting-form case.
3. Pass 4's own §3.8 sentence called adjudication "the one money movement that does not suppress a zero", but `settle_claim` appends `CLAIM_SETTLEMENT` unconditionally (`claims.py:296-297`) → §3.8 narrowed to "one of only two", §3.9 now pins the zero-valued settlement row, and `SALVAGE_RECOVERY` noted as suppressing its zero.
4. §3.9 put the settlement segregation-of-duties gate after the state check, but impl tests it before both the state check and the 404 (`claims.py:271-275`, matching rung 6) → §3.9's ordering rewritten, including that the check is vacuous while the 404 stands when the claim id resolves to nothing.
5. §2.11's general rule books the prorated entry only while the policy is `IN_FORCE`/`SUSPENDED`, but hop three books it unconditionally (`cascades.py:13`) → §2.11 now names that single exception.

§2.8's "exactly two deliberate exceptions" count was re-verified and left standing (every failure path in settle, salvage, adjudicate, terminate, activate, approve and report precedes any write). Step 8's `claim_limit_cents` paragraph was left byte-identical.

### Orchestrator verification of Step 9
- `PRD_COMPLETED.md` is **509 lines / 139,990 chars** vs `PRD_FINALIZED.md`'s 507 / 116,745 — **+23,245 chars (+19.9%)**, and `cmp` confirms the two files are NOT byte-identical, so the scan genuinely ran (a byte-identical Step 9 output is the known failure signature and did not occur).
- `diff` reports **118 changed lines** across the four passes.
- Structure intact: **28 markdown headings** (identical to `PRD.md`'s count, so no pass added a section), all **63** `ERR_` catalogue rows present, and the final line is still `| ERR_AGGREGATE_LIMIT_EXHAUSTED | 422 |` — a real section boundary, not a truncation.
- `find` over `workspace/implementation/`, `test_suite/` and `test_helpers/` for `*.py` newer than 08:55 returns nothing, so no Step 9 pass touched the implementation or the tests. The 8-round 132/132 sweep recorded in Step 7 therefore still describes the shipped artifact.
- `grep -rn "harder than expert\|expert level"` over `workspace/` returns nothing: the difficulty directive never reached any PRD variant.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` is written; all nine steps are done.
