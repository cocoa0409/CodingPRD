# Worklog — task_3394_veteran_program_enrollment_benefits_navigation_outcome_measurement

## Step 1: Create Task Directory — 2026-10-01T15:21:01.612Z

Task directory pre-allocated by the entrance invocation (index not recomputed). Verified `./tasks/task_3394_veteran_program_enrollment_benefits_navigation_outcome_measurement/workspace/` exists and is empty. No new directory created.

Note: the "Generate task much harder than expert level!" instruction is forwarded to prd-bench-scaffold-generator only (Step 2).

## Step 2: Generate Scaffold — 2026-10-01T16:51:06.62334344Z

All three artifacts are complete and verified. Final state of the task:

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3394_veteran_program_enrollment_benefits_navigation_outcome_measurement/`):
- `SCAFFOLD.yaml` — 1657 lines; 16 entities, 45 endpoints, 36 error codes, 9 roles, 15 calculations, 11 state machines, 14 ordered validation priorities, 2 OCC concurrency rules
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1138 lines; all 9 §0.5 rules × exactly 2 instances = 18 instances (each with full structured `setup_api_calls`/`trigger`/`assert` and precomputed literals)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2509 lines; 61 active instances + 5 `excluded_because` stubs across all 9 guide sections

**Verification**: `scaffold_lint.py` → `VERDICT: clean lint` (596 recipe calls scanned, zero violations across checks a–f). A separate self-audit confirmed: instance-name uniqueness across both design files, every `grounds:` reference resolves to a declared §1.1–§1.7 element, zero unbound `${var}` placeholders, no forbidden concurrency vocabulary, every catalog error exercised by at least one recipe, no duplicate YAML keys, and the file-split rule honored (neither design key appears in SCAFFOLD.yaml).

**Key design adjudications**:
1. *Endpoint count*: landed at 45 vs the ~40 soft cap — I consolidated action verbs into `/transition` endpoints (eligibility, enrollment, referral, placement, registration) and dropped redundant single-GETs, but FK reverse-reachability for 11 FK relations plus the scenario's 8 mandated facets set a hard floor; §1.5's testability-completeness principle takes precedence.
2. *Deterministic ordering*: the set-only logical clock would tie `created_at` on same-tick rows, so EventRegistration carries `queue_position` (per-event) and Referral carries `request_seq` (global) as system sequence fields; selector tie-breaks end at `name ASC` — ids never decide outcomes.
3. *Dead-code avoidance*: claim auto-close fires at `decided_at + APPEAL_WINDOW_DAYS + CLAIM_CLOSE_GRACE_DAYS` (90+7d) so the temporal error `ERR_APPEAL_WINDOW_CLOSED` stays reachable on a still-DECIDED claim — without the grace week the sweep would close the claim first and the 422 would be unreachable. Removed two unreachable 404 errors (`ERR_PARTNER_SITE_NOT_FOUND`, `ERR_EXTERNAL_RECORD_NOT_FOUND`) whose ids no endpoint dereferences.
4. *Rounding pinned*: claim COLA rounds per-claim before the member-level sum (35876 vs 35875 divergence computed and pinned); donor reports round per-track before weighting.
5. *Priority split*: eligibility-policy rejection (`ERR_ELIGIBILITY_CRITERIA_NOT_MET`, 409) got its own validation row separate from segregation-of-duties (403), and priorities renumbered 1–14.
6. *Ownership refinement*: the ClinicalPartner ownership check applies only once `partner_site_id` is set, so a never-matched EXPIRED referral correctly fails with the state error rather than a misleading 403.

Orchestrator verification after subagent exit: all three files exist on disk and parse with `yaml.safe_load`; top-level keys correct (SCAFFOLD.yaml has neither design key; design files have exactly their single top-level key); `api_prefix: /veteran-services`, domain_name `veteran-program-outcomes`, 16 veteran-domain entities (Member, EligibilityCase, ExternalServiceRecord, ProgramTrack, Enrollment, Assessment, BenefitsClaim, Appeal, Referral, PartnerSite, EmployerPartner, Placement, CommunityEvent, EventRegistration, OutcomeSurvey, DonorReport), 45 endpoints, 9 roles — all consistent with the scenario; no foreign-domain contamination.

## Step 3: Copy Shared Files — 2026-10-01T16:51:26.200Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (build contract for the implementer).

## Step 4: Generate PRD — 2026-10-01T17:12:28.950Z

All contracts pass. The PRD is complete and verified.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3394_veteran_program_enrollment_benefits_navigation_outcome_measurement/workspace/PRD.md` — 338 lines, ending at §5 Error Code Catalogue with no audit footer.

