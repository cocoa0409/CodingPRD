# Worklog — task_3374_membership_advocacy_benefit_licensing_royalties_chapter_programs

## Step 1: Create Task Directory — 2026-10-01T10:36:00.000Z

Task directory pre-allocated by the caller at `tasks/task_3374_membership_advocacy_benefit_licensing_royalties_chapter_programs/` with `workspace/` inside; verified it exists and is empty. No new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-01T11:47:00.000Z

All three scaffold artifacts are written and verified. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3374_membership_advocacy_benefit_licensing_royalties_chapter_programs/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (76 KB)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (66 KB)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (85 KB)

**Design shape** (compliance_audit primary + pricing_engine secondary; flat topology; segregation-of-duties role model):
- **40 endpoints** (held exactly at the impl-gen safety ceiling; depth was added per-endpoint instead — merged action endpoints, sub-resource reads, one atomic approve-executes transfer)
- **15 entities**: Household, Member, MembershipTerm, Provider, LicenseAgreement, RoyaltyStatement, Complaint, LegalEntity, FundTransfer, Publication, AdBooking, Chapter, CourseSession, Campaign, MobilizationEvent
- **9 state-machine entries** with two cyclic machines (LicenseAgreement ACTIVE⇄PROBATION, Provider LICENSED⇄SUSPENDED), branching machines (Complaint, RoyaltyStatement, FundTransfer), and clock-derived lazy machines (Campaign, CourseSession, Household standing)
- **10 calculations**: dual-variant royalty tiers (provisional vs audited-final with late-binding re-baseline), dual-variant refund (short-rate 133/mo clawback vs pro-rata effective-monthly — 3921 vs 3960 on identical inputs), nested-min discount-cap pricing (5yr renewal hits the 0.25 cap exactly → 6000), escalation thresholds (>=3 / >=5 over inclusive 365-day trailing windows), governance direction matrix with per-transfer/annual caps, half-open circulation dedupe, round-half-up ad cost, snapshot audience count, two-semantics session overlap (30-min room buffer vs instructor half-open adjacency)
- **12 prioritized validation rules** spanning auth → ownership → SoD → schema → existence → OCC → state → cross-entity state → safety → constraint → fiscal
- **36 error codes**, all wired to validations/transitions
- **2 OCC concurrency rules** (agreement-create on Provider.version; statement-submit supersede on LicenseAgreement.version)
- **10 roles** (3 entity-backed: Member, ProviderManager, ChapterCoordinator)

**Design indexes**: 18 difficulty instances (exactly 2 per rule, all §0.5 differentiation clauses honored — different domains, modes, entities, triggers, category pairs, metrics, pairs, interval semantics, conserved quantities) + 41 full corner instances across all 9 guide sections + 6 `excluded_because` stubs citing valid difficulty instances.

**Verification performed myself**: `scaffold_lint.py` verdict — `VERDICT: clean lint` (40 endpoints, 15 entities, 18+41 instances, 395 calls scanned); YAML anchors/JSONPath quoting fixed after parse failures; a custom audit confirmed zero unbound `${var}` placeholders, global name uniqueness (65 names), all stub citations resolve, all `grounds:` resolve to declared §1.1–§1.7 elements, no forbidden race vocabulary, and every formula-derived assert literal was recomputed in Python (pricing, refunds, royalty tiers incl. the 8,000,000/10 tier-cap boundary, transfer caps, ad estimate 7.5→8) — all match the pinned values.

Orchestrator note: verified all three files exist on disk (SCAFFOLD.yaml 76,022 B; SCAFFOLD_CORNER_DESIGN.yaml 84,912 B; SCAFFOLD_DIFFICULTY_DESIGN.yaml 66,126 B); endpoint grep confirms 40 paths.

## Step 3: Copy Shared Files — 2026-10-01T11:51:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1,424 B).

## Step 4: Generate PRD — 2026-10-01T12:13:00.000Z

