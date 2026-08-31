# Worklog — task_2143_custom_grazing_pasture_rental

## Step 1: Create task directory — 2026-08-23T00:00:00.000Z

Created `tasks/task_2143_custom_grazing_pasture_rental/` and `tasks/task_2143_custom_grazing_pasture_rental/workspace/` (index 2143 = highest existing 2142 + 1).

## Step 3: Copy shared files — 2026-08-23T00:00:00.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (1424 bytes). Run ahead of Step 2's completion since it has no dependency on the scaffold.

## Step 2: Generate scaffold — 2026-08-23T04:45:00.000Z

All three artifacts are generated, lint-clean, and cross-verified.

## What was produced

`/home/ubuntu/github/CodingPRD/tasks/task_2143_custom_grazing_pasture_rental/`
- **`SCAFFOLD.yaml`** (§1.0–§1.7 + `concurrency_rules`) — 13 entities, 8 state machines, 2 OCC rules, 12 calculations, 27 ordered validations, 46 endpoints, 40 error codes, 4 roles
- **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 26 instances across all 9 §0.5 rules (min 2 each)
- **`SCAFFOLD_CORNER_DESIGN.yaml`** — 82 instances across all 9 claim-extraction-guide sections (15 are `excluded_because` stubs pointing at named §1.8 instances)

## Design shape
- **Profile:** ledger-reconciliation × multi-party-negotiation; `entity_topology: graph` (GrazingContract is a Grazier×CattleOwner×Pasture junction, Settlement a Contract×Lot×Consultant junction); `state_machine_shape: cyclic`; `role_model: segregation_of_duties`; layers = dual-variant calc, cascading side effects, rate/threshold triggers, OCC. Difficulty band `expert_plus`.
- **Signature mechanics:** dual-variant gain (`PROVISIONAL_PRORATED` 15096 lb vs `FINAL_ADJUDICATED` 15510 lb from identical scale tickets); dual-variant carrying capacity (DRY_MATTER 20769 head-days vs STOCKING_HISTORY 4250); the ISSUED→DISPUTED→ADJUDICATED→ISSUED negotiation cycle capped at 2 rounds; GrazingContract's parallel `lifecycle_status × billing_status` dimensions; InfrastructureTicket's fork where the OWNER-repair branch flips `owner_share_cents` negative.
- **Pinned traps:** lot-level shrink rounding (61514 vs the per-head 61500); round-per-treatment-then-sum (7627 vs 7626); the volume rebate keyed on the *pre-rebate* base (30176/1478624 vs 15088/1493712); half-open grazing windows + a 14-day rest buffer vs closed-inclusive drug-withdrawal intervals; capacity rejection at strict `>` (1000 == 1000 passes).
- Logical clock `POST /_clock/set_current_utc` declared with the mandated `2026-08-01T00:00:00Z` startup default.

## Verification performed
- `scaffold_lint.py` verdict, pasted verbatim:
```
Coverage
  §1.5 endpoints declared:    46
  §1.1 entities declared:     13
  §1.8 instances scanned:     26
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  1147

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
- Every formula-derived assertion was computed in Python with `Decimal`/`ROUND_HALF_UP` before being written as a literal (settlement totals, shrink weights, death-loss credits, capacity ratings, ADG tiers, rebate tiers, early-removal adjustments).
- Additional scripted checks, all zero-error: placeholder closure (`${var}` bound by an earlier `captures:`), capture-name uniqueness, name uniqueness across both design files, every `grounds:` reference resolving into §1.1–§1.7, every stub's `difficulty_instance` existing by name, no forbidden concurrency vocabulary, design keys absent from `SCAFFOLD.yaml`, all 40 error codes triggered by at least one design instance, and all 46 endpoints exercised.
- Hard constraint honored: no sibling `tasks/task_*/` directory was listed, read, or searched.

## Step 4: Generate PRD — 2026-08-23T05:05:00.000Z

The PRD is written and verified. Final state:

**Output:** `workspace/PRD.md` — 81 KB, ~11,500 words, ends at §5 with no audit footer.

**Structure** (domain-derived): §1 Introduction (3 paragraphs); §2 with 10 subsections (2.1 Parties/Identity Headers, 2.2 fixed verbatim envelope, 2.3 Listing & Pagination, 2.4 Record Identity/Audit/Version, 2.5 Units/Money/Rounding, 2.6 Stale-Parent Rejection, 2.7 Logical Clock, 2.8 The Order in Which Requests Are Rejected — the full 27-rule ladder, 2.9 Derived Aggregates & Cascade Discipline, 2.10 Grazing Posture); §3 with 9 lifecycle-ordered subsections (parties → pasture/capacity → contract formation → receiving/shrink → herd health → death loss → infrastructure → drought/early removal → settlement/dispute/closeout); §4 46-row endpoint table; §5 40-row error table.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 131 unique required (154 entries), 131 present, 0 missing
- endpoints[].request_body/input: 69 required, 69 present, 0 missing
- endpoints[].query_params: 28 required, 28 present, 0 missing
- path_params: 1 required (id), present
Status: PASS
(also verified: 4/4 role names, 40/40 error ids, all state values, all enum members present verbatim in backticks)
```

