## Step 1: Create task directory — 2026-09-05T12:24:28.459550889Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2890_nutrient_trading_watershed_load_allocation and its workspace/ subdirectory. Index 2890 pre-assigned by the orchestrator prompt (no scan of ./tasks/ performed, to avoid collision with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T13:50:24.208923741Z

All three artifacts complete; scaffold-generator self-lint clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    49
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  782

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

| file | lines | bytes |
|---|---|---|
| SCAFFOLD.yaml | 2698 | 135866 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 1998 | 151611 |
| SCAFFOLD_CORNER_DESIGN.yaml | 3031 | 217081 |

**SCAFFOLD.yaml** — top-level keys exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no `scaffold_difficulty_design` / `scaffold_corner_design`). Scenario copied verbatim. Profile: primary archetype `quota_allocation`, secondary `compliance_audit`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, topology `graph`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, difficulty `beyond_expert`. Counts: **13 entities, 9 state machines, 2 OCC rules, 8 calculations, 30 ordered validations, 49 endpoints, 40 error codes, 7 roles.**

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single key `scaffold_difficulty_design`; all nine §0.5 rule ids at 2 instances each, **18 total**: `dual_variant_calc` 2, `combinatorial_formula` 2, `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 2, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2.

**SCAFFOLD_CORNER_DESIGN.yaml** — single key `scaffold_corner_design`; all 9 sections, **79 instances (46 with full `test_recipe`, 33 `excluded_because` stubs)**: entities 12 (11/1), state_machines 15 (9/6), calculations 15 (6/9), validations 17 (11/6), endpoints 7 (1/6), errors 2 (2/0), rbac 3 (3/0), cross_cutting_layers 7 (2/5), consistency_model 1 (1/0).

Verified programmatically: zero duplicate `name` values across the union of both design files, and every stub's `difficulty_instance` resolves to a real §1.8 instance name.

Notes on the final pass: `cross_cutting_layers` got real recipes for both §1.2.1 OCC rules (`stale_expected_tmdl_version_on_an_allocation_run_is_rejected` — the sole trigger of `ERR_STALE_TMDL_VERSION`, plus a re-read-and-retry success and a proof the refused call did not bump the version; and `credit_batch_version_advances_on_every_registry_write` — version 1→2→3 across certify/list/retire with a read that does not bump), with the cascade, dual-variant and threshold layers deferred to their §1.8 owners. `consistency_model` got one real `immediate` instance asserting the allocation run's four row families all agree on reads issued immediately after the write with no intervening mutation. One SCAFFOLD.yaml gap was closed along the way: §1.5 declared `GET /monitoring-samples/{monitoring_sample_id}` with no matching 404 code, so `ERR_MONITORING_SAMPLE_NOT_FOUND` was added (39 → 40 codes) and appended to validation priority 3.

Orchestrator note: the scaffold generator copied the difficulty directive line ("Generate task harder than expert level!") verbatim into SCAFFOLD.yaml's `scenario:` block. Per the pipeline contract that line must never reach PRD.md, so the orchestrator deleted that line (and its trailing blank) from SCAFFOLD.yaml before Step 4. Verified 0 remaining occurrences.

## Step 3: Copy shared files — 2026-09-05T13:50:24.220726121Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T14:01:18.993748278Z

PRD generated at workspace/PRD.md.

**Size:** 400 lines, ~13,400 words, 99 KB. Written in 6 incremental appends (initial Write + 5 heredocs + 1 generated table block) — no single giant Write.

**Section list**
- §1 Introduction (3 paragraphs — program context, the two-audience tension, conservatism rationale)
- §2 Global Specifications: 2.1 Program Actors and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination and Collection Ordering · 2.4 Resource Identity, Versioning and the Logical Program Clock · 2.5 Units, Precision and Rounding Discipline · 2.6 Path Resolution and Cross-Watershed Referential Integrity · 2.7 Stale-Parent Rejection on Registry and Allocation Writes · 2.8 The Order in Which Requests Are Rejected (all 30 validations, explicitly ordered) · 2.9 Load Conservation and Credit Mass Conservation · 2.10 Trading Gates and Program Suspension · 2.11 Segregation of Duties · 2.12 Cascade Discipline
- §3 Business Logic (9 subsections): 3.1 Watershed / Reaches / Monitoring · 3.2 TMDL Development and Revision Loop · 3.3 Source Inventory, Allocation Waterfall, Rescission · 3.4 Permit Issuance and Limit Derivation · 3.5 Annual Reporting and the Two Compliance Axes · 3.6 Producers, Practice Projects, Field Verification · 3.7 Certification, Serialization, Registry Operations · 3.8 Credit Purchase: Proposal, Settlement, Void · 3.9 Adaptive Management, Program Evaluation, Program Status
- §4 Endpoint Definitions (4-column table, 49 rows) · §5 Error Code Catalogue (2-column table, 40 rows)

**Coverage verification (machine-checked against SCAFFOLD.yaml, by the subagent)**

```
Field coverage check:
- entities[].fields: 136 required, 136 present, 0 missing
- endpoints[].request_body: 72 required, 72 present, 0 missing
- endpoints[].query_params: 26 required, 26 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 30 checked, 30 expressed in prose (§2.8 numbered 1–30 + scattered detail), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 9 machines / 44 transitions checked, 44 fully expressed, 0 missing
- calculations[]: 8 checked (incl. both dual-variant pairs), 8 fully expressed step-for-step, 0 missing
- validations[] conditions: 30 checked, 30 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 49 endpoints checked, expressed, 0 missing
- entities[].fields[] structured content: 13 entities checked, reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked, equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 909 · tokens starting with `/`: 0 · bare HTTP-method tokens: 0 · method+path combined: 0
Status: PASS
```

Additional checks: 40/40 error codes appear in §2/§3 narrative (not only in the §5 table); 49/49 endpoint paths present; all 7 role names and every state and enum value present verbatim; §2.2 byte-identical to `section-2.2-response-structure.md`; no fuzzy/approximating words remain; tail ends cleanly at the last §5 table row with no audit footer.

Two scaffold inconsistencies the generator resolved toward the authoritative source, and stated explicitly in the PRD: (1) the `watershed_program_status` endpoint note mentions a `PROGRAM_TERMINATED` void reason absent from the `void_reason` enum — the PRD follows the enum and the state machine, using `ADAPTIVE_HOLD` for both the suspension and the termination cascade; (2) the endpoints header comment says "44 endpoints" but the table contains 49, which is what the PRD documents.

Orchestrator verification (independent of the subagent, guarding the known silent-truncation failure): `wc -l -c` = 400 lines / 99,295 bytes; `tail` ends on a complete §5 table row (`| ERR_DELIVERY_BELOW_MINIMUM | 422 |`), a real section boundary, not mid-sentence. Re-ran coverage from SCAFFOLD.yaml with PyYAML: 40/40 error ids, 49/49 endpoint paths, 13/13 entity names, 7/7 role names all present in PRD.md — 0 missing in every category. Leak grep for "harder than expert"/"beyond_expert"/"test_recipe"/"SCAFFOLD" in PRD.md: 0 hits.

## Step 6: Generate implementation — 2026-09-05T14:31:46.860642870Z

Done. Final state verified.

## Implementation: task 2890 (Nutrient Trading & Watershed Load Allocation)

Location: `workspace/implementation/`

### Modules (15 files, 2,783 lines)

| File | Lines | Role |
|---|---|---|
| `app.py` | 75 | Flask app, blueprint registration, global request lock, error handlers, `__main__` runner |
| `store.py` | 207 | In-memory `Store` (13 dicts), logical clock, Decimal/rounding + row helpers |
| `errors.py` | 102 | `ApiError`, 40-code → HTTP status map, default messages, id-field → `*_NOT_FOUND` map |
| `envelope.py` | 60 | `meta`/`response_type`/`data` envelope, `req_<20>` ids, pagination meta |
| `validation.py` | 216 | Field spec engine (type/enum/range/decimal-width/pattern, unknown-field rejection), pagination + query args |
| `auth.py` | 41 | Header auth (401), 7 roles, `require()` → 403 |
| `calc.py` | 553 | All 8 calculations: sample load, effective background, allocation waterfall, rescind reversal, limit derivation + tiers, compliance reconciliation, delivery-path walk, batch minting, review evaluation |
| `cascade.py` | 115 | Transaction voiding, verified-ratio restatement, project revocation, watershed suspension/termination unwind |
| `common.py` | 64 | Resolution/404, serialization view, list responses, filters |
| `routes_program.py` | 342 | Clock, watersheds, program-status, reaches, monitoring samples, adaptive reviews |
| `routes_tmdl.py` | 263 | TMDL assessments + status machine, source assessments, allocation runs + rescind |
| `routes_permits.py` | 178 | Producers, permits, derive/finalize limits, annual report |
| `routes_market.py` | 553 | Practice projects, verification events, certify, credit batches (list/retire), credit transactions (propose/approve/void) |
| `start.sh` | 13 | Launcher (executable) |
| `requirements.txt` | 1 | `flask` |

### Coverage
- **49 endpoints** — the runtime `url_map` was diffed against the PRD §4 table (25 POST + 24 GET) and matches exactly, name for name. Note there is deliberately no `GET /watersheds` or `GET /producers` list route (the PRD defines neither), so those return 405.
- 13 entities, 9 state machines, both OCC fields (`expected_credit_batch_version` → `ERR_STALE_BATCH_VERSION`, `expected_tmdl_assessment_version` → `ERR_STALE_TMDL_VERSION`), 8 calculations, the 30-position global rejection ordering, 40 error codes, 7 roles.
- Storage is in-memory dicts only. A grep for `sqlite3`, file writes, `json.dump`, `pickle`, `shelve`, `/tmp/` across all modules returns nothing, and nothing is seeded: a fresh boot has zero rows and the clock at the default `2026-08-01T00:00:00.000Z`.

### start.sh
Confirmed: `cd`s to its own directory, ensures flask is importable, `export PORT="${PORT:-10000}"`, and `exec python3 app.py` — foreground, no background/daemon, so the harness's kill-and-relaunch per test works. `app.py` binds `host="0.0.0.0"` with `port=int(os.environ["PORT"])`; a fresh boot on random port 25836 showed `LISTEN 0.0.0.0:25836` and served requests, then released the port on `kill <pid>`.

### Smoke verification
Two task-scoped smoke suites under `/tmp/task_2890_impl/`. The second suite (60 assertions) passes 100%, covering: allocation waterfall (`point_pool 39900 / wla 39900 / la 26600 / reserve 3500`), tier-B derivation (`interim 44925`, schedule end `2029-06-01`), `ERR_ALLOCATION_RUN_IN_USE` on rescind-while-in-use, practice-period overlap vs. touching windows, acres-vs-enrolled rejection, segregation of duties, minting/serialization (`MD-BC02-2026`, serials 1–3000), a 3-reach delivery chain (`delivery_ratio 0.8000`, `path_reach_count 3`), settlement math, `REVERIFICATION PARTIAL` restatement (`verified_ratio 0.5` → `settled_gross 500`), `FAIL` → project `REVOKED` + batch `INVALIDATED` + transaction `VOIDED/BATCH_INVALIDATED` + permit `VIOLATION` with a permanent `enforcement_flag`, review-window conflict/separation, `OFF_TRACK` → `ADAPTIVE_HOLD`, and the `PROVISIONAL`→`FINAL` background variant switch from accepted samples.

The one failure noted earlier in the first suite (`path count: got 2 want 1`) was a bad expectation in the subagent's own smoke script, not an implementation defect: the generating reach and buyer reach were distinct rows, so `path_reach_count = 2` is correct per PRD §3.8. All smoke servers were killed by exact PID resolved from their own port; no broad `pkill` was used at any point, and neither `test_helpers/` nor `test_suite/` nor the difficulty/corner design files were read.

## Step 5: Generate unit tests — 2026-09-05T14:58:19.822638535Z

Stage 1 and Stage 2 are complete for task 2890.

## Output locations (verified)
Both at the **task root** — `test_helpers/` and `test_suite/`. Nothing named `test_helpers/` or `test_suite/` exists anywhere under `workspace/` (workspace holds only `INSTRUCTION.md`, `PRD.md`, `sweep.sh`, `implementation/`). `__pycache__` dirs removed.

## Files written (line counts)
`test_helpers/`: `__init__.py` 21, `api_client.py` 269, `api_errors.py` 102, `assertions.py` 289, `constants.py` 69, `factories.py` 339, `fixtures.py` 659, `test_users.py` 140, `types.py` 105.

`test_suite/`: `conftest.py` 26, `test_01_dual_variant_arithmetic.py` 189, `test_02_combinatorial_formulas.py` 222, `test_03_non_linear_state_machines.py` 145, `test_04_transitive_cascades.py` 190, `test_05_validation_priority_pairs.py` 170, `test_06_boundary_precision.py` 236, `test_07_cross_entity_state_dependencies.py` 149, `test_08_resource_temporal_overlap.py` 262, `test_09_compensating_invariants.py` 255, `test_10_entities.py` 449, `test_11_state_machines.py` 382, `test_12_calculations.py` 377, `test_13_validations.py` 687, `test_14_endpoints.py` 70, `test_15_errors.py` 102, `test_16_rbac.py` 216, `test_17_cross_cutting_layers.py` 133, `test_18_consistency_model.py` 88. Total 6341 lines.

## Tests emitted: 82 (all collected by pytest: `82 tests collected`)

## Instance coverage — 64/64, zero SKIPs
- **Queue A (§1.8 difficulty): 18/18 instances → 36 tests** (exactly 2 per instance, all nine rule_ids: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- **Queue B (§1.9 corner): 46/46 non-stub instances → 46 tests** — entities 11, state_machines 9, calculations 6, validations 11, endpoints 1, errors 2, rbac 3, cross_cutting_layers 2, consistency_model 1. Scripted audit confirms: 82 `Design:` tags, one per test, zero dangling tags, zero tags pointing at an `excluded_because` stub, and every one of the 46 non-stub instances covered.
- No `skip`/`skipif`/`xfail` anywhere; pyflakes clean except the deliberate side-effect import in `conftest.py` (already carries `# noqa: F401`; it registers the error→HTTP status map).

