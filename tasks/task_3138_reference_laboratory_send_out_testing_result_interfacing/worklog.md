# Worklog — task_3138_reference_laboratory_send_out_testing_result_interfacing

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3138_reference_laboratory_send_out_testing_result_interfacing/` was pre-allocated by the caller and already contained `workspace/`. Verified existence; no new task_* directory created and no index computed (per caller instruction to use exactly this path).

## Step 2: Generate the three scaffold artifacts — 2026-09-30T04:17:00.000Z

Applied `prd-bench-scaffold-generator` to the scenario verbatim, with the caller's
"much harder than expert level" directive read as a demand for density over volume:

- Archetype: `workflow_orchestration` + `temporal_windowing`, entity topology `flat`,
  state-machine shape `parallel`, role model `peer_roles`, consistency model `saga`.
- Difficulty layers: cascading side effects, dual-variant calculation, optimistic
  concurrency, rate/threshold triggers, derived-field reconciliation (5 layers).

Artifacts written:

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 2597 | §1.0-§1.7 + preamble |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1626 | §1.8, 9 rules / 19 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1981 | §1.9, 9 sections / 40 instances |

Surface counts: 11 entities, 12 state-machine blocks, 3 concurrency rules,
11 calculations, 29 validations, 78 endpoints, 48 errors, 10 roles.

Self-consistency audits run before finalising: enum value closure over every
closed enum in §1.1; grounds resolvability across both design files (0 dangling
refs); every declared error id referenced by at least one validation or
transition; no §1.2.1 OCC violation (3 true races, all CREATE-with-supersede on
a `common_fields: true` parent); formula-derived assertion literals recomputed in
Python against each calculation's pinned constants and rounding order.

`scaffold_lint.py .` verdict: **clean lint** (1015 calls scanned across both
design files, 0 violations; all §1.1 FKs reverse-reachable in §1.5).

## Step 3: Copy shared INSTRUCTION.md — 2026-09-30T04:18:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` (1424 bytes) to `workspace/INSTRUCTION.md`.
## Step 4: Generate PRD.md — 2026-09-30T04:34:00.000Z

PRD generated and verified. Summary below.

## Output

**Path:** `/home/ubuntu/github/CodingPRD/tasks/task_3138_reference_laboratory_send_out_testing_result_interfacing/workspace/PRD.md`
**Lines:** 416

## Section list

- **§1 Introduction** — 3 paragraphs (business asymmetry, commercial dimension, audience + logical clock)
- **§2 Global Specifications** — 11 domain-derived subsections: 2.1 RBAC (all 10 roles, both identity forms), 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties & Logical Clock, 2.5 Specimen Integrity (Stability, Volume, Transport), 2.6 Precision & Monetary Representation, 2.7 Optimistic Concurrency Control, 2.8 Catalogue Currency / Interface Certification / Message Retry, 2.9 Client Posture, Credit Routing & Ledger Conservation, 2.10 Occupation of Scheduled Resources, 2.11 Nested Retrieval, Not-Found Resolution & Validation Precedence
- **§3 Business Logic & Workflows** — 12 subsections, grouped by lifecycle + cross-cutting concerns: 3.1 Client Onboarding/Posture/Commercial, 3.2 Courier Logistics & Specimen Intake, 3.3 Accessioning/Rejection/Aliquot Derivation, 3.4 Catalogue Stewardship & Withdrawal Cascade, 3.5 Order Submission/Utilisation Advising/Add-On, 3.6 Analyzer Booking & Start of Testing, 3.7 Result Entry/Critical Values/Release, 3.8 Reflex Chaining/Manual Reflex/Repeat, 3.9 Utilisation Advising Lifecycle, 3.10 Pricing/Turnaround Credit/Ledger Settlement, 3.11 Order Holds/Cancellation/Terminal Closure, 3.12 Interface Builds & Outbound Message Delivery
- **§4 Endpoint Definitions** — 78-row, 4-column table
- **§5 Error Code Catalogue** — 47-row, 2-column table

## How information was scattered

- **Architecture-level rules (§2, precise zone):** OCC (`expected_client_laboratory_version`, `expected_send_out_order_version` × 2 write endpoints, `ERR_STALE_VERSION` 412); pagination defaults (10/1/100/0); precision (2dp round-half-up, 4dp round-half-down for stability); sort order; the logical clock (`2026-09-01T00:00:00Z`); occupancy intervals (inclusive pickup → exclusive delivery; closed reserved window + decontamination buffer); catalogue-currency strict `<` comparison; retry backoff (base 5 doubled per failure, 60-min cap, first failure → 10 min, counter resets only on transmit).
- **Rules deliberately displaced into §3 narrative:** all 70 transitions distributed across the workflow that owns them; the rush-tier / effective-TAT circular dependency (3.6, with the three worked anchor values); volume-tier price (≤2 → 1.00, 3–5 → 0.85, ≥6 → 0.72, floor applied after discount) and the provisional-vs-final reconciliation in 3.10; per-line-then-sum turnaround credit (0.015/hour) in 3.10; ledger conservation pair and aliquot conservation pair in 3.10; the five-hop withdrawal cascade in 3.4; critical-value flag derivation and segregation-of-duties release guard in 3.7.
- **Scattered parameters:** add-on/reflex params split between 3.5 (core `test_catalog_entry_id`, `line_sequence`, `add_on_at`) and 3.8 (rules); OCC fields split between §2.7 (mechanism) and §3.2/3.7/3.12 (business situation); list filter params placed in §3.1 to keep §3 free of "field list" dumping.
- **Error trigger conditions:** live only in §2/§3 next to the workflow each guards; §5 carries IDs and statuses only. All 48 error IDs verified to have prose conditions.

