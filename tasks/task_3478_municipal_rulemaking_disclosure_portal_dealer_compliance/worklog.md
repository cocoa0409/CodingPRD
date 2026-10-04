# Worklog — task_3478_municipal_rulemaking_disclosure_portal_dealer_compliance

## Step 1: Create Task Directory — 2026-10-02T12:55:00.000Z

Task directory pre-allocated by caller (./tasks/task_3478_municipal_rulemaking_disclosure_portal_dealer_compliance with workspace/ inside); verified existence, no new index computed. INSTRUCTION.md confirmed present at project root.

## Step 2: Generate Scaffold — 2026-10-02T13:55:00.000Z

Scaffold generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_3478_municipal_rulemaking_disclosure_portal_dealer_compliance/` and `scaffold_lint.py` reports **clean lint** (verbatim verdict: "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." — 40 endpoints, 10 entities, 18 §1.8 + 58 §1.9 instances, 342 calls scanned).

**Design summary (MSRB municipal rulemaking / disclosure / dealer compliance):**

- **Profile**: compliance_audit × workflow_orchestration; flat FK topology; cyclic state machines; segregation-of-duties role model; layers = optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, scheduled_deferred_actions. Logical clock via unprefixed `POST /_clock/set_current_utc` with pinned default `2026-09-01T00:00:00Z` and a strictly ordered epoch pass (effectuation+supersession → CE transitions → tally/posture recompute).
- **Entities (10)**: Organization (single type-gated org entity covering issuers/obligated-persons/broker-dealers/advisors, with derived late_report_count, compliance_posture, published_par_total, active_professional_count), RuleProposal (self-referential supersession, half-open comment windows, 30d/10d effectiveness variants), CommentLetter, DisclosureSubmission (event-notice day-10 timeliness, closed-interval annual coverage overlap), MunicipalProfessional (parallel qualification × standing dimensions, CE cycle with ethics sub-bucket), ExamAttempt, TradeReport (900s reporting boundary, 5M par publication cap), DataSubscription (tiered fee + rounding-order invoice), EnforcementReferral (exactly-one polymorphic subject, authority selector, SoD on close, guidance published on close-with-action), SolicitationRecord (fiduciary type-gate + contingent fee cap).
- **Harder-than-expert levers** (density over volume): 2 dual-variant calcs on different domains, 2 combinatorial formulas in different modes ((a) 4-input non-linear fee — pinned literal 577125¢; (b) round-per-line-then-sum invoice — pinned 153749/1844988 vs the forbidden 1844982), a depth-3 clock-triggered supersession→referral-flag cascade and a depth-3 trade-create→posture→subscription-rejection cascade, two SoD gates, OCC on draft edits, two priority-conflict pairs (state×temporal, referential×fiscal), half-open vs closed interval overlap semantics, and two compensating invariants (headcount 2→1→2; published par 2,000,000 conserved through capped publish + cancel).
- **Coverage**: 32-error catalog, 11 roles with `identity:` declared (IssuerRep/DealerRep entity-backed to Organization, rest opaque), 25 ordered validations, 9 machine blocks. Role-scoped reads for PublicReader (PUBLISHED/DISSEMINATED only) and entity-backed ownership scoping.

**Process notes**: two YAML hazards were caught and fixed mid-build per the append-and-parse loop — an unquoted `description:` containing a colon (line 1367) and unquoted `errors[...]` brackets inside flow-style `grounds:` lists. Post-build programmatic audit confirmed: every `grounds:` reference resolves, every error id has a triggering instance (added a missing `ERR_EVENT_CATEGORY_REQUIRED` corner), all `excluded_because:` stubs cite real difficulty-instance names, instance names are unique across both design files, no forbidden concurrency vocabulary, and every active instance has a non-empty trigger.

**Orchestrator verification** (independent of subagent report): all three files parse as YAML; SCAFFOLD.yaml has api_prefix `/msrb`, 40 endpoints, 10 entities; difficulty index = 18 instances / 0 stubbed; corner index = 69 instances / 11 stubbed / 58 active across 9 sections (entities 7, state_machines 11, calculations 7, validations 17, endpoints 7, errors 7, rbac 5, cross_cutting_layers 7, consistency_model 1); 239 MSRB-domain token matches confirm correct domain. Total active test queue = 76 instances.

## Step 3: Copy Shared Files — 2026-10-02T13:56:30.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T14:19:00.000Z

The PRD is complete and verified. Final report:

## Task Complete

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3478_municipal_rulemaking_disclosure_portal_dealer_compliance/workspace/PRD.md` (300 lines), generated from `SCAFFOLD.yaml` per the prd-bench-doc-generator skill. The two forbidden design-index files were never opened; no sibling tasks were touched.

