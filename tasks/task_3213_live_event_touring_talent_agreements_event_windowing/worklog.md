# Worklog — task_3213_live_event_touring_talent_agreements_event_windowing

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Pre-allocated task directory `./tasks/task_3213_live_event_touring_talent_agreements_event_windowing/` verified to exist with `workspace/` inside (per command args; no new index computed).

## Step 2: Generate scaffold — 2026-09-30T11:18:00.000Z

All three scaffold artifacts are generated and lint-clean for task_3213.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_3213_live_event_touring_talent_agreements_event_windowing/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3213_live_event_touring_talent_agreements_event_windowing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key, 18 instances (2 per rule)
- `/home/ubuntu/github/CodingPRD/tasks/task_3213_live_event_touring_talent_agreements_event_windowing/SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key, 46 instances across all 9 claim-extraction sections

**Design highlights (maximized difficulty)**
- 18 entities, 73 endpoints, 25 error codes, 8 calculations, 9 state machines, 24 ordered validations, 8 roles — past the Expert band ceilings
- Complexity profile: `temporal_windowing` + `compliance_audit`, layers OCC / cascading side effects / dual-variant calc / rate-threshold; `segregation_of_duties` role model (Medic evaluator ≠ clearer), flat topology
- Rule coverage: dual-variant royalty (PROVISIONAL vs FINAL event-state filter, computed literals 20000/0) + forward-looking appearance shortfall (shortfall 2); combinatorial tiered day-gross royalty (mode a) + circular call-up readiness (mode c, score 42 = 3×4 + round(59×0.5)); cyclic Storyline shelve/revive + branching Booking FULFILLED→NO_SHOW (net −11.00); depth-3 medical cascade and depth-2+ event-cancel cascade; priority conflicts state-vs-constraint and safety-vs-referential; boundary checks on booking-mode bands and 2-evaluator clearance quorum; cross-entity gates Event→Booking and DistributionWindow→TerritoryRight; arena whole-day vs half-open territory-right overlap semantics; compensating invariants on wellness (50→53→42) and consecutive gap_count conservation
- Logical clock endpoint with the mandated `2026-09-01T00:00:00Z` startup default; OCC on agreement activation and event lock (412 `ERR_STALE_VERSION`, `${var}`-only version payloads)

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (520 calls scanned, 0 violations)

One design note: §1.4's ordering deliberately places the domain-specific overlap check (priority 10) above the generic shape check (priority 24), which is pinned and exercised by corner instance `agreement_overlap_beats_generic_field_validation`.

## Step 3: Copy shared files — 2026-09-30T11:18:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3213_live_event_touring_talent_agreements_event_windowing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T11:26:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_3213_live_event_touring_talent_agreements_event_windowing/workspace/PRD.md` (~70 endpoints, 16 entities, all 25 error codes). The two difficulty-design files were not touched.

**Structure.** §1 introduction (two paragraphs from the touring-calendar angle); §2 with 9 subsections — roles/RBAC with opaque-identity prose for all 8 roles, verbatim §2.2 envelope block, pagination, the logical clock (startup default `2026-09-01T00:00:00Z`, Monday 00:00Z decay sweep, agreement expiry sweep), common resource properties (with the MerchSale `common_fields: false` exception called out explicitly), OCC (only `expected_agreement_version` on activate and `expected_event_version` on lock, both `ERR_STALE_VERSION`/412), validation-ordering cascade (auth → role → path ids left-to-right → body FKs → state → event-mutability → business rules → malformed-payload last), money/precision (integer cents, basis points, per-line round-half-up, wellness 2dp clamped 0.00–100.00), and nested path validation. §3 has 12 subsections organized by workflow (roster/wellness, agreements/likeness, calendar, bookings/storylines/chapters, event run, wellness accrual, distribution, merch/royalties, appearance compliance, medical, visas, call-ups). §4 is a 4-column table covering all 69 endpoints; §5 is a 2-column table covering all 25 error ids.

**Hard contract reports:**

