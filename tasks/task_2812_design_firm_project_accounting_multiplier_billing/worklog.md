# Worklog — task_2812_design_firm_project_accounting_multiplier_billing

## Step 1: Create task directory — 2026-09-05T00:44:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2812_design_firm_project_accounting_multiplier_billing` and its `workspace/` subdirectory. Index 2812 was pre-assigned by the orchestrating caller (no scan/auto-allocation, to avoid collisions with the other pipelines running concurrently on this host).

## Step 2: Generate scaffold — 2026-09-05T02:17:00.000Z

All three scaffold artifacts are complete and the lint is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     36
  Calls scanned (§1.8+§1.9):  844

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2812_design_firm_project_accounting_multiplier_billing/`):
- `SCAFFOLD.yaml` — 2118 lines / 137 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1997 lines / 128 KB (sole key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3013 lines / 189 KB (sole key `scaffold_corner_design`)

Contents
- §1.0–§1.7: 12 entities, 13 state machines (36 transitions), 2 OCC rules (both on `Project.version`), 15 calculations, 44 validations (priority-ordered 1→90), 56 endpoints, 44 errors, 5 roles. `api_prefix: ""`, `consistency_model: immediate`, `role_model: segregation_of_duties`, pagination 10/1/100.
- §1.8: 9 rule_ids (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`) × 20 instances (2–3 each).
- §1.9: all 9 taxonomy sections, 66 instances = 36 full recipes + 30 `excluded_because` stubs. Per section (total/active/stubs): entities 9/9/0, state_machines 12/5/7, calculations 13/5/8, validations 16/7/9, endpoints 5/2/3, errors 2/2/0, rbac 3/3/0, cross_cutting_layers 5/2/3, consistency_model 1/1/0.

Verified mechanically: no duplicate instance names across §1.8 ∪ §1.9; every stub names a real §1.8 rule/instance pair and carries no `test_recipe`; **all 44 catalog errors are triggered inside an active (non-excluded) instance**; every fixture resets the logical clock to `2026-06-01T00:00:00Z` as FirmAdmin.

Design adjudications
- `api_prefix: ""` forced by the lint's FK reverse-reachability check.
- 56 endpoints / 44 errors sit above the Expert band; justified by the "harder than expert" directive, which is recorded only as `complexity_profile.difficulty_level: expert_plus` and deliberately kept out of `scenario:` so it cannot leak into PRD.md.
- Non-standard `dimension:` key used on the multi-axis state machines (ConsultantInvoice has three independent axes).
- No Employee entity — actors are opaque `X-User-Id` strings; no InvoiceLine entity — sweeps are recorded as `billed_invoice_id` / `client_invoice_id` back-references, discoverable only through list filters.
- Two computed reads (`GET /projects/{id}/wip-aging`, `GET /phases/{id}/earned-value`) documented via `output_shape:` and never used as `captures:` sources; profitability is exposed as computed `Project` fields rather than a new endpoint.
- Negative RBAC and malformed-payload corners are written as prose `trigger:` strings, because the lint rejects structured calls with an illegal role or an incomplete payload.
- Two SCAFFOLD.yaml corrections found while writing §1.9: the expense-adjudication clause order was reversed (receipt clause first) to make `ERR_EXPENSE_UNALLOWABLE` reachable at review, and the `INVOICE_RECEIVABLE` write-off side effect was disambiguated to move `gross_billed` (not the `net_due` amount) so `total_charge_value` stays conserved.

**Orchestrator note (post-step):** grepped SCAFFOLD.yaml for the difficulty directive — the literal phrase "harder than expert level" is absent from `scenario:`. The only residue was a trailing comment on `complexity_profile.difficulty_level` reading "per the generation directive"; I stripped that comment so nothing in the doc generator's sole input alludes to an externally supplied difficulty instruction. `difficulty_level: expert_plus` itself is ordinary scaffold metadata and was left in place.

## Step 3: Copy shared files — 2026-09-05T02:18:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T02:35:00.000Z

PRD generation for task 2812 is complete and verified.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2812_design_firm_project_accounting_multiplier_billing/workspace/PRD.md`

**439 lines / 92,941 bytes (92,674 characters).** Written in 9 incremental `cat >>` appends — no single Write approached the 64k cap.

## Output-completeness verification (the three mandated checks)

1. `wc -l` = 439, `wc -c` = 92,941.
2. Last 30 lines are the tail of the §5 Error Code Catalogue table, ending at a complete row — `| `ERR_WRITE_OFF_AMOUNT_MISMATCH` | 422 |`. Not mid-sentence, mid-table or mid-list. No audit footer (`grep` for "hard contract", "coverage check", "Status: PASS" → none).
3. All 27 planned headings present:

```
# Design Firm Project Accounting API — Product Requirements Document
## 1. Introduction
## 2. Global Specifications & System-Wide Principles
  2.1 Actors, Headers and Role-Based Access Control
  2.2 API Response Structure   (+ Standard Success / Standard Error subheads)
  2.3 Pagination
  2.4 Resource Identity, Audit Timestamps and the Mutation Counter
  2.5 Money, Rates and Rounding Discipline
  2.6 The Logical Clock and Accounting Period Locks
  2.7 Optimistic Concurrency on the Project Version
  2.8 The Order in Which a Request Is Rejected
  2.9 Path Resolution and Reverse Discovery
  2.10 The Conserved Charge Ledger
  2.11 Billing Posture: the Project-Level Gate
## 3. Business Logic & Workflows
  3.1 Standing Up a Client, a Project and Its Work Breakdown Structure
  3.2 Rate Governance: Cost Rates and Billing Multipliers
  3.3 Timesheet Capture and the Frozen Labour Charge
  3.4 Reimbursable Expenses and Client Allowability
  3.5 Consultant Subcontracts, Payables and Pay-When-Paid
  3.6 Earned Value, Phase Completion and Project Closure
  3.7 The Client Invoice: Preparation, Review Cycle and Settlement
  3.8 Unbilled Aging and Routed Write-Offs
  3.9 Overhead Rate Certification and Public-Agency Compliance
