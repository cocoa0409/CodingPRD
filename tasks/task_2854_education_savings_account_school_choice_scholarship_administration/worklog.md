# Worklog — task_2854_education_savings_account_school_choice_scholarship_administration

## Step 1: Create task directory — 2026-09-05T07:16:26.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2854_education_savings_account_school_choice_scholarship_administration` and its `workspace/` subdirectory. Index 2854 was pre-assigned by the invoking harness (no ./tasks/ scan performed, per orchestration instructions, because up to 32 pipelines run concurrently on this host and auto-allocation would collide).

## Step 2: Generate Scaffold — 2026-09-05T08:22:00.000Z

All three scaffold artifacts for task 2854 are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2854_education_savings_account_school_choice_scholarship_administration/`)

- `SCAFFOLD.yaml` — 2823 lines. §1.0 envelope (pagination `limit/offset/total_count/has_more`), **14 entities**, **8 state machines** (ProgramYear, Application, Account, Provider, PurchaseRequest with parallel approval/settlement dimensions, MisuseCase, RenewalReview, Appeal), **2 §1.2.1 concurrency rules** (`purchase-request-create-stale-account`, `renewal-review-create-stale-application`), **6 calculations** (annual_award_amount with 2 variants, quarterly_disbursement_slice, unused_balance_rollover, provider_risk_score with 2 variants, priority_score_and_rank, clawback penalty), **38 ordered validations**, **52 endpoints**, **38 errors**, **8 roles** (segregation-of-duties model). Contains neither design key. One correctness fix applied this pass: `POST /esa/renewal-reviews/{id}/decision` was missing its `input:` list while §1.2/§1.4 referenced "decision APPROVED"; added `input: [decision, "decision_note?"]`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1739 lines, single key `scaffold_difficulty_design`: all **9 rule ids × 2 = 18 instances** (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3768 lines, single key `scaffold_corner_design`: **9 sections / 77 instances** — entities 12, state_machines 10, calculations 9, validations 15, endpoints 8, errors 8, rbac 6, cross_cutting_complexity_layers 6, consistency_model 3. **19** of those are `excluded_because:` stubs citing a §1.8 instance by name (all cited names verified to exist); **58** carry full `test_recipe` chains.

**Verification**
- `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2854_.../` →
  `§1.5 endpoints declared: 52 / §1.1 entities declared: 14 / §1.8 instances scanned: 18 / §1.9 instances scanned: 58 / Calls scanned (§1.8+§1.9): 918`
  `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`
- 95 instance names unique across both design files; every `grounds` ref (errors ids, validation priorities, calculation/entity/role/state-machine names, endpoint paths) resolves into SCAFFOLD.yaml; no "harder than expert level" directive leaked into any artifact.

**Notable design pins** (all pre-computed literals, cross-checked between the two design files): award 932663 verified / 978382 provisional / 699497 at 3 quarters remaining; quarterly slices 233168+4080/229088 then 233165+4080/229085 (remainder front-loaded onto Q1); rollover cap exactly 233166 with strictly-greater forfeiture; clawback tier keyed on principal (250000 → 0.20/50000/debit 229088/receivable 70912); provider screening 35 static vs surveillance 43 at 12 months (decay floor 0.5 + ROUND_HALF_UP of 17.5) and 60 → 85 crossing the 75 auto-PROBATION threshold on the second substantiated case; priority tiers 3/140, 4/100, 4/170, 5/60.

Two lint issues were found and fixed during the pass: a `$.data.total_count` capture on a list endpoint (must be `$.data[0].<field>`), and three `grounds: consistency_model` refs retargeted to `complexity_profile.consistency_model`.

Orchestrator verification: SCAFFOLD.yaml 2823 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1739 lines, SCAFFOLD_CORNER_DESIGN.yaml 3768 lines all present; grep for "harder than expert"/"expert level" across all three returned no matches, so no difficulty-directive leak to strip.

## Step 3: Copy Shared Files — 2026-09-05T08:23:44.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T08:42:00.000Z

PRD complete at `workspace/PRD.md`.

## Sections emitted
- `# Education Savings Account Administration API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC · 2.2 API Response Structure (verbatim block) · 2.3 Pagination · 2.4 Common Resource Properties and Append-Only Event Records · 2.5 The Logical Programme Clock · 2.6 Money, Precision and Rounding · 2.7 Version Guards Against Stale Reads · 2.8 The Order in Which a Request Is Rejected (full 38-rung ladder) · 2.9 Cascade Discipline · 2.10 The Seat Pool Invariant · 2.11 The Account Ledger Identity
- `## 3. Business Logic & Workflows` — 3.1 award year + expense catalogue · 3.2 student intake, application, provisional award · 3.3 eligibility, priority tiers, award scoring · 3.4 award run, offers, ordered waitlist · 3.5 acceptance, account opening, quarterly funding · 3.6 provider screening, admission banding, sanctions · 3.7 purchase lifecycle (dual state dimensions) · 3.8 misuse cases, suspension, clawback · 3.9 renewal, appeals, year-end close
- `## 4. Endpoint Definitions` — status-code paragraph + 52-row 4-column table
- `## 5. Error Code Catalogue` — 38-row 2-column table

No audit footer; file ends at the last error row.

## Coverage
- Endpoints: 52/52 from the scaffold, exact paths, roles and 201-vs-200 semantics.
- Errors: 38/38 with HTTP statuses.

**Contract 1 — Field-Name Coverage**
```
- entities[].fields: 162 required, 162 present, 0 missing
- endpoints[].input: 131 required, 131 present, 0 missing
- endpoints[].output: 55 required, 55 present, 0 missing
Status: PASS
```
(The scaffold uses `input`/`output`, not `request_body`/`query_params`; list/query identifiers live in `input`.)

