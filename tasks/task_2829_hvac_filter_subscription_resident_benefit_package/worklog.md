# Worklog — task_2829_hvac_filter_subscription_resident_benefit_package

## Step 1: Create task directory — 2026-09-05T03:07:40.226Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2829_hvac_filter_subscription_resident_benefit_package` and its `workspace/` subdirectory. Index 2829 was pre-assigned by the caller (no auto-allocation, to avoid collisions with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T04:38:00.000Z

All three scaffold artifacts are complete and lint-clean.

### Output

`/home/ubuntu/github/CodingPRD/tasks/task_2829_hvac_filter_subscription_resident_benefit_package/`

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3101 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1716 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3556 |

`workspace/` and `worklog.md` were left untouched.

### Lint verdict (verbatim)

```
Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  975

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### §1.0–§1.7 shape

13 entities · 11 state machines · 2 concurrency rules · 14 calculations · 30 validations · 62 endpoints · 40 errors · 4 roles. Profile: `ledger_reconciliation` + `workflow_orchestration`, `entity_topology: flat`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers `[dual_variant_calculation, cascading_side_effects, selector_policy, optimistic_concurrency]`, `api_prefix: "/"`. Roles: ProgramOperator, PropertyManager (entity_backed:Property), Resident (entity_backed:Resident), ClaimsAdjuster.

### §1.8 rule ids (9 × 2 = 18 instances)

`dual_variant_calc` 2 · `combinatorial_formula` 2 · `non_linear_state_machine` 2 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 2 · `boundary_precision_check` 2 · `cross_entity_state_dependency` 2 · `resource_temporal_overlap` 2 · `compensating_invariant` 2

### §1.9 sections (73 instances: 57 with `test_recipe`, 16 `excluded_because` stubs)

| Section | Instances |
|---|---|
| entities | 12 |
| state_machines | 16 (11 real / 5 stubs) |
| calculations | 13 (7 / 6) |
| validations | 11 (8 / 3) |
| endpoints | 4 |
| errors | 7 |
| rbac | 4 |
| cross_cutting_complexity_layers | 5 (3 / 2) |
| consistency_model | 1 |

Verified invariants: no duplicate `name` across the union of the two design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name; no stub carries a `test_recipe` and no real instance lacks one; all 40 declared error ids are referenced by at least one instance; `SCAFFOLD.yaml` contains neither design key.

### Deliberate deviations / notes

- The `scenario:` key holds only the domain text ("2829. HVAC Filter Subscription & …") and **omits** the leading directive line "Generate task harder than expert level!". That meta-directive otherwise propagates into `PRD.md` downstream (a known failure mode); difficulty is instead expressed structurally through §1.8.
- Two internal contradictions in `SCAFFOLD.yaml` were repaired while cross-checking recipes: `POST /subscription-transfers/{id}/complete` now posts exactly one signed `TRANSFER_ADJUSTMENT` ledger row (the previous text named `TRANSFER_PRORATION_CREDIT`/`_CHARGE`, which are not members of the `LedgerEntry.entry_type` enum), and validation priority 5 now accepts an optional 1–6-digit fractional second on instants (it previously demanded exactly three digits, contradicting the `2026-08-01T00:00:00Z` clock default used throughout).
- `selector_policy` is used as a `claim_type` in `cross_cutting_complexity_layers`. It is a legitimate §0.2 layer in `SKILL.md` but has no row in `references/claim-extraction-guide.md`'s layer table, so its claim type is taken from the SKILL's layer name rather than the guide.
- Scratch work stayed in `/tmp/task_2829_scaffold/` (exact-`Fraction` verification of every money literal: monthly fee 3546, first-month proration 3088/2364, settlement 2364/1360/1020/1344, write-off cap clamps, transfer nets).

**Orchestrator verification:** all three files present; all parse as YAML; `SCAFFOLD.yaml` has neither design key; `SCAFFOLD_DIFFICULTY_DESIGN.yaml`/`SCAFFOLD_CORNER_DESIGN.yaml` each have exactly one top-level design key. `grep -rn "harder than expert"` over the task dir returns nothing — the difficulty directive did NOT leak into any artifact.

## Step 3: Copy shared files — 2026-09-05T04:39:23.792Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T04:55:00.000Z

PRD complete and all three Hard Contracts verified.

**Output:** `workspace/PRD.md` — **456 lines**, built in 11 incremental `cat >>` heredoc appends (28 → 77 → 115 → 188 → 216 → 236 → 258 → 286 → 304 → 340 → 456), `wc -l` confirmed after each. No `Write` call was used for body text; §2.2 was `cat`-ed from the canonical file so it is byte-identical.

**Sections emitted**
- `# Hvac Filter Subscription Resident Benefits API — Product Requirements Document`
- §1 Introduction (3 paragraphs)
- §2, 11 domain-derived subsections: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (fixed verbatim block) · 2.3 Pagination · 2.4 Record Identity, Auditing Fields and the Logical Clock · 2.5 Nested Reads and Left-to-Right Path Resolution · 2.6 Money, Rounding and Precision Discipline · 2.7 Optimistic Concurrency on Superseding Writes · 2.8 The Two Independent Dimensions of a Subscription · 2.9 Cascade Discipline and Compensating Actions · 2.10 The Order in Which a Request Is Rejected · 2.11 The Property Ledger and the Credit Ceiling
- §3, 9 subsections: 3.1 The Filter Catalog and Its Retirement · 3.2 Properties, Units and the Move-In Measurement · 3.3 Enrolment: Mapping the SKU, Setting the Cadence, Pricing the Subscription · 3.4 Activation and the Start of Billing · 3.5 Fulfilment: Scheduling, Shipping, Delivery and the Return Fork · 3.6 Installation Compliance: Evidence, Cases, Escalation and the Benefit Bundle · 3.7 Claims: Filing, the Review Cycle, Adjudication and Payment · 3.8 Mid-Lease Address Change and Subscription Transfer · 3.9 Cancellation, Settlement and Winding Down
- §4 Endpoint Definitions — intro paragraph + 4-column table (Method | Path | Description | Authorized Role(s)), **62 rows**
- §5 Error Code Catalogue — intro paragraph + 2-column table (Error ID | HTTP Status Code), **40 rows**

