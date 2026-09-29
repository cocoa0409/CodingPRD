# Worklog — task_2997_aviation_hull_liability_underwriting

## Step 1: Create task directory — 2026-09-06T03:54:04.112Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2997_aviation_hull_liability_underwriting` and its `workspace/` subdirectory. Index 2997 was pre-assigned by the orchestrating prompt (no scan of ./tasks/, no auto-allocation — concurrent pipelines on this host would collide).

## Step 2: Generate scaffold — 2026-09-06T05:46:38.312820335Z

Subagent (prd-bench-scaffold-generator) returned:

| File | Lines | Bytes | Top-level key(s) |
|---|---|---|---|
| `SCAFFOLD.yaml` | 3069 | 150015 | `api_prefix, calculations, complexity_profile, concurrency_rules, domain_name, endpoints, entities, errors, response_envelope, roles, scenario, state_machines, validations` |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1708 | 126031 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4492 | 341695 | `scaffold_corner_design` |

`SCAFFOLD.yaml` contains **neither** `scaffold_difficulty_design` **nor** `scaffold_corner_design` (both checked False).

§1.0–§1.7 counts (SCAFFOLD.yaml): 12 entities, 46 endpoints, 54 error codes, 43 validation rules, 13 calculations, 8 state machines, 5 roles, 2 concurrency_rules. Profile: pricing_engine / compliance_audit, flat topology, parallel state machines, role_model: segregation_of_duties, consistency_model: immediate, difficulty_level: beyond_expert.

§1.8 — 9 rule ids x 2 instances = 18: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

§1.9 — 9 sections, 76 instances (58 with test_recipe, 18 excluded_because stubs): entities 12, state_machines 15, calculations 15, validations 10, endpoints 5, errors 8, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1. Every stub cites an excluded_because.difficulty_instance that exists by name in §1.8 and carries no test_recipe (asserted programmatically). All 54/54 error codes are triggerable from §1.8+§1.9.

Verification output:
- yaml.safe_load succeeds on all three files.
- Each file's tail ends on a complete list item at a real structural boundary (no mid-key truncation).
- worklog.md and workspace/ untouched.
- Lint verdict, verbatim:
```
Coverage
  §1.5 endpoints declared:    46
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     58
  Calls scanned (§1.8+§1.9):  934

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
- Two design bugs caught and fixed during authoring: a war-placement window touching a sibling placement's closed interval on the same policy (would have hit validation priority 29 instead of the asserted 201), and seven literal `expected_*_version` values that had to become captured `${var}` tokens. Also noted: a `NON_COOPERATION` claim can never be repaired (no investigations edge leaves `COVERAGE_REFERRED`), so the cooperation-error instance uses a second claim for its positive control.

**Orchestrator post-step action:** the difficulty directive line "Generate task harder than expert level!" had leaked verbatim into SCAFFOLD.yaml's `scenario:` block (line 2). Stripped it so it cannot reach PRD.md via the doc generator. Re-parsed all three YAMLs after the edit — all still load; repo-wide grep for the directive now returns nothing.

## Step 3: Copy shared files — 2026-09-06T05:46:43.553179841Z

Copied ./INSTRUCTION.md to tasks/task_2997_aviation_hull_liability_underwriting/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-06T06:02:26.332626650Z

Subagent (prd-bench-doc-generator) returned:

Deliverable: `workspace/PRD.md` — the only file written. `SCAFFOLD*.yaml`, `worklog.md` and `workspace/INSTRUCTION.md` were not touched; scratch stayed inside `.scratch/step4/` and no `.scratch` sibling was removed.

Self-check (a) size: `wc -l` = 484, `wc -c` = 109733.

Self-check (b) clean ending: `tail -40` lands inside the §5 error table; the final three lines are complete table rows ending at `| ERR_POLICY_HAS_NO_SCHEDULES | 409 |`. There is no audit footer and no truncated sentence — the document ends exactly at the end of §5.

Self-check (c) coverage. Section outline:
- `## 1. Introduction` (L3)
- `## 2. Global Specifications & System-Wide Principles` (L11) — 2.1 RBAC, 2.2 API Response Structure (byte-verbatim), 2.3 Pagination & Collection Filtering, 2.4 Common Resource Properties, 2.5 Logical Underwriting Clock, 2.6 Money/Rates/Rounding, 2.7 Resource Addressing & Resolution Order, 2.8 Parallel Status Dimensions & Cascade Propagation, 2.9 Append-Only Premium Ledger, 2.10 Optimistic Concurrency, 2.11 Validation Precedence
- `## 3. Business Logic & Workflows` (L188) — 3.1 Risk Register, 3.2 Pilot Qualification Scoring & Logbook Audit, 3.3 Opening/Binding/Expiring a Policy, 3.4 Scheduling a Hull, 3.5 The Pilot Warranty, 3.6 Mid-Term Endorsements, 3.7 War/Hijacking/Terrorism Placement, 3.8 Fleet Accounts, 3.9 The Claim File, 3.10 Settlement
- `## 4. Endpoint Definitions` (L372)
- `## 5. Error Code Catalogue` (L425)

Mechanically verified against SCAFFOLD.yaml:
- Endpoints: 46 documented / 46 declared. Set difference in both directions is empty (method+path exact match).
- Errors: 54 documented / 54 declared, zero missing, zero HTTP-status mismatches.
- Entities: 12/12 named and their fields described.
- Validations: 43/43 — every `error_id` present (the 3 initial "misses" were compound alternation strings like `ERR_OPERATOR_NOT_FOUND | ERR_AIRCRAFT_NOT_FOUND | ...`; each component id is individually present).
- Calculations: 13/13, including all 7 multi-variant branches (2+2+3), with every numeric constant of length >=2 present in the prose (`90` resolves to the 900,000-ppm short-rate factor, written 3 times).
- State machines: 8/8, all 40 transitions and every declared state name present.
- Roles: 5/5 (Underwriter, Broker, ClaimsAdjuster, OperatorUser, Auditor).
- Concurrency rules: 2/2 — `expected_schedule_version`->`ERR_STALE_SCHEDULE_VERSION` 412 and `expected_policy_version`->`ERR_STALE_POLICY_VERSION` 412, in §2.10.

Self-check (d) no difficulty metadata: `grep -ic` for `expert`, `beyond_expert`, `difficulty` -> 0, 0, 0. Neither design index was ever opened, grepped or referenced.