## Scaffold ambiguities adjudicated

1. **Waypoint state aliases.** `R_*` / `A_*` / `S_*` prefixed state names are the scaffold's lint-walker declaration aliases (the file's own comment says so); the user-visible values are the plain ones in `entities[].fields[].constraints`. PRD uses `RECEIVED`, `ACCESSIONED`, `SUBMITTED`, etc. Verified against the example pair, where prefixed names also never reach the PRD.
2. **Validation priority numbers.** Scaffold prose references "validation priority N". Per the no-pseudocode rule, §2.11 expresses the ordering in natural language (header → permission → scope → existence → OCC guard → state → domain rules) rather than reproducing numeric codes.
3. **`POST /courier-manifests`** appears in `validations[].applies_to` and the RBAC matrix but no such endpoint exists in §1.5; mapped to the courier-leg booking operation (`POST /courier-runs`).
4. **`onboarding_status` = `COURIER_CONFIGURED`** is declared as an enum member but no endpoint or transition ever sets it. PRD states the ladder and the documented advance path (`REQUIREMENTS_PUBLISHED` → `COMPLETE` when a note and a leg both exist).
5. **`stability_deadline_at`** description claims it is "recomputed exactly once after rush_tier settles", but no transition does so. PRD states only its derived value (receipt + min remaining stability across live lines).
6. **`POST /specimens` under priority 22** would apply `ERR_INVALID_TEMPORAL_WINDOW` to `client_requested_at`, which a specimen does not carry; PRD binds that field's instant check to order submission and states `collection_at` ≤ `received_at` for specimens.
7. **`transit_allowance_minutes` per-leg increment** is named but never valued; PRD describes the chronological accumulation without inventing a figure.
8. **Nearest-entity not-found mapping** for body FKs (e.g. ISE on a specimen-style endpoint) stated in §2.11 generically, since the scaffold names only the per-entity catalogue, not a per-endpoint mapping.

## Hard Contracts reports

```
Field coverage check:
- entities[].fields: 125 required, 125 present, 0 missing
- endpoints[].request_body: 75 required, 75 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
- endpoints[].path_params: 0 declared in scaffold (ids inline in paths), 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 70 checked, 70 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed (formula, constants, precision, algorithm, both variants), 0 missing
- validations[] conditions: 29 checked, 29 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 78 endpoints checked, all side effects expressed; applies_to sets enumerated, 0 missing
- entities[].fields[] structured content: 146 field entries checked, 146 reconstructible from prose, 0 missing
- sibling-branch symmetry: 14 sibling transition groups checked (ClientLaboratory 7, CourierRun 5, TestCatalogEntry 6, Specimen 8, SendOutOrder 14, OrderTestLine 7, InstrumentRun 4, InterfaceBuild 5, ResultInterfaceMessage 7, UtilizationAdvisory 5, plus action/field sibling groups), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 268
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three contracts PASS. §2.2 is byte-identical to `section-2.2-response-structure.md` (verified by substring match, including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING` and `"data": { }`). No audit footer in PRD.md; all three reports live in this message only. All 78 scaffold endpoints appear in the §4 table and no extras. Other checks: entity fields 146/146 present, endpoint params 92/92 present, errors 48/48 present, roles 10/10 present, all 10 non-alias state values present, no fuzzy/approximating wording in rule transcription.

## Step 5: Generate unit tests — 2026-09-30T05:05:00.000Z

Stage 1 and Stage 2 are complete. Final verification passed: 76 test functions, 76 design tags (one per test), zero invalid or missing tags, zero non-verbatim PRD citations, no skip/xfail, and no scaffold vocabulary leaking into generated code.

## Files written

**`test_helpers/` (1,967 lines)**

| File | Lines | Contents |
|---|---|---|
| `constants.py` | 62 | Tier rates, TAT factors, surcharge rates, late-credit rate, retry backoff, utilisation band, window days |
| `types.py` | 382 | Status enums for all 11 entities + `UserRole` + full `TypedDict`s |
| `api_errors.py` | 116 | 48 error ids, HTTP status map, `set_error_http_status_map()` registration |
| `api_client.py` | 271 | 84 endpoint methods covering the whole §4 surface |
| `assertions.py` | 183 | Per-entity structural assertions + client and ledger invariant checkers |
| `factories.py` | 247 | One payload factory per entity, plus `order_line`/`result_line`/`add_on_payload` |
| `test_users.py` | 50 | 10 role header constants + `make_*_headers(user_id)` builders |
| `fixtures.py` | 631 | Tier 1 primitives → Tier 5 terminal states, incl. `setup_active_client` (the reused 8-call onboarding chain), `setup_released_order`, `setup_two_and_three_line_orders`, `setup_escalated_advisory` |
| `__init__.py` | 25 | Barrel export |

