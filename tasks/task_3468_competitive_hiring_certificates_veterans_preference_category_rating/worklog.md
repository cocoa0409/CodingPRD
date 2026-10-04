# Worklog — task_3468_competitive_hiring_certificates_veterans_preference_category_rating

## Step 1: Create task directory — 2026-10-02T10:42:00.000Z

Task directory pre-allocated by caller: `./tasks/task_3468_competitive_hiring_certificates_veterans_preference_category_rating/` with `workspace/` inside. Verified existence; no new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T12:53:00.000Z

All checks pass. The scaffold package is complete and verified.

## Summary

Generated the scaffold for task_3468 (OPM competitive hiring certificates, veterans preference, category rating) purely from the scenario + skill spec — no sibling tasks consulted. Calibrated harder than Expert: the difficulty is concentrated in cross-entity coupling (preference ordering vs. category tiers, segregation-of-duties onboarding chain, lazy clock-driven expiries) rather than raw size.

**Output files (all parse cleanly):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3468_competitive_hiring_certificates_veterans_preference_category_rating/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3468_competitive_hiring_certificates_veterans_preference_category_rating/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — `scaffold_difficulty_design:` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_3468_competitive_hiring_certificates_veterans_preference_category_rating/SCAFFOLD_CORNER_DESIGN.yaml` — `scaffold_corner_design:` (§1.9)

**Counts:** 15 entities · 55 endpoints · 9 state machines · 10 calculations · 42 validation rows · 42 error codes · 9 roles · §1.8: **18 instances** (9 rules × 2, all differentiation clauses honored) · §1.9: **60 active instances + 9 excluded-because stubs** (69 entries).

**Notable design decisions:**
- Dual-variant pair: narrative min-cap vs point-factor grade bands on Position; self-assessed vs SME-certified score on Application (SME formula pins per-component `round_half_up(w·r·6)` then sum — (3,1,1)→79 vs sum-then-round 80).
- Distinct interval semantics per Rule 8: half-open announcement periods (adjacency allowed) vs closed certificate windows (adjacency conflicts at `issued_at == prior expires_at`).
- Veterans preference: CPS float tops its category, preference group beats raw score within a category, categories always derive from raw scores; pass-over flow with PENDING-block (priority-5 roster posture, disambiguated from the p7 preference gate), APPROVED/DENIED adjudication by OPMDelegate.
- Two true-race OCC rules (position reclassification, certificate extension) with `expected_*_version` placeholders throughout; one `/_clock/set_current_utc` test-driving endpoint with the mandated `2026-09-01T00:00:00Z` default.
- Caught and fixed during authoring: removed unreachable ERR_OFFER_ALREADY_EXISTS (dead code), added the missing Appeal state machine, pinned ERR_ACTIVE_CERTIFICATE_EXISTS precedence over window-overlap, pinned respond-expiry evaluation order (TENTATIVE+past-due → ERR_OFFER_RESPONSE_EXPIRED; non-TENTATIVE → ERR_OFFER_NOT_ACTIONABLE), and re-scoped certificate auto-CLOSED to roster exhaustion so the vacancy-conservation invariant instance stays reachable.

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(55 endpoints, 15 entities, 18 §1.8 + 60 §1.9 instances, 1500 calls scanned, 0 violations.) Mechanical cross-checks additionally confirmed: unique instance names across both files, all grounds resolve, all 42 errors are named by at least one instance, stub citations point at real §1.8 instances, and no forbidden concurrency vocabulary appears anywhere.

Orchestrator verification: all three files exist and parse via `yaml.safe_load`; SCAFFOLD.yaml contains §1.0–§1.7 keys with no design keys leaked; api_prefix `/hiring`; 15 entities all domain-appropriate (OccupationalSeries, Position, JobAnnouncement, Applicant, EligibilityDocument, Application, Assessment, Certificate, CertificateEntry, PassOverRequest, Offer, SuitabilityReview, SecurityClearance, Appeal, Appointment).

## Step 3: Copy shared files — 2026-10-02T12:55:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T13:05:00.000Z

All contracts pass. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3468_competitive_hiring_certificates_veterans_preference_category_rating/workspace/PRD.md` — 320 lines.

**Constraint compliance:** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point. No servers were started; no processes touched.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (byte-identical to the canonical verbatim block) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Optimistic Concurrency Control · 2.7 Validation Order · 2.8 Nested Resource Retrieval · 2.9 Two Interval Semantics (half-open open-periods vs closed certificate windows) · 2.10 Precision and Rounding · 2.11 Cascades and Derived Consistency
- §3 Business Logic (9 subsections): 3.1 Series & Classification · 3.2 Announcements & Cancellation · 3.3 Applicants, Documents, Preference · 3.4 Submission & Screening · 3.5 SME Assessment · 3.6 Certificate Issuance & Ranking · 3.7 Certificate Lifecycle · 3.8 Selection, Pass-Over, Offers · 3.9 Suitability, Clearance, EOD, Appeals
- §4 Endpoint Definitions (4-column table), §5 Error Code Catalogue (2-column table)

