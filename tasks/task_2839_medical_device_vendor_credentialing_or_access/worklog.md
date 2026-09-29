# Worklog — task_2839_medical_device_vendor_credentialing_or_access

## Step 1: Create task directory — 2026-09-05T04:45:27.204Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2839_medical_device_vendor_credentialing_or_access` and its `workspace/` subdirectory. Index 2839 was pre-assigned by the orchestrating invocation (no auto-allocation scan of ./tasks/, since up to 32 pipelines run concurrently on this host and any scan-and-increment would collide).

## Step 2: Generate scaffold — 2026-09-05T06:12:00.000Z

Subagent summary (verbatim):

All three artifacts are complete and the lint is clean.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2839_medical_device_vendor_credentialing_or_access/`
- `SCAFFOLD.yaml` — 3091 lines (§1.0–§1.7 only; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2030 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4298 lines, single key `scaffold_corner_design`

All three parse under PyYAML and end at real YAML boundaries.

## §1.0–§1.7 counts
13 entities (Facility, Vendor, VendorRep, Credential, SurgicalCase, CaseRepAuthorization, KioskCheckIn, ProductIntroductionRequest, ApprovedProduct, LoanerSet, Incident, AccessAppeal, ComplianceSweep) · 11 state machines · 2 OCC concurrency rules · 11 calculations · 39 validations (priority-ordered) · 51 endpoints · 51 errors · 8 roles · complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; topology `graph`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.

## §1.8 — 9 rule families × 2 = 18 instances
`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

## §1.9 — all nine sections, 82 instances (66 real + 16 `excluded_because` stubs)
entities 12 · state_machines 16 · calculations 13 · validations 12 · endpoints 5 · errors 10 · rbac 8 · cross-cutting complexity layers 5 · consistency model 1. Every stub cites an existing §1.8 instance by exact name and carries no `test_recipe`; no name collides across §1.8 ∪ §1.9.

## Lint
```
Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     66
  Calls scanned (§1.8+§1.9):  899

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications made while writing §1.9
1. **Unreachable restore branch (SCAFFOLD.yaml fix).** `ApprovedProduct SUSPENDED -> ACTIVE` and all three `LoanerSet HELD -> *` transitions were dead: the restoring trigger needed `adjudicate(UNSUBSTANTIATED)` on an incident already adjudicated SUBSTANTIATED, which validation 20 refused. Added an `Incident SUBSTANTIATED -> UNSUBSTANTIATED` reversal transition and rewrote validation 20, `ERR_INCIDENT_INVALID_STATE` and the adjudicate endpoint text to admit exactly that one re-adjudication (a second SUBSTANTIATED outcome stays a 409).
2. **`fee_status` enum contradiction (fix).** `entities.LoanerSet.fee_status` declared `NOT_ASSESSED | WAIVED | ASSESSED | REVERSED` while the calculation, the state machine and the create endpoint all wrote `NONE`. Canonicalised on `NONE | WAIVED | ASSESSED | REVERSED` (default `NONE`) and updated the one §1.9 assertion that used the old name.
3. **Missing segregation-of-duties field (fix).** Validation 23 and the authorization state machine required "the decider is not the requester", but `CaseRepAuthorization` stored no requester. Added `requested_by_user_id` (system) plus the create-endpoint side effect and tightened the `decided_by_user_id` description.
4. **claim_type discipline.** All 82 `claim_type:` values are rows harvested from `references/claim-extraction-guide.md`; the errors section (which has no table) uses `violation_to_error` per the SKILL.md example, and the many-to-many/self-referential topology corner uses the guide's `graph`.
5. **Scenario left byte-verbatim**, so `SCAFFOLD.yaml` line 2 still carries the `Generate task harder than expert level!` directive. Per your verbatim constraint I did not strip it — worth removing before Step 3 so it cannot leak into PRD.md.

### Orchestrator post-step action (difficulty-directive leak guard)

Per the known failure mode where the scaffold generator copies the difficulty directive into `SCAFFOLD.yaml`'s `scenario:` key — from which it would reach PRD.md — the orchestrator stripped line 2 (`Generate task harder than expert level!`) and its trailing blank line from `SCAFFOLD.yaml` immediately after Step 2. Verified afterwards: `grep -c "harder than expert" SCAFFOLD.yaml` == 0 across the whole task dir, and `yaml.safe_load` still parses with top keys `[scenario, domain_name, api_prefix, complexity_profile, response_envelope, global_constants, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles]`. Final SCAFFOLD.yaml is 3089 lines.

## Step 3: Copy shared files — 2026-09-05T06:14:09.310Z

`cp ./INSTRUCTION.md tasks/task_2839_medical_device_vendor_credentialing_or_access/workspace/INSTRUCTION.md` — 1424 bytes copied, verified present.

## Step 4: Generate PRD — 2026-09-05T06:30:06.422Z

Subagent summary (verbatim):

PRD complete and verified.

**Artifact:** `/home/ubuntu/github/CodingPRD/tasks/task_2839_medical_device_vendor_credentialing_or_access/workspace/PRD.md`

**Final line count:** 471 lines. **Last heading:** `## 5. Error Code Catalogue`; the file ends on the final complete table row (`| ERR_VENDOR_FEE_HOLD | 402 |`) — a real section boundary, no audit footer, no truncation. Built with one initial `Write` plus ten `cat >>` appends, so the 64k single-message cap was never approached.

**Section list**
- `# Medical Device Vendor Credentialing & OR Access API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Quantities, Money, Minutes and Rounding · 2.7 Version Pinning and Optimistic Concurrency · 2.8 Cascade Propagation and Derived-Field Recomputation · 2.9 Path Resolution and the Validation Ladder · 2.10 Segregation of Duties (10 subsections)
- `## 3. Business Logic & Workflows` — 3.1 Facilities, Vendor Enrolment and the Representative Roster · 3.2 Attestation, Verification and Credential Posture · 3.3 The Case Schedule and the Ripples a Reschedule Sends · 3.4 Authorizing a Representative onto a Case · 3.5 The Check-In Kiosk: Two Independent Dimensions · 3.6 Product Introduction: Endorsement, Value Analysis and Supersession · 3.7 Loaner Instrument Sets: Deadlines, Bay Capacity, Delivery Branches and Fees · 3.8 Incidents, the Deepest Cascade in the Domain, and Two Ways of Scoring a Vendor · 3.9 Appealing a Revocation, and the Nine Pinned Phases of a Compliance Sweep (9 subsections)
- `## 4. Endpoint Definitions` — 4-column table, all 51 endpoints
- `## 5. Error Code Catalogue` — 2-column table, all 51 error IDs

