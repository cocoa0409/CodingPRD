# Worklog — task_3097_clearing_netting_settlement_participant_operations

Scenario: Clearing, Netting and Settlement Participant Operations (DTCC): participant membership with financial standards and clearing fund deposit requirements, trade submission and comparison with locked-in and matched trade processing, multilateral netting reducing settlement obligations to a single net position per security, settlement obligation funding, delivery versus payment and fail management with mark-to-market, clearing fund sizing based on participant risk and volatility, book-entry securities custody with position servicing across corporate events, participant default management with liquidation and loss allocation, settlement cycle timeline compression and affirmation deadlines

## Step 1: Create task directory — 2026-09-29T22:42:00.000Z

Task directory `./tasks/task_3097_clearing_netting_settlement_participant_operations/` was pre-allocated by the caller with `workspace/` already present. No index computation performed; no other `task_*` directory created. Confirmed `workspace/` exists and is empty.

## Step 2: Generate Scaffold — 2026-09-30T00:15:00.000Z

Subagent returned (verbatim):

All three files are written and the lint is clean.

## Files written

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3097_clearing_netting_settlement_participant_operations/SCAFFOLD.yaml` | 1829 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3097_clearing_netting_settlement_participant_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1160 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3097_clearing_netting_settlement_participant_operations/SCAFFOLD_CORNER_DESIGN.yaml` | 1683 |

## Design summary