All audits pass. The PRD is complete and verified against the scaffold.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_3374_membership_advocacy_benefit_licensing_royalties_chapter_programs/workspace/PRD.md` — 322 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (all 10 roles + per-role identity prose), 2.2 API Response Structure (**byte-identical verbatim block confirmed** against `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Logical Clock & Time-Derived State, 2.5 Common Resource Properties, 2.6 Money/Integer Cents/Rounding Discipline, 2.7 OCC, 2.8 Validation Pipeline & Error Precedence (12-rung ordered ladder), 2.9 Nested Resource Retrieval, 2.10 Segregation of Duties, 2.11 Member Data Usage Restrictions
- §3 Business Logic (9 subsections): enrollment/pricing, renewal/lapse/cancellation/standing, provider & agreement lifecycle, royalty reporting/settlement, complaints & escalation cascade, legal entities & fund movement, publications/advertising, chapters/sessions/enrollment, campaigns/mobilization
- §4 Endpoint Definitions: 40-row table, row-precise match on method + path + role list
- §5 Error Code Catalogue: 36 rows, exact id + HTTP status match

**Hard Contract reports:**
- **Contract 1 (Field-Name Coverage): PASS** — 88/88 entity fields, 59/59 endpoint inputs, 7/7 query params, path params, all 5 `audience_spec` keys (incl. the 3 forbidden benefit-marketing keys), all roles, all 54 enum/state values, all 36 error ids present as backticked tokens (verified mechanically with fenced-code-block stripping; two initial gaps, `chapter_id` and `OPEN_REVIEW`, were found and repaired, then re-verified).
- **Contract 2 (Rule Coverage): PASS** — 12-rung validation ordering stated explicitly; both OCC rules name write endpoint + `expected_*_version` field + exact error id + 412, framed purely in stale-version terms; all state transitions expressed with from→to pairs (sibling symmetry preserved: TERMINATE from 3 states, RESOLVE from 2, admit from 2); all 10 calculations with constants and pinned rounding; escalation cascade's 3 links with version bumps; supersede reversal postings; finalize's dual version increments.
- **Contract 3 (§3 Path Purity): PASS** — 501 backticked tokens in §3 scanned: 0 paths, 0 bare HTTP methods, 0 method+path combos.

**Zero-Silence audit — constant categories verified pinned in prose:** pricing (1,600¢ base, 0/10/20% multi-year, +5pp loyalty, 25% cap, worked examples 6,400/6,000), refunds (133¢ monthly basis, months-used formula incl. the +1 cancellation month, pinned round-basis-first order with the 1,197-vs-1,200 worked example), royalty tiers (100,000,000/500,000,000¢ at 8/10/12%, chronological quarter order, late-binding, SUPERSEDED exclusion, 10,000,000¢ worked example), escalation thresholds (3 / 5 / 365-day inclusive window, only-`ESCALATED` counts), governance caps (5% per-transfer, 15% foundation annual, 20% lobbying dues, round-down before compare, exactly-at-cap passes, pinned balance→per-transfer→annual order), scheduling (30-minute room buffer with the 11:00/11:30 boundary example, instructor half-open adjacency), eligibility (age ≥ 50, exact 50th birthday eligible, `term_years` ∈ {1,3,5}, quarter 1–4, `amount_cents` ≥ 1, `capacity` ≥ 1, capacity-th enrollment succeeds), defaults (clock exactly `2026-09-01T00:00:00Z` with no wall-clock fallback, pagination limit 10/min 1/max 100/offset 0, `auto_renew_enabled` false, opt-out flags false, `refunded_cents` 0, null-until-set fields), and interval semantics (half-open term coverage, inclusive campaign/agreement windows, strict future `start_time`, `HELD` at clock ≥ `end_time`).

Orchestrator note: verified `workspace/PRD.md` on disk — 322 lines, 59,284 B.

## Step 5: Generate Unit Tests — 2026-10-01T13:05:00.000Z

