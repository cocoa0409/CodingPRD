# Worklog — task_3288_geographic_platform_licensing_enterprise_deployment_data_publishing

## Step 1: Create task directory — 2026-09-30T17:47:00.000Z

Directory was pre-allocated per invocation instructions; verified `./tasks/task_3288_geographic_platform_licensing_enterprise_deployment_data_publishing/workspace/` exists. No new index computed.

## Step 2: Generate scaffold — 2026-09-30T18:45:00.000Z

All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_3288_geographic_platform_licensing_enterprise_deployment_data_publishing/` and pass `scaffold_lint.py` with a clean verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."**

**Counts (final, verified):**
- Entities: **12** (Organization, CreditPool, LicenseProduct with embedded extension_modules, LicenseGrant, ExtensionGrant, NamedUser, DeploymentServer, VersionCompatibilityRule, ContentItem, ApiKey, CreditBatch, EligibilityVerification)
- State machines: **10** (Organization, LicenseGrant, NamedUser, DeploymentServer, ContentItem, ContentItemSharingLevel as a parallel dimension, CreditBatch, EligibilityVerification with a renewal cycle, ApiKey, LicenseProduct)
- Calculations: **7** (credit_pool_posture, credit_consumption with provisional/chronological variants + 10%-per-period late fee, concurrent_seat_overage_fee with marginal/sustained variants, version_compat_check, storage_credit_billing with ceiling, credit_burn_projection with forward/chronological variants, eligibility_renewal_window)
- Endpoints: **42** (at the ~40 cap; flat topology under `/geo-orgs` prefix, merged lifecycle-transition endpoints, filtered-list GETs satisfying FK reverse-reachability)
- Errors: **74**; Validations: **30** ordered priorities; Roles: **7** (2 entity-backed); OCC concurrency rules: **3**
- §1.8 instances: **18** (9 rules × 2), including deep chains: settle-late-fee → OVERDRAWN → org suspension → grant/user/key/item cascades; EV renewal lapse → program-grant suspension; extension + tier-straddle credit math; OCC-vs-eligibility and state-vs-fiscal priority conflicts
- §1.9 instances: **42** across 7 sections (entities, state_machines, calculations, validations, endpoints, errors, roles, cross-cutting layers), covering boundaries (tier edges, threshold equality, storage ceiling, cap `>` vs `>=`), terminal lockdowns, depth-1 flag cascade, idempotency replay/conflict, per-tenant uniqueness, and OCC roundtrips

**Key design decisions driven during linting:** org lifecycle transitions deliberately do NOT bump `Organization.version` (only grant transitions do), keeping OCC setup chains replay-safe; the chronological credit variant carries a late fee so OVERDRAWN is genuinely reachable; the logical clock endpoint defaults to 2026-09-01T00:00:00Z per the skill's mandate.

Orchestrator verification: all three YAML files parse; SCAFFOLD.yaml has 42 endpoints / 12 entities / 74 errors; difficulty instances 18; corner instances 42. (Note: subagent's first pass exhausted its output before writing; a resume message completed the rewrite and both design files.)

## Step 3: Copy shared files — 2026-09-30T18:50:30.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-30T19:05:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_3288_geographic_platform_licensing_enterprise_deployment_data_publishing/workspace/PRD.md`.

**Summary**

**PRD:** 426 lines, at `/home/ubuntu/github/CodingPRD/tasks/task_3288_geographic_platform_licensing_enterprise_deployment_data_publishing/workspace/PRD.md`

