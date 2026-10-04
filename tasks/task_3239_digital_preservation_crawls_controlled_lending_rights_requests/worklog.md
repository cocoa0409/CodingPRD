# Worklog — task_3239_digital_preservation_crawls_controlled_lending_rights_requests

## Step 1: Create Task Directory — 2026-09-30T13:00:00.000Z

Task directory was pre-allocated by the caller: `tasks/task_3239_digital_preservation_crawls_controlled_lending_rights_requests/workspace/`. Verified existence; no new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T13:52:21.000Z

All three artifacts are written and the lint verdict is clean. Final report:

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3239_digital_preservation_crawls_controlled_lending_rights_requests/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (envelope, entities, state machines, concurrency, calculations, validations, endpoints, errors, RBAC)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 9 rules × 2 instances = **18 instances**
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 9 sections, **44 instances (41 active + 3 `excluded_because` stubs)**

**Counts:** 14 entities, 55 endpoints, 23 error codes, 9 roles, 23 ordered validations, 12 state machines (39 transitions), 7 calculations, 2 OCC concurrency rules. Lint: **474 calls scanned, 0 violations** (all endpoint/role/payload/capture/OCC checks + FK reverse-reachability pass).

**Difficulty design decisions (pushed past expert):**
- **Archetype blend:** quota/allocation (loan caps, grant budget, waitlist offers) × compliance/audit (rights requests with segregation-of-duties: filer ≠ reviewer ≠ decider, officer ≠ self).
- **Dual-variant calcs on different domains:** playback nearest-vs-latest selection (Capture) vs provisional-embargo vs hard-withdrawal availability (Work/RightsRequest).
- **Combinatorial formulas in distinct modes:** mode (a) 3+-input non-linear playback resolution with directional tie-break + dynamic-content branch; mode (c) pinned evaluation order on the grant settle→counters→utilization→status→creation-gate dependency.
- **Non-linear machines on different entities:** FundingGrant OPEN↔EXHAUSTED cycle vs RightsRequest fork with divergent cascades per branch.
- **Transitive cascades from different triggers:** sweep-expiry depth-4 (loan→strike→suspension→offer-cancel) vs rights-hold depth-3 (hold→availability→loan-revocation→item/counter/promotion).
- **Validation priority conflicts in different category pairs:** state-vs-fiscal (4 vs 19) and standing-vs-temporal (7 vs 16).
- **Boundary precision on different metrics/endpoints:** grant cents equality (== amount triggers EXHAUSTED, +1 rejects) vs discrete strike count (==3 suspends, 2 stays ACTIVE).
- **Temporal overlap with different interval semantics:** half-open loan expiry/offer window (strict <) vs closed-start crawl scheduling (>=).
- **Compensating invariants on different quantities:** grant reserve↔release/settle cents conservation vs checkout↔return loan/counter/item occupancy conservation.

**Notable structural choices:** waitlist is per-work with a selector-policy promotion (transient cap skip, terminal suspension cancel, earliest-created item claim); capture dedupe returns the pre-existing row with 200 vs 201; `POST /archive/captures` carries `crawl_job_id` in the body (needed for lint segment derivation); logical clock with mandatory startup default `2026-09-01T00:00:00Z`; 55 endpoints (above the ≤40 soft cap) because the lint mechanically requires both single-resource GETs and sub-resource reverse-reads for FK reachability — business actions stay tight while reads provide the required coverage.

Orchestrator note: endpoint count 55 exceeds the historical ≤40 impl-gen safety threshold (memory: scaffold-endpoint-overshoot-breaks-impl-gen). Subagent reports the count is lint-mandated (FK reverse-reachability reads). Proceeding with heightened verification of Step 6 output files on disk; will re-spawn impl-gen if it returns a report instead of files.

## Step 3: Copy Shared Files — 2026-09-30T13:52:21.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3239_digital_preservation_crawls_controlled_lending_rights_requests/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T14:01:34.000Z

All contracts pass. One more fidelity concern: §3.2 says withdrawal "executed by a `LibraryAdmin`" — that matches the endpoint table (which does include withdraw). Good.

**Output:** `workspace/PRD.md` — 312 lines.