**Coverage confirmation** (mechanically checked against the scaffold): 13/13 entities · 62/62 endpoints (every `path` present as a backtick token in §4) · 11/11 state machines, 64/64 transitions · 14/14 calculations · 30/30 validations (§2.10 is a 30-item ordered ladder, each item carrying error id + HTTP status + full `applies_to` scope) · 40/40 errors · 2/2 `concurrency_rules` · 4/4 roles.

**Contract 1: Field-Name Coverage**
```
Field coverage check:
- entities[].fields: 116 required, 116 present, 0 missing
- endpoints[].input (body): 65 required, 65 present, 0 missing
- endpoints[].query_params: 24 required, 24 present, 0 missing
- endpoints[].output keys: 10 required, 10 present, 0 missing
- errors[].id: 40 required, 40 present, 0 missing
- state values: 46 required, 46 present, 0 missing
- enum values: 80 required, 80 present, 0 missing
- roles[].name: 4 required, 4 present, 0 missing
Status: PASS
```
Additionally verified every required name appears as a *standalone* backtick token, not merely as a substring of a compound token.

**Contract 2: Rule Coverage**
```
Rule coverage check:
- validations[] with priority: 30 checked, 30 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 64 checked, 64 fully expressed, 0 missing
- calculations[]: 14 checked, 14 fully expressed, 0 missing
- validations[] conditions: 30 checked, 30 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 62 checked, 62 expressed, 0 missing
- entities[].fields[] structured content: 116 checked, 116 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked, 9 with equal prose density, 0 asymmetric
Status: PASS
```
The 9 symmetry groups: the two `non_install_evidence_score` detection variants; the two `claim_settlement_amount` claim-type variants; the shipment return fork (returned vs. written off); the transfer fork (complete vs. reject); the two compensating pairs (property suspend/reactivate, claim pay/reverse-payment); the two `BenefitEntitlement` suspend/restore arms; the cancellation vs. void terminal arms; the three parallel `monthly_fee_cents` annual components.

**Contract 3: §3 Path Purity**
```
Path purity check (§3 only):
- backtick tokens scanned: 802
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Other precision checks:** 0 occurrences of `>=`, `<=`, `!=`, `==`, `+=`, `-=` anywhere in the document; 0 occurrences of any fuzzy word — I rewrote the four remaining non-quantitative uses of "about" (lines 7, 185, 239, 267) so a mechanical grep for `about|approximate|roughly|conservativ|more or less|neighborhood of` now returns zero. PRD.md ends at §5 with no audit footer; the contract reports live only here. Neither withheld design file was opened, and no sibling task directory was read.

**Notes for downstream:** three scaffold self-contradictions were resolved in favour of the §1.2 state-machine table — Claim reversal targets `PAYMENT_REVERSED`, write-off runs from `RETURN_REQUESTED` only, and resubmit does not recompute `provisional_amount_cents` (a DENY sets `approved_amount_cents` to 0).

**Verbatim `tail -40`** (ends at a real section boundary — the last row of the §5 table, followed by a single trailing newline): last rows are `ERR_TRANSFER_TARGET_INVALID`/422 … `ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED`/402.

**Orchestrator truncation check (per caller's explicit guard):** independently ran `wc -l` (456), dumped all headings (`# … §1 … §2.1–2.11 … §3.1–3.9 … §4 Endpoint Definitions … §5 Error Code Catalogue`) and `tail -6`. The file ends cleanly on the final row of the §5 error table (`| ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED | 402 |`) plus a trailing blank line — a real section boundary, NOT mid-sentence. No regeneration needed. A grep for `harder than expert|SCAFFOLD|difficulty_design|corner_design|test_recipe` over PRD.md returns nothing, so neither the difficulty directive nor any test-index vocabulary leaked into the contract.

## Step 5: Generate unit tests — 2026-09-05T06:01:00.000Z

Test infrastructure for `task_2829` is complete. Both output directories are at the task root (`/home/ubuntu/github/CodingPRD/tasks/task_2829_hvac_filter_subscription_resident_benefit_package/`); nothing was written under `workspace/`.

### Files written

`test_helpers/` (Stage 1, 1704 lines total — unchanged this session, import-verified)
`__init__.py` 27 · `constants.py` 163 · `api_errors.py` 146 · `types.py` 201 · `test_users.py` 90 · `api_client.py` 311 (62 endpoint methods) · `assertions.py` 234 · `factories.py` 271 · `fixtures.py` 261

`test_suite/` (4262 lines, 94 tests)
`conftest.py` 41 · `test_01_dual_variant_calculations.py` 231/4 · `test_02_combinatorial_formulas.py` 207/4 · `test_03_non_linear_state_machines.py` 264/4 · `test_04_transitive_cascades.py` 206/4 · `test_05_validation_priority_conflicts.py` 176/4 · `test_06_boundary_precision.py` 208/4 · `test_07_cross_entity_state_dependencies.py` 225/4 · `test_08_resource_temporal_overlap.py` 183/4 · `test_09_compensating_invariants.py` 242/4 · `test_10_entity_contracts.py` 359/12 · `test_11_state_transitions.py` 516/11 · `test_12_calculation_corners.py` 395/7 · `test_13_validation_corners.py` 400/8 · `test_14_endpoint_corners.py` 271/4 · `test_15_error_corners.py` 376/7 · `test_16_rbac.py` 266/4 · `test_17_concurrency_and_selector.py` 266/4 · `test_18_consistency.py` 78/1 (lines/tests)

### Counts and audit result

- **Queue A (Difficulty): 36 tests** covering **18/18** instances (4 per rule id).
- **Queue B (Corner): 58 tests** covering **57/57** non-stub instances (every instance ≥1 test; `selector_eligibility_predicate_and_created_at_tie_break` got 2 so eligibility and the tie-break each carry their own citation).
- **Design-tag audit: clean.** All 94 tests carry exactly one `Design:` line, it is the last line of the docstring, and every tag resolves to a real `name:` in the source yaml (18 difficulty names, 57 of the 73 corner names — the other 16 are stubs).
- **Citation audit: clean.** Exactly one `PRD §x.y: "..."` per test, all 94 quoted strings survive a literal substring match against `workspace/PRD.md`.
- **Stub cross-references: clean.** All 16 `excluded_because.difficulty_instance` values resolve to real §1.8 instance names; no tests emitted for them.
- **Static checks:** all 18 modules import successfully; every `api.*`, `a.*`, `f.*`, `fx.*` attribute referenced exists; no unused imports; no "scaffold"/"§1.x"/"Table N" vocabulary anywhere in emitted code.