**`test_suite/` (3,858 lines, 76 tests)**

`conftest.py` (64) + eight numbered files: `test_01_catalog_and_requisition_contracts` (14), `test_02_state_machine_cycles` (10), `test_03_pricing_and_turnaround` (8), `test_04_specimen_acceptability` (8), `test_05_cascades_and_ledger` (11), `test_06_hold_and_utilization` (8), `test_07_withdrawal_and_validation_order` (11), `test_08_occ_and_slot_occupation` (6).

## Per-instance coverage

**Queue A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: 16 of 19 instances covered** (all at ≥2 tests).

Skipped (no test emitted):
1. `combinatorial_formula/volume_tier_rate_selection_with_floor_applied_last` — the six-line variant totals it asserts (provisional 543600.00, final 416484.00, variance −127116.00) require a 336-hour GENETIC panel; no PRD sentence uniquely derives those figures, and the six-line rate itself is only derivable by extending the "three through five" cell with no PRD text covering it.
2. `priority_pair_validation_conflict/client_not_active_outranks_catalog_publication_currency` — PRD §2.11 puts "catalogue and interface integrity" ahead of "client state and temporality", so the PRD uniquely derives the **opposite** error precedence from the one asserted.
3. `priority_pair_validation_conflict/expired_specimen_stability_outranks_duplicate_add_on_line` — PRD §3.5 states only that the two bounds "apply to them differently" and never orders the add-on rules against each other, so no single priority is derivable.

**Queue B — `SCAFFOLD_CORNER_DESIGN.yaml`: 40 of 40 non-stub instances covered** (all at ≥1 test). The file contains zero `excluded_because:` stubs with a `test_recipe`; its only `excluded_because` occurrence is in the header comment, so no cross-reference resolution was needed.

## conftest / helper design notes

- **Identity threading**: `make_lab_client_admin_headers(client["id"])` is used at every ownership-gated call (publish-requirements, order submit/cancel, advisory acknowledge/dismiss); the shared constant is reserved for catalog-entry create/publish, which takes no client in path or body. `make_pathologist_headers(...)` / `make_medical_technologist_headers(...)` exist specifically for the segregation-of-duties comparison.
- **Empty-DB discipline**: every fixture builds from scratch; `set_clock()` is called at the head of `setup_active_client`, so each test pins the logical clock itself.
- **Setup error surfacing**: `fixtures.py` uses `get_success_data()` internally and wraps failures with a `pytest.fail("Setup failed at <label>: HTTP …")` carrying the returned `error_id`.
- **One deviation from the skill template**: the shared role-header dict is keyed `<role>_headers` (e.g. `"pathologist_headers"`), not the template's `"role_a_headers"` shape — conftest exposes all ten as same-named fixtures.
- **`order_line` factory** is named that way rather than `test_line` because pytest collects module-level `test_*` callables as tests; the original name inflated the collected count from 76 to 82.
- **Tests were not executed** against a live server — the implementation directory is owned by a concurrent step, so no server was available at `API_BASE_URL`. Validation was collection + static (pyflakes clean, verbatim-citation grep against PRD.md, tag-to-instance resolution against both yamls).

## Step 6: Generate implementation — 2026-09-30T05:51:00.000Z

Done. The implementation is complete and verified.

## What was built

`workspace/implementation/` — Python 3 + Flask, in-memory only.

