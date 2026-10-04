# Worklog — task_3492_peer_review_study_sections_percentile_scoring_award

## Step 1: Create Task Directory — 2026-10-02T16:35:00.000Z

Task directory `./tasks/task_3492_peer_review_study_sections_percentile_scoring_award/` was pre-allocated per command args; verified it exists with `workspace/` inside. No new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-02T18:25:15.000Z

Generated SCAFFOLD.yaml (14 entities, 52 endpoints, 73 errors, 10 state machines, 8 calculations, 20 validations, 7 roles, 2 OCC concurrency rules), SCAFFOLD_DIFFICULTY_DESIGN.yaml (19 instances: all 9 rules at >= 2, combinatorial_formula covers modes a+b+c), SCAFFOLD_CORNER_DESIGN.yaml (48 active instances + 3 exclusion stubs across 9 sections). scaffold_lint.py verdict: clean (1296 calls scanned, all FKs reverse-reachable). All formula-derived assert literals executed and pinned (percentiles, budget per-year rounding, payline walk, transfer proration, carryover 25% boundary).

## Step 3: Copy Shared Files — 2026-10-02T18:26:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T18:55:00.000Z

  The PRD is complete and all verification passes. Final summary:

  ## Task Complete

  **Generated**: `/home/ubuntu/github/CodingPRD/tasks/task_3492_peer_review_study_sections_percentile_scoring_award/workspace/PRD.md` (382 lines) from `SCAFFOLD.yaml`. The two DESIGN files were not opened, grepped, or referenced.

  **Structure** (domain-derived, not example-cloned):
  - §1: two-paragraph introduction from the NIH peer-review scenario
  - §2 (9 subsections): 2.1 RBAC with per-role identity translations (entity-backed `Applicant`/`Reviewer` vs opaque officers, `recorded_by` recording, `ERR_MODIFICATION_TYPE_ROLE_MISMATCH` split); 2.2 verbatim response envelope (byte-identical to canonical source — verified by diff); 2.3 pagination (limit 10/1–100, offset 0, `created_at` ascending, `ERR_INVALID_PAGINATION_PARAMETERS`); 2.4 logical clock (default 2026-09-01T00:00:00Z, monotonic, `to_iso8601`/`current_utc`, unprefixed `/_clock/set_current_utc` mount, lazy expiry, two-family timestamp rendering); 2.5 common properties + integer-cents/half-up precision; 2.6 OCC (exactly two versioned endpoints); 2.7 the full 20-stage ordered validation pipeline; 2.8 institute ledger and commitment authority
  - §3 (9 subsections): announcements/drafting → submission/withdrawal cascade → referral + honor rule + re-referral → recruitment/COI/capacity/proximity → meeting/impact/raw-vs-normalized percentiles → council review → payline walk + select pay → JIT + award budget build → reports/carryover/NCE/termination/transfer. No paths or HTTP methods anywhere in §3; endpoints named via state pairs and role+verb
  - §4: 52-row, 4-column endpoint table (exact path-set match with scaffold, clock endpoint unprefixed); §5: 73-row, 2-column error catalogue

  **Hard Contract Reports**

  ```
  Field coverage check:
  - entities[].fields: 92 required, 92 present, 0 missing
  - endpoints[].request_body/input: 76 required, 76 present, 0 missing
  - endpoints[].query_params: 15 required, 15 present, 0 missing
  Status: PASS
  ```

  ```
  Rule coverage check:
  - validations[] with priority: 20 checked, 20 expressed as the ordered §2.7 pipeline, 0 missing
  - concurrency_rules[] OCC rejections: 2 checked, 2 expressed (referral→expected_application_version→ERR_STALE_APPLICATION_VERSION/412; payline-decisions→expected_institute_version→ERR_STALE_INSTITUTE_VERSION/412), 0 missing
  - state_machines[].transitions: 10 machines (incl. REFERRED→REFERRED supersede, quorum loop UNDER_REVIEW↔REFERRED, JIT expiry from all three open states, transfer cascade), all expressed, 0 missing
  - calculations[]: 8 checked, 8 fully expressed in precise prose (no pseudocode, no fuzzy words — mechanically scanned), 0 missing
  - validations[] conditions: 20 checked, 20 matchable to error_ids in §2.7/§3 prose, 0 missing
  - endpoints[].side_effects / applies_to: 52 checked; cascades (withdraw L1/L2/L3, decline quorum, release-scores normalized-pool reconciliation, payline JIT fan-out, transfer three-level) all stated, 0 missing
  - entities[].fields[] structured content: defaults, nulls, derived arrays, computed flags (auto_approved, submitted_late, proration_variant) all reconstructible from prose, 0 missing
  - sibling-branch symmetry: FUND/DEFER/NOT_FUND, ACCEPT/DECLINE/RETURN, APPROVE/DENY, TIME_PRORATED/LEDGER_ACTUALS, raw/normalized variants, three JIT expiry sources — all equally specified, 0 asymmetric
  Status: PASS
  ```

  ```
  Path purity check (§3 only):
  - backtick tokens scanned: 584
  - tokens starting with `/`: 0
  - bare HTTP-method tokens: 0
  - method+path combined tokens: 0
  Status: PASS
  ```

  Additional checks: all 73 error ids and all 64 state/enum value tokens appear in backticks in §2/§3; all 7 role names exact; §2.2 confirmed byte-identical to the canonical block; §5 row count (73) matches the scaffold error catalog exactly.

