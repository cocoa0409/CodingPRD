# Worklog — task_2184_semi_trailer_rental_leasing

## Step 1: Create task directory — 2026-08-30T00:00:00.000Z

Created `tasks/task_2184_semi_trailer_rental_leasing/` and `tasks/task_2184_semi_trailer_rental_leasing/workspace/`.

## Step 2: Generate scaffold — 2026-08-30T02:40:00.000Z

Done. Three scaffold artifacts generated from the scenario alone (no sibling task was read, listed, or grepped).

## Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2870 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2953 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 7448 |

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     75
  Calls scanned (§1.8+§1.9):  1065

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design summary

**Profile** — quota/allocation blended with a pricing engine, `entity_topology: graph`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, layers: optimistic concurrency, dual-variant calculation, cascading side effects, selector policy. Sized above Expert: 12 entities, 9 state-machine blocks, 4 OCC rules, 12 calculations, 22 ordered validations, 59 endpoints, 53 errors, 5 roles.

**Entity model** — `Branch`, `TrailerType`, `Trailer`, `Customer`, `InsuranceCertificate`, `RateCard`, `Agreement`, `AgreementUnit` (Agreement<->Trailer junction), `MaintenanceEvent` (append-only, `common_fields: false`), `DamageAssessment` (self-referential via `supersedes_assessment_id`), `Chargeback`, `RelocationOrder` (two FKs into `Branch`). Every FK is discoverable through a filtered-list GET.

**State machines** — `Agreement.status` is branching **and cyclic** (`RESERVED <-> PENDING_ALLOCATION` when a trailer leaves service), with a second parallel dimension `purchase_option_status`. `Trailer` carries two genuinely independent dimensions: an explicit `availability_status` machine and a derived, precedence-ordered `service_status` (DOT -> damage -> PM -> serviceable). `Chargeback` cycles `PENDING <-> DISPUTED`. `AgreementUnit`, `RelocationOrder` (branching) and `InsuranceCertificate` (lazy read-time expiry against a logical clock defaulting to `2026-08-01T00:00:00Z`) complete the set.

**Key mechanics** — dual variants on two different domains (Agreement cost `quoted_forward` 123240 vs `final_chronological` 151268; Customer risk `underwriting_snapshot` 48 vs `renewal_review` 67); pinned round-per-line-then-sum (11190, not 11191); a pinned-evaluation-order lease-end purchase option (2262419); a depth-4 cascade (assessment submit -> chargeback + damage points -> OOS_DAMAGE -> relocation auto-cancel) and a depth-3 cascade from a failed DOT inspection; half-open trailer occupancy vs closed-interval buffered yard capacity; and two conserved quantities (fleet headcount, chargeback balance) with compensating actions.

**Instance counts** — 18 difficulty instances (all nine `rule_id`s x 2) and 79 corner instances across the guide's nine sections (75 executable + 4 `excluded_because` stubs). Placeholder closure, capture-to-`output:` resolution, grounds resolvability, stub back-references, and error-catalog triggerability (all 53 errors covered) were each verified programmatically; no forbidden concurrency vocabulary appears, and every tie-break uses `created_at`, never `id`.

## Step 3: Copy shared files — 2026-08-30T02:40:30.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-30T02:55:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — 450 lines, ends at §5 with no audit footer.

**Sections**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Money, Points and Rounding · 2.7 Optimistic Concurrency on Parent Records · 2.8 Nested Path Resolution · 2.9 Order of Evaluation for Rejections · 2.10 Fleet Position, Yard Counters and Cascades · 2.11 Interval Conventions
- §3 Business Logic (9 subsections): 3.1 Yards/Equipment Classes/Units · 3.2 Lessees, Certificates, Underwriting · 3.3 Published Pricing & Peak Uplift · 3.4 Contract Origination · 3.5 Allocation, Manual Attach & Peak Lease Reserve · 3.6 Checkout, Return, Settlement & Purchase Option · 3.7 Shop Events & Service-Status Cascade · 3.8 Damage Assessment, Liability Split & Chargeback Adjudication · 3.9 Repositioning
- §4 Endpoint Definitions (4-column table, 59 rows)
- §5 Error Code Catalogue (2-column table, 53 rows)

