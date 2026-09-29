# Worklog — task_2874_landscape_supply_yard_bulk_material_delivery

## Step 1: Create task directory — 2026-09-05T10:02:55.653Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2874_landscape_supply_yard_bulk_material_delivery` and its `workspace/` subdirectory. Index 2874 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-05T11:49:00.000Z

Subagent summary (verbatim):

Done. All three scaffold artifacts for task_2874 are complete and lint-clean.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2874_landscape_supply_yard_bulk_material_delivery/`)

| file | lines | top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 2738 | §1.0–§1.7 only (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1667 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3397 | `scaffold_corner_design` |

## Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2874_landscape_supply_yard_bulk_material_delivery/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2874_landscape_supply_yard_bulk_material_delivery/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2874_landscape_supply_yard_bulk_material_delivery/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  833

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Counts

- **§1.0–§1.7**: 13 entities, 11 state machines (MaterialOrder split into `fulfillment_status` + `settlement_status` dimensions), 2 `concurrency_rules`, 8 calculations (all with `variants`), 39 validation priorities, 66 endpoints, 75 errors, 6 roles, `api_prefix: ""`, profile = expert_plus / pricing_engine + quota_allocation / flat / parallel / segregation_of_duties / immediate, layers = dual_variant_calculation, rate_threshold_triggers, cascading_side_effects, optimistic_concurrency.
- **§1.8**: 9 Difficulty Rules / **22 instances** (2–3 each).
- **§1.9**: 9 taxonomy sections / **77 instances** — 56 with full `test_recipe`, 21 `excluded_because:` stubs. Per section: entities 11, state_machines 13, calculations 15, validations 19, endpoints 5, errors 2, rbac 6, cross_cutting_complexity_layers 5, consistency_model 1.
- All 75 catalogued error ids are triggered by at least one §1.8/§1.9 instance; all 176 distinct `grounds` references resolve to declared §1.1–§1.7 elements; instance names are unique across the union of both design files.

## Fixes made while closing out

1. Lint's only violation was in §1.8: `role_authorization_outranks_path_existence_on_prebuy_activate` intentionally calls `POST /prebuy-contracts/{id}/activate` as `Contractor`, but its name didn't match the linter's negative-trigger pattern. Renamed to `role_authorization_outranks_path_existence_and_returns_403_on_prebuy_activate` (no §1.9 stub cited the old name).
2. `JobPurchaseOrder` had statuses `{OPEN, EXHAUSTED, CLOSED}` and was referenced by `state_machines.JobPurchaseOrder(.EXHAUSTED_to_OPEN)` grounds in both design files but had **no §1.2 machine**. Added it to `SCAFFOLD.yaml` (initial OPEN, terminal `[CLOSED]`, transitions OPEN→EXHAUSTED at confirm, EXHAUSTED→OPEN on cancel/reprice/claim-settle, OPEN→CLOSED via the close action guarded by `ERR_PO_NOT_OPEN`).
3. Normalised grounds syntax so every reference resolves: `constants.X` → `calculations.<calc>.constants.X`, `endpoints.<M> <path>` → `endpoints[<M> <path>]`, `rbac.<Role>` → `roles.<Role>`, bare `pagination` → `response_envelope.pagination_fields/.pagination_defaults`.
4. Removed the two "simultaneously" occurrences (Quality-Checklist banned concurrency vocabulary).

## One flag for the orchestrator

`SCAFFOLD.yaml`'s `scenario:` begins with the literal line `Generate task harder than expert level!` because you required the scenario verbatim. That line propagates into PRD.md downstream, so strip that single line after this step if your pipeline's later stages consume the scenario key. I did not touch `worklog.md` (no step entry written).

### Orchestrator action taken after Step 2

The subagent's flag was acted on: the literal line `Generate task harder than expert level!` (plus its trailing blank line) was deleted from `SCAFFOLD.yaml`'s `scenario:` block by the orchestrator, so the difficulty directive cannot reach PRD.md. YAML re-parsed clean afterwards; `scenario` now begins at "2874. Landscape Supply Yard...". No other scaffold content was modified. `grep` confirms the phrase appears in none of the three scaffold files.

## Step 3: Copy Shared Files — 2026-09-05T11:50:05.616Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T12:12:00.000Z

Subagent summary (verbatim):

PRD generation complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2874_landscape_supply_yard_bulk_material_delivery/workspace/PRD.md` — **477 lines**, built as 1 `Write` + 12 appends (no chunk near the 64k cap). Document ends at a real section boundary: the last line of the §5 error table (`| \`ERR_UNDERPAYMENT\` | 402 |`), no audit footer, no meta-commentary.

