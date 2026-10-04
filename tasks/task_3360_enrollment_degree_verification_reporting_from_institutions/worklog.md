# Worklog — task_3360_enrollment_degree_verification_reporting_from_institutions

## Step 1: Create Task Directory — 2026-10-01T08:50:00.000Z

Task directory pre-allocated by invoker: `tasks/task_3360_enrollment_degree_verification_reporting_from_institutions/` with `workspace/` inside. Verified it exists; no new index computed, no other task_* directory created.

## Step 2 (resumed): Scaffold repair — 2026-10-01T10:13:52.815358251Z

Prior session was interrupted mid-Step-2. Found SCAFFOLD.yaml (84KB) and SCAFFOLD_DIFFICULTY_DESIGN.yaml (86KB) on disk; SCAFFOLD_CORNER_DESIGN.yaml missing. SCAFFOLD.yaml had invalid YAML (bare `token?` scalars in flow sequences); repaired by quoting (15 fix rounds), now parses: 43 endpoints, 14 entities, 37 errors, 7 roles, all §1.0–§1.7 sections present, no forbidden keys. DIFFICULTY file parses OK. Regenerating only the missing SCAFFOLD_CORNER_DESIGN.yaml via subagent.

## Step 2: Generate Scaffold — 2026-10-01T11:03:12.388420193Z

Done. Summary of the work:

**File written**: `SCAFFOLD_CORNER_DESIGN.yaml` (2301 lines, single top-level key `scaffold_corner_design`). SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml were only read, never modified.

**YAML parse verification**: `yaml.safe_load` succeeds. One authoring error was caught and fixed (a missing `setup:` key in `compliance_standing_lookback_ages_out_old_delinquent`); one payload type typo (`credit_hours: "12.0"` → `12.0`) was also fixed.

**The skill's own `scaffold_lint.py` verdict** (run against the task dir): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` — 89 §1.9 instances, 1015 total §1.8+§1.9 calls scanned.

**Instance counts per §1.9 section** (103 entries = 89 real instances + 14 `excluded_because` stubs): entities 8/0, state_machines 20/0, calculations 7/2, validations 14/0, endpoints 4/0, errors 20/9, rbac 12/0, complexity_layers 3/3, consistency_model 1/0. Coverage: creation+embedded users ordering, defaults, computed fields, student resolution, screening reject_reason matrix incl. MAX_CREDIT_HOURS 30.0 boundary; agreement half-open lifecycle, period grace strict-> boundaries, certify/pay/ack idempotency, terminal lockdowns, notification dispatch, file supersession, correction DENIED, directive supersession/expiry, quote expiry TTL, transcript artifact TTL, suspend/reinstate guards, ops-suspend refund asymmetry; DEFERMENT_INELIGIBLE band, REPAYMENT_DUE grace boundary, on-time certify at due date, DELINQUENT->LATE remediation, 3-period compliance lookback, volume-tier quarter reset, STANDARD-tier rush fee 2132; error priorities, tenancy, malformed payload, clock strictly-forward, consent paths, purpose matrix; pagination envelope defaults; all catalog errors triggerable; 6 exclusive-op denials + 3 ownership denials + 3 scoped listings; OCC stale-version 412s; immediate read-after-write. All fixture dates reachable from pinned default clock 2026-09-01T00:00:00Z moving strictly forward; every OCC expected_*_version references an earlier capture; all names resolve verbatim against SCAFFOLD.yaml; 89 names unique vs §1.8's 19.

Orchestrator verification: file parses; 89 real + 14 stub instances confirmed on disk; 89 unique names confirmed. Full scaffold set now complete: SCAFFOLD.yaml (43 endpoints, 14 entities, 37 errors, 7 roles), SCAFFOLD_DIFFICULTY_DESIGN.yaml (19 instances), SCAFFOLD_CORNER_DESIGN.yaml (89 real instances).

## Step 3: Copy Shared Files — 2026-10-01T11:03:18.588899043Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-10-01T11:31:25.236666389Z