**Scaffold coverage confirmation:**
- **15/15 entities** covered in prose with every field named in backticks
- **55/55 endpoints** in the §4 table — method, path, and authorized-role list verified equal to the scaffold programmatically (0 mismatches)
- **9/9 state machines**: all 33 distinct state values present as exact UPPERCASE strings; all transitions expressed with preconditions, error IDs, and side effects (including the asymmetric OPEN-vs-CLOSED cancellation withdraw sets, pool-return cascades, and lazy EXPIRED/OFFER_EXPIRED)
- **10/10 calculations** in precise prose: point-factor bands (all 8) + narrative caps (all 5) with both divergence examples, qualification with pinned evaluation order and equality-qualifies boundary, SME score with per-component round-half-up and both (3,1,1)/(1,3,1) counterexamples, category cuts (95/85 defaults, raw-score rule), rule-of-three roster with whole-category merging, CPS-float ranking with `submitted_at` tie-break, closed-interval expiry (max 2 extensions, 1–30 days), strict 14-day appeal window, 5-day offer window, remaining-vacancies set formula
- **42/42 validations** expressed, including the priority ladder (§2.7) and both explicit orderings (`ERR_ACTIVE_CERTIFICATE_EXISTS` over window-overlap; respond's temporal-before-state rule)
- **42/42 errors** in the §5 table and each one mentioned in §2/§3 prose
- **9/9 roles** with exact spelling and identity translations (Applicant entity-backed with registration nuance; eight opaque roles; SME authorship rule)
- **2/2 OCC rules** (`expected_position_version`, `expected_certificate_version` → `ERR_STALE_VERSION` 412)

**Hard contract reports:**
```
Field coverage check:
- entities[].fields + endpoint inputs/query params: 103 required, 103 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 42 checked, 42 expressed, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint + occ field + error id named), 0 missing
- state_machines[].transitions: 40 checked, 40 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 42 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed, 0 missing
- entities[].fields[] structured content: defaults/nullability/sources reconstructible, 0 missing
- sibling-branch symmetry: all parallel branches (cancel sets, clearance gate levels, areas of consideration, eligibility-doc mappings, appeal grounds) at equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 569
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Orchestrator spot-check: PRD.md is 320 lines; 42 unique `ERR_*` tokens; 55 endpoint table rows; §1/§2.1 prose confirmed on-domain (OPM hiring, 9 roles, RBAC).

## Step 5a: Generate test helpers (Stage 1 of split Step 5) — 2026-10-02T13:25:00.000Z

Step 5a is complete. All nine files are written, syntax-checked, and import-clean. No `test_suite/` or `test_*.py` files were created (that is Step 5b's job).

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_3468_competitive_hiring_certificates_veterans_preference_category_rating/test_helpers/`)

| File | Lines | Contents |
|---|---|---|
| `__init__.py` | 30 | Barrel export: framework generics + all PRD-specific modules |
| `types.py` | 415 | 15 entity TypedDicts (all `common_fields: true` → id/created_at/updated_at/version on each), 9 status enums, 13 domain enums, `UserRole` |
| `api_client.py` | 187 | `ApiClient(GenericApiClient)` with 55 methods — one per PRD §4 endpoint; base URL from `API_BASE_URL` env (framework default), no hardcoded port; clock method correctly targets `/_clock/set_current_utc` **outside** the `/hiring` prefix |
| `api_errors.py` | 98 | `ApiErrorId` enum (42 ids) + `HTTP_STATUS_CODES` map matching PRD §5 exactly, registered via `set_error_http_status_map` at import |
| `assertions.py` | 264 | `assert_{entity}()` ×15, `assert_common_fields`, plus PRD formula helpers: `expected_total_points`, `expected_official_grade`, `expected_provisional_grade`, `expected_sme_score` (Decimal ROUND_HALF_UP per component), `expected_category`, `expected_required_months`, `expected_creditable_months` |
| `factories.py` | 218 | 21 payload factories; unique series_code/announcement_number/email via counter+uuid; default open period 2026-09-05→2026-09-20 (reachable from the 2026-09-01 clock start) |
| `constants.py` | 92 | PRD-verbatim values only (below) |
| `test_users.py` | 82 | Role headers (below) |
| `fixtures.py` | 441 | Composite fixtures, 5 tiers (below) |

