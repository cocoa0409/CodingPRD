# Worklog — task_3362_audit_independence_monitoring_partner_rotation_client_acceptance

## Step 1: Create task directory — 2026-10-01T08:54:54.860Z

Task directory was pre-allocated by the caller at `./tasks/task_3362_audit_independence_monitoring_partner_rotation_client_acceptance/` with `workspace/` already created; no new index was computed and no other `task_*` directory was created. Verified `workspace/` exists and is empty; project-root `INSTRUCTION.md` confirmed present.

## Step 2: Generate scaffold artifacts — 2026-10-01T09:34:45.889Z

All three artifacts are generated and the scaffold lint is clean.

## Output files

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3362_audit_independence_monitoring_partner_rotation_client_acceptance/SCAFFOLD.yaml` | 2031 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3362_audit_independence_monitoring_partner_rotation_client_acceptance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1453 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3362_audit_independence_monitoring_partner_rotation_client_acceptance/SCAFFOLD_CORNER_DESIGN.yaml` | 1545 |

## Shape

- **Profile**: `compliance_audit` primary + `temporal_windowing` secondary; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `contagion_risk_propagation`; topology **flat**, role model **segregation_of_duties** (both flagged "0% in examples, PRIORITIZE"); `api_prefix: /audit`.
- **Entities**: 12 (Client, Engagement, ClientAcceptance, IntegrityAssessment, Professional, EngagementRoleAssignment, IndependenceFinding, IndependenceThreat, NonAuditService, Affiliate, AffiliateAttestation, QualityReview) with 20 FK fields, including a self-referential `Client.parent_client_id`.
- **State machines**: 9, of which 5 non-linear — ClientAcceptance (branch + DRAFT⇄SUBMITTED revert), IndependenceFinding (REMEDIATION→RE_TEST→REOPENED loop), Engagement (two independent axes: `status` × `independence_status`), AffiliateAttestation (ATTESTED→BREACHED→PENDING), Client, NonAuditService, IndependenceThreat, QualityReview.
- **Calculations**: 10, with 4 variants across 2 dual-variant rules (client_risk_score PROVISIONAL/FINAL; rotation_tenure STANDARD/PIE_ACCELERATED). Combinatorial rules span three distinct modes: (a) risk-score conditional/clamped, (b) NAF fee pool round-per-service-then-sum, (c) workload base-sum-then-surcharge with pinned evaluation order.
- **Endpoints**: 46 (4 computed/action reads; 2 OCC-guarded writes; 1 `_clock` test-driver fixed at `2026-09-01T00:00:00Z`).
- **Errors**: 34. **Validations**: 23 priority-ordered rows. **Roles**: 6 (2 `entity_backed:Professional`). **Concurrency rules**: 2, both OCC on `Engagement.version`.
- **§1.8**: 9 rules × 24 instances (dual_variant 2, combinatorial 3, non_linear 3, cascade 3, priority-pair 3, boundary 3, cross-entity 3, temporal-overlap 2, compensating 2).
- **§1.9**: 9 canonical sections across 14 blocks — 29 active corner instances + 11 `excluded_because` stubs, 26 distinct guide-vocabulary claim types.

## Verification performed

- `scaffold_lint.py` → **VERDICT: clean lint** (489 calls checked; all FKs reverse-reachable).
- Scenario text stored **byte-identical** to the supplied description.
- Zero hits for the forbidden concurrency vocabulary; neither design key appears inside `SCAFFOLD.yaml`; instance names unique across both design files; all `excluded_because.difficulty_instance` citations resolve; every error code referenced outside the catalog.

Two judgment calls worth flagging: (1) endpoints landed at 46, above the 40 threshold noted in memory as a risk for downstream impl-gen — the surface was kept deliberately dense (12 entities) rather than wide, but Step 6 output should be checked on disk; (2) `QualityReview` carries `review_type: REGULATORY_INSPECTION` so regulatory inspection response/remediation shares one entity with QC reviews instead of adding a 13th entity.

Orchestrator verification on disk: all three files present with the reported line counts (2031 / 1453 / 1545); `SCAFFOLD.yaml` top-level keys confirmed as scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — no `scaffold_difficulty_design` or `scaffold_corner_design` key.

## Step 3: Copy shared files — 2026-10-01T09:35:05.346Z

Copied project-root `INSTRUCTION.md` (1424 bytes) to `workspace/INSTRUCTION.md`. `workspace/` now contains `INSTRUCTION.md` only.

## Step 4: Generate PRD document — 2026-10-01T09:46:22.704Z

PRD generation complete and verified.

### Output

**Path:** `/home/ubuntu/github/CodingPRD/tasks/task_3362_audit_independence_monitoring_partner_rotation_client_acceptance/workspace/PRD.md`
**Line count:** 376 (ends cleanly on the final §5 table row — no truncation)
**Build method:** 8 sequential append passes (Write + heredoc appends), never a single monolithic write.

### Section headings

- `# Audit Independence Monitoring API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock and Temporal Windows · 2.6 The Independence Posture Ladder and Its Propagation · 2.7 Global Network Risk Weighting · 2.8 Optimistic Concurrency on Engagement-Scoped Writes · 2.9 Scoring, Fee Pooling and Rounding Precision · 2.10 The Validation Cascade and Its Precedence · 2.11 Nested Resource Retrieval · 2.12 Segregation of Duties Across the Acceptance and Staffing Pipeline
- `## 3. Business Logic & Workflows` — 3.1 Client Onboarding and Engagement Opening · 3.2 Acceptance and Continuance Decision-Making · 3.3 Staffing, Rotation Tenure and Workload Ceilings · 3.4 Personal Independence: Financial Interests and Employment Relationships · 3.5 Findings, Remediation and Regulatory Escalation · 3.6 Non-Audit Services and Audit-Committee Pre-Approval · 3.7 Global Network Affiliates and Multinational Attestations · 3.8 Quality Control Reviews and Inspection Response · 3.9 Engagement Closure and Client Termination
- `## 4. Endpoint Definitions` (46-row, 4-column table)
- `## 5. Error Code Catalogue` (34-row, 2-column table)

### Scaffold coverage