**Document skeleton** (domain-derived, not templated): §1 Introduction (2 paragraphs); §2 with nine subsections (2.1 RBAC+identity, 2.2 verbatim response structure, 2.3 pagination, 2.4 resource identity/common fields incl. the leaner Assessment/DonorReport shape, 2.5 logical clock + 7-step sweep, 2.6 OCC, 2.7 the 14-priority validation order, 2.8 money/scores/rounding, 2.9 nested reads); §3 with eight subsections (registration/eligibility, tracks/enrollment, assessments/acuity, claims/appeals, referrals/site matching, placements/milestones, events/seating/travel, surveys/donor reporting); §4 endpoint table (4 columns); §5 error catalogue (2 columns).

**Coverage counts (scaffold → PRD, all verified mechanically):**
- Entities: 16, field entries 123 (95 unique names) — all 95 unique field names backticked in prose: **0 missing**
- State machines: 11, transitions 46 — all walked; all 36 distinct state strings appear as exact backticked UPPERCASE tokens: **0 missing**
- Calculations: 15 — all expressed in precise prose (acuity weights 0.4/0.3/0.2/0.1 vs 0.5/0.1/0.2/0.2 with 70/40 tiers; full 11-row rating base table in cents; dependent allowance floor 30 / 16000 / 31000+9000; COLA 1.025; travel cap 50000; survey windows 14/30/90±7; baseline impute 50; appeal window 90; close grace 7; recovery buffer 7; per-track-round-before-weighting; rational occupancy ranking; closed vs half-open interval semantics): **0 missing**
- Validations: 14 priorities — all rendered as an explicit ordered list in §2.7 with masking order stated: **0 missing**
- Endpoints: 45 — all present in §4 with method, path, and role list matching the scaffold exactly (script-verified): **0 mismatches**
- Errors: 36 — all in §5 table and each mentioned in §2/§3 prose near its trigger: **0 missing**
- Roles: 9 — all named with identity prose (ProgramMember entity-backed to Member, ClinicalPartner entity-backed to PartnerSite, seven opaque): **0 missing**
- OCC rules: 2 — both expressed with `expected_member_version`, endpoint framing, `ERR_STALE_VERSION` (412), no race framing
- Endpoint inputs 39, query params 31, path params 11 — all backticked: **0 missing**

**Contract reports**: Contract 1 PASS (0 missing after one repair pass adding `q2`/`q3`/`q4`, `action`, `target_status`, `milestone`); Contract 2 PASS (walked all six high-risk categories plus tail); Contract 3 PASS (550 backticked tokens in §3, zero paths/methods/method+path combos).

**Wording decisions for ambiguous points**: (1) claim close stated as "more than 97 days" while naming both components (90-day appeal window + 7-day grace); (2) FOLLOWUP_90 window rendered as exit+83 through exit+97 days; (3) monetary constants given in integer cents with parenthetical dollar equivalents; (4) §4 Path column backticked to match the example PRD; (5) endpoint action enums (ADMIT/DISCHARGE, CONFIRM_MILESTONE/SEPARATE, CANCEL/ATTEND, DAY_30/90/180) named as values of the `action`/`milestone` payload fields rather than as HTTP framing, preserving §3 path purity; (6) coverage scripts strip the §2.2 fenced JSON before extracting backtick spans — naive pairing otherwise shifts and false-reports everything after §2.2 as missing.

Orchestrator verification after subagent exit: workspace/PRD.md exists (338 lines); spot-checked tokens ERR_STALE_VERSION ×6, COLA `1.025` ×1, ERR_APPEAL_WINDOW_CLOSED ×3, `/veteran-services` ×48, expected_member_version ×5, ProgramMember ×8; endpoint table (header at line 249) + error catalogue = 85 table rows total, consistent with 45 endpoints + 36 errors + 4 header/separator rows; 36 unique ERR_ ids in doc matching scaffold's 36-error catalogue.

## Step 5: Generate Unit Tests — 2026-10-01T17:56:16.688Z

All checks pass. Generation is complete and verified.

## Summary

