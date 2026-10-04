# Worklog — task_3081_tax_return_accuracy_guarantee_audit_representation_program

## Step 1: Create task directory — 2026-09-29T21:00:00.000Z

Pre-allocated task directory `tasks/task_3081_tax_return_accuracy_guarantee_audit_representation_program/` verified to exist with `workspace/` inside. Used exactly this path per command args; no index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-29T21:48:00.000Z

All three files are written, lint is clean, and manual consistency checks pass.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3081_tax_return_accuracy_guarantee_audit_representation_program/`):
- `SCAFFOLD.yaml` — 1948 lines (§1.0–§1.7; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1470 lines (single top-level `scaffold_difficulty_design`; 9 rules × 2+ instances = 19 instances)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1407 lines (single top-level `scaffold_corner_design`; 8 sections, 30 instances; total 557 linted calls)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Difficulty tier applied:** maximum ("harder than expert") — 13 entities, 55 endpoints, 27 error codes, 7 calculation rules (5 with variants/multi-mode), 9 state machines, 20 ordered validations, 2 OCC concurrency rules; every §0.5 rule carries ≥2 differentiated instances (19 total), with all formula-derived asserts pre-computed as literals (fees 27500/34400/41300/48100; interest 0/3/323/425/468; payouts 43323/55425; liabilities 81323/105425; accruals 60968/121936/22187; scores 79/80/0).

**Key design decisions:**
- **Archetype:** compliance_audit primary + ledger_reconciliation secondary; flat topology, branching state-machine shape, segregation_of_duties role model, immediate consistency. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, derived-field reconciliation.
- **Entities (13):** Office (derived posture OK/WATCH/PROBATION), Preparer (parallel dimensions: credential_status × remediation_status), Client, TaxReturn (self-referential `original_return_id` for amended filings), ProtectionProduct (STANDARD/PLUS, 1-per-return), AuthorityNotice (interest computed at pay time), Claim (cyclic: TRIAGE↔INFO_NEEDED, RESOLVED→REOPENED→…→RESOLVED), EnrolledAgent (capacity + half-open assignment windows), RepresentationAssignment, PowerOfAttorney (DRAFT supersession + lazy expiry), RemediationAction (self-overwrite auto-close chain), OfficeEscrow (paid_out vs historical expected_accrual), OfficeQualitySnapshot.
- **State machines (9):** Claim is fully cyclic with an info loop and a reopen cycle; Office posture is a fully-connected recomputation machine driven only by quality-close; Preparer carries two independent state dimensions.
- **Calculations (7):** prep_fee (dual-variant quote-vs-final with tier multiplier + round-to-dollar), protection_premium (tiered threshold, `<=` caps), interest_accrual (round-once vs round-per-day pinned), reimbursement_payout (PREPARER_ERROR vs CLIENT_DATA_ERROR variants + base-double-count liability fold), escrow_accrual_expected (per-claim round-then-sum, historical on reopen), office_quality_score (weighted score with 80/60 posture thresholds + probation suspension cascade).
- **Cross-cutting mechanisms:** OCC on `expected_return_version` (claim intake) and `expected_poa_version` (POA execute); segregation of duties on resolve vs scope (priority 7 vs 10 conflict); probation posture gating on product sales/upgrades; half-open assignment-window overlap vs strictly-increasing quality-close periods (two distinct interval semantics); logical-clock endpoint with the mandated `2026-09-01T00:00:00Z` default.

## Step 3: Copy shared files — 2026-09-29T21:48:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3081_tax_return_accuracy_guarantee_audit_representation_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T21:55:00.000Z

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_3081_tax_return_accuracy_guarantee_audit_representation_program/workspace/PRD.md`

**Line count:** 279 lines

