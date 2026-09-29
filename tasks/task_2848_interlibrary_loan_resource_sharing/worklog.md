# Worklog — task_2848_interlibrary_loan_resource_sharing

## Step 1: Create task directory — 2026-09-05T06:23:29.238Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2848_interlibrary_loan_resource_sharing` and its `workspace/` subdirectory. Index 2848 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed and no index was auto-allocated (32 pipelines run concurrently on this host, so auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-05T08:03:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     16
  §1.8 instances scanned:     19
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  926

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files**
- `SCAFFOLD.yaml` — 3447 lines / 160 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2073 lines / 142 KB
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4590 lines / 311 KB

**Scaffold summary**
- §1.0–§1.7: 16 entities, 10 state machines, 11 calculations, 44 validation rules (priority-ordered), 68 endpoints, 56 errors, 6 roles, 3 OCC `concurrency_rules`. `complexity_profile`: graph topology, cyclic state machines, segregation_of_duties role model, immediate consistency, archetypes multi_party_negotiation + compliance_audit, layers `[selector_policy, rate_threshold_triggers, cascading_side_effects, optimistic_concurrency]`. Logical clock default `2026-08-01T00:00:00Z`, money in integer cents with `round_half_up` and pinned rounding order, 8-step idempotent `POST /ill/ops-runs` sweep.
- §1.8: **9 rules / 19 instances** (every mandated `rule_id`, each with >=2 differentiated instances; 3 for `cross_entity_state_dependency`).
- §1.9: **9 sections / 72 instances** — 57 with full `test_recipe`, 15 `excluded_because` stubs deferring to a named §1.8 instance. Per section: entities 12, state_machines 14, calculations 15, validations 10, endpoints 6, errors 6, rbac 3, cross_cutting_complexity_layers 5, consistency_model 1. All `claim_type` values come from `claim-extraction-guide.md` rows; `selector_policy` was skipped in the cross-cutting section because the guide has no row for it (its content lives in the Calculations rows for `lender_landed_cost_ranking`).

**Notable findings**
- Found and fixed a real reachability defect in `SCAFFOLD.yaml`: validation priority 44 originally required `ElectronicDelivery.status == AVAILABLE`, which made priority 73 (`ERR_DELIVERY_DOWNLOAD_CAP_REACHED`) permanently unreachable, since the capping download itself flips the row to `EXHAUSTED`. Relaxed 44 to `status is not EXPIRED` and matched the state-machine precondition; the §1.9 `errors` instance now proves all three delivery refusals (44, 66, 73) are individually reachable.
- Verified independently of the linter: no duplicate instance names across the union of both design files, every stub citation resolves to a `rule_id / instance_name` in §1.8, no stub carries a `test_recipe`, no call object has keys outside `{call, payload, as, as_user_id, captures}`, every `${var}` in payloads/paths/asserts is bound by an earlier `captures:` (one stale placeholder, `${req_id_never}`, was removed from a §1.8 assert), and none of the forbidden concurrency vocabulary appears in any file.
- Heads-up for the orchestrator: `SCAFFOLD.yaml`'s `scenario:` block retains the verbatim first line "Generate task harder than expert level!" because the instruction said the scenario text must not be modified. That line is the known leak path into PRD.md and should be stripped after Step 2.

**Orchestrator action taken:** per the known leak path flagged above, the line `Generate task harder than expert level!` and its trailing blank line were deleted from `SCAFFOLD.yaml`'s `scenario:` block immediately after this step. `grep -rn "harder than expert"` over the whole task dir now returns nothing, and all three YAML files still parse (`yaml.safe_load`) with the expected top-level keys. The difficulty directive was therefore never visible to the doc generator, test generator, or implementation generator.

## Step 3: Copy shared files — 2026-09-05T08:03:10.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T08:20:00.000Z

PRD complete and verified.

**Artifact:** `workspace/PRD.md` — **494 lines**, built incrementally (one `Write` + seven `cat >> … <<'PRDEOF'` heredocs plus two script-generated table appends), each append confirmed with `wc -l`/`tail`. Final line is the last row of the §5 error table (`| \`ERR_DAMAGE_FEE_EXCEEDS_REPLACEMENT\` | 422 |`) — a genuine end-of-document boundary, no mid-sentence cut, no audit footer.

**Sections in order**
1. `# Interlibrary Loan & Resource Sharing API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC · 2.2 API Response Structure · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 Money, Counts and Rounding Discipline · 2.6 Snapshots, Cascades and Derived Counters · 2.7 Optimistic Concurrency Control on Partners and Rotas · 2.8 The Rejection Ladder · 2.9 Nested Resource Retrieval · 2.10 The Logical Clock and Time-Driven Change · 2.11 Filtered Reads and Reverse Reachability
4. `## 3. Business Logic & Workflows` — 3.1 Patron Accounts, Standing and Migrated History · 3.2 The Partner Network, Reciprocity Terms and Lender Rotas · 3.3 Bibliographic Records and Request Intake · 3.4 Copyright Compliance for Article Copies · 3.5 Sourcing the Rota: Candidate Ranking, Offers and Commitment Pricing · 3.6 Physical Fulfilment: Shipping, the Hold Shelf, Pickup, Renewals and Recalls · 3.7 Returns, Damage, Loss and the Settlement Waterfall · 3.8 Electronic Delivery, Purchase on Demand and Cancellation · 3.9 Consortium Settlement and the Nightly Operational Sweep
5. `## 4. API Endpoint Definitions` (intro paragraph + 68-row table)
6. `## 5. Error Code Catalogue` (56-row table)