**Task**: task_3394_veteran_program_enrollment_benefits_navigation_outcome_measurement — 79 non-stub design instances (18 difficulty + 61 corner) against a 16-entity / 45-endpoint / 36-error PRD.

### Files generated (3,735 lines total)

`test_helpers/` — `__init__.py` (26), `types.py` (437: 16 TypedDicts incl. lean Assessment/DonorReport without `updated_at`/`version`, 25 enums), `api_errors.py` (85: all 36 error IDs + HTTP map registered with the framework), `constants.py` (68: 25 constants, all traced to PRD prose), `api_client.py` (160: all 45 endpoints under `/veteran-services`), `assertions.py` (128), `factories.py` (225), `test_users.py` (66: shared constants + per-instance builders for all 9 roles, entity-backed `make_program_member_headers`/`make_clinical_partner_headers`), `fixtures.py` (468: clock control, verified-member flow with OCC version threading, active/INTENSIVE enrollment setups, claim/appeal/referral/placement/event/survey/report composites — all state built via declared API endpoints).

`test_suite/` — `conftest.py` (44), `test_01_member_registration_eligibility.py` (13), `test_02_enrollment_acuity.py` (13), `test_03_claims_appeals.py` (16), `test_04_referrals_sites.py` (10), `test_05_placements.py` (6), `test_06_events.py` (9), `test_07_surveys_reports.py` (10).

### Verification results
- `pytest --collect-only`: **77 tests collected, 0 errors**.
- Tag audit (AST-parsed docstrings): **77 emitted** (18/18 Difficulty, 59/61 Corner), **2 skipped**, **5 stubs** (all `difficulty_instance` cross-refs resolve; none emitted). No untagged, dual-tagged, or dangling tags; every Design line is the docstring's last line and matches the yaml `name:` verbatim.
- Citation sweep: **120/120** quoted spans grep verbatim in PRD.md.
- Constants diff: **30/30** values (rate table, weights, thresholds, windows, caps) match PRD literals exactly.
- Zero `skip`/`skipif`/`xfail` markers. All creates assert 201 via `validate_success(resp, 201)`.

### Skipped instances (PRD-silence gaps, left as gaps)
1. `Corner/entities/member_create_ignores_system_field_input_ignored` — PRD never states how undeclared payload fields (smuggled `verification_status=VERIFIED`, `version=99`) are handled; a faithful reader could ignore them (201) or reject the body (400). Not uniquely derivable.
2. `Corner/entities/survey_submit_ignores_client_wellbeing_score_input_ignored` — same silence: the submit payload declares only `q1..q5`; ignoring vs rejecting an extra `wellbeing_score` is an open design space.

### Literal re-derivations
None needed — every design-index literal was re-checked against PRD formulas and matched (e.g. provisional 166100 vs final 140118, per-claim rounding 17938+17938=35876, allowance floor 35465, overturn cascade 202028, acuity 61/ENHANCED vs 70/INTENSIVE on identical scores, tier boundary 40/39, ITT 12.00 vs COMPLETER 24.00, imputed-baseline 30.00, EXIT window [2026-10-01, 2026-10-31] and FOLLOWUP_90 [2026-12-23, 2027-01-06], claim close at decided_at+97d strictly-after, appeal window day-90 inclusive, milestone day-30 inclusive).

### PRD-silence adjudication (emitted, flagged)
Absolute `version` values (1 at creation, 6/3/3 in later states): PRD §2.4 says version "starts at its initial value and increments by 1 on every mutation" without naming the initial value. I emitted the pre-audited absolute assertions (start-at-1), since the OCC capture flows and the design index's literals uniformly assume it; a 0-starting implementation would fail those assertions.

Timestamp comparisons in the survey-window test parse ISO strings to datetimes before comparing, so the assertion is on the instant, not the serialization format (PRD allows three-fractional-digit form).

Orchestrator verification after subagent exit: all 9 test_helpers/ files and 8 test_suite/ files exist on disk; independent `pytest --collect-only -q` run reports **77 tests collected, 0 errors** — matches hand-back.

## Step 6: Generate Implementation — 2026-10-01T18:38:14.053Z

The implementation is complete, compiles, imports cleanly, and passes the smoke test. Final report:

## Implementation delivered

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_3394_veteran_program_enrollment_benefits_navigation_outcome_measurement/workspace/implementation/`

**Files (17 total, 2150 lines):**
| file | lines | role |
|---|---|---|
| start.sh | 10 | exec foreground launcher, guarded `pip install`, `$PORT` (default 10000), `0.0.0.0` |
| requirements.txt | 1 | `flask==3.0.3` |
| app.py | 53 | Flask wiring, blueprint registration, envelope-shaped error handlers |
| constants.py | 72 | all PRD literals (weights 0.4/0.3/0.2/0.1 + 0.5/0.1/0.2/0.2, tiers 70/40, COLA 0.025, rate table, allowances 16000/31000/9000, travel cap 50000, impute 50, windows 14/30/90±7, appeal 90, grace 7, buffer 7, clock start) |
| errors.py / middleware.py / response.py / validation.py / db.py | 9+26+44+136+85 | ApiError, auth+role checks, `meta`/`response_type`/`data` envelope with pagination fields, body/pagination validators, in-memory store + logical clock |
| services.py | 367 | acuity, compensation (provisional/final), site selection (exact-Fraction occupancy ranking), travel award, seating/promotion, engagement derivation, 7-step clock sweep, donor-report aggregation |
| routes_core.py | 269 | clock, program-tracks, members, eligibility-cases, external-service-records |
| routes_enrollments.py | 199 | enrollments, assessments, transitions, enrollment surveys |
| routes_claims.py | 218 | claims + appeals (incl. SoD, appeal window, re-anchor) |
| routes_referrals.py | 204 | referrals + partner-sites (OCC, supersede, selector, discharge re-match) |
| routes_placements.py | 165 | employer-partners + placements (milestone ladder, requisition restore) |
| routes_events.py | 193 | community-events + registrations (seating, travel award, waitlist promotion) |
| routes_surveys.py | 99 | survey submit + donor reports |

**Verification:**
- `py_compile` passed on every .py file; `import app` succeeds with all **45 endpoints** registered.
- **ALL_CAPS audit:** all 31 named constants defined exactly once in `constants.py`, all referenced; no undefined constants.
- **Store empty at boot**, clock at `2026-09-01T00:00:00.000Z`; no seeding anywhere.
- **Smoke test** (dynamic port 37161, server killed by exact PID afterward, port confirmed free): clock set → 200 `{"current_utc": "2026-09-01T00:00:00.000Z"}`; track create → 201; member create → 201 (UNVERIFIED/INACTIVE, v1); case create `expected_member_version:1` → 201; replay with stale version → **412 ERR_STALE_VERSION**; case VERIFIED → 200 with `decided_at`; GET member → VERIFIED, era copied, **v3**; enrollment → 201 INTAKE + BASELINE survey SCHEDULED with window `[09-01, 09-15]`; assessment {8,7,6,5} → 201 acuity **70** INTENSIVE, enrollment flipped ACTIVE; negative checks → 401 ERR_UNAUTHENTICATED, 403 ERR_FORBIDDEN_ROLE, 400 ERR_INVALID_REQUEST, all in the PRD error envelope.

**Interpretation decisions (PRD admitted >1 reading):**
1. `version` starts at **1**; each mutation bumps version+updated_at, at most once per entity per request (sweep transitions also bump).
2. Claim decide: `decided_rating_pct` required only for GRANTED on DISABILITY_COMPENSATION; DENIED records 0 regardless of payload; HEALTHCARE_ACCESS decisions record `decided_rating_pct=null`, `final_monthly_cents=0`.
3. Appeal OVERTURNED sets `claim.outcome := GRANTED` before recomputing the final award (leaving DENIED would force final=0 and make overturning vacuous).
4. VERIFIED case transition requires both `verified_service_era` and `verified_injury_connection` in the payload (missing → 400); `pend_reason`/`denial_reason` optional.
5. Pagination bounds enforced: `limit` outside 1–100 or `offset`<0 → 400 ERR_INVALID_REQUEST.
6. List sort: `created_at` asc, insertion order as tie-break (clock may be set backwards).
7. Unknown filter values yield empty lists (no 400); unknown routes return envelope-shaped 404/405.
8. Datetimes floored to second precision at ingestion (PRD: comparisons at second precision), emitted as `...T...SS.000Z`; naive inputs treated as UTC.
9. `track_weights` naming empty-cohort tracks are dropped and the remainder renormalized; weights must sum to exactly 1.0 (Decimal comparison).
10. `target_status=SUPERSEDED` via the case-transition API → 400 (system-only transition).
11. Enrollment exit bumps member version only when engagement actually flips (PRD §3.2 "flips" sentence); enrollment creation bumps unconditionally (explicit endpoint side effect).

One process note: my first smoke boot lost the `PORT` export through a backgrounded `&&` chain and bound the default 10000; I identified that exact `python3 app.py` PID via its port, killed it, and re-ran correctly — no broad kill patterns used at any point.

Orchestrator hand-off verification: all 17 files on disk; independent `import app` OK (46 url rules = 45 endpoints + static); start.sh execs foreground with `$PORT` (default 10000) read in app.py; **Step 6→7 constant drift audit**: impl `COLA_RATE=0.025` used as `*(1+COLA_RATE)` ≡ helpers' `COLA_MULTIPLIER=1.025` (behaviorally identical); RATING_BASE_CENTS 11-row tables byte-identical between impl constants.py and test_helpers/constants.py; milestone days {30,90,180} defined in impl routes_placements.py matching helpers' MILESTONE_DAY_*; clock start 2026-09-01 on both sides; windows 14/30/90±7, appeal 90, grace 7, buffer 7, travel cap 50000, impute 50, allowances 16000/31000/9000 all match.

## Step 7: Run Tests and Iterate — 2026-10-01T18:50:58.411Z

**Summary**

- **Iterations run**: 2 (first sweep: 76/77 × 8 rounds, one consistent failure; second sweep after fix: 77/77 × 8 rounds, clean).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**: none.

- **Fixes applied to `implementation/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_3394_veteran_program_enrollment_benefits_navigation_outcome_measurement/workspace/implementation/routes_claims.py` — `decide_claim()`: removed an invented guard (`decided_rating_pct must be null for HEALTHCARE_ACCESS` → 400) that has no PRD basis. PRD §3.4 scopes the null-rule to `claimed_rating_pct` only ("The field is required exactly when the `claim_type` is `DISABILITY_COMPENSATION` and must be null for `HEALTHCARE_ACCESS`"), while the decide paragraph is claim-type-uniform ("by supplying the `outcome` ... and the `decided_rating_pct`"; "a denied claim records a `decided_rating_pct` of 0"). The decision handling is now uniform: `GRANTED` requires `decided_rating_pct` and computes `final_monthly_cents` under the final-variant formula; `DENIED` records rating 0 / final 0 — for both claim types. This was the "impl-gen invents guards not in PRD" pattern, and it had been flagged in the Step 6 worklog as interpretation decision #2. The failing test (`test_healthcare_claim_cannot_be_appealed`) was faithful: its setup decide (GRANTED, rating 0) is PRD-legal, and its assertions (provisional null, final 0 via the formula, `ERR_CLAIM_TYPE_NOT_APPEALABLE` on appeal) are all PRD-verbatim.

- **Artifact confirmation**: `workspace/implementation/results.{1..8}.json` from the final green sweep (run after the only implementation edit) remain on disk — 8 files, all `passed == total == 77`.

Orchestrator verification after subagent exit: read all 8 results.{1..8}.json from disk — every round `passed=77 total=77 failed=0` (ALL GREEN, 8 files present); mtime audit shows NO source file in implementation/, test_suite/, or test_helpers/ is newer than the final sweep — the green sweep reflects the final tree state.

## Step 8: Finalize PRD — 2026-10-01T19:01:58.759Z

Done. The patch is a single inline sentence insertion; all other 337 lines are byte-identical.

## Summary

**Line counts / delta**: PRD.md 338 lines, PRD_FINALIZED.md 338 lines (one paragraph extended inline; 1 line modified of 338, ~0.3% of lines; +1 sentence, +39 words).

**Changes (one total)**:
- **§3.4 Benefits Claims, Appeals, and Monthly Compensation** (decide paragraph, line 182) — **insert** — added "The `decided_rating_pct` is required exactly when the outcome is `GRANTED`, identically for both claim types; a rating supplied with a `DENIED` outcome is disregarded." — impl: `/home/ubuntu/github/CodingPRD/tasks/task_3394_veteran_program_enrollment_benefits_navigation_outcome_measurement/workspace/implementation/routes_claims.py:93-111` (`decide_claim`); formula consistent with `services.py:81-92`.

**Why not zero-change**: the Step 7 fix itself (removing the invented `HEALTHCARE_ACCESS` null-guard) needed no corrective text — the PRD decide paragraph was already claim-type-uniform and the impl was aligned *to* it. But the fix site carried a live PRD-silence the diff's own post-fix description pins: "supplying the `outcome` ... and the `decided_rating_pct`" did not determine that the rating is required only for `GRANTED`, that a `DENIED`-supplied rating is disregarded (impl returns 200 and records 0, not 400), or that none of this varies by claim type — the exact misreading impl-gen originally shipped by analogy to the claim-type-scoped `claimed_rating_pct` rule one paragraph earlier. The single inserted sentence closes all three without touching anything else.

**Per-edit pre-edit search log** (the only edit):
- (a) Subject: `decided_rating_pct` requirement and claim-type-uniformity on `POST /claims/{claim_id}/decide`.
- (b) Impl paths enumerated and read/grepped: `routes_claims.py:88-118` (`decide_claim`, full function); `routes_claims.py:19-58` (`create_claim` — inits `decided_rating_pct: None`; claim-type rules there govern the distinct `claimed_rating_pct` field); `routes_claims.py:121-151` (`create_appeal` — claim-type appeal gate at :138, never reads `decided_rating_pct`); `routes_claims.py:169-210` (`decide_appeal` — rewrites claim rating from `new_rating_pct` on OVERTURNED, :201; governed by the separate appeal paragraph which already pins its own "required exactly when" rule); `services.py:75-78` (provisional — claim-type-scoped but concerns the filing-time estimate, already pinned); `services.py:81-92` (`final_monthly_cents` — takes no claim_type, DENIED/null → 0); `services.py:95-105` (`recompute_member_compensation` — rating-blind); full `claim_type` grep across impl confirms the decide path is claim-type-free; test-side: `test_03_claims_appeals.py:251-271` (the faithful failing test) and `test_helpers/factories.py:116-117`.
- (c) Wording adjustments from the search: used the PRD's existing idiom "required exactly when" (cf. lines 180, 188); scoped "identically for both claim types" inside the *decide* paragraph only so it cannot be read as overriding the filing-time `claimed_rating_pct` rules or the provisional-null rule; chose "is disregarded" over "is accepted" so §2.7 priority-2 step validation of a supplied value stays in force; named no error code (§2.7 derives `ERR_INVALID_REQUEST`/400, matching impl :100-101); deliberately silent on check ordering (impl runs this check after role/existence, contrary to a strict reading of §2.7's global order — under-determined wording keeps that free, per the prefer-loose rule).

Produced file: `/home/ubuntu/github/CodingPRD/tasks/task_3394_veteran_program_enrollment_benefits_navigation_outcome_measurement/workspace/PRD_FINALIZED.md`

Orchestrator verification after subagent exit: `diff workspace/PRD.md workspace/PRD_FINALIZED.md` confirms exactly one change — the claimed sentence insertion in the §3.4 decide paragraph (line 182); all other 337 lines byte-identical; both files 338 lines.

## Step 9: Complete PRD — 2026-10-01T19:24:59.462Z

Done. `PRD_COMPLETED.md` is produced; `implementation/` (including all `results.*.json` sweep evidence) was never written to — all writes went to `workspace/PRD_COMPLETED.md` only, and no servers or tests were run.

## File stats
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_3394_veteran_program_enrollment_benefits_navigation_outcome_measurement/workspace/PRD_FINALIZED.md` — 338 lines, 57203 chars
- Produced: `/home/ubuntu/github/CodingPRD/tasks/task_3394_veteran_program_enrollment_benefits_navigation_outcome_measurement/workspace/PRD_COMPLETED.md` — 343 lines, 61195 chars (+5 lines, +3992 chars)

