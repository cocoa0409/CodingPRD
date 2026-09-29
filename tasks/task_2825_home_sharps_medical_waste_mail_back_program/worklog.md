# Worklog — task_2825_home_sharps_medical_waste_mail_back_program

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2825_home_sharps_medical_waste_mail_back_program` and its `workspace/` subdirectory. Index 2825 was pre-assigned by the invoker; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T04:49:00.000Z

All three scaffold artifacts are complete and the lint is clean.

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_2825_home_sharps_medical_waste_mail_back_program/`

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2953 | 151380 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2120 | 135546 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4228 | 293862 |

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2825_home_sharps_medical_waste_mail_back_program/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2825_home_sharps_medical_waste_mail_back_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2825_home_sharps_medical_waste_mail_back_program/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     44
  Calls scanned (§1.8+§1.9):  1080

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Structural verification (scripted, all green):**
- `SCAFFOLD.yaml` top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: all 9 rule_ids present with exactly 2 instances each = 18 total (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).
- `SCAFFOLD_CORNER_DESIGN.yaml`: all nine guide sections covered — entities 12, state_machines 17, calculations 13, validations 6, endpoints 5, errors 11, rbac 3, cross_cutting_complexity_layers 4, consistency_model 1 (72 instances; 44 with full `test_recipe`, 28 `excluded_because` stubs). Every stub's cited `difficulty_instance` resolves to a real §1.8 instance name; no instance has both `test_recipe` and `excluded_because`; zero duplicate names across the union of both design files.
- Scenario key is byte-identical to the supplied text (verified via `repr()`).
- No sibling task directory was read at any point; the design was derived only from the scenario plus the skill spec.

**Design shape worth relaying:** the domain is 14 entities under `/sharps`, `complexity_profile.complexity_layers = [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint]`, `role_model: segregation_of_duties`, `consistency_model: immediate`, 5 roles, 59 endpoints, 35 validation priority bands, and a logical clock (`POST /_clock/set_current_utc`, startup `2026-08-01T00:00:00Z`) that every date/instant assert is anchored to. Two OCC rules are declared in §1.2.1: `kit-issue-stale-enrollment` and `funding-adjustment-stale-program`.

**One flag for the pipeline owner:** per your instruction the scenario was preserved verbatim, so `scenario` still begins with the line `Generate task harder than expert level!`. That difficulty directive will leak into PRD.md downstream unless it is stripped from `SCAFFOLD.yaml` before the PRD step.

**Orchestrator post-step action (per known leak path):** the line `Generate task harder than expert level!` and its trailing blank line were stripped from `SCAFFOLD.yaml`'s `scenario` block by the orchestrator immediately after Step 2, before Step 4. Verified with `grep -n "harder than expert" SCAFFOLD.yaml` → no matches. The scenario block now begins at `2825. Home Sharps & Medical Waste Mail-Back Program ...`.

## Step 3: Copy shared files — 2026-09-05T04:49:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T05:05:00.000Z

PRD generation and verification complete.

**Output:** `workspace/PRD.md` — 421 lines / 97,560 bytes, written in 11 incremental `cat >>` appends (no one-shot Write, so no 64k truncation). File ends cleanly on the last `## 5.` error-table row, not mid-sentence. Scratch work confined to `/tmp/task_2825_prd/`.

**Structure:** §1 Introduction; §2 with 11 subsections (2.1 RBAC, 2.2 verbatim response structure, 2.3 Pagination, 2.4 Identity/Timestamps/Logical Clock, 2.5 Optimistic Concurrency, 2.6 Nested Path Resolution & Failure Order, 2.7 Cents/Units/Rounding, 2.8 Parallel State Dimensions & Cascades, 2.9 Sponsor Ledger, 2.10 State Law Variance, 2.11 Segregation of Duties); §3 with 9 workflow subsections; §4 endpoint table; §5 error catalogue.

**Hard Contract reports (not written into PRD.md or any sibling file):**

**Field coverage check: PASS**
- `entities[].fields[].name`: 113/113 present verbatim in backticks, 0 missing
- `endpoints[].request_body`: 62/62 present, 0 missing
- `endpoints[].query_params` (incl. `limit`, `offset`): 26/26 present, 0 missing
- `path_params`: 1/1 present
- Second pass restricted to prose sections §1–§3 (tables in §4/§5 excluded): 0 of the 113+62 names appear only in a table; every name is also used in narrative prose.
- All 6 role names, all 33 state values, all field-level enum values, and every `calculations[]` numeric constant appear literally.

