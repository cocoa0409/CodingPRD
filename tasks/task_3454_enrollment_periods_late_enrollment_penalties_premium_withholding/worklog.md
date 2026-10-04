# Worklog — task_3454_enrollment_periods_late_enrollment_penalties_premium_withholding

## Step 1: Create task directory — 2026-10-02T06:30:00.000Z

Task directory was pre-allocated per command args; verified `./tasks/task_3454_enrollment_periods_late_enrollment_penalties_premium_withholding/workspace/` exists. No new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T07:29:00.000Z

All literals verified against the pinned formulas. The scaffold package is complete and clean.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3454_enrollment_periods_late_enrollment_penalties_premium_withholding/`):

1. **SCAFFOLD.yaml** — §1.0–§1.7 only (no design keys): fixed response envelope, normative conventions block (logical clock default `2026-09-01T00:00:00Z`, month-granular arithmetic, half-open enrollment vs closed employer-coverage interval semantics, cent/dime rounding pins, `created_at ASC` tie-break), plus complexity profile (temporal-windowing primary, compliance/audit secondary; flat topology; parallel state dimensions; segregation-of-duties role model).
2. **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single key `scaffold_difficulty_design`, **18 instances** (9 rules × 2), each with structured setup/trigger chains and pre-computed literals.
3. **SCAFFOLD_CORNER_DESIGN.yaml** — single key `scaffold_corner_design`, **50 instances** (42 active + 8 `excluded_because` stubs) across all 9 taxonomy sections.

**Counts**: 14 entities, **37 endpoints** (35 business under `/medicare` + `/_clock/set_current_utc` + `/_ops/run_monthly_cycle`), 12 state machines, 15 calculations, 37 ordered validations, 37 error codes, 5 roles, 1 OCC concurrency rule.

**Difficulty design (beyond expert)**: provisional-vs-final IRMAA premiums (19000 vs 38000 for identical inputs), Part-D LEP rounding variants (round_dime half-up 448.5→450 vs rejected truncations/per-month 210), 4-branch IEP coverage-start formula, parallel enrollment×collection status dimensions, appeal review cycle with supersede cascade, depth-2 employer-end cascade (ENDED→SEP row + payer flip) and depth-4 relief-grant cascade (retro enrollment → penalty VOIDED → determination SUPERSEDED → invoice reprice + credit, conserving 41800 == 38000 + 3800), two validation priority pairs ({temporal,constraint} and {state,fiscal}), boundary checks at MAGI==floor and gap==12 months, cross-entity gates (window state, arrangement state), closed-vs-half-open interval overlap semantics, AEP last-in-wins vs OEP single-use election divergence, OCC on `Beneficiary.version` for elections, withholding waterfall with suspension cascade, 3-past-due delinquency termination, SoD on appeal adjudication.

**Verification**: all three files parse as valid YAML with required top-level keys; `scaffold_lint.py` verdict — **clean lint** (424 §1.8+§1.9 calls scanned, 0 violations, all FKs reverse-reachable); no forbidden concurrency vocabulary; error catalog closed under references (fixed one missing `ERR_PAYMENT_AMOUNT_MISMATCH` entry, a dead `WITHDRAWN` enum value, and two pseudo-transitions during the audit); every formula-derived assert literal executed and confirmed in Python.

Orchestrator verification: all three files exist at the required paths and parse as valid YAML with the required top-level keys (1368 + 1069 + 1517 lines).

## Step 3: Copy shared files — 2026-10-02T07:31:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T07:46:00.000Z

The document passed the full read-through and all mechanical checks. The generation is complete.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3454_enrollment_periods_late_enrollment_penalties_premium_withholding/workspace/PRD.md` — 359 lines.

**Section list**:
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 Roles/RBAC, 2.2 API Response Structure (byte-identical to the canonical block — verified by diff), 2.3 Pagination, 2.4 Logical Clock & Calendar-Month Arithmetic, 2.5 Common Resource Properties, 2.6 Money/Rounding Modes, 2.7 OCC, 2.8 Validation Order & Error Precedence, 2.9 Coverage Interval Semantics
- §3 Business Logic (9 subsections): 3.1 Registration/IEP, 3.2 Windows & Enrollment, 3.3 Employer Coverage & Payer Coordination, 3.4 Late Enrollment Penalties, 3.5 Rates/Tax/Determinations, 3.6 Appeals, 3.7 Withholding/Invoices/Delinquency (+ monthly cycle), 3.8 Elections, 3.9 Equitable Relief cascade
- §4 Endpoint table (37 rows, 4 columns), §5 Error catalogue (37 rows, 2 columns)

