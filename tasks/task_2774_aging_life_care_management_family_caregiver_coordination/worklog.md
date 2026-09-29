# Worklog — task_2774_aging_life_care_management_family_caregiver_coordination

## Step 1: Create task directory — 2026-09-04T19:29:48.575Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2774_aging_life_care_management_family_caregiver_coordination` and its `workspace/` subdirectory. Index 2774 was pre-assigned by the invocation (no scan/auto-allocation performed, per orchestration instructions, because up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T20:59:00.000Z

Done. All three scaffold artifacts are complete and pass the skill's linter.

### Files

| Path | Lines |
|---|---|
`SCAFFOLD.yaml` | 1900
`SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1825
`SCAFFOLD_CORNER_DESIGN.yaml` | 4245

### SCAFFOLD.yaml counts (§1.0–§1.7)
- 12 entities, 10 state machines, 2 concurrency rules (§1.2.1), 10 calculations, 41 ordered validations, 52 endpoints, 40 errors, 5 roles
- `domain_name: aging-life-care-coordination`, `api_prefix: /care`; complexity profile: `compliance_audit` / `ledger_reconciliation`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation]`, `entity_topology: flat`, `state_machine_shape: branching`, `role_model: segregation_of_duties`, `consistency_model: immediate`
- Neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears in this file.

### Design indices
- §1.8 `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: 9 difficulty rules, **19 instances** (all with executable `test_recipe`)
- §1.9 `SCAFFOLD_CORNER_DESIGN.yaml`: all 9 guide sections, **78 instances** = 58 full test recipes + 20 `excluded_because:` stubs
  - entities 12, state_machines 14 (4 stubs), calculations 13 (5), validations 14 (5), endpoints 6 (2), errors 7, rbac 5, cross_cutting 6 (4), consistency_model 1

### Verification
```
Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     58
  Calls scanned (§1.8+§1.9):  971

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Additional self-checks run beyond the linter: every `${var}` in every payload/path/assert is bound by an earlier `captures:`; instance names unique across both design files; every stub's `difficulty_instance` resolves to a real §1.8 instance *and* the right rule id; all 40 catalog error_ids are triggered by at least one instance.

### Notes / disclosures
- **Scenario text**: the domain paragraph is verbatim in `scenario:`, but the leading directive line "Generate task harder than expert level!" was deliberately omitted, because the scaffold's `scenario:` value propagates into PRD.md downstream and that line leaks meta-instructions into the artifact. The difficulty intent is instead carried by the §1.8 rule set and the corner breadth.
- **Coherence fixes made to SCAFFOLD.yaml while authoring the corners** (each unlocked a corner that was otherwise unreachable/contradictory): `ERR_DAILY_CAP_EXCEEDED.when` reworded to match validation 72's cross-client aggregate; `PATCH /care/assessments/{assessmentId}` now permits a narrative-only correction on an ACCEPTED assessment (version bump only) so `ERR_PINNED_ASSESSMENT_STALE` is reachable, with validation 40 keeping `domain_scores` edits DRAFT-only; validation priority 30 extended to state that a `PracticeSupervisor` X-User-ID must resolve to a `CareManager` with `is_supervisor == true` and that a `FamilyDecisionMaker`'s GETs are scoped to its own client (plus the matching `applies_to` endpoints).
- Hard constraint respected: no sibling `task_*/` directory was listed, read, or grepped; everything derives from the scenario text plus the skill spec.

**Orchestrator verification**: `grep -i "harder than expert|expert level"` over all three scaffold files returns nothing — the difficulty directive did not leak (guards against the known scaffold-generator leak path into `scenario:` → PRD.md).

## Step 3: Copy shared files — 2026-09-04T21:00:36.296Z

`cp ./INSTRUCTION.md tasks/task_2774_.../workspace/INSTRUCTION.md` — 1424 bytes in place.

## Step 4: Generate PRD — 2026-09-04T21:13:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — 412 lines / 93,550 bytes. Written incrementally in 8 chunked appends (no one-shot Write, no truncation).

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim canonical block); 2.3 Listing, Filtering and Pagination; 2.4 Record Identity, Timestamps and the Logical Clock; 2.5 Resource Addressing and Reference Resolution; 2.6 The Request Validation Ladder; 2.7 Version Pinning on Cross-Aggregate Writes; 2.8 Money, Minutes and Rounding Discipline; 2.9 Derived Fields, Cascades and Reconciliation; 2.10 Segregation of Duties and Surrogate Authority
- §3 Business Logic & Workflows — 3.1 Client Intake, Capacity Determination and Risk Posture; 3.2 Registering the People Around the Client; 3.3 The Comprehensive Geriatric Assessment and Its Supervisory Review; 3.4 Authoring the Care Plan and Winning Family Approval; 3.5 Facilitating Family Conferences and Documenting Decisions; 3.6 Vendor Engagement: Two Independent Dimensions on One Authorization; 3.7 Crisis Response and Hospital-to-Home Transition Oversight; 3.8 Capturing and Rating Billable Time; 3.9 The Retainer Ledger, Invoicing and Payment
- §4 Endpoint Definitions (52 rows, 4 columns)
- §5 Error Code Catalogue (40 rows, 2 columns)

