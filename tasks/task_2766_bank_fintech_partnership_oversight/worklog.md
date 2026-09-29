# Worklog — task_2766_bank_fintech_partnership_oversight

## Step 1: Create task directory — 2026-09-04T18:16:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2766_bank_fintech_partnership_oversight` and `.../workspace` (pre-assigned path; no index scan performed).

## Step 2: Generate Scaffold — 2026-09-04T20:35:00.000Z

Ran as three sequential/concurrent subagents rather than one, because the first single-subagent attempt died at the hard 64000-token output cap having written **nothing at all** to disk. Split: (2a) SCAFFOLD.yaml §1.0–§1.7; then (2b) SCAFFOLD_DIFFICULTY_DESIGN.yaml §1.8 and (2c) SCAFFOLD_CORNER_DESIGN.yaml §1.9 launched concurrently. Each was mandated to write in chunked `cat >>` appends and never echo YAML in its visible response.

### 2a — SCAFFOLD.yaml (3493 lines as generated; 3510 after orchestrator RBAC repair, below)

Counts parsed from the YAML: **11 entities** (Partner with a self-referential group tree, DiligenceReview, ProgramAgreement, MarketingReview, CustodyAccount, LedgerEntry (append-only, `common_fields: false`), SettlementBatch (two independent status dimensions `reconciliation_status` × `funding_status`), Complaint, TransactionMonitoringAlert, OversightCycle, WindDownPlan); **10 state machines**, all cyclic/non-linear; **3 concurrency rules** (OCC/412 on Partner.version ×2 and CustodyAccount.version); **14 calculations**; **47 validations**, priorities 1–86, no duplicates; **54 endpoints** flat under `api_prefix: /oversight` plus `/_clock/set_current_utc` (documented default now `2026-08-01T00:00:00Z`); **72 error codes**; **5 roles** (ProgramOfficer, ComplianceOfficer, RiskCommittee, InternalAudit, FintechPartner `entity_backed:Partner`).

Two defects the generator found and fixed during its own validation:
1. YAML parse failure — bare `field?` tokens are illegal in YAML flow sequences (`?` opens a complex key). Fixed by quoting every optional token: `input: [a, "b?"]`. This preserves the linter's per-element `endswith("?")` parsing, unlike the shipped examples' `input: ["a, b?"]` single-string style which collapses all names into one bogus optional field.
2. `ERR_PARTNER_NOT_CONTRACTED` was catalogued but unreferenced; added validation priority 39 (status guard on `go-live`, ordered ahead of the priority-40 readiness sweep so a `DILIGENCE_PASSED` partner reports the status error, not the readiness error).

Verified: no `scaffold_difficulty_design` / `scaffold_corner_design` key present, and the difficulty directive sentence ("harder than expert level") does NOT appear anywhere in SCAFFOLD.yaml — the known leak-via-`scenario`-key path is clean.

### 2b — SCAFFOLD_DIFFICULTY_DESIGN.yaml (2887 lines)

Single top-level key `scaffold_difficulty_design`. All **9 §0.5 rule_ids**, **21 non-stub instances**, 0 stubs, 21 globally unique names (3+2+2+2+3+3+2+2+2): dual_variant_calc 3, combinatorial_formula 2 (modes a and c), non_linear_state_machine 2 (DiligenceReview cycle; SettlementBatch parallel dimensions), transitive_cascade 2 (depth-5 funding→reserve-basis→shortfall→posture→refusal; depth-4 alert→freeze→marketing-block plus cycle-close thaw), priority_pair_validation_conflict 3 (52/46, 56/57, 28/32), boundary_precision_check 3 (composite floor half-up, end-user cap exact-equality accept, concentration ratio rounds up into an inclusive breach), cross_entity_state_dependency 2, resource_temporal_overlap 2 (half-open settlement windows vs closed disclosure windows with a 3-day buffer), compensating_invariant 2 (money_cents clawback; complaint count partition across a cyclic path). All numeric asserts were produced by executing the scaffold's formulas in Python (Decimal, ROUND_HALF_UP), not by hand. 402 capture values quoted after an unquoted `$.data[0].id` broke flow mappings.

**This file initially shipped with 51 `scaffold_lint.py` violations** — the subagent had validated placeholder closure by hand but never actually run the linter. Rather than respawn (which would have made the file diverge from itself), the orchestrator re-sent the SAME agent a computed, grouped to-do list of all 51 sites. Repairs it then applied:
- Payload keys remapped onto the real §1.5 `input` lists: `current_utc`→`to_iso8601` (6 sites); ledger-entries `end_user_ref`→`memo` (10); marketing-review create rewritten to `agreement_id`/`disclosure_elements`/`apr_disclosed`/`fdic_signage_correct` (4); alerts create given required `transaction_volume_cents`+`detection_note` (2); alert dispose `detail_note`→`disposition_note` (≥20-char string, since CLEARED requires it); assign-root-cause →`root_cause_code`/`investigation_note` (2); wind-down create given `trigger_reason`+`end_user_funds_disposition`, dropped invented `end_user_communication_plan`; marketing decide `change_request_note`→`change_requests: [...]`.
- Nonexistent endpoints: `complaints/{id}/dispose`→`complaints/{id}/disposition` with `outcome` (3 sites); `marketing-reviews/{id}/submit` deleted entirely (creation IS the submission, default status SUBMITTED) with the CHANGES_REQUESTED→SUBMITTED recovery re-composed as `resubmit` as FintechPartner (5 sites); `partners/{id}/terminate`→`agreements/{id}/terminate` as RiskCommittee plus a follow-on partner GET to capture the cascaded WIND_DOWN status.
- Captures: `growth_breach_count`→`growth_breach_partner_count`; `custody_residual_cents`→`residual_balance_cents`.
- Beyond the linter's scope (its own enum/field audit, since scaffold_lint checks neither enum values nor assert-side fields): 11 invalid `business_model` values→`PAYMENT_FACILITATION`; `WEBSITE`→`PARTNER_SITE`; `EMAIL`→`DIRECT_MAIL`; `BANK_PARTNER_NAME`→`BANK_NAME`; `BILLING_DEFECT`→`FEE_CONFIG_ERROR`; `PRE_SEED`→`SEED`; Partner terminal `REJECTED`→`DILIGENCE_FAILED`. Final field-aware re-audit: 0 enum/assert-field mismatches.
- One substantive rewrite: `escalate_then_reassign_root_cause_restores_the_complaint_bucket_partition`. Losing `/dispose` for `/disposition` forced a re-derivation of `complaint_rate_bps`, whose numerator counts {RECEIVED, ROOT_CAUSE_ASSIGNED, ESCALATED, RESOLVED} — only WITHDRAWN is excluded. Stage-4 asserts moved from `63 / OPEN` to `${s4_rate} == 125 and ${s4_posture} == HEIGHTENED`, with the drop to 63/OPEN now landing at stage 5 after the WITHDRAWN disposition; `redress_cents: 1200` added to the RESOLVED disposition and asserted. No instance was deleted; all 9 rule_ids stay covered; every `name`/`grounds`/`distinguishing_aspect` unchanged.

### 2c — SCAFFOLD_CORNER_DESIGN.yaml (4915 lines)