## constants.py values (name: value — PRD §)
- `CLOCK_START_ISO: "2026-09-01T00:00:00Z"` — §2.5
- `WEIGHT_KNOWLEDGE: 300, WEIGHT_SUPERVISION: 200, WEIGHT_COMPLEXITY: 250, WEIGHT_IMPACT: 250` — §3.1
- `LEVEL_GRADE_CAP: {1:5, 2:7, 3:9, 4:11, 5:13}` — §3.1
- `GRADE_BANDS: {5:(1000,1599), 7:(1600,2199), 9:(2200,2799), 11:(2800,3399), 12:(3400,3899), 13:(3900,4299), 14:(4300,4699), 15:(4700,5000)}` — §3.1
- `GRADE_MIN: 5, GRADE_MAX: 15` — §3.1
- `SME_WEIGHT_KNOWLEDGE: 0.30, SME_WEIGHT_SKILL: 0.20, SME_WEIGHT_ABILITY: 0.50, SME_SCALE: 6, SME_BASE: 70` — §3.5
- `SME_SCORE_MIN: 76, SME_SCORE_MAX: 100` — §3.5
- `DEFAULT_BQ_CUT: 95, DEFAULT_WQ_CUT: 85, CUT_MIN: 70, CUT_MAX: 100` — §3.2
- `DEFAULT_CERTIFICATE_VALIDITY_DAYS: 60, CERTIFICATE_VALIDITY_MIN_DAYS: 30, CERTIFICATE_VALIDITY_MAX_DAYS: 90` — §3.2
- `RULE_OF_MANY_MIN: 3` — §3.6
- `EXTENSION_MIN_DAYS: 1, EXTENSION_MAX_DAYS: 30, MAX_EXTENSIONS: 2` — §3.7
- `APPEAL_WINDOW_DAYS: 14` — §3.9
- `OFFER_RESPONSE_DAYS: 5` — §3.8
- `PREFERENCE_POINTS_FIVE: 5, PREFERENCE_POINTS_TEN: 10` — §3.3
- `RETURN_REASON_APPEAL_SUSTAINED: "APPEAL_SUSTAINED"` — §3.5/§3.9
- `DEFAULT_LIMIT: 10, MIN_LIMIT: 1, MAX_LIMIT: 100, DEFAULT_OFFSET: 0` — §2.3

No scaffold-only constants (e.g. numeric category ranks 3/2/1) were included — only values a PRD-only reader sees.

## Role-header builders (PRD §2.1)
- `TEST_USERS` shared constants for all 9 roles: `applicant_headers` (fallback only), `hr_specialist_headers`, `hiring_manager_headers`, `sme_headers` ("sme-1"), `selecting_official_headers`, `opm_delegate_headers`, `suitability_reviewer_headers` ("suit-1"), `security_adjudicator_headers` ("sec-1"), `platform_admin_headers`
- `make_<role>_headers(user_id)` for all 9 roles; `make_applicant_headers` is the entity-backed path (X-User-ID == Applicant.id), `make_sme_headers` threads the authorship id for submit/resubmit

## Fixture factories (fixtures.py)
- Clock/plumbing: `set_clock`, `list_entries`
- Tier 1: `create_series`, `create_draft_position`, `classify_position`, `create_classified_position`, `create_announcement`, `open_announcement`, `setup_open_announcement`
- Tier 2: `register_applicant` (Applicant-role self-registration, X-User-ID ignored per PRD), `upload_document`, `verify_document`, `upload_and_verify_document`, `register_verified_preference_applicant` (DD214 for FIVE_POINT; DD214+VA_LETTER for ten-point), `submit_application`, `screen_application`, `setup_application`, `setup_qualified_application`, `setup_ineligible_application`
- Tier 3: `rate_application` (DRAFT→submit→accept with SME authorship), `setup_rated_application`
- Tier 4: `issue_certificate`, `setup_competitive_certificate` (default 100/98/96 all-BQ roster), `setup_unranked_certificate` (DIRECT_HIRE), `setup_pass_over_scenario` (verified-FIVE_POINT rank 1 vs non-preference rank 2)
- Tier 5: `select_entry`, `accept_offer`, `setup_selected_offer`, `setup_accepted_offer`, `record_suitability`, `record_clearance`, `setup_offer_with_favorable_suitability`, `setup_eod_scheduled_offer` (sensitivity-scaled clearance gate), `setup_entered_on_duty`, `file_appeal`
- Default clock choreography (fixture-local, not constants.py): apply 2026-09-10 → issue 2026-09-15 → select 2026-09-16 → accept 2026-09-17 → EOD 2026-09-25 — all monotonically forward from the 2026-09-01 startup and inside the default [09-05, 09-20) open period

## Verification
- `python3 -m py_compile` on all nine files: OK
- `import test_helpers.fixtures` + `import test_helpers` smoke check: OK (59 public client methods, 42 registered errors)
- Formula helpers reproduce the design-index literals exactly: points(2,2,3,2)=2250→grade 9; sme(3,1,1)=79 (pinned per-component rounding); sme(5,5,5)=100; sme(4,4,4)=94; provisional(3,3,3,3)=9 vs official 11; category(95)=BEST_QUALIFIED, category(84)=QUALIFIED
- `__pycache__` removed; directory contains exactly the nine spec'd files

Orchestrator spot-check: nine files present; PRD.md grep confirms SME weights 0.30/0.20/0.50 × scale 6 + base 70 with per-component round-half-up, cuts 95/85 within 70–100, validity 60 within 30–90, 14-day appeal window (strictly-before), 5-day offer window — all matching the constants table above.

## Step 5b: Generate test suite (Stage 2 of split Step 5) — 2026-10-02T13:55:00.000Z

Step 5b is complete. All checks pass. Summary:

## Files generated (12, all under `/home/ubuntu/github/CodingPRD/tasks/task_3468_competitive_hiring_certificates_veterans_preference_category_rating/test_suite/`)

