# Worklog — task_2128_sma_model_portfolio

## Step 1: Create task directory — 2026-08-22T02:09:03.125Z

Created `./tasks/task_2128_sma_model_portfolio/` and `./tasks/task_2128_sma_model_portfolio/workspace/` (next index after task_2127).

## Step 3: Copy shared files — 2026-08-22T02:09:03.125Z

Copied `./INSTRUCTION.md` -> `./tasks/task_2128_sma_model_portfolio/workspace/INSTRUCTION.md` (run early; no dependency on Step 2).

## Step 2: Generate scaffold artifacts — 2026-08-22T03:06:00.000Z

Ran `prd-bench-scaffold-generator` against the task 2128 scenario (SMA sponsor
platform). Wrote three files into `./tasks/task_2128_sma_model_portfolio/`:

- `SCAFFOLD.yaml` — §1.0–§1.7. Expert+ profile: 12 entities, 61 endpoints,
  41 error codes, 10 calculations, 10 state machines (2 of them the two parallel
  dimensions of `Account`), 28 ordered validations, 2 OCC concurrency rules,
  5 roles. `api_prefix: /sma`; logical clock default `2026-08-01T00:00:00Z`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, 21 instances across all nine §0.5
  rules (3 rules carry a third instance).
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, 57 instances (48 with `test_recipe`,
  9 `excluded_because` stubs) over 9 claim-extraction sections.

Verification: `scaffold_lint.py` reports `VERDICT: clean lint` (936 calls
scanned); placeholder closure, grounds resolvability, instance-name uniqueness,
error-catalog triggerability and endpoint coverage all checked clean.

### Step 2 — subagent's verbatim returned summary — 2026-08-22T03:06:30.000Z

All three scaffold artifacts are generated and verified. No sibling task directory was read at any point — the design comes only from the scenario text plus the skill spec, its `references/claim-extraction-guide.md`, and `scaffold_lint.py`.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_2128_sma_model_portfolio/SCAFFOLD.yaml` (§1.0–§1.7, 2286 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2128_sma_model_portfolio/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2128_sma_model_portfolio/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single key `scaffold_corner_design`)

Also appended a Step 2 entry to the pre-existing `worklog.md` in that directory.

## Lint verdict (pasted verbatim)

```
Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     12
  §1.8 instances scanned:     21
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  936

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design summary