**Sections covered**
- §1 Introduction (3 paragraphs: volume drift, price drift, credit/liability leakage)
- §2 Global Specifications — 10 subsections: 2.1 RBAC & trade accounts, 2.2 API Response Structure (byte-identical to the skill's fixed text), 2.3 Pagination, 2.4 identity/audit/versions, 2.5 yard logical clock, 2.6 volume/weight/money conventions, 2.7 stale-version guards, 2.8 rejection precedence (all 39 rungs as an ordered ladder), 2.9 cascade discipline, 2.10 the two independent order state dimensions
- §3 Business Logic & Workflows — 9 subsections: catalogue & price book; stockpile intake/moisture/net sellable volume; accounts, POs & pre-buys; order build → quote freeze → confirm; truck sizing, driveway access & delivery run; will-call queue & equipment safety; claims; container deposits & late decay; invoicing, payment & credit release
- §4 Endpoint Definitions — 4-column table, 66 rows
- §5 Error Code Catalogue — 2-column table, 75 rows

**Coverage confirmation (all mechanically checked against SCAFFOLD.yaml)**
- Endpoints: 66/66 present, and every row's `Authorized Role(s)` set matches the scaffold exactly — 0 missing roles, 0 extra roles
- Errors: 75/75 in the §5 table with 0 HTTP-status mismatches; additionally all 75 error IDs appear in backticks in the §1–§4 prose (0 table-only errors)
- Calculations: 8/8 expressed fully in prose with every constant embedded in business context (`inventory_net_sellable_volume`, `order_line_pricing`, `order_charge_assembly`, `truck_load_fit`, `account_credit_position`, `claim_settlement_waterfall`, `container_deposit_refund`, `will_call_queue_ranking`)
- Validations: 39/39 as an explicit numbered precedence ladder in §2.8, each with its error ID and endpoint scope
- Concurrency: 2/2 OCC rules in §2.7 with write endpoint, OCC field, error ID and HTTP 412

**Hard Contracts**
- Contract 1 (Field-Name Coverage) — **PASS**: 118/118 entity fields, all endpoint input field names, all 13 path params (via the §4 path column), 0 missing
- Contract 2 (Rule Coverage) — **PASS**: 39 validations, 2 OCC rules, 8 calculations, all cascade hop chains (confirm 3, cancel-compensate 3, deliver 5, claim-settle 4, payment 3, container receive/close/forfeit), and all 51/51 state transitions now carry explicit `FROM → TO` phrasing; sibling branches given equal density (DELIVERED vs REFUSED, APPROVE vs DENY, INVOICED vs SETTLED → CREDIT_MEMO_ISSUED, OUTSTANDING vs PARTIALLY_RETURNED → CLOSED/FORFEITED, DRAFT/CONFIRMED/ALLOCATED → CANCELLED)
- Contract 3 (§3 Path Purity) — **PASS**: 0 backtick tokens in §3 contain `/`, 0 bare HTTP-method tokens, 0 method+path combinations

**Two fixes applied in this final pass:** added to §3.1 that a successful price-row filing advances the parent `Material.version` by one (the mechanism that makes a replayed `expected_material_version` fail), and converted the remaining 17 prose-only state changes into explicit arrow pairs.

**Scaffold contradiction resolved by decision:** the `ClaimCase` `UNDER_REVIEW → DENIED` transition says `payable_cents` stays null, while `POST /claim-cases/{claimCaseId}/decide`'s side_effects say denial sets `payable_cents = 0`. I wrote the state-machine reading (denial leaves `payable_cents` null and moves no ledger field anywhere) so the implementer and test generator, both of which read only the PRD, stay consistent. Flagging in case you want the endpoint reading instead.

Constraints honored: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory was read; no `pkill` was run.

### Orchestrator verification after Step 4

Truncation guard applied: `PRD.md` is 477 lines / 113044 bytes and its final line is the last row of the §5 error catalogue table (`| \`ERR_UNDERPAYMENT\` | 402 |`) — a real section boundary, not a mid-sentence cut. All five top-level sections (§1–§5) are present in order. No regeneration needed. Also grepped the PRD for the Step 2 difficulty directive: the phrase "harder than expert level" does not appear anywhere in `PRD.md`, so the directive did not leak through the scaffold.

Decision recorded on the subagent's flagged scaffold contradiction (ClaimCase DENIED / `payable_cents`): the orchestrator accepts the doc generator's resolution. The state-machine reading (denial leaves `payable_cents` null) is what `PRD.md` states, and PRD.md is the single contract both the test generator and the implementation generator read, so both will agree with each other. Since neither downstream generator sees SCAFFOLD.yaml, the endpoint-side wording in the scaffold can no longer create a divergence. No edit to PRD.md.

## Step 5: Generate Unit Tests — 2026-09-05T14:07:00.000Z

Subagent summary (verbatim):

Test generation is complete. Everything landed at the task root; nothing was written under `workspace/`.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2874_landscape_supply_yard_bulk_material_delivery/`)

**`test_helpers/`** (1,391 lines total, written earlier in the run): `__init__.py` 31, `api_client.py` 364, `api_errors.py` 171, `assertions.py` 348, `constants.py` 69, `factories.py` 360, `fixtures.py` 710, `test_users.py` 90, `types.py` 248.

**`test_suite/`** (`conftest.py` 44 + 17 test modules, 100 tests):

| file | lines | tests | queue |
|---|---|---|---|
| test_01_dual_variant_calculations.py | 242 | 4 | A |
| test_02_combinatorial_formulas.py | 239 | 4 | A |
| test_03_parallel_and_cyclic_lifecycles.py | 419 | 6 | A |
| test_04_transitive_cascades.py | 317 | 4 | A |
| test_05_rejection_precedence_pairs.py | 318 | 6 | A |
| test_06_boundary_precision.py | 388 | 6 | A |
| test_07_cross_entity_state_gates.py | 409 | 6 | A |
| test_08_resource_temporal_overlap.py | 264 | 4 | A |
| test_09_compensating_invariant.py | 340 | 4 | A |
| test_10_entities.py | 568 | 11 | B |
| test_11_state_machines.py | 497 | 7 | B |
| test_12_calculations.py | 767 | 8 | B |
| test_13_validations.py | 1541 | 14 | B |
| test_14_endpoints.py | 611 | 5 | B |
| test_15_errors.py | 260 | 2 | B |
| test_16_rbac.py | 642 | 6 | B |
| test_17_cross_cutting_and_consistency.py | 422 | 3 | B |

## Coverage

- **100 tests**, `pytest --collect-only` = 100 collected, every file `ast.parse` clean, ASCII-only, zero `skip`/`xfail`/`mock`/"scaffold" occurrences.
- **Queue A (Difficulty): 44 tests** covering all 22 non-stub §1.8 instances, 2 tests each.
- **Queue B (Corner): 56 tests**, exactly 1 per non-stub §1.9 instance — entities 11, state_machines 7, calculations 8, validations 14, endpoints 5, errors 2, rbac 6, cross_cutting_complexity_layers 2, consistency_model 1.
- A yaml-vs-suite reconciliation script confirmed: **78 non-stub instances expected, 78 distinct `Design:` tags present, 0 missing, 0 dangling, 0 of the 21 `excluded_because:` stubs translated**, and every test carries exactly one `Design:` line as the last docstring line.
- **0 instances skipped by the PRD-first filter** — every non-stub instance had verbatim PRD coverage that uniquely derives its asserted outcome.

## Work completed this session

- `test_16_rbac.py`: added the last three `rbac` instances — cross-account read refusal (`ERR_ACCOUNT_SCOPE_VIOLATION` at rung 3, with the owner and a staff identity reading the same row successfully), segregation of duties (the planner in `dispatched_by_user_id` refused, `adjuster-clean` approving with the deductible waived because `driveway_protection_used` was false), and the six-role shared read returning byte-identical projections.
- `test_17_cross_cutting_and_consistency.py` (new): the two OCC guards (`ERR_STALE_MATERIAL_VERSION` on `POST /price-schedules`, `ERR_STALE_ACCOUNT_VERSION` on credit adjustments — each refused on the replayed version, leaving no row/limit change, then succeeding on the re-read version) plus the immediate-consistency delivery cascade (deliver response body already `DELIVERED`; first reads of order/line/lot/truck/account already show `FULFILLED`, `final_total_cents` 33850, delivered 6.00, withdrawn 6.00 with reserved back to 0.00, truck `AVAILABLE`, credit 33850/4966150).

## One cross-file defect found and fixed

A verbatim-citation audit over all 17 files found **16 citations that would fail a literal grep of PRD.md**: the PRD writes state arrows inside a single backtick pair (`` `ACTIVE -> CREDIT_HOLD` ``) while six earlier files had split them (`` `ACTIVE` -> `CREDIT_HOLD` ``). Normalized all 21 occurrences in `test_03`, `test_04`, `test_06`, `test_07`, `test_09`, `test_11` to the PRD's joined form. All **245 PRD quotes across the suite now match the PRD verbatim** (after only the sanctioned em-dash/arrow/whitespace-collapse normalization); previously 16 did not.

## Step 6: Generate Implementation — 2026-09-05T12:41:00.000Z

(Launched concurrently with Step 5 in a single orchestrator message, so the implementation generator's process could not read `test_suite/` — the directory did not exist when it started.)

Subagent summary (verbatim):

Implementation complete and smoke-tested.

## Modules (all in `/home/ubuntu/github/CodingPRD/tasks/task_2874_landscape_supply_yard_bulk_material_delivery/workspace/implementation/`)

| File | Lines | Contents |
|---|---|---|
| `core.py` | 656 | Error catalogue + `ApiError`/`fail`, Decimal helpers (`r2`, `floor2`, `cents`, ROUND_HALF_UP), ISO-8601 instants (always exactly 3 fractional digits, `Z`), logical clock, in-memory `Store` (13 dict collections, empty on boot), envelope builders (`meta.api_request_id` = `req_` + 20 uppercase alnum), auth/role/scope, request validators, pagination + filter plumbing |
| `calc.py` | 781 | All yard constants, pricing/charge assembly (quote + final basis), lot net-sellable & reservation math, credit/PO/pre-buy roll-ups, load fit (payload, driveway caps), will-call queue ordering, claim waterfall, container-deposit refund schedule, credit-posture evaluation, multi-hop cascade helpers |
| `serial.py` | 140 | One serializer per entity; explicit key lists (internal `_seq`/`_dispatched_at` never leak); computed read-only fields (`effective_density_lb_per_cubic_yard`, `available_net_cubic_yards`, `priority_class`, `queue_position`) |
| `routes_catalog.py` | 299 | Materials, price schedules (OCC), inventory lots, moisture readings, `POST /_clock/set_current_utc` |
| `routes_accounts.py` | 252 | Contractor accounts (+ credit adjustments with OCC), job purchase orders, pre-buy contracts |
| `routes_orders.py` | 443 | Orders, order lines, confirm (39-rung ladder segment with pricing rollback on credit/PO refusal), cancel, invoice, settle |
| `routes_delivery.py` | 412 | Trucks, loads: plan (weight -> access -> capacity -> 45-min window conflict -> mode -> window -> balance), dispatch, deliver (5-hop cascade), refuse, replan, cancel |
| `routes_willcall.py` | 228 | Tickets, `stage-next` (bay capacity -> queue-empty -> window), safety-ack, load, release, cancel |
| `routes_claims.py` | 342 | Claim lifecycle (segregation-of-duties checked at rung 4, ahead of body shape and path existence), decide/settle with credit memo + deposit offset, container returns receive/forfeit |
| `app.py` | 66 | Blueprint registration, `ApiError`/`HTTPException`/catch-all handlers returning the PRD error envelope, `0.0.0.0:$PORT` |
| `start.sh` | 17 | Reads `$PORT` (default 8000), guarded `pip install flask`, `exec python3 app.py` in the foreground |

`requirements.txt` pins `flask`. Storage is process-memory dicts only; nothing is seeded, written to disk, or cached.

## Endpoints: 66

Verified by enumerating `app.url_map` against the PRD §4 table one-for-one: materials 4, price-schedules 3, inventory-lots 4, contractor-accounts 4, job-purchase-orders 4, prebuy-contracts 4, material-orders 7, order-lines 3, delivery-trucks 4, delivery-loads 8, will-call-tickets 8, claim-cases 8, container-returns 4, clock 1.

## Smoke test

Booted on port 41874 via `start.sh`, ran a 54-assertion end-to-end script (`/tmp/task_2874_impl/smoke.py`) covering the full happy path plus refusals, then killed only my captured PID (port confirmed free afterwards). 52 passed. The 2 reported failures were errors in my own expected values, not the implementation: I predicted a 3.0% volume discount on an $880 bulk subtotal, but PRD §3.4 step three puts the 3.0% tier at $1,000 and up, so 0.0% / `quoted_total_cents = 165650` is the PRD-correct output the server produced.

Verified end-to-end: envelope shape (`meta`/`response_type`/`data`, `req_` id, `...T...:....000Z` timestamps, money as integer cents), 401 unauthenticated, 403 `ERR_ACCOUNT_SCOPE_VIOLATION`, 412 `ERR_STALE_MATERIAL_VERSION`, lot net-sellable (200 cy -> 171.0), bagged volume conversion + whole-bag rejection, confirm charge assembly and `quote_locked_at` freeze, credit reservation then release, load payload/`max_allowed_cubic_yards`, 409 `ERR_TRUCK_WINDOW_CONFLICT` across the 45-minute buffer, CONFIRMED->ALLOCATED->FULFILLED, container return issuance + full-refund close, invoice/underpayment/settle, claim segregation-of-duties -> review -> approve waterfall -> settle -> `CREDIT_MEMO_ISSUED`, the whole will-call queue chain (queue position, priority class, PPE gating, release), clock advance + `ERR_CLOCK_MUST_ADVANCE`, and pagination meta.

I also confirmed `start.sh` `exec`s Python in place (launcher PID *is* the server PID), so the harness's per-test kill leaves no orphan holding the port.

### Orchestrator verification after Steps 5 and 6

Confirmed `test_helpers/` (9 files) and `test_suite/` (18 files) are at the TASK ROOT, and `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` and the sweep script — no stray test directories were written under `workspace/`. `implementation/` holds 12 files including `start.sh`.

Also written by the orchestrator for Step 7: `workspace/sweep.sh`, a syntax-checked script file that runs the 8 rounds in parallel and `wait`s. Step 7 is instructed to invoke it under `setsid nohup ... &` and then poll for `results.$i.json`. Handing the fix agent a script file rather than an inline one-liner avoids the shell-quoting hazard where nested escaping injects literal quote characters into `--start-command` and kills all 8 rounds at t=0 with a ServerStartError.

## Step 7: Run Tests and Iterate — 2026-09-05T14:24:00.000Z

Subagent summary (verbatim):

Clean sweep achieved. All 8 parallel rounds pass 100/100.

## Summary

**Iterations run:** 2

**Per-round passed/total (final sweep, results written 14:23:44):**
| round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| result | 100/100 | 100/100 | 100/100 | 100/100 | 100/100 | 100/100 | 100/100 | 100/100 |

Iteration 1 was 96/100 in all 8 rounds — 4 deterministic failures, zero flakiness (no timing/load-induced failures anywhere).

**Tests deleted:** none. All 4 failures passed STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability).

**Fixes applied to `test_suite/`** — `/home/ubuntu/github/CodingPRD/tasks/task_2874_landscape_supply_yard_bulk_material_delivery/test_suite/test_13_validations.py`
- `TestClaimActionGuardsAndMoneyCeilings::test_review_steps_and_approval_arithmetic_are_both_refused` — the two `settle_claim_case` calls issued `ClaimsAdjuster` headers, so the PRD-faithful impl correctly returned `ERR_UNAUTHORIZED`. PRD 3.7: "Settling the claim is a `CreditManager` act and requires the claim to be `APPROVED`". Swapped both to `make_credit_manager_headers()`; the exact `ERR_CLAIM_NOT_APPROVED` / `ERR_CLAIM_NOT_PAYABLE` assertions are unchanged.
- `_referential_yard` fixture + `TestReferentialConfigRules::test_missing_po_foreign_account_po_stray_target_and_dead_season_are_refused` — the fixture tried to seed an *untagged* order on a `po_required=True` account, which PRD 3.4 forbids at creation ("an untagged order on such an account is refused with `ERR_PO_REQUIRED` **both at creation** and again at confirm"), so setup died with the very error the test was hunting. The fixture now gives account_a its own purchase order and seeds one legitimately *tagged* order (keeping `total_count == 1` meaningful), and the assertion exercises the same `ERR_PO_REQUIRED`/422 rung at the creation endpoint named verbatim in PRD 2.8 rung 29. No assertion was weakened; the confirm-time restatement of the rule is unreachable through the API since no endpoint flips `po_required` after creation.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`**
- `workspace/implementation/calc.py`, `finalize_order_money` — replaced the bare `order["final_total_cents"] = ...` with `apply_charges(order, figures, "final_total_cents")`. PRD 3.5 says the final basis differs from the confirm basis "in three respects" only (price-row instant, billable quantity, axle base), and PRD 3.4's step one/two explicitly *set* `bulk_subtotal_cents` / `bagged_subtotal_cents` — reinforced by PRD 3.5's "each keeps its quoted `line_price_cents` and contributes it unchanged to `bagged_subtotal_cents`". The impl was computing the final figures but discarding the breakdown, leaving `bulk_subtotal_cents` frozen at the quote-basis value after a mid-flight price promotion.
- `workspace/implementation/routes_willcall.py`, `release_ticket` — added `calc.evaluate_credit_posture(account)` after the credit recompute. PRD 3.3: "The account transitions `ACTIVE -> CREDIT_HOLD` on **any recompute** where `credit_used_cents` is strictly greater than `credit_limit_cents`". The delivery close-out already evaluated posture; the will-call release path recomputed credit but never ran the hysteresis test, so an account overrun by a will-call release stayed `ACTIVE` (and its queued tickets were never cancelled). No new side effect beyond that PRD sentence was introduced — I deliberately did *not* add a purchase-order recompute here, since PRD 3.6's release paragraph does not name it.

Also removed stale `__pycache__` directories from the artifact tree. `worklog.md` was neither read nor modified.

### Orchestrator verification after Step 7

Independently re-verified rather than trusting the subagent's claim. All eight `workspace/implementation/results.$i.json` files physically exist on disk (timestamped 14:23, ~33.5 KB each) and each parses to `passed=100 total=100 failed=0`. `workspace/sweep.log` contains the `ALL_ROUNDS_DONE` marker exactly once, confirming the sweep's `wait` returned normally rather than the rounds being reaped. A direct count of test functions in `test_suite/*.py` is 100, matching the 100 collected in every round — consistent with the reported zero deletions.

Step 8 is NOT skipped: Step 7 ran 2 iterations with 2 `test_suite/` fixes and 2 `implementation/` fixes, so the skip condition (zero iterations beyond the baseline) does not apply. The two implementation fixes are the PRD-silence sites Step 8 must target.

## Step 8: Finalize PRD — 2026-09-05T14:30:00.000Z

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` is a two-sentence-level patch of `PRD.md`.

**Line counts:** PRD.md 477 -> PRD_FINALIZED.md 477 (0.0% delta; 2 long lines revised, 15822 -> 15913 words). Last line is still `| \`ERR_UNDERPAYMENT\` | 402 |`, the final row of the §5 error table.

**Changes**

- §3.5 (delivery close-out, line 256) — *revise* — after "the order's `final_total_cents` is assembled from those figures", pinned that the final-basis assembly re-runs the same eight steps and therefore **rewrites** the order's published breakdown figures (`bulk_subtotal_cents`, `bagged_subtotal_cents`, `volume_discount_pct`, `volume_discount_cents`, `min_load_fee_cents`, `delivery_fee_cents`) from the final basis, with `quoted_total_cents` the one figure left frozen — `implementation/calc.py:755-765` (`finalize_order_money` -> `apply_charges(order, figures, "final_total_cents")`, `calc.py:311-315`).
- §3.6 (will-call release, line 284) — *revise* — same breakdown rewrite stated by reference to §3.5, and the `credit_used_cents` recompute explicitly put through the §3.3 credit-posture test — `implementation/routes_willcall.py:199` and `routes_willcall.py:206-207`.

**Per-edit pre-edit search log**

Edit 1 — subject: which order-level money fields the final-basis charge assembly writes.
(b) Enumerated/read: `calc.py:270-304` (`assemble_charges`, the only producer of the figures dict), `calc.py:311-315` (`apply_charges`, the only writer of the six breakdown keys plus one total field), `calc.py:755-765` (`finalize_order_money`), both callsites `routes_delivery.py:307` and `routes_willcall.py:199`, the confirm-time callsite `routes_orders.py:346` (`quoted_total_cents`), order creation defaults `routes_orders.py:62-69`, order serialization `serial.py:73-82`, and a repo-wide grep for every mention of the six breakdown fields / `quoted_total_cents` / `final_total_cents` (hits confined to those files plus the read-only `order_value_cents` at `calc.py:119-121` and the payment due at `routes_orders.py:431`). No other path writes them — notably the claim-settlement cascade (`routes_claims.py:221-249`) moves `credit_memo_cents` only, and the refusal branch touches no money at all.
(c) Adjustment: wrote "rewrites ... with the values the final basis produces" rather than "recomputes only the bulk subtotal". On a `WILL_CALL` order the same helper writes `min_load_fee_cents`/`delivery_fee_cents` as 0 and on a delivery it can genuinely move the fee and the discount tier, so the wording had to be widened to all six fields; and I added the explicit "`quoted_total_cents` is the one figure left untouched" because `apply_charges` writes only the passed-in total field.

Edit 2 — subject: the will-call release cascade, specifically the account recompute and what follows it.
(b) Enumerated/read: `routes_willcall.py:185-208` (`release_ticket`, the Step 7 site), `calc.py:447-464` (`evaluate_credit_posture`, both hysteresis directions plus `touch`), `calc.py:557-569` (`cancel_queued_tickets_for_account` -> `evaluate_revert` + `recompute_lots_of_order`), `calc.py:424-440` (`recompute_account`), and every other `evaluate_credit_posture` callsite: `routes_delivery.py:328` (close-out), `routes_orders.py:403`/`:442` (confirm and cancel), `routes_claims.py:248` (settle), `routes_accounts.py:76` (credit adjustment, the sole `standalone=False` caller). Also checked `calc.py:467-481` (`recompute_po`) to confirm the release path does *not* recompute the purchase order.
(c) Adjustment: phrased it as "puts that recompute through the credit-posture test of section 3.3 like any other" instead of naming a one-way `ACTIVE -> CREDIT_HOLD` step — the impl runs the bidirectional band here (a final total below the quote can release a held account), and §3.3 already carries the queued-ticket cancellation and version consequences. I deliberately did **not** add a purchase-order recompute to this sentence, since `release_ticket` has none.

No PRD edits were made for the two `test_suite/test_13_validations.py` fixes: PRD §3.7 already states verbatim that settling is a `CreditManager` act (matching `routes_claims.py:209`), and PRD §3.4 already forbids an untagged order on a `po_required` account at creation — both were fixture bugs, not PRD silence.

### Orchestrator verification after Step 8

`PRD_FINALIZED.md` exists and is NOT byte-identical to `PRD.md` (`cmp` reports a difference; 477 lines in both, 113044 -> 113742 bytes, i.e. +698 bytes of inserted prose in the two revised §3.5/§3.6 lines). Its final line is still the last row of the §5 error table, so nothing was truncated. Step 8's own byte-identical outcome would have been legitimate had Step 7 made no implementation fixes, but Step 7 made two, and the patch correctly targets exactly those two sites.

## Step 9: Complete PRD — 2026-09-05T15:12:00.000Z

Run as THREE sequential file-partitioned passes over one shared `PRD_COMPLETED.md`, rather than a single monolithic scan. Rationale (orchestrator decision, no user available to consult): the implementation is 3,461 lines across 11 modules with 66 endpoints, and a single subagent asked to walk all of it exhaustively reliably under-delivers — it produces a handful of edits and declares completeness. Partitioning by implementation module keeps each pass's reading load tractable while still covering every module exactly once. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying (a `cp` in a later pass would silently destroy the earlier passes' edits) and each was handed the list of ground already settled so they neither redid nor reverted prior work.

