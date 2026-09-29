# Worklog — task_2800_preschool_special_education_child_find_evaluation

## Step 1: Create task directory — 2026-09-04T23:34:11.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2800_preschool_special_education_child_find_evaluation` and its `workspace/` subdirectory. Index 2800 was pre-assigned by the orchestrating invocation (no scan of ./tasks/ performed, per instruction, to avoid collision with the other concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T01:00:30.000Z

Subagent summary (verbatim):

All three artifacts are complete and the lint is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     11
  §1.8 instances scanned:     26
  §1.9 instances scanned:     47
  Calls scanned (§1.8+§1.9):  1345

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2968 | 169 KB |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3006 | 198 KB |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4770 | 298 KB |

`SCAFFOLD.yaml` top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key is present; the two design files each hold their single top-level key.

## Counts

- **Seed tables (§1.0–§1.7):** 11 entities, 9 state-machine blocks, 3 concurrency rules, 13 calculations, 38 validations, 49 endpoints, 54 errors, 6 roles.
- **§1.8 difficulty design:** 9 rules, 26 instances.
- **§1.9 corner design:** 9 sections, 74 instances = 47 with `test_recipe` + 27 `excluded_because` stubs (entities 11/0, state_machines 9/6, calculations 4/9, validations 11/5, endpoints 3/4, errors 1/0, rbac 4/1, cross_cutting_complexity_layers 3/2, consistency_model 1/0).
- **Verification:** all 54 declared error ids are triggered somewhere in §1.8 ∪ §1.9 (0 uncovered); every stub's cited `difficulty_instance` resolves to a real §1.8 instance name; instance names unique across the union of both files.

## Design summary

`domain_name: preschool-child-find`, `api_prefix: /child-find`, expert difficulty, `compliance_audit` × `quota_allocation`, graph topology, parallel state machines, `segregation_of_duties` roles, `immediate` consistency. Layers: `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `selector_policy`.

Two hard cores share one entity graph. **Statutory compliance:** consent-anchored 60-day evaluation deadlines capped by the third-birthday Part C transition deadline, interpreter/language-access gating on every parent notice, chair-vs-evaluator segregation, 90-day kindergarten conference lead time. **Finite capacity:** screening slots bounded by `min(slot_capacity, floor(window/slot_length))`, IEP seats per community site, and two orthogonal Provider dimensions (weekly service minutes with a per-line `ceil5` rounding plus a tiered travel overhead charged only on sites beyond the first, and evaluation caseload). `Referral` carries two independent dimensions (`intake_status` × `consent_status`); `EvaluationCase` and `ServiceLine` cycle; `ServicePlan` branches on service setting with divergent side effects. Roles: DistrictAdmin, ChildFindCoordinator, EvaluationChair, Evaluator, PlacementAdministrator, Parent.

§1.8 probes depth: dual-variant due dates and projected-vs-committed minutes, rounding-order traps (`ceil5` per line before summing; travel tier selected from direct minutes before overhead), parallel-dimension divergence, revision cycles that terminate, five-level consent-revocation and kindergarten-exit cascades, error-priority contests, and boundary cases (33-vs-32 months, exactly 25% delay, exactly-at-cap minutes). §1.9 probes breadth: CRUD read-backs, pagination `meta.total_count`/`has_more`, per-entity not-found ids, enum/increment rejection, FK existence, validation priority chains, RBAC denial (unauthenticated, unrecognised role, non-guardian parent, non-assigned evaluator, non-chair provider), one OCC instance per concurrency rule (each capturing v1, bumping, replaying for a 412, re-reading and succeeding), and a single-request cascade-visibility proof for the immediate consistency model.

## One disclosure

The scenario's leading directive line, "Generate task harder than expert level!", was deliberately **not** copied into `scenario:` — that line otherwise propagates through `SCAFFOLD.yaml`'s `scenario` key into `PRD.md` and leaks the meta-instruction to the model under test. The intent is encoded structurally instead: `complexity_profile.difficulty_level: expert` plus deliberately over-guideline counts (49 endpoints, 54 errors, 38 validations, four complexity layers, dual parallel state dimensions). The domain sentence itself is otherwise verbatim.

Orchestrator verification: `grep -rn "harder than expert"` across the task dir returns nothing — the difficulty directive did not leak into any scaffold artifact.

## Step 3: Copy shared files — 2026-09-05T01:01:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T01:22:00.000Z

Subagent summary (verbatim):

§4 and §5 are appended and the PRD is complete. All three Hard Contracts verified mechanically (scripted diffs against `SCAFFOLD.yaml`, two passes for Contract 1).

**Output:** `workspace/PRD.md` — **448 lines, 109,125 bytes**

Structure: §1 Introduction; §2 with ten domain-derived subsections (2.1 RBAC, 2.2 fixed response envelope, 2.3 pagination, 2.4 identity/clock, 2.5 nested paths + the full 38-rung ordered refusal ladder, 2.6 OCC, 2.7 language access, 2.8 arithmetic/calendar, 2.9 cascades/compensating recomputation, 2.10 pinned rules and reported alternatives); §3 with nine freely-grouped workflow subsections; §4 the 49-row endpoint table; §5 the 54-row error catalogue. §2.2 is byte-identical to `section-2.2-response-structure.md` (verified by substring match). No audit footer, no contract report, no forbidden design file was opened.

```
Field coverage check:
- entities[].fields: 131 required, 131 present, 0 missing
- endpoints[].input (request_body + query params; this scaffold declares both in one `input` list): 86 distinct identifiers required, 86 present, 0 missing
- endpoints[].path_params: only `{id}`, present
- concurrency_rules[].occ_field: 3 required, 3 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed in prose as a single ordered 1-38 ladder in §2.5, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write endpoint + expected_screening_event_version / expected_evaluation_case_version / expected_provider_version + 412 error_id all named), 0 missing
- state_machines[].transitions: 53 checked, 53 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed in prose (constants rendered as words/decimals, no operator syntax), 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 24 endpoints with side effects (80 items) + 38 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 131 checked, 131 reconstructible from prose (all 103 enum values present verbatim), 0 missing
- sibling-branch symmetry: 21 groups checked, 21 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1090 (323 unique)
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: all 54 error IDs appear in §5 with HTTP statuses matching the scaffold exactly, and every one is also triggered in §2/§3 prose; all 49 endpoints and their role lists match the scaffold set-for-set; the §4 intro's 201-vs-200 rule matches the scaffold's 12 `code: 201` endpoints exactly; zero fuzzy hedging words and zero pseudocode operators outside the §2.2 JSON fence.

