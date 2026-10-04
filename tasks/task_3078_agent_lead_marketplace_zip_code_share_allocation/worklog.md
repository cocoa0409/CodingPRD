# Worklog — task_3078_agent_lead_marketplace_zip_code_share_allocation

## Step 1: Create task directory — 2026-09-29T20:35:00.000Z

Pre-allocated task directory `tasks/task_3078_agent_lead_marketplace_zip_code_share_allocation/` verified to exist with `workspace/` inside. No new directory created per orchestrator override instructions.

## Step 2: Generate scaffold — 2026-09-29T21:16:30.000Z

All artifacts generated and clean. Lint verdict:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

Scaffold for `task_3078_agent_lead_marketplace_zip_code_share_allocation` (Zillow Premier Agent-style lead marketplace) generated purely from the scenario text and the skill spec; no sibling tasks were read.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3078_agent_lead_marketplace_zip_code_share_allocation/`):
- `SCAFFOLD.yaml` — 2601 lines (§1.0–§1.7 only; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1989 lines (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2226 lines (single top key `scaffold_corner_design`)

**Counts:**
- Entities: 17 (Market, Brokerage, Agent, TeamAccount, TeamMembership, ShareOrder, Payment, Lead, LeadAssignment, LiveConnection, CallRecording, Rating, PerformanceSnapshot, CreditClaim, Listing, Dispute, OpsRun)
- State machines: 12 declared (11 with transitions; PerformanceSnapshot intentionally transitionless), 40 transitions
- Endpoints: 84 (2 system `/_clock` + ops-runs, 49 business CRUD/actions, 33 reverse-reachability/filtered-list GETs)
- Errors: 36
- Calculations: 9 | Validations: 15 (priority-ordered) | Roles: 4 (Agent/BrokerageUser entity-backed; MarketplaceOps/PlatformAdmin opaque) | OCC concurrency rules: 2 (Market version on payment capture, Lead version on offer accept)
- §1.8 difficulty instances: 18 (9 rules × 2)
- §1.9 corner instances: 32 (30 full + 2 `excluded_because` stubs)

**Difficulty-maximizing design choices** (per the "harder than expert" directive): dual-variant pricing (quoted vs locked tier/price) and scoring (rolling vs windowed-official, which drives tier demotion); demand-tier × volume-discount compounding formula with floor semantics; team charge split with per-member floor + weight-ordered remainder allocation; ShareOrder pause/resume cycle with capacity re-check on re-entry; Lead ROUTED→ROUTED reroute self-loop with 3-candidate exclusion per attempt; ops-run sweep as a 5-step chronological checkpoint driving expirations, reroutes, recording purges, and score snapshots; expiry branching on settled-vs-unpaid balance (COMPLETED vs CANCELLED); trailing 30-day duplicate window vs aggregate 10000-bps capacity as two distinct interval semantics; two compensating invariants (share bps conservation, charge/credit money conservation). All formula-derived assertion literals (9000, 11875, 12500, 2375000, 5667/2833, scores 0/45/65/77, hash-mod routing values) were computed by executing the scaffold's own formulas, and every OCC version input traces to a captured `${var}` from a prior response (deliberate-stale tests use `${var} + 1` expressions).

## Step 3: Copy shared files — 2026-09-29T21:18:20.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3078_agent_lead_marketplace_zip_code_share_allocation/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T21:26:00.000Z

All contracts pass. Final summary:

## Summary

**PRD generated:** `/home/ubuntu/github/CodingPRD/tasks/task_3078_agent_lead_marketplace_zip_code_share_allocation/workspace/PRD.md`

- **Line count:** 387 lines
- **Section list:**
  - §1 Introduction (3 paragraphs)
  - §2 Global Specifications — 12 subsections (2.1 RBAC + identity prose for all 4 roles, 2.2 verbatim fixed envelope, 2.3 Pagination, 2.4 Logical clock & sweeps, 2.5 Share capacity, 2.6 Licensing, 2.7 OCC, 2.8 Validation ordering with all 15 priorities enumerated, 2.9 Nested retrieval, 2.10 Common resource properties + carve-out for the 5 entities without `updated_at`/`version`, 2.11 Monetary precision, 2.12 Cascade discipline)
  - §3 Business Logic — 11 subsections organized by domain workflow (Markets/Listings → Agents/Teams → Share purchase → Lead intake → Offers → Charge split → Performance scoring → Live connections → Closes/Claims → Disputes → Ops sweep)
  - §4 Endpoint Definitions — 4-column table (Method, Path, Description, Authorized Roles), 86 endpoints
  - §5 Error Code Catalogue — 2-column table, 36 errors

**Hard contract results:**
- Contract 1 (Field-Name Coverage): 111 required, 111 present, 0 missing → **PASS**
- Contract 2 (Rule Coverage): all 36 `error_id`s appear in §2/§3 narrative; all 34 state enum values present; both OCC rules name `expected_market_version`/`expected_lead_version` + exact error ids + HTTP 412; validation priority 1–15 explicitly ordered in §2.8 → **PASS**
- Contract 3 (§3 Path Purity): 500 backticked tokens in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos → **PASS**

**Zero-Silence coverage notes:**
- The 5 append-only entities (`Payment`, `CallRecording`, `Rating`, `PerformanceSnapshot`, `OpsRun`) are explicitly called out as lacking `updated_at`/`version` in §2.10.
- The `Payment.payment_status` echo, `routing_note` values (`pool empty` / `pool exhausted`), the 30-day duplicate window's anchor-not-`REJECTED_DUPLICATE` carve-out, the `DROPPED` connection's non-terminal-for-lead semantics, the `REJECTED_DISPUTE` resolution enum value, and the automatic 3-consecutive-`NO_ANSWER` suspension trigger are all surfaced in narrative.
- Team-order waterfall split (floor per member, then 1-cent reconciliation by `allocation_weight` DESC, `created_at` ASC) is fully reconstructed in §3.6.
- Score formula's five components with weights (0.25 / 0.20 / 0.20 / 0.20 / 0.15), the `max(1, …)` denominators, and the 50-minute response-score floor are all translated into prose in §3.7 without pseudocode.
- The `agent_performance_score` ROLLING vs OFFICIAL variants, and the share-price `quoted` vs `locked` variants, are each distinguished in prose.

## Step 5: Generate unit tests — 2026-09-29T21:50:00.000Z

Done. Summary:

## Test infrastructure generated for task_3078 (Agent Lead Marketplace / Zip-Code Share Allocation)

### test_helpers/ (9 files)
- `/home/ubuntu/github/CodingPRD/tasks/task_3078_agent_lead_marketplace_zip_code_share_allocation/test_helpers/__init__.py` — barrel export (framework + PRD-specific)
- `types.py` — 18 entity TypedDicts (append-only Payment/CallRecording/Rating/PerformanceSnapshot/OpsRun omit `updated_at`/`version` per PRD §2.10) + 16 status enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (clock, ops-runs, markets, brokerages, agents, teams, memberships, share-orders/payments/pause/resume/cancel, leads/assign/close/cancel, assignments/accept, live-connections/record, ratings, credit-claims, listings/review/withdraw, disputes/resolve, snapshots, all nested list GETs)
- `api_errors.py` — all 37 error IDs + HTTP status map, registered with the framework
- `assertions.py` — per-entity `assert_*` + `assert_market_share_conservation` invariant
- `factories.py` — input-field-only payload factories with unique zip/email/license generation
- `constants.py` — tier thresholds (5000/8000 bps), volume-discount bands (2500/5000), 300s offer TTL, 30-day duplicate window, 90-day retention, score weights
- `test_users.py` — 4 role header constants + `make_agent_headers` / `make_brokerage_user_headers` per-instance builders for the entity-backed roles
- `fixtures.py` — tiered composites: `set_clock`, entity creators, `create_active_share_order` (OCC-safe via fresh market version re-read), `setup_market_with_active_order`, `create_routed_lead`, `accept_lead_offer`, `setup_assigned_lead`, `setup_team_with_order`, claim/listing/dispute shortcuts

### test_suite/ (8 files + conftest, 87 tests total)
- `test_01_market_and_entity_foundations.py` (13) — market/agent creation defaults, 404, leads pagination, required-field/enum 400s, payment immutability, price-quote computed read
- `test_02_share_pricing.py` (7) — quoted-vs-locked variant, tier×volume combinator, 5000-bps tier boundary, tier-3 constants
- `test_03_share_order_lifecycle.py` (14) — pause/resume cycle, capacity boundary (10000 exact fit + 1 over), share conservation, payment exactness, stale market OCC + retry, market-suspension gate, license gate
- `test_04_lead_routing_and_offers.py` (13) — duplicate window (day 29 reject / day 31 allow), empty-pool boundary, reroute self-loop + exhaustion + 9000 credit, selector determinism, offer TTL, manual assign, cancel-then-accept OCC
- `test_05_claims_and_expiry.py` (10) — claim approve/reject cascades, charge-credit conservation → COMPLETED expiry, expiry-driven repricing, duplicate-claim rejection
- `test_06_scoring_connections_ops.py` (12) — rolling-vs-official window (65→0), zero-offer UNRATED guard, NO_ANSWER side effects (connections_missed, rolling 45), recording retention exclusive boundary, rating reconciliation (77), ops-run epoch monotonicity
- `test_07_listings_disputes_rbac.py` (14) — IDX_LIMITED gate, listing terminal lockdown, dispute REMOVE/KEEP side effects, Agent/BrokerageUser RBAC denials, PlatformAdmin superset, 401 auth
- `test_08_teams_and_terminal_states.py` (4) — waterfall split (5667/2833 remainder-to-largest-weight), equal-weight split, lead terminal lockdown both directions

### Coverage audit
- §1.8 difficulty queue: **16 of 18 instances translated**, each with ≥2 tests.
- §1.9 corner queue: **all 30 non-stub instances translated** (≥1 test each); both `excluded_because:` stubs left untranslated with verified cross-references.
- Every test has exactly one `Design:` tag resolving to a real instance, and every PRD quote verified verbatim (modulo whitespace) against PRD.md by an automated grep pass.

### Skipped instances (with reasons)
- `Difficulty/priority_pair_validation_conflict/duplicate_window_vs_capacity_conflict` — PRD §2.8 lists a global check ordering, but never narratively names which error surfaces for the *combined* failure (capacity ∩ duplicate on one request); testing the claimed "capacity wins" precedence would violate the `validation-priority` silence rule (both constituent errors already covered individually by other instances).
- `Difficulty/priority_pair_validation_conflict/expired_offer_vs_not_candidate_conflict` — same silence category: PRD states both `ERR_OFFER_EXPIRED` and `ERR_NOT_A_CANDIDATE` triggers but never says expired precedes not-a-candidate for a combined failure; the assertion is not uniquely derivable by a PRD-only reader.

All 87 tests collect cleanly under pytest (imports resolve, no fixture errors).

## Step 6: Generate implementation — 2026-09-29T22:12:30.000Z

All flows verified, including the trickiest cascades. The implementation is complete.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3078_agent_lead_marketplace_zip_code_share_allocation/workspace/implementation/`):