| File | Tests | Contents |
|---|---|---|
| `conftest.py` | 0 | Session `api` fixture + one header fixture per PRD role |
| `test_01_series_and_positions.py` | 8 | series echo/keys, position computed fields, DRAFT null grade, classify/reclassify gates, position OCC, dual-variant grading (Difficulty) |
| `test_02_announcement_construction.py` | 7 | shape rules, duplicate natural keys, authority/method coherence, DRAFT-position gate, double-open, half-open adjacency (Difficulty), fixed startup clock |
| `test_03_application_intake.py` | 6 | duplicate application, open-period bounds, DRAFT-announcement gate, AGENCY_ONLY, SCHEDULE_A verified-doc gate, pagination |
| `test_04_applicants_documents_auth.py` | 6 | NONE-claim defaults, unverified document shape, preference recompute on verify, ownership 403, missing-headers 401, role-before-existence 403 |
| `test_05_screening_qualification.py` | 4 | nested-min qualification (Difficulty), exact-months boundary (Difficulty), substitution-disabled branch, rescreen/premature-assessment 409 |
| `test_06_assessments_scoring.py` | 7 | provisional-vs-certified (Difficulty), pinned rounding order (Difficulty), return-resubmit cycle (Difficulty), wq_cut 85/84 boundary, submit-on-SUBMITTED, second-DRAFT 409, SME authorship 403 |
| `test_07_certificate_issuance_roster.py` | 9 | roster-count boundary (Difficulty), issuance-requires-CLOSED (Difficulty), referral cascade + expiry literals, whole-category merge, CPS/preference ranking, raw-score category rule, expiry date arithmetic, one-ACTIVE rule, closed-interval window adjacency (Difficulty) |
| `test_08_certificate_lifecycle.py` | 6 | RETURNED lockdown, exact-instant expiry, third-extension 422, extend OCC, roster-exhaustion close+fill, SO-cannot-issue 403 |
| `test_09_selection_pass_over.py` | 7 | PENDING block 409, category bypass 422, full pass-over approval flow, target eligibility 422, double adjudication 409, denial preserves gate, vacancy-slot conservation (Difficulty) |
| `test_10_offers_eod.py` | 9 | state-beats-temporal on respond (Difficulty), respond-at-due 409 + cascade, lazy expiry at due instant, second suitability review 409, segregation-beats-duplicate (Difficulty), TOP_SECRET clearance gate (Difficulty), EOD date rules + happy path, DIRECT_HIRE UNRANKED end-to-end, route-level SoD 403 |
| `test_11_cascades_appeals.py` | 9 | suitability-rescission chain (Difficulty), cancel 3-hop cascade (Difficulty), INELIGIBLE→QUALIFIED appeal loop (Difficulty), rated-pool conservation (Difficulty), denied-appeal no-op, exact-deadline lateness, RECEIVED appeal 409, ground/posture mismatch 422, PlatformAdmin 403 |

**Total: 78 tests emitted; 0 skipped.** Every live instance in both indices passed the PRD-first two-condition filter (the errors and consistency_model corner sections are all-stub and correctly generate nothing).

**fixtures.py additions: none.** All 78 instances composed from the frozen Step 5a helpers.

**Two recipe adaptations** (asserted rules unchanged; documented in test comments):
1. `Corner/calculations/certificate_expiry_date_arithmetic` — the recipe places two announcements with identical periods on one position, which PRD §2.9's sibling-overlap rule forbids; I built them on two positions of the same series with interleaved, monotonically advancing clock choreography. Asserted `expires_at` literals (2026-11-14 / 2026-10-30) unchanged.
2. `Corner/cross_cutting_layers/reclassify_stale_version_occ` — the recipe's stale-replay payload (4,4,4,4) computes grade 13, outside the default series span, so per PRD §2.7's ladder (priority 7 range check before priority 10 OCC) a faithful implementation would answer `ERR_SERIES_GRADE_RANGE`, not `ERR_STALE_VERSION`. The stale replay uses in-range factors (2,3,3,2 → grade 9) so OCC is the sole violation; asserted outcome (412, grade stays 11) unchanged.

**Audit (verbatim output):**
```
expected live instances: 78
per-file counts: 8/7/6/6/4/7/9/6/7/9/9 (=78)
emitted tags: 78 (unique 78)
missing instances: []
extra/unknown tags: []
duplicate tags: []
citation failures: 0
AUDIT: PASS
```
The audit also ran a C1 citation check: every `"…"`-quoted span in every docstring's PRD-citation block survives a whitespace-normalized literal grep of `workspace/PRD.md` (0 failures). `python3 -m py_compile test_suite/*.py` passes, and `pytest test_suite/ --collect-only -q` with `PYTHONPATH` set to the task dir reports **78 tests collected, 0 errors**.

Orchestrator independent re-audit: re-parsed both YAMLs (78 live instances) and re-ran the AST tag extraction myself — 78 emitted, 78 unique, missing=[], extra=[], duplicates=[]. Independent `pytest --collect-only` also reports 78 collected, 0 errors.

## Step 6: Generate implementation — 2026-10-02T14:25:00.000Z