**Section structure:**
- §1 Introduction — 3 paragraphs (trust/pain-point angle, hard bookkeeping questions, role model + logical clock)
- §2 Global Specifications — 9 subsections: 2.1 RBAC (all 6 roles, entity-backed identity translated per role), 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`, verified programmatically), 2.3 Pagination (limit default 10 / min 1 / max 100, offset 0, `created_at` ascending), 2.4 Common Resource Properties, 2.5 Money/Rates/Rounding Discipline, 2.6 OCC (both rules with `expected_return_version` / `expected_poa_version` → `ERR_STALE_VERSION` 412), 2.7 Logical Clock (seeded at `2026-09-01T00:00:00Z`, `to_iso8601`, `current_utc`), 2.8 Validation Ordering (20-priority cascade in prose), 2.9 Referential Integrity
- §3 Business Logic — 8 subsections organized by program lifecycle: 3.1 office/agent/escrow provisioning, 3.2 return preparation/quote/file (credit table, tier multipliers, pinned round-once order, quote-vs-final divergence), 3.3 product sale (premium banding with inclusive-downward cap rule, duplicate/void gates), 3.4 notice intake/pay/abate/withdraw (interest accrual with due-exclusive/paid-inclusive day count, daily rate constant), 3.5 claim intake + info loop + scoping, 3.6 assignment capacity/window rules + POA draft/execute/revoke/lazy-expire, 3.7 resolution waterfall (PREPARER_ERROR vs CLIENT_DATA_ERROR variants, liability fold counting base twice, escrow accrual per-claim rounding, reopen credit-back), 3.8 quality close (400/300 weights, 80/60 thresholds, probation suspension cascade, remediation self-overwrite chain)
- §4 Endpoint table — 54 rows, 4 columns only
- §5 Error catalogue — 27 errors, 2 columns only

**Hard-contract results (all PASS):**
- Contract 1: 57/57 entity fields, 39/39 endpoint input identifiers present in backticks (one miss — `status` — found and repaired in pass 2)
- Contract 2: all 27 error IDs mentioned with trigger conditions in §2/§3 prose; both OCC rules fully expressed; all calculations rendered as precise prose with constants embedded (verified spot checks for credit weights, tier multipliers, premium bases/caps, daily rate, accrual markup, quality weights/thresholds); all state values and enum values present; validation priority ordering stated explicitly
- Contract 3: 364 §3 backtick tokens scanned, zero path/method violations

**Notable prose decisions:** constants translated into words where natural ("four hundredfold", "one tenth markup", "nearest whole dollar"); numeric caps and rates kept as numerals since they are load-bearing constants; unit-conversion trick not applicable here (all constants already in cents); the asymmetric liability fold (base counted twice) stated explicitly; remediation self-overwrite chain narrated step-by-step so the transient `COMPLETED` → `ACTIVE` toggling is reconstructible; DENIED terminality, withdraw-unlinked-only, and pay/abate-on-resolved rejection all placed adjacent to the workflows they guard. The two withheld files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) were never opened.

## Step 5: Generate unit tests — 2026-09-29T22:20:00.000Z

**Files written**

**test_helpers/** (9 files, all under `test_helpers/`):
- `types.py` — entity TypedDicts + status enums (Office, Preparer, Client, TaxReturn, ProtectionProduct, AuthorityNotice, Claim, EnrolledAgent, RepresentationAssignment, PowerOfAttorney, RemediationAction, OfficeEscrow, OfficeQualitySnapshot; all `common_fields: true` so all carry `id/created_at/updated_at/version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (all 40+ paths)
- `api_errors.py` — full `ApiErrorId` enum + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions
- `factories.py` — input-only payload factories with auto-unique names/emails/licenses
- `constants.py` — COMPONENT_CREDITS, TIER_MULTIPLIER, BASE_PREMIUM, caps, quality weights, DAILY_RATE, ACCRUAL_MARKUP, named scoper/resolver operator ids
- `test_users.py` — TEST_USERS constants + `make_client/preparer/enrolled_agent_headers(id)` builders for the three entity-backed roles
- `fixtures.py` — composite helpers: `create_office/preparer/client/agent/escrow/return/product/notice`, `file_return`, `open_claim` (fetches current version for OCC), `scope_claim_in_scope` (as scoper), `assign_agent`, `draft_and_execute_poa`, `pay_notice`, `quality_close`, `resolve_claim` (as resolver, satisfying SoD), `set_clock`, and three scenario composites up to `setup_claim_in_representing`
- `__init__.py` — barrel export of framework + PRD-specific names

