# Worklog — task_3343_fuel_cell_material_handling_deployment_site_fuel

## Step 1: Create Task Directory — 2026-09-30T22:05:00.000Z

Pre-allocated directory `./tasks/task_3343_fuel_cell_material_handling_deployment_site_fuel/` verified to exist with empty `workspace/` inside; used as-is (no index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-10-01T04:47:00.000Z

Scaffold generation complete, lint-clean. Summary:

**Files written**
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key

**Counts**
- Entities: 15 (Site, Assessment, SupplyContract, FuelingStation, Permit, ConversionPlan, ConversionEvent, Technician, ServiceAgreement, DowntimeReport, FuelingEvent, FuelInvoice, FuelLineItem, IncentiveClaim, TrainingRecord)
- State machines: 11 (all entities except Technician/DowntimeReport/FuelingEvent/FuelLineItem, which are lifecycle-less or config)
- Calculations: 7 (daily_kg_estimate, supply_pricing_tier, take_or_pay_credit, availability_credit, invoice_availability_reconciliation, incentive_qualification_amount, telematics_productivity_credit)
- Validations: 21 (priorities 1–21 across auth/existence/state/safety/temporal/fiscal/referential/constraint)
- Endpoints: 82 total (incl. `POST /api/_clock/set_current_utc` with the mandatory 2026-09-01T00:00:00Z default)
- Errors: 21, every one referenced by at least one validation/transition
- Roles: 6 (PlatformAdmin, SiteManager, SafetyOfficer, ComplianceOfficer, ConversionTechnician entity_backed:Technician, BillingOperator)
- Concurrency rules: 2 (OCC on FuelInvoice line-add and ConversionPlan schedule)

**Difficulty design (§1.8)**: 18 instances — 2 per each of the nine rules, with the required differentiation (dual variants on invoice vs site domains; combinatorial modes (a) and (c); non-linear machines on FuelInvoice vs Assessment; cascades from clock-driven permit expiry vs explicit contract termination; priority conflicts state-vs-safety and fiscal-vs-referential; boundaries on availability % vs storage kg; cross-entity pairs plan→assessment and fueling event→station; strict-overlap datetimes vs half-open dates; invariants on invoice totals vs conversion progress counts). All formula-derived asserts were pre-computed to literals.

**Corner design (§1.9)**: 48 instances total — 38 active test_recipes across 9 sections (entities 10, state_machines 7+1 stub, calculations 4, validations 8, endpoints 1+2 stubs, errors 2+6 stubs, rbac 3, cross_cutting_layers 3, consistency_model 1); 10 stubs reference existing §1.8 instances.

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (530 calls scanned). Additional checks passed: unique instance names across the union, no forbidden concurrency vocabulary, all grounds resolve to §1.1–§1.6 elements, zero unbound `${var}` placeholders, all OCC version inputs are placeholder references. No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-10-01T04:48:19.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-10-01T04:58:00.000Z

PRD is written and all three hard contracts pass. Summary:

**Output path:** `workspace/PRD.md` — 322 lines.

**Section overview:**
- **§1 Introduction** (2 paragraphs): fuel-cell forklift deployment program framing, role/approval-chain overview, `/api` mount note.
- **§2 Global Specifications** (10 subsections): 2.1 RBAC with both headers, all six roles spelled, and per-role `identity:` prose (ConversionTechnician entity-backed to `Technician`, all others opaque); 2.2 fixed verbatim response-envelope block copied byte-for-byte from `section-2.2-response-structure.md`; 2.3 pagination (limit default 10, min 1, max 100, offset default 0, `created_at` ascending sort, meta fields); 2.4 common resource properties (`id` UUID no prefix, `created_at`/`updated_at` ISO 8601 UTC 3-fractional-digits, `version` integer incrementing on every mutation); 2.5 logical clock with startup default `2026-09-01T00:00:00Z` and all four clock-driven automatic transitions plus their cascades; 2.6 hierarchical consistency/cascades and left-to-right nested-path validation; 2.7 fire-code envelope (INDOOR 200 kg ceiling, DISPENSING_INDOOR commissioning gate); 2.8 money/precision conventions (integer cents, per-line-round-then-sum, 4-decimal tier price); 2.9 OCC on exactly the two guarded endpoints (`expected_invoice_version` on line-item add, `expected_plan_version` on plan schedule, both `ERR_STALE_VERSION`/412); 2.10 full validation priority ordering (21 checks, grouped in prose order).
- **§3 Business Logic & Workflows** (8 subsections): 3.1 sites/assessments with `daily_kg_estimate` (0.9 kg/h factor, 1.0 vs 1.15 peak-shift multiplier at the 8-hour boundary, round-half-up 2dp) and the full DRAFT→SUBMITTED→APPROVED/REJECTED→DRAFT cycle; 3.2 supply contracts with half-open same-mode overlap rule, activation cascade reactivating SUSPENDED sites, termination blocked by open invoices; 3.3 stations/permits with the CONSTRUCTION+FIRE pair cascade to PERMITTED, construction start date gate, commissioning gates, permit-expiry suspension cascade; 3.4 conversion plans/events/technicians with the approved-assessment gate, strict-vs-touching technician overlap rule, bubble-up and cascade-down transitions, unstart; 3.5 service agreements and the availability report (730 hours/month, latest-created APPROVED assessment and ACTIVE agreement win ties, strictly-below guarantee trigger, 10% credit rate); 3.6 fueling events and the full tiered pricing (prior-billed kg set definition excluding VOID, three tier branches, 0.92 discount, 1.08 DELIVERED_LIQUID markup, 4-decimal unit price, per-line round-then-sum) plus dual-variant provisional/final take-or-pay credit (last-day exclusion, 25% shortfall rate, availability reconciliation added at issuance, clamps); 3.7 incentive claims with TELEMATICS vs SELF_REPORTED (90% haircut) productivity variants, FEDERAL_ITC gate and fixed evaluation order (plan → converted units → 1,500,000 cents/unit capex → uplift → 30% ITC rate → cap at claimed amount), non-ITC symmetric branch; 3.8 training records with VALID→EXPIRED clock transition.
- **§4 Endpoint Definitions**: 4-column table covering all 82 scaffold endpoints with exact paths and authorized roles.
- **§5 Error Code Catalogue**: 2-column table covering all 21 error IDs with HTTP statuses.

**Coverage-audit results:**
- Contract 1 (Field-Name Coverage): 79 required field/request identifiers, all present in backticks — PASS (two FK fields, `invoice_id` and `station_id`, were added in a repair pass).
- Contract 2 (Rule Coverage): all 21 validations expressed with priority ordering stated in §2.10; both OCC rules named with endpoint capability, field, error ID, and 412 status; all 12 state machines' transitions (from/to, preconditions, side effects) expressed; all 7 calculations rendered as precise prose with constants (0.9, 1.0/1.15, 0.92, 1.08, 0.25, 730, 0.10, 1,500,000, 0.30, 0.90) embedded in business context; all endpoint side effects and cross-entity cascades covered; sibling branches (INDOOR/OUTDOOR, TELEMATICS/SELF_REPORTED, provisional/final, ITC vs non-ITC) treated with equal density — PASS.
- Contract 3 (§3 Path Purity): 377 backticked tokens scanned in §3, zero path tokens, zero bare HTTP methods, zero method+path combos — PASS.
- Additional spot checks: all 43 enum/state values and all 6 role names present; all 82 endpoint paths present in §4; all 21 error IDs appear in prose.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not read or referenced at any point.

(Note: the first Step 4 subagent invocation exited after planning without writing the file; it was resumed via SendMessage and completed in the second invocation. Both invocations honored the design-index withholding.)

## Step 5: Generate Unit Tests — 2026-10-01T09:10:00.000Z

Regenerated from scratch (old partial `test_helpers/` + `test_suite/` deleted first, per instructions). NOTE: this step required 4 spawn attempts — attempts 1–3 died mid-flight (host OOM-kill and two `model_not_found` endpoint failures) each leaving partial output; the 4th completed. Only the final artifact persists.

### Files written

**`test_helpers/`** (9 files):
- `types.py` — 20 status/role/enum types + 16 entity TypedDicts (all carry §2.4 system fields)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~60)
- `api_errors.py` — `ApiErrorId` (21 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + invoice money invariants
- `factories.py` — 14 payload factories (input fields only)
- `constants.py` — PRD-pinned rates (0.9 kg/h, 0.92, 1.08, 0.25, 730 h, 0.10, 1,500,000¢, 0.30, 0.90, 200 kg)
- `test_users.py` — role headers + `make_conversion_technician_headers(technician_id)` for the entity-backed role, plus `ANONYMOUS_HEADERS`
- `fixtures.py` — composite chains: clock, approved assessment, active contract/agreement, commissioned station (permit pair + construction + commission), scheduled/completed plans, OCC-threaded invoice-with-lines, full conversion-lifecycle setup
- `__init__.py` — barrel export

**`test_suite/`** (21 files): `conftest.py` + `test_01`–`test_20`, one file per design-index rule/section.

### Test counts — 72 total, all collected by pytest
- **Queue A (Difficulty): 34 tests** covering 17/18 instances at ≥2 each
- **Queue B (Corner): 38 tests** covering all 38 non-stub instances; 10 `excluded_because:` stubs not translated (all stub pointers verified to resolve)

### Skips and corrections (PRD-first filter)
1. **Skipped entirely**: `Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_fueling_event` — asserts `ERR_INVALID_STATE` beats `ERR_STATION_NOT_COMMISSIONED` for a dispense on a PLANNED station, but PRD §3.6 names `ERR_STATION_NOT_COMMISSIONED` for exactly that condition and §2.10 stage-4's scope over plain creates is ambiguous; the sibling instance (`fueling_event_blocked_by_station_state`) asserts the opposite error. Not uniquely derivable.
2. **Partial**: `fiscal_error_beats_referential_error_on_schedule` — the zero-line-invoice issuance under a TERMINATED contract (`ERR_CONTRACT_NOT_ACTIVE`) is undecidable from the PRD (no error id is named for the "≥1 line item" issuance requirement, so precedence is unknowable); the instance is instead covered by two PRD-verbatim `ERR_EVENT_NOT_BILLABLE` tests (out-of-period + double-billing).
3. **Drifted literals corrected to PRD-derived values** (flagged, not copied verbatim): `incentive_evaluation_order_with_cap` uncapped ITC asserted as **1,080,000** (2 × 1,500,000 × 1.20 × 0.30; design said 1,029,600); `invoice_availability_component_added_at_issue` subtotal/credit asserted as **4,800** (straddle blend 2.40 × 20 kg; design said 5,000).

### Audit results
- **Tag audit**: 72/72 tests carry exactly one `Design:` line; every tag resolves to a real instance; only shortfall is the deliberately skipped instance above; no stub has a test.
- **Citation audit**: all 108 quoted docstring chunks (≥6 words) match PRD.md verbatim (whitespace-normalized).
- Compile + `pytest --collect-only`: 72 tests collected, no import errors; no `skip`/`xfail`/`skipif` markers; no scaffold references in comments.

## Step 6: Generate Implementation — 2026-10-01T09:55:00.000Z

Implementation complete and verified. Final summary:

## Files written — all under `workspace/implementation/`

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Guarded pip install + `exec python3 app.py`, `PORT`/0.0.0.0, foreground |
| `requirements.txt` | 1 | flask>=2.2 |
| `app.py` | 44 | Flask app, error handlers, blueprint registration |
| `db.py` | 76 | In-memory stores (empty at boot), logical clock (default 2026-09-01T00:00:00Z), strictly-increasing stamps |
| `errors.py` | 32 | All 21 error IDs + ApiError |
| `envelope.py` | 34 | `meta`/`response_type`/`data` envelope, error envelope, pagination meta |
| `validators.py` | 147 | Type/enum/date/datetime/month validators |
| `authz.py` | 44 | X-User-ID + X-User-Role checks (401/403) |
| `helpers.py` | 83 | 404 fetch, nested-ownership, site-closed guard, OCC touch, pagination |
| `calc.py` | 231 | All 7 calculations (daily_kg, tiered pricing, take-or-pay provisional/final, availability, invoice reconciliation, ITC amount, productivity variants) |
| `clockops.py` | 59 | Clock reconciliation pass (permit/contract/agreement/training expiries + cascades) |
| `routes/` (16 files) | 1,566 | One module per resource group |

**Endpoint coverage: 82/82** — verified programmatically by diffing the registered Flask route table against the full PRD §4 endpoint list (zero missing; only extra is Flask's built-in `/static`).

**Import check:** `python3 -c "import app"` succeeds; cold boot via `python3 app.py` serves HTTP within ~1s.

**Live smoke test (70+ assertions, all passing):** envelope shape, 401/403 auth ordering, ERR_DUPLICATE_CODE, daily_kg = 82.8 (peak>8 multiplier), contract half-open overlap (back-to-back allowed), permit-pair cascade PLANNED→PERMITTED, ERR_INDOOR_DISPENSING_NOT_APPROVED at commission, ERR_INDOOR_STORAGE_EXCEEDED, technician double-booking (touching windows allowed), ConversionTechnician ownership 403, plan SCHEDULED→IN_PROGRESS→COMPLETED bubbling, ERR_STALE_VERSION on both OCC endpoints, tiered pricing with boundary straddle + 1.08 markup (5.4 / 5.256 / 4.968 unit prices), provisional credit with last-in-period-day exclusion (5000/27400) vs final freeze, availability SLA credit (97.26 < 99 → 10000) and its clamped addition at issue, ERR_OPEN_INVOICES_EXIST, terminate/expire/activate site cascades (ACTIVE↔SUSPENDED), FEDERAL_ITC gate (422) then approval amount 990000, clock-driven EXPIRED transitions, ERR_SITE_CLOSED guard, and pagination bounds.

**Process safety:** one earlier smoke-server orphan was traced by port via `ss` and killed by exact PID; all test servers started were stopped and ports confirmed free.

One design judgment flagged for the test-fix phase if needed: transition preconditions like "site must be ACTIVE" on a SUSPENDED (not CLOSED) site return ERR_INVALID_STATE (409), and a body-referenced nonexistent FK (e.g., `supply_contract_id` on invoice create) returns 404 while a nonexistent `fueling_event_id` on line-add returns ERR_EVENT_NOT_BILLABLE per the priority-18 referential rule.

Isolation rule honored: SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, test_helpers/ were not read.

## Step 7: Test-Fix Iteration Loop — 2026-10-01T10:25:00.000Z

NOTE: a first Step 7 subagent was killed mid-flight (host session ended) leaving unattributed edits in test_01/05/19, test_helpers/{constants,api_client,assertions}.py, and implementation/db.py. A fresh Step 7 subagent was spawned with instructions to re-adjudicate all inherited edits. Its summary follows verbatim:

All verification passes. The exit condition is met — all 8 rounds have `passed == total` (72/72), union of failures is empty, and the inherited mid-flight edits all re-adjudicate as PRD-faithful.

**Summary**

- **Iterations run:** 1 (single 8-round parallel sweep; all 8 rounds 72/72 passed, zero flaky failures across rounds — `results.1.json` … `results.8.json` preserved at `workspace/implementation/`)

- **Tests deleted:** none.

- **Fixes applied this loop:** none — the sweep was green on arrival. Per the inherited-state warning, every file the killed subagent touched was re-adjudicated rather than trusted:

  - `test_suite/test_01_dual_variant_invoice_credit.py` — re-derived all literals from PRD §3.6: two 40 kg DELIVERED_LIQUID lines at 2.00 × 1.08 = 2.16 → 8640 cents/line, subtotal 17280; provisional credit (100−40) × 200 × 0.25 = 3000 with total 8640−3000 = 5640; final credit (100−80) × 200 × 0.25 = 1000 with total 17280−1000 = 16280. The hybrid assertion (full `subtotal_cents`/`total_kg` fields with provisional `credit_cents`/`total_cents`) is supported by the standing line-add sentence ("`total_kg` is the sum of line `kg`, `subtotal_cents` is the sum of the already-rounded line amounts") scoping the exclusion to "this preview". Faithful.
  - `test_suite/test_05_state_machine_cycles.py` — dispute/resolve cycle and revise/resubmit loop literals re-derived (straddle blend (10×3.00 + 10×2.76)/20 → line 5760; daily_kg 6 × 8.0 × 0.9 × 1.0 = 43.2 at the ≤8h boundary). Faithful.
  - `test_suite/test_19_corner_cross_cutting.py` — OCC quotes match PRD §2.9 verbatim; derived-field recompute on add/void matches §3.6; no error-precedence conflict in the stale-version cases. Faithful.
  - `test_helpers/constants.py` — all 13 constants verified verbatim against PRD prose (0.9 kg/h, 1.0/1.15 at 8h, 0.92, 1.08, 0.25, 730 h, 0.10, 1,500,000¢, 0.30, 0.90 haircut, 200 kg, clock default 2026-09-01T00:00:00Z).
  - `test_helpers/api_client.py` — programmatic diff: all 82 client calls match PRD §4 paths; zero unmatched.
  - `test_helpers/assertions.py` — helpers faithful; entity asserts are exported but uncalled by tests (dead-but-harmless; tests carry direct literal assertions). No weakening found.
  - `workspace/implementation/db.py` — in-memory stores only, no seeding, clock default correct; the `stamp()`/`clock_stamp()` split is legitimate timestamp infrastructure consistent with §2.3/§2.4.

- **Cross-cutting checks:** no `skip`/`xfail`/status-only assertions anywhere in the suite; all 21 PRD error IDs are referenced in live code paths (none dead); no source file was modified after the sweep started, so the green result genuinely covers the current tree.

Orchestrator verification: all 8 `results.{i}.json` files exist on disk and each reports passed==total==72; no .py source file under test_suite/, test_helpers/, or workspace/implementation/ is newer than the results files.

## Step 8: Finalize PRD — 2026-10-01T10:45:00.000Z

NOTE: Step 8 was NOT skipped despite the green-on-arrival sweep, because the killed first Step 7 subagent left unattributed edits in 7 files; those edits constitute Step 7 fixes whose descriptions were unrecoverable, so the step_7_diff inlined the edited-file list plus the re-adjudication notes. Subagent summary follows verbatim:

The diff is exactly the two intended inline revisions. Both files remain at 322 lines (0% line-count delta; 2 lines revised inline, ~0.6% of the document).

### Changes (one bullet per edit)

- **§2.5 (The Logical Clock)** — revise — pinned that every server-emitted timestamp (`created_at`, `updated_at`, envelope `api_request_timestamp`) derives from the logical clock (never wall-clock), that these stamps are strictly increasing via a 1 ms nudge on ties so `created_at` ordering is total, and that the action stamps `commissioned_at`/`terminated_at`/conversion-event `completed_at` record the exact logical-clock instant with no nudge — `implementation/db.py:55-76` (`stamp()` vs `clock_stamp()`), `implementation/helpers.py:36-44`, `implementation/envelope.py:12`, `implementation/routes/stations_r.py:159`, `implementation/routes/contracts_r.py:138`, `implementation/routes/events_r.py:157`.
- **§3.6 (invoice credit variants)** — revise — pinned that the last-in-period-day exclusion applies only inside the provisional-credit computation, that a `DRAFT` invoice's own `total_kg`/`subtotal_cents` fields always carry the full sums over all line items, and that while `DRAFT`, `total_cents` = provisional subtotal − credit (floored at zero) — `implementation/calc.py:103-125` (`recompute_draft_totals` stores full sums; `total_cents = max(0, inc_sub - credit)`), exercised by `test_suite/test_01` (subtotal 17280 / total_kg 80 / credit 3000 / total 5640).

### Per-edit pre-edit search log (NO-NEW-MISMATCH rule)

**Edit 1 (§2.5 timestamps):**
- (a) Subject: source clock and tie-breaking for all server-generated timestamps.
- (b) Paths enumerated: `grep -rn "clock_stamp\|db.stamp\|stamp()"` across `implementation/` — all callsites: `helpers.py:36` (`touch` → `updated_at`), `helpers.py:40` (`create_rec` → `created_at`/`updated_at`), `envelope.py:12` (`api_request_timestamp`), `stations_r.py:159` (`commissioned_at` = `clock_stamp()`), `contracts_r.py:138` (`terminated_at` = `clock_stamp()`), `events_r.py:157` (event `completed_at` = `clock_stamp()`). Also checked `clockops.py` (no stamps, uses `touch`), `clock_r.py` (sets clock, no stamps), and confirmed training-record `completed_at` is client-supplied (§3.8) — hence the edit names "the conversion event's `completed_at`" explicitly to avoid mis-describing the training field. Verified `created_at` tie-breaks are load-bearing: `calc.py` `max(..., key=created_at)` for governing assessment/agreement/plan (`availability_report`, `governing_completed_plan`, `plans_r.py:97`).
- (c) Wording adjustment: scoped the exact-instant clause to the three named action stamps (not "all action timestamps") so the client-supplied training `completed_at` stays excluded; said "strictly increasing across the server's lifetime" (process-global `_last_stamp`, matching the in-memory store's lifetime).

**Edit 2 (§3.6 provisional preview):**
- (a) Subject: which quantities the last-day exclusion shrinks — the credit/total computation basis only, or the invoice's displayed `total_kg`/`subtotal_cents` fields too; and which "subtotal" feeds DRAFT `total_cents`.
- (b) Paths enumerated: `grep -rn "recompute_draft_totals\|finalize_invoice_totals\|total_cents\|subtotal_cents\|credit_cents\|total_kg"` — all touchpoints: `calc.py:103-125` (DRAFT recompute: full sums stored, provisional credit, `total_cents` from provisional subtotal), `calc.py:128-143` (issue finalize: full sums, combined credit capped at full subtotal — the final-variant sentence already covers this, left verbatim), `invoices_r.py:49-59` (create initializes all four fields to 0 = full sum over zero lines), `invoices_r.py:75-103` (recompute on DRAFT get/list), `invoices_r.py:155` (recompute on line add + `touch`), `invoices_r.py:184` (finalize on issue), `invoices_r.py:190-239` (void/pay/dispute/resolve never recompute — frozen fields preserved). Also confirmed the PRD's own line-191 sentence ("`subtotal_cents` is the sum of the already-rounded line amounts") already supports the full-sums reading, so the edit harmonizes rather than contradicts.
- (c) Wording adjustment: changed "excluded from both `total_kg` and `subtotal_cents` for this preview" to "excluded from the `total_kg` and `subtotal_cents` quantities feeding this preview" (removes the apparent field-shrinking reading at the source) and scoped the `total_cents` clause with "while `DRAFT`" + "the provisional subtotal" so the adjacent final-variant sentence remains the sole governor of ISSUED semantics.

### Subjects audited and found already uniquely pinned (no edit)

- State-machine cycle literals (test_05): dispute→resolve→ISSUED loop, reject→revise→DRAFT→resubmit loop, frozen totals from issuance — PRD §3.6/§3.1 verbatim; impl matches.
- daily_kg at the ≤8h boundary (43.2): PRD §3.1; impl `calc.py:45`. Pinned.
- Straddle blend (5760): PRD §3.6; impl `calc.py:78-85`. Pinned.
- OCC stale-version (test_19): PRD §2.9/§2.10; impl `invoices_r.py:142`, `plans_r.py:102`. Pinned.
- Derived-field recompute on line add / void release (test_19): PRD §3.6/§4; impl matches. Pinned.
- All 13 constants + clock default: all verbatim in PRD §2.5/§2.7/§3.1/§3.5/§3.6/§3.7. Pinned.
- Endpoint surface: all 82 client calls map to PRD §4. Pinned.
- Envelope/system-field assertions: pinned by §2.2/§2.4/§2.8.
- db.py seeding/clock default: §2.5 pins default; empty start implied by create-only API surface.

Orchestrator verification: PRD_FINALIZED.md exists (322 lines); diff vs PRD.md shows exactly the two described inline revisions and nothing else.

## Step 9: Complete PRD — 2026-10-01T11:20:00.000Z

**File produced:** `workspace/PRD_COMPLETED.md`

**Size:** PRD_FINALIZED.md 322 lines / 46,977 chars → PRD_COMPLETED.md 322 lines / 51,058 chars (**+4,081 chars, 0 line delta** — all changes are in-place line revisions; 25 lines touched).

**Counts:** 26 ambiguity-pins, 1 mismatch-revision.

### Changes (one per bullet)

- **§2.1** — insert — ambiguity — missing `X-User-ID` header also yields `ERR_UNAUTHENTICATED` (401), not just a missing/unrecognized role — `implementation/authz.py:30`
- **§2.3** — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400); `total_count` counts matches pre-pagination; `has_more` = `offset + len(page) < total_count` — `implementation/helpers.py:51-83`
- **§2.5** — insert — ambiguity — clock-set adopts the supplied instant as-is (no monotonicity requirement) and returns 200 with empty `data` — `implementation/routes/clock_r.py:14-22`
- **§2.10** — revise — **mismatch** — `POST /api/invoices` validates body field shapes/date formats (stage 6) before resolving body-referenced `site_id`/`supply_contract_id` (stage 3), an explicit deviation from the generic order — `implementation/routes/invoices_r.py:36-48`
- **§3.1** — insert — ambiguity — site `name` 1–120 chars, `address` 1–200 chars, `baseline_labor_rate_per_hour` a number ≥ 0.01 — `implementation/routes/sites_r.py:26-30`
- **§3.1** — insert — ambiguity — a `SUSPENDED` site blocks no writes; only `CLOSED` triggers `ERR_SITE_CLOSED` — `implementation/helpers.py:29-31` (used by all site-scoped creates)
- **§3.1** — insert — ambiguity — `forklift_count`/`peak_shift_hours` are integers; PUT may update any subset of the three duty-cycle inputs plus `safety_findings_json`, always recomputing and bumping `version`; submit/approve against a non-`ACTIVE` site fail with `ERR_INVALID_STATE` (409) — `implementation/routes/assessments_r.py:51-56,86-107,118-120,135-137`
- **§3.2** — insert — ambiguity — a new contract carries `terminated_at: null` until termination — `implementation/routes/contracts_r.py:67`
- **§3.3** — insert — ambiguity — `capacity_kg_per_day`/`storage_capacity_kg` must be numbers > 0; new station has `commissioned_at: null`; PUT accepts any subset of the six attributes and re-validates the date pair and indoor ceiling against the merged result — `implementation/routes/stations_r.py:41-62,90-117`
- **§3.3** — insert — ambiguity — permit filing itself enforces `expiry_date` strictly after `issued_date` (422), re-checked at issuance — `implementation/routes/permits_r.py:36-38,73-75`
- **§3.3** — insert — ambiguity — starting construction before `construction_start` → `ERR_INVALID_STATE` (409); commissioning with a non-`ACTIVE` site → `ERR_INVALID_STATE` (409) — `implementation/routes/stations_r.py:129-131,146-148`
- **§3.4** — insert — ambiguity — plan `name` 1–80 chars, `target_forklift_count` integer ≥ 1, `baseline_productivity_units_per_hour` > 0, `expected_productivity_gain_pct` ≥ 0 — `implementation/routes/plans_r.py:34-44`
- **§3.4** — insert — ambiguity — schedule gate compares against the latest-created `APPROVED` assessment; non-`ACTIVE` site at schedule → `ERR_INVALID_STATE`; revert with a `COMPLETED` event → `ERR_INVALID_STATE` — `implementation/routes/plans_r.py:86-101,118-121`
- **§3.4** — insert — ambiguity — events may be created under a plan in any status; new event has `completed_at: null`; an unknown `technician_id` → `ERR_TECHNICIAN_NOT_CERTIFIED` (422) checked after double-booking; technician `name` 1–120 chars; `certified_until` must be strictly after the current date else `ERR_INVALID_DATE_RANGE` (422) — `implementation/routes/events_r.py:49-87`, `implementation/routes/technicians_r.py:22-31`
- **§3.5** — insert — ambiguity — `monthly_fee_cents` integer ≥ 0; agreement activation with non-`ACTIVE` site → `ERR_INVALID_STATE` (409) — `implementation/routes/agreements_r.py:34-35,79-81`
- **§3.5** — insert — ambiguity — downtime `forklift_id` 1–60 chars; malformed `month` list filter → `ERR_INVALID_REQUEST` (400) — `implementation/routes/downtime_r.py:24,43-46`
- **§3.5** — insert — ambiguity — availability report takes a required `month` query parameter; missing/malformed → `ERR_INVALID_REQUEST` (400) — `implementation/routes/availability_r.py:19-22`
- **§3.6** — insert — ambiguity — fueling `forklift_id` 1–60 chars; a nonexistent `supply_contract_id` also yields `ERR_NO_ACTIVE_CONTRACT` (422), not 404 — `implementation/routes/fueling_r.py:24,35-39`
- **§3.6** — insert — ambiguity — invoice creation takes `site_id`/`supply_contract_id` in the body, each must exist (404) but the contract need not belong to the site; new invoice totals are all zero — `implementation/routes/invoices_r.py:36-60`
- **§3.6** — insert — ambiguity — a nonexistent `fueling_event_id` at line-add → `ERR_EVENT_NOT_BILLABLE` (422) — `implementation/routes/invoices_r.py:120-123`
- **§3.6** — insert — ambiguity — the DRAFT provisional-credit refresh applies to list endpoints as well and is not a mutation (no `version` bump) — `implementation/routes/invoices_r.py:75-77,86-87,101-103`, `implementation/calc.py:103-125`
- **§3.6** — insert — ambiguity — issuing an empty invoice fails with `ERR_INVALID_STATE` (409) — `implementation/routes/invoices_r.py:177-179`
- **§3.7** — insert — ambiguity — `claimed_amount_cents` integer ≥ 0; `approved_amount_cents` null until decision; claim submit with non-`ACTIVE` site → `ERR_INVALID_STATE`; approve/reject require only not-`CLOSED`, not `ACTIVE` — `implementation/routes/claims_r.py:34-45,73-75,85-88`
- **§3.7** — insert — ambiguity — record-productivity accepts `reported_units_per_hour` ≥ 0 and enforces no conversion-completion precondition — `implementation/routes/sites_r.py:82-89`
- **§3.8** — insert — ambiguity — `trainee_employee_id` 1–60 chars — `implementation/routes/training_r.py:24-25`
- **§4** — insert — ambiguity — an out-of-set `status` filter value on list endpoints (sites, invoices) → `ERR_INVALID_REQUEST` (400) — `implementation/routes/sites_r.py:50-52`, `implementation/routes/invoices_r.py:72-74,98-100`

### Verified already-aligned (no change needed)

All endpoint paths/roles match the §4 table; the tier-pricing blend, markup, take-or-pay dual credit variants, availability formula (strictly-below trigger, 730 h/month, latest-created APPROVED assessment/agreement), ITC evaluation order, clock reconciliation pass (order + version bumps + no-nudge action stamps), half-open contract overlap, strict technician overlap, plan completion cascade, and the §5 error catalogue all match the implementation exactly as written.

Orchestrator verification: PRD_COMPLETED.md exists (322 lines) and differs from PRD_FINALIZED.md (real patch, not a silent no-op); no .py source file under test_suite/, test_helpers/, or workspace/implementation/ is newer than the Step 7 sweep results files, so the green 72/72 sweep still covers the shipped tree.
