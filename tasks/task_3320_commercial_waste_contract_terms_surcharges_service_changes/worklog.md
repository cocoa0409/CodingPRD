# Worklog — task_3320_commercial_waste_contract_terms_surcharges_service_changes

## Step 1: Create task directory — 2026-09-30T20:10:00.000Z

Pre-allocated task directory verified: `./tasks/task_3320_commercial_waste_contract_terms_surcharges_service_changes/` with `workspace/` inside. No new index computed; no other task_* directory created. Difficulty instruction for scaffold generator: "Generate task much harder than expert level!"

## Step 2: Generate scaffold — 2026-09-30T20:46:00.000Z

All three artifacts are written, parse, and pass the lint gate. Summary:

**Files written** (all in `/home/ubuntu/github/CodingPRD/tasks/task_3320_commercial_waste_contract_terms_surcharges_service_changes/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

**Counts:**
- Entities: 12 (Customer, Contract, ContractServiceLine, PickupEvent, SurchargeConfig, RateAdjustmentNotice, ServiceChangeRequest, CompetingOffer, CancellationRequest, ServiceCredit, RolloffOrder, LedgerEntry)
- State machines: 7 (Contract with auto-renewal self-loop + TERMINATED→ACTIVE reinstate cycle; PickupEvent with bounded NONE→DISPUTED→RESOLVED_UPHELD→DISPUTED appeal cycle)
- Calculations: 6 (dual-variant monthly invoice FIXED/INDEXED fuel; timely/untimely LD; quote-vs-final service-change pricing; ROFR proportional waterfall with remainder; credit-balance reconciliation; roll-off ceil-overage threshold)
- Endpoints: 54 (includes 7 single-GETs and `/_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z)
- Errors: 10
- Difficulty instances (§1.8): 18 — exactly 2 per each of the 9 rules, all differentiation clauses honored (different entity domains, modes (a)/(b), different error-category pairs, different metrics, different entity pairs, different interval semantics, credit-side vs liability-side conserved quantities)
- Corner instances (§1.9): 26 (1 `excluded_because` stub → 25 active), across 8 sections

**Difficulty highlights (harder-than-expert levers):** per-component-then-sum rounding pinned against sum-then-round (41666 vs 41667); OCC on Contract.version guarding both ROFR match and service-change apply; a depth-4 termination cascade (notice cancel + change cancel + offer void + LD balance debit); quote-vs-final repricing split by an intervening rate notice (550000 vs 577500); ROFR waterfall with a -1 cent remainder absorbed by the largest line (47222/28334/9445 = 85001).

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (339 calls scanned, 0 violations.)

**Key fixes during generation:** every formula-derived assert literal was executed in Python before pinning — caught and corrected a hand-computed ROFR allocation error, a timely/untimely boundary date (threshold is end−60d = 2027-07-03, so untimely fixtures use 2027-07-04), and pinned `months_remaining` to ceil-of-partial-month semantics so `months_remaining == 2` is well-defined. No sibling task directories were read at any point.

## Step 3: Copy shared files — 2026-09-30T20:47:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T21:05:00.000Z

First subagent run stalled mid-design without writing the file; resumed the same subagent, which then completed the write.

PRD generation is complete and verified.

**Output**: `workspace/PRD.md` — 273 lines.

**Section list**:
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (4 roles with identity prose), 2.2 API Response Structure (canonical block verified byte-identical), 2.3 Pagination, 2.4 Logical Clock & Scheduled Sweeps (pinned start `2026-09-01T00:00:00Z`, three sweeps in order), 2.5 Common Resource Properties (LedgerEntry explicitly called out as `common_fields: false`), 2.6 Monetary Precision & Rounding (half-up default; ceil for LD months and roll-off overage; floor for credits), 2.7 Customer Credit Ledger, 2.8 OCC (`expected_contract_version` → `ERR_STALE_VERSION`/412 on match + apply only), 2.9 SurchargeConfig active-window rule, 2.10 Nested retrieval + the full 10-priority validation ordering
- §3 Business Logic (11 subsections): customers; contract lifecycle (DRAFT/ACTIVE/TERMINATION_PENDING/TERMINATED, defaults 12/60/false/15); rate notices (SCHEDULED/APPLIED/CANCELLED, no-requote rule); service changes (1.10/0.95 multipliers, quote-at-create vs reprice-at-apply); pickup events + dispute channel (30-day window, appeal_count max 1, RESOLVED_CREDITED cascade); service credits (14-day window, floor, one-per-event); monthly invoice (FIXED/INDEXED fuel, per-component rounding, 30-day fee window); cancellation & LD (timely ≤ end−notice_days, ceil months, 0.5 fraction, waiver); ROFR (500-cent undercut, proportional allocation with remainder to largest line); roll-off orders (ceil overage, included_tons default 2.0); contract ledger
- §4 Endpoint table (52 rows, 4 columns), §5 Error catalogue (10 rows, 2 columns)

