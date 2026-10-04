# Worklog — task_3206_streaming_platform_channel_store_ad_share_device

## Step 1: Create task directory — 2026-09-30T10:23:39.000Z

Pre-allocated task directory `./tasks/task_3206_streaming_platform_channel_store_ad_share_device/` with `workspace/` already exists (per command args); verified present. No new task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T10:23:39.000Z

All three files written, lint clean, quality checks pass.

**Task**: `task_3206_streaming_platform_channel_store_ad_share_device` — Roku-style streaming platform (channel store + certification, subscription/ad revenue share, ad inventory split, paid home-screen placement with measurement, near-cost device hardware with subsidy recovery, OS licensing/update obligations, viewer privacy controls, channel removal/disputes).

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3206_streaming_platform_channel_store_ad_share_device/`):
- `SCAFFOLD.yaml` — 1950 lines — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1464 lines — single top-level `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1856 lines — single top-level `scaffold_corner_design:`

**Coverage statistics**:
- Entities: 15 (Publisher, Channel, ChannelVersion, ViewerAccount, Subscription, AdSlotGrant, AdCampaign, PlacementBooking, TvManufacturer, DeviceModel, LabBooking, OsUpdate, DeviceUnit, RevenueStatement, Dispute)
- State machines: 11 (cyclic channel certification loop, parallel cert × compliance dimensions on DeviceModel, parallel billing × entitlement on Subscription, dispute appeal cycle, suspend/reinstate cycle)
- Calculations: 10 (incl. dual-variant subscription payout GROSS vs NET, dual-variant subsidy recovery STRAIGHT_LINE vs MONETIZATION, pinned per-entry-then-sum ad rounding, circularity-broken tier assignment with explicit evaluation order)
- Validations: 15 ordered priorities
- Endpoints: 98 (incl. `/_clock/set_current_utc` with the mandatory 2026-09-01T00:00:00Z default)
- Errors: 30, all triggerable and referenced
- Roles: 5 (PlatformAdmin/AdOps opaque; Publisher/Viewer/TvManufacturer entity-backed)
- Concurrency rules: 2 true OCC races (channel-version supersede, grant resplit), both 412 with `${var}`-only version payloads
- Difficulty instances: 18 (9 rules × 2, all §0.5 differentiation clauses honored — different entity domains, error-category pairs, metrics/endpoints, entity pairs, interval semantics, conserved quantities)
- Corner instances: 39 (36 active + 3 excluded-because stubs) across all 9 taxonomy sections

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint` (555 calls scanned, 0 violations, all 19 FKs reverse-reachable). Additionally verified: instance-name uniqueness across the union (57 names), no forbidden race vocabulary, all numeric asserts pre-computed as literals (e.g. GROSS 799 vs NET 755; straight-line 416 vs monetization 3500; net payout 63902; slot splits 700/301 → 650/351; cross-period refund conservation 8000/−8000).

## Step 3: Copy shared files — 2026-09-30T10:23:39.000Z

Copied `./INSTRUCTION.md` to `./tasks/task_3206_streaming_platform_channel_store_ad_share_device/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T10:23:39.000Z