**Structure:** §1 two-paragraph introduction; §2 with nine domain-derived subsections (roles/identity, verbatim response envelope, pagination, logical clock & pinned epoch ordering, first-failure validation order, OCC, nested path resolution & scoped visibility, common resource properties, units/precision/rounding); §3 with eight workflow subsections (rulemaking lifecycle, effectiveness/supersession cascade, comment moderation, disclosure intake, organizations/trade reporting/dealer posture, professional qualification & CE, market-data licensing & fees, enforcement referrals & solicitation oversight); §4 four-column endpoint table with exactly 40 rows including the unprefixed `/_clock/set_current_utc`; §5 two-column error table with all 32 error IDs. Document ends at §5 with no audit footer.

**Notable fidelity points:** §2.2 diffed byte-identical against `section-2.2-response-structure.md`; validation priorities 1–24 rendered as an explicit ordered narrative (incl. proposal-open before window-closed, unresolved-comments before still-open, disclosure before fee cap); the single OCC rule names `expected_rule_proposal_version` → `ERR_STALE_VERSION` 412 in pure stale-version framing; all constants embedded (900-second limit, 5,000,000 par cap, 30-day half-open tally window, threshold 5, 365/60/12/2 CE values, pass marks 70/72/75/80, full fee schedule, 2,500,000-cent fiduciary cap, 21–90 comment window, 30/10-day effectiveness variants, clock start `2026-09-01T00:00:00Z`); append-only `ExamAttempt`/`SolicitationRecord` explicitly carry only `id` + `created_at`.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint input/query/path params: 100 required, 100 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 24 checked, 24 expressed in §2.5 ordered prose + endpoint narratives, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (write endpoint + expected_rule_proposal_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 21 checked (incl. 2 posture transitions), 21 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed with all constants and pinned rounding orders, 0 missing
- validations[] conditions: 24 checked, 24 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 40 checked, 40 expressed, 0 missing
- entities[].fields[] structured content: 100 checked, 100 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (decide, moderate, review-outcome, standing, subscription transitions, posture transitions), 6 with equal prose density, 0 asymmetric
- 46 load-bearing phrase spot-checks: 46 pass
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 502
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All enum/state values (77), all role names (11), and all error IDs (32) verified present verbatim. One process note: the first coverage audit false-negatived because triple-backtick code fences shifted the regex's backtick pairing — stripping fenced blocks before tokenizing fixed it (file itself was never corrupted; quoted heredocs preserved every backtick).

**Orchestrator verification** (independent): PRD.md = 300 lines, 67 ERR_ mentions, 61 domain-token matches, 76 table rows, unprefixed `/_clock/set_current_utc` present at line 262.

## Step 5a: Generate test_helpers (Stage 1 of split Step 5) — 2026-10-02T14:45:00.000Z

Stage 1 is complete. All nine `test_helpers/` files are written, compile-verified individually, and the package imports end-to-end.

## What was generated

`/home/ubuntu/github/CodingPRD/tasks/task_3478_municipal_rulemaking_disclosure_portal_dealer_compliance/test_helpers/`:

- **constants.py** — API_PREFIX `/msrb`, CLOCK_START `2026-09-01T00:00:00Z`, 900-second trade limit, 5,000,000 par cap, 30-day/5-trade posture rule, effectiveness delays 30/10, comment bounds 21–90, PASS_SCORES 70/72/75/80, REQUIRED_SERIES, retake 30d, CE 365/60/12/2, event-notice 10d, fiduciary cap 2,500,000 cents, full fee schedule, pagination. No dead constants.
- **types.py** — UserRole (11 roles, exact spellings) + 25 domain enums + 12 TypedDicts. Append-only entities (ExamAttempt, SolicitationRecord) carry only `id`/`created_at` — verified mechanically per entity against `common_fields`.
- **api_errors.py** — all 32 error IDs with PRD §5 statuses (401×1, 403×3, 400×1, 404×9, 409×5, 412×1, 422×12); registered via `set_error_http_status_map`.
- **api_client.py** — 41 methods (all 40 scaffold endpoints + `raw`). Audit confirmed all 40 paths covered; `set_clock` posts to `/_clock/set_current_utc` **without** the `/msrb` prefix, the other 39 use it.
- **factories.py** — 24 payload factories, input fields only, unique `org_code`/`rule_code` via a process counter, clock-safe defaults (trade `executed_at` defaults to CLOCK_START; event notices default to a past date).
- **test_users.py** — `TEST_USERS` (14 header sets including `rulemaking_officer_alt`, `regulator_alt`, `compliance_officer_alt` for segregation-of-duties tests), mandatory `make_issuer_rep_headers(org_id)` / `make_dealer_rep_headers(org_id)` entity-backed builders, malformed-credential header helpers.
- **assertions.py** — per-entity `assert_*` shape checkers, `assert_mutable_common_fields` vs `assert_append_only_common_fields`, `canonical_instant`/`assert_instant` (tolerates `.000Z` rendering differences on computed instants), `assert_may_transact_invariant`, envelope/pagination-order helpers.
- **fixtures.py** — five tiers: clock/primitive builders; org+professional and qualified-professional hierarchies; proposal lifecycle walks (`create_pending_approval_proposal`, `create_approved_proposal`, `create_effective_proposal`, `create_disapproved_proposal`, `create_referred_referral`); accumulation targeting (`create_late_trades`, `setup_org_at_watch` = 5 late trades → WATCH + PENDING subscription REJECTED, `setup_active_subscription`); terminal states (`create_superseded_pair` with optional referral, `create_ce_due_professional`, `create_lapsed_professional`, `create_closed_referral`). All timing flows through `add_days`/`sub_seconds` from an explicit `anchor` (default CLOCK_START); anchor math was verified to reproduce every design-index literal (2026-09-22, 2026-10-02, 2026-10-22, 2027-09-01, 2027-10-31). Entity-backed calls build headers from the real org id internally.
- **__init__.py** — barrel export (171 names) re-exporting framework generics + all helpers.

## Self-audit results (all green)

- 40/40 endpoints covered; clock unprefixed (grep-verified)
- 32/32 errors, zero status mismatches vs scaffold §1.6/PRD §5
- 10/10 entities: TypedDict + factory + assertion; append-only shape correct
- 11/11 roles in UserRole and exercised in test_users
- All pinned constants grep-verified verbatim against PRD.md prose
- No "scaffold"/section-table references in any generated comment
- Functional smoke (factories, headers, instant canonicalization, error-map registration) passes; `test_suite/` untouched for Stage 2

**Note for the Stage-2 agent:** `from test_helpers import api_client` yields the shared client *instance* (the module attribute is shadowed after package import — the known pattern); construct `ApiClient()` or use the instance. Fixture functions that move the clock document their `anchor` assumption — pass a later anchor when composing after an earlier clock move to avoid `ERR_CLOCK_REGRESSION` in setup.

**Orchestrator verification** (independent): all 9 files present, package imports cleanly (181 names), `set_clock` posts to unprefixed `/_clock/set_current_utc` (line 30), no `msrb` prefix bleed on the clock path.

## Step 5b: Generate test_suite (Stage 2 of split Step 5) — 2026-10-02T15:42:00.000Z

Collection is clean: 94 tests, no import errors. Stage 2 is complete.

## Report

**Generated:** `test_suite/` in `/home/ubuntu/github/CodingPRD/tasks/task_3478_municipal_rulemaking_disclosure_portal_dealer_compliance/` — `conftest.py` (session-scoped `api` fixture + role header fixtures) plus 13 test modules, **94 tests total**. `test_helpers/` was not touched (verified read-only usage; all calls go through the frozen fixtures/factories/`make_*_headers` builders).

**Coverage (audited programmatically via AST walk + YAML cross-reference):**
- Queue A (Difficulty): 18/18 instances covered with ≥2 tests each (36 tags).
- Queue B (Corner): 58/58 non-stub instances covered with ≥1 test (58 tags); the 11 `excluded_because` stubs are untagged, as required.
- No untagged, dual-tagged, dangling, or stub-pointing `Design:` tags.
- `pytest --collect-only -q` (PYTHONPATH=task dir): **94 collected, 0 import errors** — package graph is sound.
- PRD-citation verbatim check: every ≥8-word quoted span in every docstring greps literally against `workspace/PRD.md` (initial run caught 25 paraphrase/ellipsis violations — `§` vs "section", ellipses inside quotes — all fixed by rewriting to full verbatim sentences; final audit PASS). Audit script kept at `tasks/task_3478.../audit_stage2.py` for re-verification.

**Key adjudication:** all 76 active instances passed the PRD-first two-condition filter — zero skipped. The one adjustment: the design YAML pins absolute `version` literals (create==1, decide_v==4, etc.), but PRD §2.8 only states version "increments by exactly one on every mutation" without pinning the creation-time value. I asserted all versions relatively (e.g. `patched["version"] == decide_version + 1`, `va_post == va_pre + 1`) to avoid a false failure against a PRD-faithful 0-initialized implementation; all other design literals (577125/6925500 fee pair, 153749/1844988 rounding pair, 900-second and day-10 boundaries, 2,500,000-cent cap, window/CE anchor instants) are asserted verbatim.

**File map (domain-clustered):** `test_01_organizations` (entity defaults/schema/append-only shape), `test_02_rule_proposal_lifecycle` (OCC, revision cycle ×2, decide/SoD gates), `test_03_rule_effectiveness_and_supersession` (30/10-day dual variant ×2, depth-3 referral-flag cascade ×2, pinned epoch order), `test_04_comment_letters` (state-beats-temporal ×2, unresolved-comments gate ×2, half-open window), `test_05_disclosure_submissions` (day-10/11 timeliness, closed-interval overlap ×2, scoping), `test_06_trade_reporting` (par-cap dual variant ×2, 900s boundary ×2, ownership), `test_07_dealer_compliance_posture` (WATCH cascade ×2, cancel-conserves-par ×2, tally window decay), `test_08_exams_and_qualification` (pass-mark boundaries ×2, retake half-open window ×2, employer-suspension gate ×2), `test_09_standing_and_ce` (parallel dimensions ×2, headcount conservation ×2, CE ethics sub-bucket, CE epoch), `test_10_subscriptions_and_feeds` (fee formula ×2, rounding order ×2, licensing gates), `test_11_enforcement_referrals` (SoD close, ambiguous subject, rule citation split), `test_12_solicitation_records` (type-gate-beats-fee-cap ×2, cap boundary, disclosure gate), `test_13_auth_rbac_envelope_pagination` (401/403 role matrix, envelope, pagination, clock monotonicity).

Note: tests assume the runner's per-test server restart (fresh DB + clock at `2026-09-01T00:00:00Z`); all clock choreography uses the fixtures' `anchor`-discipline helpers and stays monotonic.

**Orchestrator verification** (independent AST audit + collection): 13 test modules + conftest; `pytest --collect-only` = 94 tests, 0 import errors; 94/94 tests carry exactly one `Design:` tag; 0 tags fail to resolve to an active design instance; 0 tags point at stubbed instances; 76/76 active instances covered (18 Difficulty + 58 Corner), 0 uncovered.

## Step 6: Generate Implementation — 2026-10-02T16:25:00.000Z

Done. The implementation is complete, compile-clean, and smoke-tested across two full boot cycles (proving the per-test-server isolation requirement).

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_3478_municipal_rulemaking_disclosure_portal_dealer_compliance/workspace/implementation/` — Python + Flask, in-memory dicts only, zero seeding:

- `start.sh` (guarded pip install + `exec python3 app.py`, `$PORT`/0.0.0.0/foreground), `requirements.txt`
- `app.py` — blueprint registration, envelope-wrapped error handlers
- `store.py` — 10 entity dicts + logical clock pinned at `2026-09-01T00:00:00Z`
- `errors.py` — all 32 catalog error_ids with exact HTTP statuses
- `respond.py` — `{meta, response_type, data}` envelope; list meta carries `limit/offset/total_count/has_more`
- `validators.py` — auth headers (`X-User-ID`/`X-User-Role`), schema/type/enum/datetime parsers, pagination
- `serializers.py` — exact per-entity output fields; ExamAttempt/SolicitationRecord ship only `id`+`created_at` (no `updated_at`/`version`)
- `services.py` — all calculation constants (900s trade limit, 5M par cap, fee schedules, pass scores, CE 365/60/12/2, 30-day late window, threshold 5) + posture recompute + qualify
- `clock_ops.py` — monotonic clock set + pinned 3-step epoch pass (proposal effectuation w/ supersession cascade → CE transitions → org tally/posture w/ PENDING-subscription rejection)
- `routes/` — 8 modules covering all 40 endpoints (39 under `/msrb` + unprefixed `POST /_clock/set_current_utc`)

## Key fidelity decisions (all traceable to PRD/scaffold)

- **Validation order** follows PRD §2.5 exactly, including the subtle ones: `ERR_UNRESOLVED_COMMENTS` (409) before `ERR_COMMENT_PERIOD_STILL_OPEN` (422) on submit; `ERR_DISCLOSURE_REQUIRED` before `ERR_FEE_CAP_EXCEEDED`; `ERR_PROPOSAL_NOT_OPEN_FOR_COMMENT` fires regardless of window state; trade-time (422) before org-type gate (422); SoD (403) before generic state (409) on decide/close.
- **Scoped single-GETs** return 404 (not 403) for IssuerRep/DealerRep/PublicReader out-of-scope reads; trade **cancel** ownership mismatch returns 403 per its explicit precondition.
- **OCC**: `expected_rule_proposal_version` required on PATCH; state check (DRAFT/DISAPPROVED → 409) precedes the stale-version 412.
- **Epoch effects** counted as discrete state changes (effectuation, supersession, referral flag flips, CE transitions, posture flips, cascade rejections); org derived-counter recomputes do not bump org `version` per PRD §2.8.
- **Fees**: `Decimal` math, one `ROUND_HALF_UP` at the end of the monthly formula; annual = 12 × rounded monthly (verified: 99999→1199988 and the 0.9-discount Redistribution case 313875→3766500).
- **`to_state: REJECTED`** on the subscription transition → 400 `ERR_INVALID_REQUEST` (system-only target).
- **Boundary checks verified live**: exactly-900s trade = timely, 901s = late (`seconds_late` 1); day-10 event notice = TIMELY; half-open retake window; closed-interval coverage overlap with day-sharing rejected and perfect adjacency allowed; 5th late trade trips WATCH and rejects PENDING subscriptions; cancel relaxes WATCH→CLEAR without resurrecting REJECTED.
- **Prose-only uniqueness** (`org_code`, `rule_code`) enforced via store-scan + `ERR_INVALID_REQUEST` since the catalog has no dedicated id.

## Verification

`python3 -m py_compile` on all 17 source files: clean. Two smoke suites (~100 assertions) run against two separate fresh boots via `start.sh` on dynamically allocated ports: **all passed** — covering the full rulemaking pipeline (draft→open→comment→moderate→submit→SoD→approve→epoch-effectuate→supersede→referral flag), disclosure intake/timeliness/overlap/scoping, trade timeliness/banding/cancel compensation, professional qualification/standing/CE cure, subscription fees/lifecycle, data feeds, enforcement routing/closes, solicitation fiduciary gates, clock regression, and envelope shape on both success and error paths. Server PIDs were saved and killed exactly; no other pipeline processes touched.

**Orchestrator verification** (independent): 11 top-level files + 8 route modules, all compile clean; start.sh is guarded-pip + foreground exec; clock route registered unprefixed at routes/clock.py:13.

## Step 7: Iterate Tests + Fixes — 2026-10-02T16:35:00.000Z

First 8-round parallel sweep: 93/94 in every round — one deterministic failure, zero flakiness. `test_03_rule_effectiveness_and_supersession.py::test_both_variants_effectuate_at_their_own_computed_instant` crashed with `ValueError: time data '2026-10-02T00:00:00.000Z' does not match format '%Y-%m-%dT%H:%M:%SZ'` at its `add_days(expedited["effective_at"], 20)` call.

Diagnosis (per protocol): the asserted rule (dual 30/10-day effectiveness variants, PRD section 3.2) is verbatim-covered and uniquely derived — no deletion. The failure was a STEP 2 test_helpers bug: `fixtures.py::_parse` accepted only the whole-second Z spelling, while the implementation legitimately renders computed instants with three fractional digits (PRD section 2.8 pins three fractional digits for `created_at`; rendering of computed instants is format-silent, and the suite's own `assert_instant`/`canonical_instant` already declares both spellings equal). Fix: `_parse` now tries `%Y-%m-%dT%H:%M:%S.%fZ` then `%Y-%m-%dT%H:%M:%SZ`, still rejecting non-instants. No implementation change; no assertion weakened; no test deleted.

Second 8-round parallel sweep after the fix: 94/94 in all 8 rounds. CLEAN.

**Step 7 final summary (verbatim from subagent exit):**

- **Iterations run:** 2 sweeps (initial 8-round sweep + 1 fix + confirming 8-round sweep). Final state: **94/94 passing in all 8 parallel rounds**.

- **Tests deleted:** none. The single failing test's asserted rule (PRD §3.2 dual 30-day/10-day effectiveness variants) is verbatim-covered and uniquely derivable, so it stayed.

- **Fixes applied to `test_helpers/`:** one file — `/home/ubuntu/github/CodingPRD/tasks/task_3478_municipal_rulemaking_disclosure_portal_dealer_compliance/test_helpers/fixtures.py`, the `_parse` instant parser (backing `add_days`/`sub_seconds`). It previously accepted only the whole-second `...T00:00:00Z` spelling via strict `strptime`, so when `test_03_rule_effectiveness_and_supersession.py::test_both_variants_effectuate_at_their_own_computed_instant` fed the server-returned `effective_at` (`2026-10-02T00:00:00.000Z`) into `add_days`, it raised `ValueError`. PRD §2.8 pins three fractional digits for `created_at` and is format-silent for computed instants, and the suite's own `assert_instant`/`canonical_instant` already treats both spellings as equal — so the strict parser was the bug, not the implementation. `_parse` now tries `...%S.%fZ` then `...%SZ`, and still rejects non-instants. Verified with a direct unit check (both spellings parse, garbage still rejected).

- **Fixes applied to `implementation/`:** none. The implementation's `.000Z` rendering of computed instants is PRD-faithful; no implementation defect was found. No assertions weakened, no skips/xfails added, no PRD-required checks touched.

**Orchestrator verification** (independent): all 8 results.{i}.json show passed=94 total=94 failed=0; no .py source file in implementation/, test_suite/, or test_helpers/ is newer than the sweep artifacts; results files were not deleted.

## Step 8: Finalize PRD — 2026-10-02T16:55:00.000Z

The edit is applied. Final verification confirms a single, minimal insertion.

## Summary

**Line counts:** PRD.md = 300 lines; PRD_FINALIZED.md = 302 lines; +2 lines (+0.67%). Not byte-identical — one edit was warranted (adjudication below).

**Changes:**
- §2.8 (Common Resource Properties) — insert — added one paragraph after the `version` bullet pinning that every timestamp the server renders on a resource uses ISO 8601 UTC with exactly three fractional digits (`.000Z` spelling), covering `updated_at`, derived instants (`comment_window_start/end`, `approval_at`, `effective_at`, `qualified_at`, `ce_cycle_end`, `ce_grace_end`, `reported_at`, `referred_at`), and echoed client-supplied instants (`executed_at`, `event_occurred_at`, `period_start`, `period_end`) — `workspace/implementation/serializers.py:10-14` (`fmt_dt`, the unconditional three-fractional-digit renderer used by all 15 datetime-field callsites across all 10 resource serializers).

**Per-candidate adjudication (the Step 7 diff contained exactly one fix):**
- The fixtures.py `_parse` fix traces to a genuine PRD silence, not merely a fixture bug: Step 7's own diff states "PRD §2.8 pins three fractional digits for `created_at` and is format-silent for computed instants", while the impl uniformly renders every resource-carried datetime as `.mmmZ`. A fresh implementer rendering `effective_at` as `2026-10-02T00:00:00Z` (PRD.md-legal) would produce wire bytes differing from `implementation/`, so the zero-edit condition ("PRD.md already determines every behavior at the touched site") is not met. The alternative zero-edit trigger (pinning would be a false universal claim) was checked and neutralized by scoping — see below.

**Pre-edit search log (edit 1):**
- (a) Subject: the wire spelling (fractional-digit precision) of server-rendered timestamps on resources.
- (b) Impl paths enumerated and read/grepped: `serializers.py:10-14` (`fmt_dt`) plus every callsite (serializers.py:38-39, 55-56, 61-64, 78-79, 90-92, 98-99, 112-114, 118-119, 131, 143-144, 150-151, 167-168, 183, 188-189, 202) — all resource datetimes, always three fractional digits; `serializers.py:17-23` (`fmt_clock`) + `routes/clock.py:22` — the clock-set response's `current_utc`, which renders whole-second instants WITHOUT a fractional part (matching §2.4's pinned `2026-09-01T00:00:00Z` startup default); `respond.py:14-16` — envelope `meta.api_request_timestamp`, three fractional digits, already pinned verbatim by PRD §2.2 line 55; `validators.py:134-148` (`parse_datetime_value`) — lenient ISO 8601 input parsing, unaffected by a rendering pin. A full-repo grep for `strftime|isoformat|fmt_dt|fmt_clock` confirmed no other render sites exist, and route-level grep confirmed all single-read, create, transition, and list responses funnel through the same serializers.
- (c) Wording adjustment: the universal claim is scoped with "renders on a resource" so it neither contradicts the `fmt_clock` whole-second echo (clock-set response is not a resource representation) nor re-pins the already-pinned envelope timestamp; field lists use "such as" so they illustrate rather than close the enumeration; input-side parsing is left untouched.

**Orchestrator verification** (independent): diff PRD.md→PRD_FINALIZED.md shows exactly the reported 2-line insertion after line 129, nothing else.

## Step 9: Complete PRD — 2026-10-02T17:20:00.000Z

Done. The diff confirms exactly 18 in-place paragraph edits (18 old lines ↔ 18 new lines), no new sections, no deletions.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 302 lines / 57,180 chars → `PRD_COMPLETED.md` 302 lines / 60,526 chars (char-delta **+3,346**; line count unchanged — all edits are in-paragraph inserts/revisions).

**Counts:** 18 ambiguity-pins, **0 mismatch-revisions**, **0 IMPL BUGs**. Every pinned PRD behavior I checked (validation ordering, boundaries at 900s/30d/10d/5/21–90/70-72-75-80, fee formula, cascades, scoping, roles, error catalogue, endpoint surface of 40 routes) matched the implementation exactly. Direction-(c) check (PRD-mandated check with no enforcement): none — both prose uniqueness rules (`org_code`, `rule_code`) are enforced via store scans.

### Changes (all ambiguity-pins)

- §2.3 — insert — ambiguity — pinned pagination rejection of non-integer/out-of-range `limit`/negative `offset` as `ERR_INVALID_REQUEST` 400, creation-timestamp ties keep insertion order, and the `has_more` formula — implementation/validators.py:168-186, respond.py:31-38
- §2.4 — insert — ambiguity — pinned `epoch_effects` accounting (per effectuation, supersession, referral flag, CE transition, posture change, subscription rejection) and `current_utc` rendering (whole-second instants without fractional part) — implementation/clock_ops.py:37-106, serializers.py:17-23
- §2.4 — insert — ambiguity — pinned that both CE transitions are evaluated within one epoch pass, so a professional past `ce_grace_end` goes `QUALIFIED`→`CE_DUE`→`LAPSED` in a single pass (two version bumps) — implementation/clock_ops.py:77-100
- §2.5 step 2 — insert — ambiguity — pinned ownership comparison applies only to present string payload fields (missing/wrong-typed defers to schema 400) and cancellation ownership is checked after the trade resolves (404 before 403) — implementation/validators.py:45-56, routes/trades.py:153-162
- §2.6 — insert — ambiguity — pinned the stale-version check runs after the editing-state gate (409 beats 412) — implementation/routes/rulemaking.py:157-168
- §2.8 — revise — ambiguity — pinned `version` starts at 1 on creation — implementation/routes/organizations.py:59 (and all other create routes)
- §2.8 — insert — ambiguity — pinned that org derived-counter/posture recomputation (`late_report_count`, `compliance_posture`, `published_par_total`, `active_professional_count`) never bumps org `version`/`updated_at`; only registration and suspension do — implementation/services.py:63-97, routes/organizations.py:88-89
- §2.9 — insert — ambiguity — pinned datetime input parsing (offset-less values read as UTC; offsets normalized to UTC) — implementation/validators.py:134-146
- §3.1 — revise — ambiguity — pinned duplicate `rule_code` at creation → `ERR_INVALID_REQUEST` 400 — implementation/routes/rulemaking.py:75-81
- §3.1 — insert — ambiguity — pinned a no-field-change PATCH on `DISAPPROVED` still reopens to `DRAFT` and clears decision history — implementation/routes/rulemaking.py:169-181
- §3.1 — insert — ambiguity — pinned a `reason` supplied with `APPROVE` is accepted but not recorded — implementation/routes/rulemaking.py:253,282-284
- §3.3 — insert — ambiguity — pinned a `reason` supplied with `PUBLISH` is ignored — implementation/routes/rulemaking.py:351-367
- §3.4 — revise — ambiguity — pinned `event_category` on non-`EVENT_NOTICE` filings → `ERR_INVALID_REQUEST` 400, and `period_start`/`period_end`/`event_occurred_at` supplied on non-carrying types are ignored — implementation/routes/disclosures.py:75-81
- §3.5 — revise — ambiguity — pinned duplicate `org_code` → `ERR_INVALID_REQUEST` 400 — implementation/routes/organizations.py:38-44
- §3.6 — revise — ambiguity — pinned standing `reason` is accepted but not persisted, and setting standing to its current value → `ERR_INVALID_STATE` 409 — implementation/routes/professionals.py:122-130
- §3.6 — insert — ambiguity — pinned CE credit amounts accept any decimal including zero/negatives — implementation/routes/professionals.py:148-149,157-158
- §3.7 — insert — ambiguity — pinned the earliest-created qualifying ACTIVE subscription authorizes a feed pull and supplies `subscription_id` — implementation/routes/subscriptions.py:188-199
- §3.8 — insert — ambiguity — pinned transition-inapplicable inputs (`guidance_text`/`closure_notes` on `OPEN`→`REFERRED`, `guidance_text` on `CLOSED_NO_ACTION`) are accepted but not recorded — implementation/routes/enforcement.py:173-198

### IMPL BUGs

None.

### Dead-code findings (direction (a) — impl smells, reported only; no PRD change)

- `opt_datetime` — implementation/validators.py:155 — defined, never called from any route.
- `invalid_request` / `invalid_state` — implementation/errors.py:55,59 — helper constructors defined, never called (all routes raise `ApiError` directly).
- Benign: the `not ref["needs_rule_review"]` guard at implementation/clock_ops.py:64 is unreachable in practice (a `rule_code` can be superseded only once, and that cascade is the flag's only setter) — harmless defensive code, no behavioral impact.

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_3478_municipal_rulemaking_disclosure_portal_dealer_compliance/workspace/PRD_COMPLETED.md`

**Orchestrator verification** (independent): PRD_COMPLETED.md = 302 lines with 36 changed lines vs PRD_FINALIZED.md (18 old ↔ 18 new, matching the report); spot-checked pin `version: 1` confirmed at routes/organizations.py:59; no .py source in implementation/, test_suite/, or test_helpers/ is newer than the final sweep's results files (Step 9 touched only PRD_COMPLETED.md — no re-sweep required); all 8 results.{i}.json intact at 94/94.
