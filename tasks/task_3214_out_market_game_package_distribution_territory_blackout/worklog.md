# Worklog — task_3214_out_market_game_package_distribution_territory_blackout

## Step 1: Create task directory — 2026-09-30T10:55:00.000Z

Task directory pre-allocated by command args; verified `./tasks/task_3214_out_market_game_package_distribution_territory_blackout/workspace/` exists. No new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T11:22:00.000Z

All three artifacts are complete and pass the linter cleanly.

**Files written** (task directory `/home/ubuntu/github/CodingPRD/tasks/task_3214_out_market_game_package_distribution_territory_blackout/`):

- `SCAFFOLD.yaml` — 1771 lines. §1.0 envelope (verbatim) + §1.1–§1.7.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1321 lines. Single top-level key `scaffold_difficulty_design`; all 9 rules × 2 instances = 18 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3322 lines. Single top-level key `scaffold_corner_design`; 9 sections, 40 active instances + 1 excluded stub (551 calls lint-scanned).

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Key design decisions:**

- **Complexity profile:** primary archetype `access_control_matrix` (territory entitlement gating) blended with `temporal_windowing` (weekly slates, offer windows, grace windows); layers: posture-driven gating (Season.phase), derived-field reconciliation (WeekSlate snapshots), scheduled/deferred actions (logical clock), optimistic concurrency, cascading side effects, rate/threshold triggers. Flat topology — `api_prefix: ""` with filtered-list FK reverse reachability (the lint's sub-resource derivation only matches paths nested under the prefix, so sub-resource GETs were added then replaced by the filtered-list form).
- **Entities (15):** RightsGrant, Season, Market, Game, WeekSlate, Offer, Account, StudentVerification, VenueLicense, Subscription (parallel state dimensions `status` × `entitlement_state`), Payment (append-only), TerritoryCheck (append-only evidence), GameEntitlement, ComplaintCase (OPEN⇄ESCALATED cycle), EntitlementOverride (grantor-only rescind).
- **State machines (10):** WeekSlate has a correction cycle PRELIMINARY→FINALIZED→PRELIMINARY plus FINALIZED self-transitions and terminal LOCKED gated on first kickoff; Subscription is a parallel-dimension machine; RightsGrant termination drives a depth-4 cascade (grant→season→subscription→entitlement, plus venue-license sibling cascade).
- **Calculations (10):** dual-variant pairs on different domains — `charged_price` (pinned discount-before-proration order; verified 9999¢/10%/wk-4-of-17 → 6882 vs 6881 reversed) and `effective_market` (device-preferred vs billing-authoritative for flagged accounts); `game_availability` set-difference with slate-posture branching; `proration_factor` remaining-vs-elapsed anchors; `blackout_refund_amount` weekly-value waterfall (16667/15 → 1111); venue fee tiers with inclusive boundaries (100=T1/500000, 101=T2/2000000).
- **Concurrency (3 true OCC races):** stale-version guards on `week-slates/selections`, `week-slates/finalize`, `seasons/advance-phase` (412s).
- **Difficulty instances** pin computed literals throughout (16667, 1111, 25000, 6882, 15556, fee-tier boundaries) and every `${var}` traces to a declared `captures:` binding; two test-driving endpoints (`/_clock/set_current_utc` with fixed default 2026-09-01T00:00:00Z, `/_payments/simulate`) make all time- and payment-gated states reachable from empty DB.

## Step 3: Copy shared files — 2026-09-30T11:23:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3214_out_market_game_package_distribution_territory_blackout/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T11:31:00.000Z

All three contracts verified. Final document state confirmed.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3214_out_market_game_package_distribution_territory_blackout/workspace/PRD.md` — 336 lines (~51 KB).

**Section list:**
- §1 Introduction (3 paragraphs; scenario rewritten from business-context angle, logical-clock default stated here)
- §2 Global Specifications: 2.1 Roles/Auth, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common Resource Properties & Mutation Ledger, 2.5 Markets/ZIP Prefixes/Territory Resolution, 2.6 Monetary Values & Rounding, 2.7 Optimistic Concurrency Control, 2.8 Nested Path Validation & Validation Ordering (full 22-priority list rendered explicitly)
- §3 Business Logic (11 subsections, organized by lifecycle/actor): 3.1 Rights Grant cascade, 3.2 Seasons & phase machine, 3.3 Markets & game scheduling, 3.4 WeekSlate & national selections (PRELIMINARY/FINALIZED/LOCKED cycle + entitlement sweep), 3.5 Accounts/Offers/pricing (3-step pinned charged-price), 3.6 Territory checks (dual-variant effective market + verdict chain + override supremacy), 3.7 Complaints & refund waterfall, 3.8 Venue licensing & commercial-misuse enforcement, 3.9 Student verification, 3.10 Entitlement overrides, 3.11 Multiview & features read
- §4 Endpoint table (4 columns; 71 rows, mechanically verified equal to scaffold endpoint set)
- §5 Error catalogue (2 columns; 25 rows, verified equal to scaffold error set)

**Contract reports:**
- Contract 1 (field-name coverage): 84 required (entity fields + endpoint inputs + pagination params), 84 present, 0 missing — PASS (after adding `current_utc`, `phase`, `slate_status` mentions found in pass 2).
- Contract 2 (rule coverage): all 22 validations expressed in §2.8 with priority ordering plus trigger-adjacent prose; all 3 OCC rules named with occ field + exact error id + HTTP 412; all state-machine transitions (including both WeekSlate self-transitions, both Subscription parallel-dimension self-transitions, both cyclic ComplaintCase edges, and the SUSPENDED→CERTIFIED reinstate-lands-certified quirk) expressed; all 10 calculations rendered as reconstructible prose (tier boundaries 100/101/500/501, fee constants, MAX_MULTIVIEW_SESSIONS=2 with cap-minus-one boundary, grace-days inclusive boundary, charge/refund proration asymmetry, student-discount-before-proration ordering); cross-entity cascades stated per leg. PASS.
- Contract 3 (§3 path purity): 464 backtick tokens scanned, 0 path/method violations — the 6 `POST` matches are the Season `phase` enum value, not the HTTP method. PASS.

**Scaffold rules deliberately softened into prose:**
- `market_for_zip` uniqueness-impossibility note rendered as "one prefix may appear in at most one market across the entire system" tied to `ERR_MARKET_PREFIX_OVERLAP`.
- Proration variants expressed as prose ("weeks *p* through the final week inclusive"; "weeks before the purchase week") rather than the `(W - p + 1)/W` formulas.
- Week window rule ("kickoff inside the owning week's window") expressed as "the seven-day span of that week counted from `season_start_date`" since scaffold defines no explicit window computation.
- Multiview session storage ("tracked in-memory per account") omitted as an implementation detail; the contract surface (cap, ordering, no auto-eviction, returned `multiview_session_id`/`active_count`) is fully stated.
- `Payment.reason` optionality on CHARGE rendered as "may omit it."

One scaffold inconsistency noted and resolved conservatively: validation §1.4 priority 13 lists `PUT /markets/{id}` under `applies_to` but §1.5 defines no such endpoint; I followed the endpoint table (no PUT /markets row in §4) and expressed prefix-overlap for create/update in §2.5 prose only.

## Step 5: Generate unit tests — 2026-09-30T11:58:00.000Z

Generation complete for `task_3214_out_market_game_package_distribution_territory_blackout`.

**Files written (4949 lines total):**

`test_helpers/` — 9 files:
- `types.py` (346) — 16 TypedDicts + 17 enums; Payment/TerritoryCheck correctly typed as append-only (no `updated_at`/`version`)
- `api_client.py` (360) — 48 endpoint methods on `ApiClient(GenericApiClient)`, matching PRD §4
- `api_errors.py` (67) — 25 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` (144), `factories.py` (111), `constants.py` (41), `test_users.py` (42, with `make_subscriber_headers`/`make_venue_manager_headers` entity-backed builders), `fixtures.py` (257, scenario-spine composite helpers), `__init__.py` (80 barrel)

`test_suite/` — 13 files: `conftest.py` (45) + 12 test files, **95 tests**, every one tagged with exactly one `Design:` line.

**Queue A (Difficulty) — 18/18 instances emitted, ≥2 tests each (40 tags):** all 9 rules covered (dual_variant_calc ×2, combinatorial_formula ×2, non_linear_state_machine ×2, transitive_cascade ×2, priority_pair ×2, boundary_precision ×2, cross_entity_state ×2, resource_temporal ×2, compensating_invariant ×2). Zero skipped.

**Queue B (Corner) — 41/41 non-stub instances emitted, ≥1 test each; 1 stub (`errors/every_catalogued_error_is_triggerable`) correctly not translated** (its `difficulty_instance` cross-reference resolves; the individual error triggers live in other corners). Zero skipped.

**Self-audit results:**
- Stage 1/2 syntax: all 22 files parse.
- Design tags: 95 tags, all resolve to real instances; no untagged, dual-tagged, or stub-tagged tests.
- PRD citation sweep: all quoted docstring fragments (normalized for backticks/markdown-emphasis/whitespace) survive a literal grep of `workspace/PRD.md` — 0 misses.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in comments/docstrings.
- All `from test_helpers import …` names resolve through the barrel.

**Notable PRD-first adjudications:** second-cancel and double-rescind tests assert 409 accepting `ERR_ALREADY_TERMINAL | ERR_INVALID_STATE` (PRD's terminal-vs-wrong-state taxonomy is not uniquely derivable per endpoint); the suspended-account effective-market leg asserts `verdict == NO_ENTITLEMENT` (the unique outcome once the misuse flag suspends entitlements — the design recipe's `AVAILABLE` assertion contradicts the PRD's entitlement-gate-first chain and was not emitted); the priority-pair window-vs-category leg asserts the exact `ERR_COMPLAINT_WINDOW_EXPIRED` because PRD §2.8 explicitly pins "(16) is evaluated before the category gate (17)".

## Step 6: Generate implementation — 2026-09-30T12:20:00.000Z

Implementation complete and verified end-to-end.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3214_out_market_game_package_distribution_territory_blackout/workspace/implementation/`):

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | Foreground launcher, guarded `pip install`, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0,<4` |
| `app.py` | 51 | Flask entrypoint, blueprint registration, error handlers |
| `db.py` | 69 | In-memory stores, logical `Clock` (boot default 2026-09-01T00:00:00Z), ISO parse/format (3 fractional digits) |
| `errors.py` | 136 | `APIError` + one constructor per scaffold error id |
| `response.py` | 73 | Envelope: `meta`/`response_type`/`data`, error body, pagination meta |
| `middleware.py` | 47 | `X-User-ID`/`X-User-Role` auth + role gating decorator |
| `paginate.py` | 47 | `limit`/`offset` parsing (default 10, min 1, max 100), window slicing |
| `validate.py` | 98 | Payload shape validators → `ERR_INVALID_REQUEST` |
| `services.py` | 372 | Shared logic (below) |
| `routes/` | 16 files | One module per resource group (clock+payments, rights-grants, seasons, markets, games, week-slates, offers, accounts, student-verifications, venue-licenses, subscriptions, territory-checks, game-entitlements, complaint-cases, entitlement-overrides, multiview-sessions) |

**Notable implementation decisions**

- **Logical clock**: `db.Clock` defaults to exactly `2026-09-01T00:00:00Z`, never wall-clock. `POST /_clock/set_current_utc` sets it and runs `run_auto_transitions()` (grant `ACTIVE→EXPIRED` past `effective_until`, student-verification `VERIFIED→EXPIRED` past `valid_through`), with the full depth-4 grant cascade (seasons → POST, subscriptions → CANCELLED/REVOKED, entitlements → WITHDRAWN/ENTITLEMENT_REVOKED, venue licenses → REVOKED).
- **OCC**: `expected_slate_version` on selections/finalize (`ERR_STALE_SLATE_VERSION`, 412) and `expected_season_version` on advance-phase (`ERR_STALE_SEASON_VERSION`, 412); only checked when the field is present.
- **Pricing**: `Decimal` with `ROUND_HALF_UP` at each pinned step — student discount applied to full-season base before proration (step 1 before step 2), `purchase_week_index` clamped to `[1, W]`.
- **Refund waterfall**: `weekly_value = round_half_up(price_charged / (W - p + 1))`; refund = `min(weekly, paid_amount)`, rejected (422) when CANCELLED/0/over-paid. Guards evaluated in §2.8 order: window (16) → category (17) → floor (18).
- **Territory verdict chain**: NO_ENTITLEMENT → NOT_IN_PACKAGE (slate FINALIZED/LOCKED via `finalized_game_ids`, PRELIMINARY via live `national_game_ids`) → BLACKED_OUT → AVAILABLE, with `EntitlementOverride` ACTIVE forcing AVAILABLE as the final step. Effective market: device-preferred when account ACTIVE, billing-authoritative when SUSPENDED.
- **Storage**: plain dicts keyed by UUID; store starts empty on every boot — no seeding anywhere. `Payment`/`TerritoryCheck` rows carry only `id` + `created_at` (append-only, no `updated_at`/`version`); all other resources carry the common quartet.
- **Fresh-boot safety**: smoke-tested `start.sh`-equivalent boot from a fresh process four times (register, full purchase/payment/territory chain, slate lifecycle + OCC + entitlement sweep + lock, complaint refund + multiview cap); all matched spec, including boundary behaviors (412 before lock check, restore-on-remove only for `NATIONAL_SELECTION`, refund reducing `paid_amount_cents`, cap rejection at 2 active sessions).

## Step 7: Run tests and iterate — 2026-09-30T12:42:00.000Z

All 8 rounds pass 95/95. Clean sweep.

**Iterations run:** 3 sweeps (8 parallel rounds each, per-test-server isolation).

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_01_pricing.py` — `test_student_tier_base_computed_before_proration`: the expected constant 6882 used 13 received weeks (`W - p`), contradicting PRD §3.5's verbatim formula "regular_season_weeks minus the purchase week index **plus one**" (14 weeks at p=4, W=17) and its own sibling test asserting `purchase_week_index == 4`. Corrected to 7411 and added a genuinely order-discriminating second case (base 9998: discount-then-prorate 7410 vs prorate-then-discount 7411), parametrizing `_student_setup` with an `email` arg to avoid the PRD-required account-email uniqueness collision.

2. `test_suite/test_09_entities_structure.py` — `test_terminal_states_lock_down_grant_and_slate`: (a) the test locked the slate while the logical clock (2026-08-20) was before the week's first kickoff (2026-08-23T17:00Z), which PRD §3.4 says must be rejected — added `set_clock("2026-08-24T00:00:00Z")` before the lock; (b) the reopen-on-LOCKED assertion expected `ERR_ALREADY_TERMINAL`, but PRD §3.4 verbatim states "reopen attempts against a locked slate are rejected with `ERR_SLATE_LOCKED`" — corrected the expected error id (lock-on-LOCKED stays `ERR_ALREADY_TERMINAL` per §2.8).

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:**

1. `implementation/routes/week_slates.py` — `slate_selections`: accept `action` case-insensitively (`add`/`remove`/`ADD`/`REMOVE`, normalized lowercase). PRD §3.4 writes the value as bare prose "(add or remove)" while every other enum literal in the PRD is UPPERCASE; casing is not uniquely pinned, so accepting both resolves the ambiguity without adding capability. This fixed 12 of the 18 failures.

2. `implementation/services.py` — `venue_grant_cap`: previously linked accounts to grants only via subscriptions, but PRD §3.5 forbids COMMERCIAL accounts from holding any subscription, which made the §3.8 occupancy cap ("checked again at certify and recertify") vacuous. Now falls back to the minimum cap across all grants when no subscription linkage exists. Fixed `test_occupancy_at_cap_admitted_above_cap_rejected`.

3. Same file — `cascade_grant_end`: the §3.1 depth-4 cascade ("every venue license held by accounts of this distributor is `REVOKED`") now also sweeps venue-holding accounts with no subscription linkage to any other grant (commercial accounts cannot be subscription-linked, per above). Fixed `test_terminate_cascades_through_season_subscription_entitlement_license`.

**Final state:** 95/95 passing in all 8 parallel rounds, zero flakiness.

## Step 8: Finalize PRD — 2026-09-30T12:48:00.000Z

All three edits applied cleanly, line count unchanged (edits are inline within existing paragraphs). One more consistency check on my edit-2 wording against the impl: `venue_grant_cap` returns `min(caps)` where caps are from subscription-linked grants, else min across all grants, else `None`. My wording matches. For edit 3, the impl also skips licenses already `REVOKED` — PRD's "is REVOKED" remains true for those, no conflict.

Done. Summary below.

---

**PRD.md vs PRD_FINALIZED.md:** 335 lines → 335 lines (0% line-count delta; all edits are inline revisions within existing paragraphs, no sections added).

**Changes (3 edits, all traced to `<step_7_diff>` implementation fixes; the two test_suite fixes were pure fixture bugs where the PRD already pinned the behavior — no edit needed):**

- **§3.4** — revise — pinned that the national-selection `action` value is matched case-insensitively (`add`/`ADD`/`remove`/`REMOVE` accepted and normalized) — `implementation/routes/week_slates.py:95`.
- **§3.8** — revise — defined how "the grant that parents the account's activity" is resolved for the occupancy cap: smallest cap among subscription-linked grants; with no subscription linkage (always true for COMMERCIAL accounts), smallest cap across all grants; no grants → no cap, only the >0 rule — `implementation/services.py:266-285` (`venue_grant_cap`), callsites `implementation/routes/venue_licenses.py:30,80,100`.
- **§3.1** — revise — defined "accounts of this distributor" for the depth-4 grant-end cascade: accounts subscription-linked to this grant, plus venue-license-holding accounts with no subscription linkage to any grant; accounts linked only to other grants are not swept — `implementation/services.py:175-195` (`cascade_grant_end`), callsites `implementation/routes/rights_grants.py:75` and `implementation/services.py:217`.

**Per-edit pre-edit search log:**

1. **§3.4 action casing.** (a) Subject: `action` field of `POST /week-slates/{id}/selections`. (b) Enumerated: `week_slates.py:95` (sole `action` site), `validate.py:req_enum`, and all other `req_enum` callsites via grep — accounts (`account_kind`), offers (`plan_tier`), rights_grants (`scope`, `exclusivity`), entitlement_overrides (`reason_code`), clock (`outcome`), complaint_cases (`category`, `decision`), student_verifications (`verification_method`) — all strict-uppercase. (c) Wording scoped explicitly to "the value" of this one field ("matched case-insensitively ... normalized before processing") so no other enum is implicated.

2. **§3.8 occupancy cap.** (a) Subject: grant-cap resolution behind `ERR_OCCUPANCY_CAP_EXCEEDED`. (b) Enumerated: `services.py:venue_grant_cap`, `enforce_occupancy_cap`; callsites `venue_licenses.py:30` (apply), `:80` (certify), `:100` (recertify); confirmed reinstate (`venue_licenses.py:122-135`) performs no cap check, consistent with PRD's existing "checked again at certify and recertify". (c) Included the `min`-across-linked-grants rule and the zero-grants case (cap `None`, only >0 enforced) so multi-grant and empty-grant paths are not mis-described.

3. **§3.1 cascade venue-license sweep.** (a) Subject: which accounts' venue licenses the grant-end cascade revokes. (b) Enumerated: `services.py:cascade_grant_end` lines 175-195 (linkage built from subscriptions; fallback adds license-holding accounts with no linkage to any grant; already-`REVOKED` licenses skipped); both callsites — terminate (`rights_grants.py:75`) and auto-expiry (`services.py:217` via `run_auto_transitions`) — share the same function. (c) Added the explicit exclusion "an account linked by subscription only to other grants is not swept" to match the `linked.get(aid)` guard, and kept "is REVOKED" phrasing so already-terminal licenses remain consistent.

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_3214_out_market_game_package_distribution_territory_blackout/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-09-30T13:02:00.000Z

All edits applied. Final summary:

**Source vs output:** `PRD_FINALIZED.md` 335 lines / 52,475 chars → `PRD_COMPLETED.md` 335 lines / 53,840 chars (char-delta +1,365; edits were all in-paragraph, no lines added or removed).

**Counts:** 8 ambiguity-pins, 1 mismatch-revision (9 changes total).

**Changes:**

- §2.7 Optimistic Concurrency Control — revise — mismatch — the three OCC fields (`expected_slate_version` on selections/finalize, `expected_season_version` on advance-phase) are optional; the check runs only when the field is present — `implementation/routes/week_slates.py:79-81`, `implementation/routes/seasons.py:99-101` (both use `opt_field` + `if expected is not None`).
- §2.8 Validation Ordering, priority 3 — insert — ambiguity — body-referenced resources (`account_id`, `offer_id`, `season_id`, `game_id`, `subscription_id`) also fail with `ERR_NOT_FOUND` when unresolved — `implementation/routes/subscriptions.py:35-37`, `implementation/routes/complaint_cases.py:37-39`, `implementation/routes/entitlement_overrides.py:23-24`.
- §2.8 Validation Ordering, priority 4 — insert — ambiguity — named state errors (`ERR_SLATE_LOCKED`) take the priority-4 slot; terminal-vs-nonterminal error split is per-endpoint (e.g. lock-on-LOCKED is `ERR_ALREADY_TERMINAL`, selections/reopen-on-LOCKED is `ERR_SLATE_LOCKED`) — `implementation/routes/week_slates.py:88-91,123-126,142-144,156-159`.
- §3.1 RightsGrant cascade — insert — ambiguity — the venue-license sweep revokes licenses in `PENDING`/`CERTIFIED`/`SUSPENDED` and leaves already-`REVOKED` licenses untouched — `implementation/services.py:192-195`.
- §3.2 Season REGULAR→POST cascade — insert — ambiguity — an expiring subscription's `entitlement_state` is left exactly as it was (not merely "unchanged unless REVOKED") — `implementation/services.py:198-205` (`cascade_season_post` never touches `entitlement_state`).
- §3.4 WeekSlate — insert — ambiguity — resources may reference a (season, week) with no slate; a game in a slateless week is legal and joins no package; a lock attempt against a gameless slate is `ERR_INVALID_STATE`; lock-on-LOCKED is `ERR_ALREADY_TERMINAL` — `implementation/routes/games.py:49-51` (slate optional), `implementation/routes/week_slates.py:156-165`.
- §3.6 Territory verdict chain — insert — ambiguity — when no slate exists for the game's (season, week), the verdict is `NOT_IN_PACKAGE` — `implementation/services.py:317-319`.
- §3.7 Complaint grace window — revise — ambiguity — the `grace_days` window is enforced at approval time (resolve), not at filing time; filing is never window-checked — `implementation/routes/complaint_cases.py:28-54` (no window check on create), `:109-115` (check on approve).
- §3.7 Refund waterfall — insert — ambiguity — the weeks-received denominator is clamped to a minimum of 1, and only `CANCELLED` status fails the refund-availability check (an `EXPIRED` subscription with positive `paid_amount_cents` remains refundable) — `implementation/services.py:248-253`, `implementation/routes/complaint_cases.py:120-125`.

Everything else in the implementation (error catalogs, pagination defaults/bounds, response envelope, role tables, pricing step order with student-discount-before-proration, venue tier boundaries 100/500 and fees 500000/2000000/6000000, multiview cap of 2 with no auto-evict, market prefix resolution, effective-market dual variant, national-selection sweep semantics, entitlement fan-out, payment simulation behavior, logical-clock default `2026-09-01T00:00:00Z`, auto-transitions) was already pinned uniquely by the PRD and required no change.
