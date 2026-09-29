# Worklog — task_2785_municipal_bond_underwriting_official_statement_preparation

## Step 1: Create task directory — 2026-09-04T20:47:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2785_municipal_bond_underwriting_official_statement_preparation` and its `workspace/` subdirectory. Index 2785 was pre-assigned by the orchestrating caller; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T22:45:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and the lint is clean.

**Verdict block (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../task_2785_municipal_bond_underwriting_official_statement_preparation/SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    71
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     96
  Calls scanned (§1.8+§1.9):  1350

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2785_municipal_bond_underwriting_official_statement_preparation/`):
- `SCAFFOLD.yaml` — 3,303 lines / 164 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,613 lines / 163 KB
- `SCAFFOLD_CORNER_DESIGN.yaml` — 6,287 lines / 379 KB

**SCAFFOLD.yaml (§1.0–§1.7):** 14 entities, 10 state machines, 2 §1.2.1 concurrency rules, 8 calculation rules, 46 validation rules (16-rung priority ladder), 71 endpoints, 66 errors, 6 roles. `complexity_profile`: archetype compliance_audit / quota_allocation, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, conditional_feature_flags; graph topology, cyclic state machines, segregation_of_duties role model, immediate consistency, difficulty expert_plus. No `scaffold_difficulty_design` / `scaffold_corner_design` keys; the "harder than expert level" directive is not present in `scenario`.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rule_ids × 2 instances = 18 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** all 9 guide sections, 117 instances (96 with full `test_recipe`, 21 `excluded_because` stubs citing §1.8) — entities 17, state_machines 21, calculations 14, validations 39, endpoints 6, errors 2, rbac 10, cross-cutting complexity layers 6, consistency model 2.

**Verified invariants:** all 135 instance names globally unique across §1.8 ∪ §1.9; every stub's `difficulty_instance` resolves to a real §1.8 instance name; every instance has exactly one of `test_recipe`/`excluded_because` and no non-schema keys; every `section:`/`claim_type:` value comes from the claim-extraction guide; all 66 declared error ids are referenced by at least one design instance.

**Two fixes needed to reach clean lint** (worth noting for future scaffolds): (1) `scaffold_lint.py` check (f) matches sub-resource reverse-reachability GETs literally against `/<parent>/{id}/<segment>`, so the scaffold's `{deal_id}`-style path parameters produced 9 spurious `FK_REVERSE_UNREACHABLE` violations — I normalized every path placeholder to `{id}` across all three files (248 replacements), which is also the convention in SKILL.md's own examples. (2) A §1.9 instance that deliberately posts system/computed fields to prove they are ignored must have `_input_ignored` (or another `_NEGATIVE_NAME_RE` token) in its name, otherwise check (c) flags the extra payload keys; renamed to `system_and_computed_fields_in_the_body_are_input_ignored`. Also fixed a missing required `reopen_reason` in one §1.8 reopen call.

Orchestrator verification: all three files present, non-trivial (3303/2613/6287 lines); grep for "harder than"/"expert level!" in SCAFFOLD.yaml returned nothing — no difficulty-directive leak.

## Step 3: Copy shared files — 2026-09-04T22:46:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T23:05:00.000Z

Subagent summary (verbatim):

PRD.md is complete.

**Output:** `.../workspace/PRD.md` — **466 lines, 15,686 words**, built incrementally (one `Write` + seven `cat >> ... <<'PRDEOF'` appends). It ends at a real section boundary: the final line is the last row of the §5 error table (`| \`ERR_POST_ISSUANCE_HANDOFF_INCOMPLETE\` | 422 |`). Last heading: `## 5. Error Code Catalogue`. No audit footer, no PASS report inside the file.