## 4. Endpoint Definitions
## 5. Error Code Catalogue
```

§2 has 11 subsections (guidance 8–12); §3 has 9 (guidance 5–9). §2.2 verified byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md` via `diff`. §4 table is exactly 4 columns with **56 endpoint rows** (all 56 scaffold paths matched programmatically, 0 missing, 0 extra). §5 is exactly 2 columns with **44 error rows** (exact set match).

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS**
158 unique identifiers required across `entities[].fields`, `endpoints[].request_body`/`query_params`/`path_params`, `{}` path params, and the two computed reports' `output_shape`. All 158 present as backticked tokens; 0 missing. (Verified twice — loose flattened pass and strict exact-backtick-token pass. The scaffold's `?` optionality suffixes were stripped before matching.)

**Contract 2 — Rule Coverage: PASS**
- `validations[]`: 44 checked, 44 expressed (§2.8 rejection ladder + per-rule narrative), 0 missing.
- `concurrency_rules[]`: 2 checked, 2 expressed with write endpoint, `expected_project_version` and `ERR_STALE_PROJECT_VERSION`/412 all named; §2.7 also states explicitly that no other operation accepts the field.
- `state_machines[]`: 13 machines / 36 transitions, all 36 fully expressed, 0 missing.
- `calculations[]`: 15 checked, 15 fully expressed in natural language with pinned operation order; all 13 named constants verified present verbatim in the text.
- Error mapping: all 44 `errors[].id` appear in the §2/§3 **narrative**, not merely in the §5 table; 0 absent.
- `endpoints[].side_effects` / `applies_to` scopes: all expressed.
- Sibling-branch symmetry: 7 groups checked (3 Invoice→VOID transitions; 2 WriteOff approval branches; 2 ConsultantInvoice reject branches; ALLOW/DISALLOW expense review; 2 payment-release routes; PROVISIONAL/FINAL rate variants; EFFORT_BASED/ASSESSED/COMPLETION_OVERRIDE earned value) — 0 asymmetric.

**Contract 3 — §3 Path Purity: PASS**
984 backtick tokens scanned in §3. Tokens starting with `/`: 0. Bare HTTP-method tokens: 0. Method+path tokens: 0. Additional regex scan for slash-paths in raw §3 prose outside backticks: 0.

Style checks also clean: 0 fuzzy quantifiers (`approximately`/`roughly`/`conservatively`/`around N`), 0 leaked operators or pseudocode (`==`, `>=`, `round_half_up`, `IS NULL`), 0 forbidden concurrency framing ("simultaneous", "first-writer", "race winner").

## Adjudications and carefully-rendered rules

Pinned arithmetic orders rendered as prose with their worked examples and the wrong-order counter-value stated, so the implementer cannot collapse the steps:
- **Labour charge**: raw cost rounded to 2dp *first*, then multiplied by the multiplier and rounded again (`7.35 h × 62.50 × 3.0500` → `459.38` → `1401.11`; single-step gives `1401.09`).
- **Invoice totals**: volume-discount tier chosen on **pre-discount** gross, retainage taken on the **post-discount** base (`100500.00` gross at `0.0500` retainage → discount `1005.00`, retainage `4974.75`, net due `94520.25`; reversed order gives `95475.00`).
- **Overhead rate**: PROVISIONAL on annualized unadjusted figures vs FINAL on unannualized actuals net of unallowables (`1.6500` vs `1.5750`, ceiling `2.8325`).
- **Phase earned value**: the EFFORT_BASED / ASSESSED divergence spelled out (`3620.00` vs `50000.00` on identical inputs).
- **WIP aging asymmetry preserved deliberately**: the over-90 bucket is age >= 91 days while write-off escalation to Controller triggers at aging >= 90 days — stated explicitly as intentional so it isn't "tidied up".
- **Expense allowability clause order**: the missing-receipt hold outranks both exclusion clauses.
- **Consultant commitment overlap**: closed-inclusive windows (touching windows *do* overlap), strict aggregate cap.

