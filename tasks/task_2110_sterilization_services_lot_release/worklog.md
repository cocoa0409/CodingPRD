# Worklog — task_2110_sterilization_services_lot_release

## Step 1: Create task directory — 2026-08-16T18:42:00.000Z

Created `tasks/task_2110_sterilization_services_lot_release/` and `workspace/`. Index 2110 chosen as `max(task_NNNN) + 1` over `./tasks/` (highest existing was 2109), matching the scenario's own item number.

## Step 3: Copy shared files — 2026-08-16T18:42:00.000Z

Copied `./INSTRUCTION.md` -> `tasks/task_2110_sterilization_services_lot_release/workspace/INSTRUCTION.md` (performed together with Step 1 as a single bash block).

## Scaffold generation — 2026-08-16T20:00:00.000Z

Generated `SCAFFOLD.yaml` (§1.0–§1.7 + §1.2.1 concurrency rules + a cross-cutting `invariants:` block),
`SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 9 rule blocks / 21 instances) and
`SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 9 sections / 113 instances, 17 of them `excluded_because` stubs).
`scaffold_lint.py` reports `VERDICT: clean lint` over 1671 scanned calls.

## Step 2: Generate scaffold — 2026-08-16T19:57:00.000Z

All three artifacts are generated, validated, and lint-clean.

