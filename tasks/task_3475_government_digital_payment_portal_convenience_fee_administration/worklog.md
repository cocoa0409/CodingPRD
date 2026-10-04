# Worklog — task_3475_government_digital_payment_portal_convenience_fee_administration

## Step 1: Create task directory — 2026-10-02T11:35:00.000Z

Pre-allocated task directory `tasks/task_3475_government_digital_payment_portal_convenience_fee_administration/` verified to exist with empty `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T13:00:00.000Z

All three scaffold artifacts are complete, parse as valid YAML, and pass `scaffold_lint.py` with a clean verdict (1290 recipe calls checked, zero violations). Files live in `/home/ubuntu/github/CodingPRD/tasks/task_3475_government_digital_payment_portal_convenience_fee_administration/`.

**Verdict block (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts**
- Endpoints: 56 (37 writes incl. `POST /_clock/set_current_utc` with the mandatory 2026-09-01T00:00:00Z default, 19 reads; all list endpoints pin `default_sort` for determinism)
- Entities: 15 (Agency, AgencySettlementAccount, ContractPricingTier, ComplianceAttestation, ServiceCatalogItem, StatutoryAuthorization, Payer, PaymentInstrument, FeeQuote, PaymentTransaction, SettlementBatch, ReconciliationException, Refund, ChargebackCase, SelfFundingLedgerEntry)
- State machines: 10 (incl. cyclic ACH SETTLED→RETURNED→RE_PRESENTED→SETTLED, branching chargeback fork, instrument self-loop, exception→batch bubble)
- Calculations: 7 (dual-variant convenience fee QUOTED/FINAL, marginal-chronological vs flat-retroactive tiered billing, value-date lags, batch totals, accrual-vs-cash portal cost recognition, pool waterfall, reconciliation match)
- Validations: 11 ordered priority rows (auth → existence → OCC 412 → state → safety → SoD → constraint → temporal → referential → fiscal)
- Error catalog: 46 ids, every one named by at least one design instance
- Roles: 6 (Payer entity_backed:Payer; PlatformAdmin/AgencyAdmin/TreasuryOfficer/ComplianceAuditor/Anonymous opaque; segregation_of_duties model)
- §1.8 difficulty instances: 27 (all nine rules ≥2; dual_variant 3, combinatorial 3 modes a/b/c, non_linear 3, cascade 2 [depth-3 suspend + depth-2 bubble], priority_conflict 3 distinct category pairs, boundary 4, cross_entity 3, temporal_overlap 3 distinct interval semantics, compensating_invariant 3)
- §1.9 corner instances: 64 (60 active + 4 `excluded_because` stubs) across all nine guide sections

**Harder-than-expert mechanisms:** circular fee-on-gross gross-up pinned to a closed form (wallet 20000 → 393, not the naive 385); quote-vs-final fee divergence on identical inputs (2281 vs 1549 via card-bucket); per-line-then-sum rounding pinned against the 1-cent-divergent aggregate reading (56 vs 57); marginal tier straddle across the 500000-cent band (invoice 12559 vs flat 9549); accrual 200000 vs cash 20437 portal-cost recognition; two true-race OCC rules (agency account supersede, service repricing) plus quote version-pinning (`ERR_STALE_SERVICE_VERSION`); deposit-timing value-date membership with inclusive boundary; and a self-funding pool waterfall with zero-remainder conservation.

**Notes for the orchestrator:** all formula-derived asserts were executed in Python before being pinned as literals; chronological fixtures bump the logical clock between captures so `captured_at/created_at` tie-breaks never resolve to `id`. The 56-endpoint surface exceeds the 40-endpoint comfort threshold flagged in project memory — Step 6 (impl-gen) should be pre-constrained accordingly (per-domain modules, one file per message, no-truncation, self-smoke-test).

Orchestrator verification: all three files exist and parse as valid YAML. Independent instance count confirms difficulty 27 active / corner 60 active (4 stubs) = 87 active total.

## Step 3: Copy shared files — 2026-10-02T13:05:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T13:45:00.000Z

PRD generation complete. All hard contracts verified against `SCAFFOLD.yaml` programmatically (field coverage, error ids, states, §3 path purity, endpoint table, §2.2 verbatim sentinels, fuzzy-word scan). The two design-index files were not opened.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3475_government_digital_payment_portal_convenience_fee_administration/workspace/PRD.md` — 330 lines, ~7,850 words.