**Section list:**
- 1. Introduction (3 paragraphs)
- 2. Global Specifications & System-Wide Principles — 2.1 Roles & RBAC (with entity-backed vs opaque identity prose for all 7 roles), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Common Resource Properties, 2.5 Logical Clock & Period Advancement (startup default `2026-09-01T00:00:00Z`, four clock-advance effects), 2.6 Nested Retrieval/Existence, 2.7 Credit Posture & Rounding (OVERDRAWN/EXHAUSTED/LOW_CREDIT/OK with strict boundaries), 2.8 Concurrent-Use Overage Metering (marginal 250/400/700-cent tiers + sustained average-rate variant), 2.9 OCC (all three rules: `expected_organization_version`, `expected_content_item_version`, `expected_credit_pool_version` → `ERR_STALE_VERSION` 412), 2.10 Validation Pipeline (priorities 1–29 in prose), 2.11 Request Body Semantics
- 3. Business Logic & Workflows — 3.1 Organizations, 3.2 Credit Pool & projection (forward/chronological variants), 3.3 Product Catalog & extensions, 3.4 License Grants, 3.5 Extension Grants, 3.6 Named Users, 3.7 Credit Batches (provisional per-tier-round vs chronological sum-then-round + 10%/period late fee, full tier tables with worked GEOCODE 100/101 example), 3.8 Eligibility Verifications (+12-period approval window), 3.9 Content Items (storage billing in 100-MiB ceiling units, sharing cycle, moderation depth-1 cascade), 3.10 Deployment Servers & version_compat_check (pinned 3-step order, warning in `meta`), 3.11 API Keys
- 4. Endpoint Definitions — 42 rows, 4 columns
- 5. Error Code Catalogue — 74 rows, 2 columns

**Hard-contract reports:**
- Field coverage: 81 required (entities + endpoint inputs), 81 present, 0 missing — PASS
- Rule coverage: all 7 calculations expressed in prose with pinned rounding orders/constants; all state-machine transitions with preconditions/side-effects/error IDs; all 3 OCC rules with endpoint+field+error+status; validation priority ordering stated; all 74 error IDs appear in §2/§3 narrative — PASS
- Path purity: 631 backticked tokens in §3, 0 path/method violations — PASS

**Ambiguities noted in scaffold (resolved conservatively in prose):**
1. `ApiKey.organization_id` mismatch with owner org has no scaffold-nominated error; stated only that the field must equal the owner's `organization_id` without inventing an error code.
2. ContentItem sharing state machine is formally cyclic in scaffold (`PUBLIC`→`ORGANIZATION`→`PRIVATE`, no `PUBLIC`→`PRIVATE`); prose renders it as a strict single-step ladder, matching the transition table.
3. Priority-19 wording "posture != EXHAUSTED and != OVERDRAWN" for settle vs "posture != OVERDRAWN" for reinstate kept verbatim (`ERR_CREDIT_POOL_EXHAUSTED` covers both postures at settle despite its name).

## Step 5: Generate unit tests — 2026-09-30T19:35:00.000Z

All modules import cleanly against the real framework. Done.

**Summary**

**Generated for task_3288 (Geo Platform Licensing):**

### test_helpers/ (9 files)
- `types.py` — 12 entity TypedDicts + 18 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with 27 methods covering all 30 PRD endpoints
- `api_errors.py` — 74 `ApiErrorId` values with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserts + `assert_pool_invariants` (posture/balance mirror check)
- `factories.py` — 11 payload factories (input fields only)
- `constants.py` — posture threshold, overage tiers, EV window, late-fee ratio, pricing tier tables
- `test_users.py` — 7 role header constants + per-instance builders for the two entity-backed roles
- `fixtures.py` — composite chains: `setup_base_chain`, `setup_with_user`/`setup_with_key`, `setup_education_org(_with_approved_ev)`, `setup_concurrent_use_org`, `setup_server_org`, server/EV/share/batch lifecycle shortcuts, version-threading `activate_grant`
- `__init__.py` — barrel export of framework + PRD-specific names

### test_suite/ (12 files, 107 tests)
| File | Tests |
|---|---|
| test_01_organization_and_pool.py | 8 |
| test_02_field_semantics.py | 6 |
| test_03_listing_and_visibility.py | 5 |
| test_04_grant_lifecycle.py | 11 |
| test_05_credit_batches.py | 14 |
| test_06_cascades.py | 4 |
| test_07_overage_metering.py | 2 |
| test_08_content_items.py | 18 |
| test_09_eligibility.py | 15 |
| test_10_deployment_servers.py | 10 |
| test_11_named_users.py | 10 |
| test_12_api_keys_and_uniqueness.py | 4 |