Partition:
- Pass 1 — `core.py`, `app.py`, `serial.py`, `routes_catalog.py`, plus the inventory/moisture math in `calc.py`.
- Pass 2 — `routes_accounts.py`, `routes_orders.py`, plus the pricing/charge-assembly/credit/pre-buy/PO math in `calc.py` and the five matching serializers.
- Pass 3 — `routes_delivery.py`, `routes_willcall.py`, `routes_claims.py`, plus the load-fit/queue-ranking/claim-waterfall/container-deposit math in `calc.py` and the five matching serializers; pass 3 also owned the final structural integrity check.

### Pass 1 summary (verbatim)

Pass 1 of 3 complete. Copy made from `PRD_FINALIZED.md`. Lines 477 -> 477 (every edit in-paragraph); chars 113,742 -> 120,107 (+6,365). Last line still the final §5 error row; 15 prose lines differ from source; no new sections, no table rows added.

Counts: ambiguity-pins 13, mismatch-revisions 2 (18 changes).

Changes: §2.1 whitespace-only header counts as empty (401) and values are trimmed (core.py:375-384). §2.2 `api_request_id` is `req_` + exactly 20 upper-case alnum chars (core.py:325-331). §2.3 filters match exactly and are not enum-validated (unknown value -> empty page, empty value ignored); the one boolean filter `prebuy_eligible` must parse or 400; `limit`/`offset` are not filters (core.py:584-600, routes_catalog.py:73). §2.4 `created_at`/`updated_at` come from the server wall clock, not the logical clock, and are equal on creation (core.py:184-203, 301-309). §2.4 instant inputs parsed leniently (`Z`, numeric offset, no designator -> UTC, bare date -> midnight UTC), normalised to UTC, re-rendered with 3 fractional digits (core.py:206-219). §2.4 a neighbour recompute landing on unchanged figures does NOT advance that neighbour's `version`/`updated_at` (calc.py:362-379). §2.5 clock-advance response arrays ordered by `created_at` ascending, empty arrays when nothing fired (routes_catalog.py:270-298). §2.7 `expected_material_version` is input-only, neither persisted nor echoed (routes_catalog.py:135, serial.py:34-38). §2.8 rung 5 explicit `null` counts as absent; absent/unparseable body treated as `{}`; non-object JSON body is itself malformed (core.py:408-422). §3.1 PATCH material fields both optional, a no-field patch is accepted and still bumps `version` (routes_catalog.py:94-110). §3.1 backdated guard compares only against the `EFFECTIVE` row; none -> any date accepted; `SCHEDULED` rows never constrain a filing (routes_catalog.py:116-145). §3.1 one advance promotes every due row of a material in `effective_from` ascending order, each superseding the previous (routes_catalog.py:268-284). §3.1 in-force row selection is status-agnostic and breaks an `effective_from` tie in favour of the later-created row (calc.py:195-206). §3.2 intake allowed for a material in any status; the two computed material fields are render-time derived so lot movement never bumps the Material's version (serial.py:21-31, calc.py:176-189). §3.2 `current_moisture_pct` and `set_quarantine` both mandatory; lot `version` advances even when the reading moves no volume (routes_catalog.py:239-253). §3.2 REVISE (mismatch): the reading writes `status` outright regardless of prior state, so `set_quarantine=false` also returns a `DEPLETED` lot to `AVAILABLE` (routes_catalog.py:251). §3.2 REVISE (mismatch): depletion refreshes `withdrawn_gross_cubic_yards` before recomputing/comparing `net_sellable_cubic_yards`; only an `AVAILABLE` lot can deplete; "excluded from all future allocation" softened to "for as long as it remains `DEPLETED`" (calc.py:362-389). §5 intro: unmatched path -> `ERR_NOT_FOUND` 404, unsupported method -> `ERR_INVALID_REQUEST` under 405, both decided before any header check; trailing slash not significant (app.py:40-52).