PRD generated at `workspace/PRD.md` (355 lines), built solely from the task's SCAFFOLD.yaml plus the doc-generator skill spec. The two forbidden design-index files and all sibling tasks were never opened.

**Section list**: 1. Introduction; 2. Global Specifications (2.1 Roles/Access Control all 7 roles; 2.2 API Response Structure canonical block verified byte-identical; 2.3 Pagination limit 10/1/100, offset 0, created_at ASC; 2.4 Logical Clock default 2026-09-01T00:00:00Z strictly forward with pinned 6-step advance order; 2.5 Common Resource Properties; 2.6 OCC both rules; 2.7 Precision integer cents half-up, 2dp credit hours, 4dp rates, day granularity; 2.8 Reference Resolution & Evaluation Order first-failure-wins cascade, 404 family; 2.9 State Transitions & Cascading Consistency); 3. Business Logic (9 subsections: onboarding/agreements, reporting calendar & compliance standing, file submission & row screening, certification/status determination/servicer feed, correction cycle, degree lifecycle, requester vetting & verification commerce, learner self-service & privacy directives, research data services); 4. Endpoint Definitions (43-row, 4-column table); 5. Error Code Catalogue (37-row table; document ends there).

**Coverage self-audit (mechanical, script-verified)**: field names 100/100 present in backticks; error IDs 37/37 with trigger+status; roles 7/7 with identity prose; enum values 85/85 exact; state transitions 42/42 with from/to in prose, preconditions paired with error_ids, cascades enumerated; calculation constants 20/20 with exact values (12.0/6.0/9.0/4.5 bands, 14-day census offset, 30-credit ceiling, 180-day withdrawal grace, 2599/1599/0-cent base fees, 2000/3333 bps, 48h quote TTL, 72h artifact TTL, 2 max transcripts, tier threshold 3, k-anonymity 10, 730-day completion lag, 14-day grace, 3-period standing lookback); OCC rules 2/2; endpoints 43/43 with per-endpoint validation priority narration; §3 path purity 683 tokens scanned, 0 violations; no fuzzy words, no pseudocode.

Orchestrator spot-check: 355 lines, 84 table rows, 37 unique ERR_ tokens, default clock literal present.

## Step 5: Generate Unit Tests — 2026-10-01T12:22:08.887926361Z

Everything is green. All verification passes are complete:

- **127 tests collected** with `pytest --collect-only` (0 errors — package graph imports cleanly with `PYTHONPATH=<task dir>`)
- **All 207 quoted PRD citations survive verbatim grep** against PRD.md (4 initial failures from elided quotes were fixed with full-sentence citations)
- **All 127 Design tags validate** against the source YAMLs (namespace, rule_id/section, instance name all resolve; no stub tagged; no dual/untagged tests)
- **No skip/skipif/xfail markers** anywhere

**Files written** — test_helpers/ (9 files): types.py (7 role/28 status enums + 14 entity TypedDicts), constants.py (PRD-pinned: fees 2599/1599/0, 3333/2000 bps, TTLs 48h/72h, tier threshold 3, k-anonymity 10, lag 730d, grace 14d, credit bands 12.0/6.0/9.0/4.5, max 30 credits, clock start 2026-09-01T00:00:00Z), api_errors.py (all error IDs + HTTP map), api_client.py (33 endpoint methods incl. `/_clock/set_current_utc`), assertions.py (per-entity shape + file row-partition invariant), factories.py (incl. `enrollment_row` builder), test_users.py (opaque-role shared headers + make_*_headers builders), fixtures.py (composite period/upload/certify/degree/requester/tier/OCC/research fixtures). test_suite/ (15 files): conftest.py plus test_01..test_14 grouped by concern.

**Coverage**: Queue A (difficulty): 19/19 instances translated, 2 tests each = 38 tests. Queue B (corner): 89/89 non-stub instances translated, 1 test each = 89 tests. Skipped: exactly the 14 `excluded_because:` stubs (2 calculations, 9 errors, 3 complexity-layers) — not translated per spec; owning difficulty instances carry the assertions. No PRD-first filter skips needed.

