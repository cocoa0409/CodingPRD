## Step 1: Create task directory — 2026-10-01T12:57:28.934314176Z

Pre-allocated task directory ./tasks/task_3386_case_screening_evidence_testing_requests_exoneration_support/ verified present with workspace/ inside; no new index computed and no other task_* directory created.
## Step 2: Generate scaffold — 2026-10-01T14:40:17.595573526Z

All three artifacts are generated, parse cleanly, and pass the mechanical lint with a clean verdict.

## Report

**Output files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3386_case_screening_evidence_testing_requests_exoneration_support/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys): 13 entities, 10 state machines, 9 calculations, 13 priority-ordered validation rows, 50 endpoints, 50 errors, 8 roles, 2 OCC concurrency rules
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, all 9 rules × 2 instances = 18, each with a full structured `test_recipe`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 71 instances (60 active recipes across all 9 claim-guide sections + 11 `excluded_because` stubs)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1125 calls scanned, 0 violations.)

**Difficulty mechanics** (beyond-expert per the directive): dual-variant calcs on two domains (compensation PROVISIONAL 50000000 vs FINAL_VERIFIED 71250000; screening STANDARD 66.55 vs EXPEDITED 71.07 — all literals pre-computed in Python, including a genuine 66.55-vs-66.54 rounding-order divergence found by search); combinatorial modes (a) tiered-cap-fee ordering and (b) pinned per-factor rounding; cyclic intake/agreement/motion/petition/policy machines + parallel location×testing dimensions on EvidenceItem; a depth-3 cascade (records-response → item → case → policy count) and a depth-2 cascade (DB HIT → exculpatory flag → posture/petition gate); priority conflicts on state-vs-temporal and referential-vs-constraint pairs; boundary checks at exact-equality sample reservation and the ≥3 pattern threshold; two OCC rules; segregation-of-duties on intake decide; jurisdiction feature flags gating motions/clemency/compensation; a logical-clock endpoint (default 2026-09-01T00:00:00Z pinned) driving deadline/sweep/release/window temporal rules.

**Consistency checks run:** forbidden concurrency vocabulary (clean), instance-name uniqueness across both files (89, no dupes), every error id referenced outside its catalog entry, endpoint roles ⊆ declared roles, `entity_backed:Client` identity declared, YAML parsed after every append.

**One risk to flag downstream:** the scaffold declares 50 endpoints — above the ~40 threshold where Step 6 (impl-gen) is known to break *unless* the impl-gen prompt pre-constrains (one file per message, per-domain modules, no-truncation, self-smoke-test). Thirteen of the 50 are trivial sub-resource list GETs required by the lint's FK reverse-reachability check, so effective handler complexity is lower, but the impl-gen step should be pre-constrained accordingly.
## Step 3: Copy shared files — 2026-10-01T14:40:24.587666249Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.
## Step 4: Generate PRD — 2026-10-01T15:04:54.664772238Z

The PRD is complete and verified.

**Delivered:** `/home/ubuntu/github/CodingPRD/tasks/task_3386_case_screening_evidence_testing_requests_exoneration_support/workspace/PRD.md` (361 lines, ~64 KB), generated from the scaffold with deliberate §3 scattering. The two forbidden design files were never opened.

**Structure:**
- §1 Introduction — 2 paragraphs (domain pipeline + system guarantees)
- §2.1–2.10 — roles with per-role identity translations (`Client` is entity-backed, seven staff roles opaque), verbatim §2.2 envelope, pagination (limit 10/1/100, offset 0, `created_at` ascending), the logical clock (mandatory default `2026-09-01T00:00:00Z`, no wall-clock fallback), common resource properties, derived-state/cascade discipline (chains A and B named), the two OCC rules, jurisdictional statute flags, full 13-level validation priority order with the (a)–(g) domain-constraint sub-order, and pinned precision rules
- §3.1–3.9 — intake/screening (both scoring profiles with the 66.55/71.07 worked anchors), decide + segregation of duties + waitlist selector, evidence/records (two independent EvidenceItem dimensions, per-item reveal legality), agreement-vs-motion testing lifecycles, lab analyses with the sample-ledger conservation invariant, litigation deadlines + exoneration cascade, contact sweep + release checklist, compensation (both worked anchors: 71,250,000 and the cap-bites 62,500,000), reentry capacity + policy pattern threshold
- §4 — 50-row endpoint table (Method/Path/Description/Authorized Roles only)
- §5 — 50-row error table (Error ID/HTTP Status only); file ends there, no audit footer

**Hard contract reports:**

