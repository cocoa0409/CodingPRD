# Worklog — task_2876_brand_recommerce_resale_as_a_service

## Step 1: Create task directory — 2026-09-05T10:10:36.981Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2876_brand_recommerce_resale_as_a_service` and its `workspace/` subdirectory. Index 2876 was pre-assigned by the orchestrating prompt (no scan/auto-allocation, to avoid collision with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T12:01:00.000Z

Done. All three scaffold artifacts are complete and the mandated lint passes.

**Verdict block (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2876_brand_recommerce_resale_as_a_service/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2876_brand_recommerce_resale_as_a_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2876_brand_recommerce_resale_as_a_service/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1397

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2876_brand_recommerce_resale_as_a_service/`):
- `SCAFFOLD.yaml` — 3074 lines, 145 KB; top-level keys are §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design`). 15 entities, 54 endpoints, 63 error ids, 6 roles, 13 calculations.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2167 lines, 136 KB; single key `scaffold_difficulty_design`, 9 rules × 2 instances = 18.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 6006 lines, 380 KB; single key `scaffold_corner_design`, all nine taxonomy sections present: entities 15, state_machines 10, calculations 11, validations 7, endpoints 4, errors 14, rbac 6, cross_cutting_complexity_layers 5, consistency_model 1 = 73 instances (63 with full `test_recipe`, 10 `excluded_because:` stubs).

**Key findings from this final stretch:**
- Error-id coverage is complete: all 63 catalog ids are triggered in §1.9 or stubbed to a §1.8 instance that genuinely asserts them (verified by grepping the difficulty file for each stubbed id).
- `ERR_STALE_UNIT_VERSION` is only reachable with a wrong-valued version on an `INTAKE` unit: validation priority 50 (per-transition state error, i.e. `ERR_UNIT_NOT_SCHEDULABLE`) outranks the OCC check at 52, and no transition bumps `ResaleUnit.version` while leaving it schedulable. Since the lint forbids literal OCC values, the instance sources the wrong version from a `PATCH /recommerce/customers/{id}` response (version 3) — documented in the asserts.
- Two internal SCAFFOLD.yaml contradictions found earlier this session remain fixed: the `QC_PENDING -> COMPLETED` override precondition now says ProgramAdmin (matching validation 74), and `ERR_CAMPAIGN_NOT_RUNNABLE` no longer contradicts the `SCHEDULED/ACTIVE -> CLOSED` boundary run.
- Lint-driven fixes applied: `$.data.total_count` is not a capturable path on array-output endpoints (three occurrences rewritten as prose asserts, matching the convention used earlier in the file), and the one literal OCC version.
- Heads-up for the orchestrator: `SCAFFOLD.yaml`'s `scenario:` still begins with the line `Generate task harder than expert level!` because the scenario was supplied verbatim and must not be modified. Per the known leak path (scenario → PRD.md), that line should be stripped in the post-Step-2 cleanup.

**Orchestrator post-step action:** acted on that heads-up — stripped the `Generate task harder than expert level!` line (and its trailing blank line) from `SCAFFOLD.yaml`'s `scenario:` block so the difficulty directive cannot reach PRD.md via the doc generator. Re-verified: `grep -rn "harder than expert"` over the task dir returns nothing, and `yaml.safe_load(SCAFFOLD.yaml)` still parses.

## Step 3: Copy shared files — 2026-09-05T12:03:01.394Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T12:23:00.000Z

PRD generation is complete.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2876_brand_recommerce_resale_as_a_service/workspace/PRD.md` — **468 lines / 100,671 bytes**, written incrementally (1 `Write` + 9 heredoc appends, no single giant write). `tail -40` shows the file ending on the last row of the §5 error table (`| \`ERR_REPORT_ALREADY_PUBLISHED\` | 409 |`) — a completed final section, no audit footer, nothing mid-sentence.

Structure: §1 Introduction; §2 Global Specifications with 12 subsections (2.1 RBAC, 2.2 verbatim response contract, 2.3 pagination, 2.4 logical clock and window semantics, 2.5 integer money/mass/basis points and the three rounding modes, 2.6 identity/version counters, 2.7 policy supersession, 2.8 stale-view rejection, 2.9 cascade discipline and the append-only ledger, 2.10 segregation of duties and ownership scoping, 2.11 a 21-step request admission ladder, 2.12 conservation invariants); §3 with 9 workflow subsections (configuration → intake → grading/appeal → disposition → refurbishment → listing/markdown → purchase → after-sale → expiry & reporting); §4 endpoint table; §5 error catalogue.

## Hard Contract results

**Contract 1 — Field-Name Coverage: PASS.** All 127 names in the mechanically derived inventory (`/tmp/task_2876_prd/required_fields.txt`) appear in backticks. Two additional broader sweeps were run: (a) every snake_case value under any `name`/`field`/`fields` key in the scaffold — the only 17 absent tokens are rule/variant/invariant *identifiers* (`return_refund_settlement`, `replacement_unit_selector`, `remorse_return`, `credit_expiry_sweep`, …), which are expressed as prose rather than as field names; (b) every suffix-shaped identifier anywhere in the scaffold text — the 27 absent tokens are all formula-local intermediates (`raw_minor`, `stepped_minor`, `shortfall_minor`, `non_refundable_minor`, `margin_floor_minor`, `channel_cap_minor`, `redemption_cap_minor`, …), scaffold meta keys (`domain_name`, `rule_id`, `initial_state`) and fee-band table keys (`up_to_minor`, `fee_bp`), none of which are persisted or wire fields. Additionally, every `input:` field name of all 54 endpoints is present.