**PRD-vs-design discrepancies**: none found; all design literals matched PRD (fee arithmetic 2599->2079->693->2772; grace dates verified; TTL dates verified; rates 4/10=0.4, 4/9=0.4444; balance conservation 50000-3*2599-2772=39431). Clock discipline: every set_current_utc target advances strictly forward from the pinned 2026-09-01T00:00:00Z default; past-looking dates appear only as entity payload data.

Orchestrator verification: `pytest --collect-only` re-run by orchestrator — 127 tests collected, 0 errors; all 9 test_helpers files and 15 test_suite files present on disk.

## Step 6: Generate Implementation — 2026-10-01T12:55:06.946448691Z

Implementation complete and boot-verified by the subagent. Files written under workspace/implementation/ (~2,670 lines): start.sh (10, guarded pip install, exec python3 app.py, PORT/0.0.0.0), requirements.txt (flask>=3.0,<4), app.py (63, Flask app + error handlers), core.py (210, 37 error IDs + envelope + pagination + ISO8601 + validators), db.py (81, empty in-memory store, logical clock default 2026-09-01T00:00:00Z, version from 1, monotonic _seq tiebreak), auth.py (82, role extraction + entity-backed resolution), calc.py (195, status determination FT/HT 12/6 UG 9/4.5 GR, census +14d, deferment +180d strict, pinned fee quote round-half-up 2599/1599/0 + 2000/3333 bps, quarterly volume tier >=3, 3-period compliance standing), cascade.py (203, suspension + cancellation cascade, notification generation/supersession, file supersession, period close, pinned six-step clock advance), r_institutions.py (264), r_enrollment.py (401, deterministic row screening all 6 reject reasons, OCC on period version, full certify cascade), r_corrections.py (237, segregation of duties, replacement entry row_index := row_count), r_degrees.py (148), r_requesters.py (93), r_verification.py (350, pinned guard chain, pay/fulfill with refunds and TTL), r_students.py (100, directive OCC + supersession), r_notifications.py (71), r_research.py (136, opt-out -> k>=10 -> 730d completers -> census-withdrawn exclusion -> 4dp rates), r_clock.py (23, strictly-forward set_current_utc).

Boot smoke test (run twice, PIDs saved and killed exactly): 401 unauthenticated; POST /institutions 201 with embedded users in input order; GET without users key; agreement 201 ACTIVE; period 201 OPEN with grace_ends_at = due+14d; upload 201 with correct status determination on both as-of variants; stale version 412 ERR_STALE_VERSION; certify 200 with QUEUED notification; clock advance flips QUEUED->SENT; servicer ack writes deferment_standing; consent gate 422; rush fee 2132 verified; pay -> PAID; fulfill -> RELEASED with FULL_TIME; second boot returns 404 (fresh store confirmed). No seeding; no forbidden reads (no design indices, no test dirs, no sibling tasks); pytest not run.

Ambiguities resolved (choices): (1) registrar role/entity mismatch -> 401; (2) duplicate ope_id/email -> 400 ERR_VALIDATION; (3) timestamps from logical clock, 3 fractional digits; (4) past-period create -> CLOSED/DELINQUENT + standing recompute; (5) duplicate student_ref counts any prior row incl. rejected; field-level reasons precede DUPLICATE; (6) corrected_credit_hours validated 0-30; (7) research latest entry by (term_start, insertion seq); (8) period-close outcome considers any ever-certified file; (9) clock step 1 activations before expirations.

Orchestrator verification: all 18 files on disk with matching line counts; every .py parses via ast.

## Step 7: Run Tests and Iterate — 2026-10-01T13:18:41.797799910Z

Clean 8-round parallel sweep achieved: **127/127 passed in every round**, no flakiness. All `results.1..8.json` deliverables are in place under `workspace/implementation/` and no edits followed the final sweep.

**Iterations run: 2** (round 1: 16 deterministic failures, identical across all 8 rounds; round 2: clean).