**Sections written**
- §1 Introduction (3 paragraphs)
- §2.1 RBAC · 2.2 Response Structure (byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination and List Ordering · 2.4 Common Properties, Identifiers and the Logical Clock · 2.5 Validation Order and the First-Violation Rule (all 16 priority tiers) · 2.6 Precision, Rounding and Denomination · 2.7 Version Guarding · 2.8 Segregation of Duties and Firm Standing · 2.9 Conserved Identities and Cascade Discipline · 2.10 Nested Resource Retrieval
- §3.1 Participants and Disclosure Risk · 3.2 Maturity Schedule and Yield-to-Worst Pricing · 3.3 Credit Enhancement · 3.4 Official Statement, Sections, Undertakings and Posting · 3.5 Rating Engagements and Presentations · 3.6 Syndicate Formation and the Sale-Method Fork · 3.7 The Order Book (periods, entry, waterfall, reopen) · 3.8 Pricing, Compensation Disclosure and Arbitrage Yield · 3.9 Award, Closing Documents, Handoff, Close and Cancellation
- §4 Endpoint Definitions (status-code paragraph + table) · §5 Error Code Catalogue

**Coverage (mechanically verified with a python/yaml differ against SCAFFOLD.yaml)**
- Endpoints: **71/71** rows, table is exactly 4 columns (73 pipe-rows = 71 + header + separator); rows generated programmatically from the scaffold, so methods, paths, descriptions and role lists are transcription-exact.
- Errors: **66/66** rows, exactly 2 columns (68 pipe-rows), and all 66 IDs also appear verbatim in §2/§3 prose.
- Validation rules: **46/46** — every rule's `on_violation` error, priority tier and `applies_to` scope is stated (ladder in §2.5, re-expressed contextually in §3).
- State machines: **10/10 entities, 43/43 transitions**, including all system/cascade transitions; every state name in every machine appears verbatim.
- Calculations: **8/8** translated into prose with pinned rounding order and worked figures (reoffering price incl. the 100.000 tie, issue-price total, both gross-spread variants, premium/net proceeds, allotment waterfall incl. the 1,715,000 / 1,280,000 pro-ration, takedown reconciliation, arbitrage yield incl. the strict-comparison 4.2083 case, disclosure risk incl. 39/40 gate cases).
- Both `concurrency_rules` (`expected_deal_version`, `expected_order_period_version` -> 412) documented in §2.7 and at their endpoints.

**Hard Contracts**
- Contract 1 (Field-Name Coverage): **PASS** — 142 required identifiers all present in backticks; plus 93/93 enum members, all state names, and all ad-hoc endpoint output keys. Two passes run; the single gap found on pass 1 (`rating_engagement_id`) was repaired in §3.5.
- Contract 2 (Rule Coverage): **PASS** — sibling branches (competitive vs negotiated; `DRAFT`->`APPROVED` vs `NEEDS_REVISION`->`APPROVED`) written at equal density, and the exceed-vs-equal asymmetry on `liability_pct` is called out explicitly.
- Contract 3 (§3 Path Purity): **PASS** — 307 distinct backticked tokens in §3, zero start with `/`, zero are bare HTTP methods, zero combine method+path.

Two judgment calls, both recorded faithfully: an omitted `priority_policy` is documented as `STANDARD_PRIORITY` (scaffold gives no default for this optional input), and the enhancement-commit "recompute when `PRICED`" side effect is phrased as a neutral conditional since the commit precondition excludes `PRICED`. Also confirmed the difficulty directive did not leak.

Orchestrator verification (truncation guard): `wc -l` = 466; `tail -25` shows the §5 error table terminating cleanly on its 66th row; 66 `ERR_*` rows and 73 endpoint pipe-rows (71 + header + separator) counted mechanically; grep for "harder than|expert level|scaffold|test_recipe|corner case" in PRD.md returned nothing. PRD is NOT truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T23:45:00.000Z

Subagent summary (verbatim):

The implementation is complete and verified.

## Modules written (`workspace/implementation/`, 3,684 lines total)

Core (shared machinery):
- `app.py` 92 — Flask factory, 11 blueprints, `ApiError` + 400/404/405/415/500 envelope handlers, `PORT` binding
- `db.py` 78 — in-memory `Store` with 14 empty dicts, logical clock defaulting to `2026-08-01T00:00:00Z`, `new_row`/`touch`
- `errors.py` 110 — full 66-entry error catalog + HTTP mapping
- `response.py` 132 — envelope, `req_`-prefixed ids, 3-digit ISO timestamps, pagination (limit 10/1–100, offset 0)
- `validation.py` 220, `serializers.py` 253, `middleware.py` 110, `lookup.py` 173
- `services/calc.py` 275 (eight calculations, Decimal/ROUND_HALF_UP, pinned rounding order), `services/derive.py` 176 (derived fields + cascades)

Routes: `deals.py` 464, `statements.py` 320, `orders.py` 311, `ratings.py` 222, `enhancements.py` 165, `tranches.py` 156, `participants.py` 124, `closing.py` 98, `syndicate.py` 95, `undertakings.py` 68, `clock.py` 31.

## Endpoint coverage

**71 routes registered — an exact set-match against SCAFFOLD.yaml's 71 endpoints** (programmatic diff: zero missing, zero extra).

## Boot / smoke result

Booted clean on `PORT=18785 bash start.sh` (foreground, 0.0.0.0). Verified via a 55-step end-to-end script, all steps passing:
- Envelope shapes: success object, paginated array (`limit/offset/total_count/has_more`), `ERR_DEAL_NOT_FOUND` 404, `ERR_NOT_FOUND` 404 for unrouted paths, `ERR_INVALID_REQUEST` 422, `ERR_STALE_ORDER_PERIOD_VERSION` 412.
- Full lifecycle: issuer -> firms -> deal -> tranche -> syndicate seat -> submit-structure -> NEGOTIATED designation -> undertaking activate -> OS with 4 mandatory sections approved by a non-author -> submit-for-review -> post-preliminary -> rating engagement acknowledge/present/clock-promote/assign-rating -> order period open/order/close -> reopen -> close -> price -> handoff -> award (6 required docs, correct negotiated composition) -> post-final -> execute/waive -> close.
- Arithmetic checks against PRD worked examples: the priority waterfall reproduced O1 2,005,000 ALLOTTED / O2 1,715,000 / O3 1,280,000 PARTIALLY_ALLOTTED / O4 UNFILLED with 5,000,000 total; money identity held (5,408,800 = 5,368,800 + 40,000 + 0); par identity held exactly across close -> reopen -> close (5,000,000/0 -> 0/5,000,000 -> 5,000,000/0); the 60-minute presentation buffer accepted an exact-60 gap and rejected 59 minutes.

Storage is in-memory only (grep confirms no sqlite, no file writes, no `/tmp`), nothing is seeded at boot, and `__pycache__` was cleaned up. The server was killed by resolving the PID listening on 18785 only (no pattern pkill).

(Note: Steps 5 and 6 were launched concurrently in a single assistant message, per the skill; Step 6's summary is recorded here first because it exited first. Step 5's entry follows.)

## Step 5: Generate unit tests — 2026-09-05T00:15:00.000Z

Subagent summary (verbatim):

Step 5 is complete for `task_2785_municipal_bond_underwriting_official_statement_preparation`.

## Files written (all at the TASK ROOT — nothing under `workspace/`)

**`test_helpers/` — 3,342 lines, 9 files**

| File | Lines |
|---|---|
| `__init__.py` | 63 |
| `api_client.py` | 505 |
| `api_errors.py` | 173 |
| `assertions.py` | 433 |
| `constants.py` | 232 |
| `factories.py` | 430 |
| `fixtures.py` | 945 |
| `test_users.py` | 122 |
| `types.py` | 439 |

**`test_suite/` — 11,024 lines, 18 test files + `conftest.py` (148)**

Queue A (difficulty): `test_01` 340, `test_02` 354, `test_03` 273, `test_04` 440, `test_05` 236, `test_06` 303, `test_07` 213, `test_08` 365, `test_09` 508.
Queue B (corner): `test_20_entity` 906, `test_21_state_machine` 1175, `test_22_calculation` 1158, `test_23a_validation` 1144, `test_23b_validation` 1230, `test_24_endpoint` 595, `test_25_error` 168, `test_26_rbac` 736, `test_27_complexity_and_consistency` 732.

## Coverage: 114/114 non-stub instances, zero skipped

18 difficulty instances (9 rule_ids x 2) + 96 non-stub corner instances. All 21 stubs (3 state_machines, 7 calculations, 7 validations, 1 endpoints, 3 complexity layers) correctly left untranslated.

## Audits

```
design universe: 114 non-stub, 21 stub
emitted: 18 files, 221 test functions, 221 Design tags, 114 distinct instances
non-stub instances covered: 114/114
stubs translated: none
no tag/marker problems
```
Exactly one `Design:` line per test, every tag resolving to a real non-stub instance; no `skip`/`xfail`/`TODO`/`FIXME` anywhere. A separate citation pass verified all 219 quoted PRD sentences are byte-verbatim substrings of `PRD.md` — it caught two docstrings in `test_22` that had transcribed the PRD's em dash as `--`, which I fixed. Whole suite collects: **231 tests in 0.34s** (231 > 221 because `test_26_rbac` parametrizes several tests). Money is emitted as JSON numbers throughout, guarded by `assert_is_number`; all timestamp comparisons route through `canonical_timestamp` (millisecond truncation).

## Notable PRD-first substitutions (design text vs. what the PRD uniquely derives)

- `ERR_MATURITY_TRANCHE_NOT_FOUND` is absent from §5's 66-error catalogue -> asserted `ERR_TRANCHE_NOT_FOUND` per §2.5 tier 7.
- Field/enum corrections: `gross_spread_usd`->`gross_spread_total_usd`, `S_AND_P`->`RatingAgency.SP`, `GROUP_NET`->`INSTITUTIONAL_PRIORITY`, `COMPETITIVE_BID`/`NEGOTIATED_SPREAD`->`COMPETITIVE`/`NEGOTIATED`; par counters asserted `== 0` not null.
- Design's calculations instance 1 gave T2/T3 the same `maturity_date` (PRD rejects with `ERR_TRANCHE_SEQUENCE_CONFLICT`); T3 moved to 60 periods, preserving the 109.522 outcome. Design's "40,275.00 forgotten allowance" is not reproducible (12,917.50 is correct) — derived from the formula instead of hard-coded.
- Individually dropped non-derivable assertions: zero-length order period's `ERR_ORDER_PERIOD_OVERLAP` (PRD only requires `closes_at > opens_at`); `disclosure_clearance` after enhancement withdrawal (§3.3 vs §2.9 ambiguity); the `deal_id` field name in the yield-restriction projection; `permitted_investment_yield_pct` as a stored Deal field (read-only projection only, two files); RBAC's unrecognised-role->401 (PRD tiers 1/2 make it 403 `ERR_UNAUTHORIZED`).
- `competitive_designation_requires_an_engaged_municipal_advisor`: negative half unreachable through the API (only an MA resolved against the deal's own `municipal_advisor_firm_id` can submit) — positive half only.
- Error envelope: PRD §2.2 has no `success` field; tests pin `response_type == "error"` and exact top-level/`meta` key sets.

## Operational hazard worth flagging to the pipeline

`/tmp/corner.txt` was **overwritten mid-task by a concurrent pipeline** on this shared host — it held a battery-storage task's design index in a foreign format. I recovered by regenerating into task-private `/tmp/prdbench_2785/` and verified the regenerated dump matched my recorded section offsets exactly. Future runs should write design dumps to task-scoped paths, never generic `/tmp/<name>.txt`.

Also two structural notes for Step 7: `fx.approve_mandatory_sections` sets `is_material_risk=True` on its CONTINUING_DISCLOSURE section (which would vacuously satisfy the high-risk gate) and never sets `references_credit_enhancement`, so affected files use module-local variants; undertakings and credit enhancements have no individual GET, so module-local `_read_undertaking`/`_read_enhancement` filter the deal-scoped listing by id.

Orchestrator verification: `test_helpers/` and `test_suite/` are both at the task root; `find workspace -name test_helpers -o -name test_suite` returned nothing (no stray copies under workspace/). `__pycache__` dirs removed before Step 7.

## Step 7: Run tests and iterate — 2026-09-05T00:22:00.000Z

Subagent summary (verbatim):

Clean 8-round sweep achieved: **231/231 passing in all 8 parallel rounds**.

## Summary

**Iterations run:** 2

**Iteration 1 baseline:** 228/231 in every round — 3 deterministic failures (identical union across all 8 rounds, no flakiness, no load-induced timeouts or connection resets).

**Tests deleted:** none. All three failures traced to verbatim PRD rules that are uniquely derivable; both were test-artifact bugs.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `material_risk_section_payload()` and `continuing_disclosure_risk_section_payload()`: both passed `is_material_risk=True` positionally into `section_payload()` *and* splatted `**overrides`, so a caller overriding that flag raised `TypeError: got multiple values for keyword argument 'is_material_risk'`. Rewrote both to merge the default into a dict that `overrides` can win over. This broke `test_risk_score_exactly_at_the_gate_blocks_preliminary_posting` and `test_risk_score_one_point_below_the_gate_posts_preliminary`, which deliberately build an *immaterial* `CONTINUING_DISCLOSURE` section to leave the high-risk gate unmet.

**Fixes applied to `test_suite/`:**
- `test_suite/test_21_state_machine_corners.py` — `test_opening_the_book_waits_for_the_deal_to_reach_a_pricing_state`: the test drove `POST /order-periods/{id}/open` as an `Underwriter` against a bare `structuring_deal` (no syndicate seat, `sale_method` still `UNDETERMINED`), so PRD 2.5 tier 8 (actor ownership) correctly fired `ERR_ROLE_IDENTITY_MISMATCH` *before* the tier 11 deal-state guard the test wanted to isolate — the implementation was PRD-faithful. Fixed the setup to seat the acting underwriter firm as an `ACTIVE` `SENIOR_MANAGER` first (PRD 2.1's ownership route for an `Underwriter`; the `COMPETITIVE` carve-out cannot apply pre-designation), and switched the follow-on designation from `COMPETITIVE` to `NEGOTIATED`, because PRD 3.6 forbids any `SyndicateMember` row on a competitive deal. The assertion itself (`ERR_DEAL_INVALID_STATE`) was left exactly as written.

**Fixes applied to `implementation/`:** none — no implementation defects were found. `middleware.require_deal_ownership` and the order-period routes already implement the ladder ordering PRD 2.5 specifies.

Orchestrator verification: all 8 `results.$i.json` present and independently re-read — every round reports `passed=231 total=231 failed=0`, all written at 00:21 (the sweep artifacts are real, not a subagent claim).

Orchestrator decision on Step 8: Step 7 applied 0 `implementation/` fixes but DID make 1 `test_helpers/` fix and 1 `test_suite/` fix, so the skill's skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is not met. Step 8 runs, with those two items as its `<step_7_diff>` focus list. Given that both were pure test-artifact bugs, a near-zero-diff PRD_FINALIZED.md is a legitimate outcome here.

## Step 8: Finalize PRD — 2026-09-05T00:33:00.000Z

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` created as a one-line patch of `PRD.md`.

## Line counts
- `PRD.md`: 466 lines / 117,221 bytes
- `PRD_FINALIZED.md`: 466 lines / 117,667 bytes
- Line delta: 0 lines (0.0%); byte delta +446 (+0.38%) — one line revised in place, no lines added or removed.

## Changes
- **§2.5 tier 8 (Actor ownership)** — revise — appended one sentence pinning that a resource addressed by its own identifier is still deal-scoped work: scheduling/opening/closing an order period and entering/cancelling an order are each checked against the deal that owns the order period, so an `Underwriter` with no `ACTIVE` `SyndicateMember` seat on a non-`COMPETITIVE` deal is refused at tier 8 before any §3.7 state or window guard — `implementation/routes/orders.py:42,99,123,202,296` + `implementation/middleware.py:89-101`.

## Per-edit pre-edit search log

**Edit 1 — §2.5 tier 8**
- (a) Subject: which operations tier-8 deal ownership is evaluated on, and the `Underwriter` `ACTIVE`-seat / `COMPETITIVE` carve-out as it applies to child-addressed (non-`/deals/{id}/...`) endpoints.
- (b) Enumerated/read: `middleware.py` (`authenticate`, `has_active_seat`, `require_deal_ownership`, `require_pinned_analyst`); grepped every `require_deal_ownership` callsite repo-wide and read the surrounding endpoint bodies — `routes/orders.py` (create_period 42, open 99, close 123, create_order 202, cancel_order 296; reopen has **no** check, `ComplianceOfficer`-only so vacuous), `routes/statements.py` (create 47, request-revision 123, post-preliminary 177, post-final 211; submit-for-review / resume-drafting / section create / section approve have no check but are `BondCounsel`-only, i.e. vacuous), `routes/deals.py` (114, 146, 198, 308, 369, 417; handoff/close are `ComplianceOfficer`-only), `routes/tranches.py:51`, `routes/enhancements.py` (47, 100, 134), `routes/syndicate.py:37` (with `adding_firm_id` carve-out), `routes/undertakings.py` (27, 57), `routes/ratings.py` (34, 108, 164, 216; analyst paths use `require_pinned_analyst` instead), `routes/closing.py` (execute/waive — **no** ownership check despite `IssuerOfficial`/`Underwriter`/`MunicipalAdvisor` being authorised), plus `lookup.deal_of_period` / `deal_of_order` to confirm the deal resolved for child paths.
- (c) Wording adjustment: I deliberately did **not** write a universal claim ("every operation on a child of the deal"), because `closing-documents/{id}/execute` admits three entity-backed roles and performs **no** ownership check — a universal sentence would have created a fresh mismatch off the Step 7 site. The sentence was scoped to the order-period/order family only (the Step 7 subject), and phrased "on a deal whose `sale_method` is not `COMPETITIVE`" so it makes no claim about the competitive carve-out's suspension test or about the add-syndicate-member self-seat carve-out. "before any state or window guard of section 3.7" was chosen (rather than naming a specific error) so it holds for all five endpoints, including `create_period`, which has no state guard but does have the tier-14 overlap check after ownership.

## No-op items
- `test_helpers/factories.py` (`material_risk_section_payload` / `continuing_disclosure_risk_section_payload` duplicate-kwarg `TypeError`): confirmed a pure Python kwargs bug in the fixture factory with **no PRD dimension**. I verified the two affected tests (`test_06_boundary_precision.py:163,190`) exercise only rules PRD already pins verbatim — the inclusive score-40 gate (§3.1/§3.4) and the `mandatory_sections_approved` definition (§3.4) — and that `routes/statements.py:188-196` + `calc.DISCLOSURE_RISK_GATE = 40` match that prose exactly. No edit made.
- `test_suite/test_21_state_machine_corners.py` setup change from `COMPETITIVE` to `NEGOTIATED`: traced to `routes/deals.py:160-161`, which refuses designation when *any* `SyndicateMember` row exists (no status filter) — already stated verbatim in §3.6 ("no `SyndicateMember` row may exist on the deal at all"). Kept verbatim, no edit.
- No implementation fixes were made in Step 7, so no mismatch-driven edits were required.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one hunk, `103c103` — the §2.5 tier 8 line revised in place, no other change. 466 lines both files; 117,221 -> 117,667 bytes.

## Step 9: Complete PRD — 2026-09-05T01:00:00.000Z

Orchestrator note on method: Step 9 was run as THREE SEQUENTIAL, MODULE-PARTITIONED passes over one shared `PRD_COMPLETED.md`, rather than one single-shot full scan. A one-shot scan over a 20-module / 71-endpoint implementation reliably degenerates into a near-no-op. Pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from re-copying (that would have destroyed the earlier passes' edits) and were restricted to in-place `Edit` calls. Partition: pass 1 = core machinery (app/db/errors/response/validation/serializers/middleware/lookup) + deals/tranches/participants/clock; pass 2 = services/calc.py, services/derive.py, routes/orders.py, routes/syndicate.py; pass 3 = statements/undertakings/ratings/enhancements/closing. Each pass handed forward any out-of-slice observation as an explicit carry-over item for the pass that owned the code, and both carry-overs were resolved (pass 2 pinned `governing_statement` tie-breaking and the `insured_tranche_ids` premium source; pass 3 widened §2.4's `touch(deal)` claim after enumerating all 18 callsites, 15 unconditional + 3 conditional, so the universal statement is globally true).

### Pass 1 summary (core machinery + deals/tranches/participants) — verbatim

Modules scanned: app.py (7 behaviors), db.py (6), errors.py (66 catalogue entries + 3 transport fallbacks), response.py (12), validation.py (24), middleware.py (11), lookup.py (13 not-found mappings + 20 collection views), serializers.py (14 field sets), routes/clock.py (5), routes/participants.py (8 endpoints), routes/deals.py (12 endpoints / ~55 guards), routes/tranches.py (4 endpoints / 7 ordered guard tiers).

Counts: **Ambiguity-pins 25, mismatch-revisions 4, no-change confirmations ~80.**

Notable changes: §2.1 header trimming + exact case-sensitive role match; §2.1 the three underwriter ownership carve-outs tried in fixed order; §2.2 resource objects carry the complete declared field set with unpopulated fields as `null`; §2.2 `api_request_timestamp` **revise/mismatch** — read from the logical clock, not wall clock; §2.3 pagination non-integer definition (`limit=`/`10.0`/`+10` rejected, `offset=-0` accepted); §2.3 `created_at` ties broken by creation sequence; §2.3 filters are unvalidated exact matches (bad boolean filter dropped, not rejected); §2.4 `id` is canonical lower-case UUIDv4; §2.4 `updated_at` equals `created_at` on a fresh row; §2.4 **revise/mismatch** — a recompute landing on the existing value is not a mutation and does not advance `version`, the directly-targeted `Deal` excepted; §2.4 clock may move backwards, `data` is exactly `{current_utc, held_presentation_ids}`, clock moves before the sweep; §2.5 tier 3 keyed on declared role so it fires on reads; §2.5 tier 5 explicit-null-equals-omission, non-JSON body read as `{}`, datetime parser accepts offsets/naive/any fractional width; §2.6 money/percent as JSON numbers not strings; §3.2 deal creation has no ownership check and unbounded `record_retention_years`, guard order issuer->advisor->suspension->designation; §3.2 tranche creation has no deal-state precondition, monotonicity strict and symmetric; §3.2 non-positive principal is tier 15 `ERR_DENOMINATION_INVALID`; §3.2 `first_call_date` alignment runs whenever supplied with month-end clamping; §3.6 **revise/mismatch** — re-designation guard hoisted above the `STRUCTURING` state check so an already-designated deal always reports `ERR_SALE_METHOD_CONFLICT`; §3.8 yield analysis returns exactly six `data` keys with no common properties; §3.9 award tests OS before the net-proceeds floor; §3.9 **revise/mismatch** — close ladder is OS->documents->handoff, not the narrated documents-first order; §3.9 cancel recomputes period counters to zero but deliberately leaves syndicate seats and undertakings untouched; §4 trailing slashes insignificant, `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED` transport fallbacks sit outside the §5 catalogue.

Verification: 27 hunks; 466->470 lines (+4, two intentional new paragraphs), 117,667->134,333 chars. Headings and table row counts unchanged.

### Pass 2 summary (calc/derive/orders/syndicate) — verbatim

Modules scanned: services/calc.py (18 behaviors incl. the full allotment waterfall), services/derive.py (14), routes/orders.py (11 endpoints / ~32 guards), routes/syndicate.py (2 endpoints / ~11 guards).

Counts: **16 ambiguity-pins, 4 mismatch-revisions, ~28 no-change confirmations.**

Notable changes: §2.5 tier 7 **revise/mismatch** — a `syndicate_member_id` naming no row reports `ERR_CROSS_DEAL_REFERENCE`, there being no member not-found error; §2.9 governing-statement `created_at` ties broken by creation sequence, last written governs, no statement at all => `PENDING` (carry-over 1); §3.2 semiannual yield/coupon, discount and annuity factors carried at full precision with only the final sum rounded; §3.3 hop four also clears `approved_by_user_id` to null; §3.6 seating has no deal-state precondition; §3.7 `closes_at` <= `opens_at` reports `ERR_ORDER_PERIOD_OVERLAP` tested before existing periods; §3.7 open tests period status -> deal state -> sibling-open; §3.7 **revise/mismatch** — order entry resolves tranche first then member; §3.7 close has no deal-state and no window precondition, tranches walked in `sequence_number` order; §3.7 available principal never negative; §3.7 residual ties broken by creation sequence in the waterfall and remainder walk; §3.7 every candidate order re-versioned including `UNFILLED`, `CANCELLED` untouched; §3.7 **revise/mismatch** — par recomputed for every tranche of the deal, re-versioning only movers; §3.7 reopen recomputes counters and never revives cancelled orders; §3.7 reopen reads null `takedown_per_bond_usd` as zero driving credits to 0.00; §3.7 order cancel checks order status -> period status -> window; §3.8 negotiated per-bond component total carried unrounded; §3.8 premium's insured set comes from the committed enhancement's `insured_tranche_ids` not `is_insured`, in `sequence_number` order (carry-over 2); §3.8 bond years unrounded, empty schedule => `arbitrage_yield_pct` 0.0000 / permitted 0.1250; §3.8 takedown credits gathered across every order period of the deal.

Verification: 41 total hunks (27 + 14 new hunk lines carrying 20 edits); pass 1's edits confirmed intact; 470 lines / 140,495 chars (+5,845 chars from pass 2, 0 new lines/sections).

Deliberately not pinned as unreachable: `calc.py:120` zero-par guard, `calc.py:242` no-progress break, and everything keyed on `SyndicateMember.status == "RESIGNED"` — no endpoint writes `RESIGNED`, so §3.6's `RESIGNED` prose describes a state the API cannot reach.

### Pass 3 summary (statements/undertakings/ratings/enhancements/closing) — verbatim

Modules scanned: routes/statements.py (11 endpoints / ~48 behaviors), routes/undertakings.py (3 endpoints / ~12), routes/ratings.py (10 endpoints / ~30), routes/enhancements.py (4 endpoints / ~22), routes/closing.py (4 endpoints / ~16).

Counts: **16 new diff hunks / 21 Edit calls — 18 ambiguity-pins, 2 mismatch-revisions, 1 widened universal claim; ~60 behaviors confirmed already uniquely pinned.**

Notable changes: §3.3 **revise/mismatch** — `premium_bps` floor was "strictly greater than zero", impl refuses anything below 1; §3.3 a >40-entry `insured_tranche_ids` fails tier 5 with `ERR_INVALID_REQUEST`, proposals not deal-status gated; §3.3 withdrawal's presentation sweep is unconditional and pushes no engagement to `INFO_REQUESTED`; §3.4 `is_preliminary` gates nothing; §3.4 statement creation refused on `CLOSED`/`CANCELLED` deal, listing ties break by descending `_seq`; §3.4 duplicate `section_code` -> `ERR_INVALID_REQUEST` tested before `parent_section_id` resolution; §3.4 section creation has no state guard and versions neither parent; §3.4 approve orders section-then-statement state tests; §3.4 submit-for-review's three-test order; §3.4 request-revision has no deal-status guard; §3.4 post-preliminary tests statement status before deal status; §3.4 post-final does not move the deal's `version`; §3.5 engagement creation not deal-status gated; §3.5 pinned-analyst test precedes the state test and passes vacuously while null; §3.5 `response_summary` validated then discarded, `latest_information_request` not cleared; §3.5 presentation window tests report `ERR_INVALID_REQUEST` before ownership/state; §3.9 **insert/mismatch** — closing-document execute runs its gates in narrated order (signatory-role before deal-status) and carries **no tier-8 ownership test** despite §2.5's universal wording; §3.9 `signatory_name` 1–120 non-blank, `waiver_reason` floor 1 no ceiling.

§2.4 carry-over resolution: enumerated every `db.touch(deal)` callsite repo-wide. Unconditional (15): `deals.py:137,181,290,334,353,408,463`; `statements.py:71,150,167,201`; `enhancements.py:124,164`; `orders.py:139,176`. Conditional (3): `statements.py:113,223,319`. Committed wording replaces "The single exception is…" with three sentences covering the §3.2/3.6/3.8/3.9 deal-level actions, the eight child-originated unconditional advances, and the exactly-three conditional writes. The 15+3 partition is exhaustive, so the universal claim is globally true.

Verification: 57 total hunks; NOT byte-identical to PRD_FINALIZED.md; 470 lines / 148,386 chars vs 466 / 117,667 (+0 lines this pass, all in-paragraph, +~7.9 KB); heading set identical; §4 73/73 pipe-rows; §5 66/66 error rows; passes 1 and 2's marker sentences present and unmodified.

### Orchestrator final verification

- `diff PRD_FINALIZED.md PRD_COMPLETED.md | grep -c '^[0-9]'` = **57** hunks; `cmp` reports DIFFERENT (the byte-identical no-op failure mode did NOT occur).
- Line/char progression: PRD.md 466/117,221 -> PRD_FINALIZED.md 466/117,667 -> PRD_COMPLETED.md 470/148,386.
- `diff` of the `^#` heading sets between PRD_FINALIZED.md and PRD_COMPLETED.md is empty — no sections added or removed.
- §5 error rows still 66. Grep for "scaffold|test_recipe|harder than" in PRD_COMPLETED.md returns 0 — no scaffold or difficulty-directive leakage into the final contract.

## Pipeline complete — 2026-09-05T01:00:00.000Z

All nine steps finished. Final state: 231/231 tests passing in all 8 parallel rounds of the stability sweep (`workspace/implementation/results.{1..8}.json`), 71/71 endpoints implemented, 114/114 non-stub design instances covered with zero test deletions, and `workspace/PRD_COMPLETED.md` written as the final aligned contract.
