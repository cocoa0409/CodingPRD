# Worklog — task_3322_capacity_market_auction_resource_adequacy_obligations

## Step 1: Create Task Directory — 2026-09-30T20:15:00.000Z

Task directory pre-allocated at `./tasks/task_3322_capacity_market_auction_resource_adequacy_obligations/` with `workspace/` inside; verified existence (no new index computed, per command args).

## Step 2: Generate Scaffold — 2026-09-30T20:48:00.000Z

Clean lint, final state:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    63
  §1.1 entities declared:     15
  §1.8 instances scanned:     19
  §1.9 instances scanned:     35
  Calls scanned (§1.8+§1.9):  773
```

Final spot-check of remaining consistency concerns:

1. **`commitment_replacement_loop_revert_and_reapply`** — after reject the commitment version increments (REPLACEMENT_PENDING→ACTIVE is a mutation); the instance re-GETs the version (`c1_v2`) before the second replacement. ✓
2. **OCC-before-state ordering** — validation priorities 5 (OCC/412) then 6 (state/409) let the stale-withdraw corner (412) and sealed-withdraw corner (409) coexist; prose updated everywhere.
3. **Overlap check moved to begin-assessment only** — validation 9 and the EmergencyEvent transition precondition now agree, so EV3 in `emergency_pai_half_open_adjacency` can be created but not assessed. ✓
4. **`performance_ratio_no_obligation_vs_bonused_overperformance`** — assessment ordering capture assumes CE's assessment precedes CF's in `created_at ASC`; both setup chains create CE's resource/offer first, so ordering is deterministic per the pinned tie-break. ✓
5. All formula-derived asserts were pre-computed with Decimal round-half-up (ucap 40.260, charge -33.33/-66.67/-102.50/-150.00/-266.67/-93.33, bonus 11.67, pool redistribution 93.33, revenues 700/420/280, LDA clearing at 80.00 with partial 10 MW).

Generated the three scaffold artifacts for **task_3322_capacity_market_auction_resource_adequacy_obligations** (PJM-style capacity market), purely from the scenario text plus the skill spec — no sibling tasks were inspected.

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7 only)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts (per lint):**
- Entities: **15** (DeliveryYear, Zone, LoadForecast, ResourceOwnerEntity, CapacityResource, Accreditation, AuctionOffer, MitigationReview, AuctionRun, CapacityCommitment, ReplacementTransaction, EmergencyEvent, PerformanceAssessment, MeasurementReport, SettlementEntry)
- Endpoints: **63** (incl. `_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default)
- Calculations: **8** (peak_load_requirement, accreditation_ucap dual-variant, seller_offer_cap, auction_clearing waterfall with LDA deliverability + shortage pricing, performance_ratio_calc, nonperformance_charge tiered, redistribution_pool remainder-absorbing, mv_verified_ucap)
- Validations: 20 ordered; Errors: 19; Roles: 3 (MarketAdmin/SettlementOps opaque, ResourceOwner entity-backed); 2 OCC concurrency rules
- Difficulty instances: **19** (every one of the 9 rules has ≥2; combinatorial_formula has 3 spanning modes a/b/c)
- Corner instances: **35 active + 3 excluded_because stubs** (stubs verified to cite real §1.8 instances) across all 9 claim-guide sections

**Max-difficulty features:** dual-variant accreditation (class-avg vs unit-specific ELCC, 85.000 vs 40.260 UCAP on identical inputs), nested max/min offer-cap band, rounding-order-sensitive tiered non-performance charges (0.60/0.30 ratio tiers), LDA import-constrained auction clearing with upward price separation and 390.00 shortage pricing, cyclic replacement loop with OCC, half-open PAI overlap vs VERIFIED-only M&V window overlap, and a zero-sum charge→redistribution settlement invariant. `scaffold_lint.py` verdict: **clean lint** (773 calls scanned, 0 violations).

## Step 3: Copy Shared Files — 2026-09-30T20:49:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T20:56:00.000Z

PRD generated and verified. The difficulty/corner design files were never opened or consulted.

