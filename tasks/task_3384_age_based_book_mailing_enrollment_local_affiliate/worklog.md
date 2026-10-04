# Worklog — task_3384_age_based_book_mailing_enrollment_local_affiliate

## Step 1: Create task directory — 2026-10-01T12:22:00.000Z

Pre-allocated task directory `./tasks/task_3384_age_based_book_mailing_enrollment_local_affiliate` confirmed present with `workspace/` inside; no new index computed and no other task_* directory created (per command args).

## Step 2: Generate scaffold — 2026-10-01T13:56:00.000Z

All three artifacts are complete, verified on disk, and lint-clean. Final summary:

### Generated files

All under `/home/ubuntu/github/CodingPRD/tasks/task_3384_age_based_book_mailing_enrollment_local_affiliate/`:

- **SCAFFOLD.yaml** (66 KB) — §1.0–§1.7 for an Imagination-Library-style book mailing program (`api_prefix: /library`)
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (66 KB) — single key `scaffold_difficulty_design`, 18 instances (exactly 2 per each of the 9 rules)
- **SCAFFOLD_CORNER_DESIGN.yaml** (94 KB) — single key `scaffold_corner_design`, 50 entries: 44 active instances across all 9 claim-extraction sections + 6 `excluded_because:` stubs (all citations resolve)

### Surface counts

- **Entities: 12** — StateProgram, Affiliate, AffiliateAgreement, PopulationStat, Child, AddressChange, Title, AgeBandSelection, PrintOrder, MailingWave, MailingItem, AffiliateInvoice (flat topology, FK-linked, self-referential `Child.transfer_source_child_id`)
- **Endpoints: 40** — deliberately capped at 40 after trimming two non-load-bearing single-GETs (memory: >40 risks impl-gen quality); includes `POST /library/_clock/set_current_utc` with the mandated `2026-09-01T00:00:00Z` default and sweep side effects
- **State machines: 8** — cyclic Child hold loop, Selection rework cycle, AddressChange 4-way fork, Invoice dispute cycle, sweep-driven graduation/expiry
- **Calculations: 9** with all constants pinned; **validations: 12** priorities; **errors: 35**; **roles: 6** (segregation-of-duties on selection propose/approve; entity-backed Coordinator→Affiliate and Officer→StateProgram)

### Difficulty design highlights (harder-than-expert load)

- Dual-variant calcs in different domains with precomputed diverging literals: PER_LINE vs AGGREGATE invoice share (330/342 vs 331/341 at 4925bp), SNAPSHOT vs TRAILING_12 penetration (2bp vs 3bp)
- Combinatorial formulas in different modes: tier×plate×reprint print pricing (19999 units costs 3,724,815c > 20000 units at 3,200,000c) and pinned round-per-line-then-sum order (334 vs 335 at 4975bp)
- Depth-3 cascades from different triggers (return threshold → hold → auto-unenroll → recount; address transfer → new enrollment → dual recount)
- Temporal overlaps with different interval semantics: half-open agreement windows (adjacency allowed) vs aggregate press-month capacity (400,000 inclusive boundary)
- Compensating invariants on different quantities: global enrollment conserved across transfer (3+1 = 2+2), invoice gross conserved across dispute credit (330+118+224 = 672)
- One true-race OCC rule (`expected_affiliate_version`, 412) — all version payloads are `${var}`-bound

### Verification

- `scaffold_lint.py`: **VERDICT: clean lint** — 1064 calls scanned, all §1.8/§1.9 calls conform to §1.5, all FKs reverse-reachable
- All three files parse as YAML; 68 instance names unique across both design files; every error code referenced outside its catalog entry; every role used and declared; all `grounds:` (calculations/entities/state-machine transitions) resolve; no forbidden race vocabulary
- No sibling task directories were read at any point

Orchestrator verification: all three files exist on disk, parse as YAML with expected top-level keys, and grep confirms the book-mailing/affiliate domain (api_prefix `/library`, 112 Affiliate/Child/MailingItem mentions in SCAFFOLD.yaml).

## Step 3: Copy shared files — 2026-10-01T14:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T14:05:00.000Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_3384_age_based_book_mailing_enrollment_local_affiliate/workspace/PRD.md`.

**Output stats:** 278 lines. The two difficulty-design files were never opened.

