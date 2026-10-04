# Worklog — task_3389_cohort_scholar_selection_partner_placement_campus_support

## Step 1: Create Task Directory — 2026-10-01T13:56:00.000Z

Task directory pre-allocated by caller: `tasks/task_3389_cohort_scholar_selection_partner_placement_campus_support/` with `workspace/` inside. Verified existence; no index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-01T15:45:00.000Z

All three artifacts are complete, parse cleanly, and pass `scaffold_lint.py` with `VERDICT: clean lint` (1,713 recipe calls checked against the endpoint table, zero violations; all 16 FKs reverse-reachable).

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_3389_cohort_scholar_selection_partner_placement_campus_support/`)

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key, 18 instances (9 rules × 2)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key, 49 live instances + 18 `excluded_because` stubs = 67 entries

## Counts

| Metric | Count |
|---|---|
| Entities | 13 |
| Endpoints | 40 (at the ~40 cap) |
| State machines | 9 entries (7 entities; Scholar carries two independent axes) |
| Calculations | 10 (all constants pinned to literals) |
| Validation tiers | 12 ordered priorities |
| Errors | 26 (every one fired by a named instance — cross-check comment in the corner file) |
| Roles | 8 (4 entity-backed: Nominator, Nominee, FacultyMentor, Scholar) |
| §1.8 instances | 18 (2 per rule, all differentiation clauses honored) |
| §1.9 instances | 49 live + 18 stubs |

## Difficulty profile (per the "harder than expert" instruction — depth, not breadth)

Quota/allocation core + workflow orchestration; dual-variant calcs on two domains (cohort fill projection 3-vs-1; census-vs-rolling outcome rates 5000-vs-3333 bps); combinatorial modes (a) min-dimension cap (499 vs 820 on a 1-point flip) and (b) pinned per-scholar-then-sum invoice rounding (653086 vs 653087); cascades of depth 4 (withdrawal → offer revoke → seat decrement → LOCKED→FORMING revert → waitlist promotion) and depth 3 (last terminal scholar → cohort COMPLETED → agreement FULFILLED → college PROBATION); validation priority pairs (state×fiscal, temporal×fiscal); inclusive boundaries (lock at exactly cohort_size, cutoff at exactly 600, expiry strictly-past-deadline, window inclusive close); two interval-overlap semantics (mentor 15-minute buffer vs scholar inclusive-date); two compensating invariants (seat ledger, nomination quota); one OCC rule (agreement create vs PartnerCollege.version, 412).

## Interpretations I chose (scenario left open)

1. **Cohort size band pinned to [3, 6]** (real-world ~10 would triple every setup chain; rule depth is unaffected).
2. **Three assessment rounds** with cutoffs 600/700/800 over a 1000-point weighted score (4L+3T+3G, dimension floor 40 caps at 499); ≥2 evaluations per round, round-half-up averages.
3. **Logical clock** (`POST /api/_clock/set_current_utc`, default 2026-09-01T00:00:00Z) drives the 14-day offer-expiry sweep and nomination windows; all fixture dates verified ≥ clock start.
4. **Dead-code guard:** I removed the cohort-FORMING precondition from offer *accept* after replay proved it unreachable (create-gate + lock rule imply OFFERED ⇒ FORMING); the gate lives on offer *create* instead.
5. **Matriculate ordering pinned** (cohort flips MATRICULATED first, suppressing revert/promotion cascades mid-batch; scholars processed created_at ASC; untrained → WITHDRAWN, no seat refill).
6. **Outcome rates:** null (not 0) on empty denominators; pre-matriculation withdrawals excluded via `ever_matriculated`; census variant is authoritative for renewal (8000/6000 bps thresholds), probation floor 7000, recovery 8000.
7. **Individual check-ins** folded into `CohortMeeting` (kind=INDIVIDUAL + validated non-FK `scholar_id`) to stay under the endpoint cap.
8. **No `id`-based tie-breaks anywhere** — waitlist ranking is `round_3_score DESC, created_at ASC`; empty waitlist is a no-op, not an error.

One process note: an early heredoc append corrupted the corner file (leaked delimiter + command text at lines 141–142); I caught it via the per-append parse check, switched to write-part-file-then-`cat`-append for all remaining chunks, and re-verified — no residual damage.

Orchestrator verification: all three YAMLs parse; SCAFFOLD.yaml confirmed free of both design keys; domain vocabulary present (cohort×211, scholar×138, nomin×238, partner×90, mentor×58); endpoint table = 40 entries.

## Step 3: Copy Shared Files — 2026-10-01T15:46:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T15:58:00.000Z

All contracts verified. The PRD is complete and passes every hard check.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3389_cohort_scholar_selection_partner_placement_campus_support/workspace/PRD.md` — 341 lines, written in 10 verified chunks (each append confirmed via `wc -l`/`tail` before continuing).

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (all 8 roles with identity bindings), 2.2 API Response Structure (verbatim block, byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ASC + `module_code` ASC exception), 2.4 Logical Clock & Offer Expiry (boot at 2026-09-01T00:00:00Z, strict-less-than sweep, 14-day TTL), 2.5 Resource Identity/Timestamps/Versioning (incl. Evaluation carrying only `id`+`created_at`), 2.6 OCC on Partnership Drafting (`expected_college_version` → `ERR_STALE_VERSION` 412), 2.7 Validation Pipeline (all 12 tiers in priority order), 2.8 Scoring/Rounding/Precision, 2.9 Nested Resources & Filtering
- §3 Business Logic: 3.1 city programs/quotas, 3.2 assessment rounds, 3.3 colleges/agreements/mentors, 3.4 cohort formation/seat ledger, 3.5 offers/waitlist promotion, 3.6 matriculation/invoice, 3.7 scholar lifecycle/training, 3.8 meetings/internships, 3.9 outcomes/standing/renewal
- §4 Endpoint Definitions (40 rows, 4 columns)
- §5 Error Code Catalogue (26 rows, 2 columns)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs/query/path + outputs + common fields:
  70 required, 70 present, 0 missing (one miss, `category`, found and repaired)
