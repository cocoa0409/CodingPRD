# Worklog — task_3448_veterinary_diagnostic_instrument_placement_reagent_subscription

## Step 1: Create task directory — 2026-10-02T05:24:00.000Z

Pre-allocated task directory `./tasks/task_3448_veterinary_diagnostic_instrument_placement_reagent_subscription/` verified to exist with `workspace/` inside; directory is empty and ready. No new index computed (per instructions).

## Step 2: Generate scaffold artifacts — 2026-10-02T05:47:00.000Z

Wrote SCAFFOLD.yaml (sections 1.0-1.7: 9 entities, 8 state machines, 7 calculations, 11 validations, 32 endpoints, 29 errors, 5 roles, 2 OCC concurrency rules), SCAFFOLD_DIFFICULTY_DESIGN.yaml (9 rules x 2 = 18 instances), SCAFFOLD_CORNER_DESIGN.yaml (71 instances: 53 active + 18 excluded stubs). scaffold_lint.py verdict: clean lint (526 calls scanned, 0 violations). All 29 error codes wired and test-referenced; all 203 grounds refs resolve; OCC fields dynamic; FK reverse-reachability confirmed by lint check (f).

## Step 3: Copy shared files — 2026-10-02T06:20:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3448_veterinary_diagnostic_instrument_placement_reagent_subscription/workspace/INSTRUCTION.md`. Orchestrator verified all three scaffold YAMLs parse and match the vet-diagnostics domain (api_prefix=/api, 9 entities) before proceeding.

## Step 4: Generate PRD — 2026-10-02T06:35:00.000Z