**Hard Contracts**
- **Contract 1 (Field-Name Coverage): PASS** — 123/123 `entities[].fields[].name` and 68/68 endpoint identifiers (inputs + path params, optional `?` markers stripped) appear verbatim in backticks. Zero missing.
- **Contract 2 (Rule Coverage): PASS** — all 39 validation priorities reproduced as an ordered 1–39 list in §2.9 with error ID, HTTP status and full `applies_to` scope; all 51 error IDs also referenced in §1–§3 prose, not only in the §5 table; all 61 transitions across the 11 state machines covered (46 with an explicit `FROM → TO` arrow, the other 15 in prose naming both source and target states — the three `→ REVOKED` rep paths, the two credential expiries, the two case cancellations, `SUSPENDED → EXPIRED` for products, the three `→ HELD` entries, `ISSUED → VOIDED`, `ESCORT_ATTACHED → ESCORT_RELEASED`, and the two `→ CLOSED` incident closures); all 11 calculations translated into prose with pinned evaluation order; both `concurrency_rules` covered in §2.7 and restated at their write sites.
- **Contract 3 (§3 Path Purity): PASS** — 329 distinct backticked tokens in §3, none starting with `/`, none a bare HTTP method, none a method+path pair; zero raw occurrences of `/vendor-access` anywhere in §3.

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; §4 is exactly 4 columns × 51 rows; §5 is exactly 2 columns × 51 rows; no pseudocode operators (`==`, `>=`, `<=`, `floor(`, `max(`, `round_half_up`) and no fuzzy words ("approximately", "roughly", "conservatively", "etc.") survive anywhere in the document.

**Coverage decisions worth flagging**
1. **Product suspension trigger on substantiation.** The `incident_type` field gloss says only `UNAPPROVED_PRODUCT_USE` can suspend a product, but both the state machine and the endpoint side-effects key the `ACTIVE → SUSPENDED` cascade on the incident naming an `approved_product_id`. I made the two operational rule tables normative (suspension fires whenever a substantiated incident names a product) and kept the type restriction where it is unambiguous — the rep-suspension hop, which requires `UNAPPROVED_PRODUCT_USE` **and** `CRITICAL`.
2. **`ApprovedProduct.suspended_reason`** — the entity constraint omits `SUPERSEDED` while the transitions use it; the PRD lists all four values.
3. **`CaseRepAuthorization.revoked_reason`** — the enum omits `MANUAL` while the endpoint defaults to it; the PRD states the default is `MANUAL` and separately lists the five enumerated values.
4. **Sweep phase numbering** — the endpoint description lists nine phases starting at credential expiry, but the numbered side-effects label credential expiry as phase 2. I made phase 1 the epoch-stamping step (`epoch_number`, `previous_epoch_number`, `swept_at_utc`), which is the only reading consistent with the numbered bullets.
5. **§2.9 validation ladder placed in §2** rather than scattered through §3, since paths are permitted in §2 — but I still wrote the rungs with descriptive operation names instead of URLs, so no path token appears even there.
6. **"All roles" shorthand** in the §4 table for the 8-role open reads, with the expansion given explicitly in the preamble immediately above the table (all eight role names also appear verbatim in §2.1).

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced; no sibling task directory was read; scratch work stayed in `/tmp/task_2839_scratch/`; no destructive commands were run.

### Orchestrator truncation-guard verification

Independently re-checked the PRD tail per the known doc-generator truncation failure mode: `wc -l` == 471; `grep -n "^#"` lists all 26 headings ending at `## 5. Error Code Catalogue` (line 415); `tail -15` ends on the complete table row `| ERR_VENDOR_FEE_HOLD | 402 |`, a real section boundary rather than a mid-sentence cut. No regeneration needed. Also confirmed the difficulty directive did not leak: `grep -ci "harder than expert\|expert level" PRD.md` == 0.

## Step 5: Generate unit tests — 2026-09-05T07:13:00.000Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message, per the skill, so the implementation generator was physically unable to read `test_suite/` — the directory did not exist when it started.)

Subagent summary (verbatim):

Generation complete and fully verified.

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_2839_medical_device_vendor_credentialing_or_access/test_helpers/`** — 2762 lines
```
 181 __init__.py     353 api_client.py    138 api_errors.py
 202 assertions.py   467 constants.py     337 factories.py
 572 fixtures.py     119 test_users.py    393 types.py
```

**`.../test_suite/`** — 8128 lines, 19 files
```
  19 conftest.py                                    619 test_10_entity_shapes_and_defaults.py
 235 test_01_score_variants_and_deadline_bases.py    433 test_11_credential_and_loaner_state_machines.py
 353 test_02_fee_arithmetic_and_sweep_order.py       582 test_12_case_incident_and_appeal_state_machines.py
 315 test_03_rep_lifecycle_and_badge_dimensions.py   521 test_13_derived_calculations.py
 411 test_04_expiry_and_substantiation_cascades.py   655 test_14_validation_refusals.py
 391 test_05_precedence_of_refusals.py               462 test_15_endpoint_round_trips.py
 339 test_06_boundary_instants_and_zero_tray_fees.py 617 test_16_error_responses.py
 432 test_07_cross_entity_state_dependencies.py      494 test_17_role_authorization.py
 382 test_08_badge_and_bay_overlap.py                460 test_18_concurrency_and_immediate_visibility.py
 408 test_09_counter_and_ledger_conservation.py
