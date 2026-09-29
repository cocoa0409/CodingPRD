## Step 1: Create task directory — 2026-09-05T11:41:12.896431733Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2888_tourism_improvement_district_administration and its workspace/ subdirectory. Index 2888 was pre-assigned by the invocation (no auto-allocation scan performed, per instructions, to avoid collision with the other concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T14:14:28Z

Step 2 is complete. All three scaffold artifacts are written and the skill's linter passes.

## Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3423 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1834 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4712 |

Lint verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     69
  Calls scanned (§1.8+§1.9):  1713

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

`SCAFFOLD.yaml` holds exactly 13 top-level keys with no `scaffold_difficulty_design` / `scaffold_corner_design` leak; the difficulty directive appears nowhere in any YAML. `worklog.md` (untouched, Step-1 entry only) and `workspace/` are intact; scratch files live only in `workspace/scratch_step2/`.

## Domain model

12 entities: District, LodgingBusiness, PetitionDrive, PetitionSignature, AssessmentPeriod, AssessmentStatement, Remittance, AssessmentDispute, AnnualWorkPlan, MarketingProgram, RoomNightClaim, TransparencyRecord. 63 endpoints, 57 error codes, 7 roles (DistrictAdministrator, BoardMember, LodgingOperator — `entity_backed:LodgingBusiness`, DmoLiaison, HearingOfficer, IndependentAuditor, PublicViewer) under a segregation-of-duties role model. complexity_profile: compliance_audit / multi_party_negotiation, layers [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers], graph topology, parallel state machines, immediate consistency. Three calculations (assessment_amount with PROVISIONAL/FINAL variants over four methods, delinquency_charges, program_performance) plus petition_support, work_plan_compliance, remittance_waterfall and payment_status_derivation; a 13-rung §1.4 priority ladder (10 auth → 90 business_fiscal) and two §1.2.1 concurrency rules (statement amendments, work-plan amendments).

## §1.8 (9 rules, 22 instances)

dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant — e.g. a four-hop delinquency cascade (charges → strike → SUSPENDED → signature disqualification → drive re-score), a granted dispute that walks funding_ratio into a frozen marketing program, priority inversions where a certified statement outranks a closed filing window, and half-open interval overlap on periods and room-night stays.

## §1.9 (9 sections, 94 instances: 69 with full recipes, 25 `excluded_because` stubs)