### Verbatim Step 2 subagent report

  Scaffold generation complete. All three artifacts are written and lint-clean.

  ## Deliverables

  All under `/home/ubuntu/github/CodingPRD/tasks/task_3492_peer_review_study_sections_percentile_scoring_award/`:

  - **SCAFFOLD.yaml** (96 KB) — §1.0–§1.7 only: 14 entities, 52 endpoints, 73 errors, 10 state machines, 8 calculations, 20 ordered validations, 7 roles (segregation-of-duties model; Applicant/Reviewer entity-backed), 2 OCC concurrency rules (`referral-stale-application-version`, `payline-stale-institute-version`), logical clock endpoint with the mandated `2026-09-01T00:00:00Z` startup default. No design keys inside this file.
  - **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (136 KB) — 19 instances, all nine §0.5 rules at ≥2 (combinatorial_formula has 3, covering modes (a) weighted scoring with quorum gate, (b) per-year-then-sum rounding pinned to the cent, (c) circular-looking payline budget walk with pinned evaluation order).
  - **SCAFFOLD_CORNER_DESIGN.yaml** (244 KB) — 48 active instances + 3 `excluded_because` stubs across the nine taxonomy sections.

  ## Key design decisions (hardness drivers)

  - **Dual percentile variants**: within-section raw vs cross-panel normalized (section-mean adjustment over the activity-code pool); payline uses normalized, select-pay band uses raw — the divergence trap is explicitly tested (a2 raw 75.0 selectable where normalized 83.3 would be rejected).
  - **Pinned arithmetic**: award budget rounds per component per year before summing (92999999 vs 93000000 contrast); payline walk funds candidate 3 at cumulative == committable exactly (`<=` boundary), stops without skipping.
  - **Transfer relinquishment variants**: TIME_PRORATED (15123288 for the pinned dates) vs LEDGER_ACTUALS (18000000), selected on `disbursed_cents > 0`.
  - **Cyclic machines on different entities**: Application REFERRED↔UNDER_REVIEW quorum loop; JitRequest ISSUED→SUBMITTED→RETURNED→SUBMITTED.
  - **Invariants**: institute ledger conservation across issue/disburse/terminate; transfer lineage conservation (total == disbursed + retained + successor).

  ## Issues caught and fixed during self-audit

  - YAML flow-sequence breakers: `$.data[0].id` captures and `grounds: [errors[...]]` nested brackets (quoted / converted to block style).
  - Two dead rules removed before shipping: `ERR_PRIOR_REPORT_OUTSTANDING` (unreachable — period advancement implies acceptance) and the award-issuance commitment check (provably unreachable after walk/select-pay pre-gates); difficulty instance 11 rewritten as a genuinely dual-violating state-vs-fiscal pair on select-pay.
  - Meeting-proximity rule initially self-blocked same-section co-review (0-day difference); added the same-section exemption.
  - Carryover `unobligated` double-subtracted `carried_out`; fixed formula (audit-only array).
  - Corner `re_referral_with_live_assignment_rejected` replays to the wrong error from UNDER_REVIEW (state gate would mask the constraint); restructured to reach REFERRED-with-one-live-assignment via the decline quorum flip.
  - Two date literals corrected by executing the date math (grace windows close 2028-03-31 / 2029-03-31 under the 365-day-period convention).
  - Path params renamed to `{id}` so the linter's sub-resource FK-reverse check matches.

  ## Verification

  `scaffold_lint.py` verdict block (final run, pasted verbatim):

  ```
  VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  ```

  (1296 calls scanned across 19 §1.8 + 48 §1.9 instances.) Additional audits all clean: placeholder closure, grounds resolvability, unique names, role/endpoint consistency, error-catalog completeness (all 73 errors referenced and triggerable), enum closure, forbidden-vocabulary scan, OCC contract (both endpoints take `expected_*_version` and bump parent version), and every formula-derived assert literal re-executed in Python (impacts, percentiles, budget rounding, payline walk, proration, carryover 25% boundary, date arithmetic).

