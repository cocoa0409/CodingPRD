# Worklog — task_2858_school_bus_manufacturing

## Step 1: Create task directory — 2026-09-05T07:36:20.865Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing` and `.../workspace`. Index 2858 was pre-assigned by the orchestrator prompt (no `./tasks/` scan performed — concurrent pipelines on this host make auto-allocation unsafe).

## Step 2: Generate scaffold — 2026-09-05T09:17:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and the linter reports a clean verdict.

## Files

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing/SCAFFOLD.yaml` | 3614 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2009 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml` | 4321 |

All three parse with `yaml.safe_load`. `SCAFFOLD.yaml` contains neither design key; each design file has exactly one top-level key (`scaffold_difficulty_design` / `scaffold_corner_design`).

## SCAFFOLD.yaml counts (§1.0–§1.7)
15 entities · 63 endpoints · 14 state machines (parallel shape; BusUnit carries 3 dimensions) · 2 concurrency rules · 10 calculations · 66 validations · 66 errors · 6 roles. `api_prefix: ""` (flat topology). Validation priority numbers 35 and 55 are deliberate gaps: two originally drafted rules (`ERR_NO_PUBLISHED_SPEC_PROFILE`, `ERR_SPEC_SAFETY_ITEM_MISSING`) were proven unreachable — the award-time `max()/OR` upgrade plus the order's frozen profile means the rollover/safety gate can never fail at mint or certify — so both rows and their error-catalog entries were deleted rather than left as untriggerable claims. Other check texts cite priority numbers by value, so no renumbering was done.

## §1.8 Difficulty design
18 instances across 9 rule_ids (`dual_variant_calc`, `non_linear_state_machine`, `transitive_cascade`, `validation_priority_inversion`, `boundary_precision`, `cross_entity_state_dependency`, `temporal_window_arithmetic`, `conserved_quantity_ledger`, `rounding_composition`).

## §1.9 Corner design — 62 instances (46 with full `test_recipe`, 16 `excluded_because` stubs)
entities 12 · state_machines 12 · calculations 9 · validations 8 · endpoints 5 · errors 4 · rbac 5 · cross_cutting_complexity_layers 5 · consistency_model 2.

## Verification
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 63   §1.1 entities declared: 15
  §1.8 instances scanned: 18    §1.9 instances scanned: 46
  Calls scanned (§1.8+§1.9): 909
```
Additional self-checks: instance names unique across §1.8 ∪ §1.9 (no collisions, no overlap); every stub's cited `difficulty_instance` resolves to a real §1.8 name; **all 66 error ids are triggered by at least one instance** (the last two holes, `ERR_ORDER_NOT_ACTIVE` and `ERR_BODY_CLASS_UNSUPPORTED`, were closed by extending the delivery-gate and slot-OCC chains rather than duplicating ~130 lines of fixture).

Two lint fixes were needed this session: a capture of `$.data.current_utc` on the clock endpoint (scalar output → changed to `$.data`), and earlier grounds/priority cross-reference errors found by diffing against §1.4/§1.5.

Scratch: only `workspace/calc.py` and `workspace/calc2.py` remain (the literal-pinning scripts; `calc2.py` is authoritative). The stale `workspace/lintcheck/` copy of the three YAMLs was deleted. `git status` shows the single untracked directory `tasks/task_2858_school_bus_manufacturing/` — nothing outside the task dir was created, modified, or deleted, and no sibling task was read.

**Orchestrator note:** verified `SCAFFOLD.yaml` contains no trace of the "harder than expert level" difficulty directive (grep clean), so it cannot leak into PRD.md. Deleted the two scratch scripts `workspace/calc.py` / `workspace/calc2.py` before Step 4 — they pin §1.8/§1.9 worked-example literals and sit in the same directory the doc generator reads.

## Step 3: Copy shared files — 2026-09-05T09:18:48.878Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T09:37:00.000Z

Subagent summary (verbatim):

PRD complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing/workspace/PRD.md` — **532 lines, 110,526 bytes** (built with 1 `Write` + 8 heredoc appends; no truncation).

**Section outline (top-level):**
- `# School Bus Manufacturing API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` (2.1 RBAC · 2.2 API Response Structure, verbatim · 2.3 Pagination · 2.4 Logical Plant Clock · 2.5 Identity/Timestamps/Version · 2.6 Money & Range Rounding · 2.7 Stale-Read Protection · 2.8 Rejection Precedence, a 66-rung ladder · 2.9 Derived Counters & Conservation Invariants · 2.10 Natural Keys & Compatibility Gates · 2.11 Sub-Resource Paths)
- `## 3. Business Logic & Workflows` (3.1 State Spec Profiles · 3.2 Catalogue & Range · 3.3 Solicitations, Bids, Compliance Verdict · 3.4 Revisions & Round Ceiling · 3.5 Award, Spec Upgrade, Escalation, Contract Total · 3.6 Lines, Buses, Build Slots, Schedule Posture & Liquidated Damages · 3.7 Test Bays, Quality Tests, Certification & Waivers · 3.8 Dealers, Driver Training, Delivery, Legacy Fleet · 3.9 Recall Campaigns, Kit Pool, Dealer Standing)
- `## 4. Endpoint Definitions` (4 columns: Method | Path | Description | Authorized Role(s))
- `## 5. Error Code Catalogue` (2 columns: Error ID | HTTP Status Code)

**Tail check:** the file ends at a clean section boundary — the final row of the §5 error table (`| \`ERR_CLOCK_REWIND_FORBIDDEN\` | 422 |`), a completed table closing a completed final section. Nothing mid-sentence, mid-table or mid-list.

