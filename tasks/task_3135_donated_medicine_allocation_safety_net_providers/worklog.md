# Worklog — task_3135_donated_medicine_allocation_safety_net_providers

## Step 1: Create Task Directory — 2026-09-30T02:53:00.000Z

Pre-allocated task directory `tasks/task_3135_donated_medicine_allocation_safety_net_providers/` verified to exist with `workspace/` inside. Used the pre-allocated path as instructed (no new index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-09-30T04:06:46.000Z

Generated three scaffold artifacts for `task_3135_donated_medicine_allocation_safety_net_providers`:

**Files written (absolute paths):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3135_donated_medicine_allocation_safety_net_providers/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_3135_donated_medicine_allocation_safety_net_providers/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_3135_donated_medicine_allocation_safety_net_providers/SCAFFOLD_CORNER_DESIGN.yaml`

**Key stats (per lint report):**
- Entities: **13** (ManufacturerDonor, ProductLot, RecipientSite, License, AllocationRequest, AllocationDecision, AllocationLine, Shipment, CustomsDeclaration, EmergencyEvent, PrepositionedModule, ValuationSnapshot, DistributionReport)
- State machines: **11** (one per stateful entity; ProductLot posture, RecipientSite qualification with cyclic QUALIFIED↔SUSPENDED, License, AllocationRequest with revision loop, AllocationDecision with SUPERSEDED, AllocationLine with FORFEITED sweep, Shipment with fork-join on is_international, CustomsDeclaration, EmergencyEvent, PrepositionedModule, DistributionReport)
- Calculations: **8** (lot_available_quantity, need_score with weighted scoring + emergency/cold-chain variants, valuation_total with per-lot-rounding + dual methods, customs_declared_value, site_active_license_count, shipment_temperature_band, overreport_check, reservation_ttl with emergency variant)
- Validations: **26** ordered priorities (auth → existence → state → safety → temporal → constraint → fiscal → referential)
- Endpoints: **70** (full CRUD + state actions + `_clock/set_current_utc` test-driving endpoint with default `2026-09-01T00:00:00Z`)
- Errors: **26** domain-specific codes
- Roles: **8** (PlatformAdmin, QAPharmacist, ComplianceOfficer, AllocationOfficer, LogisticsCoordinator, SiteCoordinator [entity_backed:RecipientSite], EmergencyManager, DonorReportingOfficer) — segregation-of-duties role model
- Difficulty instances: **18** (9 rules × 2 instances, all differentiated per §0.5: dual-variant on valuation-vs-need-score domains; combinatorial across modes (a) and (b); non-linear shapes on RecipientSite cycle and Shipment fork-join; cascades from clock-driven license expiry vs QA-driven recall; priority conflicts on (state, safety) and (safety, fiscal); boundaries on overreport equality vs zero-count licenses; cross-entity deps on Shipment×CustomsDeclaration and AllocationDecision×RecipientSite; overlap rules with strict-> vs inclusive->= interval semantics; invariants on lot quantity conservation and request approval conservation)
- Corner instances: **37** active (plus 2 `excluded_because:` stubs) across all 9 taxonomy sections

**Difficulty design highlights ("much harder than expert"):**
- Logical clock with deterministic default; drives expiry sweep, license expiry cascade, reservation TTL forfeiture, and emergency stand-down — all reproducible from empty-DB via `_clock/set_current_utc`
- Two OCC concurrency rules (decision-finalize on AllocationRequest.version; site-suspend on RecipientSite.version), each triggered by strictly sequential calls
- Per-lot-then-sum rounding pinned explicitly, with a worked example (3×0.335 + 7×0.045 = 1.33 per-lot vs 1.32 sum-then-round)
- Transitive cascade depth 4: clock advance → License EXPIRED → active_license_count=0 → site SUSPENDED → requests CANCELLED → lines RELEASED → lot counters recomputed
- Segregation-of-duties enforcement on DistributionReport accept/reject (reviewer_user_id != submitted_by_user_id)
- Shipment fork-join: international branch adds customs clearance gate before dispatch

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy Shared Files — 2026-09-30T04:07:05.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T04:15:30.000Z

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_3135_donated_medicine_allocation_safety_net_providers/workspace/PRD.md`
**Line count:** 309 lines
**Files NOT read (per hard constraint):** `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` — untouched.

### Section coverage
- **§1 Introduction** (2 paragraphs) — donated-medicine business context, role segregation rationale
- **§2 Global Specifications** — 2.1 RBAC + per-role identity semantics (SiteCoordinator entity-backed, seven opaque roles individually named); 2.2 verbatim response-envelope contract; 2.3 Pagination (limit default 10, min 1, max 100, offset default 0, `created_at` ascending); 2.4 Logical clock (initial value `2026-09-01T00:00:00Z`, `current_utc` input, sweep behavior); 2.5 Common resource properties (`id` UUID, `created_at`, `updated_at`, `version`); 2.6 OCC (both rules, exact occ fields, `ERR_STALE_VERSION`/412); 2.7 Validation priority ordering (all 26 priorities explicitly enumerated); 2.8 Quantity ledger invariants; 2.9 Cold-chain & controlled-product protocols; 2.10 Nested retrieval + path-param naming; 2.11 Precision (round-half-up, per-line-then-sum)
- **§3 Business Logic** — 11 subsections: donor/lot intake, QA release/recall/expiry, site qualification & licensing, request lifecycle (incl. cyclic `APPROVED`/`PARTIALLY_APPROVED` → `UNDER_REVIEW` re-open), decision drafting/finalization/supersession/voiding, need scoring (all four components, capped volume factor, emergency boost, −50 cold-chain penalty), shipment packing/customs/delivery/failure/cancel, reservation forfeiture (72h standard / 24h emergency TTL), emergency events & pre-positioned modules, donor valuation (both methods, per-lot rounding before sum), distribution reporting (overreport check, segregation-of-duties)
- **§4 Endpoint table** — 70 rows, 4 columns (Method / Path / Description / Authorized Roles)
- **§5 Error catalogue** — 26 rows, 2 columns (Error ID / HTTP Status)

### Hard-contract audit results
```
Field coverage check:
- entities[].fields: 91 required, 91 present, 0 missing
- endpoints[].request_body: 68 required, 68 present, 0 missing
- endpoints[].query_params: 28 required, 28 present, 0 missing
- path params: 13 required, 13 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 26 checked, all 26 expressed in priority order in §2.7 plus inline near workflows, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_request_version + expected_site_version, ERR_STALE_VERSION / 412, no race framing), 0 missing
- state_machines[].transitions: 36 checked (across 11 machines), 36 fully expressed incl. cascades, 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise prose (no pseudocode, no fuzzy words), 0 missing
- validations[] conditions: 26 checked, 26 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 70 endpoints checked, side effects and guard scopes expressed, 0 missing
- entities[].fields[] structured content: 91 checked, defaults/derived booleans/initial states placed on owning entity, 0 missing
- sibling-branch symmetry: 6 groups checked (recall from QUARANTINED/RELEASABLE; expiry from QUARANTINED/RELEASABLE; re-open from APPROVED/PARTIALLY_APPROVED; pack-complete domestic/international; valuation ACQUISITION_COST/WHOLESALE_REFERENCE; TTL standard/emergency), 6 with equal density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 0 path/method violations out of all §3 tokens
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three hard contracts report PASS.

## Step 5: Generate Unit Tests — 2026-09-30T04:41:37.000Z

Generated complete test infrastructure and suite for task_3135 (Donated Medicine Allocation to Safety-Net Providers), translating exclusively the two design indices under the PRD-first rule.

### Files written

**`test_helpers/`** (9 files):
- `types.py` — status/class enums + TypedDicts for all 13 entities
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~55 methods), paths under `/medicine-relief`
- `api_errors.py` — `ApiErrorId` enum (26 errors) + HTTP status map registered via `set_error_http_status_map`
- `constants.py` — need-score weights (100/1000/2.0/25/10/-50), TTLs (72h/24h), clock epoch, pagination defaults
- `test_users.py` — opaque headers for 7 roles + `make_site_coordinator_headers(site_id)` for the entity-backed `SiteCoordinator` (ownership checks compare `X-User-ID` to site id / `requested_by_user_id`)
- `factories.py` — payload factories for all 11 creatable resources
- `assertions.py` — per-entity shape assertions + lot quantity-ledger conservation invariant
- `fixtures.py` — composite helpers: clock, donor/lot (incl. `create_lot_batch`), verified license, qualified site (auto IMPORT license for international), full request→review→draft→finalize pipeline, domestic shipped/delivered pipeline, events/modules, distribution reports
- `__init__.py` — barrel export

**`test_suite/`** (6 files, 74 tests, all collect cleanly):
- `test_01_difficulty_calculations.py` (8), `test_02_difficulty_state_machines_and_cascades.py` (8), `test_03_difficulty_validation_priority.py` (4), `test_04_difficulty_boundaries_and_dependencies.py` (12), `test_05_difficulty_compensating_invariants.py` (4), `test_06..test_10_corner_*.py` (38)

### Coverage (audited programmatically)
- **Queue A (Difficulty): 18/18 instances, each with exactly 2 tests (36 tests)** — dual-variant valuation/need-score, per-lot rounding, site cycle, shipment fork/join, license-expiry and recall cascades, state-vs-safety and safety-vs-fiscal priority pairs, overreport + license-count boundaries, customs-gated dispatch, finalize-vs-site-qualification, license-expiry strict `>`, TTL inclusive forfeit, shipment-cancel restoration, supersede conservation.
- **Queue B (Corner): 37/37 non-stub instances, ≥1 test each (38 tests)**; 3 `excluded_because:` stubs not translated, cross-references verified to resolve.
- Every test docstring carries a verbatim PRD quote (74/74 grep-verified against `workspace/PRD.md`) and exactly one `Design: Difficulty/...` or `Design: Corner/...` tag resolving to a real instance.

### Skipped / judgment calls
- No instance fully skipped. Two assertions were relaxed where the PRD leaves design space open: (1) `created_at == logical clock` exact-equality in the common-fields corner (PRD declares logical-clock behavior only for `intake_recorded_at`-style stamps; asserted UUID/version/ISO-8601 instead); (2) dispatch-before-customs-clearance accepts `ERR_CUSTOMS_NOT_CLEARED` or `ERR_INVALID_STATE` since the shipment is in `AWAITING_CUSTOMS_DOCS` at that point and both guards are PRD-named (the clearance-unblocks-dispatch half is asserted exactly).
- No skip/xfail marks, no scaffold references in generated code. Tests were not executed (no implementation exists yet); pytest collection and helper import both pass.

## Step 6: Generate Implementation — 2026-09-30T05:26:15.000Z

**Files written** (all under `workspace/implementation/`):
- `start.sh` — guarded dependency install (`python3 -c "import flask"` check) + `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry point, error handlers, route registration
- `common.py` — in-memory store (13 entity dicts, starts empty), logical clock (initial `2026-09-01T00:00:00Z`), response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), auth (`X-User-ID`/`X-User-Role`, 8 roles), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10 / max 100), serializers, expiry sweep, shared cascades
- `routes_core.py` — clock, donors, lots, sites, licenses
- `routes_alloc.py` — allocation requests, decisions (incl. finalize with OCC, need scoring, supersession), lines
- `routes_logistics.py` — shipments (pack/dispatch/deliver/fail/cancel), customs declarations
- `routes_misc.py` — emergency events, prepositioned modules, valuation snapshots, distribution reports

