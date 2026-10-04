# Worklog — task_3071_medicare_broker_call_center_enrollment_marketing_compliance

## Step 1: Create task directory — 2026-09-29T19:40:00.000Z

Task directory `./tasks/task_3071_medicare_broker_call_center_enrollment_marketing_compliance/` was pre-allocated by the requester; verified it exists with `workspace/` inside. No new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-29T20:26:57.894Z

All three scaffold artifacts are complete and lint-clean.

### Files generated

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3071_medicare_broker_call_center_enrollment_marketing_compliance/SCAFFOLD.yaml` | 2950 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1201 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 2771 |

`scaffold_lint.py` verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Design generated

**Profile** (beyond-Expert, per the difficulty directive): `compliance_audit` primary + `ledger_reconciliation` secondary; flat topology; compound state shape; `segregation_of_duties` roles; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `derived_field_reconciliation`, `rate_threshold_triggers`, `selector_policy`.

**§1.1 Entities** — 18: Agency (derived posture gating all children, money + rate rollups), Carrier, Agent, AgentStateLicense, CarrierAppointment, CarrierCertification, Member, ScopeOfAppointment, CallSession, Plan, FormularyDrug, PharmacyNetworkEntry, ProviderDirectoryEntry, Enrollment, CommissionLedgerEntry, CarrierReconciliation, Complaint, CoachingAssignment.

**§1.2 State machines** — 8 machines / 52 transitions, all non-linear: Agency posture (branching + two-step jump), Agent (branching + cyclic + terminal re-entry via rehire), CallSession (fork/join + amendment cycle), Enrollment (**parallel** submission_status × disenrollment_status), CommissionLedgerEntry (reinstatement cycle), CarrierReconciliation (dispute cycle), Complaint (appeal round trip), CoachingAssignment (time-driven overdue branch).

**§1.2.1** — 2 OCC rules on distinct parents (CallSession, Member), each with `expected_*_version` required input and a §1.5 write endpoint that bumps the parent version.

**§1.3 Calculations** — 15, including the dual-variant money family (`provisional_book_commission` vs `earned_commission_projections`, `rapid_disenrollment_chargeback` provisional vs final, `carrier_reconciliation_variance` provisional vs final), the order-pinned band-then-escalate chargeback, budget-weighted plan scoring, risk scoring, posture propagation, and three boundary/decay metrics.

**§1.4 / §1.6** — 21 ordered validation rules; 89 error codes, all reachable except four deliberately declared-and-shadowed branches that §1.9 asserts as such.

**§1.5 / §1.7** — 104 endpoints; 8 roles (7 opaque + `LicensedAgent: entity_backed:Agent`).

**§1.8** — 9 rule blocks × 2 instances = **18 instances**, each grounded in §1.7–§1.6 refs, with executable `setup_api_calls`/`trigger` chains and literal-computed assertions (e.g. `684.80`, `-1800.00`, `4134.00`).

**§1.9** — **9 sections / 60 instances** matching the claim-extraction guide's taxonomy exactly (Entities 13, State Machines 13, Calculations 7, Validations 8, Endpoints 3, Errors 4, RBAC 5, Cross-Cutting 5, Consistency Model 2); all 30 page tokens carry unbound `expected_*_version` placeholders resolved, and every `${var}` traces to an earlier `captures:`.

No sibling task directories were read at any point; the scaffold was derived solely from the scenario text, the skill spec, the claim-extraction guide, and the lint script.

## Step 3: Copy shared files — 2026-09-29T20:27:30.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3071_medicare_broker_call_center_enrollment_marketing_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-29T20:39:00.000Z

All three hard contracts pass. The PRD is complete.

### Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3071_medicare_broker_call_center_enrollment_marketing_compliance/workspace/PRD.md` — 579 lines.