```

## Coverage: 113 tests, 113 Design tags, zero instances skipped

Machine-reconciled by parsing both yamls and AST-walking every test docstring:

- **§1.8 difficulty: 18/18 non-stub instances translated, 0 skipped.** 47 tests, every instance carrying ≥2 tests (min 2, no thin instances).
- **§1.9 corner: 66/66 non-stub instances translated, 0 skipped.** 66 tests, exactly one per instance.
- 84 distinct tags emitted = 18 + 66. **Zero tags point at a non-existent instance, zero point at a stub, zero tests are untagged or dual-tagged, and every `Design:` line is the last line of its docstring.**

**Assertions dropped inside otherwise-kept instances** (the PRD-first filter applied at sub-assertion granularity, grouped by cause):
- *Channel does not exist in the PRD* (6): absence-proofs that needed a list-facilities / list-vendors / list-compliance-sweeps endpoint or a `code`/`vendor_code` filter. Substituted with equivalent proofs through declared reads (e.g. an untouched `last_sweep_epoch` instead of an empty sweep listing). Single-credential reads were re-routed to the declared `GET /vendor-reps/{id}/credentials`, losing nothing.
- *PRD does not uniquely derive the value* (6): `open_pir_count == 2` on two unsubmitted drafts (§3.6 self-contradictory), `open_incident_count` (open statuses never defined), `pinned_pir_version` at approval (ambiguous vs the same write's own increment), fresh-set `late_minutes_* == 0` vs null, `escort_required == false` on a `REQUESTED` row (PRD says "stays empty"), and the post-overturn `adjudicated_compliance_score` (sweep phase 3 readable two ways).
- *Design literal contradicted the PRD's own enum/value* (4): `SUBMITTED` → `CLINICAL_REVIEW`, `adjudicated_outcome: null` → `NONE`, plus the documented incident-type substitutions (`BADGE_MISUSE`/`ESCORT_VIOLATION` → `UNBADGED_ACCESS`, `DOCUMENTATION_FAILURE`/`STERILITY_BREACH` → `GIFT_POLICY_VIOLATION`, severity weights preserved).

## Verification output

```
python3 -m py_compile test_helpers/*.py test_suite/*.py   →  py_compile: all OK
python3 -m pytest test_suite/ --collect-only -q           →  113 tests collected in 0.48s
import smoke, all 19 modules exec'd against test_helpers  →  all modules import cleanly
grep skip/xfail/skipif/mock/monkeypatch in test_suite     →  none
grep '["data"]' (double-unwrap)                           →  none
grep -i 'scaffold|design index|corner case'               →  none
non-test_helpers imports in test_suite                    →  only __future__ and pytest (conftest only)
fixtures: every test takes only `api`; one @pytest.fixture, in conftest.py
```

Layout (constraint 1): task root holds `SCAFFOLD*.yaml`, `test_helpers/`, `test_suite/`, `worklog.md`, `workspace/`. `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/` — `find workspace -type d -name test_helpers -o -name test_suite` returns nothing. `worklog.md` untouched (mtime 06:30, before any write). No stray `.md` anywhere; `__pycache__` byproducts removed.

## Two things worth flagging to Step 7

1. **Birth `version`.** Nine tests assert a freshly created row's `version`; `test_15` asserts `0` for a surgical case while `test_10`/`test_11` assert `1` for facility, representative and credential. The PRD only says `version` "increments on every mutation" and never pins the birth value, so at most one convention can hold. If the sweep shows a coherent cluster of version failures, this is a one-line-per-file reconciliation, not an implementation defect.
2. The suite depends on the logical clock reading its startup default `2026-08-01T00:00:00Z` at the top of every test, which `--isolation per-test-server` guarantees.

## Step 6: Generate implementation — 2026-09-05T07:07:00.000Z

Subagent summary (verbatim):

Done. Implementation complete and verified.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2839_medical_device_vendor_credentialing_or_access/workspace/implementation/`)

| File | Lines |
|---|---|
| `start.sh` | 11 |
| `requirements.txt` | 1 |
| `app.py` | 74 |
| `timeutil.py` | 55 |
| `errors.py` | 80 |
| `db.py` | 222 |
| `envelope.py` | 56 |
| `reqval.py` | 181 |
| `calc.py` | 352 |
| `cascades.py` | 224 |
| `routes/__init__.py` | 0 |
| `routes/common.py` | 106 |
| `routes/core.py` | 361 |
| `routes/cases.py` | 408 |
| `routes/kiosk.py` | 129 |
| `routes/products.py` | 402 |
| `routes/compliance.py` | 453 |
| **total** | **3115** |

## Endpoint count: 51/51, exact

I diffed the live Flask `url_map` against the 51 rows of the PRD §4 table (normalising path params): **zero missing, zero extra**. Nothing was invented.

## Verification output

- `python3 -m py_compile` over all 15 `.py` files → `COMPILE_OK`; no file truncated mid-statement.
- `ls -la` + `find . -type f` show exactly the 17 files above — no `__pycache__`, no strays, no data files.
- `git status --porcelain` on the task dir shows only the untracked dir; `worklog.md`, `PRD.md`, `INSTRUCTION.md` and all `SCAFFOLD*.yaml` are untouched (mtimes predate my first write). I never read or waited on the concurrent `test_helpers/` or `test_suite/`.
- `start.sh` reads `$PORT`, binds `0.0.0.0`, guards the pip install (so a per-test reboot is a no-op), and `exec`s the server so signals reach it.

## Smoke tests (three suites, each on a freshly booted server, port 18839)

Every boot was launched with `setsid bash -c 'PORT=18839 exec bash start.sh'` and torn down by resolving the actual listener via `ss -ltnp | grep ':18839 '` and killing that single PID. No `pkill`/`killall` was ever run.

- **smoke.py — SMOKE OK.** Broad happy path across all resource families plus refusals: 404 unknown vendor, 401 bad role, 403 wrong role, 409 duplicate vendor code, 400 `limit=0`, 400 bad time range, filtered/paginated listings, check-in read.
- **smoke2.py — SMOKE2 OK** (all-green after correcting two script-side expectations, see below). Confirms the load-bearing arithmetic: late fees 1824 (6 trays / COMPLEX / 90 min) and 131300 (100 trays / IMPLANT_SPECIALTY / 300 min, i.e. per-tray rounding before multiplication); 24 h implant lead floor; reschedule fee reversal (`fee_status` REVERSED, balance debited to 0, provisional score back to 100, pinned basis retained at 90); SPD bay capacity 409; stale-version 412; fee hold 402; PIR revision limit 422; segregation of duties 403; sweep counters 4/1/1/1 with the badge VOIDED and the rep SUSPENDED/LAPSED/CREDENTIAL_LAPSED; score 94 → TIER_PLATINUM → quota 4→6 → epoch counter reset to 0; sweep row carries no `version` and no `updated_at`; second sweep epoch 2 / previous 1 / 2 vendors rescored.
- **smoke3.py — SMOKE3 OK** (new this session, targeting the paths the first two missed): the two independent check-in dimensions (`ESCORT_PENDING` → check-out refused `ERR_ESCORT_REQUIRED` → attach escort leaves `badge_status` at ISSUED → check-out gives CHECKED_OUT + ESCORT_RELEASED), deterministic badge serial `LK-1-0001`, `ERR_CHECK_IN_ALREADY_ACTIVE`, vendor-scope 403 on another rep's check-out, `ERR_REP_BADGE_WINDOW_CONFLICT` on an overlapping window, the quota hard cap (6th approval OK, 7th → `ERR_VENDOR_ACCESS_QUOTA_EXCEEDED`, `utilization_ratio` 1.5), the full incident cascade (SUBSTANTIATED → product SUSPENDED/INCIDENT_SUBSTANTIATED, set HELD, case BLOCKED, MAJOR non-UPU leaves the rep alone) and its reversal (product ACTIVE/NONE, set back to DELIVERED_ON_TIME, case PENDING), the cancellation cascade (APPROVED→REVOKED/CASE_CANCELLED, REQUESTED→DENIED, badge VOIDED, then 409 on re-cancel and on reschedule), and the appeal window (`ERR_REP_NOT_REVOKED`, `ERR_APPEAL_WINDOW_CLOSED` past the deadline, `ERR_APPEAL_ALREADY_FILED`, SoD on the revoking officer, overturn with no credentials landing on SUSPENDED/CREDENTIAL_LAPSED).

Empirical zero-persistence check: each of the three clean boots started from an empty estate (facility/vendor codes that had 409'd on the previous long-lived server created cleanly), and the clock was back at its default instant.

### Four earlier "failures" that were script bugs, not implementation defects

All four disappeared once smoke2 ran against a clean boot. `second sweep epoch 3/previous 2/vendors_rescored 3` were off by exactly the state a prior suite had left on the same long-lived server. The fourth is worth recording because it looks like a real bug: `coverage after revoke` returned `NOT_REQUIRED` where my script wanted `AT_RISK`. The implementation is correct — PRD §3.4 says the branches are "evaluated strictly top to bottom, so an earlier branch wins over a later one", and PRD §3.3 states outright that the cancellation recomputation "lands on `NOT_REQUIRED` or `UNCOVERED` once `approved_rep_count` has reached zero". A non-implant case with zero approved authorizations never reaches the `revoked_authorization_count >= 1` branch.

## PRD ambiguities resolved by choosing an interpretation

- **Time and identity.** All timestamps read the logical clock (never wall-clock); an internal `_seq` breaks creation-order ties; `version` starts at 1 with exactly one bump per row per operation, enforced by a per-request dirty set flushed once at the end of each mutating handler.
- **Instant shape.** Every caller-supplied instant is canonicalised on ingest to the three-fractional-digit UTC form, so echoed and server-computed instants share one shape and the lexicographic window/bay comparisons are safe.
- **VendorRep `email` uniqueness** has no catalogued error id → enforced with `ERR_INVALID_REQUEST` (400). Same for invalid list-filter enum values (rung 3).
- **Authorization create** leaves `escort_required`, both badge-window instants and `epoch_number` null, with `revoked_reason` = `"NONE"`; `revoked_reason` accepts `MANUAL` as the default when a revoke omits it.
- **Decide ladder.** The DENY branch checks only rungs 13 and 23; APPROVE inserts `ERR_REP_ACCESS_REVOKED` at position 10 because §3.4 forbids approving a REVOKED rep even though rung 10 does not formally name decide; `PENDING_CREDENTIALING` is caught by rung 24.
- **Fees.** `fee_status` precedence NONE → WAIVED → ASSESSED; `late_fee_balance_cents` is always recomputed as the sum over ASSESSED sets rather than incrementally adjusted.
- **`pinned_pir_version`** is the PIR's *post*-mutation version (the one returned in the approval response) — implemented by flushing before minting the product.
- **Sweep phase 6** sets `suspended_reason = "APPROVAL_EXPIRED"` only when the product was ACTIVE, so an already-SUSPENDED product keeps its original cause on record.
- **Substantiation holds** fire only when the product actually moved ACTIVE → SUSPENDED ("each hop exists because the previous one happened"); unsubstantiation reinstates only when `suspended_reason == "INCIDENT_SUBSTANTIATED"`, and never un-suspends the representative. Supersession suspends the product but does *not* hold loaner sets (explicit in §3.6/§3.7).
- **Free-text notes** (`review_note`, `decision_note`, `adjudication_note`, revoke `reason`) are validated but not persisted — the PRD defines no fields for them.
- **Reschedule** recomputes everything except `RELEASED_TO_OR` sets, fires only the two documented backward transitions, and never re-derives `late_minutes_pinned_basis`.

### Orchestrator layout verification (post Steps 5+6)

`ls` of the task root shows `test_helpers/` and `test_suite/` correctly at the task root (not under `workspace/`); `find workspace -maxdepth 2 -type d \( -name test_helpers -o -name test_suite \)` returns nothing, so the known "test dirs land under workspace/" failure did not occur. `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`. `python3 -m pytest test_suite/ --collect-only -q` → 113 tests collected, no collection errors.

## Step 7: Run tests and iterate — 2026-09-05T07:33:31.342Z

Subagent summary (verbatim):

All 8 parallel rounds green: 113/113, zero failures, zero errors, zero skips.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each). Iteration 1: 110/113 in all 8 rounds. Iteration 2: 112/113 (partially stale — collection raced my last four edits). Iteration 3 (authoritative, clean-`__pycache__`): **113/113 in all 8 rounds**, 203s per round.

**Root cause — one coherent cluster, entirely test-side.** All failures were `AssertionError: version should be 0, got 1`. The generator's hint was correct and I verified it independently: PRD §2.5's only sentence about the field is *"**`version`** (integer): a system-managed integer that increments on every mutation of the row."* Grepping every `version` mention in PRD.md confirms the **birth value is never pinned**. Two PRD-faithful readings both exist — row born at 0 (creation is not a mutation of a row that did not yet exist) or born at 1 (the initial write is the first increment) — so this is **DEFAULT-VALUE SILENCE** under STEP 1b. The implementation mints every row at 1 through a single shared `db.stamp_common`, and the suite *already* demanded `1` in three other places, so the suite contradicted itself; a contradiction cannot be an implementation bug in both directions.

**Tests deleted:** none. Every affected test carried substantial PRD-covered content, so all seven sites were handled under **STEP 1c partial-coverage splitting** — the uncovered birth literal removed, the covered rule kept or strengthened.

**Fixes applied to `test_suite/` (7 assertion sites, 4 files):**
- `test_18_...py` — `TestVendorVersionEchoOnASecondRequest`: dropped `assert_integer_field(vendor, "version", 0)`; replaced the absolute `1` and `2` literals with `assert_version_bumped(...)` deltas. This makes the test *more* faithful — PRD verbatim says "A successful create itself increments the vendor's `version` by one", which pins the delta, not the absolute.
- `test_18_...py` — `TestCaseVersionEchoOnASecondTraySet`: same treatment against PRD's "a successful registration ... increments the case `version`". Re-read idempotence (a plain read is not a mutation) now asserts equality against the observed value rather than a literal.
- `test_18_...py`: added `assert_version_bumped` to the `test_helpers` import block.
- `test_15_...py` — `TestSurgicalCaseRoundTrip`: `expected_version=0` dropped from both `assert_common_fields` calls, and the create-vs-read comparison re-expressed as `stored["version"] == created["version"]` (the genuinely covered rule). Also fixed line 148's `assert_integer_field(listed, "version", 0)` → `created["version"]`; this one was **masked** by the earlier abort and would have become the next failure.
- `test_10_...py`: `assert_common_fields(facility, 1)` and `assert_common_fields(stored, 1)` → literal dropped.
- `test_11_...py`: removed `assert_integer_field(filed, "version", 1)`.

The mirror-image `1` literals in test_10/test_11 were passing, but they embed the same PRD-silent value and would have failed a legitimate `version=0` implementation. I neutralised them for the same reason, so the artifact no longer contains *any* absolute birth-`version` assertion (verified by grep). `assert_common_fields` still checks that all four common properties exist, that `id` is a UUID, that both instants are ISO-8601, and that `version` is a non-negative int — only the unfair literal is gone.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:** **none.** No implementation defect was found; `db.stamp_common`/`db.touch` and the mark-then-`flush` cascade pattern (each rewritten row touched exactly once per operation, per §2.8) are coherent and PRD-faithful. No assertion was weakened, no `skip`/`xfail` added, and no `error_id` check downgraded.

### Orchestrator independent verification of the sweep

Because a Step 7 subagent can report a clean sweep without leaving artifacts behind, the orchestrator re-verified from disk rather than trusting the report. All eight `workspace/implementation/results.{1..8}.json` exist (mtime 07:32, ~39 KB each) and every one parses to `passed=113 total=113 failed=0 errors=0 skipped=0`. `grep -rn "mark.skip\|mark.xfail\|mark.skipif" test_suite/` returns nothing, so the green sweep is not skip-assisted. `worklog.md` mtime (07:15) predates the subagent's run, confirming it honoured the instruction not to write its own step heading here.

### Step 8 gating decision

Step 7 ended with 0 deletions, 0 `test_helpers/` fixes and 0 `implementation/` fixes, but **7 `test_suite/` fixes**, so the skip condition (all four counts zero) is not met and Step 8 runs. The substantive PRD silence to reconcile is the one Step 7 adjudicated: PRD §2.5 never pins the birth value of `version`, while the implementation mints every row at 1 via `db.stamp_common`.

## Step 8: Finalize PRD — 2026-09-05T07:36:40.673Z

Subagent summary (verbatim):

PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_2839_medical_device_vendor_credentialing_or_access/workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 471 lines; PRD_FINALIZED.md: 471 lines; **0% line delta** (one line revised in place, no lines added or removed). Both files end at the identical real boundary — the §5 error table's last row `| ERR_VENDOR_FEE_HOLD | 402 |`.

## Changes (1)
- **§2.5 Common Resource Properties** — *revise* — the `version` bullet now pins the birth value: a row is written with `version` at 1 when first created (directly or cascade-minted), each later mutation adds one, and 1 is the smallest observable `version`. — `implementation/db.py:203` (`stamp_common` sets `row["version"] = 1`), `implementation/db.py:211` (`touch` does `+1`).

## Per-edit pre-edit search log

**Edit 1 — §2.5 `version` bullet**

(a) **Subject:** the `version` field's lifecycle — its value at row birth, and every path that reads, writes, or increments it.

(b) **Impl paths enumerated:**
- Grepped every `version` occurrence in `implementation/` (excluding `__pycache__`): `db.py:203/209/211`, `cascades.py:5/15`, `app.py:36`, `routes/compliance.py:440`, `routes/products.py:74/168/307`.
- Read `db.py` in full — `stamp_common` (the single mint site, `version = 1`) and `touch` (`row.get("version", 0) + 1`).
- Enumerated **all 12 `stamp_common` callsites** and read each one to confirm no create ever marks the row it just minted (which would flush it to 2): `routes/core.py:58` facility, `:91` vendor, `:171` vendor_rep, `:293` credential; `routes/cases.py:46` surgical case, `:227` authorization; `routes/products.py:55` PIR, `:160` approved product, `:288` loaner set; `routes/kiosk.py:57` kiosk check-in; `routes/compliance.py:42` incident, `:196` appeal. Each marks only the *parent* (vendor / case) or nothing at all.
- Read `cascades.py` in full — `mark*`/`flush()` dirty-set design (one `db.touch` per row per operation) plus `app.py`'s `before_request` reset, confirming the increment-exactly-once semantics my wording ("every subsequent mutation adds one") must not contradict.
- Checked the cascade-minted case specifically: `_mint_approved_product` (`products.py:160`) plus the `SUPERSEDED` supersession loop at `products.py:212-217` — the newly minted product cannot match `supersedes_request_id`, so it is never suspended/touched in its own creating operation and is readable at 1. This is why the wording explicitly covers "or a cascade minted it".
- Checked the "smallest observable value" claim against the only rows lacking a `version` key: `store.sweeps` (`compliance.py:450`). Grepped `sweeps` across `routes/`, `calc.py`, `cascades.py` — sweeps are written once and only read for `epoch_number`, never marked or touched, so `touch`'s `get("version", 0)` default is unreachable and no row can surface `version` 0.
- Verified read-idempotence (relied on by the reworked test_15/test_18 assertions) is already determined and unaffected: `common.ok/created/listing` (`routes/common.py:90-102`) never touch, and no `cascades.flush()` appears in any GET handler (all 23 `flush()` sites are POST handlers).
- Read PRD §2.5/§2.7/§2.8 to confirm the existing delta statements ("A successful create itself increments the vendor's `version` by one", the reschedule/registration increments, the §2.8 cascade rule) stay verbatim and remain arithmetically consistent with a birth value of 1.

(c) **Wording adjustment made:** two. First, an earlier draft phrased the guarantee as "the representation returned by a create carries `version` 1"; that is false for `ApprovedProduct`, which is minted inside the value-analysis approval whose response body is the *request*, not the product — rephrased to "a row is written with `version` at 1 when it is first created … whether the caller created it directly or a cascade minted it". Second, I dropped a drafted clause about creates that also re-mutate the new row; no such path exists, so the clause would have described behavior the implementation does not exhibit.

**Not patched (deliberate):** `pinned_pir_version` (`products.py:168`). The approve path flushes the PIR *before* minting, so the pinned value is the request's post-approval `version`; PRD's existing "observed at the moment of approval" is compatible with that, this is not a Step 7 site, and tightening it would be an out-of-scope edit. The test-side changes in `test_10`/`test_11`/`test_15`/`test_18` that merely dropped absolute literals in favor of already-PRD-pinned deltas need no PRD change beyond the birth value above.

### Orchestrator verification

`diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 95, the §2.5 `version` bullet, extended in place to pin the birth value at 1). Both files are 471 lines and both still end on `| ERR_VENDOR_FEE_HOLD | 402 |`, so no trailing section was lost to the output cap. A byte-identical PRD_FINALIZED.md would also have been legitimate here (Step 7 applied 0 implementation fixes), but the `version` birth-value silence was a genuine impl-pinned choice worth recording.

### Step 9 execution plan (orchestrator decision)

Step 9 is a full PRD-vs-implementation scan over a 3115-line, 17-file implementation and a 471-line PRD. A single subagent asked to do that in one pass reliably under-scans and returns a PRD_COMPLETED.md that is byte-identical to its input — i.e. the scan never really ran. To prevent that, the orchestrator runs Step 9 as **three sequential passes, partitioned by implementation module**, each editing the same shared `workspace/PRD_COMPLETED.md`:

- **Pass 1** — does the `cp PRD_FINALIZED.md PRD_COMPLETED.md`, then scans the foundation and core registry: `app.py`, `db.py`, `envelope.py`, `errors.py`, `reqval.py`, `timeutil.py`, `routes/common.py`, `routes/core.py`.
- **Pass 2** — must NOT re-copy; scans `routes/cases.py`, `routes/kiosk.py`, `calc.py`.
- **Pass 3** — must NOT re-copy; scans `routes/products.py`, `routes/compliance.py`, `cascades.py`.

Passes are sequential (never concurrent) because they share one output file, and each is told to read the whole implementation for context but to edit only for behaviors owned by its assigned modules.

## Step 9: Complete PRD — 2026-09-05T08:05:47.908Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying and edited in place.

### Pass 1 (app.py, db.py, envelope.py, errors.py, reqval.py, timeutil.py, routes/common.py, routes/core.py) — verbatim summary

Pass 1 complete.

**cp performed:** yes — `PRD_FINALIZED.md` → `PRD_COMPLETED.md` as pass 1's Step 0, then edited only `PRD_COMPLETED.md`.

**Line counts / delta:** PRD_FINALIZED.md 471 lines / 109,212 chars → PRD_COMPLETED.md 475 lines / 115,232 chars (+4 lines, +6,020 chars). Tail still ends at `| ERR_VENDOR_FEE_HOLD | 402 |`. 12 edit sites, all targeted `Edit` replacements.

**Counts:** 9 ambiguity-pins, 3 mismatch-revisions.

**Changes**
- §2.1 — revise — ambiguity — empty (not just absent) auth header is `ERR_UNAUTHENTICATED`, and the role comparison is case-sensitive — `reqval.py:17`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 uppercase-alnum chars — `envelope.py:9,18`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the **logical clock**, not real time (incl. on the clock-set call itself) — `envelope.py:24`
- §2.3 — insert — ambiguity — creation-timestamp ties (the normal case, since the clock is manual) break by server creation sequence, making list order total and stable — `db.py:222`
- §2.3 — insert (new paragraph) — ambiguity — filter semantics: conjunctive exact-equality; empty-string filter ignored; out-of-domain enum / non-boolean boolean filter ⇒ `ERR_INVALID_REQUEST` 400 rather than empty page; identifier filters never existence-checked ⇒ empty page — `reqval.py:144-172`
- §2.4 — revise — ambiguity — `current_utc` is required, echoed as the single `current_utc` field in `data`, normalised, carrying no common properties — `routes/core.py:354-361`
- §2.5 — insert — ambiguity — with the sweep-row exception, every declared property is present on every read; unwritten fields are JSON `null`, not omitted — `routes/core.py:181-184`, `routes/cases.py:236-243`
- §2.5 — insert — ambiguity — caller-supplied instants accepted as `Z` / numeric offset / no designator, and **normalised to three-fractional-digit UTC before storage**, so echoes and all stored-instant comparisons use the canonical string — `reqval.py:87-105`, `timeutil.py:12-43`
- §2.9 rung 3 — insert — ambiguity — JSON `null` ≡ omitted; undeclared fields ignored; absent/empty body ≡ `{}`; non-object or unparseable body fails; integer rejects boolean; strings have no minimum length — `reqval.py:31-118`
- §2.9 rung 10 — revise — **mismatch** — "four operations" → five: revoking a representative's site access also raises `ERR_REP_ACCESS_REVOKED` — `routes/core.py:222`
- §3.1 — revise — **mismatch** — rep `email` collision is `ERR_INVALID_REQUEST` (400), checked after `vendor_id` resolution; rep registration is not vendor-scoped; the three audit fields are present-with-`null`, not "absent" — `routes/core.py:163-184`
- §3.2 — revise — ambiguity — revoke-access `reason` is required free text that is validated but never persisted; already-`REVOKED` ⇒ `ERR_REP_ACCESS_REVOKED`; `suspension_reason`/`reinstated_at_utc` left untouched — `routes/core.py:216-228`
- §3.8 — insert — ambiguity — scorecard `data` is exactly the 14 fields with no common properties; `utilization_ratio` is a JSON number from live counters; and definitions for `substantiated_incident_count` (incl. `CLOSED`), `open_incident_count`, `late_delivery_count` (the late-delivery-penalty population) — `routes/core.py:127-151`, `calc.py:261-268`
- §5 — insert — **mismatch** — the catalogue is not exhaustive of all responses: `ERR_NOT_FOUND` 404 (unknown path), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 sit outside the ladder and table — `app.py:43-64`

**Deliberately left unpatched**
- `strict_slashes = False` (trailing-slash tolerance) and `JSON_SORT_KEYS = False` (key order) — no observable contract the PRD contradicts; pinning them would add noise.
- The `415` handler mapping to `ERR_INVALID_REQUEST` — unreachable, since `read_body` uses `get_json(silent=True)`.
- `cascades.flush()` recomputing a marked vendor's `late_fee_balance_cents` and both scores on an authorization revoke, which §3.8's "recomputed whenever…" list does not include: provably value-identical (inputs unchanged) and the vendor row is legitimately rewritten anyway, so §2.8's version rule already covers it. No wording added, to avoid a false universal.
- Intra-rung-3 field evaluation order (which `ERR_INVALID_REQUEST` *message* surfaces first) — the `error_id` is the same either way, and messages are not pinned anywhere in the PRD.
- Verified the impl's `ERROR_STATUS` table is exactly the 51 rows of §5 (the 6 apparent extras are the `DEFAULT_MESSAGE` duplicates), so no status-code edits were needed.

### Pass 2 (routes/cases.py, routes/kiosk.py, calc.py) — verbatim summary

Verification complete. All checks pass: 475 lines, same 24 headings as PRD_FINALIZED, file still ends on `| ERR_VENDOR_FEE_HOLD | 402 |`, and every one of pass 1's edited lines (15, 46–47, 80, 86, 97, 99, 135, 142, 189, 207, 321, 419–421) is intact in the diff.

**No copy performed** — I opened the existing `PRD_COMPLETED.md` and applied 19 targeted `Edit` replacements in place. Pass 1's edits are all still present in the final `diff PRD_FINALIZED.md PRD_COMPLETED.md` (including its rung-10 "revoking a representative's site access" clause, which I extended rather than replaced).

**Size:** 475 lines (unchanged from pass 1; all edits are in-paragraph). 115,232 → 120,415 chars, so **+5,183 chars added by pass 2**. Changed lines: 144, 149, 213, 219, 221, 227, 237, 247, 291, 315.

**Counts:** 13 ambiguity-pins, 7 mismatch-revisions.

- §2.9 rung 10 — revise — mismatch — `ERR_REP_ACCESS_REVOKED` applies to six ops, not five; the authorization approval branch also raises it — `routes/cases.py:332`
- §2.9 rung 15 — revise — mismatch — `ERR_CASE_NOT_SCHEDULED` applies to six ops; the authorization approval branch also raises it — `routes/cases.py:338`
- §3.3 — insert — ambiguity — `case_number` uniqueness scans every case at the facility whatever its status, so a `CANCELLED` number is not freed — `routes/cases.py:42`
- §3.3 — revise — mismatch — a `RESTRICTED` case does not *validate* that an escort is named; it only writes `escort_required` true, and an approval with no `escort_user_id` is accepted — `routes/cases.py:361`
- §3.3 — insert — ambiguity — reschedule refreshes only `APPROVED` authorizations, in creation order; other statuses keep their stored window — `routes/cases.py:99`
- §3.3 — insert — ambiguity — badge-window and check-in rewrites are unconditional, so `version` moves even when the recomputed window is identical — `routes/cases.py:105`
- §3.3 — revise — mismatch — the reschedule's loaner-set set is "everything but `RELEASED_TO_OR`", i.e. it includes `REJECTED_LATE`, which the old enumeration omitted — `routes/cases.py:119`
- §3.3 — insert — ambiguity — the three re-derived loaner instants are written unconditionally (version moves regardless) — `routes/cases.py:128`
- §3.3 — revise — mismatch — only a `DELIVERED_LATE` set flips to `DELIVERED_ON_TIME`; the old sentence was a false universal — `routes/cases.py:138`
- §3.3 — revise — mismatch — vendors are rescored/rebalanced for every set the reschedule *visited*, not only those that changed branch — `routes/cases.py:149`
- §3.3 — insert — ambiguity — `cancellation_reason` is required but never persisted, so it is absent from the response — `routes/cases.py:182`
- §3.3 — insert — ambiguity — cancellation's `REQUESTED → DENIED` leaves `decided_by_user_id`/`decided_at_utc` null — `routes/cases.py:193`
- §3.4 — insert — ambiguity — a `DENY` ignores any supplied `escort_user_id` and evaluates none of the rep/case/credential/quota/fee tests — `routes/cases.py:312`
- §3.4 — revise — mismatch — the approval tests `access_status` only for `REVOKED`/`SUSPENDED`; `PENDING_CREDENTIALING` is caught by the posture rung instead — `routes/cases.py:331`
- §3.4 — insert — ambiguity — implant backing accepts any `ACTIVE` implant product of the vendor, with no facility or case constraint — `routes/cases.py:292`
- §3.4 — insert — ambiguity — `revoked_reason` is validated against the full six-value domain and stored verbatim — `routes/cases.py:384`
- §3.5 — insert — ambiguity — the badge counter advances only on a successful issue and is never reissued — `routes/kiosk.py:20`
- §3.5 — insert — ambiguity — the check-in's `escort_user_id`/`escort_attached_at_utc` start null and are never copied from the authorization — `routes/kiosk.py:68`
- §3.7 — insert — ambiguity — reschedule re-adjudication runs downhill only: on-time-turned-late, still-late, `REJECTED_LATE`-turned-zero and `HELD` sets all keep their status and their existing fee — `routes/cases.py:138-148`
- §3.8 — insert — ambiguity — a loaner set belongs to the vendor of the request that minted its approved product, not to whoever registered it — `calc.py:55-61`

**Deliberately left unpatched:**
- §2.9 rungs 11/24/37/38/39 still say "deciding a case authorization" without the approval-branch qualifier. §3.4 now states explicitly that the deny branch evaluates none of them; qualifying five more rungs would have been redundant edits.
- Attach-escort's check order (badge before escort) is already pinned by the ladder's top-to-bottom rule with rung 18 preceding rung 19.
- §4's row for `GET /surgical-cases` says "filterable by facility and status" while impl also filters coverage/readiness — §3.3 already enumerates all four filters, and the table's Description column is prose rather than normative.
- §3.1's `restricted_escort_required` sentence (`routes/core.py`, pass 1's partition) reads as a naming requirement; the §3.3 revision pins the actual mechanism.
- Out of my partition, for the record: §3.9 phase 4 names a field `approved_authorization_count` where impl uses `approved_rep_count` (`cascades.py:142` — pass 3), and `timeutil.fmt_instant` truncates rather than rounds sub-millisecond input (pass 1).

### Pass 3 (routes/products.py, routes/compliance.py, cascades.py) — verbatim summary

Verification complete. Final state confirmed.

**No re-copy performed** — I opened `workspace/PRD_COMPLETED.md` and applied 20 targeted `Edit` replacements in place. The diff against `PRD_FINALIZED.md` shows 40 replaced paragraphs (80 diff lines) spanning §2.1, §2.2, §2.3, §2.5, §2.8, §2.9 rungs, §3.1–§3.9 and §5 — i.e. passes 1 and 2's edits are all still present alongside mine. Line count is unchanged at **475** (every edit is in-paragraph; no new sections/paragraphs).

**Final: 475 lines, 125,800 chars** (was 120,415 → **+5,385 chars** added by pass 3).
**Counts: 8 mismatch-revisions, 10 ambiguity-pins** (18 distinct changes; 2 extra Edit calls were wording refinements of my own inserts).

### Changes
- §2.8 — insert — ambiguity — a cascade-rewritten row's `version` moves **exactly once per operation** however many hops touch it (two held sets of one case ⇒ one bump) — `cascades.py:16-19,68-84`
- §3.6 — revise — mismatch — `supersedes_request_id` is resolved for existence only, **not** required to be the acting vendor's own request; stored/read back as explicit `null` rather than absent — `routes/products.py:44-49`
- §3.6 — revise — mismatch — `open_pir_count` counts only `CLINICAL_REVIEW`/`VALUE_ANALYSIS_REVIEW`/`CHANGES_REQUESTED`; a `DRAFT` request is **not** counted, so opening one does not raise it — `routes/products.py:121,27` (`PIR_OPEN_STATUSES` in db.py is dead code)
- §3.6 — insert — ambiguity — submit's `DRAFT` branch rewrites the vendor row (`version` +1); the `CHANGES_REQUESTED` branch leaves the vendor row untouched — `routes/products.py:119-125`
- §3.6 — revise — ambiguity — `pinned_pir_version` is the request's **post-approval** `version` (flush precedes minting), i.e. the number in the same response — `routes/products.py:204-211,168`
- §3.6 — revise — mismatch — approved-product listing is also narrowable by `vendor_id` and `facility_id`, matched via the originating request — `routes/products.py:232-248`, `calc.py:44-53`
- §3.7 — revise — ambiguity — a registered set's `late_minutes_pinned_basis`/`late_minutes_current_basis` start at `0` (not `null`), `delivered_at_utc` at `null` — `routes/products.py:296-300`
- §3.7 — revise — mismatch — receipt rewrites the vendor row on **all three** branches, including on-time (fee balance + both scores recomputed, `version` +1) — `routes/products.py:370-374`
- §3.8 — insert — ambiguity — investigating rewrites only the incident; the vendor row's `updated_at`/`version` do not move — `routes/compliance.py:104-108`
- §3.8 — insert — ambiguity — product suspension hop fires **only** from `ACTIVE`; if it does not fire (already `SUSPENDED` for another cause, or `EXPIRED`) the loaner-set hold does not fire either — `cascades.py:205-211`, `routes/compliance.py:116-119`
- §3.8 — insert — ambiguity — rep-suspension hop fires only from `CREDENTIALED`; a `PENDING_CREDENTIALING`/already-`SUSPENDED`/`REVOKED` rep is untouched and no authorization is revoked — `cascades.py:217-224`
- §3.8 — insert — ambiguity — scores are taken after every hop lands, so a set moved to `HELD` has already left the late-delivery penalty population (+5 back per newly held `DELIVERED_LATE` set; `REJECTED_LATE` is never held) — `cascades.py:178-186`, `calc.py:261-268`
- §3.8 — revise — mismatch — unsubstantiation reinstates the product **this incident names** whenever it sits in `SUSPENDED` for `INCIDENT_SUBSTANTIATED`, whichever incident suspended it and even if this one never suspended anything; hold release runs only if that reinstatement fired; a returning `DELIVERED_LATE` set resumes its 5-point penalty in the same call — `routes/compliance.py:122-135`
- §3.9 — insert — ambiguity — an overturned appeal leaves `revoked_by_user_id`/`revoked_at_utc` standing — `routes/compliance.py:243-254`
- §3.9 — insert — ambiguity — phase 3 recomputes posture for every non-`REVOKED` rep whatever its `access_status` — `routes/compliance.py:287-291`
- §3.9 — insert — ambiguity — phase 3 does **not** rewrite a rep whose posture/`ever_credentialed` are unchanged and which takes neither transition (no `version` bump) — `cascades.py:90-106`
- §3.9 — revise — **mismatch (cross-partition item 1)** — phase 4 decrements `approved_rep_count`, not `approved_authorization_count`, and also decrements the rep's `open_authorization_count` — `cascades.py:142,131`
- §3.9 — insert — ambiguity — phase 6 writes `suspended_reason = APPROVAL_EXPIRED` only on the `ACTIVE → EXPIRED` move; an already-`SUSPENDED` product keeps its existing reason — `routes/compliance.py:347-351`
- §3.9 — insert — ambiguity — phase 8 step four writes **both** score variants from the one overage penalty and one lapsed count, held frozen internally (not new vendor fields) — `routes/compliance.py:385-389`, `calc.py:297-309`

### Cross-partition items handed to me
1. **Confirmed and fixed.** `cascades.py:142` writes `approved_rep_count`; `approved_authorization_count` existed nowhere in the implementation and appeared only in §3.9 phase 4. That name is now gone from the PRD (grep-verified), and the omitted `open_authorization_count` decrement was added so phase 4 matches §3.3/§3.4's description of the same cascade.
2. **Reviewed; two real gaps found and fixed, both in the cascade chain reachable from `cases.py` but owned by me:** (a) the hop-conditionality of substantiation/unsubstantiation (product must be `ACTIVE`; rep must be `CREDENTIALED`; hold-release only if reinstatement fired), and (b) the score-recomputation-after-all-hops ordering that makes `HELD` transitions move the late-delivery penalty. `cases.py`'s reschedule/cancel use of `cascades.revoke_authorization` and `_refresh_loaner_sets` was re-verified against pass 2's §3.3/§3.7 text and is already accurate — nothing left to fix there.

### Deliberately left unpatched
- §4 table descriptions omit some list filters (`is_implant` on PIRs, `fee_status` on loaner sets). §3.6/§3.7 prose enumerates them correctly, and the table's descriptions are uniformly loose (including in passes 1/2's rows), so tightening only my rows would create inconsistency.
- Rung 35's revision-bound check on *submission* is unreachable in the implementation (`CHANGES_REQUESTED` with `revision_round == 2` cannot be produced, since the third change request is refused first). The ladder text is not wrong, only redundant, so I left it.
- `vendor_coverage_status` is in fact recomputed on every case flush (loaner registration/receipt/release too), not only on the triggers §3.4 lists; the recomputation is idempotent and its list is phrased non-exclusively, so there is no observable divergence to pin.
- No server was booted; all findings are from static reading of `implementation/`.

### Orchestrator final verification (Step 9 close-out)

- `PRD_COMPLETED.md` is **475 lines / 125,800 chars** vs `PRD_FINALIZED.md`'s 471 / 109,212 — **+16,588 chars, 40 paragraphs revised (80 diff lines)**. It is emphatically NOT byte-identical to its input, so the scan genuinely ran (the failure mode the 3-pass split exists to prevent).
- `diff <(grep '^#' PRD.md) <(grep '^#' PRD_COMPLETED.md)` is empty — all 26 headings preserved, no section added or dropped.
- File still ends on `| ERR_VENDOR_FEE_HOLD | 402 |`, a real section boundary; no output-cap truncation.
- `grep -c "approved_authorization_count" PRD_COMPLETED.md` == 0 — the phantom field name pass 2 spotted is gone.
- The Step 7 green sweep artifacts are intact and still on disk: all eight `workspace/implementation/results.{1..8}.json` parse to 113/113.
- `find . -name "worklog*"` returns only `./worklog.md` at the task root — no worklog drift into `workspace/` (a known Bash-cwd-persistence hazard; every append in this run used an absolute path).

**PIPELINE COMPLETE.** All nine steps finished. Final deliverables: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 files), `test_suite/` (19 files, 113 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, and `workspace/implementation/` (17 files, 3115 lines, 51/51 endpoints) passing 113/113 across all 8 stability rounds.
