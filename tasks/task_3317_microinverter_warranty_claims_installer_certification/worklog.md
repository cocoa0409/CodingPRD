# Worklog — task_3317_microinverter_warranty_claims_installer_certification

## Step 1: Create task directory — 2026-09-30T19:59:00.000Z

Used the pre-allocated task directory `./tasks/task_3317_microinverter_warranty_claims_installer_certification/`. No index computation performed (per invocation instruction). Verified `workspace/` already exists and is empty; `./INSTRUCTION.md` present at project root (1424 bytes).
## Step 2: Generate scaffold — 2026-10-01T00:30:00.000Z

All three artifacts are generated, parse cleanly, and pass the skill's own linter.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3317_microinverter_warranty_claims_installer_certification/`):
- `SCAFFOLD.yaml` — 1923 lines (§1.0–§1.7; `scaffold_difficulty_design` and `scaffold_corner_design` appear nowhere in it)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1542 lines (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1867 lines (single top-level key `scaffold_corner_design`)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (66 endpoints, 10 entities, 18 §1.8 instances, 34 §1.9 instances, 616 calls scanned, 0 violations). No forbidden concurrency vocabulary; all instance names unique; zero unbound `${var}` placeholders.

**Entity model (10, flat topology, 5 cross-aggregate FK links):** Installer, DesignProject, ProductionLot (immutable, `common_fields: false`), SystemRegistration, Unit, WarrantyClaim, LaborReimbursement, WarrantyTransfer, ProactiveCampaign, ReplacementOrder.

**State machines (7):** Installer certification (cyclic PENDING→ACTIVE→SUSPENDED→ACTIVE, plus lazy ACTIVE→EXPIRED), Unit monitoring (cyclic 2-phase ONLINE↔UNDERPERFORMING/FAILED/OFFLINE), WarrantyClaim (branching + cyclic: DIAGNOSED forks, CLOSED/DENIED loop back via REOPENED), LaborReimbursement, WarrantyTransfer, ProactiveCampaign, ReplacementOrder. 2 OCC `concurrency_rules` on `Unit.version` (`expected_unit_version`).

**Calculation rules (6):** `evaluate_lot_defect_rate` (cumulative vs trailing-90-day), `compute_warranty_coverage` (narrow vs fleet-wide replacement ratio), `compute_labor_reimbursement` (per-component vs sum-then-round; all pinned literals computed by code, e.g. GOLD 2.0 h @130 months → 7013+3188 = 10201 vs blended 10200), `resolve_replacement_model` (GEN1→GEN2 forced promotion), `evaluate_metering_posture`, `rank_campaign_target_units` (guaranteed-bucket waterfall with `created_at` tie-break, never `id`).

**Endpoint count:** 66. **Error catalog:** 33. **Roles (4):** PlatformAdmin (opaque), Installer (`entity_backed:Installer`), MonitoringService (opaque), Homeowner (opaque).

**Difficulty design:** 18 instances, all nine §0.5 rules at exactly 2 instances each, each grounding in real §1.1–§1.5 elements and carrying an executable `setup_api_calls` chain. Cascade instances are depth-3 from different triggers (unit failure → lot RECALL → campaign → orders; campaign cancel → order cancel → counter fixed point).

**Corner design:** 37 instances across all nine guide sections (entities 7, state_machines 6, calculations 1, validations 6, endpoints 3, errors 2, rbac 4, cross_cutting 7, consistency_model 1), including two `excluded_because:` stubs citing existing §1.8 instances.

Notable hardening done while drafting: removed a dead-end `VOID` warranty status and replaced `ERR_UNIT_CHARGE_VOID` with `ERR_INCOMPATIBLE_REPLACEMENT` (enum-value closure), added `ERR_INVALID_REQUEST_BODY` at validation priority 3 with priorities 3–33 renumbered to 4–34, added the `POST /warranty/replacement-orders/{id}/reactivate` endpoint plus priority-33 entitlement-overlap rule so the §1.8 compensating-invariant and §1.9 half-open-interval instances are reachable, and recorded every numeric assertion as a literal actually executed against the formulas.

**Orchestrator verification:** confirmed all three files on disk with expected line counts; SCAFFOLD.yaml top-level keys are `scenario, domain_name, api_prefix, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, response_envelope, endpoints, errors, roles`; `scaffold_difficulty_design`/`scaffold_corner_design` leakage count = 0.

## Step 3: Copy shared files — 2026-10-01T00:31:00.000Z

Copied `./INSTRUCTION.md` (1424 bytes) to `./tasks/task_3317_microinverter_warranty_claims_installer_certification/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-01T00:40:00.000Z

All three hard contracts now pass. Final verification summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3317_microinverter_warranty_claims_installer_certification/workspace/PRD.md` — 352 lines, ends at §5 with no audit footer.

### Section map (PRD section → scaffold source)

| PRD section | Draws from |
|---|---|
| §1 Introduction | `scenario`, `complexity_profile` (workflow_orchestration + temporal_windowing; three-clock framing) |
| §2.1 RBAC | `roles[]` (all 4 names, identity forms), validations priority 1–2, role-gated errors |
| §2.2 Response Structure | `section-2.2-response-structure.md` emitted byte-identically (only the trailing `---` hr differs) |
| §2.3 Pagination | `response_envelope.pagination_defaults`, §4 note on commissioning-order listing |
| §2.4 Identity/Versioning | `common_fields` split (7 with full fields; `ProductionLot`/`WarrantyTransfer`/`ReplacementOrder` explicitly id+created_at only), Unit.version mutation triggers |
| §2.5 Nested Retrieval & Validation Order | validation priorities 3–6, path left-to-right rule, FK list from priority 5 |
| §2.6 Certification & Entitlements | Installer state machine, validations 8/10/28/29, `design_tool_enabled`/`commissioning_enabled` definitions |
| §2.7 Logical Clock | endpoint `/_clock/set_current_utc`, default `2026-09-01T00:00:00Z` |
| §2.8 OCC | `concurrency_rules[]` (both entries: `expected_unit_version` + `ERR_STALE_UNIT_VERSION`/412) |
| §2.9 Precision | `calculations[].precision` for all six calcs |
| §3.1 Onboarding/Certification | Installer machine (5 transitions), `cert_term_months`, validation 26, all 4 installer aggregates |
| §3.2 Design Projects | `dc_ac_ratio` calc + `MAX_DC_AC_RATIO`, validations 27/29 |
| §3.3 Commissioning/Coverage | `compute_warranty_coverage` (all 6 steps, both variants), validations 10–16, registration side effects |
| §3.4 Monitoring/Metering | Unit machine (7 transitions), `evaluate_metering_posture` (both variants), validations 21–22 |
| §3.5 Lots/Campaign Cascade | `evaluate_lot_defect_rate` (both variants), `rank_campaign_target_units` (both variants), long online→failed side effect, lot-actions, campaign machine |
| §3.6 Claims | WarrantyClaim machine (10 transitions), validations 7/8/9/19/20/28, claim-field snapshots |
| §3.7 Replacement/Install | ReplacementOrder machine (5 transitions), `resolve_replacement_model` (both variants), validations 17/18/23/32/34, entitlement windows |
| §3.8 Labor | `compute_labor_reimbursement` (both rounding variants with the 7013+3188=10201 vs 10200 worked contrast), LaborReimbursement machine (4 transitions), validations 24/25 |
| §3.9 Transfers | WarrantyTransfer machine (3 transitions), share links |
| §4 | `endpoints[]` — 4 columns, 67 rows |
| §5 | `errors[]` — 2 columns, 33 rows |

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 101 required, 101 present, 0 missing
- endpoints[].request_body/input: 55 required, 55 present, 0 missing
- endpoints[].query_params (limit/offset): 2 required, 2 present, 0 missing
- endpoints[].path_params: 0 required, 0 present, 0 missing
Status: PASS
```
(`campaign_eligible` was the single first-pass omission and was repaired in §3.5.)

```
Rule coverage check:
- validations[] with priority: 34 checked, 34 expressed (order stated at every multi-gate site), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_unit_version + ERR_STALE_UNIT_VERSION/412), 0 missing
- state_machines[].transitions: 37 checked, 37 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed (constants embedded in business units), 0 missing
- validations[] conditions: 34 checked, 34 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 66 checked, 66 expressed, 0 missing
- entities[].fields[] structured content: 101 checked, 101 reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 612
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Two items worth flagging

