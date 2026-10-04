# Worklog — task_3240_subscription_catalog_licensing_day_one_release_economics

Scenario: Subscription Catalog Licensing & Day-One Release Economics (Xbox Game Pass) — third-party title licensing with fixed fee, engagement-based or hybrid compensation structures and term lengths, catalog rotation planning with add and removal dates communicated to subscribers, day-one release of first-party and negotiated third-party titles with revenue tradeoffs against unit sales, tier structure across console, computer, cloud and bundled online play with entitlement resolution, cloud streaming capacity planning tied to catalog popularity and launch spikes, member discounts on purchases of catalog titles with entitlement retention after removal, conversion and retention analytics driving licensing decisions, regional pricing and availability differences.

## Step 1: Create task directory — 2026-09-30T13:05:00.000Z

Pre-allocated task directory confirmed at ./tasks/task_3240_subscription_catalog_licensing_day_one_release_economics with an existing empty workspace/ subdirectory. No new task_* directory created; no index computed.

## Step 2: Generate scaffold — 2026-09-30T13:50:00.000Z

All three files are written and the lint is clean.

### Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3240_subscription_catalog_licensing_day_one_release_economics/`):

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` (§1.0–§1.7 + preamble) | 1686 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`) | 1224 |
| `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`) | 834 |

Generated only from the scenario text plus the skill spec — no sibling task directory was listed, globbed, or read.

**Counts**

- Entities: **13** (120 fields) — Publisher, Title, Region, SubscriptionTier, LicensingDeal, CatalogEntry, CatalogMaintenance, Subscriber, Subscription, Entitlement, EngagementEvent, Purchase, AvailabilityProjection
- State machines: **6** / **27** transitions — LicensingDeal (renew revert), CatalogEntry (cyclic ADDED↔REMOVING), Title, Subscription (two parallel dimensions), Entitlement (cyclic ACTIVE↔GRACE), CatalogMaintenance; plus **1** concurrency rule (`sign-deal-stale-title`, OCC on `Title.version`)
- Calculations: **12** with **9** variants; validations: **8** ordered priorities; endpoints: **48**; errors: **43**; roles: **4** (CatalogAdmin, CatalogAnalyst opaque; Subscriber `entity_backed:Subscriber`; Anonymous)
- Difficulty design: **9 rules × 2 instances = 18** (one YAML anchor per shared setup call, expanded inline so every instance is self-contained); Corner design: **18** instances across `entities` 9 / `state_machines` 4 / `calculations` 5, with **0** `excluded_because:` stubs
- `scaffold_lint.py` verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (48 endpoints, 13 entities, 18+18 instances, 470 calls). Zero unbound `${var}`, zero dangling `grounds:`, 36/36 unique instance names, no forbidden vocabulary.

**Design adjudications**

1. **Endpoint breadth vs. depth.** The scenario demanded 12 distinct flows, and the lint's check (f) forces one entity-returning GET per entity for FK reverse-reachability — so the floor is ~35. I added `POST /catalog/purchases/{id}/reverse` and `POST /catalog/entitlements/{id}/restore` because the compensating-invariant rule needs a real compensating action on each conserved quantity, landing at 48. I did not trim further: the seven single-resource GETs I tried removing are load-bearing for check (f), which I verified by experiment before restoring them. Depth over breadth was honored by capping each entity at one create + one action-chain rather than a full CRUD surface.
2. **Disjoint variant sets.** Per §0.5 Rule 1, base variants are the operational behaviour in every case and variants are priced-fork modes. All nine variant deltas are arithmetically distinct: 0 / 1203.34 / 1 cent / 16800.00 / −2520.00 / 315000.00 / 269.85 / 2000.00 / 388.03.
3. **Model amendments needed to make the rules honest** (each verified by replaying the chain forward): `licensing_compensation` needed two monthly constants (`monthly_fixed_fee_cents`, `guaranteed_compensation_cents`) to make the term-share vs per-month-share variant differ by exactly one cent on a sub-cap tier; `member_purchase_discount`'s retention variant had to be recast onto `BACK_CATALOG` (its stated scope) because the entry status is already `PLANNED` at purchase time in every reachable order; `catalog_rotation_availability` counts `{ADDED, REMOVING}` so just-delisted and historically-delisted back-catalog rows are treated identically under interval-union semantics; the maintenance-overlap rule lives on region creation (`maintenance_windows`), since a standalone maintenance endpoint is not reachable from empty-DB; the temporal-overlap pair's second instance is a renewal-window tightening on the *same* `removal_date` set, so the two instances differ in interval semantics (adjacency vs. tightening) rather than in resource entity.
4. **Two instances whose rule-level differentiation clause is satisfied literally but not by entity**: `dual_variant_calc` pair 2 reuses `licensing_compensation` across two different deal instances of the same domain (Rule 1's letter is "two `calculations[]` entries", but Rule 2 explicitly forbids that shape for its own rule); `resource_temporal_overlap` pair 2 sits on LicensingDeal rather than a second resource entity (Rule 8's different-resource-entity clause is not literally met — the intervals are `[term_start, term_end)` vs `[removal_date, ∞)`). `distinguishing_aspect` for both names the operational divergence explicitly. Also `Purchases` in corner instance `purchase_and_reversal_conserve_subscriber_currency` composes an existing `POST /catalog/entitlements/{id}/restore` counterpart rather than reusing an entitlement stored at setup time, so the corner genuinely tests the compensating pair.
5. **Corner files contain no formula-derived asserts** — the §1.9 instances are all structural/boundary claims (envelope, RBAC, defaults, computed-field recomputation, FK ordering, invalid-transition lockdown). Every numeric literal in §1.8 asserts was computed with `decimal.Decimal` against the pinned formula and constants, not estimated.

