# Worklog — task_3453_retirement_benefit_claims_earnings_record_correction_spousal

## Step 1: Create Task Directory — 2026-10-02T06:30:00.000Z

Task directory pre-allocated by the caller: `./tasks/task_3453_retirement_benefit_claims_earnings_record_correction_spousal/` with `workspace/` inside. Verified it exists; no new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-02T07:41:00.000Z

All three scaffold artifacts are complete, machine-linted clean, and self-audited.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3453_retirement_benefit_claims_earnings_record_correction_spousal/`):
- `SCAFFOLD.yaml` (950 lines) — §1.0–§1.7, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2696 lines) — single `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` (3558 lines) — single `scaffold_corner_design:` key

**Counts:**
- **Entities: 10** — Worker, EarningsYear, WageReport (append-only, `common_fields: false`), CorrectionRequest, Relationship (self-referential Worker↔Worker), BenefitClaim, BenefitPayment, OverpaymentCase, PayeeCase, RecomputationEvent
- **Endpoints: 39** — 37 business endpoints under `/ssa` plus unprefixed `/_clock/set_current_utc` (fixed default 2026-09-01T00:00:00Z) and `/_batch/run-monthly-cycle` (pinned 5-step processing order, idempotent re-run)
- **State machines: 7**, four non-linear — BenefitClaim (DENIED→FILED reopen loop, ENTITLED↔SUSPENDED DRC cycle), CorrectionRequest (evidence loop + denial-reopen loop), OverpaymentCase (waiver branch), PayeeCase; plus Worker death and BenefitPayment repayment
- **Calculations: 11** — indexation (AWI series formula), AIME top-35, bend-point PIA, WEP variant with 50%-pension guarantee, age adjustment (5/9‰ vs 5/12‰ kink + monthly DRC), spousal/dual-entitlement/GPO with pinned 4-step evaluation order, survivor reduction, family-maximum waterfall with per-line dime reconciliation, dual-variant overpayment withholding (chronological vs proportional), January COLA, recomputation delta
- **Validations: 30** ordered rows (auth → existence → shape → state → OCC → segregation/safety → constraint → temporal → referential → fiscal); **Errors: 35** (all exercised); **Roles: 5** in a segregation-of-duties model; **OCC concurrency rules: 3** (suspend, waiver, pension PATCH)
- **§1.8 instances: 20** — every rule with ≥2; rule 2 covers all three modes (a/b/c), rule 6 has three boundaries (age-744 inclusive, 12-month withdrawal, GPO exact-zero-to-the-cent)
- **§1.9 instances: 69** — 56 active + 13 `excluded_because:` stubs, across all nine taxonomy sections

**Verification performed:** `scaffold_lint.py` verdict: **clean lint** (723 recipe calls scanned, 0 violations, all FKs reverse-reachable). Every formula-derived assert literal (PIA 111740, WEP 5560, DRC resume 24220, family-max shares 4120/6320, dual-entitlement 2640, retro deltas ±3150/−4400, GPO boundary 0-vs-10, COLA 8960, etc.) was pre-computed by executing the pinned formulas in exact rational arithmetic before writing. Grounds-resolution audit over all 89 instances: zero dangling references. Forbidden concurrency vocabulary: absent. Enum closure: every declared status/enum value has a producing transition, and previously gap-prone values (WAIVED, PayeeCase DENIED, OVERPAYMENT_CREATED resolution, PARTIAL mode) each got a dedicated corner instance.

Orchestrator verification: all three YAMLs parse with yaml.safe_load; SCAFFOLD.yaml top-level keys are [scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules]; api_prefix is `/ssa`; entity list matches the SSA domain (Worker, EarningsYear, WageReport, CorrectionRequest, Relationship, BenefitClaim, BenefitPayment, OverpaymentCase, PayeeCase, RecomputationEvent).

## Step 3: Copy Shared Files — 2026-10-02T07:44:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T08:12:00.000Z

All verification passes are clean. The PRD is complete and shipped.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3453_retirement_benefit_claims_earnings_record_correction_spousal/workspace/PRD.md` — 327 lines. The two forbidden design-index files were never opened or referenced.