1. **`POST /warranty/design-projects/{id}/reject` appears in §4 but is absent from `endpoints[]`.** Included deliberately: the scaffold defines `DesignProject.rejection_reason` and the `REJECTED` enum value, references the rejection source in `errors` semantics, and otherwise has no operation able to reach that state (DiagnosisProject has no `state_machines` entry, so its machine is expressed only through endpoints). Removing it would leave a status and a field unreachable. It is the only §4 row not backed 1:1 by a scaffold endpoint entry; all 66 scaffold endpoints are present with method/path/role set verified programmatically (0 mismatches).

2. **§2.2's `response_type` value is `"object" | "array"`**, which is a literal union in the fixed contract, not a valid JSON token. Emitted verbatim as required. Any evaluator that parses the §2.2 fence as strict JSON would reject it; this is upstream behavior, identical in `example-prd.md`.

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read.

**Orchestrator verification:** `workspace/PRD.md` on disk at 351 lines (subagent reported 352 — off-by-one from trailing newline). Sections confirmed: §1 Introduction, §2 Global Specifications, §3 Business Logic, §4 Endpoint Definitions (67 rows), §5 Error Code Catalogue.

## Step 5: Generate unit tests — 2026-10-01T01:30:00.000Z

Done. Both stages are written, lint-clean, and audited.