**Tests deleted: none.** Every failure traced to either a fixable test artifact or a fixable implementation choice; no PRD-silence or unique-derivability deletions were needed.

**Implementation fixes** (`workspace/implementation/`):
- `core.py` — added `fmt_dt_sec()` (whole-second `T00:00:00Z` rendering). The Step-6 worklog recorded "timestamps from logical clock, 3 fractional digits" as an ambiguity choice; that drifted from the PRD's own notation (clock default written `2026-09-01T00:00:00Z` in §2.4, date-valued fields as `T00:00:00Z` in §2.5), which pins three fractional digits only for `api_request_timestamp`, `created_at`, `updated_at` (§2.2/§2.5).
- `db.py` — `serialize()` routes `created_at`/`updated_at` through 3-frac `fmt_dt`, all other datetimes through `fmt_dt_sec`.
- `r_clock.py` — `current_utc` rendered with `fmt_dt_sec`.
- This fixed 8 tests asserting exact instants (`grace_ends_at` = due+14d, `quote_expires_at` = +48h, `artifact_expires_at` = +72h, `certified_at`, `decided_at`, `released_at`, notification `grace_end_date` = withdrawal+180d).

**test_helpers/ fixes** (`test_helpers/fixtures.py`):
- `list_file_entries()` — added `"limit": 100` to the params. The PRD §2.3 default page size is 10, so 12-row fixture files silently truncated and `entries[10]`/`entries[11]` raised `IndexError` in all four test_14 research-cohort tests. Matches the classic pagination trap; the dedicated pagination-envelope test calls the raw client and is unaffected.

**test_suite/ fixes**:
- `test_02_institution_suspension.py` — (a) added missing `setup_period_scenario` import (NameError in `test_err_agreement_lapsed_upload_and_reinstate`); (b) re-dated `_build_expiry_scene` and both `advance_clock` calls: the original scene advanced the clock to 2026-04-10, before the PRD-pinned default clock 2026-09-01T00:00:00Z (clock-unreachable fixture). Scene now: agreement 2026-08-01→2027-02-01, period opens 2026-10-01 / due 2026-11-20, advance to 2026-10-10 for upload/certify/pay, expiry advance to 2027-02-01.
- `test_06_corrections.py` — `test_correction_apply_supersedes_entry_and_regenerates_notification`: changed `notifications[0]["status"]` assertion from `SUPERSEDED` to `ACKNOWLEDGED`. The scene acknowledges n1 before the correction, and PRD §3.4 states verbatim: "the entry's `QUEUED` and `SENT` notifications move to `SUPERSEDED`; acknowledged ones are historical and remain." The implementation already followed the PRD; the test contradicted it.

Orchestrator verification: all 8 results.*.json on disk show passed=127/127 failed=0; newest implementation source mtime (13:11:11) precedes final sweep results (13:17:29) — no post-sweep edits.

## Step 8: Finalize PRD — 2026-10-01T13:24:57.793718268Z

Done. `PRD_FINALIZED.md` is written with exactly one revision.

**Line counts**: PRD.md = 355 lines, PRD_FINALIZED.md = 355 lines — 0.0% line delta (single in-place line extension on line 99).

**Changes**:
- **§2.4 — revise — appended the per-class timestamp-rendering rule to the closing paragraph**: `api_request_timestamp` (§2.2) and `created_at`/`updated_at` (§2.5) carry three fractional digits; every other returned timestamp (`current_utc`, derived instants like `grace_ends_at`/`quote_expires_at`/`artifact_expires_at`, stamped instants like `certified_at`/`decided_at`/`sealed_at`/`vetted_at`/`paid_at`/`released_at`/`generated_at`) renders whole-second with no fractional component — `implementation/core.py:71-88` (`fmt_dt`/`fmt_dt_sec`), `implementation/db.py:79` (`serialize()` routing), `implementation/r_clock.py:23` (`current_utc` via `fmt_dt_sec`).