**Coverage self-audit** (scaffold vs. PRD prose):
- Endpoints: 37 scaffold → 37 in §4 table, all side effects narrated in §3
- State machines: 12 → 12 fully expressed (every transition's from/to, preconditions paired with error ids, side effects, terminal-state notes)
- Calculations: 15 → 15 fully expressed in reconstruction-safe prose (rounding pins, evaluation orders, rejected variant readings for Part D LEP, boundary examples)
- Validations: 37 → 37 expressed; global priority pipeline in §2.8 plus per-endpoint orderings restated in §3 (window→duplicate→part on enrollments; part→schedule→tax→enrollment→duplicate on determinations; OCC→window→OEP checks→target on elections; SoD-before-state on adjudication; state→temporal→verified on coverage end; payable→amount on pay)
- Error codes: 37 in catalog (profile header says 36; actual catalog lists 37 — I used the catalog) → 37 in §5, all 37 also present in §2/§3 prose
- Roles: 5 → 5 in §2.1 with identity translations (Beneficiary entity-backed; FieldOfficer/AppealsOfficer/IrsDataAgent/BenefitAdministrator opaque)

**Hard Contract reports**:
- Contract 1 (Field-Name Coverage): 90 required identifiers (entity fields + request bodies + query params + system outputs) — 90 present, 0 missing. PASS
- Contract 2 (Rule Coverage): all six high-risk categories plus the tail walked by hand — priority orderings, the single OCC rule (endpoint + `expected_beneficiary_version` + `ERR_STALE_BENEFICIARY_VERSION`/412 all named, no time-overlap framing), cross-entity cascades, applies_to scopes, field-level defaults (`credit_cents` 0, null end months, `is_drug_coverage_creditable` false, `adjudicated_by_user_id` null until decision), sibling-branch symmetry (MA/ORIGINAL, APPROVED/DENIED, GRANTED/DENIED, 4 IEP effective-month branches). PASS
- Contract 3 (§3 Path Purity): 567 backticked tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path tokens. PASS

One adjudication note: the endpoint description for withholding-arrangement creation said it "sweeps eligible PENDING_SETUP/DIRECT_BILL enrollments," while the state-machine note says only DIRECT_BILL is swept and PENDING_SETUP resolves at activation. I carried the more specific state-machine reading (and stated the PENDING_SETUP exemption explicitly).

## Step 5a: Generate test helpers (Stage 1 of split Step 5) — 2026-10-02T08:05:00.000Z

All checks pass (the last probe used an outdated pytest attribute name — `fx.client` is a genuine `FixtureFunctionDefinition` under pytest 9.1.1). Stage 1 is complete.

## Stage 1 complete — test_helpers/ frozen

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3454_enrollment_periods_late_enrollment_penalties_premium_withholding/test_helpers/`):

| file | lines | contents |
|---|---|---|
| `__init__.py` | 58 | barrel: framework generics + all domain modules |
| `constants.py` | 376 | mount points, clock default, roles, all enum vocabularies, thresholds, rounding + month helpers, canonical RS2026/RS2027 literals |
| `types.py` | 280 | 12 status enums + 14 entity TypedDicts (all `common_fields: true` → id/created_at/updated_at/version) + `IrmaaBracket`, `ClockReading`, `MonthlyCycleSummary` |
| `api_errors.py` | 111 | `ApiErrorId` (37 members) + `HTTP_STATUS_CODES` + `set_error_http_status_map` registration |
| `api_client.py` | 331 | `ApiClient(GenericApiClient)` — 37 endpoint methods + `canonical_instant`/`same_instant` + `api_client` singleton |
| `factories.py` | 288 | 18 payload builders + `irmaa_brackets()` + canonical `rate_schedule_2026/2027_payload` + `next_sequence` |
| `assertions.py` | 346 | 14 `assert_<entity>()` + `assert_common_fields/month_string/date_string/cents` + invariants `assert_premium_component_sum`, `assert_invoice_outstanding`, `assert_money_conservation`, `assert_single_governing_election` |
| `test_users.py` | 121 | 6 operator header constants + `TEST_USERS` + 5 `make_<role>_headers()` builders + 4 malformed-auth header sets |
| `fixtures.py` | 740 | `client`/`api` pytest fixtures + clock/cycle primitives + ~20 single-entity builders + 11 composite setups |

**Key frozen signatures** (fixtures.py, the Stage-2 load-bearing surface): `set_clock(client, iso)`, `run_monthly_cycle(client)`, `advance_clock_and_run_cycle(client, iso)`, `publish_rate_schedule(client, year)`, `publish_default_rate_schedules(client)`, `register_beneficiary(client, date_of_birth=...)`, `beneficiary_headers(b)`, `submit_tax_record(...)`, `enroll(client, b, part)`, `terminate_enrollment(client, e)`, `create_employer_coverage/verify_employer_coverage/end_employer_coverage(...)`, `create_withholding_arrangement/adjust_arrangement(...)`, `create_determination/read_determination(...)`, `file_appeal/adjudicate_appeal/respond_to_appeal(...)`, `file_relief_case/adjudicate_relief_case(...)`, `pay_invoice_in_full(client, invoice)`, `make_election(client, b, window, target)` (raw response for 201-or-412), `create_election(...)` (201-validated), 12 `list_*` readers, and composites `setup_beneficiary_with_enrollment`, `setup_billed_enrollment`, `setup_delinquent_enrollment(past_due_count=1|2)`, `setup_terminated_by_delinquency`, `setup_terminated_enrollment_interval`, `setup_withholding_shortfall`, `setup_verified_employer_coverage`, `setup_determination`, `setup_final_determination`, `setup_provisional_determination`, `setup_appeal_under_review`, `setup_paid_invoice_pair`, `setup_relief_case_on_paid_pair`, `setup_beneficiary_with_ma_coverage`.

**Critical pins verified:**
1. **Unprefixed platform endpoints** — exactly two: `POST /_clock/set_current_utc` and `POST /_ops/run_monthly_cycle`. Runtime-intercepted every client method: produced (method, path) set == the 37 scaffold-declared endpoints exactly; the platform pair is built bare via `CLOCK_PATH`/`MONTHLY_CYCLE_PATH`, all 35 business paths via `API_PREFIX = "/medicare"`.
2. **Logical clock** — `CLOCK_INITIAL_INSTANT = "2026-09-01T00:00:00Z"`; every time-sensitive fixture calls `set_clock` before creating rows, so nothing depends on wall-clock.
3. **201s** — fixtures use `get_success_data` (lenient 2xx) throughout; no create path relies on a 200 default.
4. **Money/rounding** — `round_half_up_cents`/`round_dime_cents` (Decimal, ROUND_HALF_UP) verified against the PRD's worked examples (448.5→450, 241.5→240, 18500×10%→1850). Constants diffed against PRD: LEP 10%/12-month periods, Part D 1%/month, past-due termination threshold 3, employer-size ≥20, SEP 8 months, IEP ±3, arrears +30 days, IRMAA 6 tiers, pagination 10/1/100/0, canonical RS2026 (18500/3450) and RS2027 (19000/3600) with the full bracket arrays.
5. **Roles** — all 5 wired per PRD §2.1: `make_beneficiary_headers(id)` for the entity-backed Beneficiary (fixtures thread it through every ownership-gated call), opaque constants for FieldOfficer (`fo-100`), AppealsOfficer (`ao-200`), IrsDataAgent, BenefitAdministrator, plus `make_appeals_officer_headers(user_id)` for the SoD cross-wire test.
6. **No Stage-2 artifacts** — no `test_suite/`, no `conftest.py`, no test functions anywhere.

**Flag for Stage 2 (design-index contradiction):** ten design instances (e.g. `coverage_enrollment_parallel_status_dimensions`, `withholding_shortfall_triggers_suspension_cascade`, `delinquency_termination_after_third_past_due`, `invoice_pay_wrong_amount_rejected`) use DOB `1961-04-12` + enroll at clock `2026-05-10` and claim `effective_month == "2026-06"`. PRD §3.2 / calc_coverage_effective_month gives 2026-07 for that pair (attainment 2026-04 = T, M == T+1 → M+2). The fixtures therefore default this scenario to DOB `1961-06-12` (attainment 2026-06; enroll at 2026-05 is the M<T branch → effective 2026-06), which reproduces every downstream literal in those instances (June activation, invoice months 2026-06/07/08, arrears due 2026-07-05, termination at the 2026-09 cycle) without contradicting the PRD. Stage 2 should cite the PRD branch rule, not the design instance's DOB.

**Verification:** `ast.parse` passes on all 9 files; `import test_helpers.<module>` succeeds for every module and the barrel with no server running; error map registers 37 codes with the framework's validators; the singleton/client/class wiring is correct.

## Step 5b: Generate test suite (Stage 2 of split Step 5) — 2026-10-02T08:35:00.000Z

All checks green. Final state of the suite:

## Stage 2 complete — test_suite/ generated

**Files (16 test files + conftest.py, 78 tests total vs 60 active instances):**

| File | Tests | Contents |
|---|---|---|
| `conftest.py` | — | re-registers frozen `client`/`api` fixtures + one header fixture per role |
| `test_01_corner_entities.py` | 8 | entities section |
| `test_02_corner_state_machines.py` | 6 | state_machines section |
| `test_03_corner_calculations.py` | 4 | calculations section |
| `test_04_corner_validations.py` | 10 | validations section |
| `test_05_corner_endpoints_errors.py` | 4 | endpoints + errors sections |
| `test_06_corner_rbac.py` | 5 | rbac section |
| `test_07_corner_complexity_consistency.py` | 5 | complexity_layers + consistency_model |
| `test_08..test_16_difficulty_*.py` | 4 each (36) | one file per difficulty rule; 2 instances × 2 tests |

**Coverage:** 18/18 difficulty instances at exactly 2 tests each; 42/42 active corner instances at 1 test each; 8 `excluded_because` stubs not translated (all cross-references verified to resolve). **Skipped instances: none** — every active instance passed the PRD-first two-condition filter.

**pytest --collect-only:** `78 tests collected`, zero errors (PYTHONPATH=task root).

**AST tag audit:** 60 distinct tags emitted == 60 expected; 78 tagged tests; zero untagged, zero dual-tagged, zero tags-not-on-last-line, zero unknown tags, zero stub tags. Citation sweep: all 130 quoted spans verbatim-grep against `workspace/PRD.md` (two initially failed on PRD `**bold**` markers inside the span — fixed by quoting the marker-inclusive text).

**Known DOB contradiction:** the ten `1961-04-12` instances were translated onto the frozen fixtures' default `1961-06-12` scenario (attainment 2026-06; enroll at 2026-05 is the M<T branch → `effective_month == "2026-06"` per PRD §3.2). Every downstream literal (18500 fallback invoice, due 2026-06-30, arrears 950 due 2026-07-05, delinquency ladder, termination end_month 2026-09) reproduces exactly; no coverage-start contradicts the PRD branch formula.

**Deliberate non-assertions (PRD leaves the design space open):**
1. `delinquency_termination_after_third_past_due` — the design's "exactly 3 invoices" depends on intra-cycle issue-vs-terminate ordering the PRD doesn't pin; I assert the three billed months are all `WRITTEN_OFF`, no `ISSUED`/`PAST_DUE` survives, and `enrollments_terminated >= 1`.
2. `beneficiary_create_client_supplied_system_fields_input_ignored` — PRD never pins the initial `version` value; asserted `version != 99` (client value ignored) instead of `== 1`.
3. `withholding_shortfall_triggers_suspension_cascade` — asserted exactly one *arrears* invoice (part PART_D, 950, due 2026-07-05), not total invoice count.
4. `payer_role_employer_size_twenty_boundary` Y-side start month not asserted (in-place basis update vs close+reopen both fit PRD; design itself captures only role/basis).
5. `beneficiary_cannot_create_rate_schedule` — "no row afterwards" is not API-observable (no rate-schedule read endpoint); omitted.

**test_helpers surface:** nothing broken; all composite setups came from the frozen fixtures (`setup_billed_enrollment`, `setup_delinquent_enrollment`, `setup_withholding_shortfall`, `setup_terminated_enrollment_interval`, `setup_relief_case_on_paid_pair`, `setup_beneficiary_with_ma_coverage`, `setup_appeal_under_review`, `setup_final/provisional_determination`, `setup_verified_employer_coverage`).

Orchestrator verification: `pytest --collect-only -q test_suite/` independently re-run → 78 tests collected, 0 errors.

## Step 6: Generate implementation — 2026-10-02T09:20:00.000Z

All 37 scaffold endpoints are mounted exactly (35 under `/medicare` + 2 unprefixed; the 38th rule is Flask's built-in `/static` helper). Implementation complete.

## Summary

**File tree** (all under `.../workspace/implementation/`, 2683 lines total, `python3 -m compileall` clean):

| file | lines | role |
|---|---|---|
| start.sh / requirements.txt | 11 / 1 | guarded-install launcher (`exec python3 app.py`, `PORT` default 10000, `0.0.0.0`) |
| clock.py | 123 | logical clock (default 2026-09-01T00:00:00Z) + calendar-month arithmetic |
| db.py | 89 | in-memory store (14 dicts), id/timestamps/version, `_seq` tie-break; **no seeding** |
| errors.py | 54 | all 36 catalog error ids + pinned HTTP statuses |
| envelope.py / authn.py / validate.py | 43 / 64 / 141 | `meta`/`response_type`/`data` envelope, header auth + ownership, body/pagination validators |
| calcs.py | 106 | attainment, effective-month, SEP window, LEP (round_half_up / round_dime), IRMAA tier + pinned constants |
| domain.py | ~330 | window governance, activation/collection resolution, payer coordination, LEP gap, penalty sync, determination compute, invoice repricing |
| cycle.py | ~220 | monthly cycle in PRD's pinned 8-step order |
| routes_*.py ×12 | ~1400 | one module per domain |

**Constant audit**: every referenced constant has exactly one definition site (grep-verified); every `fail("ERR_...")` call site resolves to the catalog; no unused catalog ids.

**Smoke transcript** (port 52011, self-discovered): unprefixed `POST /_clock/set_current_utc` → 200 with `current_utc`; unauthenticated business call → 401 `ERR_UNAUTHENTICATED`. Happy path: register (DOB 1961-12-14 → attainment 2026-12, IEP [2026-09,2027-03]; DOB 1961-12-01 → 2026-11, first-of-month rule) → publish rates → enroll → cycle activates → invoice. Also verified live: payment guards (422/200/409); 3-strike delinquency → TERMINATED + WRITTEN_OFF; Part B LEP gap 16 → 10% → 1850; Part D gap 2 → round_dime(69)=70; PROVISIONAL→FINAL in-place flip on tax arrival; waterfall shortfall 350 → SUSPENDED + arrears (due +30d) + cascade flip; appeal SoD 403 then APPROVED → SUPERSEDED+replacement, cancel+reissue; relief grant → retro adjust, penalty VOIDED, paid invoice applied 3520→3450, credit_cents 70 (conservation holds); election OCC 412 on stale, AEP last-in-wins, effectivity creates PART_C and terminates PART_D at the election month; employer verify → retroactive SECONDARY (empty interval deleted), end → SEP [anchor+1, anchor+8] + PRIMARY resume.

**Interpretations chosen** (candidate over/under-guard sites for review):
1. **Invoice issuance includes DELINQUENT enrollments** — the literal "DIRECT_BILL only" reading makes the pinned ≥3-PAST_DUE termination unreachable (first past-due flips DIRECT_BILL→DELINQUENT, freezing the count at 1). Resolved toward keeping termination reachable.
2. **Arrears invoices excluded from relief/appeal repricing** — reissuing a 350-cent shortfall at the full corrected premium (27350) fabricates charges; PRD doesn't carve them out explicitly.
3. **Relief filing overlap guard includes CANCELLED rows with open-ended intervals** (literal `[effective_month, null)` reading), though CANCELLED coverage never began.
4. **Relief adjust-path leaves a PENDING enrollment's status unchanged** when its start moves earlier (activation pinned only for creation/cycle paths).
5. **Waiver-only relief reprices all service months** of the part (no "new effective month" exists to cut off at).
6. **`created_at`/`updated_at`/`api_request_timestamp` use the logical clock** ("runs on a logical clock, never wall-clock"), with insertion sequence as tie-break under equal timestamps.
7. **Nested-resource 404 precedes ownership 403** (ownership needs the loaded owner); direct `/beneficiaries/{id}` paths do ownership first per the pipeline.
8. `/end` temporal check follows the state-machine precondition verbatim (`coverage_start <= coverage_end <= clock`; `employment_end <= clock`), not "both ends >= start".
9. Arrangement auto-STOP counts PENDING+ACTIVE billable enrollments as billable; cycle invoice issuance skips when a non-CANCELLED invoice exists for the (part, service_month); `limit` > 100 clamps to 100; `set_current_utc` echoes seconds-precision when microsecond == 0.

One bug was found and fixed during smoke (missing `find_one` import in cycle.py); a stale-listener restart pitfall was hit and resolved by killing exact PIDs only.

Orchestrator verification: implementation/ tree compiles clean (`compileall`); start.sh uses guarded pip install + `exec python3 app.py`.

## Step 7: Test/fix iteration loop — 2026-10-02T09:28:00.000Z

All 8 rounds passed cleanly on the first iteration. The sweep is done — exiting per protocol.

**Summary**

- **Iterations run:** 1 (initial 8-round parallel sweep — no fixes needed)
- **Sweep results:** All 8 rounds report `passed=78, total=78, failed=0, errors=0, skipped=0`. Each round ran ~131s wall time with ~1.66s average per test, consistent with real per-test-server execution (78 test entries per file, all status `passed`). No flakiness signal: zero tests failed in any round, so there was no union set to diagnose.
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** none.
- **Step 8 handoff list:** not applicable — no test-side fixes were made, so no sibling unasserted code paths to flag.
- **Results files on disk:** confirmed — all 8 final-sweep results files remain at `/home/ubuntu/github/CodingPRD/tasks/task_3454_enrollment_periods_late_enrollment_penalties_premium_withholding/workspace/implementation/results.{1..8}.json` (not cleaned up, per the output contract).

Orchestrator verification: (a) all 8 `results.*.json` independently parsed — every round `passed=78, total=78, failed=0, errors=0`; (b) source mtime audit — newest implementation .py is `domain.py` 09:19 (Step 6's own write), newest test_suite .py 08:45 (Step 5b), newest test_helpers .py 08:09 (Step 5a): Step 7's "0 fixes" claim confirmed against the filesystem; the clean sweep is real, not a side effect of post-sweep edits.

## Step 8: Finalize PRD — SKIPPED — 2026-10-02T09:29:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes (verified above). `PRD.md` already determined every behavior the implementation exhibits; no subagent spawned, no PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-10-02T09:51:00.000Z

All work is complete. Final summary:

## Step 9 outcome — task_3454

**Files**: `workspace/PRD.md` (359 lines / 61,961 chars) → `workspace/PRD_COMPLETED.md` (361 lines / 65,867 chars; +2 lines, +3,906 chars). One implementation file touched: `workspace/implementation/routes_enrollments.py`. Post-fix sweep evidence: `workspace/implementation/results.9.json` — **78/78 passed, 0 failed** (per-test-server isolation), plus a manual smoke test of the changed path on a dynamically allocated port.

**Counts**: 16 ambiguity-pin edits, 2 mismatch revisions (PRD-side, both with direction-rule exceptions), 1 implementation fix.

### Mismatch revisions (PRD-side)
- **§3.7 Invoicing — revise — mismatch — "for each `ACTIVE` enrollment in `DIRECT_BILL`" → "in `DIRECT_BILL` or `DELINQUENT`"** — `cycle.py:171-174`. Exception (jointly unimplementable as written): PRD also states "The first `PAST_DUE` invoice on an enrollment flips its collection status from `DIRECT_BILL` to `DELINQUENT`" and "Once an enrollment carries three or more `PAST_DUE` invoices, the enrollment itself is terminated." Under a DIRECT_BILL-only reading the past-due count caps at 2 (billing stops the moment the first invoice flips the enrollment to DELINQUENT), making the pinned ≥3 termination clause unreachable. The test fixtures (`setup_terminated_by_delinquency`) rely on DELINQUENT billing.
- **§5 catalogue — revise — mismatch — "every error identifier" → "every domain error identifier", with transport-level `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` named** — `app.py:44-56`. Exception (unimplementable as written): any HTTP server must answer undefined routes/methods and crashes with something; the three transport ids cannot be removed from the implementation.

### Implementation fix
- **`routes_enrollments.py:101` — added `maybe_stop_arrangement(ent["beneficiary_id"])` to the PENDING-cancel branch** — PRD: "When the beneficiary's last billable enrollment terminates, the arrangement — whether `ACTIVE` or `SUSPENDED` — moves to `STOPPED`, its terminal state." combined with §3.2 "terminating a `PENDING` enrollment moves it to `CANCELLED`". With the impl's own billable definition (PENDING+ACTIVE PART_B/D, site 9a), cancelling the last PENDING billable enrollment is a PRD-required trigger the impl omitted. No exception applies. Smoke-verified both directions (STOPPED when last billable cancelled; ACTIVE retained while a PENDING PART_D remains); full suite still 78/78.

### Ambiguity pins (one bullet each)
- §2.3 — insert — `limit` >100 clamps to 100; `limit`<1 / non-integer / negative-or-non-integer `offset` → `ERR_VALIDATION` — `validate.py:111-135`.
- §2.3 — insert — created_at ties break by creation (insertion) order — `db.py:87-89`.
- §2.4 — insert — `current_utc` echoes at seconds precision on whole-second instants, three fractional digits otherwise — `clock.py:43-47`, `routes_platform.py:24`.
- §2.5 — insert — `created_at`/`updated_at`/`api_request_timestamp` are logical-clock readings — `db.py:40,55`, `envelope.py:20`.
- §2.8 item 5 — insert — sub-resource paths (and body-identified resources like `premium_determination_id`) run existence-404 before ownership-403 (ownership requires the loaded row); `/medicare/beneficiaries/{id}`-anchored paths run ownership first — `routes_beneficiaries.py:16-22` vs `_load_enrollment`/`_load_record`/`_load_determination`/`_load_appeal`/`pay_invoice`/`file_appeal`.
- §3.1 — insert — opening PayerCoordinationRecord starts at the registration clock month, open-ended — `routes_beneficiaries.py:50-56`.
- §3.3 — revise — interval splits on a (role, basis) *combination* change, including basis-only — `domain.py:163-182`, `cycle.py:198-204`.
- §3.3 — insert — the end-cascade recomputes the role as of `coverage_end_month`+1; with other qualifying coverage remaining, the open interval continues unchanged — `routes_employer.py:163-167`.
- §3.4 — revise — credit comes from prior *non-`CANCELLED`* same-part enrollments (CANCELLED coverage never began) — `domain.py:198-207`.
- §3.7 — insert — an unpriceable part (no determination, no RateSchedule) counts as zero due in the waterfall and never shortfalls — `cycle.py:58-59,66-71`.
- §3.7 — revise — "last billable enrollment" pinned as a `PART_B`/`PART_D` enrollment in `PENDING` or `ACTIVE` status — `domain.py:103-114`.
- §3.7 — insert — issuance is idempotent per (beneficiary, part, service month): skipped when any non-`CANCELLED` invoice already exists — `cycle.py:175-182`.
- §3.6 — revise — appeal repricing scope pinned: non-arrears invoices of the appealed part whose `service_month` lies in the appealed coverage year, repriced to the replacement's `total_premium_cents`; `tax_year_used` carried over — `routes_appeals.py:93-117`.
- §3.9 — insert — filing guard reads a `CANCELLED` row's null `end_month` as open-ended — `routes_relief.py:52-61`.
- §3.9 — insert — adjust-path moves only `effective_month` (PENDING stays PENDING until the next cycle; collection untouched); recompute creates an ACTIVE assessment when none exists and the penalty is non-zero — `routes_relief.py:97-119`, `domain.py:252-260`.
- §3.9 — revise — pure `PENALTY_WAIVER` reprices every service month of the part; corrected amount = the §3.7 invoice rules post-cascade; replacement keeps the original `due_date`; arrears invoices are never repriced — `routes_relief.py:150-152`, `domain.py:363-421`.

### Per-edit search log (subject → impl paths enumerated → wording)
- Pagination clamp → `validate.py:111-135` + `envelope.success_list` meta echo → "clamped to 100 rather than rejected" matches post-clamp meta.
- Ordering tie-break → `db.sort_entities` (only sorter; used by all 13 list endpoints) → "creation (insertion) order".
- Clock echo → `format_clock_reading`, sole caller `set_clock` → seconds/millis conditional.
- Logical-clock timestamps → `db.make_entity`, `db.touch`, `envelope._meta` (all `format_ts(now())`) → single sentence in §2.5.
- 404-before-ownership → enumerated every loader: `_require_beneficiary` (ownership-first), `_load_enrollment`, `_load_record(ownership=True)`, `_load_determination`, `_load_appeal(ownership=True)`, `pay_invoice`, `file_appeal`, and all 12 `/beneficiaries/{id}/*` list handlers (ownership-first) → wording scoped to "ownership can only be evaluated by loading it".
- Opening payer interval → `create_beneficiary` only → start = registration clock month.
- (Role,basis) pair → `apply_payer_role_change` early-return + cycle step-7 condition → both compare pair; wording widened from "role".
- End-cascade recompute → `end_employer_coverage` (recomputes at resume month) → added conditioning sentence, canonical outcome kept.
- CANCELLED credit → `lep_gap_months` enrollment filter → "non-`CANCELLED`".
- Waterfall zero-due → `_withholding_waterfall` (`None→0`) → "counts as zero due and never shortfalls".
- Billable definition → `maybe_stop_arrangement` (PENDING+ACTIVE) vs `adjust_arrangement` (ACTIVE-only, already PRD-pinned) → wording scoped to the stop sentence only.
- Issuance idempotency → cycle step-3 `find_one` non-CANCELLED skip → pinned including that WRITTEN_OFF/PAID also block reissue.
- Appeal scope → `affected()`/`amount_for` closures in `adjudicate_appeal` → part × coverage year at replacement total.
- Relief guard CANCELLED → `_FAR_FUTURE` substitution → "reads as open-ended".
- Adjust-path status → stage-1 `if ent:` branch (only `effective_month` + `touch`) → explicit no-status-change sentence.
- Stage-four pins → `reprice_invoices` (arrears filter, due_date carry, `min()` cap) + `reprice_beneficiary_part_invoices` (None cutoff) → widened wording covers both relief and appeal callers.

### Verdicts on the 9 self-reported sites
1. DELINQUENT invoicing — confirmed in code; pinned via mismatch revision (exception above).
2. Arrears excluded from repricing — confirmed (`domain.py:377`); pinned as-is.
3. CANCELLED open-ended in relief guard — confirmed (`routes_relief.py:58`); pinned as-is.
4. Adjust-path leaves PENDING status unchanged — confirmed (`routes_relief.py:98-104`); pinned as-is.
5. Waiver-only reprices all service months — confirmed (cutoff `None`); pinned as-is.
6. Logical-clock timestamps + insertion tie-break — confirmed; pinned as-is.
7. Nested 404 precedes ownership; `/beneficiaries/{id}` paths ownership-first — confirmed across all loaders; pinned as-is.
8. Employer `/end` temporal check (start ≤ coverage_end ≤ clock, employment_end ≤ clock) — **already pinned verbatim in PRD §3.3; code matches; no edit needed**.
9. All four sub-items confirmed (PENDING+ACTIVE billable; non-CANCELLED skip; limit clamp; seconds-precision echo); each pinned.

Orchestrator verification: (a) `diff -q` confirms PRD_COMPLETED.md is not byte-identical to PRD.md (359 → 361 lines, +3,906 chars) — not a killed-mid-flight no-op; (b) `routes_enrollments.py` mtime 09:44 (post-Step-7) with `maybe_stop_arrangement` present in the PENDING-cancel branch; (c) subagent's post-fix single-round `results.9.json` = 78/78.

## Final sweep regeneration (post-Step-9 impl fix) — 2026-10-02T09:55:00.000Z

Step 9's `implementation/` fix invalidated Step 7's results.1–8 as final evidence (they ran against the pre-fix build). Orchestrator re-ran the full 8-round parallel sweep (`prd-bench-local-run --isolation per-test-server`, 8 concurrent rounds joined with `wait`, ~132s wall) against the current implementation and regenerated `workspace/implementation/results.{1..8}.json`. Independent parse of all 8 files: **every round passed=78, total=78, failed=0, errors=0 — ALL_PASS**. The results files now on disk are valid final evidence for the shipped implementation. (`results.9.json` retained as Step 9's single-round post-fix evidence.)
