# Worklog — task_3113_fertility_benefit_network_management_treatment_bundle_administration

Scenario: Fertility Benefit Network Management & Treatment Bundle Administration (Progyny).

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3113_fertility_benefit_network_management_treatment_bundle_administration/` was pre-allocated by the caller with an empty `workspace/` inside; verified present via `ls`. No new index computed, no other `task_*` directory created.

## Step 2: Generate scaffold — 2026-09-30T00:41:00.000Z

Subagent (prd-bench-scaffold-generator) returned verbatim: "All three files are written and lint-clean. Final verification is done."

Verified by orchestrator on disk:
- `SCAFFOLD.yaml` — 3279 lines; top-level keys §1.0–§1.7: scenario, domain_name (`fertility-benefit-network`), api_prefix, complexity_profile, entities (14), state_machines (13), concurrency_rules (3), calculations (8), validations (17), response_envelope, endpoints (89), errors (38), roles (9). No `scaffold_difficulty_design` / `scaffold_corner_design` key present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2215 lines; single top-level key `scaffold_difficulty_design`, a 9-element list keyed by rule_id (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant), each carrying `instances` — 18 instance `name:` entries total.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1909 lines; single top-level key `scaffold_corner_design`, 13 sections (entities ×2, state_machines ×2, calculations ×2, validations ×2, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model) each carrying `instances` — 49 instance `name:` entries total.

Scenario passed verbatim to the generator; the only added instruction was the caller's `Generate task much harder than expert level!` directive. Hard constraint honoured: no sibling `task_*/` directory was read.

## Step 3: Copy shared files — 2026-09-30T00:42:00.000Z

`cp ./INSTRUCTION.md ./tasks/task_3113_fertility_benefit_network_management_treatment_bundle_administration/workspace/INSTRUCTION.md` — 1424 bytes, copied successfully.

## Step 4: Generate PRD — 2026-09-30T00:55:00.000Z

Subagent (prd-bench-doc-generator) returned verbatim:

> The PRD is complete and all three hard contracts pass mechanically.
>
> ## Summary
>
> **Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3113_fertility_benefit_network_management_treatment_bundle_administration/workspace/PRD.md` — 411 lines.
>
> **Section headings:**
> - `# Fertility Benefit Network API — Product Requirements Document`
> - `## 1. Introduction` (3 paragraphs)
> - `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim); 2.3 Pagination, Ordering, and Envelope Metadata; 2.4 The Bundle Ledger Principle and Dual-Variant Netting; 2.5 Common Resource Properties and Derived Fields; 2.6 The Logical Clock and Time-Dependent Eligibility; 2.7 Monetary Precision, Percentages, and Rounding; 2.8 Optimistic Concurrency Control; 2.9 Nested Resource Retrieval and Validation Order; 2.10 Allowance and Network Governance
> - `## 3. Business Logic & Workflows` — 3.1 Designing the Benefit: Sponsor Accounts and Bundle Grants; 3.2 Enrolling a Member and Picking an Advocate; 3.3 Contracting the Clinic Network on Quality Evidence; 3.4 Opening a Treatment Plan and Committing It to a Clinic; 3.5 Pre-Authorization: Clinical Appropriateness and the Sequencing Guard; 3.6 Running a Cycle: Stimulation Through Outcome; 3.7 The Specialty Pharmacy Pathway and Its Pool; 3.8 Life-Path Routes: Preservation, Donation, and Surrogacy; 3.9 Claim Adjudication, Member Share, and the Reversal Route; 3.10 Network Stewardship and the Consequences of Exhaustion
> - `## 4. Endpoint Definitions` (89-row, 4-column table — exact match to scaffold)
> - `## 5. Error Code Catalogue` (38-row, 2-column table)
>
> **Hard Contract Reports**
>
> ```
> Field coverage check:
> - entities[].fields: 125 required, 125 present, 0 missing
> - endpoints[].input (request_body): 101 required, 101 present, 0 missing
> - endpoints[].query_params (embedded as '?' keys in `input`): 41 required, 41 present, 0 missing
> - endpoints[].path_params: 0 declared in scaffold
> Status: PASS
> ```
>
> ```
> Rule coverage check:
> - validations[] with priority: 17 checked, 17 expressed in prose (ordered in §2.9/§2.10, trigger conditions in §3), 0 missing
> - concurrency_rules[] OCC rejections: 3 checked, 3 expressed (§2.8 — write operation + expected_<parent>_version + ERR_PLAN_VERSION_STALE/ERR_PREAUTH_VERSION_STALE/ERR_CYCLE_VERSION_STALE + 412 all named), 0 missing
> - state_machines[].transitions: 10 machines / all transitions checked, fully expressed (from/to pairs, preconditions with paired error_ids, side-effect cascades), 0 missing
> - calculations[]: 8 checked, 8 fully expressed in precise prose (C6/C8 C1 expanded; C5, C7 given as their scaffold worked numbers), 0 missing
> - validations[] conditions: 17 checked, 17 matchable to error_id in prose, 0 missing
> - endpoints[].side_effects / applies_to: 89 checked, expressed in §3 narratives, 0 missing
> - entities[].fields[] structured content: 125 checked, reconstructible (defaults, sources, enum constraints, never-negative floors), 0 missing
> - sibling-branch symmetry: 12 groups checked (cancel branches, withdraw branches, no-gate branches, ancillary slices, copay variants), equal prose density, 0 asymmetric
> Status: PASS
> ```
>
> ```
> Path purity check (§3 only):
> - backtick tokens scanned: 733
> - tokens starting with `/`: 0
> - bare HTTP-method tokens: 0
> - method+path combined tokens: 0
> Status: PASS
> ```
>
> **Scaffold rules that were hard to render as PRD prose**
>
> 1. **Two scaffold calculations are named but never defined.** `pathway_coverage_rule` (referenced by `PathwayRequest.pathway_cost_cents` and `SurrenderRoute.surrender_cost_cents`) and `monthly_claim_liability_cents` (referenced in three Claim transition side effects) have no entry in the `calculations` table — only 8 of the formulas exist. I kept them as named rule-sets referenced in prose rather than inventing formulas (which "No invented rules" forbids), but an implementer cannot fully reconstruct either from the PRD alone.
> 2. **Documented constants that carry no value.** `AUTHORIZATION_WINDOW_DAYS`, `SUBMITTED_EXPIRY_HOURS`, `PREGNANCY_TEST_DAYS`, `CLAIM_PEND_AFTER_DAYS`, `APPEAL_WINDOW_DAYS`, `REVERSAL_WINDOW_DAYS`, `AMENDMENT_WINDOW_DAYS`, `STORAGE_RETENTION_DAYS`, and `PREROUTE_LEAD_DAYS` are used by transitions/enumeration but never declared under any `constants:` block. I removed every fabricated day/hour figure I had initially written and described each as "the configured <window>" with its anchor instant and boundary inclusivity stated precisely, so the prose does not lie but also does not supply a number.
> 3. **`Clinic.bundles_offered` is an endpoint input with no entity field.** It is accepted at clinic registration but no `bundles_offered` field exists on the `Clinic` entity. I mention it only as an accepted registration input.
> 4. **`ClinicContract.activate`'s precondition looks internally inconsistent** — it tests "`Clinic.required_quality_report_count >= 3`" (a config field compared to a literal) while the §9 validation says the count must be "accumulated" first. I rendered it as a floor of three reports, larger when `required_quality_report_count` is configured larger, and flagged the reading in prose rather than silently choosing one.
> 5. **`bundle_cycle_allowance` references a field that does not exist.** The formula subtracts `B.cycles_consumed_this_plan_year`, which is absent from `BundleEntitlement.fields` and annotated "future-dated = 0 for the whole benchmark". I described the annual slice only as the `max_cycles_per_year` cap rather than reintroducing a phantom field name.
> 6. **`Appeal.WINDOW` arithmetic** uses `Preauthorization.effective_to + APPEAL_WINDOW_DAYS` in the precondition but `Claim.paid_at + REVERSAL_WINDOW_DAYS` for reversal, with an undeclared `paid_at` field. I anchored the appeal window to the close of the authorization's validity and the reversal window to the instant of payment without naming the undeclared `paid_at` field.
>
> Two deliberate, spec-permitted omissions: no §3 subsection enumerated the seven `allocation_strategy` propagation rules (the scaffold never defines what that enum's members *do*, only that the selector must produce a candidate or `ERR_NO_ADVOCATE_CANDIDATE`), and `subject_of`-style fields absent from the scaffold were not invented. `member_cost_share_pct` is presented in §3.5 as the authorization's member-responsibility percentage; the scaffold gives no value range for it, so no range is asserted.

Orchestrator verification: `workspace/PRD.md` exists, 410 lines / 97,118 bytes. Design indices were not read (withheld by prompt). The six scaffold gaps reported above are recorded here as upstream scaffold-generator defects; they are the known candidate sources of Step-7 test deletions (PRD-silence on the two undefined calculations and the undeclared window constants).

## Step 5: Generate unit tests — 2026-09-30T01:18:00.000Z

Subagent (prd-bench-unit-test-generator) returned verbatim:

> Done. Test infrastructure and suite are written, self-audited against both design indices, and lint/collection-clean.
>
> ## Files written
>
> **`test_helpers/` (2,280 lines)**
> | File | Lines |
> |---|---|
> | `types.py` | 464 |
> | `fixtures.py` | 646 |
> | `api_client.py` | 336 |
> | `assertions.py` | 313 |
> | `factories.py` | 195 |
> | `constants.py` | 102 |
> | `api_errors.py` | 97 |
> | `test_users.py` | 72 |
> | `__init__.py` | 55 |
>
> **`test_suite/` (3,365 lines, 83 tests)**
> | File | Lines | Tests |
> |---|---|---|
> | `conftest.py` | 58 | — |
> | `test_01_dual_variant_calculations.py` | 292 | 9 |
> | `test_02_clinic_quality_and_cascades.py` | 510 | 11 |
> | `test_03_version_pinning_and_gate_order.py` | 366 | 10 |
> | `test_04_scoring_and_interval_boundaries.py` | 659 | 17 |
> | `test_05_corner_entity_state_rbac.py` | 672 | 19 |
> | `test_06_price_appeal_and_reversal.py` | 233 | 4 |
> | `test_07_allowances_ordering_and_windows.py` | 575 | 13 |
>
> ## Coverage
>
> **Queue A (difficulty): 17 of 18 instances emitted, 36 tests** (≥2 each, verified programmatically).
> **Queue B (corner): 35 of 35 non-stub instances emitted, 47 tests** (≥1 each). No `excluded_because:` stub was translated.
>
> **Total: 83 tests.** Audit results: zero untagged tests, zero dual-tagged tests, zero tags pointing at non-existent instances, zero stub-of-a-stub, all 119 distinctive docstring quotes (≥40 chars) survive a literal normalized `grep` of `PRD.md`.
>
> ## The one skipped instance
>
> `Difficulty/combinatorial_formula/clinic_bundle_price_copay_max_manager_fee_rounding_mode_b` — **skipped under the `default-value` / Constants Applied silence patterns.** The PRD names the *manager-fee percentage* as one of the percentages that drive money (§2.7) and describes `copay_max` as controlling whether "the maximum copay reduction" applies (§3.1), but it states **neither the 8 percent fee percentage nor the 25000-cent reduction amount**. The instance's asserted value (1175000 for a 1250000 rate) is derivable only from the scaffold's `calculations.clinic_bundle_price.constants`, which the implementer never sees. Two PRD-only readers could pick any fee percentage and any reduction amount and still be faithful. I first emitted the two tests for this instance, then removed them after this check — the asserted literals had no PRD basis.
>
> ## Other PRD-silence decisions worth flagging
>
> - The Elapsed-and closed-window tests (`ERR_REVERSAL_WINDOW_CLOSED`, `ERR_AMENDMENT_WINDOW_CLOSED`) are written as **relative** probes: they derive the authorization's `effective_to` from the API's own response and then move the clock past it, rather than hard-coding a window length the PRD leaves to configuration. The same pattern was applied to the appeal-window and spacing/retention tests.
> - The claim dual-failure priority test genuinely probes the dual failure it claims: the same request carries an unresolvable `treatment_cycle_id` **and** a service instant outside a closed authorization window, and dropping only the bad foreign key flips the answer to `ERR_PREAUTH_WINDOW_OUTSIDE_COVERAGE`.
> - OCC tests (`ERR_PLAN_VERSION_STALE`, `ERR_PREAUTH_VERSION_STALE`, `ERR_CYCLE_VERSION_STALE`) use the sequential stale-token form the skill sanctions.
> - Each test file's docstrings cite PRD prose only — no "scaffold" or section-table references leak into generated code.
>
> No implementation exists yet under `workspace/`, so tests were not executed against a live server.

Orchestrator verification: `test_helpers/` has 9 files (2,280 lines per report); `test_suite/` has `conftest.py` + 7 test files; `grep -c 'Design: '` over `test_suite/*.py` = 83 tags, matching the reported test count. `workspace/` still contains only `INSTRUCTION.md` + `PRD.md` — confirming no implementation existed at Step 5 launch (physical isolation for Step 6).
## Interruption + recovery assessment — 2026-09-30T02:37:00.000Z

The host session that launched Step 6 ended mid-flight; the Step 6 subagent's report was never recorded. Recovery assessment performed by the orchestrator:

- Steps 1–5 artifacts verified intact and complete: `SCAFFOLD.yaml` (3279 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2215), `SCAFFOLD_CORNER_DESIGN.yaml` (1909), `workspace/INSTRUCTION.md` (1424 B), `workspace/PRD.md` (410 lines), `test_helpers/` (9 files) + `test_suite/` (7 files + conftest, 83 `Design:` tags). No rework needed.
- Step 6 had left an orphaned `workspace/implementation/` (files timestamped 01:27–02:02, 4580 lines) with no report. Structural probe: `python3 -m compileall` clean, zero TODO/FIXME/stub markers, `create_app()` registers exactly 89 rules vs the scaffold's 89 endpoints (the 64 apparent diffs were bare Flask `<var>` vs YAML `{var}` syntax only).
- Behavioral probe (single `prd-bench-local-run --isolation per-test-server` round): 83 tests, **31 passed / 52 failed**. Dominant failure signatures: `Setup step failed with HTTP 403: ERR_UNAUTHORIZED` (role-vs-resource mismatch surfacing in fixtures) and `Setup step failed with HTTP 400: ERR_INVALID_REQUEST - external_ref must be unique within the account` (fixture reusing a literal external_ref across accounts), plus `ERR_BUNDLE_EXHAUSTED` on setup. These are the classic Step-7 triage-hint signature: ≥5 failures sharing one setup error ⇒ `test_helpers/` is the first suspect.

Decision: because Step 6's subagent was mid-flight when the process stopped and produced no report, the orphaned output is treated as an untrusted partial. It is backed up to `/tmp/task3113_orphan_impl/` (outside the task dir, retained as a cross-check reference for Step 7) and `workspace/implementation/` is regenerated from scratch by a fresh Step 6 subagent. The 31/52 probe result is NOT treated as Step 7's baseline.

## Step 6 (redo): Generate implementation — 2026-09-30T02:37:00.000Z

Restarted from scratch after the interruption above. Orphaned pre-interruption implementation preserved at `/tmp/task3113_orphan_impl/`.

## Second interruption + base selection — 2026-09-30T03:39:00.000Z

The host session died a second time, again mid-Step-6. `workspace/implementation/` contained a THIRD body of code (structurally distinct: `core.py`/`domain.py`/`router.py`/`routes_*.py`/`services.py`, 4227 lines, timestamps 02:43–02:58), again with no report.

Probe round on that body: 83 tests, **9 passed / 74 failed**. Root cause of the 74 was a single systemic defect — it validated the advocate-selector input `allocation_strategy` against the bundle-netting enum (`allocation_strategy must be SEQUENTIAL_BUNDLE or CONCURRENT_BUNDLE`), rejecting the fixtures' `ROUND_ROBIN`.

Direct comparison against the first body (preserved at `/tmp/task3113_orphan_impl`):

- `allocation_strategy` and `allocation_method` are **two different concepts** in the scaffold/PRD. `allocation_method` is an `EmployerAccount` enum field constrained to `SEQUENTIAL_BUNDLE | CONCURRENT_BUNDLE` — it selects the *netting policy* (§2.4). `allocation_strategy` is an optional **input** to `POST /members/{id}/assign-advocate`, whose members the scaffold never constrains and whose behaviour PRD §3.2 leaves as ordering policy over an already-built eligible pool. Conflating them is a hallucinated validation with no PRD basis.
- The first body treated `allocation_strategy` as an unconstrained selector (defaulting to `ROUND_ROBIN`), which is the PRD-faithful reading, and scored 31/83.

Base selection: the first body is restored as `workspace/implementation/` and handed to Step 7. The third body is preserved at `/tmp/task3113_attempt2/` as a cross-check reference (it may contain correct logic for rules the first body got wrong). The 31/83 figure is Step 7's true starting baseline.

## Step 6 (final): implementation base selected — 2026-09-30T03:40:00.000Z

`workspace/implementation/` = first body (4580 lines, 89/89 endpoints, boots clean, probe 31/83). Reference bodies on disk outside the task dir: `/tmp/task3113_orphan_impl` (== current base) and `/tmp/task3113_attempt2`.

## Step 7: Run tests and iterate — 2026-09-30T04:34:00.000Z

Single long-lived diagnostic subagent. It reports 6 sweeps (8 parallel rounds each), trajectory 31 → 57 → 71 → 77 → 81 → 83. Orchestrator verification of the final sweep on disk: `results.1..8.json` all present, each `total=83 passed=83 failed=0 errors=0 skipped=0`.

Subagent summary, verbatim:

> All 8 rounds clean: 83/83, zero failures, zero errors, zero skips. Done.
>
> ## Summary
>
> **Iterations run:** 6 sweeps (each 8 parallel rounds). Trajectory: 31 → 57 → 71 → 77 → 81 → 83. Every intermediate result was identical across all 8 rounds, so no timing-sensitive flakiness was present at any stage. Final sweep: 8/8 rounds at 83/83 with `failed=0, errors=0, skipped=0`.
>
> **Tests deleted:** None. Every failure traced to either a `test_helpers/` fixture defect or an implementation defect — the PRD covered each asserted rule, and the assertions were faithful once the setup/request layer was corrected.
>
> ### Fixes applied to `test_helpers/`
> - **`fixtures.py` `create_member`** — the dominant upstream bug (32 403s + several cascades): swallowed `member_overrides` as an unrecognized kwarg, so every member got the same literal `external_ref` (→ `ERR_INVALID_REQUEST`) and most scenario builders lost their `required_track`/identity (→ `ERR_NO_ADVOCATE_CANDIDATE`, and role-mismatched advocate selection that surfaced later as 403s). Now merges both `member_overrides` and bare kwargs into the payload.
> - **`fixtures.py` bundle-entitlement reads (6 sites)** — used `NETWORK` (NetworkManager), which PRD §4 does not list as a permitted reader of `/bundle-entitlements/{id}`. Switched to `PHARMACIST` (permitted). Same class of bug fixed for `get_preauthorization` (→ `CLAIMS`) and `list_member_surrender_routes`/`list_surrender_routes` (→ the nested member collection, whose role set is the widest).
> - **`fixtures.py` `setup_routed_surrender_route`** — used the standing `/surrender-routes/{id}` read with `NETWORK`, which PRD §4 excludes; now reads back through the member's nested collection.
> - **`fixtures.py` `setup_authorization_near_score_floor`, `setup_clinic_with_reported_workset`; `test_02`/`test_04` scenario builders** — approved authorizations at a clock already advanced by earlier steps, while their windows open at the approval instant and their cycles were back-dated. Moved approval ahead of the cycle creation.
> - **`constants.py` + `test_04`/`test_07` assertions** — the "69" criteria profile actually scored 55 (a critical-level assertion defect), and two ISO-8601 comparisons asserted `Z` instead of the PRD-declared three-fractional-digit format. Replaced with profiles whose band totals are exact and with timestamp-tolerant assertions.
> - **`test_02` exhaustion cascade, `test_04` `setup_spaced_plan`, `test_05` pathway references, `test_07` dispense test** — reordered a sibling authorization ahead of pool exhaustion; approved both spacing authorizations before cycle creation; filed the pathway requests *without* the reference their enumeration demands (the PRD refuses at filing, not at `begin-clinical-review`); unwrapped a `tuple`-vs-`dict` fixture misuse.
> - **`test_06` appeal/reversal tests** — the SOD test asserted a never-recorded actor id (now the actual adjudicating identity); the price/ceiling assertions hard-coded the manager-fee-derived 1450000, which PRD states no percentage for, so they now assert the derivable relation against the plan's own pinned ceiling; the reversal test's bundle-version bump is now real.
>
> ### Fixes applied to `implementation/`
> - **`routes/cycles.py`** — creation required the *logical clock* to sit inside the authorization window, rejecting every forward-scheduled cycle; the PRD requires only the billed service instant to fall inside it.
> - **`routes/members.py`** — `complete-intake` reported `ERR_INVALID_STATE` at the capacity arm of the advocate gate; PRD §2.10 names `ERR_ADVOCATE_CREDENTIAL_LAPSED` for both arms. Also: `POST /members/{id}/surrender-routes` returned the *member* row instead of the created route (PRD §2.2 requires the created resource), which broke every route read-back.
> - **`routes/claims.py`** — the claim's recorded decision actor was never seeded at submission, so an appeal could be decided by the same identity that produced the last adjudication (PRD §2.1/§3.9 SOD); the reversal's pool recompute never advanced the entitlement's version (PRD §2.5 counts a ledger recompute as a mutation).
>
> No endpoint, field, or capability was added that does not trace to a verbatim PRD sentence; storage remains in-memory only, and no data is seeded at startup.

Step 8 trigger check: Step 7 exited with **0 deletions**, but it DID apply `test_helpers/` fixes (many) and `implementation/` fixes (7 findings across 3 route modules). The skip condition requires 0 deletions AND 0 test_suite/ fixes AND 0 test_helpers/ fixes AND 0 implementation/ fixes. That condition is NOT met — so Step 8 RUNS.

## Step 8: Finalize PRD — 2026-09-30T05:02:00.000Z

Step 8 ran (skip condition not met: Step 7 applied test_helpers/ and implementation/ fixes). Orchestrator verification: `workspace/PRD_FINALIZED.md` exists, 410 lines (same as PRD.md), 3 in-place prose revisions (diff shows 6 changed lines = 3 replaced pairs), no sections added.

Subagent summary, verbatim:

> The three edits are in place and stable. Both files are 410 lines.
>
> ## Summary
>
> Produced `/home/ubuntu/github/CodingPRD/tasks/task_3113_fertility_benefit_network_management_treatment_bundle_administration/workspace/PRD_FINALIZED.md`.
>
> **Line counts:** PRD.md 410 → PRD_FINALIZED.md 410 (0% delta; all three edits are in-place prose revisions, no sections added).
>
> **Changes (3):**
>
> - §2.1 — *revise* — Added that a claim's recorded `decision_actor` is seeded at submission with the submitting identity, so a not-yet-adjudicated claim already carries an actor the appeal decision must differ from — `implementation/routes/claims.py:123` (seed at create), `:184-185` (overwritten by each adjudication), `:297` (SOD compare at appeal-decide).
> - §3.5 — *revise* — Replaced "A second decision on an authorization already decided is refused with `ERR_DUPLICATE_OPERATION`" with the actual behaviour: a decision on an authorization no longer awaiting a decision is refused with `ERR_INVALID_STATE`, across explicit-decision, expiry, cascade-denial and abandonment origins — `implementation/routes/plans.py:295-296`.
> - §3.6 — *insert* — Pinned that cycle creation's coverage test compares the requested `retrieval_date` (service instant) against the authorization window and deliberately excludes the logical clock — `implementation/routes/cycles.py:114-125` and `:78`.
>
> **Per-edit pre-edit search log:**
>
> - **Edit A — subject:** "the claim's recorded decision actor at submission". **Impl paths enumerated/read:** `routes/claims.py:123` (create seeds `_last_decision_actor` from `X-User-ID`), `:184-185` (`_adjudicate` overwrites on adjudicate and appeal-decide), `:297` (appeal-decide SOD compare); `serializers.py:77-84` (claims field map — confirms the actor is an internal record, as PRD already frames it); `middleware.py` role table. **Wording adjustment:** none needed — the sentence describes only the seeding + overwrite behaviour common to all three callsites.
> - **Edit B — subject:** "the error code for a second decision on an authorization". **Impl paths enumerated/read/grepped:** `routes/plans.py:272-273, 289-296`; every path into a terminal pre-auth reading — `routes/system.py:88-92` (EXPIRED sweep), `helpers.py:485-488` (`block_plans_of_clinic` → DENIED), `helpers.py:302-305` (`_exhaustion_cascade` → DENIED), `routes/plans.py:228-231` (abandon → EXPIRED), `routes/accounts.py:80-83` (suspend → EXPIRED); grep confirmed `ERR_DUPLICATE_OPERATION` never appears in `routes/plans.py`. **Wording adjustment:** widened from "already decided" to "no longer awaiting a decision — whether it reached its terminal reading by an explicit decision, an expiry, a cascade denial, or an abandonment" so every enumerated terminal-origin path stays consistent; explicitly noted the idempotency code is not the one returned.
> - **Edit C — subject:** "which instant cycle creation checks against the authorization window". **Impl paths enumerated/read:** `routes/cycles.py:112-125` (creation model), `:114-125` (`_renumber_cycles` uses created_at/creator/retrieval_date — no clock term), `:34, 48` (plan-state gate admits not-yet-begun `CLINIC_SELECTED`), `:68-80` (creation compares `retrieval_date` only; the clock comparison is commented out), `:199-216` (`_start_stimulation` — the contrasting clock-based check). **Wording adjustment:** scoped the new sentence to creation's coverage check only, so `_start_stimulation`'s clock-inside-window rule (already stated two paragraphs earlier in the PRD) is not narrowed or contradicted.
>
> **Deliberately not edited (step_7_diff items that are fixture/assertion-side, not PRD silence/mismatch):** the `create_member` kwarg merge, role substitutions (NETWORK→PHARMACIST/CLAIMS/nested collection — §4 already permits exactly these roles, and `middleware.py` already enforces them), the clock-ordering fixture fixes, the constants "69"→55 and ISO-`Z` assertion fixes, the pathway-reference and tuple/dict fixture fixes, the test_06 SOD actor-id and reversal-version-bump assertion fixes, and the manager-fee/price hardcoding (PRD states no manager-fee percentage; the `5.7*rate/100` behaviour is exercised only by a degenerate negative-differential contract, and no "8%" literal appears anywhere in the deliverable, so no scatter site contradicts it — under-determined wording preferred per the NO-NEW-MISMATCH rule). Also not edited: `complete-intake`'s caseload error code (impl's `ERR_ADVOCATE_CREDENTIAL_LAPSED` now matches PRD §2.10 verbatim) and the surrender-route creation response (impl returns the created resource, which PRD §2.2 already requires; the §4 status-table exclusion is pre-existing and outside the diff).