## Step 5a: Generate Test Helpers — 2026-10-02T19:30:00.000Z

  All checks pass. Here is the complete Step 5a report.

  ## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3492_peer_review_study_sections_percentile_scoring_award/test_helpers/`)

  | File | Lines | Content |
  |---|---|---|
  | `__init__.py` | 42 | Barrel export; `api_client` re-exported as the **module** (never an instance) |
  | `types.py` | 382 | 7 role/field enums + 13 status enums + decision enums + 14 entity TypedDicts (all entities carry `id/created_at/updated_at/version` — all are `common_fields: true`) |
  | `api_client.py` | 418 | `ApiClient(GenericApiClient)` + 51 endpoint methods + identical module-level delegates on an internal `_default_client`; clock endpoint correctly **unprefixed** (`/_clock/set_current_utc`), all others under `/grants` |
  | `api_errors.py` | 188 | `ApiErrorId` (73 ids) + `HTTP_STATUS_CODES` + `set_error_http_status_map(...)` at import |
  | `assertions.py` | 253 | 14 `assert_<entity>()` + `assert_institute_ledger_invariants`, `assert_award_budget_conserved`, `assert_transfer_conservation` |
  | `constants.py` | 132 | 28 PRD-pinned constants, each with its verbatim PRD quote in a comment |
  | `factories.py` | 412 | 24 payload factories + `unique_name/unique_pa_number/unique_email` + canonical scenario date defaults; optional fields omitted via a shared `_UNSET` sentinel |
  | `test_users.py` | 75 | `TEST_USERS` (7 roles), `make_applicant_headers`/`make_reviewer_headers` (entity-backed, mandatory for ownership-gated calls), opaque-role builders, `without_header` |
  | `fixtures.py` | 699 | 65 setup helpers (see below) |

  Verified: `py_compile` on all 9 files, package import with `PYTHONPATH=.`, `import test_helpers.api_client as ac` binds the **module** (`ac.get_application(...)` works), zero callable-name collisions between client module and fixtures/factories (checked programmatically), error map has exactly 73 entries with spot-checked statuses.

  ## Helper API surface for Step 5b

  **Module-level client** (`test_helpers.api_client`, all `(payload|id..., headers)` or `(headers, params=None)`; creates return raw Response): `set_clock`, `create_funding_opportunity`, `get_funding_opportunity`, `close_funding_opportunity`, `create_institute`, `get_institute`, `publish_payline_decision`, `create_institution`, `get_institution`, `create_applicant`, `get_applicant`, `create_application`, `list_applications`, `get_application`, `submit_application`, `withdraw_application`, `refer_application`, `select_pay_application`, `list_council_reviews`, `list_application_jit_requests`, `create_study_section`, `get_study_section`, `convene_study_section`, `release_section_scores`, `create_reviewer`, `list_reviewers`, `get_reviewer`, `reviewer_respond`, `reviewer_declare_conflict`, `create_assignment`, `list_assignments`, `get_assignment`, `assignment_respond`, `submit_critique`, `create_council_review`, `get_jit_request`, `submit_jit_items`, `adjudicate_jit_request`, `issue_award`, `list_awards`, `get_award`, `create_progress_report`, `list_progress_reports`, `accept_progress_report`, `create_award_modification`, `list_award_modifications`, `adjudicate_modification`, `create_transfer_request`, `list_transfer_requests`, `get_transfer_request`, `relinquish_transfer`, `decide_transfer`, plus `ApiClient`, `get_default_client()`, `GRANTS`, `CLOCK_PATH`.

  **fixtures.py** (success-path wrappers; negative triggers call `ac.*` directly):
  - Dates/clock: `add_days_iso(iso, days)`, `iso_days_between(a, b)`, `advance_clock(to_iso8601)`
  - Refreshers (ProgramOfficer read): `refresh_funding_opportunity/institute/institution/applicant/application/study_section/reviewer/assignment/jit_request/award/transfer_request`
  - Makers: `make_institution(name?, human_subjects_certification_expiry?, animal_welfare_assurance_expiry?)`, `make_institute(**ledger_overrides)`, `make_foa(**foa_overrides)`, `close_foa(id)`, `make_applicant(career_stage=..., **o)`, `make_study_section(meeting_date=..., application_quota=10, **o)`, `make_reviewer(institution_id, **o)`, `make_active_reviewer(institution_id, **o)`, `respond_to_invitation(reviewer_id, decision)`, `declare_conflict(reviewer_id, application_id)`
  - Application pipeline: `make_draft_application(foa_id, institution_id, applicant_id, **o)`, `submit_draft_application(app_id, applicant_id)`, `withdraw_own_application(app_id, applicant_id)`, `refer_application_current_version(app_id, section_id, institute_id, expected_application_version=None, override_assignment_request=...)`, `create_submitted_application(...)`, `create_referred_application(...)`
  - Review pipeline: `assign_reviewer(app_id, reviewer_id, role="PRIMARY")`, `respond_to_assignment(asg_id, reviewer_id, decision)`, `create_accepted_assignment(...)`, `convene_section(section_id)`, `file_critique(asg_id, reviewer_id, overall_impact_score=3, significance/innovation/approach/investigator/environment=None)`, `release_scores(section_id)`, `assign_panel(app_id, reviewer_institution_id, reviewers=None)` → `{"assignments":[p,s],"reviewers":[r1,r2]}`, `critique_panel(panel, specs)` (None entry = hold quorum)
  - Funding pipeline: `record_council_review(app_id, recommendation, priority_alignment_score=4-if-FUND, portfolio_balance_note=...)`, `publish_payline(institute_id, base_payline_percentile, expected_institute_version=None)`, `select_pay(app_id, rationale=...)`, `fetch_jit_request(app_id)`, `submit_own_jit_items(jit_id, applicant_id, items_submitted=JIT_BASE_ITEMS)`, `adjudicate_jit(jit_id, decision, budget_cut_pct=..., return_reason=...)`, `award_application(app_id, start_date=DEFAULT_AWARD_START_DATE)`
  - Post-award: `file_progress_report(award_id, applicant_id, period_year, actual_expenditure_cents, publications_count=0)`, `accept_report(report_id)`, `request_modification(award_id, caller_headers, type, amount_cents=, from_period=, new_end_date=, reason=)`, `decide_modification(mod_id, decision, denial_reason=...)`, `propose_transfer(award_id, applicant_id, to_institution_id, effective_date=...)`, `relinquish_transfer_request(tr_id)`, `decide_transfer_request(tr_id, decision, decline_reason=...)`, `fetch_successor_award(tr_id)`
  - Composites: `make_review_context(**o)` → `{institution, reviewer_institution, institute, foa}` (reviewer pool at a second institution, so COI never fires accidentally; cert overrides via `human_subjects_certification_expiry`/`animal_welfare_assurance_expiry`, name via `institution_name`); `add_referred_application(context, section, applicant=None, career_stage=..., **app_o)`; `add_reviewed_application(context, section, critique_specs=None, applicant=None, career_stage=..., convene=True, **app_o)`; `score_section(section, reviewed_apps, critique_specs_list)` → refreshed apps; `setup_scored_application(overall_impact_score=3, approach_score=None, career_stage=..., context=None, context_kwargs=None, **app_o)` → `{context, section, applicant, application, panel}`; `setup_council_reviewed_application(recommendation="FUND", priority_alignment_score=..., **kw)`; `setup_jit_pending_application(base_payline_percentile=100.0, **kw)`; `setup_jit_complete_application(budget_cut_pct=0, items_submitted=..., **kw)`; `setup_active_award(start_date=..., **kw)`; `setup_award_with_accepted_report(actual_expenditure_cents=12_000_000, publications_count=1, period_year=None, **kw)`; `setup_proposed_transfer(to_institution=None, effective_date=..., with_report_cents=..., **kw)`; `setup_relinquished_transfer(**kw)`.

  **factories.py**: `set_clock_payload`, `create_funding_opportunity_payload`, `create_institute_payload`, `create_institution_payload`, `create_applicant_payload`, `create_application_payload` (derives `requested_years` from `direct_cents_per_year` length), `create_study_section_payload`, `create_reviewer_payload`, `reviewer_respond_payload`, `declare_conflict_payload`, `create_assignment_payload`, `assignment_respond_payload`, `critique_payload` (criteria default to overall), `council_review_payload`, `referral_payload`, `payline_decision_payload`, `select_pay_payload`, `jit_submit_items_payload`, `jit_adjudicate_payload`, `award_payload`, `progress_report_payload`, `award_modification_payload`, `modification_adjudicate_payload`, `transfer_request_payload`, `transfer_decide_payload`; dates `DEFAULT_OPEN_DATE=2026-08-01`, `DEFAULT_RECEIPT_DEADLINE=2026-12-01`, `DEFAULT_MEETING_DATE=2027-03-01`, `DEFAULT_AWARD_START_DATE=2027-01-01`, `DEFAULT_TRANSFER_EFFECTIVE_DATE=2027-07-01` (all consistent with the 2026-09-01 clock start: deadline after the clock; start/effective dates on/after the clock; verified `add_days_iso("2027-01-01",3*365)=="2029-12-31"`, `+"90d"→"2028-03-31"` over leap Feb 2028, and 2027-07-01→2028-01-01 = 184 days ⇒ 30000000×184/365 → 15123288, matching the design literals).

  ## Constants audit (each literal → verbatim PRD quote)

  - `CLOCK_START_ISO="2026-09-01T00:00:00Z"` — "the logical clock starts at exactly 2026-09-01T00:00:00Z"
  - `MIN_CRITIQUES_TO_SCORE=2` — "An application with fewer than two submitted critiques becomes UNSCORED"
  - `MIN_LIVE_ASSIGNMENTS=2` — "an application must hold at least two live assignments to remain under review"
  - `PRIMARY_WEIGHT=2`/`SECONDARY_WEIGHT=1` — "a weight of two for a PRIMARY assignment, one for a SECONDARY assignment"
  - `IMPACT_SCORE_MULTIPLIER=10`, `IMPACT_SCORE_MIN=10`, `IMPACT_SCORE_MAX=90` — "multiplied by ten and rounded half up to a whole number, yielding an integer from 10 to 90"
  - `CRITERION_SCORE_MIN/MAX=1/9` — "six integer scores, each from 1 to 9"
  - `PERCENTILE_DECIMALS=1`/`CRITERION_MEAN_DECIMALS=2` — "Percentile values ... exactly one decimal place, and criterion means with exactly two decimal places"
  - `ESI_PAYLINE_BONUS=5.0` — "five percentile points when the applicant's career_stage is EARLY_STAGE_INVESTIGATOR"
  - `EFFECTIVE_PERCENTILE_FLOOR=0.1` — "but never below one-tenth of a percentile point"
  - `JIT_RESPONSE_WINDOW_DAYS=30` — "its due_date thirty days after the request's creation"
  - `BUDGET_CUT_MAX_PCT=0.30`/`BUDGET_CUT_DEFAULT_PCT=0` — "defaulting to zero, and never above 0.30"
  - `JIT_ITEM_*` + `JIT_BASE_ITEMS` — "OTHER_SUPPORT and BUDGET_JUSTIFICATION always, plus IRB_APPROVAL exactly when human_subjects_involved is set, plus IACUC_APPROVAL exactly when vertebrate_animals_involved is set"
  - `AWARD_PERIOD_DAYS=365` — "its end_date falls exactly requested_years times 365 days after the start_date"
  - `TERM_STANDARD/RESTRICTED_DRAW_DOWN/TRANSFERRED_AWARD` — "always contain STANDARD_TERMS_V1, and gain RESTRICTED_DRAW_DOWN exactly when the accepted budget_cut_pct is greater than zero"; "gaining TRANSFERRED_AWARD alongside STANDARD_TERMS_V1"
  - `REPORT_GRACE_DAYS=90` — "the filing window closes ninety days after the current period's end"
  - `NCE_MAX_EXTENSION_DAYS=365` — "must not exceed 365 days beyond the current end_date"
  - `CARRYOVER_AUTO_APPROVE_PCT=0.25` — "at most one quarter of the unobligated balance"
  - `MAX_ACTIVE_ASSIGNMENTS_PER_REVIEWER=4` — "A reviewer may hold at most four active assignments"
  - `MAX_LIVE_ASSIGNMENTS_PER_APPLICATION=3` — "an application may hold at most three live assignments"
  - `MEETING_PROXIMITY_BUFFER_DAYS=7` — "within seven days — inclusive"
  - `MIN/MAX_PROJECT_YEARS=1/5` — "the requested_years project period (one to five years)"
  - `PRIORITY_ALIGNMENT_MIN/MAX=1/5` — "A priority_alignment_score from 1 to 5"
  - `PAGINATION_*` (10/1/100/0) — "defaults to 10, with a minimum of 1 and a maximum of 100 ... defaults to 0 and may not be negative"

  ## Design-index expressibility

  All 19 difficulty + all non-stub corner instances (3 corner stubs excluded by their own `difficulty_instance` pointers, which resolve) are expressible: the four multi-application percentile/payline pools compose `make_review_context` + `make_study_section` + `add_referred_application` + `assign_panel` + `score_section`; the two-award transfer variant instance uses one shared context with two per-applicant pipelines; `context_kwargs` routes institute/FOA config (rate 0.55, appropriation 98M/40M, extension 70.0) through every `setup_*` chain without leaking into the application payload; negative triggers use `ac.*` module functions directly with `make_*_headers`/`without_header`. No instance is inexpressible.

  One note for Step 5b: fixtures are plain functions (not pytest fixtures), so tests call them directly or wrap them in `test_suite/conftest.py`.

