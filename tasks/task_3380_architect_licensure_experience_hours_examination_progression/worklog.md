# Worklog — task_3380_architect_licensure_experience_hours_examination_progression

## Step 1: Create task directory — 2026-10-01T11:55:00.000Z

Task directory was pre-allocated by the caller: `./tasks/task_3380_architect_licensure_experience_hours_examination_progression/` with empty `workspace/` inside. Verified it exists; no new index computed and no other task_* directory created. Project-root `INSTRUCTION.md` confirmed present (1424 bytes).

## Step 2: Generate scaffold — 2026-10-01T12:59:00.000Z

All verification passed. The pre-existing `worklog.md`/`workspace/` are the orchestrator's Step 1 directory pre-allocation — untouched by me.

## Report

**Task**: task_3380_architect_licensure_experience_hours_examination_progression (NCARB-style licensure). All three artifacts generated at `/home/ubuntu/github/CodingPRD/tasks/task_3380_architect_licensure_experience_hours_examination_progression/`.

**Final counts**
- Endpoints: **40** (at budget; difficulty spent on rule depth, not route count)
- Entities: **12** (Candidate, Jurisdiction, Supervisor, EducationEvaluation, ExperienceReport, ExamAuthorization, ExamDivisionProgress, SupplementalExam, Certificate, CEEntry, Transmittal, DisciplinaryReport)
- State machines: **8** (four cyclic: education deficiency loop, exam retake/rolling-clock loops, report return-resubmit loop, certificate lapse-reinstate cycle)
- Calculations: **7** — dual-variant in two domains (locked-vs-projected experience credit tiers; strict-vs-carry-over CE compliance), combinatorial in two modes (per-report round-half-up-then-sum; nested min/max rolling-clock window), all constants pinned (8/60-month credit windows, 60-month rolling clock, 60-day retake, 3-per-365-day attempt cap, 45-day reassign window, 24-month CE periods, 60-day renewal window, 12-month reinstatement window, +4 HSW penalty, 3740 hours with per-area minima)
- Validations: **36** ordered rows (auth → ownership → existence → state/OCC → safety → referential → temporal → constraint)
- Errors: **35**; Roles: **5** (segregation-of-duties: disciplinary resolver ≠ filer; supervisor ownership on verify)
- Concurrency: 2 true-race OCC rules (jurisdiction/supervisor PATCH, 412 ERR_STALE_VERSION)
- §1.8 difficulty design: **9 rules × 2 = 18 instances** (depth-3 disciplinary sanction cascade: FLAGGED → REVOKED → CANCELLED; depth-2 verify→COMPLETE→eligible cascade; state-vs-temporal and referential-vs-constraint priority conflicts; inclusive/exclusive boundary pairs on hours vs days)
- §1.9 corner design: **50 instances** (44 active + 6 excluded_because stubs, all resolving to §1.8 names) across all nine guide sections

**Verification**: all three files parse as valid YAML; `scaffold_lint.py` verdict — **clean lint** (823 recipe calls scanned, zero violations; every FK reverse-reachable). File split honored (no design keys in SCAFFOLD.yaml). Forbidden concurrency vocabulary absent. Logical clock default 2026-09-01T00:00:00Z declared; fixture dates all explicit and clock-reachable. Object graph is acyclic (jurisdiction → candidate/supervisor → reports/evaluations → authorization → divisions → certificate → CE/transmittals; disciplinary hangs off candidate only). No sibling task was read at any point.

Orchestrator spot-check: all three YAMLs exist and parse (SCAFFOLD.yaml 73,372 B; DIFFICULTY 86,787 B; CORNER 118,447 B); `endpoints` key length = 40; no `scaffold_difficulty_design`/`scaffold_corner_design` keys in SCAFFOLD.yaml; domain vocabulary (architect/licensure/candidate/jurisdiction) grep = 282 matches — artifact describes this scenario, not a foreign domain.