**Tail confirmation:** the document ends at the final `| ERR_RETAINER_INSUFFICIENT | 402 |` row of the §5 table — a complete section boundary, fully rendered table.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 118 required, 118 present, 0 missing
- endpoints[].request_body: 74 required, 74 present, 0 missing
- endpoints[].query_params: 27 required, 27 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
- errors[].error_id: 40 required, 40 present, 0 missing
- state enumeration values: 42 required, 42 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 33 checked, 33 expressed in prose (ordered ladder in §2.6 plus per-workflow relative ordering), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_client_version / expected_care_plan_version + ERR_STALE_CLIENT_VERSION / ERR_STALE_CARE_PLAN_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 48 checked across 11 machines/dimensions, 48 fully expressed (from/to, every precondition paired with its error, every side effect incl. multi-hop cascades), 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise prose (no operator syntax, no fuzzy words), 0 missing
- validations[] conditions: 33 checked, 33 matchable to error_id in narrative, 0 missing
- endpoints[].side_effects / applies_to: 52 endpoints checked, all side-effect sets and applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: 118 checked, defaults / initial values / enum sets / constraints reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (assessment ACCEPTED vs REVISION_REQUESTED; care-plan ACTIVE vs REJECTED; escalation ACCEPTED vs DECLINED; invoice DRAFT-void vs ISSUED-void; PROVISIONAL vs FINAL; SCREENING vs COMPREHENSIVE), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1096
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 matches the canonical `section-2.2-response-structure.md` byte-for-byte; no meta-instruction or difficulty language present (swept for "harder than", "expert level", "difficulty", plus forbidden fuzzy words); the two withheld design files were never opened, grepped, or referenced.

One judgement call flagged by the doc generator: scaffold validation priority 64 (`ERR_COVERAGE_CAPACITY_EXCEEDED`) applies to target states `AUTHORIZED` **and** `ACTIVE`, but its formula sums over rows already in `{AUTHORIZED, ACTIVE}` *and* adds the candidate's own `concurrent_caregivers` — which would double-count the candidate on an `AUTHORIZED → ACTIVE` transition. The PRD resolves this determinately by summing over the client's *other* intersecting authorizations plus the candidate's own; identical to the literal scaffold reading for `PROPOSED → AUTHORIZED` and `SUSPENDED → ACTIVE`, and the only non-degenerate reading for `AUTHORIZED → ACTIVE`.

**Orchestrator verification (guards the known silent-truncation failure):** `wc -l` = 412; `tail -25` shows the §5 table closing on a complete `| error | code |` row; section scan shows all five top-level sections present in order; `grep -i "harder than|expert level"` returns nothing. PRD accepted without regeneration.

## Step 6: Generate implementation — 2026-09-04T21:57:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator started before `test_suite/` existed on disk — physical isolation from the tests. Step 6 returned first; its entry is recorded here in completion order.)

Implementation is complete, verified, and the smoke server has been shut down (pid 3881612 killed by PID only; port 39774 confirmed free).

### Files (`workspace/implementation/`, 3331 lines total)

| File | Lines | Role |
|---|---|---|
| `derive.py` | 458 | all derived fields, money math, ordered cascades |
| `routes/conferences.py` | 300 | conferences + conference decisions |
| `routes/authorizations.py` | 281 | service authorizations + COI events |
| `serialize.py` | 246 | per-entity serializers (derive-on-read) |
| `routes/time_entries.py` | 236 | time entries + rating guards |
| `validators.py` | 229 | 13-step ladder primitives, paging, filters |
| `routes/care_plans.py` | 204 | care plans + OCC |
| `routes/assessments.py` | 193 | assessments |
| `routes/invoices.py` | 187 | invoices + payments |
| `routes/people.py` | 186 | care managers, vendors, family contacts |
| `routes/clients.py` | 142 | clients, state, capacity, retainer deposits |
| `routes/crisis.py` | 132 | crisis episodes |
| `auth.py` | 112 | roles, `X-User-*`, family scoping, supervisor resolution |
| `lookup.py` | 89 | twelve `need_*` 404 helpers |
| `store.py` | 71 | in-memory dict store, id/version/`_seq` stamping |
| `app.py` | 64 | blueprint registration + error handlers + `app.run` |
| `errors.py` | 63 | 40 error IDs -> HTTP status + default messages |
| `envelope.py` | 57 | meta/response_type/data, `req_` ids, pagination |
| `clock.py` | 52 | logical clock, 3-digit ISO renderer |
| `routes/clock_admin.py` | 18 | `POST /_clock/set_current_utc` |
| `start.sh` | 10 | guarded pip install then `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=3.0,<4` |

`routes/__init__.py` is empty. All files parse under `ast.parse`; no `__pycache__` left behind.

### Endpoint parity
**52 implemented vs 52 declared** — programmatic diff over `app.url_map` gave `missing: []`, `extra: []`. Store is empty at import (`seeded rows: 0`) and the clock boots at exactly `2026-08-01T00:00:00.000Z`.

### Notable design decisions
- **Ladder vs. prose conflicts resolved in favour of PRD prose.** On `PROPOSED→AUTHORIZED` the scaffold puts COI before vendor standing, but §3.6 pins "in this order" with vendor first — PRD won. Conversely `SUSPENDED→ACTIVE` uses vendor → client → capacity (prose and scaffold agree), while `AUTHORIZED→ACTIVE` and invoice `ISSUED` keep the §2.6 numeric order (client status first).
- **Supervisor resolution** (`X-User-ID` → supervising care manager) is applied only on the scaffold's validation-30 `applies_to` endpoints — never on GETs, capacity determination, or crisis-episode state. It runs *after* existence, so a bogus supervisor on a missing assessment yields `ERR_ASSESSMENT_NOT_FOUND`.
- **Target-state ownership is read from the raw body before payload validation**, so an unowned outcome (e.g. PracticeSupervisor requesting care-plan `ACTIVE`) is a 403 rather than a 400.
- **Client version advances exactly once per API operation** regardless of cascade depth; each cascaded child record gets its own `touch()`.
- **Cascade reactivation respects the forward-transition guards**: `restore_client_from_nonpayment` skips NONPAYMENT-suspended authorizations whose vendor is BARRED or whose coverage capacity no longer holds (fixed during this session).
- **Money**: `Decimal` + ROUND_HALF_UP, rounded once on the composed product; invoice subtotal is per-line rounding then sum, admin fee rounded once on the summed subtotal. Coverage windows use closed intervals, time entries half-open.
- Errors chosen where the PRD is silent: `DOCUMENTED` with no surviving decision → 409; `TRANSITION_OVERSIGHT` without standing coverage → 409; plan activation during CRISIS → 409; ratification against a non-convened conference → 409 (while `quorum_met` false → `ERR_QUORUM_NOT_MET`).

