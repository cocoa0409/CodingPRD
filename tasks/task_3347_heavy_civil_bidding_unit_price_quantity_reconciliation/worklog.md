# Worklog — task_3347_heavy_civil_bidding_unit_price_quantity_reconciliation

Scenario: Heavy Civil Bidding & Unit-Price Quantity Reconciliation (Granite Construction)

## Step 1: Create task directory — 2026-10-01T04:34:00.000Z

Task directory `./tasks/task_3347_heavy_civil_bidding_unit_price_quantity_reconciliation/` was pre-allocated by the caller with an empty `workspace/` inside; no index computation and no new directory creation was performed. Verified: `SCAFFOLD*` absent, `workspace/` empty.
## Step 2: Generate Scaffold — 2026-10-01T05:03:00.000Z

All three artifacts are written and lint-clean.

## Files written

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3347_heavy_civil_bidding_unit_price_quantity_reconciliation/SCAFFOLD.yaml` | 2562 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3347_heavy_civil_bidding_unit_price_quantity_reconciliation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1939 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3347_heavy_civil_bidding_unit_price_quantity_reconciliation/SCAFFOLD_CORNER_DESIGN.yaml` | 2654 |

## Counts

- **Entities 10** (Project, BidItem, Bond, Surety, SubcontractorQuote, ProgressMeasurement, QuantityReconciliation, DifferingSiteCondition, EngineerDetermination, SuretyCommitment) · **State machines 10** · **Calculations 10** · **Validations 40** (priority 1–40, all distinct) · **Endpoints 62** · **Errors 41** · **Roles 7** (one `entity_backed:Surety`, identity on every role) · **Concurrency rules 2** (both OCC-only)
- **§1.8: 9 rule groups × 2 instances = 18** (meets every §0.5 minimum)
- **§1.9: 10 sections, 32 active instances + 6 `excluded_because` stubs = 38**

## Profile and key design decisions

Archetype: Ledger reconciliation + Compliance/audit secondary; layers dual-variant calc, rate/threshold triggers, cascading side effects, optimistic concurrency. Segregation-of-duties RBAC, hybrid topology (no strict nesting), parallel state dimensions on Project (`bid_status` × `project_status`).

Difficulty is carried by coupling rather than volume. The three worked mechanisms the task asked for:

- **Cascades C1–C3/C4** — every hop caused by the previous hop: `open-bid` → BidItem SUBMITTED→AWARDED → reconciliation variance recompute → reconciliation money fields → project `contract_value_cents`/`retention_balance_cents` (depth 4); `release-retention` → items CLOSED → project COMPLETE → surety capacity recompute (depth 3).
- **Interdependent numerics** — the statutory `required_bond_cents` (four-tier whole-tier selector) is itself an input to the capacity gate; `net_adjustment_cents` drives `final_contract_value_cents`, which in turn selects the bond tier.
- **Non-obvious precedence** — the dual-failure conflicts are *true* priority inversions, not restatements: e.g. `ERR_RECONCILIATION_NOT_FOUND` (404, priority 10) deliberately wins over `ERR_OPEN_CLAIM_BLOCKS_CLOSEOUT` (422, priority 36) on the same finalize call, and `ERR_SURETY_SUSPENDED` (422, 18) wins over `ERR_BOND_AMOUNT_INSUFFICIENT` (422, 31).

## §1.9 orthogonality

The nine corner sections cover concerns genuinely distinct from §1.8: RBAC ownership/identity boundaries, near-boundary numerics (variance exactly at 15.0 does *not* trigger; one cent over capacity headroom does), error precedence, OCC idempotency/replay, pagination + filter interaction on the measurements list, and interval arithmetic diverging from the bond-coverage rule.

## Hand-off notes for the downstream generator

Two things worth verifying at the Step 6→7 boundary, because both are pinned-by-me literals that a later step could drift:

- **Numeric thresholds are unvalued in the entity tables by design** (`overrun_threshold_pct` default 15.0 is a *default*, not a constant). Test fixtures pin 15.0 explicitly. The formulas' `constants:` blocks (`UPLIFT_PER_EV_POINT_CENTS: 200`, `ANNUAL_PACE_CENTS`, tier percentages) are the authoritative values.
- **`absolute_retention_reconciliation` is deliberately clock-independent.** I dropped any "clock > 2026-10-01" clause so that a fixture at the default clock `2026-09-01T00:00:00Z` still produces the divergent variant value (16666667 vs 100000 for a 2000000-cent gross) — otherwise the corner instance would silently assert the wrong polarity.

Also note the `scaffold_lint.py` report above is the verbatim verdict block; the two design files were last written by a YAML re-dump, so they are valid YAML but their comments were reduced to a single header line each.

### Orchestrator verification note

On-disk check confirms all three files exist with the reported line counts (2562 / 1939 / 2654) and 62 endpoints in SCAFFOLD.yaml. Endpoint count exceeds the ~40 guard: Step 6 output will be verified on disk by the orchestrator rather than trusted from the hand-back.

## Step 3: Copy Shared Files — 2026-10-01T05:04:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3347_heavy_civil_bidding_unit_price_quantity_reconciliation/workspace/INSTRUCTION.md` (1424 bytes). No content modification.

## Step 4: Generate PRD — 2026-10-01T05:09:00.000Z

Output: `workspace/PRD.md` — 434 lines, 93,789 bytes.