Profile: `workflow_orchestration` × `compliance_audit`, graph topology, **parallel** state-machine shape, `segregation_of_duties` roles, immediate consistency. Sized above the Expert band as requested: 12 entities, 61 endpoints, 41 errors, 10 calculations, 10 state machines, 28 ordered validations, 2 OCC rules, 5 roles. `api_prefix: /sma`; the only test-driving endpoint is `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default.

The nine §0.5 rules are carried by structurally distinct mechanics:
- **Dual variant** — `account_drift_bps` (SETTLED 1000 bps vs TRADE_DATE 52 bps on one frozen account) and `cross_account_dispersion` (EQUAL_WEIGHTED 113 vs ASSET_WEIGHTED 104 on one cohort) — different entity domains.
- **Combinatorial** — mode (b) fee billing, where per-tier rounding gives gross 289725 not 289726 and the manager residual gives 178674 not 178673; mode (c) `effective_sleeve_weights`, a three-pass capping fixed point where eff depends on residual depends on the pinned set depends on eff.
- **Non-linear machines** — ModelVersion cyclic (reject → DRAFT), Account parallel (`implementation_status` × `billing_status`), plus cyclic TradeOrder/Block (allocate → unwind) and branching HarvestProposal.
- **Cascades** — publish (depth 5: supersede → lapse → notify → stale) and invoice write-off (depth 4: crosses both Account dimensions into order cancellation).
- **Priority conflicts** — three distinct category pairs (state×safety, safety×fiscal, referential×temporal).
- **Boundaries** — drift `>=` at exactly 1000 vs 999; empty dispersion cohort; wash lookback at exactly 30 vs 31 days.
- **Cross-entity** — SponsorDistribution→ModelVersion, FeeInvoice→Account, Account→SponsorDistribution.
- **Interval overlap** — half-open adjacency-legal distribution windows on (Sponsor, Model) vs closed symmetric ±30-day wash windows on (Account, Security).
- **Compensating invariants** — shares (`filled == allocated + unallocated` across allocate/unwind) and cents (`gross == sponsor + manager + platform`, `fees_billed_ytd` restored by void).

Every formula-derived assertion is a literal I computed by running the pinned formulas in Python (fee tiers 55479/147945/86301, splits 96565/14486/178674, pro-rata allocation 580/420 from a 1000-share fill on 980+712 requests, HIFO split basis 400000/400000, dispersion 113/124 vs 104/39, generation share counts).

Two notes on choices I made while drafting, in case they matter downstream: I swapped validation priorities so `ERR_INSUFFICIENT_SHARES` precedes `ERR_HARVEST_BUDGET_EXCEEDED` (the budget check needs a completed HIFO walk) and so `ERR_BELOW_SPONSOR_MINIMUM` precedes `ERR_NO_TRADES_GENERATED` (the minimum should gate before generation runs). Both are reflected consistently in §1.4 and in the design files' grounds.

## Step 4: Generate PRD — 2026-08-22T03:20:00.000Z

The PRD is complete and verified. Written to `/home/ubuntu/github/CodingPRD/tasks/task_2128_sma_model_portfolio/workspace/PRD.md` (435 lines, ~13,500 words).

**Document skeleton** (domain-derived, not copied from the example): §1 Introduction (3 paragraphs); §2 with 11 subsections — RBAC, the fixed §2.2 envelope, Pagination, Common Resource Properties, The Logical Clock, The Validation Ladder, OCC on Parent Rows, Integer Money & Rounding Discipline, The Two State Dimensions & Cascade Discipline, Interval Semantics, Resource Addressing; §3 with 9 workflow subsections organized as a delivery chain (instrument master → version authoring → publication fan-out → account opening → weights & generation → drift/performance/dispersion → blocks & tax lots → harvesting → billing); §4 endpoint table (4 columns); §5 error table (2 columns). PRD ends at §5 with no audit footer.

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 111 required, 111 present, 0 missing
- endpoints[].request_body/input: 60 required, 60 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
  (all 12 appear verbatim inside backticked path tokens in §4)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 28 checked, 28 expressed in prose (§2.6 renders the full
  ascending ladder, each rung naming its error_id, HTTP status and exact applies_to scope
  with the endpoint count spelled out), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint +
  expected_model_version_version / expected_account_version + ERR_STALE_VERSION + 412
  all named; §2.7 also states that no other endpoint takes a version field), 0 missing
- state_machines[].transitions: 52 checked across 10 machines, 52 fully expressed
  (from/to pair, preconditions paired with error_ids, all side effects), 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise prose with no operator
  syntax; all 12 named constants embedded in business context, 0 missing
- validations[] conditions: 28 checked, 28 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 61 endpoints checked, all side effects expressed
  in the owning workflow narrative, 0 missing
- entities[].fields[] structured content: 111 checked (types, defaults, initial values,
  ranges, uniqueness constraints), 111 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (model-version approve/reject,
  harvest approve/reject/supersede, suspend/reinstate, in-place close vs split,
  void from DRAFT vs ISSUED, distribution PENDING/ACTIVE, drift SETTLED/TRADE_DATE,
  dispersion EQUAL_WEIGHTED/ASSET_WEIGHTED, tax-lot CLOSED→OPEN vs CLOSED→REVERSED),
  9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 746
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Completeness verification counts (per your instruction)

| Scaffold section | Scaffold count | Present in PRD |
| --- | --- | --- |
| §1.1 entities | 12 | 12 (all 111 fields covered) |
| §1.2 state machines | 10 (52 transitions) | 10 / 52 |
| §1.2.1 concurrency rules | 2 | 2 |
| §1.3 calculations | 10 | 10 |
| §1.4 validations | 28 | 28 |
| §1.5 endpoints | 61 | 61 (§4 table) |
| §1.6 errors | 41 | 41 in §5, and all 41 also triggered in §2/§3 prose |
| §1.7 roles | 5 | 5 (each `identity:` translated into §2.1) |

Additional checks that passed: §2.2 matches the canonical file byte-for-byte (verified by exact substring match, including `req_RANDOMALPHANUM123456` and `"data": { }`); all 26 state enumeration values and all 17 enum-type field values appear as exact backticked strings; no fuzzy/approximating words remain.

The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-08-22T03:55:00.000Z

Generation is complete and audited.

## What was produced

**`test_helpers/`** (Stage 1, 9 files, ~1,900 lines) — all under `/home/ubuntu/github/CodingPRD/tasks/task_2128_sma_model_portfolio/test_helpers/`:
- `types.py` — 17 status/role enums + TypedDicts for all 12 entities (all carry `common_fields: true`, so all four housekeeping fields).
- `api_client.py` — one method per endpoint (57 endpoints incl. `/_clock/set_current_utc`) plus `raw_get`/`raw_post`.
- `api_errors.py` — all 41 error ids + HTTP map, registered with the framework.
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (5 tiers: registry → version lifecycle → accounts/distributions → orders/blocks/harvest → invoices/write-off, incl. `setup_standard_account`, `setup_drifted_account_with_orders`, `setup_account_pending_implementation`, `setup_filled_block`, `setup_written_off_account`), `__init__.py` barrel.
- `SponsorOperator` identity threading is enforced: `make_sponsor_operator_headers(sponsor["id"])` everywhere a sponsor-scoped write happens; the shared fallback constant is used only in one open-read 404 case.

**`test_suite/`** (Stage 2, `conftest.py` + 16 test files, ~5,100 lines) — 114 test functions / 129 collected items.

## Design-index coverage — complete, no gaps

| Queue | Instances | Tests | Minimum per instance |
|---|---|---|---|
| A — Difficulty (§1.8) | 21 / 21 | 53 | 2 (target >=2) |
| B — Corner non-stub (§1.9) | 48 / 48 | 61 | 1 (target >=1) |

- **0 instances skipped.** Every instance passed the PRD-first two-condition filter.
- The 9 `excluded_because:` stubs in `errors` were not translated; all 9 `difficulty_instance` cross-references were verified to resolve to real names in the difficulty index.
- Mechanical audit: 0 coverage shortfalls, 0 untagged/dual-tagged/unknown tags, 0 citation failures. Every docstring's **last** line is exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>`, and every PRD quote above it is a literal substring of `workspace/PRD.md`.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no `approx` on money (all integer cents/bps); no scaffold vocabulary in generated code; all files compile and `pytest --collect-only` succeeds with no import errors; every `api.<method>` resolves against `ApiClient`.