**Contract 2 — Rule Coverage: PASS.** Verified mechanically and by walk against the scaffold's 15 entities, 7 state machines (49 transitions, including the four campaign legs, `RETURNED → LISTED` re-listing, `LISTED → SOLD` substitution, and the nine cyclic `CreditGrant` legs with the release-then-immediate-re-expiry pair), 2 concurrency rules, 13 calculations (all reconstructable from prose, with rounding mode and evaluation order pinned per formula), 32 validations, 63 errors and all 16 global constants (tier bonus 500 bp, 60000 cap, 21/2-day intake windows, appeal limit 1, 145-per-minute labour rate, 10000/13500/9000 bay multipliers, 60-minute sanitation buffer, rework limit 2, 11500 bp margin, the three channel-fee bands, 14-day remorse window, 2 concurrent campaigns per channel, default clock, money/bp units). All 63 concrete error ids appear in §1–§3 prose, not just in the §5 table; the only validation `error_id` strings not literally present are the scaffold's own templated placeholders (`per-entity ERR_<ENTITY>_NOT_FOUND`, `per-transition state error`). No scaffold `worked_example` numbers leaked into the prose.

**Contract 3 — §3 Path Purity: PASS.** 987 backticked spans in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combos, and zero unbackticked `/recommerce` or HTTP-method mentions. Paths appear only in §1/§2/§4, where the spec allows them.

## Cross-checks and one deliberate resolution
- §4: 54 rows, exactly matching the scaffold's 54 endpoints on method, path and role list (no diffs). Status-code claim verified: exactly 12 endpoints declare 201 and all are creations; every other endpoint declares 200.
- §5: 63 rows, identical set, identical HTTP statuses, and in the scaffold's own declaration order.
- §2.2 is byte-identical to `section-2.2-response-structure.md`.
- Style: no pseudocode, no operator syntax (`==`, `<=`, `:=` and all `→` arrows were removed in a final pass and rewritten as prose), no fuzzy quantifiers.
- Scaffold self-contradiction on report supersession: the state machine allows only `PUBLISHED → SUPERSEDED`, while the publish `side_effects` say `DRAFT|PUBLISHED -> SUPERSEDED`. I rendered the superset (either `DRAFT` or `PUBLISHED` moves to `SUPERSEDED`), since no error code exists for superseding a draft, so the superset cannot conflict with a test that only exercises the published case.
- Earlier noted issues remain fixed: the placeholder error id typo in §3.3 is now `ERR_APPEAL_LIMIT_EXCEEDED`, and a full sweep confirms no invented error identifiers (`in PRD not in scaffold: []`).

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read. Scratch files live only in `/tmp/task_2876_prd/`.

**Orchestrator truncation check (mandated guard):** ran `wc -l`/`tail -25`/`grep -n '^## '` on PRD.md. 468 lines; five top-level sections present (§1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue); the file ends on the final complete row of the §5 error table. Not truncated — no regeneration needed. Also re-confirmed no difficulty-directive or scaffold-reference leak in PRD.md.

## Step 5: Generate unit tests — 2026-09-05T14:22:16.000Z

Generation complete. `test_15_configuration_and_platform.py` closed the last eight open corner instances, and both mandatory audits are clean.

## Outputs (task root, nothing under `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2876_brand_recommerce_resale_as_a_service/test_helpers/` — 9 files, 2544 lines (`__init__` 59, `api_client` 331, `api_errors` 142, `assertions` 355, `constants` 139, `factories` 244, `fixtures` 723, `test_users` 101, `types` 450).

`.../test_suite/` — `conftest.py` 84 plus 15 test modules, 7709 lines total, **100 tests**:

| file | lines | tests |
|---|---|---|
| test_01_intake_and_provisional_quote.py | 642 | 10 |
| test_02_grading_and_appeals.py | 388 | 5 |
| test_03_disposition_and_credit_issuance.py | 382 | 5 |
| test_04_refurbishment_scheduling.py | 524 | 9 |
| test_05_refurbishment_costing_and_qc.py | 740 | 12 |
| test_06_listing_and_pricing.py | 273 | 4 |
| test_07_markdown_campaign_declaration.py | 497 | 6 |
| test_08_markdown_cadence_runs.py | 413 | 5 |
| test_09_purchase_settlement_arithmetic.py | 598 | 6 |
| test_10_redemption_restrictions_and_concurrency.py | 675 | 8 |
| test_11_after_sale_refunds.py | 705 | 8 |
| test_12_warranty_replacement.py | 364 | 4 |
| test_13_expiry_and_diversion_reporting.py | 388 | 5 |
| test_14_access_control.py | 509 | 5 |
| test_15_configuration_and_platform.py | 527 | 8 |

## Audits

- **PRD citation audit (C1–C3):** 457 quotes checked, 0 missing — every `PRD §x.y: "..."` quote survives a literal whitespace-normalised match against `workspace/PRD.md`.
- **Design coverage / C4 audit:** 100 `Design:` tags emitted, 81 distinct, against 81 non-stub instances (18 difficulty × 2 tests + 63 corner × 1). **UNDER-COVERED: 0**, and zero tags pointing outside either index. Every test has exactly one tag, and a structural check confirms each tag is the last line of its docstring.
- `python3 -m pyflakes test_suite/*.py` rc=0; all 15 modules import cleanly with exactly 100 tests discovered.

## Notable restatements (PRD-first filter)