### Stage 2 self-verification
- **Tag audit (AST-level):** all 107 tests have exactly one terminal `Design: Difficulty/...` or `Design: Corner/...` line; every tag resolves to a real instance; 18/18 difficulty instances have ≥2 tests; 42/42 corner instances have ≥1 test; no stubs.
- **Skipped instances:** none — all 60 instances passed the PRD-first two-condition filter.
- **Verbatim-citation sweep:** every quoted PRD passage in every docstring survives a whitespace-normalized literal grep of PRD.md (0 misses after fixing 13 elided quotes to full verbatim sentences).
- **Syntax/import:** `compileall` clean; all 12 test modules + conftest import successfully against the installed `prd_bench_local_runner` framework.

### Notable adjudications
- `credit_projection_forward_vs_chronological`: the YAML's pre-computed forward value (4420) is not derivable from PRD §3.2 (consumed 400 + reserved 0 + 10×(1 seat×2) = 420). Asserted the PRD-derived **420**; chronological 2000 matches both.
- `grant_activate_from_active_rejected`: avoided the YAML's stale-version capture (OCC fires at priority 5 before the state check) by fetching the org version fresh so the asserted `ERR_GRANT_NOT_PENDING` is the unique outcome.
- `setup_education_org` diverges from the YAML chain by adding an activated STANDARD grant to host the user — the YAML's accept-onto-PENDING-program-grant chain contradicts PRD §3.6 (acceptance requires home grant ACTIVE), so the fixture follows the PRD.

## Step 6: Generate implementation — 2026-09-30T19:50:00.000Z

All 42 endpoints registered. Summary:

**Location:** `workspace/implementation/`

**Files written (one per Write call):**
- `start.sh` — guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py`, executable
- `requirements.txt` — flask
- `app.py` — Flask app, blueprint registration, ApiError/404/405 handlers, `0.0.0.0:$PORT` (default 10000)
- `store.py` — in-memory dicts for all 12 entities + idempotency index + logical clock (default 2026-09-01T00:00:00Z); no seeding
- `errors.py` — full 74-entry error catalog with HTTP statuses
- `envelope.py` — response envelope (`meta`/`response_type`/`data`, `req_*` id, 3-fractional-digit ISO timestamps, `limit`/`offset`/`total_count`/`has_more` pagination meta) + paginate helper (default 10, min 1, max 100)
- `auth.py` — `X-User-ID`/`X-User-Role` header checks (ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER 400), role gate (ERR_INSUFFICIENT_PERMISSIONS 403)
- `calc.py` — tier tables (GEOCODE/ANALYSIS/STORAGE/TILE_QUERY/ROUTING), provisional (round-half-up per tier, then sum) vs chronological (sum raw, ×(1+0.1·periods), round once) variants via `Decimal`, posture thresholds (OVERDRAWN/EXHAUSTED/LOW_CREDIT strict-less-than/OK), storage unit ceiling (104857600 bytes), marginal vs sustained (average-rate) overage fees, forward/chronological burn projection
- `helpers.py` — body-shape validation (priority 2.5, unknown fields ignored) and cascade logic (org suspend depth-3 chain, grant suspend/expire/revoke, user disable)
- `routes/clock.py`, `orgs.py`, `pools.py`, `products.py`, `grants.py` (+extension grants), `users.py`, `servers.py` (+compat rules), `items.py` (transition/share/moderate + visibility), `keys.py`, `batches.py` (idempotency + OCC on pool version), `evs.py`

**Endpoints implemented: 42/42** (verified by counting route decorators).

**Key fidelity points honored:** OCC fields required and checked before business rules on the three endpoints (`expected_organization_version`, `expected_content_item_version`, `expected_credit_pool_version` → ERR_STALE_VERSION 412); grant activation increments Organization.version; validation priority order (e.g. credit sufficiency before idempotency before key scoping before extension applicability on batch create; single-step legality before PUBLIC level gate before basemap gate on share); storage batches synthesized on publish with `storage:<item-id>` idempotency key and null api_key_id; settle can push pool OVERDRAWN → org suspension cascade; per-test-server reboot safety (in-memory only, empty at boot).

**Smoke boot:** launched `PORT=19877 bash start.sh` in background (PID 1365161), verified: create org → 201 with correct envelope; get org → 200 round-trip; missing headers → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error envelope; clock advance 10 days → `{"advanced_periods": 10, "current_utc": "2026-09-11T00:00:00Z"}`. Killed exactly PID 1365161 afterward. Test suite was not run, per instructions.

Orchestrator verification: implementation/ contains 12 files incl. start.sh + 12 route modules; grep counts exactly 42 route decorators.

## Step 7: Run tests and iterate — 2026-09-30T19:53:00.000Z

**Iterations run:** 2 (initial 8-round sweep: 90/107 in all 8 rounds, 17 deterministic failures; single-round validation: 106/107; final 8-round sweep: 107/107 in all 8 rounds).

**Tests deleted:** none — every failure traced to a test-artifact bug, an implementation bug, or a relaxable error-precedence ambiguity; no PRD-silent assertions were found.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` / `setup_with_key` — when called with a pre-built `base` lacking a user, it now runs `setup_with_user(base)` first; previously `setup_with_key(setup_base_chain(...))` raised `KeyError: 'user'` (5 test_01 failures).

