# Worklog — task_2847_orthopedic_practice_in_office_dme_dispensing_bracing

## Step 1: Create task directory — 2026-09-05T06:05:46.390Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2847_orthopedic_practice_in_office_dme_dispensing_bracing/` and its `workspace/` subdirectory. Index 2847 was pre-assigned by the orchestrating invocation; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-05T08:03:30.000Z

Scaffold generation for task 2847 is complete and lint-clean.

**Output directory** `/home/ubuntu/github/CodingPRD/tasks/task_2847_orthopedic_practice_in_office_dme_dispensing_bracing/`

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3349 | 171 KB |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2888 | 203 KB |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4620 | 334 KB |

**SCAFFOLD.yaml (§1.0–§1.7)** — 14 entities, 8 state machines (parallel clinical/financial dimensions on `DispenseEncounter`), 2 concurrency rules, 7 calculations, 62 validations (single global priority ladder), 49 endpoints, 62 errors, 6 roles. `complexity_profile`: primary compliance_audit / secondary quota_allocation; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation; entity_topology graph; role_model segregation_of_duties; consistency immediate; `difficulty_level: expert_plus`. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`. The "harder than expert level" line lives only in `difficulty_directive:`; `scenario:` is the plain domain text.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single top-level key, 9 rules / 25 instances (2+3+3+2+4+4+3+2+2).

**SCAFFOLD_CORNER_DESIGN.yaml** — single top-level key, all 9 guide sections, 73 instances = 50 with full `test_recipe` + 23 `excluded_because:` stubs citing §1.8 by name: entities 13, state_machines 13, calculations 11, validations 18, endpoints 5, errors 3, rbac 3, cross_cutting_complexity_layers 6, consistency_model 1.

**Verification**
- `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (49 endpoints, 14 entities, 25 §1.8 + 50 §1.9 instances, 1230 calls scanned) — clean on the first run.
- All 98 instance names unique across the two design files; every stub's cited `difficulty_instance` resolves.
- Error triggerability census: all 62 error ids are now referenced (the 14 that were uncovered — the auth-header pair, `ERR_ACTOR_NOT_FOUND`, eight `*_NOT_FOUND`s, both `ERR_STALE_*_VERSION`s and `ERR_SEGREGATION_OF_DUTIES` — got dedicated instances in the errors / rbac / cross-cutting sections).

**Two self-consistency fixes made while writing this last batch**: the errors-section `POST /dme/prior-auth-requests/{id}/decision` and `POST /dme/abn-notices/{id}/signature` payloads used invented field names (`authorization_number`/`valid_from`/`valid_through`, `signature_status`/`selected_option`); corrected to the §1.5 inputs `auth_number`/`valid_for_days` and `signed_by`/`option_selected`.

**Orchestrator post-step action (difficulty-directive leak guard):** deleted line 3 of `SCAFFOLD.yaml` (`difficulty_directive: "harder than expert level"`) so the difficulty instruction cannot reach the doc generator and from there PRD.md. Verified: `grep -i "harder than expert"` now matches nothing in any of the three scaffold files; all three still parse as valid YAML with the expected top-level keys; `workspace/` intact.

## Step 3: Copy Shared Files — 2026-09-05T08:04:17.609Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T08:22:00.000Z

PRD complete.

**Output:** `workspace/PRD.md` — **423 lines**, built by ten chunked `cat >>` appends (never a single giant write). Last heading is `## 5. Error Code Catalogue`; the file ends on a complete final table row (`| ERR_PAR_MAX_EXCEEDED | 422 |`), not mid-sentence, mid-table or mid-list.

**Section list**
- `# Orthopedic In-Office DME Dispensing API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim block); 2.3 Pagination; 2.4 The Logical Clock; 2.5 Resource Identity, Timestamps and Versioning; 2.6 Money, Units and Rounding Discipline; 2.7 Optimistic Concurrency on Shelves and Encounters; 2.8 Nested Path Resolution; 2.9 The Rejection Ladder; 2.10 Accreditation, Supplier Standards and the Compliance Hold; 2.11 Self-Referral Compliance and Duty Separation; 2.12 The Two Dimensions of a Dispensing Encounter
- `## 3. Business Logic & Workflows` — 3.1 Master Data; 3.2 Par Levels, Stock Receipts and the Clinic's Dispensing Posture; 3.3 Opening an Encounter, Documenting Necessity and Attesting Supervision; 3.4 Coverage Verification, the Same-or-Similar Lookback, and Prior Authorization; 3.5 Advance Beneficiary Notices and Cash Pricing; 3.6 Committing a Device: Par Reservations and Custom Fabrication; 3.7 The Fitting Session; 3.8 Dispensing the Device and the Inventory Cascade; 3.9 Returns, Inspection, Refunds, Refits and Clinic Reconciliation
- `## 4. Endpoint Definitions` — 49 rows (Method | Path | Description | Authorized Role(s)), verified count 49
- `## 5. Error Code Catalogue` — 62 rows (Error ID | HTTP Status Code), verified count 62