| File | Lines | Role |
|---|---|---|
| `start.sh` | 9 | Guarded-dep launcher, `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `Flask>=3.0` |
| `app.py` | 23 | Flask entry point |
| `dispatcher.py` | 115 | Auth → permission → scope → route; envelope; error handlers |
| `response.py` | 43 | Envelope helpers (`meta`/`response_type`/`data`) |
| `middleware.py` | 138 | Header extraction, RBAC, client scope, pagination |
| `errors.py` | 117 | 51-id catalogue + HTTP map + `ApiError` |
| `db.py` | 184 | Dict store, logical clock, UUID/ISO helpers |
| `rules.py` | 586 | Calculations, derived-field reconciliation |
| `serializers.py` | 341 | 11 row→wire serialisers |
| `engine.py` | 648 | Client/courier/catalogue state machines, clock events, guards |
| `workflows.py` | 1720 | Specimen/order/analyzer/interface/ledger/advisory workflows |
| `workflow_one.py` | 10 | Namespace re-export |
| `routes.py` | 1054 | 78 handlers + endpoint table |

**Endpoints: 78 implemented vs 78 rows in the PRD §4 table** (53 POST, 22 GET, 2 PATCH, 1 DELETE). All 11 collections start empty; nothing is seeded — verified by a boot assertion and an audit for `seed`/file IO/persistence.

## PRD ambiguities I adjudicated

1. **Settlement vs. balance (PRD §3.1 vs §2.9/§1.3).** §3.1 says settlement raises the ledger's `voided_cents` and flips the client to ACTIVE, but §2.9 defines the balance purely as the sum of routed BILLED orders — so settlement could never lower it and the revert leg would be unreachable. I net the settlement credit against the routed balance for CLIENT-routed accounts; ledger `net_billed_cents` and the outstanding-balance conservation identity are untouched (verified: void/re-charge returns the net to 0).
2. **CLIA duplicate status.** §3.1 says `ERR_INVALID_REQUEST` "at HTTP 409"; §5 only lists a status per error id. Pinned 409 explicitly. Same for the `line_sequence` collision in §3.5.
3. **`transit_allowance_minutes` increment.** No base or per-leg constant exists anywhere, so the default is 0 and the increment is opt-in via `base_transit_minutes`/`per_leg_increment_minutes`; the chronological count over earlier same-route legs is what's implemented.
4. **Courier DISPATCHED→IN_TRANSIT vs. recall.** The auto-transition fires on every request, which would make the `DISPATCHED→PLANNED` recall leg unreachable for any leg dispatched after its departure instant. Resolved per §2.4/§3.2: a leg dispatched once departure had already arrived is held until the clock next moves, so recall stays reachable while the vehicle hasn't physically left.
5. **Analyzer section matching.** No catalog field carries a section, so `begin-testing` matches by section when a live run matches, and otherwise requires exactly one live run — matching the precondition's literal "exactly one RUNNING run covering the clock".
6. **Multi-order specimens.** A specimen can carry several orders (reflex spawns one), so specimen-level accession/begin-testing/reject bubbles reach *all* of them, and hop 4 of the withdrawal cascade voids any order cancelled at hop 2 that carries a charged, now-cancelled line (§3.4 says "a cancelled line", not "the withdrawn test's line").
7. **`order.charge` cost basis.** §3.10 says the final variant runs "at charge or release"; at charge no `billed_cents` exists yet, so lines are priced first. I additionally reject a charge that would take a CLIENT-routed balance strictly above the limit, per the §9.24 wording.

## Bugs found and fixed during verification

`ERR_STALE_VERSION` missing from an import; non-idempotent `db.iso`; `db.clock` used as a module attribute; missing `begin-testing` in the Specimen transition table; query params not reaching list handlers; aliquot overdraw persisted the offending tube (breaking the create/delete conservation claim); RESULT messages didn't bump the order version; a specimen's reference parser gaining a `_ensure_ref` guard for `bind_named_reference`.

## Smoke testing

Eight scripted passes (≈250 assertions) run against a server I launched on **port 38265**, chosen by binding an ephemeral port (`socket.bind(("", 0))`) so it could not collide with other pipelines. I killed only PIDs I started (the wrapper and its `python3` child, tracked via `$!` and `ss` on my own port) — never `pkill`/`killall`. Each pass ran against a **fresh boot** to prove per-test restart safety; boot-to-ready measured 0.64 s, repeated 3×, and all passes were re-run with zero server tracebacks. Coverage: the full specimen→order→testing→release→reflex→interface→billing journey; all five cascade hops; pricing arithmetic pinned exactly (18.56+18.56=37.12 not 37.11; 1051.45/890.64 tier boundaries; 1.15/1.40 surcharges; floor-then-ceiling clamp); the retry ladder 10/20/40/60/60; OCC on all three guarded writes; ledger and aliquot conservation pairs; all 16 list filters; and an error-catalog sweep over 12 error ids with status codes, envelope shape, and request-id prefix/timestamp precision. Scripts live in `/tmp/t3138_smoke*.py` (scratch, not deliverables).

I did not read `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, anything under `test_suite/` or `test_helpers/`, or any sibling task.

## Step 7: Run tests and iterate — 2026-09-30T07:30:00.000Z

All 8 rounds pass 76/76. Final state verified: 76 tests still collected (none deleted).

## Summary

**Iterations run:** 3 single-round diagnostics plus targeted per-test runs, then the required 8-round parallel sweep. Initial state: 20/76 passing (56 failures, all deterministic across all 8 rounds — no flakiness). Final state: **8/8 rounds at 76/76, zero failures**. No tests deleted, no skips/xfails added, no assertions weakened.

**Root cause of the bulk of failures:** a single fixture bug. `setup_specimen_and_order` issued *both* `POST /specimens/{id}/accession` and `POST /send-out-orders/{id}/accession`. PRD §3.3 states the specimen-level act bubbles upward — "the owning send-out order, if still in SUBMITTED status, moves to ACCESSIONED in the same transaction" — so the second call always hit an order that had already left SUBMITTED and was refused `ERR_INVALID_STATE`. That one over-call produced 20 of the 56 failures.

