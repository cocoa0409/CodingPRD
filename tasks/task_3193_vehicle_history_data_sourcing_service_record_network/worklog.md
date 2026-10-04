# Worklog — task_3193_vehicle_history_data_sourcing_service_record_network

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Used the pre-allocated directory `./tasks/task_3193_vehicle_history_data_sourcing_service_record_network` (with `workspace/` inside) as instructed; verified it exists. No new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T00:00:00.000Z

Done. All three scaffold artifacts are written and pass `scaffold_lint.py` with a clean verdict.

### Files written

- `SCAFFOLD.yaml` — 1670 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1306 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1665 lines (single key `scaffold_corner_design`)

### Surface counts (SCAFFOLD.yaml)

- **Entities: 11** — Network, DataSource, Shop, Vehicle, HistoryRecord, CorrectionRequest, ConsumerAccount, Dealer, InventoryListing, GuaranteeClaim, ReportOrder
- **State machines: 7** — DataSource (cyclic ACTIVE↔SUSPENDED with remediation/streak gates), Shop (cyclic + deferred tier upgrade), HistoryRecord (supersede/withdraw/void with rollup cascades), CorrectionRequest (branching fork: AWAITING_SOURCE → VERIFIED/REJECTED/EXPIRED, only VERIFIED joins to APPLIED), InventoryListing (DRAFT→PUBLISHED→DELISTED with claim-in-flight gate), GuaranteeClaim (OPEN→APPROVED/REJECTED/DENIED→PAID), Dealer (auto-suspension on balance > $10k)
- **Concurrency rules: 3** — OCC on Vehicle (record ingest), Vehicle (correction open), InventoryListing (guarantee enroll), all via `expected_*_version` + 412
- **Calculations: 11** — vin_match (Hamming-1 fuzzy), dedupe_grouping, brand_normalization (severity-ranked lexicon), vehicle_brand_rollup (max severity + tie-break), accident_confidence (dual-variant provisional/recomputed), feed_reliability_decay (asymmetric −10/+2), shop_tool_tier, report_price (tiered overage with pinned counter-last evaluation order), subscription_window, claim_window_overlap (closed occupancy vs half-open window), guarantee_payout (waterfall with lifetime-cap clamp variants)
- **Validations: 21** ordered priorities across auth/existence/state/temporal/constraint/referential/fiscal
- **Endpoints: 71** (flat topology with `api_prefix: ""`; includes `/_clock/set_current_utc` with default 2026-09-01T00:00:00Z and full FK reverse-reachability GETs)
- **Errors: 34** domain-specific codes
- **Roles: 6** — NetworkAdmin (opaque), SourceOperator (entity_backed:DataSource), ShopOperator (entity_backed:Shop), VehicleOwner (entity_backed:ConsumerAccount), DealerAgent (entity_backed:Dealer), GuaranteeAdmin (opaque)

### Design instances

- **§1.8: 18 instances** (2 per each of the 9 Difficulty Rules) — dual-variant domains split HistoryRecord-confidence vs GuaranteeClaim-payout; combinatorial modes (a) multi-input nonlinear confidence and (c) circular counter-last pricing; cascades of depth 3 (epoch→source→record→rollup→claim DENIED) and depth 2 (correction-apply→supersede→rollup); interval semantics split closed claim-occupancy vs half-open publication window; conserved quantities split Network.enrolled_listing_count vs snapshot+credit pair
- **§1.9: 39 instances** across sections entities/state_machines/calculations/validations/endpoints/errors/roles/cross_cutting_layers/consistency_model; all instance names unique across both files (57 total)

### Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes for downstream consumers: (1) the URL surface is flat (e.g. `POST /records`, `GET /vehicles/{id}`) because the lint's FK collection-segment heuristic requires single-resource GETs at `<prefix>/<segment>/{id}` depth — network scoping is by request body `network_id?` filters plus network-scoped list aliases under `/networks/{networkId}/...`; (2) a handful of recipes mark bulk iteration with `# LOOP xN` comments for the unit-test generator to expand (25 included reports, 49 service records, 29 epoch advances); (3) `POST /claims` admits DealerAgent in its role list so the §1.8 auth-vs-existence priority test can reach the later validation layers.

## Step 3: Copy shared files — 2026-09-30T00:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T00:00:00.000Z

All checks pass. The PRD is complete.