**Section list:**
- 1. Introduction (2 paragraphs — funding/enrollment framing, logical-clock note)
- 2. Global Specifications: 2.1 RBAC (6 roles, entity-backed identity prose for `AffiliateCoordinator`→Affiliate.id and `StateProgramOfficer`→StateProgram.id, opaque for the other four), 2.2 API Response Structure (byte-verbatim canonical block, verified against `section-2.2-response-structure.md`), 2.3 Pagination (`limit` 10/1–100, `offset` 0, created_at ascending, meta fields), 2.4 Logical Clock & Calendar-Month Semantics (startup default 2026-09-01T00:00:00Z, whole-month age math), 2.5 Common Resource Properties (all 12 entities carry id/created_at/updated_at/version), 2.6 Integer Cents & Rounding (half-up reprint/per-line, floor division for per-unit, basis points), 2.7 OCC on agreement creation only (`expected_affiliate_version` → `ERR_STALE_VERSION` 412), 2.8 Validation Ordering (12-step priority cascade + left-to-right path 404s), 2.9 Derived Counters & Inventory Reconciliation
- 3. Business Logic: 3.1 Programs & Affiliates (operability rule, population stats), 3.2 Agreements & Geography (half-open overlap, adjacency allowed, approve/reject/expire sweep, version bump), 3.3 Child Registration & Lifecycle (5 registration guards incl. the future-vs-over-age error split, graduation), 3.4 Address Changes, Transfers & Undeliverable Mail (3-way approve fork + reject, affiliate selector with tie-break, return threshold 2, hold stays manifest-eligible), 3.5 Titles & Selections (band definitions, segregation of duties, rework cycle, lock), 3.6 Print Orders & Press Capacity (tier pricing 210/185/160/140, reprint 9/10 half-up, plate fee 25,000 waiver, 400,000 capacity with equality allowed), 3.7 Waves (5-condition manifest eligibility, duplicate prevention, reconcile auto-delivery), 3.8 Invoicing & Penetration (PER_LINE split, AGGREGATE reporting-only variant, dispute/credit invariant, SNAPSHOT + TRAILING_12)
- 4. Endpoint Definitions: 40 rows, 4 columns, path set verified equal to scaffold
- 5. Error Code Catalogue: 35 rows, 2 columns, all IDs/statuses match scaffold exactly

**Hard contract reports:**
- Field coverage: 83 required identifiers (entity fields + request/query/path params + clock/penetration outputs + address sub-fields + common fields), 83 present, 0 missing — **PASS**
- Rule coverage: 12-priority validation cascade ordered in prose; 1 OCC rule fully specified (endpoint + field + error + status, no race framing); 30 state transitions across 8 machines with preconditions/side effects; all 9 calculations in precise prose (no pseudocode/fuzzy wording); all 35 error IDs triggerable from §2/§3; sibling branches (ACTIVE vs HOLD exits, 4 address-change outcomes, 2 dispute resolutions, 2 penetration variants) at equal density — **PASS**
- Path purity: 326 backticked tokens in §3 scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path combos — **PASS**

One repair was applied during verification: `CONFIRMED` initially appeared only as lowercase prose; §3.6 now names the `SUBMITTED → CONFIRMED` pair explicitly, and §3.7 carries the negative-age exclusion clause from the age-band formula.

Orchestrator verification: PRD.md exists on disk (277 lines), head confirms book-mailing/affiliate domain and `/library` prefix.

## Step 5a: Generate test_helpers — 2026-10-01T14:25:00.000Z

Everything verifies. Framework's `NON_EXISTENT_UUID` (`00000000-…`) differs from the design recipes' probe id, so `BOGUS_UUID` is retained deliberately — it matches every anchor in both design indices.

### Step 5a complete — summary

#### Files written (10)
- `test_helpers/types.py`
- `test_helpers/constants.py`
- `test_helpers/api_errors.py`
- `test_helpers/api_client.py`
- `test_helpers/factories.py`
- `test_helpers/assertions.py`
- `test_helpers/test_users.py`
- `test_helpers/fixtures.py`
- `test_helpers/__init__.py`
- `test_suite/conftest.py`

#### Frozen public API (Step 5b codes against this)

**api_client** (`api_client` singleton, `ApiClient` class) — 40 endpoint methods, all return raw `requests.Response`:
- `set_clock(payload, headers)`; `create_state_program(payload, headers)`
- `create_affiliate(payload, headers)`; `get_affiliate(affiliate_id, headers)`; `list_affiliates(headers, params=None)`; `get_affiliate_penetration(affiliate_id, headers, params=None)`
- `create_agreement(affiliate_id, payload, headers)`; `list_agreements(affiliate_id, headers, params=None)`; `approve_agreement(agreement_id, headers)`; `reject_agreement(agreement_id, headers)`
- `create_population_stat(affiliate_id, payload, headers)`; `list_population_stats(affiliate_id, headers, params=None)`
- `create_child(payload, headers)`; `get_child(child_id, headers)`; `list_children(headers, params=None)`
- `create_address_change(child_id, payload, headers)`; `list_address_changes(child_id, headers, params=None)`; `decide_address_change(change_id, payload, headers)`
- `create_title(payload, headers)`; `get_title(title_id, headers)`
- `create_selection(payload, headers)`; `get_selection(selection_id, headers)`; `list_selections(headers, params=None)`; `approve_selection(selection_id, headers)`; `reopen_selection(selection_id, payload, headers)`
- `create_print_order(payload, headers)`; `get_print_order(print_order_id, headers)`; `list_print_orders(headers, params=None)`; `confirm_print_order(print_order_id, headers)`
- `create_wave(payload, headers)`; `manifest_wave(wave_id, headers)`; `reconcile_wave(wave_id, headers)`
- `get_item(item_id, headers)`; `list_items(headers, params=None)`; `mark_item_returned(item_id, headers)`
- `get_invoice(invoice_id, headers)`; `list_invoices(headers, params=None)`; `issue_invoice(invoice_id, headers)`; `pay_invoice(invoice_id, headers)`; `dispute_invoice(invoice_id, payload, headers)`

