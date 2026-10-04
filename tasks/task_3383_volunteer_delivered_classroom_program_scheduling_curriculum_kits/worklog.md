# Worklog — task_3383_volunteer_delivered_classroom_program_scheduling_curriculum_kits

## Step 1: Create Task Directory — 2026-10-01T12:20:00.000Z

Pre-allocated directory `tasks/task_3383_volunteer_delivered_classroom_program_scheduling_curriculum_kits/` verified to exist with `workspace/` inside (no new index computed, per invocation instructions).

## Step 2: Generate Scaffold — 2026-10-01T13:50:00.000Z

Scaffold generation complete and lint-clean. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3383_volunteer_delivered_classroom_program_scheduling_curriculum_kits/`):
- `SCAFFOLD.yaml` (1403 lines) — §1.0–§1.7; no design keys embedded
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2099 lines) — single top-level `scaffold_difficulty_design` key
- `SCAFFOLD_CORNER_DESIGN.yaml` (2479 lines) — single top-level `scaffold_corner_design` key

**Counts:**
- Entities: 12 (AreaOffice, SchoolDistrict, School, CorporatePartner, Volunteer, ProgramCatalog, PartnershipAgreement, ClassroomDelivery, DeliverySession, KitInventory, CapstoneEvent, StudentParticipant)
- Endpoints: 43 (flat topology under `/ja-programs`, incl. `POST /_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default)
- State machines: 8 — including Volunteer with 3 parallel dimensions (screening × training × engagement), cyclic Agreement amendment loop, self-looping Session (RESCHEDULE, NO_SHOW→SCHEDULED recovery), and ClassroomDelivery with parallel status × kit_status dimensions
- Calculations: 7 (per-session-then-sum kit rounding, AND/OR-gated recognition tier with EARNED/PROJECTED variants, PROVISIONAL/FINAL evaluation metrics, per-session hours rounding, funding floor, adjacent-pair cadence, buffered facility capacity)
- Errors: 29; Roles: 6 (all opaque, peer-role model + read-only Funder); OCC concurrency rules: 2 (agreement-versioned delivery create, delivery-versioned substitute)
- §1.8: 18 instances (9 rules × 2), every recipe with structured `setup_api_calls` replayed from empty-DB, all formula-derived asserts pre-computed as literals (e.g., required_kits 33 vs the wrong 30; growth 15.0 vs 17.5; hours 0.99 vs 1.0; exact capacity 60 == 60 pass / 70 fail)
- §1.9: 53 instances (46 active + 7 `excluded_because` stubs) across all nine claim-guide sections; every error code is exercised by at least one instance

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1386 calls scanned, 0 violations)

**Difficulty levers used (per the harder-than-expert directive, without endpoint inflation):** dual-variant calculations on two distinct domains (student outcomes vs sponsor funding/hours); two OCC-guarded write paths with cascade-driven version drift; two depth-3 transitive cascades (partner EXIT → volunteer DEPARTED → session NEEDS_SUBSTITUTE → delivery recompute; district CHURN → agreement TERMINATE → delivery CANCEL → kit release); two compensating invariants (kit ledger, service hours); two distinct interval semantics (volunteer half-open vs facility buffered-aggregate); clock-sweep side effects (credential expiry, auto-NO_SHOW); and multi-gate delivery scheduling (teacher confirm × session count × kit reservation × cadence).

One design correction made mid-flight: the cadence rule was initially written as all-pairs [3,14]-day gaps, which makes any 5-session weekly program unsatisfiable — fixed to adjacent-pair (consecutive-visit) semantics in both the calculation and the session CONFIRM precondition before drafting the recipes.

Orchestrator verification: all three YAML files exist and parse (`yaml.safe_load` OK); top-level keys correct (SCAFFOLD.yaml has no design keys; design files have their single keys); domain sanity confirmed — `domain_name: volunteer-classroom-programs`, `api_prefix: /ja-programs`, 12 entities match the JA scenario; 43 endpoints listed (flat CRUD+transition topology, includes clock endpoint). 43 marginally exceeds the ~40 impl-gen coherence threshold from prior runs; scaffold is lint-clean and §1.8/§1.9 are tightly coupled to the endpoint set, so proceeding at 43 with mandatory post-Step-6 on-disk verification rather than risking a desynchronizing trim.

## Step 3: Copy Shared Files — 2026-10-01T13:51:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T13:58:00.000Z