All audits pass. The PRD is complete and verified.

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_3448_veterinary_diagnostic_instrument_placement_reagent_subscription/workspace/PRD.md`
**Line count:** 292 lines (prose paragraphs as long lines; ~5,000 words)

**Section list:**
- §1 Introduction (2 paragraphs: business context + system scope)
- §2 Global Specifications — 2.1 Roles/Auth (all 5 roles with identity translation: `ClinicManager` entity-backed to Clinic, other 4 opaque) · 2.2 API Response Structure (**verified byte-identical** to `section-2.2-response-structure.md`) · 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ASC) · 2.4 Logical Clock (default 2026-09-01T00:00:00Z, strictly-forward, pinned 3-stage sweep order) · 2.5 Common Resource Properties (incl. LabResult exception: no `updated_at`/`version`) · 2.6 Money/Precision (integer cents, round-half-up, 4-decimal uptime) · 2.7 Two Interval Semantics (half-open GPA windows vs closed PA terms, adjacency vs touching rules) · 2.8 OCC (both guarded writes, `expected_agreement_version`, `ERR_STALE_AGREEMENT_VERSION` 412) · 2.9 Validation Order (all 11 priority tiers enumerated with error IDs and applies-to scopes) · 2.10 Identifier Resolution
- §3 Business Logic — 9 subsections (clinic lifecycle, group pricing, placement agreements, reagent pricing ladder, commitment/shortfall/breach, renegotiation loop, analyzer/service, testing pipelines, proficiency/uptime)
- §4 Endpoint Definitions — all 32 endpoints verified present with correct method+path rows
- §5 Error Code Catalogue — all 29 error IDs with scaffold-pinned HTTP statuses

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 89 required names (entity fields + endpoint inputs + common fields + nested pricing fields), 89 present, 0 missing — **PASS**
- Contract 2 (Rule Coverage): all 11 validation tiers with ordering prose; both OCC rules fully expressed (endpoint + field + error + 412); all 8 state machines' transitions/preconditions/side-effects rendered; all 7 calculations in reconstructible prose (pricing ladder, dual fulfillment attribution, shortfall sum-of-rounds, renegotiation proposal order, proficiency tolerance, dual uptime variants, interval semantics); all cascades (breach→clinic suspend, FAIL→remediation case, loaner flips, service credit) stated — **PASS**
- Contract 3 (§3 Path Purity): 555 backtick tokens scanned in §3, 0 paths, 0 bare HTTP methods, 0 method+path combos — **PASS**

**Constant verification:** every scaffold constant appears verbatim in the PRD — 2026-09-01T00:00:00Z, 0.40, 50000, 0.30, 0.80, 250000, 0.05, 30 days, 90 days, 2160 hours, 16 hours, 0.985, 25000, 24 hours, {24, 36, 48, 60}, and all 8 PRICE_TABLE SKUs with families and list prices (420/760/890/385/153/3000/3000/12500). All enum values, state names, role names, and action verbs verified present. The renegotiation chain is written acyclically (snapshot at request → advisory proposal → finance-supplied value at resolution). The withheld design-index files were never opened.

Orchestrator spot-check: 291 lines on disk; 29 unique ERR_ IDs; clock default and all 8 SKU prices + key constants each present verbatim.

## Step 5a: Generate test_helpers/ — 2026-10-02T06:58:00.000Z

Step 5a complete. All outputs are in `test_helpers/` — no `test_suite/` or `test_*.py` files were created.

Files written: types.py (356 lines: 24 str enums + 9 entity TypedDicts; LabResult omits updated_at/version per PRD §2.5), constants.py (143 lines), api_errors.py (86 lines: 29 ApiErrorId values + HTTP map), api_client.py (214 lines: exactly 32 endpoint methods, clock under /api, no hardcoded port), assertions.py (334 lines: 9 assert_{entity} checkers + invariants; docstring documents 201-for-creates convention), factories.py (317 lines: input-only payloads, OCC expected_agreement_version payloads), test_users.py (63 lines: 5 roles, ClinicManager entity-backed), fixtures.py (701 lines: 5 tiers incl. hierarchy composites, pipeline drivers, threshold composites, clock arithmetic via iso_hours_after), __init__.py (50 lines), INTERFACE.md (283 lines: frozen public-name catalog for Step 5b).

Constant-vs-PRD verification: all constants grep-verified against PRD.md (CLOCK_START_ISO 2026-09-01T00:00:00Z @L78; MAX_DISCOUNT_PCT 0.40 @L134; MIN_MONTHLY_MINIMUM_CENTS 50000; SHORTFALL_BILLING_RATE 0.80; SHORTFALL_BREACH_THRESHOLD_CENTS 250000; RENEGOTIATION_CASELOAD_DELTA_PCT 0.30 inclusive; PROFICIENCY_TOLERANCE_PCT 0.05 inclusive; QC_VALIDITY_DAYS 30; UPTIME 90d/2160h, threshold 0.985 strict; CALIBRATION_FREE_HOURS_PER_YEAR 16; UPTIME_SERVICE_CREDIT_CENTS 25000; RESPONSE_SLA_HOURS 24; ALLOWED_TERM_MONTHS [24,36,48,60]; PRICE_TABLE 8 SKUs @L156; pagination 10/1/100 @L74; 5 roles @L15). No scaffold-carried drift.

Self-check: AST parse OK (9/9); import test_helpers + all 8 submodules OK; `from test_helpers import api_client` binds the ApiClient instance (documented idiom); endpoint coverage 32/32; error catalog 29==29; 206 public names resolve.

Notes for Step 5b: creating POSTs return 201 — pass 201 explicitly to validate_success; fixtures thread make_clinic_manager_headers(clinic["id"]); OCC helpers re-read live agreement version (PRD §3.5 unconditional per-close version bump); extract_pricing_lines() tolerates bare list and {"lines":[...]}.

Orchestrator spot-check: all 9 helper files + INTERFACE.md on disk; import test_helpers OK; api_client binds ApiClient instance; CLOCK_START_ISO=2026-09-01T00:00:00Z; PRICE_TABLE has 8 SKUs; no test_suite/ exists yet.

## Step 5b: Generate test_suite/ — 2026-10-02T07:35:00.000Z

All checks pass and pytest collects the full suite. Step 5b is complete.

**Output**: `conftest.py` + 11 test files in `test_suite/` — **89 tests**, each translating exactly one design-index instance (nothing from `test_helpers/` was touched).

| File | Tests | Contents |
|---|---|---|
| `conftest.py` | — | session `api` + 5 role-header fixtures |
| `test_01_auth_and_rbac.py` | 8 | header context, unknown role, ownership mismatch, 5 RBAC denials |
| `test_02_group_pricing_agreements.py` | 10 | window validity, half-open adjacency ×2, group-type keying ×2, referential>temporal ×2, clock default, deferred activation/expiry, expiry repricing |
| `test_03_clinics_and_placement_agreements.py` | 11 | clinic defaults, program-conditional terms, enum/term rejection, end_date, approve/activate gates, snapshot immutability, clinic-active dependency ×2, closed-interval term overlap ×2 |
| `test_04_renegotiation.py` | 8 | cycle ×2, caseload 0.30 boundary ×2, reject conservation ×2, proposal floor, OCC resolve-stale |
| `test_05_reagent_pricing.py` | 9 | layered pricing ×2, QC zero-pricing, order_month term gate, immediate locked pricing, pagination/filters, cancel lockdown, cancel conservation ×2 |
| `test_06_commitment_billing.py` | 13 | provisional-vs-final attribution ×2, null-until-close, FULFILLED-only input set, sum-of-rounds ×2, close side effects, payment mismatch, pay-on-OPEN, payment reconciliation, OCC close-stale, state>fiscal ×2 |
| `test_07_breach_recovery.py` | 3 | breach threshold cascade ×2, terminate blocked by unpaid shortfall |
| `test_08_analyzers_service.py` | 8 | system-field smuggling, install gate, parallel dimensions ×2, double dispatch, cancel/loaner compensation, FK reverse filters, state-error sweep |
| `test_09_uptime.py` | 3 | reported-vs-breach variants ×2, exactly-one service credit |
| `test_10_lab_pipeline.py` | 12 | immutable result record, branch invalids, deliver gates, analyzer readiness ×2, proficiency FAIL cascade ×2, tolerance boundary, QC lapse boundary |
| `test_11_existence_and_input_shape.py` | 4 | per-entity 404s, action-endpoint 404s, FK declaration order, 4-way ERR_INVALID_REQUEST |

**Tag audit (real AST parse + `yaml.safe_load` of both indices)**: 89 tests → 71 distinct valid tags. Queue A: 18/18 instances with exactly 2 tests each. Queue B: 53/53 active instances with exactly 1 test each. Phantom tags: 0. Missing: 0. Duplicates: 0. Misformed/untagged: 0. **Skipped instances: none** — every active instance passed the PRD-coverage + unique-derivability filter.

**Excluded stubs (18)**: not translated, per spec. 17 cross-references resolve; one stub (`Corner/calculations/pricing_layered_precedence`) cites `layered_pricing_override_membership` but the actual §1.8 instance is `layered_pricing_override_membership_program` — a corner-design typo (reporting only; stub excluded as specified either way).

**Self-check outputs**: (a) AST parse 12/12 OK; (b) tag audit above; (c) all 12 modules import with the task dir on `sys.path`; (d) every docstring citation contains a ≥6-word contiguous span verified verbatim against `workspace/PRD.md` (162 spans checked, ALL PASS after fixing three: a mis-quoted "since the client last read it" in both OCC docstrings and dropped markdown `**` around the §2.9 tier-4 "Existence" sentence); (e) no `skip`/`skipif`/`xfail` markers; (f) pyflakes clean; plus a bonus `pytest --collect-only` run collecting all 89 tests with zero errors.

**Two adjudication notes** (derivability choices, not skips): (1) absolute version numbers from the design indices are asserted as observed-base + increment chains (`assert_version_incremented`, `version == draft_v + N`), since PRD §2.5 pins "+1 per mutation" but never an absolute initial value — this keeps every version claim two-reader safe while preserving the design's exact arithmetic whenever the base is 1; (2) `finance_reviewer_cannot_set_clock` proves the clock never moved with a discriminating probe (GPA opening 2026-09-02 lands DRAFT) instead of the design's weaker probe, which would land ACTIVE whether or not the clock had moved.

Orchestrator independent audit: AST tag walk confirms 89 tests / 71 unique tags / 18 Difficulty (×2 each) / 53 Corner (×1 each) / 0 phantom / 0 uncovered / 0 wrong-multiplicity; `pytest --collect-only` collects 89 tests, 0 errors.

## Step 6: Generate implementation — 2026-10-02T07:53:00.000Z

Implementation complete. All checks green.

**Files written (17 files, 2145 lines total)**: constants.py (41: all PRD-verbatim constants), errors.py (47: ApiError + 29 catalog codes), db.py (41: in-memory dicts, 9 collections, logical clock; empty at boot), util.py (161: ISO helpers, Decimal round-half-up, envelope/pagination, auth middleware), ser.py (184: per-entity serializers, on-read provisional attribution, LabResult without updated_at/version), services.py (209: layered price resolution, clock sweep 3-phase order, uptime dual-variant recompute, credit/breach/remediation cascades, period factory), routes_clock.py (27), routes_gpa.py (97), routes_clinics.py (118), routes_agreements.py (404: OCC on resolve+close), routes_analyzers.py (183), routes_service_cases.py (151), routes_reagent.py (145), routes_lab.py (260: dual pipeline, safety gates in pinned order, proficiency cascades), app.py (66), start.sh (10: guarded pip install, $PORT default 10000, 0.0.0.0, foreground), requirements.txt.

**Endpoint count: 32** (route-decorator grep, matches §1.5 exactly, clock under /api).

**Dead-check grep: PASS** — all 29 ERR_* codes raised outside errors.py; every raise references a defined catalog code; all calculation helpers have callers.

**Smoke test** (dynamic ports; own PIDs killed): no-headers → 400 envelope; clinic create 201; draft→approve→activate (end_date 2028-09-01, 24 periods, baseline snapshot 100); order LIST pricing 420×10=4200; close 2026-09 with SUBMITTED order → fulfilled 0, shortfall 50000, billed 40000, ISSUED; attribution divergence (order_month vs fulfilled_at) verified; OCC stale → 412; payment mismatch → 402; exact → PAID; renegotiation 29% → 422, exactly 30% → RENEGOTIATION proposed 65000 (inclusive boundary, round-half-up); non-monotonic clock → 400 ERR_INVALID_REQUEST.

**Interpretations chosen** (audit input for Step 7):
1. current_utc compact `...T00:00:00Z`; created_at/updated_at/meta and system-stamped fields 3-fractional-digit `...T00:00:00.000Z` per §2.5; input-sourced datetimes round-trip compact.
2. Ownership (tier 3) before 404 only where computable without the entity (body clinic_id on creations; PATCH clinics); other path-addressed resources 404 precedes ownership.
3. PRD tier order over scaffold precondition order: input-shape (tier 5) before state checks (tier 6) per PRD §2.9.
4. RECORD_RESULT: static action-role rules enforced pre-existence at tier 2; origin-dependent role checked right after loading the order, before state checks; unknown action/status → ERR_INVALID_REQUEST.
5. PATCH analyzers: client-supplied UNDER_SERVICE/ON_LOAN → ERR_INVALID_REQUEST; valid-enum-but-illegal → ERR_ANALYZER_INVALID_STATE; one version bump per dimension actually changed; connectivity refused if request decommissions the unit.
6. Illegal clinic status transitions → ERR_CLINIC_NOT_ACTIVE (409); empty PATCH clinics → 200 no-op no bump; caseload_current_tests accepts any integer (PRD pins >0 only for baseline).
7. Explicit JSON null for another program type's field counts as absent; non-integer/negative lease/purchase → ERR_INVALID_PROGRAM_TERMS.
8. Non-REAGENT_COMMITMENT agreements: CommitmentPeriods created with minimum_cents=null (treated as 0 at close); renegotiation proposed_minimum computes with monthly_minimum 0 → 50000 floor.
9. Resolve-renegotiation: waive_period_ids validated even when accept=false, waivers applied only on accept; OPEN periods rewritten on accept get own version bump.
10. Close version accounting: agreement +1 unconditionally per close, +1 more if breach cascade fires; clinic +1 on cascade suspension.
11. PROFICIENCY_REMEDIATION cases do not move analyzer to UNDER_SERVICE; compensations flip units only when actually UNDER_SERVICE/ON_LOAN; analyzer version bumps only when a field changed.
12. No invented guards: duplicate serial → ERR_INVALID_REQUEST; no clinic↔agreement ownership beyond PRD; analyzer-belongs-to-clinic on test orders → ERR_INVALID_REQUEST (400, tier 5 referential).
13. Pagination: unparseable limit/offset fall back to defaults; out-of-range clamped; lab results sub-collection returns response_type array without pagination meta.

Orchestrator verification: all 17 files on disk; py_compile clean; 32 bp route decorators, all /api-prefixed incl. clock; independent boot smoke on dynamic port — clinic create 201 with envelope {data,meta,response_type}, status ACTIVE, version 1, created_at 2026-09-01T00:00:00.000Z; own PID killed.

## Step 7: Test-and-fix iteration loop — 2026-10-02T08:25:00.000Z

Clean 8-round sweep achieved. Summary:

## Iterations run
2 (first sweep: 12 deterministic failures in 4 clusters; second sweep: clean).

## Tests deleted
None. No PRD-silent or non-uniquely-derivable assertion survived triage — every failure traced to a fixable artifact.

## Fixes applied to `test_helpers/`
- `__init__.py` — `assert_version_incremented`: suite and INTERFACE.md use `(before, after)` order; the framework helper takes `(new_version, old_version)`. Added an adapter wrapping the framework function. Cured 5 failures (`test_approve_from_approved_rejected`, `test_renegotiation_cycle_version_marks_each_lap`, `test_renegotiation_reject_restores_active_and_terms`, `test_occ_resolve_renegotiation_stale_version_rejected`, `test_analyzer_version_marks_each_dimension_hop`, `test_service_case_double_dispatch_rejected` — the impl versions were correct all along).
- `fixtures.py` — `list_commitment_periods`: fetched only the default first page (PRD §2.3: `limit` defaults to 10) while callers assert the full 24-month term collection (PRD §3.3: "One commitment period per term month is created"). Now walks `offset` with `limit=100` until `has_more` clears. Cured 3 failures (`test_activation_snapshots_baseline_and_creates_periods`, `test_activate_succeeds_once_clinic_restored`, `test_commitment_period_computed_fields_null_until_close`).

## Fixes applied to `test_suite/`
- `test_08_analyzers_service.py::test_state_errors_sweep_analyzer_and_service_case` — the decommission-with-OPEN-case assertion expected `ERR_SERVICE_CASE_INVALID_STATE`, but PRD §2.9 ("a request that fails several checks reports the failure from the earliest tier") puts state legality at tier 6 and decommission-blocked-by-open-cases at tier 9; a unit with an OPEN/DISPATCHED case is always UNDER_SERVICE/ON_LOAN, so tier 6's `ERR_ANALYZER_INVALID_STATE` is the PRD-determined outcome (the tier-9 blockage is unreachable — scaffold self-contradiction shadowed by first-failure-wins). Corrected the expected error_id and docstring; kept the state-conservation assertions.

## Fixes applied to `implementation/`
- `ser.py` (`qc_valid_until`, `fulfilled_at`, `resolved_at`), `services.py` (`opened_at`, `response_due_at`), `routes_service_cases.py` (`opened_at`), `routes_lab.py` (`resulted_at`) — clock-taken timestamps now render compact (`iso_z`) instead of `.000Z`. PRD attaches "three fractional digits" only to `created_at` and `api_request_timestamp` (§2.5/§2.2) and renders the logical clock compact (`2026-09-01T00:00:00Z`, §2.6); the impl already emitted `current_utc` compact, so this also removed an internal inconsistency. Cured 2 failures (`test_proficiency_tolerance_boundary_inclusive`, `test_qc_validity_lapses_only_after_boundary`). No test asserts `.000Z` anywhere, so the flip was safe.

## Sibling unasserted paths (test-side fixes did not dominate, but noting per protocol)
- The tier-9 decommission-blocked-by-open-cases error (`ERR_SERVICE_CASE_INVALID_STATE` on decommission) is now asserted nowhere — it is unreachable under PRD §2.9 given the case⇒UNDER_SERVICE/ON_LOAN coupling; the impl retains the check per PRD §3.7. `ERR_SERVICE_CASE_INVALID_STATE` remains covered via dispatch/resolve state errors (`test_service_case_double_dispatch_rejected`).
- Periods-endpoint pagination meta (default limit/offset on that specific collection) is exercised only through the helper, not asserted directly.

## Final sweep evidence
results.1–8.json, all on disk in `workspace/implementation/`: every round passed=89, total=89. Union of failures across rounds: 0.

Orchestrator verification: read all 8 results files — 89/89/0 in every round; 0 source files (implementation/, test_helpers/, test_suite/) newer than results.1.json (no post-sweep edits).

## Step 8: Finalize PRD — 2026-10-02T08:40:00.000Z

Done. The edit is applied cleanly: one sentence inserted into §2.4, files differ by exactly that line (291 lines each, +277 chars, 0.55% delta).

### Changes (1 edit)

- **§2.4 (The Logical Clock)** — insert — appended a sentence pinning the lexical rendering of clock-taken timestamps: *"Of these clock-taken values, `opened_at`, `resolved_at`, `fulfilled_at`, `resulted_at`, `qc_valid_until`, and the advance response's `current_utc` render in the clock's own compact ISO 8601 UTC form (as in `2026-09-01T00:00:00Z`), omitting the fractional part when it is zero."* — impl evidence: `ser.py:76` (qc_valid_until), `ser.py:97` (fulfilled_at), `ser.py:179` (resolved_at), `services.py:182` + `routes_service_cases.py:62` (opened_at), `routes_lab.py:135` (resulted_at), `routes_clock.py:27` (current_utc), all via `util.iso_z` (`util.py:36-40`).

  Rationale: PRD pinned three fractional digits only for `created_at` (§2.5) and `api_request_timestamp` (§2.2) and showed the clock compactly, but never affirmatively stated the rendering of the six fields above — the original impl shipped `.000Z` and was PRD-defensible (Step 7's first sweep failed on exactly this). The pin removes the ambiguity a fresh implementer would face.

### Pre-edit search log (edit 1)

- (a) Subject: rendering format of clock-taken timestamps.
- (b) Impl paths enumerated: `util.py:31-40` (iso_ms/iso_z), `util.py:93` (api_request_timestamp → iso_ms), `services.py:31-32,42` (created_at/updated_at → iso_ms), `ser.py:15-16,48-49` (effective_from/to, start/end_date → iso_z, client-supplied), `ser.py:76,97,179` (qc_valid_until/fulfilled_at/resolved_at → iso_z), `services.py:182,184` (remediation opened_at/response_due_at → iso_z), `routes_service_cases.py:62,64` (API-case opened_at → iso_z, **response_due_at → iso_ms**), `routes_lab.py:135` (resulted_at → iso_z), `routes_clock.py:27` (current_utc → iso_z). Full-read: ser.py, util.py, db.py, services.py, routes_service_cases.py, routes_analyzers.py, routes_lab.py, routes_clock.py; grep-swept all remaining routes.
- (c) Wording adjustments: three conflicts found and avoided — (i) `updated_at` renders iso_ms and is format-silent in the PRD, so the sentence names fields explicitly instead of claiming "every clock-taken timestamp renders compact"; (ii) `response_due_at` is internally inconsistent in the impl (iso_ms at `routes_service_cases.py:64` vs iso_z at `services.py:184`), so it is deliberately left unpinned; (iii) iso_z falls back to three fractional digits when microsecond≠0, so the sentence pins only the zero-fractional case. Also used non-exhaustive phrasing so the preceding "every timestamp … is taken from this clock" sentence is not contradicted.

### Items needing no edit (evidence)

- `test_helpers/__init__.py` version adapter — pure test-side signature fix; impl version semantics already pinned by PRD §2.5 (impl: `services.py:39-42`).
- `fixtures.py` pagination walk — pure fixture bug. PRD §2.3 pins limit default 10 / max 100; §3.3 pins one period per term month. Impl paginates exactly per §2.3 (`routes_agreements.py:370` → `util.paginate`).
- test_08 decommission error_id — PRD §2.9 already determines the outcome (tier 6 before tier 9, earliest tier wins). Impl `routes_analyzers.py:130-139` checks state first and retains the tier-9 check per §3.7. No PRD silence, no mismatch.
- Sibling unasserted paths — informational; both already consistent with PRD §2.9/§3.7 and §2.3 respectively.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (§2.4 sentence append); both files 291 lines.

## Step 9: Complete PRD — 2026-10-02T09:05:00.000Z

The grep missed the merged block `105,106c105,106` (adjacent changed lines), which is exactly where the two §2.9 edits landed — confirmed present in the file. All 26 edits are accounted for: 23 distinct lines changed, matching the edit plan with no collateral changes.

**Source → output**: `workspace/PRD_FINALIZED.md` (291 lines / 51,096 chars) → `workspace/PRD_COMPLETED.md` (291 lines / 55,018 chars; **+3,922 chars**, 23 lines touched, all in-paragraph edits; no new sections).

**Counts**: 25 ambiguity-pins (inserts), 1 mismatch-revision.

### Changes (section — insert|revise — class — what — impl ref)

- §2.3 — insert — ambiguity — non-integer `limit`/`offset` falls back to defaults; parsed values clamped (limit [1,100], offset ≥0) — `implementation/util.py:117-127`
- §2.4 — insert — ambiguity — client-supplied datetimes (`effective_from`, `effective_to`, `start_date`, `end_date`) echoed in the compact iso_z form — `implementation/ser.py:15-16,48-49`, `util.py:36-40`
- §2.4 — insert — ambiguity — sweep version bump is per-transition; a GPA whose whole window elapsed goes `DRAFT`→`ACTIVE`→`EXPIRED` in one advance (+2) — `implementation/services.py:103-110`
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — `implementation/services.py:33`
- §2.6 — **revise** — **mismatch** — uptime ratios rounded half-up to 4dp but rendered as JSON numbers (`1.0`, trailing zeros dropped); legit: "exactly 4 decimal places" is unimplementable as a JSON number — `implementation/services.py:154-155`, `routes_analyzers.py:71-72`
- §2.9 tier 2 — insert — ambiguity — test-order action-role rule needs `origin`, so it runs after load; missing order yields `ERR_TEST_ORDER_NOT_FOUND` even for a wrong role–action pair — `implementation/routes_lab.py:162-183`
- §2.9 tier 3 — insert — ambiguity — ownership-before-existence only where computable without the entity (clinic path id, creation body `clinic_id`); otherwise existence first, ownership immediately after — `implementation/routes_agreements.py:194-197`, `routes_reagent.py:119-122`, `routes_lab.py:186-188`, `routes_clinics.py:65-71`
- §3.1 — insert — ambiguity — caseload update accepts any integer (no positivity floor); empty/null-only clinic PATCH is a 200 no-op with no version bump — `implementation/routes_clinics.py:74-76,109-117`
- §3.2 — insert — ambiguity — `sku_overrides` `unit_price_cents` must be non-negative int; malformed entry or explicit null array → `ERR_INVALID_REQUEST` — `implementation/routes_gpa.py:40-54`
- §3.3 — insert — ambiguity — `lease_rate_cents`/`purchase_price_cents` are non-negative integers; explicit null counts as absent for other program types' fields — `implementation/routes_agreements.py:68-94`
- §3.4 — insert — ambiguity — no cross-check that the billed agreement belongs to the ordering clinic — `implementation/routes_reagent.py:39-44`
- §3.4 — insert — ambiguity — order drive PATCH body names target in `status` (`FULFILLED`|`CANCELLED`), else `ERR_INVALID_REQUEST` — `implementation/routes_reagent.py:124-126`
- §3.5 — insert — ambiguity — null `minimum_cents` (LEASE/PURCHASE periods) treated as zero at close: zero shortfall/billed, `billing_status` stays `NONE` — `implementation/routes_agreements.py:333-341`, `services.py:196-209`
- §3.5 — insert — ambiguity — close responds with the closed period object, not the agreement — `implementation/routes_agreements.py:357`
- §3.6 — insert — ambiguity — renegotiation not restricted by program type — `implementation/routes_agreements.py:198-214`
- §3.6 — insert — ambiguity — null `monthly_minimum_cents` scales from zero, so the proposal lands on the 50000 floor — `implementation/routes_agreements.py:208-211`
- §3.6 — insert — ambiguity — `waive_period_ids` validated even when `accept` is false; `new_minimum_cents` ignored on reject; null waive list ≡ empty — `implementation/routes_agreements.py:238-261`
- §3.7 — insert — ambiguity — install gates on agreement state only (no clinic-status gate, no agreement↔clinic check); duplicate serial → `ERR_INVALID_REQUEST`; `is_loaner_unit` must be boolean when present — `implementation/routes_analyzers.py:31-58`
- §3.7 — insert — ambiguity — client-supplied `UNDER_SERVICE`/`ON_LOAN` → `ERR_INVALID_REQUEST` — `implementation/routes_analyzers.py:113-116`
- §3.7 — insert — ambiguity — decommission+connectivity in one call refused; per-dimension version bumps (both driven = +2); empty/null-only analyzer PATCH is a 200 no-op — `implementation/routes_analyzers.py:144-170`
- §3.7 — insert — ambiguity — case PATCH body `action` ∈ {DISPATCH, RESOLVE, CANCEL}, else `ERR_INVALID_REQUEST` — `implementation/routes_service_cases.py:88-91`
- §3.7 — insert — ambiguity — `downtime_hours` rounded half-up to whole hours; `resolution_note` must be a string when present — `implementation/routes_service_cases.py:107-118`
- §3.8 — insert — ambiguity — `expected_result` must be a number for PROFICIENCY — `implementation/routes_lab.py:61-63`
- §3.8 — insert — ambiguity — `result_value` must be numeric; the recording response carries the updated order (result read via the results collection) — `implementation/routes_lab.py:191-195,222`
- §3.8 — insert — ambiguity — results collection returned whole, unpaginated, no pagination fields in `meta` — `implementation/routes_lab.py:254-260`, `util.py:112-114`
- §3.9 — insert — ambiguity — FAIL on an already-`LAPSED` analyzer changes nothing on the unit (no version move) but still opens the remediation case; remediation case does not move operational state — `implementation/routes_lab.py:144-155`, `services.py:172-192`

### Flagged-but-pinned silences (pinned per impl since PRD was silent; noted as commercially surprising, worth a second look)
- Reagent order submission never checks `agreement.clinic_id == body clinic_id` (`routes_reagent.py:39-44`) — cross-clinic billing is possible; PRD §3.4 had no sentence requiring the check.
- Analyzer install never checks clinic status nor `agreement.clinic_id == body clinic_id` (`routes_analyzers.py:31-58`) — PRD §3.7 gates on agreement state only.
- Renegotiation allowed on LEASE/PURCHASE agreements, proposing from a null minimum (`routes_agreements.py:208-211`).

### Known-good items left untouched
The exonerated §2.9/§3.7 decommission-check shadowing (tier 6 fires first on units with open cases) and the deliberately unpinned `response_due_at` format split (iso_ms on the API route at `routes_service_cases.py:64`, iso_z on the remediation cascade at `services.py:184`) were left exactly as-is.

### Degenerate corners observed but deliberately not pinned
Self-loan (loaner == serviced unit) is accepted and ends `ON_LOAN`; duplicate ids in `waive_period_ids` would double-subtract. Both are unreachable-in-practice edges with no PRD prose touching them.

Orchestrator adjudication + verification: the single mismatch-revision (§2.6 uptime rendering) is EXONERATED — "exactly 4 decimal places" is unimplementable as a JSON number; precision semantics (round-half-up 4dp) retained, only rendering revised. diff confirms PRD_COMPLETED.md ≠ PRD_FINALIZED.md with 48 diff lines (~23 touched lines, consistent with the edit plan); still 291 lines, in-paragraph only. All 8 results.*.json intact; 0 source files newer than the Step 7 sweep (Steps 8/9 touched no code).
