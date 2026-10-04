# Worklog — task_3306_corporate_real_estate_outsourcing_transaction_management_facilities

## Step 1: Create task directory — 2026-09-30T19:06:36.222Z

Task directory pre-allocated by the caller at `./tasks/task_3306_corporate_real_estate_outsourcing_transaction_management_facilities/` with `workspace/` already present. Verified it exists; no new index computed and no other `task_*` directory created. `INSTRUCTION.md` present at project root.

## Step 2: Generate scaffold — 2026-09-30T19:44:53.908Z

All three artifacts are generated and lint-clean. Final report:

## Deliverables

All three files written to `/home/ubuntu/github/CodingPRD/tasks/task_3306_corporate_real_estate_outsourcing_transaction_management_facilities/`:

- `SCAFFOLD.yaml` — §1.0–§1.7 (127 KB). No `scaffold_difficulty_design` / `scaffold_corner_design` key.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`, 9 rule blocks × exactly 2 instances = **18 instances**.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`, 48 instances (46 active + 2 `excluded_because` stubs)

Generated purely from the scenario + skill spec; no sibling `task_*/` directory was listed, globbed, grepped, or read.

## Scaffold shape (much harder than expert band)

- **16 entities, 106 endpoints, 28 error codes, 13 calculations, 12 state machines, 30 validations, 8 roles, 2 OCC rules.**
- Archetype: Multi-party negotiation + Compliance/audit; layers: OCC, cascading side effects, dual-variant calc, derived-field reconciliation, ops-run checkpoint. `entity_topology: flat`, `state_machine_shape: cyclic`, `role_model: approval_chain`.
- The CBRE scenario's own nouns drive structure: PortfolioAccount / Lease pipeline / TransactionRequest approval chain / CommissionRecord credit-vs-fee netting / BrokerEngagement market deployment / ServiceLevelKpi gainshare+penalty / FacilitiesVendor + FacilitySite / ConsolidationProject / Scorecard / DisciplineAudit / DataLicense / TransitionTask + offboarding, plus AccountAssignment (entity-backed approval authority) and AuditReview.
- Logical clock `POST /api/_clock/set_current_utc` with pinned default `2026-09-01T00:00:00Z`; drives lease-expiration buckets, KPI re-measurement, escalation counts, overdue-task expiry.

## Difficulty-rule coverage (§1.8)

`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant` — 2 instances each, each honoring its differentiation clause (different entity domains, different formula modes (a)+(b), different entity pairs, different interval semantics, different conserved quantities, different error-category pairs).

All formula-derived asserts were computed by executing the formulas as code before pinning literals, e.g.:
- commission rounding order: `61666.61 + 35150.19 = 96816.80` vs `96816.79` sum-then-round;
- consolidation rounding order: provisional `378135.12` vs final `378135.11`;
- broker split: `1110000.00 + 740000.00 == 1850000.00`;
- KPI penalty leg: `3000000 * (9100-8600)/10000 = 150000.00`;
- completion floor: 2/3 → `6666` (not 6667).

## Key consistency work during generation

The §1.8/§1.9 setup chains forced several §1.5/§1.4/§1.6 corrections (the design files act as a §1.5 audit): narrowed the safety-validation `applies_to` so cooling-off is reachable; added `BrokerEngagement` and missing state-machine transitions (`ConsolidationProject.IN_REVIEW→PLANNED`, `BrokerEngagement EXECUTED→TERMINATED`); added business endpoints (`/broker-engagements/{id}/execute`, `/leases/{id}/expire`, `/transition-tasks/{id}/expire`, `/account-assignments`, audit-review child routes) rather than test-driving shims; added conserved-quantity fields (`fee_ledger_credit_cents`, `broker_pool_allocated_cents`, `portfolio_leased_sqft`); removed an unreachable error code so every §1.6 entry is triggerable.

## Verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    106
  §1.1 entities declared:     16
  §1.8 instances scanned:     18
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  493

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional checks passed: no forbidden concurrency vocabulary; every `grounds:` reference resolves; instance names unique across both design files; all `common_fields` entities carry `version`; a `POST /_clock/set_current_utc` and a `GET /audit-reviews/{id}` parent-create = update endpoint cover the two OCC parents so `expected_*_version` is always a `${var}`.

### Orchestrator verification (independent of subagent claims)

- All three files exist on disk: `SCAFFOLD.yaml` (127391 B), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (60540 B), `SCAFFOLD_CORNER_DESIGN.yaml` (86115 B).
- All three parse as valid YAML with the expected top-level key sets.
- Programmatic counts confirm the claimed shape: 16 entities, 12 state machines, 13 calculations, 30 validations, **106 endpoints**, 28 errors, 2 concurrency rules; primary_archetype `Multi-party negotiation`, secondary `Compliance / audit`, role_model `approval_chain`, state_machine_shape `cyclic`, api_prefix `/api`.
- ⚠️ RISK FLAGGED FOR STEP 6: the 106-endpoint count is far above the ~40-endpoint threshold at which impl-gen has previously degraded (returning a rambling report instead of writing files). Step 6's prompt will carry an explicit instruction to write files to disk incrementally and NOT stop at a report; Step 6 output will be verified on disk before proceeding.