Sections: 1 Introduction · 2 Global Specifications & System-Wide Principles (2.1 RBAC, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Evaluation Order and Rejection Precedence, 2.6 The Logical Clock and Time-Dependent Rules, 2.7 Nested Resource Retrieval, 2.8 Measurement Units Money and Rounding, 2.9 Optimistic Concurrency Control, 2.10 Precision and Immutability of Determinations, 2.11 Conservation of Surety Bonding Capacity, 2.12 Response Visibility of Computed Fields) · 3 Business Logic & Workflows (3.1–3.12) · 4 Endpoint Definitions · 5 Error Code Catalogue.

### Orchestrator note on subagent exit

The Step 4 subagent was terminated by the harness with an API error (`model_not_found`, HTTP 404, model sent: `deepseek-v4p1-flash-wave`) and therefore never returned its coverage-audit summary. `PRD.md` was already fully written to disk before the failure: the file ends cleanly with the complete §5 error catalogue table, and an on-disk spot-check confirms the downstream-critical rules are present verbatim in prose —
- logical clock start `2026-09-01T00:00:00Z` (§2.6),
- the nine-band precedence ordering with each band's internal check order (§2.5),
- the four statutory bond tiers with percent 0.50 / 0.75 / 1.00 / 1.25 and whole-tier selection (§3.6),
- `overrun_threshold_pct` / `underrun_threshold_pct` defaulting to 15.0 with range 0.0–100.0 inclusive (§3.1),
- the unbalanced-bid-score four bands with multipliers 1.00 / 1.00 / 1.005 / 1.015 and whole-item band assignment (§3.2).

Coverage-audit note is therefore unavailable from the subagent; the §1.8/§1.9 design indices are withheld from this step by design, so any residual zero-silence gap will surface as a Step 5 instance that fails the PRD-first two-condition filter (skipped, not weakened) and will be reported in the Step 5 and Step 7 summaries.

## Step 5: Generate Unit Tests — 2026-10-01T09:02:33.873678447Z

Generation complete. Both directories are clean, all modules import, and the audit passes.

### Files written

**`test_helpers/`** (1,791 lines)
| File | Lines |
|---|---|
| `__init__.py` | 30 |
| `types.py` | 321 |
| `api_client.py` | 294 |
| `api_errors.py` | 100 |
| `assertions.py` | 142 |
| `constants.py` | 116 |
| `factories.py` | 118 |
| `test_users.py` | 30 |
| `fixtures.py` | 641 |

**`test_suite/`** (2,476 lines) — `conftest.py` (50), `test_01_bid_preparation.py` (437), `test_02_bid_lifecycle.py` (274), `test_03_bonding_capacity.py` (599), `test_04_measurement_ledger.py` (555), `test_05_claims_and_closeout.py` (561).

### Tests emitted

- **Queue A: 36 tests** — all 18 difficulty instances × 2. No shortfalls.
- **Queue B: 32 tests** — all 32 non-stub corner instances × 1. The 6 `excluded_public_surface` stubs were verified to resolve to real difficulty instance names and were **not** translated.
- **Total 68.** Every test carries exactly one `Design:` tag resolving to a real instance; 0 dual/untagged. 152/152 PRD citations pass a literal grep of `PRD.md`. No `skip`/`skipif`/`xfail`, no "scaffold" leakage, no reference to `workspace/implementation/`.

### Instances skipped

**None.** Every instance passed the two-condition filter.

### Contradictions found — design index vs PRD

The implementation generator's own rule is *"PRD wins unconditionally over SCAFFOLD.yaml on any disagreement"*, so I asserted PRD-derived literals wherever the index disagreed. Four drifts, all flagged for the Step 6→7 hand-off:

1. **Bond statutory tiers are 10× apart.** PRD §3.6 sets the tier bounds at 1,000,000 / 5,000,000 / 10,000,000 cents; `calculations.performance_bond_requirement.constants` says 10,000,000 / 50,000,000 / 100,000,000. For a 3,000,000-cent contract the PRD gives a PERFORMANCE requirement of **2,250,000**, not the index's 1,500,000. Affects 4 instances (`performance_bond_tier_selection_feeding_capacity_gate`, `suspended_surety_beats_insufficient_bond_amount`, corner `performance_bond_statutory_requirement_derived_at_creation`, and — fatally — `performance_bond_call_requires_outstanding_lien_claim`, whose 1,500,000-cent bond could not even be issued under the PRD). I used 2,250,000-cent faces, which issue under **both** readings, and asserted the requirement only in the two instances where the tier *is* the subject.
2. **`retention_release_cascade...` asserts `available_capacity_cents == 188000000`.** 188M is the value *before* the bond is issued. PRD §3.12 releases both the commitment and the bond, and §2.11 restores available to the aggregate: the derivable value is **200,000,000** (asserted).
3. **`voiding_payable_measurement_restores_measured_quantity` asserts `renegotiation_required == false`.** With `measured_quantity == 0` and `variance_pct == -100.0`, PRD §3.9's strict comparison (`-100 < -15`) makes it **true** (asserted).
4. **`quote_negotiation_reopens_on_recall` asserts `total_bid_cents == 3000000`.** PRD §3.4 verbatim: *"the project's `total_bid_cents` is reset to 0"* — and the recalled item is DRAFT, so 0 is doubly forced (asserted).

