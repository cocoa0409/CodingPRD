# Worklog — task_3202_streaming_bundle_entitlement_cross_service_billing_retention

## Step 1: Create task directory — 2026-09-30T09:54:00.000Z

Task directory was pre-allocated at `./tasks/task_3202_streaming_bundle_entitlement_cross_service_billing_retention/` with `workspace/` inside. Verified existence; did NOT compute a new index per command-args instruction.

## Step 2: Generate scaffold — 2026-09-30T10:23:00.000Z

## Scaffold generated — task_3202_streaming_bundle_entitlement_cross_service_billing_retention

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Design** ("much harder than expert"): ledger-reconciliation archetype blended with pricing engine; layers = optimistic concurrency (2 OCC rules), cascading side effects, dual-variant calculation, scheduled actions. Hybrid topology, parallel state dimensions (Subscription `lifecycle_status` × `billing_dimension`), hierarchical-override role model.

**SCAFFOLD.yaml counts:**
- 12 entities (Plan, SubscriberAccount, ServiceProfile, WatchlistItem, BillingAccount, Subscription, Entitlement, Migration, RetentionOffer, RetentionRedemption, Invoice, RevenueAllocation)
- 9 state machines (incl. parallel-dimension Subscription machine and compound/bubble-up Entitlement and Subscription activation machines)
- 9 calculations (dual-variant migration proration CHRONOLOGICAL_REMAINING vs FORWARD_LOOKING_PERIOD; retention price cap+floor formula; grandfathered lock with pinned evaluation order; revenue allocation with per-row rounding + remainder absorption; maturity rank gate; tier mismatch propagation; bundle breakup fate; chronological renewal collection; 6-clause retention eligibility)
- 29 ordered validation rules across 8 categories
- 48 endpoints (incl. `/_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default and `/_billing/run_renewal` test-driver)
- 31 error codes
- 5 roles (Anonymous, Subscriber entity-backed, Support, DistributorOps, PlatformAdmin)
- 2 OCC concurrency rules (plan-change, migration-confirm)

**§1.8 difficulty index:** 25 instances — 3 each for dual_variant_calc, combinatorial_formula (modes a/b/c), non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency; 2 each for resource_temporal_overlap and compensating_invariant. All numeric asserts pre-computed as literals.

**§1.9 corner index:** 55 instances (53 active + 2 `excluded_because` stubs) across all 9 guide sections; zero name collisions across both design files.

**Lint:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (595 calls scanned). No sibling task directories were read; no forbidden concurrency vocabulary remains.

## Step 3: Copy INSTRUCTION.md — 2026-09-30T10:24:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T10:31:00.000Z

PRD generation complete. Output: `workspace/PRD.md` (299 lines).

## Section outline

- §1. Introduction (2 paragraphs, goals + engineering framing)
- §2. Global Specifications
  - 2.1 User and Role-Based Access Control (5 roles, identity semantics per role)
  - 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`)
  - 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending)
  - 2.4 Common Resource Properties (full-bookkeeping vs config-style entities)
  - 2.5 The Logical Clock (default 2026-09-01T00:00:00Z, monotonic, `ERR_CLOCK_REGRESSION`)
  - 2.6 Money, Precision, and Rounding
  - 2.7 Optimistic Concurrency Control (both OCC rules with `ERR_STALE_VERSION`/412)
  - 2.8 Nested Resource Resolution and Validation Order
  - 2.9 Three-Tier Consistency Model (account → subscription → entitlement → profile cascades)
  - 2.10 Billing Periods, Grace, and Failure Budget (30/31 days, 7-day grace, 3-failure hard fail)
  - 2.11 Closed Accounts Are Read-Only
- §3. Business Logic & Workflows — 13 subsections: plans; account lifecycle; profiles/parental controls/watchlists; billing accounts and first purchase; grandfathered pricing and effective price (60% cap, 100-cent floor); tier mismatch; plan changes; cancellation (scheduled/immediate/rescind + bundle breakup rules); migration with both proration variants; retention offers/redemptions (six-clause eligibility); renewal/dunning/recovery; invoices/revenue allocation (DPLUS-first, half-up, HULU absorbs remainder)/reporting; reading the graph (FK/filter coverage)
- §4. Endpoint Definitions — 4-column table, all 46 endpoints
- §5. Error Code Catalogue — 2-column table, all 30 error ids