Single top-level key `scaffold_corner_design`. **79 non-stub instances, 0 stubs**: entities 14, state_machines 17, calculations 15, validations 15, endpoints 6, errors 3, rbac 3, cross_cutting_complexity_layers 4, consistency_model 2. All 72 §1.6 error codes referenced. This agent DID run scaffold_lint.py and self-corrected 55 violations before returning: 51 pagination captures moved from `$.data.total_count|has_more|limit|offset` to envelope level (the linter rejects `$.data.<field>` on array outputs); `monthly_growth_pct` is not a Partner field (3 sites → `growth_breach_count`); LedgerEntry has no `resulting_balance_cents` (2 sites → `amount_cents`/`sequence_no` plus a follow-up custody read); DiligenceReview's tier field is `tier`; `end_user_account_count` is required on POST /oversight/partners so `parent_partner_id` is the only omittable field; the segregation-of-duties instance was authoring diligence as ComplianceOfficer (now user `dual-brett` submits as ProgramOfficer, then decides as ComplianceOfficer — the only way priority 14 can fire, since the two endpoints' roles are disjoint). 0 stubs because the only legal stub reason (`excluded_because.difficulty_instance`) would require reading the sibling §1.8 file, which was forbidden.

Coverage gaps it reported: no marketing-review-specific rbac probe (marketing coverage lives in state_machines/validations instead), and the ops-checkpoint instance exercises steps 1/2/3/4/6 but not step 5 (wind-down completion), which is covered in state_machines.

### ORCHESTRATOR REPAIR — §1.5 vs §1.7 RBAC contradiction (decision recorded per AUTONOMY)

Both design subagents independently reported that SCAFFOLD.yaml's §1.5 endpoint `roles:` lists and §1.7's RBAC matrix disagree. A mechanical cross-check found the damage was far wider than either reported: **24 of 54 endpoints** disagreed. Examples: §1.5 gives `clear-variance` to InternalAudit alone while §1.7 assigns it to RiskCommittee; §1.5 gives `fund`/`clawback`/`cycles/{id}/close` to ProgramOfficer while §1.7 assigns them to RiskCommittee; §1.5 grants FintechPartner reads on diligence-reviews/agreements/alerts/cycles/wind-down-plans and writes on ledger-entries/settlement-batches/account-census, all of which §1.7's prose explicitly denies; §1.7 grants FintechPartner the `oversight-summary` read that §1.5 withholds.

Left unrepaired, the doc generator (which reads both §1.5 and §1.7) would have emitted a self-contradictory PRD, and Step 7 would have burned many iterations on RBAC failures with no PRD-derivable answer.

**Decision: reconcile §1.7 → §1.5, not the reverse.** Rationale: (a) validation priority 5 (`ERR_ROLE_NOT_PERMITTED`) cites the §1.5 roles list, and `scaffold_lint.py` check (b) validates every design call against §1.5 — §1.5 is the machine-checked side; (b) both design subagents independently treated §1.5 as authoritative and built all 100 instances (7802 lines) against it, so rewriting §1.5 instead would have invalidated the two most expensive artifacts in the task and forced the test generator to emit tests contradicting the scaffold. §1.7's prose was the domain-plausible side, but plausibility is not the benchmark's currency — internal consistency is, and an implementer only ever reads the PRD.

Implementation: regenerated the whole `roles:` block from the §1.5 endpoint table, deriving `exclusive_operations` (sole role on the endpoint) and `shared_operations` mechanically, and rewrote all five `description:` fields so no prose claim survives that §1.5 contradicts — notably dropping "InternalAudit appears on no write endpoint" (it owns `clear-variance` and shares `reconcile`), dropping ProgramOfficer's "holds no approval authority anywhere" (it funds, claws back and closes cycles), and rewriting FintechPartner's read/write surface to the actual scoped set. `identity:` values unchanged. SCAFFOLD.yaml 3493 → 3510 lines. Post-repair cross-check: **0 of 54 endpoints mismatched.**

Residual §1.5-side oddities accepted deliberately rather than "improved", since the design files depend on them: `clear-variance` reserved to InternalAudit, and money movement sitting with ProgramOfficer rather than RiskCommittee. Both are coherent contracts; only realism suffers.

### Known scaffold defects carried forward (both design agents concur; NOT repaired — logged so Step 7 recognises them instead of chasing them)

1. **Concentration-cap bootstrap deadlock** (priority 84): the first-ever `END_USER_CREDIT` yields a 100.00% ratio and is refused inclusively. A manual `VARIANCE_ADJUSTMENT` entry is the only escape, and also the only way to seed custody balances pre-go-live. Both design files route around it via a ballast partner.
2. **`settlement_conservation_invariant` Invariant 1 is false as written**: the fund legs plus the `cumulative_bank_fee_cents` increment double-count the fee, so the conserved total drops by exactly `bank_fee_cents` at fund (21,250,000 → 21,189,000). Only Invariant 2 is asserted anywhere.
3. **Unreachable branches**: `clear-variance` while `funding_status == FUNDED` (priority 36 forbids funding a VARIANCE_OPEN batch); funding-driven posture `FROZEN`; WindDownPlan execute-success with an UNFUNDED batch at termination; `ERR_POSTURE_BLOCKS_INFLOW` (priority 52) may be permanently preempted by priority 46.
4. **`Complaint.handling_owner` is under-specified** on any RENEWAL-diligence-variant path (that variant requires a partner with no EXECUTED agreement), so neither design file asserts it there.

**Final validation of all three artifacts together**: `scaffold_lint.py` over 1552 calls → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Step 3: Copy shared files — 2026-09-04T20:29:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T20:52:00.000Z

`workspace/PRD.md` — **588 lines**, written in 12 incremental appends plus 3 targeted edits. Nothing else written; SCAFFOLD.yaml was read-only (md5 verified unchanged afterwards: `e21133bd56f1d81be4a41a68cdd73cbe`), and neither design YAML was opened, grepped, or referenced.

Section list:
- §1 Introduction
- §2 Global Specifications: 2.1 Program Actors and Access Control · 2.2 API Response Structure (verbatim block) · 2.3 Pagination and Collection Ordering · 2.4 Resource Identity, Versioning and the Logical Clock · 2.5 Stale-Version Guards · 2.6 Money, Basis Points and Rounding · 2.7 The Oversight Posture Ladder · 2.8 Reserve Adequacy and the Recompute Cascade · 2.9 Segregation of Duties · 2.10 The Order in Which a Request Is Rejected · 2.11 Two Conservation Invariants
- §3 Business Logic (9 subsections): 3.1 Partner Intake/Diligence · 3.2 Contracting and Custody Creation · 3.3 Program Launch and Manual Custody Movements · 3.4 Marketing and Disclosure Approval · 3.5 Settlement Windows/Reconciliation/Variance · 3.6 Funding, Fee Tiers, Reserve Routing, Clawback · 3.7 Complaint Aggregation and Root Cause · 3.8 Transaction Monitoring and Sanctions Alerts · 3.9 The Oversight Cycle Checkpoint, Termination and Orderly Wind-Down
- §4 Endpoint Definitions · §5 Error Code Catalogue