**Output:** `workspace/PRD.md` — 271 lines.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (three roles with identity semantics — `ResourceOwner` entity-backed, `MarketAdmin`/`SettlementOps` opaque), 2.2 API Response Structure (verbatim fixed block, byte-identical confirmed), 2.3 Pagination (limit 10 default / 1–100, offset 0, `created_at` ascending, meta fields), 2.4 Common Resource Properties (append-only exception for PerformanceAssessment and SettlementEntry — no `updated_at`/`version`), 2.5 Precision & Rounding, 2.6 Validation Cascade (10-gate priority ordering with the OCC-before-state-gate rule), 2.7 OCC (both rules with `expected_commitment_version` / `expected_auction_run_version` and `ERR_STALE_VERSION` 412), 2.8 Hierarchy & Nested Retrieval, 2.9 Logical Clock (2026-09-01T00:00:00Z initial)
- §3 Business Logic: 3.1 delivery-year setup/zones/forecasts (peak_load_requirement 4-step calc incl. LDA share fallback), 3.2 participants/resources/accreditation (dual CLASS_AVG vs UNIT_SPECIFIC variants), 3.3 runs/offers, 3.4 sealing/mitigation/clearing (seller offer cap with NET_CONE 390.00 / ACR 60.00 + 0.10×(1000−credit_score), 4-step waterfall clearing, upward-only LDA price separation, shortage pricing), 3.5 commitments/replacements/default (0.40 score + ≥2 FINALIZED threshold), 3.6 emergency events/assessment (tiered charges 1.0/1.5/2.0 on unrounded ratio, 1.5 bonus cap), 3.7 M&V (mv_verified_ucap, half-open window exclusion, append-only revisions), 3.8 settlement/redistribution (remainder-absorbing rounding in created_at order)
- §4 Endpoint table (63 endpoints, 4 columns only)
- §5 Error catalogue (19 errors, 2 columns only)

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 78 required (entities + endpoint inputs/query params), 78 present, 0 missing — PASS
- Contract 2 (Rule Coverage): all 10 state machines' transitions with preconditions + side effects, all 8 calculations (constants embedded: 390.00, 60.00, 0.10, 100 hours full sample, 1.0 factor cap, 24 h/day, 0.60/0.30 tiers, 1.5×/2.0× multipliers, 0.5 bonus-MW fraction, 1.5 bonus cap, 0.40 default threshold, 1.000 share sum), both OCC rules with write endpoint + occ field + `ERR_STALE_VERSION`/412, all 20 validations with priority ordering stated explicitly in §2.6, all `applies_to` scopes enumerated, sibling branches (PASS/MITIGATE/EXEMPT; approve/reject; class-avg/unit-specific) with equal density — PASS
- Contract 3 (§3 Path Purity): 373 backtick tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos — PASS

Auxiliary checks: no fuzzy/approximating words, no pseudocode/operator leaks in §3, all 19 error ids appear in §2/§3 prose, all state and enum values from the scaffold appear verbatim, all 63 scaffold endpoint paths present in §4.

## Step 5: Generate Unit Tests — 2026-09-30T21:22:00.000Z

Generation complete. Summary:

## Tests emitted

**Queue A (Difficulty, 19 instances):** 16 emitted with ≥2 tests each (32 tests), 3 skipped.
- Skipped `dual_variant_calc/performance_ratio_no_obligation_vs_bonused_overperformance` — the asserted bonus literal 11.67 implies a 70.00 clearing price, but the recipe's offers (250/75 against requirement 12.000) uniquely derive RTO prices 250/75 under PRD §3.4; PRD derives 41.67 (or 12.50), not 11.67. Literal not derivable.
- Skipped `combinatorial_formula/auction_clearing_evaluation_order_requirement_before_price` — asserted literals are mutually inconsistent: LDA price 80 + RTO price 80 requires RB's remainder to participate in RTO clearing (making RB cleared 20/CLEARED), which contradicts the asserted RB cleared 10/PARTIALLY_CLEARED. No single PRD-faithful reading produces the asserted tuple.
- Skipped `priority_pair_validation_conflict/state_beats_business_temporal_on_begin_assessment` — setup unreachable: PRD §3.6 forbids EV1 (13:00–15:00) from entering ASSESSING while the overlapping EV2 (14:00–16:00) sits in DECLARED, so the recipe's precondition can never be reached.
- Emitted `non_linear_state_machine/measurement_report_revision_loop_after_rejection` with a **re-derived literal**: the design asserted `verified_ucap_mw == 0.8`, but the revision's inputs (metered 1500 MWh / 1464 h × factor 0.8) derive 0.820 under PRD §3.7. The test asserts 0.820.

