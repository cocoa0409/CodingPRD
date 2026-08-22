# Worklog — task_2121_medical_surgical_supply_distribution

## Step 1: Create task directory — 2026-08-17T18:03:59.271588530Z

Created `tasks/task_2121_medical_surgical_supply_distribution/` and `workspace/`. Index 2121 = highest existing (2120) + 1.

## Step 3: Copy shared files — 2026-08-17T18:03:59.271588530Z

Copied `./INSTRUCTION.md` → `tasks/task_2121_medical_surgical_supply_distribution/workspace/INSTRUCTION.md` (done early alongside Step 1; independent of Step 2).

## Step 2: Generate scaffold — 2026-08-17T19:03:34.789231098Z

All three scaffold artifacts are generated and lint-clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_2121_medical_surgical_supply_distribution/SCAFFOLD.yaml` (§1.0–§1.7, 2449 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2121_medical_surgical_supply_distribution/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key)
- `/home/ubuntu/github/CodingPRD/tasks/task_2121_medical_surgical_supply_distribution/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key)

## Complexity profile
`pricing_engine` × `compliance_audit`; layers = dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers; topology `graph` (two junction entities + two self-referential edges); shape `parallel`; role model `segregation_of_duties`; consistency `immediate`. Calibrated above the Expert band deliberately (`difficulty_level: expert_plus`).

## Contents
- **12 entities**: SupplyRoom, Item (self-ref `lum_parent_item_id`), GpoContract (self-ref `supersedes_contract_id`), ContractLine, FormularyItem, Lot, ReplenishmentOrder, OrderLine, SubstitutionRequest, RecallNotice, DeliveryRoute, ChargebackClaim.
- **11 state machines** across 10 entities, incl. ReplenishmentOrder's two parallel axes (`fulfillment_status` × `settlement_status`) and four cycles (GpoContract ACTIVE⇄SUSPENDED, Lot AVAILABLE⇄EXCURSION_HOLD, FormularyItem APPROVED⇄RESTRICTED, SubstitutionRequest PENDING⇄INFO_REQUESTED, ChargebackClaim SUBMITTED→DISPUTED→SUBMITTED).
- **2 concurrency rules** (OCC only): `order-line-write-stale-order` (ReplenishmentOrder.version), `par-adjust-stale-formulary-item` (FormularyItem.version).
- **5 calculations**: `contract_unit_price` (dual-variant pin-at-write vs settlement-reprice, nested max/min), `order_total` (per-line rounding pinned, 412 vs 411), `chargeback_settlement` (4-step pinned order, bracket keyed on gross), `par_replenishment_suggestion` (dual-variant STANDARD_TOPOFF vs LUM_SPLIT), `route_cold_chain_load`.
- **24 validations** (strict ascending priority), **51 endpoints** (incl. `POST /_clock/set_current_utc`, default clock `2026-08-01T00:00:00Z`), **49 error codes**, **5 roles** (ContractAdmin, MaterialsManager `entity_backed:SupplyRoom`, Clinician, DistributionOperator, ManufacturerRep) with two two-person rules.

## Design instance counts
- §1.8: **19 instances** across all 9 rule_ids (2 each, 3 for `combinatorial_formula` covering modes a/b/c).
- §1.9: **68 instances** across all 9 guide sections — 53 with full `test_recipe`, 15 `excluded_because` stubs.

## Verification performed
- `scaffold_lint.py` → `VERDICT: clean lint` (770 calls scanned, exit 0).
- Custom checks: 0 unresolvable `grounds`, 0 unbound `${var}` placeholders, 0 duplicate instance names (87 total), every stub's `difficulty_instance` resolves, every one of the 49 error codes is both referenced by a validation/transition and named by a design instance, no forbidden concurrency vocabulary.
- All formula-derived assert literals computed in Python (e.g. 9540/9200 pin-vs-settle divergence, 98024 order total, 412-vs-411 rounding, gross 50000 → fee 0.015/750 → net 49250, LUM 3×24=72 vs 2 cases + 22 eaches, 24108 ledger conservation).

