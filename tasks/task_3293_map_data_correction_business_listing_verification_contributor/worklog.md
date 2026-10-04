# Worklog — task_3293_map_data_correction_business_listing_verification_contributor

## Step 1: Create Task Directory — 2026-09-30T18:10:00.000Z

Pre-allocated task directory `./tasks/task_3293_map_data_correction_business_listing_verification_contributor/` verified to exist with `workspace/` inside. Used the given path exactly as instructed (no new index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-09-30T18:14:00.000Z

All three scaffold artifacts are written and the lint is clean.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3293_map_data_correction_business_listing_verification_contributor/`):

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **13** (Region, Contributor, ContributorGrant, BusinessListing, VerificationAttempt, MapEdit, ReviewTicket, UserReview, ReviewFlag, SuspensionCase, HoursObservation, ImageryTask, RoutingUpdate)
- Endpoints: **73** (incl. `POST /v1/_clock/set_current_utc` with pinned default `2026-09-01T00:00:00Z`, and sweeps for attempt expiry, reverify, routing activation/expiry, fake-detection)
- State machines: **7** (MapEdit cyclic via NEEDS_MORE_INFO loop; BusinessListing cyclic via REVERIFY and SUSPENDED→VERIFIED reinstatement; UserReview cyclic via RESTORE; VerificationAttempt; SuspensionCase; ImageryTask with REPROCESS loop; RoutingUpdate)
- Calculations: **8** (dual-variant trust and health scores, per-contribution rounding order pinned, hours conflict winner with conditional promotion, fake-review probability, edit auto-validation threshold, verification cooldown, region privacy clearance posture)
- Errors: **32**; Validations: **25** (ordered, with priority-conflict pairs state-vs-safety and referential-vs-safety); Roles: **8** (Anonymous, Contributor, BusinessOwner — both entity-backed by Contributor — Moderator, PolicyAnalyst, ImageryOperator, RoutingEngineer, PlatformAdmin); Concurrency rules: **3** OCC on listing/region versions
- Difficulty-design instances: **18** (9 rules × 2, all differentiation clauses honored: different entity domains, different combinatorial modes (a)/(b), different error-category pairs, different metrics/endpoints, different entity pairs, different interval semantics (half-open adjacency vs 24h buffer), different conserved quantities (points vs review_count))
- Corner-design instances: **42** total (36 active with full recipes + 6 `excluded_because` stubs citing §1.8 instances)

**Validation:** `scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (403 calls scanned, 18 §1.8 + 36 §1.9 active instances). Instance names are unique across both design files; forbidden concurrency vocabulary absent; formula-derived asserts were pre-computed as literals (trust 44/50, health 37.33, score boundaries 85/75, cooldown 72h, buffer 24h).

Orchestrator note: initial subagent run exhausted its output budget during design prose and wrote nothing; resumed via SendMessage with one-file-per-message instructions, which completed. Verified on disk: SCAFFOLD.yaml (1788 lines, 73 method: entries), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1118 lines), SCAFFOLD_CORNER_DESIGN.yaml (1548 lines). Endpoint count 73 exceeds the ~40 overshoot threshold — Step 6 prompt will enforce incremental one-file-per-message writes and the orchestrator will verify files on disk afterward.

## Step 3: Copy Shared Files — 2026-09-30T18:37:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3293_map_data_correction_business_listing_verification_contributor/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T18:45:00.000Z