Machine-verified coverage (the subagent scripted a PRD-vs-SCAFFOLD diff): validations **47/47** priority ranks enumerated in §2.10, all 46 distinct validation error IDs present; endpoints **54/54**, §4 table exactly 54 rows × 4 columns; errors **72/72**, §5 table exactly 72 rows × 2 columns; calculations **14/14** in prose; state machines **10/10** entities with all transitions, preconditions and side effects; roles **5/5**; entity field names **134/134** verbatim in backticks; endpoint input/output names **108/108**; both OCC fields (`expected_partner_version`, `expected_custody_account_version`) and all 3 concurrency rules in §2.5.

Contract 3 (§3 path purity): PASS — 1215 backtick tokens scanned in §3; zero start with `/`, zero are bare HTTP methods, zero combine method+path; zero occurrences of `POST /` or `GET /` anywhere in §3. No fuzzy quantifiers anywhere in the file.

**Truncation guard (the known doc-generator failure mode): PASS.** Orchestrator independently read `tail -25` — the file ends at a real section boundary, the final row of the §5 error catalogue table, verbatim `| ERR_RESERVE_SHORTFALL_BLOCKS_FUNDING | 402 |`. No mid-sentence cut, so no regeneration needed.

**Leak guard: PASS.** Orchestrator grepped PRD.md for `harder than expert`, `expert level`, `scaffold`, `benchmark`, `test_recipe` — zero hits. The difficulty directive never reached the implementer-facing contract.

## Step 5: Generate Unit Tests — 2026-09-04T22:28:00.000Z

Launched concurrently with Step 6 in a single assistant message, so the implementation generator was physically isolated from `test_suite/` (the directory did not exist when it started).

Complete. Both queues fully translated.

**119 tests, all tagged, 0 bad tags** (119 `Design:` lines / 119 test functions, one each; every tag resolves to a real yaml instance).
- **Queue A (difficulty): 40 tests** across `test_01`–`test_15`, covering **20 of 21** non-stub instances, every one with ≥2 tests.
- **Queue B (corner): 79 tests** across `test_20`–`test_37`, covering **79 of 79** non-stub instances (entities 14, state_machines 17, calculations 15, validations 15, endpoints 6, errors 3, rbac 3, cross_cutting 4, consistency_model 2).

Representative depth translated in the final two files: `test_36_corner_cross_cutting_layers.py` (546 lines, 4 tests) chains all three OCC tokens in one flow (census → stale diligence 412 → refreshed 201 → stale agreement 412 → stale ledger 412, RESERVE 312500→412500 at seq 2); pins the five-link funding cascade refused at 402 then allowed only after a **193750** top-up rather than the visible 92500, because the top-up's own pass re-reads the HEIGHTENED multiplier; isolates the reserve-basis variant to exactly 5000 cents (400000 gross-basis vs 405000 net-basis on an identical 8100000 base, via a clawback between the two fundings); and pins cycle close as the only writer that thaws custody. `test_37_corner_consistency_model.py` (208 lines, 2 tests) pins the sanctions cascade as complete before its own response (posture FROZEN + both accounts FROZEN on the first read, `required_reserve` still 250000 and NOT 500000 — no fixed-point iteration), and the post-write version as already post-cascade (80/80/90/85 → 84.5 / TIER_2, one version bump, token accepted by the next agreement create).

**Skips (2 — reported, not weakened, per the PRD-first filter):**
1. `Difficulty/priority_pair_validation_conflict/frozen_posture_inflow_gate_outranks_frozen_custody_account_gate` — PRD §2.10 publishes Rank 46 `ERR_CUSTODY_ACCOUNT_NOT_ACTIVE` **ahead of** Rank 52 `ERR_POSTURE_BLOCKS_INFLOW`, so the PRD uniquely derives the *opposite* outcome to the one the instance asserts. (This is the priority-52 unreachability logged under Step 2 defect 3, now confirmed from the PRD side.)
2. Within corner instance `the_cycle_close_checkpoint_is_the_only_writer_that_can_unfreeze_custody`, the recipe's reserve walk (810000 → 506250 during an alert disposition) is not PRD-derivable: PRD line 132 enumerates the recompute triggers and alert disposition is not among them. The instance's primary claim (only the close thaws custody) IS fully translated; the non-derivable arithmetic was dropped rather than asserted, and the test instead pins `required_reserve_cents == 506250` unchanged across the disposition.

Verification: `python3 -m py_compile test_helpers/*.py test_suite/*.py` clean; `pyflakes` clean; both packages import cleanly with the runner on `PYTHONPATH`. Output paths confirmed at the **task root** — `test_helpers/` (9 files, 2138 lines) and `test_suite/` (35 files incl. conftest, 8754 lines); orchestrator independently re-verified that `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`, and that `find workspace -type d -name "test*"` is empty — the known "test dirs land under workspace/" failure did not occur. `workspace/implementation/` was never read. `__pycache__` removed.

## Step 6: Generate Implementation — 2026-09-04T21:12:00.000Z

`workspace/implementation/` — Python 3 + Flask, **17 modules, 3094 lines**, plus `start.sh` (guarded pip, `exec python3 app.py`, binds `0.0.0.0:$PORT`, default 10000) and `requirements.txt`.

Module line counts: app.py 56 · authz.py 57 · respond.py 66 · errors.py 88 · util.py 102 · store.py 111 · cascade.py 120 · calc.py 347 · routes_cycle.py 370 · routes_partner.py 158 · routes_diligence.py 164 · routes_agreement.py 182 · routes_marketing.py 203 · schema.py 205 · serialize.py 246 · routes_complaint.py 262 · routes_settlement.py 357.

Coverage:
- **Endpoints 54/54** — machine-diffed the registered Flask URL map against the PRD §4 table (path + method, ids normalised): `ENDPOINT SETS IDENTICAL`, nothing missing, nothing extra.
- **Validations 47/47 ranks** (1,2,5,8,10,12,14,18,20,22,24,28,29,32,34,36,38,39,40,42,44,46,50,52,54,56,57,58,59,60,62,63,64,66,67,68,69,70,71,72,73,74,75,80,82,84,86), each an explicit ordered check annotated `# rank N` at its call site rather than incidental control flow.
- **Errors 72/72** catalogue ids reachable from code, none unused. Only additions are framework fallbacks for unrouted path/method/unhandled exception, all wrapped in the standard error envelope.
- 14 calculations in `calc.py`; 10 state machines; 3 OCC guards; 5 roles. In-memory dicts only; **nothing seeded** — a fresh boot returns `total_count: 0` for every collection, reproved after each restart.

