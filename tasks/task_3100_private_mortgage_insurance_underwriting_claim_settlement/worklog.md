# Worklog — task_3100_private_mortgage_insurance_underwriting_claim_settlement

Scenario: Private Mortgage Insurance Underwriting & Claim Settlement (MGIC): coverage application from lenders with delegated and non-delegated underwriting paths, premium plan selection across borrower-paid monthly, single and lender-paid structures with rate cards by credit and loan-to-value, master policy terms governing rescission relief, curtailment and independent validation of loan data, cancellation of coverage on borrower request or automatic termination at amortization milestones, servicer reporting of delinquency with loss mitigation participation requirements, claim filing after foreclosure or short sale with claim amount computation and settlement options, rescission and curtailment disputes over origination defects, portfolio risk concentration and reinsurance

## Step 1: Create Task Directory — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3100_private_mortgage_insurance_underwriting_claim_settlement/` was pre-allocated by the caller with `workspace/` already created. No index computation performed and no other `task_*` directory created, per the invocation instructions.
## Step 2: Generate Scaffold — 2026-09-30T01:05:00.000Z

Done. All three scaffold artifacts are written and the linter runs clean.

### Files written

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2144 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1359 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2150 |

`SCAFFOLD.yaml` carries only §1.0–§1.7 (no `scaffold_difficulty_design` / `scaffold_corner_design` key); each design file has exactly its single required top-level key.

### Structure

- **Complexity profile** — primary archetype *Ledger reconciliation*, secondary *Compliance/audit*; layers: dual-variant calculation, rate/threshold triggers, cascading side effects, optimistic concurrency. Topology **flat** (FK-referenced peers, no URL nesting), state-machine shape **branching** (the `Loan` machine is a compound parallel axis: `coverage_status × amortization_status`; `Claim` is cyclic), role model **peer_roles**, consistency **immediate**.
- **15 entities** — MasterPolicy, RateCard, ReinsuranceTreaty, Servicer, Lender, CoverageApplication, Loan, DelinquencyReport, CancellationNotice, ExternalReport, CurtailmentDispute, Claim, ClaimSettlementOption, ReinsuranceCession, PortfolioSnapshot.
- **9 state machines / 30 transitions** across CoverageApplication, Loan, DelinquencyReport, Claim, CurtailmentDispute, CancellationNotice, Lender, PortfolioSnapshot, ReinsuranceCession.
- **17 calculations** (claim arithmetic with pinned ceiling-before-curtailment order, true-up premium billing, cancelling-factor refund, rescission-relief cycles, loss-mitigation gate, cancellation-term earliest-instant merge, reinsurance waterfall, exposure reconciliation, portfolio concentration, two invariants).
- **23 validations, 65 endpoints, 41 errors, 5 roles** (MasterPolicyAdmin/Underwriter opaque, Lender/Servicer entity-backed, Borrower opaque read-only), **3 concurrency rules** (all OCC on `Loan.version` at three distinct write endpoints).
- **Difficulty design: 18 instances across all 9 difficulty rules** (2 each), every instance with a structured `setup_api_calls` → `trigger` → `assert` recipe and code-computed literals.
- **Corner design: 51 instances across 14 sections** — 33 carrying full test recipes, 18 `excluded_because:` stubs pointing at named §1.8 instances.

### Verification

`scaffold_lint.py` verdict, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional self-checks: every `grounds:` reference resolves (calcs, errors, priorities, fields, transitions, rule ids); instance names unique across both design files; every declared error referenced somewhere; endpoint roles all in the RBAC matrix; 21 FK declarations all carrying the canonical `FK -> <Entity>.id` prefix with reverse-reachability GETs; no forbidden concurrency vocabulary; enum closure fixed (dropped the unwritten `LENDER_EXPOSURE_CAP_BREACH` termination value and added a `Lender` machine so `SUSPENDED` has a producer).

Hard constraint observed: no sibling task directory was listed, globbed, grepped, or read — the scaffold was derived from the scenario text plus the skill spec and `scaffold_lint.py` only. No processes were killed.

## Step 3: Copy Shared Files — 2026-09-30T01:06:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes) — the build contract for the implementation generator (start.sh + PORT/0.0.0.0/foreground).

## Step 4: Generate PRD — 2026-09-30T01:30:00.000Z

The PRD is complete and all three hard contracts pass.

### Summary

**Output:** `workspace/PRD.md` — **438 lines**, 100,222 characters.

**PRD section list:**