### Files written

`test_helpers/`
- `__init__.py` (27), `types.py` (339), `api_client.py` (239), `api_errors.py` (79), `assertions.py` (159), `constants.py` (84), `factories.py` (159), `fixtures.py` (544), `test_users.py` (18)

`test_suite/`
- `conftest.py` (29), `test_01_entities_and_state_machines.py` (18 tests), `test_02_dual_variant_calculations.py` (6), `test_03_cascades.py` (6), `test_04_validations_and_rbac.py` (12), `test_05_boundary_precision.py` (7), `test_06_cross_entity_dependencies.py` (8), `test_07_temporal_overlap.py` (6), `test_08_invariants_and_layer_edges.py` (10), `test_09_endpoints_and_consistency.py` (7), `test_10_position_budget_and_listing.py` (6)

### Totals

**86 tests**, all collected by pytest, all modules import cleanly, pyflakes clean, no `skip`/`xfail`, no "scaffold"/section-reference vocabulary in generated code.

**§1.8 (queue A): 18/18 translated, 0 skipped.** Every difficulty instance carries ≥2 tests (80 tests total tagged `Difficulty/...`).
**§1.9 (queue B): 33/34 translated, 1 skipped.** 33 non-stub instances each carry ≥1 test at two-instance isolation; the 3 `excluded_because:` stubs were **not** translated, and their cross-references to queue A all resolve (`resubmit_conflict_business_safety_beats_fiscal`, `unit_failure_to_lot_recall_to_campaign_depth_three`, `lot_defect_cumulative_vs_trailing_window`).

### Skips (one, with reason)

- `Corner/cross_cutting_complexity_layers/rate_threshold_trigger_on_lot_defect_rate` — already an `excluded_because:` stub that is **verified broken**: it points at `lot_defect_cumulative_vs_trailing_window`, which asserts a *cumulative-vs-window divergence*, not a WATCH→RECALL threshold crossing. Per the skill, a broken pointer means skip; do not emit a placeholder.
- I also read `Corner/cross_cutting_complexity_layers/cascading_side_effects_chain_depth_three` and `Corner/errors/stale_unit_version_rejection_path` as properly covered stubs (their queue-A owners do exercise the cited chains).

### Key findings (limits of the source indices)

1. **Numeral drift vs PRD on DC/AC.** Both indices use 400 W/module in their worked examples (`40 modules / 24600 W = 1.5375`; `20/10000 = 1.25`), but PRD §3.2 states "three hundred and fifty watts per microinverter". A PRD-faithful reader gets `1.7571` and `1.4286`. All ratio assertions and the "exactly 1.5" fixture were re-derived to PRD values (the 1.5 case uses 21000 W over 40 modules); the instances themselves were kept since the rule is verbatim and uniquely derivable.
2. **A design index toggles a case that only exists on the other branch.** `installer_missing_required_field_returns_invalid_request`, `missing_role_header_returns_unauthenticated` and `unknown_claim_id_returns_not_found` are all *negative* cases (missing `company_name`, unknown role, unknown id). "The exact error for this negative path" is not derivable, so each asserts only the error the PRD names (`ERR_INVALID_REQUEST_BODY` for a required field; `ERR_UNAUTHENTICATED` for an unknown role) and the accompanying non-creation/no-dispatch claim is capped to the PRD-verbatim status shell; no scaffold-only literal is copied.
3. **The two-reader filter dropped several index-asserted numbers** that the PRD never states: `Unit.version == 1` on a fresh unit, `certification_status`/`limited to four states`, `owner_change_count` on the cusp, `duplicate serial leaves no second row`, `replacement_ratio == 0.3` computed indices, that `CRON`-style totals recompute synchronously. Where a number was *not* PRD-stated but a *shape* was (e.g. `Status` exists, `owner_change_count` starts at 0), the test asserts the shape, not the drifted literal.
4. **A few sibling fixtures returned whole objects (with `version` etc.) whose field is not in the committed PRD field list.** Only PRD-named fields (`id`, `created_at`, `updated_at`, `version`, `status`) are asserted; PRD-named derived fields are asserted exactly.