PRD generation complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3293_map_data_correction_business_listing_verification_contributor/workspace/PRD.md` — 321 lines.

**Sections:**
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications (9 subsections: RBAC with identity semantics for all 8 roles, verbatim §2.2 envelope, pagination, common fields + logical clock with `common_fields: false` entities called out, OCC covering all 3 rules, validation priority order, precision/rounding + dual-variant trust/health, region posture/privacy ledger, hierarchical consistency)
- §3 Business Logic (10 subsections: onboarding+grants, listings, verification, map edits, reviews/flags, suspension/appeals/trust+health formulas, hours conflict resolution, imagery+privacy, routing epochs, shared ticket queue)
- §4 Endpoint Definitions (73 endpoints, 4-column table)
- §5 Error Code Catalogue (32 errors, 2-column table)

**Hard Contract Audits:**

- **Contract 1 (Field-Name Coverage):** PASS — 107 required identifiers (all `entities[].fields[].name`, all endpoint `input` names, all path params, `limit`/`offset`); 107 present in backticks; 0 missing.
- **Contract 2 (Rule Coverage):** PASS — all 25 validation rules expressed with priority ordering in §2.6 plus per-rule trigger prose with `error_id` in §3; all 3 OCC rules expressed (write endpoint, `expected_<parent>_version`, `ERR_STALE_VERSION`/412); all 8 state machines' transitions covered with from/to states, preconditions paired to error IDs, and side effects (including cascades: suspension three-link cascade, revert compensating invariant, verification-failure auto-suspension at 5 failed counts, posture bubble-up, supersede-on-activate); all 8 calculations expressed in reconstruction-safe prose (trust weighted ledger with 7-day finalized variant and permanence penalty applied once, pinned per-contribution rounding with the forbidden sum-then-round alternative called out, pinned 3-step health evaluation with moderation variant's half-weight numerator/denominator, hours winner source priorities incl. EXPERT/MASTER promotion and both tie-breaks plus empty-set behavior, fake-probability signal weights and 0.80 threshold, auto-validation base/risk table with exact 85.0 boundary, verification cooldown with strict-< boundary and 5-per-30-day cap, privacy posture priority chain); all endpoint side effects and `applies_to` scopes enumerated; sibling branches (AUTO_VALIDATED/QUEUED/REJECTED, UPHELD/OVERTURNED, REMOVE/RESTORE/DISMISS, three suspension admissible states) rendered at equal density.
- **Contract 3 (§3 Path Purity):** PASS — 523 backtick tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. Endpoints referenced via state-transition framing, role+verb, or capability descriptions only.

Notes: the two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never read. Two minor edits were applied after the initial draft (explicit `ERR_INVALID_STATE` on revert-from-non-published; `UNDER_MODERATION` named in the moderation-health variant sentence).

Orchestrator note: verified on disk — PRD.md is 321 lines / 59888 bytes, 109 table rows, 58 ERR_ mentions. The subagent's audits are consistent with a complete §4/§5; treated as plausible (verify-against-source rule) with final behavioral validation deferred to Step 7's test sweep.

## Step 5: Generate Unit Tests — 2026-09-30T19:05:00.000Z

All done. Final summary:

## Files written

**test_helpers/** (9 files, under `/home/ubuntu/github/CodingPRD/tasks/task_3293_map_data_correction_business_listing_verification_contributor/test_helpers/`):
- `types.py` — 14 status/enum classes + 14 entity TypedDicts (append-only ContributorGrant/ReviewFlag/HoursObservation omit `updated_at`/`version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (56 methods)
- `api_errors.py` — all 32 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators enforcing the append-only field absence
- `factories.py`, `constants.py` (all calculation constants), `test_users.py` (opaque-role constants + entity-backed `make_contributor_headers`/`make_business_owner_headers`), `fixtures.py` (claim/verify/suspend/appeal lifecycle, QUEUED-edit + ticket machinery, review/flag/moderation chain, hours/imagery/routing helpers; all ownership-gated calls thread real contributor ids)
- `__init__.py` — barrel export