**Coverage confirmation** — all 14 entities named; all 49 endpoints in §4; all 62 error IDs in §5 and in the §2.9 priority ladder, with each error's raising condition stated in prose (§2.9 carries `ERR_INVALID_REQUEST` and the three pinned carve-outs; every other error's condition sits with its rule in §2.10–§3.9); all 7 calculations spelled out with pinned step order and constants (`par_stock_posture`, `clinic_dispensing_posture`, `same_or_similar_lookback`, `abn_cash_quote`, `supplier_turnaround_score`, `patient_responsibility` with both `INSURANCE_ASSIGNED` / `ABN_CASH_SELFPAY` variants, `restock_refund`); all 8 state machines with every declared transition (including the `RESERVED → RESERVED` fitting self-loop, `AUTH_PENDING → AUTH_PENDING`, the `ABN_ISSUED` re-issue and declined-signature self-loops, the `OPTION_3 → VOIDED`/`WRITTEN_OFF` cascade, `APPROVED → EXPIRED` at dispense, the `SUPPLIER_HOLD` in/out cascade, the `ProductReturn` fork-join, and both derived posture machines including `ACTIVE → SUSPENDED` in one mutation); all 6 roles described with duties and identity translation.

**Hard Contract results**
- Contract 1 Field-Name Coverage: **PASS** — 154/154 required identifiers (all `entities[].fields[].name` plus every endpoint `input`/`output` identifier) appear verbatim in backticks; 0 missing, verified twice (the first run was a false positive caused by the §2.2 fenced JSON desyncing backtick pairing — fixed by stripping code fences before matching).
- Contract 2 Rule Coverage: **PASS** — all 62 validations (priority order, `applies_to` scopes, conditions), both OCC rules with their `expected_par_level_version` / `expected_encounter_version` fields, error IDs and 412 statuses, all cross-entity side effects and the four-link dispense cascade, all field defaults/types/enums (every enum literal in the scaffold appears in backticks; 0 missing), sibling-branch symmetry (three `fit_outcome` branches, both inspection branches, both refund variants), all state transitions, all 7 calculations.
- Contract 3 §3 Path Purity: **PASS** — 949 backtick tokens in §3 (363 unique), 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations; §2 is clean of paths as well.

Two notes for downstream steps: (1) the scaffold nominates no error ID for the "acting physician must be the encounter's `ordering_physician_id`" precondition on the medical-necessity note, so §3.3 states that precondition without inventing a code; (2) I wrote header `X-User-Id` to match the scaffold, with an explicit note that HTTP header names are case-insensitive so `X-User-ID` is the same header.

**Orchestrator truncation guard:** verified `tail -45` ends at a real section boundary (complete final row of the 62-row §5 table, 62/62 rows present); heading scan shows all sections 1–5 with subsections 2.1–2.12 and 3.1–3.9 intact; `grep -i "harder than expert|scaffold|test_recipe|expert_plus|difficulty"` matches nothing in PRD.md. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-05T09:02:00.000Z

Implementation complete.

## Modules written (`workspace/implementation/`)

| file | lines | contents |
|---|---|---|
| `app.py` | 57 | app factory, 8 blueprint registrations, `ApiError`/`HTTPException`/`Exception` handlers all emitting the error envelope, `app.run(host="0.0.0.0", port=$PORT or 10000)`, no seeding |
| `common.py` | 515 | logical clock (`2026-08-01T00:00:00Z` at boot), instant/date formatting & parsing, `whole_days`/`ceil_minutes`, `round_half_up`, 62-entry `ERROR_STATUS`, envelope builders, offset pagination, `authorize` (ladder priorities 1–4 + fitter carve-out), full validator family |
| `store.py` | 418 | 14 empty in-memory collections, all domain enums, `stamp`/`touch`/`insert`/`sort_created`, lookup helpers, 14 serializers |
| `calc.py` | 327 | par/clinic posture + the four-link inventory cascade, same-or-similar lookback, ABN cash quote, patient responsibility, restock refund, the two turnaround scores + supplier rollup, dispensing summary |
| `guards.py` | 97 | the 10 reusable band-5/band-6 guards (accreditation, supplier standards/quality, compliance hold, IOAS, Stark, medical necessity, fitter credential/privilege, clinic dispensing) |
| `routes/clinics.py` | 162 | clinics, physicians, fitters, patients, dispensing-summary |
| `routes/catalog.py` | 145 | suppliers, standards-attestation + supplier-hold cascade, products |
| `routes/inventory.py` | 86 | par-levels, stock-receipts |
| `routes/encounters.py` | 447 | encounter CRUD, MN note, IOAS, reservations, custom-fab order, fitting records, dispense |
| `routes/finance.py` | 307 | coverage verifications, prior auth submit/decision/appeal, ABN issuance/list/signature |
| `routes/fabrication.py` | 127 | fab order read/list, fabrication events, fitting check |
| `routes/returns.py` | 145 | returns, inspection, refit |
| `routes/clock.py` | 19 | `POST /_clock/set_current_utc` |
| `start.sh` / `requirements.txt` | 10 / 1 | foreground `exec python3 app.py`, flask installed only when missing |

**49/49 endpoints implemented** (verified one-to-one against the scaffold endpoint table). `python3 -m py_compile` clean on every `.py`; `__pycache__` removed so the harness boots cold.