**Section list:**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 RBAC (9 roles, identity semantics), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Logical Clock (incl. `Capture` carrying only `id`+`created_at`), 2.5 Validation Order of Operations (23 explicit priorities), 2.6 OCC (`expected_entry_version`, `expected_grant_version`, `ERR_STALE_VERSION`/412), 2.7 Monetary & Tiered Storage Pricing, 2.8 Expiry Sweep, 2.9 Hierarchical Reads
- §3 Business Logic: 3.1 Patrons/Accessibility, 3.2 Works/Partner Libraries, 3.3 Scanning, 3.4 Lending (checkout/return/renewal), 3.5 Waitlists, 3.6 Crawl Jobs/Exclusions, 3.7 Captures/Dedupe/Storage/Playback, 3.8 Rights Requests, 3.9 Funding/Budget Lines
- §4 Endpoint Definitions — 55 rows, exact match to the scaffold's 55 endpoints (initially added 4 rows for state-machine-only transitions — scan-batch reject, item retire, crawl-job cancel, waitlist cancel — and removed them; the corresponding §3 prose now marks those transitions as declared-but-not-exposed in v1)
- §5 Error Code Catalogue — all 23 error IDs with HTTP statuses

**Hard contract reports:**
- Contract 1 (field-name coverage): 79 required names (entity fields + endpoint inputs/query params + common fields), 79 present, 0 missing — PASS
- Contract 2 (rule coverage): 23 validation priorities expressed in explicit order; both OCC rules with field + error + status; all state-machine transitions, preconditions, and side effects in prose; all 7 calculations in reconstructible prose; all error IDs trigger-matched in §2/§3 — PASS
- Contract 3 (§3 path purity): 472 backtick tokens scanned in §3, 0 paths/methods — PASS