**Fixes to `test_helpers/`**
- `fixtures.py::setup_specimen_and_order` — removed the redundant order accession (PRD 4's order endpoint is now used only when a requisition is submitted against an already-accessioned specimen, the one case where §3.3's bubble has nothing to move); accession now precedes order creation, matching PRD 3.2's collection → receipt → request ordering; the fixture's analyzer window now brackets the clock so it is RUNNING per PRD 3.6.
- `fixtures.py::setup_active_client` — default clock raised to `2026-09-01T07:00:00Z`, past the chain's 06:30 receipt / 06:35 request instants (PRD 3.2/3.5 temporal bound).
- `fixtures.py::activate_client` — now sends the client-scoped `LabClientAdmin` identity; PRD 2.1 makes that role entity-backed, so the shared constant was invalid.
- `fixtures.py` — `setup_released_order` opens the client ledger *before* the release (nothing in PRD 3.10 opens a ledger at release); removed the now-duplicate openers in `setup_released_order_with_ledger` / `setup_charged_order`; `setup_two_and_three_line_orders` uses a 06:00 receipt so the six-hour ROUTINE assay pins `expected_result_at` at 09:00.
- `fixtures.py` — added `resend_advisory_via_repeat_order`; `setup_escalated_advisory` now drives PRD 3.9's ACKNOWLEDGED → SENT send-back cycle, the only PRD path to the `send_count` of two escalation requires.

**Fixes to `implementation/`**
- `workflows.py` — removed the non-PRD add-on order-status gate (PRD 3.5 places no status precondition on an add-on); reordered the add-on's specimen-anchored bounds ahead of state checks per PRD 2.11's documented priority; `engine_order_accession` now admits `ACTIVE` **and** `CREDIT_HOLD` (PRD 2.9); `_cancel_order` no longer cancels lines that already reached `FINAL` (PRD 3.4's "not already cancelled" pinned against PRD 3.10's cancelled-line exclusion); register-results now requires every line of every order against the specimen (PRD 3.7's specimen-level transition); advisory acknowledge records OPEN → SENT then ACKNOWLEDGED (PRD 3.9's two distinct delivery paths).
- `routes.py` — catalogue creation validates `transport_temperature`, `test_category` and `reflex_condition` against their declared sets (PRD 3.4/2.11); `_page` fills the pagination block on an empty window; interface-build creation recomputes the client's `interface_status` (PRD 3.1/3.12); courier-overlap excludes legs whose delivery instant the clock has passed (PRD 2.4/2.10); removed the intake-time credit-admission call, as PRD 2.9's only declared credit refusal is at charge time.
- `engine.py` — added per-entity state enums so a value outside a resource's declared set reports `ERR_INVALID_STATE` rather than being mistaken for terminal (PRD 2.11); `billing_status` has its own enum; removed the non-PRD `CREDIT_HOLD → ON_HOLD` sweep (PRD 3.1 confines it to "still in SUBMITTED").
- `db.py` — `iso()` renders whole-second instants as `…:00Z` and sub-second ones with three digits, matching the PRD's own pinned instants.
- `serializers.py` — orders carry their `test_lines` in ascending `line_sequence`.
- `rules.py` — a specimen with no ordered test reports a numeric `remaining_stability_hours` rather than null.

**Tests rewritten to be PRD-faithful (assertion corrections, not weakenings):** the stability-boundary expectations in `test_02`/`test_04`/`test_08` (remaining stability is *window minus elapsed*, so "exactly one window ago" is 0.0, not the full window); `test_03`'s late-credit figure (PRD credits "the line's own charge" = `billed_cents` 1000 → 15.00, not the order's surcharged 1150); `test_02`'s recall/dispatch and reject-twice error ids (terminal-state refusals); the reflex-target publish ordering in `test_04`/`test_05` (PRD 3.4 requires the target `PUBLISHED` first, which also keeps the certified build current per PRD 2.8); `test_07`'s CREDIT_HOLD and courier-overlap scenarios; `test_06`'s multi-line and patient-scope setups.

## Step 8: Finalize PRD — 2026-09-30T09:30:00.000Z

`PRD_FINALIZED.md` produced by copying `PRD.md` and applying **19 in-place revisions** (no new sections, no line-count change).

- **PRD.md:** 415 lines · **PRD_FINALIZED.md:** 415 lines · **delta:** 0 lines (0%). Every edit replaces an existing sentence in place; paragraph/section structure is unchanged.

## Per-change log

