# Worklog — task_2970_public_land_grazing_permit_administration

## Step 1: Create task directory — 2026-09-05T23:21:42.836857085Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2970_public_land_grazing_permit_administration and its workspace/ subdirectory. Index 2970 was pre-assigned by the orchestrator prompt; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-06T01:39:36Z

All three scaffold artifacts are complete and the lint is clean.

Verdict block, verbatim from `python3 /home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/scaffold_lint.py /home/ubuntu/github/CodingPRD/tasks/task_2970_public_land_grazing_permit_administration`:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     14
  §1.8 instances scanned:     21
  §1.9 instances scanned:     77
  Calls scanned (§1.8+§1.9):  1022

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Worklog-ready summary

Scope covered (SCAFFOLD.yaml, §1.0–§1.7): 14 entities (Allotment, Pasture, Permittee, BaseProperty, GrazingPermit, AnnualOperatingInstruction, PastureUseRecord, GrazingBill, RangelandHealthAssessment, PermitDecision, AppealCase, ClosureOrder, TrespassIncident, RangeImprovementProject), 11 state machines, 14 calculations (AUM allocation ledger + conservation invariant, base-property qualification, use-record/actual-use aggregation, dual-variant use billing, unauthorized-use charge with willfulness × repeat factors, waterfall cost-share allocation, money-conservation invariant, outstanding balance, emergency-reduction reallocation, health determination, dual-variant stocking recommendation, consecutive non-use), 33 priority-ordered validations, 65 endpoints, 53 errors, 5 roles (Permittee, RangeSpecialist, AuthorizedOfficer, AppealsAdjudicator, SystemAdmin), 1 OCC rule on `Allotment.version`.

§1.8 (SCAFFOLD_DIFFICULTY_DESIGN.yaml): 9 rule_ids — dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant — with 21 instances.

§1.9 (SCAFFOLD_CORNER_DESIGN.yaml): 9 sections, 104 instances (entities 12, state_machines 19, calculations 16, validations 29, endpoints 7, errors 3, rbac 9, cross_cutting_complexity_layers 8, consistency_model 1). 125 instance names across §1.8+§1.9, no duplicates; every `excluded_because` stub cites a real §1.8 instance and carries no `test_recipe`.

Line counts: SCAFFOLD.yaml 3215, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1985, SCAFFOLD_CORNER_DESIGN.yaml 5267. All three `yaml.safe_load` cleanly; SCAFFOLD.yaml contains neither design key; each design file has exactly one top-level key.

Changes made in this final pass to reach clean lint:
- Added 5 §1.5 read endpoints to give three FKs reverse reachability (`Pasture.allotment_id`, `BaseProperty.permittee_id`, `ClosureOrder.allotment_id`): `GET /pastures/{pastureId}`, `GET /pastures` [allotment_id?, rest_required?, limit?, offset?], `GET /base-properties/{basePropertyId}`, `GET /base-properties` [permittee_id?, base_property_type?, limit?, offset?], `GET /closure-orders` [allotment_id?, order_status?, order_type?, limit?, offset?]. Endpoint count 60 -> 65.
- Renamed 7 §1.9 negative-test instances so the linter's negative-trigger regex recognises them (it does not match `_refused_`): the four role-exclusivity instances, the SystemAdmin clock instance, the segregation-of-duties instance, and the envelope-shape instance (now `..._on_invalid_payload`). No cross-reference breakage.
- Added 2 new §1.9 `endpoints` instances (`corner_pasture_and_base_property_reverse_paths_and_filters`, `corner_global_registries_list_across_allotments_with_conjunctive_filters`) so all 11 previously unexercised list/get endpoints are covered; endpoint coverage is now 65/65 with 0 uncovered.
- Fixed the `GET /pastures/{pastureId}` description to name the real field `scheduled_aums`.
- `worklog.md` and `workspace/` untouched; `.scratch/step2/` removed after use.

Orchestrator verification: all three files present, 3215 / 1985 / 5267 lines. Grep for the difficulty directive phrasing ("harder than", "expert level") across all three YAMLs returned zero hits, so the Step 2 difficulty instruction did not leak into the scaffold prose. SCAFFOLD.yaml does carry the structured metadata key `complexity_profile.difficulty_level: expert_plus`; that is a scaffold-spec field, not the directive sentence, and PRD.md will be checked after Step 4 for any difficulty wording.

## Step 3: Copy shared files — 2026-09-06T01:39:42Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T01:59:17Z

PRD.md is complete.

**Deliverable:** `workspace/PRD.md` — **490 lines, 125,137 bytes**, built by one small `Write` plus 12 append-only heredocs, each verified with `wc -l`/`tail`.

**Top-level sections in order:**
1. `# Public Land Grazing Permit Administration API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 Actors/Identity Headers/RBAC · 2.2 API Response Structure (byte-identical to the fixed source, fences intact) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Timestamps and Record Versioning · 2.5 The Logical Range Calendar · 2.6 Path Resolution and the Order in Which a Request Is Rejected · 2.7 Optimistic Concurrency on Allotment Writes · 2.8 AUM Arithmetic, Rounding and Money Precision · 2.9 The Allotment Capacity Ledger and Its Conservation Invariants · 2.10 Segregation of Duties · 2.11 Cascade Discipline: Snapshots, Supersession and Restoration (11 subsections)
4. `## 3. Business Logic & Workflows` — 3.1 Allotment Inventory/Pastures/Season of Use · 3.2 Permittee Standing, Base Property, Preference Qualification · 3.3 Term Permit Lifecycle · 3.4 The Grazing Year (AOI drafting/scheduling/issuance) · 3.5 Non-Use, Actual Use, Final Settlement · 3.6 Grazing Bills · 3.7 Rangeland Health Monitoring · 3.8 Permit Decisions · 3.9 Administrative Appeals · 3.10 Closure Orders and the Reallocation Cascade · 3.11 Trespass and Unauthorized-Use Billing · 3.12 Range Improvement Projects and Cost-Share Allocation (12 subsections)
5. `## 4. Endpoint Definitions` — intro paragraph + 4-column table (Method, Path, Description, Authorized Role(s))
6. `## 5. Error Code Catalogue` — intro paragraph + 2-column table (Error ID, HTTP Status Code)

**SCAFFOLD coverage (mechanically verified):** 14/14 entities · 11/11 state machines (every transition, including the AppealCase `REMANDED → UNDER_REVIEW` and TrespassIncident `BILLED → DETECTED` cycles, the RangelandHealthAssessment `FIELD_REVIEW` fork, and the `STAYED`/`VACATED` decision branches) · 14/14 calculations · 33/33 validations (numbered 1–33 in §2.6 with error id, HTTP status and applies_to scope) · 65/65 endpoints (table row count = 65, verified against a parse of §1.5) · 53/53 error ids (table row count = 53; every one also appears in the prose of §§1–4 — the only scaffold `ERR_*` strings absent are `ERR_NO_ELIGIBLE_PERMITS`, which the scaffold declares deliberately nonexistent, and the placeholder `ERR_XXX`) · 5/5 roles · 1/1 concurrency rule (`expected_allotment_version` → `ERR_STALE_ALLOTMENT_VERSION` 412).

