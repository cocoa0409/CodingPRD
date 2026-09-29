# Worklog — task_2772_zoological_animal_transfer_species_survival_planning

## Step 1: Create task directory — 2026-09-04T19:17:24.304Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2772_zoological_animal_transfer_species_survival_planning` and its `workspace/` subdirectory. Index 2772 was pre-assigned by the invoker; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-04T20:41:00.000Z

Subagent summary (verbatim):

All three artifacts are complete and the linter is clean on the first pass.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2772_zoological_animal_transfer_species_survival_planning/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2772_zoological_animal_transfer_species_survival_planning/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2772_zoological_animal_transfer_species_survival_planning/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     42
  Calls scanned (§1.8+§1.9):  764

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml` — 3122 lines. `domain_name: zoological-transfer-ssp`, `api_prefix: "/"`. 12 entities, 11 state machines, 2 `concurrency_rules`, 15 calculations, 48 ordered validations (priority 10→90), 55 endpoints, 59 errors, 4 roles. `complexity_profile`: archetypes multi_party_negotiation / compliance_audit, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`, topology `flat`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2844 lines, single key `scaffold_difficulty_design`. 9 rule blocks / **22 instances**: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2124 lines, single key `scaffold_corner_design`. **82 instances over all nine guide sections — 42 with full `test_recipe`, 40 `excluded_because` stubs**: entities 11, state_machines 15, calculations 17, validations 9, endpoints 5, errors 15, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1.

Neither design key appears in `SCAFFOLD.yaml`; the scenario block is the supplied text verbatim minus the "harder than expert level" directive line, so nothing can leak that directive downstream into PRD.md.

## Verification beyond the linter

Scripted checks confirmed: every instance name unique across both files (zero collisions with the 22 §1.8 names); every stub cites a `difficulty_instance` that exists by name in the difficulty file and carries no `test_recipe`; every real recipe has exactly the four keys `setup / setup_api_calls / trigger / assert`; every `${var}` in every call is bound by an earlier `captures:`; forbidden concurrency vocabulary absent (the only regex hit was "grace window"). `claim_type` values were normalised to the snake_case form the SKILL §1.9 example uses (`invalid_transition`, `violation_to_error`, …), each mapping 1:1 onto a claim-extraction-guide row.

## Design adjudications made while authoring §1.9

- **RBAC-denial and required-field corners are emittable.** `scaffold_lint.py`'s `is_negative_trigger` exempts checks (b) role-allowed and (c) payload-subset when the instance name matches its negative pattern, so the four `*_cannot_*` instances (Registrar→POST /species-programs, ProgramCoordinator→endorse, cross-institution accession, collecting vet signing the CVI) and the missing-`sex` / bad-enum instances lint clean while still being genuine 403/400 probes.
- **Both `concurrency_rules` entries were unexercised by §1.8** (no `ERR_STALE_*` anywhere in the difficulty file), so §1.9 carries both OCC tests as real recipes: `stale_expected_subject_animal_version_is_rejected_412` (a crate-training session invalidates the accession-time version) and `stale_expected_transfer_agreement_version_is_rejected_412` (the accept-time version is stale once execute bumps the agreement), each followed by a succeeding retry with the re-read version.
- **`ERR_UNAUTHENTICATED` is triggered with `as_user_id: ""`** rather than by omitting the key, because §1.8 already uses bare `as: AccreditationAdmin` for the opaque role — an omitted `as_user_id` cannot mean "no header" in one place and "harness-chosen header" in another.
- **New literals computed for this file** (all inside the §1.9 recipes, no §1.8 overlap): the late-studbook path `reporting_period_end 2026-06-01 → deadline 2026-07-01 → days_late 31 → base_points 15.50 → tier 0.40 → surcharge 6.20 → total 21.70`, which crosses `ACCREDITATION_REVIEW_POINTS 21.00` and demotes ACCREDITED → PROVISIONAL at review time (the `rate_threshold_triggers` layer, otherwise untested); and the on-time counterpart `2026-07-15 → deadline 2026-08-14 → 0 days late → 0.00 points`, whose ACCEPT posts nothing.
- **`transfer_scope_derivation` gets a real corner** with two US-CA institutions yielding `INTRA_JURISDICTION` (empty document/test panel), because every §1.8 instance uses the INTERSTATE pair.
- **Three high-value validations that §1.8 never reaches are real recipes**, not stubs: `ERR_DISPOSITION_POLICY_MISSING` (priority 60, conditional on `ownership_disposition == OWNERSHIP_TRANSFER`, and demonstrably not part of the accept gate), `ERR_HOLDING_CAPACITY_EXCEEDED` (priority 90, receiver capacity 1 already filled), and `ERR_SEGREGATION_OF_DUTIES` (priority 38, one vet collecting the TB test and signing the CVI — ahead of the licence-60 and panel-65 checks the request would otherwise pass).
- **`PROPOSED → SUPERSEDED` and `PROPOSED → EXPIRED` are both covered as real state-machine corners.** The expiry case pins the counter-intuitive contract that a 422 still commits its side effects (status EXPIRED persisted, `pending_recommendation_id` cleared, and the program flipping to CYCLE_CLOSED because the last open recommendation left the set).
- **Stub citations were checked against the difficulty file's actual asserts.** I dropped two planned rows rather than cite loosely: a `parallel` state-shape row (the declared shape is `cyclic`, so the guide row does not apply) and the `ERR_CRATE_TRAINING_INCOMPLETE` / `ERR_CRATE_TRAINING_STALE` pair — §1.8 only asserts those two ids are *not* returned, so no honest `excluded_because` exists and no cheap real recipe does either. **These two error ids are the only ones in the 59-error catalog with neither a §1.8 nor a §1.9 trigger**; if full catalog coverage is required, a follow-up corner needs a full journey to `POST /shipment-bookings/{id}/confirm` with fewer than `MIN_CRATE_SESSIONS` sessions and with a session older than `CRATE_RECENCY_DAYS`.
- Two §1.8 booking facts constrained several recipes and are worth remembering downstream: `POST /shipment-bookings` aborts any RESERVED sibling booking of the same agreement, and a quarantine `fail` terminates the parent agreement — so multi-booking and multi-occupancy corners must spread across separate EXECUTED agreements.

Orchestrator verification: all three files present and YAML-parseable; `SCAFFOLD.yaml` top-level keys contain neither `scaffold_difficulty_design` nor `scaffold_corner_design`; grep for "harder than expert"/"expert level" in `SCAFFOLD.yaml` returned nothing, so the difficulty directive did not leak. `workspace/` survived the scaffold step intact.

## Step 3: Copy shared files — 2026-09-04T20:43:29.861Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T21:02:00.000Z