### Instances skipped / assertions dropped (design-vs-PRD conflicts)

No instance was skipped wholesale. Six individual design assertions were dropped as non-derivable rather than weakened:

1. `returned_shipment_accepts_no_further_trigger` — design says `unreturned_fee_cents == null`; PRD §3.5 says the RETURNED arm "leaves `unreturned_fee_cents` at 0". Asserted 0.
2. `property_offboard_pushes_every_unit_out_of_service` — design says "unit_count is still 2"; §2.11 defines `unit_count` over AVAILABLE-or-OCCUPIED units only, so after offboarding it is not 2. Assertion omitted.
3. `first_month_fee_prorates_the_activation_month_inclusively` — design pins `period_start`/`period_end` on the MONTHLY_FEE row; PRD pins those only for one-off rows. Omitted.
4. `logical_clock_default_and_repointing_drive_every_temporal_read` — design asserts `Subscription.first_month_fee_cents`; that field name appears nowhere in PRD.md. Replaced with the MONTHLY_FEE ledger amounts (3546 at the 2026-08-01 default, 2364 after repointing to 2026-09-11), which §3.4 does derive.
5. `request_missing_x_user_id_header_rejected` — the unrecognised-role probe (`Warehouse` → 403) is genuinely ambiguous: PRD §2.1 says an unrecognised role is `ERR_ROLE_NOT_PERMITTED` (403) while §2.10 rule 1 folds "`X-User-Role` one of the four role names" into `ERR_UNAUTHENTICATED` (401). Probe omitted; the four derivable absent/empty-header 401s plus the priority-1-before-priority-3 probe are asserted instead.
6. `stale_expected_subscription_version_on_transfer_create_returns_412` — design advances the parent version with a renewal survey, but §3.6 says a survey "transitions nothing on its own" and never states it bumps `Subscription.version`. Used a manual shipment schedule instead (§3.5 advances `shipment_sequence_counter`, so §2.4's per-mutation increment applies): stale token 2, fresh 3, post-create 4.

One data-quality substitution also required a setup change: `selector_eligibility_predicate_and_created_at_tie_break` needs an observable `created_at` ordering between two otherwise-identical SKUs, which a frozen logical clock cannot produce — the two tied rows are now registered on successive clock days (2026-08-01 and 2026-08-02).

**Orchestrator verification:** `test_helpers/` (9 files) and `test_suite/` (19 files) both landed at the TASK ROOT; `find workspace/ -name "test_*" -o -name conftest.py` returns nothing, so the known "test dirs written under workspace/" failure did not occur. No stray worklog.md anywhere but the task root.

## Step 6: Generate implementation — 2026-09-05T06:01:00.000Z

The implementation is complete.

### Files written — `workspace/implementation/`

| File | Lines | Role |
| --- | --- | --- |
| `start.sh` | 10 | guarded launcher (`if ! python3 -c "import flask"` → pip, then `exec python3 app.py`), executable |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 57 | blueprint registration, `ApiError`/`HTTPException` handlers, `0.0.0.0:$PORT` (default 10000) |
| `calc.py` | 473 | every pinned calculation (SKU selection, cadence, fee, evidence scoring, settlement waterfall, transfer proration, claim variants) |
| `services.py` | 206 | cascades A/B/C side-effect bundles, void/settle, occupancy + residency cascades |
| `guards.py` | 177 | ladder rungs 1–4 and 6 (auth, RBAC, 404 getters, ownership, pagination) |
| `validate.py` | 125 | rung 5 shape validation |
| `clock.py` | 88 | logical clock, default `2026-08-01T00:00:00Z`, 3-fractional-digit ISO instants |
| `store.py` / `errors.py` / `views.py` / `ledger.py` / `envelope.py` / `money.py` | 66/66/60/50/49/25 | in-memory dicts + `_seq` tie-break, 40-error catalogue, serialization with derived fields, append-only ledger + credit ceiling, envelope helpers, exact `Fraction` money with half-up-away-from-zero rounding |
| `routes/subscriptions.py` | 430 | 14 endpoints |
| `routes/claims.py` | 239 | 10 |
| `routes/transfers.py` | 223 | 6 (incl. cascade C) |
| `routes/properties.py` | 178 | 9 |
| `routes/shipments.py` | 141 | 7 |
| `routes/units.py` | 101 | 4 |
| `routes/cases.py` | 97 | 5 |
| `routes/catalog.py` | 57 | 3 |
| `routes/residents.py` | 47 | 2 |
| `routes/clock_route.py` / `entitlements.py` / `__init__.py` | 18/17/0 | 1 / 1 |

3001 lines total. No seeding anywhere (store is pure in-memory dicts, empty at import); no disk/SQLite/tmp state; `__pycache__` cleaned.

### Endpoint coverage

**62 / 62.** Flask's URL map enumerates exactly 62 non-static rules, matching the PRD §4 table path-for-path.

### Smoke test (PORT=18829, killed by explicit PID only)

Booted via `bash start.sh`, then two end-to-end scripts (44 + 20 assertions) exercised: clock set, catalog, property → units → activate, resident, enrolment (derived cadence 30 / 2 filters / fee 6679 / 4 benefit codes), activation (ENROLLMENT_FEE 2500 + prorated MONTHLY_FEE, shipment #1, entitlements ACTIVE), ship/deliver/request-return/write-off, telemetry ingest, RUNTIME_ANALYTICS evaluation → send-notice → confirm (cascade A), renewal survey, cadence-window overlap rejection (409) then a legal date (201), settlement preview (`waiver_credit_pct` as the decimal string `"0.25"`, frozen field as number `0.25`), transfer open → remap → complete (successor minted ACTIVE with `predecessor_subscription_id`, single `TRANSFER_ADJUSTMENT`, origin unit released, resident stays `RESIDING`), claim file → triage (provisional 30000) → segregation-of-duties 422 → decide → pay → reverse-payment (property balance returned to its exact pre-payout value, 9179 → −20821 → 9179, zero drift), cancellation settlement + entitlement expiry + unit/resident cascades, plus negative paths: bad enum 400, `limit=0` → `ERR_INVALID_PAGINATION` 400, bad role → `ERR_UNAUTHENTICATED` 401, unknown id 404, stale `expected_unit_version` → 412. All assertions passed; server stopped by killing only its own PID (port confirmed free).

Notable PRD-over-scaffold decisions kept: write-off only from `RETURN_REQUESTED`; `resubmit` does not recompute `provisional_amount_cents`; DENY sets `approved_amount_cents = 0`; reverse target is `PAYMENT_REVERSED`; ladder order in §2.10 governs where it conflicts with §3 prose (rung 20 before 26 on remap; rung 22 before 25/26 on transfer open, with the moving subscription excluded from its own occupancy test); undeclared request fields (`return_reason`, `question`, `decision_note`, `withdraw_reason`) are stored on internal `_`-prefixed keys so they never leak into responses.

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single message, so the impl generator had physical isolation from `test_suite/` (the directory did not exist when it started).

## Step 7: Run tests and iterate — 2026-09-05T06:20:00.000Z

Clean sweep on iteration 2. Summary below.

### Iterations run
2.

**Iteration 1**: 89/94 in all 8 rounds — 5 failures, identical and deterministic in every round (no flakiness, no load-induced timeouts, no `Terminated` server logs).

### Tests deleted
None. No failing test asserted a rule on which the PRD is silent; all five traced to verbatim PRD prose. Two assertions inside otherwise-covered tests were relaxed for non-unique-derivability (below).

### Fixes applied to `implementation/`

1. `workspace/implementation/routes/subscriptions.py` — `schedule_shipment()`: added `touch(sub)` after the shipment is minted. PRD §3.5 has scheduling advance the subscription's `shipment_sequence_counter`, and §2.4 says `version` "increments by exactly 1 on every mutation of that record" — the counter was being advanced without the version bump, so a client's version token never went stale. (Deliberately not put inside the shared `create_shipment()` helper, because activation is "one atomic step" per §3.4 and already bumps once.)
2. `workspace/implementation/services.py` — `settle_and_cancel_subscription()`: the frozen `waiver_credit_pct` was stored as `float(...)`; now `calc.pct_string(...)`. §3.9 names exactly one representation for that field, "a decimal string, one of `0.00`, `0.25`, `0.50` or `0.75`", and §2.6 bans floating-point money fields. The preview route already used `pct_string`; only the frozen copy diverged. (Left the creation-time initial value as `0` to match §3.3's "all start at 0" literally; no test covers it.)

### Fixes applied to `test_suite/`

3. `test_suite/test_13_validation_corners.py` — `test_a_transfer_is_refused_unless_the_destination_unit_is_available`: the fixture made the destination unit OCCUPIED by a subscription whose lease (2026-08-01…2027-07-31) is identical to the transferring subscription's, so the destination violated **both** ladder rung 22 (`ERR_UNIT_OCCUPANCY_CONFLICT`) and rung 26 (`ERR_TRANSFER_TARGET_INVALID`). §2.10 fixes 22 above 26, so the PRD-faithful implementation correctly answered the occupancy conflict. Gave the occupant a lease of 2027-08-05…2028-07-31, which clears the incoming lease by more than the three-day turnover buffer — the unit is still OCCUPIED, but only rung 26 is now violated, isolating the gate under test. Setup fix; the assertion (exact `error_id`) was left untouched.
4. `test_suite/test_12_calculation_corners.py` and `test_suite/test_17_concurrency_and_selector.py` — three `validate_success(api.capture_filter_size(...), 201)` calls changed to `get_success_data(api.capture_filter_size(...))` (any 2xx). **Non-unique-derivability, format-silence pattern**: §4 pins 201 only for endpoints that "create a new resource", and §2.4 exhaustively enumerates the 13 persisted record types — there is no `FilterSizeCapture` among them, no GET for one, and no `ERR_..._NOT_FOUND` code for one. §3.2 describes the capture purely as overwriting the *unit* and incrementing its `size_capture_count`, and the implementation accordingly returns the updated Unit with 200 ("every other successful call answers with HTTP 200"). Both 200 and 201 are PRD-faithful readings, so the status pin was dropped; every observable effect of the capture (`actual_measured_size_code`, `size_capture_count`, unit `version`, the SKU remap on the live subscription) is still asserted, and the 412 stale-token assertions the tests exist for are untouched. Scaffold rules that drove these: `Corner/calculations/unreturned_fee_clamps_at_the_cap_and_reads_the_shipment_sku_snapshot` and `Corner/cross_cutting_complexity_layers/stale_expected_unit_version_on_size_capture_returns_412`.

No assertion was weakened to an HTTP-status check, no `error_id` was downgraded, no skip/xfail was added, and no PRD-required implementation check was removed.

### Final sweep evidence
All 8 parallel rounds, read from `workspace/implementation/results.$i.json`:

| round | passed/total | failed | errors | skipped |
|---|---|---|---|---|
| 1 | 94/94 | 0 | 0 | 0 |
| 2 | 94/94 | 0 | 0 | 0 |
| 3 | 94/94 | 0 | 0 | 0 |
| 4 | 94/94 | 0 | 0 | 0 |
| 5 | 94/94 | 0 | 0 | 0 |
| 6 | 94/94 | 0 | 0 | 0 |
| 7 | 94/94 | 0 | 0 | 0 |
| 8 | 94/94 | 0 | 0 | 0 |

`worklog.md` was not created, edited, or appended to.

**Orchestrator verification (per the "verify Step 7 sweep artifacts" rule):** independently listed and JSON-parsed all 8 `results.$i.json` files in `workspace/implementation/`. All 8 exist and each reports `passed: 94, failed: 0, total: 94, errors: 0, skipped: 0`. The clean sweep is real, not a subagent claim. Step 7 applied 2 `implementation/` fixes, so the Step 8 skip condition does NOT apply — Step 8 runs.

## Step 8: Finalize PRD — 2026-09-05T06:26:00.000Z

Done. Three surgical edits to `PRD_FINALIZED.md`; two Step 7 items produced no PRD change.

### Line counts / delta
- `PRD.md`: 456 lines, 101,294 bytes
- `PRD_FINALIZED.md`: 456 lines, 102,049 bytes
- Delta: 0 lines (+0.00%), +755 bytes (+0.75%); 3 lines revised in place, 0 inserted, 0 deleted, no new sections.

### Changes
- **§3.2 (move-in measurement)** — revise — pinned that a filter-size capture persists no record of its own, is therefore not a create despite its collection-shaped path, and answers HTTP 200 returning the updated `Unit` in `data` — `implementation/routes/units.py:61` (default-200 `object_response(views.unit_view(unit))`).
- **§3.5 (scheduling a shipment)** — revise — pinned that advancing `shipment_sequence_counter` also increments the subscription's own `version` by exactly one, on top of the shipment's `version` 1 — `implementation/routes/subscriptions.py:345` (`touch(sub)`).
- **§3.9 (freezing the settlement figures)** — revise — pinned the persisted representation: four whole-cent integers, `waiver_credit_pct` as the same decimal string the preview reports (`0.00`/`0.25`/`0.50`/`0.75`), and the integer `0` retained on any path that runs no settlement — `implementation/services.py:184` (`calc.pct_string(...)`), `implementation/calc.py:308`.
- **Step 7 items 3 and 4 (test-side only)** — no PRD change. Item 3 was a pure fixture bug: `implementation/routes/transfers.py:48-58` evaluates occupancy (rung 22) → date (25) → target (26), exactly the §2.10 order already in the PRD. Item 4's status relaxation is covered by the §3.2 edit above.

### Per-edit pre-edit search log

**Edit A — §3.2 capture response**
- (a) Subject: response status/body of `POST /units/{id}/filter-size-captures`, and whether a capture is a persisted record type.
- (b) Enumerated/read: `routes/units.py:27-61` (capture handler, returns `views.unit_view`, no status arg); `envelope.py:object_response` (default 200); `views.py:unit_view`; `store.py:Store.__init__` (no captures collection — 13 collections, none for captures); `grep "@bp.(post|get)"` across all of `routes/` (no GET for a capture, no `ERR_..._NOT_FOUND` for one); `grep -rn "201"` across `implementation/` — the eleven 201 sites are all genuine row creates (`/properties`, `/properties/{id}/units`, `/residents`, `/filter-skus`, `/subscriptions`, `/subscriptions/{id}/shipments`, `/subscriptions/{id}/renewal-surveys`, `/subscriptions/{id}/non-install-evaluations`, `/units/{id}/runtime-readings`, `/claims`, `/subscription-transfers`); every other POST is verb-shaped and returns 200, so the capture is the only collection-shaped POST at 200.
- (c) Adjustment: scoped the sentence to the capture rather than stating a general "no-record-persisted ⇒ 200" rule, and kept §4's existing 201/200 sentence untouched so the eleven real creates are not re-described.

**Edit B — §3.9 frozen `waiver_credit_pct`**
- (a) Subject: the stored representation of `waiver_credit_pct` (and of the other four frozen settlement figures) on a `Subscription`.
- (b) Enumerated/read: `routes/subscriptions.py:76` (`build_subscription` initialises the field to integer `0`); `services.py:179-191` (`settle_and_cancel_subscription` → `calc.pct_string`); `services.py:170-176` (`void_subscription` — never writes the field); `routes/transfers.py:200-214` (transfer-driven cancellation — never writes it either, so it stays integer `0`); `routes/subscriptions.py:228-245` (preview route, also `pct_string`); `calc.py:301-309` (`waiver_credit_pct` returns a `Fraction`; `pct_string` is `"%.2f"`); `calc.py:312-336` + `money.py:round_half_up` (the four cent figures are Python ints); `store.py:public` (raw value serialised, no coercion); `views.py:subscription_view`.
- (c) Adjustment: an unqualified "frozen as a decimal string" would have mis-described the enrolment-time value and both no-settlement cancellation paths, so I added the explicit carve-out "on any path that runs no settlement at all `waiver_credit_pct` keeps the integer `0` it was created with", and left §3.3's "all start at 0" verbatim.

**Edit C — §3.5 subscription `version` on scheduling**
- (a) Subject: which rows have `version` incremented when a shipment row is minted.
- (b) Enumerated/read: `routes/subscriptions.py:149-164` (`create_shipment` — bumps the counter, does not `touch(sub)`); `routes/subscriptions.py:342-345` (schedule endpoint — `touch(sub)` after the mint); `routes/subscriptions.py:186-198` (activation — `touch(sub)` once, then `create_shipment`, i.e. exactly one bump for the whole atomic step); `routes/units.py:53-60` (capture repricing writes subscription fields *without* `touch`); `services.py:14-26` (cascade shipment transitions touch shipments only); `routes/transfers.py:209-214` (completion touches the outgoing sub once); `store.py:touch`.
- (c) Adjustment: scoped the sentence to "this operation" (the scheduling endpoint of §3.5) instead of "every time a shipment is created", so activation's single atomic bump (§3.4) is not implied to be two, and so the capture path's deliberate no-bump on repriced subscriptions is neither contradicted nor generalised from.

**Orchestrator verification:** `PRD_FINALIZED.md` exists, 456 lines / 102,049 bytes, and `diff` against `PRD.md` shows exactly 3 revised lines (6 diff lines) — not byte-identical, so the finalizer really ran. File ends cleanly on the last row of the §5 error table.

## Step 9: Complete PRD — 2026-09-05T06:55:00.000Z

Step 9 was deliberately run as **three sequential passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module**, rather than as a single subagent. A single agent cannot hold 3001 lines of implementation plus a 456-line PRD and still do an exhaustive behavior-by-behavior scan; the known failure mode is that it emits a byte-identical copy. Pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying, and each pass was told the other passes' file slices and PRD footprints so the three interlock instead of colliding.

### Pass 1 of 3 — cross-cutting core (`app.py`, `envelope.py`, `store.py`, `errors.py`, `views.py`, `money.py`, `clock.py`, `routes/clock_route.py`, `guards.py`, `validate.py`, `ledger.py`)

`cp workspace/PRD_FINALIZED.md → workspace/PRD_COMPLETED.md` done first. 456 lines / 102,049 chars → 458 lines / 106,150 chars, **+4,101 chars**, 11 diff hunks, all inside §2.1–§2.5, §2.11 and the §5 preamble.

**10 ambiguity-pins, 2 mismatch-revisions:**
- **§2.1** — revise — mismatch — an unrecognised `X-User-Role` value yields `ERR_UNAUTHENTICATED` (401), not `ERR_ROLE_NOT_PERMITTED` (403); only a *recognised* but unauthorised role gets 403. — `guards.py:18-19`
- **§2.1** — revise — mismatch — the universal "narrowing applies to every endpoint whose role list includes PM/Resident" was false; narrowed to resources that actually carry the scoping FK (SKUs and `Resident` records are read unnarrowed by a PropertyManager), and pinned that the three top-level lists silently restrict the result set and `total_count` instead of rejecting, while nested lists keep the 403. — `guards.py:107-125`, `routes/subscriptions.py:141-142`, `routes/shipments.py:41-43`, `routes/transfers.py:100-102`, `routes/residents.py:46`, `routes/catalog.py:44`
- **§2.2** — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum characters. — `envelope.py:9,18`
- **§2.2** — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall-clock, so it is identical across responses until the clock is repointed. — `envelope.py:24`
- **§2.3** — insert — ambiguity — a supplied `limit`/`offset` that is not an optionally minus-signed digit run is `ERR_INVALID_PAGINATION`. — `guards.py:131-142`
- **§2.3** — insert — ambiguity — every ordering takes ascending server insertion order as its final tie-break, and that ordinal never appears in a payload. — `store.py:43,57-59,63`
- **§2.3** — insert — ambiguity — FK-named filters are compared literally and never existence-checked; undefined query parameters are ignored. — `guards.py:168-172`
- **§2.4** — revise — ambiguity — the clock endpoint accepts any instant (backwards included) and answers 200 with an object whose only field is `current_utc`, mutating no record and no `version`. — `routes/clock_route.py:16-18`, `clock.py:66-68`
- **§2.4** — insert — ambiguity — JSON `null` ≡ absent at the body-shape rung; a bodyless request reads as `{}`; an unparseable or non-object body is `ERR_INVALID_REQUEST` 400; undeclared properties ignored; declared fields checked in document order, first problem wins. — `validate.py:16-28`
- **§2.5** — insert — ambiguity — a body FK field that is absent, `null`, or not a string resolves to nothing and surfaces as that referent's 404, not `ERR_INVALID_REQUEST`. — `guards.py:35`, `routes/subscriptions.py:91-92`, `routes/transfers.py:33-34`, `routes/claims.py:41`
- **§2.11** — revise — ambiguity — ledger listing order gains its actual third key: `created_at`, then `period_start`, then insertion order. — `calc.py:194`
- **§5** — insert — ambiguity — two transport-level failures reuse `ERR_INVALID_REQUEST` with a non-400 status: undefined path → 404 (trailing slash tolerated), undefined method → 405. — `app.py:33-46`, `app.py:24`

Verified-consistent, no change needed: the 40-entry §5 status table matches `errors.py` exactly; `money.round_half_up` matches §2.6's away-from-zero wording; §2.4's "exactly three record types lack `updated_at`/`version`" matches the three `base_record(with_version=False)` call sites; §2.3's per-endpoint filter inventory matches every `guards.pagination(...)` call; §2.11's balance formula, `<= credit_limit_cents` comparison and both ceiling preconditions match `ledger.py:41-50`.

### Pass 2 of 3 — `calc.py`, `services.py`, `routes/catalog.py`, `routes/properties.py`, `routes/units.py`, `routes/residents.py`, `routes/subscriptions.py`

458 lines / 106,150 chars → 458 lines / 112,372 chars, **+6,222 chars**, 0 line delta (every change an in-paragraph insert or revision). md5 confirmed changed and distinct from `PRD_FINALIZED.md`; 32 surgical `Edit` calls, no `cp`, no wholesale write.

**20 ambiguity-pins, 11 mismatch-revisions:**
- §3.1 — insert — ambiguity — `sku_code` collision answers `ERR_INVALID_REQUEST`, tested only after every declared field passed its own shape check; `size_code` separator pinned as lower-case `x` — `routes/catalog.py:25-27`, `validate.py:10`
- §3.1 — insert — ambiguity — retiring an already-`DISCONTINUED` SKU is `ERR_SKU_DISCONTINUED` (422) — `routes/catalog.py:53-54`
- §2.10 rule 19 — revise — mismatch — the "exactly two operations" claim now records that the id is also reused outside the ladder by §3.1 retirement — `routes/catalog.py:54`
- §2.10 rule 8 — revise — mismatch — the "exactly three operations" claim now records reuse by the four §3.2 property-lifecycle actions — `routes/properties.py:79-128`
- §2.10 rule 16 — revise — mismatch — "two telemetry readings inside the evaluation window" → "in the evidence set §3.6 defines", since `evaluated_through_date` filters nothing — `routes/subscriptions.py:391`, `calc.py:370-378`
- §3.2 — insert — ambiguity — units may be added at any property status including terminal `OFFBOARDED`; duplicate `unit_label` is `ERR_INVALID_REQUEST` after shape checks — `routes/properties.py:151-165`
- §3.2 — insert — ambiguity — `suspend_reason` is a required string with no declared length bound — `routes/properties.py:95`
- §3.2 — insert — ambiguity — all four lifecycle actions report a wrong-status property as `ERR_PROPERTY_NOT_ACTIVE` (409), as do `unit_count` 0 on activation and a live-subscription-blocked offboarding; shape validation precedes that test — `routes/properties.py:79-128`
- §3.2 — insert+revise — mismatch — the measurement's re-derivation excludes the benefit set, and the unit's `version` is the only counter it advances: no affected subscription's `version` or `updated_at` moves — `routes/units.py:50-60`, `calc.py:252-264`
- §3.2 — insert — ambiguity — telemetry `window_start`/`window_end` stored and echoed at three fractional digits, sub-millisecond parts truncated — `routes/units.py:83-84`, `clock.py:15-20`
- §3.2 — insert — ambiguity — a missing `@` and an email collision are both `ERR_INVALID_REQUEST`, uniqueness tested last — `routes/residents.py:20-28`
- §3.3 — insert — ambiguity — `lease_end <= lease_start` is `ERR_INVALID_REQUEST`; lease dates unconstrained relative to the logical clock — `routes/subscriptions.py:98-100`
- §3.3 — revise — mismatch — "two occupancy guards run before any arithmetic" was wrong: they run after SKU selection, so `ERR_NO_ELIGIBLE_SKU` precedes rules 21/22 — `routes/subscriptions.py:105-114`
- §3.3 — revise — mismatch — "creation time is the final tie-break" → `created_at` then the §2.3 insertion-order tie-break; the id is never consulted — `calc.py:100-101`
- §3.3 — insert — ambiguity — entitlement rows are inserted in ascending `benefit_code` order — `routes/subscriptions.py:119-120`
- §3.3 — revise — mismatch — rewrote the re-derivation-trigger sentence: measurement re-runs SKU→cadence→qty→fee only; remap re-runs selection alone and stores it on the transfer; the successor gets the whole chain with the SKU fixed; confirmed non-install re-derives the fee alone — `routes/units.py:50`, `routes/transfers.py:119-125,172-181`, `services.py:161-163`
- §3.4 — revise — mismatch — the ceiling test additionally requires `billing_mode == PM_BILLED` — `ledger.py:45-49`
- §3.4 — insert — ambiguity — `ENROLLMENT_FEE` is a one-off (both period edges = activation date); `MONTHLY_FEE` runs activation date → last day of that month — `routes/subscriptions.py:193-198`
- §3.4 — revise — mismatch — activation's "four things" reordered to ladder order (property `ACTIVE` before subscription `PENDING_SETUP`) — `routes/subscriptions.py:172-179`
- §3.5 — revise+insert — mismatch — scheduling requires `ACTIVE` (not merely "live"); `scheduled_ship_date` unconstrained vs the clock; `tracking_code` optional/null; every shipment born with `shipped_at`/`delivered_at`/`returned_at` null and `unreturned_fee_cents` 0 — `routes/subscriptions.py:149-164,320-326`
- §3.6 — revise — mismatch — a renewal survey requires `ACTIVE` or `SUSPENDED` — `routes/subscriptions.py:358`
- §3.6 — revise+insert — mismatch — evaluation requires `ACTIVE`/`SUSPENDED` and a posture that is not `NON_INSTALL_CONFIRMED`; `evaluated_through_date` is required but filters nothing — `routes/subscriptions.py:391-397`
- §3.6 — revise — mismatch — the observation span is measured to whole seconds, then carried as an exact day fraction — `calc.py:386-388`
- §3.6 — insert — ambiguity — an evaluation answers 201 with the new case row in `data` — `routes/subscriptions.py:433`
- §3.6 — insert — ambiguity — posture legality after scoring: suspect allowed from `UNVERIFIED`/`COMPLIANT`/`NON_INSTALL_SUSPECTED` (not `REMEDIATED`), clear allowed from `UNVERIFIED`/`COMPLIANT`/`REMEDIATED` (not `NON_INSTALL_SUSPECTED`), both refusals `ERR_SUBSCRIPTION_STATE_INVALID`, decided after rule 16 — `routes/subscriptions.py:403-414`
- §3.6 — insert — ambiguity — the waiver-reversal credit performs exactly one rounding; the /12 stays exact — `calc.py:351-355`
- §3.6 — insert — ambiguity — `WAIVER_REVERSAL` rows are one-offs dated the confirmation date on both period edges — `services.py:152-157`, `ledger.py:24-26`
- §2.6 — revise — mismatch — the runtime-analytics score does one final rounding; the renewal-survey score accumulates whole points with no rounding at all — `calc.py:407,436`
- §3.9 — insert — ambiguity — cancel requires a date-only `effective_date` and a `cancel_reason` string with no declared length bound — `routes/subscriptions.py:208-209`
- §3.9 — insert — ambiguity — `PRORATION_CREDIT` brackets the whole settlement month; the cancellation `UNRETURNED_SHIPMENT_FEE` is a one-off on the logical-clock date, not the effective date — `services.py:197-204`, `calc.py:326-327`
- §3.9 — insert — ambiguity — the preview's `effective_date` is a required *query* parameter reported as `ERR_INVALID_REQUEST` (not `ERR_INVALID_PAGINATION`), with no date-range check and no status requirement — `routes/subscriptions.py:233`, `validate.py:118-125`

Pass 2 note: three of its edits touch §2.6 and §2.10 rather than §3.x, because §2.10 rules 8/16/19 make *exhaustive* claims that pass 2's code falsifies — pinning the §3 behavior alone would have left a live contradiction. Pass 3 was explicitly told those four sentences had been modified. Pass 2 reverted nothing of pass 1's and found no pass-1 sentence wrong; its §3.3 tie-break edit deliberately depends on pass 1's new §2.3 insertion-order rule so the two interlock rather than duplicate.

### Pass 3 of 3 — `routes/shipments.py`, `routes/cases.py`, `routes/entitlements.py`, `routes/claims.py`, `routes/transfers.py`

458 lines / 112,372 chars → 458 lines / 118,740 chars, **+6,368 chars**. No `cp`, no wholesale `Write`; 15 surgical `Edit` calls. Passes 1 and 2 edits intact (§2.6 and §2.10 rules 8/16/19 untouched).

**17 ambiguity-pins, 2 mismatch-revisions:**
- §3.5 — insert — ambiguity — ship's two preconditions both answer `ERR_SHIPMENT_STATE_INVALID` (shipment status tested first); `tracking_code` required, unbounded, overwrites the scheduled value — `routes/shipments.py:55-61`
- §3.5 — insert — ambiguity — the `delivered_at` ≥ `shipped_at` test is vacuous while `shipped_at` is null, so delivery on a `SCHEDULED` shipment is a status refusal — `routes/shipments.py:78-83`
- §3.5 — insert — ambiguity — `delivered_at`/`returned_at` stored in the three-fractional-digit form (sub-ms truncated) — `routes/shipments.py:85,120`
- §3.5 — insert — ambiguity — `return_reason` is required/unbounded but **not** a shipment field; enumerated the shipment payload — `routes/shipments.py:97,101`
- §3.5 — insert — ambiguity — `returned_at` < `delivered_at` is shape validation (`ERR_INVALID_REQUEST`) ahead of the status rung — `routes/shipments.py:113-116`
- §3.5 — insert — ambiguity — write-off takes no body, its ledger row carries memo `unreturned shipment write-off` and the clock date on both period fields, runs whatever the subscription's status is, and is never ceiling-checked — `routes/shipments.py:127-140`
- §3.5 — **revise** — **mismatch** — in-flight recall was claimed for every `CANCELLED` transition; only the §3.9 settling path recalls — the transfer-driven cancellation cancels `SCHEDULED` shipments but recalls nothing — `routes/transfers.py:213` (vs `services.py:194`)
- §3.6 — insert — ambiguity — confirm/remediate/close-unsubstantiated write the posture unconditionally (case status is the only gate) with exactly one subscription `version` bump; send-notice touches only the case — `routes/cases.py:36-96`
- §3.6 — insert — ambiguity — `remediation_note` required/unbounded and the only body field any case action declares — `routes/cases.py:73`
- §3.7 — insert — ambiguity — enumerated the readable claim payload; of `question`/`decision_note`/`withdraw_reason`/`reversal_reason` only `reversal_reason` is published — `routes/claims.py:131,179,236`
- §3.7 — insert — ambiguity — resubmit's `description` is 1–500 chars and replaces the stored narration — `routes/claims.py:144`
- §3.7 — insert — ambiguity — an `APPROVED` claim with `approved_amount_cents` 0 is refused with `ERR_CLAIM_STATE_INVALID`; payout/reversal memos and one-off dating pinned — `routes/claims.py:191-221`
- §3.8 — insert — ambiguity — occupancy test uses the mover's own lease window and excludes the mover, so a same-unit `to_unit_id` reaches rule 26 (`ERR_TRANSFER_TARGET_INVALID`) — `routes/transfers.py:48-58`
- §3.8 — **revise** — **mismatch** — remap selection was claimed to run against the destination unit's `hvac_system_type`; selection uses size, `filter_slot_count` and the resident's `allergy_flag` only — `routes/transfers.py:119` (`calc.select_sku`)
- §3.8 — revise — ambiguity — completion order (rule 8 property check first) and both state refusals answering `ERR_TRANSFER_STATE_INVALID` — `routes/transfers.py:158-165`
- §3.8 — insert — ambiguity — ceiling test reads the destination property and the inherited `billing_party`, adding the signed `net_adjustment_cents` — `routes/transfers.py:187`
- §3.8 — insert — ambiguity — successor inherits resident/billing_party/channel/lease dates, benefit set derived at posture `UNVERIFIED` (forfeited riders return), born at `version` 1 with `activated_at` stamped, entitlements created directly `ACTIVE`, no shipment and no enrolment/monthly fee — `routes/transfers.py:170-198`
- §3.8 — insert — ambiguity — the single `TRANSFER_ADJUSTMENT` row is always posted (even at zero), memo pinned, dated on the transfer's `effective_date` not the clock date — `routes/transfers.py:216-219`
- §3.8 — insert — ambiguity — `rejection_reason` required/unbounded; the subscription is driven to `ACTIVE` with no second test of its current value — `routes/transfers.py:137-144`

Pass 3 note (not changed): §3.6's entitlement-lifecycle sentence says cancellation expires rows that are `ACTIVE` or `SUSPENDED`, while `services.expire_entitlements` also covers `PENDING` (and §3.9 already pins `PENDING, ACTIVE or SUSPENDED`). Under-determined rather than contradicted, the `PENDING`-at-cancellation state is unreachable, and the code is pass 2's slice, so both sentences were left alone. `routes/entitlements.py` needed no PRD change.

### Step 9 totals

**47 ambiguity-pins + 15 mismatch-revisions = 62 changes** across the three passes. `PRD_COMPLETED.md` = 458 lines / 118,740 chars vs `PRD_FINALIZED.md`'s 456 / 102,049 — **+2 lines, +16,691 chars (+16.4%)**.

**Orchestrator verification:** `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md`, so the scan genuinely ran (the known Step 9 no-op failure did not occur). 28 headings preserved; the file ends cleanly on the final row of the §5 error table. A grep for `harder than expert|SCAFFOLD|difficulty_design|corner_design` returns nothing.

### Known latent edge deliberately NOT changed

Pass 2 flagged, and I independently confirmed, that `calc.runtime_analytics_score` (`implementation/calc.py:388,398-399`) computes `window_days = Fraction(int(round(span_seconds)), 86400)` and then divides by `expected = 1440 * window_days`. If the entire runtime evidence set spans under half a second of wall time, `span_seconds` rounds to 0 and the division raises `ZeroDivisionError` → HTTP 500. Each individual telemetry window is already required to be non-degenerate at ingest (`routes/units.py:75`), so this is only reachable with two sub-second windows inside the same half-second.

I chose to leave the implementation untouched, for three reasons: (1) no PRD sentence pins any outcome for that input, so picking one — an error id, a clamp, a floor of one day — would be adding behavior that traces to no verbatim PRD sentence, which the cardinal rules forbid; (2) documenting a crash in `PRD_COMPLETED.md` is not a legitimate "pin what impl does"; (3) an unverified implementation edit after Step 7's clean 8-round sweep would invalidate that evidence, and re-running a 20–60-minute sweep to cover an unreachable-in-practice input is a poor trade. Recorded here instead so the defect is visible to whoever owns follow-ups.

### Pipeline complete

Step 9 has written `workspace/PRD_COMPLETED.md`. All nine steps are done.