## Step 5b: Generate Test Suite — 2026-10-02T20:10:00.000Z

  Step 5b is complete. All verification gates pass.

  ## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3492_peer_review_study_sections_percentile_scoring_award/test_suite/`)

  | File | Tests | Contents |
  |---|---|---|
  | `conftest.py` | — | `api` + per-role header fixtures bridging test_helpers |
  | `test_01_creation_and_defaults.py` | 8 | corner/entities (FOA 201+OPEN, applicant_id-from-header, computed fields null, 404, pa_number/duplicate-application uniqueness, enum validation, reviewer INVITED) |
  | `test_02_submission_and_referral.py` | 9 | 3 difficulty (page-limit boundary, cert-beats-page priority, FOA-open gate) + 6 corner (resubmit, draft-referral, re-referral supersede + live-assignment guard, stale OCC version, ownership) |
  | `test_03_review_assignments.py` | 12 | 4 difficulty (quorum cycle, withdraw cascade, section-recruiting gate, 7-day inclusive proximity) + 8 corner (lockdowns, pre-convene critique, convene/release gates, 3-arm COI, capacity 4/5, score range) |
  | `test_04_scoring_and_percentiles.py` | 4 | 2 difficulty (raw-vs-normalized divergence across panels, weighted roles + quorum gate) + 2 corner (approach-mean tie-break, normalized reconciliation after second release) |
  | `test_05_council_payline_selectpay.py` | 10 | 3 difficulty (walk stops at committable boundary, percentile==payline boundary, state-gate-beats-fiscal-cap) + 7 corner (NOT_FUND lock, DEFER→FUND, ESI bonus, raw-not-normalized band, no-payline-then-band-exceeded, stale institute OCC, applicant payline denial) |
  | `test_06_jit_and_award.py` | 5 | 2 difficulty (JIT ISSUED→SUBMITTED→RETURNED→SUBMITTED→ACCEPTED cycle, per-year rounding-then-sum budget) + 3 corner (adjudicate-before-submit, non-owner JIT submit, immediate issuance response) |
  | `test_07_post_award.py` | 9 | 5 difficulty (time-vs-ledger proration variants, transfer accept cascade, NCE adjoin, institute funds conservation, transfer lineage conservation) + 4 corner (decide-before-relinquish, carryover quarter boundary, report period/window/late flag, applicant TERMINATION denial) |
  | `test_08_api_conventions.py` | 10 | corner conventions (missing header, role-before-existence ×2, body FK 404, not-found sweep ×11, report/modification 404s, list filter+pagination envelope, pagination params, clock regression) |

  **Total: 67 tests (19 difficulty + 48 corner).**

  ## Verification results

  - `PYTHONPATH=. python3 -m pytest test_suite --collect-only -q` → **67 tests collected**, no errors.
  - Real AST audit (python `ast` module): every test function's docstring ends with exactly one `Design:` line as its last line; all 67 tags resolve to real YAML instances; every active instance (19 difficulty + 48 corner) is covered by exactly one test; the 3 stubs (`jit_returned_resubmit_cycle_states`, `error_page_limit_exceeded_on_submit`, `error_foa_not_open_blocks_submit`) are excluded and their `excluded_because` pointers resolve to real difficulty instances. **0 violations.**
  - The audit also grep-checked every ≥8-word docstring quote against PRD.md: **all verbatim**, including backticks/em-dashes.
  - `test_helpers/` untouched (no writes; only read).

  ## Skips
  None — every active instance passed the PRD-first two-condition filter.

  ## Design-literal vs PRD-derivation judgment calls (all derivations confirmed the design numbers; only assertion *form* was adjusted where PRD under-pins)

  1. **Absolute `version` literals** — instances asserting `version == 1/2/3/4` (`foa_create_returns_open_with_server_fields`, `re_referral_supersedes_and_moves_section_count`, `stale_institute_version_on_second_payline`, `payline_budget_walk_stops_at_committable_boundary`, `select_pay_no_payline_then_band_exceeded`): PRD §2.5 pins only "increments by one on every mutation", never the start value. Tests assert the PRD-derivable form instead: `version == captured_version + k` (or `int >= 1` at creation, matching the frozen `_assert_common`). Increment counts and OCC semantics are asserted exactly as designed.
  2. **`required_items` ordering** (`jit_return_resubmit_cycle_to_acceptance`): design asserts an ordered list `[OTHER_SUPPORT, BUDGET_JUSTIFICATION]`; PRD pins membership ("OTHER_SUPPORT and BUDGET_JUSTIFICATION always") not order → asserted set equality.
  3. **Grace-close annotations** (`progress_report_period_window_and_late_flag`): design prose says "grace closing 2028-03-31" / "closed 2029-03-31"; my derivation from PRD ("ninety days after the current period's end") gives 2028-03-31 (2028 leap) and 2029-04-01 respectively. Immaterial to assertions: the recipe's clocks (2028-02-01 within grace, 2029-05-01 past close) are unambiguous under either reading, and the test asserts only those outcomes.
  4. **Re-derived money/percentile literals all match the design exactly**: TIME_PRORATED 15,123,288 (= rhup(30,000,000 × 184/365)), LEDGER_ACTUALS 18,000,000, award periods [30,999,995, 30,999,995, 31,000,009] / total 92,999,999 at rate 0.55, carryover quarters 3,000,000 (auto) vs 2,250,000 (3,000,001 pends), normalized pool values 16.7/50.0/83.3, walk boundary 93,000,000 committable vs 31,000,000/candidate.
  5. **Tag fix found by audit**: `clock_regression_rejected` is indexed under `cross_cutting_layers` (not `consistency_model`) in the YAML — corrected; re-audit clean.