- **§2.3 — revise** — pagination block is present on every paginated response including an empty window (`total_count` 0, `has_more` false) — `routes.py:906` (`_page`), `middleware.py:123` (`paginate`)
- **§2.4 — revise** — `created_at`/`updated_at` render bare (`…:00Z`) on whole seconds and 3-digit otherwise, not "exactly three fractional digits" — `db.py:79` (`iso`)
- **§2.5 — revise** — a specimen with no establishable binding window (no ordered test, or no datable window) reports numeric `0`, not null — `rules.py:201` (`remaining_stability_hours`)
- **§2.9 ¶1 — insert** — order-accession is separately posture-gated to `ACTIVE`/`CREDIT_HOLD` (`ERR_CLIENT_NOT_ACTIVE`) — `workflows.py:581` (`engine_order_accession`, gate at 591)
- **§2.9 ¶2 — insert** — the credit ceiling is the only credit refusal and fires only at the explicit charge act, not at intake or release — `engine.py:282` (`within_credit_ceiling`), `workflows.py:1034`, `workflows.py:734`, `workflows.py:501` (`_check_credit_admission`, now dead)
- **§2.10 — revise** — courier overlap excludes a leg whose `scheduled_delivery_at` the clock has passed (clock-authoritative) — `routes.py:200` (`_leg_state_as_of`), `routes.py:236`
- **§2.11 — insert** — declared-enum terminal/starting semantics, terminal-before-generic precedence, the per-entity terminal-state list, the redo-leg exemptions, and the `billing_status` dimension — `engine.py:188` (`guard_transition`), `engine.py:128-185`, `workflows.py:775` (`engine_order_hold`)
- **§3.1 — revise** — `interface_status` ladder values (`NOT_BUILT`/`DRAFT`/`IN_BUILD`/`CERTIFIED`/`SUPERSEDED`/`RETIRED`) and that opening a build recomputes it — `rules.py:53`, `rules.py:525`, `workflows.py:1249`, `routes.py:717`
- **§3.3 ¶1 — revise** — accession uses the inclusive elapsed-time bound (remaining `0.0` still accessions) — `workflows.py:159`, `workflows.py:124`
- **§3.3 ¶2 — revise** — re-accession uses the same inclusive bound — `workflows.py:159`
- **§3.3 ¶4 — revise** — rejection cancels only `PENDING`/`IN_PROGRESS`/`REPEAT_REQUIRED` lines (leaves `INTERIM`/`FINAL`/`CANCELLED`) — `workflows.py:271` (`_cancel_order`), `workflows.py:244`
- **§3.4 — revise** — catalogue creation validates `transport_temperature`/`test_category`/`reflex_condition` against declared sets as `ERR_INVALID_REQUEST` — `routes.py:353`
- **§3.5 ¶1 — revise** — an order read carries its `test_lines` in ascending `line_sequence` — `serializers.py:155` (`send_out_order`)
- **§3.5 ¶4 — revise** — no order-status precondition on an add-on; specimen-anchored bounds run ahead of catalogue-currency/duplicate checks — `workflows.py:889` (`engine_order_add_on_test`), `workflows.py:869`
- **§3.6 — revise** — begin-testing uses the inclusive stability bound (remaining `0.0` qualifies) — `workflows.py:191`
- **§3.7 — revise** — specimen reaches `RESULT_PENDING_REVIEW` only once every order's non-cancelled lines are entered — `workflows.py:662` (`engine_order_enter_results`)
- **§3.9 — revise** — acknowledging from `OPEN` records `SENT` + one `send_count` before `ACKNOWLEDGED` — `workflows.py:1711` (`engine_advisory_acknowledge`)
- **§3.10 ¶3 — revise** — the late credit reads the line's own `billed_cents`, not the surcharged order figure — `rules.py:339` (`compute_turnaround_credit`)
- **§3.10 ¶4 — revise** — no ledger row is ever auto-created; charge/release/settlement skip the ledger when absent — `engine.py:301`, `engine.py:321`, `workflows.py:734`, `workflows.py:1631`, `engine.py:494`

## Per-edit pre-edit search log

Each edit was preceded by enumerating every impl path touching its subject (grep + read of all callsites/branches/cascades), then the wording was widened where an enumerated path would otherwise be mis-described:

1. **§2.3 subject:** pagination `meta`. **Paths:** `_page` (all `_page` callers), `paginate`, `pagination_args`. **Adjustment:** dropped a first draft that pinned the echoed `limit`/`offset` on empty windows; kept only `total_count`/`has_more`, matching `paginate`.
2. **§2.4 subject:** instant serialization. **Paths:** `iso` (every serializer, `stamp_common`, `touch`, all `created_at`/`updated_at`/`updated_at`-derived fields, `api_request_timestamp`). **Adjustment:** none; scoped to recorded instants so `api_request_timestamp` (real time, always 3-digit) stays out.
3. **§2.5 subject:** `remaining_stability_hours`. **Paths:** `remaining_stability_hours`, `binding_window_hours`, `ordered_catalog_entries_of_specimen`, `serializers.specimen`. **Adjustment:** widened from "no ordered test" to "no establishable window" because `binding_window_hours` also returns `None` when the entry declares no window for the observed temperature.
4. **§2.9¶1 subject:** order-accession posture. **Paths:** `engine_order_accession`, `require_intake_admissible`, `needs_published_requirements`, `engine_specimen_accession` bubble, specimen create, order create, courier dispatch. **Adjustment:** scoped the new sentence to the dedicated order-accession act (species-level and submit paths use the laxer published-note gate); removed a draft "stricter than intake" comparison that risked implying other acts.
5. **§2.9¶2 subject:** credit ceiling. **Paths:** `within_credit_ceiling`, `engine_order_charge`, `engine_order_release_results`, `refresh_client_posture`, `_check_credit_admission` (dead), `recompute_outstanding_balance`. **Adjustment:** pinned the refusal to the explicit charge act and stated release admits over-limit (aligns with §3.7).
6. **§2.10 subject:** courier overlap. **Paths:** `h_courier_create`, `_leg_state_as_of`, `engine_courier_dispatch`, `engine_courier_arrive`, `fire_clock_events`. **Adjustment:** added the clock-authoritative exclusion; confirmed `RECALL`/`ABORTED`/`COMPLETED` legs were already excluded by both PRD and impl.
7. **§2.11 subject:** state guards. **Paths:** `guard_transition`, `STATE_ENUMS`, `TERMINALS`, `TERMINAL_EXEMPT`, `transition_state_field`, `engine_order_hold`, all transition tables. **Adjustment:** re-drafted to avoid the false claim that rebooking an `ABORTED` run leaves a terminal state (it does not); confined the redo-leg list to the two true redo legs plus the billing-review hold.
8. **§3.1 subject:** `interface_status`. **Paths:** `recompute_interface_status`, `INSTALL`/`INTERFACE_BUILD_RANK`, `engine_build_*`, `_recompute_client_interface`, `h_build_create`, activation, publish-requirements. **Adjustment:** replaced "takes one of `NOT_BUILT`,`IN_BUILD`,`CERTIFIED`,`RETIRED`" with the full ladder since impl can report `DRAFT`/`SUPERSEDED`; kept the activation consequence.
9. **§3.3¶1 subject:** accession stability. **Paths:** `engine_specimen_accession`, `_check_stability_inclusive`, `_check_specimen_quality`, `engine_specimen_begin_testing`. **Adjustment:** replaced "`remaining_stability_hours` strictly above zero" with the inclusive elapsed bound the impl actually applies.
10. **§3.3¶2 subject:** re-accession. **Paths:** same as 9 plus the `TEST_WITHDRAWN` branch. **Adjustment:** same substitution.
11. **§3.3¶4 subject:** rejection line cascade. **Paths:** `engine_specimen_reject`, `_cancel_order`, `_maybe_raise_duplicate_advisory`. **Adjustment:** corrected the status list to `PENDING`/`IN_PROGRESS`/`REPEAT_REQUIRED` (first draft wrongly said `INTERIM`).
12. **§3.4 subject:** catalogue creation shape checks. **Paths:** `h_catalog_create`, `engine_catalog_publish` (reflex-target gate). **Adjustment:** none; confirmed publish's reflex-target refusal is already `ERR_INVALID_STATE` in the PRD.
13. **§3.5¶1 subject:** order wire shape. **Paths:** `serializers.send_out_order`, `order_test_line`, `lines_of_order`. **Adjustment:** none.
14. **§3.5¶4 subject:** add-on semantics. **Paths:** `engine_order_add_on_test`, `_check_order_line_effect_eligibility`, `_check_stability_inclusive`, `_check_strict_reflex_stability`, `engine_order_create`. **Adjustment:** neutralized the order-status clause and stated the specimen-anchored bounds precede catalogue-currency/duplicate checks (matches impl order).
15. **§3.6 subject:** begin-testing stability. **Paths:** `engine_specimen_begin_testing`, `_check_stability_inclusive`, `_live_analyzer_run_covers`. **Adjustment:** same substitution as accession. (Same stability-boundary silence as the Step 7 test_02/04/08 item, applied at the sibling site so no un-implemented strict check is implied.)
16. **§3.7 subject:** specimen review transition. **Paths:** `engine_order_enter_results`, `rules.orders_of_specimen`, specimen serializer, message transmit. **Adjustment:** added the cross-order condition (impl requires every line of every order against the specimen).
17. **§3.9 subject:** advisory acknowledgement. **Paths:** `engine_advisory_acknowledge`, `engine_client_publish_requirements`, `_raise_utilization_advisories`. **Adjustment:** none beyond the two-rung description.
18. **§3.10¶3 subject:** late-credit base. **Paths:** `compute_turnaround_credit`, `overrun_hours_for`, `volume_tier_price`, `order_final_charge_cents`. **Adjustment:** none.
19. **§3.10¶4 subject:** ledger optionality. **Paths:** `post_charge_to_ledger`, `void_charge_on_ledger`, `_ledger_for`, `engine_order_release_results`, `engine_ledger_void_charges`, `engine_client_settle_balance`, `engine_order_charge`. **Adjustment:** softened a first draft that enumerated release's specific order-side effects (it also applies broadly); final wording only asserts the ledger update is skipped.

All edits are consistent with the current `implementation/`; no test files were treated as authoritative.

## Step 9: Complete PRD — 2026-09-30T09:55:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_3138_reference_laboratory_send_out_testing_result_interfacing/workspace/PRD_COMPLETED.md` now pins every passage where the PRD admitted more than one reading of what `workspace/implementation/` does.

## Summary

- **Source**: `PRD_FINALIZED.md` (existed) → `PRD_COMPLETED.md`.
- **Size**: 415 lines → 415 lines (unchanged); 105,198 → 108,742 chars (**+3,534**).
- **Counts**: 16 ambiguity-pins, 2 mismatch-revisions. No new sections; all edits are in-paragraph inserts/revisions.

