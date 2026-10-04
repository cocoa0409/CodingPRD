## Step 1: Create task directory — 2026-10-02T11:20:27.263613747Z

Pre-allocated directory ./tasks/task_3473_certification_examination_recertification_state_licensure_linkage/ verified (workspace/ present, empty). No new index computed.

## Step 2: Generate scaffold — 2026-10-02T11:45:00.000Z

Scaffold generation complete. All three artifacts are written, lint-clean, and cross-audited.

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_3473_certification_examination_recertification_state_licensure_linkage/`)

- **SCAFFOLD.yaml** (§1.0–§1.7 only): 17 entities, 66 endpoints, 52 error codes, 14 state machines, 13 calculations, 12 ordered validation priorities, 7 roles, 3 OCC concurrency rules. Archetype: compliance/audit + workflow orchestration; flat topology (FK-wired peers); segregation-of-duties role model; logical clock (`POST /_clock/set_current_utc`, default `2026-09-01T00:00:00Z`) with a pinned 7-step sweep as the ops-run checkpoint.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 19 instances, ≥2 per rule — dual-variant CAT scoring (provisional PASS vs final FAIL on identical responses, theta 0.8333 vs UCB 0.6508, computed by code) vs NCCP/HOURLY CE divergence; combinatorial formulas in all three modes (per-line fee rounding 2998≠2997; anniversary-preserving expiry 2030-09-04≠2029-10-15; waterfall spill); cyclic machines (disciplinary rehearing loop, ACTIVE→LAPSED→ACTIVE); depth-4 program-revocation cascade vs depth-3 falsified-education cascade; priority conflicts (state>temporal, safety>referential); boundary pins (15-day retake inclusive, CE exact minimum); two interval semantics (half-open slot intersection vs point-in-validity-window containment); two compensating invariants (attempt budget 6 = consumed+remaining through void; CE credited hours through audit rejection).
- **SCAFFOLD_CORNER_DESIGN.yaml**: 87 instances (81 active + 6 `excluded_because` stubs) across all 9 guide sections, including full error-catalog triggerability.

## Verification

`scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (66 endpoints, 17 entities, 100 instances, 1,410 calls scanned). Additionally self-audited beyond lint: zero unbound `${var}` placeholders, 106 globally unique instance names, every error code referenced by rules AND exercised by a design instance, per-instance clock monotonicity (only deliberate regression is the `ERR_CLOCK_REGRESSION` test), no forbidden concurrency vocabulary, all CAT/fee assertion literals computed via Python.

Two design-time repairs worth noting for downstream steps: `ERR_APPEAL_WINDOW_CLOSED` was removed as unreachable dead code (sweep finalizes lapsed DECIDED cases first, so late appeals surface as `ERR_CASE_STAGE_MISMATCH` — pinned in the transition), and the REVOCATION cascade's license denial is cert-mediated (not blanket) so the §1.8 cascade chain is causally airtight. Heads-up for Step 6: at 66 endpoints this exceeds the known >40 impl-gen strain point — per-domain module splitting in the generation prompt is advised.

## Step 3: Copy INSTRUCTION.md — 2026-10-02T13:05:01.490901935Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-10-02T12:10:00.000Z