- **Entities (12, 92 fields):** every field name appears in backticks; defaults (`is_public_interest_entity` false, `max_workload_points` 100, `value_cents` 0, `breach_count` 0, `deficiency_count` 0, `remediation_attempts` 0, `resolved` false, `naf_annual_cap_cents` 0, `is_multinational` false, `industry_expertise_confirmed` false), initial statuses, null-until-set fields, and computed-field derivations all stated in narrative. All 12 entities carry the full `id`/`created_at`/`updated_at`/`version` set (§2.4).
- **State machines (9 axes, 51 transitions):** every `from`/`to` pair, precondition and side effect expressed, including the automatic Engagement status↔independence_status cascades, client posture roll-up, and every terminal state.
- **Calculations (10):** all formulas rendered as precise prose with every constant embedded — industry/jurisdiction indices, PIE surcharge 15, 12/24-month decay with 1.0/0.5/0.25 factors, risk bands 50/70, rotation tables (84/60/36/24/12, 12-month gap tolerance), workload steps 1–4 with pinned evaluation order and 40/25/20/15 base points, per-service rounding before summing, the FROZEN/RESTRICTED ladder (12/6 network thresholds, 50 ceiling, 3/2/1 tier weights), materiality cents with the 2× indirect multiplier, cooling-off months (0/12/24), and inspection windows (30/21/45/15, halved at 5).
- **Validations (23):** §2.10 states the full priority order 1→23 with each rule's `error_id`, and every condition is restated near the workflow it guards.
- **Concurrency (2 rules):** both write endpoints named with `expected_engagement_version`, `ERR_STALE_VERSION`, HTTP 412, and an explicit "no other endpoint takes a version field" statement.
- **Endpoints (46):** 4-column table only; status-code rule and the independence-summary response shape in the intro paragraph. **Errors (34):** 2-column table only; every id also appears in §2/§3 prose. **Roles (6):** exact names plus per-role `identity:` prose in §2.1. **Request identifiers:** all 59 body ids and 30 query ids covered (`limit`/`offset` in §2.3).

Also patched in the exact `action` enum strings (26 values: `CLOSE`, `SUSPEND`, `RESUME`, `START_REMEDIATION`, `PASS_RETEST`, `REPORT_BREACH`, etc.) which prose alone would not have made guessable, and corrected one contradiction where the `RETURN` decision had been written as leaving the engagement's risk fields untouched (the scaffold resets `risk_tier` to `LOW` and `combined_risk_score` to 0).

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 92 required, 92 present, 0 missing
- endpoints[].request_body: 59 required, 59 present, 0 missing
- endpoints[].query_params: 30 required, 30 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 23 checked, 23 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 51 checked, 51 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 23 checked, 23 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 46 checked, 46 expressed, 0 missing
- entities[].fields[] structured content: 92 checked, 92 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked, 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 267
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verification: §2.2 matches `section-2.2-response-structure.md` byte-for-byte (confirmed by diff after fixing one trailing clause); 58/58 numeric-constant spot checks pass; all state enum values, enum field members and role names appear as exact backticked strings. Neither withheld design file nor any sibling task was read.

Orchestrator verification on disk: `workspace/PRD.md` is 376 lines, terminates cleanly at the final §5 table row, contains all five `##` sections, and its §4 table has 46 data rows (48 lines incl. header+separator) and its §5 table has 34 data rows (36 lines incl. header+separator) — matching the reported endpoint and error counts.

## Step 5: Generate unit test suite — 2026-10-01T10:16:44.882Z

**INTERRUPT NOTE.** The Step 5 subagent was killed mid-flight when the host session ended (its report was never returned). Per the "a lost subagent report ≠ a lost artifact" rule, the orchestrator verified the on-disk artifact against source rather than blindly re-running the step. Verdict: **the artifact is complete and valid**; it was accepted as-is.

### Artifact verification (orchestrator-run, not subagent-reported)

- `test_helpers/` — 8 files: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (72 KB).
- `test_suite/` — `conftest.py` + 17 `test_*.py` files; **102 tests collected**.
- `python -m pytest --collect-only -q test_suite/` → **102 tests collected in 0.26s, zero import/collection errors.** This is the only check that catches a dead generation subagent's broken package graph (files that each compile but whose import graph is severed); it passes.
- Every file in `test_helpers/` and `test_suite/` ends on a complete statement (no mid-statement truncation); no `Test*` class is empty.
- `conftest.py`'s `reference` fixture calls `fixtures.seed_reference_data(api)`, which builds the affiliate / professional / client / engagement world **through the public API** (`seed_affiliate`, `seed_professional`, `seed_client`, `open_engagement`). No server-side seeding is assumed — consistent with the no-preloaded-data contract.

### Design-index coverage audit (queue A + queue B)

| Index | Active (non-stub) instances | Covered by an emitted `Design:` tag |
|---|---|---|
| §1.8 Difficulty (queue A) | 24 | 22 |
| §1.9 Corner (queue B) | 29 | 26 |
| **Total** | **53** | **48** |

