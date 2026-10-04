# Worklog — task_3271_merchant_application_ecosystem_review_billing_partner_revenue

## Step 1: Create Task Directory — 2026-09-30T16:25:00.000Z

Task directory pre-allocated per entrance args: verified `./tasks/task_3271_merchant_application_ecosystem_review_billing_partner_revenue/workspace/` exists. No index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T16:43:00.000Z

All three artifacts are generated and lint-clean. Summary:

## Generated: task_3271_merchant_application_ecosystem_review_billing_partner_revenue

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3271_merchant_application_ecosystem_review_billing_partner_revenue/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key

**Counts**: 16 entities, 7 state machines, 9 calculations, 15 ordered validations, 72 endpoints (incl. 1 `/_clock/set_current_utc` test-driving endpoint with the mandatory `2026-09-01T00:00:00Z` default), 23 error codes, 4 roles, 2 OCC concurrency rules. Difficulty design: 9 rules × 2 instances = 18. Corner design: 50 instances across all 9 claim-extraction sections (40 with full test recipes, 10 `excluded_because:` stubs).

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Design decisions worth noting**:
- Archetype: workflow-orchestration primary + pricing-engine secondary; segregation-of-duties role model (Reviewer is opaque and must not equal the owning DeveloperAccount id — enforced as a priority-6 safety check that outranks constraint checks).
- Difficulty anchors: dual-variant accrual (PROVISIONAL vs FINAL `developer_accrual`) plus dual-variant performance windows (rolling 7-day vs lifetime average) for Rule 1; pinned evaluation order in `charge_net_computation` (discount→share→net, mode c) vs 3-input non-linear proration+aggregation (mode a) for Rule 2; cyclic AppVersion review loop vs Installation×ConsentRecord parallel dimensions for Rule 3; depth-3 delist cascade (App→Installation→charge reversal) vs merchant-uninstall→deadline→strike cascade for Rule 4.
- Boundary pins: revenue-share tiers are inclusive-down (exactly 1,000,000.00 stays zero-share); performance budget `<=` is inclusive; half-open ReviewWindow intervals allow adjacency; SLA breach requires strictly-greater.
- All formula-derived assert literals were pre-computed in Python (e.g. invoice total 10100, tier-T1 share 18000000, prorated 500) before being written into recipes.

**Caveat relevant to downstream steps**: endpoint count is 72 — well past the ~40 overshoot threshold noted in memory (`scaffold-endpoint-overshoot-breaks-impl-gen`). Most of the surface is read-side GETs forced by the lint's collection-derivation heuristic (per-entity single GETs under the `/` api_prefix plus reverse-reachability lists for 17 FKs) and RBAC-denial corners; if Step 6 degrades, trimming read-only list/detail endpoints is the safe lever since no difficulty instance depends on them.

