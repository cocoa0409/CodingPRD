# Worklog — task_3083_payroll_service_bureau_tax_filing_agency_client

## Step 1: Create task directory — 2026-09-29T21:15:00.000Z

Pre-allocated task directory `./tasks/task_3083_payroll_service_bureau_tax_filing_agency_client/` verified to exist with `workspace/` inside. No new index computed; used the pre-allocated path as instructed.

## Step 2: Generate scaffold — 2026-09-29T22:10:00.000Z

Scaffold generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_3083_payroll_service_bureau_tax_filing_agency_client/` and the linter verdict is clean:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

### Counts

| Table | Count |
|---|---|
| Entities (§1.1) | 12 — Jurisdiction, Client, JurisdictionRegistration, PayrollRun, Impound, FundingFailureEvent, TaxDeposit, TaxReturn, ReturnAmendment, AgencyNotice, CreditAssessment, WageStatement |
| State machines (§1.2) | 9 (Client, Registration, PayrollRun, Impound, TaxDeposit, TaxReturn, ReturnAmendment, AgencyNotice, WageStatement) + 3 OCC concurrency rules |
| Calculations (§1.3) | 9 |
| Validations (§1.4) | 24 priority-ordered rules |
| Endpoints (§1.5) | 80 |
| Error codes (§1.6) | 23 — all referenced by at least one validation |
| Roles (§1.7) | 5 — ClientPayrollAdmin (entity_backed:Client), BureauOnboarder, BureauTaxFiler, BureauTreasury, BureauCompliance (opaque) |
| §1.8 difficulty instances | 18 (exactly 2 per rule × 9 rules) |
| §1.9 corner instances | 53 total (49 active + 4 `excluded_because:` stubs) across all 9 sections |
| Calls scanned by lint | 910 |

### Notable design decisions (maximum-difficulty posture)

- **Archetype**: compliance/audit primary + ledger-reconciliation secondary; `segregation_of_duties` role model (the filer of a return/amendment cannot accept/reject/reconcile it — enforced by X-User-ID at priority 7), saga consistency, hybrid topology with two self-referential links (return supersession, wage-statement corrections).
- **Rule 1 (dual-variant)**: liability computed bureau-books vs agency-confirmed (750000 vs 400000 on identical data); wage-summary as-issued vs include-voided history (9000000 vs 14000000).
- **Rule 2 (combinatorial)**: mode (a) tiered late-deposit penalty with inclusive 5/6/15/16-day edges; mode (c) shortfall penalty with pinned evaluation order (liability first, safe-harbor threshold second — never the naive `(liability − deposits) × rate`).
- **Rule 3 (non-linear SM)**: registration reject→resubmit cycle; deposit failure→reschedule loop where `due_date` never moves so lateness accumulates.
- **Rule 4 (cascades)**: depth-3+ NSF cascade (Impound FAILED → run REVERSED → deposits CANCELLED, plus a parallel strike/posture/assessment branch); amendment-acceptance supersession chain spawning a replacement return.
- **Rule 6 (boundaries)**: Tuesday-vs-Wednesday semiweekly bucket flip; the third funding strike (count == 3, inclusive) as the suspension boundary — deliberately decoupled from the weighted posture base (NSF weighs 2, wire-miss weighs 1), so posture leads the count.
- **Rule 8 (overlap)**: two different interval semantics — deposit (run, jurisdiction) occupation windows released by terminal states vs wage-statement per-key capacity released by atomic supersession via the correction channel.
- **Rule 9 (invariants)**: draft-then-reverse conserves money-in-motion/pipeline totals at exactly the pre-forward baseline; correction cycles conserve active-statement count at exactly 1 per key.
- Clock default `2026-09-01T00:00:00Z` pinned; all penalty/due-date fixtures use calendar-verified dates (Sept 2026 weekdays, weekend rollover, quarter boundaries). Four lint-driven §1.5 additions were made during generation: a `/_probe/no-auth` endpoint for the unauthenticated 401 corner, plus filtered-list/single-read GETs to satisfy FK reverse-reachability for FundingFailureEvent, CreditAssessment, and JurisdictionRegistration.

## Step 3: Copy shared files — 2026-09-29T22:11:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3083_payroll_service_bureau_tax_filing_agency_client/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T22:25:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_3083_payroll_service_bureau_tax_filing_agency_client/workspace/PRD.md` (327 lines). The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` files were never opened, and no sibling task directories were touched.

**Section structure** — §1 Introduction (2 paragraphs, fiduciary business-context angle); §2 with 10 subsections (2.1 RBAC + identity semantics per role, 2.2 verbatim response envelope, 2.3 pagination, 2.4 common resource properties incl. the FundingFailureEvent `common_fields: false` exception, 2.5 integer-cents precision, 2.6 logical clock + bureau calendar, 2.7 OCC, 2.8 existence/validation priority order, 2.9 segregation of duties, 2.10 cascades); §3 with 10 domain-lifecycle subsections (jurisdictions → onboarding → registrations/POA → payroll runs/impounds → funding failures/credit posture → deposits/lateness → returns/two liability views/shortfall → amendments → notices → wage statements); §4 endpoint table (4 columns); §5 error catalogue (2 columns, no conditions).

**Scaffold coverage audit (all PASS):**
- **§1.1 entities (12/12):** Jurisdiction→§3.1; Client→§3.2/§3.5; JurisdictionRegistration→§3.3; PayrollRun + Impound→§3.4; FundingFailureEvent + CreditAssessment→§3.5; TaxDeposit→§3.6; TaxReturn→§3.7; ReturnAmendment→§3.8; AgencyNotice→§3.9; WageStatement→§3.10. Every entity field name verified present in backticks programmatically (0 missing).
- **§1.2 state machines (8/8, all transitions):** every from→to pair, precondition (paired with its error id), and side effect expressed — including the cyclic loops (registration rejection loop, deposit failure loop with statutory `due_date` never moving, return redraft loop, notice escalation loop, wage-statement correction chain) and all cross-entity cascades (fail/reverse → run REVERSED + SCHEDULED deposits CANCELLED + strike + CreditAssessment + 3rd-strike auto-suspend; SETTLED→RETURNED late-return loop leaving the run SETTLED; amendment accept → return AMENDED + new FILED superseding return; correction issue → target ISSUED→CORRECTED).
- **§1.3 calculations (8/8):** impound_amount, settlement_timing (2 business days / end-of-day, weekend-only roll, Friday→Tuesday), deposit_due_date (all three frequency branches), late_deposit_penalty (inclusive tier edges), agency_liability_reconciliation (both bureau-books and agency-confirmed variants + divergence condition), shortfall_penalty (pinned evaluation order, inclusive safe-harbor threshold), client_credit_risk_posture (count vs weighted views, inclusive thresholds, count-keyed suspension), wage_statement_annual_total (both as-issued and as-filed-history variants), registration_interim_gate (incl. no-rewrite propagation).
- **§1.4 validations (24/24):** every check paired with its exact `error_id` + HTTP status in §2/§3 prose; global priority layering stated explicitly in §2.8/§2.9; all `applies_to` scopes enumerated.
- **§1.5 endpoints (80/80):** all in the §4 table; role lists programmatically diffed against the scaffold (0 mismatches).
- **§1.6 errors (23/23):** all in the §5 table with matching statuses, none extra, each mentioned in §2/§3 prose. (`ERR_PENDING_IMPOUNDS` appears only in a state-machine precondition, not the catalog — kept in prose only, excluded from §5.)
- **§1.7 roles (5/5):** exact spellings, identity semantics translated per role (entity-backed ClientPayrollAdmin vs opaque bureau roles).

**Hard-contract reports:** Field coverage 98 required / 98 present / 0 missing (PASS, two passes — second pass caught the 12 standalone path-param identifiers, added to §2.8). §3 path purity: 449 backtick tokens scanned, 0 violations (PASS). No pseudocode operators, fuzzy words, or `>=`-style syntax in prose (regex-verified). §2.2 emitted verbatim from the canonical block.

**No-leak confirmation:** no worked example numbers, no `test_recipe` content, and no difficulty/corner-design material exists in the PRD — the only numeric constants are the scaffold's own business constants (2026-09-01 clock start, 2 business days, day-15/quarter-end due dates, tier day boundaries 5/15/16, posture weights 2/1 and thresholds 1/3/4, strike limit 3), all expressed as rules rather than worked computations.

## Step 5: Generate unit tests — 2026-09-29T22:55:00.000Z

Generation complete for `task_3083_payroll_service_bureau_tax_filing_agency_client`.

### Test counts by queue

- **Queue A (Difficulty)**: 18/18 instances covered, every instance at ≥2 tests (36+ tests tagged `Design: Difficulty/...`).
- **Queue B (Corner)**: 47/47 non-stub instances covered, every instance at ≥1 test; 4 `excluded_because:` stubs were NOT translated (all four cross-references verified to resolve to real difficulty instances: `sm_deposit_submit_requires_run_settled_guard`, `v_duplicate_deposit_returns_domain_error`, `ep_summary_is_computed_read`, `k_failed_leg_compensates_prior_legs`).

**Total: 126 tests**, all byte-compiled cleanly. A scripted audit confirmed all 126 docstrings carry exactly one `Design:` tag, and every tag resolves to a real instance name in the source yamls — no untagged, dual-tagged, or dangling tags.

### Instances skipped under the PRD-first filter

None. Every non-stub instance in both indices had verbatim PRD coverage with a uniquely-derived outcome. Two translation decisions worth noting:

- `l_wire_missed_creates_lighter_strike` — its literal headline claim ("1 NSF + 1 wire miss → ELEVATED not HIGH") is structurally unreachable (wire misses require a HIGH-posture WIRE_REQUIRED run, and HIGH requires base ≥ 4, so any wire-miss scenario already has base ≥ 4 → HIGH). I translated the PRD-derivable core instead: `miss-wire` produces a WIRE_NOT_CONFIRMED event, fails the impound, reverses the run, suspends on the third count, and NSF (weight 2) vs wire (weight 1) weighting per PRD §3.5.
- `c_settlement_timing_weekend_rollover`'s clock-moved-backward assertion line was dropped (PRD says nothing about backward clock moves); the due_by assertions themselves are fully PRD-covered.

### `test_helpers/` inventory

`__init__.py` (barrel), `types.py` (12 entity TypedDicts + status/role enums; FundingFailureEvent correctly omits `updated_at`/`version` per PRD §2.4), `api_client.py` (ApiClient with one method per PRD §4 endpoint), `api_errors.py` (23 error IDs with §5 HTTP statuses, registered via `set_error_http_status_map`), `assertions.py` (per-entity shape assertions), `factories.py` (input-field-only payload factories), `constants.py` (clock default, tier boundaries, posture weights), `test_users.py` (opaque role constants incl. two distinct filer identities for SoD, plus mandatory `make_client_admin_headers(client_id)` for the entity-backed role), `fixtures.py` (composite builders: `setup_active_client`, `create_settled_run`, `create_confirmed_deposit`, `create_accepted_return`, `create_nsf_strikes`, version-fetch helpers, `set_clock`).

### `test_suite/` inventory

`conftest.py` + nine domain-named files: `test_01_client_onboarding.py`, `test_02_payroll_runs_impounds.py`, `test_03_deposits_penalties.py`, `test_04_returns_liability.py`, `test_05_funding_risk_suspension.py`, `test_06_notices_amendments.py`, `test_07_wage_statements.py`, `test_08_rbac_auth_sod.py`, `test_09_infrastructure.py`.

Every emitted test carries exactly one `Design:` tag as its docstring's final line — confirmed by the automated audit (126/126, zero bad). No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no freelance tests outside the two design indices.

## Step 6: Generate implementation — 2026-09-29T23:35:00.000Z

Cold boot is clean with an empty store. Implementation is complete.

### File inventory — `workspace/implementation/`

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 8 | Guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py` |
| `requirements.txt` | 1 | flask>=2.0,<4.0 |
| `app.py` | 55 | Flask factory, ApiError/404/405 handlers, blueprint registration, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 36 | In-memory store, logical clock pinned at `2026-09-01T00:00:00Z`, monotonic `_seq` |
| `errors.py` | 105 | ApiError + one factory per error ID (all 23 from §5) |
| `response.py` | 43 | Envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type`, `data` |
| `middleware.py` | 45 | Priority 1–3 auth: role header check, role RBAC, ClientPayrollAdmin entity-backed identity |
| `services_common.py` | 118 | Timestamps (3-frac-digit ISO), `_seq`-tiebroken created-asc sort, pagination (limit 1–100 default 10, offset), business-day add, `public()` serializer |
| `services_calc.py` | 214 | All calculation rules (below) |
| `services_strikes.py` | 80 | Funding-strike application, cure, scheduled-deposit cancellation cascade |
| 11 `routes_*.py` | 1764 | All 80 endpoints |

### Endpoint coverage vs PRD §4 — all 80 implemented
Clock (2), jurisdictions (3), clients (11 incl. credit-hold, funding-failures, credit-assessments sub-resources), registrations (7), payroll runs (7), impounds (7), funding failures (3), deposits (7), returns (9 incl. amendments/notices sub-lists), amendments (7), notices (7), wage statements (5 + summary), credit assessments (2).

### State machines (all 8, in respective route modules)
Client (PROSPECT→ONBOARDING→ACTIVE→SUSPENDED/TERMINATED, auto-suspend on 3rd strike), JurisdictionRegistration (PENDING⇄REJECTED→VERIFIED), PayrollRun (DRAFT→SUBMITTED→IMPOUNDED→SETTLED/REVERSED/CANCELLED), Impound (PENDING→SETTLED→RETURNED, PENDING→FAILED), TaxDeposit (SCHEDULED⇄SUBMITTED/FAILED→CONFIRMED/CANCELLED), TaxReturn (DRAFT⇄FILED/REJECTED→ACCEPTED→RECONCILED, →AMENDED on amendment accept), ReturnAmendment (DRAFT⇄FILED/REJECTED→ACCEPTED with supersession cascade), AgencyNotice (OPEN⇄IN_REVIEW⇄ESCALATED→RESOLVED_*→CLOSED), WageStatement (DRAFT→ISSUED→CORRECTED/VOIDED with correction-chain flip).

### Calculations (`services_calc.py`)
- `impound_amount` = gross + tax (int cents)
- `settlement_timing` — STANDARD = +2 business days (weekend roll only); WIRE_REQUIRED = 23:59:59Z same day
- `deposit_due_date` — SEMIWEEKLY Wed/Thu/Fri→next-Wed / Sat–Tue→next-Fri strictly-after, MONTHLY→15th of next month, QUARTERLY→quarter-end month (Apr 30/Jul 31/Oct 31/Jan 31)
- `late_deposit_penalty` — Decimal ROUND_HALF_UP, inclusive tiers 1–5 / 6–15 / 16+, recomputed on read of CONFIRMED
- `agency_liability_reconciliation` — both variants: bureau-books (SUBMITTED/IMPOUNDED/SETTLED runs in period; re-derived on GET of FILED/ACCEPTED) and agency-confirmed (CONFIRMED deposits; frozen at reconcile)
- `shortfall_penalty` — pinned order: liability → safe harbor (>= threshold inclusive) → shortfall × tier by days from quarter end to filing
- `client_credit_risk_posture` — dual view: count drives 3-strike suspension; weighted base (NSF=2, WIRE_NOT_CONFIRMED=1) drives NORMAL/ELEVATED(2–3)/HIGH(>=4); CreditAssessment appended on every recompute with FUNDING_FAILURE / FAILURE_CURED / MANUAL_REVIEW triggers
- `wage_statement_annual_total` — as-issued vs as-filed-history (`include_voided`) variants, `voided_total_cents` always reported

### Cascades & cross-aggregate version bumps
Impound fail/miss-wire/reverse → run REVERSED + SCHEDULED deposits CANCELLED (each touched) + strike + assessment + Client version; settle → run SETTLED + run version; correction issue → target ISSUED→CORRECTED both versions bumped; amendment accept → return AMENDED + new FILED return with `supersedes_return_id` and `expected_liability_cents = adjusted_liability_cents`.

### OCC rules (all 3, HTTP 412)
`expected_payroll_run_version` on POST /payroll-runs/{id}/deposits; `expected_client_version` on POST /returns and POST /payroll-runs/{id}/initiate-impound.

### Contract confirmation
- `start.sh` reads `$PORT` (default 10000 in app.py), binds `0.0.0.0`, runs foreground via `exec`, guards pip install behind an import check
- Storage is in-memory only; cold boot verified empty (0 clients, 0 jurisdictions); no seeding anywhere (`grep seed` clean)
- Boots cleanly from a fresh process and passes end-to-end smoke tests covering strikes→suspension→cure→reactivation, WIRE_REQUIRED settle gating, late returns, SoD (filer-blocked accept/reconcile, amendment accept), notice-blocked reconciliation, amendment supersession, correction chain with voided summary variants, OCC 412s, duplicate/exceeds deposit guards, MANUAL_INTERIM filing, and tier-2 late-penalty math (6 days late → 5% = 500 on 10000)

## Step 7: Test-fix iteration loop — 2026-09-30T00:05:00.000Z

All 8 rounds pass 126/126. Clean exit.

### Summary

**Iterations run:** 3 (baseline 104/126 → 122/126 → clean 126/126 across all 8 parallel rounds).

**Tests deleted:** none. Every failing test traced to verbatim PRD prose; no deletions were warranted.

**Fixes applied to `test_suite/`:**
- `test_09_infrastructure.py` (`test_settlement_timing_weekend_rollover`) — the Wednesday leg asserted `due_by` 2026-09-03 (start-day-counting), which contradicts the PRD §2.6 example "adding two business days to a Friday initiation lands on the following Tuesday" (tomorrow-counting) and the test's own Friday leg plus the already-passing weekday tests. Corrected the Wednesday expectation to 2026-09-04 (Thu=day1, Fri=day2) to match the PRD-pinned semantics.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `routes_returns.py` `file_return` — replaced the invented 30-day `FILING_WINDOW_DAYS` with period close at the start of the day after the period's final day. PRD §3.7 names "the jurisdiction's filing window" but never defines its length; the only uniquely derivable reading consistent with every test (filing on the last day rejected, filing from the next day onward accepted) is close-at-next-midnight. This one root cause drove 19 of the 22 baseline failures (returns liability, shortfall penalties, period-close gates, notice-gated reconcile, registration-gated filing, amendment cascades, SoD).
- `routes_returns.py` `ret_view` — stopped re-deriving bureau-books liability for amendment-created supersession returns (`supersedes_return_id` set), whose `expected_liability_cents` is pinned to the amendment's `adjusted_liability_cents` per PRD §3.8.
- `routes_payroll.py` `initiate_impound` — reordered validation so the OCC `expected_client_version` shape check and the client credit gates (`ERR_CLIENT_NOT_ACTIVE`, `ERR_CREDIT_HOLD_ACTIVE`) run before the run's SUBMITTED state check. PRD §3.4 blocks initiation for a non-ACTIVE client with `ERR_CLIENT_NOT_ACTIVE`, and the test initiates against a still-DRAFT run on a SUSPENDED client.
- `routes_wage_statements.py` `issue_statement` and `_active_exists` — the duplicate-active gate now counts only `ISSUED` rows as active (dropping `CORRECTED`). PRD §3.10's invariant is "exactly one statement is ever active per employee key" and the summary section explicitly calls CORRECTED rows "superseded predecessors"; counting them as active broke the PRD-sanctioned correction-of-a-correction chain.

No skip/xfail was added, no assertion was weakened, no endpoint or field was added beyond PRD, and storage remains in-memory only.

## Step 8: Finalize PRD — 2026-09-30T00:15:00.000Z

All four edits applied cleanly; no line-count drift (same 327 lines, edits are inline revisions within three paragraphs).

### Summary

**Line counts:** PRD.md 327 lines → PRD_FINALIZED.md 327 lines (0% delta; all edits are inline revisions inside existing paragraphs, no sections added).

**Changes:**
- §3.4 — revise — pinned the initiate-impound evaluation order: `expected_client_version` shape/OCC checks first, then client `ACTIVE`/credit-hold gates, then the run's `SUBMITTED` state check — `implementation/routes_payroll.py:136-152`
- §3.7 — revise — replaced the undefined "period end plus the jurisdiction's filing window" with the pinned semantics: the period closes at 00:00:00Z on the day after the period's final day; filing on the last day or earlier is `ERR_PERIOD_NOT_CLOSED`, earliest accepted filing is the next day — `implementation/routes_returns.py:144-148`
- §3.7 — revise — scoped the bureau-books re-derivation on reads of FILED/ACCEPTED returns with an exception: amendment-created supersession returns (`supersedes_return_id` set) keep `expected_liability_cents` pinned to the amendment's `adjusted_liability_cents` — `implementation/routes_returns.py:29-31`, `implementation/routes_amendments.py:118-131`
- §3.10 — revise — the duplicate-active gate counts only `ISSUED` rows (was "ISSUED or CORRECTED"); CORRECTED rows are superseded predecessors and do not block a further correction — `implementation/routes_wage_statements.py:25-32,152-160`

**Step 7 item not edited:** the `test_09_infrastructure.py` Wednesday-leg fix was a test-fixture correction (the test contradicted the PRD's own tomorrow-counting example); PRD §2.6 already pins the correct semantics and `services_common.py:110-121` matches, so no PRD change.

**Per-edit pre-edit search log:**

- **Edit 1 (§3.7 temporal gate):** (a) subject = period-close gate at filing. (b) enumerated paths: grep for `period_not_closed|period_bounds|close_at` across implementation — `routes_returns.py:144-148` is the sole gate; `period_bounds` (`services_calc.py:43-46`) also feeds the liability sums (`:121,:139`) but the gate sentence only defines close timing, not period bounds, so no conflict. (c) none needed.
- **Edit 2 (§3.7 re-derivation exception):** (a) subject = which returns re-derive `expected_liability_cents` on reads. (b) enumerated paths: all `expected_liability_cents`/`supersedes_return_id` references — `routes_returns.py:23-31,82,85,152,217`; `routes_amendments.py:124,127`; `services_calc.py:161,174`. Reconcile (`:217`) overwrites the field under the agency-confirmed view and RECONCILED status is outside the re-derivation sentence's FILED/ACCEPTED scope, so the exception does not mis-describe reconcile. (c) scoped the exception to FILED/ACCEPTED reads of supersession returns only.
- **Edit 3 (§3.4 validation order):** (a) subject = gate evaluation order on impound initiation. (b) enumerated paths: `routes_payroll.py:130-152` (auth → identity → run existence → OCC shape/equality → client gates → run state); cross-checked §2.8's generic priority (shape before state before business) — the client gates are business checks here and the impl runs them before the run-state check, so the new sentence pins order for this action explicitly without contradicting §2.8's generic layering. `cancel_run` (`:177-186`) has no client gates and is untouched. (c) wording pinned to "this action" to avoid a universal claim.
- **Edit 4 (§3.10 active definition):** (a) subject = statuses counted as active for the duplicate gate. (b) enumerated paths: `routes_wage_statements.py:25-32` (creation gate), `:152-160` (issue gate with target exemption), `:201-218` (summary, already ISSUED-only), `:173-182` (void accepts ISSUED or CORRECTED — separate prose, unchanged and still accurate). (c) added the "only ISSUED rows count as active for this gate" clause rather than redefining "active" globally, so void eligibility and the CORRECTED-target flip prose remain consistent.

Output file: `workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD scan — 2026-09-30T00:35:00.000Z