## Two things worth flagging to whoever implements this

1. **Fee-tier slice wording (PRD §3.9) is the weakest link.** Two agents independently hit it: the pre-computed `gross_fee_cents == 289725` only reconciles if the tier-2 "capped at one million dollars" is read as a **cumulative** ceiling (slices 25M / 75M / 50M on a 150M ADV). The literal "cap the slice at 100M" reading gives 295890 and breaks slice conservation; the phrase "cut into three tier slices" plus "the third slice is whatever exceeds the second ceiling" is what pins the cumulative reading. Tests assert the design-index value verbatim, so an implementer taking the other reading will fail `test_09` and `test_16`.
2. **Timestamp assertions are date/second-prefix based**, not exact `.000Z` string equality, wherever the rule under test is an interval boundary rather than the rendering — a deliberate two-reader relaxation. The `notified_at` / `implementation_deadline` cascade assertions do use the full `2026-08-01T00:00:00.000Z` form, copied from the index.

## Step 6: Generate implementation — 2026-08-22T04:05:00.000Z

All 61 endpoints from the scaffold are registered and every smoke path passes.

## What was built

`workspace/implementation/` — Python 3 + Flask, in-memory store, no seeding at startup (verified: `/sma/accounts` and `/sma/model-versions` both return empty on a fresh boot).

| File | Contents |
|---|---|
| `start.sh` | Guarded `pip install` (skipped when Flask imports), `exec python3 app.py`; boots and answers HTTP in ~2s |
| `app.py` | Blueprint registration, logical-clock endpoint, error handlers, auth `before_request`, per-request serialization lock |
| `core.py` | Envelope (`meta`/`response_type`/`data`), error catalog (41 IDs → HTTP), ISO-8601 UTC ms timestamps, ID/version/`touch` bookkeeping, auth + RBAC + sponsor scope, field validators, `limit`/`offset` pagination, exact-rational `round_half_up` |
| `calc.py` | All 10 calculations verbatim from the scaffold constants |
| `entities.py` | Enums, account serializer with derived `market_value_cents`, ladder guards, block recompute |
| `routes/` | `catalog`, `models` (+CASCADE-A), `accounts`, `trading` (+CASCADE-B), `harvest`, `billing` (+CASCADE-C) |