All checks pass. Task complete.

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_3206_streaming_platform_channel_store_ad_share_device/workspace/PRD.md` — 378 lines.

**Section coverage checklist (all scaffold sections projected to prose):**

- §1 Introduction — 2 paragraphs (business context + reconciliation-integrity angle), not the templated "This document outlines…"
- §2.1 RBAC — headers `X-User-ID`/`X-User-Role`, all 5 roles exact, per-role `identity:` translation (3 entity-backed roles with ownership-compare prose, 2 opaque roles)
- §2.2 Response envelope — emitted verbatim from `section-2.2-response-structure.md`
- §2.3 Pagination — `limit` default 10 / min 1 / max 100, `offset` default 0, `created_at` ascending sort, meta fields
- §2.4 Logical clock — fixed epoch `2026-09-01T00:00:00Z`, no wall-clock fallback, `to_iso8601` input / `current_utc` output
- §2.5 Common resource properties — `id` (UUID, no prefix), `created_at`/`updated_at` (ISO 8601, 3 fractional digits), `version` (+1 per mutation, cascades included)
- §2.6 Precision — integer cents, basis points, round-half-up (signed: away from zero on .5), floor for slot splits and straight-line recovery
- §2.7 OCC — both rules (`expected_channel_version` on channel-version submit, `expected_grant_version` on grant resplit), `ERR_STALE_VERSION` / 412, explicit "no other endpoint takes a version field"
- §2.8 Validation order — all 15 priority tiers in order, including the pinned 5-step sub-order of the device referential checks
- §2.9 Cascade boundaries — suspension/removal/termination cascades, one-way semantics (reinstate does not un-pause/re-hold), no auto-refunds
- §2.10 Nested/filtered retrieval — left-to-right existence, `active_version_id` reverse-reachability filter, all FK-reverse listing endpoints enumerated
- §3.1–3.10 Business workflows — publisher standing (incl. `to_standing`/`reason`, `TERMINATED` cascade, outstanding-balance definition), channel certification loop (supersession, `ERR_REVIEW_IN_PROGRESS` vs `ERR_INVALID_STATE` disambiguation), publication/holds/removal (`held` flag), ad grants (floor split, 500 bps standing penalty at resplit, INV-SLOT, pinned per-entry-then-sum rounding with the [1,1,1]@3333bps counterfactual), campaigns (credit limit 100000, flight windows, impression cost, auto-complete at exact budget, privacy gate, pacing projection), placement bookings (half-open overlap, adjacency non-conflict, EXPIRED sweep), viewers/subscriptions (dual billing/entitlement dimensions, refund attribution by `refunded_at`), statements (3-period look-back tiering with `>=` 10000000 boundary, GROSS_SHARE vs NET_OF_FEES with 55-cents-per-charge, exact platform fee remainder, negative-net balance accrual/release), device domain (closed lab intervals + 24h buffer, capacity 3, overlap-before-capacity, compliance boundary semantics: deadline-inclusive compliance, 7-day grace, OVERDUE→license-suspend cascade, no auto-reinstate), disputes (compensating OVERTURNED reinstatement, 7-day appeal window inclusive), subsidy ledger (INV-SUBSIDY, both recovery variants, 24-month floor vs 3500 bps monetization, policy-mismatch errors)
- §4 Endpoint table — 4 columns only, all 63 endpoints
- §5 Error catalogue — 2 columns only, all 30 error IDs

**Hard contract results:**
- Contract 1 (field-name coverage): 84 entity fields, 60 request-body inputs, scalar outputs — all present in backticks; **PASS**
- Contract 2 (rule coverage): validation priorities (15 tiers, ordered), 2 OCC rules (endpoint + field + `ERR_STALE_VERSION` + 412 all named), all state-machine transitions/side effects, all 9 calculations in reconstructible prose (no pseudocode, no fuzzy words — scanned), all 30 error IDs matchable to prose conditions, endpoint side effects and `applies_to` scopes expressed, sibling-branch symmetry preserved (PASS/FAIL decide, GROSS_SHARE/NET_OF_FEES, STRAIGHT_LINE/MONETIZATION, UPHELD/OVERTURNED all get equal density); **PASS**
- Contract 3 (§3 path purity): 512 backtick tokens scanned, 0 paths / 0 bare HTTP methods / 0 method+path tokens; **PASS**

**Deliberate scattering decisions:**
- §3 organized as 10 subsections grouped by business domain (publishers / channels / ad inventory / campaigns / viewers / statements / devices-compliance / disputes / units-subsidy), not the 7-subsection template
- Endpoint request fields split across subsections: e.g. campaign creation fields in §3.5 while the fiscal gate constant (100000 cents) and privacy gate live in the same subsection's measurement/schedule paragraphs; `to_standing`, `reason`, `held`, `decision`, `outcome`, `failure_codes` distributed to the subsections that own the action
- Constants embedded in narrative: 500 bps penalty described as "five hundred basis points" in §3.1 but numerically in §3.4/§3.7; premier threshold as "10000000 cents"; straight-line term as "twenty-four monthly installments"; monetization rate as "3500 basis points … thirty-five percent"
- The two interval semantics (half-open placement windows vs closed+buffered lab windows) placed in §3.5 and §3.8 respectively, with the closed-interval "end equals start conflicts" asymmetry called out explicitly
- The pinned validation sub-order for device referential checks lives in §2.8 (priority 12) and is cross-referenced from §3.10 rather than duplicated verbatim

## Step 5: Generate unit tests — 2026-09-30T10:23:39.000Z

Done. Summary of the generated suite for `task_3206_streaming_platform_channel_store_ad_share_device`:

**Files written**

`test_helpers/` (1704 lines)
- `types.py` (382) — 16 entity TypedDicts + 20 status/role enums; all entities carry common fields per PRD §2.5.
- `api_client.py` (480) — `ApiClient(GenericApiClient)` with one method per each of the 63 endpoints in PRD §4.
- `api_errors.py` (74) — all 30 `ApiErrorId` values + HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` (195) — per-entity shape assertions plus `assert_slot_split_invariant` (INV-SLOT) and `assert_subsidy_invariant` (INV-SUBSIDY).
- `factories.py` (152) — input-only payload factories for all creatable entities.
- `constants.py` (35) — PRD thresholds (fee bps, penalty, credit limit, lab capacity, recovery constants, appeal window, default clock).
- `test_users.py` (34) — shared headers for opaque roles + mandatory `make_<role>_headers(id)` builders for the three entity-backed roles.
- `fixtures.py` (319) — composite setup helpers: publisher/channel certification chain, PUBLISHED-channel shortcut, ACTIVE campaign, certified device model (with clock advance), activated device unit, statement generate/finalize.
- `__init__.py` (33) — barrel export.