## Step 3: Copy shared files — 2026-09-30T19:45:19.781Z

Copied `./INSTRUCTION.md` (1424 B) to `tasks/task_3306_corporate_real_estate_outsourcing_transaction_management_facilities/workspace/INSTRUCTION.md`. Verified present on disk.

## Step 4: Generate PRD — 2026-09-30T19:59:13.702Z

PRD generated and verified. All three Hard Contracts pass.

## Artifact

`/home/ubuntu/github/CodingPRD/tasks/task_3306_corporate_real_estate_outsourcing_transaction_management_facilities/workspace/PRD.md` — 397 lines, ~10k words, ends at §5 with no audit footer.

**Structure** (skeleton derived from this domain, not the example's): §1 Introduction; §2 with 11 domain-titled subsections (`Account Governance and Lifecycle Gating`, `Fee Ledger Conservation and Commission Credits`, `Occupancy Area Conservation and Committed Intervals`, `Approval Chain and KPI Thresholds`, …); §3 with 9 subsections grouped by business process (account stand-up → lease pipeline → transaction requests → broker deployment + fee accruals → facilities → consolidation → governance → offboarding → data rights and clock); §4 with 106 endpoint rows; §5 with 28 error rows.

## Hard Contract reports

**Contract 1: Field-Name Coverage**
```
Field coverage check:
- entities[].fields: 118 required, 118 present, 0 missing
- endpoints[].request_body: 76 required, 76 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing
Status: PASS
```

**Contract 2: Rule Coverage**
```
Rule coverage check:
- validations[] with priority: 30 checked, 30 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_account_version + ERR_STALE_VERSION all named), 0 missing
- state_machines[].transitions: 47 checked, 47 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 30 checked, 30 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 106 checked, 106 expressed, 0 missing
- entities[].fields[] structured content: 118 checked, 118 reconstructible from prose, 0 missing
- sibling-branch symmetry: 49 groups checked, 49 with equal prose density, 0 asymmetric
Status: PASS
```

**Contract 3: §3 Path Purity**
```
Path purity check (§3 only):
- backtick tokens scanned: 604
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Key notes

- **§2.2 is byte-identical** to `skills/prd-bench-doc-generator/section-2.2-response-structure.md` (verified by string compare, including the fenced JSON — fences balanced at 4).
- **Contract 2 emphasis** where the scaffold is densest: the pinned evaluation orders in `commission_credit_nets_fee`, `kpi_net_adjustment`, `weighted_scorecard_composite` and the two `consolidation_savings_estimate` variants are all written as prose with exact operator direction and no fuzzy hedging; the three-hop termination cascade (close → vendor `TERMINATED` → site `DISPOSED` → `LINE_ITEM` licence `REVOKED`) is spelled out hop-by-hop; the two OCC rules are framed purely as stale-version mismatches (no "simultaneous"/"race" wording).
- **Scattering**: request-body parameters are distributed across subsections (e.g. `expected_account_version` appears in §2.7 and in the lease-revision and audit-review narratives; `client_consent_confirmed` appears only in §3.9); all constants are embedded in business statements with unit conversions where useful (`72 hours`, `30-day cooldown`, `1.10` cap, `145/118/96 cents per sq ft` at the `250,000`/`750,000` thresholds).
- **Two process notes.** (1) A naive backtick-parity scan of the PRD derails on the fenced JSON blocks in §2.2, which produces a false "everything is missing" diff — the Contract 1/3 checks must strip ```` ``` ```` fences first. (2) The AUTHORS' scaffold has 106 endpoints, well above the ~40 that a downstream impl-gen step tolerates; not a PRD issue, but worth flagging to the orchestrator.

### Orchestrator verification (independent of subagent claims)

- `workspace/PRD.md` exists on disk, 74154 B, 397 lines / 9999 words.
- Section headers confirmed: §1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue; no audit footer.
- §4 contains 108 table rows (106 endpoint rows + header + separator); §5 contains 29 rows (28 error rows + header). 28 distinct `ERR_*` tokens found, matching the scaffold's 28 error codes exactly.

## Step 5: Generate unit tests — 2026-09-30T20:35:08.907Z

Generated test infrastructure is complete and self-consistent. Final verification passed.

## Summary

Produced the full unit-test infrastructure for `task_3306_corporate_real_estate_outsourcing_transaction_management_facilities`, translated strictly from the two design indices.

**`test_helpers/`** (9 files): `types.py` (all 16 entity TypedDicts — every entity carries `id/created_at/updated_at/version` per PRD §2.5; plus status/role enums), `api_client.py` (106 endpoint methods, one per PRD §4 row), `api_errors.py` (28 error IDs registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (with mandatory per-instance builders `make_account_executive_headers` / `make_approval_authority_headers` for the two `entity_backed` roles), `fixtures.py` (~600 lines, 5 tiers), `__init__.py`.

**`test_suite/`** (15 test files + `conftest.py`): 82 tests.

**Coverage audit (clean):**
- Difficulty queue A: 18/18 instances, each with exactly 2 tests (36 tests).
- Corner queue B: 46/46 non-stub instances, each with exactly 1 test (46 tests). Both `excluded_because:` stubs were skipped — their cited queue-A owners are covered (2 tests each). Zero stub tags emitted.
- 82/82 tests carry exactly one `Design:` tag, all resolving to real `name:` fields in the source yamls. No untagged, dual-tagged, or dangling tags.
- C1 verbatim: 131 quoted fragments, 0 mismatches against a normalized `grep` of `PRD.md`. No `scaffold`/table/§ references leak into generated code; no skip/xfail/pytest.mark.skip anywhere.

**PRD-first adjudication — instances where the design index's literal contradicts the PRD contract (documented, re-derived, not weakened):**
- `Difficulty/dual_variant_calc/standby_fee_credit_conversion_vs_fee_level_netting`: the recipe's `applied_credit_cents == 7850000.00` is not derivable from PRD §2.9 (`applied_credit = min(total_credit, gross_fee + self_perform_credit)`, which yields 4,720,000 at the stated tier). I kept the recipe's full setup and asserted the two PRD-computed per-record credits summed (6,000,000 + 1,850,000), which §3.4 verbatim requires. The paired test asserts the PRD-derivable annual fee 45,350,000.
- `Difficulty/non_linear_state_machine/consolidation_review_replan_fork_returns_to_planned`: recipe literal `378135.12` is wrong for the stated inputs (per-site rounded sum × 1.05 = 378,134.54). I asserted the PRD-derivable figure and made the three sites real (`created_at` ASC) so the positional per-site arrays are unambiguous.
- `Difficulty/transitive_cascade/account_close_cascades_vendor_then_site_then_data_license`: recipe set S1 to CONSOLIDATING via a window starting before the recipe's own clock — un-derivable timing. I assert the OCCUPIED→DISPOSED second-hop rule from the verbatim §3.8 cascade prose.
- `Validations/unlicensed_broker_assign...`: recipe's `as_user_id: ${auth}` precedes the capture that defines `auth`; I drove the PRD-legal order (create engagement → assign → expect `ERR_BROKER_NOT_LICENSED` at assign).

Notes: tests assume the runner's per-test server restart (no DB priming). Verification was limited to compile + `pytest --collect-only` + static contract audits — no live server was available, so behaviors were not executed end-to-end. No sibling `task_*/` directory was read; no broad kill patterns used.

### Orchestrator verification (independent of subagent claims)

- `test_helpers/` present with 9 files (`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`); `test_suite/` present with `conftest.py` + 15 `test_*.py` files.
- 82 test functions counted programmatically (`^\s*(async )?def test_`), matching the claimed 82.
- 82 `Design:` tags; distinct set = 18 difficulty instance names × 2 + 46 corner instance names, exactly as claimed.
- `pytest.mark.skip` / `pytest.mark.xfail` / `pytest.skip` occurrences across `test_suite/` and `test_helpers/`: **0**.
- These adjudicated literals (the 4 PRD-first re-derivations above) are flagged for Step 7 attention: each is a place where the design index and the PRD disagree, so Step 7 may see failures that trace to the *design file*, not to the implementation.

## Step 6: Generate implementation — 2026-09-30T20:58:39.812Z

Implementation complete and verified. Final state:

**Files written** — `/home/ubuntu/github/CodingPRD/tasks/task_3306_corporate_real_estate_outsourcing_transaction_management_facilities/workspace/implementation/`
- `start.sh` (executable, guarded `import flask` check, `exec python3 app.py`), `requirements.txt`, `app.py`
- `core/`: `db.py` (in-memory store, empty at boot, logical clock, Decimal helpers), `errors.py` (all 28 error IDs → HTTP), `response.py` (meta/response_type/data envelope), `auth.py` (X-User-ID / X-User-Role, role table, per-account assignment gate), `calc.py` (all 13 calculations), `domain.py` (lifecycle gate, cascades, recompute pipelines)
- `routes/`: `registry.py` (decorator, validation, pagination), `accounts.py`, `leases.py`, `transactions.py`, `brokers.py`, `facilities.py`, `consolidation.py`, `governance.py`, `licenses.py`, `transitions.py`, `clock.py`

**Coverage** — 108 routes registered, matching the scaffold's endpoint table (106 declared + the `POST /api/audit-reviews` OCC entry point and the account-nested listings). All 16 entities, 12 state machines, 13 calculations, 30 validations and 28 error codes are implemented. Storage is in-memory dicts keyed by id; no seeding or disk persistence anywhere.

**Self-boot check** — `PORT=<free> bash start.sh` launched twice, each time answering `POST /api/accounts` (201) and `GET /api/accounts` (200) plus `POST /api/_clock/set_current_utc` (200); both PIDs killed individually, no stray server left.

**Notes on ambiguous spec points (judgment calls made, not blockers)**
- `expected_account_version` is enforced as required (wrong/missing → `ERR_STALE_VERSION`/`ERR_INVALID_REQUEST`) on `POST /api/leases/{id}/revise`, `POST /api/scorecards/{id}/publish`, both audit-review paths.
- The assignment gate is unconditional: a mutating call on an account that already has assignments requires X-User-ID to match an assignment of the acting role. Approval decisions additionally require the X-User-ID to be an `APPROVAL_AUTHORITY` assignment on the account.
- `ERR_CONSENT_REQUIRED` (validation priority 10) is enforced on the four declared endpoints — account transitions/closure, vendor activation, licence grant (plus licence rejection tracks a priority-11 consent check).
- Tenant-scoped purge of hardcoded `expiration_bucket` semantics: the bucket is derived at creation from the logical clock rather than being frozen at `UNASSIGNED`.
- Scorecard publication updates the account's `kpi_code == "SLA_BPS"` row; the scaffold's prose names that row explicitly, so no other KPI is touched.

Two environment caveats worth flagging: the model endpoint duplicated one large parallel tool call early on, and one `Write` batch was truncated — both were recovered by writing in smaller sequential chunks, so nothing is missing from disk.

### Orchestrator verification (independent of subagent claims)

- Files confirmed on disk: `start.sh`, `requirements.txt`, `app.py`, `core/` (7 modules), `routes/` (11 modules) — 3277 total source lines, no `__pycache__`-only gaps. The explicit incremental-write instruction in the prompt defeated the 106-endpoint scale degradation; this is the first time at >40 endpoints that impl-gen produced files rather than a report.
- **Isolation rule held:** `grep -rn 'test_suite\|test_helpers\|SCAFFOLD_DIFFICULTY\|SCAFFOLD_CORNER'` across all `.py`/`.sh` returned **zero** matches.
- **No persistence:** no `sqlite`/`pickle`/`shelve`/`json.dump`/file-write; the only `db` matches are imports of the in-memory `core.db` module. `core/db.py` header reads "In-memory store. Starts empty on every boot; never persisted, never seeded." and `CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0)`.
- `app.py` binds `host="0.0.0.0"`, `port=int(os.environ.get("PORT", "10000"))` — correct.
- **Role names align exactly** between `test_helpers/test_users.py` and `core/auth.py` ROLES: AccountExecutive, TransactionManager, ApprovalAuthority, FacilitiesManager, OccupancyPlanner, GovernanceManager, DataSteward, TransitionManager.
- **Independent orchestrator boot test** (own PIDs only, killed individually): server starts under `PORT=<free> bash start.sh`; `GET /api/accounts` returns `response_type:"array"` with `has_more`/`limit`/`offset`/`total_count` in `meta`; successful create returned the full account object with logical-clock timestamps `2026-09-01T00:00:00.000Z` (not wall-clock) and the conserved-quantity fields (`fee_ledger_credit_cents`, `broker_pool_allocated_cents`, `portfolio_leased_sqft`); error paths return the correct `response_type:"error"` envelope.

## Step 7: Run tests and iterate — 2026-09-30T21:40:05.381Z

Confirmed: all source edits predate the results files (no writes during the sweep), so the clean 8-round sweep is valid. 82/82 passed in every round.

## Summary

**Iterations run:** 2 (diagnosis sweep → one batch of fixes → verification sweep). Final state: **8/8 parallel rounds green, 82/82 tests passed in every round.**

**Tests deleted:** none. All 82 tests trace to PRD prose; two assertions were *relaxed* to their PRD-covered subset (coverage corrections, not weakenings):
- `test_14 ... test_unassigned_approver_is_refused` — a foreign ApprovalAuthority assignment satisfies neither the §2.1 assignment gate (`ERR_NOT_ASSIGNED`) nor the §3.3 approval-chain ownership lookup (`ERR_UNAUTHORIZED`); PRD does not pin which 403 fires first. Relaxed to `validate_error_is_one_of([...])`.
- `test_15 ... test_lease_expiration_bucket_survives_a_clock_advance` — PRD states the recompute *trigger* and the bucket enum but never pins the day-thresholds separating `NEAR_TERM`/`MID_TERM`/`LONG_TERM` (the scaffold pins them nowhere either). Split per STEP 1c: kept the covered "bucket stays a present, valid enum member after the clock advances" assertion, dropped the underivable exact value.

**Fixes to `test_helpers/`:**
- `fixtures.py` `setup_approved_request` / `setup_pending_request` — never submitted the lease, so it stayed `PIPELINE` and the PRD §3.2 approval decision could not cascade it to `BROKER_ASSIGNED`. Now submits the lease and re-reads it (stale-dict bug). `setup_executed_lease_with_accrual` — same missing lease submit.
- `fixtures.py` `setup_executed_lease_with_accrual` — executed *both* the broker engagement and the lease; PRD §3.4 makes the lease route the record-posting one, so the engagement execute left the request `EXECUTED` and the lease route silently posted nothing. Removed the engagement execute (the two routes are alternatives).
- `fixtures.py` `setup_termination_cascade_account` / `setup_offboarding_with_granted_licence` — hardcoded the same `account_name`, violating PRD §3.1 uniqueness when two tests share one server session. Added a distinct per-call default.
- Fixture header role usage in `test_03` — `TransactionManager` was used for `get_vendor`/`get_site`/`get_data_license`, none of which PRD §4 authorises for that role. Switched to FacilitiesManager/DataSteward.

**Fixes to `test_suite/`:**
- `test_03` cascade tests: distinct account names; correct read roles.
- `test_05` completion-floor tests: `complete_transition_task(task)` double-started the task (`start` twice → `ERR_INVALID_STATE`) because the helper already starts. Now calls `api.complete_transition_task` directly.
- `test_07` half-open-window tests: sites lacked an `consolidation_project_id` pointing at an **APPROVED** project, which PRD §3.6 requires. Added an approved project and attached the sites.
- `test_10` revision-cap test: `range(2)` left `revision_count` at 2, not the 3 the PRD cap describes → `range(3)`.
- `test_10` vendor-suspension test: activated the vendor *after* the failed audit, tripping the §3.9 vendor-activation consent gate. Reordered.
- `test_04` priority test: asserted `ERR_CONSENT_REQUIRED`, but PRD §3.7 names `ERR_COOLING_OFF_ACTIVE` for an approval decision taken during a failed audit's cooling-off window.
- `test_11` CENTS-boundary test: off by 50,000 (`39_450_000` instead of `39_500_000`), asserting the *wrong* side of the 500,000-cent threshold.
- `test_01` feasibility: `set_clock("2026-07-01")` runs the clock *backwards* from the default `2026-09-01`; removed the four calls.
- `test_15` tier-change test: absolute `version == 2` is not PRD-derivable (the activation transition's version arithmetic is unstated); changed to `before["version"] + 1`.

**Fixes to `implementation/`:**
- `routes/leases.py` `lease_launch_marketing` — evaluated the lease-state check (`ERR_NOT_TRANSITIONING`, priority 9) ahead of the missing-assigned-engagement check (`ERR_INVALID_STATE`, priority 8). PRD §3.2 says the latter is "rejected before any business check", so reordered.
- `routes/transactions.py` `submit_transaction_request` — applied the cooling-off gate, which PRD §3.7 scopes to "account closure, conversion, offboarding, approval decisions and consolidation execution", not submission. Removed.
- `routes/transactions.py` `decide_transaction_request` — fallback allowed any ApprovalAuthority to reject a request they had no assignment on, against PRD §3.3's ownership requirement. Removed.
- `core/calc.py` `consolidation_savings_estimate` — truncated both variants to whole cents, contradicting PRD §3.6's pinned "rounded half-up to 2 decimal places" final step. Now returns 2-decimal values (378,135.12 provisional / 378,135.11 final).

**Not changed:** the two other known-divergence adjudications (`Validation/unlicensed_broker_assign`, the provisional-vs-final netting pair) were confirmed PRD-faithful and pass as shipped.

### Orchestrator verification (independent of subagent claims)

- All 8 `results.{1..8}.json` exist (27.3 KB each) and every round reads `passed=82 / total=82` — confirmed by parsing each file programmatically, not by trusting the report.
- **Sweep invalidation check (post-Step-7 write guard):** newest source mtime = `1790804127` (`test_helpers/fixtures.py`); results mtime = `1790804320`. All source edits precede the sweep's results files, so no `implementation/`, `test_suite/` or `test_helpers/` write happened after or during the clean sweep. The green result is valid.

## Pause / resume note — 2026-10-01T04:07:52.981Z

The host killed all background processes under memory pressure while Step 8's subagent was in flight (after it had written its output file but before its report was recorded). Pipeline resumed from the task directory. Inspected on disk before resuming:

- Steps 1–7 artifacts all present and complete (SCAFFOLD ×3, workspace/INSTRUCTION.md, workspace/PRD.md, test_helpers/ ×9, test_suite/ ×16, workspace/implementation/ ×22 files).
- All 8 `results.{1..8}.json` re-parsed: every round 82/82. Step 7 sweep re-confirmed valid — newest *source* file mtime (`core/calc.py`, 21:31:44) still predates the results (21:38:40). The later `workspace/implementation` directory mtime (21:50:25) was traced to `__pycache__` generation from Step 8 reading modules; no source file changed after the sweep.
- `workspace/PRD_FINALIZED.md` exists (75722 B, written 22:09:18), 397 lines, ends cleanly at §5 — not truncated. Step 8's write completed before the kill; only its report was lost. Rather than re-run Step 8 from scratch (which risks a *different* minimal patch over already-finalized prose), the artifact was verified against the live implementation instead — see the Step 8 entry below.

## Step 8: Finalize PRD — 2026-10-01T04:07:52.981Z

(Spawned 2026-09-30 ~21:5x; subagent killed mid-flight after writing its output. Artifact reconstructed and independently verified by the orchestrator rather than re-run.)

**Output:** `workspace/PRD_FINALIZED.md` — 397 lines, byte-for-byte same structure as `PRD.md` (397 lines), 4 diff hunks / 8 changed lines (≈2% char-delta). Every hunk traces to a Step 7 `implementation/` fix. No new sections added.

**Verification of each hunk against the shipped `implementation/` (orchestrator-run, not subagent claims):**

- **§2.10 decimal-vs-integer field inventory — revise.** The hit-list of decimal fields gained `savings_estimate_cents` and `savings_finalized_cents` on a consolidation project, and the integer list was re-scoped from "every savings field on a transaction request or consolidation project" to "a transaction request's savings fields". **Verified:** `core/calc.py:140-160` `consolidation_savings_estimate` returns via `rhu(x, 2)` (2 decimals) for both variants, written to `project["savings_estimate_cents"]` / `["savings_finalized_cents"]` (`routes/consolidation.py:79,104,128`); while `core/calc.py:83-96` `savings_realization_score` returns via `rhu_int(...)` (integer), written to `savings_provisional_cents` / `savings_final_cents` (`routes/transactions.py:126`, `routes/brokers.py:177`, `routes/leases.py:260`). Hunk is accurate.
- **§3.2 expiration bucket + revision cap — revise.** Replaced the vague "begins as `UNASSIGNED` and is one of … once the clock positions it" with the derivation the code performs, and restated the cap as "three re-openings are allowed". **Verified:** `core/calc.py:262-277` `expiration_bucket_for` — `UNASSIGNED` only when `lease_end_date is None`; `end <= clock` or `days <= 365` → `NEAR_TERM`; `days <= 1095` → `MID_TERM`; else `LONG_TERM`; derived identically at creation (`routes/leases.py:64`). `routes/leases.py:168` rejects at `revision_count >= 3` after three successful increments — cap verbatim.
- **§3.2 marketing launch ordering — revise.** Pre-existing sentence asserted only `ERR_NOT_TRANSITIONING`; revised so the missing-`ASSIGNED`-engagement check is "rejected before any business check with `ERR_INVALID_STATE`". **Verified:** `routes/leases.py:187-208` `lease_launch_marketing` raises `ERR_INVALID_STATE` for a missing assigned engagement even when the lease is not `BROKER_ASSIGNED`, and only raises `ERR_NOT_TRANSITIONING` once an engagement is assigned. Matches the code's own comment citing §3.2/§2.8 priority 8 < 9.
- **§3.3 approval decision — revise (largest hunk).** Adds: decision token sets → `ERR_INVALID_REQUEST`; `level` must be `MANAGER`/`DIRECTOR`/`ACCOUNT_EXECUTIVE`; affirmative decisions require a matching `APPROVAL_AUTHORITY` `AccountAssignment` else `ERR_UNAUTHORIZED` (403); negative decisions do **not**; `ERR_COOLING_OFF_ACTIVE` (422) while a failed audit's window is open; lease follows to `BROKER_ASSIGNED`/`REJECTED` only from `APPROVAL_PENDING`. **Verified line-by-line** against `routes/transactions.py:144-192` — every clause matches (`APPROVE_TOKENS`/`REJECT_TOKENS` gate, level validation, `assignment is None and token in APPROVE_TOKENS → ERR_UNAUTHORIZED`, `domain.cooling_off_gate(account["id"])`, the conditional `pipeline_state == "APPROVAL_PENDING"` lease cascade).

**Note on the NO-NEW-MISMATCH rule:** because the subagent's per-edit pre-edit search log was lost with its report, the orchestrator performed the equivalent check directly — reading the full code path behind each hunk (`core/calc.py`, `routes/leases.py`, `routes/transactions.py`, `routes/consolidation.py`, `routes/brokers.py`, `core/domain.py`) to confirm each revised sentence describes all related callsites, not only the Step 7 site. All four hunks hold; no contradictory callsite was found. Any residual PRD-silence outside these four sites is Step 9's scope.

## Step 9: Complete PRD — 2026-10-01T05:15:48.405Z

Done. `PRD_COMPLETED.md` produced as a minimal inline patch over `PRD_FINALIZED.md`.

## Source / output

| | File | Lines | Bytes |
|---|---|---|---|
| Source | `PRD_FINALIZED.md` (exists, so it was the base) | 397 | 75,722 |
| Output | `PRD_COMPLETED.md` | 397 | 83,557 |

Char delta: **+7,797**. Line count unchanged; heading and endpoint/error-table lines are byte-identical (`diff` over `^#`/`^|` is empty). 30 changed paragraph blocks, all inline in-paragraph inserts/revisions — no new sections, no invented behavior.

Counts: **13 mismatch-revisions, 22 ambiguity-pins**.

Note: a stale `PRD_COMPLETED.md` from a previous run was present; I backed it up to `/tmp/prev_PRD_COMPLETED_3306.md` and rebuilt from `PRD_FINALIZED.md`. Its claims were **not** carried over — see findings below.

## Changes

Each: section — insert/revise — ambiguity/mismatch — what changed — impl anchor.

- §2.1 — revise — **mismatch** — "no assignment ⇒ `ERR_NOT_ASSIGNED`" replaced with the role-shaped rule: gate exempt for account creation and assignment creation, skipped when `X-User-ID == account.id`, opens when the acting role holds no same-role assignment, else requires `assignee_name == X-User-ID` (or `id == X-User-ID` for `ApprovalAuthority`) — `implementation/core/auth.py:69-95`, `:25-29`
- §2.5 — revise — **mismatch** — "fourteen" → "seventeen" entity types — `implementation/core/db.py:9-16`
- §2.5 — revise — **mismatch** — added **AccountTransition** to the enumerated list — `implementation/core/db.py:9-16`
- §2.6 — insert — ambiguity — `commission_pct` is stored as the supplied decimal fraction (0.025 stays 0.025); a site's `sqft_reduction` is truncated to a whole number (12.7 → 12) — `implementation/routes/facilities.py:194`, `core/calc.py:39-41`
- §2.7 — revise — **mismatch** — the audit-review OCC requirement is split: flat `/api/audit-reviews` requires `expected_account_version`, the audit-scoped route accepts it optionally — `implementation/routes/governance.py:234-244` vs `:201-219`
- §2.7 — insert — ambiguity — only the request-driven lease forks (approve/reject/withdraw/cancel) leave account `version` untouched — `implementation/routes/leases.py:139-157`
- §2.8 — revise — **mismatch** — required-field *presence* is checked before identifier resolution, not last; supplied-value type errors stay last — `implementation/routes/registry.py:79-116`
- §2.8 — insert — ambiguity — unmatched path → 404 `ERR_RESOURCE_NOT_FOUND`; known path with unsupported method → 400 `ERR_INVALID_REQUEST` — `implementation/app.py:30-38`
- §2.9 — insert — ambiguity — applied credit is `min(total_credit, gross_fee + self_perform)` — `implementation/core/calc.py:64`
- §2.11 — insert — ambiguity — escalation flag is gated on raw values (exactly-500 shortfall leaves `NONE`) yet still records a non-zero penalty — `implementation/core/calc.py:104-108`, `:243-251`
- §3.1 — insert — ambiguity — update re-applies trim/length/uniqueness, `portfolio_sqft >= 1`, tier enum; other body fields ignored — `implementation/routes/accounts.py:74-105`
- §3.2 — insert — ambiguity — dates are ISO 8601, trailing `Z` or UTC offset accepted — `implementation/core/db.py:83-93`
- §3.2 — insert — ambiguity — approval drives the first `PENDING_APPROVAL` request; rejection drives the most recent request whatever its state — `implementation/routes/leases.py:16-28`
- §3.2 — insert — ambiguity — the lease-reject fork and the request reject/withdraw/cancel escapes apply no temporal or premises check — `implementation/routes/leases.py:146-158`, `:268-276`
- §3.3 — revise — **mismatch** — provisional benchmark is the request's own lease area alone; the term window and same-market lease set are illustrative and unused — `implementation/core/calc.py:83-94`
- §3.3 — insert — ambiguity — only the provisional leg is floored at zero; final savings may be negative — `implementation/core/calc.py:90-93`
- §3.3 — insert — ambiguity — decision token trimmed and matched case-insensitively — `implementation/routes/transactions.py:151`
- §3.3 — insert — ambiguity — an unsubmitted request is banded on the fly from `prior_rent_cents_per_year` — `implementation/routes/transactions.py:164-165`
- §3.4 — insert — ambiguity — engagement born with the three split fields at zero; request on another account → 404 — `implementation/routes/brokers.py:94-96`, `:115-118`
- §3.4 — insert — ambiguity — prior-base limit truncated to whole cents — `implementation/core/calc.py:165-167`
- §3.4 — revise — **mismatch** — lease execution completes with no linked request present — `implementation/routes/leases.py:255-262`
- §3.4 — revise — **mismatch** — `/api/lease-executions/{id}/apply` resolves the account from a lease, account, request or accrual id; no accrual at all → 404, only all-non-OPEN → 409 — `implementation/routes/brokers.py:264-299`
- §3.5 — insert — ambiguity — reinstatement additionally requires `governance_posture == NORMAL` and recomputes `kpi_track` — `implementation/routes/facilities.py:123-133`
- §3.5 — revise — **mismatch** — site `sqft` upper bound only (a value of 0 or below passes); vendor on another account → 404 — `implementation/routes/facilities.py:169-174`
- §3.6 — revise — **mismatch** — planned reduction need not equal the assigned sites' sum at creation; enforced only at start-execution — `implementation/routes/consolidation.py:26-29` vs `:124-126`
- §3.6 — insert — ambiguity — an array shorter than the site list contributes zero past its end — `implementation/core/calc.py:146-152`
- §3.6 — insert — ambiguity — new projects carry four derived figures at zero — `implementation/routes/consolidation.py:38-49`
- §3.6 — insert — ambiguity — consolidation credit = `sqft_reduction × vendor service rate`, earliest OPEN accrual, silently unrecorded when none is open — `implementation/core/domain.py:173-179`
- §3.6 — insert — ambiguity — project approval needs an `APPROVAL_AUTHORITY` assignment; absent `X-User-ID` passes on role match alone; no level check — `implementation/routes/consolidation.py:92-101`
- §3.6 — insert — ambiguity — cooling-off gate sits between site-readiness and the reduction-sum check; start-execution sets `realized_sqft_reduction` — `implementation/routes/consolidation.py:118-129`
- §3.7 — revise — **mismatch** — removed the claim that publication requires `ACTIVE`/`OFFBOARDING`; publication only requires the scorecard to be `DRAFT` — `implementation/routes/governance.py:74-87`
- §3.7 — insert — ambiguity — consent and cooling-off gates are never consulted by resource-creation endpoints — `implementation/core/domain.py:77-87`
- §3.8 — insert — ambiguity — re-opening a transition on an `OFFBOARDING` account reports `ERR_OFFBOARDING_PENDING`, not `ERR_INVALID_STATE` — `implementation/routes/accounts.py:140-146`
- §3.9 — revise — **mismatch** — clock advance does not set `actual_value`; it re-settles only rows already `EVALUATED`/`ESCALATED` from stored values — `implementation/routes/clock.py:46-50`
- §4 — revise — **mismatch** — flat `/api/audit-reviews` creation returns 201; each route serves only its listed method (else 400) — `implementation/routes/governance.py:234-244`, `implementation/app.py:35-38`

## Key findings

- **The prior run's `PRD_COMPLETED.md` was wrong in two directions.** (a) It pinned "`commission_pct` is stored as a whole number of basis points … 0.025 persists as 250" — this runtime stores `Decimal` and serializes `0.03`; the pin contradicted the PRD's own §2.6 ("input configuration values preserve the precision they were supplied with") and `core/calc.py:40`. (b) It appended "Publication carries no assertion that the account be either `ACTIVE` or `OFFBOARDING`" to §3.7 while leaving the original contradictory sentence in place and failing to remove the same claim from §2.7 — a self-contradiction. Both are corrected here.
- **The §2.1 assignment gate is role-shaped, not identity-shaped.** `check_assignment` returns early when the acting role holds no assignment with a matching `assignment_role` (`core/auth.py:88`), so the *first* assignment of a role flips the gate from "anyone" to "only the named assignee". Verified live: an `OccupancyPlanner` with zero assignments creates a project (201); a `FacilitiesManager` acting as a second identity after one same-role assignment exists is admitted (201), never `ERR_NOT_ASSIGNED`. Any PRD pin written as "no covering assignment ⇒ 403" is false for the first principal of a role.
- **Terminal-account gating is far narrower than "every child mutation is blocked":** on a `CLOSED_TERMINATED` account, profile update, fee-accrual creation and assignment creation all still return success; only `create_lease`, `create_transaction_request`, `create_data_license` and account closure are terminal-guarded (`core/domain.py:15-18`). The `DRAFT` branch of §2.4 is likewise inaccurate but was left alone as out of scope for this pass (it would require rewriting §2.4, §2.8 and §3.1).
- **Endpoint set and error catalogue match exactly** (96 routes after normalizing `{id}`/`<id>`; 28 error ids with identical HTTP mappings). No table edits were needed; the only §4 change was the 201/method prose.
- Cross-checked 35 claims against the running server (started on port 38271 with my own PID, killed exactly that PID; `__pycache__` dirs created by the probe were removed).

### Orchestrator verification (independent of subagent claims)

- `workspace/PRD_COMPLETED.md` exists on disk (83557 B, 397 lines) built on `PRD_FINALIZED.md`; section headers §1–§5 identical; `diff` of all `^#`/`^|` (heading + table) lines between FINALIZED and COMPLETED is **empty** — confirming prose-only edits, no table/section churn, so no endpoint/error drift was introduced.
- Spot-checked Step 9's two most structurally-consequential claims against source: `core/db.py` KINDS now holds **17** entries including `account_transitions` (matches the "seventeen" revision), and `core/auth.py:69-95` `check_assignment` is exactly the role-shaped gate described (opens only when the acting role holds a same-role assignment; `ERR_NOT_ASSIGNED` otherwise) — matches the §2.1 revision.
- **Post-Step-9 sweep-invalidation guard:** newest source file mtime is still `core/calc.py` @ 21:31:44 (2026-09-30) and `results.1.json` @ 21:38:40 — neither Step 8 nor Step 9 wrote anything under `implementation/`, `test_suite/` or `test_helpers/` (only `PRD_*.md` files and transient `__pycache__`). The Step 7 clean sweep therefore remains authoritative.
- **Independent end-to-end confirmation round** (orchestrator-run, own server PID managed by the runner): `prd-bench-local-run --isolation per-test-server` against the shipped tree → **82/82 passed, 0 failed, 0 errors, 0 skipped** (144.6 s). The extra `confirm.json` was parsed (82/82) and removed; `__pycache__` dirs cleaned.

## Pipeline complete — 2026-10-01T05:15:48.405Z

Final state: 8/8 Step 7 rounds green (82/82 each) plus an independent confirmation round (82/82); `PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md` all present; no source file written after the clean sweep.