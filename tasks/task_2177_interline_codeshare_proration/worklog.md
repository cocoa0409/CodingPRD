# Worklog — task_2177_interline_codeshare_proration

## Step 1: Create task directory — 2026-08-30T00:00:00.000Z

Created `tasks/task_2177_interline_codeshare_proration/` and `tasks/task_2177_interline_codeshare_proration/workspace/`. Index 2177 chosen (highest existing was 2176).

## Step 2: Generate scaffold — 2026-08-30T04:35:00.000Z

All three scaffold artifacts are written and verified.

## Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2710 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1783 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3629 |

## Surface counts

11 entities · 49 endpoints · 9 state machines · 9 calculation rules · 45 ordered validation rows · 51 error codes · 4 roles · 2 OCC concurrency rules. §1.8 = 21 instances across all 9 `rule_id`s (min 2 each); §1.9 = 71 instances (60 with recipes + 11 `excluded_because` stubs) across all 9 claim-guide sections. 92 unique instance names, zero collisions.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     11
  §1.8 instances scanned:     21
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  852

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

A supplementary audit script also confirmed: zero unbound `${var}` across all 852 calls plus every `setup:`/`assert:` line, every `grounds:` ref resolves (errors/calcs/priorities/entity fields/OCC ids), every stub's `difficulty_instance` exists in §1.8, all 51 error codes are reachable from a validation row, no forbidden concurrency vocabulary, and `SCAFFOLD.yaml` contains neither design key.

## How difficulty was pushed past Expert

- **Three dual-variant calculation pairs on three different subjects** — coupon revenue allocation (PROVISIONAL straight-rate vs FINAL SPA-first: 72260/4523/23217 vs 66601/12000/21399 on identical data), FFP mileage cost (chronological ESTIMATE 25500 vs retroactive single-tier TRUE_UP 23000), and FX conversion (submission-day 1.085 anchor vs period-fixing 1.120 anchor).
- **Deep calculation chain**: factor selector (4-part eligibility/specificity-ranking/created_at tie-break/straight-rate fallback) → weight with `factor_bp` → SPA off-the-top → residual pool → per-coupon round-then-grant-residual-to-heaviest → conservation slack bucket. All three §0.5 mode-(a)/(b)/(c) combinatorial forms are present, with the fee-tier evaluation order explicitly pinned to pre-fee gross.
- **Two 5-hop transitive cascades from different triggers**: memo-accept (memo → invoice + settled balances → coupon ADJUSTED → ticket dual-axis flip → carrier reproration counter/audit flag) and period-close (rate fixing → invoice CLEARED → settled balances → **FX-variance-driven** carrier suspension → agreement suspension). The second is the sharp one: the submit-time credit check passes at 269216 and only the 8684 FX variance breaks the 270000 limit at close.
- **Parallel + cyclic + branching state machines on distinct entities**: Ticket carries two independent axes; RejectionMemo cycles RAISED<->COUNTERED with a stage-3 cap then forks to arbitration where UPHELD carries the whole cascade and DENIED carries none; BillingInvoice forks on a `>=` comparison and rejoins at SETTLED; Carrier and ProrateAgreement both cycle ACTIVE<->SUSPENDED.
- **45-row precedence ladder** with three distinct dual-failure conflicts (state>fiscal, temporal>referential, safety>constraint), plus a deliberate FX-before-credit-limit ordering because the fiscal check cannot be evaluated without the converted figure.
- **Two genuinely different interval geometries**: agreements are closed-closed (a shared end day conflicts), settlement periods are half-open (a shared boundary instant is legal).
- **Two conserved quantities with compensating actions**: per-ticket fare identity (void-proration) and clearinghouse zero-sum across all carriers (invoice recall), both asserted before and after.
- Every formula-derived literal in both design files (2416/11500/13646/72708/46509/269216/277900/8684/97250/5100/2000/199 …) was computed by executing the §1.3 formulas in Python, not estimated.

## Step 3: Copy shared files — 2026-08-30T04:28:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2177_interline_codeshare_proration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-30T04:45:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — 447 lines, ~12,700 words. Built incrementally in 6 appends (no truncation).