Notable fidelity corrections during drafting: fixed a self-contradiction in the offer-expiry sentence, aligned credential SoD to apply only to VERIFY (per the scaffold's transitions), and marked the four endpoint-less state-machine transitions (batch reject, item retire, job cancel, entry cancel) as declared-but-unexposed rather than implying live endpoints.

## Step 5: Generate Unit Tests — 2026-09-30T14:17:09.000Z

All 73 tests collect cleanly.

**Files created**

`test_helpers/` (9 files):
- `types.py` — status enums, role enum, TypedDicts (Capture correctly omits `updated_at`/`version` per PRD 2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint
- `api_errors.py` — all 23 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + grant counter invariant
- `factories.py` — payload factories with auto-unique emails/codes
- `constants.py` — domain thresholds (caps, terms, tiers, bounds)
- `test_users.py` — shared headers for opaque roles; `make_patron_headers(user_id)` builder for the entity-backed Patron role
- `fixtures.py` — composite helpers: clock/sweep, library+work+batch+items with seal, checkout, waitlist join, verified-credential patron, running crawl job, rights-request pipeline, grant/budget-line helpers
- `__init__.py` — barrel export

`test_suite/` (7 files):
- `conftest.py`, `test_01_entities_creation_and_listing.py` (9), `test_02_validations_and_rbac.py` (10), `test_03_state_machines_and_sod.py` (11), `test_04_calculations.py` (4), `test_05_endpoints_occ_and_cascades.py` (7), `test_06_playback_resolution.py` (4), `test_07_grants_and_invariants.py` (10), `test_08_rights_requests_depth.py` (8), `test_09_sweeps_strikes_and_temporal.py` (10)

**Coverage**
- **Queue A (Difficulty): 16/18 instances covered, 2 tests each.** Skipped: `priority_pair_validation_conflict/state_precondition_vs_grant_fiscal_capacity` and `priority_pair_validation_conflict/patron_standing_vs_waitlist_temporal_window` — both require testing that one error pre-empts another at identical trigger conditions; PRD §2.5's ordering sentence is generic and does not uniquely derive the winner, so unique derivability fails.
- **Queue B (Corner): all 41 non-stub instances covered, 1 test each; 3 `excluded_because` stubs not translated.**

**73 tests total**, every docstring carries exactly one verbatim `Design:` tag resolving to a real instance (verified programmatically), plus verbatim PRD citations. `pytest --collect-only` passes cleanly (73 collected, 0 errors). Test execution left to Step 7.

## Step 6: Generate Implementation — 2026-09-30T14:33:33.000Z

Implementation complete. Summary:

**Files written under `workspace/implementation/`**

| File | Lines |
|---|---|
| `start.sh` | 8 |
| `requirements.txt` | 1 |
| `app.py` | 48 |
| `db.py` | 34 |
| `errors.py` | 51 |
| `response.py` | 93 |
| `middleware.py` | 44 |
| `models.py` | 291 |
| `services.py` | 215 |
| `routes/__init__.py` | 0 |
| `routes/system.py` | 96 |
| `routes/patrons.py` | 133 |
| `routes/libraries_works.py` | 103 |
| `routes/scanning.py` | 178 |
| `routes/loans.py` | 188 |
| `routes/waitlist.py` | 179 |
| `routes/crawl.py` | 297 |
| `routes/rights.py` | 147 |
| `routes/funding.py` | 166 |

**Boot confirmation:** `bash start.sh` with `PORT=18329` boots cleanly, binds 0.0.0.0 in foreground via `exec python3 app.py`, guards `pip install` behind a `python3 -c "import flask"` check. Smoke test exercised and passed: 401 auth gate, clock set/read, patron create + case-insensitive duplicate rejection, work/library/batch/item/seal chain (SEALED), checkout (due_at = clock+14d), renew, return, grant budget-line OCC (stale version → ERR_STALE_VERSION 412, correct version → SETTLED with grant flipping EXHAUSTED→OPEN), crawl schedule-not-due gate, capture dedupe (201 then 200 with duplicates_skipped increment), playback FULL resolution, waitlist offer promotion on return, offer expiry via sweep with EXPIRED_OFFER transition. Only the self-started PID was killed.

**Notable implementation decisions:**
- **Module split**: `db.py` (stores + logical clock, default 2026-09-01T00:00:00Z), `errors.py` (error-id catalog with HTTP codes), `response.py` (envelope + pagination limit/offset/total_count/has_more defaults 10/0, min 1, max 100), `middleware.py` (X-User-Role/X-User-ID auth), `models.py` (serializers + derived projections: `item.lendable`, `patron.max_concurrent_loans`, `work.availability` recomputed live from rights requests), `services.py` (waitlist promotion, loan-end cascade incl. 4-hop strike→suspension→OFFERED-cancel, work availability recompute + withdrawal/recovery cascades, capture dedupe/storage cost with per-tier ROUND_HALF_UP via Decimal, grant recompute), and 9 route blueprints.
- **Work availability** is derived on read plus a `_availability_cache` on the work so transitions can detect AVAILABLE→WITHDRAWN and fire the loan-revocation cascade, and WITHDRAWN/EMBARGOED→AVAILABLE to re-promote DEPOSITED items in sealed batches.
- **Validation ordering** follows the 23-priority gauntlet inline in each handler: auth → role/ownership → existence (left-to-right FK) → state → SoD → schema → business rules in scaffold priority order, OCC last at priority 23.
- **OCC** only on the two scaffold-declared endpoints: `expected_entry_version` on waitlist claim and `expected_grant_version` on budget-line settle/release, both returning ERR_STALE_VERSION 412 after all other checks.
- **Storage cost** computed per tier with `Decimal` ROUND_HALF_UP then summed.
- **Captures** omit `updated_at`/`version`; all other entities carry `created_at`/`updated_at`/`version` with version starting at 1 and `touch()` bumping on every mutation.
- **Sweep** orders loans by (due_at, created_at), offers by offer_expires_at, applies full per-loan cascades before the next, and reports `expired_loan_ids`/`expired_offer_ids`/`suspended_patron_ids`/`offered_entry_ids`.
- No entity seeding at startup; all stores are empty dicts keyed by UUID.

Orchestrator verification: all 19 files confirmed on disk with the reported line counts (2272 lines total).

## Step 7: Run Tests and Iterate — 2026-09-30T14:55:27.000Z

All 8 rounds pass 73/73. Clean sweep achieved.

Summary:
- Iterations run: 3 (8-round parallel sweeps each; final sweep 73/73 in all 8 rounds).
- Tests deleted: none — every failing test traced to a verbatim PRD sentence; fixes went to the artifact layer that was actually wrong.
- Fixes applied to `test_helpers/`:
  - `test_helpers/test_users.py` — `anonymous_headers` now carries `X-User-Role: Anonymous` (and still no `X-User-ID`). PRD 2.1 makes Anonymous a declared role sent in `X-User-Role`; the previous headerless form conflated "anonymous" with "unauthenticated" and caused 38 cascade 401s.
- Fixes applied to `test_suite/`:
  - `test_09_sweeps_strikes_and_temporal.py::test_sweep_expiry_to_patron_suspension_cascade_third_expiry_suspends` and `..._cancels_offered_entries` — fixtures took two loans on two items of the same work and later re-checked-out the same work while a live OFFERED entry existed; both violate PRD 3.4 (one ACTIVE loan per work per patron; waitlist priority over walk-up checkout). Restructured so the three strikes come from loans on three distinct single-copy works, keeping the OFFERED entry on the first work.
  - `test_05_endpoints_occ_and_cascades.py::test_waitlist_claim_occ_happy_path_and_stale_replay` — the "stale replay" assertion demanded ERR_STALE_VERSION on a terminally CLAIMED entry, but PRD 2.5's priority ordering (state precondition at 6, OCC at 23) plus PRD 3.5's "CLAIMED ... terminal" uniquely derive ERR_INVALID_STATE there. Split: same-token replay on the CLAIMED entry now asserts ERR_INVALID_STATE; the ERR_STALE_VERSION path is exercised on a fresh live OFFERED entry whose version advanced via offer expiry/re-promotion (exactly the scenario PRD 2.6 names).
  - `test_08_rights_requests_depth.py::test_rights_hold_to_loan_revocation_cascade_offers_waitlist` — assertion now expects the entry to stay OPEN with `offered_at` null after escalation: the revocation cascade runs promotion, but the WITHDRAWN availability flips the `lendable` projection false (PRD 3.3's three-leg definition), so the supply check ends the run with no offer.
- Fixes applied to `implementation/`:
  - `workspace/implementation/services.py` — `end_loan()` gained `defer_promotion`; `recompute_work_availability_and_effects()` now revokes loans with promotion deferred and runs `run_promotion(work_id)` once after the availability cache flip, so promotion sees the withdrawn work's lendable=false projection (previously the per-loan promotion fired while availability was still EMBARGOED/AVAILABLE and could issue a spurious offer).

Orchestrator verification: read all 8 results.{1..8}.json files on disk — each reports 73/73 passed, 0 failed. Confirmed independently of the subagent's report.

## Step 8: Finalize PRD — 2026-09-30T14:58:29.000Z

Done. `PRD_FINALIZED.md` is written with a single targeted edit.

**Line counts / delta:** PRD.md 312 lines, PRD_FINALIZED.md 312 lines; 1 line modified in place (+0.0% line delta; one sentence in section 3.8 replaced by three).

**Changes:**
- **Section 3.8 (Rights Requests: escalation cascade) — revise —** replaced "and waitlist promotion runs per affected work" with an explicit pinning that the availability flip to `WITHDRAWN` takes effect before any promotion runs, and that one promotion run executes once per work after all of that work's loan revocations complete (not once per revoked loan), so the supply check sees the withdrawn work's `lendable=false` projection and issues no offer — `workspace/implementation/services.py:97-117`.

**Step 7 items with no PRD edit (with rationale):**
- `test_helpers/test_users.py` `anonymous_headers` — PRD 2.1 already uniquely requires `X-User-Role: Anonymous` with no `X-User-ID`; the old helper contradicted the PRD. Fixture bug, prose kept verbatim.
- `test_09` sweep/strike fixtures — pure fixture violations of PRD 3.4 rules the PRD already pins.
- `test_05` stale-replay assertion — PRD 2.5's ordering plus 3.5's "CLAIMED ... terminal" already uniquely derive `ERR_INVALID_STATE` on a CLAIMED entry; implementation confirms the state check runs first. No PRD silence.
- `test_08` rights-hold expectation — the corrected assertion follows from PRD 3.3's three-leg `lendable` definition; only the promotion-sequencing silence behind it needed pinning (the edit above).

**Per-edit pre-edit search log:**
- **Edit 1 (Section 3.8 promotion-sequencing sentence):** (a) Subject: when waitlist promotion runs relative to a work's availability flip during rights-driven loan revocation, and how many promotion runs the cascade issues. (b) Paths enumerated: `services.py` `run_promotion` (16-50), `end_loan` (55-92), `recompute_work_availability_and_effects` (97-128), `apply_rights_request_cascade` (179-186); all `end_loan`/`run_promotion` call sites via grep — `routes/system.py:53,68`, `routes/loans.py:156`, `routes/waitlist.py:68,178`, `routes/scanning.py:70`, `routes/rights.py:103,120,143,146`; confirmed no item-retirement route exists. Also verified `models.py:25-28` `touch()` increments version. (c) Wording scoped explicitly to the hard-withdrawal cascade so it does not re-scope the generic per-loan promotion statements in 3.3/3.5, which remain accurate for return, expiry, and the (unexposed) item-retirement path.

Orchestrator verification: PRD_FINALIZED.md exists at 312 lines (same as PRD.md, 1 line revised in place as reported).

## Step 9: Complete PRD — 2026-09-30T15:09:25.000Z

Done. PRD_COMPLETED.md is written as a minimal patch over PRD_FINALIZED.md.

**Source vs output**: `PRD_FINALIZED.md` 312 lines / 49,539 chars → `PRD_COMPLETED.md` 313 lines / 51,370 chars (+1 line, +1,831 chars; 25 changed/added diff lines).

**Counts**: 12 ambiguity-pins, 1 mismatch-revision (the mismatch revision is the grant-close error id; all other edits pin silent behavior).

**Changes** (all inserts inline; no new sections):
- §2.2 Error Response Format — insert — ambiguity — unmatched paths and unsupported methods are answered with `ERR_NOT_FOUND` (404) — implementation/app.py:28-34
- §2.3 Pagination — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION`; `has_more` = `offset + len(page) < total_count` — implementation/response.py:63-93, 43
- §2.4 Logical Clock — insert — ambiguity — a `to_iso8601` without timezone offset is interpreted as UTC — implementation/routes/system.py:31-33
- §2.6 OCC — insert — ambiguity — `expected_entry_version` must be an integer; missing/non-integer → `ERR_VALIDATION` — implementation/routes/waitlist.py:134-136
- §2.6 OCC — insert — ambiguity — same integer-token schema rule for `expected_grant_version` — implementation/routes/funding.py:123-128
- §3.5 Waitlists — insert — ambiguity — join response echoes the entry post-promotion, so it may be returned already `OFFERED` — implementation/routes/waitlist.py:68-69
- §3.6 Crawl Jobs — insert — ambiguity — `scheduled_at` is stored and echoed verbatim as supplied (no normalization) — implementation/routes/crawl.py:69
- §3.6 Directive Retract — revise — mismatch — restoration is blocked by a rights request in `LEGAL_HOLD` **or** `UPHELD_REMOVED` (PRD said only "upheld") — implementation/services.py:164-176, 136-143
- §3.7 Captures — insert — ambiguity — dedupe scope is global across all jobs, not per-job; a new capture immediately refreshes `storage_cost_cents` — implementation/routes/crawl.py:147-164
- §3.7 Playback — insert — ambiguity — invalid `requested_at` → `ERR_VALIDATION`; `SUPPRESSED`/`NOT_FOUND` responses null all three of `capture_id`, `captured_at`, `has_dynamic_content` — implementation/routes/crawl.py:203-234
- §3.8 Rights Decisions — insert — ambiguity — dismissing a `CAPTURE_URL_PREFIX` request does not restore suppressed captures — implementation/services.py:179-186, routes/rights.py:142-146
- §3.8 Availability Recompute — insert — ambiguity — each recomputation stamps the work's `updated_at`/`version` even when the derived availability is unchanged — implementation/services.py:97-106
- §3.9 Grant Close — insert — ambiguity — close with non-zero `reserved_cents` → `ERR_VALIDATION`; close from a status other than `OPEN`/`EXHAUSTED` → `ERR_INVALID_STATE` — implementation/routes/funding.py:54-57

Everything else in the implementation (all endpoints, cascades, sweep ordering, tiered storage pricing with per-tier ROUND_HALF_UP, promotion ordering, SoD rules, strike/suspension cascade, OCC rotation, error catalog) was already uniquely pinned by PRD_FINALIZED.md and required no change.

Orchestrator verification: PRD_COMPLETED.md exists on disk at 313 lines / 51,370 chars, matching the report exactly.

## Pipeline Complete — 2026-09-30T15:09:25.000Z

All 9 steps finished. Final state: 73/73 tests passing in all 8 rounds of the final stability sweep; 0 tests deleted during iteration; full artifact set present (SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ ×9, test_suite/ ×9+conftest, workspace/INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ ×19 files, results.{1..8}.json all passing).