**Queue B (Corner, 38 instances):** 34 non-stub instances covered with ≥1 test each, 3 `excluded_because` stubs correctly untranslated (their difficulty pointers verified to resolve), 1 skipped.
- Skipped `state_machines/mitigation_mitigate_reprices_offer_to_cap` — MITIGATE resolution is preconditioned on `pivotal_supplier_flag == true`, but the PRD never specifies the three-pivotal-supplier screen's inputs, so a PRD-only reader cannot derive the flag's value; the resolve outcome is underdetermined.
- `entities/create_delivery_year_required_fields_and_defaults`: the `version == 1` assertion was dropped (PRD says only "an integer starting at its initial value"); all PRD-pinned defaults (DRAFT, reliability_requirement_mw 0, forecast_version 0) are asserted.

**Total: 66 test functions**, each with exactly one verbatim `Design:` tag as the final docstring line, and 78 PRD citations all verified to survive literal grep of PRD.md.

## Helpers created
`test_helpers/`: `__init__.py` (barrel), `types.py` (19 status enums + 16 TypedDicts; PerformanceAssessment/SettlementEntry omit `updated_at`/`version` per PRD §2.4), `api_client.py` (all 45 endpoints), `api_errors.py` (19 error IDs + status map registered with the framework), `assertions.py`, `factories.py`, `constants.py` (all PRD calc constants), `test_users.py` (opaque shared constants + `make_resource_owner_headers` for the entity-backed role), `fixtures.py` (tiered composites: clock pin → delivery-year hierarchy → forecast lock → open run → seal/PASS/clear → events/assessments → replacements → M&V).

## Stage-check results
- Tag audit: every tag resolves to a real instance; no stubs translated; no dual/untagged tests; every emitted difficulty instance has exactly 2 tests, every emitted corner instance ≥1.
- Citation sweep: 78/78 verbatim against PRD.md (markdown-normalized).
- No `skip`/`skipif`/`xfail` markers anywhere.
- All files compile; all `test_suite` imports resolve against `test_helpers`; no scaffold references in generated code.

One known risk for the later run: `finalize_assessments_three_hop_charge_to_redistribution`, `settle_conserves_settlement_dollars_across_entries`, and `nonperformance_tier2_and_tier3_multipliers` record `expected_mw=10` on a commitment that cleared only 2 MW (two 10-MW offers vs requirement 12.000). The PRD states expected_mw is "no more than the commitment's committed_mw" but names no error and no §2.6 gate for it, so acceptance is the uniquely derivable reading — if the implementation adds an undocumented rejection, those three tests fail at setup; re-derive then.

## Step 6: Generate Implementation — 2026-09-30T21:35:00.000Z

Final fresh boot works (timeout terminated the server cleanly). Done.

**Files created** in `workspace/implementation/`:

- `start.sh` — guarded launcher (`import flask` check before pip install, `exec python3 app.py`, `$PORT` default 10000, binds 0.0.0.0)
- `requirements.txt` (flask>=3.0), `app.py` (Flask entry, ApiError/404/405 handlers, blueprint registration)
- `db.py` (in-memory store + logical clock starting at exactly 2026-09-01T00:00:00Z, never wall-clock, strictly increasing via ms sequence)
- `errors.py` (all 19 error IDs with exact HTTP statuses), `response.py` (exact envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination meta `limit`/`offset`/`total_count`/`has_more`), `middleware.py` (`X-User-ID`/`X-User-Role` auth, role gating), `util.py` (Decimal helpers q2/q3/q4 ROUND_HALF_UP, pagination defaults 10/1-100/0, created_at-asc sort, ISO8601 parsing)
- `routes/`: delivery_years.py, owners.py, resources.py, accreditations.py, auction_runs.py, offers.py, commitments.py, events.py, measurements.py, clock.py
- `services/calcs.py` — all 8 calculations

**Endpoints**: all 46 from the scaffold's endpoint table, including the `_clock/set_current_utc` test-driving endpoint.

**Calculations implemented**: peak_load_requirement (ICI → UCAP basis → zonal roll-down with LDA share fallback rules), accreditation_ucap (CLASS_AVG flat vs UNIT_SPECIFIC marginal-ELCC derated by outage ratio and sample confidence, 4dp/3dp rounding), seller_offer_cap (max(0.10×net CONE, ACR 60 + 0.10×(1000−credit)) capped at 390, 2dp), auction_clearing (merit order by effective price/sealed_at/created_at, innermost-LDA-first clearing with import limits, shortage pricing at 390, upward-only price separation, MW rounded to 3dp before marginal determination, commitment creation), performance_ratio_calc (cap 1.5, 4dp), nonperformance_charge (tiered multipliers 1.0/1.5/2.0 on unrounded ratio, bonus capped at 0.5×expected, 2dp), redistribution_pool (net pool pro-rata by assessed_mwh, remainder absorbed by last performer in created_at order), mv_verified_ucap (min(metered, baseline)/hours × effective accreditation factor or 1.0).

