# Worklog — task_3387_volunteer_home_repair_project_selection_trade_coordination

## Step 1: Create Task Directory — 2026-10-01T13:57:58.737Z

Pre-allocated task directory verified at `tasks/task_3387_volunteer_home_repair_project_selection_trade_coordination/` with `workspace/` inside (per command args; no new index computed, no other task_* directory created). `./INSTRUCTION.md` present at project root (1424 bytes) for Step 3.

## Step 2: Generate Scaffold — 2026-10-01T15:29:03.810062744Z

All three deliverables are complete, parse cleanly, and pass `scaffold_lint.py` with zero violations. Summary for the worklog:

## Scaffold generation complete — task_3387_volunteer_home_repair_project_selection_trade_coordination

**Output files (all parse with `yaml.safe_load`):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3387_volunteer_home_repair_project_selection_trade_coordination/SCAFFOLD.yaml` — 2167 lines (§1.0–§1.7 only; no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3387_volunteer_home_repair_project_selection_trade_coordination/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2130 lines (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3387_volunteer_home_repair_project_selection_trade_coordination/SCAFFOLD_CORNER_DESIGN.yaml` — 3021 lines (single top-level key `scaffold_corner_design`)

**Counts:** 57 endpoints · 15 entities · 14 state machines · 10 calculations · 11 validation priority tiers · 44 error codes · 9 roles · 2 OCC concurrency rules

**api_prefix:** `/rebuild` · **Entities:** FundingCycle, SelectionRun, Sponsor, SponsorshipCommitment, HomeownerApplication, HomeAssessment, ScopeItem, Project, RebuildEvent, Volunteer, EventEnrollment, TradeContractor, TradeWorkOrder, MaterialOrder, WarrantyClaim

**§1.8:** 20 instances (all non-stub, 0 stub) — dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c all exercised), non_linear_state_machine 2, transitive_cascade 2 (depth-4 funding withdrawal + depth-3 contractor suspension), priority_pair_validation_conflict 2 (state>fiscal, safety>temporal), boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2 (half-open windows vs whole-day booking), compensating_invariant 2 (funding pool, event seats).
**§1.9:** 54 instances — 46 non-stub, 8 `excluded_because` stubs citing §1.8 instances.

**Design highlights (harder-than-expert levers):** integer-cross-multiplication income tiers (no float ambiguity at the 80%/50%/30% AMI boundaries); envelope contingency tier keyed on the pre-contingency estimate producing a provable inversion (estimate 499999 → envelope 574999 > 550000 for estimate 500000); per-line-then-sum-then-fee material rounding pinned against sum-then-round (1727 vs 1726); STANDARD vs HAZARD_PRIORITY scoring variants (81 vs 100 on identical inputs); provisional vs reconciled project cost (450000 vs 510000); clock default fixed at 2026-09-01T00:00:00Z.