- Distinct emitted tags: **48**; tags that resolve to a non-existent instance: **0** (no dangling tags).
- The 5 uncovered instances were **deliberately skipped**, not lost to the interrupt: each belongs to a test file that was written in full (the instance is absent from an otherwise-complete file, so a mid-write death would not explain it). The orchestrator independently re-adjudicated all 5 against the PRD-first two-condition filter and **confirms each skip is correct** — emitting them would have violated the contract:

  1. `Corner/calculations/prohibited_service_classification_requires_the_pie_flag` — **not uniquely derivable (unpinned constant)**. The recipe asserts the `BOOKKEEPING` category is prohibited on a PIE client and admitted on a private one. PRD §3.6 (line 242) states the *conditional* rule verbatim ("the categories on the prohibited list are prohibited only when the client is a public interest entity") but **never enumerates which categories are on the prohibited list** — and neither does `SCAFFOLD.yaml` (no `PROHIBITED_CATEGORIES` constant; `grep -n 'PROHIBITED_' SCAFFOLD.yaml` returns only the `PROHIBITED_SERVICE` enum member and the `ERR_PROHIBITED_SERVICE` id). A faithful PRD-only implementer may legitimately choose a different prohibited set (e.g. the real-world SEC set of `MANAGEMENT_FUNCTION`/`LEGAL`/`IT_SYSTEMS_DESIGN`), so two readers diverge. SKIP.
  2. `Difficulty/priority_pair_validation_conflict/prohibited_service_safety_beats_naf_cap_fiscal` — **not uniquely derivable (same unpinned constant)**. The ERR_PROHIBITED_SERVICE-beats-ERR_NAF_CAP_EXCEEDED precedence is only observable if `BOOKKEEPING` is prohibited; with an unpinned list the safety check may never fire. SKIP.
  3. `Difficulty/transitive_cascade/prohibited_service_create_freezes_engagement_then_rejection_restores` — **not uniquely derivable (same unpinned constant)**. The whole depth-3 freeze chain is triggered by creating a `BOOKKEEPING` service on a PIE client. SKIP.
  4. `Corner/entities/client_parent_filter_returns_only_the_controlled_group_children` — **no verbatim PRD coverage of the filter**. The recipe asserts `GET /audit/clients?parent_client_id=...` returns only controlled-group children. PRD line 291 describes the endpoint only as "List clients with filters" and line 286 defers to "the filter parameters implied by their descriptions"; `parent_client_id` appears in the PRD (line 172) **only as a registration field**, never as a list filter. A faithful reader need not implement that query parameter. SKIP.
  5. `Corner/entities/professional_create_rejects_client_supplied_computed_field` — **not uniquely derivable (default/extra-field silence)**. The recipe asserts a body carrying the computed field `active_workload_points` is *rejected* with `ERR_INVALID_REQUEST` rather than silently ignored. PRD line 132 pins the failure modes it enumerates (required fields present, enum membership, numeric ranges) and says "the body must match the endpoint's schema", but never states that an unknown/computed field is a rejection rather than an ignored key — a lenient-but-faithful parser would accept and compute the field. SKIP.

- No **existing** test depends on the unpinned prohibited-category list: `grep -rn 'is_prohibited_for_pie|BOOKKEEPING' test_suite/ test_helpers/` hits only `types.py` (enum + dataclass field), `assertions.py` (an `isinstance(..., bool)` type check) and one docstring quoting the enum. So the unpinned constant cannot poison the 48 emitted tests.

### PRD defect recorded for doc-generator feedback (Zero-Silence Rule)

The PRD names the `service_category` enum and states that `is_prohibited_for_pie` is computed from "the pairing of the service category with the client's `is_public_interest_entity` flag", but **omits the prohibited-category list itself** — a named-but-unvalued constant. This single silence cost 3 of the 24 depth instances (12.5% of queue A) and is the largest coverage loss in this task. Consequence carried forward: the Step 6 implementation will guess the list, which is acceptable only because no emitted test asserts it.

## Step 6: Generate implementation — 2026-10-01T10:48:07.347Z

The implementation is complete and verified. Here is the report.

### Files written under `workspace/implementation/`

| File | Lines |
|---|---|
| `start.sh` | 13 |
| `requirements.txt` | 1 |
| `app.py` | 95 |
| `core/__init__.py` | 1 |
| `core/constants.py` | 185 |
| `core/errors.py` | 91 |
| `core/utils.py` | 143 |
| `core/validate.py` | 150 |
| `core/auth.py` | 32 |
| `core/clock.py` | 28 |
| `core/db.py` | 101 |
| `core/response.py` | 45 |
| `core/serialize.py` | 123 |
| `routes/__init__.py` | 1 |
| `routes/common.py` | 85 |
| `routes/reference.py` | 163 |
| `routes/engagements.py` | 104 |
| `routes/acceptances.py` | 131 |
| `routes/assignments.py` | 82 |
| `routes/findings.py` | 93 |
| `routes/threats.py` | 88 |
| `routes/naf.py` | 81 |
| `routes/attestations.py` | 70 |
| `routes/reviews.py` | 88 |
| `routes/clock.py` | 26 |
| `services/__init__.py` | 1 |
| `services/calc.py` | 201 |
| `services/staffing.py` | 251 |
| `services/independence.py` | 241 |
| `services/lifecycle.py` | 348 |
| `services/assignments.py` | 127 |
| `services/findings.py` | 97 |
| `services/threats.py` | 167 |
| `services/naf.py` | 127 |
| `services/attestations.py` | 110 |
| `services/reviews.py` | 74 |

3,763 lines total. All 35 source files end on a complete statement (verified by tail-checking each).

### Boot verification

Command: `cd .../workspace/implementation && PORT=18899 bash start.sh` (plus `ss -ltnp` PID check; only PIDs I started were killed).

Observed live response to `POST /audit/clients` with `X-User-Role: PlatformAdmin`, `X-User-ID: ops-1`:

```json
{"meta":{"api_request_id":"req_dolpwfdxanr762xbbs","api_request_timestamp":"2026-10-01T10:46:36.109Z"},"response_type":"object","data":{"id":"ef302598-c9e0-419e-bf81-8dc73e38c868","created_at":"2026-10-01T10:46:36.109Z","updated_at":"2026-10-01T10:46:36.109Z","version":1,"legal_name":"Final Check Ltd","industry_code":"TECH","jurisdiction_country":"US","is_public_interest_entity":false,"parent_client_id":null,"status":"PROSPECT","naf_annual_fee_cents":0,...}}
```

(exact field set: `naf_annual_cap_cents`, `naf_approved_fee_cents`, `aggregate_independence_status`, `open_finding_count`).

Fresh-boot wipe confirmed: a server holding 10 clients was killed and relaunched; `GET /audit/clients` then returned `total_count = 0`, `data = []`. No SQLite/JSON/pickle artifacts exist in the tree.

### Coverage note