**types**: enums `UserRole, AgreementStatus, EnrollmentStatus, UnenrollReason, AddressChangeStatus, AgeBand, SelectionStatus, PrintOrderStatus, WaveStatus, ItemStatus, InvoiceStatus, DisputeOutcome, AddressChangeOutcome`; TypedDicts `MailingAddress, StateProgram, Affiliate, AffiliateAgreement, PopulationStat, Child, AddressChange, Title, AgeBandSelection, PrintOrder, MailingWave, MailingItem, AffiliateInvoice, PenetrationReport, ClockResponse` (all entities carry id/created_at/updated_at/version).

**api_errors**: `ApiErrorId` (35 members), `HTTP_STATUS_CODES` (registered with framework via `set_error_http_status_map` at import).

**assertions**: `assert_state_program/affiliate/affiliate_agreement/population_stat/child/address_change/title/age_band_selection/print_order/mailing_wave/mailing_item/affiliate_invoice/penetration_report/clock_response(data)`; invariants `assert_invoice_invariants(invoice)` (gross == state+local+credit; PER_LINE pinned when issued+), `assert_confirmed_print_order_pricing(order)` (total == qty×unit+plate), `assert_dispute_outcome(value)`.

**factories** (payload dicts, `**overrides`): `set_clock_payload(current_utc=CLOCK_START)`, `create_state_program_payload()`, `create_affiliate_payload(state_program_id)`, `create_agreement_payload(expected_affiliate_version)`, `create_population_stat_payload()`, `create_child_payload(affiliate_id)`, `create_address_change_payload(new_address=None)`, `decide_address_change_payload(outcome="APPROVE")`, `create_title_payload(age_band)`, `create_selection_payload(mailing_month, age_band, title_id)`, `reopen_selection_payload(reason=None)`, `create_print_order_payload(selection_id, quantity=6000, is_reprint=False)`, `create_wave_payload(mailing_month="2026-10")`, `dispute_invoice_payload(outcome, credit_amount_cents=None)` (credit key omitted when None). Data constants: `DEFAULT_ADDRESS`, `DEFAULT_TITLE_BY_BAND`, `DEFAULT_CHILD_SPECS`.

**test_users**: `TEST_USERS` dict with keys `platform_admin_headers, state_program_officer_headers, affiliate_coordinator_headers` (last two are non-ownership fallbacks only), `advisory_committee_member_headers` (acm-ada), `_2` (acm-ben), `_3` (acm-cid), `publisher_ops_headers, mail_ops_headers`. Builders: `make_affiliate_coordinator_headers(affiliate_id)`, `make_state_program_officer_headers(state_program_id)`, `make_advisory_committee_member_headers(user_id)`, `make_platform_admin_headers(user_id=...)`, `make_publisher_ops_headers(user_id=...)`, `make_mail_ops_headers(user_id=...)`.

**fixtures** (all raise `AssertionError("Setup failed: …")` on precondition failure):
- Tier 1: `set_logical_clock(current_utc=CLOCK_START)`, `create_state_program(**ov)`, `create_affiliate(program_id, **ov)`, `create_agreement(affiliate, expected_affiliate_version=None, **ov)` (OCC defaults to `affiliate["version"]`), `approve_agreement(agreement_id, state_program_id)`, `reject_agreement(...)`, `create_population_stat(affiliate_id, **ov)`, `create_title(age_band, **ov)`, `propose_selection(mailing_month, age_band, title_id, proposer_id=ACM_PROPOSER_ID)`, `approve_selection(selection_id, approver_id=ACM_APPROVER_ID)`, `reopen_selection(selection_id, reason=None, member_id=ACM_APPROVER_ID)`, `create_print_order(selection_id, quantity=6000, is_reprint=False, **ov)`, `confirm_print_order(order_id)`, `register_child(affiliate_id, **ov)`, `create_address_change(child_id, affiliate_id, new_address)`, `decide_address_change(change_id, affiliate_id, outcome="APPROVE")`, `create_wave(mailing_month="2026-10")`, `manifest_wave(wave_id)`, `reconcile_wave(wave_id)`, `mark_item_returned(item_id)`, `issue_invoice(invoice_id)`, `pay_invoice(invoice_id, affiliate_id)`, `open_invoice_dispute(invoice_id, affiliate_id)`, `resolve_dispute_overruled(invoice_id)`, `resolve_dispute_upheld(invoice_id, credit_amount_cents)`
- Tier 2: `setup_operative_affiliate(program_overrides=None, affiliate_overrides=None, agreement_overrides=None, clock=CLOCK_START, approve=True, population_stat=None)` → `{program, affiliate, agreement, population_stat}` (affiliate re-fetched post-decision); `setup_second_affiliate(program, postal_prefixes, agreement_overrides=None, approve=True, **affiliate_overrides)`; `setup_five_titles(available_from_month="2026-01", available_until_month="2027-12")` → `{band: title}`
- Tier 3: `setup_approved_selection(mailing_month, age_band, title_id=None, title_overrides=None, proposer_id=..., approver_id=...)` → `{title, selection}`; `setup_locked_selection(mailing_month, age_band, title_id=None, quantity=6000, is_reprint=False, title_overrides=None)` → `{title, selection, order}` (selection LOCKED); `setup_month_supply(mailing_month="2026-10", quantities=None, titles=None, title_window=None, is_reprint=False)` → `{titles, selections, orders}` keyed by band, all LOCKED/CONFIRMED
- Tier 4/5: `register_children(affiliate_id, specs=None)` → list; `setup_wave_ready(mailing_month="2026-10", child_specs=None, quantities=None, clock=CLOCK_START, program_overrides=None, affiliate_overrides=None, agreement_overrides=None, title_window=None, with_population_stat=False, population_overrides=None)` → ctx `{program, affiliate, agreement, population_stat, titles, selections, orders, children, wave, mailing_month}`; `setup_manifested_wave(**kwargs)` (+`items`); `setup_reconciled_wave(**kwargs)` (+`invoices`); `setup_issued_invoice(**kwargs)` (+`invoice`, ISSUED)
- Lookups/math: `list_wave_items(wave_id)`, `get_child_wave_item(wave_id, child_id)` (exactly-one), `get_wave_invoices(wave_id)`, `get_wave_invoice(wave_id)` (exactly-one), `get_affiliate(affiliate_id)`, `get_child(child_id)`, `add_months(month, n)`

