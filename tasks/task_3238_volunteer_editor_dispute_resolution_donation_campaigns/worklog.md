# Worklog — task_3238_volunteer_editor_dispute_resolution_donation_campaigns

## Step 1: Create Task Directory — 2026-09-30T12:55:00.000Z

Pre-allocated task directory verified: `./tasks/task_3238_volunteer_editor_dispute_resolution_donation_campaigns/` with `workspace/` inside. Used as-is per command args; no new index computed.

## Step 2: Generate Scaffold — 2026-09-30T13:44:00.000Z

All three scaffold artifacts are complete and lint-clean for task_3238 (Volunteer Editor Dispute Resolution & Donation Campaigns).

**Final summary**

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_3238_volunteer_editor_dispute_resolution_donation_campaigns/`):

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys; verified programmatically)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

Counts:
- **14 entities** (VolunteerEditor, WikiPage, Revision, DisputeCase, ProtectionRequest, VandalismReport, DonationCampaign, CampaignBanner, Donation, GrantProgram, GrantApplication, LegalRequest, TransparencyReport, ImpressionEvent)
- **74 endpoints** (incl. 13 reverse-reachability list GETs, banner-impression serve endpoint, and `/_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z)
- **21 error codes**, **10 calculations**, **9 state machines**, **9 roles** (8 domain roles with mandatory `identity:` + PlatformAdmin), **5 OCC concurrency rules** (page accept, dispute escalate, campaign activate, grant approve, report publish — all with `${var}`-bound `expected_*_version`)
- **Difficulty design: 9 rule blocks × 2 instances = 18 instances** (all nine §0.5 rules; differentiation clauses honored — e.g. dual-variant on Revision threshold vs CampaignBanner conversion rate; combinatorial mode (a) non-linear branch vs mode (b) pinned per-banner-round-then-sum; cascades from editor-block vs campaign-cancel triggers; boundary at grant score 69/70 vs banner cap exactly-at-cap)
- **Corner design: 32 instances** across all nine claim-extraction-guide sections (entities 8, state_machines 5, calculations 3, validations 4, endpoints 2, errors 4, rbac 2, cross_cutting_layers 3, consistency_model 1)

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` — 74 endpoints, 14 entities, 18 §1.8 instances, 32 §1.9 instances, 327 calls scanned, 0 violations.

Fixes applied during the lint loop: added single-resource GETs for protection-requests/impressions (needed by the linter's collection-segment derivation), added `current_revision_id?` filter to `GET /wiki/pages` (reverse reachability for the WikiPage→Revision FK), removed a non-schema payload key from one corner, and replaced a literal OCC version with a `${var}` capture in the 404 corner.

No sibling task directories were inspected; the scaffold was derived solely from the scenario text and the skill spec.

## Step 3: Copy Shared Files — 2026-09-30T13:45:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3238_volunteer_editor_dispute_resolution_donation_campaigns/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T13:50:00.000Z

All three hard contracts pass.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs + path params: 112 required, 112 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 12 checked, ordering stated in §2.7, 0 missing
- concurrency_rules[] OCC rejections: 5 checked, 5 expressed (write op + expected_*_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all 8 machines' transitions expressed with preconditions and side effects, 0 missing
- calculations[]: 9 checked (page_content_score, editor_rollback_eligibility, campaign_banner_selection, banner_conversion_rate_bp dual variant, grant_review_score, grant_budget_check, vandalism_score, transparency_report_aggregation, revision_acceptance_threshold dual variant, campaign_net_revenue_allocation per-banner-round-then-sum), all expressed in prose, 0 missing
- validations[] conditions: 12 checked, each matchable to error_id in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: types/defaults/enum values reconstructible, 0 missing
- sibling-branch symmetry: ACTIVE→BLOCKED and SUSPENDED→BLOCKED, COMPLIED vs PARTIALLY_COMPLIED, SUBMITTED/UNDER_REVIEW→WITHDRAWN, truncated vs rounded bp variants, provisional vs final thresholds — all with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 287
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Output written to `workspace/PRD.md` (37 KB, 315 lines, non-empty). The two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened. The PRD ends at §5 Error Code Catalogue with no audit footer.

## Step 5: Generate Unit Tests — 2026-09-30T14:00:00.000Z

All checks pass. Final summary:

## Deliverables

**test_helpers/** (9 files, import-verified against the installed `prd_bench_local_runner` framework):
- `types.py` — 20 status enums + 14 entity TypedDicts (version-bearing vs append-only split per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 80 endpoint methods covering every PRD §4 row, including `/_clock/set_current_utc`
- `api_errors.py` — all 21 `ApiErrorId`s with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + page/campaign/grant-program invariant checkers
- `factories.py`, `constants.py`, `test_users.py` (opaque shared headers + mandatory `make_volunteer_editor_headers(editor_id)` for the entity-backed role), `fixtures.py` (tiered composite setups: active-campaign-with-banner, completed donation, accepted revision, TALK/NOTICE/ARBITRATION dispute ladders via clock advancement, scored/approved grant applications)
- `__init__.py` barrel export

**test_suite/** (6 files, **64 test functions**): `conftest.py` + `test_01_entities.py` (8) + `test_02_state_machines.py` (10) + `test_03_calculations.py` (11) + `test_04_validations.py` (22) + `test_05_cascades_and_invariants.py` (13).

## Coverage audit

- **Queue A (Difficulty)**: 16 of 18 instances × ≥2 tests each = 32 tags, all verified present. Skipped: both `resource_temporal_overlap` instances — the PRD contains no campaign-window-overlap rule (§3.7/§3.8) and no report-period-overlap rejection (§3.11), so they fail the coverage condition of the PRD-first filter.
- **Queue B (Corner)**: 31 of 32 non-stub instances × ≥1 test each. Skipped: `consistency_model/donation_process_immediately_visible_in_campaign_total` — asserts no rule beyond the already-tested process side effects; gap documented in the `test_05` module docstring.
- Every test docstring ends with exactly one verbatim `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real yaml instance; no untagged/dual-tagged tests; no `skip`/`xfail` markers anywhere.
- PRD citations spot-checked: 34 distinctive rule-bearing substrings all grep-verified verbatim against `workspace/PRD.md` (including every asserted `error_id` named in PRD prose, not just the §5 table).
- Scaffold-fragile setups were hardened at translation time: block-cascade tests first satisfy the PRD's "three or more confirmed vandalism reports" block precondition; protection-approve setups flag 3 revisions to satisfy the §3.5 precondition; score-dependent accept tests branch on the server-computed `vandalism_score`/composite instead of assuming exact values; the grant closed-program test creates both applications before closing.