All audits pass. The deliverable is complete and verified.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3468_competitive_hiring_certificates_veterans_preference_category_rating/workspace/implementation/`

### Module list (line counts)
| file | lines | role |
|---|---|---|
| `start.sh` | 10 | foreground launcher, guarded pip install, `exec python3 app.py`, `$PORT`/0.0.0.0 |
| `requirements.txt` | 1 | flask |
| `app.py` | 52 | app factory, blueprint registration, ApiError/404 envelope handlers |
| `store.py` | 96 | in-memory dicts (empty at boot, no seeding), logical clock (default 2026-09-01T00:00:00Z), id/seq, ISO-8601 3-fractional-digit formatting |
| `errors.py` | 75 | ApiError + all 42 catalog ids with HTTP statuses |
| `envelope.py` | 50 | `meta`/`response_type`/`data` envelope, pagination meta |
| `auth.py` | 44 | X-User-ID/X-User-Role extraction, 9 declared roles, ownership |
| `validate.py` | 125 | body-shape validation (priority 3), pagination parsing |
| `calc.py` | 157 | grade bands/provisional caps, pinned round-half-up SME score, category mapping, qualification determination, roster selection, ranking |
| `cascade.py` | 146 | remaining_vacancies recompute, auto-FILL/auto-CLOSE, lazy EXPIRED/OFFER_EXPIRED, NOT_SELECTED cascade, cancel cascade |
| `serializers.py` | 102 | per-entity wire dicts |
| `routes_series.py` | 186 | series + positions + classify/reclassify (OCC) |
| `routes_announcements.py` | 179 | announcement CRUD/transitions + FK-reverse lists |
| `routes_applicants.py` | 139 | applicants, documents, verification + preference recompute |
| `routes_applications.py` | 185 | submission gates, screening, application-scoped lists |
| `routes_assessments.py` | 133 | SME assessment lifecycle, accept cascade |
| `routes_certificates.py` | 273 | issuance/roster/ranking, extend (OCC), return, selections with all gates |
| `routes_passovers.py` | 101 | entry reads, pass-over create/adjudicate |
| `routes_offers.py` | 277 | respond (temporal-before-state), suitability, clearance, EOD, appointments |
| `routes_appeals.py` | 136 | appeal filing + adjudication cascades |
| `routes_clock.py` | 23 | `/_clock/set_current_utc` outside the `/hiring` prefix |

### Wiring audits
- **Endpoints**: 55/55 — machine-diffed against the scaffold endpoint table (54 under `/hiring` + clock at root): `missing: []`, `extra: []`.
- **Errors**: 42/42 catalog ids each raised from at least one site; zero unknown ids raised.
- **Constants**: every referenced constant (`WEIGHT_*`, `GRADE_BANDS`, `LEVEL_GRADE_CAP`, `SME_WEIGHT_*`, `SME_SCALE`, `SME_BASE`, `RULE_OF_MANY_MIN`, `MAX_EXTENSIONS`, `EXTENSION_MAX_DAYS`, `APPEAL_WINDOW_DAYS`, `OFFER_RESPONSE_DAYS`, `DEFAULT_BQ_CUT/WQ_CUT`) is defined exactly once in `calc.py` with the PRD value; no orphan references.
- **No seeding**; store starts empty every boot.

### Smoke tests (dynamic ports, server via `start.sh`, killed by saved PID)
- **Smoke A (52 checks, 0 fail)**: series → position (total_points=3000, provisional 9, official null) → classify (official 11) → announcement → open → 3 applicants → apply (provisional 100/BQ) → duplicate-application 409 → screen (required 48) → rescreen 409 → assess/submit/accept (scores 100/94/88 → BQ/WQ/WQ) → issue-while-OPEN 409 → close → issue → rank order → category-bypass 422 → select → accept offer → suitability/clearance gates → EOD schedule/confirm → appointment COMPETITIVE, application HIRED → stale reclassify 412 → UNRANKED/DIRECT_HIRE chain → ERR_ASSESSMENT_NOT_APPLICABLE → 1-eligible roster → auto-FILLED + auto-CLOSED.
- **Smoke B (all green)**: DD214/VA_LETTER verification → CPS 10-point float to rank 1, preference group, augmented-score order → ERR_NOT_PREFERENCE_ELIGIBLE → ERR_PASS_OVER_PENDING block → approve → ERR_PASS_OVER_REQUIRED → second pass-over → select → segregation-of-duties 422 (both directions wired) → ERR_REVIEW_ALREADY_RECORDED → extend OCC 412 / days>30 422 / two extends OK / third 422 → respond at exactly `response_due_at` → 409 ERR_OFFER_RESPONSE_EXPIRED with NOT_SELECTED cascade → RATING appeal sustain (assessment RETURNED/`APPEAL_SUSTAINED`, app RATED→QUALIFIED) → QUALIFICATION appeal sustain re-screen → appeal at exactly deadline → 422 → certificate EXPIRED at exactly `expires_at` with pool return → return-on-expired 409 → re-issue → ERR_INSUFFICIENT_ELIGIBLES.

### Interpretations chosen (PRD-silent or tension points)
1. **`preference_eligible` on entries = verified non-NONE claim** (points > 0), not a raw copy of `preference_verified` (always true for NONE) — otherwise no desired entry could ever be non-eligible and the whole pass-over machinery would be dead; same reading for STATUS_CANDIDATES "verified preference".
2. Entity-backed ownership is checked after existence (ownership needs a resolvable entity); pure role gating stays at priority 2.
3. Screening checks application state (`ERR_APPLICATION_WRONG_STATE`) before announcement state (`ERR_INVALID_STATE`), per PRD §3.4 sentence order.
4. Lazy certificate expiry also evaluates prior certificates at issuance time (determining "still ACTIVE") and in the RATING-appeal ACTIVE-certificate check; not on plain entry reads/lists (scaffold lists no side effect there).
5. schedule-eod compares at date granularity (`eod_date.date() >= clock.date()`); confirm-eod compares datetimes (`clock >= eod_date`).
6. Reclassification leaves `provisional_grade` unchanged (PRD lists only factors + total_points + official_grade as rewritten).
7. Provisional score/category computed for UNRANKED announcements too (submission side effect unconditional).
8. Ranking ties beyond identical `submitted_at` break by insertion sequence (deterministic; PRD pins "never id").
9. Document re-verification is idempotent (no document state machine specified).
10. `adjudication_note` stored on PassOverRequest (PRD sanctions it); certificate-return `reason` accepted but not persisted (no entity field).
11. Selecting an entry id belonging to a different certificate → 404 (nested-scope resolution).
12. Announcement period overlap counts all siblings including cancelled (PRD explicitly includes cancelled only for certificate windows).
13. `api_request_timestamp` uses the logical clock (all server-recorded timestamps do).
14. Pagination violations (limit outside 1..100, offset < 0, non-integer) → ERR_INVALID_REQUEST.
15. Sustained PREFERENCE appeal on a RATED application refreshes determination fields + `notified_at`; the rating stands.
16. Appeal adjudication cascades are posture-guarded: if the application no longer matches (e.g. no longer RATED), the appeal still adjudicates and only the cascade is skipped.

Orchestrator spot-check: 20 Python modules all `py_compile`-clean; clock route at `/_clock/set_current_utc` (unprefixed, correct); 55 route decorators counted across route modules.

## Step 7: Test-fix iteration loop — 2026-10-02T15:20:00.000Z

Clean 8-round sweep achieved. Final state: all 8 `results.${i}.json` files preserved in `workspace/implementation/`, each showing 78/78 passed.

**Summary**

- **Iterations run:** 2 (sweep 1: 12 deterministic failures identical across all 8 rounds; one implementation fix; sweep 2: 78/78 in all 8 rounds).
- **Tests deleted:** none.
- **`test_helpers/` fixes:** none.
- **`test_suite/` fixes:** none.
- **`implementation/` fixes:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_3468_competitive_hiring_certificates_veterans_preference_category_rating/workspace/implementation/store.py` — added `fmt_clock_dt()`: renders clock-sourced/computed timestamps as the logical clock itself renders (no fractional part at whole-second instants; three fractional digits otherwise).
  - `/home/ubuntu/github/CodingPRD/tasks/task_3468_competitive_hiring_certificates_veterans_preference_category_rating/workspace/implementation/serializers.py` — `_dump()` now uses `fmt_dt` (3 fractional digits) only for `created_at`/`updated_at`, and `fmt_clock_dt` for all domain timestamp fields (`submitted_at`, `issued_at`, `expires_at`, `response_due_at`, `deadline_at`, `eod_date`, etc.). Envelope `api_request_timestamp` unchanged (3 digits).