Smoke evidence: `py_compile` clean; `PORT=18766 bash start.sh` → `HTTP/1.0 200 OK` with `{"meta":{...,"total_count":0,"has_more":false},"response_type":"array","data":[]}`. Full lifecycle round trip via curl: partner 201 → diligence create/submit/decide (PASSED, TIER_2) → agreement create/submit/execute (custody pair auto-created, reserve recomputed 250000, shortfall 250000, posture HEIGHTENED) → cycle open → RESERVE_FUND entry (sequence_no 1, shortfall→0, posture→OPEN) → go-live (LIVE) → batch create/reconcile (MATCHED, variance 0) → complaint intake (STATE_AG due 2026-08-31T23:59:59.999Z vs CFPB_PORTAL 2026-08-30T10:00:00.000Z, `handling_owner: PARTNER` from the executed agreement) → assign-root-cause → resolve → SANCTIONS_HIT alert (posture→FROZEN, both accounts frozen) → dispose (posture→OPEN, accounts stay frozen) → clock advance → cycle close (complaints_escalated_count 1) → oversight-summary → terminate → wind-down draft/submit/approve. Negative checks confirmed: 401 no headers, 401 unknown role, 403 role, 403 partner scope, 403 SoD, 404, 422 pagination, 422 short disposition note, 409 ERR_BATCH_NOT_FUNDED, 409 ERR_UNSETTLED_BATCHES_OUTSTANDING, 409 ERR_CUSTODY_INSUFFICIENT_FUNDS. Settlement money verified directly: gross 4,000,000 → 45 bps, fee 25000+18000=43000, base 4,030,000, reserve 200,000, net 3,787,000; the VARIANCE_CLEARED variant correctly switches the reserve basis to base. Smoke server was stopped by its own pid/port only — no broad pkill.

**Spec note relayed by the implementer, independently confirming Step 2 defect 1:** rank 84 as written is unsatisfiable for the first end-user credit in the system. The concentration ratio is recomputed *after* the credit, breaches on equality, and `concentration_cap_pct` is capped at 100.00 — so any first-mover `END_USER_CREDIT` always yields 100.00 ≥ cap → `ERR_CONCENTRATION_CAP_BREACH`, which in turn makes settlement funding unreachable over HTTP (rank 80 needs an FBO balance). PRD §3.3, scaffold priority 84 and the `concentration_ratio_pct` formula (step 6, `>=`) all agree, so it was implemented literally rather than corrected toward domain intuition. Funding/clawback arithmetic was therefore verified by direct call into `calc.settlement_money` instead of end-to-end. Step 7 should expect the test suite to reach these paths via the ballast-partner / `VARIANCE_ADJUSTMENT` workaround the design indices use, not by fixing the implementation.

## Step 7: Run Tests and Iterate — 2026-09-04T23:00:00.000Z

Clean sweep reached.

### Iterations
3 full 8-round sweeps (iteration 1 = baseline 103/119; iteration 2 = 116/119; iteration 3 = **119/119 in all 8 rounds**). All rounds were byte-deterministic every time — no load-induced flakiness, no `setsid` reaping symptoms.

### Tests deleted
**None.** Every failure resolved to either a real implementation gap or a test/fixture defect; no test was PRD-silent or non-uniquely-derivable in whole.

### Fixes to `test_helpers/`
- `test_helpers/api_errors.py` — `ApiErrorId` was `class ApiErrorId(str)` with plain string attributes, while 7 call sites (and the repo-wide `types.py` convention of `str, Enum`) read `.value`. Added an `_ErrorId(str)` subclass exposing `.value` and wrapped every `ERR_*` attribute after class definition. Keeps plain-string equality, formatting and `HTTP_STATUS_CODES` keying intact. This single bug caused 5 of the 16 baseline failures (`AttributeError: 'str' object has no attribute 'value'` in test_20 ×2, test_22 ×2, test_33 ×1). — a textbook instance of one upstream fixture bug masquerading as several independent implementation bugs.

### Fixes to `test_suite/`
- `test_01_diligence_underwriting.py` (2 asserts) — expected the refused `PASSED` decision to leave `latest_composite_score` at the submit-time composite (54.7 / 54.5). PRD §3.1 copies the file's composite onto the partner **only** on a `PASSED` or `FAILED` outcome, so a refused decision leaves the partner's initial `0.0`. Corrected to `0.0` with PRD-quoting messages.
- `test_04_funding_cascade.py` — trailing-volume arithmetic omitted the second batch: both batches are `MATCHED` with `window_end` inside the trailing 90 days, so the floor is `floor(21_000_000*150/10000) = 315_000`, not `300_000`, and the shortfall is `71_500`, not `56_500` (2 tests). Also, once the first wire drains the FBO to 0, rank 80 `ERR_CUSTODY_INSUFFICIENT_FUNDS` preempts rank 86, so the second test now bootstraps the FBO with exactly the second batch's base (`seed_end_user_balance` 1,000,000) to make the intended 402 `ERR_RESERVE_SHORTFALL_BLOCKS_FUNDING` the binding refusal. Assertion strength unchanged.
- `test_08_concentration_cap.py` — asserted the unrelated ballast partner's `concentration_ratio_pct` became 75.01 after the subject's credit. PRD §3.3 scopes the recompute to "every partner in the group"; a foreign group is never rewritten, so the persisted 100.00 is correct. Assertion re-pointed with a PRD-quoting message.
- `test_29_corner_...clawback.py` — two defects in one test: complaints were filed with `received_at` after the default clock (`ERR_TIMESTAMP_IN_FUTURE` setup failure), and, once the clock was merely advanced once, all four `created_at` stamps were identical (the clock is logical), so the count tie fell through to the lexicographic rule and returned `KYC_FRICTION`. The clock is now walked forward one intake at a time, giving the diagnosed complaints distinct `created_at` values, plus an added guard asserting the two tie-break rules disagree.
- `test_34_corner_error_catalogue.py` — re-disposed a closed alert with a 5-character `disposition_note`; PRD §3.6 requires ≥20 characters for closing dispositions and rank 18 outranks rank 34, so the impl's `ERR_VALIDATION` was correct. Note lengthened so the rank-34 `ERR_ALERT_TERMINAL` is the reason for refusal.
- `test_37_corner_consistency_model.py` (3 asserts) — expected `required_reserve_cents` 250,000 where the PRD's pinned-posture rule (§2.8) gives 312,500: agreement execution leaves a 250,000 shortfall → persisted `HEIGHTENED`, so the reserve top-up's own pass scales the 250,000 absolute floor by 1.25. Confirmed against `test_36`, which already encodes the identical pinning (405,000 → 506,250). Corrected on the partner row, the post-alert read, and the oversight-summary read.

### Fixes to `implementation/`
- `workspace/implementation/routes_settlement.py::list_entries` — added the two PRD-declared ledger filters that were missing (`settlement_batch_id`, `reversal_of_entry_id`). PRD §3.3 verbatim: "Ledger entries are listable with filters on `partner_id`, `custody_account_id`, `settlement_batch_id`, `reversal_of_entry_id` and `entry_type`, and readable individually." Their absence let seeded/unrelated entries leak into filtered counts, causing 3 baseline failures (test_33 `8 == 6`, test_36 `6 == 3`, test_27 extra entries). **This was the only implementation defect found**; no endpoint, field, side effect or seeded data was added.

### Final sweep evidence
`results.1..8.json`, all eight rounds identical: `total 119, passed 119, failed 0, errors 0, skipped 0`.

The three pre-confirmed spec quirks (rank-84 concentration bootstrap, rank-52 unreachability, false Invariant 1) were never contradicted by any test. `worklog.md` was neither read nor written by the subagent — the known "Step 7 writes its own mislabelled worklog entry" failure did not occur.