## Key fidelity decisions

- **Ladder order.** The 28 rungs of PRD §2.6 drive the order of checks inside every handler, including the cases that invert the "obvious" order: sponsor scope on `POST /sma/accounts` runs against the body's `sponsor_id` *before* body-reference existence; segregation of duties runs *before* the from-state check (so a submitter re-approving an already-`APPROVED` version gets 403, not 409); `ERR_MODEL_NOT_PUBLISHED` precedes `ERR_DUPLICATE_KEY` on account creation; rung 9 precedes rung 10; rung 25 precedes rung 26 (so the `tax_overlay_enabled` gate, which lives in rung 26, fires *after* `ERR_INSUFFICIENT_SHARES`). Where a rung structurally cannot be evaluated before the row exists (path-scoped sponsor scope), existence wins — unavoidable.
- **Versioning.** One `version` bump + `updated_at` refresh per row per request, including rows touched only as a cascade consequence (blocks whose `requested_shares`/`order_count` recompute, sponsors on account creation, accounts on restriction create/lift).
- **`created_at`/`updated_at` use a monotonic wall clock**, not the logical clock — the logical clock is used for every business instant the PRD enumerates (`open_date`, `close_date`, wash windows, `notified_at`, `implementation_deadline`, `activated_at`, `published_at`, `issued_at`, …). This keeps list ordering and the HIFO/waterfall `created_at` tie-breakers equal to insertion order when a test rewinds the clock.

## Two judgement calls worth flagging

1. **SELL unwind reverses the proceeds.** PRD §3.7's unwind paragraph explicitly mentions crediting back the cost basis of *opened* lots but never mentions debiting back SELL proceeds. I implemented the full reversal, on the strength of §1's "no cent is ever created or destroyed" and §2.9's "restore every counter they touch to its exact prior integer value". A literal-minded test could expect proceeds to remain.
2. **Negative `investable`.** `investable = market_value − cash_reserve` is implemented literally, with floor rounding, so an unfunded account (mv 0 → investable −10000) generates 1-share SELL orders rather than `ERR_NO_TRADES_GENERATED`. The PRD states no clamp; the clean `ERR_NO_TRADES_GENERATED` path is reached by an in-balance account or one whose deltas fall under the 5000-cent materiality floor.

Smaller unspecified choices: a 0-share pro-rata allocation transitions the order to `CANCELLED` but keeps `block_id` (the "cleared on cancel" rule reads as the operator cancel path); an in-place-closed lot restored by an unwind has `closing_trade_order_id` cleared back to null; `billing_days` is floor of elapsed duration; lots already `REVERSED` by an earlier unwind of the same block are excluded from the rung-22 safety scan so a re-allocated block can be unwound twice.

## Verification

Three smoke suites (~140 assertions, in the scratchpad) all pass against `start.sh`, covering: auth/RBAC/scope/SoD; the model-version revision loop; CASCADE-A hops 1–5 (supersede → lapse → notify with a correct `implementation_deadline` → stale orders, allocated orders untouched); implementation with lag/late flags and `ERR_DISTRIBUTION_NOT_ACTIVE`; effective weights under `MAX_POSITION` (6000/4000 → 3000/7000 after the second pass) and `DO_NOT_BUY`; the two-floor generator; both drift bases from identical data (7000 SETTLED vs 70 TRADE_DATE); the pro-rata waterfall with remainder (667/333 of a 1000-share fill); HIFO split with carved basis, wash-window stamping, and exact unwind restoration of parent lot, cash and `realized_loss_ytd_cents`; both wash-sale clauses; tiered fee split with per-tier rounding and the manager residual; both dispersion bases (equal 300/200 vs asset-weighted 200/150).

## Step 7: Run tests and iterate — 2026-08-22T04:12:00.000Z

The task is already at a clean state. All 8 parallel rounds passed on the first iteration, so no diagnostic protocol steps were triggered.

## Summary

**Iterations run:** 1 (a single 8-round parallel stability sweep).