### Smoke test (PORT=39774, killed by PID)
Two end-to-end scripts, all assertions green:
- **Happy path (30 steps):** comprehensive_acuity 83, coverage_hours 48, base_cost_cents 144000, billable 18000 (52 min at 18000/hr on a 15-min increment), admin_fee_cents 1260.
- **Second pass (44 steps):** OCC 412 `ERR_STALE_CLIENT_VERSION`; SoD 403 on self-acceptance; tiered coordination fee (480000 → 6% → 28800 → 508800); conserved coverage hours across a suspend/reactivate lap (96 → 0 → 96); `coverage_gap_flag` flipping true→false on authorization and driving `risk_posture` ELEVATED→ROUTINE; crisis rating 1.5 × 1.2 = 21600; `ERR_TRAVEL_BUFFER_VIOLATION`, `ERR_TIME_ENTRY_OVERLAP`, discharge blocked during CRISIS; quorum with the DIMINISHED_DOCUMENTED guardian requirement; decision RATIFIED → `ERR_ESCALATION_PRECONDITION_UNMET` before DOCUMENTED → ESCALATED → ESCALATION_ACCEPTED with the guardianship cascade rewriting `capacity_status` to ADJUDICATED_INCAPACITATED.
- **Negative envelopes:** 401 unauthenticated / unknown role, 400 `limit=0`, 400 domain score out of range, 403 role admission, 403 target-state ownership, 404 unknown route (`ERR_NOT_FOUND`), 404 `ERR_CLIENT_NOT_FOUND`, 422 `ERR_COI_NOT_ACKNOWLEDGED`, 422 `ERR_PAYMENT_EXCEEDS_BALANCE`, 402 `ERR_RETAINER_INSUFFICIENT`.

## Step 5: Generate unit tests — 2026-09-04T23:10:00.000Z

The suite is complete. Final deliverable:

### Output locations (both directly at the task root, nothing under `workspace/`)

**test_helpers/ — 3045 lines**
| file | lines |
|---|---|
| `__init__.py` | 50 |
| `api_client.py` | 288 |
| `api_errors.py` | 111 |
| `assertions.py` | 510 |
| `constants.py` | 87 |
| `factories.py` | 334 |
| `fixtures.py` | 1160 |
| `test_users.py` | 75 |
| `types.py` | 430 |

**test_suite/ — 7403 lines**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 50 | — |
| `test_01_assessment_acuity_and_review_cycle.py` | 385 | 10 |
| `test_02_time_entry_rating_and_calendar.py` | 352 | 9 |
| `test_03_invoice_variants_and_administrative_fee.py` | 338 | 8 |
| `test_04_authorization_costing_and_disclosure_dimensions.py` | 244 | 8 |
| `test_05_authorization_gates_and_coverage_capacity.py` | 384 | 8 |
| `test_06_invoice_void_release_chain_and_retainer_conservation.py` | 273 | 7 |
| `test_07_decision_rescission_and_coverage_conservation.py` | 281 | 8 |
| `test_08_entity_contracts_and_field_derivation.py` | 478 | 12 |
| `test_09_state_machine_guards_and_cascades.py` | 665 | 10 |
| `test_10_derived_calculations_and_boundaries.py` | 705 | 14 |
| `test_11_validation_priority_order.py` | 889 | 17 |
| `test_12_endpoint_behaviours.py` | 472 | 9 |
| `test_13_error_contract.py` | 765 | 14 |
| `test_14_role_authorisation.py` | 558 | 10 |
| `test_15_cross_cutting_and_consistency.py` | 564 | 10 |

### Coverage

- **154 tests, 77 distinct `Design:` tags** — every test carries exactly one tag as the last docstring line, plus exactly one `PRD: "…"` citation verified as a whitespace-flattened verbatim substring of `workspace/PRD.md`.
- **Queue A (Difficulty): 19/19 instances, 58 tests** — files test_01–test_07.
- **Queue B (Corner): 58/58 non-stub instances, 96 tests** — entities 12, state_machines 10, calculations 8, validations 9, endpoints 4, errors 7, rbac 5, cross_cutting 2, consistency_model 1 (files test_08–test_15).
- **SKIPPED instances: none.** No `skip`/`skipif`/`xfail` anywhere. The 20 `excluded_because:` corner stubs are out of scope by contract, not skips.

### Verification run

- `check` script: `tests: 154 distinct tags: 77`, no bad/dual/unknown tags, no non-verbatim citations.
- Import reconciler across all 16 test_suite files: zero unused, zero missing, zero non-helper names; every `from test_helpers import …` name resolves against the real package (`import test_helpers` succeeds), and every `api_client.<attr>` used exists on the client.
- `compileall` clean on both directories; `__pycache__` removed afterwards.
- No mention of "scaffold", scaffold section names, or scaffold priority numbers in generated code.
- `worklog.md` untouched; no server started; no `pkill` issued.

### Recipe-vs-PRD adjudications in the final file (test_15)