Status: PASS

Rule coverage check:
- validations[] priority: 12 tiers expressed in order; within-tier-8 ordering
  (nominee → cohort → other) and within-tier-12 ordering (count before cutoff) stated
- concurrency_rules[]: 1/1 expressed (write_endpoint + expected_college_version +
  ERR_STALE_VERSION/412, no race framing)
- state transitions: all 9 machines, every from/to/precondition/side-effect expressed
- calculations[]: 10/10 expressed with all constants (4/3/3 weights, 40 floor, 499 cap,
  2-eval minimum, 600/700/800 inclusive cutoffs, 7500 bps provisional weight,
  250000 + 125 bps fee with pinned per-line rounding and the 6123460 → 653086 vs
  653087 worked example, 7000/8000 standing derivation, 8000/6000 renewal gate,
  census vs rolling variants)
- endpoints[] side_effects / applies_to: all expressed (accept cascade, drop→revoke→sweep,
  matriculate Steps 1–4, completion cascade, LAPSE cascade, supersede + version bump)
- sibling-branch symmetry: round gates, lifecycle branches, projection variants symmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 510; paths: 0; bare methods: 0; method+path combos: 0
Status: PASS
```

**Notable finding:** the scaffold header comment claims "27 codes" but the actual `errors[]` catalog contains 26 entries; the PRD §5 table matches the 26 real entries exactly (verified by diffing extracted IDs against the scaffold). Every scaffold calculation, validation, error, and state machine appears as quotable prose with literal constants and explicit boundary inclusivity; no fuzzy wording or operator pseudocode survives in the document.

Orchestrator verification: PRD.md = 341 lines; spot-checked tokens present (2026-09-01 ×1, ERR_STALE_VERSION ×3, 653087 ×1, 8000 ×2, MATRICULATED ×16, _clock ×1); file ends with the §5 error catalogue (not truncated).

## Step 5: Generate Unit Tests — 2026-10-01T16:20:00.000Z

All green. Generation complete — final state verified by AST tag audit, verbatim PRD-citation sweep, and a real `pytest --collect-only` (85 collected, no import breakage).

## Summary

**Helpers (`test_helpers/`, frozen before any test was written):**
`__init__.py` (barrel), `types.py` (13 TypedDicts + 16 enums; Evaluation correctly omits `updated_at`/`version` per PRD §2.5), `constants.py` (all literals from PRD: clock boot 2026-09-01T00:00:00Z, weights 4/3/3, floor 40/cap 499, ≥2 evals, cutoffs 600/700/800, quota 1–20, cohort size 3–6, 14-day TTL, 7500 bps, 250000+125 bps fee, 7000/8000 standing, 8000/6000 renewal, 15-min buffer, 8 modules, pagination 10/1/100), `api_errors.py` (27 ids + status map registered), `api_client.py` (35 endpoint methods), `test_users.py` (shared opaque-role headers + `make_*_headers` for the 4 entity-backed roles), `assertions.py`, `factories.py`, `fixtures.py` (nominee pipeline to SELECTED/WAITLISTED, locked/matriculated/completed cohorts, OCC-safe agreement drafting, identity threading for accept/decline/withdraw/meeting/self-lifecycle).

**Tests (`test_suite/`, 10 files, 85 tests):** test_01 programs/nominations/quota, test_02 assessment rounds/cutoffs, test_03 partnerships/agreements/renewal, test_04 seat ledger/offers, test_05 waitlist/clock sweep, test_06 matriculation/invoice, test_07 scholar lifecycle/cascades, test_08 outcome rates, test_09 meetings/internships, test_10 auth/RBAC. Creates assert 201 explicitly; every fixture date ≥ clock boot; clock advances monotonic within each test.

**Audit (all clean):** 18/18 difficulty instances with exactly 2 tests each; 49/49 live corner instances with 1 test each; 18 `excluded_because` stubs correctly untested and every stub's `difficulty_instance` pointer resolves; every test has exactly one `Design:` tag as its docstring's last line; 138 citation fragments verbatim-match PRD.md; no skip/skipif/xfail.

**PRD gaps / derivability notes:** No instance was skipped. Two two-reader adjustments: (1) PRD pins "version increments on every mutation" but not its initial value — helpers assert type only and the OCC tests assert the +1 relative increment, so `city_program_creation_stamps_system_fields` is covered by its pinned claims (201, UUID id, `created_at` == boot instant, GET consistency) without hard-coding version==1; (2) a created_at-ASC list-order assertion in the supersede test was dropped because both agreements share the boot timestamp and PRD pins no tie-break.

Orchestrator verification: independent `pytest --collect-only` run collected 85 tests with no errors; `grep` of Design tags yields 67 unique tags (18 difficulty ×2 tests + 49 corner ×1 = 85 ✓).

## Step 6: Generate Implementation — 2026-10-01T16:50:00.000Z

Implementation complete. All work is in `/home/ubuntu/github/CodingPRD/tasks/task_3389_cohort_scholar_selection_partner_placement_campus_support/workspace/implementation/`.

## File list (17 source files + start.sh + requirements.txt, 2,157 lines)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Launcher: guarded `pip install` (no-op when flask present), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0,<4` |
| `app.py` | 53 | Flask assembly, envelope-wrapped 404/405/500 handlers, `0.0.0.0:$PORT` (default 10000) |
| `constants.py` | 120 | Every pinned PRD literal: clock boot `2026-09-01T00:00:00Z`, weights 4/3/3, floor 40, cap 499, ≥2 evals, cutoffs 600/700/800, cohort size [3,6], 14-day TTL, 7500 bps, fee 250000+125bps, standing 7000/8000, renewal 8000/6000, pagination 10/1/100, all enums and transition tables |
| `core.py` | 96 | In-memory store (empty at boot, no seeding), logical clock, UUID ids, ISO8601-3f timestamps, `rhu()` (Decimal ROUND_HALF_UP), add/touch with version |
| `errors.py` | 39 | `ApiError` + all 27 error IDs |
| `response.py` | 53 | Envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` |
| `ledger.py` | 71 | Computed-on-read fields: `nominations_used`, seat ledger, round evals, training count, meeting count — invariants cannot drift |
| `serialize.py` | 54 | Serializers with computed cohort/scholar/partner fields (both fill projections, alumni flag) |
| `validate.py` | 140 | Tier 1 auth, tier 2 shape validators, tier 3 role check, lookup (404), pagination params |
| `services.py` | 176 | Offer-expiry sweep (strict `<`, `created_at` ASC), waitlist promotion sweep (`round_3_score` DESC, created ASC, never id), pre-collegiate withdrawal cascade with LOCKED→FORMING revert, outcome rates (census/rolling), standing derivation, cohort completion |
| `routes_clock.py` | 34 | `POST /api/_clock/set_current_utc` |
| `routes_recruitment.py` | 393 | City programs, partners, nominees (create/list/get/withdraw/decision), evaluations |
| `routes_partnership.py` | 248 | Colleges, outcomes readout, renewal-review, mentors, OCC-guarded agreements + activate |
| `routes_cohorts.py` | 157 | Cohort create/list/get + 4-step matriculate with pinned invoice rounding |
| `routes_offers.py` | 150 | Offer create/list/get/accept/decline |
| `routes_scholars.py` | 167 | Scholar list/get, training-records (module_code ASC), internships list, two-axis lifecycle, training complete |
| `routes_campus.py` | 195 | Cohort meetings (15-min buffer rule) + internships (inclusive overlap, confirm-time standing recheck) |

**Endpoint count: 40/40** (verified by counting route decorators against the endpoint table).

## Smoke tests (self-run, no pytest — isolation rule honored)

- Boot: `PORT=$(( (RANDOM % 20000) + 30000 )) bash start.sh` (bound 31412, then 33971 after restart); readiness via curl loop; killed exactly the PIDs started (verified via `ss -tlnp` + `ps` that they were the `python3 app.py` processes; port confirmed free afterward).
- Suite 1 (47 checks, ALL PASS): auth 401s, 404 envelope, shape-beats-role tier ordering, quota bounds at tier 2, nominee ownership 403, NOMINATED→ROUND_1 free advance, insufficient-evals 422, wrong-round 409, weighted score 800, duplicate-evaluation 409, floor cap (39,100,100)→499, round-half-up average 750, cutoffs inclusive, OCC 412 + version bump to 2, cohort_size 7→422 at tier 10, offer TTL = created+14d, accept cascade (scholar + 8 training records T1..T8, nominee PLACED), clock set/before-boot-400/role-403, outcomes null rates, pagination bounds.
- Suite 2 (48 checks, ALL PASS): WAITLIST without cutoff, LOCKED at 3 committed, scholar self-withdraw → LOCKED→FORMING revert + promotion sweep (D promoted, fresh 14-day offer), decline → empty-pool no-op sweep, expiry boundary (`expires_at == now` survives, `< now` expires), expired offer accept → 409, matriculation invoice = 3 × (250000 + rhu(6123460×125/10000)) = 979629 with pre-withdrawn scholar excluded, offers FULFILLED, mentor buffer rule (11:14 conflicts, 11:15 passes), internship boundary-date overlap 422, standing frozen when terminal, completion cascade → agreement FULFILLED + census 6667/6667 → college PROBATION, RENEW 422, draft-on-PROBATION allowed but activate 409, LAPSE expires DRAFTs, draft-on-LAPSED 409.

## Bug found and fixed during smoke

Matriculation Step 3 initially applied the training gate to **all** cohort scholars, resurrecting an already-WITHDRAWN scholar with 8/8 training to MATRICULATED and billing them (invoice 1306172 instead of 979629). Fixed by skipping non-PRE_COLLEGIATE scholars, per PRD 3.6's invoice input set ("pre-existing MATRICULATED or WITHDRAWN scholars excluded").

## PRD ambiguities resolved (interpretation chosen)

1. **Entity timestamps use the logical clock** — PRD 2.4 says *all* time-dependent behavior is logical-clock-driven, and `expires_at = created_at + 14d` is meaningless otherwise; `meta.api_request_timestamp` uses wall clock (PRD's own example timestamp predates the boot instant).
2. **Lifecycle `to_enrollment_status` accepts any declared enum value** (incl. MATRICULATED) at shape tier, rejected at state tier — PRD 3.7 explicitly says requesting MATRICULATED yields `ERR_INVALID_STATE`, not 400.
3. **Evaluation round check is status-based** (`status == ROUND_N`), not `current_round`-based — PRD/scaffold call the two equivalent but they diverge for WAITLISTED/SELECTED nominees (current_round stays 3); scaffold validation tier 8 states the status form.
4. **Cohort completion check runs only on post-matriculation terminal transitions** — the scaffold's PRE_COLLEGIATE→WITHDRAWN side effects omit the completion check while MATRICULATED/RETAINED→terminal include it; matriculate's pinned 4 steps also omit it.
5. **Combined enrollment+standing lifecycle call**: both transitions validated up-front (atomic), enrollment applied first, standing validated against the post-enrollment state (enforces the terminal freeze).
6. **Internship CONFIRMED re-checks standing only** (PRD 3.8 prose wins over the broader error-catalog wording that also mentions enrollment).
7. **Clock-set is not monotonic** — PRD pins only `to_iso8601 >= 2026-09-01T00:00:00Z`; no backward-set guard was invented.
8. **Initial `version` = 1**, incremented per mutation; drafting an agreement bumps the college exactly +1 per PRD 2.6.
9. **created_at ties** (same logical instant) break by insertion order for list sort and waitlist ranking — consistent with created_at ASC; `id` never used.

Orchestrator verification: all 17 .py files compile; start.sh is a foreground launcher with guarded pip install; app.py binds `0.0.0.0:$PORT`; 40 route registrations counted (matches endpoint table); constants.py literal counts match PRD.md counts exactly for 2026-09-01/600/700/800/499/7500/250000/7000/8000.

## Step 7: Run Tests and Iterate — 2026-10-01T17:10:00.000Z

Clean sweep achieved: all 8 rounds pass 85/85, and all 8 `results.${i}.json` artifacts remain in `workspace/implementation/`.

## Summary

- **Iterations run:** 2 (initial sweep → fix → final clean 8-round sweep).

- **Tests deleted:** none. Both failing tests traced to verbatim PRD sentences with uniquely derivable outcomes.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:** two, both confirmed as implementation bugs against verbatim PRD text.

  1. `workspace/implementation/services.py` — `withdraw_scholar_pre_collegiate`: the waitlist promotion sweep ran only inside the `LOCKED → FORMING` revert branch, so a pre-collegiate withdrawal while the cohort was *already* `FORMING` never promoted. PRD §3.5 states the sweep "triggers on any event that raises `seats_remaining` while the cohort is `FORMING`: ... an offer revocation, or a lock revert." Hoisted `run_promotion_sweep(cohort)` out of the LOCKED guard (the sweep self-guards on `FORMING`, preserving the MATRICULATED/COMPLETED suppression). This fixed `test_waitlist_promotion_rank_and_created_at_tiebreak`, where the first withdrawal reverted+promoted W1 but the second withdrawal (cohort already FORMING) left W2 unpromoted.

  2. `workspace/implementation/ledger.py` — `seat_counts`: derived `seats_committed` as count of `ACCEPTED` offers only, so matriculation (2 trained → `FULFILLED`, 1 shortfall → `REVOKED`) zeroed the ledger. PRD §3.6 Step 3 pins that only the shortfall scholar's revocation makes "`seats_committed` fall by one" (the `FULFILLED` transition carries no ledger delta), so 3 → 2, not 0. Now counts `ACCEPTED` + `FULFILLED` as committed; `FULFILLED` offers exist only post-matriculation, so pre-matriculation behavior (and every other test's ledger expectation) is unchanged. This fixed `test_training_gate_withdraws_untrained_scholar`.

- **Unasserted sibling paths:** not applicable — the iteration was purely implementation fixes, no test-side edits, so no coverage was traded away.

Orchestrator verification: all 8 `results.${i}.json` files show passed=85/85, failed=0, errors=0; both fixes confirmed present in services.py (sweep hoisted out of LOCKED guard) and ledger.py (seats_committed counts ACCEPTED+FULFILLED with explanatory comment citing PRD 3.6).

## Step 8: Finalize PRD — 2026-10-01T17:58:00.000Z

Done. PRD_FINALIZED.md is written and verified against the implementation.

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_3389_cohort_scholar_selection_partner_placement_campus_support/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 341 lines / 53621 bytes; PRD_FINALIZED.md = 341 lines / 53925 bytes. Line-count delta 0.0%; byte delta +0.57%. Exactly one line changed (line 190).

**`diff -q PRD.md PRD_FINALIZED.md`:** `Files PRD.md and PRD_FINALIZED.md differ` — the copy is not byte-identical; the edit pass landed.

### Changes (one bullet per Step 7 item)

- **§3.5 (promotion sweep on pre-collegiate withdrawal while FORMING)** — **no change** — PRD already pins the rule verbatim: §3.5 states the sweep "triggers on any event that raises `seats_remaining` while the cohort is `FORMING`: an offer decline, an offer expiry, an offer revocation, or a lock revert." A pre-collegiate withdrawal is an `ACCEPTED → REVOKED` offer revocation raising `seats_remaining`; the universal trigger sentence uniquely requires the sweep when the cohort is already FORMING. Step 7's fix (hoisting `run_promotion_sweep` out of the LOCKED guard in `implementation/services.py:112`) moved the impl toward this text; verified the impl now calls the sweep unconditionally with the FORMING self-guard (`services.py:37`), and that all sibling sweep call sites match the PRD trigger list: decline (`routes_offers.py:149`), clock expiry (`services.py:74`), nominee-drop revocation (`services.py:87`), matriculation suppression (`routes_cohorts.py:110-152`, no sweep — cohort already MATRICULATED per §3.6 Step 1).
- **§3.4 (seat-ledger definition)** — **revise** — `seats_committed` redefined from "offers in `ACCEPTED` status" to "offers in `ACCEPTED` or `FULFILLED` status", with a clause noting FULFILLED offers exist only post-matriculation so the pre-matriculation count is exactly the ACCEPTED count; the invariant sentence updated to "count of `ACCEPTED` plus `FULFILLED` offers at all times" with an added no-delta clause for the `ACCEPTED → FULFILLED` transition — `implementation/ledger.py:36` (`seat_counts` counts statuses in `("ACCEPTED", "FULFILLED")`). Justification: PRD §3.4's invariant ("equals the count of `ACCEPTED` offers **at all times**") contradicted §3.6 Step 3's pinned arithmetic (only a shortfall revocation drops `seats_committed`; FULFILLED carries no delta), so the PRD did not uniquely determine the post-matriculation ledger; the impl resolved it per §3.6 and the finalized text now matches both.

### Pre-edit search log (NO-NEW-MISMATCH rule)

- **Edit: §3.4 `seats_committed` definition + invariant**
  - (a) Subject: derivation of the cohort seat ledger's `seats_committed` field.
  - (b) Impl paths enumerated and read/grepped (via `grep -rn "seat_counts|seats_committed|seats_remaining|projected_fill"` over `implementation/*.py`, then reading each site): `ledger.py:22-40` (derivation — ACCEPTED+FULFILLED); `routes_offers.py:65` (creation capacity gate, FORMING-only, pre-matric so no FULFILLED offers exist); `routes_offers.py:128-132` (acceptance lock check, pre-matric); `services.py:40` (promotion sweep loop, self-guarded to FORMING, pre-matric); `services.py:103-107` (withdrawal LOCKED→FORMING revert check, pre-matric); `routes_cohorts.py:126-152` (matriculation Step 3: FULFILLED flip touches only the offer — no delta; REVOKED flip drops committed by one); `serialize.py:36-47` (cohort read surface: `seats_committed`, `seats_remaining`, `projected_fill_provisional/final` — the only post-matriculation-observable path). Also grepped the full PRD for every `seats_committed`/`FULFILLED` passage (lines 188, 190, 192, 200, 204, 216, 229) to confirm no other section restates the ACCEPTED-only rule.
  - (c) Wording adjustment: added the clause "such offers exist only after matriculation (Section 3.6), so before matriculation the committed count is exactly the `ACCEPTED` count" because paths 2-5 are all pre-matriculation and were correctly described by the original ACCEPTED-only wording — the clause preserves that meaning while extending coverage to the post-matriculation paths (1, 6, 7). §3.4's projection formulas (line 192) are defined in terms of `seats_committed` and inherit the revised derivation without needing edits; left verbatim.

Orchestrator verification: `diff` shows exactly one changed line (line 190, §3.4 seat-ledger invariant) matching the reported revision; `diff -q` confirms the files differ (not a silent no-op); newest implementation source mtime (ledger.py 17:48:12) predates the sweep results (results.1.json 17:51:16) — the clean sweep remains valid; Step 8 wrote only PRD_FINALIZED.md.

## Step 9: Complete PRD — 2026-10-01T18:15:00.000Z

All 17 edits landed as intended. Final verification is complete — implementation/ untouched, PRD_COMPLETED.md differs from source exactly at the planned sites.

## Summary

**Source vs output:** `workspace/PRD_FINALIZED.md` (341 lines, 53925 chars) → `PRD_COMPLETED.md` (344 lines, 58441 chars; +3 lines, +4516 chars). `diff -q` result: **files differ** (edits confirmed landed). Nothing under `implementation/` was modified (all source mtimes predate this session).

**Counts:** 12 ambiguity-pins, 5 mismatch-revisions (17 total changes).

**Changes (section — kind — class — what — impl evidence):**
1. §2.2 — insert — ambiguity — pin `ERR_NOT_FOUND` (404) for undefined paths/unsupported methods and `ERR_INTERNAL` (500) for unexpected failures — app.py:36-49
2. §2.3 — insert — ambiguity — invalid `limit`/`offset` (non-integer, out of 1..100, negative) → `ERR_INVALID_REQUEST` 400 — validate.py:108-128
3. §2.3 — insert — ambiguity — `has_more` true exactly when `offset` + page size < `total_count` — validate.py:131-140
4. §2.3 — insert — ambiguity — `created_at` ties break by creation (insertion) order everywhere; `id` never an ordering key — core.py:49,84 (`_seq`); all list routes sort by `_seq`
5. §2.4 — insert — ambiguity — clock-set accepts any target ≥ boot instant, non-monotonic, backward set expires nothing retroactively — routes_clock.py:25-32
6. §2.4 — revise — ambiguity — logical clock stamps every persisted timestamp (`created_at`, `updated_at`, `expires_at`, `completed_at`); `meta.api_request_timestamp` is the sole wall-clock stamp — core.py:85-87,94-95; response.py:27-29
7. §2.5 — revise — ambiguity — `version` starts at 1; computed-counter changes (nominations_used, seat ledger, meetings_held_count, training_completed_count) count as mutations; multi-step calls may bump `version` more than once — core.py:87,93-96; routes_offers.py:128-132; routes_cohorts.py:113-162
8. §2.7 tier 4 — insert — ambiguity — target-dependent ownership checks run after path resolution, so a nonexistent target yields 404, not 403 — routes_recruitment.py:222-224; routes_offers.py:96-98; routes_scholars.py:100-104
9. §2.7 tier 8 — revise — mismatch — internship confirmation re-checks only `GOOD_STANDING` (was: "creation or confirmation requiring … MATRICULATED or RETAINED with GOOD_STANDING") — routes_campus.py:184-192
10. §3.1 — revise — mismatch — city-program `code` uniqueness is a convention, not server-enforced (PRD said "unique") — routes_recruitment.py:55-75 (no uniqueness check)
11. §3.1 — insert — ambiguity — ProgramAdmin missing `nominator_id` → `ERR_INVALID_REQUEST`, evaluated once role is established — routes_recruitment.py:150-157
12. §3.2 — revise — mismatch — round check is nominee-status-based, not `current_round`-equality (the two diverge for SELECTED/WAITLISTED, which keep `current_round` 3) — routes_recruitment.py:343-349
13. §3.2 — insert — ambiguity — round-score write-back mutates the nominee (updated_at/version) only when the value actually changes — routes_recruitment.py:390-392
14. §3.3 — insert — ambiguity — activation checks the agreement's own state first: non-`DRAFT` → `ERR_INVALID_STATE` before the college-status gate — routes_partnership.py:223-226
15. §3.5 — insert — ambiguity — waitlist ranking same-instant `created_at` ties break by creation order — services.py:52
16. §3.7 — revise — ambiguity — lifecycle `to_enrollment_status` accepts any declared enum at shape tier; undeclared transitions (incl. `MATRICULATED`, `PRE_COLLEGIATE`) state-reject with `ERR_INVALID_STATE`; combined two-axis calls validate atomically (enrollment vs current, standing vs post-enrollment), apply enrollment first — routes_scholars.py:93-150
17. §3.7 — revise — mismatch — completion check runs only on post-matriculation terminal lifecycle transitions; Section 3.6 training-gate withdrawals do not trigger it (was: "runs whenever a scholar leaves a non-terminal enrollment state") — routes_scholars.py:143-147 vs routes_cohorts.py:146-152 (no completion call); services.py:163-167
18. §3.7 — insert — ambiguity — training completion has no scholar/cohort-state gate; double-complete → `ERR_INVALID_STATE` — routes_scholars.py:154-163
19. §3.9 — insert — ambiguity — renewal review against a `LAPSED` college → `ERR_INVALID_STATE` — routes_partnership.py:114-115
20. §5 — insert — mismatch — add `ERR_INTERNAL | 500` row (catalogue claimed completeness; impl emits it) — app.py:49; errors.py has no such constant (string literal in app.py)

(Items 1/20 are one logical change across two locations; totals: 12 pins + 5 revisions.)

**Nine known interpretation sites:**
1. **Logical vs wall clock** — pinned-now (§2.4 edit, change 6).
2. **Lifecycle any-enum at shape, state-reject (MATRICULATED → ERR_INVALID_STATE)** — pinned-now (§3.7 edit, change 16).
3. **Evaluation round check status-based** — pinned-now (§3.2 edit, change 12); the prior "must equal `current_round`" clause contradicted impl for SELECTED/WAITLISTED.
4. **Completion check only post-matriculation terminal transitions** — pinned-now (§3.7 edit, change 17).
5. **Combined lifecycle call atomic, enrollment first, standing vs post-enrollment state** — pinned-now (§3.7 edit, change 16).
6. **Internship CONFIRMED re-checks standing only** — pinned-already in §3.8 ("re-checks the scholar's standing at confirm time: if the scholar is no longer in `GOOD_STANDING`…"); §2.7 tier 8 contradictorily bundled confirmation into the enrollment+standing gate — fixed by change 9.
7. **Clock-set ≥ boot, non-monotonic** — pinned-now (§2.4 edit, change 5).
8. **`version` = 1 initially, per-mutation increment** — pinned-now (§2.5 edit, change 7).
9. **`created_at` ties by insertion order; `id` never a tie-break** — pinned-now (§2.3 global rule, change 4; §3.5 waitlist parenthetical, change 15).

Orchestrator verification: PRD_COMPLETED.md = 344 lines and differs from PRD_FINALIZED.md (not a silent no-op); `find` shows 0 implementation .py files newer than results.8.json — the clean 8-round sweep evidence remains valid; all 8 results.*.json files present.

## Pipeline Complete — 2026-10-01T18:16:00.000Z

All 9 steps done. Final state: SCAFFOLD.yaml + both design indices; PRD.md → PRD_FINALIZED.md (1-line §3.4 revision) → PRD_COMPLETED.md (17 pins/revisions); 85 tests (67 unique Design tags) passing 8/8 parallel rounds under per-test-server isolation; 40-endpoint Flask implementation, in-memory storage, no seeding.
