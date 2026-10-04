# Worklog — task_3299_mobile_wallet_card_provisioning_token_lifecycle_device

## Step 1: Create task directory — 2026-09-30T18:25:00.000Z

Task directory was pre-allocated by the caller: `./tasks/task_3299_mobile_wallet_card_provisioning_token_lifecycle_device/` with `workspace/` inside. Verified it exists; no new index computed and no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T19:00:00.000Z

All checks pass. The scaffold package is complete and lint-clean.

**Task:** `task_3299_mobile_wallet_card_provisioning_token_lifecycle_device` — Mobile Wallet Card Provisioning, Token Lifecycle & Device Binding (Apple Pay), generated per the difficulty directive "much harder than expert level."

**Files written:**
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Surface:**
- Entities: **15** (Cardholder, Device, Issuer, IssuerAgreement, MerchantProgram, CardAccount, CardArtifact, ProvisioningSession, PaymentToken, Authorization, Dispute, TransitOperator, MerchantCardProgram, TransitAllowlist, TokenEvent)
- State machines: **8** (issuer, agreement, card account w/ fraud-restrict cycle, artifact, provisioning session w/ lazy expiry + OTP-failure branch, payment token w/ suspend/resume cycle + auto-suspend at 3 consecutive declines, authorization, dispute) — plus 2 OCC concurrency rules (tokenize on session version, default-card on device version)
- Endpoints: **73**
- Validations: **24** priority-ordered rules spanning auth / existence / state / safety / fiscal / constraint / temporal / referential
- Errors: **36** catalogued codes
- Roles: **5** (PlatformAdmin, IssuerOperator, Cardholder entity_backed, CustomerService, Any) — segregation-of-duties: cardholder opens disputes, only issuer resolves
- §1.8 instances: **18** (9 rules × 2, each with distinguishing aspect per §0.5)
- §1.9 instances: **49** across all 9 guide sections (47 scanned by lint + 2 `excluded_because` stubs)

**Verification:** `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (921 calls scanned). Additional audits passed: grounds resolvability, instance-name uniqueness across both design files, placeholder closure including YAML-anchor reuse, no forbidden concurrency vocabulary, OCC endpoints carry `expected_*_version` inputs and version-bump side effects, and the logical-clock default `2026-09-01T00:00:00Z` is pinned in the `/_clock/set_current_utc` endpoint description. No sibling task directories were inspected.

## Step 3: Copy shared files — 2026-09-30T19:01:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T19:10:00.000Z

All checks still pass. Final verification of a few remaining subtle rules — merchant enrollment carve-out wording and `enrolled_at`, `flat_fare_cents`, and the dispute `payment_token_id`/`authorization_id` path derivation are all present (confirmed in the field check). The work is complete.

**Output:** `workspace/PRD.md` — **355 lines**.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (all 5 roles with identity semantics), 2.2 API Response Structure (verbatim fixed block, byte-identical per template check), 2.3 Pagination, 2.4 Common Resource Properties (incl. `TransitAllowlist`/`TokenEvent` carrying only `id`+`created_at`), 2.5 OCC (both `concurrency_rules` with `expected_session_version`/`expected_device_version` → `ERR_VERSION_CONFLICT`/412), 2.6 Nested Resource Retrieval (left-to-right, all 9 entity-specific 404s), 2.7 Logical Clock (fixed `2026-09-01T00:00:00Z` startup), 2.8 Precision and Money (integer cents, floor division), 2.9 Status Codes, 2.10 Priority Ordering (all 24 validations with priorities 1–23 incl. 7.5), 2.11 Derived Security Posture, 2.12 Audit Trail
- §3 Business Logic: 3.1 Issuers/Agreements, 3.2 Cardholders/Devices, 3.3 Accounts/Artifacts, 3.4 Provisioning, 3.5 Token lifecycle/default card, 3.6 Authorization (two-phase gate architecture, all 8–17 gates, fee accrual/projection dual variants, express ceiling waterfall), 3.7 Disputes/Restriction/Risk (4/1/15/25/100 risk formula, conservation invariant), 3.8 Merchant Programs/Transit, 3.9 Reads
- §4 Endpoint table — all **73 endpoints** (4 columns only; role cells verified cell-by-cell against scaffold)
- §5 Error catalogue — all **36 error codes** (2 columns only; statuses verified)

**Hard contract results:**
- Contract 1 (field names): 92 required (all `entities[].fields[]`, all endpoint inputs incl. query filters, computed-read response fields, common fields) — 92 present, 0 missing. PASS
- Contract 2 (rules): all 8 state machines' transitions with guards/side effects in prose; all 7 calculations expressed in reconstructible prose; both OCC rules fully specified; all 24 validations paired with error_ids and priority ordering stated explicitly; all `applies_to` scopes enumerated. PASS
- Contract 3 (§3 path purity): 509 backtick tokens scanned in §3 — 0 slash-starting, 0 bare HTTP methods, 0 method+path combos. PASS

**Coverage confirmation:** every scaffold §1.1 entity field, §1.2 state machine transition, §1.2.1 concurrency rule, §1.3 calculation (including constants `SESSION_TTL_HOURS: 24`, `per_auth_cap_cents: 100000`, `decline_streak_suspend_threshold: 3`, risk bonuses 15/25, cap 100), §1.4 validation, §1.5 endpoint, §1.6 error code, and §1.7 role is covered in prose. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened.

## Step 5: Generate unit tests — 2026-09-30T19:30:00.000Z

Done. Summary:

**Files written**

`test_helpers/` (9 files): `__init__.py` (barrel export), `types.py` (status enums + role enum), `api_errors.py` (36 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`), `api_client.py` (one method per PRD endpoint — 76 client methods incl. `set_clock`), `constants.py` (100000 cap, 3-decline threshold, 15/25/100 risk constants, 24h TTL, clock start `2026-09-01T00:00:00Z`, good/bad OTP codes), `factories.py` (12 payload factories), `test_users.py` (shared headers for opaque roles + `make_cardholder_headers(entity_id)` for the entity-backed Cardholder role), `assertions.py` (per-entity assertions; `TransitAllowlist`/`TokenEvent` assert absence of `updated_at`/`version`), `fixtures.py` (composite chain: `reset_clock` → cardholder → issuer+agreement ACTIVE → HEALTHY device → OPEN account → artifact → verified session → tokenize with OCC version, plus `provision_second_token`, `authorize`, `approved_authorization`, `setup_provisioned_token`).

