# Worklog — task_3451_electronic_benefit_card_processing_state_program_account

Scenario: Electronic Benefit Card Processing & State Program Account Operations (Conduent): state contract implementation with benefit program configuration for food, cash and disaster assistance with separate purse rules, card issuance, mailing, activation and replacement with fee rules that differ by program and state, eligible item restriction enforcement at the point of sale using retailer item files with exception handling, benefit posting schedules staggered across a month by case identifier with availability timing, expungement of unused benefits after inactivity periods with notification requirements, retailer settlement and reconciliation across acquirers with dispute handling, cardholder customer service including balance inquiry, personal identification number reset and skimming claim investigation, program integrity reporting and transaction data delivery to the state

Difficulty directive: "Generate task much harder than expert level!" (applies to prd-bench-scaffold-generator only).

## Step 1: Create task directory — 2026-10-02T05:39:00.000Z

Pre-allocated directory `tasks/task_3451_electronic_benefit_card_processing_state_program_account/` verified to exist with `workspace/` inside (per command args; no new index computed, no other task_* directory created). `INSTRUCTION.md` present at project root; all prd-bench skills present; `prd-bench-local-run` on PATH.

## Step 2: Generate scaffold — 2026-10-02T07:09:00.000Z

All three artifacts are written, parse cleanly, and pass the linter. Summary:

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_3451_electronic_benefit_card_processing_state_program_account/SCAFFOLD.yaml` (§1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3451_electronic_benefit_card_processing_state_program_account/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3451_electronic_benefit_card_processing_state_program_account/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts**
- Endpoints: **40** (at the hard cap, incl. 1 platform clock endpoint)
- Entities: **14** | State machines: **13** | Calculations: **12** | Errors: **40** | Roles: **4**
- §1.8 instances: **19** (every §0.5 rule has ≥2; combinatorial_formula has 3, one per mode a/b/c)
- §1.9 instances: **51 active + 3 excluded_because stubs**

**Verification**
- All three files parse as valid YAML; top-level key discipline confirmed programmatically.
- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (816 calls scanned, 0 violations)
- Additional audits I ran and passed: instance-name uniqueness across both design files, zero unbound `${var}` placeholders, every `grounds:` reference resolves (calculations/transitions/validations/fields/errors/concurrency-rules/roles/endpoints), every error id referenced, enum-value closure on every state-machine field and on LedgerEntry entry types, no forbidden concurrency vocabulary, every rule_id at ≥2 instances, clock monotonicity (forward-only) within all 70 fixture chains, and no fixture date earlier than the clock default.
- Every named constant carries a concrete value in both the top-level `constants:` block and the StateContract field defaults (values kept identical; verified).

**Logical clock**: starts at exactly `2026-09-01T00:00:00Z` on server startup (never wall-clock); advanced only via `POST /_clock/set_current_utc` (forward-only), mounted **outside** the `/ebt` api_prefix and declared as such in SCAFFOLD.yaml. Each set runs a pinned 7-step sweep (availability → disaster expiry → expungement notice/expunge + dormancy cascade → card mailing → provisional credit → settlement cutoff + daily file → monthly integrity report), with multi-day jumps applied per crossed boundary.

**Key interpretive choices** (scenario → design):
- Difficulty is depth-driven per the directive: dual balance variants (LEDGER vs SPENDABLE on Purse; GROSS vs NET on SettlementBatch), split-tender waterfall with a no-cross-purse-spill rule and disaster-purse-first priority, pinned round-per-transaction-then-sum acquirer fees, FIFO attribution for disaster expiry, and a 3-link expungement→dormancy→card-deactivation cascade.
- "Exception handling" for item eligibility = per-FOOD-program `item_restriction_mode` STRICT/LENIENT; LENIENT allows unknown UPCs with an `exception_flag_count` that feeds the monthly integrity report (no separate exception entity — kept the endpoint budget).
- Interval-overlap rule (Rule 8) is grounded twice with different semantics: RetailerItem windows are half-open (adjacency allowed), DISASTER program windows are closed (adjacency conflicts).
- Replacement fee is a pinned evaluation order: free allowance (1 per trailing 365d) → CASH purse absorbs its program's fee if spendable ≥ fee → FOOD purse → full waiver (never partial).
- Segregation-of-duties role model: claims filed by a CardholderServices user cannot be investigated by the same X-User-ID (ERR_SOD_VIOLATION); adjudication is StateAdmin-exclusive.
- One OCC rule (CaseAccount version on the status endpoint); void windows were given a reachable temporal path by allowing `settlement_cutoff_hour_utc` override (a corner fixture uses cutoff hour 6 so ERR_VOID_WINDOW_EXPIRED is triggerable while still AUTHORIZED).
- The pre-existing `worklog.md` and `workspace/` in the task directory predate my run and were left untouched.

Orchestrator spot-check (post-hand-back): all three files exist and parse as YAML; SCAFFOLD.yaml has no design keys; design files have the correct single top-level keys; endpoint count is exactly 40; clock endpoint is `POST /_clock/set_current_utc` mounted outside `/ebt`; 20 constants, all with concrete values.

## Step 3: Copy shared files — 2026-10-02T07:12:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3451_electronic_benefit_card_processing_state_program_account/workspace/INSTRUCTION.md` (1424 bytes, verified present).

## Step 4: Generate PRD — 2026-10-02T07:16:00.000Z

