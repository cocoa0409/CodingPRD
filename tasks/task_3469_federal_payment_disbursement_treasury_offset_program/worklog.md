# Worklog — task_3469_federal_payment_disbursement_treasury_offset_program

## Step 1: Create Task Directory — 2026-10-02T10:53:00.000Z

Pre-allocated task directory verified: `tasks/task_3469_federal_payment_disbursement_treasury_offset_program/` exists with empty `workspace/` inside. No new index computed; no other task directory created.

## Step 2: Generate Scaffold — 2026-10-02T11:56:00.000Z

All three artifacts are written, parse cleanly, and pass `scaffold_lint.py` with a clean verdict (710 design calls scanned, 0 violations; all FKs reverse-reachable).

**Task:** `task_3469_federal_payment_disbursement_treasury_offset_program` — Federal Payment Disbursement & Treasury Offset Program. Archetype: compliance/audit + ledger reconciliation; flat topology (root-level peer collections, empty `api_prefix`); segregation-of-duties role model; immediate consistency; logical clock defaulting to `2026-09-01T00:00:00Z`.

**Counts**
- Entities: 13 (CreditorAgency, Payee, ExemptionPolicy, Debt, PaymentFile, Payment, Offset, RefundClaim, CollectionAgency, CollectionAction, ReverseOffsetRequest, ReciprocalAgreement, DoNotPayRecord)
- State machines: 10 — including cyclic Debt (re-referral + reopen loops), dual-independent-axis Payment (processing_status × integrity_status), and RefundClaim with a capped appeal loop
- Endpoints: 40 (deliberately held at the known-safe boundary — >40 risks impl-gen breakage)
- Calculations: 11
- Validation priority rows: 11
- Errors: 34 (every one exercised by at least one design instance)
- Roles: 8 (incl. System); CreditorAnalyst is `entity_backed:CreditorAgency`, all others opaque
- Concurrency rules: 2 true OCC races only (payment re-evaluate supersede; garnishment collect against stale debt version)
- **§1.8 difficulty instances: 19** (9 rules × ≥2; `combinatorial_formula` has 3 covering modes (a), (b), (c))
- **§1.9 corner instances: 59** (52 active + 7 `excluded_because` stubs, all resolving to real §1.8 instances)

**Notable design decisions / self-contradictions resolved**
1. **Endpoint-budget vs FK-lattice conflict:** the linter's FK check requires a single-resource GET per FK child to derive its collection segment, forcing me to restore `GET /offsets/{id}`, `/refund-claims/{id}`, `/collection-actions/{id}`. Compensated by removing `POST /debts/{id}/return` (RETURNED now reachable only via the refund-approval system cascade), `POST /reciprocal-agreements/{id}/terminate` (replaced by half-open window expiry — a stronger temporal test), and `GET /reverse-offset-requests/{id}` (expiry observed via terminal-flip `ERR_INVALID_STATE` on re-confirm). All dependent instances reworked and replayed.
2. **Dual-variant masking bug caught pre-write:** the naive variants (flat $750 floor vs max(floor, 25%)) were indistinguishable because the 15% cap always bound first. Redesigned as INTAKE_ESTIMATE (protected minimum only, no pct cap — agency-facing projection) vs EXECUTION_FINAL (cap applied) — same inputs give 125000 vs 30000.
3. **Mode-(b) rounding pinned with a computed 1-cent divergence:** two 33337-cent payments → per-payment round-then-sum 10002 vs forbidden sum-then-round 10001; asserted as a literal.
4. **Mode-(c) circular dependency pinned:** remittance fee tier reads the creditor's pre-event YTD gross; the 60000-cent threshold lands exactly between events 2 and 3 → fees 900/900/600.
5. **Interval semantics deliberately opposite:** reciprocal agreements are half-open `[from, until)` (adjacency legal); do-not-pay records are closed `[from, until]` (touching conflicts) — the rule-8 pair.
6. **Refund ≠ reversal semantics:** reversal restores balances and reopens PAID_IN_FULL; refund pays the payee, claws back net remittance only (Treasury absorbs the fee), and sends the debt to RETURNED *without* balance restoration — two distinct compensating invariants for rule 9.