I did not read `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory.

### Section structure

- **§1 Introduction** — 3 paragraphs (pain-point / architecture / dual-audience angles).
- **§2 Global Specifications** — 13 domain-derived subsections: 2.1 RBAC (all 8 roles, identity translation), 2.2 verbatim fixed envelope, 2.3 Pagination, 2.4 Staffing Authority, 2.5 Scope of Appointment, 2.6 Recording/Disclaimer/Marketing obligations, 2.7 Agency Compliance Posture, 2.8 Commission Ledger Principle, 2.9 Nested Resource Retrieval, 2.10 Common Resource Properties, 2.11 Precision and Rounding, 2.12 Optimistic Concurrency Control, 2.13 Validation Precedence.
- **§3 Business Logic** — 11 subsections grouped by lifecycle stage: standing up the call center → licensing bench → authorizing/running the conversation → plan comparison → commission forecasting/earning → enrollment submission & two dimensions → disenrollment & chargebacks → ledger entry amounts → complaints/secret shoppers/coaching → risk score → posture cascades.
- **§4 Endpoint Definitions** — status-code paragraph + 104-row table, 4 columns.
- **§5 Error Code Catalogue** — 89-row table, 2 columns. File ends there; no audit footer.

### Coverage audit

**Contract 1 — Field-Name Coverage: PASS.** Every scaffold identifier appears verbatim in backticks: 143/143 `entities[].fields[].name`, 120/120 `endpoints[].input` identifiers, 0/0 query/path params (the scaffold encodes these inside `input`). Diff empty.

**Contract 2 — Rule Coverage: PASS.** Every `validations[].check` has a prose sentence matchable to its `error_id` (all 89 error IDs appear, plus every transition-precondition error ID). All 52 `state_machines[].transitions` are expressed with `from`/`to` state pairs, preconditions paired to their error IDs, and side effects stated — including the full 6-level and 11-scenario cascade side-effect lists, the CERTIFIED→ACTIVE cross-agent cascade hop, and the `TERMINATED → PROVISIONING` re-entrant rehire. All 15 `calculations[]` are rendered as precise prose with pinned evaluation order (chargeback band lookup → hard escalation at tier 7 → soft escalation at tier 4 → complaint escalation → amount; ledger "round at the outer multiplication, then negate"; chronological earned-commission running-rate pass). Both `concurrency_rules` entries express `write_endpoint` + `expected_call_session_version` / `expected_member_version` + `ERR_STALE_VERSION` (412) in OCC-only terms. `applies_to` scopes enumerated; sibling branches rendered at equal density.

**Contract 3 — §3 Path Purity: PASS.** 991 backticked tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path tokens.

**Contract precision spot-checks:** §2.2 is byte-identical to `section-2.2-response-structure.md` (`req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`). Pagination defaults/min/max/sort stated. `PharmacyNetworkEntry` explicitly noted as the sole `common_fields: false` entity (only `id` + `created_at`). Precision (2dp / 6dp, round half up) and OCC stated. No fuzzy or approximating wording and no operator syntax or mathematical notation in prose — all thresholds rendered as words ("at least 1", "strictly below", 1.05 described as "a days-supply ratio multiplier", 2555 days as seven years, 3650 days as ten years). §3 contains no tables, no field lists, and no declared foreign keys; the `aep_daily_submission_capacity`, `max_open_coaching_per_agent`, `max_live_calls_per_agent` and `rapid_disenrollment_day_limit` constants are embedded as "90 days", "caps … at once", "defaults to 2", etc.

## Step 5: Generate unit tests — 2026-09-29T21:11:00.000Z

All checks pass. Here is the final summary.

### Files created

**`test_helpers/`** (1,933 lines)
| File | Lines |
|---|---|
| `__init__.py` | 18 |
| `types.py` | 517 |
| `api_client.py` | 403 |
| `api_errors.py` | 222 |
| `assertions.py` | 258 |
| `constants.py` | 94 |
| `factories.py` | 308 |
| `fixtures.py` | 598 |
| `test_users.py` | 33 |

**`test_suite/`** (4,617 lines, 124 tests, 130 files total = 6,550 lines)
Queue A: `test_10_commission_variants.py` (168), `test_20_chargeback_and_plan_scoring.py` (191), `test_30_cyclic_workflows.py` (213), `test_40_cascades.py` (188), `test_50_validation_precedence.py` (154), `test_60_boundary_precision.py` (212), `test_70_cross_entity.py` (105), `test_80_overlap_and_windows.py` (210), `test_90_compensating_invariants.py` (177).
Queue B: `test_c1_entities.py` (424), `test_c2_state_machines.py` (463), `test_c3_calculations.py` (308), `test_c4_validations.py` (362), `test_c5_endpoints.py` (151), `test_c6_errors.py` (179), `test_c7_rbac.py` (212), `test_c8_cross_cutting.py` (212), `test_c9_consistency.py` (125). Plus `conftest.py` (45).

### Tests emitted
- **Queue A (Difficulty): 59 tests** across 17 of the 18 instances — every instance carries ≥2 tests.
- **Queue B (Corner): 65 tests** across 59 of the 60 non-stub instances.
- All 124 test functions carry exactly one `Design:` tag; none untagged, none dual-tagged, none pointing at a non-existent instance.

### Instances SKIPPED (PRD-first filter)

**Queue A (1)**
- `cross_dependency_call_session_status_gates_enrollment` (`cross_entity_state_dependency`) — **Coverage fails.** The instance's core assertion is that `POST /enrollments` succeeds against a COMPLETED call and is refused with `ERR_CALL_NOT_COMPLETED` against an IN_PROGRESS call. PRD §2.13 lists `ERR_CALL_NOT_COMPLETED` only as a generic example in the state-legality paragraph, and §4's endpoint table title ("Submit an enrollment to a carrier from an **open** call session") does not state a state-machine precondition on the call session. No verbatim PRD sentence pins the outcome, so it fails the coverage condition (C2 red flag: endpoint-titular only).

**Queue B (1)**
- `prov_book_commission_rounds_each_term_before_summing` (`calculations`) — **Unique derivability fails.** Its asserted literal `provisional_book_commission_cents == 4134.00` (and the negative control "not 3966.00") depends on **where** the PRD's stated `1.06` method-fee multiplier is applied. PRD §3.5 states only that it "is carried in the configuration register for this projection" and never places it in a term; multiplier-inside-both-terms and multiplier-on-the-final-sum both survive a PRD-only reading at the given inputs (making the instance's own "4964.00" derivable), so a faithful implementer could ship a failing variant.

### Tag-coverage audit
- **§1.8 rule_ids represented (all 9):** `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.
- **§1.9 sections represented (all 9):** `entities`, `state_machines`, `calculations`, `validations`, `endpoints`, `errors`, `rbac`, `cross_cutting`, `consistency_model`. There are 0 `excluded_because:` stubs in this corner index, so no stub translation was due.