**Fixes applied to `test_suite/`:**
- `test_06_cascades.py` — added missing `setup_with_user` and `validate_error` imports (NameError in `test_org_terminate_blocked_by_published_content`); `_setup_overdraw_scenario` capacity 1300 → 1320: at 1300 the two 650-credit reservations leave available exactly 0, i.e. `EXHAUSTED`, and PRD §3.7's settle gate ("Settlement of a pending batch refuses to proceed while the posture is `EXHAUSTED` or `OVERDRAWN`") then correctly refuses the very settle the test needs to push the pool `OVERDRAWN` (capacity must be in [1301, 1364] for creation to pass, pre-settle posture to be non-EXHAUSTED, and post-settle available to go negative).
- `test_08_content_items.py` — `test_basemap_public_share_requires_advanced_grant` and `test_basemap_public_share_unblocked_by_advanced_grant`: capture the post-publish item (`item = publish_item(...)`) so the OCC `expected_content_item_version` is current (PRD §2.9 runs OCC before business rules, so the stale version correctly produced `ERR_STALE_VERSION`); `test_publish_synthesizes_pending_storage_batch`, `test_offline_publish_succeeds_with_supports_offline_grant`, `test_derivative_publish_succeeds_from_published_source`: removed `get_success_data(...)` double-wrap around `publish_item` (already returns unwrapped data dict → AttributeError); `test_retracted_item_rejects_share_and_flag`: capture the post-retract item so the share carries the current version and reaches the PRD-required `ERR_ITEM_NOT_PUBLISHED` business rule.
- `test_09_eligibility.py` / `test_ev_resubmit_from_submitted_rejected` — relaxed the exact-error assertion to `validate_error_is_one_of([ERR_EV_NOT_RENEWAL_REQUIRED, ERR_INSUFFICIENT_PERMISSIONS])` (ERROR PRECEDENCE SILENCE: PRD §3.8 pins the state rule for resubmit and §254 pins the ComplianceOfficer role for begin-review, but never orders role-vs-state for a NamedUser targeting `UNDER_REVIEW` on a `SUBMITTED` record; both outcomes are PRD-defensible, and the status-stays-`SUBMITTED` assertion holds under either).

