# Worklog — task_3130_source_plasma_donation_center_donor_qualification_compensation

## Step 1: Create Task Directory — 2026-09-30T01:43:00.000Z

Pre-allocated task directory `./tasks/task_3130_source_plasma_donation_center_donor_qualification_compensation/` (with `workspace/` inside) verified to exist; used as-is per orchestration args. No new index computed, no other task_* directory created.


## Step 2: Generate Scaffold (redo) — 2026-09-30T02:20:32.000Z

Previous run was interrupted: SCAFFOLD.yaml existed (85.8KB, valid YAML) but worklog had no Step 2 entry and the DIFFICULTY/CORNER design files were missing. Deleted the orphan SCAFFOLD.yaml; regenerating all three scaffold artifacts from scratch via subagent.

## Step 2: Generate Scaffold (resume) — 2026-09-30T03:38:27.218769226Z

Resumed after second interruption. SCAFFOLD.yaml found complete on disk (96633 bytes, 1728 lines, valid YAML, all sections §1.0–§1.7 present, no forbidden top-level keys, clean ending) — kept as-is. SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml missing (subagent was interrupted after writing SCAFFOLD.yaml but before writing the design files). Spawning a subagent to generate the two design files from the existing SCAFFOLD.yaml.

## Step 2: Generate Scaffold — DESIGN FILES COMPLETE — 2026-09-30T03:38:00.000Z

Both design files are complete and verified. SCAFFOLD.yaml was not modified (96633 bytes, untouched).

**Files written** (both parse as valid YAML with the required single top-level key):
1. SCAFFOLD_DIFFICULTY_DESIGN.yaml — 200,527 bytes, top-level key `scaffold_difficulty_design`
2. SCAFFOLD_CORNER_DESIGN.yaml — 226,577 bytes, top-level key `scaffold_corner_design`

**§1.8 difficulty design — 27 instances (3 per rule, exceeding the ≥2/rule minimum per the "much harder than expert" instruction):**
- `dual_variant_calc`: 3 (promo optimistic-vs-pessimistic 4500→0 on abort; plasma-volume snapshot 690 vs live 825 after re-weigh; base-rate provisional 3000 vs final 2500 via cross-visit interleave)
- `combinatorial_formula`: 3, one per mode — (a) tiered monthly ordinal 3000/2500/2000, (b) abort payout multiply→floor→min-floor (869 and 500), (c) promo once-per-schedule resolved by completion order
- `non_linear_state_machine`: 3 cycles on different entities (DonationUnit QUARANTINED→RELEASED→LOOKBACK_HOLD→RELEASED; Donor APPLICANT→DEFERRED_TEMP→APPLICANT; PlasmaCenter OPERATIONAL↔INSPECTION_HOLD with cascades)
- `transitive_cascade`: 3 (depth-3 severe-reaction→deferral→NO_SHOW; depth-4 reactive-marker→FAILED→case→unit holds→UNITS_QUARANTINED; depth-3 resolve-DESTROY→claw-back→ytd 5500→0)
- `priority_pair_validation_conflict`: 3 distinct category pairs (state/fiscal, safety/referential, state/safety)
- `boundary_precision_check`: 3 distinct metrics on distinct endpoints (weight band 67.9/68.0 at check-in; 14:59 vs 15:00 dwell at discharge; volume 0/691/690 at complete-collection)
- `cross_entity_state_dependency`: 3 pairs (Unit→Donor, Visit→Center, Unit→LookBackCase)
- `resource_temporal_overlap`: 3 (bed aggregate capacity + min-free reuse; lane half-open interval adjacency at exactly +24h; chair aggregate capacity)
- `compensating_invariant`: 3 quantities (ytd money conservation with sticky-1099 carve-out; capacity slot conservation; unit cardinality across decommission)

**§1.9 corner design — 76 instances (64 active + 12 `excluded_because` stubs, all stubs citing existing §1.8 instance names):** entities 12, state_machines 23, calculations 8 (incl. 180-day inclusive-edge qualification/window-restart and ytd year-scoping), validations 7, endpoints 3, errors 10 (mostly stubs + envelope shape), rbac 5, cross_cutting_complexity_layers 7 (incl. all three OCC stale-version rules), consistency_model 1.