**Orchestrator independent verification** (not taken on trust, per the known "subagent claims a clean sweep with no artifacts" failure): all 8 `results.$i.json` exist on disk, timestamped 23:00, each parsing to `total 119 / passed 119 / failed 0 / errors 0 / skipped 0`. Test suite holds exactly **119 test functions and 119 `Design:` tags** (1:1, none untagged). `grep` for `mark.skip` / `mark.xfail` / `pytest.skip` across `test_suite/` and `test_helpers/` → zero hits, so nothing was passed by dodging. `grep` for `sqlite` / `json.dump` / file-write / `/tmp/` / `pickle` / `shelve` across `implementation/*.py` → zero hits, confirming in-memory-only storage. `start.sh` reads `$PORT` via `app.py`, installs only when Flask is missing, and `exec`s in the foreground as the harness contract requires.

## Step 8: Finalize PRD — 2026-09-04T23:12:00.000Z

Step 8 ran (not skipped): Step 7 applied 1 `implementation/` fix, 6 `test_suite/` fixes and 1 `test_helpers/` fix, so the zero-iteration skip condition did not hold.

`workspace/PRD_FINALIZED.md` written with four targeted edits. `PRD.md` 588 lines → `PRD_FINALIZED.md` 588 lines (no line-count change; 4 of 588 lines revised in place = 0.68% line delta). **Not byte-identical** — orchestrator independently confirmed with `cmp` (differs) and `diff` (8 changed lines = 4 revised pairs).

### Changes
- **§2.4** — revise — pinned that `created_at`/`updated_at` are stamped from the logical clock (never wall clock), so rows written without a clock advance share a byte-identical `created_at`, and created_at-keyed orderings break such ties by insertion order unless the rule declares its own further tie-break — `implementation/store.py:61-77`, `implementation/routes_cycle.py:115,132`.
- **§3.1** — revise — added `latest_composite_score` of 0.0 to the registration defaults and pinned that only a `PASSED` or `FAILED` diligence decision ever writes it, so a refused decision leaves 0.0 — `implementation/cascade.py:101`, `implementation/routes_diligence.py:154-162`.
- **§3.8** — insert — pinned the ≥20-character closing `disposition_note` rule as part of the rank-18 request-schema check, so it precedes the rank-34 terminal guard and yields `ERR_VALIDATION` even on an already-closed alert — `implementation/routes_complaint.py:246-253`.
- **§4 endpoint table** — revise — the `GET /oversight/ledger-entries` row's filter list now names all five filters (partner, custody account, settlement batch, reversed-entry target, entry type), matching §3.3 and the impl — `implementation/routes_settlement.py:337-355`.

### Per-edit pre-edit search log (NO-NEW-MISMATCH RULE)
1. **§2.4 timestamp source.** (a) Subject: origin of server-minted timestamps and created_at tie ordering. (b) Read `store.py` (`insert`, `touch`, `clock`, `rows` sorting by `(created_at, _seq)`), `respond.py` (`_meta` uses `store.clock_iso()`), grepped all impl for `utcnow|now()|time.time` (zero hits), grepped every list source/sort in `routes_*.py` — all lists come from `store.rows` (created_at, _seq) except ledger entries (custody_account_id, sequence_no) and cycles (cycle_index); close-time sorts in `routes_cycle.py:115,132` also end in `_seq`. (c) Adjustment: initially wrote a universal "any ordering that keys on created_at" claim; **narrowed** to "an ordering of rows … unless the rule declaring that ordering names a further tie-break of its own" so §3.7's earliest-`created_at`-then-lexicographic code rule is not contradicted, and scoped the byte-identical claim to `created_at` rather than to all stamps.
2. **§3.1 latest_composite_score.** (a) Subject: every writer/default of `latest_composite_score` and `capability_tier`. (b) Grepped `latest_composite_score|capability_tier` repo-wide: default in `cascade.new_partner_record` (0.0/UNRATED), writes only in `routes_diligence.decide_review` PASSED (tier+score) and FAILED (UNRATED+score); serialize casts to float; `routes_agreement.py:107` reads tier for routing; nothing in cycle close, census or clawback touches it. (c) Adjustment: **widened** the refusal clause to "on the compliance-capability floor, on the composite floor or on any earlier check" rather than naming a single error, since any rank-ordered refusal leaves the row untouched.
3. **§3.8 disposition_note length/rank.** (a) Subject: `disposition_note` validation and its position relative to the alert terminal guard. (b) Grepped `disposition_note` (single call site: `routes_complaint.py:249`), read `dispose_alert` fully (rank 8 lookup → rank 18 enum + note length with `min_len` 20 for closing / 1 otherwise → rank 34 terminal → sanctions recompute) and `schema.req_str` (`schema.py:65-78`). (c) Adjustment: **kept the `PARTNER_RESPONSE_PENDING` branch untouched** (impl uses min length 1 there, matching the existing "no note-length requirement beyond the schema" sentence) and avoided any claim about whitespace/stripping.
4. **§4 ledger-entries filter row.** (a) Subject: the ledger list endpoint's filter set, ordering and scoping. (b) Read `routes_settlement.list_entries` (5 filters, sort by `(custody_account_id, sequence_no)`, `scope_rows`, `paginate`), `schema.filter_str/filter_enum`, and cross-checked §3.3's verbatim filter sentence and §2.3's declared exception order. (c) No adjustment needed; described the filters in the impl's own field terms without asserting anything new about ordering or scoping.

### Step 7 diff items deliberately NOT patched (PRD already uniquely determines the impl behaviour)
- The `api_errors.py` `.value` plumbing bug — pure test fixture defect, no PRD implication whatsoever.
- The trailing-volume window and the rank-80-before-rank-86 funding order — `calc.trailing_gross` and `routes_settlement.fund_batch` both already match §3.3/§2.10 verbatim; the Step 7 failure was test arithmetic, not PRD silence.
- The group scope of the concentration recompute — `cascade.refresh_concentration` writes only group members, exactly as §3.3 already says.
- The pinned-posture reserve multiplier — `calc.required_reserve` reads `partner["oversight_posture"]` before the pass, exactly §2.8/§3.3, with `routes_agreement.risk_decision` setting `CONTRACTED` before the first pass so `HEIGHTENED` persists into the next one.

## Step 9: Complete PRD — 2026-09-05T00:05:00.000Z

Step 9 always runs. Executed as **four sequential passes partitioned by implementation module** over one shared `PRD_COMPLETED.md`, rather than as a single full-scan subagent. Rationale (recorded per AUTONOMY): a one-shot scan of a 3094-line implementation against a 588-line PRD reliably either blows the 64000-token output cap or returns a file byte-identical to its input, i.e. a scan that never actually ran. Partitioning also guarantees the densest surfaces (calculations, and the 989-line settlement/complaint/cycle group) get a dedicated budget instead of being starved by whatever came first. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2–4 were explicitly forbidden to copy and edited the existing file in place, each verifying its predecessors' edits survived.

