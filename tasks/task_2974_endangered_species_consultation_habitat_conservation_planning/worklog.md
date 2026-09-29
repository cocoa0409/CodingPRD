# Worklog — task_2974_endangered_species_consultation_habitat_conservation_planning

## Step 1: Create task directory — 2026-09-06T00:05:24.915Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2974_endangered_species_consultation_habitat_conservation_planning` and its `workspace/` subdirectory. Index 2974 was pre-assigned by the orchestrator invocation (no scan of ./tasks/ performed, per instruction — concurrent pipelines on this host make auto-allocation collide).

## Step 2: Generate scaffold — 2026-09-06T02:00:30.000Z

All three scaffold artifacts are complete and lint-clean.

## Deliverables (`/home/ubuntu/github/CodingPRD/tasks/task_2974_endangered_species_consultation_habitat_conservation_planning/`)

| file | lines | top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 3049 | §1.0–§1.7 only (no `scaffold_difficulty_design`, no `scaffold_corner_design`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2864 | `scaffold_difficulty_design` (24 instances) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 8747 | `scaffold_corner_design` (113 instances) |

All three `yaml.safe_load` cleanly. Scratch dir `.scratch/` and the build file `SCAFFOLD_CORNER_DESIGN_NEW.yaml` are deleted; `worklog.md` and `workspace/` untouched.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    43
  §1.1 entities declared:     13
  §1.8 instances scanned:     24
  §1.9 instances scanned:     84
  Calls scanned (§1.8+§1.9):  1773

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Scaffold surface

13 entities (Species, CriticalHabitatUnit, ConservationBank, Proponent, ProjectAction, PresenceDetermination, Consultation, BiologicalOpinion, HabitatConservationPlan, MitigationCommitment, IncidentalTakePermit, MonitoringReport, ChangedCircumstanceEvent), flat topology at `api_prefix: "/"`, 43 endpoints, 8 state machines, 13 calculations, 29 validations + 4 declared priority conflicts, 38 error ids, 2 optimistic-concurrency rules, 4 roles (`Proponent` entity-backed; `WildlifeAgency`/`Auditor`/`Anonymous` opaque) under `role_model: segregation_of_duties`, `consistency_model: eventual` scoped to exactly `Proponent.compliance_standing_score` + `compliance_variant_applied`. Pagination only on `GET /project-actions` and `GET /presence-determinations`; all sub-resource lists unpaginated with a null pagination block.

Domain flow modelled: presence determination (database vs. field survey, seasonal windows, CHU overlap) → effect determination (three-input ladder → NLAA/informal vs. LAA/formal, tolled statutory deadlines) → BA/BO with incidental take statement and reinitiation trigger → HCP with mitigation commitments (bank credit / in-lieu fee / permittee-responsible), endowment + changed-circumstance reserve funding waterfall → agency decision → ITP with implementing agreement → monitoring reports, take ledger, adjudication, changed/unforeseen circumstances and assurances, take-exceedance reinitiation.

## §1.9 breadth-walk coverage

All nine claim-extraction-guide sections present: entities 22, state_machines 18, calculations 26, validations 24, endpoints 6, errors 2, rbac 6, cross_cutting_complexity_layers 9, consistency_model 1 — **83 full `test_recipe` probes + 30 `excluded_because` stubs**. Every stub cites one of the 24 §1.8 instances by name (verified programmatically: no bad citations, no stub carries a `test_recipe`, no name collides across the two design files).

Sections finished this session: `cross_cutting_complexity_layers` (both OCC rules — plan-version staleness caused by an unrelated funding write, and permit-version staleness caused by *someone else's* report rejection; an all-or-nothing refused-cascade probe; and the cumulative take threshold re-arming to `suspension_count == 2` while `reinitiation_count` stays 1 because the asymmetric unwind leaves the action/consultation latched) plus `consistency_model` (score changes 89.00 → 89.00 → 94.50 across a 180/181-day decay boundary with zero intervening writes, identical when read by the write-less Auditor, while every plan/bank aggregate is byte-stable; then a `ROLLING_12_MONTH → LIFETIME` flip with the score unchanged).

Coverage notes recorded in-file: all 38 error ids are triggerable from at least one instance (audit table lives in the errors section); the guide's *bulk action* pattern has no instance because §1.5 declares no bulk endpoint; two `validations[priority=22]` applies_to clauses are unreachable by construction (documented in the `no_presence_determination_rule` stub rather than patched).

## SCAFFOLD.yaml self-consistency edits

Seven total, all made because a §1.8/§1.9 claim would otherwise have been unfoundable or self-contradictory. Four this session: (1) the instant-precision rule now accepts whole seconds *or* three fractional digits, which every `T00:00:00Z` clock call depends on; (2) priority 7 now bounds `limit`/`offset` (out-of-range rejected, never clamped); (3) `instrument_type` now has a declared four-value enum; (4) priority 5 now binds the body `proponent_id` on `POST /project-actions` to `X-User-ID` while letting an unresolvable id fall through to a 404 `ERR_PROPONENT_NOT_FOUND` (needed so it does not contradict the already-written flat-FK entities instance).

### Orchestrator note (post-Step-2 sanitation)

The scaffold generator reproduced the difficulty directive "Generate task harder than expert level!" verbatim inside `SCAFFOLD.yaml`'s `scenario:` block (and flagged it in a header comment asking the orchestrator to strip it). Since `SCAFFOLD.yaml` is the doc generator's only input, that line would have leaked into PRD.md. The orchestrator removed the header note lines and the directive line + its blank line from `scenario:`, re-verified `yaml.safe_load` parses, and confirmed `grep -rn "harder than expert"` over the whole task dir now returns nothing. `SCAFFOLD.yaml` is now 3043 lines.

## Step 3: Copy shared files — 2026-09-06T02:01:30.532Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T02:15:00.000Z

**Step 4 complete — `workspace/PRD.md` generated (403 lines, 27 headings).**

**Sections emitted (24 §-headings, in order):**
- `## 1. Introduction` — 3 paragraphs of pain-point/business framing, no bullet lists.
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Callers, Roles and Identity · 2.2 API Response Structure (fixed block copied verbatim, confirmed byte-identical) · 2.3 Pagination and Collection Ordering · 2.4 Resource Identity, Timestamps and Version Counters · 2.5 The Logical Regulatory Clock · 2.6 Path Resolution and Referential Integrity · 2.7 The Validation Ladder · 2.8 Quantities, Money and Rounding Discipline · 2.9 Optimistic Concurrency Control · 2.10 Cascade Discipline, Ledger Invariants and Read-Time Derivation.
- `## 3. Business Logic & Workflows` — 9 narrative subsections: species register/critical habitat/uplisting · proponents and compliance standing · action screening and presence · effect determination and the three-way fork · consultation review, tolling, concurrence, biological opinion · HCP mitigation requirements, banks, commitments · costing, endowment, agency decision · permit issuance, take monitoring, reinitiation · changed/unforeseen circumstances, assurances, plan closure.
- `## 4. Endpoint Definitions` — lead paragraph on status-code conventions + 4-column table (Method | Path | Description | Authorized Role(s)).
- `## 5. Error Code Catalogue` — 2-column table (Error ID | HTTP Status Code), ordered by status.

**Coverage:** 13/13 entities · 43/43 endpoints (table rows machine-diffed against the scaffold: 0 missing, 0 role-list mismatches) · 8/8 state machines with all 45 transitions · 13/13 calculations (including both PRELIMINARY/FINAL mitigation variants, both ROLLING_12_MONTH/LIFETIME score variants, and both interval-conflict branches) · 29/29 validations with the explicit priority ladder and all 4 declared priority-conflict pairs · 38/38 error ids (each row's HTTP status machine-verified against the scaffold) · 4/4 roles.

**Hard Contract reports:**
- **Contract 1 (Field-Name Coverage): PASS** — entity fields 136 required / 136 present / 0 missing; endpoint body inputs 63 / 63 / 0 missing; query params 11 / 11 / 0 missing. All 38 error ids, all state-machine state values, and all enum field values also present as backticked tokens.
- **Contract 2 (Rule Coverage): PASS** — 2 concurrency rules (`expected_hcp_version` → `ERR_STALE_HCP_VERSION`, `expected_permit_version` → `ERR_STALE_PERMIT_VERSION`, both 412); all 45 transitions covered (6 expressed as prose rather than literal arrow pairs — the ProjectAction reinitiation hops and the three ChangedCircumstanceEvent exits from `REPORTED` — each individually re-verified in situ); all 13 calculations with normative rounding order stated as specification (per-row-then-sum for FINAL mitigation and the endowment base; ILF tier selected once from `base_fee_cents` and never re-selected; funding status decided on exact integer cents); all `side_effects` and `applies_to` scopes; sibling-branch symmetry across the 3-way effect fork, 2 circumstance types, 2 decision branches, 2 adjudication branches and 3 cost mechanisms.
- **Contract 3 (§3 Path Purity): PASS** — 846 backtick tokens scanned inside §3; 0 begin with `/`, 0 are bare HTTP-method tokens, 0 are method+path pairs. The only paths in the document are §2.9's OCC illustration and the §4 table.

**Tail confirmed a real section boundary:** the file ends on the last completed row of the §5 table, `| \`ERR_RESERVE_CONTRIBUTION_INSUFFICIENT\` | 422 |` — no mid-sentence or mid-table truncation and no audit footer. Built via 12 sequential heredoc appends to stay under the output cap. Scratch dir `.scratch/step4/` removed (nothing else under `.scratch/` touched); no file outside the task directory was created or modified, and `worklog.md` was not touched.

One resolution worth flagging to the orchestrator: the scaffold's validation entries name the role header `X-Role`, while the skill mandates the fixed names `X-User-ID` / `X-User-Role`. The PRD uses `X-User-Role` throughout, per the skill's fixed contract.

### Orchestrator note (post-Step-4 truncation check)

Independently verified per the known doc-generator truncation failure mode: `wc` reports 403 lines / 13,099 words / 95,817 bytes; `grep -n '^#'` shows all 27 headings present in order through `## 5. Error Code Catalogue`; §4's table holds 45 pipe-rows (43 endpoints + header + separator); the file's last line is the final complete `ERR_RESERVE_CONTRIBUTION_INSUFFICIENT` table row, i.e. a real section boundary rather than a mid-sentence cut. No regeneration needed. Also re-confirmed no difficulty-directive or scaffold-vocabulary leakage into PRD.md (`grep -in "harder than expert\|scaffold\|test_recipe"` returns nothing).

## Step 6: Generate implementation — 2026-09-06T02:45:00.000Z

Implementation complete and verified.

## Modules emitted (17 Python files, 3,386 lines) — all in `/home/ubuntu/github/CodingPRD/tasks/task_2974_endangered_species_consultation_habitat_conservation_planning/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `util.py` | 223 | Decimal/ROUND_HALF_UP helpers, `q2/q3/q4`, ISO-8601 instant+date parse/format, `add_days`, `add_years_clamped`, `whole_days_between`, UUID/`req_` id minting, trailing-zero-preserving JSON `dumps` |
| `errors.py` | 108 | `ApiError` + HTTP status and default message for all 38 error ids |
| `store.py` | 111 | In-memory dict tables (13), logical clock (default `2026-08-01T00:00:00Z`), `new_row`/`touch`/`ordered`/`where` |
| `envelope.py` | 75 | `meta`/`response_type`/`data` envelope; paginated, null-pagination and error variants |
| `auth.py` | 108 | Ladder rungs 1–3 and 5, ownership resolvers per entity |
| `shape.py` | 252 | Rung 7 body/query validation, unknown-field rejection, pre-resolution field peeking for rungs 5–6 |
| `calc.py` | 512 | All 30+ PRD constants and every derivation |
| `serialize.py` | 268 | 13 field-ordered renderers (opinion is unversioned) |
| `resolve.py` | 69 | Rung 4/6 lookups mapped to the 11 404 codes |
| `cascades.py` | 149 | Uplisting (4 hops), take-exceedance (5 hops), suspension unwind, clock-advance permit expiry (3 hops) |
| `routes_read.py` | 254 | 20 GETs |
| `routes_species.py` | 194 | Registry writes + `/_clock/set_current_utc` |
| `routes_action.py` | 259 | Screening, presence determinations, effect fork, plan creation |
| `routes_consult.py` | 184 | BA/tolling/info-request/concurrence/opinion |
| `routes_plan.py` | 224 | Commitments, funding assurances, submit, decision |
| `routes_permit.py` | 323 | Permit issuance, monitoring reports, adjudication, circumstance events + responses |
| `app.py` | 73 | Blueprint registration, `ApiError`/HTTP/unhandled error handlers, `0.0.0.0:$PORT` |

Plus `start.sh` (11 lines, guarded pip install, `PORT` default 10000, `exec python3 app.py` in the foreground) and `requirements.txt`.

## Coverage

**43 endpoints — 20 GET + 23 POST — an exact match for the PRD's endpoint table (PRD.md lines 316–358), verified by dumping Flask's url_map.**

State machines: ProjectAction (8 states incl. `REINITIATION_PENDING` with reason), Consultation (6 states with tolling and clock restart), HabitatConservationPlan (`plan_status` × `funding_status` as parallel independent dimensions), MitigationCommitment (RESERVED/SECURED/RELEASED), IncidentalTakePermit (ACTIVE/SUSPENDED/EXPIRED), MonitoringReport, ChangedCircumstanceEvent.

Calculations: effect determination with the 0.00/5.00 % overlap thresholds; incidental take and jeopardy fraction (0.0500) with the 0.90 reinitiation trigger; dual-variant mitigation units (PRELIMINARY covered-acres vs FINAL per-row-rounded) and the reconciliation delta; commitment cost across all three mechanisms with the three-tier ILF admin ladder; endowment (30-year capitalisation, mechanism factors 0.60/0.85/1.00, 12 % changed-circumstance reserve); integer-cent funding decision; dual-variant compliance score (ROLLING_12_MONTH vs LIFETIME, 180-day halving decay, floor 0); statutory deadlines (135/60 days with whole-day tolling); `ITP-nnnnnn` numbering; two-bucket CHANGED waterfall vs the 5 %-capped UNFORESEEN allocation.

Validations: the full 29-rung ordered ladder, both optimistic-concurrency guards (412), both segregation-of-duties rules (403), the two deliberately different interval semantics (closed + 3-day-buffered survey windows vs half-open unbuffered reporting periods), and the three ledger invariants (bank credits, permit take, event cost split).

## Verification

`bash -n start.sh` clean; `python3 -m py_compile` clean on all 17 modules; one foreground boot on port 47913 driven by a 26-check end-to-end script that walked proponent → species → habitat unit → action → presence determination → effect determination (LAA) → BA → biological opinion (NO_JEOPARDY, 120.00 authorized / 108.00 trigger) → HCP → bank → commitment → funding assurance → submit (FULLY_ASSURED) → approve → segregation-of-duties rejection (403) → permit `ITP-000001` (2026-08-15 → 2046-08-15) → clock advance → monitoring report (due 2026-12-30, not late) → ACCEPT adjudication (consumed 10.00 / remaining 110.00) → CHANGED circumstance (draw 10,821,600, shortfall 889,178,400, RESPONSE_REQUIRED) → response → compliance re-derivation (100.00, ROLLING_12_MONTH) → both list endpoints → 401 unknown role → 404 `ERR_PROJECT_ACTION_NOT_FOUND`. Result: **SMOKE_OK**, zero tracebacks in the server log. Server killed by its exact port owner PID; `__pycache__` and `.scratch/step6` removed (`.scratch/step5` left intact).

One note for the record: two smoke-script bugs surfaced and were fixed in the script, not the implementation — an invalid `instrument_type` literal (`ENDOWMENT` vs the PRD's `ENDOWMENT_TRANSFER`) and an assertion expecting 409 for `ERR_SEGREGATION_OF_DUTIES` where PRD.md lines 23/276/370 all specify 403.

## Step 5: Generate unit tests — 2026-09-06T04:21:26.000Z

Step 5 complete. Both directories are at the task root; nothing was written under `workspace/`.

## Deliverables

**`/home/ubuntu/github/CodingPRD/tasks/task_2974_endangered_species_consultation_habitat_conservation_planning/test_helpers/`** — 9 files, 2 651 lines
`__init__.py` 48 · `api_client.py` 280 · `api_errors.py` 89 · `assertions.py` 493 · `constants.py` 85 · `factories.py` 245 · `fixtures.py` 899 · `test_users.py` 107 · `types.py` 405

**`.../test_suite/`** — `conftest.py` (51) + 20 test files, 10 434 lines, **200 tests**

| file | lines | tests | queue |
|---|---|---|---|
| test_01_dual_variant_calculations | 151 | 5 | A |
| test_02_combinatorial_formulas | 362 | 10 | A |
| test_03_non_linear_state_machines | 440 | 14 | A |
| test_04_transitive_cascades | 489 | 19 | A |
| test_05_validation_priority_pairs | 491 | 18 | A |
| test_06_boundary_precision | 323 | 12 | A |
| test_07_cross_entity_state_dependency | 285 | 7 | A |
| test_08_resource_temporal_overlap | 347 | 11 | A |
| test_09_compensating_invariants | 346 | 12 | A |
| test_10_corner_entities_registry | 494 | 15 | B |
| test_11_corner_entities_lifecycle | 672 | 11 | B |
| test_12_corner_state_machines | 819 | 14 | B |
| test_13_corner_calculations_presence | 554 | 8 | B |
| test_14_corner_calculations_money | 582 | 8 | B |
| test_15_corner_validations_auth | 549 | 8 | B |
| test_16_corner_validations_business | 863 | 9 | B |
| test_17_corner_endpoints | 710 | 6 | B |
| test_18_corner_errors | 221 | 2 | B |
| test_19_corner_rbac | 633 | 6 | B |
| test_20_corner_cross_cutting | 603 | 5 | B |

## Design-index coverage

- **Queue A (§1.8 difficulty): 24/24 live instances, every one with ≥2 tests.** 0 uncovered, 0 dangling tags.
- **Queue B (§1.9 corner): 84/84 live instances, ≥1 test each** — entities 20, state_machines 12, calculations 16, validations 17, endpoints 6, errors 2, rbac 6, cross_cutting 4, consistency_model 1. 0 uncovered, 0 dangling. The 30 `excluded_because` stubs were correctly not translated.
- Every one of the 200 test docstrings ends in exactly one `Design:` line resolving to a real yaml `name:` (checker: `tests=200 distinct_instances=108 problems=0`).

## Instances / claims skipped or narrowed under the two-condition filter

No whole instance was skipped — all 108 live instances are covered. Five individual recipe claims were dropped or corrected because the PRD does not uniquely derive them:

1. **`errors/every_error_body_carries_only_an_error_id_and_a_message`** — the recipe's "Auditor with no `X-User-ID` → 401" probe was replaced by a `headers_without_role()` probe. PRD §2.1/rung 1 requires `X-User-ID` only for `Proponent` and `WildlifeAgency`, so an auditor read without it must be **200**, and test_15 already asserts that.
2. **`cross_cutting/a_refused_cascade_trigger...`** — the recipe asserts `action_status == 'CONSULTATION_CONCLUDED'` after the refused issuance; PRD line 230 moves the action `CONSULTATION_CONCLUDED → HCP_DEVELOPMENT` on plan creation, so `HCP_DEVELOPMENT` (plus `!= PERMITTED`, which is the claim's substance) is asserted instead.
3. Recurring **201-vs-200 conflicts**: several recipes claim 201 for modify-operations (BA submission, plan submit, plan decision, adjudication, circumstance response). PRD line 312 pins those at 200; the PRD value was used throughout.
4. **Partial skips carried from earlier files**: the 180-day-decay `version`/`updated_at` claim, the `permit_term_years` 1-and-50 pair, and the plan-creation `final_mitigation_units == null` claim — each asserted only as far as the PRD derives it.
5. `ERR_SURVEY_WINDOW_CONFLICT` hazards forced fixture (not assertion) changes: second surveys use non-conflicting windows or omit the CHU, since PRD line 188's 3-day buffer reaches across all actions.

## Verification

- `python3 -m py_compile` clean on all 29 emitted `.py` files.
- `pytest --collect-only`: **200 tests collected**, no import or collection errors.
- C1 quote checker: **441 quoted PRD fragments, 0 misses** (arrows/em dashes normalised to `-`, `**bold**` markers preserved).
- C4 design-tag checker: `problems=0`.
- AST unused-import scan: clean on every test file (also removed one stale `species_payload` import found in test_10).
- Scratch: `rm -rf .scratch/step5` only; the `.scratch` parent and all sibling dirs untouched. `__pycache__`/`.pytest_cache` removed.
- `worklog.md` was not read or modified. `workspace/implementation/` was never read or written; the only workspace read was `workspace/PRD.md`.

### Orchestrator note (post-Step-5 placement check)

Verified `test_helpers/` and `test_suite/` are both at the TASK ROOT (not under `workspace/`, which is the known recurring misplacement); `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`. Independently re-ran `pytest test_suite --collect-only -q`: **200 tests collected, 0 collection errors.** Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator never saw `test_suite/` (the directory did not exist at its spawn time).

## Step 7: Run tests and iterate — 2026-09-06T04:42:16.000Z

Fully green 8-round sweep achieved. Here is the summary for worklog.md.

## Step 7 Summary

**Iterations run: 2**

Iteration 1 produced 196/200 in all 8 rounds, with an identical 4-test failure set in every round (zero flakiness — no load-induced noise, no timeouts, no connection resets). Iteration 2, after the fixes below, produced 200/200 in all 8 rounds.

### Tests deleted
None. No test failed STEP 1a (PRD silence) or STEP 1b (unique derivability) outright.

### Assertions removed under STEP 1c (partial coverage)
- `test_suite/test_09_compensating_invariants.py` — `TestBankCreditIdentityRestoredByReturnForRevision::test_the_plan_aggregates_recompute_over_an_empty_contributing_set`: removed the single line `assert plan["secured_mitigation_units"] == 0.00`. **Category: PRD silence on one field of a multi-field rule.** PRD §3.7's `RETURN_FOR_REVISION` paragraph enumerates exactly which fields recompute — "`endowment_base_cents`, `changed_circumstance_reserve_cents`, and `endowment_required_cents` all recompute to 0 over the now-empty contributing set, `funded_ratio` becomes 0.0000, and `funding_status` becomes `UNFUNDED`" — and `secured_mitigation_units` is not among them. The PRD names that field's recompute sites explicitly and only twice: §3.6 commitment creation and §3.7 plan submission. A faithful PRD-only implementer would therefore leave it at 59.72 on this branch. Every other assertion in the test is verbatim-covered and was kept.

### Fixes applied to `test_helpers/`
None. No fixture, factory, header builder, or assertion helper was at fault.

### Fixes applied to `test_suite/`
- `test_04_transitive_cascades.py` — `TestPermitExpiryCascade::test_an_expired_permit_accepts_no_further_report`: moved the `read_permit(...)["version"]` guard read from *before* the `set_clock("2027-10-02T00:00:00Z")` call to *after* it. The expiry cascade touches the permit, and PRD §2.10 requires a cascade-touched row's `version` to increment, so the pre-expiry token was stale and rung 8 (`ERR_STALE_PERMIT_VERSION`, 412) correctly pre-empted the rung-10 rule the test means to probe. The test now sends a live token and gets the asserted `ERR_PERMIT_NOT_ACTIVE` (409).
- `test_20_corner_cross_cutting.py` — `TestStaleHcpVersion::test_a_funding_assurance_between_the_read_and_the_write_makes_the_token_stale`: changed the funding contribution from `100_000` to `1_894_201` cents. The test asserts `funding_status == "PARTIALLY_ASSURED"`, but against that plan's `endowment_required_cents` of 3,788,402 a 100,000-cent contribution is `UNFUNDED` under PRD §3.7's exact-integer-cent rule ("`PARTIALLY_ASSURED` when twice `endowment_secured_cents` is at least `endowment_required_cents`"). 1,894,201 is exactly half, the inclusive lower bound of the band.
- `test_20_corner_cross_cutting.py` — `TestRefusedCascadeLeavesNothingBehind::test_a_refused_approval_and_a_refused_issuance_move_no_downstream_row`: same defect, same rule. Changed `build_scenario("submitted", funding_cents=100_000)` to `funding_cents=2_513_257` (exactly half of that plan's 5,026,514-cent requirement) and the matching top-up from `4_926_514` to `2_513_257`, preserving the test's later `endowment_secured_cents == 5_026_514` and `FULLY_ASSURED` assertions.

### Fixes applied to `implementation/`
None. No implementation defect was found. All four failures were test-artifact bugs in `test_suite/` — three fixture-value/ordering errors inconsistent with PRD, one assertion on a field the PRD does not govern on that branch.

### Final sweep evidence (per-round passed/total)

| Round | Passed | Total | Failed |
| --- | --- | --- | --- |
| 1 | 200 | 200 | 0 |
| 2 | 200 | 200 | 0 |
| 3 | 200 | 200 | 0 |
| 4 | 200 | 200 | 0 |
| 5 | 200 | 200 | 0 |
| 6 | 200 | 200 | 0 |
| 7 | 200 | 200 | 0 |
| 8 | 200 | 200 | 0 |

Union of non-passing tests across all 8 rounds: empty. `results.{1..8}.json` left in place in `workspace/implementation/`. `SWEEP_DONE`, `round.*.log`, `sweep.log`, and `.scratch/step7/` removed; `worklog.md` untouched.

**Note for Step 8:** the implementation required no changes, so a byte-identical `PRD_FINALIZED.md` would be the legitimate outcome here.

### Orchestrator note (post-Step-7 sweep-artifact verification)

Independently verified rather than trusted: all eight `workspace/implementation/results.{1..8}.json` exist on disk (~69.9 KB each, written 2026-09-06T04:38:44Z), each holding **200 test records with `status: "passed"` for every one and `passed == total == 200`**. Parsed on the `"status"` key (not `"outcome"`) and cross-checked `total - passed == 0` against the per-test union, so the zero-failure reading is not a parser artifact. Step 8 is **not** skipped: Step 7 ran 2 iterations with 3 `test_suite/` fixes plus 1 STEP-1c assertion removal, which is a non-empty diff even though `implementation/` was untouched.

## Step 8: Finalize PRD — 2026-09-06T04:53:04.000Z

Done. One edit, on line 272 only.

## Line counts
- `PRD.md`: 403 lines. `PRD_FINALIZED.md`: 403 lines. **0% line delta**; exactly one line modified (§3.7, line 272). Tail verified intact through the `ERR_RESERVE_CONTRIBUTION_INSUFFICIENT | 422 |` row.

## Changes
- **§3.7 (`RETURN_FOR_REVISION` paragraph) — insert — pins that `secured_mitigation_units` and `endowment_secured_cents` are *not* recomputed on the return-for-revision path, and names the field's three and only write sites (plan creation → 0.00, commitment creation, submission), so the returned plan carries forward its submission-time figure — `implementation/routes_plan.py:205-224` (`_return_for_revision`, which calls only `recompute_endowment` + `recompute_funding`), `implementation/calc.py:347-351` (`recompute_secured_units`).**

No other PRD change. The three remaining Step 7 items are genuine test-artifact bugs against PRD text that already determines the behavior:
- **test_04 permit-expiry version guard** — PRD §2.4 ("`version` … increases by exactly 1 on every mutation … including mutations the row receives as a cascade") and §2.10 ("Each row a cascade touches has its `updated_at` refreshed and its `version` incremented") already pin the increment; `cascades.expire_permits` calls `store.touch(permit)`. §2.7 already pins rung 8 (`ERR_STALE_PERMIT_VERSION`) ahead of rung 10 (`ERR_PERMIT_NOT_ACTIVE`). No silence.
- **test_20 ×2 funding-band fixture values** — PRD §3.7 already states the band verbatim as impl computes it (`FULLY_ASSURED` when secured >= required; else `PARTIALLY_ASSURED` when twice secured >= required; else `UNFUNDED`, with "One cent short of exactly half is `UNFUNDED`"), matching `calc.recompute_funding` (`2 * secured >= required`). No silence.

## Pre-edit search log

**Edit 1 — §3.7 line 272**
- **(a) Subject:** which plan fields are (and are not) recomputed by the `RETURN_FOR_REVISION` branch; the complete write-site set of `secured_mitigation_units`, and of `endowment_secured_cents`.
- **(b) Impl paths enumerated** (grep for `secured_mitigation_units`, `recompute_secured_units`, `recompute_endowment`, `recompute_funding`, `endowment_secured_cents`, `refresh_reserve_remaining`, `reserve_remaining_cents`; then read each site):
  - `routes_action.py:244` — plan creation initialises `secured_mitigation_units` to `q2(0)`.
  - `routes_plan.py:87-89` — commitment creation: endowment + secured-units + funding recompute (§3.6 site).
  - `routes_plan.py:111` — funding assurance: `recompute_funding` only; adds to `endowment_secured_cents`.
  - `routes_plan.py:136` — submission: `recompute_secured_units` (§3.7 site).
  - `routes_plan.py:176` — approval gate *reads* the field (no write).
  - `routes_plan.py:186-201` `_approve` — `refresh_reserve_remaining` only; no secured-units write.
  - `routes_plan.py:205-224` `_return_for_revision` — the Step 7 site: `recompute_endowment` + `recompute_funding`, no secured-units write, no `endowment_secured_cents` write.
  - `routes_permit.py:249-256, 317` — changed-circumstance response: reserve draw + `recompute_funding`; `endowment_secured_cents` grows only via the response contribution; no secured-units write.
  - `cascades.py` — `uplisting_cascade`, `take_exceedance_cascade`, `unwind_suspension`, `expire_permits`: none writes `secured_mitigation_units` or `endowment_secured_cents`; `expire_permits` releases `SECURED` commitments without any plan aggregate recompute (consistent with the new "carried-forward figure stands" wording).
  - `calc.py:324-351` (`recompute_endowment`, `refresh_reserve_remaining`, `recompute_secured_units`), `serialize.py:124,131` (field exposed on the plan representation).
- **(c) Wording adjustments made before committing:** two revisions. First draft said "the recompute on this path covers exactly those fields and no others" — a false universal, since `recompute_endowment` also refreshes `reserve_remaining_cents` (and `plan_status` plus commitment statuses change); dropped the exhaustive claim. Second draft then added an explanatory clause about `reserve_remaining_cents` being refreshed "as it is on every endowment recompute"; removed it too, because §3.7's existing recompute-from-scratch paragraph and §3.6/§3.7-approve already cover that field, Step 7 kept that assertion as verbatim-covered, and `refresh_reserve_remaining` is additionally called from `_approve` and the changed-circumstance path — so the clause was both out of scope and at risk of over-claiming. Final wording is a positive, enumerated statement about two named fields only, and the `endowment_secured_cents` half was phrased as "only ever grows by an accepted contribution" to stay consistent with `routes_plan.py:111` and `routes_permit.py:317` rather than implying it is frozen.

### Orchestrator note (post-Step-8 diff verification)

Independently diffed `PRD.md` against `PRD_FINALIZED.md`: exactly one changed line (272), an in-paragraph append to §3.7's `RETURN_FOR_REVISION` prose, no new sections, no other hunk. Both files are 403 lines and the finalized tail is still the complete `ERR_RESERVE_CONTRIBUTION_INSUFFICIENT | 422 |` row, so nothing was truncated. A near-identical `PRD_FINALIZED.md` is the legitimate outcome here because Step 7 applied zero `implementation/` fixes (per the known "Step 8 identical PRD is OK" case); the one edit is the genuine PRD silence hiding inside the STEP-1c assertion removal.

## Step 9: Complete PRD — 2026-09-06T05:34:13.206Z

Step 9 was run as **four sequential passes over one shared `PRD_COMPLETED.md`**, partitioned by implementation module. A single pass over 17 modules reliably under-scans, and a byte-identical `PRD_COMPLETED.md` would mean the scan never ran. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2, 3 and 4 were forbidden to re-copy and edited additively. Total: **49 edits, 44 diff hunks** against `PRD_FINALIZED.md`.

### Pass 1 — plumbing and shapes (app, envelope, errors, store, util, auth, shape, resolve, serialize, routes_read)

**Modules scanned (all 10).** **Counts:** 11 ambiguity-pins, 2 mismatch-revisions (13 edits).

- §2.1 (header presence) — insert — ambiguity — pinned the trim asymmetry: `X-User-Role` is stripped before the emptiness test, `X-User-ID` is not, so a whitespace-only `X-User-ID` clears rung 1 and fails later at ownership — `auth.py:29,42-44`.
- §2.1 (proponent ownership) — revise — mismatch — "may read and write only its own action tree" now scoped to the *addressed* resource; owner-less resources (species/units/banks) readable by any proponent; the two paginated lists explicitly not owner-scoped — `auth.py:67-74`, `routes_read.py:25,66,123`.
- §2.2 (success bullets) — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A–Z0-9` (24 total) — `util.py:165,173-174`.
- §2.2 (success bullets) — revise — ambiguity — `api_request_timestamp` reads the logical clock, not wall clock, and is identical to the same request's `created_at` — `envelope.py:19`.
- §2.2 (pagination bullet) — revise — ambiguity — four pagination keys carry counters on paginated lists, all-`null` on unpaginated lists, and are **absent** on object/error responses (`meta` holds two keys) — `envelope.py:7-23,32-64`.
- §2.2 (error format) — insert — ambiguity — new bullet: framework-level 404 / 405 / 500 use the same envelope with `error_id` `ERR_INVALID_REQUEST`; trailing-slash-only paths are served, not 404 — `app.py:28,41-62`.
- §2.3 (paginated para) — insert — ambiguity — `has_more` formula (`offset + len(data) < total_count`), no upper bound on `offset`, out-of-range `offset` yields empty `data` + full `total_count` + `has_more` false, unrecognised query params ignored — `envelope.py:42-51`, `shape.py:231-236`, `routes_read.py:84`.
- §2.3 (unpaginated para) — revise — mismatch — "accept no `limit` or `offset`" corrected to *silently ignore* them (never validated, never rejected); null block spelled out as four null-valued keys — `envelope.py:7-12,54-64`, `routes_read.py:30-35`.
- §2.3 (ordering para) — insert — ambiguity — `created_at` ties broken by internal insertion order (never serialised, never `id`), for both listings and cascades — `store.py:68,81-85`.
- §2.4 — insert — ambiguity — field order (`id`, entity fields, `created_at`, `updated_at`, `version`); every declared field always present as JSON `null` rather than omitted; array fields returned verbatim preserving order and duplicates — `serialize.py:197-215`.
- §2.7 (rung 7 para) — insert — ambiguity — explicit JSON `null` is indistinguishable from an omitted key everywhere; body must be a JSON object, and an absent/whitespace-only body is treated as `{}` (so it fails on the first missing required field) — `shape.py:3-4,18-23,57-60`, `util.py:205-223`.
- §2.8 — insert — ambiguity — numbers are JSON numbers never strings; money must be an integer literal (`500.0` rejected); quantities accept 0–2 input fractional digits while "exactly two" describes storage/output (`12` → `12.00`); 3- and 4-digit widths rendered with trailing zeros — `shape.py:116-154`, `util.py:20-70,182-198`.
- §3.1 (listing change) — insert — ambiguity — `rationale` is validated as a non-empty string but neither persisted nor returned — `serialize.py:6-18`.
- §3.3 (list filters para) — insert — ambiguity — lists not identity-scoped but identity still resolved (unknown proponent → 403); filter values matched by exact string equality and *not* enum-validated (unknown value → empty result, not an error); `requires_reevaluation` accepts only case-insensitive trimmed `true`/`false`; filtering happens after ordering, before the window — `routes_read.py:63-146`, `shape.py:239-252`.

Result after pass 1: 404 lines, tail row intact, headings 27 and table rows 85 unchanged.

### Pass 2 — calculations and cascades (calc.py, cascades.py)

**Modules scanned (both, exhaustively).** **Counts:** 10 ambiguity-pins, 1 mismatch-revision (11 edits).

- §3.1 — insert — ambiguity — uplisting hop 1 is a global sweep: every candidate determination of the species is flagged whatever proponent owns it and whatever state its action is in (including `SCREENING` actions hop 2 skips), and a determination already `requires_reevaluation` true is rewritten and re-versioned rather than skipped — cascades.py:33-43
- §3.1 — insert — ambiguity — hop 4's plan flag is versioned again even when already true; a proponent reached via two affected actions is re-derived once — cascades.py:66-75
- §3.1 — insert — ambiguity — expanded the "does not touch" paragraph: permit `status`/take ledger/`reinitiation_trigger_units` untouched, `assurance_review_required` is the only plan field written, no presence status or overlap figure recomputed — cascades.py:26-75
- §3.2 — insert — ambiguity — report `period_end` (date-only) enters the 365-day variant window as **midnight UTC** of that day — calc.py:456-459
- §3.2 — insert — ambiguity — the compliance re-derivation persists score/variant/`open_reinitiation_count` quietly: no `updated_at` refresh, no `version` bump, so a proponent's `version` stays 1 for life — calc.py:500-508
- §3.5 — insert — ambiguity — primary-species selection's final tie-break is insertion order after `created_at`, never `id` — calc.py:194-203
- §3.7 — insert — ambiguity — the endowment contribution rounds exactly once on the four-factor product, with no intermediate rounding — calc.py:305-311
- §3.7 — **revise** — **mismatch** — "recomputed from scratch whenever the commitment set changes" was false: recomputation happens only on commitment creation and on `RETURN_FOR_REVISION`; approval needs none (both statuses contribute) and permit expiry pointedly does not recompute despite emptying the contributing set — calc.py:324-337 vs cascades.py:147-149 (and call-sites routes_plan.py:87, 223)
- §3.7 — insert — ambiguity — each recomputation pass rewrites every contributing commitment's `endowment_contribution_cents` in place (always reproducing the same figure) without bumping that commitment's `version`/`updated_at` — calc.py:330-331
- §3.8 — insert — ambiguity — exceedance hops three and four are source-state gated exactly like hop five; a non-`IMPLEMENTING` plan or non-`PERMITTED` action is left unwritten and unversioned, and a skipped hop does not stop later hops — cascades.py:88-97
- §3.8 — insert — ambiguity — the unwind is not a symmetric reversal: `suspension_count` is not decremented, the action stays `REINITIATION_PENDING`/`TAKE_EXCEEDANCE`, the consultation stays `REINITIATION_REQUIRED` with its counters intact, and the plan hop is itself gated — cascades.py:111-121
- §3.9 — insert — ambiguity — expiry compares `term_end` as **midnight UTC** and strictly: a clock at exactly midnight of `term_end` leaves the permit alive, any later instant that day expires it; the sweep runs on every reposition over the whole permit table — cascades.py:131-134
- §3.9 — insert (one new paragraph) — ambiguity — what expiry leaves standing: `RESERVED` commitments, all endowment/reserve/funding fields (a `CLOSED` plan can read `FULLY_ASSURED`), `assurance_review_required`, `secured_mitigation_units`, the action at `PERMITTED`, the consultation, and every proponent's compliance standing; and expiry is irreversible — an `EXPIRED` permit is skipped by later sweeps, so rewinding the clock revives nothing — cascades.py:137-149

Result after pass 2: 406 lines (+2 = the one new §3.9 paragraph and its blank line), tail row intact. Pass 2 explicitly re-checked §2.1 against `auth.require_identity` and found no contradiction with pass 1, and did not restate pass 1's §2.8 decimal-width clarifier or §3.1 `rationale` prose.

### Pass 3 — write routes (routes_species, routes_action, routes_consult, routes_plan, routes_permit)

**Modules scanned (all 5, exhaustively).** **Counts: 18 ambiguity-pins, 3 mismatch-revisions (21 edits).**

- §2.5 — insert — ambiguity — the clock capability resolves a `Proponent` caller's identity, so an `X-User-ID` naming no `Proponent` row is `ERR_NOT_RESOURCE_OWNER` even though it addresses no resource — `routes_species.py:186-187`
- §3.1 — insert — ambiguity — a duplicate `scientific_name` is `ERR_INVALID_REQUEST` (400), raised after the body otherwise passes shape validation — `routes_species.py:59-64`
- §3.1 — insert — ambiguity — a duplicate `unit_code` within one species is `ERR_INVALID_REQUEST` (400) post-shape; the same code under another species is legal — `routes_species.py:96-101`
- §3.1 — insert — ambiguity — designating a unit always writes and versions the owning species row, even when `critical_habitat_designated` does not change value — `routes_species.py:113-118`
- §3.1 — insert — ambiguity — `rationale` carries no maximum length (bound only; did not restate pass 1's not-persisted/not-returned prose) — `routes_species.py:128`
- §3.2 — revise — **mismatch** — "Two events also clear penalties ... without any recomputation of their own ... from the next read" was false: both the event response and the BA resubmission re-derive the score in-request per §2.10 — `routes_permit.py:321`, `routes_consult.py:70`
- §3.3 — insert — ambiguity — recording a presence determination is gated on nothing but ownership and §3.3's own rules; the action's `status` is never consulted, so determinations may be added post-screening/post-permit and re-derive nothing — `routes_action.py:69-146`
- §3.4 — insert — ambiguity — both consultation-creating branches open the row with `ba_revision_number`/`info_request_count`/`reinitiation_count` at 0, `ba_effects_analysis_complete` false, and four null stamps — `routes_action.py:186-202`
- §3.5 — insert — ambiguity — `ba_narrative` is non-empty, unbounded above, persisted verbatim — `routes_consult.py:29`
- §3.5 — insert — ambiguity — the action hop out of `REINITIATION_PENDING` is gated on that exact source state (skipped row unwritten/unversioned), while the proponent recompute fires either way — `routes_consult.py:63-70`
- §3.5 — insert — ambiguity — `request_note` non-empty, unbounded above, neither persisted nor returned — `routes_consult.py:81`
- §3.5 — insert — ambiguity — `concurrence_note` validated identically and likewise not persisted — `routes_consult.py:107`
- §3.5 — insert — ambiguity — `rpa_description` non-empty when supplied, unbounded above, persisted; null when omitted — `routes_consult.py:132`
- §3.6 — revise — **mismatch** — "`mitigation_delta_units` … stays null while `final_mitigation_units` is null" is impossible: both are 0.00 from creation (the delta is *not* seeded as final−preliminary) until submission writes them — `routes_action.py:242-243`, `routes_plan.py:131-135`
- §3.7 — insert — ambiguity — `decision_note` non-empty when supplied, unbounded above, neither persisted nor returned — `routes_plan.py:148`
- §3.7 — insert — ambiguity — `RETURN_FOR_REVISION` also drops `reserve_remaining_cents` to 0 while `reserve_drawn_cents` stands (added to the existing recompute enumeration; left pass 2's two-moment sentence untouched) — `routes_plan.py:223` → `calc.refresh_reserve_remaining`
- §3.8 — insert — ambiguity — the multi-opinion tie-break is effectively insertion order, since an opinion's `created_at` and `issued_at` are always the same instant — `routes_permit.py:31-34`
- §3.8 — insert — ambiguity — at issuance the plan hop is unconditional but the action hop is gated on `HCP_DEVELOPMENT`; an uplisted action stays `REINITIATION_PENDING`, unwritten and unversioned, and the permit issues anyway — `routes_permit.py:93-95`
- §3.8 — insert — ambiguity — `mitigation_units_verified` is recorded and returned but read by no calculation, and never folded into `secured_mitigation_units` — `routes_permit.py:110`
- §3.8 — insert — ambiguity — `period_end` enters the clock comparison as midnight UTC, so a period ending on the clock's own date passes only at exactly midnight — `routes_permit.py:129-130`
- §3.8 — insert — ambiguity — `adjudication_note` non-empty when supplied, unbounded above, null when omitted — `routes_permit.py:184`
- §3.8 — revise — **mismatch** — "surfaces on the next read" replaced: **both** `ACCEPT` and `REJECT` re-derive the proponent's three compliance fields as the request's last act, after any ledger reversal, as the quiet write of §3.2 — `routes_permit.py:207-225`
- §3.9 — insert — ambiguity — a new event starts with `contributed_cents` at integer 0 (never null) and `response_note` null — `routes_permit.py:280,284`
- §3.9 — insert — ambiguity — the `UNFORESEEN` branch leaves the plan row entirely unwritten (no `updated_at`/`version` move), whereas `CHANGED` always writes and versions it even at a 0 draw — `routes_permit.py:246-257`

Result after pass 3: 406 lines, tail row intact, 42 hunks vs `PRD_FINALIZED.md`. Pass 3 handed four items forward rather than silently resolving them.

### Pass 4 — reconciliation

- **Item 1 (adjudicator-conflict skip, `routes_permit.py:192`) — NO EDIT NEEDED.** Pass 3's unreachability reasoning verified from source. (a) `permit is None`: the store exposes no delete of any kind — the only `pop` calls in the whole implementation are `routes_consult.py:173-174`, which strip `updated_at`/`version` off a newly minted opinion — so a report's `permit_id`, written from a resolved permit at `routes_permit.py:146`, always resolves. (b) `issued_by_user_id is None`: its single write site is `routes_permit.py:81` (`caller.user_id`) on an `AGENCY`-only endpoint, and `auth.authenticate` rung 1 (`auth.py:42-44`) rejects a missing or `""` `X-User-ID` for `WildlifeAgency`, so the field is always a non-empty string. No request can reach the skip; §3.8's adjudication prose left alone.
- **Item 2 (§2.10 compliance re-derivation trigger list) — EDITED.** Grepped every `refresh_compliance` call site: `routes_read.py:56` (every proponent read), `routes_permit.py:225` (adjudication, outside the ACCEPT/REJECT branch so both decisions), `routes_permit.py:321` (circumstance response), `routes_consult.py:70` (BA resubmission out of `REINITIATION_REQUIRED`, outside the action-hop status gate at lines 65-68 so it fires either way), `cascades.py:75` (uplisting, once per affected proponent, independent of whether the consultation hop fired), `cascades.py:108` (take-exceedance hop five, only when the consultation moves to `REINITIATION_REQUIRED`). §2.10 named only three of these and omitted the BA resubmission entirely; rewritten as an accurate five-item enumeration.
- **Item 3 (§3.6 gate order) — NO EDIT NEEDED.** Verified at `routes_action.py:224-229`. To distinguish status → existing-plan → action_type from the prose's status → action_type → existing-plan a request must violate both the existing-plan gate and the `NON_FEDERAL` gate at once. An existing plan implies the action was `NON_FEDERAL` at plan creation (line 228), and `action_type` is written only at registration (`routes_action.py:39,53`) and never mutated anywhere. So the pair is unreachable and the two orders are observationally identical. (Note: pass 3's stated reason — that a second attempt always fails the `CONSULTATION_CONCLUDED` gate first — is not airtight, since the reinitiation loop can return a plan-bearing action to `CONSULTATION_CONCLUDED` via `HCP_DEVELOPMENT → REINITIATION_PENDING → FORMAL_CONSULTATION → CONSULTATION_CONCLUDED`; the conclusion nonetheless holds by the `action_type` argument.) §3.6 prose left alone.
- **Item 4 (`_seed_take_ledger` fallback, `routes_permit.py:40-42`) — NO EDIT NEEDED.** Verified unreachable. `presence_status` is never rewritten anywhere in the implementation (only read: `calc.py:166`, `routes_read.py:138`) and determinations are never deleted, so a candidate set only ever grows; plan creation already required a non-empty one (`calc.preliminary_mitigation_units`, `calc.py:254-256`, raises `ERR_NO_PRESENCE_DETERMINATIONS`). The uplisting cascade touches only `requires_reevaluation` (`cascades.py:47-48`), never `presence_status`, so it cannot empty or invalidate the set. At issuance `action` is non-None and `calc.incidental_take` therefore gets a non-None `primary_species` and returns figures. §3.8 stays silent on the fallback.
- **Item 5 (boundary-consistency sweep).** §3.7 recomputation triggers: the merged paragraph is coherent — `recompute_endowment` has exactly the two call sites the prose claims (`routes_plan.py:87`, `:223`), and pass 3's `reserve_remaining_cents` clause sits in the RETURN_FOR_REVISION paragraph and matches `recompute_endowment → refresh_reserve_remaining`. One residual false-exhaustive reading fixed: `refresh_reserve_remaining` also runs standalone at approval (`routes_plan.py:201`) and on a `CHANGED` draw (`routes_permit.py:256`), so §3.7 now says so explicitly. Compliance re-derivation across §3.2/§3.8/§2.10: now one rule (quiet write, in-request), but the sweep found two surviving contradictions with it — §3.1's "with `compliance_standing_score` re-derived on its next read" and §3.9's "disappears from the next read of its `compliance_standing_score`" — both fixed to the in-request quiet write, matching `cascades.py:75` and `routes_permit.py:321`. §3.9 permit-expiry: pass 2's "what expiry leaves standing" paragraph and pass 3's `UNFORESEEN`-vs-`CHANGED` plan-write asymmetry are in different paragraphs about different operations, no overlap; expiry re-deriving no compliance standing confirmed (no `refresh_compliance` in the expiry path). §3.1 uplisting: line 155's unit-designation species-row versioning and line 161's "does not touch" list concern different operations and do not conflict. §2.8 widths: stated once authoritatively (2/3/4 digits and whole cents); §3.5 and §3.7 restate them locally with identical values, no contradiction. Near-duplicate sweep over "insertion order", "midnight UTC of that day", "left unwritten and unversioned", "quiet", "half up", and the decimal widths found only distinct, non-redundant instances — nothing to collapse.

Edits made in pass 4 (4):
- §2.10 — revise — mismatch — the in-request re-derivation trigger list for `compliance_standing_score`/`compliance_variant_applied`/`open_reinitiation_count` was a false exhaustive claim of three; now enumerates all five (adjudication under either decision, uplisting cascade per affected proponent, take-exceedance cascade, BA resubmission out of `REINITIATION_REQUIRED`, circumstance response) and ties them to §3.2's quiet write — `routes_consult.py:70`, `cascades.py:75`, `cascades.py:108`, `routes_permit.py:225`, `routes_permit.py:321`.
- §3.1 — revise — mismatch — uplisting hop four said the proponent's score was re-derived "on its next read"; it is re-derived in the same request as a quiet write, for every affected proponent whether or not the consultation hop fired — `cascades.py:69-75`.
- §3.9 — revise — mismatch — the circumstance-response paragraph said the unresponded-circumstance penalty clears "from the next read"; it clears inside the response request — `routes_permit.py:319-321`.
- §3.7 — revise — ambiguity — "recomputed from scratch at exactly two moments" read as excluding every `reserve_remaining_cents` write; now states that `reserve_remaining_cents` alone is also refreshed on the approval path and on a `CHANGED` draw — `routes_plan.py:201`, `routes_permit.py:256`.

### Orchestrator note (final verification and close-out)

Verified independently rather than trusted:
- **PRD chain:** `PRD.md` 403 lines → `PRD_FINALIZED.md` 403 lines → `PRD_COMPLETED.md` **406 lines**. `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (the known "Step 9 never ran" failure signature), and `diff` reports **44 hunks**. Tail is the complete `ERR_RESERVE_CONTRIBUTION_INSUFFICIENT | 422 |` row, so nothing was truncated by any pass.
- **Aggregate Step 9 totals:** 39 ambiguity-pins + 6 mismatch-revisions + 4 reconciliation edits = **49 edits**; 3 items adjudicated as needing no edit because the impl paths are provably unreachable.
- **Deliverables present:** three SCAFFOLD yamls, `worklog.md`, `test_helpers/` (9 modules), `test_suite/` (conftest + 20 test files, 200 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}`, and the 8 passing `results.{1..8}.json` from the final green sweep.
- **Cleanup:** the empty `.scratch/` parent, the orchestrator's `workspace/sweep.sh` helper, and every `__pycache__` were removed. No `SWEEP_DONE`, `sweep.log`, or `round.*.log` strays remain. Steps 8 and 9 touched only PRD documents, so the verified 8/8 × 200/200 sweep result stands for the shipped implementation.

Pipeline complete through Step 9.