Verified already uniquely pinned: all 75 error ids and HTTP statuses match `core.ERROR_HTTP` exactly (script-diffed, zero discrepancies); envelope shape and `response_type` values; pagination bounds, `total_count` pre-pagination, `has_more`, `created_at` ascending ordering; rounding conventions; the 401->403->404 and shape-before-path-before-FK rung order; logical clock default `2026-08-01T00:00:00Z` and forward-only guard; the moisture multiplier and both `net_sellable_cubic_yards` variants to the digit; serializer key sets for Material/PriceSchedule/InventoryLot with no internal field leaking; role lists for all 11 in-scope endpoints.

### Pass 2 summary (verbatim)

Pass 2 complete. `PRD_COMPLETED.md` edited in place with 19 targeted `Edit` calls (no `cp`, no whole-file `Write`); 477 lines, 24 headings, last line still the final §5 error row; both pass-1 spot-checks verified present. Chars 120,107 -> 126,698 (+6,591). Counts: 15 ambiguity-pins, 7 mismatch-revisions (22 changes).

Changes: §3.3 `business_name` must be a non-empty string. §3.3 REVISE (mismatch): the credit roll-up is not recomputed on `settlement_status` changes — invoicing recomputes nothing, so re-invoicing a `SETTLED` order leaves `credit_used_cents` excluding it. §3.3 REVISE (mismatch): a credit adjustment runs the posture test in both directions, not just `CREDIT_HOLD -> ACTIVE`. §3.3 `new_credit_limit_cents` >= 0, non-empty `memo`, `credit_available_cents` = new limit - existing used, `version` +1 exactly once. §3.3 `po_number`/`job_code` non-empty; uniqueness spans every PO of the account whatever its status. §3.3 REVISE (mismatch): an order tagged to an `EXHAUSTED` PO is stopped by the rung-17 `ERR_PO_NOT_OPEN` gate, which fires before `ERR_PO_LIMIT_EXCEEDED`. §3.3 REVISE (mismatch): closing a PO does not freeze `committed_cents` — the roll-up is unconditional, so a `CLOSED` PO's figures still move on cancel/reprice/credit memo. §3.3 a Contractor's PO list is silently narrowed before `total_count`, not refused. §3.3 inverted pre-buy season -> `ERR_INVALID_REQUEST` at the shape rung, before either FK resolves. §3.3 REVISE (mismatch): activation evaluates account-ACTIVE -> `prebuy_eligible` -> season, and `season_start_date` is not consulted. §3.3 pre-buy list contractor narrowing. §3.4 tagged PO status unchecked at creation; `WILL_CALL` orders ignore supplied delivery fields; `delivery_address` non-empty; `volume_discount_pct` opens at 0.0. §3.4 earliest-created ACTIVE pre-buy contract is selected and season-tested alone; no ACTIVE contract also yields `ERR_PREBUY_OUT_OF_SEASON`; a BAGGED line may carry `use_prebuy` and draws volume though its money is unaffected. §3.4 REVISE (mismatch): a bulk `line_volume_cubic_yards` is the quantity rounded half up to 2dp while `quantity` keeps full precision and is what confirm bills. §3.4 line-list contractor narrowing. §3.4 pre-buy balance tested against the confirm's summed draw, not per line. §3.4 allocation walks lines `created_at` ascending, a lot's headroom is reduced by earlier lines of the same confirm, and a shortfall abandons the whole allocation. §3.4 the PO-OPEN gate is rung 17 and so first of the nine; the nine are listed for readability, not evaluation order. §3.4 no price row in force -> unit basis zero, line prices 0, confirm not refused. §3.4 pricing + lot pinning are one hop, so each line's `version` advances by exactly one. §3.4 the DRAFT cancel path leaves an already-issued will-call ticket in `QUEUED`. §3.9 REVISE (mismatch): invoicing overwrites any `settlement_status` including `SETTLED` and still recomputes no money. §3.9 `paid_amount_cents` >= 0, overpayment stored as supplied, the figure replaces rather than accumulates.

