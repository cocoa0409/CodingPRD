# Worklog — task_2864_hotel_group_sales_room_block_management

## Step 1: Create task directory — 2026-09-05T08:15:14.727Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2864_hotel_group_sales_room_block_management/` and its `workspace/` subdirectory. Index 2864 was pre-assigned by the invocation; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-05T09:57:00.000Z

All three scaffold artifacts are complete and the lint is clean.

Verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2864_hotel_group_sales_room_block_management/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2864_hotel_group_sales_room_block_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2864_hotel_group_sales_room_block_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     49
  Calls scanned (§1.8+§1.9):  1295

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all absolute):
- `/home/ubuntu/github/CodingPRD/tasks/task_2864_hotel_group_sales_room_block_management/SCAFFOLD.yaml` — 2904 lines (149 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2864_hotel_group_sales_room_block_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2605 lines (160 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2864_hotel_group_sales_room_block_management/SCAFFOLD_CORNER_DESIGN.yaml` — 5794 lines (299 KB)

SCAFFOLD.yaml (§1.0–§1.7 only; verified it contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`): 13 entities, 9 state machines, 4 `concurrency_rules`, 13 calculations, 32 ordered validations, 54 endpoints, 51 errors, 7 roles (SalesManager, RevenueManager, ContractAdmin, ReservationsAgent, AccountingClerk, GroupContact `entity_backed:GroupAccount`, SystemOperator). `domain_name: hotel-group-sales`, `api_prefix: /group-sales`, archetypes quota_allocation + ledger_reconciliation, role_model segregation_of_duties, consistency_model immediate.

Design indices:
- §1.8 `scaffold_difficulty_design`: 18 instances = 9 rule_ids × 2 (dual_variant_calc, multi_step_calc_chain, cyclic_state_machine, parallel_state_dimensions, cascade_depth_4plus, priority_pair_validation_conflict, boundary_condition_cluster, cross_entity_gating, conservation_invariant).
- §1.9 `scaffold_corner_design`: 72 instances across all 9 guide sections — entities 10, state_machines 13, calculations 12, validations 19, endpoints 4, errors 2, rbac 4, cross_cutting_complexity_layers 7, consistency_model 1. Of these, 49 carry full `test_recipe`s and 23 are `excluded_because` stubs, every stub naming an existing §1.8 instance; no instance name is duplicated across the two files.

Coverage checks I ran beyond the linter: all 54 declared endpoints are exercised by at least one recipe call (the last two gaps, `GET /group-sales/contracts` and `GET /group-sales/room-blocks/{id}/reservations`, were closed by extending the reverse-lookup instance), and all 51 catalog error ids appear in the design files — ~45 through recipes, the remaining 6 (ERR_GROUP_CEILING_EXCEEDED, ERR_BLOCK_ALLOTMENT_EXCEEDED, ERR_FUNCTION_SPACE_CONFLICT, ERR_DISPLACEMENT_NOT_APPROVED, ERR_EVENT_NOT_CONCLUDED, ERR_BLOCKS_NOT_CUT_OFF) via an errors stub that points at the §1.8 scenarios that trigger them. Each of the four §1.2.1 OCC rules has its own dedicated 412 instance with a stale-token leg plus a refreshed-token control leg.

One small prose fix applied to SCAFFOLD.yaml: `Reconciliation.prepared_by_user_id` said "X-User-ID of the ContractAdmin"; the create endpoint is AccountingClerk-only, so the description now says AccountingClerk.

One thing for you to decide: per your instruction the `scenario:` key holds the input verbatim, so line 9 is still `Generate task harder than expert level!`. If your pipeline strips that directive before PRD generation (it otherwise leaks into PRD.md), that removal is still pending.

**Orchestrator post-step action:** removed the `Generate task harder than expert level!` line (and its trailing blank line) from the `scenario:` block of SCAFFOLD.yaml so the difficulty directive cannot reach the doc generator or PRD.md. SCAFFOLD.yaml is now 2902 lines; `grep -rn "harder than expert"` over the task dir returns nothing.

## Step 3: Copy shared files — 2026-09-05T09:58:22.389Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T10:14:00.000Z

PRD complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2864_hotel_group_sales_room_block_management/workspace/PRD.md` — 541 lines, 115,689 bytes. Written incrementally (Write + heredoc appends), every append verified with `wc -l` + `tail`. No truncation; file ends on a genuine section boundary (the last row of the §5 error table, terminated by a newline).

**Sections**
- `# Hotel Group Sales API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC · 2.2 API Response Structure (verbatim from the skill's fixed contract) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Money, Room Nights and Rounding Discipline · 2.7 Version Guards on Parent Records · 2.8 Rejection Precedence (all 32 priorities, ordered, with `applies_to` scopes and error IDs) · 2.9 House Inventory Conservation and the Group Ceiling · 2.10 Cascade Integrity Across the Contract Tree · 2.11 Nested and Filtered Resource Retrieval
- `## 3. Business Logic & Workflows` — 3.1 Client Organizations, the House Calendar, and Concession Design · 3.2 Lead Capture, Qualification Scoring, and Meeting Space · 3.3 Displacement Review and the Clearing Decision · 3.4 Rate Quoting and the Negotiation Cycle · 3.5 Papering and Countersigning the Group Contract · 3.6 Room Blocks, Sub-Blocks, and Rooming-List Pickup · 3.7 Cutoff, Release, and Attrition Exposure · 3.8 Ancillary Revenue and the Contract Receivable · 3.9 Post-Event Settlement, Cancellation, and Force Majeure
- `## 4. API Endpoint Definitions` — 54 rows, exactly 4 columns
- `## 5. Error Code Catalogue` — 51 rows, exactly 2 columns

**Hard Contract results (reported here only; PRD.md carries no audit footer — verified)**
- **Contract 1 Field-Name Coverage — PASS.** 136 required identifiers extracted mechanically from `entities[].fields[].name` plus every endpoint `input` token (`?` stripped); all 136 appear verbatim inside backticks. Diff run against a freshly regenerated required-set in `/tmp/prd_bench_2864_prdgen/required.txt`; missing = 0.
- **Contract 2 Rule Coverage — PASS.** All 51 error IDs appear in §1–§3 prose (not merely the §5 table). All 56 declared state transitions covered (22 are rendered as prose rather than `A → B` literals — e.g. block releases, the billing-status axis, the quote WITHDRAWN/EXPIRED cascades — each verified by hand). All 13 calculations present with every scaffold constant reproduced (`0.85`, `0.25`, `0.02`, `2,000,000`, `0.05`, `0.50`, `730`, `1500`/`400`, the four segment multipliers, the 45-minute turnover, the 180/90/30 tiers). All 4 OCC rules with their guard fields and 412 error IDs. No pseudocode operators (`==`, `>=`, `:=`, `min(`, `ceil(`, …) remain — the one `>=` that leaked in via a copied endpoint description was prose-ified. No fuzzy words ("approximately"/"roughly"/"conservatively") and no difficulty-directive leak.
- **Contract 3 §3 Path Purity — PASS.** Scanned every backtick token in lines 195–423: zero start with `/`, zero are bare HTTP methods, zero are method+path pairs.

**Notes for the caller**
- The forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced. Incidentally, `/tmp/prd_bench_2864/` already contained a `gen_corner.py` from another agent on this task; I left it untouched and did all my own scratch work in `/tmp/prd_bench_2864_prdgen/`.
- Two scaffold self-contradictions were resolved in favour of the state machine + entity-field tables (which corroborate each other several times), and the §4 table descriptions were edited to match so the implementer sees one story: (1) countering a quote **retains** the hold and does **not** advance `negotiation_round` (the endpoint blurb claimed it releases the hold); (2) propose is admissible from `DRAFT` only and revise from `COUNTERED` only (the endpoint blurbs said "DRAFT or COUNTERED" for both). A third blurb saying cancel releases blocks "to CLOSED" is superseded by §3.9's `RELEASED`, per the state machine.

**Orchestrator truncation check (per invocation instruction):** independently verified — `wc -l` = 541, `tail -12` ends with the `ERR_ACCOUNT_CREDIT_HOLD | 402` table row (a complete row, not a mid-sentence cut), and all five `##` sections are present at lines 3/11/195/424/485. No regeneration needed. `grep -in "harder than expert|expert level"` over PRD.md returns nothing.

## Step 6: Generate Implementation — 2026-09-05T10:52:00.000Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message, so Step 6 is recorded first because it finished first; the Step 5 entry follows below.)

Implementation complete and smoke-verified. All smoke servers are shut down (killed by exact PID/port only — no broad `pkill` was ever run), and the port is free.

## Files (`.../task_2864_hotel_group_sales_room_block_management/workspace/implementation/`)

| File | Lines |
|---|---|
| `app.py` | 54 |
| `core.py` | 667 |
| `logic.py` | 937 |
| `serialize.py` | 263 |
| `routes/__init__.py` | 13 |
| `routes/catalog.py` | 168 |
| `routes/leads.py` | 250 |
| `routes/quotes.py` | 232 |
| `routes/contracts.py` | 241 |
| `routes/blocks.py` | 213 |
| `routes/reservations.py` | 163 |
| `routes/billing.py` | 198 |
| `start.sh` | 9 (mode 755) |
| `requirements.txt` | 1 |

3399 lines of Python. `python3 -m py_compile` on every module: COMPILE_OK. Storage is in-process dicts only (`core.Store`); nothing is seeded, persisted, or read from disk; the logical clock starts at `2026-08-01T00:00:00Z`.

## Endpoints: 54 — exact match to the PRD

I extracted the PRD §4 endpoint table and diffed it against Flask's `url_map` (path params normalised): **the two sets are byte-identical, 54 rows each**. No extra routes, none missing.

## Smoke results

`start.sh` cold-booted three consecutive times on port 28641 with `__pycache__` removed; each boot answered `POST /_clock/set_current_utc` with 200 within 3s, and each was killed by its exact listener PID. It reads `$PORT` (default 8000 fallback), binds `0.0.0.0`, and `exec`s in the foreground, so the harness's per-test kill/relaunch cycle is satisfied.

Beyond the earlier 7 envelope/RBAC checks (201 create, 403 `ERR_UNAUTHORIZED`, 401 `ERR_UNAUTHENTICATED`, 400 bad enum, 404 `ERR_ACCOUNT_NOT_FOUND`, 400 on `limit=101` never clamped, 200 clock set), I ran two scripted chains against fresh processes; both ended CLEAN with every status code and every derived figure matching my hand-computed PRD expectation.

Chain 1 (60 calls, full lifecycle): qualify score 68 (57 raw × 1.20 CORPORATE) and value 2,945,850 (two-stage rounding); function-space 45-minute turnover conflict → 409; SoD 403, stale-version 412, replay 409 on `decide`; effective net rate 20,880; propose held 60 rooms, revise-down adjusted the hold to 55 and returned PROPOSED at round 2; countersignature released holds and committed 55/50/45, confirmed the space hold, and minted the master block with `cutoff_date = 2026-10-11`; sub-block carve shrank parent `rooms_open` 55→45 with 409 overdraw and 422 out-of-range guards; reservation derivation, duplicate 409, `ERR_STAY_DATE_OUTSIDE_BLOCK` 422; cutoff released 137 room nights and cascaded into the OPEN sub-block; settlement produced damages 1,973,187 / rebate 2,250 / total 2,784,809, finalize gated by SoD then one-shot 409; account re-tiered to 0.03 and decayed back to 0.01 after moving the clock past the 730-day lapse window.

Chain 2 (cascades): comp ratio 2 awarded guests 2 and 4, and cancelling guest 1 **moved** the comp onto guest 3 with `rate_cents` flipping 20000↔0 (re-derived from scratch, as §3.6 requires); cancel on an OPEN block returned the room (`rooms_picked_up` 3, `rooms_open` 7); attrition waiver stuck and drove settlement damages to 0 (would have been 320,000 unwaived), finalize then moved the block to SETTLED/CLOSED; `CLIENT_CANCEL` gave damages 160,000 (16 unsold room nights × 20,000 × 0.50 tier), kept posted ancillary at 200,000, released all blocks (20 room nights, pickup → 0), cancelled every reservation and handed inventory back to 0; `FORCE_MAJEURE` under a STANDARD clause returned damages 0 / posted 0 / receivable exactly 0 with the charge VOIDED; pagination rejected `limit=0` and `offset=-1` with 400.

One PRD subtlety worth flagging as intentional, since it looks like a leak at first glance: after cutoff, a stay date's `committed_group_rooms` retains the rooms carved into sub-blocks, because PRD §3.5 states "a **sub-block** release moves no inventory-day figure at all". The implementation follows the PRD, and the only two test-script bugs found were mine (`AV` instead of `AUDIOVISUAL`, and a state-carryover assertion), not implementation defects.

## Step 5: Generate Unit Tests — 2026-09-05T11:39:00.000Z

Done. All 18 test files plus infrastructure are at the task root (siblings of `workspace/`); nothing was written under `workspace/`, and `workspace/implementation/` was never read.

## Files

`/home/ubuntu/github/CodingPRD/tasks/task_2864_hotel_group_sales_room_block_management/test_helpers/`
| file | lines |
|---|---|
| `__init__.py` | 255 |
| `api_client.py` | 588 |
| `api_errors.py` | 134 |
| `assertions.py` | 282 |
| `constants.py` | 103 |
| `factories.py` | 403 |
| `fixtures.py` | 695 |
| `test_users.py` | 92 |
| `types.py` | 400 |

`.../test_suite/`
| file | lines | tests |
|---|---|---|
| `conftest.py` | 80 | – |
| `test_01_displacement_variant_economics.py` | 202 | 4 |
| `test_02_rate_and_settlement_arithmetic.py` | 204 | 4 |
| `test_03_negotiation_and_block_state_paths.py` | 255 | 4 |
| `test_04_signature_and_cutoff_cascades.py` | 269 | 4 |
| `test_05_rejection_precedence_pairs.py` | 238 | 4 |
| `test_06_threshold_boundaries.py` | 222 | 4 |
| `test_07_cross_entity_gates.py` | 176 | 4 |
| `test_08_inventory_and_space_overlap.py` | 319 | 4 |
| `test_09_conservation_and_compensation.py` | 314 | 4 |
| `test_10_entity_shapes_and_defaults.py` | 366 | 9 |
| `test_11_state_machine_edges.py` | 498 | 9 |
| `test_12_calculation_variants.py` | 415 | 5 |
| `test_13_validation_rules_part_one.py` | 628 | 8 |
| `test_14_validation_rules_part_two.py` | 374 | 5 |
| `test_15_endpoints_and_error_envelope.py` | 310 | 4 |
| `test_16_role_access.py` | 217 | 4 |
| `test_17_version_guards.py` | 316 | 4 |

Total 8,355 lines; **84 tests**, every one carrying exactly one verbatim `Design:` tag.

## Coverage
- **Queue A (§1.8 difficulty):** 18 live instances, 0 stubs → **18/18 translated**, 36 tests (exactly 2 per instance).
- **Queue B (§1.9 corner):** 49 live instances (the 23 `excluded_because:` stubs untranslated by design) → **48/49 translated**, 48 tests. Sections covered: entities 9, state_machines 9, calculations 5, validations 13, endpoints 3, errors 1, rbac 4, cross_cutting_complexity_layers 4, consistency_model 0.

## Skipped (1)
`Corner/consistency_model/every_cascaded_write_is_visible_in_the_response_that_caused_it` — its setup is refused by the PRD, so the asserted outcomes are not derivable. It needs two quotes on one lead simultaneously holding rooms (a PROPOSED sibling of 2 rooms plus a proposed 4-room quote, `held_group_rooms` 6 on every night). But PRD 3.4 admits a proposal "only when the quote is in `DRAFT`, the lead's `status` is `CLEARED`", and proposing moves the lead `CLEARED → QUOTED`; the only route back to `CLEARED` is the upward revise, which itself drops the quote to `DRAFT` and releases its hold, and PRD 3.4 further has a newer quote withdraw any `DRAFT` sibling at creation time. So hop 4 of the accept cascade (a `PROPOSED`/`COUNTERED` sibling releasing its hold) is unreachable except through the REJECT cascade, which is already covered by `Corner/state_machines/reject_decision_withdraws_the_quote_and_unwinds_both_holds` in `test_11`. Per the skip rule I did not weaken it to a `DRAFT`-sibling variant.

## Notes
- One PRD-first correction made while writing `test_15`: the design index treated the block-nights `to_date` window as inclusive, but PRD 2.3 and PRD 4 declare "`from_date` … inclusive and a `to_date` … exclusive", so the test asserts the half-open window (`2026-11-10` → `2026-11-11` returns exactly the 11-10 night).
- Verification: `py_compile` clean on all files; an AST check confirms every imported `test_helpers` name and every `api.<method>` call resolves; a tag checker cross-loads both design YAMLs and reports `tags OK`, 84 tagged tests, 0 unknown tags, 0 stubs translated, difficulty `untranslated=0 under-covered=[]`, corner `untranslated=1` (the documented skip). No occurrence of "scaffold" or any scaffold section reference in any docstring or comment. `__pycache__` removed; `worklog.md` untouched.

**Orchestrator placement check:** `test_helpers/` and `test_suite/` are both at the task root; `find workspace -name test_helpers -o -name test_suite` returns nothing. 18 test files, 84 `def test` functions, 84 `Design:` tags — counts agree.

## Step 7: Run Tests and Iterate — 2026-09-05T12:24:00.000Z

All 8 rounds are green. Final report:

## Iterations run: 2

### Iteration 1 — 79/84 in all 8 rounds (5 deterministic failures, identical in every round)

No test was deleted — every failing test's rule was verbatim-covered by PRD.md and uniquely derivable.

### Fixes to `implementation/`

| File | Function | Why |
|---|---|---|
| `workspace/implementation/routes/billing.py` | `post_charge` | PRD §2.7 verbatim: "an attrition waiver or **a newly posted ancillary charge bumps the contract's `version`**, so a stale writer would settle on numbers that no longer hold." Posting recomputed the receivable but never touched the contract, so `test_17…stale_contract_view_is_refused` saw version 3 → 3 and the whole `expected_contract_version` guard was untestable. Added `touch(contract)` after `recompute_receivable`. |
| `workspace/implementation/routes/blocks.py` | `waive_attrition` | Same PRD §2.7 sentence names the attrition waiver as the other contract-version bump; the waiver touched only the block and the DRAFT reconciliation. Added `touch(contract)`. |
| `workspace/implementation/routes/leads.py` | `decide_analysis` | Ladder-order defect found by inspection (no test covered it): the one-shot replay guard (`ERR_ANALYSIS_ALREADY_DECIDED`, §2.8 priority 11) was evaluated **before** the declared-transition gate (`ERR_LEAD_INVALID_STATE`, priority 10). Re-deciding a REJECTED study, whose lead is then `LOST`, reported the priority-11 error. Swapped the two checks. |

### Fixes to `test_suite/` (STEP 2 — test was inconsistent with PRD)

- `test_suite/test_07_cross_entity_gates.py::test_approving_the_sibling_study_unblocks_the_identical_accept` — read the displacement analyses with `ACCOUNTING_CLERK`, but PRD §4 authorizes `GET /group-sales/displacement-analyses/{id}` for `SalesManager`, `RevenueManager`, `ContractAdmin` only; the correct response was the 403 the implementation returned. Switched the read to `CONTRACT_ADMIN`.
- `test_suite/test_07_cross_entity_gates.py` — helper `_sent_contract_with_quoted_charge` created an `AncillaryCharge` against a **SENT** contract, but PRD §3.8 ("quotes an `AncillaryCharge` **against a signed contract**") and the §4 row ("Quote … revenue **against a SIGNED contract**") make a SIGNED parent a creation precondition — as `test_helpers.seed_ancillary_charge`'s own docstring already states, and as every other one of the 9 call sites in the suite does. The fixture therefore issued a PRD-inconsistent request; a faithful PRD-only implementer gating creation on SIGNED would fail at setup. Replaced with `_signed_contract_with_quoted_charge` and re-anchored the two tests on rules that *are* verbatim and uniquely derivable:
  - `test_a_charge_cannot_post_once_its_contract_has_left_signed` (was `…against_an_unsigned_contract`): charge is created on the SIGNED contract, the contract is then CLIENT_CANCELled, and the post is refused with `ERR_CONTRACT_INVALID_STATE` 409 — the same gate ("It requires the charge to be `QUOTED` and the contract to be `SIGNED`"), reached through a PRD-legal path, with `ancillary_posted_cents == 0` and the receivable identity still asserted.
  - `test_the_countersigned_contract_lets_the_same_charge_post` (was `test_the_countersignature_alone_…`): asserts the admitted side — post → POSTED, `ancillary_posted_cents` 450000, `receivable_total_cents` 450000, identity holds ("On success the contract's `ancillary_posted_cents` increases by the charge's `net_amount_cents` and the contract's receivable is recomputed"). No assertion was weakened; no exact `error_id` was downgraded.
- `test_suite/test_12_calculation_variants.py::test_ninety_days_notice_prices_one_tier_and_no_clause_halves_it` — the test builds a **second** programme on the same calendar and same nights while the first programme's accepted quote still holds 4 rooms. PRD §3.3 computes displacement against "the day's `total_rooms` less its `committed_group_rooms` less its **`held_group_rooms`**", so the second study displaces 18 room nights instead of 6 and its `net_benefit_cents` is −117,360 → verdict `OVERRIDE_REQUIRED`; PRD §3.3 then admits the approval only with "a non-blank `override_reason`", so the implementation's `ERR_DISPLACEMENT_NET_BENEFIT_NEGATIVE` was correct. Threaded an `override_reason` through `_walk_to_sent_contract` and supplied it for the second programme only (the first, whose verdict is `ACCEPT`, still clears with none). No expected figure changed — the 125,280 / 62,640 cancellation assertions are untouched.

No changes to `test_helpers/`. No endpoint, field, side effect or seeded data was added to the implementation; storage remains in-memory dicts wiped by every `start.sh` re-invocation.

### Final sweep evidence (iteration 2, read from each `workspace/implementation/results.$i.json`)

| round | passed/total | failed | errors | duration |
|---|---|---|---|---|
| 1 | 84/84 | 0 | 0 | 154.2s |
| 2 | 84/84 | 0 | 0 | 154.1s |
| 3 | 84/84 | 0 | 0 | 153.6s |
| 4 | 84/84 | 0 | 0 | 154.2s |
| 5 | 84/84 | 0 | 0 | 154.1s |
| 6 | 84/84 | 0 | 0 | 154.2s |
| 7 | 84/84 | 0 | 0 | 154.1s |
| 8 | 84/84 | 0 | 0 | 154.2s |

No flakiness: the 5 iteration-1 failures were identical in all 8 rounds, and all 8 iteration-2 rounds are clean. `worklog.md` untouched; scratch confined to `/tmp/prd_bench_2864_step7/`.

**Orchestrator independent verification:** re-read all 8 `results.$i.json` directly — 8 files present, each `passed=84 total=84 failed=0 errors=0`. Test count still 84 `def test` functions; `grep` for `pytest.mark.skip|pytest.mark.xfail` across `test_suite/` + `test_helpers/` returns 0 hits; `grep` for `sqlite3|json.dump|pickle|open(...'w')` across the implementation returns 0 hits (storage remains in-memory). Step 8 will run, since Step 7 applied 3 `implementation/` fixes and 3 `test_suite/` fixes.

## Step 8: Finalize PRD — 2026-09-05T12:32:00.000Z

Done. `PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 541 lines; `PRD_FINALIZED.md`: 541 lines (0.0% line delta — all four edits are in-place sentence revisions; 4 lines changed, ~0.74% of lines).

## Changes (one bullet each)
- **§3.8, ancillary-charge creation** — insert — pins that a `SIGNED` parent contract is a *creation* precondition tested after `contract_id` resolves, and names the previously-unnamed rejection `ERR_CONTRACT_INVALID_STATE` (409) for `DRAFT`/`SENT`/`COMPLETED`/`CANCELLED`/`TERMINATED_FORCE_MAJEURE` — `implementation/routes/billing.py:22-25`.
- **§3.8, posting a charge** — revise — adds that on success the contract's `version` increments (the §2.7 "newly posted ancillary charge" bump), and pins the charge-status-before-contract-status order plus `ERR_CONTRACT_INVALID_STATE` (409) when a still-`QUOTED` charge's contract has left `SIGNED` — `implementation/routes/billing.py:54-71`.
- **§3.7, attrition waiver** — revise — adds that the contract's `version` increments alongside the block's (the §2.7 "attrition waiver" bump) — `implementation/routes/blocks.py:213-215`.
- **§3.3, deciding a study** — revise — reorders the lead-stage gate ahead of the replay guard and states explicitly that a re-decision of a `REJECTED` study on a now-`LOST` lead reports `ERR_LEAD_INVALID_STATE`, not `ERR_ANALYSIS_ALREADY_DECIDED` — `implementation/routes/leads.py:223-231`.

## Per-edit pre-edit search log

**Edit 1 — charge-creation contract-status precondition**
- (a) Subject: the contract-status gate on creating an `AncillaryCharge`, and its error id.
- (b) Paths enumerated/read: `routes/billing.py::create_charge` (the only `AncillaryCharge` creation site — confirmed by grepping `store.charges[` and `"QUOTED"` assignments); `logic.py::need_contract` (404 precedes the state gate); `core.py::CONTRACT_STATUSES` for the exhaustive non-`SIGNED` list; §4's `POST /group-sales/ancillary-charges` row; §5 catalogue confirms `ERR_CONTRACT_INVALID_STATE` = 409. Also checked that creation is *not* gated on `credit_hold` (only posting/signing are) so the new sentence adds nothing about credit standing.
- (c) Adjustment: scoped to creation only and phrased "tested once the `contract_id` has resolved" so it cannot be read as overriding the priority-4/6 not-found gates.

**Edit 2 — contract `version` bump and error id on posting**
- (a) Subject: which rows a charge post touches, and the post-time contract-status rejection.
- (b) Paths enumerated: `billing.py::post_charge` (`touch(charge)`, `recompute_receivable`, `touch(contract)`); `billing.py::void_charge` (calls `recompute_receivable` but **no** `touch(contract)`); `contracts.py::cancel_contract:208-209`; `billing.py::open_reconciliation:157`; `billing.py::finalize_reconciliation:192,199`; `logic.py::recompute_receivable` (returns `changed`, never touches the row itself); grep of `touch(contract` / `recompute_receivable` across all modules.
- (c) Adjustment: the `version`-increment claim is confined to the *posting* sentence and deliberately **not** attached to §3.8's later "recomputed on every event that can disturb it: posting a charge, voiding a charge, cancelling…" list, because voiding a posted charge recomputes the receivable without bumping the contract's `version`. A universal phrasing there would have been a brand-new mismatch.

**Edit 3 — contract `version` bump on the attrition waiver**
- (a) Subject: the set of rows whose `version` a waiver increments.
- (b) Paths enumerated: `blocks.py::waive_attrition` (grep `'"WAIVED"'` shows `blocks.py:206` is the only assignment) — `touch(block)` unconditional, `touch(newest)` only when a `DRAFT` settlement exists (reachable only from the `ATTRITION_ASSESSED` branch, since the `UNBILLED` branch requires no settlement at all), `touch(contract)` in both branches whenever the contract resolves; `logic.py::waived_room_nights` and `commitment_base_room_nights` (consumers of `WAIVED`); `billing.py:194` (`WAIVED → SETTLED` at finalize, no waiver semantics).
- (c) Adjustment: wrote "and so does the contract's" rather than enumerating the reconciliation, so the sentence stays true in the `UNBILLED` branch where no settlement row exists; the draft-settlement touch remains covered by §2.10's general cascade rule.

**Edit 4 — lead-stage gate vs. replay guard on `POST /displacement-analyses/{id}/decide`**
- (a) Subject: relative evaluation order of `ERR_LEAD_INVALID_STATE` (priority 10) and `ERR_ANALYSIS_ALREADY_DECIDED` (priority 11) on the decide endpoint.
- (b) Paths enumerated: `leads.py::decide_analysis:208-252` (full order: schema → `need_analysis` → `need_lead` → `expected_lead_version` → SoD → lead stage → analysis `PENDING` → override gate); the other two priority-11 replay guards, `billing.py::finalize_reconciliation:174-185` (SoD → `ERR_RECONCILIATION_ALREADY_FINALIZED` → contract-`SIGNED` `ERR_CONTRACT_INVALID_STATE`) and `blocks.py::waive_attrition:192-205` (`ERR_BLOCK_ALREADY_BILLED` → settlement-context `ERR_BLOCK_INVALID_STATE`) — in both of those the later `*_INVALID_STATE` is a *context* precondition on a different row, not a declared-transition gate on the target row, so neither contradicts the ladder.
- (c) Adjustment: added the qualifier "on this operation" and pinned the claim to the lead-stage gate specifically, so it does not become a universal "declared-transition always beats replay" rule that the finalize and waive paths would appear to violate. Also left the separation-of-duties sentence untouched (its true position, priority 9, is already fixed by §2.8) to keep the diff minimal.

**Orchestrator verification:** `PRD_FINALIZED.md` exists at 541 lines and is NOT byte-identical to `PRD.md` — `diff` reports 8 changed lines (4 revised sentences, one `<`/`>` pair each).

## Step 9: Complete PRD — 2026-09-05T13:22:00.000Z

**Orchestrator note on structure:** Step 9 was run as three sequential, module-partitioned passes over one shared `PRD_COMPLETED.md`, because a single pass reliably under-scans a 541-line PRD against ~3,400 lines of implementation. Pass 1 did the `cp` from `PRD_FINALIZED.md` exactly once; passes 2 and 3 were instructed not to copy and to edit in place, preserving prior edits. Slices: pass 1 = `app.py`, `core.py`, `routes/catalog.py`, `routes/leads.py`, `routes/quotes.py`; pass 2 = `routes/contracts.py`, `routes/blocks.py`, `routes/reservations.py`, `routes/billing.py`; pass 3 = `logic.py`, `serialize.py`.

### Pass 1 (app.py, core.py, routes/catalog.py, routes/leads.py, routes/quotes.py)

Job A: `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` done exactly once at the start, before any edit.
Line counts / delta: `PRD_FINALIZED.md` 541 lines / 116,921 chars → `PRD_COMPLETED.md` 541 lines / 120,492 chars (+3,571 chars, 0 new lines).
Counts: 15 ambiguity-pins, 5 mismatch-revisions (20 lines touched).

- §2.1 — insert — ambiguity — a `GroupAccount` (and its leads reverse listing) resolves to itself for `GroupContact` ownership — `routes/catalog.py:41,51`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, never wall clock — `core.py:347`
- §2.3 — insert — ambiguity — `created_at` ties broken by write order, earliest first — `core.py:332`, `routes/leads.py:107`
- §2.4 — insert — ambiguity — client instants accepted with/without seconds, 0–9 fractional digits, `Z`/bare/`±HH:MM`, normalized to 3 fractional digits + `Z` on read — `core.py:180-217`, `routes/leads.py:43`
- §2.5 — revise — ambiguity — `created_at` stamped from the logical clock — `core.py:309-319`
- §2.8 #3 — insert — ambiguity — all per-field numeric floors/ceilings and string-length bounds land at the schema gate as `ERR_INVALID_REQUEST` 400 (incl. `group_ceiling_rooms > total_rooms`), never 422 — `core.py:449-498`, `routes/catalog.py:112`
- §2.8 #5 — insert — ambiguity — the rate-quotes listing is silently narrowed rather than 403, `total_count` counting owned rows only — `logic.py:269`, `routes/quotes.py:106`
- §2.8 #13 — revise — **mismatch** — quote-still-live also applies to countering; revising is not gated — `routes/quotes.py:150,168`
- §2.8 #18 — revise — **mismatch** — displacement gate also applies to proposing, but only its `APPROVED` half — `routes/quotes.py:122`
- §2.9 — insert — ambiguity — re-posting an existing `stay_date` updates the same row and still returns HTTP 201 — `routes/catalog.py:116-127`
- §2.11 — insert — ambiguity — FK query filters string-matched, unknown value → empty page with `total_count` 0, not 404 — `routes/quotes.py:100-103`
- §3.1 — revise — ambiguity — `billing_contact_email` is 1–320 characters — `routes/catalog.py:23`
- §3.3 — revise — ambiguity — `override_reason` capped at 500 characters — `routes/leads.py:212`
- §3.3 — revise — **mismatch** — on APPROVE the reason is recorded whenever non-blank, needed or not — `routes/leads.py:239`
- §3.3 — insert — ambiguity — on REJECT a supplied `override_reason` is ignored and stays null — `routes/leads.py:245-247`
- §3.4 — insert — ambiguity — no floor on `effective_net_rate_cents`; it and `total_quote_value_cents` may go negative — `logic.py:476-482`
- §3.4 — revise — ambiguity — `countered_base_rate_cents` ≥ 1, `counter_note` ≤ 500 chars — `routes/quotes.py:141-143`
- §3.4 — revise — ambiguity — revise reads `room_rate_discount_pct` live off the package while using pinned `comp_room_ratio`/`rebate_per_room_night_cents`; discount stack not re-checked; counter fields retained — `routes/quotes.py:179,191-193`
- §3.4 — revise — **mismatch** — `countered_base_rate_cents` is advisory: acceptance re-prices nothing — `routes/quotes.py:227` with `routes/contracts.py:67`
- §4 — revise — **mismatch** — accept row now reads "a PROPOSED or COUNTERED quote" — `routes/quotes.py:218`

Deliberately left alone: zero-delta `move_held` on an equal-peak revise, the Flask-level `ERR_NOT_FOUND`/405 handlers, blank-string `counter_note` storage — judged too fine-grained to pin without risking a false universal. Cross-slice claims (§2.8 #3/#5, §2.11, §2.3) were grep-verified against the pass-2 modules first.

### Pass 2 (routes/contracts.py, routes/blocks.py, routes/reservations.py, routes/billing.py)

No re-copy: never ran `cp`, never wrote the file whole; all 24 Edit calls were in-place. `PRD_FINALIZED.md` byte-unchanged. Line-paired diff shows 43 changed lines, 18 of them pass 1's — all still present and unmodified (markers verified: "1 to 320 characters", "silently narrowed", "advisory throughout", "revising a quote is not gated here", "PROPOSED or COUNTERED quote", "No floor is applied to the subtraction").
Size: 541 lines / 120,492 chars → 541 lines / 127,690 chars (+7,198 chars, 0 new lines).
Counts: 29 changes — 23 ambiguity-pins, 6 mismatch-revisions.

- §2.8 #5 — insert — ambiguity — a body-FK-resolved owner is looked up before the ownership gate, so an unresolvable id is 404 and only a resolvable foreign one is 403 — `routes/reservations.py:28-29`
- §2.8 #11 — insert — **mismatch** — two of the three one-shot guards invert priority 10: finalize tests the settlement's `DRAFT` before the contract's `SIGNED`; waive tests `billing_status` before the source-state settlement conditions — `routes/billing.py:177`, `routes/blocks.py:192`
- §2.10 — revise — **mismatch** — cascade hops "move" rather than "touch" every row, with a carve-out where §3 leaves a row's `version` alone; the client organization is removed from the bumped set (history derived on read) — `routes/billing.py:186-199`, `serialize.py`
- §2.11 — revise — ambiguity — `is_master` accepts `true`/`false`/`1`/`0` case-insensitively, else `ERR_INVALID_REQUEST` — `core.py` (`q_bool`)
- §3.5 — revise — ambiguity — a distinct+contiguous plan on the wrong dates clears the date gate and fails later as `ERR_ALLOTMENT_PLAN_MISMATCH` — `routes/contracts.py:28,46-49`
- §3.5 — insert — ambiguity — per-field floors land as `ERR_INVALID_REQUEST` while the ceiling against `quoted_room_nights` is `ERR_ALLOTMENT_PLAN_MISMATCH`; stored/echoed plan sorted by `stay_date` ascending — `routes/contracts.py:24,50,36`
- §3.5 — insert — ambiguity — no uniqueness on `quote_id`: a second contract papered from the same ACCEPTED quote is created normally — `routes/contracts.py:27`
- §3.5 — revise — ambiguity — send requires the quote still `ACCEPTED` (`ERR_QUOTE_INVALID_STATE` 409), tested after the contract's DRAFT check — `routes/contracts.py:112,117`
- §3.5 — revise — ambiguity — `signature_name` is 1–120 chars, non-blank — `routes/contracts.py:129`
- §3.6 — revise — ambiguity — `parent_block_id` may be master or sub-block, no parent/contract status gate; duplicate `stay_date` is 400; sub-block plans need not be contiguous — `routes/blocks.py:25-28`
- §3.6 — revise — **mismatch** — sub-block validation is two complete passes (all dates, then all rooms) — `routes/blocks.py:36-47`
- §3.6 — insert — ambiguity — only the parent block row is stamped; parent `BlockNight` rows keep their `version` because `rooms_sub_allocated` is derived — `routes/blocks.py:67`
- §3.6 — revise — ambiguity — open's gate order; `ERR_CONTRACT_INVALID_STATE` for a non-SIGNED contract; `ERR_BLOCK_INVALID_STATE` (not `ERR_PAST_CUTOFF_DATE`) for a passed cutoff — `routes/blocks.py:154-165`
- §3.6 — revise — ambiguity — duplicate test matches `guest_name` case-sensitively; a `NO_SHOW` row still blocks — `routes/reservations.py:50-56`
- §3.6 — insert — ambiguity — the comp re-walk may zero the brand-new row's `rate_cents`, yet the 201 returns `version` 1 and `updated_at` == `created_at` — `routes/reservations.py:75-78`
- §3.6 — revise — ambiguity — `to_status` enum-checked (400); in-set but unreachable target is `ERR_RESERVATION_INVALID_STATE`; the three clock gates report 409 and none inspects `inventory_status` — `routes/reservations.py:95-122`
- §3.6 — insert — ambiguity — `NO_SHOW` adjusts no `rooms_released` — `routes/reservations.py:125-127`
- §3.6 — revise — ambiguity — `disposition_reason` 1–500; block gate `ERR_BLOCK_INVALID_STATE` 409; cancelling on a `CUT_OFF` block raises each night's `rooms_released` instead of returning the room — `routes/reservations.py:135,143-161`
- §3.7 — insert — ambiguity — pickup summary's `commitment_base_room_nights` and both projections are contract-scoped, so a sub-block reports its master's figures — `routes/blocks.py:144-146`
- §3.7 — revise — ambiguity — `waiver_reason` 1–500 chars, non-blank — `routes/blocks.py:190`
- §3.7 — insert — ambiguity — the `UNBILLED` branch is closed by any reconciliation (DRAFT, SUPERSEDED or FINALIZED) — `routes/blocks.py:197-201`
- §3.7 — revise — ambiguity — from `ATTRITION_ASSESSED`, a missing/SUPERSEDED/FINALIZED newest settlement is `ERR_BLOCK_INVALID_STATE` 409 — `routes/blocks.py:203-205`
- §3.8 — revise — **mismatch** — a directly requested void bumps only the charge's `version`; the contract's status is never gated on a void — `routes/billing.py:79-93`
- §3.9 — insert — ambiguity — behind the version guard the contract must be `SIGNED`, checked ahead of both timing gates — `routes/billing.py:108-111`
- §3.9 — revise — ambiguity — only `CUT_OFF`/`CLOSED` blocks move `UNBILLED → ATTRITION_ASSESSED`; a `RELEASED` block is silently skipped — `routes/billing.py:126-130`
- §3.9 — insert — **mismatch** — finalize's replay guard runs ahead of the contract-state check — `routes/billing.py:177-185`
- §3.9 — revise — ambiguity — on finalization only `CUT_OFF` blocks move to `CLOSED` — `routes/billing.py:196-197`
- §3.9 — insert — **mismatch** — finalization hop 3 writes nothing to the account row; all four history figures are derived — `routes/billing.py:186-199`, `serialize.py`
- §3.9 — revise — ambiguity — contract-cancel `note` ≤1000 chars, may be blank, validated but never persisted — `routes/contracts.py:189-190`

### Pass 3 (logic.py, serialize.py)

No re-copy, no whole-rewrite: 11 in-place `Edit` calls only. Passes 1–2 markers re-verified present verbatim (each `grep -c` = 1): "resolves to itself", "unresolvable `block_id` reports", "The one row the walk never counts as mutated", "no contract property carries it back", "case-insensitively, any other value being", "Two of the three invert the order".
Size: 541 lines / 127,690 chars → 541 lines / 130,539 chars (+2,849 chars, 0 lines).
Counts: 10 ambiguity-pins, 1 mismatch-revision.

- §2.6 — insert — ambiguity — every product/quotient/sum feeding a rounding point is formed in exact decimal arithmetic on the literal written values, not binary floating point, with two worked boundary cases (1050 × 0.15 → 158; ceil(100 × 0.8) → 80, not 81) — `core.py:36` (`D()`), `core.py:41` (`round_half_up`), `core.py:47` (`ceil_int`)
- §3.1 — insert — ambiguity — `discount_stack_pct` is the exact decimal sum, reading back as exactly `0.3` for 0.1 + 0.2 — `logic.py:499`
- §3.5 — insert — ambiguity — the countersignature ceiling check removes the quote's hold only while `hold_placed` is still true, so a second contract papered off the same consumed quote is tested against the full `held_group_rooms` — `routes/contracts.py:142` with `logic.py:808`
- §3.5 (hop 5) — insert — ambiguity — the quote's `version` increments even when `hold_placed` was already false, in which case no `held_group_rooms` figure moves — `logic.py:770` with `routes/contracts.py:176`
- §3.6 — insert — ambiguity — a master block's pickup roll-up spans every descendant sub-block at any depth, each night counted once — `logic.py:371`
- §3.6 — insert — ambiguity — the comp walk's ordering tie-break: equal `created_at` resolves by write order, earliest first, per §2.3 — `logic.py:510` with `core.py:in_order`
- §3.6 — insert — ambiguity — only rows whose designation actually moves are stamped; a reservation re-derived to the `is_comp`/`rate_cents` it already held keeps its `version`/`updated_at` — `logic.py:531`
- §3.6 — revise — **mismatch** — narrowed the universal "re-derived whenever a reservation is created or cancelled" to the rooming-list endpoints (create/cancel/no-show), naming the §3.9 contract-cancellation cascade as the one cancellation that does not re-derive — `routes/reservations.py:75,127,162` vs `logic.py:924`
- §3.7 — insert — ambiguity — a post-draft attrition waiver fully re-derives the draft (`actualized_room_nights`, `billable_room_nights`, `ancillary_net_cents` re-read from the contract's current actualized set and currently `POSTED` charges) rather than patching two fields, with `incentive_rate_snapshot` the sole frozen figure, and the draft's `version` incrementing — `logic.py:678` with `routes/blocks.py:211`
- §3.7 — insert — ambiguity — of the two waiver-derived quantities only `commitment_base_room_nights` is surfaced (by the pickup summary); no response field carries `waived_room_nights` — `serialize.py` (absence) with `routes/blocks.py:144`
- §3.9 — insert — ambiguity — the cancellation cascade is the one path reaching `CANCELLED` without re-deriving complimentary designations — `logic.py:924`

Pass 3 deliberate non-edits: night-row `version` behavior in the cutoff/release cascades (covered by pass 2's §2.10 wording); the single-rounding shape of the force-majeure/`NONE`-clause damages branch; damages-computed-before-release ordering in §3.9; `revise_quote`'s `exclude_held=old_peak` and `expire_quote_if_lapsed` callsites (already matching existing §3.4 text).

Pass 3 residual statement: after three passes no behavior in `logic.py` or `serialize.py` fails to trace to a PRD sentence — all 13 calculations have their rounding order, divisor semantics, floor-at-zero clamps, tier boundaries and tie-breaks pinned; every serializer's field set, JSON type, null handling and derived-on-read recomputation matches PRD prose, with the single formerly-unsurfaced term (`waived_room_nights`) now explicitly declared absent. The one mismatch found (§3.6's over-broad cancellation claim) was narrowed rather than removed; no prior-pass edit was duplicated, reverted or contradicted.

### Orchestrator final verification

- `PRD_COMPLETED.md` exists at 541 lines / 130,539 chars and is NOT byte-identical to `PRD_FINALIZED.md` (541 / 116,921) — `diff` reports 98 changed lines, i.e. 49 revised sentences across the three passes. `+13,618` chars over `PRD_FINALIZED.md`, `+14,850` over the original `PRD.md`.
- Tail integrity confirmed: the file ends on the complete `ERR_ACCOUNT_CREDIT_HOLD | 402` table row and carries all 5 `##` sections — no truncation.
- `implementation/` and both test directories are byte-unchanged since the green sweep (`find … -newer implementation/results.1.json` returns nothing for `*.py` in `implementation/`, `test_suite/`, and `test_helpers/`). Steps 8 and 9 touched documentation only, so the recorded 8×(84/84) sweep result still holds for the delivered artifacts.

**PIPELINE COMPLETE.**