Subagent summary (verbatim):

PRD generation is complete.

## Output
`workspace/PRD.md` — **485 lines, ~14,400 words**, ending at a real section boundary: the final row of the `## 5. Error Code Catalogue` table (`| \`ERR_ANIMAL_NOT_HELD_BY_SENDER\` | 422 |`). No PASS report, contract note, or scaffold reference was written into PRD.md or any sibling file; the only other file in `workspace/` is the pre-existing `INSTRUCTION.md`.

## Sections written
- `## 1. Introduction` (3 paragraphs, domain framing).
- `## 2.` with nine subsections: 2.1 Acting Identities and RBAC; **2.2 API Response Structure (copied byte-for-byte from `section-2.2-response-structure.md`)**; 2.3 Pagination; 2.4 Resource Identity, Audit Fields and the Logical Clock; 2.5 Path Resolution and Referential Validation Order; 2.6 Numeric Precision and Rounding; 2.7 Optimistic Concurrency on Supersede-Bearing Writes; 2.8 Cascade Integrity and Compensation Discipline; 2.9 Rejection Precedence (16-rung ladder placing all 59 error ids).
- `## 3.` with nine subsections (3.1 institutional register + plan cycle; 3.2 accessioning; 3.3 genetic/demographic analysis; 3.4 endorsement and designations; 3.5 negotiation; 3.6 execution cascade; 3.7 testing/paperwork/crating/transport; 3.8 quarantine and introduction; 3.9 termination, studbook filing, surplus disposition).
- `## 4. Endpoint Definitions` — intro paragraph on 201-vs-200 and role semantics, plus a 4-column table with all **55** endpoints.
- `## 5. Error Code Catalogue` — 2-column table with all **59** error ids and statuses.

## Coverage counts (grep-verified against SCAFFOLD.yaml)
12 entities · 117 entity field names · 103 distinct endpoint input/query identifiers · 12 path params · 55 endpoints · 59 errors · 48 validations across 26 priority rungs · 11 state machines / **65 transitions** · 15 calculations (incl. the 2-variant `transfer_credit_valuation` and 2-variant `kinship_and_pairing_verdict`) · 2 OCC rules · 4 roles · 98 enum/state values · 36 named constants.

## Hard Contract results
**Contract 1 — Field-Name Coverage: PASS.** Programmatic diff of all 117 `entities[].fields[].name`, all 103 endpoint `input` identifiers (with `?` stripped), and all 12 `path_params` against every backtick-delimited token in PRD.md (fenced code blocks excluded from token pairing, JSON keys inside §2.2 counted): **0 missing in all three sets.** Path params appear verbatim inside the backticked full paths of §4 (each `{...}` token 1–7 occurrences).

**Contract 2 — Rule Coverage: PASS.** All 26 validation priorities appear in the §2.9 ladder; all 59 error ids appear in the PRD (the 17 generic auth/schema/not-found/OCC ids live in §2.1, §2.5, §2.7 and §2.9 by design, the other 42 in §3 prose at their point of use). All 98 enum and state values appear verbatim. All 36 constants' numeric values appear as literals except `MOLECULAR_WEIGHT = 0.40`, which is intentionally rendered in prose ("four tenths of that percentage … plus six tenths of the pedigree coefficient") per the no-symbolic-expression rule, and remains reconstructible. Both concurrency rules, both `analysis_mode` variants, both `transfer_credit_valuation` variants (provisional and final), all cross-entity cascades (four-link execute cascade, four-link introduction-abort cascade, full EXECUTED-termination compensation chain, quarantine-failure chain), all field-level defaults, and sibling-branch symmetry (ACCEPT/REJECT posting identically; offer/counter turn symmetry) are documented.

**Contract 3 — §3 Path Purity: PASS.** 1,088 backticked tokens (299 distinct) in §3 scanned: **0** start with `/`, **0** are a bare HTTP method, **0** combine method+path. §1–§2 also carry no `/`-leading tokens; endpoint paths appear only in §2.4 (the logical-clock setter, deliberately named) and the §4 table.

## Adjudications (scaffold gaps or internal conflicts resolved)
1. **`MAX_NEGOTIATION_ROUNDS` is referenced 6 times but never defined.** Adjudicated to **6**; PRD states at most six offer-or-counter actions in total, with `ERR_NEGOTIATION_ROUND_LIMIT` (422) once `round_number` has reached six.
2. **Compliance-points posting timing conflict.** The `Institution` state machine says the ACCREDITED→PROVISIONAL threshold demotion fires "at the end of `POST /studbook-submissions`", while the submission endpoint, and both `StudbookSubmission` transitions, put posting and demotion at **review**. Followed the three-to-one majority: nothing is posted at filing; both review outcomes post `total_compliance_points` and can demote. PRD states this explicitly ("which is why the demotion below fires at review time rather than at filing time").
3. **Non-`BREED_WITH` kinship fields.** Entity table says `kinship_coefficient` / `projected_offspring_inbreeding` are null; the formula comment says "both coefficients are 0.0000". Reconciled: the record shows null, but `demographic_need_index` reads the coefficient as 0.0000, so `kinship_relief` is 1.0.
4. **Initial-value conflicts resolved by one uniform rule — the entity table's declared `default:` wins over endpoint `side_effects` phrasing.** Applied to `temperature_samples` (null, not `[]`) and to `isolation_class` / `required_days` (`STANDARD` / 30 at booking, re-derived at delivery).
5. **Endorse-endpoint ownership check has no error id** → assigned `ERR_ACTOR_SCOPE_VIOLATION` (403).
6. **"Wrong side of the agreement" checks** (opening offer by the receiver; execute/confirm/depart by a non-sender; deliver by a non-receiver) have no explicit id → assigned `ERR_NOT_A_PARTY_TO_AGREEMENT` (403), justified because every one of those endpoints is in that error's own `applies_to` list.
7. **Three §3.9 checks fall outside their error's `applies_to` list** (`ERR_ANIMAL_LOCATION_CONFLICT` on terminate; `ERR_DISPOSITION_POLICY_MISSING` and `ERR_ANIMAL_HAS_ACTIVE_AGREEMENT` on disposition). Named the semantically exact code in each case rather than inventing new ids or dropping the precondition.
8. **`ERR_HEALTH_CERTIFICATE_MISSING` at confirm** is stated for all scopes, while the empty `INTRA_JURISDICTION` document panel governs only the permit gate (`ERR_PERMIT_NOT_ISSUED`) — this reconciles two otherwise contradictory scaffold statements.
9. **Publishing an already-`PUBLISHED` plan** names no error id anywhere in the scaffold. Left deliberately unspecified: only `DRAFT` and `CYCLE_CLOSED` are documented as legal source states. Flagged as a documented gap rather than an invented code.
10. **Corrected one self-introduced id.** The §4 intro initially said `ERR_ROLE_NOT_PERMITTED`; the scaffold's role-rejection id is `ERR_UNAUTHORIZED`, and the text was fixed (0 occurrences remain).
11. **Stale scaffold self-description ignored.** The `difficulty_level` comment claims "12 entities / 55 endpoints / 44 error codes / 10 state machines / 8 calculations with 6 variants"; the grep-verified reality is 59 errors, 11 state machines and 15 calculations, and the real counts were used. No difficulty directive was found leaking into the `scenario` key.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read.