### Additional audit results
- 199 long quoted PRD citations checked against `PRD.md` — 0 non-verbatim (whitespace-normalized).
- 29 asserted `ERR_*` identifiers — all named in the PRD.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no mention of "scaffold" or `§1.x`/`Table N` in generated code.
- `python3 -m py_compile` clean; `pytest --collect-only` collects all 124 tests with no import errors.

## Step 6: Generate implementation — 2026-09-29T21:40:54.671Z

**Orchestrator note on isolation:** the Step 6 subagent reported "No `test_helpers/` or `test_suite/` directories exist in this task tree yet". The orchestrator verified afterwards that both directories DO exist (created by Step 5, 19 test_suite/*.py files). The subagent's factual claim about directory existence was therefore wrong; however its operative statement — that it read and created nothing under them — matches the isolation contract, and the implementation was generated from PRD prose alone. Recorded here rather than silently dropped.

Implementation complete.

### Files created — `workspace/implementation/` (4,185 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 12 | launcher — guarded `import flask` check, `exec python3 app.py`, reads `$PORT` |
| `requirements.txt` | 1 | `flask>=3.0.0` |
| `app.py` | 40 | Flask app, route registration, error handlers |
| `db.py` | 96 | in-memory collections, logical clock (default `2026-09-01T00:00:00Z`), UUID/ISO/date helpers |
| `errors.py` | 115 | full error catalogue with PRD §5 statuses + `ApiError` |
| `response.py` | 62 | `meta`/`response_type`/`data` envelope, pagination meta |
| `middleware.py` | 184 | auth/allow-list, body coercion, left-to-right id resolution, pagination |
| `decorators.py` | 22 | `@requires(*roles)` |
| `serializers.py` | 87 | per-entity serializers; derived fields computed on read |
| `calculations.py` | 239 | pure rule engine (all §3 arithmetic) |
| `core.py` | 655 | recomputation, posture aggregate + cascades, ledger posting, projections |
| `comparison.py` | 121 | plan-comparison candidate set, costing, scoring, ranking |
| `routes/` (11 modules) | 2,571 | `platform, agencies, carriers, agents, members, scopes, call_sessions, plans, enrollments, ledger, complaints` |

### Endpoint count: 104 / 104
Automated diff of the PRD §4 table against the registered Flask rules returned **zero missing, zero extra**. All roles are enforced as a strict allow-list with the exact PRD role spellings, and `LicensedAgent` identity is `entity_backed` (`X-User-ID` must be an existing Agent).

### Verification performed
- `start.sh` booted twice on the same port: store empty on first boot, entity created, **store empty again after re-launch** — per-test-server isolation wipes all state.
- Three independent smoke suites (≈90 scenarios, run to completion only against a freshly booted process) covering auth, RBAC, pipeline gates, OCC, state machines, calculations, cascades and error codes.
- Compile-clean; no file I/O, no SQLite, no `/tmp` cache, no seeding anywhere (grep-verified).

### Coverage audit

**PRD sections:** §2.1 RBAC (both header checks, strict deny) · §2.2 envelope (exact field names, 3-digit timestamps, pagination fields only on lists) · §2.3 pagination (default 10, min 1, max 100, offset 0, creation-ascending) · §2.4 pipeline + termination unwind + guarded rehire · §2.5 scope capture/expiry/consumption/voiding, empty-authorization treated as no scope · §2.6 recording retention (`MISSING`/`EXPIRED`/`RECORDED`) and disclaimer/recording obligations waivable only on `WRITTEN` · §2.7 posture aggregate · §2.8 ledger conservation, reconciliation, corrections · §2.9 left-to-right id resolution · §2.10 common fields (`PharmacyNetworkEntry` carries only `id`+`created_at`) · §2.11 `Decimal` round-half-up everywhere · §2.12 OCC on `expected_call_session_version` / `expected_member_version` / agency / carrier / member updates, 412 · §2.13 the full 21-step precedence chain.

**State machines:** all seven, including the cyclic ones — Agent `TERMINATED→PROVISIONING`, CallSession `COMPLETED⇄AMENDED` (amendment mutates nothing else), CommissionLedgerEntry `REVERSED→{PROVISIONAL,FINALIZED}`, CarrierReconciliation `DISPUTED→OPEN`, Complaint `APPEALED→UNDER_REVIEW`, CoachingAssignment automatic `→OVERDUE`.

**Calculations (all 15):** provisional book (per-enrollment + agency variants), chronological earned pass (lapse gap 0 ⇒ initial rate each time), rapid-disenrollment chargeback with the pinned 10-step order and both variants, reconciliation variance under both selectors, formulary annual cost (1.05 multiplier, `ceil` fills), composite score (5 rounded terms then re-rounded), finding codes (ordered table), risk score (per-session rounding then single sum), posture recomputation (top-down branches, no stored-posture read), loss ratio, coaching overdue days, ledger amounts (rounded *then* negated), AEP daily capacity (strict), scope validity (inclusive), recording retention (inclusive).

**Validations:** all 21 priorities in order; a blocked mutation on a `FROZEN` agency reports `ERR_AGENCY_FROZEN` ahead of body-field validation, matching §2.7/§2.13.

**Cascade coverage:** `OPEN→RESTRICTED`, `OPEN→FROZEN` and `RESTRICTED→FROZEN` each run their own level-specific effects (suspensions, call drops, enrollment withdrawals with REVERSAL entries, `DISPUTED→OPEN` re-opening, risk-score recomputation for every agent); recovery is only ever via `posture-reset`, one level at a time, with the two legs guarded by different conditions.

One judgement call worth flagging: results are returned in creation-ascending order per §2.3 rather than the scaffold's unspecified sort defaults, and the PRD-wins rule was applied where the two disagreed — notably `POST /call-sessions` overlapping on the path is `ERR_AGENT_HAS_ACTIVE_CALL` (expected-clock containment), while the per-agent cap rule is `ERR_LIVE_CALL_LIMIT_EXCEEDED`, and the "5 strikes ⇒ FROZEN" cascade was implemented with the strike count over `SUBSTANTIATED ∪ APPEALED` as the PRD sentence states.

## Step 7: Run tests and iterate — 2026-09-30T00:04:00.000Z

**Orchestrator verification:** all 8 `results.${i}.json` files read back independently by the orchestrator — `passed=124 total=124` for i = 1..8. Clean sweep, no flakiness. Suite still collects 124 tests (no deletions).

All 124 tests pass in all 8 parallel rounds.

### Summary

**Iterations run**: 9 total — 1 initial diagnostic 8-round sweep (124 tests, **68 failing** deterministically in 8/8 rounds), 7 local full-suite iterations (69 → 54 → 48 → 10 → 8 → 7 → 5 → 0 failures), then the authoritative 8-round parallel sweep: **rounds 1–8 all report `passed=124 total=124`** (clean sweep, no flakiness).

**Tests deleted**: none. The union of failures was 68; all 68 were resolved without deletion — every failing assertion traced to a verbatim PRD sentence, and the collapses were in fixtures/implementation, not in PRD coverage.

**Root-cause groups and fixes**

`test_helpers/` (fixture bugs — the largest group; ≈25 tests shared these):
- `fixtures.py::capture_scope` — stamped a fixed `captured_on` literal, so scenarios whose anchor clocked later built a "clock before captured_on" state PRD §2.5 forbids. Now stamps the server's live clock.
- `fixtures.py::setup_scope_and_completed_call` / `setup_ringing_call` — `suffix` was `"two"` instead of `"_two"`, producing `member_versiontwo` while tests read `member_two`/`call_two` (`KeyError`). Fixed.
- `fixtures.py::setup_three_plan_comparison_scenario` / `setup_two_plan_comparison_scenario` — placed candidate plans under three different carriers while the agent held one appointment; PRD §3.4's staffing-authority rule can never be satisfied by any PRD-faithful implementation. Consolidated onto one carrier.
- `fixtures.py::create_licensed_certified_agent` — left the agent CERTIFIED, but PRD §3.3 only lets an ACTIVE agent connect a call, so the anchor was unbuildable.

`test_suite/` (assertion/fixture bugs):
- Timestamp spelling: ~40 equality assertions compared server timestamps (PRD §2.10 pins three fractional digits) to no-millisecond literals. Added `test_helpers/assertions.py::utc()` and canonicalised the literals; instants unchanged.
- `test_c1` Pydantic-typed response fields (`'4.5' == 4.5`), a missing activated agent in a local helper, and a correction probe.
- `test_c6`/`test_c8`: `get_success_data()` on list endpoints returned the envelope, not the list (`len == 10`).
- `test_c50` two-violation scenario: PRD §2.5–2.6 make the intended voided-scope-with-completed-call precondition unreachable; rebuilt using PRD §3.2 termination to unwind the appointment.
- `test_c4`/`test_c60` clock-vs-window collisions (the anchor was submitted inside the AEP window; the RESTRICTED cascade *by design* suspends the agent and drops the call, so the "complete under RESTRICTED" probe was reframed onto a scope capture that §2.7 genuinely admits).
- `test_90` compensating pair: the pre-reversal/restored balance omitted the ADJUSTMENT that PRD §3.8 mandates on reversal of an EFFECTUATED+ENROLLED entry.

`workspace/implementation/` (genuine PRD violations found):
- `routes/call_sessions.py` — connect evaluated the agent-status check first and never swept overdue coaching; §2.13 puts the posture gate first, then scope gate, then disclaimer, then the overlap rule, and state legality (priority 16) last. Reordered; dropped a never-reachable `ERR_AGENT_HAS_ACTIVE_CALL` branch on create (the current-clock containment rule is the connect precondition, and PRD's "touching endpoints do not overlap" case now succeeds).
- `routes/enrollments.py` — rapid/standard CHARGEBACK entries were posted `PROVISIONAL`; PRD §3.7 requires `FINALIZED`. Also the withdrawal REVERSAL never recomputed its reconciliation period (§3.8).
- `core.py` — a REVERSAL that fed a `REVERSED` entry (PRD §3.8: "Reversed entries are excluded from every base, including the base of the reversal calculation itself"), and no reversal ever recomputed its period. Added `present_entry` so every new entry is attached to its month's standing period and that period is recomputed.
- `routes/agents.py` / `plans.py` — derived counters (`sweep_overdue`, `enrolled_member_count`) are now refreshed on read, per PRD §2.10 / §3.9.
- `serializers.py` — rate inputs were emitted as strings, not JSON numbers.
- `routes/complaints.py` — close was refused from `APPEALED` (PRD §3.9 lists it as closable); overdue sweep added before start/complete.

No `skip`/`xfail` anywhere; storage remains in-memory only and `start.sh` still wipes all state per boot.

## Step 8: Finalize PRD — 2026-09-30T00:41:00.000Z

PRD_FINALIZED.md is complete. Here is the summary.

### File stats
- `PRD.md`: 579 lines / 118,444 B. `PRD_FINALIZED.md`: 579 lines / 122,453 B. **Line delta 0 (0.00%)**; 14 source lines revised in place, no insertions/deletions, no new sections.

### Changes (one bullet per edit)

1. **§2.5** — revise — a non-`CAPTURED` (`CONSUMED`/`VOIDED`) scope on the comparison/connect/enrollment paths reports `ERR_SCOPE_OF_APPOINTMENT_MISSING`; `ERR_SCOPE_OF_APPOINTMENT_CONSUMED` is reserved for the effectuation precondition — `implementation/core.py:684-686`, `implementation/routes/enrollments.py:178`.
2. **§2.6** — revise — `ERR_RECORDING_EXPIRED` is declared but no operation raises it; elapsed retention only reads as `EXPIRED` — `implementation/errors.py:46`, `implementation/core.py:114` (no raise site).
3. **§2.8** — revise — compensating pair restores the pre-reversal balance disregarding the reversal's own side-effect `ADJUSTMENT` — `implementation/routes/ledger.py:100,352`, `implementation/core.py:281`.
4. **§2.8** — insert — an entry posted implicitly takes its `period_month` from `submitted_on` and is presented in the standing period for its carrier/month (the `OPEN` one, else the most recent); a period sums entries by carrier+`period_month`, not by stored `carrier_reconciliation_id`; the finalize/reverse/reinstate edges recompute every matching period — `implementation/core.py:490-494,530-571`, `implementation/routes/enrollments.py:106,244`, `implementation/routes/ledger.py:85,109,139`.
5. **§2.10** — insert — single-resource reads refresh that resource's own derived counts (agent counts, plan `enrolled_member_count`); the `overdue_days` derivation runs on individual assignment and coaching-collection reads too and moves a passed-`due_on` assignment to `OVERDUE` — `implementation/routes/agents.py:84-85,394`, `implementation/routes/plans.py:75`, `implementation/routes/complaints.py:261,271`.
6. **§2.11** — insert — decimal rate inputs are carried as JSON numbers, not strings — `implementation/serializers.py:50-54`, `implementation/routes/carriers.py:33-38`, `implementation/routes/plans.py:139`.
7. **§3.3** — revise — the two live-call rules are distinguished: opening an overlapping *declared* half-open interval fails `ERR_AGENT_HAS_ACTIVE_CALL`; connect re-checks *clock containment*; `max_live_calls_per_agent` is evaluated at connect and yields `ERR_LIVE_CALL_LIMIT_EXCEEDED` — `implementation/routes/call_sessions.py:15-42,80-82,160-165`.
8. **§3.3** — revise — finalize-amendment failures are spelled out (`ERR_DISCLAIMER_NOT_DELIVERED`, then `ERR_RECORDING_MISSING`), not just stated as booleans — `implementation/routes/call_sessions.py:253-256`.
9. **§3.6** — revise — the effectuation recompute targets the standing period `OPEN` at the clock's own `period_month` for the carrier; absent that, none — `implementation/routes/enrollments.py:195`.
10. **§3.6** — revise — `disenrolled_day_number` reads null and `is_rapid_disenrollment` reads boolean false before disenrollment — `implementation/serializers.py:80-85`.
11. **§3.8** — revise — finalize derives the amount and adopts it for `INITIAL`/`RENEWAL`; `ADJUSTMENT`/`CHARGEBACK`/`REVERSAL` keep their posted amount; `ERR_AMOUNT_VARIANT_MISMATCH` is declared but unreachable — `implementation/routes/ledger.py:73-83`.
12. **§3.8** — revise — same compensating-pair side-effect-`ADJUSTMENT` caveat at its second statement — `implementation/routes/ledger.py:100,352`.
13. **§3.9** — insert — the overdue derivation runs before start/complete read the assignment's status, so a passed-`due_on` assignment is already `OVERDUE` (un-startable, completable) — `implementation/routes/complaints.py:271-284`.

### Per-edit pre-edit search log (a/b/c)

Every edit got a mandatory global search. Representative summaries; (c) = wording adjustment made to keep all enumerated paths consistent.

- **§2.5 CONSUMED (e1)** — (a) which error a non-`CAPTURED` scope produces. (b) `core.require_scope_usable` callsites `plans.py:224`, `call_sessions.py:86,149`, `enrollments.py:36`; `enrollments.py:177-179`; `errors.py:42`; PRD §2.5:96-98, §2.6, §3.3:225. (c) Softened from a blanket "reports MISSING" to scoping the effectuation-only use of the CONSUMED identifier, since `enrollments.py:178` *does* use it.
- **§2.6 RECORDING_EXPIRED (e2)** — (a) whether any path raises `ERR_RECORDING_EXPIRED`. (b) `errors.py:46`, `core.py:114,183`, `serializers.py:78`, `call_sessions.py:121-123`. (c) Narrowed to "no operation raises it" and named the derived-status alternative, avoiding a claim the `410` mapping contradicts.
- **§2.8 invariant (e3)** — (a) the compensating-pair invariant's subject. (b) `ledger.py:100-104,335-355`, `core.py:274-282,516-521`. (c) Added the side-effect-`ADJUSTMENT` carve-out required by `_check_invariant`'s `_reversal_side_effect_cents`.
- **§2.8 presentation (e4)** — (a) the reconciliation period a posted entry lands in and which entries a period sums. (b) `core.py:314-336,524-579`, `enrollments.py:106,156,195,244,310,327`, `ledger.py:35,85,109,120,139,159,182,225,252,271,290,296,310,315,350`, `core.py:396-409` (freeze path deliberately excluded). (c) **Revised twice**: first draft over-claimed that close/dispute/reopen "recompute every matching period"; corrected to finalize/reverse/reinstate only, then narrowed to "the finalize, reverse and reinstate edges" so the freeze-cascade reversal (`core.py:407`, which recomputes no period) is not mis-described.
- **§2.10 read-refresh (e5)** — (a) which derived values refresh on read. (b) all `sweep_overdue`/`recompute_agent_counts`/`recompute_plan_enrolled_count` callsites in `agents.py`, `plans.py`, `complaints.py`, `core.py`. (c) **Revised**: first draft implied *list* reads of agents/plans refresh counts; narrowed to single-resource reads and stated the coaching-read overdue effect separately.
- **§2.11 numbers (e6)** — (a) wire type of decimal fields. (b) `serializers.py:22-54`, all Decimal-valued emitted fields. (c) none.
- **§3.3 live-call (e7)** — (a) the overlap/cap rules at both endpoints. (b) `call_sessions.py:15-42,80-82,160-165`, PRD §2.13:175, §3.3:229. (c) Split into open-time (interval-vs-interval) vs connect-time (clock containment) to match the code.
- **§3.3 amendment (e8)** — (a) finalize-amendment error identifiers. (b) `call_sessions.py:241-262`. (c) none.
- **§3.6 effectuation (e9)** — (a) which period effectuation recomputes. (b) `enrollments.py:189-196`, `core.py:524-528`. (c) Added the no-period no-op.
- **§3.6 unset fields (e10)** — (a) wire values before disenrollment. (b) `serializers.py:79-85`. (c) none.
- **§3.8 finalize (e11)** — (a) `ERR_AMOUNT_VARIANT_MISMATCH`. (b) `ledger.py:59-89`, `errors.py:101`. (c) none.
- **§3.8 invariant 2nd (e12)** — (a) as e3. (b) as e3. (c) none.
- **§3.9 overdue-before-edges (e13)** — (a) overdue derivation vs start/complete status reads. (b) `complaints.py:264-293`, `core.py:230-245`. (c) none.

### Key findings
- The largest class of PRD/impl divergence was **error-identifier routing**: `ERR_SCOPE_*_CONSUMED`, `ERR_RECORDING_EXPIRED`, `ERR_AMOUNT_VARIANT_MISMATCH` are declared in the PRD for conditions the implementation reports under a different identifier or never raises at all.
- The **live-call overlap rule** was stated identically in §2.13 and §3.3 but the implementation enforces *two distinct* rules (declared-interval overlap at open; clock containment at connect) plus the cap at connect — the §3.3 sentence now reflects that without disturbing §2.13.
- **Reconciliation period membership** was pinned by stored id in the PRD and by (carrier, `period_month`) in code; the finalized text states the code's rule, which is what a fresh implementer needs to reproduce `internal_total_cents`.
- No edits were made for the pure-fixture-bug items (timestamp spelling/`utc()`, fixture consolidation, `suffix` keys) — those were test/helper defects with no PRD-silence behind them.

## Step 9: Complete PRD — 2026-09-30T01:12:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written as a minimal in-place patch over `PRD_FINALIZED.md`.

### Summary

**Source:** `PRD_FINALIZED.md` (existed, so used as the base) → `PRD_COMPLETED.md`
**Lines:** 579 → 579 (unchanged; every edit was an in-paragraph insert or revise, no new sections)
**Chars:** 122,453 → 135,332 (delta **+12,879**)

**Counts:** 44 changed sites — **37 ambiguity-pins**, **7 mismatch-revisions** (a few sites carry both a pin and a revision).

I walked every endpoint, state transition, formula, validation, default, side effect and response shape in `implementation/` against the PRD. Endpoint table paths and role allow-lists already matched exactly (verified programmatically), as did the error catalogue and its HTTP statuses. The residual was interpretation-level prose.

### Changes, one bullet per site

- §2.2 Standard Success Response — insert — ambiguity — named the two operations whose `data` is a projection rather than a stored row (book-of-business object; `_clock` echo) — implementation/routes/platform.py:20, implementation/routes/agencies.py:162
- §2.3 Pagination — insert — ambiguity — `limit` outside 1–100 and negative `offset` are clamped, not rejected; `has_more` is `offset+len(page) < total_count` — implementation/middleware.py:151-156, implementation/response.py:51
- §2.4 Terminating an agent — revise — ambiguity — termination instant is `effective_on` when supplied else the clock; rehire rewrites `hire_date` — implementation/routes/agents.py:313-318, 357-359
- §2.4 Rehire — revise — ambiguity — rehire resets `chargeback_tier` but leaves EXPIRED certification rows, so the `ERR_RECERTIFICATION_REQUIRED` guard persists after a rehire loop — implementation/routes/agents.py:352-359
- §2.5 Derived scope dates — revise — ambiguity — `expires_on`/`retained_until` are recomputed on read from current agency config, not frozen at capture — implementation/serializers.py:73-75, implementation/core.py:99-106
- §2.6 Call session fields — insert — ambiguity — an open without `disclaimer_delivered` records boolean false — implementation/routes/call_sessions.py:103
- §2.7 Posture recompute — insert — ambiguity — only worsening moves are applied; a computed target at/below stored posture is ignored (so repeat recomputes cannot re-fire cascades) — implementation/core.py:443-459
- §2.7 Substantiated rate — insert — ambiguity — numerator counts APPEALED complaints regardless of `substantiated_on`; CLOSED excluded; balance sum skips entries whose enrollment no longer resolves — implementation/core.py:260-282
- §2.7 FROZEN gate — revise — mismatch — enumerated the operations the gate actually guards (scope capture, call open/connect/complete/amend, enrollment submit/withdraw/disenroll, license/cert/appointment, agent rehire, ledger reinstate/reinstate-finalized) and the ones it does not (carrier-side enrollment edges, POST /plans, POST /members, PUT /agents|carriers|members, complaints, coaching, `_clock`) — implementation/middleware.py:135-138 + 14 call sites
- §2.10 Recomputation-on-read — insert — ambiguity — agency posture/rate/loss_ratio refresh on mutation, not on a bare agency read — implementation/routes/agencies.py:80-82
- §2.11 Wire format — insert — ambiguity — cent counts emit as JSON numbers (floats), not integers; scope derived dates stay ISO strings — implementation/serializers.py:47-55, 73-75
- §2.13 Agency posture gate — insert — ambiguity — cross-reference pinning the gate to the §2.7 site list — implementation/middleware.py:135
- §2.13 Call-connect ordering — insert — ambiguity — scope → disclaimer → overlap → live-call cap → `ERR_AGENT_NOT_ACTIVE`, so scope failures beat call state and the agent-status check is last — implementation/routes/call_sessions.py:148-167
- §3.1 AEP window — insert — ambiguity — window inclusive at both ends and bites only PDP — implementation/routes/enrollments.py:56-59
- §3.1 `max_open_coaching_per_agent` — insert — ambiguity — declared and updatable but never enforced — implementation/routes/agencies.py:23, grep shows no enforcing call site
- §3.1 Carrier config — insert — ambiguity — `chargeback_clawback_pct` is stored/reported but never applied; non-ACTIVE carrier surfaces as `ERR_CARRIER_NOT_FOUND` — implementation/routes/carriers.py:37, implementation/routes/enrollments.py:143
- §3.1 Plan `enrolled_member_count` — insert — ambiguity — derived and refreshed on the plan's single read plus effectuation/disenrollment, not on a list read — implementation/routes/plans.py:75
- §3.1 Reference data — insert — ambiguity — `cost_share_multiplier_pct` does not enter the comparison drug cost — implementation/calculations.py:174-190
- §3.2 Agent creation — revise — ambiguity — no uniqueness guard on `national_producer_number` — implementation/routes/agents.py:34
- §3.2 Certification duplicate guard — insert — ambiguity — checked before the carrier's contract_type guard — implementation/routes/agents.py:160-169
- §3.2 Appointment — revise — ambiguity — certification sought by carrier only (no product type on the request); state_code only constrains the license — implementation/routes/agents.py:218-232
- §3.2 Appointment hop — revise — mismatch — counts recomputed for every other agent of the agency, not narrowed to the request's `state_code` — implementation/routes/agents.py:253-255
- §3.2 Suspension — insert — ambiguity — no suspend endpoint exists; SUSPENDED is reached only via posture cascades — implementation/core.py:375-380, 412-415
- §3.2 Reinstate guards — insert — ambiguity — FROZEN is answered with `ERR_AGENCY_FROZEN` ahead of `ERR_AGENCY_NOT_OPEN` — implementation/routes/agents.py:282-285
- §3.3 Member drug/provider lists — insert — ambiguity — both default to empty; update refuses staleness with `ERR_STALE_VERSION` — implementation/routes/members.py:32-33, 63-67
- §3.3 Void scope — insert — ambiguity — missing `reason` is `ERR_INVALID_REQUEST` — implementation/routes/scopes.py:86-87
- §3.3 Open call — insert — ambiguity — body ids resolve `agent_id`,`member_id`,`scope_of_appointment_id`; opening is not gated on agent status — implementation/routes/call_sessions.py:66-86
- §3.3 Complete call — revise — mismatch — `notes` is accepted but never stored or echoed — implementation/routes/call_sessions.py:174-203
- §3.3 Drop call — insert — mismatch — `reason` is accepted but discarded; agent ownership not enforced (call's `agent_id` drives recomputes) — implementation/routes/call_sessions.py:205-223
- §3.3 Finalize amendment — insert — ambiguity — disclaimer and recording presence only; capture_channel waiver does not apply — implementation/routes/call_sessions.py:253-256
- §3.4 Ranking response — insert — ambiguity — pinned the per-entry `ranked_plans` shape and the computed-read (non-persisted) nature — implementation/comparison.py:100-113
- §3.5 `window_days` — insert — ambiguity — overrides the 365-day span — implementation/routes/agencies.py:158-160
- §3.5 Method-fee multiplier — insert — ambiguity — carried but never applied — implementation/calculations.py:14 (unreferenced)
- §3.5 `provisional_commission_cents` — insert — ambiguity — pinned at creation; recomputed only on the four membership edges — implementation/routes/enrollments.py:102, 194, 332
- §3.5 `final_commission_cents` — insert — ambiguity — recomputed agency-wide on each of those four edges, so sibling rows refresh — implementation/core.py:650-654
- §3.6 Rejection — insert — mismatch — `reason` accepted but not recorded — implementation/routes/enrollments.py:200-213
- §3.6 Daily capacity — insert — ambiguity — refusal at count ≥ capacity, and capacity 0 refuses every dated submission — implementation/routes/enrollments.py:61-68
- §3.6 Operator money paths — revise — mismatch — pinned the three paths' differing reconciliation-status demands (adjustment requires OPEN; standalone ledger entry does not; correction requires OPEN carrier+month match) and the `CHARGEBACK`/`REVERSAL` fall-through amount of zero — implementation/routes/enrollments.py:343, implementation/routes/ledger.py:173-175, implementation/core.py:481-489
- §3.7 Disenrollment classification — insert — ambiguity — classification rides the request's optional `disenrollment_status`; free text is `disenrollment_reason`; output status is always re-derived — implementation/routes/enrollments.py:269-277, 288-289
- §3.7 Standard-path chargeback — insert — ambiguity — amount 0 excluded from the `loss_ratio` numerator by the strictly-negative test — implementation/core.py:291-292
- §3.7 Band fall-through — insert — ambiguity — the beyond-band fall-through to 1.00 is unreachable because such a day number is refused as `ERR_NOT_RAPID_DISENROLLMENT` — implementation/routes/enrollments.py:300-302
- §3.8 Reversal side effects — insert — ambiguity — no `ENROLLED` precondition on reversal; the side-effect ADJUSTMENT is presented in the reversed entry's period; balance/period recomputed again after it — implementation/routes/ledger.py:91-123
- §3.8 Finalization amount — revise — mismatch — `REVERSAL` keeps its posted amount while `CHARGEBACK` is re-derived (so a 0-amount standard chargeback is not carried forward) — implementation/routes/ledger.py:73-83
- §3.9 Coaching type from complaint — insert — ambiguity — pinned the complaint_type→coaching_type pairing table — implementation/routes/complaints.py:296-306
- §3.9 Dismiss from UNDER_REVIEW — insert — ambiguity — does not touch `substantiated_complaint_count` or risk score — implementation/routes/complaints.py:148-154
- §3.9 Overdue trigger — insert — ambiguity — the ≥1-day trigger counts assignments of any status, so a COMPLETED assignment still triggers — implementation/core.py:361-364
- §3.10 Risk-score triggers — revise — mismatch — corrected the trigger list (adds withdrawal from SUBMITTED/ACKNOWLEDGED, complaint appeal, appeal-reversal dismissal, complaint closure, amendment finalization, the agency-freeze sweep; excludes filing, begin-review, UNDER_REVIEW dismissal, remand, amendment, recording attachment, bare agent read) — implementation/routes/*.py (grep of `recompute_risk_score`)
- §3.11 OPEN→FROZEN — insert — ambiguity — the closing per-agent risk recompute is needed because calls were just dropped — implementation/core.py:423-424
- §3.11 Posture reset — revise — mismatch — invalid `target_posture` is `ERR_INVALID_REQUEST`; the RESTRICTED leg does not test the complaint rate — implementation/routes/agencies.py:117-152
- §2.8 Compensating pair — revise — ambiguity — removed an inserted sentence that mis-identified the side-effect ADJUSTMENT by its empty `memo` (the code actually keys on the posted reversal's own amount), restoring the original text — implementation/routes/ledger.py:112-123

No behavior in `implementation/` was invented, and no test-suite assertion was used as authority — tests were consulted only to confirm whether a behavior was already pinned.

**Orchestrator note:** the final bullet is Step 9 reverting a Step 8 edit — exactly the NO-NEW-MISMATCH rule doing its job (Step 8 introduced a false universal claim about how the side-effect ADJUSTMENT is identified; Step 9 caught it against the code and restored the original wording).