## Counts
- Ambiguity-pins: 15
- Mismatch-revisions: 2

## Changes (one per bullet)
- §2.2 — revise — ambiguity — pinned `api_request_timestamp` as wall-clock request metadata, the platform's only wall-clock read, driving no temporal rule — `implementation/response.py:14-20`
- §2.2 — insert — ambiguity — pinned envelope-shaped transport errors `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — `implementation/app.py:37-49`
- §2.3 — revise — ambiguity — non-integer or out-of-range `limit` (1–100) / negative `offset` → `ERR_INVALID_REQUEST` 400; `created_at` ties break by insertion order; `has_more` = `offset + returned < total_count` — `implementation/validation.py:116-136`, `implementation/response.py:33`, e.g. `implementation/routes_core.py:68`
- §2.4 — revise — ambiguity — `version` starts at 1; supplied datetimes floored to second precision, naive read as UTC, resource timestamps always emitted `.000Z` — `implementation/services.py:27-34`, `implementation/db.py:63-85`
- §2.5 — revise — **mismatch** — "never reads wall-clock time" carved out for the §2.2 metadata timestamp (impl reads wall clock there) — `implementation/response.py:15`
- §2.5 — insert — ambiguity — every clock-sweep transition bumps the record's `version` and refreshes `updated_at` — `implementation/services.py:186-229`
- §2.7 — insert — ambiguity — on claim-decide alone, the GRANTED-requires-`decided_rating_pct` presence rule runs after the claim existence check and before the state check (missing claim masks missing rating; missing rating masks wrong state) — `implementation/routes_claims.py:95-103`
- §2.9 — insert — ambiguity — filters are exact-match, never enum-validated; unknown filter values yield empty pages, never 400 — e.g. `implementation/routes_enrollments.py:64-74`
- §3.1 — revise — ambiguity — case `target_status` ∈ {PENDED, UNDER_REVIEW, VERIFIED, DENIED}, `SUPERSEDED` system-only (→ 400); VERIFIED decision requires both `verified_service_era` and `verified_injury_connection` (missing/null → 400); `pend_reason`/`denial_reason` optional (default null); resume keeps the recorded `pend_reason`; inapplicable payload fields are ignored — `implementation/routes_core.py:21,173-221`
- §3.2 — revise — ambiguity — enrollment `target_status` ∈ {SUSPENDED, ACTIVE, COMPLETED, WITHDRAWN} (`INTAKE` never a target); `exit_reason` optional default null, stored only on exits — `implementation/routes_enrollments.py:15,137-182`
- §3.4 — revise — **mismatch** — member `total_monthly_compensation_cents` recompute + member `version` bump fires on *every* appeal decision (upheld or overturned), not only overturning ones — `implementation/routes_claims.py:205-209`
- §3.4 — revise — ambiguity — an OVERTURNED appeal sets the claim's `outcome` to `GRANTED` before recompute — `implementation/routes_claims.py:200`
- §3.5 — revise — ambiguity — referral creation supersedes *all* of the member's `PENDING_MATCH` referrals (plural possible with non-overlapping windows) — `implementation/routes_referrals.py:77-82`
- §3.5 — revise — ambiguity — site-ranking final tie-break by site registration order; a referral matched at creation is returned at `version` 1 (match is part of the creation write) while the matched site's version bumps — `implementation/services.py:248-261`, `implementation/routes_referrals.py:84-88`
- §3.6 — revise — ambiguity — `separation_reason` is accepted but never stored on the placement record; a `milestone` supplied with SEPARATE is ignored — `implementation/routes_placements.py:133`
- §3.8 — revise — ambiguity — `per_track` ordered by `track_code` ascending; `track_weights` 1.0-sum spans all supplied entries (unknown/dropped-track entries count toward the sum but not the weighting); unnamed included tracks weigh 0 pre-renormalization; surviving sum ≤ 0 → equal weights; report echoes `period_start`/`period_end`/`methodology`/`track_weights` (null when omitted) — `implementation/routes_surveys.py:61-86`, `implementation/services.py:320-367`
- §5 — insert — ambiguity — catalogue rows for `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — `implementation/app.py:37-49`

## Known-decision checklist
All 11 hinted decisions verified against code; #2 (DENIED records 0, supplied rating disregarded) and #11 (create bumps member unconditionally, exit bumps only on engagement flip) were already correctly pinned by the base PRD and needed no change; the other 9 are now pinned via the bullets above. Additional finds beyond the hint list: the wall-clock metadata timestamp mismatch, the upheld-appeal member version bump mismatch, the deferred claim-decide rating check, the plural supersede cascade, the selector's final registration-order tie-break plus at-creation version semantics, non-persisted `separation_reason`, `has_more` formula, transport-error catalogue, resume-keeps-`pend_reason`, and the donor-report echo/ordering/weighting edge rules.

Orchestrator verification after subagent exit: PRD_COMPLETED.md exists (343 lines), `diff -q` against PRD_FINALIZED.md confirms real changes (35 diff lines — not a silent no-op); mtime audit confirms NO file in implementation/, test_suite/, or test_helpers/ is newer than the Step 7 green sweep — all 8 results.{1..8}.json remain valid passing evidence (77/77 × 8 rounds).