**Hard Contract checks:**
- **Contract 1 (Field-Name Coverage) — PASS.** All 149 entity-field and request-body/query-param identifiers appear verbatim in backticks; all 16 real path params appear inside backticked paths. The only unmatched scaffold `name:` tokens are the five internal calculation-variant labels (`PRELIMINARY`/`FINAL`/`REVISED`, `PROPORTIONAL_STANDARDS`/`UTILIZATION_BASED`), which are not API identifiers — all five variants' behavior is specified in §3.6 and §3.7.
- **Contract 2 (Rule Coverage) — PASS.** Includes base-amount-driven (not total-driven) admin fee tiers, supersede-if-unpaid vs adjust-if-partly-paid, max-not-sum reduction combination, snapshot-based non-compounding re-authorization, single-pass 5-hop cascade with no feedback, `pre_decision_adjustment_pct` snapshot taken *before* application, the `permitted_aums` DESC / `created_at` ASC remainder ranking with `id` never a tie-break, empty-cost-share-pool-as-success, `NON_WILLFUL` yielding zero penalty via the multiplier-minus-1.0 form, and the disjoint CONCUR/REMAND side-effect sets.
- **Contract 3 (§3 Path Purity) — PASS.** 1,266 backticked tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combinations (§2 is clean on the same scan too).

**Tail:** the file ends with `| \`ERR_OVERPAYMENT\` | 422 |`, the last row of the §5 table — a complete final section, not a truncation.

**Hygiene:** no forbidden meta-vocabulary remains (one domain-sense use of "difficulty" in §1 was reworded to "challenge"); the two design-index YAMLs were never opened; `.scratch/step4/` was created and removed without touching its parent; `worklog.md` untouched; no `test_helpers/`, `test_suite/` or `implementation/` created — `workspace/` holds only the pre-existing `INSTRUCTION.md` and the new `PRD.md`.

