# Worklog — task_2157_vegetation_line_clearance

## Step 1: Create task directory — 2026-08-27T04:44:52.730Z

Created `tasks/task_2157_vegetation_line_clearance/` and `tasks/task_2157_vegetation_line_clearance/workspace/`. Index 2157 = max existing (2156) + 1.

## Step 3: Copy shared files — 2026-08-27T04:45:08.946Z

Copied `./INSTRUCTION.md` -> `tasks/task_2157_vegetation_line_clearance/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-27T05:26:00.000Z

First attempt (agent 1) terminated early on an API error ("Connection lost mid-response") with zero files written. Relaunched with an explicit incremental-write protocol (many small appends, each well under the per-response output cap). Second attempt succeeded. Verbatim subagent summary follows.

All three artifacts are generated, YAML-valid, and pass the scaffold linter.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    71
  §1.1 entities declared:     13
  §1.8 instances scanned:     21
  §1.9 instances scanned:     47
  Calls scanned (§1.8+§1.9):  784
```

**Files** (under `/home/ubuntu/github/CodingPRD/tasks/task_2157_vegetation_line_clearance/`): `SCAFFOLD.yaml` (2764 L), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1864 L), `SCAFFOLD_CORNER_DESIGN.yaml` (2422 L).

**Profile** — beyond-Expert: ledger_reconciliation x compliance_audit, graph topology, parallel state shape, segregation_of_duties roles, layers = dual-variant calc / cascading side effects / OCC / rate-threshold triggers. `api_prefix: /vm`.

**Contents**
- **13 entities**: Prescription, Circuit, WorkPlan, WorkOrder, Crew, CrewAssignment, ProductionEntry, CustomerNotification, HazardTree, HerbicidePermit, StormEvent, BillingLine, OutageRecord. 18 FKs incl. self-referential `WorkOrder.parent_work_order_id` (storm split/merge).
- **10 state machines** — WorkOrder carries two parallel dimensions (`execution_status` with a STORM_PREEMPTED cycle; `billing_status` compound over BillingLine children); CustomerNotification and BillingLine are cyclic; HazardTree/HerbicidePermit branch. Plus 2 OCC concurrency rules (stale WorkOrder version on line draft; stale Crew version on storm reassignment).
- **10 calculations**: prescription selector, trim_cycle_months (nested clamp), dual-variant reliability index (rolling-36mo vs program-YTD), refusal-adjusted units, dual-variant billable amount (unit-price density tiers vs T&M with per-entry rounding), pinned-order settlement (retainage on gross / credit on net / storm premium), committed_cents, production_pct, crew rate, hazard risk score.
- **37 validations** (priority-ladder 1->60), **49 errors**, **7 roles** (CrewForeman is `entity_backed:Crew`; rest opaque), **71 endpoints** incl. `/vm/_clock/set_current_utc` with default clock `2026-08-01T00:00:00Z`.

**§1.8**: 21 instances — 2/3/2/2/3/3/2/2/2 across the nine rules (all >=2). Every formula-derived assert is a Python-computed literal (e.g. 864000 / 820800, 367034 vs 367033, 1042176->990067 vs 1059840->981848, cycle 36->29->24, risk 83.00/68.00/60.00/59.50).

**§1.9**: 54 instances across all nine guide sections (entities 11, state_machines 12, calculations 5, validations 10, endpoints 3, errors 4, rbac 4, cross-cutting 4, consistency 1), including 5 `excluded_because` stubs pointing at existing §1.8 instances.

Checks run: no duplicate instance names, zero unbound `${var}`, every error code referenced >=2x, no forbidden concurrency vocabulary, design keys absent from `SCAFFOLD.yaml`.

## Step 4: Generate PRD — 2026-08-27T05:38:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2157_vegetation_line_clearance/workspace/PRD.md` — 417 lines, written incrementally in 11 appends. The two withheld design indices were never opened.

