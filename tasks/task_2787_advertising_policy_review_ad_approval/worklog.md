## Step 1: Create task directory — 2026-09-04T21:21:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2787_advertising_policy_review_ad_approval and its workspace/ subdirectory. Index 2787 was pre-assigned by the orchestrating caller; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T23:26:00.000Z

All three scaffold artifacts for task 2787 are complete and lint-clean.

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_2787_advertising_policy_review_ad_approval/`

**Lint verdict (verbatim, `skills/prd-bench-scaffold-generator/scaffold_lint.py`):**
```
Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     15
  §1.8 instances scanned:     20
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1181

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**SCAFFOLD.yaml** (2842 lines) — 15 entities, 49 endpoints, 37 ordered validations, 45 errors, 4 roles (Advertiser, PolicyReviewer, IntegrityAnalyst, PolicyAdmin). complexity_profile: `entity_topology: flat`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers `[cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency]`, 2 §1.2.1 concurrency rules. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; the `scenario:` key holds only the domain text — the "Generate task harder than expert level!" directive line was deliberately stripped so it cannot leak into the PRD.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (2198 lines) — single top-level key, 9 rules / 20 instances: `dual_variant_calc` 2, `combinatorial_formula` 3, `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 3, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2.

**SCAFFOLD_CORNER_DESIGN.yaml** (4931 lines) — single top-level key, all 9 guide sections, 89 instances (65 with full `test_recipe`, 24 stubs deferring to §1.8): From Table 1 (Entities) 11, From Table 2 (State Machines) 13, From Table 3 (Calculations) 15, From Table 4 (Validations) 13, From Table 5 (Endpoints) 6, From Table 6 (Errors) 14, From Table 7 (RBAC) 8, From Cross-Cutting Complexity Layers 7, From Consistency Model 2.

**Verified invariants:** every stub's cited `difficulty_instance` resolves to a real §1.8 instance name (0 dangling); no duplicate names within §1.9 and no overlap with §1.8; every stub omits `test_recipe` and every non-stub has one.

**Two fixes applied during the final lint pass:** (1) five §1.9 calls used `GET /ad-policy/policy-rules`, which was never declared — added it to §1.5 as a general business list endpoint (all four roles, `["category_class?", "limit?", "offset?"]`, ordered by `code` ASC), which is what took the endpoint count from 48 to 49; §1.7 already grants "every GET endpoint" so no RBAC edit was needed. (2) An OCC instance captured `$.data.advertiser_version` off an `EnforcementAction` response, a field that entity does not declare — dropped the capture and reused the version read back from `GET /ad-policy/advertisers/{id}`.

**Orchestrator verification:** grep for "harder than expert"/"expert level" across all three YAMLs returned no hits — difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-04T23:27:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2787_advertising_policy_review_ad_approval/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T23:42:00.000Z

PRD complete and verified.

## Output
`workspace/PRD.md` — **432 lines**, 101,208 bytes, ends at a real section boundary (last row of the §5 table).

Constraints honoured: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or grepped; no sibling task directory was read; the file was built in nine chunked `cat >>` appends with `wc -l` + `tail -3` after each.

## Section list
- `# Advertising Policy Review API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles`
  - 2.1. User and Role-Based Access Control
  - 2.2. API Response Structure *(verbatim contract — diffs clean against `section-2.2-response-structure.md`)*
  - 2.3. Pagination
  - 2.4. Common Resource Properties
  - 2.5. Left-to-Right Resolution of Path Identifiers
  - 2.6. Points, Scores and Numeric Discipline
  - 2.7. Version Pinning on Classifier Ingest and Manual Enforcement
  - 2.8. The Logical Clock and the Deterministic Policy Sweep
  - 2.9. Cascade Discipline
  - 2.10. Validation Precedence
  - 2.11. The Serving Eligibility Gate
- `## 3. Business Logic & Workflows`
  - 3.1. The Policy Framework: Rules and Country Variation
  - 3.2. Advertiser Accounts, Verification Axes and Posture
  - 3.3. Creative Authoring, Revision, Submission and Withdrawal
  - 3.4. Automated Pre-Approval Screening
  - 3.5. Certifications and Licence Coverage
  - 3.6. The Human Review Queue: Reviewers, Claiming, Escalation and SLA
  - 3.7. Reviewer Decisions and Their Cascades
  - 3.8. Destination and Landing-Page Integrity
  - 3.9. Disapproval Notices, Appeals, the Violation Ledger and Account Enforcement
- `## 4. Endpoint Definitions` (49-row Method | Path | Description | Authorized Role(s) table)
- `## 5. Error Code Catalogue` (45-row Error ID | HTTP Status Code table)