Partition: **pass 1** = app/authz/respond/errors/util/store/schema/serialize (global envelope, auth, pagination, ordering, timestamps, request-schema, serialization shapes); **pass 2** = calc.py + cascade.py (all 14 formulas, rounding, caps, tie-breaks, cascade scope and fixed-point behaviour, entity-record defaults); **pass 3** = routes_partner/diligence/agreement/marketing (onboarding, contracting, marketing); **pass 4** = routes_settlement/complaint/cycle (money movement, complaints, alerts, the cycle-close checkpoint, wind-down).

### Aggregate result
`PRD_FINALIZED.md` 588 lines / 120,101 chars → `PRD_COMPLETED.md` **600 lines / 155,253 chars** (+12 lines, **+35,152 chars, +29.3%**; 156 changed lines vs PRD_FINALIZED). Nearly all edits are in-paragraph inserts/revisions — no new sections were added. **Totals across the four passes: 59 ambiguity-pins, 22 mismatch-revisions (81 changes).**

### Pass 1 — global layer (14 changes: 12 ambiguity-pins, 2 mismatch-revisions), 588 → 598 lines
- §2.1 — revise — whitespace-only header counts as empty for `ERR_MISSING_AUTH_HEADERS`; both header values trimmed before recognition/comparison; role match exact and case-sensitive — `authz.py:16-19`
- §2.2 — revise — `api_request_id` shape pinned: `req_` + 20 chars from `A–Z`/`0–9`, 24 total, minted per response including errors — `util.py:19-21`, `respond.py:9-13,31-36`
- §2.2 — revise — **mismatch** — `api_request_timestamp` is read from the logical clock, not a wall-clock instant; identical while the clock stands still — `respond.py:12`
- §2.2 — revise — object and error `meta` carry only the two fields; pagination keys absent — `respond.py:16-19,31-36`
- §2.3 — revise — `limit`/`offset` trimmed then parsed base-ten; empty, decimal-formatted or non-numeric values are `ERR_VALIDATION`; `offset` has no upper bound — `respond.py:39-59`
- §2.3 — revise — `has_more` formula (`offset + len(page) < total_count`); out-of-range `offset` returns an empty page, not an error; filter → scope → order → window sequencing — `respond.py:21-28,62-66`
- §2.4 — insert — every declared field always present, unset values emitted as JSON `null`, keys never omitted, empty arrays as `[]`; ISO handling pinned both directions (permissive input: lowercase `z`, numeric offsets normalised, date-only, no-zone treated as UTC, >6 fractional digits discarded; output **truncated, not rounded**, to exactly 3 digits with `Z`) — `util.py:24-63`, `serialize.py`
- §2.5 — insert — a missing/`null`/non-integer version token is rank-18 `ERR_VALIDATION` (422), not staleness; no range declared, so a negative integer merely mismatches → 412 — `schema.py:102-112`
- §2.6 — insert — JSON type split: all `_cents`/`_bps`/counts are integers, the seven named percentage/score fields are fractional numbers even when whole — `serialize.py:20-41,58,79-80`
- §2.9 — insert — SoD is exact string equality against the trimmed `X-User-ID`; a null originator passes rather than fails — `authz.py:54-57`
- §2.10 rank 12 — insert — scope is a *filter* on lists (never a 403 from a list, `total_count` computed post-scope), a refusal only on single reads/writes; the partner collection compares the row's own `id`; cycles are unscoped — `authz.py:48-51`, `routes_partner.py:65`, `routes_cycle.py:61-65`
- §2.10 rank 18 — insert — the largest single gap: eight sub-rules pinned (absent/unparseable body = empty object; non-object body = `ERR_VALIDATION`; explicit `null` ≡ absent; unknown keys silently ignored; no type coercion, booleans never accepted as integers, numeric strings rejected except for two-decimal percentage fields; string lengths measured raw with whitespace-only failing any min ≥ 1; array/non-empty/member rules with duplicates allowed and order preserved; enum query filters validated at this rank while id filters are exact-match with no existence check → empty page, not 404) — `schema.py:53-205`
- §4 preamble — insert — trailing slash accepted — `app.py:22`
- §4 `GET /oversight/ledger-entries/{id}` — revise — **mismatch** — PRD promised "its resulting balance"; the representation has no balance field — `serialize.py:128-142`
- §5 preamble — insert — three framework identifiers outside the catalogue and outside the §2.10 ranking: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500, same envelope — `app.py:35-51`

### Pass 2 — calculations and cascades (9 changes: 7 ambiguity-pins, 2 mismatch-revisions), 598 → 600 lines
- §2.6 — insert — flooring of a bps product is toward negative infinity, so a negative settlement base floors *away* from zero — `util.py:84`, reached via `calc.py:250`
- §2.8 — insert — every derived quantity in the cascade is a **full recompute**, not an incremental delta (`balance_cents`, `complaint_rate_bps`, `open_sanctions_alert_count`, `unreconciled_variance_cents` as Σ|`variance_cents`| over `VARIANCE_OPEN`, `concentration_ratio_pct`); the group reach rewrites siblings' reserve/shortfall/ratio **without** bumping their `version`/`updated_at`; only the acting partner's posture is re-derived and only its accounts freeze — `cascade.py:6-51,73-85`
- §2.8 — insert — the pinned posture is the partner's own *persisted* `oversight_posture`, read once at the top of the pass before the agreement is located — `calc.py:201`
- §2.8 — insert — only `ACTIVE` accounts are frozen; an already-`FROZEN` account is not re-stamped and its `version` does not move; `CLOSED` never refrozen — `cascade.py:59-70`
- §3.1 — insert — the complete default field set of a new `Partner` record (14 integer counters at 0, `concentration_ratio_pct`/`monthly_growth_pct` at `0.00`, `systemic_root_cause_code` null) — `cascade.py:88-120`
- §3.1 — revise — **mismatch** — registration-time concentration is not "zero until custody exists"; the refresh runs *after* the row is filed and writes the group's current non-zero ratio onto a partner joining a group that already holds custody — `routes_partner.py:44-45` + `cascade.py:45-51`
- §3.3 — insert — the group write hits **every** member irrespective of its own `status` (incl. `PROSPECT`/`TERMINATED`) and moves neither `version` nor `updated_at` — `calc.py:117-132`, `cascade.py:49-50`
- §3.6 — revise — **mismatch** — PRD said "each ledger insert recomputes its account's `balance_cents`"; impl re-sums each affected account **exactly once after all legs**, so a reserve account carrying two legs gains only `version` +1 — `routes_settlement.py:217-218`
- §3.9 — insert — the growth-cap comparison reads the *already-rounded* pct; the cap comes from the `EXECUTED`/`TERMINATED` agreement; with no such agreement the percentage branch records no breach while the absolute 5,000,000-cent test still governs the zero-baseline branch — `calc.py:292`, `routes_cycle.py:149`
- §3.9 — insert — step 3's reserve step reads the pre-close persisted posture (a `FROZEN` partner re-underwrites at 2.00 in the close that releases it), and the concentration recompute spans the whole group, so a *skipped* group sibling does get its ratio rewritten — `routes_cycle.py:155-156`, `calc.py:201`, `cascade.py:45-51`