### Structural checks I ran

- 132 distinctive quoted spans (≥8 words) grepped literally against `PRD.md`: **all verbatim** (modulo whitespace).
- Every test has exactly one `Design:` line copied verbatim from a `name:`; 0 unresolved tags; 0 dual-tagged; 0 untagged.
- 86/86 tests collected by `pytest --collect-only`.

I also ran `prd-bench-local-runner --isolation per-test-server` in the sandboxing-friendly way the skill allows — but the runner needs the task's `workspace/implementation/` (which does not exist yet for task 3317), so execution stopped at startup, as expected at the unit-test-generation stage.

**Orchestrator verification:** on-disk line counts match; 86 test functions confirmed by grep; exactly 86 `Design:` tag lines (one per test); 0 `pytest.mark.skip`/`xfail`; 52 unique tags all resolve to `name:` values present in the two design yamls (cross-checked with a script over all instances of both files) — 0 dangling tags.

## Step 6: Generate implementation — 2026-10-01T04:20:24.000Z

Step 6 was **interrupted by the host** (all background processes killed under memory pressure) while the implementation subagent was mid-flight. The orchestrator therefore did NOT trust the missing hand-back and audited the partial output directly before deciding whether to redo it.

**Audit of the partial `workspace/implementation/` (25 files, 4034 lines):**

- **Route coverage: exact.** App boots; `url_map` yields 67 real routes (68 minus the Flask `/static` rule). Mechanical diff against PRD §4's 67-row endpoint table: 0 PRD paths missing, 0 extra routes.
- **Storage purity:** `db.py` is a `Store` of plain dicts keyed by entity id, no db/file/cache/persistence of any kind; declared empty at boot.
- **No seeding:** `app.py` docstring states the store is empty at boot; no seed/preload/hardcode found anywhere.
- **Compile + lint:** `compileall` clean across all modules. pyflakes reports only unused imports and 3 unused local variables — all manual dead code, not incomplete logic. The one bare `pass` (`views/units.py:135`) is an intentional no-op for the already-terminal `FAILED` branch of the observation state machine, not a stub.
- **Cold boot:** launched via `start.sh` on a self-chosen free port; boots cleanly, binds `0.0.0.0`, serves the response envelope correctly.
- **Spine logic present:** validation gates fire correctly (`ERR_LEVEL_UP_NOT_ELIGIBLE`, `ERR_LEVEL_UP_NOT_ELIGIBLE`, `ERR_DESIGN_TOOL_NOT_ENABLED`, required-field and auth checks), i.e. the domain logic is materially implemented, not stubbed.
- **`start.sh` contract:** reads `$PORT`, binds `0.0.0.0`, runs in the foreground via `exec`; conditional `pip install` guarded by an `import flask` probe so per-test restarts do not contend on the interpreter. `requirements.txt` = `Flask==3.0.3`.

Verdict: the partial output is materially complete, so it was **completed rather than redone**.

**Orchestrator-applied fix (implementation).** A first probe round scored 10/86 with 75/76 failures collapsing on one setup error: `409 ERR_LEVEL_UP_NOT_ELIGIBLE — the installer lacks the required decided-claim history`.

Root cause, traced to source: the scaffold's validation `installer_level_change` (SCAFFOLD.yaml:1095) reads "the requested certification level is exactly one step above the installer's current level, **and** the installer has at least `CONST.claims_for_level_up` decided claims", and error entry 1790 repeats the same `CONST.` reference — but **`CONST.claims_for_level_up` is referenced yet never defined anywhere in SCAFFOLD.yaml**, and appears in neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml`. The doc-generator literalized this undefined constant as "at least one hundred decided claims" (PRD:128), and the implementation followed suit (`services/common.py: CLAIMS_FOR_LEVEL_UP = 100`, `views/installers.py:117`).

Evidence the threshold is not part of the intended system:

1. **The scaffold's own §1.8 setup chains promote to GOLD with zero claims.** `SCAFFOLD_DIFFICULTY_DESIGN.yaml:24-32` is `installers → activate → installer-levels GOLD → design-projects` with no claim creation; every §1.8/§1.9 GOLD setup chain follows the same shape.
2. **The threshold makes the system unbootstrappable.** Proved empirically against the unmodified code: opening a design project requires GOLD (`ERR_DESIGN_TOOL_NOT_ENABLED`), commissioning requires an applicant-owned APPROVED design project (which only a GOLD installer can create) *and* `commissioning_enabled` (which requires that same design project), and filing a claim requires a unit on a commissioned system. So every route to a Unit runs through a GOLD-gated design project, while GOLD requires 100 decided claims, which requires units and claims to already exist. There is no seed data by design, so no installer can ever be promoted: A(certification)→B(design project)→C(system)→D(claim) is closed at B→A.
3. If the intent had been a gate, the correct bootstrap value would be at most one decided claim; but the design indices contradict even that.

Fix applied: removed the `decided_claims(...) < CLAIMS_FOR_LEVEL_UP` rejection from `views/installers.py` (2 lines). The one-rung-at-a-time rule and `ERR_LEVEL_UP_NOT_ELIGIBLE` for skipped rungs / same-level requests are **retained**, matching both the scaffold validation's reachable clause and the review's actual behaviour. PRD:128's corresponding sentence must be corrected at Step 8.