**Section list:**
- §1 Introduction (2 paragraphs: shared-portal business context + self-funding/audit commitments)
- §2 Global Specifications: 2.1 Roles & headers, 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`, sentinels confirmed), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, exception-list tie-break), 2.4 The Logical Clock (`/_clock/set_current_utc` stated at its true path **outside** the `/portal` prefix, startup default 2026-09-01T00:00:00Z, never wall-clock), 2.5 Resource Identity & Change Tracking (incl. the four `common_fields: false` entities lacking `updated_at`/`version`), 2.6 Money/Precision/Rounding, 2.7 OCC (both rules with `expected_agency_version`/`expected_service_version` → `ERR_STALE_VERSION` 412), 2.8 Validation Priority Order (all 11 priorities as explicit ordered prose with per-error HTTP statuses), 2.9 Statutory & Compliance Baseline, 2.10 Segregation of Duties & Self-Funding Mandate
- §3 Business Logic (8 subsections): 3.1 Agency Onboarding/Accounts/Compliance, 3.2 Services/Pricing Bands/Statutory Authorizations, 3.3 Payers & Instruments, 3.4 Checkout (quote → authorize → capture/void, full four-step gross-up fee formula in prose with both QUOTED/FINAL variants), 3.5 Settlement Batching & Reconciliation, 3.6 ACH Returns & Re-Presentment, 3.7 Refunds & Chargebacks, 3.8 Self-Funding Period Close (pool waterfall, MARGINAL_CHRONOLOGICAL vs FLAT_RETROACTIVE, ACCRUAL vs CASH)
- §4 Endpoint Definitions (4-column table, all 56 endpoints) · §5 Error Code Catalogue (2-column table, all 46 errors)

**Coverage confirmation (machine-checked):**
- §1.4 calculation constants verbatim in prose: `MIN_FEE_CENTS` 100, all `FEE_RATES` pairs (150/25, 220/30, 290/35 CARD buckets; ECHECK flat 150; WALLET 180/25), `QUOTE_TTL_MINUTES` 30, `METHOD_LAG_DAYS` 1/1/2, `GRACE_DAYS` 1, `TOTAL_PORTAL_COST_CENTS` 12000000, `AMORTIZATION_MONTHS` 60, `MONTHLY_AMORTIZATION_CENTS` 200000 — all present with exact values.
- §1.3 state names: 30/30 present verbatim (all `state_machines` initial/terminal/transition states).
- §1.6 error ids: 46/46 present verbatim, each with its trigger condition in §2/§3 prose; §5 table carries id + HTTP status only.

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 107 required (entity fields + endpoint input/query/path identifiers), 107 present, 0 missing — PASS (one repair: `batch_id` added to §3.5; initial checker false-negative from §2.2 code-fence parity was diagnosed and corrected by stripping fences before tokenization).
- Contract 2 (Rule Coverage): 11 validation priorities expressed as explicit ordered prose; 2 OCC rules expressed (write endpoint + occ field + `ERR_STALE_VERSION`/412); all transitions with preconditions and side effects narrated (incl. suspend/offboard two-link cascades, return/chargeback auto-create-batch debits, exception bubble-up); all 7 calculations fully expressed in reconstruction-safe prose; sibling-branch symmetry maintained (WON vs LOST, SUCCESS/FAILURE, both fee variants, both invoice variants, ACCRUAL/CASH) — PASS.
- Contract 3 (§3 Path Purity): 560 backticked tokens in §3, 0 path/method violations — PASS.

No fuzzy/approximating words remain (one instance of "conservatively" replaced with "in a fixed waterfall order").

Orchestrator spot-check: `/_clock/set_current_utc` confirmed at unprefixed path in PRD (lines 77, 221); fee floor 100 cents + TTL 30 minutes pinned in §3.4 context; scaffold api_prefix `/portal` consistent.

## Step 5a: Generate test_helpers (frozen infrastructure) — 2026-10-02T14:15:00.000Z

All verification gates pass. Step 5a is complete.

**Files written** (all under `test_helpers/`):

| File | Bytes | py_compile |
|---|---|---|
| `types.py` | 9,008 | OK |
| `api_errors.py` | 5,535 | OK |
| `constants.py` | 2,939 | OK |
| `api_client.py` | 11,590 | OK |
| `factories.py` | 7,775 | OK |
| `test_users.py` | 2,866 | OK |
| `assertions.py` | 15,224 | OK |
| `fixtures.py` | 33,146 | OK |
| `__init__.py` | 1,285 | OK |

**Endpoint coverage:** mechanically verified — invoked all 56 `ApiClient` methods against a recording stub; the (method, path) set is an exact 56/56 match with the PRD endpoint table. The clock setter is `POST /_clock/set_current_utc` with payload field `current_utc`, mounted **outside** the `/portal` prefix (55 business endpoints carry the prefix). `validate_success` is never called with a hardcoded status in helpers — fixtures use the lenient `get_success_data`, leaving explicit 201-vs-200 assertions to Stage 5b.

**Error catalog:** `ApiErrorId` + `HTTP_STATUS_CODES` diffed programmatically against PRD §5 — exact 46/46 match on ids and HTTP statuses; registered with `set_error_http_status_map` at import.

**Constants vs PRD:** every constant (`DEFAULT_CLOCK_UTC=2026-09-01T00:00:00Z`, card bucket rates (150,25)/(220,30)/(290,35), WALLET (180,25), ECHECK flat 150, MIN_FEE 100, QUOTE_TTL 30min, METHOD_LAG 1/1/2, representment once/30d, ACH failure limit 3, evidence 10d, grace 1d, portal cost 12000000/60/200000, pagination 10/1/100) is pinned by a verbatim PRD sentence — diff all-OK, no dead or losing-branch constants.

**Clock reachability:** all fixture default windows straddle the 2026-09-01T00:00:00Z clock start (accounts effective 2026-01-01, attestations 2026-08-01→2027-08-01, authorizations [2026-01-01, 2027-12-31]); time-moving fixtures (`capture_series`, `setup_settled_echeck`, `setup_returned_echeck`, `setup_exception_batch`, `setup_september_pool_scenario`) call `set_clock` before each time-sensitive step. No stale design-index literals were copied into helpers.

**Roles:** builders for all 6 roles; Payer is entity-backed (`make_payer_headers(payer["id"])` mandatory for ownership-gated calls, threaded everywhere in fixtures); three opaque AgencyAdmin ids (`aa-lead`/`aa-peer`/`aa-county`) support segregation-of-duties.

**Fixture inventory vs design indices** (27 difficulty + 60 corner = 87 active):
- 9 difficulty rules covered by: `setup_cf_checkout` (all card buckets incl. COMMERCIAL), `setup_september_pool_scenario` (accrual-vs-cash, marginal-vs-flat, pool conservation), `setup_absorbed_checkout(top_unbounded=...)` + `capture_series` (round-per-line, tier boundary/gap, straddle), `setup_settled_echeck`/`setup_returned_echeck` + `re_present`/`ach_return`/`open_and_close_batch` (ACH cycle, representment boundary, net-zero drift), `setup_captured_card_pair` + chargeback helpers (contest-won vs accept fork), `add_echeck_instrument` + `verify_ach` FAILURE loop (self-loop→DEACTIVATED), `setup_open_card_quote` + `suspend_agency` (cascade), `setup_exception_batch` + `resolve_exception` (bubble), `setup_agency_with_verified_account` (half-open windows + OCC), `create_approved_authorization` (closed-window overlap), `create_pricing_band` (band boundary), `setup_captured_card(with_open_batch=...)` + `request_refund`/`decide_refund`/`approve_refund` (refund boundary, segregation, no-open-batch, money conservation), expiring-attestation params on `setup_active_agency`/`setup_cf_checkout` (priority-pair lapse probes).
- 9 corner sections (entities 11, state_machines 12, calculations 4, validations 3, endpoints 2, errors 17, rbac 6, cross_cutting 4, consistency 1) — all preconditions reachable from the same building blocks; every fixture path was executed against a stubbed HTTP layer with zero NameErrors.

**Flags for Stage 5b** (adjudication points, not helper bugs):
1. Difficulty instance `fee_floor_bucket_tier_nested_min_max` asserts `quote_big.quoted_fee_cents == 3023`, but the recipe's own parenthesized formula (CONSUMER_CREDIT closed form for 100000) evaluates to 2281, and PRD §3.4 pins QUOTED as always CONSUMER_CREDIT-rated — 3023 is the COMMERCIAL number. Re-derive from PRD (expect 2281).
2. PRD §3.4 says ABSORBED "fee is zero in every variant", yet four design instances pin `processing_costs_cents` at 150 per absorbed ECHECK (2542/450/300). PRD §3.4's authorize paragraph names only `charged_fee_cents` as "zero for ABSORBED". 5b must apply the two-reader rule to these literals.
3. Corner instance `compliance_auditor_cannot_create_agency` cites a `GET /portal/agencies` list endpoint that does not exist in the PRD endpoint table — that sub-assertion likely fails unique-derivability.
4. The WALLET 393 literal is arithmetically correct (392.057 ceils to 393) — verified, no action needed.

Orchestrator verification: 9 files exist, all compile, clock path unprefixed in api_client.py (line 17).

## Step 5b: Generate test_suite — 2026-10-02T15:05:00.000Z

All checks pass. Step 5b is complete.

**Files written** (all under `test_suite/`): `conftest.py` plus 13 test files — `test_01_fee_quotation.py` (14 tests), `test_02_absorbed_billing_and_period_close.py` (13), `test_03_payment_state_machine.py` (9), `test_04_ach_return_represent.py` (7), `test_05_chargebacks.py` (7), `test_06_refunds.py` (10), `test_07_settlement_and_reconciliation.py` (9), `test_08_agency_lifecycle.py` (7), `test_09_catalog_services.py` (8), `test_10_windows_and_tiers.py` (5), `test_11_payers_instruments.py` (8), `test_12_api_conventions.py` (9), `test_13_cross_entity_gates.py` (6). **112 tests total.** `test_helpers/` untouched.

**AST tag audit (real ast walk):** 112 tests, 86 distinct tags; 0 untagged, 0 dual-tagged, 0 dangling, 0 stub tags emitted. Queue A: 26/27 instances with ≥2 tests (52 tests); Queue B: 60/60 active instances (60 tests); 4 `excluded_because` stubs correctly untranslated with resolved cross-references.

**Skip list (1):** `Difficulty/cross_entity_state_dependency/service_activate_blocked_when_attestation_expired` — PRD §2.9 exhaustively lists attestation-gated operations ("required to activate the agency, to quote a checkout, and to authorize a payment") and §3.2's service-activation gates name only agency-ACTIVE + statutory coverage; `ERR_COMPLIANCE_LAPSED` on service activate is not PRD-covered, so the asserted 409 is not uniquely derivable.

**Adjudication flags applied:**
1. `fee_floor_bucket_tier_nested_min_max` — asserted 2281 (re-derived CONSUMER_CREDIT closed form), not stale 3023; floor-at-100 kept.
2. Absorbed `processing_costs_cents` — PRD's "their fee is zero in every variant" uniquely derives `final_fee_cents == 0` for ABSORBED, so I re-derived: processing_costs **2092** (not 2542), cash recovery **20887**, remaining cash **11979113**, divergence **179113** (A2/A27); pool balance **0** (A5); cash **41035** (A16) — each with verbatim PRD citations.
3. `compliance_auditor_cannot_create_agency` — kept only the covered 403 `ERR_FORBIDDEN_FOR_ROLE`; dropped the non-existent `GET /portal/agencies` sub-assertion.
4. WALLET 393 confirmed correct, used as-is.

**Extra PRD-first adjustments:** `authorize_blocked_when_agency_suspended` uses `validate_error_is_one_of([ERR_AGENCY_NOT_ACTIVE, ERR_INVALID_STATE])` (both gates sit on the same priority-5 rung and §3.4's authorize gate list omits agency state — intra-rung winner not uniquely derivable); dropped the PlatformAdmin leg of `authorize_body_fks_checked_in_declared_input_order` (role check at priority 2 would 403 first); pagination/filter tests advance the logical clock between creates so `created_at ASC` ordering is strict.

**Verification:** `py_compile` all pass; all 14 modules import against frozen helpers; `pytest --collect-only` collects 112 tests with no errors; all 131 quoted docstring fragments verified as verbatim substrings of PRD.md.

Orchestrator independent AST audit confirms: 112 tests, 86 distinct tags, 0 untagged/dangling, exactly 1 uncovered instance (the reported skip). Duplicate tags are the 26 difficulty instances carrying exactly 2 tests each.

## Step 6: Generate implementation — 2026-10-02T15:50:00.000Z

Done. The implementation is complete, compiles cleanly, boots fresh repeatedly, and passes the end-to-end smoke test including the calculation checks.

**File inventory (implementation/, bytes)**

| File | Size | Role |
|---|---|---|
| start.sh | 381 | Guarded install + `exec python3 app.py`, reads $PORT, binds 0.0.0.0 |
| requirements.txt | 11 | flask>=2.2 |
| app.py | 2049 | App factory, blueprint registration, ApiError/404/405/500 handlers |
| store.py | 1148 | In-memory dicts (empty at boot, no seeding), UUID + creation-seq minting |
| clock.py | 1461 | Logical clock (default 2026-09-01T00:00:00Z), ISO-8601 3-fractional-digit fmt |
| errors.py | 549 | ApiError carrying error_id/status/message |
| envelope.py | 1730 | meta/response_type/data envelope, pagination (limit/offset/total_count/has_more) |
| auth.py | 1167 | X-User-ID/X-User-Role checks (priorities 1–2) |
| validate.py | 2911 | Body/field/enum/date/month/method-set validators → ERR_INVALID_REQUEST |
| helpers.py | 6621 | Per-resource 404 getters, PCI/statutory gates, batch factory, cascades |
| serialize.py | 9239 | Per-entity serializers with clock-derived computed fields |
| fees.py | 4614 | Gross-up closed form, floor 100, tier invoices (MARGINAL_CHRONOLOGICAL + FLAT_RETROACTIVE), constants |
| routes_clock.py | 668 | POST /_clock/set_current_utc (outside /portal) |
| routes_agencies.py | 4480 | Agency CRUD + activate/suspend/offboard with 2-link cascade |
| routes_accounts.py | 5068 | Settlement accounts: OCC create, supersede handoff, verify |
| routes_tiers.py | 2752 | Pricing bands with closed-interval overlap rejection |
| routes_attestations.py | 1859 | Attestation filing, computed CURRENT/EXPIRED |
| routes_services.py | 6091 | Services CRUD + activate/deactivate |
| routes_authorizations.py | 3637 | Statutory authorizations + approve with closed-window overlap |
| routes_payers.py | 5394 | Payers + instruments + verify-ach (3-failure deactivation) |
| routes_quotes.py | 5164 | Fee quotes: QUOTED variant, 30-min TTL, version pin |
| routes_transactions.py | 9727 | Authorize (FINAL variant), capture, void, ach-return, re-present, nested lists |
| routes_batches.py | 7948 | Batch lifecycle, reconciliation exceptions, resolve bubble-up |
| routes_refunds.py | 3426 | Refund initiate/decide with segregation of duties |
| routes_chargebacks.py | 5376 | Chargeback fork: contest/accept/record-outcome incl. force-LOST |
| routes_selffunding.py | 4374 | Period close: pool waterfall, ACCRUAL/CASH recognition, zero-remainder conservation |

`python3 -m py_compile` on all 23 .py files: ALL COMPILE OK.

**Smoke-test transcript (dynamic port 39237, killed via saved $! only)**

- POST /_clock/set_current_utc → 200, echoes input
- POST /portal/agencies → 201 ONBOARDING v1
- POST /portal/settlement-accounts (expected_agency_version=1) → 201 PENDING_VERIFICATION; agency bumped to v2
- POST verify SUCCESS (TreasuryOfficer) → VERIFIED, attempts 1
- POST /portal/attestations (PCI_DSS_AOC) → 201, computed CURRENT
- POST activate → ACTIVE, activated_at stamped, v3
- POST services → DRAFT (fee_model inherited CONVENIENCE_FEE); statutory-authorization create+approve (in_effect flips false→true); activate → ACTIVE
- POST /portal/payers (Anonymous) → 201; CARD instrument CONSUMER_DEBIT → ACTIVE with tok_ ref
- POST /portal/fee-quotes amount 10000 CARD → quoted_fee 256 = ceil((220·10000+30·10000)/9780) per CONSUMER_CREDIT disclosure rating; payer_total 10256; expires_at = created+30min
- POST /portal/payment-transactions → charged_fee 256 (QUOTED binding), final_fee 178 (CONSUMER_DEBIT), AUTHORIZED
- capture → CAPTURED, value_date 2026-09-02 (CARD lag 1)
- batch open→close (member_count 1, gross 10000, fees_withheld 256, deposit 10000, due 2026-09-02)→submit→confirm-deposit(10000)→reconcile → RECONCILED
- Negative probes: missing headers → 400; AgencyAdmin creating agency → ERR_FORBIDDEN_FOR_ROLE; stale expected_agency_version → ERR_STALE_VERSION 412; empty period close 2026-08 → 201 (accrual 200000, cash 0, surplus 0, remaining 11800000/12000000)
- Second fresh boot on another dynamic port → create agency 201 (per-test-server restart contract verified). Server log: no tracebacks.

**PRD ambiguities resolved (interpretation chosen)**

1. **Activate gate order**: ERR_NO_VERIFIED_ACCOUNT before ERR_COMPLIANCE_LAPSED (§3.1 and state-machine precondition order; §2.8's mention order within priority 6 is generic prose).
2. **ERR_INVALID_REQUEST placement**: evaluated after auth + path-id existence, before body-FK resolution and all business checks ("independently of this ladder" has no explicit slot).
3. **FINAL fee cap**: steps 1–3 (rate, gross-up, floor 100) apply to FINAL; the statutory cap hard-stop applies only to the disclosure-binding QUOTED fee (FINAL is the portal's cost accrual, never the charged fee).
4. **Supersede validation**: named account must belong to the same agency (ERR_INVALID_REQUEST) and be VERIFIED (ERR_INVALID_STATE); non-advancing effective_from → ERR_INVALID_REQUEST; overlap checked against all other non-RETIRED accounts.
5. **Format guards**: routing_number ^\d{9}$, account_number_last4 ^\d{4}$ (PRD-described formats; violations → ERR_INVALID_REQUEST).
6. **DEPOSIT_LATE expected_cents**: epoch-day of (deposit_due_date + 1 grace day), per scaffold's "expected latest date epoch-day context"; actual_cents null.
7. **Timestamp echo**: input-sourced instants echo the caller's original string; all system stamps serialize from the logical clock with 3 fractional digits.
8. **Payer list scoping**: fee-quote/transaction lists force-filter to payer_id == X-User-ID rather than erroring on a mismatched filter.
9. **Prior pool balance**: most recently created ledger entry's pool_balance_after_cents (entries kept in creation order).
10. **record-outcome WON on OPENED case** (even past deadline) → ERR_INVALID_STATE; only LOST is force-decided per the state machine.
11. **Frozen-clock ordering**: internal monotonic creation seq tiebreaks created_at ASC sorts; exception listing sorts created_at then exception_type per spec.

Orchestrator verification: 23 .py files compile; clock route confirmed unprefixed at `/_clock/set_current_utc` (routes_clock.py:14); fee constants in fees.py match PRD and test_helpers/constants.py exactly (150/25, 220/30, 290/35, ECHECK flat 150, WALLET 180/25, MIN_FEE 100, TTL 30) — no Step 5↔6 drift. The 11 interpretations are logged above as candidate over-guard/under-guard sites for Step 7 adjudication.

## Step 7: Run tests and iterate — 2026-10-02T16:20:00.000Z

Clean sweep achieved. All 8 rounds pass 112/112.

**Iterations run:** 2 sweeps (1 initial diagnostic, 1 post-fix verification)

**Tests deleted:** none

**Fixes applied to `test_helpers/`:** none

**Fixes applied to `test_suite/`:** none

**Fixes applied to `implementation/`:**
- `workspace/implementation/store.py` — `new_id()`: changed `uuid.uuid4().hex` → `str(uuid.uuid4())`. PRD §2.5 states "Every resource carries an `id`, a server-minted UUID with no type prefix" — the canonical string form of a UUID is the dashed 8-4-4-4-12 representation, which is exactly what the test assertion library's `is_valid_uuid` demands. The undashed 32-hex form was an implementation bug, not a test bug. All 22 deterministic failures across all 8 rounds traced to this single root cause (FeeQuote.id, SelfFundingLedgerEntry.id, and generic `id` assertions on transactions, refunds, chargebacks, batches, agencies, services, accounts, instruments).

**Sibling unasserted code paths:** not applicable — the fix was purely implementation-side; no test-side edits were made, so no assertion coverage was traded away. The two remaining `.hex` uses in the implementation (`envelope.py` `api_request_id` with `req_` prefix, `routes_payers.py` `token_ref` with `tok_` prefix) are opaque non-UUID identifiers per PRD and are correctly left as-is.

**Final state:** 8/8 rounds × 112/112 tests passing. All `results.{1..8}.json` files remain in `workspace/implementation/` per the output contract.

Orchestrator verification: all 8 results.${i}.json read back passed=112/total=112/failed=0; store.py:30 shows `str(uuid.uuid4())`.

## Step 8: Finalize PRD — 2026-10-02T16:40:00.000Z

Done. Zero-edit verdict delivered.

**Line counts / delta:** `PRD.md` 329 lines (57,558 bytes) vs `PRD_FINALIZED.md` 329 lines (57,558 bytes) — 0.0% delta, byte-identical (verified with `diff -q`). Output at `workspace/PRD_FINALIZED.md`.

**Changes:** none — zero-edit verdict.

**Verdict evidence (the single `<step_7_diff>` item: `store.py` `new_id()` `.hex` → `str(uuid.uuid4())`):**
- Verbatim PRD §2.5 (line 81): *"Every resource carries an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits."*
- Impl read, `workspace/implementation/store.py:29-30`: `def new_id(): return str(uuid.uuid4())`.
- "A UUID" unqualified in a spec denotes the canonical 8-4-4-4-12 dashed string representation (what Python's `str(uuid.UUID)` emits and what `is_valid_uuid` in `test_helpers/assertions.py:12,20,28` demands). The undashed 32-hex form is a specialized variant a spec would have to name explicitly; no reasonable fresh implementer reads "server-minted UUID" and mints undashed hex. Step 7 itself classified the undashed form as "an implementation bug, not a test bug" — the impl moved toward the PRD, so there is no PRD silence to pin and no test-side weakening to codify. This is the pure-impl-bug case the scope rule anticipates.

**Pre-edit search log (edit considered and rejected — a parenthetical naming the 8-4-4-4-12 dashed form in §2.5):**
- (a) Subject: the string representation of server-minted resource `id` fields.
- (b) Impl paths enumerated and grepped/read: every `uuid` use in `implementation/` — `store.py:30` (`new_id`, dashed, sole minting point for all resource ids; 16 callsites across `routes_agencies.py:29`, `routes_accounts.py:76`, `routes_tiers.py:47`, `routes_attestations.py:31`, `routes_services.py:61`, `routes_authorizations.py:33`, `routes_payers.py:38,89`, `routes_quotes.py:86`, `routes_transactions.py:85`, `routes_batches.py:134`, `routes_chargebacks.py:50`, `routes_refunds.py:43`, `routes_selffunding.py:79`, `helpers.py:153`); plus the two non-`.hex`-removed sites `envelope.py:16` (`api_request_id` = `"req_" + uuid4().hex[:24]`) and `routes_payers.py:95` (`token_ref` = `"tok_" + uuid4().hex`). Cross-checked PRD: line 43 describes `api_request_id` as a `req_`-prefixed opaque request identifier and line 151 describes `token_ref` as a server-minted gateway token — neither is a resource `id` under §2.5, so both are consistent with the PRD as written. Also grepped PRD for any example pinning a concrete `id` string form — none exists.
- (c) Why rejected: the current sentence already uniquely determines the shipped behavior on every enumerated path; the dashed-form parenthetical would be redundant restatement, not disambiguation. Per the explicit instruction not to manufacture an edit and to prefer under-determined wording, no edit was made.

No other `<step_7_diff>` items exist (no test deletions, no helper fixes, no other impl fixes), so nothing else was in scope.

Orchestrator verification: `diff -q` confirms PRD_FINALIZED.md byte-identical to PRD.md (both 329 lines) — consistent with the zero-edit verdict.

## Step 9: Complete PRD — 2026-10-02T17:20:00.000Z

PRD_COMPLETED.md is written and verified. Final summary:

**Produced** `workspace/PRD_COMPLETED.md` — a minimal patch over PRD_FINALIZED.md.

- **Line counts**: PRD_FINALIZED.md 329 lines / 57,558 chars → PRD_COMPLETED.md 333 lines / 60,914 chars (**+4 lines, +3,356 chars**). No sections added or removed; all changes are in-paragraph inserts/revisions plus two rows in the §5 index.
- **Counts**: 23 ambiguity-pins, 1 mismatch-revision, 2 impl-bugs-reported.

### Changes (one bullet each)

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as read from the logical clock, not wall-clock — implementation/envelope.py:14-18
- §2.2 + §5 — insert — ambiguity — framework rejections pinned: undefined path → `ERR_NOT_FOUND` (404), unsupported method on a defined path → `ERR_METHOD_NOT_ALLOWED_ON_PATH` (405); two catalogue rows added — implementation/app.py:55-65
- §2.3 — insert — ambiguity — non-numeric/out-of-range `limit`/`offset` fall back to defaults and clamp (limit into [1,100], offset at 0) rather than erroring; `has_more` = `offset` + returned rows < `total_count`; `created_at` ties broken by creation order — implementation/envelope.py:30,43-65
- §2.4 — insert — ambiguity — clock endpoint accepts any parseable ISO 8601 instant (no monotonicity enforcement) and echoes the caller's string verbatim — implementation/clock.py:42-49, implementation/routes_clock.py:14-23
- §2.5 — insert — ambiguity — input-supplied instants (account `effective_from`/`effective_to`, attestation `issued_at`/`expires_at`, authorization window) echoed verbatim, not reformatted — implementation/serialize.py:9-13
- §2.8 — insert — ambiguity — the "non-positive amount" malformed rule scoped to `amount_cents` of fee-quote and refund requests; all other integer inputs are type-checked only — implementation/validate.py:48-52, routes_quotes.py:24, routes_refunds.py:24
- §3.1 — insert — ambiguity — `verified_at` stays null until a SUCCESS verification outcome — implementation/routes_accounts.py:124-127
- §3.1 — insert — ambiguity — a `supersedes_account_id` naming another agency's account is `ERR_INVALID_REQUEST` — implementation/routes_accounts.py:50-52
- §3.1 — insert — ambiguity — attestation `issued_at`/`expires_at` not cross-validated at filing (an inverted window just computes EXPIRED) — implementation/routes_attestations.py:26-27
- §3.2 — insert — ambiguity — service amount bounds not cross-validated (min > max admits no quotable amount) — implementation/routes_services.py:37-38
- §3.2 — insert — ambiguity — `service_code` uniqueness comparison is exact and case-sensitive — implementation/routes_services.py:47-58
- §3.2 — insert — ambiguity — repricing (PUT) is permitted in any service status, including DEACTIVATED — implementation/routes_services.py:98-135
- §3.2 — insert — ambiguity — pricing-band bounds not cross-validated (`volume_max_cents` < `volume_min_cents` accepted, covers nothing) — implementation/routes_tiers.py:22-25
- §3.2 — insert — ambiguity — authorization window bounds not cross-validated at draft time — implementation/routes_authorizations.py:27-28
- §3.3 — insert — ambiguity — payer email uniqueness is an exact, case-sensitive comparison — implementation/routes_payers.py:29-35
- §3.3 — insert — ambiguity — `token_ref` is an opaque `tok_`-prefixed server-minted string; `ach_verify_failures` starts at zero on every instrument — implementation/routes_payers.py:95-97
- §3.4 — insert — ambiguity — step-four statutory cap is evaluated only at quotation against the QUOTED fee; authorization does not re-check the FINAL fee against the cap (defensible: only the QUOTED fee is ever charged to the payer) — implementation/routes_quotes.py:69-79 vs implementation/routes_transactions.py:77-81
- §3.4 — insert — ambiguity — `captured_at`, `value_date`, `returned_at` are null at authorization — implementation/routes_transactions.py:100-102
- §3.5 — insert — ambiguity — new batch's `member_count`/`gross_amount_cents`/`fees_withheld_cents` start at zero; `deposit_due_date`/`submitted_at`/`confirmed_at`/`actual_deposit_cents` start null — implementation/helpers.py:150-172
- §3.5 — insert — ambiguity — `DEPOSIT_LATE` row's `expected_cents` carries the latest on-time confirmation date (due date + 1-day grace) as whole days since 1970-01-01; both exception row types carry a human-readable `detail` — implementation/routes_batches.py:174-183
- §3.7 — insert — ambiguity — refund's `decided_by_user_id` is null until a decision — implementation/routes_refunds.py:48
- §3.7 — insert — ambiguity — chargeback's `network_debit_cents` and `evidence_note` are null at intake — implementation/routes_chargebacks.py:53-56
- §3.7 — insert — ambiguity — recording any outcome other than LOST on an OPENED case past its deadline is rejected with `ERR_INVALID_STATE` (force-decide accepts only LOST) — implementation/routes_chargebacks.py:137-138
- §3.8 — revise — mismatch — absorbed-invoice walk order changed from "by `captured_at` and then `created_at`" to "by `captured_at`, with ties broken by creation order" — implementation/routes_selffunding.py:54 sorts by `(captured_at, created_seq)`. Exonerating condition: the pinned key was not a well-defined total order under the PRD's own clock semantics (the clock endpoint imposes no monotonicity, so `created_at` can tie or reorder), so the phrase admitted multiple readings; the impl's reading coincides with `created_at` order on every forward-only clock run.

## IMPL BUGS

1. **POST /portal/payers/{id}/instruments** — PRD §2.8 priority 3: *"An unknown payer `X-User-ID` on a payer-scoped write also reports `ERR_PAYER_NOT_FOUND`."* — Impl behavior: a Payer-role caller whose `X-User-ID` is not a persisted payer, posting to another (existing) payer's instrument path, gets `ERR_NOT_RESOURCE_OWNER` (403) because the ownership check fires without any existence check on the caller — implementation/routes_payers.py:61-104 (ownership at lines 85-86, no `require_payer_exists`). The sibling Payer-role writes all perform the existence check (`require_payer_exists` at routes_quotes.py:28, routes_transactions.py:32, and routes_payers.py:134 on verify-ach — an instrument-path endpoint, which shows the impl itself reads "payer-scoped write" broadly), so instrument-create is the lone omission. Why the PRD side is worth keeping: the rule is clear and implementable, priority 3 explicitly outranks the priority-10 ownership check, and the impl honors it everywhere else.

2. **POST /portal/refunds/{id}/decide** — PRD §3.7: *"on approval the refund moves to `APPROVED`, `decided_by_user_id` records the decider"* (and rejection with `ERR_NO_OPEN_BATCH` is not an approval). — Impl behavior: `decided_by_user_id` is written to the stored refund record at implementation/routes_refunds.py:76, *before* the open-batch check raises `ERR_NO_OPEN_BATCH` at lines 79-86, so a rejected APPROVE attempt leaks the would-be decider's id into a still-`REQUESTED` refund (observable via the refund listing until a later successful decide overwrites it). Why the PRD side is worth keeping: a rejected request must not partially apply; the PRD conditions the write on approval, and the status correctly stays REQUESTED (asserted by test_06) — only the decider field leaks.

No other divergences found: all 56 endpoints, role lists, state machines, fee/tier/ledger formulas, cascade rules, validation-ladder ordering, error ids/status codes, and append-only resource shapes in the impl match the PRD text as already pinned.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (+4 lines, +3,356 chars) — no silent no-op. Two IMPL BUGS accepted for orchestrator fix + re-sweep (Step 9b terminal sequence).

## Step 9b: Fix Step-9 impl defects + re-sweep — 2026-10-02T18:05:00.000Z

Orchestrator-applied targeted fixes to the two IMPL BUGS Step 9 reported; PRD_COMPLETED.md untouched (the impl moved toward the PRD, so no contract edit).

**Fixes applied to `implementation/`:**
1. `routes_payers.py` — `create_instrument()`: added `helpers.require_payer_exists(uid)` before `require_payer_ownership` inside the `if role == "Payer":` block, matching the established verify-ach idiom (routes_payers.py:133-135). An unknown payer `X-User-ID` on this payer-scoped write now reports `ERR_PAYER_NOT_FOUND` (priority 3) instead of leaking to the priority-10 ownership 403 — per PRD §2.8 priority 3 verbatim. Both files byte-compile after edit.
2. `routes_refunds.py` — `decide_refund()`: moved the `rec["decided_by_user_id"] = uid` write to after the open-batch gate on the APPROVE branch (and into the DENY branch), so a request rejected with `ERR_NO_OPEN_BATCH` no longer partially applies the decider id to a still-REQUESTED refund — per PRD §3.7 conditioning the write on the decision being made.

**Re-sweep:** full 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`, fresh `results.${i}.json`) after the fixes: **all 8 rounds passed 112/112, failed 0**. The final passing results files remain in `workspace/implementation/` per the output contract.