**46 endpoints → modules** (all registered under the `/audit` prefix; verified via `app.url_map` = 46 rules):
- `routes/reference.py` — POST/GET `/clients`, GET `/clients/{id}`, POST/GET `/affiliates`, GET `/affiliates/{id}`, POST/GET `/professionals`, GET `/professionals/{id}` (9)
- `routes/engagements.py` — POST/GET `/engagements`, GET `/engagements/{id}`, GET `/engagements/{id}/independence-summary`, POST `/engagements/{id}/transitions` (5)
- `routes/acceptances.py` — POST/GET `/client-acceptances`, GET `/client-acceptances/{id}`, POST `…/submit`, POST `…/decision`, POST/GET `…/integrity-assessments` (7)
- `routes/assignments.py` — POST/GET `/role-assignments`, GET `/role-assignments/{id}`, POST `/role-assignments/{id}/end` (4)
- `routes/findings.py` — POST/GET `/independence-findings`, GET `/{id}`, POST `/{id}/transitions` (4)
- `routes/threats.py` — POST/GET `/independence-threats`, GET `/{id}`, POST `/{id}/transitions` (4)
- `routes/naf.py` — POST/GET `/non-audit-services`, GET `/{id}`, POST `/{id}/transitions` (4)
- `routes/attestations.py` — POST/GET `/affiliate-attestations`, GET `/{id}`, POST `/{id}/transitions` (4)
- `routes/reviews.py` — POST/GET `/quality-reviews`, GET `/{id}`, POST `/{id}/transitions` (4)
- `routes/clock.py` — POST `/_clock/set_current_utc` (1)

**9 state machines → services**: `Engagement.status` + `Engagement.independence_status` → `services/lifecycle.py` (status axis) and `services/independence.py` (posture axis, incl. FROZEN→SUSPENDED and rule-scoped auto-resume); `ClientAcceptance` → `services/lifecycle.py`; `Client` → `services/independence.py` + `services/lifecycle.py`; `IndependenceFinding` → `services/findings.py`; `IndependenceThreat` → `services/threats.py`; `NonAuditService` → `services/naf.py`; `AffiliateAttestation` → `services/attestations.py`; `QualityReview` → `services/reviews.py`.

All 10 calculations live in `services/calc.py` and `services/staffing.py`; the 23-priority validation cascade is enforced in the order declared by PRD §2.10 (shape → auth → role → path → FK → state → OCC → business rules), and all 34 error IDs are defined and raised.

### Two notes for the caller

1. **Two constants are referenced but not valued in PRD.md or SCAFFOLD.yaml**: `REMEDIATION_WINDOW_DAYS` (scaffold cites it but never defines it) and the `risk_tier` band boundaries (only the 50 and 70 decision thresholds are pinned). I derived `{LOW:90, MEDIUM:60, HIGH:30, CRITICAL:15}` and `LOW<25, MODERATE<50, HIGH<70, SIGNIFICANT>=70` — both consistent with the PRD's stated monotonicity and the two known boundaries. If the test suite asserts exact dates/tiers, these are the first places to check. The prohibited-service category list is likewise unpinned; I used the seven SEC Reg S-X 2-01(c)(4) categories (leaving `TAX_PREPARATION`, `TAX_ADVISORY`, `OTHER` permitted).

2. I ran an 8-part live smoke suite (~180 assertions) covering auth/envelope/pagination, the full acceptance pipeline (PROVISIONAL vs FINAL variants, RETURN/REJECT/CONDITIONAL/WITHDRAW/APPROVE), staffing with OCC, rotation tenure and the PIE-accelerated 60/60 regime, workload surcharges and ceilings, the posture ladder (CLEAR→RESTRICTED→FROZEN with auto-suspend and rule-scoped auto-resume), network risk, NAF fee pooling with per-service rounding and the cap, review buffering, clock-driven decay tiers and cooling-off auto-clearance, and exact ±1 version arithmetic. All pass; the only failures encountered were errors in my own test expectations, which I verified against the spec before correcting.

### Orchestrator verification on disk (independent of the subagent's report)

