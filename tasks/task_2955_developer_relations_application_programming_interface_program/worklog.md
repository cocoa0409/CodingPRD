## Step 1: Create task directory — 2026-09-05T21:44:34.156414582Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2955_developer_relations_application_programming_interface_program and its workspace/ subdirectory. Index 2955 pre-assigned by the orchestrator invocation; no index scan performed.

## Step 2: Generate scaffold — 2026-09-05T23:26:50.902415985Z

All three scaffold artifacts are complete and lint-clean.

## Files (all parse as YAML, non-empty)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3269 | 146 549 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2533 | 153 629 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4934 | 288 100 |

`SCAFFOLD.yaml` top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key leaked into it; each design file has exactly one top-level key. `worklog.md`, `workspace/`, and every `.scratch/step*` dir other than my (unused, still empty) `step2` are untouched.

## §1.0–§1.7 surface
11 entities (Developer, ApiProduct, ApiVersion, AccessApplication, QuotaAssignment, UpgradeRequest, UsageWindow `common_fields:false`, SandboxLease, ViolationCase, SupportCase, FeedbackItem) · 12 state machines · 2 concurrency rules · 9 calculations · 57 validations (priorities 1–57) · 63 endpoints · 65 errors · 6 roles. Profile: Compliance/audit + Quota/allocation, `flat` topology, `parallel` state shape, `role_model: segregation_of_duties`, `immediate` consistency, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`.

## §1.8 — 9 rules / 25 instances
`dual_variant_calc` 2 · `combinatorial_formula` 3 · `non_linear_state_machine` 3 · `transitive_cascade` 3 · `priority_pair_validation_conflict` 2 · `boundary_precision_check` 3 · `cross_entity_state_dependency` 3 · `resource_temporal_overlap` 3 · `compensating_invariant` 3.

## §1.9 — 9 sections / 84 instances (58 full recipes + 26 `excluded_because` stubs)
entities 12 (12/0) · state_machines 17 (9/8) · calculations 11 (7/4) · validations 10 (7/3) · endpoints 6 (6/0) · errors 18 (10/8) · rbac 4 (4/0) · cross_cutting_complexity_layers 5 (2/3) · consistency_model 1 (1/0). All 109 instance names are unique across the union of both files; every stub cites an existing §1.8 instance name and carries no `test_recipe`.

## Lint (first run, verbatim)
```
Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     11
  §1.8 instances scanned:     25
  §1.9 instances scanned:     58
  Calls scanned (§1.8+§1.9):  1124

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications
- **Error-catalog coverage is complete**: all 65 error ids are now reachable from §1.8 or §1.9. The errors section uses grouped sweeps (auth/identity/ownership, per-family 404s, pool exhaustion in both dimensions) plus 8 stubs deferring to §1.8.
- **Header-level refusals are asserted, not encoded**: `ERR_MISSING_AUTH_HEADERS`, `ERR_UNKNOWN_ROLE`, `ERR_UNKNOWN_DEVELOPER_IDENTITY` and `ERR_UNAUTHORIZED` cannot appear as structured calls (lint check (b) requires `as:` ∈ the endpoint's roles), so they are expressed as header substitutions on a valid baseline call in `assert:` lines. `ERR_NOT_RESOURCE_OWNER` and both segregation-of-duties rules *are* real calls, exploiting the opaque operator identity space (`as: PlatformAdmin, as_user_id: drm-1`).
- **Every numeric literal was recomputed from the formulas**, e.g. uncertified PARTNER 2250/6750/67500 (trust 56 → 0.75), certified 3000/9000/90000; STANDARD 450 → ceiling 1200, waterfall grant 750, burst 2400; pool-clamped provisioning 750 → burst 2250; roadmap scores 10.48 / 6.55 / 3.93 / 3.93 at factor 1.0475 after the DECLINE compensation drops demand to 23.75; deprecation 30 non-breaking vs 60 breaking (sunsets 2026-08-31 / 2026-09-30); justification bound probed at 119 (fail) / 120 (pass).
- **Eight SCAFFOLD.yaml self-consistency fixes** were made while writing the designs (checkpoint step 4 UPHELD→UPHELD_FINAL gate, priority 16 SupportCase edges, priority 32 vs 33 duplicate-window split, `quota_provisioning` step renumbering in QuotaAssignment field docs, `sunset_at` → `source: computed`, rate-limit-breach double-count wording, checkpoint step 5's 30-day reset gate + `last_reset_at`).
- **Known leak to strip**: `scenario:` still contains the literal line "Generate task harder than expert level!" because the task said to use the scenario verbatim. Per the known failure mode, remove that one line before Step 3/4 so it cannot reach PRD.md.

**Orchestrator note (Step 2 post-check):** the reported leak is NOT present — `grep -n "harder than expert"` over all three scaffold files returns nothing, and `SCAFFOLD.yaml`'s `scenario:` block begins at "2955. Developer Relations...". No strip was needed. Task dir, `workspace/`, and `worklog.md` verified intact after the subagent exited.

## Step 3: Copy shared files — 2026-09-05T23:26:50.917684672Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T23:45:00.934747651Z

PRD generation complete. Sole output: `workspace/PRD.md` — **548 lines / 15,347 words**, ending at the last row of the §5 error table with no audit footer. Scratch dir `.scratch/step4/` removed; sibling scratch dirs (`step2`, `step5`–`step9`) verified intact; no other file created, moved or modified.

## Section list

- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Revision Counters · 2.5 The Logical Programme Clock · 2.6 Rejection Precedence: The Validation Ladder · 2.7 Path Resolution for Sub-Resource Reads and Writes · 2.8 Optimistic Concurrency · 2.9 Custody of Finite Capacity Pools · 2.10 Cascades, Compensation and Server-Initiated Movement · 2.11 Numeric Precision, Rounding and Threshold Inclusivity · 2.12 Standing as the Master Gate
- §3 Business Logic & Workflows — 3.1 Registration/Docs/Sandbox · 3.2 Catalogue, Version Lifecycle, Deprecation · 3.3 Access Applications · 3.4 Entitlement Provisioning · 3.5 Metering and Throttling · 3.6 Upgrade Requests and the Allocation Waterfall · 3.7 Enforcement, Appeal and Revocation · 3.8 Support, Communication and Service Credits · 3.9 Ecosystem, Directory and Feedback Roadmap · 3.10 The Programme Checkpoint
- §4 Endpoint Definitions (4-column table, 63 rows)
- §5 Error Code Catalogue (2-column table, 65 rows)

## Coverage verified by script against SCAFFOLD.yaml

- **Endpoints**: 63 scaffold paths, 63 present in §4 table, 0 missing. Table pipe-count check: 65 five-pipe lines = header + separator + 63 rows (exactly 4 columns).
- **Errors**: 65 ids, 65 present, 0 missing. 67 three-pipe lines = header + separator + 65 rows (exactly 2 columns). Both alternation-style rungs (priorities 6 and 7) have every constituent id present.
- **Validations**: 57 blocks, priorities 1–57 all distinct, all `error_id`s present in prose; ladder ordering stated explicitly in §2.6 in 8 bands with `applies_to` scopes.
- **State machines**: 12 (`Developer.onboarding_state`/`standing`/`directory_state`, `ApiProduct`-less, `ApiVersion`, `AccessApplication`, `QuotaAssignment.entitlement_state`/`throttle_state`, `UpgradeRequest`, `ViolationCase`, `SupportCase`, `SandboxLease`, `FeedbackItem`), 58 transitions; every from/to state name appears in the PRD.
- **Calculations**: all 9 (`developer_trust_score` both variants, `quota_provisioning`, `usage_consumption_attribution`, `sla_service_credit`, `upgrade_allocation_waterfall`, `feedback_roadmap_prioritisation`, `deprecation_notice_requirement`, `violation_penalty_points`, `support_response_commitments`) rendered as prose with every constant, rounding mode and comparison inclusivity.
- **Endpoint side effects**: all 57 scaffold bullets expressed; all 16 structured output field names of the computed endpoints (allocation run, checkpoint, clock) present in backticks.

```
Field coverage check:
- entities[].fields: 156 required, 156 present, 0 missing
- endpoints[].request_body: 62 required, 62 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 57 checked, 57 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_api_product_version / expected_quota_assignment_version + ERR_STALE_PRODUCT_VERSION / ERR_STALE_ASSIGNMENT_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 58 checked, 58 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 57 checked, 57 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 57 checked, 57 expressed, 0 missing
- entities[].fields[] structured content: 156 checked, 156 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (BURST_ISOLATED/BURST_INCLUSIVE, onboarding_snapshot/enforcement_audit, PARTNER_TICKET/PLATFORM_INCIDENT, APPROVE/REJECT directory, ACCEPT/DECLINE roadmap, UPHELD/DISMISSED, GRANTED/PARTIALLY_GRANTED/DEFERRED, suspend/reinstate, NOT_LISTED->PENDING_REVIEW / DELISTED->PENDING_REVIEW), 9 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1194
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Judgement calls worth flagging to the implementer-side steps

- `TIER_MAX_SENSITIVITY` is referenced by `AccessApplication.data_access_limit` but never defined in the scaffold's constants; derived from validation priority 24 and stated explicitly as `PUBLIC` at `SANDBOX`, `PERSONAL` at `STANDARD`, `FINANCIAL` at `PARTNER` and `PRIVILEGED`.
- `BURST_CREDIT_MINUTES` / `BURST_CREDIT_WINDOWS` name the same value 10 in two places; rendered as "`burst_rpm` multiplied by 10" rather than inventing an identifier.
- Two scaffold internal contradictions were rendered faithfully rather than resolved: the docs-acknowledgement self-loop (submitted `docs_version` must equal revision 2 **and** be strictly greater than `docs_version_acknowledged`), and the certification-expiry comparison (validation 40 says strictly after the clock; the directory-submission precondition says at or after — the PRD states the strict form as the gate and the state-machine wording alongside it).
- An `UPHELD` adjudication leaving `violation_points` below 50 has no scaffold transition back to `GOOD_STANDING`; the PRD states standing remains `UNDER_REVIEW`.
- §3 has 10 subsections (skill guidance is 5–9); the scaffold's 12 state machines and 9 calculations did not compress further without losing rule density.

**Orchestrator note (Step 4 truncation post-check):** PRD.md is 548 lines; sections are §1 (L3), §2 (L11), §3 (L185), §4 (L408), §5 (L478). The file ends on the final row of the §5 error table (`| ERR_POOL_BELOW_ALLOCATED | 422 |`) — a genuine section boundary with all 65 rows present, not a mid-sentence cut. No regeneration needed. Difficulty-directive leak check on PRD.md (`grep -i "harder than expert|expert level"`) returns nothing.

## Step 6: Generate implementation — 2026-09-06T00:25:32.943480516Z

_(Steps 5 and 6 ran concurrently; Step 6 returned first, so its entry is recorded above Step 5. The concurrency was deliberate — it keeps the implementation generator physically unable to read `test_suite/`, which did not exist when it started.)_

Done. The implementation is complete, compiled, and verified end-to-end.

## Files written

`workspace/implementation/` — 4,610 lines total, 29 files.

**Core (983 lines):** `app.py` 82, `constants.py` 247, `db.py` 137, `errors.py` 100, `middleware.py` 100, `response.py` 95, `serializers.py` 270, `validation.py` 152
**`services/` (1,062):** `common.py` 221, `quota.py` 267, `enforcement.py` 158, `usage.py` 112, `support.py` 98, `checkpoint.py` 92, `trust.py` 78, `feedback.py` 74, `lifecycle.py` 62, `__init__.py` 0
**`routes/` (2,254):** `assignments.py` 398, `applications.py` 342, `support.py` 322, `catalog.py` 301, `violations.py` 255, `developers.py` 251, `leases.py` 174, `feedback.py` 163, `system.py` 48, `__init__.py` 0
**Launcher:** `start.sh` 10 (guards the flask import, installs on demand, then `exec python3 app.py`), `requirements.txt` 1

## How the surface is organised

- **63 endpoints** as 9 blueprints, confirmed by walking Flask's `url_map`: catalog 12, assignments 11, developers 8, applications 7, violations 6, support 6, leases 5, feedback 5, system 3 = 63 exactly.
- **65 error ids** live in one table in `errors.py` (`ERROR_STATUS` id→status plus `DEFAULT_MESSAGES`); `ApiError` is raised anywhere and rendered by a single `app.errorhandler`, so no route can invent a status.
- **57 validations in ladder order.** Bands 1–4 (auth) are enforced once in `middleware.authorise` via the `@endpoint(roles)` decorator, so every route inherits rungs 1–4 identically. Band 5 (shape) is `validation.body()`, which parses and range-checks before any lookup. Bands 6–7 (existence) are `middleware.lookup`, band 8 `require_owner`, bands 9–10 (OCC) are explicit `expected_*_version` comparisons in the two parent routes. Bands 11–19 (state), 20–28 (safety/SoD) and 29–57 (temporal/fiscal) sit inline in each route in strict numeric sequence — the ordering is the code's statement order, which is what makes rejection precedence auditable.
- **12 state machines** are advanced only inside route handlers, with cascades delegated to `services/lifecycle.py` (sunset), `services/enforcement.py` (standing cascade, release-once across SUSPENDED→RETIRED) and `services/checkpoint.py` (the 6-step checkpoint in its mandated order).
- **9 calculation formulas** are each owned by one service: `quota.py` (sustained/burst/allowance chain + the upgrade waterfall), `usage.py` (attribution variant, effective-allowance ratio, throttle write-through), `trust.py` (both score variants), `support.py` (cadence, uplift, per-entitlement-rounded incident credits), `enforcement.py` (penalty points), `feedback.py` (raw impact → demand index → re-score), `lifecycle.py` (notice period). `Decimal` + `ROUND_HALF_UP` for scores/credits, floor for rates and durations, ceil for burst uplift.
- **State is in-memory only** — one `Store` singleton of plain dicts, clock seeded at `2026-08-01T00:00:00Z`, zero seeded entities, no file or external persistence, so each `start.sh` is a clean programme.

## compileall

`python3 -m compileall -q .` → clean, `COMPILE_OK`. `__pycache__` dirs removed afterwards.

## Smoke test

`PORT=53791 bash start.sh` booted first try (pid recorded to a scratch file). I ran an 84-check end-to-end walk covering registration, docs ack, catalog, lease overlap, the full application review→decide path, provisioning, activation, usage ingestion, upgrade allocation, ecosystem, feedback, both support kinds, enforcement with appeal, deprecation, checkpoint and 7 ladder spot-checks: **all 84 passed** (`ALL SMOKE CHECKS PASSED`). Server killed by its exact recorded pid; port 53791 confirmed free. `.scratch/step6` removed; the sibling `step2/step5/step7/step8/step9` scratch dirs are untouched. Nothing outside `workspace/implementation/` was written.

Six formulas reproduce the PRD's own worked examples exactly, which is the strongest available evidence the chains are right:
- sustained rpm 3000 × 0.75 trust × 0.90 scope = **2025**, burst 2025×3 = **6075**
- required notice for a breaking FINANCIAL version with one ACTIVE PARTNER entitlement = **150** days (PRD §224's illustration)
- incident credit 4,000,000 × 0.10 × 1.5 uplift × 780 min ÷ 1440 = **325,000**
- RESALE × HIGH = 25 × 3 = **75** penalty points
- raw_impact 40 × 1.50 + 5.00 = **65.00** (PRD §388's illustration), priority 65 × 1.13 = **73.45**
- BURST_ISOLATED charged 3,000,000 − 1,000 = **2,999,000**, ratio 0.74975 → NORMAL

One thing worth flagging for whoever reviews the tests: `/access-applications/{id}/decide` is PlatformAdmin-only and `claim-review` is DevRelManager-only, so `ERR_SEGREGATION_OF_DUTIES` on that workflow is only reachable when the same `X-User-ID` is presented under both roles. My implementation compares user ids, not roles, so it trips correctly in that case (verified, 422).

## Step 5: Generate unit tests — 2026-09-06T00:35:30.924301386Z

Step 5 complete. Test infrastructure and suite are at the task root.

## Files written

`test_helpers/` — 2,316 lines, 9 files
- `types.py` 442 — `UserRole`/`ALL_ROLES`, 26 domain enums, decision literals, TypedDicts for all 11 entities (measurement entity `UsageWindow` deliberately carries only `id`/`created_at`)
- `api_errors.py` 152 — `ApiError` with all 65 catalogue constants + `ERROR_HTTP_STATUS`, registered via `set_error_http_status_map` at import so `validate_error` also asserts status
- `constants.py` 159 — `CLOCK_DEFAULT = "2026-08-01T00:00:00Z"`, operator IDs, every PRD numeric table (tier bases, monthly caps, ceilings, trust bands, burst factors, notice baselines, justification floors, penalty/remediation/appeal windows, response/cadence/credit tables, feedback weights), and three exact-length justification strings (88/250/582 chars)
- `api_client.py` 316 — `canonical_instant()` normalising every ISO-8601 instant to millisecond width (guards the known timestamp-precision false-failure mode) + one method per PRD §4 endpoint (63)
- `test_users.py` 87 — role header builders (Developer entity-backed, distinct `X-User-ID` per operator) plus malformed builders; blank cases send `""`, never whitespace
- `factories.py` 410 — payload builders for all 35 POST endpoints, field names extracted from the design yamls' own `payload:` lines; money/decimals emitted as JSON numbers, instants as full instants
- `assertions.py` 187 — instant-aware `assert_fields`, common/measurement field gates, version bump/unchanged, pool-availability, trust-score and entitlement-dimension helpers
- `fixtures.py` 562 — `Programme` setup façade (~50 verbs, all via `get_success_data`) + 12 fixtures including `onboarded_developer`, `partner_entitlement`, `provisioned_partner_entitlement`
- `__init__.py` 1

`test_suite/` — 8,648 lines, `conftest.py` (13) + 16 test files, **210 tests**: `test_01` 530/13, `test_02` 983/24, `test_03` 308/10, `test_04` 377/10, `test_05` 533/13, `test_06` 460/11, `test_07` 443/11, `test_08` 539/12, `test_09` 502/12, `test_10` 472/12, `test_11` 521/9, `test_12` 403/9, `test_13` 900/15, `test_14` 407/7, `test_15` 525/14, `test_16` 732/28.

## Coverage per queue

- **Queue A (difficulty, §1.8): 69 tests** — all 25 instances across 9 rule_ids covered at ≥2 tests each.
- **Queue B (corner, §1.9): 141 tests** — 57 of 58 non-stub instances across 9 sections at ≥1 test each. The 26 `excluded_because:` stubs were not translated.
- Every docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line copied verbatim; audit reports 0 untagged, 0 dual-tagged, 0 dangling, 0 stub-tagged, 0 duplicate test names, 0 `skip`/`xfail` markers.

## Skipped instances (1)

- `Corner/state_machines/docs_reacknowledgement_self_loop_awards_docs_points_once` — **non-unique derivability**. PRD §3.1 (line 193) requires the submitted `docs_version` to "equal the platform's current documentation revision, which is **2**", while a repeat acknowledgement is "admissible only when the submitted `docs_version` is strictly greater than the currently recorded `docs_version_acknowledged`". Those two conditions are mutually exclusive after a first acknowledgement, so the `DOCS_ACKNOWLEDGED → DOCS_ACKNOWLEDGED` self-loop is unreachable and its outcome is not derivable. Left as a gap, no placeholder.

Additionally, several individual assertions inside otherwise-emitted instances were dropped for PRD silence rather than weakened: `revision_round == 0` after first submission (PRD says 1), `submitted_at` (not a PRD field), `released_at == null` after checkpoint expiry (PRD sets it), post-upgrade `burst_credit_balance` recomputation (PRD silent), and `AccessApplication.version` (no such field). Design recipes with setup defects (missing certification step, directory review without a validated lease, revocation without §3.7's RESTRICTED + ≥100-points/UPHELD_FINAL precondition, tie-breaks with a frozen clock, a usage window recorded before the clock advanced) were fixed in setup, not by relaxing assertions.

## Verification

- `python3 -m compileall -q test_helpers test_suite` → **clean** (no output, exit 0) — no truncation anywhere.
- `pytest --collect-only` → **210 tests collected in 0.34s**, no errors; `--setup-plan` → no fixture errors, so all helper imports resolve.
- `ls` confirms `test_helpers/` and `test_suite/` exist **at the task root**; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — neither directory was written there. `workspace/implementation/` was never read or written. `worklog.md`, `PRD.md`, `INSTRUCTION.md` and the three SCAFFOLD files are untouched. Scratch confined to `.scratch/step5/` (sibling step dirs intact); `__pycache__`/`.pytest_cache` removed.

**Orchestrator note:** verified independently that `test_helpers/` and `test_suite/` are at the task root and absent from `workspace/` (which holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`).

## Step 7: Run tests and iterate — 2026-09-06T00:57:03.733564121Z

All 8 rounds green at 210/210.

## Summary

**Iterations run:** 2 (iteration 1 = 206/210 in all 8 rounds, deterministic; iteration 2 = 210/210 in all 8 rounds)

**Tests deleted:** none. All 4 failing tests passed STEP 1a (PRD verbatim coverage) and STEP 1b (unique derivability).

**Fixes applied to `test_helpers/`:** none. No shared fixture/factory/assertion bug — the failures were per-test setup ordering, not a common upstream helper defect.

**Fixes applied to `test_suite/`** (3 tests, all the same STEP 2 test bug: setup called `programme.onboarded_developer()` while the product catalogue was still empty, so the acknowledgement could not satisfy PRD §3.1 "the submitted `tos_version` must equal the `required_tos_version` of at least one product in the catalogue" — the PRD-faithful implementation correctly rejected it):
- `test_suite/test_07_entitlement_state_and_pool_conservation.py::test_a_decided_application_refuses_both_a_second_decision_and_a_change_request` — moved `create_product()` / `grantable_version()` ahead of `onboarded_developer()`.
- `test_suite/test_07_entitlement_state_and_pool_conservation.py::test_a_dismissed_violation_case_refuses_an_appeal_and_records_none` — added a `create_product()` before onboarding (test creates no product at all).
- `test_suite/test_15_feedback_scoring_and_roadmap.py::test_feedback_creation_resolves_its_author_before_its_product` — same, added `create_product()` before onboarding. The test's own assertion (`ERR_DEVELOPER_NOT_FOUND` for two unresolvable body ids) is untouched.

**Fixes applied to `implementation/`** (1 real defect):
- `workspace/implementation/services/checkpoint.py`, `run_checkpoint()` step 1 — sandbox-lease expiry set `state`/`closed_reason` but never `released_at`. PRD §3.1: "a checkpoint run whose clock has reached `expires_at` moves it `ACTIVE → EXPIRED` with `released_at` set and `closed_reason` `CHECKPOINT_EXPIRY`". The developer-release and standing-cascade paths already set it; only the checkpoint path was missing it.

**Final sweep numbers:** rounds 1–8 all **210/210 passed**, 0 failed, 0 errors. `results.1.json`–`results.8.json` are left in `workspace/implementation/`; `SWEEP_DONE` and the `round.$i.log` files were removed. `worklog.md` and `PRD.md` untouched.

**Orchestrator note (independent verification):** re-read all 8 `results.$i.json` directly — each reports `passed 210 / failed 0 / total 210 / errors 0`. `PRD.md` still 548 lines and `worklog.md` carries no subagent-written step heading, both as required. Step 8 is NOT skipped: Step 7 applied 1 `implementation/` fix and 3 `test_suite/` fixes, so the skip condition (zero fixes, zero deletions) does not hold.

## Step 8: Finalize PRD — 2026-09-06T01:04:55.261165647Z

Done. `PRD_FINALIZED.md` written with exactly one edit.

**Line counts:** PRD.md 548 → PRD_FINALIZED.md 548 lines (0.0% line delta; one line revised in place, §3.1 line 193).

**Changes**
- §3.1 "Acknowledging the documentation" — revise (append to existing sentence) — pins the rejection error for the acknowledgement's submitted-version checks as `ERR_INVALID_REQUEST` (HTTP 400), notes they run after the path developer resolves and before the ownership check, and spells out that an empty catalogue therefore matches no `required_tos_version` — `implementation/routes/developers.py:114-134` (`invalid(...)` at :117 and :131, `require_owner`/`require_not_revoked` at :133-134, `_developer()` lookup at :112).

**Per-edit pre-edit search log**

Edit 1 — acknowledgement rejection code
- (a) Subject: how the onboarding-acknowledgement endpoint rejects a `docs_version`/`tos_version` that fails its cross-resource checks, and where that rejection sits relative to path resolution and ownership. Traced to the three `test_suite/` fixes in `<step_7_diff>` (all three failed because the PRD-faithful impl rejected `onboarded_developer()` while the catalogue was empty; PRD stated the rule but never named the error).
- (b) Paths enumerated: `routes/developers.py:105-142` (the handler itself — both `invalid()` call sites, the REGISTERED/recorded-None vs. repeat branch, ordering of `_developer()` → version checks → `require_owner` → `require_not_revoked`); `errors.py` (`invalid()` → `ERR_INVALID_REQUEST` = 400; confirmed `ERR_TOS_VERSION_STALE`/`ERR_DOCS_NOT_ACKNOWLEDGED` are 422 and distinct); repo-wide grep for `TOS_VERSION_STALE|DOCS_NOT_ACKNOWLEDGED|required_tos_version|docs_version_acknowledged|tos_version_accepted` — the 422 pair is raised **only** from `services/common.py:159-173` (application submit / provisioning / lease creation), never from the acknowledgement, so the new sentence cannot collide with rungs 22–23 of §2.6; `constants.py:102` (`CURRENT_DOCS_VERSION = 2`); `routes/catalog.py:50,79,120,143` (where `required_tos_version` is set/defaulted, confirming the catalogue is the only source of matchable versions); `services/trust.py:37` (reads `docs_version_acknowledged`, unaffected).
- (c) Wording adjustment: I dropped an earlier draft that called these "request-shape" (band 2 / rung 5) rejections. The impl resolves the path developer first, so a bad `tos_version` plus an unknown developer id yields `ERR_DEVELOPER_NOT_FOUND`, not 400; the band-2 framing would have been a false universal claim. Final wording names the error id only and states the ordering explicitly ("once the developer named in the path has resolved and before the ownership check"), which matches the handler exactly.

**Items deliberately not patched**
- `implementation/services/checkpoint.py` `released_at` fix: PRD §3.1 already says a checkpoint expiry moves the lease `ACTIVE → EXPIRED` "with `released_at` set and `closed_reason` `CHECKPOINT_EXPIRY`". Step 7 changed the impl to match the PRD, so the prose stays verbatim (§3.10 step 1's shorter restatement is reinforcing, not contradicting — verified against the developer-release and standing-cascade paths, which already set `released_at`).
- `test_07`/`test_15` setup-ordering fixes beyond the acknowledgement rule: pure fixture bugs. In particular `test_feedback_creation_resolves_its_author_before_its_product` is already determined by §2.6 rung 7 plus the field declaration order in §3.9 — verified `routes/feedback.py:47-49` resolves `developer_id` before `api_product_id`.
- No `test_helpers/` fixes and no test deletions in Step 7, so nothing else traces.

`implementation/results.1-8.json` (8 files) left untouched; scratch dir `.scratch/step8` removed (parent `.scratch` untouched).

## Step 9: Complete PRD — 2026-09-06T01:34:59.701656395Z

Run as **three sequential file-partitioned passes** over one shared `PRD_COMPLETED.md`, partitioned by implementation module. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying so they built on prior edits instead of reverting them. Each pass received the previous passes' hand-off notes and returned an explicit verdict on each.

**Final file: `workspace/PRD_COMPLETED.md` — 548 lines, 131,982 chars** (from `PRD_FINALIZED.md`'s 548 lines / 114,887 chars → **+17,095 chars, +0 lines**; 61 lines changed). Every edit is an in-paragraph insert or revision — no new sections, no new paragraphs. **66 edits total: 54 ambiguity-pins, 12 mismatch-revisions.**

### Pass 1 — core machinery + developers/catalog/leases (15 modules): 23 edits, 19 ambiguity-pins / 4 mismatch-revisions
- §2.1 — revise — ambiguity — whitespace-only header value counts as empty for `ERR_MISSING_AUTH_HEADERS` — `middleware.py:16-22`
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock, not wall time, so it repeats across responses at one clock reading — `response.py:21-25`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; explicitly empty value treated as omitted; `offset` unbounded — `response.py:52-73`
- §2.3 — insert — ambiguity — `created_at` ties broken by server arrival order (dominant in practice since the clock is client-driven) — `db.py:120-127`
- §2.3 — insert — ambiguity — filter semantics: empty value = absent; bad enum → 400; identifier filters matched literally, never existence-checked — `response.py:82-95`
- §2.4 — insert — ambiguity — supplied instants accept `Z`/`±HH:MM`/no zone (read as UTC), 1–9 fractional digits, sub-ms **truncated** not rounded on echo — `db.py:10-56`
- §2.5 — **revise** — **mismatch** — clock rejects an instant **equal to** the current one with `ERR_CLOCK_REWIND` (PRD had said equal is a no-op) — `routes/system.py:29-34`
- §2.5 — insert — ambiguity — clock read validates headers when they *are* supplied — `routes/system.py:46`, `middleware.py:40-46`
- §2.6 band 2 — insert — ambiguity — absent/empty body = empty JSON object; non-object body rejected; explicit `null` = absent; bool/int types strict — `validation.py:13-48,79`
- §2.6 rung 20 — **revise** — **mismatch** — `ERR_DEVELOPER_STANDING_BLOCKED` also covers directory-**review** approval and both revocation refusals — `routes/developers.py:213,230-240`
- §2.11 — insert — ambiguity — decimal fields ship as JSON numbers, so 2-dp quantisation governs value not rendering (`65.00` → `65.0`) — `serializers.py:7-12`
- §3.1 — insert — ambiguity — re-acknowledging from `SANDBOX_VALIDATED`/`PRODUCTION_ACTIVE` never regresses `onboarding_state` — `routes/developers.py:138-139`
- §3.1 — insert — ambiguity — bad `sample_app_slug` → `ERR_INVALID_REQUEST` but evaluated *after* both FK checks and before ownership; `starts_at` unconstrained vs the clock — `routes/leases.py:52-58`
- §3.1 — **revise** — **mismatch** — lease validation records **no** new lease field; only `updated_at`/`version` move, and it is repeatable while `ACTIVE` — `routes/leases.py:141-152`
- §3.1 — **revise** — **mismatch** — audited score dips below snapshot only when a case is pending or `throttled_window_count` **reaches 2** (PRD said "any throttling"); clamp can flatten both to 0 — `services/trust.py:62-67`, `constants.py:113-114`
- §3.2 — insert — ambiguity — `semver` checked for shape only; not unique per product, no ordering inferred — `routes/catalog.py:29,152-154`
- §3.2 — insert — ambiguity — migration guide republishable, overwriting both url and published-at — `routes/catalog.py:249-251`
- §3.2 — insert — ambiguity — `required_notice_days` persisted only by a *successful* announcement — `routes/catalog.py:272-295`
- §3.2 — insert — ambiguity — cascade-rejected applications also get `decided_at` from the clock — `services/lifecycle.py:56-60`
- §3.7 — insert — ambiguity — wrong-standing and missing-grounds both yield `ERR_DEVELOPER_STANDING_BLOCKED`, standing first, SoD last — `routes/developers.py:230-245`
- §3.9 — insert — ambiguity — `certification_expires_at` required on every update incl. `NONE`; `hackathon_awards_delta` ≥ 0; expiry check precedes any write — `routes/developers.py:149-159`
- §3.9 — **revise** — **mismatch** — directory-submission standing failure yields `ERR_DEVELOPER_STANDING_BLOCKED` (rung 20) and fires **first**, not `ERR_DIRECTORY_PREREQUISITES_UNMET`; current `directory_state` is not a precondition — `routes/developers.py:176-193`
- §3.9 — insert — ambiguity — directory review wrong state → `ERR_DIRECTORY_PREREQUISITES_UNMET`; approval standing failure → `ERR_DEVELOPER_STANDING_BLOCKED`, checked after state — `routes/developers.py:207-214`
- §4 preamble — insert — ambiguity — unrouted path → `ERR_INVALID_REQUEST` 404, undeclared method → `ERR_INVALID_REQUEST` 405, both before header checks; trailing slash insignificant — `app.py:27,50-68`

Pass 1 verified non-obvious claims against a live server on port 17955, started and killed by exact PID.

### Pass 2 — applications/assignments/feedback routes + quota/usage/feedback services (6 modules): 22 edits, 18 ambiguity-pins / 4 mismatch-revisions
- §2.8 — insert — ambiguity — both `expected_*_version` fields are integers ≥ 1, so 0/negative is a shape-band 400, not a 412 — `routes/assignments.py:54,307`
- §3.3 — insert — ambiguity — the 40-char draft justification floor and scope-catalogue membership are both `ERR_INVALID_REQUEST` (not `ERR_JUSTIFICATION_INSUFFICIENT`), after developer+version resolve, before ownership — `routes/applications.py:68-84`
- §3.3 — insert — ambiguity — a supplied `justification_text` revision is what the floor measures and persists only on success; omitted ⇒ stored text measured and untouched — `routes/applications.py:178,196-197`
- §3.3 — insert — ambiguity — a non-claiming manager is refused `ERR_UNAUTHORIZED` (403), not the SoD error — `routes/applications.py:236-243`
- §3.3 — insert — ambiguity — `approved_tier`/`granted_scopes` required only on approve, shape-checked but ignored on reject; omitted `decision_reason` stays null — `routes/applications.py:263-273,330`
- §3.3 — insert — ambiguity — `REVISION_LIMIT_EXHAUSTED` overwrites any caller-supplied `decision_reason` on that path only — `routes/applications.py:335-338`
- §3.4 — insert — ambiguity — not-`SUNSET` refusal is `ERR_VERSION_NOT_GRANTABLE` 422 — `services/common.py:208-214`
- §3.4 — insert — ambiguity — `suspension_reason` mandatory and non-empty — `routes/assignments.py:175`
- §3.4 — insert — ambiguity — reinstatement uses the same `ERR_VERSION_NOT_GRANTABLE` identifier — `routes/assignments.py:204-206`
- §3.4 — insert — ambiguity — the appeal-dismissal cascade re-deducts with **no** standing/version/pool gate and can push allocated above the pool — `services/quota.py:164-172`, `services/enforcement.py:88-95`
- §3.5 — **revise** — **mismatch** — alignment requires the whole fractional second zero, not just the millisecond component — `routes/assignments.py:245-249`, `db.py:27`
- §3.5 — **revise** — **mismatch** — window counters move on *every* soft/hard window, not only the crossing one — `services/usage.py:75-80`
- §3.5 — insert — ambiguity — ingestion unconditionally bumps the entitlement's `updated_at`/`version`, even for a zero-call hour — `services/usage.py:73`
- §3.6 — insert — ambiguity — empty `justification_text` is a 400 before the 40-char floor — `routes/assignments.py:306,329`
- §3.6 — **revise** — **mismatch** — (a) tie-break after `created_at` is server arrival order; (b) only the **eligible** queue is stamped — ineligible candidates stay `PENDING` with `run_sequence`/`decided_at` null, neither counted nor reported — `services/quota.py:176-183,206-229`
- §3.6 — insert — ambiguity — each grant is its own product mutation, so three grants advance the product `version` by three — `services/quota.py:249-258`
- §3.6 — **revise** — **mismatch** — `run_sequence_count` counts eligible, not candidate, requests; an all-ineligible run succeeds with 0s — `services/quota.py:220-225,260-267`
- §3.6 — insert — ambiguity — `denial_reason` is null on admin suspension, retirement, sunset and `SUPERSEDED` — `services/quota.py:127-135`, `routes/assignments.py:350-352`
- §3.9 — insert — ambiguity — the certification bonus is read from the stored level even after expiry (unlike §3.1's trust component) — `services/feedback.py:20`
- §3.9 — insert — ambiguity — items/product re-stamped only when `priority_score`/`demand_index` actually move; the triggering item stamped exactly once — `services/feedback.py:48-61`
- §3.9 — insert — ambiguity — arrival-order tie-break after `created_at` — `services/feedback.py:64-74`
- §3.9 — insert — ambiguity — an omitted `decision_note` retains the existing note rather than clearing it — `routes/feedback.py:122-123,151-152`

Verdicts on pass 1's hand-off notes: (1) confirmed-and-pinned; (2) **refuted, no edit spent** — §3.6 already pins a 0 grant as `PARTIALLY_GRANTED` since `requested_delta_rpm` ≥ 1, *and* the branch is unreachable because creation refuses an entitlement at its tier ceiling and supersedes prior `PENDING` requests, so `headroom` > 0 whenever a request is walked; documenting it would describe behaviour the impl cannot exhibit; (3) confirmed-and-pinned.

### Pass 3 — violations/support routes + enforcement/support/checkpoint services (5 modules): 21 edits, 17 ambiguity-pins / 4 mismatch-revisions
- §3.7 open-case — insert — ambiguity — `evidence_window_ids` caps at 100, need not be distinct, records `[]` (not null) when omitted; `quota_assignment_id` need only exist and is never checked against the target developer; attributability holds in any `entitlement_state`; window existence checked across the whole array before attributability; investigation-time evidence appended and deduped, never replacing — `routes/violations.py:40-51,71-88,150-156`
- §3.7 — insert — ambiguity — a developer already `UNDER_REVIEW`/`RESTRICTED`/`REVOKED` keeps its standing; neither opening nor investigating is standing-gated — `routes/violations.py:62-79,163-166`
- §3.7 — insert — ambiguity — the restriction cascade fires only out of `UNDER_REVIEW`; an already-`RESTRICTED` developer takes the points but fires no second cascade — `services/enforcement.py:140-143`
- §3.7 — insert — ambiguity — the `RESTRICTED → GOOD_STANDING` dismissal branch does not consult other live cases; a still-`UNDER_REVIEW` developer returns to `GOOD_STANDING` with no restoration run; a cascade-driven `DELISTED` directory is not restored — `services/enforcement.py:146-158`
- §3.7 — insert — ambiguity — `decision_note` mandatory, non-empty, no max length — `routes/violations.py:176`
- §3.7 — insert — ambiguity — `appeal_reason` mandatory, non-empty — `routes/violations.py:227`
- §3.7 — insert — ambiguity — the appealed-upheld path does not mutate the developer record (no `version` advance) and `penalty_points` recomputes to the same figure — `routes/violations.py:203-218`
- §3.8 — insert — ambiguity — a supplied `started_at` on a `PARTNER_TICKET` is silently discarded, not refused — `routes/support.py:97`
- §3.8 — **revise** — **mismatch** — the S1/S2 qualifying `PARTNER`/`PRIVILEGED` entitlement must be **on the named product**; plus rung-26-before-rung-44 precedence — `routes/support.py:67-73,135-151`
- §3.8 — insert — ambiguity — either role may open either kind; a `Developer`'s single read of a `PLATFORM_INCIDENT` fails `ERR_NOT_RESOURCE_OWNER` while the list read shows it — `routes/support.py:47,62-63,160`
- §3.8 — insert — ambiguity — only incidents already carrying `resolved_at` constrain coalescing, "most recent" = latest `resolved_at`, bound inclusive against the submitted `started_at` — `services/support.py:51-63`, `routes/support.py:76-87`
- §3.8 — **revise** — **mismatch** — a later communication leaves an `ESCALATED` case `ESCALATED` (PRD said `RESPONDING`) — `routes/support.py:239-240`
- §3.8 — insert — ambiguity — a communication is internal bookkeeping, not an addressable resource, hence HTTP 200 with the case rather than 201; any agent may act on any case, no operator identity, no SoD — `routes/support.py:223-243`, `db.py:90-91,104-111`
- §3.8 — insert — ambiguity — `body` mandatory, non-empty, no max length — `routes/support.py:195`
- §3.8 — insert — ambiguity — the tier-3 cap surfaces as `ERR_SUPPORT_CASE_STATE_INVALID` (409), tested before the entitlement gate; `escalation_note` validated then discarded — `routes/support.py:250,260-264`
- §3.8 — **revise** — **mismatch** — the beyond-tier-1 entitlement must be on the case's own `api_product_id`; a `PLATFORM_INCIDENT` is never gated — `routes/support.py:266-274`
- §3.8 — insert — ambiguity — `resolution_note` mandatory, non-empty — `routes/support.py:286`
- §3.8 — insert — ambiguity — a 0 credit (every `S4` entitlement, or a rounded-away outage) still counts in `affected_assignment_count`, still bumps the entitlement's `updated_at`/`version`, still re-evaluates throttle; the developer's window counters are untouched — `services/support.py:82-96`, `services/usage.py:23-30`
- §3.9 — **revise** — **mismatch** — restriction delists only a `LISTED` entry (a `PENDING_REVIEW` listing survives); revocation delists from any state including `NOT_LISTED` — `services/enforcement.py:83-84,102-103`
- §3.10 intro — insert — ambiguity — every reported identifier array is in `created_at`-then-arrival order, step 3's two arrays grouped version by version — `services/checkpoint.py:21,36-44`
- §3.10 step 2 — insert — ambiguity — comparison is `<= clock`, any `certification_level` including `NONE`, and the lapse is re-reported on every later run — `services/checkpoint.py:30-33`
- §3.10 step 5 — insert — ambiguity — a reset moves nothing on the developer (window counters, `trust_score`) — `services/checkpoint.py:60-74`
- §3.10 step 6 — insert — ambiguity — every developer is reported but only a changed `audited_trust_score` mutates `updated_at`/`version` — `services/checkpoint.py:77-82`

Verdicts on hand-off notes 1–7: (1) confirmed-and-pinned; (2) **already-covered / refuted as observable** — `checkpoint.py:52` does read `outcome`, but the branch is unreachable (appealing moves the case to `APPEALED` and re-adjudication overwrites `outcome`, so a case in `state` `UPHELD` with `appeal_count > 0` necessarily has `outcome == "UPHELD"`); the PRD's existing wording is exactly equivalent; (3) confirmed-and-pinned, also resolving the latent 201-vs-200 question; (4) already-covered by pass 2's §3.4 edit, deliberately not restated; (5) already-covered by pass 2's §3.6 edit; (6) confirmed-and-pinned in §3.8's credit paragraph and §3.10 step 5, with a grep confirming `clean_window_count`/`throttled_window_count` are written only by `usage.ingest_window` and at registration; (7) **refuted** — there is no analogous wrong-operator guard in pass 3's modules (`violations.py`'s only identity guard is investigator-vs-adjudicator and already uses `ERR_SEGREGATION_OF_DUTIES` as §3.7 says; `support.py` has no operator-identity guard at all), so the absence was pinned instead of naming an error.

### Residual gaps consciously left (pass 3's closing statement)
(a) the unreachable `awaiting` branch of checkpoint step 4 — pinning unobservable implementation internals would risk a false claim; (b) internal-only artefacts (`_seq`, `_developer_snapshot`, and `services/common.has_active_tier`/`is_entitled_for_escalation`, dead code superseded by the product-scoped `_has_active_on_product`) are deliberately not described; (c) trivial per-field minima already implied by §2.6 band 2 (e.g. `developer_id` non-empty on case creation) were not enumerated field by field.

### Orchestrator verification
- `PRD.md` 548 lines / 114,349 chars → `PRD_FINALIZED.md` 548 / 114,887 → `PRD_COMPLETED.md` 548 / 131,982. `diff -q` confirms **both** hops differ (61 lines changed across the three passes), so neither the Step 8 nor the Step 9 output is the degenerate byte-identical copy.
- `PRD_COMPLETED.md` ends on the final row of the §5 error table — a genuine section boundary, not a truncation.
- All 8 `results.*.json` (210/210 each) present in `workspace/implementation/`.
- Exactly one `worklog.md` in the tree; no test directory under `workspace/`; the difficulty directive appears nowhere in the scaffold, PRD chain, tests, or implementation (its only occurrence is inside this worklog, quoted in the Step 2 subagent's own summary).