One scaffold internal inconsistency resolved during drafting: `Provider.active_evaluation_count`'s field description says cases the provider "chairs or assesses in", while `calculations.provider_evaluation_caseload` counts only `chair_provider_id` matches. I treated the calculation as authoritative (chair-based) and phrased the evaluator-side triggers as merely recomputing the rollup.

The file ends at a real section boundary — the final row of the §5 error table.

Orchestrator verification (guarding against the known silent-truncation failure): `wc -l` = 448; `tail -14` ends on a complete `| \`ERR_PROVIDER_CASELOAD_EXCEEDED\` | 422 |` table row; all five top-level sections (§1 Introduction L3, §2 Global Specifications L11, §3 Business Logic L175, §4 Endpoint Definitions L333, §5 Error Code Catalogue L389) are present. Not truncated — no regeneration needed. `grep -c "harder than expert"` = 0, so the difficulty directive did not reach PRD.md.

## Step 5: Generate unit tests — 2026-09-05T02:38:00.000Z

Subagent summary (verbatim):

Stage 2 is complete and audited. All eleven test files plus the nine helper modules sit at the task root, and every audit gate passes.

## Files

**`test_helpers/`** (Stage 1 infrastructure, 2,722 lines)
`__init__.py` 41 · `api_client.py` 315 · `api_errors.py` 142 · `assertions.py` 486 · `constants.py` 236 · `factories.py` 331 · `fixtures.py` 607 · `test_users.py` 82 · `types.py` 482

**`test_suite/`** (8,040 lines)
`conftest.py` 67 · `test_01_entity_shapes_and_defaults.py` 1002 · `test_02_state_machines.py` 667 · `test_03_calculation_views.py` 314 · `test_04_validation_ladder.py` 1036 · `test_05_endpoints_rbac_and_concurrency.py` 1317 · `test_06_dual_variant_and_formula_order.py` 711 · `test_07_non_linear_state_machine.py` 505 · `test_08_cascades_and_priority_conflicts.py` 595 · `test_09_boundary_precision.py` 473 · `test_10_cross_entity_and_temporal_overlap.py` 866 · `test_11_compensating_invariants.py` 487

Both directories are at the task root — verified nothing landed under `workspace/`.

## Test count

**196 test functions → 216 collected cases** (parametrization). `pytest --collect-only` succeeds with zero collection errors; all 11 modules import cleanly; `pyflakes` reports no undefined names; no duplicate test names within any file.

## Coverage

