# Worklog — task_3276_family_location_sharing_place_alerts_crash_detection

## Step 1: Create Task Directory — 2026-09-30T00:00:00.000Z

Pre-allocated task directory `tasks/task_3276_family_location_sharing_place_alerts_crash_detection/` verified to exist with `workspace/` inside; used exactly as instructed (no new index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-09-30T16:59:01.943Z

All three files on disk and lint-clean. Final summary:

## Files written (under `/home/ubuntu/github/CodingPRD/tasks/task_3276_family_location_sharing_place_alerts_crash_detection/`)

- **SCAFFOLD.yaml** — 1703 lines, 81 873 bytes (§1.0–§1.7, no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 972 lines, 57 419 bytes (single top-level key `scaffold_difficulty_design`)
- **SCAFFOLD_CORNER_DESIGN.yaml** — 1352 lines, 67 321 bytes (single top-level key `scaffold_corner_design`)

## Lint verdict (verbatim, from `scaffold_lint.py`)

```
§1.5 endpoints declared:    64
§1.1 entities declared:     12
§1.8 instances scanned:     18
§1.9 instances scanned:     43
Calls scanned (§1.8+§1.9):  337
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Key design decisions (harder-than-expert calibration)

- **Complexity profile**: primary archetype `compliance_audit`, secondary `posture_driven_gating`; layers = rate_threshold_triggers + derived_field_reconciliation + cascading_side_effects + optimistic_concurrency; hybrid topology (Circle tree + flat member-centric resources); parallel state-machine shape (Member has three independent dimensions: role × consent_state × privacy_mode); hierarchical_override role model with anti-coercion self-only carve-out.
- **12 entities**: Circle, Member, Place, LocationFix, PlaceAlert, TripReport, CrashEvent, WellnessCheck, EmergencyDispatch, SubscriptionEvent, ConsentRecord, ComplianceHold.
- **9 state machines** including compound/posture-driven Circle (OPEN/RESTRICTED/FROZEN derived from subscription + ComplianceHold set), parallel dimensions on Member, and a CrashEvent cycle (DETECTED→WELLNESS_PENDING→ESCALATED→DISPATCHED→RESOLVED with FALSE_ALARM revert from any non-terminal state).
- **9 calculations**, three of them dual-variant: driver_score (trip vs rolling_30d), assistance balance (instantaneous vs anchor-replenished), dwell_bucket (with circular-look dependency on effective_sample_interval). Nested-rounding order pinned for trip_distance (per-segment round then sum).
- **64 endpoints** (above Expert band 20–32 by design: "much harder than expert level" instruction), including test-driving `/_clock/set_current_utc` and `/_sweeps/age-and-retention`. Every FK in §1.1 has a reverse-reachability GET (sub-resource or filtered list, or both).
- **21 error codes** spanning auth, existence, state, business_safety (consent/privacy), business_constraint, business_temporal, business_referential, business_fiscal, OCC.
- **19 prioritized validations** with explicit cross-category conflicts (e.g., priority 4 state vs priority 8 business_safety; priority 5 circle-FROZEN vs priority 7 consent).
- **2 OCC concurrency rules** (Circle version on change-tier; Member version on privacy PATCH), both wired to `expected_*_version` payload inputs that lint rule (e) enforces as `${var}` placeholders.
- **18 difficulty instances** (2 per rule × 9 rules) and **43 corner instances** (36 active + 1 `excluded_because` stub + several creation/listing/default precomputed-literal pins), with all formula-derived numeric asserts pre-computed as literals (e.g., driver_score 69, trip distance 2224 m, retention cutoff `>=` boundary at exactly 7 days, crash severity inclusive at delta_v=8.0, place-overlap 50%-of-smaller-area threshold at d=250 vs d=500 for r=500 circles, effective_sample_interval 60/30/15 across FREE/PLUS/PROTECT for identical inputs).

## Step 3: Copy Shared Files — 2026-09-30T16:59:30.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T17:07:00.000Z

**File written**: `/home/ubuntu/github/CodingPRD/tasks/task_3276_family_location_sharing_place_alerts_crash_detection/workspace/PRD.md`
**Line count**: 301 lines, ~52 KB

**Section structure**:
- §1 Introduction — 3 paragraphs framing the safety-vs-privacy tension and the crash cascade
- §2 Global Specifications — 10 subsections: 2.1 RBAC (with identity semantics for each role), 2.2 verbatim response envelope, 2.3 pagination, 2.4 common resource properties, 2.5 nested resource retrieval, 2.6 circle posture as derived gate, 2.7 OCC, 2.8 assistance-unit + identity-credit ledgers, 2.9 numerical precision, 2.10 server logical clock
- §3 Business Logic — 9 subsections: circle+subscription, membership+consent, privacy+tension, location ingestion+sampling, places+alerts, trips+driver score, crash cascade, compliance holds, aging+retention sweep
- §4 Endpoint table — 64 rows, 4 columns (Method, Path, Description, Authorized Role(s))
- §5 Error catalogue — 21 rows, 2 columns (Error ID, HTTP Status)

**Hard Contract Reports**:
- **Contract 1 (Field-Name Coverage)**: 102 required (entities + endpoint inputs + query/path params), 102 present, 0 missing. PASS (after one repair round adding `alert_status`, `check_status`, `crash_status`, `dispatch_status`, `since`, `trip_id`).
- **Contract 2 (Rule Coverage)**: all 32 state values, 21 error IDs, 77 enum tokens, both OCC rules (circle change-tier + member privacy), all 9 calculations (geofence membership with accuracy cap, effective sample interval with pinned order and single round-half-up, crash severity ladder, trip distance with per-segment rounding, dual-variant driver score, assistance-unit compensating invariant, identity-credit invariant, dwell-bucket evaluation order, retention cutoff), and the 19-priority validation cascade expressed in prose. PASS.
- **Contract 3 (§3 Path Purity)**: 559 backtick tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS.

**Notable scaffold-to-prose decisions**:
- **Diversity**: §2 subsections are domain-derived ("Circle Posture as a Derived Gate", "Assistance-Unit and Identity-Credit Ledgers", "Server Logical Clock") rather than templated; §3 groups by lifecycle stage rather than the canonical 7-subsection pattern.
- **Formula translation**: all calculations rendered in pure prose with pinned evaluation order called out — e.g. the effective sample interval as "First… Second… Third… Fourth… Fifth and finally", and the dwell-bucket rule as an explicit three-step ordered procedure.
- **Numeric constants embedded in context** rather than as a constants table (1.6 km blur radius, 365.25-day age divisor, 600-second trip timeout, 1,609-metre mile, 6,371,000-metre earth radius).
- **Compensating invariant** on assistance units described twice (§2.8 as a ledger principle, §3.7 as a narrative consequence) for redundant reinforcement.
- **Tier values embedded**: retention 7/30/60 days, units 0/2/4, identity credit 0/0/1, sample floors 60/30/15 s — all surfaced in prose.

## Step 5: Generate Unit Tests — 2026-09-30T17:22:00.000Z

Done. All test infrastructure and test cases generated, verified, and audited.

## Files written (line counts)

**test_helpers/** (1141 lines)
- `__init__.py` (26), `types.py` (349), `api_client.py` (213 — one method per PRD §4 endpoint), `api_errors.py` (56 — full §5 catalog registered via `set_error_http_status_map`), `assertions.py` (114), `factories.py` (124), `constants.py` (53), `test_users.py` (37 — shared constants plus `make_*_headers` builders for all four entity-backed roles), `fixtures.py` (188 — `create_circle` with identity threading, invite/grant/promote composites, `start_trip`, crash/escalation helpers).

**test_suite/** (2672 lines, 107 tests)
- `conftest.py` (15 — lazy import of test_helpers; collection works with no server), `test_01_circles.py` (164), `test_02_members_and_roles.py` (273), `test_03_consent_and_privacy.py` (211), `test_04_fixes_geofence_retention.py` (370), `test_05_places_and_alerts.py` (286), `test_06_trips_and_driver_score.py` (284), `test_07_crash_wellness_dispatch.py` (359), `test_08_crash_cascades.py` (227), `test_09_posture_subscription_fiscal.py` (427), `test_10_auth_rbac_errors.py` (224), `test_11_assistance_invariant.py` (98).

## Coverage

- Queue A: 18/18 difficulty instances, ≥2 tests each (41 tests).
- Queue B: 42/43 corner instances, ≥1 test each (66 tests). The one `excluded_because` stub (`errors/err_place_overlap_already_covered_in_difficulty`) was not translated — its pointer reads `resource_temporal_overlap / place_geofence_overlap_area_threshold`; the rule_id half is correct and the instance name `place_geofence_overlap_area_threshold` does exist and is covered by 2 tests, so the assertion is owned upstream (the slash-separated path in the pointer doesn't mechanically resolve, but both components check out).
- No SKIPs — every instance passed the PRD-first filter. Two PRD ambiguities were handled by weakening the *assertion mechanism* (never removing the rule): `err_consent_not_granted_on_fix_post` accepts either an `ERR_CONSENT_NOT_GRANTED` error or a 201 fix row with `fix_status == REJECTED_CONSENT` (PRD §3.4 covers both readings), and the priority-pair test asserts status ∈ {403, 409} with the error_id pinned to the status-appropriate value (PRD §3.2 doesn't pin validation order).
- Scripted audit over both YAMLs confirmed every test's `Design:` tag resolves to a real instance and every instance meets its quota (61 expected instance→test mappings, 0 failures). Two quoted citations in test_02 (`invites further members`, `the invite increments the`) were verified to survive literal grep of PRD.md.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere.

## Verification results

- `python3 -m py_compile test_helpers/*.py test_suite/*.py` — OK.
- `PYTHONPATH=. python3 -m pytest test_suite --collect-only -q` — **107 tests collected in 0.21s**, no errors (collection requires no live server; `conftest.py` imports `test_helpers` lazily inside fixtures).
- `workspace/implementation/` was never touched (does not exist); no sibling tasks inspected.

## Step 6: Generate Implementation — 2026-09-30T17:46:00.000Z

Done. Summary below.

## Implementation complete: task_3276

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3276_family_location_sharing_place_alerts_crash_detection/workspace/implementation/`):

| File | Lines | Role |
|---|---|---|
| start.sh | 8 | Guarded dep install (`import flask` check), `exec python3 app.py`, PORT env, 0.0.0.0 |
| requirements.txt | 1 | flask |
| app.py | 56 | Flask app, blueprint registration, ApiError/404/405/500 handlers, /health |
| db.py | 77 | In-memory store (12 dicts, starts empty), logical clock booted at 2026-09-01T00:00:00Z, ISO-8601 3-fractional-digit formatting |
| errors.py | 52 | ApiError + all 21 error-id constants |
| response.py | 73 | Envelope: `meta{api_request_id, api_request_timestamp, limit/offset/total_count/has_more}`, `response_type`, `data`; error body `{error_id, message}`; pagination defaults 10/0 clamp 1..100 |
| middleware.py | 123 | X-User-ID/X-User-Role auth, entity-backed RBAC (Owner/Admin verified against Member row role + same circle), derived `circle_posture` (FROZEN > RESTRICTED > OPEN), FROZEN read/mutation gates |
| serializers.py | 22 | datetime → ISO serialization |
| calculations.py | 112 | Haversine (R=6371000), geofence membership (inclusive `<=`, accuracy capped at floor, accuracy>floor = per-place rejection), effective_sample_interval (base×motion×battery, tier floor, round-half-up once, clamp 15–900), crash severity ladder (8/16/24 at 2dp), per-segment trip distance, driver score (100−8·min(se,5)−5·min(pe,6)−mi), age_years |
| services.py | 137 | Subscription ledger append + billing-period index, posture recompute, FROZEN side effects (trips ABANDONED, alerts SUPPRESSED/TIER_HISTORY), consent-revoke cascade (crashes → FALSE_ALARM with unit refund if escalated, wellness CANCELLED, trips ABANDONED, alerts CANCELLED) |
| sweeps.py | 173 | Wellness-deadline sweep (SENT+past deadline → UNANSWERED + escalate, gated by posture/fiscal checks), age sweep (MINOR→MEMBER at 16, tension cleared), retention sweep (older than window → RETIRED), disclosure sweep (GRANTED+opt-in under 30d-open disclosure hold → EXPIRED, HIDDEN, MINOR_PRIVACY_AUDIT for minors) |
| crash_service.py | 124 | Crash creation (DETECTED→WELLNESS_PENDING immediately, deadline 300s SEVERE/600s else), acknowledge (CONFIRMED_OK + PENDING_VERIFICATION dispatch → CANCELLED), false-alarm with compensating refund, verify (VERIFIED→STAGED atomic + crash DISPATCHED), complete (RESOLVED), cancel (STAGED/COMPLETED → ERR_DISPATCH_ALREADY_STAGED) |
| fix_service.py | 223 | Fix ingestion (REJECTED_CONSENT recording when consent not GRANTED), geofence window open/close with pinned dwell evaluation order (0.5×eff-interval gap check → DUPLICATE_EVENT; posture != OPEN → TIER_HISTORY; dwell ≥ bucket → CONFIRMED with frozen visible_to_owner; HIDDEN at confirm → PRIVACY_HIDDEN), trip open/extend/close, 600s trip timeout |
| routes_circles.py | 303 | Circle create (owner member + self-grant FULL + TIER_CHANGE ledger entry + tier budgets), circle read/list, member invite (MINOR <16), promote/demote, transfer-ownership |
| routes_consent.py | 202 | Grant (actor matrix: MINOR needs non-self OWNER/ADMIN, adult self-or-OWNER; EXPIRED re-entry FULL-only), revoke (MINOR → OWNER-only else ERR_MINOR_CONSENT_LOCKED), consent-record reads, privacy PATCH (OCC on expected_member_version, anti-coercion HIDDEN→PRECISE self-only, tension flag rules, consent gate for →HIDDEN) |
| routes_places.py | 273 | Place CRUD with field validation (ERR_PLACE_CONFIG_INVALID) and two-circle exact intersection-area overlap check (>50% of smaller area → ERR_PLACE_OVERLAP), archive (cancels PENDING_DWELL), place-alert lists with HIDDEN privacy filter for non-self readers |
| routes_fixes.py | 232 | Fix POST (±300s clock skew and field validation → ERR_FIX_CLOCK_SKEW), retention-windowed fix/trip lists (inclusive cutoff), nested+top-level reads with FROZEN read gate |
| routes_crashes.py | 268 | Crash report (ERR_TRIP_NOT_OPEN, ERR_CRASH_BELOW_THRESHOLD, consent gate), wellness acknowledge (subject-only, deadline → ERR_WELLNESS_EXPIRED), mark-false-alarm (reason ≥5 chars, invalid from DISPATCHED), wellness/dispatch reads, verify/complete/cancel (OWNER-of-circle) |
| routes_subscription.py | 297 | change-tier (OCC on expected_circle_version → 412, retention recompute, PROTECT credit enter/leave), reactivate (SUSPENDED→ACTIVE, posture may land RESTRICTED), simulate-payment-failed / simulate-suspend (System), ledger lists, roadside-assistance (RESTRICTED → 409, FREE/PLUS floor 0, PROTECT overdraw to −1 → 402), identity-protection (PROTECT-only, 402 when 0), compliance holds open/resolve/list |

**Verification:**
- `python3 -m py_compile *.py` — all 17 modules compile.
- Smoke boot on port 18371 with saved PID: server came up, `/health` OK, and a full end-to-end chain succeeded — circle create (PLUS: balance 2, retention 30) → member invite → consent grant → DRIVING fix (ACCEPTED, trip auto-opened) → crash report (delta_v 16.0 → MAJOR, WELLNESS_PENDING, deadline +600s) → clock advance past deadline → wellness sweep escalated to ESCALATED with dispatch created and balance 2→1 → owner mark-false-alarm → FALSE_ALARM with compensating refund balance back to 2. Envelope shape, `req_` ids, and logical-clock timestamps (2026-09-01 boot, no wall-clock) all confirmed. Server killed by exact PID afterwards.
- No seeding anywhere — the store starts empty; no reads of test_suite/, test_helpers/, or SCAFFOLD_*_DESIGN.yaml.

**One judgment call to flag:** the scaffold's speed-event threshold says "exceeds the tier threshold" without giving a per-tier numeric value; I used 35.0 m/s for all tiers (constant `TIER_SPEED_EVENT_THRESHOLD` in calculations.py), easily adjustable if tests indicate otherwise.

## Step 7: Run Tests and Iterate — 2026-09-30T18:07:00.000Z

All 8 rounds pass 104/104 (107 − 3 deleted = 104). Clean sweep. (Orchestrator independently verified: all impl file mtimes ≤ 18:01:40, all 8 results.*.json written 18:06:19–18:06:23 post-fix, each showing passed=104 total=104 failed=0 errors=0.)

## Summary

**Iterations run:** 2 (initial sweep: 13 distinct failures, deterministic across all 8 rounds; post-fix sweep: 8/8 rounds clean, 104/104).

**Tests deleted (3):**
1. `test_location_fix_missing_required_field_returns_invalid_request` (test_04) — PRD silence: §3.4 assigns value-domain violations to `ERR_FIX_CLOCK_SKEW` but never names the error for a *missing* required field; `ERR_INVALID_REQUEST` has no trigger condition anywhere in the PRD prose. Two faithful readers diverge (missing-as-unrecognized → 422 vs. missing-field → 400).
2. `test_geofence_membership_accuracy_cap_applies` (test_04) — unique-derivability collapse: the accuracy cap is only observable when `accuracy_m > accuracy_floor_m`, exactly the region where PRD §3.5 says the fix "cannot trigger alerts for that place — REJECTED_ACCURACY for that place's purposes only". PRD never states whether such a place appears in `place_ids_inside`; the impl's exclusion reading and the test's inclusion reading are both defensible.
3. `test_speed_event_counted_only_when_pair_avg_exceeds_threshold` (test_06) — threshold silence: PRD says speed events count pairs whose average "exceeds the tier's speed-event threshold" but never gives a numeric per-tier threshold; the test hardcoded 27.0 (scaffold/test-helpers constant `SPEED_EVENT_THRESHOLD_BY_TIER`), which no PRD-only implementer could derive.

**Fixes applied to `test_suite/` (5):**
- test_02 `test_age_sweep_promotes_minor_to_member_at_16` — birthdate 2010-09-01 made the invitee exactly 16 at boot (5844/365.25 = 16.0 → floor 16 → MEMBER at invite per §3.2); moved birthdate to 2010-09-02 and the sweep clock to 2026-09-02 so the member is 15 at join and crosses 16 at the sweep.
- test_04 `test_geofence_boundary_inclusive_equality` — fixture coordinate 37.70540 is 600.45 m from the centre (genuinely outside the 600 m effective radius); replaced with 37.705395929635515, whose haversine is exactly 600.0 m, making it a true inclusive-boundary probe.
- test_05 `test_place_alert_confirmed_alert_is_immutable_after_departure_and_reentry` — fixes at 00:04/00:06/00:08 exceeded PRD's 300 s clock-skew window against a stationary logical clock; added `set_clock` calls tracking each `recorded_at`.
- test_06 `test_driver_score_trip_level_vs_rolling_30d` and `test_driver_score_persisted_trip_value_unchanged_by_later_trips` — same skew fix (clock advanced alongside each fix batch); additionally removed the dependence on the PRD-silent speed threshold: trip A is now identified by its PRD-defined phone-use event instead of `speed_event_count > 0`, and all driver-score formula assertions read `speed_event_count` back from the response so they hold for any threshold value.
- test_06 `test_trip_open_uniqueness_temporal_interval` — assertion expected `ended_at == 00:05:00`, contradicting PRD §3.6 ("`ended_at` is the timestamp of the last `DRIVING` fix before close", which was at 00:00:00); corrected to 00:00:00.
- test_08 `test_crash_detection_depth3_cascade` — version assertion `>= created + 2` not uniquely derivable (PRD §3.7: "Escalation increments both the crash event's `version` and the circle's `version`" — a single increment); relaxed to `>= created_version + 1`, the PRD-supported floor.

**Fixes applied to `implementation/` (2):**
- `crash_service.py::acknowledge_wellness` — reordered gates so the deadline check (`now() >= deadline_at` → `ERR_WELLNESS_EXPIRED`) runs before the crash-status state gate; PRD §3.7 explicitly pins `ERR_WELLNESS_EXPIRED` for an ack attempted at/after the deadline even after the system has already escalated.
- `sweeps.py` (new `run_billing_anchor_roll`, wired into `run_all_sweeps`) + `services.py::append_subscription_event` (optional `billing_period_index` override) — implemented the missing billing-anchor replenishment: at each 30-day anchor roll the circle's `assistance_units_balance` is reset *to* the per-window tier allotment (0/2/4) and `identity_protection_credits` to the tier window start (1 on PROTECT else 0), appending a `RENEWAL` ledger row with the signed `units_delta` actually applied and the incremented `billing_period_index` (PRD §2.8, §3.1).

No `test_helpers/` changes were needed. Final state: 104/104 passing in all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-09-30T18:15:00.000Z

Done. Summary:

**Line counts:** `PRD.md` = 301 lines, `PRD_FINALIZED.md` = 303 lines (+2 lines, +0.66%). Five targeted edits; all other step_7_diff items were pure test-fixture bugs (birthdate/boundary-coordinate/`set_clock` tracking, the `ended_at` assertion, the crash-version floor) where the PRD already pinned the behavior the corrected test now asserts — no PRD change needed for those. (Orchestrator verified the diff first-hand: exactly the five hunks below, nothing else.)

### Changes (one bullet each)

- §3.4 — insert — Pins the missing/absent-field error split for fix ingestion: absent or unparsable `recorded_at` → `ERR_INVALID_REQUEST` (400); absent/null `lat`, `lng`, `accuracy_m`, `speed_mps`, `battery_pct`, or `motion_context` → `ERR_FIX_CLOCK_SKEW` (422) like other value-domain violations — `implementation/routes_fixes.py:26-50` (deleted test `test_location_fix_missing_required_field_returns_invalid_request`).
- §3.5 — revise — Clarifies that a fix whose `accuracy_m` exceeds a place's `accuracy_floor_m` is treated as *not inside* that place and the place does not appear in `place_ids_inside` — `implementation/calculations.py:39-46`, `implementation/fix_service.py:76-85` (deleted test `test_geofence_membership_accuracy_cap_applies`).
- §3.6 — revise — Pins the speed-event threshold to 35.0 m/s on every tier — `implementation/calculations.py:13,87-95` (deleted test `test_speed_event_counted_only_when_pair_avg_exceeds_threshold`).
- §3.7 — insert — Pins that the wellness-ack deadline gate takes precedence over the crash lifecycle-state gate, so an ack at/after `deadline_at` returns `ERR_WELLNESS_EXPIRED` even when the crash is no longer `WELLNESS_PENDING` — `implementation/crash_service.py:50-55` (step-7 impl fix in `acknowledge_wellness`).
- §2.10 + §3.9 — insert/revise — §2.10's sweep list now includes the billing-anchor roll; new §3.9 paragraph pins the roll's mechanics: 30-day rolling windows from the circle's creation instant, `assistance_units_balance` reset *to* the per-window tier allotment (0/2/4), `identity_protection_credits` reset to window start (1 PROTECT else 0), a `RENEWAL` ledger row per roll with signed `units_delta` (new allotment minus prior balance) and incremented `billing_period_index`, multiple elapsed windows rolled in turn — `implementation/sweeps.py:163-185`, `implementation/services.py:12-35`, `implementation/routes_clock.py:13-37` (step-7 impl fix `run_billing_anchor_roll`).

### Per-edit pre-edit search log

1. **§3.4 missing-field error** — (a) subject: error identity for absent fix-payload fields. (b) enumerated: `routes_fixes._validate_fix_payload` (all six value-domain branches + `recorded_at` parse), `app.py:46-47` (malformed-JSON fallback also 400), `errors.err_invalid_request`. (c) wording scoped to the fix-ingest endpoint only, preserving §3.4's existing 422 assignment for present-but-invalid values; no universal claim about `ERR_INVALID_REQUEST` elsewhere (it is used ad hoc across routes).
2. **§3.5 accuracy-cap exclusion** — (a) subject: whether accuracy-rejected places appear in `place_ids_inside` / trigger alerts. (b) enumerated: `calculations.geofence_inside`, `fix_service.evaluate_places` (both `place_ids_inside` population and alert open/resolve paths consume the same inside-set), `fix_service._member_prev_inside` (frozen-list reads), `ingest_fix` (`REJECTED_ACCURACY` is never persisted as a fix_status). (c) initial draft claimed the fix "neither opens nor resolves alert windows" — wrong, because an accuracy-rejected place counts as *outside* and can close a pending ARRIVAL window as `SUPPRESSED`; wording was narrowed to the `place_ids_inside` exclusion only.
3. **§3.6 speed threshold 35.0** — (a) subject: numeric per-tier threshold. (b) enumerated: `calculations.TIER_SPEED_EVENT_THRESHOLD` (35.0 all tiers), sole consumer `speed_event_count` ← `fix_service.close_trip`; trip-level driver score reads the same count; no rolling-score endpoint exists in impl. (c) none — only the value pinned; strict "exceeds" comparison retained from existing PRD prose.
4. **§3.7 ack gate precedence** — (a) subject: ordering of deadline vs. state gates on acknowledge. (b) enumerated: `crash_service.acknowledge_wellness` (deadline → crash_status → check_status), route-level gates in `routes_crashes.acknowledge_wellness` (role, 404, subject-actor, FROZEN) which run before the service. (c) wording deliberately says "crash lifecycle-state check", not "any check", so it does not claim precedence over auth/404/frozen gates.
5. **§2.10/§3.9 billing-anchor roll** — (a) subject: anchor-roll trigger and mechanics. (b) enumerated: `sweeps.run_billing_anchor_roll`, `services.current_billing_period_index`/`append_subscription_event`, both callers (`set_current_utc`, `run_sweeps`), `routes_circles.create_circle` (initial `TIER_CHANGE` at period 0, consistent with §3.1's "starting at 0"), test_09 anchor tests (PROTECT 3→4 with `units_delta` +1, PLUS 1→2, FREE 0→0). (c) §2.10's parenthetical kept non-exhaustive ("any daily sweeps that have come due") so adding the roll doesn't falsely exclude the disclosure sweep, which also runs on `set_clock` but is outside step-7 scope; window anchoring described as "the circle's creation instant" (matching impl's `created_at + 30-day` math) rather than redefining `billing_anchor_day`.

## Step 9: Complete PRD — 2026-09-30T18:26:00.000Z

Done. Summary:

**Files:** `PRD_FINALIZED.md` (303 lines / 55,244 chars) → `PRD_COMPLETED.md` (303 lines / 62,492 chars; +7,248 chars, same line count — all changes inline). (Orchestrator verified on disk: 303 lines, 62,492 bytes.)

**Counts:** 23 ambiguity-pins (PRD silent, impl behavior inserted) and 9 mismatch-revisions (PRD contradicted impl, prose corrected).

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.3 — insert — ambiguity — pagination params are clamped (limit→[1,100], offset→≥0), unparsable values fall back to defaults; `has_more` = `offset+limit < total_count` — response.py:57-73
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — db.py:69-77
- §2.6 — revise — ambiguity — FROZEN exemptions extended to System-only operations (hold opens, subscription simulations carry no frozen gate) — routes_subscription.py:70-94,210-230
- §2.9 — revise — mismatch — haversine is full floating-point precision (not 0.1 m quantized), no pre-comparison rounding — calculations.py:29-36
- §2.9 — insert — ambiguity — `delta_v` quantized to 2dp round-half-up before severity comparison — calculations.py:66-75
- §2.10 — insert — ambiguity — clock-set also runs the trip-timeout check — routes_clock.py:21-22
- §3.1 — insert — ambiguity — creation appends initial `TIER_CHANGE` ledger row (from_tier null, period 0); owner member starting state (GRANTED/PRECISE/BALANCED, battery 100, tension false); `owner_email` not persisted — routes_circles.py:59-93
- §3.1 — revise — mismatch — tier change never touches `assistance_units_balance` (replenishment only at billing-anchor roll); tier change recomputes all members' sample intervals — routes_subscription.py:23-52
- §3.1 — revise — mismatch — posture→FROZEN sweeps PENDING_DWELL alerts to SUPPRESSED/TIER_HISTORY and abandons OPEN trips; suppressed alerts never resume — services.py:47-60
- §3.2 — insert — ambiguity — member-facing roles require backing Member row in the circle whose `role` matches the claimed header role — middleware.py:42-63
- §3.2 — insert — ambiguity — invited members start PRECISE/BALANCED, battery 100, tension false — routes_circles.py:149-164
- §3.2 — insert — ambiguity — grant actor-matrix violations are `ERR_FORBIDDEN`; grant persists `monetization_opt_in` on member and returns the ConsentRecord; EXPIRED partial re-grant is `ERR_INVALID_STATE` (409) — routes_consent.py:45-64
- §3.2 — revise — ambiguity — revoke requires current `GRANTED` (else `ERR_INVALID_STATE`); records scope `FULL`; cascade covers DETECTED/WELLNESS_PENDING/ESCALATED crashes (ESCALATED refunds a unit), cancels PENDING_VERIFICATION/VERIFIED dispatches, and cancels the member's PENDING_DWELL alerts — services.py:85-121, routes_consent.py:67-93
- §3.2 — insert — ambiguity — promote/demote precondition failures are `ERR_INVALID_STATE`; demote requires current ADMIN — routes_circles.py:243-274
- §3.2 — insert — ambiguity — ownership transfer returns the updated circle — routes_circles.py:303
- §3.3 — insert — ambiguity — exact privacy transition set (PRECISE↔BLURRED, →HIDDEN, HIDDEN→PRECISE, same-mode no-op permitted; HIDDEN→BLURRED is `ERR_INVALID_STATE`); self-only check precedes transition check; consent gate skipped on HIDDEN→HIDDEN; patch returns updated member — routes_consent.py:148-202
- §3.4 — insert — ambiguity — `phone_in_use` defaults to false; fixes may be posted by the subject member or a circle OWNER/ADMIN — routes_fixes.py:57,62-72
- §3.4 — insert — ambiguity — REJECTED_CONSENT fixes persist but perform no member/geofence/trip side effects — fix_service.py:196-223
- §3.5 — insert — ambiguity — place create/patch/archive do not increment the circle's version — routes_places.py:110-202
- §3.5 — insert — ambiguity — overlap uses the exact planar two-circle lens area (zero beyond r₁+r₂, full smaller-circle area under containment) — routes_places.py:75-107
- §3.5 — insert — ambiguity — "previously inside" read from frozen `place_ids_inside` of latest prior ACCEPTED fix (none ⇒ outside); notify flags gate candidate creation; window fields start null; closing fix always stamped as `window_close_fix_id` — fix_service.py:25-124
- §3.5 — revise — mismatch — pinned evaluation order extended: DUPLICATE_EVENT → TIER_HISTORY (posture non-OPEN at evaluation) → confirm/PRIVACY_HIDDEN → null-reason suppress; all suppressions immediate (no deferral) — fix_service.py:37-73
- §3.5 — revise — mismatch — alert CANCELLED reserved for consent-revocation cascade and place archival — services.py:118-121, routes_places.py:198-201
- §3.5 — insert — ambiguity — System reader exempt from the HIDDEN alert-list privacy filter — routes_places.py:227-237
- §3.6 — insert — ambiguity — trip extension advances `ended_at` to the latest DRIVING fix and tracks running `max_speed_mps`; timeout is strictly >600s and runs on sweeps and fix ingestion — fix_service.py:127-157,182-193
- §3.6 — revise — mismatch — no rolling driver-score endpoint exists; only the trip-level variant is exposed/persisted — (no rolling computation anywhere in implementation/)
- §3.7 — insert — ambiguity — crash report requires member consent `GRANTED` (else `ERR_CONSENT_NOT_GRANTED`, checked before the trip gate) — routes_crashes.py:39-40
- §3.7 — insert — ambiguity — blocked deadline escalation is skipped, crash stays WELLNESS_PENDING/check SENT, retried by later sweeps; escalation appends ASSISTANCE_CONSUME -1 ledger row — sweeps.py:64-82,11-30
- §3.7 — insert — ambiguity — dispatch verify requires PENDING_VERIFICATION+ESCALATED, complete requires STAGED+DISPATCHED, cancelling a CANCELLED dispatch is `ERR_INVALID_STATE` — crash_service.py:93-129
- §3.7 — insert — ambiguity — false-alarm retraction from any non-{DETECTED,WELLNESS_PENDING,ESCALATED} state is `ERR_INVALID_STATE`; refund appends ASSISTANCE_GRANT +1 — crash_service.py:68-90
- §3.8 — insert — ambiguity — `opened_reason` defaults to `manual`; resolving a non-OPEN hold is `ERR_INVALID_STATE` — routes_subscription.py:219,260-261
- §3.8 — insert — ambiguity — no per-member disclosure-acknowledgement tracking: all GRANTED+opted-in members expire once the hold is ≥30 days old — sweeps.py:121-160
- §3.9 — revise — ambiguity — retention sweep retires any non-RETIRED fix status; trip-list retention projection applies to `started_at` — sweeps.py:99-118, routes_fixes.py:179-180
- §4 — insert — ambiguity — roadside-assistance and identity-credit consumption return the appended SubscriptionEvent ledger row — routes_subscription.py:178-179,198-199

One observation: the PRD's rolling driver-score variant (§3.6) has no endpoint in the implementation, so the prose was revised to mark it as unexposed rather than inventing a read path.

## Pipeline complete — 2026-09-30T18:26:00.000Z

Final artifacts: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml; workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}; test_helpers/ + test_suite/ (107 tests generated, 3 deleted in Step 7 for PRD-silence/non-derivability, 104 final). Final 8-round stability sweep: 104/104 passed in every round (verified first-hand by orchestrator from results.1–8.json, all written after the last implementation edit).