**Hard Contracts**
- **Contract 1 — Field-Name Coverage: PASS.** All 160 unique identifiers (every `entities[].fields[].name` across the 15 entities plus every endpoint input/query/path identifier) appear verbatim in backticks. 0 missing.
- **Contract 2 — Rule Coverage: PASS.** All 66 error IDs are referenced in the narrative before §5; all entity enum values appear; all constants of all 10 calculations appear (numerically or as the equivalent worded percentage — e.g. `DEALER_PREP_PCT` as 2.375 %, volume tiers as "1 through 9 / 10 through 24 / 25 through 49 / 50 or more"); all 12 state machines' transitions incl. sibling-branch symmetry (both revision-append branches, both `PENDING → CERTIFIED` and `WAIVED → CERTIFIED`, all three `→ PLANNED` reverts), both OCC rules, both 4-hop cascades with their hop-2 short-circuit, both conservation invariants, and every `applies_to` scope rendered as a rung of the §2.8 ladder.
- **Contract 3 — §3 Path Purity: PASS.** 326 backtick tokens in §3; none starts with `/`, none is a bare HTTP method, none combines method+path; no raw path-like strings outside backticks either.

**Structural fidelity checks:** §4 contains exactly 63 rows matching the scaffold's methods, paths and role lists byte-for-byte (0 missing, 0 extra, 0 role mismatches) and exactly 4 columns; §5 contains exactly 66 rows matching every error ID/status pair and exactly 2 columns. No scaffold jargon leaked (no `CASCADE-A`, no `§1.x` back-references, no fuzzy hedging words).

**Two things worth flagging:**
1. The error catalogue has **66** entries, not 68 — scaffold validation priorities run 1–68 but skip 35 and 55. The §2.8 ladder is renumbered contiguously 1–66 and all its internal cross-references use the renumbered rungs.
2. One genuine scaffold ambiguity resolved: `POST /bids` side_effects never mentions creating a `BidRevision`, but `BidRevision.round_index` is documented as "0 for the revision minted with the bid" and `Bid.revision_round` / the `is_superseded` sweep only cohere if it exists. The PRD therefore states that bid creation lays down a round-zero revision snapshot, asserted consistently in §3.3 and §3.4. Also, the bid's "`unit_count` must equal the solicitation's `unit_count`" has no error code in the catalogue, so it is stated descriptively rather than as an invented gate.

Scratch directory removed; only `workspace/PRD.md` was created. `worklog.md` untouched.

**Orchestrator truncation check:** independently confirmed — `wc -l` 532; `tail -15` ends on the `ERR_CLOCK_REWIND_FORBIDDEN | 422` table row, a complete final row of the §5 table; 5 top-level `##` headings present (§1–§5) with §5 last. No mid-sentence cutoff, so no regeneration needed. Also grepped PRD.md for the difficulty directive and scaffold jargon — clean.

## Step 6: Generate implementation — 2026-09-05T10:19:00.000Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message, so the impl generator could not see `test_suite/`. Step 6 returned first; the Step 5 entry follows below out of numeric order.)

Subagent summary (verbatim):

