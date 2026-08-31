# Worklog — task_2164_cert_training_program

## Step 1: Create task directory — 2026-08-28T00:00:00.000Z

Created `tasks/task_2164_cert_training_program/` and `tasks/task_2164_cert_training_program/workspace/`. Index 2164 chosen as max existing index (2163) + 1.

## Step 3: Copy INSTRUCTION.md — 2026-08-28T09:25:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2164_cert_training_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-08-28T10:18:00.000Z

All three scaffold artifacts are generated and lint-clean.

## Files written to `/home/ubuntu/github/CodingPRD/tasks/task_2164_cert_training_program/`

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 2262 | §1.0–§1.7 + preamble (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1380 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2468 | `scaffold_corner_design` only |

## Complexity profile (deliberately beyond the Expert band)
- **Archetypes**: `compliance_audit` + `quota_allocation`; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy
- **Topology `graph`** (3 junction entities, self-referential `CurriculumModule.prerequisite_module_id`, 4-way cross-aggregate `ClassSession`), **shape `cyclic`**, **role model `segregation_of_duties`**, consistency `immediate`
- `api_prefix: "/"` (flat/graph paths, no shared prefix — required for the lint's FK reverse-reachability check)

## Surface
- **15 entities**: Program, Cohort, CurriculumModule, Facility, Instructor, ClassSession, Trainee, ModuleCompletion, Credential, EquipmentAsset, EquipmentIssuance, Exercise, ExerciseParticipation, Activation, RosterAssignment
- **11 state machines**, incl. **two parallel dimensions on the same Trainee row** (`enrollment_status` × `currency_status`), a **cyclic Credential** (ACTIVE→GRACE→EXPIRED→ACTIVE and ACTIVE→SUSPENDED→ACTIVE), a bounded ModuleCompletion retake loop, and a Cohort GRADUATION_REVIEW→IN_SESSION revert
- **8 calculations**: `trainee_readiness_score` (dual-variant, weighted, tiered recency + min/max clamps), `equipment_loss_settlement` (dual-variant + pinned round-per-line-then-sum), `credential_renewal_terms` (circular-looking, pinned evaluation order, tier read pre-increment), `refresher_currency_hours`, `activation_roster_selection` (waterfall + full selector determinism), `equipment_issuance_selection`, `exercise_hours_credit`, `instructor_daily_contact_load`
- **40 ordered validations**, **60 endpoints** (incl. `/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default and `/_ops/run-currency-sweep`), **54 error codes**, **7 roles** (2 entity-backed to `Instructor`, 1 to `Trainee`, 4 opaque), **2 OCC concurrency rules** (Program, Activation)

## Difficulty & corner design
- **§1.8: 24 instances** across all 9 rule_ids (2–3 each). Two 5–6-hop cascades from *different* triggers, three validation-priority pairs (state↔fiscal, safety↔referential, temporal↔constraint), two overlap rules with genuinely different interval geometry (facility 30-min buffer where adjacency *collides* vs instructor unbuffered where adjacency *is legal* + aggregate per-UTC-day cap), three conserved quantities (cents / seat headcount / contact hours). All formula-derived asserts are pre-computed literals (e.g. 65.20 vs 76.60, 17435+8176=25611 vs 25610, 26000 vs 25735, expires_on 2028-06-15).
- **§1.9: 72 instances** (55 with recipes + 17 `excluded_because` stubs) across all 9 guide sections.
- **96 unique instance names**; a placeholder-closure audit found **zero** unbound `${var}`, zero duplicate captures, zero empty chains, and all stub `difficulty_instance` refs resolve. A grounds-resolvability audit found **zero** dangling refs.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     15
  §1.8 instances scanned:     24
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  1853

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two §1.5 endpoints were added mid-generation via the priority ladder because corner instances proved a gap: `PATCH /curriculum-modules/{moduleId}` (without it `ERR_CURRICULUM_CYCLE` was untriggerable — creates alone can never close a cycle) and eight single-resource GETs required to make every FK reverse-reachable. The hard constraint held: no sibling task directory was listed, read, or grepped.

## Step 4: Generate PRD — 2026-08-28T10:28:00.000Z

PRD generated at `workspace/PRD.md` — **408 lines / 88,173 bytes**, built with 8 incremental appends (no single oversized write).

## Structure
- **§1 Introduction** — 3 paragraphs (domain pain points, seven constituencies, three design properties).
- **§2 (10 subsections)** — 2.1 RBAC (all 7 roles + every `identity:` translated: 3 entity-backed, 4 opaque), 2.2 verbatim response envelope (byte-identical to `section-2.2-response-structure.md`, verified), 2.3 pagination, 2.4 identity/timestamps/logical clock (`2026-08-01T00:00:00Z` default), 2.5 nested-path + body-FK resolution, 2.6 the full 16-step evaluation ladder covering all 40 validation priorities, 2.7 the two SoD walls, 2.8 OCC, 2.9 precision/conserved ledgers, 2.10 cascade discipline + the two parallel `Trainee` dimensions.
- **§3 (9 subsections)** — program/curriculum/facilities/instructors; cohort seat ledger + waitlist selector; scheduling & delivery (both overlap geometries, daily load cap); attendance/skills-demo/retake loop/void cascade A; graduation & credential mint; currency, refresher hours & renewal terms; equipment issuance/return/loss settlement; exercises & AAR; activation roster + dual-variant readiness score.
- **§4** — 60-endpoint table (4 columns); **§5** — 54-error table (2 columns). Document ends at §5, no audit footer.

## Hard contract reports
```
Field coverage check:
- entities[].fields: 102 required, 102 present, 0 missing
- endpoints[].request_body: 73 required, 73 present, 0 missing
- endpoints[].query_params: 20 required, 20 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 40 checked, 40 expressed in prose (§2.6 ladder + local trigger prose), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (operation + expected_program_version / expected_activation_version + ERR_STALE_PROGRAM_VERSION / ERR_STALE_ACTIVATION_VERSION + 412), 0 missing
- state_machines[].transitions: 70 checked, 70 fully expressed (11 machines incl. both Trainee dimensions, cyclic Credential, bounded retake loop, GRADUATION_REVIEW revert), 0 missing
- calculations[]: 8 checked, 8 fully expressed with pinned evaluation order and all constants embedded, 0 missing
- validations[] conditions: 40 checked, 40 matchable to error_id in §2/§3 prose (all 54 error ids appear outside §5), 0 missing
- endpoints[].side_effects / applies_to: 32 endpoints with side effects + all applies_to sets enumerated, 0 missing
- entities[].fields[] structured content: 132 field entries checked (defaults, initial values, enum sets, derivations), 0 missing
- sibling-branch symmetry: 9 groups checked (3 renewal edges, 4 void edges, 4 revoke edges, 2 cohort-cancel edges, 2 exercise-cancel edges, 2 settlement variants, 2 readiness variants, 2 overlap rules, enroll/waitlist branch), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 874
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Key finding you should know about
Two symbolic constants are referenced by the scaffold but **never given a numeric value anywhere in `SCAFFOLD.yaml`**: `DEMO_PASS_SCORE` (used in the `SKILLS_PENDING → PASSED` / `→ FAILED` branch) and `AAR_MIN_SUMMARY_CHARS` (used in the `COMPLETED → AAR_SUBMITTED` precondition). Since the implementer sees only the PRD, I had to pin concrete values: **pass score 70** (consistent with `IMPUTED_PENDING_DEMO_SCORE: 70`) and **50 characters** for the AAR summary. If the withheld design index asserts different numbers, these two spots are where the PRD and tests will disagree — worth reconciling before test generation.

Confirmation: **neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.** Files read: the skill's `SKILL.md` and `section-2.2-response-structure.md`, `SCAFFOLD.yaml`, the task `worklog.md`, and a heading-only grep of the skill's `example-prd.md`.

### Orchestrator reconciliation of unbound constants (post-Step-4, pre-Step-5)

Acting on the doc-generator's flag, the orchestrator audited both withheld design indices for the two invented constants:

- `DEMO_PASS_SCORE = 70` — **kept**. Every PASS instance in both indices uses a score of 85/88/90/92/95/100; every FAIL uses 40/50/55/60. No instance sends `outcome: PASS` with a sub-70 score, and no instance probes the exact boundary. 70 is consistent with all 96 instances.
- `AAR_MIN_SUMMARY_CHARS = 50` — **revised to 40**. `SCAFFOLD_CORNER_DESIGN.yaml:697` issues, as a *setup* call expected to succeed, `aar_summary: "Objectives met; radio discipline needs work."` (44 chars). Under a 50-char minimum that setup would 4xx and the whole `exercise_credit` corner instance would die before its trigger. No error code for a too-short summary exists in the scaffold's 54-error catalog and no instance in either index tests the negative branch, so the threshold is unconstrained from the test side; 40 admits both the 44-char and 63-char design summaries while keeping the constraint real in prose. One-token edit to `workspace/PRD.md:251`.

## Step 6: Generate implementation — 2026-08-28T10:52:00.000Z

Implementation complete and verified.

## Files created — `workspace/implementation/` (3,218 lines total)

| File | Lines | Role |
|---|---|---|
| `app.py` | 74 | Flask entry point, blueprint registration, error handlers, serialising WSGI lock, `0.0.0.0:$PORT` |
| `store.py` | 126 | In-memory dicts (15 collections), logical clock, row minting, `touch()` version/`updated_at` bumping |
| `errors.py` | 79 | All 54 error IDs → HTTP status map, `ApiError` |
| `web.py` | 287 | `meta`/`response_type`/`data` envelope, `X-User-ID`/`X-User-Role` auth + RBAC, typed body validators, `limit`/`offset`/`total_count`/`has_more` pagination |
| `util.py` | 110 | ISO-8601 (3 fractional digits), `Decimal` ROUND_HALF_UP helpers, day arithmetic |
| `calc.py` | 487 | Constants + all 8 calculations (readiness dual-variant, loss settlement, renewal terms, refresher window, roster selection, asset selection, exercise credit, daily load) + conserved-counter recomputation |
| `cascade.py` | 189 | Chains A & B primitives: pass ledger, void, demotion, credential suspend/revoke, roster withdrawal, cohort revert |
| `routes_core.py` | 384 | Programs, cohorts, curriculum modules (cycle check), facilities, instructors |
| `routes_training.py` | 547 | Class sessions (both overlap geometries, day cap), trainees (waitlist selector), module completions (retake loop) |
| `routes_credentials.py` | 360 | Credential mint/lifecycle, equipment assets/issuances/return/loss |
| `routes_ops.py` | 565 | Exercises, participations, activations, roster assignments, `_clock`, `_ops` sweep |
| `start.sh` / `requirements.txt` | 9 / 1 | Guarded `pip install` + `exec python3 app.py` |

## Endpoint coverage
**60 / 60** implemented — verified by enumerating Flask's URL map (26 GET, 3 PATCH, 31 POST), matching the PRD §4 table exactly.

## Key fidelity decisions
- `created_at`/`updated_at` are stamped from the **logical clock** (startup `2026-08-01T00:00:00Z`), which the refresher window `[term_start_on, now)` requires; list ordering breaks logical-clock ties by insertion sequence, never by `id`.
- Check ordering follows **PRD §2.6 verbatim** (e.g. cert-expiry before activeness on scheduling, credential-live before activation-rostered on respond, budget ceiling last).
- One `version` bump per row per request, including cascade-touched rows.
- Facility overlap buffers **both ends of the candidate only** (adjacency collides); instructor overlap is unbuffered (adjacency legal).
- `renewal_tier`/`required_refresher_hours` resolved pre-increment and never recomputed from the new term.
- Store starts empty — no seeding anywhere; confirmed by querying 8 collections on a fresh boot (all `total_count: 0`).

## Boot smoke test — PASSED
`PORT=… bash start.sh` boots in <1s and answers correctly. Beyond the required single-endpoint check I ran four scripted end-to-end suites against fresh servers, all green: full program→cohort→session→completion→graduation→credential→equipment→activation→exercise→sweep→renewal→void-cascade path; auth/RBAC/ownership; waitlist promotion & seat ledger; equipment selector ranking, OCC (both rules), budget ceiling; roster build/manual-add/response-window/sweep; cascade chain B. Spot-checked numerics all matched the PRD's worked examples (readiness 95.2, settlement 3 months / 0.955 / 47750, 365-day term, `CERT-2026A-0001`). All background servers were killed afterwards.

## Step 5: Generate unit tests — 2026-08-28T11:00:00.000Z

(Completed after Step 6; both were launched concurrently in a single message.)

Test infrastructure and suite generated.

## Files created

**`test_helpers/`** (9 files, ~1,920 lines)
- `__init__.py` — barrel export (framework generics + domain code)
- `types.py` — 15 entity TypedDicts + 20 status/role enums
- `api_client.py` — 60 endpoint methods on `ApiClient(GenericApiClient)` + raw helpers
- `api_errors.py` — 54-member `ApiErrorId` enum, HTTP status map, registered with the framework
- `assertions.py` — per-entity assertions, `assert_instant` (fractional-digit-tolerant), `assert_hours`/`assert_score`, `assert_fill_status_matches_counts`
- `factories.py`, `constants.py`, `test_users.py` (per-instance builders for all three `entity_backed` roles)
- `fixtures.py` (667 lines) — 5 tiers: primitives → program/curriculum scaffold → `setup_passed_core_trainees` / `setup_graduated_trainees` / `setup_credentialed_trainees` → equipment & exercise accrual → `setup_rostered_activation`

**`test_suite/`** (conftest + 9 thematic files, ~3,900 lines): program/curriculum, cohort lifecycle & seats, class sessions, completions & demos, graduation & credentials, credential lifecycle, equipment, field operations, cascades & readiness.

## Coverage

- **104 test functions / 115 collected** (one 12-way parametrize).
- **Queue A (difficulty): 24 / 24 instances**, each with exactly ≥2 tests → 48 difficulty tests.
- **Queue B (corner): 55 / 55 non-stub instances**, ≥1 test each → 56 corner tests. All 17 `excluded_because:` stubs verified to resolve to a real difficulty instance; none translated.
- **0 instances skipped.**

Automated audit confirms: every test carries exactly one `Design:` line resolving to a real instance; every `PRD §x.y: "…"` citation survives a whitespace-normalised literal match against `PRD.md`; no `skip`/`skipif`/`xfail`; pyflakes clean; no scaffold/table references in emitted code.

## Assertion-level relaxations (two-reader rule)

No instance was dropped, but three post-renewal assertions were **not** emitted because the PRD leaves the design space open:

- `renewal_tier_resolved_before_reinstatement_count_increment`, `credential_cycles_active_grace_expired_and_back_to_active`, `refresher_hours_exactly_at_requirement_permits_renewal` — the design indices assert `renewal_tier == WATCH` / `required_refresher_hours == 12.0` *after* a renewal. PRD §3.6 states the opposite reading verbatim: *"the tier that governed that renewal remains STANDARD even though the credential now carries a reinstatement_count of 1"*, and §3.5 adds *"Under no circumstances is required_refresher_hours recomputed … from an incremented reinstatement_count."* Two faithful PRD-only implementers would diverge on the persisted post-renewal value, so those two fields are asserted only at issuance (where PRD pins STANDARD/8.0). Everything else in those instances (11.3-hour accrual, pre-increment gate, 380-day term, `reinstatement_count == 1`, reset to 0.0, cycle closure) is asserted in full.

## Timing adjustments vs. the design recipes

Two recipes were internally inconsistent with the PRD's half-open refresher window `[term_start_on, now)`; I re-sequenced the fixtures (keeping every literal expected value the design pre-computed):

- Credentials are always minted at `2026-08-05T16:00:00Z`, strictly after the `2026-08-05T15:00:00Z` module passes, so the refresher-eligible CERT-103 hours fall outside the term (11.3, not 16.3 / 2.0, not 7.0).
- In `refresher_hours_exactly_at_requirement_permits_renewal` the 7.9-hour rejection now happens at `2026-11-01T00:00:00Z` and the second drill is credited at `2026-12-01T10:00:00Z`, so the 0.1 hour is strictly inside the window at the successful `2027-01-01T00:00:00Z` renewal (the recipe as written credited it at the same instant as the renewal clock, which the exclusive upper bound would have discarded). Term literals `2027-01-01` / `2028-01-01` are preserved.

One other softening: `duplicate_module_code_returns_global_key_error` corroborates with an unfiltered module listing rather than `is_core=true`, since boolean query-parameter serialisation is not pinned by the PRD.

## Step 7: Run tests and iterate — 2026-08-28T11:07:00.000Z

No stray servers, working tree clean apart from the untracked task directory.

## Summary

**Iterations run:** 2 (sweep 1 → one fix → sweep 2, all green).

**Final result:** all 8 parallel rounds of sweep 2 reported `115 / 115`.

**Tests deleted:** none. No test failed STEP 1a (PRD coverage) or STEP 1b (unique derivability).

**Fixes applied to `test_helpers/`:** none — the bug was localized to a single test function, not a shared fixture.

**Fixes applied to `test_suite/`:**
- `test_suite/test_01_program_and_curriculum.py`, `test_class_session_end_time_is_derived_from_the_modules_contact_hours` — inserted the missing CERT-102 class session (`2026-08-04T09:00:00Z`) between session A and session C. This was a STEP 2 test bug: the test scheduled a session for CERT-103, whose `prerequisite_module_id` points at CERT-102, without ever scheduling CERT-102 on that cohort. PRD §3.3 states verbatim: *"When the module being scheduled carries a non-null `prerequisite_module_id`, the prerequisite must already have a session on this same cohort standing at `SCHEDULED` or `DELIVERED` whose `ends_at` falls at or before the candidate's `starts_at`; otherwise the request fails with `ERR_PREREQUISITE_NOT_SCHEDULED`."* The PRD-faithful implementation correctly returned 409 `ERR_PREREQUISITE_NOT_SCHEDULED`; reproduced directly against a live server before fixing. The fix makes the setup MORE faithful to PRD and leaves every original assertion (`ends_at` 11:30 / 14:00, `SCHEDULED`, null `delivered_at`, zero `recorded_completion_count`) untouched.

**Fixes applied to `implementation/`:** none. No implementation defect surfaced.

**Flakiness:** zero. The single failure was deterministic — identical in all 8 rounds of sweep 1 — and sweep 2 was clean in all 8 rounds, so no timing-sensitive bug (concurrency race, fixture ordering, port collision) is hiding behind a lucky round.

### Orchestrator verification of the green sweep (post-Step-7)

A green sweep with **0 implementation fixes** on a beyond-Expert task has three indistinguishable causes — a genuinely complete PRD, a design-index leak into the implementation, or a vacuous test suite — all of which print the same `passed == total`. The orchestrator discriminated between them before accepting the result:

1. **Design-index leak audit.** Parsed the Step 6 implementation agent's JSONL transcript and inspected the `input` of all 45 `tool_use` blocks (not raw text, which always false-positives on the prompt's own mention of the filenames). **0 calls** referenced `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, or `test_helpers/`. The withhold constraint held; concurrent launch with Step 5 also meant `test_suite/` did not exist at impl-gen spawn time.

2. **Mutation test of the suite.** Two rounds of deliberate implementation mutations, each reverted afterwards:
   - Round A: facility turnover buffer zeroed (`add_minutes(starts_at, -BUFFER)` → `add_minutes(starts_at, 0)`) plus settlement residual rounded to 3 digits instead of 4 → **113/115**, caught by `test_facility_buffer_makes_an_exactly_adjacent_session_collide` and `test_facility_double_booking_is_reported_before_room_capacity`. The rounding half of this mutation was *equivalent* (0.955 rounds identically at 3 and 4 digits) and therefore proved nothing on its own — which is why round B followed.
   - Round B: `CREDENTIAL_BASE_TERM_DAYS` 365 → 366 and `READINESS_CORE_WEIGHT` 60.0 → 55.0 → **104/115**, caught by 11 tests spanning graduation, renewal tiers, the currency sweep, activation response, and all four readiness-score tests.
   The suite is load-bearing, not vacuous.

3. **Independent re-run.** The Step 7 agent had deleted its `results.*.json` files. The orchestrator restored the implementation from backup (verified byte-identical to the pre-mutation copy), and re-ran the full 8-round parallel sweep itself: **115/115 in all 8 rounds**, regenerating `workspace/implementation/results.{1..8}.json` as the skill's output contract requires.

## Step 8: Finalize PRD — 2026-08-28T11:26:00.000Z

Done. `PRD_FINALIZED.md` written as a byte-identical copy of `PRD.md` — **zero edits warranted**.

## Line counts
- `PRD.md`: 408 lines
- `PRD_FINALIZED.md`: 408 lines
- Delta: **0 lines / 0.00%** (md5 identical: `699c44cbe47f2a936f7c5a773fa32f0c`)

## Change list
None. No PRD section required an insert or revise.

## Per-item analysis (the sole `<step_7_diff>` item)

**Item:** `test_suite/test_01_program_and_curriculum.py::test_class_session_end_time_is_derived_from_the_modules_contact_hours` — inserted a missing CERT-102 session between A and C.

(a) **Subject identified:** class-session scheduling — specifically the `prerequisite_module_id` guard on `POST /class-sessions`, plus the `ends_at` derivation and the new-session initial field values the test asserts.

(b) **Impl paths enumerated and read:**
- `routes_training.py:83-97` — the prerequisite check. Reads exactly as PRD §3.3 states: same `cohort_id`, same `module_id == prerequisite_module_id`, status in `("SCHEDULED","DELIVERED")`, `ends_at <= candidate starts_at`, else `ERR_PREREQUISITE_NOT_SCHEDULED`.
- `routes_training.py:47-48` — `ends_at = starts_at + contact_hours*60` minutes, matching PRD §3.3 verbatim ("2.5 contact hours produces a session 150 minutes long").
- `routes_training.py:110-124` — new-row initialisation: `status="SCHEDULED"`, `delivered_at=None`, `recorded_completion_count=0`, matching PRD §3.3 verbatim.
- `errors.py:49` — `ERR_PREREQUISITE_NOT_SCHEDULED` → 409, matching PRD §2.6 item 14.
- Grepped the whole implementation for `PREREQUISITE_NOT_SCHEDULED`: only these two sites; no parallel endpoint or cascade re-runs this check. (The learner-side sibling rule, `ERR_PREREQUISITE_NOT_PASSED`, is a distinct error code on completion recording and is separately documented in PRD §3.4.)

(c) **Wording adjustment:** none — no edit committed. The PRD sentence the Step 7 fix cited was already present verbatim and already uniquely determined the outcome; the implementation needed no change and exhibits exactly that behavior. This is a pure test-fixture bug (the test scheduled a CERT-103 session without ever scheduling its prerequisite CERT-102 on that cohort), so per Method step 1 it carries no PRD-silence and no PRD/impl mismatch to pin.

No other edits were manufactured — the broader ambiguity scan is Step 9's scope, and the HARD SCOPE rule confines Step 8 to items traceable to `<step_7_diff>`.

## Step 9: Complete PRD — 2026-08-28T11:38:00.000Z

`workspace/PRD_COMPLETED.md` is written and verified intact.

## Summary

**Source vs. output:** `PRD_FINALIZED.md` 408 lines / 87,905 chars → `PRD_COMPLETED.md` **408 lines / 98,127 chars (+10,222 chars)**. All edits are in-paragraph; no section added, no line added. §1–§5 all present, endpoint table complete at **60 rows**, error catalogue complete at **54 rows**.

**Counts:** 47 changes — **44 ambiguity-pins, 3 mismatch-revisions.**

### Changes

- §2.1 — revise — ambiguity — an empty (not just absent) auth header is also `ERR_UNAUTHENTICATED` — web.py:75-78
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from wall-clock time, not the logical clock — web.py:32
- §2.3 — insert — ambiguity — `created_at` ties broken by write order; enum filters and non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` 400; unmatched id filter → empty page — store.py:122, web.py:242-261
- §2.3 — revise — ambiguity — that same write order settles residual selector tie-breaks — calc.py:418, calc.py:459, routes_training.py:296
- §2.4 — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock — store.py:65-70
- §2.4 — insert — ambiguity — `version` advances at most 1 per row per request; a no-op counter refresh mutates nothing — store.py:96-102, cascade.py:26-33
- §2.4 — insert — ambiguity — clock accepts backwards moves; client datetimes echoed verbatim, only server-derived instants normalised — routes_ops.py:499, web.py:198-211, routes_training.py:117
- §2.6 — revise — ambiguity — step 10 also carries every lifecycle precondition with no dedicated code (`ERR_INVALID_STATE` 409) — routes_core.py:171-196, routes_ops.py:124-133
- §2.8 — insert — ambiguity — the OCC program is resolved from the trainee, never named in the payload — routes_credentials.py:236-243
- §3.1 — insert — ambiguity — PATCH semantics: omitted fields kept, unknown ignored, version bumps on a no-op payload — routes_core.py:67-74, 318-324, 377-383
- §3.2 — insert — ambiguity — no ordering imposed between `session_window_start` and `session_window_end` — routes_core.py:87-88
- §3.2 — insert — ambiguity — all five cohort-advance preconditions report `ERR_INVALID_STATE` 409 — routes_core.py:169-197
- §3.2 — insert — ambiguity — cohort cancellation applies no equipment/roster-commitment bars — routes_core.py:203-206
- §3.2 — insert — ambiguity — a new trainee's derived fields all open null/0 — routes_training.py:246-252
- §3.2 — insert — ambiguity — ownership checked before action; trainee `ENROLL`/`GRADUATE` → `ERR_UNAUTHORIZED`; per-action legal source standings → `ERR_INVALID_STATE` — routes_training.py:309-357
- §3.3 — insert — ambiguity — deliver: owner error precedes state; non-SCHEDULED, cohort-not-IN_SESSION, unreached clock all → `ERR_INVALID_STATE` — routes_training.py:162-173
- §3.3 — insert — ambiguity — cancelling an already-CANCELLED session → `ERR_INVALID_STATE` — routes_training.py:191-192
- §3.3 — revise — **mismatch** — chain B also reverts the cohort when a voided completion demotes a graduate, not only on missing core delivery — routes_training.py:207-209
- §3.4 — insert — ambiguity — any `Instructor` may record; no session-ownership and no cohort-membership check — routes_training.py:403-410
- §3.4 — insert — ambiguity — an auto-passing completion is returned at `version` 1 with `updated_at == created_at` — routes_training.py:456
- §3.4 — insert — ambiguity — `demo_score` required on both outcomes; wrong standing → `ERR_INVALID_STATE` before the SoD check — routes_training.py:497-506
- §3.4 — insert — ambiguity — re-void or CLOSED-cohort void → `ERR_INVALID_STATE` — routes_training.py:535-540
- §3.4 — insert — ambiguity — a non-PASSED void still lowers `recorded_completion_count` and touches the trainee — cascade.py:174-183
- §3.5 — revise — ambiguity — a non-graduated mint is refused with `ERR_CREDENTIAL_ALREADY_ISSUED` too — routes_credentials.py:56-58
- §3.5 — insert — ambiguity — credential sequence = existing cohort credentials + 1 — routes_credentials.py:60-63
- §3.6 — insert — ambiguity — the pre-action refresh is unconditional and survives a refused action without a version bump — routes_credentials.py:118
- §3.6 — revise — ambiguity — renewal from a non-GRADUATED trainee or a non-renewable standing → `ERR_INVALID_STATE` — routes_credentials.py:121-127
- §3.6 — insert — ambiguity — reinstatement guards → `ERR_INVALID_STATE` (not `ERR_CORE_MODULES_INCOMPLETE`); only `term_start_on` is reset — routes_credentials.py:147-164
- §3.6 — revise — ambiguity — revocation withdraws assignments whatever the activation's standing; re-revoke → `ERR_INVALID_STATE` — cascade.py:102, routes_credentials.py:166-167
- §3.6 — insert — ambiguity — `swept_credential_count` counts every program credential; one step per sweep; ACTIVE past `grace_ends_on` untouched — routes_ops.py:517-540
- §3.6 — insert — ambiguity — a credential read never re-derives `refresher_hours_in_term` — routes_credentials.py:101-105
- §3.7 — revise — ambiguity — the credential gate runs before asset selection, the kit-duplicate gate after — routes_credentials.py:246-260
- §3.7 — revise — ambiguity — the issuance row also records `trainee_id` and `kit_type` — routes_credentials.py:267-281
- §3.7 — insert — ambiguity — return/report-lost on a non-ISSUED issuance → `ERR_INVALID_STATE` — routes_credentials.py:321, 343
- §3.8 — insert — ambiguity — participation registration is unguarded (any exercise standing, any program, duplicates allowed) — routes_ops.py:174-192
- §3.8 — insert — ambiguity — exercise-advance preconditions → `ERR_INVALID_STATE` 409 — routes_ops.py:122-133
- §3.8 — insert — ambiguity — the coordinator/manager split resolves after payload validation → `ERR_UNAUTHORIZED`; `aar_summary` checked only after edge legality — routes_ops.py:94-117, 136
- §3.8 — revise — **mismatch** — exercise credit is added on the `term_start_on` lower bound alone; term upper bound and credential standing not consulted — routes_ops.py:152
- §3.9 — insert — ambiguity — rostering a non-REQUESTED activation → `ERR_INVALID_STATE` — routes_ops.py:284-286
- §3.9 — insert — ambiguity — the roster build answers with the activation, not the assignments — routes_ops.py:312
- §3.9 — insert — ambiguity — every row from one build shares a single `notified_at` — routes_ops.py:292-303
- §3.9 — insert — ambiguity — `selection_rank` 1 on an empty roster; manual add works in any activation standing; 201 with the assignment row — routes_ops.py:330-347
- §3.9 — revise — **mismatch** — respond checks run state → credential → rostered → window, not the order §3.9 narrated — routes_ops.py:437-451
- §3.9 — revise — ambiguity — sweep's no-response is scoped to the swept program and ignores the activation's standing — routes_ops.py:544-556
- §3.9 — insert — ambiguity — activation and assignment advance preconditions → `ERR_INVALID_STATE` — routes_ops.py:364-377, 468-475
- §3.9 — insert — ambiguity — readiness read output precision per field (2/1/4/4/2/1 dp) — routes_training.py:383-395
- §4 — insert — ambiguity — unknown path → `ERR_INVALID_REQUEST` 404; wrong method → `ERR_INVALID_REQUEST` 405 — app.py:50-55

### Orchestrator verification of Step 9 output

Independently confirmed `PRD_COMPLETED.md` is not truncated (the known doc-generator failure mode where sections 4–5 silently vanish): 408 lines / 98,448 bytes, all six headings present (`# title`, §1 Introduction, §2 Global Specifications, §3 Business Logic, §4 Endpoint Definitions, §5 Error Code Catalogue), **60** endpoint rows and **54** error rows counted directly, file ends cleanly on the last error row. `PRD.md` and `PRD_FINALIZED.md` remain byte-identical to each other (88,173 bytes each).

## Pipeline complete

Final state: 115/115 tests passing across 8 parallel rounds, `results.{1..8}.json` present, implementation byte-identical to the version that produced that sweep, no stray server processes.