**Coverage (mechanically checked against SCAFFOLD.yaml)**
- **68/68 endpoints**, **16/16 entities**, **44/44 validations** (§2.8 has exactly 44 numbered rungs), **11/11 calculations** (all 39 distinct constants verbatim, pinned orderings stated), **56/56 errors** (zero table-only identifiers).

**Hard Contracts**
- Contract 1 (Field-Name Coverage): PASS — 163/163 entity fields and 88/88 endpoint input/query identifiers appear verbatim in backticks outside code fences.
- Contract 2 (Rule Coverage): PASS — 44 priority-ordered rungs; all 3 OCC rules; every enum value of every constrained field; all transitions of the 8 state machines including the depth-5 damage cascade and the 8-step idempotent sweep.
- Contract 3 (§3 Path Purity): PASS — 0 backticked paths, 0 bare HTTP methods, 0 method+path combinations in §3; no pseudocode, no fuzzy quantifiers, no scaffold jargon.

Constraints honoured: neither design index was opened; no sibling task directory read; no broad kill; scratch confined to `/tmp/task2848_prd/`.

**Orchestrator truncation check (per the known doc-generator failure mode):** independently verified — `wc -l` = 494, `tail -15` ends on the final error-table row `| \`ERR_DAMAGE_FEE_EXCEEDS_REPLACEMENT\` | 422 |` (a real section boundary, not a mid-sentence cut), all five `##` sections present in order, endpoint table row count = 68, and a grep for `harder than expert|scaffold|test_recipe|difficulty` over PRD.md returns nothing (difficulty directive did not leak). No regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T09:55:00.000Z

Step 5 complete.

## Files written

**`test_helpers/`** (Stage 1, at task root): `__init__.py` 46 · `api_client.py` 608 · `api_errors.py` 126 · `assertions.py` 245 · `constants.py` 101 · `factories.py` 443 · `fixtures.py` 644 · `test_users.py` 90 · `types.py` 586

**`test_suite/`** (Stage 2, at task root): `conftest.py` 14 · `test_01_entities_and_reads.py` 700 · `test_02_state_machines.py` 845 · `test_03_calculations.py` 984 · `test_04_validations.py` 698 · `test_05_endpoints.py` 666 · `test_06_errors.py` 715 · `test_07_rbac.py` 419 · `test_08_cross_cutting_and_consistency.py` 688 · `test_09_dual_variant_calc.py` 433 · `test_10_combinatorial_formula.py` 268 · `test_11_non_linear_state_machine.py` 442 · `test_12_transitive_cascade.py` 377 · `test_13_priority_pair_validation_conflict.py` 363 · `test_14_boundary_precision_check.py` 338 · `test_15_cross_entity_state_dependency.py` 513 · `test_16_resource_temporal_overlap.py` 357 · `test_17_compensating_invariant.py` 364

12,073 lines total.

## Coverage

- **95 tests emitted**, all carrying exactly one `Design:` line.
- **Legal tag universe 91** (72 corner instances − 15 `excluded_because` stubs = 57 non-stub, plus 19 difficulty instances = 76 translatable). **76 of 76 covered.**
- **Queue A (difficulty): 19 / 19 instances**, each with >=2 tests (uncovered difficulty tags: 0).
- **Queue B (corner): 57 / 57 non-stub instances**, each with >=1 test. The 15 uncovered corner tags were cross-checked programmatically against the yaml and are byte-for-byte the 15 `excluded_because` stubs, as required.
- Citation/tag checker: `tests=95 problems=0` — no untagged, dual-tagged, or dangling-tag tests; every `PRD:` / `And:` citation was `grep -F`-verified as a verbatim, complete PRD sentence.

## Instances skipped

**None.** Every non-stub instance in both design indices passed the PRD-first two-condition filter, so no instance was dropped for PRD-silence or non-unique-derivability.

## Notable resolutions

- **yaml/PRD conflict:** `cross_entity_state_dependency/escalation_gate...` asserts a post-escalation request status of `POD_PROPOSED`, which is not one of the PRD's eighteen request statuses. Applied PRD-first and asserted `RequestStatus.ESCALATED_POD`.
- **Pagination/type discipline:** all money sent as JSON integer cents; every instant sent as a full ISO-8601 literal with milliseconds (never date-only).
- No `cancel_request` fixture exists in `test_helpers/fixtures.py`, so `test_17` wraps the raw `client.cancel_request(...)` (`test_helpers/api_client.py:183`) in `validate_success`.

## Verification

`python3 -m compileall` clean and `pyflakes` clean across `test_helpers/` and `test_suite/`; the only remaining pyflakes lines are the five intentional `# noqa: F401` fixture re-exports in `conftest.py`. `ls -la` confirms `test_helpers/` and `test_suite/` exist at the task root and neither exists under `workspace/`. `worklog.md` and `workspace/implementation/` were left untouched; scratch work stayed in `/tmp/task2848_tests/`.

## Step 6: Generate implementation — 2026-09-05T09:20:00.000Z

The implementation is complete, verified, and the smoke server has been stopped (port 18848 free).

## Files written (`workspace/implementation/`)