## Step 3: Copy shared files — 2026-10-01T13:00:00.000Z

Copied `./INSTRUCTION.md` (1424 bytes) to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-01T13:07:00.000Z

PRD generation complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3380_architect_licensure_experience_hours_examination_progression/workspace/PRD.md` — 274 lines, 6,227 words, ending at §5 Error Code Catalogue (no audit footer).

**Structure:** §1 introduction (2 paragraphs, domain-context angle); §2 with 8 subsections (RBAC with per-role identity prose, byte-identical §2.2 envelope block, pagination, logical clock, resource identity/OCC, validation ordering, precision/half-open periods, exam confidentiality); §3 with 8 lifecycle-grouped subsections (registries, education loop, experience reporting, examination, supplemental exams, eligibility/issuance, CE/renewal/reinstatement, transmittal/disciplinary); §4 table with 40 endpoints × 4 columns; §5 table with 35 errors × 2 columns.

**Self-verification results (all programmatic checks against the file on disk):**
- **Numeric constants in prose: 36/36 placed** — logical-clock default 2026-09-01T00:00:00Z, 8-month/100% and 60-month/50% credit tiers with inclusive boundaries, 1–2000 report hours, all six area minima (160/360/260/1360/1520/80), national floor 3740, 60-month rolling clock with inclusive expiry day, 60-day retake (inclusive), 3-per-365-day attempt window (strict cutoff), 45-day reassignment window, 90-day supplemental retake, 64 alternative-path credits, 24-month CE periods, 12-hour carry cap, 60-day renewal window (half-open), 12-month reinstatement window (inclusive), +4 HSW reinstatement penalty, 1–24 CE entry hours, jurisdiction defaults (3740/24/12/false/false), scaled score 0–100, pagination 10/1/100/0, six divisions, and the minima-sum-equals-3740 cross-check.
- **Error IDs: 35/35 present verbatim** in §2/§3 prose (checked outside the §5 table) and in the §5 table with correct HTTP statuses.
- **Contract 1 (field coverage): 87/87** entity fields, request-body keys, query params, and header names appear in backticks (0 missing). Note: a first-pass checker false-alarms here because §2.2's fenced JSON desynchronizes naive backtick pairing — fences must be stripped before token extraction.
- **Contract 2 (rule coverage):** all 28 state transitions with preconditions/side-effects, all 7 calculations (credit tiering locked vs projected variants, area aggregation, completion gate, rolling clock, retake eligibility, CE compliance strict vs carry-over variants, eligibility conjunction), both OCC rules (`expected_jurisdiction_version`/`expected_supervisor_version` → `ERR_STALE_VERSION` 412), the 8-tier validation precedence, all multi-endpoint `applies_to` scopes, and both 3-link cascades (verify, expiry, sanction) expressed in prose.
- **Contract 3 (§3 path purity):** 402 backtick tokens scanned, 0 path/method violations.
- All 54 state/enum values verbatim; all 5 role names exact; §2.2 confirmed byte-identical to the canonical source file.

**Nothing unplaceable.** The forbidden SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were never opened.

Orchestrator spot-check: `workspace/PRD.md` is 274 lines and ends with the §5 error table (last line `| ERR_STALE_VERSION | 412 |`, i.e. complete tail, not truncated); 35 unique `ERR_*` tokens present; constants verified in prose with explicit inclusivity language (six area minima 160/360/260/1360/1520/80 + national floor 3740 with minima-sum cross-check at line 143; logical clock 2026-09-01T00:00:00Z at line 80; calendar-month arithmetic + day granularity at line 82).

## Step 5: Generate unit tests — 2026-10-01T13:58:00.000Z

All audits pass. The suite is complete and verified.

## Summary

**Task**: test infrastructure + claim-driven test suite for `task_3380_architect_licensure_experience_hours_examination_progression` (NCARB licensure).

### Generated artifacts (absolute paths)

`test_helpers/` under `/home/ubuntu/github/CodingPRD/tasks/task_3380_architect_licensure_experience_hours_examination_progression/test_helpers/` (9 files, 1341 lines): `types.py` (308; 21 enums, 12 TypedDicts), `api_client.py` (234; 40 endpoint methods), `api_errors.py` (84; 35 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (165), `factories.py` (107; uuid-unique emails/license numbers), `constants.py` (55; 15 PRD-verbatim constants), `test_users.py` (45; per-instance builders for the entity-backed Candidate/Supervisor roles), `fixtures.py` (279; composite setups incl. `verify_six_area_minima`, `pass_all_six_divisions`, `setup_eligible_candidate`, `setup_certificate_holder`), `__init__.py` (64).

`test_suite/` (13 files, 2874 lines): `conftest.py` + `test_01_registries` … `test_12_security_and_concurrency`, **80 tests total**.

### Audit results
- **Collection**: `pytest --collect-only` → **80 tests, 0 errors**; pyflakes clean on `test_suite/`.
- **Tag audit** (AST docstring walk vs `yaml.safe_load` of both indices): 62 unique tags; **18 difficulty instances × exactly 2 tests**, **44 corner non-stub instances × exactly 1**; 0 orphans, 0 untagged, 0 dual-tagged; 6 `excluded_because` stubs correctly not emitted, all 6 cross-references resolve to real difficulty instances.
- **Constants audit**: after wiring, all 15 constants have live usages (zero dead); every value greps verbatim to PRD prose (18/18 anchors found: 3740, 160/360/260/1360/1520/80, 8/60-month tiers, 100/50, 1..2000, 64 credits, 24/12 CE defaults, 1..24 CE entries, limit 10, division order CE/PA/PCM/PDD/PJM/PPD, clock 2026-09-01T00:00:00Z).
- **C1 citation sweep**: 129 quoted docstring spans ≥12 chars, **all** survive literal whitespace-normalized grep of `workspace/PRD.md` (9 initial failures fixed: ellipsis elisions, a semicolon/period mismatch, hyphen line-breaks, and two endpoint-titular §4-table pseudo-quotes replaced with rule-bearing §3.2/§3.6 prose).
- **No skip/xfail** markers anywhere. **Clock discipline**: no `set_clock` target precedes 2026-09-01T00:00:00Z; every per-test clock sequence is monotonic non-decreasing.

### Skipped design instances
None. All 62 non-stub instances passed the PRD-first two-condition filter; gaps remain gaps (only the 6 sanctioned stubs are untranslated).

### PRD-adjudicated deviations from recipe literals
1. **Clock-reachability**: eight recipes set the clock to 2026-04-01, before the PRD-pinned startup instant. Those timelines were re-derived forward from 2026-09-01 (e.g., the 45-day reassign boundary re-anchored to a 2026-09-01 submission → 2026-10-15 fails / 2026-10-16 succeeds; locked-vs-projected T1 moved to 2026-09-15, preserving projected 80 / locked 40). All asserted values unchanged.
2. **Version literals** (`version == 1/2/3` in OCC and creation recipes) translated to relative assertions (positive integer at creation; exactly +1 per accepted guarded update, PRD §2.5) — PRD never pins the initial version, so absolute literals fail the two-reader test.
3. Dropped the `created_at == logical clock` sub-assertion (PRD pins timestamp format but never sources `created_at` from the logical clock); the client-supplied-fields-ignored rule (PRD §2.5) is still fully asserted.
4. `last_failed_at == 2026-11-30` retention after a PASS kept: PRD §3.4's PASS side-effect list is exhaustive and never clears that field.

Orchestrator spot-check: `test_helpers/` (9 files) and `test_suite/` (13 files) exist on disk; independent `pytest --collect-only -q` reports **80 tests collected in 0.22s, 0 errors**; independent tag histogram from `grep "^ *Design: "` = 44 tags ×1 + 18 tags ×2 = 80 total, matching the §1.8/§1.9 instance counts exactly; `constants.py` read in full — all 15 constants carry verbatim PRD quote comments and match the PRD values the orchestrator spot-checked in Step 4.

## Step 6: Generate implementation — 2026-10-01T14:28:00.000Z

Implementation complete. Summary of what was delivered and verified:

## Module list (all in `workspace/implementation/`, 2,138 lines total)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded `pip install` (skips when flask importable), `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `flask>=2.2,<4` |
| `app.py` | 52 | App factory, ApiError/404/405/500 handlers in the PRD envelope, blueprint registration under `/licensure` |
| `store.py` | 89 | In-memory dicts (empty at boot, no seeding), logical clock starting exactly `2026-09-01T00:00:00Z`, `now_iso`/`today`, `stamp_new`/`touch` (version bump + updated_at) |
| `dates.py` | 29 | Calendar-month/day addition (day-of-month clamped), ISO date parsing |
| `errors.py` | 51 | Full 33-id error catalog with PRD §5 HTTP statuses |
| `envelope.py` | 62 | Success/error envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit` 10/1/100, `offset` 0, `total_count`, `has_more`, created_at-asc default sort with override hook) |
| `auth.py` | 37 | `X-User-Role`/`X-User-ID` tier-1 auth, role-list tier-2, candidate ownership |
| `services.py` | 245 | All PRD constants verbatim (3740; 160/360/260/1360/1520/80; 8/60-month tiers; 45/60/90-day windows; 3-per-365 strict cutoff; 64 credits; 24-month periods; 12-cap carry; +4 HSW penalty; 60-day half-open renewal window; 12-month inclusive reinstatement), credit tiering with per-report `Decimal` ROUND_HALF_UP, area aggregation, completion gate, eligibility recompute, CE totals/carry |
| `serializers.py` | 199 | Explicit whitelists per entity; password never serialized; `_prev_period` internal carry bookkeeping hidden |
| 9 route modules | 1,431 | Clock+sweep, registries, education, experience, exam, supplemental, certificate/CE, transmittal, disciplinary |

## Route coverage
Registered routes: **40** — PRD §4: **40** (exact match; Flask `<param>` vs PRD `{param}` style difference only).

## Boot verification transcript (real server, since killed)
- `POST /licensure/jurisdictions` (CA) → 201, defaults `min_total_experience_hours: 3740`, `ce_hours_required: 24`, `version: 1`
- `POST /licensure/candidates` → 201, sub-statuses `NONE/NOT_STARTED/NOT_AUTHORIZED/CLEAR`, `certificate_eligible: false`
- `GET /licensure/candidates/{id}` → 200; missing headers → 401 `ERR_UNAUTHENTICATED` in the error envelope
- Report flow: submit at 2026-09-01 with work end 2026-08-01 → `SUBMITTED, credit_pct=100`; supervisor verify → `VERIFIED, credited_hours=161`; summary → `IN_PROGRESS`, totals 161
- OCC: `PATCH /jurisdictions/{id}` with `expected_jurisdiction_version: 99` → `ERR_STALE_VERSION`
- Clock set → `{"current_utc": "2027-03-01T00:00:00Z"}`; sweep → `{"expired_divisions": 0, "lapsed_certificates": 0}`
- Exam: authorization created six ELIGIBLE rows; exam-progress list ordered **CE, PA, PCM, PDD, PJM, PPD** (verified after fixing a pagination re-sort that would have clobbered the division_code order); schedule → `SCHEDULED`; report PASS → `passed_at 2027-03-01`, `expires_at 2032-03-01` (+60 months)

## Checks
- `python3 -m py_compile` passes on all 17 modules.
- Validation order follows PRD §2.6 tiers (auth → role/ownership → existence/jurisdiction → state incl. OCC → safety → referential → temporal → constraint), including the PRD's tier-6 order (`ERR_SUPERVISOR_NOT_ACTIVE` before `ERR_SUPERVISOR_MISMATCH`) and tier-7 order (retake → attempt-window → date-past).
- No invented guards (e.g., resubmit does not re-check the 64-credit floor; void of an already-voided CE entry is allowed; no reverse-GET on authorizations); every validation helper is reachable from a live route.
- Isolation rule honored: only `INSTRUCTION.md`, `SCAFFOLD.yaml`, and `PRD.md` were read — no design YAMLs, no `test_suite/`, no `test_helpers/`; no pytest or benchmark runner was executed. Both verification servers were killed by exact PID; ports are free.

Orchestrator spot-check: 17 `.py` modules + `start.sh` + `requirements.txt` on disk (2,132 lines total); independent url_map dump shows **40 endpoints (path+method pairs)** — the 34 unique paths collapse 6 dual-method paths, so the subagent's "40" claim is exact, not inflated; `errors.py` carries 35 `ERR_` ids; constants grep confirms 3740 / 1360 / 1520 / clock default `2026-09-01T00:00:00Z` present in services.py/store.py. (Subagent's "33-id error catalog" phrasing differs from the 35-token grep; the grep count is authoritative and matches PRD §5's 35 rows.)

## Step 7: Run tests and iterate — 2026-10-01T14:55:00.000Z

The sweep is legitimately green: round 1 ran 143 seconds (per-test-server isolation over 80 tests), and the test identities match this task's domain (candidates, jurisdictions, OCC, supervisors, clock). All 8 results files are on disk in workspace/implementation/.

## Summary

- **Iterations run:** 1 (initial sweep was clean — no fixes needed)
- **Tests deleted:** none
- **Fixes applied to `test_helpers/`:** none
- **Fixes applied to `test_suite/`:** none
- **Fixes applied to `implementation/`:** none
- **Sweep result:** all 8 parallel rounds passed 80/80 (0 failed, 0 errors in every round). Round durations ~143s each, consistent with real per-test-server restarts, not a no-op artifact. Test nodeids verified against this task's domain (registries, education, experience, exam, certificate, transmittal, disciplinary, security/concurrency).
- **Shadow-check:** no fixes were applied at all, so there is no test-dominated iteration history to shadow. The implementation was written Step 6 against PRD only and passed the full suite on first contact. No sibling-path concerns beyond the standing caveat that 80 tests cannot assert every branch — Step 8 may still wish to audit PRD §3.4's PASS-side-effect list and the tier-6/tier-7 validation orderings in `services.py` / route modules, which the worklog flags as carefully implemented but only sample-tested.
- **Sweep evidence preserved:** `results.1.json` through `results.8.json` all remain on disk at `/home/ubuntu/github/CodingPRD/tasks/task_3380_architect_licensure_experience_hours_examination_progression/workspace/implementation/`.

Orchestrator verification (independent of subagent claims): all 8 `results.*.json` parsed directly — every round reports `passed: 80, failed: 0, errors: 0, total: 80`; files are ~26 KB each (real per-test detail, not stubs); `find -newer results.1.json` over non-pycache `.py` sources = 0 files, so no post-sweep edits invalidate the green run (newest source `routes_exam.py` mtime 14:46 predates the 14:53 sweep).

## Step 8: Finalize PRD — SKIPPED — 2026-10-01T14:56:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced. Step 9 will read `PRD.md` directly.

## Step 9: Complete PRD — 2026-10-01T15:19:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_3380_architect_licensure_experience_hours_examination_progression/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output**: `PRD_FINALIZED.md` absent (Step 8 skipped as expected) → sourced from `PRD.md` (274 lines / 46,491 bytes). `PRD_COMPLETED.md`: 276 lines / 51,840 bytes (+2 lines, +5,349 bytes). `diff -q PRD.md PRD_COMPLETED.md` → **files differ** (exit 1); 21 paragraph hunks changed, all in-place inserts/revisions, no new sections.

**Counts**: 27 ambiguity-pins, 3 mismatch-revisions.

### Changes (one bullet each)

- §2.2 — insert — ambiguity — unmatched routes and unsupported methods answered with `ERR_NOT_FOUND` (404) in the standard error envelope — app.py:19-25
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, negative `offset` → `ERR_INVALID_REQUEST` — envelope.py:41-54
- §2.4 — insert — ambiguity — calendar-month addition clamps to the target month's last day when the day-of-month doesn't exist — dates.py:22-29
- §2.4 — insert — ambiguity — calendar-date fields exchanged as `YYYY-MM-DD`; instant fields (`created_at`, `submitted_at`, `issued_at`, `current_utc`, …) as UTC timestamps — serializers.py, store.py:67-70
- §2.7 — revise — mismatch — "All hour figures are integers" → "All credited hour figures … are integers, and continuing-education entry hours are integers" (impl accepts decimal report `hours`; CE entry hours must be int) — routes_experience.py:53-54, routes_certificate.py:148-150
- §3.1 — insert — ambiguity — duplicate candidate `email` → `ERR_INVALID_REQUEST` — routes_registry.py:47-49
- §3.1 — revise — mismatch — "four optional overrides" → "five" (PRD listed five, impl accepts five) — routes_registry.py:128-140
- §3.1 — insert — ambiguity — guarded jurisdiction update accepts `name` plus the five overrides, omitted fields unchanged — routes_registry.py:169-184
- §3.1 — insert — ambiguity — supervisor registration accepts optional `license_status` (`ACTIVE`/`INACTIVE`, default `ACTIVE`); duplicate `license_number` → `ERR_INVALID_REQUEST`; guarded update accepts `full_name`/`license_status`/`jurisdiction_code` with `ERR_JURISDICTION_UNKNOWN` on bad code — routes_registry.py:202-216, 231-242
- §3.2 — insert — ambiguity — resubmit of non-`DEFICIENT` → `ERR_INVALID_STATE`; the 64-credit floor and the one-open rule are NOT re-applied on resubmission — routes_education.py:118-139
- §3.3 — insert — ambiguity — report `hours` accepted as any JSON number; non-numeric → `ERR_INVALID_REQUEST` — routes_experience.py:53-55
- §3.3 — insert — ambiguity — candidate listing scoping: absent `candidate_id` forced to caller, foreign `candidate_id` → `ERR_UNAUTHORIZED` — routes_experience.py:102-106
- §3.3 — insert — ambiguity — omitted `new_supervisor_id` → `ERR_INVALID_REQUEST`, evaluated before the 45-day window/fitness checks — routes_experience.py:220-225
- §3.3 — insert — ambiguity — concrete summary definitions: `total_credited_hours`/`area_progress` = VERIFIED only; `locked_credited_hours` adds in-flight SUBMITTED at locked tier; DRAFT/RETURNED contribute zero — routes_registry.py:81-97
- §3.3 — revise — ambiguity — summary `certificate_status` = live (non-REVOKED) cert's status, else most recently created cert's, else null — routes_registry.py:98-114
- §3.4 — insert — ambiguity — granting authorization when `exam_status` ≠ `NOT_AUTHORIZED` → `ERR_INVALID_STATE` — routes_exam.py:36-37
- §3.4 — insert — ambiguity — missing/unparseable `scheduled_date` → `ERR_INVALID_REQUEST`, evaluated before temporal checks — routes_exam.py:102-106
- §3.4 — insert — ambiguity — scoring a non-`SCHEDULED` division or before the sitting date → `ERR_INVALID_STATE` — routes_exam.py:135-138
- §3.5 — insert — ambiguity — missing `jurisdiction_code` / missing or unparseable `exam_date` → `ERR_INVALID_REQUEST`, before date-past and retake-wait checks — routes_supplemental.py:34-42
- §3.5 — revise — ambiguity — 90-day retake wait measured from the candidate's most recent FAILED sitting **for that same jurisdiction** — routes_supplemental.py:43-51
- §3.5 — insert — ambiguity — early or non-`REGISTERED` result reporting → `ERR_INVALID_STATE` — routes_supplemental.py:88-91
- §3.6 — insert — ambiguity — `serial_number` format `CERT-` + 12 uppercase hex digits — services.py:173-174
- §3.6 — revise — ambiguity — history returns all certificates incl. REVOKED, `created_at` ascending, in a single list window without `limit`/`offset` applied — routes_certificate.py:64-73
- §3.7 — insert — ambiguity — renewing a `REVOKED` certificate → `ERR_INVALID_STATE` — routes_certificate.py:122-123
- §3.7 — insert — ambiguity — CE entry on non-ACTIVE/LAPSED cert → `ERR_INVALID_STATE`; completed_date parse/future rules evaluated before field-shape checks; missing/unparseable completed_date, non-integer hours, non-boolean hsw, missing provider → `ERR_INVALID_REQUEST` — routes_certificate.py:133-160
- §3.7 — insert — ambiguity — voiding is idempotent and available regardless of certificate status — routes_certificate.py:194-205
- §3.7 — insert — ambiguity — `voided` filter accepts `true`/`1`/`false`/`0` case-insensitively; other values → `ERR_INVALID_REQUEST` — routes_certificate.py:183-190
- §3.7 — revise — mismatch — renewal carry is recomputed live at each renewal from then-current non-voided entries of the preceding period (not frozen at booking); backdated entries augment the next carry — services.py:202-217, routes_certificate.py:105
- §3.8 — insert — ambiguity — `GRANT` after certificate left `ACTIVE` → `ERR_CERTIFICATE_NOT_ACTIVE`; deciding a non-`REQUESTED` transmittal → `ERR_INVALID_STATE` — routes_transmittal.py:74-85
- §3.8 — insert — ambiguity — resolving a non-`OPEN` report → `ERR_INVALID_STATE`; supplied `resolution_notes` must be a string — routes_disciplinary.py:55-67

### Dead-code audit (report-only)

- Greps run: per-helper callsite counts over `services.py` (20 helpers, all ≥1 callsite); per-`error_id` callsite counts for all 36 catalogued IDs (`grep -rn "\"ERR_…\""` over routes/auth/app/envelope) — **every PRD error_id is constructed on a live request path; none found dead**.
- One unused helper: `fmt_date` at `implementation/dates.py:14` (defined, zero callsites) — a trivial date serializer, not a PRD-required validation or error gate; no PRD sentence requires it. Left untouched.
- Out-of-scope observation (not patched): `app.py:27-29` returns `ERR_INTERNAL` (HTTP 500) for unhandled exceptions; the PRD §5 catalogue covers only 4xx codes, so this fallback has no catalogue entry. Flagging for orchestrator adjudication.

### diff -q result

`diff -q PRD.md PRD_COMPLETED.md` → "Files PRD.md and PRD_COMPLETED.md differ" (exit 1) — 21 hunks, +2 lines, +5,349 bytes. All edits describe the implementation exactly as it stands (80/80 green suite untouched; no edit requires any impl change).

Orchestrator verification: independent `diff -q` confirms files differ (not a killed-mid-flight no-op); `PRD_COMPLETED.md` tail intact (ends with the §5 error table); 0 non-pycache impl sources newer than `results.1.json` — Step 9 made no implementation edits, so the green sweep remains valid; all 8 `results.*.json` still on disk. Orchestrator adjudication of the two flagged items: (a) `fmt_date` unused helper — harmless, not PRD-required, left as-is; (b) `ERR_INTERNAL` 500 fallback — a defensive default handler, not a PRD-contract behavior; no action.