The diff confirms all edits applied cleanly (one accidental double-insert was found and repaired during the process). Final summary:

**Source:** `PRD_FINALIZED.md` (327 lines, 52,328 chars) → `PRD_COMPLETED.md` (328 lines, 55,588 chars; +3,260 chars). File: `workspace/PRD_COMPLETED.md`

**Counts:** 26 ambiguity-pins (inserts), 2 mismatch-revisions (revises) — 28 change hunks total.

**Changes:**

- §2 intro — insert — ambiguity — unmatched paths and unsupported methods surface as `ERR_NOT_FOUND` (404) — implementation/app.py:18-23
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the wall clock, not the logical clock — implementation/response.py:9-12
- §2.2 — insert — ambiguity — envelope also wraps clock setter (`current_utc`), probe (`{"ok": true}`), and wage-statement summary aggregate — implementation/routes_clock.py:26,33; implementation/routes_wage_statements.py:213
- §2.3 — insert — ambiguity — list sort ties broken by creation sequence — implementation/services_common.py:94-95
- §2.5 — insert — ambiguity — new deposits stored with `late_days` 0 / `penalty_exposure_cents` 0 until confirmed — implementation/routes_deposits.py:97-98
- §2.5 — insert — ambiguity — `due_by`/`due_date` serialized to second precision; lateness/shortfall-day math on date portions — implementation/services_common.py:24-28; implementation/services_calc.py:112,179-180
- §3.1 — insert — ambiguity — inactive jurisdiction refuses registrations and deposits with `ERR_INVALID_REQUEST` — implementation/routes_jurisdictions.py:32-33; implementation/routes_deposits.py:64-65
- §3.2 — revise — mismatch — activation gate order pinned as credit-hold first, then verified-jurisdiction (PRD listed the checks in the opposite order) — implementation/routes_clients.py:97-105
- §3.2 — insert — ambiguity — termination sweep check order: impounds → deposits → notices → runs; `ERR_PENDING_IMPOUNDS` status 409 — implementation/routes_clients.py:120-131
- §3.3 — insert — ambiguity — `poa_document_ref`/`agency_account_number` optional at creation, mandatory at verify — implementation/routes_registrations.py:34-38,103
- §3.3 — insert — ambiguity — downstream registration gates consult the most recently created registration for the pair — implementation/services_calc.py:207-214
- §3.4 — insert — ambiguity — no client-status gate at run draft; ACTIVE enforced at submission — implementation/routes_payroll.py:32-80
- §3.4 — insert — ambiguity — cancel defined only from `SUBMITTED`; run list filters are `client_id` and `status` — implementation/routes_payroll.py:182,90-95
- §3.4 — revise — ambiguity — direct reversal requires run `IMPOUNDED` and impound `PENDING` (not merely "a settled run") — implementation/routes_payroll.py:194-203
- §3.4 — insert — ambiguity — confirm-wire/miss-wire gated on `WIRE_REQUIRED` funding model and `PENDING` impound — implementation/routes_impounds.py:113-117,128-132
- §3.5 — revise — ambiguity — reactivation check order pinned: credit-hold first, then unresolved-failures — implementation/routes_clients.py:144-150
- §3.6 — insert — ambiguity — no run-state gate at deposit scheduling; guard order inactive → OCC → duplicate → cap — implementation/routes_deposits.py:38-83
- §3.6 — insert — ambiguity — `confirmed_at` left untouched by the fail/reschedule loop — implementation/routes_deposits.py:193-196
- §3.7 — insert — ambiguity — missing registration (not just `REJECTED`) blocks return creation with `ERR_REGISTRATION_NOT_VERIFIED` — implementation/routes_returns.py:71-73
- §3.7 — insert — ambiguity — period closes at 00:00:00Z the day after; earliest accepted filing is any time from 00:00:00Z that day — implementation/routes_returns.py:144-148
- §3.7 — insert — ambiguity — agency-confirmed view: deposit's quarter counts when its start date lies inside the period — implementation/services_calc.py:148-155
- §3.8 — insert — ambiguity — supersession return copies the amended return's `filing_method` — implementation/routes_amendments.py:122
- §3.9 — insert — ambiguity — `received_at`/`response_due_at` stored verbatim as supplied — implementation/routes_notices.py:60-65,73-74
- §3.9 — insert — ambiguity — resolve allowed only from `IN_REVIEW`; close only from the resolved states — implementation/routes_notices.py:132,170
- §3.10 — revise — mismatch — create-time `ERR_DUPLICATE_ACTIVE_STATEMENT` applies to `ORIGINAL` only; a `CORRECTION`'s duplicate exposure is enforced at issuance (PRD implied the check applied at both creation paths) — implementation/routes_wage_statements.py:64-76,152-160
- §3.10 — revise — ambiguity — issue gates ordered year-close first, then uniqueness; correction target exempt from the uniqueness scan — implementation/routes_wage_statements.py:143-160
- §3.10 — insert — ambiguity — `include_voided` on the list endpoint is a visibility filter (VOIDED excluded unless true) — implementation/routes_wage_statements.py:119-121
- §5 — insert — ambiguity — `ERR_PENDING_IMPOUNDS` (HTTP 409) row added to the error catalogue — implementation/errors.py:104-105; implementation/routes_clients.py:122

No new sections added; all changes are in-paragraph inserts/revisions. Everything else in the implementation (OCC guards, SoD scope, business-day arithmetic, semiweekly/monthly/quarterly due-date formulas, tier boundaries, strike weighting and 3-strike suspension, per-run vs per-client version increments, FundingFailureEvent field shape, amendment supersession chain) was already pinned uniquely by the PRD and left untouched.