Eight scaffold ambiguities/self-contradictions resolved:
1. **Fixed-fee headroom** applies to FIXED_FEE contracts only — followed the calculation's trigger over validation 82's wider contract-type list.
2. **Project ACTIVE→CLOSED** requires every **leaf** phase COMPLETE — followed the endpoint side-effect over the state machine's "every Phase", which is unreachable for parent nodes.
3. **ConsultantInvoice markup frozen at approval**, not at creation — followed entity + state machine + calculation over the creation endpoint's `side_effects`.
4. **Invoice `revise` recomputes totals** — followed state machine + `invoice_totals_computation` over the scaffold endpoint description's "totals stay frozen"; I patched the §4 row so the table no longer contradicts §3.7.
5. **Self-certification** of an overhead rate maps to `ERR_SEGREGATION_OF_DUTIES`.
6. **404 codes split per path identifier** per validation priorities 25–28, rather than lumped as validation 25's `check` text implies.
7. Auth header spelled **`X-User-ID`** per SKILL.md, overriding the scaffold's `X-User-Id`.
8. `BillingMultiplier.effective_to` rendered as an optional input with its system semantics stated (null while ACTIVE; truncated to the successor's `effective_from` on supersede).

Zero-Silence patches made after the first draft: added the two recompute-on-read side effects (`GET /phases/{phase_id}` recomputes earned value; `GET /consultant-subcontracts/{subcontract_id}` recomputes the commitment rollup) into §2.10; added the eight computed-report field names that my first extractor missed because they live under `output_shape`; added `expected_project_version` to the two §4 rows that require it; and removed an internal calculation name (`consultant_markup_computation`) that had leaked from a scaffold description into the §4 table.

One judgement call worth flagging: the §2.8 ladder's step 8 reads "the not-found errors of §2.9" rather than spelling all nine 404 identifiers inline. §2.9 immediately enumerates all nine with their exact error IDs and every one also appears in the §3 narrative, so the reconstruction test still passes — I judged this acceptable rather than a Contract-2 gap.

Constraints honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory under `tasks/` was read; no `pkill` was run.

**Orchestrator note (post-step):** independently re-ran the truncation check the caller flagged. `wc -l` = 439; the tail is a complete `| \`ERR_WRITE_OFF_AMOUNT_MISMATCH\` | 422 |` table row closing the §5 catalogue, which is the document's genuine final section — not a mid-sentence cut. All five top-level `## ` headings (§1–§5) are present in order. Grepped for the difficulty directive: no occurrence of "harder than expert", "expert_plus" or "difficulty" anywhere in PRD.md. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T03:20:00.000Z

Stage 2 is complete and audited. Everything landed at the task root; nothing under `workspace/`; `worklog.md` untouched.

## File inventory

`/home/ubuntu/github/CodingPRD/tasks/task_2812_design_firm_project_accounting_multiplier_billing/test_helpers/` — 3299 lines
`__init__.py` 212, `api_client.py` 356, `api_errors.py` 204, `assertions.py` 606, `constants.py` 230, `factories.py` 469, `fixtures.py` 796, `test_users.py` 101, `types.py` 325

`.../test_suite/` — 10171 lines, **177 tests**
`conftest.py` 145 · `test_01_entity_contracts.py` 858 (18) · `test_02_state_transitions.py` 597 (15) · `test_03_calculations.py` 664 (15) · `test_04_validation_rules.py` 1469 (32) · `test_05_endpoint_reads.py` 489 (8) · `test_06_error_semantics.py` 265 (5) · `test_07_access_control.py` 552 (15) · `test_08_concurrency_layers.py` 354 (5) · `test_09_earned_value_variants.py` 476 (6) · `test_10_frozen_charge_arithmetic.py` 679 (11) · `test_11_lifecycle_state_machines.py` 723 (12) · `test_12_cascades.py` 415 (5) · `test_13_rule_precedence.py` 284 (4) · `test_14_boundary_edges.py` 594 (8) · `test_15_cross_entity_gates.py` 554 (6) · `test_16_temporal_windows.py` 440 (6) · `test_17_compensating_actions.py` 613 (6)

## Coverage

**Zero instances skipped in either queue.**

- Queue A (difficulty): 20/20 non-stub instances translated, every one with >=2 tests (range 2–4). 51 tests.
- Queue B (corner): 36/36 non-stub instances translated, every one with >=1 test (range 1–7). 126 tests.
- 30 `excluded_because:` stubs left untranslated as required; all 30 `difficulty_instance:` cross-references resolve to real instances — **0 dangling**.

## Verification performed

- `py_compile` clean on all 26 modules; `pytest test_suite --collect-only -q` → **177 collected, 0 errors**.
- Machine audit over every test function: exactly one `Design:` line, and it is the last docstring line; every tag resolves to a real non-stub instance under the correct section/rule_id; every test carries >=1 `PRD §x.y: "…"` citation whose quoted span is a verbatim contiguous substring of a single `PRD.md` line; no forbidden vocabulary in any docstring or comment. **0 errors.**
- Named-defect probes all clean: no `["data"]` re-index on a `get_success_data`/`validate_success` result (0 hits), no money/ratio sent as a JSON string (0 hits), timestamp canonicalisation lives only in `api_client._request`, no duplicate test-function names shadowing within a file.
- `ls -d` confirms both dirs at the task root; `find workspace -name test_helpers -o -name test_suite` returns nothing; `workspace/` still holds only `INSTRUCTION.md` and `PRD.md`. No `.md` file was created anywhere.

## Adjudications (yaml expectation vs PRD)

1. **`REPROGRAPHICS` is not an admitted expense category** (PRD admits only TRAVEL, MILEAGE, PRINTING, MEALS, ENTERTAINMENT, PERMIT_FEE), so the PRD uniquely derives `ERR_INVALID_REQUEST` rather than the designed allowability outcomes. Substituted `PRINTING` at the same amounts across all affected instances; every pinned figure is preserved (e.g. 74.99 × 1.1000 = 82.49).
2. **Unresolvable `subcontract_id` in a payable creation body** → asserted `ERR_INVALID_REFERENCE` 422 per PRD §2.9, not the yaml's `ERR_SUBCONTRACT_NOT_FOUND` 404, which §2.9 reserves for path ids.
3. **Phase completion on a CLOSED project** → asserted `ERR_PROJECT_NOT_ACTIVE` 409, since the §2.8 ladder puts owning-project status above transition legality (yaml expected `ERR_INVALID_STATE_TRANSITION`).
4. **Cross-project `parent_phase_id`** → asserted `ERR_WBS_CYCLE` 422 on §3.1's explicit sentence, in preference to the §2.9 body-FK rung.
5. **Two field names the PRD never declares** (`labor_billable_total`, `actual_labor_cost`) dropped; the PRD-declared equivalents (`net_multiplier_achieved` 2.7750, `actual_labor_cost_to_date` 250.00) asserted instead.
6. **Under-determined expectations not asserted**: page composition where all rows share a frozen `created_at`; the earned-value report's `selected_method` spelling; "the payable has no `project_id` field"; "§1.5 declares no mutating verb on /labor-rates" (unreachable over HTTP — replaced by asserting the row carries no `version`/`updated_at`).
7. **Setup repairs that weakened nothing**: activating a project the yaml left phase-less (§3.1 forbids it); stale `expected_project_version` tokens in recipes refreshed so OCC does not mask the rule under test.
8. **Flag for Step 7 — one inconsistency across files.** Where the yaml publishes a multiplier on an *uncertified public-agency* project, `test_04` and `test_13` resolved the null `certified_multiplier_ceiling` differently: `test_04` certifies fiscal 2026 first (ceiling 2.8325), `test_13` asserts that a null ceiling imposes no cap. Both readings are defensible under §3.5/§2.11 and each is self-consistent within its file, but if the implementation picks the other reading one of the two will fail.
9. **Weakest citation in the suite**, flagged deliberately: the three activation-precondition tests assert `ERR_INVALID_STATE_TRANSITION` by elimination (the PRD names the preconditions but no error id for their failure).

**Orchestrator note (process deviation, recorded deliberately):** the skill requires Steps 5 and 6 to be launched in a single assistant message so that the implementation generator starts before `test_suite/` exists and therefore *cannot* read it. I issued Step 5 on its own, so that physical isolation is unavailable for Step 6. Mitigation: Step 6's prompt carries an explicit, absolute prohibition on reading, listing, globbing or grepping `test_helpers/` and `test_suite/` (its inputs are exactly INSTRUCTION.md, SCAFFOLD.yaml and PRD.md), and I will spot-check the resulting implementation for test-shaped tells. No throughput was lost — Step 6 simply runs after Step 5 rather than beside it.

## Step 6: Generate implementation — 2026-09-05T03:45:00.000Z

The implementation is complete, boots cleanly, and all 56 PRD endpoints are wired.

## File inventory
`/home/ubuntu/github/CodingPRD/tasks/task_2812_design_firm_project_accounting_multiplier_billing/workspace/implementation/`

| file | lines | role |
|---|---|---|
| `start.sh` (chmod +x) | 10 | guarded `pip install` (only if flask missing), `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 60 | app factory, 4 blueprints, `ApiError`/404/405/500 envelope handlers, `app.run(host="0.0.0.0", port=$PORT or 10000)` |
| `db.py` | 63 | in-memory `Store` (12 dicts), logical clock default `2026-08-01T00:00:00Z`, `_seq` tie-breaker, uuid ids |
| `errors.py` | 72 | all 44 error ids → HTTP status |
| `money.py` | 42 | Decimal `ROUND_HALF_UP`, `q2`/`q4`, 2dp/4dp serialisers |
| `response.py` | 91 | §2.2 envelope, `req_` + 20 alnum id, 3-digit-ms timestamps, §2.3 pagination |
| `validate.py` | 263 | rung-7 shape validation, all enum vocabularies, body parsed with `parse_float=Decimal` |
| `auth.py` | 63 | ladder rungs 1–6 |
| `guards.py` | 71 | rungs 8–15 shared guards |
| `calc.py` | 665 | every pinned formula, rollups, postures, closure bubble-up |
| `serialize.py` | 284 | 12 entity serialisers + 2 computed reports (recompute-on-read) |
| `flows.py` | 134 | sweep/void/release/write-off cascades |
| `routes_core.py` | 461 | clock, clients, projects, phases, labour rates, multipliers |
| `routes_charges.py` | 251 | time entries, expenses |
| `routes_consultants.py` | 273 | subcontracts, payables, pay-when-paid |
| `routes_billing.py` | 457 | invoices, write-offs, overhead certifications |

**56 routes implemented = 56 rows in the PRD §4 table.** Storage is dicts only; no file, DB or /tmp artifact is written and nothing is seeded (`__pycache__` removed).

## Smoke test (port 47913, single PID killed by exact pid, no pkill)
Two end-to-end scripts passed. Every arithmetic example the PRD pins verified exactly: labour `7.35h × 62.50 × 3.0500 → raw 459.38 / billable 1401.11`; invoice `gross 100500.00 @ retainage 0.0500 → pct 0.0100, discount 1005.00, retainage 4974.75, net 94520.25`; overhead `provisional 1.6500 / final 1.5750 / ceiling 2.8325`; effort earned value `3620.00` vs assessed `50000.00`. Ladder spot-checks returned the right code at the right rung (401/403 role, `ERR_NOT_PROJECT_MANAGER`, `ERR_SEGREGATION_OF_DUTIES` on self-certify, `ERR_STALE_PROJECT_VERSION`, `ERR_MULTIPLIER_ABOVE_CERTIFIED_CEILING`, `ERR_PHASE_NOT_LEAF`, `ERR_WBS_FEE_ROLLUP_MISMATCH`, `ERR_WBS_CODE_DUPLICATE`, `ERR_EXPENSE_UNALLOWABLE`, `ERR_PAY_WHEN_PAID_NOT_SATISFIED`, `ERR_BILLING_EXCEEDS_EARNED`, `ERR_BACKUP_DOCUMENTATION_MISSING`, `ERR_PERIOD_LOCKED`, `ERR_WRITE_OFF_AMOUNT_NOT_ALLOCATABLE`). Void restored `unbilled_wip` and `total_charge_value` byte-for-byte and returned the payable to `UNBILLED`.

## Adjudications (PRD won wherever it disagreed with SCAFFOLD.yaml)
- Header `X-User-ID` (PRD) vs `X-User-Id` (scaffold) — headers are case-insensitive, moot.
- Body FK on `POST /billing-multipliers` and `POST /invoices` is absent from §2.9's list → `ERR_INVALID_REFERENCE` (422) on both.
- `parent_phase_id` unresolvable → `ERR_INVALID_REFERENCE`; resolves but wrong project → `ERR_WBS_CYCLE` (§3.1 is explicit).
- Consultant payable creation does **not** freeze markup (scaffold `side_effects` claims it does; §3.5 keeps all three figures zero until approval).
- §2.8 ladder puts `ERR_BILLING_EXCEEDS_EARNED` **before** `ERR_NOTHING_TO_INVOICE`, contradicting §3.7's narrative order — the ladder wins.
- Activation preconditions (SETUP, >=1 phase, >=1 ACTIVE multiplier) have no declared error id → `ERR_INVALID_STATE_TRANSITION`; same for `submit`'s unreachable `gross_billed > 0` clause and for a receivable write-off whose invoice isn't `APPROVED`.
- `ERR_MULTIPLIER_ABOVE_CERTIFIED_CEILING` fires only when the project's ceiling is non-null (i.e. public-agency client with a CERTIFIED current-year cert).
- `POST /phases/{id}/assess` bumps the **phase** version only; `revise` bumps the invoice (plus newly attached charges), not the project — PRD enumerates project bumps explicitly elsewhere and omits them here.
- Phase creation is not gated on project status (phases must exist before activation); multiplier creation is gated on `CLOSED` only.
- Cascades that hit a row twice increment twice, per literal PRD: subcontract on release-then-close, project on phase-completion-then-closure.
- `created_at` ties (clock frozen between writes) broken by an internal `_seq`; money/ratios emitted as JSON numbers from quantised Decimals.
- `ERR_MULTIPLIER_BACKDATED` second clause read as: violation iff any project time entry with `status == BILLED` has `work_date > effective_from`.
- ClientContact list/read of invoices always restricted to their own client's projects; an explicit `project_id` for another client's project → 403 `ERR_NOT_PROJECT_CLIENT`.
- Not gated on project ACTIVE (absent from both PRD and scaffold validation 40): expense review, payable reject/release, invoice submit/review/revise/record-payment/void, write-off approve, all certification endpoints.
- `POST /_clock/set_current_utc` returns `data: {}`.

**Orchestrator note (post-step):** grepped the whole implementation for test-artifact tells (`test_helpers`, `test_suite`, `conftest`, `pytest`) — 0 hits, so the prompt-level isolation held despite Step 5 having run first. Also probed for forbidden persistence (`sqlite`, file writes, `json.dump`, `/tmp/`, `pickle`, `shelve`) — the only matches were the substring `open` inside `require_period_open(...)`; storage is in-memory dicts only. `start.sh` is present and executable.

## Step 7: Run tests and iterate — 2026-09-05T04:10:00.000Z

Clean sweep — all 8 parallel rounds at 177/177.

## Summary

**Iterations run:** 2

**Iteration 1 baseline:** 173/177 in all 8 rounds — 4 deterministic failures (no flakiness; identical set in every round).

### Tests deleted
None. All 4 failures traced to test-artifact defects, not to PRD-silent assertions.

### Assertions removed (STEP 1c partial-coverage split)
- `test_suite/test_17_compensating_actions.py` — `test_earned_value_survives_the_void_and_re_invoicing_the_period_reproduces_the_money`: dropped the single `assert_swept_counts(voided, 0, 0, 0)` block. **Category: BRANCH-ASYMMETRIC SIDE EFFECT.** PRD §3.7 enumerates the void branch's side effects exhaustively (charges move back and links clear, `unbilled_wip` restored, `billed_open` falls, versions increment) and never mentions the `swept_*_count` fields, while the same sentence implies `gross_billed` is *retained* on the voided row ("its `billed_open` falls by `gross_billed`"). Live-derived-count vs frozen-at-sweep is not determined by PRD prose, so the assertion was not uniquely derivable. The rest of the test (earned value survives, re-sweep reproduces the money) is PRD-covered and was kept.

### Fixes applied to `test_helpers/`
- `test_helpers/api_errors.py` — added `ladder_position()` and repointed `outranks()` at it. `ladder_rung()` collapsed PRD §2.8's explicit within-rung "then" chains into a tie, so `ERR_WBS_CODE_DUPLICATE` vs `ERR_WBS_FEE_ROLLUP_MISMATCH` (both rung 15, but PRD orders them) compared equal. Flattening the ladder preserves both between-rung and within-rung order; verified all 6 `assert_outranks` call-site pairs still hold.
- `test_helpers/assertions.py` — `assert_outranks()` now compares `ladder_position` instead of `ladder_rung` (message reports both).

### Fixes applied to `test_suite/`
- `test_suite/test_04_validation_rules.py` — `test_successor_multiplier_dated_before_the_incumbent_is_refused` and `test_successor_after_the_billed_work_date_truncates_the_incumbent_window`: both did `rows = validate_paginated(...)` then subscripted `rows["items"]` / `rows["total_count"]`, but the runner's `validate_paginated` returns a `(data_list, meta)` tuple — a raw `TypeError`, not a real API assertion. Unpacked the tuple and strengthened each check to assert both the row identities and `meta["total_count"]`.

### Fixes applied to `implementation/`
None — no implementation defects surfaced.

### Adjudication of the flagged cross-file inconsistency
`test_04` (certifies fiscal 2026 first, ceiling 2.8325) and `test_13` (null `certified_multiplier_ceiling` imposes no cap) turn out **not** to conflict. PRD §3.2 caps a multiplier only against the project's ceiling, and §3.9 makes that ceiling `null` when no `CERTIFIED` row matches the clock's calendar year — a null ceiling is therefore no cap. `calc.project_certified_multiplier_ceiling` + the `ceiling is not None and multiplier > ceiling` guard in `routes_core.py:403` already implement exactly that reading, and both files pass unmodified. No change was needed.

**Orchestrator note (post-step verification):** independently re-read all eight `workspace/implementation/results.$i.json` rather than trusting the subagent's claim (a prior pipeline had a Step 7 agent report a clean sweep with no artifacts on disk). All 8 files are present, same timestamp cohort, and each parses to `passed=177 / failed=0 / total=177`. Test count is unchanged from Step 5's 177, consistent with "0 tests deleted".

**Step 8 gating decision:** NOT skipped. The skip condition requires all four counters at zero; Step 7 made 2 `test_helpers/` fixes, 2 `test_suite/` fixes and 1 assertion removal. Implementation fixes were 0, so a byte-identical `PRD_FINALIZED.md` would be a legitimate outcome here — but the assertion removal in `test_17` is exactly the kind of PRD-silence signal Step 8 exists to pin, so the subagent runs.

## Step 8: Finalize PRD — 2026-09-05T04:16:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- `PRD.md`: 439 lines; `PRD_FINALIZED.md`: 439 lines (0.0% line delta; one line revised in place, +766 chars).

## Changes
- §3.7 (void paragraph, line 293) — **revise** — added that the voided invoice's own recorded figures (`labor_billed`, `expense_billed`, `consultant_billed`, `gross_billed`, `volume_discount_pct`, `discount_amount`, `retainage_amount`, `net_due`, `swept_labor_count`, `swept_expense_count`, `swept_consultant_count`, `backup_missing_count`) are left exactly as the last sweep computed them rather than zeroed, with the row simply ceasing to contribute to the §2.10 buckets — `implementation/flows.py:100-123` (`detach_invoice` touches no invoice field) + `implementation/routes_billing.py:200-215` (void sets only `status`/`void_reason`) + `implementation/serialize.py:231-242` (fields served straight from the row).

## Pre-edit search log
**Edit 1 — §3.7 void, retained sweep figures**
- (a) Subject: the invoice row's persisted sweep/money fields — the three `swept_*_count`s, `backup_missing_count`, and the four money figures — and every operation that can write them.
- (b) Paths enumerated: `grep swept_` and `grep gross_billed|net_due|labor_billed|expense_billed|consultant_billed|volume_discount_pct|discount_amount|retainage_amount` across all of `implementation/*.py`. Only writer is `flows.write_invoice_figures` (`flows.py:81-97`), reached from exactly two callsites: `routes_billing.py:65` (prepare) and `routes_billing.py:173` (revise). Read/verified the non-writers on the same entity: `detach_invoice` (`flows.py:100-123`), `void_invoice` (`routes_billing.py:200-215`), `submit_invoice` (`104-125`, reads `gross_billed`/`backup_missing_count` only), `review_invoice` (`128-152`), `record_invoice_payment` (`181-197`), `approve_write_off`'s `INVOICE_RECEIVABLE` branch (`330-347`, sets `status` only), `invoice_out` (`serialize.py:222-247`, pure passthrough — no recompute-on-read for invoices), and the rollup consumers `project_billed_open`/`project_paid_gross_to_date`/`project_written_off_gross`/`fixed_fee_headroom` (`calc.py:277-301, 577`), all of which filter `VOID` out by status.
- (c) Wording adjustments made: (1) said "left exactly as the **last sweep** computed them" rather than "as preparation computed them", so the revise path — which legitimately rewrites all twelve fields, including the two counts PRD's revise paragraph does not enumerate — is not contradicted; (2) appended "the row simply stops contributing to any of the four buckets of §2.10" so the retained `gross_billed` cannot be misread as still feeding `billed_open`/`written_off_gross`, matching the status filters in `calc.py:277-301`; (3) scoped the sentence to the invoice's *own recorded figures* and left the detached charges' own fields to the existing prose.

## Items deliberately not patched
- **`test_helpers/api_errors.py` within-rung ordering fix** — not a PRD silence. PRD §2.8 rung 15 already spells the within-rung order explicitly as a `then` chain (`… ERR_WBS_CODE_DUPLICATE`, then … `ERR_WBS_FEE_ROLLUP_MISMATCH`, …), and `routes_core.py:212-215` (duplicate) precedes `routes_core.py:230-232` (fee rollup), so impl matches PRD verbatim. The collapsed-tie was purely a helper defect.
- **`test_suite/test_04` tuple-unpacking fixes** — pure fixture bugs (`validate_paginated` returns a tuple). The behaviours under test (`ERR_MULTIPLIER_BACKDATED` on a successor at/before the incumbent's `effective_from`, truncation of the incumbent window, list ordering/`total_count`) are all already pinned by §3.2 and §2.3, and `routes_core.py:416-427` implements them as written.
- **Certified-ceiling / null-ceiling adjudication** — Step 7 concluded no conflict and changed nothing; §3.2 + §3.9 already determine `calc.project_certified_multiplier_ceiling` and the `ceiling is not None` guard at `routes_core.py:404`.

**Orchestrator note (post-step):** verified the diff myself — `PRD_FINALIZED.md` is 439 lines / 93,461 bytes against PRD.md's 439 / 92,941, and `diff` shows exactly one changed line (293, the §3.7 void paragraph). Not byte-identical, so the edit did land; and the single-hunk diff confirms the subagent honoured the minimal-patch scope rather than rewriting spans.

## Step 9: Complete PRD — 2026-09-05T04:40:00.000Z

**Orchestrator design decision.** Step 9 was run as **three sequential subagent passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module**, rather than as a single subagent. A single agent cannot hold a 443-line PRD plus a 3,261-line 17-module implementation in context deeply enough to do an exhaustive behaviour-by-behaviour scan, and the observed failure mode is that it produces a PRD_COMPLETED.md byte-identical to its input — i.e. the scan silently never ran. Partition:

- **Pass 1 (owns the `cp`)** — `app.py`, `db.py`, `errors.py`, `money.py`, `response.py`, `validate.py`, `auth.py`, `guards.py`, `serialize.py`, `routes_core.py` (clock, clients, projects, phases, labour rates, billing multipliers).
- **Pass 2** — `routes_charges.py`, `routes_consultants.py`, `flows.py`, plus the `calc.py` bodies for labour charge, expense allowability/markup, consultant markup and commitment arithmetic.
- **Pass 3** — `routes_billing.py`, plus the `calc.py` bodies for invoice totals, earned value, closure bubble-up, overhead rate and certified ceiling, WIP aging, write-off allocation/routing, profitability.

Passes 2 and 3 were explicitly forbidden from copying or wholesale-writing the file (that would destroy the earlier passes' edits) and each verified the prior passes' edits had survived before exiting.

### Pass 1 — 21 changes (14 ambiguity-pins, 7 mismatch-revisions); 439 → 443 lines, 93,461 → 99,867 chars
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + twenty uppercase-alnum chars, minted per response, never persisted — `response.py:10,19`
- §2.3 — insert — ambiguity — non-integer-literal `limit`/`offset` is `ERR_INVALID_REQUEST` — `response.py:56-75`
- §2.3 — insert — ambiguity — `created_at` ties (the norm, since the logical clock is static) break by write order — `response.py:79-83`
- §2.3 — insert — ambiguity — `has_more` = `offset + len(page) < total_count`; `total_count` is pre-pagination — `response.py:40,89`
- §2.4 — revise — mismatch — the "derived refresh restamps every ancestor" claim narrowed: only rows a transition names are restamped — `calc.py:41`, `routes_core.py:291`
- §2.5 — insert — ambiguity — money/ratio are JSON numbers, so decimal places are a rounding not textual contract — `money.py:31-42`
- §2.5 — insert — ambiguity — explicit `null` == absent (required→missing, optional→default, forbidden→tolerated); empty body == `{}`; non-object body is 400; unknown fields ignored — `validate.py:49-59,62-63,261`
- §2.6 — insert — ambiguity — `to_iso8601` accepts `Z`/offset/naive-as-UTC, clock may move backwards, no stamps rewritten, answers 200 with empty `data` — `routes_core.py:22-29`, `validate.py:212`
- §2.7 — revise — mismatch — "neither require nor **accept**" → the field is ignored, not rejected, outside the two endpoints — `validate.py:261`
- §2.8 — insert — mismatch — rungs 3–6 are skipped when their subject row can't be resolved, so rung 8/9 (or 7 on an unparseable body) reports — `auth.py:29,39`, `guards.py:16`, `validate.py:36-42`
- §2.9 — revise — mismatch — body-FK list was missing billing multiplier creation and invoice creation — `routes_core.py:396`, `routes_billing.py:32`
- §2.9 — insert — ambiguity — filters are conjunctive; bad enum filter is 400; booleans only exact `true`/`false`; `effective_on` is a date resolved half-open; id filters exact-match to an empty page — `validate.py:227-258`, `routes_core.py:372-379`
- §3.1 — insert — ambiguity — all seven client fields required, `disallowed_categories` may be empty but not omitted — `routes_core.py:39-52`
- §3.1 — insert — ambiguity — activation's three preconditions all report `ERR_INVALID_STATE_TRANSITION`, in the stated order; no body/version — `routes_core.py:143-151`
- §3.1 — insert — ambiguity — phase creation is outside the ACTIVE gate (`SETUP`/`ACTIVE`/`CLOSED` all admitted), no version field — `routes_core.py:178-250`
- §3.1 — insert — ambiguity — the unused fee field is stored/returned `null`; the rollup cap binds children<->parent only, so top-level fees may sum past `contract_amount` — `routes_core.py:197,201,224-232`
- §3.1 — insert — ambiguity — lock-period admitted in any project status, no version field, returns the project, and replaces the prior date unconditionally — `routes_core.py:157-165`
- §3.2 — insert — ambiguity — a labour rate's `effective_to <= effective_from` is `ERR_INVALID_REQUEST` — `routes_core.py:347`
- §3.2 — insert — ambiguity — a multiplier's `effective_to` is *not* validated against its `effective_from` — `routes_core.py:394`
- §3.2 — revise — mismatch — "truncation" is an unconditional assignment, so an incumbent with an earlier explicit `effective_to` is *widened* — `routes_core.py:424-427`
- §3.6 — insert/revise — mismatch — assess on a `COMPLETE` phase is `ERR_INVALID_STATE_TRANSITION`; assess leaves `status` and bumps the phase's `version` only — `routes_core.py:288-291`
- §3.9 — revise — mismatch — a project's `certified_multiplier_ceiling` is `null` on any non-public-agency client regardless of certifications — `calc.py:336-347`, `serialize.py:61`
- §5 — insert — mismatch — `ERR_INVALID_REQUEST` also answers unknown path (404) and disallowed method (405) — `app.py:37-43`

### Pass 2 — 16 changes (12 ambiguity-pins, 4 mismatch-revisions); 99,867 → 103,732 chars (line count unchanged, all in-paragraph)
- §3.1 — insert — ambiguity — a leaf phase's own `status` is never consulted at charge placement, so charges may be booked to a `PLANNED`, `IN_PROGRESS` or already `COMPLETE` leaf — `routes_charges.py:47-49,159-161`, `routes_consultants.py:41-42`
- §3.3 — insert — ambiguity — submission restamps nothing but the new line — `routes_charges.py:50-68`
- §3.4 — insert — ambiguity — a `PENDING_REVIEW` expense leaves the project untouched — `routes_charges.py:186-189`
- §3.4 — insert — ambiguity — review carries no owning-project status gate; `DISALLOW` increments only the expense's `version` — `routes_charges.py:222-251`
- §3.4 — insert — ambiguity — `ALLOW` increments both the expense's and the project's `version` — `routes_charges.py:248-250`
- §3.4 — revise — mismatch — `ERR_EXPENSE_UNALLOWABLE` does **not** guard invoicing; the sweep silently gathers only `ALLOWED` expenses — `calc.py:553`, `routes_charges.py:237`
- §3.5 — insert — ambiguity — `commitment_end` before `commitment_start` is `ERR_INVALID_REQUEST` on the shape rung, ahead of body-FK resolution — `routes_consultants.py:35-37`
- §3.5 — insert — ambiguity — drafting restamps neither project nor phase — `routes_consultants.py:43-57`
- §3.5 — insert — ambiguity — the named subcontract may be `DRAFT`/`EXECUTED`/`CLOSED` at payable entry (the `EXECUTED` test bites at approval) — `routes_consultants.py:130-155`
- §3.5 — insert — ambiguity — both approval status conditions are `ERR_INVALID_STATE_TRANSITION`, payable axis first; `amount` exactly equal to `committed_remaining` is permitted — `routes_consultants.py:200-208`
- §3.5 — revise — mismatch — "Rejected payables contribute to neither sum" was false: `released_to_date` keys on `payment_status` alone — `calc.py:211-229`
- §3.5 — revise — mismatch — "a rejected payable's `payment_status` stays `WITHHELD` permanently" was false: release-then-reject is legal and keeps `RELEASED` — `routes_consultants.py:238-253`, `flows.py:12-24`
- §3.5 — insert — ambiguity — failing either explicit-release status condition is `ERR_INVALID_STATE_TRANSITION`; the route ignores project `status` — `routes_consultants.py:263-265`
- §3.7 — insert — ambiguity — on revise, a charge already carrying this invoice's link is not re-stamped; only newly attached charges increment — `flows.py:42-61`
- §3.7 — revise — mismatch — payables detach on void only while `payment_status` is `WITHHELD`; an already-`RELEASED` payable keeps `BILLED_TO_CLIENT` (conservation qualified rather than falsely universal) — `flows.py:117-123`
- §3.8 — insert — ambiguity — an allocated entry no longer `APPROVED` at approval time is silently skipped — `flows.py:126-134`

### Pass 3 — 14 changes (11 ambiguity-pins, 3 mismatch-revisions); 103,732 → 107,176 chars (line count unchanged)
- §2.1 — insert — ambiguity — invoice-list ownership check runs only when a `ClientContact` supplies a resolving `project_id`; otherwise the page is silently narrowed with no error — `routes_billing.py:87-100`
- §2.9 — insert — ambiguity — integer filters (`fiscal_year`) tolerate sign/zero-padding unlike `limit`/`offset` — `routes_billing.py:407`, `validate.py:247`
- §3.6 — insert — ambiguity — the earned-value report's `selected_method` always echoes the project's `percent_complete_method`, even on a `COMPLETE` phase — `serialize.py:112`
- §3.7 — revise — mismatch — the empty-sweep refusal is preceded by the fixed-fee ceiling, so a nothing-swept request against negative headroom reports `ERR_BILLING_EXCEEDS_EARNED` — `routes_billing.py:41-50`
- §3.7 — insert — ambiguity — submit's draft-status and positive-`gross_billed` conditions are `ERR_INVALID_STATE_TRANSITION` — `routes_billing.py:112-115`
- §3.7 — revise — mismatch — a review decision records `client_decision_comment` unconditionally, writing `null` over an earlier round's comment — `routes_billing.py:143`
- §3.7 — insert — ambiguity — revise re-applies only the fixed-fee ceiling (no project-status/`HOLD`/empty-sweep re-test) — `routes_billing.py:160-171`
- §3.7 — revise — ambiguity — revise increments the invoice's `version` but leaves the project's untouched — `routes_billing.py:177`
- §3.7 — revise — mismatch — settlement hop two now carries the `APPROVED` + `BILLED_TO_CLIENT` + `WITHHELD` filter — `flows.py:32-36`
- §3.8 — insert — ambiguity — write-off `invoice_id` is a bare body FK: need not belong to the named project, status untested until approval — `routes_billing.py:242`
- §3.8 — insert — ambiguity — both `aging_days` computations floor a negative age at zero — `calc.py:124-128`, `routes_billing.py:258,266`
- §3.8 — insert — ambiguity — neither approval branch consults the project's `status`, so a write-off may be approved after closure — `routes_billing.py:314-353`
- §3.8 — revise — ambiguity — `INVOICE_RECEIVABLE` approval tests invoice-`APPROVED` first then re-tests `net_due` equality — `routes_billing.py:330-337`
- §3.9 — insert — ambiguity — `unallowable_costs` is bounded below only, never against the pool; excess yields a negative final rate — `routes_billing.py:367`, `calc.py:626-628`
- §3.9 — insert — ambiguity — certification hop two sweeps public-agency projects in any status and no private-client project — `routes_billing.py:437-441`

Pass 3 also resolved the two gaps pass 2 handed it: (a) §3.7's hop-two sentence now states all three payable filters, so §3.5 and §3.7 agree; (b) §2.8's rung 16 *already* ordered `ERR_BILLING_EXCEEDS_EARNED` before `ERR_NOTHING_TO_INVOICE`, but the §3.7 narrative did not — the narrative was revised. Pass 3 reports that §2.10's rollup formulas, the pinned invoice money-figure order, volume-discount tiers, retainage/net-due, sweep population, aging buckets, write-off allocation/routing, and the provisional/final overhead rate and ceiling formulas all already matched `calc.py` exactly.

### Totals
**51 changes across the three passes: 37 ambiguity-pins, 14 mismatch-revisions.** `PRD_FINALIZED.md` 439 lines / 93,461 chars → `PRD_COMPLETED.md` 443 lines / 107,176 chars (+4 lines, +13,715 chars, +14.7%).

**Orchestrator note (post-step verification):** confirmed `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (the tell that the scan never ran) — `diff` reports 45 changed lines. Structural integrity re-checked independently: all five `## ` top-level sections present in order (§1 L3, §2 L11, §3 L184, §4 L331, §5 L394); the §4 routing table still carries 56 endpoint rows; the §5 catalogue still carries 44 error rows; the file ends at the genuine final boundary `| \`ERR_WRITE_OFF_AMOUNT_MISMATCH\` | 422 |`. Spot-checked that each pass's edits survived the later passes: pass 1's §2.2 `api_request_id` sentence at line 52, pass 2's §3.5 release-then-reject revision at line 255, pass 3's `BILLED_TO_CLIENT` hop-two filter (5 occurrences). No difficulty-directive leak ("harder than expert", "expert_plus"): 0 hits.

No test or implementation code was touched by Step 9, so the Step 7 result stands: 8/8 rounds at 177/177. Pipeline complete.