**Rule coverage check: PASS**
- All 58 `validations[]` entries: every error id present in §2/§3 prose; token-overlap scan of each entry's condition+description against the prose found 0 entries below 60% coverage.
- Both `concurrency_rules[]`: `expected_enrollment_version` → `ERR_STALE_ENROLLMENT_VERSION` (412) and `expected_program_version` → `ERR_STALE_PROGRAM_VERSION` (412), each stated in §2.5 and re-stated at its workflow site (§3.4, §3.2), with the explicit note that no other endpoint accepts a version field.
- All state-machine transitions: 0 transitions whose trigger vocabulary is absent from the prose; both parallel dimensions (Shipment transport vs. conformance) and cascade propagation covered in §2.8.
- 40 distinct `applies_to` scopes: all target endpoints exist in §4 and all scoped rules are attributed to their specific operation.
- All 8 calculations translated to prose with pinned evaluation order (single terminal ceiling for `required_units`; per-component round-half-up before summing at settlement; rebate tier basis on the pre-rebate capped amount; SCREENING/AUDIT dual variants both specified); `SKIP_REASON_ORDER` precedence and the Feb-29→Feb-28 anniversary clamp included.
- Sibling-branch symmetry preserved (MANUFACTURER vs. HEALTH_PLAN rates and rebate tiers, all 4 remediation actions with surcharges, all 6 non-conformance reason weights and 3 decay bands).

**Path purity check (§3 only): PASS**
- 881 backtick tokens scanned in §3: 0 begin with `/`, 0 are a bare HTTP method, 0 combine method+path. Endpoints in §3 are named by state-transition pair, role + action verb, or capability description. All methods and URLs live only in §4.