Several design instances paired `channel: MAIL_IN` with a `store_location_id` and then refurbished or listed the unit, which PRD §3.2 L197 (store required for IN_STORE, null for MAIL_IN) and §3.5 (bay must belong to the trade-in's custody store) forbid. Those setups were restated to IN_STORE sellers, or to a MAIL_IN grant whose unit never leaves `INTAKE`, keeping every asserted figure PRD-derived. The difficulty instance `warranty_replacement_preserves_tracked_mass_conservation_exactly` additionally asserted the *seller's* `diverted_grams_total` while naming a different buyer — §3.8 only recomputes the **buyer's** — so the seller was made the buyer and its `credit_liability_minor` restated from 23000 to 21000 (two IN_STORE PLUS grants of 10500).

No stubs, skips or xfails were emitted; `worklog.md`, `PRD.md` and the SCAFFOLD files were left untouched, and `workspace/implementation/` was never read.

## Step 6: Generate implementation — 2026-09-05T13:53:48.000Z

(Launched concurrently with Step 5; finished earlier. Recorded here in step order.)

Implementation complete and smoke-verified.

## Files — `/home/ubuntu/github/CodingPRD/tasks/task_2876_brand_recommerce_resale_as_a_service/workspace/implementation/`

| file | lines | role |
|---|---|---|
| `services.py` | 505 | all domain math + multi-entity cascades (appraisal, refurb costing/viability, list price, settlement, waterfalls, expiry sweep, markdown step, replacement selector, diversion metrics, window helpers) |
| `r_config.py` | 299 | customers, grade/credit policies, stores, bays, channels, logical clock |
| `r_tradein.py` | 268 | intake, receive, authenticate, appeal, disposition cascade |
| `r_orders.py` | 260 | placement/settlement, fulfil, return-request, settle-return (REFUND / REPLACE / DENY) |
| `r_refurb.py` | 258 | bay bookings, task lines, start, submit-qc, qc-decision |
| `r_market.py` | 184 | resale-unit reads, listing, markdown campaigns, cadence runs |
| `store.py` | 179 | in-memory dict tables + logical clock (default `2026-08-01T00:00:00Z`) |
| `validators.py` | 171 | header guard, body shape, query params |
| `errors.py` | 114 | 66-id catalogue + `ApiError` |
| `constants.py` | 94 | pinned constants and enum tuples |
| `r_reports.py` | 93 | diversion reports + publish/supersede |
| `r_credit.py` | 71 | grants, grant ledger, expiry-runs |
| `app.py` | 67 | Flask app, 7 blueprints under `/recommerce`, error handlers |
| `envelope.py` | 52 | success/list/error envelopes, pagination meta |
| `access.py` | 35 | Customer ownership scoping |
| `serialize.py` | 33 | row → JSON incl. computed `aged_days` |
| `start.sh` | 17 | guarded `pip install`, `exec python3 app.py` on `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `flask>=2.0` |

## Verification
- `python3 -m py_compile *.py` clean; `__pycache__` removed afterwards.
- **Scenario 1** (fresh boot, port 22411): full happy path — config → IN_STORE trade-in → receive/authenticate/disposition → grant + unit → refurb order/task/QC PASS → listing → markdown run → purchase → fulfil → remorse return → REFUND → expiry sweep → report generate/publish, plus negative checks (401 blank header, 404 unknown id, 422 duplicate/`limit=0`/non-whole-day window, 409 report overlap, 405, unknown route 404). **0 failures.** Numbers matched hand-computation: credit 31500 (PLUS bonus floored on base), task cost 4850, viability 970 bp, capitalized 36350, list price 50000, markdown 50000→45000, fee 2925 at 650 bp on gross alone, total 47925, restock 4500, refund cash 39500 / credit 1000.
- **Scenario 2** (fresh boot): salvage-at-birth (`SALVAGED`/`EXPENSED`), DENY→re-claim cycle, REPLACE (cheapest candidate, defective→`SALVAGED`/`EXPENSED`/channel cleared, substitute→`SOLD` with lineage, **no ledger entries**), `ERR_NO_REPLACEMENT_UNIT`, `ERR_STALE_CUSTOMER_VERSION` (412), `ERR_ASSORTMENT_NOT_PERMITTED`, idempotent second expiry sweep (zeros), and the release-then-re-expire pair — buyer balance returned to exactly its pre-settlement value and per-grant ledger net equalled `remaining_minor` for all 6 grants (conservation invariant holds). **0 failures.**
- Final fresh-boot check on port 22777 via `bash start.sh` with `PORT` exported: server answered `GET /recommerce/trade-ins` and `GET /recommerce/credit-grants` with empty arrays (no seeded data) and the clock setter with 200, then was killed by its recorded PID only (`kill 2453476`, confirmed gone). No pattern-based `pkill` was ever used; scratch stayed in `/tmp/task_2876_impl/`.

Test blindness honoured: `test_helpers/` and `test_suite/` were never read, listed, globbed or grepped, and no sibling `task_*/` directory was touched. `worklog.md`, `PRD.md` and the SCAFFOLD files were read-only.

Key judgement calls to be aware of: query-parameter FK filters are validated to per-entity 404 uniformly; `ERR_CREDIT_NOT_REDEEMABLE_HERE` fires when the buyer holds live unexpired grants but none admit the channel and credit was requested; `ERR_BAY_STORE_MISMATCH` is skipped for mail-in units (no origin store); fulfilment falls back to 0 warranty days if no ACTIVE tier policy exists (§2.11 does not list policy availability for fulfilment); duplicate unique codes/emails return `ERR_INVALID_REQUEST` 422 (no dedicated catalogue code).

**Orchestrator layout check:** `test_helpers/` and `test_suite/` are at the task root (nothing stray under `workspace/`, which contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`). Only one `worklog.md` exists, at the task root. Removed the stray `test_suite/__pycache__` before Step 7.

## Step 7: Run tests and iterate — 2026-09-05T14:43:42.000Z

All 8 rounds green. Done.

## Summary

**Iterations run:** 2 (sweep 1 → 4 deterministic failures; sweep 2 → clean).

**Tests deleted:** none. All four failures traced to test-artifact defects, not to PRD-silent or non-derivable rules, so nothing needed deletion.