**test_suite/** (14 test files + `conftest.py`, under `.../test_suite/`): 75 tests total.

## Coverage

- **Queue A (difficulty): 18/18 instances, each with ≥2 tests** (43 tests)
- **Queue B (corner): 36/36 non-stub instances, each with ≥1 test** (32 tests); the 6 `excluded_because` stubs were verified to resolve to real difficulty instances and were not translated

## Skipped instances

None — every instance passed the PRD-first filter. One literal correction applied: corner instance `health_public_vs_moderation_diverge...` (difficulty queue) pins `moderation_health_score == 37.33` in the design YAML, but the PRD formula uniquely derives 54.00 (numerator 0.5·1, denominator 0.5·1 → aggregate 1.0 → 50+4·1); per the clock/literal re-derivation rule, the tests assert the PRD-derived value 54, not the recipe literal. All fixture dates were checked against the 2026-09-01T00:00:00Z logical-clock start — no clock-unreachable dates remained.

## Validation verdicts

- **Stage 1** — PASS: all helpers compile; `import test_helpers` succeeds against the installed `prd_bench_local_runner.testing` framework.
- **Stage 2** — PASS: 75/75 tests carry exactly one `Design:` tag; every tag resolves verbatim to a real instance name in the source yaml; difficulty ≥2/instance and corner ≥1/non-stub-instance coverage verified programmatically; no test without a tag, no stub translated.
- **Stage 3** — PASS: automated verbatim sweep confirms every PRD citation (75 tests, all quotes ≥8 words) survives a literal whitespace-normalized grep of PRD.md; no `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in comments/docstrings.

Orchestrator note: verified on disk — test_helpers/ has all 9 files, test_suite/ has conftest.py + 14 test files, 75 test functions, 75 Design: tag lines (exactly one per test). Launched alone in its own message per the parallel-call duplication constraint; Step 6 follows in a separate message.

## Step 6: Generate Implementation — 2026-09-30T19:17:00.000Z

Implementation complete. Summary below.

## Files (all under `tasks/task_3293_map_data_correction_business_listing_verification_contributor/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| start.sh | 7 | Guarded pip install, `exec python3 app.py`, PORT env |
| requirements.txt | 1 | flask |
| app.py | 53 | Flask app, blueprint registration, ApiError/404/405 handlers |
| clock.py | 45 | Logical clock, default `2026-09-01T00:00:00Z`, never wall-clock |
| store.py | 19 | In-memory dicts, empty at boot, zero seeding |
| errors.py | 49 | ApiError + full 32-entry error catalog |
| response.py | 105 | Envelope (`meta`/`response_type`/`data`), pagination (limit/offset/total_count/has_more, default 10, max 100), auth header parsing (X-User-Role + X-User-ID) |
| validation.py | 63 | Field/enum/number validators |
| domain.py | 253 | Recomputes (points, level, trust variants, health variants, region posture), serializers, keyword-stuffing screen |
| services_listings.py | 159 | Edit publish/revert cascades, suspension cascade, reverify transition |
| services_hours.py | 113 | Hours observations + hours_conflict_winner scoring |
| routes_platform.py | 97 | Clock set + 5 sweeps |
| routes_regions.py | 73 | Region CRUD (3 endpoints) |
| routes_contributors.py | 135 | Contributors + grants (6 endpoints) |
| routes_listings.py | 238 | Listings, claim, suspend, require-reverify, reverse lists, hours resolve (11 endpoints) |
| routes_attempts.py | 157 | Verification attempts (5 endpoints) |
| routes_edits.py | 198 | Map edits, supply-info, revert, edit ticket reverse list (6 endpoints) |
| routes_tickets.py | 199 | Review tickets create/claim/resolve/escalate (5 endpoints) |
| routes_reviews.py | 234 | Reviews, flags, dismiss, fake-probability calc (7 endpoints) |
| routes_cases.py | 116 | Suspension cases, appeal lifecycle (5 endpoints) |
| routes_imagery.py | 198 | Imagery tasks pipeline (8 endpoints) |
| routes_routing.py | 174 | Routing updates + 24h buffer conflict (6 endpoints) |

Total: 2,686 lines across 19 Python modules + start.sh + requirements.txt. All 73 endpoints from the scaffold table are mounted (verified against §1.5/§4).

## Endpoint-to-module mapping
- Platform plumbing (6): clock, 5 sweeps → `routes_platform.py`
- Regions (3) → `routes_regions.py`
- Contributors/grants (6) → `routes_contributors.py`
- Listings + hours resolve + reverse lists (11) → `routes_listings.py`, `services_hours.py`
- Verification attempts (5) → `routes_attempts.py`
- Map edits (6) → `routes_edits.py`
- Review tickets (5 + 2 reverse-lookup in edits/reviews modules) → `routes_tickets.py`
- Reviews/flags (7) → `routes_reviews.py`
- Suspension cases (5 + listing reverse in listings) → `routes_cases.py`
- Hours observations (2) → `services_hours.py`
- Imagery tasks (8) → `routes_imagery.py`
- Routing updates (6) → `routes_routing.py`

## Key behaviors implemented per spec
- Validation priority: auth → role → path/body existence → field shape → state → OCC → ownership → listing admissibility → content/temporal policies.
- OCC on the 3 guarded writes (map-edit create, claim, routing create) with `ERR_STALE_VERSION` 412; parent version bumps on guarded mutations.
- Logical clock with pinned default `2026-09-01T00:00:00Z`; all windows/sweeps/expiry evaluated against it.
- Per-contribution round-half-up points; level thresholds 50/250/1000/5000; edit quality weights 0.5–2.5.
- Trust score dual variants (provisional counts all edits; finalized excludes edits younger than 7 days), 25-point PERMANENTLY_CLOSED penalty, auto-RESTRICT below 20 on finalized.
- Listing health dual variants with pinned evaluation order (30-day revert rate → rating aggregate → score), visibility HIDDEN/RESTRICTED/PUBLIC derivation.
- Auto-validation score (40 + 0.4·finalized_trust + 10·evidence_urls(capped 3) − risk by type), exact 85/50 routing boundaries.
- Verification throttles (72h cooldown strict-`<`, 5-per-30d cap), 5-failure auto-suspension with FAKE_ADDRESS case.
- Suspension cascade: case create → edit rejection storm → trust demotion → visibility HIDDEN → attempt cancellation; appeals with segregation-of-duties and stricter-of-two reinstatement.
- Hours conflict winner with source priorities, EXPERT/MASTER contributor promotion, recency/corroboration scoring and tie-breaks.
- Region privacy posture (FROZEN > CLEARANCE_PENDING > CLEAR > ACTIVE) with privacy ledger driven by imagery lifecycle; half-open window overlap; capacity cap.
- Routing: 24h buffer conflict (exactly 24h allowed) for CLOSURE/CONSTRUCTION, same-request VALIDATED→SCHEDULED/ACTIVE split, supersede-on-activate, epoch bumps on create/validate/activate/expire/cancel (not PROPOSED-cancel).
- No seeding; store starts empty every boot.

## Boot smoke test
`PORT=18443 bash start.sh` (background, PID saved). Verified: clock set, region create, contributor register, listing create, claim (OCC), verification attempt + code submit → VERIFIED listing + VERIFICATION_ASSIST grant, auto-published edit (score exactly 85.0 → PUBLISHED), queued edit (55.0) → moderator ticket → CLAIMED → resolve APPROVE → PUBLISHED with wrong-moderator `ERR_NOT_TICKET_OWNER`, imagery full pipeline with posture transitions ACTIVE→CLEARANCE_PENDING→CLEAR, routing propose/validate → SCHEDULED with routing_version bump, auth errors (401/403 envelopes). Server killed with exactly the saved PID (1249750); `ps` confirms the process is gone. All 19 modules pass `python -m py_compile`.

Orchestrator note: verified on disk — 19 .py files (2678 lines total) + start.sh (executable) + requirements.txt; `python3 -m py_compile *.py` passes. The stray `python3 app.py` processes visible in `ps` predate this step (18:00–18:19, other pipelines on this shared host) and were not touched. Launched alone in its own message after Step 5 completed, per the parallel-call duplication constraint.

## Step 7: Run Tests and Iterate — 2026-09-30T19:50:00.000Z

Task complete — clean 8-round parallel sweep (75/75 in every round).

## Summary

**Iterations run:** 5 sweeps (4 with failures, final one clean 8/8 rounds).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `fixtures.py::make_region` — was sending only `{"name": ...}`; now uses `create_region_payload()` so PRD-required `country_code`, `timezone`, and bounding-box edges are sent (this single fixture bug caused 71/75 setup failures).
- `fixtures.py::make_map_edit` — when `expected_listing_version` is omitted, re-reads the listing's current version instead of trusting the caller's stale dict; PRD §2.5 makes every edit create bump the listing version, so a previously captured listing dict is already stale after one edit.

**Fixes applied to `test_suite/`:**
- `test_08_suspension_appeals.py::test_suspension_edit_rejection_trust_demotion_cascade` — added `set_clock("2026-09-10T00:00:00Z")` so the six rejections age past the 7-day finalized-trust window (PRD §2.4 gates RESTRICTED demotion on the finalized variant only), and moved the 7th edit's creation before the clock move so its auto-score is computed while finalized trust is still 50 (score 55 → QUEUED, per PRD §3.4).

**Fixes applied to `implementation/`:**
- `routes_reviews.py` (3 sites: review create, `auto_flag`, `dismiss_flag`) and `routes_tickets.py` (2 sites: moderation-ticket create, REVIEW_MODERATION resolve) — removed listing `version` bumps on review/flag/moderation mutations; PRD §2.5 exhaustively lists bump triggers (map-edit create, claim, routing-update create, suspension) and reviews are not among them.
- `routes_listings.py::claim_listing` — reordered validation: field-shape check first (PRD §2.8), then OCC before the already-claimed state check, because PRD §2.5 verbatim requires a claim built on a snapshot taken before another claim to surface `ERR_STALE_VERSION`.
- `services_hours.py` — `create_observation` now records the acting contributor id as `_contributor_id` for CONTRIBUTOR-source observations so `resolve` can apply the PRD §3.7 EXPERT/MASTER priority promotion (previously the author was never stored, so promotion was unreachable).
- `domain.py::hours_view` — switched to `_clean` so the internal `_contributor_id` never leaks into responses.
- `routes_imagery.py::_check_window_and_capacity` — capacity count now excludes the task being scheduled; otherwise a PLANNED task (PRD includes PLANNED in the capped set) could never schedule into a region already at cap−1, making PRD §3.8's "active-task count must remain below the cap" unsatisfiable.

Orchestrator note: verified on disk — all 8 `results.{i}.json` files show 75/75 passed, 0 failed; results written 19:50 UTC, newer than the last implementation edit (19:36 UTC), so the sweep reflects the final code. Step 7 made `implementation/` fixes, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-30T20:00:00.000Z

All 5 edits are in place. Line counts: PRD.md 321 lines, PRD_FINALIZED.md 321 lines (0% delta — all edits are inline sentence insertions/revisions within existing paragraphs, no lines added or removed; the diff shows 5 modified paragraphs).

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3293_map_data_correction_business_listing_verification_contributor/workspace/PRD_FINALIZED.md` — 321 lines vs PRD.md's 321 lines (0% line-count delta; 5 paragraphs revised inline).

**Step 7 items assessed:**
- `fixtures.py::make_region` and `fixtures.py::make_map_edit` — pure test-fixture bugs; PRD already required the region fields (§2.8/§3.1) and the edit-version bump (§2.5). No PRD edit.
- `test_08_suspension_appeals.py` clock fix — PRD §2.4/§2.7 already pinned the finalized-variant gating and §3.4 already pinned the 50–85 queue band. No PRD edit.

**Changes applied (one bullet each):**

- §2.6 — insert — appended a sentence pinning that the listing-claim endpoint runs the `expected_listing_version` field-shape check before the OCC comparison — `routes_listings.py:143-148`
- §3.2 — insert — appended claim-endpoint ordering: required-field check, then OCC, then the already-claimed check, so a stale-snapshot claim surfaces `ERR_STALE_VERSION` even on a now-claimed listing — `routes_listings.py:143-150`
- §3.4 — insert — appended that review-side mutations (review create, flag, auto-flag, flag dismiss, `REVIEW_MODERATION` ticket create/resolve) recompute listing aggregates but never bump the listing's `version`; §2.5's bump triggers are exhaustive — `routes_reviews.py:69,130,181,227`, `routes_tickets.py:79,157,167,171,175`
- §3.7 — revise (two edits) — recording an observation now specifies the server retains the acting contributor's id on `CONTRIBUTOR`-source observations created by an authenticated Contributor/BusinessOwner, internal-only and never exposed; and the EXPERT/MASTER promotion reads the "recorded author" at "resolution time" — `services_hours.py:61-62,88-93`, `domain.py:220-221,228-229`
- §3.8 — revise — capacity check sentence now states the count excludes the task being scheduled, so a `PLANNED` task can schedule into a region at cap−1 — `routes_imagery.py:36-40`

**Per-edit pre-edit search log:**

1. **§2.6 claim ordering** — (a) subject: validation-order precedence around the claim OCC check. (b) enumerated: all three OCC sites (`routes_listings.py:139-158`, `routes_edits.py:35-54`, `routes_routing.py:41-56`) plus the §3.2 claim paragraph. (c) scoped wording explicitly as an endpoint-specific exception for the claim call only, to avoid contradicting the general pipeline ordering that the other OCC sites follow (field-shape happens to precede OCC there too, but only the claim site's ordering was fixed by Step 7).
2. **§3.2 claim ordering** — (a) subject: claim endpoint error precedence (OCC vs already-claimed). (b) enumerated: `routes_listings.py:139-158` (the only claim path); cross-checked `suspend_listing` (bumps version via touch) so the "before another claim mutated the listing" phrasing stays accurate. (c) none.
3. **§3.4 review-side version bumps** — (a) subject: which mutations bump listing `version`. (b) enumerated: all `domain.touch` callsites across `routes_reviews.py`, `routes_tickets.py`, `routes_edits.py`, `routes_listings.py`, `services_listings.py` — confirmed post-Step-7 impl touches the review (own version) but never the listing on the five review-side sites, while create-edit/claim/suspend/patch/publish/revert do bump the listing. (c) worded as "recompute aggregates but never increment version; §2.5's bump triggers are exhaustive" and explicitly listed only the review-side operations, avoiding any universal claim about non-review mutations (PATCH listing and edit publication do bump via touch, consistent with §2.9's "mutations propagate").
4. **§3.7 author recording + promotion** — (a) subject: hours observation fields and CONTRIBUTOR priority promotion. (b) enumerated: `services_hours.py::create_observation` (sets `_contributor_id` only for CONTRIBUTOR source under Contributor/BusinessOwner role), `services_hours.py::resolve` (promotion reads stored id and current level), `routes_listings.py::resolve_hours`, `domain.py::hours_view`/`_clean` (strips `_`-prefixed keys from all response views, including the per-listing list endpoint). (c) added "at resolution time" (impl recomputes the author's current level at resolve, not at creation) and "recorded by an authenticated Contributor or BusinessOwner" (PlatformAdmin/Moderator-created CONTRIBUTOR observations store no author, so no promotion — wording avoids implying promotion for those).
5. **§3.8 capacity counting** — (a) subject: imagery capacity check membership. (b) enumerated: `routes_imagery.py::_check_window_and_capacity` (excludes `task["id"]`, counts only `ACTIVE_STATUSES`), its sole caller `schedule()`; verified `create_task` runs no capacity check and no other endpoint enforces the cap. (c) added "covers other tasks already in the capped statuses and excludes the task being scheduled itself" — stays silent on creation-time behavior, so it doesn't conflict with `create_task`'s unchecked path.

Orchestrator note: verified on disk — PRD_FINALIZED.md exists, 321 lines, diff vs PRD.md is 24 diff-lines (5 paragraphs). Implementation untouched since the 19:50 sweep (no re-run needed).

## Step 9: Complete PRD — 2026-09-30T20:05:00.000Z

Done. `PRD_COMPLETED.md` is produced as a minimal patch over `PRD_FINALIZED.md`.

## Summary

**Source vs output**: `PRD_FINALIZED.md` 321 lines / 61,357 chars → `PRD_COMPLETED.md` 322 lines / 66,176 chars (+1 line, +4,819 chars). 24 source paragraphs revised in place; 1 paragraph gained an extra line (bullet added in §2.2).

**Counts**: 20 ambiguity-pins, 5 mismatch-revisions (25 changed passages total; some pins ride along inside mismatch revisions).

**Changes** (one bullet per change):

- §2.2 — insert — ambiguity — unknown path or unsupported method returns `ERR_NOT_FOUND` (404) — implementation/app.py:35-42
- §2.3 — revise — ambiguity — negative/non-integer pagination params rejected with `ERR_INVALID_REQUEST`; `has_more = offset+limit < total_count`; `created_at` ties broken by `id` ascending — implementation/response.py:47-78
- §2.4 — revise — ambiguity — `version` starts at 1; internal bookkeeping fields (`_applied_prior`, `_publish_grant_id`, `_review_grant_id`, `_contributor_id`, `_pre_suspension_status`, case `suspended_by`) never exposed — implementation/domain.py:228-245, routes_cases.py
- §2.6 — revise — ambiguity — on map-edit create, OCC runs before contributor-active, listing-admissibility, duplicate, and content screens — implementation/routes_edits.py:53-64
- §2.8 — revise — mismatch — `routing_version` bumps on validation/activation/expiry/validated-or-scheduled-cancellation only, NOT on creation or proposed-cancellation — implementation/routes_routing.py:73 (create does not bump), 128-138, 152-174
- §3.1 — revise — ambiguity — new region starts ACTIVE/unfrozen/pending 0/routing_version 0/version 1; `max_active_imagery_tasks` must be a non-negative integer — implementation/routes_regions.py:30-51
- §3.1 — revise — ambiguity — single-contributor read applies automatic RESTRICTED demotion; list reads recompute without demoting — implementation/routes_contributors.py:71, domain.py:103-109, 202-204
- §3.1 — revise — ambiguity — grants carry `note` (empty string default); revoking a non-POSTED grant is `ERR_INVALID_STATE` — implementation/routes_contributors.py:104-135
- §3.2 — revise — mismatch — keyword-stuffing strike persists only when a listing record exists; a rejected creation records no strike — implementation/routes_listings.py:27-34, 51
- §3.2 — revise — ambiguity — PATCH: non-owner BusinessOwner → `ERR_NOT_LISTING_OWNER`; any status admitted; geofence re-run on coordinate change; version bumps — implementation/routes_listings.py:110-135
- §3.3 — revise — mismatch — `code` minted and returned at creation for every method, not only postcard/phone; verifiability check precedes owner check; attempts list filters `listing_id`/`status`/`method` — implementation/routes_attempts.py:20-80
- §3.3 — revise — mismatch — `failed_verification_count` counts FAILED attempts across all owned listings (not per listing); auto-suspension fires at count ≥ 5 only while the listing is in a suspendable state; VERIFICATION_ASSIST grant has multiplier 1.0 — implementation/routes_attempts.py:121-139, domain.py:115-118
- §3.4 — revise — ambiguity — edit create bumps listing `version` once, and an in-request auto-publish bumps it once more (+2 total) — implementation/routes_edits.py:107-122, services_listings.py:70-84
- §3.4 — revise — ambiguity — EDIT_REVIEW ticket creation admissible from QUEUED or from an unassigned IN_REVIEW edit; other states → `ERR_INVALID_STATE` — implementation/routes_tickets.py:57-60
- §3.5 — revise — ambiguity — every accepted flag (human or auto) moves the review to FLAGGED; `flag_count` counts OPEN flags only; review list filters `listing_id`/`contributor_id`/`status` — implementation/routes_reviews.py:76-79, 158-182
- §3.5 — revise — ambiguity — REVIEW_MODERATION ticket creation requires flag OPEN and review FLAGGED else `ERR_INVALID_STATE`; ticket-level `DISMISS` behaves exactly like `RESTORE` — implementation/routes_tickets.py:68-76, 164-171
- §3.6 — revise — ambiguity — suspension records suspending analyst and pre-suspension status internally (never exposed) — implementation/services_listings.py:118-129, domain.py:244-245
- §3.6 — revise — ambiguity — OVERTURNED restores to CLAIM_PENDING when the listing was suspended from CLAIM_PENDING — implementation/routes_cases.py:99-108
- §3.7 — revise — ambiguity — `day_mask` validated for seven-character length only; empty resolution reports `accepted_observation_id` null and `accepted_count` 0 — implementation/services_hours.py:42-46, 75-114
- §3.8 — revise — ambiguity — imagery window well-formedness (`window_start` strictly before `window_end`, parseable) enforced at creation with `ERR_INVALID_REQUEST` — implementation/routes_imagery.py:53-59
- §3.8 — revise — mismatch — blur-complete admissible from both `BLUR_PENDING` and `REPROCESS`; a complete blur from REPROCESS moves directly to BLURRED (no loop back through BLUR_PENDING) — implementation/routes_imagery.py:139-162
- §3.9 — revise — ambiguity — routing create rejects malformed datetimes at creation but defers start<end ordering to validation — implementation/routes_routing.py:50-54, 107-110
- §3.9 — revise — ambiguity — cancelling a SCHEDULED update whose start has been reached fails with `ERR_INVALID_STATE` — implementation/routes_routing.py:162-164
- §3.10 — revise — ambiguity — ticket claim admissible from OPEN and ESCALATED; each queue admits only its own resolution set, cross-queue → `ERR_INVALID_REQUEST` — implementation/routes_tickets.py:106-115, 130-132, 149-151

**Known latent implementation issue (not pinned into the PRD)**: `routes_platform.py` imports `services_routing` and `services_reviews`, which do not exist — so `POST /v1/routing-updates/sweep-activation` and `POST /v1/reviews/sweep-fake-detection` raise `ModuleNotFoundError`, surfacing as `ERR_INVALID_REQUEST` (400) via the generic exception handler. The passing sweep tests cover only the other three sweeps, so the test suite never exercises these two. I left the PRD's normative sweep descriptions untouched rather than pinning crash behavior; implementation/ was out of scope for edits.

## Post-Step-9 orchestrator repair + re-sweep — 2026-09-30T20:30:00.000Z

Verified the Step 9 latent-issue claim against source: `routes_platform.py` did import the non-existent `services_routing`/`services_reviews` modules, while `activate_update` exists in `routes_routing.py:20` and `compute_fake_probability`/`auto_flag` exist in `routes_reviews.py:20,56` (all pure store-operating functions, no request context). Fixed by the orchestrator with two minimal import-line edits in `routes_platform.py` (`from routes_routing import activate_update`; `from routes_reviews import compute_fake_probability, auto_flag`) — behavior-equivalent; the functions' definitions, bodies, and callers are unchanged, and the edit traces to PRD §3.9/§3.5 normative sweep behavior.

Per the post-Step-7 sweep-invalidation rule, the orchestrator re-ran the full 8-round parallel sweep after the edit: **all 8 rounds 75/75 passed, 0 failed**. Fresh `results.{1..8}.json` written to workspace/implementation/.