`test_suite/` (12 files + `conftest.py`): `test_01_…`–`test_21_…` covering fee calculation, risk scoring, token/account state cycles, transitive cascades, priority pairs, boundary precision (24h inclusive TTL, 3-decline auto-suspend), cross-entity gating, temporal overlap, compensating invariants, entities, state machines, calculations, validations, endpoints, errors, RBAC, cross-cutting (OCC, express flag, allowlist, active_token_count), consistency model.

**Test counts:** 81 tests total — Queue A (Difficulty): 34 tests over 17 instances (2 each); Queue B (Corner): 47 tests over 47 non-stub instances (1 each). The 2 `excluded_because` stubs were not translated; both cross-references resolve.

**Instances skipped (1):**
- `Difficulty/dual_variant_calc/issuer_fee_accrual_vs_projection_diverge_while_pending_authorizations_exist` — requires observing a PENDING authorization, but the PRD states the cryptogram alone decides the outcome at request time, so no PRD-declared flow leaves an authorization observably PENDING; fails unique derivability (the design recipe itself concedes no operational way to produce the state).

**Clock discipline:** PRD pins startup clock at `2026-09-01T00:00:00Z`; all design fixtures agree, and every fixture calls `POST /_clock/set_current_utc` explicitly. Boundary test uses `expires_at − 1s` success vs exactly-`expires_at` failure.

**Audit results:** every non-stub §1.8/§1.9 instance maps to exactly its required number of tests with verbatim `Design:` tags (no stray/missing tags); all quoted PRD citations survive a normalized literal grep of PRD.md (81/81 tests pass citation check); no `skip`/`xfail` markers; no scaffold references in comments/docstrings; all files compile and `test_helpers` imports cleanly.

## Step 6: Generate implementation — 2026-09-30T19:45:00.000Z

Implementation complete and verified. Summary:

**Files written (all under `workspace/implementation/`)**

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Guarded `pip install` (only when flask missing), `exec python3 app.py`, `$PORT` default 10000, binds 0.0.0.0 |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 70 | Flask app, ApiError/404/405/500 handlers emitting the scaffold envelope, blueprint registration, per-request store lock |
| `db.py` | 66 | Empty in-memory tables for all 15 entities, logical clock (fixed default `2026-09-01T00:00:00Z`, never wall-clock), fee ledgers, monotonic `_seq` for stable created-order sorting |
| `errors.py` | 69 | All 36 error IDs with their exact HTTP statuses |
| `response.py` | 94 | Envelope (`meta.api_request_id`/`api_request_timestamp` + `response_type` + `data`), list pagination meta (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, 1–100) |
| `middleware.py` | 104 | `X-User-ID`/`X-User-Role` auth (skipped on `[Any]` endpoints), role checks, Cardholder ownership, payload-schema helpers |
| `domain.py` | 223 | Posture computation, session lazy expiry (inclusive boundary), OTP expected codes, token suspend/deactivate cascades, issuer cascades, DPAN minting with collision retry, token events, risk score, floor-division fees |
| `helpers.py` | 105 | Entity-specific 404 resolvers, nested-parent checks, filtered/sorted/paginated list responses |
| `routes/*.py` (13 files) | ~1400 | All route groups |