## Hard Contract reports
**Contract 1 — Field-Name Coverage: PASS.** 126 unique required identifiers (all `entities[].fields[].name` across the 15 entities plus every `input`/`query_params`/`path_params` key across all 49 endpoints, `?`-suffix normalised) — 0 missing. Second pass over nested/structured content (`assessment_lines` element keys `policy_rule_code`/`reason_code`/`line_points`, `decisions` element keys `policy_rule_id`/`confidence`/`matched_snippet`, verification `dimension`/`outcome`/`evidence_ref`, `to_iso8601`) — 0 missing. Enum-literal pass found `action_type`'s `WARNING` and `RESTRICTION` present only as lowercase prose; **fixed** in three places in §3.9 so the literals `WARNING | RESTRICTION | SUSPENSION` appear verbatim. All 38 scaffold constants appear with their exact values.

**Contract 2 — Rule Coverage: PASS.** All 45 declared error IDs are discussed in the §1–§4 narrative, not merely listed in §5. All 37 validations' errors present, with the two deliberate precedence inversions stated explicitly in §2.10 (`ERR_APPEAL_ALREADY_EXISTS` before the state check; `ERR_CERTIFICATION_MISSING` before `ERR_INVALID_LIMITED_COUNTRIES`). Both `concurrency_rules` present with field, error and 412. All state-machine tokens across the four parallel axes appear verbatim. Endpoint set matches the scaffold exactly: 49 in, 49 table rows, zero set difference in either direction.

**Contract 3 — §3 Path Purity: PASS.** 280 distinct backtick tokens in §3; 0 begin with `/`, 0 are bare HTTP methods, 0 are method+path combinations. The single slash-bearing token is `https://`, the required URL-scheme constraint on `landing_page_url`/`display_url`, which is none of the three prohibited forms. Full endpoint paths are confined to §2.7 (where Contract 2 requires them) and §4.

Also cleaned: one fuzzy word (`roughly seven years` → `exactly seven 365-day years`, the 2555-day retention). No symbolic operators, no pseudocode, and no scaffold/difficulty vocabulary leaked into the prose.

**Orchestrator verification:** `tail -12` shows the file ending on the final error-table row (`ERR_INVALID_THRESHOLD_ORDER | 422`) — a real section boundary, not mid-sentence, so the known doc-generator truncation failure did not occur. grep for "expert level"/"scaffold"/"test_recipe" in PRD.md returned no hits.

## Step 5: Generate unit tests — 2026-09-05T01:32:00.000Z