**Structure:** §1 Introduction (3 paras) · §2 with 10 subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Identity/Timestamps/Versions, 2.5 Logical Clock, 2.6 Money/Basis Points/Rounding, 2.7 Validation Ladder, 2.8 OCC, 2.9 Cascades & Nested Reads, 2.10 Balances & Zero-Sum) · §3 with 9 workflow subsections · §4 endpoint table (4 cols) · §5 error table (2 cols). File ends at §5 — no audit footer.

**Coverage counts vs SCAFFOLD.yaml (grep-verified):**

| Item | Scaffold | In PRD |
|---|---|---|
| entities | 11 | 11 (all named + all 124 field names in backticks) |
| endpoints | 49 | 49 rows matched exactly |
| state machines | 9 | 9 (Carrier, ProrateAgreement, SettlementPeriod, Ticket x2 axes, Coupon, BillingInvoice, RejectionMemo, AuditSample) — all states/terminal states present |
| calculations | 9 | 9 (factor selection, revenue allocation, FFP cost, claim build, FX selection, undercharge extrapolation, audit population, memo aging, net position) |
| validation ladder | 45 | 45 numbered steps in exact priority order |
| error codes | 51 | 51 in §5 table, and all 51 also mentioned in §2/§3 prose |
| roles | 4 | 4, each with `identity:` translated |
| concurrency_rules | 2 | 2, both with write_endpoint + occ_field + error_id + 412 |

**Hard Contracts**

```
Field coverage check:
- entities[].fields: 124 required, 124 present, 0 missing
- endpoints[].request_body/input: 55 required, 55 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 45 checked, 45 expressed in prose (ordered ladder §2.7), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 44 checked, 44 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed (formula + constants + precision + variants), 0 missing
- validations[] conditions: 45 checked, 45 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 49 checked, 49 expressed, 0 missing
- entities[].fields[] structured content: 124 checked, 124 reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (PARTIALLY vs FULLY_REJECTED; UPHELD vs DENIED; CLOSED_IMMATERIAL vs CLAIM_RAISED; CLAIM_ACCEPTED vs CLAIM_DENIED; PROVISIONAL vs FINAL run; ESTIMATE vs PERIOD_TRUE_UP), 6 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 851
- tokens starting with `/`: 0 | bare HTTP-method tokens: 0 | method+path tokens: 0
Status: PASS
```

**§2.2** matches `section-2.2-response-structure.md` byte-for-byte (verified by substring equality).

**Deliberately indirect expressions:**
- Constants embedded in business context rather than named: `CLASS_WEIGHT_BP` / `FFP_MULTIPLIER_BP` given as basis-point values with plain-language glosses ("a business-class mile counts for 1.6 economy miles"); `CAP_MULTIPLE: 25` as "capped at 25 times"; `MEMO_RAISE_WINDOW_DAYS: 45`, `AUDIT_TIME_BAR_DAYS: 730`, `ARBITRATION_MIN_AGE_DAYS: 90` as day counts in narrative; FFP tier rates as "1400 minor units per thousand miles".
- Foreign keys are never declared as schema; parentage surfaces through actions ("names the `settlement_period_id` of the open clearance window").
- Endpoints in §3 are referenced only by state-transition framing, role+verb, or capability description (Contract 3).
- Validation `applies_to` scopes in §2.7 use unambiguous operation phrases instead of paths, so §2 stays out of API-reference form while §4 supplies the HTTP mapping.
- The two withheld design indices were not opened, grepped, or referenced.

**Orchestrator verification:** 447 lines; §4 present at line 335 with 49 endpoint rows; §5 present at line 391 with 51 distinct `ERR_` codes; file terminates cleanly — no truncation.

## Step 5: Generate unit tests — 2026-08-30T05:15:00.000Z

Generation complete.

## Files written