**Endpoint count:** 70 (all from scaffold §1.5 / PRD §4).

**Entity/state-machine coverage:** all 13 entities (ManufacturerDonor, ProductLot, RecipientSite, License, AllocationRequest, AllocationDecision, AllocationLine, Shipment, CustomsDeclaration, EmergencyEvent, PrepositionedModule, ValuationSnapshot, DistributionReport) with all state machines and cascades: lot release/recall/expire, site qualify/suspend (OCC)/reinstate/revoke with request-cancel + line-release cascades, license verify/reject/expire with auto-suspend on zero active licenses, request begin-review (incl. APPROVED/PARTIALLY_APPROVED revision loop)/reject/cancel, decision finalize (OCC `expected_request_version`, segregation of duties on reviewer, supersession of prior FINALIZED decision, need_score, 72h/24h TTL) / void, line RESERVED→PICKED→SHIPPED→DELIVERED plus RELEASED/FORFEITED, shipment full lifecycle with customs gating and delivery-failed spoilage accounting, customs DRAFT→SUBMITTED→CLEARED/REJECTED with declared-value computation (per-line round-half-up before sum), event DECLARED→ACTIVE→STAND_DOWN→CLOSED with module auto-release, module reserve/deploy/consume, report submit (overreport check, equality allowed) and SoD-guarded accept/reject.