**Result:** All 8 concurrent rounds passed `129 / 129` — 0 failed, 0 errors, 0 skipped, ~162 s per round. The union of failing tests across all rounds is empty, so there is no flakiness signal to chase.

| round | passed/total | failed | errors | skipped |
|---|---|---|---|---|
| 1–8 | 129 / 129 | 0 | 0 | 0 |

Collection was verified complete: `collected 129 items` spanning all 16 test files (`test_01` 23, `test_02` 9, `test_03` 5, `test_04` 10, `test_05` 9, `test_06` 5, `test_07` 15, `test_08` 6, `test_09` 5, `test_10` 6, `test_11` 6, `test_12` 7, `test_13` 8, `test_14` 7, `test_15` 4, `test_16` 4) — no silently-uncollected file was masking failures.

**Tests deleted:** none. No test failed, so STEP 1a/1b were never reached.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `workspace/implementation/`:** none.

**Cardinal-rule audit performed while the sweep ran** (to confirm the passing state is legitimately passing rather than passing-but-invalid):
- No `pytest.mark.skip` / `xfail` anywhere in `test_suite/` or `test_helpers/` — the only `skip` matches are substrings inside test function names describing PRD cascade-skip semantics (e.g. `test_publication_fan_out_skips_an_account_that_is_already_suspended`).
- Storage is in-memory only: `workspace/implementation/core.py:184` instantiates a plain `Store()` of Python dicts; no sqlite, file `open(...)`, `json.dump`, `pickle`, `shelve`, or `/tmp` path exists in the implementation.
- No startup seeding: `core.py:165` and `app.py:3` both document the store starts empty on every boot, and no bootstrap/seed/preload function exists — which matters here because `--isolation per-test-server` reboots via `start.sh` before every test.
- Spot-checked the high-risk calculation paths against PRD prose and found them faithful: `round_half_up` (`core.py:477`) rounds away from zero for negatives as §2.8 requires; `compute_fee_invoice` (`calc.py`) rounds each of the three tiers independently before summing and takes the manager share as the exact residual; `effective_sleeve_weights` floors the pro-rata split and distributes the remainder one bp at a time in ticker-ascending order over at most 3 passes; `generate_trade_orders` applies the weight before the share conversion with two separate floors.

The eight `results.${i}.json` files were removed by the fix subagent after reading them; the orchestrator re-ran the sweep to restore them as the documented evidence artifact.

## Step 8: Finalize PRD — SKIPPED — 2026-08-22T04:12:30.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at every site Step 7 exercised, so no `PRD_FINALIZED.md` is produced.

## Step 9: Complete PRD — 2026-08-22T04:25:00.000Z

Done. `PRD_COMPLETED.md` is written.

## Summary

**Source:** `workspace/PRD.md` (no `PRD_FINALIZED.md`; Step 8 skipped)
**Output:** `workspace/PRD_COMPLETED.md`

- Lines: 435 → 435 (all edits in-paragraph; no new sections, no new paragraphs)
- Chars: 95,768 → 99,539 (+3,771); 24 lines changed
- **Ambiguity-pins: 24 · Mismatch-revisions: 3**

### Changes