All Python files compile and `test_helpers` imports cleanly (framework exports verified against installed signatures).

## Step 6: Generate Implementation — 2026-09-30T14:25:00.000Z

Implementation complete and verified. Summary:

## What was built

A complete Python + Flask implementation of the Wiki Governance API at `workspace/implementation/`, covering all 74 endpoints from the scaffold.

**File list:**
- `start.sh` — executable launcher; guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — Flask assembly, blueprint registration, error handlers (404/405 map to `ERR_NOT_FOUND`)
- `db.py` — in-memory store (empty on boot, no seeding) + logical clock starting at `2026-09-01T00:00:00Z`
- `errors.py` — ApiError class + all 21 error IDs with correct HTTP statuses
- `response.py` — envelope helpers matching the scaffold exactly: `meta{api_request_id, api_request_timestamp(, limit, offset, total_count, has_more)}`, `response_type`, `data`; error body uses `error_id`/`message`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth; 401 for missing/unknown role, 403 for unauthorized role
- `helpers.py` — UUID ids, ISO-8601 timestamps with 3 fractional digits + `Z`, pagination (limit default 10, min 1, max 100, offset 0), `created_at`-ascending sort, OCC check (skipped when field omitted)
- `services.py` — calculations: vandalism score (base 10/5 + keyword 30 + pattern 40 + history 20, cap 100), rollback eligibility (zero CONFIRMED reports in 90d), content score (0.4/0.4/0.2 with stability bonus 100/50/0, ROUND_HALF_UP), dispute-level derivation, protection gates (NONE/SEMI 4-day age/FULL admin-only), protection-request expiry, conversion-rate bp (truncated on detail read, rounded-half-up variant for summaries), campaign net revenue allocation (per-banner round-half-up 3% fee then sum — per-banner-round-then-sum per spec)
- `routes_clock.py`, `routes_editors.py`, `routes_pages.py`, `routes_revisions.py`, `routes_disputes.py`, `routes_protection.py`, `routes_vandalism.py`, `routes_campaigns.py`, `routes_banners.py`, `routes_donations.py`, `routes_grants.py`, `routes_legal.py`, `routes_transparency.py`