## PRD-over-design-index corrections carried through (worth flagging to the implementation side)
1. **`INTERIM`**, not the index's `INTERIM_LIMITS`, is the `limit_status` after derive-limits (PRD §3.4).
2. **Certification's `residual_lbs` is added to `reserve_pool_lbs`** (PRD §3.7); the indices omit it. Every post-certification pool figure therefore ends in `.40` for the canonical 520.40-lb batch: 2400.40, 2450.40, 2500.40, 2520.40, 2920.40, 2420.40. Eight assertions in `test_01`, `test_09` and `test_11` were patched to match.
3. **A partially retired LISTED batch stays `LISTED`** (PRD §3.7 "leaves the batch's `status` unchanged"); the index said `ISSUED`.
4. The RBAC clock test asserts the shared-role acceptance plus the clock's *effect* (a later write's `created_at`) rather than the index's `data.current_utc` echo, which the PRD never pins.

Orchestrator note on concurrency: Steps 5 and 6 were launched back-to-back rather than in a single assistant message, so the impl generator did not get physical isolation from `test_suite/` by non-existence. Compensating control: the Step 6 prompt carried an absolute prohibition on reading/listing/globbing/grepping `test_helpers/`, `test_suite/`, and both design YAMLs at any point even if present on disk, and Step 6 reported in its summary that it read none of them. Both directories landed at the task root (the known misplacement failure did not occur).