Verified already uniquely pinned: the full confirm gate ladder order (rungs 10, 17, 18, 28, 29, 31-35); bulk/bagged line-pricing formulas incl. unrounded-basis extension and prebuy locked price with surcharge forced to zero; all eight charge-assembly steps incl. tier bounds 0.0/3.0/6.0 with inclusive-lower/exclusive-upper, the three-part min-load-fee condition and `WILL_CALL` exemption, and the $4.25/mi delivery fee rounded before adding; the final-basis assembly; every roll-up formula and its state-set filter; the hysteresis band (entry strictly above the limit, release at `cents(limit x 0.90)`); pre-buy `ACTIVE <-> EXHAUSTED` recompute transitions with the season-end guard; cancel compensation's gate order and three hops; settle's two accepted source states and underpayment rule; the five serializer field sets.

### Pass 3 summary (verbatim)

Pass 3 of 3 complete. All edits inline, in place; no `cp`, no whole-file `Write`. Chars 126,698 -> 133,473 (+6,775); cumulative vs `PRD_FINALIZED.md` (113,742) = **+19,731**. Counts: ambiguity-pins 16, mismatch-revisions 9 — 25 Edit calls touching 21 distinct lines inside §2.8 and §3.5-§3.8.

Changes: §2.8 rung 18 REVISE (mismatch): `ERR_ACCOUNT_CREDIT_HOLD` is never raised by stage-next — account posture is a clause of the candidate predicate, so a queue of held accounts' tickets yields `ERR_WILL_CALL_QUEUE_EMPTY` at rung 27 (routes_willcall.py:104/106, calc.py:743). §2.8 rung 36 REVISE (mismatch): the "net of other live loads" reduction applies only at `POST /delivery-loads`; the will-call load compares against the plain undelivered balance (routes_willcall.py:162 vs routes_delivery.py:173). §3.5 any truck status pair may be taken directly; `status` is the PATCH's only mutable field and is optional, and an omitted/identical status still advances `version` (routes_delivery.py:76-81). §3.5 an order with no `driveway_access_class` clears the access gate and imposes no driveway cap (routes_delivery.py:102/106). §3.5 the density material is the earliest-created bulk line's; with no bulk line `planned_payload_lb` is null and the weight gate cannot fire (calc.py:343, 330). §3.5 "live load" defined as `PLANNED` or `DISPATCHED` for balance headroom (routes_delivery.py:139). §3.5 the dispatch instant is the logical clock at dispatch, is what the final-basis repricing consults, and is not a published load field (routes_delivery.py:259, serial.py:101). §3.5 close-out: `actual_net_cubic_yards` required, `driveway_protection_used` a required boolean, both volumes >= 0 (routes_delivery.py:273-275). §3.5 a bulk line written by both the waterfall and the repricing advances `version` by exactly one for the whole close-out (calc.py:775). §3.5 every other lot pinned to a line of the same order is re-derived in the same hop, rewritten only on real movement; only the pinned lot is evaluated for `DEPLETED` (routes_delivery.py:318, calc.py:392). §3.5 hop three runs the posture band in both directions, including release from `CREDIT_HOLD` when the final total lands below the quote (routes_delivery.py:328). §3.5 Replanning REVISE x2 (mismatch): replan re-runs only the truck/window/fit checks — order `fulfillment_status`, `fulfillment_mode` and the order-balance gate are not re-run, so `ERR_LOAD_EXCEEDS_ORDER_BALANCE`/`ERR_ORDER_NOT_ALLOCATABLE` are unreachable there (routes_delivery.py:360-379). §3.5 a truck already `AVAILABLE` is not rewritten, so its `version` does not advance (routes_delivery.py:405). §3.6 no `fulfillment_status` gate at ticket issue; a ticket may be issued against a DRAFT order (routes_willcall.py:28-31). §3.6 `ppe_confirmed` carries no shape validation (absent/null/wrong type all give `ERR_SAFETY_ACK_REQUIRED`) while `safety_briefing_code` fails earlier as `ERR_INVALID_REQUEST` (routes_willcall.py:132/137). §3.6 REVISE (mismatch): an omitted `pallet_count` falls back to the computed bags-over-48 figure, and `pallet_count` 0 creates no record at all (routes_willcall.py:153/178, calc.py:626-631). §3.6 `loaded_cubic_yards` >= 0 (not strictly positive), `pallet_count` a non-negative integer. §3.6 REVISE (mismatch): the bay is freed at `LOADING -> LOADED`, not at release, since occupancy counts only `STAGED`/`LOADING` (routes_willcall.py:15). §3.6 the tagged purchase order's `committed_cents` is deliberately not recomputed on the will-call path (routes_willcall.py:196-207). §3.7 no state gate at filing: order/load/ticket status unexamined (routes_claims.py:39-52). §3.7 `approved_amount_cents` must be >= 0 (negative is malformed, not an arithmetic failure) (routes_claims.py:178). §3.7 REVISE (mismatch): `settlement_status` becomes `CREDIT_MEMO_ISSUED` from whatever value it holds, including `UNBILLED` and itself (routes_claims.py:229). §3.7 REVISE (mismatch): the deposit offset is spread across the order's container records in `created_at` order, skipping zero-forfeit records, statuses undisturbed — not applied to one targeted record (routes_claims.py:232-242). §3.8 REVISE (mismatch): will-call `issued_count` falls back to the delivery path's computed figure when the loader recorded no count (calc.py:626).