**Three scaffold contradictions resolved and stated explicitly in the PRD** (flagging for the orchestrator): list envelope (§2.2 fixed contract wins over the §1.5 header comment's `{items,total_count,has_more}`); `authorized_aums_at_issue` stamped at creation *and* re-stamped identically at issuance; AOI voidable from `DRAFT`/`ISSUED`/`USE_REPORTED` per the endpoint description, with `ERR_AOI_STATE_INVALID` from `BILLED`/`CLOSED`/`VOIDED`. Two scaffold gaps were closed by assignment: the use record's `livestock_kind`-must-match-permit rule → `ERR_VALIDATION`; the AOI `planned_aums_total <= authorized_aums` issuance precondition → priority 8, `ERR_AOI_STATE_INVALID`.

Orchestrator verification (truncation guard): `wc -l -c` gives 490 lines / 125,137 bytes; `tail -25` ends on the complete final row of the §5 error table, a genuine section boundary rather than a mid-sentence cut, so no regeneration was needed. A case-insensitive grep for `expert|scaffold|benchmark|harder than|expert_plus` over PRD.md returned zero hits — the Step 2 difficulty directive and the `complexity_profile.difficulty_level: expert_plus` metadata key did not leak into the contract.

## Step 6: Generate implementation — 2026-09-06T02:49:24Z

All 53 catalogued error ids are mapped (plus three transport-level ids). Implementation is complete and smoke-verified.

## Step 6 complete — Flask implementation generated

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2970_public_land_grazing_permit_administration/workspace/implementation/`

### Module layout (3,751 lines of Python across 19 modules)
| file | lines | role |
|---|---|---|
`app.py` | 85 | app factory, blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers, WSGI-level `store.LOCK` serialization, `app.run(host="0.0.0.0", port=$PORT, threaded=True, debug=False, use_reloader=False)` |
`start.sh` | 10 | `set -euo pipefail`, guarded pip install, `exec python3 app.py` (foreground) |
`errors.py` | 74 | 53 PRD error ids → HTTP status + 3 transport ids (`ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`, `ERR_INTERNAL`) |
`constants.py` | 95 | every §2.7 numeric constant and enum vocabulary |
`store.py` | 156 | in-memory dicts (14 collections, empty at boot), RLock, logical clock (epoch `2026-08-01T00:00:00Z`), strictly-increasing ms `created_at`/`updated_at`, `version` |
`envelope.py` | 108 | `meta`/`response_type`/`data` envelope, `req_`+20 char id, pagination (limit 10/1–100, offset >= 0, `has_more`) |
`validate.py` | 176 | priority-1 shape checks (9 field kinds) in declared order + priority-2 date-range coherence |
`auth.py` | 70 | priority-3 role/identity, permittee row scoping, priority-4 segregation |
`calc.py` | 210 | 16 Decimal/ROUND_HALF_UP calculators (AUM forage, qualified AUMs, capacity floor, use-bill money + admin tiers, final billed AUMs, trespass money, composite score, recommended reduction, pro-rata shares) |
`derive.py` | 430 | live aggregates (allotment ledger, permittee balance/status, pasture scheduled AUMs, AOI totals) + all 14 serializers |
`services.py` | 333 | bill supersede/adjust discipline, 5-hop reallocation cascade (single pass, snapshot-based), decision effect/vacatur cascades, non-use run, account-status refresh |
`find.py` / `gates.py` | 72 / 71 | priority 5–6 FK resolution (14 entity 404 codes), filters; priorities 9,10,16,25,28,30 gates |
`routes_land.py` … `routes_ops.py` | 215/234/351/123/173/344/431 | allotments+pastures+permittees+base properties / permits / AOIs+use records / bills / assessments / decisions+appeals / closure orders+trespass+projects+clock |

### Coverage
- **65 endpoints** — programmatically diffed against the PRD §4 table: zero missing, zero extra.
- **53 error ids**, all mapped to their catalogued HTTP status; **33 validation priorities** honoured as short-circuit ordering.
- **10 state machines** (permit, AOI, use record, bill, assessment, decision, appeal, closure order, trespass incident, project) plus the permit `account_status` axis.
- Optimistic concurrency: `expected_allotment_version` → `ERR_STALE_ALLOTMENT_VERSION` 412 at priority 7, before every state/business rule.
- Concurrency: one WSGI-level `RLock` around each request, so the threaded server never interleaves mutations; storage is pure in-memory dicts — no file, DB, or cache, and nothing is ever seeded.

### Clean-boot smoke test
`bash start.sh` on `PORT=20643` (pid 306963): 47 scripted calls covering allotment→pasture→permittee→base property→permit issue→AOI→use records→AOI issue→bill payment→assessment submit/review→decision author (incl. a deliberate 412)→env review→finalize→make-effective→appeal file/docket/REVERSE→closure order (incl. a deliberate 409 buffer overlap)→lift→trespass bill→project approve/allocate→clock advance (incl. a deliberate 422)→404/403 checks. **0 failures.** Spot-checked figures: preliminary bill 17,200 cents for 100 AUMs; 0.30 decision → `RESTRICTED`, capacity 1,400, AOI re-authorised 100→70 from its snapshot with an `ADJUSTMENT_CREDIT` of -5,160 cents; drought 0.40 → -6,880 cents (max, not sum); lift → delta 0, no bill; trespass 12.4 → 13 billed AUMs, 60,840 cents total; project share 250,000 cents allocated exactly.

Then two literal `curl` calls (list + a 404 envelope showing `ERR_ALLOTMENT_NOT_FOUND`), `kill 306963`. A second fresh boot on `PORT=26344` (pid 309579) returned an empty `/allotments` list with `total_count: 0` and a clock back at the epoch, proving `start.sh` re-invocation wipes all state; `kill 309579`. Both servers killed by exact PID — no `pkill` was ever run. Scratch removed with `rm -rf .scratch/step6` only; sibling `step5`/`step7` dirs, `worklog.md`, `PRD.md` and all `SCAFFOLD*.yaml` untouched, and `test_helpers/`/`test_suite/` were never read.

## Step 5: Generate unit tests — 2026-09-06T04:15:41Z

Step 5 complete. Everything is at the task root, nothing under `workspace/`.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2970_public_land_grazing_permit_administration/`

**test_helpers/** (1,793 lines): `__init__.py` 28, `api_client.py` 233, `api_errors.py` 118, `assertions.py` 267, `constants.py` 150, `factories.py` 269, `fixtures.py` 409, `test_users.py` 58, `types.py` 261

**test_suite/** (8,261 lines): `conftest.py` 50, `test_01_dual_variant_calc.py` 181, `test_02_combinatorial_formula.py` 295, `test_03_non_linear_state_machine.py` 161, `test_04_transitive_cascade.py` 260, `test_05_priority_pair_validation_conflict.py` 201, `test_06_boundary_precision_check.py` 383, `test_07_cross_entity_state_dependency.py` 375, `test_08_resource_temporal_overlap.py` 251, `test_09_compensating_invariant.py` 287, `test_10_entities.py` 604, `test_11_state_machines.py` 626, `test_12_calculations.py` 634, `test_13_validations.py` 1192, `test_14_endpoints.py` 759, `test_15_errors.py` 292, `test_16_rbac.py` 785, `test_17_cross_cutting.py` 372, `test_18_consistency_model.py` 161, `test_99_clock_dependent.py` 392

Total 10,054 lines.

## Queue A (difficulty, §1.8) — 20 of 21 translated, 47 test functions

Some instances carry several named cases in one recipe and are translated as 2-3 sibling tests (all tagged to that instance); every instance is represented.

**Skipped (1):** `stocking_recommendation_variant_divergence` — the asserted divergence is not PRD-derivable. Its scores 62/44/51 give a composite of 52.95, i.e. `MEETING_WITH_PROBLEMS`, and PRD §3.7 states `recommended_reduction_pct` "is 0 whenever the `determination` is anything other than `NOT_MEETING`", so both variants must read 0.0 rather than 0.2000/0.3590; the instance's `monitoring_method` literals (`PROPORTIONAL_STANDARDS`/`UTILIZATION_BASED`) are also not PRD enum members (`INDICATOR_ASSESSMENT`/`UTILIZATION_MAPPING`).

## Queue B (corner, §1.9) — all 77 non-stub instances translated, 77 test functions

The 27 instances carrying `excluded_because` (including the five in `cross_cutting_complexity_layers`) are yaml stubs and were correctly not translated.

**Repairs made to make instances PRD-legal (disclosed, not weakened):**
- Supplied a real `permit_id` on the ISSUANCE decisions in the test_16 SoD test and both test_17 OCC tests — PRD 3.8 requires non-null `permit_id` on every non-STOCKING_ADJUSTMENT decision, so the yaml's null would trip priority-1 ERR_VALIDATION before the priority-7 OCC check under test.
- The clock/role instance moved into `test_99_clock_dependent.py` with 2027-02-01 / 2027-01-31T23:59:59Z targets and a `current_grazing_year == 2027` control, replacing the yaml's `created_at`-on-2026-08-15 control (§2.4 never ties `created_at` to the logical clock, and its 2026-08-15 targets sit behind the suite's clock).
- Global `total_count` assertions adapted to id-scoped / membership-scoped ones (test_14, test_16, test_17) — the database is shared across the run.
- Dropped sub-probes that were not uniquely derived: the `u_ghost_1` unregistered-officer 403 (PRD 2.1 makes non-Permittee ids opaque) and the 1-cent overpayment on an already-PAID bill; `assessment_id` fixture references repaired; the transfer instance's ISSUED-successor repaired and its `preference_priority` assertion omitted.

## Verification

- 124 test functions; the citation/tag auditor reports `tests audited: 124 / PROBLEMS: 0` — every test's docstring ends in exactly one `Design:` line, every tag resolves to a real yaml `- name:`, no untagged or dual-tagged test, and every `PRD x.y: "…"` citation is verbatim against `workspace/PRD.md`.
- `python3 -m py_compile test_helpers/*.py test_suite/*.py` → clean; pyflakes clean apart from the intentional barrel re-exports in `test_helpers/__init__.py`.
- `ls -d workspace/test_*` → "No such file or directory".
- No server started, no pytest run, nothing under `workspace/implementation/` touched, `worklog.md`/`PRD.md`/`SCAFFOLD*.yaml` untouched.
- Cleanup: `rm -rf .scratch/step5` only; `.scratch/step7` left intact.

Note for Step 7: all clock-advancing tests are confined to `test_99_clock_dependent.py` with monotonically increasing targets (2026-09-01 → … → 2027-02-01); tests in `test_01`–`test_18` assume the default 2026-08-01 clock, which is what makes literals such as `due_date == "2026-08-31"` and `effective_date == "2026-08-01"` correct under alphabetical file ordering.

Orchestrator note appended for Step 7: Step 5's closing remark assumes a database shared across the run and alphabetical-file-ordering clock continuity. That assumption is FALSE under the harness this pipeline uses — `prd-bench-local-run --isolation per-test-server` kills and re-launches the server via `start.sh` before every individual pytest test, so each test starts from an empty store with the logical clock back at its 2026-08-01 epoch. The consequence is benign for the id-scoped/membership-scoped list assertions (they are strictly safer than global `total_count` ones), but any `test_99_clock_dependent.py` test that relies on a *previous* test having advanced the clock will fail; each such test must advance the clock itself from the epoch. Step 7 was told to treat that as a test_helpers/test_suite bug, not an implementation bug.

## Step 7: Run tests and iterate — 2026-09-06T04:37:36Z

Clean. All protected files have pre-session mtimes (worklog.md 04:15, my session began 04:17), no stray directories, and the 8 passing `results.*.json` are in place.

## Summary

**Iterations run:** 2 (baseline sweep found 4 deterministic failures; one batch of fixes; verification sweep green).

**Final sweep numbers:** 124/124 passed in all 8 rounds (rounds 1–8: `124/124`). Zero failures, zero flakiness — the 4 baseline failures were deterministic across all 8 rounds, not load artifacts.

### Tests deleted
None. One assertion was removed under STEP 1c partial-coverage handling (below); no whole test failed STEP 1.

### Fixes applied to `test_suite/`

- **`test_16_rbac.py`** — `test_only_the_affected_permittee_may_file_an_appeal_and_only_in_its_own_name` (renamed to `test_an_appeal_is_filed_by_the_permittee_role_alone_and_only_in_its_own_name`): removed the single sub-assertion that a *bystander* permittee filing an appeal **in its own name** (payload `appellant_permittee_id` == `X-User-ID`) must get `ERR_UNAUTHORIZED`/403. **Unique-derivability collapse (ENUM/RULE-MEMBERSHIP-ONLY + rule-silence).** PRD 3.9 says "filed by the affected `Permittee` alone", but the PRD never defines *affectedness* for a decision, names no error for it, and gives no algorithm — a `STOCKING_ADJUSTMENT`/`ISSUANCE` decision carries only `allotment_id`, no `permit_id`. Worse, the PRD's own gloss operationalizes that phrase as exactly the identity match: "it must equal the acting `X-User-ID` … so the server neither infers the appellant silently nor lets one permittee appeal in another's name", and priority 3 enumerates the Permittee confinement exhaustively as the same match. Two PRD-faithful implementations exist (identity-match only vs. identity-match plus derived affectedness). The covered assertions — name-mismatch → `ERR_UNAUTHORIZED`, role gate beating the segregation code, happy path `FINAL → STAYED`, and the scoped-read rules — were all kept; docstring counts corrected from "four refusals / fifth attempt" to "three / fourth".
- **`test_12_calculations.py`** — `test_planned_aums_multiplies_by_the_livestock_factor_over_half_open_days`: expected pasture `scheduled_aums` corrected from `100.00`/`50.00` to `0.00`/`0.00`. **Test bug (assertion mis-translated PRD).** Both instructions in the test are still `DRAFT`, and PRD 3.1 states verbatim: *"Records belonging to draft or voided instructions, and records for any other grazing year, contribute nothing."* The test read PRD 3.4's "the roll-up is refreshed" as "now equals the leg's planned_aums", but "refreshed" means recomputed under PRD 3.1's definition. The implementation was correct, and this test was the lone outlier — `test_10:483` and `test_13:460-461` already assert `0.00` for draft instructions, while `test_12:463` and `test_17:316` cover the non-zero issued case. Added the two PRD 3.1 quotes to the docstring.
- **`test_99_clock_dependent.py`** — `test_delinquency_spares_the_due_date_itself_and_bites_on_the_following_day`: rebased three date literals onto the fresh-server epoch (`due_date` `2026-12-31` → `2026-08-31`; `set_clock` `2026-12-31` → `2026-08-31`; `set_clock` `2027-01-01` → `2026-09-01`). **Test bug — the known false "clock carries between test files" assumption.** Under `--isolation per-test-server` every test boots at the `2026-08-01T00:00:00Z` epoch, so the bill raised by `_two_dimension_setup()` (which never sets the clock) falls due 2026-08-31. The asserted rule — strict boundary, due date itself not yet delinquent, next day flips all three axes — is fully preserved. Sibling test `test_99:248` legitimately keeps its `2026-12-31` expectation because it advances the clock itself first.

### Fixes applied to `test_helpers/`
None — no fixture, factory, or role-header bug was implicated.

### Fixes applied to `implementation/`

- **`workspace/implementation/routes_permits.py` → `transfer_permit()`**: moved the "source permit must be `ISSUED`" precondition ahead of `gates.closed` / `gates.health` / `owned_by`, and changed it to emit `ERR_PERMIT_STATE_INVALID` (409) via `gates.state(...)` instead of `predecessor_invalid()` (`ERR_PREDECESSOR_PERMIT_INVALID`, 422). PRD 3.3 declares transfer to be the `ISSUED → TRANSFERRED` transition, so a source in any other state is a **priority 8** transition-legality failure; priority 15 restates the same fact but PRD 2.6 makes the ordering normative — *"the checks below are evaluated in ascending order of the numbers given, the first violated check short-circuits the request"*. The lower number wins. Note the renewal path was deliberately left emitting `ERR_PREDECESSOR_PERMIT_INVALID`, because PRD 3.3's renewal narrative explicitly assigns that code to all three preference-chain failures ("all three failures reporting `ERR_PREDECESSOR_PERMIT_INVALID`") and no test exercises renewal on a non-`ISSUED` predecessor.

This is the only implementation change — Step 8's focus list is that one function.

Orchestrator verification of the Step 7 claim (per the "verify the sweep artifacts yourself" rule): all 8 `workspace/implementation/results.*.json` exist with fresh 04:30 mtimes and were re-parsed independently. Each reports `passed == total == 124`, and for each round the count of test entries whose `"status"` key is not `passed` is 0, which reconciles exactly with `total - passed == 0` (guarding against the summarizer bug where keying on `"outcome"` instead of `"status"` prints zero failures beside `passed < total`). The green sweep is real; Step 8 proceeds with the single `routes_permits.py::transfer_permit()` item as its focus list.

## Step 8: Finalize PRD — 2026-09-06T04:45:49Z

Done. `PRD_FINALIZED.md` written with 4 targeted edits.

## Line counts
- `PRD.md`: 490 lines / 125,137 bytes
- `PRD_FINALIZED.md`: 490 lines / 126,599 bytes (0.0% line delta, +1.17% bytes; 4 lines revised in place, no lines added/removed)
- Tail verified intact, ending on `| \`ERR_OVERPAYMENT\` | 422 |`.

## Changes
- **§2.6 priority 8 (Transition legality)** — revise — added that transfer's source permit, being the declared `ISSUED → TRANSFERRED` subject, fails at this priority with `ERR_PERMIT_STATE_INVALID` ahead of the lower-numbered gates, and that renewal is the explicit exception reported at priority 15 — `implementation/routes_permits.py:206-208`
- **§2.6 priority 15 (Preference chain)** — revise — split the clause: the no-successor rule stays on both renewal and transfer; the `ISSUED` source-state rule and the term-date rule are now renewal-only, with transfer's source-state failure redirected to priority 8 — `implementation/routes_permits.py:155-160, 212-213`
- **§3.3 transfer narrative** — insert — one sentence pinning `ERR_PERMIT_STATE_INVALID` (priority 8, before posture/standards/ownership/preference-chain) for a non-`ISSUED` source, contrasted with renewal's `ERR_PREDECESSOR_PERMIT_INVALID`, and keeping the successor clash at priority 15 — `implementation/routes_permits.py:206-213`
- **§3.9 appeal filing** — revise (2 spots) — "filed by the affected `Permittee` alone" → "filed by a `Permittee` alone, in that permittee's own name", plus one sentence pinning that the role gate and the `appellant_permittee_id == X-User-ID` match are the entire appellant test and no affectedness is derived — `implementation/routes_decisions.py:229-238`

No edit for the other two Step 7 items: the `scheduled_aums` correction was a pure test bug (PRD §3.1 line 202 already states the DRAFT/VOIDED exclusion verbatim, and `derive.py:76-92` matches it exactly via `ALLOCATING_AOI_STATUSES`), and the clock rebase was a test-harness epoch bug (PRD §2.5 line 98 already pins the `2026-08-01T00:00:00Z` start and line 272 the strict delinquency boundary).

## Per-edit pre-edit search log
1. **Priority 8 edit.** (a) Subject: which priority/code governs a permit action's source-`permit_status` check. (b) Enumerated: `grep -rn "ERR_PERMIT_STATE_INVALID|ERR_PREDECESSOR_PERMIT_INVALID|predecessor_invalid"` over all of `implementation/` → `routes_permits.py:128` (issue: `PENDING_REVIEW` gate at priority 8, before closed/health), `:156/:158/:160` (renew, all three → `ERR_PREDECESSOR_PERMIT_INVALID`), `:207` (transfer), `:213` (transfer successor clash), `routes_aoi.py:74` (AOI draft requires `ISSUED` permit), `routes_aoi.py:224` (AOI issue re-checks permit still `ISSUED`), `errors.py:24/50` (409 vs 422); read `gates.py` in full for the ordering of `closed`/`health`/`qualified`/`debt`/`capacity`. (c) Adjustment: named only transfer as the new priority-8 case and called renewal out as an explicit exception, leaving the generic sentence to cover permit issuance and both `routes_aoi.py` cross-entity sites — an unqualified "every declared permit transition fails here" would have mis-described `renew_permit`.
2. **Priority 15 edit.** (a) Subject: the scope of `ERR_PREDECESSOR_PERMIT_INVALID`. (b) Same enumeration as above; confirmed the only three emitters are renew's status/successor/term checks and transfer's successor check, and confirmed `has_successor()` is shared by both paths and sits after `owned_by` (priority 13) in each. (c) Adjustment: kept "on permit renewal and permit transfer" in the header and preserved the no-successor rule for both, rather than narrowing the whole priority to renewal — narrowing would have orphaned `routes_permits.py:213`.
3. **§3.3 transfer narrative edit.** (a) Subject: the transfer precondition order as a reader-facing narrative. (b) Read `transfer_permit()` end to end (lines 191-240) plus `renew_permit()` and `issue_permit()` for contrast, and `gates.py` for each gate's numbered comment; confirmed the actual runtime order is state → closed → health → owned_by → successor → qualified → debt → capacity. (c) Adjustment: listed the four checks the state gate now precedes by their PRD names rather than claiming it is "the first check", since shape, date-range, role and both existence resolutions still run before it.
4. **§3.9 appeal edit.** (a) Subject: who may file an appeal and what the server tests about the appellant. (b) Read `routes_decisions.py:228-254` (`file_appeal`) and its neighbours `list_appeals`/`get_appeal`/`docket_appeal`/`decide_appeal`; read all of `auth.py` (`authenticate`, `require_own`, `scope_permittee_rows`, `require_identity`, `require_segregation`); grepped PRD for `affected` to confirm §2.1 line 21, §2.6 priority 3 and §4's endpoint table already describe filing as role + identity match only, and that the other "affected" uses are cascade-scope language untouched by this edit. (c) Adjustment: scoped the new sentence to the *appellant* test only ("no further relationship between the appellant and the appealed decision") and deliberately deferred to the following sentence for the `FINAL`/`EFFECTIVE` status rule via "any decision whose status allows an appeal" — an unqualified "any registered Permittee may appeal any decision" would have contradicted the `ERR_DECISION_STATE_INVALID` branch at `routes_decisions.py:236`. Also left the scoped-read rules on `appellant_permittee_id` untouched.

Orchestrator verification: `PRD_FINALIZED.md` is 490 lines / 126,599 bytes against PRD.md's 490 / 125,137, `diff` emits 16 lines (8 changed line-pairs across the 4 edit sites, consistent with in-place revision and no section loss), and the tail is still the complete final row `| ERR_OVERPAYMENT | 422 |` — not truncated. The file is NOT byte-identical to PRD.md, which is the expected shape here given Step 7 landed one real implementation fix.

## Step 9: Complete PRD — 2026-09-06T05:34:21Z

Step 9 was run as FOUR sequential, module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 owned the `cp`; passes 2-4 were forbidden to copy), with pass 4 doubling as the cross-pass reconciliation pass. Partition: pass 1 = cross-cutting layer (`app.py`, `envelope.py`, `errors.py`, `constants.py`, `store.py`, `validate.py`, `auth.py`, `find.py`, `gates.py`, `start.sh`); pass 2 = computation layer (`calc.py`, `derive.py`, `services.py`); pass 3 = `routes_land.py`, `routes_permits.py`, `routes_aoi.py`, `routes_bills.py`; pass 4 = `routes_monitoring.py`, `routes_decisions.py`, `routes_ops.py` + reconciliation + a full self-consistency sweep.

Source file: `PRD_FINALIZED.md` (490 lines / 126,599 bytes). Result: `PRD_COMPLETED.md` **492 lines / 163,039 bytes** (+2 lines, +36,440 chars, +28.8%). Totals across the four passes: **81 edits — 40 ambiguity-pins, 41 mismatch-revisions.** File grew monotonically pass to pass (133,703 -> 143,521 -> 151,444 -> 163,039), proving no pass clobbered an earlier one.

### PASS 1 — cross-cutting layer (11 ambiguity-pins, 5 mismatch-revisions)
- §2 intro — insert — ambiguity — trailing slash equivalence; unrouted path -> `ERR_NOT_FOUND`/404, bad method -> `ERR_METHOD_NOT_ALLOWED`/405, both in the standard envelope — `app.py:34-38,55,66-70`
- §2.1 — revise — mismatch — only `Permittee` identities resolve; blank header, unrecognised role, and the five-condition gate order pinned — `auth.py:24-40`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars of `A-Z0-9` (24 total) — `envelope.py:17,21`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the host real-time clock, not the logical clock, strictly increasing per process — `envelope.py:27`, `store.py:51-63`
- §2.2 — revise — mismatch — the error envelope also covers 5xx faults, not 4xx only — `app.py:72-74`
- §2.3 — insert — ambiguity — omitted/empty `limit`/`offset` take defaults; whitespace trimmed; non-integer is `ERR_VALIDATION`; `offset` unbounded, out-of-range returns an empty page with `has_more` false; both validated ahead of the identity gate on all 16 list routes — `envelope.py:76-96`
- §2.3 — insert — ambiguity — default order is total (stamps strictly increase), insertion order as tie-break; filters applied after ordering; omitted/empty filter ignored; uninterpretable int/bool filter matches nothing; unknown-id filter yields an empty page, not 404 — `envelope.py:106-108`, `find.py:43-72`
- §2.4 — insert — ambiguity — `id` is a canonical lower-case hyphenated 36-char UUID and a client-supplied `id` is ignored; `created_at` from the real-time clock; strictly increasing stamps so no two resources share `created_at` — `store.py:36,55-63,116-124`
- §2.6 item 1 — insert — ambiguity — accepted instant spellings (offsets rejected, `Z` only) and re-render to 3 fractional digits — `store.py:69-88`, `routes_ops.py:181`
- §2.6 item 1 — insert — ambiguity — shape check extends to `limit`/`offset`; absent body read as `{}`; non-JSON/non-object body is `ERR_VALIDATION`; fields checked in declared order; present-`null` fails like absent; integer fields accept `5.0` but never booleans; strings reject whitespace-only — `validate.py:17-29,32-43,71-158`
- §2.6 item 2 — insert — ambiguity — the date-range check is skipped when either endpoint is absent or null — `validate.py:164-172`
- §2.7 — insert — ambiguity — requests are serialised process-wide, so a version check and its write are indivisible and cascades are never observed half-applied — `app.py:41-50,76`, `store.py:10`
- §2.10 — insert — ambiguity (x2) — both the segregation comparisons and the positive identity-match rules hold vacuously while the named identifier is null — `auth.py:60-70`
- §3.8 — revise — mismatch — `nepa_level` has four members (`CX`, `CATEGORICAL_EXCLUSION`, `EA`, `EIS`); only `EA`/`EIS` are "heavy" for the priority-11 rationale rule — `constants.py:80-81`
- §3.12 — revise — mismatch — `project_type` has five members, adding `VEGETATION_TREATMENT` and `EROSION_CONTROL` — `constants.py:91-92`
- §5 intro — insert — mismatch — §5 claimed to list every failure; added prose for the three framework-level ids (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500) deliberately outside the table — `errors.py:23,46,59`

Pass 1 also mechanically verified that every constant in `constants.py`, all 14 not-found codes in `find.NOT_FOUND`, all 52 catalogue statuses in `errors.HTTP_STATUS`, and the `gates.py` priority numbers (9, 10, 16, 28, 30) already matched the PRD exactly — no change needed.

### PASS 2 — calc/derive/services (8 ambiguity-pins, 5 mismatch-revisions)
- §3.10 hop two — revise — mismatch — **pass-1 hand-off RESOLVED**: `effective_capacity_aums` derives from the allotment's own `total_permitted_aums`, not `carrying_capacity_aums` (a base-property preference input with no part in allotment capacity); §2.9 was right, §3.10 was wrong; worked example re-anchored to a 1,000-AUM ceiling — `calc.py:78`, `derive.py:50`
- §3.5 — revise — mismatch — the non-use counter is the unbroken run ending at the most recent *counting* year; a later breaking year or gap does not reset it and an earlier broken run never revives — `services.py:131-152`
- §3.8 `CANCELLATION` cascade — revise — mismatch — it releases the sum of the voided instructions' `billable_aums` across every grazing year, not "the permit's `permitted_aums`" (a permit is never an entry in `allocated_aums`) — `services.py:303-313`, `derive.py:38-47`
- §3.8 `SUSPENSION` cascade — revise — mismatch — `permit_status`/`suspension_reason` are written only if the permit is actually `ISSUED`, while the `DRAFT` instruction voiding happens regardless — `services.py:290-302`
- §2.9 — insert — ambiguity — all three ledger lines are derived on read, never stored; `open_aums` is not clamped and goes negative when `BILLED`/`CLOSED` instructions outlive a reduction; exact `version`-bump trigger set — `derive.py:50-56`, `gates.py:57`
- §2.9 — insert — ambiguity — `account_status` is re-derived two-way from live bills, scoped to `PENDING_REVIEW`/`ISSUED`/`SUSPENDED` permits — `services.py:112-125`
- §2.11 — insert — ambiguity — a recompute landing on the existing value is not a mutation (no `updated_at`/`version` move); the reallocation's head allotment is the exception, written once regardless — `services.py:157,124,237`
- §2.8 — insert — ambiguity — these fields render as bare JSON numbers, so the decimal rules constrain value not textual width (`40.0`, `0.4`); genuinely absent quantities render `null` — `derive.py:12-23`
- §3.4 pasture aggregate — insert — ambiguity — no `record_status`/`aoi_status` filter (so `DRAFT` legs count, unlike §3.1's roll-up); on actual-use reporting only the subject leg substitutes its actual window/`actual_aums` — `services.py:258-275`
- §3.6 — insert — ambiguity — full field set of an `ADJUSTMENT_DEBIT`/`ADJUSTMENT_CREDIT` bill (`billed_aums` 0.00, `fee_rate` still 172, base = total = signed delta, no admin fee re-levied, `superseded_bill_id` null, `aoi_id` populated) — `services.py:41-49,105`
- §3.6 step five — insert — ambiguity — the third branch: with no live use bill a `FINAL_USE` bill is raised outright when the total exceeds 0 and nothing at all when it is 0; a fully paid preliminary bill is never credited back — `services.py:87-96`
- §3.10 hop four — insert — ambiguity — candidates restricted to the three use-bill types in `ISSUED`/`DELINQUENT`; unpaid supersession is unconditional and emits a replacement even at an identical or zero total; `void_reason` left null; no candidate means a no-op — `services.py:66-107,240`
- §3.10 cascade — insert — ambiguity — hops 3-5 run only when hop one's fraction actually moved, while the allotment `version` still bumps once — `services.py:218-247`

### PASS 3 — routes_land / routes_permits / routes_aoi / routes_bills (7 ambiguity-pins, 16 mismatch-revisions)
- §2.4 — revise — mismatch — replaced the false universal "whenever its capacity ledger, posture or health determination is rewritten" with the exact closed trigger set (closure order issued/lifted/expired-by-clock, assessment finalized with concurrence, decision authored, decision effective/vacated, operating-instruction issuance) plus explicit non-triggers — `routes_aoi.py:242`, `routes_decisions.py:73,81,136`, `routes_monitoring.py:172`, `routes_ops.py:85,136,421`
- §3.1 — insert — ambiguity — the `season_end > season_start` rule is `ERR_VALIDATION` at priority 1, never `ERR_INVALID_DATE_RANGE` — `routes_land.py:37-38`
- §3.1 — revise — mismatch — pasture `name` is not unique within the allotment; only `sequence_order` is collision-checked — `routes_land.py:86-93`
- §3.2 / §4 — revise — mismatch — **hand-off RESOLVED**: register-wide listing filters `permittee_id`/`base_property_type`, nested listing filters `base_property_type` only, and `qualification_basis` is an exact query alias of `base_property_type` on both with no stored attribute; neither listing is ownership-narrowed — `routes_land.py:191-194,202-207`
- §3.3 / §4 — insert — ambiguity — **hand-off RESOLVED**: permit issuance writes only `permit_status` + `preference_priority`, reads `open_aums` without reserving, contributes nothing to `allocated_aums`, never touches the allotment row or `version`; returns 200 — `routes_permits.py:136-140`
- §3.3 — insert — ambiguity — renewal: `requested_aums` ignored; supplied `base_property_id` used only for priorities 13/16 while the successor inherits the predecessor's property; successor `suspension_reason` null; HTTP 201 — `routes_permits.py:162,172-187`
- §3.3 — revise — mismatch — transfer voids instructions of the *source permit*, not "of the transferor"; successor takes the supplied base property, ignores payload term dates/`requested_aums`, starts `consecutive_nonuse_years` at 0; source's `suspension_reason` cleared; HTTP 201 — `routes_permits.py:218-240`
- §2.6 priority 16 — revise — mismatch — issuance, renewal and transfer all compare the *stored* `permitted_aums`, never a payload figure — `routes_permits.py:134,162,214`
- §3.4 — insert — mismatch — the `livestock_kind`-vs-permit `ERR_VALIDATION` is evaluated after priority 3 and after path-AOI resolution but before the `pasture_id` FK and every gate — `routes_aoi.py:138-141`
- §3.4 — insert — ambiguity — the five issue conditions run by §2.6 priority, not in the order enumerated — `routes_aoi.py:220-238`
- §3.4 — insert — ambiguity — a draft instruction's `void_reason` starts null — `routes_aoi.py:100`
- §3.5 — insert — ambiguity — non-use has no `aoi_status` precondition and a second approval replaces rather than accumulates — `routes_aoi.py:249-271`
- §3.5 — revise — mismatch — acceptance goes `ISSUED` -> `BILLED` in a single write; `USE_REPORTED` is a declared enum member no operation persists, so `version` advances by exactly 1 — `routes_aoi.py:319-333`
- §3.6 — revise — mismatch — the first two payment effects fire only when the payment brings the bill to `PAID` (and the AOI hop also needs `aoi_status` `BILLED`); the last two run on every successful payment — `routes_bills.py:65-96`
- §4 preamble + 7 table cells — revise/insert — mismatch — renew/transfer return 201 with the successor; added the missing filters `admin_unit_code`, `rest_required`, `base_property_id`, `predecessor_permit_id`, `nonuse_reason`, `superseded_bill_id`, and the base-property filter/alias set; corrected the issue-endpoint ledger claim — `routes_land.py:62,125,191-194,202-207`, `routes_permits.py:104-111,136,188,240`, `routes_aoi.py:119`, `routes_bills.py:37`

### PASS 4 — routes_monitoring / routes_decisions / routes_ops + reconciliation (14 ambiguity-pins, 15 mismatch-revisions)
- §2.1 — revise — mismatch — the closed Permittee scope list now includes trespass incidents attributed to it — `routes_ops.py:206,221`
- §2.5 — revise — mismatch — "four consequences" -> the exactly three sweeps in executed order (delinquency, closure expiry, permit expiry), with the observable ordering consequence — `routes_ops.py:382-384`
- §2.6 pri 1 — revise — mismatch — "three cross-field shape rules" -> six, adding the per-`decision_type` `assessment_id`/`permit_id`/`adjustment_pct` rules and the `UTILIZATION_MAPPING`->`observed_utilization_pct` rule; all precede priority 3 — `routes_decisions.py:89-100`, `routes_monitoring.py:64-66`
- §2.6 pri 9 — revise — mismatch — six -> seven guarded operations, adding project approval — `routes_ops.py:325-327`
- §2.6 pri 12 — insert — ambiguity — on make-effective the stay is tested before the priority-8 `FINAL` requirement — `routes_decisions.py:217-220`
- §2.6 pri 18 — insert — mismatch — creation checks both duplicate clauses; review checks only the `FINALIZED` clause and only on `CONCUR` — `routes_monitoring.py:69-74,143-147`
- §2.6 pri 25 — insert — ambiguity — planned window may end one day past `season_end_date`; reported window is inclusive on both ends; the allotment-window check is creation-time only — `routes_aoi.py:84,153,295`
- §2.9 — revise — mismatch — dropped "or cancelling" from the version-neutral list, added effectuation/vacatur to the expressly-bumping list, and stated the agreement with §2.4 — `routes_decisions.py:73,81`
- §3.1 — insert — ambiguity — `MM-DD` is calendar-shape-only, validated against a leap year, so `02-29` is accepted; the document explicitly does not define its resolution against a non-leap grazing year — `validate.py:55-62`, `gates.py:62-67`
- §3.3 — insert — ambiguity — no operation writes `NONPAYMENT`; only an effective `SUSPENSION` decision sets `DECISION` — `services.py:293`
- §3.6 — insert — ambiguity — the fourth payment effect is conditional and never fires — `routes_bills.py:99-110`
- §3.7 — insert — ambiguity — nullability/defaults of the three optionals (null, empty array, false) and `review_notes` starting null — `routes_monitoring.py:26-31,83-90`
- §3.7 — revise — ambiguity — submit's utilization precondition is `ERR_ASSESSMENT_STATE_INVALID`, tested after the `DRAFT` check — `routes_monitoring.py:124-128`
- §3.7 — revise — ambiguity — review order: segregation, then the branch-specific `ERR_DUPLICATE_ASSESSMENT_FOR_YEAR` (CONCUR only) / remand ceiling (REMAND only), then the non-null `review_notes` write on either branch — `routes_monitoring.py:139-152`
- §3.7 — revise — mismatch — "does nothing else at all" now excepts `review_notes` — `routes_monitoring.py:151-156`
- §3.7 — revise — mismatch — corrected the cap example: four standards + livestock lands *on* 0.5000 by arithmetic; the cap never truncates — `calc.py:177-183`
- §3.8 — revise — mismatch — `assessment_id`/`permit_id` are existence-checked only (not `FINALIZED`, no allotment relation); `adjustment_pct` is rounded per §2.8, not refused — `routes_decisions.py:103-104`
- §3.8 — revise — mismatch — signature order is segregation -> `PROPOSED` -> NEPA; `rationale` falls back to the authored value; every `REMANDED` appeal returns to `UNDER_REVIEW` — `routes_decisions.py:183-206`
- §3.8 — revise — mismatch — make-effective order is identity -> stay -> `FINAL` — `routes_decisions.py:212-221`
- §3.8 — insert — ambiguity — every vacatur bumps the allotment version once (including the cascade-free `STAYED`->`VACATED` path and `CANCELLATION`/`ISSUANCE`); `REVERSE` against a merely-`FINAL` decision leaves it `FINAL` — `routes_decisions.py:76-81,340-343`
- §3.9 — revise — mismatch — adjudication gates: identity -> segregation against both `deciding_officer_id` and `authoring_officer_id` -> `UNDER_REVIEW` — `routes_decisions.py:299-307`
- §3.9 — revise — mismatch — `REMAND` pushes down from `FINAL` or `STAYED`; leaves `EFFECTIVE` untouched; does not clear `stay_granted`; `decision_rationale` written only when supplied — `routes_decisions.py:312-325`
- §3.10 — insert — ambiguity — a wholly-earlier interval is refused by the same start-date-only test — `routes_ops.py:69-71`
- §3.10 — insert — ambiguity — lift's `justification` is optional/nullable but keeps the 10-500 shape and does not clear on omission — `routes_ops.py:33-36,131-132`
- §3.10 — insert — ambiguity — expiry recomputes once per distinct allotment (one version bump per advance) and is the second of three sweeps; nested listing narrows by `order_status`/`order_type` only — `routes_ops.py:102-113,406-421`
- §3.10 — insert — ambiguity — hop two fires §3.12's project termination on the transition into `CLOSED` — `services.py:226-227,209-215`
- §3.11 — insert — ambiguity — incidents are Permittee-scoped by `permittee_id`; a null-owner incident is filtered from a Permittee listing and a direct read is `ERR_UNAUTHORIZED` — `routes_ops.py:206,221`, `auth.py:47-57`
- §3.12 — revise — mismatch — fractions are rounded per §2.8, and the exact-1.0 sum is tested on the submitted values before rounding — `routes_ops.py:279-288`
- §3.12 — revise — mismatch — excluded permit statuses corrected: dropped the non-existent `DRAFT`, added `TRANSFERRED` — `routes_ops.py:342-344`

### Job B reconciliation resolutions (pass 4)
1. **REMAND vs `review_notes`** — confirmed at `routes_monitoring.py:151-152`. §3.7's "nothing else at all" narrowed to except the notes; the notes rule now stated once, up front, as written on either branch only when non-null.
2. **`NONPAYMENT`** — confirmed written nowhere (declared `constants.py:65`, read `routes_bills.py:107`). Pinned in §3.3 that no operation produces it; the enum member stays declared and §3.6's reinstatement rule stays, now labelled a conditional that never fires. No implementation change.
3. **§2.9 vs §2.4 on cancellation** — §2.4 was already code-accurate; §2.9 was wrong. §2.9 now drops cancellation from the version-neutral list and adds effectuation/vacatur to the bumping list. Both sections now describe the same 8 bump sites.
4. **Closure expiry via clock advance** — confirmed: `sweep_closure_expiry` calls `services.run_reallocation` (`routes_ops.py:421`). §3.10 names it sweep two of three with per-allotment dedup; §2.5 and the §4 clock row list the same three sweeps in the same order; §3.6 and §3.3 supply sweeps one and three. All four agree.
5. **Season-window asymmetry** — was genuinely ambiguous. Tightened at priority 25 only: planned exit may be `season_end + 1` (half-open), reported exit must be `<= season_end`. `gates.season_window` confirmed called from `routes_aoi.py:84` alone, so the allotment-level clause is now scoped to instruction creation.
6. **Leap day** — both sites read. `parse_mmdd` validates against year 2000 (leap) so `02-29` is accepted; `gates.season_window` would raise on a non-leap `grazing_year`. §3.1 now says the `MM-DD` check is calendar-shape-only and that this document does not define the `02-29`/non-leap resolution. Deliberately not stated: any concrete status or `error_id` for that combination — asserting `ERR_INTERNAL`/500 would contradict §5's "none of the three is ever the correct answer to a request this document describes", and asserting `ERR_VALIDATION` would misdescribe the code. Implementation untouched.

### Internal contradictions found and closed by pass 4's self-consistency sweep (12)
§2.5's "four consequences" vs the §4 clock row's three sweeps; §2.9's version-neutral list vs §2.4's trigger list on permit cancellation; §2.6 pri 9's "six operations" vs §3.12's `ERR_ALLOTMENT_CLOSED` on project approval; §2.10's "neither `deciding_officer_id` nor `authoring_officer_id`" vs §3.9's signing-officer-only sentence; §2.6 pri 12 vs §3.8's make-effective ordering; §2.6 pri 18's two-clause duplicate rule vs §3.7's review behaviour; §3.8's "finalized assessment" vs §3.7's finalization rules (no such link exists); §3.7's self-contradictory cap example; §3.10 hop two vs §3.12's project-termination trigger; §3.12's excluded-status list vs §3.3's `permit_status` enumeration; §2.8's decimal conventions vs §3.8/§3.12's "at most 4 decimal places"; §5's "`ERR_INTERNAL` is never correct" vs the new leap-day text.

### Deliberately left un-pinned
- The concrete outcome of a `02-29` season boundary against a non-leap grazing year — the PRD cannot state it honestly without either contradicting §5 or misdescribing the code.
- The `pct4` rounding drift the §3.12 sum check permits is disclosed but no exact stored-sum invariant is asserted, because none holds.
- Three unobservable impl paths (pass 2): `recommended_reduction`'s null-`observed_utilization_pct` branch (the submission gate forbids it), `outstanding_use_bill`'s `_seq` tie-break (at most one live use bill per instruction), and the missing `record_status` filter in `scheduled_aums`/`planned_aums_total` (no route ever writes `record_status` `VOIDED`). `INCIDENT_STATUS.DISMISSED` (pass 1) is likewise never written by any path and is not enum-validated, so it is not pinnable as behaviour.

### Orchestrator verification
`PRD_COMPLETED.md` is 492 lines / 163,039 bytes against `PRD_FINALIZED.md`'s 490 / 126,599. It is **not** byte-identical to its source (`cmp` differs), so the scan genuinely ran — the known failure mode where a byte-identical `PRD_COMPLETED.md` means no pass executed does not apply here. `diff` reports 70 hunks. All 5 top-level `##` sections are present, the tail is the intact final row `| ERR_OVERPAYMENT | 422 |`, and a case-insensitive grep for `expert|scaffold|benchmark|harder than` returns 0 hits. The newest file under `implementation/` has mtime 04:25:36 while `results.1.json` is 04:30:51, confirming Steps 8 and 9 changed no implementation code after the green sweep — the 8 x 124/124 result files remain valid evidence for exactly the code that ships. Scratch tree removed in full.