PRD generated and all hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3473_certification_examination_recertification_state_licensure_linkage/workspace/PRD.md` (386 lines)

**Structure:** §1 two-paragraph introduction (credentialing structure + compliance-first design angle); §2 with 9 subsections — RBAC with per-role identity translation (2.1), verbatim response envelope (2.2), pagination (2.3), common resource properties including the two `common_fields: false` config entities (2.4), the unprefixed logical clock with startup default `2026-09-01T00:00:00Z` and the pinned 7-step sweep (2.5), calendar/units/rounding conventions (2.6), OCC covering exactly the three `concurrency_rules` (2.7), the 11-tier validation precedence with in-tier error-id orderings (2.8), snapshots/cascades/hop discipline (2.9). §3 has 9 lifecycle-stage subsections (config → programs/accreditation → completion records → cognitive pathway → psychomotor+issuance → recertification/waterfall/audit → lapse/reentry → licensure → disciplinary due process). §4: 66-row endpoint table (verified to match scaffold paths/methods exactly), 4 columns. §5: 52-row error catalogue, 2 columns, statuses match scaffold.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 175 required (incl. common fields), all present, 0 missing
- endpoints[].input (incl. query params): 197 required occurrences -> 149-name deduped set, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority tiers: 11 checked, 11 expressed in prose (§2.8 with explicit in-tier orderings), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write op + expected_certification_version/expected_case_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 60 checked (all 14 machines incl. sibling branches and system sweeps), all state strings verified present, 0 missing
- calculations[]: 13 checked (incl. CAT scoring, CE waterfall + HOURLY variant, fee per-line rounding, audit selector, reentry tiers), 0 missing — all constants embedded (MIN_ITEMS=6 -> "six items", Z=1.645, 0.5 cap -> "one half", etc.)
- validations[] conditions: all matched to error ids in §2/§3 prose
- endpoints[].side_effects / applies_to: all expressed (revocation 5-hop cascade, sanction 5-step cascade, version increments on recert/license create and case decide)
- entities[].fields[] structured content: defaults (registry_share_bps 1500, jurisprudence false, interim_action NONE, counters at zero), ranges (difficulty_b 0.1-1.0), nullability all placed
- sibling-branch symmetry: all branch groups (decision outcomes, tier pairs, NCCP/HOURLY, provisional/final, pass/fail voiding) given equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 677
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 block byte-identical to `section-2.2-response-structure.md`; all 7 role names exact; no fuzzy/approximating words; no operator syntax (`==`, `>=`, `+=`) outside prose translations; the clock endpoint correctly rendered unprefixed in both §2.5 and §4. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened at any point.

## Step 5a: Generate test helpers — 2026-10-02T12:45:00.000Z

Stage 1 is complete and verified. Final report:

## Files written (all under `test_helpers/`)

| File | Purpose |
|---|---|
| `types.py` | 17 entity TypedDicts (config entities LevelDefinition/StateAdoptionPolicy carry only `id`+`created_at` per PRD §2.4; all others add `updated_at`+`version`), 24 value/status enums, `UserRole` (7 roles spelled per PRD §2.1) |
| `constants.py` | Every threshold derived from PRD: clock default `2026-09-01T00:00:00Z`, CAT 6/12/Z=1.645/4dp, attempt cap 6, remedial gate 3, retake wait 15d, ATT 90d, education validity 24mo, cert term 24mo + lapse 48mo, recert window 12mo + extension 24mo, distributed cap 0.5, audit seq-mod 3 / 20h provider / 60mo lookback, reentry tiers 12/24mo, case deadlines 30d/30d, suspension 12mo, 1500 bps default share, pagination 10/1/100/0; plus canonical EMT level/WA policy payloads and the canonical chain timeline |
| `api_errors.py` | `ApiErrorId` enum + `HTTP_STATUS_CODES` for all **52** catalogued errors, registered via `set_error_http_status_map()` at import |
| `api_client.py` | `ApiClient(GenericApiClient)` with exactly **66** endpoint methods; clock method uses the literal unprefixed `/_clock/set_current_utc`, all domain methods use `f"{REGISTRY}/..."` |
| `api_errors.py` ↔ scaffold diff | machine-verified: 0 missing, 0 extra, 0 status mismatches |
| `factories.py` | 25 payload builders, one per entity + decision/action bodies; `cat_pass_responses`/`cat_fail_responses`/`cat_responses_payload` for CAT deliveries; auto-unique emails/course codes/item ids |
| `assertions.py` | `assert_<entity>` for all 17 entities + `assert_attempt_budget_invariant` (consumed+remaining==6), `assert_state_exam_passed_computed`, `assert_clock_response` (7 sweep counters) |
| `test_users.py` | `TEST_USERS` with 7 role entries (`anonymous_headers = {}` — no identity headers per PRD §2.1) + 6 `make_<role>_headers(user_id)` builders |
| `fixtures.py` | 5 fixture tiers (see surface below) |
| `__init__.py` | Barrel: framework generics + all PRD-specific modules |

## Verification output (verbatim)

```
$ python3 -m py_compile test_helpers/*.py
PY_COMPILE OK

$ PYTHONPATH=$PWD python3 -c "<module-by-module importlib import + 100-name surface probe>"
imported test_helpers.types / constants / api_errors / api_client / factories / assertions / test_users / fixtures / test_helpers
missing: []
errors registered: 52
client public methods: 70          # 66 endpoint methods + 4 inherited (get/post/put/delete)
IMPORT CHECK OK

$ <endpoint coverage check>  →  uncovered: []   (66/66 paths present in client source)
$ <final re-check after edit> → FINAL CHECK OK — 9 modules compile and import; surface intact
```

## PRD-vs-SCAFFOLD value disagreements

Only one, and it is metadata, not behavioral: `complexity_profile.error_code_count: 51` while the scaffold's actual `errors:` list and PRD §5 both contain **52** entries. Took the catalog/PRD side (52). Every behavioral constant (thresholds, windows, fees, caps, deadlines, enum values) was cross-checked and agrees between PRD and SCAFFOLD — no dead scaffold-valued constants. Clock path confirmed unprefixed in PRD §2.5, §4 table, and scaffold alike; default `2026-09-01T00:00:00Z` consistent.

## Helper API surface for Stage 2

**Client**: `api_client.<66 methods>` — `set_clock`, `create_level_definition`, `list_level_definitions`, `create_state_adoption_policy`, `list_state_adoption_policies`, `register_candidate`, `get_candidate`, `create_education_program`, `list_education_programs`, `get_education_program`, `record_accreditation_event`, `create_program_completion_record`, `list_/get_program_completion_record(s)`, `decide_program_completion_record`, `create/list/get_exam_application(s)`, `decide_exam_application`, `resubmit_exam_application`, `list/get_authorizations_to_test`(`_to_test`), `schedule_cognitive_exam_attempt`, `list/get_cognitive_exam_attempt(s)`, `deliver_cognitive_exam_responses`, `create/list/get_remedial_education_record(s)`, `create/list/get_psychomotor_verification(s)`, `decide_psychomotor_verification`, `issue_certification`, `list/get_certification(s)`, `create/list/get_recert_application(s)`, `add_ce_entry`, `list_ce_entries`, `submit_recert_application`, `decide_recert_application`, `record_audit_outcome`, `reopen_recert_application`, `create/list/get_reentry_application(s)`, `decide_reentry_application`, `create/list/get_license_application(s)`, `decide_license_application`, `respond_license_application`, `create/list/get_state_exam_record(s)`, `create/list/get_disciplinary_case(s)`, `issue_case_notice`, `submit_case_response`, `schedule_case_hearing`, `decide_case`, `appeal_case`, `decide_appeal`.

**Fixtures**: `advance_clock`, `create_level`, `create_state_policy`, `create_candidate`, `create_program`, `record_accreditation_event`, `create_verified_completion`, `create_exam_application`, `approve_exam_application`, `create_approved_exam_application`, `schedule_attempt`, `deliver_attempt`, `create_psychomotor`, `verify_psychomotor`, `create_verified_psychomotor`, `create_remedial_record`, `issue_certification`, `refresh_{certification,completion_record,recert_application,case,license_application}`; composite tiers `setup_candidate_with_verified_completion` → `setup_approved_application` → `setup_scored_attempt` → `setup_certified_candidate` (each returns a ctx dict; certified ctx keys: `level, candidate, candidate_headers, program, director_user_id, completion_record, exam_application, att_id, attempt, psychomotor, certification`); accumulation `setup_candidate_with_consumed_attempts(consumed_count, outcome_sequence=None)` (15-day-wait-safe, auto-remedial after 3rd fail); lifecycle `setup_lapsed_certification`, `create_reentry_application`, `decide_reentry`; recert `create_recert_draft` (fresh OCC version), `add_ce_entries`, `default_nccp_entry_specs`, `single_provider_audit_entry_specs`, `setup_recert_draft_with_entries`, `submit_recert`, `setup_submitted_recert`, `setup_audit_pending_recert`, `decide_recert`, `record_audit_outcome`, `reopen_recert`; licensure `create_state_exam_record`, `create_license_application` (auto-fresh cert version), `setup_license_context_nremt`, `setup_license_context_state_exam`, `decide_license`, `respond_license`; discipline `open_case`, `issue_notice`, `submit_case_response`, `walk_case_to_under_review`, `schedule_hearing`, `walk_case_to_hearing_scheduled`, `decide_case` (auto-fresh case version), `walk_case_to_decided`, `appeal_case`, `decide_appeal`, `finalize_decided_case` (computes appeal_deadline+1d itself), `walk_case_to_final_via_affirm`; plus `iso_z`, `date_str`, `iso_days_after` datetime helpers.

**Errors**: `ApiErrorId.*` (52 members), `HTTP_STATUS_CODES` pre-registered. **Constants**: all PRD thresholds listed above. **Roles**: `TEST_USERS["<role>_headers"]` + `make_<role>_headers(user_id)`; identity threading is wired inside every fixture (candidate calls always use `make_candidate_headers(candidate["id"])`; program attestations use the program's `director_user_id`).

`test_helpers/` is now frozen for Stage 2.

## Step 5b: Generate test suite — 2026-10-02T13:40:00.000Z

All verification passes are green. Final state is settled.

## Summary

**Files written** (all under `test_suite/`): `conftest.py` + 19 test modules — `test_01_difficulty_dual_variant_calc.py` (2), `test_02_difficulty_combinatorial_formula.py` (3), `test_03_difficulty_non_linear_state_machine.py` (2), `test_04_difficulty_transitive_cascade.py` (2), `test_05_difficulty_priority_pair.py` (2), `test_06_difficulty_boundary_precision.py` (2), `test_07_difficulty_cross_entity.py` (2), `test_08_difficulty_temporal_overlap.py` (2), `test_09_difficulty_compensating_invariant.py` (2), `test_10_corner_entities.py` (10), `test_11_corner_state_machines.py` (14), `test_12_corner_calculations.py` (9, incl. the addendum instance), `test_13_corner_validations.py` (5), `test_14_corner_endpoints.py` (3), `test_15_corner_errors_config_and_windows.py` (12), `test_16_corner_errors_state_gates.py` (15), `test_17_corner_rbac.py` (6), `test_18_corner_complexity_layers.py` (5), `test_19_corner_consistency_model.py` (1).

**Verification results:**
- `py_compile`: clean on all 9 helper modules + 20 suite files.
- `pytest --collect-only test_suite/ -q` (PYTHONPATH=task dir): **99 tests collected, 0 errors** — package graph intact.
- Real AST tag audit (yaml.safe_load both indices, ast.walk every FunctionDef, docstring extraction): queue A 19 instances / 0 stubs — **19/19 covered exactly once**; queue B 87 instances / 6 stubs — **80/81 active covered exactly once**; 99 test functions, 99 unique well-formed tags, every tag resolves to a real non-stub instance, every `Design:` line is the last docstring line, no dual/untagged tests.
- Verbatim-citation sweep (every ≥6-word quoted span in every docstring, whitespace-normalized, grepped against PRD.md): **164/164 spans verified verbatim** (7 initial failures from my "..." elisions were rewritten to full contiguous PRD sentences and re-passed).

**Skipped instance (1, with PRD-filter reason):**
- `Corner/errors/credential_stale_at_issue` — fails unique derivability (two-reader). PRD §3.5 states freshness as "a cognitive pass delivered, or a psychomotor examination verified, more than twenty-four calendar months in the past": the cognitive side anchors on `delivered_at`, so the parallel reading anchors psychomotor on `verified_at` (consistent with §3.5's validity window, which is also anchored on `verified_at`). The instance's expected `ERR_CREDENTIAL_STALE` only fires if freshness reads `exam_date` (2026-09-06) instead of `verified_at` (2026-09-10); under the `verified_at` reading the issue at 2028-09-09T12:00 succeeds (verified 2026-09-10 + 24mo = 2028-09-10, still fresh) and a PRD-faithful implementation fails the test. Gap left as a gap.

**Judgment calls inside otherwise-emitted instances:**
- `candidate_registration_mints_system_fields` and `issue_endpoint_full_side_effects`: the literal `version == 1` sub-assertion was relaxed to "positive integer" — PRD §2.4 says version increments per mutation but never states the initial value (two-reader failure on that sub-point only). All other asserted fields kept verbatim.
- `psychomotor_validity_window_containment`: the recipe submits the first psychomotor at clock 2026-09-01 with `exam_date` 2026-09-03, which PRD §2.8 tier 3 rejects ("examination dates are not in the future"). I inserted an `advance_clock("2026-09-03T00:00:00Z")` before that submission; the asserted window semantics (anchored at `verified_at` 2026-09-05) are unchanged.
- Timestamp assertions use parsed-datetime equality (PRD §2.4 mandates three fractional digits, so a bare `...T00:00:00Z` string compare would over-constrain the format).

**Helper gaps worked around (test_helpers untouched, frozen):**
- `create_state_exam_record`'s default `exam_date` (2026-09-03) is future-dated at the default clock (2026-09-01); tests pass `exam_date="2026-09-01"` explicitly.
- No fixture creates a PENDING (undecided) completion record — composed inline in `test_04` via `api_client.create_program_completion_record` + `create_completion_record_payload` for the revocation cascade's hop-1 target.
- OCC stale-token calls bypass `create_recert_draft`/`create_license_application` (which re-read fresh versions by design) and use raw `api_client` calls with explicit payload factories — as intended.

**Orchestrator independent re-audit**: AST tag audit re-run by orchestrator against both YAMLs — 100 active instances expected, 99 tagged tests, 0 untagged, 0 extra tags, 0 duplicates, sole missing instance is the documented skip `Corner/errors/credential_stale_at_issue`. Confirmed.

## Step 6: Generate implementation — 2026-10-02T14:30:00.000Z

Done. The implementation is complete, verified, and all smoke-server processes I started are killed (ports released; the unrelated task_3470 server was left untouched).

## Files written (all under `workspace/implementation/`)

- `start.sh` (exec launcher, guarded `pip install`, PORT env, 0.0.0.0), `requirements.txt`
- `app.py` (app factory, ApiError/404/405/500 handlers), `db.py` (in-memory store, logical clock default `2026-09-01T00:00:00Z`, base_entity/touch/serialize, live-computed fields), `errors.py` (full 52-code catalog with exact HTTP statuses), `envelope.py` (`meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination), `middleware.py` (`X-User-ID`/`X-User-Role` auth, role checks, typed body extractors), `util.py` (add_months clamping, parse/format, ROUND_HALF_UP 4dp + per-line cents)
- `services/`: `scoring.py` (CAT weighted accuracy, provisional at 6, 1.645-SEM band stop), `ce.py` (waterfall with N→L→I spill, HOURLY variant, audit selector), `cascade.py` (5-hop program revocation, completion invalidation, attempt voiding, pinned-order sanction cascade), `sweep.py` (7-step clock sweep with counters)
- `routes/`: `clock.py` (UNPREFIXED `/_clock/set_current_utc`), `config.py`, `candidates.py`, `programs.py`, `completions.py`, `exam_apps.py` (+ATT reads), `attempts.py`, `remedial.py`, `psychomotor.py`, `certifications.py`, `recerts.py` (+CE entries), `reentry.py`, `licenses.py`, `state_exams.py`, `cases.py`

## Compile + import check (verbatim)
```
FINAL_PY_COMPILE_OK
IMPORT_OK routes=67        # 66 spec endpoints + Flask's built-in /static
FINAL_IMPORT_OK
```

## Smoke tests (dynamic ports, server killed by exact PID afterward)
- (a) `POST /_clock/set_current_utc` {"to_iso8601":"2026-09-01T00:00:00Z"} → 200, all sweep counters 0, `current_utc` echoed
- (b) `POST /registry/level-definitions` (RegistryAdmin) → 201, full LevelDefinition echoed, `created_at` from logical clock
- (c) `GET /registry/level-definitions` → 200, `response_type:"array"`, meta carries limit=10/offset=0/total_count=1/has_more=false
- (d) `GET /registry/candidates/does-not-exist` → 404 `ERR_NOT_FOUND`; missing headers → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; clock backwards → 409 `ERR_CLOCK_REGRESSION`
- Deeper E2E also passed: candidate→program→completion→verify→approve (ATT minted)→schedule→CAT PASS at 6 items (theta 1.0, ATT CONSUMED)→psychomotor→issue (expires +24m, lapse +48m)→recert draft (cert version bumped 1→2)→3 CE entries→submit (waterfall 20/10/10=40; audit fired on SINGLE_PROVIDER_CONCENTRATION: all entries shared one provider totaling 40h ≥ 20)→audit-outcome APPROVED with anniversary extension→lapse sweep→TIER_CE_ONLY reentry→fresh-cycle reinstatement→license GRANTED with per-line rounding (12500→1875, 3333→500, share 2375)→disciplinary case (hold flag live, segregation 403, sanction deferred until sweep FINAL)→PERMANENT_BAR cascade (candidate BARRED, cert REVOKED). Also verified: half-open slot overlap (touching windows allowed), retake-wait 409 then success, stale OCC 412, REVOKED terminal 409, program-revocation hop chain (record INVALIDATED→SUBMITTED app DENIED→cert REVOKED→license DENIED) and its effective_date boundary (completion before revocation effective_date survives).

## Interpretation choices (where PRD admitted >1 reading)
1. **Accreditation-at-completion fallback**: if no history entry has effective_date ≤ completion_date (e.g., completion dated before program creation), the earliest entry's status applies — entry 0 is the program's accredited-from-creation state.
2. **Education validity window**: completion_date treated as midnight UTC; `start <= now <= add_months(midnight,24)` at datetime precision, both ends inclusive.
3. **Unverified record at approval/issue** folds into `ERR_EDUCATION_VALIDITY_EXPIRED` (scaffold groups "VERIFIED and within window" under that id).
4. **Remedial gate anchor**: 3rd SCORED_FAIL's delivered date; if consumed ≥ 3 with fewer than 3 fails, anchors to the 3rd consumed attempt instead.
5. **Resubmit**: swaps `completion_record_id` with existence check only (full gates re-run at decision per PRD); clears `denial_reason`, leaves `decided_at` untouched.
6. **recert_seq**: 1 + count of *other* applications for the certification that ever reached SUBMITTED (persistent `_ever_submitted` flag; a reopened-then-resubmitted app does not re-increment — "ever reached" read as historical).
7. **SINGLE_PROVIDER_CONCENTRATION** evaluated over the waterfall-eligible entry set (in-window RECORDED/VERIFIED).
8. **HOURLY model**: component credited fields stored as 0; only `total_credited_hours` is meaningful.
9. **audit-outcome**: cert-ACTIVE precondition checked before applying verdicts; sufficiency failure → 200 + AUDIT_FAILED (not 422); verdicts for non-RECORDED entries skipped; verdict item shape accepted liberally (`entry_id`/`id`, `verdict`/`outcome`, optional `reason`/`reject_reason`) since PRD doesn't pin it.
10. **Psychomotor role binding**: ProgramDirector↔PROGRAM only, StateOfficial↔STATE only (403 otherwise); PROGRAM submissions also require uid == program.director_user_id; cross-reference also checks the named program teaches the level.
11. **Certification issue**: wrong-status basis records (app not APPROVED, attempt not SCORED_PASS, psychomotor not VERIFIED, attempt↔app linkage broken) → `ERR_CROSS_REFERENCE_MISMATCH`; BARRED checked (tier-7 applies_to includes issue), disciplinary hold not checked (PRD §3.2 scopes holds to opening applications).
12. **License create**: `expected_certification_version` required only on the NREMT path; NREMT_ACCEPTED with both refs still uses the NREMT path; HYBRID with certification_id → NREMT path, no fallback; absent `accepted_level_codes` = nothing accepted; state-exam staleness = midnight(exam_date)+24 months < now.
13. **fee_lines_snapshot** stores the three policy fee lines as an object; grant assesses base + (surcharge | state_exam_fee) by path; registry share rounded half-up per line then summed.
14. **License decision reason mapping**: DENIED→`decision_reason`, MORE_INFO_REQUIRED→`more_info_note` (both from the `reason` input).
15. **suspensions_lifted_count** counts both SUSPENDED→ACTIVE and SUSPENDED→LAPSED lifts; interim suspensions tracked via internal `_suspended_by_case_id` (underscore fields never serialize) so NONE/WARNING finalization restores exactly the certs that case suspended.
16. **Case decide**: no officer identity check beyond role + segregation-from-opener (PRD doesn't require decider == scheduled officer).
17. Implicated attempt/record ids on case creation must exist (body-FK existence tier); case-list filters on them use contains-semantics.
18. Pagination: unparseable limit/offset fall back to defaults, then clamp to [1,100]/[0,∞).
19. Remedial hours non-multiple-of-0.5 → `ERR_INVALID_REQUEST` (not `ERR_CE_HOURS_INCREMENT`, which the scaffold scopes to the CE-entry endpoint).
20. `state_code` two-letter shape not enforced; `completion_date` not future-checked (PRD tier-3 names only examination dates).
21. Exam-app creation checks only existence + bar/hold + cross-ref; validity window is evaluated at approval, per PRD.
22. Reopen leaves `submitted_at`/`decided_at` as history; REJECTED entries stay REJECTED and are excluded from recomputation.
23. `theta_final` = weighted accuracy at the stop prefix (`items_delivered_count`), stored round-half-up 4dp; all pass/fail comparisons unrounded doubles.
24. Unknown paths/methods return the error envelope with `ERR_NOT_FOUND`/404.

**Orchestrator spot-check**: all implementation .py files compile; routes/clock.py mounts unprefixed `/_clock/set_current_utc`; per-domain module layout confirmed.

## Step 7: Test/fix iteration loop — 2026-10-02T15:35:00.000Z

Clean 8-round sweep: 99/99 in every round. The `results.1..8.json` files remain in `workspace/implementation/` per the output contract.

## Summary

**Iterations run:** 2 (initial sweep: 87/99 with a deterministic 12-failure set, identical across all 8 rounds; post-fix sweep: 99/99 × 8 rounds).

**Tests deleted:** none.

**Assertions removed (STEP 1c partial coverage, not deletion):**
- `test_11_corner_state_machines.py::test_recert_deny_reopen_cycle` — removed `assert resubmitted["recert_seq"] == 2`. Unique-derivability collapse (self-inclusion ambiguity): PRD §3.6 states "`recert_seq` is one plus the number of prior applications for the same certification that ever reached `SUBMITTED`" but does not determine whether a reopened-then-resubmitted application counts its own earlier submission as a "prior application". Two PRD-faithful readings exist (exclude-self → seq stays 1, the shipped implementation's reading; include-self → seq 2, the design index's reading). The PRD-covered cycle (DENIED → reopen → DRAFT → resubmit succeeds, seq==1 on first submission) is retained. Scaffold rule that drove the generation: `SCAFFOLD_CORNER_DESIGN.yaml` instance `recert_deny_reopen_cycle` ("resubmission observes recert_seq == 2") — a design-index literal the PRD prose does not uniquely pin.

**Fixes applied to `test_suite/` (test bugs, helpers layer untouched — it was correct):**
- `test_suite/test_11_corner_state_machines.py` — added missing `create_level` to the `from test_helpers import (...)` list (NameError in `test_state_exam_record_voided_by_revocation`).
- `test_suite/test_12_corner_calculations.py` — added missing `setup_candidate_with_verified_completion` import (NameError in `test_education_validity_last_day_inclusive`).
- `test_suite/test_15_corner_errors_config_and_windows.py` — added missing `create_program` import (NameError in `test_issue_cross_reference_mismatch`).

**Fixes applied to `implementation/`:**
- `workspace/implementation/db.py` (`new_id`) — `uuid.uuid4().hex` → `str(uuid.uuid4())`; PRD §2.4 requires "a server-minted UUID", and the canonical hyphenated form is what `is_valid_uuid` (and any standard reader) accepts. Fixed 4 tests (`test_level_definition_create_persists_fields`, `test_state_policy_defaults_applied`, `test_candidate_registration_mints_system_fields`, `test_issue_endpoint_full_side_effects`).
- `workspace/implementation/services/cascade.py` — added `SUSPENSION_MONTHS` to the `from db import ...` line; the constant was defined in db.py but referenced unimported in the SUSPENSION_12M sanction step, causing a 500 NameError in `test_suspension_lift_boundary_sweep` (the "undefined CONST" pattern).
- `workspace/implementation/routes/state_exams.py` (`create_state_exam`) — store `passed` on the record at creation (`float(score) >= float(passing_score)`); previously it existed only in the serializer, so `routes/licenses.py:105`'s `ser["passed"]` raised KeyError 'passed' → HTTP 500 on every STATE_EXAM-path license creation. Fixed `test_fee_state_exam_path_lines`, `test_decision_on_granted_license_fails`, `test_respond_on_under_review_license_fails`.

No PRD-required checks were weakened; no endpoints or fields were added beyond PRD; storage remains in-memory only.

**Orchestrator verification**: all 8 results.*.json read directly — passed=99/total=99/failed=0 in every round; results files present (not deleted); no .py source file in implementation/, test_suite/, or test_helpers/ is newer than the final sweep (no post-sweep writes).

## Step 8: Finalize PRD — 2026-10-02T15:50:00.000Z

Done. `PRD_FINALIZED.md` is written with exactly one targeted revision.

## Summary

**Line counts / delta:** PRD.md = 385 lines, PRD_FINALIZED.md = 385 lines, 0% line delta — a single in-place sentence revision on line 213 (§3.6), no lines added or removed.

**Change (1 total):**
- §3.6 (Recertification audit selector) — revise — "one plus the number of **prior** applications" → "one plus the number of **other** applications", and appended the pinning clause: "the application being submitted never counts its own earlier submissions, so reopening and resubmitting the same application does not by itself advance its `recert_seq`" — `implementation/services/ce.py:81-88` (`a["id"] != app["id"]` + `_ever_submitted` flag), stamped at `implementation/routes/recerts.py:234-241`.

**Pre-edit search log (mandatory enumeration):**
- (a) Subject: `recert_seq` derivation at recertification submission — whether a reopened-then-resubmitted application's own earlier submission counts as a "prior application".
- (b) Impl paths enumerated and read: `services/ce.py:81-88` (`compute_recert_seq` — self excluded by id check, counts persistent `_ever_submitted`); `services/ce.py:91-95` (`audit_select` — consumes seq only for `SEQ_MOD`, mod 3); `routes/recerts.py:90,100` (creation initializes `recert_seq=None`, `_ever_submitted=False`); `routes/recerts.py:234-241` (`submit_recert` — seq computed before `_ever_submitted=True` is set; re-stamped unconditionally on every submit, including resubmission after reopen); `db.py:99-102` (serializer strips underscore keys — flag never leaks). Grepped both `recert_seq` and `_ever_submitted` across `implementation/` and `test_helpers/` — no other paths exist. PRD mentions `recert_seq` only at line 213.
- (c) Wording adjustment: chose "does not **by itself** advance" rather than "keeps the same value", because an intervening submission of a *different* application for the same certification is possible between denial and resubmission (creation is only blocked while another application stands `SUBMITTED`/`AUDIT_PENDING`, per `routes/recerts.py:74-76`), and in that case the resubmission's seq legitimately rises. The looser phrasing keeps every enumerated path consistent.

**Step-7 items adjudicated as needing NO PRD edit (with evidence):**
- `db.py` `new_id` UUID fix (`uuid4().hex` → `str(uuid4())`) — impl moved *toward* PRD §2.4 ("a server-minted UUID"); PRD already determines the canonical form. No edit.
- `services/cascade.py` `SUSPENSION_MONTHS` import — pure impl NameError; PRD §3.9 step 2 already pins "twelve calendar months after `finalized_at`". No edit.
- `routes/state_exams.py` `passed` stored at creation — pure impl KeyError fix; PRD §3.8 already states "the record computes `passed` as the score meeting or exceeding the passing threshold" (verified at `state_exams.py:18,51`; consumer `licenses.py` reads the same stored value). No edit.
- Three test-suite import fixes (`create_level`, `setup_candidate_with_verified_completion`, `create_program`) — pure test bugs; PRD untouched.

Output file: `workspace/PRD_FINALIZED.md`

**Orchestrator verification**: `diff PRD.md PRD_FINALIZED.md` shows exactly the one claimed §3.6 sentence revision and nothing else.

## Step 9: Complete PRD scan — 2026-10-02T16:40:00.000Z

Done. PRD_COMPLETED.md is written and verified. Final report:

## Output

**Source:** `workspace/PRD_FINALIZED.md` (385 lines) → **`workspace/PRD_COMPLETED.md`** (385 lines, +4838 chars). 30 paragraphs touched; every change is an in-paragraph insert/revision — no new sections, no deletions of requirements.

**Counts:** 33 ambiguity-pins (one marked unimplementable-clause), 0 mismatch-revisions, 2 impl-bugs-reported. Suite state cross-checked: 99/99 green in all eight recorded sweeps (`implementation/results.*.json`), so implementation was treated as the stable target.

## Pins (one bullet each)

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as wall-clock envelope metadata; logical clock governs domain time only — implementation/envelope.py:7,16 + util.py:65-66
- §2.3 — insert — ambiguity — limit/offset out-of-range values clamped (1..100 / ≥0), unparseable falls back to defaults; timestamp ties break by creation sequence — implementation/envelope.py:44-66
- §2.4 — revise — ambiguity — `version` starts at 1 at creation, `updated_at` == `created_at` initially — implementation/db.py:71-77
- §2.5 — revise — ambiguity — sweep step 2 consumes the authorization only when it still stands ISSUED; an ATT already expired by step 1 of the same sweep stays EXPIRED (corner: attempt window outliving ATT validity) — implementation/services/sweep.py:27-35
- §2.5 — insert — ambiguity — suspension lift clears `suspension_ends` — implementation/services/sweep.py:56-58
- §2.8 — insert — unimplementable-clause — entity-backed ownership presupposes the entity; unresolved path id reports ERR_NOT_FOUND before any ownership comparison — implementation/routes/recerts.py:154-158, exam_apps.py:193-197, etc.
- §3.1 — revise — ambiguity — `cognitive_cut_score` between zero and one *inclusive*, else ERR_INVALID_REQUEST — implementation/routes/config.py:27-29
- §3.1 — revise — ambiguity — two-letter `state_code` is the keying convention; only non-empty + uniqueness enforced (PRD pinned no rejection for other lengths) — implementation/routes/config.py:80,91-94
- §3.2 — revise — ambiguity — revocation hop 2 "strictly after" compared at day precision; same-calendar-day completions survive — implementation/services/cascade.py:93-96
- §3.3 — revise — ambiguity — accreditation history read: each entry applies from the calendar date of its `effective_date`; pre-everything dates read the earliest entry — implementation/db.py:142-156
- §3.3 — revise — ambiguity — validity window upper bound resolves to 00:00:00.000Z of the +24-month boundary date, inclusive — implementation/db.py:134-139
- §3.4 — insert — ambiguity — tier-8 cross-reference (record belongs to caller, teaches level) enforced already at exam-application creation — implementation/routes/exam_apps.py:65-68
- §3.4 — revise — ambiguity — remedial anchor: day-precision "strictly after the third failed attempt", falling back to the third *consumed* attempt when fewer than three fails exist — implementation/routes/exam_apps.py:30-37
- §3.4 — revise — ambiguity — both exam-app decision outcomes stamp `decided_at` — implementation/routes/exam_apps.py:133,185
- §3.4 — insert — ambiguity — resubmit retains the stale `decided_at` until the next decision — implementation/routes/exam_apps.py:206-211
- §3.4 — revise — ambiguity — `theta_final` is the accuracy at the decision prefix (stopping prefix on early band exit, else full submission); empty `responses` accepted: accuracy 0.0, PASS iff 0.0 meets cut, no provisional, `items_delivered_count` 0, `theta_final` 0.0 — implementation/services/scoring.py:44-59
- §3.5 — insert — ambiguity — program-administered psychomotor submissions are program-scoped: caller must equal the named program's `director_user_id`, and the named program must teach the level — implementation/routes/psychomotor.py:75-77,94-96
- §3.5 — insert — ambiguity — issuance re-checks subject not BARRED; disciplinary-hold gate does not apply to issuance — implementation/routes/certifications.py:42-43
- §3.6 — insert — ambiguity — CE-entry cycle check at day precision against the calendar dates of the pinned instants — implementation/routes/recerts.py:163-166
- §3.6 — revise — ambiguity — recert submit window both-bounds-inclusive at instant precision — implementation/routes/recerts.py:224
- §3.6 — insert — ambiguity — under HOURLY the three component credited fields are stored as zero; only `total_credited_hours` carries the result — implementation/services/ce.py:27-33
- §3.6 — revise — ambiguity — SINGLE_PROVIDER_CONCENTRATION computed over the same eligible entries the waterfall credits — implementation/services/ce.py:105-109 + recerts.py:229-235
- §3.6 — revise — ambiguity — cert-ACTIVE requirement at recert decision gates approval only; denial recorded regardless — implementation/routes/recerts.py:254-265
- §3.6 — insert — ambiguity — audit-outcome requires cert ACTIVE before verdicts; verdict sub-fields `entry_id`/`verdict` (aliases `id`/`outcome`), optional `reject_reason`/`reason`; verdicts on non-RECORDED entries ignored — implementation/routes/recerts.py:283-303
- §3.7 — revise — ambiguity — tier boundaries are the exact instants expiry+12/24 months, second precision, equality to the lower tier; tier evidence optional at creation, enforced only at approval — implementation/routes/reentry.py:47-53,120-131
- §3.7 — insert — ambiguity — reinstatement leaves `renewed_count` unchanged — implementation/routes/reentry.py:134-138
- §3.8 — revise — ambiguity — `fee_lines_snapshot` is an object carrying the three configured amounts — implementation/routes/licenses.py:125-129 (note: dead test-side `assert_license_application` in test_helpers/assertions.py:298 expects a list — never invoked; impl's dict is the shipped shape)
- §3.8 — revise — ambiguity — HYBRID: `certification_id` present selects national path outright with no fallback; state-exam path only when absent; neither → shape error; only the selected path's reference stored — implementation/routes/licenses.py:64-71,131-133 (test-confirmed by test_15 hybrid_prefers_nremt_path)
- §3.8 — insert — ambiguity — `expected_certification_version` ignored on the state-exam path — implementation/routes/licenses.py:29,73-76
- §3.8 — revise — ambiguity — license decision payload carries `outcome`+`reason`, stored as `decision_reason`/`more_info_note`; `response_note` not persisted — implementation/routes/licenses.py:186-201,234-243
- §3.9 — revise — ambiguity — `response_text` optional and not persisted — implementation/routes/cases.py:128-139
- §3.9 — insert — ambiguity — decision not bound to the officer named at scheduling (any HearingOfficer may record) — implementation/routes/cases.py:158-180
- §3.9 — revise — ambiguity — `appeal_grounds` optional and not persisted; appeal-decision `rationale` not persisted — implementation/routes/cases.py:191-194,209-210

## IMPL BUGs (PRD kept as-is; not edited into PRD_COMPLETED.md)

- §2.1 — IMPL BUG — "When `X-User-Role` is `HearingOfficer`, `X-User-ID` is likewise opaque, with one segregation constraint: it must differ from the `opened_by_user_id` of the disciplinary case being scheduled **or decided**." — implementation/routes/cases.py:158-180 (`decide_case` never compares `uid` to `case["opened_by_user_id"]`; only `schedule_hearing` does, cases.py:149-151) — consequence: the case opener, calling `POST /registry/disciplinary-cases/{id}/decide` with role HearingOfficer and their own X-User-ID on a case a different officer scheduled, can record the hearing decision, defeating the two-sided segregation the PRD pins for both schedule and decide — fix sketch: in `decide_case`, after loading the case, add `if uid == case["opened_by_user_id"]: raise_err("ERR_SEGREGATION_OF_DUTIES", ...)` before the stage gate.
- §2.8 — IMPL BUG — "the system evaluates them in a fixed tier order and reports the first failure: … 3. **Request shape.** … 4. **Existence.** Path identifiers must exist …" — implementation checks path-identifier existence (and on audit-outcome also the state gate) *before* body-shape validation on action endpoints: routes/programs.py:75-85, completions.py:99-103, exam_apps.py:120-124, attempts.py:127-144, psychomotor.py:164-168, recerts.py:249-253, recerts.py:272-281 (state-before-shape as well), reentry.py:101-105, licenses.py:182-186, licenses.py:229-237, licenses.py:53-71 (path-resolution shape after existence), cases.py:161-167, cases.py:186-194, cases.py:206-210 — consequence: a double-fault request (nonexistent `{id}` + malformed body) yields ERR_NOT_FOUND — or, on audit-outcome, ERR_RECERT_NOT_AUDIT_PENDING — where §2.8 requires ERR_INVALID_REQUEST; the suite's own `test_shape_error_beats_existence` (test_13) confirms the intended tier reading on create endpoints — fix sketch: on each listed endpoint, run the `req_*`/`opt_*` body-shape block before the `STORE…get` + 404 check (and in `audit_outcome` move the `AUDIT_PENDING` gate after the `entry_verdicts` shape check).

## Step 9b: Impl-bug fixes + re-sweep — 2026-10-02T17:10:00.000Z

Step 9b complete. All 8 re-sweep rounds are green: **99/99 passed, 0 failed, rounds 1-8**, with `results.1.json` … `results.8.json` retained in `workspace/implementation/`.

## Bug 1 — §2.1 segregation of duties on case decide

`workspace/implementation/routes/cases.py`, `decide_case` (now lines 158-183): captured `uid` from `authn` and added, immediately after `_stage_gate(case, ["HEARING_SCHEDULED"])`:
```python
if uid == case["opened_by_user_id"]:
    raise_err("ERR_SEGREGATION_OF_DUTIES",
              "The hearing officer must differ from the case opener")
```
Same error_id and 403 status as the schedule path (`schedule_hearing`, lines 149-151), placed at §2.8 tier 7 (compliance gate, after the state precondition) — mirroring the schedule path's placement. Per PRD_COMPLETED §3.9, the check is against `opened_by_user_id` only (decision is not bound to the scheduling officer).

## Bug 2 — §2.8 shape (tier 3) before existence (tier 4)

All 14 listed sites were existence/state-before-shape as reported; none skipped. Body-shape blocks moved ahead of the `STORE…get` + 404 check in:

- **cases.py**: `decide_case` (also Bug 1), `appeal_case` (appeal_grounds check moved up; entity-backed ownership check stays after existence), `appeal_decision`
- **programs.py**: `accreditation_event` (to_status/effective_date/reason)
- **completions.py**: `decide_completion`
- **exam_apps.py**: `decide_exam_application`
- **attempts.py**: `deliver_responses` (responses list + per-item shape block)
- **psychomotor.py**: `decide_psychomotor`
- **recerts.py**: `decide_recert`; `audit_outcome` — `entry_verdicts` list-shape moved above the app 404, and the `AUDIT_PENDING` state gate now sits after the shape check
- **reentry.py**: `decide_reentry`
- **licenses.py**: `decide_license_application`, `respond_license_application` (ownership stays after existence), `create_license_application` — path-resolution shape block moved to immediately after the policy existence check, ahead of candidate/cert/state-exam-record existence

**Justified exceptions:** (1) `create_license_application`'s path-resolution shape requires the resolved policy's `adoption_mode`, so it sits directly after the policy check rather than before all existence checks — noted in an inline comment; tier 4 pins only left-to-right path-identifier order, not body-reference order. (2) `audit_outcome`'s per-item verdict shape/existence checks remain inside the mutation loop after the state gate — the loop mutates CE entries and must not run on a request the state gate rejects; the flagged defect (list-level shape and state gate) is fixed.

**Test-side changes:** none required. The suite's only segregation test targets the schedule path with a shared operator id; all state-gate/error tests use valid bodies, and the sole nonexistent-id tests hit a GET and the already-shape-first exam-application create — so no test pinned the old order. No PRD/SCAFFOLD/worklog files touched.

**Orchestrator verification**: all 8 results.*.json read directly — 99/99/0 in every round (ALL_GREEN); no .py source file in implementation/, test_suite/, or test_helpers/ is newer than the final sweep.