`every_cascaded_change_is_visible_in_the_same_response` asserts the invoice-issue cascade suspends the engagement (`SUSPENDED`/`NONPAYMENT`, coverage hours 0), but its setup left the authorization at `AUTHORIZED`, and PRD line 302 suspends only authorizations whose `auth_status` is `ACTIVE` (line 254 keeps `AUTHORIZED` hours in the sum). Added the `AUTHORIZED → ACTIVE` activation — which PRD says moves no coverage total — so the recipe's asserted outcome is the one PRD uniquely derives. All earlier adjudications (illegal `contact_role`/`residence_setting`/`billing_increment_min` literals, the double-rule COI acknowledgement actor) are unchanged.

**Orchestrator verification**: `test_helpers/` and `test_suite/` both sit directly at the task root; `find workspace -maxdepth 2 -name "test_*" -type d` is empty (guards the known Step-5 drift that writes test dirs under `workspace/`). 16 test files, 154 `Design:` tags counted independently.

## Step 7: Run tests and iterate — 2026-09-04T23:40:00.000Z

Clean 8-round parallel sweep achieved: **154/154 passing in all 8 rounds**.

### Summary

**Iterations run:** 3 (each an 8-round parallel `setsid nohup` sweep, all rounds to completion). Progression: 146/154 → 151/154 → 154/154. Every failure was deterministic across all 8 rounds in every iteration — no flakiness or load-induced noise appeared.

**Tests deleted:** none. All 8 failing tests asserted rules verbatim in PRD.md and uniquely derivable from it; every failure was a test-artifact bug (STEP 2), not PRD silence.

**Fixes applied to `test_helpers/`:** none. All defects lived in the test functions' own inline setup, not the shared fixture layer.

**Fixes applied to `test_suite/`:**

- `test_suite/test_11_validation_priority_order.py`, `_referred_vendor_awaiting_disclosure()` — added `"referral_fee_pct": 10` to `vendor_overrides`. The fixture declared `has_referral_relationship: True` with no fee, which PRD §3.2 explicitly calls a contradictory payload rejected with `ERR_INVALID_REQUEST`; the implementation was correctly refusing it. (3 tests)
- Same helper — added `"retainer_floor_cents": 50_000` to `client_overrides`. The shared `register_client` fixture pins the floor to 0 so unrelated authorization scenarios aren't gated on a deposit, which silently contradicted this scenario's own `assert client["retainer_floor_cents"] == 50_000` and made the whole retainer-floor precedence ladder untestable. (3 tests)
- Same file, `_two_clients_each_in_crisis()` — `trigger_type="CAREGIVER_BREAKDOWN"` → `"CAREGIVER_NO_SHOW"`. `CAREGIVER_BREAKDOWN` is not among PRD §3.7's five declared trigger types. (2 tests)
- `test_suite/test_15_cross_cutting_and_consistency.py`, tests 02 and 03 — `meta["total"]` → `meta["total_count"]`. PRD §2.3 names the field `total_count`; the raw `KeyError` was a typo in the test, not a missing response field. (2 tests)
- `test_suite/test_12_endpoint_behaviours.py`, `test_09_an_unconflicted_engagement_authorizes_while_still_not_required` — the pre-authorization posture assertion `== "ROUTINE"` → `== "ELEVATED"` (docstring updated to match). PRD §3.1 lists "at least one care plan in `ACTIVE` status whose `coverage_gap_flag` is true" as an `ELEVATED` trigger, and at that point the scenario's ACTIVE plan has only a `PROPOSED` authorization beneath it, so the gap flag is still true. The test's own later assertion — `ROUTINE` once authorization closes the gap — was already correct and unchanged. (1 test)

**Fixes applied to `implementation/`:** none. No implementation defect was found; all 154 assertions pass against the original PRD-faithful implementation, and no PRD-required check was weakened or removed.

**Orchestrator verification (guards the known false-clean-sweep failure)**: independently parsed all eight `workspace/implementation/results.{1..8}.json` — each reports `passed=154 total=154 failed=0`. The results files exist and are complete JSON, so the sweep genuinely ran.

**Step 8 decision**: the skill's skip condition requires zero deletions AND zero `test_suite/` fixes AND zero `test_helpers/` fixes AND zero `implementation/` fixes. Step 7 ran 3 iterations with 5 `test_suite/` fix sites, so the skip condition is NOT met and Step 8 will run. Since `implementation/` was never modified, `PRD_FINALIZED.md` may legitimately come back byte-identical to `PRD.md` — the Step 7 fixes were test-artifact bugs, not PRD silences, so there may be nothing for Step 8 to pin. Step 9 then does the substantive full-scan alignment.

## Step 8: Finalize PRD — 2026-09-04T23:50:00.000Z

### Result: zero-diff copy (correct outcome)

`workspace/PRD_FINALIZED.md` was created as a byte-identical copy of `workspace/PRD.md` — 412 lines vs 412 lines, 0 changed lines, **0.0% delta**. `diff` reports IDENTICAL.

Step 7 applied **no** fixes to `implementation/` and deleted no tests; all five items were test-artifact bugs. Each was checked against the implementation independently rather than assumed, and every one traces to a rule PRD.md already states verbatim and uniquely. There is nothing to pin, so no edits were manufactured.

### Per-item verification log (subject → impl paths enumerated → conclusion)