entities, state_machines, calculations, validations, endpoints, errors (all 57 codes indexed to a triggering instance), rbac (wrong-role/right-role pairs, shared operator+administrator authority with ownership still binding, unknown operator identity refused before path resolution, two auditor/administrator SoD pairs, PublicViewer barred from the roll), cross_cutting_complexity_layers (one stale-version instance per §1.2.1 rule — 412 ERR_STALE_STATEMENT_VERSION after a hearing officer's ADJUSTED resolution bumps the row, and 412 ERR_STALE_WORK_PLAN_VERSION after an automatic APPROVED→AMENDMENT_PENDING bump — plus version-increments-on-every-write and a purpose-built "Lien Ridge" fixture where outstanding 1,000,000 vs 999,999 straddles LIEN_REFERRAL_THRESHOLD_CENTS at identical penalty/interest), and consistency_model (filing and remittance responses already carry every derived total, with the public financial summary agreeing on the first read).

All asserted literals were recomputed with Decimal ROUND_HALF_UP. Fixes made along the way: seven `difficulty_instance` citations used stale rule ids and now resolve, and one not-found probe that hardcoded `expected_work_plan_version: 1` was re-pointed at `POST /annual-work-plans/{id}/board-actions` (no OCC field), which is what cleared the last lint violation.

Orchestrator verification: all three files parse as YAML; SCAFFOLD.yaml top-level keys are exactly the 13 §1.0–§1.7 keys; `grep -ri "harder than expert"` over the whole task dir returns nothing, so the difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-05T14:14:36Z

Copied project-root INSTRUCTION.md to workspace/INSTRUCTION.md (%s bytes).

## Step 4: Generate PRD — 2026-09-05T14:32:45Z

**Output:** `workspace/PRD.md`

**Line count:** 529 lines (116,381 bytes), written in 9 successive `cat >>` appends, plus two targeted `Edit` fixes for coverage gaps. No single-Write truncation risk was taken.

**Last two lines, verbatim:**
```
| `ERR_REMITTANCE_EXCEEDS_TOTAL_DUE` | 409 |
| `ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT` | 409 |
```
The document ends at a real boundary — the final row of the §5 error-code table. Every section-append boundary was inspected and each ends on a completed paragraph.

**Structure:** §1 Introduction; §2.1–§2.12 (RBAC, the verbatim §2.2 response envelope, pagination, logical clock, common resource properties, money/rounding, stale-version rejection, a 13-rung validation ladder, nested reads, cascade discipline, segregation of duties, the conserved collection identity); §3.1–§3.9 (district roll; petition circulation and tally fork; assessment periods, statement generation and the filing dimension; the remittance waterfall and payment dimension; delinquency enforcement; disputes; the annual work plan; marketing programs and two-pass performance; transparency obligations); §4 endpoint table; §5 error table.

**Mechanical coverage check (all run against the finished file):**
- Endpoint paths: **63/63** found; §4 table has exactly 63 rows, all 4-column.
- Error IDs: **57/57** found in prose *and* 57 rows in §5, all 2-column.
- Entity type names: **12/12**. Roles: **7/7**.
- Entity field names (Contract 1): **148/148** present verbatim in backticks.
- Endpoint `input`/`query_params`/`path_params` identifiers (Contract 1): **85/85**.
- State machines: 68 declared transitions across 13 machines, all 52 distinct state values present; every enum value declared in any entity constraint appears in backticks.
- Contract 3 (§3 path purity): **0 violations**. §2.2 is byte-identical to the doc-generator's canonical section-2.2 file. No fuzzy quantifiers.

**Two coverage gaps found and fixed:** `marketing_program_id` was never named (added to the claim-creation paragraph in §3.8), and the twelve canonical resource-type names were only present in prose form (added parenthetically in backticks to the §2.5 enumeration).

**Scaffold conflicts resolved (worth knowing for later steps):**
- Where a state machine's `actor` disagrees with the endpoint's `roles` list, the endpoint `roles` won (e.g. claim verification is `DmoLiaison`/`DistrictAdministrator`, not `IndependentAuditor`; district certification/disestablishment is `DistrictAdministrator`, not `BoardMember`). §2.1 states that the §4 table is authoritative for the role check.
- `AnnualWorkPlan` `RETURN`: the state machine says `sponsor_user_id := null` while the endpoint says it increments `revision_count`. Both were written in.
- `AnnualWorkPlan` `CLOSE`: the state machine's precondition (every program already `CLOSED`/`CANCELLED`) was taken as normative, which makes the endpoint's "closes its RUNNING programs" side-effect vacuous; the PRD states the precondition only.
- `assessment_revenue_forecast_cents`: merged the field's `filing_status` filter with the calculation's `FY<fiscal_year>` period-label scope, and stated "regardless of `payment_status`".
- Statement-amendment variance (25%) and `MAX_AMENDMENTS` (3) have no dedicated error id in the scaffold, so they are specified as preconditions reported at the state rung with `ERR_INVALID_STATE_TRANSITION`; same treatment for the strict grace-deadline gate on the delinquency sweep and for reversal against a `CERTIFIED` statement.

Only `workspace/PRD.md` was written; the two withheld design indices were never opened.

Orchestrator verification (independent): 529 lines / 116,381 bytes; tail ends on a complete error-table row (real section boundary, not mid-sentence); re-extracted all 57 error ids and all 63 endpoint paths from SCAFFOLD.yaml and grepped each in PRD.md — 0 missing. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T15:34:19Z

(Steps 5 and 6 were launched concurrently; Step 6 returned first, so it is logged first. The Step 5 entry follows below.)

Implementation complete and verified.

## Files (all under `workspace/implementation/`)

| file | lines |
|---|---|
`services/core.py` | 381
`routes/districts.py` | 349
`routes/statements.py` | 296
`routes/programs.py` | 276
`serialize.py` | 259
`routes/petitions.py` | 254
`routes/periods.py` | 242
`services/plans.py` | 221
`validate.py` | 212
`routes/workplans.py` | 211
`store.py` | 192
`routes/businesses.py` | 190
`routes/disputes.py` | 176
`config.py` | 173
`routes/transparency.py` | 122
`envelope.py` | 102
`errors.py` | 80
`auth.py` | 79
`app.py` | 74
`routes/clock.py` | 38
`routes/common.py` | 20
`start.sh` | 10
`requirements.txt` | 1 (`Flask==3.1.3`)
**total** | **3958**

`routes/__init__.py` and `services/__init__.py` are empty. `python3 -m compileall` passes on every module; `__pycache__` removed afterwards, so the tree holds only source.

## Coverage (mechanically checked against PRD.md)

- **Endpoints: 63 declared / 63 implemented, 0 missing, 0 extra** (method+normalised-path set equality against the PRD's request tables).
- **Error codes: 57 declared / 57 raised somewhere in code, 0 never-raised, 0 unknown**, and `errors.py`'s status map matches the PRD's HTTP column for all 57 (**0 mismatches**).
- 7 roles in `config.ALL_ROLES`; ten public reads accept no headers; `LodgingOperator` identity is entity-backed via `require_owner`.

## Smoke test (own port 39288, own PID, killed by PID)

Boot 1 (PID 3345318) exercised ~55 calls end-to-end. Envelope matched §2.2 everywhere: `meta.api_request_id` = `req_` + 20 alnum, `api_request_timestamp` with exactly 3 fractional digits, `response_type` `object`/`array`/`error`, errors carrying `{error_id,message}` inside `data`, list `meta` carrying `limit`/`offset`/`total_count`/`has_more`.

Highlights, all as specified:
- Creates: district 201 `PROPOSED` v1; 3 businesses → district `assessable_business_count` 3 / `assessable_basis_cents` 30000000 v4; FORMATION drive; 3 signatures; tally `QUALIFIED` `weighted_support_pct` 1.0; certification → district `FORMED` (`expiration_date` 2031-08-01) → `ACTIVE`.
- Rejections: blank name 400 `ERR_INVALID_REQUEST`; `PublicViewer` POST 403 `ERR_FORBIDDEN_ROLE`; no headers 401; unknown id 404 `ERR_DISTRICT_NOT_FOUND`; `limit=0` 400; `ERR_PERIOD_OVERLAP`, `ERR_STATEMENT_ALREADY_EXISTS_FOR_PERIOD`, `ERR_DUPLICATE_SIGNATURE`, `ERR_NOT_RESOURCE_OWNER`, `ERR_DISPUTE_ALREADY_OPEN`, `ERR_CLAIM_OUTSIDE_BOOKING_WINDOW`, `ERR_CLAIM_STAY_OVERLAP`, `ERR_CLAIM_EXCEEDS_CAPACITY` (both create and verify arms), `ERR_CLAIMS_PENDING_VERIFICATION`, `ERR_PROGRAM_BUDGET_EXCEEDED`, `ERR_DMO_AGREEMENT_NOT_EXECUTED`, `ERR_MEETING_SEPARATION_VIOLATION`, `ERR_MEETING_NOTICE_TOO_LATE`, `ERR_ADMIN_SHARE_EXCEEDED`, `ERR_AMENDMENT_VARIANCE_EXCEEDED`, `ERR_SEGREGATION_OF_DUTIES` (plan sponsor≡approver), `ERR_REMITTANCE_EXCEEDS_TOTAL_DUE`, `ERR_REMITTANCE_ALREADY_REVERSED`.
- **OCC, both endpoints**: `expected_statement_version` 1 vs 4 → **412** `ERR_STALE_STATEMENT_VERSION`; `expected_work_plan_version` 1 vs 5 → **412** `ERR_STALE_WORK_PLAN_VERSION`.
- **Waterfall**: file 10000000 revenue → assessment 200000; pay 250000 → `applied_to_principal` 200000 / `applied_to_credit` 50000, statement `REFUND_DUE`. Reversal restored it exactly (`UNPAID`, principal 0, credit 0, due 200000) and the period's collected total with it.
- **Sweep 4-hop cascade**: period `OPEN`→sweep refused `ERR_INVALID_STATE_TRANSITION` (per §3.5, not `ERR_PERIOD_NOT_CLOSED`); after closure, sweep at clock 2026-10-05 with grace deadline 2026-09-25 → 10 days late, outstanding 220000 → penalty 22000, interest 1100, stage `NOTICE`, statement `DELINQUENT` due 243100, business strike 1 / `WATCH`, district `delinquent_charges_cents` 23100, period `DELINQUENCY_SWEPT`.
- **Dispute 3-hop cascade**: role split enforced as authz (operator `OPEN_REVIEW` → 403; officer `WITHDRAW` → 403); uncapped info cycle; `ADJUSTED` 50000 → statement `granted_adjustment` 50000, effective 170000, due 193100 (hop 1); plan forecast 170000, ratio 0.8500 → `APPROVED`→`AMENDMENT_PENDING` (hop 2); hop 3 no-op only because the sole program was already `CLOSED`.
- **Program measurement**: committed 100000, verified 80 nights → gross CPRN 1250, `TIER_EFFICIENT`, DMO share 40000, net 60000, net CPRN 750, index 3.3333, `MEETS_BENCHMARK`.
- **Clock cascade**: advancing past a `NOTICED` meeting's `required_by` flipped it to `OVERDUE` and re-derived district standing (stayed `COMPLIANT` — correct, `PUBLIC_MEETING` is outside the `ANNUAL_REPORT`/`FINANCIAL_AUDIT` standing set).
- **Plan amendment then board CLOSE**: amendment → `APPROVED`, budget 176000, ratio 0.9659, `revision_count` 1; `CLOSE` → `CLOSED` v7.

## Confirmations

- **B (no seeded data)**: an AST scan finds no module-level `put()`/`new_record()` anywhere; a grep for `sqlite3`, `shelve`, `pickle`, `open(`, `json.dump/load`, `/tmp`, `os.path`, `pathlib`, `atexit` returns **zero hits** in the whole implementation. Storage is 12 plain dicts on `store.state`, all cleared by `reset()`. Verified empirically: after `kill` and re-boot, `GET /districts` returned `total_count` 0 / `data` [], and the previous district id returned 404. No file was created by either boot.
- **D (start.sh contract)**: `set -euo pipefail`, `cd "$(dirname "$0")"`, installs Flask only if the import fails (an unconditional `pip install` causes boot contention across the 8 concurrent sweep rounds), then `exec python3 app.py`. `app.py` binds `0.0.0.0` on `int(os.environ["PORT"] or 10000)`, `debug=False`, `use_reloader=False`, `threaded=True`, foreground, no `&`/nohup.
- **F (safe smoke test)**: only `kill 3345318` and `kill <PID2>` were used — no `pkill`, no `killall`, no pattern matching. Port 39288 confirmed free after each kill. Second boot verified fresh. Logs and JSON captures live in `workspace/scratch_step6/`; nothing scratch, log, or pid remains inside `implementation/`.

## PRD ⟂ SCAFFOLD conflicts (PRD won every time)

1. Statement amendment 25%-deviation and the 3-revision cap → `ERR_INVALID_STATE_TRANSITION` (PRD line 232). The scaffold pointed both at `ERR_AMENDMENT_VARIANCE_EXCEEDED`, which the PRD reserves for **work-plan** amendments.
2. Transparency `PUBLISHED` with a missing `document_reference`: PRD §2.8 puts it at rung 4 (`ERR_INVALID_REQUEST`); the scaffold's precondition list ordered it after the status check.
3. Program `verified_room_nights` on a `REJECT` decision uses `set_if_changed`, so a rejection that changes nothing does not bump the program version — the scaffold's side-effect text says it always increments.
4. `spend_frozen` clearing on disestablishment scoped to an `ACTIVE` origin (PRD §3.2 vs §3.8).
5. Scaffold's forecast omits the filing-status filter the PRD requires (`FILED|AMENDED|AUDITED|CERTIFIED`).
6. Scaffold board `CLOSE` "closes RUNNING programs"; PRD requires every program already `CLOSED`/`CANCELLED`.
7. Scaffold `actor: BoardMember` on several district lifecycle transitions vs PRD `DistrictAdministrator`.
8. Scaffold claim-verification actor `IndependentAuditor` vs PRD `DmoLiaison, DistrictAdministrator`.
9. Scaffold's `SUBMITTED→VERIFIED` "program RUNNING" guard is absent from the PRD.
10. Scaffold lists `ERR_BUSINESS_OUTSIDE_BOUNDARY` on room-night claims; PRD §3.8 enumerates only three claim rules.
11. PRD §3.2 vs §3.9 on scoping the renewal transparency gate to `current_fiscal_year` — scoped.
12. Activation with an assessable pool below 3 reports `ERR_INVALID_STATE_TRANSITION`, since the scaffold scopes `ERR_PETITION_POOL_TOO_SMALL` to tally/certification.
13. Program launch on a non-`ACTIVE` district: terminal → `ERR_DISTRICT_NOT_ACTIVE`, non-terminal-but-not-`ACTIVE` → `ERR_INVALID_STATE_TRANSITION` (the scaffold scopes `ERR_DISTRICT_NOT_ACTIVE`'s `applies_to` to the five creates).
14. Duplicate non-`CLOSED` work-plan fiscal year → `ERR_INVALID_REQUEST`; no dedicated code exists.

One design note worth flagging for the test suite: caller-supplied instants are echoed verbatim (`"2026-09-01T00:00:00Z"`), while server-stamped instants render canonically with exactly 3 fractional digits — PRD §2.5 mandates the 3-digit form only for `created_at`/`updated_at` and the other system-stamped fields.

## Step 5: Generate unit tests — 2026-09-05T16:24:27Z

Step 5 is complete. Final state and verification below.

## Output locations (item A — confirmed)
Both directories are siblings of `workspace/`, at the task root: `test_helpers/` and `test_suite/`.

`ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation`, `scratch_step2`, `scratch_step4`, `scratch_step5`, `scratch_step6`; a `find` over `workspace/` returns no `test_helpers` or `test_suite` anywhere. `worklog.md`, the three `SCAFFOLD*.yaml` files, `workspace/PRD.md`, `workspace/INSTRUCTION.md` and `workspace/implementation/` were never written to or read (implementation deliberately unread). Scratch stayed in `workspace/scratch_step5/`. `__pycache__`/`.pytest_cache` removed. No process was killed.

## Line counts
test_helpers (3,192 lines): `fixtures.py` 753, `types.py` 546, `api_client.py` 541, `factories.py` 505, `assertions.py` 415, `api_errors.py` 150, `constants.py` 150, `test_users.py` 119, `__init__.py` 13.

test_suite (7,692 lines): `conftest.py` 89, `test_01` 212, `test_02` 382, `test_03` 218, `test_04` 322, `test_05` 278, `test_06` 415, `test_07` 300, `test_08` 277, `test_09` 275, `test_10` 547, `test_11` 511, `test_12` 726, `test_13` 552, `test_14` 296, `test_15` 473, `test_16` 531, `test_17` 252, `test_18` 452, `test_19` 430, `test_20` 154.

## Tests emitted
**133 tests**, all collected cleanly (`pytest --collect-only` → 133, 0 errors), pyflakes clean over both directories.

## Design-index coverage
- **§1.8 (queue A, difficulty): 22 live instances, 22 translated, 0 skipped** → 65 tests (tests 01–09).
- **§1.9 (queue B, corner): 69 live instances (26 stubs excluded by the yaml itself), 68 translated, 1 skipped** → 68 tests (tests 10–20). Per section: entities 13, state_machines 9, calculations 9, validations 8, endpoints 4, errors 13, rbac 6, cross_cutting_complexity_layers 4, consistency_model 2.
- Only skip: `Corner/endpoints/one_signature_is_reachable_from_the_drive_side_and_from_the_property_side` — the instance's assertions turn on a `status` filter on `/petition-drives/{id}/signatures` and `/lodging-businesses/{id}/petition-signatures`, and the PRD declares no such filter on either row (§4 lines 414/419, §3.2), so the filtered outcomes are not PRD-derivable.

Audit results: every test docstring ends in exactly one `Design:` line, 90 distinct tags, **0 dangling tags**, no docstring or comment mentions "scaffold". All PRD citations re-checked verbatim against `workspace/PRD.md` after backtick/asterisk/arrow normalisation; the 17 checker flags were all artifacts (multi-quote citations, §4 table-row pipes, and quotes truncated to a period mid-sentence).

## Item F — re-verified
1. No money literal is a string, `Decimal` or `float` anywhere in `factories.py`. 2. No date-only ISO literal exists in either directory (every instant carries `T…Z`). 3. `api_client.canonical_instant` normalises sub-second width and is what `assert_instant_equals` compares through. 4. No `["data"]` appears in either directory — `validate_success` output is used directly. 5. Blank-header users are built with `""` (`EMPTY_USER_ID`, `EMPTY_ROLE`), never whitespace. All state is built through declared endpoints only; no test relies on seeded data or on another test (item G: base URL comes from `API_BASE_URL`/`API_URL`/`BASE_URL` with a localhost default).

## Deviations worth flagging to Step 7
Setup-only deviations where a design recipe contradicted the PRD (assertions kept intact): a second work plan uses FY2028 because PRD 327 forbids two live plans on one year; the pool-too-small drive is built from three properties with one exempted because PRD 188 needs `assessable_business_count` >= 3 to open a drive; program `verified_room_nights` is asserted 0 rather than null at creation (PRD 357); the renewal-drive listing is asserted unfiltered because PRD 409 declares no `drive_type` filter. In `test_19` the two work-plan `version` integers from the recipe conflict with PRD 2.5/2.10 (a derived-field recompute is itself a mutation), so that test asserts the staleness relationally (`pending.version > approved.version`, then `refused.version + 1`) instead of hardcoding 3 and 4; every other figure in it is pinned exactly.

## Step 7: Run tests and iterate — 2026-09-05T16:56:31Z

Task complete — a full 8-round parallel sweep is green.

## Summary

**Iterations run:** 2 (sweep → diagnose → fix → sweep).

Iteration 1 produced 6 failures, identical in all 8 rounds (127/133 each) — all deterministic, no load-induced flakiness, and no `Terminated` in any server log.

**Tests deleted:** none. All 133 tests remain.

**Fixes applied to `test_suite/`:**
- `test_18_role_and_identity_boundaries.py` — `test_the_operator_files_only_its_own_statement_while_the_administrator_files_any`: dropped `expected_status=201` on two `file_statement` calls. `POST /assessment-statements/{id}/filings` creates no resource (PRD §2.5 lists exactly twelve persisted types; "filing" is not one), so PRD §4's "every other successful call returns HTTP 200 with the affected resource" applies. 28 of the suite's 31 filing call sites already expected 200.
- `test_20_write_visibility.py` — `test_the_filing_response_already_carries_every_total_the_next_read_returns`: same 201→200 correction.
- `test_12_calculation_branches.py` (2 sites) and `test_14_endpoint_surfaces.py` (2 sites): added `headers=ADMIN` to `get_lodging_business` calls that sent no headers. `GET /lodging-businesses/{id}` is not among the ten public reads enumerated in PRD §2.1, so the implementation's `ERR_UNAUTHENTICATED` was correct — a test bug, not an implementation one.
- `test_19_versioning_and_thresholds.py` — `test_three_revisions_of_one_property_advance_its_version_on_every_write`: STEP 1c partial-coverage split. Kept every `version` assertion (verbatim in PRD §2.5); removed the 7 assertions that `created_at`/`updated_at` equal the logical clock instant, replaced with `assert_common_fields`. PRD §2.5 pins the *shape* of those two fields but never says they are stamped from the logical clock, whereas every field that is (`filed_at`, `signed_at`, `opened_on`, `tallied_at`, `noticed_on`, …) says so explicitly in §3 — so the concrete instant is not uniquely derivable. The wall-clock reading is in fact the better-supported one: PRD calls `created_at` ordering normative and "observable" for statement generation and the sweep, which is undefined if every record minted under a frozen clock shares one timestamp.

**Fixes applied to `test_helpers/`:** none needed — no shared fixture bug was implicated.

**Fixes applied to `implementation/`:**
- `routes/disputes.py`, `resolve_dispute`: moved the `resolved_by_user_id` / `resolution_note` writes out of the pre-validation path and onto each success branch. The handler was stamping them before the `granted_adjustment_cents` bound checks, so a resolution refused with `ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT` left the hearing officer's id persisted on an `UNDER_REVIEW` dispute — a genuine side effect on a rejected request, contrary to PRD §2.8's ladder and §3.6's "Both *outcomes* record `resolved_by_user_id`".

**Final sweep evidence** (completed 2026-09-05T16:46:25Z, 238s per round):

| round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 133/133 | 133/133 | 133/133 | 133/133 | 133/133 | 133/133 | 133/133 | 133/133 |

`worklog.md` was not read or modified (mtime still 16:24, predating this step). No stray worklogs, and PRD/INSTRUCTION/SCAFFOLD files are untouched.

**Orchestrator independent verification:** re-read all 8 `results.$i.json` after the agent exited — every round reports passed 133 / total 133, failed 0, errors 0; `workspace/SWEEP_DONE` carries 2026-09-05T16:46:25Z; no `round.$i.log` contains `Terminated` (so the sweep was not reaped); `test_suite/` still defines 133 test functions; `worklog.md` mtime confirms the agent never touched it. Step 7 made 1 `implementation/` fix, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-05T17:07:26Z

Done. `PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 529 lines / `PRD_FINALIZED.md`: 529 lines — **0.0% line delta** (3 in-place line revisions, 6 lines touched; no new sections, no reflow).

## Changes (one per bullet)
- **§2.5, `created_at` / `updated_at` bullets** — *revise* — pinned both stamps to the server's **real wall-clock time** (explicitly not the §2.4 logical clock), and pinned that an unmutated record's `updated_at` equals its `created_at` — `implementation/store.py:78,145-149,165`.
- **§3.6, resolution paragraph** — *revise* — pinned that `resolved_by_user_id` / `resolution_note` are written **only on a reached outcome**, so a refused resolution (including the three granted-figure bounds) leaves `status`, `resolved_by_user_id`, `resolution_note`, `granted_adjustment_cents`, `updated_at` and `version` untouched — `implementation/routes/disputes.py:126-156`.
- **§4 preamble** — *revise* — defined "creation endpoint" as one that persists a brand-new record of a §2.5 type and enumerated the exactly twelve that answer 201; noted statement-generation's 201-with-summary; pinned that every other write endpoint answers 200 regardless of how plural its path noun is, naming `/filings` explicitly — `implementation/envelope.py:16,25-26` plus the 12 `envelope.created(...)` sites vs. `routes/statements.py:99`.

## Per-edit pre-edit search log

**Edit 1 — subject: the instant source of `created_at`/`updated_at`.**
(b) Enumerated/read: `store.py` in full (`wall_now`, `new_record`, `touch`, `set_if_changed`, `iso3`, `sorted_records`, `clock`); `grep -rn "wall_now|created_at|updated_at"` over the whole tree (only writers are `store.new_record` and `store.touch`; only other `wall_now` consumer is `envelope.py:12` `api_request_timestamp`); `grep -rn "store.clock()"` over all routes to confirm every workflow instant (`filed_at`, `signed_at`, `tallied_at`, `filed_on`, `reversed_on`, `closed_at`, `approved_at`) comes from the logical clock, verifying `signed_at` at `routes/petitions.py:130,154`; `grep -rn "touch(rec)|begin_request"` plus `routes/periods.py:22-53` (`new_statement`) to confirm no freshly created record is `touch`ed in its creating request, which is what makes the equality claim safe.
(c) Adjustment: dropped a draft clause "and neither moves when the clock is set" — false, because `routes/clock.py:30` `touch`es transparency records swept to `OVERDUE`, moving their `updated_at`. Also kept the workflow-field list open-ended ("and the rest") rather than claiming exhaustiveness.

**Edit 2 — subject: HTTP status code of write endpoints.**
(b) Enumerated/read: every `@bp.post` and every `return envelope.*` across all of `routes/` (single grep, full output reviewed); `envelope.py:16-36` (`ok`, `created`, `paginate`); `routes/periods.py:126-159` to confirm statement-generation returns 201 with a summary dict, not a resource; `routes/clock.py:38` for the `{}` 200; `routes/statements.py:75-99` for the filings 200.
(c) Adjustments: two. Added the explicit statement-generation carve-out because its 201 `data` is not a resource, so the unqualified "201 with the created resource" would have mis-described it. Then widened the illustrative verb list ("records against", "or otherwise mutates") and added an explicit `POST /_clock/set_current_utc` sentence, because `/districts/{id}/dmo-coordination` and the clock endpoint fell outside my first verb list and would have been left ambiguous or mis-described as returning "the updated resource".

**Edit 3 — subject: writes performed by `POST /assessment-disputes/{id}/resolution` on a refused request.**
(b) Enumerated/read: `routes/disputes.py` in full — `create_dispute` (initial `resolved_by_user_id`/`resolution_note` null), `advance_dispute` (confirmed `APPEAL` clears only `resolved_by_user_id`, not `resolution_note`, at line 100), `resolve_dispute` lines 111-181 (no dispute write precedes any `fail`, `touch(dispute)` only on a success branch); `validate.py` in full to confirm every validator and every `_lookup` is pure; `services/core.py:112` `statement_of_dispute` (pure read); `store.py` `touch` to confirm `version`/`updated_at` move only via `touch`.
(c) Adjustment: scoped the sentence strictly to the resolution endpoint and said nothing about `resolution_note` on the `APPEAL` path, since `routes/disputes.py:100` clears only `resolved_by_user_id` — a "cleared on appeal" phrasing covering both fields would have been a brand-new mismatch.

## Not patched (deliberate)
The `GET /lodging-businesses/{id}` Step 7 fix needs no PRD change: §2.1 already enumerates the ten public reads and states "Every other operation in the API requires both headers", and the §4 row lists five roles. That item was a pure fixture bug (`routes/businesses.py:31`). Likewise the two 201→200 test corrections are covered by the single §4 edit.

## Truncation check
Not truncated — `PRD_FINALIZED.md` ends at a real section boundary, the last row of the §5 error table.

No files other than `workspace/PRD_FINALIZED.md` were created or modified.

**Orchestrator independent verification:** `diff PRD.md PRD_FINALIZED.md` shows 8 changed lines (3 revised passages), 116,381 → 118,873 bytes, both 529 lines; the file is NOT byte-identical (correct — Step 7 made one `implementation/` fix, so Step 8 was required); tail is the final §5 error-table row; `PRD.md` mtime unchanged at 14:30.

## Step 9 pass 1 of 3: PRD completeness scan — cross-cutting/infrastructure modules — 2026-09-05T17:49:31Z

Orchestrator note: Step 9 was deliberately run as THREE SEQUENTIAL passes over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module. A single agent asked to scan all 3958 implementation lines against a 529-line PRD reliably under-covers and can return a byte-identical file. Pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from copying and edited in place.

Partition: app.py, config.py, store.py, envelope.py, errors.py, auth.py, validate.py, serialize.py, routes/common.py, routes/clock.py.

Pass 1 complete. All structure verified intact.

## Confirmation of the copy
`cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` was performed by me as Step 0, before any edit. No later re-copy.

## Line counts / delta
| file | lines | chars |
|---|---|---|
| `PRD_FINALIZED.md` | 529 | 118,873 |
| `PRD_COMPLETED.md` | 530 | 128,223 |

Char delta **+9,350**; one line added (a new bullet in §2.2's error-format list). 19 lines touched. Structural invariants re-verified: 29 headings, 57 error-table rows, 63 endpoint rows — all unchanged. §3 and §4 completely untouched, so passes 2/3 inherit pristine sections.

## Counts
**16 ambiguity-pins, 1 mismatch-revision** (§2.2's "4xx status codes" claim, which the framework paths falsify).

## Changes
- §2.1 — revise — ambiguity — public reads: an absent/empty `X-User-Role` is served anonymously whatever `X-User-ID` says; a *non-empty* role is still list-checked, and an unrecognized role name fails 403 `ERR_FORBIDDEN_ROLE` (not 401, since `ERR_UNAUTHENTICATED` is unavailable) — `auth.py:37-52`
- §2.1 — revise — ambiguity — operator identity resolution is skipped on a public read that declares `LodgingOperator` but carries no `X-User-ID` — `auth.py:58-65`
- §2.1 — revise — ambiguity — the dispute-proceeding role split reports `ERR_FORBIDDEN_ROLE` and is settled from the action alone, before the path id is resolved — `auth.py:76-79`, `routes/disputes.py:66-73`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`–`Z`/`0`–`9` — `store.py:126-130`
- §2.2 — revise — ambiguity — `api_request_timestamp` is `…SS.mmmZ` from **real wall clock**, unaffected by the logical clock — `envelope.py:9-13`, `store.py:70-79`
- §2.2 — revise — ambiguity — `response_type` is `"object"` for empty-data 2xx and for computed summary objects — `envelope.py:16-22`
- §2.2 — revise — ambiguity — pagination `meta` fields are omitted entirely from non-list responses; `has_more` == `offset + len(data) < total_count` — `envelope.py:29-36`
- §2.2 — **revise — mismatch** — "All error API responses (4xx status codes)" → all error responses whatever the status — `app.py:52-64`
- §2.2 — insert — ambiguity — new bullet: unknown path → 404, undefined method → 405, unexpected failure → 500, all with `error_id` `ERR_INVALID_REQUEST` (the sole §5 identifier whose status may differ from its listed 400, and only on these framework paths); trailing slash insignificant — `app.py:44,56-64`
- §2.3 — revise — ambiguity — bounds are rejection not clamping (400); `offset` unbounded above and may overshoot; empty-string param == omitted; whitespace ignored; ties break on insertion order — `envelope.py:47-66`, `store.py:186-188`
- §2.3 — revise — ambiguity — list filters are optional exact-equality matches on the same-named field; out-of-enum and non-integer values are refused 400; an id-valued filter is not an existence check — `envelope.py:78-102`, `routes/common.py:14-20`
- §2.4 — revise — ambiguity — the clock is not a ratchet; backward moves are legal — `routes/clock.py:20`
- §2.4 — revise — ambiguity — deadline comparison is strict; other statuses untouched; the OVERDUE sweep is one-directional (backward moves do not restore records) — `routes/clock.py:22-36`
- §2.5 — revise — ambiguity — the eleven caller-supplied instants are echoed back **character for character**, un-normalized, while server stamps render canonically — `serialize.py:5-10`, `validate.py:147-154`
- §2.5 — revise — ambiguity — `version`/`updated_at` advance at most **once per record per request**; a record the request created stays at `version` 1 — `store.py:139-166`
- §2.5 — revise — ambiguity — a recompute landing on the stored value is not a mutation and moves no version — `store.py:169-178`
- §2.6 — revise — ambiguity — four-decimal rounding precedes the threshold range test (1.00004 accepted as 1.0000); ratios accept a number or numeric string, reject bool/non-finite; whole-day counts are floored; year addition clamps 29 Feb → 28 Feb — `validate.py:93-111`, `store.py:86-97`
- §2.8 rung 4 — revise — ambiguity — six universal shape rules: absent/empty/`null` body == `{}` and non-object/unparseable bodies fail here; explicit `null` == omitted (selects the default); strict non-coercing types (ints reject bools, numeric strings and fractional numbers); untrimmed string lengths, with id-valued fields the trimming exception; the accepted instant grammar (bare date → midnight UTC, `Z`/`z`, numeric offset converted, naive assumed UTC); bounds reject rather than clamp — `validate.py:22-144`, `store.py:52-67`

## Deliberately left alone (already pinned, non-obvious)
- **The whole §5 error map** — verified programmatically identical to `errors.py:3-61`, all 57 rows, including the two 412s and `ERR_OPERATOR_IDENTITY_UNKNOWN` at 403.
- **The list of ten public reads** — matches the ten `public=True` call sites exactly, one for one.
- **Clock default `2026-08-01T00:00:00Z`** — exact match to `config.DEFAULT_CLOCK`.
- **The single ordering exception** (district's assessment-period list by `period_start`) — the only `sort_key=` in the entire codebase.
- **`id` as a bare UUID with no type prefix**, and `created_at`/`updated_at` from real wall clock while §3's workflow instants come from the logical clock — both already correct and both easy to get backwards.
- **Twelve creation endpoints → 201, everything else 200 including the clock** — §4 preamble already pins this precisely.

## Truncation check — last two lines, verbatim
```
| `ERR_REMITTANCE_EXCEEDS_TOTAL_DUE` | 409 |
| `ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT` | 409 |
```

Scratch files are confined to `workspace/scratch_step9_pass1/`. No process was killed and no test run.

## Step 9 pass 2 of 3: PRD completeness scan — district/roll/petition/assessment/collection modules — 2026-09-05T17:49:31Z

Partition: routes/districts.py, routes/businesses.py, routes/petitions.py, routes/periods.py, routes/statements.py, services/core.py. Forbidden from copying; edits in place only.

PASS 2 of 3 complete.

## Integrity confirmations

- **I did NOT copy any file.** `PRD_COMPLETED.md` was edited in place with 23 targeted `Edit` calls only. No `cp`, no whole-file `Write`.
- **Pass 1's §2 edits are still present and byte-intact.** `diff PRD_FINALIZED.md PRD_COMPLETED.md` yields 35 hunks: **16 hunks below line 160 (pass 1's 17 §2.x edits)** and **19 hunks at/after line 164 (mine)**. I reverted, reworded, and re-scoped nothing pass 1 wrote, and I did not touch §2.2–§2.6 or §2.8.
- No orchestrator-owned file was modified. I read no `SCAFFOLD*.yaml` and no `worklog.md`. No processes killed. No server started, no tests run.

## Size

| | lines | chars |
|---|---|---|
| before first edit | 530 | 128223 |
| after last edit | 530 | 134275 |

Structural gates all pass: **57 error-table rows**, **63 endpoint-table rows**, 29 markdown headings, document still ends at the last row of the §5 error table.

## Change counts

**21 substantive changes across 19 diff hunks**: **14 ambiguity-pins**, **7 mismatch-revisions**.

## Changes

- §3.1 — revise — ambiguity — "The five money and count aggregates" → "The eight" (the enumeration that follows names eight fields, all zero-initialised) — `routes/districts.py:180-191`
- §3.1 — insert — ambiguity — status resolution re-runs against the **stored** `exempt_status`, so raising `room_count` alone never clears an `UNDER_MINIMUM_ROOMS` exemption — `routes/businesses.py:183-186`, `services/core.py:218-226`
- §3.1 — insert — ambiguity — close-out: the owed-money test runs before any field is stored; the branch short-circuits assessability resolution, disqualifies **no** signature, and re-scores every OPEN drive (denominators only) — `routes/businesses.py:154-181`
- §3.1 — revise — **mismatch** — boundary revision: `effective_on` is required but neither stored nor compared (revision takes effect immediately); re-entry to `ASSESSABLE` additionally requires `exempt_status == "NONE"` and `room_count >= 5`; roll walked in `created_at` order; `EXEMPT`/`CLOSED_OUT` rows untouched — `routes/districts.py:196-222`
- §3.1 — revise — ambiguity — `dmo_name` must be non-blank once trimmed; omitted/null pool and offset keep the stored value — `routes/districts.py:230-242`
- §3.1 — revise — ambiguity — financial summary: `fiscal_year` narrows purely by `period_label` `FY`-prefix across all filing/payment statuses; the echoed year is the supplied one else `current_fiscal_year`; an unmatched year yields zeros; per-field formulas pinned; `lodging_tax_match_committed_cents` copied from the district row — `routes/districts.py:51-79`
- §3.2 — insert — ambiguity — `closes_at` need not lie in the future — `routes/petitions.py:54-115`
- §3.2 — insert — ambiguity — renewal drive: the window is the only condition beyond the terminal-status bar (no district-status precondition, not blocked by another OPEN drive, no pool floor, district status left untouched); a null `expiration_date` fails the window test — `routes/petitions.py:81-89`
- §3.2 — insert — ambiguity — signing guard precedence: different-district → exempt → boundary/assessability → duplicate — `routes/petitions.py:135-148`
- §3.2 — revise — **mismatch** — a failing RENEWAL tally "leaves the district's `status` exactly where it was, whatever that status happens to be" (was: "in RENEWAL_PENDING"); only FORMATION writes `FORMATION_FAILED` — `routes/petitions.py:212-214`
- §3.2 — insert — ambiguity — tallying is not gated on the signature window — `routes/petitions.py:189-200`
- §3.2 — revise — ambiguity — `certified_on` is validated but neither stored nor echoed — `routes/petitions.py:223`
- §3.2 — revise — ambiguity — renewal certification advances `current_fiscal_year` by exactly one — `routes/petitions.py:252`
- §3.2 — revise — ambiguity — the formation drive is "the earliest-created drive of that district whose `drive_type` is `FORMATION`", which must exist and stand CERTIFIED — `services/core.py:371-375`
- §3.2 — revise — **mismatch** — the RENEWAL_PENDING advance requires PUBLISHED `ANNUAL_REPORT`/`FINANCIAL_AUDIT` records whose `fiscal_year` equals the district's `current_fiscal_year` — `services/core.py:359-365`
- §3.2 — insert — ambiguity — disestablishment's program cancellation also recomputes each affected plan's `committed_program_cents` and the district's `lodging_tax_match_committed_cents` — `routes/districts.py:268-283`
- §3.3 — revise — **mismatch** — `ERR_BUSINESS_OUTSIDE_BOUNDARY` on generation fires only in the degenerate case (roll non-empty, nothing eligible, at least one out-of-boundary); generation has no period-status precondition — `routes/periods.py:138-146`
- §3.3 — revise — ambiguity — `ERR_STATEMENT_ALREADY_EXISTS_FOR_PERIOD` is also the answer for an empty roll or a roll excluded for non-boundary reasons; `statement_count` is set to the period's **total** statement count, not the newly created count — `routes/periods.py:145-152`
- §3.3 — revise — **mismatch** — filing re-evaluates **every** annual work plan of the district (forecast + `funding_ratio`), driving only the APPROVED current-FY plan into `AMENDMENT_PENDING` — `services/plans.py:105-124`
- §3.3 — revise — **mismatch** — audit "re-evaluates the district's annual work plans exactly as a filing does" — `routes/statements.py:29-34,187`
- §3.3 — insert — **mismatch** — the final-variant recompute on a granted dispute adjustment fires only where `final_assessment_cents` is already non-null; otherwise the adjustment reaches the effective figure through §3.4's derivation — `routes/disputes.py:160-161`
- §3.5 — insert — ambiguity — a sweep that selects nothing is still accepted: the period moves to `DELINQUENCY_SWEPT` and nothing else changes — `routes/periods.py:198-242`

## Deliberately left alone (PRD already pinned; non-obvious)

- §3.3's period-closure rule recomputing `collected_total_cents` as Σ`principal_paid_cents` even though remittances increment it by the full `amount_cents` — both facts are already pinned separately at §3.3 and §3.4.
- §3.5's per-statement round-then-accumulate discipline and the `standing_at_start`-snapshot `LIEN_REFERRED` rule — already exactly pinned.
- §3.2's three signature-disqualification causes: the impl narrows to `previous_status == "ASSESSABLE"`, but every reachable path already satisfies that, so narrowing the PRD would have risked a new mismatch.
- §3.5's hop-1/hop-2 presentation order — inverted relative to the impl, end state identical.
- §2.12's "checked after every forward payment" phrasing — the impl recomputes rather than checks, but every conserved-identity claim still holds; this is pass-1 §2 territory and I left it.
- All 63 endpoint-table role lists were verified against every `authenticate(...)` call in my partition — all matched exactly, so no §4 row needed editing.

## Truncation check — last two lines verbatim

```
| `ERR_REMITTANCE_EXCEEDS_TOTAL_DUE` | 409 |
| `ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT` | 409 |
```

Note handed to pass 3: the §3.3 edits reference plan re-evaluation semantics in `services/plans.py` (`reevaluate_plans` touching every plan, only the APPROVED current-FY plan going pending) and the dispute-grant final-variant condition in `routes/disputes.py:160-161`. Pass 3 owns both modules — §3.6–§3.9 wording must stay consistent with those two statements.

## Step 9 pass 3 of 3: PRD completeness scan — disputes/work-plan/marketing-program/transparency modules — 2026-09-05T18:10:28Z

Partition: routes/disputes.py, routes/workplans.py, routes/programs.py, routes/transparency.py, services/plans.py. Forbidden from copying; edits in place only.

Pass 3 complete.

## Integrity confirmation

**I did NOT copy `PRD_FINALIZED.md` over `PRD_COMPLETED.md`.** Every change was a targeted `Edit`. Verified passes 1 and 2 survive three ways:
1. The changed-hunk map versus `PRD_FINALIZED.md` still contains all 35 pre-existing hunks at their original line pairs (`19c19 … 291c292`), now joined by my 27.
2. Five distinctive sentinel strings from the earlier passes each still occur exactly once (`"Waived does not mean ignored"` §2.1, `"the different-district test first"` §3.2, `"already disqualified signatures are not restored"` §3.1, `"The district cannot enter renewal while any transparency artifact stands"` §3.2, `"Where a district is dissolved from ACTIVE, that cancellation also clears"` §3.2).
3. Only one of my hunks lands below line 300 — `114c115`, my own §2.7 edit. §2.2–§2.6, §2.8 and §3.1–§3.5 are byte-identical to what pass 2 left.

**Size:** 530 lines / 134,275 chars before → **532 lines / 150,317 chars** after (+2 lines: one new paragraph inside §3.9, no new sections).
**Structure:** 57 error-table rows, 63 endpoint-table rows, file still ends at the last §5 error row.

**Counts: 22 ambiguity-pins, 7 mismatch-revisions** (27 hunks; two hunks each carry two logical changes).

## Changes

- §2.7 — revise — ambiguity — enumerated every path that moves a plan's `version` (board action, amendment, program creation which always bumps it, disestablishment cancellation, district-wide forecast re-derivation incl. non-`APPROVED`/non-current plans), and that the version rung sits below the plan's state check — `workplans.py:163,178-184,209`, `programs.py:117-118`, `plans.py:105-118`, `districts.py:281-282`
- §3.6 — insert — ambiguity — dispute filing consults neither the statement's `filing_status`/`payment_status` nor the district's lifecycle status; reads also carry a `dispute_type` filter; only the per-property list is ownership-scoped — `disputes.py:24-56,18-21`, `statements.py:55-63`, `businesses.py:69-79`
- §3.6 — insert — ambiguity — the proceeding role split is decided before the dispute is looked up, so a wrong-role action on an unknown id is `ERR_FORBIDDEN_ROLE` — `disputes.py:66-75`
- §3.6 — insert — ambiguity — `APPEAL` clears only `resolved_by_user_id`; `resolution_note` and `granted_adjustment_cents` survive — `disputes.py:98-100`
- §3.6 — insert — ambiguity — an `UPHELD` outcome short-circuits and ignores any supplied `granted_adjustment_cents`/`exempt_status_granted`; no bound is applied — `disputes.py:131-136`
- §3.6 — insert — ambiguity — error codes and evaluation order of the granted-figure bounds: only the `>=1` bound is a shape check; the rest run after the `UNDER_REVIEW` state check and all but the assessment bound report `ERR_INVALID_REQUEST` — `disputes.py:116,122-150`
- §3.6 — insert — ambiguity — hop one also recomputes the period's `billed_total_cents` and the district's money aggregates (not `collected_total_cents`) — `disputes.py:166-167`, `core.py:331,144`
- §3.6 — **revise** — **mismatch** — hop two re-derives forecast + `funding_ratio` on *every* plan of the district in any status; only the `APPROVED` current-fiscal-year plan flips to `AMENDMENT_PENDING` — `plans.py:105-118`
- §3.6 — insert — ambiguity — the exemption grant fires only from `ASSESSABLE` (otherwise silently skipped, resolution still succeeds) and drags §3.1's signature-disqualification/aggregate/re-score cascade — `disputes.py:170-177`, `core.py:229-237`
- §3.7 — insert — ambiguity — `narrative` shape (>=1 char, no max, no trim), non-object array entries refused, `ERR_INVALID_REQUEST` for repeated category and duplicate fiscal year, plus the `ERR_DISTRICT_NOT_ACTIVE` terminal-district guard preceding them — `workplans.py:20-36,78-85`
- §3.7 — insert — ambiguity — the match ceiling and funding-ratio floor are also not applied at draft; work-plan read filters (`fiscal_year`, `status`) and which of the three reads are public — `workplans.py:87-110,51-64`, `districts.py:115-123`
- §3.7 — insert — ambiguity — no board action (nor an amendment) consults the district's lifecycle status; each success bumps the plan's version — `workplans.py:113-164,167-211`
- §3.7 — insert — ambiguity — the re-evaluation is district-wide, runs on certification too, and the `AMENDMENT_PENDING` flip is decided from the recomputed ratio itself rather than from any movement in it — `plans.py:105-118`, `statements.py:29-34,187`
- §3.7 — **revise** — **mismatch** — amendment check order is ladder order, not narration order: four category tests first, then variance, revision ceiling, match ceiling, funding-ratio floor last — `workplans.py:186-202`
- §3.8 — insert — ambiguity — program creation's `ERR_DISTRICT_NOT_ACTIVE` terminal guard precedes the plan-`APPROVED` check and makes no positive `ACTIVE` demand — `programs.py:72-76`
- §3.8 — insert — ambiguity — the three fiscal ceilings run budget → 50 % ceiling → pool, so a double breach reports `ERR_LODGING_TAX_MATCH_CAP_EXCEEDED` — `programs.py:78-91`
- §3.8 — insert — ambiguity — creation's parent bookkeeping: plan version always bumps, district's `lodging_tax_match_committed_cents` re-derived district-wide and only bumps on change — `programs.py:117-119`, `plans.py:76-79`, `core.py:138-141`
- §3.8 — insert — ambiguity — launch guard order plus the two surprising codes: terminal district → `ERR_DISTRICT_NOT_ACTIVE`, merely-not-`ACTIVE` → `ERR_INVALID_STATE_TRANSITION`, clock outside window → `ERR_INVALID_STATE_TRANSITION` (not `ERR_CLAIM_OUTSIDE_BOOKING_WINDOW`); budget re-check adds nothing for the launching program — `programs.py:133-154`
- §3.8 — insert — ambiguity — the claimed property is never reconciled against the program's district, and its `status`/`compliance_standing` are not consulted — `programs.py:200-208`
- §3.8 — **revise** — **mismatch** — the window refusal covers *any* non-`RUNNING` program status, not only "not yet launched" — `programs.py:204-208`
- §3.8 — insert — ambiguity — per-property claim list carries a `status` filter and is ownership-scoped; per-program list and single read are not — `businesses.py:59-66`, `programs.py:37-51`
- §3.8 — insert — ambiguity — each verification branch ignores the other's field; `ALLOW` bumps the program, `REJECT`'s recompute is a no-op leaving `verified_room_nights`/`updated_at`/`version` untouched — `programs.py:254-275`
- §3.8 — insert — ambiguity — closure tests `spend_frozen` before pending claims and consults neither plan nor district status — `programs.py:170-177`
- §3.8 — insert — ambiguity — a `net_cost_per_room_night_cents` rounding to 0 yields `performance_index` 0.0000 rather than a division by zero — `plans.py:200-204`
- §3.8 — **revise** — **mismatch** — disestablishment clears `spend_frozen` only when the district was `ACTIVE`; it also recomputes the district's `lodging_tax_match_committed_cents`; `EXPIRED` cancels nothing — `districts.py:268-283,346`
- §3.9 — insert — ambiguity — record creation's `ERR_DISTRICT_NOT_ACTIVE` guard; the meeting separation is symmetric-absolute and counts `PUBLIC_MEETING` records in every status; `scheduled_for`/`required_by` are unordered and need not be future — `transparency.py:35-47`
- §3.9 — insert — ambiguity — `document_reference` is read but discarded by the `NOTICED` and `COMPLETED` steps, and stored untrimmed by `PUBLISHED` — `transparency.py:72-76,118`
- §3.9 — insert — ambiguity — premature completion is `ERR_INVALID_STATE_TRANSITION` and is evaluated before the audit segregation test — `transparency.py:96-102`
- §3.9 — **revise** — **mismatch** — `transparency_standing` is re-derived after *every* successful advance, not just publication (moved into its own paragraph after the bullet list) — `transparency.py:121`, `core.py:156-161`
- §3.9 — **revise** — **mismatch** — a lapsed `ANNUAL_REPORT`/`FINANCIAL_AUDIT` makes `DEFICIENT` **permanent**; the old text promised recovery "by publishing whatever other reports remain outstanding", which is unreachable — `OVERDUE` is terminal, the derivation reads only the overdue set, and nothing else in the API writes the field — `core.py:156-161`, `clock.py:25-36`, `districts.py:180`
- §3.9 — **revise** — **mismatch** — the two transparency gates differ: `RENEWAL_PENDING` entry adds a no-record-`OVERDUE` arm (a lapsed `PUBLIC_MEETING` blocks it) that `RENEWAL` drive certification lacks — `core.py:352-368`, `districts.py:316`, `petitions.py:234`

## Deliberately left alone (already uniquely pinned, and non-obvious)

- §3.7's approval check order (SoD → admin cap → contingency cap → marketing floor → `CAPITAL_IMPROVEMENT` permission → match ceiling → funding-ratio floor) exactly matches `workplans.py:142-148` + `plans.py:130-165`, including the ceiling being `min(50 % of total, pool)` against the *district's* committed total.
- §3.7's forecast definition (`FY`-prefix scan, the four counting filing statuses, `payment_status` ignored, 0.0000 on a zero budget) matches `plans.py:45-60` verbatim.
- §3.8's two-pass measurement, tier bounds, share percentages and flag thresholds match `plans.py:178-221` exactly; the "tier never reselected" invariant is already explicit.
- §3.6's `ERR_DISPUTE_ALREADY_OPEN` scoping (per statement-and-ground, live set = `SUBMITTED`/`UNDER_REVIEW`/`INFO_REQUESTED`) and the unlimited `REQUEST_INFO`/`SUBMIT_RESPONSE` cycle are already pinned.
- §3.6's "no side effect on a refused resolution" paragraph already matches the impl's deliberate write-ordering comment at `disputes.py:128-136`.
- All 63 endpoint rows' authorized-role lists and all 57 error/HTTP-status pairs were checked against `auth.py`/`errors.py` for my flows and needed no change.

One note for the record: pass 2's §3.2 line about `ACTIVE`-only `spend_frozen` clearing was left untouched; the §3.8 sentence was made to agree with it, since both now describe `districts.py:346` correctly.

## Pipeline complete — 2026-09-05T18:10:28Z

Step 9 wrote `workspace/PRD_COMPLETED.md`; the pipeline is finished.

**Orchestrator final verification (independent of every subagent):**

| artifact | lines | bytes |
|---|---|---|
| `workspace/PRD.md` | 529 | 116,381 |
| `workspace/PRD_FINALIZED.md` | 529 | 118,873 |
| `workspace/PRD_COMPLETED.md` | 532 | 150,317 |

- `PRD.md` vs `PRD_FINALIZED.md`: DIFFER (Step 8 was required — Step 7 made one `implementation/` fix).
- `PRD_FINALIZED.md` vs `PRD_COMPLETED.md`: DIFFER, 62 diff hunks (35 from passes 1+2, 27 from pass 3). Not byte-identical, so the Step 9 scan demonstrably ran.
- `PRD_COMPLETED.md` structure: 57 error-table rows, 63 endpoint-table rows, 29 headings, tail is the final `ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT` row — a real section boundary, not truncated.
- Step 9 totals across the three passes: **52 ambiguity-pins, 15 mismatch-revisions** (17 + 21 + 29 logical changes).
- No `.py` file under `workspace/implementation/` was modified after the green Step 7 sweep (latest impl mtime 16:42, sweep completed 16:46), so the 8× 133/133 result still describes the shipped implementation. `results.1..8.json` are retained in `implementation/`.
- `test_suite/` holds 133 test functions; `test_helpers/` and `test_suite/` are at the task root, with no strays under `workspace/`.
- The difficulty directive "Generate task harder than expert level!" appears nowhere in the task tree.

Retained diagnostic evidence (not part of the deliverable): `workspace/run_sweep.sh`, `workspace/sweep.log`, `workspace/round.1..8.log`, `workspace/SWEEP_DONE`, and the per-step `workspace/scratch_step*/` directories.