**Output path:** `workspace/PRD.md` — **Line count:** 349 lines

**Section list:**
- §1. Introduction (2 paragraphs: trust/attribution angle + commercial-lifecycle angle)
- §2. Global Specifications — 2.1 RBAC (with per-role identity semantics), 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Resource Properties & Monetized Precision, 2.5 Logical Clock & Feed-Health Epoch, 2.6 Feed Reliability & Source Suspension, 2.7 Brand Normalization & Severity Ranking (incl. default CA/TX lexicon), 2.8 Optimistic Concurrency Control (all three OCC rules with `expected_vehicle_version` / `expected_listing_version` and `ERR_STALE_VERSION`/412), 2.9 Hierarchical Consistency & Nested Resource Retrieval
- §3. Business Logic — 3.1 Network & source registration, 3.2 Epoch advance (decay/suspension/purge sweep), 3.3 Record ingest (VIN match, dedupe, idempotency), 3.4 Vehicle rollups, 3.5 Accident confidence (provisional vs recomputed variants), 3.6 Shops, service records & tool tiers (incl. count==10 no-op and inclusive 50 threshold), 3.7 Corrections (route/confirm/deny/expire/apply), 3.8 Dealers & subscriptions (30-epoch half-open window, $10,000 auto-suspension), 3.9 Listings & guarantee enrollment, 3.10 Claims (closed occupancy, half-open window, payout waterfall with capped/uncapped variants, claim sweep), 3.11 Report pricing (consumer first/returning rates, dealer included tranche + tiered overage with floor, pinned evaluation order with counter incremented last)
- §4. Endpoint Definitions — 4-column table covering all 68 endpoints
- §5. Error Code Catalogue — 2-column table covering all 34 error IDs

**Contract reports:**
- Contract 1 (Field-Name Coverage): PASS — 85 required identifiers (entity fields, request-body keys, path params), all present in backticks. Path-param names (`networkId`, `sourceId`, …) explicitly enumerated in §2.9 after the first pass flagged them as only appearing inside whole-path tokens.
- Contract 2 (Rule Coverage): PASS — all state machines with preconditions paired to error IDs; all 10 calculations rendered as precise prose; all 21 validation rules matchable to their `error_id` in §2/§3 prose; all 3 OCC rules fully expressed; all endpoint side effects narrated.
- Contract 3 (§3 Path Purity): PASS — 446 backticked tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combos.

**Zero-Silence Rule coverage notes:** All scaffold rules were rendered. Deliberately rendered detail includes: the default CA/TX brand lexicon contents (§2.7), the exact lexicon-term strings ("salvage certificate", "manufacturer buyback", etc.), the asymmetric decay step sizes, the Hamming-distance-1 fuzzy VIN rule with the ambiguity rejection, idempotency short-circuit ordering before dedupe, the SERVICE-never-dedupes carve-out, the "count == 10 confers nothing" note from the shop tier endpoint side-effect, the inclusive 50/49 tier boundary, the half-open claim/publication window semantics (filing at `window_end_epoch − 1` valid, at `window_end_epoch` rejected), the capped vs uncapped payout variants, the provisional vs recomputed confidence variants, and the startup clock value `2026-09-01T00:00:00Z`. No scaffold rules were judged out of scope; the forbidden design-index files were not opened.

## Step 5: Generate unit tests — 2026-09-30T00:00:00.000Z

**Task:** `task_3193_vehicle_history_data_sourcing_service_record_network` — test infrastructure + suite generated per the prd-bench-unit-test-generator skill.