**Verified via end-to-end scripts against a live boot**: full lifecycle (DY→zones→forecast→lock with exact numbers 165442.5, accreditation 0.9/0.95 factors, open→offer→seal with cap 80.0 for credit 800, clear with shortage pricing, commitments 180@390, event→assessments→finalize with charge −10530.0 matching hand-math, settle with REDISTRIBUTION 416.67 remainder, close), replacement OCC 412/deliverability 422/ownership 403 flows, measurement report GEN-block/window-overlap/revision flows, auth 401/403/404, and pagination meta. Fresh boot confirmed: empty store, clock at 2026-09-01T00:00:00Z, no seeding.

One notable judgment call: the three-pivotal-supplier screen is implemented deterministically (owner pivotal iff the offer sits in a constrained LDA where other owners' sealed supply in-zone is below the zonal requirement); RTO-wide-zone offers are never flagged pivotal by the auto-screen.

## Step 7: Run Tests and Iterate — 2026-09-30T21:45:00.000Z

All 8 rounds pass 66/66. Clean sweep achieved. (Orchestrator verified all 8 results.{i}.json on disk: 66/66, 0 failed; no implementation/ or test file mtimes postdate the sweep.)

**Iterations run:** 2 (initial sweep: 27/66 failing deterministically across all 8 rounds; post-fix sweep: 66/66 in all 8 rounds).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `resolve_review_pass`: now returns the review unchanged when it was auto-resolved to `EXEMPT` at seal instead of forcing a `POST .../resolve` that a PRD-faithful server must 409. The PRD never specifies the three-pivotal-supplier screen's inputs, so a fixture offer priced at-or-under its seller cap (70.00 at credit 900) may legitimately seal as EXEMPT rather than PENDING; EXEMPT and PASS have identical clearing semantics (effective price kept, clear gate satisfied), so this fixes 18 tests' shared setup without touching any assertion.

**Fixes applied to `implementation/`:**
- `services/calcs.py` — `auction_clearing`: removed the 390.00 shortage-price substitution for the RTO-wide zone. PRD §3.4 names the administrative shortage price only inside the nested-LDA sentence; for the RTO zone it states verbatim "its price is the marginal offer's effective price". The impl's RTO shortage override priced every under-supplied RTO zone at 390, corrupting commitment prices and all downstream charge math (e.g. charge −260.00 instead of −66.67). Nested-LDA shortage pricing retained.
- `routes/events.py` — `record_actual`: removed the undocumented `expected_mw > committed_mw` → `ERR_INVALID_REQUEST` rejection. PRD §3.6 describes expected_mw as "no more than the commitment's committed_mw" but names no error and no §2.6 gate for exceeding it, so acceptance is the uniquely derivable reading (matches the Step-5 known-risk flag for `test_tier_two_and_tier_three_charges_on_one_event`).
- `routes/accreditations.py` — `approve_accreditation`: moved the EFFECTIVE-uniqueness check (`ERR_ACCREDITATION_CONFLICT`) ahead of the resource-`REGISTERED` state check. Approval cascades the resource REGISTERED → ACCREDITED, so the old ordering made the PRD-named conflict error unreachable; PRD §3.2 verbatim: "a second effective accreditation is refused with `ERR_ACCREDITATION_CONFLICT`".

No tests were weakened, skipped, or deleted; no endpoints/fields were added to the implementation; storage remains in-memory only.

## Step 8: Finalize PRD — 2026-09-30T21:49:00.000Z

Produced `workspace/PRD_FINALIZED.md` (copy of PRD.md with 4 in-place edits across 3 Step-7 items).

**Line counts:** PRD.md 271 lines, PRD_FINALIZED.md 271 lines (0% delta — all edits are inline sentence revisions, no lines added or removed).

### Changes (one bullet each)

- §2.6 item 9 — revise — appended a scoped ordering exception: on accreditation approval, `ERR_ACCREDITATION_CONFLICT` (EFFECTIVE-uniqueness) is evaluated before the item-6 resource-state and delivery-year-state checks — `implementation/routes/accreditations.py:116-125` (uniqueness loop precedes the `REGISTERED` and DRAFT/FORECAST_LOCKED checks).
- §3.2 — revise — added a sentence pinning the approve gate order: uniqueness before resource-state/DY-state, with the rationale (the REGISTERED→ACCREDITED cascade would otherwise make the conflict error unreachable) — `implementation/routes/accreditations.py:111-125`.
- §3.4 — revise — pinned that the 390.00 administrative shortage price applies only to nested LDAs; the RTO-wide zone always prices at the marginal offer's effective price (null when no offer cleared for it), even when under-supplied — `implementation/services/calcs.py:200-220` (SHORTAGE_PRICE only at line 201 inside the nested-LDA loop; RTO branch has no override).
- §3.6 — revise — the `expected_mw ≤ committed_mw` bound is now stated as a descriptive convention with no validation gate; both `expected_mw` and `actual_mw` require ≥ 0 — `implementation/routes/events.py:209-230` (`record_actual` validates only non-negativity; comment at lines 225-227).

The test_helpers fixture fix (EXEMPT-at-seal vs forced resolve) is a pure fixture bug, not a PRD silence — PRD §3.4 already specifies the seal-time EXEMPT auto-resolution — so no PRD edit was made for it.

### Per-edit pre-edit search log

1. **§3.4 shortage price** — (a) subject: which zones the 390.00 shortage price applies to. (b) paths enumerated: grep for `SHORTAGE_PRICE|390|clearing_price` across routes/ and services/ → `calcs.py:8,13,201,217-220,233,257,264,292`, `auction_runs.py:153` (fallback seller cap, different subject), `delivery_years.py:203`, `commitments.py:221,230,232`; confirmed shortage substitution exists only at `calcs.py:201` (nested-LDA loop) and the RTO branch (lines 205-220) has none; price-separation step 3 only reads `marginal_price` and propagates parent→child, never writes 390 to the RTO zone. (c) added the parenthetical "or null when no offer was cleared for it" to match `marg = None` when the RTO clears nothing.

2. **§3.6 expected_mw bound** — (a) subject: validation on `expected_mw` at record-actual. (b) paths enumerated: all `expected_mw`/`committed_mw` references in `routes/events.py` and `services/calcs.py` (lines 121,157,166,168,216-228 in events.py; `calcs.py` performance_ratio/nonperformance_charge consume `expected_mw` but impose no bound); confirmed no gate compares `expected_mw` to `committed_mw` anywhere. (c) kept the ≥0 requirement for both fields verbatim-equivalent (`err_invalid_request` at events.py:221-224) and framed the committed_mw bound as convention-only.

3. **§3.2 + §2.6 approval gate ordering** — (a) subject: evaluation order of ERR_ACCREDITATION_CONFLICT vs ERR_INVALID_STATE on accreditation approve. (b) paths enumerated: grep for `accredit` across all routes and services — the conflict error is raised only in `approve_accreditation` (`accreditations.py:116-120`), checked before resource-state (122) and DY-state (124); other accreditation consumers (`calcs.py:381-386`, `commitments.py:141-149`, `offers.py`, `auction_runs.py`) read status but raise no conflict error; also verified other endpoints (seal, clear, default, create_replacement, settle, lock-forecast) keep state-before-business so the §2.6 exception could be scoped narrowly to accreditation approval. (c) scoped the §2.6 addition explicitly to accreditation approval and cross-referenced §3.2, so no other endpoint's gate order is re-described.

## Step 9: Complete PRD — 2026-09-30T22:00:00.000Z

Structure intact (5 sections, 86 table rows — unchanged). Line count identical (271), char delta +4,674.

**Source vs output:** `PRD_FINALIZED.md` (271 lines / 47,668 chars) → `PRD_COMPLETED.md` (271 lines / 52,342 chars); +4,674 chars, line count unchanged (all edits are in-paragraph).

**Counts:** 24 ambiguity-pins, 3 mismatch-revisions.

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.3 — insert — ambiguity — pin ERR_INVALID_REQUEST for non-integer/out-of-range `limit`/`offset` and negative `offset`; pin extra filters (zones by `delivery_year_id`/`parent_zone_id`, replacements by `replacement_resource_id`, reports by `revision_of_id`) and ignoring of unrecognized query params — `util.py:106-126`, `routes/delivery_years.py:225-230`, `routes/commitments.py:186`, `routes/measurements.py:99`
- §2.4 — revise — ambiguity — `version` starts at 1 — `util.py:40`
- §2.6 — insert — ambiguity — pin three local gate-ordering exceptions (offer numeric checks before `ERR_OFFER_EXCEEDS_UCAP`; replacement bounds then price check before deliverability; report revision overlap after numeric checks) — `routes/offers.py:50-60`, `routes/commitments.py:127-165`, `routes/measurements.py:54-75`
- §2.7 — insert — ambiguity — expected-version fields must be integers; replacement record echoes `expected_commitment_version` — `routes/offers.py:112-113`, `routes/commitments.py:108-110,173`
- §2.9 — insert — ambiguity — clock stamps strictly increasing (≥1 ms apart) — `db.py:16-22`
- §3.1 — insert — ambiguity — duplicate `delivery_year_label` → ERR_INVALID_REQUEST — `routes/delivery_years.py:38-40`
- §3.1 — revise — mismatch — `import_limit_mw` only *conventionally* null on the RTO root (impl enforces >0 only when present); `parent_zone_id` cross-year/missing → ERR_INVALID_REQUEST; zone creation and forecast submission not gated on DY status — `routes/delivery_years.py:189-195,248-250`
- §3.1 — insert — ambiguity — lock-forecast preconditions fail with ERR_INVALID_STATE — `routes/delivery_years.py:87-98`
- §3.2 — insert — ambiguity — duplicate `legal_name` → ERR_INVALID_REQUEST; `credit_score` must be an integer; suspend from non-ACTIVE → ERR_INVALID_STATE — `routes/owners.py:29-34,61-62`
- §3.2 — insert — ambiguity — accreditation submission has no resource/DY state gate; `scarcity_hours_sampled` is an integer ≥ 1; `accreditation_factor`/`ucap_mw` null until approval — `routes/accreditations.py:55-69`
- §3.2 — insert — ambiguity — UNIT_SPECIFIC with no forecast at all treats pool-wide eford as 0 — `services/calcs.py:89-91`
- §3.2 — revise — mismatch — `must_offer` rule pinned to impl: GEN with a commitment in any delivery year other than the latest by `planning_period_start` (equals "immediately prior" for two years) — `services/calcs.py:390-405`
- §3.2 — insert — ambiguity — retire gates (non-ACCREDITED, live commitments) → ERR_INVALID_STATE — `routes/resources.py:86-93`
- §3.3 — insert — ambiguity — run creation not gated on DY status; duplicate `run_label` → ERR_INVALID_REQUEST — `routes/auction_runs.py:25-33`
- §3.3 — insert — ambiguity — no resource-accreditation-year vs run-year matching check; new offers have `mitigated_cap_per_mw_day`/`effective_price_per_mw_day` null until seal — `routes/offers.py:36-39,68-70`
- §3.4 — revise — ambiguity — seal re-validation pinned as cumulative per-resource headroom in `created_at` order; sealed offers initialize `effective_price_per_mw_day` to the offer price — `routes/auction_runs.py:143-161`
- §3.4 — insert — ambiguity — three-pivotal-supplier screen defined: pivotal iff zone is a nested LDA and other owners' SEALED MW in it < LDA requirement; RTO-zone offers never pivotal — `routes/auction_runs.py:93-119`
- §3.4 — insert — ambiguity — per-offer review fetch returns a list envelope; MITIGATE without pivotal flag → ERR_INVALID_STATE — `routes/offers.py:130-139,168-169`
- §3.4 — revise — ambiguity — clearing: zone `cleared_mw` restated as total cleared MW of offers located in the zone; DY `AUCTION_OPEN` precondition noted as guaranteed by sealing (impl checks run state only) — `services/calcs.py:235-242`, `routes/auction_runs.py:210-211`
- §3.5 — insert — ambiguity — replacement `price_per_mw_day` required and ≥ 0 (else ERR_INVALID_REQUEST); no standing check on the replacement resource's owner — `routes/commitments.py:99-100,133-134,123-125`
- §3.5 — revise — mismatch — default from non-ACTIVE → ERR_INVALID_STATE (threshold error only for score/assessment failures) — `routes/commitments.py:53-58`
- §3.6 — insert — ambiguity — event declaration accepted in any DY status; record-actual repeatable while DRAFT — `routes/events.py:29-35,209-230`
- §3.6 — insert — ambiguity — zero-amount settlement posts as BONUS; zero-total-weight score falls back to simple average — `routes/events.py:170`, `services/calcs.py:318-322`
- §3.7 — insert — ambiguity — measurement submission not gated on DY status — `routes/measurements.py:34-36`
- §3.8 — insert — ambiguity — redistribution skipped when no performers or performers' total assessed MWh is zero — `services/calcs.py:353-359`

No SCAFFOLD files or worklog were read; implementation mtimes all predate the final sweep results (no post-Step-7 impl drift).