**Additional verification**
- §4 table: 59 rows, exact set-equality with `endpoints[]` (0 missing, 0 extra); 0 authorized-role mismatches against the scaffold.
- §5 table: 57 rows, exact set-equality with `errors[]`; 0 HTTP-status mismatches.
- §2.2 diffs byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md` (only a trailing blank separator line added).
- Fuzzy/approximating-language scan: 0 hits. No pseudocode blocks outside the fixed §2.2 JSON envelopes.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no other task directory was read; `worklog.md` untouched.

**Scaffold inconsistencies resolved (deliberate readings, worth flagging to Step 5+):**
1. A scaffold comment attributes the EXHAUSTED-program refusal to "priority 23", but priority 23 is `ERR_INVALID_FACILITY_STATE`; funding exhaustion is `ERR_PROGRAM_FUNDING_EXHAUSTED`. The PRD uses the latter.
2. `ERR_INVALID_PATIENT_STATE`'s description says WITHDRAW requires "a non-terminal status", but the Patient machine defines WITHDRAW only from `{ELIGIBLE, ENROLLED, SUSPENDED}`. The PRD documents the narrower, machine-accurate reading.
3. Priority 8 says acknowledge-receipt "requires ISSUED", but the Kit machine also permits `RETURNED_TO_PATIENT → ACTIVE_FILLING`. The PRD documents both source states as legal.
4. Several state-machine preconditions had no matching `validations[]` entry; each was mapped to the nearest existing error id (e.g. kit issuance requires patient `ENROLLED` → `ERR_INVALID_PATIENT_STATE`; certificate issuance requires kit `RECEIVED` → `ERR_INVALID_KIT_STATE`; facility hazard-class coverage → `ERR_FACILITY_NOT_PERMITTED`).
5. The label-void endpoint accepts `void_reason?` but ReturnLabel has no such field; the PRD says the caller may optionally supply it without asserting persistence.

**Orchestrator anti-truncation verification:** `tail -c 1500 workspace/PRD.md` confirms the file ends at the final row of the §5 error catalogue table (`ERR_FUNDING_BELOW_OBLIGATIONS | 422`), a real section boundary. `grep -in "harder than expert|expert level|scaffold" workspace/PRD.md` → no matches; the difficulty directive did not leak.

## Step 5: Generate unit tests — 2026-09-05T05:56:00.000Z

Test generation is complete. Both stages are finished and verified.

## What was produced

**`test_helpers/`** (task root, 9 files, 2,730 lines) — `constants.py`, `types.py`, `api_errors.py`, `test_users.py`, `api_client.py` (64 endpoint methods), `factories.py`, `assertions.py`, `fixtures.py` (tiered composite fixtures), `__init__.py` barrel.

**`test_suite/`** (task root, `conftest.py` + 24 test files, 10,854 lines) — 246 test functions, 295 collected pytest items after parametrization.

## Work completed this session

Finished queue A with the last two difficulty rules:
- `test_23_facility_day_buckets_and_label_windows.py` (329 lines, 10 tests) — `resource_temporal_overlap` ×2: the aggregate 69+69 > 100 same-`scheduled_intake_date` refusal at a 100-unit facility versus the free next-day bucket, and the label window walk (45-day closed interval 2026-08-01 → 2026-09-15, adjacency conflict at `valid_until`, void quarantine still blocking at 2026-09-15T23:59:59Z, free exactly at 2026-09-16T00:00:00Z with a fresh window to 2026-10-31).
- `test_24_exact_and_partial_compensations.py` (316 lines, 11 tests) — `compensating_invariant` ×2: kit void reversing money through an append-only pair (`RESERVATION` +1465 / `RESERVATION_RELEASE` −1465, snapshots 1465/498535 → 0/500000, amounts summing to zero), and `RETURN_TO_PATIENT` giving back exactly 69 custody units while deliberately leaving 1465 cents reserved and the ledger at one row.

## Coverage audit (scripted, `/tmp/task_2825_tests/check_coverage.py`)

- All 18 difficulty instances have >=2 tests (min 3, max 8).
- All 44 non-stub corner instances have >=1 test.
- All 26 `excluded_because:` stubs are untranslated (0 tests each).
- 0 orphan `Design:` tags, 0 tag problems, 0 unknown instance names.

## Verification

- `check_citations.py`: 0 bad citations across 246 tests — every `PRD X.Y: "…"` quote is a literal substring of `workspace/PRD.md`.
- `check_sections.py`: 3 remaining reports, all benign — they point at the sentence on PRD line 295 under `## 4. Endpoint Definitions`, and the checker only tracks `###` headings.
- `python3 -m py_compile` clean on all 34 files; `pyflakes` clean on the whole suite after removing two genuinely unused imports (`notify_customer_for` in test_04, `kit_issuance_payload` in test_16).
- `pytest --collect-only`: 295 items, no collection errors.
- `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no test dirs leaked inside it; `worklog.md` untouched; no server started or killed.

## Filter decisions worth relaying

Exact instant-string equality is not uniquely derived by the PRD (2.4 pins three fractional digits and `api_client` does no canonicalisation), so instant literals are compared through a file-local `_normalised_instant()` helper rather than by raw string equality. Two design assertions were dropped instead of weakened: `Enrollment.kits_issued == 3` in the suspension cascade (§3.9's hops never say it is recomputed, unlike §3.5's void) and `fill_units == null` on a refused seal (§3.4 mints kits with `fill_units` at 0).

All five corner subagents reported complete; the Step 6 implementation agent was not disturbed.

## Step 6: Generate implementation — 2026-09-05T05:50:00.000Z

The implementation is complete, verified, and the smoke server has been shut down (port 18825 free).

## What was built

`workspace/implementation/`

- **Foundation:** `app.py`, `clock.py` (logical UTC clock from `2026-08-01T00:00:00Z`, 3-digit fractional instants), `constants.py`, `db.py` (in-memory dicts, never seeded, deepcopy snapshot/restore), `errors.py` (57 error ids + HTTP map), `response.py` (envelope + per-kind field whitelists), `validate.py`, `middleware.py` (auth/role/atomic rollback), `start.sh`, `requirements.txt`
- **Services:** `lookup.py`, `calc.py`, `kits.py`, `accounting.py`, `patients.py`
- **Routes (8 blueprints):** `catalogue`, `sponsors`, `patients`, `enrollments`, `kitops`, `shipments`, `certificates`, `autoship`

`start.sh` reads `$PORT`, binds `0.0.0.0`, `exec`s in the foreground, and installs Flask only when missing (avoids boot contention under the 8-round concurrent sweep). Storage is purely in-memory; every restart comes up empty (verified across 8 restarts).

## Verification performed

- **Endpoint coverage: exact.** Parsed all 59 endpoints from the PRD §4 table and diffed against Flask's `url_map` — 0 missing, 0 extra.
- **Compile sweep:** every `.py` compiles; `__pycache__` cleaned.
- **Four end-to-end smoke runs** against a live server on port 18825 covering the full happy path plus cascades, all matching the PRD by hand-computed arithmetic:
  - `required_units` (99, 184, 1775, 493) and `provisional_cost_cents` (1465, 2722, 7447) exact
  - Settlement: HEALTH_PLAN half-cent rate 45x2.5->113 -> final 1582; MANUFACTURER rebate tier keyed on `committed_before + capped` -> 0.03 then 0.06 across two certificates (16160, 15660), `committed_cents` 31820
  - Deterministic ids: `USPSMB-00000001..3` global label sequence, `CERT-PERM9-00001..3` per-facility, fresh number after a void
  - Retention: `max(patient, facility, federal 3)` -> 2033-08-01; leap-day clamp 2028-02-29 + 3y -> **2031-02-28**
  - Pinned ledger orders: issue = `RESERVATION_RELEASE` -> `COMMITMENT`; void = `COMMITMENT_REVERSAL` -> `RESERVATION`; per-program `sequence_no` contiguous
  - Cascades: LOST (label->VOIDED, kit->VOIDED/`SHIPMENT_LOST`, facility units released), NON_CONFORMING -> NCE with state-rule deadline -> notify -> remediate, 5-hop suspension at `screening_risk_score` 75 (enrollment->PAUSED, due date cleared), reinstate, withdraw->TERMINATED
  - Band ordering spot-checks: `ERR_INVALID_KIT_STATE` (prio 8) before `ERR_PACKAGING_SPEC_MISMATCH`/`_RETIRED` (prio 18); seal order enrollment->kit state->`fill_units>=1` (400)->`ERR_CONTAINER_OVERFILLED` (422); `ERR_STATE_MAILBACK_PROHIBITED` outranking packaging/capacity
  - Label 45-day closed-interval conflict and 24-hour void quarantine (both `ERR_LABEL_WINDOW_CONFLICT`), facility per-date aggregate booking with the three open-shipment exclusions
  - Auto-ship: skip order not_due->risk->unfilled->funding; abort on `ERR_KIT_AUTHORIZATION_EXHAUSTED` left **0 run rows and no kits** (rollback works)
  - OCC 412 on both `expected_enrollment_version` and `expected_program_version`; RBAC 401/403; segregation of duties 403; pagination `limit` 1..100 with `total_count`/`has_more`; filter existence checks 404

## Fixes made this session

- `errors.py`: added a `_humanise()` fallback so error ids without a curated message render as readable sentences (e.g. `ERR_PATIENT_NOT_FOUND` -> "Patient not found.") instead of echoing the raw id.
- Earlier: `weekly_sharps_count` bound corrected to 1..500; patient `WITHDRAW` narrowed to ELIGIBLE/ENROLLED/SUSPENDED.

## Deliberate omissions

`program_code` and enrollment-level uniqueness beyond `ERR_DUPLICATE_ACTIVE_ENROLLMENT` are declared unique in the PRD but have no error id in the catalogue, so they are not enforced. Sponsor illegal status-action maps to `ERR_SPONSOR_NOT_ACTIVE` (422) and facility illegal status-action to `ERR_INVALID_FACILITY_STATE` (409), as no dedicated ids exist.

Test directories, `SCAFFOLD_*_DESIGN.yaml`, other `task_*/` dirs, and `worklog.md` were never read or touched; all scratch work lived in `/tmp/task_2825_impl/`.

**Orchestrator note:** Steps 5 and 6 were launched back-to-back as concurrent background agents. Both output locations are correct — `test_helpers/` and `test_suite/` at the task root, `implementation/` under `workspace/`; `ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation/`, so no test directory leaked into `workspace/`.

## Step 7: Run tests and iterate — 2026-09-05T06:36:00.000Z

All 8 rounds pass 295/295. Clean sweep achieved.

## Summary

**Iterations run:** 2

**Tests deleted:** none. Both failure clusters traced to test-artifact bugs whose PRD coverage and unique derivability held, so both were fixed to be *more* faithful to PRD rather than removed.

**Fixes applied to `test_helpers/`:** none — the factory itself was correct; the miscall was in the suite.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_10_lookup_and_payload_failures.py` — `_creation_missing_one_field`, case `kit_without_expected_enrollment_version`. The call was `kit_issuance_payload(1, expected_enrollment_version=OMIT)`, which passes `1` positionally into the same parameter and raises `TypeError: kit_issuance_payload() got multiple values for argument 'expected_enrollment_version'` before any HTTP request is made. Corrected to `kit_issuance_payload(OMIT)`, which is the factory's sanctioned way to drop the key (`_merge` strips the `"__OMIT__"` sentinel). This one-line fix cleared three tests (`test_03[kit_without_expected_enrollment_version]`, `test_04`, `test_05`) that all routed through the same helper.