**Step-7 items adjudicated as no-edit** (PRD already determines behavior): fixtures.py limit:100 (PRD §2.3 pins default 10/max 100; impl core.py:151-163 matches); test_02 import + re-dating (test-side clock-discipline fix vs PRD-pinned default; impl db.py:12 matches); test_06 SUPERSEDED->ACKNOWLEDGED (PRD §3.4 already states the acknowledged-ones-remain rule verbatim; impl cascade.py:76-79 matches).

**Per-edit pre-edit search log** (the single edit): (a) subject: rendering precision of timestamps in API responses. (b) paths enumerated: core.py:71-88, core.py:122, db.py:70-82 (serialize choke point), r_clock.py:23, r_institutions.py:164-165,218-220, r_students.py:82-83, r_enrollment.py:115,128,189,214,238, r_corrections.py:99-104,213, r_degrees.py:64-66, r_requesters.py:47, r_verification.py:189-194, r_research.py:52, cascade.py:67; strftime/isoformat grep confirmed no response path bypasses the two formatters. (c) wording framed as universal rule with illustrative "such as" lists so unlisted whole-second fields are covered; the three 3-fractional-digit fields named as the only exceptions, matching serialize() routing exactly.

Orchestrator verification: diff PRD.md vs PRD_FINALIZED.md is exactly the single line-99 revision claimed; implementation source untouched (newest mtime still 13:11:11, pre-sweep).

## Step 9: Complete PRD — 2026-10-01T13:53:26.418648473Z

All checks pass. Final summary:

**PRD_COMPLETED.md produced.** Source vs output: `PRD_FINALIZED.md` 355 lines / 58,413 chars -> `PRD_COMPLETED.md` 355 lines / 63,140 chars (char delta +4,727; 25 lines touched, all in-paragraph — no new sections, no new lines).