## Files written
- `SCAFFOLD.yaml` (§1.0–§1.7; neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

## Scaffold shape (top of the Expert band, per the "harder than expert" instruction)
- **Profile**: `compliance_audit` × `temporal_windowing`; topology `graph`; state-machine shape `cyclic`; role model `segregation_of_duties`; layers = OCC, cascading side effects, dual-variant calculation, rate/threshold triggers.
- **13 entities**: Customer, Product, EmissionPermit, Chamber, CycleRecipe, ProductQualification, DoseAudit, Lot, Cycle, LoadPosition, Indicator, AerationRecord, AdverseEvent. Graph topology: LoadPosition is the Lot<->Cycle junction, Lot is self-referential via `parent_lot_id`, Chamber->EmissionPermit is a cross-aggregate capacity edge.
- **9 state machines / 60 transitions**: Cycle (branching fork at DOSIMETRY_REVIEW + two cycles: READY->LOADING and DOSE_DEVIATION->DOSIMETRY_REVIEW), Lot on **two parallel axes** (`status` x `residual_status`), ProductQualification (audit loop, counter-bounded exit to REVOKED), AerationRecord (retest self-loop), AdverseEvent, EmissionPermit, Chamber, CycleRecipe.
- **10 calculations**: cycle_load_density (rounding-order pinned), delivered_dose_kgy (**dual variant** ROUTINE_MEAN/MIN_ZONE), dose_conformance_verdict, lot_cumulative_dose, aeration_required_hours (**dual variant** STANDARD/EXTENDED_RETEST — multiplier *and* anchor move), residual_verdict, emission_fee_usd (tier keyed on **post-charge** YTD), cycle_occupancy_window (two different interval geometries), vdmax_audit_verdict, governing_cycle_selector.
- **33 validations** (priority 10->98), **48 endpoints** (incl. `POST /sterilization/_clock/set_current_utc`, default `2026-08-01T00:00:00Z`), **48 errors**, **5 roles** (RegulatoryAdmin, CustomerRep [`entity_backed:Customer`], CycleOperator, DosimetryAnalyst, QualityReleaseOfficer — all others `opaque`), **2 OCC rules** (`load-position-create-stale-cycle`, `adverse-event-create-stale-lot`), **2 named conserved-quantity invariants** (abated-EtO mass ledger; discrete pallet count).

## Design indices
- **§1.8**: 9 rule blocks, **21 instances** (2–3 per rule; every §0.5 minimum met). Highlights: depth-4 cascade (close -> cycle deviation -> lot quarantine -> qualification AUDIT_DUE -> sibling lot stripped from another cycle's load map), depth-3 resterilize cascade, three distinct validation-priority pairs, chamber half-open buffered overlap vs permit closed-interval aggregate cap.
- **§1.9**: 9 sections, **113 instances** (17 `excluded_because` stubs), spread entities 17 / state_machines 19 / calculations 17 / validations 29 / endpoints 13 / errors 3 / rbac 7 / cross_cutting 6 / consistency_model 2.

## Verification performed
- `scaffold_lint.py` -> **`VERDICT: clean lint`** over 1671 scanned calls (48 endpoints, 13 entities, 21 §1.8 + 96 active §1.9 instances).
- Every `${var}` bound by an earlier `captures:`; 134 instance names globally unique; all `grounds:` refs resolve; all stub targets exist; endpoint `roles:` <-> RBAC matrix match exactly both ways; enum closure clean (remaining values are client-supplied inputs); no forbidden concurrency vocabulary anywhere.
- **Every formula-derived assert was computed in Python before being written as a literal** — densities (0.1000 / 0.1050 vs the rejected 0.1063 / 0.1031 / 0.0800 / 0.2000), doses (30.09, 26.85, 29.83), emission fees (576.00, 74.00 vs the rejected pre-charge 48.00, 6480.00, 24.00), aeration hours/anchors (15->23->30 h; 2026-08-13T22:30:00Z), and all audit due-dates.

One thing worth flagging: the corner file is large (432 KB; ~113 full call chains). Every instance is distinct and non-redundant, but if the downstream unit-test-generator has a tight context budget you may want to prune the §1.9 `validations` and `entities` sections first — they carry the most instances with the shortest chains.

**Orchestrator verification**: SCAFFOLD.yaml 2681 lines / 134 KB; SCAFFOLD_DIFFICULTY_DESIGN.yaml 2301 lines / 150 KB; SCAFFOLD_CORNER_DESIGN.yaml 7028 lines / 432 KB. Confirmed SCAFFOLD.yaml contains neither design key; each design file has exactly one top-level design key.

## Step 4: Generate PRD — 2026-08-16T20:12:00.000Z

The PRD is written and verified.

## Output
`workspace/PRD.md` — **403 lines, ~12,700 words**.

## Section list
- **§1 Introduction** (3 paragraphs)
- **§2 Global Specifications** (10 subsections): 2.1 Operator Identity & RBAC · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Record Identity, Audit Trail & Facility Clock · 2.5 Precision in Dose/Density/Mass/Time/Money · 2.6 Load-Map & Lot-File Concurrency Control · 2.7 Order of Screening (all 33 validations as an ordered list) · 2.8 Batch-Record Consistency & Cascading Reversal · 2.9 Conserved Quantities · 2.10 Segregation of Duties
- **§3 Business Logic** (9 subsections): 3.1 Accounts/Products/Modalities · 3.2 Permits, Chambers & Emission Rate Schedule · 3.3 Recipes & VDmax Qualification · 3.4 Receiving Lots & Scheduling Chamber Time · 3.5 Building the Load Map · 3.6 Readiness, Dwell & Emission Debit · 3.7 Dosimetry Review, Delivered Dose & Deviation Cascade · 3.8 Aeration & Residual Clearance · 3.9 Quarantine, Release & Adverse-Event Disposition
- **§4 Endpoint Definitions** (4-column table) · **§5 Error Code Catalogue** (2-column table). No audit footer.

## Self-verified coverage (PRD vs scaffold)
| Item | Found / Expected |
|---|---|
| Entities named | 13 / 13 |
| State-machine transitions (explicit `FROM -> TO` pair in prose) | 60 / 60 |
| Calculations | 10 / 10, incl. both variants of `delivered_dose_kgy` (`ROUTINE_MEAN`/`MIN_ZONE`) and `aeration_required_hours` (`STANDARD`/`EXTENDED_RETEST`) |
| Validations (error_id present in the §2.7 priority-ordered chain) | 33 / 33, in exact scaffold priority order 10->98 |
| Endpoints in §4 table | 48 / 48 |
| Errors | 48 / 48 in §5 table **and** 48 / 48 mentioned in §2–§3 narrative |
| Roles | 5 / 5, each with its `identity:` translated |
| OCC rules | 2 / 2 (`expected_cycle_version`->`ERR_STALE_CYCLE_VERSION` 412; `expected_lot_version`->`ERR_STALE_LOT_VERSION` 412) |
| Conserved-quantity invariants | 2 / 2 (pallet conservation; abated-EtO/fee ledger with exact-credit abort) |

**Hard contracts:** Contract 1 field coverage — entities 114/114, request bodies 71/71, query params 11/11, path params 2/2, 0 missing -> PASS. Contract 2 rule coverage — all six high-risk categories plus the tail walked; gaps found and repaired during the pass (missing `load_position_id`, implicit `LOADING -> LOADING` delete branch, implicit `PLANNED/LOADING/READY -> CANCELLED` and `RUNNING -> CANCELLED` pairs, load-position preconditions reordered to match §2.7 screening order, OCC write endpoints named explicitly) -> PASS. Contract 3 §3 path purity — 871 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos -> PASS. §2.2 verified byte-identical to `section-2.2-response-structure.md`; no fuzzy/approximating words present. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read.

**Orchestrator verification (anti-truncation check)**: 402 lines; all 5 top-level sections present; §4 endpoint table = 50 table rows (48 endpoints + header + separator); §5 error table = 50 rows (48 errors + header + separator); 48 unique `ERR_*` ids across the document; file ends mid-catalogue with no truncation. The known large-PRD tail-loss failure mode did NOT occur.

## Step 6: Generate implementation — 2026-08-16T20:38:00.000Z

Implementation complete and verified.

## Files written (`workspace/implementation/`, 2,681 LOC total)

| Layer | Files |
|---|---|
| Launcher | `start.sh` (10), `requirements.txt` |
| Foundation | `app.py` (79), `errors.py` (112), `response.py` (89), `middleware.py` (32), `validation.py` (189), `clock.py` (63), `db.py` (35) |
| Services | `services/calc.py` (154), `services/domain.py` (257) |
| Routes | `routes/reference.py` (467), `routes/cycles.py` (536), `routes/lots.py` (275), `routes/misc.py` (192), `routes/positions.py` (152), `routes/common.py` (38) |

## Coverage (machine-verified against the PRD, not by eye)

- **Endpoints: 48/48** — parsed the §4 table and diffed against `app.url_map`: 0 missing, 0 extra.
- **Errors: 48/48** — every `ERR_*` in §5 is raised from a non-`errors.py` code path; all 48 HTTP statuses match the §5 table exactly (401/402/403/404/409/412/422).
- Nothing was left stubbed: dosimetry review with both `delivered_dose_kgy` variants, the depth-4 deviation cascade (quarantine -> qualification `AUDIT_DUE` -> sibling-lot strip from other cycles' load maps), aeration/`EXTENDED_RETEST` re-test with the moving anchor, the VDmax audit state machine incl. `CONDITIONAL`x2 -> `REVOKED`, the six-step post-charge emission fee ledger with exact-credit abort, and the depth-3 re-sterilization cascade are all implemented and exercised.

## Verification performed

Four hand-written HTTP suites (~190 assertions) run against fresh processes — **0 failures**, plus a sweep of all 20 GET endpoints (all 200). Confirmed numerically: density `0.1000` (single-quotient rounding), aeration `15 -> 23 -> 30 h` with anchor moved to `last_failed_sample_at`, emission fee `120.00` at tier 1 and permit auto-`SUSPENDED` at the allowance, abort crediting the ledger bit-for-bit back to `0.000`/`0.00` and restoring `ACTIVE`, MIN_ZONE flipping a load to `UNDERDOSE`, re-read reopening `DOSE_DEVIATION -> DOSIMETRY_REVIEW` and the conforming re-close compensating `quarantine_reason`/`schedulable`, and successor lot `L-1-R1` inheriting `cumulative_dose_kgy`.

Validation ordering follows §2.7's global priority chain (10->98) on every endpoint, including the ones where it is counter-intuitive: schema (25) is screened **before** path 404s (30), duplicate-code (38) **before** customer scoping (40), capacity (88) **before** cumulative-dose headroom (92).

## Contract confirmations

- `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs in the foreground via `exec python3 app.py`, and guards the `pip install` behind `python3 -c "import flask"` so per-test reboots don't re-install. Booted successfully via `bash start.sh`.
- **Storage is in-memory only** — plain dicts in `db.py`; no SQLite, no JSON dump, no `/tmp`, no file writes anywhere. Confirmed by grep.
- **No seeding**: a freshly booted server returns `total_count: 0` for every collection; the only occurrences of the word "seed" are the comments asserting the absence.

## Two judgement calls worth flagging

1. **`permit_code` uniqueness is enforced** (`ERR_DUPLICATE_CODE`). §3.2 calls it "unique across the facility", but §2.7 step 6 and the §5 trigger list both omit permits from the checked operations. I enforced it since a test creating two identical permit codes almost certainly expects 409.
2. **`position_index > chamber.pallet_capacity` yields `ERR_VALIDATION`** at priority 25 (evaluated by peeking at the cycle, so a bad path id still 404s at priority 30). §3.5 states the bound but §2.7 step 3 doesn't enumerate it, so no error id is formally assigned to it.

**Orchestrator verification**: 2670 LOC across 16 `.py` files; `app.py:78-79` reads `$PORT` (default 10000) and binds `0.0.0.0` with `use_reloader=False`; `start.sh` ends in `exec python3 app.py` (foreground). Grep for `sqlite` / `json.dump(` to file / `open(...,'w')` / `/tmp` found no persistence (only `json.dumps` for response serialization).

## Step 5: Generate unit tests — 2026-08-16T20:57:00.000Z

All work is complete and verified. Final summary:

## Files written

**`test_helpers/`** (Stage 1) — `__init__.py`, `types.py` (13 entity TypedDicts + 20 enums; `DoseAudit` correctly omits `updated_at`/`version`), `api_client.py` (all 48 endpoints), `api_errors.py` (48 error ids + HTTP map, registered with the framework), `assertions.py` (per-entity checkers, decimal-precision and pallet-conservation invariants, `assert_instant_equals`), `factories.py`, `constants.py`, `test_users.py` (identity-threaded `make_customer_rep_headers`), `fixtures.py` (~40 primitives + `setup_reference_data`, `build_cycle_scenario(stage=...)` walking planned->loading->ready->running->completed->review->closed, `setup_quarantined_lot`, `setup_released_lot`, `setup_aerating_lot`).

**`test_suite/`** (Stage 2) — `conftest.py` + 17 test files: `test_01`–`test_07` and `test_17` carry queue B, `test_08`–`test_16` carry queue A.

## Counts

- **135 test functions / 136 pytest items** (one parametrized function contributes 2).
- **Queue A (Difficulty): 21/21 instances emitted, 0 skipped** — 42 tests, every instance covered by >=2.
- **Queue B (Corner): 93/96 active instances emitted, 3 skipped** — entities 15/17, state_machines 16/16, calculations 12/12, validations 26/26, endpoints 9/10, errors 3/3, rbac 7/7, cross_cutting 3/3, consistency_model 2/2. All 17 `excluded_because` stubs left untranslated; every `difficulty_instance` back-reference verified to resolve.

## Skipped instances (gaps left as gaps)

| Instance | Reason |
|---|---|
| `corner_create_lot_client_supplied_status_input_ignored` | Non-unique-derivability — the instance asserts `ERR_VALIDATION` for supplying an undeclared `status` field, but the PRD nowhere states that unrecognised body fields are rejected; §2.7's payload-schema check names only required fields, types, enums and ranges. Ignoring the extra field is equally PRD-faithful. |
| `corner_create_chamber_client_supplied_id_input_ignored` | Non-unique-derivability — §2.4 says the id has "no client control over its value", which mandates ignoring a supplied `id`, not rejecting the request with `ERR_VALIDATION`. |
| `corner_pagination_limit_above_maximum_rejected` | PRD-silence — §2.3 says `limit` "may not be larger than 100" but names no error for a violation, and §2.7's `ERR_VALIDATION` step is scoped to writes ("On every write..."). Clamping is as faithful as rejecting. |

## Verification performed

- Every one of the **259 PRD citations** survives a whitespace-normalised literal match against `workspace/PRD.md` (C1/C3).
- Every test docstring ends with exactly one `Design:` tag; all tags resolve to a real `name:` in the correct rule/section (C4). No untagged or dual-tagged tests.
- No `skip`/`skipif`/`xfail` anywhere; no "scaffold"/§1.x references in emitted code.
- `pytest --collect-only` collects all 136 tests cleanly; pyflakes clean; every `api_client.*` call and every `from test_helpers import` name resolves.

**Orchestrator verification**: `test_helpers/` 9 modules + `test_suite/` conftest + 17 test files; `pytest test_suite --collect-only` = 136 tests collected in 0.07s; `Design:` tag census across test_suite = 93 Corner + 42 Difficulty = 135 tagged functions (136th item is the parametrized duplicate).

## Step 7: Run tests and iterate — 2026-08-16T21:12:00.000Z

No stray processes. The task is complete.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps.
- Sweep 1: 132/136 in all 8 rounds — 4 deterministic failures (no flakiness; identical union across all rounds).
- Sweep 2 (after fixes): **136/136 in all 8 rounds, 0 failed / 0 errors / 0 skipped.**

**Tests deleted:** none. Every failure traced to a test-artifact defect under STEP 2, not to PRD silence or a unique-derivability collapse — each failing test's asserted rule was verbatim in PRD.md and uniquely determined.

**Fixes applied to `test_helpers/`**
- `test_helpers/fixtures.py` — `place_required_indicators()`: the default `prefix="D"` minted the same serial codes (`D-MIN-1`, `D-RT-1`, ...) on every call, so any test that walked two cycles through `build_cycle_scenario` hit `ERR_DUPLICATE_CODE` on the second scenario's indicator placement. PRD §2.7 step 6 makes `serial_code` unique across the whole facility, so the implementation was correct and the fixture was violating the precondition. Changed the default to a freshly minted per-call prefix (`itertools.count`); explicit-prefix callers are unaffected. This one fixture bug masqueraded as two independent implementation failures (`test_permit_allowance_rejects_an_excess_charge_and_accepts_an_exact_landing`, `test_emission_fee_rate_band_comes_from_the_post_charge_consumption`).

**Fixes applied to `test_suite/`**
- `test_01_records_and_identity.py::test_create_chamber_with_an_unrecognised_modality_is_rejected` — the call passed `modality` both positionally (`"ETO"`) and as a keyword (`"XRAY"`), so the test raised `TypeError` before ever issuing a request. Rewritten as `create_chamber_payload(permit["id"], "XRAY", chamber_code="CH-1")`, which now actually exercises the PRD §2.7 step-3 enum check.
- `test_06_listing_and_subresources.py::test_qualifications_list_filters_by_recipe_and_by_product` — the test's own setup (`setup_reference_data(qualify=False)`) already binds product 1 to `recipe_g` with a `PENDING` qualification, so filtering by `recipe_id` correctly returns 3 rows, not 2. Corrected the expected `total_count` and id set to include the setup's qualification. The `by_product` half (filtered on `status=QUALIFIED`) was already right and was left untouched.

**Fixes applied to `implementation/`:** none. No implementation defect was found; every PRD-required check in `workspace/implementation/` is intact, and no endpoint, field, side effect or seed data was added.

**Orchestrator verification**: independently parsed all 8 `workspace/implementation/results.{1..8}.json` — every round reports `passed=136 / total=136, failed=0, errors=0, skipped=0`.

## Step 8: Finalize PRD — 2026-08-16T21:16:00.000Z

## Result

`workspace/PRD_FINALIZED.md` created — **verbatim copy of PRD.md, zero edits.**

- **PRD.md**: 402 lines / 99,423 bytes
- **PRD_FINALIZED.md**: 402 lines / 99,423 bytes
- **Delta: 0 lines, 0.00%** (`diff` is empty)

### Per-item adjudication (all three items -> no edit)

**1. `test_helpers/fixtures.py::place_required_indicators()` duplicate serial prefix**
- Subject: `serial_code` uniqueness scope for `Indicator` creation.
- Impl paths enumerated: `routes/positions.py:45-84` (`place_indicator` — `V.req_string(body,"serial_code",1,32)` at :51, then `peek`-based MIN_DOSE zone check, then `fetch` 404, then the facility-wide scan `for existing in db.indicators.values(): if existing["serial_code"] == serial_code -> ERR_DUPLICATE_CODE` at :67-70); grepped `serial_code` across all of `implementation/` — the only other hit is `routes/cycles.py:456`, a message string in the dosimetry-close completeness check, not a uniqueness rule. No per-cycle, per-position, or per-recipe narrowing anywhere.
- Verdict: impl scans **all** indicators facility-wide, which is exactly what PRD §2.7 step 6 and §3.5 already state. The check's position in the impl (after payload schema, after the 404) also matches the §2.7 ordering (3 -> 4 -> 6). The fixture was violating a stated precondition by reusing `D-MIN-1` across scenarios; nothing was left open by the PRD. **No PRD silence, no mismatch -> no edit.**

**2. `test_01::test_create_chamber_with_an_unrecognised_modality_is_rejected` (Python `TypeError`)**
- Subject: enum validation of `modality` on chamber creation.
- Impl paths enumerated: `routes/reference.py:214-241` (`create_chamber`, `V.req_enum(body,"modality",MODALITIES)` at :219); plus every other `modality` consumer for consistency — recipe creation, the recipe/chamber modality-equality check at cycle scheduling, and the `contracted_modalities` membership check at load-position creation.
- Verdict: the test never issued a request (duplicate positional+keyword arg), so it exercised nothing. The rule it *meant* to test is verbatim PRD §2.7 step 3 plus §3.2, and the impl does precisely that. **Pure test bug -> no edit.**

**3. `test_06::test_qualifications_list_filters_by_recipe_and_by_product` (miscounted setup rows)**
- Subject: filter semantics of `GET /sterilization/qualifications`.
- Impl paths enumerated: `routes/reference.py:371-387` (`list_qualifications` — three independent, all-optional `and`-composed predicates on `product_id`, `recipe_id`, `status`, with **no** implicit status filter and no exclusion of `PENDING`); `routes/common.py:35-38` (`paginate` -> `by_seq`, matching §2.3's "sorted by `created_at` ascending"); `routes/reference.py:336-362` (`create_qualification`, which births rows in `PENDING`).
- Verdict: PRD §2.3 already determines that a `recipe_id`-only query returns rows of every status. The test simply forgot its own setup's `PENDING` row; 3 is the correct count. **Pure test bug -> no edit.**

### Notes
- No implementation fixes and no test deletions existed in `<step_7_diff>`, so there was no candidate site where impl could have pinned an open choice or diverged from PRD.
- Because zero edits were committed, the NO-NEW-MISMATCH rule had no wording to adjust — but the mandatory pre-edit enumeration was still performed for all three candidate subjects (logged above), and in each case it confirmed the existing PRD prose already describes every impl path touching that subject. Keeping the prose verbatim is the correct outcome.

**Orchestrator verification**: `diff PRD.md PRD_FINALIZED.md` returns empty — files byte-identical.

## Step 9: Complete PRD — 2026-08-16T21:28:00.000Z

`PRD_COMPLETED.md` is written. Exhaustive walk of all 16 impl modules (~2670 LOC), all 48 endpoints, 9 state machines, 10 calculations, 33 validations, both OCC rules and both conserved quantities.

**Source vs output:** `PRD_FINALIZED.md` 402 lines / 99,423 chars -> `PRD_COMPLETED.md` 402 lines / 107,876 chars (**+8,453 chars**, 30 lines touched, no lines added or removed — every edit is in-paragraph).

**Counts:** 27 ambiguity-pins, 5 mismatch-revisions (32 total).

**Changes**

- §2.2 — insert — ambiguity — defined `total_count` (pre-window) and `has_more` = `offset + len(page) < total_count` — `response.py:74`
- §2.3 — insert — ambiguity — bad/out-of-range `limit`/`offset` -> `ERR_VALIDATION` at screening step 3, ahead of path-id resolution — `validation.py:170-189`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion sequence (the frozen clock makes ties the norm); this is what "ascending `created_at` order" means throughout — `services/domain.py:38`
- §2.3 — insert — ambiguity — filter values are exact string matches, unrecognised members select no rows — `routes/lots.py:92-99`
- §2.4 — insert — ambiguity — clock set returns `200` with empty `data`; backwards moves allowed — `routes/misc.py:186-192`
- §2.7 step 3 — insert — ambiguity — added `position_index` ceiling and residual-ppm >= 0 to the range list; pinned that the three record-dependent schema checks *consult without resolving*, so an unknown id falls through to its own 404 — `routes/cycles.py:166-171`, `routes/positions.py:60,104`
- §2.7 step 5 — insert — ambiguity — multiple unresolvable body FKs resolve in the order enumerated (recipe before chamber, customer before product) — `routes/cycles.py:49-50`, `routes/lots.py:35-36`
- §2.7 step 6 — insert — ambiguity — **`permit_code` added** to the facility-unique list and to the checked-on-create list (`ERR_DUPLICATE_CODE`) — `routes/reference.py:154-157`
- §2.7 step 22 — revise — ambiguity — every non-`PENDING_AERATION` residual status (incl. `AERATING`/`RESIDUAL_PASS`/`RESIDUAL_FAIL`) yields `ERR_AERATION_NOT_APPLICABLE`, never `ERR_INVALID_STATE` — `routes/lots.py:181-183`
- §3.1 — insert — ambiguity — re-asserting a customer's current status is accepted and bumps neither `updated_at` nor `version` — `routes/reference.py:76-78`
- §3.1 — insert — ambiguity — `open_lot_count` is a fresh recount, and touches the customer row only when the value actually changes — `services/domain.py:142-152`
- §3.2 — **revise — mismatch** — dropped "provided the permit had been auto-suspended": no auto-suspend flag exists, so an abort credit restores an administratively suspended permit identically — `routes/cycles.py:412-414`
- §3.2 — insert — ambiguity — permit status pairs outside the declared four (incl. re-asserting current) -> `ERR_INVALID_STATE` — `routes/reference.py:192-194`
- §3.2 — insert — ambiguity — same for chamber status — `routes/reference.py:264-266`
- §3.3 — insert — ambiguity — several qualifications may bind one pair; earliest-created current one governs the check, cascades move all of them — `services/domain.py:168-183`
- §3.3 — insert — ambiguity — a revoking `CONDITIONAL_PASS` nulls only the qualification's `next_audit_due_at`; the audit row keeps `performed_at`+30d and `audit_interval_days` is 30 — `routes/reference.py:405-429`
- §3.3 — **revise — mismatch** — lazy `AUDIT_DUE` fires at load-position creation *and release*, and never on a plain read/list — `services/domain.py:175-183`, `routes/lots.py:134`
- §3.4 — insert — ambiguity — `raw_eto_charge_kg` is persisted and echoed as supplied on gamma/e-beam cycles, merely never used — `routes/cycles.py:112`
- §3.4 — insert — ambiguity — `occupancy_end_at` is a persisted, returned field, never recomputed — `routes/cycles.py:69,111`
- §3.5 — insert — ambiguity — `position_index` ceiling is `ERR_VALIDATION` at step 3, evaluated via the path cycle, so an unknown cycle still 404s — `routes/cycles.py:166-173`
- §3.5 — **revise — mismatch** — a `READY` cycle emptied by a removal lands in `PLANNED` in one move, not `READY -> LOADING` — `services/domain.py:211-219`
- §3.5 — insert — ambiguity — a lot in any other primary `status` is placed just as readily and keeps that status — `routes/cycles.py:236-237`
- §3.6 — insert — ambiguity — a gamma/e-beam start reads but never writes the permit row — `routes/cycles.py:331,348`
- §3.6 — insert — ambiguity — the abort credit is EtO-only; a running gamma abort leaves the permit row wholly untouched — `routes/cycles.py:406-415`
- §3.7 — insert — ambiguity — the cycle's state is never a precondition of a reading; readings in other states leave `status` alone — `routes/positions.py:141-150`
- §3.7 — insert — ambiguity — a re-read does **not** clear `dosimetry_closed_by_user_id` — `routes/positions.py:145-150`
- §3.8 — revise — ambiguity — aeration open refuses every non-`PENDING_AERATION` status with `ERR_AERATION_NOT_APPLICABLE` — `routes/lots.py:181-186`
- §3.8 — **revise — mismatch** — reordered: the settled-record (`ERR_RETEST_LIMIT_EXHAUSTED`) test precedes the timing (`ERR_AERATION_INCOMPLETE`) test — `routes/misc.py:34-40`
- §3.8 — insert — ambiguity — on exhaustion `variant_applied`/`required_hours`/`target_end_at` freeze and `last_failed_sample_at` is not restamped; the `REJECTED`/`RESIDUAL_FAIL`/`open_lot_count` half requires the lot to actually be in `QUARANTINE` — `routes/misc.py:73-81`
- §3.9 — insert — ambiguity — an adverse event is accepted against a lot in any `status` — `routes/lots.py:243-252`
- §3.9 — insert — ambiguity — an already-dispositioned event, or a subject lot whose status bars the disposition, -> `ERR_INVALID_STATE` — `routes/misc.py:98-107`
- §3.9 — revise — ambiguity — `DISMISS` rewrites the reason only when it is `QUARANTINE` **and** `ADVERSE_EVENT`; otherwise the lot row is untouched — `routes/misc.py:114-116`
- §4 table — **revise — mismatch** — adverse-event POST description no longer claims a released/quarantined-only gate — `routes/lots.py:243`

Both generator-flagged under-determinations are now explicitly pinned (`permit_code`/`ERR_DUPLICATE_CODE` in §2.7 step 6; `position_index` ceiling as a step-3 `ERR_VALIDATION` with peek semantics in §2.7 step 3 and §3.5). The single most consequential find beyond those was the §3.2 auto-suspend proviso — the implementation tracks no suspension provenance, so the PRD's restriction was factually wrong.

**Orchestrator verification**: PRD_COMPLETED.md is 402 lines / 107,876 chars vs source 402 lines / 99,423 chars; `diff` shows 60 changed lines (30 replaced pairs), confirming zero net line additions; heading set is byte-identical to the source (no new sections added). Step 9 touched only PRD_COMPLETED.md — `implementation/` and the test tree are unchanged since the green Step 7 sweep, so no re-run was required.

## Pipeline complete — 2026-08-16T21:30:00.000Z

All 9 steps finished. Final state: 136/136 tests passing across 8 independent parallel rounds; PRD_COMPLETED.md is the reconciled contract.