Implementation complete and smoke-verified.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing/workspace/implementation/`)

| file | lines |
|---|---|
| `app.py` | 72 |
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `db.py` | 147 |
| `errors.py` | 100 |
| `middleware.py` | 43 |
| `response.py` | 107 |
| `shapes.py` | 181 |
| `services/calc.py` | 289 |
| `services/domain.py` | 357 |
| `routes/clock.py` | 37 |
| `routes/catalog.py` | 212 |
| `routes/plant.py` | 246 |
| `routes/commerce.py` | 419 |
| `routes/units.py` | 279 |
| `routes/quality.py` | 154 |
| `routes/network.py` | 352 |
| `routes/__init__.py`, `services/__init__.py` | 0 |
| **total** | **3006** |

All modules `py_compile` clean. Storage is in-memory dicts only; nothing is seeded at import or startup; `start.sh` reads `$PORT`, binds 0.0.0.0, runs `python3 app.py` in the foreground (pip install only when `import flask` fails). Flask is created with `static_folder=None`.

## Endpoint coverage: 63 / 63
`app.url_map` reports exactly 63 method+rule pairs, matching the scaffold list one-for-one (clock 1, spec profiles 4, bus models 3, propulsion packages 3, production lines 4, test bays 3, dealers 4 incl. legacy-fleet-records, solicitations 4, bids 8, contract orders 3, bus units 8, build slots 5, quality tests 4, recall campaigns 4, remedy tasks 5).

## Covered behaviour
- **State machines**: StateSpecProfile (DRAFT→PUBLISHED→SUPERSEDED), Solicitation (OPEN→CLOSED→AWARDED), Bid (DRAFT/SUBMITTED/REVISION_REQUESTED/AWARDED/REJECTED incl. sibling rejection on award), ContractOrder (ACTIVE→FULFILLED, posture ON_TRACK/AT_RISK/BREACHED with BREACHED absorbing), ProductionLine status, BuildSlot (PLANNED/COMMITTED/IN_PROGRESS/COMPLETED/RELEASED), BusUnit's three parallel dimensions (production × certification × service) plus driver_training_status, QualityTest (SCHEDULED→PASSED/FAILED/VOIDED), RecallCampaign (DRAFT→LAUNCHED→COMPLETED), RemedyTask (OPEN→IN_PROGRESS→COMPLETED/CANCELLED).
- **Calculations** (`services/calc.py`, Decimal, ROUND_HALF_UP money / ROUND_DOWN 1-dp / ROUND_FLOOR nominal): six-line-item `bid_unit_price` with the 2.375% prep fee rounded per line item, award-time max()/OR spec upgrade, 0.45%/month escalation, volume discount + freight tier + 1.25% compliance admin contract total, diesel and electric `range_validation`, joint strength with the rollover bonus, `spec_compliance_evaluation`, test minimum values (0.0025 kN/lb rollover), liquidated damages with the 5% cap, dealer standing thresholds and the factory-escalation extra kit / kit-shortfall accounting.
- **Cascades**: CASCADE-A (FAIL → unit NONCONFORMING → live slot RELEASED → line ledger + phase revert + sibling SCHEDULED tests VOIDED → order posture/damages) and CASCADE-B (launch → one OPEN task per in-scope bus in `delivered_at ASC, created_at ASC` order → bus RECALL_OPEN → dealer exposure/standing → DEALER_DIRECTED→FACTORY_DIRECTED escalation with kit reserve or shortfall).
- **Cross-cutting**: envelope + `req_`-prefixed request ids, pagination meta, six-role RBAC with entity-backed DealerAgent ownership, the 66-rung global ladder with lowest-rung-wins ordering and strict check-then-mutate, both OCC endpoints (`expected_bid_version`, `expected_production_line_version`, both required), `version`/`updated_at` bumping at most once per record per request, and the logical clock (startup epoch `2026-08-01T00:00:00Z`, never wall clock).

## Smoke test (PORT=18581, own PID only, no pattern-kill; port confirmed free afterwards)
Three scripted runs against a fresh process:
1. Dealer/recall path: empty list → create dealer 201 → read 200 → 404/409/403/401 error envelopes → profile+publish → model → package → legacy fleet import 201 (seats raised 71→72, mirror STANDARD→CROSSVIEW, joint 55→64.5 kN, nominal 450 mi, derated 356.2 mi) → campaign 201 → launch 200 (affected_unit_count 1, reserved 1, available 4) → task start/complete → campaign auto-COMPLETED with consumed 1 / available 4 (kit conservation) → unit RECALL_OPEN→RECALL_CLOSED → clock set 200 (`api_request_timestamp` follows it) and pre-epoch rewind 422.
2. Full commerce/production lifecycle: solicitation → bid → revision (round 1, stale version → 412) → submit (CONFORMING) → close → award 201 (awarded price 15,378,543; total 16,836,400; upgraded config) → mint unit → line → slot (stale line version → 412) → commit (unit SLOTTED, ledger 10) → BODY_JOINED → BUILT → five quality tests incl. measured JOINT_STRENGTH (min 60.0) and ROLLOVER (min 53.75) → certify 200 → assign dealer → driver training → deliver → order FULFILLED, ON_TRACK, damages 0.
3. Failure path: FAIL on a BRAKE test produced NONCONFORMING unit, RELEASED slot, unit back to PLANNED, sibling test VOIDED, ledger 17→10, order at_risk 1, then `certify` 409 `ERR_UNIT_PHASE_INVALID` and `waive-nonconformance` 422 `ERR_WAIVER_NOT_PERMITTED` (brake failures unwaivable). Unknown route returns a 404 error envelope.

## Ambiguities resolved (interpretation chosen)
- `api_request_timestamp` and every system-stamped instant come from the logical clock, formatted `YYYY-MM-DDTHH:MM:SS.mmmZ` (exactly 3 fractional digits). Client-supplied datetimes (`window_start/end`, legacy `delivered_at`) are echoed back byte-for-byte as supplied; a bare date is accepted and compared at date granularity.
- Clock endpoint: missing/non-string `current_utc` → `ERR_INVALID_REQUEST` 400; unparseable or earlier than the **fixed epoch** `2026-08-01T00:00:00Z` → `ERR_CLOCK_REWIND_FORBIDDEN` 422 (so a backward move that stays >= epoch is accepted); it recomputes nothing.
- PRD rung 36 prose calls the "profile still published" check rung 44 when it is rung 53 — the numeric ordering was followed.
- `to_status` accepts only `{BODY_JOINED, BUILT}` (anything else 400); advance without a COMMITTED/IN_PROGRESS slot → `ERR_UNIT_PHASE_INVALID`.
- Certify on an already-CERTIFIED bus → `ERR_UNIT_PHASE_INVALID` at the rung-25 position; NONCONFORMING falls through to `ERR_OPEN_TEST_FAILURE`; a WAIVED bus skips the required-test rung but still faces range/joint/SoD/profile-published.
- Line `status` and `complete-driver-training` are idempotent (200 + version bump when already in the target state).
- Deliver has no "dealer unassigned" error id, so an unassigned bus fails at `ERR_DRIVER_TRAINING_INCOMPLETE`; a DealerAgent on another dealer's bus fails at `ERR_NOT_ASSIGNED_DEALER`.
- `record-result`: "measured_value required when min_required_value is non-null" is evaluated after existence and before the state rung; measured_value is stored only for measured tests.
- Legacy-fleet-record resolution follows the numeric ladder (profile → model → package → dealer) rather than §2.11's path-before-body reading.
- Declared numeric bounds, `state_code` (2 uppercase) and `school_year` (YYYY-YYYY) are enforced as `ERR_INVALID_REQUEST`; decimal-place counts are not. Bid `unit_count` mirroring the solicitation is not enforced (no error id exists).
- `recompute_order` recomputes (never accumulates) damages on every breached recomputation, so a fully delivered breached order settles at 0 by the literal formula; dealer escalation fires only when standing severity increases.
- Filter query params are validated against their declared enums/booleans (bad value → `ERR_INVALID_REQUEST`); list default order is `created_at` ASC with a stable creation-sequence tie-break.

## Step 5: Generate unit tests — 2026-09-05T11:17:00.000Z

(Launched concurrently with Step 6 in a single orchestrator message; returned second, hence the out-of-numeric-order placement.)

Subagent summary (verbatim):

Step 5 is complete. Both output directories sit directly under the task root; nothing was written inside `workspace/`, and the scratch dir and all `__pycache__` are removed.

## Files

`/home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing/test_helpers/` (Stage 1, 2,436 lines)
`__init__.py` 40 · `api_client.py` 270 · `api_errors.py` 147 · `assertions.py` 420 · `constants.py` 89 · `factories.py` 369 · `fixtures.py` 530 · `test_users.py` 93 · `types.py` 478

`/home/ubuntu/github/CodingPRD/tasks/task_2858_school_bus_manufacturing/test_suite/` (Stage 2, 5,933 lines)
`conftest.py` 65 · `test_01_bid_pricing_and_award_variants.py` 403 (8) · `test_02_lifecycle_state_machines.py` 248 (4) · `test_03_failure_and_recall_cascades.py` 250 (5) · `test_04_rejection_precedence.py` 181 (4) · `test_05_boundaries_and_windows.py` 248 (4) · `test_06_cross_entity_gating.py` 232 (4) · `test_07_temporal_overlap.py` 303 (4) · `test_08_compensating_invariants.py` 226 (4) · `test_09_entity_contracts.py` 450 (11) · `test_10_state_machine_transitions.py` 583 (10) · `test_11_derived_calculations.py` 442 (7) · `test_12_validation_gates.py` 559 (8) · `test_13_endpoint_surfaces.py` 347 (5) · `test_14_error_precedence.py` 366 (5) · `test_15_role_and_identity_gates.py` 415 (6) · `test_16_concurrency_and_consistency.py` 615 (6)

## Coverage

- **95 test functions**, each carrying exactly one `Design:` line as the last line of its docstring.
- **Queue A (Difficulty): 18/18 instances → 37 tests.** Queue B (Corner): **46/46 instances → 58 tests.**
- **Zero skips.** A machine cross-check parsed both design yamls and every `Design:` tag: 64 non-stub instances expected, 64 distinct tags present, no missing instance, no tag pointing at a stub or a non-existent name. The 16 `excluded_because:` stubs were correctly not translated.
- Verified mechanically: every file `py_compile`s; every `test_helpers` import resolves to a real barrel export; every `api_client.<attr>` is a real method; no unused imports (Name-node scan, not just attribute matching).

## Design-index defects overridden in favour of the PRD

The final file exposed three more index errors (added to the earlier list of wrong HTTP statuses and enum values):

- `derated_route_range_mi` on MOUNTAIN terrain: the index asserts `73.0`; the PRD truncates rather than rounds, so 122.76 / 1.425 / 1.18 = 72.99776... → **72.9**.
- `spec_compliance_status: CONFORMING_WITH_EXCEPTIONS` is not a PRD enum value → **`EXCEPTIONS_TAKEN`**.
- The index claims `?is_superseded=true` after round 2 returns "exactly the round-1 revision"; the PRD supersedes *every* earlier revision including round zero, so the test asserts **rounds 0 and 1** (total_count 2).
- `defect_category` values `BRAKE` / `ELECTRICAL` are not in the PRD enum → `BRAKE_LINE_CORROSION` / `WIRING_HARNESS`.

All monetary and range literals in the new file were re-derived by hand from the PRD before being asserted: `14,641,571`, `14,582,808` (crossview mirror = 57,400 of options + 1,363 of per-line prep fee), and `30,695,891` for the 78-seat belted electric bid (29,983,775 of line items + 712,116 of six per-item 2.375% fees).

## Step 7: Run tests and iterate — 2026-09-05T11:44:00.000Z

Subagent summary (verbatim):

All 8 rounds green: **110/110 passed in every round**.

## Iterations run
2 sweeps (sweep 1 → diagnose 8 deterministic failures → batch of fixes → sweep 2 clean).

Sweep 1: 102/110 in all 8 rounds — the same 8 failures every round, zero flakiness, so nothing was load-induced.

## Tests deleted
**None.** All 8 failures passed STEP 1 (PRD verbatim-covers + uniquely derives). Every one resolved at STEP 2 as a test-artifact defect; the implementation needed no change.

## Fixes applied to `test_helpers/`
- `factories.py` — `type_a_mini_model_payload`, `type_c_alt_model_payload`, `type_d_transit_model_payload`, `propane_package_payload`, `mini_diesel_package_payload`: these five derived factories passed their variant defaults as keyword arguments *and* splatted `**overrides` into the same call, so any caller override of a variant-pinned field raised `TypeError: got multiple values for keyword argument`. Rewritten to merge overrides into a variant dict before delegating. (This is what broke `test_14`'s duplicate-`model_code` probe.)

## Fixes applied to `test_suite/`
- `test_01_bid_pricing_and_award_variants.py` — `test_contract_total_is_built_in_four_stages_over_the_awarded_price`: expected `total_contract_cents` was `376_888_640`, derived from a transposed-digit discount of `7,536,422`. PRD §3.5's four stages on the awarded `31,401,843 × 12` give discount `7,536,442`, discounted subtotal `369,285,674`, freight `2,950,000`, admin `4,652,946` → `376_888_620`. Constant and comment corrected.
- `test_02_lifecycle_state_machines.py` — `test_every_earlier_round_is_superseded_and_the_listing_stays_ordered`: sent the `is_superseded` filter as a Python `False`, which serialises on the wire as `"False"`; changed to the canonical JSON boolean literal `"false"`.
- `test_10_state_machine_transitions.py` — `test_the_award_rejects_only_the_siblings_of_the_awarded_solicitation` and `test_the_new_order_opens_priced_but_with_no_buses_on_it`: both called `validate_success(...)` with its default expectation of 200 on an award. PRD §4: "An operation that brings a new resource into existence returns **201 Created** ... this includes awarding a bid". Added the explicit `201`.
- `test_15_role_and_identity_gates.py` — `test_the_submitter_cannot_award_its_own_bid_but_a_colleague_can`: the closing probe resubmits a bid whose solicitation has since reached `AWARDED`, and expected `ERR_BID_STATE_INVALID`. PRD §2.8 rung 22 (`ERR_SOLICITATION_NOT_OPEN`, explicitly listed "on ... submitting a bid") outranks rung 24, so the implementation's answer was the correct one. Expectation corrected to `ERR_SOLICITATION_NOT_OPEN`/409, with the rung-22 verbatim quote added to the docstring. No error_id was downgraded to a bare status check.
- `test_16_concurrency_and_consistency.py` — `test_the_replayed_bid_version_is_refused_and_changes_nothing`: same Python-`True` query-param serialisation bug, changed to `"true"`.
- `test_16_concurrency_and_consistency.py` — `MOUNTAIN_ROUTE_RANGE_MI` (used by `test_the_draft_body_already_carries_price_range_joint_strength_and_verdict`): constant was `72.9`, an arithmetic slip. PRD §3.2's chain gives `122.76 / 1.425 = 86.14736...`, over the `1.18` MOUNTAIN factor `= 73.00624...`, truncated toward zero at one digit `= 73.0`. Verified the same code path reproduces the PRD's own worked `ROLLING` example of `79.7` exactly, so the divisor chain is right and only the test's expected value was wrong. Corrected to `73.0` with the derivation in the comment.

## Fixes applied to `implementation/`
**None.** No implementation defect was found; every failure traced to a test-side constant, wire-format, expected-status or factory-signature bug. `implementation/` is byte-for-byte unchanged from what Step 5/8 produced.

## Final sweep (8 rounds)
| round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 110/110 | 110/110 | 110/110 | 110/110 | 110/110 | 110/110 | 110/110 | 110/110 |

0 failed, 0 errors, 0 skipped in every round. `worklog.md` untouched; the scratch spot-check helper I used between sweeps has been removed, so the only changed files are the five listed test artifacts.

**Orchestrator verification (not taken on trust):** independently re-read all 8 `results.$i.json` (each ~35 KB, mtime 11:42, i.e. written by the post-fix sweep, not the baseline). Every round: `passed=110 failed=0 total=110 errors=0 skipped=0`, and `sweep.log` ends in `SWEEP COMPLETE` with the same 8 lines. Anti-hack invariants re-checked directly: zero `pytest.mark.skip` / `xfail` anywhere in `test_suite/` or `test_helpers/`; zero `sqlite3` / file-write / `json.dump` / `/tmp` persistence anywhere in `implementation/`. The 95 test functions each still carry exactly one `Design:` tag (58 Corner + 37 Difficulty = 95), and the 110 collected cases come from the single `parametrize` in `test_09_entity_contracts.py` — no test was dropped from the suite.

**Step 8 gate decision:** Step 7 needed a second sweep and made 6 test-side fixes, so the "zero iterations beyond baseline" skip condition is NOT met and Step 8 runs. But because Step 7 applied **0** `implementation/` fixes, the expected outcome is a very small or byte-identical `PRD_FINALIZED.md` — every Step 7 item was a pure test-artifact defect (wrong constant, wire serialisation of booleans, factory kwarg collision), and only the `test_15` rung-22 precedence item even arguably reflects PRD wording the implementation read differently. An identical `PRD_FINALIZED.md` is a legitimate result here.

## Step 8: Finalize PRD — 2026-09-05T11:53:00.000Z

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` is written with exactly one edit.