Generation complete. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3374_membership_advocacy_benefit_licensing_royalties_chapter_programs/`)
- `test_helpers/` — `__init__.py` (barrel), `types.py` (15 TypedDicts + 17 enums), `api_client.py` (42 endpoint methods, one per PRD endpoint), `api_errors.py` (36 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity shape assertions + royalty-exposure and balance-conservation invariants), `factories.py` (13 payload factories, input fields only), `constants.py` (19 PRD-derived constants), `test_users.py` (10 roles; per-instance `make_*_headers` builders for the three entity-backed roles Member/ProviderManager/ChapterCoordinator), `fixtures.py` (composite setups: licensed provider, active agreement, multi-statement scenarios, 5-escalation suspended provider, renewal cascade, legal entities, campaigns, sessions).
- `test_suite/` — `conftest.py` + 11 test files organized by domain concern.

**Test counts**
- Queue A (Difficulty): 18/18 instances, exactly 2 tests each = **36 tests**
- Queue B (Corner): 40/41 non-stub instances, 1 test each = **40 tests**; total **76 tests**
- 6 `excluded_because` stubs not translated; all 6 cross-references resolve to real difficulty instances.

**Skipped instances (1)**
- `Corner/entities/household_create_status_input_ignored` — fails unique derivability: the PRD never states whether a client-supplied computed field (`status: LAPSED` in a create payload) is ignored or rejected; a strict-schema implementer would 400 while another would ignore-and-201. Left as a gap, no placeholder emitted.

**Verification results**
- `pytest --collect-only` (PYTHONPATH=task dir): **76 tests collected, 0 errors** — package graph sound, no dangling imports.
- PRD citation sweep: 131 rule-bearing quotes (≥8 words) extracted from docstrings; **all 131 survive whitespace-normalized literal grep of PRD.md** (6 elided quotes were caught and rewritten to full sentences during the pass).
- Design-tag audit: every test has exactly one terminal `Design:` line; all 76 tags resolve to real instances; no stub tags, no unknown tags, no dual tags.
- Constants-vs-PRD diff: **19/19 match** (1600 base, 0/10/20% discounts, +5pp loyalty, 25% cap, 133 monthly basis, 100M/500M tiers at 8/10/12%, thresholds 3/5, 365-day window, 5/15/20% caps, 30-min buffer, age 50, clock 2026-09-01T00:00:00Z).
- Every create-path `validate_success` pins `expected_status=201` (balanced-paren audit); action endpoints use the 200 default.
- Fixture dates all consistent with the pinned clock start; the 365-day inclusive-boundary case verified arithmetically (2026-09-01 + 365d = 2027-09-01 exactly, no leap day in the span).

Orchestrator note: independently verified on disk — all 9 test_helpers files + conftest.py + 11 test files present; `pytest --collect-only -q` from the task dir returns **76 tests collected in 0.22s, 0 errors**.

## Step 6: Generate Implementation — 2026-10-01T13:27:00.000Z

Implementation complete. Summary:

## Files written (16) in `tasks/task_3374_membership_advocacy_benefit_licensing_royalties_chapter_programs/workspace/implementation/`

- `start.sh` — exec-based foreground launcher, binds `0.0.0.0:$PORT` (default 10000), guarded `pip install` (no-op once Flask is importable, so per-test reboots never re-install)
- `requirements.txt`, `app.py` (blueprint registration + envelope-shaped 404/405/500 handlers)
- `db.py` — in-memory dict store (starts empty, no seeding), logical clock defaulting to exactly `2026-09-01T00:00:00Z`, `mint`/`touch` (version starts at 1, +1 per mutation), `locked` decorator
- `util.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, pagination fields `limit`/`offset`/`total_count`/`has_more`), Decimal rounding (half-up for money, round-down for caps), strict date / lenient datetime parsers
- `auth.py` — `X-User-ID`/`X-User-Role` validation, 10 declared roles
- `services.py` — all PRD-pinned constants and calculations: tiered pricing (1600 base, 0/10/20% + 5% loyalty, 25% cap), cancel refunds (pinned per-month rounding order; verified 1197-cent DECEASED example), marginal royalty tiers (100M@8% / 500M@10% / 12%), trailing-365-day escalation counts (thresholds 3/5, inclusive bound), governance direction matrix + caps (5% per-transfer / 15% annual foundation / 20% lobbying-of-dues, truncated), circulation, room-buffer vs instructor half-open overlap, audience snapshot
- `serializers.py` — lazy derived fields recomputed on every read (household status, member standing/age, campaign/session status, circulation, trailing counts, royalty exposure)
- 8 route modules covering all resource groups