## Step 9: Complete PRD — 2026-09-30T05:20:00.000Z

Orchestrator verification: `workspace/PRD_COMPLETED.md` exists, 410 lines / 107,060 chars (source `PRD_FINALIZED.md` 410 lines / 97,802 chars → +9,258 chars, line count unchanged). 20 changed line ranges; reported 20 ambiguity-pins / 0 net mismatch-revisions.

Subagent summary, verbatim:

> `PRD_COMPLETED.md` is written. Summary below.
>
> ## Artifact
> - `/home/ubuntu/github/CodingPRD/tasks/task_3113_fertility_benefit_network_management_treatment_bundle_administration/workspace/PRD_COMPLETED.md`
> - Source: `PRD_FINALIZED.md` — 410 lines / 97,802 chars → PRD_COMPLETED.md 410 lines / 107,060 chars (**+9,258 chars, line count unchanged**; edits were in-place inserts/revisions only, no new paragraphs, no new sections).
> - 20 changed line ranges; 20 ambiguity-pins / 0 mismatch-revisions on net (two candidate mismatches were investigated and self-corrected — see below).
>
> ## Changes (one bullet each)
>
> | PRD § | Kind | Class | What changed | impl |
> |---|---|---|---|---|
> | §2.1 | insert | ambiguity | Advocate-credential/caseload gates resolve `X-User-ID` against advocate rows where it resolves | `routes/members.py:278-290` |
> | §2.3 | insert | ambiguity | Collection tie-break pinned: `created_at` asc, then row `id` asc | `db.py:71-73` |
> | §2.5 | insert | ambiguity | Two version-advance exceptions: activation/reinstate always advance; pooled-release settlements advance even at zero release | `helpers.py:284-297`, `routes/claims.py:348` |
> | §2.6 | insert | ambiguity | Advance fires due transitions first, moves clock only when nothing ripe, fires again; call order pinned | `routes/system.py:162-179` |
> | §2.6 | insert | ambiguity (flagged) | All nine configured window constants valued (180/90/120/30 days, 1080 h, 14 d, 0 d lead) | `clock.py:18-26` |
> | §2.8 | insert | ambiguity | Optional clinic/member version guards (`expected_clinic_version`, `expected_member_version`) and the mandatory `expected_bundle_entitlement_version` on dispense | `routes/clinics.py:234`, `routes/plans.py:121`, `routes/members.py:275`, `routes/medication.py:103-107` |
> | §2.10 | revise | mismatch | Contract coverage governed by ACTIVE-or-FROZEN contract at clock, latest `effective_from` wins | `helpers.py:408-443` |
> | §2.10 | insert | mismatch | `PROBATION`/`SUSPENDED` fails contractedness (clinic-selection refusal is contractedness code, not frozen code) | `routes/plans.py:114-119` |
> | §2.10 | insert | ambiguity | Frozen-contract unavailability extended to select-clinic and cycle creation | `routes/plans.py`, `routes/cycles.py:83-85` |
> | §2.10 | revise | mismatch | Activation report floor is the clinic's own `required_quality_report_count`; three-report floor ignored | `routes/clinics.py:244-247` |
> | §3.1 | insert | ambiguity | Bundle price round: 8% manager fee → flat 25000 copay reduction, floored at zero | `calculations.py:102-109` |
> | §3.1 | insert | ambiguity | Interval well-formedness at creation; activate/reinstate preconditions; `effective_from` gate is a state refusal | `routes/accounts.py:123-124,180-188` |
> | §3.2 | insert | ambiguity | `external_ref` uniqueness within account | `routes/members.py:59-64` |
> | §3.2 | insert | ambiguity | Lapsed credential outranks full caseload in derived status | `helpers.py:90-97` |
> | §3.2 | insert | ambiguity | `member_id` advocate-list filter semantics; unresolvable member yields nothing | `routes/advocates.py:71-84` |
> | §3.3 | insert | ambiguity | `bundles_offered` / `min_composite_quality_bps` filter semantics; `npi` uniqueness | `routes/clinics.py:54-55,96-105` |
> | §3.3 | revise | mismatch | Contract-activation report gate restated to the clinic's own figure | `routes/clinics.py:244-247` |
> | §3.5 | insert | ambiguity | `bundle_price_snapshot_cents` re-pinned and `approved_cycles` reset to 0 on re-entry to review | `helpers.py:331`, `routes/plans.py:420-421` |
> | §3.5 | insert | ambiguity | Expiry sweep recomputes committed/remaining and counts as a fired transition | `routes/system.py:151-158` |
> | §3.6 | insert | ambiguity | Spacing anchor = latest transfer_date among cycles that reached a transfer; slot test keys constraining instant + 30-day reserved tail | `routes/cycles.py:128-156` |
> | §3.7 | revise | ambiguity | Dispense token mandatory/stale-refusal detail | `routes/medication.py:103-107` |
> | §3.8 | insert | ambiguity | Surrender-route conflict = differing `carrier_kind` on touching windows, tail extended by retention | `routes/members.py:249-294` |
> | §3.8 | revise | ambiguity (flagged) | Pre-route lead pinned to zero at the `route_from` instant | `routes/system.py:126` |
> | §3.9 | insert | ambiguity | MEDICATION claim with no order on file → billed charge as allowance | `routes/claims.py:155-157` |
> | §3.9 | insert | mismatch | Ancillary basis is `CONTRACT_RATE` when bill ≤ slice | `calculations.py:152` |
> | §3.9 | insert | ambiguity (flagged) | `monthly_claim_liability_cents` given its formula (member share over claims settled in clock month) | `calculations.py:253-265` |
> | §3.9 | insert | ambiguity | Appeal-window closure reported as closed-window, not wrong-state | `routes/claims.py:281-283` |
> | §3.9 | insert | ambiguity | Reversal release amount = order's settled cents, else claim's; entitlement advances | `routes/claims.py:322-330,348` |
> | §3.10 | insert | ambiguity | Amendment fields applied per-field; null/absent leaves prior value; `amendment_reason` may be omitted | `routes/outcomes.py:63-71` |
> | §3.10 | revise | mismatch | Restored `Because the exhaustion posture is derived, the loop is genuinely reversible` (a dropped connective) | §3.10 prose |
>
> ## Key findings
> - **§4 role table is already verbatim-identical to the implementation's RBAC table** (89/89 rows, zero differences). The upstream-flagged "NetworkManager not listed as a reader" sites are therefore *not* a PRD-vs-impl mismatch — the implementation itself excludes NetworkManager there, so I deliberately made no change. Likewise the error catalogue §5 is byte-identical to `errors.py`.
> - **Real mismatch corrected:** the "(scaffold's floor of three reports)" annotation in §3.3 claimed `max(3, required_quality_report_count)`; `routes/clinics.py:244-247` uses only the clinic's configured count (tests rely on the 0 default). Both occurrences revised.
> - **`ERROR_BUNDLE_VERSION_STALE` is emitted but absent from the §5 catalogue**; PRD already says "No other operation carries a version token", so only a generic prose mention was added rather than inventing a catalogue row (would require editing the table).
> - **`pathway_coverage_rule` is genuinely ambiguous** (donor/surrogacy use a fixed baseline, ignoring `coverage_pct`; only PRESERVATION multiplies). I did not invent a formula — no test pins it and no PRD passage names it, so pinning it would exceed the impl-anchored mandate.
> - Files inspected (implementation is fully exhaustive at 4,605 lines): `app.py`, `middleware.py`, `errors.py`, `db.py`, `serializers.py`, `calculations.py`, `helpers.py`, `body.py`, `listing.py`, `lookups.py`, `response.py`, `clock.py`, `bp.py`, `start.sh`, and all 11 route modules.