**test_suite/** (8 files): `conftest.py` + `test_01_fee_and_premium_calculations.py`, `test_02_claim_lifecycle.py`, `test_03_payouts_and_escrow.py`, `test_04_office_quality_and_remediation.py`, `test_05_representation_and_poa.py`, `test_06_core_api_contracts.py`, `test_07_concurrency_occ.py` — 71 tests total, pytest-collectable with `PYTHONPATH=.

**Coverage verdicts**

- **Queue A (Difficulty): 19/19 instances translated, each with ≥2 tests.** Key adjudications: the two `priority_pair_validation_conflict` instances were split into isolated single-failure tests per instance (per the validation-priority silence pattern) while keeping the pair-contrast as the two ordered checks PRD §2.8/§3.7 explicitly pin; corner `return_create_rejects_empty_components` asserted ERR_INVALID_COMPONENTS (PRD §3.2 verbatim) instead of the recipe's weaker ERR_VALIDATION.
- **Queue B (Corner): 30/30 non-stub instances translated, each with ≥1 test** (no `excluded_because:` stubs exist in this index).
- **Skipped: none.** Every instance passed the PRD-first two-condition filter; all numeric literals (fees 27500/34400/41300/48100; premiums 4900/7350/9900; interest 0/3/323/424/468; payouts 1003/43323/55425; liabilities 2003/40170/81323/105425; accruals 60968/22187/121936) were independently recomputed and match the design indices.
- **Stage-check results:** all tests carry exactly one terminal `Design: Difficulty/...` or `Design: Corner/...` tag resolving to a real instance (0 bad tags, 0 shortfalls); every docstring PRD citation passes a whitespace-normalized verbatim check against PRD.md and contains a literally greppable ≥8-word substring (0 failures); no `skip`/`skipif`/`xfail` markers; no scaffold/Table references in generated code; pyflakes clean; all 71 tests collect under pytest.

## Step 6: Generate implementation — 2026-09-29T22:40:00.000Z

**Files written** (all under `workspace/implementation/`):

- `start.sh` — foreground launcher; guards `pip install` behind `python3 -c "import flask"` so per-test-server reboots don't reinstall; `exec python3 app.py`.
- `requirements.txt` — `flask>=3.0,<4`.
- `app.py` — Flask entry point with all 40 endpoints under `/tax`, error handlers (ApiError, 404/405, generic fallback that never leaks bare 500), route registration, `0.0.0.0:$PORT` (default 10000).
- `db.py` — in-memory dict stores per entity (empty at boot, no seeding), UUID ids, `created_at`/`updated_at`/`version` common fields, the logical clock (defaults to `2026-09-01T00:00:00Z`, settable only via `POST /tax/_clock/set_current_utc`, never falls back to wall-clock), ISO8601 ms-precision formatting, `touch()` mutation hook (updated_at refresh + version bump, applied to cascade targets too).
- `errors.py` — ApiError carrying `error_id`/`message`/`http_status` plus all 27 scaffold error IDs.
- `response.py` — exact envelope: `{meta:{api_request_id: "req_...", api_request_timestamp}, response_type: object|array|error, data}`; list responses add `limit`/`offset`/`total_count`/`has_more` inside `meta`; error body is `{error_id, message}`.
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction (401 `ERR_UNAUTHENTICATED` when missing/invalid role), role-permission checks (403 `ERR_FORBIDDEN`).
- `services.py` — all calculations with `Decimal` arithmetic: `prep_fee_quote`/`prep_fee_final` (sum credits, multiply total by tier multiplier, one round-half-up to nearest 100), `protection_premium` (caps 15000/30000, inclusive-downward banding), `interest_accrual` (days due-exclusive/paid-inclusive, single round of full product at rate 0.000273972602739726), `reimbursement_payout` (PREPARER_ERROR vs CLIENT_DATA_ERROR waterfall, PLUS-only penalty), liability fold `total + base`, per-claim accrual `round_half_up(total * 1.1)`, `office_quality_score` (exact-decimal rates, `round_half_up(100 − 400·defect − 300·claim)`, clamp [0,100]) and posture thresholds (>=80 OK, >=60 WATCH, else PROBATION).

**Architecture**: single-process Flask app over module-level dict stores; business logic centralized in `app.py` route handlers with calculation primitives in `services.py`; every mutation (including cascades — notice link on claim intake, payout recompute on pay/abate, assignment completion and escrow debit on resolve, escrow credit on reopen, preparer remediation_status flips, probation suspension cascade) calls `touch()` so each affected resource gets its own `version` bump and `updated_at` refresh.

**Design choices where the PRD left room**:
- Validation ordering follows scaffold priority numbers: auth → roles → existence (left-to-right) → state/terminal → OCC → business rules → generic `ERR_VALIDATION`. On conflicts (e.g. FILED return PATCH) returns `ERR_ALREADY_TERMINAL` per PRD §3.2 wording; DENIED claim transitions return `ERR_INVALID_STATE` per the scaffold note; RESOLVED claims return `ERR_ALREADY_TERMINAL` except reopen.
- Duplicate agent `license_number` intake is rejected with `ERR_VALIDATION` (400) since the scaffold's error catalog has no dedicated code for it.
- Entity-backed ownership (Client provide-info, Preparer complete, EnrolledAgent abate) compares `X-User-ID` to the owning entity FK and returns 403 on mismatch, per PRD §2.1.
- POA lazy expiry runs on POA reads, claim POA lists, and before claim transition attempts; expiry bumps POA version.
- Quality-close "claims resolved in period" matches claims by office with `resolved_at` (recorded at resolve time from the logical clock) whose `YYYY-MM` equals `period_month`.
- `RemediationAction.status` never stores OVERDUE (derived only), per scaffold constraint.

**Verification**: booted the server on a fresh port and ran a 76-assertion end-to-end smoke script covering auth (401/403), office/preparer/client/return/product/notice/claim/POA/assignment/remediation/escrow lifecycles, quote-vs-final fee divergence (9400 quoted → 11300 final after tier upgrade), interest accrual (137 cents for 5 days on 100000), payout waterfall (120137 total, 220137 liability), escrow accrual (132151), reopen credit-back, SoD (403), posture gating, probation suspension cascade, OCC 412s, duplicate product/email/escrow errors, and pagination envelope — 76 passed, 0 failed. A second fresh boot confirmed the store starts empty (`total_count: 0`).

## Step 7: Run tests and iterate — 2026-09-29T23:05:00.000Z

All 8 rounds pass 70/70. Clean sweep achieved.

- **Iterations run**: 3 sweeps (baseline → after first fix batch → after version-line fix). Final: all 8 rounds at 70/70.

- **Tests deleted** (1):
  - `test_intake_on_preparing_return_rejected` (`test_suite/test_02_claim_lifecycle.py::TestClaimIntakeRequiresProtection`) — unconstructible precondition. PRD §3.5 does cover "the return must be FILED" → ERR_PROTECTION_REQUIRED, but the test's setup requires registering an authority notice against a PREPARING return, which PRD §3.4 forbids ("registers an authority notice against a FILED return"). Since a notice can only ever sit on a FILED return, the "PREPARING return with an OPEN notice" state is unreachable via PRD-declared endpoints, so the §3.5 FILED-prerequisite cannot be exercised faithfully. Scaffold driver: Corner/validations/claim_intake_requires_protection.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `implementation/`** (both in `workspace/implementation/app.py`):
  - `execute_poa()` — reordered validation so the POA state precondition (priority 4 per PRD §2.8) runs before the POA business rules: if the claim has no DRAFT POA but carries a POA in a terminal state (REVOKED/EXPIRED, e.g. a directly revoked draft), execution now yields `ERR_INVALID_STATE` instead of `ERR_POA_NOT_DRAFT`. When a DRAFT exists, OCC against the current draft's version runs as before, so an attested version from a superseded draft yields `ERR_STALE_VERSION` per PRD §2.6 ("a newer draft… supersedes the prior one, so executing against a stale draft view is likewise rejected with ERR_STALE_VERSION"). The claim-absence error `ERR_POA_NOT_DRAFT` is preserved for claims that never had a POA.
  - `draft_poa()` — a superseding draft now continues the claim's draft-POA version line (`version = superseded.version + 1`) instead of starting at 1. PRD §2.6 requires that executing with a pre-supersede version be detected as stale; with both drafts at version 1 the OCC was vacuous and stale executes incorrectly succeeded.

## Step 8: Finalize PRD — 2026-09-29T23:12:00.000Z

**File produced:** `workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 279 lines, PRD_FINALIZED.md 279 lines (0% delta — 3 lines revised in place, no lines added/removed).

**Changes (one bullet each):**
- §2.6 — revise — "the claim's draft POA" → "the claim's current `DRAFT` POA" to pin that the OCC attestation targets the currently-draft POA, not a superseded/revoked one — `implementation/app.py:1262-1264` (execute_poa OCC against the located DRAFT).
- §2.4 — revise — `version` rule scoped with "(except where a per-entity rule states otherwise, see §3.6)" to avoid a false universal claim, since POA drafts are the one exception — `implementation/db.py:81-88` (default 1) vs `implementation/app.py:1215-1220` (override).
- §3.6 — revise — added that a superseding draft continues the claim's draft-POA version line (`version = superseded.version + 1`) rather than restarting at 1, and re-pinned the execute precondition: no DRAFT but a POA in REVOKED/EXPIRED → `ERR_INVALID_STATE`; only a claim that never had a POA → `ERR_POA_NOT_DRAFT` — `implementation/app.py:1200-1220` (draft_poa supersede/version continuation) and `app.py:1242-1261` (execute_poa state-precondition reorder).

**Deleted-test item:** `test_intake_on_preparing_return_rejected` required no PRD edit — PRD §3.5 already pins the FILED prerequisite as `ERR_PROTECTION_REQUIRED` and the impl matches (`app.py:982-989`); the deletion was an unconstructible precondition (§3.4 only registers notices on FILED returns), not PRD silence.

**Pre-edit search logs** recorded inline per edit (subject, enumerated impl paths including `draft_poa`/`execute_poa`/`revoke_poa`/`lazy_expire_poas`/all `base_record` sites, wording adjustments — notably scoping the §3.6 sentence to the REVOKED/EXPIRED case so `ERR_POA_NOT_DRAFT` is preserved for never-had-POA claims, and verifying the `("REVOKED", "EXPIRED")` wording matches both the execute check and the fact that lazy expiry only ever moves EXECUTED POAs to EXPIRED).

## Step 9: Complete PRD — 2026-09-29T23:25:00.000Z

**File produced:** `workspace/PRD_COMPLETED.md`

**Source vs output:** PRD_FINALIZED.md 279 lines / 42,637 chars → PRD_COMPLETED.md 279 lines / 46,038 chars (+3,401 chars, 0 line-delta — all edits are in-paragraph).

**Counts:** 21 ambiguity-pins, 2 mismatch-revisions (23 edited passages total). Implementation's own test suite: 70/70 passing (results.8.json), so impl is a stable alignment target.

**Changes:**
- §1 — insert — ambiguity — store starts empty on every boot, no seeding — db.py:3-4
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` or negative `offset` → `ERR_VALIDATION` — app.py:106-117
- §2.3 — insert — ambiguity — list sort tie-break by ascending `id` — app.py:123-124
- §2.4 — insert — ambiguity — pinned per-entity `status` enumerations and terminal markers — app.py:62-65,655,781,855,996,1178,1213,1290,1404,1485
- §3.1 — revise — mismatch — duplicate agent `license_number` refused with `ERR_VALIDATION` (400), not the vague "duplicate rejected at intake" — app.py:1428-1430
- §3.2 — insert — ambiguity — `tax_year` must be an integer — app.py:637-638
- §3.2 — insert — ambiguity — AMENDED `original_return_id` nonexistent → `ERR_NOT_FOUND`; ORIGINAL ignores and nulls any supplied `original_return_id` — app.py:619-621,654
- §3.2 — insert — ambiguity — no-change PATCH is a no-op: no re-quote, no `updated_at`/`version` bump — app.py:712-723
- §3.2 — insert — ambiguity — filing under non-`ACTIVE` preparer → `ERR_INVALID_STATE`; original re-validated at filing time — app.py:739-742
- §3.3 — insert — ambiguity — duplicate-product gate fires before eligibility re-check — app.py:768-775
- §3.3 — insert — ambiguity — premium rounded half-up to cents in all three bands (identity for integral bases) — services.py:63-72
- §3.3 — insert — ambiguity — `RESOLVED`/`DENIED` claims do not block void; re-void of `VOID` product → `ERR_ALREADY_TERMINAL` — app.py:792-799
- §3.4 — insert — ambiguity — notice against non-`FILED` return → `ERR_INVALID_STATE` — app.py:831-832
- §3.4 — insert — ambiguity — `interest_cents` stored as 0 (never null) on payment; day count truncates sub-day remainder — services.py:77-79
- §3.5 — insert — ambiguity — claim terminal lockdown pinned per terminal state: `DENIED` → `ERR_INVALID_STATE`, `RESOLVED` → `ERR_ALREADY_TERMINAL` (except assignment cancel, always `ERR_INVALID_STATE`) — app.py:1068-1071,1136-1139,1403-1409
- §3.6 — insert — ambiguity — existing `ACTIVE` assignment blocks re-assignment with `ERR_INVALID_STATE`; window-order check precedes capacity/overlap — app.py:1148-1153
- §3.6 — insert — ambiguity — POA drafting requires only claim not `DENIED`/`RESOLVED`; agent-mismatch at execution → `ERR_INVALID_STATE` — app.py:1192-1195,1274-1275
- §3.6 — insert — ambiguity — POA valid at exact `expires_at` instant (strictly-after expiry); lazy expiry bumps POA version — app.py:134-142,1266
- §3.7 — insert — ambiguity — reopen of non-`RESOLVED` claim → `ERR_INVALID_STATE` — app.py:1383-1384
- §3.8 — insert — ambiguity — malformed `period_month` → `ERR_VALIDATION` — app.py:411-412
- §3.8 — insert — ambiguity — "claims resolved in period" = resolution instant's calendar month matches `period_month` — app.py:424-431,1356
- §3.8 — revise — mismatch — every close bumps office `version` and `last_close_period` even when posture is unchanged (PRD said only closes that change posture) — app.py:450-452
- §3.8 — insert — ambiguity — already-`SUSPENDED` preparers take no extra bump from probation cascade — app.py:464-466
- §3.8 — insert — ambiguity — remediation-replacement touches the preparer once (single version bump) — app.py:1475-1489
- §4 — insert — ambiguity — quality-close returns 201 with the created snapshot — app.py:469

No remaining PRD silence or mismatch against `implementation/` was found in the walk.