```
Field coverage check:
- entities[].fields: 104 required, 104 present, 0 missing
- endpoints[].request_body/input: 88 required, 88 present, 0 missing (includes query params)
- endpoints[].query_params: covered within the 88 (status, client_id, jurisdiction_id,
  location_status, testing_status, kind, petition_type, provider_id, limit, offset)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 13 checked, 13 expressed in §2.9 ordered prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint capability + expected_case_version/expected_testing_authorization_version + ERR_STALE_VERSION/ERR_STALE_AUTHORIZATION_VERSION + 412), 0 missing
- state_machines[].transitions: all 10 machines walked — every from/to pair, precondition error_id, and side effect expressed, including kind-conditional illegality and the no-direct-advance-into-EXONERATED rule, 0 missing
- calculations[]: 9 checked, 9 fully expressed with constants in business context (30-year saturation, 5-ng minimum, interval map 90/90/60/30/14, threshold 3, tier rates and fee cap), 0 missing
- validations[] conditions: 13 checked, 13 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 50 checked, 50 expressed (both cascade chains, slot accounting, score freezing, sweep outputs), 0 missing
- entities[].fields[] structured content: defaults and null-until-event semantics placed (a §2.6 convention sentence covers the 18 event-stamped fields), 0 missing
- sibling-branch symmetry: decide/response/ruling/claim-decision sibling sets rendered at equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 675
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional mechanical checks: all 50 scaffold error IDs appear in backticks in the PRD; all 50 endpoint paths appear in §4; §4 and §5 tables each have exactly 50 data rows; §2.2 matches the canonical `section-2.2-response-structure.md` byte-for-byte (verified via diff).
## Step 5a: Generate frozen test helpers — 2026-10-01T15:47:51.152334501Z

Step 5a is complete. All nine helper files are written, compile clean, import as one package, and the full composite-fixture graph was validated by walking it against a transition-checked in-memory stub (13/13 walks passed, with the stub independently re-deriving every pinned number from the PRD formulas).

## Files written (all under `.../test_helpers/`)

| File | Lines | Public API surface |
|---|---|---|
| `types.py` | 620 | `UserRole` (8 roles) + 36 domain enums (statuses, events, vocabularies: `IntakeStatus`, `CaseStatus`, `LocationStatus`, `TestingStatus`, `TestingAuthorizationStatus`, `LabAnalysisStatus`, `PetitionStatus`, `ClaimStatus`, `ReferralStatus`, `PolicyStatus`, per-endpoint advance-event enums, etc.) + 13 entity TypedDicts (`Jurisdiction`, `Client`, `IntakeRequest`, `Case`, `EvidenceItem`, `RecordsRequest`, `TestingAuthorization`, `LabAnalysis`, `LegalPetition`, `CompensationClaim`, `ReentryProvider`, `ReentryReferral`, `PolicyInitiative`). All entities carry `id/created_at/updated_at/version` (scaffold has `common_fields: true` on all 13). |
| `api_client.py` | 283 | `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint — 50 methods: `set_clock`, `run_contact_overdue_sweep`, `create_/get_jurisdiction`, `list_jurisdiction_policy_initiatives`, `create_/get_client`, `create_/list_/get_intake_request`, `advance_intake_request`, `submit_intake_supplement`, `decide_intake_request`, `activate_waitlist_next`, `list_intake_request_cases`, `get_/update_/advance_case`, `log_case_contact`, 6 case sub-resource listers, `create_/get_/advance_evidence_item` + 2 item sub-listers, `create_/advance_records_request`, `create_/get_/advance_/amend_testing_authorization` + TA lab lister, `create_/advance_lab_analysis`, `create_/advance_legal_petition`, `create_/advance_compensation_claim`, `create_/get_reentry_provider`, `list_reentry_provider_referrals`, `create_/advance_reentry_referral`, `create_/advance_policy_initiative`; plus the `api_client` singleton. |
| `api_errors.py` | 124 | `ApiErrorId` enum + `HTTP_STATUS_CODES` for all 50 PRD §5 error ids (matches the §5 table exactly), registered via `set_error_http_status_map` at import. |
| `assertions.py` | 397 | `validate_created` (explicit 201 — never lets `validate_success`'s 200 default wrap a create), `validate_ok`, `assert_common_fields`, `assert_optional_timestamp`, `assert_score_2dp`, `assert_integer_cents`, 13 `assert_<entity>` functions, and invariant checkers `assert_sample_ledger_conservation`, `assert_new_case_defaults`, `assert_contact_interval_matches_status`, `assert_slots_in_use_consistent`. |
| `factories.py` | 429 | 13 `create_*_payload` factories (input fields only; optionals omitted unless supplied, so server defaults/nulls are exercised) + event payload builders (`intake_advance_payload`, `decide_payload`, `case_advance_payload` with the PRD's `housing_arranged`/`id_documents_ready`/`transportation_arranged` key names, `records_advance_payload` + `revealed_item`, `authorization_advance_payload`, `amendment_payload`, `lab_advance_payload`/`lab_result_payload`/`expert_interpretation_payload`/`db_comparison_payload`, `petition_advance_payload`, `claim_advance_payload`, `referral_advance_payload`, `policy_advance_payload`, `case_update_payload`, `log_contact_payload`, `clock_payload`, `submit_supplement_payload`). Intake defaults use the PRD's anchor screening inputs (STRONG/LIKELY_STORED/7y/CRITICAL). Unknown override keys pass through deliberately (supports unknown-field rejection tests). |
| `constants.py` | 154 | See literal list below. |
| `test_users.py` | 121 | `TEST_USERS` with header constants for all 8 roles; `make_client_headers(client_id)` (Client is entity-backed — the builder is mandatory for ownership-gated calls; the shared `client_headers` constant is documented as non-ownership fallback only); `make_*_headers(user_id)` for all 7 opaque staff roles; canonical opaque ids (`INTAKE_SPECIALIST_ID="spec_1"`, `MANAGING_ATTORNEY_ID="ma_1"`, `STAFF_ATTORNEY_ID="atty_1"`, plus second/third specialists and a second attorney for multi-actor recipes); malformed-header builders (`headers_without_user_id/role`, `headers_with_empty_*`, `headers_with_undeclared_role`, `UNDECLARED_ROLE`). |
| `fixtures.py` | 912 | Tier-1 primitives (all creates/advances/reads, `set_clock`, `run_contact_overdue_sweep`, `sign_agreement`, `grant_motion`, `ship_sample`, `record_result`, `run_database_comparison`, `file_petition`, `record_petition_decision`, `file_claim`, `record_claim_decision`, `record_claim_payment`); ctx extenders (`add_evidence_item`, `add_effective_authorization`, `add_lab_analysis`, `advance_case_to`, `record_result_on_ctx`) for multi-item hybrid worlds; composites: `setup_intake_pipeline` (with `jurisdiction_id`/`client_id` reuse for multi-case worlds), `setup_accepted_case`, `setup_waitlisted_request`, `setup_case_in_investigation`, `setup_case_with_item`, `setup_effective_authorization`, `setup_case_in_testing` (kind=AGREEMENT or MOTION), `setup_lab_analysis_scheduled`, `setup_lab_result_recorded` (optional `db_hit`), `setup_case_in_litigation`, `setup_exonerated_case` (optional `exoneration_clock` set between FILE and RECORD_DECISION), `setup_submitted_records_request`, `setup_case_with_records_reveal` + `setup_case_with_destroyed_evidence`, `setup_policy_initiative`, `setup_release_ready_case`, `setup_compensation_claim_filed/approved`, `setup_reentry_referral_pending`. All composites keep recommender/decider X-User-IDs distinct (segregation of duties) and use `get_success_data` so failures surface as "Setup step failed". |
| `__init__.py` | 309 | Barrel export: framework generics (`validate_success/error/paginated`, `run_race`, `NON_EXISTENT_UUID`, etc.) + explicit re-export of the full PRD-specific surface (295 names). |

No `test_suite/`, `conftest.py`, or `test_*.py` was created anywhere in the task directory.

## Frozen literals in constants.py (each grep-verified against PRD prose)

- `CLOCK_DEFAULT = "2026-09-01T00:00:00Z"` — §2.4
- Screening (§3.1): `CLAIM_STRENGTH_POINTS` 25/55/80/95; `EVIDENCE_POTENTIAL_POINTS` 0/35/65/95; `HEALTH_URGENCY_POINTS` 0/45/90; `YEARS_SATURATION = 30` ("saturates at thirty years"); `WEIGHTS_STANDARD` 0.425/0.275/0.185/0.115; `WEIGHTS_EXPEDITED` 0.260/0.240/0.155/0.345; anchors `ANCHOR_SCORE_STANDARD = 66.55`, `ANCHOR_SCORE_EXPEDITED = 71.07`, `ANCHOR_TIME_FACTOR = 23.33`, part tuples (34.00/17.88/4.32/10.35) and (20.80/15.60/3.62/31.05)
- Compensation (§3.8): `FLAT_RATE_CENTS_PER_YEAR = 5_000_000`; `TIER1_YEARS = 5`; `TIER1_RATE_CENTS = 5_000_000`; `TIER2_RATE_CENTS = 7_500_000`; `FEE_REIMBURSEMENT_CAP_CENTS = 2_500_000`; `DAYS_PER_YEAR = 365`; anchors `ANCHOR_CONVICTION_DATE = "2016-03-15T00:00:00Z"`, `ANCHOR_EXONERATION_CLOCK = "2026-11-20T00:00:00Z"`, `ANCHOR_VERIFIED_DAYS = 3902`, `ANCHOR_VERIFIED_YEARS = 10`, `ANCHOR_PROVISIONAL_CENTS = 50_000_000`, `ANCHOR_TIERED_BASE_CENTS = 62_500_000`, `ANCHOR_ENHANCED_BASE_CENTS = 68_750_000`, `ANCHOR_FINAL_AWARD_CENTS = 71_250_000`, `ANCHOR_CAPPED_FINAL_AWARD_CENTS = 62_500_000`, caps 100_000_000 / 60_000_000, enhancement 10, fees 3_000_000
- `MIN_TESTABLE_NG = 5` — §3.5 ("at least 5 nanograms")
- `CONTACT_INTERVAL_DAYS` 90/90/60/30/14, CLOSED→None — §3.7; `CLOCK_DEFAULT_PLUS_90D = "2026-11-30T00:00:00Z"` and `+91D = "2026-12-01T00:00:00Z"` (derived; match the corner recipe's own literals)
- `POLICY_PATTERN_THRESHOLD = 3` — §3.9 ("at least 3")
- Pagination 10/1/100/0 — §2.3

No unused scaffold-valued constants were left behind — every constant maps to PRD prose (verified by literal grep above).

## Clock-reachability audit (design recipes vs the 2026-09-01T00:00:00Z default)

Every date-bearing recipe in both design indices either uses the default clock or calls `set_current_utc` before the gated operation. Two instances set the clock **backward** from the default (2023-*), via explicit endpoint calls:

- `Difficulty/priority_pair_validation_conflict/petition_file_state_error_precedes_deadline_error` — sets 2023-04-01, then 2023-05-01, then 2023-07-01 (deadline 2023-06-01).
- `Corner/calculations/petition_deadline_equality_timely_and_excess_rejected` — sets 2023-05-01, 2023-06-01 (equality, timely), 2023-06-02 (excess, rejected).

These are reachable **only under the plain-setter reading** of the clock endpoint: PRD §4 describes it as "Set the server's logical clock" with no monotonicity constraint, though §2.4's verb is "advance". Neither the fixtures nor constants bake any 2023 date — tests pass them to `set_clock()` directly. All other recipe dates (2026-10-15, 2026-11-20, 2026-11-30, 2026-12-01T08:59:59/09:00, 2027-01-01, 2027-02-01, 2027-02-28, 2027-03-01, 2027-03-02) are forward of the default; conviction dates in payloads (e.g. 2016-03-15) are data, not clock reads, and are unaffected.

One sequencing detail Step 5b should know: `setup_exonerated_case(exoneration_clock=...)` sets the clock between petition FILE and RECORD_DECISION, matching the design recipes exactly; the compensation anchors (3902 days → 10 verified years → 50,000,000 provisional / 71,250,000 final / 62,500,000 cap-bites) were reproduced end-to-end through this fixture path in the validation walk.
## Step 5b: Generate test suite — 2026-10-01T16:40:33.154520268Z

All checks pass. The pyflakes output shows only unused imports (cosmetic, all resolve) — zero undefined names in test bodies, which was the runtime-critical check.

**Step 5b complete.** Generated `test_suite/` for task_3386 on top of the frozen `test_helpers/` (untouched).

**Deliverables**
- 24 test files + `conftest.py` (session-scoped `api` fixture + 8 role-header fixtures), under `/home/ubuntu/github/CodingPRD/tasks/task_3386_case_screening_evidence_testing_requests_exoneration_support/test_suite/`
- **96 tests**: 36 difficulty-tagged (all 18 queue-A instances × exactly 2) + 60 corner-tagged (all 60 non-stub queue-B instances × 1). 11 `excluded_because` stubs not translated (cross-references all resolve to real difficulty instances).

**AST audit (real `ast.parse`, not grep)**
- All 96 test functions carry exactly one `Design:` tag; all 78 distinct tags resolve to real non-stub instances in the YAMLs; no tag points at a stub; no instance is uncovered. Work order remaining: none.
- Citation sweep: 158 rule-bearing quoted spans across all docstrings, each verified to survive a whitespace-normalized literal grep of `PRD.md`. The sweep initially caught 15 non-verbatim spans (markdown bold markers in §2.9 list items, `->` vs `→`, case mismatches) — all fixed and re-verified.

**Collection**: `python3 -m pytest --collect-only test_suite/` → **96 collected, 0 errors** (PYTHONPATH=task root).

**Skips**: none. Every non-stub instance passed the PRD-first two-condition filter. Borderline calls kept with reasoning: (1) jurisdiction null-on-omission defaults — PRD pins "null means uncapped / no deadline" semantics with no other write pathway, so omission→null is the only consistent reading; (2) waitlist `created_at` tie-break under the frozen logical clock — all creates share one timestamp, and since PRD §3.2 explicitly bans `id` from the tie-break, stable insertion order is the only PRD-legal deterministic resolution; (3) `facility_name` null on omission per the §2.6 null-until-stamped convention.

**Recipe handling notes**
- The two 2023-clock recipes (petition deadline pair) call `set_clock` directly in-test, per the fixture design; compensation anchors use `setup_exonerated_case(exoneration_clock=...)` with `db_hit=True` where the enhancement gate needs the flag.
- All asserted-201 create triggers use raw `api_client` + `validate_created` (fixture `get_success_data` is status-lenient); error triggers use `validate_error` with the registered HTTP-status map.
- No race instances exist in either index (OCC instances are sequential), so the race utilities/one-of assertions were not needed.
- No `GET /legal-petitions/{id}` exists; post-rejection petition-state assertions go through the case-scoped list endpoint.

**Helper API gaps**: none — the frozen helpers covered every recipe; no patches were needed or made.

**Orchestrator spot-check:** independently re-ran collection (96 collected, 0 errors) and a from-scratch AST tag audit (96 tests, 0 untagged, 0 bad tags, 78/78 instances covered, 0 uncovered). Subagent claims verified.
## Step 6: Generate implementation — 2026-10-01T17:30:46.299395824Z

Implementation complete and verified. Final report:

## Deliverable

`.../workspace/implementation/` — 23 files, 2913 lines:

| File | Lines | Role |
|---|---|---|
| start.sh | 10 | Guarded pip install (`import flask` check), `exec python3 app.py` on `0.0.0.0:$PORT` (default 10000) |
| requirements.txt | 1 | flask>=2.2,<4 |
| app.py | 75 | Blueprint wiring, ApiError/404/405/500 envelope handlers |
| errors.py | 128 | All 50 error ids with pinned HTTP statuses |
| clock.py | 86 | Logical clock (default `2026-09-01T00:00:00Z`, echoes the exact raw string set) + monotonic 3-fraction wall timestamps for created_at/updated_at/meta |
| db.py | 60 | Empty in-memory dict stores (no seeding), entity factory, touch (version+1/updated_at), lookup→404 |
| envelope.py | 53 | `meta`/`response_type`/`data` envelope, pagination fields in meta |
| auth.py | 58 | X-User-ID/X-User-Role validation, role admission, Client ownership |
| validation.py | 157 | Shape checks (required/type/enum/floor/unknown-field/window), pagination parsing |
| calculations.py | 210 | Screening scores (Decimal, per-product HALF_UP round-then-sum), compensation PROVISIONAL/FINAL_VERIFIED, testing-status derivation, posture, overlap/capacity, pattern counts |
| cascades.py | 95 | Chain A (destruction), chain B (HIT), records/claim denial pattern re-derivation, exoneration cascade |
| routes_ops.py 49 · routes_jurisdictions.py 87 · routes_clients.py 35 · routes_intake.py 266 · routes_cases.py 271 · routes_evidence.py 271 · routes_testing.py 233 · routes_lab.py 224 · routes_petitions.py 156 · routes_compensation.py 137 · routes_reentry.py 155 · routes_policy.py 96 | | Per-domain blueprints |

## Coverage

- **Endpoints: 50/50** (verified by enumerating the Flask url_map against PRD §4).
- **Errors: 50/50** catalogued, each raisable with its pinned HTTP status.
- All 11 state machines (incl. kind-conditional TestingAuthorization, two-dimension EvidenceItem, cyclic intake/records/motion/petition/policy loops), both OCC rules (412s before business logic), validation priority order (auth → role → existence → ownership → OCC → shape → event vocabulary → from-state → cross-entity gates → SoD → referential → temporal → domain a–g), both pinned numeric anchors (screening 66.55/71.07; compensation provisional 50000000, final 71250000 with cap-before-fees), and all four policy pattern topics.

## Self-smoke-test

Booted via `bash start.sh` on a dynamic free port (socket-allocated, never hardcoded), ran a 93-assertion cross-domain chain (auth errors → jurisdiction + duplicate 409 → client → intake → screening anchors → SoD 403 → decide+Case creation with default-clock `last_contact_at` → evidence to CUSTODY_CONFIRMED → case to TESTING → agreement PROPOSE/COUNTER/SIGN + stale-amendment 412 → lab create/ship/result with ledger settle → overlap 409 → insufficient-sample 422 → HIT chain-B cascade → LITIGATION → stale-PUT 412 → petition FILE/GRANTED+vacates → exoneration cascade → compensation anchors → release checklist/date gate → records DENIED/appeal/DESTROYED chain-A → policy threshold 409 → provider capacity + endpoint-touching window → sweep + log-contact → pagination envelope → Client ownership 403s). **All 93 checks green.** Two fresh boots verified pristine (empty stores), server killed by exact PID both times, clean shutdown confirmed.

The smoke test caught and I fixed two real bugs: lab-create derived `testing_status` before inserting the analysis (never reached SAMPLE_RESERVED), and RECORD_RESULT's `if refund or refresh(...)` short-circuited derivation on any refund.

## PRD ambiguities resolved

1. **created_at/updated_at/meta timestamps → wall clock** (logical clock governs §3 business timestamps; the waitlist tie-break note "equal timestamps impossible in practice" only makes sense with wall-clock distinctness). Business timestamps echo the exact string passed to `set_current_utc`.
2. **Version bumps are change-conditional** on re-derivations (matches the explicit "bump when changed" rules for sweep/policy; chain A's unconditional case bump falls out of `destroyed_evidence_count` always changing).
3. **EvidenceItem.testing_status starts UNTESTED** at creation even when initial_sample_ng < 5 (pinned initial state; derivation runs on later triggers).
4. **EXECUTE_RELEASE with null scheduled_release_date** treats the date gate as satisfied (READY still required).
5. **decide records `decision_reason` from `rejection_reason` on all three branches** (PRD §3.2 prose wins over the scaffold side-effect list omitting it on WAITLISTED).
6. **Fulfilling RECORD_RESPONSE requires items_revealed present** (empty array allowed); DENIED requires absent/empty.
7. **RUN_DATABASE_COMPARISON HIT requires matched_subject_name** (missing → ERR_INVALID_REQUEST).
8. **Out-of-range limit/offset → ERR_INVALID_REQUEST** rather than clamping.
9. **Cross-FK mismatch (item not on payload case / authorization for another item) is not rejected** — no pinned error id exists; gates evaluate per the spec's stated paths.
10. **POST_CONVICTION deadline = calendar-year anniversary at 00:00:00 UTC**, equality timely; Feb 29 clamps to Feb 28.
11. **log-contact allowed in any case status** (no gate specified in PRD/SCAFFOLD).
12. **verified_years clamped at ≥ 0** against pathological date ordering.

Orchestrator spot-check: all 23 files compile clean; grep confirms zero references to test_suite/, test_helpers/, or either design YAML inside implementation/.
## Step 7: Run tests and iterate — 2026-10-01T17:45:22.271726610Z

All 8 rounds pass clean, 96/96 each, and `results.1.json`–`results.8.json` are in place under `workspace/implementation/`.

**Summary**

- **Iterations run:** 2 (first sweep: 94/96 in all 8 rounds, two deterministic failures; second sweep after fixes: 96/96 × 8 rounds).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:**
  - `fixtures.py` — `setup_case_with_records_reveal`: added the missing `jurisdiction_overrides` keyword and forwarded it to `setup_accepted_case`. It was the only mid-level fixture with an explicit signature that blocked a parameter `setup_intake_pipeline` already supports; every peer fixture forwards `**kwargs`. Fixed `test_posture_exculpatory_precedence_over_compromised` (TypeError on a PRD-consistent request).
- **Fixes applied to `test_suite/`:**
  - `test_18_security_rbac.py` — `test_clock_set_requires_platform_admin`: kept the PRD-covered RBAC assertion (non-admin set → `ERR_UNAUTHORIZED_ROLE`, passing), replaced the non-uniquely-derivable tail `jurisdiction["created_at"].startswith(CLOCK_DEFAULT)` with `ctx["case"]["last_contact_at"] == CLOCK_DEFAULT` via `setup_accepted_case`. Why: §2.4's logical-clock rule scopes its catch-all to "every other business timestamp described in §3", while `created_at` is a §2.5 system-managed field that §2.5 requires to carry *three fractional digits* — so the old assertion was unsatisfiable by any §2.5-faithful implementation (a logical-clock rendering `2026-09-01T00:00:00.000Z` still fails the `Z`-terminated prefix). The new assertion traces verbatim to §3.1 ("`last_contact_at` set to the current logical clock") + §2.4 ("reads exactly `2026-09-01T00:00:00Z`"). The wall-clock reading for `created_at` is independently confirmed PRD-admissible by `test_05_waitlist`'s tie-break, which needs distinct `created_at` values with no clock set.
- **Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful on both paths; both failures were test-artifact bugs.

Orchestrator verification: all 8 `results.*.json` files present; each reports passed=96, total=96, failed=0.
## Step 8: Finalize PRD — 2026-10-01T17:51:27.772814187Z

The diff is minimal and complete. Both edits verified consistent against every enumerated implementation path.

## Summary

**Line counts:** PRD.md 361 → PRD_FINALIZED.md 363 (+2 lines, +0.55%).

**Step 7 item disposition:**
- `test_helpers/fixtures.py` `jurisdiction_overrides` kwarg — pure fixture-plumbing bug (PRD does not govern test helper signatures). No PRD edit.
- `test_18_security_rbac.py` clock assertion — revealed genuine PRD silence at the §2.4/§2.5 boundary: §2.4's head clause "All timestamps the server writes" admitted a universal reading covering `created_at`, while §2.5's three-fractional-digit format is unsatisfiable from the logical clock's default rendering `2026-09-01T00:00:00Z`. Implementation splits the sources: business timestamps from the logical clock, system timestamps from a monotonic wall clock. Pinned with two edits.

**Changes (one bullet each):**
- §2.4 — revise — changed "All timestamps the server writes" to "All business timestamps the server writes" and added a sentence stating the logical clock does not feed §2.5 `created_at`/`updated_at` or §2.2 `api_request_timestamp`, which are wall-clock-rendered ISO 8601 UTC with three fractional digits — implementation/clock.py:70-86, implementation/db.py:34-46, implementation/envelope.py:20
- §2.5 — insert — added closing sentence "`created_at` and `updated_at` are read from the server's wall clock, never from the logical clock of §2.4." — implementation/db.py:34-46

**Per-edit pre-edit search log:**

Edit 1 (§2.4):
- (a) Subject: source clock (logical vs wall) for every category of server-written timestamp.
- (b) Paths enumerated/read: `clock.py` (full read — `LogicalClock.stamp()` echoes raw string, `wall_now_iso()` is the sole wall source); `db.py` (full read — `new_entity`/`touch` write `created_at`/`updated_at` from wall for all 13 entity stores); `cascades.py:37,50,58,73,95` (all cascade mutations via `touch` → wall); `envelope.py:20` (`api_request_timestamp` wall); business stamps `routes_intake.py:220`, `routes_cases.py:206` (`last_contact_at`), `routes_petitions.py:133,139` (`filed_at`/`decided_at`), `cascades.py:92` (`exoneration_date` via stamp param from `routes_petitions.py:144`); `routes_ops.py:23` (`current_utc` echo, not an entity timestamp); greps for `datetime.now`/`strftime`/`isoformat` and all `"*_at"` fields confirmed no other writers. Client-supplied datetimes (`conviction_date`, `scheduled_release_date`, `service_start`/`end`) excluded as not server-written.
- (c) Adjustment: draft said "in the three-fractional-digit format of §2.5", widened to "as ISO 8601 UTC with three fractional digits" because `api_request_timestamp`'s format is pinned in §2.2, not §2.5 — citing §2.5 for it would mis-scope.

Edit 2 (§2.5):
- (a) Subject: same clock-source split, pinned at the field-definition site an implementer reads when writing `created_at`/`updated_at`.
- (b) Paths enumerated: same set as Edit 1; specifically re-confirmed no path (creation, mutation, or any of the five cascade `touch` sites) ever writes these two fields from `CLOCK`.
- (c) No adjustment needed; sentence asserts only source, leaves format to the existing bullets and monotonicity unpinned (under-determined, outside Step 7 scope).

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the two described edits and nothing else; no implementation/*.py file is newer than the Step 7 sweep results, so the green 8-round sweep remains valid.
## Step 9: Complete PRD — 2026-10-01T18:17:14.723695057Z

Done. `PRD_COMPLETED.md` is produced at `.../workspace/PRD_COMPLETED.md`. Only that file was created/edited; `implementation/`, `test_helpers/`, `test_suite/`, `PRD.md`, `PRD_FINALIZED.md` are untouched.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 363 lines / 65,275 chars → `PRD_COMPLETED.md` 363 lines / 71,875 chars (**+6,600 chars, +0 lines** — every change is an in-paragraph insert or inline revision; no new sections or paragraphs).

**Counts:** 27 changes total — **23 ambiguity-pins, 4 mismatch-revisions**.

### Changes (one per edit)

- **§2.3** — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400) — `implementation/validation.py:125-146`
- **§2.3** — insert — ambiguity — `has_more` defined as `offset + returned < total_count` — `implementation/envelope.py:43-53`
- **§2.4** — revise — ambiguity — clock retains the supplied string verbatim; `current_utc` and all clock-stamped business timestamps echo it — `implementation/clock.py:49-61`, `implementation/routes_ops.py:16-23`
- **§2.5** — insert — ambiguity — response `data` carries exactly the entity's stored fields, no more/no fewer — `implementation/envelope.py:24-28`, all `routes_*.py` returning entity dicts
- **§2.6** — insert — ambiguity — change-conditional touch discipline: no stored-value change → no `version`/`updated_at` bump; multi-field mutations bump once per field (CONFIRM_CUSTODY can bump an item twice) — `implementation/cascades.py:26-50`, `implementation/routes_evidence.py:133-140`
- **§2.6** — revise — ambiguity — null-until-supplied convention extended to optional creation fields (`facility_name`, `terms`, `proposed_test_types`, `strategy_notes`, `theory_of_case`, `assigned_attorney_id`, `supplement_notes`, `scheduled_release_date`) — `implementation/routes_intake.py:93-104`, `implementation/routes_cases.py:210-230`, etc.
- **§2.7** — insert — ambiguity — expected-version field is required and integer; missing/non-integer → `ERR_INVALID_REQUEST`; a well-formed stale value → 412 ahead of remaining shape checks — `implementation/routes_cases.py:69-82`, `implementation/routes_testing.py:194-209`
- **§2.8** — insert — ambiguity — jurisdiction registration: `state_code`/`name`/three boolean flags required; `post_conviction_deadline_years` (≥1) and `compensation_cap_cents` (≥0) optional-nullable; `actual_innocence_enhancement_pct` optional int 0–100, explicit null rejected — `implementation/routes_jurisdictions.py:42-52`
- **§2.9 step 3** — revise — ambiguity — body-id existence checked only when the key is present; a non-string id resolves to the same 404 as an unknown id — `implementation/db.py:49-60`, `implementation/routes_intake.py:60-63`
- **§2.9 step 6** — insert — ambiguity — explicit null on a required field treated as missing; optional fields reject explicit null except the declared-nullable set (`post_conviction_deadline_years`, `compensation_cap_cents`, `vacates_conviction`, non-HIT `matched_subject_name`, DENIED `items_revealed`) — `implementation/validation.py:30-33,98-122`
- **§2.9 step 7** — revise — **mismatch** — advance-endpoint check interleave pinned: unknown-fields → event presence/type → event vocabulary → event-specific shape; an unknown event wins over a malformed event-specific field — `implementation/routes_intake.py:134-141`, `implementation/routes_cases.py:95-113`, `implementation/routes_lab.py:135-165`
- **§3.1** — revise — **mismatch** — submit-supplement open to "any `IntakeSpecialist`" (was "the assigned specialist"; no assignment exists on intake requests) — `implementation/routes_intake.py:170-185`
- **§3.2** — revise — ambiguity — `rejection_reason` recorded as `decision_reason` on every decision branch, null when absent — `implementation/routes_intake.py:203-207`
- **§3.2** — insert — ambiguity — decide response returns the updated intake request; the case is read via `accepted_case_id`/case list — `implementation/routes_intake.py:242-243`
- **§3.2** — insert — ambiguity — frozen `waitlist_priority_score` retained through re-entry; re-frozen by a later WAITLISTED decision, never cleared by a non-WAITLISTED one — `implementation/routes_intake.py:237-241,255-258`
- **§3.3** — revise — **mismatch** — new EvidenceItem's `testing_status` starts `UNTESTED` even below the 5 ng testable minimum; the pure derivation governs only from the first re-derivation trigger — `implementation/routes_evidence.py:80-81` vs `implementation/calculations.py:97-110`
- **§3.3** — revise — ambiguity — `items_revealed` rules pinned: required array (may be empty) on fulfilling responses; entries have exactly `evidence_item_id`+`disposition`; reveals may reference any existing item (no same-case constraint), item-existence checked post-shape/pre-from-state; whole sequence pre-simulated atomically; DESTROYED cascades on the item's own case, LOCATED/MISSING re-derive the records request's case; DENIED accepts absent/null/empty — `implementation/routes_evidence.py:186-208,229-268`
- **§3.4** — insert — ambiguity — `proposed_test_types` must be an array of §3.5 test-type vocabulary entries — `implementation/routes_testing.py:49-56`
- **§3.5** — revise — ambiguity — `matched_subject_name` required on HIT; non-null on NO_HIT/PARTIAL is `ERR_INVALID_REQUEST`; explicit null tolerated and ignored; each comparison rewrites `db_matched_subject_name` (null on non-HIT) — `implementation/routes_lab.py:157-165,209-211`
- **§3.6** — insert — ambiguity — case-update admitted on a case in any status, working or terminal — `implementation/routes_cases.py:64-87`
- **§3.6** — revise — ambiguity — POST_CONVICTION deadline pinned to the instant 00:00:00 UTC on the calendar anniversary, Feb-29 clamping to Feb-28 in non-leap target years; instant-vs-instant comparison — `implementation/calculations.py:202-210`, `implementation/routes_petitions.py:120-132`
- **§3.6** — revise — ambiguity — `vacates_conviction` defaults to false when omitted or null — `implementation/routes_petitions.py:104-108`
- **§3.7** — insert — ambiguity — log-contact admitted on a case in any status including CLOSED; `channel`/`summary` validated but never persisted — `implementation/routes_cases.py:197-211`
- **§3.7** — revise — ambiguity — `scheduled_release_date` must be a valid ISO 8601 timestamp when its key is present — `implementation/routes_cases.py:113,174-175`
- **§3.7** — revise — ambiguity — a null stored `scheduled_release_date` passes the EXECUTE_RELEASE date gate vacuously — `implementation/routes_cases.py:188-191`
- **§3.8** — revise — ambiguity — `verified_years` computed from UTC calendar-date difference, clamped at zero, floor-divided by 365 — `implementation/calculations.py:82-85`
- **§5** — revise — **mismatch** — catalogue scoped to domain errors; framework-level `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL_ERROR` (500) documented — `implementation/app.py:53-70`

All flagged interpretation choices (OCC version handling, initial EvidenceItem `testing_status`, null `scheduled_release_date` gating, `items_revealed` presence rules, `matched_subject_name` requirement, limit/offset rejection, Feb-29 anniversary clamp, log-contact gating, `verified_years` clamping) now trace to explicit PRD_COMPLETED.md prose.

Orchestrator verification: PRD_COMPLETED.md differs from PRD_FINALIZED.md (real edits, no silent no-op); all 8 sweep results files intact; no impl/helpers/suite source file is newer than the sweep, so the 96/96 × 8 evidence remains valid.