**Root cause:** all 12 failures were one defect — the implementation applied a uniform 3-fractional-digit serializer to every timestamp, returning e.g. `issued_at: "2026-09-15T00:00:00.000Z"` where tests expected `"2026-09-15T00:00:00Z"`. PRD adjudication: §2.4 and §2.2/§2.3 explicitly mandate three fractional digits only for `created_at`/`updated_at`/`api_request_timestamp`, while §2.5 states clock-sourced timestamps are "taken from a single server-side logical clock" that "reads exactly 2026-09-01T00:00:00Z" (no fractional digits) and §2.10 carries timestamps without rounding. The tests' assertions (stamp equals the exact clock literal; computed deadlines = clock literal + N days) trace verbatim to those sentences, so the tests were faithful and the implementation was brought into line — a change that is strictly more literal to PRD §2.5 and violates no PRD sentence.

Orchestrator verification: all 8 `results.{1..8}.json` present post-sweep, each independently parsed: passed=78, failed=0, total=78, errors=0.

## Step 8: Finalize PRD — 2026-10-02T15:45:00.000Z

Done. Summary on exit:

## Line counts
- `PRD.md`: 320 lines; `PRD_FINALIZED.md`: 320 lines; delta 0 lines (+0.00%) — the single edit extends §2.5's first paragraph in place (same line, +497 characters).

## Change list
- **§2.5 (The Logical Clock), first paragraph — revise** — appended three sentences pinning wire rendering of timestamps: `created_at`/`updated_at`/`api_request_timestamp` always render with three fractional digits; every other emitted timestamp (clock-sourced fields, clock-computed values like `expires_at`/`response_due_at`/`deadline_at`, and echoed client-supplied datetimes like `open_at`/`close_at`/`eod_date`) renders exactly as the clock reads — no fractional part at whole-second instants, three fractional digits otherwise, truncated not rounded — `implementation/store.py:56-75` (`fmt_dt`/`fmt_clock_dt`), `implementation/serializers.py:15-18`, `implementation/envelope.py:19`.