## Smoke test (port 18477, killed by its own PID)

Full off-shelf happy path passed end to end: clinic → physicians → fitter → patient → supplier → product → par level → receipt → encounter → MN note → IOAS → verification → reservation → fitting record → dispense → return → inspection → refit → dispensing-summary. Money checked by hand: responsibility 18000 / billable 32000 on a 50000-allowed, 10000-deductible, 0.2-coinsurance line; refund split 15300/2700 → 13770+2565 = 16335 with 1665 retained. Inventory invariant `units_accounted_total == units_received_total` held (10 == 10).

Custom-fabrication + finance path also passed: PENDED → appeal → APPROVED (approved_units 5 correctly rejected with `ERR_APPROVED_UNITS_EXCEED_REQUEST` 422), stale `expected_encounter_version` → `ERR_STALE_ENCOUNTER_VERSION` 412, notice supersession (seq 1 voided, seq 2 signed), projected score 88 vs final 82 with one adjustment round, supplier rollup 82, and a 3-unit dispense with 2 approved units → responsibility 140000 / billable 120000. Error paths: 404 `ERR_CLINIC_NOT_FOUND`, 400 `ERR_INVALID_REQUEST`, 401 `ERR_MISSING_AUTH_HEADERS`, 409 `ERR_INVALID_FINANCIAL_STATE`, unknown route 404 in envelope shape. Cold boot re-verified afterwards: empty list, `total_count` 0, 401 without headers.

## Two spec conflicts resolved (worth knowing for Step 7)

1. **Signing a VOIDED notice** → I return `ERR_INVALID_ABN_STATE` (409), not `ERR_ABN_SUPERSEDED`. PRD §3.5 prose says the superseded notice yields `ERR_ABN_SUPERSEDED`, but the rejection ladder puts priority 23 before 49 and the error catalog for `ERR_INVALID_ABN_STATE` explicitly reads "already SIGNED, DECLINED, or VOIDED by a later issuance". That makes `ERR_ABN_SUPERSEDED` unreachable in practice; the ladder + catalog won.
2. **`APPROVED` decision with no `approved_units`** → defaults to `requested_units` rather than 422, since the catalog only faults a decision that *carries* a value below 1 or above the request.

## Step 5: Generate Unit Tests — 2026-09-05T09:30:00.000Z

Step 5 complete. The unit-test suite for `task_2847_orthopedic_practice_in_office_dme_dispensing_bracing` is finished and verified.

## Output location
Both directories are directly under the task root `/home/ubuntu/github/CodingPRD/tasks/task_2847_orthopedic_practice_in_office_dme_dispensing_bracing/`. There is no copy under `workspace/`, and `worklog.md` was not touched.

## Files

`test_helpers/` — 2430 lines total: `__init__.py` 78, `api_client.py` 367, `api_errors.py` 159, `assertions.py` 294, `constants.py` 193, `factories.py` 423, `fixtures.py` 492, `test_users.py` 138, `types.py` 286.

`test_suite/` — 5643 lines total: `conftest.py` 28; queue A `test_01` 156, `test_02` 269, `test_03` 249, `test_04` 222, `test_05` 296, `test_06` 289, `test_07` 235, `test_08` 184, `test_09` 224; queue B `test_10` 429, `test_11` 433, `test_12` 226, `test_13` 932, `test_14` 374, `test_15` 287, `test_16` 384, `test_17` 279, `test_18` 147.

## Coverage against the two design indices
- **100 tests total**, 50 tagged `Design: Difficulty/...` and 50 tagged `Design: Corner/...`.
- **75 distinct design instances translated — every non-stub instance in both queues, zero skipped.** Queue A: 25 live instances / 0 stubs, all 25 covered, each of the 9 difficulty rules carrying at least 2 tests. Queue B: 50 live / 23 `excluded_because:` stubs; all 50 live covered, no stub touched.
- Corner sections covered: entities 13, state_machines 8, calculations 5, validations 11, endpoints 4, errors 3, rbac 3, cross_cutting_complexity_layers 2, consistency_model 1.
- Every test docstring carries exactly one `Design:` line, and a programmatic audit confirmed each tag's instance name exists verbatim in the corresponding yaml (`BAD: []`).

## Verification run
- `python3 -m py_compile` on all 28 generated `.py` files: zero syntax errors.
- Real import smoke test with `sys.path` set as `conftest.py` does: `test_helpers` plus all 18 test modules import cleanly (`ALL MODULES IMPORT OK`), so there are no missing-import `NameError`s waiting at collection time.
- AST scan for unused imports across `test_suite/`: clean.

## Two PRD-first deviations from the design index
Both are cases where the design's asserted literal contradicts what the PRD uniquely derives, so the test asserts the PRD's value:
1. Corner `endpoints` instance 46 claims the final dispense answers HTTP 200; the PRD derives 201, so that test asserts no status there and goes through the status-lenient helper.
2. Corner `consistency_model` instance 73 asserts `financial_status == VERIFIED_COVERED`; the PRD's enum member is `VERIFIED` ("Recording a verification with `covered` true advances the financial dimension `UNVERIFIED → VERIFIED`"), so `test_18` asserts `VERIFIED`.