### Orchestrator independent AST re-audit (post-5b)

Re-ran the tag audit from the orchestrator with a correct structural parse of both YAMLs (list-of-sections → instances): tagged=67, untagged=0, unresolvable/stub-pointing=0, difficulty 19/19 covered, corner 48/48 covered, duplicate tags=0. Subagent's coverage claim CONFIRMED.

## Step 6: Generate Implementation — 2026-10-02T21:05:00.000Z

  Double-boot freshness confirmed (identical pa_number recreates cleanly, clock resets to 2026-09-01T00:00:00Z). The implementation is complete and verified. Final state-machine walk: all 10 machines' transitions map to handlers (verified above against §1.2).

  ## Step 6 Summary — task_3492 implementation complete

  **Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3492_peer_review_study_sections_percentile_scoring_award/workspace/implementation/`):

  | File | Lines | Role |
  |---|---|---|
  | start.sh | 10 | guarded pip install, `exec python3 app.py`, `$PORT`/`0.0.0.0`/foreground |
  | requirements.txt | 1 | flask>=3.0 |
  | app.py | 64 | app assembly, blueprint registration, envelope-shaped 404/405/500 handlers |
  | constants.py | 92 | every PRD/scaffold-pinned constant, one definition site each |
  | errors.py | 73 | ApiError + full 73-id catalog with HTTP statuses |
  | db.py | 73 | in-memory STORE (empty at boot, no seeding), logical clock, dashed-UUID ids |
  | util.py | 305 | envelope, pagination, ISO8601 parse/render (two timestamp families), auth, field validators |
  | services.py | 365 | impact/percentile/payline/award-budget/transfer/carryover calculations, derived counters, cascades |
  | serializers.py | 260 | per-entity JSON views |
  | routes_core.py | 239 | clock (unprefixed), FOAs, institutes+payline, institutions, applicants |
  | routes_applications.py | 367 | applications CRUD + submit/withdraw/referral/select-pay + sublists |
  | routes_review.py | 178 | study sections + reviewers |
  | routes_assignments.py | 252 | assignments + COI/capacity/proximity gates |
  | routes_council_jit.py | 151 | council reviews + JIT |
  | routes_awards.py | 106 | award issuance + award reads |
  | routes_postaward.py | 273 | progress reports + modifications |
  | routes_transfers.py | 205 | transfer requests |

  **Coverage**: 52/52 routes registered (verified against live url_map); 73/73 error ids raised by at least one code path (grep-verified against the catalog); 10/10 state machines implemented with all transitions (walked §1.2 by hand). Constants audit clean (AST walk: no undefined UPPER_SNAKE refs; `ROUND_HALF_UP` comes from `decimal`). `grep uuid4` shows only `str(uuid.uuid4())` for resource ids (the `req_…hex` form is the envelope request-id per PRD §2.2, not a resource id). Clock endpoint mounted at unprefixed `/_clock/set_current_utc`.

  **Smoke tests** (all on dynamically allocated ports, own PID killed after each):
  - Matrix 1 (60 checks): full happy path — registries → draft→submit→refer→assign→convene→critiques→release (impact 87, means 8.5/8.5/8.0, percentiles 50.0) → council FUND → payline (walk funds, ESI) → JIT (due = clock+30d exactly) → award (per-year round-then-sum: 900000+450000=1350000/yr, total 2700000, terms incl. RESTRICTED_DRAW_DOWN) → report accept (min-disbursal, ledger conversion) → auto carryover (50000 ≤ 87500 limit) → auto NCE → LEDGER_ACTUALS transfer accept (successor 1700000, TRANSFERRED_AWARD term, institute net-zero) + header/404/RBAC/pagination errors.
  - Matrix 2 (41 checks): cert missing/expired, page/budget/receipt/closed-FOA gates, honor rule + override, section quota, all three COI errors, 7-day proximity boundary (inclusive at exactly 7d, free at 7d+1s), reviewer capacity (4 ok, 5th rejected), 3-live limit, duplicate/PRIMARY uniqueness, quorum fallback UNDER_REVIEW→REFERRED, live-assignments re-referral block, withdraw cascade, convene/release gates, UNSCORED path.
  - Matrix 3 (~50 checks): cross-panel normalized-percentile reconciliation (A1 rewritten 50.0→75.0 after later section release), payline stop-at-first-exceed (no skipping), ESI bonus decisiveness at payline 22, select-pay band/no-payline/cap(402)/authority(402) ordering, JIT RETURN→resubmit loop, JIT expiry cascade (EXPIRED + NOT_FUNDED), TIME_PRORATED relinquish (49863 = rhu(100000·182/365)), transfer pending/invalid-state/decline-no-fiscal, report period-mismatch/late/window-closed, carryover mismatch/exceeds/pending→approve effects (sum conserved), NCE too-late/limit/not-after/second-goes-pending, termination returning commitment.

  All three matrices pass clean; double-boot test proves fresh state per `start.sh` invocation; `py_compile` clean on all 15 Python files.

  **PRD ambiguities resolved (Step 7/8 arbitration inputs)**:
  1. **ERR_VALIDATION pipeline position**: §2.7 leaves it "separate from the pipeline". I validate malformed payloads (missing/typed/enum/range fields, start/effective dates before clock) after path existence and before ownership/state gates — except `submit-critique`, where the scaffold transition text puts state gates (assignment ACCEPTED, section MEETING_HELD) before the score-range validation.
  2. **Referral check order**: followed the §3.3 narrative (app state → OCC → section exists → recruiting → quota → institute exists → live-assignments → honor rule), noting §2.7's stage-4 body-FK list omits the referral target ids.
  3. **Derived counters** (`assigned_application_count`, `live_assignment_count`, `active_assignment_count`): recomputed from base data on every read instead of stored-and-adjusted — identical observable values, no drift; version bumps follow the scaffold's explicit `version += 1` sites (application transitions, institute ledger mutations per §2.8), not counter changes.
  4. **version starts at 1** at creation (PRD doesn't pin the initial value).
  5. **declare-conflict has no state gate** (scaffold defines none; PRD's "an active reviewer may" read as descriptive, not a gate).
  6. **Assignment to an unreferred application** (no study_section_id) → ERR_SECTION_NOT_RECRUITING, the only fitting catalog gate.
  7. **Successor award terms** are exactly `[STANDARD_TERMS_V1, TRANSFERRED_AWARD]` per the PRD's enumeration, even when the original award carried a budget cut.
  8. **created_at/updated_at/api_request_timestamp read the logical clock** (never wall clock), rendered with 3-digit millis; domain datetimes render second-precision when whole, else millis.
  9. **Carryover onto a fully-reported award** (current_period beyond the last period) extends `period_total_cents` so the sum-conservation invariant holds; unspecified by the PRD.
  10. **Modification type-role mismatch** is checked after path existence, before ownership (Applicant creating TERMINATION on a foreign award → ERR_MODIFICATION_TYPE_ROLE_MISMATCH).

## Step 7: Run Tests and Iterate — 2026-10-02T21:20:00.000Z

  Clean sweep achieved on the first iteration. All 8 parallel rounds passed 67/67 with zero failures, errors, or skips, and all 8 `results.*.json` artifacts remain in place.

  Summary:
  - Iterations run: 1
  - Tests deleted: none
  - Fixes applied to `test_helpers/`: none
  - Fixes applied to `test_suite/`: none
  - Fixes applied to `implementation/`: none
  - Final sweep evidence (per-round passed/total):
    - round 1: 67/67 (failed=0, errors=0)
    - round 2: 67/67 (failed=0, errors=0)
    - round 3: 67/67 (failed=0, errors=0)
    - round 4: 67/67 (failed=0, errors=0)
    - round 5: 67/67 (failed=0, errors=0)
    - round 6: 67/67 (failed=0, errors=0)
    - round 7: 67/67 (failed=0, errors=0)
    - round 8: 67/67 (failed=0, errors=0)

  The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_3492_peer_review_study_sections_percentile_scoring_award/workspace/implementation/` passes the full 67-test suite under per-test-server isolation across all 8 concurrent rounds with no flakiness signal. No diagnostic intervention was needed.