## Step 7: Run tests and iterate — 2026-09-05T15:19:26.360865447Z

Done. All 8 rounds green at 82/82.

## Summary

**Iterations run:** 2 sweeps (iteration 1 diagnosed 4 deterministic failures; iteration 2 verified the fixes).

Iteration 1 was 78/82 in **all 8 rounds** with the identical 4 failures — fully deterministic, no flakiness and no load-induced noise anywhere in the sweep. All 4 turned out to be test-artifact defects; the implementation needed no changes.

**Tests deleted:** none. Two individual *assertions* were removed under the STEP 1c partial-coverage rule (the enclosing tests were kept, since the rest of both traces verbatim to PRD):

- `test_07_cross_entity_state_dependencies.py` — removed `assert_is_null(batch["listed_at"])` and `assert_instant_equals(listed["listed_at"], CLOCK_BASE)`. **PRD-silence category: computed/response-field silence.** `listed_at` has zero occurrences in PRD.md. §2.4 enumerates every server-written timestamp exhaustively (`created_at`, `updated_at`, `observed_at`, `approved_at`, `certified_at`, `rescinded_at`, `voided_at`, `finalized_at`) and `listed_at` is not among them; §3.7's listing sentence specifies only the status move, that buckets are untouched, and the version bump. A PRD-faithful implementer would never mint the field. The surviving assertions (the `ERR_PROJECT_NOT_CERTIFIED` rejection, `status`, all four balance buckets, `verified_ratio`, `issued_lbs` never restated) all quote PRD directly.