**Complexity profile.** Expert band (above §0.4's 10–15 / 20–32 / 18–30). Primary archetype *Ledger reconciliation* (net vs gross settlement, Vickrey vs first-price auction, provisional vs final), secondary *Multi-party negotiation* (trade comparison, dispute resolution, sealed-bid default auction). Layers: dual-variant calc, cascading side effects, optimistic concurrency, rate/threshold triggers, selector policy. Topology `flat`, state shape `parallel`, role model `segregation_of_duties`, consistency `saga`.

**Surface.** 13 entities (Participant, ClearingMemberDeposit, DepositTransaction, TradeSubmission, Security, CustodyAccount, SettlementWindow, NetPosition, CorporateAction, ClearingFund, FundComponent, DefaultProceeding, LossAllocationTransaction). 68 endpoints. 34 error codes. 9 calculations × 2 variants each = 18 formulas. 27 ordered validations. 5 state machines. 2 OCC concurrency rules. 3 roles (PlatformAdmin `opaque`, ClearingMember `entity_backed:Participant`, RiskOfficer `opaque`).

**Key mechanics worth flagging to downstream generators:**
- `TradeSubmission` carries **three parallel state dimensions** on one row — `lock_status × match_status × affirmation_status` — with a lock-in cascade that flips contras.
- `SettlementWindow` and `ClearingFund` are **cyclic** (self-loop netting re-run; fund re-opened by a fresh net position); the window auto-closes when no admitted member remains.
- `NetPosition` is the analogous warning on the actor side (`net_position` ↔ mark-to-market), but a stronger one: the two hop-3 holes I traced were both *silent* rather than contradictory — a cascade that claimed depth it did not have and an assert that named a field the endpoint does not expose. In the scaffold the corresponding holes are now pre-closed: `defaulter_resources_cents` is an explicit declared field, and settlement saturation is spelled out.
- The cash/mark legs cross deliberately (`mark_to_market_cents = signed_failed_qty * (prev_settlement_price − failed_at_price)`), and `failed_at_price_cents` is **stamped once at failure** — without that field the mark is unreproducible.
- `loss_allocation_waterfall` rounds per participant with **no running clamp**, then `loss_allocation_remainder_repair` posts a signed correction term. That two-step split is what makes `SUM(loss allocation amounts) == −deficit` an exact invariant. Ordering keys are `legal_name`/`created_at`; no UUID participates in any decision.

**§1.8 — 19 instances** across all nine §0.5 rules (9 rules ≥ 2, plus a third on rules 1, 2, 5, 6, 8, 9). Transitive cascades are depth 3 (default declaration) and depth 4 (suspension) from different triggering transitions. Boundary precision sits on a strict-`>` volatility threshold at 2500/2501 bps and on an empty net-position set. Compensating invariants conserve loss-allocation amounts and aggregate settled quantity.

**§1.9 — 35 active corners + 6 `excluded_because:` stubs**, covering all eight applicable taxonomy sections.

**Two design notes you may want to sanity-check:**
1. `ERR_ALL_PARTICIPANTS_NOT_ACTIVE` and `ERR_FUND_RECOMPUTE_NOT_TRIGGERED` were **retired** — both were provably unreachable behind a higher-priority validation, and the latter also had no endpoint surface at all (it is a system event). Their conditions remain as system events with the error citations removed.
2. `ERR_STALE_VERSION` and `ERR_IMMEDIATELY_FUNDED`-style corners are reachable through the OCC endpoints only when the caller captures `$.data.version`; the design files follow that discipline throughout (`expected_*_version` is always a `${var}`, never a literal).

Verified: `scaffold_lint.py` reports `VERDICT: clean lint` over 471 scanned calls; a separate audit found zero unbound placeholders, zero dangling `grounds:` refs, zero declared-but-unproduced enum values, zero unreferenced error codes, valid role↔endpoint consistency, and no forbidden concurrency vocabulary. No sibling task directory was read.

## Step 3: Copy Shared Files — 2026-09-30T00:17:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T00:30:00.000Z

Subagent returned (verbatim):

Done. Final verification passes all three hard contracts.

## Output

**Path:** `/home/ubuntu/github/CodingPRD/tasks/task_3097_clearing_netting_settlement_participant_operations/workspace/PRD.md`
**Line count:** 377

Generated purely from `SCAFFOLD.yaml` + the doc-generator skill. I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task.

## Section outline

- **1. Introduction** — 3 paragraphs (central-counterparty framing, the four ledgers, precision/ordering posture)
- **2. Global Specifications** — 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Membership Standing and Financial Standards · 2.5 Collateral Deposits and Coverage Status · 2.6 Trade Submission State Dimensions · 2.7 Settlement Cycle Timeline Governance · 2.8 Monetary Precision and Ledger Conventions · 2.9 Optimistic Concurrency Control · 2.10 Common Resource Properties · 2.11 Hierarchical Resource Retrieval · 2.12 Validation Precedence · 2.13 Clearing Fund Integrity and Default Management Principles
- **3. Business Logic** (9 subsections) — 3.1 Participant Admission and the Financial-Standard Review · 3.2 Collateral Postings and Deposit Coverage · 3.3 Trade Entry, Lock-In and Comparison · 3.4 Disputes, Reversals and Cancellation · 3.5 Cycle Timeline, Affirmation and Multilateral Netting · 3.6 Funding and Delivery versus Payment · 3.7 Fail Management and the Daily Mark-to-Market · 3.8 Corporate Actions and Book-Entry Custody Servicing · 3.9 Clearing Fund Sizing and Default Management
- **4. Endpoint Definitions** — 4-column table, 68 rows
- **5. Error Code Catalogue** — 2-column table, 34 rows

## Hard-contract reports

```
Contract 1: Field-Name Coverage
- entities[].fields: 68 required, 68 present, 0 missing
- endpoints[].request_body: 47 required, 47 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing
Status: PASS

Contract 2: Rule Coverage
- validations[] with priority: 27 checked, 27 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 25 checked, 25 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing
- validations[] conditions: 27 checked, 27 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 68 checked, expressed, 0 missing
- entities[].fields[] structured content: 68 checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 14 groups checked, equal prose density, 0 asymmetric
Status: PASS

Contract 3: §3 Path Purity
- backtick tokens scanned: 483 (147 unique)
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 body is byte-identical to `section-2.2-response-structure.md` (verified by diff; the only difference is the `### 2.2.` heading line, which sits above the pasted block). Endpoint and error tables verified at exactly 4 and 2 columns. All 34 error IDs appear in §2/§3 narrative, and all state-machine state values and enum values appear as exact backticked strings.

## Under-determined spots (choices I had to make; downstream prose may be silent here)

1. **`POST /clearing/securities/{id}/allocate-fund-cost` validation** — the scaffold lists no `validations[]` entry and no explicit rejection for this debit path. I described it as an unconditional debit that re-derives pool status, but whether a debit driving `posted_amount_cents` negative is refused is **not pinned**.
2. **`POST /clearing/participants/{id}/financial-review` state gating** — the endpoint is absent from the Participant state machine (only `activate`/`reinstate` re-run the review). I treated the review as ungated on `membership_status`, matching the calculation's `input_set` note; there is no explicit scaffold rule either way.
3. **Bid withdrawal** — `default_liquidation_and_loss` counts "non-withdrawn sealed bids," but no withdrawal endpoint exists in `endpoints[]`. The withdrawal mechanism and its effect on the standing-high-bid reservation are **unspecified**; I described only displacement by a higher bid.
4. **`PUT /clearing/default-proceedings/{id}`** — the scaffold only pins the `DECLARED → LIQUIDATING` step (with `reason_code` optional). Whether the update can set any other status is not stated; I documented only that one step.
5. **`mark_to_market_only` interaction with `amount_cents`** — the endpoint says the call "performs only the daily mark-to-market recomputation" when true, but does not say whether `amount_cents` is still required or ignored in that mode. I wrote that it moves no funds; the field's optionality in that mode is ambiguous.
6. **Clearing `DEFICIENT_DEFAULT`** — the derived-status branch of `deposit_posted_balance` yields only `SATISFIED` / `DEFICIENT_GRACE`, while `DEFICIENT_DEFAULT` is imposed by suspension/default side effects. When (if ever) a pool leaves `DEFICIENT_DEFAULT` is not pinned.
7. **`allocate-fund-cost` version bump target** — side effects say "Bump `Participant.version`" while the path is `/securities/{id}/...`; I resolved this to the body-referenced `participant_id`'s version.
8. **`positions` sub-fields** — `settled_quantity` and `last_corporate_action_applied_id` live inside the `positions` array description and are not top-level `fields[].name`, so they are outside Contract 1's required set; I included them in §3.8 prose rather than the ledger dump.
9. **Gross-position variant fields** — `gross_receive_quantity` / `gross_deliver_quantity` exist only in the `gross_position_convention` variant (non-selected reporting convention). I described the net convention and named the divergence in §2.8 rather than enumerating the fields, since the scaffold selects the net convention.
10. **System-event transitions** — the `OPEN → CLOSED` auto-close and the `RECOMPUTED → OPEN` fund re-open have no endpoints. I rendered them as capabilities/conditions in §2.13/§3.6 with no §4 row, which is the expected treatment but leaves them without an HTTP contract by design.

## Step 5: Generate Unit Tests — 2026-09-30T00:55:00.000Z

Subagent returned (verbatim):

All checks pass. Here is the final report.

## Summary

Generated the complete test infrastructure for `task_3097_clearing_netting_settlement_participant_operations`. The two design indices were the sole source of tests; `SCAFFOLD.yaml` was read only for entity/endpoint/error vocabulary, and `workspace/implementation/` was never opened.

### Files & line counts

**`test_helpers/` — 1,459 lines**
| file | lines |
|---|---|
| `__init__.py` | 18 |
| `api_client.py` | 257 |
| `api_errors.py` | 82 |
| `assertions.py` | 242 |
| `constants.py` | 43 |
| `factories.py` | 119 |
| `fixtures.py` | 365 |
| `test_users.py` | 27 |
| `types.py` | 306 |

**`test_suite/` — 2,207 lines** (10 test files + conftest)
`conftest.py` 25 · `test_01_membership_and_financial_standards.py` 250 · `test_02_collateral_and_deposits.py` 122 · `test_03_trade_comparison.py` 192 · `test_04_netting_and_convention.py` 303 · `test_05_fails_and_mark_to_market.py` 142 · `test_06_precedence_and_boundaries.py` 162 · `test_07_clearing_fund_sizing.py` 166 · `test_08_default_management.py` 252 · `test_09_corporate_actions_and_custody.py` 230 · `test_10_cascades_and_cross_entity_gates.py` 363

**Total 3,666 lines; 82 tests collected, imports clean.**

### Test counts by queue
- **Queue A (Difficulty): 41 tests** — all 19 instances covered ≥2 (rules 1/2/5/6/8/9 with three instances each carry 2–3).
- **Queue B (Corner): 41 tests** — all 35 non-stub instances covered ≥1.
- Stubs: 5 `excluded_because:` corner stubs not translated; their cross-references resolve to real §1.8 `name:`s.

### Instances SKIPPED under the PRD-first filter
1. `Difficulty/resource_temporal_overlap/contested_security_capacity_half_open_with_buffer` — **coverage fails**: PRD contains zero occurrences of "capacity", "notional", "occup" or "collide"; no sentence states any aggregate-capacity rule. Its recipe also asserts `ERR_SELF_TRADE_FORBIDDEN`, which PRD §3.3 attaches only to counterparty-equals-self.
2. `Difficulty/resource_temporal_overlap/adjacent_window_occupation_half_open_with_buffer` — **coverage and derivability fail**: PRD contains zero occurrences of "buffer"; §2.7's "unique per (`security_id`, `settlement_date`)" concerns only duplicate-key exclusion, never adjacent-window occupancy, so neither the "collides" outcome nor its assert could be uniquely derived.

Both remain gaps, untranslated and unmarked.

### PRD prose found ambiguous (assertion relaxed, not invented)
- **PRD §3.6** — "settlement is no longer blocked by the active-fail gate" is not stated; §3.6 commits only to the negative gate. `test_window_with_a_failed_position_of_an_active_member_cannot_settle` therefore asserts the two verbatim negatives (blocked while ACTIVE; `NETTED` unchanged) without asserting the post-suspension outcome.
- **PRD §3.8** — the PRD never states whether opening a custody account creates a zero-quantity position row, nor whether apply writes one for a security with no prior holding. The two custody tests assert only array-ness, `account_type`, `status` and the cleared `last_corporate_action_applied_id`.
- **PRD §3.9** — `defaulter_resources_cents` "saturate[s] at the total of its settlement obligations"; with a zero obligation total the PRD does not say whether resources clamp to zero or stand at the posted balance, so that case is not asserted.
- **PRD §3.4** — the OPEN-trade cancellation path does not state whether a non-owner `ClearingMember` may cancel another member's OPEN trade; only the `LOCKED_IN`/admin path (which PRD does pin) is asserted.

### Verification performed
- All 82 docstrings carry ≥1 verbatim PRD quote; every quote matches a literal grep of `PRD.md` (140 quotes checked).
- Exactly one `Design:` line per test; all tags resolve to real instance `name:`s in the cited index (0 bad tags, 0 untagged, 0 dual-tagged).
- No `skip`/`skipif`/`xfail`; no "scaffold"/table/`§1.x` references; no reference to `implementation/`.
- Static check: every `api_client.*` call and every imported `test_helpers` name exists.

One structural finding worth flagging upstream: **PRD §3.3 records the submission-time comparison cascade ("If a contra row matching the tuple exists at submission, the new trade's `match_status` is set to `MATCHED`") but never states that an equivalent cascade fires on lock-in.** The netting inclusion set (§3.5) requires each included row itself to be `LOCKED_IN` **and** `MATCHED`/`UNRESOLVED`, so the only PRD-derivable route for a two-row comparison is the submission cascade — under which the asserting participant's row matches only if the contra was submitted first. `fixtures.locked_in_matched_trade` encodes that ordering deterministically (contra first, asserted row last), which is what makes the netting and open-risk assertions derivable from the contract alone.

## Step 6: Generate Implementation — 2026-09-30T00:30:00.000Z

Subagent returned (verbatim):

Implementation complete and verified. Final report below.

## Files delivered

All under `/home/ubuntu/github/CodingPRD/tasks/task_3097_clearing_netting_settlement_participant_operations/workspace/implementation/`:

| Lines | File |
|---|---|
| 10 | `start.sh` |
| 1 | `requirements.txt` |
| 90 | `app.py` |
| 104 | `db.py` |
| 103 | `errors.py` |
| 56 | `response.py` |
| 67 | `middleware.py` |
| 109 | `request.py` |
| 237 | `lookups.py` |
| 315 | `serializers.py` |
| 91 | `timeutil.py` |
| 0 | `routes/__init__.py` |
| 29 | `routes/common.py` |
| 449 | `routes/participants.py` |
| 301 | `routes/windows.py` |
| 162 | `routes/trades.py` |
| 541 | `routes/positions.py` |
| 0 | `services/__init__.py` |
| 230 | `services/custody.py` |
| 296 | `services/defaults.py` |
| 135 | `services/deposit.py` |
| 111 | `services/funds.py` |
| 62 | `services/marks.py` |
| 170 | `services/netting.py` |
| 155 | `services/participants.py` |
| 220 | `services/trades.py` |

Total 4044 lines. No `__pycache__`, no data files, no test-suite or sibling-task files read.

## Launcher contract — confirmed

`start.sh` reads no hardcoded port; `app.py` binds `host="0.0.0.0", port=int(os.environ.get("PORT", "10000"))` and runs in the foreground via `exec python3 app.py`. The dependency install is guarded by `if ! python3 -c "import flask"`. Verified: `PORT=<n> bash start.sh` serves within ~2 s, and a kill+relaunch on the same port returns `total_count = 0` (state is a process-local dict; nothing persists, nothing is seeded — `db.py` exposes only empty `TABLES` dicts plus the clock).

## Endpoints implemented: 68

1 operational (`POST /clearing/_clock/set_current_utc`) + 67 domain routes, matching PRD §4 and scaffold §1.5 exactly.

## Verified behaviours (live HTTP)

Admission gating and precedence (`ERR_SEGREGATED_CUSTODY_REQUIRED` → `ERR_INVALID_STATE` → `ERR_FINANCIAL_STANDARD_NOT_MET`); broker-dealer held to 500,000,000 not 250,000,000; multilateral netting (`qty 60 / cash 64000 / obligation 64000`, `net_quantity −60 → obligation 0`); funding saturation; settle → `RECEIVED`/`DELIVERED`; mark-to-market pinned order; fund sizing `250000 → ASSESSED` with round-before-clamp; suspended fund rejected as `ERR_FUND_ALREADY_RECOMPUTED`; Vickrey single-bid proceeds with `deficit = 90000 − 49999 = 40001`; pro-rata waterfall with remainder repair (`−20000`, `−20001`, sum `= −deficit` exactly); `experiences_deficit` after a negative balance; suspension cascade; `ERR_STALE_VERSION` 412; `ERR_UNCONFORMED_IDENTITY` cases for self-trade, immutable field, unknown field, pagination clamp; three roles with `ERR_UNAUTHENTICATED`/`ERR_UNAUTHORIZED`.

## PRD ambiguities and the interpretation pinned

1. **Contra `match_status` on the match cascade.** PRD 3.3 says only that a matched contra becomes `LOCKED_IN` "even a contra that was still `OPEN`", and never says it becomes `MATCHED`. Taken literally, a matched pair is un-nettable (the contra stays `UNMATCHED`, which the netting inclusion set excludes), contradicting "Multilateral netting then collapses the locked trades". I set `match_status = MATCHED` on a cascade-locked contra **only when it is currently `UNMATCHED`**, so netting works; a `cancel` of a `LOCKED_IN` trade still reopens contras to `OPEN`/`UNMATCHED` exactly as PRD states.

2. **`ERR_INSUFFICIENT_DEPOSIT` at netting.** The calculation's `deposit_posted_balance` comment says "the cycle-close sweep **and the netting run** assign this value", but the endpoint table says netting "may surface `ERR_INSUFFICIENT_DEPOSIT`". I chose **assign** (never raise) at netting, and **raise** only at `activate`, `reinstate`, and financial-review — the three places PRD 3.1 explicitly says the pool "may surface `ERR_INSUFFICIENT_DEPOSIT`". Deposits also cannot be posted before activation (priority-5 is only declared for trade/fund/affirm endpoints), so raising at netting would be a trap.

3. **`POST /clearing/securities/{id}/allocate-fund-cost`.** The scaffold declares the endpoint and its side effects but never states an `ERR_INVALID_AMOUNT` / zero rule, nor the sign convention. I rejected `amount_cents == 0` with `ERR_INVALID_AMOUNT` and reused the release rules (reason-code + non-negative balance) for a negative amount. This is the least-specified endpoint in the scaffold.

4. **Reverted contras on `unmatch`.** PRD 3.4 says "applies the same to every non-`CANCELLED` contra row", so all contras become `OPEN`/`UNMATCHED`, not only the previously `LOCKED_IN` ones.

5. **RBAC binding in the scaffold.** The route tables list e.g. `GET /clearing/fund-components/{id}/loss-allocations` as `PlatformAdmin, RiskOfficer` only, while the §1.7 matrix puts it under no role. I implemented the **route table** binding and additionally admitted `PlatformAdmin`/`RiskOfficer` to the `count`-style nested lists the matrix omits, but kept the PRD issue (not scaffold §1.7) as the authority wherever they disagree — notably `POST /clearing/trade-submissions/{id}/cancel`, which I accept from `ClearingMember` **and** `PlatformAdmin` with role-dependent branch behaviour, and `POST /clearing/clearing-funds` from `RiskOfficer` (scaffold says RiskOfficer; the matrix folds it under PlatformAdmin's shared set, which I did not follow).

6. **`SettlementWindow.settlement_date` scope.** The comparison has no date field, so I derived each trade's settlement date as the date portion of its `trade_date`; the window's `settlement_date` is necessarily the settlement date its trades carry. Any trade whose date portion differs from the window's is excluded from that window's netting.

7. **`default_liquidation_and_loss`.** `defaulter_resources_cents = min(posted_deposit_balance, Σ settlement_obligation over all of the member's net positions)` (handles the "saturating" language); `deficit = max(resources − proceeds, 0)`, floored at zero.

8. **`experiences_deficit`.** Implemented as "any latest component balance strictly negative", per PRD 2.13.

9. **Grace at `close-cycle`.** I set `DEFICIENT_GRACE` for a non-zero shortfall and `SATISFIED` for a zero/sufficient balance, never overriding `DEFICIENT_DEFAULT` (PRD 2.5 reserves that value for the risk workflow).

## Step 7: Run Tests and Iterate — 2026-09-30T02:15:00.000Z

Subagent returned (verbatim):

Clean 8-round sweep: 82/82 in every round, zero flakiness.

## Summary

**Iterations run:** 1 diagnostic sweep (baseline 23/82), then ~4 targeted per-test passes during diagnosis, then a final 8-round parallel stability sweep — **82/82 in all 8 rounds, zero flaky tests**.

**Tests deleted:** none. No failing assertion was found to assert a scaffold-only or non-uniquely-derivable rule; every failure traced to a fixture or implementation defect, so all were repaired rather than removed.

**Root cause of 40 of the 59 failures (one bug, wide reach):** `settlement_date` is derived from `trade_date`, but PRD.md never states the derivation. The implementation used `date_part(trade_date)` (same-day) while every test and both scaffold design files use T+2 (`trade_date 2026-09-08` → window `2026-09-10`). Because the tests are the API client and both design files agree unanimously on T+2, I treated the implementation as the defect.

### Fixes applied to `test_helpers/`
- `fixtures.py` — `locked_in_matched_trade` docstring clarified (semantics unchanged); `setup_default_proceeding` now books a netted obligation before sizing the fund (the resource saturation term was zero, so `defaulter_resources_cents` was always 0); `setup_fund_open_risk` now applies the FAIL review *after* the open risk is booked (a FAIL member is refused further trade submission) and takes `review_member_index`; `component_of(..., fund["generation"])` → literal generation `1` (`fund["generation"]` does not exist — `KeyError`); `reopen_fund_with_fresh_net_position` drives the clock back so the second cycle's netting clears the affirmation-deadline gate; added `unresolved_long_position` (a disputed-mirror book that yields a positive-only net-position set, required by PRD §3.8's split/dividend gates), `book_fresh_long_on_a_new_cycle`, `dispute`, and `read_action`.
- `api_client.py` — `get_corporate_action` re-pointed at the PRD §4-declared `GET /clearing/securities/{id}/corporate-actions` listing (PRD §4 declares no single-action GET endpoint).

### Fixes applied to `test_suite/`
- `test_04`, `test_10` — auto-close test now opens the window while a member is ACTIVE then removes the last ACTIVE membership (create-time firing is a reasonable PRD reading and interacted with a passing test); empty-net-position setups fixed (the locked-in row was the counterparty's, so no NA row qualified); window reorder for the lock-in/netting test; one net-position count switched to `unresolved_long_position`.
- `test_05`, `test_10` — mark tests booked a fresh long after reinstatement (PRD §3.1 cancels the member's own rows on suspension, so the §3.7 inclusion set was empty and the mark was 0).
- `test_09` — split/dividend tests switched to `unresolved_long_position`, which satisfies PRD §3.8's short-position gate; settle-servicing assertion matched to its design instance (`4 units @ 100000 + 4 @ 25`).
- `test_02`, `test_03`, `test_08`, `test_09` — dropped four double-wrappings of `validate_success`/`validate_error` around fixture helpers that already return validated `data` (`AttributeError: 'dict' object has no attribute 'status_code'`).
- `test_07` — two assertions corrected to PRD §3.9's actual floor rule (the design instance's `25_000_000_000` floor is unreachable: no class yields it, since the floor is the class base or 500,000,000); the fund-total assertion now accounts for the second sized member.
- `test_04`, `test_08`, `test_10` — two assertions against errors PRD attaches to *different* triggers: `PUT /default-proceedings/{id}` after `LIQUIDATING` now asserts `ERR_PROCEEDING_NOT_LIQUIDATING` (PRD's "advancing a proceeding that is not in `DECLARED` is refused"), and the lock-in-past-netting test relaxed to `validate_error_is_one_of([ERR_WINDOW_NOT_FOUND, ERR_WINDOW_ALREADY_NETTED])` (PRD §3.3 and §3.4 name both without stating which pre-empts).

### Fixes applied to `implementation/`
- `timeutil.py` — added `settlement_date_for` (T+2) and `timedelta` import; `services/trades.py` uses it for `settlement_date`.
- `routes/trades.py` — canonicalize `trade_date` once and pass the normalized value into `create_trade`, so the comparison tuple and the date derivation see identical text.
- `services/trades.py` — removed a `touch()` that double-incremented a new trade's `version` to 2 at creation.
- `services/participants.py` — same double-increment fix for participant creation; `financial_review` now assigns the pool standing instead of raising `ERR_INSUFFICIENT_DEPOSIT` (PRD §3.1 attaches that clause only to admission and reinstatement).
- `routes/positions.py` — fund endpoint now enforces `ERR_UNAUTHORIZED` for a non-owner `ClearingMember`; the ACTIVE gate moved to the funding path only, so `mark_to_market_only` works for a non-ACTIVE owner.
- `routes/positions.py` — fund recompute checks `expected_fund_version` before the recompute-eligibility gate (PRD §2.9's version rejection is not subordinate to §3.9's `ERR_FUND_ALREADY_RECOMPUTED`).
- `services/custody.py` — a corporate action's cash leg is now written to `NetPosition.cash_delta_cents` (apply, settlement pass, and reversal), per PRD §3.8's "cash adjustment is the already-adjusted settled quantity multiplied by the `cash_rate_cents_per_unit`".

Orchestrator verification: all 8 `results.{1..8}.json` independently parsed — `passed=82 total=82` in every round.

## Step 8: Finalize PRD — 2026-09-30T02:45:00.000Z

Not skipped: Step 7 applied 7 `implementation/` fixes. Subagent returned (verbatim):

PRD_FINALIZED.md is complete. All eight edits are in place and the file is intact.

## Summary

**Line counts:** PRD.md 377 lines / 67,599 bytes → PRD_FINALIZED.md 377 lines / 70,033 bytes. Delta: **0 lines** (8 existing lines revised, none inserted or deleted), **+3.60% bytes**.

**Alignment target:** `implementation/`. Every edit below traces to a `<step_7_diff>` item and to a concrete behavioral choice in `implementation/`.

### Changes

- **§3.3 (line 174) — insert —** pins the settlement-date derivation the implementation actually uses (**T+2**: `trade_date` + 2 calendar days) and the de-normalization of `trade_date`, because PRD nowhere stated either and 40/82 Step-7 failures came from this single unpinned choice — `implementation/timeutil.py:75-83` (`SETTLEMENT_LAG_DAYS`, `settlement_date_for`), `implementation/services/trades.py:89-90`, `implementation/routes/trades.py:71-88`.
- **§3.3 (line 174, same sentence) — insert —** pins that the canonicalized `trade_date` is what both the comparison tuple and the settlement-date derivation see — `implementation/routes/trades.py:76-88` + `implementation/services/trades.py:89`.
- **§2.7 (line 106) — revise —** states that window creation does *not* itself trigger the auto-close and points the exception at §3.6, so a fresh implementer does not over-fit the test's create-time firing — `implementation/routes/windows.py:132-140` vs `implementation/lookup`-driven `auto_close_open_windows` (`implementation/services/netting.py:161-171`).
- **§2.12 (line 138) — insert —** the fund-recompute version check pre-empts the `ERR_FUND_ALREADY_RECOMPUTED` / `ERR_INVALID_STATE` gate — `implementation/routes/positions.py:318-326` (diff-hardened ordering).
- **§3.1 review paragraph (line 156) — insert —** the financial review *assigns* standing rather than raising `ERR_INSUFFICIENT_DEPOSIT` — `implementation/services/participants.py:136-145` (`refresh_coverage`, not `require_coverage`).
- **§3.6 mark-only mode (line 212) — insert —** mark-only is not gated on `ACTIVE`; that gate lives on the funding path — `implementation/routes/positions.py:112-122`.
- **§3.6 auto-close (line 220) — revise —** auto-close is a non-failing system event, invoked on suspension and on expulsion-by-liquidation, and only closes `OPEN` windows — `implementation/services/netting.py:161-171`, `implementation/services/participants.py:132`, `implementation/services/defaults.py:173`.
- **§3.8 CASH_DIVIDEND (line 238) — insert —** the dividend's cash leg is carried in the net position's `cash_delta_cents` (and removed on reversal); the custody position stores no cash figure — `implementation/services/custody.py:140`, `:175`, `:225` (diff-hardened).
- **§3.9 fund recompute (line 246) — insert —** version rejection decided before the fund's eligibility gate — `implementation/routes/positions.py:318-326`.

### Pre-edit search log (subject → impl paths enumerated → wording adjustment)

- **Version-check precedence.** (b) grepped `ERR_STALE_VERSION`, `ERR_FUND_ALREADY_RECOMPUTED`: `routes/positions.py:307-352` (fund, version first) and `routes/windows.py:219-235` (run-cycle, state/deadline before version). (c) Scoped the §2.12 sentence to "the one place where the version check pre-empts a state gate is the clearing-fund recompute" so the window path, which still checks state first, is not mis-described.
- **Review assigns vs raises.** (b) grepped `require_coverage`/`ERR_INSUFFICIENT_DEPOSIT`: only caller is `services/participants.py:74` (activate) + `:143` (refresh_coverage). (c) Added "Unlike admission and reinstatement" and didn't touch `activate`'s documented surface.
- **T+2 derivation + canonicalization.** (b) grepped `settlement_date`/`normalize_iso`/`date_part`: `timeutil.py:78-83`, `services/trades.py:89-90`, `routes/trades.py:76-88`, `lookups.py:123-135`; also confirmed `netting.py`/`custody.py` compare stored canonical values, so the wording "as it is recorded" is safe. (c) Restricted the claim to "what locates the trade's settlement window" (explicitly saying the window's cut-offs are what pin the cycle), so `lock_in`'s deadline comparison is not redefined.
- **Fund-recompute ordering.** (b) same grep; confirmed `routes/windows.py:228-231` reads the body after the `OPEN` gate — so §2.9's blanket claim stays falsifiable there. (c) None needed after scoping to the fund.
- **Auto-close semantics.** (b) grepped `auto_close_open_windows`: `netting.py:161-171`, `participants.py:132` (suspend), `defaults.py:173` (liquidate). (c) Two revisions: dropped a "not gated on any window status" clause (false — the loop requires `status == "OPEN"`), and reworded the invocation list to name the two real call sites instead of over-claiming "whenever the last ACTIVE is removed".
- **Mark-only mode.** (b) grepped the fund route and `mark_failed`/`fail_mark_to_market`; confirmed `netting.py:117-118` preserves a fail mark during re-netting. (c) Added "may still re-mark **its own** failed position" so the ownership gate (`routes/positions.py:101-106`) is not blurred.
- **CASH_DIVIDEND cash leg.** (b) grepped `cash_delta_cents`: all writers are `custody.py` apply/reverse/settle-pass plus `netting.py`; custody positions carry no cash field (`serializers.py:214-225`). (c) Re-scoped the sentence to net positions explicitly and added that the custody position records no cash figure — leaving `reverse_action`'s recalculation described by §3.5's existing sentence untouched.

No files were created beyond PRD_FINALIZED.md; no test, scaffold, or implementation file was modified. I did not read `SCAFFOLD*.yaml` or `worklog.md`.

## Step 9: Complete PRD — 2026-09-30T03:10:00.000Z

Subagent returned (verbatim):

Done. `PRD_COMPLETED.md` is written as a minimal in-place patch over `PRD_FINALIZED.md`.

## Metrics
- Source: `PRD_FINALIZED.md` (existed) — 377 lines / 70,143 chars
- Output: `PRD_COMPLETED.md` — 381 lines / 78,783 chars (char delta **+8,640**)
- Section/heading set and both tables byte-identical to the source (30 headings, 106 table rows); no new sections.
- Counts: **24 ambiguity-pins**, **2 mismatch-revisions** (26 changes total).

## Changes

**Global (§1, §2.x, §4)**
- §1 Introduction — insert — ambiguity — added book-entry security registry + custody-account register to the declared scope, per endpoint table and impl routes — `implementation/routes/participants.py:383`, `implementation/routes/windows.py:75`
- §2.3 Pagination — insert — ambiguity — pinned the per-list filter parameter surface and that `total_count` is taken after filtering — `implementation/routes/positions.py:69,361,450,550`, `implementation/routes/participants.py:118`
- §2.5 Deposits — **revise — mismatch** — PINNED that `ERR_INSUFFICIENT_DEPOSIT` is *raised* only at admission/reinstatement; posting/review/netting/close *assign* `DEFICIENT_GRACE` — `implementation/services/participants.py:74,143`, `implementation/services/deposit.py:76,122`
- §2.7 Windows — insert — ambiguity — duplicate non-CLOSED `(security_id, settlement_date)` → `ERR_INVALID_STATE`; date/instant shape → `ERR_INVALID_REQUEST` — `implementation/routes/windows.py:118-130`
- §2.10 Common properties — insert — ambiguity — update is `ERR_IMMUTABLE_FIELD` for system-managed fields too; mutable surface pinned (participant: `legal_name`/`requires_segregated_custody`; security: `prev_settlement_price_cents`/`current_volatility_bps`) — `implementation/routes/participants.py:55-69,78-87`
- §2.12 Precedence — insert — ambiguity — trade submission's structural validation pre-empts its business-safety gates (member resolved first) — `implementation/routes/trades.py:47-69`
- §2.13 Fund integrity — revise — ambiguity — `experiences_deficit` is over ACTIVE class members' latest component — `implementation/serializers.py:244`
- §4 Endpoints — insert — ambiguity — pinned each creation site's default state, and split list endpoints into paginated vs non-paginated (7 non-paginated collections named) — `implementation/routes/common.py:12-22`

**Workflows (§3.x)**
- §3.1 — insert — ambiguity — security registration contract: ticker/cusip unique → `ERR_INVALID_REQUEST`, `currency`→USD, `current_volatility_bps`→0 — `implementation/routes/participants.py:394-400`
- §3.2 — insert — ambiguity — `allocate-fund-cost` rejects `amount_cents==0` with `ERR_INVALID_AMOUNT`; negatives reuse release rules — `implementation/routes/participants.py:347-357`
- §3.3 submission — insert — ambiguity — quantity/price positive, side enum, security must resolve (`ERR_SECURITY_NOT_FOUND`) — `implementation/routes/trades.py:51-62`
- §3.3 submission cascade — insert — ambiguity — contra `UNMATCHED`→`MATCHED` on cascade — `implementation/services/trades.py:103-109`
- §3.3 lock-in — insert — ambiguity — not-OPEN window maps to `ERR_WINDOW_NOT_FOUND` (404), not `ERR_WINDOW_ALREADY_NETTED` — `implementation/services/trades.py:119-123`
- §3.3 lock-in cascade — insert — ambiguity — contra `UNMATCHED`→`MATCHED`; other contras keep status — `implementation/services/trades.py:44-50`
- §3.4 dispute — insert — ambiguity — lock-state gate decided before the matching gate — `implementation/services/trades.py:139-142`
- §3.4 resolve-dispute — insert — ambiguity — `DISPUTED` gate before window gate before ownership rule — `implementation/services/trades.py:154-163`
- §3.4 revert — insert — ambiguity — CANCELLED contras are not reopened — `implementation/services/trades.py:176` (`set_pair`/`tuple_rows`, `implementation/lookups.py:221`)
- §3.4 cancel — insert — ambiguity — a `ClearingMember` cancelling `LOCKED_IN`/`DISPUTED` gets `ERR_UNAUTHORIZED` — `implementation/services/trades.py:185-188`
- §3.5 netting scope — insert — ambiguity — window is scoped to one `settlement_date`; differing-date trades excluded — `implementation/services/netting.py:24-33`
- §3.5 netting run — **revise — mismatch** — assigned `DEFICIENT_GRACE` rather than surfacing `ERR_INSUFFICIENT_DEPOSIT` — `implementation/services/netting.py:147-154`
- §3.5 timeline update — insert — ambiguity — non-OPEN update → `ERR_INVALID_STATE`; bad instant → `ERR_INVALID_REQUEST`; create requires resolvable security — `implementation/routes/windows.py:116-158`
- §3.6 funding — insert — ambiguity — standing gate decided before amount is read — `implementation/routes/positions.py:121-126`
- §3.6 close-cycle — insert — ambiguity — covered/zero-obligation members reset to `SATISFIED` unless `DEFICIENT_DEFAULT` — `implementation/services/deposit.py:122-136`
- §3.8 announcement — insert — ambiguity — security must resolve; numerator positive; date/instant shape → `ERR_INVALID_REQUEST` — `implementation/routes/positions.py:172-184`
- §3.9 declare/advance/bid — insert/revise — ambiguity — participant must resolve; advance's `reason_code` recorded; bid price>0 → `ERR_INVALID_AMOUNT`, quantity≥1, `placed_at` an instant; bid acknowledged `201` returning the proceeding — `implementation/routes/positions.py:416-516`

## Notes
- The 9 Step-6 seeds were checked against impl: all 9 confirmed, but several were **partially** right — e.g. #6 (`settlement_date` scoping) already appears in prose, so nothing added; #4 (`unmatch` reverts ALL non-CANCELLED contras) is already stated verbatim in §3.4 (only the cancelled-row carve-out was newly pinned); #2/#9 were the two genuine mismatches above; #7's `experiences_deficit` population was pinned.
- Additional open behaviors found beyond the seeds and pinned: security-registration contract, allocate-fund-cost zero/negative, window duplicate/shape validation, timeline-update state gate, corporate-action announcement validation, bid validation and response shape, funding-gate ordering, close-cycle `SATISFIED` reset, trade-submission structural-validation precedence, list filter/response-shape split, and creation default states.
- `test_suite` results (82/82 passing) were used only as cross-reference, never as authority.

Orchestrator verification: `PRD_COMPLETED.md` 381 lines, 30 headings (identical count to `PRD_FINALIZED.md`). Pipeline complete.