**Fixes applied to `test_suite/`** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2876_brand_recommerce_resale_as_a_service/test_suite/`):

- `test_04_refurbishment_scheduling.py` · `test_a_stale_unit_version_refuses_the_create_and_supersedes_nothing` — the final assertion read `second["expected_resale_unit_version"]` off the refurb-order response (`KeyError`). PRD §2.8/§3.5 name that field only as a *request-body* input, and §3.5's enumeration of a newly scheduled order's fields omits it, so a faithful implementer would correctly not serialize it (uncovered assertion, STEP 1c partial-coverage split). Kept the covered intent — that starting work increments the unit's version past what the scheduler observed — by capturing `observed_before_second = fetch_unit(...)` and comparing against its `version`.
- `test_04_refurbishment_scheduling.py` · `test_bay_ownership_qc_sequencing_and_override_authority_all_refuse` — the override-authority probe signed QC as `TECH1`, which is the very identity `start_refurb_order` had stamped into `performed_by_user_id`, so PRD §2.11's gate 9 (`ERR_SEGREGATION_OF_DUTIES`) legitimately pre-empted gate 18 (`ERR_OVERRIDE_ROLE_REQUIRED`). Switched the signer to `TECH2` (also a `RefurbTechnician`, so the asserted PRD rule is still the one under test) and added the `TECH2` import.
- `test_09_purchase_settlement_arithmetic.py` · `test_the_waterfall_drains_the_earliest_expiring_grant_first` — asserted the SALVAGE-graded unit was `INTAKE`, directly contradicting PRD §3.4 ("When the `assessed_grade` is `SALVAGE`, the unit that was just created is moved, **inside the very same request**, to lifecycle state `SALVAGED`"). Corrected to `SALVAGED`, which also still satisfies the test's stated purpose of keeping that unit out of the listing pool.
- `test_14_access_control.py` · `test_the_customer_role_shares_every_operation_it_holds` — setup called bare `setup_estate()` (only an OUTERWEAR/B tier policy) then graded the trade-in at `C`, so the PRD-required check of §3.3 ("Grading is refused unless an `ACTIVE` condition-tier policy exists for the pair") correctly returned `ERR_GRADE_POLICY_MISSING`. Passed `grade_policies=(GRADE_POLICY_OUTERWEAR_B, GRADE_POLICY_OUTERWEAR_C)` and added both imports.

**Fixes applied to `test_helpers/`:** none — no shared fixture/factory defect was implicated.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on all four points, including the §2.11 admission ordering that put segregation-of-duties ahead of the override-privilege check.

**Final sweep evidence:** 100/100, 100/100, 100/100, 100/100, 100/100, 100/100, 100/100, 100/100 (rounds 1–8, zero failures and zero errors in every round). `worklog.md`, `workspace/PRD.md`, `workspace/sweep.sh` and every file under `workspace/implementation/` are untouched.

**Orchestrator verification (not taken on trust):** re-read all 8 `workspace/implementation/results.$i.json` myself — each reports `passed=100`, `total=100`, zero failures. Also confirmed `test_suite/` still declares exactly 100 tests, consistent with the "0 deletions" claim. The baseline sweep I observed independently at 14:33Z was a deterministic 96/100 in all 8 rounds, matching the reported 4-test union.

**Step 8 skip-condition adjudication:** NOT skipped. The skip condition requires zero iterations beyond the baseline with 0 deletions and 0 fixes of any kind; Step 7 ran 2 iterations with 4 `test_suite/` fixes. Because there were 0 `implementation/` fixes, Step 8 may legitimately produce a PRD_FINALIZED.md that is byte-identical or near-identical to PRD.md — the Step 7 diff contains no implementation behavior change to pin, and the one PRD-silence it did reveal (`expected_resale_unit_version` not being a response field) is a serializer omission that PRD §3.5's field enumeration already implies. An identical Step 8 output is therefore an acceptable outcome here; Step 9's full scan is where residual ambiguity gets closed.

## Step 8: Finalize PRD — 2026-09-05T14:47:00.000Z

`PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- PRD.md: 468 lines; PRD_FINALIZED.md: 468 lines. 1 line changed → **0.21% delta**, 0% line-count delta.

## Change list (1 change)
- **§3.4 (Disposition, the salvage-at-birth twist)** — *revise* — the sentence claimed a SALVAGE-graded unit is moved to accounting state `EXPENSED` unconditionally; impl only does so for `OWNED_INVENTORY` and leaves a `CONSIGNED` unit at `UNCAPITALIZED`. Added the ownership qualifier. — `implementation/r_tradein.py:255-257`

## Per-edit pre-edit search log
**Edit 1 — §3.4 salvage-at-birth accounting state**
- (a) **Subject:** a resale unit's `accounting_state` at/after creation, and the `OWNED_INVENTORY` vs `CONSIGNED` gate on every accounting-dimension transition.
- (b) **Impl paths enumerated** (`grep -n "accounting_state\|ownership_treatment" *.py`, then read each): `r_tradein.py:243-264` (creation + salvage-at-birth, the Step 7 site); `r_refurb.py:237-241` (QC pass → `CAPITALIZED` + `capitalized_cost_minor`, gated on `OWNED_INVENTORY`); `r_refurb.py:247-255` (QC salvage → `EXPENSED`, same gate); `r_orders.py:249-252` (warranty replacement, defective unit → `EXPENSED`, same gate); `services.py:406-407` (markdown floor → `WRITTEN_DOWN`, gated on `CAPITALIZED`, hence unreachable for consigned stock); `services.py:117` (`capitalized_cost` returns 0 for non-`OWNED_INVENTORY`); `r_market.py:35,59-60` (`accounting_state` list filter, read-only); `store.py:109-129` (row creation/`touch`). Every write path is gated on `OWNED_INVENTORY`, so a `CONSIGNED` unit is `UNCAPITALIZED` for its whole life in the impl — matching PRD §3.5's existing "never capitalizes anything and stays `UNCAPITALIZED` for its entire life" and §3.5's salvage-QC wording. §3.4 was the only spot missing the qualifier.
- (c) **Wording adjustment:** phrased the qualifier to mirror §3.5's existing salvage-QC clause and justified it by the general consigned rule rather than by a narrow salvage-only carve-out, so it does not accidentally imply the gate is unique to this branch. Left `capitalized_cost_minor` at 0 untouched (already stated in the preceding sentence and true on both branches).

## Why the other three `<step_7_diff>` items warranted no edit
1. **`expected_resale_unit_version` not in the refurb-order response** — pure test-artifact bug. §2.8 names the field as a *required request-body input*, and §3.5's enumeration of a newly scheduled order (`rework_count`, `logged_cost_minor`, `viability_ratio_bp`, `performed_by_user_id`, `qc_by_user_id`, `viability_override_reason`, plus §2.6's `id`/`created_at`/`updated_at`/`version`) is exactly the field set `r_refurb.py:67-82` + `store.create` produce. The impl is uniquely determined by the PRD as written; nothing to pin.
2. **QC override-authority probe pre-empted by segregation of duties** — PRD §2.11 already pins the order normatively (gate 9 `ERR_SEGREGATION_OF_DUTIES` before gate 18 `ERR_OVERRIDE_ROLE_REQUIRED`), and `r_refurb.py:210-231` follows it exactly (state 208 → SoD 210 → grade policy 214 → viability 228 → override 230). Test fixture chose a colliding signer identity; no PRD gap.
3. **Waterfall test asserting `INTAKE` for a SALVAGE unit** — the lifecycle half of this was already unambiguous in §3.4 and `r_tradein.py:254` matches it. Only the *accounting* half of that same sentence diverged, which is the single edit above.
4. **`ERR_GRADE_POLICY_MISSING` on grading at grade `C`** — PRD §3.3 already states grading is refused without an `ACTIVE` policy for the (`product_category`, `assessed_grade`) pair, and `r_tradein.py:153-154` does exactly that. The test simply failed to seed the `C` policy.