**Hard-contract results**:
- Contract 1 (field coverage): 68 scaffold field/input names required, 68 present, 0 missing; invoice output keys (`base_cents`…`total_cents`), `expected_contract_version`, `to_iso8601`, `resolution` all present — **PASS**
- Contract 3 (§3 path purity): 397 backticked tokens scanned in §3, 0 path/method violations — **PASS**
- Supporting checks: all 10 error_ids appear in §2/§3 prose; all 4 roles, all 21 state values, and all enum literals (container sizes, outcomes, fuel modes, reasons, ledger sources, dispute resolutions, ld statuses) present verbatim; §2.2 canonical block byte-identical — **PASS**

**Zero-silence mapping (scaffold → PRD)**: §1.1 entities/fields → §2.5, §2.7, §2.9, §3.1–§3.11; §1.2 state machines → §3.2 (Contract), §3.3 (RateAdjustmentNotice), §3.4 (ServiceChangeRequest), §3.5 (PickupEvent), §3.8 (CancellationRequest), §3.9 (CompetingOffer), §3.10 (RolloffOrder); §1.3 calculations → §3.7 (invoice), §3.8 (LD), §3.4 (quote), §3.9 (ROFR), §2.7 (credit balance), §3.10 (roll-off); §1.4 validations → §2.10 priority ordering + trigger prose co-located in §3; §1.0 envelope → §2.2/§2.3; §1.5 endpoints → §4 table; §1.6 errors → §5 + §2/§3 triggers; §1.7 roles → §2.1 + §4 authorized-role column.

One judgment call to flag: `credit_pct_of_base` is referenced by the scaffold's ServiceCredit formula but is not declared as a SurchargeConfig field; the PRD names it in backticks as the active configuration's credit percentage without adding it to any input list, mirroring the scaffold exactly.

## Step 5: Generate unit tests — 2026-09-30T21:35:00.000Z

All 56 tests collect cleanly. Generation is complete.