**Line counts:** PRD.md 532 lines / PRD_FINALIZED.md 532 lines — 0% line delta; 1 line revised (0.19% of lines), +198 characters.

**Changes**
- §3.4 (Negotiation Rounds) — revise — the `is_superseded` revision-listing filter is now pinned to the lowercase wire literals `true`/`false`, with any other non-empty value refused as `ERR_INVALID_REQUEST` (400) — `implementation/response.py:99-107` (`q_bool`), consumed at `implementation/routes/commerce.py:261`.

**Per-edit pre-edit search log**
- (a) Subject: textual form accepted for a boolean *query-string filter* value, and the failure mode for a non-canonical spelling.
- (b) Paths enumerated: `response.py:83-107` (`q_str`, `q_enum`, `q_bool` — `q_bool` accepts only `"true"`/`"false"`, raises `ERR_INVALID_REQUEST` otherwise, and inherits `q_str`'s "None or empty string ⇒ filter absent" behaviour); grepped every filter callsite across `routes/catalog.py`, `commerce.py`, `plant.py`, `quality.py`, `units.py`, `network.py` — `q_bool` has exactly **one** callsite in the whole system (`commerce.py:261`, revision listing), so no other endpoint could be mis-described; `shapes.py:92-100` (`get_bool`) confirms body booleans are a separate, JSON-typed path that the new sentence does not touch; `commerce.py:235-237` and `services/domain.py:317` confirm the field's own semantics (starts false, flipped on supersession) are untouched.
- (c) Wording adjustments made: scoped the sentence to this one filter rather than stating a global rule for boolean parameters (only one exists, so a global claim would be unverifiable elsewhere); and used "any other **non-empty** value" because `q_str` maps an empty value to *filter absent* rather than to a 400 — an unqualified "any other value" would have been a false universal.

**Items deliberately left unedited (PRD already uniquely determines them):**
- `test_15` rung-22 precedence — §2.8 rung 22 already lists `ERR_SOLICITATION_NOT_OPEN` "on ... submitting a bid" and rung 24 is strictly lower in the global ladder; `commerce.py:268-276` checks solicitation-OPEN before bid-status, exactly as written. No silence.
- Award returns 201 — §4 already states verbatim that creation returns 201 "this includes awarding a bid, which returns the newly minted contract order rather than the bid"; `commerce.py:389` returns `created(public(order))`. No silence.
- `total_contract_cents` (test_01) — §3.5's four stages plus §2.6's half-up rounding uniquely give 376,888,620; `calc.py:172-178` implements exactly that order (discount → discounted subtotal → freight tier off the discounted subtotal → 1.25% admin on discounted+freight). Pure test-constant bug.
- MOUNTAIN route range 73.0 (test_16) — §3.2's chain and §2.6's truncate-toward-zero uniquely give 73.0; `calc.py:193-199` divides by effective consumption then terrain then `trunc_1dp`, matching the PRD's own worked 79.7 `ROLLING` example. Pure test-constant bug.
- `factories.py` keyword-collision `TypeError` — a fixture signature defect with no behavioral surface in the API. Nothing to pin.

**Orchestrator verification:** diffed the two files directly — exactly one line changed (line 711, the §3.4 revision-listing sentence), +198 chars, 532 lines both sides, and the §5 error table tail is intact. The small diff is the expected shape given Step 7 applied 0 `implementation/` fixes.

**Step 9 plan (recorded before launching):** Step 9 will run as **three sequential file-partitioned passes** over one shared `PRD_COMPLETED.md`, partitioned by implementation module rather than by PRD section, because a single subagent cannot exhaustively walk 3,006 lines of implementation against a 110 KB PRD without silently degrading to a skim (the failure mode is a `PRD_COMPLETED.md` byte-identical to its source). Pass 1 does the `cp` and owns the cross-cutting layer (`app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `shapes.py`) plus `routes/clock.py`, `routes/catalog.py`, `routes/plant.py`. Pass 2 owns `routes/commerce.py` + `services/calc.py`. Pass 3 owns `routes/units.py`, `routes/quality.py`, `routes/network.py` + `services/domain.py`. Passes 2 and 3 must NOT re-copy the file — they edit the accumulated `PRD_COMPLETED.md` in place.

## Step 9: Complete PRD — 2026-09-05T12:26:00.000Z

Run as three sequential file-partitioned passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module (pass 1 did the `cp`; passes 2 and 3 edited in place and were explicitly forbidden from re-copying). Cumulative result: **532 lines, 125,596 chars** — +14,880 chars over the 110,716-char `PRD_FINALIZED.md` it started from, across **45 edits** (40 ambiguity-pins, 13 mismatch-revisions as counted by the passes; 94 diff lines vs `PRD_FINALIZED.md`). No new sections; every edit is an in-paragraph insert or revision.

### Pass 1 — cross-cutting layer + clock/catalogue/plant (`app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `shapes.py`, `start.sh`, `routes/clock.py`, `routes/catalog.py`, `routes/plant.py`)

Subagent summary (verbatim):

- Source `PRD_FINALIZED.md`: 532 lines / 110,716 chars → `PRD_COMPLETED.md`: **532 lines / 115,146 chars** (+4,430 chars, **0 lines added or removed** — 13 line-groups revised in place, all in-paragraph inserts; no new sections). Tail check: final row is `| ERR_CLOCK_REWIND_FORBIDDEN | 422 |` — clean boundary preserved.
- **Counts**: 14 changes — 12 ambiguity-pins, 2 mismatch-revisions.
- §2.1 — revise — ambiguity — an empty (not merely absent) auth header is also 401, and role matching is exact/case-sensitive — `middleware.py:29-34`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + twenty uppercase-alphanumeric chars — `response.py:11,21`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time, so it repeats across requests at one clock setting — `response.py:25`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` → 400; an empty value is treated as omitted and takes the default — `response.py:46-58`
- §2.3 — revise — ambiguity — equal `created_at` values tie-break on internal creation order (never exposed) — `db.py:132-134`
- §2.3 — revise — ambiguity — empty filter value = absent; bad enum filter value → 400; identifier filters match literally (empty page, not 404) — `response.py:83-96`
- §2.4 — revise — **mismatch** — the malformed-vs-shape split: a bad *string* → `ERR_CLOCK_REWIND_FORBIDDEN` 422, but absent/null/non-string `current_utc` → `ERR_INVALID_REQUEST` 400; `Z` required; the rewind floor is the fixed epoch, never the clock's current reading, so backwards moves at/after the epoch are accepted — `routes/clock.py:19-36`
- §2.5 — revise — ambiguity — one request advances a record's `version` by exactly 1 no matter how many cascade hops touch it — `db.py:103-121`
- §2.6 — revise — ambiguity — decimal-place statements are conventions; only the stated bounds are validated — `shapes.py:72-89`
- §2.8 rung 3 — revise — ambiguity — missing body = empty object; non-object body → 400; `null` = absent (takes default); undeclared fields ignored; empty string refused for coded/patterned/enum fields but accepted for free text; instant fields accept a bare calendar date as midnight UTC — `shapes.py:20-39,42-54,153-171`
- §3.1 — revise — ambiguity — `school_year` is shape-checked only; the two years need not be consecutive — `routes/catalog.py:26`, `shapes.py:13`
- §3.6 — revise — **mismatch** — `POST /production-lines/{id}/status` asserts a target state with **no precondition** on current status; a restatement of the same status is accepted and still bumps `version` (PRD previously required the opposite state) — `routes/plant.py:65-73`
- §3.6 — revise — ambiguity — changeover preceding-slot tie-break extends to creation order after `end_date` and `created_at` — `routes/plant.py:153-154`
- §3.6 — revise — ambiguity — slot planning examines nothing else about the bus (phase, existing slots, order status) or the line's `status`, so multiple planned slots and planning on a down line are legal — `routes/plant.py:115-182`
- §5 preamble — revise — ambiguity — the two routing-layer refusals outside the catalogue: unrouted path → `ERR_NOT_FOUND` 404, disallowed method → `ERR_INVALID_REQUEST` 405 — `app.py:47-58`

Notes for later passes: the §5 error table is already byte-exact against `errors.py` (66 ids, identical statuses and order) — no catalogue work remains. `start.sh` (PORT default 10000, conditional pip install) is infrastructure with no PRD surface; the `ERR_INTERNAL` 500 handler in `app.py:60` is a defensive, unreachable branch and was deliberately left undocumented.

### Pass 2 — commerce spine + calculation engine (`routes/commerce.py`, `services/calc.py`)

Subagent summary (verbatim):

- **532 lines** (unchanged), **118,328 chars** — **+3,182** vs the 115,146 inherited (never smaller). Tail still ends at `| ERR_CLOCK_REWIND_FORBIDDEN | 422 |`; §5 still has exactly 66 error rows. **Did not copy any file**; 11 targeted `Edit` calls. Pass 1's work verified present (spot-checks: §2.4's fixed-epoch rewind-floor sentence; §2.5's BidRevision immutability exception).
- **Counts**: 9 ambiguity-pins, 2 mismatch-revisions (11 edits).
- §3.3 ¶solicitation — insert — ambiguity — `required_delivery_date`'s ISO shape is the whole check (never compared to the profile's `school_year` or the clock, so a past date is accepted); `solicitation_code` is not a natural key and is never checked for uniqueness — `commerce.py:63-81`
- §3.3 ¶bid-draft — revise — **mismatch** — PRD said the bid's `unit_count` "mirrors the solicitation's own count"; impl takes it from the request verbatim, never defaulting or validating it, and that figure is what the order and the volume discount use — `commerce.py:131,154,353`
- §3.3 ¶offered-configuration — insert — ambiguity — all seven `offered_*` fields are required on the draft; none carries a default — `commerce.py:22-32`
- §3.4 ¶revision-record — insert — ambiguity — drafting accepts no `note`, so the round-zero snapshot always carries null — `commerce.py:175`
- §3.4 ¶append-preconditions — insert — ambiguity — a revision states the whole configuration, not a delta: all seven figures required (`ERR_INVALID_REQUEST`, never inheritance); `note` optional, null when omitted, empty string accepted — `commerce.py:215-216`
- §2.7 — insert — ambiguity — the version field is an integer >= 0: negative/non-integer/null is 400 at the shape rung, while any non-negative integer that merely mismatches (0 included) reaches the 412 comparison. Verified true of `expected_production_line_version` too — `commerce.py:214,219` + `plant.py:119`
- §3.3 ¶submitting — insert — ambiguity — a re-submission overwrites `submitted_at`/`submitted_by_user_id` with no history, so award-time SOD and the escalation month count read the latest submission — `commerce.py:299-300`
- §3.5 ¶reconciliation — insert — ambiguity — award writes back only the bid's `status`; the upgraded config, `evaluated_spec_profile_id`, verdict fields and both range figures stay as submission left them — `commerce.py:379-380`
- §3.2 ¶electric-range — insert — ambiguity — zero nameplate consumption yields `nominal_range_mi` 0 rather than an arithmetic failure — `calc.py:192`
- §3.2 ¶electric-range — insert — ambiguity — zero effective consumption (consumption and HVAC both zero) yields `derated_route_range_mi` `0.0` — `calc.py:195-198`
- §2.8 rung 3 — revise — **mismatch** — pass 1's clause claimed a non-object body is always refused; the eleven payload-free POSTs never call `shapes.body()`, so they ignore such a body. Scoped the clause to operations that declare a payload — `commerce.py:112,269,306` (also true of the payload-free routes in `catalog.py`, `plant.py`, `network.py`, `units.py`)

Audited and already correctly pinned (no change): every `calc.py` constant and formula — the six line items and per-line-item 2.375% prep fee, the 0.45%/month linear escalation with date-based month floor, the volume-discount/freight/1.25%-admin four-stage total with its exact ordering, both range families, the nine-item compliance verdict with inclusive boundaries and nonconformance dominance, the 9.5 kN rollover bonus, the award-time raise-never-lower upgrade, liquidated damages (7,500 c/unit/day, 5% cap, min-of-two), dealer standing thresholds (2/4), the `ROLLOVER` test minimum (0.0025 kN/lb, 2 dp), and the required-test set. Every commerce refusal order matches §2.8's ladder exactly. The only ladder divergence found is unreachable: `ERR_SPEC_PROFILE_NOT_FOUND` (rung 4) is checked last on a bid draft, but the solicitation's frozen `spec_profile_id` can never dangle.

### Pass 3 — units, quality, dealer network, cascade engine (`routes/units.py`, `routes/quality.py`, `routes/network.py`, `services/domain.py`)

Subagent summary (verbatim):

- `wc -l` = **532** (unchanged), `wc -c` = **125,596** (inherited 118,328 → **+7,268**, no shrink). §5: **66** `ERR_` rows; tail still ends `| ERR_CLOCK_REWIND_FORBIDDEN | 422 |`. **Did not copy any file.** Earlier passes' edits spot-checked by name and still present: pass 1's `api_request_id` clause (§2.2) and pass 2's solicitation natural-key clause (§3.3). The one-request-one-version-bump rule in §2.9 is intact and the cascade edits are written to be consistent with it.
- **Counts**: 19 ambiguity-pins, 11 mismatch-revisions (30 edits).
- §3.6 — insert — ambiguity — mint recomputes range against the *order's* `spec_profile_id` terrain, which may differ from the bid's — `routes/units.py:44-45`
- §3.6 — insert — ambiguity — `to_status` accepts only `BODY_JOINED`/`BUILT`; other phases are `ERR_INVALID_REQUEST` — `routes/units.py:19,138`
- §3.6 — revise — mismatch — posture recomputation points: eight → **nine** (adds the PASS that clears the last failure) — `routes/quality.py:151`
- §3.7 — insert — ambiguity — window ordering compares full instants; all occupancy compares dates only; endpoints echoed verbatim — `routes/quality.py:40,43-44,78-79`
- §3.7 — insert — ambiguity — scheduling never compares bay `plant_code` with the bus's line plant — `routes/quality.py:25-88`
- §3.7 — insert — ambiguity — a new test's `measured_value`/`recorded_by_user_id`/`recorded_at`/`result_notes` are empty — `routes/quality.py:82-85`
- §3.7 — insert — ambiguity — missing `measured_value` on a measured test is `ERR_INVALID_REQUEST`, evaluated after the 404 but **before** the `SCHEDULED` gate — `routes/quality.py:129-132`
- §3.7 — insert — ambiguity — on an unmeasured test the supplied value is discarded and `measured_value` stays empty — `routes/quality.py:139`
- §3.7 — revise — mismatch — FAIL hop 1: only `PENDING` moves; `NONCONFORMING`, `WAIVED` **and `CERTIFIED`** are all left as-is while later hops still fire — `services/domain.py:257-259`
- §3.7 — revise — mismatch — certify: only `CERTIFIED` has its own refusal (`ERR_UNIT_PHASE_INVALID`); `NONCONFORMING` has no gate and falls to the test checks — `routes/units.py:173-174`
- §3.7 — revise — mismatch — the `WAIVED` path skips the required-test-set check entirely; range/joint/open-failure/segregation/published still apply — `routes/units.py:185-196`
- §3.7 — insert — ambiguity — all three waiver refusals report `ERR_WAIVER_NOT_PERMITTED` in a stated order, and waiving ignores build phase — `routes/units.py:213-219`
- §3.8 — insert — ambiguity — assignment recomputes no dealer figure, so reassigning a delivered bus leaves both `delivered_unit_count`s stale — `routes/units.py:244-246`
- §3.8 — insert — ambiguity — training: empty `dealer_id` matches nobody; re-recording on a `COMPLETED` bus succeeds and still bumps `version` — `routes/units.py:253-256`
- §3.8 — revise — mismatch — delivery has **no** separate refusal for a missing `dealer_id`; the training gate catches it — `routes/units.py:260-271`
- §3.8 — insert — ambiguity — a legacy import's `certified_at` and `waiver_justification` are empty; `delivered_at` echoed verbatim — `routes/network.py:120-123`
- §3.9 — revise — mismatch — scope ordering is date → stored `delivered_at` text → `created_at` → creation order (PRD claimed `created_at` was the only tie-break) — `routes/network.py:221-222`
- §3.9 — insert — ambiguity — hop 1 restamps a bus already `RECALL_OPEN` — `routes/network.py:256-257`
- §3.9 — insert — ambiguity — hop 2 visits each distinct dealer once, in first-appearance scope order — `routes/network.py:258-263`
- §3.9 — revise — mismatch — hop 3 fires on a *worsening* of standing (incl. `RESTRICTED → SUSPENDED`), not on "leaving GOOD"; a `RESTRICTED`→`RESTRICTED` recomputation escalates nothing; `escalated_task_count` is derived over all `FACTORY_DIRECTED` tasks whatever their status — `services/domain.py:193-198,158-160`
- §3.9 — revise — mismatch — dealer figures recomputed at **five** points (adds legacy fleet record); both figures rewritten each time; dealer restamped even if unchanged — `routes/network.py:126`, `services/domain.py:176-192`
- §3.9 — insert — ambiguity — while another task is still open the bus is not restamped at all — `services/domain.py:269-277`
- §3.9 — insert — ambiguity — cancel has no ownership check and leaves `completed_at` empty — `routes/network.py:342-350`
- §3.9 — revise — ambiguity — cancel settles `service_status` by the same open-task rule as completion — `services/domain.py:266-277`
- §2.9 — revise — mismatch — cascade summary: escalation is caused by a dealer's standing moving to a worse band (consistency with hop 3) — `services/domain.py:193-198`
- §2.8 rung 4 — revise — mismatch — `ERR_SPEC_PROFILE_NOT_FOUND` also applies to a legacy fleet record, resolved ahead of model/package/dealer — `routes/network.py:72-75`
- §2.11 — revise — mismatch — **three** sub-resource creations, not two (legacy fleet record) — `routes/network.py:62`
- §2.11 — insert — ambiguity — on a legacy record the body's profile/model/package references outrank the path dealer's 404 — `routes/network.py:72-75`
- §2.11 — revise — ambiguity — parent-identifier list adds `dealer_id` for a legacy import (its `contract_order_id` stays empty) — `routes/network.py:99,103`
- §4 preamble — insert — ambiguity — a 200 returns the resource the path names however wide the cascade (launch → campaign, record-result → test) — `routes/network.py:264`, `routes/quality.py:154`

Residual silence deliberately left (unreachable or unobservable only): (1) `advance_build`'s defensive "no slot in the required status" branch — a `SLOTTED` bus always holds exactly one `COMMITTED` slot and a `BODY_JOINED` bus exactly one `IN_PROGRESS` slot, because committing requires the bus to be `PLANNED`; (2) `recompute_order` clamping `days_late` at zero — an order only breaches once the clock is already past the promise; (3) whether duplicate entries in `licensed_state_codes` are deduped (stored verbatim; only membership is ever consulted); (4) creation-order tie-breaks inside `live_slot_of_unit` and the waiver's void loop (single-element in every reachable state); (5) the exact intra-request order of the four hops in the remedy-task settlement, which the one-bump-per-request rule and the single clock reading make unobservable. Pinning these would add prose without constraining any observable response.

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (`cmp` differs; 94 diff lines, +14,880 chars) — so the scan genuinely ran rather than degrading to a no-op copy.
- Structure intact: 532 lines, all five top-level sections present in order, §5 holds exactly 66 `ERR_` rows, and the file still ends on the `ERR_CLOCK_REWIND_FORBIDDEN | 422` row.
- `implementation/` mtimes are all <= 10:10, i.e. earlier than the 11:42 green sweep — confirming Steps 8 and 9 changed no code, so the 8×110/110 result still describes the shipped implementation. Steps 8/9 were documentation-only, as designed.
- Exactly one `worklog.md` exists, at the task root; no stray copy drifted into `workspace/`.

### Pipeline complete

All nine steps finished. Final artifacts: `SCAFFOLD.yaml` + both design indices, `test_helpers/` (9 files, 2,436 lines), `test_suite/` (16 files + conftest, 95 test functions / 110 collected cases), `workspace/implementation/` (3,006 lines, 63/63 endpoints), `workspace/PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md`, and `results.{1..8}.json` from the final all-green sweep.