The `consistency_model` section has no matching PRD section heading, but every individual outcome it asserts is uniquely derivable from PRD rules that are quoted in the test (the shelf recompute list, the "derived on demand and none is stored" summary, and the 10300-cent responsibility), so the instance was translated rather than skipped.

**Orchestrator verification:** confirmed `test_helpers/` and `test_suite/` are at the task root and that `workspace/test_helpers` / `workspace/test_suite` do not exist. Steps 5 and 6 were launched in a single assistant message so the implementation generator started before `test_suite/` existed on disk (physical isolation from the tests).

## Step 7: Run Tests and Iterate — 2026-09-05T09:52:00.000Z

Clean 8-round sweep achieved: **100/100 passed in all 8 parallel rounds** (~180s per round).

## Summary

**Iterations run:** 2 (iteration 1 = baseline sweep, 94/100 deterministic in all 8 rounds; iteration 2 = verification, 100/100 in all 8 rounds).

The 6 failures were deterministic (identical in all 8 rounds) — no flakiness or load-induced failures appeared. All 6 traced to the test artifact; **no implementation change was needed**.

**Tests deleted:** none. Three assertions were partially trimmed under STEP 1c (partial-coverage handling):

- `test_02_pinned_formula_order.py::test_restock_refund_rounds_the_device_split_then_each_refund_line` — dropped `lifetime_restocked_qty=1`
- `test_02_pinned_formula_order.py::test_non_sellable_poor_fit_return_uses_the_heaviest_fee_fraction` — dropped `lifetime_destroyed_qty=1`, `lifetime_restocked_qty=0`
- `test_03_state_machine_walks.py::test_destroyed_return_reaches_the_same_terminal_refit_state` — dropped `lifetime_destroyed_qty=1`

PRD-silence category: **COMPUTED-FIELD SILENCE**. PRD §3.2 enumerates the shelf's fields as `on_hand_qty`, `reserved_qty`, `available_qty`, `lifetime_received_qty` and `stock_posture`; the strings `lifetime_restocked_qty` / `lifetime_destroyed_qty` / `lifetime_dispensed_qty` appear **zero times** anywhere in PRD.md. The PRD-faithful implementation correctly omits them. The covered `on_hand_qty` / `stock_posture` assertions in the same calls were kept.

**Fixes applied to `test_helpers/`:**

- `assertions.py`, `assert_shelf` — removed the three PRD-silent `lifetime_*_qty` parameters from the signature and the checks dict, so no future test can assert a non-PRD shelf field.
- `factories.py`, new `_variant_product_payload` helper backing `knee_brace_/custom_afo_/custom_fitted_/wrist_splint_/cervical_collar_product_payload` — the five variants passed their own defaults *and* `**overrides` as keywords into `product_payload`, so any caller overriding a variant default raised `TypeError: got multiple values for keyword argument`. Defaults are now merged before the call, caller wins.
- `factories.py`, `off_shelf_fitter_payload` — same latent collision on `full_name` / `privilege_scope`, fixed the same way.

**Fixes applied to `test_suite/`:**

- `test_10_entity_contracts.py::test_re_verifying_coverage_appends_a_second_row_and_leaves_the_first_intact` — setup issued a second `covered: true` verification from a `VERIFIED` encounter. PRD §3.4 declares only two origins ("advances the financial dimension `UNVERIFIED → VERIFIED`… Either may also be recorded when the dimension already sits at `NON_COVERED`"), so `VERIFIED` is not a declared origin and the implementation's `ERR_INVALID_FINANCIAL_STATE` is correct. First row now records `covered: false`, exercising the PRD's stated correction path `NON_COVERED → VERIFIED`; two `covered` assertions added, all original assertions kept.
- `test_16_rbac_corners.py::test_the_three_shared_writes_treat_both_of_their_holders_identically` — sent `payer_type="MEDICARE_PART_B"`, which is not a member of PRD §3.1's declared set (`MEDICARE`, `MEDICAID`, `COMMERCIAL`, `SELF_PAY`); the implementation's `ERR_INVALID_REQUEST` was correct. Changed to `MEDICARE` in both the request and the echo assertion.

**Fixes applied to `implementation/`:** none. Every failure was a test-layer defect; no PRD-required check was removed or weakened, and no assertion was downgraded, skipped or xfailed.

**Orchestrator verification:** independently re-read all 8 `results.$i.json` (each 31 KB, written 09:50) and confirmed `passed == total == 100`, `failed == 0` in every one of the 8 rounds. Sweep artifacts are present on disk, so the clean-sweep claim is substantiated rather than merely asserted. The subagent did not touch worklog.md.

**Step 8 gate:** Step 7 ran 2 iterations with non-zero test-layer fixes (2 `test_helpers/` files, 2 `test_suite/` files, 3 trimmed assertions), so the skip condition does not apply and Step 8 must run. Note for Step 8: `implementation/` fixes were zero, so the expected PRD delta is small — the `lifetime_*_qty` trims are the one genuine PRD-silence signal (the shelf serializer does not expose them), while the two `test_suite/` fixes were pure test-layer defects that reveal no PRD gap.

