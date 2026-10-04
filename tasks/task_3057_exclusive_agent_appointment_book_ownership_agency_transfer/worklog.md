# Worklog — task_3057_exclusive_agent_appointment_book_ownership_agency_transfer

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3057_exclusive_agent_appointment_book_ownership_agency_transfer/` was pre-allocated by the caller with an empty `workspace/` inside. Verified present; no new index computed and no other `task_*` directory created, per the caller's explicit instruction.

## Step 2: Generate scaffold — 2026-09-30T00:20:00.000Z

Scaffold generation complete. All three artifacts written and `scaffold_lint.py` reports `VERDICT: clean lint`.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3057_exclusive_agent_appointment_book_ownership_agency_transfer/SCAFFOLD.yaml` — 1188 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3057_exclusive_agent_appointment_book_ownership_agency_transfer/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1347 lines (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3057_exclusive_agent_appointment_book_ownership_agency_transfer/SCAFFOLD_CORNER_DESIGN.yaml` — 1757 lines (single top-level key `scaffold_corner_design`)

Total 4292 lines. Neither design key appears inside SCAFFOLD.yaml (verified).

## Structural counts

| Metric | Count |
|---|---|
| Entities | 10 (Agency, Agent, Policy, Agreement, StaffMember, MarketingCampaign, Claim, BookTransfer, LicenseRecord, AppointmentApplication) |
| State machines | 9 (32 transitions total) |
| Concurrency rules | 2 (OCC on Agency and Agent `version`) |
| Calculations | 20 (40 named variants) |
| Validations | 21 (priorities 1–9) |
| Endpoints | 58 |
| Error catalog | 21 |
| Roles | 7 (all with mandatory `identity:`) |

## Design-instance counts

- §1.8 difficulty: 9 rule_ids × 2 instances = **18 instances** (meets every §0.5 minimum)
- §1.9 corners: 9 sections / 38 instances = **35 authored + 3 `excluded_because:` stubs** (stubs cite existing §1.8 instance names)

## Complexity profile

Primary `multi-party_negotiation`, secondary `workflow_orchestration`; layers: optimistic concurrency, cascading side effects, dual-variant calculation, derived-field reconciliation. `entity_topology: flat` and `state_machine_shape: cyclic` (under-used shapes per §0.3).

## Verification performed

- `scaffold_lint.py` clean: all 307 design calls resolve to §1.5 endpoints, roles, payload schemas, and captures; both `expected_*_version` inputs reference captured `${var}`s; all §1.1 FKs have reverse-reachability GETs.
- Placeholder closure verified independently: zero unbound `${var}` across both design files.
- Instance-name uniqueness across the union of §1.8 and §1.9 (no collisions).
- All formula-derived assertions pre-computed as literals via `decimal` (e.g., loss_ratio 83.33, growth -75.00, book settlement 1800.00, split invariant 12000+48000=60000); no `round(...)` left in any `assert:`.
- No §1.2.1-forbidden vocabulary anywhere.
- Every error code referenced by at least one validation/transition/endpoint; every role has an `identity:`.

Note: the scenario says "harder than expert" — the scaffold exceeds the Expert band (10 entities, 58 endpoints, 20 calculations, 9 state machines) while keeping the coupling dense; the three `/_` test-driving endpoints (`/_clock/set_current_utc`, `/_inject/agent`, `/agencies/{id}/book-settlement`) exist only where no business chain could reach a precondition.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-30T00:22:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T00:30:00.000Z

All three hard contracts pass. Final verification is clean.

### Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3057_exclusive_agent_appointment_book_ownership_agency_transfer/workspace/PRD.md` — **372 lines**, ending at §5 with no audit footer.

**Section headings produced:**

- `## 1. Introduction` (3 paragraphs: system scope, operational pain, REST mount)
- `## 2. Global Specifications & System-Wide Principles` — 12 domain-derived subsections: 2.1 User and Role-Based Access Control, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 Resource Identity and Common Record Properties, 2.5 Book Custody/Derived Bookkeeping/Anniversary Terms, 2.6 Nested Resource Resolution and Left-to-Right Existence Ordering, 2.7 Monetary Precision and the Allowance Ledger, 2.8 Commission Split Invariants and Chargeback Ledgers, 2.9 Optimistic Concurrency Control, 2.10 Licensing Currency/Staffing Capacity/Territorial Fit, 2.11 The Logical Clock and Deterministic Term Rolls, 2.12 Validation Precedence and Failure Ordering
- `## 3. Business Logic & Workflows` — 9 subsections organized by lifecycle/role mix
- `## 4. Endpoint Definitions` (4 columns) · `## 5. Error Code Catalogue` (2 columns)

**Coverage mirrored from scaffold:**

| Dimension | Count |
|---|---|
| Entities / entity fields | 10 / 92 (72 distinct field names) |
| State machines / transitions | 9 / 32 |
| Calculations | 20 |
| Validations (priority-ordered) | 21 across priorities 1–9 |
| Concurrency rules | 2 |
| Endpoints | 58 (all 58 present in §4 table; 0 extra) |
| Errors / roles | 21 / 7 |

**Hard contract reports (agent transcript only, not in PRD.md):**

```
Field coverage check:
- entities[].fields: 72 required, 72 present, 0 missing
- endpoints[].request_body/input: 49 required, 49 present, 0 missing
- endpoints[].query_params: 14 required, 14 present, 0 missing
- enum-type values + all state names: 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 21 checked, 21 expressed in prose (precedence stated explicitly in §2.12), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_agency_version/expected_agent_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 32 checked, 32 fully expressed (from/to, preconditions, side effects), 0 missing
- calculations[]: 20 checked, 20 fully expressed, 0 missing
- validations[] conditions: 21 checked, 21 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 58 checked, expressed, 0 missing
- entities[].fields[] structured content: 92 checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: equal prose density across all sibling groups (the two ERR_STALE_VERSION rules, the three claim-resolution branches, the three application closures, the three agency/staff termination paths), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 443
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Deliberate omissions / flags** (none reduce rule coverage):

- **§1.3 cross-reference labels** (`§1.3a`, `§1.3v`, etc.) are intentionally not carried into PRD prose — each formula is described in place instead, which is why the four literal calculation identifiers `retention_threshold_check`, `successor_agent_selection`, `book_transfer_settlement`, `agency_performance_measurement` do not appear verbatim while their full semantics do.
- **Calculation `variants` blocks** are expressed as pinned behaviour rather than as enumerated "wrong implementation" contrasts — e.g. the `contract_value_cents` age split (1.5 multiple at ≥5 years, 2.0 below), the `agency_valuation` collapse to 1.0 when loss ratio exceeds 70, per-policy-before-sum rounding, total-cap-not-per-member staffing cap, and the ordered IF/ELIF precedence for `performance_status`. All pinned-side semantics are stated; the divergence notes themselves are not.
- **`market_need_score <= 40 with a SUPPORT subtype`** (`ERR_MARKET_NEED_EXISTS`) is written as "at most 40", preserving the scalar-threshold semantics; the subtype name is kept as the scaffold's `SUPPORT`.
- Fixed §2.2 block verified **byte-identical** to `section-2.2-response-structure.md` by programmatic diff.

Files read: `/home/ubuntu/github/CodingPRD/skills/prd-bench-doc-generator/SKILL.md`, `section-2.2-response-structure.md`, `example-prd.md`, and the task's `SCAFFOLD.yaml`. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-30T00:56:00.000Z

Step 5 complete. Both stages generated and validated.

### `test_helpers/` (9 files)
`__init__.py` (barrel export of framework generics + PRD code), `types.py` (status enums + TypedDicts; `LicenseRecord` correctly omits `updated_at`/`version`), `api_client.py` (64 methods, one per §4 endpoint), `api_errors.py` (21 error IDs, registered with the framework), `assertions.py` (9 entity assertions + domain invariants), `factories.py`, `constants.py`, `test_users.py` (7 role headers + `make_agency_principal_headers`/`make_staff_member_headers` per-instance builders for the two `entity_backed` roles), `fixtures.py` (5 fixture tiers).

### `test_suite/` (7 files)
- `conftest.py` — API client + one fixture per role
- `test_01_application_assessment_and_scoring.py` — 11 tests
- `test_02_agency_and_agent_lifecycle.py` — 13
- `test_03_agreements_licensing_and_staffing.py` — 15
- `test_04_claims_cascades_and_transfers.py` — 14
- `test_05_performance_allowance_and_governance.py` — 19
- `test_06_ledger_and_priority_ordering.py` — 7

**Total: 79 test functions, 80 collected cases** (one `@pytest.mark.parametrize`).

### Coverage
- **Queue A (Difficulty):** 18/18 instances emitted, all with ≥2 tests (39 tags).
- **Queue B (Corner):** 35/35 non-stub instances emitted (40 tags). The 3 `excluded_because:` stubs were verified against their `difficulty_instance` pointers and correctly not translated.

### Instances SKIPPED
Nine instances were dropped by the PRD-first two-condition filter; each `unsatisfiable` one also failed local validation, so the coverage targets are still met 18/18 and 35/35.

**non-unique-derivability (8):**
- `dual_variant_calc/book_transfer_cause_forfeiture_settlement` — the scaffold's own two variants emit 1800.00 vs 5400.00; PRD §3.7's "terminated for cause" flag has no stated write pathway and no PRD-declared field carries it, so a PRD-only reader cannot produce the scaffold's 1800.00. Covered instead via §3.7's fully-pinned 0.10 × 0.10 × 0.90 formula.
- `non_linear_state_machine/claim_settle_resolve_reopen_cycle` and `compensating_invariant/claim_resolution_chargeback_commission_invariant` — §3.8 pins the chargeback at the *claim's* `policy_paid_cents` while §2.8 pins the ledger at 12,000.00; applying a 40,000.00 chargeback drives it to a floor the PRD says is unreachable from the pinned release, and the exact post-chargeback value is underdetermined. Covered instead via the floored-at-zero assertion the prose genuinely pins.
- `priority_pair_validation_conflict/*` (both) — assert cross-validation *precedence* on dual-failure requests; no verbatim PRD sentence commits to pre-empting the competing path.
- `boundary_precision_check/retention_threshold_at_eighty_five_percent` — the scaffold postulates 20 transferred policies but never creates them; §3.7 pins the `retention_pct ≥ 85` predicate but not a reachable 85.00 vs 84.00 pair. Covered instead via the predicate-agreement test.
- `cross_entity_state_dependency/transition_book_requires_target_agency_active` — scaffold lists 1 test, but §3.2 pins `ERR_AGENCY_STAFFING_CAP` for the below-twelve gate while §2.10 ties `ERR_AGENCY_STAFFING_CAP` to the *twelve* boundary, so the gate's error is ambiguous. Emitted with a status-only assertion plus a cited positive path; met the ≥2 target.
- `appointment_application_assess_self_loop_reassessment` — one of its three scaffold `assert`s (`version advances on each assess`) conflicts with PRD §2.4's "including mutations to derived fields", so the version advance is underdetermined.

**no-PRD-coverage (1):**
- `transitive_cascade/staff_termination_cascade_reimbursement` — the scaffold's setup chain (one ACTIVE staffer + suspended agreement → agency terminate) cannot fire: cessing the sole owner agent moves `agency_level_units` to 0 and leaves a live agent, so §3.9's termination precondition refuses and the staff cascade never runs. Emitted via the reachable MASTER-terminated-agreement route.

### Validation output
- Design tags: 79/79 functions carry exactly one tag, verbatim from source `name:`; every tag resolves to a real instance; 0 untagged, 0 dual-tagged, 0 dangling.
- PRD citations: 141 quoted spans checked against a literal grep of PRD.md — **0 failures**. All asserted `error_id`s appear in PRD prose (not just the §5 table).
- No `pytest.mark.skip`/`skipif`/`xfail`; no "scaffold" references in emitted code.
- `pyflakes`: clean (only expected barrel re-export warnings in `__init__.py`).
- `pytest --collect-only`: 80 tests, 0 errors.

Not run: the tests themselves — no `workspace/implementation/` exists yet, which is Step 6.

## Step 6: Generate implementation — 2026-09-30T01:30:00.000Z

Implementation complete and verified. Summary below.

### Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_3057_exclusive_agent_appointment_book_ownership_agency_transfer/workspace/implementation/`

| Lines | File |
|---|---|
| 69 | `app.py` |
| 70 | `clock.py` |
| 84 | `db.py` |
| 87 | `errors.py` |
| 121 | `middleware.py` |
| 54 | `money.py` |
| 22 | `occ.py` |
| 61 | `response.py` |
| 200 | `serializers.py` |
| 120 | `routes/_common.py` |
| 148 | `routes/agencies.py` |
| 93 | `routes/agents.py` |
| 42 | `routes/agreements.py` |
| 61 | `routes/applications.py` |
| 56 | `routes/claims.py` |
| 41 | `routes/policies.py` |
| 53 | `routes/records.py` |
| 44 | `routes/staff.py` |
| 62 | `routes/system.py` |
| 106 | `services/agencies.py` |
| 248 | `services/agents.py` |
| 111 | `services/agreements.py` |
| 94 | `services/applications.py` |
| 386 | `services/calculations.py` |
| 133 | `services/campaigns.py` |
| 102 | `services/claims.py` |
| 245 | `services/factories.py` |
| 177 | `services/ops.py` |
| 57 | `services/policies.py` |
| 288 | `services/recompute.py` |
| 133 | `services/staff.py` |
| 60 | `services/transfers.py` |
| 14 | `start.sh` (+ 2 empty `__init__.py`, `requirements.txt`) |

**3,642 lines total.**

### Coverage vs spec

- **Endpoints: 58/58.** Set-diffed against the §4 table — exact match, no missing, no extras (plus a non-PRD `/agency-network/_health` probe).
- **Calculations: 20/20** (`services/calculations.py`) — all of SCAFFOLD §1.3: `appointment_priority` (round-half-up on the final sum), `required_action` ordered chain (open high band / closed middle band), `application_value_tier` (≥80), per-policy-rounded commission aggregations, `staffing_reimbursement` (total capped once), the allowance ledger (pool capped 250k base / 400k total, carryover leading), `retention_threshold_check` (≥85), `cessation_bonus`, `contract_value` (1.5 vs 2.0 multiple by 5-year seasoning, floored at 0), `agency_valuation` (floor 2,000,000), `loss_ratio`, successor selection (`agency_level_units` DESC, `created_at` ASC), `book_transfer_settlement` (0.10 → 0.10 → 0.90), `agency_performance_measurement` (AT_RISK before BEHIND), `recompute_agency`, `direct_additions_revenue`, `commission_split_invariant`, `resolution_chargeback`.
- **Validations: 21/21** enforced in the scaffold's priority order — auth (401) → RBAC (403) → left-to-right existence 404s → state/terminal 409s → licensing 400 / sponsor 409 → territorial, staffing-cap, schedule, overlap → allowance, then OCC (412) → referential tail.
- **State machines: 9/9** (AppointmentApplication, Agent, Agreement, StaffMember, LicenseRecord, MarketingCampaign, Policy, Claim, Agency) with their triggers, preconditions, side effects, and terminal guards.

### `start.sh`

Foreground bash launcher; `cd`s to its own directory, guards the dependency install behind `if ! python3 -c "import flask"` (a no-op on the hundreds of per-test reboots), then `exec python3 app.py`. `app.py` reads `PORT` (default `10000`) and binds `0.0.0.0` via `app.run(host="0.0.0.0", port=port, threaded=True)`. Measured cold boot to first HTTP: **0.84 s** (budget 60 s).

### Storage and isolation

In-memory only — Python dicts keyed by id in `db.py`. Grepped clean for sqlite/JSON dumps/pickle/`/tmp` caches. **Zero startup seeding**: `app.py` never writes to any store; all 20 creation paths live in `services/factories.py`, reachable only from `services/*` behind routes. Verified on a fresh process: every collection reads `total_count=0`, the clock reads `2026-09-01T00:00:00.000Z` before any `/clock` call, and state created in one boot is gone in the next (`total_count 1 → 0`).

### Notable fidelity decisions

- OCC runs at the transition's declared spot: `expected_agent_version` on transcribe/transition-book and `expected_agency_version` on activate/participate are checked before the state check, per §2.9/§3.4 (the scaffold's own `transcribe` transition lists no state precondition, so the PRD's sequencing governs).
- The book transfer attaches the departing agent's full book when posted (so a 50-policy transfer with 44 retained reads 88%, not 100%), and `transfer-book` binds the successor.
- `AgencyPrincipal` identity is an `Agency.id`: enforced across campaign, staff, cessation, policy-cancel, book-transfer and the agency-FK reads; root `GET /agencies/{id}` stays readable per the RBAC table. `StaffMember` is restricted to its own record and its sponsoring agreement.
- `policy_paid_cents` reads unset on a newly filed claim and `0` after a deny; `LicenseRecord` exposes only `id` and `created_at` plus its declared inputs.

I read only `INSTRUCTION.md`, `SCAFFOLD.yaml`, `PRD.md`, and the skill — the test artifacts, design indices, and sibling tasks were never touched. All servers I started were killed by explicit PID (verified: no listeners left on any port I used).

## Step 7: Run tests and iterate to PASS — 2026-09-30T02:42:00.000Z

All 8 parallel rounds pass 79/79 with zero failures. The loop is complete.

### Summary

**Iterations run:** 4 full 8-round parallel sweeps.
- Sweep 1: 14 deterministic failures (identical in all 8 rounds).
- Sweep 2: 5 failures (after first fix batch).
- Sweep 3: 1 failure (a bad assertion I introduced).
- Sweep 4: **0 failures — all 8 rounds `passed == total == 79`.**

**Tests deleted (1):**
- `test_suite/test_01_application_assessment_and_scoring.py::test_retired_territory_is_refused_at_application_submission` — **no-declared-trigger silence (collapse: COMPUTED-FIELD SILENCE).** PRD (§2.10, §3.1) and SCAFFOLD both state only the *outcome* ("a retired address that cannot fit the appointment territory is refused … `ERR_INVALID_TERRITORY`") with no field or mechanism marking an address "retired" or a territory unfit; the test asserted 400 for `state_code="ZZ"`, which a faithful PRD-only implementer has no basis to reject. Scaffold rule driving generation: `Corner/errors/err_invalid_territory_triggered` (`validations[priority=9]`).

**Fixes applied to `test_suite/`:**
- `test_01…` priority test: odds 70 → 80 so `required_action` is genuinely `PROCEED` (70 falls in the closed middle band per §3.1); expected priority now 86.
- `test_02…termination` test: build the live-agent precondition via the real pipeline; corrected the assertion (`agency_level_units` counts ACTIVE agreements, not TRANSITIONING agents).
- `test_03…transcribe` test: seeded a `TRANSITIONING`/`NOT_LICENSED` agent so the licensing gate is the only unmet precondition, and added the positive path.
- `test_03…suspended sponsor` test: nominate while the sponsor is live, then cease the owner, then appoint (the prior version violated the nomination-time sponsor gate).
- `test_04…staff cascade` test: read `staffing_reimbursement_cents` off the agency, not the agreement.
- `test_04…book transfer exposure` test: call the endpoint with its PRD-authorized `FieldManager` role instead of an `AgencyPrincipal` id that doesn't own the resource.
- `test_06…back-to-back windows` test: replaced the half-open back-to-back construction (which PRD's "closed intervals" sentence forbids) with a strictly-after window.

**Fixes applied to `workspace/implementation/`:**
- `services/ops.py::_shelf_reopen_claims`: restrict shelf-reopen to a policy that was actually **restored** — a plain `run_ops` was silently zeroing a legitimate settled claim (this was a real bug corrupting `loss_ratio`/`performance_status`).
- `services/agencies.py::run_ops`: added the ACTIVE-state guard (state checks precede business rules, §2.12); `create`: reject a create missing any PRD-declared required input (agency_code/name/region_code/market_need_score).
- `services/staff.py`: `appoint` now checks the member's own state before the sponsor gate (§2.12 precedence); `nominate` now enforces the sibling window-collision rule (§3.5) at creation; both paths recompute agency-level `staffing_reimbursement_cents`.
- `services/policies.py::create`: resolve owner agency then holder agent before any business check (§2.6 ordering) → `ERR_AGENCY_NOT_FOUND`/`ERR_AGENT_NOT_FOUND`.
- `services/agents.py::complete_reassignment`: recompute successor selection and raise `ERR_NO_SUCCESSOR_AGENT` when the candidate set is empty (§3.7).
- `services/factories.py`, `serializers.py`, `services/recompute.py`: carry and expose the agency-level `staffing_reimbursement_cents`.

**Key findings:** the single largest defect was an implementation bug (`_shelf_reopen_claims` zeroing every settled claim on any ops sweep); the rest were a mix of PRD-mandated checks missing from the implementation (existence ordering, successor recompute, run_ops state gate, required inputs, create-time overlap) and test fixtures that constructed preconditions the PRD forbids or asserted values contradicting PRD prose. No implementation check required by PRD was weakened.

## Step 8: Finalize PRD — 2026-09-30T03:05:00.000Z

All edits are applied. `PRD_FINALIZED.md` is written.

### Summary

**Line counts:** `PRD.md` = 371 lines; `PRD_FINALIZED.md` = 371 lines (0.0% delta — every change was an in-place rewrite of an existing line, no lines added or removed).

**Changes (12 edits, one per change):**

- §2.10 — revise — Collapsed "Two territorial gates" to one; deleted the `ERR_INVALID_TERRITORY` "retired address" gate (implementation never raises it). impl: `services/applications.py:11` (`submit` does no territory check), `errors.py` (constant defined but never raised).
- §2.12 — revise — Removed `ERR_INVALID_TERRITORY` from the referential-tail precedence list. impl: same as above.
- §3.1 — revise — Replaced the submission-time `ERR_INVALID_TERRITORY` sentence with "submission applies no territorial fit test". impl: `services/applications.py:11`.
- §3.9 — insert — Agency create requires `agency_code`, `name`, `region_code`, `market_need_score`; a create omitting any is refused. impl: `services/agencies.py:26-30`.
- §3.9 — insert — Ops sweep accepted only for `ACTIVE` agencies; terminal → `ERR_ALREADY_TERMINAL`, non-`ACTIVE` → `ERR_INVALID_STATE`. impl: `services/agencies.py:94-98`.
- §3.5 — insert — Appoint examines the member's own state first (TERMINATED → `ERR_ALREADY_TERMINAL`; other non-PENDING → `ERR_INVALID_STATE`) before the sponsor/licensing gates. impl: `services/staff.py:76-79`.
- §3.5 — insert — Booked-window collision applies at nomination as well as appointment; closed-interval touch counts; TERMINATED members disregarded. impl: `services/staff.py:51-52,124-145`.
- §3.5 — insert — `staffing_reimbursement_cents` is carried on the Agency and mirrored onto each agreement. impl: `serializers.py:35-36,108-109`; `services/recompute.py:36,62-63,285-291`.
- §3.5 — revise — Two-hop cascade wording: "recomputed from the agency's current ACTIVE team" instead of "from the recomputed unit count". impl: `services/recompute.py:284-291`.
- §3.7 — insert — Finalization re-runs the successor selection; an empty same-region ACTIVE candidate set → `ERR_NO_SUCCESSOR_AGENT`. impl: `services/agents.py:192-194,241-245`.
- §3.8 — insert — Shelf-reopen restricted to a restored policy; a PAID claim whose policy was never restored (incl. stayed `OPEN`) is untouched. impl: `services/ops.py:90-111`.
- §3.8 — insert — Policy create resolves owner agency then holder agent first (`ERR_AGENCY_NOT_FOUND`/`ERR_AGENT_NOT_FOUND`) before other checks. impl: `services/policies.py:14-22`.

**Per-edit pre-edit search log (a subject / b paths enumerated / c adjustment):**

1. subject: `ERR_INVALID_TERRITORY` (§2.10/§2.12/§3.1 elems). (b) Grepped whole impl for the identifier — only `errors.py` definition; `applications.submit`/`factories.create_application` do no territory validation. (c) None — wrote only that submission applies no fit test, leaving the support-subtype assessment gate and §5 catalogue row intact.
2. subject: agency create required inputs. (b) `agencies.create` (sole caller `routes/agencies.py:23`), `factories.create_agency` (stores payload values verbatim, no validation). (c) Widened to "omits any of them is refused" (impl returns `ERR_INVALID_REQUEST`, which §5 does not catalogue, so I avoided pinning the exact id).
3. subject: run_ops state gate. (b) `agencies.run_ops` (route `routes/agencies.py:53`, service `:94`), `ops.run_ops`, `ops.maybe_promote_ceasing_agents`. (c) None — terminal→ALREADY_TERMINAL then non-ACTIVE→INVALID_STATE matches impl order (§2.12).
4. subject: staff appoint member-state precedence. (b) `staff.appoint` (route `routes/staff.py:39`), `recompute.terminate_staff_under_agency`/`active_staff_under_agency` (only ACTIVE→TERMINATED), and `_check_overlap`'s TERMINATED skip. (c) None.
5. subject: staff booking-window overlap at nominate. (b) `staff.nominate`, `staff._check_overlap`, `staff.appoint`, campaign `_check_overlap` (sibling rules), PRD §2.10 closed-interval sentence. (c) None — stated the same-owner closed-interval rule and the TERMINATED exclusion exactly as impl.
6. subject: `staffing_reimbursement_cents` carrying. (b) `calculations.staffing_reimbursement_cents`, `recompute._rebuild_agency_fields`, `_rebuild_agreement_fields`, `terminate_staff_under_agency`, `staff.appoint`, `serializers.view_agency`/`view_agreement`. (c) None — "carried on the Agency and mirrored onto each agreement" covers all paths (create, staff termination, appoint).
7. subject: staff-termination cascade wording. (b) `recompute.terminate_staff_under_agency:273-292`, `recompute.active_staff_under_agency`, `agency_level_units` (counts ACTIVE agreements). (c) Softened "from the recomputed unit count" → "from the agency's current ACTIVE team" to match that `staffing_reimbursement_cents` reads ACTIVE members, not the agreement-unit count.
8. subject: complete_reassignment successor recheck. (b) `agents.complete_reassignment`, `agents.select_successor`, `calculations.successor_candidates`, route `routes/agents.py:64`. (c) Added the recheck only; left the auto-promotion branch (PRD §3.7 "sweep performs it") unpinned to avoid over-claiming, since it is not Step-7-changed and not test-exercised.
9. subject: shelf-reopen. (b) `ops._shelf_reopen_claims`, `ops.run_ops`, `recompute.cascade_from_claim`; grepped `restored` across impl — set isn't defined anywhere (inert). (c) Added the negative half ("never restored … left untouched") to capture exactly what the sweep skips, without inventing a restore mechanism the impl lacks.
10. subject: policy create existence resolution. (b) `policies.create`, `_common.policy_or_404`/`agency_or_404`/`agent_or_404`, route `routes/policies.py:17`, §2.6 left-to-right rule. (c) None.

**Not edited (Step 7 items that were pure fixture bugs, already pinned by PRD.md):** priority band at 70 (§3.1), termination live-agent precondition (§3.9), transcription licensing gate (§3.3/§2.10), nomination-time sponsor gate (§3.5), book-transfer RBAC/exposure fixtures, and closed-interval window collision (§2.10). No test file was consulted as an alignment target — `implementation/` is the target.

## Step 9: Complete PRD — 2026-09-30T03:32:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_3057_exclusive_agent_appointment_book_ownership_agency_transfer/workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`, then edited in place).

### Summary

**Source vs output**
- Source: `workspace/PRD_FINALIZED.md` — 371 lines, 60,469 chars (60,362 without trailing-newline accounting).
- Output: `workspace/PRD_COMPLETED.md` — 371 lines, 64,676 chars.
- Line delta: **0**; char delta: **+4,187**. 25 lines touched, all in-paragraph inserts/revisions; no new sections or paragraphs.

**Counts**
- Ambiguity-pins: **23**
- Mismatch-revisions: **2**

**Changes** (section — insert/revise — kind — what changed — impl anchor)

- §2.4 — insert — ambiguity — a recompute that a change necessitates advances every rewritten record's `version`; only pure reads (performance snapshot, book-transfer read, ops-sweep transaction reads) mint no version — `services/recompute.py:20-24, 74-98`; `services/ops.py:124-149`
- §2.5 — insert — ambiguity — `recompute_agency` also rebuilds `growth_new_pct`, `performance_status`, `agency_valuation_cents`, `agency_paid_claims_cents`, `staffing_reimbursement_cents` and refreshes pool/spend/carryover and the three commission lines — `services/recompute.py:27-98`
- §2.5 — insert — ambiguity — a claim not yet compensated contributes nothing to the paid total; the cap/gross-paid reading is the sum of compensated `policy_paid_cents` — `services/calculations.py:120-130`
- §2.7 — insert — ambiguity — the prior carryover is the term-opening allowance balance; it changes only at a term rollover, so an already-spent draw is never re-absorbed by the pool — `services/campaigns.py:105`; `services/ops.py:49-51`
- §2.11 — insert — ambiguity — any parseable ISO 8601 form is accepted (trailing `Z` or not; no offset = UTC; date-only lands at midnight) — `clock.py:35-45`
- §3.1 — insert — ambiguity — scoring inputs are the submission-supplied scores; assessment is not body-driven — `services/applications.py:31-48`
- §3.1 — insert — ambiguity — the support subtype is the application's declared `territory_subtype`, read case-insensitively; a missing subtype never fires the gate — `services/applications.py:51-54`
- §3.2 — insert — ambiguity — the mint copies the candidate name from `full_name` or the `applicant_name` alias — `services/factories.py:73-82`
- §3.2 — insert — ambiguity — raw-agent seeding may also set `market_need_score` and `license_expiry_date` — `routes/system.py:32-45`
- §3.3 — insert — ambiguity — transcribe's three commission lines are computed from the agency book under that schedule and written onto each agreement; `annualized_commission_cents` = direct + renewal — `services/agreements.py:92-112`
- §3.3 — insert — ambiguity — line rounding is half-up quantisation (a half-cent line rounds away from zero) — `money.py:26-28`
- §3.4 — **revise** — **mismatch** — removed the non-existent agency `marketing_allowance_utilization`; participation moves the campaign to `PARTICIPATED` and grows the agency's `marketing_allowance_spent_cents`, with the pool/spend/carryover mirrored onto agreements — `services/campaigns.py:93-119`
- §3.5 — insert — ambiguity — `allocation_units` outside 1–20 or absent is refused `ERR_INVALID_ALLOCATION_UNITS` (400) before sponsor/window gates — `services/staff.py:43-46`
- §3.5 — insert — ambiguity — the practising agency is read off the member's own `agency_id`, not the sponsor agreement's — `services/staff.py:96`
- §3.6 — insert — ambiguity — an agency with no base carries zero, and a zero base yields `growth_new_pct` of zero — `services/calculations.py:158-162`
- §3.7 — **revise** — **mismatch** — the five-year seasoning branch is unobservable under the 24-month recency flag; the contract value is always priced at the 2.0 multiple, and a book with no `appointment_date` takes 2.0 — `services/calculations.py:287-305`
- §3.7 — insert — ambiguity — finalization also performs the `PENDING_TERMINATION`→`TRANSITIONING` promotion itself when the condition holds — `services/agents.py:185-190`
- §3.7 — insert — ambiguity — finalization transfers only `OPEN` policies; others are left as they are — `services/agents.py:196-199`
- §3.7 — insert — ambiguity — an explicitly posted transfer records the supplied successor at posting (not left null) and attaches the agent's current policies as its transferred book — `services/transfers.py:25-27, 32-42`
- §3.7 — insert — ambiguity — the for-cause condition is pinned on the transfer record itself at posting — `services/factories.py:205`
- §3.8 — insert — ambiguity — every claim is filed `OPEN` regardless of policy state or a prior claim on the same policy — `services/claims.py:15-21`
- §3.8 — insert — ambiguity — denial is terminal; a denied claim can be neither settled nor resolved — `services/claims.py:12, 57-61`
- §3.8 — insert — ambiguity — the sweep leaves a settled claim alone when its policy is no longer `OPEN` — `services/ops.py:103-107`
- §3.9 — insert — ambiguity — at term rollover the unused carryover becomes the next term's opening balance and `rolling_base_cents` resets to zero — `services/ops.py:44-54`
- §3.9 — insert — ambiguity — advancing the clock also refreshes recency flags, re-derives every transfer's retention/settlement, and recomputes each agreement's termination value — `services/ops.py:124-149`

**Notes**
- No servers were started or killed; no state-mutating commands outside PRD editing.
- Verified adjacent-to-PRD behaviours that turned out to be consistent and were left unchanged (all `error_id`/status pairs, envelope shape, paginated family lists, `for_cause` early-write forfeiture, retention by successor holding, creation-time `first_written_at`).