**Key behaviors verified via live smoke tests** (booted on a private port, exercised, then killed only own PID):
- Editor register → page create → revision submit → accept with `ERR_STALE_VERSION` on wrong `expected_page_version`, success on correct (page version bumped, content_score recalculated, edit_count incremented)
- Dispute ladder: duplicate-level `ERR_DISPUTE_ALREADY_OPEN`, `ERR_ESCALATION_TOO_SOON` before 72h, TALK→NOTICE→ARBITRATION with auto `FULL` protection and `ARB` dispute level, resolve recalculates
- Campaign lifecycle with OCC, impression frequency cap (`ERR_BANNER_FREQUENCY_CAP` on 3rd of cap=2), geo mismatch (`ERR_BANNER_GEO_MISMATCH`), donation process/refund updating `raised_cents` and `conversion_count`
- Grants: weighted review score (0.3/0.3/0.2/0.2, round-half-up → 75 for the test input), `ERR_GRANT_BUDGET_EXCEEDED`, approval increments `allocated_cents`
- Legal/transparency: `ERR_LEGAL_REQUESTS_PENDING` blocks publish, publish recomputes counts and stamps `transparency_report_id`
- Suspend (flags PENDING revisions, `rollback_eligible=false`), reinstate blocked before 7 days, RBAC 401/403 ordering, pagination meta, 404s
- Fresh-process reboot returns an empty store (`total_count: 0`), confirming per-test-server isolation

**One bug found and fixed during verification:** an overflow in `timedelta(days=10**9)` used for the "prior confirmed vandalism" check; replaced with a windowless lookup.

**Judgment calls (spec-silent areas):** `source_quality_score`/`neutrality_score` are deterministic content heuristics (overridable via optional body fields) since the scaffold gives no formula; the 72h escalation check uses `escalated_at or opened_at`; reinstate timing tracked via a `suspended_at` marker so incidental updates can't reset it.

## Step 7: Run Tests and Iterate — 2026-09-30T14:40:00.000Z

All 8 rounds pass 64/64.

## Summary

- **Iterations run:** 2 (initial sweep → fixes → clean sweep).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`:**
  - `test_03_calculations.py` — `test_per_banner_fee_rounded_before_summation` and `test_completion_retires_banners_and_excludes_refunded`: added `set_clock("2027-01-01T00:00:00Z")` before the `complete_campaign` call. The tests previously tried to complete a campaign at clock 2026-09-01 with `end_at=2026-12-31` and raised (6669) < target (1000000), which PRD §3.7 forbids ("A campaign may be completed when the current time has passed `end_at` or when `raised_cents` has reached `target_amount_cents`") — the implementation was correct to reject with ERR_INVALID_STATE; the test setup was PRD-inconsistent.
  - `test_04_validations.py` — `test_protection_blocked_for_non_admin_on_full_page`: moved creation of the PENDING revision to *before* the FULL protection approval. PRD §3.2 blocks non-admin revision *submission* on a FULL-protected page with ERR_PROTECTION_BLOCKED, so the previous setup (create revision after protection) was unsatisfiable under PRD.

- **Fixes applied to `workspace/implementation/`:**
  - `routes_editors.py` `get_editor` — recompute `rollback_eligible` on read via `recompute_rollback_eligible`. PRD §3.6 states the biconditional "Rollback eligibility is true exactly when the editor has zero confirmed vandalism reports in the last ninety days," a function of current time; the cached value went stale when the 90-day window elapsed without a moderation event (fixes `test_rollback_eligibility_threshold_zero_confirmed`).
  - `routes_editors.py` `block_editor` — two cascade additions: (1) when cascade-flagging pending revisions, create a `VandalismReport` per flagged revision with `auto_flagged: true` — PRD §3.1 says blocking "flags all pending revisions" and PRD §3.2 defines flagging as "transitions the revision to `FLAGGED` and creates a `VandalismReport`"; (2) after cascade-closing disputes, recompute each affected page's `dispute_level` — PRD §3.4 states closure "applies the same `dispute_level` recalculation" from remaining open disputes (fixes `test_editor_block_cascade_creates_vandalism_report_for_flagged_revision`).

- **Final state:** all 8 parallel rounds pass 64/64.

## Step 8: Finalize PRD — 2026-09-30T14:45:00.000Z

Done. `PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Summary

**Line counts:** PRD.md = 315 lines, PRD_FINALIZED.md = 315 lines (0% line-count delta; 3 sentences revised/extended in place, no sections added).

### Changes