| File | Lines |
|---|---|
| `start.sh` (executable, guarded pip + `exec python3 app.py`) | 10 |
| `requirements.txt` (`flask`) | 1 |
| `app.py` (blueprint registration, ApiError/404/405/400/500 envelope handlers, `0.0.0.0:$PORT` default 10000) | 56 |
| `db.py` (in-memory `Store`, logical clock, id/time/serialize helpers) | 132 |
| `errors.py` (all 56 error ids -> HTTP statuses, `ApiError`) | 76 |
| `response.py` (`meta`/`response_type`/`data` envelope, pagination meta) | 68 |
| `middleware.py` (`X-User-ID`/`X-User-Role` auth, 6 roles, 14 404 resolvers, ownership) | 147 |
| `validate.py` (rung-35 shape helpers, pagination, query filters) | 207 |
| `routes/common.py` | 20 |
| `routes/patrons.py` / `partners.py` / `rotas.py` / `bib.py` | 132 / 191 / 125 / 84 |
| `routes/requests.py` (intake ladder, copyright routing, cancel cascade, 6 nested lists) | 298 |
| `routes/sourcing.py` (royalty clearance, rota round, accept/decline, ship) | 237 |
| `routes/fulfilment.py` (receive, lender-confirm, 7 loan endpoints) | 367 |
| `routes/deliveries.py` / `routes/pod.py` / `routes/finance.py` | 76 / 127 / 240 |
| `services/calc.py` / `derive.py` / `sweep.py` | 249 / 196 / 169 |

3,208 lines total; every module compiles, `pyflakes` is clean, no seeding anywhere (store empty at boot).

## Endpoint coverage
**68/68.** A programmatic diff of the PRD §4 table against Flask's `url_map` returns zero missing and zero extra. The error catalogue was diffed the same way: 56/56 ids present with exactly the PRD's HTTP statuses, and all 14 not-found ids are wired to resolvers.

## Smoke test result (PORT=18848, killed by its own PID afterwards)
Three scripted suites, ~140 assertions, **all passing**:
1. Auth/envelope/CRUD + full LOAN happy path (patron -> partner -> agreement -> rota/entry -> bib -> request -> source -> accept -> ship -> receive -> pickup -> renew -> recall -> return -> lender-confirm -> waive) + finance (lending charge -> NET invoice draft `payable=1075 receivable=358 net=717` -> issue -> dispute -> reinstate -> pay) + clock forward/backward + sweep idempotency + list envelope/pagination bounds.
2. COPY path: rule-of-five routing (5x `CONTU_FREE` -> 6th parks at `COPYRIGHT_HOLD`), royalty clearance with SoD + amount-mismatch refusals, re-pricing (`royalty 2100, gross 3300, subsidy 1980, net 1320`), electronic delivery with 3 downloads -> `EXHAUSTED` -> 4th refused, POD reject cycle (`attempt_count` reset to 0) -> re-escalate -> approve -> receive -> `FILLED_BY_PURCHASE` -> `ERR_HELD_LOCALLY`, cancel freeing a copyright slot, and a chained sweep (`agreements_expired 1, offers_expired 1, deliveries_expired 1, requests_unfilled 1`) that is all-zero on the second run.
3. Loan-window capacity refusal, the depth-5 damage cascade (`total 5500`, request `CLOSED_WITH_DAMAGE`), waterfall allocation (3200 -> damage 3000 + processing 200) then `CHARGE_SETTLED`, invoice supersede, and sweep steps 4/6 (`pickups_abandoned 1`, `shipments_lost 1` -> `UNCLAIMED` / `UNFILLED+TRANSIT_LOST`), idempotent on re-run.

Two apparent failures during smoking were the agent's scratch scripts' wrong expectations, both confirmed against the PRD: `ERR_ROTA_ATTEMPTS_EXHAUSTED` is 409 (not 422), and 2 migrated `LOST` infractions correctly score 50 -> `ERR_PATRON_STANDING_BLOCKED` at intake.

## PRD contradictions resolved (recorded in code comments)
- **Shipping vs offer state**: PRD §3.6 "while the underlying offer is still open" would make the happy path unreachable (shipping follows acceptance), so `POST /ill/supply-offers/{id}/shipments` requires `ACCEPTED` and returns `ERR_OFFER_NOT_OPEN` (409) for every other status.
- **Royalty against a non-hold request**: ladder rung 40 (< 51) wins, so `ERR_REQUEST_INVALID_STATE`; rung 51 is reserved for the "already covered by CONTU_FREE/PRE_WINDOW_EXEMPT" limb.
- **Electronic-delivery preconditions** (`service_type == COPY`, partner `supplies_electronic`): the ladder catalogues only `ERR_REQUEST_INVALID_STATE` for that endpoint, so both fold into rung 40.
- **POD approval rung 77**: PRD prose says approval is refused only once the work is `HELD_AVAILABLE` (escalation checks `HELD_AVAILABLE` *or* `ON_ORDER`); prose wins.
- **Sweep step 3** uses `clock > recall_due_at`, matching renewal rung 65's "at or before" boundary, while steps 1/2/4/5/6 use "has reached" (`>=`).

## Step 7: Run tests and iterate — 2026-09-05T09:52:00.000Z

## Summary

**Iterations run:** 2. Iteration 1 was 92/95 in all 8 rounds with an identical 3-test failure set (fully deterministic, no flakiness, no load artifacts). Iteration 2 was **95/95 passed in all 8 parallel rounds**.

**Tests deleted:** none. Two assertions were removed under STEP 1c partial-coverage splitting; both host tests survive with the rest of their assertions intact.

**Assertions removed (STEP 1c splits):**