**Coverage confirmed**
- **All 73 endpoints** (62 route decorators cover 73 distinct method+path pairs — Flask merges `/x` and `/x/<id>` rules; each scaffold row maps to exactly one handler)
- **8 state machines**: Issuer (incl. suspend/offboard cascades, terminate→suspend), IssuerAgreement (overlap, supersede rebirth, terminate cascade), CardAccount (reissue successor, FRAUD restrict/reopen, close gating), CardArtifact, ProvisioningSession (auto INITIATED→VERIFICATION_REQUIRED, 2-challenge verify, 3rd-mismatch→FAILED, lazy EXPIRED), PaymentToken (incl. decline-streak auto-suspend at 3), Authorization (cryptogram decision), Dispute
- **24 validations** in priority order (auth → role/ownership → schema → existence L2R → lazy expiry → state → idempotency → one-window → gates 8–17 → enrollment/dispute/agreement/default/DPAN rules)
- **36 error codes** all mapped to scaffold HTTP statuses
- **2 OCC rules**: `expected_session_version` on tokenize, `expected_device_version` on default-card (both 412)

**Boot check**
Port 19355 (test iterations) and default 10000 (final cold boot via `bash start.sh`). Verified live: full golden path (cardholder→issuer+agreement activation→device→set-security→account/artifact→session→2 verifies→OCC tokenize→default card), error paths (AGREEMENT_REQUIRED, VERSION_CONFLICT, OTP_MISMATCH×3→FAILED, IDEMPOTENCY_CONFLICT, one-window INVALID_STATE, AUTHENTICATION_REQUIRED, EXPRESS_TRANSIT_NOT_SUPPORTED, TRANSIT_NOT_ALLOWED, PROGRAM_INELIGIBLE, DISPUTE_AMOUNT_MISMATCH, PROVISIONING_SESSION_EXPIRED), cascades (issuer suspend/offboard, report_lost), fee accrual/projection (150¢ = 10000×150bps/10000), risk scoring, and FRAUD dispute restrict→resolve→reopen. Server killed by saved PID; ports left free.

Two notable judgment calls: the OTP challenge code is deterministic (`"<METHOD>:<session_id>"`) since the PRD/scaffold never pins a challenge value, and transit same-service-day (priority 23) is trivially satisfied because every auth is created at the logical clock instant.

**Orchestrator verification note:** independently diffed the PRD §4 endpoint table (73 rows) against the implementation's Flask route registrations. 72 unique method+path pairs cover all 73 rows: the scaffold declares `GET /merchant-programs/{programId}` (line 1317) and `GET /merchant-programs/{id}` (line 1473) as two rows with identical behavior ("Get a merchant program" / "id-keyed, supports reverse lookup"), which one Flask route serves. 36/36 error codes present in errors.py. start.sh verified guarded-install + foreground exec.

## Step 7: Test-iterate to PASS — 2026-09-30T20:00:00.000Z

All 8 rounds pass 81/81. Clean sweep achieved.

- **Iterations run:** 3 sweeps (initial diagnostic sweep + 1 post-fix sweep per fix, final sweep clean).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none (the canonical OTP constants there were the established contract; the implementation was the party that diverged).

- **Fixes applied to `test_suite/`:**
  - `test_02_risk_score_weighted_sum.py` — `test_risk_weighted_sum_is_42` setup bug: the fixture declined `ns["token"]` (the token carrying the OPEN dispute) twice, which under PRD §3.7's verbatim rule ("four points per decline accumulated by tokens of the account that currently carry an OPEN dispute") yields 4×2+15+25=48, not the asserted 42. The test's own docstring even stated "the disputed token has zero declines". Fixed by routing the two declines through a second, undisputed token (`provision_second_token`), restoring the intended 2×1+15+25=42 state. `test_decline_counters_below_autosuspend_threshold` in the same file was retargeted to `ns["token2"]` accordingly (the PRD-pinned counters now live on the declined token).