2. `test_suite/test_18_destruction_and_fiscal_refusals.py` — `test_05_replaying_a_successful_certification_is_refused`. The test asserted `ERR_CERTIFICATE_ALREADY_ISSUED` on the replayed certification, but PRD §3.8 pins the kit-state gate ahead of the duplicate-certificate gate and names this exact scenario for the earlier one: *"The kit must be `RECEIVED`; a kit that has already been certified and is therefore `DESTROYED`, or one that was mailed back and is `RETURNED_TO_PATIENT`, blocks certification with `ERR_INVALID_KIT_STATE`."* Since the first certification moves the kit `RECEIVED → DESTROYED`, a PRD-faithful server must answer `ERR_INVALID_KIT_STATE`. Assertion changed to `ERR_INVALID_KIT_STATE`/409 and the docstring's leading PRD quote swapped to the kit-state sentence it now tests. Still an exact `error_id` assertion — no downgrade to an HTTP-status check.

**Fixes applied to `implementation/`:** none. The `ERR_CERTIFICATE_ALREADY_ISSUED` ordering in `routes/certificates.py::issue_certificate` was already correct per PRD's pinned band order — the duplicate-certificate check remains in place (it is simply unreachable via same-kit replay, since a void returns the kit to `RECEIVED` while flipping the certificate to `VOIDED`), and I did not weaken it to satisfy the test.