**`test_helpers/` (1,933 lines)**
| file | lines |
|---|---|
| `__init__.py` | 38 |
| `types.py` | 377 |
| `constants.py` | 94 |
| `api_errors.py` | 125 (52 error ids + HTTP map, registered with the framework) |
| `api_client.py` | 243 (one method per endpoint, incl. the `/_clock` hook) |
| `test_users.py` | 48 (opaque operator constant + per-carrier builders for the three `entity_backed` roles) |
| `factories.py` | 136 |
| `assertions.py` | 306 (per-entity + `assert_fare_conservation`, `assert_clearinghouse_zero_sum`, `assert_carrier_net_position`, `assert_specificity_score`) |
| `fixtures.py` | 566 (5 tiers, up to `setup_cleared_invoice_with_raised_memo` and `setup_audit_sample_in_review`) |

**`test_suite/` (3,743 lines, 102 tests)** — `conftest.py` plus `test_01_membership_and_agreement_book` (10), `test_02_calendar_and_fx_table` (6), `test_03_tickets_coupons_and_mileage` (12), `test_04_revenue_allocation` (17), `test_05_clearinghouse_billing` (16), `test_06_period_close_and_settlement` (4), `test_07_rejection_memos` (16), `test_08_audit_sampling` (10), `test_09_access_control_and_ladder` (11).

## Coverage

