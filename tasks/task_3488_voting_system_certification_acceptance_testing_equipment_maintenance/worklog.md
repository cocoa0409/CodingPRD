# Worklog — task_3488_voting_system_certification_acceptance_testing_equipment_maintenance

## Step 1: Create task directory — 2026-10-02T15:56:00.000Z

Task directory pre-allocated by command args: `tasks/task_3488_voting_system_certification_acceptance_testing_equipment_maintenance` with `workspace/` inside. Verified present; no new index computed, no other task_* directory created. Difficulty directive: "Generate task much harder than expert level!" (applies to prd-bench-scaffold-generator).

## Step 2: Generate scaffold — 2026-10-02T17:37:00.000Z

All three artifacts are generated, parse cleanly, and pass `scaffold_lint.py` with zero violations. Final lint verdict (verbatim):

```
Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     15
  §1.8 instances scanned:     19
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1120

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_3488_voting_system_certification_acceptance_testing_equipment_maintenance/` — `SCAFFOLD.yaml` (2440 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1135 lines), `SCAFFOLD_CORNER_DESIGN.yaml` (2428 lines).

**Counts:**
- Entities: **15** (VotingSystem, TestLaboratory, CertificationCampaign, Certificate, Jurisdiction, ElectionOfficial, Procurement, AcceptanceTest, ElectionDefinition, LogicAccuracyTest, EquipmentUnit, MaintenanceWorkOrder, CustodyTransfer, SoftwareModification, PostElectionAudit)
- State machines: **12** (incl. cyclic campaign resubmission loop, cyclic L&A challenge/retest loop, cyclic Certificate ACTIVE↔SUSPENDED, parallel operational×custody dimensions on EquipmentUnit, branching procurement/audit/modification machines)
- Calculations: **8** (dual-variant conformity screen/final with aging, dual-variant fleet readiness optimistic/conservative, per-test-type acceptance deficiency index, per-precinct-ceil-then-aggregate-tier print cost, pre-cascade-pinned recertification lead time, exact-integer L&A discrepancy gate, budget ledger invariant, custody conservation invariant)
- Validation rows: **20 priority levels**, ordered auth → role → path-existence → schema → body-FK-existence → ownership → SoD → state/OCC → safety → constraint → temporal → referential → fiscal
- Endpoints: **57** (incl. `/_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default, OCC-guarded layout PUT and modification create, computed reads for readiness and print-estimate, and a public transparency documentation endpoint)
- Error catalog: **56** codes (every one wired to a validation/transition and exercised by ≥1 test instance)
- Roles: **7** (segregation-of-duties model; LabAgent and ElectionOfficial are entity-backed; L&A conductor cannot certify/challenge own test)
- Concurrency rules: **2** OCC rules, both satisfying the §1.2.1 hard constraints
- §1.8 difficulty instances: **19 non-stub, 0 stub** (2 per rule; combinatorial_formula has 3 covering modes a/b/c; cascades from two different triggers at depth 3 and depth 2)
- §1.9 corner instances: **60 non-stub + 16 stub** (76 total) across all nine taxonomy sections; every catalog error has at least one trigger

**Difficulty design highlights (per the "much harder than expert" directive):** pre-computed literal asserts throughout (e.g., conformity 7725 vs 7430 bp on identical counters, 50bp inclusive boundary where both sides display identical floored bp, the non-monotonic 100-ream 420000c vs 102-ream 397800c tier crossing, 135-day lead time evaluated pre-cascade), a depth-3 recertification cascade (modification → certificate → election definition → L&A test), a depth-2 audit-escalation cascade quarantining fleets, two OCC rules, two compensating invariants (budget ledger, custodial identity), and lazy certificate expiry pinned to reads so `ERR_CERTIFICATE_EXPIRED` stays reachable.

**Process notes:** built incrementally with a YAML re-parse after every append; fixed flow-sequence quoting for `?`-optional inputs and bracketed `grounds` tokens; corrected two design-time defects caught by self-replay (an SoD-vs-state priority shadow in a terminal-lockdown trigger, and a backward clock jump in the calendar-gates corner, restructured to forward-only); added two missing catalog errors (`ERR_UNIT_UNSEALED`, `ERR_BATTERY_CYCLE_LIMIT`) found by the catalog-vs-reference audit; reordered ownership vs body-FK-existence priorities to remove an ambiguity. No sibling task directories were read.

**Orchestrator verification:** all three files exist, parse as valid YAML, carry correct top-level keys (scaffold_difficulty_design / scaffold_corner_design), api_prefix `/evote`, and 175 voting-domain keyword hits — no foreign-domain contamination.

## Step 3: Copy shared files — 2026-10-02T17:40:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T17:55:00.000Z

All checks pass. The duplicated lines are exactly the two verbatim JSON envelope blocks in §2.2 — required by the fixed contract.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3488_voting_system_certification_acceptance_testing_equipment_maintenance/workspace/PRD.md` — **376 lines**, no truncation, no duplicated prose blocks (verified by full end-to-end re-read and a duplicate-line scan).

**Section list:**
- §1 Introduction (2 paragraphs — business context + design commitments)
- §2 Global Specifications: 2.1 RBAC, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Resource Identity/Timestamps/Versioning, 2.6 Optimistic Concurrency Control, 2.7 The Validation Pipeline, 2.8 The Jurisdiction Budget Ledger, 2.9 Chain of Custody and Tamper Evidence, 2.10 Numeric Conventions
- §3 Business Logic & Workflows: 3.1 Ecosystem Onboarding, 3.2 Certification Campaigns, 3.3 Certificates, 3.4 Procurement & Acceptance Testing, 3.5 Election Definition/Layout/Paper, 3.6 Logic & Accuracy Testing, 3.7 Equipment Fleet & Custody, 3.8 Maintenance Work Orders, 3.9 Software Modifications, 3.10 Post-Election Audits & Public Transparency
- §4 Endpoint Definitions (57 rows, 4 columns), §5 Error Code Catalogue (56 rows, 2 columns)

**Scaffold coverage confirmed:**
- All 15 entities in prose; AcceptanceTest and CustodyTransfer explicitly called out as carrying only `id`/`created_at` (no `updated_at`/`version`)
- All 12 state machines with every transition's preconditions, side effects, cascades, and terminal states
- All 8 calculations as precise prose (dual conformity variants with all 10 constants, fleet readiness OPTIMISTIC/CONSERVATIVE, acceptance deficiency weights, pinned print-cost order, pre-cascade lead-time evaluation 30/60/45, L&A exact-integer 50bp boundary, budget ledger invariant, custody conservation)
- All 20 validation priorities stated in explicit first-failure-wins order (§2.7)
- 57 endpoints (table row count verified), 56 error codes (all appear in §2/§3 prose as well as the table), 7 roles with per-role `identity:` translation (LabAgent/ElectionOfficial entity-backed, five opaque)
- Both OCC rules (layout write → `expected_election_definition_version`; modification create → `expected_voting_system_version`, both `ERR_STALE_VERSION` 412)
- `/_clock/set_current_utc` presented as the unprefixed platform endpoint with the `2026-09-01T00:00:00Z` boot default and lazy certificate-expiry sweep

**Hard contracts:** Contract 1 (field names: 129 required, 0 missing) PASS; Contract 2 (rule coverage — all categories walked) PASS; Contract 3 (§3 path purity: 689 backtick tokens, 0 path/method violations) PASS.

**Orchestrator verification:** PRD.md exists at 376 lines. Orchestrator independently measured design-index queues from the YAML: queue A (§1.8 difficulty) = 19 non-stub instances; queue B (§1.9 corner) = 60 non-stub instances; 79 total — these corrected queue sizes are passed into Step 5.

## Step 5a: Generate test helpers (Stage 1 of split Step 5) — 2026-10-02T18:20:00.000Z

Stage 1 complete. All ten files are written, compile-clean, and the package imports with the full helper surface verified against the design indices' literals.

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_3488_voting_system_certification_acceptance_testing_equipment_maintenance/`)

| File | Lines | Contents |
|---|---|---|
| `test_helpers/types.py` | 413 | `UserRole` + 20 domain enums + 15 entity TypedDicts; `AcceptanceTest`/`CustodyTransfer` carry only `id`+`created_at` (verified: no `version`/`updated_at` annotations) |
| `test_helpers/constants.py` | 117 | PRD-pinned literals only, each with its citing PRD sentence (8000 bp gate, both conformity weight sets, 730-day TTL, acceptance weights/clamp/20-max, print tiers, paper envelope, 30/14-day windows, 500-cycle battery cap, storage band, 30/60/45 lead-time parts, 50 bp L&A bound, lab capacity 3∈[1,10], pagination 10/1/100, boot clock) |
| `test_helpers/api_errors.py` | 140 | `ApiErrorId` enum — all 56 PRD §5 errors — + `HTTP_STATUS_CODES` registered via `set_error_http_status_map` |
| `test_helpers/api_client.py` | 309 | `ApiClient(GenericApiClient)`, 57 methods, one per endpoint |
| `test_helpers/factories.py` | 349 | One factory per entity, input fields only; uuid-suffixed unique defaults; optional fields omitted when None |
| `test_helpers/assertions.py` | 462 | 15 `assert_*` entity checkers + ledger invariant + 6 `compute_*` oracles re-deriving the PRD formulas |
| `test_helpers/test_users.py` | 72 | Role headers (mapping below) |
| `test_helpers/fixtures.py` | 726 | Tier-0/1 primitives + composites (justified >400: the skill expects fixtures to be the large file) |
| `test_helpers/__init__.py` | 47 | Barrel export (framework generics + all PRD-specific) |
| `test_suite/conftest.py` | 54 | `api` session fixture + one fixture per role entry in `TEST_USERS` |

## Role→identity mapping (test_users.py)
- **Entity-backed**: `make_lab_agent_headers(lab_id)` (X-User-ID = TestLaboratory.id) and `make_election_official_headers(official_id)` (X-User-ID = ElectionOfficial.id). Shared `TEST_USERS` fallbacks for these two ("test-lab-1", "test-official-1") are marked non-ownership-only. Fixtures thread real entity ids everywhere; distinct owners get distinct identities because composites create fresh lab/official records per call.
- **Opaque** (shared constants canonical): PlatformAdmin, CertificationAuthority, VendorRep, Auditor, PublicRequester.

## Clock endpoint
`api_client.set_current_utc()` calls `POST /_clock/set_current_utc` at the **server root, unprefixed** — all other 56 methods are under `/evote` (PRD §2.4/§4: the clock lives outside the mount). `fixtures.set_clock()` wraps it with PlatformAdmin headers.

## OCC fields surfaced by factories
`put_layout_payload(expected_election_definition_version=...)` (required positional) and `create_software_modification_payload(voting_system_id, expected_voting_system_version=...)`. Fixture wrappers `store_layout`/`propose_modification` auto-read the fresh parent version unless the caller passes one explicitly (stale-path tests pass it).

## Verification
- `python3 -m py_compile` — all 10 files OK
- `import test_helpers` — OK; surface smoke-tested: 7 TEST_USERS, entity-backed builders set correct header pairs, OCC fields present in payloads, optional-None omission works
- Compute oracles reproduce every design-index literal exactly: screen 7725 / final 7430 bp; deficiency indices 29/16/100 with FAIL/PASS/FAIL; print estimates (2,6,4200,25200), (100→420000), (102→397800); lead times 135/90/30; L&A 100-of-20000 PASS, 101 FAIL

## PRD-silent decisions (for Step 7 audit)
1. Unique-value defaults use `uuid4().hex[:8]` suffixes (`SN-`, `LAB-`, `B-`, `SEAL-` prefixes) — PRD pins only uniqueness scope, not format.
2. Test-data defaults (vendor/model "DS450", DUAL lab, VVSG_2_0, "CA", 100M-cent budget, qty 10 @ 2.5M cents, election 2026-11-03 with 3 precincts, paper 90/100/UNCOATED, WO window 09-05→09-06, storage 20C/40%, component AUDIT_LOG_SERVICE, RISK_LIMITING, tallies {PRES:12000,SEN:8000}) — chosen to satisfy PRD windows/ranges against the 2026-09-01 boot clock; none are asserted as PRD rules.
3. Optional fields are **omitted** (not sent as null) when None — factories can't emit explicit JSON null for `state_code`/`max_concurrent_campaigns`/calibration fields; a test needing explicit null builds its payload inline.
4. `store_layout`/`propose_modification` auto-read current version when the OCC field isn't passed (client convenience; PRD pins only the 412 outcome).
5. Read calls inside fixtures use Auditor headers (PRD §2.1: all seven roles may read everything).
6. `compute_*` functions are test-side oracles, not extra PRD claims; composites return plain dicts of entities.
7. conftest.py generated now (skill lists it in Stage 2 §2.0, orchestrator authorized Stage 1); Stage 2 may extend it.

No `test_suite/test_*.py` files were generated — that's Stage 2's queue (19 difficulty + 60 corner instances).

## Step 5b: Generate test suite (Stage 2 of split Step 5) — 2026-10-02T18:55:00.000Z

All verification gates pass. Stage 2 is complete.

## Summary

**Files written (10), 79 tests total — 19 difficulty + 60 corner, zero skips:**

| File | Tests | Content |
|---|---|---|
| `test_01_difficulty_calculations.py` | 7 | dual_variant_calc ×2, combinatorial_formula ×3, boundary_precision_check ×2 |
| `test_02_difficulty_workflows.py` | 12 | non_linear_state_machine ×2, transitive_cascade ×2, priority_pair ×2, cross_entity_state_dependency ×2, resource_temporal_overlap ×2, compensating_invariant ×2 |
| `test_03_corner_entities.py` | 10 | Corner/entities |
| `test_04_corner_state_machines.py` | 9 | Corner/state_machines |
| `test_05_corner_calculations.py` | 3 | Corner/calculations |
| `test_06_corner_validations_a.py` | 13 | Corner/validations (first half) |
| `test_07_corner_validations_b.py` | 13 | Corner/validations (second half) |
| `test_08_corner_endpoints.py` | 3 | Corner/endpoints |
| `test_09_corner_rbac.py` | 5 | Corner/rbac |
| `test_10_corner_cross_cutting.py` | 4 | Corner/cross_cutting_layers ×3 + consistency_model ×1 |

All under `/home/ubuntu/github/CodingPRD/tasks/task_3488_voting_system_certification_acceptance_testing_equipment_maintenance/test_suite/`. No helper files were edited; no new helpers were needed — every recipe mapped onto the frozen Stage 1 API (fixtures + factories + `api` fixture for error probes).

**Skipped instances:** none. All 79 non-stub instances passed the PRD-first filter.

**One partial-assertion drop (not a skip):** `Corner/validations/audit_already_active_rejected` asserts the PRD-pinned primary claim (second non-terminal audit → 409 `ERR_AUDIT_ALREADY_ACTIVE`) but omits the design's secondary sub-assertion (audit create on a DRAFT definition → 409 `ERR_INVALID_STATE`). PRD §3.10 states "The definition must be `CANVASSING`" without naming an error_id, and §2.7 priority 8's state-legality rule applies to `*/transitions` endpoints only — audit creation is not one — so the DRAFT-case failure mode is not uniquely derivable by two PRD-only readers (400 vs 409 vs 422 all defensible).

**Verification verdicts:**
- `py_compile`: OK on all 10 test files + conftest.
- `pytest --collect-only`: **79 tests collected, 0 collection errors** (PYTHONPATH=. against installed framework).
- AST tag audit (real yaml parse of both indices): 79 tests, each with exactly one *trailing* `Design:` line; **missing NONE / extra NONE / stub violations NONE**; all 16 `excluded_because:` corner stubs correctly untranslated.
- Citation pass: 130 PRD citation chunks across all docstrings, all verbatim-verified against `PRD.md` (whitespace-normalized 10-word sliding-window grep) after fixing 4 initially non-verbatim chunks (3 paraphrases of §4 table rows re-quoted in literal pipe format, 1 paraphrased §3.2 enum domain re-quoted verbatim).

**Conventions honored:** unprefixed clock via `set_clock`; `validate_success(resp, 201)` on all raw creates; OCC stale paths pass explicit outdated versions; entity-backed headers (`make_lab_agent_headers(lab_id)` / `make_election_official_headers(off_id)`) on every ownership-gated call; no `version`/`updated_at` presence assertions on AcceptanceTest/CustodyTransfer (only the helpers' absence checks); design literals (7725/7430 bp, 25200/420000/397800c, 135/90/30-day leads, 50bp boundary) asserted as-is, cross-checked against the frozen `compute_*` re-derivations. Version arithmetic uses captured-base-plus-delta (e.g. `version_at_create + 6`) everywhere except the design-pinned `version == 1` at creation; `expires_at` asserted by date prefix (`2028-08-31`) to stay serializer-agnostic. No server was booted; collect-only was the deepest check run.

**Orchestrator re-verification (independent of subagent claim):** `pytest --collect-only` → 79 collected; own AST parse of all 10 test files diffed against own YAML parse of both indices (stub = `stub:` or `excluded_because:`; section = `section:`/`rule_id:` field) → **79 tests / 79 unique tags / 79 expected non-stub instances; MISSING [], EXTRA []**. Subagent's report confirmed against source.

## Step 6: Generate implementation — 2026-10-02T19:40:00.000Z

Implementation complete and verified. Final report:

## Files (all under `workspace/implementation/`, 2838 lines total)

| File | Lines | py_compile |
|---|---|---|
| start.sh (exec launcher, guarded pip install) | 10 | n/a (bash -n OK, boot-tested) |
| requirements.txt | 1 | n/a |
| app.py (bootstrap, blueprints, error handlers) | 77 | OK |
| store.py (in-memory dicts + logical clock, empty at boot) | 37 | OK |
| util.py, constants.py, errors.py, envelope.py, validation.py, auth.py | 84/82/39/137/127/80 | all OK |
| domains/: clock, systems, labs, campaigns, certificates, jurisdictions, officials, procurements, definitions, la_tests, units, work_orders, modifications, audits, public_read | 28–289 each | all OK |

All 57 endpoints registered (56 under `/evote` + unprefixed `POST /_clock/set_current_utc`; verified via `url_map` dump). In-memory only, zero seeding, fresh state per boot (verified by rebooting between smoke rounds).

## Smoke test (self-run, dynamic ports, exact PID kill)
Round 1 (44 checks, all PASS): clock set (unprefixed, 200), 401/403/404 paths, envelope shape, system→lab→campaign create, campaign IN_TEST (LabAgent ownership 403 on wrong lab), CERTIFIED + auto-FIELDED + certificate mint, P4-beats-P5 ordering check, both OCC guards (412 stale / 201 match), budget ledger encumber→spend, layout PUT (412, 422 paper, 200), print-estimate math (rpp=3, total=37800), readiness read, unit deploy + record-usage, L&A SoD (403 self-certify / 200 other official), public documentation read, lazy certificate expiry at 730d.
Round 2 (all PASS): deficiency file/resubmit loop with exact conformity values (7975/7850, aging term verified), resubmit-mismatch 422, cert expires_at = issued+730d exact string, custody seal break→UNSEALED→deploy blocked 422→RESEAL work order→SECURED, work-order overlap 409 + adjacency allowed, unit IN_MAINTENANCE capture/restore, full recertification cascade (lead 135 = 30+60+45 evaluated pre-cascade, cert suspended, ED reverted with CERTIFICATE_SUSPENDED, CERTIFIED L&A untouched), lead-time gate 422, recert-campaign gate 422, EFFECTIVE compensation (cert reinstated, baseline rewritten), freeze-window/not-held gates, audit open-409/escalate-quarantine/publish/close flow.

## Constants cross-check
Every PRD §2/§3 numeric defined exactly once in constants.py and matched one-by-one: pagination 10/1/100/0; CERT_TTL 730; conformity 1200/300/75/250 + 1500/250/50/400/10-wk/8000; lab 3/[1,10]; acceptance (25,8,2)/(30,10,3)/(40,12,4), cap 100, max 20; ream 500, tiers 100→4200/500→3900/>500→3500; election 30d/14d; LA 50bp; battery 500; storage 10–35°C/20–70%; paper 80–120/60–250; mod lead 30/60/45; boot clock 2026-09-01T00:00:00Z (store.py, single definition).

## Guard-wiring audit
All 56 catalog error ids are raised in domain code (grep verified, zero missing). Every helper is invoked: sweep_certificate (cert list/get + public doc), mint_certificate, recompute_conformity, abort_open_work_orders (retire/quarantine/escalation), release_encumbrance, revoke_cascade, compute_lead_time_days, recertification_cascade, effective_compensation, escalation_cascade. Guard-read fields (cert_hold, pre_maintenance_status, battery_cycles, custody_status, resubmission_count, last_submitted_at, report_public, certificate_version_pinned) all have writers. Certificate `reason` payload is accepted (declared input) but intentionally not persisted — the Certificate entity has no such field.

## Interpretations chosen (Step 7 pre-flag candidates)
1. **Campaign-create guard order**: PRD §3.2's narrative lists lab checks before single-active-campaign, but §2.7's fixed pipeline numbers put aggregates (P14) before referential state (P19). I followed the numbers: ERR_CAMPAIGN_ALREADY_ACTIVE fires before ERR_LAB_SUSPENDED/SCOPE/SYSTEM_RETIRED. Same choice on procurement ACCEPTED (test-completeness P17 before cert-active P19) and campaign IN_TEST (capacity P14 before lab-suspended P19).
2. **Acting ElectionOfficial must be ACTIVE**: scaffold entity text says "INACTIVE officials are refused (ERR_OFFICIAL_INACTIVE)"; PRD §3.1 names only custody-receiving/initial-custodian cases. I enforce it on all ElectionOfficial write endpoints, checked at the ownership stage after jurisdiction match.
3. **Quarantine gate promoted above state legality** on unit transitions: PRD §3.7 prose ("deploy/store against QUARANTINED → ERR_UNIT_QUARANTINED") wins over strict P8<P10 numbering; CA release QUARANTINED→IN_STORAGE still passes.
4. **System-only to_states** (IN_MAINTENANCE, EXPIRED, SECURED/UNSEALED): pass P4 (real states), no human actor so they skip the P2 actor check, and fail at P8 with ERR_INVALID_STATE (matches the scaffold's explicit IN_MAINTENANCE→ERR_INVALID_STATE rule).
5. **reason requiredness**: required non-empty for procurement REJECTED and ED revert-to-DRAFT (explicit PRD error), and for budget-adjustments (required field + P4 "empty reason where required"); optional for procurement/ED CANCELLED (scaffold lists no reason precondition) and certificate transitions (accepted, not persisted).
6. **current_utc and all timestamps** render with three fractional digits per §2.5 (`2026-09-01T00:00:00.000Z`).
7. **Public documentation read** applies the lazy certificate expiry sweep to the named system's certificates before counting (treats the doc read as a certificate read path).
8. **Reopen missing scanned_tallies** → ERR_INVALID_TALLIES (422) per the transition precondition, checked at P17 position (after SoD/state), not P4.
9. **Certify-time open-counters-zero precondition** is unreachable by construction (counters are always 0 in IN_TEST) — wired anyway, sharing ERR_CONFORMITY_BELOW_THRESHOLD.
10. **Pagination bounds** (limit outside [1,100], offset < 0, non-integer) → 400 ERR_INVALID_REQUEST rather than clamping.

## Isolation confirmation
Never opened SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, or test_helpers/; never ran the test suite. Only SKILL.md, INSTRUCTION.md, SCAFFOLD.yaml, and PRD.md were read. Smoke servers were started on OS-assigned free ports and killed by exact PID; all temp files removed.

**Orchestrator verification:** all 21 source files + start.sh exist; every .py py_compiles; start.sh passes bash -n; 2827 total lines; per-domain module layout as pre-constrained.

## Step 7: Test-fix loop — 2026-10-02T19:56:00.000Z

Two iterations of the 8-round parallel sweep (`prd-bench-local-run --isolation per-test-server`, 79 tests per round).

**Iteration 1:** 76/79 in all 8 rounds (deterministic, not flaky). Union of failures: 3 tests.
- `test_voting_system_create_returns_defaults` and `test_event_records_carry_no_version_field` — "id must be a valid UUID". PRD §2.5: "id is a server-minted UUID with no type prefix" — the canonical RFC 4122 textual form (verified via the framework's frozen `is_valid_uuid`). Impl emitted `uuid4().hex` (undashed). IMPL FIX: `util.py new_id()` → `str(uuid.uuid4())`.
- `test_invalid_state_beats_battery_safety` — expected ERR_INVALID_STATE, got ERR_UNIT_QUARANTINED (pre-flag #3). STEP 1b unique-derivability collapse (ERROR PRECEDENCE SILENCE): §2.7's fixed pipeline order (P8 before P10) supports ERR_INVALID_STATE, while §2.7 priority 10's own clause and §3.7 ("Quarantine overrides everything. ... While a unit is QUARANTINED, ... deploy/store transitions ... are all rejected with ERR_UNIT_QUARANTINED") support ERR_UNIT_QUARANTINED for this exact request; PRD does not resolve the precedence between the two earlier checks, and the impl's §3.7 reading is PRD-faithful. TEST FIX (sanctioned relaxation, not deletion): primary assertion relaxed to `validate_error_is_one_of([ERR_INVALID_STATE, ERR_UNIT_QUARANTINED])`; the design instance's PRD-pinned core — battery ceiling (P12) masked by an earlier check — kept via the `!= ERR_BATTERY_CYCLE_LIMIT` assertion; §3.7 quote added to the docstring.

**Iteration 2:** 79/79 passed in all 8 rounds. CLEAN SWEEP. results.1.json … results.8.json retained in workspace/implementation/ per the output contract.

No test deletions. No implementation check was weakened; no capability was added beyond PRD.

**Orchestrator verification:** all 8 `results.{i}.json` parsed independently — each `passed=79 total=79 failed=0 errors=0`. Oldest results file (19:56:10Z) is newer than the newest source file across implementation/+test_suite/+test_helpers (19:53:21Z) — the clean sweep is post-edit and valid.

## Step 8: Finalize PRD — 2026-10-02T20:10:00.000Z

The task is complete. Both edits applied cleanly, verified via diff.

## Summary

**Line counts / %-delta:** PRD.md = 376 lines, PRD_FINALIZED.md = 376 lines — 0% line delta; exactly 2 lines revised in place (no insertions, no deletions, no new sections).

### Changes
- **§2.5 (Resource Identity)** — revise — appended "rendered in the canonical hyphenated 8-4-4-4-12 form" to the `id` sentence — `implementation/util.py:13-20` (`new_id()` returns `str(uuid.uuid4())`; sole minter via `stamp_new` at `util.py:77`, used by all 15 creation paths across `domains/*.py`).
- **§2.7 priority 10 (Custody and work-order state gates)** — revise — appended a scoped exception sentence: on the equipment-unit transition endpoint, after earlier pipeline stages pass, a request to move a `QUARANTINED` unit to `IN_SERVICE`/`IN_STORAGE` is rejected with `ERR_UNIT_QUARANTINED` ahead of priority-8 state legality, except the CertificationAuthority release `QUARANTINED`→`IN_STORAGE` which remains permitted — `implementation/domains/units.py:153-159` (gate before P8 at 162-163).

### Per-edit pre-edit search log
1. **UUID edit** — (a) subject: textual representation of the server-minted resource `id`. (b) Enumerated: `util.py:13-20` (sole minter), `util.py:70-83` `stamp_new` + all 15 call sites (13 versioned + 2 immutable: custody transfers `units.py:246`, acceptance tests `procurements.py:196`), `envelope.py:34-43` `serialize` (pass-through), `envelope.py:24-25` `_request_id` (`req_`-prefixed alphanum — a different field, pinned separately in §2.2, excluded from scope), path-param dict lookups in every domain (opaque keys, no inbound format validation), framework validator `prd_bench_local_runner.testing.assertions._UUID_RE` (`^[0-9a-f]{8}-...{12}$`, hyphenated-only; verified undashed fails). (c) Scoped the clause to the resource `id` sentence only; no case pin and no claim about `api_request_id` — case is not behaviorally observable (the regex is case-insensitive and ids round-trip), so it stays under-determined.
2. **Quarantine-precedence edit** — (a) subject: which check reports a deploy/store attempt against a QUARANTINED unit. (b) Enumerated every unit-transition path on a QUARANTINED unit in `units.py:129-197`: official deploy (→`ERR_UNIT_QUARANTINED`, the relaxed test's exact case), official `to_state=IN_STORAGE` (→`ERR_UNIT_QUARANTINED`), CA release (→ succeeds, P8 legal via `UNIT_FROM["IN_STORAGE"]∋QUARANTINED`), CA deploy (→`ERR_UNAUTHORIZED` at P2 via `UNIT_ACTORS`/`require_transition_actor` in `auth.py:52-63`), re-quarantine / retire / `IN_MAINTENANCE` attempts (fall through the gate → `ERR_INVALID_STATE` at P8); plus custody-transfer creation (`units.py:235-236`), work-order creation (`work_orders.py:61-62`), and the audit-escalation cascade (`audits.py:93`, no request path). (c) Added three guards in the wording: "once the request has survived the earlier pipeline stages (authentication through ownership)" (so P1–P6 failures like a CA deploy or wrong-jurisdiction official are not mis-described), scoping to `to_state` `IN_SERVICE`/`IN_STORAGE` (so retire/re-quarantine/IN_MAINTENANCE still report `ERR_INVALID_STATE`), and the explicit CA-release carve-out (so `QUARANTINED`→`IN_STORAGE` by CertificationAuthority remains permitted and succeeds).

### Per-<step_7_diff> item adjudication
- **impl fix `util.py::new_id()` → EDIT.** §2.5's "server-minted UUID with no type prefix" does not uniquely determine the hyphenated form for a PRD-only reader (`uuid4().hex` undashed 32-hex is also "a UUID" and was the impl's original choice). Since the impl moved toward the canonical form the frozen `is_valid_uuid` encodes, a one-clause representation pin is in scope and was applied.
- **test relaxation `test_invalid_state_beats_battery_safety` → EDIT.** The PRD genuinely left the precedence unresolved (§2.7's fixed P8-before-P10 order vs §2.7-P10's own clause + §3.7's "deploy/store ... rejected with `ERR_UNIT_QUARANTINED`"). The impl resolves it for `ERR_UNIT_QUARANTINED` on deploy/store paths (gate evaluated before state legality, `units.py:153-159`); §2.7 P10 was amended to pin exactly that, consistent with §3.7's existing prose (left verbatim — it already matches the impl) and with the preserved test core (P12 battery ceiling remains masked).

No other edits: zero test deletions and zero test_helpers fixes were listed, and the sweep was clean at 79/79.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly the 2 reported in-place revisions and nothing else; both files 376 lines.

## Step 9: Complete PRD — 2026-10-02T20:40:00.000Z

All edits verified. The task is complete. Final report:

## Step 9 output: PRD_COMPLETED.md produced

**File**: `workspace/PRD_COMPLETED.md` — 376 lines (unchanged count), 67,121 chars vs 64,738 (+2,383); 19 paragraphs patched in place, no sections added/removed.

**Counts**: 19 ambiguity-pins, 1 mismatch-revision, 4 IMPL BUGs reported.

### PRD changes (one bullet each)

- §2.3 — insert — ambiguity — `created_at`-ascending ties preserve insertion order (matters: the frozen logical clock makes all `created_at` equal) — `envelope.py:136` (`_seq` tiebreak)
- §2.4 — insert — ambiguity — clock accepts any ISO instant forward or backward; logical clock governs business behavior only, envelope `api_request_timestamp` records server receipt time — `domains/clock.py:24-28`, `envelope.py:28-31`
- §2.7 priority 6 — revise — ambiguity — acting ElectionOfficial must resolve (else `ERR_FORBIDDEN_OWNERSHIP`) and be `ACTIVE` (else `ERR_OFFICIAL_INACTIVE` at this stage, ahead of state checks); creation endpoints use the body-named/parent jurisdiction — `auth.py:66-80`
- §2.7 priority 7 — revise — ambiguity — segregation of duties applies only to `CONDUCTED`→`CERTIFIED` and `CONDUCTED`→`CHALLENGED`; reopen and the §3.9 cascade carry no SoD check — `domains/la_tests.py:109-110`
- §2.8 — insert — ambiguity — budget adjustment returns the updated jurisdiction object with `201 Created` — `domains/jurisdictions.py:66`
- §3.2 — revise — **mismatch** — creation guard enumeration reordered to existence → `ERR_CAMPAIGN_ALREADY_ACTIVE` (priority 14) → `ERR_LAB_SUSPENDED` → scope → retired; the old sentence claimed the reverse order, contradicting §2.7's own priority numbering (14 < 19), which the impl follows — `domains/campaigns.py:85-103`
- §3.3 — insert — ambiguity — the optional `reason` on certificate suspend/revoke is accepted but not persisted (certificates carry no reason field) — `domains/certificates.py:112`
- §3.3 — insert — ambiguity — list read sweeps every certificate before filters; public documentation read sweeps too; transitions and internal guard checks act on stored status without sweeping — `domains/certificates.py:71-72,84`, `domains/public_read.py:21-23`
- §3.4 — insert — ambiguity — acceptance test against non-`ACCEPTANCE_TESTING` procurement → `ERR_INVALID_STATE` (409) — `domains/procurements.py:191-192`
- §3.4 — revise — ambiguity — cancellation `reason` is optional; a supplied reason is retained in `status_reason` — `domains/procurements.py:143-148,166-167`
- §3.5 — insert — ambiguity — layout store against non-`DRAFT` definition → `ERR_INVALID_STATE` (409) — `domains/definitions.py:139-140`
- §3.5 — revise — ambiguity — manual revert's non-empty reason is recorded in `status_reason`; cancellation reason optional, recorded when supplied — `domains/definitions.py:168-169,207-208`
- §3.6 — insert — ambiguity — conducting an L&A test against a definition not `PROGRAMMED`/`LA_PASSED` → `ERR_INVALID_STATE` (409) — `domains/la_tests.py:61-62`
- §3.6 — revise — ambiguity — reopen validates fresh `scanned_tallies` under the full tally rules (key equality, non-negative integers), not key-set only — `domains/la_tests.py:119-122`
- §3.7 — revise — ambiguity — `cycles_used` must be an integer ≥ 0; record-usage against a non-`IN_SERVICE` unit → `ERR_INVALID_STATE` (409) — `domains/units.py:207,209-210`
- §3.7 — revise — ambiguity — store environment pair must be numeric, not merely present — `domains/units.py:143-149`
- §3.7 — insert — ambiguity — `SECURED`/`UNSEALED` as `to_state` on the unit transition endpoint fail state legality (`ERR_INVALID_STATE`), being states of the unit's machines — `domains/units.py:28,162-163`
- §3.8 — revise — ambiguity — `resolution_note` accepted and recorded on any work-order transition, not only completion — `domains/work_orders.py:106,139-140`
- §3.10 — insert — ambiguity — audit opened against a non-`CANVASSING` definition → `ERR_INVALID_STATE` (409) — `domains/audits.py:44-45`
- §3.10 — revise — ambiguity — publishing from a non-terminal state → `ERR_INVALID_STATE` (409) — `domains/audits.py:132-133`

### IMPL BUGs (do NOT patch PRD; for Step 9b)

- **"`a to_state naming a real state that is unreachable from the current state fails here with ERR_INVALID_STATE (409)`" (§2.7 priority 8, verbatim)** — `domains/work_orders.py:28-32,109`: `WO_FROM` has no `SCHEDULED` key, so `to_state="SCHEDULED"` (a real machine state) raises `KeyError` → Flask 500 handler returns `ERR_INVALID_REQUEST`/500 (`app.py:67-69`) — fix: `if to_state not in WO_FROM or wo["status"] not in WO_FROM[to_state]: err_invalid_state(...)`
- Same verbatim §2.7 priority-8 rule — `domains/modifications.py:39-45,174`: `MOD_FROM` has no `PROPOSED` key → `to_state="PROPOSED"` KeyErrors to 500 — fix: same `to_state not in MOD_FROM` guard before indexing
- Same verbatim §2.7 priority-8 rule — `domains/audits.py:24-28,110`: `AUDIT_FROM` has no `INITIATED` key → `to_state="INITIATED"` KeyErrors to 500 — fix: same `to_state not in AUDIT_FROM` guard
- **"both floored at zero and both recomputed on every campaign mutation" (§3.2, verbatim)** — `domains/campaigns.py:205-229`: `recompute_conformity` runs only on `DEFICIENCIES_FILED` (210), resubmission (217), and `CERTIFIED` (200/225); the `IN_TEST`, `DENIED`, and `WITHDRAWN` transitions mutate the campaign without recomputing, leaving `conformity_final_bp`'s aging term (10 bp/full week since `last_submitted_at`) stale on reads — fix: call `recompute_conformity(camp)` unconditionally before `touch(camp)` at line 229. (Certification gating is unaffected — line 200 already evaluates fresh.)

### Focused checks

1. **Prose-only uniqueness**: all four PRD uniqueness declarations (`lab_code` global, `serial_number` global, `badge_no` per-jurisdiction, `seal_number` per-unit history) have dedicated catalog errors AND are enforced (`labs.py:38-40`, `units.py:79-81`, `officials.py:32-34`, `units.py:237-239`). No orphans. **Clean** — base-rate impl bug not present here.
2. **PRD-nullable read paths**: enumerated all nullable fields (`state_code`, `completed_at`, `ballot_layout`/paper fields, `status_reason`, `pre_maintenance_status`, calibrated paper fields, modification `classification`/`lead_time_days`/`classified_at`, `published_at`, `certified_by`); every read site is None-guarded or unreachable-when-None via state legality. The only crash paths found are the three KeyError sites above.
3. **Defined-but-uncalled / read-but-unwritten**: every PRD-stated guard exists and is invoked on its route; every guarded field has a writer. One harmless dead check: `units.py:168-169` (non-CA quarantine) is shadowed by the priority-2 transition-actor map.
4. **Unprefixed clock endpoint**: `POST /_clock/set_current_utc` mounted at root (`domains/clock.py:18`), boot default `2026-09-01T00:00:00Z` (`store.py:10`) — matches §2.4/§4 exactly. **Clean**.
5. **56-error catalog sweep**: all 56 §5 error ids are raised in impl code; none dead. **Clean**.

**Orchestrator verification:** `diff -q PRD_FINALIZED.md PRD_COMPLETED.md` → differ (rc=1); 38 changed lines total across the diff — real edits, not a mid-flight-kill byte-identical no-op. 4 IMPL BUGs carried into Step 9b.

## Step 9b: Fix Step-9 impl bugs + re-sweep — 2026-10-02T20:50:00.000Z

All 8 rounds are clean. The task is complete. Final report:

## Step 9b: 4 implementation bugs fixed, 8/8 sweep rounds green

### Per-bug confirmation and fixes

**Bug 1 — `domains/work_orders.py:109`** — Confirmed: `WO_FROM` (lines 28-32) keys are `IN_PROGRESS`/`COMPLETED`/`ABORTED` only; `to_state="SCHEDULED"` passes the `req_enum` check (line 105, `SCHEDULED ∈ WO_STATES`) then KeyErrors on `WO_FROM[to_state]` → Flask 500 handler → `ERR_INVALID_REQUEST`/500 envelope (app.py:67-69). Fix: `if to_state not in WO_FROM or wo["status"] not in WO_FROM[to_state]:` → 409 `ERR_INVALID_STATE`. py_compile OK.

**Bug 2 — `domains/modifications.py:174`** — Confirmed: `MOD_FROM` (lines 39-45) has no `PROPOSED` key; same KeyError→500 mechanism. Fix: same membership guard (`to_state not in MOD_FROM or ...`). py_compile OK.

**Bug 3 — `domains/audits.py:110`** — Confirmed: `AUDIT_FROM` (lines 24-28) has no `INITIATED` key; same mechanism. Fix: same guard (`to_state not in AUDIT_FROM or ...`). py_compile OK.

**Bug 4 — `domains/campaigns.py:229`** — Confirmed: `recompute_conformity` ran only on DEFICIENCIES_FILED/SUBMITTED-resubmission/CERTIFIED; IN_TEST, DENIED, WITHDRAWN mutated the campaign leaving `conformity_final_bp`'s aging term stale, violating PRD §3.2's verbatim "both floored at zero and both recomputed on every campaign mutation" (PRD.md:159). Totality verified before the fix: all four counters are initialized at creation (lines 111-114) and `last_submitted_at` is set at creation (line 117) and resubmission (line 216), never None — the function cannot raise in any reachable state. Certification gating unaffected: the CERTIFIED gate (line 200) evaluates fresh before checking the threshold, and the added call runs after the gate; the logical clock (`util.now()` → `db.clock`) doesn't advance within a request, so the double-recompute on the CERTIFIED path is idempotent. Fix: single unconditional `recompute_conformity(camp)` between `camp["status"] = to_state` and `touch(camp)`; per-branch calls left in place (no refactoring).

### Smoke probes (live server, dynamic port, killed by saved PID)
All 6 passed:
- WO `to_state=SCHEDULED` → 409 `ERR_INVALID_STATE` (was 500)
- Modification `to_state=PROPOSED` → 409 `ERR_INVALID_STATE` (was 500)
- Audit `to_state=INITIATED` → 409 `ERR_INVALID_STATE` (was 500)
- Negative control: `to_state=BOGUS` → 400 `ERR_INVALID_REQUEST` (P4 enum check still fires earlier)
- Campaign IN_TEST after clock +21 days → `conformity_final_bp=9970` (10000 − 3wk×10bp; was stale 10000), `conformity_screen_bp=10000` (screen has no aging term)
- Full certification pipeline (setup through CERTIFIED + certificate mint) still succeeds with the unconditional recompute in place

### Sweep verdict
Rounds 1-8: **79/79 passed, 0 failed** in every round. All eight `results.{1..8}.json` files exist under `workspace/implementation/` and were left in place per the output contract. No protected files (PRD.md, PRD_COMPLETED.md, PRD_FINALIZED.md, test_suite/, test_helpers/) were touched — edits are confined to the four domain files listed above.

**Orchestrator verification:** all 8 `results.{i}.json` parsed independently — 8× `passed=79/79`. Oldest results (20:45:43Z) newer than newest source (20:40:03Z) — sweep is post-edit. The three membership guards grep-verified at work_orders.py:109, modifications.py:174, audits.py:110; unconditional `recompute_conformity(camp)` at campaigns.py:229. `PRD_COMPLETED.md` untouched (mtime 20:34:16Z, pre-9b) — impl moved toward PRD, contract intact.