All contracts verified. The document is complete and clean.

**Output:** `workspace/PRD.md` — 317 lines, ending at §5 with no audit footer.

**Sections produced:**
- **§1 Introduction** — 2 paragraphs (business context of volunteer-delivered classroom programs; system scope including the logical clock)
- **§2 Global Specifications** (10 subsections) — 2.1 roles/RBAC with per-role opaque-identity prose; 2.2 response envelope emitted verbatim from `section-2.2-response-structure.md`; 2.3 pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields); 2.4 logical clock (default `2026-09-01T00:00:00Z`, expiry + auto-NO_SHOW sweeps); 2.5 common resource properties; 2.6 OCC (both rules, exact error ids + 412); 2.7 the 11-tier validation ladder with tier-8 district-before-sponsor ordering and tier-9 sub-order; 2.8 flat addressing + left-to-right id validation; 2.9 kit-stock invariant; 2.10 precision/rounding rules
- **§3 Business Logic** (8 subsections) — territory/district lifecycle with CHURN cascade; partner + three-dimension volunteer credential pipeline with EXIT cascade; agreements (floor, funding self-loop, amendment cycle, recognition ladder); delivery planning incl. pinned per-session `required_kits` rounding (33-kit worked example, forbidden 30); sessions (cadence 3–14 inclusive, delivery window, substitution OCC); kit lifecycle RESERVE→DISTRIBUTE→RECONCILE plus both RELEASED return variants; capstone buffered-capacity (60/90 seats, 30-min buffer); surveys + PROVISIONAL/FINAL evaluation report
- **§4 Endpoint table** — 43 rows, 4 columns only
- **§5 Error catalogue** — 29 rows, 2 columns only

**Hard Contract self-audit (Zero-Silence):**
- **Contract 1 Field-Name Coverage: PASS** — 79/79 entity fields, 65/65 endpoint inputs, 20/20 query params, 11/11 path params present in backticks; 0 missing
- **Contract 2 Rule Coverage: PASS** — 11/11 validation tiers expressed with ordering; 2/2 OCC rules fully expressed; all transitions across the 8 state machines named with precondition→error_id pairs and side effects; 7/7 calculations reconstructed in precise prose with all constants embedded; all 29 error ids paired to triggers in §2/§3; all endpoint side effects covered; structured field content reconstructible
- **Contract 3 §3 Path Purity: PASS** — 309 backticked tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos
- Additional scans: no pseudocode operators outside the verbatim §2.2 JSON; no fuzzy/approximating words; all 6 role spellings exact; all 29 errors mentioned in §2/§3

One scaffold ambiguity handled: the `DeliverySession` machine lists the clock-sweep NO_SHOW only from SCHEDULED, while the clock endpoint's `side_effects` say "SCHEDULED or NEEDS_SUBSTITUTE"; the PRD follows the endpoint's more specific operational contract (§2.4, §3.5).

