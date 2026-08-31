# Worklog — task_2152_hmda_data_collection_reporting

## Step 1: Create task directory — 2026-08-25T12:50:27.685Z

Created `tasks/task_2152_hmda_data_collection_reporting/` and `tasks/task_2152_hmda_data_collection_reporting/workspace/`.

## Step 3: Copy shared files — 2026-08-25T12:51:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2152_hmda_data_collection_reporting/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-25T13:48:25.676Z

All three artifacts are generated and lint-clean.

## What was generated

`/home/ubuntu/github/CodingPRD/tasks/task_2152_hmda_data_collection_reporting/`
- `SCAFFOLD.yaml` (§1.0–§1.7, 120 KB)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key)

## Structure

**Profile** — `compliance_audit` × `workflow_orchestration`; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation. `entity_topology: flat`, `state_machine_shape: cyclic`, `role_model: segregation_of_duties`, `consistency_model: immediate`. `api_prefix: /hmda`. Expert+ band.

**12 entities** — Institution, Application, DemographicEntry, GeocodeAssignment, CensusTract (immutable), EditRun, EditException, FilingSubmission, DisclosureStatement (immutable), AuditSample, AuditFinding, FairLendingAnalysis. Self-referential FK (`Application.supersedes_application_id`), 15 FKs all reverse-reachable via sub-resource GETs.

**9 state machines** — Application carries **two parallel dimensions** (`stage` INTAKE→…→ARCHIVED with a REGISTER_LOCKED→DECISIONED reopen cycle, and `lar_status` PENDING_FIELDS/COMPLETE/EXCEPTION_FLAGGED/CLEARED/EXCLUDED); FilingSubmission is **cyclic** (DRAFT→EDITS_ATTACHED→CERTIFIED→FILED→REJECTED→DRAFT); AuditSample **branches** to CLOSED_CLEAN/CLOSED_WITH_FINDINGS; EditException cycles VERIFIED→OPEN; plus EditRun, GeocodeAssignment, FairLendingAnalysis, DemographicEntry.

**11 calculations** — filing_profile_resolution (pinned-order constraint propagation, 500-origination boundary), application_completeness, geocode_match_resolution, edit_check_evaluation (S300/S301/V610/V620/V631/Q607/Q615/Q620 + macro Q800), certification_verification_quota (snapshot-pinned circular dependency), submission_record_count (PROVISIONAL vs FINAL), filing_deadline_and_lateness, audit_sample_sizing_and_selection (tiered + nested min/max), audit_defect_rate (FIELD_WEIGHTED vs RECORD_WEIGHTED), fair_lending_disparity_index (rounding order pinned: 133.34 vs 133.33), disclosure_redaction.

**35 validations** (priority 10→156), **46 endpoints** (21 reads / 25 writes incl. `POST /_clock/set_current_utc` defaulting to 2026-08-01T00:00:00Z), **50 errors**, **6 roles** (InstitutionAdmin is `entity_backed:Institution`; the rest opaque; SoD blocks a certifier who verified an exception), **2 OCC rules** (Institution.version on submission create, Application.version on geocode create).

## Design indices

- **§1.8: 22 instances** across all nine rules (2/3/2/2/3/3/3/2/2) — cascades of depth 5 (reopen → decertification) and depth 3 (file → archive → year close); overlap rules contrast half-open Institution edit-run windows against closed, touching-collide Application remediation windows; invariants conserve the register-record accounting identity and the exception ledger identity.
- **§1.9: 91 instances** (75 executable + 16 `excluded_because` stubs) across all nine claim-extraction sections.

## Verification

`scaffold_lint.py` verdict, pasted verbatim:

```
Coverage
  §1.5 endpoints declared:    46
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     75
  Calls scanned (§1.8+§1.9):  648

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional self-checks passed: 113 unique instance names, zero unbound `${var}` placeholders across 648 calls, every `excluded_because` stub resolves to a real §1.8 instance name, all 50 error codes appear in at least one design file, no forbidden concurrency vocabulary, no `id`-based business decisions (ordering everywhere is `created_at ASC`). Formula-derived assertions (133.34, 37.50/100.00, 999.99, sample sizes, quota, late_by_days) were computed in Python before being written as literals. No sibling task directories were read.

## Step 4: Generate PRD — 2026-08-25T14:00:00.000Z

All constants, contracts, and coverage checks pass. The PRD is complete.

## Result

**Output:** `workspace/PRD.md` — **448 lines**

Written incrementally in five appends (intro+2.1 → verbatim 2.2 → 2.3–2.11 → 3.1–3.2 → 3.3–3.4 → 3.5–3.6 → 3.7–3.9 → 4+5), so the output-token cap was never a risk. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 139 required, 139 present, 0 missing
- endpoints[].request_body/input: 75 required, 75 present, 0 missing
- endpoints[].query_params: 11 required, 11 present, 0 missing
- errors[].id: 50 required, 50 present, 0 missing
- roles[].name: 6 required, 6 present, 0 missing
- state values: 35 required, 35 present, 0 missing
- enum-field values: 106 required, 106 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 35 checked, 35 expressed in prose (full ladder in §2.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named in §2.8), 0 missing
- state_machines[].transitions: 9 machines / 47 transitions checked, 47 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed with constants, pinned order and precision, 0 missing
- validations[] conditions: 35 checked, 35 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 46 checked, 46 expressed, 0 missing
- entities[].fields[] structured content: 139 checked, 139 reconstructible (defaults, initial values, common_fields:false exceptions for CensusTract/DisclosureStatement), 0 missing
- sibling-branch symmetry: 6 groups checked (geocode 3-way outcome, run RUNNING→COMPLETED/CLEARED_ALL, sample close 3-way, defect-rate variants, submission-count variants, disparity 3-branch), 6 with equal density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 913
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Coverage map (scaffold → PRD)

| Scaffold | PRD home |
|---|---|
| `scenario` | §1 (3 paragraphs) |
| `roles` (6, incl. all `identity:` translations) | §2.1 |
| `response_envelope` | §2.2 verbatim (byte-identical, `data: { }` untouched) |
| `pagination_defaults` | §2.3 |
| `common_fields` incl. the two `false` entities | §2.4 |
| clock endpoint semantics / 2026-08-01 default | §2.5 |
| path + body FK resolution, all sub-resource navigation | §2.6 |
| `calculations[].precision` | §2.7 |
| `concurrency_rules` (2) | §2.8 |
| `validations` priority ladder (35, in order) | §2.9 (+ conditions restated at their workflow) |
| cascade/`version`/`updated_at` semantics | §2.10 |
| segregation-of-duties role model | §2.11 |
| `filing_profile_resolution`, `filing_deadline_and_lateness` step 1, Institution counters | §3.1 |
| Application stage + lar_status machines, `application_completeness`, 5-hop reopen cascade, archival/reversal | §3.2 |
| DemographicEntry machine, validations 92/94/96/98/138/140 | §3.3 |
| CensusTract, GeocodeAssignment machine, `geocode_match_resolution`, override rules | §3.4 |
| action-taken validations 100–124 | §3.5 |
| EditRun + EditException machines, `edit_check_evaluation` (9 edit codes), `certification_verification_quota`, window overlap 130 | §3.6 |
| FilingSubmission machine (cyclic), `submission_record_count` both variants, `filing_deadline_and_lateness`, `disclosure_redaction`, DisclosureStatement | §3.7 |
| AuditSample/AuditFinding machines, `audit_sample_sizing_and_selection`, `audit_defect_rate` both variants, window overlap 132 | §3.8 |
| FairLendingAnalysis machine, `fair_lending_disparity_index` (pinned triple rounding) | §3.9 |
| `endpoints` (46) | §4, 4-column table |
| `errors` (50) | §5, 2-column table |

**Deliberate omissions:** none of the rule content. Only *form* differs — no request/response bodies or side-effect columns in §4, no trigger-condition column in §5 (both per spec), and `EditRun.scope` (`FULL`/`INCREMENTAL`) is named and enumerated but carries no behavioral branch because the scaffold assigns it none.

Orchestrator verification: 448 lines, 5 top-level sections, 46 endpoint table rows, 50 error table rows — no truncation.

## Step 6: Generate implementation — 2026-08-25T14:22:00.000Z

Implementation complete at `workspace/implementation/`.

## Files generated (3,146 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | `exec python3 app.py`, guarded `pip install` (no-op once flask is present) |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 90 | Entry point, blueprint registration, error handlers, request-serializing WSGI middleware |
| `store.py` | 88 | In-memory dicts, logical clock, UUID/timestamp/version bookkeeping |
| `errors.py` | 76 | `ApiError` + all 50 error IDs → HTTP status |
| `response.py` | 49 | `meta`/`response_type`/`data` envelope, pagination meta |
| `constants.py` | 196 | Every enum + pinned numeric constant |
| `auth.py` | 24 | Ladder steps 1–3 (`X-User-ID`/`X-User-Role`, role list, InstitutionAdmin scope) |
| `validate.py` | 202 | Ladder step 5 (body shape, enums, ranges, ISO-8601, `limit`/`offset` bounds) |
| `serializers.py` | 259 | Per-entity field sets (CensusTract/DisclosureStatement carry no `updated_at`/`version`) |
| `calc.py` | 329 | All 11 pinned calculations, `Decimal`/`Fraction`, ROUND_HALF_UP |
| `cascades.py` | 129 | Run invalidation, decertification, staling, 5-hop reopen cascade |
| `routes/*.py` (10) | 1,693 | One module per resource group |

## Endpoints: 46 (all 45 `/hmda/*` routes from PRD §4 plus `POST /_clock/set_current_utc`)

## Boot smoke test: passed
Fresh process on `PORT=18777` via `bash start.sh`; `GET /hmda/institutions/{unknown}` → 404 `ERR_INSTITUTION_NOT_FOUND` in the correct envelope, `POST /hmda/institutions` → 201 with the derived filing profile. Store confirmed empty at boot (no seeding anywhere). Two end-to-end scripts also passed: full happy path (onboard → capture → geocode → action → lock → edit run → submit → certify → file → disclose → reject → resubmit → reopen cascade → audit scrub → fair lending) and an edge-case pass (non-exempt 13-field completeness, exception catalogue ordering `S300,S301,V631,Q615,Q620,Q615`, quota, SoD 403, staling/invalidation, touching-window rules, both defect-rate variants, disparity cap 999.99 → SEVERE/ESCALATED, all 422 date/referential errors).

## Judgment calls worth flagging
- **PRD §2.9's global ladder was treated as authoritative over local §3 prose orderings** where they disagreed: `ERR_EDIT_RUN_INVALIDATED` (409, step 8) fires before `ERR_EDIT_RUN_INSTITUTION_MISMATCH` (422, step 12) on attach; `ERR_INVALID_STAGE_TRANSITION` (step 8) before `ERR_GEOCODE_UNRESOLVED` (step 9) on `DECISIONED → REGISTER_LOCKED`; `ERR_APPLICATION_ARCHIVED` (step 8) before `ERR_SEVERITY_NOT_VERIFIABLE` (step 15) on verify.
- **`lei` format (20-char uppercase alnum) is not enforced** — §2.9 step 5 enumerates type/range/enum/datetime checks but no string formats.
- **Version bumps** follow the scaffold's explicit `side_effects` for `Institution`, and PRD §2.10's general "every cascade-mutated row bumps" rule for all other entities.
- **List ordering** uses an internal monotonic creation sequence rather than the `created_at` value, so ordering stays correct when a test moves the logical clock backwards.

## Step 5: Generate unit tests — 2026-08-25T14:35:00.000Z

Test infrastructure and suite generated and verified.

## Files generated

**`test_helpers/`** (2,435 lines)
| file | lines |
|---|---|
| `__init__.py` | 39 |
| `api_client.py` | 232 (one method per PRD endpoint, incl. `/_clock/set_current_utc`) |
| `api_errors.py` | 116 (all 50 error ids + status map, registered with the framework) |
| `assertions.py` | 370 (per-entity assertions + register-accounting and exception-ledger invariants) |
| `constants.py` | 102 |
| `factories.py` | 206 |
| `fixtures.py` | 826 (7 tiers: primitives → locked records → edit-run scenarios → filing chain → audit scrub → fair-lending populations → superseded pairs) |
| `test_users.py` | 59 (shared constants + per-instance builders; `InstitutionAdmin` is entity-backed) |
| `types.py` | 485 (`CensusTract`/`DisclosureStatement` correctly omit `updated_at`/`version`) |

**`test_suite/`** (4,051 lines, 13 files + conftest, **118 tests**)
`test_01_institution_profile` 10 · `test_02_register_record_capture` 11 · `test_03_capture_stage_workflow` 5 · `test_04_applicant_demographics` 12 · `test_05_geocoding_and_tracts` 10 · `test_06_action_taken_accuracy` 7 · `test_07_edit_battery` 12 · `test_08_filing_submission_lifecycle` 14 · `test_09_filing_and_disclosure` 7 · `test_10_audit_scrub` 13 · `test_11_fair_lending_analysis` 4 · `test_12_access_control` 5 · `test_13_register_cascades_and_invariants` 8

## Coverage per queue
- **Queue A (Difficulty):** 44 tests — all 22 instances across the 9 rules have exactly 2 tests each.
- **Queue B (Corner):** 74 tests — every one of the 75 non-stub instances covered by ≥1 test except the single skip below. The 13 `excluded_because:` stubs were verified to cross-reference real difficulty instances and were not translated.

## Skipped instance (1)
- **`Corner/entities/application_create_with_extra_field_rejected`** — PRD-silence, *unspecified-strictness*. The instance asserts that supplying the system-owned `stage` field in `POST /hmda/applications` returns 400 `ERR_INVALID_REQUEST`. PRD §2.9 step 5 enumerates what body-shape validation checks (required inputs present, enum membership, declared types/ranges, arrays are arrays, ISO 8601 parses, pagination bounds) and never says unknown or system-owned fields are rejected. A faithful PRD-only implementer could equally ignore unrecognised keys, so the outcome is not uniquely derivable.

## Verification performed
- `python3 -m py_compile` on all 23 generated files — clean; `pyflakes` clean (no unused/undefined names).
- `pytest --collect-only` → **118 tests collected**.
- Automated citation audit (script over the AST): every test has exactly one `Design:` tag resolving to a real non-stub instance; every quoted PRD citation survives a whitespace-normalised literal match against `workspace/PRD.md` and is ≥8 words.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no "scaffold"/"§1.x"/"Table N" references leaked into generated code or docstrings.

## Orchestrator audit: withhold-constraint verification — 2026-08-25T14:40:00.000Z

Parsed the Step 4 and Step 6 subagent transcripts, extracting **only `tool_use` block inputs** (never grepping raw text, which always false-positives on the prohibition sentence echoed in the agent's own prompt).

- Step 4 (PRD generator), 73 transcript records: **0** tool calls referencing `SCAFFOLD_*_DESIGN.yaml`, `test_suite`, or `test_helpers`.
- Step 6 (implementation generator), 192 transcript records: **0** tool calls referencing `SCAFFOLD_*_DESIGN.yaml`, `test_suite`, or `test_helpers`.

Both withhold constraints held. Any first-sweep green in Step 7 is therefore not attributable to a design-index leak.

## Step 7: Run tests and iterate — 2026-08-25T14:52:00.000Z

All 8 parallel rounds passed on the first sweep. No fixes or deletions were required.

## Summary

**Iterations run: 1** (single 8-round parallel stability sweep; ~28 min wall time, 8 concurrent runners on runner-allocated ports)

**Result: 118/118 passed in every one of the 8 rounds** — `failed: 0`, `errors: 0`, `skipped: 0` in all of `results.1.json` … `results.8.json`. Union of failing tests across rounds is empty, so there is no flakiness signal to chase.

**Tests deleted:** none. No test failed either PRD coverage (STEP 1a) or unique derivability (STEP 1b), because none failed at all.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### Adjudication of the three flagged judgment calls
The generator's three §2.9-vs-§3 conflicts were audited against verbatim PRD text; the implementation already resolves all three the way §2.9 requires, and each is exercised green in all 8 rounds:

- **Attach edit run** — `routes/submissions.py::attach_edit_run` fires `ERR_EDIT_RUN_INVALIDATED` (§2.9 step 8) before `ERR_EDIT_RUN_INSTITUTION_MISMATCH` (step 12). §2.9 states "the outcome is decided by the first rule to fail in the following strictly ascending order, and no later rule is evaluated. This ordering is observable and is part of the contract," and both errors are named in their respective steps — the global ladder governs over §3.7's narrative order.
- **Lock the record** — `routes/applications.py::advance_application` fires `ERR_INVALID_STAGE_TRANSITION` (step 8, for missing `action_taken` and for a `lar_status` outside `COMPLETE`/`EXCLUDED`) before `ERR_GEOCODE_UNRESOLVED` (step 9, "Cross-entity state guards on advancing a register record").
- **Verify an exception** — `routes/editruns.py::verify_exception` orders `ERR_EXCEPTION_NOT_OPEN` → `ERR_APPLICATION_ARCHIVED` (both step 8) → `ERR_SEVERITY_NOT_VERIFIABLE` (step 15).

### Compliance checks performed
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere in `test_suite/` or `test_helpers/`.
- 118 test functions collected and 118 recorded per round — no silent collection loss.
- `workspace/implementation/` contains no SQLite, file I/O, JSON dump, pickle, or `/tmp` path; `store.py` is pure in-memory dicts and boots empty (no seeding).

### Orchestrator independent verification
- Re-read all 8 `results.N.json` directly: each reports `passed=118, failed=0, errors=0, skipped=0, total=118`.
- Independent grep confirms: no `sqlite3`/`open(`/`pickle`/`shelve`/`/tmp/`/`json.dump(` anywhere in `implementation/*.py`; no `mark.skip`/`skipif`/`xfail` in `test_suite/` or `test_helpers/`; 118 `def test_` functions on disk, matching the 118 recorded per round.

## Step 8: Finalize PRD — SKIPPED — 2026-08-25T14:53:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the tests exercise, so there is no Step 7 diff for Step 8 to patch. `PRD_FINALIZED.md` is intentionally absent; Step 9 starts from `PRD.md`.

## Orchestrator independent confirmation sweep — 2026-08-25T15:20:00.000Z

Ran 2 additional rounds of `prd-bench-local-run --isolation per-test-server` myself, on runner-allocated ports, with results written outside the task tree (scratchpad) so they cannot be confused with Step 7's artifacts.

- independent round 1: `passed=118, failed=0, errors=0, skipped=0, total=118`
- independent round 2: `passed=118, failed=0, errors=0, skipped=0, total=118`

Combined with Step 7's 8 rounds: **10/10 green rounds, 118/118 each**. Together with the zero-hit withhold audit above, the first-sweep green is recorded as genuine (complete PRD), not a design-index leak.

## Step 9: Complete PRD — 2026-08-25T15:32:00.000Z

`workspace/PRD_COMPLETED.md` is written.

**Counts**
- PRD.md: 448 lines / 83,560 chars → PRD_COMPLETED.md: 448 lines / 91,051 chars (**+7,491 chars**, line count unchanged — every change is an in-paragraph replacement; headings and all §4/§5 tables are byte-identical)
- 36 changes on 30 lines: **27 ambiguity-pins**, **9 mismatch-revisions**. No new sections, no new paragraphs.

**Per-change log** (paths relative to `workspace/implementation/`)

- §2.3 — insert — ambiguity — list ordering key is an internal monotonic creation sequence, not the stored `created_at`, so a backwards clock never reorders rows; same key for the §3.6 snapshot and §3.8 population — `store.py:86-88`
- §2.3 — insert — ambiguity — out-of-enum filter values (and non-boolean `is_current`) are `ERR_INVALID_REQUEST` 400 — `validate.py:171-189`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` read the logical clock; only `api_request_timestamp` uses real time — `store.py:59-69`, `response.py:16-18`
- §2.5 — insert — ambiguity — clock endpoint answers 200 with an empty `data` object — `routes/clock.py:333-338`
- §2.9 step 5 — insert — ambiguity — unnamed body fields are ignored, not rejected — `validate.py:73-92`
- §2.10 — insert — **mismatch** — counter recomputation is not a version-bumping mutation: advance, verify, sample draw, demographic record, finding, analysis leave institution `version`/`updated_at` alone; an edit run's counters refresh `updated_at` only, its `version` moving solely on invalidation — `calc.py:125-133`, `store.py:72-83`, `cascades.py:70,77,84`
- §3.1 — insert — ambiguity — `lei` has no length/case/charset check — `routes/institutions.py:22`
- §3.1 — insert — ambiguity — a null in the amendment body is treated as not supplied — `routes/institutions.py:90`
- §3.1 — insert — ambiguity — re-evaluated records bump `version` only when the outcome actually changed — `routes/institutions.py:96-103`
- §3.2 — insert — ambiguity — `uli` uniqueness is tested before this request's supersession applies; `supersedes_application_id` is existence-resolved only (any institution, any stage) — `routes/applications.py:68-76`
- §3.2 — revise — **mismatch** — `DECISIONED → REGISTER_LOCKED` order is `action_taken`, then `lar_status` (both `ERR_INVALID_STAGE_TRANSITION`), then geocode — `routes/applications.py:163-170`
- §3.2 — insert — ambiguity — advance out of `ARCHIVED` yields `ERR_INVALID_STAGE_TRANSITION`; advance leaves institution `version`/`updated_at` untouched — `routes/applications.py:171-177`
- §3.2 — insert — ambiguity — an amendment null clears the field, except `denial_reason_codes` (→ `[]`) and `business_or_commercial_purpose` (→ false); both versions bump regardless of change — `routes/applications.py:125-135`
- §3.2 — revise — **mismatch** — the `ERR_APPLICATION_ARCHIVED` set is exactly four writes; geocoding, findings and corrections are still accepted, advance/reopen surface as `ERR_INVALID_STAGE_TRANSITION` — `routes/applications.py:122,186`, `routes/demographics.py:133`, `routes/editruns.py:259`
- §3.2 hop 1 — revise — **mismatch** — reopening an `EXCLUDED` locked record leaves it `EXCLUDED`, not `PENDING_FIELDS` — `calc.py:109-113` via `cascades.py:93`
- §3.2 hop 2 — revise — **mismatch** — the run's `cleared_record_count` falls only if the record was among those it had cleared — `cascades.py:73-78,116-123`
- §3.2 hop 3 — insert — ambiguity — every non-invalidated run of the institution whose snapshot held the record is invalidated, verified exception or not — `cascades.py:116-127`
- §3.3 — insert — ambiguity — recording a demographic row leaves the parent record and institution counters untouched and carries no stage precondition — `routes/demographics.py:87-124`
- §3.3 — insert — ambiguity — merged nulls are ignored except `age_years` (clearable); re-amending an `AMENDED` row is accepted and still bumps `version` — `routes/demographics.py:143-161`
- §3.4 — insert — ambiguity — tract code/FIPS/state/MSA fields are stored unvalidated — `routes/census_tracts.py:269-278`
- §3.4 — insert — ambiguity — address fields and `submitted_tract_code` unvalidated; geocoding has no stage precondition (archived records included) — `routes/geocodes.py:178-187,195-230`
- §3.4 — insert — ambiguity — the superseded previous assignment's own `version` increments by 1 — `routes/geocodes.py:223-226`
- §3.5 — insert — ambiguity — no stage precondition beyond archival; an existing action may be overwritten; omitted companions merge from the stored row and the referential rules run on the merged value — `routes/applications.py:181-223`
- §3.6 — revise — **mismatch** — verify precedence is `ERR_EXCEPTION_NOT_OPEN` → `ERR_APPLICATION_ARCHIVED` → `ERR_SEVERITY_NOT_VERIFIABLE` — `routes/editruns.py:253-264`
- §3.6 — revise — **mismatch** — a snapshot record drawing no edit is written to `CLEARED` from any prior value, `PENDING_FIELDS` included — `routes/editruns.py:187-191`
- §3.7 — revise — **mismatch** — attach checks run status (`ERR_EDIT_RUN_INVALIDATED`) before institution ownership — `routes/submissions.py:91-99`
- §3.7 — insert — ambiguity — a superseded draft gets `updated_at` refreshed but no `version` increment — `routes/submissions.py:44-47`
- §3.7 — insert — ambiguity — `rejection_reason` is optional and null when omitted; ignored on acceptance — `routes/submissions.py:29,223`
- §3.7 — insert — ambiguity — acceptance also increments the institution's `version`, and leaves published statements in place — `routes/submissions.py:216-220`
- §3.7 — insert — ambiguity — records with no geocode assignment at all join the no-tract suppression group — `calc.py:304-308`
- §3.8 — insert — ambiguity — the remediation-overlap scan spans every sample, not just this one — `routes/audits.py:143-147`
- §3.8 — insert — **mismatch** — the four finding refusals evaluate in §2.9 ladder order (`SAMPLE_NOT_OPEN`, `FINDING_APPLICATION_NOT_IN_SAMPLE`, `INVALID_WINDOW`, `REMEDIATION_WINDOW_OVERLAP`), not the order the prose lists them — `routes/audits.py:129-147`
- §3.8 — insert — ambiguity — every finding bumps the sample's `version` regardless of status movement, and touches neither record nor institution — `routes/audits.py:164-167`
- §3.8 — insert — ambiguity — `defect_rate_basis` is recorded on a `CLOSED_CLEAN` close too — `routes/audits.py:181-186`
- §3.8 — insert — ambiguity — each finding moved to `ACCEPTED_AS_IS` has its `version` incremented — `routes/audits.py:191-194`
- §3.9 — insert — ambiguity — group codes are not validated against the `basis` code set; a universe record with no `APPLICANT` row belongs to neither group — `routes/fairlending.py:216-238,257-258`

Confirmed against the flagged spots: (a) all three §2.9-vs-§3 precedence conflicts are now pinned in §3.2/§3.6/§3.7 (plus a fourth found in §3.8), (b) `lei` format is now explicitly unenforced, (c) the version-bump rule is pinned in §2.10 where impl diverges from the blanket cascade rule, (d) the creation-sequence ordering key is pinned in §2.3 and referenced for §3.6/§3.8.

### Orchestrator verification
- `wc -l`: PRD.md 448 / PRD_COMPLETED.md 448.
- `diff` over headings and table rows only: **byte-identical** — no section was added, removed, or renamed, and §4 (46 endpoints) / §5 (50 errors) tables are untouched.
- 30 lines differ between the two files, consistent with 36 in-paragraph changes.

## Pipeline complete — 2026-08-25T15:33:00.000Z

All 9 steps done (Step 8 skipped by its documented skip condition). Final state: 118/118 tests passing across 10 independent rounds; `PRD_COMPLETED.md` is the shipping contract.