```
Field coverage check:
- entities[].fields + endpoints[].input: 76 required, 76 present, 0 missing
- endpoints[].query_params: limit/offset and filter params present in §2.3 and §4 context, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: expressed as the ordered §2.7 cascade, all 24 rules named with error ids across §2/§3
- concurrency_rules[] OCC: 2 checked, 2 expressed (write op + expected_*_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all 10 machines, every from/to pair, preconditions, and side-effect cascade expressed (agreement terminate 2-hop cascade, event complete/cancel sweeps, no-show net -11.00, gap_count shelf/revive, medical open scratch horizon of 30 days, visa deny cascade)
- calculations[]: 7/7 expressed in prose with constants embedded (250,000¢/100,000¢ tiers, +200/−100 bp, 70.00/40.00 wellness bounds, +3.00/−8.00/−1.00 deltas, 30-min LIVE pre-open, 24-hour REPLAY delay, 90-day/×4/×10/×0.5/60 call-up score, gap threshold 3); half-open interval and touching-window semantics stated for both territory rights and distribution windows
- validations[] conditions: all matchable to error_id in §2/§3 prose
- endpoints[].side_effects: expressed in workflow narratives
- entities[].fields[] structured content: defaults/initials (DEVELOPMENTAL tier, 0.00 wellness, UNBOOKABLE start, gap_count 0, clearance_id null) and sources stated
- sibling-branch symmetry: PROVISIONAL vs FINAL royalty variants, LIVE vs REPLAY windows, exclusive vs non-exclusive rights, PROMOTE vs DEFER — each branch specified with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 423
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 verified byte-identical to `section-2.2-response-structure.md` (including `req_RANDOMALPHANUM123456` and the empty `"data": { }`). No pseudocode or operator syntax in prose; all thresholds translated to natural language with exact boundary inclusivity.

## Step 5: Generate unit tests — 2026-09-30T11:55:00.000Z

Complete. Summary of what was generated and the key findings.

**`test_helpers/`** (9 files) under `/home/ubuntu/github/CodingPRD/tasks/task_3213_live_event_touring_talent_agreements_event_windowing/`:
- `types.py` — 18 entity TypedDicts + status enums; `MerchSale` correctly omits `updated_at`/`version` (common_fields: false)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (48 endpoints)
- `api_errors.py` — all 25 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions; `assert_merch_sale` explicitly asserts absence of `updated_at`/`version`
- `factories.py`, `constants.py` (thresholds: wellness bands 40/70, tier gates 100000/250000, ±200/−100bp, gap shelf 3, LIVE 30min / REPLAY 24h, injury horizon 30d, promote 60), `test_users.py` (8 opaque role headers + per-medic builder), `fixtures.py` (composite helpers: draft/activate agreement with OCC, lock/complete/cancel, storyline+chapter activation, shelved storyline, premium-event-with-spanning-right, medical quorum/clearance, visa lifecycle, clock advance), `__init__.py` barrel.

**`test_suite/`** — `conftest.py` + 9 test files, **81 tests collected cleanly** (pyflakes-clean, imports verified).

## Key finding driving the suite

The PRD (§3.1) pins fresh talent wellness at **0.00 / UNBOOKABLE** and (§3.6) raises wellness **only** via fulfilled bookings — which require a booking an UNBOOKABLE talent can never get. The scaffold's design indices assume 50.00/LIMITED. Per the PRD-first two-condition filter this made 4 difficulty instances unassertable (both royalty tier-gate instances needing LOCKED/COMPLETED merch day-gross, and both no-show wellness instances needing a FULFILLED booking) — they were skipped rather than weakened. Reachable adjacents were preserved: e.g. merch tier0/base-tier arithmetic on SCHEDULED events (no booking required), cancel cascades on chapters/windows (booking hop vacuous), clearance quorum/segregation, OCC 412s, half-open interval rules, anchor-day match, RBAC matrix, visa lifecycle, appearance-compliance floor saturation, and the locked-vs-completed event guards.

## Verification

- Every test's docstring ends with exactly one `Design:` tag resolving to a real non-stub instance (no `excluded_because` stubs exist in queue B).
- Coverage: all 17 PRD-reachable difficulty instances ≥2 tests; all 44 non-stub corner instances ≥1 test; 4 difficulty instances skipped as gaps (documented above).
- Every `PRD §x.y: "..."` citation survives a literal grep of `workspace/PRD.md` (0 verbatim failures, short quotes checked whole).

## Step 6: Generate implementation — 2026-09-30T12:00:00.000Z

Done. Generated a complete Python + Flask implementation for task_3213.

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3213_live_event_touring_talent_agreements_event_windowing/workspace/implementation/`):
- `app.py` (~1170 lines of application code) — single-file Flask app with in-memory store, all 55 endpoints from the scaffold endpoint table
- `start.sh` — executable launcher; guarded `pip install` (no-op once Flask is present), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`

**Key implementation decisions, all traced to PRD/SCAFFOLD:**
- Envelope: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; pagination fields `limit/offset/total_count/has_more` inside `meta` (list endpoints only); error body `data.{error_id,message}`
- Auth: `X-User-ID` + `X-User-Role` headers, 8 exact role names, RBAC matrix per §4 table; auth → forbidden → path 404 (left-to-right) → body FK 404 (`ERR_REFERENCE_NOT_FOUND`) → state 409 → business 422/400 ordering
- Logical clock pinned at `2026-09-01T00:00:00Z`; `POST /touring/_clock/set_current_utc` runs Monday-boundary wellness decay (MAIN_ROSTER only, −1.00 per crossing, floor 0) and ACTIVE→EXPIRED agreement sweep with likeness recompute
- OCC only on agreement activate (`expected_agreement_version`) and event lock (`expected_event_version`), checked after state, before business rules → `ERR_STALE_VERSION` 412
- Wellness clamped 0–100 at 2dp; booking_mode derivation strictly ordered (SUSPENDED/INJURED/open-case → UNBOOKABLE, ≥70 BOOKABLE, ≥40 LIMITED, inclusive bounds)
- Royalty: per-line round-half-up integer cents at MerchSale creation using event-day gross tiers (250000/100000 thresholds, +200/−100 bp); statement totals sum the lines' stored `royalty_cents` (immutable ledger), variants filter LOCKED+COMPLETED (PROVISIONAL) vs COMPLETED-only (FINAL); `event_id` denormalized pointer null when spanning multiple events
- Distribution windows: UTC-naive event instants, LIVE ≥ start−30min, REPLAY ≥ end+24h, half-open non-overlap per partner+territory+event (REVOKED excluded); licensing pinned at creation, not re-checked at publish
- Cascades: terminate agreement → forward scratch + ACTIVE-storyline auto-conclude; event cancel → scratch + chapter miss + gap increments + shelving sweep (no further increments) + window revoke; medical case creation → INJURED + 30-day scratch horizon; visa deny → country/date-scoped scratch
- MerchSale immutable: no `updated_at`/`version` fields
- No seeding — store starts empty on every boot, safe for `--isolation per-test-server`

**Verification:** ran four smoke suites against fresh server boots (each on a private port, killed by exact PID afterwards) covering auth/RBAC, envelope shape, pagination defaults/bounds, agreement lifecycle + OCC + overlap + terminate cascade, anchor day-match, arena date conflict, storyline gap/shelve/revive/conclude, territory-right exclusivity and adjacency, window timing/overlap/publish/revoke, merch gating and tiered royalty math (including the 3330×900bp → 300 round-half-up case), statement variants/finalize guards, visa windows, medical segregation-of-duties, clock sweeps, and appearance-compliance output. All passed. The test suite itself was not run, per the isolation rule.

## Step 7: Run tests and iterate — 2026-09-30T12:30:00.000Z

All 8 rounds pass 81/81. Clean sweep achieved.

**Iterations run:** 2 (round 1: 5 deterministic failures across all 8 rounds, no flakiness; round 2: 1 residual failure exposed by the timezone fix; final sweep: 81/81 × 8 rounds).

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `test_04_storylines.py::test_chapter_index_follows_event_date_not_creation_order` — the test asserted `chapter_index == 2` on the *first* creation's response, but PRD §3.4 assigns the index as the chapter's position among existing chapters at that moment (1 when it was the only chapter). Fixed to re-read via `list_storyline_chapters` after both creations before asserting the date-ordered indices.
- `test_06_distribution.py::test_uncovered_window_dates_rejected_then_spanning_right_accepted` — payload used UTC-naive window instants (`opens_at=2026-09-20T19:30:00Z`) that violate the PRD §3.7 LIVE 30-minute pre-open floor once the event's local times are correctly converted through the arena's America/New_York timezone. Fixed the payload to the timezone-correct floor (`23:30:00Z` open / `2026-09-21T04:00:00Z` close); the licensing assertion is unchanged.
- `test_08_compliance_visas_callups.py::test_submitted_visa_insufficient_grant_unblocks` — ERROR-PRECEDENCE collapse: a fresh talent is permanently UNBOOKABLE under PRD §3.1/§3.6, and §3.4's booking battery names the booking-mode check ahead of the visa check, so `ERR_VISA_REQUIRED` is not the uniquely derivable rejection. Relaxed the first assertion to `validate_error_is_one_of([ERR_VISA_REQUIRED, ERR_TALENT_UNBOOKABLE])` per the permitted coverage correction; the post-grant assertion (not ERR_VISA_REQUIRED) already matched PRD.

**Fixes applied to `implementation/`:**
- `app.py::create_agreement` — reordered validation to match the PRD §2.7 cascade: the domain-specific `ERR_AGREEMENT_OVERLAP` check now runs before the generic end-before-start/shape checks (previously `ERR_INVALID_REQUEST` short-circuited first, inverting the mandated order).
- `app.py::_event_start_end_utc` — event `event_date`/`start_time`/`end_time` are in the host arena's local calendar (PRD §3.3), so start/end instants in UTC are now derived via `zoneinfo.ZoneInfo(arena.timezone)` instead of being pinned to UTC. This is what the PRD §3.7 LIVE/REPLAY window timing rules mean by "the event's start/end instant in UTC".

## Step 8: Finalize PRD — 2026-09-30T12:40:00.000Z

**Line counts:** PRD.md 299 lines, PRD_FINALIZED.md 299 lines (0% delta — both edits are inline sentence insertions within existing paragraphs; character-level diff is 2 changed lines).

**Changes (2 edits):**
- §3.4 — insert — pinned the booking-creation check battery as ordered (event mutability → booking-mode eligibility → visa coverage → double-booking conflict, earliest failing check wins) — `implementation/app.py:1107-1150` (`create_booking`).
- §3.7 — insert — pinned that the event's start/end instant in UTC is derived by interpreting the local `event_date`/`start_time`/`end_time` through the host arena's IANA `timezone` — `implementation/app.py:1419-1434` (`_event_start_end_utc`).

**Step 7 diff items not edited, with reasons:**
- `test_04_storylines.py` chapter-index fix: pure test-fixture bug; PRD §3.4 already pins date-ordered `chapter_index`, and impl `recompute_chapter_indexes` (app.py:405-418) matches PRD.
- `test_06_distribution.py` payload fix: downstream fixture correction of the timezone impl fix; covered by the §3.7 edit.
- `app.py::create_agreement` reorder: the impl was changed to match PRD §2.7, which already places domain rules (agreement overlap) ahead of generic end-before-start/shape checks ("caught last as ERR_INVALID_REQUEST"). PRD already determines this; verbatim prose kept.

**Per-edit pre-edit search log:**

*Edit 1 (§3.4 battery order):*
- (a) Subject: error precedence among booking-creation business checks.
- (b) Paths enumerated/read: `create_booking` (app.py:1098-1159) — the sole site enforcing booking-mode/visa/double-booked; verified check order UNBOOKABLE → VISA_REQUIRED → DOUBLE_BOOKED; cross-checked §2.7 (already places `ERR_EVENT_NOT_MUTABLE` before domain rules) and §3.11 visa-grant semantics (no conflict). Scratch/cascade paths (`scratch_booking`, medical/visa cascades) do not run this battery, so no wording conflict.
- (c) No adjustment needed after enumeration; wording deliberately scopes the ordering claim to booking creation only.

*Edit 2 (§3.7 UTC derivation):*
- (a) Subject: how an event's start/end instant in UTC is derived.
- (b) Paths enumerated/read: `_event_start_end_utc` (app.py:1419-1434) is the only local→UTC instant conversion; its sole callers are `_check_window_timing` (1437) used by window create (1503) and publish (1548). Verified no other impl path converts event local times to UTC: double-booking compares local `HH:MM` directly (1136-1148), no-show same-day compares dates only, merch gating uses event status. Wording therefore covers all consumers of the conversion.
- (c) Wording written to describe the conversion rule once, applicable to both create and publish, without asserting anything about date-granularity comparisons elsewhere.

## Step 9: Complete PRD scan — 2026-09-30T13:00:00.000Z

**Source:** `workspace/PRD_FINALIZED.md` (299 lines / 46,795 chars) → **Produced:** `workspace/PRD_COMPLETED.md` (299 lines / 52,656 chars; Δ +5,861 chars, 0 net line change — all pins inline).

**Counts:** 31 ambiguity-pins, 7 mismatch-revisions (38 edited passages total).

Changes, one per bullet:

- §2.3 — insert — ambiguity — pinned invalid limit/offset → ERR_INVALID_REQUEST(400), `id`-ascending tie-break after `created_at`, `has_more ≡ offset+limit < total_count`, and the exact per-endpoint filter sets — app.py:292-318 plus each list handler's filter tuple.
- §2.4 — insert — ambiguity — clock may move backward (no monotonicity), naive `to_iso8601` read as UTC, `current_utc` response omits fractional seconds when zero — app.py:426-431, 203-215, 472-477.
- §2.5 — insert — ambiguity — `created_at`/`updated_at` stamped from wall clock, logical clock governs business rules only — app.py:92-95, 262-273.
- §2.6 — revise — mismatch — `expected_agreement_version`/`expected_event_version` are optional (absent/null skips the check); non-integer → 400; state check precedes version check; version fields elsewhere silently ignored — app.py:817-822, 1014-1019.
- §2.7 — insert — ambiguity — carve-out noting some endpoints interpose field-shape checks before specific business rules (exceptions pinned inline) — multiple handlers.
- §3.1 — insert — ambiguity — new talent's `likeness_granted` starts false — app.py:500.
- §3.1 — revise — mismatch — suspend `reason` is accepted but not persisted — app.py:522-531 (no reason handling).
- §3.1 — insert — ambiguity — suspend-when-SUSPENDED / reinstate-when-not-SUSPENDED → ERR_INVALID_STATE(409) — app.py:526-527, 538-539.
- §3.2 — insert — ambiguity — EXPIRED/TERMINATED agreements ignored by overlap rule; creation checks overlap before window shape — app.py:707-709, 734-737.
- §3.2 — insert — ambiguity — editing non-DRAFT agreement → ERR_INVALID_STATE(409); edit validates window/field shapes before overlap re-check — app.py:781-803.
- §3.2 — insert — ambiguity — activation evaluates OCC guard before overlap re-check — app.py:817-825.
- §3.3 — insert — ambiguity — `country_code`/`timezone` validated only as strings, not against ISO/IANA databases — app.py:878-880.
- §3.3 — insert — ambiguity — `anchor_id` on non-TELEVISION events is existence-validated and stored but carries no constraint — app.py:942-945.
- §3.3 — insert — ambiguity — arena-date-conflict guard runs after body field-shape checks — app.py:957-972.
- §3.4 — insert — ambiguity — malformed `segment_label` → ERR_INVALID_REQUEST between visa check and conflict check — app.py:1133-1134.
- §3.4 — insert — ambiguity — chapter_index further tie-breaks (chapter `created_at`, then chapter `id`); indexes recomputed across the storyline on each new chapter — app.py:405-418, 1301.
- §3.4 — revise — mismatch — a scratch has no storyline side effect at all; gap increments arrive only via chapter-miss (cancellation/shelving); only termination hop-2 concludes storylines — app.py:398-402 (`scratch_booking` touches nothing else).
- §3.4 — insert — ambiguity — scratching a non-BOOKED booking → ERR_INVALID_STATE, before event-mutability check — app.py:1183-1187.
- §3.5 — insert — ambiguity — locking a non-SCHEDULED event → ERR_INVALID_STATE(409), ahead of the version guard — app.py:1011-1012.
- §3.5 — insert — ambiguity — completing non-LOCKED / cancelling non-SCHEDULED → ERR_INVALID_STATE(409) — app.py:1038-1039, 1067-1068.
- §3.5 — insert — ambiguity — no-show rejections all ERR_INVALID_STATE(409) in order booking-state → event-state → same-day; nested path does not verify booking↔event linkage — app.py:1195-1206.
- §3.7 — revise — mismatch — no endpoint ever moves a partner to SUSPENDED; registered partners remain ACTIVE — app.py:1335-1340 (no suspend route exists).
- §3.7 — insert — ambiguity — territory-right field-shape validation precedes the conflict check — app.py:1366-1373.
- §3.7 — insert — ambiguity — distribution-window creation does not gate on event status (SCHEDULED/LOCKED only at publish) — app.py:1472-1473.
- §3.7 — insert — ambiguity — window field-shape validation precedes licensing/timing checks — app.py:1475-1483.
- §3.7 — revise — ambiguity — licensing "spans" pinned precisely: `window_start_date ≤ opens_at` UTC date and `closes_at` UTC date strictly `< window_end_date` — app.py:1496.
- §3.7 — insert — ambiguity — REVOKED windows ignored by the window-overlap check — app.py:1454-1455.
- §3.7 — insert — ambiguity — publish/revoke from wrong status or wrong event state → ERR_INVALID_STATE(409) — app.py:1541-1545, 1561-1562.
- §3.8 — insert — ambiguity — `sold_at` validated only as ISO 8601, never against event date or clock — app.py:1630.
- §3.8 — insert — ambiguity — day-gross tier groups by `sold_at` UTC calendar date — app.py:1588-1599.
- §3.8 — insert — ambiguity — discounted rate not floored at zero; negative `royalty_cents` possible — app.py:1605-1608.
- §3.8 — insert — ambiguity — statement `event_id` is null when zero lines included — app.py:1705-1706.
- §3.9 — insert — ambiguity — `quarter` rendered as `YYYY-Qn` string — app.py:626.
- §3.9 — revise — mismatch — `committed` counts FULFILLED bookings dated anywhere in the quarter (not restricted to the elapsed part) — app.py:654-657.
- §3.9 — insert — ambiguity — quarter-floor agreement = half-open window containing the quarter's last day, ACTIVE at read time; none → floor 0 — app.py:629-640.
- §3.10 — insert — ambiguity — case creation flips only ACTIVE→INJURED (SUSPENDED/already-INJURED keep status); multiple OPEN cases allowed — app.py:1802-1805.
- §3.10 — revise — mismatch — injury scratches have no storyline side effect; horizon pinned as [clock date, clock date + 30 days] inclusive — app.py:1807-1820.
- §3.10 — revise — mismatch — `evaluator_id` comes from the request body, not the `X-User-ID` header; evaluation on non-OPEN case → ERR_INVALID_STATE — app.py:1844-1856.
- §3.10 — revise — mismatch — clearance `cleared_by` is a required body field (opaque string), not the header — app.py:1869-1872.
- §3.10 — insert — ambiguity — clearance flips talent INJURED→ACTIVE only if currently INJURED; SUSPENDED stays — app.py:1891-1895.
- §3.11 — insert — ambiguity — any number of visa cases may coexist per talent+country — app.py:1919-1925 (no uniqueness check).
- §3.11 — revise — mismatch — visa-denial scratches have no storyline side effect — app.py:1971-1984.
- §3.12 — insert — ambiguity — readiness window is [clock date − 90 days, clock date] inclusive by event date; NO_SHOW counted on any event type — app.py:560-580.
- §3.12 — revise — mismatch — deleted the "ties broken by talents' created_at" sentence (no cross-talent decision ordering exists in the API); added that the endpoint doesn't gate on current `roster_tier` and a rejected PROMOTE records no decision — app.py:586-603.