## Step 3: Copy Shared Files — 2026-09-30T16:44:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T16:52:00.000Z

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_3271_merchant_application_ecosystem_review_billing_partner_revenue/workspace/PRD.md`
**Line count:** 396 lines

**Sections produced:**
- §1. Introduction (3 paragraphs)
- §2. Global Specifications — 13 subsections (2.1 RBAC, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Monetary Values/Integer Cents, 2.6 OCC, 2.7 Validation Ordering & Precedence, 2.8 Nested Resource Retrieval, 2.9 Hierarchical Consistency, 2.10 Logical Clock, 2.11 Billing Cycles & Charge Ledger Sync, 2.12 Revenue Share Tiering, 2.13 Storefront Performance Budget)
- §3. Business Logic & Workflows — 13 subsections (Developer Onboarding & App Creation; Versioning & Review Cycle; Scope Requests & Segregation of Duties; Publishing & Search Ranking; Installation & Consent; Billing Charges & Discounts; Storefront Performance; Invoicing & Revenue-Share Accrual; Uninstall & Data Deletion; Webhook Subscriptions; Governance Strikes & Delisting; Support Tickets & SLAs; Permission Scope Catalog)
- §4. Endpoint Definitions (72-row table: Method, Path, Description, Authorized Roles)
- §5. Error Code Catalogue (23-row table: Error ID, HTTP Status Code)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoints[].input + concurrency occ_field: 71 required, 71 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in prose (§2.7 enumerates the full ordered list), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_app_version + ERR_STALE_VERSION on PATCH /apps; expected_invoice_version + ERR_STALE_VERSION on invoice issue), 0 missing
- state_machines[].transitions: all 8 state machines covered (App 9 transitions, AppVersion 7, Installation 8, ConsentRecord 1, AppBillingCharge 5, MonthlyInvoice 3, SupportTicket 6) with preconditions and side effects in §3, 0 missing
- calculations[]: 9 checked, 9 fully expressed (revenue_share_tier_assignment, charge_net_computation, developer_accrual dual-variant, usage_charge_proration, storefront_performance_score, search_ranking_score, support_sla, uninstall_deadline_enforcement, invoice_total), 0 missing
- validations[] conditions: 15 checked, 15 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all covered, 0 missing
- entities[].fields[] structured content: all types/defaults/enums expressed, 0 missing
- sibling-branch symmetry: reviewer actions and uninstall transitions rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 516
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage confirmation:** Every endpoint (72), every entity (13), every state machine transition (39), every calculation (9), every validation rule (15), every error ID (23), every role (4), and every enum value (73) in SCAFFOLD.yaml is covered by PRD prose.

## Step 5: Generate Unit Tests — 2026-09-30T17:15:00.000Z

Generation complete. Summary:

## Test infrastructure (test_helpers/, 9 files)
All under `/home/ubuntu/github/CodingPRD/tasks/task_3271_merchant_application_ecosystem_review_billing_partner_revenue/test_helpers/`:
- `types.py` — 16 status/enum types + 17 entity TypedDicts (PermissionScope correctly omits `updated_at`/`version` per the immutable-catalog rule)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~60 methods)
- `api_errors.py` — `ApiErrorId` enum (23 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` helpers + charge money invariant
- `factories.py` — payload factories, input fields only
- `constants.py` — tier boundaries (T0 ≤ 100000000 < T1 ≤ 1000000000 < T2), LAUNCH10 10%, T1/T2 share rates, 30-day proration/deletion windows, 200ms perf budget, SLA hours, 5-strike delist threshold, 14-day dispute window
- `test_users.py` — `TEST_USERS` constants + per-instance builders `make_developer_headers`/`make_merchant_headers` (entity-backed roles), `make_admin_headers`/`make_reviewer_headers` (opaque)
- `fixtures.py` — composite chain helpers: `setup_listed_app`, `setup_active_installation`, `create_approved_charge`, `open_invoice`/`issue_invoice`/`mark_invoice_paid`, `setup_issued_invoice`/`setup_paid_invoice`, `setup_uninstalling_installation`/`setup_uninstalled_installation`, `add_performance_strikes`, `setup_suspended_app_with_strikes`, `setup_support_ticket`
- `__init__.py` — barrel export

## Test suite (test_suite/, 8 files, 76 tests)
- `conftest.py` + `test_01_entities.py` (7) + `test_02_review_lifecycle.py` (10) + `test_03_calculations_corner.py` (3) + `test_04_validations.py` (6) + `test_05_endpoints_errors_rbac.py` (14) + `test_06_revenue_share.py` (16) + `test_07_difficulty_workflows.py` (20)

**Queue A (difficulty): 36 tests — 2 per each of 18/18 instances.**
**Queue B (corner): 40 tests — 1 per each of 40/40 non-stub instances; 10 `excluded_because:` stubs not translated** (all cross-references resolve to real difficulty instances).

**Skipped instances: none** — every non-stub instance passed the PRD-first filter.