---

# PIPELINE COMPLETE — 2026-09-30T05:21:00.000Z

Final state of `./tasks/task_3113_fertility_benefit_network_management_treatment_bundle_administration/`:

| Artifact | Status |
|---|---|
| `SCAFFOLD.yaml` | 3279 lines — 14 entities, 13 state machines, 8 calculations, 17 validations, 89 endpoints, 38 errors, 9 roles |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2215 lines — 9 rule_ids / 18 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1909 lines — 13 sections / 49 instances |
| `test_helpers/` | 9 files |
| `test_suite/` | conftest + 7 test files — 83 tests, all `Design:`-tagged |
| `workspace/INSTRUCTION.md` | 1424 B |
| `workspace/PRD.md` | 410 lines / 97,118 B |
| `workspace/PRD_FINALIZED.md` | 410 lines / 97,802 B — 3 edits |
| `workspace/PRD_COMPLETED.md` | 410 lines / 107,060 B — 20 pins/revisions |
| `workspace/implementation/` | 4580 lines, 89/89 endpoints, fresh boot verified (401 on unauthenticated `GET /members`) |
| `workspace/implementation/results.{1..8}.json` | all 8 rounds `total=83 passed=83 failed=0 errors=0 skipped=0` |

Incidents: two host-session interruptions during Step 6 (neither an error in the pipeline work). Recovery preserved both orphaned bodies outside the task dir (`/tmp/task3113_orphan_impl`, `/tmp/task3113_attempt2`); the first was selected as the base on the evidence that the second had conflated the advocate-selector `allocation_strategy` with the bundle-netting `allocation_method` enum. Step 7 then took the base from 31/83 to 83/83 over 6 sweeps with zero test deletions.