```
Rule coverage check:
- validations[] with priority: 27 checked, 27 expressed in prose (ordered ladder in §2.8 with error id + scope per rule), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 43 checked across 8 machines, 43 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed in prose (pinned rounding orders and worked contrasts: 61514 vs 61500 shrink, 7627 vs 7626 treatment sum, 30176/1478624 rebate keyed on the pre-rebate base, 15096 vs 15510 vs 15248 gain), 0 missing
- validations[] conditions: 27 checked, 27 matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: 27 endpoints with side effects checked, 27 expressed, 0 missing
- entities[].fields[] structured content: 154 entries checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 16 groups checked, 16 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 694
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 diffs byte-identical against `section-2.2-response-structure.md`.

**Flagged unbound scaffold constant.** `DISPUTE_WINDOW_DAYS` is referenced six times in `SCAFFOLD.yaml` but never bound to a number; the doc-generator pinned it at seven days.

### Orchestrator reconciliation (post-subagent)

Grepped the withheld design indices: `SCAFFOLD_CORNER_DESIGN.yaml:1104` asserts `DISPUTE_WINDOW_DAYS is 10` (issued_at 2026-11-11, dispute at 2026-11-22 → one day past boundary → `ERR_DISPUTE_WINDOW_CLOSED`), and `:1005` has a Grazier finalize at 2026-11-12 → `ERR_DISPUTE_WINDOW_OPEN`. The doc-generator's guess of 7 would have invalidated both corner instances.

Fixed by the orchestrator before Step 5:
- `workspace/PRD.md` — 4 sed replacements, seven → ten (§2.7 clock paragraph line 106; §3.9 lines 281, 283, 289).
- `SCAFFOLD.yaml` — bound the constant inline at all 6 reference sites as `DISPUTE_WINDOW_DAYS (= 10)`.

## Step 6: Generate implementation — 2026-08-23T05:32:00.000Z

The implementation is complete and verified.

## What was built

`workspace/implementation/`

| File | Role |
|---|---|
| `start.sh` | Guarded `pip install` (skipped once Flask is importable), `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `app.py` | Blueprint registration, error handlers, per-request store lock |
| `store.py` | Empty-on-boot in-memory store, UUIDs, audit fields, once-per-request `touch()`, logical clock (epoch `2026-08-01T00:00:00Z`) |
| `errors.py` / `envelope.py` | 40-code catalogue; `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination |
| `common.py` | Auth ladder (rules 1–3), body validators, ISO date helpers, `ROUND_HALF_UP` via `Decimal` |
| `derive.py` | Constants, capacity rating, posture precedence, pasture/owner recomputes + cascades, shrink, treatment split, death-loss sweep, infra allocation, window conflict, drought trigger |
| `money.py` | Settlement gain (3 methods), base charge (both billing modes), the 8-step waterfall |
| `routes/*.py` | All 46 endpoints across 7 modules |

## Verification

Three smoke suites (~130 assertions) run against the app; every PRD worked example reproduces exactly:

- DRY_MATTER 683.54 AUM / 20769 head-days; STOCKING_HISTORY 139.80 / 4250
- Lot-level shrink 63745 @ 3.5% → **61514** (not 61500)
- Round-per-treatment-then-sum → **7627** (not 7626)
- Death sweep 2/0 then 1/1 → **84000** credit; **0** under `OWNER_BEARS_ALL`
- Gain 15096 / 15510 / 15248 for provisional / adjudicated / midpoint
- Rebate keyed on pre-rebate base; ADG tiers; 250 lb/head gain cap
- Full cascades: drought destock (+15-day notice), critical-ticket `RESTRICTED` → `RECEIVING_HELD` → release, delinquency suspend/reinstate, finalize closeout
- Ladder ordering spot-checks (path-before-pagination, validation-before-ownership, stale-before-state), boundaries (14-day rest gap, forage 20.00 vs 20.01, dispute window ±1s, capacity equality)

Live boot through `bash start.sh` confirmed on a fresh process; store starts empty, no seeding anywhere.

## Judgement calls worth flagging

Three points where PRD/scaffold were silent or ambiguous:

1. **`POST /grazing/contracts` enforces that the acting grazier owns the named pasture** (`ERR_NOT_RESOURCE_OWNER`), per §2.1's blanket resource-scoped-write rule. Not explicitly listed in §3.3.
2. **Voiding a confirmed death loss while a live settlement exists** returns `ERR_SETTLEMENT_INVALID_STATE` (the report itself is in a legal state; the settlement is the blocker). `ERR_DEATH_LOSS_INVALID_STATE` was the other candidate.
3. **`receive` checks lot state before contract state** (rule 10 names the target resource first, contract as an add-on clause) — matches the scaffold precondition order; §3.4's prose lists them the other way.

Also: the logical clock renders whole-second instants without a fractional part (so the default reads exactly `2026-08-01T00:00:00Z` as §2.7 states), and `issued_at`/`dispute_opened_at` use the same renderer so they compare equal to `current_utc`. `created_at`/`updated_at` use wall clock with three fractional digits.

## Step 5: Generate unit tests — 2026-08-23T06:03:00.000Z

Test infrastructure and suite are generated and audited.

## What was built

**`test_helpers/`** (2,324 lines, 9 modules)
- `types.py` — 22 status/enum classes plus TypedDicts. The three append-only entities (`CapacityAssessment`, `DroughtReading`, `WeightEvent`) omit `updated_at`/`version` per PRD §2.4.
- `api_client.py` — 46 endpoint methods on `ApiClient(GenericApiClient)`, one per PRD §4 row.
- `api_errors.py` — all 40 error ids + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, `assert_pasture_invariants`, `assert_settlement_waterfall`, `assert_treatment_split_invariants`, and format-agnostic `assert_same_instant` / `assert_same_calendar_date` helpers.
- `factories.py`, `constants.py`, `test_users.py` (per-instance builders for all three entity-backed roles; identity threaded through every fixture).
- `fixtures.py` (952 lines) — 5 tiers, from single-call wrappers up to `setup_full_north_bench_settlement`, `setup_delinquency_world`, `setup_rest_buffer_world`, `setup_capacity_boundary_world`, `setup_two_contracts_two_liability_regimes`, `setup_gain_billed_lot`.

**`test_suite/`** — `conftest.py` + 10 domain-named files, **119 tests, all collecting cleanly**.

## Audit results

| Check | Result |
|---|---|
| Difficulty instances (26) with >=2 tagged tests | 26/26 PASS |
| Corner non-stub instances (67) with >=1 tagged test | 67/67 PASS |
| `excluded_because:` stubs translated | 0 of 15 (correct); all 15 cross-references resolve PASS |
| Untagged / dual-tagged / dangling tags | none PASS |
| PRD citations grepping verbatim (226 quoted spans, whitespace-normalised) | 226/226 PASS |
| `pytest.mark.skip` / `skipif` / `xfail` | none PASS |
| "scaffold" / §1.x / "Table N" leakage in emitted code | none PASS |
| pyflakes on emitted code | clean PASS |

## Judgement calls worth flagging

- **Two corner RBAC instances survived the two-reader test by elimination, not by direct PRD naming.** `grazier_cannot_approve_a_treatment_charge_only_void_it` and `range_consultant_cannot_void_a_confirmed_death_loss_report` assert `ERR_FORBIDDEN_ROLE` for a role-partitioned *decision* on an endpoint that lists both roles. PRD §3.5/§3.6 clearly say the decision is not that role's to make, but never name the code. Generated because the error catalogue is closed and no other code's stated trigger fits. These are the two most likely to fail against a faithful-but-divergent implementation.
- **Sub-assertions dropped under Silence patterns** rather than weakening tests: `signature_ref == null` on an unsigned contract, and `repair_cost_cents`/`owner_share_cents == 0` on an un-completed ticket — all `default-value` silences. Every instance retains its rule-bearing assertions.
- **Date/timestamp comparisons are instant-based, not string-based** (`assert_same_instant`, `assert_same_calendar_date`), since the PRD pins ISO 8601 but not the exact serialisation of body-supplied dates.
- `DISPUTE_WINDOW_DAYS = 10` is bound in `constants.py` and exercised at both boundaries (grazier finalize at +1 day → `ERR_DISPUTE_WINDOW_OPEN`; dispute at +11 days → `ERR_DISPUTE_WINDOW_CLOSED`).

All arithmetic in the expected values was re-derived independently from the PRD formulas and matches the design indices (shrink 61514, treatment sum 7627, rebate 30176/1478624, gain 15096 vs 15510, midpoint 13728, death credit 84000, capped gain 270000, min-days floor 228000).

## Step 7: Run tests and iterate — 2026-08-23T06:35:00.000Z

Storage is in-memory dicts only, no seeding, no on-disk persistence.

## Summary

**Iterations run: 2** (baseline sweep + verification sweep, 8 parallel rounds each).

**Result: 119/119 passing in all 8 rounds of the final sweep.**

### Baseline
All 8 rounds returned an identical **117/119** — fully deterministic, no flakiness. The union of failures was exactly the two tests the test generator had pre-flagged as risky:

| Test | Expected | Actual |
|---|---|---|
| `test_a_grazier_may_void_a_treatment_charge_but_not_approve_it` | `ERR_FORBIDDEN_ROLE` | `ERR_TREATMENT_INVALID_STATE` |
| `test_a_range_consultant_may_not_void_a_confirmed_death_report` | `ERR_FORBIDDEN_ROLE` | `ERR_DEATH_LOSS_INVALID_STATE` |

### Diagnosis (STEP 1a/1b)
Both failed **unique derivability**, via the *error-precedence silence* pattern.

`ERR_FORBIDDEN_ROLE` has exactly one verbatim trigger in the PRD (§2.1, echoed as ladder rule 2): *"A request whose role is well-formed but is not listed as an authorized role **for the endpoint being called**."* The §4 endpoint table lists `CattleOwner, Grazier` for `/grazing/treatments/{id}/review` and `RangeConsultant, Grazier` for `/grazing/death-losses/{id}/review` — so in both tests the acting role **is** authorized for the endpoint, and that trigger does not literally fire. The PRD never states which code a *role-mismatched decision* on an endpoint the role is authorized for produces.

Two PRD-faithful readings exist, so both could be articulated — the deletion/relaxation criterion:
- **Reader A** (the implementation): role passes ladder rule 2; the decision is not a declared transition for this actor, so rule 10 fires → `ERR_*_INVALID_STATE`.
- **Reader B** (the test): approving/voiding is the other party's decision, so the role is forbidden → `ERR_FORBIDDEN_ROLE`.

Neither test was deleted outright, because each also carries assertions that **are** verbatim-covered — so STEP 1c splitting applied instead.

### Fixes applied to `test_suite/`
`test_suite/test_10_access_control_and_listings.py` — the only file changed:
1. Added `validate_error_is_one_of` to the imports.
2. `test_a_grazier_may_void_a_treatment_charge_but_not_approve_it` — relaxed the exact-code assertion to `validate_error_is_one_of([ERR_FORBIDDEN_ROLE, ERR_TREATMENT_INVALID_STATE])`. The PRD-covered half is retained exactly: the grazier's `VOID` succeeds with `status == "VOIDED"` (PRD §3.5 verbatim).
3. `test_a_range_consultant_may_not_void_a_confirmed_death_report` — relaxed to `validate_error_is_one_of([ERR_FORBIDDEN_ROLE, ERR_DEATH_LOSS_INVALID_STATE])`. The PRD-covered assertions are retained exactly: report stays `CONFIRMED`, `confirmed_death_head == 2`, and `stocked_head_count == 148` (PRD §2.9's conservation rule, 150 − 2).

Each docstring now cites the competing PRD sentence and records why the code choice is not uniquely derivable.

This used the explicitly permitted exception to the no-weakening rule (relaxing to `validate_error_is_one_of` where the PRD does not pin the specific choice). No assertion was downgraded to a bare HTTP-status check, and no `skip`/`xfail` was added anywhere — verified by grep across `test_suite/`.

### Fixes applied to `test_helpers/`
**None.** No fixture, factory, or role-header builder constructed a precondition inconsistent with the PRD; both failures were pure error-code-choice disputes, not setup bugs.

### Fixes applied to `implementation/`
**None.** The implementation's readings were PRD-faithful under ladder rules 2 and 10, so STEP 3 was never reached — per the cardinal rule, the implementation must not be changed to satisfy a non-derivable assertion. All three impl judgement calls flagged by the generator (pasture-ownership on contract creation, `ERR_SETTLEMENT_INVALID_STATE` on voiding a confirmed death loss under a live settlement, and lot-state-before-contract-state in `receive`) went unchallenged by any test and were left as-is.

Final verification confirms the store boots empty with in-memory dicts only — no SQLite, no JSON dump, no `/tmp` cache, no seeding. Transient `results.*.json` files were removed from `implementation/`.

### Deletions
**None.**

## Step 8: Finalize PRD — 2026-08-23T06:50:00.000Z

Produced `workspace/PRD_FINALIZED.md`.

## Size delta

| | lines | words | chars |
|---|---|---|---|
| PRD.md | 391 | 11,471 | 78,707 |
| PRD_FINALIZED.md | 391 | 11,688 | 80,176 |
| delta | 0 (+0.0%) | +217 (+1.89%) | +1,469 (+1.87%) |

All five edits are inline insertions into existing paragraphs; no new sections, no new lines, no prose removed except two re-scoped clauses.

## Changes

- **§3.5 (treatment review)** — insert — a cross-constituency `decision` on `/grazing/treatments/{id}/review` (Grazier submitting `APPROVE`/`DISPUTE`, CattleOwner submitting `VOID`) yields `ERR_TREATMENT_INVALID_STATE`, never `ERR_FORBIDDEN_ROLE`, because both roles are authorized for the endpoint — `routes/health.py:80,97-105`
- **§3.6 (death-loss review)** — insert — same rule for `/grazing/death-losses/{id}/review`: RangeConsultant submitting `VOID`, or Grazier submitting `CONFIRM`/`REJECT`, yields `ERR_DEATH_LOSS_INVALID_STATE`, never `ERR_FORBIDDEN_ROLE` — `routes/health.py:165,180-188`
- **§3.6 (death-loss void guard)** — revise — the void-while-settled guard now names its code `ERR_SETTLEMENT_INVALID_STATE`, is stated over *every* settlement on the lot (impl loops all), and is pinned as reached only after the `CONFIRMED → VOIDED` transition itself is found declared — `routes/health.py:190-194`
- **§3.3 (contract drafting)** — insert — the acting grazier must own the pasture named by `pasture_id` or the draft is refused `ERR_NOT_RESOURCE_OWNER` at ladder rule 8 — `routes/contracts.py:61-64`
- **§3.4 (receiving)** — insert — within ladder rule 10 the lot's own status is checked before the contract's `lifecycle_status`, so a non-`SCHEDULED` lot reports `ERR_LOT_INVALID_STATE` even when the contract is also not `ACTIVE` — `routes/lots.py:103-106`

## Per-edit pre-edit search log

**1. Treatment cross-constituency decision**
- (a) Subject: which error code a role-authorized but wrong-constituency review decision produces.
- (b) Enumerated: `routes/health.py:78-111` (the only writer of `treatments.status`); `common.py:40-54` `authenticate()` (the sole `ERR_FORBIDDEN_ROLE` site — fires only on roles outside the endpoint's tuple); `req_enum` (decision outside `APPROVE|DISPUTE|VOID` → `ERR_VALIDATION`, rule 7, earlier); ownership check at `health.py:90-93` (rule 8, earlier); grepped for other treatment-status mutations — none. Also read the two parallel dual-role endpoints: `routes/infrastructure.py:114-136` (grazier/owner completing the wrong branch → `ERR_TICKET_INVALID_STATE`, same shape) and `routes/contracts.py:172-206` (early removal, where a role/reason mismatch instead yields `ERR_EARLY_REMOVAL_NOT_PERMITTED`).
- (c) Because early-removal is the counter-example, the sentence was kept **local to the treatment review endpoint** rather than generalized into §2.8, and phrased as "clears rule 2 … and is caught by the same rule 10" so rules 3–9 (notably ownership, rule 8) are not implied to be skipped.

**2. Death-loss cross-constituency decision**
- (a) Subject: same, for death-loss review.
- (b) Enumerated: `routes/health.py:163-203` (sole writer of `death_losses.status`); `authenticate(("RangeConsultant","Grazier"))` at `:165`; grazier-only ownership check at `:175-176` (consultants intentionally exempt — PRD already says so, left untouched); `derive.death_loss_sweep` / `recompute_pasture` cascade at `:201-202` (unaffected by the error-code wording).
- (c) Same localization; no general claim added to §2.8.

**3. Death-loss void settlement guard**
- (a) Subject: the "settlement must be DRAFT or VOID" precondition on `CONFIRMED → VOIDED`.
- (b) Enumerated: `routes/health.py:190-194` (loops **all** `settlements_of_lot`, rejects on any status outside `DRAFT`/`VOID`); `derive.settlements_of_lot`; `routes/settlements.py` void/finalize paths that produce `VOID`/`FINAL` statuses; confirmed no other site raises `ERR_SETTLEMENT_INVALID_STATE` against a death-loss operation.
- (c) Widened PRD's singular "the lot's settlement, if one exists at all, is in DRAFT or VOID" to "the lot's settlements, if any exist at all, are every one of them in `DRAFT` or `VOID`", matching the loop; and explicitly ordered the guard *after* the transition check so the sentence cannot be read as pre-empting `ERR_DEATH_LOSS_INVALID_STATE`.

**4. Contract drafting pasture ownership**
- (a) Subject: ownership of the body-supplied `pasture_id` on `POST /grazing/contracts`.
- (b) Enumerated: `routes/contracts.py:29-96` (check at `:61-64`, after body validation, before any derivation); the parallel body-`pasture_id` endpoint `routes/infrastructure.py:28-53` (grazier→pasture owner, owner→contract owner, also `ERR_NOT_RESOURCE_OWNER`); `routes/pastures.py` path-scoped grazier checks; §2.1's existing general statement.
- (c) Scoped the clause to the contract draft only (not a general body-identifier rule), so the ticket endpoint's dual grazier/owner ownership fork is neither narrowed nor restated.

**5. Receive ordering, lot state before contract state**
- (a) Subject: relative order of the two rule-10 state checks on `POST /grazing/lots/{id}/receive`.
- (b) Enumerated: `routes/lots.py:89-136` (lot `:103-104`, contract `:105-106`, posture `:108-111`); the two sibling endpoints that could be mis-swept by a broader claim — `routes/lots.py:29-47` `book_lot` (contract state only, then posture) and `routes/lots.py:139-157` `record_weight_event` (lot state only, no contract-state check).
- (c) Confined the sentence to receiving instead of stating a system-wide lot-before-contract precedence, which would have mis-described `book_lot`, and left the posture check (rule 12) unmentioned so its existing placement stands.

## Step 9: Complete PRD — 2026-08-23T06:05:00.000Z

`workspace/PRD_COMPLETED.md` is written.

## Deltas

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| Lines | 391 | 391 (unchanged — every edit is in-paragraph) |
| Words | 11,688 | 12,364 (+676) |
| Chars | 80,176 | 84,833 (**+4,657**) |

Section headings and both tables (§4 endpoints, §5 errors) are byte-identical; 24 paragraphs touched, no new sections, no new paragraphs.

**Counts: 25 changes — 23 ambiguity-pins, 2 mismatch-revisions.**

## Changes

- §2.3 Listing and Pagination — revise — ambiguity — creation-order ties broken by server write sequence; drought readings tie later-written-first, scale tickets earlier-written-first — `derive.py:54`, `pastures.py:325`, `lots.py:443`
- §2.4 Audit Fields — insert — ambiguity — `version`/`updated_at` advance at most once per request however many cascades touch a record — `store.py:92-106`
- §2.5 Units and Money — insert — ambiguity — which numeric fields are integer-only on input vs. accept any JSON number — `common.py:110-152`
- §2.7 Logical Clock — insert — ambiguity — clock-rendered instants omit the fractional part on a whole second; clock `data` carries `current_utc` alone — `store.py:62-72`, `parties.py:91`
- §2.10 Grazing Posture — insert — ambiguity — the RECEIVING_HELD/SCHEDULED sweeps fire only when a recompute actually changes the posture — `derive.py:223-234`
- §3.2 Capacity Assessment — **revise** — **mismatch** — under `STOCKING_HISTORY` the dry-matter figure is not "ignored entirely": it is still range-validated if present and stored on the row (0 when omitted) — `pastures.py:225-229,246`
- §3.2 Capacity Assessment — insert — ambiguity — a `CLOSED` pasture cannot be assessed; `ERR_PASTURE_INVALID_STATE` — `pastures.py:235-237`
- §3.3 Contract Formation — insert — ambiguity — `signature_ref`, `early_removal_reason`, `early_removal_effective_date` start null — `contracts.py:88,92-93`
- §3.4 Lot Booking — insert — ambiguity — the eight zeroed and three null receiving/weigh-out fields on a fresh lot — `lots.py:286-297`
- §3.4 Receiving — insert — ambiguity — the response body is the updated lot, not the `IN` weight record — `lots.py:368`
- §3.4 Scale Tickets — insert — ambiguity — `INTERIM` and `OUT` may only be posted while the lot is `ON_FEED` or `REMOVAL_SCHEDULED`; else `ERR_LOT_INVALID_STATE` — `lots.py:386-388`
- §3.5 Treatments — insert — ambiguity — a treatment may be recorded whatever status the lot and contract hold (no state guard) — `health.py:25-63`
- §3.5 Treatments — insert — ambiguity — `review_note` starts null — `health.py:59`
- §3.5 Treatment Review — insert — ambiguity — an omitted `note` leaves the stored `review_note` standing rather than clearing it — `health.py:108-109`
- §3.6 Death Loss — insert — ambiguity — `review_note` starts null — `health.py:144`
- §3.6 Death-Loss Review — insert — ambiguity — omitted `note` is non-clearing — `health.py:197-198`
- §3.7 Infrastructure Tickets — insert — ambiguity — fresh-ticket nulls/zeros — `infrastructure.py:266-273`
- §3.7 Infrastructure Tickets — insert — ambiguity — ownership pairing on open **and** complete: Grazier↔pasture, CattleOwner↔contract — `infrastructure.py:253-256,330-333`
- §3.7 Infrastructure Tickets — insert — ambiguity — the contract need not be booked on the named pasture; both ids are existence-checked only — `infrastructure.py:237-252`
- §3.8 Drought Cascade — insert — ambiguity — the +15-day effective date is rendered in the shape `reading_date` arrived in — `common.py:206-214`, `derive.py:448`
- §3.8 Early Removal — **revise** — **mismatch** — the `min_days` floor is tested against *every* received lot on the contract, not one lot; un-received lots are skipped — `contracts.py:192-198`
- §3.8 Early Removal — insert — ambiguity — the third branch (nothing on the ground but a `WEIGHED_OUT` lot exists) is refused with `ERR_CONTRACT_INVALID_STATE` — `contracts.py:228-230`
- §3.9 Settlement Draft — insert — ambiguity — the nine null fields on a fresh draft; the waterfall runs at draft time; no lot-`WEIGHED_OUT` check and no lot↔contract membership check — `settlements.py:78-111`
- §3.9 Average Daily Gain — insert — ambiguity — divisor is the settlement's snapshotted `days_on_feed` (not the lot's live value), and ADG is 0 when head-out or days-on-feed is 0 — `money.py:53-56,72-74`
- §3.9 Adjudication — insert — ambiguity — the `resolution` value is itself stored on the settlement — `settlements.py:216`

## Notes

- The §2.8 rejection ladder was verified endpoint-by-endpoint against all 46 handlers; impl ordering matches the PRD's stated ladder everywhere, so no ladder edits were needed.
- Verified-and-unchanged (PRD already pins uniquely): all rounding sites, the two capacity methods, the shrink order-of-operations, the death-loss chronological sweep, the infrastructure cost fork's sign convention, the drought persistence/severity conditions, the gain methods, the base-charge tiers, and the pre-rebate-base tier trap.
- Tests were used only as auxiliary cross-reference; implementation was the sole alignment target.

## Final verification sweep (orchestrator) — 2026-08-23T06:30:00.000Z

Step 7 removed its transient `results.*.json` on exit, so the orchestrator re-ran the 8-round sweep to regenerate the required artifacts and independently confirm green:

```
results.1.json 119 / 119
results.2.json 119 / 119
results.3.json 119 / 119
results.4.json 119 / 119
results.5.json 119 / 119
results.6.json 119 / 119
results.7.json 119 / 119
results.8.json 119 / 119
```

All 8 rounds pass under `--isolation per-test-server`. Pipeline complete.