### Changes (one bullet per edit)

- §2.1 — insert — ambiguity — scope check runs after the permission check and before any identifier is resolved, so a foreign-scope request naming a non-existent resource reports `ERR_CLIENT_SCOPE_VIOLATION`, not a not-found error — `implementation/dispatcher.py:60-72`
- §2.1 — revise — mismatch — scope-checked list now names only publishing requirements, submitting an order, cancelling an order and reading a single client; advisory acknowledge/dismiss (and listing/reading advisories) are removed, since those endpoints carry no scope spec — `implementation/routes.py:940,1097,1099` vs `implementation/routes.py:151,1000,1016`
- §2.4 — revise — ambiguity — clock-driven advances now name the exact instants (`scheduled_departure_at`/`scheduled_delivery_at`, `reserved_start_at`/`reserved_end_at`) and the resulting edges (`DISPATCHED→IN_TRANSIT→COMPLETED`, `RESERVED→RUNNING→COMPLETED`) — `implementation/engine.py:362-398`
- §2.11 — insert — ambiguity — a non-integer query parameter is `ERR_INVALID_REQUEST`, while an out-of-range integer is clamped into the permitted window rather than rejected — `implementation/middleware.py:94-110`
- §3.2 — insert — ambiguity — `base_transit_minutes` and `per_leg_increment_minutes` are supplied on the booking and are not carried on the leg response — `implementation/routes.py:262-278`
- §3.4 — insert — ambiguity — reflex block is mandatory when `reflex_condition != NONE`; `reflex_test_code` need not resolve at creation (only at publication); only `client_price_cents` and the four interpretation limits are optional — `implementation/routes.py:329-363,384-393`
- §3.4 — insert — ambiguity — the withdrawal cascade reaches *every* order riding a rejected specimen, not only the earliest — `implementation/engine.py:619-627`
- §3.5 (submission) — insert — ambiguity — `line_sequence` defaults to the line's 1-based position in the submitted array — `implementation/workflows.py:465-469`
- §3.5 (utilization) — insert — ambiguity — the override lifts only the ESCALATED block; the repeat still raises/re-sends its duplicate-order advisory — `implementation/workflows.py:512-578`
- §3.5 (add-on) — revise — mismatch — `stability_deadline_at` is re-derived as the specimen's `received_at` plus its binding window (null when no window), not "receipt instant plus smallest remaining stability across live lines" — `implementation/rules.py:421-434`, `implementation/serializers.py:156`
- §3.6 — insert — ambiguity — "live catalogue entries" = entries on lines in `PENDING`/`IN_PROGRESS`/`INTERIM`; `FINAL`/`REPEAT_REQUIRED`/`CANCELLED` lines drop out — `implementation/rules.py:50-51,390-401`
- §3.8 — insert — ambiguity — reflex spawn copies `client_laboratory_id`, `specimen_id`, `order_number`, `patient_mrn`, `priority` and pins `client_requested_at` to the clock; only the first firing line spawns an order; an order may be submitted against a `RESULT_PENDING_REVIEW` specimen — `implementation/workflows.py:1086-1137`, `implementation/workflows.py:399-435`
- §3.10 (per-line) — insert — ambiguity — the reportable count includes lines whose charge is not yet written, i.e. the tier count can exceed the number of lines that contributed an amount — `implementation/rules.py:260-288`
- §3.10 (charge) — revise — mismatch — direct charge is admissible from `billing_status` `UNBILLED`, `PROVISIONAL` **or `VOIDED`** (the PRD omitted `VOIDED`, contradicting her own §3.10 cyclic-charge claim) — `implementation/engine.py:98`
- §3.11 — insert — ambiguity — release-hold requires the strict `ACTIVE` rung; a `CREDIT_HOLD` client is refused — `implementation/workflows.py:792-801`
- §3.12 (certify) — insert — ambiguity — round-trip evidence is not separately recorded API surface, so an `IN_BUILD` build certifies on request — `implementation/workflows.py:1293-1309`
- §3.12 (transmit/hold) — insert — ambiguity — the specimen is released only when it sits in `RESULT_PENDING_REVIEW`; a `QUEUED`/`TRANSMITTED` message resolving to a non-CERTIFIED build is passed over by release-hold — `implementation/workflows.py:1547-1551`, `1571-1578`
- §4 — insert — ambiguity — the add-on and reflex appends answer `200 OK` (the order already exists), the single exception to "new resource ⇒ 201" — `implementation/dispatcher.py:98-115`, `implementation/routes.py:1021-1028`

Deliberately not changed: the §2.1 identity-semantics sentence about a "segregation-of-duties check" (already non-load-bearing and too broad to pin without inventing behavior), the unreachable `ERR_CREDIT_LIMIT_EXCEEDED` definitions, and the `_settlement_credit_cents` razor-edge reachability of the credit-hold revert (a hazard in the PRD's own settlement definition rather than an ambiguity vs. the implementation).