**Contract 2 — Rule Coverage**
```
- validations[] with priority: 38 checked, 38 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 51 checked, 51 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed, 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 87 distinct refs + 28 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 162 fields / 53 defaults / 184 enum constants checked, all reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked, 8 with equal prose density, 0 asymmetric
Status: PASS
```

**Contract 3 — §3 Path Purity**
```
- backtick tokens scanned: 1145
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Fixes applied during verification
Seven scaffold decimal constants had been written only in word form; I added the exact literals so every formula is reconstructible without conversion: income multipliers 1.00/0.90/0.75, add-on percentages 0.375/0.225/0.125/0.0625, add-on cap 0.45, priority income weights 1.0/0.6/0.25, decay per month 0.1 and floor 0.5, penalty tiers 0.10/0.20/0.35, plus `rollover_cap_pct` 0.25 and `admin_fee_pct` 0.0175 defaults. Also named the appeal round cap explicitly as fixed at 2.

Two automated "misses" are verified false positives: the 7 `PurchaseRequest` transitions carry `APPROVAL:`/`SETTLEMENT:` dimension prefixes in the scaffold, and §3.7 expresses all 8 bare state names plus both `approval_status`/`settlement_status` dimension fields; the five `[]` defaults are expressed as "defaults to the empty list".

**Final line count: 532. Final section heading: `## 5. Error Code Catalogue`.**

The two withheld design files were never opened, grepped or referenced. Scratch work stayed in `/tmp/task_2854_prd/`.

Orchestrator truncation check (per the known doc-generator failure mode): PRD.md is 532 lines; `tail -25` shows the file ending on a complete markdown table row of §5's error catalogue, with all 38 `ERR_*` rows present and the §5 table therefore closed — a real section boundary, not a mid-sentence cut. Section headings present: 1 Introduction, 2 Global Specifications, 3 Business Logic & Workflows, 4 Endpoint Definitions, 5 Error Code Catalogue. No regeneration needed. Difficulty-directive leak check on PRD.md: no matches.

## Step 5: Generate Unit Tests — 2026-09-05T09:52:08.000Z

Step 5 (test generation) for task 2854 is complete. `test_13_year_end_close.py` was the last file; the suite now covers every non-stub design instance.

**Output locations (task root, nothing under `workspace/`)** — verified: `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation`, `run_sweep.sh`.

`test_helpers/` (2,963 lines)
- `__init__.py` 36, `api_client.py` 381, `api_errors.py` 102, `assertions.py` 449, `constants.py` 182, `factories.py` 468, `fixtures.py` 761, `test_users.py` 150, `types.py` 434

`test_suite/` (6,793 lines, 96 tests)
- `conftest.py` 64
- `test_01_program_years_and_catalog.py` 390 · `test_02_students_and_applications.py` 571 · `test_03_eligibility_determination_and_ranking.py` 522 · `test_04_appeals.py` 379 · `test_05_award_acceptance_and_accounts.py` 559 · `test_06_disbursement_runs.py` 396 · `test_07_providers_screening_and_admission.py` 602 · `test_08_provider_surveillance_and_delisting.py` 560 · `test_09_purchase_request_filing.py` 848 · `test_10_purchase_decision_claim_settle.py` 512 · `test_11_misuse_cases_and_clawbacks.py` 849 · `test_12_renewals.py` 296 · `test_13_year_end_close.py` 245

**Coverage**
- Queue A (difficulty): 18/18 instances, every one with ≥2 tests.
- Queue B (corner): 58/58 non-stub instances covered; the 19 `*_covered_by_difficulty` stubs carrying `excluded_because:` were correctly not translated (77 corner instances total).
- 76 distinct design instances across 96 tests. **No instance was skipped for a PRD-filter reason** — every non-stub instance had verbatim PRD coverage and a uniquely-derivable outcome.

**Verification run**
- `python3 -m compileall -q test_suite` clean.
- Citation/tag verifier (`/tmp/task_2854_tests/check_citations.py --coverage`): `files: 13, tests: 96, distinct design instances covered: 76, problems: 0`; the only "not yet covered" entries are the 19 legitimate excluded stubs. Every test has exactly one trailing `Design:` line resolving to a real yaml instance name, at least one whitespace-normalised-verbatim PRD quote, no skip/xfail, no mention of "scaffold".
- AST import check: every name imported from `test_helpers` across all 14 suite files resolves (`missing: []`).

**Notes on the final file** — `test_13_year_end_close.py` builds the boundary from real endpoint traffic: a Band-B/IEP award of `final_award_cents` 932663 with four quarters remaining, two disbursement runs (233168 + 233165 gross, 4080 fee each → balance 458173), then a TUITION purchase approved/claimed/settled at exactly 225007 (balance lands on the cap 233166 → carried 233166, forfeited 0) and at 225006 in the twin test (balance 233167 → carried 233166, forfeited exactly 1 cent). Both assert the close summary (`program_year_status`, `closed_account_count`, `total_rolled_cents`, `total_forfeited_cents`, `resolved_misuse_case_ids`), the application's move to `COMPLETED`, single version bumps, and `assert_ledger_identity` including `forfeited_cents`. I deliberately did not assert an account status change at close — the PRD never states one, and the renewal-acceptance `ACTIVE → CLOSED` transition implies the account is still `ACTIVE` afterwards, but that is inference rather than a uniquely-derived outcome.

## Step 6: Generate Implementation — 2026-09-05T09:12:32.000Z