**Note on flakiness:** every failure was deterministic (8/8 rounds, identical messages) and no load-induced timeout or connection-refused failure appeared in either sweep, so no re-run was needed to separate signal from host contention.

**Orchestrator independent verification:** the 8 `workspace/implementation/results.$i.json` files are present on disk and each parses to `passed == total == 295`, so the clean sweep is confirmed rather than merely claimed. Step 8 is NOT skipped: although `implementation/` fixes were 0, Step 7 applied 2 `test_suite/` fixes, so the skip condition (0 deletions AND 0 test_suite AND 0 test_helpers AND 0 implementation fixes) is not met.

## Step 8: Finalize PRD — 2026-09-05T06:29:00.000Z

`workspace/PRD_FINALIZED.md` was created and is **byte-identical** to `PRD.md` (421 lines each, 0 lines changed, 0.0% delta). This is the legitimate outcome flagged in the method: Step 7 applied **zero** `implementation/` fixes, deleted **zero** tests, and both test-side fixes traced to test-artifact bugs against behavior the PRD already uniquely determines. No edits were invented.

## Per-item analysis (both traced, both rejected as PRD-silence candidates)

**Item 1 — `test_10_lookup_and_payload_failures.py::_creation_missing_one_field`, `kit_without_expected_enrollment_version`**
- (a) Subject: whether the PRD uniquely determines that kit issuance rejects a body omitting `expected_enrollment_version` with `ERR_INVALID_REQUEST`/400 and writes nothing.
- (b) Paths enumerated/read: `implementation/routes/enrollments.py:59-62` (`KIT_ISSUE_SCHEMA` — `Field("expected_enrollment_version", "int", required=True)`), `enrollments.py:181-199` (`issue_kit`: `validate.parse_body` runs before `lookup.require("enrollment", …)`, so the shape band precedes existence, state and the version echo — exactly PRD 2.6's band order), `implementation/errors.py:30,102,162` (`ERR_INVALID_REQUEST → 400`), plus grep of `expected_enrollment_version` across all of `implementation/` (only the two `enrollments.py` sites), and `test_helpers/factories.py:232-237` (`kit_issuance_payload` — the `"__OMIT__"` sentinel is stripped by `_merge`, so the factory was already correct).
- (c) No wording adjustment: the failure was a Python `TypeError` raised client-side before any HTTP request. PRD §2.5 line 93/95 and §2.6 line 105 together pin the impl behavior verbatim. Pure fixture bug; no PRD edit.

**Item 2 — `test_18_destruction_and_fiscal_refusals.py::test_05_replaying_a_successful_certification_is_refused`**
- (a) Subject: which gate answers a replayed certification on the same kit — the kit-state gate or the duplicate-certificate gate — and whether PRD's placement of `ERR_CERTIFICATE_ALREADY_ISSUED` matches the impl.
- (b) Paths enumerated/read: `implementation/routes/certificates.py:47-48` (kit-state gate, first, before the safety band), `:69-71` (the `ERR_CERTIFICATE_ALREADY_ISSUED` loop, still present), `:109-110` (`kit → DESTROYED` on success, which makes the replay hit the earlier gate), `:132-179` (`void_certificate` — certificate `ISSUED → VOIDED` at `:138` and kit `DESTROYED → RECEIVED` at `:161-163`, confirming a void re-opens the cycle), `implementation/errors.py:51,78,119,142`, and PRD §5 lines 386/409.
- (c) No wording adjustment: PRD §3.8 line 249 already pins the kit-state gate ahead of the constraint band and names this exact scenario for it, while still requiring the `ISSUED`-certificate check with its "a previously voided certificate does not block re-issuance" caveat — precisely what `certificates.py:69-71` implements. The impl follows PRD exactly; the test's expectation was the deviant party. I did **not** weaken PRD's `ERR_CERTIFICATE_ALREADY_ISSUED` sentence to match the test's original assertion, which would have manufactured a new mismatch for Step 9.

No `worklog.md`, `SCAFFOLD*.yaml`, or other task directory was touched.

## Step 9: Complete PRD — 2026-09-05T07:03:00.000Z

**Orchestrator design decision (recorded per AUTONOMY):** Step 9 was run as **three sequential subagent passes over one shared `PRD_COMPLETED.md`**, partitioned by implementation module, rather than as a single subagent. A single agent scanning 3,685 lines of implementation against a 97KB PRD reliably runs out of working context and returns a `PRD_COMPLETED.md` that is byte-identical to its source — i.e. the scan never actually ran. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying so they inherit prior edits. Partition: pass 1 = foundations (`app`, `clock`, `constants`, `db`, `errors`, `response`, `validate`, `middleware`, `routes/common`, `routes/catalogue`, `routes/sponsors`, `services/lookup`); pass 2 = `routes/patients`, `routes/enrollments`, `routes/kitops`, `routes/autoship`, `services/patients`, `services/kits`; pass 3 = `routes/shipments`, `routes/certificates`, `services/calc`, `services/accounting`, plus the cross-cutting §2.8 versioning cleanup pass 2 escalated.

**Totals: 66 edits — 47 ambiguity-pins, 19 mismatch-revisions.** `PRD_FINALIZED.md` 421 lines / 97,560 chars → `PRD_COMPLETED.md` 423 lines / 115,428 chars (+17,868 chars, +18.3%; +2 lines from one added paragraph inside existing §2.6). Headings unchanged (5 top-level sections), §4 endpoint rows unchanged (59), §5 error rows unchanged (57), file still ends at `| ERR_FUNDING_BELOW_OBLIGATIONS | 422 |`.

### Pass 1 — foundations (28 edits: 23 ambiguity-pins, 5 mismatch-revisions)

- §2.1 — revise — ambiguity — an empty (not just absent) `X-User-ID` is also 401 — middleware.py:19
- §2.1 — insert — mismatch — PRD implied blanket sponsor/patient ownership; pinned that ownership is checked on exactly 3 write ops (sponsor-decision, funding-adjustment, patient kit receipt/seal), skipped for ProgramAdmin, and never on any read/list — sponsors.py:164, enrollments.py:126, kitops.py:62
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — response.py:12
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the logical clock, including on errors — response.py:19
- §2.2 — insert — ambiguity — pagination `meta` keys absent entirely on object responses — response.py:16
- §2.2 — insert — ambiguity — serialised resources carry exactly the declared field set; unset fields are JSON `null`, not omitted — response.py:232
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is 400; `+`/`-` sign accepted — validate.py:168
- §2.3 — insert — ambiguity — equal `created_at` ties (routine, since the clock is manual) break by insertion order — db.py:96
- §2.3 — insert — ambiguity — filter validation: bad enum → 400, bool accepts true/false/1/0 case-insensitively, unknown id filter → that entity's 404, filters exact-match/conjunctive, unknown params ignored — validate.py:186/195, lookup.py:53
- §2.3 — insert — ambiguity — pagination validated before filters — sponsors.py:198
- §2.4 — revise — ambiguity — `id` is a v4 UUID, lowercase hyphenated — db.py:62
- §2.4 — revise — ambiguity — `updated_at` equals `created_at` until first mutation — db.py:86
- §2.4 — insert — ambiguity — accepted instant spellings (Z / ±HH:MM / ±HHMM / no zone = UTC, 1–9 fractional digits, `T` or space, trimmed), output truncated to 3 digits; dates only `YYYY-MM-DD` — clock.py:9, 33, 69
- §2.6 — insert — ambiguity — shape band precedes existence even for query strings — sponsors.py:129
- §2.6 — insert (new paragraph in existing section) — ambiguity — JSON `null` == omitted, undeclared keys ignored, empty/absent body == `{}`, non-object body 400, and every rejected mutating request rolls the store back completely — validate.py:121/40, middleware.py:49
- §3.1 — insert — ambiguity — `un_specification_code` non-empty, no ceiling/format check — catalogue.py:59
- §3.1 — insert — ambiguity — `state_code` filter matched literally/case-sensitively (empty page, not 400) — catalogue.py:121
- §3.1 — revise — ambiguity — facility status-action `reason` accepted but never persisted; bad `action` is 400 — catalogue.py:89
- §3.1 — revise — mismatch — out-of-turn facility SUSPEND/REINSTATE itself returns `ERR_INVALID_FACILITY_STATE` — catalogue.py:190
- §3.2 — revise — ambiguity — sponsor `contact_email` non-empty with no format check, no length ceilings, may be created already `SUSPENDED` — sponsors.py:25
- §3.2 — revise — mismatch — out-of-turn sponsor status action returns `ERR_SPONSOR_NOT_ACTIVE`, and the sponsor-active gate fires at **four** points (PRD said "precisely two") — sponsors.py:63, enrollments.py:75/113/133
- §3.2 — revise — mismatch — `program_code` is **not** uniqueness-checked (PRD claimed unique; no such error exists) — sponsors.py:100
- §3.2 — insert — ambiguity — program creation: path sponsor 404 then not-active 422 — sponsors.py:102
- §3.2 — revise — ambiguity — global program list's `sponsor_id` is the one id filter matched literally, not existence-checked — sponsors.py:149
- §3.2 — insert — ambiguity — `delta_cents` unbounded incl. 0, `memo` null when omitted, sponsor status irrelevant, ownership evaluated before the version echo — sponsors.py:162
- §3.2 — revise — mismatch — funding entry's after-balances snapshot the already-adjusted ceiling, and `version` rises by exactly 1 even when the status flips (§2.9 implied a second increment) — sponsors.py:174/181
- §3.2 — insert — ambiguity — ledger list id filters are existence-checked; cross-program `sequence_no` ties break by creation then insertion order — sponsors.py:202/211
- §5 — insert — ambiguity — out-of-catalogue framework errors `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 in the same envelope; trailing slash insignificant — app.py:26/42

Also verified by script that the §5 table and `errors.HTTP_STATUS` agree exactly (57 codes, no missing/extra, no status mismatch), so no table row needed changing.

### Pass 2 — patients / enrollments / kits / auto-ship (25 edits: 16 ambiguity-pins, 9 mismatch-revisions)

- §3.3 — insert — ambiguity — `full_name`/`contact_email` are required non-empty strings, no upper bound, no format check — routes/patients.py:20,24
- §3.3 — insert — ambiguity — retrieving a patient returns both scores as most recently stored; no read endpoint recomputes — routes/patients.py:97
- §3.3 — insert — ambiguity — eligibility-review `note` shape-checked then discarded, never persisted — routes/patients.py:29,69
- §3.3 — insert — ambiguity — `patient_id` resolved before `sponsorship_program_id`; program's own ACTIVE/EXHAUSTED status not consulted at creation; patient-state and sponsor gates precede the duplicate check — routes/enrollments.py:69-81
- §3.3 — insert — ambiguity — an already-`ENROLLED` patient is untouched by approval (no `updated_at`/`version` move) — routes/enrollments.py:141
- §3.4 — insert — ambiguity — `volume_liters` emitted as a JSON number at one decimal place — services/kits.py:104
- §3.4 — revise — mismatch — step 4: the program's `version` advances only on an actual ACTIVE/EXHAUSTED flip (contradicted §2.8's blanket "every mutated record bumps version"); step 5: `kits_issued` defined as the non-`VOIDED` kit count — services/accounting.py:122-125, services/kits.py:57-58
- §2.6 — revise — mismatch — the state-precondition sub-order now names its one documented exception (kit receipt acknowledgement) — kitops.py:75-79
- §3.5 — revise — mismatch — acknowledge-receipt checks kit state *before* enrollment state, inverting §2.6's sub-order — kitops.py:75-79
- §3.5 — insert — ambiguity — `sealed_gross_weight_grams` has no range bound; stored as declared — kitops.py:43
- §3.5 — insert — ambiguity — admin-void `void_reason` is required free text stored verbatim; no enrollment-state precondition applies — kitops.py:46,113
- §3.5 — revise — mismatch — admin void refreshes the enrollment's `updated_at` without a `version` bump; program version only on flip — kitops.py:117-120
- §3.6 — insert — ambiguity — label-void `void_reason` is discarded; labels carry no such field — kitops.py:50,164
- §3.6 — revise — mismatch — activation resolves `treatment_facility_id` (404) *before* the label-`PRINTED` check; PRD had listed label state first — kitops.py:178-181
- §3.6 — revise — mismatch — activation's `pending_intake_units` bump refreshes the facility's `updated_at` only (no version); `absorbent_declared` persisted nowhere — kitops.py:239-240
- §3.9 — insert — ambiguity — one status-action capability with `SUSPEND`/`REINSTATE`/`WITHDRAW`, other values 400; `reason` discarded — routes/patients.py:32-35
- §3.9 — insert — ambiguity — hop 3 recomputes the enrollment's `kits_issued`; cascade walks enrollments then kits in creation order, fixing ledger `sequence_no` order — services/patients.py:18-31
- §3.9 — revise — mismatch — hop 5 recomputes derived counters, runs once per distinct program after all enrollment hops, and the program is the exception to "every record's version increments" — services/patients.py:37-38
- §3.9 — insert — ambiguity — withdrawal leaves `suspended_at` as-is and recomputes `kits_issued` — services/patients.py:57,73
- §3.9 — revise — mismatch — withdrawal carries the same program version/once-per-program exception — services/patients.py:78-79
- §3.9 — insert — ambiguity — the run's risk refresh refreshes each patient's `updated_at` but never bumps `version` — routes/autoship.py:34-36
- §3.9 — revise — ambiguity — a null `next_autoship_due_date` counts as not-due — routes/autoship.py:69
- §3.9 — insert — ambiguity — inside a run `supersedes_kit_id` is provenance only: no void, no `RESERVATION_RELEASE` — routes/autoship.py:79-107
- §3.9 — revise — mismatch — abort precedence pinned: the two sizing aborts, then the authorization cap, then the allowance gate (PRD had listed authorization first) — routes/autoship.py:86-93
- §3.9 — insert — ambiguity — `as_of_date` filter must be `YYYY-MM-DD` (else 400); unmatched date yields an empty page — routes/autoship.py:125-128

Pass 2 escalated one cross-cutting conflict rather than editing it: §2.8's blanket "every record actually mutated has its own `version` incremented by 1" is false for several derived-value touches. Pass 2 pinned each exception inline at its workflow site and handed the §2.8 sentence itself to pass 3.

### Pass 3 — shipments / certificates / calc / accounting + §2.8 cleanup (13 edits: 8 ambiguity-pins, 5 mismatch-revisions)

- §2.3 — revise — mismatch — the "single exception" to id-filter existence-checking was wrong: the global non-conformance-event list's `shipment_id` is also matched literally and yields an empty page; listed both exceptions and named the shipment/certificate list filters that *are* checked — routes/shipments.py:295 vs routes/certificates.py:197-199, routes/shipments.py:253-255
- §2.4 — revise — mismatch — "`version` … increments by exactly 1 on every mutation" now defers to §2.8's derived-value exception — db.py:66-77
- §2.8 — revise — mismatch — the assigned versioning cleanup (verdict below) — services/accounting.py:94-126
- §2.9 — revise — ambiguity — `memo` was "and the like"; pinned the closed set of eight server-written phrases, that settlement and void each stamp *both* their entries, and that only the funding adjustment copies a client memo — services/accounting.py:18-25, routes/certificates.py:112-159
- §2.9 — revise — mismatch — status was "`EXHAUSTED` at exactly zero" but impl is `ACTIVE if available > 0 else EXHAUSTED` (negatives read `EXHAUSTED`); also pinned that the flip is evaluated **once per request per program after all appends**, so a certificate void whose appends cancel leaves `status` and `version` untouched instead of flipping twice — services/accounting.py:103,122-125,129-139
- §3.6 — insert — ambiguity — a carrier scan answers 200 with the updated shipment however far the cascade reaches — routes/shipments.py:109
- §3.6 — revise — mismatch — the loss cascade's "Every record touched … has its own `version` incremented by 1" was false; only shipment/kit/label bump, while enrollment, facility and program are derived-value touches. Also pinned the previously unmentioned recompute of the enrollment's `kits_issued` on a loss — routes/shipments.py:100-108, services/kits.py:57-58
- §3.7 — insert — ambiguity — the missing-`reason_code` rejection is a shape-band 400 ahead of the shipment's existence/state gates, and `observed_gross_weight_grams` carries no range bound (0 and negatives accepted), unlike `declared_gross_weight_grams` — routes/shipments.py:42,115-123
- §3.7 — insert — ambiguity — screening returns 200 with the shipment, not 201 with the minted event; the shipment-scoped event list also accepts `status`; the global `shipment_id` filter is literal — routes/shipments.py:166,276-281,295
- §3.7 — insert — ambiguity — remediation returns 200 with the updated event rather than the shipment — routes/shipments.py:231
- §3.8 — insert — ambiguity — a new certificate starts in `ISSUED` with `voided_at` and `void_reason` both null — routes/certificates.py:103-105
- §3.8 — insert — ambiguity — certificate-void `void_reason` is required and non-empty (400 otherwise) — routes/certificates.py:36
- §3.9 — insert — ambiguity — a negative elapsed time (clock rewound) reads as age 0, so the event contributes full weight — services/calc.py:155-161

**§2.8 verdict (pass 3):** option (a) — softened, and it was necessary. `services/accounting.py:123-125` makes the program a permanent counter-example (`db.touch` plus a bump only on a genuine status flip), and pass 3's own slice adds three more sites pass 2 did not cover inline: the facility counters on certificate issue (`certificates.py:126`) and void (`:175`), and the facility plus enrollment on a loss scan (`shipments.py:66,105`). All 16 `db.touch` and 29 `db.bump` sites were audited; the split is systematic — `touch`-only happens exactly when the sole change is a facility custody/destruction counter, an enrollment's recomputed `kits_issued`, a patient's refreshed risk scores, or a program's recomputed balances. §2.8 now states that rule with those four cases enumerated, plus the funding adjustment as the one unconditional program bump. The matching blanket claim in §2.4 was cross-referenced. Passes 1/2's inline exceptions in §3.4, §3.5, §3.9 remain true and now agree with §2.8.

### Orchestrator verification of Step 9

- `wc -l -c`: `PRD_COMPLETED.md` = 423 lines / 115,428 chars; `cmp` against `PRD_FINALIZED.md` reports **DIFFERS** (so the scan genuinely ran — not the byte-identical failure mode).
- `tail` confirms the document still ends at the final §5 error-catalogue row; 5 top-level `##` sections intact.
- `find workspace/implementation test_suite test_helpers -name '*.py' -newermt '2026-09-05 06:40'` → no matches, confirming all three Step 9 passes were documentation-only and did not disturb the green artifact.
- All 8 `workspace/implementation/results.$i.json` files still present and each still parses to `passed == total == 295`.
- `ls workspace/` → `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/`, `sweep.log` — no test directory leaked into `workspace/`.

**Pipeline complete through Step 9.**