- `## 1. Introduction` (3 paragraphs: product scope, the coupled-views problem, the double-edged economics)
- `## 2. Global Specifications & System-Wide Principles`
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim fixed block, byte-identical to `section-2.2-response-structure.md`)
  - 2.3 Pagination
  - 2.4 Record Identity, Versioning and Audit Fields
  - 2.5 The Logical Clock and Temporal Evaluation
  - 2.6 Money, Rate and Rounding Conventions
  - 2.7 The Premium Schedule Ledger
  - 2.8 Nested Resource Retrieval
  - 2.9 Optimistic Concurrency Control
  - 2.10 Coverage, Claim and Dispute State Families
  - 2.11 Underwriting Paths and Rate Card Pinning
  - 2.12 Order of Evaluation and Request Rejection Discipline
- `## 3. Business Logic & Workflows` — 12 subsections, grouped by business-process timeline rather than the template lifecycle pattern: 3.1 parties and policy terms → 3.2 pricing/LTV banding → 3.3 issuance and premium plans → 3.4 servicer reporting and the loss-mitigation gate → 3.5 the two loan axes and termination arbitration → 3.6 cancellation/refund/rescission-relief and independent validation → 3.7 claim filing and review → 3.8 the claim computation → 3.9 settlement options and the recovery waterfall → 3.10 reinsurance cessions and treaty capacity → 3.11 settlement, disputes and rescission → 3.12 exposure, concentration and treaty configuration
- `## 4. Endpoint Definitions` — 66 rows, 4 columns only
- `## 5. Error Code Catalogue` — 42 rows, 2 columns only

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 131 required, 131 present, 0 missing
- endpoints[].request_body: 91 required, 91 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- endpoints[].path_params: 0 required, 0 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 24 checked, 24 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_loan_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 30 checked, 30 fully expressed, 0 missing
- calculations[]: 17 checked, 17 fully expressed, 0 missing
- validations[] conditions: 24 checked, 24 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 24 checked, 24 expressed, 0 missing
- entities[].fields[] structured content: 131 checked, 131 reconstructible from prose, 0 missing
- sibling-branch symmetry: 11 groups checked, 11 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 546
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: all 22 state enumeration values appear as exact strings; all 4 role names spelled exactly and each role's `identity:` translated into §2.1 prose; every `errors[].id` (41) mentioned in §2 or §3; no fuzzy/approximating hedges around any numeric threshold; no backtick parity defects; §2.2 verbatim match confirmed programmatically.

**Constraint confirmation:** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, read, or referenced — only `SCAFFOLD.yaml` and the skill's own files (`SKILL.md`, `section-2.2-response-structure.md`, `example-prd.md`) were read. No sibling task directory under `tasks/` was listed, globbed, grepped, or read. No processes were started or killed.

## Step 5: Generate Unit Tests — 2026-09-30T02:15:00.000Z

Generation is complete and verified. Summary:

### Files written

**`test_helpers/`** (9 files, 1,715 lines)

| File | Lines |
|---|---|
| `__init__.py` (barrel export) | 36 |
| `types.py` (entity TypedDicts, status/role enums) | 342 |
| `api_client.py` (`ApiClient(GenericApiClient)`, one method per PRD endpoint) | 243 |
| `api_errors.py` (`ApiErrorId` + status map, registered via `set_error_http_status_map`) | 99 |
| `assertions.py` (per-entity asserts + claim-arithmetic / premium-schedule / exposure invariants) | 165 |
| `factories.py` (per-entity payload factories) | 203 |
| `constants.py` (thresholds, canonical fixtures) | 73 |
| `test_users.py` (opaque constants + `make_lender_headers` / `make_servicer_headers` builders) | 28 |
| `fixtures.py` (composite setup helpers, tiers 1–5, identity threading) | 526 |

**`test_suite/`** (17 files, 2,725 lines) — `conftest.py` plus 16 numbered `test_*.py` files organized by concern (premium schedules, claim review cycle, claim computation, settlement options, loan axes/cascade, cross-entity dependencies, boundaries/precedence, temporal windows, compensating invariants, resource contracts, RBAC, refusals/version guards, underwriting/reporting, pricing/terms, boundary companions, single premium).

### Totals

- **88 tests**, collected cleanly (`pytest --collect-only`), zero import/lint errors.
- **Queue A (Difficulty): 47 tests** — all 18 §1.8 instances carry ≥2 tests.
- **Queue B (Corner): 41 tests** — all 33 non-stub §1.9 instances carry ≥1 test.
- All 18 `excluded_because:` stubs were **not** translated; their `difficulty_instance` cross-references all resolve.

### Audit results