## Endpoint count: 40 — matches the PRD §4 table exactly

## Boot verification (ran `bash start.sh` on a private port, curled, killed the exact listener PID)
Verified live: auth 401/403 ordering; age-before-term-length precedence; 5-year pricing = 6400; renewal batch (renewed household stays ACTIVE, collected 3120 = 1600+1520; non-renewed LAPSED); OCC 412s on both guarded writes; royalty math matches the PRD example (120M → 10,000,000 provisional; finalize at 100M → delta −2,000,000; bucket conservation recognized/outstanding/exposure); supersede reverses postings and bumps agreement version twice; complaint cascade (agreement PROBATION at 3, provider SUSPENDED at 5, conditional sibling probation, reinstate/re-admit gating with `ERR_REINSTATE_BLOCKED`); transfer SoD, direction matrix, pinned fiscal order (exactly-at-cap passes); ad standards → rate card → circulation ordering; room 30-minute buffer vs instructor case-sensitive adjacency; enrollment gate order (timing → standing → duplicate → capacity); campaign sponsor-kind, state_code conditionality, and audience snapshots frozen across clock moves. Dead-code audit: all 17 service helpers have real callsites; all 36 catalog error IDs are emitted; no seeding, no disk persistence.

One judgment call worth flagging: `purchased_at`/`filed_at`/`escalated_at`/`cancelled_at`/`executed_at` echo the clock's raw set string (per PRD's "echoes the new reading" semantics), while `created_at`/`updated_at` use the PRD-pinned three-fractional-digit format.

Orchestrator note: verified on disk — 16 files in `workspace/implementation/` including executable `start.sh`; app.py + 8 route modules + services/serializers/db/util/auth all present with non-trivial sizes.

## Step 7: Run Tests and Iterate — 2026-10-01T13:37:00.000Z

Clean 8-round sweep achieved: 76/76 passed in every round. Final sweep evidence preserved.

## Summary

- **Iterations run:** 2 (first sweep surfaced 7 stable failures; fix applied; second sweep fully green).

- **Tests deleted:** none.

- **Fixes applied to test artifacts (both STEP 2 — test bug, out-of-scope fixture name):**
  - `/home/ubuntu/github/CodingPRD/tasks/task_3374_membership_advocacy_benefit_licensing_royalties_chapter_programs/test_suite/test_03_renewal_cancellation_standing.py` — module-level helper `_run_batch()` referenced `api` (a pytest fixture only injected as a test-method parameter), raising `NameError` in all 5 tests of `TestRenewalPricingDiscountCap`, `TestRenewalBatchCascade`, and `TestRenewalSweepNoop`. Changed `api.run_renewal_batch(ADMIN)` → `api_client.run_renewal_batch(ADMIN)` (`api_client` was already imported; the conftest `api` fixture returns exactly this object, so the fix is behavior-neutral).
  - `/home/ubuntu/github/CodingPRD/tasks/task_3374_membership_advocacy_benefit_licensing_royalties_chapter_programs/test_suite/test_06_complaints_escalation.py` — instance helper `TestEscalatePriorityPair._setup_resolved_complaint_terminated_agreement` referenced `api.get_complaint` / `api.transition_agreement` without receiving the fixture, raising `NameError` in both class tests. Changed to `api_client.get_complaint` / `api_client.transition_agreement`.

- **Fixes applied to `implementation/`:** none — once the NameError masking was removed, all 7 previously failing tests passed against the unmodified implementation (the asserted rules — renewal pricing cap 6000/4080, batch cascade renewed/lapsed tallies, no-op sweep before `end_date`, `ERR_COMPLAINT_STATE` precedence and no-side-effect-on-failure — were already correctly implemented).