| File | Lines | Contents |
|---|---|---|
| `app.py` | ~1448 | Flask entry point, error handlers, all 85 routes |
| `core.py` | 215 | Envelope/response helpers, auth middleware, validators, in-memory store, logical clock |
| `logic.py` | 233 | Calculations: `share_price_quote`, `agent_performance_score` (rolling + snapshot), `team_charge_split`, `refund_credit`, `display_rule_check`, `lead_allocation`, `lead_assignment_selector`, `team_member_pick`, charge finalize/credit reversal |
| `start.sh` | 7 | Guarded pip install (`import flask` check) + `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `flask>=3.0` |

**Endpoints implemented** — all 80 routes from the SCAFFOLD endpoint table: clock, ops-runs, markets (incl. price-quote/suspend/reopen), brokerages, agents (suspend/unsuspend/deactivate), team-accounts + memberships, share-orders (payments with `expected_market_version` OCC, pause/resume/cancel), leads (intake with duplicate guards + deterministic share-proportional routing + top-3 offers, manual assign, close, operator cancel), lead-assignments (accept with `expected_lead_version` OCC), live-connections (bridge/record with consent/no-answer/dropped, auto-suspend on 3 consecutive NO_ANSWER), ratings, credit-claims (INVALID full / DUPLICATE half credits with per-member reversal), listings (display-rule gate at ingest + review, withdraw), disputes (KEEP/REMOVE/REASSIGN/REJECTED_DISPUTE), performance-snapshots, and all nested/scoped GET list endpoints.

**Key spec decisions**: envelope `{meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}, response_type, data{error_id, message}}`; timestamps formatted from the logical clock (boot default 2026-09-01T00:00:00Z, 3 fractional digits); integer-cents math with floor for prices/half-credits and round-half-up for scores; OCC optional-checked only on the two guarded endpoints; store starts empty, no seeding.

**Boot sanity check**: started via `bash start.sh` on ports 19378–19382, verified health/401, market create, price quote (tier 1 → 5000/500000), stale-version 412, activation moving market allocated_bps 0→2000 and version 1→2, lead ROUTED with top-3 offer, duplicate 422, accept → connection → recording → LIVE_CONNECTED → CLOSED_CONVERTED → claim APPROVED 5000 credit, ops-run snapshot (score 85), team waterfall split (225/675 on 900 charge), offer-expiry sweep → pool exhausted → UNASSIGNED with full credit reversal (members back to 0), and order expiry → COMPLETED with market allocation released. Each server instance killed by its exact PID afterward.

## Step 7: Test-fix iteration loop — 2026-09-29T23:10:00.000Z

Final state: all 8 parallel rounds pass 85/85.

## Summary

**Iterations run:** 5 eight-round sweeps (40 round-results total; final sweep: 85/85 in all 8 rounds).

**Tests deleted (2):**
- `test_payment_against_suspended_market_rejected_then_reopen_allows` (test_03) — ENUM/BRANCH coverage collapse: PRD §3.1 says a SUSPENDED market accepts "no new share orders, no new leads, and no new listings"; it never says payment capture on an existing order is blocked, so asserting `ERR_MARKET_SUSPENDED` on capture is not uniquely derivable (a PRD-faithful reader could allow it). Scaffold's `share_order_activation_depends_on_market_open` instance drove the test.
- `test_activation_blocked_while_suspended_no_allocation` (test_03) — same PRD silence / same scaffold instance.

**Fixes applied to `test_helpers/`:**
- `factories.py` — `create_lead_payload` and `create_live_connection_payload` no longer default `listing_id`/`listing_agent_id` to None; PRD §3.4/§3.8 require both. Factory signature now takes them explicitly.
- `fixtures.py` — added `create_active_listing` (creates + approves a listing via the PRD review flow); `create_routed_lead` now requires a listing; `setup_assigned_lead` creates one internally and returns it (7-tuple); `setup_team_with_order` gains `include_lead_membership` + `base_lead_price_cents` params, returns the listing (8-tuple), and creates memberships at distinct clock seconds so PRD §3.6's created_at tie-break is deterministic (this eliminated the flakiness in rounds 3/6/7 of sweep 4).
- `fixtures.py` review call uses `outcome: "APPROVE"` per PRD §3.1 wording ("an `outcome` of approve or reject").

**Fixes applied to `test_suite/`:**
- test_01: added missing `setup_assigned_lead`/`create_active_listing` imports; lead-pagination tests now create a listing; fixed 7-tuple unpacking.
- test_03: `test_pause_releases_capacity...` — changed filler order from 4000 to 4001 bps (PRD §2.5 rejects only aggregates *over* 10000; 6000+4000=10000 must succeed); `test_stale_expected_market_version...` — the fixture's market re-read returns the post-activation version, so the stale version is `market["version"] - 1`.
- test_04: duplicate-window tests now route the repeat ingestion through a different listing agent (PRD §3.4's same-agent guard has no time window, so reusing the same `listing_agent_id` would reject forever); reroute/pool tests now use a team order with 6 members (PRD §3.4: solo orders cover only the buyer — the scaffold's "7 eligible agents" recipe contradicted this); imports updated.
- test_05: 8 call sites updated for the 7-tuple; `test_order_expiry_releases_share_and_reprices_market` now asserts `unit_price_cents == 9500` (PRD §3.3: 4000 bps is the 5% band; the old 10000 contradicted PRD).
- test_06: 8 call sites updated; `_start_bridging_connection` sends the lead's real `listing_agent_id` (PRD §3.8 requires it).
- test_07: review outcomes `"APPROVED"/"REJECTED"` → `"APPROVE"/"REJECT"` per PRD §3.1; `test_idx_limited_blocks_out_of_state_broker_direct_listing` now targets the ingestion-time gate (PRD: "the same check applies at ingestion time as a defensive gate" — creation of a violating listing fails with `ERR_LISTING_DISPLAY_VIOLATION`, so no listing ever existed to review); the two listing-terminal tests relax the exact error to `validate_error_is_one_of([ERR_ALREADY_TERMINAL, ERR_INVALID_STATE])` (PRD lists both at 409 but never maps listing terminal rejections to a specific id).
- test_08: waterfall test uses share_bps=4000/no-lead-membership so the 9500 charge leaves a real 1-cent remainder (6334/3166) exercising PRD §3.6's reconciliation; equal-weights test uses base 10001/share 600 → charge 10001 → 5001/5000 (both now assert exact per-member remainder allocation per the PRD tie-break, no longer even splits).

**Fixes applied to `implementation/`:**
- `core.py` — added internal `EVENTS` audit list (never serialized).
- `logic.py` — added `record_event`/`windowed_counters`; **bug fix:** `recompute_rolling` no longer rewrites `performance_tier` from the stale `official_score` (PRD §3.7: the official variant is computed only at ops-run time and drives the tier; the rolling variant is separate). This bug had been silently flipping agents to INELIGIBLE after their first offer, poisoning every later routing/manual-assign.
- `app.py` — all seven scoring mutations (offer received/expired/accepted, response latency, closes, no-answer, ratings) now append windowed events; ops-run snapshots and `official_score`/tier now compute from `windowed_counters(agent, last_run_at, run_at)` instead of all-time counters, per PRD §3.7's window definition.

## Step 8: Finalize PRD — 2026-09-29T23:25:00.000Z

PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_3078_agent_lead_marketplace_zip_code_share_allocation/workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md 387 lines, PRD_FINALIZED.md 387 lines, 0% line-count delta (8 lines modified in place, no lines added/removed).

**Changes (one bullet each):**
- §3.1 — revise — suspended-market scope: added "no new team accounts" to the blocked list and pinned that payment capture against an existing order in a suspended market is NOT blocked — `app.py:371` (team creation gate), `app.py:528-577` (capture_payment has no market-status check).
- §3.1 — revise — listing review outcome values pinned to `APPROVE`/`REJECT` (impl accepts those case-insensitively; lowercase remains acceptable under the impl's normalization but the canonical values are now explicit) — `app.py:1199,1205`.
- §3.1 — insert — lead intake requires the referenced listing to exist and be `ACTIVE`; intake against `PENDING_REVIEW`/`REJECTED`/`WITHDRAWN` listings is rejected — `app.py:637,641-644`.
- §3.4 — revise — pinned that the same-agent duplicate guard has no time window and fires regardless of anchor age — `logic.py:199-202` (same-agent loop has no window check, unlike the window loop at `logic.py:203-205`).
- §3.7 — revise — scoring-event enumeration extended to include "an offer received" — `app.py:683-687` (offer creation increments counters, records event, recomputes rolling).
- §3.7 — revise — pinned that `performance_tier` changes only at ops-run time; rolling-score recomputation never touches the tier — `logic.py:67-72` (`recompute_rolling` sets only `rolling_score`), `app.py:148-152` (tier set only in the ops-run snapshot step).
- §3.7 — revise — pinned tier thresholds: score >= 80 HIGH, 60-79 STANDARD, 40-59 LOW, below 40 INELIGIBLE — `logic.py:57-64`.
- §3.8 — revise — `listing_agent_id` described as the listing-side agent's id; pinned that the same-agent duplicate guard (no time window) also applies to live connections — `logic.py:199-202` via `app.py:954`.

**Step-7 items judged to need no PRD edit:** capacity-boundary "over 10000" (PRD §2.5 already says "over", so 6000+4000=10000 succeeding is PRD-consistent), expected_market_version staleness (PRD §2.7/§3.3 already pin exact-match semantics), team-charge waterfall tie-breaks (PRD §3.6 already pins weight-desc/created_at-asc), 5%-discount band at 4000 bps (PRD §3.3 already pins "< 2500 / >= 2500 < 5000 / >= 5000"), listing-terminal rejection error ids (impl agrees PRD is silent; loosened wording would be inventing behavior), `ERR_VALIDATION` for the review `state_code` format etc. (all already covered), and the internal EVENTS audit list (impl-internal, not API-visible).

**Pre-edit search log:**
1. Market suspension scope — (a) subject: which operations `ERR_MARKET_SUSPENDED` blocks; (b) enumerated: grep `ERR_MARKET_SUSPENDED|market_status` over app.py/logic.py/core.py → gates at app.py:371 (team create), 486 (order create), 639 (lead intake), 1165 (listing create); confirmed absent from capture_payment (528-577), pause (580-593), resume (596-610), cancel (613-623), review_listing (1194-1215), withdraw_listing (1218-1229), manual_assign (719-768), create_connection (931-965); (c) widened the blocked list to include team accounts and added the explicit payment-capture carve-out rather than claiming "all operations on existing resources continue".
2. Review outcome enum — (a) subject: accepted `outcome` values for `/listings/{id}/review`; (b) enumerated: app.py:1199 (`{'approve','reject','APPROVE','REJECT'}`), app.py:1205 (case-insensitive branch); checked no other endpoint uses "outcome" for reviews; (c) pinned canonical uppercase values, kept wording minimal to avoid claiming lowercase is rejected (impl accepts it).
3. Listing-status gate on lead intake — (a) subject: which listing statuses permit lead ingestion; (b) enumerated: app.py:637-644 (only `ACTIVE` accepted), listing lifecycle at app.py:1175 (`PENDING_REVIEW`), 1210/1212 (review outcomes), 1226 (withdraw), 1317 (dispute REMOVE); no other lead-ingestion path exists (`create_lead` → `_ingest_lead` only); (c) none — wording matches the single gate exactly.
4. Same-agent duplicate guard window — (a) subject: temporal scope of the same-agent guard; (b) enumerated: logic.py:189-206 (`find_duplicate`: same-agent loop lines 200-202 has no window check; window loop lines 203-205 checks 30 days), callers app.py:646 (lead intake) and app.py:954 (live connection); (c) added "has no time window, applies regardless of anchor age" in §3.4 and cross-referenced it in §3.8 so both call sites are consistently described.
5. Scoring-event enumeration — (a) subject: which mutations count as scoring events recomputing scores; (b) enumerated all `record_event` call sites: app.py:87 (offers_expired sweep), 685 (offers_received intake), 758 (manual assign), 788/791 (closes), 914/918 (accept + latency), 1017 (no-answer), 1065/1066 (ratings), plus `recompute_rolling` at each site; (c) added "an offer received" to the event list; did not enumerate internal-only events beyond what the impl exposes behaviorally.
6. Tier mutation timing — (a) subject: when `performance_tier` changes; (b) enumerated: logic.py:67-72 (rolling recompute touches only `rolling_score`), app.py:149-152 (tier written only in ops-run snapshot step), agent creation app.py:292 (initial UNRATED), candidate selector logic.py:180 (reads tier); (c) added the sentence clarifying tier changes only at ops-run time.
7. Tier thresholds — (a) subject: official-score-to-tier mapping; (b) enumerated: logic.py:57-64 (sole definition), app.py:152 (sole writer), logic.py:180/185 (tier consumed by selector), TIER_RANK logic.py:36; (c) none — thresholds stated exactly as implemented.
8. Live-connection listing_agent_id — (a) subject: semantics of `listing_agent_id` on connection requests; (b) enumerated: app.py:938-959 (required, agent-existence check, duplicate guard), logic.py:189-206 (guard semantics), app.py:1007-1009 (no use in record path); (c) mirrored the §3.4 wording ("listing-side agent") and noted the windowless same-agent guard applies here too.

## Step 9: Complete PRD scan — 2026-09-29T23:48:00.000Z

All edits are in place. Done — summary below.

## Summary

**Files:** `/home/ubuntu/github/CodingPRD/tasks/task_3078_agent_lead_marketplace_zip_code_share_allocation/workspace/PRD_FINALIZED.md` (387 lines, 56,757 chars) → `PRD_COMPLETED.md` (391 lines, 65,834 chars; +4 lines, +9,077 chars, 36 changed paragraphs). All changes are inline paragraph inserts/revisions; no new sections, no behavior invented beyond what `implementation/` exhibits.

**Counts:** 32 ambiguity-pins (insert), 4 mismatch-revisions (revise).

### Changes (per section)

- §2.2 Standard Success Response — insert — ambiguity — pinned the exceptions to "returns the mutated resource": payments endpoint returns the `Payment`, live-connection record returns the `CallRecording` on success and `{}` for `NO_ANSWER`/`DROPPED`, ops-run returns the `OpsRun`, clock-set echoes `current_utc` — implementation/app.py:65,161,577,1010,1028,1032
- §2.3 Pagination — insert — ambiguity — `limit`/`offset` out-of-range values are clamped (not rejected); non-integer values are `ERR_VALIDATION`; list tie-break by `id` ascending — implementation/core.py:94-104,195-200
- §2.4 Logical Clock — insert — ambiguity — clock-set accepts any well-formed ISO 8601 (naive = UTC), no monotonicity enforcement; first ops run's window has no lower bound (`window_start_at` null) — implementation/app.py:55-65,136-146
- §2.4 OpsRun — insert — ambiguity — (same edit as above) first-run window semantics — implementation/app.py:142
- §2.7 OCC — insert — ambiguity — `expected_*_version` fields are advisory (omitted = skip check); a rejected capture persists no `Payment`; staleness checks run after amount checks — implementation/app.py:537,551,890,901,554-556
- §2.10 Common Properties — insert — ambiguity — `version` starts at 1 on creation — implementation/core.py:179
- §3.1 Markets — insert — ambiguity — new market initializes `allocated_bps`=0, `available_bps`=10000, `current_unit_price_cents`=tier-1 quote for 100 bps (= `base_lead_price_cents`) — implementation/app.py:184-190
- §3.1 Listing review — insert — ambiguity — review `outcome` accepts lowercase `approve`/`reject` as equivalent — implementation/app.py:1199,1205
- §3.1 Withdrawal — insert — ambiguity — dispute-driven REMOVE writes the fixed compliance note "Removed via dispute resolution" — implementation/app.py:1318
- §3.2 Agent suspend/unsuspend — insert — ambiguity — suspend requires `ACTIVE` (else `ERR_INVALID_STATE`; `ERR_ALREADY_TERMINAL` for `DEACTIVATED`); unsuspend requires `SUSPENDED` — implementation/app.py:320-323,333-334
- §3.2 Auto-suspension — insert — ambiguity — three consecutive `NO_ANSWER` measured over recorded bridge outcomes; `COMPLETED`/`DROPPED` resets the streak — implementation/app.py:1019-1025
- §3.2 Team accounts — insert — ambiguity — enumerated the caller-activity-gated actions (`ERR_AGENT_SUSPENDED` for suspended/deactivated callers); dissolved-team check precedes team-lead check on dissolve/membership-create — implementation/app.py:364,391-396,418,428-431,451-457
- §3.2 Memberships — insert — ambiguity — pinned how "consistent with the team's market scope" is realized: agent license_state vs market state_code, enforced at team-order purchase (`team_id` must name a team led by the buyer and scoped to the order's market) and by selector/manual-assignment checks, not at membership creation — implementation/app.py:490-494,432-434
- §3.3 Share purchase — insert — ambiguity — `buyer_agent_id` must equal the acting agent (else `ERR_UNAUTHORIZED`) — implementation/app.py:484-485
- §3.3 Payment capture — insert/revise — mismatch — pinned endpoint order-status gate (`PENDING_PAYMENT`/`ACTIVE`, else `ERR_INVALID_STATE`), response returns the `Payment`, staleness runs after amount checks, duplicate `SUCCEEDED` payment and capacity-failed capture leave no `Payment` row, `DECLINED` activation still records a `Payment`, amount must be positive — implementation/app.py:528-577
- §3.3 Settlement — insert — ambiguity — settlement requirement is `charged_cents − paid_cents` (credits not netted); `DECLINED` settlement is recorded with no ledger effect — implementation/app.py:546,572-576
- §3.4 Duplicate guards — insert — ambiguity — same-agent match wins as recorded anchor when both guards fire — implementation/logic.py:199-205
- §3.4 Routing walk — insert — ambiguity — hash pinned as SHA-256(utf-8 consumer_key) as integer mod total share_bps; sort tie-break by `id`; fallback to last sorted order if no cumulative reaches the key — implementation/logic.py:148-164
- §3.4 LeadAssignment — revise — mismatch — `candidate_agent_ids` holds up to three ids (may be fewer when pool is smaller), never empty on the intake path — implementation/logic.py:186,209-221
- §3.4 LeadAssignment — insert — ambiguity — `id` tie-break in candidate ranking; every candidate's `offers_received` increments and `rolling_score` recomputes at offer creation — implementation/logic.py:185, app.py:683-687
- §3.4 Pool empty — insert — ambiguity — covers both no-ACTIVE-orders and no-eligible-candidates cases — implementation/app.py:662-673
- §3.4 Charge timing — insert — ambiguity — charge finalization posts at the routing instant — implementation/app.py:688
- §3.5 Offer acceptance — insert — ambiguity — staleness runs last; assignment not `OFFERED` or lead not `ROUTED` → `ERR_INVALID_STATE`; `expires_at` == now is expired; response seconds are whole seconds (sub-second latency contributes zero) — implementation/app.py:891-902,915-918
- §3.5 Sweep reroute — insert — ambiguity — reroute only attempted when lead still `ROUTED`; missing order also forces UNASSIGNED-with-credit — implementation/app.py:90-111
- §3.5 Operator cancel — insert — ambiguity — cancelled lead records `routing_note` "pool exhausted" — implementation/app.py:810
- §3.5 Manual assignment — insert — ambiguity — covering order picked by `created_at`/`id` order; cancels open `OFFERED` assignment; retargets `share_order_id`/`team_id`; increments `offers_accepted` with no response seconds; posts charge if not already charged; does not re-increment `leads_received` — implementation/app.py:733-767
- §3.6 Charge finalization — insert — ambiguity — chargeable moment = routing instant (or manual-assign instant); posted amount = order's locked `unit_price_cents`; credit reversal scales member shares by credit/charge ratio, rounded half-up — implementation/logic.py:226-244,247-265, app.py:1127-1136
- §3.7 Scoring — insert — ambiguity — "50 minutes" pinned as 3000 seconds — implementation/logic.py:46-48
- §3.7 Snapshots — insert — ambiguity — ops run also writes `official_score` onto the agent and re-derives `performance_tier` (zero `offers_received` → `UNRATED`) — implementation/app.py:148-153
- §3.8 Live connection request — revise — mismatch — dropped the claim that `consumer_key` must match the lead's recorded key (impl performs no such equality check; mismatched values only feed the duplicate guard) — implementation/app.py:931-959
- §3.8 Live connection request — insert — ambiguity — `listing_agent_id` must resolve to an existing agent; the connection's own lead never anchors its own duplicate rejection — implementation/app.py:940,955
- §3.8 Bridge recording — insert — ambiguity — `duration_seconds` ≥ 0 (negative → `ERR_VALIDATION`); caller must be the connection's `agent_id` (else `ERR_UNAUTHORIZED`); success returns the `CallRecording`, `NO_ANSWER`/`DROPPED` return empty data; `DROPPED` does not increment `connections_missed` and resets the streak — implementation/app.py:988-1032
- §3.8 Recording purge — insert — ambiguity — purge horizon is strictly in the past (`<` now) — implementation/app.py:131
- §3.9 Close — insert — ambiguity — terminal leads rejected with `ERR_ALREADY_TERMINAL`, other non-closable statuses with `ERR_INVALID_STATE` — implementation/app.py:778-781
- §3.9 Credit claims — revise — ambiguity — eligibility pinned to "lead has actually been charged" (impl checks the posted charge, not a status whitelist) — implementation/app.py:1083-1087
- §3.9 Claim resolve — insert — ambiguity — resolution body values `APPROVED`/`REJECTED`; other values → `ERR_VALIDATION` — implementation/app.py:1106-1110
- §3.10 Dispute resolve — insert — ambiguity — dispute must still be `OPEN` (else `ERR_INVALID_STATE`) — implementation/app.py:1299-1300
- §3.11 Ops sweep step 3 — insert — ambiguity — `ends_at` exactly equal to now counts as reached — implementation/app.py:115
- §3.11 Ops sweep steps 4-5 — insert — ambiguity — strict `<` purge; snapshot step also updates `official_score` and tier — implementation/app.py:131,148-153
- §5 Error Catalogue — insert — ambiguity — added `ERR_NOT_FOUND` (404, generic unrouted-path/method fallback) and `ERR_INTERNAL` (500) rows — implementation/app.py:26-38

## Post-pipeline verification — 2026-09-29T23:52:00.000Z

Re-ran a single-round `prd-bench-local-run --isolation per-test-server` verification after Steps 8/9 (PRD-level edits only, no code changes): **85/85 passed, 0 failed, 0 errors, 0 skipped** (156.9s). Results file: `workspace/implementation/results.verify.json`.