Hard contracts (reported by the subagent, deliberately absent from the PRD itself):
- Contract 1 — Field-Name Coverage: PASS. 127 entity field names + 93 endpoint input identifiers = 136 unique required names; 0 missing from backticked prose (checked after stripping fenced code blocks so the §2.2 JSON fences don't skew backtick parity).
- Contract 2 — Rule Coverage: PASS. All 43 validations with error id, HTTP status and `applies_to` scope in §2.11; both OCC rejections in §2.10; all 40 transitions with guards, actors and side effects; all 13 calculations including the pinned-order rules (deductible on gross before salvage credit; floor-then-ceil war premium; round-per-line-then-sum for declarations; loss-year rather than clock-year depreciation basis); sibling-branch symmetry stated for both `NOTIFIED->INVESTIGATING`/`NOTIFIED->COVERAGE_REFERRED` and the three settlement bases; the `SETTLEMENT_RETURN` vs `REMOVE_AIRCRAFT` short-rate contrast made explicit.
- Contract 3 — §3 Path Purity: PASS. Zero backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path; §3 contains 0 occurrences of the string `/aviation`. The single `/aviation` mention outside §4 is the mount-prefix statement in §2.7.

Judgement call flagged by the subagent: the scaffold's endorsement-referral transition declares `actor: Broker` while the referral endpoint's `roles` list is `[Underwriter]`. §3.6 describes referral as an `Underwriter` action that records the broker's push-back in `referral_reason`, which is consistent with the §4 authorization table.

**Orchestrator truncation guard (per pipeline instruction):** independently re-checked PRD.md. 484 lines / 109733 chars; `grep -n '^## '` returns exactly the 5 top-level sections above; `tail -12` is 12 complete, well-formed error-table rows ending at `| ERR_POLICY_HAS_NO_SCHEDULES | 409 |`. The document ends at a real section boundary, not mid-sentence. No regeneration needed.

## Step 6: Generate implementation — 2026-09-06T06:53:25.725457131Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill's isolation requirement. Step 6 finished first, so its entry is appended ahead of Step 5's; the worklog is append-only and entries are in completion order, not step order.)

**Orchestrator note — infra interruption and resume:** the Step 6 subagent was terminated mid-run by an upstream API error ("The system encountered an unexpected error during processing"), immediately before its final verification checklist. All 20 implementation modules were already on disk. Rather than respawn a fresh generator (which would have rewritten the modules and risked divergence), the orchestrator resumed the SAME agent via SendMessage with an explicit "do not regenerate anything already on disk — only finish verification and teardown" instruction plus the full checklist. That resume completed cleanly. Verbatim summary follows.

---

All verification and cleanup complete. The one "LIVE" pid was the documented trap — my own audit subshell (I had `cd`'d into `implementation/`); rescanned from outside and it's gone.

## Deliverable

`workspace/implementation/` — 20 files, 3,446 lines, 131,120 bytes (byte-identical across two checks 22s apart).

| Module | Lines | Module | Lines |
|---|---|---|---|
| routes_endorsements.py | 502 | derive.py | 108 |
| routes_claims.py | 400 | constants.py | 106 |
| services.py | 331 | store.py | 95 |
| routes_policies.py | 311 | util.py | 93 |
| serialize.py | 253 | app.py | 62 |
| routes_registry.py | 209 | auth.py | 55 |
| validate.py | 205 | envelope.py | 44 |
| routes_war.py | 196 | start.sh | 10 |
| routes_fleet.py | 167 | requirements.txt | 1 |
| calc.py | 165 | errors.py | 133 |

## Verification results

1. `ls -la` + `wc -l` — done, table above.
2. Parse — 18/18 `.py` files parse under `ast.parse`. Zero failures, so nothing needed fixing.
3. Tail integrity — all 18 modules end at a real structural boundary (complete `return`/dict-close). No 64k truncation anywhere; no re-appends needed.
4. **Routes — 46 of 46.** Parsed the PRD §4 table mechanically (46 declared) and iterated `app.url_map` (46 registered): `MISSING: none`, `EXTRA: none`.
5. Cold boot (PORT=22710) — ready in 0.5s, bound `0.0.0.0`, foreground. `POST /aviation/operators` → 201, `GET /aviation/operators/{id}` → 200 with identical body. Envelopes exact: top keys `["data","meta","response_type"]`; object `response_type:"object"`; list adds `limit/offset/total_count/has_more`; error `meta` carries only `api_request_id` + `api_request_timestamp` and `data` only `error_id`+`message`; `api_request_id` = `req_` + 20 alphanumerics; timestamps 3 fractional digits. Clock at the mandated default `2026-08-01T00:00:00.000Z`.
6. Teardown — killed only the captured pid, then derived pids from my port alone and `/proc`-verified `cwd` before killing. Earlier reap caught the known trap: a second child (2578313) survived the parent's TERM and held the port. All five ports used (22185, 23417, 23891, 24503, 22710) confirmed free; no python process has `cwd` inside `implementation/`. No `pkill`/`killall`/unscoped `ss` kill was ever issued.
7. No seeding — grep for seed/preload/bootstrap/sample/fixture/sqlite/pickle/json.dump/`open(...,'w')`/`/tmp/` matched only two *comments* saying nothing is seeded. Importing the app shows all 12 collections `len=0`, total rows at import: 0. Storage is plain dicts only.
8. Isolation honoured — never read `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any other `task_*` directory. Built solely from INSTRUCTION.md, SCAFFOLD.yaml and PRD.md.
9. Cleanup — removed `.scratch/step6` and `implementation/__pycache__` only; `.scratch` parent intact with siblings step4/step5/step7/step8/step9 untouched.

## Functional validation (three cold-boot passes)

Beyond the required smoke test I ran three full-lifecycle passes and hand-checked the arithmetic against the PRD; every figure matched to the cent:

- **Rate chain** floor-after-each-step: 10000 →17500 (COMMERCIAL) →21875 (WORLDWIDE) →19687 (BAND_A, from 19687.5). Also 15000→26250→26250→32812.
- **Depreciation** residual with 400,000ppm floor: 2018 jet = 680,000,000 at ref 2026, 600,000,000 at 2028 — and confirmed the read-model uses the *clock* year while the over-insurance ceiling uses the schedule's `effective_from` year.
- **Money invariant** verified on both pinned compensating pairs: endorsement bind/void (77,598,133 → 50,269,782 = exactly pre-bind) and placement create/cancel (16,499,600 → 15,749,600 = exactly pre-placement), with the market line released back to 500,000,000.
- **Round-up families**: endorsement delta 27,328,351 (from …350.68), declaration line 24,020,182 (from …181.9), late loading 576,048 at 150,000ppm, war premium 750,000 (floor then ceil).
- **RERATE_ADJUSTMENT** posts the full annual difference (−3,937,400, basis `ANNUAL`, null `endorsement_id`); a zero-delta revision correctly writes no row.
- **Parallel dimensions / cascades**: logbook audit dropped BAND_B→BAND_C, flipped `warranty_basis` to `VERIFIED_HOURS`, set `BREACHED`/`SUSPENDED_WARRANTY` and wrote the re-rate row; `WAIVER` reinstated `ACTIVE`. CTL promotion at 800,000ppm, settlement 400,000,000 − 20,000,000 deductible − 50,000,000 salvage = 330,000,000, schedule → `TOTAL_LOSS_SETTLED`.
- **Gates and plumbing**: OCC 412 on both `expected_schedule_version` and `expected_policy_version`; SoD 403 on both quote/bind and coverage/settlement; `ERR_PERILS_NOT_OFFERED`, `ERR_MARKET_LINE_EXCEEDED`, `ERR_OVER_INSURED_VALUE`, `ERR_DECLARATION_PERIOD_INVALID` (closed-interval touch counts as overlap), `ERR_CONDITIONAL_FIELD_REQUIRED` in both directions, 404/405/400 handlers, pagination bounds, and the auth ladder (401 missing headers → 401 unknown role → 403 `ERR_UNAUTHORIZED` / `ERR_OPERATOR_SCOPE_VIOLATION`).

Two apparent anomalies were investigated and are correct behaviour, not defects: `GET` on `/operators`, `/aircraft`, `/pilots`, `/war-markets` returns 405 because the PRD declares no collection-GET for those four (consistent with the zero-extras route audit); and my first fixture's 422 was a genuine `ERR_OVER_INSURED_VALUE` (900M vs the 680M×1.2 = 816M ceiling). No implementation change was made during verification.

## Step 5: Generate unit tests — 2026-09-06T07:04:03.570499310Z

Subagent (prd-bench-unit-test-generator) returned verbatim:

---

Step 5 complete.

## Files written

`test_helpers/` — 9 files, 3,064 lines: `__init__.py` 95 · `api_client.py` 387 · `api_errors.py` 141 · `assertions.py` 461 · `constants.py` 375 · `factories.py` 635 · `fixtures.py` 525 · `test_users.py` 116 · `types.py` 329

`test_suite/` — 18 files, 11,313 lines

| file | lines | tests |
|---|---|---|
| conftest.py | 16 | — |
| test_01_dual_variant_calculations.py | 466 | 7 |
| test_02_combinatorial_formulas.py | 462 | 8 |
| test_03_non_linear_state_machines.py | 406 | 9 |
| test_04_transitive_cascades.py | 475 | 11 |
| test_05_validation_priority_conflicts.py | 273 | 7 |
| test_06_boundary_precision.py | 434 | 8 |
| test_07_cross_entity_state_dependency.py | 440 | 7 |
| test_08_resource_temporal_overlap.py | 378 | 6 |
| test_09_compensating_invariants.py | 523 | 7 |
| test_10_entity_surfaces.py | 807 | 17 |
| test_11_state_machines.py | 1024 | 18 |
| test_12_calculations.py | 981 | 14 |
| test_13_validations.py | 977 | 16 |
| test_14_endpoint_surfaces.py | 797 | 11 |
| test_15_error_conditions.py | 1205 | 18 |
| test_16_access_control.py | 814 | 13 |
| test_17_concurrency_and_layering.py | 835 | 8 |

**185 test functions** (220 pytest cases after parametrize expansion).

## Coverage

- Queue A (§1.8 difficulty): **18 of 18** non-stub instances, 70 tests, every instance >=2 tests (min 2, typical 3–5).
- Queue B (§1.9 corner): **58 of 58** non-stub instances, 115 tests, every instance >=1 test.
- **Skip list: empty.** No instance failed the PRD-first filter.

Agents instead applied ~15 PRD-over-yaml corrections where the design index contradicted PRD.md (e.g. `ERR_CLAIM_INVALID_STATE` outranking `ERR_PILOT_WARRANTY_BREACHED` on the warranty-breach cascade by ladder rank; `CHARTER` → `PRIVATE_OWNER`; `applied_rate_ppm` → `rate_ppm`; agreed values pulled under the over-insurance ceiling; one `INITIAL_PREMIUM` ledger row not five; a `period_from == period_to` declaration split into two legal periods), and left a handful of figures deliberately unasserted where the PRD is silent (policy `version` bump on settlement/schedule attach, `WAR_RISK_PREMIUM` `basis`, `SETTLEMENT_RETURN` `effective_date`, undeclared HTTP methods on immutable paths, the referral-refusal error id).

## Two cross-file bugs found and fixed after the fan-out

1. **`perils_offered` was an array in `factories.py`.** PRD §3.7 ("a `perils_offered` recording the widest scope it writes. Scope is ordered: `WAR_ONLY` … `WAR_HIJACK_TERRORISM`") and `SCAFFOLD.yaml` (`type: enum`, `constraints: "one of …"`) both make it a **scalar**; the design index's example payload listing three values misled the builder. Changed the factory to `PerilsScope.WAR_HIJACK_TERRORISM` (widest, so narrower placements are accepted) and converted the two list overrides in `test_17`. `test_15`/`test_16` already used scalars, so all 17 files are now consistent. Zero `perils_offered=[` remain.
2. **`ApiErrorId.ERR_*` symbol bug (fixture rule g).** `ApiErrorId` attributes are unprefixed (`POLICY_NOT_FOUND = "ERR_POLICY_NOT_FOUND"`). 18 call sites in `test_04`/`test_05`/`test_10` used the prefixed spelling against 77 correct ones — a hard `AttributeError` at import that would have wiped `test_10` entirely in Step 7. Minority rewritten to match.

## Verification

- **AST**: 27 `.py` files parsed, 0 syntax errors.
- **Collection**: `pytest --collect-only` with the runner on `PYTHONPATH` → **220 tests collected, 0 errors** (no server booted).
- **Symbol resolution**: a static pass resolving every `f.*`/`fx.*`/`c.*`/`a.*`/`users.*`/enum-class attribute reference in the suite against the imported helper objects → **0 unresolved symbols**.
- **Tags**: `grep -c 'Design: '` = 185, `grep -c 'def test_'` = 185; AST check confirms every test has a docstring whose **last line** is **exactly one** `Design:` tag, and every tag resolves to a real `name:` in the correct index (rule ids validated against the index's `rule_id:` set).
- **Stability** (constraint 6): `wc -c` over both dirs sampled twice 25 s apart, then again 20 s apart after the fixes — identical both times. 536,901 bytes total.
- **Leakage**: `ls -d workspace/test_helpers workspace/test_suite` prints nothing. `workspace/implementation/` untouched; `worklog.md` untouched.
- **Housekeeping**: `__pycache__` and `.pytest_cache` removed; `rm -rf .scratch/step5` only — siblings `step4`, `step7`, `step8`, `step9` intact.

---

**Orchestrator verification:** independently confirmed `workspace/test_helpers`/`workspace/test_suite` do not exist (no misplacement into workspace/); `wc -c` over both output dirs sampled twice 25 s apart is identical at 536,901 bytes (fan-out fully drained); no `__pycache__`/`.pytest_cache` strays; `.scratch/` holds only step4/step7/step8/step9.

## Step 7: Run tests and iterate — 2026-09-06T07:35:49.688010103Z

Long-lived fix subagent returned verbatim:

---

All 8 rounds pass. Storage is in-memory only, `worklog.md` untouched (07:04, pre-dates my session), and `.scratch/step7` cleaned up without touching sibling scratch dirs.

## Summary

**Iterations run:** 2 (sweep 1 diagnosed, fixes applied, sweep 2 verified clean).

**Final sweep (passed, total):** (218, 218) × 8 — rounds 1–8 all `failed=0, errors=0`. Files on disk at `workspace/implementation/results.{1..8}.json`.

Sweep 1 was (216, 220) in **all 8 rounds** — 4 deterministic failures, zero flakiness, so nothing was load-induced and no re-sweep-to-confirm was needed.

### Tests deleted (2)

- **`test_17_concurrency_and_layering.py::TestWarPlacementPolicyVersionToken::test_a_attaching_another_hull_stales_a_line_sized_against_the_old_exposure`** — *branch-asymmetric side effect* (STEP 1b). It asserted that attaching a schedule advances the **policy's** `version` (`version=observed_version + 1`), which is the sole premise of its `ERR_STALE_POLICY_VERSION` refusal. PRD §3.4 enumerates attachment's closing actions as "updating the policy's `total_hull_sum_insured_cents` and `live_schedule_count` and advancing **the schedule's** `version`" — it names only the schedule. PRD is systematically explicit whenever a policy version advances (bind, endorsement bind, placement create/cancel, declaration acceptance, expiry all say so verbatim); attachment does not. Two faithful readings exist: §3.4 read as exhaustive (policy row untouched, its aggregates being derived per §3.3 — the implementation's reading), versus §2.4's generic "any cascade … that mutates a resource" read as reaching the policy row. Not salvageable by partial-coverage splitting, since the covered assertions were the premise of the uncovered one. Sibling `test_b` in the same class already covers the same OCC rule via the PRD-verbatim mechanism (§3.7 "advances the policy's `version`") and passes. Scaffold rule: `Corner/cross_cutting_complexity_layers/corner_occ_war_placement_stale_policy_version_rejected`.

- **`test_16_access_control.py::test_an_operator_user_cannot_read_another_operators_tree[premium_transactions]`** (one parametrization removed; `[policy]` and `[schedule]` kept) — *collection-read silence* (STEP 1b, with STEP 1c partial-coverage handling). PRD §2.1 verbatim covers refusing an `OperatorUser` that reaches a foreign premium-ledger row, but does not determine the response to a **collection** read carrying a foreign `policy_id` *filter*. Decisive: PRD must permit narrowing for an unfiltered collection read (an `OperatorUser` is an authorized role on every collection and §2.1 grants it the right to "read its own policy tree"), so once narrowing is the mechanism, applying it when a filter is present — yielding an empty array — is coherent; §2.3 treats filters as selection, not entitlement. The implementation applies this narrowing **uniformly across all 8 list endpoints**, so it is consistent, not a gap. The two retained cases are single-resource GETs by `{id}`, where "reaching a foreign resource" is unambiguous and the implementation correctly returns 403. Scaffold rule: `Corner/rbac/corner_operator_user_scoped_to_its_own_operator_tree`.

### Fixes applied to `test_suite/` (2)

- **`test_12_calculations.py`** lines 790 & 829, `test_a_rate_chain_falling_below_the_corridor_is_lifted_to_the_floor` and `test_a_rate_chain_rising_above_the_corridor_is_cut_to_the_ceiling`: `pilot["pilot_band"]` → `pilot["rating_band_logged"]`. Minority-symbol test-artifact bug (`KeyError: 'pilot_band'`, no HTTP response in the traceback) — `pilot_band` is not a PRD field and appeared at exactly these 2 call sites, against 15 uses of the PRD-declared `rating_band_logged` elsewhere in the suite. Both pilots are unaudited, so `LOGGED_HOURS` is the correct basis; the expected band values were already right (I verified ATPL_PILOT scores 850 → `BAND_A` and PPL_PILOT scores 275 → `BAND_D` by hand against §3.2). The fix makes the guard assertion more faithful to PRD, not weaker.

### Fixes applied to `test_helpers/` — none
The shared helpers were audited against PRD (money as JSON integers, full ISO-8601 instants, `_build` precluding duplicate-kwarg collisions, `""` rather than whitespace for blank auth headers, a `validate_unpaginated` variant alongside `validate_list`, phased fixtures, `canonical_instant` centralised in `api_client`). None of the known fixture-bug shapes was present.

### Fixes applied to `implementation/` — none
No PRD-traceable implementation defect surfaced. All 4 failures were test-artifact issues. No implementation check was weakened and nothing was added to `implementation/`.

### Load-induced flakiness
None observed. Every one of the 4 sweep-1 failures reproduced in all 8 rounds with identical assertions, and sweep 2 was clean in all 8 rounds.

---

**Orchestrator verification (independent of the subagent's report):** polled `workspace/SWEEP_DONE` and parsed all 8 `workspace/implementation/results.$i.json` myself. Sweep 1 read `(216, 220)` in all 8 rounds; the final sweep reads `(218, 218)` in all 8 rounds. Both sweeps ran through the pre-written `workspace/sweep.sh` under `setsid nohup` with a `SWEEP_DONE` sentinel after `wait`, so neither the SIGTERM-reaping failure mode nor the early-return-relaunch failure mode could occur. Test total dropped 220 → 218, consistent with exactly the 2 documented deletions (one whole test, one parametrization).

**Step 8 gate:** Step 7 made 0 `implementation/` fixes but DID make 2 deletions and 2 `test_suite/` fixes, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is not met. Step 8 runs.

## Step 8: Finalize PRD — 2026-09-06T07:41:04.572228445Z

Subagent returned verbatim:

---

PRD_FINALIZED.md is written. Two of the three candidate sites needed PRD edits; the third did not.

## Line counts
- PRD.md: 484 lines / 109,733 bytes
- PRD_FINALIZED.md: 484 lines / 111,062 bytes
- Delta: 0 lines (+0.00%), +1,329 bytes (+1.21%) — 3 lines revised in place, no new sections, no reflow.

## Changes

- **§2.1 (Underwriting Authority / RBAC), line 21** — revise — added that an `OperatorUser`'s `ERR_OPERATOR_SCOPE_VIOLATION` governs only requests naming one specific resource (path `{id}` or body FK), while every list endpoint is *narrowed* to the acting operator's tree before filters run, so a filter naming a foreign `policy_id` yields HTTP 200 with an empty `data` array and `total_count` 0 — `implementation/auth.py:51` (`visible_operator_id`), `implementation/services.py:97` (`visible_policy_ids`), `implementation/routes_policies.py:92`.
- **§2.11 rank 4, line 145** — revise — "Applies to every business operation" → "…that names one specific resource of those kinds; collection reads are narrowed rather than refused, as §2.1 sets out" — same impl sites.
- **§3.4 (Scheduling a Hull), line 252** — insert — after the existing closing-actions sentence, pinned that the attachment closing list is exhaustive as to the policy: the two aggregates are derived on read, so no write reaches the policy row and the policy's own `version`/`updated_at` do not move; plus the general statement that a policy's `version` advances only where the document says so in terms — `implementation/routes_policies.py:144-214` (`create_schedule`, no `touch(policy)`), `implementation/serialize.py:94`, `implementation/derive.py:70,74`.
- **`pilot_band` → `rating_band_logged`** — **no PRD edit**. `pilot_band` is not a PRD field anywhere (the 3 substring hits are `rated_pilot_band`); `rating_band_logged` is declared in §3.2 line 204 and emitted at `implementation/serialize.py:65`. Pure test-artifact symbol bug; PRD already determines it uniquely.

## Per-edit pre-edit search log

**Edit 1+2 (OperatorUser collection reads).** (a) Subject: how operator scope behaves on collection reads vs single-resource reads vs writes. (b) Enumerated: all 20 `GET` routes via `grep '@bp.route'` across `routes_*.py`; all 11 `visible_policy_ids`/`visible_operator_id` callsites; all 15 `scope_*` callsites. Found exactly 8 list endpoints (policies, schedules, endorsements, war-placements, claims, damage-assessments, premium-transactions, fleet-declarations) — narrowing applied in all 8, always **before** `V.filter_eq`, with `total = len(rows)` computed after; damage-assessments narrows transitively claim→policy (`routes_claims.py:182-184`). No list endpoints exist for operators/aircraft/pilots/war-markets. Single GETs by `{id}` scope-check and 403 for policies/schedules/endorsements/placements/claims/assessments/transactions/declarations/operators; `aircraft/{id}`, `pilots/{id}`, `war-markets/{id}` carry **no** scope check at all. Writes (`routes_policies.py:149`, `routes_claims.py:32`, `routes_endorsements.py:85`, `routes_war.py:75`, `routes_fleet.py:48`) 403 via body FK. `validate.py:187` confirms an unmatched filter value simply matches nothing. (c) Adjustment: wrote "one specific resource **of those kinds**" rather than a bare "any `{id}` read", so the sentence does not falsely claim `aircraft/{id}`, `pilots/{id}` or `war-markets/{id}` are scope-checked; and phrased the exception clause as "the single exception to the scope check as a whole" so it still covers both mechanisms.

**Edit 3 (policy version on attachment).** (a) Subject: which operations write the policy row / advance the policy's `version`. (b) Enumerated: all 41 `touch(...)` callsites and all 9 direct `policy["…"] =` assignments across `implementation/*.py`; `store.py:73` (`touch` advances at most once per row per request); `serialize.py:72-94` (policy aggregates derived at serialize time); `derive.py:70-97`. Exactly 7 sites advance a policy's `version`: policy bind (`routes_policies.py:138`), endorsement bind (`routes_endorsements.py:428`), void of a **BOUND** endorsement only (`routes_endorsements.py:497`, inside the `if`), placement create (`routes_war.py:137`), placement cancel (`routes_war.py:195`), declaration **ACCEPT** only (`routes_fleet.py:166`), expiry sweep (`services.py:213`). Confirmed absent from: `create_schedule`, value revision, warranty findings, pilot hours audit, every claim action incl. settlement, endorsement submit/quote/refer, declaration create/REJECT. Cross-checked all 31 `version` mentions in PRD.md: the policy's `version` is stated in terms at exactly those 7 transitions (lines 226, 228, 290, 292, 308, 310, 328), so the "only where this document says so in terms" universal holds. (c) Adjustments: scoped "the policy's own `version` and `updated_at` do not move" to attachment rather than to all re-derivations, then added the general "only where this document says in terms" clause so the value-revision and warranty-finding paragraphs (which also re-derive policy figures without touching the policy row) are not implied by contrast to advance it. Deliberately left "advancing the schedule's `version`" verbatim — `_add_aircraft_schedule` + `touch(created)` on void means a claim about a newly created schedule's version number would not hold uniformly, and it is off the Step 7 subject anyway.

## Constraint-6 verification
`wc`: 484/484 lines, 109,733 vs 111,062 bytes. `diff`: exit 1 with exactly the 3 line-level hunks above (21, 145, 252) and nothing else. `tail -3` ends at `| ERR_POLICY_HAS_NO_SCHEDULES | 409 |` — the real §5 error-table boundary, not truncated. Scratch dir `.scratch/step8` removed; PRD.md, `implementation/`, `test_suite/`, `test_helpers/`, `worklog.md` untouched; no server booted.

## Step 9: Complete PRD — 2026-09-06T08:34:49.486194308Z

**Orchestrator design decision (recorded per the autonomy directive).** A single monolithic Step 9 subagent reliably under-scans an 18-module implementation against a 484-line PRD, and its output is often byte-identical to its input (the tell that the scan never really ran). Step 9 was therefore executed as **four sequential passes over one shared `workspace/PRD_COMPLETED.md`**, partitioned by implementation module. Pass 1 alone performed the one-time `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2–4 were explicitly forbidden from copying, so no pass could erase its predecessors. A fourth **reconciliation** pass was added because module-partitioned passes report cross-pass contradictions rather than fixing them — with four agents editing §2.11 blind to each other, an unreconciled ladder is where a self-contradictory PRD comes from.

Partition:
- Pass 1 — cross-cutting foundation: `app.py`, `auth.py`, `envelope.py`, `errors.py`, `store.py`, `util.py`, `constants.py`, `validate.py`, `serialize.py`, `derive.py`.
- Pass 2 — registry, policies, war placement, calculations, services: `routes_registry.py`, `routes_policies.py`, `routes_war.py`, `calc.py`, `services.py`.
- Pass 3 — endorsements, claims, fleet: `routes_endorsements.py`, `routes_claims.py`, `routes_fleet.py`.
- Pass 4 — reconciliation only (no re-scan): close reported cross-pass contradictions, adjudicating from source.

Each pass handed its unresolved observations forward explicitly; the orchestrator inlined them into the next pass's prompt.

### Pass 1 (cross-cutting) — 11 ambiguity-pins, 3 mismatch-revisions

`cp` performed as the first action. 484/111,062 → 485/117,668 (+6,606 bytes, +1 line: one bullet added inside the existing §2.2 list). 11 diff hunks.

Changes: §2.1 role header compared exactly and untrimmed (`auth.py:14-19`); §2.2 `api_request_id` pinned to `req_` + 20 chars of `A-Z0-9` (`util.py:12,20-22`); §2.2 **mismatch** — `api_request_timestamp` is the real wall clock, explicitly not the §2.5 logical clock, three fractional digits (`envelope.py:8-12`) — PRD had said "the service does not read wall-clock time"; §2.2 **mismatch** — new bullet naming the four framework-level identifiers outside §5 (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INVALID_REQUEST` 400, `ERR_INTERNAL` 500) and pinning that routing resolves before the rank-1 auth ladder (`app.py:38-52`); §2.3 `limit`/`offset` empty==omitted, non-integer or out-of-range → `ERR_VALIDATION_FAILED` 422 with no silent clamping, `offset >= total_count` is an empty 200 page (`validate.py:161-180`); §2.3 list-ordering tie-breaker pinned to insertion order (`store.py:52-58`); §2.3 unknown/unmatched/empty filter values match nothing rather than erroring, `late_flag` the sole boolean filter, unknown query params ignored (`validate.py:187-205`); §2.4 `created_at` from the logical clock, sub-ms truncated not rounded, every defined field always present with explicit `null` (`store.py:63-66`); §2.4 **mismatch** — `version` advances at most once per request per row, not once per field write or per cascade hop (`store.py:61-95`); §2.6 **mismatch** — division floors to the largest whole number not exceeding the quotient, i.e. for negatives downwards away from zero, not truncation towards it (`util.py:67-71`); §2.6 zero denominator yields 0 in both floor and ceil families and is not an error; §2.7 trailing slash addresses the same endpoint (`app.py:25`); §2.11 rank 7 — JSON `null`==omitted, the exact accepted instant grammar, absent/empty body=={}, undeclared body fields ignored (`validate.py:27-99`); §2.11 rank 8 also covers `limit`/`offset`/boolean-filter query params, checked before narrowing and filtering; §5 lead sentence reworded to "business-rule identifiers … alongside the four framework-level identifiers named in §2.2" (table byte-identical).

Handed forward: `permitted_use_classes` echo order; `perils_offered` scalar-vs-array; route-level `ERR_VALIDATION_FAILED` raises; `HULL_LOSS_TYPES` vs `derive.paid_hull`; `check_pattern` trailing-newline leniency.

### Pass 2 (registry / policies / war / calc / services) — 14 ambiguity-pins, 10 mismatch-revisions

No `cp`; all 11 pass-1 hunks verified surviving by 12 distinctive-fragment probes. 485/117,668 → 485/129,556 (+11,888 bytes, 0 lines). 23 targeted Edits. All 29 section headers at identical line numbers.

Mismatches corrected: §2.10 ¶1 and ¶2 — dropped "before any business rule runs" / the equivalent for the policy token; both OCC tokens are compared at their true rank-19 position, after the rank-14 liveness gate and the rank-12 state gate respectively (`routes_policies.py:253-256`, `routes_war.py:90-94`). §2.11 rank 9 — warranty findings added to the applies-list, with the check displaced below rank 14 there alone. §2.11 rank 23 — policy binding and blocked placement cancellation added, with the bind-time displacement below rank 43. §2.11 rank 43 — no fiscal rule is checked at bind at all. §2.11 closing ¶ — "before anything else is evaluated" → before anything ranked below it. §3.3 bind-preconditions (×2) — an empty *and* unplaced draft reports `ERR_POLICY_HAS_NO_SCHEDULES`, not `ERR_WAR_RISK_NOT_PLACED`. §3.4 — "Five gates" → "Six gates", plus the real evaluation order (medical → use class → window → overlap → over-insurance → aggregate), which is not the expository order. §3.9 salvage — the blocked cancellation carries `ERR_WAR_RISK_NOT_PLACED` (422) after the rank-16 `BOUND` check.

Ambiguities pinned: §2.5 clock capability answers 200 with empty-object `data`, backwards repositioning accepted, the expiry sweep is one-directional; §2.7 a present-but-non-string body FK fails at rank 6 with the collection's 404, not as a rank-7 type error; §3.1 a single-operator read *is* scoped (403) while single-airframe and single-pilot reads never are; §3.2 audit figures ≥ 0 with no on-type ≤ total rule, a repeat audit overwrites and re-runs the fan-out; §3.3 `permitted_use_classes` echoed verbatim with order and duplicates preserved, canonical order only on default, non-array = 400 rank 7 vs empty/non-subset = 422 rank 8; §3.3 both liability-extension flags start `false` and are not inputs; §3.3 a zero-sum `INITIAL_PREMIUM` writes no row at all; §3.4 the over-insurance ceiling on value revision is re-derived against the schedule's stored `effective_from` year, not the clock year, so it never erodes with time; §3.5 a finding not accepted from the current state is a silent no-op (200, no version bump, no cascade) rather than a 409, and `WAIVER` clears the breach reason only when it also lifts a suspension; §3.5 a passing audit moves `PENDING_EVIDENCE` only, so an audit can suspend a hull but never reinstate one; §3.7 `perils_offered` confirmed a single scalar, `market_name` non-blank, duplicate → 422 with no dedicated code; §3.7 placement windows inclusive against the policy term, the three scopes nested so every pair overlaps, `CANCELLED` placements disregarded; §3.7 `WAR_RISK_PREMIUM` carries basis `ANNUAL` and `effective_date` = `coverage_from`, a zero premium suppresses the row but still commits the line; §3.7 the `RETURN_PREMIUM` row's `effective_date` is the current logical clock and the amount is never apportioned despite the `PRO_RATA` basis.

Pass-1 handoffs resolved: (1) echo order pinned; (2) scalar confirmed — pass 1 was right, one explicit "never an array" clause added since the nested-scope model makes the array reading superficially plausible; (3) route-level `ERR_VALIDATION_FAILED` confirmed correct id and rank, and a *second* family of route-level raises found that the PRD had not named correctly (`routes_war.py:51` duplicate `market_name`, `routes_war.py:184` blocked cancellation) — both pinned; (4) `derive.paid_hull` divergence agreed, no edit, escalated to pass 3.

Also verified with no edits needed: all eight `calc.py` formulas whose PRD homes lie in pass 3's sections (`pro_rata_up`, `short_rate_return` nested double floor, `exposure_base_annual`, `declaration_line`, `late_loading`, `ctl_ratio_ppm`, `deductible_on_gross`, `settlement_return`) — every rounding step and its order already matched the prose; and `services.select_assessment` / `recompute_claim_ctl`, whose strict `>` tie behaviour and one-way promotion already matched §3.9.

### Pass 3 (endorsements / claims / fleet) — 33 ambiguity-pins, 6 mismatch-revisions

No `cp`; all 34 earlier-pass diff lines verified untouched. 485/129,556 → 485/143,803 (+14,247 bytes, 0 lines). 39 targeted Edits.

Mismatches corrected: §3.9 ¶339 — "refuses every further action" narrowed to that dimension; `SELL`/`ABANDON` carry no `adjustment_status` gate and stay legal on a `SETTLED`/`DENIED` claim. §3.10 ¶369 — the schedule reaches `TOTAL_LOSS_SETTLED` from whatever `coverage_status` it holds (`ACTIVE` ordinarily, `PENDING` for an unregularised automatic acquisition), not only from `ACTIVE`. Plus four more in the §2.11 ranks 4/9/12/13/14/15/27/36 group and §3.6 ¶¶277–293.

Ambiguities pinned (selection): §3.8 `period_to == period_from` clears the rank-8 at-or-before rule and fails as `ERR_DECLARATION_PERIOD_INVALID`, overlap inclusive at both ends so touching periods collide; §3.8 an empty population still runs the clock test, so `late_flag` true with `late_loading_cents` 0 is reachable; §3.8 rejection has no policy gate and does not touch the policy's `version`; §3.8 the `reported_declaration_id` stamp is unconditional while activation is not, and `DECLARATION_PREMIUM` `effective_date` = `period_from`; §3.9 `loss_description` / `assessor_reference` non-blank when trimmed; §3.9 `investigator_reference` mandatory at investigation and overwrites the notification value, and only `REMOVED` blocks — `TOTAL_LOSS_SETTLED` does not; §3.9 the three COVERED conditions run in ladder order 14 → 24 → 42, not narration order; §3.9 the DENIED branch applies none of them; §3.9 salvage reachability precedes the TENDER `ctl_flag` test and the SELL proceeds test, and proceeds sent with any other action are ignored with the stored value staying 0; §3.10 the five settlement guards run in ladder order 21 → 23 → 25 → 37 → 38 → 40; §3.10 the basis test consults only `ctl_flag`, `assessment_count` and (for `AGREED_VALUE`) `warranty_status` — no basis is restricted by `loss_type`; §3.10 the aggregate test adds the **net** figure and applies on every basis and every loss type; §3.10 the zero floor bears on `settlement_amount_cents` alone while `deductible_applied_cents` records the deductible as computed; §3.10 `SETTLEMENT_RETURN` `effective_date` = the claim's `loss_date`, not the clock.

Handoff 1 resolved decisively: `HULL_LOSS_TYPES` (three types, incl. `WAR_PERIL`) is consumed **only** by the §3.9 coverage-decision reserve-ceiling gate (`routes_claims.py:239`); `derive.paid_hull` (two types) drives §2.9's `paid_hull_cents` and the §3.10 aggregate gate (`routes_claims.py:356`). §2.9 was already correct and left alone; the divergence is now pinned in §3.9 ¶351 and cross-referenced from §3.10 ¶363. Handoff 2 resolved: displacements recorded at ranks 13 (above 12 on quote and bind), 15 (to the foot of the bind ladder for the `REMOVE_AIRCRAFT` open-claim gate), 14 (below 15, narrowed to `REMOVED`, on investigation), 9 (below 15 / 18 / 17 depending on operation), 17 (above 12 on declaration acceptance); `notify_claim`, `settle_claim`, `create_endorsement` and `create_declaration` confirmed nominal-order. Handoffs 3 and 4 honoured — no formula paragraph and no §3.9 assessment-selection prose altered.

Also settled the count question: §4 endpoint table = **46** data rows (lines 379–424), §5 error table = **54** data rows (lines 432–485). Pass 2's reported 45/53 was an off-by-one counting artifact; no row was ever lost, and none was added or removed to make a number match.

### Pass 4 (reconciliation) — 11 targeted Edits

No `cp`. 485/143,803 → 485/146,291 (+2,488 bytes, 0 lines). No merge reduced content.

**Mandate A — §2.11 ladder end to end.** Read all 43 ranks, the closing paragraph and §2.10's two OCC paragraphs against every route module. Four defects, all products of blind concurrent editing, all fixed:
- rank 4 — Step 8 and pass 3 both touched it, leaving a resource list that named only transitive reach "through a schedule"; single-resource operator and policy reads are scope-checked directly and were missing, so rank 4 contradicted §2.1. Now one rule enumerating direct and transitive reach (`routes_registry.py:59`, `routes_policies.py:107`).
- rank 9 — pass 2 and pass 3 both edited it; the merged text said the displacement happens "on that last operation alone" and the next sentence then described it on two more. Rewritten as "the last of those three" / "the other two of the three" (`routes_claims.py:218`, `routes_fleet.py:332`, `routes_policies.py:287`).
- rank 14 — listed only the investigation displacement while §3.9 already described the coverage-decision ordering, so the ladder contradicted §3.9. Appended the coverage-decision displacement, including that it bites on `COVERED` only (`routes_claims.py:215,218,234`).
- rank 17 — rank 12 asserted that rank 17 records a displacement above it, and rank 17 recorded nothing. Added it, plus the resulting `ERR_DECLARATION_NOT_SUBMITTED`-over-`ERR_POLICY_NOT_BOUND` outcome (`routes_fleet.py:329,343`).
Verified coherent as inherited: displacement clauses at ranks 12, 13, 15, 18, 23, 27, 36, 43 (each states direction once and the directions agree pairwise); the §2.11 closing paragraph; §2.10's two paragraphs, which both name rank 19 and agree with rank 19's own text and with `routes_policies.py:255` / `routes_endorsements.py:384`.

**Mandate B — operator-scope story.** After the rank-4 fix, §2.1, §2.3, §2.11 rank 4 and §3.1 agree: the scope-checked single-resource reads are exactly operator, policy and their descendants; aircraft and pilot reads are unscoped; collection reads are narrowed, not refused. One genuine gap pinned — `notify_claim` scope-checks `policy_id` only, so a foreign `schedule_id` is not a scope violation but `ERR_SCHEDULE_POLICY_MISMATCH` at rank 33 (`routes_claims.py:31-33,56`).

**Mandate C — hull-loss populations.** Re-verified from source; §2.9, §3.9 and §3.10 already state the contrast explicitly and correctly and cannot be read as one population. Pass 3's pin is source-accurate; no change.

**Mandate D — the two deferred items, both now decided and pinned.** (1) `check_pattern` uses `re.match` with no `\Z` (`validate.py:130`), so a `$`-anchored pattern accepts one trailing newline; reachable because `aoc_number` and `registration_mark` have length ranges wide enough to absorb it, so a PRD-only implementer using a fully-anchored match would diverge on an input a test can send. Pinned in §3.1, including that a second trailing newline still fails and that `home_base_icao` cannot reach the leniency because its exactly-4 length rule runs first. (2) §3.4's blanket policy-version rule does exist and is general, but settlement is where a reader would most expect a policy touch (it re-derives two policy aggregates), so the local application was added at §3.10's point of use citing §3.4 as the general rule (`routes_claims.py:320-374` has `touch(rec)` and `touch(schedule)` and no `touch(policy)`).

**Mandate E — coherence sweep.** Three false universals and one broken count fixed: §3.5 "None of those four is terminal" was wrong — `WAIVED` is terminal, since no finding or logbook audit writes a schedule out of it (`routes_policies.py:292-310`, `routes_registry.py:187-197`); §3.10 "Five further conditions guard the payment" preceded a six-rank list (the numeral was inherited and only became self-contradictory when pass 3 added the list — numeral changed, list untouched); §3.3 "an expired policy refuses every write, whatever the operation" contradicted rank 12's own statement that endorsement voiding, declaration rejection and every claim-file action remain available, replaced with the rank-11/rank-12 framing plus the rank-14 route by which value revision and warranty findings actually fail; §3.7's companion sentence narrowed to "every write guarded by rank 12 of §2.11". A duplicate-sentence scan over all 717 sentences longer than 70 characters found exactly one hit — ranks 20 and 28 closing with the same sentence — deliberately left alone, since they are two distinct rules that happen to have the same true operation set and merging them would require restructuring the ladder.

### Step 9 net result

`workspace/PRD_COMPLETED.md` — 485 lines / 146,291 bytes, from `PRD_FINALIZED.md`'s 484 / 111,062. **+35,229 bytes (+31.7%), +1 line.** 58 ambiguity-pins and 19 mismatch-revisions across passes 1–3, plus 11 reconciliation edits in pass 4. Not byte-identical to its source (verified by `cmp` and by differing md5), so the scan demonstrably ran.

**Orchestrator final verification.** `wc`: PRD.md 484/109,733 → PRD_FINALIZED.md 484/111,062 → PRD_COMPLETED.md 485/146,291. `cmp` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md. Section structure preserved: 5 `##` and 21 `###` headings, same set and order as the source. §4 = 46 endpoint rows, §5 = 54 error rows. Last line is `| ERR_POLICY_HAS_NO_SCHEDULES | 409 |` — a real section boundary, not a truncation. Zero occurrences of "expert" or "difficulty" anywhere in the file. All 8 `workspace/implementation/results.$i.json` still on disk from the Step 7 final sweep, each reading `passed=218, total=218, failed=0`. Implementation module mtimes (06:15–06:31) predate Step 7's test fixes (07:19) and all of Step 9, confirming no Step 8 or Step 9 pass modified `implementation/` — consistent with Step 7 having made zero implementation fixes. No `workspace/test_helpers` or `workspace/test_suite` misplacement. Transient sweep artifacts (`sweep.sh`, `sweep.log`, `round.*.log`, `SWEEP_DONE`), all `__pycache__` directories and the whole `.scratch/` tree removed.

**Pipeline complete.** Step 9 has written `workspace/PRD_COMPLETED.md`.