Orchestrator truncation check (per the known doc-generator failure mode): `wc -l` = 485; heading list runs §1 → §5 with all nine §2 and nine §3 subsections present; `tail -12` shows twelve complete, well-formed error-catalogue table rows ending with `| ERR_ANIMAL_NOT_HELD_BY_SENDER | 422 |` — a real section boundary, not mid-sentence. Grep for "harder than expert" / "expert level" / "scaffold" in PRD.md returned nothing. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T21:50:00.000Z

Orchestrator note on sequencing: Steps 5 and 6 were meant to launch in one assistant message so the implementation generator would be physically unable to see `test_suite/`. I launched Step 5 alone by mistake. Rather than accept the lost isolation, before spawning Step 6 I moved `test_helpers/` and `test_suite/` out of the task tree to `/tmp/task2772_tests_hold/`, ran Step 6 against a tree containing no test directory at all, and moved both back afterwards (verified present at the task root, 20 files in `test_suite/`, nothing stray under `workspace/`). The isolation guarantee is therefore preserved in substance: the impl generator's filesystem never contained the tests.

Subagent summary (verbatim):

Suite is complete and verified.

## Files written

**`test_helpers/` (9 modules, 2,182 lines total)**

| file | lines |
|---|---|
| `__init__.py` | 16 |
| `api_client.py` | 346 |
| `api_errors.py` | 128 |
| `assertions.py` | 163 |
| `constants.py` | 170 |
| `factories.py` | 392 |
| `fixtures.py` | 839 |
| `test_users.py` | 85 |
| `types.py` | 43 |

**`test_suite/` (conftest + 19 test modules, 3,479 lines, 126 tests)**

`conftest.py` 23 · `test_01` 331/10 · `test_02` 173/8 · `test_03` 128/5 · `test_04` 191/7 · `test_05` 129/5 · `test_06` 221/8 · `test_07` 175/7 · `test_08` 183/7 · `test_09` 192/7 · `test_10` 254/7 · `test_11` 166/6 · `test_12` 314/12 · `test_13` 294/10 · `test_14` 125/3 · `test_15` 172/5 · `test_16` 134/3 · `test_17` 113/4 · `test_18` 126/4 · `test_19_cross_cutting_corners.py` 258/8 (written last: both OCC-token instances, the compliance-points demotion at the exact 21.00 boundary, and the immediate-derived-read instance).

## Coverage

- **Queue A (depth index): 77 tests / 22 instances — all 22 translated, every one with >=2 tests.** Files `test_01`-`test_11`.
- **Queue B (breadth index): 49 tests / 42 instances — all 42 non-stub instances translated, >=1 test each.** Files `test_12`-`test_19`.
- **Skipped: none of the eligible instances.** No instance failed the PRD-first filter. The 41 `excluded_because:` corner stubs were correctly not translated (verified programmatically that no `Design:` tag names a stub, including `four_link_cascade_runs_end_to_end` and `both_credit_variants_produce_their_own_result`).

## Verification run

- Tag audit: 126 `Design:` lines vs 126 `def test_` definitions, file by file — exactly one tag per test, no untagged or dual-tagged test; every `<section>/<instance>` pair resolves to a real `name:` in its source yaml; no non-stub instance left untranslated in either index.
- Citation audit: every `PRD: "..."` quotation in all 19 files was matched, whitespace-normalised, against `workspace/PRD.md` — **0 misses**.
- `python3 -m compileall -q test_helpers test_suite` clean; per-file `py_compile` clean.
- No `skip`/`xfail`, no mention of "scaffold" or design-section refs anywhere in either directory.
- `workspace/` untouched: it still contains only `INSTRUCTION.md` and `PRD.md` (both with mtimes predating my first write); no stray `test_helpers/` or `test_suite/` under it; `worklog.md` not touched.

## Index-vs-PRD adjudications (PRD always won)

`ERR_PROGRAM_PLAN_NOT_PUBLISHED` 409 and `ERR_RECOMMENDATION_NOT_ENDORSED` 409 (index said 422); negotiation cap at six actions (index said four); `offspring_disposition_rule` `FIRST_TO_SENDER` replacing the non-PRD `SENDER_RETAINS`; new-booking `thermal_excursion_minutes == 0` (index said null); `quarantine_room_code` as the field name. Statuses are enforced automatically because `test_helpers/api_errors.py` registers the full 59-entry PRD status map with `set_error_http_status_map`, so `validate_error` cross-checks each one.

One deliberate restraint in `test_19`: the consistency-model recipe asserts the crate-session POST response body itself reports the recomputed counters, but the PRD never fixes that endpoint's response shape, so those assertions read the animal on the immediately following request instead — which is what the PRD does uniquely derive.

## Step 6: Generate implementation — 2026-09-04T22:31:00.000Z

Subagent summary (verbatim):

Implementation is complete, compiles cleanly, and all smoke servers are shut down (killed by specific PID/port; no pattern kills used).

## Modules written (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | executable, `set -euo pipefail`, `cd $(dirname $0)`, guarded `if ! python3 -c "import flask"` install, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 49 | blueprint registration (13 modules), `ApiError`/`HTTPException`/`Exception` handlers, `app.run(host="0.0.0.0", port=$PORT or 10000, threaded=True)` |
| `core.py` | 452 | envelope (`meta`/`response_type`/`data`, `req_`+20 uppercase alnum, 3-digit-fraction UTC), auth (`X-User-ID`/`X-User-Role`), logical clock (default `2026-08-01T00:00:00Z`), typed body/query getters, `Decimal` ROUND_HALF_UP helpers, pagination (`limit` 10/1-100, `offset` 0, `total_count`, `has_more`) |
| `db.py` | 121 | in-memory dicts keyed by UUID; `insert`/`touch` (`created_at`/`updated_at`/`version`), 404 lookups. Starts empty — no seeding anywhere |
| `calc.py` | 247 | 14 calculations + all constants (kinship classes, molecular 0.4/0.6 blend, demographic index, 3-component credit valuation with per-component rounding, thermal penalty, lateness cap-then-multiplier, quarantine/sanitation/crate/carrier constants) |
| `services.py` | 499 | serializers, slot recomputation, credit ledger posting, program roll-up (PUBLISHED <-> CYCLE_CLOSED), termination compensation, cascade helpers, `party_check`, `valuation`, `as_date`/`as_instant` |
| `routes/` | 1,514 | `recommendations` 214, `agreements` 252, `bookings` 222, `quarantine` 174, `documents` 168, `introductions` 158, `animals` 142, `submissions` 117, `tests` 82, `institutions` 78, `programs` 68, `veterinarians` 61, `clock` 14 |