- **Queue A (difficulty): 26 / 26 instances, all with >=2 tests** (77 tests). Nine rule_ids, per-instance counts 2-3.
- **Queue B (corner): 47 / 47 non-stub instances, all with >=1 test** (119 tests). Counts range 1-6 where an instance names several facets.
- **27 `excluded_because:` stubs were not translated.** Their `difficulty_instance:` cross-references all resolve — they point at rule_ids (all nine exist in the difficulty index) rather than at instance names.

## Skipped instances

**None.** Every instance in both indices survived the PRD-first two-condition filter.

## Audit gates

- Every test docstring ends with exactly **one** `Design:` line; all 196 tags parse, name a real instance, and name the section/rule_id that actually owns it. Zero untagged, dual-tagged or dangling tags.
- No `skip`/`skipif`/`xfail` markers, no placeholders.
- No occurrence of "scaffold", "design index", "difficulty design", ".yaml", or "corner" outside the mandated tag lines; prose cites only PRD sections.
- Every `api.*`, `fx.*`, `f.*`, `constants.*`, `assertions.*` and `ApiErrorId.*` reference resolves against the frozen helpers (0 problems).

## Three findings worth passing to whoever reviews the implementation

1. **The design index contradicts the PRD on one field, and the tests follow the PRD.** The consent-revocation cascade instance expected `Referral.evaluation_due_date == null`, but PRD §3.4 says the pinned date "is retained as the historical deadline rather than cleared". The test asserts retention — the implementation must **not** clear that field.
2. **Three fields are asserted only indirectly because the PRD does not pin their serialisation** (C2 failures at the field level, not the instance level): `travel_tier_pct` (§3.8 says "5 percent" but names a `_pct` field, so `5` vs `0.05` is undecidable), `utilization`, and `pinned_variant`'s enum spelling. Tier selection is instead pinned through `travel_overhead_minutes` and `assigned_weekly_service_minutes`, which are unambiguous.
3. **Nullable optionals are read with `.get(...) is None`** throughout, since the PRD never states whether unset optional fields are omitted or serialised as `null`. An implementation may choose either.

## Step 6: Generate implementation — 2026-09-05T02:14:00.000Z

Subagent summary (verbatim):

The implementation is complete and verified.

## Deliverable

`workspace/implementation/` — 23 files, 3642 lines of Python + Flask, in-memory dicts only, no seeding.

| file | lines |
|---|---|
| `start.sh` (executable) | 8 |
| `requirements.txt` | 1 |
| `app.py` | 71 |
| `db.py` | 104 |
| `errors.py` | 73 |
| `response.py` | 45 |
| `middleware.py` | 54 |
| `validation.py` | 343 |
| `services/calc.py` | 340 |
| `services/derive.py` | 398 |
| `services/rules.py` | 270 |
| `routes/common.py` | 16 |
| `routes/clock.py` | 20 |
| `routes/children.py` | 100 |
| `routes/sites.py` | 83 |
| `routes/providers.py` | 163 |
| `routes/screening.py` | 281 |
| `routes/referrals.py` | 222 |
| `routes/consent.py` | 117 |
| `routes/evaluation.py` | 523 |
| `routes/plans.py` | 410 |

All 39 declared endpoints are implemented across 10 blueprints mounted at `url_prefix="/child-find"`.

## Verification

- `bash start.sh` with `PORT=18973` boots and serves on `0.0.0.0`; guarded `if ! python3 -c "import flask"` install then `exec python3 app.py`. Server was killed by exact PID (never a broad pkill); port confirmed free afterwards.
- Two throwaway smoke suites in `/tmp` both ended at `FAILS: 0`: a full happy path (clock -> child -> referral -> consent grant -> timeline -> 5 providers -> case -> 5 domain assessments + completions -> eligibility profile -> report -> revision round -> determination -> service line -> staffing -> caseload ledger -> service consent -> kindergarten transition -> exit) and a negative-path suite (`ERR_AGE_INELIGIBLE`, `ERR_CONSENT_NOT_GRANTED`, `ERR_INTERPRETER_NOT_PROVIDED`/`_UNAVAILABLE`, guardian 403, `ERR_SEGREGATION_OF_DUTIES`, `ERR_DISCIPLINE_MISMATCH`, all three `ERR_EVALUATOR_WINDOW_CONFLICT` shapes, `ERR_DUPLICATE_DOMAIN_ASSESSMENT`, and the full consent-revocation cascade).
- Fresh boot: all 11 list endpoints return `total_count: 0` with `response_type: "array"`; missing `X-User-ID` -> 401.
- Dual-variant arithmetic confirmed live, e.g. `per_line_rounded_minutes: 120` vs `sum_then_rounded_minutes: 115` side by side, and the provider ledger emitting `utilization` unrounded (`0.043333333333333335`).
- No test-suite or corner-design file was read; `test_suite/`, `test_helpers/`, `SCAFFOLD_*_DESIGN.yaml` and sibling task dirs were never touched. `worklog.md`, `PRD.md` and `SCAFFOLD.yaml` are unmodified (`git status` shows only the new `implementation/` dir).

