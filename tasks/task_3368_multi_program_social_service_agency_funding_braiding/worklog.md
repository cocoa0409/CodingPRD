# Worklog — task_3368_multi_program_social_service_agency_funding_braiding

Scenario: Multi-Program Social Service Agency Funding Braiding & Client Intake (Catholic Charities)

## Step 1: Create task directory — 2026-10-01T09:28:00.000Z

Task directory `./tasks/task_3368_multi_program_social_service_agency_funding_braiding/` was pre-allocated by the caller (index 3368, not computed) and already contained an empty `workspace/`. No other `task_*` directory was created. Verified `./INSTRUCTION.md` exists at the project root for Step 3 copy.

## Step 2a: Generate SCAFFOLD.yaml — 2026-10-01T09:48:00.000Z

First Step 2 attempt (all three files in one subagent) died on the 32000-token output cap with nothing written to disk. Relaunched as Step 2a with forced one-file-per-message write discipline and a `# __APPEND_HERE__` sentinel-append protocol; SCAFFOLD.yaml then completed.

Subagent summary (verbatim):

> Sanity checks run: the skill's `scaffold_lint.py` returns `VERDICT: clean lint` (including FK reverse-reachability across all 19 FKs), I executed every pinned formula in Python (15/15 literals match), and I re-verified that no role, RBAC op, or error reference dangles and that no forbidden concurrency vocabulary appears.
>
> **File:** `/home/ubuntu/github/CodingPRD/tasks/task_3368_multi_program_social_service_agency_funding_braiding/SCAFFOLD.yaml` — 2,125 lines, §1.0–§1.7 only, no `scaffold_difficulty_design` or `scaffold_corner_design` key.
>
> **Counts:** 12 entities, 6 state machines, 8 calculations, 42 endpoints, 29 validations, 29 errors, 6 roles, 2 OCC concurrency rules.
>
> **Design adjudications:**
> - Archetype: Quota/allocation (funding braiding) + Compliance/audit, with cascading side effects, threshold triggers, OCC, and selector policy.
> - Endpoint budget: I landed at 42, not ~35. The linter derives each entity's URL segment only from a single-resource `GET /api/<seg>/{id}`, so 8 such GETs were mandatory for FK reverse-reachability. I paid for them by dropping the program/client list GETs, `POST /grants/{id}/close` (and the unreachable `CLOSED` enum), and by folding `InKindDonation`/`OutcomeReport` into sub-resource GETs under `/grants/{id}/`. Dropping `POST /enrollments/{id}/suspend` makes `SUSPENDED` reachable only through the grant-freeze cascade — deliberate depth.
> - Validation priorities: OCC sits at priority 5, *above* the business checks, so a stale-version create isn't masked by a period-overlap error; that ordering is what makes the 412 deterministically testable.
> - `ServiceDelivery.sequence_no` (server-minted monotonic counter) is the ordering key for braiding and duplication, since a frozen logical clock makes `created_at` tie. No UUID/id decides any observable result.
> - `InKindDonation.program_id` was removed; the match-eligible program is reached via `Grant.program_id`.

Orchestrator verification against disk (independent of the hand-back): `sha256 b915c6947d61a6bd6c62fda95467d23cc9470e4291fb1503318a6cbec88e74b0`, 2,125 lines, `yaml.safe_load` clean, top-level keys exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, concurrency_rules, state_machines, calculations, validations, endpoints, errors, roles`; counts confirmed 12/6/8/29/42/29/6; no `scaffold_*_design` key present.

### Note on Step 2b attempts

The host session was interrupted mid-Step-2b. On resume, disk inspection showed SCAFFOLD.yaml intact but BOTH design-index files absent. Two further attempts to produce both indices in one subagent each died on the 32,000-token single-response output cap with nothing written (the subagent composed the entire file before its first Write). The fix that worked: one file per subagent, plus a protocol forcing the first message to Write a skeleton ending in a `# __APPEND_HERE__` sentinel, then exactly one rule/section appended per message in payloads under 150 lines.

## Step 2b-i: Generate SCAFFOLD_DIFFICULTY_DESIGN.yaml — 2026-10-01T11:07:00.000Z

Subagent summary (verbatim):

