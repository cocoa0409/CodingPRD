# Worklog — task_2881_aquatic_invasive_species_inspection_decontamination

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `tasks/task_2881_aquatic_invasive_species_inspection_decontamination/` and `tasks/task_2881_aquatic_invasive_species_inspection_decontamination/workspace/`. Index pre-assigned (2881) by the orchestrating command; no index scan performed.

## Step 2: Generate scaffold — 2026-09-05T12:49:00.000Z

Done. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_2881_aquatic_invasive_species_inspection_decontamination/`, generated only from the scenario text plus the scaffold-generator skill spec (no sibling task was read).

Lint verdict, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     12
  §1.8 instances scanned:     27
  §1.9 instances scanned:     73
  Calls scanned (§1.8+§1.9):  1212

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Artifacts (all non-empty, all `yaml.safe_load`-clean):
- `SCAFFOLD.yaml` — 2901 lines — §1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2695 lines — single key `scaffold_difficulty_design`, 27 instances over 9 rule_ids
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4488 lines — single key `scaffold_corner_design`, 96 instances (73 full recipes + 23 `excluded_because` stubs)

SCAFFOLD.yaml counts: 12 entities (flat topology), 8 state machines / 42 transitions over 7 entities, 2 concurrency rules, 12 calculations, 4 invariants, 38 ordered validations, 51 endpoints (one test-driving endpoint, `POST /_clock/set_current_utc`), 57 error codes, 7 roles (`role_model: segregation_of_duties`), `consistency_model: immediate`, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers`.

§1.9 breadth spread (section → instances): entities 14, state_machines 21, calculations 13, validations 21, endpoints 8, errors 5, rbac 5, cross_cutting_complexity_layers 7, consistency_model 2. Every `section:`/`claim_type:` value comes from `references/claim-extraction-guide.md`; all 23 stub citations resolve to real §1.8 instance names; no name collides between the two design files.

Design defects the §1.9 walk surfaced and that were fixed in SCAFFOLD.yaml rather than designed around (all recorded in the corner-design header):
- Added `PATCH /water-bodies/{id}` (ladder step 2) — `ERR_WATER_BODY_CYCLE` was unreachable once a row existed; also added to ProgramAdmin's exclusive ops and widened validations 6/8/10.
- Validation 32 now measures presented-seal age to the record's `arrived_at`, matching the basis `reciprocity_seal_decision` pins (it previously used current logical time).
- §1.2 now declares the `Inspector EXPIRED -> ACTIVE` transition that `POST /inspectors/{id}/status` already claimed in its §1.5 side effects (previously an undeclared transition).
- Earlier in the run: `PLANNED -> OPEN` no-hours precondition now names `ERR_INVALID_STATION_STATE`; `ERR_DECON_NOT_TREATED` scoped to `{ORDERED, RETREAT_REQUIRED}` so it cannot collide with `ERR_DECON_ALREADY_TERMINAL`.

Two housekeeping items: the `Generate task harder than expert level!` directive had leaked into SCAFFOLD.yaml's `scenario:` key and has been stripped (orchestrator re-verified: `grep -rn "harder than expert"` over the task dir returns nothing), and the task-scoped `.scratch_2881/` dir was removed.

Orchestrator verification: all three files present and non-empty (160KB / 174KB / 287KB).

## Step 3: Copy shared files — 2026-09-05T12:50:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2881_aquatic_invasive_species_inspection_decontamination/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T13:07:00.000Z

PRD generation for `task_2881_aquatic_invasive_species_inspection_decontamination` is complete and verified.

**Output:** `workspace/PRD.md` — **475 lines**, 108,363 bytes, built via 16 chunked `cat >>` appends (no single giant Write).