**Verification performed:**
- Both files parse via `yaml.safe_load`; required single top-level keys confirmed.
- Independent checker: zero unresolved `grounds` references (calculations, state-machine transitions, entity fields, validation priorities, error ids, roles, concurrency rule ids, endpoint method+path all resolve against SCAFFOLD.yaml); zero name duplicates across the union of both files; stubs carry no `test_recipe` and cite real difficulty instances.
- `scaffold_lint.py`: **zero violations of checks (a)–(e)** across 1,539 calls (endpoints, roles, payload shapes, captures, OCC `${var}` discipline all conform). The 24 remaining findings are all check (f) `FK_REVERSE_UNREACHABLE`, a scaffold-level artifact not fixable without modifying SCAFFOLD.yaml: §1.5 *does* declare reverse-lookup GETs for every FK, but the linter's `derive_entity_collection_segments` only recognizes single-resource GETs shaped `<api_prefix>/<segment>/{id}`, and §1.5's paths omit the `/plasma-centers` prefix, so zero collection segments are derived and every FK is flagged structurally.

**Scaffold observations noted for downstream stages (not modified):** three catalog errors are shadowed/unreachable under the scaffold's own priority ordering — `ERR_DONOR_DEFERRED` (p9 always preceded by p8 donor-status gate), `ERR_ACTIVE_DEFERRAL_EXISTS` (an ACTIVE entry implies DEFERRED_*, which hits `ERR_DONOR_NOT_DEFERRABLE` first), and `ERR_SCREENING_NOT_PASSABLE` (any FAIL sub-record auto-flips the visit to FAILED, so clear fails with `ERR_VISIT_NOT_IN_PROGRESS` first). No corner instances were written asserting these, to avoid broken fixtures.

## Step 3: Copy Shared Files — 2026-09-30T05:08:57.781005829Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-30T05:15:00.000Z

**Summary**

- **Output**: `tasks/task_3130_source_plasma_donation_center_donor_qualification_compensation/workspace/PRD.md`
- **Size**: 364 lines, ~8,001 words
- **Section structure**:
  - §1 Introduction (3 paragraphs)
  - §2 Global Specifications — 12 subsections: 2.1 RBAC + role identity, 2.2 Response envelope (verbatim), 2.3 Pagination, 2.4 Logical clock, 2.5 Common resource properties, 2.6 Monetary precision, 2.7 OCC, 2.8 Nested resource retrieval, 2.9 Validation priority, 2.10 Center lifecycle, 2.11 Capacity accounting & snapshots, 2.12 Deterministic slot assignment
  - §3 Business Logic — 11 subsections covering center onboarding, donor registration, screening lifecycle, donation check-in, collection/observation/discharge, units & look-back, qualification & applicant window, compensation computation, adverse reactions, deferral registry, inspection holds & decommission
  - §4 Endpoint table (40 rows, 4 columns)
  - §5 Error catalogue (37 rows, 2 columns)
- **Coverage audit**:
  - Contract 1 (field names): 95/95 present, 0 missing — PASS
  - Contract 2 (rule coverage): all 22 validations with priority ordering expressed in §2.9; all 3 OCC rules with write endpoint + expected_*_version + `ERR_STALE_VERSION`/412 named; all 32 state-machine transitions with preconditions and side effects; all 11 calculations expressed in prose with constants, precision, and variants; all 37 error IDs reachable in narrative; all 5 roles spelled exactly; all 27 state values present — PASS
  - Contract 3 (§3 path purity): 563 backticked tokens scanned, 0 path/method violations — PASS

Manual spot-check by the subagent: OCC rules (3) covered in §2.7 with `expected_center_version` / `expected_schedule_version`, `ERR_STALE_VERSION` 412; all 11 calculations covered with constants/precision/variants; all 22 validation priorities enumerated in §2.9; all state machine transitions covered in §2.10/§3.1/§3.3–§3.11; cascades for inspection hold, decommission, deferral, look-back, qualification, discharge, abort all enumerated.

## Step 5: Generate Unit Tests — 2026-09-30T06:05:00.000Z

**Files written**