## Step 8: Finalize PRD — 2026-09-05T10:02:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one edit.

## Line counts / delta
- PRD.md: 423 lines, 15,108 words
- PRD_FINALIZED.md: 423 lines, 15,150 words
- Delta: 1 line revised out of 423 = **0.24% of lines**, +42 words = **+0.28%**

## Changes
- **§3.2 (Par Levels, Stock Receipts and the Clinic's Dispensing Posture), line 180** — *revise* — appended one sentence to the "A new shelf opens empty" paragraph pinning `lifetime_received_qty` as the shelf's only cumulative lifetime counter and stating the shelf carries no `lifetime_dispensed_qty` / `lifetime_restocked_qty` / `lifetime_destroyed_qty` field, with cumulative dispense/restock/destruction figures computed at clinic level by the §3.9 reconciliation read — `implementation/store.py:245-258` (`par_level_json`), `implementation/routes/inventory.py:33-42`, `implementation/calc.py:316-322`.

## Pre-edit search log (the one edit)
(a) **Subject**: the `ClinicParLevel` (shelf) resource's persisted keys and serialized field set, specifically cumulative counters.

(b) **Impl paths enumerated, read or grepped**:
- `implementation/store.py:245` `par_level_json` — the sole shelf serializer; emits `clinic_id, product_id, par_min_qty, par_max_qty, on_hand_qty, reserved_qty, available_qty, stock_posture, lifetime_received_qty` plus `_common` (`store.py:160`: `id, created_at, updated_at, version`). No `lifetime_restocked_qty`/`lifetime_destroyed_qty`/`lifetime_dispensed_qty`.
- All four `par_level_json` callsites (`routes/inventory.py:47,54,71,86`) — create, get, list, stock receipt. No other serializer of a shelf exists anywhere (grep over `implementation/`).
- Every writer of a shelf row, grepped across all modules: `routes/inventory.py:33-42` (row creation key set), `:82-83` (receipt raises `on_hand_qty` + `lifetime_received_qty`), `routes/encounters.py:214` (reserve), `:78-80` (release), `:441-444` (dispense consumption), `routes/finance.py:298-300` (ABN-refusal release), `routes/returns.py:100` (restock raises `on_hand_qty` only), `calc.py:32` (`stock_posture`). Confirmed: the only mutated keys are `on_hand_qty`, `reserved_qty`, `lifetime_received_qty`, `stock_posture` (+ `touch`'s `version`/`updated_at`) — no code path ever adds another counter key.
- `calc.py:271-329` `dispensing_summary` and its single callsite `routes/clinics.py:48-51` — confirms the cumulative dispensed/restocked/destroyed figures exist only as clinic-level `units_*_total` in the reconciliation read, computed from encounters and returns, never from a shelf counter.
- Grep for `_total"` across the impl — no other endpoint reports cumulative dispense/restock/destroy figures.

(c) **Wording adjustments made**: two. First, I scoped the exclusivity claim to *cumulative lifetime counters* rather than to shelf quantities or shelf fields in general, because `par_min_qty`, `par_max_qty`, `on_hand_qty` and `reserved_qty` are also quantity fields and a broader "only field" claim would have contradicted `par_level_json`. Second, I avoided an "only the reconciliation read reports these figures" universal and instead wrote that they "are computed at the clinic level by the reconciliation read of §3.9 rather than stored on the shelf" — the load-bearing claim is the absence of a shelf counter, and the softer phrasing cannot be falsified by any other endpoint that happens to expose a per-encounter `quantity` or per-return `quantity_returned`.

## Diff items that correctly received NO PRD edit
Four of the five Step 7 items reveal no PRD gap and were deliberately left unpatched:
1. **`factories.py` variant-payload keyword collision** (`_variant_product_payload` backing the five product variants) — pure fixture bug: Python `TypeError: got multiple values for keyword argument`. No behavioral surface at all.
2. **`factories.py` `off_shelf_fitter_payload`** — same latent collision, same verdict.
3. **`test_10_entity_contracts.py` re-verification from `VERIFIED`** — PRD already determines this. §3.4 declares the only two origins ("advances the financial dimension `UNVERIFIED → VERIFIED`… Either may also be recorded when the dimension already sits at `NON_COVERED`"), and §2.12 pins the error for a financial transition with no declared origin: "The equivalent financial violation… is `ERR_INVALID_FINANCIAL_STATE`, also HTTP 409". `routes/finance.py:41-43` (`VERIFIABLE_FINANCIAL = ("UNVERIFIED", "NON_COVERED")`) matches verbatim PRD. No edit.
4. **`test_16_rbac_corners.py` `payer_type="MEDICARE_PART_B"`** — PRD already determines this. §3.1 declares the member set and §2.9's second band states `ERR_INVALID_REQUEST` "fires when… an enum value is not a declared member". No edit.

Note on an adjacent path I found but deliberately did **not** touch, for Step 9's awareness: `routes/finance.py:41` returns `ERR_INVALID_FINANCIAL_STATE` for the *closed-clinical-dimension* gate on a coverage verification (PRD §3.4 states the gate but not its error code, and §2.9 band 4 would ordinarily put `ERR_INVALID_CLINICAL_STATE` first). That is a real PRD under-determination, but it is off every Step 7 site — no diff item exercised it — so patching it would have violated the hard scope rule.

**Orchestrator verification:** `cmp` confirms `PRD_FINALIZED.md` differs from `PRD.md` (109438 vs 109091 bytes), and the diff is the single §3.2 paragraph revision described above — consistent with the reported 1-line/+42-word delta.

## Step 9: Complete PRD — 2026-09-05T10:32:00.000Z

Step 9 was run as **three sequential passes over one shared `PRD_COMPLETED.md`**, partitioned by implementation module. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying so the earlier passes' edits survived. **54 edits total (14 + 19 + 21)**: 44 ambiguity-pins, 10 mismatch-revisions. Final size 425 lines / 124,143 chars, versus 423 / 109,438 for `PRD_FINALIZED.md` — **+2 lines, +14,705 chars (+13.4%)**, almost all of it in-paragraph inserts.

### Pass 1 — app.py, common.py, store.py, guards.py, routes/clock.py (14 edits: 13 ambiguity, 1 mismatch)

Verified clean with no change needed: the 62-entry `ERROR_STATUS` map matches §5's table exactly (same identifiers, statuses, order); all 28 domain enums in `store.py` match their PRD enumerations member-for-member; all 14 serializers' field sets are already named in PRD prose; `CoverageVerification` is the only serializer without `updated_at`/`version`, as §2.5 pins; `actor_check=False` is used on exactly the two operations §2.1's carve-out names.

- §2.1 — revise — ambiguity — whitespace-only auth headers rejected as empty — `common.py:324-327`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + twenty lowercase hex chars — `common.py:208`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the one timestamp read from real host time, not the logical clock; never agrees with `created_at`, no rule evaluated against it — `common.py:209`
- §2.2 — insert — ambiguity — 5xx responses carry the same error envelope — `app.py:42-47`
- §2.3 — revise — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST`, never clamped; `offset` unbounded above; over-the-end offset yields empty page with true `total_count` — `common.py:241-272`
- §2.3 — insert — ambiguity — enum filters reject undeclared values (not empty page); boolean filters accept only `true/false/1/0` case-insensitively; id filters match literally; undeclared query params ignored — `common.py:275-293`
- §2.3 — insert — ambiguity — `created_at` ties broken by an internal insertion counter, never exposed — `store.py:65-67,92-93`
- §2.4 — insert — ambiguity — tolerant ISO-8601 instant parsing (any fractional width, offset normalised, naive read as UTC); strict 10-char `YYYY-MM-DD` dates; canonical 3-digit-`Z` output; unset temporal fields emitted as `null` — `common.py:36-79`
- §2.5 — revise — ambiguity — `created_at` read from the logical clock, so simultaneous creations share it — `store.py:70-78`
- §2.5 — revise — ambiguity — `updated_at` also from the logical clock, equals `created_at` before first mutation — `store.py:81-84`
- §2.9 — revise — ambiguity — band-2 shape gate expanded to its real trigger set (bad JSON / non-object body, blank-after-trim and length bounds, range violations at either end, unparseable dates/instants, excess decimal places, empty/blank/duplicate list members, non-empty-object maps, malformed pagination) plus three conventions: explicit `null` ≡ absent, booleans and fractional numbers never satisfy an integer, absent/empty body ≡ `{}`, strings stored verbatim — `common.py:348-511`
- §2.9 — revise — **mismatch** — band 4's clinical-before-financial precedence governs only operations that move the clinical dimension; a purely financial operation reports its "encounter not clinically closed" precondition as `ERR_INVALID_FINANCIAL_STATE` — `routes/finance.py:20,40,196`. This resolves the `finance.py:41` under-determination Step 8 flagged but could not touch under its hard scope rule, and the same wording covers the identically-shaped ABN self-loop gate.
- §3.2 — insert — ambiguity — a `RESTRICTED` clinic never blocks an operation that targets no shelf (fab order, `CUSTOM_FABRICATED` dispense) — `guards.py:90-97`
- §3.4 — revise — ambiguity — the verification row echoes `deductible_remaining_cents`/`valid_for_days` as integers and `coinsurance_pct` as the client's own JSON number — `store.py:307-324`, `routes/finance.py:58`
- §3.4 — revise — ambiguity — `appeal_note` validated but persisted nowhere, absent from all responses — `store.py:327-339`, `routes/finance.py:166`
- §3.6 — revise — ambiguity — fitting-check `note` likewise validated but never stored or returned — `store.py:377-394`, `routes/fabrication.py:82`
- §4 — insert — ambiguity — trailing slash insignificant in path matching — `app.py:19`
- §5 — insert — ambiguity — `ERR_NOT_FOUND` 404 (unrouted path), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 sit outside the ladder and the table — `app.py:31-47`

### Pass 2 — routes/clinics.py, routes/catalog.py, routes/inventory.py, routes/encounters.py, calc.py posture/cascade/lookback/summary (19 edits: 13 ambiguity, 6 mismatch across 5 distinct defects)

- §2.10 — revise — mismatch — quality-hold *release* cascade is conditional on the same request also affirming `dmepos_standards_attested` — `routes/catalog.py:78`
- §3.1 — revise — mismatch — same fact at the operation's own description: lowering the hold while withdrawing the attestation leaves orders in `SUPPLIER_HOLD` and encounters held — `routes/catalog.py:78-88`
- §3.2 — insert — ambiguity — `par_max_qty` admitted at the shape gate from 0, so `0` clears band 2 and is then caught as `ERR_PAR_MAX_EXCEEDED` — `routes/inventory.py:22,31`
- §3.2 — insert — ambiguity — `received_qty` is 0-or-more; a 0-unit receipt is admitted and still advances `version`; response is the updated shelf — `routes/inventory.py:78-86`
- §3.3 — insert — ambiguity — `service_date` stored as supplied with no relation to the clock (past or future accepted) — `routes/encounters.py:93,104`
- §3.3 — insert — ambiguity — opening state pins `covered_units` 0, `responsibility_variant` null, plus the full roster of null-at-creation fields — `routes/encounters.py:37-58`
- §3.3 — insert — ambiguity — a note signed by a non-ordering physician is `ERR_INVALID_CLINICAL_STATE`/409, with the `DRAFT` check evaluated first — `routes/encounters.py:150-153`
- §3.3 — insert — ambiguity — `mn_expected_duration_months` is an integer of at least 0 — `routes/encounters.py:148`
- §3.3 — insert — ambiguity ×2 — note and IOAS attestation each answer with the updated encounter — `routes/encounters.py:164,185`
- §3.6 — insert — ambiguity — a reservation of a `CUSTOM_FABRICATED` item looks for no shelf and runs no version comparison, so it reports the category mismatch, not `ERR_PAR_LEVEL_NOT_FOUND`/`ERR_STALE_PAR_LEVEL_VERSION` — `routes/encounters.py:196-203`
- §3.6 — insert — ambiguity — `expected_par_level_version` is an integer ≥ 0 (negative = shape error, not 412); reservation answers with the encounter — `routes/encounters.py:192,219`
- §3.6 — insert — ambiguity — the created `CustomFabOrder`, not the encounter, is the response body — `routes/encounters.py:260`
- §3.7 — insert — ambiguity — the created `FittingRecord` is the response body — `routes/encounters.py:331`
- §3.7 — revise — mismatch — "checked twice" now defers to §2.9: `ERR_FITTING_SLOT_CONFLICT` is evaluated before `ERR_INVALID_INTERVAL` — `routes/encounters.py:294-306`
- §3.7 — insert — mismatch — `ADJUST_NEEDED` and `REJECTED` are declared from `RESERVED` alone; an `AWAITING_DEVICE` encounter admits `ACCEPTABLE` only — `routes/encounters.py:263-267`
- §3.8 — revise ×2 — mismatch — the dispensing-posture sentence moved from just after the fitter-credential check to the bottom of the ladder, after documentation, coverage and authorization — `routes/encounters.py:419-420`
- §3.8 — insert — ambiguity — the excess-units ABN gate is keyed on `covered_units` as computed in the responsibility step; dispense answers with the updated encounter — `routes/encounters.py:413-414,447`
- §3.9 — insert — ambiguity — the cash ledger draws no product-category distinction (custom-fab charges, refunds and retained fees all count), unlike the unit ledger — `calc.py:286-310`

Pass 1 hand-off dispositions: (1) `covered_units`/`responsibility_variant` opening values — pinned in §3.3. (2) §3.8 posture ordering — the narrative order was judged misleading enough to fix rather than lean on "ladder order of §2.9", so the sentence was relocated. (3) `par_max_qty` shape-gate floor of 0 — pinned in §3.2.

### Pass 3 — routes/finance.py, routes/fabrication.py, routes/returns.py, calc.py money/turnaround (21 edits: 18 ambiguity, 3 mismatch)

- §3.4 — insert — ambiguity — a new `PriorAuthRequest` opens with `approved_units`, `auth_number`, `decision_at`, `expires_at` all null — `finance.py:99-108`
- §3.4 — insert — ambiguity — `APPROVED` defaults `approved_units` to `requested_units` when omitted; `valid_for_days` admitted from 1 with no upper bound and, when omitted, leaves `expires_at` null; `approved_units` 0 clears the shape gate and is caught as `ERR_APPROVED_UNITS_EXCEED_REQUEST` while a negative is a 400 — `finance.py:130-153`
- §3.4 — insert — ambiguity — `DENIED`/`PENDED` validate then discard `approved_units`/`auth_number`/`valid_for_days`, writing only `status` and `decision_at` — `finance.py:146-154`
- §3.4 — insert — ambiguity — an approval whose `expires_at` is null never goes stale, and no other request reads the expiry — `finance.py:152-153`, `encounters.py:404-410`
- §3.5 — insert — ambiguity — `expected_encounter_version` is an integer of 0 or more; negative is a shape error, not 412 — `finance.py:205`
- §3.5 — revise — **mismatch** — signing a notice voided by a later issuance is `ERR_INVALID_ABN_STATE` (the state check precedes the superseded check); `ERR_ABN_SUPERSEDED` pinned as catalogued-but-unreachable, since issuance voids every outstanding notice — `finance.py:266-271`. This is the resolution of the spec conflict Step 6 flagged.
- §3.5 — insert — ambiguity — a new notice opens with `option_selected`, `signed_by`, `patient_signed_at` null — `finance.py:222-235`
- §3.5 — revise — ambiguity — cash quote step one: absent auth or null `approved_units` contributes 0 approved units; quoted count floored at 0; step two reworded to "below 2" so a zero-unit quote determinately yields full `cash_price_cents`, subtotal 0 and a 2500-cent fee — `calc.py:139-153`
- §3.5 — insert — ambiguity — `signed_by` is optional (defaults null); a declined signature records `signed_by`, advances only the notice's `version` and does not touch the encounter; the response body is the notice — `finance.py:262,274-281`
- §3.5 — revise — **mismatch** — the `OPTION_3` clinical cascade voids only from `DRAFT`/`DOCUMENTED`/`RESERVED`; `AWAITING_DEVICE` and `FITTED` keep their `clinical_status` while the financial dimension still moves to `WRITTEN_OFF` and money zeroes — `finance.py:255,289-303`
- §3.6 — insert — ambiguity — `SUPPLIER_HOLD → IN_FABRICATION` demands the full standards+accreditation+quality posture (like `SUBMITTED`), not just the quality check — `fabrication.py:55-57`
- §3.6 — insert — ambiguity — the fitting check runs no clinic-scope comparison, so a foreign-clinic credentialled fitter may close/rework/cancel — `fabrication.py:77-94`
- §3.6 — insert — ambiguity — every fabrication event and fitting-check outcome answers with the `CustomFabOrder`, including `CANCEL`, which also mutates the encounter — `fabrication.py:119-127`
- §3.6 — insert — ambiguity — a null `final_turnaround_score` in the accepted set contributes 0 to the supplier mean — `calc.py:264`
- §3.8 — insert — ambiguity — step two: no authorization row or a null `approved_units` counts as zero covered units, a state the §3.4 `APPROVED` default keeps out of reach at dispense — `calc.py:167-171`
- §3.8 — revise — **mismatch** — the dispense authorization gate accepts an `APPROVED` auth with a null `expires_at` (PRD had promised an unconditional expiry comparison) — `encounters.py:404-410`, `finance.py:152`
- §3.8 — insert — ambiguity — `ABN_CASH_SELFPAY` reads the greatest-`notice_seq` notice, which the excess-units gate guarantees is signed on `OPTION_1`/`OPTION_2`; with no notice at all the figure would be 0 — `calc.py:179-186`
- §3.9 — insert — ambiguity — `return_note` is persisted and echoed (unlike the appeal/fitting notes), null when omitted — `returns.py:33,45-63`
- §3.9 — insert — ambiguity — `restock_fee_pct` is emitted as a bare JSON number in shortest decimal form (`0.0`, `0.1`, `0.2`, `0.25`), null before inspection — `calc.py:235`
- §3.9 — insert — ambiguity — refit also copies `mn_physician_id` and `service_date`; supervision fields are **not** carried forward; response body is the new encounter — `returns.py:128-145`
- §3.9 — insert — ambiguity — refit never parses a body, so anything sent is ignored rather than shape-checked — `returns.py:113-117`

Pass 2 hand-off dispositions, all addressed: the null-`approved_units` path was reconciled against the decision-endpoint default (`APPROVED` with no `approved_units` takes `requested_units`), so §3.4 pins the default and §3.8 pins the zero-count reading while noting the combination is unreachable on a committing dispense; the no-notice `ABN_CASH_SELFPAY` case, the `restock_fee_pct` float form, the null-`final_turnaround_score` mean, and the zero-unit `UNITS_EXCEED_AUTH` quote were each pinned inline. Pass 3 also confirmed §2.9's new band-4 wording covers `finance.py:20,40,196`, so no §3.4 edit was needed for that item.

### Orchestrator final verification

- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (124,143 vs 109,438 bytes), so the scan genuinely ran in all three passes.
- Document integrity: 5 `##` headings, subsections §2.1–2.12 and §3.1–3.9 each present once, §4 endpoint table 49 data rows, §5 error table 62 data rows, file ends on the complete `| ERR_PAR_MAX_EXCEEDED | 422 |` row under `## 5. Error Code Catalogue`. No truncation.
- Step 9 was documentation-only, as required: `find` over `implementation/`, `test_suite/` and `test_helpers/` shows **no** `.py` or `start.sh` modified after 09:50, the timestamp of the green 8-round sweep. The 8 passing `results.$i.json` therefore remain valid evidence for the artifact as shipped.
- Cleanup: removed the four `.scratch*` directories and the `__pycache__` trees so the harness boots cold. `worklog.md` sits only at the task root — no stray copy drifted into `workspace/`.

**Pipeline complete.** Steps 1–9 all finished; `workspace/PRD_COMPLETED.md` is written.