- Zero untagged tests, zero dual-tagged tests, zero tags pointing at non-existent instances, zero tags pointing at stubs.
- Every docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, copied verbatim from the source yaml.
- **Every quoted PRD fragment survives a literal grep of PRD.md** (0 mismatches across all 88 docstrings).
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no mention of "scaffold" or scaffold-section labels in generated code.

### Instances skipped by the PRD-first two-condition filter

**None.** Every non-stub §1.8 and §1.9 instance passed both conditions (verbatim PRD coverage *and* unique derivability), so no instance was skipped and no gap-log entries were produced. Notable judgment calls that passed:

- `Corner/calculations/single_premium_financed_note_raises_the_loan_to_value_band` — the PRD pins the financed annuity formula plus `TERM_MONTHS`/`PRESENT_VALUE_FACTOR`, but **not** the band/rate-card the fixture yaml assumes. I derived the expected `single_premium_cents` from the PRD formula itself (`ceil(8500000 × 128 / 10000) = 108800` unfinanced; `ceil(8650000 × 190 / 10000 × 10 × 0.92) = 1512020` financed) rather than copying the yaml's figure, which is inconsistent with PRD §3.3's 240-month/0.92 constants.
- `Difficulty/dual_variant_calc/lender_paid_versus_borrower_paid_premium_divergence` — the plan/payer branch and the zero-premium consequence are both PRD-verbatim; the claim-side "no carve-out" clause is cited from PRD §3.8 ("A lender-paid loan occupies no special carve-out here…") and tested on a real non-delegated LPM leaf.
- The two §1.9 `cross_cutting_layers` stubs whose `excluded_because` pointers look self-referential actually resolve to real §1.8 instance names (`…is_refused` under `boundary_precision_check`; `…treaty_is_not_in_forge` under `priority_pair_validation_conflict`), so they were treated as legitimate stubs and not translated.

A design note worth flagging: the yaml fixture for the corner `single_premium` instance uses a 120-month term and expects `1000960`, which is `ceil(8500000 × 128 / 10000 × 10 × 0.92)`. PRD §3.3 states the term is 240 months and the present-value factor 0.92. I followed the PRD, so the emitted assertions match the contract the implementer actually sees.

**Orchestrator verification note:** independently confirmed 88 tests collected, 88 `Design:` tags (47 queue A + 41 queue B), 0 skip/xfail. One malformed tag was found and repaired by the orchestrator: `test_suite/test_01_premium_schedules.py` line 4 carried a module-docstring line `Design: Difficulty/dual_variant_calc/* (queue A, rule 1).` — a wildcard tag that Stage 2's "tags pointing to non-existent instances" check would flag. It was rewritten as plain module prose (the per-test citation lines in that file were already correct and untouched); tag count is now exactly 88 with zero column-0 `Design:` lines.

## Step 6: Generate Implementation — 2026-09-30T02:50:00.000Z

Done. The implementation is complete and verified.

### What was built

A Python + Flask REST API for the private-mortgage-insurance task at `workspace/implementation/`

| File | Lines |
|---|---|
| `start.sh` | 12 |
| `requirements.txt` | 1 (`Flask>=3.0`) |
| `app.py` | 56 |
| `common.py` | 129 |
| `db.py` | 75 |
| `errors.py` | 123 |
| `middleware.py` | 186 |
| `response.py` | 79 |
| `routes/{__init__,core,coverage,claims}.py` | 0 / 369 / 609 / 410 |
| `services/{serializers,views,pricing,claim_arithmetic,coverage_rules,reinsurance,workflows}.py` | 313 / 300 / 132 / 127 / 269 / 179 / 948 |