- All **35 source files present**, `find . -name '*.py' | xargs wc -l` = **3,750 lines**; every file ends on a non-blank, complete statement (no truncation).
- **Route count verified independently**: `grep -rc '@bp.route' routes/*.py` sums to **exactly 46**, matching the scaffold's 46 endpoints — the ">40 endpoints breaks impl-gen" hazard did not materialise here.
- **Boot verified by the orchestrator**, not just reported: `PORT=18991 bash start.sh` served on `0.0.0.0:18991`, and `POST /audit/clients` returned `201`-shaped data with the correct field set including `naf_annual_cap_cents` (a `naf_annual_fee_cents` typo appeared only in the subagent's prose report, **not** in the shipped code — grep confirms zero occurrences in source). A follow-up `GET /audit/clients` returned the pagination `meta` block with `limit`/`offset`/`total_count`/`has_more`. Only the orchestrator's own PID was killed.
- **UNPINNED-CONSTANT DRIFT CHECK (the Step 6→7 hand-off grep, run because Step 5 and Step 6 guessed independently).** Three constants are named but never valued in PRD.md or SCAFFOLD.yaml. Cross-checked each against what the test suite actually asserts:

  | Unpinned constant | Step 6 impl guess | Does any test assert it? | Verdict |
  |---|---|---|---|
  | `risk_tier` band boundaries | `LOW<25, MODERATE<50, HIGH<70, SIGNIFICANT>=70` | Only `risk_tier == "LOW"` (the PRD-pinned default and the PRD-pinned RETURN/REJECT reset) and an enum-membership check in `assertions.py`. **No test maps a score to a tier.** | Safe — no drift possible |
  | `REMEDIATION_WINDOW_DAYS` | `{LOW:90, MEDIUM:60, HIGH:30, CRITICAL:15}` | Only `remediation_due_on != original_due` after a failed re-test (a change-detector, not a date). **No test asserts an exact due date.** | Safe — no drift possible |
  | prohibited `service_category` list | seven SEC Reg S-X 2-01(c)(4) categories | Nothing — see the Step 5 audit above. | Safe — no drift possible |

  The Step 5 generator was appropriately conservative on all three, so no test can fail for a non-PRD reason. This closes the hand-off hazard; Step 7 starts from a suite and an implementation that cannot disagree on an unpinned value.

## Step 7: Run tests and iterate — 2026-10-01T11:01:11.959Z

All 8 rounds pass 102/102 with no implementation changes needed. Final verification confirms the sweep ran against the current test artifacts (edits at 10:56, sweep at 10:59) and the implementation sources were untouched (newest mtime 10:42).

### Summary

**Iterations run:** 2 (initial 8-round sweep, then one fix batch + re-sweep). Final: all 8 rounds `passed == total == 102`, zero failed / errors / skipped.

**Tests deleted:** none. Every failure traced to a defect in the test artifact, not to PRD silence or non-derivability, so no test was removed or weakened.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3362_audit_independence_monitoring_partner_rotation_client_acceptance/test_helpers/fixtures.py` — `scenario_pagination` created **five** engagements, not four: it called `seed_reference_data` (which already opens one engagement for the first client) and then appended four more, while its own docstring and both consuming tests assert four. `total_count`/`len(data)` came back 5, so `test_engagement_list_pages_with_total_count_and_has_more` and `test_engagement_list_defaults_to_ten_and_zero` failed with `assert 5 == 4`. The fixture now reuses `world["engagement"]` as the first of the four and creates three more; `world["engagements"]` lists all four. This is a fixture-construction bug — PRD §2.3 verbatim covers `total_count`/`has_more`/`limit`-defaults, and the tests expressed that rule correctly.

**Fixes applied to `test_suite/`:**
- `test_corner_rbac.py` — `test_segregation_holds_in_both_directions` called `fixtures.finding_payload(...)`, but `fixtures.py` never re-exports the factories (it imports them as `f`), so the test died with `AttributeError` before issuing any request. Switched to the top-level `finding_payload` factory, matching the file's existing import style.
- `test_corner_validations.py` — `test_a_valid_role_outside_the_endpoint_list_is_rejected` had the identical defect with `fixtures.acceptance_payload(...)`; switched to the top-level `acceptance_payload` factory.
- `test_corner_errors.py` — `test_same_day_assessment_is_admitted` used `assessed_on="2026-10-01T00:00:00Z"` while the logical clock sat at `DEFAULT_CLOCK = 2026-09-01T00:00:00Z`, so the setup call correctly returned 422 `ERR_ASSESSMENT_DATE_IN_FUTURE` — the literal was a full month in the future, not "same day". Replaced the drifted literal with `DEFAULT_CLOCK`. The implementation's check is `assessed_on > clock_now()` (strict), so same-instant assessment is admitted as PRD line 150 requires ("must not be later than the logical clock"), and the asserted `integrity_score == 88.0` follows from a 0-month decay of the 12-point impact.

**Fixes applied to `implementation/`:** none. The three code paths implicated by the failures (pagination `total_count`, `ERR_UNAUTHORIZED_ROLE` role gate, `ERR_ASSESSMENT_DATE_IN_FUTURE` date gate) all match PRD verbatim; the implementation was correct in each case and was left untouched.

**Notable detail:** the PRD's §2.10 cascade (shape → auth headers → role authorization → path existence → FK resolution) confirms the role gate must fire before the dangling `professional_id` in the committee's finding payload is resolved, which is exactly what `routes/findings.py` does — the RBAC test was asserting a genuine PRD rule, and `validate_error` checks the exact `error_id` plus HTTP status, so those passes are real.

### Orchestrator verification on disk (independent of the subagent's report)

- **Sweep evidence exists and is complete**: `results.1.json` … `results.8.json` all present (≈34 KB each, written 10:59). Parsed each: `passed=102 total=102 failed=0 errors=0 skipped=0` in **all 8 rounds**. The "Step 7 deletes its own results.json" hazard did not occur this time.
- **All three claimed test fixes verified against source**, not taken on trust:
  - `fixtures.scenario_pagination` now reuses `world["engagement"]` plus three `open_engagement` calls, with an inline comment explaining the count — four total, matching the docstring and the consuming tests.
  - `test_corner_rbac.py` and `test_corner_validations.py` import and call the top-level `finding_payload` / `acceptance_payload` factories (lines 12/55 and 11/71 respectively); no `fixtures.<factory>` call remains.
  - `test_corner_errors.py::test_same_day_assessment_is_admitted` passes `assessed_on=DEFAULT_CLOCK` and asserts `integrity_score == 88.0` (100 − 12 at 0-month decay) — consistent.
- **Implementation untouched by Step 7**: newest source mtime is 10:42 (`services/lifecycle.py`, `services/naf.py`), the sweep ran at 10:59, and `find workspace/implementation -newermt '2026-10-01 10:58' -type f` (excluding `results.*`) returns nothing. So the green sweep is not stale with respect to the code.

### Hazard carried into Step 8 (test-side fixes dominate)

Step 7 applied **3 test-side fixes and 0 implementation fixes**. Per the known "Step 7 fixes can be shadowed by test-side edits" hazard, a green sweep in this configuration proves the tests match the *code*, not that the code matches the *PRD* — the tests were bent to fit the implementation at three sites. The three implicated implementation paths are therefore named explicitly for Step 8's attention: (a) pagination `total_count`/`has_more` in the engagement list, (b) the `ERR_UNAUTHORIZED_ROLE` role-gate ordering in `routes/findings.py`, and (c) the strict `assessed_on > clock_now()` assessment-date gate. Each was confirmed PRD-verbatim during triage, but they are the paths where a PRD/impl divergence would now be invisible to the suite.

## Step 8: Finalize PRD — 2026-10-01T11:08:38.350Z

### Outcome: ZERO PRD edits — `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`

**Files**
- Produced: `/home/ubuntu/github/CodingPRD/tasks/task_3362_audit_independence_monitoring_partner_rotation_client_acceptance/workspace/PRD_FINALIZED.md`
- `PRD.md`: 376 lines / 83,689 bytes. `PRD_FINALIZED.md`: 376 lines / 83,689 bytes. Delta: 0 lines, 0.00% (`diff -q` reports IDENTICAL).

**Why zero edits.** `<step_7_diff>` records 0 implementation fixes and 0 deleted tests; all four fixes were test artifacts (one fixture counting bug, two `AttributeError` wiring bugs, one drifted date literal). Per the orchestrator caveat, I verified each implicated code path against `implementation/` by reading it. All three subjects match PRD verbatim, so there is nothing to pin and no PRD/impl divergence to correct. No edit was manufactured.

### Verification findings (a)/(b)/(c)

**(a) Engagement-list `total_count` / `has_more` / `limit`-default — MATCHES PRD §2.3 verbatim.**
- `total_count` is the filtered set size *before* slicing: `routes/engagements.py:63-71` filters, `core/db.py:98-101` (`paginate` returns `total = len(rows)` before `rows[offset:offset+limit]`), `core/response.py:30-37` emits it in `meta`.
- `has_more` = `(offset + len(rows)) < total` at `core/response.py:35` — true exactly when records remain beyond the returned page, including the empty-page-past-end case.
- Defaults: `routes/common.py:15-22` falls back to `C.PAGINATION_DEFAULT_LIMIT` / `C.PAGINATION_DEFAULT_OFFSET`; `core/constants.py:182-185` pins them to 10 and 0. Clamp range `[1,100]` at `routes/common.py:23-26` matches §2.3's "at least 1 and must not exceed 100".
- Ordering (asserted by `test_corner_entities.py:114-116`): `core/db.py:94-95` orders by insertion sequence, which is equivalent to `created_at` ascending because `created_at` is minted from the wall clock at insertion (`core/utils.py:22-23`, `core/db.py:46-59`) — no divergence from §2.3.
- The fixture fix (`test_helpers/fixtures.py:1368-1395`) only changed how many rows exist (5→4); the rule under test was already PRD-pinned.

**(b) `ERR_UNAUTHORIZED_ROLE` role gate before body-FK resolution in `routes/findings.py` — MATCHES PRD §2.10 verbatim.**
- `routes/findings.py:34-55` runs: shape (`V.*`, :34-41) → `require_role([IndependenceOfficer])` (:42) → `professional_id` FK (:43-45) → `engagement_id` FK (:46-49) → engagement-status gate (:50-52) → OCC version compare (:53-55). PRD §2.10 orders role authorization at position 3 and body-FK resolution at position 5, with state at 6 and OCC at 7 — the impl matches, including state-before-OCC. `core/auth.py:13-32` raises `ERR_UNAUTHORIZED_ROLE` (403) for a valid-but-unauthorized role.
- Sibling enumeration (same rule, same ordering everywhere): `routes/assignments.py:30-45`, `routes/acceptances.py:38-52`, `routes/naf.py:31-44`, `routes/reference.py:40-47`, `routes/threats.py:30-46`, `routes/reviews.py:31-47`, `routes/attestations.py:28-38`, `routes/engagements.py:43-52`, `routes/clock.py:20-22`. This also covers the third Step 7 fix (`test_corner_validations.py`, `acceptance_payload` wiring): `POST /audit/client-acceptances` gates at `routes/acceptances.py:44` before its FKs, and `POST /audit/clients` gates at `routes/reference.py:47`.
- No PRD silence here: §2.1 (line 15) plus the §2.10 cascade fully determine the code and status.

**(c) Assessment-date gate `assessed_on > clock_now()` (strict) — MATCHES PRD verbatim.**
- `routes/acceptances.py:104-110`: parses to a tz-aware datetime, then `if assessed_on > clock_now()` → `ERR_ASSESSMENT_DATE_IN_FUTURE` 422. Strict `>` means same-instant is admitted, exactly as §2.10 item 19 (line 150) "must not be later than the logical clock" and §2.5 (line 96) / §3.2 (line 184) require.
- The parallel submit-time re-check at `services/lifecycle.py:195-200` uses the identical strict `>`, so the two paths agree.
- Clock baseline `2026-09-01T00:00:00Z` at `core/clock.py:10`; the corrected test literal (`DEFAULT_CLOCK`) now exercises same-instant admission, and the asserted `integrity_score == 88.0` follows from 0-month decay of a 12-point impact under the DRAFT provisional (resolved-only) variant per §3.2 lines 186/190.

### Pre-edit search log

No edits were committed, so there is no per-edit log. For each of the three verification subjects I enumerated the full set of impl paths touching it before concluding:
- (a) subject "list pagination": `routes/common.py` (`pagination_args`, `list_response`), `core/response.py` (`send_list`, `_meta`), `core/db.py` (`ordered`, `paginate`, `new_row`), `core/constants.py` (pagination block), and every `list_response` callsite (all 12 list endpoints, grepped) — the semantics are shared globally, so any edit would have had global blast radius.
- (b) subject "role-gate ordering": `core/auth.py` and every `require_role` callsite (grepped; 50+ sites), plus each create endpoint's full check sequence.
- (c) subject "assessment dating": both `ERR_ASSESSMENT_DATE_IN_FUTURE` raises (grepped; `routes/acceptances.py:108`, `services/lifecycle.py:197`), `core/clock.py`, `core/validate.py:datetime_field`, `core/utils.py:parse_datetime`.

### Observed but deliberately NOT edited (outside the step-7-derived scope)

For transparency only; these were not touched because no Step 7 fix, deletion, or test edit implicates them:
- `routes/common.py:15-28` silently coerces an unparseable/out-of-range `limit` to the default or clamps to `[1,100]`, and a negative `offset` to 0; §2.3 states the bounds but not the enforcement response. No test in the suite exercises an out-of-range or non-numeric `limit`/`offset`.
- `services/lifecycle.py:197` raises `ERR_ASSESSMENT_DATE_IN_FUTURE` on the submit-time re-check (reachable only if an admin sets the clock backwards); §3.2 requires the condition but does not name the error for that path.

### Orchestrator verification on disk

`workspace/PRD_FINALIZED.md` exists (83,689 bytes, written 11:02); `diff -q PRD.md PRD_FINALIZED.md` reports no differences and both files hash to `md5 70066eddc52c08b3eb70d81cf64ceb18`. A byte-identical result is the *expected* outcome for a zero-edit step here (Step 7 had no implementation fixes and no deletions), and it is distinguishable from the known "Step 9 killed mid-flight leaves a silent no-op" failure mode because the zero-edit outcome was explicitly justified by the subagent's three verification findings rather than left unexplained.

**Two residual PRD silences were surfaced but are out of Step 8's scope** — they are handed to Step 9, whose full-scan mandate covers exactly this class: (i) the pagination out-of-range/non-numeric `limit`/`offset` coercion response is unpinned; (ii) the submit-time re-check in `services/lifecycle.py:197` raises `ERR_ASSESSMENT_DATE_IN_FUTURE` on a path the PRD describes without naming the error.

## Step 9: Complete PRD — 2026-10-01T11:29:33.925Z

Done. Here is the report.

### Artifact

`/home/ubuntu/github/CodingPRD/tasks/task_3362_audit_independence_monitoring_partner_rotation_client_acceptance/workspace/PRD_COMPLETED.md`

- Source: `PRD_FINALIZED.md` (it existed, so it was copied). 376 lines / 83,689 chars → 377 lines / 89,653 chars (**+1 line, +5,943 chars**).
- 25 hunks: 26 added lines, 25 replaced lines. All 5 top-level sections intact; no new sections.
- Nothing else touched: `PRD.md`/`PRD_FINALIZED.md` byte-identical, `implementation/*.py` mtimes unchanged, and the `__pycache__` dirs my in-process verification created were removed.

### Counts

**18 ambiguity-pins, 7 mismatch-revisions.**

### Changes (one bullet per hunk)

- §2.1 RBAC — revise — ambiguity — blank/whitespace-only header counts as missing; role matched after trimming — `core/auth.py:21,26`
- §2.1 RBAC — revise — **mismatch** — PRD asserted ownership checks compare a resource's FK to `X-User-ID`; no endpoint does any such comparison, authorization is role membership alone — `core/auth.py:27-31` (nothing consumes the returned `user_id`)
- §2.2 error envelope — insert — ambiguity — unknown path → 404 `ERR_INVALID_REQUEST`, unsupported method → 405 — `app.py:68-74`
- §2.3 Pagination — revise — ambiguity — coercion: unparseable → default (10/0), limit clamped into [1,100], negative offset → 0, effective values echoed; ordering is creation order with insertion-order tie-break, independent of filters — `routes/common.py:12-29`, `core/db.py:94-96`
- §2.4 Common fields — revise — ambiguity — `version` begins at **1** — `core/db.py:52`
- §2.4 Common fields — revise — ambiguity — a recompute refreshes `updated_at`/`version` only when the value actually moved — `core/db.py:68-77`, `services/independence.py:121-125`
- §2.5 Logical clock — revise — ambiguity — the clock call echoes the supplied text verbatim as `current_utc`; unparseable value → `ERR_INVALID_REQUEST`, clock unchanged — `routes/clock.py:21-26`, `core/clock.py:22-28`
- §2.6 Posture ladder — revise — **mismatch** — PRD said a suspended engagement's ACTIVE assignments are "excluded from workload ceilings"; they keep counting — `services/staffing.py:154-162`
- §2.9 Rounding precision — revise — ambiguity — a fractional amount for an integer-cent field is truncated toward zero, not refused — `routes/naf.py:35`, `services/naf.py:36`
- §2.10 #1/#2 cascade — revise — ambiguity — undeclared fields refused (submit and end carry no body at all); null/blank = absent; wrong-type refused, numeric/integral strings accepted; shape check precedes the auth check — `core/validate.py:28-53`, `routes/acceptances.py:80`, `routes/assignments.py:78`
- §2.10 #13 Review buffering — revise — ambiguity — buffer is a **conjunctive** proximity test, not a simple "5 days after the latest due_on" — `services/calc.py:185-201`
- §2.10 #19 Assessment dating — revise — ambiguity — names the error for the submit-time re-check — `services/lifecycle.py:195-200`
- §3.2 Acceptance — revise — ambiguity — submit-time re-check rejected with `ERR_ASSESSMENT_DATE_IN_FUTURE` (422) — `services/lifecycle.py:197-200`
- §3.2 Acceptance — insert — ambiguity — `risk_tier` bands: `LOW` <25, `MODERATE` 25–<50, `HIGH` 50–<70, `SIGNIFICANT` ≥70 — `core/constants.py:118-120`, `services/calc.py:77-85`
- §3.2 Activation gates — revise — ambiguity — risk band re-tested only on direct `SUBMITTED` approval, dropped on `CONDITIONAL`→approve; the assignment/finding gate is scoped to findings **on that engagement** and surfaces as `ERR_INVALID_STATE` (409) — `services/lifecycle.py:211-231,275-287`
- §3.3 Workload step 2 — revise — **mismatch** — assignments on suspended engagements count in the base sum — `services/staffing.py:154-162`
- §3.4 Cooling-off bar — revise — **mismatch** — the bar is anchored at `effective_on` and runs while the *clock* is inside the window; a start on/after `cooling_off_end_on` is still barred (not "closed at both ends") — `services/threats.py:131-151`
- §3.5 Findings — revise — ambiguity — remediation windows pinned: `LOW` 90, `MEDIUM` 60, `HIGH` 30, `CRITICAL` 15 days — `core/constants.py:167`, `services/calc.py:178-179`
- §3.5 Findings — revise — ambiguity — `START_REMEDIATION` recomputes `remediation_due_on` from `discovered_on`, not the clock — `services/findings.py:58-60`
- §3.5 Findings — revise — **mismatch** — PRD said live findings bar staffing onto a new engagement of the same client; they do not — a live `HIGH`/`CRITICAL` finding bars *activation* of the engagement whose ACTIVE assignment names that professional — `services/assignments.py:35-112` (no finding check), `services/lifecycle.py:220-225`
- §3.6 Non-audit services — revise — ambiguity — prohibited list pinned verbatim: `BOOKKEEPING`, `INTERNAL_AUDIT_OUTSOURCING`, `VALUATION`, `IT_SYSTEMS_DESIGN`, `ACTUARIAL`, `MANAGEMENT_FUNCTION`, `LEGAL` (`TAX_PREPARATION`/`TAX_ADVISORY`/`OTHER` never flagged) — `core/constants.py:171-174`, `services/naf.py:22-25`
- §3.6 Non-audit services — revise — **mismatch** — a flagged service counts against every engagement of its client too, not only the one it names — `services/independence.py:44-48`
- §3.8 Reviews — revise — **mismatch** — `inspection_body` is only null by omission; a value sent with a non-inspection review type is stored as given — `routes/reviews.py:35-36`, `services/reviews.py:19-23`
- §3.8 Reviews — revise — ambiguity — buffer test restated conjunctively — `services/calc.py:185-201`
- §4 Endpoints — insert — ambiguity — per-collection filter parameter sets and matching semantics (string equality; booleans accept true/1/yes and false/0/no; nulls accept none/null/empty; unknown params ignored) — `routes/common.py:32-51` plus each route's mapping

All five known starting points were verified against code and pinned; I also exercised the implementation in-process (Flask test client) to confirm the pagination coercion, the clock echo, the shape-before-auth precedence, the submit-time date re-check (422), the suspended-engagement workload counting, the cooling-off upper-bound behavior, the review-buffer conjunction, the absent staffing bar, and the activation gate's `ERR_INVALID_STATE`.

### Dead-code audit

Grepped callsites for every defined helper in `core/validate.py`, `core/auth.py`, `core/db.py`, `core/utils.py`, `core/errors.py`, `routes/common.py` and every `services/*` module.

**No PRD-required check is defined-but-never-called.** Every gate in the cascade is reachable: `_cap_check` (both `SUBMIT_FOR_APPROVAL` and `APPROVE`), `_activation_gates`, `review_buffer_conflict`, `cooling_off_bar`/`material_interest_bar`, `recompute_affiliate`, `_unresolved_critical`/`_has_unresolved` all have live callsites.

Dead helpers found (utilities only, no PRD prose added for them):
- `core/validate.py:138` `raw_datetime`; `core/utils.py:65,137` `parse_date_only`, `to_decimal`; `core/db.py:90` `rows_where`; `core/clock.py:18` `current_iso`; `core/errors.py:86,90` `invalid_request`, `not_found`; `routes/common.py:74,78,84` `clients`, `engagement_client`, `engagement_of`
- `services/independence.py:173` `propagate_client` — imported at `services/findings.py:11` but never invoked; its effect is inlined in `cascade_finding_posture`
- `core/errors.py:9` `ERR_ASSESSMENT_NOT_FOUND` — mapped to 404 in `ERROR_HTTP` but never raised by any path (no endpoint has an assessment path segment), so §2.11/§5 list an unreachable code. I left the catalogue alone rather than delete rows; flagging it here as the one catalogue over-claim.
- 15 enum tuples in `core/constants.py` (`CLIENT_STATUSES`, `RISK_TIERS`, `ACCEPTANCE_STATUSES`, `ROUNDING_UNIT_CENTS`, …) are declared but never referenced — vocabulary documentation, not checks.

### Orchestrator verification on disk

- **The `cp`-then-edit silent-no-op hazard is ruled out**: `wc -l -c` gives `PRD.md` 376/83,689, `PRD_FINALIZED.md` 376/83,689, `PRD_COMPLETED.md` **377/89,653**. `diff -q PRD_FINALIZED.md PRD_COMPLETED.md` reports the files differ, so the +5,943 chars are real edits and not an unmodified copy.
- **`implementation/` was NOT touched by Steps 8 or 9**: `find workspace/implementation -type f \( -name '*.py' -o -name '*.sh' -o -name '*.txt' \) -newermt '2026-10-01 10:58'` returns nothing; the newest source mtime remains `services/lifecycle.py` at 10:42. The Step 7 sweep (10:59) therefore remains valid with respect to the code — no re-run is forced by a post-sweep write.
- No stray artifacts: no `__pycache__`, `*.db`, `*.sqlite*` or non-`results` `*.json` anywhere under `implementation/`.

**Seven genuine PRD↔implementation mismatches were found and corrected** (not just ambiguities): the RBAC ownership claim in §2.1, the suspended-engagement workload exclusion in §2.6/§3.3, the cooling-off bar's upper bound in §3.4, the findings-bar-staffing rule in §3.5, the client-level NAF posture count in §3.6, and the `inspection_body` handling in §3.8. Each is a place where the original PRD asserted behavior the implementation does not exhibit — the strongest doc-generator feedback produced by this task, because a fresh implementer reading the pre-Step-9 PRD would have built something different at each of those six sites.

**One unreachable error code flagged**: `ERR_ASSESSMENT_NOT_FOUND` is catalogued in PRD §5 and mapped to HTTP 404 but is never raised by any implementation path. Recorded as a catalogue over-claim; the PRD catalogue rows were deliberately left intact rather than pruned.

## Final verification: orchestrator-run 8-round stability sweep — 2026-10-01T11:33:38.858Z

The orchestrator re-ran the full 8-round parallel sweep itself against the frozen final state (rather than relying on the Step 7 evidence), because Steps 8 and 9 both read `implementation/` and Step 9 additionally exercised it in-process — any post-sweep write would have invalidated the earlier results. Mtime inspection first confirmed no source file changed after the Step 7 sweep (newest source mtime still 10:42), and the fresh sweep then re-confirmed it end-to-end.

Command (all 8 rounds launched concurrently, joined with `wait`, per-round free port claimed by the runner's file-locked registry):

```bash
rm -f results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd .../workspace/implementation && bash start.sh" \
    --test-dir       .../test_suite \
    --isolation      per-test-server \
    --timeout        120 --test-timeout 30 \
    --results-file   .../workspace/implementation/results.${i}.json &
done
wait
```

Result — every round, written 11:33:

| Round | passed | total | failed | errors | skipped |
|---|---|---|---|---|---|
| 1 | 102 | 102 | 0 | 0 | 0 |
| 2 | 102 | 102 | 0 | 0 | 0 |
| 3 | 102 | 102 | 0 | 0 | 0 |
| 4 | 102 | 102 | 0 | 0 | 0 |
| 5 | 102 | 102 | 0 | 0 | 0 |
| 6 | 102 | 102 | 0 | 0 | 0 |
| 7 | 102 | 102 | 0 | 0 | 0 |
| 8 | 102 | 102 | 0 | 0 | 0 |

**Pipeline complete.** Final artifact inventory verified against the output contract — all present: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`; `test_helpers/` (8 modules) and `test_suite/` (`conftest.py` + 17 test files, 102 tests); `workspace/` with `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, and `implementation/` (`start.sh`, `requirements.txt`, `app.py`, 35 source modules, 46 routes, and `results.1.json`–`results.8.json`).