1. **`referral_fee_pct: 10` added to `_referred_vendor_awaiting_disclosure`**
 - Subject: vendor-registration validation of `has_referral_relationship` / `referral_fee_pct`.
 - Enumerated: `implementation/routes/people.py:73-83` (create: `if has_referral and referral_fee_pct <= 0: raise v.bad(...)`, default 0, range 0-100), `people.py:112-117` (standing/fee update path), `serialize.py:62-63`, `routes/authorizations.py:92-95` (the only consumer — mints `disclosure_text` from vendor name + fee pct).
 - PRD §3.2 (line 168) already states the greater-than-zero requirement and the `ERR_INVALID_REQUEST` rejection of a zero/absent fee verbatim, and states the 0-default and 0-100 range. Impl matches exactly. No edit.

2. **`retainer_floor_cents: 50_000` added to client_overrides in the same helper**
 - Subject: `retainer_floor_cents` default and the retainer-floor guard's position in the authorize ladder.
 - Enumerated: `routes/clients.py:36` (`opt_int(..., 50000, 0, None)` — default 50000, min 0), `serialize.py:33`, and every reader of the floor: `routes/authorizations.py:201` (last guard in `_authorize`, after plan-active → client-in-service → vendor-barred → COI → coverage-capacity), `derive.py:437` (nonpayment suspension check), `routes/invoices.py:139` (issue-time slide to `SUSPENDED_NONPAYMENT`).
 - PRD §3.1 (line 152) states the 50,000 default and non-negativity; PRD §3.6 (line 250) states the six-guard order verbatim, and impl `_authorize` reproduces it in that exact sequence. No edit.

3. **`CAREGIVER_BREAKDOWN` → `CAREGIVER_NO_SHOW` in `_two_clients_each_in_crisis`**
 - Subject: crisis-episode `trigger_type` enum domain.
 - Enumerated: `routes/crisis.py:16-17` (`TRIGGER_TYPES` = the exact five), `crisis.py:33` (`req_enum`), `crisis.py:34/40` (`hospital_name` optional, never conditionally required), `serialize.py:186`.
 - PRD §3.7 (line 266) lists precisely those five names. The removed value never existed in the impl. No edit.

4. **`meta["total"]` → `meta["total_count"]` in test_15 tests 02/03**
 - Subject: list-envelope pagination meta field names.
 - Enumerated: `envelope.py:40-49` — the single pagination renderer for all collections, emitting `limit`, `offset`, `total_count`, `has_more`; no `total` key exists anywhere in the impl (grep across all modules).
 - PRD §2.2 (meta sample, line 42) and §2.3 (line 80) both name `total_count`. Pure test typo. No edit.

5. **test_12 test_09: pre-authorization posture `ROUTINE` → `ELEVATED`**
 - Subject: `coverage_gap_flag` derivation and the ACTIVE-plan-with-gap `ELEVATED` trigger in `risk_posture`.
 - Enumerated: `derive.py:144-150` (`coverage_gap_flag`: false only if some auth on the plan is in `AUTHORIZED_SET` = `("AUTHORIZED","ACTIVE")` — a `PROPOSED` auth leaves the flag true), `derive.py:153-171` (`risk_posture`, first-matching-branch: crisis → acuity ≥ `ACUITY_ELEVATED_THRESHOLD` = 70 → adjudicated → any auth `PENDING_DISCLOSURE`/`DISCLOSED` → any ACTIVE plan with gap → `ROUTINE`), `derive.py:28`/`23` (constants), `serialize.py:116` (recomputed on every plan read).
 - PRD §3.4 (line 214) and §3.1 (line 162) state both rules verbatim, including the AUTHORIZED-or-ACTIVE membership and the inclusive 70 threshold. The test's original `ROUTINE` assertion was simply wrong about its own scenario. No edit.

No enumerated path required any wording adjustment, because no wording was changed. The NO-NEW-MISMATCH rule is trivially satisfied by an empty patch.

**Orchestrator note**: a byte-identical `PRD_FINALIZED.md` is the legitimate Step 8 outcome when Step 7 made zero `implementation/` fixes — the five Step 7 items were test-artifact bugs against rules the PRD already pinned. The substantive alignment work therefore falls entirely to Step 9, which will run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 does the `cp`; passes 2 and 3 must not) so the full-implementation scan is not truncated by a single agent's budget.

## Step 9: Complete PRD — pass 1 of 3 (infrastructure + clients/people/serialization) — started

### Step 9 partitioning decision (orchestrator)