**Coverage audit (documented / in scaffold)**
- Entities 12/12 · state machines 9/9 (59/59 transitions) · calculations 12/12 (incl. both conservation invariants and all dual variants) · validations 22/22 with explicit priority ordering in §2.9 · concurrency rules 4/4 · endpoints 59/59 · errors 53/53 · roles 5/5 (each `identity:` translated to prose)

**Hard contracts**
```
Field coverage check:
- entities[].fields: 111 required, 111 present, 0 missing
- endpoints[].request_body: 70 required, 70 present, 0 missing
- endpoints[].query_params: 26 required, 26 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 22 checked, 22 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 4 checked, 4 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 59 checked, 59 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 22 checked, 22 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 59 checked, 59 expressed, 0 missing
- entities[].fields[] structured content: 111 checked, 111 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (4 cancel sources, waive PENDING/DISPUTED, void PENDING/DISPUTED, auto-cancel REQUESTED/APPROVED, ON_RENT/ON_LEASE returns, ALLOCATED->ON_RENT/ON_LEASE, exercise/decline, revoke ACTIVE/EXPIRED), 8 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 905
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Notes: §2.2 was concatenated byte-for-byte from `section-2.2-response-structure.md`. The two withheld design indices were never opened. Pinned-order traps that needed careful prose — the round-per-line-then-sum settlement order, the six-step purchase-option credit cap keyed on the pre-credit base price, the first-match-wins service-status precedence, the top-of-ranking peak lease reserve, and the half-open vs. closed interval split — are each stated explicitly with their boundary inclusivity.

**Orchestrator verification:** 450 lines; §1–§5 all present; §5 contains 53 `ERR_` rows; file ends mid-catalogue-table as expected (no truncation).

## Step 6: Generate implementation — 2026-08-30T03:15:00.000Z

Implementation complete.

## Files written (`workspace/implementation/`, 3034 lines total)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 8 | Guarded `pip install` (skipped when flask imports), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 61 | Blueprint registration, ApiError/HTTPException handlers, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 133 | In-memory dicts, logical clock (starts `2026-08-01T00:00:00Z`), UUIDs, ISO-ms timestamps, insertion `_seq` |
| `errors.py` | 69 | All 54 error IDs -> HTTP status |
| `envelope.py` | 44 | `meta`/`response_type`/`data` envelope, `req_` request ids, list pagination meta |
| `auth.py` | 43 | `X-User-ID`/`X-User-Role`, 5 roles, ownership guard |
| `validate.py` | 187 | Payload-shape + pagination validation (limit 1-100, offset >= 0) |
| `calc.py` | 319 | All pinned calculations (Decimal + ROUND_HALF_UP) |
| `serializers.py` | 244 | Per-entity output; computed fields evaluated on read |
| `services.py` | 263 | 404 lookups, cascades, trailer selection/ranking/lease reserve |
| `routes/*.py` | 1662 | reference, parties, agreements, units, shop, relocations |

## Endpoint coverage
**59 implemented vs. 59 in the PRD table** — verified by enumerating Flask's url_map against §4.

## Key fidelity decisions (PRD-driven)
- Rejection precedence follows PRD §2.9 verbatim, not the scaffold's precondition ordering: FK-existence before payload shape; date-ordering before ownership/state; SoD (9) and OCC (10) before from-state (11); in-service before DOT; window-conflict before availability.
- Computed fields (branch counters, `outstanding_chargeback_cents`, `allocated_unit_count`, `damage_points`, `service_status`, `net_book_value_cents`, lazy cert `EXPIRED`) are derived on read and never bump `version`; only stored-state mutations `touch()`. This makes the fleet-position and chargeback-balance identities hold by construction.
- `created_at` comes from the logical clock; an internal `_seq` provides deterministic ordering, selection tie-breaks and the damage-repair watermark comparison (equal-timestamp rows would otherwise be ambiguous).
- Attach that would complete `unit_count` validates the ACTIVE rate card *before* writing, so `ERR_RATE_CARD_NOT_FOUND` leaves nothing written.
- Lease `term_months` is optional at create (required only on submit), keeping the PRD's explicit submit-side `ERR_INVALID_REQUEST` path reachable.
- Assessment supersession is applied before the trailer's service-status cascade, so the end state is coherent; cascades are idempotent and keyed on the resulting OOS status.

## Boot smoke test — passed
`PORT=18999 bash start.sh` booted, `GET /fleet/trailers` returned the empty-array envelope with correct pagination meta, and a bad role header returned the `ERR_UNAUTHENTICATED` error envelope. Server killed afterwards; no stray processes remain.

Beyond boot, three end-to-end scripts (~140 assertions) all pass: full rental lifecycle with quote/settlement arithmetic, peak lease reserve, DOT-fail and damage cascades with agreement revert, forward booking, OCC, purchase option pricing, closed-interval yard capacity, relocation cost bands/surcharge/floor, supersession + waiver balance conservation, and the error-precedence paths. Store starts empty on every boot — no seeding anywhere.

**Orchestrator leak audit:** scanned the impl subagent's full transcript (158 records) for any `tool_use` whose input referenced `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, or `test_helpers/` — 0 hits. The withhold constraint held.

## Step 5: Generate unit tests — 2026-08-30T03:30:00.000Z

Test infrastructure generated and verified. Summary:

## Files written

**`test_helpers/`** (1,896 lines)

| File | Lines | Contents |
|---|---|---|
| `types.py` | 367 | 13 status/role enums + entity TypedDicts. `MaintenanceEvent` omits `updated_at`/`version` (PRD §2.5 ledger-row exception) |
| `api_client.py` | 295 | `ApiClient(GenericApiClient)`, one method per PRD §4 endpoint (56 methods) + `raw_get` for header-negative tests |
| `api_errors.py` | 121 | 53 `ApiErrorId` members + HTTP status map, registered via `set_error_http_status_map` |
| `assertions.py` | 236 | Per-entity assertions, `assert_common_fields`, `assert_fleet_position_identity` |
| `factories.py` | 213 | 15 payload factories |
| `constants.py` | 89 | Severity multipliers/points, tier deductibles, relocation cost bands, depreciation and purchase-option constants |
| `test_users.py` | 55 | Opaque-role constants + per-instance builders `make_branch_manager_headers` / `make_customer_headers` (identity threading for both `entity_backed` roles) |
| `fixtures.py` | 579 | 5 tiers: reference bootstrap -> contract lifecycle (`setup_agreement_pending_allocation/reserved/active/returned_unit`) -> damage-recovery (`setup_draft_assessment/pending_chargeback/approved_chargeback`) -> repositioning (`setup_relocation_requested/approved/in_transit`) -> `setup_settled_lease_with_purchase_option` |
| `__init__.py` | 41 | Barrel export |

**`test_suite/`** (3,183 lines, 9 test files + conftest) — **111 tests**.

## Coverage

- **Queue A (Difficulty)**: 18/18 instances translated, **2 tests each = 36 tests**. Zero skips.
- **Queue B (Corner)**: 75/75 non-stub instances translated, **1 test each = 75 tests**. Zero skips. The 4 `excluded_because:` stubs were not translated; all four `difficulty_instance` cross-references verified to resolve.

Every instance passed the PRD-first two-condition filter, so there are no gaps to report.

## Verification performed

- **C1-C3 verbatim citation audit**: every docstring quote whitespace-normalised and literal-matched against `workspace/PRD.md` — **0 failures** across all 111 tests (min 8 words per quote enforced).
- **C4 scaffold citation**: every docstring ends with exactly one `Design:` line resolving to a real, non-stub instance — 0 failures.
- `pytest --collect-only`: **111 collected**, no import errors.
- `pyflakes` clean on both directories; every `api.<method>` reference resolves to a real `ApiClient` method.
- No `skip`/`skipif`/`xfail` anywhere; no "scaffold"/§1.x/"Table N" leakage in generated comments or docstrings.

## Two judgement calls worth flagging

- `Corner/calculations/underwriting_risk_score_capped_at_100_...` asserts the risk-review response's `risk_score`/`base_points` but **not** `variant == "renewal_review"` — the PRD names the variant as "renewal review" in prose and `renewal_review` only in the §4 table, so exact casing is not uniquely derivable and asserting it would fail the two-reader test.
- Null-valued fields (`rate_card_id`, `purchase_option_price_cents`, `paid_amount_cents`, ...) are asserted with `.get(x) is None` rather than key-presence, since the PRD pins the value but not whether the serializer emits the key.

**Orchestrator verification:** 9 test files + conftest on disk; 111 `def test_` functions; 0 occurrences of `skip`/`xfail` in either directory.

## Step 7: Run tests and iterate — 2026-08-30T03:50:00.000Z

Clean exit — 8/8 rounds at 111/111.

## Summary

**Iterations run:** 2 (baseline sweep + one verifying sweep after fixes).

Baseline sweep: all 8 rounds 108/111, with the **same 3 tests failing deterministically in every round** (no flakiness signal — no test passed in one round and failed in another).

**Tests deleted:** none. All three failures traced to test-artifact bugs or a partial-coverage assertion, not to missing PRD coverage.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `fail_dot_inspection()` forwarded a hardcoded `cost_cents=9500` to `file_maintenance_event()` *alongside* `**overrides`, so any caller supplying its own `cost_cents` crashed with `TypeError: got multiple values for keyword argument 'cost_cents'` before a single request was issued. Promoted `cost_cents` to a named parameter defaulting to 9500. This was a pure fixture defect (STEP 2 / TEST IS WRONG); it killed 2 tests (`test_failed_inspection_moves_service_status_while_availability_holds_on_rent`, `test_a_unit_already_out_with_a_customer_is_not_swapped_off_its_contract`) at setup time — the implementation was never even reached.

**Fixes applied to `test_suite/` (STEP 1c partial-coverage split):**
- `test_03_underwriting_and_insurance.py` :: `test_certificate_lapses_to_expired_on_the_next_read_after_the_clock_moves` — removed the single assertion `clock["current_utc"] == "2026-09-01T00:00:00Z"`. PRD §2.4 says only that the clock endpoint "sets the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`"; it never pins that field's wire format. A faithful reader may echo the supplied instant verbatim (`...T00:00:00Z`) or normalise it to the API's three-fractional-digit timestamp convention from §2.5 (`...T00:00:00.000Z`, which the implementation does) — two divergent PRD-faithful implementations, so unique derivability is broken for that assertion. The test's PRD-verbatim core (the lazy `ACTIVE -> EXPIRED` flip on the next read, and `revoked_reason` staying null) was kept intact.

**Fixes applied to `implementation/`:** none. No implementation defect was found; all three failures were test-side.

**Deliverables:** the 8 passing `results.{1..8}.json` files remain on disk in `workspace/implementation/`. No `skip`/`xfail` exists anywhere in the test artifact, and the suite still collects all 111 tests.

**Orchestrator verification:** all 8 `results.{1..8}.json` present and each reports `passed == total == 111`; `test_suite/` still defines 111 test functions.

## Step 8: Finalize PRD — 2026-08-30T04:00:00.000Z

`PRD_FINALIZED.md` is written.

**Line counts:** PRD.md 450 lines -> PRD_FINALIZED.md 450 lines (0.0% delta; one sentence revised in place, no new lines/sections).

**Changes (1):**
- §2.4 The Logical Clock — revise — the clock-set capability now pins the wire format of `current_utc`: the supplied `to_iso8601` is normalised to UTC (a naive instant read as UTC) and answered in the §2.5 three-fractional-digit ISO 8601 UTC timestamp format (`2026-09-01T00:00:00Z` -> `2026-09-01T00:00:00.000Z`), rather than echoed verbatim — `implementation/routes/reference.py:36` (`envelope.ok({"current_utc": store.iso_ts()})`), formatter at `implementation/store.py:55-58`, normaliser at `implementation/store.py:94-106`.

**Pre-edit search log:**
- (a) Subject: the `current_utc` field returned by `POST /fleet/_clock/set_current_utc`, and the timestamp-rendering / instant-parsing convention it inherits.
- (b) Paths enumerated and read: `grep -rn "clock\|current_utc\|to_iso8601"` across all of `implementation/` — the only producer of `current_utc` is `routes/reference.py:27-36`; no GET clock endpoint exists. Read `store.iso_ts` (`store.py:55-58`), `store.parse_datetime` (`store.py:94-106`), `store.set_clock`/`now`/`clock_date` (`store.py:34-43`), and every other `iso_ts` consumer to be sure the format claim holds globally: `envelope._meta` `api_request_timestamp` (`envelope.py:11`), `store.new_record` `created_at` (`store.py:69`), `store.touch` `updated_at` (`store.py:78`), and the one derived timestamp field `last_damage_repair_at` (`routes/shop.py:67`, `serializers.py:61`, `routes/reference.py:219`). No other timestamp producer exists, so no path contradicts the §2.5 format reference.
- (c) Wording adjustment: first draft said the format is the one "used for timestamps everywhere else in this API" — a universal claim that could be misread as covering the plain `YYYY-MM-DD` date fields (`performed_on`, `dot_expires_on`, `planned_start_date`, ...). Rescoped to "the same ISO 8601 UTC timestamp format with three fractional digits that section 2.5 prescribes". Also kept the normalisation clause deliberately narrow (UTC conversion + naive-as-UTC).

No edit was made for the `test_helpers/fixtures.py` `cost_cents` fix — it is a pure fixture defect (the implementation was never reached), and PRD §3.7 already pins `cost_cents` as a required non-negative field on a shop event. No implementation fixes existed in the Step 7 diff, so there was no PRD/impl mismatch to patch.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 86, §2.4) — scope held.

## Step 9: Complete PRD — 2026-08-30T04:15:00.000Z

All 18 edits landed cleanly. File integrity verified: 450 lines (same as source), all five sections (§1-§5) present.

**Line counts:** `PRD_FINALIZED.md` 450 lines / 96,911 chars -> `PRD_COMPLETED.md` 450 lines / 101,138 chars (**+4,227 chars**, 18 lines revised, no lines added or removed).

**Counts:** 14 ambiguity-pins, 4 mismatch-revisions.

### Changes

- **§2.2 — insert — ambiguity** — `api_request_timestamp` is minted from the logical clock, not host wall time — `envelope.py:8-12`, `store.py:55-59`
- **§2.3 — insert — ambiguity** — list ties on an identical `created_at` (the frozen clock makes these common) break by server insertion order, oldest first — `store.py:121-123`
- **§2.5 — insert — ambiguity** — `created_at` is minted from the logical clock — `store.py:67-73`
- **§2.5 — insert — ambiguity** — purely derived values (`service_status`, `damage_points`, `net_book_value_cents`, certificate lapse to `EXPIRED`, yard counters, `allocated_unit_count`, `outstanding_chargeback_cents`) change with no write, so they never refresh `updated_at` or advance `version` — `serializers.py:1`, `store.py:76-81`
- **§2.7 — insert — ambiguity** — undeclared body properties (a version field on an unguarded endpoint included) are ignored, not rejected — `validate.py:11-17`
- **§2.9 step 8 — revise — mismatch** — ownership does not guard *every* `BranchManager` mutation; it guards verify-insurance, allocate, attach, activate, cancel, return and relocation-approve only. Relocation request/reject/dispatch/complete/abort carry no ownership guard — `routes/relocations.py:22,133,151,171,203` vs `:100-101`
- **§3.4 — revise — mismatch** — `term_months` is *not* required at agreement creation for `FULL_SERVICE_LEASE` (only its presence on a `SHORT_TERM_RENTAL` is rejected there); the lease requirement is enforced at submission — `routes/agreements.py:49-51` vs `:131-134`
- **§3.4 — insert — ambiguity** — the three submit gates run in the stated order, so a non-`DRAFT` lease missing its term reports `ERR_AGREEMENT_NOT_DRAFT` — `routes/agreements.py:129-134`
- **§3.4 — revise — mismatch** — the insurance-limit test applies only to the single certificate selected by greatest-expiry ordering, not to the qualifying pool — `routes/agreements.py:175-181`
- **§3.5 — insert — ambiguity** — manual attach returns the created contract unit line (not the agreement) in `data` — `routes/agreements.py:300`
- **§3.5 — revise — ambiguity** — the selector's `ACTIVE`-rate-card check runs before the candidate pool is sized, so it wins over `ERR_NO_ELIGIBLE_TRAILER` / `ERR_INSUFFICIENT_AVAILABILITY` — `routes/agreements.py:227-238`
- **§3.5 — revise — ambiguity** — availability projection: both window dates omitted => unconditional intersect; one omitted => that edge falls back to the peak boundary; intersection formula pinned as half-open vs closed; an unknown `trailer_type_id` is not an error — `routes/reference.py:96-113`
- **§3.6 — revise — ambiguity** — on return, the mileage check (`ERR_INVALID_REQUEST`) precedes the date-ordering check (`ERR_INVALID_DATE_RANGE`) — `routes/units.py:63-68`
- **§3.7 — revise — mismatch** — the damage-repair watermark is applied by server insertion order, not by `created_at` comparison; an assessment opened after the repair still counts despite an identical timestamp — `calc.py:77-89`, `routes/shop.py:67-68`
- **§3.7 — revise — ambiguity** — `passed` on `PM_SERVICE`/`DAMAGE_REPAIR` is optional, stored verbatim, reported null when omitted, and inert — `routes/shop.py:37-40`, `serializers.py:188`
- **§3.7 — insert — ambiguity** — no shop event writes the unit's `hub_miles` (only a return does), and every shop event advances the trailer's `version` — `routes/shop.py:56-69`
- **§3.8 — insert — ambiguity** — line-item `description` is optional and stored as `""`; the four declared properties are the whole stored item and extras are dropped — `routes/units.py:102-122`
- **§3.9 — revise — ambiguity** — dispatch tests `service_status` before `availability_status` (matching the §2.9 ladder, reversing the prose order) — `routes/relocations.py:156-160`

**Not changed** (verified PRD already pins impl behavior uniquely): all pricing/scoring formulas and constants, the §2.9 step-12 domain ladder for manual attach, allocation ranking and peak lease reserve, settlement rounding order, purchase-option price steps, damage liability waterfall, chargeback state machine and segregation of duties, relocation cost bands and closed-interval yard capacity, service-status precedence, and the full endpoint/role table and error catalogue (impl's `ERROR_STATUS` map matches §5 exactly, entry for entry).

**Orchestrator verification:** PRD_COMPLETED.md is 450 lines with all 5 `##` sections and 53 `ERR_` rows in §5; `diff PRD_FINALIZED.md PRD_COMPLETED.md` shows exactly 18 changed lines, 0 added/removed.

## Post-pipeline verification: mutation test of the green sweep — 2026-08-30T04:40:00.000Z

Orchestrator-run check that the passing suite is not vacuous (a green sweep alone cannot distinguish a real pass from a suite that asserts nothing).

Two mutations injected into `workspace/implementation/calc.py`:
1. `BAND2_RATE_CENTS_PER_MILE` 215 -> 216 (relocation mileage band rate).
2. `rounding=ROUND_HALF_UP` -> `rounding="ROUND_DOWN"` in the cents-rounding helper (line 61).

Single round under `--isolation per-test-server`: **107/111**, with exactly the arithmetic-sensitive tests failing:
- `test_the_forward_quote_rounds_the_whole_per_unit_charge_once`
- `test_submitting_an_assessment_prices_the_damage_and_raises_the_chargeback`
- `test_the_fuel_surcharge_trigger_is_strictly_above_five_hundred_miles`
- `test_the_actual_move_cost_diverges_from_the_planned_estimate`

The suite detects both mutations and localises them; it is live, not vacuous.

`calc.py` restored from backup and verified byte-identical to the pre-mutation file. A confirming 8-round parallel sweep was then re-run on the restored implementation: **all 8 rounds 111/111**, and `results.{1..8}.json` on disk are from that final clean sweep.

Note: the runner's `--start-command` must keep the `cd <impl dir> && bash start.sh` form. Runs issued as a bare `bash start.sh` produced `ServerStartError ... code 127` / "API server could not be restarted" on every test, which reads exactly like a total implementation failure.