**conftest fixtures**: `api` (session), plus 8 header fixtures named exactly as the TEST_USERS keys.

#### PRD-vs-scaffold constant diff
No conflicts. Every constant value (clock start `2026-09-01T00:00:00Z`, capacity 400,000 inclusive, tiers 210/185/160/140 at 5,000/20,000/50,000, plate 25,000 waived ≥20,000-or-reprint, reprint 9/10 round-half-up, handling 35¢, auto-unenroll at 2, band edges 0/12/24/36/48/60, default cap 300¢, pagination 10/1/100, funding_share_bp 0..10000) matches PRD prose verbatim. No dead constants: each is consumed by helpers or is a PRD-stated assertion target; `BOGUS_UUID="8a3e1c0b-…"` intentionally matches the design recipes' probe id (framework's `NON_EXISTENT_UUID` differs and is also re-exported).

#### Verification output
- `python -m py_compile` on all 10 files → `PY_COMPILE_ALL_OK`
- `python -c "import test_helpers"` from task dir → `IMPORT_OK`; 40 endpoint methods (+ inherited framework helpers `get/post/put/delete/base_url/session`); 35 error codes registered; 8 TEST_USERS keys; 43 fixture exports
- `python -m pytest test_suite --collect-only -q` → "no tests collected" with **no conftest errors**

#### Hand-off notes for Step 5b
1. Corner instance `created_child_immediately_readable_with_identical_fields` asserts `expected_final_mailing_month == "2030-12"` for a 2025-12 birth, but PRD's "birth month plus fifty-nine months" gives **2030-11** (the other two anchors check out: 2021-10→2026-09, 2024-02→2029-01). Re-derive; don't copy the literal.
2. Corner instance `trailing_12_window_excludes_items_older_than_window` sets the clock to 2025-10-01, *before* the startup default 2026-09-01. PRD only says the clock "advances" and states no monotonicity rejection — apply the two-reader test before translating; the helpers' `set_logical_clock` passes any value through.
3. Entity-backed identity is fully threaded: fixtures never use the shared coordinator/officer fallback constants for ownership-gated calls.

Orchestrator verification: all 10 helper files + conftest.py on disk, `py_compile` clean, no test_*.py files yet (expected for 5a).

## Step 5b: Generate test suite — 2026-10-01T14:55:00.000Z

Step 5b complete. All work is done; here is the summary.

### Files written (9 test files, 80 tests)

All under `/home/ubuntu/github/CodingPRD/tasks/task_3384_age_based_book_mailing_enrollment_local_affiliate/test_suite/`:

| File | Tests | Covers |
|---|---|---|
| `test_01_affiliates_and_agreements.py` | 11 | affiliate defaults/system-fields, agreement round-trip, window rules, OCC 412, geography adjacency (×2), RBAC/404 ordering |
| `test_02_child_registration.py` | 11 | computed fields, missing-field 400, pagination/filters, duplicate/coverage/operativity guards, 59-vs-60-month boundary (×2), immediate read |
| `test_03_address_changes_and_transfers.py` | 10 | reject-quiet-branch, graduated lockdown, hold cycle (×2), transfer cascade (×2), branch-by-target-state (×2), enrollment conservation (×2) |
| `test_04_titles_and_selections.py` | 8 | enum 400, title window, self-approval 403, locked-reopen 409, rework cycle (×2), month-past-beats-duplicate (×2) |
| `test_05_print_pricing_and_capacity.py` | 7 | 4999/5000 tier boundary, tier×plate×reprint interaction (×2), 400000 capacity boundary (×2), state-beats-capacity (×2) |
| `test_06_waves_and_returns.py` | 13 | past-month wave, inventory shortfall, manifest idempotency, post-reconcile return 409, manifest/reconcile side effects, 11-vs-12-month bands, zero-eligible (×2), blocked-until-locked (×2), return cascade (×2) |
| `test_07_invoices_and_disputes.py` | 10 | floor division, PER_LINE vs AGGREGATE (×2), round-then-sum (×2), pay-from-draft 409, overruled cycle, credit>gross 422, credit-memo conservation (×2) |
| `test_08_penetration_reporting.py` | 5 | null rates without stats, greatest-year-≤ selector, trailing-12 window edges, snapshot/trailing divergence (×2) |
| `test_09_auth_rbac_and_sweep.py` | 5 | entity-specific 404 family (8 probes), missing headers 401, exclusive-role denials, three uniqueness 409s, clock sweep graduation+expiration |

### Coverage

- **Queue A (Difficulty)**: 18/18 instances translated, exactly 2 tests each (36 tests).
- **Queue B (Corner)**: 44/44 non-stub instances translated, 1 test each (44 tests). The 6 `excluded_because:` stubs were not translated; all their `difficulty_instance` cross-references resolve.
- **Skipped by PRD-first filter**: none.

### Repairs applied during translation (fixture/literal re-derivation, not skips)

1. `created_child_immediately_readable_with_identical_fields`: asserted `expected_final_mailing_month == "2030-11"` — PRD §3.3's "birth month plus fifty-nine months" for a 2025-12 birth (the yaml's "2030-12" was off by one; the corrected value is uniquely derivable).
2. `trailing_12_window_excludes_items_older_than_window` and `age_band_boundaries_11_vs_12_months`: clock set before the 2026-09-01 startup default is kept — PRD §2.4 states no monotonicity rejection and the closed error catalog has no clock error, so both PRD readers accept the set.
3. `selection_outside_title_window_rejected`: the yaml fixture (clock 2026-09, month 2026-08) is internally inconsistent with PRD §2.8 ordering — 2026-08 is also past, so check 9 would fire `ERR_SELECTION_MONTH_PAST`, not the asserted `ERR_TITLE_UNAVAILABLE_MONTH`. Re-derived: clock 2026-01-01, window 2026-01..2026-06, reject 2026-08, accept 2026-06 (inclusive edge).
4. Absolute affiliate `version` values (1/2/3) are not PRD-pinned; asserted the PRD-stated relative rule ("increments ... by one", §3.2) instead.
5. `created_at == logical-clock` equality in the affiliate-defaults instance is not uniquely derivable (§2.5 mandates ISO-8601 with three fractional digits, not the clock source) — asserted presence/type/derived defaults instead.
6. No `GET /library/waves/{id}` exists, so wave-state persistence claims (e.g. "stays SCHEDULED") are asserted via observable proxies: items list, title stock, child counters.

### Audit results

- **AST tag audit** (real `ast.parse` walk of every `test_*` function, incl. class methods): 80 tests; **0 untagged, 0 dual-tagged, 0 dangling, 0 tags pointing at stubs**; every `Design:` line is the docstring's final line and resolves verbatim to an instance `name:`; difficulty ≥2 and corner ≥1 counts satisfied everywhere. Audit exit 0.
- **Citation check**: every docstring carries a ≥8-word span that greps PRD.md verbatim (5 initially failing quotes with ellipses were rewritten to complete-sentence citations; re-audit clean).
- **`pytest test_suite --collect-only -q`**: **80 tests collected in 0.43s, no collection errors.**
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code; `test_helpers/` and `conftest.py` untouched.

Orchestrator verification: `pytest --collect-only -q` re-run by orchestrator → **80 tests collected in 0.21s, no collection errors**; 9 test_*.py files on disk.

## Step 6: Generate implementation — 2026-10-01T15:48:00.000Z

Implementation complete and verified. Final summary:

### Files written (all in `workspace/implementation/`)