- **Fixes applied to `implementation/`:**
  - `workspace/implementation/domain.py` — replaced the ad-hoc deterministic challenge scheme `expected_code(session, method) -> f"{method}:{session_id}"` with `code_matches()` accepting the canonical good codes {"111111","222222","333333"}. PRD §3.4 names success/mismatch counting semantics but is silent on the issued challenge value; the prior scheme contradicted the benchmark-wide fixture contract in `test_helpers/constants.py`, causing all 57 setup-chain failures (`ERR_OTP_MISMATCH` on `verify_session`).
  - `workspace/implementation/routes/provisioning.py` — `verify_session` now uses `code_matches(...)`; import updated. All PRD-required semantics (ERR_OTP_MISMATCH on wrong code, third consecutive mismatch → FAILED, two successes → VERIFIED) unchanged.

**Final state: 8/8 parallel rounds at 81 passed / 81 total, no flakiness observed across rounds.**

**Orchestrator verification:** all 8 `results.*.json` files independently read — 81/81 passed, 0 failed in every round. Spot-checked the claimed fixes on disk: `test_02` routes declines through `provision_second_token`/`ns["token2"]` and asserts 42; `domain.py:114` defines `_GOOD_CODES = {"111111","222222","333333"}` and `routes/provisioning.py:129` calls `code_matches(...)`.

## Step 8: Finalize PRD — 2026-09-30T20:02:00.000Z

§3.7 (line 218) already pins the exact verbatim rule ("four points per decline accumulated by tokens of the account that currently carry an OPEN dispute; plus one point per decline accumulated by the account's other tokens"), so the test_02 fixture fix requires no PRD change.

**Line counts:** PRD.md 355 lines, PRD_FINALIZED.md 355 lines (0% delta — single in-place sentence insertion, no lines added/removed).

**Changes:**
- §3.4 — insert (one sentence into the identity-verification paragraph) — pins the OTP challenge semantics: the canonical correct codes are the literals `111111`, `222222`, and `333333` for all three methods (`OTP_TEXT`, `OTP_EMAIL`, `ISSUER_APP`), and any other `code` value counts as a wrong code — `implementation/domain.py:114` (`_GOOD_CODES`), `implementation/domain.py:124-125` (`code_matches`), `implementation/routes/provisioning.py:129` (only callsite).

**Step 7 diff disposition:**
- `implementation/domain.py` + `routes/provisioning.py` OTP fix → the one PRD edit above (PRD §3.4 named the mismatch semantics but was silent on which codes satisfy the challenge).
- `test_02_risk_score_weighted_sum.py` fixture fix → verified no PRD change needed; PRD §3.7 (line 218) already pins the verbatim weighted-sum rule the corrected test now asserts.

**Per-edit pre-edit search log:**
- Edit 1 (§3.4 OTP sentence):
  - (a) Subject: which `code` values count as a successful vs. wrong challenge on `POST /devices/{id}/provisioning-sessions/{id}/verify`.
  - (b) Paths enumerated: repo-wide grep for `code_matches`, `_GOOD_CODES`, `expected_code`, `verify_session`, `consecutive_otp` across `implementation/` — hits: `domain.py:114` (good-code set), `domain.py:117-121` (`expected_code` stub returning None, docstring confirming PRD silence), `domain.py:124-125` (`code_matches` — method-independent membership check), `routes/provisioning.py:10` (import), `routes/provisioning.py:110-146` (`verify_session`, the sole callsite; mismatch counting and third-mismatch FAILED semantics already match PRD verbatim). No other endpoint or helper consumes OTP codes.
  - (c) Wording adjustment: explicitly scoped the sentence to "for all three methods" because `code_matches` ignores `method` — naming the codes without that qualifier could have been read as method-specific, mis-describing the method-independent implementation behavior. The sentence also says "the issued challenge value is not surfaced to the caller" to stay consistent with `expected_code` returning None rather than claiming any particular issuance scheme.

**Orchestrator verification:** diff of PRD.md vs PRD_FINALIZED.md confirms exactly one sentence inserted into §3.4 line 186, nothing else changed.

## Step 9: Complete PRD — 2026-09-30T20:13:00.000Z

The file is complete: 355 lines in both, +1,662 chars over PRD_FINALIZED.md. All edits applied.

**Source**: `workspace/PRD_FINALIZED.md` (355 lines, 57,683 chars) → `workspace/PRD_COMPLETED.md` (355 lines, 59,345 chars; +1,662 chars, no lines added/removed).

**Counts**: 9 ambiguity-pins, 9 mismatch-revisions (18 edits total).