**Calculations:** need_score (100·underserved + 25·min(volume/1000, 2.0) + 10·severity if ACTIVE event − 50 cold-chain shortfall, round-half-up 2dp), valuation_total (per-lot round then sum, RECALLED excluded, both ACQUISITION_COST and WHOLESALE_REFERENCE variants), customs declared value (PICKED lines, acquisition cost), temperature band (max of mins / min of maxes, incompatibility rejected), overreport threshold, reservation TTLs, active license count — all per scaffold §1.3.

**Storage design:** pure in-memory dicts keyed by UUID hex id, guarded by a reentrant lock; insertion-order sequence for `created_at`-ascending list ordering. No seeding at startup — store is empty on every boot. `created_at`/`updated_at` use wall clock (3-fractional-digit ISO 8601); business timestamps (`intake_recorded_at`, `decided_at`, `dispatched_at`, `delivered_at`, `qualified_at`, `declared_at`, `generated_at`, `reservation_expires_at`) use the logical clock.

**Smoke test results:** 38/39 checks passed on first run — the one "failure" was a test-script artifact (intaking a lot with an already-past expiry after the last clock-set; sweep runs on clock advancement only, per spec), and verified the expiry sweep fires correctly on the next clock-set (lot → EXPIRED, `quantity_expired=100`, `quantity_available=0`). Fresh-reboot verification: empty store, envelope shape correct, clean shutdown by exact PID (no stray processes). Both OCC checks, SoD checks, ownership checks, pagination meta, error envelope, RBAC rejection, and the full donor→lot→site→request→decision→shipment→delivery→report→snapshot happy path exercised successfully.

