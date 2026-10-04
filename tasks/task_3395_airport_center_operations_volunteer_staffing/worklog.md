# Worklog — task_3395_airport_center_operations_volunteer_staffing

Scenario: Airport Center Operations & Volunteer Staffing (USO) — center site agreements, eligibility verification at check-in, volunteer recruitment/screening/shift scheduling, donated food & supply management with corporate partners, deployment/homecoming events, entertainment tour logistics, center services with usage policies, donor funding with center-level cost accountability. Difficulty: much harder than expert level.

## Step 1: Create task directory — 2026-10-01T16:10:00.000Z

Pre-allocated directory `./tasks/task_3395_airport_center_operations_volunteer_staffing/` verified to exist with `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-01T17:17:00.000Z

All checks pass. Final lint verdict block (verbatim from `scaffold_lint.py`):

```
Coverage
  §1.5 endpoints declared:    46
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     44
  Calls scanned (§1.8+§1.9):  520

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Design summary** — USO-style airport center operations, Expert+ density rather than volume:
- **Archetype**: posture-driven gating (Center.posture CLOSED/RESTRICTED/OPEN derived from ACTIVE site agreement + confirmed-only staffing coverage, gating check-ins, service bookings, events) blended with temporal windowing (three distinct overlap semantics: half-open volunteer shifts, buffered FAMILY_ROOM with 45-min cleaning gap, half-open event windows) + ops-run checkpoint (`run_ops` sweeps screenings, volunteers, agreements, lots, assignments, check-ins, bookings, events, grants).
- **Hard mechanics**: dual-variant calcs in two domains (coverage confirmed-only vs optimistic; cost-per-visit actual vs loaded); pinned per-lot-then-sum partner-match rounding (3×3¢ → 3 not 2); waterfall expense allocation with all-or-nothing boundary; FEFO lot selector with created_at tie-break; segregation-of-duties screening (claimer ≠ decider); 3 OCC concurrency rules (screening create / agreement activate-supersede / expense post); two transitive cascades (screening-expiry depth-4 via run_ops; third-no-show depth-3 via mark-no-show); cyclic machines (agreement renewal, volunteer rescreen, guest reverify, shift OPEN↔FILLED); branching event machine (tour security path vs deployment direct path).
- **Clock**: `POST /_clock/set_current_utc` with fixed default 2026-09-01T00:00:00Z; all 173 fixture timestamps ≥ clock start (the only earlier literal, 2026-08-15, is an intentionally-expired guest verification document date).

**Final-verification results**: (a) all three files parse; (b) SCAFFOLD.yaml has no `scaffold_difficulty_design`/`scaffold_corner_design` key; (c) each design file has exactly its single required top-level key; (d) all 67 instances (18 §1.8 + 44 active §1.9 + 5 `excluded_because` stubs) have unique `name:` fields; (e) domain grep confirms on-domain content (center ×958, volunteer ×363, eligibility ×58, screening ×162, agreement ×219, tour ×44, donation ×51, grant ×59, etc.). All constants are literal-pinned in a canonical `constants:` block; every error in the 29-code catalog is triggered by at least one instance; no sibling task directories were read.

**Files written**:
- `SCAFFOLD.yaml` — 1960 lines, §1.0–§1.7 (12 entities, 12 state machines, 9 calculations, 10 ordered validation priorities, 46 endpoints, 29 errors, 5 roles, 3 OCC concurrency rules, pinned constants)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1270 lines, 18 instances (2 per each of the 9 difficulty rules), all with structured replayable `setup_api_calls`/`trigger`/`assert`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1611 lines, 44 active corner instances + 5 exclusion stubs across all nine claim-guide sections

Orchestrator verification: all three files exist, parse as YAML, correct top-level keys, 46 endpoints, on-domain grep hits ×365.

## Step 3: Copy shared files — 2026-10-01T17:20:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T17:45:00.000Z

**PRD generated and fully verified.**