**Fixes applied to `test_helpers/`:** none needed — the helper layer (money as JSON numbers, instant-vs-calendar-date discipline, `canonical_instant` folding, single-unwrap convention, `""` blank auth headers) was already correct on every known-hazard axis.

**Fixes applied to `test_suite/`:**
- `test_10_entities.py::test_a_verification_event_carries_no_version_and_no_updated_at` — asserted field `verifier_user_id`; PRD §2.1 and §3.6 both name it **`inspector_user_id`** ("a verification event records the acting verifier in `inspector_user_id`"). Assertion mis-translation; renamed to the PRD's field, which makes the test *more* faithful. The implementation already stamps `inspector_user_id` correctly (`routes_market.py:260`).
- `test_13_validations.py::test_only_the_recorded_permittee_may_file_the_annual_report` — asserted `compliance_gap_lbs` is null on a freshly created permit, but PRD §3.4 states verbatim that a new permit opens with "`compliance_gap_lbs` at 0.00", placing it in the zero group, not the null group (`reported_annual_load_lbs`, which the same test correctly asserts as null, *is* in the null group). Changed to `assert_load(..., 0.00)`.

**Fixes applied to `implementation/`:** **none.** No endpoint, field, side effect, or check was added, removed, or weakened. On both contested field names the implementation was already the PRD-faithful side of the discrepancy.

**Final per-round results (sweep 2):**

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Passed/Total | 82/82 | 82/82 | 82/82 | 82/82 | 82/82 | 82/82 | 82/82 | 82/82 |

0 failed, 0 errors, empty failing union across all 8 rounds. `worklog.md` was not touched, no test directories drifted into `workspace/`, and the `/tmp/task_2890_step7/` scratch dir has been cleaned up.

Orchestrator verification: independently re-read all 8 `workspace/implementation/results.*.json` files with a fresh json parse — every one reports `passed 82 / total 82`, so the clean sweep artifacts are really on disk (not merely claimed).

## Step 8: Finalize PRD — 2026-09-05T15:27:26.561919586Z

## Result

`PRD_FINALIZED.md` created and is **byte-identical** to `PRD.md`.

- **Line counts:** 400 / 400 lines, 99295 / 99295 bytes — **0.00% delta**. Same md5 (`0ed373f9…`).
- **Changes:** none. All three `<step_7_diff>` items were pure test-artifact defects against a PRD that already uniquely determines the behavior, and `implementation/` already matches that PRD wording exactly. Per the "do not manufacture edits" instruction, nothing was patched.

## Per-item verification (the three candidates)