`test_suite/` (2860 lines, 75 tests) — `conftest.py` + 18 test modules (`test_01_`…`test_18_`), all importing from `test_helpers`.

**Test counts per queue**
- **Queue A (Difficulty): 36 tests** — exactly 2 per each of the 18 instances across all 9 rules.
- **Queue B (Corner): 39 tests** — 1 per each of the 36 non-stub corner instances, plus 3 boundary/split tests (7-day appeal boundary, safety-vs-temporal isolation probes) tagged to already-covered instances. The 3 `excluded_because:` stubs were not translated; all 3 cross-references resolve to real difficulty instances.

**Skipped instances**
None. Every non-stub instance in both indices had verbatim PRD coverage and a uniquely-derived outcome, so nothing was dropped and no skip/xfail markers exist.

**Self-check results**
- **Stage 1:** `python -m compileall` clean; `import test_helpers` succeeds; entity-backed role builders present and used by all ownership-gated fixture calls.
- **Stage 2:**
  - `pytest --collect-only` collects exactly 75 tests with no import errors.
  - Tag audit: 75/75 test functions carry exactly one `Design:` line as the last docstring line; 0 unknown tags; 0 under-covered instances (all 18 difficulty instances have 2 tests, all 36 non-stub corner instances have ≥1).
  - PRD verbatim audit: every quoted docstring span (C1) matches PRD.md literally — 0 failures.

## Step 6: Generate implementation — 2026-09-30T10:23:39.000Z

Implementation complete for task_3206. All files under `/home/ubuntu/github/CodingPRD/tasks/task_3206_streaming_platform_channel_store_ad_share_device/workspace/implementation/`:

**Files written (2,857 lines total)**

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded pip install (`import flask` check); `exec python3 app.py` |
| `requirements.txt` | 1 | flask>=3.0,<4.0 |
| `app.py` | 48 | Flask app, error handlers, blueprint registration, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 66 | In-memory store (dicts per entity), logical clock pinned at `2026-09-01T00:00:00Z`, UUID/timestamp/version helpers — no seeding |
| `errors.py` | 66 | ApiError class + all 30 error IDs with exact HTTP statuses |
| `response.py` | 60 | `meta`/`response_type`/`data` envelope, pagination meta (`limit`/`offset`/`total_count`/`has_more`) |
| `middleware.py` | 201 | `X-User-ID`/`X-User-Role` auth, role gating, pagination parsing, field/enum/period/datetime validators |
| `services/common.py` | 153 | Decimal round-half-up/floor helpers, cascades (channel suspend/remove, campaign pause, booking release), pacing projection |
| `services/statement.py` | 115 | Tier assignment (trailing-3-period lookback), GROSS_SHARE/NET_OF_FEES payout, net computation |
| `routes/core.py` | 165 | Clock + publishers (incl. standing machine + TERMINATED cascade) |
| `routes/channels.py` | 336 | Channels + versions, certification loop, OCC on `expected_channel_version` |
| `routes/viewers.py` | 183 | Viewer accounts, privacy PATCH, subscriptions (dual billing/entitlement dimensions) |
| `routes/grants.py` | 143 | Ad slot grants, split math, per-entry-then-sum revenue, resplit OCC |
| `routes/campaigns.py` | 363 | Campaigns, impression budget guard/auto-complete, placement bookings (half-open overlap, EXPIRED sweep) |
| `routes/devices.py` | 416 | Manufacturers, device models, lab bookings (closed interval + 24h buffer, capacity 3), OS updates, compliance refresh |
| `routes/units.py` | 221 | Device units, activation posture gates in pinned order, dual-variant subsidy recovery, INV-SUBSIDY |
| `routes/statements.py` | 310 | Statement generate/finalize/settle/dispute, full dispute lifecycle with 7-day appeal window |

**Coverage**
- **Endpoints: 63/63** implemented (all from the endpoint table).
- **Entities: 16/16**, each with `id`/`created_at`/`updated_at`/`version` common fields; version increments on every mutation including cascaded children.
- **State machines: 10/10** (Channel, ChannelVersion, Publisher standing, Subscription billing, AdCampaign, PlacementBooking, DeviceModel cert, DeviceModel update_compliance, DeviceUnit, RevenueStatement, Dispute).
- **Calculations: 9/9** — verified numerically: slot split 100@7000bps → 70/30; per-entry rounding [1,1,1]@7000 → payout 3; statement math gross 999 → sub_payout 799 / fee 200 / net 802; monetization recovery 1000 → 350 with cap; deactivation write-off conserves INV-SUBSIDY (350+650+0=1000).
- **Validation order** follows the 15-tier cascade (auth → role → ownership → existence → shape → state → cross-entity → policy → temporal → standing → uniqueness/capacity → referential pinned sub-order → fiscal → privacy → OCC last).
- **Errors: 30/30** with exact IDs and HTTP statuses from the catalog.

**Clean boot confirmation**
`bash start.sh` with `PORT=17321` launched in the foreground, bound `0.0.0.0`, answered HTTP within ~2s, and served a full end-to-end smoke (publisher → channel → certification → publish → viewer → subscription → grant → revenue → statement finalize → manufacturer → model → lab → certify → unit → sell → activate → recover → deactivate). OCC stale writes correctly return 412. Store starts empty; no seeding anywhere. The test server was stopped by exact PID; isolation-rule files (test_suite/, test_helpers/, difficulty designs) were never read.

## Step 7: Test/fix iteration loop — 2026-09-30T10:23:39.000Z

Clean 8-round parallel sweep: all 8 rounds at 74/74 passed.

**Iterations run:** 3 (initial sweep 70/75 → 73/74 → 74/74).