This was the only Step 7 diff item (the two `implementation/` fixes are one behavior: the serializer split). No tests or helpers were touched by Step 7, and nothing else in the diff required PRD pinning.

**Why not zero-edit:** the task note allowed byte-identical output only if the PRD already uniquely determines the split. It nearly does (§2.2 pins 3 digits for `api_request_timestamp`; §2.4 pins it for `created_at`; §2.5 says the clock "reads exactly 2026-09-01T00:00:00Z"; §2.10 says timestamps are carried without rounding), but the rendering rule for domain timestamps is a multi-hop inference across four sections that the original implementer demonstrably missed (uniform 3-digit serializer was the Step 7 root cause), and §2.4's `updated_at` bullet never repeats the three-fractional-digit phrase. So I added the minimal pinning sentences rather than shipping zero-edit.

## Per-edit pre-edit search log (single edit)
- **(a) Subject:** wire rendering of timestamps (fractional-digit format).
- **(b) Impl paths enumerated and read/grepped:** `store.py` (fmt_dt L56-62, fmt_clock_dt L65-75, parse_dt L78-93, `touch`/`base_fields` L96-109 — `created_at`/`updated_at` are themselves clock-sourced); `serializers.py` (`_dump` L11-21 routes `created_at`/`updated_at`→`fmt_dt`, every other `*_at` field + `eod_date`→`fmt_clock_dt`, all 15 resource serializers pass through it); `envelope.py` (`_meta` L16-20 → `fmt_dt(now())`, used by success object/empty/list and error bodies); `app.py` L38-44 (ApiError + 404 handlers route through `error_body`); `routes_clock.py` (returns `success_empty`, no timestamp payload); computed timestamps `expires_at` (`routes_certificates.py:72,154`), `response_due_at` (`routes_certificates.py:265`), `deadline_at` (`routes_appeals.py:72`); client-supplied echoed timestamps `open_at`/`close_at` (`routes_announcements.py:37-38`), `eod_date` (`routes_offers.py:211,223`). Greps confirmed no `jsonify` outside `envelope.py` and no other `strftime`/`isoformat`/formatter callsites. Test-side evidence (unchanged by Step 7): `test_suite/test_08_certificate_lifecycle.py` asserts exact strings like `expires_at == "2026-11-14T00:00:00Z"` (no fraction); `test_helpers/assertions.py` uses the runner's `is_iso8601_timestamp`, which accepts both forms.
- **(c) Wording adjustment:** initial draft ("a timestamp sourced from the clock is rendered exactly as the clock reads") would have mis-described `api_request_timestamp`/`created_at`/`updated_at`, which are also clock-sourced (`now()` = `DB.clock`) yet always render with three fractional digits. Restructured to lead with the carve-out and scope the clock-rendered rule to "every other timestamp the API emits," explicitly naming the computed and client-supplied-echoed sub-families so the `open_at`/`close_at`/`eod_date` paths (which are not clock-sourced) stay consistent. The sentence also pins `updated_at` to three fractional digits, closing §2.4's gap to match `serializers.py:15-16` exactly. Null timestamp fields remain governed by the PRD's existing per-field nullability statements; the edit makes no nullability claim.

Deliverable: `/home/ubuntu/github/CodingPRD/tasks/task_3468_competitive_hiring_certificates_veterans_preference_category_rating/workspace/PRD_FINALIZED.md`

Orchestrator verification: `diff` confirms exactly one changed paragraph (§2.5 first paragraph, +497 chars, 2 diff lines); no `implementation/` file is newer than the sweep results, so the Step 7 clean sweep remains valid.

## Step 9: Complete PRD — 2026-10-02T16:20:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_3468_competitive_hiring_certificates_veterans_preference_category_rating/workspace/PRD_COMPLETED.md` is written and verified.

**Source vs output:** PRD_FINALIZED.md 320 lines / 58,399 chars → PRD_COMPLETED.md 320 lines / 63,499 chars (+5,100 chars, zero line-count delta — all edits are inline inserts/revisions; no new sections). 27 change sites: 25 ambiguity-pins, 2 mismatch-revisions.

**Changes** (section — insert|revise — class — what — impl ref):