**1. `listed_at` — assertions removed from `test_07_cross_entity_state_dependencies.py`. No edit.**
- (a) Subject: any timestamp field written on the credit-batch listing path.
- (b) Paths enumerated: `grep -rn "listed_at" implementation/*.py` → **zero occurrences anywhere in the implementation**. Read the listing endpoint `routes_market.py:334-351` (`list_credit_batch_onto_market`): it writes only `batch["status"] = "LISTED"` then `touch(batch, touched())`. Read `touch` at `store.py:179-190` — it bumps `version` and refreshes `updated_at` only; `new_row` (`store.py:167-176`) mints only `created_at`/`updated_at`/`version`. So the field the test asserted **does not exist in the implementation at all**.
- PRD §3.7 (line 265) already describes exactly what impl does: status move `ISSUED → LISTED`, "leaving every bucket amount untouched", `version` +1; §2.4 (line 80) covers `created_at`/`updated_at`/`version` generically. PRD is not *silent in a way impl fills in* — impl mints nothing, so there is nothing to pin. Adding a "no `listed_at` is written" sentence would be new invented prose about a nonexistent field.
- (c) Wording adjustment: n/a (no edit).

**2. `inspector_user_id` vs `verifier_user_id` — `test_10_entities.py` assertion renamed. No edit.**
- (a) Subject: the field name recording the acting verifier on a VerificationEvent, plus the neighbouring verifier-identity fields it could be confused with.
- (b) Paths enumerated: `grep -rn "inspector_user_id\|verifier_user_id" implementation/` → `routes_market.py:260` (`inspector_user_id=g.user_id` on the verification-event row, created with `versioned=False` at `:254`), and the *separate* project-level fields `baseline_verifier_user_id` / `implementation_verifier_user_id` at `routes_market.py:143-144` (init to null), `:230-231` (segregation-of-duties check), `:238`, `:241` (writes), `:298-299` (certification segregation check). Two distinct field families, and the impl keeps them distinct.
- PRD already names all three correctly and in the same split: line 19 ("a verification event records the acting verifier in `inspector_user_id`… a practice project retains `baseline_verifier_user_id` and `implementation_verifier_user_id`"), line 247 ("The server stamps `inspector_user_id` from the acting `X-User-ID`"), lines 245/249/251/259 for the project-level pair. The implementation was the PRD-faithful side; the test was mis-translated.
- (c) Wording adjustment: n/a (no edit).

**3. `compliance_gap_lbs` on a fresh permit — `test_13_validations.py` changed from null to 0.00. No edit.**
- (a) Subject: the initial value of `compliance_gap_lbs` at permit creation, and every later writer of that field.
- (b) Paths enumerated: `routes_permits.py:99-102` — creation sets `reported_annual_load_lbs=None` and `compliance_gap_lbs=ZERO2` (`0.00`, `store.py:160`); `routes_permits.py:155,166,175` (annual-report write path); `calc.py:368`, `calc.py:380-398` (`reconcile`: gap forced to `ZERO2` when `reported` is null, else computed and floored); `routes_market.py:444` and `:496` (`ERR_NO_COMPLIANCE_GAP` gate on proposal and approval, both reading `dec(permit["compliance_gap_lbs"]) <= 0`). All presume a non-null numeric gap, consistent with a `0.00` initial value.
- PRD §3.4 line 211 states verbatim that a new permit opens with "`compliance_gap_lbs` at 0.00" while listing `reported_annual_load_lbs` among the null fields — exactly the impl's split. Lines 229/231/233/235/281/283/297 already cover every recompute path.
- (c) Wording adjustment: n/a (no edit).

## Notes
- Step 7 applied zero implementation fixes, and on both contested field names the implementation was already the PRD-conformant side, so an identical `PRD_FINALIZED.md` is the correct outcome here.
- One observation handed to Step 9, **not acted on** because it traces to no Step 7 item: in `routes_market.py:340-347` the listing checks fire in the order `ERR_INVALID_STATE` → `ERR_TRADING_SUSPENDED` → `ERR_PROJECT_NOT_CERTIFIED` → `ERR_CREDIT_INSUFFICIENT`, whereas PRD line 265 narrates certified-before-suspended. Step 7 never exercised that precedence pair, so it was outside Step 8's hard scope.
- The subagent did not read `SCAFFOLD*.yaml` or `worklog.md`, and touched no other file.

## Step 9: Complete PRD — 2026-09-05T15:55:36.792424843Z

Run as three SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place). Partition: pass 1 = cross-cutting modules (app/envelope/auth/errors/validation/store/common), pass 2 = calc.py + cascade.py, pass 3 = the four routes_*.py modules. All edits made surgically with Edit, never a whole-file Write.

**Totals: 42 changes — 29 ambiguity-pins, 13 mismatch-revisions. 400 lines / 99,295 chars → 401 lines / 114,225 chars (+14,930 chars, +15.0%).**