Two corner recipes also carry 10× slips in payable/retention (e.g. `payable_amount_cents == 80000` for 400 units at 2,000 cents); I asserted the PRD-derived 800,000 / 120,000 / 2,400,000.

### Two judgment calls worth knowing

- **`open_claim_blocks_finalize_before_measurement_gap`** is internally inconsistent: its name and `distinguishing_aspect` describe open-claim-vs-pending-measurement precedence, but its `test_recipe` triggers with a bogus reconciliation id and asserts `ERR_RECONCILIATION_NOT_FOUND`. Both readings are PRD-derivable, so I emitted one test for each (precedence per §2.5 band 9, and existence-first per §2.5 band 3).
- **`exact_capacity_boundary_then_one_cent_over_is_rejected`** relies on the available-capacity gate applying to `POST /surety-commitments`; PRD prose states only the interval-intersection rule for commitments. I rebuilt the fixture with commitments only, so the assertion holds under both readings.
- **`performance_bond_issued_and_surety_active_gate_work_start`**: PRD §3.7 states the suspended-surety gate but names no error id there; I cited §2.5's band-6 sentence (which does name `ERR_SURETY_SUSPENDED`) plus §3.7.

### Orchestrator verification note

Step 5 was re-run from scratch after the earlier mid-flight kill (partial `test_helpers/` stashed to `/tmp/step5_partial_3347/`; it lacked `__init__.py` and `test_suite/` was empty). On-disk verification of the fresh run: 15 files, 4,268 total lines matching the hand-back; 68 test functions; 68 `Design:` tags, every one resolving to a real instance in §1.8/§1.9 (0 unresolved, 0 dual-tagged); 36 queue-A / 32 queue-B; 0 `skip`/`xfail`; 0 references to `implementation/`; 0 "scaffold" strings.