**Sections (in order):** 1. Introduction · 2. Global Specifications (2.1 RBAC, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Identity/Timestamps/Version, 2.5 Path Resolution, 2.6 Logical Clock, 2.7 Rounding Discipline, 2.8 OCC, 2.9 Order of Rejection, 2.10 Cascades & Conserved Quantities) · 3. Business Logic (3.1 Prescriptions, 3.2 Circuits/Cycles/Outages, 3.3 Plans & Spans, 3.4 Crews/Bookings/Production, 3.5 Notification & Refusal, 3.6 Hazard Trees, 3.7 Herbicide Permits, 3.8 Storm Response, 3.9 Billing) · 4. Endpoint Definitions · 5. Error Code Catalogue.

**Coverage audit (covered / declared):**
- Entities 13/13; entity fields 96/96 verbatim in backticks
- State machines 10/10 blocks (incl. both WorkOrder dimensions), 61/61 transitions with from/to, preconditions+error ids, side effects
- Calculations 10/10 in prose (all constants embedded, both dual-variant pairs, pinned rounding orders)
- Validations 37/37 with error ids and the full ascending priority ladder stated in §2.9
- Endpoints 71/71 in the 4-column table; request-body identifiers 63/63, query params 29/29, computed-read output fields 15/15
- Errors 49/49 in the 2-column table, all 49 also triggered in §2/§3 prose
- Roles 7/7 with identity semantics; OCC rules 2/2 (endpoint + occ field + error id + 412)
- States and enum values: 0 missing

**Hard contracts:** Contract 1 Field-Name Coverage PASS (0 missing across all four sets). Contract 2 Rule Coverage PASS. Contract 3 §3 Path Purity PASS (845 tokens scanned; 0 slash-leading, 0 bare methods, 0 method+path).

_Orchestrator verification_: 417 lines; headings 1–5 all present and ordered; endpoint table 71 data rows; error catalogue 49 data rows; file ends on a complete table row (no truncation).

## Step 6: Generate implementation — 2026-08-27T05:56:00.000Z

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2157_vegetation_line_clearance/workspace/implementation/`

**Files written (2,796 lines total):**

| File | Lines | Role |
|---|---|---|
| `app.py` | 54 | Flask entry, blueprint registration, error handlers, `0.0.0.0:$PORT` |
| `store.py` | 135 | In-memory dicts (13 collections), logical clock (default `2026-08-01T00:00:00Z`), calendar-month math |
| `errors.py` | 65 | 49-entry error->HTTP catalogue + `ApiError` |
| `envelope.py` | 99 | `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination |
| `auth.py` | 54 | `X-User-ID`/`X-User-Role`, 7 roles, 401->403 ordering |
| `validate.py` | 145 | Priority-6 FK existence + priority-7 shape/range/uniqueness |
| `calc.py` | 206 | All 10 calculations, `Decimal`/`ROUND_HALF_UP` throughout |
| `services.py` | 522 | Cascades: plan/circuit counters, billing settlement, refusal 4-hop, storm 4-hop + inverse demobilization, terminal-vs-invalid state gate |
| `constants.py` | 29 | Enum member sets |
| `routes/*.py` (12) | 1,479 | One module per resource group |
| `start.sh` | 8 | Guarded `pip install`, `exec python3 app.py` |