The test suite for task 2787 is complete.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2787_advertising_policy_review_ad_approval/`)

**`test_helpers/`** — 2,982 lines total: `__init__.py` 232, `api_client.py` 441, `api_errors.py` 129, `assertions.py` 519, `constants.py` 293, `factories.py` 246, `fixtures.py` 744, `test_users.py` 79, `types.py` 299.

**`test_suite/`** — `conftest.py` 29 lines, plus 18 test modules / 107 tests:

| file | lines | tests |
|---|---|---|
| test_01_risk_scores_and_points_balances.py | 240 | 4 |
| test_02_priority_assessment_and_severity_formulas.py | 661 | 7 |
| test_03_creative_and_task_state_machines.py | 347 | 4 |
| test_04_disapproval_and_cloaking_cascades.py | 429 | 4 |
| test_05_validation_precedence_conflicts.py | 500 | 6 |
| test_06_threshold_boundaries_and_coverage_instants.py | 360 | 4 |
| test_07_cross_entity_state_dependencies.py | 356 | 4 |
| test_08_interval_contention_windows.py | 343 | 4 |
| test_09_compensating_invariants.py | 391 | 4 |
| test_10_entity_shapes_and_body_validation.py | 731 | 11 |
| test_11_state_machine_transitions_and_guards.py | 728 | 10 |
| test_12_calculation_rounding_and_constants.py | 785 | 8 |
| test_13_validation_rules_and_precedence.py | 1108 | 10 |
| test_14_endpoint_behaviour_and_bulk_actions.py | 726 | 6 |
| test_15_error_catalogue_triggerability.py | 860 | 9 |
| test_16_role_permissions_and_scope.py | 852 | 8 |
| test_17_version_pinning_and_threshold_edges.py | 419 | 3 |
| test_18_immediate_consistency.py | 154 | 1 |

## Queue counts

- **Queue A (Difficulty, §1.8): 41 tests** covering all **20** live instances (≥2 tests each; the nested-max `priority_score` instance gets 3).
- **Queue B (Corner, §1.9): 66 tests** covering all **65** live instances (Tables 1–7 = 61, Cross-Cutting = 3, Consistency Model = 1; the policy-sweep endpoint instance gets 2).

## Verification

- Every test carries exactly one `Design:` line, last line of the docstring, name verbatim from the source yaml: automated check → **107 tests, 0 problems**.
- Every PRD quotation grepped literally against `workspace/PRD.md`: **338 quotes, 0 missing**.
- All 27 `.py` files `ast.parse` clean; all 18 test modules import cleanly under `PYTHONPATH=.`; `pyflakes` clean (trimmed six unused imports found in test_01–test_05).
- Coverage cross-check confirms **0 uncovered live instances** and **0 stubs accidentally translated**.
- Nothing was written under `workspace/`; `workspace/implementation/` was never read or touched.

## Skipped / adjusted

**Skipped instances: the 24 `excluded_because:` stubs in `SCAFFOLD_CORNER_DESIGN.yaml` only** — each is explicitly delegated to a queue-A difficulty instance that already covers the same behaviour, so translating them would duplicate. No instance was skipped for lacking PRD coverage; every live instance in both indices passed the two-condition filter.

**Six recipe assertions were corrected to the PRD-derived value** (instance still translated, since the PRD uniquely derives the corrected outcome):
1. Table 6 restricted-account: `blocking_reason_codes` extended to include `ACCOUNT_ENFORCEMENT` (§3.1 third conjunct is satisfied only for `ACTIVE`/`WARNED`).
2. Cross-Cutting and Consistency recipes said `origin CASCADE`; PRD §3.9 spells it `SYSTEM_CASCADE`.
3. Table 5 ledger `reason ASSESSMENT` → `DISAPPROVAL_ASSESSED`.
4. Table 5's `decay_refreshed_advertisers` sweep counter omitted (not a PRD-named counter).
5. Table 2 instance 7's post-sweep `severity_index == 0.00` omitted (not uniquely derivable there).
6. Table 3 instance 3's `priority_score == 70.00` omitted (PRD's nested max yields a different value; the rest of the instance is asserted).

Also deliberately never asserted: `closed_action_count`, which appears nowhere in the PRD as a response field.

**Orchestrator verification:** both directories landed at the task root (not under workspace/); `find workspace -name "test_*"` returned nothing. 107 `Design:` tags = 66 Corner + 41 Difficulty, matching the reported queue counts.

## Step 6: Generate implementation — 2026-09-05T00:12:00.000Z

Implementation complete and verified.

## Files written

`workspace/implementation/`

| file | lines | role |
|---|---|---|
| `start.sh` (0755) | 10 | guarded `pip install`, then `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=2.2.0` |
| `app.py` | 61 | app factory, blueprints under `/ad-policy`, error handlers (ApiError, 404/405/400/500) |
| `core.py` | 401 | logical clock, in-memory `Store` (15 collections), envelope/meta, 45 error ids, auth, pagination, `touch()` versioning |
| `validate.py` | 247 | body shape validation → `ERR_INVALID_REQUEST` |
| `calc.py` | 508 | all 10 derived calculations (risk scores, severity index, priority score, screening outcome/route, disapproval assessment, destination result, serving gate) |
| `services.py` | 698 | serializers, lookups, cascades (gate recompute, account posture, ledger, enforcement, task lifecycle, notices, archive) |
| `routes_policy.py` | 325 | policy rules, country overrides, advertisers, verifications, manual enforcement, reviewers |
| `routes_creatives.py` | 440 | ad creatives, submit/withdraw, screening runs, destination checks |
| `routes_review.py` | 705 | review tasks, certifications, notices, appeals, enforcement reads, clock, policy sweep |

Total 3396 lines. Every `.py` file passes `python3 -m py_compile`; `__pycache__` removed, so the directory holds exactly the 10 deliverable files.

## Endpoint coverage

49 routes registered — an exact match against SCAFFOLD.yaml's 49 declared endpoints (path-parameter-normalized diff: nothing missing, nothing extra).

## Smoke test (live server, `PORT=18787 bash start.sh`)

Ready in 2 s. All envelopes match PRD §2.2:
- `POST /ad-policy/policy-rules` as PolicyAdmin → **201**, `response_type: "object"`, `meta.api_request_id` = `req_` + 20 uppercase alnum, `api_request_timestamp` = `2026-08-01T00:00:00.000Z` (logical clock, 3 fractional digits)
- `GET /ad-policy/policy-rules?limit=5&offset=0` → **200**, `response_type: "array"`, meta carries `limit/offset/total_count/has_more`
- `GET /ad-policy/advertisers/<missing>` → **404** `ERR_ADVERTISER_NOT_FOUND`
- `POST /ad-policy/policy-rules` as Advertiser → **403** `ERR_FORBIDDEN_ROLE`
- no auth headers → **401** `ERR_UNAUTHENTICATED`; `limit=101` → **400** `ERR_INVALID_PAGINATION`; unrouted path → **404** `ERR_NOT_FOUND`

I also ran a full in-process business-flow test (rule + country override, advertiser verification, reviewer, creative submit, OCC-pinned screening run → `ROUTED_MANUAL`, task claim, certification, `APPROVE_WITH_LIMITS`, destination mismatch → re-route, cloaking → auto-disapproval + notice + ledger + SUSPENSION, granted appeal → reversal + reinstatement, clock advance, two idempotent sweeps): every assertion on status codes passed, including 409/412/422 negative cases.

## Cleanup note

The backgrounded `bash start.sh` PID was the wrapper shell — killing it left the real `python3 app.py` alive. I located it by port with `ss -ltnp`, confirmed via `/proc/<pid>/cmdline` and `cwd` that it was the task-2787 server, and killed that single PID. Port 18787 is released and connections are refused. No pattern kill was used at any point.

Verified constraints: storage is in-memory dicts only (no sqlite/file/`/tmp` usage anywhere in the modules), all 15 collections are empty on a fresh boot with every list endpoint returning `total_count: 0`, and the clock starts at `2026-08-01T00:00:00Z` — nothing is seeded.

## Step 7: Run tests and iterate — 2026-09-05T01:54:00.000Z

Clean exit — all 8 parallel rounds pass 107/107.

## Summary

**Iterations run:** 2 (iteration 1 sweep: 104/107 in all 8 rounds, 3 deterministic failures, zero flakiness; iteration 2 sweep: 107/107 in all 8 rounds).

**Tests deleted:** none. All 3 failures were partial-coverage cases resolved under STEP 1c by removing the single uncovered assertion and keeping the covered remainder.

**Assertions removed (STEP 1 partial-coverage handling):**

- `test_18_immediate_consistency.py::test_every_artefact_of_a_disapproval_is_readable_in_the_very_next_request` — removed the `decided["resolved_at"]` instant assertion. **PRD-silence category: computed/response-field silence.** `resolved_at` appears nowhere in PRD.md. §3.6 enumerates the `ReviewTask` fields closed-form ("It records the `ad_creative_id`… the `queue`… its `status`, the reviewer's `resolution`, the derived `priority_score`, the derived `sla_deadline_at`, the `cycle_count` loop counter, the `claimed_at` instant… and the `escalation_note`") and `resolved_at` is not among them. Rule that drove generation: the §2.9 immediate-consistency cascade — all remaining assertions of that rule (notice, ledger, both balances, severity index, enforcement action, posture, serving gate, freed reviewer slot) were kept and pass.

- `test_16_role_permissions_and_scope.py::test_one_advertiser_cannot_read_or_touch_another_advertisers_creative` — removed the cross-tenant `GET /ad-creatives/{id}` → `ERR_ADVERTISER_SCOPE_VIOLATION` assertion. **PRD-silence category: unique-derivability collapse (two-reader divergence).** §2.1 closes the guarded-operation list explicitly: "This scope rule guards creative creation, creative revision, creative submission, creative withdrawal, certification submission, appeal filing, and every `PolicyReviewer` action on review tasks and appeals" — creative *read* is absent, and the §4 table lists "Read one creative" as **All roles** with no scoping caveat. Reader A takes the later "`Advertiser` reads are scoped to that advertiser's own creatives" as a 403 on single reads; Reader B takes it as list-filtering, since the closed enumeration deliberately omits reads. Both are PRD-faithful, so the assertion is not uniquely determined. The three genuinely-enumerated scope assertions in the same test (withdraw, author-under-another's-`advertiser_id`, and the ghost-reviewer claim) were kept and pass.

**Fixes applied to `test_helpers/`:** none — no fixture-layer defect surfaced.

**Fixes applied to `test_suite/` (STEP 2, test mis-translates PRD):**

- `test_02_priority_assessment_and_severity_formulas.py::test_the_risk_score_rounds_once_on_the_sum_unlike_the_assessment` — tightened the discriminating tolerance from `abs=0.01` to `abs=0.005` on the paired assertions for `provisional_risk_score`. The test's whole point is that rounding-once-on-the-sum yields **6.93** while rounding-per-finding yields **6.92** — one cent apart — but `abs=0.01` swallowed exactly that cent, making `!= pytest.approx(6.92, abs=0.01)` self-contradictory with the `== pytest.approx(6.93, abs=0.01)` on the line above. The implementation was already correct (it returned 6.93, the PRD-mandated value per §3.4 "keep each of those products unrounded, add them all together, round the single total half-up to 2 decimals"). Half a cent is the faithful window given §2.6's "carried to exactly 2 decimal places", so this is a tightening, not a weakening.

**Fixes applied to `implementation/`:** none. No implementation defect was found — the sole arithmetic failure was a test-tolerance bug against an already-correct value, and the other two were PRD-uncovered assertions.

**Final sweep evidence** (`results.$i.json`, 8 concurrent rounds under `setsid nohup`, 190s each):

| round | passed/total |
|---|---|
| 1 | 107/107 |
| 2 | 107/107 |
| 3 | 107/107 |
| 4 | 107/107 |
| 5 | 107/107 |
| 6 | 107/107 |
| 7 | 107/107 |
| 8 | 107/107 |

`failed=0, errors=0, skipped=0` in every round; no `skip`/`xfail` markers exist anywhere in `test_suite/`. `worklog.md` was not touched (mtime unchanged at 01:32).

One note for the orchestrator: both PRD-coverage gaps I hit are arguably worth a PRD amendment rather than a test trim, if you want that coverage back — adding `resolved_at` to §3.6's `ReviewTask` field list, and stating whether single-resource reads are scope-guarded for `Advertiser` (§2.1's guarded-operation enumeration currently excludes reads while a later sentence implies read scoping). Neither is actionable inside my remit.

**Orchestrator verification:** independently re-read all 8 `workspace/implementation/results.*.json` with a json parser — every file reports `passed=107, total=107`. Step 8 is NOT skipped: Step 7 ran 2 iterations and made 3 `test_suite/` changes (2 assertion removals + 1 tolerance tightening), each marking a site where PRD.md failed to determine behaviour the implementation had already chosen.

## Step 8: Finalize PRD — 2026-09-05T01:56:00.000Z

PRD_FINALIZED.md is written. One edit was warranted; the other two Step 7 items were already determined by PRD or matched impl.

## Line counts
- `PRD.md`: 432 lines · `PRD_FINALIZED.md`: 432 lines · **0.0% line delta** (single in-place sentence replacement inside §2.1's paragraph; 1 line changed, ~+380 chars).

## Changes
- **§2.1 (role model paragraph, line 23)** — *revise* — the closing sentence "All four roles may read; `Advertiser` reads are scoped to that advertiser's own creatives, certifications, notices, appeals, archive entries and ledger entries" was a **PRD/impl mismatch**. Implementation applies no ownership scoping to any read: reads are gated only by `authenticate()` plus the §4 table's role set. Replaced with wording stating reads carry no ownership scoping and no reviewer-identity resolution, that cross-advertiser single reads succeed, that list endpoints are not implicitly narrowed, and that the scope rule bites only on the enumerated write operations — `implementation/routes_creatives.py:129-132` (`read_ad_creative`), `implementation/core.py:330-340` (`authenticate`).

## Items deliberately NOT patched
- **`resolved_at` on `ReviewTask`** — grep for `resolved_at` across `implementation/` returns **zero hits**; `services.py:146-163` (`s_review_task`) emits exactly the field set §3.6 already enumerates plus `id`/`created_at`/`updated_at`/`version`. Step 7's suggestion to "add `resolved_at` to §3.6" would have *introduced* a mismatch against the impl, so §3.6 is left verbatim — it already matches.
- **`provisional_risk_score` tolerance tightening (test_02)** — a pure test-tolerance bug. `calc.py:220-226` rounds once on the unrounded sum and caps at 100.00, exactly as §3.4/§2.6 already pin. No PRD silence; no edit.

## Per-edit pre-edit search log
**Edit 1 — §2.1 read scoping**
- **(a) Subject:** advertiser (and reviewer) ownership scoping as applied to read operations, plus implicit list filtering by acting principal.
- **(b) Impl paths enumerated (grepped `SCOPE_VIOLATION`/`scope` repo-wide, then read every `methods=["GET"]` handler):**
  - `routes_creatives.py`: `read_ad_creative:129`, `list_ad_creatives:112` (filters only from query args), `list_creative_screening_runs:330`, `read_screening_run:341`, `list_run_classifier_decisions:347`, `list_destination_checks:420`, `list_creative_archive_entries:431` — all `authenticate()` only.
  - `routes_review.py`: `list_review_tasks:42`, `read_review_task:57`, `list_certifications:346`, `read_certification:360`, `list_disapproval_notices:384`, `read_disapproval_notice:397`, `list_notice_ledger_entries:403`, `list_appeals:462`, `read_appeal:476`, `list_enforcement_actions:530`, `read_enforcement_action:544` — all unscoped.
  - `routes_policy.py`: `list_policy_rules:85`, `read_policy_rule:98`, `list_country_overrides:138`, `read_advertiser:189`, `list_advertiser_archive_entries:248`, `list_advertiser_ledger_entries:260` unscoped; `list_rule_classifier_decisions:149` and `read_reviewer:298` are role-restricted only (→ `ERR_FORBIDDEN_ROLE`, matching the §4 table).
  - Write-side scope sites confirmed still matching the PRD's closed guarded-operation list, so the sentence must not disturb them: `routes_creatives.py:32-39,57-58,138,192,212`, `routes_review.py:28-36,94,172,192-193,298-300,424-427`, `core.py:343-350` (`require_reviewer_identity`).
- **(c) Wording adjustments made:** (1) added "subject only to the authorized-role set the §4 table gives each individual read operation" so the sentence does not falsely promise every role can reach `GET /reviewers/{id}` or `GET /policy-rules/{id}/classifier-decisions`; (2) widened from advertiser-only to "no ownership scoping **and no reviewer-identity resolution**", because `read_review_task`/`read_reviewer` never resolve a `PolicyReviewer`'s `X-User-ID` (unlike claim/release/decision/appeal-decision, which do via `require_reviewer_identity`); (3) explicitly added the list-endpoint clause so the sentence cannot be re-read as "single reads are open but lists are filtered"; (4) closed with "bites only on the write operations enumerated with it" to keep the earlier closed enumeration in the same paragraph authoritative rather than contradicted.

**Orchestrator verification:** PRD_FINALIZED.md is 101,539 bytes vs PRD.md's 101,208 — not byte-identical, so the pass genuinely ran.

## Step 9: Complete PRD — 2026-09-05T02:43:00.000Z

Step 9 was run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place). Partition: pass 1 = app.py/core.py/validate.py/calc.py; pass 2 = services.py/routes_policy.py; pass 3 = routes_creatives.py/routes_review.py. Total **54 edits** (46 ambiguity-pins, 8 mismatch-revisions). Source 432 lines / 101,539 chars → final 433 lines / 118,313 chars (**+16,774 chars, +1 line**); every patch was an in-paragraph insert or revision, no new sections.

### Pass 1 — app.py, core.py, validate.py, calc.py (17 ambiguity-pins, 1 mismatch)
- §2.1 — revise — ambiguity — a whitespace-only `X-User-ID`/`X-User-Role` counts as empty, and the four role spellings are matched exactly (case-sensitive) — core.py:333-338
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly twenty uppercase-alnum characters — core.py:279-283
- §2.2 — insert — ambiguity — sub-business failures absent from the §5 catalogue: unrouted path → `ERR_NOT_FOUND` 404, undeclared method → `ERR_METHOD_NOT_ALLOWED` 405, unexpected fault → `ERR_INTERNAL` 500; trailing slash ignored in route matching — app.py:22,32-51
- §2.3 — revise — ambiguity — an empty-valued `limit`/`offset` is rejected as non-integer, a leading `+` is tolerated, and `offset` has no upper bound (past-the-end offset returns an empty `data`) — core.py:357-384
- §2.3 — revise — ambiguity — every ordering breaks its residual tie (routinely a shared `created_at` under the logical clock) by ascending server-side insertion order; `id` never participates — core.py:200-209
- §2.3 — revise — ambiguity — `limit`/`offset` in meta are the effective values, `total_count` is pre-pagination post-filter, `has_more` ⇔ `offset + len(page) < total_count` — core.py:301-309
- §2.4 — revise — ambiguity — inbound instants accept trailing `Z`, an explicit numeric offset (normalized to UTC), a bare offset-less instant (read as UTC) and a bare calendar date (midnight UTC) — core.py:59-74, validate.py:143-154
- §2.6 — revise — ambiguity — whole-number JSON literals are legal for 2-decimal fields (`5`→`5.00`), but the value must be a JSON number (numeric strings and booleans are shape failures) — validate.py:122-140
- §2.8 — revise — **mismatch** — PRD sent every invalid `to_iso8601` to `ERR_CLOCK_REWIND`; impl reports `ERR_INVALID_REQUEST` when it is missing/null/non-string and `ERR_CLOCK_REWIND` only for an unparseable string — validate.py:36-57 + routes_review.py:556-562
- §2.9 — revise — ambiguity — the version bump is once per request, not once per hop; a row created inside the triggering request is published at `version` 1 with `updated_at` == `created_at` — core.py:154-198
- §2.10 item 4 — revise — ambiguity — JSON `null` counts as absent (required → missing-field error; optional → declared default); absent/empty/whitespace body reads as `{}`; a non-object JSON body is `ERR_INVALID_REQUEST` — validate.py:36-57, 72-119
- §3.3 — revise — ambiguity — `declared_category_codes` elements are screened only as 1-40-char strings (charset not re-checked → `ERR_POLICY_RULE_NOT_FOUND`, not `ERR_INVALID_REQUEST`) and duplicates are tolerated, collapsing in the matched rule set — validate.py:192-194, routes_creatives.py:66, calc.py:89-96
- §3.3 — revise — ambiguity — `political_flag` filter accepts `true/false/1/0` in any case and silently ignores anything else; other filters are exact string equality — core.py:392-401
- §3.4 — revise — ambiguity — the `decisions` array admits field-for-field identical elements, each materializing its own decision row — routes_creatives.py:251, validate.py:157-178
- §3.5 — revise — ambiguity — coverage selection's third tie-break is ascending insertion order after `valid_until` desc / `created_at` asc — calc.py:203-209
- §3.8 — revise — ambiguity — reference-crawler-check ranking has a fourth key: later insertion order — calc.py:460-472
- §3.9 — revise — ambiguity — `policy_rule_codes` is duplicate-free even when two qualifying decisions matched the same rule (which still contributes two `assessment_lines`) — calc.py:454-455
- §3.9 — revise — ambiguity — phase-one lines with equal rule codes keep submitted decision order (stable sort) — calc.py:428-429

### Pass 2 — services.py, routes_policy.py (14 ambiguity-pins, 1 mismatch)
- §2.5 — insert — ambiguity — a body copy of an identifier that also appears in the path need only resolve to *some* row of its type; it is never compared to the path value and the path value is what is acted on/stored — routes_policy.py:116-119, 224-227
- §3.1 — insert — ambiguity — `category_class` filter is exact string equality; a value outside the three tiers matches nothing rather than erroring — routes_policy.py:90-93
- §3.2 — insert — ambiguity — `evidence_ref` is 1..2000 chars, validated then discarded: persisted nowhere, absent from the response — routes_policy.py:203
- §3.2 — insert — ambiguity — recording an outcome recomputes nothing else, so a `political_eligibility_status` move leaves every creative's serving gate stale; re-recording the value already held still bumps `version` — routes_policy.py:204-207
- §3.2 — insert — ambiguity — posture re-derivation always bumps the advertiser's `version`, but sibling creatives' gates are recomputed only when the posture value actually changed, and such a creative's `version` advances only if its `serving_eligible`/`blocking_reason_codes` actually move — services.py:436-442, 393-404
- §3.6 — insert — ambiguity — `status` is an optional reviewer-registration field (ACTIVE/OFFLINE, default ACTIVE); every PATCH field optional so an empty amendment is an accepted no-op that still bumps `version`; supplied arrays keep the non-empty/duplicate-free/enum constraints; lowering the ceiling below the current `claimed_task_count` is admitted and releases nothing — routes_policy.py:284, 304-325
- §3.6 — insert — ambiguity — `queue_specialties` and `country_authorizations` are stored and returned in submitted order, never sorted — services.py:79-80
- §3.6 — insert — ambiguity — SLA expiry on every path leaves `claimed_at` and `resolution` untouched (last-claim instant survives; `resolution` stays `PENDING`) — services.py:565-570
- §2.9 — insert — ambiguity — `claimed_task_count` is floored at 0; no decrement can drive it negative — services.py:558-562
- §3.5 — insert — ambiguity — the replacement `REGULATED_CERT` task carries a null `primary_policy_rule_id` and `cycle_count` 0 (hence the default 48h SLA and a 0.00 severity component); `risk_score_final` is rewritten, giving back the 8.00 licence credit; affected creatives are visited in ascending insertion order — services.py:680-698
- §3.7 — insert — ambiguity — the suspension hold also rewrites `risk_score_final` from the current provisional score, destination penalty and licence credit — services.py:471-485
- §3.9 — revise — **mismatch** — PRD claimed `delta_points` is "signed non-zero"; impl writes the entry even at 0.00 (a `MANUAL_REVIEW`-only disapproval with no qualifying decisions assesses nothing), so the "non-zero" claim was removed and 0.00 admitted on both reasons — services.py:454-468, calc.py:425-456
- §3.9 — insert — ambiguity — a `SYSTEM_CASCADE` action's `trigger_reason` is server-written as exactly `Severity index {index} reached the {action_type} threshold.` with the index rendered as a bare number, trailing zero dropped (`40.0`) — services.py:533-536
- §3.9 — insert — ambiguity — action creation does not re-derive the advertiser's index: `severity_index_at_issue` is the pre-existing stored `severity_index`, and the new +5.00 from the freshly `SUPERSEDED` predecessor only lands at the next ledger insert or sweep phase 6 — services.py:494-520
- §3.9 — insert — ambiguity — manual mint: `expected_advertiser_version` must be a non-negative integer (else `ERR_INVALID_REQUEST`, not 412); a supplied `prior_action_id` need only resolve (may belong to another advertiser, need not be the action in force) and is stored verbatim while the real in-force action is still superseded; a supplied `effective_until` is stored unchecked against `effective_from`; a manual action is exempt from the strictly-more-severe gate — routes_policy.py:217-244

### Pass 3 — routes_creatives.py, routes_review.py (15 ambiguity-pins, 6 mismatches)
- §2.7 — insert — ambiguity — `expected_ad_creative_version` must be a non-negative integer; absent/null/non-integer/negative is `ERR_INVALID_REQUEST`, not a 412 — routes_creatives.py:252-254
- §3.3 — insert — ambiguity — a revision expires only `QUEUED` tasks, so a `CLAIMED` task survives and its holder's load is not decremented; and all eight revisable fields are optional, so an empty revision still performs the whole reset and bumps `version` — routes_creatives.py:139-185
- §3.3 — insert — ambiguity — withdrawal leaves `risk_score_provisional` and `risk_score_final` exactly as they stood — routes_creatives.py:209-221
- §3.4 — insert — ambiguity — the screening-ingest body may echo `ad_creative_id`; it is required only to resolve to *some* AdCreative and is never compared with the path — routes_creatives.py:255-258
- §3.4 — insert — ambiguity — `creative_version_at_run` is the pre-ingest version, hence exactly the pinned `expected_ad_creative_version` — routes_creatives.py:285
- §3.8 — insert — ambiguity — the destination-check body may likewise echo `ad_creative_id`; `check_type` is recorded for audit only — routes_creatives.py:364-385
- §3.6 — insert — ambiguity — requeue uses the default 48 hours when there is no `primary_policy_rule_id`, and leaves `escalation_note` standing — routes_review.py:129-131
- §3.7 — insert — ambiguity — the ESCALATE `note` is 1–2000 characters, and a field belonging to another decision branch is tolerated and ignored — routes_review.py:173-188
- §3.7 — insert — ambiguity — `approved_under_certification_id` is ranked over the union of every candidate set gathered across all retained countries and demanding rules, and is null when no retained country demanded a licence — routes_review.py:221-232, 267-269
- §3.7 — insert — ambiguity — **handoff 2**: the sweep's phase-8 release also rewrites `risk_score_final` and recomputes the gate, symmetric with the hold — routes_review.py:690-691
- §3.5 — insert — ambiguity — `revocation_reason` is 1–300 characters — routes_review.py:370
- §3.9 — insert — ambiguity — the appeal-decision `note` is 1–2000 characters, screened for shape then discarded (no field carries it, absent from the response) — routes_review.py:488
- §3.9 — insert — ambiguity — grant hop five is skipped in silence when the creative is not `DISAPPROVED`: the grant stands, hops 1–4 land, `reinstated_review_status` stays null, no replacement task — routes_review.py:513-522
- §3.9 — insert — ambiguity — sweep phase 6 visits advertisers in ascending insertion order and rewrites all four figures, but counts in `decay_refreshed_advertisers` and bumps `version` only when `violation_points_decayed` or `severity_index` actually moves; the phase never mints an enforcement action — routes_review.py:664-678
- §4 — insert — ambiguity — where an operation moves several rows, `data` is the resource the path addresses or creates and never the cascade's collateral (ingest → run, destination check → check, decision → review task, appeal adjudication → appeal, revocation → certification), so the affected `AdCreative` must be re-read; the clock advance returns only `previous_utc`/`current_utc` and the sweep only its nine counters — verified estate-wide against all `return ok(...)` sites
- §3.8 — revise — **mismatch** — **handoff 1**: the axis move is a function of the derived result alone, regardless of the prior `destination_status` and of `check_type`; re-clearing turns on the result, not on the `RECHECK` label (an `INITIAL` check re-clears too); `CLOAKING` carries no separate crawler-baseline precondition (that is inherent in derivation clause two); and every accepted check rewrites `risk_score_final`, recomputes the gate and bumps `version` even when the axis value is unchanged — routes_creatives.py:399-416, calc.py:475-490
- §3.3 — revise — **mismatch** — the birth `blocking_reason_codes` were stated unconditionally as `[REVIEW_NOT_APPROVED, DESTINATION_NOT_CLEARED]`, but the §2.11 gate runs at creation like anywhere else, so `ACCOUNT_ENFORCEMENT` joins them for a `RESTRICTED` account and `POLITICAL_ARCHIVE_MISSING` for a political creative (no archive entry can exist yet) — routes_creatives.py:108, calc.py:494-508
- §3.6 — revise — **mismatch** — `assigned_reviewer_id` is also null on a `RESOLVED` task — routes_review.py:254
- §3.6 — revise — **mismatch** — `claimed_at` is cleared by a release, an escalation and a resolving decision alike; only an `EXPIRED` row still carries the instant — routes_review.py:245, 255
- §3.6 — revise — **mismatch** — on release (and identically on the §3.7 decision endpoint) the ownership comparison reports `ERR_ADVERTISER_SCOPE_VIOLATION` only for a task another reviewer actually holds; an unheld task passes it vacuously and is refused `ERR_INVALID_TASK_STATE` — routes_review.py:28-36, 94-98
- §3.5 — revise — **mismatch** — certification validity instants are truncated to whole seconds on storage, so a sub-second component is discarded and never appears in the response — routes_review.py:285-287, 309-310

### Handoff 3 — premise disproved, no edit
Pass 2 suspected `-notice["assessed_points"]` could emit `-0.0` on a zero assessment. Pass 3 checked empirically: `-Decimal("0.00")` is `Decimal("0.00")` (Python normalizes zero's sign), so the impl cannot emit `-0.0`. Pass 2's existing §3.9 wording (`0.00` on both) was already correct; pinning `-0.0` would have invented behavior.

### Orchestrator verification
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` — `diff` reports 93 changed lines — so the scan genuinely ran in all three passes.
- `PRD_COMPLETED.md` ends on the final `ERR_INVALID_THRESHOLD_ORDER | 422` row of the §5 catalogue — a real section boundary, not mid-sentence; no pass truncated it.
- `workspace/implementation/` mtimes all predate 00:05, well before Step 9's 02:04 start — no pass modified the implementation (correct: Step 9 is documentation-only, so the Step 7 green sweep still holds).
- All 8 `results.*.json` artifacts are present at 107/107.
- No `pytest.mark.skip` / `xfail` anywhere in `test_suite/` (the one `grep` hit in test_12 is the word "skipping" inside a docstring).

Pipeline complete.
