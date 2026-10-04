# Worklog — task_3004_store_rebate_certificate_program_store_credit_liability

## Step 1: Create Task Directory — 2026-09-29T12:06:00.000Z

Used pre-allocated task directory `./tasks/task_3004_store_rebate_certificate_program_store_credit_liability` with `workspace/` inside (per command args; no new index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-09-29T13:38:39.511Z

All three scaffold artifacts are generated, lint-clean, and saved under `/home/ubuntu/github/CodingPRD/tasks/task_3004_store_rebate_certificate_program_store_credit_liability/`.

**Files**
- `SCAFFOLD.yaml` (1571 lines) — §1.0–§1.7 only
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1542 lines) — `scaffold_difficulty_design`, 18 instances (2 per rule × 9 rules)
- `SCAFFOLD_CORNER_DESIGN.yaml` (2444 lines) — `scaffold_corner_design`, 53 instances (50 active + 3 `excluded_because` stubs)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (83 endpoints, 14 entities, 18 §1.8 + 50 §1.9 active instances, 786 calls scanned)

**Scaffold shape (Expert band, difficulty pushed to the skill's maximum):**
- **14 entities**: Store, RebateProgram, ProgramItem, CreditAccount, JobPurchase, Receipt, ReceiptLine, Return, RebateSubmission, SubmissionLine, RebateCertificate, CreditLedgerEntry, FraudFlag, BreakageRun. Archetype: ledger reconciliation + temporal windowing; cyclic state-machine shape; peer-role RBAC (StoreAdmin/GuestService/FraudAnalyst/FinanceAdmin opaque + Customer/Contractor entity-backed).
- **7 state machines**, two non-linear on different entities: certificate ACTIVE→EXPIRED→REISSUED→(new ACTIVE) cycle with a parallel fraud_hold dimension; submission REJECTED→SUBMITTED resubmission cycle bounded by `resubmit_count < 3`.
- **8 calculations** covering all difficulty modes: dual-variant rebate award (provisional ignores returns/min-quantity) AND dual-variant store liability (gross vs net-of-breakage) — different entity domains; mode (a) 5-input award formula (returns × cert-tender × pct × cap × exclusions); mode (b) pinned round-per-line-then-sum (111 vs 110 divergence pre-computed); contractor tiered aggregation with >= boundary (500000 exactly → PRO, bonus 10000); month-end-clamped expiry projection (Jan 31 → Feb 28).
- **17 validation priorities** with two deliberate cross-category conflicts (business_temporal p8 vs state p9; business_constraint p13 vs business_referential p14).
- **27 error codes**; **2 OCC concurrency rules** on `Store.version` (config PATCH + breakage runs) with `${var}`-captured versions throughout.
- **Cascade chains**: depth-4 guest-service return reversal (Return → submission REVERSED → certificate VOIDED → REVERSAL_DEBIT ledger → liability recompute) and depth-3 breakage-run sweep, plus two compensating invariants (certificate face-value conservation across issue/redeem/expire/reissue; signed ledger sum == account position with zero drift).
- All numeric asserts in both design files were pre-computed with Python (round_half_up semantics); every receipt `purchase_at` is sequenced behind the logical clock (default `2026-09-01T00:00:00Z`) to satisfy `ERR_RECEIPT_IN_FUTURE`; fraud-confirmed reissue blocking is tested via a hold-release + second-expiry chain rather than an un-releasable hold.

**Notable design decisions:** `api_prefix` set to root so canonical single-GET segments drive FK reverse-reachability; certificates are store-scoped AND account-bound (both folded into `ERR_CERTIFICATE_WRONG_STORE`); the rebate-purchase bar is enforced twice at different layers (redeem-time 422 and award-time FULLY_CERTIFICATE_TENDERED base zeroing); EXPIRED certificates stay in gross liability during the 30-day reissue grace, making the reissue cascade restore liability from recognized breakage.

## Step 3: Copy Shared Files — 2026-09-29T13:38:39.511Z

Copied `./INSTRUCTION.md` to `./tasks/task_3004_store_rebate_certificate_program_store_credit_liability/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T13:51:38.493914821Z

PRD generated successfully. Summary below.

**Output:** `workspace/PRD.md` — 324 lines.

**Section structure:**
- §1 Introduction (2 paragraphs — business context + the two shaping forces: liability accounting and fraud surface)
- §2 Global Specifications (9 subsections): 2.1 RBAC with per-role `identity:` prose, 2.2 verbatim response-envelope block (byte-identical copy), 2.3 Pagination, 2.4 Common Resource Properties (including explicit `updated_at`/`version` absence for `ReceiptLine`, `SubmissionLine`, `CreditLedgerEntry`), 2.5 Monetary Precision (integer cents, round-half-up), 2.6 Logical Clock & Temporal Windows (startup default `2026-09-01T00:00:00Z`, half-open weeks, inclusive deadlines, exclusive expiry), 2.7 Liability Accounting (dual gross/net variants, append-only ledger, all five `entry_type` values), 2.8 OCC (both rules with `expected_store_version` → `ERR_STALE_VERSION` 412), 2.9 Nested Retrieval & Validation Priority
- §3 Business Logic (9 subsections): store provisioning, program week lifecycle, accounts & contractor job envelopes, receipts/tender splits/split-scan, submission & award calculation (9-step per-line algorithm as a numbered list), certificate redemption/expiry/reissue/holds, liability composition & breakage sweep, return reversal cascade (4 levels), fraud workflow
- §4 Endpoint table — 4 columns, all 83 scaffold endpoints
- §5 Error catalogue — 2 columns, all 27 error IDs

**Coverage (all verified mechanically):**
- Contract 1: 73 entity fields + 42 endpoint input identifiers — 0 missing (one miss, `contractor_account_id`, found and repaired on the second pass)
- Contract 2: spot-checked ~38 high-risk rule phrases (validation priority ordering on activation, both OCC rules, full reversal cascade including the no-clawback rule, pinned rounding order, per-variant award differences, breakage zero-sweep legality, tier boundary inclusivity, day-overflow clamp, lazy auto-close, adjacency-not-overlap, REVERSED-exempt duplicate scan, half-open split window, confirmed-flag hold cascade, etc.) — all present
- Contract 3: 373 backticked tokens scanned in §3 — 0 path-starting tokens, 0 bare HTTP methods, 0 method+path tokens
- All 41 enum/state values present; all 27 error IDs mentioned in §2/§3 prose

**Notable prose-design decisions:**
- §3.5 renders the 9-step `rebate_award` algorithm as a numbered list inside narrative (still prose sentences per step, no pseudocode operators), the cleanest way to keep the pinned per-line-then-sum rounding and provisional/adjudicated variant differences unambiguous
- Unit-conversion scattering: tier thresholds expressed as "500,000 cents" / "2,000,000 cents" (matching the cent-denominated domain) rather than converting to dollars, keeping the constants exactly reconstructible
- Temporal conventions consolidated once in §2.6 (half-open weeks, inclusive submission deadline, exclusive expiry instant) and then applied by reference in §3, avoiding contradictory restatements
- The certificate expiry day-overflow rule carried the concrete worked example (Jan 31 + 1 month → Feb 28) since the scaffold itself defines the clamp by example
- §2.9 folds the global validation priority order (auth → role → path → payload shape → business rules) into the nested-retrieval subsection rather than a standalone block

## Step 5: Generate Unit Tests — 2026-09-29T14:31:33.941031643Z

All 83 tests collect cleanly. Generation is complete. Final summary:

**test_helpers/** (9 files, all under `test_helpers/`):
- `types.py` — 6 roles + 12 status/type enums + 14 entity TypedDicts (ReceiptLine/SubmissionLine/CreditLedgerEntry correctly carry only `id`+`created_at`)
- `api_client.py` — `ApiClient(GenericApiClient)` with all 40 PRD endpoints, keep-alive-safe `_request` override, `to_iso8601` clock payload
- `api_errors.py` — 27 error IDs with HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + store/account invariant checkers
- `factories.py` — payload factories incl. `cash_line()` tender-split builder
- `constants.py` — `MAX_RESUBMITS`, `REISSUE_GRACE_DAYS`, tier thresholds, `STANDARD_POLICY`
- `test_users.py` — opaque role constants + `make_customer_headers`/`make_contractor_headers` entity-backed builders + `NO_AUTH_HEADERS`
- `fixtures.py` — 5-tier composites: clock/store/program/account/receipt builders, submission chain (submit/approve/reject/resubmit/issue), `setup_issued_certificate` (with `account=` reuse), OCC-safe `run_breakage`, `open_duplicate_receipt_flag`
- `__init__.py` — barrel export

**test_suite/** — 83 tests in 7 files: `test_01_stores_programs_rbac.py` (15), `test_02_receipts_and_returns.py` (12), `test_03_award_calculation.py` (12), `test_04_submission_lifecycle.py` (11), `test_05_certificate_lifecycle.py` (16), `test_06_cascades_breakage_fraud.py` (16), `test_07_resubmit_recompute.py` (1), plus `conftest.py`.

**Queue A (difficulty): 16/18 emitted (≥2 tests each); 2 skipped**
- `priority_pair_validation_conflict/adjudicate_rejected_submission_past_window_temporal_beats_state` — SKIPPED: PRD §2.9's priority ladder (auth → authorization → path existence → payload → "business, temporal, referential, state…") lists categories only and never states that a temporal failure precedes a state failure on the same endpoint; asserting `ERR_SUBMISSION_WINDOW_CLOSED` over `ERR_INVALID_STATE` is not uniquely derivable (validation-priority silence pattern).
- `priority_pair_validation_conflict/redeem_wrong_store_rebate_eligible_receipt_referential_beats_constraint` — SKIPPED: PRD §3.6 explicitly orders redemption checks with wrong-store (`ERR_CERTIFICATE_WRONG_STORE`) *before* the rebate-purchase bar; the instance asserts the scaffold's priority-13-before-14 ordering, which contradicts the PRD and would fail a PRD-faithful implementation.

**Queue B (corner): 47/47 non-stub instances emitted (1 test each).** All 3 `excluded_because` stubs correctly untranslated; their `difficulty_instance` pointers resolve (verified against the difficulty index).

**Stage 2 self-audit findings:**
- Every test carries exactly one `Design:` tag resolving to a real instance (automated check passed).
- Every PRD citation contains a ≥8-word substring surviving literal grep of `workspace/PRD.md` (automated check, 0 failures).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code.
- Deviations fixed during generation: recipe-stated receipt numbers use `receipt_number=` overrides (factory auto-increments would collide); multi-certificate scenarios reuse one account via the `account=` fixture kwarg; the redeem-past-expiry test uses the exact expiry instant (PRD states redemption fails "at or past" expiry); the reissue-grace test fires at `expires_at + 30 days` exactly (PRD: "once the logical clock reaches 30 days past expiry").

NOTE (orchestrator): A duplicate Step 5 Agent call was accidentally issued in the same message as the first; it terminated early with an API error. Post-incident verification confirmed the test artifacts are intact: 83 tests collect cleanly, matching the completed agent's report exactly.

## Step 6: Generate Implementation — 2026-09-29T15:28:43.914612729Z

Fresh boot confirmed: empty store, 201 on create, and the process responds to SIGTERM (via `exec` in start.sh).

Implementation complete. Summary:

**Files created (all under `workspace/implementation/`)**
- `start.sh` — bash launcher; guards the pip install behind `python3 -c "import flask"`, then `exec python3 app.py`
- `requirements.txt` — `Flask>=2.2.0`
- `app.py` — Flask app factory, blueprint registration, `ApiError`/HTTP error handlers, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`
- `db.py` — in-memory dicts (13 collections, all empty at boot; no seeding), logical clock with fixed startup default `2026-09-01T00:00:00Z`, `base_record` (id + created_at [+ updated_at/version=1]), monotonic `_seq` tiebreaker for created_at ordering
- `errors.py` — all 26 catalog error_ids with exact HTTP statuses
- `response.py` — envelope `{"meta": {api_request_id, api_request_timestamp}, "response_type": object|array|error, "data": ...}`; pagination fields `limit/offset/total_count/has_more` in meta; ISO-8601 timestamps with 3 fractional digits
- `middleware.py` — `X-User-Role`/`X-User-ID` auth (401 ERR_UNAUTHENTICATED / 403 ERR_FORBIDDEN), entity-backed ownership check for Customer/Contractor (X-User-ID == account id), typed payload validators (400 ERR_INVALID_REQUEST), pagination parsing (default 10, min 1, max 100)
- `serialize.py` — per-entity field projections; ReceiptLine/SubmissionLine/CreditLedgerEntry emit only `id`+`created_at` (no updated_at/version, per PRD 2.4)
- `services/lookup.py` — existence + left-to-right nesting checks (404 ERR_NOT_FOUND)
- `services/temporal.py` — half-open advertised weeks, submission deadline (purchase date 00:00:00Z + N days, deadline inclusive), calendar-month expiry with day-clamp (Jan 31 + 1mo → Feb 28), lazy program auto-close, reissue grace (30 days), MAX_RESUBMITS=3
- `services/core.py` — all calculations and cascades
- `routes/` — `clock.py`, `stores.py`, `programs.py`, `accounts.py`, `receipts.py`, `submissions.py`, `certificates.py`, `ops.py` (ledger/breakage/fraud), `common.py`

**Endpoint count**: 83 routes registered, covering all 78 scaffold endpoints (64 store-scoped + flat canonical/lookup reads) plus Flask internals excluded.

**Key mechanics**
- **State machines**: RebateProgram DRAFT→ACTIVE (ordered checks: ERR_PROGRAM_EMPTY → ERR_PROGRAM_WEEK_OVERLAP with adjacency-not-overlap → ERR_PROGRAM_WEEK_PAST) →CLOSED incl. lazy auto-close on access; RebateSubmission SUBMITTED→UNDER_REVIEW in-request, adjudicate (window-then-frozen order), REJECTED↔SUBMITTED capped at 3 resubmits, APPROVED→REVERSED cascade; RebateCertificate lifecycle plus independent `fraud_hold` parallel dimension (HELD blocks redeem/reissue, toggled from any non-terminal status); FraudFlag OPEN→CONFIRMED (holds all NONE certs)/CLEARED→OPEN; CreditAccount freeze/unfreeze (blocked by OPEN DUPLICATE_RECEIPT flag)/close (requires zero credit + pending); Receipt OPEN→PARTIALLY/FULLY_RETURNED derived from line quantities; BreakageRun RUNNING→COMPLETED atomically in-request.
- **Calculations**: `rebate_award` per-line (store-scoped match, max rebate_pct / created_at tiebreak, excluded-category override, adjudicated-only min_quantity, fully-certificate-tendered bar, cert-tender-adjusted base floored at 0, pre-rounding cap, per-line `Decimal` ROUND_HALF_UP then sum); provisional variant ignores returns and min_quantity; `store_credit_liability` gross (ACTIVE/PARTIALLY_REDEEMED/EXPIRED remainders + unsettled APPROVED awards) and net (single final round-half-up of gross × (1−rate)); `credit_account_balance` with pending-before-balance pinned order via "settled" detection (APPROVED submission with issued cert counted only through the certificate leg); `breakage_recognition` (expires_at ASC / created_at tiebreak, inclusive `<=` boundary, epoch stamped on entries, zero-sweep runs still advance epoch); `fraud_screening` split scan (half-open `(purchase−window, purchase]`, min-receipts cluster, shared-SKU requirement) and duplicate scan (non-REVERSED prior submission → 409 + flag); `contractor_aggregation` net-of-reversal per-job totals with inclusive-upward tiers (NONE/PRO 2%/PRO_PLUS 5%, single round-half-up); `certificate_expiry_timestamp` month arithmetic with clamp.
- **Validation priority**: auth → role/ownership → path existence left-to-right → structural (400) → tender-sum (422) → future receipt → job-purchase referential → submission window → resource state → duplicate-submission screening → fraud holds → certificate temporal → redemption bar → store/account scoping → fiscal limits → program activation rules → OCC (412), with per-endpoint ordering pinned to PRD prose (e.g. adjudicate-APPROVE checks window before frozen; returns check all quantities before any mutation).
- **OCC**: `expected_store_version` on PATCH /stores and POST breakage-runs; mismatch → ERR_STALE_VERSION 412; every store mutation (including each liability recompute and each breakage run) bumps `Store.version` by 1.
- **start.sh contract**: reads `$PORT` (default 10000), binds `0.0.0.0`, runs in foreground via `exec`, idempotent dependency install. Verified: fresh process boots with an empty store, full 100+ assertion smoke coverage passes (award math, liability variants, reversal cascade with REVERSAL_DEBIT on remaining balance only, expiry/reissue with grace window, holds, freeze/unfreeze flag interplay, split-scan window edges, contractor tiers, OCC, pagination, 404 nesting), and the server restarts cleanly per invocation.

## Step 7: Run Tests and Iterate — 2026-09-29T16:15:02.927290942Z

Cleanup done (results files removed; stray manual servers killed). Final state: 82/82 tests passing in all 8 rounds across two consecutive sweeps.

**Iterations run:** 3 eight-round parallel sweeps (plus 1 confirmation sweep after the last fix).

- Sweep 1 (baseline): 63/83 in all 8 rounds — 20 deterministic failures, 4 clusters.
- Sweep 2 (after fixes A/B/D): 79–81/82 — 3 remaining failures, 1 flaky (connection reset).
- Sweep 3 (after fixes C/E/F): 82/82 × 8 rounds clean.
- Sweep 4 (confirmation): 82/82 × 8 rounds clean.

**Tests deleted (1):**
- `TestReceiptCreationRules::test_receipt_create_with_unknown_account_returns_422_invalid_job_purchase` (test_02) — DEFAULT-VALUE/error-attribution silence: PRD §3.4's `ERR_INVALID_JOB_PURCHASE` sentence is explicitly scoped to "When `job_purchase_id` is present" (the test sent none), and PRD never names the error for a receipt referencing a nonexistent `account_id` (a faithful implementer may return `ERR_NOT_FOUND` per §2.9's referential-rule wording). Scaffold-only rule (scaffold priority-7 check drove generation).