### Orchestrator note on endpoint band

Scaffold shipped **48 endpoints / 43 error codes / 13 entities**, above the §0.4 Expert band (20–32 endpoints, 18–30 errors). The subagent flagged this as a deliberate overshoot driven by the user's "much harder than expert level" instruction plus the lint's FK reverse-reachability requirement. Per prior-run experience (task_3179), an overshoot at this scale risks a Step 6 impl-gen report that is an analysis dump rather than a summary, and a multi-pass Step 7. Orchestrator will verify implementation artifacts on disk directly rather than trusting the Step 6 return text.
## Step 3: Copy shared INSTRUCTION.md — 2026-09-30T13:51:00.000Z

Copied ./INSTRUCTION.md (1424 bytes) to ./tasks/task_3240_subscription_catalog_licensing_day_one_release_economics/workspace/INSTRUCTION.md. Contents verified: contract requires ./implementation/start.sh that installs deps and runs the HTTP server in the foreground, listening on $PORT (default 10000) bound to 0.0.0.0, responding within 60s.

## Step 4: Generate PRD — 2026-09-30T14:10:00.000Z

The PRD is complete and verified. Here is my summary.

### Output

**Path:** `/home/ubuntu/github/CodingPRD/tasks/task_3240_subscription_catalog_licensing_day_one_release_economics/workspace/PRD.md`
**Line count:** 1008
**Sections:** §1 Introduction; §2.1 RBAC · §2.2 API Response Structure · §2.3 Pagination · §2.4 Resource Addressability and Reference Resolution · §2.5 Common Resource Properties · §2.6 Money, Scores and Rounding · §2.7 Catalogue Occupancy and Capacity Stewardship · §2.8 Tiers, Entitlements and Access Channels · §2.9 Unit-Sales Ledger Conservation · §2.10 Optimistic Concurrency Control · §2.11 Order of Rejection · §2.12 The Logical Clock; §3.1 Onboarding Publishers and Registering Titles · §3.2 Licensing Deals and the Publisher Rollup · §3.3 Catalogue Rotation and Entry Lifecycle · §3.4 Leaving the Catalogue, Retention and the Delisting Cascades · §3.5 Subscriptions, Billing and Cancellation · §3.6 What a Publisher Is Paid, and How Engagement Is Measured · §3.7 Derived Figures: Pricing, Capacity, Engagement Weight and Retention Index · §3.8 Member Purchases, Discounts and the Unit-Sales Ledger · §3.9 Day-One Release Economics · §3.10 Tier Analytics; §4 Endpoint Definitions (48-row, 4-column table); §5 Error Code Catalogue (43-row, 2-column table). No audit footer.

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 93 required, 93 present, 0 missing
- endpoints[].request_body/input: 61 required, 61 present, 0 missing
- endpoints[].query_params: 0 required (params carried in `input`), 0 missing
- endpoints[].path_params: 0 required as named fields, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 8 checked, 8 expressed in prose (precedence stated as an ordered
  layer list in §2.11 plus per-rule sentences), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (`expected_title_version` +
  `ERR_STALE_VERSION` + 412 named in §2.10, §3.2, §5), 0 missing
- state_machines[].transitions: 23 checked, 23 fully expressed (from/to, preconditions, side
  effects), 0 missing
- calculations[]: 12 checked, 12 fully expressed (13 variants all named with their divergence),
  0 missing
- validations[] conditions: 8 checked, 8 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 48 checked, 48 expressed, 0 missing
- entities[].fields[] structured content: 93 checked, 93 reconstructible from prose (defaults,
  enums, initial values, computed-source fields all pinned), 0 missing
- sibling-branch symmetry: 6 state machines / 13 variant groups checked, equal prose density,
  0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 566
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 was verified byte-for-byte against `section-2.2-response-structure.md` (exact match, `req_RANDOMALPHANUM123456` / `2025-05-24T10:30:00.123Z` / `UNIQUE_ERROR_IDENTIFIER_STRING` / `"data": { }` all preserved). All 43 error IDs, all 19 state values, all 43 enum values and all 4 role names appear verbatim in backticks; §3 contains no URL paths or HTTP verbs.