### Orchestrator verification of the Step 7 claim

Read all 8 `workspace/implementation/results.{1..8}.json` directly: all present (mtime 20:48, freshly written by the sweep), each `total=67, passed=67, failed=0, errors=0, skipped=0`; per-test entry list has 67 unique nodeids, identical across all 8 rounds, every entry status `passed`; round duration ~120s each. Claim CONFIRMED against source artifacts.

## Step 8: Finalize PRD — SKIPPED — 2026-10-02T21:21:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes. `PRD.md` determined every behavior exercised; no `PRD_FINALIZED.md` produced. Step 9 will read `PRD.md` directly.

## Step 9: Complete PRD — 2026-10-02T22:20:00.000Z

  PRD_COMPLETED.md is complete and verified. Here is the full report.

  ## Summary

  **Source vs. output:** `PRD.md` 382 lines / 64,822 chars → `PRD_COMPLETED.md` 386 lines / 70,053 chars (+4 lines, +5,231 chars, 20 edit sites, all in-paragraph inserts/revisions; no new sections, tables and numbering intact).

  **Counts:** 17 ambiguity-pins, 3 mismatch-revisions, **0 IMPL BUGs**.

  **Exhaustiveness audits (all clean):** all 52 PRD endpoints exist in impl; all 73 catalog error ids are both defined (`errors.py`) and raised (multiline-aware grep); no dead PRD-required checks (only uncalled helper is `rhu_int`, a pure numeric utility); no unguarded reachable reads of PRD-nullable fields (`study_section_id` guarded in assignment/critique routes, `percentile_*` only read post-SCORED, `current_payline_percentile` None-checked, transfer amounts non-null in RELINQUISHED state, etc.); all prose-only uniqueness rules (duplicate pa_number, one non-terminal application per applicant+FOA, non-duplicating declared_conflicts, one in-flight transfer) are enforced. `implementation/results.*.json` untouched.

  ### Changes (one bullet each)

  - §2.1 — insert — ambiguity — server never validates that an entity-backed `X-User-ID` is a registered entity; ownership is a pure FK comparison — routes_applications.py:54-57 (no applicant existence check)
  - §2.3 — insert — ambiguity — `created_at` ties break by creation sequence, id never a tie-break (also covers percentile pools) — util.py:130-135
  - §2.4 — revise — mismatch — domain datetimes render second-precision when whole, else exactly 3 fractional digits; sub-millisecond not preserved (was "rendered as supplied") — util.py:79-88
  - §2.5 — revise+insert — ambiguity — `version` starts at 1 at creation; new paragraph pinning the three counters as derived, recomputed per read, never self-bumping version — db.py:65, services.py:49-70, serializers.py:103/123/138
  - §2.7 stage 14 — revise — mismatch — enumeration order swapped: `ERR_LIVE_ASSIGNMENTS_EXIST` before `ERR_ASSIGNMENT_REQUEST_IGNORED` — routes_applications.py:271-295
  - §2.7 — insert — ambiguity — §3 narratives' more specific order governs the pipeline (referral: state gate + OCC before section/institute existence, per §3.3) — routes_applications.py:251-270
  - §2.7 — insert — ambiguity — ERR_VALIDATION position pinned per endpoint: after stage 3, before stage 4; follows ownership on reviewer-respond/declare-conflict/assignment-respond/JIT-submit-items, precedes it on report-creation/transfer-proposal/modification-creation; precedes stage 6 except submit-critique (both gates first) and award issuance (JIT_COMPLETE gate first); precedes stage 7; modification `type`-enum and type-role before ownership, required-for-type fields after the award-state gate; JIT expiry after validation, before JIT state gate — routes_review.py:150-178, routes_assignments.py:188-252, routes_council_jit.py:104-151, routes_awards.py:30-45, routes_postaward.py:60-96/142-234, routes_transfers.py:41-68
  - §2.8 — insert — ambiguity — institute creation bounds: appropriation/reserve ≥ 0, indirect_cost_rate and select_pay_cap_pct in [0,1], select_pay_extension_percentile ≥ 0, else ERR_VALIDATION — routes_core.py:126-130
  - §3.3 — insert — ambiguity — re-referral live-assignments guard evaluated before the honor rule — routes_applications.py:271-275
  - §3.4 — insert — ambiguity — `assigned_application_count` defined: applications of the section currently REFERRED or UNDER_REVIEW — services.py:65-70
  - §3.4 — insert — ambiguity — declare-conflict has no status precondition; repeat declaration is a successful no-op with no version increment — routes_review.py:165-178
  - §3.4 — insert — ambiguity — assignment section check reads the section only (application lifecycle not gated); never-referred application fails with ERR_SECTION_NOT_RECRUITING — routes_assignments.py:75-84
  - §3.5 — insert — ambiguity — percentile rewrites are derived-field reconciliation, no version bump; release increments each newly SCORED/UNSCORED app's version exactly once — services.py:88-195
  - §3.6 — revise — ambiguity — `priority_alignment_score` on DEFER/NOT_FUND: optional, but if supplied validated 1–5 and recorded — routes_council_jit.py:45-50
  - §3.7 — insert — ambiguity — `base_payline_percentile` taken as supplied, no range validation — routes_core.py:167
  - §3.8 — insert — ambiguity — lazy JIT expiry runs on submit-items/adjudicate only; GET does not trigger it — routes_council_jit.py:90-101
  - §3.9 — insert — ambiguity (silence) — report acceptance lands the report in terminal `ACCEPTED` state — routes_postaward.py:134-135
  - §3.9 — revise — ambiguity — type-role mismatch check runs after path existence and `type` validation, before ownership and the ACTIVE gate; carryover field bounds (`amount_cents` ≥ 0, `from_period` ≥ 1) — routes_postaward.py:146-163, 180-181
  - §3.9 — insert — ambiguity (silence) — carryover past the last budgeted period extends `period_total_cents` with a new trailing entry; `total_awarded_cents` unchanged — services.py:344-354
  - §3.9 — revise — mismatch — successor award terms are exactly `STANDARD_TERMS_V1` + `TRANSFERRED_AWARD`; `RESTRICTED_DRAW_DOWN` does not carry over (was "gaining … alongside") — routes_transfers.py:195
  - §5 — insert — ambiguity (silence) — envelope-level `ERR_NOT_FOUND` (404) / `ERR_METHOD_NOT_ALLOWED` (405) / `ERR_INTERNAL` (500) outside the business catalogue — app.py:47-59

  ### Per-known-site verdicts

  1. **ERR_VALIDATION position — pin-added**, with a correction to the site description: the code does *not* uniformly validate before ownership — ownership precedes validation on reviewer respond, declare-conflict, assignment respond, and JIT submit-items (e.g. routes_review.py:155-157); and award issuance (routes_awards.py:37-45) is a second state-gate-before-validation endpoint alongside submit-critique (routes_assignments.py:232-247). Pinned the code's actual per-endpoint positions in §2.7.
  2. **Referral order — pin-added** (§2.7 carve-out + §3.3 clause + stage-14 reorder). Code order confirmed: app state → OCC → section exists → recruiting → quota → institute exists → live-assignments → honor rule (routes_applications.py:251-295).
  3. **Derived counters — pin-added** (§2.5 paragraph + §3.4 definition). Confirmed recomputed per read in serializers.py; version bumps only at explicit `touch()` sites (db.py:70-73).
  4. **version starts at 1 — pin-added** (§2.5). db.py:65.
  5. **declare-conflict no state gate — pin-added** (§3.4). routes_review.py:165-178 — no status check; duplicate declaration is a no-op without touch.
  6. **No-section assignment → ERR_SECTION_NOT_RECRUITING — pin-added** (§3.4). routes_assignments.py:75-84.
  7. **Successor terms exactly [STANDARD_TERMS_V1, TRANSFERRED_AWARD] — mismatch-revision** (§3.9). routes_transfers.py:195; original's budget-cut term does not carry.
  8. **Timestamp two-family rendering — mismatch-revision** (§2.4). util.py:79-96 (`render_ts` always 3-digit; `render_dt` second-precision when whole).
  9. **Carryover beyond last period extends `period_total_cents` — pin-added** (§3.9). services.py:347-353.
  10. **Type-role mismatch after path existence, before ownership — pin-added** (§3.9 + covered in §2.7 position pin). routes_postaward.py:146-163 — confirmed: Applicant creating TERMINATION on a foreign award gets ERR_MODIFICATION_TYPE_ROLE_MISMATCH, not ERR_NOT_RESOURCE_OWNER.

  ### IMPL BUGs

  None. Every place where PRD states a rule uniquely, the implementation conforms; all divergences found were PRD silence or multi-interpretable prose, pinned as above.