## Fidelity decisions worth flagging

1. **Referral timeline with no pinned due date** — `days_remaining` and `timeline_compliance` are both `null` when `evaluation_due_date` is absent, tracing to the PRD's "a referral without a granted consent is excluded from every compliance aggregate". `third_birthday_cap_date` is always the child's third birthday regardless of pathway.
2. **`ERR_AGE_INELIGIBLE` is unreachable on the consent-request creation endpoint** — a manual intake outside 33-71 months is refused at rung 17, and a screening-generated one is `DECLINED` at creation, so intake can never be `RECEIVED` with an ineligible pathway. The error catalogue's `applies_to` also restricts that error to referral creation, so `ERR_INVALID_REFERRAL_STATE` is the only reachable refusal there. A code comment records this.
3. **PRD §2.5 rung numbers override §3 paragraph order** where they disagree: rung 20 (site placement eligibility) runs before rung 30 (setting requirements) on consent-submission even though §3.9's prose lists the "at least one STAFFED line" rule first, and rung 24 (conference lead time) runs before rung 32 (transition sequence).
4. **`PENDING -> REVOKED`** is an undeclared ConsentRecord transition and so yields `ERR_INVALID_CONSENT_STATE` at rung 11; `ERR_CONSENT_NOT_REVOCABLE` is reserved for `GRANTED -> REVOKED` on a `SERVICE_CONSENT` at rung 29.
5. Note one non-bug that cost debugging time: `kindergarten_eligibility_date` is September 1 of the fifth-birthday year, so lead-time probes must be dated against that September anchor, not the birthday.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single message, so the implementation generator started before `test_suite/` existed on disk (physical isolation). Verified `test_helpers/` and `test_suite/` are at the task root, not under `workspace/`. Verified the implementation registers 49 route decorators, matching the scaffold's 49 declared endpoints (the summary's "39" is a miscount in the subagent's prose, not a gap in the code).

## Step 7: Run tests and iterate — 2026-09-05T03:07:00.000Z

Subagent summary (verbatim):

Iteration 1 came back clean on all 8 parallel rounds. No fixes were required.

## Summary

**Iterations run:** 1 (single 8-round parallel stability sweep; no further iterations needed)

**Sweep result:** 216/216 passed in every one of the 8 concurrent rounds — `failed 0, errors 0, skipped 0` in all of `results.1.json` … `results.8.json` (each round ~408 s wall time). Union of failing tests across all 8 rounds: **empty**. No flakiness signal: not one test failed in any round.

**Tests deleted:** none. No test entered the diagnostic protocol, so no STEP 1a/1b silence or collapse pattern was ever adjudicated.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `workspace/implementation/`:** none.

**Zero files were modified** anywhere in the task directory — no edits to `test_suite/`, `test_helpers/`, `workspace/implementation/`, and (per instruction) nothing appended to `worklog.md`.

### Verification notes from the pre-diagnosis audit
Since results arrived clean, the reading I did while the sweep ran serves as a compliance check rather than a diagnosis:

- **No-seed / in-memory-only rule is satisfied.** `workspace/implementation/db.py` is a plain `Store` over 11 Python dicts with no seeding, no SQLite, no on-disk dump, no `/tmp` cache.
- **Both known false-signal sources were checked and do not apply.** `test_helpers/factories.py` emits every numeric field as a JSON number (not a money-as-string bug), and `test_helpers/constants.py::utc()` tolerates any sub-second width, so the ISO-8601 precision trap is neutralised on the assertion side even though `api_client.py` does no canonicalisation of its own.
- `workspace/PRD.md` (448 lines) is complete, ending at a real section boundary (the Error Code Catalogue) — not truncated.
- I did not read `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, or `SCAFFOLD_CORNER_DESIGN.yaml` at any point.

One process-level note worth passing along: the `setsid nohup` wrapper returns exit 0 within about a minute because `setsid` forks and detaches, while the sweep itself keeps running for ~7 more minutes. I confirmed via `pgrep` that the wrapper, all 8 runners, and all 8 pytest subprocesses were alive, and polled for the 8 `results.$i.json` files rather than re-launching — re-launching would have doubled host load and corrupted the round data.

Sweep artifacts left in place for inspection: `workspace/implementation/results.1.json` … `results.8.json`.

**Orchestrator independent verification** (the known failure mode is a Step 7 subagent claiming a clean sweep with no artifacts on disk, so this was re-checked rather than trusted): all eight `workspace/implementation/results.{1..8}.json` exist (~67.8 KB each, all written 02:21) and each parses to `passed=216 total=216 failed=0 errors=0 skipped=0`. The 216 total matches Step 5's reported 216 collected cases exactly, independently confirming zero test deletions.

## Step 8: Finalize PRD — 2026-09-05T03:08:00.000Z

**SKIPPED**, per the skill's skip condition. Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior Step 7 exercised, and there is no `<step_7_diff>` to hand off; spawning the finalizer would produce either a byte-identical file or out-of-scope edits. No subagent spawned, no `PRD_FINALIZED.md` written. Step 9 consequently reads `workspace/PRD.md` as its source.

## Step 9: Complete PRD — 2026-09-05T03:37:00.000Z

Source: `workspace/PRD.md` (448 lines, 109,125 chars) — Step 8 was skipped, so no `PRD_FINALIZED.md` existed.
Output: `workspace/PRD_COMPLETED.md` — **455 lines, 132,815 chars (+7 lines, +23,690 chars)**.

Orchestrator decision: Step 9 was run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` rather than one monolithic subagent. Rationale: the implementation is 3,642 lines across 23 files and the PRD is 109 KB; a single agent asked to walk all of it exhaustively runs out of working context and degenerates into a `cp` with no real scan (the failure signature being a `PRD_COMPLETED.md` byte-identical to its source). Partitioning by implementation module keeps each pass's read set bounded while still covering every file exactly once. Pass 1 performed the initial `cp`; passes 2 and 3 were explicitly forbidden from copying, so as not to destroy earlier passes' edits.

Partition (disjoint, union = all 23 implementation files):
- **Pass 1** — app.py, db.py, errors.py, response.py, middleware.py, validation.py, routes/{common,clock,children,sites}.py → 18 ambiguity-pins, 1 mismatch-revision (+7 lines, +8,981 chars).
- **Pass 2** — services/{calc,derive,rules}.py (provider + screening + formula scope), routes/{providers,screening}.py → 12 ambiguity-pins, 2 mismatch-revisions (+4,969 chars).
- **Pass 3** — routes/{referrals,consent,evaluation,plans}.py plus the referral/consent/case/plan helpers in services/{rules,derive}.py → 26 ambiguity-pins, 3 mismatch-revisions (+9,740 chars).

**Totals: 56 ambiguity-pins, 6 mismatch-revisions (62 changes).**

Notable mismatch-revisions (PRD described behavior the implementation does not exhibit):
1. §5 error catalogue claimed exhaustiveness but omitted `ERR_NOT_FOUND` (404), the only identifier in `errors.py` absent from the entire PRD — row added.
2. §3.1 provider registration validated `status` last, not before the three ceilings as the prose order implied.
3. §3.1 a ceiling registered as 0 makes its dimension read `AT_CAPACITY` from the first read; the PRD claimed both postures start `OPEN`.
4. §2.9 the cascade's last two hops (provider rollup, child `status`) are read-time re-derivations that bump neither `version` nor `updated_at`; the PRD implied they were stored writes.
5. §3.4 the `AGE_INELIGIBLE` pathway rule is unreachable — such a referral reports `ERR_INVALID_REFERRAL_STATE` (matches the Step 6 fidelity note).
6. §3.8 `delivery_site_id` is not restricted to absent for non-`COMMUNITY_PRESCHOOL` settings; it need only exist, and defaults to the plan's own site.

Recurring ambiguity themes pinned: derived-on-read vs stored fields (and the consequent `version` behavior), refusal-ordering where §2.5 rung numbers disagree with §3 paragraph order, optional-field defaults and string length ceilings, list-field dedup/empty-array semantics, which response bodies are returned by action endpoints (e.g. determination returns the new `ServicePlan`, service submission returns the new `ConsentRecord`), uncapped-vs-pinned due-date reporting, numeric typing (integers for minutes, fractions for `travel_tier_pct`, unrounded `utilization`), and the logical-clock-vs-wall-clock split for audit timestamps.

Orchestrator verification: `PRD_COMPLETED.md` is 455 lines, retains all five top-level sections, ends on a complete final error-table row (`| ERR_PROVIDER_CASELOAD_EXCEEDED | 422 |`) rather than mid-sentence, and is **not** byte-identical to `PRD.md` (`cmp` differs) — confirming the scan actually ran. `find` over `implementation/`, `test_suite/`, `test_helpers/` shows no `.py` modified after the 02:21 passing sweep, so the verified 216/216 × 8-round result still describes the shipped code exactly.

Pipeline complete.