All checks pass. The PRD is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3451_electronic_benefit_card_processing_state_program_account/workspace/PRD.md` — 398 lines, written in 5 chunks (1 Write + 3 quoted-heredoc appends + 2 targeted Edits).

**Structure:** §1 Introduction (3 paragraphs) · §2.1–2.11 (roles/identities, verbatim response envelope, pagination, logical clock + 7-step sweep, ledger conventions, rounding, dual balance views, the 23-step validation pipeline, nested retrieval, OCC, configuration defaults) · §3.1–3.10 (contracts/programs, retailers/items, cases/purses/ledger, allotments/postings, expungement/dormancy, cards/PIN/replacement, authorizations/voids, skimming claims, settlement/disputes, closure/data delivery) · §4 (40 endpoints, 4 columns) · §5 (40 errors, 2 columns).

**Required verifications:**
- **Constants:** 20/20 valued in prose — clock start `2026-09-01T00:00:00Z` and outside-prefix mount (§2.4); all 18 config defaults with exact values and constraint ranges (§2.11): modulus 10 (1–28), hour 6 (0–23), expungement 90 (≥31), notice lead 30 (≥1), disaster expiry 30 (≥1), fee 250 (≥0), free replacements 1 (≥0), PIN failures 3 (≥1), claim window 60 (≥1), provisional delay 10 (≥1), cap 50000 (≥0), suspend threshold 3 (≥1), dispute window 15 (≥1), 75 bp (≥0), daily limit 50000 (≥0), multiple 500 (≥1), cutoff hour 0 (0–23), mail delay 24 (≥0); key values repeated in §3 narrative context.
- **Clock endpoint:** §2.4 states the full unprefixed path `POST /_clock/set_current_utc`, explicitly "mounted outside the `/ebt` API prefix", start value, forward-only semantics (`ERR_INVALID_REQUEST` on backward), input `to_iso8601`/output `current_utc`, the pinned 7-step sweep in order, and per-boundary chronological application on multi-day jumps.
- **Error IDs:** 40/40 appear in §2/§3 prose (pipeline ordering in §2.8, trigger conditions scattered in §3) and in §5.
- **Contract 1 (field coverage):** 144 required names, 0 missing (fence-aware backtick extraction — note: the mandatory §2.2 JSON fences flip naive backtick pairing, so the checker must strip code fences; the markdown itself is well-formed).
- **Contract 2 (rule coverage):** PASS — all 13 state machines (incl. the parallel `credit_status` dimension), all 12 calculations in precise no-pseudocode prose (round-per-transaction-then-sum pinned with the 5-vs-3-cent contrast; FIFO tie-break `created_at` never id; replacement-fee waterfall CASH→FOOD with frozen-skip and DISASTER exclusion; split-tender no-spill order; proration round-half-up-once), validation priorities 1–23 with explicit ordering consequences (frozen beats fiscal; claims-before-balance on close; dispute-check before amount comparison; PIN_LOCKED short-circuit), the single OCC rule (`expected_case_account_version` → `ERR_STALE_VERSION` 412), and all endpoint side effects including "replacement does not increment case version".
- **Contract 3 (§3 path purity):** 613 backticked tokens in §3, zero path/method violations.
- **§2.2** is byte-identical to the canonical source (diff-verified).

**Scaffold rules not rendered:** none. One internal scaffold tension adjudicated in prose: validation 8's applies_to lists program creation under the contract-ACTIVE gate, but the program endpoint and the DRAFT/activation cascade require creation to be legal while `CONFIGURING`. The PRD renders program creation as permitted in `CONFIGURING` or `ACTIVE` (with `ERR_CONTRACT_NOT_ACTIVE` still guarding it against `SUSPENDED`/`CLOSED`), and reserves the strict ACTIVE gate for the other five operations — the only reading consistent with the DRAFT state existing at all.

Orchestrator spot-check (post-hand-back): PRD.md is 398 lines; 93 `ERR_` mentions; §2.4 states clock start `2026-09-01T00:00:00Z`, forward-only, and the unprefixed mount explicitly; constants `90`, `250`, `modulus`, and error ids `ERR_STALE_VERSION` / `ERR_VOID_WINDOW_EXPIRED` / `ERR_SOD_VIOLATION` all present.

## Step 5a: Generate test helpers (test_helpers/ only) — 2026-10-02T07:35:00.000Z

Step 5a complete. Here is the hand-off report for Step 5b.

### Files written (all under `.../test_helpers/`)

| File | Lines | Contents |
|---|---|---|
| `__init__.py` | 70 | Barrel export; submodules kept as modules; singleton named `default_client` |
| `types.py` | 420 | 4-role `UserRole` enum, 20 status/type enums, `LEDGER_CREDIT_TYPES`/`LEDGER_DEBIT_TYPES`, 15 entity TypedDicts (LedgerEntry omits `updated_at`/`version` per PRD §2.5) |
| `api_client.py` | 152 | `ApiClient(GenericApiClient)` — all 40 endpoints (39 business under `/ebt` + unprefixed clock); `default_client` singleton |
| `api_errors.py` | 106 | `ApiErrorId` (40 ids) + `HTTP_STATUS_CODES`, registered via `set_error_http_status_map` |
| `assertions.py` | 304 | `assert_<entity>` ×14, `canonical_instant`/`instants_equal`, `assert_purse_balances`, `assert_batch_position`, `assert_ledger_entry_types` |
| `factories.py` | 258 | 20 payload factories + `item_entry`/`purchase_item` + `DEFAULTS` |
| `constants.py` | 83 | 19 PRD constants + pagination + `CLAIM_MAX_REFERENCED_TXNS` + 6 pure PRD-formula helpers |
| `fixtures.py` | 596 | `Ctx`, ISO arithmetic, ~35 single-call primitives, 8 composites |

### Frozen helper API surface (Step 5b codes against this)

**Client** (`from test_helpers import default_client, ApiClient`): `set_clock(to_iso8601, headers)` (UNPREFIXED), `create_contract`, `get_contract`, `set_contract_status`, `list_contract_programs`, `run_allotment`, `list_data_deliveries`, `create_program`, `create_retailer`, `get_retailer`, `list_contract_retailers`, `set_retailer_status`, `upload_item_file`, `list_retailer_items`, `create_authorization`, `list_retailer_authorizations`, `void_authorization`, `list_case_accounts`, `create_case_account`, `get_case_account`, `set_case_status`, `list_case_cards`, `list_case_claims`, `list_purses`, `get_purse`, `list_purse_ledger`, `list_purse_postings`, `create_card`, `get_card`, `activate_card`, `replace_card`, `reset_pin`, `file_claim`, `set_claim_status`, `list_settlement_batches`, `get_settlement_batch`, `reconcile_batch`, `file_dispute`, `list_batch_disputes`, `set_dispute_status`. All return raw `Response`; use `validate_success(resp, 201)` for creates (contracts, programs, retailers, cases, cards, item-files, authorizations, claims, disputes, card-replacement, allotment runs) and 200 elsewhere.

**Headers** (`test_users`): `TEST_USERS` keys: `state_admin_headers`, `csr_headers` (csr-a), `csr_alt_headers` (csr-b), `cardholder_headers`, `retailer_system_headers` (last two = non-ownership fallbacks only). Builders: `make_cardholder_headers(case_id)`, `make_retailer_system_headers(retailer_id)`, `make_cardholder_services_headers(user_id)`, `make_state_admin_headers()`. Named ids: `STATE_ADMIN_USER_ID`, `CSR_USER_A`, `CSR_USER_B`. Malformed: `headers_without_role()`, `headers_without_user_id()`, `headers_with_unknown_role()`.

**Fixtures** (all take `api` first; composites return `Ctx` with attribute access):
- Primitives: `set_clock`, `create_contract`, `create_program`, `set_contract_status`, `create_retailer`, `set_retailer_status`, `upload_item_file`, `list_retailer_items`, `create_case`, `get_case`, `set_case_status` (OCC-aware, reads version first), `list_case_purses`, `get_purse_for_program`, `get_purse`, `list_ledger(entry_type=…)`, `list_postings(posting_status=…)`, `run_allotment` (→ `created_count`/`skipped_count`/`posting_ids`), `issue_card`, `activate_card` (as owning cardholder), `activate_card_as_csr`, `replace_card`, `replace_card_as_csr`, `reset_pin_as_csr`, `reset_pin_as_cardholder`, `place_purchase`, `place_withdrawal`, `void_authorization`, `file_claim(filer="cardholder"|"csr", csr_user_id=…)`, `investigate_claim` (default csr-b), `adjudicate_claim(to=…, substantiated_amount_cents=…)`, `list_batches`, `first_batch`, `get_batch`, `reconcile_batch`, `file_dispute`, `list_batch_disputes`, `decide_dispute`, `list_data_deliveries(delivery_type=…)`, `list_case_claims`, `list_case_cards`.
- Composites: `setup_active_contract(program_types=…, contract_overrides=…, program_overrides={type: {...}})` → ctx{contract, programs}; `add_retailer(ctx, item_entries=…, with_item_file=…, key=…)`; `add_case(ctx, case_identifier=…, key=…)` → ctx.purses by program type; `fund_case(ctx, allotments={type: cents}|"__default__"|{})`; `add_active_card(ctx, pin=…, activate_at=…)` (auto-computes issuance+25h, floored at 2026-09-02T12:00:00Z — never backward); `place_purchases(ctx, specs|count=…)`; `settle_authorizations(ctx, cutoff_at="2026-09-03T00:00:00Z")`; `setup_pos_ready(...)` (full preamble: contract+programs+retailer+items+case+allotments+active card, with `pre_case_clock` for proration setups); `setup_settled_batch(purchase_specs=…, …)` → ctx.batch; `file_claim_on(ctx, txns, amount, …)`; `setup_purchase_and_claim(...)`. Time helpers: `parse_utc`, `format_utc`, `iso_plus_hours`, `iso_plus_days`. Canonical clocks: `DEFAULT_ACTIVITY_CLOCK` (09-02T12:00Z), `DEFAULT_CUTOFF_CLOCK` (09-03T00:00Z).

**Factories**: `contract_payload`, `contract_status_payload(to)`, `program_payload(contract_id, program_type=…)` (optional overrides omitted unless given; DISASTER needs `disaster_window_start/end`), `retailer_payload`, `retailer_status_payload`, `item_entry(upc, food_eligible, effective_from="2026-08-01", effective_to=None)`, `item_file_payload(items)`, `case_account_payload`, `case_status_payload(to, expected_case_account_version)`, `allotment_run_payload(program_id, benefit_month="2026-09", amount_cents=30000)`, `card_payload`, `activate_card_payload(pin="1234")`, `pin_reset_payload(new_pin="4321", current_pin=None)`, `purchase_item`, `purchase_payload(card_id, pin, items)`, `withdrawal_payload(card_id, pin, withdrawal_amount_cents=500)`, `claim_payload(…, freeze_purse=True)`, `claim_status_payload(to, substantiated_amount_cents=None)`, `reconcile_payload`, `dispute_payload`, `dispute_status_payload(to, adjustment_cents=None)`, `clock_payload(to_iso8601)`.

**Assertions**: 14 `assert_<entity>` structural checks + `assert_purse_balances(purse, ledger_balance_cents=…, spendable_balance_cents=…)`, `assert_batch_position(batch, gross, fee, adj, net)`, `assert_ledger_entry_types(entries, […])`, `instants_equal(a, b)`.

**Errors**: `ApiErrorId.ERR_*` ×40 with the PRD §5 status map registered (validate_error auto-checks HTTP status).

### Constants table (all verified against verbatim PRD prose)

`LOGICAL_CLOCK_DEFAULT_UTC="2026-09-01T00:00:00Z"` (§2.4); §2.11: `DEFAULT_POSTING_MODULUS=10`, `DEFAULT_AVAILABILITY_HOUR_UTC=6`, `DEFAULT_EXPUNGEMENT_INACTIVITY_DAYS=90`, `EXPUNGEMENT_NOTICE_LEAD_DAYS=30`, `DEFAULT_DISASTER_EXPIRY_DAYS=30`, `DEFAULT_REPLACEMENT_FEE_CENTS=250`, `FREE_REPLACEMENTS_PER_365D=1`, `PIN_MAX_FAILURES=3`, `CLAIM_WINDOW_DAYS=60`, `PROVISIONAL_CREDIT_DELAY_DAYS=10`, `PROVISIONAL_CREDIT_CAP_CENTS=50000`, `SKIMMING_SUSPEND_THRESHOLD=3`, `DISPUTE_WINDOW_DAYS=15`, `ACQUIRER_FEE_BASIS_POINTS=75`, `CASH_WITHDRAWAL_DAILY_LIMIT_CENTS=50000`, `CASH_WITHDRAWAL_MULTIPLE_CENTS=500`, `SETTLEMENT_CUTOFF_HOUR_UTC=0`, `CARD_MAIL_DELAY_HOURS=24`; §2.3 pagination: `PAGE_LIMIT_DEFAULT=10`, min 1, max 100, offset 0; §3.8 `CLAIM_MAX_REFERENCED_TXNS=20`. Formula helpers: `round_half_up_ratio`, `posting_bucket`, `prorated_amount_cents`, `acquirer_fee_cents_for`, `net_position_cents`, `provisional_credit_cents_for` (all parameterized, no instance answers).

### Self-verification results

- **(a)** `python3 -m py_compile test_helpers/*.py` → OK (9 files).
- **(b)** Import check → `imports OK`; `test_helpers.api_client` resolves to the **module**, `default_client` is the `ApiClient` instance, `test_helpers.fixtures` resolves to the module (no shadowing). Error map size 40.
- **(c)** Clock grep → the only request-path literal is `/_clock/set_current_utc` (line 20 of api_client.py); all 39 business paths start `/ebt/`; no string ever concatenates the two (one docstring line mentions both in prose only).
- **(d)** Constant audit (AST) → all 19 constant names imported elsewhere in the package are defined in `constants.py`; zero misses. No undefined bare ALL_CAPS references (import check would have caught any).
- **(e)** Constants-vs-PRD scripted diff → 19/19 OK, 0 fails (each value matched to a verbatim PRD sentence, table above).
- Extra: no wall-clock reads anywhere (`datetime.now`/`time.time`/`utcnow` grep clean); `__pycache__` removed so later mtime sweeps stay accurate.

### PRD gaps routed around

None. Every fixture need was derivable from PRD-declared endpoints. Design notes Step 5b should know: (1) card activation requires the 24h mail delay — `add_active_card` handles it via clock advance, never field backdating; (2) fixture identity threading is mandatory — fixtures already mint `make_cardholder_headers(case["id"])` / `make_retailer_system_headers(retailer["id"])`; tests doing ownership-negative cases should build mismatch headers the same way; (3) `freeze_purse` is always sent explicitly (default True) so behavior never depends on server defaults; (4) multi-case recipes compose `add_case(..., key="case_b")` + `get_purse_for_program` directly.

Orchestrator spot-check (post-hand-back): all 9 files exist with the reported line counts (2067 total); `py_compile` clean; import check confirms `test_helpers.api_client` resolves as a module; clock request path at api_client.py:20 is unprefixed.

## Step 5b: Generate test suite (test_suite/) — 2026-10-02T08:12:00.000Z

All verifications pass. Step 5b is complete.

**Generated** `/home/ubuntu/github/CodingPRD/tasks/task_3451_electronic_benefit_card_processing_state_program_account/test_suite/` — 12 files, 2542 lines, **89 tests**:

| File | Lines | Tests | Content |
|---|---|---|---|
| `conftest.py` | 35 | — | session `api` fixture (returns `default_client`) + 5 role-header fixtures |
| `test_01_contract_program_case_setup.py` | 216 | 10 | case-identifier format/dup/missing, program enum, duplicate FOOD, contract/case ACTIVE+close gates, body-reference 422; difficulty: disaster closed-window adjacency ×2 |
| `test_02_posting_schedule_allotments.py` | 200 | 7 | default inheritance, first-month proration (26000 literal), month-window, duplicate run, suspended-case skip; difficulty: availability boundary ×2 (bucket 0 and bucket 3) |
| `test_03_purse_balances_ledger.py` | 138 | 5 | append-only ledger shape, 404, pagination envelope; difficulty: ledger-vs-spendable dual variant ×2 |
| `test_04_item_files_eligibility.py` | 170 | 6 | UPC-atomic file rejection, STRICT unknown-UPC, LENIENT exception flag, no-cash-purse; difficulty: half-open item windows ×2 (both adjacency directions) |
| `test_05_authorizations_withdrawals.py` | 166 | 6 | withdrawal multiple / no-cash-purse; difficulty: no-spill waterfall ×2, daily-limit boundary (exact-50000 allowed, voided-excluded) ×2 |
| `test_06_card_lifecycle.py` | 216 | 7 | not-mailed, double-replace, free allowance; difficulty: fee waterfall (CASH-priority debit 250; waiver) ×2, PIN lock cycle (lock→ERR_PIN_LOCKED→CSR reset; success resets counter) ×2 |
| `test_07_voids_compensation.py` | 165 | 6 | double-void, next-day void (cutoff-hour-6 override), cross-retailer void, immediate reread; difficulty: void restores purse ×2 (single- and multi-purse) |
| `test_08_settlement_disputes_delivery.py` | 375 | 14 | day boundary, dispute window inclusive ±1s, mismatch→RECONCILIATION_MISMATCH(−92), terminal dispute; difficulty: fee round-per-txn ×2 (5-vs-3 pinned; half-up 2+1=3), gross-vs-net ×2, reconcile-blocked ×2, pre-cutoff void conservation ×2; daily file + monthly integrity report |
| `test_09_skimming_claims.py` | 447 | 15 | amount-exceeds, case-mismatch, early adjudication, CSR-adjudicate 403, SoD; difficulty: parallel credit dimensions ×2 (provisional 50000 at inclusive boundary → FINAL with −5000 reversal; pre-provisional full CLAIM_CREDIT), retailer threshold cascade ×2 (3 suspends; 2 doesn't), frozen-beats-insufficient ×2, window-beats-mismatch ×2 |
| `test_10_case_state_sweeps_occ.py` | 287 | 8 | suspend/reinstate, terminal CLOSED, nonzero-balance close, OCC 412, disaster FIFO expiry (24500), dormant reactivation leaves cards DEACTIVATED; difficulty: expungement→dormancy→card chain ×2 (full chain + activity-restarts-clock) |
| `test_11_rbac_retailer_state.py` | 127 | 5 | unauthenticated (4 malformed-header variants), cross-case purse 403, cardholder-creates-program 403; difficulty: retailer-suspended gate ×2 (authorization + item-file upload) |

**Queue translation**: Queue A (Difficulty): 19/19 instances, 38 tests (≥2 each). Queue B (Corner): 51/51 non-stub instances, 51 tests. The 3 `excluded_because` stubs (`expungement_notice_and_sweep_timing`, `provisional_credit_cap_and_target_purse`, `purse_spendable_excludes_scheduled_credit`) were not translated; their difficulty cross-references all resolve.

**Skips: none.** Every instance passed the PRD-first two-condition filter. Three adjudication notes (all judged uniquely derivable, tests kept): (1) missing-required-field and (2) enum-violation map to `ERR_INVALID_REQUEST` via PRD §2.8 step 19's "Field formats and request shape" (the only shape-error id in §5); (3) "exactly one batch" in the settlement-day test relies on batches being groupings of settled transactions (PRD §3.9), so empty days create no batch.

**Additive test_helpers edits: none** — the frozen API covered every recipe (`setup_pos_ready`/`setup_settled_batch`/`setup_purchase_and_claim`/`file_claim_on` composites, `make_*_headers` threading, `assert_purse_balances`/`assert_batch_position`/`assert_ledger_entry_types`, `instants_equal`).

**Self-verification results**:
- (a) `python3 -m py_compile test_suite/*.py` → all 12 files OK.
- (b) `python3 -m pytest test_suite --collect-only -q` → **89 tests collected**, no import/collection errors.
- (c) AST tag audit (scripted): 89/89 tests carry exactly one `Design:` tag; 0 invalid tags; 0 stub-pointing tags; 19/19 difficulty instances at ≥2 tests; 51/51 corner instances at ≥1; 70/70 non-stub instances translated; 3/3 stub cross-references resolve → **PASS**.
- Extra citation audit (scripted): all **136** quoted docstring spans ≥4 words survive whitespace-normalized verbatim match against `workspace/PRD.md` (0 misses).
- Hygiene greps: no `skip`/`skipif`/`xfail`, no scaffold references in test code, no wall-clock usage (all time via `fx.set_clock` / recipe timelines forward from `2026-09-01T00:00:00Z`).

Orchestrator spot-check (post-hand-back): 12 files, 2542 lines, `pytest --collect-only` collects exactly 89 tests with no errors, 89 `Design:` tags, 0 skip/xfail markers.

## Step 6: Generate implementation — 2026-10-02T08:48:00.000Z

Done. Final state is verified. Here is the completion report.

### File tree (all under `workspace/implementation/`, 2820 LOC total)

| File | Lines | Contents |
|---|---|---|
| `state.py` | 46 | In-memory stores (14 empty dicts), logical clock starting exactly `2026-09-01T00:00:00Z`, id/seq minting |
| `errors.py` | 96 | All 40 PRD §5 error_ids with exact HTTP statuses + `ApiError` |
| `util.py` | 210 | Envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; pagination fields in `meta`), auth (`X-User-Role`/`X-User-ID`, 4 roles), ownership guards, field/pagination validation |
| `domain.py` | 467 | Entity factories, append-only ledger posting (updates `last_activity_at`, clears notice), FIFO consumption (created_at tie-break), all 14 serializers |
| `sweep.py` | 335 | 7-step clock sweep in pinned order, per-boundary application on multi-day jumps, per-contract cutoff cursors, settlement batches (round-per-transaction-then-sum fees), daily files, monthly integrity reports |
| `contracts.py` | 355 | Contracts (18 config defaults + constraints), programs (FOOD/CASH uniqueness, DISASTER closed-window touch-or-overlap), allotment runs (bucket schedule, first-month proration round-half-up-once, duplicate-run rejection) |
| `retailers.py` | 167 | Retailer onboarding/status, atomic item-file upload (half-open overlap, adjacency allowed), items |
| `cases.py` | 222 | Cases, the single OCC rule (`expected_case_account_version` → ERR_STALE_VERSION 412), close cascade (purses/forfeits/cards), purses/ledger/postings reads |
| `cards.py` | 174 | Issuance, activation, replacement-fee waterfall (free allowance → CASH→FOOD with frozen-skip → waiver; DISASTER never absorbs), PIN reset |
| `authz.py` | 268 | Split-tender purchase (no-spill, STRICT/LENIENT with exception flags), cash withdrawal (multiple, daily-limit strictly-greater), PIN gate with lockout, void with exact VOID_CREDIT restoration |
| `claims.py` | 218 | Filing with freeze, SOD on investigation, provisional/final credit resolution (CLAIM_CREDIT/REVERSAL deltas), multi-claim freeze tracking, retailer auto-suspension cascade |
| `settlement.py` | 178 | Batches, reconcile (open-dispute gate before amount comparison, mismatch → DISPUTED + auto RECONCILIATION_MISMATCH dispute), retailer disputes (window inclusive), UPHELD adjustments recompute net |
| `app.py` | 73 | Flask wiring; `POST /_clock/set_current_utc` mounted at root OUTSIDE `/ebt`; error handlers envelope 404/405/400/500 |
| `start.sh` / `requirements.txt` | 11 | Guarded pip install, `exec python3 app.py`, `PORT` env (default 10000), `0.0.0.0` |

### Smoke tests (self-run, no pytest)
Three custom suites against fresh `bash start.sh` boots on free ports: **53/53**, **38/38**, **26/26** passed (117 checks). Covered: mount sanity (`/_ebt/*` and `/ebt/_clock/*` → 404; clock unprefixed → 200), auth/role/existence ordering, contract/program/case/retailer/card lifecycles, proration math, availability timing, PIN lockout + reset, split-tender, withdrawal multiple/limit boundary equality, void same-day, batch cutoff + fee `round(1000*75/10000)=8`, reconcile mismatch/uphold/re-reconcile, OCC 412, claim freeze/SOD/provisional/reversal, disaster expiry zeroing, expungement notice + dormancy cascade + card deactivation, dormant-case close, contract-close obligations, pagination meta. Two real bugs were caught and fixed this way: a missing cursor advance in `step6_settlement` (infinite loop) and `food_charge_cents` semantics (now FOOD+DISASTER combined with disaster as subdivision, per the entity table). Servers were killed by exact saved PID only.

### Verification
- `python3 -m py_compile` on all 13 .py files: OK (ran twice, after all fixes).
- Zero seeding: grep confirms no seed/preload/SQLite/file persistence; stores are module-level empty dicts; every entity is API-created. Fresh-process boot re-verified 6 times.

### PRD ambiguities resolved by choice (for Step 8)
1. **PIN vs frozen-purse order**: §3.7 narrates PIN-then-frozen, but §2.8's numbered pipeline (13 frozen, 18 PIN) says earliest wins — implemented **frozen (13) before PIN (18)**, so a FROZEN charged purse yields ERR_PURSE_FROZEN without incrementing `pin_fail_count`, and beats ERR_PIN_LOCKED too.
2. **`current_utc` format**: normalized to 3-fractional-digit ISO 8601 (`§2.6` pins that for all timestamps) rather than echoing `to_iso8601` verbatim.
3. **Multi-day jumps**: full 7-step pipeline at every crossed per-contract cutoff boundary plus the target instant ("behaves exactly as the corresponding sequence of single-day advances"); sweep-stamped timestamps (`mailed_at`, `resolved_at`, notice, `provisional_credited_at`) therefore carry the boundary instant.
4. **Data delivery emission**: daily file per contract per crossed cutoff boundary and monthly report per contract per crossed month boundary **even with zero activity / any contract status** (literal "emits each contract's daily transaction file"; no status condition stated).
5. **DISASTER window adjacency**: "even adjacency conflicts" implemented as closed-date intervals conflicting iff `start2 <= end1 + 1 day and start1 <= end2 + 1 day`.
6. **No FOOD program**: unknown UPCs fall to the cash bucket (restriction mode is "consulted only for FOOD programs" — no program, no rejection).
7. **Cross-contract card use**: no same-contract check (PRD states none); the retailer's contract drives the ACTIVE gate and item mode; the case's purses are charged.
8. **Claim target purse**: cash iff `cash_sum >= food_sum`; fallback to the other purse type if the chosen one is absent (spec asserts it always exists).
9. **Pagination bounds**: limit outside 1..100 / negative offset / non-integer → ERR_INVALID_REQUEST (PRD states min/max, no error id).
10. **CONFIGURING→ACTIVE with zero programs** → ERR_INVALID_STATE (scaffold lists the precondition with no pinned error).
11. **Free-allowance count** excludes the new card being created (else the first replacement could never be free).
12. **Zero-amount entries never posted** (`amount_cents > 0`): fee 0 absorbs silently, provisional 0 still flips credit_status to PROVISIONAL, zero-balance expungement flips postings without an EXPUNGE_DEBIT.
13. **`actual_settled_cents`** recorded on every reconcile attempt, matched or not.
14. **`pin_secret`** serialized as `"****"` when set, `null` when never set.
15. **Claim window boundary inclusive** (txn exactly `claim_window_days` old remains claimable).
16. **Body-shape checks** are evaluated where the gate chain needs the parsed values rather than strictly at step 19 (only diverges for malformed bodies combined with higher-priority gate failures).

Orchestrator spot-check (post-hand-back): all 13 .py files + start.sh + requirements.txt exist (2820 LOC); `py_compile` clean; route map shows exactly 39 `/ebt`-prefixed business routes + unprefixed `/_clock/set_current_utc` + Flask's built-in `/static` (benign); no bad mounts; start.sh is foreground `exec python3 app.py` with guarded pip install. NOTE: Steps 5 and 6 ran sequentially per command-args override (not concurrently), so physical isolation was absent; the ISOLATION RULE was included verbatim in the Step 6 prompt instead.

## Step 7: Test-fix iteration loop — 2026-10-02T10:22:00.000Z

Clean exit. All 8 rounds pass 89/89, deliverables preserved.

**Iterations run:** 2 (sweep 1: 80/89 ×8 rounds, deterministic; sweep 2 after fixes: 89/89 × 8 rounds, zero flakiness).

**Tests deleted:** none. (One test was *split* per STEP 1c — partial coverage — but no test function was removed; total stays 89.)

**Fixes applied to `implementation/`:**
- `workspace/implementation/state.py` — `new_id()` returned `uuid.uuid4().hex` (dashless); PRD §2.5 pins "id, a server-minted UUID with no type prefix" and the runner's `is_valid_uuid` requires canonical dashed form. Changed to `str(uuid.uuid4())`. Fixed 6 failures (`test_program_config_defaults_inherited_from_contract`, `test_first_month_proration_literal`, `test_scheduled_posting_counts_in_ledger_but_not_spendable`, `test_ledger_entries_are_append_only_without_version`, `test_acquirer_fee_round_per_txn_then_sum`, `test_reconcile_mismatch_creates_dispute_and_disputes_batch`, plus `test_monthly_integrity_report_counts_lenient_exceptions`). Verified `pan_token` ("pan_" + new_id) is only asserted as a non-empty string, so the format change is safe.

**Fixes applied to `test_suite/`:**
- `test_01_contract_program_case_setup.py::test_disaster_window_adjacency_conflicts_closed_interval` — STEP 1b/1c split. PRD §3.1's "closed windows may not touch or overlap … unlike item windows, even adjacency conflicts" admits two faithful readings of "touch": shared-boundary-date (R1) and contiguous-no-gap day-after (R2, which the implementation chose: conflict iff `start2 <= end1 + 1day`). The start==end → `ERR_DISASTER_WINDOW_OVERLAP` assertion is uniquely derivable under both readings and was kept; the day-after-start → 201 assertion depends on R1 alone and was removed, with an explanatory comment left in the test.
- `test_08_settlement_disputes_delivery.py::test_daily_transaction_file_generated_at_cutoff` — STEP 2 test bug. PRD §3.10 emits each contract's daily file at *every* crossed cutoff boundary with no activity condition, and §2.4 pins multi-day jumps as sequences of single-day advances; the fixture's card-activation jump (09-01T00:00 → 09-02T12:00) legitimately crosses the 09-02T00:00 boundary, emitting a zero-transaction file for period 09-01. Replaced the `len(deliveries) == 1` assertion with period-keyed selection of the 2026-09-02 file; all pinned content assertions (txn_count 2, 500/300 sums, DELIVERED) retained verbatim.

**Fixes applied to `test_helpers/`:** none.

**Sibling unasserted paths noticed (for PRD-completion):**
- The day-after disaster-window configuration (start = end + 1 day) is now unasserted in both directions; the implementation currently rejects it. If PRD-completion wants the R1 reading, both impl and a new test are needed.
- Delivery `created_at` stamps: the impl runs `run_sweep(old, new)` *before* `clock_set(target)` (`app.py:42-43`), so sweep-created entities (deliveries, batches) carry the *pre-advance* clock as `created_at` rather than the boundary/target instant the worklog's ambiguity note #3 claimed ("sweep-stamped timestamps carry the boundary instant"). No test asserts delivery `created_at`; PRD §2.5 only requires the field to record "creation", so this is conformant but diverges from the documented intent.
- Zero-activity daily files and zero-activity monthly reports are emitted unconditionally (impl choice #4); only the non-empty branches are asserted.

**Process hygiene:** one manual repro server was started on port 27811 by saved PID and killed by that exact PID; verified dead. Final passing `results.1.json`…`results.8.json` remain in `workspace/implementation/` untouched.

Orchestrator spot-check (post-hand-back): all 8 `results.{1..8}.json` exist and each shows `passed=89 total=89 failed=0`; `pytest --collect-only` still collects 89 tests (consistent with "split, no removal"); newest source-file mtimes (test_01/test_08 .py at sweep time) predate `results.1.json` — no post-sweep source writes, so the clean sweep is current.

## Step 8: Finalize PRD — 2026-10-02T10:35:00.000Z

All four edits verified in place. The diff is minimal and each edit traces to a step_7_diff item.

**Line counts / delta:** PRD.md 398 lines → PRD_FINALIZED.md 400 lines; +2.5% by characters. Four inline edits, no new sections.

**Changes (one bullet each):**
- §2.5 — revise — pinned resource `id` to the canonical hyphenated 8-4-4-4-12 UUID string form with example (`550e8400-…`); Step 7 changed `new_id()` from `uuid4().hex` (dashless) to `str(uuid4())` — `implementation/state.py:41-42`.
- §2.4 — insert — new paragraph after the multi-day-jump rule pinning sweep timestamp semantics: the sweep runs while the clock still reads its pre-advance value, so sweep-created resources (settlement batches, data deliveries) record the pre-advance clock as `created_at` (and sweep-mutated resources as `updated_at`), while sweep-stamped instant fields (`resolved_at`, `mailed_at`, `provisional_credited_at`, `expungement_notice_sent_at`, `cutoff_at`, and sweep-posted ledger entries' `created_at` → `last_activity_at`) record the crossed-boundary or target instant — `implementation/app.py:42-43`, `domain.py:18-53`, `sweep.py:64,93,119,125,163,185,214`.
- §3.1 — revise — pinned the R2 reading of disaster-window "touch": conflict iff `win_start <= existing_end + 1 day` AND `existing_start <= win_end + 1 day`, equivalently two windows of a contract must leave at least one full calendar day between them (day-after-adjacent is rejected) — `implementation/contracts.py:223-228`.
- §3.10 — revise — two clauses pinning unconditional delivery emission: daily transaction file for every contract at every crossed cutoff boundary even with zero settled transactions (`txn_count` 0, sums 0), and monthly integrity report for every contract at every crossed month boundary even with no relevant activity — `implementation/sweep.py:229-245,253-260,264-301,304-311`.

**Per-edit pre-edit search log:**

Edit A (§2.5 UUID):
- (a) Subject: format of the server-minted resource `id` field.
- (b) Enumerated: `state.py:41-42` `new_id()` (sole mint), `domain.py:21` (entity ids), `domain.py:38` (ledger-entry ids), `cards.py:22-23` `pan_token` = `"pan_" + new_id()` (a token, not an `id`; PRD §3.6 leaves its format unpinned), `util.py:64` `api_request_id` = `"req_" + uuid4().hex[:24]` (request id, separately pinned in §2.2), runner `testing/assertions.py:19-30` `_UUID_RE` requiring dashed 8-4-4-4-12.
- (c) Wording scoped strictly to the §2.5 resource-`id` sentence; no claim made about `pan_token` or `api_request_id`.

Edit D (§2.4 sweep timestamps):
- (a) Subject: timestamps recorded during a clock set's sweep.
- (b) Enumerated: `app.py:42-43` (sweep before `clock_set`); `domain.py:18-31` (`new_entity`/`touch` read `clock_now()` → pre-advance during sweeps); `domain.py:35-53` (`post_entry(at=instant)` → entry `created_at` = boundary/target instant, sets `last_activity_at`); `sweep.py` steps 1-5 stamp `resolved_at`/`mailed_at`/`provisional_credited_at`/`expungement_notice_sent_at` = instant; step 6 `cutoff_at` = boundary but batch/delivery `created_at` = pre-advance via `new_entity`. Non-sweep stamps (`claims.py:202` `_suspended_at`, `cards.py:80` `activated_at`, `cases.py:140,146` closure `resolved_at`, settlement reconcile/dispute stamps) are request-time and correctly outside the edit's "a sweep step stamps" scope.
- (c) Split the claim into two clauses (pre-advance `created_at`/`updated_at` vs. instant-valued stamped fields) because the impl genuinely diverges between the two; stamped fields enumerated exhaustively instead of a universal claim.

Edit B (§3.1 disaster windows):
- (a) Subject: window-vs-window conflict ("touch"/adjacency) semantics.
- (b) Enumerated: `contracts.py:223-228` (the conflict check — the Step 7 site); `contracts.py:294` (allotment-run inside-window check, closed interval — unaffected); `contracts.py:200-215` (required/forbidden + end≥start validation — unaffected); `domain.py:243-244` (serialization only); `sweep.py:78-97` uses `disaster_expiry_days`, not the window.
- (c) Kept "even adjacency conflicts" and added the exact two-sided AND plus the "one full calendar day belonging to neither" gloss; verified the gloss is logically equivalent to the impl condition for all window orderings (before/after/overlapping).

Edit C (§3.10 unconditional emission):
- (a) Subject: activity-conditionality of the two delivery types.
- (b) Enumerated: `sweep.py:253-260` (step 6 loops all contracts, one file per crossed boundary); `sweep.py:191-245` (delivery created with no `if txns` guard; `txn_count`/`settled_*` computed over possibly-empty lists → 0; batches only per non-empty acquirer group); `sweep.py:264-301,304-311` (monthly report unconditional per contract per crossed month); `contracts.py:157-165` (delivery listing, type filter only); contract creation-time cursors `contracts.py:83-85` mean "every crossed boundary/month" is always post-creation.
- (c) Daily-file clause pins exact zero figures (impl-guaranteed); monthly-report clause deliberately avoids "all figures zero" because `provisional_credits_outstanding_cents` is a point-in-time sum that can carry over — used "even when the month had no relevant activity" instead.

**Items needing no edit (verbatim PRD already pins behavior):** the `test_daily_transaction_file_generated_at_cutoff` fixture bug itself required no behavioral edit beyond Edit C's explicit no-activity-condition clause — emission per crossed boundary was already pinned by §3.10 ("emits each contract's daily transaction file") combined with §2.4's multi-day single-day-equivalence rule; Step 7's own analysis classified it as a pure test bug.

Orchestrator spot-check (post-hand-back): PRD_FINALIZED.md exists (68238 bytes vs PRD.md 66568), `diff -q` confirms they differ, and `diff` shows exactly 8 changed lines forming the 4 claimed hunks at §2.4 (sweep timestamp paragraph), §2.5 (UUID form), §3.1 (R2 adjacency wording), §3.10 (unconditional emission clauses). No wholesale rewrite.

## Step 9: Complete PRD — 2026-10-02T11:02:00.000Z

All 26 edits landed in 23 diff hunks (three pairs of edits share paragraphs). Line count unchanged at 400 (all edits are in-paragraph); char delta +6,403. Here is the final report.

**Source**: `PRD_FINALIZED.md` (400 lines, 68,238 chars) → `PRD_COMPLETED.md` (400 lines, 74,641 chars; **+6,403 chars, +0 lines**). All edits are in-paragraph inserts/revisions; no sections added.

**Counts**: 25 ambiguity-pins, 1 mismatch-revision (tagged (b)).

### Changes (one bullet each)

- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — implementation/util.py:176-194
- §2.4 — insert — ambiguity — `to_iso8601` accepts any ISO offset, naive read as UTC, normalized to UTC; missing/unparseable → `ERR_INVALID_REQUEST`; equal-to-current accepted and still sweeps once — implementation/app.py:31-44, util.py:30-45
- §2.4 — revise — ambiguity — sweep runs at the union of every contract's daily cutoff boundaries plus the target instant (all 7 steps at each); per-contract day/month tracking from creation, so nothing is emitted for pre-contract periods — implementation/sweep.py:315-335, contracts.py:84-85
- §2.5 — insert — ambiguity — zero computed ledger amounts post no entry (zero fee, zero delta, zero provisional, zero unspent, zero expunge balance) while all other effects still apply — implementation/cards.py:131-133, claims.py:176-181, sweep.py:95-97,128-130,181-183
- §2.8 — insert — ambiguity — envelope rules outside the pipeline: unknown path/method → `ERR_NOT_FOUND`; malformed/non-object JSON → `ERR_INVALID_REQUEST`; out-of-vocabulary `to` → `ERR_INVALID_REQUEST` evaluated before transition legality — implementation/app.py:52-64, contracts.py:102-103, cases.py:98-99, retailers.py:65-66, claims.py:134-135, settlement.py:162-163
- §2.11 — insert — ambiguity — non-integer/out-of-constraint config values (contract or program override) → `ERR_INVALID_REQUEST`; overrides share contract-level constraints — implementation/contracts.py:26-45,74-80,185-199
- §3.1 — insert — ambiguity — CONFIGURING→ACTIVE with zero programs → `ERR_INVALID_STATE` — implementation/contracts.py:112-115
- §3.1 — insert — ambiguity — program creation in other contract states → `ERR_CONTRACT_NOT_ACTIVE`; field violations (unknown type/mode, window rules, override bounds) → `ERR_INVALID_REQUEST` — implementation/contracts.py:177-215
- §3.2 — insert — ambiguity — item-window overlap also checked pairwise within the uploaded file; `effective_to` ≤ `effective_from` → `ERR_INVALID_REQUEST`; upload returns 201 with `created_count` — implementation/retailers.py:112-142,155
- §3.4 — insert — ambiguity — `program_id` of another contract → `ERR_REFERENCE_NOT_FOUND`; malformed `benefit_month` → `ERR_INVALID_REQUEST` (well-formed but wrong month/window stays `ERR_POSTING_MONTH_INVALID`); non-positive `amount_cents` → `ERR_INVALID_REQUEST` — implementation/contracts.py:273-299
- §3.6 — insert — ambiguity — `pin_secret` renders `****` once set, null before first PIN — implementation/domain.py:346
- §3.6 — insert — ambiguity — failed `current_pin` on PIN reset increments `pin_fail_count` and can lock an ACTIVE card — implementation/cards.py:154-158,167-174
- §3.6 — insert — ambiguity — free allowance counted before the successor exists (successor never counts itself); 365-day window inclusive at exactly 365 days — implementation/cards.py:97-116, domain.py:148-153
- §3.7 — revise — **mismatch (b)**: 3.7's prose ("Then the PIN gate runs… Only then… any purse to be debited must not be FROZEN") contradicted §2.8's numbered pipeline (frozen=13 before PIN=18); impl follows §2.8, so 3.7 now pins frozen-before-PIN, incl. `ERR_PURSE_FROZEN` beating `ERR_PIN_LOCKED`, and absent/non-string `pin` → `ERR_INVALID_REQUEST` at the PIN gate. Surviving passage: §2.8 — implementation/authz.py:133-157
- §3.7 — insert — ambiguity — request-shape checks (authorization_type, presence rules, line-item types, positive withdrawal amount) evaluated after card-active gate, before frozen/PIN gates; `ERR_WITHDRAWAL_MULTIPLE` fires after PIN — implementation/authz.py:54-110,159-164
- §3.7 — insert — ambiguity — cross-contract card use allowed: retailer's contract supplies contract-active gate, config values, and restriction mode; case-open gate and debited purses are the card's case's — implementation/authz.py:44-49,73-76,151,161,196
- §3.7 — insert — ambiguity — no-FOOD-program contracts: unknown UPC sums into cash total with no exception flag — implementation/authz.py:73-98
- §3.7 — insert — ambiguity — STRICT rejection fires at step 23 (after frozen/PIN), failing line provisionally bucketed as food for the charge plan — implementation/authz.py:90-93,167-170
- §3.7 — insert — ambiguity — fiscal rejection order pinned: purchase = eligibility → food-funds → `ERR_NO_CASH_PURSE` → cash-funds; withdrawal = `ERR_NO_CASH_PURSE` → `ERR_DAILY_LIMIT_EXCEEDED` → `ERR_INSUFFICIENT_FUNDS` — implementation/authz.py:167-200
- §3.8 — insert — ambiguity — claim window boundary inclusive (exactly `claim_window_days` old is still fileable) — implementation/claims.py:70-73
- §3.8 — insert — ambiguity — claim target purse: CLOSED purses eligible; missing selected type falls back to the other type; neither type → no entry, fields still update — implementation/domain.py:185-198
- §3.8 — insert — ambiguity — multi-claim freeze: purse reopens only when every claim that froze it is terminal — implementation/claims.py:113-125
- §3.9 — insert — ambiguity — a transaction's settlement day is the one containing its `created_at` — implementation/sweep.py:194-200
- §3.9 — revise — ambiguity — `settlement_date` = UTC calendar date of the settlement day's start instant — implementation/sweep.py:213-214
- §3.9 — insert — ambiguity — `actual_settled_cents` (null initially) recorded on every reconcile attempt, matched or not — implementation/settlement.py:78
- §3.10 — insert — ambiguity — daily-file `period` is `YYYY-MM-DD`; monthly `period` is `YYYY-MM`, figures computed from state at the emitting step-7 instant — implementation/sweep.py:233,264-301

### IMPL-SIDE FIX CANDIDATES (class c)

**None.** Every divergence found was either PRD silence (ambiguity) or the §3.7-vs-§2.8 self-contradiction resolved as (b). No clear, consistent, implementable PRD claim was found that the impl omits or contradicts.

### Checklist verdicts

1. PIN-vs-frozen ordering — **pinned by this edit** (§3.7 revised to §2.8/impl order; (b)).
2. `current_utc` normalization — pinned by this edit (§2.4).
3. Multi-day jump per-boundary semantics — pinned by this edit (union of per-contract cutoffs + target).
4. DISASTER window adjacency — pinned already (§3.1 matches contracts.py:223-228).
5. No-FOOD-program unknown-UPC — pinned by this edit (cash bucket).
6. Cross-contract card use — pinned by this edit (allowed; retailer's contract governs).
7. Claim target-purse selection — cash-iff rule pinned already; fallback pinned by this edit.
8. Pagination bound errors — pinned by this edit (§2.3).
9. CONFIGURING→ACTIVE with zero programs — pinned by this edit (`ERR_INVALID_STATE`).
10. Free-replacement allowance counting — pinned by this edit (pre-creation count, inclusive window).
11. Zero-amount ledger entries — pinned by this edit (§2.5 global rule).
12. `actual_settled_cents` recording — pinned by this edit.
13. `pin_secret` masking — pinned by this edit (null until set).
14. Claim-window boundary inclusivity — pinned by this edit (inclusive).
15. Body-shape check evaluation point — pinned by this edit (after card-active, before frozen/PIN).
16. Replacement-fee waterfall order — pinned already (§3.6 matches cards.py:116-141 incl. frozen-skip, DISASTER exclusion; zero-fee now covered by the §2.5 rule).
17. Round-per-transaction-then-sum acquirer fees — pinned already (§3.9 matches sweep.py:208,248-250).
18. FIFO created_at tie-break — pinned already (§3.5 "never by id" matches domain.py:87-100).
19. Split-tender no-spill ordering — pinned already (§3.7 matches authz.py:121-131,211-228).
20. Proration round-half-up-once — pinned already (§3.4 matches contracts.py:329-334).
21. 7-step sweep order — pinned already (§2.4 matches sweep.py:328-335).
22. Unconditional delivery emission — pinned already (§3.10 matches sweep.py:228-245,304-311).

Orchestrator spot-check (post-hand-back): PRD_COMPLETED.md exists (74,641 chars — matches report), differs from PRD_FINALIZED.md, line count unchanged at 400 as claimed, `diff` shows exactly 23 added hunks (matches "23 diff hunks"); §3.7 frozen-before-PIN revision present in the file. Zero `.py` files in implementation/, test_suite/, test_helpers/ are newer than `results.1.json` — Steps 8/9 made no source writes, so the clean 8-round sweep (89/89 ×8) remains valid; all 8 results files still present and each still reports 89/89.