**Files**
- `SCAFFOLD.yaml` (1420 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1272 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (2181 lines)

Orchestrator verification: all three files parse as YAML; SCAFFOLD.yaml contains neither design key; 13 entities / 40 endpoints confirmed; domain tokens (payment/offset/debt/creditor/payee) present throughout — no foreign-domain leakage.

## Step 3: Copy Shared Files — 2026-10-02T11:56:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T12:15:00.000Z

PRD generation complete. All three Hard Contracts pass.

**Output:** `workspace/PRD.md` — **337 lines**. The withheld design-index files were never opened.

**Section list:** §1 Introduction (3 paragraphs); §2 Global Specifications with 11 subsections (2.1 RBAC, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties, 2.6 Monetary Precision, 2.7 OCC, 2.8 Validation Order, 2.9 Creditor Remittance Ledgers, 2.10 Reciprocal Agreement Coverage, 2.11 Do-Not-Pay Screen); §3 Business Logic with 9 lifecycle-ordered subsections; §4 Endpoint table (40 rows, 4 columns); §5 Error Catalogue (34 rows, 2 columns).

**Scaffold → PRD mapping:**
- `scenario` → §1; `roles` (incl. `identity:` fields, `System` never callable) → §2.1
- `response_envelope` → §2.2 (byte-verbatim) + §2.3 (limit 10/1/100, offset 0, `created_at` ascending)
- `complexity_profile` (logical clock, OCC, cascades, scheduled actions, selector policy) → §2.4, §2.7, §3.5/§3.9 cascades, §3.7 selector
- `entities` (13) → §2.5 common fields; per-entity fields/defaults scattered across §3.1–§3.9
- `state_machines` (10, all transitions/preconditions/side effects) → §3.2–§3.9 via state-pair framing
- `concurrency_rules` (2) → §2.7 (write endpoint, `expected_payment_version`/`expected_debt_version`, `ERR_STALE_VERSION` 412, purely version-based)
- `calculations` (11) → §2.6/§2.9 (pinned rounding order, fee tier steps), §3.3 (priority ranks), §3.4 (INTAKE_ESTIMATE vs EXECUTION_FINAL, waterfall), §3.7 (AWG PROVISIONAL vs STATUTORY_FINAL), §3.6 (refund restitution), §3.8 (reverse waterfall)
- `validations` (11 tiers) → §2.8 ordered cascade with first-failure-wins semantics, triggers re-stated at each workflow
- `endpoints` (40) → §4 table; `errors` (34) → §5 table + in-prose triggers

**Hard Contract reports:**
```
Field coverage check: 95 required (entities + request_body + query_params + path_params), 95 present, 0 missing — PASS
Rule coverage check: 11 validation tiers ordered in prose; 2/2 OCC rules fully named; all 10 state machines' transitions expressed; 11/11 calculations reconstructed in prose; 34/34 errors matchable to triggers; all endpoint side_effects expressed; sibling branches symmetric — PASS
Path purity check (§3 only): 447 backtick tokens scanned, 0 path/method violations — PASS
```
Plus: §2.2 byte-identical to `section-2.2-response-structure.md`; endpoint table exactly matches scaffold (method, path) ×40; all 67 enum/state strings present verbatim; constants embedded as prose (60,000 cents/$600 tier, 3%/2% fees, 65% child-support cap, 15% garnishment, 21,750-cent weekly floor, 30/15/180/30/10-day windows, clock default 2026-09-01T00:00:00Z); no fuzzy words or operator pseudocode.

**Zero-Silence judgment calls (rules rendered in full prose because tests may assert them):**
1. **PROPOSED offsets dropped on debt return** — the `Offset.status` field description ("PROPOSED → DROPPED on re-evaluation *or debt return*") has no state-machine transition; I added it as a sentence in §3.6's refund cascade rather than dropping the sibling trigger.
2. **NO_MATCH is terminal for confirm** — the `ReverseOffsetRequest.status` description loosely reads "MATCHED | NO_MATCH → CONFIRMED", but the transitions table and confirm precondition (`status == MATCHED` else `ERR_INVALID_STATE`) are authoritative; the PRD states NO_MATCH is terminal.
3. **Selector eligibility** — the scaffold names a "ranked eligible pool" without a ranking key; I rendered eligibility as "agencies that can still accept another open action under `capacity_max_active`" (from the field's own description) without inventing a ranking criterion.
4. **Version initial value** — scaffold specifies only "integer, increments on mutation"; §2.5 deliberately does not state a starting value.
5. **Equality boundaries** — each temporal gate's inclusivity is stated explicitly (30-day and 15-day windows activate at equality; confirm allowed on `expires_at`; DNP interval closed on both ends; agreement window half-open; touching DNP intervals conflict).

Orchestrator verification: PRD.md exists at 336 lines (wc), §1/§2.1 headers and role model present, 78 table rows (endpoint + error tables).

## Step 5a: Generate test_helpers/ — 2026-10-02T12:45:00.000Z

Stage 1 of 2 (helpers only — no test_suite/ created). All 9 files compile (`py_compile`) and the package imports cleanly (`import test_helpers.fixtures` with task dir on PYTHONPATH). Calculation helpers spot-checked against every pre-computed literal in both design indices (125000 vs 30000 dual-variant; 5001+5001=10002 round-then-sum; 900/900/600 fee tiers; 3750/3263 provisional vs 3250/0 statutory AWG; fee 98 → net 3152) — all reproduce exactly.

**Files written**
- `test_helpers/constants.py` — domain constants derived verbatim from PRD (see table below).
- `test_helpers/types.py` — 13 entity TypedDicts (all carry PRD §2.5 common fields: id/created_at/updated_at/version) + 20 status/field enums incl. UserRole with SYSTEM marked never-callable.
- `test_helpers/api_errors.py` — `ApiErrorId` enum (34 ids) + `HTTP_STATUS_CODES` map, registered with the framework via `set_error_http_status_map` at import time.
- `test_helpers/api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (40 methods) + module-level `api_client` singleton; root-level paths (api_prefix ""), clock endpoint at `/_clock/set_current_utc` unprefixed per PRD §2.4.
- `test_helpers/test_users.py` — `TEST_USERS` shared headers for all 7 callable roles (opaque) + `make_*_headers` builders; `make_creditor_analyst_headers(creditor_agency_id)` is mandatory for entity-backed CreditorAnalyst calls; canonical ids op-1 (operator) vs ro-1/ro-2 (officers) make segregation-of-duties pass by default and collidable on demand via `make_refund_officer_headers("op-1")`.
- `test_helpers/factories.py` — payload factories, input fields only, with per-process unique tin/creditor_code/agency_code generators so duplicate-check tests stay deliberate.
- `test_helpers/assertions.py` — 13 `assert_<entity>` shape checkers, envelope helpers (`assert_common_fields`, `assert_created_at_ascending`), domain invariants (`assert_payment_decomposition`, `assert_refund_conservation`, `assert_file_totals`), and PRD calculation re-implementations (`round_half_up_cents`, `expected_remittance_fee_cents`, `expected_intake_projection`, `expected_execution_pool`, `expected_awg_provisional_cents`, `expected_awg_garnishment_cents`, `expected_priority_rank`).
- `test_helpers/fixtures.py` — 5-tier composite helpers (see API surface below); all setup via `get_success_data`; CreditorAnalyst identity threaded via `make_creditor_analyst_headers(creditor["id"])`; all temporal preconditions ride the logical clock (never wall time).
- `test_helpers/__init__.py` — barrel export (framework generics + all PRD-specific modules).

**Frozen helper API surface (contract for Step 5b)**

api_client (singleton; methods return raw `requests.Response`):
`set_clock(payload, headers)` · `create_creditor_agency(payload, headers)` · `get_creditor_agency(id, headers)` · `create_payee(payload, headers)` · `create_exemption_policy(payload, headers)` · `activate_exemption_policy(id, headers)` · `create_debt(payload, headers)` · `get_debt(id, headers)` · `list_debts(headers, params=None)` · `notice_debt(id, payload, headers)` · `activate_debt(id, headers)` · `create_payment_file(payload, headers)` · `get_payment_file(id, headers)` · `create_payment(file_id, payload, headers)` · `get_payment(id, headers)` · `list_payments(headers, params=None)` · `evaluate_offsets(id, payload, headers)` · `execute_payment(id, headers)` · `reverse_payment(id, headers)` · `get_offset(id, headers)` · `list_offsets(headers, params=None)` · `create_refund_claim(payload, headers)` · `get_refund_claim(id, headers)` · `list_refund_claims(headers, params=None)` · `review_refund_claim(id, headers)` · `decide_refund_claim(id, payload, headers)` · `appeal_refund_claim(id, headers)` · `create_collection_agency(payload, headers)` · `create_collection_action(debt_id, payload, headers)` · `get_collection_action(id, headers)` · `list_collection_actions(headers, params=None)` · `activate_collection_action(id, headers)` · `collect_collection_action(id, payload, headers)` · `terminate_collection_action(id, headers)` · `create_reverse_offset_request(payload, headers)` · `confirm_reverse_offset_request(id, headers)` · `create_reciprocal_agreement(payload, headers)` · `activate_reciprocal_agreement(id, headers)` · `create_do_not_pay_record(payload, headers)` · `remove_do_not_pay_record(id, headers)`

factories (all `**overrides` merge into the payload):
`unique_tin()` · `unique_code(prefix)` · `create_creditor_agency_payload()` · `create_state_creditor_payload(state_code="CA")` · `create_payee_payload()` · `create_eft_payee_payload()` · `create_exemption_policy_payload()` (defaults FULL) · `create_partial_policy_payload(payment_type="VENDOR", protected_minimum_cents=75000, max_offset_pct=0.15)` · `create_debt_payload(creditor_agency_id)` (REFERRED start) · `create_noticed_debt_payload(creditor_agency_id)` · `create_notice_payload()` · `create_payment_file_payload()` · `create_payment_payload(payee, amount_cents=30000, payment_type="SALARY")` (payee_tin auto-matches payee) · `create_evaluate_payload(expected_payment_version)` · `create_refund_claim_payload(offset_id, claimed_amount_cents=10000, reason="DEBT_NOT_OWED")` · `create_decision_payload(decision="APPROVE")` · `create_collection_agency_payload()` · `create_awg_action_payload()` · `create_cross_servicing_action_payload()` · `create_collect_payload(expected_debt_version, ...)` · `create_reverse_offset_request_payload()` · `create_reciprocal_agreement_payload(state_code="WA", direction="STATE_TO_FED")` · `create_do_not_pay_record_payload(tin=None)`

test_users: `TEST_USERS` dict keys: `treasury_supervisor_headers`, `treasury_operator_headers` (op-1), `treasury_operator_2_headers` (op-2), `payment_agency_analyst_headers`, `state_coordinator_headers`, `refund_officer_headers` (ro-1), `refund_officer_2_headers` (ro-2), `auditor_headers`, `creditor_analyst_headers` (unbound fallback only). Builders: `make_creditor_analyst_headers(creditor_agency_id)` (REQUIRED for debt create/notice/activate), `make_treasury_supervisor_headers(user_id="sup-1")`, `make_treasury_operator_headers(user_id="op-1")`, `make_payment_agency_analyst_headers(user_id="paa-1")`, `make_state_coordinator_headers(user_id="sc-1")`, `make_refund_officer_headers(user_id="ro-1")`, `make_auditor_headers(user_id="aud-1")`.

fixtures (return parsed `data` payloads; composites return namespace dicts):
- Clock/atomic: `set_logical_clock(current_utc=CLOCK_DEFAULT_UTC)` · `create_federal_creditor()` · `create_state_creditor(state_code="CA")` · `register_payee()` (CHECK) · `register_eft_payee()` · `create_draft_policy(payment_type, exemption_class)` · `activate_policy(policy)` · `create_active_policy(payment_type="VENDOR", exemption_class="FULL")` · `register_collection_agency()`
- State progression: `refer_debt(creditor)` · `record_notice(debt, creditor)` · `activate_debt(debt, creditor)` · `create_active_debt(creditor, notice_sent_at=DEFAULT_NOTICE_SENT_AT, due_process_completed=True, ensure_agreement=False, **overrides)` (notice-at-intake shortcut → activate; 30-day window satisfied at default clock; `ensure_agreement=True` pre-creates a FED_TO_STATE agreement for STATE creditors) · `create_active_agreement(state_code="WA", direction="STATE_TO_FED", window=DEFAULT_AGREEMENT_WINDOW)` · `create_payment_file()` · `add_payment(payment_file, payee, amount_cents=30000, payment_type="SALARY")` · `evaluate_payment(payment, operator_headers=None)` (OCC token read from the passed payment's version; returns bumped payment) · `execute_payment(payment, operator_headers=None)` · `reverse_payment(payment, operator_headers=None)` · `create_awg_action(debt)` · `create_cross_servicing_action(debt)` · `activate_action(action)` · `collect_awg(action, debt_id, disposable_pay_cents)` (re-reads debt for OCC token) · `collect_cross_servicing(action, debt_id, remitted_amount_cents)` · `terminate_action(action)` · `create_dnp_record(tin, window=DEFAULT_DNP_WINDOW, list_source="SAM_EXCLUSION")` · `remove_dnp_record(record)` · `create_reverse_request(state_code="WA", payee_tin="111-22-3333", requested_amount_cents=50000)` · `confirm_reverse_request(request)` · `file_refund_claim(offset, claimed_amount_cents=None, reason="DEBT_NOT_OWED")` (defaults to full offset amount) · `review_claim(claim, officer_headers=None)` · `decide_claim(claim, decision="APPROVE", officer_headers=None)` · `appeal_claim(claim, operator_headers=None)`
- Read-backs (as Auditor): `read_creditor(id)` · `read_debt(id)` · `read_payment(id)` · `read_payment_file(id)` · `read_offset(id)` · `read_refund_claim(id)` · `read_collection_action(id)` · `list_payment_offsets(payment_id, status=None)` · `list_debt_collection_actions(debt_id)`
- Composites: `setup_creditor_with_active_debt(creditor=None, set_clock=True, **debt_overrides)` → (creditor, debt) · `setup_evaluated_payment(amount_cents=30000, debt_amount_cents=50000, payment_type="SALARY", exemption_class="FULL", policy_overrides=None, tin="111-22-3333", payee_overrides=None, file_overrides=None, debt_overrides=None, creditor=None, payee=None, set_clock=True, evaluate=True)` → ns{creditor, payee, policy, debt, payment_file, payment, offsets} · `setup_applied_offset(...same..., operator_headers=None)` → ns + `offset` (payment EXECUTED, offsets APPLIED; executor op-1) · `setup_settled_payment(settlement_date=DEFAULT_SETTLEMENT_DATE, settle_clock=None, ...)` (clock sweep → SETTLED; file may reach COMPLETED) · `setup_claim_under_review(claimed_amount_cents=None, reason=..., officer_headers=None, ...)` → ns + claim UNDER_REVIEW · `setup_decided_claim(decision="APPROVE", ...)` / `setup_paid_claim(...)` / `setup_denied_claim(...)` → ns + claim decided, offset/debt/creditor re-read · `execute_payment_sequence(creditor, payee, payment_type, amounts, payment_file=None, operator_headers=None)` → [(payment, offsets)] in order (fee-tier accumulation) · `setup_agency_pool(capacities=(5,10,10))` → agencies in created_at order · `setup_active_collection_action(action_type="AWG", debt_amount_cents=100000, agency_capacities=None, awg_estimate_cents=25000, awg_notice_sent_at=DEFAULT_NOTICE_SENT_AT, ...)` → (creditor, debt, ACTIVE action) · `setup_reverse_request(state_code="WA", direction="STATE_TO_FED", debt_specs=((30000,"FEDERAL_TAX","2026-01-10T00:00:00Z"),), payee_tin=..., requested_amount_cents=50000, window=..., set_clock=True)` → ns{agreement, creditor, debts, request}

assertions: `round_half_up_cents(value)` · `expected_remittance_fee_cents(gross_cents, pre_event_gross_ytd_cents)` · `expected_intake_projection(amount_cents, exemption_class, protected_minimum_cents=None)` · `expected_execution_pool(amount_cents, exemption_class, protected_minimum_cents=None, max_offset_pct=None, has_child_support_match=False)` · `expected_awg_provisional_cents(estimate)` · `expected_awg_garnishment_cents(disposable_pay_cents)` · `expected_priority_rank(debt_type)` · `assert_common_fields(data)` · `assert_created_at_ascending(items)` · `assert_payment_decomposition(payment)` · `assert_refund_conservation(claim)` · `assert_file_totals(payment_file, payments)` · `assert_creditor_agency/payee/exemption_policy/debt/payment_file/payment/offset/refund_claim/collection_agency/collection_action/reverse_offset_request/reciprocal_agreement/do_not_pay_record(data)`

**Constants table (name → value → PRD source)**
- CLOCK_DEFAULT_UTC → "2026-09-01T00:00:00Z" → §2.4 ("Before it is ever set, the clock reads exactly 2026-09-01T00:00:00Z")
- PAGINATION_DEFAULT_LIMIT 10 / MIN 1 / MAX 100 / OFFSET 0 → §2.3
- NOTICE_WINDOW_DAYS 30 → §3.3 ("at least thirty days after notice_sent_at, with equality activating")
- AWG_HEARING_WINDOW_DAYS 15 → §3.7 ("at least fifteen days after its notice_sent_at — equality activates")
- CLAIM_WINDOW_DAYS 180 → §3.6 ("within 180 days of the offset's applied_at")
- APPEAL_WINDOW_DAYS 30 → §3.6 ("within thirty days of decided_at")
- REVERSE_REQUEST_TTL_DAYS 10 → §3.8 ("expires_at is fixed at creation as exactly ten days after created_at")
- REMIT_TIER_THRESHOLD_CENTS 60000 → §2.9 ("below 60,000 cents (six hundred dollars)")
- REMIT_FEE_PCT_LOW_BAND 0.03 / HIGH_BAND 0.02 → §2.9 ("three percent … and two percent")
- CHILD_SUPPORT_PCT 0.65 → §3.4 ("65 percent whenever any eligible matched debt is of type CHILD_SUPPORT")
- AWG_DISPOSABLE_PCT 0.15 → §3.7 ("fifteen percent of that disposable pay")
- AWG_WEEKLY_FLOOR_CENTS 21750 → §3.7 ("a protected weekly floor of 21,750 cents — thirty hours at the $7.25 federal minimum wage")
- PRIORITY_RANKS {CHILD_SUPPORT:10, FEDERAL_TAX:20, FEDERAL_NONTAX:30, STATE_TAX:40, STATE_OTHER:50} → §3.3
- Enum string sets (creditor types, tin types, payment types, exemption classes, debt types, payment methods, all 11 status axes, refund reasons/decisions, action types, agreement directions, DNP sources, 7 callable roles + System) → §2.1, §3.1–§3.9 verbatim
- DEFAULT_* fixture conveniences (notice 2026-08-01, delinquent 2026-01-15, settlement 2026-09-15, agreement [2026-01-01,2027-01-01), DNP [2026-08-01,2027-08-01]) are test-data choices, not PRD claims — each satisfies its PRD gate at the default clock (e.g. 2026-08-01 + 30 days < 2026-09-01).

**PRD gaps bridged in helpers**
1. Selector ranking: PRD §3.7 names a "ranked eligible pool" but (per Step 4 judgment call #3) deliberately does not state the ranking key. Helpers stay agnostic: `setup_agency_pool` registers agencies in a caller-chosen order and `create_cross_servicing_action` reads whatever `collection_agency_id` the server assigns. The corner instance asserting a specific ranking is a Stage-2 PRD-coverage adjudication, not a helpers concern.
2. Version initial value: PRD §2.5 never states the starting version. `assert_common_fields` requires only a positive int; fixtures always read the live version for OCC tokens instead of assuming 1.
3. `evaluate_payment` returns the post-evaluate payment from the response body (PRD §2.2: mutations return the updated resource); if an implementation omits fields there, fixtures' read-back helpers (`read_payment`) are the fallback.

**Known shadowing behavior (memory-confirmed):** after package init, `import test_helpers.api_client as ac` binds the *instance* (package attribute), while `importlib.import_module("test_helpers.api_client")` returns the module. The frozen contract for Step 5b is `from test_helpers import api_client` (the singleton instance) — this matches the skill's canonical pattern.

**Recipe capability audit:** all 19 §1.8 active instances and all 52 §1.9 active instances' recipes are expressible with the frozen API (dual-variant pools, round-then-sum vs sum-then-round, fee-tier YTD thresholds, half-open agreement windows vs closed DNP intervals, refund-vs-reversal compensation, OCC version fields on both guarded endpoints, segregation-of-duties header pairs, clock-driven settlement/expiry sweeps, entity-backed CreditorAnalyst identity, agency selector pools). No capability gaps.

## Step 5b — test_suite generation (2026-10-02)

Files written under test_suite/ (path + test count):
- test_suite/conftest.py — 0 tests (fixture bridge: session-scoped api + role header fixtures)
- test_suite/test_01_registry_and_access.py — 9 tests
- test_suite/test_02_debt_lifecycle.py — 7 tests
- test_suite/test_03_payment_intake.py — 9 tests
- test_suite/test_04_offset_evaluation.py — 9 tests
- test_suite/test_05_execution_settlement_reversal.py — 7 tests
- test_suite/test_06_do_not_pay.py — 4 tests
- test_suite/test_07_refund_claims.py — 9 tests
- test_suite/test_08_collections.py — 8 tests
- test_suite/test_09_reciprocity_reverse_offsets.py — 7 tests

Total tests emitted: 69 (Difficulty queue A: 19/19 instances; Corner queue B: 50/52 active instances). 7 corner stubs not translated (all excluded_because cross-references verified to resolve to real §1.8 instances).

Instances skipped (PRD-first two-condition filter), with per-instance reason:
- Corner/cross_cutting_layers/selector_ranks_fewest_open_then_spare_then_created_at — NOT uniquely derivable: PRD §3.7 states only that the selector assigns collection_agency_id "from the ranked eligible pool — the agencies that can still accept another open action under their declared capacity_max_active". PRD never states the ranking key (open count ASC, spare capacity DESC, created_at ASC); two PRD-only implementers could ship different-but-consistent rankings and the test's exact agency assignments (B then C) would fail one of them. Skipped per the brief's adjudication candidate note.
- Corner/entities/payee_create_client_supplied_version_is_ignored_input — NOT uniquely derivable: the instance asserts a create body carrying version 99 and a forged id returns 201 with server values, but PRD §2.8 tier 4 pins "no unknown fields" as ERR_INVALID_REQUEST (400), so a strict PRD-faithful implementer rejects the body while a lenient one ignores the fields; §2.5 ("server-minted", "system-managed") does not arbitrate between them. Skipped (silence pattern: ambiguous handling of client-supplied system fields).

AST tag-audit result (real ast.parse walk of every test function docstring):
- tagged tests: 69; untagged: 0; tests with >1 tag: 0; unresolved tags: 0; tags pointing at stubs: 0; duplicate tags: 0
- uncovered active instances: exactly the 2 skipped instances above (expected).
- Verbatim-citation sweep: 109 quoted citation fragments across all docstrings, all survive whitespace-normalized literal match against workspace/PRD.md (0 failures after fixing 5 fragments that had included bold markdown tier labels or an elision).

pytest --collect-only result line:
  69 tests collected in 0.29s
  (python3 -m py_compile test_suite/*.py: COMPILE_OK; PYTHONPATH=. python3 -m pytest test_suite --collect-only -q run from the task dir, collection clean — no import/package-graph errors)

Helper-contract notes observed (no helper edits made): api_client imported as the singleton via `from test_helpers import api_client` (conftest exposes it as the session `api` fixture); all CreditorAnalyst calls use make_creditor_analyst_headers(creditor["id"]); segregation-of-duties default pair (executor "op-1" / decider "ro-1") used throughout, with make_refund_officer_headers("op-1") for the collision test; OCC tokens always read from live create/read responses, never hardcoded.

## Step 6: Generate Implementation — 2026-10-02T13:20:00.000Z

The implementation is complete and verified. Final summary:

**Files written (all under `workspace/implementation/`)**

- `start.sh` — guarded launcher: pip-installs only when flask is missing, `exec python3 app.py` foreground, reads `$PORT` (default 10000), binds 0.0.0.0
- `requirements.txt` — flask>=3.0,<4
- `app.py` — Flask app factory, 13 blueprint registrations, ApiError + HTTPException envelope handlers (404/405/400/500)
- `constants.py` — clock default (2026-09-01T00:00:00Z), 7 declared roles (System excluded), pagination bounds, all enums, priority-rank map, CHILD_SUPPORT_PCT 0.65, remit tier (60000 / 0.03 / 0.02), AWG (0.15 / 21750), windows (30/15/180/30/10 days)
- `errors.py` — ApiError + all 34 PRD §5 error ids with factories and HTTP statuses
- `util.py` — UUID ids, `req_` request ids, ISO-8601 3-fractional-digit formatting, Z/offset/date-only datetime parsing, Decimal ROUND_HALF_UP cent math
- `db.py` — in-memory dict stores (13), logical clock, `_seq` insertion counter, `new_entity()` (version=1) / `touch()` (version+1, updated_at=clock); empty on boot, no seeding
- `response.py` — envelope: `meta`/`response_type`/`data`, error shape, list pagination fields inside `meta`
- `middleware.py` — header auth (tier 1), role membership (tier 2), body parsing, strict schema validator (unknown fields rejected, tier 4), pagination clamping, created_at-ordered list paging
- `serializers.py` — wire shape for all 13 entities; creditor `outstanding_receivable_cents` derived per read
- `services/ledger.py` — §2.9 pinned fee order (lazy year reset → pre-event tier → round-half-up fee → credit); reversal/clawback debits
- `services/matching.py` — active-policy lookup, agreement coverage, eligible-debt waterfall (`priority_rank, delinquent_since, created_at`), INTAKE_ESTIMATE vs EXECUTION_FINAL pools, reverse match, agency selector, agreement overlap
- `services/cascades.py` — file rollup/COMPLETED bubbling, settlement sweep, DNP hit/overlap, hold/release cascades
- `routes/`: `clock.py`, `creditors.py`, `payees.py`, `policies.py`, `debts.py`, `payment_files.py`, `payments.py`, `offsets.py`, `refunds.py`, `collections.py`, `reverse.py`, `agreements.py`, `dnp.py` — exactly 40 PRD §4 routes

**Boot smoke-test evidence**

Dynamic ports 58063 + two more; `start.sh` booted cleanly each time and was killed by its own PID. Verified live: header-gate 400, role-gate 403, unknown-path 404 envelope, clock set/sweep (EXECUTED→SETTLED, file→COMPLETED), creditor create + conditional state_code errors + duplicate 409, PARTIAL policy supersede, EFT determination, debt REFERRED→NOTICED→(window gate 409)→ACTIVE, TIN-mismatch 422, OCC stale 412 then success, EXECUTION_FINAL pool min(90000, 25000)=25000 waterfall, execute (fee 750 / net 24250 / disbursed 75000, ledger credited, ytd_year set), refund SoD 403 → approve cascade (PAID, clawback 10000, debt RETURNED, returned_count=1, balance not restored), DNP hold (HELD/FLAGGED) → overlap 409 → release (VERIFIED/CLEAR), AWG projected 15000, hearing-window 409, collect min(7500, 28250)=7500 with debt-version OCC, agreement overlap 409, reverse-offset MATCHED → CONFIRMED (applied 7000, PAID_IN_FULL, fee 210/net 6790), reversal cascade, pagination meta.

**Interpretations chosen (PRD admitted more than one reading)**

1. **Tier 4 (schema) vs tier 5 (path existence)**: implemented in PRD's numeric order — schema validated before path-id 404. Where a tier-2/3 check needs a loaded resource (CreditorAnalyst ownership on notice/activate, SoD on decide), the resource is loaded opportunistically: if present the check runs in its tier position; if absent, schema fires, then 404.
2. **CreditorAnalyst scoping on GETs**: not applied — §4 lists "All roles" for reads; ownership applies only to create/notice/activate (scaffold tier-2 wording: "created or transitioned").
3. **Ownership before creditor existence** on POST /debts: mismatched `creditor_agency_id` → 403 even if that creditor doesn't exist (tier 2 < tier 6); match-but-missing → ERR_CREDITOR_NOT_FOUND.
4. **Cross-servicing selector ranking**: PRD says "ranked eligible pool" without a key; chose registration order (created_at ASC, insertion tie-break). Eligibility = open (INITIATED/ACTIVE) actions under capacity; only cross-servicing actions count (AWG never has an agency).
5. **DNP release cascade for EVALUATED+FLAGGED payments**: PRD §3.9 names HELD→VERIFIED only, but §2.11 runs evaluation at removal and §3.9 says flagged payments are "barred from execution until cleared"; implemented symmetric clearing (EVALUATED stays EVALUATED, integrity→CLEAR) — otherwise the flag could never clear.
6. **Refund approval on a debt outside {ACTIVE, PAID_IN_FULL}**: scaffold defines transitions only from those two; approval forces RETURNED + returned_count+=1 from any non-RETURNED state (PRD states the move unconditionally), idempotent if already RETURNED; balance never restored; still-PROPOSED offsets on that debt → DROPPED per §3.6.
7. **decide `decision` values**: accept APPROVE/DENY case-insensitively (scaffold uses uppercase, PRD prose lowercase); unknown values still 400.
8. **Pagination out-of-range**: clamped to declared min/max (PRD gives bounds but no error); non-integer limit/offset → ERR_INVALID_REQUEST.
9. **created_at/updated_at/expires_at/applied_at/etc. all read the logical clock** (§2.4 governs every temporal rule; expires_at = created_at + 10d must be clock-derived); `api_request_timestamp` is wall-clock UTC (it is envelope metadata, not a temporal rule).
10. **Reversal/refund on non-ACTIVE debts**: reversal restores balance but reopens only PAID_IN_FULL→ACTIVE (RETURNED stays RETURNED); offsets past APPLIED (REFUNDED/REVERSED/DROPPED) untouched by reversal.
11. **Multiple claims on one offset**: not gated — decide preconditions are only UNDER_REVIEW + SoD; no invented uniqueness rule.
12. **Execute-state error precedence**: non-EVALUATED → ERR_PAYMENT_NOT_EXECUTABLE (tier 7) before ERR_DNP_FLAGGED_PAYMENT (tier 8) — observed: HELD payment execute returns PAYMENT_NOT_EXECUTABLE.
13. **Collect conditional fields**: the type-mismatched field (e.g. remitted_amount_cents on AWG) is rejected 400, mirroring the creation-time disjoint-payload rule; checked after the action loads (the conditional needs action_type).
14. **Reverse-offset confirm on an IN_COLLECTION debt**: allowed (re-capped, PAID_IN_FULL at 0 from either status per §3.3), but an open action is not auto-completed — §3.3 ties action completion to "the final collection lands on an open collection action", i.e. the collect path only.
15. **Clock set**: no monotonicity guard (PRD declares none); date-only and offset-bearing datetimes accepted, normalized to UTC; settlement compares UTC dates ("on or before the clock's UTC date").

**Self-audit**

- Every code-referenced ALL_CAPS constant is defined exactly once in constants.py/errors.py (audit grep clean; flagged names were docstring words or the imported `ROUND_HALF_UP`).
- All 40 PRD §4 endpoints routed (Flask map count = 40, default static route disabled), root-level, no prefix.
- All 34 PRD §5 error ids defined and raisable through helpers.
- Every PRD state gate implemented (notice window 30d equality-activates, AWG 15d, due-process, agreement coverage, DNP execute gate, claim 180d, appeal 30d single, request 10d expiry with lazy EXPIRED flip, terminal-state lockdowns, both OCC rules, SoD); no gates invented beyond PRD.
- No seeding, no external persistence; store is empty dicts at boot; per-test-server reboots are clean.

Orchestrator verification: full tree compiles (`py_compile` over impl root + routes + services: COMPILE_OK); 13 route modules + 3 service modules present.

## Step 7: Test-fix iteration loop — 2026-10-02T13:43:00.000Z

First 8-round parallel stability sweep ran clean; zero iterations needed.

- Sweep: 8 concurrent prd-bench-local-run rounds, --isolation per-test-server, 69 tests each.
- Result: all 8 rounds 69/69 passed, 0 failed, 0 errors, 0 skipped (union of failures across rounds = empty).
- No test deletions, no test_helpers fixes, no implementation fixes.
- Artifacts: workspace/implementation/results.1.json through results.8.json left on disk per the output contract.

## Step 8: Finalize PRD — 2026-10-02T13:50:00.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes. PRD.md already determines every behavior the implementation exhibits; no PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-10-02T14:15:00.000Z

Verification complete: only `PRD_COMPLETED.md` was written, and the diff is exactly the 19 intended edit sites. Here is the final report.

**Files:** `workspace/PRD.md` 336 lines / 50,982 chars → `workspace/PRD_COMPLETED.md` 336 lines / 53,525 chars (+2,543 chars; all edits are in-place line revisions, no new sections). Not a zero-edit outcome.

**Counts:** 23 ambiguity-pins across 18 sites, 1 mismatch-revision, 0 impl-bugs-reported.

### Ambiguity pins (PRD silent or multi-reading → pinned to impl behavior)
- §2.2 — insert — `api_request_timestamp` reads server wall clock; logical clock governs resource timestamps instead — `response.py:13-20` (`wall_now_iso`)
- §2.3 — insert — out-of-range `limit`/`offset` clamp to bounds (1/100/0); non-integer → `ERR_INVALID_REQUEST` — `middleware.py:129-148`
- §2.3 — insert — list `created_at` ties break by creation (insertion) order — `middleware.py:151-158` (`_seq`)
- §2.4 — revise — clock accepts any instant (no monotonicity guard; "advances" → "moves"); endpoint responds 200 with `{current_utc}` — `routes/clock.py:14-25`, `db.py:38-39`
- §2.4 — insert — datetime fields accept date-only (midnight UTC)/`Z`/offset input; all stored instants serialize as ISO 8601 UTC with 3 fractional digits — `util.py:27-53`
- §2.5 — revise — `created_at`/`updated_at` read the logical clock; `version` starts at 1 — `db.py:47-63`
- §2.8 tier 4 — insert — resource-discriminated conditional fields (collect's AWG-vs-CROSS_SERVICING payload rules) evaluate immediately after the path resource loads, ahead of the state tier — `routes/collections.py:189-206`
- §2.8 tier 7 — insert — within tier 7, state precondition is checked before OCC version equality — `routes/payments.py:142-145`, `routes/collections.py:208-212`
- §2.11 — revise — DNP interval-conflict test considers `ACTIVE` records only; `REMOVED` intervals no longer block — `services/cascades.py:76-86`
- §3.2 — insert — multiple `DRAFT` policies per `payment_type` may coexist — `routes/policies.py:42-52` (no uniqueness check)
- §3.3 — insert — omitted `due_process_completed` at referral defaults to `false` — `routes/debts.py:88-89`
- §3.3 — revise — approved refund sends the debt to `RETURNED` whatever its status (adds `IN_COLLECTION` to the parenthetical) — `routes/refunds.py:168-172`
- §3.4 — revise — evaluation permitted from `VERIFIED` **or** `EVALUATED` (reconciles "any other state is `ERR_INVALID_STATE`" with the PRD's own repeatability sentence) — `routes/payments.py:142-143`
- §3.4 — insert — waterfall `created_at` ties break by creation (insertion) order — `services/matching.py:37-44`
- §3.6 — revise — `decision` accepts `approve`/`deny` and identically `APPROVE`/`DENY` — `routes/refunds.py:42,138-141`
- §3.6 — revise — debt moves to `RETURNED` from any non-`RETURNED` status; already-`RETURNED` stays; open collection action on the debt is unaffected by the refund — `routes/refunds.py:168-178`
- §3.7 — insert — `disposable_pay_estimate_cents` is zero-or-more (negative → `ERR_INVALID_REQUEST`) — `routes/collections.py:86-87`
- §3.7 — insert — agency selector ranks the eligible pool by registration order (`created_at` asc, insertion tie-break), first agency wins — `services/matching.py:120-138` (note: `test_helpers/fixtures.py:610` docstring claims an open-count/spare-capacity ranking the impl does not implement; PRD text itself states no key, so impl's reading is pinned)
- §3.7 — insert — collect-time `disposable_pay_cents` zero-or-more — `routes/collections.py:196-197`
- §3.9 — revise — removal cascade also restores `CLEAR` on flagged `EVALUATED` payments in place (they stay `EVALUATED`) — `services/cascades.py:108-124`

### Mismatch revision (1, exonerated by PRD self-contradiction)
- §3.7 — revise — termination returns the debt to `ACTIVE` **only if still `IN_COLLECTION`**; a debt meanwhile sent to `RETURNED` by an approved refund keeps `RETURNED`. Original text ("returns the debt to `ACTIVE`", unconditional) contradicts §3.3's "`RETURNED` is terminal except for the re-notice path" in the composed corner (refund approved while a collection action is open); impl resolves toward the compliance-stronger `RETURNED`-terminal rule — `routes/collections.py:261-264`.

### IMPL BUGs
None. Every clear PRD rule checked was implemented faithfully: fee tiers (3% below 60,000 / 2% at-or-above, pre-event gross, lazy year reset, reversal/clawback asymmetry), 30d/15d/180d/30d/10d windows with the pinned equality semantics, half-open agreement vs closed DNP intervals, overlap-conflict matrices, pool sizing (EXEMPT/FULL/PARTIAL, 65% child-support branch, intake-vs-execution variants), waterfall order, both OCC endpoints (and only those two), segregation of duties at decide-time (tier 3 before schema), the full 11-tier validation order at every endpoint, RBAC per the §4 table (all 40 routes verified), 201/200 split, envelope shapes, and the §5 error catalog (34/34 ids and statuses match).

### Scan coverage
Walked all implementation files: `app.py`, `constants.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `serializers.py`, `util.py`, `routes/` (all 13 modules), `services/` (`cascades.py`, `ledger.py`, `matching.py`); cross-referenced `test_helpers/` and all 9 `test_suite/` files as auxiliary confirmation only. Left intentionally unpinned as direct compositions of pinned rules: collect on an action whose debt was `RETURNED` mid-collection, reversal of a payment whose other offsets were refunded, non-object JSON bodies, and undefined-route 404/405 mapping.

Orchestrator verification: no `implementation/` source file is newer than `results.1.json` (clean sweep remains valid); PRD_COMPLETED.md 53,525 chars / 336 lines, differs from PRD.md exactly as reported.