> Sanity check run: the file parses as YAML with a single top-level key `scaffold_difficulty_design`; the skill's own `scaffold_lint.py` (run in a throwaway `/tmp` copy with a stub corner file, so the task dir keeps exactly one output file) reports `VERDICT: clean lint` over 18 instances and 310 structured calls; every `grounds:` ref, `call:`, `as:` role, payload field, and `${var}` binding was independently verified against SCAFFOLD.yaml.
>
> result: Wrote /home/ubuntu/github/CodingPRD/tasks/task_3368_multi_program_social_service_agency_funding_braiding/SCAFFOLD_DIFFICULTY_DESIGN.yaml (1,623 lines; 9 rules, 18 instances, 0 stubs; scaffold_lint.py verdict clean).
>
> Details:
> - Rules: all nine §0.5 `rule_id`s, 2 instances each (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
> - No rule left uncovered and no instance stubbed — every instance carries a full structured `setup_api_calls` / `trigger` / `assert` recipe with literal asserts computed from the scaffold's own worked examples (e.g. admin totals 6800 vs 7400, per-line rounding 202 vs 201, match credits 36000/14000/0).
> - Unreachable-by-design paths were re-grounded rather than stubbed: SEALED/PROTECTED clients cannot have screens created (the priority-6 gate covers screen creation), so the confidentiality instances drive the write refusal through `POST /api/enrollments` and the read projection through `GET /api/clients/{id}`; the capacity probe uses the priority-7 refusal since no `GET /api/programs` endpoint exists.
> - Chain convention documented in-file: the first `determine` call fires the PENDING→PENDING verification hop (its preconditions omit the parent state), the parent is routed, the second fires the determination hop.

Orchestrator verification: `sha256 bd86a359d3e21776016cb23e819be66ddecf19b9420fdf40f1dcb7d37ec62a72`, 1,623 lines, no sentinel, single top-level key, 9 rules × 2 non-stub instances = 18.

## Step 2b-ii: Generate SCAFFOLD_CORNER_DESIGN.yaml — 2026-10-01T11:28:00.000Z

Subagent summary (verbatim):

> Sanity checks run: YAML parses; 9 sections / 71 instances / 55 non-stub / 16 stubs; every `grounds` ref resolves against SCAFFOLD.yaml; zero unbound `${var}`; zero bare-literal OCC versions; names unique; sentinel removed. `scaffold_lint.py` scans all 55 §1.9 instances (857 calls) and prints `VERDICT: clean lint`.
>
> Note: I dropped the `sections:` wrapper the protocol described — the skill's §1.9 schema and the linter both require `scaffold_corner_design:` to be a direct list of `{section, instances}`; with the wrapper the linter reported "§1.9 instances scanned: 0". The linter also required error-envelope captures on the RBAC-denial triggers so it recognizes them as intentional negative tests.
>
> Deliberately not covered (each already owned by §1.8, emitted as `excluded_because:` stubs): braided-allocation rank-vs-period divergence, line-level rounding order, in-kind ceiling/remainder branch, burn-ratio 0.85 boundary, zero-capacity program, tier-first vs consent-first projection, authorization half-open and outcome-report closed interval overlaps, the two named priority pairs, both non-linear state machines, both transitive cascades, both compensating invariants, and the frozen-grant activation gate. Also skipped: outcome-report submit/resubmit happy paths (need ≥5 distinct served clients, unreachably heavy for a breadth corner) and the RETURNED→SUBMITTED rate recompute (the calculation's forced-RETURNED clause and the transition's unconditional SUBMITTED clause conflict, so no single derivable expectation exists).
>
> result: /home/ubuntu/github/CodingPRD/tasks/task_3368_multi_program_social_service_agency_funding_braiding/SCAFFOLD_CORNER_DESIGN.yaml — 2737 lines, 9 sections, 55 non-stub corner instances, lint clean.

Orchestrator verification: `sha256 09d68eafe608ab9cc77578a9077630f87d47c344402ca539213c6496d6294c72`, 2,737 lines, no sentinel, single top-level key whose value is a 9-element list, 55 non-stub + 16 excluded instances.

**Scaffold phase complete.** Test-instance budget for Step 5: 18 (depth, queue A) + 55 (breadth, queue B) = **73 tests**.

## Step 3: Copy shared files — 2026-10-01T11:34:58.505Z

`cp ./INSTRUCTION.md ./tasks/task_3368_multi_program_social_service_agency_funding_braiding/workspace/INSTRUCTION.md` — 1,424 bytes copied; workspace/ now holds `INSTRUCTION.md` only. The contract requires `./implementation/start.sh`, listening on `$PORT` (default 10000), bound to `0.0.0.0`, responding within 60s of invocation.

## Step 4: Generate PRD.md — 2026-10-01T11:50:00.000Z

Subagent summary (verbatim):

> Sanity checks run: all three hard contracts verified mechanically against the scaffold, §2.2 confirmed byte-identical to the canonical block, sentinel cleared, and the document ends at §5 with no audit footer.
>
> **Written:** `/home/ubuntu/github/CodingPRD/tasks/task_3368_multi_program_social_service_agency_funding_braiding/workspace/PRD.md` — 387 lines, 82,864 bytes.
>
> **Sections:** §1 Introduction; §2.1 RBAC, §2.2 Response Structure, §2.3 Pagination, §2.4 Common Resource Properties, §2.5 The Agency Logical Clock, §2.6 Monetary Precision, §2.7 Client Confidentiality, §2.8 Public-Funding Guardrails, §2.9 OCC, §2.10 Request Validation Precedence, §2.11 Nested Resource Resolution, §2.12 Grant Posture Propagation; §3.1–3.9 (funding landscape, single door, assessment lifecycle, eligibility/capacity cascade, enrollment, authorizations/deliveries, braiding/billing/reversal, in-kind match credit, outcome reporting); §4 Endpoint Definitions (42 rows, 4 columns); §5 Error Code Catalogue (29 rows, 2 columns).
>
> **Contract reports**
> ```
> Field coverage check:
> - entities[].fields: 92 required, 92 present, 0 missing
> - endpoints[].input: 68 required, 68 present, 0 missing
> - endpoints[].path_params: 1 required, 1 present, 0 missing
> - endpoints[].query_params: 0 declared in scaffold (filters live in `input`)
> Status: PASS
>
> Rule coverage check:
> - validations[] priority (29): expressed in §2.10 with the global lowest-number-wins rule
> - concurrency_rules[] (2): both write_endpoint + occ_field + ERR_STALE_VERSION/412 named in §2.9
> - state_machines[] transitions (28): all from/to states, preconditions and side effects rendered
> - calculations[] (8): all formulas rendered as precise prose
> - validations[] conditions (29): each matchable to its error_id in §2/§3
> - endpoints[].side_effects / applies_to: expressed
> - entities[].fields[] structured content: reconstructible
> - sibling-branch symmetry: enrollment exit branches and grant posture branches carry equal density
> Status: PASS
>
> Path purity check (§3 only):
> - backtick tokens scanned: 701
> - tokens starting with `/`: 0
> - bare HTTP-method tokens: 0
> - method+path combined tokens: 0
> Status: PASS
> ```
>
> **Scaffold rules I could not render without contradicting the scaffold itself** (all rendered faithfully to the scaffold's own wording; flagged for your awareness):
> 1. `ServiceAuthorization.units_delivered` is defined over deliveries in `DOCUMENTED, BILLED, PAID`, but `ServiceDelivery.status` has no `PAID` member.
> 2. `in_kind_match_credit` breaks `created_at` ties by `sequence_no`, but `InKindDonation` has no `sequence_no` field.
> 3. `OutcomeReport` submission has both a hard `ERR_MATCH_REQUIREMENT_UNMET` (422) validation and a transition side effect that places the report in `RETURNED` on the same shortfall.
> 4. `ERR_GRANT_NOT_FOUND` lists `POST /api/grants` in `applies_to`, though grant creation names no grant.
> 5. `Client.open_enrollment_count` is described as counting `PENDING/ACTIVE/SUSPENDED`, while its transitions only increment/decrement on `ACTIVE` transitions. Both statements are in the PRD as declared.
>
> result: PRD.md generated at /home/ubuntu/github/CodingPRD/tasks/task_3368_multi_program_social_service_agency_funding_braiding/workspace/PRD.md (387 lines, 82,864 bytes), with all three hard contracts verified PASS.

Orchestrator verification: `sha256 e28a65aabb9e36c3f681885bb7a4a72c9233a0c963c9593e2396e6fab92673f9`, 387 lines / 82,864 bytes, no sentinel, headings run §1 → §5 in order, and grep for `scaffold_difficulty_design|scaffold_corner_design|test_recipe|Design: Difficulty|Design: Corner` returns 0 hits (no design-index leakage into the contract).

**Carry-forward risks for Step 7** (from the flagged list above): items 1–3 and 5 are exactly the "unpinned symbolic constant / contradictory literal" shape that has stalled this pipeline before. If Step 7 stalls or the sweep shows clusters around `units_delivered`, `in_kind_match_credit` ordering, outcome-report submission, or `open_enrollment_count`, re-derive the expectation from PRD + SCAFFOLD rather than trusting a single test's literal.

## Step 5: Generate unit tests — 2026-10-01T12:20:00.000Z

Subagent summary (verbatim):

> Sanity checks all pass: 73 test functions, each with exactly one `Design:` tag, all 73 tags resolving to real non-stub instances in the two design indices (18 Difficulty + 55 Corner, 0 duplicates, 0 bad tags); the 16 uncovered instances are exactly the `excluded_because` stubs; every file compiles; every quoted PRD citation greps verbatim in `workspace/PRD.md`; every name imported from `test_helpers` resolves; no `skip`/`skipif`/`xfail`.
>
> Files written (absolute paths, line counts):
> - `/home/ubuntu/github/CodingPRD/tasks/task_3368_multi_program_social_service_agency_funding_braiding/test_helpers/` — `__init__.py` 19, `types.py` 420, `api_client.py` 155, `api_errors.py` 71, `assertions.py` 203, `constants.py` 66, `factories.py` 169, `test_users.py` 47, `fixtures.py` 585
> - `/home/ubuntu/github/CodingPRD/tasks/task_3368_multi_program_social_service_agency_funding_braiding/test_suite/` — `conftest.py` 40, `test_01_funding_landscape.py` 159, `test_02_client_intake.py` 152, `test_03_eligibility_screening.py` 254, `test_04_capacity_cascades.py` 241, `test_05_enrollment_lifecycle.py` 233, `test_06_authorizations_and_deliveries.py` 330, `test_07_braiding.py` 292, `test_08_billing_and_posture.py` 185→249, `test_09_in_kind_and_outcome_reports.py` 253, `test_10_errors_and_rbac.py` 299
>
> Counts: 18 queue A + 55 queue B = 73. No instances were skipped; the 16 `excluded_because` stubs were verified to resolve to a difficulty instance and deliberately not translated.
>
> PRD/scaffold contradictions I adjudicated:
> 1. **Burn-ratio literals in §1.8 are wrong.** Several difficulty recipes assert `burn_ratio` values that ignore the administrative share (e.g. `documentation_cascade...` asserts obligated 54000 / burn 1.000000 for a 54000-cent delivery at admin 0.10). PRD §3.7 says `obligated_cents` rises by allocated **and** administrative amounts, so I re-derived: obligated 59400, burn 1.100000. The corner recipes (0.297000 from 59400/200000) confirm the PRD reading. Status assertions (THROTTLED/FROZEN/OPEN) are unchanged and still robust.
> 2. **`burn_ratio_exactly_point_eight_five_is_throttled` cannot hit its own boundary** as specified (34×5000 at admin 0.10 → 0.935000, not 0.850000). I kept the setup and re-derived the ratio; the test still proves `>=` throttling but not the exact 0.850000 point.
> 3. **`version == 1` on creation responses** is not uniquely derivable from §2.4 ("starts at its creation value"). Relaxed to `version >= 1` in the two creation tests; exact `+1` arithmetic where PRD states it is kept.
> 4. **`active_slots` on the program-create response** — PRD §3.1 says it "is surfaced when programs are listed", so I dropped it from the create assertion.
> 5. **`posture_computed_at` on a no-op recompute** — PRD only promises the stamp on a posture *change*; dropped, keeping the version bump (§2.4 covers recomputation).
> 6. **Program `enrolled_slots`** has no read endpoint, so the cascade is asserted through its observable effects (enrollment existence, capacity refusals, sweeps).
>
> result: 73 design-index-tagged tests (18 difficulty + 55 corner) plus 9 helper modules and conftest written to `/home/ubuntu/github/CodingPRD/tasks/task_3368_multi_program_social_service_agency_funding_braiding/`; all compile, all tags resolve, all PRD citations grep verbatim, no skips.

Orchestrator verification against disk (independent of the hand-back): 20 files / 4,237 lines; `python3 -m compileall` clean; **73 `Design:` tags — 18 Difficulty + 55 Corner, 0 duplicates, 0 unresolvable against the design indices, 0 of the 73 valid instances left uncovered**; no `skip`/`skipif`/`xfail` anywhere; and a real `python3 -m pytest test_suite --collect-only -q` collects **73 tests in 0.42s, exit 0** — so no dangling imports in the helper package graph.

**Adjudication carried into Step 6/7:** the test generator deliberately *overrode* the §1.8 difficulty recipes on the burn-ratio arithmetic (admin share included in `obligated_cents`) because the PRD's §3.7 wording plus the §1.9 corner recipes both contradict the §1.8 literals. The implementation must follow PRD §3.7, not the §1.8 literal — Step 6 never sees §1.8, so this resolves itself, but Step 7 must not "fix" the implementation toward the §1.8 numbers.

## Step 6: Generate implementation — 2026-10-01T12:55:00.000Z

Launched **alone** (not concurrent with Step 5) per the task author's endpoint constraint, so the physical isolation that concurrency would have provided was restored by an explicit read ban in the prompt: the subagent was forbidden from reading `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, or `test_helpers/`, and forbidden from running pytest.

Subagent summary (verbatim):

> Implementation complete and verified. Checks run: `bash -n start.sh` OK; `python3 -m compileall -q .` OK; smoke boot on a free port served `GET /api/grants` 200 with the exact envelope, `POST /api/_clock/set_current_utc` 200, missing headers 401; three self-written end-to-end drivers (0 failures) exercised the full funding→intake→enrollment→authorization→delivery→braid→bill→in-kind→outcome chain, both braiding variants, void reversal, capacity cascade, confidentiality, 180-day expiry, and OCC 412. No pytest was run; state-wipe confirmed by creating a grant, rebooting, and seeing 0.
>
> Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_3368_multi_program_social_service_agency_funding_braiding/workspace/implementation/`): `start.sh` 10, `requirements.txt` 1, `app.py` 70, `clock.py` 68, `common.py` 155, `db.py` 107, `errors.py` 46, `response.py` 121, `services/` `__init__.py` 1, `allocation.py` 177, `authorization.py` 82, `capacity.py` 74, `confidentiality.py` 88, `delivery.py` 219, `eligibility.py` 168, `enrollment.py` 150, `inkind.py` 83, `intake.py` 95, `outcome.py` 58, `posture.py` 90; `routes/` `__init__.py` 1, `authorizations.py` 61, `clients.py` 102, `deliveries.py` 96, `enrollments.py` 79, `finance.py` 223, `foundation.py` 217, `intake.py` 116 (2758 total).
>
> One real bug was caught by the drivers and fixed: the braiding basis is read from `Grant.cost_allocation_basis` (Funder has no such field).
>
> PRD ambiguities resolved: (1) `api_request_timestamp` uses the logical clock, since §2.5 bars wall-clock reads; (2) outcome submit below match does both §3.8 and §3.9 — 422 `ERR_MATCH_REQUIREMENT_UNMET` with the report left `RETURNED`; (3) `alternate_disallowed_cents` follows PRD prose ("cheapest row allowed") over the scaffold's worked example, which implies the opposite; (4) the ELIGIBLE→INELIGIBLE capacity reversal fires only when `enrolled_slots > capacity_slots`, else filling a capacity-2 program would deny both seats; (5) EXPIRED screens may re-verify via `determine` (no other verification path exists); (6) absent `consent_expires_on` never expires; (7) client reads: SEALED always 403, PROTECTED 403 unless a consented domain is currently valid; (8) no attestation refusal at program creation (defaults to false are legal); (9) no uniqueness enforcement — no catalog code exists; (10) `outcome_rate` always uses the base all_served variant (no selector in the model); (11) in-kind rows are created ACCEPTED (no creation-time rejection rule); (12) pre-routing `determine` persists the verification hop, then raises `ERR_INTAKE_NOT_ROUTED`, which is what makes routing reachable.
>
> result: 42-endpoint Flask implementation written to workspace/implementation/ (2758 lines, in-memory only, no seeding); boots clean per-test via start.sh, smoke boot and three end-to-end drivers pass with 0 failures.

Orchestrator verification against disk (independent of the hand-back — this step is the known endpoint-overshoot failure mode):
- 27 source files, **2,758 lines — exactly the claimed total**; no `# __APPEND_HERE__` sentinel left anywhere.
- `python3 -m compileall -q .` clean; `bash -n start.sh` clean.
- **Normalized route diff scaffold-vs-impl: 42 scaffold endpoints, 42 impl routes, 0 missing, 0 extra** (normalization collapses Flask `<param>` and scaffold `{param}` to `{}`, per the known false-alarm mode). No overshoot, no drift.
- Seeding grep: only two docstring lines *stating* that nothing is seeded; no seed/preload/hardcode data.
- Live smoke boot on a free port: server came up on 0.0.0.0, `GET /api/grants` as PlatformAdmin → **403 `ERR_FORBIDDEN_ROLE`** (correct — PlatformAdmin's only exclusive op is the clock, and it has no shared ops), missing headers → **401 `ERR_UNAUTHENTICATED`** with the exact envelope, and `api_request_timestamp` reads `2026-09-01T00:00:00.000Z` (logical clock, not wall clock). Killed only the PID I started; verified it stopped.

**Carry-forward risks for Step 7:** the impl's ambiguity resolutions (2), (3), (4), (7) are exactly where Step 5's tests may have read the PRD the other way — especially `alternate_disallowed_cents`, where impl deliberately followed PRD prose *against* the scaffold's worked example. If Step 7 sees a cluster there, the PRD prose is the authority, and the §1.9 recipe literal is the thing to re-derive.

## Step 7: Test/fix iteration loop — 2026-10-01T13:20:00.000Z

Subagent summary (verbatim):

> Sanity check passed: all 8 rounds started at 13:16:35, after the last source edit at 13:13:57 — so the sweep reflects the final code. All 8 `results.*.json` are present and valid, 73 tests collected, no skips/xfails anywhere.
>
> ## Summary
>
> **Iterations run:** 2 eight-round parallel sweeps + 2 single-round smoke runs.
> - Sweep 1: 0/73 in all 8 rounds → systemic: every request 404'd.
> - Smoke A: 67/73. Smoke B: 73/73. Sweep 2: **73/73 in all 8 rounds.**
>
> **Root cause of sweep 1 (0/73):** `test_helpers/api_client.py` built URLs from the runner's bare `API_BASE_URL` (`http://localhost:PORT`) with no `/api` prefix, so every call hit a non-existent route. Sibling tasks have `api_prefix: ""`; this task's PRD §4 states verbatim "Every endpoint is mounted under the `/api` prefix".
>
> **Tests deleted:** none. Four assertions removed by STEP 1c splitting (PRD covers part of the rule, not the rest):
>
> | Test | Assertion removed | Category |
> |---|---|---|
> | `test_confidentiality_tier_first_write_refusal_vs_consent_first_read_projection` | `shareable_domains == ["HOUSING"]` on a SEALED client read | Unique-derivability collapse: §2.7 says the client read is guarded "under the base tier-first variant" (SEALED refused outright), while §2.7's "practical consequence" sentence and §3.2 say a SEALED client's consent *is* listed. Design-index `dual_variant_calc` drove the assertion. Write-refusal assertion kept. |
> | `test_client_get_computed_open_enrollment_count_after_activation` | `open_enrollment_count == 0` with a PENDING row | Unique-derivability collapse: §3.5 defines the count as live rows in PENDING/ACTIVE/SUSPENDED recomputed on read (§2.4 names it a recomputed value), while §3.5's transition rules move it only on ACTIVE. Kept `== 1` after activation (both readings agree). |
> | `test_enrollment_activation_gated_by_governing_grant_posture` | `open_enrollment_count == 0` while SUSPENDED | same |
> | `test_documentation_cascade_freezes_grant_and_suspends_its_own_enrollment` | `open_enrollment_count == 0` while SUSPENDED | same |
>
> **Fixes to `test_helpers/`:**
> - `api_client.py` — added `ApiClient.__init__` appending `/api` to the base URL (PRD §4). Fixed all 73.
> - `fixtures.py` `verify_screen` — payload was `{"determination": "PENDING"}`; PRD §3.4 declares the supplied determination as ELIGIBLE/INELIGIBLE only. Now sends `ELIGIBLE` and tolerates the branch refusal (any 4xx, e.g. `ERR_INTAKE_NOT_ROUTED`) while asserting the verification hop persisted — required because §3.3 gates routing on an already-VERIFIED screen. Fixed ~38 tests.
> - `fixtures.py` `setup_two_grant_braiding` — `landscape["grant_a"]` KeyError; `setup_landscape` keys grants positionally, so grant_a/grant_b now map to `grants[0]`/`grants[1]`.
> - `fixtures.py` — added `refresh_authorization()`.
>
> **Fixes to `test_suite/`:**
> - `test_06` `test_service_delivery_sequence_no_...` — passed a *delivery's* `version` as `expected_service_authorization_version`; now re-reads the authorization (PRD §3.6: recording a delivery increments the authorization's version).
> - `test_06` `test_frozen_grant_state_check_outranks_zero_unit_fiscal_check` + `test_05` `test_enrollment_activation_gated_by_governing_grant_posture` — authorization window (default 09-01→10-01) didn't cover the scenario clock 2026-10-02, so §3.6's `ERR_NO_ACTIVE_AUTHORIZATION` fired before the intended check; window widened.
> - `test_09` `test_match_requirement_unmet_...` — replaced `status == "DRAFT"` with `status == "RETURNED"` (PRD §3.9 verbatim: "not advanced and lands in `RETURNED` instead"). Strengthening, not weakening.
>
> **Fixes to `implementation/`:**
> - `routes/finance.py` `submit_outcome_report` — moved the §3.8 match-requirement check ahead of the §3.9 denominator-floor short-circuit, so a below-the-line submission is refused with `ERR_MATCH_REQUIREMENT_UNMET` (422) even when the effective denominator is also below 5. (§3.8 states the match position as a precondition of submission; the impl's own "do both" adjudication was inconsistently applied.)
>
> **Final sweep tally:** 73 / 73 passed in each of the 8 rounds (results.1.json … results.8.json, all `passed == total == 73`).
>
> result: task_3368 test loop converged — 73/73 tests pass in all 8 parallel rounds; 1 impl fix (§3.8 match check ordering), 4 test_helpers fixes, 4 test_suite fixes, 4 ambiguous assertions removed.

Orchestrator verification against disk (independent of the hand-back):
- All 8 `results.{1..8}.json` present, each parsed and confirmed `passed == total == 73`.
- **Sweep validity confirmed by mtime**: newest non-`__pycache__` source file is `routes/finance.py` at epoch 1790860047; `results.1.json` is at 1790860727 — the sweep postdates the last code edit by ~11 minutes, so it reflects the final code.
- **No silent deletions**: `test_suite/` still holds exactly **73** test functions and **73** `Design:` tags, 0 unresolvable, 0 of the 73 valid instances uncovered; `pytest --collect-only` collects 73 in 0.20s.
- No `skip` / `skipif` / `xfail` anywhere in `test_suite/` or `test_helpers/`.

**Step 8 trigger:** NOT skipped. Step 7 ran 2 sweeps plus 2 smoke runs beyond the baseline and landed 1 `implementation/` fix, 4 `test_helpers/` fixes, 4 `test_suite/` fixes, and 4 STEP-1c assertion removals — so PRD.md did not uniquely determine everything the implementation does.

**Carry-forward for Step 9** (unasserted sibling paths, since test-side fixes dominated): `alternate_disallowed_cents` (impl follows PRD prose over the scaffold worked example, and no surviving test asserts the literal), the SEALED-client `shareable_domains` projection (assertion removed — impl's choice is now unpinned by any test), and `open_enrollment_count` recomputation semantics across a SUSPENDED window (assertion removed three times — the impl's PENDING/SUSPENDED counting behavior is now asserted nowhere).

## Step 8: Finalize PRD — 2026-10-01T13:35:00.000Z

Not skipped (Step 7 ran 2 sweeps + 2 smoke runs beyond baseline, with 1 impl fix, 4 test_helpers fixes, 4 test_suite fixes, 4 assertion removals). The Step 7 worklog entry was inlined verbatim as `<step_7_diff>` in the subagent prompt.

Subagent summary (verbatim):

> Sanity check complete: `diff -u PRD.md PRD_FINALIZED.md` shows exactly 10 hunks / 25 changed lines, 387 → 388 lines (+0.26%); I re-verified every pinned claim against the implementation source (and caught one over-claim of my own in §3.4, now fixed). No SCAFFOLD/worklog reads; edits only in PRD_FINALIZED.md.
>
> **Changes (section — op — what — impl site)**
> - §2.7 — revise — consent_first projection lists a PROTECTED client's still-authorized domains and a STANDARD client's whole `consent_scope`; a SEALED record never surfaces one — `services/confidentiality.py:57-88`, `routes/clients.py:67-71`
> - §2.7 — insert — a read names no target domain: SEALED refused outright, PROTECTED refused unless one consented domain is live — `confidentiality.py:57-75`
> - §3.2 — revise — sealed record returns no `shareable_domains`; consent never honoured on writes — `routes/clients.py:67-70`
> - §3.4 — insert — supplied `determination` ∈ {ELIGIBLE, INELIGIBLE} else `ERR_BAD_REQUEST` 422; omitted = hop only; hop durable when the branch refuses — `services/eligibility.py:138-158, 67-77`
> - §2.12, §3.5 (×3), §3.7 — revise — activation, reinstatement and suspension leave `open_enrollment_count` unchanged; an exit lowers it by one — `services/posture.py:46-58`, `services/enrollment.py:79-98, 110-139`
> - §3.5 — insert — count is derived, never adjusted in place; one PENDING row reads 1 — `services/capacity.py:11, 53-65`
> - §3.8 — revise — match check is DRAFT-only, runs before the §3.9 floor, leaves the report RETURNED — `routes/finance.py:172-189`
> - §3.9 — revise — DRAFT shortfall answers with `ERR_MATCH_REQUIREMENT_UNMET` — `routes/finance.py:179-185`
> - §5 — insert — `ERR_BAD_REQUEST` / 422 row — `errors.py:35`
>
> **Pre-edit search logs (a subject / b paths / c adjustment)**
> 1. Client read + `shareable_domains`. b: read `confidentiality.py` and `clients.py` whole; grepped callsites (`assert_client_readable` 1, `shareable_domains` 1, `assert_allowed` 3); confirmed GET /clients/{id} is the only client-returning route. c: deleted the "SEALED consent is listed" claim and scoped the projection to what the read actually surfaces.
> 2. determine input/hop. b: read `routes/intake.py`, `services/eligibility.py`, `services/intake.py`; grepped every test determine payload. c: "determination still PENDING" → "determination dimension untouched"; "screened_at restamped" → "the hop's own state change stands" (the hop can no-op or raise).
> 3. `open_enrollment_count`. b: grepped whole impl — only writers are creation (0) and `capacity.recompute_client`; read all four callsites (read, activate, exit-from-ACTIVE, freeze cascade). c: every increment/decrement claim replaced with derived-value wording.
> 4. Match/floor. b: read `routes/finance.py` submit, `services/inkind.py`, `services/outcome.py`; grepped `match_satisfied` (1 callsite). c: narrowed the precondition to the DRAFT path (impl's own guard) instead of the PRD's universal wording; added the RETURNED side effect and ordering.
>
> Out-of-scope observations left untouched: the denominator variant is always ALL_SERVED; the hop also accepts EXPIRED; screen expiry runs on reads; other `ERR_BAD_REQUEST` raise sites.
>
> result: /home/ubuntu/github/CodingPRD/tasks/task_3368_multi_program_social_service_agency_funding_braiding/workspace/PRD_FINALIZED.md produced — 13 pinned edits in 10 hunks (387→388 lines) across §2.7/§3.2/§3.4/§3.5/§3.7/§3.8/§3.9/§5, each traced to a Step 7 fix and verified against implementation/.

Orchestrator verification: `PRD_FINALIZED.md` = 388 lines / 85,271 bytes vs `PRD.md` 387 lines / 82,864 bytes; `diff` reports exactly 25 changed lines. **`implementation/` is byte-identical since the Step 7 sweep** — newest source file `routes/finance.py` at epoch 1790860047 still precedes `results.1.json` at 1790860727 — so Step 8 did not invalidate the sweep.

## Step 9: Complete PRD — 2026-10-01T13:52:00.000Z

Subagent summary (verbatim):

> Verification passed: 388 lines in both files, 35 single-line replacements with zero insertions or deletions, all headings identical. Writing the final report.
>
> **Sanity check run:** copied `PRD_FINALIZED.md` → `PRD_COMPLETED.md`; re-read every endpoint/service file in `implementation/`; confirmed the final artifact has identical line count (388), identical headings, and a diff of exactly 35 replaced lines (0 insertions, 0 deletions) — all in-paragraph revisions. Chars: 85,271 → 89,431 (+4,160).
>
> Files: `/home/ubuntu/github/CodingPRD/tasks/task_3368_multi_program_social_service_agency_funding_braiding/workspace/PRD_COMPLETED.md` (artifact), `/home/ubuntu/github/CodingPRD/tasks/task_3368_multi_program_social_service_agency_funding_braiding/workspace/implementation/` (authority).
>
> **Counts: 19 ambiguity-pins, 16 mismatch-revisions** (lines 258 and 268 carry one of each).
>
> - §2.2 — revise — ambiguity — `api_request_timestamp` reads the logical clock — response.py:35
> - §2.3 — revise — ambiguity — limit clamped to 1..100, bad ints default, offset clamped, timestamp ties keep write order — response.py:92, db.py:92
> - §2.4 — revise — mismatch — recomputed slot counters/count that don't change stamp nothing — capacity.py:48
> - §2.5 — revise — mismatch — elapsed-time transitions fire at the start of every request, reads included — app.py:37
> - §2.7 — revise — ambiguity — null `consent_expires_on` never lapses — confidentiality.py:23
> - §2.8 — revise — mismatch — attestation gate is not applied at program creation — routes/foundation.py:55
> - §2.10 — revise — ambiguity — assessment/screen/allocation path misses answer `ERR_INVALID_STATE` 409 — common.py:82
> - §2.10 — revise — ambiguity — `ERR_BAD_REQUEST` sits outside the tier ladder; non-empty/unique/non-negative/range constraints are unenforced — response.py:108
> - §2.11 — revise — ambiguity — body-ref resolution order; bad `funder_id` → `ERR_GRANT_NOT_FOUND` — routes/foundation.py:92
> - §3.1 — revise — mismatch — `active_slots` is not "surfaced when programs are listed" (no program read endpoint exists) — routes/foundation.py
> - §3.1 — revise — mismatch — no gate at program creation; applied at screen/enrollment only — routes/foundation.py:55
> - §3.1 — revise — mismatch — new grant always opens `OPEN` — posture.py:84
> - §3.1 — revise — ambiguity — grant read keys `cash_burn_ratio`, `child_counts` — routes/foundation.py:155
> - §3.2 — revise — mismatch — `county_code`/`immigration_status` are not screened against — eligibility.py:80
> - §3.3 — revise — mismatch — `assessment_date` is request-supplied — routes/clients.py:89
> - §3.3 — revise — mismatch — resubmission re-tests both lists and clears the reason code — intake.py:19
> - §3.3 — revise — ambiguity — bad `return_reason_code` → `ERR_INVALID_STATE` — intake.py:52
> - §3.4 — revise — ambiguity — missing income/household → `ERR_BAD_REQUEST` — eligibility.py:52
> - §3.4 — revise — ambiguity — bad determination value refused before the hop — eligibility.py:142
> - §3.4 — revise — ambiguity — hop accepts `EXPIRED`; income≤0 → `ERR_INVALID_STATE` — eligibility.py:68
> - §3.4 — revise — mismatch — only confidentiality and capacity are computed; income/immigration/residency reasons come from the request — eligibility.py:80,129
> - §3.4 — revise — mismatch — no backwards cascade; ELIGIBLE screens are never re-flipped — eligibility.py:90
> - §3.4 — revise — ambiguity — expiry applies on request handling and bumps version — eligibility.py:23
> - §3.5 — revise — mismatch — `DENIED` is unreachable (`deny()` never called) — enrollment.py:142
> - §3.6 — revise — ambiguity — bad code/window/units/rate → `ERR_BAD_REQUEST` — authorization.py:47
> - §3.6 — revise — ambiguity — `service_date` defaults to the clock; missing units/rate → `ERR_BAD_REQUEST` — delivery.py:41
> - §3.7 — revise — mismatch — commingling is the sixth documentation requirement — delivery.py:115
> - §3.7 — revise — ambiguity — documentation refusals are `ERR_INVALID_STATE`; only `PROVISIONAL` lines are discarded — delivery.py:91, allocation.py:87
> - §3.7 — revise — mismatch — disallowed amount is the billed row's own total, not a sum over disallowed rows — allocation.py:167
> - §3.7 — revise — ambiguity — alternate variant allows every tied-cheapest row — allocation.py:158
> - §3.7 — revise — ambiguity — line `disallowed_cents` is always zero — allocation.py:102
> - §3.8 — revise — mismatch — `donation_date` is request-supplied — routes/finance.py:72
> - §3.8 — revise — ambiguity — contributions are created `ACCEPTED` and never move — routes/finance.py:99
> - §3.9 — revise — ambiguity — `denominator_basis` initialized `ALL_SERVED` — routes/finance.py:147
> - §3.9 — revise — ambiguity — claimed denominator<5 and window (DRAFT only) → `ERR_INVALID_STATE` — routes/finance.py:162
> - §3.9 — revise — ambiguity — match refusal leaves the computed `rate_pct` — routes/finance.py:179
> - §3.9 — revise — mismatch — completed-only variant never evaluated — outcome.py:44
> - §3.9 — revise — ambiguity — effective floor answers 200 with the report in `RETURNED` — routes/finance.py:186
>
> Refuted/dead, left unchanged: the documentation-time `ERR_ADMIN_RATE_EXCEEDED` re-check (delivery.py:116-125) is unreachable because grant creation already enforces it; `enrollment.deny()` is dead code (covered by the §3.5 revision).
>
> result: PRD_COMPLETED.md written (388 lines, +4,160 chars vs PRD_FINALIZED.md) with 35 in-place edits — 19 ambiguity-pins, 16 mismatch-revisions — aligning it to implementation/ with no new sections or paragraphs.

Orchestrator verification: `PRD_COMPLETED.md` = 388 lines / 89,431 bytes. `diff -q PRD_FINALIZED.md PRD_COMPLETED.md` reports the files **differ** — so this was a real edit, not the silent-`cp`-no-op failure mode; `diff -u` shows 68 +/- lines (34 replaced line pairs, consistent with the reported 35 edits); heading count identical (no new sections). `implementation/` remains untouched since the Step 7 sweep.

## Final verification: independent 8-round sweep (orchestrator-run) — 2026-10-01T13:55:10Z

Step 7's own results files were deleted and the sweep re-run by the orchestrator, independently of the fix subagent, after Step 9 had finished — so this evidence reflects the frozen final artifacts.

- `rm -f workspace/implementation/results.*.json`, then 8 rounds launched concurrently against `test_suite/` with `--isolation per-test-server`, `--timeout 120`, `--test-timeout 30`, joined with `wait`. Ports were claimed per round from the runner's `fcntl`-locked registry (8 distinct ports observed), so nothing collided with the other pipelines on the host.
- Sweep window: **2026-10-01T13:52:55Z → 13:55:10Z** (134.2s per round, all 8 concurrent).
- **Result: `73/73 passed, 0 failed, 0 errors, 0 skipped` in every one of the 8 rounds** (`results.1.json` … `results.8.json`, all `passed == total == 73`). "ALL ROUNDS GREEN".
- Implementation source untouched by the sweep: newest non-`__pycache__` file `routes/finance.py` at epoch 1790860047, sweep end epoch 1790862910.

### Final artifact inventory

| Artifact | Size |
|---|---|
| `SCAFFOLD.yaml` | 102,045 B (2,125 lines; 12 entities, 6 state machines, 8 calculations, 29 validations, 42 endpoints, 29 errors, 6 roles) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 116,173 B (9 rules, 18 non-stub instances) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 193,762 B (9 sections, 55 non-stub + 16 excluded instances) |
| `worklog.md` | 39,090 B |
| `workspace/INSTRUCTION.md` | 1,424 B |
| `workspace/PRD.md` | 82,864 B (387 lines) |
| `workspace/PRD_FINALIZED.md` | 85,271 B (388 lines) |
| `workspace/PRD_COMPLETED.md` | 89,431 B (388 lines) |
| `workspace/implementation/` | 27 source files, 2,758 lines + `start.sh` + `requirements.txt` + 8 results files |
| `test_helpers/` | 9 modules |
| `test_suite/` | `conftest.py` + 10 test modules, 73 tests |

**Pipeline complete.** 73 tests, all tagged to a design-index instance, all passing in 8/8 rounds under per-test-server isolation.

### Retrospective notes for future runs of this pipeline

1. **Output cap is the dominant failure mode.** Three separate subagents died on the 32,000-token single-response limit having written *nothing*. The prompt pattern that fixed it: (a) one file per subagent where feasible, (b) first message must Write a skeleton ending in a sentinel, (c) one rule/section/file-chunk appended per message in payloads under ~150 lines, (d) an explicit ban on restating content in prose.
2. **Verify every hand-back against disk.** Two claims needed correction in practice: a subagent reported a file at one line count while the on-disk count differed mid-edit, and the route-parity check had to be done with `<param>`/`{param}` normalization to avoid a fake mismatch list. Route parity was exact (42/42) — but that was confirmed, not assumed.
3. **The Step 5/6 read ban matters more than concurrency here.** Because the endpoint constraint forced sequential launch, the physical isolation that concurrency normally provides was gone; the explicit written ban on reading `SCAFFOLD_*_DESIGN.yaml`, `test_suite/`, and `test_helpers/` is what kept impl-gen honest. The impl independently resolved 12 PRD ambiguities, none of which lined up suspiciously with test literals.
4. **Test-side fixes dominated Step 7** (4 helper fixes + 4 suite fixes vs 1 impl fix), which is the signal that a scaffold rule was under-specified in PRD rather than that the impl was wrong. Those sites were named explicitly in the Step 8 hand-off as the focus list, and Step 9 then swept the residual silences (35 edits, 19 of them ambiguity-pins) that no test had ever asserted.