`test_helpers/` (9 files):
- `types.py` — status enums (center/donor/screening/donation/unit/schedule/payment/registry/case/severity), role enum, TypedDicts for all 12 entities
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (including `/_clock/set_current_utc`)
- `api_errors.py` — all 38 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py` (bands 625/690/825/880, 500-cent abort floor, 60000 tax threshold, 7d/2 freq window, 48h gap, 180d windows, 15min observation, 24h/6h expiries)
- `test_users.py` — shared role headers (all roles are opaque per PRD §2.1) plus per-id builders for SoD scenarios
- `fixtures.py` — composite helpers: `make_center_with_schedule`, `make_cleared_screening`, `run_completed_donation`, `setup_qualified_donor_with_released_units`, `setup_lookback_case_ready`, plus getters/listers using `get_success_data`/`validate_paginated`
- `__init__.py` — barrel export

`test_suite/` (8 files): `conftest.py` + 7 test files.

**Coverage**

- 119 tests total: 54 queue A (Difficulty), 65 queue B (Corner).
- All 27 difficulty instances have exactly 2 tests each.
- All 63 non-stub corner instances covered except one skipped (below); all 12 `excluded_because:` stubs left untranslated, with their `difficulty_instance` pointers verified to resolve.
- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line copied verbatim from the YAML; an automated audit confirmed every tag resolves to a real instance and every quoted PRD sentence (≥8 words) greps verbatim in `workspace/PRD.md`.
- Suite compiles and `pytest --collect-only` collects all 119 tests cleanly.

**Skipped instance (PRD-first two-condition filter)**

- `Corner/entities/donor_create_computed_field_input_ignored` — skipped: the PRD never states that client-supplied `ytd_compensation_cents` / `lifetime_donation_count` / `donor_status` in a create payload are ignored rather than rejected; a PRD-only implementer could legitimately return 400, so the asserted outcome is not uniquely derivable.

One deliberate derivation note: `lookback_release_resolution_requires_qualified_donor` was driven with the donor in `DEFERRED_TEMP` (via a temporary deferral filed after the case opened) instead of APPLICANT as in the YAML recipe — the YAML's own setup would have the donor promoted to QUALIFIED by its second completion (an in-PRECONDITION contradiction), while the asserted rule (non-QUALIFIED donor → `ERR_DONOR_NOT_QUALIFIED`; then DESTROY succeeds and ytd claws back to 0) is exactly what the PRD states.

## Step 6: Generate Implementation — 2026-09-30T07:00:00.000Z

Implementation complete. Summary:

## Files written (all under `workspace/implementation/`)

- `start.sh` — executable launcher; guards `pip install` behind an `import flask` check, then `exec python3 app.py` (foreground, `$PORT` default 10000, binds `0.0.0.0`)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app, blueprint registration, error handlers (ApiError, 404/405, fallback)
- `db.py` — in-memory dict store (12 collections, starts empty, zero seeding), sequential ids, logical clock defaulting to `2026-09-01T00:00:00Z`, ISO-8601 UTC 3-fractional-digit timestamp helpers
- `errors.py` — all 34 scaffold error IDs with exact HTTP statuses
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta with `limit`/`offset`/`total_count`/`has_more`), pagination parsing (default 10, bounds [1,100])
- `middleware.py` — `X-User-ID`/`X-User-Role` validation and role gating
- `services.py` — serializers, capacity snapshots, lowest-free slot assignment (beds/chairs/lanes), plasma-volume bands (625/690/825/880), sub-record outcome rules, base/promo/abort compensation, YTD accumulator with sticky `requires_1099`, all cascades (qualification release, look-back sweep, deferral cascades, severe-reaction auto-deferral), chronological scheduled transitions (screening 24h expiry, donation 6h no-show, deferral auto-clear)
- `routes_centers.py`, `routes_donors.py`, `routes_screenings.py`, `routes_donations.py` — all endpoints

## Endpoint count
All 36 endpoints from the SCAFFOLD §1.5 table implemented (clock set, 6 center, 4 schedule, 4 donor, 3 deferral, 6 screening, 7 donation-visit, 3 unit, 3 look-back, 2 payment reads).

## Verification performed
- Booted via `bash start.sh` on free ports (18990–18992) and smoke-tested end-to-end (killed only PIDs the subagent started, via `ss -tlnp` PID lookup — no broad kills).
- Two smoke suites (~75 assertions) pass from a fresh boot: full happy path (center→schedule→donor→screening→4 sub-records→SoD→clear→donation→check-in→collection→15-min dwell→discharge→unit→finalized payment), OCC 412s, duplicate donor/underage 400/409, promo payout on 2nd donation (ytd 11000), qualification cascade releasing units, rolling frequency cap, auto NO_SHOW, abort compensation (0 with no volume; floor(3000×200/825)=727 from OBSERVATION with unit creation), severe→auto-deferral→auto-clear at +7d, viral-marker look-back (3 units held → DESTROY resolve → 3 claw-backs → ytd 0), inspection-hold cascade (SCHEDULED→NO_SHOW, pipeline writes blocked), deferral filing/uniqueness/override/permanent-deferral cascades.
- Fresh-boot contract verified: empty store, default clock `2026-09-01T00:00:00.000Z`, 400/403 auth behavior, envelope-shaped 404.

## PRD ambiguities resolved
1. **FINAL-variant base ordinal**: computed as prior in-month completions *excluding* the completing visit (PRD §3.8: "the final ordinal of the just-completed visit equals the number of PRIOR completions"), so provisional/final match absent a cross-visit race.
2. **`ERR_DONOR_UNDERWEIGHT` (422)**: raised as an HTTP error at PHYSICAL_EXAM write time (per PRD §3.3 "which surfaces as ERR_DONOR_UNDERWEIGHT"), not stored as a FAIL row.
3. **Screening-lane exhaustion**: lanes wrap to index 0 when all occupied (PRD §2.11 says screening admission is never gated; assignment is best-effort lowest-free).
4. **Deferral-uniqueness vs. status precedence**: donor-status check (`ERR_DONOR_NOT_DEFERRABLE`) precedes the active-entry check (`ERR_ACTIVE_DEFERRAL_EXISTS`), matching PRD §3.10 prose order.
5. **Hold/decommission/abort/discharge gating**: applied `ERR_CENTER_NOT_OPERATIONAL` to all visit-pipeline writes per PRD §3.11; reads and clock set remain ungated.
6. **Auto-filed severe-reaction deferral** uses `filed_by_user_id: "system"` and the visit's center as `source_center_id` (no human actor exists for a system cascade).
7. `GET /donation-visits/{id}/compensation-payment` returns an array envelope (0 or 1 items) per the scaffold's `CompensationPayment[]` output.

## Step 7: Run Tests and Iterate — PASS — 2026-09-30T07:30:00.000Z

All 8 rounds pass 118/118 (119 − 1 deleted). Clean sweep.

## Summary

**Iterations run:** 2 (first sweep: 21 unique failures × 8 rounds; second sweep: all 118 tests green in all 8 rounds).

**Tests deleted (1):**
- `test_suite/test_03_donation_pipeline.py::test_screening_consumed_by_second_donation_rejected` — unique-derivability collapse (scaffold "consumed-pending" rule). The corner design claimed a CLEARED screening referenced by any existing DonationVisit is "consumed-pending" and a second schedule must fail with `ERR_SCREENING_NOT_CLEARED`. But PRD §3.4 verbatim defines consumption as "consumed by any other DonationVisit that is `IN_PROGRESS` or `COMPLETED`". The test never checked in the first donation, so a faithful PRD-only implementation (as the reference implementation did) returns 201 — the asserted 409 is not derivable from PRD prose.

**Fixes applied to `test_suite/` (4 groups):**
- `test_04_compensation.py` + `test_07_capacity_boundaries_endpoints.py` — 6 abort/reaction call sites passed `observed_at` 5–15 minutes in the future relative to the logical clock, violating PRD §3.9 ("an `observed_at` timestamp that must not be later than the logical clock now"); the PRD-faithful implementation correctly returned 400 `ERR_INVALID_REQUEST`. Changed to the current clock instant (`09:30:00Z` / `09-04T09:30:00Z`).
- `test_04_compensation.py::_setup_three_completions` — third completion moved from 2026-09-08 to 2026-09-17 so the three September completions (09-01, 09-04, 09-17) each clear the rolling 7-day frequency cap (PRD §3.4: ≥2 completions in trailing 7 days rejects check-in); the original 09-01/09-04/09-08 plan is physically impossible under the PRD. Tiered-ordinal assertions (3000/2500/2000, ytd 7500, QUALIFIED) unchanged and still exercised.
- `test_05_lookback_deferral_qualification.py` (both reactive-marker tests and `_case_open_with_post_case_quarantined_unit`) — same frequency-cap setup bug: dv3 completion moved 09-08 → 09-12, dependent screening/case dates shifted 09-09 → 09-13, post-case fourth donation moved 09-12 → 09-20 (keeps ≥7-day spacing, >48h gaps, same-month ordinals, and 180-day look-back window intact).
- `test_06_center_lifecycle_occ.py::_qualified_donor_plus_quarantined_unit` — same fix: dv3 completion moved 09-08 → 09-12.
- `test_05_lookback_deferral_qualification.py::test_severe_reaction_cascades_other_scheduled_visit_to_no_show` — assertion compared `scheduled_for` to the exact client-sent string `"...10:30:00Z"`; the server normalizes timestamps to the three-fractional-digit form (`"...10:30:00.000Z"`) used throughout the API, and PRD does not pin echo format for client-supplied timestamps, so the exact-input-echo assertion was not uniquely derivable. Assertion now compares against the normalized form, still proving "scheduled_for is left unchanged" by the cascade.

**Fixes applied to `implementation/` (3):**
- `db.py::next_id` — PRD §2.5 requires "`id` (string). A server-minted UUID. Identifiers carry no type prefix."; the store was minting sequential integers (`"1"`, `"2"`, …). Now returns `str(uuid.uuid4())`.
- `routes_donations.py` (check-in inter-donation-gap tie-break) and `routes_centers.py` (capacity-snapshot listing) — removed `int(id)` ordering assumptions that would crash on UUID ids; replaced with PRD-conformant ordering (`collected_at` latest, tie-broken by `created_at` ascending per PRD §3.4; snapshots newest-first with `created_at`/`id` tie-break).
- `routes_screenings.py::clear_screening` — reordered clearance preconditions to match PRD §3.3's stated condition order: completeness (`ERR_INCOMPLETE_SCREENING` 409) and passability (`ERR_SCREENING_NOT_PASSABLE` 409) are now evaluated before the segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES` 403); previously SoD fired first, producing the wrong error id and wrong HTTP status (403 vs 409) when both conditions failed.