One adjacent silence I deliberately did **not** patch (out of Step 8's scope, left for Step 9): at `r_tradein.py:153-155` the grade-policy gate and the `assessed_grade` write only run when `assessed_grade` is present in the request, so an omitted grade skips the check and preserves the prior grade rather than overwriting it to null — which reads against §3.3's "writes ... `assessed_grade` from the request" and "overwrites `assessed_grade`". That path was never exercised by the Step 7 fix (the test supplied a grade), so it does not trace to a `<step_7_diff>` item.

**Orchestrator note:** verified PRD_FINALIZED.md is NOT byte-identical to PRD.md (one revised §3.4 sentence, 100822 vs 100671 bytes) and that PRD.md itself was left untouched. Step 9 will therefore start from PRD_FINALIZED.md, and has been handed the `assessed_grade`-omitted silence above as an explicit lead.

## Step 9: Complete PRD — 2026-09-05T15:55:23.000Z

Run as **three sequential, module-partitioned passes over one shared `PRD_COMPLETED.md`** (pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from repeating it and edited in place). Partition: pass 1 = platform/envelope/validation/storage/config (`app.py`, `envelope.py`, `validators.py`, `errors.py`, `constants.py`, `access.py`, `serialize.py`, `store.py`, `r_config.py`); pass 2 = intake→grading→disposition→refurb→credit/expiry (`r_tradein.py`, `r_refurb.py`, `r_credit.py` + their `services.py` halves); pass 3 = listing→markdown→purchase→after-sale→reporting (`r_market.py`, `r_orders.py`, `r_reports.py` + their `services.py` halves). Each pass handed its out-of-partition findings forward as explicit leads rather than patching them.

### Cumulative result
`PRD_FINALIZED.md` 468 lines / 100,822 chars → `PRD_COMPLETED.md` 474 lines / 125,477 chars (**+24,655 chars, +6 lines, 70 diff hunks**). 81 edits total: pass 1 = 26 (19 ambiguity-pins, 7 mismatch-revisions), pass 2 = 27 (19 pins, 8 revisions), pass 3 = 28 (22 pins, 6 revisions). Every edit was an in-paragraph insert/revision — no new sections, no new paragraphs; §4 still 54 endpoint rows, §5 still 63 error rows.

### Pass 1 — platform, envelope, validation, storage, configuration (26 edits)
- §2.1 — insert — ambiguity — role names matched exactly/case-sensitively; an absent/empty/whitespace `X-User-Role` is `ERR_ROLE_NOT_PERMITTED` (403), not 401; `X-User-ID` blankness-tested after trimming but recorded verbatim — `validators.py:16-23`
- §2.1 — insert — ambiguity — ownership on `Customer` compares the row's own `id`; a resale unit has no customer field, so its owner is the `customer_id` of the trade-in at its `trade_in_id` (unresolvable trade-in ⇒ owned by nobody) — `access.py:7-18`, `r_config.py:62`, `r_market.py:24`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case alphanumerics — `envelope.py:14-15`
- §2.2 — revise — mismatch — `api_request_timestamp` is the one value read from real time, so it disagrees with the `created_at` of a row written by the same request — `envelope.py:21`
- §2.2 — revise — ambiguity — pagination `meta` keys are absent from single-object responses — `envelope.py:26`
- §2.2 — revise — mismatch — the error envelope also covers the 5xx of an internal failure, not only 4xx — `app.py:55-57`
- §2.3 — insert — ambiguity — `limit`/`offset` out of range or non-integer ⇒ `ERR_INVALID_REQUEST` (422), never clamped; `offset` unbounded; `?param=` counts as absent — `validators.py:114-140`
- §2.3 — insert — ambiguity — query params validated at the §2.11 body-shape step; enum filter outside its set ⇒ 422; identifier-valued filter existence-checked ⇒ per-entity 404, resolved *before* Customer narrowing — `validators.py:143-159`, `r_tradein.py:103-107`, `r_credit.py:39-45`, `r_orders.py:108-114`, `r_market.py:40-46`, `r_refurb.py:103-106`, `r_reports.py:66-67`
- §2.3 — insert — ambiguity — `created_at` ties (common, since the clock is parked) break by ascending insertion order; filter → sort → slice — `store.py:136-141`, `envelope.py:49-52`
- §2.3 — insert — ambiguity — `has_more` = `offset + len(page) < total_count`; `total_count` is the pre-page filtered size — `envelope.py:35`
- §2.4 — revise — mismatch — "Nothing reads the host's wall clock" was falsified by the envelope timestamp; narrowed and excepted, and `created_at`/`updated_at` pinned to the logical clock — `envelope.py:21`, `store.py:113-118`
- §2.4 — insert — ambiguity — clock setter still validates its body: `current_utc` required, 422 on omission/unparseable, HTTP 200, `data` carries `current_utc` alone — `r_config.py:294-299`
- §2.4 — revise — ambiguity — output instants are exactly `…mmmZ`; input accepts non-UTC offsets (converted), zoneless values (read as UTC), date-only (midnight UTC), any fractional width, lower-case `t`/`z` and a space separator — `store.py:61-99`
- §2.6 — revise — ambiguity — `created_at` from the logical clock; internal bookkeeping keys never exposed — `store.py:116`, `serialize.py:22-26`
- §2.6 — insert — ambiguity — `aged_days` is not stored: derived at serialization time, rises with the clock, and reading never bumps `updated_at`/`version` — `serialize.py:9-28`
- §2.10 — insert — ambiguity — a `Customer` supplying no customer filter is silently narrowed, not rejected — `access.py:25-35`, `r_market.py:49-50`
- §2.11 step 3 — insert — ambiguity — explicit `null` ≡ omitted; whitespace-only fails non-empty; booleans and fractional numbers (`100.0`) rejected as integers; absent/unparseable body read as `{}` and `Content-Type` uninspected; non-object JSON rejected outright; uniqueness violations carry `ERR_INVALID_REQUEST` (422) for customer `email`, store `code`, channel `code`, bay `code`-within-store — `validators.py:27-108,162-171`
- §2.11 step 5 — insert — ambiguity — identifiers are never UUID-shape-checked, so an impossible id surfaces as its entity's 404, not a 422 — `validators.py:100-108`
- §3.1 — revise — ambiguity — customer amendment: both fields optional, and an amendment naming neither still bumps `updated_at`/`version` — `r_config.py:43-55`
- §3.1 — revise — ambiguity/mismatch — store amendment accepts `status` only, and it is required; `code`/`region_code` immutable — `r_config.py:163-171`
- §3.1 — revise — ambiguity — bay amendment: `status` only and required, reversible both ways — `r_config.py:218-226`
- §3.1 — revise — mismatch — channel amendment accepts `status` only and required; `channel_type`, `allowed_assortment`, `max_resale_price_ratio_bp`, `region_code`, `code` fixed at registration — `r_config.py:258-266`
- §3.1 — insert — ambiguity — a brand-currency policy's `code` need not be unique (unlike store/channel) — `r_config.py:113`
- §4 intro — insert — ambiguity — trailing slash insignificant; clock setter returns 200 — `app.py:28`
- §4 table ×3 — revise — mismatch — PATCH descriptions promised "or capacity", "or capability", "assortment or economics"; all three accept `status` alone — `r_config.py:163,218,258`
- §5 preamble — insert — mismatch — the table claimed to be exhaustive; added the three framework-level identifiers outside it: `ERR_NOT_FOUND` (404, unknown path — never a per-entity code), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — `app.py:38-57`, `errors.py:73-75`

Pass 1 also verified `errors.py` against §5 programmatically (all 63 ids and statuses match exactly; the only extras are those three fallbacks) and confirmed every constant and enum tuple in `constants.py` (13 scalars/tables, 27 enums, `ASSORTMENT_ADMITS`) is already stated with its exact value and member set — no edits needed there.

### Pass 2 — intake → grading/appeal → disposition → refurbishment → credit/expiry (27 edits)
- §3.2 — insert — ambiguity — `store_location_id`/`channel` dependency is `ERR_INVALID_REQUEST` at the body-shape step, ahead of FK resolution; `Customer` may only submit for themselves — `r_tradein.py:28-44`
- §3.2 — insert — ambiguity — `received_at`, `accepted_at`, `reject_reason` all start null — `r_tradein.py:79-82`
- §3.3 — insert — ambiguity — `PENDING` is not an accepted `authenticity_result` input — `r_tradein.py:144`, `constants.py:52`
- §3.3 — insert — ambiguity — the grade-policy gate runs only when `assessed_grade` is supplied — `r_tradein.py:153-154`
- §3.3 — revise — mismatch — grading writes `assessed_grade` only when supplied; omission preserves the prior grade — `r_tradein.py:153-155`
- §3.3 — insert — ambiguity — `appeal_reason` is required, may be blank, is not persisted — `r_tradein.py:167`
- §3.3 — revise — mismatch — re-grade "overwrites `assessed_grade`" is conditional; no `appeal_count` reset — `r_tradein.py:153-159`
- §3.4 — insert — ambiguity — per-branch reading of the two optional fields, `reject_reason` null default, response is the trade-in only — `r_tradein.py:185-202,268`
- §3.4 — insert — ambiguity — a trade-in with a null `assessed_grade` cannot be accepted (`ERR_GRADE_POLICY_MISSING`) — `r_tradein.py:207-209`, `store.py:161`
- §3.4 — insert — ambiguity — customer row touched once for both derived quantities; version +1 total — `r_tradein.py:267`, `services.py:200-208`
- §3.4 — insert — ambiguity — a `SALVAGE` unit is *created* in those states, so `version` is 1 and `updated_at` == `created_at` — `r_tradein.py:243-264`
- §3.5 — insert — ambiguity — the bay-store check is vacuous for a `MAIL_IN` unit — `r_refurb.py:44-47`
- §3.5 — insert — ambiguity — conflict detection already excludes the orders this create will supersede — `r_refurb.py:49-65`
- §3.5 — insert — ambiguity — the start-leg rework guard names `ERR_REWORK_LIMIT_EXCEEDED` and can never fire — `r_refurb.py:168-169`
- §2.11 (17) — revise — mismatch — rework code also sits nominally on the start leg — `r_refurb.py:168`
- §3.5 — insert — ambiguity — task-line create returns the line; list order is ascending `sequence_no`, coincident with §2.3 — `r_refurb.py:146,149-159`
- §3.5 — insert — ambiguity — a missing `ACTIVE` grade policy yields ratio 10001, never an error, on both re-materialization sites — `services.py:96-101`
- §3.5 — revise — mismatch — "an order that logged nothing submits with both at zero" is false at a zero baseline (10001) — `services.py:96-101`, `r_refurb.py:193`
- §3.5 — insert — ambiguity — grade policy resolved before branching, so `FAIL`/`SALVAGE` can also 409; blank override reason counts as supplied — `r_refurb.py:204-216`
- §3.5 — revise — mismatch — `MerchandisingManager` gets `ERR_ROLE_NOT_PERMITTED` (not `ERR_OVERRIDE_ROLE_REQUIRED`); the role gate fires even on a viable order — `r_refurb.py:201,230-231`
- §3.5 — insert — ambiguity — `SALVAGE` accepts, gates and persists `viability_override_reason` with no viability gate — `r_refurb.py:245-250`
- §3.9 — insert — ambiguity — balance recomputed once per *distinct* customer — `services.py:347-350`
- §3.9 — insert — ambiguity — `affected_customer_count` counts distinct customers; `data` carries the three figures alone — `services.py:351-355`, `r_credit.py:20`
- §2.9 — revise — mismatch — a grant issued for zero (legal, `base_credit_pct_bp` 0) yields `ISSUE`/`EXPIRE` entries with `amount_minor` 0 — `services.py:64,343`, `r_tradein.py:238`
- §2.8 — insert — ambiguity — an expected-version input must be a non-negative integer; negative is 422, not 412 — `r_refurb.py:30`, `validators.py:73`
- §4 table — revise — mismatch — submit-qc "test viability" → re-cost and recompute (it applies no gate) — `r_refurb.py:187-196`
- §4 table — revise — mismatch — qc-decision "Pass, rework or fail" → "Pass, fail or salvage" — `constants.py:85`

Pass 2 rejected two of its five handed-down leads as not real: `rematerialize_order`'s unit-None → `viability_ratio_bp` 0 is unreachable (validated FK plus §2.12's no-deletion invariant), and `capitalized_cost`'s first-match iteration order is already uniquely determined by §3.5's "exactly one grant per accepted trade-in".