Total 3,118 lines; `python3 -m compileall -q .` clean; `__pycache__` removed.

## Endpoints — 55 implemented
Institutions 4 (create/patch/get/list); species programs 4 (+`publish-plan`); veterinarians 3; animals 5 (create, crate-training-sessions, disposition, get, list); population recommendations 4 (create, endorse, get, list); transfer agreements 8 (create, offer, counter, accept, execute, terminate, get, list); compliance documents 4 (create, decision, get, list); pre-shipment tests 3; quarantine occupancies 5 (create, clear, fail, get, list); shipment bookings 6 (create, confirm, depart, deliver, get, list); introduction protocols 4 (create, observations, get, list); studbook submissions 4 (create, review, get, list); `POST /_clock/set_current_utc`.

## Verification this session
Fresh-boot servers on ports 10817-10820 (each killed by its own PID). Three full end-to-end chains — institutions -> program -> animals -> BREED_WITH recommendation -> agreement offer/accept -> TB test -> CVI issue -> execute -> 5 crate sessions -> quarantine schedule -> book/confirm/depart/deliver -> quarantine clear -> introduction protocol — passed every assertion, exercising the previously untested paths:
- regression ladder: single SEVERE (5 pts) holds; 5+2=7 regresses to HOWDY (count 1); 3xMINOR=6 regresses again (count 2); third regression **aborts** with `regression_count` left at 2.
- HOWDY special case: accumulator 10 aborts outright with `regression_count` still 0.
- four-link abort cascade: animal HELD + HOLD_NO_BREED, open `PROPOSED` BREED_WITH naming the animal as *pair* -> DECLINED with the pair-subject's `pending_recommendation_id` cleared, `open_recommendation_count` -> 0, program -> CYCLE_CLOSED with the clock **instant** stamped; the FULFILLED founding directive untouched; agreement stays EXECUTED.
- advancement: 3 CALM per stage climbs HOWDY->PARTIAL->FULL; a MINOR then two CALM integrates; animal HELD at receiver with designation untouched, agreement -> COMPLETED, ledger still sums to 0.00.
- verified computed values against PRD worked examples (`demographic_need_index` 0.5745 -> `genetic_value_score` 57.45; CVI window exam_date+30; STANDARD 30-day quarantine on a zero-excursion delivery).