### Pass 3 — onboarding / contracting / marketing routes (19 changes: 16 ambiguity-pins, 3 mismatch-revisions), 600 lines unchanged
Notably, all three of pass 3's mismatches are the same species: **the global rank ladder stated its own scope "exhaustively" and was wrong**, because a second endpoint raises the same error id at a different effective position.
- §2.10 rank 10 — insert — a non-string body foreign key yields the collection's 404 at rank 10, not a rank-18 type error — `store.py:80`
- §2.10 rank 39 — revise — **mismatch** — `ERR_PARTNER_NOT_CONTRACTED` is also raised by agreement terminate, and there it sits *below* rank 59 — `routes_agreement.py:168`
- §2.10 rank 40 — revise — **mismatch** — the launch-readiness sweep also requires exactly two custody accounts, `reserve_shortfall_cents == 0` and posture `OPEN`/`HEIGHTENED`, all under the same code — `routes_partner.py:142-146`
- §2.10 rank 67 — revise — **mismatch** — the effective-date guard also runs on `risk-decision` when the decision is `EXECUTE` — `routes_agreement.py:133`
- §3.1 — insert — the group acyclicity walk stops at a root or first revisited id; the new row's id is minted after the walk, so a create can never itself close a loop — `routes_partner.py:33-40`
- §3.1 — insert — `last_closed_cycle_index` is the max `cycle_index` among `CLOSED`, null when none; the summary is a flat object with no id/timestamps/version and persists nothing — `routes_partner.py:82-106`
- §3.1 — insert — census: both payload fields required (`as_of_date` parsed but never stored); the freeze consequence runs; reserve/shortfall/concentration are *not* recomputed — `routes_partner.py:115-123`
- §3.1 — insert — `effective_complaint_history_score` starts at 0 — `routes_diligence.py:52`
- §3.1 — insert — file state, partner status and "another open file" all report the one code `ERR_REVIEW_NOT_DRAFT_OR_INFO_REQUESTED` — `routes_diligence.py:98-112`
- §3.1 — insert — `requested_info_items` is a rank-18 requirement (beats the rank-34 state guard); resubmission leaves the partner row untouched; the partner-status failure reuses the same code — `routes_diligence.py:136,111-121`
- §3.2 — insert — partner-status and tier failures both report `ERR_AGREEMENT_NOT_DRAFT` — `routes_agreement.py:106-108`
- §3.2 — insert — **branch asymmetry**: `REJECT` returns before the execution gates, so a stale partner status or past effective date is never examined — `routes_agreement.py:125-130`
- §3.2 — insert — the two execution gates' error ids and order (`ERR_AGREEMENT_NOT_PENDING_APPROVAL` then `ERR_EFFECTIVE_DATE_IN_PAST`) — `routes_agreement.py:131-134`
- §3.2 — insert — custody pair inserted `FBO_END_USER` first, then `RESERVE` (fixes list order via the §2.4 tie-break) — `routes_agreement.py:140`
- §3.2 — insert — execution's recompute is narrower than the ledger cascade: acting partner's reserve only (no group siblings), no concentration recompute, and a `FROZEN` posture freezes the two brand-new accounts in-request — `routes_agreement.py:148-150`
- §3.3 — insert — go-live requires "exactly two" accounts; reserve/posture failures share `ERR_PROGRAM_NOT_READY_FOR_LAUNCH`; values read as persisted (no recompute); `attestation_note` discarded; success touches nothing but the partner row — `routes_partner.py:130-148`
- §3.4 — insert — the cited agreement's status is never checked (a `DRAFT` agreement is a valid basis); the partner's lifecycle status is unconstrained beyond ranks 32/50; filing does **not** touch the partner row — `routes_marketing.py:31-74`
- §3.4 — insert — recomputed `risk_flags` are written before the branch, so they survive a refused approval (without moving `version`/`updated_at`); no branch touches the partner — `routes_marketing.py:122`
- §3.4 — insert — all five restated resubmit fields are required (no defaults, unlike the filing), empty array still allowed; `decided_by_user_id` is not cleared — `routes_marketing.py:156-176`
- §3.9 — insert — terminate: `notice_days` required integer, unbounded, stored nowhere; partner-status code and its position below rank 59 — `routes_agreement.py:162,168`
- §3.9 — insert — termination recomputes nothing (posture/reserve/concentration untouched), freezes/closes no custody, creates no plan — `routes_agreement.py:171-181`