1. §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` (400) — validate.py:98-120
2. §2.3 — insert — ambiguity — `created_at` sort ties (frozen clock) fall to creation order — store.py:34, routes_announcements.py:104 et al.
3. §2.3 — insert — ambiguity — `has_more` semantics; list filters are exact-match, unrecognized values yield an empty page — envelope.py:38, routes_offers.py:55-64
4. §2.5 — insert — ambiguity — client-supplied datetimes echoed normalized to UTC; offset-less instants read as UTC — store.py:78-93
5. §2.5 — revise — ambiguity — clock endpoint accepts any instant (no monotonicity); full enumeration of lazy-expiry sites (cert: single read, extend/return/selection/pass-over filing, issuance ACTIVE-bar, RATING-appeal bar; offer: single read, offer list evals all, all offer-scoped writes; all other collection reads never eval) — routes_clock.py:14-23, routes_certificates.py:34-39/130/145/166/219, routes_passovers.py:58, routes_appeals.py:20-32, routes_offers.py:52-53/79/93/119/164/213/235
6. §2.7 — insert — ambiguity — entity-backed ownership is evaluated immediately after existence of the entities it reads; dangling id yields 404, never 403 — routes_applications.py:68-74, routes_offers.py:89-91
7. §2.7 — insert — ambiguity — shape rules: strings non-empty, booleans rejected for integer fields — validate.py:21-43
8. §2.8 — insert — ambiguity — body-carried FK resolving outside path scope → `ERR_NOT_FOUND` (selection entry of another certificate) — routes_certificates.py:216-218
9. §2.9 — insert — ambiguity — cancelled announcements still count as siblings for period overlap — routes_announcements.py:58-63
10. §3.1 — insert — ambiguity — three qualification month fields are non-negative integers — routes_series.py:47-50
11. §3.2 — insert — ambiguity — announcement-creation check order: overlap → duplicate number → authority/method → position-CLASSIFIED — routes_announcements.py:58-73
12. §3.3 — insert — ambiguity — re-verification succeeds, re-stamps `verified_by`/`verified_at`, bumps version, recomputes — routes_applicants.py:124-139
13. §3.4 — insert — ambiguity — `notified_at` initialized to the submission instant — routes_applications.py:108
14. §3.4 — revise — mismatch — `STATUS_CANDIDATES` prong is a verified non-`NONE` claim, not bare `preference_verified` — routes_applications.py:38-42
15. §3.4 — insert — ambiguity — screening reports application-state (`ERR_APPLICATION_WRONG_STATE`) before announcement-posture (`ERR_INVALID_STATE`) — routes_applications.py:131-135
16. §3.5 — insert — ambiguity — assessment creation order: QUALIFIED state → active-assessment cap → CATEGORY_RATING applicability — routes_assessments.py:34-43
17. §3.5 — revise — ambiguity — resubmission replaces only payload-carried rating fields; `return_reason` optional (stored null) — routes_assessments.py:68-82,127-130
18. §3.5 — insert — ambiguity — accept on a no-longer-QUALIFIED application → `ERR_INVALID_STATE` — routes_assessments.py:101-103
19. §3.6 — revise — mismatch — `preference_eligible` = verified non-`NONE` claim at issuance (not "copied from `preference_verified`") — routes_certificates.py:80-85
20. §3.6 — insert — ambiguity — ranking ties surviving `submitted_at` fall to application creation order (both CATEGORY_RATING and UNRANKED) — calc.py:139-157
21. §3.7 — insert — ambiguity — certificate return blocked by a SELECTED entry with live offer → `ERR_INVALID_STATE` (PRD named no error) — routes_certificates.py:169-174
22. §3.8 — insert — ambiguity — pass-over creation validates only eligibility + relative rank; no same-certificate or still-REFERRED requirement; ACTIVE gate reads the target's certificate — routes_passovers.py:51-66
23. §3.8 — insert — ambiguity — APPROVED adjudication moves the target only while it still stands REFERRED — routes_passovers.py:93-100
24. §3.9 — insert — ambiguity — schedule-eod floor compares calendar dates; confirm-eod compares full instants against stored `eod_date` — routes_offers.py:221,243
25. §3.9 — insert — ambiguity — RATING-appeal ACTIVE test applies lazy cert expiry first — routes_appeals.py:20-32
26. §3.9 — insert — ambiguity — `corrected_experience_months` optional (stored) on RATING/PREFERENCE filings — routes_appeals.py:41-46
27. §3.9 — revise — ambiguity — sustained cascade replaces claim only when a corrected value is carried; sustained PREFERENCE on a RATED application refreshes months + `notified_at` but stays RATED — routes_appeals.py:96-123

**Adjudication notes on the two mismatch-revisions (both judged non-violations):** the literal §3.6 phrase "preference_eligible copied from preference_verified" and §3.4's "a verified preference" would make every `NONE`-claimant preference-eligible (§3.3: a NONE claim is always verified), which contradicts §3.8's own scheme — the pass-over desired entry "must not itself be preference-eligible" and exists "to reach a lower-ranked non-preference candidate," i.e. exactly the NONE-claimant case. So the PRD read as a whole does not uniquely determine the behavior; the impl's reading (verified non-NONE claim) is the coherent one and is what the surviving tests assert. Per the adjudication rule's "contradicts another PRD passage" exception, these were pinned to the impl rather than reported.

**IMPL BUGS (reported, not patched):** none. Every PRD-pinned behavior checked — formulas, grade bands, cut boundaries, gate orderings incl. the two §2.7 emphasis rules, interval semantics, cascade sets, OCC guards, envelope shapes, error catalog (all 42 ids used and catalogued), endpoint/role/status tables, 201-vs-200 split, terminal states — matches the implementation.

Orchestrator verification: PRD_COMPLETED.md is +5,100 chars / 44 diff lines over PRD_FINALIZED.md (real scan, not a no-op); §3.4 mismatch hunk eyeballed — rewrites "a verified preference" to "a verified non-`NONE` preference claim" with rationale sentence, coherent with §3.8; **no `implementation/` file is newer than the Step 7 sweep results**, so the 8×78/78 clean sweep remains the final, valid evidence. Step 9 named zero impl bugs → no Step 9b fix/re-sweep cycle needed. Pipeline complete.