**Endpoints: 71 implemented / 71 declared** (verified by enumerating Flask's url_map for `/vm` paths).

**Boot test:** `PORT=18191 bash start.sh` from a fresh process -> `/health` returned 200 within ~3s; `GET /vm/circuits` returned `total_count: 0`, confirming **no seeding at startup**. All `.py` files pass `python3 -m py_compile`.

**Behaviour verified by three live smoke runs:** full prescription->circuit->plan->span->crew->production->completion->billing->payment chain; trim-cycle clamping (48mo, 90mo cases) and day-clamped month arithmetic; T&M per-entry rounding (97,248.75 -> 97,249 cents) vs unit-price density tiering; storm 4-hop preemption with unit conservation (parent 40 + child 60 = plan 100) and exact restoration on demobilize; refusal cycle to `FINAL_REFUSAL` with unit withholding; permit same-chemical and third-mutual-overlap conflicts; both OCC guards (412); crew schedule conflict with 60-min buffer; hazard risk score 91.00 with segregation-of-duties and off-ROW consent gates; committed-cents conservation across supersede/void.

**Two judgement calls** where the PRD is self-shadowing: (1) terminal-state check runs before the declared-transition check, since the literal §2.9 order would make `ERR_ALREADY_TERMINAL` unreachable; (2) `ERR_BUFFER_VIOLATION` triggers when the permit's `buffer_ft > 0` and the span carries any `FINAL_REFUSAL` notification — no per-premise distance field exists in the model.

## Step 5: Generate unit tests — 2026-08-27T06:12:00.000Z

Test infrastructure complete.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2157_vegetation_line_clearance/`)

`test_helpers/` — 1,709 lines: `__init__.py` (22), `types.py` (388, append-only `ProductionEntry`/`OutageRecord` carry only `id`+`created_at`), `api_client.py` (295, all 71 endpoints + `raw_get`), `api_errors.py` (111, 48 error IDs registered), `assertions.py` (145), `factories.py` (173), `constants.py` (72), `test_users.py` (45, with `make_crew_foreman_headers(crew_id)` for the entity-backed `CrewForeman`), `fixtures.py` (458, 5 tiers: single-step builders -> `setup_circuit`/`setup_released_span`/`setup_in_progress_span`/`setup_completed_span` -> billing lifecycle -> refusal/hazard targeting -> storm preemption + read-backs).

`test_suite/` — 2,564 lines: `conftest.py` plus 10 domain-named files (`test_01_trim_cycle_and_reliability` ... `test_10_access_control_and_paths`).

**Tests emitted:** 89 test functions (100 collected cases after parametrization), each carrying exactly one `Design:` tag — 89 tags, 1:1, no untagged or dual-tagged tests.

**Coverage**
- Queue A (Difficulty): **21/21** instances, exactly 2 tests each (42 tests).
- Queue B (Corner): **47/47** non-stub instances, >=1 test each (47 tests).
- 7 `excluded_because:` stubs correctly **not** translated; all 7 `difficulty_instance` cross-references verified to resolve.

**Instances skipped:** none. All 68 translated instances passed the PRD-first two-condition filter.

Two individual assertions inside otherwise-translated instances were dropped as PRD-silent (instance still covered): `parent_work_order_id == null` on a non-storm span (`corner_work_order_initial_states_on_both_dimensions`) and `clearance_radius_ft == null` after a rejected map (`corner_map_clearance_below_prescription_is_rejected`) — the PRD names neither default; and `superseded_by_billing_line_id == null` on a plain void (`billing_line_draft_then_void_...`), where the PRD only states the field's value when a *superseding* draft caused the void.

**Verification run**
- `python3 -m py_compile` over all 20 generated `.py` files: **ALL OK**.
- All modules import cleanly under `PYTHONPATH=.`; `pytest --collect-only` collects 100 tests, 0 errors.
- Automated citation audit: 152 quoted PRD sentences, **all verbatim** against a whitespace-normalized `PRD.md`, all >=8 words.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no "scaffold"/`§1.x`/"Table N" references leak into generated code.

## Step 7: Run tests and iterate — 2026-08-27T06:29:00.000Z

All 8 parallel rounds pass 100/100.

**Iterations run:** 4 full 8-round parallel sweeps (baseline + 3 after fix batches). Failures were fully deterministic — the same set failed in all 8 rounds every time; no flakiness surfaced.

**Baseline:** 91/100, 9 failing tests, all with the identical setup error `HTTP 409: ERR_INVALID_STATE - the owning plan does not accept mapping` — the >=5-shared-error triage hint pointed straight at `test_helpers`.

**Tests deleted:** none. Every failing test's rule was verbatim in the PRD and uniquely derivable.

### Fixes applied to `test_helpers/`

`test_helpers/fixtures.py`:
- **`setup_plan_with_mapped_span`** — new `extra_spans` argument (flows down through `setup_released_span` / `setup_in_progress_span` / `setup_completed_span` / `setup_completed_span_with_draft_line` via `**kwargs`). Sibling spans are now created and mapped while the plan is still `DRAFT`. *Why:* PRD §3.3 — "Mapping requires the span to be at `PLANNED` and the owning plan to be in `DRAFT`, `RELEASED` or `IN_PROGRESS`" — combined with "If every span of the plan is now in `COMPLETED` or `CANCELLED` and at least one is `COMPLETED`, the plan moves `IN_PROGRESS -> COMPLETED`". The old fixture chain completed the plan's only span (closing the plan) and *then* tried to map a second span, a precondition the PRD forbids. Holding the sibling at `MAPPED` also correctly keeps the plan in `IN_PROGRESS`.
- **`complete_prepared_span` (new)** — walks an already-mapped sibling through release -> book -> start -> production -> complete.
- **`add_completed_span`** — reimplemented on top of `complete_prepared_span`; docstring now states it is valid only while the plan is still open.

Call sites updated to the PRD-legal ordering (test bodies and assertions untouched): `test_02_billing_pricing.py` (`_two_spans_same_field_outcome`, `_two_dense_spans`, `_spans_at_and_below_forty_units_per_mile`), `test_03_billing_lifecycle.py` (`_plan_with_disputed_and_submitted_lines`), `test_09_plan_and_span_lifecycle.py` (`test_cancelling_the_plan_cancels_live_spans_frees_crews_and_voids_drafts`, plus its now-unused `map_span` import).

### Fixes applied to `implementation/`

`workspace/implementation/routes/workplans.py` — **`cancel_plan`**: the `DRAFT -> VOID` sweep and the follow-up `derive_billing_status` now run over **every** span of the cancelled plan, not only the spans the cascade just moved to `CANCELLED`.

*Why:* PRD §3.3 states the cascade performs "every `DRAFT` billing line on those spans moves `DRAFT -> VOID`". Scoping "those spans" to the newly-cancelled ones makes that clause unreachable, because §3.9 permits a `DRAFT` line only on a span whose "`execution_status` must be `COMPLETED`", and a `COMPLETED` span is explicitly skipped by the cancel loop. §3.9 also lists "the plan-cancellation cascade" among the events that recompute `committed_cents`, which is likewise inert under the narrow reading. The plan-wide reading is the only one under which both sentences have effect, so this is an implementation bug rather than a test-fairness problem. Voided lines correctly drop out of `committed_cents` (§2.10 cents conservation) and the span's `billing_status` falls back to `BILLABLE` per §3.9.

_Orchestrator verification_: re-read all 8 `results.{1..8}.json` independently — every round reports `passed=100 / total=100`.

## Step 8: Finalize PRD — 2026-08-27T06:33:00.000Z

Done. One PRD edit was needed.

**Line counts:** PRD.md 417 lines -> PRD_FINALIZED.md 417 lines (0% delta; one line revised in place, no lines added).

**Changes**

- §3.3 (plan-cancellation cascade) — revise — "every `DRAFT` billing line on those spans moves `DRAFT -> VOID`" -> "every `DRAFT` billing line on any span of the plan — the spans just cancelled and the plan's already `COMPLETED` spans alike — moves `DRAFT -> VOID`" — `implementation/routes/workplans.py:64-74` (the void loop and the follow-up `derive_billing_status` run over `services.plan_orders(plan["id"])`, i.e. every span, while only non-`COMPLETED`/non-`CANCELLED` spans are moved to `CANCELLED` at line 65-66).

**Pre-edit search log (edit 1)**

(a) Subject: which spans' billing lines the plan-cancellation cascade voids, and the downstream `billing_status` / `committed_cents` effects of that void.

(b) Impl paths enumerated and read:
- `routes/workplans.py:58-81` `cancel_plan` — the Step 7 site; loop is plan-wide, `derive_billing_status` fires when a line was voided **or** the span was just cancelled; `recompute_plan` + `recompute_committed` both plan-wide with `bump=False` (plan is `store.touch`ed once).
- `routes/workorders.py:138-146` `cancel_work_order` (span-level cancel) — calls only `services.cancel_order` + `recompute_plan`; does **not** void lines. Checked so the new wording stays confined to the plan-level cascade and does not leak a line-voiding claim into span cancel (the sentence's earlier clause).
- `services.py:360-363` `cancel_order` — sets `CANCELLED`, touches, releases assignments; no line handling.
- `services.py:228-241` `derive_billing_status` + `services.py:209-211` `newest_live_line` — target is `BILLABLE` only when `execution_status == COMPLETED`, else `NOT_BILLABLE`; no-ops (no version bump) when unchanged. Confirms a just-cancelled span's derive call is inert (a non-`COMPLETED` span is always already `NOT_BILLABLE`), so the only observable effect is on `COMPLETED` spans — matching the wording, and matching §3.9's existing "falls back to `BILLABLE`" sentence, which already names the plan-cancellation cascade as a voiding agent. No new §3.9 text needed.
- `services.py:151-161` `recompute_committed` + `plan_lines` — plan-wide sum over `DRAFT/SUBMITTED/APPROVED/PAID`; PRD §3.9 already says "regardless of what `execution_status` those spans are in" and lists the plan-cancellation cascade among recompute triggers, so the existing "`committed_cents` are both recomputed" clause was left verbatim.
- Grepped all `VOID` / `derive_billing_status` / `recompute_committed` writers (`routes/billing.py` draft-supersede, submit, review, resubmit, void, pay; `routes/notifications.py:104` refusal hop four) — none is plan-scoped, so widening the cancel clause creates no conflict with them.

(c) Wording adjustment: phrased as "any span of the plan — the spans just cancelled and the plan's already `COMPLETED` spans alike" rather than a bare "every span", so it stays a superset statement that also covers spans cancelled in an earlier call (which can hold no `DRAFT` line anyway, since §3.9 requires `COMPLETED` to draft) without asserting anything false about them. Deliberately did not add a `billing_status`-re-derivation clause here — §3.9's existing void paragraph already covers it generically, and restating it locally risked a narrower claim than `derive_billing_status` actually makes.

**Not patched (traced, but no PRD silence/mismatch):** all `test_helpers/fixtures.py` changes (`extra_spans`, `complete_prepared_span`, `add_completed_span`) and their call-site reorderings are fixture bugs against rules already verbatim in PRD §3.3 — mapping preconditions (`PLANNED` span, plan in `DRAFT`/`RELEASED`/`IN_PROGRESS`) and the plan auto-completion rule. No tests were deleted, so there is no weakened-assertion surface to pin.

_Orchestrator verification_: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 190), in-place, no additions or deletions.

## Step 9: Complete PRD — 2026-08-27T06:40:00.000Z

Done. `PRD_COMPLETED.md` is written.

**Files**
- Source `PRD_FINALIZED.md`: 417 lines / 82,664 chars
- Output `PRD_COMPLETED.md`: 417 lines / 86,840 chars (**+4,156 chars**, 24 changed line-blocks, no new sections/paragraphs)

**Counts:** 28 edits — **18 ambiguity-pins**, **10 mismatch-revisions**.

**Both named judgement calls verified against code and pinned:**
- (i) Confirmed. `services.py:513-521` `require_state()` tests `TERMINAL_STATES` first, then declared-from. The literal §2.9 ladder (10 = invalid-state, 11 = already-terminal) would make `ERR_ALREADY_TERMINAL` unreachable. Revised: items 10/11 swapped.
- (ii) Confirmed. `routes/production.py:68-73` — the guard is `buffer_ft > 0` AND *any* `FINAL_REFUSAL` notification on the span; no per-premise distance field exists in the model. Revised, including that `buffer_ft == 0` never trips it.

**Every change:**
- §2.1 — revise — ambiguity — a blank/whitespace `X-User-ID` is `ERR_UNAUTHENTICATED` — auth.py:24
- §2.3 — insert — ambiguity — `created_at` ties (routine, since the clock is frozen) break by insertion order — store.py:133
- §2.8 — revise — ambiguity — version fields on other endpoints are silently ignored, not rejected — validate.py:8
- §2.9 — revise — mismatch — terminal check runs before declared-transition check — services.py:513
- §2.10 — insert — ambiguity — recompute-driven cascades bump `version` only when a value actually changes — services.py:130,151,120
- §3.3 — revise — ambiguity — mapping with a bad plan state -> `ERR_INVALID_STATE`; `clearance_radius_ft` shape bound is >=0 — routes/workorders.py:51,56
- §3.3 — revise — ambiguity — span release with a bad plan state -> `ERR_INVALID_STATE` — routes/workorders.py:80
- §3.3 — insert — ambiguity — start with no `SCHEDULED` booking -> `ERR_INVALID_STATE` — routes/workorders.py:98
- §3.3 — revise — ambiguity — cancellation `reason` is not persisted or echoed — routes/workorders.py:138
- §3.3 — insert — ambiguity — plan-cancel cascade re-derives each touched span's `billing_status` — routes/workplans.py:73
- §3.3 — insert — ambiguity — production summary writes back counters + `committed_cents`, no `version` bump — routes/workplans.py:112
- §3.4 — revise — ambiguity — no span-state precondition on booking; crew `version` bumps regardless — routes/crews.py:75,101
- §3.4 — revise — mismatch — `herbicide_permit_id` at zero gallons stores whatever the client supplied — routes/production.py:89
- §3.5 — revise — ambiguity — notify on a cancelled span -> `ERR_INVALID_STATE` — routes/notifications.py:52
- §3.5 — insert — ambiguity — finalize at round 1 -> `ERR_INVALID_STATE` — routes/notifications.py:93
- §3.6 — insert — ambiguity — unassigned tree -> `ERR_NOT_CREW_OWNER`; span not `IN_PROGRESS` -> `ERR_INVALID_STATE` — routes/hazard.py:122,136
- §3.7 — revise — mismatch — buffer violation keyed on `buffer_ft > 0` + any `FINAL_REFUSAL` — routes/production.py:68
- §3.7 — revise — mismatch — expiry fires only on a gallons-bearing entry; activation never expires — routes/production.py:17; routes/permits.py:93
- §3.7 — revise — ambiguity — revoke `reason` not persisted — routes/permits.py:103
- §3.8 — revise — mismatch — storm counters recount deployed crews + still-`PREEMPTED` bookings — services.py:367
- §3.8 — insert — ambiguity — close with a still-preempted booking -> `ERR_INVALID_STATE` — routes/storms.py:83
- §3.9 — revise — mismatch — draft bumps span `version` only when the derived `billing_status` moves — services.py:236; routes/billing.py:65
- §3.9 — revise — ambiguity — newest-line ranking has a third tiebreak (creation order desc) — services.py:214
- §3.9 — revise — mismatch — `committed_cents` also recomputed on payment and on summary read — routes/billing.py:165; routes/workplans.py:113
- §3.9 — revise — ambiguity — `dispute_reason` validated but not stored/echoed — routes/billing.py:104
- §3.9 — revise — ambiguity — void `reason` not stored/echoed — routes/billing.py:141
- §3.9 — revise — mismatch — post-void fallback is `BILLABLE` only if the span is still `COMPLETED`, else `NOT_BILLABLE` — services.py:231
- §4 — revise — mismatch — `POST /storm-events/{id}/reassignments` answers 201 with the storm event — routes/storms.py:63

_Orchestrator verification_: 417 lines preserved, 27 headings intact, 24 changed line-blocks, file ends on a complete table row (no truncation). Steps 8 and 9 touched only PRD documents — `implementation/` and the test artifacts are byte-identical to the state that passed Step 7's final 8-round sweep, so the 100/100 result stands.

## Pipeline complete — 2026-08-27T06:41:00.000Z

All 9 steps finished. Final state: 100 tests, 100/100 passing across 8 independent per-test-server rounds; 0 tests deleted.