### Pass 4 — settlement / complaints / cycle routes (39 changes: 24 ambiguity-pins, 15 mismatch-revisions), 600 lines unchanged
Coverage explicitly confirmed complete: all 28 endpoints across the three modules reviewed.
- §2.11 Invariant 1 — revise — **mismatch, and the most consequential edit in Step 9.** The four-term conservation PRD asserted is arithmetically false (the fund legs plus the `cumulative_bank_fee_cents` increment double-count the fee). Replaced with ledger-level conservation (`balance_cents` = Σ`amount_cents`, append-only) plus the exact non-conservation expression `−settlement_base + reserve_funding + shortfall_carry + net_to_partner`, its reduction to `−bank_fee_cents` on positive payout and possible *rise* in the floored branch; clawback symmetry retained — `calc.settlement_money`, `routes_settlement.py:198-218`. **This retires Step 2 carried-forward defect 2 at the PRD level.**
- §2.10 rank 18 — revise — the submit-endpoint milestone re-check raises `ERR_VALIDATION` yet is *not* at rank 18 — the one schema-shaped check ranked below 34/42 — `routes_cycle.py:317`
- §2.10 rank 38 — revise — **mismatch** — ladder scope omitted `clawback`, which accepts `LIVE` **or** `WIND_DOWN` — `routes_settlement.py:237`
- §2.10 rank 69 — revise — **mismatch** — ladder scope omitted `wind-down-plans/{id}/decide` (APPROVE branch, `notice_days < 30`) — `routes_cycle.py:337`
- §3.5 — insert — the batch-overlap scan covers every batch of that partner whatever its statuses — `routes_settlement.py:62`
- §3.5 — revise — reconcile has only the rank-34 `UNRECONCILED` gate, no partner-status gate; MATCHED recomputes variance only, VARIANCE_OPEN additionally posture + freeze — `routes_settlement.py:125-137`
- §3.5 — insert — `variance_adjustment_cents` any sign, `root_cause_note` min length 1 — `routes_settlement.py:148`
- §3.5 — revise — **mismatch** — `unreconciled_variance_cents` is a full recompute (was "added to"/"removed from"); `variance_cents` is never rewritten by clearing — `cascade.refresh_unreconciled_variance`
- §3.5 — insert — `VARIANCE_ADJUSTMENT` leg fields, total bypass of the §3.3 guards, skipped when no `RESERVE` account, then group cascade + freeze — `routes_settlement.py:162-168`
- §3.6 — revise — **mismatch** — funding order: rank 80 FBO overdraft precedes rank 86 shortfall; missing/inactive reserve and missing FBO handling; FBO `status` never examined; nothing persisted on refusal — `routes_settlement.py:189-197`
- §3.6 — insert — `reserve_requirement_bps` treated as 0 with no governing agreement — `routes_settlement.py:191`
- §3.6 — insert — three legs in order debit→`RESERVE_FUND`→`FEE`, per-account `sequence_no`, zero-amount `RESERVE_FUND` still written, fee leg only when >0, guard bypass, leg ids remembered off-representation — `routes_settlement.py:201-212`
- §3.6 — insert — clawback partner-status code `ERR_PARTNER_NOT_LIVE` evaluated after rank 34 — `routes_settlement.py:234-238`
- §3.6 — insert — clawback reverses only recorded funding legs, negated amounts (so a **negative** `CLAWBACK`), `reversal_of_entry_id`, missing legs skipped, post-funding `VARIANCE_ADJUSTMENT` left standing — `routes_settlement.py:240-246`
- §3.6 — insert — balances re-summed once each, FBO then RESERVE, then group cascade + freeze — `routes_settlement.py:251-255`
- §3.3 — revise — the prospective concentration ratio adds `amount` to numerator *and* denominator and breaches on `>=`, so the first end-user credit always breaches a 100.00 cap; both caps skipped without an agreement — `routes_settlement.py:319-327`. **This pins Step 2 carried-forward defect 1 into the PRD, so it is now contract rather than surprise.**
- §3.7 — insert — intake freeze via §2.7 and "recomputes nothing else" (no reserve/shortfall/concentration/variance, no group sibling) — `routes_complaint.py:65-68`
- §3.7 — insert — **mismatch** — assign-root-cause from `RECEIVED` writes no partner row at all: no counter, no rate, no posture, no `version` — `routes_complaint.py:116-123`
- §3.7 — insert — `resolution_note` validated then discarded; `redress_cents` stored only on `RESOLVED` — `routes_complaint.py:134-147`
- §3.7 — insert — all three disposition branches recompute rate → posture → freeze — `routes_complaint.py:168-171`
- §3.7 — revise — **mismatch** — `handling_owner` consults only a literally `EXECUTED` agreement (narrower than the governing-agreement rule; `TERMINATED` gives the `BANK` default), earliest by `created_at` — `routes_complaint.py:42-45`. **This retires Step 2 carried-forward defect 4 (the RENEWAL-variant under-specification).**
- §3.8 — insert — only `SANCTIONS_HIT` creation touches the partner (count/posture/freeze per §2.7); other alert types touch nothing — `routes_complaint.py:209-213`
- §3.8 — insert — `OPEN` is not an accepted `disposition` input; closing dispositions need a ≥20-char note (rank 18, ahead of the rank-34 terminal guard) — `routes_complaint.py:246-249`
- §3.8 — insert — **mismatch** — disposing an alert touches no custody row in either direction: it can lift a posture off `FROZEN` without unfreezing accounts — `routes_complaint.py:257-261`
- §3.9 — revise — **mismatch** — the "checked against every cycle" contrast with the settlement window was wrong; both ignore status, the real difference is partner-scoped vs bank-wide — `routes_cycle.py:34`
- §3.9 — insert — `closing_note` validated then discarded — `routes_cycle.py:94`
- §3.9 — revise — close step 1 population/sort `(received_at, created_at, insertion)`; the owning partner's `version` is bumped whatever its status; no recompute in this step — `routes_cycle.py:112-126`
- §3.9 — revise — close step 3 inner order starting with `systemic_root_cause_code`, one partner write per re-underwritten row — `routes_cycle.py:143-163`
- §3.9 — insert — close step 4 marketing-review `version` bumps and no double counting between the posture sweep and the stale sweep — `routes_cycle.py:166-186`
- §3.9 — revise — **mismatch** — close step 5 sweeps every `IN_EXECUTION` plan system-wide regardless of partner status or step-3 membership; partner→`TERMINATED` only if still `WIND_DOWN` — `routes_cycle.py:189-209`
- §3.9 — insert — **mismatch** — a non-draining plan is still re-stamped: residual written, `version` +1 — `routes_cycle.py:192-195`
- §3.9 — insert — close step 6: cycle `version` moves twice per close, counters written as absolute totals, plus the explicit list of what a close never touches (variance, sanctions count, account/complaint totals, cumulative money, custody balances, batch fields) and that it synthesises no ledger entry — `routes_cycle.py:212-216`
- §3.9 — insert — create-plan milestone rules are `ERR_VALIDATION` (422) at rank 18, ahead of ranks 32 and 42; duplicates kept in supplied order — `routes_cycle.py:248`
- §3.9 — revise — contracted triggers come from the `EXECUTED`-or-`TERMINATED` agreement; with none, the list is empty so every `trigger_reason` is refused — `routes_cycle.py:252-254`
- §3.9 — revise — **mismatch** — `residual_balance_cents` is also recomputed *and written* by the plan list and the single read, moving neither `version` nor `updated_at` — `routes_cycle.py:293-294,303`
- §3.9 — revise — submit's milestone re-check is `ERR_VALIDATION` below ranks 34/42; the three plan notes are all validated then discarded — `routes_cycle.py:312-317`
- §3.9 — insert — **mismatch** — execution imposes no custody-balance condition at all and touches no account, partner or ledger row — `routes_cycle.py:365-369`. **This retires part of Step 2 carried-forward defect 3.**
- §4 table — revise — **mismatch** — the create-batch cell said "reported gross and count"; it takes the four money figures — `routes_settlement.py:54-57`
- §4 table — revise — **mismatch** — the reconcile cell said "bank-side gross and count"; it takes a single `bank_reported_net_cents` — `routes_settlement.py:124`

### Orchestrator independent verification
- `PRD_COMPLETED.md` exists at 600 lines / 155,253 chars. `cmp` against **both** `PRD.md` and `PRD_FINALIZED.md` → differs in both cases, so the known "Step 9 output byte-identical to its input, meaning the scan never ran" failure did not occur. `diff` against `PRD_FINALIZED.md` = 156 changed lines.
- `PRD.md` (588 lines / 118,889 chars) and `PRD_FINALIZED.md` (588 lines / 120,101 chars) both unmodified — no pass overwrote an upstream artifact.
- Truncation check: `PRD_COMPLETED.md` ends at a real section boundary, the final row of the §5 error catalogue table (`| ERR_RESERVE_SHORTFALL_BLOCKS_FUNDING | 402 |`).
- Each pass independently spot-confirmed its predecessors' edits survived (§2.2 `req_` id shape, §2.10 rank-18 sub-rules, §2.8 full-recompute and pinned-posture sentences, §3.2 custody-pair insertion order). No pass rewrote or removed an earlier pass's sentence.
- **Green-sweep validity re-confirmed**: `find test_suite test_helpers workspace/implementation -name "*.py" -newer workspace/implementation/results.1.json` returns nothing, so no test or implementation file changed after the 23:00:41 sweep. Steps 8 and 9 were documentation-only, exactly as intended, and the 8/8 × 119/119 result still describes the code on disk. No confirming re-sweep was needed.

### Pipeline complete
All nine steps done. Of the four scaffold defects carried forward from Step 2, three are now resolved at the PRD level by Step 9 (the false Invariant 1, the concentration-cap bootstrap, the `handling_owner` under-specification, plus the wind-down-execute branch of defect 3); the remaining unreachable branches (rank-52 preemption, `clear-variance` while FUNDED, funding-driven `FROZEN`) are documented dead code paths in the contract, not divergences between PRD and implementation.