## Step 7: Run Tests and Iterate — 2026-09-30T05:46:14.000Z

All 8 rounds pass 74/74. Clean sweep achieved.

## Summary

- **Iterations run:** 2 (initial sweep: 12 deterministic failures across all 8 rounds; fix + probe + final sweep: 74/74 × 8 rounds).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:**
  - `test_04_difficulty_boundaries_and_dependencies.py` — `test_finalize_after_site_suspension_rejected`: re-fetch the request's `version` after site suspension (suspension cancels the UNDER_REVIEW request, bumping its version) so only the site-qualification guard can fire. PRD pins both `ERR_SITE_NOT_QUALIFIED` and `ERR_STALE_VERSION` but never orders them against each other (error-precedence silence), so the fixture must not set up a stale version alongside the suspended site.
  - `test_09_corner_validations.py` — `test_stale_expected_site_version_rejected`: manufacture the OCC mismatch with `expected_site_version: 0` instead of assuming a license verification bumps the site's version. PRD says license transitions "recompute the site's `active_license_count`" but never states this bumps the site's `version` (version-bump-on-derived-recompute is not uniquely derivable); PRD pins `version` to start at 1, so 0 is a guaranteed mismatch.
  - `test_09_corner_validations.py` — `test_lines_exceeding_requested_quantity_rejected`: assert the sum-vs-`quantity_requested` rule at draft creation (PRD §3.5 states the rule in the draft-creation paragraph) instead of constructing a draft that PRD-faithful implementations must reject at creation.