**Counts:** 19 ambiguity-pins, 8 mismatch-revisions (27 edits total; two edits shared one paragraph line).

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**
- §2.1 — insert — ambiguity — registrar auth is role-exact: wrong-role/DEACTIVATED/unknown InstitutionUser -> 401 ERR_UNAUTHENTICATED — auth.py:49-58
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the logical clock — core.py:117-123
- §2.3 — insert — ambiguity — invalid limit/offset -> ERR_VALIDATION 400; created_at ties broken by insertion sequence — core.py:151-163, db.py:85-87
- §2.4 step 1 — revise — ambiguity — within step 1 all activations (created_at ASC) run before expirations — cascade.py:139-167
- §2.8 — insert — ambiguity — registrar reads/lists scoped to own institution -> ERR_UNAUTHORIZED; path-addressed tenancy precedes existence, resource-carried tenancy follows it; list filters auto-scoped — auth.py:79-82, r_enrollment.py:277-305, r_institutions.py:114
- §3.1 — revise — ambiguity — duplicate `ope_id` -> ERR_VALIDATION 400; duplicate email in `users` -> ERR_VALIDATION; `users` may be empty — r_institutions.py:69-80
- §3.1 — revise — ambiguity — agreement created with window fully in the past begins SCHEDULED, expiring only via clock — r_institutions.py:159-160
- §3.2 — insert — ambiguity — period created entirely in the past begins CLOSED, settled at creation with outcome DELINQUENT + standing recompute — r_institutions.py:227-229
- §3.2 — revise — mismatch — close outcome counts any ever-certified file (certified_at set), including SUPERSEDED, not "a CERTIFIED file exists" — cascade.py:110-121
- §3.3 — revise — ambiguity — upload gauntlet: a period id belonging to another institution counts as ERR_PERIOD_NOT_FOUND — r_enrollment.py:166-168
- §3.3 — revise — ambiguity — screening: a string student_ref joins the seen-set even if the row is later field-rejected; field-level reasons (MISSING_FIELD -> INVALID_ENUM_VALUE -> INVALID_CREDITS -> INVALID_TERM_DATES -> INVALID_WITHDRAWAL_DATE) precede DUPLICATE_STUDENT_IN_FILE; rejected entries carry null student_id + raw values; empty `rows` valid — r_enrollment.py:62-118, 199-254
- §3.3 — revise — mismatch — entry listing is effectively created_at ASC (insertion tiebreak); the row_index-primary reading was wrong (the row_index sort is shadowed) — r_enrollment.py:398-401
- §3.4 — revise — mismatch — certify check order: file-exists -> tenancy -> UPLOADED -> ACTIVE -> agreement -> clean (PRD had tenancy first) — r_enrollment.py:312-327
- §3.4 — revise — ambiguity — certification into an ON_TIME/LATE period leaves outcome unchanged — r_enrollment.py:354-357
- §3.4 — revise — mismatch — deferment_standing is last-acknowledgement-wins, not "latest by created_at" — r_notifications.py:65-70
- §3.4 — revise — mismatch — correction-driven notification supersession is conditional on the deferment_status actually changing — r_corrections.py:231-234
- §3.5 — revise — mismatch + ambiguity — filing order: payload -> entry-exists -> tenancy -> file-state -> superseded -> open-case; `corrected_credit_hours` must be a finite number in 0-30 else ERR_VALIDATION; `corrected_withdrawal_date` must parse — r_corrections.py:57-92
- §3.5 — revise — mismatch — decision order: payload -> case-exists -> tenancy -> FILED -> segregation — r_corrections.py:156-168
- §3.5 — insert — ambiguity — a FILED case on a since-superseded file is still decidable; approval installs the replacement on the SUPERSEDED file — r_corrections.py:151-237
- §3.6 — revise — mismatch — seal order: exists -> tenancy -> REPORTED -> ACTIVE -> agreement -> standing — r_degrees.py:113-128
- §3.6 — revise — ambiguity — revoke order: exists -> tenancy -> SEALED — r_degrees.py:139-145
- §3.7 — revise — ambiguity — `initial_credit_cents` must be a non-negative integer else ERR_VALIDATION — r_requesters.py:37-39
- §3.7 — revise — ambiguity — purpose matrix evaluated only for well-formed product/purpose enums; malformed values fall through to ERR_VALIDATION — r_verification.py:95-117
- §3.7 — revise — ambiguity — ENROLLMENT release uses the student's latest ACCEPTED entry at the institution by (term_start, insertion seq) — r_verification.py:329-346
- §3.9 — revise — ambiguity — unknown scope_institution_id -> ERR_INSTITUTION_NOT_FOUND; computed fields null until generation — r_research.py:36-56
- §3.9 — revise — ambiguity — "latest entry" = latest in-window ACCEPTED entry by (term_start, insertion seq); zero adjusted denominator reports 0.0 — r_research.py:117-132, calc.py:192-195
- §3.4 — revise — ambiguity — acknowledge order: exists -> servicer_ref match -> SENT — r_notifications.py:60-64

**Dead-code check:** none found among PRD-required checks — every helper/gate is reachable (callsites grep-verified: `generate_notification`, `supersede_*`, `close_period`, `active_agreement_covers`, `suspend_institution`, `compliance_standing`, `recompute_entry`, `has_active_directive`, `fee_quote`/`volume_tier`, `round4`, `require_registrar_tenancy`, and every error constant in the §5 catalogue). Only cosmetic dead code exists: an unreachable duplicated `return` block at r_enrollment.py:120-131 (after `return` at line 118) — no behavioral effect, not PRD-pinned.

**All eight known Step-6 resolutions confirmed in code and pinned** (registrar 401, ope_id/email 400, past-period DELINQUENT settle, duplicate-ref precedence, corrected-credits 0-30, research latest-entry, ever-certified close, activations-before-expirations).

**Implementation not modified:** confirmed by subagent — only `cp` + edits to PRD_COMPLETED.md.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (not a silent no-op); all 8 results.*.json still in place; newest implementation source mtime unchanged at 13:11:11 (pre-sweep) — the clean 8-round sweep remains valid.

## Pipeline complete — 2026-10-01T13:53:26.426002257Z

All 9 steps done. Final sweep: 127/127 tests passing in all 8 parallel rounds under per-test-server isolation.