**Fixes applied to `implementation/`:**
- `routes/users.py` / `create_user` — invite now accepts a home grant whose product is `NAMED_USER` **or** `CONCURRENT_USE` kind (still `ERR_GRANT_KIND_MISMATCH` for `DEPLOYMENT_SERVER` or cross-org). PRD §2.8's metered-overage contract ("a checkout that pushes a grant's in-use seats beyond its allocation succeeds") and §3.6's re-enable branch ("When the home grant is `CONCURRENT_USE`-kind, overage is metered per §2.8") explicitly contemplate users homed on CONCURRENT_USE grants; the §3.6 invite sentence naming NAMED_USER is retained for the kinds PRD does not contemplate.
- `routes/users.py` / `user_transition` (INVITED→ACTIVE self-acceptance) — seat capacity is now kind-dependent per §2.8: `NAMED_USER` keeps the hard-cap `ERR_NO_SEATS_AVAILABLE`; `CONCURRENT_USE` consumes the seat and accrues the marginal overage fee (`calc.marginal_overage_fee_cents`) onto `seat_overage_fee_accrued_cents` when the increment passes `seats_allocated`, mirroring the existing re-enable branch.

Orchestrator verification: all 8 `results.{i}.json` files independently show 107/107 passed, 0 failed; no impl/test source file is newer than the results files, so the clean sweep is not invalidated by post-sweep edits.

## Step 8: Finalize PRD — 2026-09-30T19:58:00.000Z

Done. `PRD_FINALIZED.md` produced with exactly 3 inline edits, all traced to the Step 7 diff's two genuine PRD-relevant items.

**Line counts / delta:** PRD.md 426 lines / 62,525 chars; PRD_FINALIZED.md 426 lines / 63,611 chars (+1.74% chars, 0 line-count change — all edits inline, no new sections).

**Changes (one per edit):**
- §3.6 (invite paragraph) — revise — home grant now accepts `NAMED_USER`-kind **or** `CONCURRENT_USE`-kind in the same org; `DEPLOYMENT_SERVER`-kind and cross-org remain `ERR_GRANT_KIND_MISMATCH` — `implementation/routes/users.py:38-40`.
- §3.6 (acceptance paragraph) — revise — self-acceptance seat capacity is kind-dependent: `NAMED_USER` keeps the hard-cap `ERR_NO_SEATS_AVAILABLE`; `CONCURRENT_USE` consumes the seat and accrues the marginal overage fee per §2.8 onto `seat_overage_fee_accrued_cents` — `implementation/routes/users.py:107-122`.
- §3.8 (begin-review sentence) — insert — pins role-gate-before-state-legality ordering on the EV transition endpoint: role mismatch for the operation the current state permits yields `ERR_INSUFFICIENT_PERMISSIONS` (not the state error), with both off-order examples spelled out — `implementation/routes/evs.py:79-99`.

**No edit made for the remaining Step 7 items** — the fixtures.py `setup_with_key` fix, test_06 imports/capacity-1320 fix, and test_08 OCC-capture/double-wrap fixes are pure test-artifact bugs, not PRD silences or impl mismatches.

**Per-edit pre-edit search log:**

1. *Invite kind acceptance.*
   (a) Subject: which grant kinds may home a named user, and `ERR_GRANT_KIND_MISMATCH` semantics.
   (b) Enumerated paths: `implementation/routes/users.py` `create_user` (users.py:30-40, full file read); grep for `ERR_GRANT_KIND_MISMATCH` across all routes — the only other producer is `routes/servers.py:38,102` (server-registration DEPLOYMENT_SERVER gate, an unrelated subject, wording unaffected); confirmed §2.8 and §3.6 re-enable prose already contemplate CONCURRENT_USE-homed users, so widening invite is consistent with the rest of §3.6.
   (c) Wording scoped to "either user-homing kind" with DEPLOYMENT_SERVER/cross-org still mismatch — matches impl exactly, does not touch server wording.