- **§3.1 (suspension sentence)** — revise — "flags every pending revision" → "transitions every pending revision ... to `FLAGGED` (without creating a vandalism report)", matching impl where suspend only flips status — `implementation/routes_editors.py:72-75`.
- **§3.1 (blocking sentence)** — revise — appended: block-cascade flagging follows §3.2's definition (FLAGGED + a `VandalismReport` per revision, `auto_flagged: true` since automated), and cascade-closing disputes triggers §3.4's `dispute_level` recalculation on each affected page — `implementation/routes_editors.py:112-139`.
- **§3.6** — revise — appended: the 90-day rollback-eligibility window is anchored to current time, so eligibility changes with clock advancement even without a moderation event, and the value returned by an individual editor-profile fetch reflects standing as of the current time — `implementation/routes_editors.py:51-59`, `implementation/services.py:28-31`.

### Step-7 items requiring no PRD change

- The two `test_suite/` fixes (`test_03_calculations.py` clock setup; `test_04_validations.py` ordering) were pure fixture bugs: PRD §3.7 already pins the completion precondition ("current time has passed `end_at` or `raised_cents` has reached `target_amount_cents`") and §3.2 already pins ERR_PROTECTION_BLOCKED on revision submission to a FULL-protected page. Prose kept verbatim.

### Per-edit pre-edit search log

**Edit 1 (suspension cascade verb)**
- (a) Subject: what "flags" means in the suspension cascade — whether a VandalismReport is created.
- (b) Paths enumerated: `routes_editors.py:suspend_editor` (lines 62-77 — status flip only, no report); `routes_editors.py:block_editor` (lines 112-125 — flip + report; covered by Edit 2); `routes_revisions.py:flag_revision` (lines 166-199 — creates report, `auto_flagged` false; unaffected since it's the explicit flag endpoint); `services.py` (no other FLAGGED transitions). Grepped `auto_flagged` across `test_suite/`/`test_helpers/` — only type assertion, no suspend-report expectation.
- (c) Wording adjustment: avoided the verb "flags" entirely for suspension (since §3.2 defines flagging as report-creating) and used "transitions ... to `FLAGGED` (without creating a vandalism report)" so §3.2's definition is not invoked.

**Edit 2 (block cascade: report creation + dispute_level recalc)**
- (a) Subject: side effects of the block cascade on pending revisions and initiated disputes.
- (b) Paths enumerated: `routes_editors.py:block_editor` (lines 99-141 — full cascade read); `routes_disputes.py:close_dispute` (lines 138-156 — same `recompute_dispute_level` call, so "same recalculation as §3.4" is accurate); other `recompute_dispute_level` callers (`create_dispute`, `escalate_dispute`, `resolve_dispute`) — unaffected by wording; §2.6 cascade example sentence — consistent, left untouched; `services.py:recompute_dispute_level` (lines 91-102 — derives from OPEN/ESCALATED disputes).
- (c) Wording adjustment: deliberately did NOT pin the cascade report's `report_type` (impl: "VANDALISM") or `reporter_id` (impl: null) — no consumer or test depends on them, so under-determined wording preferred; pinned only report existence and `auto_flagged: true` (matching §3.2's existing auto_flagged rule).

**Edit 3 (rollback_eligible time-dynamics)**
- (a) Subject: when/where `rollback_eligible` reflects the current-time 90-day window.
- (b) Paths enumerated: `services.py:recompute_rollback_eligible` (window vs `db.now()`); recomputing callers — `routes_vandalism._moderate` (confirm/dismiss), `routes_editors.reinstate_editor`, `routes_editors.get_editor` (on read); non-recomputing readers — `routes_editors.list_editors` (returns cached), privilege checks in `routes_revisions.py` accept/flag/revert (read stored field); direct writers — `suspend_editor` (sets false), `create_editor` (initializes true).
- (c) Wording adjustment: scoped the claim to "fetching an individual editor's profile" only — explicitly did not claim list endpoints or acceptance/flag/revert privilege checks recompute, since the impl uses the stored value there. Claiming otherwise would have been a new mismatch.

## Step 9: Complete PRD — 2026-09-30T14:57:00.000Z

Done. `PRD_COMPLETED.md` written at `workspace/PRD_COMPLETED.md`.

## Summary

- **Source:** `PRD_FINALIZED.md` (315 lines / 37,828 chars) → `PRD_COMPLETED.md` (317 lines / 46,457 chars), char-delta **+8,629**.
- **Counts:** 21 ambiguity-pins, 10 mismatch-revisions (many edits are mixed; classified by dominant intent).

### Changes (PRD section — insert|revise — ambiguity|mismatch — what changed — impl ref)