**Tests deleted (1):**
- `test_09_invariants.py::test_resplit_keeps_creation_snapshot_of_share_bps` — COMPUTED-FIELD SILENCE / unique-derivability collapse. PRD §3.4 pins `publisher_share_bps` as a creation-time snapshot of `default_ad_share_bps`, but the resplit sentence names only the "effective share" and `publisher_slots`/`platform_slots` recomputation; whether the stored `publisher_share_bps` field itself is rewritten at resplit is not derivable. A PRD-faithful implementation that overwrites the field with the effective bps (as the reference implementation does) is admitted by the prose. Scaffold rule that drove generation: entity field description "Snapshot of publisher.default_ad_share_bps at creation".

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/` (4):**
- `test_03_state_machines.py::test_device_model_overdue_blocks_new_unit_creation` — relaxed `ERR_MANUFACTURER_NOT_LICENSED` to `validate_error_is_one_of([ERR_MANUFACTURER_NOT_LICENSED, ERR_UPDATE_OVERDUE])` (+ added import). PRD names both errors; §2.8(12)'s pinned sub-order is scoped to activation (per §3.10), so unit-creation precedence between the two is not uniquely pinned.
- `test_08_resource_overlap.py::test_lab_bench_buffer_blocks_and_exact_24h_passes` — the "exactly 24h after prior end passes" assertion contradicted PRD §3.8 (closed intervals, inclusive endpoints, both windows buffered ±24h → a touch intersects). Exact-24h case now asserts `ERR_BENCH_OVERLAP`; success case moved to 2026-09-05T18:00 (49h after prior end, the first gap where neither window's buffer reaches the other).
- `test_10_lifecycles.py::test_campaign_auto_completes_at_exact_budget_boundary` — post-completion impression recording now expects `ERR_CAMPAIGN_NOT_ACTIVE` (PRD §3.5 verbatim: "Impression recording against a campaign that is not `ACTIVE` is rejected with `ERR_CAMPAIGN_NOT_ACTIVE`"), not `ERR_INVALID_STATE`.
- `test_18_disputes.py::test_dispute_appeal_cycle_redecides_upheld` — removed the final assertion that the channel returns to `REMOVED` after a re-decision of UPHELD. PRD §3.9 says only "the channel stays `REMOVED`" for an UPHELD channel-removal decision; after an OVERTURNED-then-appeal loop the channel is PUBLISHED, and PRD is silent on re-removal (branch-asymmetric side effect, not uniquely derivable). Kept the covered assertions (APPEALED → EVIDENCE → DECIDED/UPHELD).

**Fixes applied to `implementation/`:** none — the reference implementation was PRD-faithful on all five failures.

## Step 8: Finalize PRD — 2026-09-30T10:23:39.000Z

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_3206_streaming_platform_channel_store_ad_share_device/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 377 lines, PRD_FINALIZED.md 377 lines (0% delta; three in-place sentence revisions, no lines added or removed).

### Changes (3 edits; 2 of 5 step_7 items required no PRD change)

- **§3.4 (resplit paragraph, line 173) — revise** — pinned that resplit overwrites the stored `publisher_share_bps` with the recomputed effective share (not a frozen creation snapshot). — `implementation/routes/grants.py:29-34` (`_apply_split` writes `grant["publisher_share_bps"] = effective_bps`), called from resplit at `grants.py:130`.
- **§3.10 (unit creation, line 233) — revise** — pinned that unit manufacture applies the full pinned referential sub-order of §2.8 gates 1-3, including the `ERR_UPDATE_OVERDUE` check before the license check (PRD previously mentioned only CERTIFIED + LICENSED). — `implementation/routes/units.py:66` calls the shared `_activation_gates` at `units.py:41-50`.
- **§3.9 (dispute decision, line 229) — revise** — replaced "the channel stays `REMOVED`" with "the decision makes no change to the channel," covering the appeal-loop case where a channel restored to `PUBLISHED` by an earlier OVERTURNED decision is not re-removed by a later UPHELD. — `implementation/routes/statements.py:268-273` (only OVERTURNED mutates the channel).

**No edit for the other two step_7 items** — pure test bugs where the PRD already pinned the behavior verbatim:
- Lab-bench exact-24h case: PRD §3.8 already pins closed intervals with inclusive endpoints and ±24h buffers; impl `devices.py:188-199` intersects on `new_lo <= ee and new_hi >= es`, so a touch conflicts. Test assertion was contradicted by the PRD itself.
- Post-completion impression recording: PRD §3.5 already says verbatim "Impression recording against a campaign that is not `ACTIVE` is rejected with `ERR_CAMPAIGN_NOT_ACTIVE`"; impl `campaigns.py:223-225` matches.

### Per-edit pre-edit search log

1. **§3.4 resplit rewrite**
   - (a) Subject: the `publisher_share_bps` field's mutability at resplit.
   - (b) Paths enumerated: `grants.py:52,58,65` (creation snapshots raw `default_ad_share_bps`, no suspension penalty at creation — consistent with PRD creation sentence), `grants.py:29-34` (`_apply_split` overwrites the field), `grants.py:103` (record-revenue reads the stored field, so the rewrite is observable in later payouts), `services/statement.py:85` (statement sweep reads only `publisher_payout_cents`, unaffected), `services/common.py:101-102` (`grant_view` exposes the field in API responses).
   - (c) Wording chosen as "overwritten with that recomputed effective share (it is not a frozen creation-time snapshot)" — scoped strictly to resplit so the creation snapshot sentence is untouched; no claim made about revenue recording, which already reads the field by name.
2. **§3.10 unit-creation gate order**
   - (a) Subject: which referential gates apply at unit manufacture and in what order.
   - (b) Paths enumerated: `units.py:53-86` (`create_unit`, gates at line 66 before serial-uniqueness check), `units.py:123-141` (`activate_unit`, same `_activation_gates` at line 137), `units.py:41-50` (shared gate function: CERTIFIED → not-OVERDUE → LICENSED), `devices.py:182-184` (lab booking checks only LICENSED — unaffected), `devices.py:285-287` (model resubmit checks only LICENSED — unaffected). Gates 4-5 of §2.8(12) (update ROLLING, recovery-policy match) verified to belong only to `apply_os_update`/`record-ad-revenue`/`accrue-straight-line`, so wording says "gates 1 through 3."
   - (c) Added the explicit parenthetical "(gates 1 through 3, ...)" to avoid implying gates 4-5 run at creation.
3. **§3.9 UPHELD decision effect**
   - (a) Subject: channel status side effects of a channel-removal dispute decision.
   - (b) Paths enumerated: `statements.py:256-274` (`decide_dispute` — the only dispute path that mutates a channel; OVERTURNED moves REMOVED→PUBLISHED only if currently REMOVED; UPHELD does nothing), `statements.py:297-310` (`close_dispute` touches statements only), channel removal routes in `channels.py` (unaffected — dispute decisions never call them).
   - (c) Widened "the channel stays `REMOVED`" to "makes no change to the channel," with both the fresh-decision case (stays REMOVED) and the appeal-loop case (not re-removed) spelled out, so both branches of `decide_dispute` are described correctly.

## Step 9: Complete PRD — 2026-09-30T10:23:39.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_3206_streaming_platform_channel_store_ad_share_device/workspace/PRD_COMPLETED.md` written as a minimal patch over `PRD_FINALIZED.md`.