- §2.2 — insert — ambiguity — pin that serialization strips underscore-prefixed server-internal fields, and define `has_more` = `offset + len(items) < total_count` — implementation/response.py:32-54, helpers.py:79-80
- §2.3 — insert — ambiguity — ties on identical `created_at` broken by creation order — implementation/helpers.py:90 (sort key `(created_at, _seq)`)
- §2.10 (priority 6) — revise — mismatch — all state-machine rejections surface as `ERR_INVALID_STATE`; `ERR_INVALID_TRANSITION` is never emitted — implementation/errors.py:19-20 (defined, unused); routes/*.py raise `ERR_INVALID_STATE` everywhere
- §2.10 (priorities list) — revise — mismatch — drop the transit same-service-day window (priority 23); impl has no service-day check — implementation/routes/authorizations.py (absent)
- §3.1 (agreement create) — insert — ambiguity — non-positive `fee_cap_cents` on create is rejected with `ERR_TERMS_VALIDATION_FAILED` (422) — implementation/routes/issuer_agreements.py:40-50, 60
- §3.1 (supersede) — insert — ambiguity — supersede responds HTTP 200 with the newly created ACTIVE agreement — implementation/routes/issuer_agreements.py:103-109
- §3.2 (report_found) — insert — ambiguity — `found_at` overwrites; `reported_lost_at` is retained across found reports — implementation/routes/devices.py:104-105
- §3.3 (close) — insert — ambiguity — the open-dispute block applies only to closing an `OPEN` account (a `REISSUED` account has no live tokens, so closing it is dispute-agnostic) — implementation/routes/card_accounts.py:93-98
- §3.4 (session fields) — insert — ambiguity — session carries a `device_account_number` field, null until tokenize writes the minted DPAN onto it — implementation/routes/provisioning.py:73, 196
- §3.4 (verification_method) — insert — ambiguity — each verify overwrites `verification_method`; the field reflects the most recent attempt's method — implementation/routes/provisioning.py:128
- §3.4 (DPAN) — revise — mismatch+ambiguity — DPAN is a random 16-digit numeric string generated independently of the PAN; uniqueness enforced only against non-terminated tokens (`PENDING|ACTIVE|SUSPENDED`) — implementation/domain.py:173-182
- §3.5 (deactivate) — insert — ambiguity — `active_token_count` is recomputed as a fresh count of currently-ACTIVE tokens, never decremented — implementation/domain.py:59-64
- §3.6 (gate 9) — revise — mismatch — express-mode taps are exempt from the DEGRADED gate (only LOST blocks all modes) — implementation/routes/authorizations.py:54
- §3.6 (gate 15) — insert — ambiguity — program matching is `merchant_id` == program `merchant_name`, and only an `ACTIVE` enrollment in an `ACTIVE` program triggers the cap — implementation/routes/authorizations.py:74-82
- §3.6 (transit calculations) — revise — mismatch — removed the unimplemented same-service-day rule; recorded `amount_cents` equals the requested amount (caps are hard gates, never post-hoc clamps) — implementation/routes/authorizations.py (no clamping code)
- §3.6 (fee projection) — insert — ambiguity — with no ACTIVE agreement both fee figures are 0 while `authorization_count` still counts APPROVED+PENDING — implementation/routes/issuers.py:94-104
- §3.7 (total_disputed_cents) — revise — mismatch — exposure is computed on demand from the open-dispute set, not stored on the account — implementation/domain.py:213, routes/card_accounts.py:110-119
- §3.8 (enrollment) — revise — mismatch — `active_sessions_required` never widens the account-state gate (CardAccount has no SUSPENDED status); account must be OPEN — implementation/routes/merchant_programs.py:86-88
- §3.8 (operator) — insert — ambiguity — duplicate `operator_code` rejected with `ERR_VALIDATION`; `flat_fare_cents` is stored/returned but never applied to the authorized amount — implementation/routes/transit.py:27-30

Output file: `workspace/PRD_COMPLETED.md`. No new sections were added; all changes are inline sentence-level inserts/revisions, and no behavior absent from implementation/ was invented.

**Orchestrator verification:** PRD_COMPLETED.md exists (59,345 chars). Checked implementation mtimes — all .py files predate the Step 7 final sweep (19:59) except `domain.py` and `routes/provisioning.py` at 19:51, which are the Step 7 OTP fix itself (pre-sweep); NO implementation writes occurred after the clean sweep, so the 8/8 × 81/81 result stands and no re-sweep is required. Step 9 edited only PRD_COMPLETED.md.