## Step 8: Finalize PRD — 2026-09-30T07:45:00.000Z

PRD.md vs PRD_FINALIZED.md: 364 → 366 lines (+2 lines, +0.55%; three in-place paragraph edits, no new sections).

**Changes (3 edits):**

- §2.4 — revise — added a sentence pinning that client-supplied datetimes the server persists (`scheduled_for`, `observed_at`, deferral `deferral_ends_on`, schedule `effective_from`/`effective_to`, clock `current_utc`) are stored and returned in the server's canonical 3-fractional-digit UTC form, not echoed verbatim — implementation: routes_screenings.py:36, routes_donations.py:57,339, routes_donors.py:135, routes_centers.py:41,252-253 (all normalize via `db.ts()`).
- §2.11 — insert — new paragraph pinning the capacity-snapshot list ordering: newest-first by `snapshot_at` descending, ties broken by `id` descending, explicitly an exception to §2.3's ascending `created_at` default — implementation: routes_centers.py:196 (`sort(key=(snapshot_at, created_at, id), reverse=True)`; `snapshot_at == created_at` for every snapshot, services.py:372,379).
- §3.3 — revise — rewrote the clearance paragraph to state the actual fixed precondition order (visit state → center operational → donor eligible with `ERR_DONOR_NOT_ELIGIBLE` 409 → completeness 409 → passability 409 → segregation-of-duties 403), replacing the old prose whose listed order and vague "order laid out in §2.9" claim mis-described the implementation; the replacement notes §2.9 does not enumerate the screening-internal checks and that completeness beats SoD — implementation: routes_screenings.py:175-194.