### Pass 1 — cross-cutting modules (13 changes: 12 ambiguity-pins, 1 mismatch-revision; 99,295 → 103,760 chars)
- §5 preamble + table — insert/revise — mismatch — `ERR_VERIFICATION_EVENT_NOT_FOUND` (404) was absent from the catalogue although impl raises it; added the row (41 rows now, matching `errors.ERROR_STATUS` exactly), and qualified the preamble to note the two routing-level responses outside the catalogue — errors.py:28, common.py:19
- §2.6 — revise — mismatch — the verification-event unknown-identifier 404 now names `ERR_VERIFICATION_EVENT_NOT_FOUND` — errors.py:28
- §2.6 — insert — ambiguity — routing precedes all §2.8 checks: unmatched path → `ERR_NOT_FOUND` 404, undeclared method on a matched path → `ERR_INVALID_REQUEST` **405** (not 422), neither consulting auth headers; trailing slash accepted — app.py:52-60, app.py:21
- §2.8 item 4 — insert — ambiguity — internal order of the shape step: raw JSON read regardless of `Content-Type`, absent/empty body ≡ `{}`, non-object body rejected → unknown-field rejection → declared fields in declaration order, each presence → type → enum/pattern → decimal width → range — validation.py:52-63, 143-161, 66-85
- §2.8 item 4 — insert — ambiguity — explicit `null` treated as absent (rejected if required, takes default if optional) — validation.py:154-158
- §2.8 item 4 — insert — ambiguity — pattern-less string fields accept any string incl. `""`; bool/int mutually exclusive (`true` is not an int, `1` is not a bool) — validation.py:88-120
- §2.8 item 4 — insert — ambiguity — an endpoint declaring no request body ignores any body sent — validation.py:143
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected 422; `offset` ≥ `total_count` is an empty page, not an error; undeclared query params ignored; non-collection endpoints ignore query params entirely — validation.py:171-188, 213-216
- §2.3 — insert — ambiguity — enum-domain filters reject out-of-enumeration values 422 rather than returning an empty page; `vintage_year`/`reporting_period_year` reject non-integers; filter checks precede `limit`/`offset`; id/code filters are unresolved and yield empty pages — validation.py:191-210, common.py:41-64
- §2.3 — insert — ambiguity — row-creation sequence is the final tie-break for the default `created_at` ordering and all four domain orderings (load-bearing because the frozen logical clock makes `created_at` ties the norm) — store.py:197-202
- §2.4 — revise — ambiguity — `updated_at` equals `created_at` at creation — store.py:167-176
- §2.4 — insert — ambiguity — client-supplied instants (`current_utc`, `sample_datetime` only) accepted with or without offset, no-offset read as UTC, parsed instant drives clock/ordering, but the field is echoed back verbatim rather than canonicalised — store.py:74-102, validation.py:129-132
- §2.5 — insert — ambiguity — every quantity travels as a JSON number, never a string; declared decimal-place counts bound submitted precision, not the JSON type — envelope.py:10-17, validation.py:66-85
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`–`Z`/`0`–`9` — store.py:205-207
- §2.1 — insert — ambiguity — trimmed header values are what the server records and compares, so whitespace never enters an ownership comparison — auth.py:25-32, routes_permits.py:170
- §2.12 — insert — ambiguity — requests processed strictly one at a time (global lock), all §2.8 checks precede any write so a rejected request mutates nothing, and a successful write is fully visible to the next request — app.py:28-44

Pass 1 verified-already-pinned (no change): envelope success/error shapes and `response_type`, error `meta` limited to the two request fields, 201-on-create; pagination meta semantics; all 7 role names and the 401-before-403 discipline incl. missing/whitespace-empty/unknown-role all 401; all 40 pre-existing error ids' HTTP statuses verified 1:1 against `ERROR_STATUS`; the left-to-right path-id 404 chain and per-type 404 codes incl. `downstream_reach_id` → `ERR_REACH_NOT_FOUND`; bare-UUID ids, 3-fraction-digit timestamps, `version` starting at 1 with one bump per request incl. cascade-induced, default clock `2026-08-01T00:00:00Z`; half-away-from-zero rounding at 2dp/4dp; conjunctive filters and the four domain orderings.

### Pass 2 — calc.py + cascade.py (13 changes: 10 ambiguity-pins, 3 mismatch-revisions; 103,760 → 108,012 chars)
- §3.1 — revise — mismatch — `allocated_wla_total_lbs_yr` / `allocated_la_total_lbs_yr` are *stamped* from the last run created/rescinded on the watershed, not recomputed over the `ACTIVE` run; rescinding one assessment's run zeroes both even if another assessment still holds an `ACTIVE` run — calc.py:229-230, 281-282
- §3.3 step one — insert — ambiguity — `PROVISIONAL` also covers `WITHDRAWN`/`SUPERSEDED` parents (run creation is not status-gated); `APPROVED` is the only status selecting `FINAL` — calc.py:107-116, routes_tmdl.py:211-228
- §3.3 step five — insert — ambiguity — group ordering's final tie-break is row-creation sequence when existing load and `created_at` are both equal — calc.py:130
- §3.3 allocations array — insert — ambiguity — published `weight` is rounded half-up to 4 dp, while the denominator and each quotient use the exact unrounded weight — calc.py:186-204
- §3.3 step seven — insert — ambiguity — a superseded run keeps its totals/array; only the new included set is rewritten, so a source since moved to `EXCLUDED` keeps its stale `allocated_load_lbs_yr` and `allocation_run_id` pointing at the `SUPERSEDED` run — calc.py:188-197, 215-221
- §3.4 step five — insert — ambiguity — 29 Feb + 3 or 5 years lands on 28 Feb (leap-day fallback) — store.py:128-133 via calc.py:313
- §3.4 applicable limit — revise — mismatch — the *stored* field is a materialised copy re-derived on derive/finalize/reconcile and whenever the permit's need is evaluated, never bumping `version` — calc.py:327-341, 365-376 (superseded by pass 3's finding below, which is the final wording)
- §3.5 reconciliation — revise — mismatch — gap 0.00 under finalize/release-void leaves the posture untouched; gap 0.00 under an invalidated-batch void promotes only from `SHORTFALL`; invalidated-batch void with gap > 0 sets `VIOLATION` regardless of prior posture; a permit already in `VIOLATION` is never walked back to `SHORTFALL` — calc.py:400-421
- §3.5 axis-crossing — insert — ambiguity — finalization also moves `RESOLVED → SHORTFALL`, not just `IN_COMPLIANCE → SHORTFALL` — calc.py:419-420
- §3.7 minting — revise — ambiguity — "rounded down to the next lower whole number" restated as "largest whole number not exceeding it", so an exactly whole gross keeps its value and `residual_lbs` is 0.00 — calc.py:485
- §3.8 void — insert — ambiguity — voiding a `PROPOSED` transaction leaves the buyer permit wholly untouched (no reconciliation, no `version` bump) — cascade.py:41-47
- §3.9 evaluation — insert — ambiguity — zero divisor (baseline == approved capacity): `sample_count` and `observed_load_lbs_yr` still written, `achieved_reduction_pct` null, verdict `INDETERMINATE` — calc.py:548-550

Pass 2 verified-already-pinned (no change): sample-load single 2 dp rounding computed for every `qa_status`; background mean with ACCEPTED-only closed-window semantics and empty-set fallback; MOS/allocable with `ERR_ALLOCABLE_LOAD_NEGATIVE` before any write and exactly-0.00 accepted; 5% set-aside, 60/40 pools, per-source rounding before summation, zero-denominator group → 0.00, reserve as balancing residue; run→assessment roll-up copy set; rescission write order and field-by-field reset; `required_reduction_pct` flooring and the 20.00/50.00 inclusive-upper tier boundaries against the rounded pct; relief 0/0.25/0.50 and 0/3/5 years; interim-limit formula; `credit_applied_lbs` as a materialised sum over `APPROVED` transactions; gap floor at zero; sticky `enforcement_flag`; the delivery walk (self-reach 1.0000/1, generating reach's own factor excluded, ten-reach depth guard, single 4 dp rounding, no-downstream → `ERR_ZONE_NOT_ELIGIBLE`); gross-reduction proration by verified acres; serial prefix/range/high-water counter; bucket open values and `verified_ratio` 1.0000; residual → reserve pool; `ON_TRACK` inclusive threshold; all cascade void writes and reason codes; the three-origin reason-code split; approved-void bucket moves and reserve debit; `applied_lbs` never rewritten; verified-ratio restatement limited to `ISSUED`/`LISTED` with `issued_lbs` never restated; revocation link order and the `invalidated_lbs` fold; watershed unwind selecting by buyer-permit watershed with reason `ADAPTIVE_HOLD`.

### Pass 3 — the four routes_*.py modules (16 changes: 10 ambiguity-pins, 6 mismatch-revisions; 108,012 → 114,225 chars)
- §2.4 — insert — ambiguity — the clock endpoint creates no row and answers 200 with a `data` object whose sole member is the echoed `current_utc` — routes_program.py:43-49
- §2.8 step 4 — insert — ambiguity — cross-field `ERR_INVALID_REQUEST` checks (period ordering, post<pre, `verified_acres` required/forbidden/bounded) belong to step 4, ahead of steps 5/6 ownership and step 7 body-id resolution; row-dependent ones fire the instant that row resolves — routes_tmdl.py:62, routes_market.py:99-104 & 203-219
- §3.2 — revise — mismatch — per-transition role attributions are not enforced; either `TmdlAnalyst` or `ProgramAdministrator` may drive any of the seven transitions, approval included — routes_tmdl.py:112
- §3.2 — insert — ambiguity — `target_status` accepts all six statuses at shape level; self-transition, `SUPERSEDED`, or any target out of a terminal status is `ERR_INVALID_STATE`; the missing-inventory publish gate is `ERR_INVALID_STATE` (not `ERR_NO_INCLUDED_SOURCES`), inside step 11 after transition legality — routes_tmdl.py:116-126
- §3.2 — revise — mismatch — approval writes only `status`, `approved_at`, `version`; it does not recopy the active run's totals — routes_tmdl.py:133-149
- §3.2 — insert — ambiguity — a draft opens with `approved_at` null — routes_tmdl.py:88
- §3.3 — insert — ambiguity — source inventorying is not gated on the parent assessment's status — routes_tmdl.py:169-172
- §3.4 — revise — mismatch — `applicable_limit_lbs_yr` is also re-derived on every serialization of a permit row, so a plain read is never stale (this supersedes pass 2's narrower wording) — common.py:29-32 as reached by routes_permits.py:109-124
- §3.7 — revise — mismatch — batch-listing precedence rewritten to impl order: `ERR_INVALID_STATE` → `ERR_TRADING_SUSPENDED` → `ERR_PROJECT_NOT_CERTIFIED` → `ERR_CREDIT_INSUFFICIENT` — routes_market.py:340-347
- §3.7 — insert — ambiguity — `retire_lbs` of exactly 0.00 is accepted, bumps both versions, and flips a zero-balance batch to `RETIRED` — routes_market.py:360, 369-377
- §3.8 — insert — ambiguity — batch `status` and project status are not proposal preconditions (only approval ones); an `ISSUED` batch is proposable — routes_market.py:404-449
- §3.8 — revise — mismatch — geography is evaluated ahead of the balance and gap checks (position 18 vs 28/29), not "next" after them — routes_market.py:438-445
- §3.8 — insert — ambiguity — approval overwrites `retired_to_reserve_lbs` but never restates `requested_gross_lbs`, `tradable_lbs`, `proposed_delivered_lbs`, `permit_gap_at_proposal_lbs`, `delivery_ratio`, `path_reach_count` — routes_market.py:501-513
- §3.6 — insert — ambiguity — no reverification outcome restates the project's own `verified_acres`; it stays the implementation-finding value for the project's life — routes_market.py:236-248
- §3.9 — insert — ambiguity — the OFF_TRACK void cascade runs regardless of `program_status`, including on a watershed already in `ADAPTIVE_HOLD` or `TERMINATED` — routes_program.py:321-324
- §3.9 — insert — ambiguity — watershed `target_status` accepts all four statuses; `PROVISIONAL`, self-transitions, and anything from `PROVISIONAL`/`TERMINATED` are `ERR_INVALID_STATE`; `reason` is not persisted — routes_program.py:110-131

**Verdict on the Step 8 listing-precedence lead:** the implementation is not wrong and does not conflict with §2.8 — `routes_market.py:340-347` follows §2.8's numbering exactly (11 → 12 → 20 → 28). The defect was purely in §3.7's narration, which introduced the certified gate before the suspension gate and read as a sequence. Pass 3 reordered that sentence to the implementation's order and added the disambiguating consequence (suspended + non-certified reports `ERR_TRADING_SUSPENDED`). No change to §2.8 items 12 or 20 was needed. The same narration shape at certify (§3.7 lists segregation before suspension) also follows §2.8 (12 before 14) and is already resolved by §2.8's explicit normativity plus the note at line 143, so it was left alone.

Pass 3 verified-already-pinned (all 49 endpoints walked): every GET's authorized-role list matched §4 exactly, plus every filter set, enum-filter rejection, and the four domain orderings with their tie-breaks; watershed creation defaults and `ERR_DUPLICATE_CODE`; the four watershed transitions and which two run the unwind; reach creation's resolve→mismatch→duplicate order and `delivery_factor` bounds; monitoring-sample immutability; adaptive-review clear-day conflict rule and the finalize `ERR_INVALID_STATE`→`ERR_TMDL_NOT_APPROVED` order with a single watershed version bump; assessment draft init and per-watershed code uniqueness; the seven-member transition set, `revision_round` increment, supersession of other APPROVED assessments and PROVISIONAL→ACTIVE activation; source-assessment resolve order and `ERR_WATERSHED_MISMATCH`; allocation-run stale→no-sources→allocable-negative order; rescission's ACTIVE-only gate and `ERR_ALLOCATION_RUN_IN_USE` predicate; producer creation (no uniqueness, no email format); permit creation mismatch→duplicate→not-POINT order and null init; derive-limits and finalize-limits gate orders; annual-report ownership→`ERR_LIMITS_NOT_DERIVED` order; practice-project ownership→resolve→overlap→zone order with the half-open overlap rule; the verification-event transition table incl. the absent BASELINE/PARTIAL and IMPLEMENTATION/PARTIAL combos and segregation on both IMPLEMENTATION outcomes; certify's order and 201-with-batch; retire's `ERR_BATCH_HAS_OPEN_TRANSACTIONS` (PROPOSED only) placement; propose's full 8→10→12→17→18→28→29→30 chain with the permit left untouched; approve's three `ERR_INVALID_STATE` gates and three-place settlement; void's `REGISTRY_ACTION` reason with no trading gate.

### Orchestrator verification
`wc -l -c`: PRD.md 400/99,295 · PRD_FINALIZED.md 400/99,295 · PRD_COMPLETED.md 401/114,225. md5 of PRD_COMPLETED.md (`f78ea3c3…`) differs from PRD_FINALIZED.md (`0ed373f9…`), so the scan demonstrably ran rather than passing the file through untouched. Tail still ends on the last §5 error-table row (`| ERR_DELIVERY_BELOW_MINIMUM | 422 |`) — a real section boundary, not mid-sentence — and all 29 markdown headings survive. Cross-pass anchors confirmed present in the final file (`ERR_VERIFICATION_EVENT_NOT_FOUND` from pass 1, the `INDETERMINATE` zero-divisor sentence from pass 2). No re-sweep was needed: Steps 8 and 9 touched only PRD_*.md, leaving `implementation/` and `test_suite/` byte-unchanged since the green 8-round sweep, whose `results.1..8.json` (82/82 each) remain on disk.