2. *Kind-dependent seat capacity at self-acceptance.*
   (a) Subject: seat consumption and `ERR_NO_SEATS_AVAILABLE` vs. metered overage on user activation.
   (b) Enumerated paths: `users.py` `user_transition` INVITED→ACTIVE branch (107-122) and DISABLED→ACTIVE re-enable branch (132-146) — the edit reuses §3.6's existing re-enable phrasing verbatim so both branches are described identically; `helpers.py:54-81` (suspend cascades zero seats / disable decrements — unaffected); `routes/clock.py:86` (sustained-overage re-charge reads `seats_in_use` — consistent since acceptance still increments); `calc.py:121` (`marginal_overage_fee_cents` tier pricing — matches §2.8 tiers 250/400/700); `routes/servers.py:103-109` (core capacity, distinct hard-cap semantics, untouched); `errors.py:47` (ERR_NO_SEATS_AVAILABLE 409, unchanged).
   (c) Framed as "Capacity is then kind-dependent, exactly as on re-enable below" — defers to the already-accurate re-enable sentence rather than inventing new phrasing, avoiding divergence between the two parallel branches.

3. *EV transition role-vs-state precedence.*
   (a) Subject: check ordering on `/geo-orgs/eligibility-verifications/<id>/transition` for target `UNDER_REVIEW`.
   (b) Enumerated paths: full read of `routes/evs.py` — dispatch is state-first: SUBMITTED branch checks ComplianceOfficer role before anything else (80-83), RENEWAL_REQUIRED branch checks NamedUser role before evidence freshness (88-92), so for both source states role mismatch precedes state/evidence errors; also confirmed the terminal-else branch (97-99), the APPROVED/REJECTED branch ordering (101-109: role → state → rationale → segregation), and `create_ev`/`list`/`get` (role-gated at endpoint level, unaffected); cross-checked §2.10 pipeline (endpoint-level role authorization at priority 2 vs. state legality at priority 6 — the intra-endpoint role gate is a business-rule detail, so a §3.8-local pin is the right scope and does not conflict with §2.10).
   (c) Wording scoped narrowly to "on the transition endpoint" and only to the role-vs-state pairing, with the two concrete examples; no universal reordering claim that would mis-describe the APPROVED/REJECTED branch (where role also precedes state — consistent — but rationale/segregation follow state, which the edit does not claim to reorder).

## Step 9: PRD completeness scan — 2026-09-30T20:08:00.000Z

Done. PRD_COMPLETED.md produced at `workspace/PRD_COMPLETED.md`.

**Source:** PRD_FINALIZED.md (426 lines, 63,906 chars) → PRD_COMPLETED.md (433 lines, 69,450 chars; +7 lines, +5,544 chars).

**Counts:** 17 ambiguity-pins, 4 mismatch-revisions (21 total edits).

### Changes