Two scaffold-shaping decisions worth flagging: the controlled/cold-chain safety checks were moved to submit-time only (a DRAFT order is a worksheet) so the safety-vs-fiscal priority conflict is reachable; and contract effective-period overlap is scoped to the same `manufacturer_code`, which makes the unit-price selector's ranking genuinely multi-candidate.

## Step 4: Generate PRD — 2026-08-17T19:16:41.642452014Z

PRD generated at `workspace/PRD.md` — 419 lines, ~11,100 words. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directories were read.

## Section list

- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (fixed block, verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Path Resolution and Referential Integrity · 2.6 Cents, Eaches and Rounding Discipline · 2.7 Stale-Version Protection on Line Writes and Cycle Counts · 2.8 Two-Person Rules · 2.9 The Order in Which a Request Is Rejected · 2.10 Cascades, Ledgers and the Two Order Axes
- §3 Business Logic & Workflows — 3.1 Supply Room + Item Master · 3.2 GPO Contracts, Tier Pricing, Price Activation · 3.3 Formulary Standing, Par Levels, Cycle Counts · 3.4 Writing/Totalling/Submitting an Order · 3.5 Lots, Excursions, FEFO Picking · 3.6 Backorders and Clinician Substitution · 3.7 Routing, Dispatch, Receipt · 3.8 Recall Cascade · 3.9 Chargeback Settlement
- §4 Endpoint Definitions (4 columns, 51 rows) · §5 Error Code Catalogue (2 columns, 49 rows). File ends at §5 — no audit footer.

## Coverage verification (machine-checked against SCAFFOLD.yaml)

```
Field coverage check:
- entities[].fields:            95 required, 95 present, 0 missing
- endpoints[].request_body:     63 required, 63 present, 0 missing
- endpoints[].query_params:     23 required, 23 present, 0 missing
- endpoints[].path_params:      12 required, 12 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority:  24 checked, 24 expressed in prose (§2.9 states the full 1→24 precedence with error_id + applies_to scope; §3.4 restates the submit ordering 10/11/15/21/24), 0 missing
- concurrency_rules[] OCC:       2 checked, 2 expressed (write_endpoint + expected_order_version / expected_formulary_item_version + ERR_STALE_VERSION 412 all named, §2.7), 0 missing
- state_machines[].transitions: 60 checked, 60 fully expressed with explicit `FROM → TO` pairs across 11 machines, 0 missing
- calculations[]:                5 checked, 5 fully expressed (contract_unit_price incl. candidate set + 3-level ranking + pinned eval order + both variants §3.2; order_total per-line rounding §3.4; chargeback_settlement 4 pinned steps + gross-keyed brackets §3.9; par_replenishment_suggestion both variants §3.3; route_cold_chain_load projection gate §3.7), 0 missing
- validations[] conditions:     24 checked, 24 matchable to error_id in §2/§3 narrative, 0 missing
- endpoints[].side_effects:     51 checked, expressed in workflow narrative (incl. 4-hop recall cascade, supersession cascade, ledger deltas), 0 missing
- entities[].fields[] defaults:  all 12 entities checked, defaults/initial values/enums reconstructible, 0 missing
- sibling-branch symmetry:      lot FLAG/RELEASE/DESTROY, clinician REQUEST_INFO/APPROVE/REJECT, requester RESPOND/WITHDRAW, ACCEPT/DISPUTE, RECONCILE/RESUBMIT, STANDARD_TOPOFF/LUM_SPLIT, pin/settle price roles — 7 groups, equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 670
- tokens starting with `/`: 0 · bare HTTP-method tokens: 0 · method+path tokens: 0
Status: PASS
```

Also verified: all 49 error IDs appear in §2/§3 narrative (not only in the §5 table); all 41 state values and all 66 enum values appear verbatim; all 5 role names present with their `identity:` translated (MaterialsManager entity-backed to `SupplyRoom`, the other four opaque); §2.2 matches the canonical block byte-for-byte; no fuzzy/approximating words and no pseudocode operators outside the fixed JSON block.

Orchestrator spot-check: 419 lines, all 5 top-level sections present, 51 endpoint table rows, 49 distinct `ERR_` codes, file ends cleanly at the §5 catalogue — no truncation.

## Step 6: Generate implementation — 2026-08-17T19:44:43.385773082Z

Implementation complete and verified.

## What was built

`workspace/implementation/`

| File | Contents |
|---|---|
| `start.sh` | Guarded `pip install` (only when flask missing) + `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000) |
| `app.py` | App factory, blueprint registration, `ApiError`/`HTTPException` handlers, per-request `g.dirty`/`g.fresh` init |
| `db.py` | In-memory dicts (12 entity kinds), logical clock (starts `2026-08-01T00:00:00Z`), UUID/`_seq` minting, `touch`/`flush` (one `version`+`updated_at` bump per mutated entity per request), ISO-8601 3-fractional-digit formatting |
| `errors.py` | All 49 error IDs → HTTP status |
| `response.py` | `meta`/`response_type`/`data` envelope, `req_`+20-char request id, pagination meta (`limit`/`offset`/`total_count`/`has_more`) |
| `auth.py` | `X-User-ID`/`X-User-Role` auth (401), role matrix (403), MaterialsManager supply-room scope (403) |
| `validation.py` | All enums, typed body/query validators, pagination bounds |
| `services.py` | `contract_unit_price` (selector ranking + pinned adder/floor/ceiling order), `order_total` (per-line fee rounding), `chargeback_settlement` (4 pinned steps), `par_replenishment_suggestion` inputs, `route_cold_chain_load`, FEFO allocation, contract activation cascades, recall 4-hop cascade, ledgers, rebill trigger |
| `routes_catalog.py` / `routes_inventory.py` / `routes_orders.py` / `routes_logistics.py` | The 51 endpoints |

## Counts requested

- **Endpoints: 51/51.** Programmatically diffed against PRD §4 — `missing: []`, `extra: []`.
- **Error codes: 49/49** defined with the PRD §5 statuses, and every one is raised somewhere in logic (grep across all non-`errors.py` sources returned zero unreferenced ids).

## Verification

Server boots clean from a fresh process (empty store, no seeding, no disk state) and answers a listing endpoint with a correct envelope. Five smoke suites (~200 assertions) passed, covering: the global rejection order (auth → role → schema → path 404 → body-ref 404 → scope → stale version → state → uniqueness → business gates), all 12 path 404s, all 8 scope-guarded operations, pricing (tier rounding, LUM 12¢, cold `max(45, 3%)`, floor-before-WAC-ceiling, cheapest-candidate selector, cross-manufacturer overlap allowed, touching closed intervals colliding), supersession with settled≠pinned divergence, per-line fee rounding (2178 not 2177), the PRD's 100/30/24 replenishment example under both variants, FEFO, submit gate ordering (controlled → cold → formulary → qty → credit), route geometry with 15-min turnover, cold capacity (400 / AMBIENT=0), delivery lot re-checks, recall 4-hop cascade (lot→line→order HELD→route CANCELLED, ledger release), substitution round budget, approve/reject/withdraw cascades, chargeback brackets, dispute/resubmit and the rebill cycle, and both two-person rules.

## Judgment calls (spec ambiguities)

- Submit with no `OPEN` line → `ERR_ORDER_NOT_DRAFT` (409), the state code the PRD names for submit.
- Claim creation on a non-`DELIVERED` order → `ERR_ORDER_STATE_INVALID`; the "already claimed" case is left to `ERR_CLAIM_ALREADY_OPEN` (checking `settlement_status` as a state rule first would make that code unreachable).
- Client-supplied datetimes (`effective_from`, `expiry_date`, `to_iso8601`) are echoed verbatim; server-minted stamps use the documented 3-fractional-digit form from the logical clock. `meta.api_request_timestamp` uses wall clock (it is not in PRD §2.4's clock-driven list).
- `to_status` enum is the four values the endpoint declares; invalid enum values on list filters return `ERR_VALIDATION`.

## Step 5: Generate unit tests — 2026-08-17T19:48:57.466309619Z

Test infrastructure and suite are complete.

## What was generated

**`test_helpers/`** (2,262 lines, 9 modules) — `types.py` (12 entity TypedDicts + 25 enums), `api_client.py` (all 51 PRD endpoints), `api_errors.py` (49 error IDs registered with the framework's status map, keyed by plain string), `assertions.py` (per-entity assertions + three domain invariant checkers: lot unit conservation, contract chargeback ledger, room open-commitment), `factories.py`, `constants.py`, `test_users.py`, and `fixtures.py` (801 lines — ~45 primitives plus `setup_priced_catalogue` / `setup_priced_item` / `setup_draft_order` / `setup_glove_order(stage=…)` / `walk_order_to_delivered` / `setup_backordered_line`).

**`test_suite/`** (4,629 lines, 11 files + conftest) — **96 tests**, every one carrying verbatim PRD citations and exactly one `Design:` tag.

## Per-queue results

| Queue | Instances | Translated | Skipped | Tests emitted |
|---|---|---|---|---|
| **A — Difficulty** | 19 | **19** | 0 | 43 (≥2 each) |
| **B — Corner** | 68 (53 non-stub + 15 stubs) | **53** | 0 non-stub | 53 (≥1 each) |

**No instance was skipped.** Every one passed the PRD-first two-condition filter — this PRD verbatim-covers and uniquely-derives all 72 asserted rules. All 15 `excluded_because` stubs were verified (each `difficulty_instance` cross-reference resolves to a real queue-A instance name) and correctly left untranslated.

Two instances required a judgement call rather than a skip:
- `lot_quantity_on_hand_is_computed_and_client_input_ignored` — the design itself asserts a disjunction (400 on undeclared keys **or** server-owned values win); translated as that disjunction, since PRD pins the values but not the extra-key policy.
- `create_item_defaults_applied_when_optional_fields_omitted` — `lum_parent_item_id` is asserted with `.get(...) is None` (passes for null or omitted); the other three defaults are PRD-named explicitly.

## Verification performed

- **Citation audit** (script over all 96 docstrings): every quoted span survives a whitespace-normalised literal match against `PRD.md`; every citation ≥8 words; exactly one `Design:` line per test. **0 failures.**
- **Coverage audit** against both YAMLs: 19/19 difficulty instances ≥2 tests, 53/53 non-stub corner instances ≥1 test, zero tags pointing at stubs or non-existent instances. **0 failures.**
- `pytest --collect-only` → 96 tests collected, all modules import.
- Static scans: no undefined names, no unresolved `test_helpers` imports, no unused imports, **zero** `skip`/`skipif`/`xfail`, zero occurrences of "scaffold"/table/§1.x references in generated code.
- Call-signature check: every `api.*` call and every helper call binds against its real signature. **0 problems.**

## Notes worth flagging

- All arithmetic literals were re-derived independently and match the design indices (9540 vs 9200 pin/settle divergence, 98024 order total, 412≠411 per-line rounding, 4652/500 nested max-then-min, 4600 WAC cap, gross 50000→750→49250 and 250000→2500→247500, net 24108 ledger, 72 vs 70 replenishment eaches, 59595 cold-load total).
- Identity threading is enforced throughout: every supply-room scope-gated call uses `make_materials_manager_headers(room["id"])`; the shared `materials_manager_headers` constant is reserved for non-ownership paths only. The two two-person rules use distinct per-instance operator/admin IDs.
- One fixture-design constraint worth remembering for the implementation phase: contract price lines must be written **before** activation (a line added to an ACTIVE contract stays `PENDING` and prices nothing), so `setup_priced_catalogue` builds all lines first and activates once.

## Step 7: Run tests and iterate — 2026-08-17T20:21:23.515321612Z

All 8 rounds passed in two consecutive sweeps. Work is complete.

## Result

**3 iterations** (24 sweep rounds, 2,304 test executions). Final state: **96/96 in all 8 parallel rounds, twice consecutively.**

### Iteration 1 — one failure surfaced
Round 2 only: `test_07_routing_and_delivery.py::TestStopTurnoverBuffer::test_arrival_one_minute_inside_the_turnover_collides` failed with `requests.exceptions.ConnectionError: RemoteDisconnected('Remote end closed connection without response')` on `POST /orders/{id}/lines` during setup. The other 7 rounds were clean — exactly the flakiness the sweep is designed to catch.

Diagnostic protocol outcome:
- **STEP 1a/1b — test stays.** PRD §3.7 states the rule verbatim ("Two stops at the same supply room on the same service date... collide when the new stop's arrival minute is earlier than the existing stop's arrival minute plus the existing stop's service duration plus 15... `ERR_ROOM_WINDOW_CONFLICT` (HTTP 409)"), and 480/524/525 with a 30-minute service uniquely determines the outcome.
- **STEP 2 — test and fixtures faithful.** Setup, role headers (`MaterialsManager` acting as the supply room id), payload shape and assertion all match PRD.
- **STEP 3 — implementation.** Evidence from the round's own server log (`/tmp/prd_bench_server_33531.log`): the failing test's server served 16 requests, then the 17th **never reached the WSGI layer** — no access-log line, no traceback — and the socket was closed with no response. A transport-layer defect, not application logic.

### Fixes applied to `workspace/implementation/`

**`app.py` — added `_SerialisedWsgi` + `_REQUEST_LOCK` (wraps `app.wsgi_app` in `create_app`).**
A separate, *reproducible* concurrency bug: with `threaded=True`, one worker iterating a store dict (uniqueness scans, ledger recomputation) while another inserted raised `RuntimeError: dictionary changed size during iteration`, which the catch-all handler turned into a spurious `400 ERR_VALIDATION` on a perfectly valid write. Reproduced at **6 failures / 4,800 concurrent room creations** under CPU contention; **0 / 4,800** after the fix. The lock makes a request the unit of atomicity, matching PRD §2.10 ("Nothing in this system settles later").

**`app.py` — serve via `waitress` (guarded fallback to the Flask dev server).**
Werkzeug's dev server unconditionally sends `Connection: close` and closes after every response, so each API call opened a fresh TCP connection — ~19,200 connection establishments per sweep, with 6,600+ `TIME_WAIT` sockets observed on a host also running other pipelines. Since the failure occurred at connection-establishment (request never reached WSGI), cutting that surface is the direct mitigation. Verified: **40 requests now travel over 1 TCP connection** (~25x fewer establishments).

**`requirements.txt`** — added `waitress==3.0.2`. **`start.sh`** — dependency guard now checks `flask, waitress`.

### Tests deleted: **none**
Every assertion traced to a verbatim PRD sentence and was uniquely derivable.

### Fixes to `test_helpers/`: **none**
All 21 test files (11 suites + conftest, 9 helper modules) are unmodified. No assertion was weakened; no skip/xfail added.

### Verification notes
- Storage remains in-memory only — confirmed empty at boot, no file/SQLite/JSON persistence anywhere in `implementation/`.
- No endpoints, response fields, side effects, or headers were added; the changes are internal concurrency control and the WSGI server choice.
- Reproduction harnesses live in the scratchpad only; no stray servers or load processes left running.

One caveat worth passing on: the original `RemoteDisconnected` was ~1 failure per 768 test executions and could not be reproduced in an isolated 2,000-cycle kill/restart harness — it needed the real sweep's host contention (60+ concurrent server logs were being written during it). The fix is therefore justified by mechanism and by two clean sweeps rather than by a before/after reproduction of that specific symptom.

Orchestrator verification: all 8 `results.{1..8}.json` confirm `passed=96 total=96`.

## Step 8: Finalize PRD — 2026-08-17T20:24:27.84263207Z

`workspace/PRD_FINALIZED.md` is written. Near-zero-edit outcome: exactly one sentence-group added, in §2.10.

## Size
- PRD.md: 419 lines / 78,801 bytes. PRD_FINALIZED.md: 419 lines / 79,258 bytes.
- Line delta: 0 lines (0.0%); byte delta +457 (+0.58%). One line (157) revised, no lines added or removed, no new sections.

## Changes
- §2.10 (Cascades, Ledgers and the Two Order Axes) — revise — appended to the "Nothing in this system settles later" paragraph: the request is also the unit of atomicity across clients; the server handles one request at a time (reads included), requests never interleave, no request touches the store while another is in flight, and a request that would succeed alone is never rejected merely for being concurrent; `ERR_STALE_VERSION` is the only concurrency-keyed rejection — `implementation/app.py:22` (`_REQUEST_LOCK = threading.RLock()`), `app.py:25-40` (`_SerialisedWsgi.__call__`), `app.py:79` (`app.wsgi_app = _SerialisedWsgi(app.wsgi_app)`).

## Pre-edit search log

Edit 1 — §2.10 serialisation sentence
- (a) Subject: request-level concurrency/isolation semantics — whether two requests may interleave, and whether concurrency can itself cause a rejection.
- (b) Impl paths enumerated (read/grepped): `app.py:14-40` (`_REQUEST_LOCK`, `_SerialisedWsgi`, body materialised inside the lock), `app.py:41-81` (`create_app`: all four blueprints registered, all three error handlers, `wsgi_app` wrapped last so error paths are inside the lock too), `app.py:85-100` (waitress `threads=8` and the Flask `threaded=True` fallback — both multi-worker, both serialised by the wrapper); `db.py` module-level singleton `store` shared across requests plus per-request `g.dirty` / `g.fresh` initialised in `app.before_request`; `db.py:flush()` and its only callers `response.ok/ok_empty/ok_list` (version bumps land on success responses only); the two `ERR_STALE_VERSION` sites (order-line write, `adjust-on-hand`); `grep -rniE "thread|lock|atomic|rollback|concurren"` across `implementation/` confirmed no background workers, timers, queues, or async paths anywhere; `test_suite/`+`test_helpers/` grep confirmed no test asserts concurrency behaviour (so tests neither support nor contradict the wording).
- (c) Wording adjustments made: (1) dropped any all-or-nothing / rollback phrasing — `flush()` runs only on success and the store has no undo, so a request that raises mid-way can leave earlier field writes in place (e.g. multi-hop cascades); the sentence now claims only mutual exclusion, never transactional rollback. (2) Replaced "a reader never sees a cascade half-applied" with "no request reads or writes the store while another is still in flight" — the former would be false for the terminal state of a failed request; the latter is exactly what the lock guarantees. (3) Added "reads included" because the wrapper serialises GETs as well, so the claim must not read as write-only. (4) Said "handles one request at a time" rather than "is single-threaded", since both servers use worker pools. (5) No ordering/fairness claim (an `RLock` gives no FIFO guarantee). (6) The `ERR_STALE_VERSION` clause was chosen to echo §2.7's existing "none may be rejected for a version reason" rather than to add a new rule.

## Items deliberately not edited
- **waitress + guarded Flask-dev-server fallback (`app.py:85-100`, `requirements.txt`, `start.sh`)** — no PRD-observable behavioural commitment. It changes only TCP connection reuse and the accept loop; no endpoint, status code, envelope field, or header contract moves. Pinning "connections are kept alive" would additionally be a *false* claim on the impl's own fallback branch (the dev server sends `Connection: close`), i.e. a brand-new mismatch.
- **`start.sh` dependency guard and `requirements.txt` pin** — build/boot mechanics governed by `INSTRUCTION.md`, not API behaviour. No edit.
- No test deletions and no `test_suite/`/`test_helpers/` fixes occurred in Step 7, so there were no further ambiguity signals to trace.

## Step 9: Complete PRD — 2026-08-17T20:35:08.798189287Z

Done. `PRD_COMPLETED.md` is written.

**Files** — `workspace/PRD_FINALIZED.md`: 419 lines / 79,258 chars → `workspace/PRD_COMPLETED.md`: 419 lines / 85,727 chars (**+6,469 chars**, +0 lines). No new sections, no new paragraphs; every change is an in-paragraph insert or revision. Headings (27) and both tables (endpoint catalogue, error catalogue — 104 rows) are byte-identical.

**Counts** — 36 changes: **29 ambiguity-pins**, **7 mismatch-revisions**.

### Changes

- §2.1 — revise — ambiguity — an `X-User-ID` that is empty/whitespace counts as absent → `ERR_UNAUTHENTICATED` — `auth.py:27-30`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + 20 chars from upper-case letters and digits — `response.py:13-14`
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the host wall clock, not the logical clock — `response.py:20`
- §2.2 — insert — ambiguity — undeclared path / undeclared method answer in the same envelope with `ERR_VALIDATION` under 404 / 405 — `app.py:66-73`
- §2.3 — revise — ambiguity — a non-integer `limit`/`offset` is also `ERR_VALIDATION` — `validation.py:200-213`
- §2.3 — insert — ambiguity — enum filters are schema-checked (out-of-set ⇒ `ERR_VALIDATION`, not an empty page); id filters match literally; undeclared query params ignored — `validation.py:217-231`
- §2.3 — insert — ambiguity — `created_at` ties (common, because the clock stands still) break by creation order everywhere the doc orders by `created_at` — `db.py:130-135`
- §2.4 — revise — **mismatch** — `version` advances once *per request*, not per field write; a no-op recompute is not a mutation; all resources mutated by one request share one `updated_at` — `db.py:95-121`
- §2.4 — insert — ambiguity — a resource created by the request stays at `version` 1 with `created_at == updated_at` — `db.py:87-110`
- §2.4 — revise — ambiguity — clock response `data` is the single field `current_utc`, echoed back verbatim (not re-formatted) — `routes_logistics.py:492`
- §2.9 r3 — revise — ambiguity — required-string rules (non-blank except item `description` / recall `reason`), integer rules (no bool/string coercion), JSON `null` counts as absent, `credit_limit_cents ≥ 0`, `delta_qty` any integer — `validation.py:70-128`
- §2.9 r3 — insert — ambiguity — absent/empty body reads as `{}`; unparseable JSON or non-object body is `ERR_VALIDATION` — `validation.py:55-67`
- §3.1 — insert — ambiguity — `room_type` is descriptive only and gates nothing — `routes_catalog.py:62,88`
- §3.1 — revise — ambiguity — `credit_limit_cents` must not be negative — `routes_catalog.py:76-77`
- §3.1 — revise — ambiguity — `is_lot_tracked=false` changes nothing (FEFO always draws from a lot); `DISCONTINUED` bars no operation — `routes_catalog.py:126-147`
- §3.2 — insert — ambiguity — a price line may be added to a header in any status and is still born `PENDING` — `routes_catalog.py:331-359`
- §3.2 — insert — **mismatch** — `to_status` set is exactly the four targets; anything else is `ERR_VALIDATION`, not `ERR_CONTRACT_TRANSITION_INVALID` — `validation.py:23`, `routes_catalog.py:263`
- §3.2 — revise — **mismatch** — activation moves every line *not already `ACTIVE`* (not only `PENDING`) — `services.py:351-355`
- §3.2 — revise — **mismatch** — supersession fires only when the named contract is itself `ACTIVE`; otherwise silently skipped and activation still succeeds — `routes_catalog.py:297-303`
- §3.2 — revise — **mismatch** — `SUSPENDED → ACTIVE` moves `BLOCKED` *and* `PENDING` lines to `ACTIVE` and carries the same supersession side effect — `routes_catalog.py:285-304`
- §3.3 — revise — ambiguity — `variant` is a mandatory query param checked ahead of path existence; projection `data` carries exactly the six fields and no identity/timestamp/version — `routes_inventory.py:169,186-213`
- §3.4 — insert — ambiguity — the same item may be written onto one order any number of times — `routes_orders.py:129-178`
- §3.4 — insert — ambiguity — submitting with no `OPEN` line is refused under `ERR_ORDER_NOT_DRAFT` — `routes_orders.py:196-199`
- §3.5 — revise — ambiguity — `expiry_date` is an ISO 8601 instant; bare `YYYY-MM-DD` accepted as midnight UTC — `routes_inventory.py:226`, `validation.py:171-177`
- §3.5 — insert — ambiguity — the excursion `note` is schema-checked but persisted nowhere — `routes_inventory.py:276`
- §3.5 — revise — ambiguity — `SUBSTITUTED → BACKORDERED` when a substituted line finds no lot — `services.py:247-250`
- §3.6 — revise — ambiguity — the clinician `note` is retained only on `REQUEST_INFO`; discarded on approve/reject — `routes_orders.py:451,468`
- §3.6 — revise — **mismatch** — `response_note` is optional (null when omitted) — `routes_orders.py:541,555`
- §3.6 — insert — ambiguity — rejection against a non-`BACKORDERED` line still succeeds, leaving the line untouched — `routes_orders.py:480-484`
- §3.7 — insert — ambiguity — an already-stopped order may be re-stopped: excluded from the separation scan and from the route's own current cold load; only the path route's counters recompute — `routes_logistics.py:224,253,264`
- §3.8 — insert — ambiguity — `recall_class` is inert; all three classes cascade identically — `routes_logistics.py:61,73`
- §3.8 — revise — ambiguity — `lot_id` is checked for existence only, never for holding the recalled item (a foreign lot narrows the notice to nothing) — `routes_logistics.py:67`, `services.py:411-418`
- §3.9 — revise — **mismatch** — claim creation checks `fulfillment_status DELIVERED` (`ERR_ORDER_STATE_INVALID`); `settlement_status` is policed via the at-most-one-open-claim rule, not read directly; contract `manufacturer_code` is not cross-checked — `routes_logistics.py:314-321`
- §3.9 — revise — ambiguity — `dispute_reason` is optional and left null when omitted — `routes_logistics.py:384,404`
- §3.9 — insert — ambiguity — `RESUBMIT` leaves any recorded `dispute_reason` standing — `routes_logistics.py:453-461`
- §3.9 — revise — ambiguity — the rebill trigger moves the earliest-created claim still `SUBMITTED`; with none, only the order's settlement axis moves and no ledger is touched — `services.py:191-204`

### Modules walked (all complete)

`app.py`, `db.py`, `errors.py`, `response.py`, `auth.py`, `validation.py`, `services.py`, `routes_catalog.py`, `routes_inventory.py`, `routes_orders.py`, `routes_logistics.py` (plus `start.sh` / `requirements.txt`, no PRD-visible behavior). All 51 routes, 12 entity field-sets, 49 error codes, the 11 state machines, all 5 calculations, both optimistic-concurrency rules, both two-person rules and the 24-step precedence chain were cross-checked against PRD prose. Verified unchanged/already-pinned: rounding placement, tier/LUM/cold adders, floor-then-WAC order, price-selector ranking and tie-breaks, FEFO selection, the four cascade hops, the four settlement steps and bracket edges, both ledgers, all inclusive/exclusive comparison boundaries (credit, cold capacity, controlled ceiling, rounds budget, reorder point), and every list filter set.