**Step-7 items requiring no PRD edit (PRD already determined behavior or pure fixture bugs):** deleted consumed-pending test (PRD §3.4 verbatim matches services.py:552-562); future `observed_at` rejections (PRD §3.9 already pins); frequency-cap fixture date moves (PRD §3.4 already pins the rolling 7-day window); UUID ids (PRD §2.5 already pins; impl was fixed to match); check-in gap tie-break (impl now matches PRD §3.4 verbatim; impl's extra `id` tie-break at routes_donations.py:141 is behaviorally inert since tied `collected_at` yields identical gap verdicts, so left unpinned).

**Per-edit pre-edit search log:**

1. **§2.4 timestamp normalization** — (a) subject: storage/echo format of client-supplied datetimes. (b) enumerated: grep of `parse_dt`/`db.ts(` across routes_screenings.py, routes_donations.py, routes_donors.py, routes_centers.py — all client-supplied datetime fields (`scheduled_for` on screening + donation, `observed_at`, `deferral_ends_on`, `effective_from`/`effective_to`, clock `current_utc`) go through `parse_dt` then `db.ts()`; `date_of_birth` is a date, not a datetime, and is excluded from the wording. (c) wording scoped to exactly the five persisted client-datetime fields; the NO_SHOW cascade's "scheduled_for left unchanged" (§3.5/§3.11) remains consistent since the stored value is the normalized one.
2. **§2.11 snapshot ordering** — (a) subject: capacity-snapshot list ordering. (b) enumerated: only consumer is `GET /plasma-centers/{id}/capacity-snapshots` (routes_centers.py:187-198); `write_snapshot` (services.py:348-381) only appends and stamps `snapshot_at`/`created_at` from the same instant. (c) added the explicit §2.3-exception clause because §2.3's default (ascending `created_at`) would otherwise contradict "newest first"; tie-break stated as `id` descending to match the reverse sort.
3. **§3.3 clearance order** — (a) subject: screening-clearance precondition evaluation order and error ids. (b) enumerated: sole clearance path `clear_screening` (routes_screenings.py:170-198); all `err_donor_not_eligible` raise sites (routes_screenings.py:30,182; routes_donations.py:43,117 — uniform `ERR_DONOR_NOT_ELIGIBLE`, no `ERR_DONOR_NOT_SCREENABLE` exists in errors.py); §2.9 items 7/8/10 (center < donor < SoD) — consistent with the new wording; test_suite/test_02_screening_lifecycle.py:255-299 confirms completeness-beats-SoD (409 not 403). (c) replaced "`ERR_DONOR_NOT_SCREENABLE` ... error family" with the concrete `ERR_DONOR_NOT_ELIGIBLE` (HTTP 409), and replaced the false "evaluated in the order laid out in §2.9" claim with a "refines §2.9" sentence covering the checks §2.9 does not enumerate.

## Step 9: Complete PRD — 2026-09-30T08:10:00.000Z

- Source: `PRD_FINALIZED.md` (366 lines / 61,364 chars) → `PRD_COMPLETED.md` (368 lines / 66,691 chars), +2 lines / +5,327 chars. All changes are in-paragraph inserts/revisions; no new sections.

- Counts: 13 ambiguity-pins, 4 mismatch-revisions (§2.7 count, §2.11 tie-break, §2.12 lane rule, §3.10 cascade scope + source_center_id count as 2 mismatch bullets).

- Changes (PRD section — insert|revise — ambiguity|mismatch — what — impl reference):
  - §2.3 Pagination — insert — ambiguity — pin limit/offset validation errors (`ERR_INVALID_REQUEST` for non-integer, out-of-range limit, negative offset) and `total_count`/`has_more` definitions — implementation/response.py:57-79
  - §2.4 Logical clock — insert — ambiguity — pin UTC normalization of client datetimes, naive-as-UTC interpretation, millisecond truncation — implementation/db.py:47-74
  - §2.7 OCC — revise — mismatch — "Three write operations" → "Five" and enumerate all five (schedule create, hold, retire, hold-clear, decommission) — implementation/routes_centers.py:113,138,157,231,297
  - §2.10 Center lifecycle — insert — ambiguity — pin create-time field validations (non-empty strings, two-char state_code, int-not-bool capacities) and duplicate `center_code` → `ERR_INVALID_REQUEST` — implementation/routes_centers.py:51-68
  - §2.11 Capacity accounting — insert — ambiguity — pin half-open lane interval bounds (inclusive at `scheduled_for`, exclusive at +24h) — implementation/services.py:355
  - §2.11 Snapshot ordering — revise — mismatch — tie-break changed from `id` descending to `created_at` descending then `id` descending — implementation/routes_centers.py:196
  - §2.12 Lane assignment — revise — mismatch — replaced overlap/`created_at` tie-break description with lowest-free-lane that wraps to index 0 when all lanes occupied — implementation/services.py:424-436
  - §3.1 Schedule creation — insert — ambiguity — pin type validation for `effective_from`/`effective_to`, base amounts, promo fields — implementation/routes_centers.py:209-233
  - §3.2 Donor registration — insert — ambiguity — pin field type checks, age-18 evaluated against logical clock, Feb-29→Feb-28 substitution — implementation/routes_donors.py:29-56
  - §3.3 Sub-record write — insert — ambiguity — pin state gate (only SCHEDULED/IN_PROGRESS accept writes; else `ERR_INVALID_STATE`), record_type enum validation, per-type payload shape/type validation — implementation/routes_screenings.py:84-98, services.py:485-546
  - §3.3 First-write expiry — insert — ambiguity — a post-expiry first write still expires the visit (snapshot `screening.expired`) and is rejected with `ERR_INVALID_STATE` — implementation/routes_screenings.py:103-109
  - §3.4 Donation scheduling — insert — ambiguity — pin body field validation and the impl's evaluation order (center OPERATIONAL → donor eligibility → screening integrity → center match) — implementation/routes_donations.py:22-51
  - §3.6 Manual release — insert — ambiguity — pin center-must-be-OPERATIONAL gate at release — implementation/routes_donations.py:444-446
  - §3.7 Applicant window — insert — ambiguity — note the anchor re-stamp on any late completion while APPLICANT (covers lifetime count ≥ 3 lapses) — implementation/routes_donations.py:277-288
  - §3.8 Abort compensation — insert — ambiguity — abort finalize also stamps `variant_switched_at`/`payment_issued_on` from the logical clock and accumulates the abort net into `ytd_compensation_cents` — implementation/routes_donations.py:361-370
  - §3.9 Adverse reaction — insert — ambiguity — pin `ERR_INVALID_REQUEST` for bad severity/reaction_code/observed_at/notes and future `observed_at` — implementation/routes_donations.py:310-331
  - §3.10 Deferral filing — insert — ambiguity — pin reason_code/type/ends_on body validation; PERMANENT stores `deferral_ends_on` null — implementation/routes_donors.py:120-137
  - §3.10 Deferral cascades — revise — mismatch — SCHEDULED→NO_SHOW cascade applies only to TEMPORARY filings; permanent filings leave scheduled visits untouched; `source_center_id` is the donor's `home_center_id` — implementation/routes_donors.py:149,167-180
  - §3.10 Temporary auto-clear — insert — ambiguity — donor status recompute only when donor still `DEFERRED_TEMP` — implementation/services.py:930-933
  - §3.11 Inspection hold — insert — ambiguity — optional `reason` must be a string — implementation/routes_centers.py:116-118
  - §4 Endpoints — insert — ambiguity — clock-set returns 200; deferral filing is 201; pin visit-payment endpoint's array `meta` (`offset` 0, `total_count` 0/1, `limit` = items returned or 10) — implementation/routes_centers.py:41, routes_donations.py:395-404

Output file: `workspace/PRD_COMPLETED.md`

## Final verification sweep — 2026-09-30T07:20:24.301318922Z

Post-Step-9 confirmation: 2 additional prd-bench-local-run rounds against the final artifact state (test_suite + implementation unchanged since Step 7's clean 8-round sweep; Steps 8/9 touched only PRD documents). Both rounds: 118/118 passed, 0 failed, 0 errors, 0 skipped. Pipeline complete.

## Final artifact inventory
- SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, 27 instances), SCAFFOLD_CORNER_DESIGN.yaml (§1.9, 76 instances)
- test_helpers/ (9 files), test_suite/ (8 files, 118 tests: 54 Difficulty + 64 Corner)
- workspace/INSTRUCTION.md, PRD.md (364 lines), PRD_FINALIZED.md (366 lines), PRD_COMPLETED.md (368 lines)
- workspace/implementation/ (Python+Flask, in-memory store, 36 endpoints, start.sh launcher)