### Pass 3 — listing → markdown → purchase → after-sale → reporting (28 edits)
- §2.12 — revise — mismatch — tracked-mass per-customer identity now carries the warranty-replacement exception: the *buying* customer's row is recomputed, not the surrendering participant's, so the participant's stored figure lags until an event of their own — `r_orders.py:259` vs `r_refurb.py:256-257`
- §2.12 — revise — mismatch — compensating-pair sentence scoped to "the buying customer's diverted total … whenever that buyer is also the participant who surrendered it" — `r_orders.py:259`
- §2.12 — revise — mismatch — brand-currency compensating pair no longer claims the grant returns "byte-identical to its value before the order was ever placed"; reframed as a statement about the equalities, with the swept-vs-lapsed split spelled out — `services.py:287-324`
- §3.6 — insert — ambiguity — `aged_days` clamped to 0, never negative, when the clock sits at or before `listed_at` — `services.py:483-489`
- §3.6 — insert — ambiguity — campaign capacity boundary: the count is over campaigns that already exist, so the third overlapping declaration is refused and the second is admitted — `r_market.py:131`
- §3.6 — insert — ambiguity — eligible-unit ordering tie-break falls through `listed_at` → `created_at` → insertion order — `services.py:384`
- §3.6 — insert — ambiguity — a markdown step can *raise* `current_price_minor` (no clamp against the current price) and then contributes a negative amount to `total_markdown_minor` — `services.py:387-411`
- §3.6 — insert — ambiguity — resale-unit filter resolution order (`trade_in_id` → `replacement_for_unit_id` → `listed_channel_id`) and the fact that only `trade_in_id` is ownership-scoped — `r_market.py:40-50`
- §3.6 — insert — ambiguity — the cadence run consults the clock "and nothing else": the campaign's channel is not re-checked for `ACTIVE`, so a channel paused after declaration does not stop the cadence — `r_market.py:158-184`
- §3.7 — insert — ambiguity — body FK resolution order (customer, channel, unit) ahead of the state gates — `r_orders.py:27-29`
- §3.7 — revise — ambiguity — `ERR_CREDIT_NOT_REDEEMABLE_HERE` narrowed to its actual trigger: only when `requested_credit_minor > 0`, live unexpired grants exist, *and* none is channel-eligible — `r_orders.py:51-54`
- §3.7 — insert — ambiguity — redemption-waterfall tie-break `(expires_at, created_at, _seq)` including insertion order — `services.py` eligible_grants
- §3.7 — insert — ambiguity — the buyer's row is recomputed unconditionally on placement, even for a zero-credit order — `r_orders.py:88`
- §3.7 — insert — ambiguity — fulfilment: a non-`RESERVED` unit yields the same `ERR_ORDER_NOT_FULFILLABLE`; the grade policy is resolved afresh at fulfilment; an absent policy yields a zero-day warranty rather than `ERR_GRADE_POLICY_MISSING`; a zero-day warranty still admits a same-instant claim — `r_orders.py:152-160`
- §3.7 — revise — ambiguity — corrective softening of its own false universal: "one of the platform's two condition-tier reads that tolerate an absent row, the viability re-materialization of §3.5 being the other" — `r_orders.py:156-157`
- §3.8 — insert — ambiguity — `NONE` is rejected as a `reason_type` *input* even though it is the resting value — `r_orders.py:171`, `constants.py`
- §3.8 — insert — ambiguity — return settlement is not ownership-scoped, and the policy reads are branch-specific (only `REFUND` reads a grade policy; no branch reads a credit policy) — `r_orders.py:196,216-219`
- §3.8 — insert — ambiguity — a refunded unit retains `listed_at` and `markdown_step_count`, so `aged_days` keeps accruing across the return — `r_orders.py:228-230`
- §3.8 — insert — ambiguity — release walk descends by `(occurred_at, created_at, _seq)`, insertion order included — `services.py:287-295`
- §3.8 — revise — mismatch — released grant status is set from fill level alone (`ISSUED` if refilled to issue, else `PARTIALLY_REDEEMED`), not from its prior status; and each release is capped at that grant's headroom — `services.py:299-312`
- §3.8 — insert — ambiguity — third link: an already-lapsed grant gets `version` +2, the offsetting `EXPIRE` entry carries a null `resale_order_id`, and the whole `remaining_minor` is zeroed — `services.py:314-324`
- §3.8 — insert — ambiguity — fourth link: the balance recompute runs even at `refund_credit_minor == 0`, and the swept-vs-lapsed outcome differs — `r_orders.py:238`
- §3.8 — insert — ambiguity — replacement-ranking tie-break `(current_price_minor, listed_at or created_at, created_at, _seq)` — `services.py:433-440`
- §3.8 — revise — mismatch — a `CONSIGNED` defective unit stays `UNCAPITALIZED` on replacement; only `OWNED_INVENTORY` is driven to `EXPENSED` — `r_orders.py:251-252`
- §3.8 — insert — ambiguity — the substitute retains its `listed_channel_id`, price fields and `listed_at`, and the order's `resale_unit_id` is never repointed at it — `r_orders.py:255-257`
- §3.8 — revise — mismatch — `diverted_grams_total` on replacement is recomputed for the buyer, not the participant who surrendered the defective unit — `r_orders.py:259`
- §3.9 — insert — ambiguity — the named predecessor is resolved for existence alone; its `status` is never inspected at generation, so a `DRAFT` or already-`SUPERSEDED` report may be named — `r_reports.py:29-30`
- §3.9 — insert — ambiguity — window shape is judged before the predecessor is resolved, so 422 beats 404 — `r_reports.py:23-30`
- §3.9 — insert — ambiguity — publishing over an already-`SUPERSEDED` predecessor leaves it completely untouched (`version` unmoved) and still succeeds — `r_reports.py:88-92`