(Step 6 was launched concurrently with Step 5 in a single assistant message, so the impl generator could not see `test_suite/`; it finished first, at 09:12Z, but is recorded after Step 5 to preserve the skill's step order.)

Implementation complete and smoke-verified.

## Location
`workspace/implementation/`

## Modules emitted (20 files, 3177 lines)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | `cd $(dirname $0)`, guarded pip install (only if flask missing), `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=2.0` |
| `app.py` | 75 | `create_app()`, 9 blueprints at `/esa`, global RLock per request, `ApiError`/`HTTPException`/catch-all handlers, binds `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 145 | in-memory `Store` (14 dicts), logical clock (`2026-08-01T00:00:00.000Z`), ISO-8601 helpers, monotonic `_seq`/`created_at` |
| `envelope.py` | 84 | meta/`req_`+20-char id, object/list/error envelopes, `public()`, `touch()` with one version bump per record per request |
| `errors.py` | 61 | 38-entry error-id → HTTP-status catalog |
| `validators.py` | 257 | auth (401 then 403), all enums, body/query coercion, pagination |
| `calc.py` | 241 | award, proration, tier/score, quarterly slice, rollover, screening/surveillance, clawback assessment (Decimal + ROUND_HALF_UP; integer cents) |
| `lookups.py` | 114 | 404 getters + relationship queries |
| `cascades.py` | 147 | seat recount, waitlist promotion, hold release, void, suspend/close, provider delist, surveillance rescore |
| `routes/program_years.py` | 315 | + `_clock/set_current_utc` |
| `routes/applications.py` | 379 | |
| `routes/purchase_requests.py` | 236 | |
| `routes/misuse_cases.py` | 219 | |
| `routes/appeals.py` | 216 | |
| `routes/accounts.py` | 212 | |
| `routes/renewal_reviews.py` | 196 | |
| `routes/providers.py` | 168 | |
| `routes/students.py` | 100 | students + expense-categories |

All files pass `ast.parse`. No SQLite/JSON/disk state; store starts empty on every boot (verified by restarting the process and confirming an empty account list).

## Endpoint coverage
I diffed the PRD's endpoint table against Flask's `url_map`: **52 of 52 PRD endpoints registered, 0 missing, 0 extras** (only Flask's built-in `/static/<path>`). Note there is deliberately no `GET /esa/program-years` list route — the PRD does not define one, so it correctly returns a 405 error envelope.

## Bug found and fixed by the smoke test
The suspension/delisting void cascade was selecting purchase requests on `approval_status` alone, so an already-settled request (which keeps `approval_status == "APPROVED"` while `settlement_status == "PAID"`) was being voided and its long-consumed hold released a second time. Symptoms: `encumbered_cents: -100000`, inflated balance, `CANCELLED` instead of `REVERSED`, a clawback of 180000/0 instead of 139088/40912, one ledger row instead of two, and a year-end close rolling the wrong figure. Fixed by adding a settlement-track condition in both cascade sites via a new `cascades.is_open_request(pr)` (`approval_status in (PENDING_REVIEW, APPROVED)` **and** `settlement_status in (UNSETTLED, CLAIMED)`), per PRD 3.7 ("a request already `PAID` cannot be voided") and PRD 2.9 exact compensation.

## Smoke test
47/47 assertions pass on `PORT=28540` end-to-end (program year → student → application → determination → awarding → acceptance → disbursement → provider screening/approval → purchase request → approve/claim/settle → misuse case → adjudication → clawback → appeal → clock → year-end close), including every pinned PRD figure and the 401/403/404/400/402/409/412 paths. Only the PIDs I launched (902348, 955466, 962108) were killed individually; port 28540 is free and no broad `pkill` was used.

## PRD ambiguities resolved (interpretation chosen)
1. **Renewal rollover balance** — the successor account records `rollover_in_cents` but its `balance_cents` stays 0 (literal reading of §3.5 "starts with `balance_cents` at 0"); the prior account closes with `rolled_out_cents += carried`, `balance_cents -= carried`.
2. **Rejection precedence** — the §2.8 38-rung ladder wins over §3 prose ordering wherever they disagree.
3. **Version bumps** — exactly one bump per record per HTTP request (de-duped via `g._touched`), with a deliberate double force-bump for the awarding run's two ProgramYear transitions.
4. **CLOSED vs SUSPENDED account** — CLOSED yields `ERR_INVALID_STATE_TRANSITION`, SUSPENDED yields `ERR_ACCOUNT_SUSPENDED`; the latter is raised only on the APPROVED branch of the purchase-request decision.
5. **Uniqueness collisions** — duplicate program-year `label`, provider `ein`, category `code` → `ERR_INVALID_REQUEST` (400).
6. **Disbursement-run quarter** — non-negative at shape validation, then `quarter != current+1 or quarter > 4` → `ERR_INVALID_STATE_TRANSITION`.
7. **Appeal ownership** — keyed on `subject_type` (application→student, clawback→account's student, delisting→provider id) rather than on the acting role; SoD enforced on both OVERTURNED and UPHELD.
8. **Auto-sanction reason strings** — `AUTO_DELISTED_SURVEILLANCE_SCORE` / `AUTO_PROBATION_SURVEILLANCE_SCORE`; misuse suspension uses `MISUSE_SUBSTANTIATED`; overturned delisting uses `DELISTING_OVERTURNED_ON_APPEAL`.
9. **Guardian ownership on create** — no ownership rung on `POST /applications` or `POST /renewal-reviews` (ladder rung 14 does not list them).
10. **Adjudication `rationale`** — validated but not persisted (MisuseCase has no field for it in the entity spec).
11. **Quarterly slice rounding** — integer floor with the remainder front-loaded onto the first disbursement (the only place not using ROUND_HALF_UP).

Orchestrator note: verified `test_helpers/` and `test_suite/` both sit at the task root and neither leaked into `workspace/` (the known Step 5 misplacement failure mode), so Step 7 can run against `--test-dir <task_root>/test_suite` unchanged.

## Step 7: Run Tests and Iterate — 2026-09-05T10:13:41.000Z

All 8 rounds pass cleanly. Exiting.

## Summary

**Iterations run:** 2 (each an 8-round parallel per-test-server sweep).

Iteration 1 was deterministic — the same 5 tests failed in all 8 rounds (101/106 each round), no flakiness anywhere. Iteration 2 was fully green.

**Tests deleted (1)**
- `test_05_award_acceptance_and_accounts.py::TestAccountReadAccess::test_guardian_of_another_household_is_refused_on_ownership` — **PRD silence on the asserted rule.** The test demanded `ERR_NOT_ACCOUNT_HOLDER` on `GET /esa/accounts/{id}` for a non-owning Guardian. PRD §2.1 scopes the ownership check to writes only ("every guardian **write** is checked by comparing the `student_id` …"), and §2.8 item 14 enumerates the endpoints it applies to exhaustively — "on application submission, award acceptance, withdrawal, purchase-request creation, and on appeals whose `subject_type` is `APPLICATION_DENIAL` or `CLAWBACK`" — with account reads absent. A PRD-faithful implementer correctly lets any Guardian read the account (Guardian is a listed role on that endpoint in §4). Scaffold rule that generated it: `Corner/errors/guardian_cannot_read_another_households_account`.

**Partial-coverage trim (1 assertion removed, test kept)**
- `test_04_appeals.py::TestAppealRoundCap::test_third_filing_after_two_rounds_is_refused` — removed only `assert after["denial_reason_code"] == "RESIDENCY"` (it was raising `KeyError`). **Computed-field silence:** PRD §3.3 puts `denial_reason_code` on the *eligibility determination row* ("The row records `denial_reason_code` by strict first-match order…") and its list of fields copied onto the application is explicit and excludes it; §3.9's overturn-reset list excludes it too. The covered assertions (`ERR_APPEAL_ROUNDS_EXHAUSTED`, untouched `appeal_round_count`, status still `DENIED`, the two-appeal listing) all remain intact.

**Fixes applied to `test_suite/` (3, all call-site type/baseline bugs)**
- `test_03_eligibility_determination_and_ranking.py` — helper `_submitted()` returned the pre-submission application object, so `after["version"] == application["version"] + 1` compared the post-determination version (3) against the DRAFT-era version (1); submission itself legitimately bumps the version per §3.2. It now returns `read_application(...)` after submitting, making the baseline the post-submit version. Only `["id"]` is read from it at the other six call sites, so the change is inert there.
- `test_13_year_end_close.py` — three calls to `assert_version_advanced_by(...)` passed whole resource dicts where the helper's contract (`assertions.py:102`, `assert after == before + steps`) takes version integers, producing `TypeError: unsupported operand type(s) for +: 'dict' and 'int'`. Now passing `before["version"], after["version"]`.

**Fixes applied to `implementation/`:** none. All 5 failures traced to the test layer; no PRD-required check was weakened or removed, and no implementation file was touched.

**Final sweep, per round (quoted from `results.$i.json`)**

| round | passed/total |
| --- | --- |
| 1 | 105/105 |
| 2 | 105/105 |
| 3 | 105/105 |
| 4 | 105/105 |
| 5 | 105/105 |
| 6 | 105/105 |
| 7 | 105/105 |
| 8 | 105/105 |

`failed: 0, errors: 0, skipped: 0` in every round. Total is 105 rather than 106 because of the single deleted test. `worklog.md`, `PRD.md` and `SCAFFOLD*.yaml` were not modified.

**Orchestrator independent verification of the Step 7 sweep artifacts** (the "clean sweep with no artifacts" failure mode): all 8 `workspace/implementation/results.$i.json` files exist and each parses to `passed=105 total=105 failed=0 errors=0 skipped=0`; `workspace/SWEEP_DONE` marker written at 2026-09-05T10:04:18Z. The 95 physical `def test_` functions expand to 105 collected items via `@pytest.mark.parametrize` in `test_01_program_years_and_catalog.py` and `test_02_students_and_applications.py`. Grep confirms zero `pytest.mark.skip`/`xfail` anywhere in `test_suite/` or `test_helpers/`, zero on-disk persistence (no sqlite3, no `json.dump`, no file writes) in `implementation/`, and no entity seeding at startup. No stray worklog.md under `workspace/`.

**Step 8 decision:** Step 7 recorded 1 deletion + 1 partial-coverage trim + 3 `test_suite/` fixes, i.e. more than zero iterations beyond the baseline, so the skip condition does not apply and Step 8 runs. Note that `implementation/` fixes were zero, so Step 8's diff may legitimately be very small or byte-identical to PRD.md — that is an acceptable Step 8 outcome (only Step 9 must never be identical).

## Step 8: Finalize PRD — 2026-09-05T10:23:01.000Z

**Result: `PRD_FINALIZED.md` is byte-identical to `PRD.md`** (532 lines each, md5 `a4c7ef0d…`, 0.0% delta). Step 7 made **zero** implementation fixes, and each of the four diff items turned out to be either already uniquely determined by PRD.md or a pure test-layer bug.

Per-item analysis (subject → impl paths enumerated → conclusion):

**1. Deleted test — `ERR_NOT_ACCOUNT_HOLDER` on `GET /esa/accounts/{id}` for a non-owning Guardian**
- (a) Subject: the scope of the Guardian-ownership check.
- (b) Enumerated: `grep -rn "ERR_NOT_ACCOUNT_HOLDER\|ERR_NOT_ASSIGNED_PROVIDER"` over all of `implementation/` returns exactly 7 enforcement sites — `routes/applications.py:135` (submit), `:272` (accept-award), `:354` (withdraw), `routes/accounts.py:135` (purchase-request creation), `routes/appeals.py:54,60` (APPLICATION_DENIAL / CLAWBACK), `routes/appeals.py:64` + `routes/purchase_requests.py:186` (provider ownership on delisting appeal / invoice claim). `read_account` (`routes/accounts.py:39-43`), `list_accounts` (`:46-61`), `list_account_disbursements` (`:64`), `list_account_clawback_entries` (`:74`) and `read_application` (`applications.py:107`) do role-only `authenticate(...)` with no ownership scoping.
- (c) No edit. That 7-site set maps exactly onto PRD §2.8 items 14–15, §2.1 already scopes the check to *writes*, and §4 lists `Guardian` on `GET /esa/accounts/{id}`. Step 7's own note concedes "a PRD-faithful implementer correctly lets any Guardian read the account" — so PRD.md already determines the impl behavior and any clarifying sentence would be redundant (and risked wrongly universalizing the check onto renewal-review filing, a Guardian write that impl deliberately leaves unchecked).

**2. Trimmed assertion — `denial_reason_code` on the application**
- (a) Subject: where `denial_reason_code` lives.
- (b) Enumerated: `grep -rn "denial_reason_code"` → only `routes/applications.py:199-207` (derivation) and `:235` (written onto the determination row dict). The application record literal (`applications.py:79-102`) has no such key; the DENIED branch (`:252-254`) sets only `status`; the appeal-overturn reset path was checked too (`routes/appeals.py`, `cascades.py`) and never touches it.
- (c) No edit. PRD §3.3 already places the field on the determination row and its copy-onto-application list excludes it; §3.9's reset list likewise. The `KeyError` was the test asserting a field PRD never put on the application.

**3. `test_03` `_submitted()` baseline (version arithmetic)**
- (a) Subject: `version` increments on submit and on determination.
- (b) Enumerated: `applications.py:151` (`touch(app)` once on submit), `:254` (`touch(app)` once per determination, both ELIGIBLE and INELIGIBLE branches), `envelope.touch` (single +1).
- (c) No edit. PRD §3.2 ("the application's `version` rises by 1" on submit) and §3.3 (+1 on either outcome) already pin this exactly; the failure was a fixture returning the pre-submit object.

**4. `test_13` `assert_version_advanced_by` TypeError**
- (a) Subject: version increments during year-end close.
- (b) Enumerated: `routes/program_years.py:244-295` — `touch(acct)` once per ACTIVE account (`:265`), `touch(app)` once on ACCEPTED→COMPLETED (`:273`), `touch(case)` once per swept CLAWBACK_ISSUED case (`:283`), `touch(py)` once (`:287`); test asserts `steps=1` at all three call sites.
- (c) No edit. PRD §3.9 already states "The programme year's `version` rises by 1, and so does the `version` of every account and every other record the close touched." The failure was passing whole dicts into a helper that takes integers (`test_helpers/assertions.py:102`).

No files other than `workspace/PRD_FINALIZED.md` were written.

**Orchestrator note:** a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome precisely because Step 7 applied zero `implementation/` fixes — every failure was a test-layer bug, so there was no impl behavior for the PRD to be realigned to. Verified by md5: PRD.md and PRD_FINALIZED.md match. Step 9, by contrast, must not be identical to its source; it runs a full impl-wide scan and will be partitioned into three sequential module-scoped passes over one shared `PRD_COMPLETED.md` (pass 1 performs the `cp`, later passes must not).

## Step 9: Complete PRD — 2026-09-05T10:53:00.000Z

Step 9 was executed as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying, so as not to destroy earlier passes' edits). Final result: **532 lines / 128,033 chars**, up from the 532 lines / 106,380 chars of `PRD_FINALIZED.md` — **+21,653 chars across 60 changed lines (120 diff lines), 67 total changes, no new sections and no line-count change** (every edit was an in-paragraph insert or revision). md5 confirms `PRD_COMPLETED.md` (0438777f…) is NOT identical to `PRD_FINALIZED.md` (a4c7ef0d…).

### Pass 1 — core modules (`app.py`, `store.py`, `envelope.py`, `errors.py`, `validators.py`, `lookups.py`, `calc.py`, `cascades.py`)

`cp PRD_FINALIZED.md PRD_COMPLETED.md` performed. 112,232 chars out; 20 changes — **13 ambiguity-pins, 7 mismatch-revisions**.

- §2.1 — revise — ambiguity — a header present but empty counts as absent for `ERR_UNAUTHENTICATED` — `validators.py:67`
- §2.2 — revise — ambiguity — `api_request_id` suffix is exactly 20 chars from `A`–`Z` and `0`–`9` — `envelope.py:11,15`
- §2.2 — revise — ambiguity — `api_request_timestamp` reads real wall-clock time, not the §2.5 logical clock — `envelope.py:21`
- §2.2 — revise — ambiguity — pagination `meta` fields appear on list responses only; object `meta` carries just the two id/timestamp keys — `envelope.py:43-54`
- §2.3 — insert — ambiguity — an empty query-param value falls back to the default; `limit`/`offset` must be plain decimal digits (no sign, no leading zero, no fraction; surrounding whitespace tolerated); undefined query params ignored — `validators.py:213-234`
- §2.4 — insert — ambiguity — `created_at` is wall-clock, not the logical clock, and forced strictly increasing system-wide so no two records share one — `store.py:122-130`
- §2.4 — revise — ambiguity — `updated_at` comes from the same wall-clock source and equals `created_at` on an unmodified record — `store.py:122-130`, `envelope.py:73`
- §2.5 — revise — mismatch — default clock is `2026-08-01T00:00:00.000Z` (PRD wrote it without the mandated three fractional digits) — `store.py:12`
- §2.8 item 3 — insert — ambiguity — JSON `null` counts as absent; booleans rejected for int/number fields; whitespace-only rejected where non-empty; absent/unparseable body read as `{}`; non-object body is `ERR_INVALID_REQUEST`; client instants accept any offset (missing offset = UTC) and are normalised to UTC with three fractional digits, finer digits truncated — `validators.py:80-108,186-192`, `store.py:29-55`
- §2.9 — insert — mismatch — defines an **open** purchase request as `approval_status` PENDING_REVIEW/APPROVED *and* `settlement_status` UNSETTLED/CLAIMED; PAID/REVERSED/CANCELLED requests are never touched by a cascade — `cascades.py:14,19-21`
- §2.9 — insert — ambiguity — `version` rises exactly once per record per request no matter how many times a cascade moves it; `updated_at` reflects the last movement; the award run's two stated year transitions are the sole exception — `envelope.py:76-84`
- §2.10 — insert — ambiguity — seat counters are recomputed from the application population, and the year's `version` rises from a recount only when a counter actually changes — `cascades.py:25-39`
- §3.5 — revise — mismatch — withdrawal closure voids only *open* requests; a request already `PAID` survives untouched — `cascades.py:19,100`
- §3.6 — revise — mismatch — delisting voids only *open* requests naming the provider — `cascades.py:118-120`
- §3.6 — revise — ambiguity — elapsed months floored at zero (clock at/before `screened_at`, or null `screened_at`, gives 0 months and factor 1) — `store.py:83-94`, `calc.py:208-212`
- §3.6 — insert — ambiguity — auto-delist reaches only APPROVED/PROBATION and auto-probation only APPROVED; reasons are the literals `AUTO_DELISTED_SURVEILLANCE_SCORE` / `AUTO_PROBATION_SURVEILLANCE_SCORE`; the recompute always rewrites the score and bumps `version` — `cascades.py:7-8,132-147`
- §3.8 — revise — mismatch — substantiation's suspension cascade voids only *open* requests — `cascades.py:19,88-93`
- §3.8 — revise — mismatch — the explicit `SUSPEND` action's cascade voids only *open* requests — `cascades.py:19,88-93`
- §4 — revise — ambiguity — a trailing slash on any path resolves to the same endpoint — `app.py:23`
- §5 — insert — mismatch — `ERR_INVALID_REQUEST` is also returned with HTTP 404 for an undefined path and HTTP 405 for an unsupported method, despite the table's 400 — `app.py:47-57`

Left undocumented, with reasons: the §5 error table was verified programmatically identical to `errors.py:CATALOG` (38 entries, statuses all match); all seven `calc.py` formulas were confirmed already pinned numerically by §3.2/§3.3/§3.5/§3.6/§3.8/§3.9 down to the worked examples; `lookups.py` 404 codes already pinned by §2.8 rungs 4–13, and `by_seq` insertion ordering is equivalent to `created_at` ordering because `created_at` is strictly increasing; `rank_key`'s null-`submitted_at` branch is unreachable (only ELIGIBLE applications are ranked, renewal offers enter at AWARD_OFFERED); the `unpaid < 0` and negative-balance clamp guards are unreachable; and process-internal mechanics (global request lock, `_`-prefixed key drop and Decimal→float coercion in `envelope.public()`, `_seq` minting, generic 500 handler) are not client-observable contract.

### Pass 2 — intake routes (`program_years.py`, `students.py`, `applications.py`, `accounts.py`)

No `cp` performed (confirmed); pass 1's sentinel edits verified intact before editing. 120,987 chars out; 22 changes — **19 ambiguity-pins, 3 mismatch-revisions**.

- §2.1 — revise — mismatch — "every guardian write is checked" was false; application creation performs no ownership check at all (`user_id` is bound and never compared), so the sentence is now scoped to writes on an already-existing application/account, with the creation exception stated — `routes/applications.py:35`
- §4 preamble — revise — mismatch — "Requests that bring a brand-new resource into existence respond with 201" was false for award acceptance, which mints an `Account` yet returns 200 + operation summary — `routes/applications.py:339`
- §3.2 — revise — mismatch — PRD pinned only unknown flag codes as `ERR_INVALID_REQUEST`; a repeated code in a flag list is also rejected rather than collapsed, and a non-array is rejected too — `validators.py:158`
- §2.3 — insert — ambiguity — empty-valued filter params are absent; out-of-enum filter values are `ERR_INVALID_REQUEST`; identifier filters match by exact case-sensitive equality and an unknown id yields an empty page — `validators.py:230`
- §2.3 — insert — ambiguity — no list endpoint scopes results by caller identity; a Guardian sees every application/account — `routes/applications.py:113`, `routes/accounts.py:46`
- §2.5 — insert — ambiguity — `to_iso8601` mandatory, normalised to 3 fractional digits, may move the clock *backwards* (no comparison against the old value), `data` carries `current_utc` alone, no `version` changes — `routes/program_years.py:309`
- §2.7 — revise — ambiguity — `expected_account_version` is non-negative; missing/null/bool/non-int/negative is `ERR_INVALID_REQUEST` at the shape step, not the version guard — `routes/accounts.py:122`
- §3.1 — insert — ambiguity — duplicate `label` → `ERR_INVALID_REQUEST`, exact case-sensitive comparison — `routes/program_years.py:49`
- §3.1 — insert — ambiguity — window/term/label cross-field checks all live in the shape step, all report `ERR_INVALID_REQUEST`, and run only after every individual field is accepted — `routes/program_years.py:45`
- §3.1 — revise — ambiguity — exact `code` shape (leading A–Z, underscore-separated uppercase-alnum segments), `name` non-empty, malformed *and* duplicate code both `ERR_INVALID_REQUEST` — `routes/students.py:73`, `validators.py:22`
- §3.2 — insert — ambiguity — all three student string fields non-empty; `date_of_birth` only calendar-checked, never compared to the clock; zero duplicate detection; no status field — `routes/students.py:21`
- §3.2 — revise — ambiguity — all *three* award figures at 0 (PRD said "both"), plus `priority_tier`/`priority_score` 0 and `waitlist_position`/`submitted_at`/`acceptance_deadline_at` null — `routes/applications.py:87`
- §3.2 — insert — ambiguity — cross-reference that ownership is not one of the creation gates — `routes/applications.py:35`
- §3.3 — insert — ambiguity — `verified_category_flags` is mandatory, not defaulted; omitting it is `ERR_INVALID_REQUEST` — `routes/applications.py:181`
- §3.3 — insert — ambiguity — the ineligible *row* also carries 0 for tier/score/award, the ladders are not run, and no verified attribute is copied onto the application — `routes/applications.py:220`
- §3.4 — insert — ambiguity — `awarded_application_ids` is in rank order; both arrays empty when there are no candidates — `routes/program_years.py:143`
- §3.5 — insert — ambiguity — the four rollover/forfeiture fields also start at 0; `version` is 1 and `updated_at` == `created_at` — `routes/applications.py:296`
- §3.5 — insert — ambiguity — earliest-created matching review governs; outgoing account `version` +1 while the incoming account stays at 1; a non-`ACTIVE` prior account carries nothing — `routes/applications.py:322`
- §3.5 — revise — ambiguity — `quarter` must also not exceed 4 (a fifth run is `ERR_INVALID_STATE_TRANSITION` even though 5 == 4+1); absent/negative fails the shape step before the year is resolved — `routes/program_years.py:163`
- §3.5 — insert — ambiguity — ordering of `expired_application_ids`, `promoted_application_ids` and `skipped_account_ids`, and that promotions are a subsequence of expiries — `routes/program_years.py:168`
- §3.7 — insert — ambiguity — missing `invoice_reference` on `REIMBURSEMENT` is `ERR_INVALID_REQUEST` raised *before* existence resolution (so it beats `ERR_ACCOUNT_NOT_FOUND`); whitespace-only rejected — `routes/accounts.py:126`
- §3.7 — insert — ambiguity — the six null fields on the new request, the account's `updated_at` refresh, and that filing is gated on account status alone (a `CLOSED` programme year does not block it) — `routes/accounts.py:171`
- §3.8 — insert — ambiguity — `reason` mandatory and non-empty under both status actions though only SUSPEND stores it; response is the updated `Account`, not a summary — `routes/accounts.py:89`
- §3.9 — insert — ambiguity — processed accounts stay `ACTIVE`; `SUSPENDED`/`CLOSED` accounts are skipped wholesale (no counters, no version bump, no application completion); `resolved_misuse_case_ids` in creation order — `routes/program_years.py:255`

Left undocumented, with reasons: ordering among the three `create_program_year` cross-field checks and among `create_expense_category`'s code-shape vs uniqueness checks (all collapse to `ERR_INVALID_REQUEST`, so unobservable — only the "after per-field validation" position was pinned); `waitlist_position = None` written onto applications the award run offers (a no-op, they already hold null); absence of a `window_close_at` clock check on the award run (PRD makes no claim and §3.4 already pins that leaving `WINDOW_OPEN` closes intake); `committed_in_category`'s `exclude_id` parameter (dead on the filing path, live only in pass 3's approval re-check); and `_terms_intersect` / `is_open_request` / `recount_seats` internals (already pinned by §2.9, §2.10 and pass 1).

### Pass 3 — remaining routes (`providers.py`, `purchase_requests.py`, `misuse_cases.py`, `appeals.py`, `renewal_reviews.py`)

No `cp` performed (confirmed). 128,033 chars out; 25 changes — **23 ambiguity-pins, 2 mismatch-revisions**.

- §3.6 — revise — ambiguity — `ein` is exactly nine decimal digits and both a malformed and an already-registered value are rejected as `ERR_INVALID_REQUEST` at the shape step — `providers.py:27-31`
- §3.6 — insert — ambiguity — `flags` is a mandatory field (empty array legitimate); omission or a repeated indicator is `ERR_INVALID_REQUEST` — `providers.py:68`, `validators.py:158`
- §3.6 — insert — ambiguity — `authorized_category_codes` is a mandatory, possibly-empty array of non-empty strings, duplicates stored as supplied; the rung-9 code check runs before the state guard and the fraud bar — `providers.py:113-125`
- §3.6 — revise — **mismatch** — `reason` is mandatory non-empty under all three sanction actions but is stored only under `PROBATION`/`DELIST`; `REINSTATE` discards it and nulls `sanction_reason`; all three answer with the `Provider` record — `providers.py:141-162`
- §3.7 — insert — ambiguity — an omitted/null `reason` leaves `decision_reason` unchanged, whitespace-only is `ERR_INVALID_REQUEST`, and every decision branch returns the request record — `purchase_requests.py:109,140,174`
- §3.7 — insert — ambiguity — the reimbursement auto-settle shortcut skips the settlement conditions and the SoD bar, stamps the approver as `settled_by_user_id`, still runs duplicate detection, and still returns the request record — `purchase_requests.py:147-148`
- §3.7 — insert — ambiguity — `claimed_amount_cents` 0 → `ERR_CLAIM_AMOUNT_MISMATCH`, negative → `ERR_INVALID_REQUEST` — `purchase_requests.py:182,192`
- §3.7 — insert — ambiguity — the auto-opened case names **this** settlement's request as `purchase_request_id` (not the earlier `PAID` one), carries a server-authored narrative, and is opened at most once — `purchase_requests.py:47-100`
- §3.7 — insert — ambiguity — `opened_misuse_case_id` is null when nothing fired — `purchase_requests.py:235`
- §3.8 — insert — ambiguity — the named purchase request is resolved for existence only (need not belong to the account) and the account's status never gates case opening — `misuse_cases.py:46-48`
- §3.8 — revise — ambiguity — the five clawback figures plus `reviewed_by_user_id`/`adjudicated_by_user_id` are all null at creation — `misuse_cases.py:60-66`
- §3.8 — insert — ambiguity — the adjudication `rationale` is validated then discarded; the case has no rationale field — `misuse_cases.py:119`
- §3.8 — insert — ambiguity — a dismissal is not subject to the SoD bar — `misuse_cases.py:129-133`
- §3.8 — insert — ambiguity — substantiation on an already-`SUSPENDED`/`CLOSED` account still succeeds but runs no suspension, no void and no hold release; only the provider effect fires — `misuse_cases.py:143-145`
- §3.8 — insert — ambiguity — both adjudication branches return the `MisuseCase` record, not a cascade summary — `misuse_cases.py:133,153`
- §3.8 — insert — ambiguity — the `ACCOUNT_DEBIT` ledger row is written unconditionally, including a zero-amount row — `misuse_cases.py:178-180`
- §3.9 — insert — ambiguity — neither evidence field is enforced at filing; `next_program_year_id` need not differ from or follow the account's own year — `renewal_reviews.py:30-35`
- §3.9 — insert — ambiguity — the five approval conditions are evaluated in §2.8 ladder order (target-year status before the review's own state) — `renewal_reviews.py:124-144`
- §3.9 — insert — ambiguity — the minted successor's remaining fields: `provisional_award_cents`/`final_award_cents`/`priority_score` 0, `waitlist_position`/`submitted_at` null, `appeal_round_count` 0 — `renewal_reviews.py:164-177`
- §3.9 — insert — ambiguity — `prior_account_status` is informational; account status neither gates nor changes on either decision — `renewal_reviews.py:104,119,194`
- §3.9 — insert — ambiguity — the subject-reference pairing is a rung-3 shape rule, `ERR_INVALID_REQUEST` before any reference is resolved — `appeals.py:31-46`
- §3.9 — revise — **mismatch** — the appeals endpoint admits both `Guardian` and `Provider` for every `subject_type`; the division is enforced by ownership (`ERR_NOT_ACCOUNT_HOLDER` / `ERR_NOT_ASSIGNED_PROVIDER`), never `ERR_FORBIDDEN_ROLE` — `appeals.py:23,52-65`
- §3.9 — revise — ambiguity — delisting appeal filing: `ERR_INVALID_STATE_TRANSITION` off-state, `round_number` from prior provider appeals, provider record untouched by the filing — `appeals.py:86-91`
- §3.9 — insert — ambiguity — a clawback reversal keeps the other assessed figures and does not un-reverse the purchase request or restore `lifetime_spent_cents` — `appeals.py:184-200`
- §3.9 — insert — ambiguity — an overturned delisting leaves `surveillance_score`/`substantiated_case_count` as they stand, so reinstatement can still be blocked at ≥75 — `appeals.py:201-204`

Left undocumented, with reasons: renewal filing's absence of a guardian-ownership check (already uniquely pinned because §2.8 rung 14 enumerates the ownership endpoints exhaustively and omits it); list ordering / empty-filter / unknown-enum filter semantics / no-identity-scoping in these five modules (pinned globally in §2.3); screening rows and clawback entries carrying only `id` + `created_at` (pinned by §2.4); Guardian and `ExpenseReviewer` read access (covered by the §4 role table plus §2.3); unreachable defensive branches (missing student behind an account in a renewal approval, `store.*.get(... or "")` returning `None` in the appeal cascade); and `POST /purchase-requests/{id}/settle` ignoring any request body (PRD names no payload, which already admits only the impl behavior).

### Pass 3 final consistency check — PASS

Structure intact (`## 1`–`## 5`, all of §2.1–§2.11 and §3.1–§3.9, the §4 endpoint table, §5); the file ends at a real section boundary (last line is the final `| ERR_CLAIM_AMOUNT_MISMATCH | 422 |` row) with exactly 38 `ERR_*` rows; sentinels from passes 1–2 all verified present (the twenty-character `api_request_id` wording, the trailing-slash sentence, the award-acceptance 200 exception, the §2.9 "open purchase request" definition, the 404/405 `ERR_INVALID_REQUEST` sentence, the unchecked-application-creation ownership carve-out, and the `2026-08-01T00:00:00.000Z` default clock literal).

### Orchestrator independent verification

- `wc`: PRD.md and PRD_FINALIZED.md 532 lines / 106,380 chars; PRD_COMPLETED.md 532 lines / 128,033 chars. `diff PRD_FINALIZED.md PRD_COMPLETED.md` → 120 changed lines (60 `<` / 60 `>`), so the Step 9 scan demonstrably ran (the byte-identical failure mode did not occur).
- Structure re-checked independently: 5 `## ` headings, 38 `ERR_*` rows, tail ends on the closing error row.
- Sentinel spot-checks passed (`api_request_id` "exactly twenty characters" wording, one `trailing slash` sentence, one `open purchase request` definition, the `2026-08-01T00:00:00.000Z` literal).
- Leak check on PRD_COMPLETED.md: no occurrence of "harder than expert", "expert level", or "SCAFFOLD".
- `find` over `workspace/implementation/`, `test_suite/` and `test_helpers/` for files modified after the green sweep (10:04:18Z, excluding `results.*.json`) returned **nothing** — Step 8 and all three Step 9 passes touched documentation only, so Step 7's eight 105/105 result sets remain valid evidence for the shipped artifact. All 8 `results.$i.json` files are present.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` written; Steps 1–9 all done.