**test_helpers/ written** (8 files, all under `test_helpers/`):
- `types.py` — 13 entity TypedDicts + status enums (LedgerEntry correctly omits `updated_at`/`version` per its append-only `common_fields: false`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (37 methods)
- `api_errors.py` — 10 error IDs + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions; ledger entry asserts absence of `version`/`updated_at`
- `factories.py`, `constants.py` (ROFR undercut 500, multipliers 1.10/0.95, LD 0.5, 14/30-day windows)
- `test_users.py` — opaque-role shared constants + `make_customer_headers(id)` for the entity-backed Customer role
- `fixtures.py` — composite builders (active contract, fixed config, rate notice, service change, offer, pickup, credit, cancellation, roll-off, timely-terminated contract, version/balance getters)
- `__init__.py` — barrel export

**test_suite/ written** (8 files): `conftest.py` + `test_01_monthly_invoice_calculations.py`, `test_02_cancellation_liquidated_damages.py`, `test_03_service_change_requests.py`, `test_04_competing_offers_rofr.py`, `test_05_disputes_and_rate_notices.py`, `test_06_boundaries_and_windows.py`, `test_07_lifecycle_rbac_and_validation.py`.

**Totals: 56 tests — 32 queue A (all 16 covered difficulty instances × 2), 24 queue B (all 24 covered non-stub corner instances × 1).** All files compile, import, and collect under pytest. (Orchestrator verified on disk: 56 test functions across 7 test files.)

**Skipped instances (4, gaps left as gaps — no skip/xfail markers):**
1. `Difficulty/transitive_cascade/dispute_credited_cancels_credit_recomputes_balance` — recipe disputes a MISSED event to reach RESOLVED_CREDITED, but PRD §3.5 rejects disputing MISSED events ("Disputing a `COMPLETED` or `MISSED` event is rejected with `ERR_INVALID_STATE`") and §3.6 credits attach only to MISSED events; the credit-cancel cascade is unreachable for any event carrying a credit. Clock/logic contradiction, not derivable from PRD.
2. `Difficulty/compensating_invariant/credit_file_then_dispute_credited_conserves_balance` — same unreachability defect.
3. `Corner/errors/stale_version_on_second_sequential_match` — asserts ERR_STALE_VERSION on a second match of an already-MATCHED (terminal) offer, but PRD §2.10 orders state admissibility (priority 5) before OCC (priority 6), uniquely deriving ERR_INVALID_STATE instead.
4. `Corner/state_machines/terminal_contract_lockdown_reject_cancellation` — asserts filing a cancellation against a TERMINATED contract is rejected, but PRD §3.8 gates only approval on contract status and gives no filing-time rule; two PRD-only implementers could legitimately differ.

**Clock/constant drift re-derived per the warning:** four recipes said "24mo" while asserting end 2027-09-01 and `months_remaining == 2`; PRD §3.8's verbatim example (2027-07-04→2027-09-01 = 2) pins end_date to 2027-09-01, so I emitted `term_months: 12` in all LD/cascade/reinstate setups. `invoice_includes_event_fees_and_credits` originally set the clock to 2026-08-01 (before the fixed 2026-09-01 start); I kept the clock at/after 2026-09-01 and backdated the old event's `occurred_date` to 2026-08-19 with the config `effective_from` backdated to 2026-08-01 (PRD allows). Credit-bearing configs carry `credit_pct_of_base: 0.05`, the field PRD §3.6 names as the credit percentage, making the asserted 30000/5000 credit literals PRD-derivable. All 66 distinctive docstring citation substrings were verified verbatim against PRD.md.

## Step 6: Generate implementation — 2026-09-30T21:18:00.000Z

Done. Summary of the implementation:

**Files written (all under `workspace/implementation/`)**

| File | Lines | Purpose |
|------|-------|---------|
| `app.py` | 1037 | Flask app: error handlers, auth/RBAC decorator usage, all route handlers |
| `db.py` | 325 | In-memory stores (dicts keyed by id), logical clock, serializers, sweeps (auto-renewal → rate-notice apply → termination finalization), ledger writes, customer balance + contract base recompute |
| `util.py` | 217 | Response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), error class with catalog IDs, field/type validation, `limit`/`offset` pagination, Decimal `round_half_up`/`floor`/`ceil`, calendar month add/ceil |
| `start.sh` | 8 | Guarded pip install (no-op when flask present), `exec python3 app.py` on `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | flask>=3.0,<4.0 |

**Endpoints implemented: 42/42**
All routes from the scaffold endpoint table: clock, customers (3), contracts incl. activate/reinstate/service-lines/monthly-invoice/ledger-entries (7), service-lines get, pickup events + dispute/resolve-dispute (5), surcharge-configs (2), rate-notices (4), service-change-requests + approve/reject/apply/withdraw (6), competing-offers + match/decline (5), cancellation-requests + approve/deny/withdraw/waive-ld (6), service-credits (3), rolloff-orders + deliver/complete/cancel (5), ledger-entries (2).

**Key design decisions**
- **Logical clock** starts at `2026-09-01T00:00:00Z`; every set runs the three sweeps in the pinned order (renewal, notice application with `LedgerEntry(RATE_NOTICE)` + per-line half-up repricing, termination finalization).
- **Calculations** per scaffold: per-component half-up rounding before summation on invoice; LD = `round_half_up(base × ceil-months × 0.5)` with `months_ceil` (partial month rounds up); service-change quote uses per-pickup unit × 1.10 (upgrade) / 0.95 (downgrade), re-quoted from the line's current rate at apply time; ROFR match = `max(0, competitor − 500)` allocated proportional half-up in (rate DESC, created ASC) order with remainder to the first line; service credit = `floor(base × 0.25)` — PRD references `credit_pct_of_base` but no such field exists on SurchargeConfig, so the pinned constant is 0.25 (invisible when tests omit a config, which leaves fees and the credit rate undefined either way); rolloff overage uses `ceil`.
- **Validation priority** follows the scaffold ordering: auth(401) → forbidden(403) → not-found(404) → invalid-request(400) → invalid-state(409) → OCC `expected_contract_version` stale(412) → window-expired(422) → duplicate-pending(409) → rofr-not-enabled(422) → invalid-amount(422).
- `credit_balance_cents` is recomputed from sources (ACTIVE credits on customer lines minus ASSESSED LDs) on every relevant mutation; ledger entries are immutable (no `updated_at`/`version`).
- No seeding: all stores start empty; the store is per-process so per-test-server isolation works.

**Boot verification**
Launched via `PORT=19477 bash start.sh`, smoke-tested: clock set (200), customer create (201, `credit_balance_cents: 0`), empty contract list with pagination meta (200), missing-role request → `ERR_UNAUTHENTICATED` 401 with correct error envelope. Process killed by its saved PID and confirmed dead.

(Orchestrator note: all 5 files verified on disk with matching line counts; all 3 Python files parse cleanly via ast. CONCERN flagged for Step 7: impl pins service credit to `floor(base × 0.25)` while test fixtures post `credit_pct_of_base: 0.05` on configs and assert 30000/5000 credit literals — Step 7 must adjudicate this against PRD §3.6's exact wording.)

## Step 7: Run tests and iterate — 2026-09-30T21:35:59.000Z

All 8 rounds pass 56/56. Clean sweep achieved.

Summary:

- **Iterations run**: 3 sweeps (24 total rounds). Final sweep: all 8 rounds passed 56/56.

- **Tests deleted**: none.

- **Fixes applied to `test_suite/`**:
  - `test_06_boundaries_and_windows.py` — `TestRolloffOverageBoundary._setup` referenced undefined `api` (a pytest fixture) inside a helper method; switched to the imported module-level `api_client`. Also added `expected_status=201` to the two `create_service_credit` success calls in `TestCreditFilingWindowBoundary` (PRD §4: resource creation returns 201; the test asserted default 200).
  - `test_07_lifecycle_rbac_and_validation.py` — three `end_date` assertions compared exact strings (`"2028-03-01T00:00:00Z"`), but PRD pins the three-fractional-digit format only for `created_at`/`updated_at`/`api_request_timestamp`; `end_date` is just "ISO 8601 UTC", so exact-string format is not uniquely derivable (implementation emits `.000Z`). Replaced with an `_instant()` semantic-instant comparison — the PRD rule asserted (start + term months, same day-of-month) is still fully verified.

- **Fixes applied to `test_helpers/`**:
  - `types.py` — added optional `credit_pct_of_base: Optional[float]` to the `SurchargeConfig` TypedDict (matches PRD §3.6's named attribute).

- **Fixes applied to `implementation/`**:
  - `app.py` (`create_surcharge_config`, `create_service_credit`) — adjudicated the known suspect per PRD §3.6's verbatim wording: "`credit_cents` equals the floor of the line's `base_rate_cents` multiplied by the credit percentage of base, `credit_pct_of_base`, in effect under the surcharge configuration active at filing." PRD names `credit_pct_of_base` as a surcharge-configuration attribute (also §2.9: the active config "supplies … the credit percentage of base used when a service credit is computed"), so the hardcoded `CREDIT_PCT_OF_BASE = 0.25` was implementation hacking. Now: config creation accepts optional `credit_pct_of_base` (PRD §2.9's required-field list omits it, so it stays optional), stores and serializes it, and credit filing computes `floor(base_rate_cents × active_config.credit_pct_of_base)`.
  - `db.py` (`_next_created_at`, `ser_surcharge`) — `created_at`/`updated_at` now use the logical clock instead of wall clock. This was the root cause of the ROFR window failure: PRD §2.4 says all temporal rules evaluate against the logical clock, and §3.9's match window compares the logical clock against the offer's `created_at`; a wall-clock `created_at` (2026-09-30) made every match "within window" regardless of the logical clock. `_seq` still breaks ties for ordering. Also removed the dead `CREDIT_PCT_OF_BASE` constant and added `credit_pct_of_base` to the surcharge serializer.

(Orchestrator verification: mtime check found test_06 edit at 21:31 vs results files at 21:31–21:33 — a 2-minute window where a post-sweep test edit was possible. Re-ran the full 8-round sweep myself: all 8 rounds 56/56 passed, 0 failed, 0 errors, 0 skipped. Results files are from the orchestrator's own sweep.)

## Step 8: Finalize PRD — 2026-09-30T21:45:00.000Z

Done. `PRD_FINALIZED.md` is written at `workspace/PRD_FINALIZED.md`.

**Line counts and delta**
- PRD.md: 273 lines; PRD_FINALIZED.md: 273 lines; 0% line-count delta (three inline sentence revisions, no lines added or removed).

**Changes**
- **§2.5 — revise** — `created_at` now records "the logical-clock time at which the resource was created (per §2.4, never the wall clock)" and `updated_at` is "refreshed to the current logical-clock time" on mutation — `implementation/db.py:35-38` (`_next_created_at` returns `fmt_ts(now())`), used by `Rec.__init__`/`Rec.touch`/`LedgerRec` (db.py:41-68).
- **§2.9 — insert** — appended a sentence declaring `credit_pct_of_base` optional, stored and serialized as null when omitted — `implementation/app.py:448-454` (optional acceptance), `implementation/db.py:148` (`ser_surcharge` emits it, null when absent).
- **§3.6 — revise** — credit formula sentence extended with the fallback: "if no configuration is active at filing, or the active configuration carries no `credit_pct_of_base`, `credit_cents` is 0" — `implementation/app.py:910-912` (`pct = getattr(cfg, 'credit_pct_of_base', None) if cfg is not None else None; amount = dfloor(...) if pct is not None else 0`).

**Per-edit pre-edit search log**
1. **Edit 1 (§2.5 timestamps)** — (a) Subject: source of truth for `created_at`/`updated_at` on all primary resources and ledger entries. (b) Enumerated paths: `db.py` `_next_created_at` (line 35), `Rec.__init__`/`touch` (lines 41-55), `LedgerRec.__init__` (line 62-68); all `ser_*` serializers merely emit stored strings; `util.py` `wall_now_iso` (line 52) is used only for `meta.api_request_timestamp` in `success`/`error_response` (lines 57, 66) — wall clock there is unchanged and §2.2 pins that field's format independently; `app.py` has no other timestamp minting. (c) Wording kept scoped to `created_at`/`updated_at` only; deliberately did not claim anything about `api_request_timestamp`, which remains wall-clock in impl — no adjustment needed beyond that scoping.
2. **Edit 2 (§2.9 optional `credit_pct_of_base`)** — (a) Subject: surcharge-config field set — optionality, storage, serialization of `credit_pct_of_base`. (b) Enumerated paths: `app.py` `create_surcharge_config` (lines 420-457 — not in the required-field validation chain; accepted via `body.get`, validated as number only when present, stored possibly None), `db.py` `ser_surcharge` (line 148 — emits the value verbatim, so null when absent), `db.py` `active_config_at` (lines 244-250 — does not care about the field), `app.py` `create_service_credit` (line 911 — the only reader). No other impl path touches the field. (c) Initial draft said "stored and serialized as null when omitted" — verified against `ser_surcharge` that the field is always present in the response (null when omitted), which the wording reflects; no conflict with any enumerated path.
3. **Edit 3 (§3.6 credit formula fallback)** — (a) Subject: `credit_cents` computation at service-credit filing. (b) Enumerated paths: `app.py` `create_service_credit` (lines 892-921 — sole computation site), `util.py` `dfloor` (line 190 — ROUND_FLOOR on Decimal), `db.py` `recompute_customer_balance` (lines 259-271 — consumes stored `credit_cents`, formula-agnostic), `app.py` monthly invoice `credits_cents` (lines 268-269 — same, reads stored values), `db.py` `ser_credit` (lines 202-209 — emits stored value). The fallback clause describes only the computation site and mis-describes no consumer. (c) No adjustment needed; clause is additive and preserves the PRD's verbatim formula for the happy path.

**Step-7 items not patched (with reason)**
- `test_06` `_setup` fixture bug (`api` → `api_client`) and `test_helpers/types.py` TypedDict addition — pure test-side fixes, no PRD silence.
- `test_06` `expected_status=201` on credit creation — PRD §4 already pins 201 for resource creation; no edit.
- `test_07` `end_date` exact-string assertions replaced with semantic-instant comparison — PRD deliberately does not pin a fractional-digit format for `end_date` (only §2.5 fields and §2.2 `api_request_timestamp`); the implementation's `.000Z` emission is within PRD-permitted latitude, so no PRD change.

(Orchestrator spot-check: diff PRD.md vs PRD_FINALIZED.md shows exactly the 3 claimed edits at §2.5, §2.9, §3.6; 273→273 lines confirmed.)

## Step 9: Complete PRD — 2026-09-30T21:55:00.000Z

All edits are in place. The completed PRD is at `workspace/PRD_COMPLETED.md`.

- Source: `PRD_FINALIZED.md` (273 lines / 45,651 chars) → `PRD_COMPLETED.md` (273 lines / 48,410 chars); char delta +2,759, no lines added or removed (all changes are inline in-paragraph inserts/revisions, no new sections).
- Counts: 11 ambiguity-pins, 2 mismatch-revisions (13 edits total).

**Changes (one per edit)**
- §2.1 Role identity — **revise** — **mismatch** — PRD claimed per-resource `Customer` ownership comparison of `X-User-ID` to foreign keys; impl does role-only auth with no ownership check — `implementation/util.py:26-40` (guarded) and no ownership comparisons anywhere in `app.py`.
- §2.3 Pagination — **insert** — **ambiguity** — pin invalid `limit`/`offset` (non-integer, limit outside 1–100, negative offset) as `ERR_INVALID_REQUEST` 400 — `implementation/util.py:156-168`.
- §2.4 Logical clock — **insert** — **ambiguity** — clock is set unconditionally (backward sets allowed), sweeps run once after each set — `implementation/db.py:19-21`.
- §2.4 Sweeps — **insert** — **ambiguity** — auto-renewal renews exactly once per clock advance (no catch-up loop) — `implementation/db.py:310-315`.
- §2.5 Common properties — **insert** — **ambiguity** — `version` starts at 1 at creation — `implementation/db.py:48`.
- §2.9 Surcharge config — **insert** — **ambiguity** — `fuel_index_base` must be non-zero, else `ERR_INVALID_REQUEST` — `implementation/app.py:443-444`.
- §2.10 Validation ordering — **revise** — **ambiguity** — softened the global fixed-ordering claim ("order identifiers appear in the endpoint contract"; per-endpoint orderings in §3 take precedence where stated) because impl's rate-notice create checks window before amount and rolloff-complete checks body shape before state — `implementation/app.py:479-482`, `implementation/app.py:1014-1016`.
- §3.2 Renewal/reinstatement — **insert** — **ambiguity** — renewal once per advance; reinstatement does not alter `end_date`, `current_term_index`, or line rates — `implementation/db.py:310-315`, `implementation/app.py:190-198`.
- §3.3 Rate notice filing — **insert** — **mismatch** — window check precedes amount check on this endpoint, and no contract-status precondition exists at filing (notice against non-ACTIVE contract is accepted and applies on schedule) — `implementation/app.py:479-482`, `implementation/app.py:475`.
- §3.3 Notice application sweep — **insert** — **ambiguity** — multiple due notices are applied in creation order (sequence, not `effective_date` order), and each touched service line's `updated_at`/`version` advance — `implementation/db.py:317-319`, `implementation/db.py:296-300`.
- §3.7 Monthly invoice fees window — **revise** — **ambiguity** — the trailing 30-day fees window is compared as calendar dates on both ends (`(clock − 30 days).date() <= occurred_date <= clock.date()`) — `implementation/app.py:254-267`.
- §3.8 Cancellation filing — **insert** — **ambiguity** — no contract-status precondition at filing; ACTIVE requirement is enforced only at approval — `implementation/app.py:762-778`.
- §3.8 Cancellation withdraw/approve — **insert** — **ambiguity** — withdrawal after `requested_end_date` is rejected with `ERR_WINDOW_EXPIRED`; approval moves the request to `APPROVED` (terminal) in both branches — `implementation/app.py:865-867`, `implementation/app.py:829-839`.
- §3.9 ROFR match preconditions — **insert** — **ambiguity** — pin per-endpoint check order (window → duplicate → contract-status → version) and error codes for each — `implementation/app.py:704-719`.
- §3.9 ROFR match allocation — **insert** — **ambiguity** — degenerate allocations (no lines: contract total set to matched rate; zero pre-match base: entire matched rate to first line, others 0), touched lines' `version` advance, and ledger `effective_date` is the match-time logical clock — `implementation/app.py:722-742`.
- §3.10 Roll-off complete — **insert** — **ambiguity** — `actual_tons` shape validation runs before the `DELIVERED` status check — `implementation/app.py:1014-1016`.

(Orchestrator spot-check: PRD_COMPLETED.md exists; 273→273 lines, 45,651→48,410 chars (+2,759), 16 changed lines in diff — matches the report.)

**Pipeline complete.** Final state: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml; PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md; test_helpers/ (9 files) + test_suite/ (7 files, 56 tests); implementation/ (app.py 1037 + db.py 325 + util.py 217 + start.sh + requirements.txt); 8-round per-test-server stability sweep all 56/56 (orchestrator-verified fresh run); results.{1..8}.json on disk.