Step 9 was run as **three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`**. Rationale: a single agent cannot hold a 3331-line implementation plus a 412-line PRD and still do an exhaustive behavior-by-behavior scan; the known failure mode is a subagent that `cp`s the source PRD and returns a byte-identical file, or truncates the document with a one-shot Write. Pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from copying or recreating the file and were told how many edits the earlier passes had already made, so each built on top of the previous. Hand-off notes were carried forward verbatim between passes so subjects that surfaced in one partition but belonged to another were resolved by their owner rather than dropped.

Partition:
- **Pass 1** — `app.py`, `envelope.py`, `errors.py`, `clock.py`, `store.py`, `auth.py`, `lookup.py`, `validators.py`, `serialize.py`, `routes/clients.py`, `routes/people.py`, `routes/clock_admin.py`
- **Pass 2** — `routes/assessments.py`, `routes/care_plans.py`, `routes/conferences.py`, `routes/crisis.py` + `derive.py` acuity / `coverage_gap_flag` / `risk_posture` / quorum derivations
- **Pass 3** — `routes/authorizations.py`, `routes/time_entries.py`, `routes/invoices.py` + `derive.py` billing / retainer / money / cascade parts

### Pass 1 — infrastructure + clients/people/serialization

**Copy step:** `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` done (pass 1 owns it). PRD_FINALIZED.md = 412 lines / 93,550 chars; PRD_COMPLETED.md after pass-1 edits = 415 lines / 100,064 chars; **char delta +6,485** (3 new lines: one §2.2 bullet + two §5 catalogue rows). All edits surgical `Edit` calls; no whole-file rewrite.

**Counts:** 14 ambiguity-pins, 3 mismatch-revisions (17 edits).

- §2.1 — revise — mismatch — the blanket "supervisor `X-User-ID` must resolve to a care manager with `is_supervisor`" claim now scoped to the operations that actually run it (assessment/authorization/time-entry/decision/client-state) and explicitly *not* on capacity determination, care-plan state, crisis-episode state — `auth.py:76`, `routes/clients.py:82,116`
- §2.1 — insert — ambiguity — a `FamilyDecisionMaker` `X-User-ID` resolving to no contact is `ERR_UNAUTHORIZED`, including on collection reads — `auth.py:89-102`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — `envelope.py:9,18`
- §2.2 — insert — ambiguity — envelope-level rejections: unknown path → 404 `ERR_NOT_FOUND`, wrong method → 405 `ERR_INVALID_REQUEST`, fault → 500 `ERR_INTERNAL`; trailing slash tolerated — `app.py:28,38-54`
- §2.3 — insert — ambiguity — `offset` has no upper bound and past-end yields an empty page with `has_more` false; empty/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` — `validators.py:199-221`, `envelope.py:48`
- §2.3 — revise — ambiguity — `created_at` ties broken by server creation sequence (never `id`), and the client roster reverses the tie-break too — `store.py:58-64`
- §2.3 — insert — ambiguity — filters are exact string comparisons, a null field never matches, undeclared query params ignored, filter values not enum-validated (empty page, not 400) — `lookup.py:73-88`, `validators.py:224-229`
- §2.4 — insert — ambiguity — body instants accept `Z` or numeric offset, bare values read as UTC, unparseable → `ERR_INVALID_REQUEST` — `clock.py:37-52`
- §2.4 — revise — ambiguity — clock surface answers 200 with `data` whose sole field is `current_utc`, and accepts a backwards instant — `routes/clock_admin.py:12-18`
- §2.6 item 4 — insert — ambiguity — absent/empty body = `{}`; non-object body rejected; optional `null` = omitted (default applies) vs required `null` rejected; empty optional string rejected; booleans never accepted as integers — `validators.py:19-129`
- §3.1 — revise — ambiguity — `travel_billing_pct` must be a whole number; `authorized_concurrent_caregivers` has no upper bound — `routes/clients.py:35,37`
- §3.1 — insert — mismatch — `PATCH /state`: non-declared `to_state` → `ERR_INVALID_REQUEST`; `PROSPECT`/`ASSESSMENT_IN_PROGRESS`/`SUSPENDED_NONPAYMENT` and a short-balance `ACTIVE_CARE` → `ERR_INVALID_STATE_TRANSITION` (**not** `ERR_RETAINER_INSUFFICIENT`); restore runs the §3.9 reinstatement cascade; version +1 either way — `routes/clients.py:75-111`
- §3.1 — insert — ambiguity — `basis` required even when recording `PRESUMED_CAPABLE` (text discarded); determination accepted at any client status incl. `DISCHARGED` — `routes/clients.py:114-125`
- §3.2 — revise — mismatch — care-manager `active` is write-once at registration, never updated, never read by any guard — `routes/people.py:42-54`
- §3.2 — revise — ambiguity — `referral_fee_pct` may be fractional and is echoed as supplied — `routes/people.py:29-37,74`
- §3.2 — insert — ambiguity — vendor PATCH with neither field → `ERR_INVALID_REQUEST`; version +1 on no-op writes; `standing` has no state machine and un-barring reinstates nothing — `routes/people.py:107-123`
- §3.2 — insert — ambiguity — report payload fields are unvalidated non-empty strings, never persisted; reports may be sent to non-long-distance contacts (counters move, `report_status` stays `NOT_APPLICABLE`) — `routes/people.py:175-186`
- §3.9 (deposit payload only) — revise — ambiguity — `amount_cents` integer > 0, `received_at` required but unused, deposit accepted at any client status, client `version` +1 unconditionally — `routes/clients.py:128-142`
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` (404) and `ERR_INTERNAL` (500) rows — `errors.py:44-45`

**Modules found already fully pinned:** `errors.py` (every catalogued id's HTTP status matches §5 exactly), `store.py` beyond the ordering tie-break, `lookup.py` per-entity not-found mapping, `serialize.py` client/care-manager/vendor/contact field sets. Ladder ordering in all three route modules already matched §2.6.

### Pass 2 — assessments / care plans / conferences / crisis

**Before:** 415 lines / 100,064 chars → **After:** 415 lines / 105,407 chars (all edits in-paragraph, no structural rewrite).

**Counts:** 22 changes — 18 ambiguity-pins, 4 mismatch-revisions.

- §2.7 — revise — ambiguity — `expected_client_version` is a required integer ≥ 1, so absent/non-integer/≤0 fails as `ERR_INVALID_REQUEST` before the version comparison — `routes/care_plans.py:56`
- §2.9 — revise — mismatch — removed `quorum_met` from the fields recomputed on every read (it is a latched stored boolean; only `surrogate_present` is recomputed) — `serialize.py:158-159`
- §3.3 — insert — ambiguity — `care_manager_id` on assessment creation is taken as supplied and need not equal the acting `X-User-ID` — `routes/assessments.py:34-49`
- §3.3 — insert — ambiguity — a second/later assessment, or one against a non-`PROSPECT`, leaves the client record entirely untouched (no `version` bump) — `routes/assessments.py:60-62`
- §3.3 — insert — ambiguity — assessment edit payload must carry at least one of `domain_scores`/`narrative` else `ERR_INVALID_REQUEST`; `domain_scores: null` reads as absent while `narrative: null` clears the narrative — `routes/assessments.py:91-96`
- §3.3 — revise — ambiguity — withdrawal blocked by a dependent plan reports `ERR_INVALID_STATE_TRANSITION` — `routes/assessments.py:182-187`
- §3.3 — insert — ambiguity — the withdrawal role check depends on current status and runs after resolution, so a withdrawal against a missing assessment reports `ERR_ASSESSMENT_NOT_FOUND` for either role — `routes/assessments.py:125-135`
- §3.4 — revise — ambiguity — missing surrogate on send-for-approval reports `ERR_SURROGATE_AUTHORITY_MISSING`, and the four preconditions run in §2.6 ladder order (discharge first), not narration order — `routes/care_plans.py:155-175`
- §3.4 — revise — ambiguity — `CRISIS` posture blocking activation reports `ERR_INVALID_STATE_TRANSITION`; missing client `capacity_basis` reports `ERR_CAPACITY_BASIS_REQUIRED` — `routes/care_plans.py:184-192`
- §3.4 — insert — ambiguity — activation carries no client-status precondition, so a `SUSPENDED_NONPAYMENT` client keeps that status — `routes/care_plans.py:202-204`
- §3.4 — insert — ambiguity — a named predecessor no longer `ACTIVE` is left untouched and activation still succeeds — `routes/care_plans.py:198-201`
- §3.4 — insert — ambiguity — `SUPERSEDED`/`WITHDRAWN` as `to_state` → `ERR_INVALID_STATE_TRANSITION` after resolution; `PracticeSupervisor` is admitted but owns none of the four outcomes → `ERR_UNAUTHORIZED` — `routes/care_plans.py:19-24,149-151`
- §3.4 — revise — **mismatch** — `coverage_gap_flag` ignores the plan's own `status` entirely (true for any plan with no `AUTHORIZED`/`ACTIVE` authorization, incl. `DRAFT`/`REJECTED`/`SUPERSEDED`/`WITHDRAWN`); status enters only via the risk-posture trigger — `derive.py:144-150`
- §3.5 — insert — ambiguity — a conference may be scheduled whatever the client's status, and scheduling leaves the client untouched — `routes/conferences.py:45-65`
- §3.5 — revise — **mismatch** — on convening, the invited-subset test runs *before* quorum, inverting §2.6's step 10/11 order — `routes/conferences.py:115-123`
- §3.5 — insert — ambiguity — `attended_contact_ids` is 1–12 unique ids (duplicate → `ERR_INVALID_REQUEST`); `quorum_met` latched at convening and never re-evaluated, `surrogate_present` recomputed from stored attendance — `routes/conferences.py:100,124-126`
- §3.5 — revise — ambiguity — `CONVENED → DOCUMENTED` with no surviving decision reports `ERR_INVALID_STATE_TRANSITION` — `routes/conferences.py:136-139`
- §3.5 — revise — **mismatch** — decision documentation guards on `quorum_met` alone, not conference `status`, so a `DOCUMENTED` conference still accepts decisions; no client-status guard — `routes/conferences.py:189-192`
- §3.5 — insert — ambiguity — the decision's `capacity_basis` is a request field stored on and echoed by the decision; the guard reads it, not the client's, and never writes the client's — `routes/conferences.py:175-182,201`
- §3.5 — revise — ambiguity — ratification: conference not `CONVENED`/`DOCUMENTED` → `ERR_INVALID_STATE_TRANSITION`, quorum → `ERR_QUORUM_NOT_MET`; `RECORDED` as `to_state` → `ERR_INVALID_STATE_TRANSITION` — `routes/conferences.py:250-259,297-299`
- §3.5 — revise — **mismatch** — the guardianship and rescission cascades "recompute `risk_posture`" rather than forcing `ELEVATED` (a live episode still outranks it) — `derive.py:153-171`
- §3.7 — insert — ambiguity — `hospital_name` never required and accepted with any trigger; an episode may be opened against a `DISCHARGED` client; `assigned_care_manager_id` comes from `X-User-ID` and is not resolved against the register — `routes/crisis.py:29-49`
- §3.7 — insert — ambiguity — either `CareManager` or `PracticeSupervisor` may drive any episode transition, with no assigned-CM ownership check — `routes/crisis.py:76`
- §3.7 — revise — ambiguity — no standing coverage → `ERR_INVALID_STATE_TRANSITION`; unsettled crisis time on close → `ERR_INVALID_STATE_TRANSITION`; readmission alone leaves the client record untouched — `routes/crisis.py:98-127,114-117`

### Pass 3 — authorizations / time entries / invoices / money

**Before:** 415 lines / 105,407 chars → **After:** 415 lines / 113,204 chars (+7,797 chars, all in-paragraph). **Overall vs PRD_FINALIZED.md (412 / 93,550): +3 lines / +19,654 chars.**

**Counts:** 22 edits — 17 ambiguity-pins, 3 mismatch-revisions, plus 2 self-refinements of its own wording.

- §2.7 — insert — ambiguity — `expected_care_plan_version` is a required integer ≥ 1, so absent/non-integer/≤0 fails at the payload rung as `ERR_INVALID_REQUEST` — `routes/authorizations.py:57`
- §3.6 — insert — ambiguity — proposal reads no client `status`; may be proposed for a `SUSPENDED_NONPAYMENT` client — `routes/authorizations.py:66-81`
- §3.6 — insert — ambiguity — literal `disclosure_text` template with vendor `name` / `referral_fee_pct` substitution — `routes/authorizations.py:44-48,94`
- §3.6 — **revise — mismatch** — activation `AUTHORIZED → ACTIVE` also re-runs the coverage-capacity test (PRD said "requires only that the client's status is ACTIVE_CARE"); does not re-read vendor standing; leaves the client untouched — `routes/authorizations.py:211-220`
- §3.6 — insert — ambiguity — `to_state` enum → `ERR_INVALID_REQUEST`; `PROPOSED` owned by no role and rejected `ERR_INVALID_STATE_TRANSITION` after the record resolves — `routes/authorizations.py:153,176`
- §3.6 — insert — ambiguity — activation / direct suspension / direct termination touch neither client nor plan; only `AUTHORIZED` reaches back into both — `routes/authorizations.py:204-207`, `derive.py:361-376`
- §3.6 — insert — ambiguity — `action` vocabulary `DISCLOSE` / `ACKNOWLEDGE`; the disclosing step leaves the client untouched — `routes/authorizations.py:18,244,261-262`
- §3.6 — insert — ambiguity — a surrogate of another client also yields `ERR_COI_ACK_BY_INELIGIBLE_PARTY`; self-identity → reachability → eligibility order; acknowledgement reads no `auth_status`, so a `TERMINATED` row may be acknowledged — `routes/authorizations.py:264-277`
- §3.8 — insert — ambiguity — `care_manager_id` taken as supplied, need not equal `X-User-ID` — `routes/time_entries.py:107`
- §3.8 — **revise — mismatch** — travel buffer examines exactly two neighbours (nearest preceding and nearest following), across every client; same-location neighbours impose nothing; no more distant entry is consulted — `routes/time_entries.py:66-88`
- §3.8 — insert — ambiguity — `rate_multiplier` / `after_hours_factor` are JSON numbers (`1.2`, `1.0`, `1.5`, `0.5`), not strings — `serialize.py:213-214`
- §3.8 — insert — ambiguity — approval leaves the client record untouched — `routes/time_entries.py:205-208`
- §3.8 — insert — ambiguity — `INVOICED` not requestable (`ERR_INVALID_STATE_TRANSITION` after resolve); no lifecycle transition reads client `status` — `routes/time_entries.py:183,233-235`
- §3.9 — insert — ambiguity — reinstatement skips: ascending `created_at`, skip `BARRED`-vendor rows and capacity-breaching rows, skipped rows stay `SUSPENDED`/`NONPAYMENT` with `version` unmoved, earliest-created candidates win — `derive.py:433-450`
- §3.9 — **revise — mismatch** — invoice-period collision is a window-vs-window closed-interval intersection, not "covers a service date inside"; plus real-calendar-date validation — `routes/invoices.py:36-53`, `validators.py:147-155`
- §3.9 — insert — ambiguity — invoice creation does not touch the client — `routes/invoices.py:63-74`
- §3.9 — insert — ambiguity — `retainer_applied_cents` floored at 0 — `derive.py:337-339`
- §3.9 — insert — ambiguity — `amount_cents` > 0 integer, `received_at`/`method` required but never persisted, client untouched, and a 0 `balance_due_cents` invoice admits no payment and stays `ISSUED` — `routes/invoices.py:171-186`
- §3.9 — insert — ambiguity — draft void: client untouched, provisional figures re-derived once and frozen (`variant` stays `PROVISIONAL`), later reads return the frozen figures — `routes/invoices.py:146-151`, `serialize.py:233-235`
- §3.9 — insert — ambiguity — issued void leaves `variant`/`line_entry_ids`/money fields exactly as issued — `routes/invoices.py:159-164`
- §3.9 — insert — ambiguity — void's reinstatement is subject to the same skips; client touched whether or not the restore fired; only `ISSUED`/`VOIDED` requestable on the invoice state op — `routes/invoices.py:110-112,163-164`
- §3.9 — insert — ambiguity — line ordering tie-break falls through to server creation order, never `id`; empty-line check at creation uses the provisional variant — `derive.py:325`, `routes/invoices.py:59-62`

**Hand-off resolution:** all five inter-pass notes resolved (reinstatement skips → §3.9; `retainer_applied_cents` 0-floor → §3.9; multiplier JSON number types → §3.8; `expected_care_plan_version` integer-≥-1 → §2.7 ¶2); note 5 honoured — no plan-status condition was re-introduced into `coverage_gap_flag`.

**Structural integrity (pass 3 self-check):** 415 lines / 113,204 chars; all five top-level sections present in order (§1 L3, §2 L11, §3 L149, §4 L309, §5 L370); §4's endpoint table and §5's 42-row catalogue intact; ends cleanly on `| ERR_INTERNAL | 500 |` with trailing newline; backtick parity even.

### Step 9 orchestrator verification — 2026-09-05T00:25:00.000Z

- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (`cmp` differs; 103 changed lines; 412 → 415 lines, 93,550 → 113,204 chars, +21.0%). This is the check that catches the known failure where a Step 9 subagent copies the source and never scans.
- All five top-level sections present in order; tail ends on the final complete `| error | code |` row of the §5 catalogue.
- `grep -ic "harder than|expert level|scaffold"` over `PRD_COMPLETED.md` = 0 — no difficulty directive and no scaffold reference leaked into the deliverable.
- No re-sweep needed: Step 9 edits only `PRD_COMPLETED.md`. Confirmed by mtime — `implementation/` last modified 09-04 21:44, `test_suite/` 09-04 23:34, the clean 8-round results files 09-04 23:39, `PRD_COMPLETED.md` 09-05 00:20. The passing sweep therefore postdates every implementation and test change, and nothing but the PRD has been touched since.

**PIPELINE COMPLETE** — Steps 1–9 all done; `workspace/PRD_COMPLETED.md` written.