**Source vs output:** PRD_FINALIZED.md 377 lines / 57,935 chars → PRD_COMPLETED.md 377 lines / 61,758 chars (+3,823 chars, +0 lines; all changes are in-paragraph inserts/revisions).

**Counts:** 14 ambiguity-pins, 3 mismatch-revisions (17 edits total).

- §2.3 — insert — ambiguity — pinned ERR_INVALID_REQUEST for non-integer/out-of-range `limit`/`offset`, and `has_more == (offset+limit < total_count)` — implementation/middleware.py:51-71, implementation/response.py:38-40
- §2.4 — revise — mismatch — logical-clock list now says subscription `period_start` stamping (not "subscription period attribution"); statement attribution keys on `created_at` — implementation/services/statement.py:70-71 vs implementation/db.py:51
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — implementation/db.py:57
- §2.8 tier 3 — insert — ambiguity — path-identifier existence resolves before ownership on path resources (404 before 403) — implementation/routes/channels.py:234-236, implementation/routes/campaigns.py:133-135
- §2.10 — insert — ambiguity — replaced the dangling "filters documented per endpoint in §4" (§4 documents none) with the pinned filter list per list endpoint — implementation/routes/*.py list handlers
- §3.1 — insert — ambiguity — standing-transition `reason` is optional, type-validated only, never persisted; same-standing transition rejected with ERR_INVALID_STATE — implementation/routes/core.py:109-113
- §3.1 — insert — ambiguity — publisher-termination cascade stamps each removed channel's `removed_reason` as the fixed string `publisher terminated` — implementation/routes/core.py:123
- §3.3 — insert — ambiguity — suspension `reason` is any non-empty string; `policy_hold` set only when reason is exactly `POLICY` — implementation/routes/channels.py:126-131
- §3.4 — insert — ambiguity — grant creation is not gated on channel status or policy_hold (existence only) — implementation/routes/grants.py:44-46
- §3.4 — insert — ambiguity — `slot_revenue_entries` must be a non-empty array of non-negative integers, else ERR_INVALID_REQUEST — implementation/routes/grants.py:95-100
- §3.5 — insert — ambiguity — campaign creation does not consult channel status/policy_hold (gates apply at schedule/booking) — implementation/routes/campaigns.py:87-88
- §3.5 — insert — ambiguity — `impression_count`/`cpm_cents` are non-negative integers (zero accepted); supplied `viewer_id` must reference an existing viewer — implementation/routes/campaigns.py:211-222
- §3.5 — insert — ambiguity — HELD→EXPIRED sweep runs lazily on booking creation for the slot only; confirm/release do not trigger it — implementation/routes/campaigns.py:256-264, 290
- §3.7 — insert — ambiguity — `generated_count` counts both created and refreshed OPEN statements; provisional OPEN statement pins `sub_payout_cents=0`, `platform_sub_fee_cents`=full base, net = ad payout minus placement spend — implementation/routes/statements.py:52-78, implementation/services/statement.py:95-103
- §3.7 — insert — ambiguity — finalization and settlement always touch the publisher (updated_at/version bump) even when tier/balance unchanged — implementation/routes/statements.py:120-123, 136-138
- §3.8 — revise — mismatch — lab-booking check order pinned as license → model SUBMITTED → overlap → capacity (license before model-state, contra the generic §2.8 tier reading) — implementation/routes/devices.py:182-206
- §3.8 — insert — ambiguity — license suspension only from LICENSED (else state gate), `reason` optional; reinstatement blocked by any OVERDUE model fails with ERR_UPDATE_OVERDUE — implementation/routes/devices.py:84-102
- §3.9 — insert — ambiguity — a STATEMENT-subject dispute raised via POST /disputes carries null `statement_id` and moves no statement to DISPUTED; CHANNEL_REMOVAL dispute against a non-REMOVED channel fails with ERR_INVALID_STATE — implementation/routes/statements.py:184-205
- §3.10 — insert — ambiguity — activation against an inactive viewer account fails with ERR_INVALID_STATE — implementation/routes/units.py:132-133
- §3.10 — insert — ambiguity — serial-uniqueness check runs after the three referential gates at unit creation — implementation/routes/units.py:66-69
- §3.10 — insert — ambiguity — `revenue_cents` is a non-negative integer (zero accepted); neither recovery endpoint is gated on unit status — implementation/routes/units.py:186-187, 204-221
- §4 table — revise — mismatch — suspend row no longer claims "reason OPS or POLICY"; any non-empty reason accepted, `POLICY` sets the hold — implementation/routes/channels.py:126-131

Notable non-changes verified aligned: grant resplit OCC ordering (state gate before OCC), per-entry-then-sum rounding, half-open vs buffered closed-interval overlap semantics, tier lookback (FINALIZED/SETTLED/DISPUTED only), NET_OF_FEES 55c/charge variant, dispute appeal inclusive 7-day boundary, and the pause/release cascade directionality.