Pass 3 rejected four of its handed-down leads as already-pinned (`ERR_UNIT_NOT_LISTED`'s compound gate, `REPLACE` requiring `WARRANTY_DEFECT`, `DENY`'s field resets, the channel-fee bands and their upper-inclusive boundaries, and `whole_days_apart`'s integral-day requirement).

### Residual silence consciously left unpinned (pass 3's closing statement)
1. §3.6's narrative ordering of the assortment gate vs the grade-policy read — the impl checks the grade policy first (`r_market.py:79-83`), the opposite of §3.6's reading order, but §2.11 steps 13/14 are the normative tie-breaker and already match the impl; restating it locally risked contradicting §2.11.
2. The cadence-run endpoint ignoring any request body — harmless; it declares no required fields, and §2.11's unknown-key tolerance is already uniform.
3. §2.7's loose collective claim that both policy-missing codes guard "resale-order placement" and "return settlement" — the impl raises neither there. Rather than narrowing another partition's §2.7, pass 3 pinned the exact truth at the §3.7 and §3.8 sites, leaving §2.7 merely loose rather than contradictory.

Pass 3 also self-caught and corrected one NO-NEW-MISMATCH violation before exiting: a fulfilment edit initially asserted "the one condition-tier read in the platform that tolerates an absent row", contradicting pass 2's committed §3.5 statement about viability re-materialization; it was revised in place to "one of the platform's two…".

### Orchestrator verification
- `PRD_COMPLETED.md` exists at 474 lines / 125,477 chars and is **not** byte-identical to `PRD_FINALIZED.md` (70 diff hunks) — the scan genuinely ran in all three passes.
- All five top-level sections intact and in order; the file ends on the final complete row of the §5 error table; §4 has 54 endpoint rows and §5 has 63 error rows.
- No difficulty-directive or scaffold reference leaked into `PRD_COMPLETED.md`.
- Re-read all 8 `results.$i.json`: still 100/100 in every round — Step 9 touched no code, as required.
- Housekeeping: removed the pytest `__pycache__` dirs and the transient sweep logs (`sweep.log`, `sweep.round*.log`, `sweep.done`); kept `workspace/sweep.sh` and the 8 `results.$i.json`.

**Pipeline complete.** All nine steps finished; final artifact `workspace/PRD_COMPLETED.md` is in place.

## Step 9 addendum: cross-partition cleanup of the policy-availability overclaim — 2026-09-05T16:09:43.000Z

Pass 3 ended by reporting a §2.7 mismatch that sat inside pass 1's partition and that it had correctly declined to edit. Rather than leave it in a summary or patch it myself, I resumed the still-live pass 1 agent (its context intact) with two section-scoped cleanup briefs. Both were single targeted `Edit` calls; the second closed out a duplicate of the same overclaim that pass 1 spotted at §2.11 step 13.

**Root cause (one defect, two sites):** both `ERR_GRADE_POLICY_MISSING` and `ERR_CREDIT_POLICY_MISSING` originate from exactly one helper each — `services.grade_policy_or_error` (`services.py:41`) and `services.credit_policy_or_error` (`services.py:48`) — so their guarded operations are precisely their call sites, and the PRD's shared six-operation list was an overclaim in both directions. Actual sites: grade code at 6 (trade-in submission; the authentication leg **only when `assessed_grade` is supplied**; the **accept** branch of disposition; unit listing; every QC decision; the **REFUND** branch of return settlement), credit code at 3 (trade-in submission; the accept branch of disposition; resale-order placement). Never raised at resale-order placement (grade) or at any branch of return settlement (credit), and never at fulfilment, which falls back to a zero-day warranty.

- §2.7 — revise — mismatch — replaced the single collective sentence with the two disjoint enumerations; 125,477 → 126,190 chars, no line change, §2.7 still spans 121–126.
- §2.11 step 13 — revise — mismatch — same narrowing at the normative ladder rung, adding the previously-omitted authentication leg, keeping it proportionate (names the operations, cross-references §2.7 and the workflow sections for per-branch conditions rather than duplicating them), plus explicit negatives for fulfilment, task-line append, QC submission, and replacement/denial settlement; 126,190 → 126,834 chars, all 21 ladder steps intact and in order.

**Closed-out check:** pass 1 grepped both error ids across the whole file and enumerated all 13 remaining occurrences (§2.7, §2.11, §3.2, §3.3, §3.4, §3.5 ×2, §3.6, §3.7 ×2, §3.8, §5 ×2), confirming each is site-local and correct and that no other passage makes a collective or unqualified claim about either code. The two loose spots were the only ones and are now mutually consistent.

**Final orchestrator verification of the delivered artifact:**
- `workspace/PRD_COMPLETED.md` — 474 lines / 126,834 chars; +26,012 chars over `PRD_FINALIZED.md` across 83 edits (26 + 27 + 28 + 2 addendum). Not byte-identical to `PRD_FINALIZED.md`.
- Structure invariants hold: 5 `##` sections in order, §4 endpoint table 54 rows, §5 error table 63 rows, file ends on the last complete error row.
- No difficulty-directive or scaffold leak anywhere in `PRD.md`, `PRD_FINALIZED.md`, or `PRD_COMPLETED.md`.
- `find workspace/implementation -name '*.py' -newermt "2026-09-05 14:36"` is empty — no implementation file changed after the final green sweep, so the 8 `results.$i.json` (100/100 each) remain valid evidence for exactly the delivered code.

**Pipeline complete.** Steps 1–9 all finished; `workspace/PRD_COMPLETED.md` is the final artifact.