Two translations deliberately deviated from the design-yaml literal assertions where the yaml conflicted with the PRD (PRD wins, per the contract):
- `semver` duplicate → asserted `ERR_INVALID_REQUEST` (yaml claimed `ERR_DUPLICATE`); PRD §3.2 states verbatim "reusing a `semver` already on file for the same app is rejected with `ERR_INVALID_REQUEST`", and the PRD §2.7 uniqueness rule names only email/app-name/cycle/topic.
- `charge_approval_gated_by_installation_state` → used `validate_error_is_one_of([ERR_INVALID_STATE, ERR_CHARGE_NOT_PENDING])` (the design's own assert line sanctions this), since the charge is REVERSED by the uninstall cascade and PRD pins the not-PENDING case to `ERR_CHARGE_NOT_PENDING` while §2.7 leaves the state-vs-specific-error resolution open.
- Tier-boundary instance asserts share on `c11b` (the 40M charge invoiced while crossing the boundary) — 0 at T0 is correct; the yaml's `c11a` (60M, invoiced at T0 pre-crossing) would also be 0.

**Stage 2 self-check: PASS** — every instance covered at target depth, exactly one valid `Design:` tag per test (no orphans, no untagged), every PRD citation has a ≥8-word verbatim match in PRD.md, no skip/skipif/xfail markers, all files compile, and all `from test_helpers import` names resolve.

## Step 6: Generate Implementation — 2026-09-30T17:21:00.000Z

72 unique (method, path) rules plus Flask's built-in `/static/<path:filename>` — exactly matching PRD §4's 72 endpoints. All done.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3271_merchant_application_ecosystem_review_billing_partner_revenue/workspace/implementation/`):

| File | Lines |
|---|---|
| `app.py` | 39 |
| `db.py` | 75 |
| `errors.py` | 78 |
| `middleware.py` | 56 |
| `services.py` | 436 |
| `routes_core.py` | 637 |
| `routes_marketplace.py` | 499 |
| `routes_billing.py` | 421 |
| `start.sh` | 7 |
| `requirements.txt` | 1 |

**Endpoint coverage: 72/72** from PRD §4 (verified by dumping Flask's url_map — 72 app routes + Flask's built-in `/static/` rule).

**Boot verification**: `start.sh` launched on port 18723, responded correctly to `POST /_clock/set_current_utc` (200) and `GET /apps` (empty list envelope with `limit/offset/total_count/has_more` in meta), plus a full end-to-end smoke: developer → scope → merchant → app → version → scope-request → submit → decide → approve → publish → install → consent → LAUNCH10 charge (10005 → discount 1001 → final 9004, T0 share 0) → approve → invoice issue (total 9004) → mark-paid → lifetime_gross 9004 → uninstall → confirm-data-deletion. Server then killed by exact listener PID only.

**Key implementation choices / PRD ambiguities resolved:**
- Logical clock starts at exactly 2026-09-01T00:00:00Z per scaffold endpoint note; all timestamps derive from it; `api_request_timestamp` also uses logical clock (PRD says "server-generated" without specifying wall vs logical).
- Submit picks the latest-created matching version when several SUBMITTED/CHANGES_REQUESTED versions exist (PRD says "at least one" without naming which).
- Recency signal in search ranking uses a `published_at` timestamp recorded on the version at publish time (PRD says "version was PUBLISHED within the last 30 days" — scaffold has no such field, so I track it internally; it is not serialized since it's not a declared field).
- Performance delisting transitions app status to DELISTED only when currently LISTED (per §3.7 "app transitions LISTED → DELISTED"), but `performance_state`/`listing_status` always flip on the 3rd breach.
- "3 consecutive windows" tracked as a set of distinct sampled_at days (reset on a compliant window per §2.13 "remains or returns to COMPLIANT"); a 3rd-breach strike is opened in addition to the per-breach strikes (scaffold side-effects show both DEGRADED and DELISTED_PERFORMANCE open a PERFORMANCE_BREACH strike).
- Reconsent consent call grants delta scopes only (approved published-version scopes lacking a GRANTED record) per §3.5 "new ConsentRecord rows for the delta scopes".
- FINAL ledger entries on mark-paid are appended as new ACCRUAL/FINAL rows (PROVISIONAL rows kept; distinguished by `entry_variant`, per "supersede via entry_variant markers").
- Uninstall's `app/uninstalled` delivery attempt is recorded as an internal `last_delivery_attempt_at` on ACTIVE webhooks (not serialized; subscriptions stay ACTIVE until DISABLED by deletion confirmation/expiry per §3.10).
- Scaffold's `common_fields: true` includes PermissionScope, but PRD §2.4 explicitly overrides: PermissionScope carries only `id` and `created_at`. PRD wins.
- Support tickets include a `resolved_at` field (needed for the 14-day dispute window); serialized alongside declared fields.
- No entity seeding anywhere; store starts empty.

## Step 7: Run Tests and Iterate — 2026-09-30T17:55:00.000Z

Clean 8-round parallel sweep: all 8 rounds 75/75 (no failures, no flakiness). Orchestrator re-verified all 8 `results.*.json` files on disk: every round 75/75, 0 failed.

## Summary

**Iterations run:** 3 sweeps (76→76 with 7 failures, then 75/75 after deletion, then final clean 8×75/75).

**Tests deleted (1):**
- `test_publish_supersedes_prior_published_version` (test_02_review_lifecycle.py) — REACHABILITY COLLAPSE. The PRD state machine makes a second publish of the same app unreachable through PRD-declared operations: publish requires app=APPROVED (§3.4), and no transition takes LISTED back to APPROVED (reject/request-changes require version IN_REVIEW; version creation requires app DRAFT/CHANGES_REQUESTED; suspend/reinstate return to LISTED only). Two PRD-faithful implementations diverge: one enforces the coupled app/version preconditions (supersede branch unreachable), another might allow it. The scaffold's flat state-machine table drove generation without checking reachability through declared operations.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `setup_listed_app`/`setup_active_installation` gained an optional `developer` param (PRD §3.1: a developer may act only on own apps; the search test created two apps under different developers then updated both with one developer's headers — fixture identity bug).
- `fixtures.py` — `setup_suspended_app_with_strikes` now uses a new `add_performance_strikes_without_perf_delist` helper: one breaching sample + one compliant sample 8 days later per strike. The old pattern (5 breaching samples on consecutive days) triggered the PRD §3.7 system-initiated LISTED→DELISTED transition on the 3rd consecutive breach, leaving the app ineligible for the admin delist action (§3.11 requires SUSPENDED). The 8-day gap ensures the compliant sample's 7-day window excludes the breach, resetting the consecutive tracker.

**Fixes applied to `test_suite/`:**
- `test_03_calculations_corner.py::test_search_ranking_weights_and_tiebreak` — second app now created under the same developer (via the new fixture param) so `update_app` with that developer's headers is ownership-consistent with PRD §3.1.
- `test_04_validations.py::test_overdue_data_deletion_confirm_rejected` — relaxed to `validate_error_is_one_of([ERR_DELETION_OVERDUE, ERR_INVALID_STATE])`. PRD §3.9 names ERR_DELETION_OVERDUE for overdue confirmation, but the deadline-passage cascade moves the installation to UNINSTALLED, and §2.7's precedence puts the state category (4) above the deadline category (11). Permitted relaxation.
- `test_05_endpoints_errors_rbac.py::test_error_already_terminal_on_uninstalled_installation` — relaxed to `validate_error_is_one_of([ERR_ALREADY_TERMINAL, ERR_UNINSTALL_IN_PROGRESS])`. §3.9 names ERR_UNINSTALL_IN_PROGRESS for "creating charges ... against an installation that is UNINSTALLING or UNINSTALLED" while §2.7 also lists ERR_ALREADY_TERMINAL; PRD doesn't pin which for an UNINSTALLED installation.
- `test_06_revenue_share.py::test_final_accrual_excludes_reversed_charge_on_mark_paid` — split per STEP 1c: replaced the `entries[0]["entry_variant"] == "FINAL"` ordering assertion (contradicts PRD §2.3's created_at-ascending default, which places PROVISIONAL first) with a PRD-faithful assertion that a FINAL ACCRUAL entry exists (§3.8 "supersedes ... the entry_variant marker distinguishes the two"). The lifetime-gross and platform-share assertions (verbatim-covered) were kept.

**Fixes applied to `implementation/`:**
- `routes_billing.py::issue_invoice` + `services.py::finalize_charge_share` — the share is now computed against a running gross that includes the charge being invoiced (and earlier same-batch charges), per §3.6 "tier in force at the moment the charge is invoiced" + §2.12's gross defined over INVOICED/SETTLED charges. `_charges_for_invoice` now sorts by (created_at, id) so the batch finalization order is deterministic. (Note: issue-time vs read-time gross diverge when a sibling charge is later reversed — PRD is silent on recomputation at mark-paid; test expects the issue-time snapshot, kept.)
- `routes_marketplace.py::_evaluate_performance` — a compliant window now resets the consecutive-breach tracker and returns performance_state to COMPLIANT regardless of prior state (§3.7 "remains or returns to COMPLIANT"; previously only DEGRADED reset, so a 4th-day breach after DELISTED_PERFORMANCE could never be walked back). Also, a repeated breaching sample on an already-counted day no longer opens a duplicate strike (consecutive windows are distinguished by distinct sampled_at days).
- `routes_marketplace.py::confirm_data_deletion` — ERR_DELETION_OVERDUE is checked before the state check whenever the installation is still UNINSTALLING, so an overdue-but-uncascaded confirmation surfaces the §3.9 deadline error; once the cascade has moved it to UNINSTALLED, the state error applies per §2.7 priority ordering.

## Step 8: Finalize PRD — 2026-09-30T18:02:00.000Z

All three edits are in place. Both files are 396 lines (edits were in-line revisions of existing paragraphs; character delta ~+1.5%).

## Summary

**Line counts:** PRD.md 396 lines, PRD_FINALIZED.md 396 lines (0% line delta; ~1.5% character growth — all edits are inline revisions within existing paragraphs, no new sections).

**Changes (one bullet per edit):**

- **§3.7 (Storefront Performance Sampling and Enforcement)** — revise — Pinned that a compliant window returns `performance_state` to `COMPLIANT` regardless of prior performance state (including from `DELISTED_PERFORMANCE`, without undoing `DELISTED` app status/listing) and resets the consecutive-breach count to zero; that consecutive breaching windows are distinguished by distinct `sampled_at` days so a same-day repeat breach opens no additional strike and causes no state change; and that once in `DELISTED_PERFORMANCE`, further breaching windows open no further strikes until a compliant window resets the run — `implementation/routes_marketplace.py:439-484` (`_evaluate_performance`).
- **§3.8 (Invoicing, Revenue-Share Accrual, and Payouts — issue paragraph)** — revise — Pinned that a multi-charge issue action processes charges in `created_at`-ascending order (ties by charge `id`), and each charge's share is finalized against the tier derived from a lifetime gross that includes the charge itself plus earlier same-batch charges of the same developer; also pinned that finalized `platform_share_cents`/`developer_net_cents` are never recomputed later (not at mark-paid, not on reversal of a sibling charge) — `implementation/routes_billing.py:212-279` (`_charges_for_invoice`, `issue_invoice`), `implementation/services.py:390-404` (`finalize_charge_share`).
- **§3.9 (Uninstall, Data Deletion, and the Thirty-Day Deadline)** — revise — Pinned that `ERR_DELETION_OVERDUE` surfaces while the installation is still `UNINSTALLING`, but once the deadline-passage cascade has moved it to `UNINSTALLED` the confirmation fails the state requirement and surfaces `ERR_INVALID_STATE` per §2.7 precedence — `implementation/routes_marketplace.py:258-282` (`confirm_data_deletion`), `implementation/services.py:422-442` (`run_time_cascades`).

**Step-7 items with no PRD edit (already PRD-determined or pure fixture bugs):**

- Deleted `test_publish_supersedes_prior_published_version` — PRD §3.4 already pins both the APPROVED precondition and the supersede cascade exactly as implemented (`routes_core.py:194-217`); the deletion was about reachability, not ambiguity of the described behavior.
- `fixtures.py` developer param + search test fix — pure fixture identity bug; §3.1 ownership already pinned (`routes_core.py:133-157`).
- `fixtures.py` `add_performance_strikes_without_perf_delist` — fixture fix; §3.7 auto-delist on 3rd consecutive breach and §3.11 SUSPENDED precondition for admin delist were already verbatim in the PRD.
- `test_overdue_data_deletion_confirm_rejected` relaxation — covered by Edit 3.
- `test_error_already_terminal_on_uninstalled_installation` relaxation — §3.9 already pins `ERR_UNINSTALL_IN_PROGRESS` for operations against UNINSTALLING/UNINSTALLED installations, which is exactly what the impl raises; no edit.
- Ledger-entry ordering assertion split — §2.3's created_at-ascending default plus §3.8's append order (PROVISIONAL at issue, FINAL at mark-paid) already determine ordering; no edit.

**Per-edit pre-edit search log:**

1. **Edit §3.7** — (a) Subject: performance-state transitions, `PERFORMANCE_BREACH` strike opening, consecutive-breach tracking. (b) Paths enumerated: `routes_marketplace.py::_evaluate_performance` (sole writer of `performance_state`, sole performance-strike source) and its only caller `create_sample` (lines 411-436); `services.py::open_strike` (generic strike writer, also called from `resolve_ticket` SUPPORT_BREACH and `run_time_cascades` DATA_DELETION_OVERDUE — neither touches performance_state); `services.py::search_score` (reads ACTIVE strikes only); `routes_core.py` suspend/reinstate/delist (none touch `performance_state` or installation cascade on performance delist). (c) Wording adjustment: added the explicit clause "though it never undoes a `DELISTED` app `status` or `listing_status`" because the impl's compliant-window walk-back sets only `performance_state`, leaving the terminal app status intact — without that clause "returns to COMPLIANT regardless of prior state" could be misread as resurrecting the listing.

2. **Edit §3.8** — (a) Subject: `platform_share_cents`/`developer_net_cents` computation timing and tier base. (b) Paths enumerated: `routes_billing.py::create_charge` (provisional share at creation using current tier — §3.6 already pins this; edit does not touch it), `issue_invoice` + `_charges_for_invoice` (batch order, running gross), `services.py::finalize_charge_share` (called only from `issue_invoice` — confirmed by grep), `mark_paid` (transitions status, appends FINAL entries, recomputes gross — does not touch shares), `reverse_charge` (REVERSAL entry + gross recompute — does not touch shares), `services.py::recompute_lifetime_gross` / `serialize_app` tier reads (read-time tier recomputation per §2.12 — unaffected by the "never recomputed" clause since it is scoped to the charge's share fields, not the tier field). (c) Wording adjustment: scoped the "never recomputed" sentence explicitly to `platform_share_cents`/`developer_net_cents` and named mark-paid and sibling-reversal as the non-recomputing events, to avoid any reading that the app's read-time `revenue_share_tier` (which §2.12 requires to be recomputed on every read) is frozen.

3. **Edit §3.9** — (a) Subject: error surfaced by confirm-data-deletion when the deadline has passed. (b) Paths enumerated: `routes_marketplace.py::confirm_data_deletion` (deadline check before state check, guarded on status == UNINSTALLING); `services.py::run_time_cascades` (the only writer that moves UNINSTALLING→UNINSTALLED without confirmation, triggered on every `/_clock/set_current_utc`); the other ERR_DELETION_OVERDUE/ERR_UNINSTALL_IN_PROGRESS sites (grep: charge creation, consent, revoke, webhook creation, sample submission, uninstall) — none overlap with the confirmation path. (c) Wording adjustment: anchored the state-error branch to "once the deadline-passage cascade ... has already moved the installation to UNINSTALLED" rather than a blanket precedence claim, matching the impl's exact branch structure and staying consistent with §2.7 (state category 4 masks deadline category 11).

## Step 9: Complete PRD — 2026-09-30T18:10:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_3271_merchant_application_ecosystem_review_billing_partner_revenue/workspace/PRD_COMPLETED.md` is written (copied from PRD_FINALIZED.md, then patched in place only).

## Summary

- **Source vs output**: PRD_FINALIZED.md 396 lines / 61,291 chars → PRD_COMPLETED.md 397 lines / 68,842 chars (+1 line, +7,551 chars).
- **Counts**: 22 ambiguity-pins, 9 mismatch-revisions (some edits contain both; counted by distinct behavioral claim).

### Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref)

- §1 Introduction — insert — ambiguity — in-memory store, empty at boot, rebuilt via API calls — implementation/db.py:1
- §2.2 Error format — insert — ambiguity — `api_request_timestamp` comes from the logical clock, not wall-clock — implementation/errors.py:20-24
- §2.2 Error format — insert — ambiguity — unknown route/method → `ERR_NOT_FOUND` 404 envelope — implementation/app.py:21-27
- §2.3 Pagination — insert — ambiguity — non-integer/out-of-range limit/offset → `ERR_INVALID_REQUEST` 400; offset non-negative; `has_more` formula — implementation/errors.py:51-78
- §2.6 OCC — insert — mismatch — PATCH on `DELISTED` app → `ERR_ALREADY_TERMINAL` before version check; both expected-version fields optional when omitted — implementation/routes_core.py:139-144, routes_billing.py:240-242
- §2.7 rule 4 — insert — ambiguity — pinned intra-state check order (submit app-state before version population; approve charge-status before installation-state; reverse charge-status before invoice-status) — implementation/routes_core.py:166-175, routes_billing.py:131-135, 158-165
- §2.7 rule 6 — revise — mismatch — segregation rule renamed to include the HIGH-risk revocation gate; scope-decide endpoint explicitly not segregated; window-creation segregation precedes interval checks — implementation/routes_core.py:504-525, 532-541
- §2.7 rule 7 — insert — mismatch — `ERR_VALIDATION` (400) admitted as a structural-error id; `base_amount_cents` validated under rule 12 so discount error surfaces first — implementation/routes_core.py:519,523, routes_billing.py:37-43
- §2.10 Logical clock — revise — mismatch — clock set is arbitrary and non-monotonic (may move backward), not "advance"-only — implementation/db.py:37-39, routes_billing.py:434-444
- §2.12 Tiering — insert — mismatch — lifetime gross is a pure function of charge state, never derived from ledger entries — implementation/services.py:286-297
- §3.1 App update — insert — ambiguity — ownership-checked, allowed from all statuses except `DELISTED`, no developer-`ACTIVE` requirement — implementation/routes_core.py:133-157
- §3.2 Submit — insert — ambiguity — referenced version is the most recently created qualifying (`SUBMITTED`/`CHANGES_REQUESTED`) version — implementation/routes_core.py:171-187
- §3.3 Scope-request creation — insert — ambiguity — not gated on version status; unknown `scope_code` → `ERR_NOT_FOUND`; duplicate scope requests allowed — implementation/routes_core.py:455-481
- §3.3 Scope decide — insert — mismatch — non-PENDING decide → `ERR_INVALID_STATE`; approval nulls `denied_reason`; missing denial reason / bad decision → `ERR_VALIDATION` 400; no segregation check — implementation/routes_core.py:504-525
- §3.3 Request-changes / reject — revise — mismatch — `note` and rejection `reason` are accepted but not persisted on any resource — implementation/routes_core.py:413-448 (no storage of either field)
- §3.4 Publish — insert — ambiguity — published version gets `published_at` = logical now — implementation/routes_core.py:212
- §3.4 Search — insert — ambiguity — `search` restricts results to `listing_status == LISTED`; no merchant ownership filtering on listing — implementation/routes_marketplace.py… routes_core.py:114-118
- §3.4 Merchant — revise — mismatch — merchant account carries no `status` field at all — implementation/services.py:104-112
- §3.5 Consent — insert — ambiguity — published version = most recently created PUBLISHED; no published version → consent succeeds with no records — implementation/routes_marketplace.py:162-168, 195-207
- §3.5 Reconsent — insert — mismatch — delta = approved published-version scopes lacking an active GRANTED record; no all-approved precondition on reconsent — implementation/routes_marketplace.py:208-216
- §3.5 Revocation — insert — ambiguity — scope missing from catalog skips the HIGH-risk pending-charge gate — implementation/routes_marketplace.py:334-340
- §3.6 Charge creation — insert — ambiguity — developer must own app; creation allowed in any installation status except UNINSTALLING/UNINSTALLED (incl. PENDING_CONSENT, SUSPENDED); `base_amount_cents` must be an integer — implementation/routes_billing.py:24-43
- §3.6 Proration — revise — mismatch — capped amount computed from the declared base; charge's stored `base_amount_cents` records the prorated effective base; `capped_at` set whenever `installed_at` is known (even uncapped), null when unknown — implementation/routes_billing.py:45-55, 72
- §3.7 Performance — revise — mismatch — third consecutive breaching day opens exactly one strike (3 total per run, not 4); breaching window in `DELISTED_PERFORMANCE` does not revert to `DEGRADED`; samples accepted in any installation status except UNINSTALLING/UNINSTALLED — implementation/routes_marketplace.py:417-418, 439-484
- §3.8 Invoice open — insert — ambiguity — `cycle` must match `\d{4}-\d{2}`, else `ERR_INVALID_REQUEST` — implementation/routes_marketplace.py:69-72
- §3.8 Ledger semantics — revise — mismatch — ledger is append-only; supersession is purely logical; PROVISIONAL = one ACCRUAL per invoiced charge at issue; FINAL = one ACCRUAL per settled charge at mark-paid plus FINAL REVERSAL entries on reversal; gross never derived from ledger — implementation/routes_billing.py:254-303, 154-178, services.py:286-297, 407-419
- §3.8 Mark-paid — insert — ambiguity — invoice `total_cents` unchanged at mark-paid — implementation/routes_billing.py:282-303
- §3.9 Uninstall — insert — ambiguity — `app/uninstalled` delivery attempt represented by stamping `last_delivery_attempt_at`; subscription status unchanged — implementation/routes_marketplace.py:250-253
- §3.11 Suspend — insert — ambiguity — only ACTIVE installations transition; pending charges not voided; merchant may still approve/decline from SUSPENDED per §3.6 — implementation/routes_core.py:220-233, routes_billing.py:125-151
- §3.12 Tickets — insert — ambiguity — resolve sets `resolved_at`; SUPPORT_BREACH strike only when `sla_breached` newly becomes true on resolution from ESCALATED; expired dispute window → `ERR_INVALID_STATE` 409 — implementation/routes_billing.py:393-427
- §5 Error catalogue — insert — mismatch — added `ERR_VALIDATION` (HTTP 400) row — implementation/routes_core.py:519,523

No new sections were added; all changes are in-paragraph inserts/revisions, plus the one required catalogue row for the previously-undocumented error id.

## Final verification — 2026-09-30T18:12:00.000Z

Orchestrator mtime check: all `implementation/` files last modified ≤ 17:45:07 and all `test_suite/`/`test_helpers/` files ≤ 17:50:34 — both before Step 7's final clean 8×75/75 sweep (verified on disk ~17:55). Steps 8/9 wrote only `PRD_FINALIZED.md` / `PRD_COMPLETED.md`; the clean sweep remains valid. Pipeline complete.