- `test_03_calculations.py::test_royalty_and_subsidy_are_recomputed_at_clearance_and_at_commitment` — dropped the three clearance-time `gross_charge_cents == 3400` / `subsidy_cents == 2040` / `net_patron_charge_cents == 1360` assertions; replaced with the PRD-pinned `priced_once["royalty_cents"] == 3400`. **DEFAULT-VALUE SILENCE.** These numbers price the request at a moment before any rota round has run, so they hinge entirely on the pre-first-round value of `days_available_at_source`, which the PRD never names. §3.5 only says "On every successful round this figure is snapshotted onto the request" and "when the request's `days_available_at_source` is at most 3 days, `rush_surcharge_cents` is 1200 cents". Reader A initialises the `_days` field to 0 (per §2.5's whole-integer framing) -> `0 <= 3` -> rush 1200 -> gross 4600 (what the implementation produced). Reader B leaves it null and reads an unset runway as not-a-rush -> gross 3400. Both are PRD-faithful, so the expected outcome is not uniquely derivable. The commitment-time half of the test (gross 4900 / subsidy 2940 / net 1960, where the round has actually snapshotted 19 days) is fully pinned and was kept — that half is the real regression value. Scaffold rule: `Corner/calculations/royalty_fee_and_subsidy_are_recomputed_when_the_clearance_and_the_commitment_land`.

- `test_12_transitive_cascade.py::test_the_damage_report_reaches_the_patron_counters_and_blocks_the_account` — dropped `after["provisional_risk_score"] == 54`. **BRANCH-ASYMMETRIC SIDE EFFECT.** §3.7's damage cascade enumerates exactly which patron fields are re-derived: "the patron's `damaged_count`, `lost_count`, `unpaid_balance_cents`, `open_request_count` and `final_risk_score` are all re-derived" — `provisional_risk_score` is pointedly absent, and the PRD names it as re-derived only at intake, at admin amendment and at infraction load (§3.9 Step 8 likewise recomputes only `final_risk_score`). Treating it as a stored value refreshed solely where enumerated is the faithful reading, so it legitimately stays at 37. All the covered assertions were kept, including `damaged_count == 2`, `unpaid_balance_cents == 5500`, `final_risk_score == 50` and `status == BLOCKED` — the block-the-account cascade the test exists to prove still passes. Scaffold rule: `Difficulty/transitive_cascade/lender_damage_confirmation_cascades_five_levels_from_shipment_to_patron_block`.

**Fixes applied to `test_helpers/`:** none. No fixture, factory or role-header bug surfaced — notably none of the known repeat offenders (money-as-strings, date-only literals, sub-second precision, `validate_success` double-unwrap).

**Fixes applied to `implementation/`:**

- `workspace/implementation/routes/sourcing.py`, `record_royalty_clearance` — the rung-40 state gate rejected every non-`COPYRIGHT_HOLD` request with `ERR_REQUEST_INVALID_STATE`, which swallowed the case §3.4 addresses verbatim: "recording a royalty against a request in any other state, or against one that already holds a `CONTU_FREE` or `PRE_WINDOW_EXEMPT` clearance, is `ERR_COPYRIGHT_CLEARANCE_NOT_REQUIRED`". Rung 40 is now scoped to terminal requests only (`calc.REQUEST_TERMINAL`, per §3.3's "every operation that demands a live request refuses with `ERR_REQUEST_INVALID_STATE`"), and a live-but-not-on-hold request such as one at `SOURCING` now falls through to rung 51's `ERR_COPYRIGHT_CLEARANCE_NOT_REQUIRED` (422). Both rungs remain enforced and nothing was weakened; only their boundary moved to match the PRD prose. This reconciliation also keeps the segregation-of-duties check at rung 28 ahead of both, which is what the failing test was asserting.

**Orchestrator verification (per the known "clean sweep with no artifacts" failure mode):** independently re-read all 8 `workspace/implementation/results.$i.json` files. All 8 exist, parse as complete JSON, and report `passed=95 failed=0 total=95`, with mtimes clustered at 2026-09-05T09:49:32Z — a genuine concurrent 8-round sweep, not a single round copied eight times. Step 7's clean-exit claim is confirmed. Step 8 is NOT skipped: Step 7 applied 1 `implementation/` fix and 2 assertion splits.

## Step 8: Finalize PRD — 2026-09-05T10:03:00.000Z

All four edits are in. Summary:

**Line counts:** PRD.md 494 -> PRD_FINALIZED.md 496 lines (+2, **+0.40%**). Four hunks, no new sections.

**Changes**
- **§2.8 rung 40** — revise — scoped rung 40 on the royalty-clearance create to terminal requests only, and stated that a live-but-not-on-hold request passes rung 40 and is stopped at rung 51; left the other four rung-40 operations deliberately un-narrowed — `routes/sourcing.py:29-35`
- **§3.4 (royalty-clearance guards)** — revise — "in any other state" -> "in any other **live** state — `SOURCING` included", plus the terminal-request carve-out to rung 40 — `routes/sourcing.py:30-38`
- **§3.1 (standing)** — insert — one new paragraph pinning `provisional_risk_score` as a stored value rewritten at exactly three points (intake, admin amendment, infraction load) and at no cascade or sweep step; inline cascades and the sweep refresh `final_risk_score` only — `services/derive.py:97-106`, `routes/requests.py:172-174`, `routes/patrons.py:85-86,113`
- **§3.5 (days available)** — insert — pinned the pre-first-round value of `days_available_at_source` at 0, that only a successful round ever writes it, and the consequence that a request priced before any round (paid-royalty release of a `COPYRIGHT_HOLD` request) reads a 0-day runway and takes the rush surcharge — `routes/requests.py:137`, `services/calc.py:210-211`, `routes/sourcing.py:48,116`

**Per-edit pre-edit search log**

1. **Rung-40 scope (§2.8).** (a) Subject: which statuses trip `ERR_REQUEST_INVALID_STATE`, per operation. (b) Enumerated: `grep -rn ERR_REQUEST_INVALID_STATE` -> all five callsites read — `routes/sourcing.py:31` (royalty clearance, terminal-only), `sourcing.py:60` (rota round, `!= SOURCING`), `sourcing.py:224` (lender ship, `!= SUPPLY_COMMITTED or service_type != LOAN`), `routes/pod.py:47` (escalate, `!= SOURCING`), `routes/deliveries.py:26-28` (delivery, `!= SUPPLY_COMMITTED` or wrong service type or partner flag), `routes/requests.py:207` (cancel, `not in CANCELLABLE`), plus `calc.REQUEST_TERMINAL` (7 statuses, matching the PRD's "last seven"). (c) Adjustment: added the closing sentence "On the other four operations the rung is as wide as the state each of them demands" so the narrowing reads as royalty-clearance-only and cannot be back-applied to cancel/round/escalate/delivery — and kept it deliberately vague rather than restating each predicate (the delivery rung also folds in `service_type` and `supplies_electronic`, a path Step 7 never exercised).

2. **§3.4 prose.** (a) Subject: the `ERR_COPYRIGHT_CLEARANCE_NOT_REQUIRED` trigger set. (b) Enumerated: `routes/sourcing.py:20-51` in full (the only emitter of that code — verified by grep across `routes/` and `errors.py`), including the `CONTU_FREE`/`PRE_WINDOW_EXEMPT` loop over `calc.active_clearances`, and the fact that a second `ROYALTY_PAID` clearance is unreachable because success moves the request to `SOURCING`. (c) No adjustment; the existing "already holds a `CONTU_FREE` or `PRE_WINDOW_EXEMPT` clearance" clause was left verbatim because the impl checks exactly those two methods.

3. **`provisional_risk_score` (§3.1).** (a) Subject: every write site of `provisional_risk_score`. (b) Enumerated: `grep -rn "provisional_risk_score|provisional_standing|PATRON_ALL_KEYS|PATRON_COUNTER_KEYS|recompute_patron"` -> all 20 hits inspected: writes only at `routes/requests.py:172-174` (intake), `routes/patrons.py:85-86` (PATCH), `routes/patrons.py:113` (`PATRON_ALL_KEYS`, infraction), creation default `patrons.py:58`; the intake gate at `requests.py:110-113` uses a non-persisted probe. Read every other recompute callsite to confirm none passes the key: `routes/fulfilment.py:138,155,174,286,314,357`, `routes/sourcing.py:50,166`, `routes/requests.py:236`, `routes/pod.py:119`, `services/sweep.py:92,111,157,163`. (c) Two adjustments: (i) rewrote "refresh `final_risk_score` only" -> "refresh `final_risk_score` and never `provisional_risk_score`", because the inline damage/loss cascades *do* also refresh counters and the first phrasing would have falsely excluded them; (ii) **deleted** a drafted universal sentence ("wherever §3 enumerates the patron fields a cascade re-derives, that enumeration is exhaustive") — sweep Step 7's unfilled branch re-derives `open_request_count` (`sweep.py:157`) while the PRD's Step 7 text names no patron field, so that generalization would have created a brand-new mismatch off the Step 7 site.

4. **`days_available_at_source` default (§3.5).** (a) Subject: every read and write of `days_available_at_source`, and every caller of `price_request`. (b) Enumerated: `routes/requests.py:137` (created at 0), `routes/sourcing.py:116` (only writer, on a successful round), `services/calc.py:210-211` (`(… or 0) <= 3` -> rush 1200), callers of `price_request` at `sourcing.py:48` (royalty clearance, always from `COPYRIGHT_HOLD`) and `sourcing.py:163` (accept, always post-round); also checked the two paths that reset request state — `routes/requests.py:221-231` (cancel zeroes the money fields but not `days_available_at_source`) and `routes/pod.py:86-95` (reject resets `attempt_count`/`unfilled_reason` only). (c) Adjustment: phrased the rush consequence as a property of "a request that has not yet completed a round" rather than "a request at `COPYRIGHT_HOLD`", and kept the existing "replacing whatever the previous round left there" clause intact so the un-reset behaviour after a POD rejection or cancellation stays correctly described.

**Orchestrator note:** `PRD_FINALIZED.md` differs from `PRD.md` (496 vs 494 lines) and still ends at the final row of the §5 error table — no truncation.

## Step 9: Complete PRD — 2026-09-05T10:35:00.000Z

**Orchestrator decision (recorded per the AUTONOMY directive):** the implementation is ~3,200 lines across 20 modules, which is far beyond what one subagent can scan exhaustively without silently degrading into a shallow skim (the known failure mode is a `PRD_COMPLETED.md` byte-identical to its source, proving the scan never ran). Step 9 was therefore executed as **three sequential passes partitioned by implementation module**, all editing the SAME shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying so they could not clobber earlier work. Passes ran strictly sequentially (never concurrently) because they share one output file.

Partition:
- **Pass 1** — `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `validate.py`, `routes/{common,patrons,partners,rotas,bib}.py`
- **Pass 2** — `routes/{requests,sourcing,fulfilment}.py`
- **Pass 3** — `routes/{deliveries,pod,finance}.py`, `services/{calc,derive,sweep}.py`, plus two items passes 1/2 explicitly deferred

### Pass 1 (infra + registries)

Source `PRD_FINALIZED.md` 496 lines / 106,046 chars -> `PRD_COMPLETED.md` 500 lines / 112,732 chars (+4 lines, +6,686 chars). **11 ambiguity-pins, 7 mismatch-revisions.** Only two new paragraphs (both in-section continuations: §2.1 ownership-scope clarifier, §2.5 instant-parsing clarifier); all other edits in-paragraph. No new sections, no table rows added.

- `§2.1` — revise — mismatch — PartnerAgent ownership enumeration extended to its own `Partner` row and the child collections addressed beneath it (rota entries, lending charges, invoices) and to `ElectronicDelivery`; Patron enumeration extended to `Shipment`; added that `ReciprocityAgreement` is not ownership-scoped — `middleware.py:107,128,135`, `routes/partners.py:93,110,180`
- `§2.1` — insert — ambiguity — new paragraph pinning that the ownership comparison is made against the path identifier, and that list endpoints narrow by acting identity only where §3 says so — `middleware.py:101-147`
- `§2.1` — revise — ambiguity — auth rejects whitespace-only headers and requires an exact case-sensitive role match — `middleware.py:21-24`
- `§2.2` — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from upper-case letters and digits — `response.py:10,14`
- `§2.2` — revise — ambiguity — `api_request_timestamp` comes from the host's real clock, not the logical clock, and no rule reads it — `response.py:18-22`
- `§2.3` — revise — ambiguity — created_at ties broken by server insertion order; `has_more` = `offset + len(rows) < total_count`; offset past `total_count` is an empty page, not an error; pagination fields absent from single-resource `meta` — `db.py:130-132`, `response.py:45-56`, `validate.py:206`
- `§2.5` — revise — mismatch — integer fields accept any fraction-free JSON number (`2000.0` == `2000`) and reject fractions, booleans and numeric strings — `validate.py:26-33`
- `§2.5` — insert — ambiguity — new paragraph pinning body-instant parsing: `Z`/numeric offset/no designator all normalised to UTC, date-only read as midnight UTC, non-string or unparseable is 400, output always 3 fractional digits — `db.py:59-82`, `validate.py:119-134`
- `§2.8 rung 25` — revise — mismatch — scope narrowed from "every endpoint reachable by `Patron` or `PartnerAgent`" to endpoints whose addressed resource is ownership-scoped by §2.1, plus which paths give 403-before-404 versus 404-first — `middleware.py:101-147`, `routes/patrons.py:121`, `routes/partners.py:93,110`
- `§2.8 rung 35` — revise — ambiguity — absent/empty body read as `{}`; JSON `null` treated as omitted; required strings must be non-empty — `validate.py:14-23,59-69,72-82`
- `§2.10` — revise — ambiguity — every collection is empty at boot; nothing is seeded — `db.py:12-44`
- `§3.1` — revise — ambiguity — duplicate `external_id` is `ERR_INVALID_REQUEST`; `email` checked only for being a non-empty string — `routes/patrons.py:26,32-34`
- `§3.1` — revise — ambiguity — patron amendment always bumps `version`, re-derives the two scores from the stored counters without refreshing them, and never moves `status` itself (so restoring `ACTIVE` sticks even at score >= 40) — `routes/patrons.py:85-88`, `services/derive.py:88-113`
- `§3.1` — revise — ambiguity — infraction load: `count` >= 0 and the unused figure ignored per `kind`; `unpaid_amount_cents` mandatory on `UNPAID_CHARGE`; the load never auto-blocks — `routes/patrons.py:97-114`
- `§3.2` — revise — ambiguity — duplicate partner `code` is `ERR_INVALID_REQUEST` — `routes/partners.py:37-39`
- `§3.2` — revise — ambiguity — `supersedes_agreement_id` is only checked for existence and `ACTIVE`; no same-partner check — `routes/partners.py:126-127,141-144`
- `§3.2` — revise — mismatch — rota-entry `quoted_fee_cents`/`quoted_turnaround_days` are optional and snapshot the partner's published figures when omitted; `manual_rank` required under both policies — `routes/rotas.py:64-71`
- `§3.2` — revise — ambiguity — a rota's own entry list is ordered `manual_rank` asc then `created_at` asc (that is §4's "ranking order"); the partner-side list of the same entries uses the default `created_at` order — `routes/rotas.py:124-125`, `routes/partners.py:112-114`
- `§3.3` — revise — mismatch — only `issn` is validated against `item_type`; `isbn` and `journal_title` are stored as supplied, neither required nor forbidden on any type — `routes/bib.py:25-33`
- `§4` — revise — mismatch — a trailing slash addresses the same endpoint — `app.py:16`
- `§5` — revise — mismatch — an unrecognised path or method answers the standard envelope with `ERR_INVALID_REQUEST` but HTTP 404/405 rather than the table's 400 — `app.py:28-43`

Verified with no change needed: the full `ERROR_STATUS` map in `errors.py` matches §5's table exactly; the ladder ordering in `routes/partners.py`/`routes/rotas.py` (32 -> 35 -> 47 -> 48/49 -> 63) matches §2.8; UUID ids, 3-digit ISO output, `version` starting at 1, `floor_days`, and the initial clock all already pinned; every role list in this partition matches the §4 table.

### Pass 2 (request lifecycle)

500 lines / 112,732 chars -> 500 lines / 119,442 chars. **26 edits — 15 ambiguity-pins, 11 mismatch-revisions.** No new sections, no new paragraphs; all inserts in-paragraph.

Mismatch-revisions:
- §2.1 (role/SoD para) — revise — mismatch — SoD no longer claims to precede "any existence check"; it precedes body-shape/FK/state checks but follows resolution of the addressed row — `routes/sourcing.py:22-26`, cross-checked `routes/pod.py:59-62`
- §2.8 rung 40 — revise — mismatch — added lender shipping to the endpoint list, its `service_type == LOAN` clause, and the explicit note that on shipping rung 40 is evaluated *after* rung 41 — `routes/sourcing.py:220-224`
- §2.8 rung 41 — revise — mismatch — the demanded status is `OFFERED` for accept/decline but `ACCEPTED` for lender shipping — `routes/sourcing.py:220`
- §2.8 rung 43 — revise — mismatch — recalls also enforce this rung (`AWAITING_PICKUP` or `WITH_PATRON`); "four loan operations" -> five — `routes/fulfilment.py:246`
- §3.6 (shipping) — revise — mismatch — "while the underlying offer is still open" -> offer must be `ACCEPTED` (`ERR_OFFER_NOT_OPEN`) and request `SUPPLY_COMMITTED` + `LOAN` (`ERR_REQUEST_INVALID_STATE`), offer test first — `routes/sourcing.py:219-224`
- §3.6 (pickup) — revise — mismatch — deleted the non-existent "inbound parcel must be at `RECEIVED`" precondition — `routes/fulfilment.py:188-197`
- §3.6 (recall) — revise — mismatch — recall is gated on custody only, not on `recall_status`; re-recall from `RECALL_ISSUED`/`RECALL_BREACHED` is accepted and resets the dimension; `grace_days` >= 0 — `routes/fulfilment.py:239-253`
- §3.7 (fine rule) — revise — mismatch — recall resolution happens **only** on the return path — `routes/fulfilment.py:271-276`
- §3.7 (fine multiplier) — revise — mismatch — multiplier 3 requires `RECALL_BREACHED` after this call's resolution; on the loss path only a sweep-breached recall qualifies — `routes/fulfilment.py:300,305`
- §3.7 (loss declaration) — revise — mismatch — the loss path leaves `recall_status` untouched — `routes/fulfilment.py:291-308`
- §3.7 (settlement) — revise — mismatch — `CHARGE_SETTLED` needs outstanding 0 **and** a prior billable state; `PAY` is not gated on `billing_status`; `payment_cents` >= 0 — `routes/fulfilment.py:348-349`

Ambiguity-pins:
- §2.1 (PartnerAgent bullet) — insert — `GET /ill/requests/{id}` is not partner-scoped, while its child collections are — `routes/requests.py:183` vs `:273`
- §2.1 (line 24) — revise — "narrows … only where §3 says so" -> "§2.11", to anchor the new narrowing pin — `routes/requests.py:191`
- §2.8 rung 25 — insert — intake compares the **body** `patron_id` (non-blank string only) ahead of rungs 32/35, after JSON parsing — `routes/requests.py:63-68`
- §2.8 rung 28 — insert — both SoD endpoints resolve their own path row first — `routes/sourcing.py:23-26`
- §2.8 rung 32 — insert — only non-blank string FKs are resolved here; other types fall to rung 35 — `validate.py:146-153`, `routes/requests.py:74`
- §2.11 — insert — exactly two lists narrow by acting identity (Patron->requests, PartnerAgent->offers), before filters; others do not — `routes/requests.py:191-192`, `routes/sourcing.py:202-203`
- §3.3 (intake gates) — insert — the request-cap, standing and balance gates read freshly re-derived figures and write nothing — `routes/requests.py:105-119`
- §3.3 (created request) — insert — commitment/money fields all open at 0/null (intake never prices) and the stored `provisional_risk_score` may differ from the gated figure — `routes/requests.py:121-147,172-174`
- §3.5 (days available) — insert — a passed `needed_by` yields a negative figure, not clamped — `services/calc.py:191`, `db.py:94-96`
- §3.6 (inbound parcel) — insert — `received_at`/`confirmed_at` open null — `routes/sourcing.py:233-234`
- §3.7 (return) — insert — a return never drives the account to `BLOCKED` — `routes/fulfilment.py:286-287`
- §3.7 (lender confirm) — insert — `damage_fee_cents` optional, >= 0, default 0 — `routes/fulfilment.py:115`
- §3.7 (waive) — insert — a waiver from a non-billable state is `ERR_INVALID_REQUEST` (400), not a 409 — `routes/fulfilment.py:351-352`
- §3.8 (cancellation) — insert — `committed_loan_period_days` keeps its snapshot; patron `open_request_count` + `pending_charge_cents` re-derived, no risk score — `routes/requests.py:221-237`
- §4 (preamble) — insert — renewals, charge-settlements and downloads mint no row and answer 200 with the parent — `routes/fulfilment.py:236,359`, `routes/deliveries.py:68`

### Pass 3 (delivery, POD, finance, services) — final pass

500 lines / 119,442 chars -> **502 lines / 123,865 chars** (+2 lines, +4,423 chars). Overall `PRD_FINALIZED.md` (496 / 106,046) -> `PRD_COMPLETED.md` (502 / 123,865): **+6 lines, +17,819 chars**. **9 ambiguity-pins, 4 mismatch-revisions.**

- **§2.4** — revise — mismatch — a recomputation bumps `updated_at`/`version` **only if a recomputed value actually differs** from what was stored; a no-op re-derivation writes nothing. Patron amendment and infraction load named as the unconditional exceptions — `services/derive.py:111`, `:154`, `routes/patrons.py:85-87`, `:113-114`. *(deferred item 1)*
- **§2.6** — insert — ambiguity — any partner-balance re-derivation recomputes **all five** figures, so the field lists in §3.5/§3.8/§3.9 name what ordinarily moves, not a limit on what is looked at — `services/derive.py:145-156`
- **§2.8 rung 40** — insert — ambiguity — electronic delivery gathers three clauses (not `SUPPLY_COMMITTED`; `service_type` != `COPY`; committed partner without `supplies_electronic`, including no committed partner) under the single `ERR_REQUEST_INVALID_STATE` — `routes/deliveries.py:26-28`
- **§2.8 rung 77** — revise — mismatch — escalation refuses `HELD_AVAILABLE` **or** `ON_ORDER`; an `APPROVE` decision refuses `HELD_AVAILABLE` alone — `routes/pod.py:50`, `:73`
- **§2.11** — insert — ambiguity — `issn` and `calendar_year` are required query parameters on the copyright-usage report; missing/empty/non-integer is `ERR_INVALID_REQUEST` — `routes/finance.py:216-221`
- **§3.1** — insert — mismatch — the automatic block moves an account **only out of `ACTIVE`**; a `WITHDRAWN` account is never overwritten — `services/derive.py:107-110`
- **§3.8** (delivery) — insert — ambiguity — all three delivery preconditions report the one `ERR_REQUEST_INVALID_STATE` — `routes/deliveries.py:26-28`
- **§3.8** (download) — revise — mismatch — PRD claimed an `EXHAUSTED` row gives `ERR_DELIVERY_NOT_AVAILABLE`; impl stops only `EXPIRED` at that limb, `EXHAUSTED` falls through (to the cap limb, or the expiry limb if the window also lapsed) — `routes/deliveries.py:56-63`
- **§3.8** (POD) — insert — ambiguity — `vendor` is a required non-empty string on escalation, and is **null** on the sweep-opened order — `routes/pod.py:44`, `services/sweep.py:148`
- **§3.9** (settle) — insert — ambiguity — a `PartnerAgent` naming `PAY` gets `ERR_UNAUTHORIZED`, raised after rung-35 body parsing and **ahead of** the rung-46 state check — `routes/finance.py:172-173`
- **§3.9** (sweep step 6) — insert — ambiguity — step 6 re-derives nothing, so the patron's `open_request_count` and the partner's `borrowed_from_count`/`net_borrow_imbalance_items`/`borrow_payable_cents` stay stale until a later operation re-derives them — `services/sweep.py:113-132`
- **§3.9** (determinism) — revise — ambiguity — final tiebreak is server creation order, and for parentless rows (steps 1, 7, 8) the parent-request term is vacuous — `services/sweep.py:17-24`
- **§5 preamble** — insert (+ first-sentence qualifier) — ambiguity — `ERR_INTERNAL` / HTTP 500 catch-all documented outside the table — `app.py:46-51`. *(deferred item 2)*

**Resolution of the two deferred items**
1. **§2.4** — reconciled by making the bump conditional on a value actually moving, with the two unconditional patron writes called out. Verified against all 30+ callsites: the only paths that bump unconditionally are `patrons.py`'s amendment and infraction load (`defer_touch=True` + explicit `touch`); every cascade callsite in requests/sourcing/fulfilment/deliveries/pod/finance/sweep goes through the conditional path. The observable no-op cases are sweep step 8 over an unmoved patron and `finance.py:158` issuing an invoice with no lend lines.
2. **`ERR_INTERNAL`** — pass 3 reversed pass 1's "leave undocumented" and pinned it minimally, because it turns out to be **reachable**, not merely defensive: `calc.period_bounds` (`calc.py:241-249`) raises `ValueError` for `period_month` values that pass the rung-35 regex — year `0000` (any month) and `9999-12` — so `POST /ill/partners/{id}/invoices` genuinely answers `ERR_INTERNAL`/500. One paragraph was added to the §5 preamble (no new table row, since it is not a domain check and holds no ladder rung) and the preamble's "Every error response…" claim was softened to match.

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` is **502 lines**, versus 496 for `PRD_FINALIZED.md` and 494 for `PRD.md`; `cmp` confirms it is **not** byte-identical to `PRD_FINALIZED.md` (the tell that a Step 9 scan never ran). +17,819 chars over its source.
- It still ends at a real section boundary — the final row of the §5 error table (`| \`ERR_DAMAGE_FEE_EXCEEDS_REPLACEMENT\` | 422 |`) — and still has all 5 `##` sections. No truncation.
- `find` over `workspace/implementation` confirms **no `.py` file was modified after the clean sweep at 09:49:32Z**, so the 8/8 × 95/95 green result still describes the shipped implementation. Steps 8 and 9 touched documentation only.
- Only one `worklog.md` exists in the task tree (no cwd-drift strays under `workspace/`).

**Pipeline complete.** Step 9 has written `workspace/PRD_COMPLETED.md`.