**Section list**:
- §1 Introduction (2 paragraphs, business-context angle)
- §2.1 User and Role-Based Access Control (5 roles, per-role `identity` prose: Claimant entity-backed vs 4 opaque)
- §2.2 API Response Structure (verified **byte-identical** to the canonical block)
- §2.3 Pagination (limit 10/1/100, offset 0, created_at ascending)
- §2.4 The Logical Clock and All Timekeeping (startup default 2026-09-01T00:00:00Z, never wall-clock)
- §2.5 Money, Cents, and the Dime-Floor Rounding Discipline
- §2.6 Common Resource Properties (WageReport/RecomputationEvent carry only `id`+`created_at` — stated explicitly)
- §2.7 Optimistic Concurrency Control (all 3 rules, stale-view framing only)
- §2.8 Cascading Consistency and the Audit Trail
- §2.9 Rejection Order and Segregation of Duties (all 12 validation priority layers in prose)
- §2.10 The Monthly Benefit Cycle at a Glance
- §2.11 Nested Resource Retrieval
- §3.1–§3.9 Business Logic (earnings ledger, corrections, relationships, adjudication, benefit computation, withdrawal/suspension, monthly cycle, overpayments, payees/death)
- §4 Endpoint Definitions — 39/39 rows, 4 columns
- §5 Error Code Catalogue — 35/35 rows, 2 columns; document ends here, no audit footer