### Orchestrator verification + mismatch-revision adjudication (post-Step-9)

Artifact check: `PRD_COMPLETED.md` exists at 386 lines / 70,053 chars (exactly the claimed +4/+5,231 delta over PRD.md), differs from PRD.md (not a silent no-op); diff contains exactly 20 hunks matching the 20 reported bullets; all 8 `results.*.json` sweep artifacts intact.

Mismatch-revision adjudication against scaffold intent (orchestrator read of SCAFFOLD.yaml — the Step 9 subagent was barred from it):
1. **§2.4 timestamp rendering** — SCAFFOLD.yaml has NO rendering-precision rule (grep for fractional/precision/millisecond/render is empty). Scaffold-silent → no intent lost; revision pins impl behavior. ACCEPTED.
2. **§2.7 stage-14 order** — SCAFFOLD.yaml lines 277-280 (REFERRED→REFERRED transition) order preconditions: OCC → `ERR_LIVE_ASSIGNMENTS_EXIST` → "same target-state preconditions as SUBMITTED→REFERRED" (whose honor rule, line 267, is last). The impl's order (live-assignments before honor rule) IS the scaffold's order; the original PRD stage-14 sentence had translated them in the wrong order. The revision restores scaffold intent, it does not strip it. ACCEPTED. (Residual scaffold nuance: scaffold puts the live-assignments guard before section-existence on re-referral; PRD narrative and impl put it after target-state checks. PRD-first contract makes PRD_COMPLETED authoritative; no test asserts the scaffold-only relative order — noted as a doc-generator translation observation.)
3. **§3.9 successor terms** — SCAFFOLD.yaml line 175 (`STANDARD_TERMS_V1 always; + RESTRICTED_DRAW_DOWN when budget_cut_pct > 0; + TRANSFERRED_AWARD on successor awards`) plus the ACCEPT cascade (line 609) enumerating the successor's fields with `terms += TRANSFERRED_AWARD` and no carry of the original's budget-cut term. Exactly-[STANDARD_TERMS_V1, TRANSFERRED_AWARD] is the scaffold reading; original PRD "gaining … alongside" was ambiguous. ACCEPTED.

No Step 9b (impl fix + re-sweep) needed: 0 IMPL BUGs, all 3 revisions adjudicated as scaffold-consistent.