- §2.2 Success envelope — insert — ambiguity — pinned `req_` + 20 uppercase-alphanumerics, wall-clock (not logical) timestamp with 3 fractional digits, response_type derived from data shape, `has_more` = offset+limit < total_count, non-list meta fields — implementation/envelope.py:9-38
- §2.2 Error envelope — insert — ambiguity — unmatched routes/methods answered ERR_INVALID_REQUEST (400) — implementation/app.py:21-30
- §2.3 Pagination — insert — ambiguity — non-integer/out-of-range limit and negative/non-integer offset → ERR_INVALID_REQUEST — implementation/envelope.py:62-81
- §2.4 Common fields — insert — ambiguity — `version` starts at 1 on creation — implementation/store.py:37
- §2.5 Clock — insert — ambiguity — bad `to_iso8601` → ERR_INVALID_REQUEST; `current_utc` rendered without fractional digits; backward moves clamp advanced_periods to 0 — implementation/routes/clock.py:34-42, 96
- §2.5 Clock — insert — ambiguity — every advance touches (version-bumps) every org; sustained-overage accrual touches org a second time — implementation/routes/clock.py:46-48, 88-90
- §3.2 Credit pool — insert — ambiguity — second pool per org → ERR_DUPLICATE_VALUE; pool creation mutates the org record (version bump) — implementation/routes/pools.py:32-33, 45
- §3.2 Projection — insert — ambiguity — missing/non-integer `periods` and bad `mode` → ERR_INVALID_REQUEST; forward base is 0 when no pool exists — implementation/routes/pools.py:75-82, calc.py:159-160
- §3.4 Grant creation — insert — ambiguity — creation does not gate on product status; only activation enforces retirement — implementation/routes/grants.py:43-45
- §3.6 User transition — insert — ambiguity — target enum {ACTIVE, DISABLED, DEACTIVATED}; wrong-state error mapping (ACTIVE→ERR_USER_NOT_INVITED, DEACTIVATED→ERR_USER_NOT_DISABLED); LicenseAdmin-only ops with state-check-before-role-check ordering — implementation/routes/users.py:90, 147-149, 150-160
- §3.7 Batch creation — revise — mismatch — reordered check narrative to impl order (sufficiency → idempotency → key active/scoping → NamedUser own-key → extension); added missing own-key check (ERR_NOT_ITEM_OWNER); no-pool available treated as 0 — implementation/routes/batches.py:57-88
- §3.7 Idempotency — insert — ambiguity — payload equality covers exactly organization_id, api_key_id, service_kind, requested_units, extension_code — implementation/routes/batches.py:15-16
- §3.7 Settlement — revise — mismatch — key-active check runs before posture gate (impl order); reversal skips org-active/key/posture gates; pool-less org → ERR_NO_CREDIT_POOL on transition — implementation/routes/batches.py:147-177
- §3.7 Reversal — insert — ambiguity — pending-period count floored at zero (no negative late fee); storage batches carry `content_item_id`; `settled_credits` null until settlement — implementation/routes/batches.py:179-181, items.py:98,111
- §3.8 EV begin-review — insert — ambiguity — RENEWAL_REQUIRED exception to ERR_EV_NOT_SUBMITTED; fresh-EV null fields (decided_by, rationale, valid_through_period) — implementation/routes/evs.py:34-36, 86-99
- §3.9 Moderation — insert — ambiguity — flag cascade also forces derivative items' sharing_level to PRIVATE — implementation/routes/items.py:255-256
- §3.9 Retraction — insert — ambiguity — state check precedes caller gate (non-owner + DRAFT → ERR_ITEM_NOT_PUBLISHED) — implementation/routes/items.py:184-187
- §3.10 Authorization — insert — ambiguity — AUTHORIZED re-targeted at AUTHORIZED yields ERR_SERVER_NOT_AUTHORIZED (not NOT_REGISTERED) — implementation/routes/servers.py:150-153
- §3.10 Upgrades — insert — ambiguity — completion call needs no `target_major_version` (recorded value reused) — implementation/routes/servers.py:84-85, 113
- §3.10 Peer evaluation — insert — ambiguity — warnings returned as `meta.warnings` list, one per offending peer, key absent when empty; rule with no matching peers passes vacuously — implementation/routes/servers.py:122-136, 148
- §3.10 Decommission — insert — ambiguity — `seats_in_use` decrement floored at zero — implementation/routes/servers.py:175
- §3.11 API keys — insert — ambiguity — org-id mismatch rejected with ERR_INVALID_REQUEST; invalid `allowed_service_kinds` elements → ERR_INVALID_REQUEST; self-issuance check runs after entity/scope resolution — implementation/routes/keys.py:26-37
- §4 Endpoint table (4 rows) — revise — ambiguity — pinned EV transition dual use of target UNDER_REVIEW, publish/retract target values and role split, `status` filters on extension-grant and api-key list endpoints — implementation/routes/evs.py:69, items.py:149, grants.py:207, keys.py:61

**No remaining known gaps:** all error codes in the PRD §5 catalogue are exercised by the implementation and vice versa; every route module (clock, orgs, pools, products, grants, users, servers, items, keys, batches, evs) plus store/calc/helpers/auth/envelope/errors was walked.