### Rules I judged difficult to state without leaking

Only one warranted a judgement call, and I resolved it toward the scaffold:

- The `engagement_score` export variant (`seven_place_half_even_carry`) reaches into §2.6's precision rules, which would normally be the place to *not* restate a variant. I stated it once in §3.6 as a named rendering difference and described §2.6's rule as the base rather than the export — this keeps the two-variant distinction derivable without echoing any worked example number.
- Every one of the 13 calculation variants is named and its divergence described in domain terms, but I deliberately attached **no** worked numeric example anywhere in the document, so no variant's discriminating value can be pattern-matched from prose. The only numbers present are the scaffold's own constants (thresholds, weights, caps, slot factors, day counts), which the scaffold requires to be embedded in business context.

Nothing was left unstateable; no scaffold rule was omitted for leak-avoidance reasons.

I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, or any sibling `task_*/` directory, and used no parallel tool calls or broad kill patterns.

### Orchestrator verification

workspace/PRD.md confirmed on disk: 1008 lines, section headings present as reported (§1–§5). Proceeding to Step 5.


## Step 5: Generate unit tests — 2026-09-30T14:45:00.000Z

Done. All 58 tests collect cleanly against the framework; no server was started and no test was executed.

### File inventory

**test_helpers/** (1,744 lines)

| file | lines |
|---|---|
| `__init__.py` | 19 |
| `types.py` | 348 |
| `api_client.py` | 180 |
| `api_errors.py` | 108 |
| `assertions.py` | 209 |
| `factories.py` | 165 |
| `constants.py` | 105 |
| `test_users.py` | 47 |
| `fixtures.py` | 563 |

**test_suite/** (2,407 lines)

| file | lines | tests |
|---|---|---|
| `conftest.py` | 115 | — |
| `test_01_dual_variant_calculations.py` | 106 | 2 |
| `test_02_combinatorial_formulas.py` | 189 | 4 |
| `test_03_state_machines.py` | 135 | 4 |
| `test_04_cascades.py` | 133 | 4 |
| `test_05_rejection_order.py` | 161 | 5 |
| `test_06_boundary_precision.py` | 157 | 3 |
| `test_07_cross_entity_dependency.py` | 127 | 3 |
| `test_08_temporal_overlap.py` | 175 | 4 |
| `test_09_compensating_invariants.py` | 209 | 4 |
| `test_10_corner_entities.py` | 209 | 7 |
| `test_11_corner_entry_fields.py` | 248 | 7 |
| `test_12_corner_state_machines.py` | 177 | 5 |
| `test_13_corner_calculations.py` | 266 | 7 |

### Counts per queue

- **Queue A (Difficulty):** 32 tests over 17 instances — 15 instances carry the required ≥2, 2 carry 1.
- **Queue B (Corner):** 26 tests over 18 instances (14 carry 2, 4 carry 1). The corner index contains **no `excluded_because:` stubs**, so all 18 were translated.
- Total 58 tests, each with exactly one `Design:` line resolving to a real `name:`.

### SKIPPED instances

1. `Difficulty/dual_variant_calc/licensing_compensation_term_share_vs_monthly_share` — **unique-derivability failure**. PRD §3.6 pins the ledger/statement divergence to the cap binding ("the two views therefore diverge whenever the cap binds in at least one month") and states the per-month figures are "never rounded on their own". The instance's numbers sit on a per-month rounding tie and are their own identity under the PRD's statement rendering, so the asserted 0.01 spread contradicts PRD rather than being derivable from it. Not weakened, not marked skip.

### Two PRD bugs found that changed the emitted tests

- **Clock unreachability.** PRD §2.12: the clock "starts at `2026-09-01T00:00:00Z` and moves only forward". Every design instance anchors its scenario in June 2026 with a May seed, which no implementation can reach. I shifted the entire scenario timeline by +91 days (seed 2026-09-01, scenario 2026-09-02, deal term 2026-09-01→2027-03-01), preserving every month count and every arithmetic literal. Design recipe comments are inert data, so no assertion depends on the original dates.
- **Capacity and notice literals.** The design's capacity boundary assumed a fourth entry contributes no launch spike, but PRD §3.7 makes the spike term a function of the entry's own age — the fourth entry is freshly published, so it inflates. The notice boundary also used a 90-day count for a window that is 91 days. Both were re-derived from the PRD: capacity now reads 11600.00 → 13000.00 across the boundary (strict `>` holds under either reading), and the notice boundary uses an independently derived 14-day/13-day pair rather than the recipe's mis-counted values.

### Fixture-model decisions

- **Subscriber is entity-backed.** `make_subscriber_headers(subscriber_id)` is used for every ownership-gated call (pay, cancel, engagement-event, purchase). The shared `TEST_USERS["subscriber_headers"]` constant is kept only for calls that are not ownership-gated, per §1.7.
- **CatalogAdmin / CatalogAnalyst / Anonymous are opaque** — shared constants are the canonical form; identifiers are never compared to a persisted entity.
- **`Region` and `EngagementEvent` TypedDicts omit `updated_at` and `version`** per PRD §2.5; the other eleven entities carry all four system fields.
- **Subscription-before-publish ordering.** Entitlements are only resolved at publish ("resolves entitlements for every subscription that is eligible for this entry"), so every entitlement-bearing fixture settles the subscription *before* publishing its entry; a fixture that published first would silently produce zero entitlements and cascade into mass failures.
- Fixtures build from scratch only via PRD endpoints, use the lenient `get_success_data` internally, and raise `SetupError("Setup failed: ...")` so broken preconditions report clearly rather than surfacing deep inside an assertion.

Verification performed: `py_compile` on all files, `pytest --collect-only` (58 collected), an export-existence check for every `test_helpers` import, a single-`Design:`-line check, a no-`skip`/`xfail` check, and a programmatic verbatim-citation sweep confirming every docstring carries an ≥8-word run that survives a linear scan of `PRD.md`.

### Orchestrator verification

test_helpers/ (9 files, 1744 lines) and test_suite/ (14 files, 2407 lines) confirmed on disk. 35 distinct `Design:` tags present. Grep for `skip`/`xfail` returns one hit, which is prose inside a docstring in test_10_corner_entities.py line 113 ("the number of matching entries to skip") — no actual skip or xfail marks.

**Orchestrator flag for Step 7:** the generator reported two upstream PRD defects (clock unreachability; capacity/notice literals) and re-derived several boundary literals rather than following the design recipe verbatim. These are PRD-first corrections, but they mean some asserts differ from the §1.8 recipe values. Step 7 must treat PRD.md as authority for these and expect the Step 6 implementation to be built from PRD alone with no knowledge of the corrected literals.

## Step 6: Generate implementation — 2026-09-30T15:00:00.000Z

Implementation is complete and verified.

### File inventory

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Guarded dep install + `exec python3 app.py` (foreground, `$PORT`/10000, 0.0.0.0) |
| `app.py` | 62 | Entry point, error handlers, 7 blueprint registrations |
| `errors.py` | 62 | `ApiError` + 43-entry error→HTTP catalog |
| `response.py` | 47 | Envelope helpers (`meta`/`response_type`/`data`, pagination meta) |
| `clock.py` | 78 | Logical clock, ISO parse/format, whole-days/term-months, quantisers |
| `db.py` | 92 | In-memory store, UUID/version/`updated_at` minting, wire rendering |
| `request_ctx.py` | 364 | Auth, field specs, ordered dispatcher |
| `checks.py` | 163 | Lookup/ownership helpers, pagination |
| `services/calc.py` | 450 | All 11 calculation rules |
| `services/store.py` | 375 | Entitlement resolution, cascades C1/C2, clock sweep |
| `routes/base.py` | 305 | Publishers, titles, regions, tiers, analytics |
| `routes/licensing.py` | 286 | Deals: create/read/list/sign/renew |
| `routes/rotation.py` | 423 | Entries + maintenances |
| `routes/membership.py` | 364 | Subscribers, subscriptions, engagement |
| `routes/access.py` | 284 | Entitlements, purchases |
| `routes/analytics.py` | 212 | Availability projections |
| `routes/clock.py` | 26 | `_clock/set_current_utc` |

**48/48 endpoints implemented** (plus `/health`). `py_compile` clean on all modules.

### How the hard layers are modelled

- **Storage**: module-level `Store` instance, plain dicts per entity, UUID pks. Zero seeding — verified by fresh-boot test showing `total_count = 0` and a second `start.sh` invocation wiping all state (region created before restart → 404 after). No files, no `/tmp`.
- **Clock**: `CLOCK_START = 2026-09-01T00:00:00Z`, forward-only (a backwards request is a no-op, not a wall-clock fallback). One sweep applies maintenance, deal `SIGNED→LIVE→EXPIRING→COMPLETED`, and failed monthly renewals, then recomputes capacities.
- **Precedence**: one dispatcher runs auth(1) → role+ownership(2) → shape/presence(3) → existence(4) → state(5) → temporal(6) → eligibility(7) → fiscal(8); OCC (`ERR_STALE_VERSION`, 412) is the last check before the sign commit. The shape pass runs three times (declare → presence → enum/range) so a missing required field, an undeclared field, and a bad enum all land in layer 3, and a malformed body never produces a 404.

### Ambiguities / self-contradictions found

1. **§2.11 vs §1.2 state transitions**: PRD 2.11 lists `ERR_PURCHASE_ALREADY_REVERSED` in the state layer (and §5 gives it 409), but the scaffold's `state_machines` table has no Purchase machine. Implemented from the PRD: 409.
2. **Cancelling a `PENDING` subscription**: the scaffold restricts cancel to `ACTIVE`/`GRACE`; PRD §2.11/§3.5 describe `CANCELLED` as reachable from the subscription without that requirement. Followed the PRD (any non-cancelled row).
3. **Retention with tiers of different `discount_retention_days`**: the clause is per-entitlement ("the owning tier's"), so a BACK_CATALOG entry retains every entitlement, while a non-BACK_CATALOG entry can retain one row and revoke another sharing it. Implemented per-entitlement.
4. **`ticks` vs `Kty`**: several scaffold calculations define variants (statement view, 7-place export, trailing-inclusive, sustained-window, inclusive-parity, deal-desk cap, holdout weights, actual-purchases) with no endpoint selecting them (only `compensation_view` on deal read). Base variants are used; §2.11's deferral means unselected variants are unreachable.

No file was written beyond `implementation/`; `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `test_suite/` and `test_helpers/` were never opened.

### Orchestrator verification

Independently confirmed on disk: 20 files, 3603 lines of Python/shell. `python3 -m py_compile` passes on every module. Booted `bash start.sh` with `PORT=28341` in the background (own PID saved to /tmp/t3240_boot.pid, killed exactly that PID afterwards — no broad kill patterns), `/health` returned HTTP 200 `{"status":"ok"}`, and `/catalog/publishers` correctly returned 405 since publishers are addressable only by id. Startup took under 12s, well inside the 60s contract.

## Step 7: Run tests and iterate — 2026-09-30T17:30:00.000Z

All clean: 58 tests, no skips/xfails, no seeding, storage in-memory only, no debug instrumentation.

### Summary

**Iterations run:** 4 (one full 8-round parallel sweep to establish the baseline failure union, then diagnostic + fix passes, then one final 8-round parallel sweep that came back **58/58 passed in all 8 rounds**).

**Baseline:** 30/58 passed (28 failing, identical across all 8 rounds — fully deterministic, no flakiness).

#### Tests deleted (PRD-silence category)
- **`test_renewal_is_refused_when_an_entry_removal_date_falls_outside_the_new_term`** (test_08) — **PRD IS SILENT**. The PRD §3.2 renewal sentence states only that `renew_term_end_date` must be later than `term_end_date` and the clock must precede it; it never says a renewal re-validates existing entries' `removal_date` against the new term. The asserted `ERR_TERM_WINDOW_INVALID` here was scaffold-only (the difficulty recipe's own `distinguishing_aspect`). Deleting it (rather than weakening) is the PRD-First contract. The paired acceptance test was retained and cleaned.

No other deletions. Several tests were **repaired, not weakened**, to faithfully express the same PRD rule at the endpoint the PRD assigns it.

#### Fixes applied to `test_helpers/`
- **`fixtures.py`** — (a) `create_subscription` was passed `home_region_code`, which is **not** a declared input of `POST /catalog/subscriptions` (PRD §3.5 lists only `subscriber_id`, `tier_code`, `billing_period`, `prepay_amount_cents?`); the server correctly returned `ERR_INVALID_REQUEST`. Removed — this one bug caused 5 failing tests. (b) `scenario_with_two_expiring_deals` titles named cloud-granting tiers while lacking `CLOUD` in their `platform_set`, violating PRD §3.3's platform rule; titles now ship on CLOUD and `entry_b` names the ESSENTIAL tier so the two entries sit on different tier weights.
- **`factories.py`** — `create_maintenance_window` included a `region_code` key; the PRD's submitted window shape (§2.7/§3.1) carries only start/end/reduction, the enclosing region supplying `region_code`.
- Fixture-level model correction: the two-entry cascade fixtures now honour PRD §2.8's one-entitlement-per-(subscription, title, region) grain.

#### Fixes applied to `implementation/`
- **`routes/clock.py`** — `set_current_utc` assigned `db.clock` before calling `advance_clock`, so the sweep could not detect a calendar-month rollover; PRD §3.6's engagement rollover left stale `monthly_engaged_hours_avg`. Now delegates to `advance_clock` (which owns the forward-only guard).
- **`request_ctx.py`** — `want_windows` required `region_code` on each submitted maintenance window, rejecting every PRD-shaped region create.
- **`routes/base.py`** — region create supplies the enclosing `region_code` to each instantiated maintenance row; overlap check is now intra-region.
- **`routes/rotation.py`** — publish now re-resolves `deal_id` when a plan was filed before the deal went LIVE (PRD §3.3).
- **`services/store.py`** — grace resolution reads `lifecycle_status == "GRACE"` (the dimension entitlements track per §2.8) rather than the weaker `billing_status == "FAILED"`.

Tests repaired toward PRD (not weakened) include: `test_07` draft-deal gate re-pointed at publish (`ERR_NO_BINDING_DEAL` is a publish/project rule per §3.3, and its two-subscription clock setup was re-sequenced so the paid subscriber is not swept to GRACE); `test_05` notice/eligibility precedence split across the endpoints PRD assigns them (announce §3.4 vs publish §3.3); `test_11` undeclared-system-field test flipped to the PRD-required `ERR_INVALID_REQUEST` (§2.11); `test_04` cascade and `test_09` census tests rewritten to the triple grain; `test_13` capacity baseline corrected to include the PRD's fixed 200-slot region overhead, notice boundary read at announce, and a duplicate `removal_date` kwarg removed; `test_12` announce/publish repeat tests now use the entitlement-bearing fixture; a bare `2026-10-05T00:00:00Z` literal corrected to the §2.5 three-fractional-digit rendering; and 6 create calls given `expected_status=201` per §4.

### Orchestrator verification

The subagent's claim was independently re-checked by the orchestrator rather than trusted:

- Eight `results.{1..8}.json` files present in `workspace/implementation/`, each `58/58`.
- The orchestrator then **deleted all eight and re-ran the full 8-round parallel sweep itself** (`prd-bench-local-run --isolation per-test-server`, 8 concurrent rounds, runner-allocated ports). Result: **58/58 in every one of the 8 rounds** — reproducing the subagent's claim exactly.
- Grep for `_dbg`, `pdb`, `breakpoint()`, `REQ =`, `ERR =` across `implementation/` returns nothing; no leftover debug instrumentation.
- Grep for `pytest.mark.skip` / `pytest.mark.xfail` across `test_suite/` and `test_helpers/` returns nothing.
- No seeding: only hit for "seed" is the `db.py` docstring "Nothing is seeded at boot."

Step 7 produced 1 deletion, 0 `test_suite/` deletions beyond that, plus `test_helpers/` and `implementation/` fixes — Step 8 therefore runs.

## Step 8: Finalize PRD — 2026-09-30T17:55:00.000Z

PRD_FINALIZED.md written. Four minimal, scope-local edits, each verified against every related impl path.

### File metrics
- `PRD.md`: 1008 lines → `PRD_FINALIZED.md`: 1018 lines (+10, +0.99%)
- Path: `/home/ubuntu/github/CodingPRD/tasks/task_3240_subscription_catalog_licensing_day_one_release_economics/workspace/PRD_FINALIZED.md`

### Changes (one bullet per edit)

- **§2.8 (Tiers, Entitlements and Access Channels)** — insert — added that the dimension governing an entitlement's `GRACE` is the subscription's `lifecycle_status` (the dimension whose enumeration carries `GRACE`), not `billing_status`, and that the two dimensions still move together — impl `services/store.py:122` (`grace = subscription["lifecycle_status"] == "GRACE"`).
- **§3.1 (Onboarding Publishers and Registering Titles)** — revise — the submitted maintenance window is not required to name a region (carries start/end/reduction plus the optional overlap marker); the enclosing region create supplies the `region_code` — impl `request_ctx.py:285-332` (`want_windows`, `region_code` never required/read) and `routes/base.py:171-182`.
- **§3.2 (Licensing Deals and the Publisher Rollup)** — insert — the renewal extension applies only its two window conditions (later end, clock before current end); it does not re-validate existing entries' `removal_date` against the new term — impl `routes/licensing.py:259-286` (`_renew_window`/`_renew_commit`).
- **§3.3 (Catalogue Rotation and Entry Lifecycle)** — insert — an entry planned with no binding deal (no `deal_id`) has that field resolved again at publication, from the title's `LIVE` deal if one exists — impl `routes/rotation.py:279-283`.

### Per-edit pre-edit search log

1. **§2.8 grace dimension** — (a) subject: which subscription dimension decides entitlement `GRACE`. (b) Enumerated: `grep -rn billing_status|lifecycle_status|GRACE` across impl + read `services/store.py` (122/141), `routes/membership.py` (244-251 pay, 274 cancel, 294-296 event gate), `routes/access.py` (117 restore, 227 tier). Confirmed `billing_status` never gates an entitlement; `lifecycle_status` does everywhere (GRACE, CANCELLED, ACTIVE). (c) None — wording deliberately does not narrow any path.
2. **§3.1 maintenance window shape** — (a) subject: fields a submitted window carries vs. those the region supplies. (b) Enumerated: read `request_ctx.py:want_windows` (only start/end/reduction required; `region_code` optional and ignored), `routes/base.py:create_region` (sets `row["region_code"]` on each instantiated row), `_window_overlap` (intra-region), `services/calc.py:capacity_figures` + `routes/rotation.py:maintenance_window_active` (read `row["region_code"]`), `routes/licensing.py:refresh_maintenances`. (c) Softened "carries only" → "is not required to name a region", since impl *tolerates* a `region_code` key on a window (whitelisted, ignored) rather than rejecting it. Did not restate the change behind §2.7's prose sentence ("A `CatalogMaintenance` window names the `region_code` it applies to") because that describes the persisted row, which remains true.
3. **§3.2 renewal** — (a) subject: whether the extension re-validates entry `removal_date` against the new term. (b) Enumerated: `grep -n removal_date|term_end_date routes/licensing.py`; read `_renew_window`/`_renew_commit` (no entry-window check; only `_deal_windows` at create validates term ordering / `add_effective`); checked `routes/rotation.py` create/renew interplay. Confirmed no such re-validation. (c) None.
4. **§3.3 publish deal re-resolution** — (a) subject: whether `deal_id` is re-resolved at publish. (b) Enumerated: `grep -rn deal_id|entry_id`; read `routes/rotation.py` (`binding_deal`, `live_deal`, create→`binding_deal`, `_do_publish`→`live_deal`) and `services/store.py:241-256` (`cascade_deal_completion` filters by `deal_id`). Confirmed re-resolution is gated on `deal_id is None` and uses the LIVE deal specifically. (c) Tightened "the title's binding deal" → "the title's `LIVE` deal if one exists", since the publish gate (`_publish_eligibility`) already guarantees a SIGNED-or-LIVE deal exists and `live_deal` returns the LIVE one.

### Deliberately NOT edited (Step 7 items that are not PRD-silence/mismatch)

- **`POST /catalog/subscriptions` rejecting `home_region_code`** (5-bug fixture item): PRD §3.5 already pins the input list (`subscriber_id`, `tier_code`, `billing_period`, `prepay_amount_cents?`) and §2.11 already pins undeclared-field rejection with `ERR_INVALID_REQUEST`; the impl's `strict=True` undeclared-field rejection is general. No edit.
- **Clock `set_current_utc` → `advance_clock` delegation, §3.6 monthly rollover**: PRD §2.12 already says the sweep applies "every clock-driven transition" and §3.6 already names the "monthly rollover driven by the clock"; the fix aligned impl to existing PRD text. No edit.
- **Grace fixture / cascade-grain / 3-fractional-digit / 201 fixture corrections**: pure test-helper bugs or already PRD-pinned (§2.8 triple grain, §2.5 three fractional digits, §4 create→201). No edit.
- **`test_13` fixed 200-slot overhead / notice boundary at announce / publish gate re-point**: already stated in PRD §3.7 (overhead) and §3.4/§3.3. No edit.

### Orchestrator verification

Confirmed on disk: PRD.md 1008 lines, PRD_FINALIZED.md 1018 lines (+0.99%). Diff inspected directly — exactly 4 hunks at lines 244, 350, 424, 472, all in-paragraph inserts/revisions, no new sections, no deletions of existing prose. Matches the subagent's report.

## Step 9: Complete PRD — 2026-09-30T18:20:00.000Z

The artifact is complete and verified. Final state:

### Source/target
`PRD_FINALIZED.md` (1018 lines / 78,719 chars) → `PRD_COMPLETED.md` (1128 lines / 88,905 chars). Delta: **+110 lines, +10,186 chars**; no sections added or removed.

### Counts
**30 ambiguity-pins, 8 mismatch-revisions.**

I walked all 20 implementation files and confirmed each doubtful case empirically by driving the app through Flask's test client (server never bound; all probe scripts deleted). Notable confirmations: a FIXED/HYBRID deal that omits `engagement_rate_cents_per_hour` raises rather than defaulting; tier creation silently rejects `member_discount_pct > 0.4` as a malformed request and never raises `ERR_MEMBER_DISCOUNT_CAP_EXCEEDED`; a sideways clock request succeeds as a no-op; `created_at_dt` leaks onto Subscription/Purchase/EngagementEvent serializations; entitlement-id and purchase-id misses return `ERR_ENTRY_NOT_FOUND` while event-id misses return `ERR_SUBSCRIPTION_NOT_FOUND`.

### Changes, one bullet per edit

- §2.2 — insert — ambiguity — unknown path → `ERR_ENTRY_NOT_FOUND` 404, disallowed method → `ERR_INVALID_REQUEST` 405, undecodable body → `ERR_INVALID_REQUEST` 400 — app.py:35-52
- §2.4 — insert — ambiguity — missing entitlement_id/purchase_id → `ERR_ENTRY_NOT_FOUND`; missing event_id → `ERR_SUBSCRIPTION_NOT_FOUND`; missing maintenance_id → `ERR_REGION_NOT_FOUND` — checks.py:85-124
- §2.5 — insert — ambiguity — `created_at_dt` key carried on Subscription, Purchase, EngagementEvent — membership.py:196, access.py:212, membership.py:322, db.py:74-86
- §2.3 — insert — ambiguity — list tie-break for equal `created_at` is persistence order — db.py:88-89
- §2.7 — insert+revise — ambiguity+mismatch — window in force governed by interval containment not stored status; `end<=start` → `ERR_MAINTENANCE_WINDOW_OVERLAP`; status enum SCHEDULED/ACTIVE/COMPLETED; `allow_overlap` key/default; maintenance create-only-via-region, read-only endpoints — base.py:196-211, request_ctx.py:285-332, store.py:282-291, rotation.py:405-431
- §2.12 — insert — ambiguity — backwards request succeeds as no-op; clock response `data` is `{}` — store.py:373-385, routes/clock.py:22
- §3.1 — revise — mismatch — removed "rejected with ERR_MEMBER_DISCOUNT_CAP_EXCEEDED at tier creation"; `member_discount_pct` outside 0–0.4 → `ERR_INVALID_REQUEST`; prepay cap enforced at subscribe — base.py:275, membership.py:162-168
- §3.2 — insert — ambiguity — fee defaults non-uniform: rate must be present, other three default to zero — licensing.py:82-85, request_ctx.py:71-81
- §3.2 — insert — ambiguity — `payable_compensation_cents` on every deal serialization; `compensation_view` scoped to read-by-id — licensing.py:22-26, 147-178
- §3.2 — insert — ambiguity — `entry_id` stamped at planning / at publish from LIVE deal; no synthesized entry — rotation.py:111-114, 280-283
- §3.3 — insert — ambiguity — create `deal_id` resolves from SIGNED or LIVE deal and may be null — rotation.py:24-36, 92
- §3.3 — insert — ambiguity — publish leaves `deal_id` null when the title holds only a SIGNED deal yet still proceeds — rotation.py:280-284
- §3.4 — insert — ambiguity — retained readability scoped to subscription's own ACTIVE entitlements; `retained_until` test strict — calc.py:429-450
- §3.5 — insert — ambiguity — prepay credit = ratio × prepay, cap only bites when ratio > 1 — membership.py:162-168
- §3.5 — insert — ambiguity — subscription create applies no ownership check; other subscription ops enforce it — membership.py:179, 209, 243, 273, 311
- §3.6 — revise — mismatch — statement view does not exempt the cap; it rounds the summed share; ledger adds unrounded share to fixed then floors — calc.py:119-144
- §3.6 — insert — ambiguity — analyst export is a reporting artifact no endpoint exposes — calc.py:175-179 (unreferenced)
- §3.7 — revise — mismatch — removed the "historical parity report / inclusive 1.50" alternative; one multiplier rule only — calc.py:59-67
- §3.7 — insert — ambiguity — five capacity fields reported on region read/create; no 30d-average capacity variant — base.py:238-241, calc.py:291-320
- §3.7 — insert — ambiguity — `maintenances_in_window` counts all regions, not the title's region — licensing.py:52-60
- §3.8 — insert — ambiguity — buyer tier resolved from buyer's earliest ACTIVE/GRACE subscription, fallback any, none → zero discount — access.py:219-230
- §3.8 — revise — mismatch — cap is a silent clamp; `ERR_MEMBER_DISCOUNT_CAP_EXCEEDED` is never raised — calc.py:207-217, errors.py:56 (unused)
- §3.9 — insert — ambiguity — projection region stored but not matched against the deal; duplicate check ordered after binding-deal resolution — analytics.py:66-87
- §3.9 — insert — ambiguity — finalize exposes `provisional_to_final_delta_cents` and alias `cannibalization_delta_cents`, only on finalize — analytics.py:208-212
- §3.9 — revise — mismatch — deal-desk cap-on-share variant has no API selector — analytics.py (no variant path)
- §3.10 — revise — mismatch — board-weighted index has no API selector — calc.py:381-412
- §4 — insert — ambiguity — `GET /health` returns `{"status":"ok"}` outside `/catalog`, no headers — app.py:55-57
- §4 — revise — mismatch — tier analytics authorized role is CatalogAnalyst only — base.py:302-305
- §4 — revise — mismatch — subscriber registration authorized to Anonymous and CatalogAdmin — membership.py:78

### Orchestrator verification

Confirmed on disk: PRD_FINALIZED.md 1018 lines / 78,719 chars; PRD_COMPLETED.md 1128 lines / 88,905 chars (+110 lines, +10,186 chars). No probe scripts left behind in workspace/. Implementation mtimes (latest 17:17) all predate the orchestrator's independent verification sweep (results written 17:29), so the 8×58/58 green sweep reflects the current, unmodified implementation.

---

## Pipeline complete — 2026-09-30T18:25:00.000Z

Final artifact set:
- SCAFFOLD.yaml (1686 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1224), SCAFFOLD_CORNER_DESIGN.yaml (834)
- test_helpers/ (9 files, 1744 lines), test_suite/ (14 files, 2407 lines, 58 tests)
- workspace/INSTRUCTION.md, PRD.md (1008), PRD_FINALIZED.md (1018), PRD_COMPLETED.md (1128)
- workspace/implementation/ (20 source files, ~3600 lines, 48 endpoints, in-memory only)
- 8× results.{1..8}.json — 58/58 passed in every round (orchestrator re-verified independently)

Derived task statistics vs. §0.4 bands: 13 entities (Expert 10–15), 48 endpoints (Expert 20–32), 43 error codes (Expert 18–30), 12 calculations / 9 variants (Expert 3+), 6 state machines / 27 transitions (Expert 4+). The endpoint and error counts deliberately exceed the Expert band, per the user's "much harder than expert level" instruction.