- **Queue A (Difficulty): 42 tests** — all 21 instances, exactly 2 tests each (each pair splits the instance's assert list into primary-outcome and side-effect/invariant halves).
- **Queue B (Corner): 60 tests** — all 60 non-stub instances, 1 test each. The 11 `excluded_because:` stubs were not translated; all 11 `difficulty_instance` cross-references were verified to resolve to real §1.8 instances.

## Instances SKIPPED

**None.** Every difficulty and non-stub corner instance passed both filter conditions. Three individual *sub-assertions* were dropped as not uniquely derivable (the instances themselves stayed, with their distinguishing aspect fully asserted):

- `carrier_registration_...` — dropped `created_at == 2026-08-01T00:00:00.000Z`: §2.5 lists the fields the logical clock stamps and `created_at` is not among them, so a PRD-only reader could stamp it from elsewhere.
- `carrier_id_is_a_bare_uuid_...` — dropped `created_at == updated_at on an unmutated row`: §2.4 only says `updated_at` is refreshed *when version advances*, leaving its value at insert open.
- `submit_without_a_published_quote_...` — dropped `provisional_rate_scaled == 0`: §3.6 pins "leaves every money field at zero"; a scaled FX rate is not a money field.

## Verification run

- `python3 -m py_compile` over all 19 generated `.py` files: **OK**.
- `pytest --collect-only`: **102 tests collected**, no `skip`/`skipif`/`xfail` anywhere.
- Automated audit: every test carries exactly one `Design:` line, all tags resolve to real instances, no dual tags, no stub tags.
- Citation audit: **194 PRD quotations, 100% survive a whitespace-normalised literal match against `workspace/PRD.md`**, none shorter than 8 words.
- `pyflakes` clean over `test_suite/` (only the intentional barrel re-exports in `test_helpers/__init__.py` flag as unused).

## Step 6: Generate implementation — 2026-08-30T05:00:00.000Z

Implementation complete and verified.

## Files written (`workspace/implementation/`, 2676 lines total)

| File | Lines | Contents |
|---|---|---|
| `app.py` | 74 | Flask entry point, blueprint registration, `ApiError`/`HTTPException` handlers, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 188 | In-memory dicts keyed by id, logical clock (epoch `2026-08-01T00:00:00Z`), ISO-8601-with-ms formatting, ISO/date parsers, `new_row`/`touch`/`serialize`/`ordered`, typed `must_find` -> the 8 `*_NOT_FOUND` codes |
| `errors.py` | 79 | All 51 error IDs with their HTTP statuses |
| `responses.py` | 57 | `meta`/`response_type`/`data` envelope, `req_…` request id, pagination meta (`limit`/`offset`/`total_count`/`has_more`) |
| `validation.py` | 227 | Ladder steps 1–3 and 6: header auth, role gate, typed body/enum/int/datetime/array checks, pagination bounds, ownership |
| `calculations.py` | 440 | `round_half_up`, FX selection/convert, factor selector, `plan_proration`/`commit_proration`, FFP estimate + period true-up, invoice claim build, memo aging, audit population derivation, undercharge extrapolation |
| `routes/` x 8 | 1611 | carriers, agreements, periods (+FX+clock), tickets, coupons, invoices, memos, audits |
| `start.sh`, `requirements.txt` | — | Guarded `pip install`, `exec python3 app.py` |

Storage is in-memory only; nothing is seeded, preloaded or hardcoded at startup (verified: a fresh boot returns `total_count: 0`).

## Endpoint coverage
**49/49** route+method pairs registered, matching the PRD §4 table exactly (5 carrier, 7 agreement/factor, 5 period/FX, 6 ticket/proration, 5 coupon, 5 invoice, 9 memo, 6 audit, 1 clock hook).

## Correctness spot-checks (three live smoke passes)
- **Ladder precedence** honored per-handler in ascending priority; OCC (steps 44/45) sits last.
- **Proration**: per-coupon `round_half_up` then residual to highest `weight_units` / lowest `coupon_number` (3-way split 33334/33333/33333 = 100000); FINAL honours SPA off-the-top while PROVISIONAL ignores it; the all-SPA case parks the whole `straight_rate_pool_minor` in the run's `unallocated_residual_minor`.
- **Dual-variant FFP**: estimate tiers read *before* the coupon's miles land (TIER_A 56000 then TIER_C 1125), true-up single-tiers the period (37125, delta -20000).
- **Invoice**: fee tier keyed on pre-fee gross (75 bp), late penalty 200 bp, two FX anchors giving `fx_variance_minor` 38900, credit-limit refusal fires (`ERR_CREDIT_LIMIT_EXCEEDED`).
- **Five-hop cascades**: memo accept/arbitrate-UPHELD walks memo -> invoice fork -> coupon `ADJUSTED` -> ticket `REPRORATION_REQUIRED`+`DISPUTED` -> carrier counter/`audit_flag`; period close walks clear -> balances -> over-limit suspend -> agreement sweep.
- **Zero-sum invariant** summed to exactly 0 after every balance-moving operation in both scenarios.
- Interval rules confirmed asymmetric: agreements closed-closed (shared endpoint date = conflict), periods half-open (back-to-back = legal).

## Boot smoke result
`PORT=8971 bash start.sh` -> server up in <1 s, `GET /interline/carriers` returns 200 with the correct envelope, `POST /interline/carriers` returns 201 with all system/computed defaults; process killed cleanly afterwards. All modules pass `python3 -m py_compile`.

One judgement call flagged: `created_at`/`updated_at` use real wall-clock time (PRD §2.5 enumerates the clock-stamped fields and does not include them), while list ordering uses a monotonic insertion sequence so `created_at`-ascending order is stable even if a test rewinds the logical clock.

## Step 7: Test and iterate to green — 2026-08-30T05:25:00.000Z

Task complete — the suite was already fully green, and I verified that the green is genuine rather than vacuous.

## Summary

**Iterations run:** 2 sweeps (initial 8-round sweep, then a final confirming 8-round sweep after a mutation audit). Zero fix iterations were needed.

**Result:** All 8 parallel rounds passed **102/102** on both sweeps. No test failed in any round, so there was no union failure set and the diagnostic protocol (STEPs 0–3) never had to be entered.

**Tests deleted:** None. No test failed either coverage (STEP 1a) or unique-derivability (STEP 1b), because no test failed at all.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None.

### Anti-vacuity verification

Because a green-on-the-first-sweep result is indistinguishable from a vacuous or leak-tuned suite by pass count alone, a mutation audit was run before exit. Three independent pinned constants in `workspace/implementation/calculations.py` were perturbed — `FEE_BP_TIER_1` 75→76 (ICH handling-fee tier 1, PRD §3.6), `HAIRCUT_MID_BP` 1500→1400 (audit coverage haircut, PRD §3.9), and `CAP_MULTIPLE` 25→26 (extrapolation cap, PRD §3.9).

The mutant scored **90/102**, with 12 tests catching it across four different test files:

- `test_05`: late-submission penalty, invoice listing filters, equal-and-opposite pending balances
- `test_06`: period-close rate fixing / FX variance, FX-variance-driven carrier suspension cascade
- `test_07`: memo amount vs. invoice claim, withdrawal release, arbitrated denial, acceptance balance moves, the five-hop acceptance cascade
- `test_08`: coverage/haircut derivation, cap-before-haircut ordering

That confirms the suite genuinely exercises the fee tiering, the FX double-conversion, the memo cascade and the audit extrapolation chain, rather than passing trivially. The original `calculations.py` was restored (verified byte-correct at the three constants) and the final confirming sweep was run against the restored code.

### Deliverables on disk

`workspace/implementation/results.1.json` through `results.8.json` are all present and correspond to the final confirming sweep against the un-mutated implementation, each 102/102. The mutant run was written to scratchpad, so it never touched the deliverable files. No stray `.bak`/`.orig` artifacts remain in the task tree.

### Orchestrator-side independent verification

- Re-read all 8 deliverable results files directly: each reports `passed == total == 102`.
- **Withhold-constraint audit of the Step 6 impl-generator transcript** (to rule out that the first-sweep green came from a design-index leak rather than from a complete PRD): parsed the agent's JSONL transcript and inspected the `input` of every one of its **57 `tool_use` calls**. Zero calls referenced `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, or `test_helpers/`. The implementation was built strictly from PRD.md + SCAFFOLD.yaml + INSTRUCTION.md, so the green reflects PRD completeness, not test-answer leakage.

## Step 8: Finalize PRD — SKIPPED — 2026-08-30T05:30:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes. `PRD.md` already determined every behavior the tests exercised, so there is no Step 7 diff to patch and `PRD_FINALIZED.md` is not produced. Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-08-30T05:40:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written.

## Summary

**Source vs. output**: `PRD.md` 447 lines / 92,300 chars → `PRD_COMPLETED.md` 447 lines / 98,094 chars (**+5,794 chars**, 0 lines added, 0 sections added, 27 lines edited in place).

**Counts**: 29 changes total — **23 ambiguity-pins**, **6 mismatch-revisions**.

### Changes

- **§2.1** — insert — ambiguity — `RevenueAccountant` ownership on factor attachment matches the parent agreement's `issuing_carrier_id` — `routes/agreements.py:189`
- **§2.1** — insert — ambiguity — `BillingAgent` escalation matches *either* invoice carrier side — `routes/memos.py:326-329`
- **§2.2** — insert — ambiguity — `api_request_timestamp` comes from real wall clock, not the logical clock — `responses.py:21` → `store.py:111`
- **§2.3** — insert — ambiguity — non-integer `limit`/`offset` and undeclared enum filter values are `ERR_INVALID_REQUEST`; unknown id-valued filters match nothing — `validation.py:189-212`
- **§2.3** — insert — ambiguity — ordering is a monotonic insertion sequence, not a `created_at` value compare, so it survives a clock rewind — `store.py:139,156-158`
- **§2.4** — insert — ambiguity — `created_at`/`updated_at` stamped from real wall clock (the flagged candidate; confirmed) — `store.py:106-108,134-147`
- **§2.5** — revise — ambiguity — clock hook answers 200 with a `data` object holding only `current_utc` — `routes/periods.py:216-222`
- **§2.7 step 3** — insert — ambiguity — the actual enforced integer bounds; `coupon_ids` has no length bound and may be empty; string fields checked only for non-emptiness; non-object JSON body rejected here — `validation.py:124-178`, `routes/*.py`
- **§2.7 step 18** — revise — ambiguity — agreement activation checks both carriers with `ERR_CARRIER_SUSPENDED` — `routes/agreements.py:249-254`
- **§2.7 step 27** — revise — **mismatch** — audit-draw currency check is on `sample_coupon_ids` coupons, not the derived population — `routes/audits.py:46-49`
- **§3.1** — revise — **mismatch** — `iata_code` two-character shape is not enforced — `routes/carriers.py:30`
- **§3.2** — revise — **mismatch** — factor `origin`/`destination` shape not validated; only literal `*` is a wildcard — `routes/agreements.py:180-181,210`
- **§3.2** — insert — ambiguity — the two unused factor value fields serialize as `null` — `routes/agreements.py:211-220`
- **§3.2** — insert — ambiguity — activation's suspended-carrier refusal code and its ladder position — `routes/agreements.py:246-267`
- **§3.4** — revise — **mismatch** — `ticket_number` thirteen-character shape not enforced — `routes/tickets.py:240`
- **§3.4** — revise — **mismatch** — coupon station codes not validated as three uppercase letters — `routes/coupons.py:19-20`
- **§3.5** — insert — ambiguity — a run rewrites `weight_units` on every coupon (0 for SPA-allocated and excluded); no coupon `version`/`updated_at` bumps; response is 201 with the `ProrationRun` — `calculations.py:240-256`, `routes/tickets.py:318-320`
- **§3.5** — insert — ambiguity — void-proration leaves `weight_units`, `coupon_status`, `adjusted_amount_minor`, `billing_invoice_id`, coupon `version` alone; answers 200 with the ticket — `routes/tickets.py:350-358`
- **§3.6** — insert — ambiguity — repeated `coupon_ids` attach/count once; empty array yields a legal draft with `coupon_count` 0 — `routes/invoices.py:170,233-239`
- **§3.7** — insert — ambiguity — all fixed quotes resolved before hop 1, so a missing quote leaves the period `OPEN` — `routes/periods.py:79-93`
- **§3.7** — insert — ambiguity — the period row is written once; `version` advances by exactly 1 per close — `routes/periods.py:91-142`
- **§3.7** — insert — ambiguity — the FFP true-up bumps the carrier's `version` (a second bump if hop 4 suspended it); carriers with no qualifying coupon are skipped — `routes/periods.py:138-140`, `calculations.py:300-316`
- **§3.7** — insert — ambiguity — at settle, only carriers whose counters were non-zero are written/version-bumped; period bumps by 1 — `routes/periods.py:177-184`
- **§3.8** — revise — ambiguity — an over-ceiling/negative `counter_amount_minor` is `ERR_INVALID_REQUEST` (400) tested *after* the step-11 state check — `routes/memos.py:195,204-208`
- **§3.8** — insert — ambiguity — hop 5 increments `open_reproration_count` on every cascade, even for an already-`REPRORATION_REQUIRED` ticket — `routes/memos.py:84-89`
- **§3.9** — insert — ambiguity — the `sample_coupon_ids` currency check and its ladder position — `routes/audits.py:46-49`
- **§3.9** — insert — ambiguity — repeated findings on one `coupon_id` are allowed and book again — `routes/audits.py:131-137`
- **§3.9** — insert — ambiguity — zero denominators yield a quotient of 0 rather than failing — `calculations.py:408-418`
- **§3.9** — insert — ambiguity — the FX quote is required in *both* close branches and resolved before the extrapolation — `routes/audits.py:157-161`

### Post-edit integrity check
- §4 endpoint data rows: **49** (51 table lines incl. header + separator; `/_clock/set_current_utc` present)
- §5 distinct `ERR_` codes: **51**
- Section headers: **27**, identical to `PRD.md` — no sections added
- File ends cleanly at §5, last line `| ERR_STALE_TICKET_VERSION | 412 |`

### Notes / judgement calls
- Six PRD passages describing *string formats* (`iata_code`, `ticket_number`, station codes) were genuine mismatches: the impl validates only non-emptiness, and ladder step 3 never listed string-format checks. The prose was revised to mark them as unenforced conventions rather than deleting them.
- The impl answers undeclared routes/methods with `ERR_NOT_FOUND` (404) and `ERR_METHOD_NOT_ALLOWED` (405), which are **not** in the §5 catalogue. Table rows were deliberately NOT added — that surface is outside the specified API and adding rows would break the 51-code invariant. This is the one known residual silence.

### Orchestrator-side independent verification
Re-measured `PRD_COMPLETED.md` directly: 447 lines / 98,094 chars (vs 447 / 92,300 for `PRD.md`); 49 endpoint rows in §4; 51 distinct `ERR_` codes in §5; file terminates on the `ERR_STALE_TICKET_VERSION` row — no truncation.

---

# Pipeline complete

All 9 steps done (Step 8 skipped by its stated condition). Final state: 102/102 tests passing in all 8 parallel rounds under `--isolation per-test-server`.