- `start.sh` — foreground launcher; guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`; chmod +x
- `requirements.txt` — flask>=2.2
- `app.py` — entry point, blueprint registration, ApiError/404/405/500 handlers; binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dict stores (empty at boot, nothing seeded), logical clock starting at exactly `2026-09-01T00:00:00Z`, `base_record()` (id UUID, created_at/updated_at with 3 fractional digits, version=1), `touch()` version bump
- `errors.py` — `ApiError(status, error_id, message)`
- `response.py` — exact scaffold envelope: `meta.api_request_id` (`req_…`), `api_request_timestamp`, `response_type` object/array/error, pagination fields `limit/offset/total_count/has_more` in `meta`
- `validation.py` — auth (X-User-ID/X-User-Role, 6 roles), body well-formedness (unknown/system-field rejection, month/prefix/address shape checks), ISO8601 parsers, limit/offset validation (1–100 / ≥0)
- `domain.py` — calendar-month math, age bands (0/12/24/36/48/60 edges), derived fields computed against the live store (`operative`, `enrolled_count`, `stock_on_hand`, `billable`), half-up rounding via Decimal, serializers that strip internal `_` keys
- `routes_admin.py` — clock + sweep (graduation when current month > birth+59; agreement expiry when now ≥ effective_to), state programs, affiliates, penetration (SNAPSHOT + TRAILING_12, population-stat selector with fallback)
- `routes_agreements.py` — agreement create with OCC (`expected_affiliate_version` → 412, bumps affiliate.version on success), officer approve/reject with half-open overlap rule (adjacency allowed), population stats
- `routes_children.py` — child registration (all 5 guards in priority order), address changes, 3-branch decide (IN_AREA / TRANSFER with earliest-covering-agreement selector / UNENROLLED)
- `routes_catalog.py` — titles, selections (SoD self-approval 403, rework cycle), print orders (tier pricing 210/185/160/140, reprint ×0.9 round-half-up, plate fee 25000 waived ≥20000 or reprint, press capacity 400000 equality allowed, confirm locks selection)
- `routes_waves.py` — waves, manifest (5-band LOCKED gate then aggregate-per-title stock gate, 5-rule eligibility, per-child items), reconcile (auto-DELIVERED, PER_LINE invoices: floor division + 35¢ handling, per-line half-up state share), mark-returned (hold at 1, auto-unenroll at 2)
- `routes_invoices.py` — issue/pay/dispute with role-split outcomes (OPEN coordinator-only, RESOLVE_* admin-only) and credit memo invariant `gross == state + local + credit`

### Endpoint count
40 API endpoints registered (verified by listing `app.url_map` — 41 rules including Flask's built-in `/static`).

### Organization of key concerns
- **Validation ordering** follows PRD §2.8 literally inside each handler: auth → role → path existence (left-to-right, entity-specific 404s) → body → ownership → OCC → state → SoD → temporal → uniqueness → FK+dependent → capacity/fiscal.
- **State machines** live in the route handlers with exact preconditions and side effects from the scaffold; derived counters (`enrolled_count`, `stock_on_hand`, `operative`, `billable`) are computed from the live store so they can never drift.
- **Calculations** use integer cents throughout; Decimal ROUND_HALF_UP for the reprint discount, per-line state share, and penetration basis points; floor division for per-item book cost.

### Verification output
- `python3 -m py_compile` on all 12 .py files: all OK
- App import + route dump: clean import, all 40 routes present
- End-to-end smoke on dynamic port 18347 (PID saved, killed exactly): program → affiliate → agreement OCC 412 → approve → operative → child register + duplicate/future-birth/coverage rejections → 5-band selection/confirm with pricing (unit 210, plate 25000, total 46000, production_month 2026-09, selection LOCKED) → wave manifest (1 INFANT item) → mark-returned (UNDELIVERABLE_HOLD, billable false) → reconcile (no invoice when all items returned) → in-area address change clears hold → penetration (10 bp snapshot/trailing) → clock sweep graduation — all passed
- `bash start.sh` boot on port 18912: serves correct envelope from a fresh empty store (`total_count: 0`); process killed cleanly by its own PID

Orchestrator verification: all 14 files on disk incl. executable start.sh; `py_compile` clean; `app.url_map` shows 41 rules (40 app + Flask /static).

## Step 7: Test/fix iteration loop — 2026-10-01T16:00:00.000Z

All 8 rounds pass 80/80. The final `results.*.json` artifacts remain in place per the artifact rule.

### Summary

**Iterations run:** 2 (baseline sweep: 78/80 × 8 rounds, deterministic; verification sweep after fixes: 80/80 × 8 rounds).

**Tests deleted:** none.

**Fixes applied to `test_suite/` (2):**

1. `test_suite/test_04_titles_and_selections.py` — `test_title_create_with_invalid_age_band_returns_invalid_request`: the call `create_title_payload("INFANT", ..., age_band="FIVE", ...)` passed `age_band` both positionally and by keyword, raising `TypeError` before any request was issued (the factory's first positional parameter *is* `age_band`). Removed the stray positional `"INFANT"` so the payload carries the invalid band `"FIVE"` as intended. PRD coverage verified verbatim: §3.5's five-band enum plus §2.8's "enum values are in range … any violation is `ERR_INVALID_REQUEST`".

2. `test_suite/test_08_penetration_reporting.py` — `test_trailing_12_window_excludes_items_older_than_window`: corrected two expected basis-point values from 20 to 2 (trailing-12 bp for October, and snapshot bp for both months). The test's own comment mis-computed `round_half_up(1 × 10000 / 5000)` as 20; it is 2. PRD §3.8 pins the formula verbatim ("count times 10,000 divided by `eligible_population`, rounded half up"), and the sibling test in the same file uses the identical convention (`2 × 10000 / 8000 → 3`, `2 × 10000 / 10000 → 2`), confirming the implementation's returned value of 2 was PRD-correct.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on both paths (enum rejection and the basis-point formula); both failures were test-side defects.

Orchestrator verification: all 8 `results.{1..8}.json` present with total=80/passed=80/failed=0/errors=0/skipped=0; all implementation/*.py mtimes (≤15:48) predate the final 16:00 sweep; spot-checked both test fixes on disk (test_04 line 42 keyword-only call; test_08 asserts bp == 2).

## Step 8: Finalize PRD — 2026-10-01T16:10:00.000Z

Done. `workspace/PRD_FINALIZED.md` is written and is byte-identical to `PRD.md`.

### Summary

**Line counts / delta:** PRD.md = 277 lines, PRD_FINALIZED.md = 277 lines, 0.0% delta (md5 `ce5f334878e3b2718d1010345f3cd7cc` for both).

**Changes: zero edits.** Both `<step_7_diff>` items are confirmed pure test-side defects with verbatim PRD coverage; neither reveals a PRD silence nor a PRD/impl mismatch, so no edit was manufactured.

**Investigation evidence per diff item:**

1. **test_04 invalid age_band (test-side fixture bug — stray positional arg).**
   - PRD coverage is verbatim: §3.5 (PRD.md:156) pins the five-band enum `INFANT`/`TODDLER`/`TWO`/`THREE`/`FOUR`, and §2.8 item 4 (PRD.md:113) pins "enum values are in range … any violation is `ERR_INVALID_REQUEST`".
   - Impl matches exactly: `implementation/routes_catalog.py:53-55` raises `ApiError(400, "ERR_INVALID_REQUEST", ...)` when `age_band not in domain.BANDS`, with `BANDS = ("INFANT", "TODDLER", "TWO", "THREE", "FOUR")` at `implementation/domain.py:8`. The same guard exists on the parallel selection-create path (`routes_catalog.py:89-92`), so the PRD wording already covers every path touching `age_band` validation.
   - The fixed test (`test_suite/test_04_titles_and_selections.py:42-45`) now passes `age_band="FIVE"` by keyword only and quotes both PRD sections in its docstring.

2. **test_08 basis-point values 20 → 2 (test-side arithmetic mis-computation).**
   - PRD coverage is verbatim: §3.8 (PRD.md:188) pins "`penetration_snapshot_bp` is that count times 10,000 divided by `eligible_population`, rounded half up, when the population is positive, else null" and states the trailing-12 bp "is computed from it the same way".
   - Impl matches exactly: `implementation/routes_admin.py:157` and `:166` compute `domain.round_half_up_ratio(enrolled * 10000, eligible)` / `round_half_up_ratio(t12 * 10000, eligible)`, where `round_half_up_ratio` (`implementation/domain.py:42-43`) is `Decimal(num)/Decimal(den)` quantized with `ROUND_HALF_UP`. For the test's numbers, round_half_up(1 × 10000 / 5000) = 2 — the corrected expectation. Null-when-zero-population also matches (`if eligible > 0 else None`).
   - The fixed test (`test_suite/test_08_penetration_reporting.py:139-140`) now carries the corrected comment `round_half_up(1 x 10000 / 5000) = 2` and asserts `== 2`.

No implementation fixes, no test deletions, and no test_helpers fixes were listed in the diff, so there was nothing further to trace.

Orchestrator verification: `diff -q PRD.md PRD_FINALIZED.md` → identical; md5 `ce5f334878e3b2718d1010345f3cd7cc` matches for both.

## Step 9: PRD completeness scan — 2026-10-01T16:45:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written — 277 lines (unchanged; all edits are inline), 42,100 → 45,307 chars (+3,207), 26 edits in 24 diff hunks, no new sections, no table changes.

### Counts
- Ambiguity-pins: 23 (PRD silent → pinned to impl behavior)
- Mismatch-revisions: 3 (PRD described different behavior → revised to match impl)

### Mismatch-revisions
- §2.9 — revise — mismatch — derived counters are computed from the live store whenever the resource is read (not stored and recomputed per event); business content (who counts, formulas) unchanged — implementation/domain.py:65-85, 107-132 (ser_affiliate/ser_title compute live)
- §3.7 — revise — mismatch — inventory gate aggregates demand **per title** (sum over bands whose locked selection names that title), not per-band; §2.8 step 12 wording aligned ("per-title stock at manifest") — implementation/routes_waves.py:105-113
- §3.7 — revise — mismatch — "gated twice" → "gated three times" (impl enforces three manifest gates) — implementation/routes_waves.py:85-113

### Ambiguity-pins (one bullet each)
- §2.1 — insert — single-resource GETs carry no coordinator scope; only the listed list endpoints + penetration report are scoped — routes_children.py:101-104, routes_invoices.py:27-30, routes_admin.py:108-111
- §2.2 — insert — `api_request_timestamp` is wall-clock (not logical clock) — response.py:19-27
- §2.3 — insert — non-integer/out-of-range limit/offset → `ERR_INVALID_REQUEST`; creation-timestamp ties break by creation order; `has_more` = offset + returned < total_count — validation.py:198-219, response.py:45
- §2.4 — insert — clock-set adopts the supplied instant unconditionally (no monotonicity check); response echoes the supplied string verbatim — routes_admin.py:44-57
- §2.5 — insert — `created_at`/`updated_at` stamped from the logical clock; `version` starts at 1 — db.py:57-77
- §2.8 step 4 — insert — required strings must be non-empty, address `postal_code` non-whitespace, month number must be 01–12 — validation.py:73-76, 122-128, 179-180
- §2.8 step 11 — insert — print-order submission's selection-`APPROVED` requirement classified as an FK-dependent rule (keeps cascade consistent with impl's ordering) — routes_catalog.py:202-204
- §3.1 — insert — duplicate `state_code` (exact, case-sensitive) → `ERR_INVALID_REQUEST` — routes_admin.py:70-73
- §3.1 — insert — supplied `max_state_share_per_book_cents` must be a non-negative integer — routes_admin.py:69
- §3.1 — insert — `contact_email` is any non-empty string (no format validation) — routes_admin.py:93
- §3.1 — insert — affiliate `state_program_id`/`name` filters are exact-match — routes_admin.py:118-122
- §3.2 — insert — window bounds are ISO 8601 datetimes (missing offset read as UTC), stored/echoed verbatim; `decided_by` null until decision — validation.py:135-148, routes_agreements.py:34-59
- §3.3 — insert — `birth_date` accepted as ISO date or datetime, echoed verbatim, compared by calendar date value — validation.py:157-166, routes_children.py:33,78
- §3.3 — insert — `unenroll_reason` and `transfer_source_child_id` null at creation — routes_children.py:38-40
- §3.4 — insert — address change starts `PENDING` with `decided_by`/`resulting_child_id` null — routes_children.py:148-150
- §3.4 — insert — decide `outcome` tokens are exactly `APPROVE`/`REJECT` (else `ERR_INVALID_REQUEST`) — routes_children.py:203-206
- §3.4 — insert — approval re-validates the child is still non-terminal at decision time (else `ERR_INVALID_STATE`) — routes_children.py:220-223
- §3.4 — insert — transfer selector's remaining ties (after effective_from, created_at) break by agreement creation order — routes_children.py:187
- §3.4 — insert — a return on an already-terminal child still transitions the item and increments counters but leaves status unchanged — routes_waves.py:230-242
- §3.5 — insert — `approved_by` null until approval — routes_catalog.py:117
- §3.5 — insert — reopen `reason` accepted but not persisted — routes_catalog.py:170
- §3.6 — insert — submission requires the selection `APPROVED`; the existing-`CONFIRMED`-order guard is evaluated first (LOCKED → `ERR_SELECTION_ALREADY_SUPPLIED`; PROPOSED → `ERR_INVALID_STATE`) — routes_catalog.py:199-204
- §3.7 — insert — new wave starts with `manifested_item_count`/`returned_item_count` at zero — routes_waves.py:49-50
- §3.7 — insert — manifest processes eligible children in registration order — routes_waves.py:60,115
- §3.8 — insert — dispute outcome tokens are exactly `OPEN`/`RESOLVE_OVERRULED`/`RESOLVE_UPHELD`; other tokens → `ERR_INVALID_REQUEST`; `credit_amount_cents` must be an integer and is consulted only by `RESOLVE_UPHELD` — routes_invoices.py:16,92-96,123
- §3.8 — insert — `population_stat_year` is null when the affiliate has no stats; a malformed `month` query param → `ERR_INVALID_REQUEST` — routes_admin.py:139-140,154

### Dead-code check
All PRD-required guards verified to have live callsites on the request path (grep-verified): auth/role guards on all 40 endpoints (`require_roles`), coordinator/officer ownership checks (inline in every scoped handler), OCC stale-version check (routes_agreements.py:43), duplicate-registration guard (routes_children.py:75-83), `operative_for_month` gating registration + manifest (routes_children.py:89, routes_waves.py:68), geography-overlap check at approval (routes_agreements.py:96-107), self-approval check (routes_catalog.py:157), title-availability window (routes_catalog.py:107), already-supplied guard at submit + confirm (routes_catalog.py:199,254), press-capacity gate (routes_catalog.py:259-264), manifest selection-completeness + per-title inventory gates (routes_waves.py:90-113), (child,month) duplicate prevention in manifest eligibility (routes_waves.py:70-76), credit-memo bounds (routes_invoices.py:123), transfer-target selector (routes_children.py:174-191), `run_sweep` wired to the clock endpoint (routes_admin.py:52), `round_half_up_ratio` used in invoice split + penetration. **No dead PRD-required checks found.**

Orchestrator verification: PRD_COMPLETED.md on disk (277 lines, differs from PRD_FINALIZED.md — real edits, not a no-op); 0 implementation/*.py files newer than results.8.json (sweep not invalidated); all 8 results.*.json present; test suite still collects 80 tests cleanly.