- §2.3 Pagination — insert — ambiguity — residual `created_at` ties outside trade orders/tax lots break by store insertion order — `core.py:597`
- §2.4 Audit trail — insert — ambiguity — `created_at`/`updated_at` come from the real wall clock, not the logical clock — `core.py:268-280`
- §2.4 Audit trail — insert — ambiguity — `version` advances at most once per row per request, even across multi-hop cascades — `core.py:367-381`
- §2.6 rung 25 — revise — **mismatch** — sufficient-shares guards three operations, adding `SELL`-block allocation with per-account summing — `routes/trading.py:243-251`
- §2.6 rung 27 — revise — **mismatch** — BUY cash coverage is summed per account across the block's members — `routes/trading.py:233-242`
- §3.1 Instrument master — insert — ambiguity — `restricted_globally` bites only at block assembly; the generator/effective weights ignore it — `calc.py:71-125`, `routes/trading.py:69-77`
- §3.1 Re-marking — insert — ambiguity — re-mark price must also be at least 1 — `routes/catalog.py:51`
- §3.2 Review — insert — ambiguity — `rejection_note` is a required non-empty string — `routes/models.py:292`
- §3.4 Funding — insert — ambiguity — `amount_cents` >= 1; response is the updated account — `routes/accounts.py:128,133`
- §3.4 Funding — insert — ambiguity — `shares` >= 1, `cost_basis_cents` >= 0; response is the created tax lot — `routes/accounts.py:148-149,176`
- §3.5 Stage one — insert — ambiguity — smallest `max_position_bps` binds when several MAX_POSITION restrictions coexist — `calc.py:80-83`
- §3.5 Rebalancing — insert — ambiguity — the account's `version` advances although no field of it changes — `routes/accounts.py:312`
- §3.6 Drift — insert — ambiguity — evaluation is reachable from any non-suspended state (incl. `PENDING_IMPLEMENTATION`) with no state change; zero valuation base yields actual weight 0 — `routes/accounts.py:288-291`, `calc.py:259-260`
- §3.6 Performance — insert — ambiguity — `gross_return_bps` unbounded/negative allowed, `ending_value_cents` >= 0, account returned — `routes/accounts.py:329-336`
- §3.6 Dispersion — insert — ambiguity — invalid `basis` → `ERR_INVALID_REQUEST` — `routes/models.py:402-404`
- §3.6 Dispersion — insert — ambiguity — null ending value weighs 0; zero weight-sum falls back to the equal-weighted formulas — `calc.py:479-487`
- §3.7 Block assembly — insert — ambiguity — repeated ids in `trade_order_ids` collapse to one member — `routes/trading.py:110-116`
- §3.7 Execution — revise — **mismatch** — no membership check; an emptied block has `requested_shares` 0 and fails rung 21 with `ERR_FILL_EXCEEDS_REQUEST`; `avg_fill_price_cents` >= 1 — `routes/trading.py:193-199`
- §3.7 Allocation hop 1 — insert — ambiguity — zero-allocation member keeps its `block_id` and the block does not recompute `requested_shares`/`order_count`; SELL share check; empty participating set → `ERR_INVALID_STATE` — `routes/trading.py:229-260`, `calc.py:274-275`
- §3.7 Disposal walk — insert — ambiguity — split slice inherits parent `origin`/`open_date`, null `opening_trade_order_id`, `sequence_number` from `next_order_sequence` — `calc.py:347-365`
- §3.7 Unwinding — insert — ambiguity — only members still `ALLOCATED` return to `BLOCKED`; zero-allocation cancellations stay `CANCELLED` — `routes/trading.py:371-381`
- §3.8 Proposal — insert — ambiguity — `replacement_security_id` must resolve → `ERR_SECURITY_NOT_FOUND` — `routes/harvest.py:41-43`
- §3.8 Execution — insert — ambiguity — execution re-checks `tax_overlay_enabled`, not just the budget — `routes/harvest.py:171`, `harvest.py:20-22`
- §3.8 Execution — insert — ambiguity — `realized_loss_cents` uses the negative-slices-only absolute total (same shape as `proposed_loss_cents`), not the signed net — `routes/harvest.py:168`, `calc.py:319-322`
- §3.8 Rejection — insert — ambiguity — `rejection_note` is a required non-empty string — `routes/harvest.py:144`
- §3.9 Tier slices — revise — **mismatch** — 100000000 cents is an absolute ceiling on ADV (slice 2 <= 75000000; slice 3 = excess over 100000000), so the three slices conserve ADV — `calc.py:421-423`
- §3.9 Voiding — insert — ambiguity — `void_reason` is a required non-empty string — `routes/billing.py:318`

Not touched (already uniquely pinned or purely infrastructural): ladder ordering per endpoint, cascade A/B/C hop conditions, HIFO ordering, half-open interval helpers, fee split residual, error catalogue, endpoint/role table.

## Orchestrator post-checks — 2026-08-22T04:26:00.000Z

- Re-ran the 8-round parallel sweep independently to restore the documented `results.{1..8}.json` evidence: all 8 rounds `129 / 129`, 0 failed.
- Design-index leak check on the Step 6 implementation-generator transcript: 0 occurrences of `SCAFFOLD_DIFFICULTY_DESIGN` / `SCAFFOLD_CORNER_DESIGN`, and no read of `test_suite/` or `test_helpers/`. The green first sweep is therefore not explained by an index leak — it reflects a PRD that already pinned the exercised behaviors (Step 9 still found 27 unexercised residual sites).