**Verification performed:** lint clean run (verbatim verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5`, 1083 calls scanned); all 66 instance names unique across the union; every `grounds:` ref resolves into §1.1–§1.7; zero unbound `${var}` placeholders; all 44 error ids referenced by a validation/transition/design; every pinned numeric literal re-executed in Python (caught and fixed one drifted literal, 5075→5175, before shipping); one unreachable error (`ERR_ASSESSMENT_NOT_SCOPED`) found and removed during self-audit; no forbidden concurrency vocabulary.

**Orchestrator verification:** all three files exist at the reported sizes, parse with yaml.safe_load, carry the expected top-level keys, and grep-confirmed the task domain (api_prefix `/rebuild` ×171 occurrences; HomeownerApplication/RebuildEvent/SelectionRun/TradeWorkOrder/WarrantyClaim all present) — not a foreign-domain artifact.

## Step 3: Copy Shared Files — 2026-10-01T15:29:15Z

Copied `./INSTRUCTION.md` → `tasks/task_3387_volunteer_home_repair_project_selection_trade_coordination/workspace/INSTRUCTION.md` (1424 bytes, verified present).

## Step 4: Generate PRD — 2026-10-01T15:36:00Z

PRD generation complete and all three hard contracts verified PASS.

**Deliverable**
- Path: `/home/ubuntu/github/CodingPRD/tasks/task_3387_volunteer_home_repair_project_selection_trade_coordination/workspace/PRD.md`
- 370 lines, 8,216 words. File ends at the final `ERR_WARRANTY_CAP_EXCEEDED` row of §5 — a complete table row, not truncated (tail-verified after every one of the 11 sequential writes).

**Section list**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (9 roles, entity-backed identity prose for Homeowner/Volunteer/TradePartner/SponsorRep, opaque for PlatformAdmin/AffiliateStaff/Assessor/Anonymous/Any) · 2.2 API Response Structure (emitted verbatim) · 2.3 Pagination (limit default 10, min 1, max 100; offset default 0; `created_at` ascending) · 2.4 The Logical Clock (`2026-09-01T00:00:00Z` initial, never wall-clock) · 2.5 Common Resource Properties (incl. ScopeItem carrying only `id`/`created_at`, no `updated_at`/`version`) · 2.6 Funding Pool Ledger (pool/reserved/spent/available + invariant) · 2.7 Money Handling (integer cents, round half up) · 2.8 Readiness Posture · 2.9 OCC (both rules, `ERR_STALE_VERSION` 412) · 2.10 Validation Priority Order (explicit 11-tier ordering) · 2.11 Nested Retrieval (all 15 NOT_FOUND ids)
- §3 Business Logic (9 subsections: funding cycles/sponsor money, applications/eligibility/priority, assessments/scope, selection runs/envelope/waterfall, amendments/reconciliation, events/volunteers/enrollments, trade work/contractor oversight, material orders, completion/warranty/close-out)
- §4 Endpoint Definitions: 4-column table, 57 rows = 57 scaffold endpoints
- §5 Error Code Catalogue: 2-column table, 44 rows = all 44 scaffold error entries

**Coverage self-audit**
- Contract 1 (field names): 126 required identifiers (entity fields + endpoint inputs incl. `?`-optionals + output-shape keys) — 111 present as inline backticked tokens, 15 path params present inside §4 path templates; 0 missing. PASS.
- Contract 2 (rules): 14 state machines fully rendered with every transition's guard + error_id + side effects (incl. the 4-link funding-withdrawal cascade, 3-link contractor-suspension cascade, re-assessment loop, rework loop); 10 calculations with exact constants (AMI table 5,400,000–10,180,000 cents; 80%/50%/30% tiers; 40/25/30 base points; 1.5/1.25/1.0 multipliers; 0–100 clamp; envelope tiers 500,000/2,000,000 cents at 15%/10%/5% with the exact-500,000 boundary; 3.5% delivery fee with pinned per-line rounding; 8%/250,000-cent warranty reserve; 365-day training validity; 62-year older-adult threshold; 12-month warranty; 3-strike suspension); 11 validation priority tiers stated as an ordered list; 2 OCC rules with endpoint + `expected_*_version` + error + 412. PASS (literal-grep spot audit: all sentinel strings present, zero fuzzy words, zero operator-syntax leakage).
- Contract 3 (§3 path purity): 653 backticked tokens scanned between `## 3.` and `## 4.`; 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos. PASS.
- Roles 9/9, state enum values 61/61, error ids 44/44 present in prose.

**Ambiguities resolved in prose**
- The apply endpoint's response shape names `deferred_application_ids`, but the scaffold never defines which applications populate it (apply side effects only mark fitting applications `SELECTED`; skipped candidates stay `CANDIDATE`). I transcribed the response shape verbatim (`applied_count`, `project_ids`, `deferred_application_ids`) without inventing semantics.
- The contractor-suspension cascade says an `EVENT_SCHEDULED` project whose posture drops "can no longer execute until re-ready (posture re-checked at EXECUTED)", but the `LOCKED → EXECUTED` precondition list names no error for that case. I rendered both faithfully — the stated preconditions, plus the cascade's execution-time posture re-check — without inventing an error id.
- Scaffold header comment claims "45 codes" but the `errors[]` block lists exactly 44; §5 renders the 44 actual entries.

Did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory.

**Orchestrator spot-check:** 370 lines confirmed; sentinel constants verified present in some rendering — `2026-09-01T00:00:00Z` ×1, AMI bounds `5,400,000`/`10,180,000`, envelope tiers `500,000`/`2,000,000`, `250,000` reserve cap, `3.5` delivery fee, `365`-day training validity, warranty as "twelve calendar months"/"twelve-month window" (my initial `12-month` grep missed the spelled-out form), `ERR_STALE_VERSION` ×4, `deferred_application_ids` ×1. File tail is a complete table row.

## Step 5a: Generate Test Helpers — 2026-10-01T15:58:00Z

All checks pass. The structure is clean — 70 fixture functions, file terminates correctly, compiles clean, imports clean.

---

## Step 5a complete — test_helpers/ shipped for task_3387

**File list (line counts):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3387_volunteer_home_repair_project_selection_trade_coordination/test_helpers/__init__.py` — 44
- `.../types.py` — 424
- `.../constants.py` — 184
- `.../api_errors.py` — 122
- `.../api_client.py` — 291
- `.../assertions.py` — 356
- `.../factories.py` — 291
- `.../test_users.py` — 75
- `.../fixtures.py` — 860 (70 functions)

**constants.py — every constant with its PRD source:**
- `CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"` — PRD §2.4 line 84 ("the logical clock reads exactly `2026-09-01T00:00:00Z`")
- `AMI_BY_HOUSEHOLD_SIZE = {1: 5400000, 2: 6170000, 3: 6940000, 4: 7710000, 5: 8330000, 6: 8950000, 7: 9560000, 8: 10180000}` — §3.2 line 158
- `INCOME_LIMIT_NUMERATOR = 80` — line 158 ("at most eighty times the area median income ... inclusive")
- `TIER_DEEP_NUMERATOR = 30`, `TIER_LOW_NUMERATOR = 50` — line 160
- `OLDER_ADULT_MIN_AGE = 62` — line 156 ("aged at least 62 — exactly 62 counts")
- `OLDER_ADULT_POINTS = 40`, `VETERAN_POINTS = 25`, `DISABILITY_POINTS = 30` — line 162
- `TIER_DEEP_MULTIPLIER = 1.5`, `TIER_LOW_MULTIPLIER = 1.25`, `TIER_STD_MULTIPLIER = 1.0` — line 162 ("one and a half ... one and a quarter ... exactly one")
- `HAZARD_SEVERITY_POINTS = 10` — line 174 ("ten points per severity level"); `HAZARD_SEVERITY_MAX = 5` — line 172; `SCORE_FLOOR/CEILING = 0/100` — line 162
- `ENVELOPE_TIER1_MAX_CENTS = 500000`, `ENVELOPE_TIER2_MAX_CENTS = 2000000`, rates `0.15/0.10/0.05` — line 182
- `DELIVERY_FEE_RATE = 0.035` — line 240 ("three and a half percent")
- `WARRANTY_RATE = 0.08`, `WARRANTY_CAP_CENTS = 250000` — line 254; `WARRANTY_PERIOD_MONTHS = 12` — line 246
- `TRAINING_VALIDITY_DAYS = 365` — line 198; `CONTRACTOR_STRIKE_LIMIT = 3` — line 228
- `HOUSEHOLD_SIZE_MIN/MAX = 1/8` — line 156; `PAGINATION_DEFAULT/MIN/MAX = 10/1/100` — §2.3 line 78
- Reason literals `CYCLE_SEALED` (line 141), `FUNDING_WITHDRAWN` (line 149), `CONTRACTOR_SUSPENDED` (line 234)
- Derived fixture dates (clock-reachable under the default clock, all PRD-gated fields default to on/after 2026-09-01): `DEFAULT_ASSESSMENT_DATE 2026-09-02`, `DEFAULT_EVENT_DATE 2026-10-10` + event-day clock `2026-10-10T07:00:00Z`, visit window `2026-10-05T08:00→12:00Z` + visit clock, license/insurance `2028-01-01`, waiver `2026-08-01`, training `2026-08-15` plus boundary pair `2025-09-01`(valid)/`2025-08-31`(lapsed), follow-up `2026-11-10`, DOBs `1990-01-01`/`1960-05-05`/`1964-09-01` (exactly-62 boundary). Past-dated values only feed fields the PRD never clock-gates.

**Role-header builders (identity model per PRD §2.1):**
- Entity-backed per-instance builders: `make_homeowner_headers(application_id)`, `make_volunteer_headers(volunteer_id)`, `make_trade_partner_headers(contractor_id)`, `make_sponsor_rep_headers(sponsor_id)` — X-User-ID IS the owning entity's id.
- Opaque builders: `make_platform_admin_headers`, `make_affiliate_staff_headers`, `make_assessor_headers`, `make_anonymous_headers`.
- `TEST_USERS` carries shared constants for the four opaque roles plus explicitly-labelled fallbacks for entity-backed roles (non-ownership tests only). Fixtures thread entity ids through the builders everywhere ownership is gated (waiver PATCH, enrollment, QUOTED/INVOICED, warranty-claim create); distinct owners always get distinct X-User-IDs.

**Factories (one line each):** `create_funding_cycle_payload`, `create_selection_run_payload`, `create_sponsor_payload`, `create_commitment_payload`, `create_application_payload`, `create_assessment_payload`, `scope_item_payload`, `trade_scope_item_payload`, `complete_assessment_payload`, `create_scope_amendment_payload`, `create_event_payload`, `create_volunteer_payload`, `create_enrollment_payload`, `create_contractor_payload`, `create_work_order_payload`, `schedule_work_order_payload`, `inspect_work_order_payload`, `material_line_payload`, `create_material_order_payload`, `create_warranty_claim_payload` — all shapes match PRD §4 verbatim; optional fields omitted unless overridden so server defaults are exercised.

**Fixtures (tiers):** clock (`set_clock`/`reset_clock`); thin re-reads for all 15 entities + scope-item/project listers; application chain (`create_application` → `create_verified_application` → `create_scoped_application` → `create_candidate`, plus `create_application_in_state` walker); selection (`create_selection_run` with OCC version read, `apply_run`, `run_selection`, `setup_selected_project` full chain returning cycle/application/assessment/scope_items/run/apply/project, `amend_scope` with OCC); sponsor money (`create_sponsor`, `create_commitment(receive=)`, `setup_cycle_with_commitments`); trade (`create_contractor`, `create_work_order`, `quote/approve/schedule/inspect/invoice/pay_work_order`, `drive_work_order_to` covering QUOTED…PAID incl. INSPECTION_FAILED rework entry and clock advance for IN_PROGRESS, `setup_project_with_work_order`); volunteers/events (`create_volunteer`, `sign_waiver` self-header, `record_training`, `create_eligible_volunteer`, `create/publish_event`, `enroll_volunteer` self-header, `setup_event_with_team_leader`, `setup_locked_event`, `setup_executed_event` with event-day clock + leader check-in); terminal/warranty (`setup_completed_project`, `setup_warranty_active_project`, `cancel_project`, `create_material_order`, `deliver_material_order` via STAGED, `create_warranty_claim` homeowner-header, `approve/resolve_warranty_claim`). All fixture dates stay clock-legal; clock advances only forward, after past-dated creations.

**Confirmations:**
- `python3 -m compileall` — clean, zero errors.
- Runtime `import test_helpers` — OK; barrel exports resolve; 44 error codes registered with the framework (PRD §5 enumerates exactly 44 rows; the scaffold header's "45" comment is an off-by-one in the source comment, the catalog itself is 44).
- Every `CONSTANTS.*` attribute referenced anywhere in test_helpers/ resolves to a definition in constants.py (referenced set == defined set, audited by grep); module-level aliases cover every name imported by factories/fixtures.
- `validate_created(response)` defaults to explicit `expected_status=201` and `validate_ok(response)` to 200; no hardcoded bare-200 create path exists.
- No module-level caches of server-resident ids; fixtures build everything from scratch per call.
- No test_suite/ created; no pytest run; no server started.

**Orchestrator verification:** 9 files at reported line counts (2647 total); `compileall` clean; `import test_helpers` OK; key constants grep-verified in constants.py (clock default, AMI dict, envelope tiers 500_000/2_000_000, fee 0.035, warranty 0.08/250_000/12, training 365, age 62, strikes 3) — all match PRD renderings spot-checked in Step 4.

## Step 5b: Generate Test Suite — 2026-10-01T16:48:00Z

Step 5b complete. Summary for the worklog:

**test_suite/ files (11 files, 3344 lines, 86 tests):**
- `test_suite/conftest.py` — 38 lines, 0 tests (api + 4 opaque-role header fixtures)
- `test_suite/test_01_scoring_verification.py` — 332 lines, 9 tests
- `test_suite/test_02_selection_envelopes_waterfall.py` — 351 lines, 8 tests
- `test_suite/test_03_cycle_admin_occ.py` — 318 lines, 9 tests
- `test_suite/test_04_ledger_and_materials.py` — 392 lines, 8 tests
- `test_suite/test_05_work_order_commercial.py` — 402 lines, 10 tests
- `test_suite/test_06_scheduling_and_locking.py` — 329 lines, 8 tests
- `test_suite/test_07_events_enrollments.py` — 356 lines, 11 tests
- `test_suite/test_08_volunteers_warranty.py` — 339 lines, 9 tests
- `test_suite/test_09_rbac_and_baseline.py` — 382 lines, 12 tests
- `test_suite/test_10_cost_reconciliation.py` — 102 lines, 2 tests

**Totals:** 86 tests = 40 queue A (§1.8: 20 instances × exactly 2 tests each) + 46 queue B (§1.9: 46 non-stub instances × 1 test each).

**Skipped instances:** none — all 66 non-stub instances passed the PRD-first two-condition filter.

**Adjudication notes (two index-vs-PRD friction points, resolved in favor of PRD):**
1. `Corner/rbac/homeowner_can_withdraw_own_application_but_not_others`: the recipe's success leg had the homeowner withdrawing from SUBMITTED, contradicting PRD §3.2 ("A SUBMITTED application may be withdrawn by staff"; homeowner withdrawal is licensed only from UNDER_VERIFICATION/VERIFIED/CANDIDATE/DEFERRED). The emitted test moves the own-withdrawal leg to UNDER_VERIFICATION; the ERR_NOT_RESOURCE_OWNER denial leg (the instance's distinguishing aspect) is unchanged.
2. Creation-shape instances (`funding_cycle_create_applies_defaults_and_system_fields`, `sponsor_create_extra_field_ignored_input`): version==1-at-creation is never pinned by PRD §2.5, so the tests assert server-minted UUID id + integer version ≥ 1 + the documented status/default/ledger values, not the literal initial version.

**Additive helper changes:** none — test_helpers/ untouched (frozen).

**AST tag audit (real `ast` parse of docstrings vs `yaml.safe_load` of both indices):** emitted-with-tag 86 tests covering 66/66 instances; missing 0; orphans 0; cardinality violations 0 (every Difficulty tag on exactly 2 tests, every Corner tag on exactly 1; the 8 `excluded_because:` corner stubs correctly untranslated, all cross-references resolve).

**Verbatim-citation pass:** every docstring's PRD §-quoted span was checked as a whitespace-normalized substring of PRD.md — all verbatim (3 extractor false-positives confirmed verbatim by direct grep).

**pytest --collect-only:** `86 tests collected`, zero import/collection errors (run with `API_BASE_URL=http://127.0.0.1:1`; no server started, tests not executed).

**Orchestrator verification:** re-ran `pytest --collect-only` myself — 86 collected, 0 errors; independent tag extraction confirms exactly 86 Design tags with cardinality 46×1 (Corner) + 20×2 (Difficulty). Helpers untouched (mtime/line-count spot check consistent with Step 5a state).

## Step 6: Generate Implementation — 2026-10-01T17:45:00Z

Implementation complete. Exit summary:

## File list (line counts) — module-per-domain map

```
implementation/
├── start.sh                  (9)    guarded pip install + exec, PORT env, 0.0.0.0
├── requirements.txt          (1)    flask>=3.0
├── app.py                    (61)   app factory, blueprint registration, error handlers
├── db.py                     (61)   in-memory stores (dicts), logical clock, id/seq/record factory
├── errors.py                 (74)   ApiError + all 44 error-id constants
├── helpers.py                (276)  envelope (meta/response_type/data), auth tiers 1-2, body+field validators, ISO-8601 parsing, pagination
├── logic.py                  (307)  calculations: income tiers, priority score, envelope, material totals, ledger, posture, eligibility, warranty reserve
├── cascades.py               (134)  cancel_project, funding-withdrawal 4-link cascade, contractor suspension/termination, event cancel, volunteer deactivation
├── serializers.py            (263)  public dicts; computed fields (ledger, posture, estimates, open_slots, is_eligible) derived fresh on read
├── routes_cycles.py          (242)  funding cycles + selection runs (OCC create, first-fit apply, sponsor waterfall)
├── routes_sponsors.py        (132)  sponsors + commitments (receive/withdraw + cascade)
├── routes_applications.py    (208)  applications (submit, verify, lifecycle, role-shaped withdrawal)
├── routes_assessments.py     (219)  assessments + completion + scope items
├── routes_projects.py        (223)  projects + OCC-guarded scope amendments (201)
├── routes_events.py          (147)  rebuild events (publish/lock/execute/cancel)
├── routes_volunteers.py      (298)  volunteers + enrollments (gauntlet, check-in, re-enroll)
├── routes_contractors.py     (79)   contractor registry + discipline
├── routes_work_orders.py     (331)  work orders (commission, quote/approve/schedule/inspect/invoice/pay/cancel)
├── routes_materials.py       (127)  material orders (per-line rounding, fee, funding check)
└── routes_warranty.py        (129)  warranty claims + POST /_clock/set_current_utc
```

## Endpoint coverage
**57/57 implemented.** Verified by enumerating Flask's url_map (57 non-static rules) and diffing against PRD §4's table — exact method+path match, including `POST /_clock/set_current_utc` outside the `/rebuild` prefix.

## Verification
- `python3 -m compileall -q .` → clean; `python3 -c "import app"` → clean (all cross-module imports resolve).
- Self-smoke-test (dynamic ports, `kill $SERVER_PID` each time; two stray PIDs from my own launches were identified by cwd+port and killed; other pipelines' servers untouched):
  - Cycle create 201 (envelope + ledger zeroed), read-back 200, clock advance 200 → `{current_utc}`, missing headers 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, unknown id 404 `ERR_FUNDING_CYCLE_NOT_FOUND`, Anonymous-on-Any-GET 403 `ERR_FORBIDDEN`, stale OCC 412 `ERR_STALE_VERSION`.
  - Full pipeline: application → verify (score 65 = (40+25)×1.0 STD tier) → assess → complete → scoped → candidate → run (OCC) → apply → project PLANNING/BLOCKED, envelope 550001 (est 500001 hits the 10% band — boundary exactly at 500000 verified), reserve ledger correct.
  - Work orders: permit gate 422 `ERR_PERMIT_REQUIRED`, quote/approve/schedule 200s, posture promotion PLANNING→READY on schedule; half-open adjacency 200, true overlap 409 `ERR_TRADE_WINDOW_CONFLICT`, day capacity 409 `ERR_CONTRACTOR_DAY_CAPACITY`, next-day 200.
  - Events: lock 200 (team-leader + READY posture), check-in wrong day 409, execute-early 409, team-leader self check-in 200, execute 200 → items COMPLETED, project IN_BUILD.
  - Completion → warranty: completed_on/warranty_valid_until (+12 months), claim-early 409 `ERR_PROJECT_NOT_COMPLETED`, payout-over-reserve 402 `ERR_WARRANTY_CAP_EXCEEDED`, payout == reserve 200 (inclusive boundary), resolve 200 (spent += payout), close after window 200.
  - Sponsor waterfall: base budget consumed first, commitment partially allocated (344000 of 1000000 → ALLOCATED); RECEIVED withdrawal → 4-link cascade cancelled the project (`FUNDING_WITHDRAWN`), application DEFERRED, ledger invariant restored (pool 1000 / reserved 0 / spent 0 / available 1000).
  - Material rounding pinned per-line: 3 × $0.335 → 101 cents, fee round(101×0.035)=4, total 105.
  - Materials per-line rounding, first-fit skip (smaller envelope funded, larger deferred-listed), priority score clamp at 100 (DEEP tier 70×1.5=105→100).

## Interpretations chosen (PRD ambiguities resolved without peeking at tests)
1. **Entity versioning starts at 1** on creation; OCC `expected_*_version` compares against that.
2. **created_at/updated_at are wall-clock** (3-fractional-digit Z); logical clock governs only date-sensitive *rules* and stamps (`received_at`, `withdrawn_at`, `completed_on`, `inspected_on`, `submitted_on`, `applied_at` use the clock string).
3. **warranty_valid_until** preserves the clock stamp's datetime style (e.g. `2027-10-10T00:00:00Z`); window comparisons are date-based, inclusive of the anniversary.
4. **Ledger fields (pool/reserved/spent/available) are computed on read**, never stored — the §2.6 invariant holds by construction; cycle `version` bumps only on its three PATCH transitions, run create, and apply (stored-field mutations), not on derived-field movements.
5. **Event lock** advances the project PLANNING→EVENT_SCHEDULED as well as READY→EVENT_SCHEDULED (a pure-volunteer project can have posture READY while still in PLANNING, since §2.8 lists promotion triggers only in §3.5/3.7/3.8, not at selection).
6. **Event execute re-checks posture** (PRD §3.6 prose) with `ERR_INVALID_STATE` (409) when BLOCKED — the scaffold's EXECUTED preconditions omit the error id.
7. **Apply skips ranked applications no longer CANDIDATE** and lists them in `deferred_application_ids` along with not-fitting ones; skipped apps stay CANDIDATE.
8. **Role-field splits enforced both ways** on work orders: staff attempting QUOTED/INVOICED → `ERR_FORBIDDEN`; TradePartner attempting staff transitions → `ERR_FORBIDDEN`. Similarly, staff setting `waiver_signed_on` → `ERR_FORBIDDEN`; Volunteer setting training/status → `ERR_FORBIDDEN`.
9. **Homeowner withdrawing a SUBMITTED application → `ERR_FORBIDDEN`** (PRD 3.2 allows SUBMITTED withdrawal "by staff" only).
10. **Ownership-vs-existence ordering**: compared by string when possible without loading (Homeowner/Volunteer path ids, SponsorRep body `sponsor_id` → `ERR_NOT_RESOURCE_OWNER` before 404); resource-mediated ownership (work orders, enrollments, warranty claims) loads first → 404 then `ERR_NOT_RESOURCE_OWNER`.
11. **Body FK existence follows the §2.11 canonical order** (funding_cycle_id, application_id, project_id, event_id, volunteer_id, contractor_id, sponsor_id, scope_item_ids).
12. **Drop/restore ids of a different assessment → `ERR_SCOPE_ITEM_NOT_FOUND`**; work-order items of a foreign assessment → `ERR_INVALID_STATE`.
13. **Work-order coverage for droppability excludes PAID** ("non-terminal"), but coverage for re-commissioning excludes only CANCELLED (PRD 3.7's literal "not CANCELLED") — the asymmetry is per the text.
14. **Project-cascade WO cancellation_reason = "PROJECT_CANCELLED"** (unspecified literal); application `decision_reason` mirrors the project reason (`FUNDING_WITHDRAWN`/`STAFF_DECISION`).
15. **`decision_reason` optional** on staff REJECTED/DEFERRED (stored when given); cleared to null on CANDIDATE restoration ("null otherwise").
16. **ERR_INVALID_REQUEST placement**: raised at the tier where the malformed field is first consumed (after existence/OCC/state for most endpoints), since PRD §2.10 doesn't tier it.
17. **`Any` accepted as a presented role** (it's in the declared nine) but authorizes only Any-endpoints; Anonymous excluded from Any.
18. **fiscal_year not range-checked** beyond integer ("four-digit" read as descriptive); `accessibility_needs_count` must be int ≥ 0; required strings must be non-empty.
19. **Duplicate enrollment in the SAME event is not blocked** — the double-booking rule covers only "another event" sharing the date; no invented guard.
20. **Re-enrollment skips team-leader re-checks** per PRD's explicit re-run list (event PUBLISHED, eligibility, capacity, double-booking, ownership).
21. **Amendment = exactly one version increment** even when it also flips PLANNING↔READY (sync_posture touch=False where the caller bumps).
22. **Team-leader check-in authorization** requires the leader's enrollment to be active (ENROLLED/CONFIRMED/CHECKED_IN).

## Compliance confirmations
- No reads of SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, or test_helpers/ — not opened, not listed, not grepped. No pytest run.
- In-memory dict storage only; no SQLite, no file persistence, no /tmp state; zero seeded entities — every boot starts empty (verified across 7 fresh launches).
- Only PRD-stated guards implemented; no extra state gates or role restrictions beyond the interpretations listed above.

**Orchestrator verification:** re-ran compileall (clean), real `import app` (clean), url_map count = 57 routes; grep across implementation for `test_suite|test_helpers|SCAFFOLD_DIFFICULTY|SCAFFOLD_CORNER` → 0 hits. 3321 total lines across 18 .py + start.sh + requirements.txt.

## Step 7: Run Tests and Iterate — 2026-10-01T18:30:00Z

Clean 8-round sweep achieved. Summary:

## Summary

**Iterations run:** 3 sweeps (86 tests × 8 rounds each) + targeted smoke runs.

**Preliminary checks:**
- (a) `test_helpers/constants.py` vs PRD.md: **all constants matched** verbatim (AMI table, 80%/30%/50% income tiers, 62/40/25/30 scoring, 1.5/1.25/1.0 multipliers, 10-pt hazard bonus, 0–100 clamp, envelope tiers 500k/2M at 15%/10%/5%, 3.5% delivery fee, 8%/250k warranty, 365-day training, 3-strike suspension, pagination 10/1/100/0, clock 2026-09-01T00:00:00Z). No fixes needed.
- (b) Worklog Step 6's 22 interpretations read and held as candidate over-guards — none were implicated by any failure.
- (c) All fixture dates verified clock-reachable from 2026-09-01.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`** (`fixtures.py`, 3 fixes, one root cause): fixtures forwarded explicit `None` defaults into factories whose `overrides.pop(key, default)` only fires on absent keys, shipping `"name": None` / `"description": None` for PRD-required non-empty strings and breaking 81/86 setups with `ERR_INVALID_REQUEST`. Fixed `create_cycle` (cycle `name`), `create_event` (event `name`), and `create_warranty_claim` (`description`) to omit the key when the caller leaves it None, letting the factory's `_unique()` default apply. Verified no test probes validation by passing None (they use `del payload[field]`), so the fix masks nothing.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`** (one bug, 3 files): `provisional_estimate_cents` was live-recomputed in the serializer as the sum over *currently* `INCLUDED` items, so a trade item's midpoint silently dropped out once a passed inspection moved it to `COMPLETED` — failing `test_project_cost_provisional_ignores_invoices` (300000 ≠ 450000). PRD §3.5 pins disjoint recomputation triggers: the provisional figure ("the selection and planning basis… ignores actual invoices") is re-aggregated only by scope amendments ("re-aggregated over the surviving INCLUDED items"), while only the reconciled figure "recomputes on scope-item completion, on invoicing and payment, and on material delivery or return". Fix: store `provisional_estimate_cents` on the project at selection-run apply (`routes_cycles.py`), re-aggregate it in the amendment path (`routes_projects.py`), and serialize the stored figure (`serializers.py`, with live-compute fallback for safety).

**Sibling unasserted paths for Step 8:** (1) the amendment re-aggregation at `routes_projects.py:202` computes over `INCLUDED` survivors only — a trade item already `COMPLETED` by inspection while the project is still `READY` would drop out of a later amendment's provisional re-aggregation; this matches PRD §3.5's literal "surviving INCLUDED items" but is untested. (2) `logic.py:provisional_estimate` remains as the serializer fallback for records lacking the stored field — unreachable on the apply-only creation path, no test pins the fallback. (3) Interpretation #5 (event lock also advances `PLANNING`→`EVENT_SCHEDULED` for pure-volunteer projects whose posture is READY while still in PLANNING) is exercised only through helper-driven flows; no negative test pins the PLANNING-with-READY-posture lock path.

**Final sweep evidence:** all 8 rounds `86/86` passed (rounds 1–8); all eight `results.1.json` … `results.8.json` files remain on disk in `/home/ubuntu/github/CodingPRD/tasks/task_3387_volunteer_home_repair_project_selection_trade_coordination/workspace/implementation/` (verified by `ls`, ~26 KB each, dated Oct 1 18:24).

**Orchestrator verification:** independently parsed all 8 `results.*.json` — every round `passed=86 total=86 failed=0`. Newest source mtimes: implementation `serializers.py` @1790878907 < results.1.json @1790879085; test_helpers `fixtures.py` @1790878572; test_suite untouched since generation. No post-sweep source writes — the clean sweep is current and valid.

## Step 8: Finalize PRD — 2026-10-01T18:45:00Z

Done. All three edits are in place, the diff is exactly those three changes, and nothing outside `PRD_FINALIZED.md` was written.

## Summary

**Line counts / delta:** `PRD.md` 370 lines → `PRD_FINALIZED.md` 372 lines (+2, +0.54%).

**Changes (one bullet each):**
- §2.2 (after error-envelope bullets) — **insert** — new paragraph pinning that every required free-text string field must be a non-empty string (missing/non-string/empty → `ERR_INVALID_REQUEST` 400), enumerating the enforced set (cycle `name`; sponsor `name`, `contact_email`; application `homeowner_name`, `address`; volunteer `full_name`, `email`; event `name`; contractor `legal_name`, `license_number`; material-line `item_name`; warranty-claim `description`), with scope-item `description` explicitly carved out as emptiable — `helpers.py:110-114` (`req_str`), `routes_materials.py:43-46`, `routes_assessments.py:57-59`.
- §3.5 (second paragraph, first sentence) — **revise** — the provisional estimate is now pinned as a figure *stored* on the project: fixed at selection-run apply, re-aggregated only by scope amendments over the post-amendment `INCLUDED` set (already-`COMPLETED` items contribute nothing), never moved by completion/invoicing/payment/delivery/return — `routes_cycles.py:196-209`, `routes_projects.py:199-220`, `serializers.py:137-141`, `logic.py:207-209`.
- §3.6 (event locking) — **revise** — on lock the host project advances to `EVENT_SCHEDULED` from `READY` *or* directly from `PLANNING` when the lock's posture proof finds it `READY`; an already-`EVENT_SCHEDULED` host is unchanged — `routes_events.py:100-111`.

**Per-edit pre-edit search log:**

1. **Non-empty required strings**
   - (a) Subject: required string field validation shape.
   - (b) Enumerated: `grep req_str(` across all routes (11 sites: `routes_cycles.py:28`, `routes_sponsors.py:28-29`, `routes_applications.py:52,60`, `routes_volunteers.py:41-42`, `routes_events.py:45`, `routes_contractors.py:31,33`, `routes_warranty.py:37`); inline string checks (`routes_materials.py:43-46` item_name rejects `""`; `routes_assessments.py:57-59` scope-item description isinstance-only, empty allowed; `routes_applications.py:173-188` decision_reason optional, empty allowed); optional strings via `opt_str` (`routes_warranty.py:105-113`, `routes_work_orders.py:267,323`, `routes_materials.py:34`); enum/date/bool/int validators in `helpers.py:117-227`; ID presence-only checks (`routes_sponsors.py:47-62`, `routes_events.py:29-31`).
   - (c) Wording adjustment: rejected a blanket "all required strings must be non-empty" claim (false for scope-item `description`); switched to an enumerated field list plus an explicit carve-out sentence, and made no claim about optional strings or ID fields.

2. **Stored provisional estimate**
   - (a) Subject: `provisional_estimate_cents` lifecycle (writers, readers, recompute triggers).
   - (b) Enumerated: `grep -rn provisional` → `routes_cycles.py:202` (stored at apply, sole project-creation path — confirmed via `grep new_record("projects"`), `routes_projects.py:199-221` (amendment re-aggregation over `INCLUDED` survivors + restored + adds), `logic.py:207-209` (live-compute fallback), `serializers.py:139-141` (stored-first read); verified invoice/payment path (`routes_work_orders.py:258-314`) and completion path (`routes_projects.py:54-77`) never write it; cross-checked §3.4 envelope-freeze wording and §4 "computed … estimate" table blurb for conflicts (none — left verbatim).
   - (c) Wording adjustment: phrased the re-aggregation as "over the items `INCLUDED` once the amendment's adds, drops, and restores have applied" rather than repeating §3.5 ¶1's narrower "surviving `INCLUDED` items", so restored/added items aren't excluded; added the COMPLETED-dropout clarification (Step 7 sibling path 1) inside the same sentence instead of a separate claim.

3. **Event-lock project advance**
   - (a) Subject: project status transitions into/out of `EVENT_SCHEDULED`.
   - (b) Enumerated: `grep -n EVENT_SCHEDULED *.py` → lock advance (`routes_events.py:100-111`, the Step 7 sibling-3 site), execute advance (`routes_events.py:136-138`), work-commence advance (`routes_work_orders.py:285`), event-cancel return (`cascades.py:28-33`), suspension cascade (`cascades.py:94-116` + `logic.py:246-259`, which never moves `EVENT_SCHEDULED`), host gates (`routes_events.py:33`, `routes_materials.py:29`), project-cancel gate (`routes_projects.py:96`); confirmed apply (`routes_cycles.py:196-209`) never calls `sync_posture`, so a pure-volunteer project genuinely sits in `PLANNING` with `READY` posture until lock.
   - (c) Wording adjustment: added the trailing clause "a host project already in `EVENT_SCHEDULED` stays there" so the from-state list (`READY`/`PLANNING`) can't be read as rejecting a second event's lock on an already-scheduled host; anchored the `PLANNING` advance to the lock's own posture proof so it can't be read as weakening the `ERR_EVENT_NOT_LOCKABLE` gate.

**Sibling paths from the diff:** (1) and (3) pinned via edits 2 and 3; (2) (`logic.py:provisional_estimate` serializer fallback) is an unreachable internal detail with no PRD-observable behavior — deliberately not pinned.

**Confirmation:** no files outside `/home/ubuntu/github/CodingPRD/tasks/task_3387_volunteer_home_repair_project_selection_trade_coordination/workspace/PRD_FINALIZED.md` were created or modified — `implementation/`, `test_suite/`, and `test_helpers/` were read only.

**Orchestrator verification:** PRD.md 370 → PRD_FINALIZED.md 372 lines; diff is exactly 6 +/- lines (the 3 reported edits); frozen-tree source mtimes unchanged since the clean sweep (serializers.py @1790878907, fixtures.py @1790878572, test_09 @1790874472) — sweep validity intact.

## Step 9: Complete PRD — 2026-10-01T19:20:00Z

Done. `PRD_COMPLETED.md` is written and verified.

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_3387_volunteer_home_repair_project_selection_trade_coordination/workspace/PRD_COMPLETED.md`

**Size delta**: PRD_FINALIZED.md 372 lines / 62,126 chars → PRD_COMPLETED.md 374 lines / 67,208 chars (+2 lines, +5,082 chars).

**Counts**: 30 edit hunks (29 in-paragraph revisions + 1 pure paragraph insertion) = **24 ambiguity-pins** + **6 mismatch-revisions**. Round-8 sweep was 86/86 passing; nothing under implementation/, test_suite/, or test_helpers/ was touched.

### Changes (section — insert|revise — class — what — impl ref)

1. §2.1 — insert — mismatch — Homeowner chain-ownership on warranty claims fires only at claim creation; claim reads are `Any`-authorized with no ownership check — `routes_warranty.py:55-72`
2. §2.1 — insert — ambiguity — presenting literal role `Any` authorizes `Any`-listed endpoints (and only those) — `helpers.py:83-89`
3. §2.1 — insert — ambiguity — other TradePartner targets, and staff `QUOTED`/`INVOICED` attempts, are `ERR_FORBIDDEN` — `routes_work_orders.py:238-248`
4. §2.4 — insert — ambiguity — `to_iso8601` stored/echoed verbatim; date-only/naive values read as UTC — `routes_warranty.py:120-129`
5. §2.5 — revise — ambiguity — `version` starts at 1; `created_at`/`updated_at`/`api_request_timestamp` are wall-clock; logical clock stamps only §3 business dates — `db.py:49-61`, `helpers.py:28-31`
6. §2.6 — insert — ambiguity — ledger figures derived on read; derived-only changes never refresh cycle `updated_at`/`version` — `logic.py:183-204`
7. §2.9 — insert — ambiguity — missing/null/non-integer `expected_*_version` → `ERR_INVALID_REQUEST` (400) — `routes_cycles.py:107-115`, `routes_projects.py:160-168`
8. §2.9 — revise — ambiguity — other endpoints silently ignore stray version/system fields (not rejected, not persisted) — e.g. `routes_sponsors.py:27-32`
9. §2.10 — insert — ambiguity — `ERR_INVALID_REQUEST` has no fixed tier; reported where the field is consumed — `routes_projects.py:160-179`
10. §2.10 — insert — ambiguity — record-keyed ownership (enrollment `volunteer_id`, work-order `contractor_id`, project `application_id`) reports the 404 first; caller-supplied-identifier ownership reports 403 first — `routes_volunteers.py:227`, `routes_work_orders.py:229`, `routes_warranty.py:29-33` vs `routes_applications.py:116-124`
11. §2.11 — revise — ambiguity — body FKs validated in the listed order; `scope_item_ids` in payload order — `routes_work_orders.py:48-70`
12. §3.1 — revise — mismatch — "four-digit `fiscal_year`" → integer with no range check — `routes_cycles.py:29`
13. §3.2 — revise — mismatch — reject `decision_reason` is optional free text (null when omitted) — `routes_applications.py:169-178`
14. §3.2 — revise — mismatch — defer `decision_reason` optional; restoration to CANDIDATE clears it to null — `routes_applications.py:179-200`
15. §3.2 — insert — ambiguity — Homeowner withdrawal outside its set → `ERR_FORBIDDEN`; staff outside its set → `ERR_INVALID_STATE` — `routes_applications.py:132-143`
16. §3.4 — insert — ambiguity — `deferred_application_ids` lists all non-selected ranked apps (insufficient headroom or no longer CANDIDATE); skipping never changes status — `routes_cycles.py:179-216`
17. §3.5 — insert — ambiguity — drop/restore ids must belong to the project's own assessment, else `ERR_SCOPE_ITEM_NOT_FOUND` — `routes_projects.py:152-159`
18. §3.5 — revise — ambiguity — amendment increments project version exactly once even with a posture flip; response carries the updated project — `routes_projects.py:219-224`
19. §3.6 — insert — ambiguity — staff setting `waiver_signed_on` → `ERR_FORBIDDEN` — `routes_volunteers.py:83-86`
20. §3.6 — revise — mismatch — gauntlet order is double-booking before capacity (per §2.10); same-event duplicate enrollment permitted, consumes a slot — `routes_volunteers.py:136-161`
21. §3.6 — insert — ambiguity — team-leader check-in requires a still-active team-leader enrollment; Volunteer `NO_SHOW` → `ERR_FORBIDDEN` — `routes_volunteers.py:217-249`
22. §3.6 — insert — ambiguity — execution-time posture failure → `ERR_INVALID_STATE` — `routes_events.py:118-123`
23. §3.6 — insert — ambiguity — re-enrollment skips team-leader checks, keeps original `is_team_leader` — `routes_volunteers.py:259-279`
24. §3.7 — insert — ambiguity — `max_concurrent_jobs` below 1 → `ERR_INVALID_REQUEST` — `routes_contractors.py:29`
25. §3.7 — revise — ambiguity — `scope_item_ids` must be non-empty; foreign-assessment item → `ERR_INVALID_STATE`; checks fire in §2.10 tier order — `routes_work_orders.py:57-80`
26. §3.7 — revise — mismatch — scheduling order: parse → credentials → window shape → overlap → day capacity (PRD had window-shape first) — `routes_work_orders.py:146-178`
27. §3.7 — insert — ambiguity — staff PATCH to `QUOTE_REQUESTED`/`INSPECTION_FAILED`/`INSPECTED` is a 200 no-op (status unchanged, version still increments) — `routes_work_orders.py:226-331` fall-through
28. §3.7 — insert — ambiguity — termination cascade also records `CONTRACTOR_SUSPENDED` — `cascades.py:119-122`
29. §3.9 — revise — ambiguity — `warranty_valid_until` preserves the datetime style of the completion stamp — `routes_projects.py:65-70`
30. §3.9 — revise — ambiguity — cascade-cancelled work orders record `PROJECT_CANCELLED`; staff cancellation defaults to `STAFF_DECISION` — `cascades.py:53-57`, `routes_projects.py:100-102`
31. §4 — revise — ambiguity — projects list also filters by `status` — `routes_projects.py:41-43`
32. §5 — insert — ambiguity — undefined route/method → `ERR_INVALID_REQUEST` envelope with 404/405 — `app.py:43-53`

(Items 31/32 share the count above; 30 hunks total since §4 and §5 are single-hunk edits.)

### Final diff check

`diff workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md | head -100` produced 30 hunks (38.7KB — changed lines are long paragraphs, so the raw output exceeded the display cap and was persisted by the harness). Hunk map, verbatim:

```
19c19 21c21 23c23 86c86 90c90 101c101 113c113 132a133,134 135c137 141c143
160c162 166c168 168c170 186c188 190c192 192c194 198c200 206c208 210c212
212c214 214c216 220c222 222c224 226c228 234c236 236c238 248c250 252c254
288c290 325c327
```

Each hunk was individually verified to contain exactly one intended edit (phrase-level grep sweep: 36/36 pins present). **Total changed-line count: 60 diff body lines (29 `<` removed, 31 `>` added); net +2 lines.**

### Confirmation

No files outside `workspace/PRD_COMPLETED.md` were created or modified. Verified by mtime listing of the whole task tree: the only file newer than the pre-session artifacts is `workspace/PRD_COMPLETED.md`; `implementation/`, `test_suite/`, `test_helpers/` are untouched, and no `__pycache__` was created (no server was started; all analysis was static). `SCAFFOLD*.yaml` and `worklog.md` were never read.

**Orchestrator verification:** PRD_COMPLETED.md exists at 374 lines; `diff -q` confirms it differs from PRD_FINALIZED.md (not a silent no-op); diff body is exactly 60 lines as claimed; all 8 `results.*.json` remain on disk; frozen-tree source mtimes unchanged since the clean sweep (serializers.py @1790878907, fixtures.py @1790878572, test_09 @1790874472). Pipeline complete — final state: 86/86 tests passing across all 8 stability rounds.