**Result:** the 4-round probe sweep after the fix scored **46/86 in every round** (up from 10/86), stable across all four rounds. Remaining 40 failures and their PRD status were triaged by the orchestrator and handed to Step 7; the two largest families (`ERR_LOT_RECALL_ACTIVE`, 16 — PRD:190 gate 3 explicitly requires this rejection, so the tests' fixtures are placing units under recalled lots before filing; and `assert '<instant>.000Z' == '<instant>Z'` in 10 monitoring tests — PRD:43/80 mandate three fractional digits, so the tests truncate) are both PRD-legitimate implementation behaviour mis-asserted by the tests.

## Step 7: Run tests and iterate — 2026-10-01T05:07:02.000Z

**Step 7 was executed by the orchestrator directly, not by a subagent.** The Agent tool was unusable for this entire session: every spawn — including one with an explicit `model: sonnet` override — terminated with `model_not_found` for `deepseek-v4p1-flash-wave`, i.e. the harness sends a nonexistent model id and the override does not take effect. (Steps 2/4/5 had run as subagents earlier, before the endpoint stopped resolving.) The loop itself was therefore driven in the foreground with the same protocol, exhausting the full failure set per iteration.

### Iterations run: 5 sweeps

| sweep | passed/total (8 rounds) | note |
|---|---|---|
| probe | 10/86 | single round; 75/76 failures collapse on one setup error |
| 1 | 69,67,66,68,68,67,67,68 | after probe fix + timestamp/threshold batch |
| 2 | 72,71,72,72,71,71,71,72 | after helper/derivation batch |
| 3 | 79,80,79,81,80,81,80,80 | after gate-order/campaign batch |
| 4 | 79,78,79,78,79,79,79,79 | after entitlement-guard batch (one fix was wrong, reverted) |
| **5** | **85/85 × 8** | **clean — every round passed** |

Final: `passed=85 failed=0 errors=0 total=85` in all 8 rounds; no implementation file was modified after the sweep (verified by mtime), so the sweep is valid.

### Tests deleted (2)

- `test_campaign_activation_refuses_a_still_pending_order_for_the_same_unit` — **incoherent / not uniquely derivable.** Its body does not exercise what its name and its own design tag (`Corner/cross_cutting_complexity_layers/occ_stale_unit_version_on_replacement_order_create`) claim: it creates a manual order, then attempts to record a billed-replacement entitlement, and asserts `ERR_ORDER_NOT_CHARGEABLE`. PRD:220 explicitly *permits* an adjacent second entitlement window ("a window ending exactly where the next one begins does not overlap it") while the first reservation order is still live, so PRD:220 and PRD:210 do not jointly determine this rejection; and the scaffold's §1.8 half-open-interval instance asserts the opposite behaviour for exactly this flow. PRD-silence category: **unique-derivability failure (ERROR PRECEDENCE SILENCE + COMPUTED-FIELD SILENCE across PRD:210/220)**.
- Assertion deleted (not the whole test): `assert (approved − reversed) == 0` in `test_rejecting_an_approved_reimbursement_moves_the_cents_to_reversed`. PRD:3.1 names the three totals but never states which is subtracted from which, and neither name is namespaced with `cents`, so the direction is not derivable. PRD-silence category: **COMPUTED-FIELD SILENCE**. The test's substantive assertions (approved 34425→0, reversed 0→34425) are kept.

### Fixes applied to `test_helpers/`

- `fixtures.py` — `advance_claim`: rewrote state-aware and idempotent. Previously it recursed into the `SUBMITTED` step unconditionally and returned whatever the transition returned — for `target="DISPATCHED"` that is the **ReplacementOrder**, so `ctx["claim"]` became an order (caused `IndexError` in three tests, made `{"claim_id": …}` list filters silently return `[]`, and fed an order id into `claim_deny`). Now it skips steps already done and always returns the claim row.
- `fixtures.py` — `setup_suspended_installer_with_claim_history`: removed the now-invalid `dispatch_order(order["id"])` after `dispatch_claim`, because PRD:208 / scaffold:429 create that order **already `DISPATCHED`**, so the extra dispatch was refused `ERR_INVALID_STATE`.
- `fixtures.py` — `setup_system_with_units`: added and forwarded `homeowner_name` / `homeowner_email` (the test passing them hit `TypeError`; `commission_system` already accepted them).
- `fixtures.py` — `list_orders`, `list_campaigns`, and a new `list_claims`: request `limit=100`. The collections are paginated with a default of 10, so a 20-unit campaign's 20 synthesized orders were silently truncated to 10 and the counter assertions failed.
- `fixtures.py` + all suite files — fixture lots used `defect_threshold_pct=100.0` to stay out of RECALL, but PRD:172's comparison is **inclusive** ("at or above the threshold"), so a fixture lot whose only unit fails reads exactly 100.00% and crosses into RECALL, which then blocks claim filing with `ERR_LOT_RECALL_ACTIVE`. Raised to `1e6` (still a legal `> 0` threshold), restoring the fixtures' own documented intent.
- `test_users.py`, `constants.py`: unchanged.

### Fixes applied to `test_suite/`

- Twelve instant-equality assertions compared against truncated `…T00:00:00Z`; PRD:43/80 require "an ISO 8601 UTC instant with **three fractional digits**". Corrected the literals (and `certified_until` to 2029 for the 36-month term).
- `test_09_endpoints_and_consistency.py` — certification-lapse test: the clock was set to 2028-10-01, which is *before* the 36-month term end (2029-09-01), so the installer was still ACTIVE. Moved past the term.
- `test_09_endpoints_and_consistency.py` — ranking assertions re-expressed against units looked up by `installed_at` rather than by list position, and reduced to the property PRD actually states ("the entity identifier is never used as a tie-break"); PRD never pins relative `created_at`/`installed_at` order between identical-`installed_at` candidates.
- `test_06` / `test_08` — three labor fixtures commissioned at 2025-09-01 (12 months ⇒ age factor 1.000 ⇒ net 45900) while asserting PRD:230's worked 34425, which is four GOLD hours on a **ninety**-month system. Re-anchored to 2019-03-01 so the age factor and the expected literal agree.
- `test_03_cascades.py` — removed `assert order["dispatched_at"] is None` after campaign cancel; PRD:184 drives orders to CANCELED but only PRD:214 (reactivation) nulls `dispatched_at`, so the check was not derivable.
- `test_01_entities_and_state_machines.py` — claim-reopen test now re-fails the unit before reopening, because PRD:204 / scaffold:461 admit a CLOSED reopen **only while the unit is FAILED or OFFLINE**; the setup had left it ONLINE.
- `test_07_temporal_overlap.py` — adjacent-window test started the second system at 2045-01-02, the *base* end, but the live window runs to the **extended** end (2045-01-01 + 120 months = 2055-01-01), so 2045-01-02 is inside, not adjacent. Moved past the extended end.

### Fixes applied to `implementation/`

- `views/lots.py` + `services/lots.py` — a manual lot override was being erased: `OPEN_CAMPAIGN_BY_HAND` set `lot_status = RECALL` and then immediately called `evaluate_lot`, which recomputed the status from the (usually zero) defect rate and reverted it to `NORMAL`, losing the operator's recall and breaking campaign activation with `ERR_LOT_NOT_IN_RECALL`. Added a sticky `status_overridden` flag, set by `FORCE_WATCH` / `OPEN_CAMPAIGN_BY_HAND` and cleared by `CLEAR_RECALL`, which `evaluate_lot` honours — matching PRD:176 ("`FORCE_WATCH` places the lot in `WATCH` **regardless of its rate**"; "`OPEN_CAMPAIGN_BY_HAND` **marks the lot `RECALL`**").
- `services/common.py` — `recompute_unit` recomputed `replacement_count` as INSTALLED-orders-only, clobbering the explicit increment PRD:220 requires when a billed-replacement entitlement is recorded. Now counts each position once: an INSTALLED order counts, and an entitlement counts unless its own reservation order has been installed (requires the new `reservation_order_id` link written in `views/billing.py`).
- `views/claims.py` — moved the `expected_unit_version` guard to **after** `claim_filing_gates`. PRD §2.5 orders the business tier as ownership → certification → safety → referential → temporal → fiscal, and the version guard is the fiscal-tier check, so certification must pre-empt it (three tests assert `ERR_INSTALLER_NOT_CERTIFIED`, not `ERR_STALE_UNIT_VERSION`, when both conditions hold).
- `services/orders.py` — `recompute_campaign_counts` was re-deriving `dispatched_count` downward as orders were cancelled, contradicting PRD:178 ("sets `dispatched_count` to the number synthesized"); reactivation should lower the withdrawal tally, not the synthesis tally.

### A fix I applied and then reverted

I added PRD:210's "a unit cannot be double-shipped" guard to entitlement creation. That was **wrong**: PRD:220 explicitly admits an adjacent second entitlement (indeed a second entitlement *window*) on the same unit, and the scaffold's §1.8 half-open-interval instance asserts exactly that. The guard broke two tests and was reverted in the next sweep. Recorded here because the same tension is what made the deleted test non-derivable.

### Step 8 hand-off (implementation/ files changed by Step 7)

`views/lots.py`, `services/lots.py`, `services/common.py`, `views/billing.py`, `views/claims.py`, `services/orders.py`.

### Step 8 hand-off (PRD passages known to diverge from the shipped implementation)

- PRD:128 — "the installer must have at least one hundred decided claims on record … before the promotion is granted". The implementation has **no** claim-history precondition; `CONST.claims_for_level_up` is referenced but never defined in `SCAFFOLD.yaml` and absent from both design indices. Must be corrected.
- PRD:160 vs PRD:220 — `replacement_count` is defined two incompatible ways (INSTALLED-orders-only vs. also incremented by an entitlement). The implementation now counts each position once.
- PRD §2.5 vs §3.6 — the version guard's position relative to the certification gate. The implementation now follows §2.5.

## Step 8: Finalize PRD — 2026-10-01T05:12:00.000Z

**Step 8 was executed by the orchestrator directly** (Agent tool unusable this session, as recorded in Step 7). Method followed exactly: `cp PRD.md PRD_FINALIZED.md`, edits applied only to `PRD_FINALIZED.md`, every edit traced to a `<step_7_diff>` item, no new sections, minimal inline revisions.

**Line counts:** `PRD.md` 351 → `PRD_FINALIZED.md` 351 (no structural change). Char delta: 71331 → 71697 (**+366, +0.51%**).

### Changes (one bullet per edit)

- **§3.1 level progression — revise — removed the 100-decided-claims precondition**, leaving the single-step rule as the whole precondition — `views/installers.py:set_installer_level` (no `decided_claims` check).
- **§3.3 `replacement_count` — revise — defined as one count per replacement position**, an INSTALLED order counting once and an entitlement counting once, with an entitlement and the later install of its own reservation order sharing one position — `services/common.py:recompute_unit` (lines 209–220), `views/billing.py:132`.
- **§3.6 claim gate order — revise — the version guard yields to the four gates**, so the certification gate is the reported failure when both would refuse — `views/claims.py:create_claim`.
- **§3.5 `dispatched_count` — revise — declared a lifetime tally that does not fall on cancellation**, with live orders being `dispatched_count` less `canceled_count` — `views/campaigns.py:activate_campaign`, `services/orders.py:recompute_campaign_counts`.

### Per-edit pre-edit search log

1. **E1 — subject:** who may be promoted, and what history the promotion requires.
   **(b) impl paths enumerated:** `views/installers.py:set_installer_level` (the rung check, the removed threshold check, the EXPIRED→ACTIVE restamp); `services/common.py:decided_claims` (only two callers — `claim_approval_rate_pct` and the removed check); `services/common.py:lazy_installer` / `require_active_certification`. Confirmed `decided_claims` has no other consumer.
   **(c) wording adjustment:** none — the new sentence names no claim-history requirement at all, so no other path can be mis-described; §3.1's separate `claim_approval_rate_pct` prose (PRD:130) is untouched and still accurate.
2. **E2 — subject:** how `replacement_count` is derived.
   **(b) impl paths enumerated:** `services/common.py:recompute_unit` (the counter), `views/billing.py:create_entitlement` (increment + `reservation_order_id` link), `views/systems.py:177` (init 0), `shapes.py:109` (serialisation), and every recompute caller.
   **(c) wording adjustment:** widened to "counts once … are not counted twice" rather than asserting a plain sum of two collections, because the plain sum is exactly the double-count the implementation avoids.
3. **E3 — subject:** the version guard's precedence at claim filing.
   **(b) impl paths enumerated:** `views/claims.py:create_claim` (guard now after `claim_filing_gates`), `views/units.py:claim_filing_gates` (the four ordered gates), `views/orders.py:create_order` (its own guard, still before claim existence — **not** in scope).
   **(c) wording adjustment:** scoped the claim to "in this operation" so the sentence cannot be read as weakening the guard on `POST /warranty/replacement-orders`, which keeps its earlier position.
4. **E4 — subject:** `dispatched_count` semantics across cancellation and reactivation.
   **(b) impl paths enumerated:** `views/campaigns.py:activate_campaign` (the sole setter), `views/campaigns.py:cancel_campaign`, `views/campaigns.py:close_campaign`, `views/orders.py:reactivate_order`, `services/orders.py:recompute_campaign_counts` (the sole recomputer), `shapes.py` preview/serialisation.
   **(c) wording adjustment:** added the explicit relation "live = `dispatched_count` − `canceled_count`" so the sentence stays true on the reactivation path, where `canceled_count` falls while `dispatched_count` holds.

## Step 9: Complete PRD — 2026-10-01T05:11:00.000Z

**Step 9 was executed by the orchestrator directly** (Agent tool unusable this session). Method followed: `cp PRD_FINALIZED.md PRD_COMPLETED.md`, edits applied only to `PRD_COMPLETED.md`, exhaustive walk of `implementation/` against the PRD.

**Source file:** `PRD_FINALIZED.md` (71697 chars, 351 lines) → `PRD_COMPLETED.md` (72467 chars, 351 lines). Char delta **+770 (+1.07%)**, no structural change.

**Counts:** 7 ambiguity-pins, 0 mismatch-revisions.

### Ambiguity-pins

The scan was driven by an automated pass over every response-shape key in `implementation/shapes.py` (131 keys) checked against the PRD text. It found 12 keys the PRD never names, all of them implementation-chosen response field names for reads whose shape the PRD describes only in prose or through the §4 endpoint table. Four of the twelve are asserted verbatim by the test suite (`active_units`, `pure_rank_unit_ids`, `guaranteed_first_unit_ids`, `lot_only_model_code`), so a PRD-only implementer could not have been guaranteed to produce them — these were the material silences; the remaining eight were pinned for uniformity. After the pins the residual set is empty.

- **§3.3 coverage window — insert — named the coverage read's interval endpoints `coverage_start_at` and `coverage_end_at`** — `shapes.py:coverage` (the endpoint table only said "the closed coverage window").
- **§3.4 monitoring read — insert — named `system_age_months`, `active_units`, `failed_units`, `per_unit_rate_cents`, `metering_fee_cents`** — `shapes.py:monitoring_summary` (the table said only "commissioning vintage, active unit count, failure count, unit rate, and monthly metering fee").
- **§3.5 preview — insert — named `pure_rank_unit_ids`, `guaranteed_first_unit_ids`, `lot_only_model_code`** — `shapes.py:campaign_preview`.
- **§3.8 quote — insert — keyed the quote by `reimbursement_id`** — `shapes.py:labor_quote`.
- **§3.7 entitlement — insert — keyed the recorded entitlement by `entitlement_id`** — `shapes.py:billing_entitlement`.
- **§3.4 billing correction — insert — keyed the correction by `period_month_id`** — `shapes.py:billing_correction`.
- **§3.9 share link — insert — keyed the minted link by `share_link_id`** — `shapes.py:share_link`.

### Behaviours walked and confirmed already pinned (no change)

Endpoint-by-endpoint pass over all 67 routes: RBAC role sets match the §4 table; the six calculations match §2.9 precision and the §3 formulas; all seven state machines match their transition tables; the §2.8 OCC guard, §2.3 pagination defaults, §2.4 identity/versioning and the §2.2 envelope all match. Two implementation choices were checked specifically because they are easy silences and both were already covered: `status_overridden` is internal-only (absent from `shapes.py`, so no response-shape leak), and `reservation_order_id` likewise never appears in `billing_entitlement`.

### Note for the doc-generator feedback loop

The `entitlement_id` / `period_month_id` / `share_link_id` class of silence is systematatic: the §4 endpoint table uses the *path* noun (`{id}`) while the response serialiser keys the row by a role-specific name. Worth a Zero-Silence-Rule addition.

## Pipeline complete — 2026-10-01T05:12:00.000Z

Final state: **85/85 tests passing in 8/8 parallel stability rounds**, implementation in-memory-only and unseeded, and `PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md` all present. No implementation file was written after the final sweep.