**4,318 Python lines**, **65 endpoints — an exact 1:1 match** against SCAFFOLD §1.5 (verified by diffing the declared method+path table against Flask's URL map, placeholders normalized; zero missing, zero extra).

### Contract confirmation

- `start.sh` is executable, runs `exec python3 app.py` in the **foreground**, binds `0.0.0.0:$PORT` (default 10000), and guards the `pip install` behind `import flask` so per-test reboots are a no-op. Verified: `LISTEN 0.0.0.0:18300` with the launcher PID inheriting to `app.py` via `exec`; HTTP 200 within ~0.8 s.
- **In-memory only.** Nothing but the logical clock persists; no SQLite, no JSON dump, no `/tmp`, no file writes anywhere in the code.
- **No seeding.** `db.py` starts empty; every fixture is built through the declared API. Verified with 8 sequential fresh `start.sh` boots, each creating one master policy and then observing `total_count == 1`, plus a ninth boot observing an empty store on all collections.

### Behaviour verified by direct exercise (four suites I wrote, all green)

Envelope/pagination/precedence (401 → 403 → 404 → state → business → 412, with `ERR_STALE_VERSION` evaluated last), the pinned premium arithmetic (base 8500000 @ 62 bps → annual 52700, monthly 4392, final 4388; SPM financed `ceil(52700·10·0.92)` = 484840), LTV banding and the 4dp boundary, the non-delegated five-point coverage step-down with the 12-percent floor, LPM zero-premium, claim arithmetic with the ceiling applied *before* curtailment, the DIL reinstatement waterfall (DIL 10000000 vs CASH 5700000 on identical inputs), cession clamping vs. `ERR_TREATY_CAP_EXHAUSTED`, settlement reversal restoring `aggregate_ceded_cents` exactly, the rescission-relief cycle count with Rule 2, the tier-3 standard dominating the policy standard, milestone monotonicity with the 30/60-day deferrals, and the waiver gate.

### Notes worth flagging

- Two places had to be reconciled from prose rather than structure: `POST /loans` accepts an explicit `reinsurance_treaty_id: null` (SCAFFOLD §1.1 explicitly permits a treaty that "is not yet in force", and cession is tested at settlement, so treating the field as mandatory would contradict it), and manual cessions against a non-`ACTIVE` treaty are refused with `ERR_TREATY_NOT_IN_FORCE` (the PRD is explicit that cancellation "stops all further cessions", which contradicts that error's own catalog condition for the literal path).
- I granted `Borrower` the single-resource reads PRD §2.1 declares (loan / claim / governing master policy / rate card); this is deliberately inconsistent with the scaffold's RBAC note, because PRD prose wins.
- No process-safety violations: only PIDs I started were killed, by exact PID or by matching the bound port; no `pkill`/`killall`/`pgrep|xargs`. All scratch listeners are released.

## Step 7: Run Tests and Iterate — 2026-09-30T02:43:00.000Z

**Resumption note.** This step was launched once before and its subagent was killed mid-flight by a host-level process stop (not an error in the work). Because Step 7 was the only incomplete step, it was restarted from scratch. On-disk state at resumption: the prior partial run had left the suite at **90 tests** (the original Stage 2 emitted 88; the interrupted run added 2) and had applied unvalidated edits to `test_suite/`, `test_helpers/` and `implementation/` after its last completed sweep. All `results.*.json` were stale (01:12) and were deleted before re-sweeping. The orchestrator verified the on-disk baseline independently first: all modules compile, `pytest --collect-only` reports 90 tests, 90 `Design:` tags, zero `skip`/`xfail`. The prior run's deletion log was unrecoverable, so no prior deletion was assumed justified; every judgment was re-derived from the current files.

Clean run complete. All 8 rounds pass 90/90.

### Summary

**Iterations run:** 2 full 8-round parallel stability sweeps (720 test executions total).

**Root cause found:** The single defect was a **test-artifact bug, not an implementation bug**. Both failing tests in the first sweep (`test_rescission_decision_is_barred_when_relief_has_attached` and `test_rescission_decision_resolves_when_relief_status_is_none`, both in `test_06_cross_entity_dependencies.py`) failed identically in all 8 rounds with `NameError: name 'file_claim' is not defined` — a missing import, meaning neither test body ever executed. This was deterministic (not flaky), so it was correctly diagnosed as a STEP 2 consistency defect rather than an implementation failure.

**First sweep (baseline, before fix):** 88 passed / 2 failed / 90 total — identical in every round.

**Second sweep (after fix):** 90 passed / 0 failed / 90 total — identical in every round (all 8 rounds `passed == total`).

**Tests deleted:** None. Both failures traced to PRD-covered, uniquely-derivable rules, so no STEP 1 deletion criterion applied.

**Fixes applied to `test_helpers/`:** None needed.

**Fixes applied to `test_suite/`:**
- `test_suite/test_06_cross_entity_dependencies.py` — added the missing `file_claim` symbol to the `from test_helpers import (...)` block. `file_claim` was already exported by `test_helpers/__init__.py` (line 26); both tests call it at lines 111 and 143. This is a pure import completion — no assertion was weakened, no skip/xfail added, no implementation check touched.

**Fixes applied to `implementation/`:** None. The implementation was never implicated; this was confirmed by running the affected test file directly against a scratch server after the import fix (5/5 passed) before committing to a full sweep.

**Process safety:** Only PIDs started by the subagent were terminated (the scratch server on port 41237, killed by exact PID). No `pkill`/`killall`/`pgrep | xargs kill` was used; the runner managed all sweep servers via its own port registry.

**Incidental note (not a defect):** `pyflakes` reports numerous unused imports across `test_suite/` (mostly `pytest` and re-exported helpers). These are harmless and do not affect collection or results; they were left untouched since they are not part of the failing-test contract.

**Orchestrator verification note:** independently re-read all 8 `results.*.json` (fresh 02:41 timestamps) — every round reports `total=90 passed=90 failed=0 errors=0 skipped=0`. Confirmed zero `skip`/`xfail` in `test_suite/` and `test_helpers/`.

**Step 8 skip condition:** NOT met — Step 7 recorded 1 `test_suite/` fix, so Step 8 (PRD_FINALIZED.md) must run.

## Step 8: Finalize PRD — 2026-09-30T02:46:00.000Z

PRD_FINALIZED.md is written and is byte-identical to PRD.md. This is a zero-edit outcome, and the evidence supports it.

### Summary

**Deliverable:** `workspace/PRD_FINALIZED.md`
- PRD.md: 437 lines · PRD_FINALIZED.md: 437 lines · 0% delta, `diff` empty (byte-identical).

### Why zero edits

The single `<step_7_diff>` item is a pure fixture bug: a missing `file_claim` symbol in the `from test_helpers import (...)` block of `test_suite/test_06_cross_entity_dependencies.py`. Both named tests raised `NameError: name 'file_claim' is not defined` before their bodies executed, in all 8 rounds. Adding the import (already exported at `test_helpers/__init__.py:26`) fixed them; no assertion was weakened, no `implementation/` file changed. A pure test-import completion is neither a PRD silence nor a PRD-vs-implementation mismatch, so it yields no edit.

Verification that both tests' asserted rules are PRD-covered verbatim:
- `test_rescission_decision_resolves_when_relief_status_is_none` cites the §3.11 rule "the targeted claim must currently be in `DENIED` or in `SETTLED`" — present verbatim at PRD.md:304 — and the `RESCINDED`/`CANCELLED` outcomes at PRD.md:306.
- `test_rescission_decision_is_barred_when_relief_has_attached` cites "It is barred absolutely on a loan whose relief has attached: a `RESCISSION_GRANTED` decision attempted where the loan's `rescission_relief_status` is `GUARANTEED` is refused with `ERR_RESCISSION_BARRED_RELIEF_ATTACHED`" — present verbatim at PRD.md:306; the relief-status computation that produces `GUARANTEED` is fully spelled out at PRD.md:234-236.

The subagent also confirmed the implementation matches those rules (no undisclosed mismatch hiding behind the fixture bug): `implementation/services/workflows.py:739-748` applies `target_claim_can_be_rescinded` (`DENIED`/`SETTLED`, line 695) then the relief bar, and the numeric pipeline (`setup_guaranteed_relief_loan`) reaches `GUARANTEED` under the implementation's `rescission_relief_status` logic — consistent with PRD.md:236.

### Per-edit pre-edit search log

No edits were committed, so there are no (a)/(b)/(c) entries to report. For completeness, the one candidate site investigated before rejecting it:

- **Candidate subject:** the `loan["rescission_relief_status"] != "NONE"` guard at `implementation/services/workflows.py:746`, which on its face is stricter than PRD.md:306's `GUARANTEED`-only wording.
- **Impl paths enumerated and read/grepped:** `services/workflows.py:726-748` (`decide_dispute` rescission branch), `services/workflows.py:695-696` (`target_claim_can_be_rescinded`), `services/workflows.py:771-785` (state mutation), `services/workflows.py` relief recomputation; grepped `RESCISSION_GRANTED|RESCISSION_BARRED|RESCINDED` and `rescission_relief_status` across `implementation/`; grepped `PROVISIONAL` across `workspace/PRD.md`, `test_suite/`, `test_helpers/`.
- **Why no edit:** the only difference between `!= "NONE"` and `== "GUARANTEED"` arises when the status is `PROVISIONAL`. Grep shows `PROVISIONAL` is declared in `test_helpers/types.py:48` and accepted by `test_helpers/assertions.py:92`, but no test starts or reaches a `PROVISIONAL` loan, and no PRD behavior for `PROVISIONAL` at the rescission gate is exhibited anywhere off the Step 7 site. Per the NO-NEW-MISMATCH rule no universal claim ("any relief other than `NONE` bars rescission") was manufactured that Step 7 never exercised and that could itself become a new mismatch. PRD.md:306's existing wording already covers the one status the tests and implementation observably reach.

Zero edits is the correct output for this step.

**Orchestrator verification note:** independently confirmed `diff PRD.md PRD_FINALIZED.md` is empty; both 437 lines / 100,431 bytes.

**Step 9:** always runs.

## Step 9: Complete PRD — 2026-09-30T03:55:00.000Z

**Redo note.** This step was launched once before and its subagent was killed by a host-level process stop immediately after Method step 0 (the `cp`), producing no edits and no summary. Its partial `PRD_COMPLETED.md` was byte-identical to `PRD.md` and was deleted; the step was re-run from scratch. Before re-running, the orchestrator confirmed the Step 7 baseline was still intact (no source file under `test_suite/`, `test_helpers/` or `implementation/` modified after the 02:41 sweep; suite still collects 90; no orphaned task processes).

### Output

- **Source:** `workspace/PRD_FINALIZED.md` (437 lines / 100,431 chars) → **`workspace/PRD_COMPLETED.md`** (437 lines / 118,757 chars), **char delta +18,281**, zero new sections/headings (32 → 32), zero new lines (same paragraph boundaries).
- **Changes: 43** — 39 in-paragraph prose edits + 4 endpoint-table cell edits, across 18 sections.
- **Counts:** ~30 ambiguity-pins, ~13 mismatch-revisions (of which 4 are the table rows).

### Bullets — `{section} — {insert|revise} — {ambiguity|mismatch} — {what changed} — {impl}`

- §2.1 — revise — mismatch — Borrower read access is role-admitted, not ownership-scoped, and does not include borrower collections — `routes/coverage.py:505-510`, `routes/claims.py:160-163`
- §2.3 — insert — ambiguity — added lender/servicer list-read scoping to own rows — `routes/coverage.py:364-367`, `routes/claims.py:132-135`
- §2.3 — insert — ambiguity — enumerated the extra FK filters per list endpoint; empty-match page and unrecognized param ignored — `routes/coverage.py:129-132`, `routes/claims.py:324-327`, `routes/core.py:167-169`
- §2.7 — insert — ambiguity — schedule is held as three fields (`annual_premium_cents`/`monthly_period_cents`/`final_period_cents`), no addressable period rows — `services/serializers.py:140-142`
- §2.8 — insert — ambiguity — loan issuance's `application_id` is a body FK → `ERR_RESOURCE_NOT_FOUND`, not `ERR_APPLICATION_NOT_FOUND` — `services/views.py:239-248`, `routes/coverage.py:330`
- §2.8 — insert — ambiguity — cession read by id uses generic `ERR_RESOURCE_NOT_FOUND`; dispute-filing cross-references → `ERR_RESOURCE_NOT_FOUND` — `services/views.py:187-193`, `routes/claims.py:299-308`
- §2.9 — insert — ambiguity — the three version checks run last among business gates; settlement also carries/checks `expected_claim_version` first — `services/workflows.py:677-681`
- §2.12 — insert — ambiguity — `verified_property_value_cents == 0` → `ERR_INVALID_REQUEST` — `routes/coverage.py:527-528`
- §2.12 — insert — ambiguity — claim `event_completed_utc` is the only future-rejected field; all other instants pass through as supplied — `routes/claims.py:76,103-115`, `middleware.py:156-176`
- §2.12 — insert — ambiguity — cancelled coverage wins over `claim_blocked` because coverage is read at claim-time — `services/workflows.py:651-655`
- §3.1 — insert — ambiguity — `coverage_percent_default` is recorded but unreachable (applications always state a percent) — `routes/core.py:85-104`
- §3.1 — insert — ambiguity — borrower submission refusal is `ERR_FORBIDDEN_FOR_ROLE`, before resource lookups — `routes/coverage.py:76-89`
- §3.2 — revise — mismatch — the priced card is the application's named `rate_card_id`; approval never re-checks the stored band — `services/workflows.py:92-109`
- §3.3 — insert — ambiguity — `SPM` with `borrower_paid=false` records `single_premium_cents` 0 — `services/workflows.py:189-196`
- §3.3 — revise — mismatch — the annuity term is a fixed 240-month constant, not the loan's `term_months` — `services/pricing.py:24,84-97`
- §3.3 — insert — ambiguity — `single_premium_cents` is never recomputed after issuance — `services/workflows.py:186-196`
- §3.3 — insert — ambiguity — annual-premium interest is derived-only, stored on no resource — `services/pricing.py:100-102` (unreferenced)
- §3.4 — insert — ambiguity — activities read by `activity_kind` only; `outcome`/`activity_utc` ignored — `services/coverage_rules.py:54-61`
- §3.4 — insert — ambiguity — the ladder is vocabulary, not sequencing; containment tested — `services/coverage_rules.py:64-73`
- §3.4 — revise — mismatch — duplicate-period is checked before `ERR_SERVICER_INACTIVE`/`ERR_SERVICER_NOT_DESIGNATED` — `services/workflows.py:461-476`
- §3.4 — insert — ambiguity — `last_loss_mitigation_deficient_utc` is overwritten, so it holds the latest failure — `services/workflows.py:498-500`
- §3.4 — revise — mismatch — a failed gate moves the axis to `PENDING_CANCELLATION` (not "suspend and cancel"); cancellation happens later on the clock — `services/workflows.py:508-527`
- §3.5 — insert — ambiguity — a non-positive submitted balance is `ERR_MILESTONE_NOT_REACHED` — `services/workflows.py:247-248`
- §3.5 — insert — ambiguity — re-recording on an `AT_78` loan is still a mutation (balance/base/schedule/version move) — `services/workflows.py:258-289`
- §3.5 — insert — ambiguity — the arbitration emits only `BORROWER_REQUEST` notices as candidates — `services/coverage_rules.py:220-227`
- §3.5 — insert — ambiguity — revocation restores the axis for any termination reason without side effects — `routes/coverage.py:403-417`
- §3.6 — insert — ambiguity — a cycle window runs backward, so newer reports do not disturb it — `services/coverage_rules.py:115-129`
- §3.6 — insert — ambiguity — no class A reports ⇒ cycle index 0 and status `NONE` — `services/coverage_rules.py:108-110`
- §3.6 — insert — ambiguity — notice filing is declared from the `ACTIVE` axis only; `termination_reason` is always `BORROWER_REQUEST` — `services/workflows.py:319-323,360-361`
- §3.6 — revise — mismatch — annex: relief recompute happens on delinquency **and validation** reports, never on a bare anniversary crossing — `services/workflows.py:450,504`; `routes/core.py:66-69`
- §3.6 — insert — ambiguity — the rescission bar reads the full standing (`GUARANTEED` **or** `PROVISIONAL`) — `services/workflows.py:745`
- §3.6 — insert — ambiguity — `ATTACHED` sets `GUARANTEED` directly; `REVOKED`/`ATTACHED` never re-derive standing — `services/workflows.py:374-377`
- §3.6 — insert — ambiguity — "attached code" = any non-empty string — `services/workflows.py:382`
- §3.6 — revise — mismatch — cancellation no longer "voids premium instalments" (no stored periods); schedule figures unchanged — `services/workflows.py:346-363`
- §3.6 — insert — ambiguity — the validation review writes no field; it refreshes the loan figures and relief standing — `services/workflows.py:445-451`
- §3.7 — insert — ambiguity — `event_completed_utc` unconstrained against `filed_utc` — `routes/claims.py:76`
- §3.7 — insert — ambiguity — reconsideration leaves frozen arithmetic alone; `reason` required in both states — `routes/claims.py:224-242`
- §3.8 — insert — ambiguity — a re-approval clears and re-seeds the four option rows — `services/workflows.py:621-635`
- §3.10 — insert — ambiguity — rejected cessions are still written on settlement (treaty_id null only when absent) — `services/reinsurance.py:39-95`
- §3.10 — revise — mismatch — a recorded `REJECTED` cession never carries `AGGREGATE_CAP_EXHAUSTED` (manual path raises `ERR_TREATY_CAP_EXHAUSTED` instead) — `services/workflows.py:825-834`
- §3.11 — insert — ambiguity — claim version checked before loan version; settlement re-asserts coverage-in-force — `services/workflows.py:647-681`
- §3.11 — insert — ambiguity — `asserted_coverage_percent` never alters arithmetic — `services/workflows.py:703-724`
- §3.11 — insert — ambiguity — `UPHELD` on a never-approved claim; `DENIED` re-prices nothing — `services/workflows.py:753-769`
- §3.11 — insert — ambiguity — a voided cession keeps its row and amounts — `services/workflows.py:779-787`
- §3.11 — revise — mismatch — the `RESCISSION_GRANTED` bar fires on any non-`NONE` standing, not `GUARANTEED` alone — `services/workflows.py:745`
- §3.12 — insert — ambiguity — per-loan rounding before summing; base is original-item — `services/reinsurance.py:100-120`
- §3.12 — insert — ambiguity — cap failure returns the refusal, never the four-field success — `services/workflows.py:873-899`
- §3.12 — revise — mismatch — every `COMPUTED` snapshot is superseded, not just the same "reporting basis" — `services/workflows.py:909-912`
- §3.12 — revise — mismatch — `EXPIRED` is declared but no operation drives it — `routes/core.py:225-232`
- §3.12 — insert — ambiguity — `loan_id` on reconciliation is a body FK → `ERR_RESOURCE_NOT_FOUND` — `routes/core.py:331-333`
- §4 — revise — mismatch ×4 — table rows for master-policy read, rate-card read, loan read, claim read now list `Borrower` — `routes/core.py:128-131,178-180`, `routes/coverage.py:378-381`, `routes/claims.py:155-158`
- §4 — insert — ambiguity — Borrower is a valid role in no operation's set (⇒ `ERR_FORBIDDEN_FOR_ROLE`, never 401); entity ownership applies on top of the role gate — `middleware.py:59-74`

**Areas with zero edits:** §1 (Introduction), §2.2 (Response Structure / envelopes), §2.4 (Identity & Audit Fields), §2.5 (Logical Clock), §2.6 (Money & Rounding), §2.10 (State Families), §2.11 (Underwriting Paths), §3.9 (Settlement Options & Waterfall), and §5 (Error Catalogue). These were checked against `response.py`, `db.py`, `common.py`, `services/claim_arithmetic.py` and `errors.py` and are already uniquely pinned.

### Verdict on `rescission_relief_status != "NONE"` (`services/workflows.py:745`)

**Reachable real behavior — pinned in prose (two edits); §3.11 revised rather than left `GUARANTEED`-only.** Reasoning:

- `rescission_relief_status` returns `PROVISIONAL` whenever the cycle index reaches ≥ 1. A single deficient class A report on a fresh loan does exactly this: `delinquency_streak` = 1 (so no auto-cancellation, which needs ≥ 3), `last_loss_mitigation_deficient_utc` = that report's effective instant, `claim_blocked` = true, coverage axis stays `ACTIVE`, and relief becomes `PROVISIONAL` (`services/coverage_rules.py:132-166`, `services/workflows.py:498-508`).
- That loan can still reach `RESCISSION_GRANTED`: deny a claim on it (`APPROVED → DENIED` is itself the `RESCISSION_GRANTED` precondition per `target_claim_can_be_rescinded`), file a non-`LOSS_MITIGATION_EXCUSE` dispute, begin review, decide `RESCISSION_GRANTED` (`services/workflows.py:738-749`). So the guard is not dead: it fires on a fully API-reachable state.
- Accuracy checks: state precedence holds (`coverage_status != "ACTIVE"` in `approve_claim` only *rejects approval*; a denied claim never passed it). A bare single class A report cannot itself drive coverage to pending while also being PROVISIONAL; and the PROVISIONAL-evaporating paths (a second class A report) also independently block the decision via `ERR_COVERAGE_NOT_ACTIVE`. So a ban on all non-`NONE` borrows no impossible state.
- Scoping: the bar is stated for **both** `GUARANTEED` and `PROVISIONAL`, with an explicit note that no other relief value reaches the guard, rather than a broader universal claim. The `PROVISIONAL`-reachable condition is stated at §3.6, and the bar clause at §3.11.

**Known non-reachable over-claims deliberately NOT touched** (impl records them but no corpus-independent rule forces them, and the PRD wants tests to remain the arbiter): `participation_standard_met=False` while the diff appears only on an exact int comparison; `curtailment_rate_applied` forced to 0 on an LPM loan; `LTV_MILESTONE` forcing `termination_reason = "BORROWER_REQUEST"` when it loses arbitration; and a validation report on a `CANCELLED` loan refreshing relief. Making these normative would have pinned hypotheses the implementation does not causally establish.

**Orchestrator verification note:** independently confirmed PRD_COMPLETED.md is 437 lines (unchanged line count → no new sections/paragraphs added), 32 headings (unchanged), an even count of code fences (4 → balanced), and `diff` vs PRD.md is non-empty as expected. Re-confirmed `implementation/`, `test_suite/` and `test_helpers/` have zero files modified after the 02:41 sweep, and all 8 `results.*.json` still read 90/90 — the post-Step-7 baseline is untouched by Steps 8 and 9, which are documentation-only.

## Pipeline complete — 2026-09-30T03:56:00.000Z

All nine steps done. Final state: 90/90 tests passing in all 8 concurrent stability rounds; `PRD.md`, `PRD_FINALIZED.md` and `PRD_COMPLETED.md` present; `SCAFFOLD*.yaml`, 9 `test_helpers/` files and 17 `test_suite/` files in place; `workspace/implementation/` boots cleanly via `start.sh` with in-memory-only storage and no seeded data.