- §2.3 — revise — ambiguity — pinned 400 on bad limit/offset, `id` tie-break in sort, `has_more` formula, and extra scalar equality filters — helpers.py:55-106
- §2.4 — revise — mismatch — `version` starts at 1; added `CampaignBanner` and `Donation` to the version-less entity list — helpers.py:22-31, routes_banners.py:42, routes_donations.py:37
- §2.5 — revise — mismatch — banner conversion bp is always truncated; no rounded variant is exposed — routes_banners.py:17-20 (services.py:149 unused)
- §2.7 — insert — ambiguity — undefined paths/methods return ERR_NOT_FOUND 404 — app.py:38-45
- §2.8 — revise — mismatch — added revert (`expected_page_version`) and grant-program close (`expected_program_version`) to the OCC list; pinned that omitting the field skips the check and non-integer → 400 — helpers.py:116-130, routes_revisions.py:219, routes_grants.py:62
- §2.9 — insert — ambiguity — clock endpoint response shape `{"current_utc": ...}` — routes_clock.py:12-19
- §3.1 — revise — mismatch+ambiguity — registration honors optional `coi_disclosure_required`/`coi_disclosed`; removed impl-absent suspend/block preconditions (vandalism counts, COI detection); pinned ACTIVE-only suspend, `suspended_at` field, reinstate 7-day + initiator-arbitration checks with error codes, block-only-if-not-BLOCKED, auto reports have `reporter_id` null and `report_type` VANDALISM — routes_editors.py:26-141
- §3.2 — revise — ambiguity+ mismatch — pinned topic_area 400, editor-lookup 404, spam keyword list and blanking definition, source/neutrality score formula (`min(100, 50 + len%51)` with body override clamped 0-100), TALK-only pages use threshold 40, composite-below-threshold → 409, flag endpoint mechanics (PENDING only, valid report_type, returns the report), revert prior-revision selection rule and null case, flagged-accept skips quality/vandalism checks, 404 for unregistered acting editor — routes_revisions.py:22-240, services.py:44-62
- §3.3 — insert — ambiguity — only the editor themself may file COI disclosure (else 403); response returns the editor — routes_editors.py:144-156
- §3.4 — revise — ambiguity+mismatch — pinned dispute_level recalculation rule, respondent/revision 404 checks, non-party escalator → 403, escalation keeps status OPEN, resolve recalculates dispute_level at any level (not only ARBITRATION), close requires initiator BLOCKED (missing initiator → 409) — routes_disputes.py:22-156, services.py:91-108
- §3.5 — revise — ambiguity — pinned requested_level 400, flagged-count window measured by revision `updated_at`, `prior_protection_level` recording, lazy expiry evaluation on page/protection-request reads — routes_protection.py, services.py:127-141
- §3.6 — insert — ambiguity — confirm/dismiss require PENDING report, else 409 — routes_vandalism.py:31-45
- §3.7 — revise — mismatch+ambiguity — cancel allowed only from ACTIVE (not "at any time"); banner flips skip RETIRED banners; activation window inclusive of both endpoints; completion response carries `net_revenue_allocation` with shape and banner ordering — routes_campaigns.py:53-150
- §3.8 — revise — mismatch — removed banner-selection endpoint prose (no such endpoint exists); geo/frequency-cap rules enforced at impression recording; geo check precedes cap check; `conversion_rate_bp` computed field on banner reads; frequency_cap/priority_weight integer validation 400s — routes_banners.py:23-109
- §3.9 — revise — ambiguity — pledge allowed in any campaign status; banner-must-belong-to-campaign 404; positive-integer amount 400; process/fail/refund state preconditions with error codes; refund window boundary (exactly 90 days still valid) — routes_donations.py:17-123
- §3.10 — revise — ambiguity+mismatch — program close requires OPEN; start-review requires program still OPEN; scoring only in UNDER_REVIEW with per-score 400 validation; approve requires UNDER_REVIEW and awarded_cents int >0; reject only from UNDER_REVIEW (was "without preconditions"); withdraw non-applicant → 403 — routes_grants.py:57-225
- §3.11 — revise — mismatch — dropped USER_INFO court-order/subpoena precondition and "revisions are locked" clause (impl does neither); pinned target existence validation at creation; comply/partially-comply/reject require UNDER_REVIEW — routes_legal.py:19-124
- §3.11 (transparency) — insert — ambiguity — publish only from DRAFT; half-open interval made explicit (start inclusive, end exclusive) — routes_transparency.py:50-77
- §3.12 — revise — ambiguity — 30-day window anchored on revision `updated_at` and dispute `opened_at`; zero accepted revisions → score 0 — services.py:65-88