**Output:** `workspace/PRD.md` — 261 lines, sections 1–5 complete (Introduction; §2.1–2.9 global specs; §3.1–3.8 workflows; §4 endpoint table; §5 error catalogue). §2.2 is byte-identical to the canonical `section-2.2-response-structure.md` (inserted via `cat`, then diff-verified). `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

**Final verification counts (all PASS):**
- Error IDs: 29 required, 29 present, 0 missing
- Endpoint paths: 46 required, 46 present, 0 missing
- Constant literals (incl. `2026-09-01T00:00:00Z`, 24 months, strike limit 3, 60-day renewal window, 0.75, 0.5, 45-minute buffer, pool capacities 8/4/20/1, duration caps 480/30/120/240, daily caps 360/240, match 0.25): 18 required, 18 present, 0 missing
- State names: 36 required, 36 present, 0 missing
- Enum tokens: 53/53; roles: 5/5
- Contract 1 (field-name coverage): 78 entity+endpoint field names, 78 present in backticks; 14 optional/query params, 14 present (first-pass "65 missing" was a checker artifact — triple-backtick fences swallowed inline-token pairing; fence-stripping fixed the extractor, not the doc)
- Contract 3 (§3 path purity): 453 backtick tokens scanned, 0 path/method violations
- Contract 2 (rule coverage): manually audited — validation priority pipeline ordered in §2.7; all 3 OCC rules with write op + `expected_*_version` + `ERR_STALE_VERSION`/412 in §2.5 and restated per workflow; all 12 state machines' transitions with guards and both-branch side effects; all 9 calculations in reconstructible prose (confirmed-only vs optimistic coverage variants, FEFO with `created_at` tie-break, waterfall boundary case, pinned per-lot-then-sum partner-match rounding with the three-3-cent-lots example, actual vs loaded cost-per-visit with null-on-zero-visits); all cross-entity cascades (supersede, suspension, screening-lapse, day-end check-out); sibling branches rendered symmetrically.

One scaffold ambiguity surfaced and resolved by design: the validations table groups `ERR_GUEST_INELIGIBLE` under an HTTP-409 priority row while the error catalog pins it at 403 — §5 follows the error catalog (403), and §3 prose names only the error ID, so no contradiction is baked in. No scaffold rule was left unrendered.

Orchestrator spot-check: PRD.md 261 lines; 29/29 error ids, 46/46 endpoint paths, 18/18 constants confirmed present via independent script; file tail intact. NOTE for Step 7: scaffold-internal inconsistency (ERR_GUEST_INELIGIBLE 409-in-validations vs 403-in-catalog) — PRD pins 403.

## Step 5a: Generate test helpers (phase 1 of 2) — 2026-10-01T18:05:00.000Z

All smoke checks pass. Step 5a is complete — test infrastructure is frozen and ready for Step 5b.

**Files written (all under the task dir):**
- `test_helpers/__init__.py` — 162 lines (barrel export)
- `test_helpers/types.py` — 338 lines (12 entity TypedDicts, 12 status enums + role enum; all entities carry id/created_at/updated_at/version since every entity here has common_fields: true)
- `test_helpers/api_client.py` — 228 lines (ApiClient with one method per endpoint: all 46 endpoints including clock, run_ops, cost-report, expense waterfall)
- `test_helpers/api_errors.py` — 81 lines (full 29-code catalog, registers with `set_error_http_status_map`)
- `test_helpers/assertions.py` — 228 lines (assert per entity + shift-capacity and occupancy invariants)
- `test_helpers/factories.py` — 240 lines (payload factories, input fields only, defaults all reachable from clock start)
- `test_helpers/constants.py` — 56 lines
- `test_helpers/test_users.py` — 65 lines
- `test_helpers/fixtures.py` — 366 lines (7 tiers: clock, single-entity create, agreement lifecycle, vetting cycle, shifts/coverage incl. `setup_open_center`, guests/bookings, money)
- `test_suite/conftest.py` — 55 lines

**Smoke results:**
- py_compile: all 10 files COMPILE_OK
- Import smoke: `import test_helpers.fixtures, ...factories, ...test_users, ...assertions, ...api_client, ...api_errors, ...constants, ...types` → IMPORT_OK
- `pytest test_suite/ --collect-only -q` → "no tests collected in 0.17s" (zero errors, conftest imports cleanly)
- Constants cross-check (SCAFFOLD.yaml `constants:` block vs constants.py, name+value+type): `CONSTANTS_OK: all 18 names+values match identically` — CLOCK_DEFAULT_UTC, SCREENING_VALIDITY_MONTHS=24, STRIKE_LIMIT=3, RENEWAL_WINDOW_DAYS=60, COVERAGE_OPEN_THRESHOLD=0.75, COVERAGE_ASSIGNED_WEIGHT=0.5, ROOM_BUFFER_MINUTES=45, four type capacities, four type max-minutes, both daily caps, MATCH_PCT=0.25.

**Factory/fixture coverage scan of §1.8 (18 instances) and §1.9 (29 non-stub instances):** 47/47 covered. Every `setup_api_calls`/`trigger` call maps to an ApiClient method, and every composite chain has a fixture path: center+agreement activation with OCC (`create_center_with_active_agreement`), segregated screening cycle (`create_cleared_volunteer` claims as mgr-1, decides as mgr-2), OPEN-posture centers (`setup_open_center` pins shift start to the clock date), expense posting with fresh OCC version (`post_expense` re-reads the center), clock control (`set_clock`/`reset_clock`). Nothing uncoverable.

**Divergences found and resolved:**
1. ERR_GUEST_INELIGIBLE: scaffold validations table (priority 7) groups it under a 409 row, but the scaffold `errors:` block and PRD §5 catalog both pin 403 — used 403 per the catalog (per constraint 8).
2. Identity model: Volunteer and Guest are entity-backed; `test_users.py` ships shared fallback headers (for role-denial probes only) plus mandatory `make_volunteer_headers(id)`/`make_guest_headers(id)` builders, and fixtures thread the real entity id (e.g. `confirm_assignment` uses the volunteer's own id). Segregation of duties is structural: three distinct manager ids, claim defaults to mgr-1, decide to mgr-2.
3. Status codes: creates are 201 (centers, agreements, volunteers, screenings, shifts, assignments, guests, check-ins, bookings, lots, events, grants, expenses per PRD §4), all transitions/reads 200; fixtures use the lenient `get_success_data` for setup so no create is silently held to 200.
4. Clock: default start 2026-09-01T00:00:00Z; all factory date/datetime defaults are on/after that date; fixtures that depend on business dates set the clock explicitly first.

**ORCHESTRATOR CORRECTION (verified by independent YAML parse):** the "29 non-stub §1.9 instances" figure above is WRONG. Actual counts: §1.8 = 18 active instances (9 rules × 2, 0 stubs); §1.9 = 49 instances of which 5 are excluded/stub (`event_initial_status_branch`, `lot_depleted_consume_rejected`, `priority_state_beats_guest_safety`, `priority_temporal_beats_quota`, `immediate_occupancy_visibility`) → **44 active corner instances**. True candidate total = 62, not 47. Step 5a's factory-coverage scan missed 15 corner instances; helpers are generic so coverage is likely still fine, but Step 5b must audit its Design tags against the true 62-instance list (18 + 44), not the 47 figure.

## Step 5b: Generate test suite (phase 2 of 2) — 2026-10-01T18:50:00.000Z

Everything verified. Helpers and conftest.py are byte-untouched (mtimes predate this session); all audits green.

**Step 5b complete.** All 62 active design-index instances (18 Difficulty + 44 Corner) are implemented as 62 tests across 11 files under `test_suite/`:

- `test_01_center_creation_envelope_pagination.py` (194 lines, 7 tests)
- `test_02_rbac_access_control.py` (153, 6)
- `test_03_site_agreements.py` (126, 3)
- `test_04_volunteers_screenings.py` (247, 6)
- `test_05_shifts_assignments_coverage.py` (387, 7)
- `test_06_guests_checkins.py` (188, 5)
- `test_07_service_bookings.py` (291, 5)
- `test_08_events.py` (429, 9)
- `test_09_donations_fefo.py` (200, 5)
- `test_10_funding_expenses.py` (248, 5)
- `test_11_cost_reports_cascades.py` (238, 4)

**Audit outputs:**
- `py_compile` on all 12 files (11 tests + conftest): ALL_COMPILE_OK
- `pytest test_suite/ --collect-only -q` from task root: **62 tests collected, 0 errors**
- AST tag audit (real `ast` parse): 62 tagged tests, 0 errors — every test's last docstring line is exactly one `Design:` tag, all resolve to the 18+44 true instance names, no stub names tagged, no duplicates
- Coverage audit: implemented=62, missing=0, extra=0, **skipped=0**
- Verbatim-citation sweep: 105 quoted PRD spans across all docstrings, all grep-verbatim in `workspace/PRD.md`

**Skips:** none — both priority-pair instances are covered by PRD §2.7's explicit ordering ("an overlap error before a capacity one" plus the bucket enumeration), so nothing failed the two-condition filter. The 5 `excluded_because` corner stubs were correctly not translated; all 5 cross-references resolve to real difficulty instances.

**Helper fixes:** none needed — `test_helpers/` and `test_suite/conftest.py` untouched.

**Clock-literal re-derivations:** none — all recipes are reachable from the 2026-09-01T00:00:00Z start. (The past `verification_expires_on=2026-08-15` in two tests is a document date the PRD explicitly accepts at registration, not a business event time.)

**Noted derivations/adjustments (all within PRD-derivable bounds):**
1. `center_create_returns_defaults`: PRD §2.5 never pins the initial `version` value (only "+1 per mutation"), so the test asserts all §2.6-verbatim defaults (CLOSED, occupancy 0, coverage 0, empty ledger, ops_run_count 0, null active_agreement_id) and the `version >= 1` invariant via `assert_center`, instead of hardcoding the unpinned `== 1` literal from the design YAML.
2. `screening_expiry_cascade`: "future-dated" read at timestamp resolution (shift start 14:00 > 08:00 checkpoint), consistent with PRD §2.8 treating `start_at` as a timestamp and with the recipe's annotation.
3. `waterfall_allocation_order`: debit-object field names are not PRD-specified, so allocation order is verified through observable grant end-states (A: spent 500/remaining 0/EXHAUSTED; B: spent 100/remaining 600/ACTIVE) plus `posted_cents == 600` and `len(debits) == 2`.
4. `fefo_tiebreak_earliest_created`: relies on `created_at` monotonicity across sequential creations; PRD pins "ties broken by `created_at` ascending — never by `id`".

Orchestrator independent verification: 62 tests collected; AST re-audit against both design YAMLs → 62 tagged tests, 0 bad/dup tags, 0 uncovered instances.

## Step 6: Generate implementation — 2026-10-01T18:56:00.000Z

**Files written** (all under `workspace/implementation/`), one file per tool call, each compiled after writing:

| File | Lines | Role |
|---|---|---|
| `app.py` | 94 | App factory, ApiError/404/405/500 envelope handlers, `POST /_clock/set_current_utc`, blueprint registration, `0.0.0.0:$PORT` (default 10000) |
| `constants.py` | 56 | Every SCAFFOLD constant with literal values (STRIKE_LIMIT 3, RENEWAL_WINDOW_DAYS 60, 0.75 as rational 3/4, all capacities/durations, MATCH_PCT 0.25) |
| `storage.py` | 47 | In-memory dicts, empty at boot, logical clock at 2026-09-01T00:00:00Z, monotone seq |
| `helpers.py` | 430 | Envelope (meta/response_type/data, error shape), auth (X-User-ID/X-User-Role), shape validators, strict date/datetime parsing, pagination (limit 1–100 default 10, offset 0, created_at-asc sort), serializers, existence getters |
| `services.py` | 258 | Posture/coverage recompute (exact rational compare), shift OPEN/FILLED derivation, no-show/suspension/lapse cascades, full run_ops sweep |
| `centers.py` | 139 | Center create/get, run_ops route, cost report (round-half-up per-visit figures, per-lot match sums) |
| `agreements.py` | 122 | Draft/list/activate (OCC + supersede cascade)/renew |
| `volunteers.py` | 154 | Register/list/get, screening open (OCC)/list/claim/decide with segregation of duties and 24-month expiry |
| `shifts.py` | 264 | Shift CRUD, assignment create (eligibility + half-open overlap)/confirm/complete/mark-no-show/cancel |
| `guests.py` | 151 | Register/get/reverify, lazy eligibility flip, check-in gauntlet, check-in lists |
| `bookings.py` | 162 | Booking gates in §2.7 order: posture → eligibility → overlap (aggregate + FAMILY_ROOM 45-min buffer) → duration (422) → quota |
| `lots.py` | 123 | Intake with per-lot round-half-up partner match, FEFO consume |
| `events.py` | 153 | Creation fork (PLANNED vs SECURITY_REVIEW), overlap, approve-security chain, optimistic staffing gate, cancel |
| `funding.py` | 120 | Grants, expense waterfall (all-or-nothing, spend_by_date then created_at order, EXHAUSTED flips) |
| `start.sh` | 9 | Guarded install, `exec python3 app.py`, foreground |
| `requirements.txt` | 1 | flask==3.1.3 (verified installed) |

**py_compile:** `ALL_COMPILE_OK` across all 14 Python files.

**Undefined-reference grep:** clean — every shared ALL_CAPS name resolves to `constants.py` exactly once; audit hits were false positives (module-local `READ_ROLES` constants, `ROUND_HALF_UP` from `decimal`, `STORE` import, status string literals, docstring words).

**Smoke transcript** (dynamic port 33983, server PID saved and killed exactly): clock set 200 → center create 201 (CLOSED, v1) → get 200 → missing-field 400 `ERR_VALIDATION` → no-headers 401 `ERR_UNAUTHENTICATED` → agreement draft 201 → stale activate 412 `ERR_STALE_VERSION` → activate 200 (center RESTRICTED, v2) → volunteer 201 → screening 201 → duplicate 409 `ERR_SCREENING_ALREADY_OPEN` → claim 200 → same-user decide 409 `ERR_SEGREGATION_OF_DUTIES` → mgr2 decide 200 (expires_at 2028-09-01) → shift 201 → assignment 201 → wrong-owner confirm 403 → owner confirm 200 (center OPEN coverage 1.0, volunteer ACTIVE, shift FILLED) → guest + check-in 201 → duplicate 409 `ERR_ALREADY_CHECKED_IN` → guest SHOWER booking 201 → 31-min SHOWER 422 `ERR_BOOKING_DURATION_INVALID` → lot 99c → match 25 → consume 200 (remaining 6) → grant 201 → expense 201 with OCC and debits list → cost report 200 (actual 5000, loaded 5000, match 25) → run_ops 200 (center v5→v6, exactly one bump) → clock +1 day → run_ops: assignment auto-NO_SHOW, strikes 1, posture RESTRICTED, occupancy swept to 0.

**Boot-clean check:** second fresh boot on dynamic port 39825 — empty store (old center 404s), clock at PRD default; killed exact PID. No leftover processes.

**Interpretation decisions** (PRD-silent or double-reading spots → choice → rationale):
1. `created_at`/`updated_at`/`posted_at`/`checked_in_at` read the logical clock (ms format); `api_request_timestamp` uses wall clock — §2.4 makes the logical clock govern temporal rules; ledger `posted_at` feeds month filtering.
2. `version` starts at 1 — PRD never states the origin.
3. Every stored posture/coverage recompute bumps `Center.version` (§2.6); run_ops is the explicit "exactly one" exception.
4. `ERR_VOLUNTEER_NOT_ELIGIBLE` / `ERR_POSTURE_SERVICE_BLOCKED` sit at the state tier (absent from the validations priority rows; §3.3/§3.5 narratives place them before overlap/capacity).
5. Booking gates follow §2.7 (overlap before duration/quota), not §3.5's narrative order — §5 defers ordering to §2.7.
6. Expired-but-unswept lot with other valid candidates → `ERR_FEFO_VIOLATION`; `ERR_LOT_EXPIRED` only when the candidate set is empty and the target itself is expired (the fefo_issue_order formula's explicit rule).
7. Volunteer registration validates `home_center_id` existence (404) — least-surprising for a declared FK.
8. Single-GET ownership enforced on resources referencing the actor (`volunteer_id`/`guest_id` on assignments/bookings/check-ins → 403 cross-owner); same-entity GETs (`/volunteers/{id}`, `/guests/{id}`) role-gated only — §2.1 scopes assignments and listings, not these.
9. Expense `debits` entries shaped `{"grant_id", "amount_cents"}` — PRD names only `posted_cents` and order preservation.
10. "Future-dated" in cascades = `shift.start_at > now`; suspension fires only from ACTIVE (the declared transition).
11. Clock response formats `current_utc` with milliseconds rather than echoing input.
12. Reverify on a non-EXPIRED guest → `ERR_INVALID_STATE` (machine defines reverify only from EXPIRED).
13. run_ops sweeps volunteers/screenings via `home_center_id`; cross-center cascade effects bump each affected center once; target center exactly once.
14. Naive request timestamps treated as UTC; date-only strings rejected as malformed timestamps.
15. Event overlap blocks against all non-CANCELLED events (including EXECUTED) per the error catalog wording.

**Isolation confirmation:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, and `test_helpers/` were never opened, grepped, or listed; the implementation derives only from INSTRUCTION.md, SCAFFOLD.yaml, and PRD.md. The test suite was never run. No broad kill patterns were used — only exact PIDs.

Orchestrator spot-check: all 14 .py files compile independently; start.sh is foreground `exec python3 app.py` with guarded pip install; requirements pinned to installed flask==3.1.3.

## Step 7: Test-fix iteration loop — 2026-10-01T19:09:00.000Z

result: task_3395 green — all 8 parallel rounds pass 62/62 after 2 fixes (set_clock default arg in fixtures, canonical UUID in implementation); 8 results.*.json preserved.

**Summary**

- **Iterations run:** 2 sweeps. Sweep 1: union of 54/62 failing (8 passed in every round). Sweep 2: clean — 62/62 in all 8 rounds, union empty.
- **Tests deleted:** none. Every failure traced to a mechanical bug, not to PRD silence or broken unique-derivability.
- **Fixes applied to `test_helpers/`:** `test_helpers/fixtures.py` — `set_clock()` given default `to_iso8601=CLOCK_DEFAULT_UTC`. 53 call sites across all 11 test files invoke bare `set_clock()` at test top intending "reset to default start" (identical to the existing `reset_clock()` helper); the missing default caused `TypeError` in 54 tests × 8 rounds (424 occurrences). Behavior-preserving — with per-test-server isolation the clock already boots at the default.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** `workspace/implementation/helpers.py` — `new_id()` changed from `uuid.uuid4().hex` (32-char, no hyphens) to `str(uuid.uuid4())` (canonical hyphenated form). PRD §2 line 78 pins "`id`, a server-minted UUID with no type prefix"; the benchmark-shared `is_valid_uuid` assertion (used by every `assert_*` entity helper) requires canonical form. This was masked in sweep 1 — only `test_checkin_occupancy_roundtrip_invariant` reached a UUID assertion before dying on the TypeError; fixing it pre-emptively avoided a wasted iteration.
- **Sibling unasserted implementation paths surfaced:** none. The iteration contained no test-weakening and no PRD-check removal; the two fixes were a Python signature bug (test side) and an id-format normalization (impl side). The 15 Step-6 interpretation decisions in `worklog.md` (e.g. version starts at 1, posture/coverage recompute bumps Center.version, booking-gate ordering per §2.7, FEFO expired-lot disambiguation) are all now exercised by the green suite — no unasserted siblings were observed during triage.
- **Results evidence confirmed:** all 8 `results.1.json` … `results.8.json` from the final clean sweep remain in `workspace/implementation/` (not deleted).

Orchestrator verification: 8/8 results files present, each passed=62/total=62/failed=0; newest source file (helpers.py) predates oldest results file → sweep is FRESH; both fixes confirmed in source (`fixtures.py:60` set_clock default; `helpers.py:186` str(uuid.uuid4())).

## Step 8: Finalize PRD — 2026-10-01T19:20:00.000Z

Diff confirms exactly one line revised in place. All checks pass.

**Summary**

- **Line counts:** PRD.md = 261 lines, PRD_FINALIZED.md = 261 lines. Delta = 0 lines (0.0%); one line revised in place, nothing added or removed.

**Changes (1 edit):**
- §2.5 "Common Resource Properties and Optimistic Concurrency" (line 78) — **revise** — changed "`id`, a server-minted UUID with no type prefix" to "`id`, a server-minted UUID in canonical hyphenated string form (e.g., `550e8400-e29b-41d4-a716-446655440000`) with no type prefix" — pins the hyphenated 8-4-4-4-12 serialization that `implementation/helpers.py:186` (`new_id()` → `str(uuid.uuid4())`) exhibits. The original wording admitted `uuid.uuid4().hex` (32-char, no hyphens) — proven by the fact that Step 6's implementer chose exactly that from this same text — while the benchmark-shared `is_valid_uuid` (verified live: accepts hyphenated, rejects 32-char hex) requires canonical form.

**Pre-edit search log (mandatory for the one edit):**
- (a) **Subject:** string serialization format of server-minted resource `id` values.
- (b) **Impl paths enumerated and grepped/read:** `helpers.py:185-186` (`new_id()`), `helpers.py:189-192` (`base_entity()`); all 12 `base_entity()` call sites (`lots.py:61`, `agreements.py:47`, `events.py:60`, `shifts.py:60`/`:120`, `centers.py:40`, `bookings.py:123`, `guests.py:57`/`:114`, `volunteers.py:41`/`:90`, `funding.py:52`) — every minted id flows through the one canonical-form generator; grep for input-side UUID parsing/validation across `implementation/`: zero hits (ids are opaque lookup keys); grep for client-supplied `"id"` reads: none; PRD-wide grep for `uuid|server-minted|no type prefix`: only line 78.
- (c) **Wording adjustment:** chose "in canonical hyphenated string form (e.g., ...)" over "8-4-4-4-12" or "version-4 UUID" — pins hyphenation concretely without adding a UUID-version claim the PRD never made.

**Zero-edit justification for the remaining step_7_diff item:**
- `test_helpers/fixtures.py` `set_clock()` default — pure test-side mechanical bug (missing Python default argument). PRD line 74 already fully pins the clock contract. No PRD silence or mismatch — no edit manufactured.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the line-78 revision and nothing else; no implementation/ file is newer than the Step 7 sweep results — sweep remains fresh.

## Step 9: Complete PRD — 2026-10-01T19:50:00.000Z

**Files**: `workspace/PRD_FINALIZED.md` → `PRD_COMPLETED.md`. Both 261 lines (all edits in-paragraph; no new sections). Char delta: 43,438 → 46,546 (**+3,108 chars**).

**Counts**: 18 ambiguity-pins, 5 mismatch-revisions (23 change sites, applied as 22 Edit-tool calls producing 21 diff hunks — two changes shared the §2.7 shape/existence sentence, and the §3.5 reorder received one in-hunk wording refinement).

**Per-change bullets** (`{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

1. §2.1 — insert — ambiguity — pin single-GET ownership scoping: Volunteer reads only own assignments (403), Guest reads only own check-ins/bookings (403), guest-list `guest_id` mismatch is 403 not silent filter, volunteer/guest records unscoped on read — shifts.py:136-137,147-150; guests.py:69-73,134-135; bookings.py:141-142,152-155; volunteers.py:55-59
2. §2.2 — insert — ambiguity — `api_request_timestamp` comes from the server's wall clock, not the logical clock — helpers.py:53-54
3. §2.3 — insert — ambiguity — `limit`/`offset` must be integers in range else ERR_VALIDATION; `created_at` ties broken by server insertion order — helpers.py:330-349
4. §2.4 — insert — ambiguity — clock response `current_utc` has three fractional digits and `Z` suffix; naive timestamps interpreted as UTC; date-only strings invalid as timestamps — app.py:76-86; helpers.py:98-132
5. §2.5 — insert — ambiguity — `version` starts at 1 on creation; `created_at`/`updated_at` stamped from the logical clock — helpers.py:179-197
6. §2.6 — revise — ambiguity — `coverage_ratio` exposed as the ratio's decimal value; only the threshold comparison is exact-rational — services.py:38,49
7. §2.7 — revise — **mismatch** — renewal's new-end-date ordering removed from the shape stage (impl runs it after the renewal-window state check) — agreements.py:113-116
8. §2.7 — insert — ambiguity — body-carried ids (`home_center_id`, `volunteer_id`, `guest_id`, `center_id`) resolve at the existence stage after path resources, yielding ERR_NOT_FOUND — volunteers.py:38-39; shifts.py:101-103; bookings.py:64-65; funding.py:50
9. §2.7 — insert — **mismatch** — entity-backed ownership on path-identified resources is evaluated after the resource loads, so a missing resource yields ERR_NOT_FOUND even for an out-of-scope caller (pipeline had authz strictly before existence) — shifts.py:164-166,246-248; guests.py:133-135; bookings.py:140-142
10. §2.7 — insert — ambiguity — ERR_POSTURE_SERVICE_BLOCKED placed in the state-admissibility tier and ERR_VOLUNTEER_NOT_ELIGIBLE in the safety-and-compliance tier (both were absent from the tier lists) — bookings.py:68-74; shifts.py:105-106,171-176
11. §2.9 — revise — ambiguity — run_ops screening sweep scoped through volunteers whose `home_center_id` is the swept center; no-show/booking/event sweeps fire when the boundary is at or before the checkpoint time — services.py:153-154,209,226,234,237
12. §3.1 — revise — **mismatch** — renewal fires ERR_RENEWAL_WINDOW_NOT_OPEN before the `new_end_date` ordering check (narrative had the date rule first) — agreements.py:113-116
13. §3.2 — insert — ambiguity — `expires_at` = exactly 24 calendar months from the logical-clock decision time, day clamped to month end — volunteers.py:144; helpers.py:143-149
14. §3.2 — insert — ambiguity — "future-dated" in cascades means shift `start_at` strictly later than now (a shift starting exactly now survives) — services.py:90-91
15. §3.3 — revise — ambiguity — completion/no-show admitted once `end_at` is at or before now; `actual_hours` is any number > 0, fractions allowed — shifts.py:200-208,229-230
16. §3.3 — revise — ambiguity — a manual no-show applies the §2.6 recompute-and-store twice, so center `version` advances by two; auto no-show boundary at-or-before — shifts.py:232-238; services.py:209-210
17. §3.4 — revise — ambiguity — reverify admitted only from EXPIRED (ERR_INVALID_STATE on ELIGIBLE), state check before the date floor — guests.py:83-86
18. §3.5 — insert — ambiguity — booking length floored to whole minutes; a sub-minute window fails the positivity check — bookings.py:60-62
19. §3.5 — revise — **mismatch** — gate order pinned to impl: capacity-pool overlap check runs before duration ceiling and daily quota (narrative had overlap "Finally") — bookings.py:76-121
20. §3.6 — revise — **mismatch** — a non-AVAILABLE target lot is ERR_INVALID_STATE unconditionally before candidate analysis; ERR_LOT_EXPIRED only for an AVAILABLE expired target with an empty candidate set (PRD had conditioned both on the empty set) — lots.py:96-110
21. §3.7 — insert — ambiguity — `min_volunteers` and `event_budget_cents` are integers of at least 0 — events.py:47,50
22. §3.7 — revise — ambiguity — event EXECUTED/CANCELLED sweeps fire at-or-before the checkpoint time — services.py:234,237
23. §3.8 — insert — ambiguity — `debits` entries carry `grant_id` and the debited `amount_cents`; ledger `posted_at` stamped from the logical clock — funding.py:111,113-114

**Final `diff -q` reconciliation**: `Files workspace/PRD_FINALIZED.md and workspace/PRD_COMPLETED.md differ` (exit 1) — consistent with 23 claimed changes across 21 hunks; no edits lost.

**Isolation confirmation**: only `workspace/PRD_COMPLETED.md` was written (22 Edit calls, all on that file); every other command was read-only. `implementation/`, `test_suite/`, `test_helpers/` untouched. SCAFFOLD*.yaml and worklog.md were never read.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (43,438 → 46,546 bytes = claimed +3,108); NO implementation/test_helpers/test_suite source file is newer than the Step 7 sweep results — the clean 8-round sweep remains valid, no regeneration needed.