Verified the four flagged drift sites against source: the tier tests do assert the PRD-derived 2,250,000 (not the scaffold's 1,500,000), and the cascade/voiding/recall assertions match the PRD-derived 200,000,000 / `True` / 0. One follow-up fix applied by the orchestrator: `test_helpers/constants.py` defined `TIER_1/2/3_MAX_CENTS` with the *scaffold* bounds (10M/50M/100M) while claiming to pin literal values; they were unused by any test but were a live trap for Step 7, so they were corrected to the PRD bounds (1M/5M/10M).

## Step 6: Generate Implementation — 2026-10-01T09:33:46.544762731Z

Implementation complete and verified. Summary:

### Files written (`workspace/implementation/`, 2,974 lines total)

| File | Lines | Role |
|---|---|---|
| `app.py` | 94 | Entry point, 62-route registration table, auth/permission `before_request` band, error handlers |
| `start.sh` | 12 | Guarded `import flask` check, then `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=3.0` |
| `db.py` | 119 | In-memory dicts (empty at boot), logical clock `2026-09-01T00:00:00Z`, id/version stamping |
| `errors.py` | 70 | `ApiError` + full 41-entry error catalog with HTTP codes |
| `util.py` | 162 | `Decimal` ROUND_HALF_UP rounding, ISO-8601 (3 fractional digits), strict body reader, pagination |
| `response.py` | 63 | `meta`/`response_type`/`data` envelope + `limit/offset/total_count/has_more` |
| `calc.py` | 401 | All 11 calculations from scaffold §1.3 |
| `views.py` | 96 | Per-entity serialisation with derived-field recompute on read |
| `services.py` | 369 | Clock, sessions, sureties, commitments, bonds |
| `services_bid.py` | 515 | Projects, pay items, quotes |
| `services_delivery.py` | 407 | Measurements, reconciliations, claims, determinations |
| `routes_admin.py` / `routes_bid.py` / `routes_delivery.py` | 132 / 243 / 290 | Route handlers + role tables |

**Endpoints routed: 62/62** (verified programmatically against `app.ROUTE_META`).

### Launch

`bash start.sh` from `implementation/` — `cd`s to its own directory, installs deps only if `import flask` fails, then `exec python3 app.py` → `0.0.0.0:$PORT` (default 10000), `threaded=True`. No seeding anywhere; a fresh boot yields an empty system (verified live).

### Verification (no pytest)

Booted on free ports, drove ~230 curl/urllib assertions across two suites plus targeted error-path probes, then killed only the exact listener PIDs (`kill <pid>`, no broad patterns). Confirmed: envelope/pagination shape, 401/403 ordering, 400-before-404, 404 band ordering, both OCC guards (412), the seal→open→mobilize cascades, recall/reset unwinding, quote negotiation rounds, bid-shopping, capacity conservation (release restores available to full aggregate), strict ±band boundaries (15.0 doesn't trigger; measured 0 → −100 does), finalized-ledger PAYABLE drop, retention/pace figures, notice clock, determination immutability and duplicate-QA rejection, and the release-retention cascade.

### Judgement calls worth flagging

1. **PRD-internal conflict (bid-total population).** §3.2's narrative ("a priced item does not enter the bid total until it is submitted") plus the `price` endpoint's side-effect list (recomputes only the score, not the extension) conflict with the pinned formula's `SUM_EXCLUDED_STATUSES = {DRAFT}`. I followed the prose: the extension population is `SUBMITTED/AWARDED/ACTIVE/CLOSED`, so `unsubmit` is meaningful. All other rules followed the PRD over the scaffold, including the bond tiers (1M/5M/10M at 0.50/0.75/1.00/1.25), strict variance boundaries, recall resetting `total_bid_cents` to 0, and full capacity restoration.
2. **`lien_claim_amount_cents`** is not defined by any formula; I derived it as the payable amounts of `APPROVED` (approved-but-not-marked-payable) measurements on the project's `PAYMENT` bonds, which makes the `execute` gate reachable only via unpaid work.
3. **Finalize precedence** follows §2.5's band 9 order (renegotiation → open claim → pending measurements), and the renegotiation gate is evaluated on the finalized (APPROVED-only) ledger so §3.8's "requirement can disappear at finalization" holds.
4. **Errors not in the catalog** (seal with an empty/never-priced bid, item close without a FINALIZED reconciliation, missing/non-issued performance bond, duplicate QA finalization) return `ERR_INVALID_STATE` 409; a suspended surety at `start-work` returns `ERR_SURETY_SUSPENDED` 422.

No PRD rule was left unimplemented.

### Orchestrator verification note

Verified on disk (not taken from the hand-back): 14 files / 2,975 lines matching the report; `start.sh` present and correct. No persistence or seeding — the only hits for `sqlite|pickle|json.dump|seed|preload` are the two explanatory comments in `app.py` and `db.py`. Booted `bash start.sh` myself on a free port: the server binds `0.0.0.0:$PORT` and honours `$PORT`; `GET /construction/projects` with no headers returns 401 and with valid headers returns the correct envelope (`data: []`, `total_count: 0`) — confirming an empty store on fresh boot. Route count: 63 Flask rules (the 62 scaffold endpoints plus a health route) and 62 `ROUTE_META` entries; 41 POST + 22 GET operations. Only the exact PIDs I started were killed.

## Step 7: Run Tests and Iterate — 2026-10-01T09:53:23.622387703Z

All 8 rounds pass cleanly. Final state verified: implementation and test source mtimes all precede the sweep; 8 result files on disk, each 68/68 with 0 errors and 0 skipped.

### Summary

**Iterations run:** 2 full 8-round parallel sweeps (plus one single confirmation round between them). Iteration 1 found 12 failures — all deterministic, failing in all 8 rounds, so no flakiness was involved. After the fix batch, a single round confirmed 67/68 (one missed `NameError`), that last fix was applied, and iteration 2's 8-round sweep returned **68/68 in every round**.

**Tests deleted:** none. Every failing test traced to a fixable artifact, so nothing hit the PRD-silence or non-unique-derivability deletion criterion.

**Fixes applied to `test_helpers/`:** none — no fixture was the root cause.

**Fixes applied to `implementation/`** (3 files):
- `/home/ubuntu/github/CodingPRD/tasks/task_3347_heavy_civil_bidding_unit_price_quantity_reconciliation/workspace/implementation/calc.py` — `BID_POPULATION_STATUSES` now includes `PRICED`, per PRD §3.2's pinned population ("every item on the project whose `item_status` is not `DRAFT`"); the impl had followed §3.2's contradicting narrative sentence instead, understating `total_bid_cents`/`contract_value_cents`.
- `.../workspace/implementation/services_delivery.py` — `finalize_reconciliation` evaluated its renegotiation gate on the APPROVED-only population *before* the reconciliation was finalized, so any PAYABLE row plunged variance to −100 and made finalization impossible; the gate now uses the OPEN-phase population (the switch to APPROVED-only happens on successful finalization).
- `.../workspace/implementation/services.py` — `release_bond` looked up the project's *non-closed* reconciliation and required it to be CLOSED, which is unsatisfiable; it now reads the project's latest reconciliation and requires CLOSED.

**Fixes applied to `test_suite/`** (8 edits, 5 files):
- `test_01_bid_preparation.py` — `test_project_creation_applies_declared_defaults`: compare `bid_window_open_at` as a parsed instant. PRD pins the 3-fractional-digit format only for `created_at`/`updated_at`/`api_request_timestamp`, so demanding the bare clock spelling was over-specification; the derivable rule (the instant equals the logical clock at creation) is kept exact.
- `test_01_bid_preparation.py` — `test_bid_item_creation_initialises_computed_fields_to_zero`: `variance_pct` 0.0 → −100.0 and `renegotiation_required` False → True. With no measurements the committed measured quantity is 0, and PRD §3.9's formula gives (0−1000)/1000×100 = −100.0, which crosses the underrun band. The sibling test at `test_04:261` already asserts exactly this pattern.
- `test_02_bid_lifecycle.py` — `test_open_bid_awards_items_and_recomputes_reconciliation_then_project`: same −100.0 correction (the "zero-init" premise contradicted §3.9).
- `test_03_bonding_capacity.py` — `test_performance_bond_tier_selection_feeds_the_capacity_gate`: added the missing `estimator_headers` fixture parameter (NameError; the fixture existed in `conftest.py`, the test just never requested it).
- `test_03_bonding_capacity.py` — `test_exact_capacity_boundary_then_one_cent_over_is_rejected`: removed a dead trailing block that re-read `ctx["surety"]` and duplicated the two assertions immediately above it (`ctx` was undefined — leftover from a rewrite).
- `test_03_bonding_capacity.py` — `test_suspended_surety_beats_insufficient_bond_amount`: read `required_bond_cents` back from `GET /bonds/{id}` after the award. The fixture creates the bond while the project is still SEALED, so the creation snapshot legitimately carries the pre-award requirement (0); the field is computed on read off `contract_value_cents`.
- `test_04_measurement_ledger.py` — `test_stale_bid_item_version_rejects_second_measurement`: dropped the `measured_quantity == 0` side-effect assertion. PRD contradicts itself on whether a DRAFT row counts (§3.8 "anything other than `VOIDED`" vs §3.9 "counts both `APPROVED` and `PAYABLE`"), so the value is not uniquely derivable; the covered OCC assertions (412 / `ERR_STALE_BID_ITEM_VERSION`) are untouched and the ledger-unchanged intent is now expressed as "one row, still DRAFT, quantity 300".
- `test_05_claims_and_closeout.py` — `test_retention_release_cascade_closes_items_project_and_surety`: added the missing `estimator_headers` fixture parameter (NameError).

No `test_helpers/` file was modified, and no PRD-required implementation check was removed or weakened to accommodate a test.

### Orchestrator verification note

Verified independently, not taken from the hand-back: all 8 `results.{1..8}.json` files exist on disk and each reports `passed=68 total=68 errors=0 skipped=0`. Sweep validity confirmed by mtime — the newest implementation/test source file is `test_suite/test_05_claims_and_closeout.py` at 09:49:17 and the newest results file is 09:51:43, so no source write postdates the sweep. Spot-checked fixes against source: `calc.py:28` now reads `BID_POPULATION_STATUSES = ("PRICED", "SUBMITTED", "AWARDED", "ACTIVE", "CLOSED")`; 0 `skip`/`xfail` markers; test count still 68 with 68 `Design:` tags; 0 persistence calls in `implementation/`.

### Sibling unasserted paths handed to Step 8

Because test-side edits (8) outnumber implementation edits (3), the green sweep proves tests match code, not PRD vs code. Three PRD self-contradictions were resolved by the implementation but are only weakly pinned by the current suite:
1. **Bid-extension population** — PRD §3.2's narrative ("a priced item does not enter the bid total until it is submitted") contradicts its own pinned formula's population ("not `DRAFT`"). Impl follows the formula (PRICED included); `unsubmit` is therefore meaningful. Only the open-bid cascade test exercises this.
2. **Measured-quantity population** — PRD §3.8 ("anything other than `VOIDED`") vs §3.9 ("counts both `APPROVED` and `PAYABLE`") disagree on whether a DRAFT row counts. The one test that asserted the difference had its assertion dropped as non-derivable, so the impl's choice is now unasserted.
3. **`bid_window_open_at` serialization format** — PRD pins 3-fractional-digit ISO-8601 only for `created_at`/`updated_at`/`api_request_timestamp`; the impl's spelling for this field is unasserted.

## Step 8: Finalize PRD — 2026-10-01T10:04:54.156445117Z

All edits are applied and verified. Here is the final report.

### Output

`workspace/PRD_FINALIZED.md`

**Size:** PRD.md 434 lines / 93,789 bytes → PRD_FINALIZED.md 434 lines / 95,558 bytes. Line delta **0** (every edit is inline within an existing line); byte delta **+1.89%**. 7 hunks, 29 headings unchanged, no new sections.

### Changes (one bullet per edit)

- **§2.4 Common Resource Properties — insert** — after the `version` sentence, pin that every other instant-valued field (`bid_window_open_at`, `bid_deadline_at`, `bid_open_at`, `measured_at`, `reported_at`, `issued_at`, `reserved_at`, `released_at`, `effective_from`/`effective_to`, `quote_window_start`/`quote_window_end`/`quote_received_at`) uses the same 3-fractional-digit ISO 8601 UTC spelling, and unset instants are `null`. — `implementation/util.py:61` (`fmt_iso`), `implementation/db.py:98` (`public`)
- **§3.2 — revise** — replaced "A priced item does not enter the bid total until it is submitted." with "A priced item enters the bid total as soon as it is priced, because the bid extension's population is every item on the project whose `item_status` is not `DRAFT`." (removes the sentence that contradicted the section's own pinned population). — `implementation/calc.py:28` (`BID_POPULATION_STATUSES`), `calc.py:31`
- **§3.6 (tier paragraph) — insert** — `required_bond_cents` is not a recording-time snapshot: whenever a bond is represented in a response it is recomputed from the project's current `contract_value_cents` (or `total_bid_cents` for bid/maintenance bonds). — `implementation/views.py:45` (`bond_view`)
- **§3.6 (release paragraph) — revise** — "the project's **non-closed** reconciliation has reached `CLOSED`" → "the project's **latest** reconciliation has reached `CLOSED`" (the old wording was unsatisfiable). — `implementation/services.py:353` (`release_bond`)
- **§3.8 (population-variant paragraph) — revise** — OPEN-phase ledger counts every measurement that is not `VOIDED` (`DRAFT`, `APPROVED`, `PAYABLE` alike), so a draft row moves measured quantity/variance immediately; FINALIZED phase drops both `DRAFT` and `PAYABLE`. — `implementation/calc.py:13-14` (`OPEN_PHASE_STATUSES`/`FINAL_PHASE_STATUSES`), `calc.py:75-89`
- **§3.9 (variance paragraph) — insert** — an item with no counted measurements has measured quantity zero, so the formula yields exactly minus 100.00 percent (not zero), crossing the default underrun band and setting the renegotiation flag. — `implementation/calc.py:148-156` (`item_ledger`), `views.py:29`
- **§3.12 (finalization paragraph) — insert** — the renegotiation gate is evaluated while the reconciliation is still `OPEN`, so the OPEN-phase population governs it (a `PAYABLE` row still counts); the switch to `APPROVED`-only happens only after finalization succeeds. — `implementation/services_delivery.py:147-148`, `calc.py:173`/`calc.py:184`

### Per-edit pre-edit search log

**1. §2.4 serialization (Edit F)**
(a) Subject: the wire spelling of every instant-valued field.
(b) Enumerated: `util.fmt_iso`; `db.public` (applies `fmt_iso` to any `datetime`, drops `_`-prefixed keys); `response.request_timestamp`; grepped every datetime producer — `services_bid.py:39,63,115,403,404,421`, `services_delivery.py:26,209,215,233,356`, `services.py:195,224,244,245,317,365`, plus `created_at`/`updated_at` from `db.create`/`db.touch`. Live-probed the running server: project (`bid_window_open_at`/`bid_deadline_at`/`bid_open_at`), measurement (`measured_at`), bond (`effective_from`/`effective_to`/`issued_at`/`released_at`) all render `.000Z`, unset ones `null`.
(c) None. Kept the claim general-but-complete; enumeration matched the grep exactly, so no widening/narrowing was needed.

**2. §3.2 bid-extension population (Edit A)**
(a) Subject: which items contribute to `total_bid_cents`/`contract_value_cents`.
(b) Enumerated: `calc.bid_population`, `items_subtotal_cents`, `total_bid_cents`, `refresh_project_bid`; all writers (`services_bid.py:327,340,353,461,480,498,513`, `seal_bid` 101, `open_bid` 116-118, `recall_bid` 160); `views.project_view:14` (recomputes on every read, so the reported value always follows the population); `routes_bid.project_summary`; `calc.required_bond_cents:271`; `included_items` used by score/variance.
(c) Phrased the population with §3.2's own existing wording ("every item … not `DRAFT`") instead of listing statuses, so it stays true for `unsubmit`, recall, and the `_awarded_value_cents` capture at open-bid; deliberately made no claim about recall's `total_bid_cents = 0` line.

**3. §3.6 `required_bond_cents` read semantics (Edit G)**
(a) Subject: whether a bond's statutory requirement is a snapshot or recomputed.
(b) Enumerated: `calc.required_bond_cents:265-271`, `calc.statutory_pct:255`; `services.create_bond:268`, `issue_bond:303,320`; every bond response route (`routes_delivery.py:48,59,63,69,74,79`) goes through `views.bond_view:42-50`. Live-probed: bond created while SEALED returned `required=0`, the same bond read back after award returned `2250000`.
(c) Wrote "whenever a bond is represented in a response" (not "on read") so write responses, which also pass through `bond_view`, are covered; named both size bases (`contract_value_cents`, `total_bid_cents`) to match the three bond-type branches.

**4. §3.6 ISSUED-bond release (Edit B)**
(a) Subject: the reconciliation condition on releasing an `ISSUED` bond.
(b) Enumerated: `services.release_bond:347-370` (only site); compared against the other `latest_reconciliation` users (`calc.settled_contract_value_cents:70`, `ledger_phase:77`, `views.project_view:17`) and the `non_closed_reconciliation` users (`services_bid.py:127,361`, `services_delivery.py:73,91,371`, `calc.py:370,386`) to confirm "latest" is the right qualifier and is not the same set. Live-probed: release on an ACTIVE project with a FINALIZED reconciliation → `ERR_INVALID_STATE` (COMPLETE checked first).
(c) Chose "latest reconciliation" (creation order via `_seq`), not "the reconciliation" or "the closed one", and left the surrounding "COMPLETE first, then reconciliation" order untouched.

**5. §3.8 measured-quantity population (Edit D)**
(a) Subject: which measurement statuses count toward measured quantity/variance per phase.
(b) Enumerated: `calc.OPEN_PHASE_STATUSES`/`FINAL_PHASE_STATUSES`, `ledger_phase`, `counted_measurements`, `item_ledger`; all consumers (`recalc_item`, `variance_counts`, `net_adjustment_cents`, `views.item_view:29`, `services_bid.close_item:371`, `services_delivery.approve_measurement:56`, `void_measurement:100`, `release_retention:195`); separately checked the *different* retention base `payable_measurements` (APPROVED/PAYABLE) in §3.10. Live-probed: a DRAFT measurement of 300 moved the item to measured 300 / variance −70.0 in the OPEN phase.
(c) Scoped the sentence to "the running ledger" (not the retention base) and added `DRAFT` to both halves of the phase contrast, since the FINALIZED phase excludes `DRAFT` too (a draft row can be created after finalization).

**6. §3.9 zero-measurement variance (Edit E)**
(a) Subject: the variance of an item with no counted measurements.
(b) Enumerated: `item_ledger:148-156` (sum over an empty population is 0 → `(0−est)/est×100 = −100`), and every reader of it (`recalc_item:159`, `variance_counts:169`, `net_adjustment_cents:181`, `views.item_view:29`, `close_item:371`, `release_retention:195`); confirmed `create_item:277` stores 0.0/False but every item response goes through `item_view`. Live-probed: fresh DRAFT item and post-mobilization item both read back `measured 0.0 / variance −100.0 / renegotiation True`.
(c) Qualified the flag consequence with "under the default underrun band" (a band of exactly 100.0 would not cross, since the comparison is strict), and avoided claiming any money moves — `net_adjustment_cents` clamps −100 points to 0 uplift.

**7. §3.12 finalization gate population (Edit C)**
(a) Subject: which measurement population the renegotiation gate tests at finalization.
(b) Enumerated: `services_delivery.finalize_reconciliation:147-154` (explicit `statuses=calc.OPEN_PHASE_STATUSES` over `included_items`), `calc.has_final_renegotiated_rate:193`, and the post-success recomputation chain `refresh_reconciliation:384` → `variance_counts`/`net_adjustment_cents` (default phase → FINALIZED after the status flips). Live-probed end-to-end: with one PAYABLE (300) + one APPROVED (700) row the gate passed (OPEN-phase variance 0.0), and the finalized reconciliation reported `underrun_item_count = 1` from the APPROVED-only population.
(c) Phrased it as a clarification of *when* the gate runs rather than a new rule, and explicitly noted the switch happens only after success, so it cannot be misread as changing the post-finalization counts.

All edits trace to `<step_7_diff>` items: impl fixes in `calc.py` (Edits A), `services_delivery.py` (C), `services.py` (B); test fixes in `test_01`/`test_02` (E, F), `test_03` (G), `test_04` (D); plus the three named sibling paths. The three pure test-bug fixes (`estimator_headers` fixtures, dead block) produced no PRD edit, as they reveal no PRD silence or mismatch. No `SCAFFOLD*.yaml` or `worklog.md` was read; `implementation/` was not modified (verified by mtime).

### Orchestrator verification note

Verified on disk: `PRD_FINALIZED.md` is 434 lines / 95,558 bytes (matching the report), heading count identical to `PRD.md` (no new sections), and `implementation/` has no source file newer than `results.7.json` — Step 8 did not touch the code, so the Step 7 sweep remains valid.

## Step 9: Complete PRD — 2026-10-01T10:29:01.15576409Z

Done. `PRD_COMPLETED.md` is now genuinely patched (the prior attempt was byte-identical; verified with `diff -q` before starting, and the file now differs).

### Source vs result

| | lines | chars |
|---|---|---|
| `PRD_FINALIZED.md` (source, copied to `PRD_COMPLETED.md`) | 434 | 95,558 |
| `PRD_COMPLETED.md` | 434 | 98,483 |

Char delta **+2,912**, line count unchanged, no new headings/sections, error catalogue intact (41 rows). **21 changes: 14 ambiguity-pins, 7 mismatch-revisions.**

### Changes

**Mismatch-revisions**
- §2.6 — revise — mismatch — carrying a quote was listed as violating the pre-deadline rule with `ERR_BID_WINDOW_CLOSED`; the next sentence (and §3.3) said `ERR_QUOTE_AFTER_DEADLINE`. Removed carry from the window-error list and made `ERR_QUOTE_AFTER_DEADLINE` its only pre-deadline error — `implementation/services_bid.py:452-454`
- §3.4 — revise — mismatch — seal's six conditions now state they are tested in the order listed, which refines §2.5's band sequence (impl tests the deadline before the empty-bid/unpriced-item state tests and before the shopping flag, inverting bands 5/6/8) — `implementation/services_bid.py:76-98`
- §3.4 — revise — mismatch — "`total_bid_cents` is reset to 0" is the stored figure only; the returned representation recomputes the extension, so a project still holding priced items reads back their subtotal — `implementation/services_bid.py:160-161`, `routes_bid.py:92`, `views.py:14`
- §3.6 — revise — mismatch — issue-bond check order reordered to surety-`ACTIVE` → overlap → `required_bond_cents` → capacity/single-job, matching §2.5's bands and the code (the old prose listed `required_bond_cents` first) — `implementation/services.py:286-314`
- §3.8 — revise — mismatch — the void guard ("permitted only while the non-closed reconciliation is not `CLOSED`") is **dead code**: `non_closed_reconciliation()` filters out `CLOSED`, so the test can never fire. PRD now says the measurement's own status is the only gate — `implementation/services_delivery.py:91-94`, `calc.py:57-61`
- §3.8 — revise — mismatch — paying is permitted while the project's non-closed reconciliation, *if it still has one*, is `OPEN`; with no non-closed reconciliation the test does not apply — `implementation/services_delivery.py:73-76`
- §3.10 — revise — mismatch — `final_contract_value_cents` is the **awarded** value (captured at bid opening, preserved against the settlement write-back) + net adjustment, not the live `contract_value_cents` — `implementation/calc.py:64-72`, `393-395`

**Ambiguity-pins**
- §2.4 — insert — ambiguity — `version` begins at 1 — `implementation/db.py:68`
- §2.3 — insert — ambiguity — list-filter query-parameter names enumerated; unknown query params ignored — `routes_*.py:_filtered`
- §2.5 — insert ×2 — ambiguity — placed `ERR_UNIT_PRICE_REQUIRED` in band 8 (before `ERR_RATE_BELOW_COST`) and `ERR_CLAIM_NOT_UNDER_REVIEW` in band 5 (after the referential checks) — `services_bid.py:310-312`, `services_delivery.py:343-345`
- §2.12 — insert ×2 — ambiguity — `unavailable_capacity_cents` reports the consumed amount (`calc.py:294-295`, `views.py:57`); the project-summary read answers with a computed 8-key object (`total_bid_cents`, `contract_value_cents`, `unbalanced_bid_score`, `dbe_participation_pct`, `retention_balance_cents`, `overrun_item_count`, `underrun_item_count`, `net_adjustment_cents`) — `routes_bid.py:56-76`
- §3.3 — insert — ambiguity — per-quote `dbe_credit_cents` definition — `implementation/calc.py:318-321`
- §3.6 — insert ×2 — ambiguity — surety registration rules (incl. the unstated `single_job_limit_cents >= 0`) all raise `ERR_INVALID_REQUEST`; `lien_claim_amount_cents` = sum of `payable_amount_cents` of `APPROVED` measurements, zero for non-payment bonds — `routes_admin.py:59-60`, `services.py:133-146`, `calc.py:349-353`
- §3.8 — insert — ambiguity — a DRAFT measurement's applied rate and payable amount both read 0 — `implementation/services_delivery.py:35-42`
- §3.11 — insert — ambiguity — duplicate finalization raises `ERR_INVALID_STATE` (409) — `implementation/services_delivery.py:397-399`
- §3.12 — insert ×3 — ambiguity — the closeout marker is the `closeout_status` field, `NONE` → `PENDING_RETENTION` → `CLOSED` — `implementation/services_delivery.py:127, 167, 187`

### Trap findings

**Dead code (no change made to `implementation/`; read-only there)**
- `services_delivery.py:92` — the void guard is provably unreachable (see above). **Empirically confirmed** by driving the service layer in-process: after the reconciliation reached `CLOSED`, voiding an `APPROVED` measurement succeeded and dropped the item's measured quantity from 1000 → 400; marking an `APPROVED` measurement `PAYABLE` also succeeded and dropped it to 0 (the FINAL-phase ledger counts `APPROVED` only).
- Defined but never called anywhere: `db.refresh()` (`db.py:83`), `db.reset()` (`db.py:114`), `util.optional_int()` (`util.py:129`), `errors.not_found()` (`errors.py:65`), `errors.invalid_state()` (`errors.py:69`), `calc.refresh_project_retention()` (`calc.py:369`).
- Route-level validation shadows service branches that can therefore never fire: `services.create_surety` `aggregate_capacity_cents <= 0` and `single_job_limit_cents < 0`; `services.create_commitment` `committed_amount_cents <= 0`; `services.create_bond` `bond_amount_cents <= 0` and its 1..365 horizon range (all pre-empted by `routes_admin.py:59-60,92` and `routes_delivery.py:43-45`).
- All 62 PRD routes are registered and reachable 1:1 (the apparent route diff is only Flask `<param>` vs PRD `{id}` naming).

**Never-raised error ids:** none. All 41 catalogued ids are raised from at least one reachable code path.

### Orchestrator verification note

The first Step 9 attempt was killed mid-flight by the host session ending, leaving `PRD_COMPLETED.md` byte-identical to `PRD_FINALIZED.md` (`diff -q` clean) — a silent no-op, not a truncated file. Re-ran the step from scratch. Verified the retry on disk: `PRD_COMPLETED.md` is 434 lines / 98,483 bytes (vs FINALIZED's 95,558 — a real +2,925 delta), it DIFFERS from `PRD_FINALIZED.md` across 244 folded diff lines, the heading count is unchanged at 30, the §5 error catalogue still holds 41 rows, and `implementation/` has no source file newer than `results.7.json` — so the Step 7 sweep remains valid.

## Final verification — 2026-10-01T10:31:37.439033145Z

Orchestrator-run confirmation sweep, executed after Step 9 (not inherited from Step 7's run). The previous `results.*.json` were deleted and all 8 rounds were re-run concurrently under `prd-bench-local-run --isolation per-test-server` against the current on-disk state:

```
round 1: passed=68 total=68 errors=0 skipped=0
round 2: passed=68 total=68 errors=0 skipped=0
round 3: passed=68 total=68 errors=0 skipped=0
round 4: passed=68 total=68 errors=0 skipped=0
round 5: passed=68 total=68 errors=0 skipped=0
round 6: passed=68 total=68 errors=0 skipped=0
round 7: passed=68 total=68 errors=0 skipped=0
round 8: passed=68 total=68 errors=0 skipped=0
```

Deliverable structure verified complete: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 modules incl. `__init__.py`), `test_suite/` (conftest + 5 test modules), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, and `workspace/implementation/` with `start.sh` and 8 result files.

Process hygiene: the two stray `python3 app.py` processes on the host were inspected and belong to `task_3350_pre_sale_home_improvement_advance_repayment_closing` — a different pipeline's task — so they were left untouched. No process from this task remains running.

### Pipeline interruptions encountered

Two host-level interruptions occurred during this run; both were handled without losing work:
1. The Step 5 subagent was killed mid-flight on the first attempt, leaving a partial `test_helpers/` (missing `__init__.py`) and an empty `test_suite/`. The partial output was stashed to `/tmp/step5_partial_3347/` and the step was re-run from scratch.
2. The first Step 9 attempt was killed when the host session ended, leaving `PRD_COMPLETED.md` byte-identical to `PRD_FINALIZED.md` — a silent no-op rather than a truncated file. Detected with `diff -q` and the step was re-run from scratch; the retry produced a real +2,925-byte patch.