Orchestrator verification: `workspace/PRD.md` exists, 316 lines (wc; subagent's 317 includes trailing newline), header is the JA domain ("Volunteer Classroom Programs API"), 69 `ERR_` mentions.

## Step 5: Generate Unit Tests — 2026-10-01T14:30:00.000Z

All verification passes are green. The work is complete.

**Files written** — all under the task dir:

- `test_helpers/` (9 files, written first and frozen): `types.py` (12 entity TypedDicts + 12 status/role enums), `constants.py` (PRD-pinned literals: kit 3-base/0.20-ratio, funding floor 75000+25000/session, tier ladder 40/2M-25/1M-60-10/500K, cadence [3,14], facilities 60/90+30min buffer, clock default), `api_errors.py` (all 29 error ids + status map registered with the framework), `api_client.py` (43 endpoint methods on `GenericApiClient`), `factories.py`, `assertions.py` (per-entity + kit-ledger invariant + evaluation shape), `test_users.py` (6 opaque-role header sets — no entity-backed builders needed since PRD §2.1 declares every role's X-User-ID opaque), `fixtures.py` (clock, territory/partner/volunteer/program/agreement chains, delivery plan→schedule→deliver helpers, `base_world`/`planned_delivery`/`scheduled_delivery` composites), `__init__.py` (barrel).
- `test_suite/` (10 files): `conftest.py` + `test_01_territory_and_access.py`, `test_02_partnership_agreements.py`, `test_03_delivery_planning.py`, `test_04_sessions.py`, `test_05_kit_inventory.py`, `test_06_capstone_events.py`, `test_07_cascades.py`, `test_08_volunteers_credentials.py`, `test_09_surveys_evaluation.py`. **79 tests total.**

**AST tag audit (real `ast` walk, diffed against both indices):**
- Queue A (§1.8): **17/18 instances emitted, 34 tests** (exactly 2 per emitted instance).
- Queue B (§1.9): **45/46 active instances emitted, 45 tests**; all 7 `excluded_because:` stubs verified to reference real difficulty instances and were not translated.
- Zero untagged, dual-tagged, stub-pointing, or unresolvable tags. All 79 docstrings contain a verbatim ≥8-word PRD fragment (programmatic grep-verified; one short citation was expanded and re-verified).

**Skipped instances (PRD-first filter, gaps left as gaps):**
- `Difficulty/cross_entity_state_dependency/capstone_complete_gated_by_session_completion` — reaching ROLES_ASSIGNED requires a successful ASSIGN_ROLES, but PRD §3.7 only says roles "must belong to the facility's role catalog" without enumerating catalog members; two PRD-only implementers could ship disjoint catalogs, so the precondition is not uniquely derivable. (The sibling corner instance `corner_role_assignment_missing_student_rejected` IS catalog-robust — every catalog choice yields the same `ERR_ROLE_ASSIGNMENT_INVALID` — and was emitted.)
- `Corner/endpoints/corner_sessions_list_filters_by_volunteer_and_status` — PRD §4 says only "List sessions with filters" and never names `volunteer_id`/`delivery_id`/`status` filter parameters or their semantics; filter composition is not verbatim-covered. (The students-pagination instance survives because its DB holds exactly one delivery, so filtered and unfiltered counts coincide.)

**Design-index literal corrections (re-derived from PRD + SCAFFOLD):**
1. Dropped every recipe's initial `POST /_clock/set_current_utc` to `2026-09-01T00:00:00Z` — that IS the PRD-documented default, and PRD §2.4 only defines forward moves, so a same-value set could be rejected by a faithful impl.
2. Absolute `version == 1` / `== 2` assertions (three corner instances) are not uniquely derivable — PRD §2.5 pins "+1 per mutation" but never the initial value; replaced with type checks and relative equality (`after == before + 1`, response version == readback version).
3. `screening_expires_on == 2027-09-01` asserted as `startswith("2027-09-01")` since PRD §2.5 renders datetimes as full ISO-8601 timestamps.
4. `corner_write_off_exceeds_available_rejected`: followed the structured recipe (assemble 15, write-off 16 rejected, 15 succeeds) — the instance's `distinguishing_aspect` prose (11 vs 10) is stale relative to its own recipe.

**Clock discipline:** every fixture date is reachable by strictly forward moves from 2026-09-01T00:00:00Z; all session weekdays verified programmatically (2026-09-12 is the Saturday used for the instructional-day rejection; 2027-09-08 Wednesday session survives the 2027-09-02 expiry sweep without hitting auto-NO_SHOW).

**Compile/collect:** `py_compile` clean on all 19 files; `pytest --collect-only` collects **79 tests with 0 errors** (no dangling imports; framework present: pytest 9.1.1, `prd_bench_local_runner.testing`). No server was started and nothing was executed against a live API.

Orchestrator verification: `pytest --collect-only -q` re-run independently → **79 tests collected, 0 errors**; `grep -c 'Design: '` across test_suite → exactly 79 tags (1 per test); grep for absolute version literals (`version == 1`, `"version", 1/2`) → no hits, confirming correction #2.

## Step 6: Generate Implementation — 2026-10-01T14:58:00.000Z

Done. Final report:

**Files written (19, all under `workspace/implementation/`)**

- `start.sh` — foreground launcher, `exec python3 app.py`, guarded `pip install` (no-op when flask already present), `$PORT`/0.0.0.0
- `requirements.txt` — flask>=2.2
- `app.py` — app factory, auth `before_request`, envelope error handlers (ApiError/404/405/500), blueprint registration
- `db.py` — in-memory `STORES` (12 dicts, start empty, no seeding), logical clock defaulting to `2026-09-01T00:00:00Z`, timestamps, ids, `touch()` (updated_at + version)
- `errors.py` — all 29 PRD error ids + `ApiError`
- `response.py` — exact envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta for lists only
- `middleware.py` — X-User-ID/X-User-Role auth (6 roles), `require_roles`, body-shape validation (undeclared fields rejected, strict typing), pagination parsing (limit 1–100 default 10, offset ≥ 0), `created_at`-ascending sort
- `calc.py` — all 7 calculation rules with pinned constants (BASE_KITS=3, ratio 0.20 per-session-ceil; funding floor 75000+25000/session; tier ladder GOLD/SILVER/BRONZE thresholds; cadence [3,14]d inclusive; facility capacity 60/90 with 30-min buffer; per-session round-half-up hours via `Decimal`)
- `cascade.py` — churn/exit/terminate/cancel cascades, clock sweeps (credential expiry + auto-NO_SHOW)
- `serialize.py` — per-entity serializers; derived fields (`eligible`, `hours_contributed`, `recognition_tier`, counters) computed at read time as pure functions of state
- `routes_*.py` — 10 route modules (clock, territory, partners+volunteers, programs, agreements+evaluation, deliveries, sessions+substitute, kits, capstones, students)

**Verification**

- **Routes: 43/43** — enumerated `app.url_map` and matched every row of PRD §4 (scaffold header says 42 but its own table and the PRD both have 43 rows)
- **py_compile: OK** on all 17 `.py` files
- **Constant audit: OK** — AST walk confirms every UPPER_CASE symbol used in a file is defined/imported there; calc constants defined exactly once in `calc.py`
- **Smoke boot: performed** (dynamic port, killed exact PID). ~90 assertions passed covering: auth 401/403, territory cap, credential state machine + expiry arming (strictly-greater boundary verified: not expired at `expires_on`, expired 1s past), funding floor inclusive boundary, amendment cycle (propose/ratify/reject), RECORD_FUNDING ceiling, delivery OCC 412 + agreement version bump, `required_kits`=33 for 27×5 (per-session-ceil, not sum-then-round), cadence confirm/schedule, overlap 409 + back-to-back allowed, substitute OCC + delivery version +1, depart cascade (NEEDS_SUBSTITUTE + blocked-count version bumps), churn cascade (agreement→delivery→session cancel), capstone flow (CONFIRM capacity, ASSIGN_ROLES stamping 27 students, COMPLETE gate), RECONCILE_KITS inventory invariant, evaluation PROVISIONAL/FINAL numbers, funding-only BRONZE path, auto-NO_SHOW at >scheduled+7d (still deliverable at exactly +7d), pagination meta
- Two mid-smoke failures were both the subagent's script sequencing bugs (testing amendment from PROPOSED; hardcoded expiry date), plus one deliberate spec correction (see interpretations)

**Interpretations chosen**

1. **RATIFY_AMENDMENT dual failure**: when a pending pledge is both below the funding floor and below funds already received, report `ERR_FUNDING_EXCEEDS_PLEDGE` first — PRD says the cut-below-received case is "rejected with ERR_FUNDING_EXCEEDS_PLEDGE **instead**". Implemented exceeds-before-floor.
2. **Auto-NO_SHOW sweep is date-based**: `clock.date() > scheduled_date + 7 days`, complementary to the inclusive date-based delivery window (deliverable through +7d, swept from +8d). Expiry sweeps are datetime-exact (`now > expires_on`).
3. **Facility role catalog is undefined** in PRD/scaffold — ASSIGN_ROLES accepts any string `role`; coverage/uniqueness/rotation-group bounds still enforced as `ERR_ROLE_ASSIGNMENT_INVALID`.
4. **Version bumps**: resources start at `version=1`; `touch()` on every mutation including cascade-driven counter recomputes (blocked-count cascades bump delivery version exactly once per cascade wave; substitute bumps exactly once per PRD 2.6). Hour/tier recomputation on RECORD_DELIVERY does not bump agreement/volunteer versions (not in PRD's explicit bump list; those fields are read-time computed).
5. **RESCHEDULE re-runs only date/overlap/cadence** — per scaffold preconditions it does NOT re-check delivery==PLANNED or volunteer eligibility (this is what makes the NO_SHOW recovery path usable).
6. **Pagination violations** (`limit` non-int/<1/>100, `offset` non-int/<0) → `ERR_VALIDATION` 400; unknown query params ignored (least restrictive).
7. **`completion_rate_pct` is `null`** when the agreement has no deliveries (division by zero; mirrors `avg_growth_score`'s null rule). Denominator includes cancelled deliveries' session counts, per the literal formula.
8. **Program-catalog `code` uniqueness** has no catalog error id → `ERR_VALIDATION` 400.
9. **Explicit JSON `null`** for optional amendment fields is treated as absent.
10. **Timestamps** (`created_at`/`updated_at`, envelope `api_request_timestamp`, evaluation `generated_at`) are wall-clock UTC with 3 fractional digits; only business-date rules use the logical clock. Clock `current_utc` renders without fractional digits when zero (matching the PRD's default rendering).
11. **Delivery/agreement COMPLETE take the literal reading**: every session DELIVERED (a CANCELLED session blocks delivery COMPLETE — unlike agreement COMPLETE, which explicitly allows CANCELLED deliveries); a required-but-absent-or-cancelled capstone yields `ERR_CAPSTONE_REQUIRED`.
12. **WRITE_OFF quantity** allows 0 (PRD states the ≥1 bound only for ASSEMBLE); negative → `ERR_VALIDATION`.

No guards beyond the PRD were added; all 29 catalog errors are wired with their exact HTTP statuses, and the validation ladder order (auth → role → body shape → existence → OCC → state → eligibility → cross-entity gates → temporal → constraint → fiscal) is followed throughout.

Orchestrator verification: 19 files present on disk; `py_compile *.py` OK; `app.url_map` enumerated independently → **43 Flask routes**; `db.STORES` all empty at import (no seeding).

## Step 7: Run Tests and Iterate — 2026-10-01T15:05:00.000Z

Clean 8-round parallel sweep achieved on the first iteration — every round reports `passed == total` (79/79), and all 8 `results.${i}.json` artifacts remain on disk in `workspace/implementation/` as required.

Summary:
- **Iterations run:** 1 (single 8-round parallel sweep, all rounds green — no fixes needed).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** none.

The Step 5/6 artifacts (79 tests, 43-endpoint Flask implementation) were already consistent: no flakiness surfaced across the 8 concurrent rounds, and no PRD-coverage or unique-derivability violations required adjudication.

Orchestrator verification: read all 8 `results.{1..8}.json` files independently — every round reports `passed: 79, total: 79, failed: 0`. All 8 files remain on disk.

## Step 8: Finalize PRD — SKIPPED — 2026-10-01T15:06:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-10-01T16:16:00.000Z

All pins verified in place. The task is complete.

**File**: `workspace/PRD_COMPLETED.md` — 320 lines / 53,348 chars (source PRD.md: 316 lines / 49,158 chars; **+4 lines, +4,190 chars**, 23 inline edits, no new sections).

**Counts**: 21 ambiguity-pin edits (several pin multiple behaviors) + 3 mismatch-revisions (one defect pinned in two places, §2.7 + §3.3).

**Dead-code defects**: none. All 31 `ERR_*` ids are raised on a request path; all 23 calc/cascade helpers (incl. `run_sweeps`, `cadence_full_ok`, `facility_capacity_ok`, `inventory_for_delivery`, `exit_partner`, `churn_district`) have live callsites.

**All 12 recorded interpretation choices verified against code and pinned** (a–l). Note on (c): the impl accepts *any* string role including empty (`isinstance` check only, routes_capstones.py:124), and the PRD sentence claimed a facility role catalog — treated as a **mismatch** and revised. Note on (j): already matched PRD §2.5 (3-fractional-digit UTC timestamps), no edit needed.

### Change log

- §2.2 — insert — ambiguity — unexpected failures return the error envelope with `ERR_INTERNAL` at HTTP 500 — app.py:57-59
- §2.3 — revise — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION` 400; `created_at` ties break by insertion order; per-endpoint exact-match filter params enumerated (districts/schools/volunteers/agreements/deliveries/sessions/kits/capstones/students); unrecognized query params ignored; `has_more` ≡ `offset + page_size < total_count` — middleware.py:91-127, response.py:24-32
- §2.4 — revise — ambiguity — clock accepts any parseable ISO 8601 timestamp (naive read as UTC, no monotonicity check) — routes_clock.py:17-21, db.py:56-69
- §2.4 — revise — ambiguity — sweep order: credential expiries first, no-show second; credential expiry compares exact datetimes, auto-NO_SHOW compares calendar dates (flips on the 8th day after `scheduled_date`); a NEEDS_SUBSTITUTE→NO_SHOW flip bumps the delivery once per sweep — cascade.py:112-145
- §2.5 — revise — ambiguity — `version` starts at 1; cascades bump each affected resource once per wave; read-time derived fields (`hours_contributed`, `eligible`, `sponsor_volunteer_hours`, `recognition_tier`, `deliveries_completed_count`, session counters) never persist or bump host versions — db.py:88,95-98, serialize.py:62-133
- §2.7 — revise — **mismatch** — tier 11: within amendment ratification the pledge-ceiling check runs first; both failing reports `ERR_FUNDING_EXCEEDS_PLEDGE` — routes_agreements.py:159-164
- §2.8 — revise — ambiguity — unknown `/ja-programs` path → `ERR_NOT_FOUND` 404; wrong method → `ERR_NOT_FOUND` at 405; trailing slashes tolerated — app.py:40,49-55
- §3.1 — revise — ambiguity — `max_districts` must be a non-negative integer — routes_territory.py:29-30
- §3.1 — revise — ambiguity — empty `instructional_days` array accepted — routes_territory.py:128-130
- §3.2 — revise — ambiguity — partner-exit cascade bumps a delivery once *per departed volunteer* (shared delivery bumps twice) — cascade.py:100-109,14-27
- §3.2 — revise — ambiguity — TRAINING BEGIN from EXPIRED leaves `training_expires_on` untouched until COMPLETE re-arms it — routes_partners.py:148-152
- §3.3 — revise — ambiguity — `funding_pledged_cents` must be non-negative at creation — routes_agreements.py:35-36
- §3.3 — revise — ambiguity — explicit JSON null for amendment fields treated exactly as absent; proposed `new_funding_pledged_cents` must be non-negative — routes_agreements.py:87-106
- §3.3 — revise — **mismatch** — RATIFY_AMENDMENT evaluates pledge-below-received (`ERR_FUNDING_EXCEEDS_PLEDGE`) *before* the funding floor (`ERR_FUNDING_BELOW_FLOOR`) — routes_agreements.py:154-169
- §3.4 — revise — ambiguity — duplicate program `code` → `ERR_VALIDATION` 400; catalog scalar bounds pinned (`grade_band_low` ≥ 1, `minutes_per_session` ≥ 1, `min_students` ≥ 1, `max_students` ≥ min) — routes_programs.py:32-51
- §3.4 — revise — ambiguity — `enrolled_count` must be non-negative at delivery creation — routes_deliveries.py:40-41
- §3.4 — revise — ambiguity — delivery COMPLETE is blocked by *any* non-DELIVERED session incl. CANCELLED/NO_SHOW; absent or non-COMPLETED capstone both report `ERR_CAPSTONE_REQUIRED` — routes_deliveries.py:196-210
- §3.5 — revise — ambiguity — RESCHEDULE re-runs *only* date/overlap/cadence with the session itself excluded; delivery status and volunteer eligibility are not re-checked — routes_sessions.py:156-174
- §3.6 — revise — ambiguity — WRITE_OFF allows quantity 0; negative → `ERR_VALIDATION` — routes_kits.py:82-85
- §3.7 — revise — **mismatch** (+ambiguity) — `role` is a free-form string, no facility role catalog exists (PRD previously required catalog membership); assignment `student_id`s validated for existence → `ERR_NOT_FOUND` before the 422 checks — routes_capstones.py:114-125,147-149
- §3.8 — revise — ambiguity — survey `score` must be an integer (non-integers → `ERR_VALIDATION`) — routes_students.py:91,111-114
- §3.8 — revise — ambiguity — invalid `variant` query value → `ERR_VALIDATION` — routes_agreements.py:209-211
- §3.8 — revise — ambiguity — `completion_rate_pct` denominator sums `session_count` over all deliveries incl. CANCELLED; null when the agreement has no deliveries — calc.py:270-280

Orchestrator verification: `PRD_COMPLETED.md` exists at 320 lines / 53,348 chars (matches report exactly); `diff -q` confirms it differs from PRD.md (not a killed-mid-flight byte-identical copy); **no `.py` source file in `implementation/` is newer than the newest sweep results file** — Step 9 did not touch the implementation, so the Step 7 sweep remains valid; all 8 `results.{1..8}.json` files still on disk; dead-code spot-check corroborated (`cadence_full_ok`, `facility_capacity_ok`, `inventory_for_delivery`, `exit_partner`, `churn_district`, `run_sweeps` all have ≥1 live callsite).