Final structural integrity check (all pass): 477 lines / 133,473 chars; last line is the final §5 error row; all five top-level sections present in order, none dropped or duplicated (§1 L3, §2 L11, §3 L170, §4 L324, §5 L397), all 21 subsections present exactly once; pass 1's §2.2 `api_request_id` sentence survives; pass 2's §3.9 revisions survive; `PRD_COMPLETED.md` is not byte-identical to `PRD_FINALIZED.md` (52 lines differ across all three passes); backtick balance verified on all 21 edited lines.

### Orchestrator verification after Step 9

Independently confirmed: `PRD_COMPLETED.md` is 477 lines / 133,473 bytes, i.e. **+19,731 bytes over `PRD_FINALIZED.md`** — decisively not the byte-identical no-op that signals a scan that never ran. `diff` against `PRD_FINALIZED.md` reports 104 changed lines (52 removed / 52 added, all in-paragraph rewrites). All five top-level sections are present and the final line is the last row of the §5 error catalogue, so nothing was truncated by any of the three passes. Grepped for scaffold leakage into the completed PRD: zero hits for `scaffold_` or the Step 2 difficulty directive.

Pipeline complete. Final tally across Step 9's three passes: 44 ambiguity-pins and 18 mismatch-revisions, 62 changes total. Every one of the 11 implementation modules was audited by exactly one pass. The task directory holds all nine artifacts the skill specifies, and the final 8-round sweep's `results.1..8.json` (100/100 each) remain in `workspace/implementation/`.