## Ambiguities resolved (this session's decisions)
1. **Abort link 2 designation** — PRD/scaffold phrase it as `BREED_RECOMMENDED -> HOLD_NO_BREED`, but §3.8 insists "every link fires whichever of the three abort paths was taken" and the scaffold side-effect reads `genetic_designation := HOLD_NO_BREED`. Chose the **unconditional assignment**, so an abort of a TRANSFER_OUT-founded transfer also lands HOLD_NO_BREED.
2. **`cycle_closed_on` type** — scaffold pseudocode says "logical clock date", PRD §3.5 link 4 says "the logical clock **instant**" and the entity type is `datetime`. Rendered as a 3-fraction-digit **instant** (PRD wins).
3. **Numeric rendering** — "stored and returned with two decimal places" implemented as JSON **numbers** (`Decimal -> float`), not strings, so `57.45`/`0.5745` compare numerically; trailing-zero width is not representable in JSON numbers.
4. **Link 3 scope** — only recommendations still `PROPOSED`/`ENDORSED` are declined; a `FULFILLED` founding directive is deliberately left alone (confirmed by test).
5. Earlier-session resolutions retained: document-decision gate split (authority + vet/institution mismatch on both outcomes; segregation, licence/jurisdiction, CATEGORY_II and panel gates on ISSUE only), turn-taking as "`last_action_institution_id` is not None and equals the actor", DRAFT-stage opener restricted to the sending side (`ERR_NOT_A_PARTY_TO_AGREEMENT`), §2.9 ladder order preferred where §3 prose disagreed, quarantine room availability half-open vs carrier overlap closed (separate implementations, per the PRD's explicit warning).

## Step 7: Run tests and iterate — 2026-09-04T22:56:00.000Z

Subagent summary (verbatim):

Green. Two iterations, exit clean.

## Summary

**Iterations run: 2.**

- **Iteration 1** — 8-round `setsid nohup` sweep: all 8 rounds **123/126**, union of failures exactly **3** tests, each failing in all 8 rounds (deterministic, not load-induced, not flaky).
- **Iteration 2** — after the three fixes below, 8-round sweep: **126/126 in all 8 rounds**, union of failures **0**.

### Tests deleted
None. No test was deleted, skipped, xfailed, or had a PRD-backed assertion weakened.

### Assertions removed (PRD-silence)
`test_suite/test_13_state_machine_transitions.py` — `TestAgreementInitialState::test_a_founded_agreement_opens_in_draft_with_no_negotiation_history`, single clause `assert data["delivered_at"] is None` removed (failure was `KeyError: 'delivered_at'`).
Category: **FIELD-EXISTENCE / DEFAULT-VALUE SILENCE**. PRD attributes `delivered_at` exclusively to `ShipmentBooking` (§3.7: "A new booking opens with `status` at `RESERVED` ... and `departed_at` and `delivered_at` null"; "Delivery also stamps `status` as `DELIVERED` and `delivered_at` from the logical clock"). The `TransferAgreement` opening-state sentence in §3.5 enumerates `status`, `round_number`, `last_action_institution_id`, `provisional_credit_points`, `final_credit_points` and nowhere gives the agreement a `delivered_at` field. Adding it to `agreement_out` would have been an untraceable response field, so the un-derivable clause went instead; every remaining assertion in the test (including `executed_at is None`, backed by §3.6 "`executed_at` is stamped from the logical clock" at execution) is verbatim-covered and the test still exercises its stated rule.

### Fixes to `test_helpers/`
`test_helpers/factories.py` — `sender_institution_payload`, `receiver_institution_payload`, `outsider_institution_payload`. They forwarded `name=`/`jurisdiction_code=` positionally *and* splatted `**overrides`, so any caller overriding either key raised `TypeError: institution_payload() got multiple values for keyword argument 'name'` — which is exactly what `fx.base_pair(api, receiver_overrides={"name": "Bayside Aquarium", "jurisdiction_code": "US-CA"})` does in `test_14_calculation_corners.py::TestScopeDerivation::test_two_same_state_parties_produce_an_intra_jurisdiction_agreement`. Each wrapper now builds its default payload first and then applies overrides through `_merge`, which preserves the existing "an override of `None` removes the key" contract used by the schema-validation tests. Pure helper bug; no fixture precondition changed, no implementation behaviour involved.

### Fixes to `implementation/`
`workspace/implementation/routes/quarantine.py` — `create_occupancy`: `services.party_check(agreement, actor(), "receiving_institution_id")` -> `services.party_check(agreement, actor())`.

The side-restricted form rejected the sending institution's own registrar reserving a room in its own quarantine building with `ERR_NOT_A_PARTY_TO_AGREEMENT` (403 instead of 201), breaking `test_10_resource_temporal_overlap.py::TestQuarantineRoomWindow::test_the_occupied_resource_is_the_institution_and_room_pair`. The stranger check that PRD §2.1 does state ("When a registrar acts on a transfer agreement to which its institution is neither the sending nor the receiving party ... `ERR_NOT_A_PARTY_TO_AGREEMENT`") is retained; only the unstated side restriction was dropped. PRD support for dropping it:

- §3.8 reservation prose names the inputs (`institution_id`, `transfer_agreement_id`, `animal_id`, `quarantine_room_code`, the two dates) and the interval/uniqueness rules, but names **no** error for the reserving institution or actor. Contrast the immediately following introduction-protocol paragraph, which *does* spell out "the `institution_id` running the protocol — which must equal the registrar's own `X-User-ID`". The asymmetry is deliberate.
- §3.7's confirmation gate reads "a `SCHEDULED` quarantine occupancy waiting **at the receiving institution** for this agreement (`ERR_QUARANTINE_NOT_SCHEDULED`)". That qualifier is only meaningful if occupancies of an agreement can exist at an institution other than the receiver; the receiving-institution constraint lives at confirmation, not at creation. `routes/bookings.py` already filters that gate by `agreement["receiving_institution_id"]`, so the relaxation does not let a sender-side room satisfy confirmation.
- §3.8's asserted rule — "The occupied resource is the pair of institution and room code, not the room code alone, so two institutions may both operate a room called 'Q3'" — is verbatim and uniquely derivable, so the test is fair and was not a deletion candidate.

No other implementation file was touched. No entity data is seeded at startup; storage remains in-memory dicts only. `worklog.md` was not read, written, or modified, and `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened. No broad pattern kill was ever issued; both sweeps ran to completion untouched under `setsid`.

**Final state: `results.1.json` ... `results.8.json` all report 126 passed / 126 total.**

Orchestrator verification of the sweep artifacts (not taken on trust): all 8 `workspace/implementation/results.$i.json` files exist, ~43 KB each, mtime 22:56, and parse to `passed=126 / total=126 / failed=0` in every round. Step 7 made 1 `implementation/` fix, 1 `test_helpers/` fix and 1 assertion removal, so Step 8 does NOT meet the skip condition and will run.


_Orchestrator note: the Step 8 entry and the Step 9 plan below were originally appended into `workspace/worklog.md` because the Bash working directory had drifted into `workspace/` from a previous verification call. They are spliced back into their correct position here verbatim and the stray file was removed; no entry was lost or overwritten._


## Step 8: Finalize PRD — 2026-09-04T23:10:00.000Z

Subagent summary (verbatim):

`PRD_FINALIZED.md` written. Two lines revised, both tracing to the single implementation fix in `<step_7_diff>`.

## Line counts
- `PRD.md`: 485 lines; `PRD_FINALIZED.md`: 485 lines; **0.0% delta** (2 lines revised in place, 0 added/removed).

## Changes
- **§3.8 "Reserving the room"** — revise — the reserving actor is no longer described as "the receiving institution's registrar"; the paragraph now states that either party's registrar may reserve, that the acting `X-User-ID` must be one of the agreement's two institutions (`ERR_NOT_A_PARTY_TO_AGREEMENT`), that the named `institution_id` need equal neither the actor nor `receiving_institution_id`, and that the receiving-institution requirement is imposed by the §3.7 confirmation gate alone — `implementation/routes/quarantine.py:38-47` (`db.get_institution` existence only, then `services.party_check(agreement, actor())` with no `side`), `implementation/services.py:480-487`.
- **§4 endpoint table, `POST /quarantine-occupancies`** — revise — dropped "at the receiving institution" from the description and noted either party's registrar may reserve, so the table no longer re-asserts the side restriction §3.8 now explicitly disclaims — `implementation/routes/quarantine.py:47`.

## Items that needed no PRD edit
- **`delivered_at` assertion removal** (`test_13`). Verified `services.agreement_out` (`implementation/services.py:202-224`) returns no `delivered_at`; `delivered_at` exists only on bookings (`routes/bookings.py:70`, `165`). PRD §3.5's opening-state sentence already enumerates the agreement's opening fields without it and §3.7 already attributes `delivered_at` exclusively to `ShipmentBooking`. PRD is already correct — adding anything would have invented a field the impl does not expose.
- **`test_helpers/factories.py` wrapper fix.** Pure fixture bug (positional `name=`/`jurisdiction_code=` plus `**overrides`); no implementation behavior and no PRD statement is involved.

## Per-edit pre-edit search log

**Edit 1 — §3.8 reservation actor/institution constraint**
- (a) Subject: who may create a `QuarantineOccupancy`, and what the `institution_id` field is constrained to be relative to the actor and to the agreement's two parties.
- (b) Enumerated and read/grepped: `grep -n "party_check" -r implementation` -> all 11 sites. Read `services.py:480-487` (`party_check`, optional `side`); `routes/quarantine.py` in full — `create_occupancy` (existence-only check on `institution_id`, `party_check` with no side, room-conflict loop), `clear_occupancy`/`fail_occupancy` (both gate on `vet["institution_id"] == occ["institution_id"]`, not on the agreement side); `routes/bookings.py` in full — `create_booking` (`party_check` no side), `confirm_booking` (`party_check` side `sending_institution_id`; the `ERR_QUARANTINE_NOT_SCHEDULED` gate filters `o["institution_id"] == agreement["receiving_institution_id"]` at line 111-115), `depart_booking` (sender side), `deliver_booking` (receiver side; activation loop at 187-198 iterates **all** `SCHEDULED` occupancies of the agreement with no institution filter); `routes/introductions.py:24-45` (`create_protocol` does enforce `actor() != institution_id -> ERR_ACTOR_SCOPE_VIOLATION`, and its `CLEARED` gate uses `occupancies_of` with no institution filter); `services.py:359-361` (`occupancies_of`), `services.py:392-396` (`cancel_scheduled_occupancies`, no institution filter), `services.py:433` (termination cascade callsite).
- (c) Wording adjustments made to stay consistent with all of those: scoped the receiver requirement to the confirmation gate only ("imposed by the confirmation gate of §3.7 alone") rather than saying occupancies away from the receiver are ignored generally — delivery activation, termination cancellation, and the introduction-protocol `CLEARED` gate all act on any occupancy of the agreement regardless of institution, so a broader claim would have been a new mismatch. Deliberately said nothing about `animal_id` (impl only checks existence, but that is outside the fix's trace) and nothing about clearance/failure actor rules (those remain vet-vs-occupancy-institution and are already stated correctly). Left the neighbouring introduction-protocol sentence — which does require `institution_id == X-User-ID` — untouched, since that asymmetry is real in the code.

**Edit 2 — §4 table row for `POST /quarantine-occupancies`**
- (a) Subject: the same reservation actor/institution constraint, as restated in the endpoint catalogue.
- (b) Enumerated: `routes/quarantine.py:25-47` (`@auth("Registrar")` decorator, so the authorized-role column stays `Registrar`); `implementation/core.py` `auth`/`actor` usage confirmed via the decorator on every quarantine route; re-checked `routes/bookings.py:111-115` to confirm the receiver requirement genuinely lives at confirmation and thus does not belong in this row.
- (c) Removed only the false locative phrase "at the receiving institution" and added the actor clause; kept the `Registrar` role column verbatim since `@auth("Registrar")` is unchanged.

Orchestrator verification: `PRD_FINALIZED.md` is 485 lines (same as PRD.md); `diff` shows exactly two changed lines (§3.8 reservation paragraph, §4 quarantine-occupancy table row), both tracing to the Step 7 `routes/quarantine.py` fix; file ends at the last error-catalogue row, not truncated.

## Step 9 plan — 2026-09-04T23:12:00.000Z

Step 9 is run as three sequential, module-partitioned passes over one shared `PRD_COMPLETED.md`, rather than a single subagent, because a whole-implementation scan in one context reliably runs out of room and returns a byte-identical copy of its input. Pass 1 performs the `cp PRD_FINALIZED.md PRD_COMPLETED.md` and then scans the foundation and simple-resource modules; passes 2 and 3 edit the same file in place and are explicitly forbidden from re-copying. Partition:
- Pass 1: `core.py`, `db.py`, `app.py`, `calc.py`, `routes/institutions.py`, `routes/programs.py`, `routes/veterinarians.py`, `routes/animals.py`, `routes/clock.py`
- Pass 2: `services.py`, `routes/recommendations.py`, `routes/agreements.py`
- Pass 3: `routes/bookings.py`, `routes/quarantine.py`, `routes/documents.py`, `routes/introductions.py`, `routes/submissions.py`, `routes/tests.py`

## Step 9: Complete PRD — 2026-09-04T23:55:00.000Z

Run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`, per the plan recorded above. Pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying and edited in place. Cumulative effect verified by the orchestrator between passes: 19 changed lines after pass 1, 33 after pass 2, 52 after pass 3 — so each pass's work survived the next.

### Pass 1 summary (verbatim) — core.py, db.py, app.py, calc.py, routes/{institutions,programs,veterinarians,animals,clock}.py

Pass 1 complete.

**Setup:** `cp PRD_FINALIZED.md PRD_COMPLETED.md` performed — 485 lines. All 19 patches were surgical in-paragraph Edits (line count still 485; no sections added, no rewrites), so passes 2 and 3 will find the file intact.

**Counts:** 17 ambiguity-pins, 2 mismatch-revisions.

- §2.1 — revise — ambiguity — a header holding only whitespace also yields `ERR_UNAUTHENTICATED` — core.py:213
- §2.2 (`api_request_id`) — insert — ambiguity — `req_` + exactly 20 upper-case alphanumerics — core.py:161-165
- §2.2 (`api_request_timestamp`) — insert — ambiguity — it is the only value read from real wall-clock time, unaffected by the logical clock — core.py:168-173
- §2.2 (`data` bullet) — insert — ambiguity — every optional `*_note` is validated non-empty then discarded, except document `decision_note` and submission `review_note` — programs.py:39, animals.py:94 (cross-checked agreements.py:134/159, bookings.py:80/130, quarantine.py:88, recommendations.py:133, documents.py:143, submissions.py:81)
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; an empty-valued query parameter counts as omitted — core.py:392-407, 411-415
- §2.3 (ordering) — insert — ambiguity — `created_at` ties are broken by creation order (the logical clock makes ties common) — core.py:451-452
- §2.3 (filters) — insert — ambiguity — an identifier-valued filter is not existence-checked and yields an empty page — institutions.py:74, animals.py:139
- §2.4 (audit fields) — insert — ambiguity — `created_at`/`updated_at` come from the logical clock — db.py:39-51
- §2.4 (`version`) — insert — mismatch — the increment unit is the request: a record rewritten several times by one request ends 1 higher, though `updated_at` refreshes each touch — db.py:47-60
- §2.4 (clock) — insert — ambiguity — the clock may run backwards, accepts `Z` or a numeric offset (normalised to UTC), answers 200 with empty `data` — clock.py:12-14, core.py:256-271
- §2.6 — revise — mismatch — only server-computed money/score quantities are rounded to 2 dp; client-supplied numbers are echoed exactly as submitted; all such figures are JSON numbers (28.00 renders `28.0`) — core.py:62-74, services.py:112-113/164
- §2.6 (integers) — insert — ambiguity — whole-number fields reject fractional/boolean/string values; number fields reject strings and booleans — core.py:309-337
- §2.9 rung 3 — insert — ambiguity — JSON `null` is treated exactly as absence (including for "must be null" rules); strings must be non-empty/non-whitespace — core.py:274-295
- §3.1 (jurisdiction) — insert — ambiguity — upper case only, digits allowed in the subdivision — core.py:235
- §3.1 (`accreditation_expires_on`) — insert — ambiguity — required but inert; no rule ever reads it — institutions.py:22 (grep-confirmed no other reader)
- §3.1 (PATCH) — insert — ambiguity — an adjustment supplying none of the four fields still bumps `updated_at`/`version` — institutions.py:49-57
- §3.1 (accreditation path) — revise — mismatch — the transition path is descriptive only; the endpoint validates only enum membership and permits any status from any other, including out of `TERMINATED`; no error id exists for an out-of-path move — institutions.py:43-50
- §3.1 (publish) — insert — ambiguity — publishing an already-`PUBLISHED` programme is an accepted no-op that leaves `current_plan_cycle` alone — programs.py:43-47
- §3.2 (pedigree) — insert — ambiguity — a sire/dam pointer is existence-checked only (no sex/programme/custody check) — animals.py:38-41
- §3.2 (`local_id`) — insert — ambiguity — uniqueness sweeps `DISPOSED` animals too; no plan-status or accreditation gate at accession — animals.py:35-48
- §3.7 (crate conditioning) — insert — ambiguity — `duration_minutes` is a number >= 0 that is discarded; holder mismatch is `ERR_ACTOR_SCOPE_VIOLATION`; no `location_status` or agreement gate — animals.py:73-85
- §3.9 (disposition) — insert/revise — ambiguity — `disposition_method` is required free text (not an enum) and discarded; gates are read actor -> custody -> active agreement -> policy flag -> surplus designation; no recommendation is touched — animals.py:93-114
- §4 preamble — insert — ambiguity — unknown path -> `ERR_INVALID_REQUEST` with HTTP 404, disallowed method -> HTTP 405, the two exceptions to §5's 400 — app.py:31-34

**No-change findings (impl already uniquely pinned by PRD):** every formula and constant in `calc.py` (kinship classes, molecular blend, verdict bands, demographic-need factor/weight/tier arithmetic and rounding order, credit valuation rounding order, thermal excursion, lateness cap-then-multiplier, transfer-scope derivation), `db.py` 404 identifiers and the `PreShipmentTest` audit-field exception, `ok_list` pagination meta and `has_more`, and the role tables in all five of my route modules.

**Final:** `wc -l PRD_COMPLETED.md` = 485.

### Pass 2 summary (verbatim) — services.py, routes/recommendations.py, routes/agreements.py

Pass 2 complete.

**File integrity:** I did **not** re-copy, recreate, or whole-file-rewrite `workspace/PRD_COMPLETED.md`. It was **485 lines** when I started (all 19 pass-1 edits present and re-verified intact afterwards), and every change was a surgical in-paragraph `Edit`. No new sections, no new paragraphs, no line-count change.

**Counts:** 15 changes — **9 ambiguity-pins, 6 mismatch-revisions**.

- §2.8 — revise — ambiguity — `open_recommendation_count` defined as *current-cycle-scoped* (PROPOSED/ENDORSED stamped with the programme's `current_plan_cycle`, earlier cycles never counted), and `cycle_closed_on` stamped as a full instant rather than a bare date — `services.py:43-47,78,130`
- §2.9 rung 16 — revise — mismatch — rung order was listed capacity-first; impl checks `ERR_ANIMAL_NOT_HELD_BY_SENDER` before `ERR_HOLDING_CAPACITY_EXCEEDED` (which really is the last gate) — `routes/agreements.py:184-188`
- §3.3 ¶1 — insert — ambiguity — the `subject_animal_id` need not belong to the named programme; nothing compares the animal's `species_program_id` to the recommendation's — `routes/recommendations.py:43-49`
- §3.3 ¶2 — revise — mismatch — an omitted `paired_animal_id` on `BREED_WITH` is `ERR_INVALID_PAIRING`, not a schema failure (unlike the two institution fields, which are `ERR_INVALID_REQUEST`); and the "no paired animal" rule covers `TRANSFER_OUT` too, not just `HOLD`/`SURPLUS_DISPOSITION` — `routes/recommendations.py:33-37,67-79`
- §3.3 molecular ¶ — revise — ambiguity — a `molecular_similarity_pct` supplied under `PEDIGREE_ONLY` is still bounds-validated 0.0-100.0 and is echoed back — `routes/recommendations.py:28`
- §3.4 expiry — revise — mismatch — the lapse clears `pending_recommendation_id` only where it pointed at *this* directive, and the programme roll-up runs before the request fails (so a cycle can close on a failed endorsement) — `routes/recommendations.py:147-154`
- §3.4 designations — insert — mismatch — no precondition guards the designation write; an endorsement overwrites whatever designation stood there (e.g. `HOLD_NO_BREED` -> `BREED_RECOMMENDED`), with no error identifier for an out-of-path move — `routes/recommendations.py:162-175`
- §3.5 ¶1 — revise — mismatch — PRD required `animal_id` to be the directive's subject; impl never compares them and no error exists for it. Also the directive's `recommendation_type` is not examined — `routes/agreements.py:43-64`
- §3.5 ¶1 — insert — ambiguity — a new agreement also opens with `executed_at` and `termination_reason` null — `routes/agreements.py:82-83`
- §3.5 turn-taking — revise — ambiguity — the sender-only test on a `DRAFT` agreement applies to *both* negotiation acts and sits at the actor-scope rung, so a receiver countering a `DRAFT` hears `ERR_NOT_A_PARTY_TO_AGREEMENT`, not `ERR_AGREEMENT_INVALID_STATE` — `routes/agreements.py:93-98`
- §3.6 ¶1 — insert — ambiguity — a receiving registrar executing hears `ERR_NOT_A_PARTY_TO_AGREEMENT` before any state read; a non-`ACCEPTED` status is `ERR_AGREEMENT_INVALID_STATE` — `routes/agreements.py:162-165`
- §3.6 close — insert — ambiguity — the founding recommendation's `version`, and the programme's when the cycle closes, also increment — `routes/agreements.py:204-206`, `services.py:79`
- §3.8 abort link 3 — revise — ambiguity — *every* animal whose `pending_recommendation_id` named a declined recommendation is cleared, including the mate that was the declined directive's own subject, not just the aborting animal — `services.py:456-463`
- §3.9 EXECUTED bullet — insert — ambiguity — documents voided on an `EXECUTED` termination also get `decision_note` set to `VOIDED_BY_TERMINATION` — `services.py:369-374,434`
- §3.3 filters — insert — ambiguity — the `plan_cycle` list filter must be a plain integer or `ERR_INVALID_REQUEST` (the system's only integer-valued filter) — `routes/recommendations.py:192-197`

**Considered and left alone** (PRD already pins uniquely, or the ladder settles it): serializer field sets for all twelve entities; `party_check` semantics; the acceptance-order listing (rung 8 before rung 9 already decides rec-vs-accreditation); `post_credit` direction and rounding; `abort_live_bookings`/`cancel_scheduled_occupancies`/`void_issued_certificates` filter sets; `valuation` inputs; negotiation term overwrite and round-cap arithmetic; the unused `skip_animal_location` argument (no behavioural effect).

**Final `wc -l`: 485** `workspace/PRD_COMPLETED.md`.

### Pass 3 summary (verbatim) — routes/{documents,tests,bookings,quarantine,introductions,submissions}.py + whole-file consistency read

Pass 3 complete.

## Confirmation

I did **not** re-copy or recreate `workspace/PRD_COMPLETED.md`. It was **485 lines** when I started (already carrying passes 1 and 2, 33 lines revised). Every change was a `Edit` in-paragraph patch. It is still 485 lines; no sections added or removed.

## Counts

- **6 mismatch revisions**, **16 ambiguity pins** (across 19 distinct lines), **1 cross-pass contradiction reconciled**.
- Cumulative across all three passes: **52 of 485 lines** now differ from `PRD_FINALIZED.md`.

## Changes

- §3.7 Pre-shipment testing — revise — mismatch — PRD claimed `animal_id` "must be the animal the agreement covers"; impl validates existence only and never compares — `routes/tests.py:27`
- §3.7 Pre-shipment testing — insert — ambiguity — a `collecting_veterinarian_id` != actor is `ERR_VET_INSTITUTION_MISMATCH`, ahead of the party test — `routes/tests.py:30`
- §3.7 Pre-shipment testing — revise — mismatch — prose read licence-then-agreement-status; impl gates `ERR_AGREEMENT_INVALID_STATE` first (per §2.9 rungs 8->9) — `routes/tests.py:38`
- §3.7 Opening a compliance document — insert — ambiguity — receiving registrar and outsider both hear `ERR_NOT_A_PARTY_TO_AGREEMENT` — `routes/documents.py:47`
- §3.7 Opening a compliance document — insert — ambiguity — non-`ACCEPTED`/`EXECUTED` agreement is `ERR_AGREEMENT_INVALID_STATE` — `routes/documents.py:49`
- §3.7 Deciding it (certificate conditions) — insert — ambiguity — only the employing-institution test is read on a `DENY`; segregation, licence, jurisdiction, USDA category and the panel are read only on `ISSUE` — `routes/documents.py:89,93,103`
- §3.7 Panel rejections — insert — ambiguity — the positive/inconclusive gate ignores collection freshness and ignores codes outside the required panel — `routes/documents.py:116`
- §3.7 Issue/deny outcome — insert — ambiguity — `decision_note` is recorded on `ISSUE` too, and `document_number` stays null when omitted — `routes/documents.py:133,143`
- §3.7 Issue/deny outcome — insert — ambiguity — a permit's `valid_until` stays null when the payload supplies none — `routes/documents.py:140`
- §3.7 Booking transport — insert — ambiguity — a non-party booker hears `ERR_NOT_A_PARTY_TO_AGREEMENT` — `routes/bookings.py:34`
- §3.7 Booking supersede — revise — ambiguity — the agreement's `version` bumps on **every** accepted create; the supersede runs **after** the carrier-capacity test, so the outgoing `RESERVED` booking still counts as live — `routes/bookings.py:42-57,72`
- §3.7 Confirming — insert — ambiguity — sending-registrar-only error id; booking status read before the six gates; the crate-recency gap is one-sided (a session on/after departure is never stale); any one still-valid `ISSUED` certificate satisfies the expiry gate — `routes/bookings.py:83,85,96,116`
- §3.7 Departure — insert — ambiguity — sending-registrar-only error id, and a non-`RESERVED` animal is `ERR_ANIMAL_LOCATION_CONFLICT` — `routes/bookings.py:133,138`
- §3.7 Arrival — insert — ambiguity — a sending registrar hears `ERR_NOT_A_PARTY_TO_AGREEMENT`; `temperature_samples` is required (omitted -> `ERR_INVALID_REQUEST`) but may be an empty array — `routes/bookings.py:153,156`
- §3.7 Delivery side effects — revise — cross-pass contradiction — said "the agreement's `SCHEDULED` quarantine occupancy" (singular) against my new §3.8 wording; both now say every `SCHEDULED` occupancy of the agreement — `routes/bookings.py:187`
- §3.8 Reserving the room — insert — ambiguity — the agreement's `status` is never read and `animal_id` is not compared to the agreement's animal (kept pass 1's either-party wording intact) — `routes/quarantine.py:38-47`
- §3.8 Activation — revise — ambiguity — delivery activates **every** `SCHEDULED` occupancy of the agreement, whatever institution it names — `routes/bookings.py:187-198`
- §3.8 Clearance — revise — ambiguity — the segregation bar reads only an `INTERSTATE_CVI` still standing `ISSUED` (a denied/voided one bars nobody); an `X-User-ID` naming no veterinarian is `ERR_VET_INSTITUTION_MISMATCH` — `routes/quarantine.py:18-21,95`
- §3.8 Failure — revise — mismatch — `failure_reason` is validated then discarded; the segregation bar does **not** apply to a failure; the agreement is unwound only where still `EXECUTED`, while the animal is driven to `HELD` and back to its sender from whatever `location_status` it held — `routes/quarantine.py:126,133,147-152`
- §3.8 Opening an introduction — revise — mismatch — PRD read animal-location first; impl checks `ERR_QUARANTINE_NOT_CLEARED` before `ERR_ANIMAL_LOCATION_CONFLICT` (matching §2.9 rung 8's own order) — `routes/introductions.py:40-43`
- §3.8 Observations — insert — ambiguity — no ownership check at all: any `Registrar` may record against any protocol, and the stage test is the only precondition — `routes/introductions.py:88-97`
- §3.8 Abort cascade link 2 — revise — mismatch — `genetic_designation` is driven to `HOLD_NO_BREED` from whatever it was carrying, not only from `BREED_RECOMMENDED` (left pass 2's link 3 untouched) — `routes/introductions.py:71`
- §3.9 Studbook filing — revise — mismatch — PRD read as a rule that `transfer_agreement_id` is null for a `BIRTH`; impl never compares it to `submission_type` and has no error for it — `routes/submissions.py:21-31`

Nothing in my slice needed a §4 or §5 row change; the existing rows (including line 400's already-patched "either party's registrar may reserve it") match impl.

## Final state

`wc -l` = **485**. Final line (485): `` | `ERR_ANIMAL_NOT_HELD_BY_SENDER` | 422 | `` — the last row of the §5 error catalogue, so the file ends on a real section boundary and is not truncated.

### Orchestrator final verification

- `PRD.md` 485 / `PRD_FINALIZED.md` 485 / `PRD_COMPLETED.md` 485 lines. `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (52 revised lines; 105,534 -> 119,030 chars, +13,496 chars / +12.8%), so the scan demonstrably ran.
- File ends at the last §5 error-catalogue row — not truncated.
- Zero occurrences of "scaffold" or "expert level" in `PRD_COMPLETED.md`; the difficulty directive never reached any PRD artifact.
- Step 9 changed no code, so the Step 7 sweep result stands: `results.1.json` ... `results.8.json` all 126/126.

Pipeline complete.
