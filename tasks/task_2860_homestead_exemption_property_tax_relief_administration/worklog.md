# Worklog — task_2860_homestead_exemption_property_tax_relief_administration

## Step 1: Create task directory — 2026-09-05T07:47:39.217Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2860_homestead_exemption_property_tax_relief_administration` and its `workspace/` subdirectory. Output path was pre-assigned by the invoking command (index 2860 fixed by scenario number); no index scan performed, no other task directory created.

## Step 2: Generate scaffold — 2026-09-05T10:02:00.000Z

All three scaffold artifacts are complete and the lint is clean.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2860_homestead_exemption_property_tax_relief_administration/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2043 | 133,871 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2193 | 152,595 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5146 | 347,855 |

**§1.0–§1.7 (SCAFFOLD.yaml)** — flat top-level keys only, neither design key present. `api_prefix: ""` (absolute paths). 13 entities, 6 state machines, 2 `concurrency_rules` (`determination-stale-parcel`/`expected_parcel_version`, `grant-port-stale-grant`/`expected_grant_version`, both 412), 7 calculations (two with dual variants: `retroactive_refund_amount` GROSS_PROVISIONAL/NET_FINAL and `fraud_risk_score` SCREENING_SNAPSHOT/ADJUDICATION_REPLAY), 34 priority-ordered validations, 44 endpoints, 55 errors, 9 roles with a segregation-of-duties role model. Profile: `compliance_audit` + `ledger_reconciliation`, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers`, `consistency_model: immediate`, `difficulty_level: expert_plus`.

**§1.8** — 9 rule_ids × 2 instances = 18 instances (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).

**§1.9** — all 9 guide sections, 82 instances (63 with full recipes + 19 `excluded_because` stubs): entities 12, state_machines 13, calculations 13, validations 9, endpoints 8, errors 15, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1. RBAC uses the guide's own vocabulary (`role_denied`, `ownership_check`, `segregation_of_duties` ×2, `unauthenticated`); the complexity-layer section gives each `concurrency_rules` entry its own OCC instance plus a `rate_threshold_triggers` instance that probes RISK_SUBSTANTIATION_THRESHOLD 60 from both reachable sides (replay 55 → 422, then 70 → SUBSTANTIATED with total_assessed 246750).

**Verification**
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1139 calls scanned across both design files).
- All 55 declared error ids are referenced by at least one design instance; 0 unplaced.
- All 44 §1.5 endpoints are exercised by at least one recipe call (the last six list/sub-resource reads were covered by two added `endpoints` instances).
- All 100 instance names are unique across the union of both design files; every stub's `difficulty_instance` resolves to a real §1.8 instance name, and no stub carries a `test_recipe`.

**Notes for the orchestrator**
- Money/score literals throughout were computed by executing the §1.3 formulas (canonical P1: capped/assessed 33,600,000; HOMESTEAD benefit 8,400,000; per-year saving 105,000; recovery total 246,750; 2027 roll → capped 34,200,000 → benefit 8,550,000).
- `scenario:` in SCAFFOLD.yaml begins with the verbatim `Generate task harder than expert level!` line as instructed; per the known leak path, strip that single line before the PRD step so the directive does not reach PRD.md.

**Orchestrator post-step action (difficulty-directive leak guard):** the `Generate task harder than expert level!` line was stripped from `SCAFFOLD.yaml`'s `scenario:` block by the orchestrator immediately after this step (SCAFFOLD.yaml 2043 → 2041 lines). Verified `grep -n "harder than expert"` now returns no hits in any of the three scaffold files, so the directive cannot reach PRD.md via the scaffold. The directive remains recorded here in the worklog only.

## Step 3: Copy shared files — 2026-09-05T10:04:18.954Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T10:19:00.000Z

All three Hard Contracts verified clean on the final file. PRD generation for task 2860 is complete.

**Deliverable:** `workspace/PRD.md` — **448 lines / 99,949 characters**. Built incrementally (one `Write` + 12 `cat >> ... <<'PRDEOF'` appends), so no output-cap truncation. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was consulted. Scratch confined to `/tmp/task_2860_prd/`.

**Section list**
- §1 Introduction (county-assessor pain points; scope; the two driving properties — reproducibility and segregation of duties)
- §2 Global Specifications: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Record Properties · 2.5 The Logical Assessment Clock · 2.6 Money, Basis Points and Rounding Discipline · 2.7 The Parcel Value Decomposition · 2.8 Segregation of Duties Across the Exemptions Unit · 2.9 Stale-Version Preconditions · 2.10 The Order in Which a Request Is Screened (all 34 rungs, numbered) · 2.11 The Conserved Relief Ledger
- §3 Business Logic & Workflows: 3.1 Building the Roll · 3.2 Intake · 3.3 Cross-Matching Against External Registries · 3.4 Determination · 3.5 The Supervised Life of a Grant · 3.6 Portability · 3.7 Retroactive Claims and Refund Settlement · 3.8 Fraud Detection, Recovery Assessment and Collection · 3.9 Notices, Appeal Rights and the Hearing Docket
- §4 Endpoint Definitions (status-code paragraph + 44-row, 4-column table)
- §5 Error Code Catalogue (55-row, 2-column table)

**Coverage:** 13 entities · **44/44** endpoint rows · **55/55** error rows · **34/34** validations as an explicit ordered priority ladder in §2.10 · **7/7** calculations as step-by-step prose (incl. both dual variants of `retroactive_refund_amount` and `fraud_risk_score`) · **6** state machines / **31/31** transitions · **9/9** roles · **2/2** OCC rules (`expected_parcel_version`→`ERR_STALE_PARCEL_VERSION`, `expected_grant_version`→`ERR_STALE_GRANT_VERSION`, both 412).

**Hard Contract reports**
- **Contract 1 — Field-Name Coverage: PASS.** `entities[].fields` 119 required / 119 present / 0 missing. Endpoint `request_body` + `query_params` + `path_params` 86 required / 86 present / 0 missing. 136-name union fully covered. All enum values, all state values, all 55 error ids, all 9 role names present in backticks; plus roll-run outputs (`parcels_rolled_count`, `certifications_lapsed_count`, `grants_suspended_count`, `grants_lapsed_count`), `current_utc`, `record_id`, `to_iso8601`, `target_tax_year`.
- **Contract 2 — Rule Coverage: PASS.** 34 validations with priority expressed as explicit ordering prose and `applies_to` scopes named; 2 concurrency rules with write endpoint, version field, error id and 412 all stated; 31 transitions with guards and side-effects; 7 calculations with pinned step order (waterfall-before-interest is called out as non-reorderable); every field-level default and terminality rule stated (including `APPROVED` as the application's only terminal status and the fraud-case ledger fields starting at 0).
- **Contract 3 — §3 Path Purity: PASS.** 898 backtick tokens scanned in §3; 0 starting with `/`; 0 bare HTTP-method tokens; 0 method+path tokens; 0 raw endpoint paths as substrings.

§2.2 confirmed byte-identical to `section-2.2-response-structure.md` (`cat`-ed, not retyped).

**Tail is complete.** File ends on the final complete row of the §5 table — `| ERR_PAYMENT_EXCEEDS_BALANCE | 422 Unprocessable Entity |` — with no mid-sentence cut and no audit footer (Hard Contract reports live here in the transcript only, per the skill).

**Three scaffold ambiguities resolved**
1. **`ERR_TAXPAYER_BARRED` status conflict** — `errors[]` says 403, validations priority 10 says 409. §5 uses 403 (the `errors[]` catalogue is §5's source of truth) and the prose deliberately states no HTTP status for it, so the PRD contains no contradiction.
2. **`ERR_NOT_RESOURCE_OWNER` scope** — validation priority 3's `applies_to` names 6 endpoints while `roles[].ownership_rule` implies every Taxpayer request. §2.1 states the general ownership-resolution rule (the superset); §2.10 rung 3 enumerates the six explicitly declared operations.
3. **Appeal-decision duty separation** — transitions attach the check only to `GRANT`/`DENY` while validation priority 4 lists the decide endpoint unqualified. Written as applying to every appeal decision, naming the comparands (`determined_by_user_id` for `DENIAL` notices, `substantiated_by_user_id` for `RECOVERY_ASSESSMENT` notices).

**Orchestrator verification of the known truncation failure mode:** independently ran `wc -l -c` (448 / 99,949), `tail -18` (ends on the complete final `ERR_PAYMENT_EXCEEDS_BALANCE` table row — a real section boundary, not a mid-sentence cut), and coverage greps: 55 `ERR_` rows in §5 / 55 distinct `ERR_` tokens PRD-wide vs 56 in SCAFFOLD.yaml, the only difference being the scaffold's `ERR_XXX` template placeholder; 44 endpoint rows in §4. Section headings present: §1–§5. Leak grep for `harder than expert` / `expert level` / `scaffold` in PRD.md returned no hits. PRD accepted without regeneration.

## Step 6: Generate implementation — 2026-09-05T10:52:00.000Z

Implementation complete and verified. Everything lives in `workspace/implementation/`.

## Modules (2,966 lines total)

| File | Lines | Role |
|---|---|---|
| `app.py` | 60 | `create_app()`, blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers, `0.0.0.0:$PORT` |
| `errors.py` | 81 | 55-code catalogue (error_id → HTTP status), `fail()` |
| `db.py` | 133 | in-memory collections, logical clock, `insert/get/rows/find/touch/public` |
| `envelope.py` | 63 | `meta`/`response_type`/`data` envelope, `req_` id, pagination meta |
| `validate.py` | 246 | 9-role auth, `endpoint()` decorator, scalar/enum/date/instant validators, pagination |
| `enums.py` | 76 | every declared enumeration |
| `calc.py` | 269 | `Fraction` + `round_half_up` arithmetic: cap, assessed basis/freeze, benefit, tiers, refunds, recovery, risk score, portable allocation |
| `services.py` | 211 | notices, taxpayer ledger re-derivation, grant status transitions, decomposition re-run, docket counts |
| `routes_roll.py` | 343 | programmes, parcels, taxpayers, ownership records (+ half-open geometry & supersession), clock, registry injection |
| `routes_applications.py` | 447 | applications, submit, respond-info, verification checks, income certifications, determine |
| `routes_grants.py` | 450 | grants, portability, compliance actions, retroactive claims, annual assessment roll |
| `routes_fraud.py` | 244 | fraud cases, adjudication, recovery actions |
| `routes_appeals.py` | 327 | notices, hearing dockets, appeals, scheduling, decisions |
| `start.sh` | 15 | guarded pip install, `export PORT`, `exec python3 app.py` (exec'd, so the harness kills the real server PID) |
| `requirements.txt` | 1 | `flask>=3.0.0` |

## Conformance checks run
- **Endpoints: 44/44.** Programmatic diff of the PRD §4 table against registered routes — zero missing, zero extra.
- **Error catalogue: 55/55**, every HTTP status matching the PRD table, and every code is actually reachable in the code (none dead).
- **Entity shapes:** live GET of one row of all 13 entities diffed against `SCAFFOLD.yaml` field lists — zero extra fields, zero missing, and `VerificationCheck` correctly carries only `id`/`created_at` (immutable, `common_fields: false`).
- **Fresh boot:** empty collections, no seeded data, clock pinned at `2026-08-01T00:00:00.000Z`.

## Notable interpretation decisions
- `api_request_timestamp` and every stamped instant come from the logical clock (PRD §2.5 forbids wall-clock reads). Clock body field is `to_iso8601`, response reports `current_utc`.
- A monotonic internal `_seq` is the final deterministic tie-break wherever `created_at` ties (common under a logical clock); internal `_`-prefixed keys are stripped by `db.public()`.
- Screening-order circularity resolved with the PRD carve-out: path/body resource resolution (404) → ownership/SoD → body shape → body FKs → OCC (412) → state (409) → business rungs.
- `improper_end_tax_year > assessment_tax_year` and uniqueness violations (`program_code`, `priority_rank`, `apn`) map to `ERR_INVALID_REQUEST` (no catalogued code); rejected requests mutate nothing, including `adjudication_risk_score` on a below-threshold SUBSTANTIATE.
- `RECERTIFICATION_LAPSE` suspension mails no notice (PRD §3.5 limits the SUSPENSION notice to the fraud and occupancy paths); the annual roll snapshots pre-existing lapse suspensions so a grant cannot suspend and lapse in the same run.
- Port reads the destination's assessed basis *before* inserting the child grant; that pre-port basis caps the allocation and feeds the child's `benefit_amount_cents`. Null `portable_balance_cents` → `ERR_PORTABLE_BALANCE_EXHAUSTED`.
- Appeal GRANT compensates by `subject_type`; a granted appeal restores a SUSPENDED **or** REVOKED grant, and a RECOVERY_ASSESSMENT grant abates the ledger and reverses the collected total.

## Smoke test result — all green
Five scenario scripts (scratch only, under `/tmp/task_2860_impl/`) covering the full lifecycle. Hand-checked arithmetic all matched, e.g.:
- Cap/basis: base 20,000,000 @ 200bps × 2 yrs → capped 20,800,000, market 30,000,000 → assessed 20,800,000; relief 5000bps ceilinged at `max_exempt` 5,000,000 → exempt 5,000,000 / taxable 15,800,000 / `PARTIALLY_EXEMPT`, parcel `version` 2.
- Income tier: 8,500,000 vs limit 10,000,000 → `TIER_PARTIAL`/5000bps, ownership 5000bps → benefit 900,000.
- Retroactive claim 2023–2025: gross 187,500 → net 187,500 + interest 15,000 = payable 202,500.
- Portability: transfer over-ask ceilinged to destination basis 15,600,000, source balance 20,800,000 → 5,200,000 (conservation invariant holds).
- Fraud: screening score 100 (DMV+USPS+INCOME_DOR mismatches + multi-parcel homestead), substantiation back_tax 125,000 / penalty 12,500 / interest 9,375 / total 146,875 (per-year rounding before summation).
- Roll 2027: cert LAPSED → grant SUSPENDED `RECERTIFICATION_LAPSE`; roll 2028 → LAPSED; reinstate gated by `ERR_INCOME_CERTIFICATION_REQUIRED` then `ERR_GRANT_ALREADY_TERMINAL`.
- Error paths confirmed: `ERR_UNAUTHENTICATED`, `ERR_UNAUTHORIZED_ROLE`, `ERR_NOT_RESOURCE_OWNER`, `ERR_SEGREGATION_OF_DUTIES` (determine / claim decide / recovery / appeal decide), `ERR_STALE_PARCEL_VERSION`, `ERR_STALE_GRANT_VERSION`, `ERR_OCCUPANCY_INTERVAL_OVERLAP`, `ERR_DUPLICATE_PRIMARY_RESIDENCE`, `ERR_HEARING_SLOT_CONFLICT` (15-min buffer + session bounds), `ERR_DOCKET_CLOSED`, `ERR_APPEAL_ALREADY_EXISTS`, `ERR_NOTICE_NOT_APPEALABLE`, `ERR_PAYMENT_EXCEEDS_BALANCE`, `ERR_CASE_ALREADY_ADJUDICATED`, `ERR_RISK_SCORE_BELOW_THRESHOLD`, pagination bounds, bad enums, 404/unknown-route envelopes.

Housekeeping: all smoke servers killed by explicit PID (no pattern `pkill`), ports free, `__pycache__` removed, nothing written outside `implementation/` — `worklog.md`, `PRD.md`, `test_helpers/` and `test_suite/` untouched. One incidental finding: port 39862 on this host is held by another concurrent pipeline, so I used 44793/44811.

**Orchestrator note on step ordering:** Steps 5 and 6 were launched in immediately consecutive messages rather than a single message. The orchestrator verified before launching Step 6 that the task root still contained only `SCAFFOLD*.yaml`, `worklog.md` and `workspace/` — `test_helpers/` and `test_suite/` did not yet exist — so the implementation generator retained full physical isolation from the test suite, which is the property the single-message launch is there to guarantee.

## Step 5: Generate unit tests — 2026-09-05T12:07:00.000Z

Queue A and queue B are both complete, and the four remaining corner instances landed this session.

## Deliverables (both at the TASK ROOT, nothing under `workspace/`)

`test_helpers/` — 9 files, 2430 lines
`__init__.py` 69, `api_client.py` 451, `api_errors.py` 154, `assertions.py` 283, `constants.py` 159, `factories.py` 527, `fixtures.py` 680, `test_users.py` 86, `types.py` 21

`test_suite/` — 12 files, 7530 lines
`conftest.py` 74, `test_01_roll_setup_and_parcel_valuation.py` 610, `test_02_ownership_and_occupancy_registry.py` 403, `test_03_intake_and_cross_matching.py` 499, `test_04_determination_and_grant_minting.py` 1471, `test_05_grant_supervision_and_roll.py` 272, `test_06_portability_transfers.py` 659, `test_07_retroactive_claims_and_refunds.py` 666, `test_08_fraud_investigation_and_recovery.py` 1175, `test_09_notices_appeals_and_hearings.py` 838, `test_10_access_control_and_ownership_scoping.py` 456, `test_11_pagination_and_listing_contracts.py` 407

Verified by `find workspace -name test_helpers -o -name test_suite` → empty. `__pycache__` removed. `workspace/PRD.md`, `worklog.md` and `workspace/implementation/` untouched.

## Tests emitted: 99

- **Queue A (difficulty index): 36 tests** — all 18 rule instances translated, exactly 2 tests each.
- **Queue B (corner index): 63 tests** — all 63 non-stub instances translated, ≥1 each. Section totals: entities 12, state_machines 11, calculations 8, validations 6, endpoints 8, errors 9, rbac 5, cross_cutting_complexity_layers 3, consistency_model 1.
- **19 `excluded_because:` stubs not translated**; every stub's `difficulty_instance` cross-reference was programmatically checked and all 19 resolve to a real §1.8 instance name.
- **0 instances skipped** — every non-stub instance passed the PRD-first two-condition filter, so there are no gaps to report.

Added this session: the roll-run stale-parcel-version determination and the immediate-consistency determination response (both in `test_04`), the stale `expected_grant_version` second port (`test_06`), and the 55-versus-70 substantiation threshold with the bespoke corrected-voter/standing-income check log (`test_08`, new `_corrected_voter_and_income_lie_world` helper).

## Verification passes run

- **Design tags**: 99/99 tests carry exactly one `Design:` line and it is the last line of the docstring; 0 dangling tags, 0 stub-tagged tests, 0 dual-tagged tests.
- **PRD citations**: an AST + normalisation checker split every quoted span on `...` and matched each fragment against `workspace/PRD.md`. This caught **9 non-verbatim fragments left by earlier sessions**, now all corrected: two paraphrased §2.4 `created_at`/`updated_at` definitions in `test_01`; a paraphrased §3.4 respond-info sentence, a paraphrased "determination is legal only from UNDER_REVIEW" sentence and a wholly paraphrased "three ordered consequences" approval cascade in `test_04`; a truncated §3.5 reinstatement clause in `test_05`; and two §4 table citations in `test_10` that quoted reformatted table cells. Final state: **240 quoted fragments, 0 non-verbatim.**
- **pyflakes clean** across `test_suite/*.py`, `test_suite/conftest.py` and `test_helpers/*.py` (pruned the leftover unused imports in `test_01` and `test_02`); `py_compile` OK; `import test_helpers.*` resolves; no duplicate test function names within or across files.
- **No occurrence of the word "scaffold"** anywhere in the generated code or docstrings.

No smoke run against a server was attempted, since the implementation generator is still working under `workspace/implementation/`.

**Orchestrator verification:** confirmed `test_helpers/` and `test_suite/` both sit at the task root and that `find workspace -name test_helpers -o -name test_suite` returns nothing, so neither directory drifted under `workspace/` (a known failure mode of this step). `workspace/` contains exactly `INSTRUCTION.md`, `PRD.md`, `implementation/`.

## Step 7: Run tests and iterate — 2026-09-05T12:29:58.887Z

All 8 rounds now pass 99/99. Here is the final report.

## Summary

**Iterations run:** 2 sweeps (iteration 1 = baseline diagnosis, iteration 2 = verification after fixes), plus per-test local triage against a hand-launched server on port 12860 (killed by PID afterwards).

**Final sweep evidence** (`workspace/implementation/results.$i.json`, written 12:27, ~180 s per round):

| round | passed/total | failed | errors |
|---|---|---|---|
| 1–8 | 99/99 each | 0 | 0 |

Iteration 1 was deterministic: all 8 rounds 85/99 with the identical union of 14 failures — no load-induced flakiness anywhere.

**Tests deleted:** none. No test was skipped, xfailed, or downgraded from an `error_id` to an HTTP status.

**Fixes applied to `test_helpers/`:** none — every defect lived in `test_suite/`.

**Fixes applied to `test_suite/`** (no `implementation/` file was touched; all mtimes remain pre-session):

- `test_03_intake_and_cross_matching.py` — `test_a_second_cross_match_appends_a_row_instead_of_rewriting_the_first`: added `expected_status=201` to both `create_verification_check` calls. PRD §6 lists "a verification check" among the creations that "return `201 Created`"; the sibling test at line 458 already did this.
- `test_04_determination_and_grant_minting.py`
  - `test_only_the_income_tested_programme_demands_a_certification_on_file`: supplied the omitted `taxable_value_cents=20800000` (call raised `TypeError`).
  - `test_the_asset_ceiling_is_only_reached_once_the_income_tier_has_resolved`: advanced the logical clock before creating the second certification. Both certifications were minted at the same pinned instant, so PRD §3.3's selector ("greatest `created_at`", tie broken by "greatest `version`") legitimately picked the *first* row — already at version 2 from its own certification — and the impl was right to leave the second `PENDING`.
- `test_05_grant_supervision_and_roll.py`
  - `_revoked_grant`: dropped the fraud case and revoke straight from `ACTIVE` (PRD §3.5: "Revocation is admissible from `ACTIVE` or from `SUSPENDED`"). The old fixture opened an investigation and then issued a compliance action, which §2.10 rung 11 correctly refuses with `ERR_FRAUD_HOLD_ACTIVE` on `POST /exemption-grants/{id}/compliance-actions`.
  - `test_suspending_the_senior_grant...`: supplied the omitted `assessed_value_cents=1000000` (`TypeError`).
- `test_06_portability_transfers.py` — one `TypeError` fix (`taxable_value_cents=0` on the worthless destination) plus **STEP 1c trimming of 8 assertion sites** that hinge on a rule PRD does not uniquely determine: which basis feeds the ported child's `benefit_amount_cents`. §3.6 says only that it is "computed by the six-step benefit formula of §3.4 against the destination parcel", and §3.4 step one says "the parcel's `assessed_value_cents` — as it stands after the cap-and-freeze step of the decomposition". Since §2.7 makes the decomposition the *only writer* of that stored field and §3.6 runs the decomposition "**Finally**", a faithful implementer can read the destination's pre-transfer basis (impl: 40000000 → benefit 4000000) or the freeze-applied basis (tests: 33600000 → 3360000); both are articulable, so the derived figures were removed and the unambiguous parts kept — child `frozen_value_cents`/`portable_balance_cents`/`ACTIVE`/`ported_from_grant_id`, source `TRANSFERRED`, all version counts, both `ERR_*` precedence checks, the destination's post-freeze `assessed_value_cents`, and the §3.6 conservation identity. Deletion category: **branch-asymmetric / order-of-evaluation silence** on the child benefit basis.
- `test_08_fraud_investigation_and_recovery.py`
  - `test_a_two_factor_replay...`: `adjudication_risk_score is None` → `== 0`. PRD §3.8 verbatim: "`back_tax_cents` … and `adjudication_risk_score` all start at 0".
  - `test_clearing_a_case...`: supplied the omitted `assessed_value_cents=33600000` (`TypeError`).
- `test_09_notices_appeals_and_hearings.py` — `_denied_claim_whose_slot_was_taken`: record fresh `VOTER_REGISTRY`/`DEED_REGISTRY` checks on the *denied* application after the registry rows are injected. Its only voter row still read `NO_RECORD`, so the reopened claim was correctly refused at the residency gate before exclusivity; PRD §3.3 ("a `MISMATCH` … subsequently corrected by a fresh check … does not block approval") is what makes `ERR_DUPLICATE_GRANT` the first failure.

**Notable non-findings:** the implementation needed no change at all — all 14 failures were test-side (4 plain `TypeError`s from an omitted `assert_parcel_decomposition` argument, 3 PRD-contradicting assertions/fixtures, 1 wrong expected status, 6 resting on the non-derivable child-benefit basis). Storage remains in-memory dicts with no seeding. I did not read any `SCAFFOLD*.yaml` and did not read or write `worklog.md`.

**Orchestrator independent verification of the sweep artifacts** (the known "clean sweep with no artifacts" failure mode): all 8 `workspace/implementation/results.$i.json` exist, are ~32.7 KB each, are stamped 12:27 (after the fix session, not stale), and parse to `passed=99 failed=0 errors=0 total=99` in every one of the 8 rounds. Cross-checks: `grep` for `pytest.mark.skip` / `pytest.mark.xfail` across `test_suite/` and `test_helpers/` returns 0 hits; the suite still holds **99 test functions with 99 `Design:` tags** (nothing was quietly dropped — the count matches Step 5's 99 exactly, consistent with "tests deleted: none"); `test_suite/` is 7527 lines vs Step 5's 7530, i.e. a 3-line net delta consistent with assertion trimming rather than test removal. Every `implementation/*.py` and `start.sh` mtime is 10:26–10:39, all pre-dating the Step 7 session, independently confirming the "0 implementation fixes" claim.

**Step 8 skip-condition adjudication:** the skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Implementation fixes were 0, but Step 7 made substantial `test_suite/` fixes — including the STEP 1c trim of 8 assertion sites over a genuine PRD silence (which basis feeds a ported child grant's `benefit_amount_cents`). Step 8 therefore **runs**, with that silence as its primary target.

## Step 8: Finalize PRD — 2026-09-05T12:35:35.776Z

Done. The patch is a single surgical edit.

## Line counts
- `PRD.md`: 448 lines / 99,949 chars
- `PRD_FINALIZED.md`: 448 lines / 100,398 chars
- Delta: **0 lines (0.0%)**, +449 chars (+0.45%) — one sentence-pair appended inside the existing §3.6 paragraph; file tail (error catalogue) intact.

## Change
- **§3.6 (portability, child-grant fields)** — *revise* — pinned that step one of the six-step benefit formula for the ported child grant reads the destination parcel's **pre-transfer** assessed basis (the same quantity that supplied the third allocation ceiling, read before the child is inserted), not the lower post-freeze basis the closing decomposition leaves; and that `benefit_amount_cents` is written once at insertion and never rewritten by a later decomposition — `implementation/routes_grants.py:106` (`destination_assessed = calc.pre_event_assessed(destination)`), used at `routes_grants.py:115-121` and stored at `:136`, with `calc.decompose(destination)` only running afterwards at `:152`.

## Per-edit pre-edit search log
**Edit 1 — §3.6 child benefit basis**
- (a) Subject: which parcel assessed figure feeds step one of the §3.4 benefit formula, and whether any later event re-derives `benefit_amount_cents`.
- (b) Paths enumerated and read: every caller of `calc.benefit_amount` (`routes_grants.py:115` port, `routes_applications.py:406` determination — both pass `calc.pre_event_assessed(...)`, so the determination path still matches §3.4's existing "as it stands after the cap-and-freeze step" wording and needed no change); `calc.pre_event_assessed` / `calc.assessed_basis` / `calc.decompose` (`calc.py:49-99`) to confirm the pre-event figure includes the destination's *already existing* active freezes — verified against `test_06:579-617`, where a second port to the same destination is capped at the 1,000,000 freeze the first port left, so the wording had to say "pre-transfer basis / third allocation ceiling" rather than anything tied to the parcel's original market or capped value; a repo-wide grep for `benefit_amount` and `frozen_value_cents` outside `calc.py` confirming `benefit_amount_cents` is written only at the two insert sites and never recomputed by `decompose`, the annual roll (`routes_grants.py:390-450`), compliance actions, or the appeal-grant compensation (`routes_appeals.py::_compensate`) — which is what licenses the "written once … no later decomposition rewrites it" clause; `db.py` insert/touch to confirm no other writer.
- (c) Wording adjustment: dropped an earlier draft phrasing that referenced the destination's "stored `assessed_value_cents` before the transfer" in favour of "the very quantity that supplied the third allocation ceiling above" — `pre_event_assessed` recomputes rather than reads the stored field, and this phrasing also stays true when a prior port already lowered the destination's basis. Added "possibly lower" (not "lower") because a destination whose received allocation is not the binding term leaves the basis unchanged.

## Items deliberately not patched (PRD already determinative)
- `test_03` 201 on a verification check — §4 preamble already lists a verification check among the `201 Created` creations; impl returns `env.created`.
- 4 `TypeError` fixes (`test_04`, `test_05`, `test_08`) — pure test-fixture bugs, no behavioral content.
- `test_04` asset-ceiling clock advance — §3.3 already pins the INCOME_DOR certification selector verbatim ("greatest `created_at`", tie to "greatest `version`"), and `services.income_dor_certification:120-134` implements exactly that; the tie only broke because §2.5's logical clock had not moved.
- `test_05 _revoked_grant` — §2.10 rung 11 already names `POST /exemption-grants/{id}/compliance-actions` unconditionally (both `REINSTATE` and `REVOKE`), matching `routes_grants.py:179-180`, which sits after the rung-9 state checks.
- `test_08` `adjudication_risk_score == 0` — §3.8 already says it starts at 0; `routes_fraud.py:56` initialises it to 0.
- `test_09 _denied_claim_whose_slot_was_taken` — §3.3's "corrected by a fresh check" rule plus the §3.4/§2.10 gate order (ownership → residency → eligibility → duplicate grant) already pin `ERR_DUPLICATE_GRANT` as the first failure; `routes_applications.py:356-379` matches. I also confirmed the reopen cascade (`routes_appeals.py::_compensate`) clears both `determined_by_user_id` and `denial_reason`, as §3.4 already states.

**Orchestrator verification:** `wc -l -c` gives PRD.md 448/99,949 and PRD_FINALIZED.md 448/100,398; `diff` shows exactly one changed line (the §3.6 child-grant paragraph at line 273), so the patch is genuinely minimal and PRD_FINALIZED.md is **not** byte-identical to PRD.md. Tail confirmed to still end on the complete final `ERR_PAYMENT_EXCEEDS_BALANCE` row of the §5 catalogue — no truncation from the in-place edit.

## Step 9: Complete PRD — 2026-09-05T13:02:16.818Z

Step 9 was deliberately run as **three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`** (a single-shot full-impl scan reliably under-scans a 13-module / 121k-char artifact and can return a byte-identical file). Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to copy, and each pass verified the previous passes' edit markers before and after its own work. Partition: pass 1 = `app.py`/`errors.py`/`db.py`/`envelope.py`/`validate.py`/`enums.py`/`routes_roll.py`; pass 2 = `calc.py`/`services.py`/`routes_applications.py`; pass 3 = `routes_grants.py`/`routes_fraud.py`/`routes_appeals.py`.

**Cumulative result: 56 edits — 44 ambiguity-pins, 12 mismatch-revisions.** Source `PRD_FINALIZED.md` 448 lines / 100,398 chars → `PRD_COMPLETED.md` 448 lines / 121,617 chars (**+21,219 chars, +21.1%; 0 new lines** — every edit is an in-paragraph insert or revision, no new sections). Char growth by pass: 100,398 → 106,583 (pass 1, +6,185) → 111,977 (pass 2, +5,394) → 121,617 (pass 3, +9,640).

### Pass 1 — infrastructure + roll (17 edits: 14 ambiguity-pins, 3 mismatch-revisions)

- §2.2 Success Format — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from `A`–`Z` and `0`–`9` — `envelope.py:10,13-14`
- §2.2 Error Format — revise — mismatch — envelope covers 4xx **and 5xx**, not 4xx only — `app.py:48-50`
- §2.3 — insert — ambiguity — negative `offset` and non-integer `limit`/`offset` text → `ERR_INVALID_REQUEST` — `validate.py:206-219`
- §2.3 — insert — ambiguity — **ties on `created_at` are broken by insertion order ascending** (the clock stands still, so ties are common); the same sequence underlies every "earlier `created_at`" / "most recently inserted" tie-break in the doc; `id` never orders — `db.py:108-114,125-129`
- §2.3 — insert — ambiguity — empty-string filter treated as absent; non-member enum filter and non-integer integer filter → `ERR_INVALID_REQUEST` — `validate.py:223-246`
- §2.4 — insert — ambiguity — `_`-prefixed internal fields are stripped from every response — `db.py:132-133`
- §2.5 — insert — ambiguity — clock response carries `current_utc` and nothing else; clock may run backwards (no monotonicity); offsets converted to UTC and zone-less instants read as UTC — `routes_roll.py:309-315`, `validate.py:177-189`, `db.py:35-37`
- §2.10 rung 5 — insert — ambiguity — explicit JSON `null` == absent (required → missing, optional → default); required strings must be non-empty; bool/float/numeric-string reject where integer declared; no body or unparseable body reads as `{}`; non-object JSON body rejected; cross-field and uniqueness rules screen at this rung — `validate.py:72-151`
- §2.10 rung 7 — revise — mismatch — applies-to list omitted `POST /_registry-records`; added, with `ERR_TAXPAYER_NOT_FOUND` — `routes_roll.py:328-329`
- §3.1 — insert — ambiguity — system starts with every collection empty and seeds nothing — `app.py:1-6`, `db.py:74`
- §3.1 — insert — ambiguity — `program_code`/`priority_rank` collisions report `ERR_INVALID_REQUEST`; programmes scanned in `created_at` order, code compared before rank per row — `routes_roll.py:40-44`
- §3.1 — insert — ambiguity — the creation-time decomposition does **not** advance `version` (created parcel reads 1); `apn` collision and `base_year > tax_year` → `ERR_INVALID_REQUEST`; `base_year` otherwise only non-negative — `routes_roll.py:85,90-95,112`
- §3.1 — revise — mismatch — registry injection: `source` is the five-member verification-source set incl. `INCOME_DOR`; `address_normalized`/`reported_income_cents` are **both optional regardless of source**; `taxpayer_id` must resolve; response is exactly four fields; stored row unversioned — `routes_roll.py:318-343`, `db.py:83-92`
- §3.1 — insert — ambiguity — unknown ownership-record read → `ERR_PARCEL_NOT_FOUND` (no dedicated not-found error) — `routes_roll.py:275-281`
- §3.1 — insert — ambiguity — **both occupancy geometry checks run against the post-truncation view**; checks run only for a `PRIMARY_RESIDENCE` ingestion; all other records participate as stored whatever their `status`, including `SUPERSEDED` and `UNVERIFIED` — `routes_roll.py:200-237`
- §3.1 — insert — ambiguity — no cascade unless a predecessor was actually truncated; **every** matching `ACTIVE` grant is suspended, not just one — `routes_roll.py:252-270`
- §4 intro — insert — ambiguity — unrouted path → `ERR_INVALID_REQUEST` 404, unsupported method → same id at 405, unexpected condition → same id at 500; trailing slash insignificant — `app.py:24,37-50`

Modules pass 1 found already fully pinned (zero edits): **`errors.py`** (55 catalogue entries, exact one-to-one set match with §5's 55 rows, every HTTP status agreeing) and **`enums.py`** (all 27 enumerations walked member-by-member; every member already declared in PRD prose, no missing or extra member).

### Pass 2 — calculations, services, applications (14 edits: 12 ambiguity-pins, 2 mismatch-revisions)

- §2.6 — insert — ambiguity — the "money is always a JSON number" rule is scoped to `_cents`/`_bps` fields and does not reach free-form `expected_value`/`observed_value` — `routes_applications.py:172-183`
- §2.7 step four — insert — ambiguity — the three posture tests are ordered, so a parcel with a 0 assessed basis reads `UNEXEMPTED`, not `FULLY_EXEMPT` — `calc.py:84-89`
- §2.7 closing ¶ — insert — **mismatch** — a decomposition run rewrites grants' `applied_exempt_value_cents` *without* touching their `updated_at`/`version`; a minted grant reads version 1 with `applied_exempt` already populated, a suspension bumps the grant exactly once — `calc.py:69-82`, `services.py:75-80`
- §2.10 rung 6 — insert — **mismatch** — path-identifier resolution runs *ahead* of rungs 3, 4 and body-shape rung 5; only the query-string half of rung 5 keeps its earlier position — `routes_applications.py:133-138,154-157,313-317,210-214`
- §2.11 — insert — ambiguity — account status re-derived from the whole case set on case-open and case-clear, testing OPEN before SUBSTANTIATED (a `BARRED` household reads `FLAGGED` while a fresh case is open); substantiation writes `BARRED` outright — `services.py:47-55`, `routes_fraud.py:70,142,171`
- §3.2 — insert — ambiguity — body FKs resolve in the order `parcel_id`, `taxpayer_id`, `program_id` — `routes_applications.py:40-45`
- §3.2 — insert — ambiguity — a `CLOSED` programme yields `ERR_INVALID_REQUEST`, tested after the `DRAFT` check and before the barred check — `routes_applications.py:106-108`
- §3.3 — insert — ambiguity — `INCOME_DOR` reads `NO_RECORD` when `reported_income_cents` is null; `expected_value` still carries the certification's income on `NO_RECORD`; an address source with a null address is a `MISMATCH`, not `NO_RECORD`; both fields compared case-sensitively with no re-normalisation — `routes_applications.py:162-183`
- §3.3 — insert — ambiguity — a check may be recorded in any application status; the auto-transition needs *both* first-check and `SUBMITTED`; an already-`CERTIFIED` selected certification is not re-touched — `routes_applications.py:185-204`
- §3.4 — insert — ambiguity — when several `VERIFIED` records qualify, greatest `occupancy_start_date` wins (then `created_at`, then insertion), and that record supplies the snapshots — `services.py:170-175`
- §3.4 — insert — ambiguity — `requires_income_certification` true with a null `income_limit_cents` resolves `TIER_FULL`/10000 with no ceiling test — `routes_applications.py:390-391`
- §3.4 — insert — ambiguity — the determination response body is the updated application, never the minted grant — `routes_applications.py:338,353,447`
- §3.6 — insert — ambiguity — a null `portable_balance_cents` counts as zero and surfaces as `ERR_PORTABLE_BALANCE_EXHAUSTED` — `calc.py:267-269`, `routes_grants.py:107-111`
- §3.9 — insert — ambiguity — `appeal_deadline` is populated on every notice, non-appealable ones included; `appealable` alone bars the appeal — `services.py:21-22`

Pass 2 reported `calc.py`'s arithmetic core already airtight (`round_half_up`, simple-not-compounded cap with single rounding, cap-then-freeze order, the waterfall, the six-step benefit formula with cap before pro-ration and no intermediate rounding, `income_relief_tier` cross-multiplication, `claim_window`, per-year-then-sum refunds, waterfall-before-interest, rounded-back-tax-feeds-penalty, both fraud-score variants and weights, `portable_allocation`'s three-way min); every `services.py` selector already uniquely pinned; and `routes_applications.py`'s seven-gate approval order, senior-age test, duplicate rules, tier bands, asset-after-tier ordering and 3-consequence cascade order already pinned.

### Pass 3 — grants, fraud, appeals (25 edits: 18 ambiguity-pins, 7 mismatch-revisions)

- §2.8 — revise — mismatch — "Four hand-offs" → "Five"; added the compliance-action `REVOKE` bar against `opened_by_user_id` of *any* case on the grant whatever its `investigation_status`; reinstatement never duty-separated — `routes_grants.py:166-169`
- §2.10 rung 4 — revise — mismatch — added `POST /exemption-grants/{id}/compliance-actions` (REVOKE only); `action` is read before rung-5 body screening — `routes_grants.py:166-171`
- §3.5 roll ¶ — revise — mismatch — "three things in order" → "four"; `target_tax_year` bounded 2015–2100; response is exactly five fields, run never persisted; pre-sweep snapshot of `RECERTIFICATION_LAPSE` suspensions; passes walk in §2.3 order — `routes_grants.py:390-450`
- §3.5 roll ¶ — insert — ambiguity — third pass driven from just-lapsed households in first-encounter order, mails nothing; non-`ACTIVE` grants and non-recertifying programmes contribute 0 — `routes_grants.py:426-435`
- §3.5 lapse ¶ — insert — ambiguity — fourth pass reads only the pre-run snapshot (a grant suspended by this run can never lapse in it); late certifiers skipped and left `SUSPENDED`; `recertification_required` not re-examined — `routes_grants.py:396-401,437-442`
- §3.6 — insert — ambiguity — transfer date = logical clock's calendar date, never caller-supplied; multi-record selector = greatest `occupancy_start_date`, `created_at`, insertion — `routes_grants.py:99-104`
- §3.6 — insert — ambiguity — child grant's `suspension_reason` is null — `routes_grants.py:131`
- §3.6 — insert — ambiguity — decomposition order source-then-destination, both after the child insert and source rewrite; partial transfer still bumps the source parcel's `version` — `routes_grants.py:143-152`
- §3.7 filing ¶ — insert — ambiguity — `grant_id` resolution and taxpayer-ownership test precede shape screening of both year fields — `routes_grants.py:217-227`
- §3.7 approval-cascade ¶ — insert — ambiguity — one account write for the whole offset waterfall (version +2 with offset, +1 without); zero-balance cases skipped unwritten; unabsorbed remainder credited nowhere — `routes_grants.py:345-374`
- §3.7 denial ¶ — revise — mismatch — `offset_applied_cents` added to the fields staying 0; `gross_refund_cents` keeps its provisional figure; no ledger moves — `routes_grants.py:315-326`
- §3.8 opening ¶ — insert — ambiguity — the three year fields carry no 2015–2100 window; only start≤end screened at opening; a case may be opened against a grant in any status, terminal included — `routes_fraud.py:33-47`
- §3.8 enforcement ¶ — revise — **mismatch** — suspension/decomposition/notice happen only when the grant is `ACTIVE`; otherwise the case still opens and `status` still re-derives to `FLAGGED` but the grant is untouched and no notice is mailed — `routes_fraud.py:68-83`
- §3.8 adjudication ¶ — insert — ambiguity — threshold evaluated *before* the `improper_end`/`assessment_tax_year` comparison, so a case failing both reports `ERR_RISK_SCORE_BELOW_THRESHOLD`; the year guard raises `ERR_INVALID_REQUEST` after the state check; `CLEAR` held to neither — `routes_fraud.py:146-149`
- §3.8 clearing ¶ — insert — ambiguity — grant reactivated only if still `SUSPENDED` (any reason); otherwise left alone with no re-decomposition, account re-derived either way — `routes_fraud.py:139-143`
- §3.8 substantiation-cascade ¶ — revise — mismatch — grant forced to `REVOKED` from whatever status it holds (terminal included), `suspension_reason` cleared — `routes_fraud.py:161`
- §3.8 substantiation-cascade ¶ — insert — ambiguity — claims reversed in `created_at` order, one account write per reversal; `PENDING`/`DENIED` claims untouched — `routes_fraud.py:163-169`
- §3.8 abatement ¶ — insert — ambiguity — with nothing collected the account is not written at all and its `version` does not advance; abatement admissible from `PARTIALLY_PAID` too — `routes_fraud.py:237-244`
- §3.9 appealability ¶ — insert — ambiguity — timeliness screened before appealability, so an out-of-time non-appealable notice reports `ERR_APPEAL_DEADLINE_PASSED` — `routes_appeals.py:129-132`
- §3.9 docket ¶ — insert — ambiguity — closing is not idempotent (`ERR_DOCKET_CLOSED` on a second close); `docket_date` carries no relation to the session instants — `routes_appeals.py:79-80,106-107`
- §3.9 scheduling ¶ — insert — ambiguity — appeal status tested before docket status — `routes_appeals.py:199-202`
- §3.9 decision ¶ — insert — ambiguity — the duty bar exists only for `DENIAL` and `RECOVERY_ASSESSMENT`; a null bar blocks nobody — `routes_appeals.py:236-246`
- §3.9 continuance ¶ — insert — ambiguity — `decided_by_user_id` is stamped on a continuance; former docket's `version` +1 — `routes_appeals.py:309-317`
- §3.9 compensation ¶ — revise — **mismatch** — branching restated by `subject_type` rather than `notice_type`: `FRAUD_CASE` (abate from any recovery status, grant reactivated only if `REVOKED`, no account write when nothing collected), `EXEMPTION_APPLICATION` (only while still `DENIED`, also clears `denial_reason`), `EXEMPTION_GRANT` (`REVOKED` **or `SUSPENDED`** → `ACTIVE`), `RETROACTIVE_CLAIM` (nothing undone); unresolvable subject = no-op — `routes_appeals.py:249-286`

Pass 3 found none of its three modules already fully pinned (`routes_grants.py` 10 edits, `routes_fraud.py` 7, `routes_appeals.py` 6, plus 2 in the global §2.8/§2.10 sections its behavior contradicted). Verified-and-left-alone as already uniquely pinned: the port screening order and `expected_grant_version` placement, the retroactive-claim window arithmetic and guard order, the substantiation cascade's seven-step order, the recovery `PAY` arithmetic and status advance, the hearing-slot buffer geometry and slot-holding statuses, the derived `scheduled_appeal_count`, all §4 list filters and role tables, and the entire §5 catalogue.

### Anti-overlap discipline between passes

Pass 2 flagged three behaviors originating in its modules but surfacing in sections pass 3 would walk (§2.10 rung 6 global screening order, §3.6's null `portable_balance_cents`, §3.9's notice `appeal_deadline`), plus Step 8's §3.6 child-grant benefit-basis sentence. Pass 3 was explicitly instructed not to re-pin any of the four and confirmed all four still present and untouched.

### Orchestrator final verification

- `wc -l -c`: PRD.md 448 / 99,949 · PRD_FINALIZED.md 448 / 100,398 · **PRD_COMPLETED.md 448 / 121,617**.
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` → **not identical** (the byte-identical Step 9 failure mode did not occur); `diff` reports **51 changed lines**, consistent with 56 in-paragraph edits across the three passes.
- Structural integrity intact: 5 top-level `##` sections (§1–§5), 55 `ERR_` catalogue rows, tail still ends on the complete final row `| ERR_PAYMENT_EXCEEDS_BALANCE | 422 Unprocessable Entity |` — no truncation from 56 in-place edits on a 121k-char file.
- Every `implementation/*.py` and `start.sh` mtime is still 10:26–10:39, unchanged since Step 6/7. Steps 8 and 9 touched documentation only, so the Step 7 evidence — all 8 sweep rounds at 99/99, results files stamped 12:27 — remains valid for the final artifact. No re-sweep needed or performed.
- Housekeeping: removed the Step 7 scratch logs (`workspace/sweep.log`, `workspace/round.1..8.log` — spliced/per-round runner stderr with no residual value) and all `__pycache__` directories. Kept `workspace/sweep.sh` (the reusable 8-round harness) and the 8 `implementation/results.$i.json` passing-round records. Confirmed exactly one `worklog.md` exists, at the task root, with no stray copy under `workspace/` (a known cwd-drift failure mode).

**Pipeline complete.** `workspace/PRD_COMPLETED.md` is written; all nine steps are done.