- **Flakiness:** none observed — failures were identical across all 8 rounds of both sweeps.

Orchestrator verification (independent): all 8 `results.{1..8}.json` present, each `total=76 passed=76 failed=0 errors=0`; spot-checked both claimed fixes in source (`api_client.run_renewal_batch` at test_03:16, `api_client.get_complaint`/`transition_agreement` at test_06:187/190); grep confirms zero `pytest.mark.skip`/`xfail`/`pytest.skip`/`pytest.xfail` in test_suite/ and test_helpers/.

## Step 8: Finalize PRD — 2026-10-01T13:45:00.000Z

Verification complete. Here is the summary.

## Result: zero edits — PRD_FINALIZED.md is byte-identical to PRD.md

**Line counts / delta:** PRD.md 322 lines, PRD_FINALIZED.md 322 lines, 0% delta. `diff -q` reports identical; md5 `27d7884527b69f4972fa227088223d14` for both. The `diff -q` / md5 check (not just `cp` mtime) confirms no silent no-op or truncation.

**Why zero edits is correct here.** Both Step 7 fixes were pure Python scoping bugs in test artifacts: module-level/helper-level code referenced `api`, a function-scoped pytest fixture, raising NameError before any assertion ran. Changing `api.*` → `api_client.*` is behavior-neutral (conftest's `api` returns exactly `api_client`). Neither fix carries any PRD-silence or PRD-mismatch signal. Per the mandated verification, I examined every behavior the fixed tests assert against the implementation and confirmed PRD.md already pins each one uniquely:

1. **Renewal pricing cap (6000/4080)** — impl `services.py:70-76` (`price_term_cents`: base 1600, discounts {1:0, 3:0.10, 5:0.20}, loyalty +0.05, `min(0.25, …)`, round-half-up once). PRD §3.1 (line 161) pins every element, literally states "a five-year renewal costs 6,000 cents," and the 3-year case follows uniquely: 10%+5%=15% < 25% cap, 1600×3×0.85 = 4080. Callsites enumerated: `routes_households.py:72` (enrollment, `is_renewal=False`) and `routes_admin.py:52` (batch, `True`) — both consistent with §3.1.
2. **Batch cascade renewed/lapsed tallies** — impl `routes_admin.py:34-85`. PRD §3.2 (line 169) pins the visit set ("`end_date` on or before the current clock date"), the RENEWED/LAPSED split by `auto_renew_enabled`, successor-term fields (`is_renewal`, start = old end_date, end = +term_years, loyalty pricing, `lifetime_collected_cents` growth), the standing recompute, and the exact four tally keys `renewed_count`/`lapsed_count`/`renewed_term_ids`/`lapsed_term_ids`.
3. **No-op sweep before end_date** — impl `routes_admin.py:42` filters `end_date <= today`; empty visit set yields zero counts and no mutations (household version untouched). Uniquely determined by §3.2's "on or before" window.
4. **ERR_COMPLAINT_STATE precedence** — impl `routes_complaints.py:125-129` checks complaint status (→ `ERR_COMPLAINT_STATE`) before agreement status (→ `ERR_AGREEMENT_STATE`). PRD §2.8's ordered twelve-rung pipeline (rung 8 target-resource state before rung 9 cross-entity state; "rejected with the error from the earliest rung it fails") plus §3.5's unconditional "acting on a `RESOLVED` complaint at all — is rejected with `ERR_COMPLAINT_STATE`" doubly pin this.
5. **No-side-effect-on-failure** — impl `err()` raises before any write in `adjudicate_complaint`; failed ESCALATE leaves status `RESOLVED`, `escalated_at` null. Pinned by §3.5 rejection semantics and §2.8's reject-at-the-rung pipeline. Escalation cascade callsites enumerated: `run_escalation_cascade` (`services.py:199-226`) is called only from `routes_complaints.py:134`, after the state gate.

**Changes:** none.

**Per-edit pre-edit search log:** no edits were committed, so no per-edit entries exist; the pre-commit path enumeration was instead applied to each candidate behavior above (subjects, impl paths read: `services.py` in full, `routes_admin.py` in full, `routes_complaints.py` in full, `routes_households.py:40-110`, plus a callsite grep for `price_term_cents`/`run_renewal_batch`), and every one concluded "PRD already pins; keep prose verbatim."

Deliverable: `/home/ubuntu/github/CodingPRD/tasks/task_3374_membership_advocacy_benefit_licensing_royalties_chapter_programs/workspace/PRD_FINALIZED.md` (byte-identical copy of PRD.md).

Orchestrator verification (independent): `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → IDENTICAL; mtime audit confirms no `implementation/` or test-artifact source files modified after the final 13:37 sweep, so the sweep evidence remains valid.

## Step 9: Complete PRD — 2026-10-01T14:05:00.000Z

All edits verified on disk. The task is complete — here is the summary.

## Step 9 Summary — task_3374 PRD_COMPLETED.md

**Source vs output:** `workspace/PRD_FINALIZED.md` (322 lines / 59,284 chars) → `workspace/PRD_COMPLETED.md` (327 lines / 62,902 chars). Delta: +5 lines / +3,618 chars, 19 diff hunks. `diff -q` run: files differ as expected; all 19 intended edits confirmed present on disk (two edits to the §3.4 royalty paragraph share one source line and merge into a single hunk).

**Counts:** 16 ambiguity-pins, 3 mismatch-revisions (19 edits total; one edit covers two §2.3 clauses, one covers three §2.5 items).

**Per-change bullets** (`{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

1. §2.2 — insert — ambiguity — `api_request_timestamp` is wall-clock request metadata, never read by business rules — implementation/util.py:38-47
2. §2.2 — insert — mismatch — framework-level rejections: undefined path → `ERR_NOT_FOUND` 404; unsupported method on a defined path → `ERR_NOT_FOUND` with HTTP 405 (contradicts the catalogue's 404 pin); unexpected fault → `ERR_INTERNAL` 500 — implementation/app.py:42-56
3. §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped into bounds, unparseable values fall back to defaults — implementation/util.py:85-98
4. §2.3 — insert — ambiguity — creation-timestamp ties broken by insertion order (`_seq`) — implementation/db.py:57
5. §2.4 — revise — ambiguity — clock-set parses lenient ISO 8601 (trailing Z, offsets, fractional seconds, naive-as-UTC) and echoes the raw supplied string verbatim as `current_utc` — implementation/routes_admin.py:16-29, util.py:137-153
6. §2.5 — revise — ambiguity — `created_at`/`updated_at` are stamped from the *logical* clock in three-fractional-digit form — implementation/db.py:54-55, 63-66
7. §2.5 — revise — ambiguity — `version` starts at 1 on creation — implementation/db.py:56
8. §2.5 — insert — ambiguity — event stamps (`purchased_at`, `cancelled_at`, `filed_at`, `escalated_at`, `executed_at`) echo the clock's raw set string verbatim, not the normalized form — implementation/routes_households.py:117,182; routes_admin.py:61; routes_complaints.py:63,132; routes_governance.py:144
9. §2.8 rung 5 — revise — ambiguity — date-typed fields accept only bare `YYYY-MM-DD`; datetime strings are malformed there — implementation/util.py:125-134
10. §3.1 — insert — ambiguity — advancing a Feb 29 start by whole years lands on Feb 28 in non-leap target years — implementation/services.py:62-67
11. §3.2 — revise — ambiguity — renewal sweep processes expiring terms in creation order, never revisits terms it created, and renewal terms stamp `purchased_at` from the clock — implementation/routes_admin.py:39-43, 61
12. §3.3 — insert — ambiguity — admitting an already-`LICENSED` provider is an idempotent no-op (200, no version/`updated_at` change) — implementation/routes_providers.py:80-90
13. §3.4 — insert — ambiguity — `period_year` accepts any integer; only `period_quarter` is range-checked — implementation/routes_providers.py:260-263
14. §3.4 — insert — ambiguity — "chronological quarter order" describes the computation, not a submission constraint; out-of-order submissions are accepted with the YTD base read at computation time — implementation/services.py:124-138
15. §3.4 — insert — ambiguity — statement submission increments the provider's `version` (+1 fresh, +2 on supersede: reversal + new posting) — implementation/routes_providers.py:291-317
16. §3.5 — insert — ambiguity — `resolution_code` supplied on non-RESOLVE actions is accepted and ignored — implementation/routes_complaints.py:106-108, 122-123
17. §3.6 — insert — ambiguity — the direction matrix is evaluated at decision time, not request time; a prohibited pair is accepted into `PENDING_APPROVAL` and rejected on approval — implementation/routes_governance.py:50-82 vs 130-135
18. §3.6 — insert — ambiguity — a failed approval (direction/fiscal rejection) leaves the transfer `PENDING_APPROVAL` with `decided_by_user_id` already populated and `version` unchanged — implementation/routes_governance.py:121-137
19. §3.8 — revise — mismatch — "two-letter `state_code`" was descriptive; the chapter's `state_code` is an opaque string with no length validation — implementation/routes_chapters.py:32
20. §3.9 — revise — ambiguity — the campaign listing's `status` filter matches the derived `computed_status` — implementation/routes_campaigns.py:96
21. §3.9 — insert — ambiguity — `audience_spec` allowed-key values are type-checked (`state_code` string, `min_age` integer) or `ERR_INVALID_REQUEST` — implementation/routes_campaigns.py:117-120
22. §5 — insert — mismatch — added `ERR_INTERNAL` (500) row so the catalogue's "every error identifier" claim holds — implementation/app.py:52-56

**Dead-code cross-check:** every PRD-required check helper has a verified live callsite — `direction_permitted` (routes_governance.py:133), `check_fiscal_rules` (:137), `run_escalation_cascade` (routes_complaints.py:134), `agreement_trailing_count` (routes_providers.py:231 + serializers.py:70 + cascade services.py:208), `provider_trailing_count` (routes_providers.py:86 + serializers.py:58), `room_conflict`/`instructor_conflict` (routes_chapters.py:79,81), `circulation_count` (routes_publications.py:77 + serializers.py:119), `audience_count` (routes_campaigns.py:132), `member_in_good_standing` (routes_complaints.py:48, routes_chapters.py:136), `compute_age_years` (routes_households.py:63), `price_term_cents` (routes_admin.py:52, routes_households.py:72), `cancel_refund_cents` (routes_households.py:179), `compute_royalty_cents` (routes_providers.py:299,354), `campaign_status` (routes_campaigns.py:96,126), `session_status` (serializers.py:148). One genuinely unused helper exists — `services.household_terms` — but it is not a PRD-required check (the terms listing implements the identical query inline at routes_households.py:157-160), so it creates no behavioral gap; noted here per the flag-don't-fix rule.

**Verification:** `diff -q` was run post-edit (files differ, exit 1); the 19-hunk diff was inspected hunk-by-hunk against the intended edit list and the merged §3.4 paragraph was re-read from disk to confirm both insertions landed. Only `workspace/PRD_COMPLETED.md` was written; `implementation/`, `test_helpers/`, and `test_suite/` were not touched.

Orchestrator verification (independent): `wc` confirms 322/59,284 → 327/62,902 exactly as reported; diff shows 43 changed lines; mtime audit confirms no `implementation/` or test-artifact files modified after the final 13:37 sweep — sweep evidence remains valid.

## Pipeline Complete — 2026-10-01T14:06:00.000Z

All 9 steps done. Final state: SCAFFOLD.yaml + both design indices; PRD.md (322 lines) → PRD_FINALIZED.md (byte-identical) → PRD_COMPLETED.md (327 lines, 19 pins); test_helpers/ + test_suite/ (76 tests, 36 Difficulty + 40 Corner, 1 corner instance skipped for unique-derivability); implementation/ (16 files, 40 endpoints); final 8-round stability sweep 76/76 × 8, evidence preserved in `workspace/implementation/results.{1..8}.json`.