**Hard Contract reports**:
```
Field coverage check:
- entities[].fields: 70 required, 70 present, 0 missing
- endpoints[].request_body: 44 required, 44 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing
- batch/clock/common identifiers (run_month, already_run, current_utc, id, version, ...): 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 30 checked, 30 expressed (12 ordered rejection layers in §2.9 + trigger narratives in §3)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_*_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 28 checked, 28 fully expressed (from→to, preconditions paired with error ids, side effects incl. all cascade hops), 0 missing
- calculations[]: 11 checked, 11 fully expressed as reconstruction-safe prose (verified literals: bend points, AWI/taxable-max/substantial series, 5/900, 25/3600, 1/150, 2/3, 1.025, family-max rates, per-auxiliary-first rounding order), 0 missing
- validations[] conditions: 30 checked, 30 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 39 checked, 39 expressed, 0 missing
- entities[].fields[] structured content: 70 checked, 70 reconstructible (defaults, ranges, enum sets all stated), 0 missing
- sibling-branch symmetry: 7 groups checked (OCC rules, waiver/payee outcomes, claim-type gates, recovery modes, expiry states, COLA inclusion, indexation bands), 7 with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 452
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage confirmation**: every scaffold rule is covered in PRD prose — all 10 entities (all 70 fields verbatim in backticks), all 7 state machines (28 transitions with preconditions, error ids, and cascade side effects), all 11 calculations (formulas translated to precise natural language with constants embedded, e.g. "$120,000 for 1986 growing $3,000/year"), all 30 validation rules in priority order, all 35 error ids with HTTP statuses, all 5 roles with identity semantics, all 39 endpoints, and all 3 OCC rules. Operator-syntax scan found zero pseudocode, fuzzy words, or race framing.

Orchestrator spot-check: PRD.md is 327 lines; 56 hits across bend point/windfall/WEP/GPO/delayed retirement/spousal/survivor/overpayment/payee; 35 distinct `ERR_*` tokens — matches the scaffold's 35-error catalogue.

## Step 5: Generate Unit Tests — 2026-10-02T09:05:00.000Z

All audits pass. The work is complete.

## Summary

**Inputs read:** SKILL.md, SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml (9 rules, 20 instances), SCAFFOLD_CORNER_DESIGN.yaml (8 sections, 69 instances: 56 active + 13 `excluded_because` stubs), PRD.md (327 lines). Every numeric literal was re-derived from PRD §3.1/§3.5 formulas before use (AWI series, taxable max, bend points, AIME/PIA/WEP, age factors, DRC, spousal/survivor, family maximum, COLA 2.5%, withholding waterfalls, retro deltas).

**test_helpers/ (Phase A, 9 files):** `types.py` (18 enums, 10 TypedDicts — WageReport/RecomputationEvent correctly omit `updated_at`/`version` per PRD §2.6), `api_client.py` (39 endpoint methods; `/​_clock` and `/_batch` unprefixed per PRD §4), `api_errors.py` (35 error IDs + status map registered), `assertions.py`, `factories.py`, `constants.py` (verified: AWI 2021–23 = 1875000/1900000/1925000, cap(2023) = 23100000, bends(2026) = 103000/618000), `test_users.py` (entity-backed `make_claimant_headers(worker_id)` + named operator builders for segregation-of-duties tests), `fixtures.py`, `__init__.py`.

**test_suite/ (Phase B, 22 files, 96 tests):** test_01 (4) worker intake/envelope · test_02 (3) wage reports · test_03 (5) claim filing/listing · test_04 (5) RBAC · test_05 (8) corrections · test_06 (4) relationships · test_07 (6) claim state machine · test_08 (6) AIME/PIA/WEP · test_09 (5) age boundaries/survivor · test_10 (4) spousal gates · test_11 (4) dual entitlement/family max · test_12 (2) GPO boundary · test_13 (4) suspend/resume · test_14 (4) withdrawal rules · test_15 (4) withdrawal invariants · test_16 (6) waivers · test_17 (6) recovery withholding · test_18 (5) recomputation · test_19 (5) death/payee · test_20 (2) batch/COLA · test_21 (3) OCC · test_22 (1) 404 catalog.

**Audits:**
- AST tag walk: 96 tests, 96 `Design:` tags (each docstring's last line, exactly one), covering all 76 active instances — 20 Difficulty instances × ≥2 tests, 56 Corner instances × ≥1. Missing: none. Extra: none. Stub-tagged: none. All 13 stub cross-references resolve to real difficulty instances and were not translated.
- `pytest --collect-only`: **96 collected, 0 errors.**
- Verbatim PRD-citation check: 137 citation chunks, **0 failures** (two real C3 elisions fixed: §2.9 layer-4 and the WEP passage; six truncated §2.9 layer-6 quotes expanded to the full sentence).
- File discipline: largest test file 261 lines, largest helper 271 — all well under the cap. No skip/xfail markers. Suite never executed against a server.

**Design-index corrections (no instance skipped):** `gpo_offset_exactly_cancels_spousal_excess` was arithmetically unreachable as written — sb's marriage (1990→1999 = 108 months) violates the 120-month DIVORCED_SPOUSAL floor (PRD §3.4), and two 10,440 excesses plus the worker's own 14,610 exceed FMAX 31,320 (PRD §3.5), so the excess would never be 10,440. Fixture re-derived preserving the instance's asserted boundary semantics: each spouse rides a separate covered worker (family max never binds) and sb's divorce moved to 2000-01-01 (exactly 120 months). Asserted values unchanged: pension 15,660 → offset 10,440 → monthly 0 with PENSION_UPDATED event; pension 15,659 → monthly 10. All other instances' worked numbers cross-checked exact against PRD formulas.

Orchestrator verification: 96 `def test_` across 22 test_suite files; 76 unique `Design:` tags (= 20 §1.8 + 56 §1.9 active instances); `pytest --collect-only` collects 96 with 0 errors.

## Step 6: Generate Implementation — 2026-10-02T09:48:00.000Z

Everything is verified. Here is the final report.

## Summary

Complete Python + Flask implementation for task_3453 (SSA retirement benefit claims) written to `/home/ubuntu/github/CodingPRD/tasks/task_3453_retirement_benefit_claims_earnings_record_correction_spousal/workspace/implementation/`, from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md only (test_suite/, test_helpers/, and the design YAMLs were never opened).

### File tree (per-file line counts; 3,058 total)

```
implementation/
├── start.sh                 (9)    guarded pip install + exec python3 app.py, $PORT/0.0.0.0/foreground
├── requirements.txt         (1)    flask>=3.0
├── app.py                   (68)   bootstrap, blueprint registration, envelope-shaped error handlers
├── db.py                    (91)   empty in-memory store, logical clock (default 2026-09-01T00:00:00Z), id/seq/timestamp helpers
├── errors.py                (99)   all 35 error IDs with exact HTTP statuses, ApiError
├── envelope.py              (87)   meta/response_type/data envelope, error body, limit/offset pagination (clamped 1..100)
├── security.py              (75)   X-User-ID/X-User-Role auth, 5 roles, Claimant entity-backed ownership
├── validation.py           (126)   layer-4 body well-formedness (bool never accepted as int)
├── timeutil.py             (104)   YYYY-MM / YYYY-MM-DD / ISO-8601 math, whole-month differences, statute deadline
├── calc.py                 (211)   CALCULATIONS: AWI/taxable-max/bend-point/substantial series, dime_floor,
│                                   round-half-up indexation, AIME top-35, PIA bend points, WEP (tier-1 factor +
│                                   guarantee cap), age adjustment (5/900 vs 5/1200 kink, 1/150 DRC), spousal
│                                   base/reduction, survivor factor, GPO, family maximum, COLA — all Fraction-exact
├── benefits.py             (232)   spousal 4-step pinned order, family-maximum waterfall (per-claim dime_floor
│                                   first, residual dimes in created_at ASC), recompute_claim with retro-delta
│                                   settlement (underpayment credit / auto OverpaymentCase "system"), resume+DRC
├── batch.py                (213)   5 pinned phases: Jan COLA → auto-resume@840 → payment generation (family-max
│                                   re-eval, FULL/PARTIAL/PROPORTIONAL withholding waterfall, credit drain,
│                                   WITHHELD_FULL, paid_to routing) → correction sweep → auto begin-recovery;
│                                   idempotent via ran_months
├── serializers.py          (218)   per-entity dicts; computed-on-read: age_months, indexed_earnings_cents,
│                                   marriage_months, total_paid_cents, remaining_cents (WAIVED → 0)
├── routes_workers.py       (214)   intake, read, OCC pension PATCH (+WEP/GPO recompute), report-death cascade, 4 lists
├── routes_wages.py         (102)   wage posting with created_at-ordered taxable-max headroom, EarningsYear upsert
├── routes_corrections.py   (252)   file/evidence/approve(+3-hop cascade)/deny/reopen, statute + 60-day windows
├── routes_relationships.py (144)   assert/verify/reject, half-open interval-overlap exclusivity, WIDOW-needs-death
├── routes_claims.py        (382)   file, approve (all per-type gates in §2.9 order), deny, reopen, withdraw, suspend, resume
├── routes_claim_reads.py    (95)   GET /ssa/claims (filters + Claimant scoping) + 4 claim sub-resource lists
├── routes_overpayments.py  (173)   open, request-waiver (OCC, 30-day), decide-waiver (SoD), begin-recovery (mode election, 10% floor)
├── routes_payees.py        (110)   open on ENTITLED, decide (SoD, capacity-1 ACTIVE)
└── routes_platform.py       (44)   POST /_clock/set_current_utc and /_batch/run-monthly-cycle — UNPREFIXED per §1.5
```

### Endpoint count
39 registered, matching the scaffold table 1:1 (37 under `/ssa` + the 2 unprefixed platform endpoints). Verified by enumerating `app.url_map`.

### py_compile
`python3 -m py_compile *.py` → COMPILE OK over all 20 modules. No `float()` anywhere; no seeding/preloading (store provably empty at boot — smoke test creates everything via the API).

### Self-smoke-test (my own, no test suite) — 101/101 PASS across two runs
Dynamic free port per run, server killed by saved PID only. Transcript highlights (all hand-derived expectations matched the server exactly):
- Auth: no headers → 401 ERR_UNAUTHENTICATED; Employer on worker intake → 403 ERR_UNAUTHORIZED_ROLE; Claimant on foreign worker → 403 ERR_FORBIDDEN_OWNERSHIP.
- Worker 1960-01 + wages 2019/2020/2021/2024 @ $60k: indexed 2019 = 6,082,192 (round-half-up), AIME 57,300, PIA 51,570, monthly 36,090 (n_early 60 → factor 0.7), reduction_months 60.
- Batch 2026-09 → 1 payment net 36,090; re-run → already_run=true.
- Correction 2024→$80k approved: monthly 39,120, underpayment credit 3,030, event CORRECTION_APPROVED/UNDERPAYMENT_CREDIT; October batch payment net 42,150 (credit drained).
- Suspend: stale version → 412 ERR_STALE_VERSION; correct OCC → 200; batch skips SUSPENDED (Nov payments=1 for the other claim only); resume after 4 months → drc_months 4, monthly 60,980, event SUSPENSION_RESUME/NONE.
- Withdraw: late → 422 ERR_WITHDRAWAL_WINDOW_EXPIRED; shortfall → 422 ERR_REPAYMENT_SHORTFALL; repaid==total → 200 WITHDRAWN, withdrawal_used=true, approve-on-terminal → 409 ERR_CLAIM_ALREADY_TERMINAL, re-file → 201.
- Spousal: covered PIA 81,030 → spouse monthly 35,440 (0.5×PIA, 18 early months × 25/3600, hand-verified); payee approve with same operator → 409 ERR_SAME_ADJUDICATOR, then ACTIVE + payments routed REPRESENTATIVE_PAYEE.
- Overpayment: early begin-recovery → 422 ERR_WAIVER_WINDOW_OPEN; waiver OCC → 200; same-creator waiver decision → 409; DENIED → RECOVERY_ACTIVE; next batch withheld 35,440 (FULL), payment WITHHELD_FULL net 0.
- Death cascade: claims ENTITLED→TERMINATED; double report → 409.
- WEP: pension $200/mo, YOC 2 → tier-1 floor 0.40, guarantee cap 10,000 → PIA 15,830; PATCH pension→0 with OCC → PIA 25,830, monthly 18,080, event PENSION_UPDATED; missing start_month → 400; Claimant PATCH → 403.

### Interpretations chosen (PRD ambiguities)
1. **Claim-approve check order** follows PRD §2.9's pinned layers (temporal→referential→fiscal), not the scaffold transition's precondition list order: divorce-wait(10) → relationship-verified/spouse-entitled/worker-deceased(11) → age bounds → marriage duration(12); RETIREMENT-on-deceased at approve is layer 8 (ERR_WORKER_DECEASED 409).
2. **Correction-reopen order**: state → SoD(8) → statute(10) → 60-day window(10), per §2.9's temporal listing (statute named before reopen window), overriding the scaffold's per-transition list.
3. **Withdrawal order**: window(10) → repayment-equality(12) → once-per-lifetime(12), per §2.9's fiscal-layer listing.
4. **Non-covered wage reports** post their full amount (posted_amount_cents = amount_cents) and do not consume taxable-maximum headroom — the cap is a covered-earnings concept; noncovered is informational-only.
5. **Corrected EarningsYear rows are not sticky**: a later wage report recomputes posted_earnings_cents from the report set (scaffold defines the field as a pure function of reports; "overwritten by an APPROVED correction" read as an event, not a lock).
6. **Ownership vs existence**: worker-path endpoints compare Claimant X-User-ID to the path id before loading (403 before 404, pure string compare); entity-scoped endpoints load first (404 when the entity doesn't exist, 403 on mismatch when it does) — strict layer order is unsatisfiable when ownership needs the entity.
7. **RecomputationEvent appended on every recomputation run** (correction approve / pension PATCH / resume), even when delta is 0 (resolution NONE) — per the cascade's unconditional "append a RecomputationEvent" language.
8. **Auxiliary claims carry covered-worker PIA context**: aime_cents/pia_cents on SPOUSAL/DIVORCED_SPOUSAL/SURVIVOR claims hold the covered worker's AIME/PIA (per the aime_cents field note).
9. **SUSPENDED auxiliary claims** recompute standalone (excess−GPO, no family pool) since family_maximum's input set is ENTITLED auxiliaries only; ENTITLED auxiliaries go through the pool.
10. **Family-max residual** distributes uncapped dimes one per claim per pass in created_at ASC (PRD-literal; pool < sum_aux keeps shares below pre-reduction amounts in practice). Pool is floored at 0 if the worker's own benefit alone exceeds FMAX.
11. **Auto begin-recovery window**: case auto-starts when created_at+30d < first day of run_month ("lapsed before the run month"), and sets claim.recovery_mode=FULL.
12. **Correction sweep in batch uses the logical clock date** (PRD phase-4 text), not run_month; **death_date in the future** → ERR_INVALID_REQUEST (no specific error assigned by the spec).
13. **PARTIAL rate storage**: monthly_rate_cents is stored on the case that elected it ("case's elected rate" in the withholding formula) and mirrored on the claim as fallback for cases that never elected PARTIAL themselves.
14. **report-death clears suspended_since** on terminated suspended claims (they "stop accruing DRCs"; the field is null unless SUSPENDED).
15. **Claimant GET /ssa/claims** is scoped to own claims; an explicit foreign worker_id filter → 403.
16. **Pagination out-of-range** clamps to [1,100]/[0,∞); unparseable limit/offset falls back to defaults (no error ID exists for query-param issues).

Orchestrator spot-check: all 20 .py modules present and compile clean (`py_compile` COMPILE_OK); start.sh is $PORT/0.0.0.0/foreground with guarded pip install; no `float(` in any module.

## Step 7: Run Tests and Iterate — 2026-10-02T10:20:00.000Z

All 8 rounds pass 96/96. The sweep is clean and the results files remain in place as required output artifacts.

## Summary

- **Iterations run:** 2 (initial sweep surfaced 5 deterministic failures; re-sweep after one fix is clean across all 8 rounds, no flakiness).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_3453_retirement_benefit_claims_earnings_record_correction_spousal/workspace/implementation/db.py` — `new_id()`: changed `uuid.uuid4().hex` to `str(uuid.uuid4())` so entity ids are emitted in canonical hyphenated UUID form. PRD §2.6 states "The `id` is a server-minted UUID with no type prefix"; the shared benchmark helper `is_valid_uuid` (used by `test_helpers/assertions.py`) requires the standard 8-4-4-4-12 hyphenated representation, and the 32-char unhyphenated hex the implementation emitted is not the canonical UUID string form. This single fix resolved all 5 failing tests (`test_worker_create_defaults_and_computed_fields`, `test_response_envelope_shape_on_success_and_error`, `test_wage_report_taxable_max_chronological_cap`, `test_wage_report_immutable_common_fields_absent`, `test_evidence_request_loop_returns_to_pending_review`), all of which tripped the same `id must be a bare UUID` assertion.

Orchestrator verification: all 8 `results.${i}.json` present, each passed=96 total=96 failed=0; newest source file (db.py) mtime 1790935210 < oldest results file (results.3.json) mtime 1790935391 — the clean sweep postdates the last implementation edit, so the evidence is valid.

## Step 8: Finalize PRD — 2026-10-02T10:07:00.000Z

Done. **Zero-edit outcome: PRD_FINALIZED.md is byte-identical to PRD.md** (verified with `diff -q` → IDENTICAL).

## Summary

- **Line counts / %-delta:** PRD.md 327 lines → PRD_FINALIZED.md 327 lines, 0% delta, byte-identical.
- **Changes:** none.

## Adjudication of the single Step 7 item (candidate edit, not committed)

The `<step_7_diff>` contained exactly one implementation fix and nothing else. Per the step's own escape hatch, I evaluated whether it was a PRD silence or a pure impl bug:

- **(a) Subject identified:** format of server-minted entity `id` values (PRD §2.6, line 95: "The `id` is a server-minted UUID with no type prefix").
- **(b) Impl paths enumerated and read/grepped:**
  - `workspace/implementation/db.py:62-63` — `new_id()` returns `str(uuid.uuid4())`; this is the **only** id-minting site (repo-wide `grep -rn "uuid" implementation/*.py` hits only `db.py:12` import and `db.py:63`).
  - All 16 other implementation modules grepped for uuid/UUID — no other file validates, formats, or transforms ids; path-parameter ids are consumed as opaque lookup keys, so no off-site path contradicts §2.6.
  - PRD-wide grep for any other id-format language (lines 86-302 scanned: monetary/rounding, version-field scoping, wage-report fields, `ERR_*_NOT_FOUND` catalog) — §2.6 is the sole statement about id form; nothing else to keep consistent.
  - Final sweep evidence `implementation/results.8.json`: 96/96 passed, confirming the post-fix implementation is the aligned target.
- **(c) Wording adjustment:** none committed. "UUID" per RFC 4122 has exactly one canonical string representation — the 8-4-4-4-12 hyphenated form that `str(uuid.uuid4())` produces; Python's `.hex` is explicitly a 32-char hex *encoding*, not the UUID string form. §2.6 therefore already uniquely determines the current implementation's behavior, and the Step 7 note itself frames the pre-fix code as violating the canonical form (not as choosing among PRD-licensed options). This was a pure implementation bug, so no PRD edit was warranted — manufacturing one was explicitly prohibited.

**Deliverable:** `workspace/PRD_FINALIZED.md` (byte-identical copy of PRD.md).

Orchestrator verification: `diff -q PRD.md PRD_FINALIZED.md` confirms byte-identical (60005 bytes each); zero-edit outcome independently confirmed.

## Step 9: Complete PRD — 2026-10-02T10:37:00.000Z

Done. The verification confirms 20 changed lines, all in-paragraph edits (line count unchanged at 327).

## Summary

**Source vs output**: `PRD_FINALIZED.md` 327 lines / 60,005 chars → `PRD_COMPLETED.md` 327 lines / 64,198 chars. Char delta **+4,193**. `diff -q`: files differ (real delta, not a no-op).

**Counts**: 19 ambiguity-pins, 1 mismatch-revision (20 hunks total, all in-paragraph; no new sections).

### Changes (one bullet each)

- §2.2 — insert — ambiguity — `api_request_timestamp` is issuance time, not drawn from the logical clock — implementation/envelope.py:24-33
- §2.3 — insert — ambiguity — limit/offset clamped to bounds (unparseable → defaults); created_at ties broken in insertion order — implementation/envelope.py:68-87, db.py:89-91
- §2.4 — insert — ambiguity — clock set accepts any instant, including backward; no monotonicity guard — implementation/routes_platform.py:19-29
- §2.6 — insert — ambiguity — `version` starts at 1; `evidence_note`/`evidence_detail`/`rejection_reason`/`reopen_reason` are validated on intake but never retained or serialized — implementation/db.py:78, routes_corrections.py:131,147,235, routes_relationships.py:139, routes_claims.py:290
- §2.9 — insert — ambiguity — nested-path ownership runs after parent resolution (per §2.11); worker-scoped ownership is a pure id match before existence — implementation/routes_workers.py:50-55, routes_claims.py:350-351
- §2.11 — insert — ambiguity — body-carried ids (`worker_id`, `claim_id`, relationship worker pair) resolve to the same 404s after body well-formedness; a claim's stored `relationship_id` resolves at adjudication — implementation/routes_wages.py:79-80, routes_corrections.py:82-83, routes_relationships.py:75-78, routes_overpayments.py:65-66, routes_payees.py:47-49, routes_claims.py:178-184
- §3.1 — revise — ambiguity — wage crediting pinned to acceptance order (== created_at order absent backward clock sets); non-covered reports post full `amount_cents` and consume no covered headroom — implementation/routes_wages.py:81-88
- §3.2 — insert — ambiguity — approval evaluates the statute before the discrepancy re-check (resolves §3.2 prose vs §2.9 layer-list self-contradiction in impl's favor) — implementation/routes_corrections.py:161-168
- §3.4 — insert — ambiguity — claimant claims-listing implicitly scoped to own worker, explicit foreign `worker_id` filter → 403 — implementation/routes_claim_reads.py:49-54
- §3.4 — insert — ambiguity — `claiming_age_months` derived and stored at filing — implementation/routes_claims.py:128
- §3.4 — insert — ambiguity — date→month durations (12-month spousal floor, 24-month divorce wait) measured in whole months to the first day of the named month — implementation/timeutil.py:80-85, routes_claims.py:189,213
- §3.4 — **revise — mismatch** — DIVORCED_SPOUSAL duration measured as 120 whole months `marriage_date`→`divorce_date`, not the clock-dependent tracked `marriage_months` (impl reading is at least as faithful: natural duration of a dissolved marriage, and deterministic) — implementation/routes_claims.py:218-222
- §3.5 — insert — ambiguity — auxiliary claims store the covered worker's PIA/AIME as their own `pia_cents`/`aime_cents` — implementation/routes_claims.py:239-243
- §3.5 — insert — ambiguity — survivor claims likewise store the deceased worker's recomputed PIA/AIME — implementation/routes_claims.py:252-256
- §3.5 — insert — ambiguity — family-max pool = ENTITLED SPOUSAL/DIVORCED_SPOUSAL only (survivors never participate; suspended auxiliaries sit outside storing excess-after-GPO); "worker's own benefit" = their ENTITLED/SUSPENDED RETIREMENT claim's `monthly_benefit_cents`, else zero with hypothetical-PIA maximum; sibling re-pricing bumps `monthly_benefit_cents`/`version` with no recomputation events or retro deltas — implementation/benefits.py:19,68-125, batch.py:154-163
- §3.6 — insert — ambiguity — each resumption reassigns `drc_months` afresh rather than accumulating across cycles — implementation/benefits.py:226
- §3.6 — insert — ambiguity — withdrawal window is one-directional (months from `entitlement_month` to now); future entitlement satisfies it — implementation/routes_claims.py:319-324
- §3.7 — insert — ambiguity — phase-5 "FULL mode" sets the claim-level `recovery_mode` to FULL — implementation/batch.py:199-202
- §3.8 — revise — ambiguity — the notice date is the case's `created_at` (no separate field) — implementation/routes_overpayments.py:51-52
- §3.8 — revise — ambiguity — begin-recovery against WITHDRAWN/TERMINATED claim → `ERR_CLAIM_ALREADY_TERMINAL`, other non-ENTITLED → `ERR_INVALID_STATE`, both before the waiver-window guard — implementation/routes_overpayments.py:144-159
- §3.9 — insert — ambiguity — payee-case opening against terminal claim → `ERR_CLAIM_ALREADY_TERMINAL`, other non-ENTITLED → `ERR_INVALID_STATE`; a denial also stamps `decided_by` — implementation/routes_payees.py:50-55,108
- §4 — insert — ambiguity — unauthenticated `GET /_health` → 200 `{"status":"ok"}`; unknown paths/methods → `ERR_INVALID_REQUEST` (400) — implementation/app.py:45-64

### Flagged as possible IMPLEMENTATION bugs (PRD deliberately left unchanged)

- **F1 — path-vs-body rejection order.** PRD §2.9 unambiguously pins body well-formedness (layer 4) before path resolution (layer 5), and §2.11 claims consistency with that order. The impl resolves path identifiers first on nearly all action endpoints (e.g. routes_claims.py:270-272, routes_corrections.py:129-131, routes_workers.py:102-106): a missing path id plus a malformed body yields 404, where the PRD's order yields 400. Manifests only when two rejections coincide.
- **F2 — ownership-vs-body rejection order.** §2.9 pins ownership (layer 3) before body (layer 4); the three create endpoints validate the body before `claimant_owns` (routes_corrections.py:76-81, routes_relationships.py:60-74, routes_claims.py:88-101): a claimant filing on another worker with a malformed body gets 400 where the PRD yields 403. Same multi-failure-corner scope. (Note withdraw/suspend/resume do ownership first, so the impl is internally inconsistent here.)

### Evidence — modules walked (all 20, each read in full)

app.py, batch.py, benefits.py, calc.py, db.py, envelope.py, errors.py, routes_claim_reads.py, routes_claims.py, routes_corrections.py, routes_overpayments.py, routes_payees.py, routes_platform.py, routes_relationships.py, routes_wages.py, routes_workers.py, security.py, serializers.py, timeutil.py, validation.py (plus INSTRUCTION.md).

Spot-checked and found conformant (no edit): every endpoint's role set vs the §4 table; 201-vs-200 discipline; all §3.5/§2.5 arithmetic (AIME, bend points, WEP tier/guarantee, DRC 1/150, spousal 25/3600, survivor 0.5%, GPO 2/3, family max 150/272/134, COLA 2.5%, dime-floor placement); OCC guard fields and layer order on the three guarded writes; retro-delta sign/period/`created_by` "system"; both withholding waterfalls incl. residual-dime rules; five-phase batch order, idempotency ledger, and run-report fields; death-report cascade scope; all ten serializer field shapes; statute/reopen/waiver window boundary inclusivity (on-or-before semantics match throughout).

Orchestrator verification: PRD_COMPLETED.md is 327 lines / 64,198 chars; `diff -q` vs PRD_FINALIZED.md shows a real delta (40 diff lines = 20 in-place line edits); not a no-op.

## Step 9-follow-up: Fix F1/F2 rejection-order impl bugs + re-sweep — 2026-10-02T10:56:00.000Z

Orchestrator adjudication of Step 9's two flagged mismatches: PRD §2.9's 12-layer rejection order is deliberate, unambiguous, and implementable (and the impl was internally inconsistent — withdraw/suspend/resume already did ownership-first), so neither exoneration category applies; the fix went into `implementation/`, not the PRD. PRD_COMPLETED.md was left untouched as the alignment target.

Subagent report (verbatim):

All 8 rounds are green: passed=96, total=96, failed=0. The results.1-8.json artifacts remain in place in workspace/implementation/.

**F1 — body well-formedness (layer 4) now precedes path resolution (layer 5)** on every endpoint that takes a path identifier plus a body and has no Claimant-ownership dependency on the path target. 11 endpoints fixed:
- `routes_claims.py`: `deny_claim`, `reopen_claim`
- `routes_corrections.py`: `request_evidence`, `deny_correction`, `reopen_correction`
- `routes_workers.py`: `patch_worker`, `report_death`
- `routes_relationships.py`: `reject_relationship`
- `routes_overpayments.py`: `decide_waiver`, `begin_recovery`
- `routes_payees.py`: `decide_payee_case`

Endpoints with a Claimant-ownership check on the path target were deliberately left in load → ownership → body order, matching the existing withdraw/suspend/resume pattern and §2.9 layer 3's "on nested paths the parent necessarily resolves before this comparison can run": `withdraw_claim`, `suspend_claim` (routes_claims.py), `submit_evidence` (routes_corrections.py), `request_waiver` (routes_overpayments.py). Verified by post-edit grep that these are the only remaining load-before-body sites (plus GETs and body-less action endpoints, which are unaffected).

**F2 — ownership (layer 3) now precedes body validation (layer 4)** on the three create endpoints. The identifier needed for the ownership comparison is extracted first (a missing/malformed id still 400s, since the comparison cannot run without it), then ownership fires, then the remaining body fields validate, then existence (404):
- `routes_claims.py`: `create_claim`
- `routes_corrections.py`: `create_correction`
- `routes_relationships.py`: `create_relationship`

**py_compile:** all 6 edited files compile cleanly (COMPILE_OK).

**Sweep:** 8/8 rounds at passed=96/total=96, zero regressions. No reorder needed reverting — the 404-catalog test (`test_22_errors.py`) sends well-formed bodies against nonexistent ids, so it still reaches the per-entity 404 after the reorder, and all single-failure outcomes are byte-for-byte unchanged.

Only files under `workspace/implementation/` were edited; no test, helper, PRD, scaffold, or worklog files were touched.

Orchestrator verification: all 8 `results.${i}.json` regenerated, each passed=96 total=96 failed=0; newest source file (routes_payees.py) mtime 1790938064 < oldest results file (results.7.json) mtime 1790938252 — the final clean sweep postdates the last implementation edit. Pipeline complete: SCAFFOLD.yaml + both design indices + PRD.md + PRD_FINALIZED.md + PRD_COMPLETED.md + test_helpers/ (9 files) + test_suite/ (22 files, 96 tests) + implementation/ (20 modules, 39 endpoints) + worklog.md all present.