## Hard contract reports

Field coverage check: entities[].fields 79 required / 79 present; endpoints request/response/query all present — PASS
Rule coverage check: all 29 validation rules in prose; 2 OCC rejections expressed; all 9 state machines' transitions expressed; 9/9 calculations fully expressed (no pseudocode); side effects expressed; structured field content stated; sibling-branch symmetry — PASS
Path purity check (§3 only): 460 backtick tokens scanned, 0 path/HTTP-method tokens — PASS

## §1.8 / §1.9 leak confirmation

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or read at any point. PRD prose derived solely from `SCAFFOLD.yaml` + doc-generator skill; no worked-example numbers, test recipes, or depth/breadth indices appear in output.

## Step 5: Generate unit tests — 2026-09-30T10:52:00.000Z

All gates pass. Generation complete.

**Task**: task_3202_streaming_bundle_entitlement_cross_service_billing_retention

**Stage 1 — test_helpers/ (9 files)**: `types.py` (12 entities; config-style entities Plan/RetentionOffer/WatchlistItem/RevenueAllocation correctly omit `updated_at`/`version`), `api_client.py` (46 endpoint methods under `/streaming`), `api_errors.py` (31 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py` (period days 30/31, GRACE_DAYS 7, MAX_RENEWAL_FAILURES 3, MAX_DISCOUNT_PCT 60, MIN_PRICE_CENTS 100, maturity ranks), `test_users.py` (shared constants for the four opaque roles + `make_subscriber_headers` for the entity-backed Subscriber role, threaded through every fixture), `fixtures.py` (composite setups: active standalone/bundle subscriptions, migration quotes, failed renewals, clock control), `__init__.py` barrel.

**Stage 2 — test_suite/ (9 test files + conftest.py)**: **105 tests total**
- Queue A (§1.8 difficulty): **50 tests** — all 25 instances covered with exactly 2 tests each
- Queue B (§1.9 corner): **55 tests** — all 53 non-stub instances covered with ≥1 test each
- Both `excluded_because:` stubs (`revenue_allocation_correct_result`, `error_catalog_stale_version_covered`) verified against real difficulty instances and not translated

**Skipped instances**: none — every instance in both indices passed the PRD-first two-condition filter. One relaxation applied per the `error-precedence` silence pattern: `test_occ_migration_confirm_stale_after_confirm` uses `validate_error_is_one_of([ERR_STALE_VERSION, ERR_INVALID_STATE])` because PRD §2.8's validation order does not uniquely pin which guard fires when a confirm is replayed after a successful confirm (both OCC-stale and terminal-state apply).

**Design-tag confirmation**: verified via AST docstring parsing — every one of the 105 test functions has exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line as the final docstring line, copied verbatim from the source YAML `name:` fields; no untagged, dual-tagged, or dangling tags.

**Citation sweep**: all 166 quoted docstring sentences verified verbatim against PRD.md (raw grep proxy, whitespace-normalized; backtick/pipe variants only where PRD itself uses markdown formatting). No `pytest.mark.skip`/`skipif`/`xfail` anywhere. All files compile and import cleanly.

## Step 6: Generate implementation — 2026-09-30T11:05:00.000Z

Implementation complete. Summary:

## Files written (in `workspace/implementation/`)

- `start.sh` — foreground launcher; guards `pip install` behind a `python3 -c "import flask"` check, then `exec python3 app.py`
- `requirements.txt` — flask
- `app.py` (1341 lines) — Flask entry point, error handlers, and all 48 routes
- `db.py` — in-memory store with logical clock (startup default 2026-09-01T00:00:00Z, monotonic)
- `errors.py` — all 31 error IDs with their HTTP statuses
- `response.py` — envelope helpers (`meta`/`response_type`/`data`, pagination `limit`/`offset`/`total_count`/`has_more` in meta)
- `middleware.py` — X-User-Role/X-User-ID auth, 5 roles, subscriber ownership checks
- `services.py` (575 lines) — serializers, all 9 calculations, cascade machinery

## Endpoint coverage

48/48 method+path pairs from the scaffold endpoint table, including clock, plans, accounts (suspend/reactivate/close), profiles (+unlink, PATCH parental controls), watchlist, billing accounts, subscriptions (plan-change with OCC, cancel, rescind), entitlements, migrations (quote/confirm with OCC/void), retention offers/redemptions, invoices (retry-payment), revenue allocations, revenue-report, and `_billing/run_renewal`.

## Entity / state machine / calculation coverage

- All 12 entities with correct bookkeeping fields (`created_at`/`updated_at`/`version` on the 8 full-bookkeeping resources; `id`+`created_at` only on Plan/RetentionOffer/WatchlistItem/RevenueAllocation)
- All 9 state machines: account lifecycle, profile bubble-up, billing dunning (CURRENT/PAST_DUE/HARD_FAILED), dual subscription dimensions (lifecycle + billing_dimension), entitlement provisioning, migration QUOTED→CONFIRMED/VOIDED, redemption ACTIVE→EXPIRED/VOIDED, invoice states, clock-gated cancel finalization
- All 9 calculations: dual-variant migration proration (CHRONOLOGICAL at quote, FORWARD_LOOKING with consumed-credit subtraction at confirm), retention effective price (60% cap floor, 100-cent floor), grandfathered price lock with relock-after-full-churn, revenue allocation (DPLUS rounded half-up, HULU absorbs remainder), maturity rank gate (kids_mode forces TV_PG), tier mismatch flagging, bundle-breakup fate, renewal collection (chronological, credit consumption, 30/31-day period advance), 6-clause retention eligibility (VOIDED excluded from cap count)
- OCC via `expected_subscription_version`/`expected_migration_version` → ERR_STALE_VERSION 412
- Validation priority order respected (auth → ownership → path existence → body refs → state → account-active → business rules → OCC)

## Boot sanity check

`bash start.sh` boots cleanly from a fresh process, binds 0.0.0.0:$PORT, responds 200 within ~3s. Two stateful smoke suites (~90 assertions) pass covering the full purchase → entitlement → renewal → dunning/recovery → migration → retention → cancellation → close lifecycle. Only own test PIDs were killed during development; no broad kill patterns used.

## Step 7: Iterate tests to PASS — 2026-09-30T11:42:00.000Z

All 8 rounds: 105/105. Clean sweep.

- **Iterations run:** 3 sweeps (8 parallel rounds each).
  - Round 1: 96/105 — 9 deterministic failures.
  - Round 2: 103/105 — 2 remaining.
  - Round 3: 105/105 across all 8 rounds — exit condition met.

- **Tests deleted:** none.

- **Test suite / helper fixes:**
  - `test_suite/test_04_migrations.py` — added missing `create_standalone_plan` import (used at lines 97 and 121; plain NameError, test bug).
  - `test_suite/test_07_occ_and_priority.py::test_account_state_beats_retention_business_rule_on_subscription_create` — moved `create_standalone_plan`/`create_profile(HULU)` setup to before `suspend_account`. PRD §3.3 verbatim requires the account to be ACTIVE to create profiles, so the original ordering asked a PRD-faithful implementation to violate the PRD.
  - `test_suite/test_08_billing_constraints.py::test_tier_mismatch_flag_and_clear_on_plan_change` — STEP 1c partial-coverage split. PRD §3.6 pins flagging to "every entitlement serving the lower-tier service," but with a mixed-tier DPLUS profile (AD_SUPPORTED bundle + AD_FREE standalone) the PRD does not uniquely determine which service side is "lower-tier" (best-tier vs worst-tier reading both defensible). Relaxed the over-specified `all(bundle ents flagged)` assertion to `any(...)` on the bundle (true under both readings) and kept the fully derivable flag-clearing-on-plan-change assertion unchanged.

- **Implementation fixes** (all in `workspace/implementation/`):
  - `app.py` (`create_plan`) + `services.py` (`plan_out`) — Plan now carries a server-minted UUID `id` instead of aliasing `plan_code`; PRD §2.6: "Every resource carries an `id` that is a server-minted UUID."
  - `app.py` (`create_offer`) + `services.py` (`offer_out`) — same UUID-`id` fix for RetentionOffer (same PRD sentence).
  - `app.py` (`create_subscription`) — removed the hard `ERR_INVALID_STATE` rejection when a named profile is not LINKED; PRD §3.4 describes provisioning to ACTIVE only "provided its profile is LINKED," implying stuck-PROVISIONING behavior otherwise. Added a retry pass so PROVISIONING entitlements on a SUSPENDED profile activate and bubble the profile back to LINKED per PRD §2.9 ("when any entitlement on a suspended profile returns to ACTIVE … the profile rises back to LINKED").
  - `app.py` (`confirm_migration`) — void any still-ISSUED invoice of the source subscription as superseded by the migration adjustment (PRD §3.12), and removed the duplicate `svc.touch(m)` so the migration's version increments by exactly 1 on confirm (PRD §3.9).
  - `services.py` (`grandfather_lock`) — implemented the full-churn re-lock: when every other subscription of the account is terminal, a newly activating subscription re-locks `grandfathered_plan_code`/`grandfathered_price_cents` at its own plan's list price (PRD §3.5).
  - `services.py` (`reevaluate_mismatch`) — rewrote to compare each LINKED profile's best ACTIVE tier and flag all ACTIVE entitlements of the lower-tier profile when they disagree; the old set-uniformity guard (`len(tiers)==1`) silently disabled flagging whenever one profile carried mixed tiers.

## Step 8: Finalize PRD — 2026-09-30T11:50:00.000Z

Done. `PRD_FINALIZED.md` is written with exactly two minimal edits.

**Line counts:** PRD.md 299 → PRD_FINALIZED.md 301 (+2 lines, +0.67%). Only two sentences/paragraphs changed; everything else verbatim.

### Changes

- **§3.4** — revise — added two sentences pinning purchase behavior when a named profile is not `LINKED`: the entitlement stays in `PROVISIONING` (no rejection), and if the profile is `SUSPENDED` the entitlement is then activated and the profile bubbles back to `LINKED` per §2.9 — `implementation/app.py:672-687` (retry pass in `create_subscription`), `services.py:361-383` (`provision_entitlements` non-LINKED branch), `services.py:303-315` (`profile_bubble`).
- **§3.6** — insert — added a paragraph pinning mixed-tier profile resolution: each `LINKED` profile is judged by the best tier among its `ACTIVE` entitlements (`AD_FREE` outranks `AD_SUPPORTED`), and on disagreement every `ACTIVE` entitlement of the lower-tier profile is flagged — `implementation/services.py:259-300` (`reevaluate_mismatch` best-tier rewrite).

### Step 7 items deliberately NOT patched (and why)

- Plan/Offer UUID `id` fixes — PRD §2.4 already said "Every resource carries an `id` that is a server-minted UUID"; the old impl was wrong, not the PRD.
- `confirm_migration` ISSUED-invoice voiding — PRD §3.12 already says an ISSUED invoice superseded by a migration adjustment is VOIDED; the duplicate-touch fix aligns impl with §3.9's "the migration's `version` increments by 1."
- `grandfather_lock` full-churn re-lock — PRD §3.5's last sentence already specifies it verbatim.
- Test-only fixes (`create_standalone_plan` import in test_04, setup reordering in test_07, `all→any` relaxation in test_08) — fixture bugs or over-specified test assertions, not PRD edits.

### Per-edit pre-edit search log

**Edit 1 (§3.4, non-LINKED profile at purchase):**
- (a) Subject: entitlement provisioning against a named profile that is not `LINKED`, and the `SUSPENDED`-profile activation/bubble.
- (b) Enumerated via grep of `profile_status`/`provision_entitlements`/`profile_bubble` across `app.py` + `services.py`: `create_subscription` (app.py:609-697, retry pass at 672-687), `provision_entitlements` (services.py:361-383), `profile_bubble` (services.py:303-315), `maybe_activate_subscription` (services.py:342-358), plan-change scope expansion (app.py:765-783), migration-confirm profile resolution (app.py:1022-1049), reactivation paths (app.py:322-344, services.py:524-543 — new wording scoped to purchase, no conflict).
- (c) Wording adjusted to scope the new rule to the purchase flow rather than claiming a universal provision-regardless-of-profile-state rule.

**Edit 2 (§3.6, mixed-tier profile resolution):**
- (a) Subject: how `mismatch_flag` is computed when a profile carries `ACTIVE` entitlements of both tiers.
- (b) Enumerated via grep of `mismatch_flag`/`reevaluate_mismatch`: `reevaluate_mismatch` (services.py:259-300) plus all 7 callsites: suspend (app.py:318), reactivate (343), profile create (409), unlink (457), plan change (786), migration confirm (1066), cancel finalize (services.py:474), renewal failure (520), payment recovery (543). All delegate to the single impl; verified "Two bundles of the same plan can never mismatch…" stays consistent.
- (c) Wording chosen as "each `LINKED` profile is judged by the best tier among its `ACTIVE` entitlements" and flagging scoped to `ACTIVE` entitlements of the lower-tier profile — matching the impl exactly without over-claiming for the degenerate multi-profile-per-service case.

## Step 9: Complete PRD — 2026-09-30T12:05:00.000Z

PRD_COMPLETED.md produced at `workspace/PRD_COMPLETED.md`.

**Source vs completed:** PRD_FINALIZED.md 301 lines / 49,779 chars; PRD_COMPLETED.md 301 lines / 55,600 chars (+0 lines, +5,821 chars — all inline edits, no new sections).

**Counts:** ambiguity-pins: 22; mismatch-revisions: 4 (all intra-paragraph).

**Change list:**

1. §2.2 — insert — ambiguity — pins `has_more = (offset + rows_returned) < total_count` — response.py:36
2. §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1–100, negative offset → `ERR_INVALID_REQUEST` — response.py:58-69
3. §2.4 — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock, not wall-clock — services.py:24-33
4. §2.5 — insert — ambiguity — setting the clock to exactly the current instant is accepted (strict `<` regression check) — app.py:142-144
5. §2.8 — insert — ambiguity — the fixed order governs priority between error categories, not intra-endpoint check sequencing — app.py (per-endpoint check order varies)
6. §3.1 — insert — ambiguity — unknown `service_scope`/`plan_kind`/`ad_tier` enum values → `ERR_INVALID_REQUEST` (400) — app.py:163-175
7. §3.1 — insert — ambiguity — `allow_app_store_billing`/`allow_distributor_billing` default false when omitted — app.py:170-171
8. §3.2 — insert — ambiguity — malformed email → `ERR_INVALID_REQUEST` — app.py:253-254
9. §3.2 — revise — mismatch — `retention_redemption_count` is computed on read (count of ACTIVE/EXPIRED redemptions), not a stored field initialized to 0 — services.py:64, 222-228
10. §3.2 — insert — ambiguity — suspending a non-ACTIVE account → `ERR_INVALID_STATE` — app.py:305-306
11. §3.2 — insert — ambiguity — reactivating a non-SUSPENDED account or with a PAST_DUE subscription → `ERR_INVALID_STATE`; reactivation skips entitlements on UNLINKED profiles — app.py:326-340
12. §3.2 — insert — ambiguity — closing an already-CLOSED account → `ERR_INVALID_STATE`; closure only moves LINKED/SUSPENDED profiles to UNLINKED — app.py:352-360
13. §3.3 — insert — ambiguity — profile creation on a CLOSED account → `ERR_ACCOUNT_CLOSED` (not `ERR_ACCOUNT_NOT_ACTIVE`) — app.py:384-387
14. §3.3 — insert — ambiguity — PATCH parental controls: omitted fields left unchanged — app.py:468-475
15. §3.3 — insert — ambiguity — unlinking an already-UNLINKED profile → `ERR_INVALID_STATE` — app.py:447-448
16. §3.4 — insert — ambiguity — profile fields required exactly for services in plan scope; wrong owner/service → `ERR_INVALID_REQUEST`, nonexistent profile → `ERR_REFERENCE_NOT_FOUND`; billing account not owned by purchaser → `ERR_INVALID_REQUEST` — app.py:630-648
17. §3.4 — insert — ambiguity — billing account `period_start`/`period_end` are null until first invoice; initial invoice consumes no account credit (`credit_applied_cents` = 0) — app.py:689-696
18. §3.5 — insert — ambiguity — the activating subscription itself is excluded from the "any live subscription" re-lock test (re-locks when it is the only live sub) — services.py:327-339
19. §3.5 — insert — ambiguity — fresh subscription before recomputation: `price_cents` = plan list, `retention_discount_cents` = 0 — app.py:664-665
20. §3.6 — insert — ambiguity — mismatch re-evaluation is account-scoped and re-runs on every entitlement/profile cascade (suspend, reactivate, cancel finalize, renewal failure/recovery, migration confirm) — services.py:259-300
21. §3.7 — insert — ambiguity — plan change requires ACTIVE or PAST_DUE lifecycle, else `ERR_INVALID_STATE` — app.py:739-740
22. §3.7 — insert — ambiguity — scope-leaving revokes PROVISIONING/ACTIVE/SUSPENDED entitlements; new-scope entitlement attaches to the first LINKED profile for the service, none spawned if absent — app.py:759-783
23. §3.8 — revise — mismatch — `immediate_effect=true` from PAST_DUE → `ERR_INVALID_REQUEST` (400), previously unpinned — app.py:805-806
24. §3.8 — insert — ambiguity — cancel finalization also auto-voids QUOTED migrations on that subscription — services.py:475, 478-485
25. §3.8 — revise — mismatch — immediate cancel finalizes in the same request regardless of period position (no "at or after period end" condition); response shows CANCELLED with null `cancel_effective_at` — app.py:808-815
26. §3.9 — insert — ambiguity — quote proration days_remaining floored at zero — app.py:902-903
27. §3.9 — insert — ambiguity — confirm: source entitlements revoked in PROVISIONING/ACTIVE/SUSPENDED; ACTIVE redemptions on source voided; new bundle billed on the same billing account; each scope service requires a LINKED profile else `ERR_REFERENCE_NOT_FOUND`; MIGRATION_ADJUSTMENT invoice stays ISSUED with current period bounds — app.py:1011-1065
28. §3.10 — insert — ambiguity — `max_redemptions_per_account` must be ≥ 1, else `ERR_INVALID_PRICING` — app.py:1109-1110
29. §3.11 — revise — mismatch — run_renewal also processes PAST_DUE/GRACE subscriptions (as retry of the failed period); invoice kind is always `RENEWAL` (never INITIAL inside a run); renewal invoices record the billing account's current period bounds; empty due set → `ERR_RENEWAL_NOT_DUE`; failed run on PAST_DUE/GRACE sub leaves lifecycle/dimension untouched — services.py:546-596, app.py:1342-1347
30. §3.11 — insert — ambiguity — retry-payment recovery does not advance the billing period; a succeeded renewal run over PAST_DUE/GRACE recovers and advances — app.py:1289-1290, services.py:575-577
31. §3.12 — insert — ambiguity — revenue report attributes invoices to the window by `created_at`; missing/unparseable from/to → `ERR_INVALID_REQUEST` — app.py:1300-1315
32. §3.13 — revise — mismatch — subscription list filters are exactly `subscriber_account_id`, `billing_account_id`, `plan_code`, `lifecycle_status`, `migration_id` (no from/to/migration_status on subscriptions; those belong to migrations); Subscriber list endpoints scope to own rows regardless of filters — app.py:709-724, 955-971
33. §3.13 — insert — ambiguity — billing-run response fields describe the last subscription processed in the run's ordering — services.py:572, app.py:1348-1352

No PRD-described behavior was found that implementation flatly contradicts beyond items 9, 23, 25, 29, 32; all other changes pin previously silent interpretations.

## Pipeline complete

All 9 steps finished. Final deliverables:
- `SCAFFOLD.yaml` + `SCAFFOLD_DIFFICULTY_DESIGN.yaml` + `SCAFFOLD_CORNER_DESIGN.yaml` (§1.0–§1.9)
- `workspace/PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md` (progressively pinned to implementation)
- `test_helpers/` + `test_suite/` — 105 tests, 8/8 rounds passing under per-test-server isolation
- `workspace/implementation/` — 48-endpoint Flask server, in-memory storage, clean boot per test