- **Fixes applied to `implementation/`:**
  - `common.py` — `new_id()`: emit canonical dashed UUIDs (`str(uuid.uuid4())`) instead of 32-char hex; PRD §2 requires "a server-minted UUID" and the framework's `is_valid_uuid` requires the dashed form (fixed 4 failing shape tests).
  - `routes_alloc.py` — `check_line_business()`: split creation vs finalization checks. The controlled-site (`ERR_CONTROLLED_SITE_NOT_AUTHORIZED`) and cold-chain (`ERR_COLD_CHAIN_INADEQUATE`) guards are finalization-only per PRD §2.9 ("at decision finalization"), and the lot-availability invariant is commit-time only (drafts carry no reservation); creation keeps site-QUALIFIED, releasability, and the line-sum bound. Also reordered finalization guards to match PRD §3.5's explicit order (releasability → cold-chain → controlled → quantity → availability).
  - `routes_alloc.py` — `finalize_decision()`: moved the `expected_request_version`/OCC check to the end of the guard sequence (PRD §3.5's ordered list places it last) and made the field mandatory per PRD §2.6 ("requires the request body to include").
  - `routes_core.py` — `recall_lot()`: fold remaining non-shipped units into `quantity_expired` on recall so the derived `quantity_available` falls to zero per PRD §3.2 while keeping the five-bucket ledger (PRD §2.x: "units leave one bucket they enter another") reconciled.

## Step 8: Finalize PRD — 2026-09-30T05:52:00.000Z

Done. PRD_FINALIZED.md created with 3 inline edits, all traced to step_7_diff items.

**Line counts:** PRD.md = 309 lines; PRD_FINALIZED.md = 309 lines; +0.0% line delta (3 paragraphs revised in place, no sections added).

**Changes:**
- §2.5 — revise — pinned `id` to the canonical dashed 8-4-4-4-12 UUID form (`str(uuid.uuid4())`) — `implementation/common.py:251-252`.
- §3.2 — revise — pinned that recall folds remaining non-shipped units into `quantity_expired` (quarantined balance for QUARANTINED recalls; post-release `quantity_available` remainder for RELEASABLE recalls), with shipped units staying in `quantity_shipped`, keeping the five-bucket ledger reconciled — `implementation/routes_core.py:232-243`, `common.py:297-300`.
- §3.5 — revise — split draft-creation vs finalization guards: creation enforces site-QUALIFIED, lot RELEASABLE, per-line positive integer quantity, and the sum-vs-`quantity_requested` bound; cold-chain adequacy, controlled-site authorization, and lot-availability are finalization-only; releasability/site guards re-checked at finalization — `implementation/routes_alloc.py:67-117` (`check_line_business`), `routes_alloc.py:235-267, 286-349`.

**Step-7 items needing no PRD edit:** finalization guard order and mandatory `expected_request_version` (impl was changed to match PRD §3.5/§2.6, which already pinned both); the three `test_suite/` fixes were fixture bugs exploiting PRD silences that remain acceptably under-determined (error precedence between `ERR_SITE_NOT_QUALIFIED`/`ERR_STALE_VERSION`, version-bump-on-derived-recompute — impl `verify_license` bumps only the license and `active_license_count` is computed on read in `site_json`, so the PRD's silence stays consistent).

**Per-edit pre-edit search log:**
1. UUID format — (a) subject: server-minted id shape; (b) `common.py:251-262` (`new_id`/`stamp_new`, sole id path for all 13 resource types across `routes_core.py`, `routes_alloc.py`, `routes_logistics.py`, `routes_misc.py`); (c) none — every id flows through the one generator.
2. Recall bucket fold — (a) subject: which ledger bucket absorbs non-shipped units on recall; (b) `routes_core.py:203-245` (`recall_lot` QUARANTINED and RELEASABLE branches), `common.py:584-604` (`cancel_shipment` with `recalled_lot_ids` — PICKED lines on recalled lot go RELEASED without restoring committed, consistent since PICKED lines aren't committed), `common.py:297-300` (`lot_available` derivation), grep for `quantity_expired` across all routes (only `routes_logistics.py:186` delivery-failure fold, orthogonal); (c) added explicit "units already in `quantity_shipped` stay in that bucket" clause to avoid mis-describing the RELEASABLE-with-shipped-units path.
3. Creation vs finalization guard split — (a) subject: which decision guards fire at draft creation; (b) `routes_alloc.py:67-117` (both modes of `check_line_business`), `routes_alloc.py:235-267` (create), `routes_alloc.py:286-349` (finalize), full read of `routes_logistics.py` (shipment/customs paths never invoke these guards — shipment creation requires FINALIZED decision + RESERVED lines), grep for `ERR_INSUFFICIENT_AVAILABLE`/`ERR_CONTROLLED_SITE_NOT_AUTHORIZED`/`ERR_COLD_CHAIN_INADEQUATE` confirming `routes_alloc.py` is the sole raiser; (c) wording scoped availability explicitly to "commit-time … at finalization" and noted releasability/site guards re-checked at finalization, matching both `check_line_business` modes.

## Step 9: Complete PRD — 2026-09-30T06:01:12.000Z

Done. `workspace/PRD_COMPLETED.md` written.

**Source:** `PRD_FINALIZED.md` (309 lines / 49,865 chars) → `PRD_COMPLETED.md` (311 lines / 55,998 chars; +2 lines, +6,133 chars).

**Counts:** 18 ambiguity-pins, 7 mismatch-revisions.

### Changes (one per bullet: `{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`)

- §2.1 — insert — ambiguity — unrecognized but non-empty role strings yield `ERR_FORBIDDEN_ROLE`, not `ERR_UNAUTHENTICATED`; only missing/blank headers give 401 — common.py:164-178
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit→[1,100], offset→≥0); non-integer values → `ERR_INVALID_REQUEST`; `has_more` = `offset+limit < total_count` — common.py:111-139
- §2.3 — insert — ambiguity — enumerated the exact filter query parameters for all 14 list endpoints — routes_core.py:69-77,170-183,279-290,402-413; routes_alloc.py:164-177,275-284,363-374; routes_logistics.py:89-102,244-255; routes_misc.py:58-67,123-136,235-246,288-301
- §2.4 — revise — ambiguity — clock may be set to any instant (forward or backward); endpoint returns 200 `{"current_utc": ...}`; logical-clock timestamps render without fractional seconds when zero — routes_core.py:33-43, common.py:56-62
- §2.6 — revise — mismatch — `expected_request_version` is mandatory (missing = 412), but `expected_site_version` on suspension is optional and only enforced when supplied (PRD had said both mandatory) — routes_alloc.py:309-312 vs routes_core.py:327-330
- §2.7 — insert — ambiguity — payload parse-time validation (400 field/enum/date/range errors, `ERR_QUANTITY_INVALID` for non-positive `quantity_received`/`quantity_requested`) precedes the numbered guard sequence; endpoint-specific sequences in §3 are authoritative where they enumerate one — routes_core.py:115-117,255-256; routes_alloc.py:132-133,308-312
- §3.1 — revise — ambiguity — donor suspend only from `ACTIVE`, deactivate from `ACTIVE`/`SUSPENDED` (`DEACTIVATED`→`ERR_INVALID_STATE`); `dea_registration_no` optional — routes_core.py:79-99
- §3.1 — insert — ambiguity — `quantity_received` must be positive (`ERR_QUANTITY_INVALID` 422); `restricted_use_conditions` optional, defaults to `[]`; committed/shipped/expired initialized to 0 — routes_core.py:115-117,122-126,146-149
- §3.2 — insert — ambiguity — recall from any posture other than `QUARANTINED`/`RELEASABLE` → `ERR_INVALID_STATE`; recalled-lot `PICKED` lines on cancelled shipments go to `RELEASED`; fully-shipped/expired `RELEASABLE` lots are skipped by the expiry sweep — routes_core.py:209-244, common.py:584-604,640-644
- §3.3 — revise — mismatch — dropped the claim that `license_number` is unique per issuing-authority-plus-number (impl enforces no uniqueness) — routes_core.py:369-394
- §3.3 — insert — ambiguity — `underserved_index` outside [0.0,1.0] → `ERR_INVALID_REQUEST`; qualify only from `PENDING_REVIEW`; import-license check evaluated before active-license-count; reinstate failure → `ERR_NO_VERIFIED_LICENSE`; revoke from other statuses → `ERR_INVALID_STATE`; suspension OCC wording aligned with §2.6 optional semantics — routes_core.py:254-256,292-366
- §3.4 — insert — ambiguity — new requests start with `need_score` null, `quantity_approved` 0; missing emergency event → `ERR_NOT_FOUND`; revision-loop violation and reject-with-finalized-decision → `ERR_INVALID_STATE` — routes_alloc.py:123-156,190-214
- §3.5 — insert — ambiguity — `rationale` required non-empty; lines enter in `DRAFT`; draft creation requires no particular request status; decisions embed `lines` in both single-fetch and list representations — routes_alloc.py:235-267, common.py:413-425
- §3.5 — revise — ambiguity — finalize ordered check list now includes the site-`QUALIFIED` re-check (after reviewer check), empty-lines → `ERR_QUANTITY_INVALID`, reviewer mismatch → `ERR_FORBIDDEN_OWNERSHIP` 403, missing `expected_request_version` treated as mismatch, and no request-status precondition — routes_alloc.py:286-312
- §3.5 — revise — mismatch — void may be performed by any `AllocationOfficer` (PRD said "by its officer"; impl has no reviewer check) — routes_alloc.py:351-360
- §3.5 — insert — ambiguity — supersession precondition violation → `ERR_INVALID_STATE` — routes_alloc.py:316-324
- §3.7 — insert — ambiguity — shipments enter `PACKING` with `requires_cold_chain`/temperature bands/`customs_declaration_id` null; pack-complete with no `PICKED` lines → `ERR_INVALID_STATE`; non-`RESERVED` line or non-`FINALIZED` decision at creation → `ERR_INVALID_STATE`; declaration creation requires only international shipment (domestic → `ERR_INVALID_STATE`, no status precondition), replaces the shipment's declaration link; submit re-validates the import license (`ERR_IMPORT_LICENSE_MISSING`); confirm-delivery requires `DISPATCHED` — routes_logistics.py:39-81,104-123,152-169,204-286
- §3.8 — insert — ambiguity — `quantity_approved` recompute basis pinned to the `FINALIZED` decision's lines in `RESERVED`/`PICKED`/`SHIPPED`/`DELIVERED` — common.py:529-541
- §3.9 — revise — mismatch — removed the "COLD_CHAIN_VACCINE compatible only with outbreak-class events" constraint (impl has no such check; events have no class field) — routes_misc.py:138-159
- §3.9 — revise — mismatch — `quantity_on_hand` initialized to 0 at registration; dropped the "sum of manifest lines" phrasing (impl has no manifest concept) — routes_misc.py:97-115
- §3.9 — insert — ambiguity — severity outside 1–5 or non-string country codes → `ERR_INVALID_REQUEST`; invalid `intended_use` → `ERR_INVALID_REQUEST`; activate only from `DECLARED`; deploy against non-`ACTIVE` event → `ERR_EMERGENCY_NOT_ACTIVE`; consume with event not `ACTIVE`/`STAND_DOWN` → `ERR_INVALID_STATE`; close requires all referencing requests in `REJECTED`/`CANCELLED` — routes_misc.py:27-94,161-189
- §3.10 — insert — ambiguity — invalid snapshot `method` → `ERR_INVALID_REQUEST` — routes_misc.py:199-201
- §3.11 — insert — ambiguity — report creation enforces ownership (`X-User-ID` must equal `site_id` → `ERR_FORBIDDEN_OWNERSHIP`) and requires shipment `DELIVERED` (`ERR_INVALID_STATE`) — routes_misc.py:249-280
- §3.11 — revise — mismatch — removed "acceptance feeds donor-facing valuation-snapshot regeneration" (impl performs no such side effect) — routes_misc.py:334-347

**Notes:** Sections §2.2 (envelope), §2.5 (id/timestamps/version), §2.8-2.11, §3.6 (need-score formula), §4 (routing table), and §5 (error catalogue) already matched the implementation exactly and were left unchanged. No new sections added; all changes are in-paragraph inserts/revisions.