### test_helpers/ (1,334 lines)
- `__init__.py` (48) — barrel export (framework + PRD-specific)
- `types.py` (264) — 11 entity TypedDicts, status enums, role enum
- `api_client.py` (255) — `ApiClient(GenericApiClient)` with one method per PRD endpoint (flat topology, networkId scoping via filters)
- `api_errors.py` (86) — all 34 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` (105) — per-entity field assertions + confidence-level consistency checker
- `factories.py` (118) — payload factories, input fields only
- `constants.py` (54) — domain thresholds (decay/recovery, confidence bands, pricing, caps)
- `test_users.py` (52) — shared headers for opaque roles + per-instance builders for all four entity-backed roles
- `fixtures.py` (352) — composite setups: network+source, title/inspection submission, shop approval, service-record loops, enrolled/escalated listings, claims, corrections (routed/verified), dealer subscriptions, report purchases

### test_suite/ (1,765 lines, 14 files)
conftest (35) + 13 test files: 5 difficulty files (dual_variant, combinatorial, state_machines, cascades, invariants, boundaries_and_gates) and 7 corner files (entities, state_machines, calculations, validations, endpoints, errors, roles, cross_cutting).

### Tests: 75 total
- **Queue A (difficulty): 34 tests** covering 17/18 instances (2 each)
- **Queue B (corner): 41 tests** covering all 29 non-stub instances (the 3 two-test instances — odometer rule, shop 49/50 boundary — got a second boundary-side test)

### Skipped instances (1)
- `Difficulty/priority_pair_validation_conflict/auth_role_beats_existence_on_claims` — the instance asserts DealerAgent is forbidden from POST /claims, but PRD §4's role table and §3.10 prose both grant DealerAgent claim-filing, so a PRD-faithful implementation would not return ERR_FORBIDDEN_FOR_ROLE for that call. Fails unique derivability; no test emitted.

### Notable deviations from recipes (both PRD-mandated)
- `accident_confidence_provisional_vs_recomputed_variants`: recipe's expected 80/70 reliability path is impossible because a submission inside an epoch blocks that epoch's decay sweep (PRD §3.2 pins sweep ordering: source must be ACTIVE at the sweep, and submissions during the epoch count as a hit). Tests use a verified-consistent seed + 2-miss construction (reliability 80 at ingest → 70 after one later miss; scores 32 → 28, VOIDED at age 2).
- `odometer_rollback_rejected`: recipe's "same-day tie" sub-assertion contradicts the PRD's monotonicity rule (an equal reading on a *later* event date is trivially ≥ the earlier-dated max, not a tie). Tests assert the RULE: equal reading on a later date accepted; below-max on a later date rejected with ERR_ODOMETER_ROLLBACK.
- `claim_closed_occupancy_overlap_on_listing` second test: after approval the guarantee is voided, so a follow-up filing is rejected 409 — the error may legitimately be CLAIM_OVERLAP or GUARANTEE_NOT_ENROLLED (PRD pins both; approval voids the guarantee); the test accepts either 409 id.

### Stage 2 self-audit verdict: PASS
- Coverage audit: every non-skipped difficulty instance has ≥2 tagged tests; every non-stub corner instance has ≥1; no extra/dangling tags; no `skip`/`skipif`/`xfail` markers anywhere.
- PRD-citation pass: every test docstring ends with exactly one `Design:` line resolving to a real instance; every citation's quoted sentence was grep-verified verbatim against PRD.md (75/75 pass after one rewrite); no scaffold references in generated code.
- Collection: `pytest --collect-only` reports 75 tests, 0 errors.

## Step 6: Generate implementation — 2026-09-30T00:00:00.000Z

Implementation complete. Summary:

### Files written
- `workspace/implementation/app.py` — 2339 lines, single-file Flask app (all routes, services, calculations inline; no seeding; store = module-level dicts).
- `workspace/implementation/start.sh` — 10 lines; guarded `pip install` (no-op once Flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000).
- `workspace/implementation/requirements.txt` — `flask>=3.0`.

### Endpoint coverage
All 71 (method, path) pairs from the SCAFFOLD endpoint table are registered as Flask routes (71 `@app.route` decorators), including the clock control, all CRUD/state-transition endpoints, all list/filter variants, and the FK reverse-reachability reads.

### Key behaviors implemented
- Envelope exactly per PRD §2.2: `meta.api_request_id` (req_ + uuid24), `meta.api_request_timestamp` (logical clock), `response_type`, `data`; pagination fields in meta for lists; error body `{error_id, message}`.
- Logical clock: starts at `2026-09-01T00:00:00Z`, never wall-clock; `POST /_clock/set_current_utc` sets it (NetworkAdmin only).
- Auth priorities 1 (headers) → 2 (RBAC), then existence → state → business rules; identity-equality checks for SourceOperator/ShopOperator/DealerAgent.
- VIN matching (exact → Hamming-1 fuzzy → ambiguous 409 → lazy create), idempotency replay/conflict, dedupe groups (TITLE_BRAND by jurisdiction; ACCIDENT/INSPECTION by event_date; SERVICE never), same-source duplicate rejection vs supersession on content change.
- Brand normalization via fixed CA/TX lexicon; severity NONE..SALVAGE = 0..5; vehicle rollup with tie-break earliest event_date then earliest created_at.
- Accident confidence (provisional at ingest / recomputed at advance_epoch, floor rounding), UNRELIABLE purge at epoch-2 lag.
- Feed reliability decay (−10 miss / +2 hit, clamped 0..100), auto-suspension at streak 3 with WITHDRAWN cascade, remediation/termination epoch gates.
- Shop approval auto-provisioning SERVICE_SHOP source; tool tier PRO at ≥50 with deferred upgrade while suspended and immediate downgrade.
- Correction workflow OPEN → AWAITING_SOURCE → VERIFIED/REJECTED/EXPIRED → APPLIED (WITHDRAW or SUPERSEDE with corrected_record).
- Dealer subscriptions with half-open 30-epoch window, included vs tiered overage pricing (500/100-step/300-floor), counter incremented last, invoice-driven auto-suspension > 1,000,000 cents, reinstate gate.
- Listing lifecycle (DRAFT → PUBLISHED → DELISTED) with publish window, OCC `expected_listing_version`, enrollment snapshot of canonical_brand, network `enrolled_listing_count` maintenance, claim-in-flight delist block.
- Guarantee claims: ENROLLED gate, closed-occupancy overlap, half-open window check, approval with escalation attribution (post-open record), payout waterfall (base × 50/75/100% floored, lifetime-cap clamp), epoch sweep DENIED on lost escalation and PAID one epoch after approval.
- Reports: consumer 3999/1900 returning-buyer pricing with credit debit; dealer subscription pricing; frozen snapshots.
- OCC `expected_vehicle_version` on record ingest and correction open; `expected_listing_version` on enrollment; ERR_STALE_VERSION 412.

### Smoke test performed
Booted via `bash start.sh` on port 29417 (first attempt on 18193 collided with another pipeline's process — that PID was not touched). Verified end-to-end with curl:
- Network create (default lexicon present, epoch 0), missing-header 400, wrong-role 403, unknown network 404.
- Source lifecycle: submit before activation → ERR_SOURCE_NOT_ACTIVE; activate; TITLE_BRAND clean → vehicle lazily created, rollup CLEAN/1; idempotent replay returns original; same-content new-key → ERR_DUPLICATE_RECORD; changed content supersedes (old SUPERSEDED, counts correct); unknown brand term → 422; future event_date → 422.
- Shop approve provisions source + BASIC; service record accepted; odometer rollback → 422.
- Epoch advance: idle epochs 70 reliability after 3 misses, auto-SUSPEND at streak 3 with suspended_epoch_index; reactivate too early → 409; after one more epoch, reactivate → ACTIVE reliability 50.
- Corrections: stale version → 412; open/route/confirm-by-wrong-source → 403; confirm by owner source → VERIFIED; apply WITHDRAW → record WITHDRAWN, vehicle back to NONE/0.
- Guarantee: publish → enroll (enrolled_brand snapshot, count 1); brand escalation; claim filed; second claim → ERR_CLAIM_OVERLAP; approve → APPROVED payout 1,000,000 (100% at delta ≥3, cap-clamped), listing VOIDED, network count 0; advance epoch → PAID with payout_epoch_index.
- Reports: consumer insufficient credit → 402; after top-up 3999 first / 1900 returning; dealer STANDARD included report at price 0.
- Pagination meta fields and limit bounds enforced.

The test server was stopped (killed only the PID it started) and temp logs removed.

## Step 7: Test/fix iteration loop — 2026-09-30T00:00:00.000Z

Three 8-round parallel sweeps (`--isolation per-test-server`). Final: 75/75 in all 8 rounds.

### Round 1 (71/75 failing): systemic network_id mismatch
- **Root cause:** implementation's POST /sources, /shops, /consumers, /dealers required a `network_id` body field that PRD never names as an input field (PRD mentions `network_id` only as a list filter). The test fixtures, built PRD-faithfully, omit it.
- **Fix (implementation/app.py):** added `resolve_network(data)` — honors an explicit `network_id`, else falls back to the single existing network (same pattern the implementation already used for `POST /advance_epoch`). Replaced all four `require_string(data, "network_id")` sites.

### Round 2 (13/75 failing): six distinct issues
- **Test bug — record version passed as `expected_vehicle_version` (7 call sites, 6 tests):** `open_correction` was handed `title["version"]` / `record["version"]` (the record's own version, 1) where PRD §2.8/§3.7 require the *vehicle's* current version (2 after ingest+rollup). Fixed each site in test_corner_state_machines.py, test_corner_errors.py, test_difficulty_state_machines.py, test_difficulty_boundaries_and_gates.py to read `get_vehicle(api, ...)["version"]`.
- **Implementation bug — non-applicable fields stored verbatim (test_identical_content_new_key_rejected_changed_content_supersedes):** PRD §3.3 "fields not applicable to the record's type are null". Implementation stored a stray `damage_severity: 3` on TITLE_BRAND records, so the content signature differed and dedupe superseded instead of rejecting ERR_DUPLICATE_RECORD. Added per-type null coercion in `submit_record`.
- **Test bug — ambiguous-VIN setup self-collided (test_two_distance_one_candidates_rejected):** the second setup VIN was Hamming-distance 1 from the first, so it fuzzy-attached instead of creating a second vehicle, leaving only one distance-1 candidate for the probe. Changed the second setup VIN to `1HGCM82633A004341` (distance 2 from the first vehicle, distance 1 from the probe).
- **Test bug — second enrollment impossible while escalated (test_capped_variant_clamps_to_remaining_lifetime_allowance):** PRD §3.9 refuses enrollment unless canonical severity ≤ 1, so the second listing over the SALVAGE vehicle could never enroll. Rewrote the second half: withdraw the escalation via the correction workflow (brand back to CLEAN), enroll, re-escalate with a fresh salvage title, then file claim2. Assertions unchanged (still clamped to 1,400,000c).
- **Test bug — future event_date (test_same_and_cross_type_caps_cross_high_boundary, part 1):** fourth record used event_date 2026-09-02 while the logical clock sat at 2026-09-01. Added `set_clock(api, "2026-09-02T00:00:00Z")`.
- **Test bug — miss-streak off-by-one (test_suspension_cascade_withdraws_records, test_withdrawal_rollup_denies_open_claim):** PRD §3.2 counts the epoch-0 submission on the first advance, so three consecutive misses require 4 advances, not 3. Also corrected the post-suspension brand assertion from CLEAN to NONE — both titles came from the suspended source, so both withdraw.

### Round 3 (1/75 failing)
- **Test bug — same-source corroborator (test_same_and_cross_type_caps_cross_high_boundary, part 2):** the test counted the first MVA record as a same-type corroborator for the fourth MVA record, but PRD §3.5 restricts the agreeing set to records "submitted by a different source". Added a second MVA source (`mva2`) as the same-type corroborator; expectation 40+10+40=90 → HIGH now holds under the PRD rule.

### Round 4: 75/75 in all 8 rounds — clean.

## Step 8: Finalize PRD — 2026-09-30T00:00:00.000Z

Done. `PRD_FINALIZED.md` produced at `workspace/PRD_FINALIZED.md` with two minimal edits.

**Line counts / delta:** PRD.md 348 lines → PRD_FINALIZED.md 350 lines (+2 lines, +0.57%; one paragraph inserted, one sentence revised inline).

**Changes (one bullet per edit):**
- §3.1 — insert — new paragraph pinning network resolution for the un-nested create endpoints (`POST /sources`, `/shops`, `/consumers`, `/dealers`) and `POST /advance_epoch`: explicit body `network_id` always honored; when omitted, the single existing network is implied; omitted with zero or multiple networks → `ERR_INVALID_REQUEST`; unknown `network_id` → `ERR_NOT_FOUND`; advance_epoch also accepts `network_id` as a query parameter — `implementation/app.py:478-493` (`resolve_network`), call sites 1215/1452/1813/1860, and 1099-1105 (advance_epoch body-or-query variant).
- §3.3 — revise — "fields not applicable to the record's type are null" → "are stored as null — any value the client supplies for a field its record type does not use is coerced to null before the record is persisted, so the stored record and its dedupe content signature always carry null for those fields" — `implementation/app.py:1356-1374` (per-type coercion in `submit_record`), signature use at 884.

**Items deliberately not edited (PRD already pins them verbatim):** `expected_vehicle_version` = the vehicle's current version (§2.8/§3.7); corroborator set restricted to "a different source" (§3.5); per-epoch submission counting including epoch-0 records on the first advance (§3.2); future `event_date` rejection vs. the logical clock (§2.5/§3.3); enrollment requiring canonical severity ≤ 1 (§3.9). All test-side fixes were fixture bugs against already-unambiguous prose.

**Per-edit pre-edit search log:**

Edit 1 (network resolution):
- (a) Subject: how the owning network is determined for requests not nested under a network path, including the no-network / multi-network and unknown-id cases.
- (b) Enumerated impl paths: `resolve_network` (app.py:478-493) read in full; all four call sites read (`create_source` 1212-1231, `create_shop` 1449-1465, `create_consumer` 1810-1823, `create_dealer` 1857-1875); `advance_epoch` (1095-1105) read — same single-network fallback but accepts body or query param; confirmed all other endpoints resolve the network via the parent resource's stored `network_id` (`get_network_or_404` on source/shop/vehicle/correction), so they are unaffected.
- (c) Wording adjustment: scoped the rule explicitly to "platform-level creation endpoints that are not nested under a network path" plus the epoch-advance capability (with its query-param allowance), so no claim is made about nested endpoints; error split pinned (`ERR_INVALID_REQUEST` for missing/ambiguous, `ERR_NOT_FOUND` for unknown id) to match both `resolve_network` and the advance_epoch inline variant.

Edit 2 (non-applicable field null coercion):
- (a) Subject: stored state of type-specific fields not applicable to a record's type, and their role in dedupe content signatures.
- (b) Enumerated impl paths: coercion block in `submit_record` (1356-1374); content signature `(raw_brand_text, damage_severity, odometer_reading, reported_cost_cents)` at 884 fed by the coerced locals; `_build_record` storage (923-938); shop service-record endpoint (1563-1598) which only ever passes SERVICE-applicable fields — consistent; correction SUPERSEDE replacement (1762-1795) which defaults corrected fields to the target's already-coerced stored values — consistent with "stored as null".
- (c) Wording adjustment: framed the sentence around *stored* state ("stored as null … before the record is persisted, so the stored record and its dedupe content signature always carry null") rather than a universal claim about request validation, so it stays true for the shop endpoint (which never receives those fields) and the supersede path (which inherits coerced values), while pinning the coercion behavior the dedupe test exercised.

## Step 9: PRD completeness scan — 2026-09-30T00:00:00.000Z

Done. PRD_COMPLETED.md produced at `workspace/PRD_COMPLETED.md`.

- Source PRD_FINALIZED.md: 350 lines / 50,731 chars. PRD_COMPLETED.md: 350 lines / 55,393 chars. Delta: +4,662 chars, 0 added sections, 0 added lines (all edits inline).
- Counts: 17 ambiguity-pins (inserts), 4 mismatch-revisions (3 behavioral + 1 wording/self-contradiction).

Changes (in file order):

- §2.2 — revise — ambiguity — `api_request_timestamp` drops the "three fractional digits" claim and pins that all server-stamped timestamps carry the logical clock's current value — impl app.py:137-139, 152-163, 260-265.
- §2.3 — insert — ambiguity — list ordering tiebreak by `id` ascending — impl app.py:312.
- §2.4 — revise — ambiguity — `created_at`/`updated_at` drop "three fractional digits", pin logical-clock sourcing — impl app.py:152-163.
- §2.5 — insert — ambiguity — clock-set capability returns an empty object — impl app.py:1014-1019.
- §2.6 — insert — ambiguity — pins exactly which rejections increment `record_rejection_streak` (future event_date, unknown brand term, odometer rollback, stale version, idempotency conflict, duplicate content) — impl app.py:809-812, 834-836, 844-846, 855-857, 864-866, 886-888.
- §3.1 — insert — ambiguity — source registration requires `source_type`+`jurisdiction`; new source carries `record_rejection_streak` 0, `consecutive_missed_epochs` 0, `suspended_epoch_index` null — impl app.py:1216-1231.
- §3.2 — insert — ambiguity — epoch advance returns the updated network object — impl app.py:1204.
- §3.2 — insert — ambiguity — streak-reset works on any status; successful reactivation also clears `suspended_epoch_index` to null — impl app.py:1285-1290, 1280.
- §3.3 — insert — ambiguity — `vin` must be exactly 17 chars (ERR_INVALID_REQUEST); source identity mismatch is ERR_FORBIDDEN_FOR_ROLE; pinned ingest check order (future-date → idempotency → VIN match → OCC → brand → odometer → dedupe) — impl app.py:249-252, 1378-1379, 804-919.
- §3.3 — insert — ambiguity — idempotency keys are scoped per network; the compared payload tuple enumerated — impl app.py:816-836.
- §3.3 — insert — ambiguity — supersession targets the earliest-created (id tiebreak) same-source ACTIVE record in the group — impl app.py:881-882.
- §3.3 — insert — ambiguity — superseding record's `submitted_epoch_index` is stamped with the current epoch — impl app.py:949.
- §3.5 — insert — ambiguity — provisional confidence uses the source's current reliability at ingest — impl app.py:595-630, 953-954.
- §3.6 — insert — ambiguity — shop service-record identity mismatch is ERR_FORBIDDEN_FOR_ROLE — impl app.py:1567-1568.
- §3.6 — insert — ambiguity — shop reactivation clears `suspended_epoch_index` to null — impl app.py:1529.
- §3.6 — revise — mismatch — corrected the self-contradictory "terminated too — but only if that source has no ACTIVE records, in which case the source stays ACTIVE" to "only when the source has no ACTIVE records; when it still has them, the source stays ACTIVE while shop termination succeeds" — impl app.py:1549-1559.
- §3.7 — insert — ambiguity — `expected_vehicle_version` is required on correction open (omission → ERR_INVALID_REQUEST) — impl app.py:1627-1630.
- §3.7 — insert — ambiguity — `corrected_record` may come from the apply body with fallback to the open-time payload; payload check precedes target-ACTIVE check; omitted corrected fields inherit the target's values — impl app.py:1744-1748, 1750-1752, 1766-1776.
- §3.8 — insert — ambiguity — subscribe identity mismatch is ERR_FORBIDDEN_FOR_ROLE; downgrading to NONE clears `subscription_started_epoch` to null — impl app.py:1899-1900, 1905-1906.
- §3.9 — insert — ambiguity — invalid `window_end_epoch` is ERR_INVALID_REQUEST; publish check order (dealer ACTIVE → ownership → vehicle → DRAFT) pinned — impl app.py:2018-2020, 2008-2014.
- §3.9 — insert — ambiguity — `expected_listing_version` is required on enroll (omission → ERR_INVALID_REQUEST) — impl app.py:2051-2053.
- §3.10 — revise — mismatch — escalation attribution pinned to impl: currently ACTIVE title-brand record with severity equal to current `brand_severity` and `submitted_epoch_index >= claim.opened_epoch_index` — impl app.py:2078-2096.
- §3.10 — insert — ambiguity — claim sweep DENIED test pinned as the pure severity comparison — impl app.py:1172-1185.
- §3.10 — revise — mismatch — "one epoch after approval" replaced with "at the next epoch advance after approval (and any advance thereafter while APPROVED)" — impl app.py:1187-1192.
- §3.11 — revise — mismatch — consumer email uniqueness: PRD said "unique within the network", impl does not enforce; revised to "intended to be unique — the platform records but does not police this uniqueness" — impl app.py:1810-1823.
- §3.11 — insert — ambiguity — report snapshot's exact field shape and record ordering — impl app.py:2225-2253.
- §3.11 — insert — ambiguity — buyer id defaults to acting `X-User-ID`; cross-product/role purchase is ERR_FORBIDDEN_FOR_ROLE; dealer purchase for another dealer is ERR_FORBIDDEN_FOR_ROLE — impl app.py:2270-2296.

## Final verification — 2026-09-30T00:00:00.000Z

Pipeline complete. All 8 rounds of the final sweep: 75/75 passing (verified from `workspace/implementation/results.{1..8}.json`). Output tree: SCAFFOLD.yaml (1670 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1306), SCAFFOLD_CORNER_DESIGN.yaml (1665), worklog.md, test_helpers/ (9 files, 1,334 lines), test_suite/ (75 tests, 14 files, 1,765 lines), workspace/{INSTRUCTION.md, PRD.md (348 lines), PRD_FINALIZED.md (350), PRD_COMPLETED.md (350), implementation/{app.py (2339 lines), start.sh, requirements.txt, results.1-8.json}}.