**Sections written**
- `# AIS Inspection & Decontamination API — Product Requirements Document`
- `## 1. Introduction` (AIS pathway framing, audit framing, three non-negotiables)
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 Role-Based Access Control (7 roles, entity-backed vs opaque), 2.2 API Response Structure (byte-for-byte verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Revision Counters, 2.5 The Logical Program Clock, 2.6 Nested Paths and Referential Integrity, 2.7 Stale-View Protection, 2.8 Numeric Discipline, 2.9 Certification Gates and Segregation of Duties, 2.10 Cascade Discipline and Conserved Quantities, 2.11 Order of Rejection
- `## 3. Business Logic & Workflows` — 9 domain-titled subsections (3.1 Program Foundations … 3.9 Public Education Campaigns)
- `## 4. Endpoint Definitions` — 51 rows, method/path/order machine-verified identical to `endpoints[]`, role cells verified against each endpoint's `roles`
- `## 5. Error Code Catalogue` — 57 rows, error IDs, statuses and ordering machine-verified identical to `errors[]`

**Hard Contract 1 — Field-Name Coverage: PASS.** 139 unique required names extracted programmatically from the scaffold (125 `entities[].fields`, 72 `request_body` inputs, 36 `query_params`, 2 path/other). Missing anywhere: 0. Missing as a *standalone* backticked token: 0. All 41 enum values (including `RUNNING`, added this pass), all 57 error IDs and all 7 role names appear as standalone backticked tokens.

**Hard Contract 2 — Rule Coverage: PASS.**
1. Validation priority ordering — §2.11 renders an explicit numbered 1–38 chain; every one of the 38 scaffold validations matched to its numbered item by error ID (the two 404-family items delegate to §2.6, which names all 10 not-found IDs).
2. `concurrency_rules` OCC — both rules covered in §2.7 with endpoint, `expected_watercraft_version` / `expected_inspection_record_version`, error ID and 412, plus the "why no state precondition suffices" rationale.
3. Cross-entity side effects — all 29 side-effect-bearing endpoints have prose coverage, including the 4-hop detection-acknowledgement cascade and the `{PLANNED, OPEN, SUSPENDED}` station-flip scope (matching scaffold line 1367, not the looser "OPEN" wording in that endpoint's own summary).
4. `applies_to` scopes — each §2.11 item names its scope in prose.
5. Field-level structured content — all 12 `calculations` and 4 `invariants` narrated; 42 state-machine transitions across 8 machines all covered (11 by prose phrasing rather than arrow notation, each individually confirmed).
6. Sibling-branch symmetry — dry-verification `VERIFIED`/`RETREAT`/`ABANDON`, quarantine `APPROVED`/`REJECTED`, breach from both origins, `PLANNED → CANCELLED` vs `RUNNING → CANCELLED`, and both `EXPIRED → ACTIVE` routes all given per-branch treatment.

**Hard Contract 3 — §3 Path Purity: PASS.** 1,016 backtick tokens (295 unique) in §3: 0 leading-slash tokens, 0 bare HTTP-method tokens, 0 method+path tokens, 0 tokens containing a slash at all. All paths/methods live only in §2.7 and §4.

**Tail verification:** `tail -40` ends at `` | `ERR_CAMPAIGN_BUDGET_EXCEEDED` | 422 | `` — the last complete row of the complete 57-row §5 table. Clean section boundary; not mid-sentence, not mid-table. Last heading is `## 5. Error Code Catalogue`.

**Also done this pass:** added explicit enum-member enumerations for station `status`, inspector `status`/`certification_level`, `inspection_status`/`enforcement_status`, DeconOrder `status` (plus its all-null-at-creation measurement fields, verified against the scaffold defaults), QuarantineOrder `status` and campaign `status`; fixed one duplicated-word artifact; ran a pseudocode/fuzzy-word scan (no `>=`, `==`, `IN {`, "approximately", "roughly", TODO). The task-scoped `.prdgen_scratch/` directory has been removed. `worklog.md` untouched; neither withheld design file was opened; no sibling task directory read; no processes killed.

**Orchestrator truncation check (per the known doc-generator failure mode):** independently verified — 475 lines, all five `## ` headings present in order (1 Introduction, 2 Global Specifications, 3 Business Logic, 4 Endpoint Definitions, 5 Error Code Catalogue), and `tail -12` ends on a complete §5 table row. Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-05T13:37:00.000Z

(Steps 5 and 6 were launched concurrently; Step 6 returned first, so its entry is recorded first. Step 5's entry follows below.)

Implementation for task 2881 is complete at `workspace/implementation/`.

## Modules (19 Python files, 2,821 lines total)

Core layer:
- `app.py` 65 — blueprint registration, `ApiError`/`HTTPException`/catch-all handlers
- `errors.py` 90 — all 57 error IDs with HTTP statuses + default messages
- `envelope.py` 51 — `meta`/`response_type`/`data` envelope, `req_` + 20-char request ids, wall-clock `api_request_timestamp`, list `has_more`
- `store.py` 126 — 12 in-memory dicts + logical clock (epoch `2026-08-01T00:00:00Z`), ISO parse/format at 3 fractional digits, `base_row`, touch-once-per-row-per-request versioning
- `validate.py` 267 — rejection steps 1-6 (auth, role, RBAC, entity-backed actor resolution, pagination, body shape) plus typed field validators
- `calc.py` 224 — every scaffold constant and all 11 calculations (Decimal + ROUND_HALF_UP)
- `services.py` 496 — shared side-effect engines: fee ledger, seal inventory, certification/training derivation, screening scoring (dual variant), treatment, hold escalation, watchlist/referral, 4-hop detection cascade, waterfall campaign allocation, compliance rate

Routes (`routes/`, 51 endpoints total, matching PRD §4's 51 rows and the scaffold's 51 paths — verified as 51 registered Flask rules):
`water_bodies.py` 105, `stations.py` 169, `inspectors.py` 127, `registry.py` 132, `records.py` 258, `decon.py` 179, `quarantine.py` 205, `detection.py` 116, `campaigns.py` 161, `clock.py` 18, `_common.py` 21, `__init__.py` 0.
Plus `start.sh` 10 (executable) and `requirements.txt` 1 (`flask>=2.0`).

## Smoke test

Launched exactly as the harness does, on a self-chosen free high port:
```
cd .../workspace/implementation && PORT=17281 setsid bash start.sh
```
Confirmed `Running on all addresses (0.0.0.0)` / `0.0.0.0:17281 LISTEN`; `POST /_clock/set_current_utc` → 200, `GET /water-bodies` → correct empty-array envelope with `limit/offset/total_count/has_more`, no-header request → 401, bodyless POST → 400, unknown path → 404. Cleaned up with `kill <exact PID resolved from ss -ltnp>` (PID 2690860); port confirmed free afterward. No pattern kill was ever used.

Two end-to-end functional flows (inspector certification → station staffing cascade → arrival → screening/scoring → decon order → treatment → dry verification → fee ledger; and seal reciprocity → quarantine → rejected release → escalation → enforcement → detection acceptance → campaign allocation/evaluation) each matched hand-computed expectations exactly. Scratch dir and `__pycache__` removed; `worklog.md` untouched; no test/helper directory was read at any point.

Notable spec decisions recorded during the build: `base_dry_hours` is fixed at decon-order creation; the station staffing recompute deliberately does not bump station `version`; PRD §2.11's numbered 38-step order was treated as authoritative over §3 prose everywhere they conflict (notably state check before inspector standing); treatment on a `TREATED` order returns `ERR_DECON_ALREADY_TERMINAL`; `seal_state_code` is always derived and silently ignored if supplied.

## Step 5: Generate unit tests — 2026-09-05T14:31:00.000Z

Generation complete. Both output directories sit at the task root (`test_helpers/` and `test_suite/`); `ls -la` on the task root confirms them, `find` shows no stray copies under `workspace/`, and nothing under `workspace/implementation/` was read or written. `worklog.md` untouched.

**test_helpers/ (Stage 1, 2,256 lines)**
`__init__.py` 43, `api_client.py` 210, `api_errors.py` 135, `assertions.py` 308, `constants.py` 98, `factories.py` 282, `fixtures.py` 673, `test_users.py` 88, `types.py` 419.

**test_suite/ (Stage 2, 8,539 lines, 241 test functions → 248 collected with parametrisation)**

| file | lines | tests | instances |
|---|---|---|---|
| conftest.py | 49 | 0 | – |
| test_01_risk_scoring_and_screening.py | 353 | 10 | 3 difficulty |
| test_02_inspection_fees_and_enforcement.py | 443 | 13 | 4 |
| test_03_decontamination_treatment.py | 315 | 10 | 3 |
| test_04_dry_verification_and_retreat.py | 275 | 8 | 3 |
| test_05_quarantine_release_cycle.py | 370 | 9 | 3 |
| test_06_quarantine_holds_and_seal_inventory.py | 294 | 8 | 3 |
| test_07_station_and_workforce_gates.py | 417 | 13 | 4 |
| test_08_detection_escalation_cascade.py | 144 | 4 | 1 |
| test_09_campaign_allocation_and_evaluation.py | 313 | 8 | 3 |
| test_10_entity_shapes_and_lookups.py | 579 | 14 | 14 corner entities |
| test_11_state_machine_corners.py | 1164 | 31 | 17 state_machines |
| test_12_calculation_corners.py | 629 | 18 | 7 calculations |
| test_13_validation_corners.py | 651 | 20 | 8 validations (V1–V8) |
| test_14_gate_and_priority_corners.py | 690 | 22 | 9 validations (V9–V17) |
| test_15_endpoint_corners.py | 743 | 21 | 7 endpoints |
| test_16_error_and_rbac_corners.py | 583 | 17 | 2 errors + 4 rbac |
| test_17_concurrency_cascades_and_consistency.py | 527 | 15 | 3 cross_cutting + 2 consistency_model |

**Design coverage (verified mechanically by `.testgen_scratch/coverage.py`, which parses both yamls and every `Design:` line)**
- 100 non-stub instances exist (27 difficulty across 9 rule_ids + 73 corner across 9 sections); **100 translated, 0 skipped, 0 missing**.
- 241 tagged tests / 100 distinct tags; **0 unknown tags**, **0 dual-tagged or untagged tests** (tagged-line count equals test-function count), every difficulty instance has ≥2 tests, every corner instance ≥1.
- The 23 corner entries carrying `excluded_because:` were **not** translated (0 stub tags), as required.
- No instance failed the PRD-first two-condition filter, so there are no gap-skips to group.

**Hygiene**: `pyflakes` and `py_compile` clean on all 18 test_suite files (zero unused imports, zero undefined names); the only pyflakes output anywhere is the expected re-export noise in the `test_helpers/__init__.py` barrel. `pytest --collect-only` collects 248 tests in 0.87 s. No server was ever started, so no kill of any kind was performed. All files were written in chunked `cat >>` appends with `wc -l` after each; scratch lives only in `.testgen_scratch/`.

**Design-vs-PRD deviations honoured (PRD wins)**: the errors instance's single-space `X-User-Role` control was replaced by missing / `""` / undeclared-role / missing-id / `""`-id probes (a space is rejected client-side as an InvalidHeader, per fixture-type discipline and `raw_headers`' own docstring) — instance still covered by 3 tests; the OCC re-screen asserts `risk_score == 30`, the value the PRD's pinned order of operations derives from the design's own component list (the yaml's "25" total is an arithmetic slip), and `standing_water_ml == 0` rather than the yaml's `null` because §3.4 declares the field "defaulting to 0"; earlier files already used the PRD's `RUNNING`, `penalty_cents` and `SEAL_TAMPER` in place of the design's `LAUNCHED`, `enforcement_penalty_cents` and `SUSPECTED_TAMPER`.

**Orchestrator verification:** both `test_helpers/` and `test_suite/` confirmed at the task root; `find workspace -name test_suite -o -name test_helpers` returned nothing (no stray copies to relocate). Scratch and `__pycache__` dirs removed.

## Step 7: Run tests and iterate — 2026-09-05T15:32:00.000Z

All 8 rounds green at 248/248. Task dir is untracked in git, so the changes are as recorded below.

## Summary

**Iterations run:** 2 (one diagnostic sweep, one verification sweep).

**Tests deleted:** none. All three failures traced to PRD-verbatim rules that a faithful implementer would satisfy — every one was a test-layer bug, so STEP 1 (coverage + unique derivability) passed in all three cases and the fixes went into the test artifact.

**Fixes applied to `test_suite/`:**

- `test_suite/test_16_error_and_rbac_corners.py` — `TestWatercraftRegistrationAndReadsAreOpenToBothIdentities::test_the_shared_write_is_open_to_the_entity_backed_inspector`: asserted `vessel["strike_count"] == 0` and `watchlist_status == "NONE"`, neither of which is a PRD field/value. PRD §3.3 says verbatim "`compliance_strikes` starts at 0, `watchlist_status` starts `CLEAR`". Corrected to `compliance_strikes` / `"CLEAR"` (the `KeyError: 'strike_count'` was the test naming a field the PRD never declares).

- Same file, `TestTheFourRemainingNotFoundCodes::test_an_action_on_a_missing_id_is_a_404_rather_than_a_state_conflict`: the test asserted `ERR_DECON_ORDER_NOT_FOUND` while sending `make_release_verifier_headers("verif-unresolvable-1")`. PRD §2.11 settles the entity-backed `X-User-ID` at **step 4** (`ERR_INSPECTOR_NOT_FOUND`), *ahead of* path existence at **step 7** — so `ERR_INSPECTOR_NOT_FOUND` was the PRD-correct response and the implementation was right. Swapped in `setup_program(clock=CLOCK)` and a resolvable `ctx["inspector_c"]` verifier so the request actually reaches the path-existence check the test claims to exercise. Left a comment recording the precedence.

- `test_suite/test_07_station_and_workforce_gates.py` — module-local fixture `_station_one_certified_inspector_short()`: built its station via `create_and_open_station(...)` with no `hot_water_capable`, which PRD §3.1 defaults to false. `decon_service_available` "is true exactly when the station's `certified_inspector_count` has reached two **and** `hot_water_capable` is true", so the implementation correctly kept it false and `test_the_promotion_makes_the_station_offer_decontamination` failed on `assert False is True`. Added `hot_water_capable=True` to the fixture — the precondition PRD requires for the asserted cascade. The test's `before[...] is False` guard still holds meaningfully (count is 1 at that point), and the two sibling tests using this fixture only read inspector fields.

**Fixes applied to `test_helpers/`:** none needed — the shared factories, fixtures and role-header builders were already PRD-consistent (none of the known high-frequency root causes applied; there was no mass-failure cluster).

**Fixes applied to `implementation/`:** none. No implementation defect was found; in particular `routes/decon.py::verify_order` already orders `require_auth` (step 4) before `decon_order_or_404` (step 7) exactly as §2.11 requires, and that was left intact rather than reordered to accommodate the bad fixture.

**Final sweep evidence** (`results.$i.json`, 8 concurrent rounds, `--isolation per-test-server`):

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 248/248 | 248/248 | 248/248 | 248/248 | 248/248 | 248/248 | 248/248 | 248/248 |

Zero failures, zero errors, and the union of failing tests across all 8 rounds is empty — so there is no residual flakiness signal. Iteration 1 had been 245/248 in *every* round with the identical three failures, i.e. fully deterministic rather than load-induced, which is why no re-run was needed before diagnosing. `worklog.md` was not touched by the subagent.

**Orchestrator verification:** independently read all 8 `results.$i.json` — each reports `passed == total == 248`. Baseline sweep was confirmed at 245/248 in all 8 rounds before the fixes, matching the subagent's deterministic-failure account. Sweep was run via the prepared `workspace/sweep.sh` under `setsid nohup` (no reaping; no round died at t=0).

**Step 8 gate decision:** Step 7 made 3 `test_suite/` fixes, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is NOT met — Step 8 will run. Note that with 0 `implementation/` fixes, a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome: the PRD was never wrong about the implementation, only the tests were, and one of the three fixes (the §2.11 precedence one) is exactly the kind of item that reveals no PRD silence at all.

## Step 8: Finalize PRD — 2026-09-05T15:27:00.000Z

**Zero edits.** `workspace/PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` (475 lines each, 0.0% delta, `cmp` clean, md5 `c4c2f1d55ddb6ce69bc1c0a557d11830` on both).

Every one of the three `<step_7_diff>` items resolved to a test-artifact bug against PRD prose that is already verbatim-determinative, and in all three cases the implementation matches that prose exactly. No PRD silence and no PRD/impl mismatch was found within the hard scope, so no edit was warranted.

Per-item analysis (subject / impl paths enumerated / wording adjustment):

1. **`strike_count` / `"NONE"` KeyError** (test_16, shared watercraft write)
   - (a) Subject: derived initial values of vessel `compliance_strikes` and `watchlist_status`, plus the roles permitted on the watercraft write.
   - (b) Enumerated & read: `implementation/routes/registry.py:22-48` (`create_watercraft`, `require_auth(("ProgramAdmin","Inspector"))`, literal `"compliance_strikes": 0` and `"watchlist_status": "CLEAR"`), `registry.py:69` (listing filter), `services.py:202-215` (the only other writer — strike increment and `WATCHLISTED`/`CLEAR` recompute), `routes/records.py:238,253` (enforcement referral/dismissal strike paths), `calc.py:57` (`WATCHLIST_STRIKE_THRESHOLD = 2`), `calc.py:202` (`penalty_for`).
   - (c) No wording change. PRD §3.3 line 231 already states "`compliance_strikes` starts at 0, `watchlist_status` starts `CLEAR` (its only other value being `WATCHLISTED`)", and §4 line 377 already grants `ProgramAdmin`, `Inspector` on `POST /watercraft`. The test invented a field name the PRD never declares.

2. **`ERR_INSPECTOR_NOT_FOUND` vs `ERR_DECON_ORDER_NOT_FOUND` precedence** (test_16, decon verify)
   - (a) Subject: §2.11 step 4 (entity-backed `X-User-ID` resolution) preceding step 7 (path existence).
   - (b) Enumerated & read: `validate.py:30-47` (`require_auth`: header presence → role membership → permitted roles → `ENTITY_BACKED_ROLES` inspector lookup raising `ERR_INSPECTOR_NOT_FOUND`), `routes/decon.py:132-146` (`verify_order` calls `require_auth` at :133, `services.decon_order_or_404` only at :138), and the parallel entity-backed entrypoints `decon.py:24-30` (`create_order`), plus the same `require_auth`-first shape across `routes/records.py`, `routes/quarantine.py`, `routes/detection.py`, `routes/inspectors.py`.
   - (c) No wording change. PRD §2.11 steps 4 and 7 already fix this ordering, and it holds uniformly, not just at the Step 7 site. Any edit here would have been a redundant restatement at best and a narrowing at worst.

3. **`decon_service_available` stayed false after promotion** (test_07 fixture omitted `hot_water_capable`)
   - (a) Subject: the `decon_service_available` derivation and the default of `hot_water_capable`.
   - (b) Enumerated & read: `services.py:67-87` (`recompute_station_staffing` — `count >= CERTIFIED_INSPECTOR_DECON_THRESHOLD and station["hot_water_capable"]`), `calc.py:13` (threshold `= 2`), `services.py:89-90` (`station_staffing_cascade`), `routes/stations.py:32` (`opt_bool(body, "hot_water_capable", False)`) and `stations.py:57-60` (`"decon_service_available": False` at creation), plus every cascade caller — promotion, suspension, reinstatement, lazy expiry, and the station-open re-initialisation.
   - (c) No wording change. PRD §3.1 line 197 already states the conjunctive rule and the false default for `hot_water_capable`; §3.2 already declares the promotion cascade. Specifically considered and rejected adding a note that the staffing recompute does not bump the station's `version` (`services.py:69-73`): that is outside the hard scope — no Step 7 fix touched a station-version assertion — and asserting it would risk a new mismatch against the seal/fee/campaign/detection cascades that do bump it.

**Orchestrator verification:** `PRD.md` and `PRD_FINALIZED.md` both 108,363 bytes. A byte-identical Step 8 output is the expected and legitimate result here, because Step 7 applied **0** `implementation/` fixes — the PRD was never wrong about the implementation. (Step 9, by contrast, must NOT come out identical; the full impl scan is a different and much wider question.)

## Step 9: Complete PRD — 2026-09-05T15:57:00.000Z

Run as **three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`** (pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from copying, to avoid clobbering prior edits). Total **55 edits — 44 ambiguity-pins, 11 mismatch-revisions.** 475 → 476 lines, 108,363 → 123,956 bytes (+15,593 bytes, 208 diff lines vs `PRD_FINALIZED.md`).

### Pass 1 — core layer + water bodies / stations / inspectors (20 edits: 15 ambiguity, 5 mismatch)

Slice: `app.py`, `envelope.py`, `store.py`, `validate.py`, `errors.py`, `routes/clock.py`, `routes/water_bodies.py`, `routes/stations.py`, `routes/inspectors.py`, plus `calc.py` numeric discipline and the certification/staffing/seal-inventory engines in `services.py`. Ran the `cp` from `PRD_FINALIZED.md`; 475 → 476 lines (one new bullet in §2.2, all else in-paragraph).

- §2.2 success bullets — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars; `api_request_timestamp` is the host **wall** clock, not the logical clock — `envelope.py:9,13,19,23`
- §2.2 error bullets — insert — ambiguity — unrouted path → `ERR_INVALID_REQUEST` @404, bad method → `ERR_INVALID_REQUEST` @405; trailing slash tolerated — `app.py:21,34-42`
- §2.3 — revise — ambiguity — `limit`/`offset` checked only when supplied; decimal-integer literal only (sign/whitespace ok, `10.5`/empty rejected) — `validate.py:53-70`
- §2.3 — revise — ambiguity — `created_at` ties (common, since it comes off the logical clock) break by insertion order — `store.py:124-126`
- §2.3 — revise — ambiguity — filter values compared literally; out-of-enum values match nothing rather than erroring; bool filters accept `true`/`false` case-insensitively, anything else matches nothing; undeclared query params ignored — `validate.py:78-94`, `routes/_common.py:14-21`
- §2.4 — revise — ambiguity — `created_at`/`updated_at` come from the logical clock; accepted client instant forms (≥ minutes, optional seconds/fraction, `Z`/numeric offset, bare = UTC) and canonical re-emission with **truncation** past 3 digits — `store.py:16-57,88-101`
- §2.4 — revise — **mismatch** — touch-once-per-row-per-request (version +1 even on multi-path writes) and the staffing recompute is the one cascade that writes a station without advancing `version`/`updated_at` — `store.py:104-117`, `services.py:68-87`
- §2.5 — revise — ambiguity — `to_iso8601` required, clock may move backwards, response `data` carries only `current_utc` — `routes/clock.py:12-18`
- §2.5 — revise — **mismatch** — lazy expiry surfaces only when the inspector is the acting principal on an `ACTIVE`-demanding op (not on any "reference") — `services.py:97-113`
- §2.6 — revise — **mismatch** — dropped "regardless of anything else": nested-path 404 sits at step 7, behind pagination and body-shape — `routes/stations.py:134-141`, `routes/inspectors.py:99-105,123-124`
- §2.9 — revise — **mismatch** — standing guard resolves to the acting principal only; no request body in the API carries an inspector id (verified by grep over all of `routes/`) — `validate.py:43-46`, `services.py:109-113`
- §2.11 step 6 — revise — ambiguity — JSON `null` = absent (takes the declared default, with the §3.1 correction as the sole exception); no type coercion (strings/bools/non-integral numbers rejected); empty body = `{}`, parsed regardless of `Content-Type`, non-object body → `ERR_INVALID_REQUEST` — `validate.py:100-207`
- §3.1 water-body correction — revise — ambiguity — key-presence semantics (explicit null clears the drainage parent and re-runs the cycle check); a no-op correction still bumps `version`/`updated_at` — `routes/water_bodies.py:93-104`
- §3.1 station init — revise — **mismatch** — seal stock re-initialises on `PLANNED → OPEN` only, not on "first leaves PLANNED" — `routes/stations.py:102-115`
- §3.1 hours — revise — ambiguity — windows may be declared/listed for a station in any status, `CLOSED` included — `routes/stations.py:130-169`
- §3.1 lifecycle — revise — ambiguity — any declared window (past or future) satisfies the open precondition — `routes/stations.py:102-107`
- §3.2 training — revise — ambiguity — `training_hours_total` emitted as a JSON number (`8.0`); inspector `version` moves only when total/level/standing/expiry actually change (failed module = untouched row); no expiry re-stamp for an already-`ACTIVE` inspector; `completed_at` null when omitted — `services.py:135-156`, `routes/inspectors.py:103-113`
- §3.2 promotion cascade — revise — ambiguity — counters re-derived from scratch, and the recompute never advances the station's `version`/`updated_at` — `services.py:68-91`
- §3.2 reinstatement — revise — ambiguity — level test first; failing either condition (null expiry included) → `ERR_INVALID_INSPECTOR_STATE` — `routes/inspectors.py:76-82`
- §3.2 renewal — revise — ambiguity — `TRAINEE` on `EXPIRED → ACTIVE` also → `ERR_INVALID_INSPECTOR_STATE` — `routes/inspectors.py:83-86`

Verified, no change needed: the §5 catalogue is exactly right — all 57 IDs and every HTTP status match `errors.py` (programmatic diff, zero deltas). `calc.py` numeric discipline (`ROUND_HALF_UP` via Decimal, floored quotients, clamps) and the constants in the slice already match §2.8/§3.1/§3.2. `has_more` is equivalent to PRD's prose in every reachable case. Rejection-order steps 4/5/6/7/8/9 are as PRD states.

Deliberately left alone: empty-string `corridor_route_code` acceptance (PRD's null/non-null wording matches impl literally); the unreachable cycle check on water-body *creation* (server-minted ids make self-reference impossible, PRD's claim is harmless); items belonging to passes 2 and 3.

### Pass 2 — registry / records / decontamination (22 edits: 20 ambiguity, 2 mismatch)

Slice: `routes/registry.py`, `routes/records.py`, `routes/decon.py`, plus the fee-ledger, risk-screening/scoring (incl. dual variant), treatment, dry-verification and watchlist/strike/enforcement engines in `services.py` and their `calc.py` constants. No `cp` run; 476 → 476 lines (all in-paragraph).

- §3.3 vessel registration — revise — ambiguity — `registration_number` uniqueness is a literal comparison (case-distinct); `home_state_code` must be exactly two uppercase letters — `routes/registry.py:26,36` + `validate.py:142`
- §3.3 agreements — revise — ambiguity — `partner_state_code` exactly two uppercase letters — `routes/registry.py:81`
- §3.3 agreements — revise — ambiguity — `max_seal_age_hours` must be a whole number of hours (fractional → `ERR_INVALID_REQUEST`) — `routes/registry.py:84`
- §3.3 agreements — insert — ambiguity — agreement status machine declares no invalid/terminal transition; every accepted call writes `target_status` and bumps `version` (self-transition is a no-op accept); `reason` never persisted — `routes/registry.py:126-132`
- §3.3 seal decision — insert — ambiguity — `presented_seal_state_code` is a free-form string, so a seal presented with it omitted matches no agreement (→ `ERR_RECIPROCITY_AGREEMENT_NOT_FOUND`) — `routes/records.py:138-144`
- §3.3 seal age — insert — ambiguity — missing `presented_seal_issued_at` and a seal issued at/after arrival both read as age 0 (negative elapsed clamped to 0) — `services.py:224-228`
- §3.4 arrival — insert — ambiguity — body FKs resolved `station_id` first, `watercraft_id` second, before any site condition — `routes/records.py:33-34`
- §3.4 fresh-record defaults — revise — ambiguity — added `standing_water_ml` 0; `prior_water_body_id` and the three `presented_seal_*` fields null; `residual_water_present` false — `routes/records.py:53-85`
- §3.4 screening — insert — ambiguity — the "no prior water body" `ERR_INVALID_REQUEST` is evaluated right after record resolution, ahead of the water-body lookup, agreement lookup, ownership, record-state and stale-version tests — `routes/records.py:126-133`
- §3.4 screening payload — insert — ambiguity — `residual_water_present` is required on every screening — `routes/records.py:119`
- §3.4 re-screen — revise — ambiguity — a re-screen also overwrites all three presented-seal fields, writing them back to null when no seal is presented — `routes/records.py:172-174`
- §3.5 disposition — insert — ambiguity — `notes` read for shape only, never persisted — `routes/records.py:185`
- §3.5 refusal — insert — ambiguity — the refusal→`REFERRED` cascade fires only while `enforcement_status` is `NONE`; otherwise the refusal is still accepted and billed with the enforcement dimension and strike count untouched — `routes/records.py:212`
- §3.5 enforcement — insert — ambiguity — `CITED` and `DISMISSED` are both terminal on that dimension (re-referring a dismissed record is `ERR_INVALID_ENFORCEMENT_STATE`) — `routes/records.py:230-246`
- §3.5 enforcement — insert — ambiguity — officer `REFER` omitting `referral_reason` leaves it null; `CITE`/`DISMISS` overwrite `agency_code` when supplied and leave it alone otherwise; `notes` never persisted — `routes/records.py:223-250`
- §3.5 dismissal — insert — ambiguity — the strike decrement never goes below 0 — `routes/records.py:253`
- §3.6 order creation — revise — **mismatch** — `base_dry_hours` is NOT null on a fresh order; it is fixed at creation from the frozen band (removed from the "starts null" list) — `routes/decon.py:57`
- §3.6 treatment payload — insert — ambiguity — temp/pressure accepted as numbers incl. fractions, `dwell_seconds` must be a whole number, all three > 0 — `routes/decon.py:91-93`
- §3.6 effectiveness — insert — ambiguity — `treatment_effectiveness_pct` emitted as a JSON number without trailing zeros (100.00 → `100.0`) — `services.py:331`
- §3.6 retreat outcome — revise — **mismatch** — `TREATED → RETREAT_REQUIRED` does *not* vacate the bay: readings, timestamps and the bay occupation interval stay, and the order keeps counting against the station's bays — `routes/decon.py:169-170` + `services.py:300`
- §3.6 retreat cycle — insert — ambiguity — a treatment aimed at an order already in `TREATED` draws `ERR_DECON_ALREADY_TERMINAL` (treatment is declared only from `ORDERED`/`RETREAT_REQUIRED`) — `routes/decon.py:97-98`
- §3.6 dry verification — insert — ambiguity — `notes` read for shape only, never persisted — `routes/decon.py:136`

Deliberately left alone: §2.11 step 14's enumeration of `ERR_DECON_ALREADY_TERMINAL` is incomplete versus impl's TREATED-treatment case, but the rejection ladder is pass 1's slice, so the behavior was pinned in §3.6 instead; §2.10's conserved-quantity paragraphs verified exact against `apply_fee`/`refund_treatment_portion`/`derive_watchlist`; §3.6 SoD-vs-dry-time order already pinned by §2.11 steps 20/24; endpoint-table filter descriptions (the table is a routing summary, §3 carries the complete filter lists).

### Pass 3 — quarantine / detection / campaigns (13 edits: 9 ambiguity, 4 mismatch)

Slice: `routes/quarantine.py`, `routes/detection.py`, `routes/campaigns.py`, plus the hold-escalation engine, the 4-hop detection cascade, the waterfall allocation algorithm and the compliance-rate/effectiveness computation. No `cp` run; 476 → 476 lines.

- §3.7 — revise — **mismatch** — PRD said issuance may optionally carry `seal_state_code`; impl never reads it and always derives it, so the field is now stated as service-derived and silently ignored when supplied — `routes/quarantine.py:24-25`, `services.py:365-370`
- §3.7 — insert — ambiguity — issuance advances the station's and the vessel's `version` by 1, the order is created at `version` 1, the parent record is untouched, and the 201 already carries a populated `hold_hours_required`/`hold_until` — `routes/quarantine.py:66-79`, `store.py:100`
- §3.7 — insert — ambiguity — `notes` on release-request, release and breach-report is validated as a string of any length but never persisted — `routes/quarantine.py:111,135,185`
- §3.7 — insert — ambiguity — an approved release writes nothing to the parent record (status, enforcement dimension, `version` all unchanged) — `routes/quarantine.py:161-166`
- §3.7 — revise — **mismatch** — rejection referral fires at `rejected_release_count` **≥** 2 (not exactly 2), only while the record's `enforcement_status` is `NONE`, and the record's `version` advances when it fires — `routes/quarantine.py:173-175`, `services.py:207-218`
- §3.7 — revise — **mismatch** — breach report also advances the parent record's `version` when the referral fires, and checks neither standing, certification, nor `hold_until` — `routes/quarantine.py:181-205`, `services.py:218`
- §3.8 — insert — ambiguity — `water_body_id` is null when the parent record is unscreened; `observed_at` is null when omitted, never defaulted, and consumed by no rule; drafting touches no other row — `routes/detection.py:26,33-43`
- §3.8 — insert — ambiguity — `REJECTED` verdict stores `rejection_reason` as supplied (empty string allowed, null when omitted) and leaves `state_db_ack_id` as it stands — `routes/detection.py:97,107-109`
- §3.8 — insert — ambiguity — `state_db_ack_id` stays null when the steward supplies none, and a null `water_body_id` aborts the entire cascade (no counter, no escalation, no station/window hop) — `routes/detection.py:96,112`, `services.py:376-379`
- §3.8 — insert — ambiguity — the third and fourth hops are gated on the confirmed state, so they re-enter on every later accepted report while `live_detection_count` ≥ 2, but are silent no-ops because already-mandatory stations are skipped and only just-flipped stations' windows are visited — `services.py:384-406`
- §3.9 — revise — **mismatch** — PRD claimed the launch guard ensures every station gets ≥ 1 cent; impl only tests `budget_cents < len(candidates)`, so a light candidate can end at 0 allocated cents yet still appear in the array with its `version` advanced — `services.py:446-447,454-466`
- §3.9 — insert — ambiguity — evaluation method falls back to `PRE_POST` when neither the call nor the campaign names one and the selected method is written back onto `evaluation_method`; a revised `impressions` overwrites the stored count before the bonus is computed — `routes/campaigns.py:141-143,148,154`
- §3.9 — insert — ambiguity — both rates entering the score difference are the four-decimal rounded values, so `effectiveness_score` is reproducible from the two stored rates; the alternate score reuses the same window rate and bonus — `routes/campaigns.py:131,145-146`, `calc.py:215-224`

Pass 3 structural checks (both PASS): five `##` sections present in order at lines 3/11/190/356/414, 20 `###` subsections, no duplicated heading; tail ends at a complete §5 table row. No repair needed. Bonus: every `ERR_*` in prose resolves to a §5 catalogue row; no new identifiers introduced.

Deliberately left alone: all rejection *ordering* at pass-3 sites (traced against §2.11 steps 12/14/16/17/21/22/24/27/29/33/35/36/37/38 — impl matches, and §2.11 is pass 1's slice); §2.9's standing/certification/SoD enumerations already exclude exactly the pass-3 operations impl leaves ungated; listing order / pagination / float emission (other slices); the redundant campaign budget re-check at launch (unreachable given the creation-time cap).

### Orchestrator verification

- `PRD_COMPLETED.md` is **476 lines / 123,956 bytes**, versus `PRD_FINALIZED.md` at 475 lines / 108,363 bytes — **208 diff lines, +15,593 bytes**. It is emphatically NOT byte-identical to its source, so the scan genuinely ran (a byte-identical Step 9 output would mean the opposite).
- Five `## ` sections confirmed present and in order; tail confirmed ending on the complete final §5 row `| ERR_CAMPAIGN_BUDGET_EXCEEDED | 422 |`.
- Partitioning worked as intended: pass 1 performed the single `cp` and grew the file by one line; passes 2 and 3 each confirmed they ran no `cp` and made in-paragraph-only edits, so no pass clobbered another. Cumulative edit count 20 + 22 + 13 = **55**.
- `__pycache__` / `.pytest_cache` dirs removed. Final artifact set present: SCAFFOLD×3, worklog.md, test_helpers/ (9 files), test_suite/ (18 files), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ incl. results.1..8.json all at 248/248}.

## PIPELINE COMPLETE — 2026-09-05T16:00:00.000Z

All nine steps finished. Final state: 248/248 tests passing in all 8 concurrent stability rounds; `workspace/PRD_COMPLETED.md` written.