**Tests pruned (partial coverage, STEP 1c):**
- `TestJobPurchaseRules::test_job_purchase_on_retail_account_rejected` (test_02) — removed its first half (creating a job purchase on a RETAIL account expecting `ERR_INVALID_JOB_PURCHASE`): PRD never names an error for the job-creation account-type gate, so both `ERR_INVALID_JOB_PURCHASE` and `ERR_INVALID_STATE` are PRD-faithful (error-attribution silence). Kept the fully-covered second half (job owned by a different contractor → `ERR_INVALID_JOB_PURCHASE`, verbatim in PRD §3.4).

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `setup_approved_submission` / `setup_issued_certificate` now accept and forward `**receipt_overrides` (e.g. `receipt_number`) to the receipt factory. Test authors already passed these kwargs; the helpers dropped them with `TypeError`, which had been masking 14 tests as setup failures. Pure bug fix; no semantic change.

**Fixes applied to `test_suite/` (test bugs, not assertion weakening):**
- test_02/04/05 — 4 timestamp assertions changed from exact string equality (`"2026-10-08T00:00:00Z"`) to instant-level datetime comparison. PRD pins only the *instant*; the fractional-second wire spelling (`.000Z` vs none) is not specified for entity timestamps (§2.4's three-fractional-digit rule names `created_at` only), so string equality was not uniquely derivable.
- test_02 `test_clock_set_endpoint_echoes_new_time_and_defaults` — fixture bug: the test created a receipt at `00:30` while asserting the clock still sat at the `00:00` startup default; PRD §3.4 correctly rejects a future `purchase_at`. Changed purchase_at to exactly the default instant.
- test_06 `test_breakage_entries_carry_run_epoch_and_sweep_order` — the account-scoped ledger listing has no PRD-declared `entry_type` filter (§4 tables declare filtering only on platform-wide `/ledger-entries`); the test now filters client-side instead of relying on an undeclared query param.
- test_06 `test_contractor_summary_tier_boundary_and_net_of_reversal` — fixture bug: `f"…T{minute}:00:00Z"` with `minute="10"` produced the malformed timestamp `T10:00:00:00Z`; switched to explicit `hhmm` strings.

**Fixes applied to `implementation/`:**
- `services/core.py::contractor_summary` — a `REVERSED` submission was counted only in the minus leg; per PRD §3.3's net-of-reversal definition ("sum over APPROVED … minus the award_cents of REVERSED submissions on those same receipts"), a reversed submission must also contribute to the APPROVED leg so its job nets to 0 rather than going negative.
- `app.py` — flakiness fix: serve with a WSGI request handler using `protocol_version = "HTTP/1.0"` (connection-per-request, no keep-alive). Under 8-way parallel load the Werkzeug dev server's keep-alive window occasionally surfaced `ECONNRESET` on the next request (1-of-8 rounds twice, different tests each time, never an assertion failure). No API-visible behavior change; all timestamps/envelopes/routes unchanged.

No implementation checks were removed or weakened, no endpoints/fields added, no data seeded; storage remains in-memory only.

## Step 8: Finalize PRD — 2026-09-29T16:20:41.411857731Z

Both edits committed. The diff is exactly two in-place sentence additions; line counts are identical (323 lines each, 0% delta).

**File produced:** `workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 323 lines, PRD_FINALIZED.md = 323 lines, 0.0% line-count delta (two inline sentence additions on existing lines).

### Changes (one bullet per edit)

- **§3.3 (Credit Accounts and Contractor Job Envelopes)** — insert — appended "— a registration attempt against any other account type or status is rejected with `ERR_INVALID_STATE` (409)" to the job-registration sentence, pinning the error for the account-type/status gate that the PRD left unnamed — `implementation/routes/accounts.py:125-128` (`create_job` raises `ERR_INVALID_STATE`).
- **§3.4 (Receipts, Tender Splits, and Split-Transaction Screening)** — insert — appended "The `account_id` itself must reference an existing credit account; an unknown `account_id` is rejected with `ERR_NOT_FOUND` (404)." to the receipt-creation paragraph — `implementation/routes/receipts.py:100-102`.

### Step 7 items that required no PRD edit

- **contractor_summary fix** — implementation (`services/core.py:419-429`) was changed to match the PRD §3.3 net-of-reversal wording verbatim; PRD already pinned the behavior.
- **Timestamp wire-spelling** — the test relaxation to instant-level comparison reflects PRD silence on fractional-digit rendering of non-`created_at` timestamps; pinning a wire format here would exceed what the implementation guarantees uniformly (e.g., caller-supplied `purchase_at` is echoed verbatim with caller precision at `routes/receipts.py:125`), so no universal claim was added.
- **fixtures.py / test bugs / account-ledger filter / clock fixture** — pure test-side bugs, no implementation behavior involved.
- **app.py HTTP/1.0 keep-alive fix** — transport-level flakiness fix, no API-visible behavior change; nothing to pin in the PRD.

### Per-edit pre-edit search log

**Edit 1 (§3.3, job-registration gate error):**
- (a) Subject: error code/status returned when a job purchase is registered on an account that is not a CONTRACTOR account in ACTIVE status.
- (b) Enumerated impl paths: `implementation/routes/accounts.py:117-138` (`create_job` — the only job-creation endpoint; gate at lines 125-128 raises `ERR_INVALID_STATE`); `implementation/routes/accounts.py:154-166` (`settle_job` — unrelated gate, `ERR_INVALID_STATE` for non-OPEN); `implementation/routes/receipts.py:103-110` (receipt-side `job_purchase_id` validation — a different rule, uses `ERR_INVALID_JOB_PURCHASE`, untouched by the edit's wording); `implementation/services/core.py` (no job-creation logic); error catalogue §5 already contains `ERR_INVALID_STATE` 409. Wording was scoped to "a registration attempt against any other account type or status" so it cannot be misread as covering the receipt-time job-link rule.
- (c) Wording adjustment: kept the added clause as a direct continuation of the existing account-type/status sentence (em-dash appositive), avoiding any claim about the receipt-side `ERR_INVALID_JOB_PURCHASE` rule.

**Edit 2 (§3.4, unknown `account_id` on receipt creation):**
- (a) Subject: error attribution when receipt creation references a nonexistent `account_id`.
- (b) Enumerated impl paths: `implementation/routes/receipts.py:93-110` (validation ladder: `ERR_RECEIPT_IN_FUTURE` at lines 94-96 precedes the account-existence check at lines 100-102, which raises `ERR_NOT_FOUND`; `ERR_INVALID_JOB_PURCHASE` at lines 103-110 applies only when `job_purchase_id` is present and fails); `implementation/services/lookup.py` (404 pattern for missing path entities); §2.9 referential-rule wording (404 before business rules); §5 catalogue (`ERR_NOT_FOUND` 404 already listed). No other endpoint resolves a body-supplied `account_id` differently.
- (c) Wording adjustment: phrased as "The `account_id` itself must reference an existing credit account" to scope it strictly to the receipt-creation body field, and placed after the `ERR_INVALID_JOB_PURCHASE` sentence so it does not alter the priority ordering statements around it; deliberately silent on ordering vs. `ERR_RECEIPT_IN_FUTURE` since the PRD elsewhere (§2.9) fixes the ladder and the edit needed no ordering claim.

## Step 9: Complete PRD — 2026-09-29T16:40:41.185267636Z

All edits complete and verified. Both files have identical structure (323 lines; all changes are inline insertions/revisions within existing paragraphs).

**Source vs. produced:** `PRD_FINALIZED.md` — 323 lines / 52,878 chars; `PRD_COMPLETED.md` — 323 lines / 56,174 chars (char-delta: **+3,296**; same line count — every change is an in-paragraph insert or revision).

**Counts:** 15 ambiguity-pins, 4 mismatch-revisions (19 edits total).

**Changes:**
- §2.1 — revise — **mismatch** — "must carry two HTTP headers" corrected: only `X-User-Role` is required; a missing `X-User-ID` is treated as an empty identifier, failing ownership comparisons — middleware.py:53-60
- §2.4 — revise — **ambiguity** — `version` now pinned to start at 1 on creation — db.py:74-77
- §2.6 — revise — **ambiguity** — clock-set accepts any instant (forward or backward) and does not itself run lazy auto-close (evaluated on next program access) — routes/clock.py:17-23, services/temporal.py:74-91
- §3.2 — revise — **mismatch** — "Once ACTIVE, receipts … become matchable" implied status-gated matching; impl matches program items in every program status (DRAFT/CLOSED included) — services/core.py:164-185
- §3.3 — revise — **ambiguity** — `pending_award_cents` excludes APPROVED submissions already settled by an issued certificate — services/core.py:93-119
- §3.3 — revise — **mismatch** — unfreeze applies only to a FROZEN account (else `ERR_INVALID_STATE`); freeze of a non-ACTIVE account rejected `ERR_INVALID_STATE` — routes/accounts.py:65-67, 80-82
- §3.3 — revise — **mismatch** — account close requires ACTIVE status (FROZEN/CLOSED → `ERR_INVALID_STATE`) before the zero-balance check — routes/accounts.py:100-107
- §3.3 — revise — **ambiguity** — contractor summary per-job entries carry `job_id`, `job_reference`, `status`, `job_awarded_cents`; RETAIL accounts rejected with `ERR_INVALID_REQUEST` (400) — services/core.py:432-437, routes/accounts.py:176-178
- §3.4 — revise — **ambiguity** — `ERR_RECEIPT_IN_FUTURE` fires only when `purchase_at` is strictly after the logical clock (equality accepted) — routes/receipts.py:94
- §3.4 — revise — **ambiguity** — receipt line structural rules pinned: non-empty `lines`, non-empty `sku`/`category`, integer `line_number` ≥ 1 unique per receipt, non-empty `tender_splits`, split `amount_cents` ≥ 0 — routes/receipts.py:38-83
- §3.4 — revise — **ambiguity** — SPLIT_TRANSACTION flag lists cluster receipt ids in ascending `created_at` order — services/core.py:324-332
- §3.5 — revise — **ambiguity** — submission creation rule order pinned: window → duplicate screen → frozen — routes/submissions.py:40-51
- §3.5 — revise — **ambiguity** — adjudication: `ERR_INVALID_STATE` precedes the window and frozen checks — routes/submissions.py:121-136
- §3.5 — revise — **ambiguity** — resubmit requires non-FROZEN account; check order state → cap → window → frozen — routes/submissions.py:169-186
- §3.5 — revise — **ambiguity** — issuance: `APPROVED`-only state check and frozen check (`ERR_ACCOUNT_FROZEN`) explicitly stated in the issuance paragraph — routes/submissions.py:209-216
- §3.6 — revise — **ambiguity** — redemption check list gains the frozen-account step (`ERR_ACCOUNT_FROZEN`) in second position, matching impl's exact order — routes/certificates.py:61-100
- §3.6 — revise — **ambiguity** — reissue pinned EXPIRED-only (`ERR_INVALID_STATE` first), then window → fraud-confirmed → held — routes/certificates.py:126-143
- §3.6 — revise — **ambiguity** — hold/release on a terminal certificate (`FULLY_REDEEMED`/`VOIDED`/`REISSUED`) rejected with `ERR_INVALID_STATE` (409) — routes/certificates.py:187-189, 202-204
- §3.7 — revise — **ambiguity** — gross liability's APPROVED-submission leg excludes submissions already settled by an issued certificate (no double-count with the certificate leg) — services/core.py:99-134
- §3.8 — revise — **ambiguity** — reversal cascade reverses every APPROVED submission on the receipt touching an eligible line, settled or not — services/core.py:374-377

Output file: `workspace/PRD_COMPLETED.md`

## Post-Step-9 Verification Sweep — 2026-09-29T16:40:41.185267636Z

Orchestrator-run final 8-round parallel stability sweep (same prd-bench-local-run invocation as Step 7) against the current implementation/ + test_suite/ + test_helpers/ tree: all 8 rounds 82/82 passed, 0 failed. Round 6's results file was missing from disk after the parallel sweep (its runner process reported "Results: 82/82 passed, 0 failed" in stdout, but the JSON was not materialized — a write-side hiccup under 8-way load); round 6 was re-run standalone and produced results.6.json with 82/82 passed. All results.{1..8}.json files are present in workspace/implementation/ and all report 82/82.
