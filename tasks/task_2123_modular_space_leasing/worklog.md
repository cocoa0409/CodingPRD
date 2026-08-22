# Worklog — task_2123_modular_space_leasing

## Step 1: Create task directory — 2026-08-17T18:04:42.718Z

Created `tasks/task_2123_modular_space_leasing/` and `tasks/task_2123_modular_space_leasing/workspace/`. Index 2123 selected (highest existing was 2122).

## Step 3: Copy shared files — 2026-08-17T18:05:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2123_modular_space_leasing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-08-17T19:10:39.000Z

All three artifacts are generated and pass the linter. Final verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2123_modular_space_leasing/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2123_modular_space_leasing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2123_modular_space_leasing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     49
  Calls scanned (§1.8+§1.9):  928

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files written (all absolute)
- `/home/ubuntu/github/CodingPRD/tasks/task_2123_modular_space_leasing/SCAFFOLD.yaml` — §1.0–§1.7 + `concurrency_rules`; neither design key present
- `/home/ubuntu/github/CodingPRD/tasks/task_2123_modular_space_leasing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 9 rules x 2 = 18 instances
- `/home/ubuntu/github/CodingPRD/tasks/task_2123_modular_space_leasing/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 56 instances (49 full recipes + 7 `excluded_because` stubs) across all nine claim-guide sections

## Design summary
**Profile**: temporal_windowing x pricing_engine; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. Deliberately picked the under-represented axes the skill flags: `entity_topology: flat` (all collections root-mounted, `api_prefix: "/"`), `state_machine_shape: cyclic`, `self_referential` relationship (`Lease.extends_lease_id`), `role_model: segregation_of_duties`.

**Scale** (Expert band, pushed above it per the "harder than expert" brief): 13 entities, 7 state machines, 14 calculations, 26 ordered validations, 49 endpoints, 43 errors, 5 roles, 2 OCC rules.

**How each §0.5 rule lands**
1. dual-variant on two domains: `lease_charge_total` (quoted 3668170 vs settled 3864975) and `damage_chargeback` (provisional 377150 vs net 358250).
2. combinatorial in two different modes: mode (b) `lease_monthly_rate` pins round-per-line-then-sum -> **127065, not 127064**; mode (c) `lease_mobilization_fee` pins the discount tier to the pre-fee subtotal -> **351500, not 336700**.
3. non-linear on two entities: `Unit.status` is a closed refurbishment cycle; `Lease` carries independent `occupancy_status` x `billing_status` axes.
4. two cascades from different triggers: teardown-complete -> lease VACATED -> unit RETURNED at the *destination* branch -> branch counters (depth 3); assessment-finalize -> lease SETTLED -> customer balance -> credit_hold -> WATCH demotion (depth 4).
5. three priority pairs: state>fiscal, safety>temporal (§1.8), temporal>fiscal (§1.9).
6. two boundaries on different metrics/endpoints: ADA ramp run `>=` at exactly 36.0 ft (`POST /accessory-packages`); empty line-item set finalizing to 0 (`POST /damage-assessments/{id}/finalize`).
7. two entity pairs: LogisticsJob<->PermitApplication (dispatch gate), RefurbishmentOrder<->DamageAssessment (quote gate).
8. two different interval semantics: pairwise closed intervals inflated by a 14-day refurb buffer on `Unit` (with an extension-handoff exemption), vs aggregate per-calendar-day capacity on `Branch`.
9. two conserved quantities of different type: yard unit count (dispatch<->cancel) and customer money ledger (activate<->void).

**Notable design decisions worth knowing downstream**
- A logical clock (`POST /_clock/set_current_utc`) is declared with the mandated `2026-08-01T00:00:00Z` boot default; every date rule reads it.
- Unit availability for a *new* lease is decided by the occupancy calendar, not instantaneous status — only `REFURBISHING` blocks outright. This was a deliberate reshape: with a "must be IN_FLEET" precondition the priority-20 overlap rule was unreachable, so the temporal-overlap difficulty rule could never be tested.
- `POST /refurbishment-orders` and `POST /damage-assessments` deliberately do NOT move their parent's status — that is what makes them genuine CREATE-with-supersede races resolvable by OCC on `Unit.version` / `Lease.version` (§1.2.1's serial-observability filter).
- Every formula-derived assertion literal was computed by executing the scaffold's own formulas in Python, not estimated.

Audits beyond the linter (all clean): zero forbidden concurrency vocabulary, 74/74 unique instance names, zero unbound `${var}` in payloads/paths/`as_user_id`/asserts, all 43 error codes triggered by at least one recipe, all 7 stub `difficulty_instance` references resolve, all endpoint roles present in §1.7, both OCC endpoints declare their `expected_*_version` input and the matching version bump.

## Step 4: Generate PRD — 2026-08-17T19:26:15.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2123_modular_space_leasing/workspace/PRD.md` (418 lines, ~85 KB). `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Structure

`§1` Introduction (3 paragraphs) -> `§2` Global Specs (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Common Properties & Mutation Bookkeeping, 2.5 Money/Rounding, 2.6 Logical Clock, 2.7 Reference Resolution, 2.8 Stale-Version Protection, 2.9 The Screening Ladder, 2.10 Yard Custody & Fleet Counters, 2.11 Customer Exposure) -> `§3` nine domain workflow subsections -> `§4` endpoint table (4 columns) -> `§5` error table (2 columns). File ends at the §5 table — no audit footer.

## Coverage counts (verified mechanically against the scaffold)

| Scaffold table | In scaffold | In PRD |
|---|---|---|
| entities | 13 | 13 (all narrated; `DamageLineItem` explicitly flagged as id + created_at only) |
| entity field names | 111 | 111 as exact standalone backticked tokens |
| endpoint request-body identifiers | 77 | 77 |
| endpoint query-param identifiers | 20 | 20 |
| unique required names | 119 | 119, 0 missing |
| state machines / transitions | 7 / 38 | 7 / 38, every one with an explicit `FROM -> TO` pair in prose |
| state values / enum values | 25 / 59 | 25 / 59 |
| calculations | 14 | 14 (incl. both `damage_chargeback` and both `lease_charge_total` variants), all constants embedded |
| validations | 26 | 26, rendered as an explicitly ordered ladder in §2.9 with each `applies_to` set enumerated |
| concurrency_rules | 2 | 2 |
| endpoints | 49 | 49 rows, all method+path pairs matched; 28 with side effects narrated in §3 |
| errors | 43 | 43 rows, and all 43 also mentioned in §2/§3 narrative (none table-only) |
| roles | 5 | 5, each `identity:` translated into §2.1 prose |

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 111 required, 111 present, 0 missing
- endpoints[].request_body: 77 required, 77 present, 0 missing
- endpoints[].query_params: 20 required, 20 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 26 checked, 26 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 38 checked, 38 fully expressed, 0 missing
- calculations[]: 14 checked, 14 fully expressed, 0 missing
- validations[] conditions: 26 checked, 26 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 28 checked, 28 expressed, 0 missing
- entities[].fields[] structured content: 111 checked, 111 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (permit approve/reject, refurb approve/reject/complete, job dispatch x3, job complete x3, lease void from UNBILLED vs ACCRUING, unit RETURNED fork), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 634
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 was appended by `cat` from `section-2.2-response-structure.md` and diffed byte-for-byte against the source — identical, including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, and `"data": { }`.

## Notes worth flagging to the pipeline

- **Two genuine ambiguities in the scaffold** were resolved toward the more specific text: (1) `ERR_INVALID_STATE`'s condition names "completing a SCHEDULED job" while `ERR_JOB_NOT_DISPATCHABLE` claims "dispatch/complete/cancel" — the PRD assigns dispatch and cancel to `ERR_JOB_NOT_DISPATCHABLE` and completion-from-wrong-state to `ERR_INVALID_STATE`; (2) the `unit_infleet_to_reserved` precondition requires the custody branch to be `OPERATIONAL`, but no validation row maps a branch-suspension error to lease creation — the PRD therefore makes branch status a condition on the `IN_FLEET -> RESERVED` status move only (the lease row is still created), which is consistent with the scaffold's forward-booking note and invents no error.
- Money constants are expressed in dollars (e.g. `$1,750.00` for `175000`), with §2.5 pinning the conversion explicitly so the reconstruction test holds; `CONFIG_AMORT_MONTHS`, `REFURB_BUFFER_DAYS`, and the mileage bands use comparable natural-language conversions.
- The extension successor's `pinned_credit_tier` and `quoted_total_cents` are stated explicitly (the scaffold left both implicit in the endpoint side-effect list).

**Orchestrator verification (anti-truncation check):** PRD.md confirmed to contain all five top-level sections (§1 L3, §2 L11, §3 L182, §4 L314, §5 L371), 43 `ERR_` table rows, and a clean terminal row — no truncation.

## Step 6: Generate implementation — 2026-08-17T19:53:00.000Z

(Completed before Step 5; worklog is append-ordered by completion time.)

The implementation is complete and verified. Here's the summary.

## What was built

A Python + Flask REST API at `/home/ubuntu/github/CodingPRD/tasks/task_2123_modular_space_leasing/workspace/implementation/`:

```
start.sh (executable, guarded pip install + exec python3 app.py)
requirements.txt - app.py - db.py - errors.py - response.py - guard.py
calc.py - serializers.py - services.py
routes/{catalog,customers,leases,accessories,permits,logistics,assessments,refurb,clock}.py
```

**Coverage** — all 49 endpoints registered (verified by enumerating the Flask URL map), 13 entities, 7 state machines, 14 calculations, all 26 ordered validations, 43 error IDs with their exact HTTP statuses, 5 roles, and both OCC rules (`expected_unit_version` / `expected_lease_version` -> 412).

**Storage** is in-memory dicts only; every collection starts empty on boot — no seeding, no disk I/O. A global RLock serializes requests so OCC races resolve deterministically.

## Key fidelity decisions (PRD prose taken as authoritative over scaffold ordering)

- **Screening ladder §2.9 governs error precedence**, not the §3 prose order. Notably body-FK 404s (rank 4) precede body-shape 422s (rank 5); ADA compliance (rank 9) precedes branch-suspended (rank 15) on job booking even though §3.8 narrates them the other way; anchoring mismatch (rank 11) precedes entity-link mismatch (rank 13) on permit creation.
- **§2.4 bookkeeping applied literally**: recomputing a branch's counters or a customer's exposure is a write, so those resources get `updated_at` + `version` bumps even when the recomputed values are numerically unchanged.
- **Teardown completion recomputes the destination branch only** (per the normative §3.8/§2.10 chain), not the unit's former custody branch.
- **Logical clock** starts at `2026-08-01T00:00:00Z` and never falls back to wall time; only `submitted_on`, `decided_on`, `actual_vacated_date`, lead-time and contiguity arithmetic read it. `created_at`/`updated_at` use real time with a monotonic millisecond counter so creation-order sorting is always strict.
- All money via `Decimal` + `ROUND_HALF_UP`, with per-line rounding before addition wherever the PRD pins that order (rate lines, transport lines, refurb lines).
- `assessment_round` increments on **every** assessment create, not only when one is superseded.
- Pagination out-of-range (`limit<1`, `limit>100`, `offset<0`, non-integer) -> `ERR_INVALID_REQUEST` 422; `credit_tier` treated as required (endpoint input list marks no `?`, unlike `status?`/`condition_grade?`).
- Clock endpoint echoes the supplied instant verbatim as `current_utc`.

## Verification

Five ad-hoc HTTP test batches (~180 assertions) run against fresh boots, all passing: full lifecycle (quote -> accessory -> permit -> activate -> deliver -> relocate -> teardown -> assess -> dispute -> finalize -> settle -> refurb), the complete error ladder and RBAC/ownership matrix, occupancy-calendar buffer boundaries (14 vs 15 day gaps, extension exemption), dispatch/yard capacity, credit hold + WATCH demotion, and calculation boundaries (term/wind/tier factors, volume-discount tier floors at exactly $3,000/$8,000, 150-mile marginal band, ceil/floor segment counts, ADA inclusive comparisons, wear cap and 40% damage clip, early-termination vs holdover). The one reported "FAIL" was an arithmetic error in my own test expectation (a $2,400 subtotal is below the $3,000 tier floor, so no discount applies) — server behavior was correct.

## Step 5: Generate unit tests — 2026-08-17T20:02:30.000Z

Generation complete. Final report:

## What was produced

**`/home/ubuntu/github/CodingPRD/tasks/task_2123_modular_space_leasing/test_helpers/`** (Stage 1, 9 files, ~2,140 lines)
- `types.py` — 14 status enums + TypedDicts for all 13 entities. `DamageLineItem` correctly omits `updated_at`/`version` (`common_fields: false`).
- `api_client.py` — 46 endpoint methods, one per PRD §4 row.
- `api_errors.py` — 43 error IDs + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions plus invariant checkers (`assert_branch_counters`, `assert_credit_hold_consistent`, `assert_yard_count_matches_units`, `assert_exposure_matches_leases`).
- `factories.py`, `constants.py`, `test_users.py` (per-instance `make_branch_ops_headers(branch_id)` / `make_customer_headers(customer_id)` for the two `entity_backed` roles), and `fixtures.py` (686 lines, 5 tiers: single-call wrappers -> catalogs -> leases -> installed/vacated lifecycles -> assessment/refurbishment chains, all `**overrides`-driven).

**`/home/ubuntu/github/CodingPRD/tasks/task_2123_modular_space_leasing/test_suite/`** — `conftest.py` + 8 domain-named files, **87 tests**.

## Coverage audit (clean)

- **Queue A**: all 18 `scaffold_difficulty_design` instances x exactly 2 tests = **36 tests**.
- **Queue B**: all 49 non-stub `scaffold_corner_design` instances covered = **51 tests**. All 7 `excluded_because:` stubs verified to resolve to real difficulty instances; none translated.
- **0 instances skipped** — every one passed the PRD-first two-condition filter.
- Machine-checked: every docstring ends with exactly one `Design:` line resolving to a real instance; every `PRD §x: "..."` citation survives a whitespace-normalized literal match against `PRD.md` (**0 non-verbatim**); no `skip`/`skipif`/`xfail`; no "scaffold"/§1.x references in generated code; pyflakes clean; `pytest --collect-only` collects 87.

## Two judgement calls you should know about

1. **PRD/design-index conflict.** Corner instance `state_machines/complete_a_scheduled_job_returns_job_not_dispatchable` asserts `ERR_JOB_NOT_DISPATCHABLE`, but PRD §3.8 states the opposite explicitly: *"a job addressed for completion while it is still `SCHEDULED` — or from any state other than `DISPATCHED` — is refused with `ERR_INVALID_STATE`."* PRD-first, so `test_completing_a_scheduled_job_is_refused` asserts `ERR_INVALID_STATE`. This is a **scaffold bug**, not a test bug — worth fixing in `SCAFFOLD_CORNER_DESIGN.yaml` (line ~996).
2. **`version` initial value is a PRD gap.** The PRD says `version` "increments by one on every mutation" but never states it starts at 1. Several corner instances assert `version == 1` / `== 2`; those absolute assertions were dropped as not uniquely-derivable. Version is instead asserted *relatively* (advances after publish; unchanged after a refused write), which is PRD-derivable. The rest of each instance's claims are asserted in full.

Also noted: `list_units_with_limit_above_the_maximum_is_rejected` was kept (422 `ERR_INVALID_REQUEST` for `limit=500`) on the strength of §2.3's "may not be larger than 100" + §2.9 rank 5's out-of-range clause, though §2.9 scopes rank 5 to "endpoints that accept a body" — mildly under-specified for a query parameter.

**Orchestrator note:** the Step 5 PRD/design-index conflict (item 1) is consistent with the Step 6 implementation, which independently read PRD §3.8 and routed completion-from-wrong-state to `ERR_INVALID_STATE`. Tests and implementation therefore agree on the PRD-faithful reading.

## Step 7: Run tests and iterate — 2026-08-17T20:15:00.000Z

All 87 tests pass in all 8 concurrent rounds.

## Summary

**Iterations run:** 2 (baseline sweep + one fix round). Both sweeps were fully deterministic — the same 2 tests failed in all 8 rounds of iteration 1, and 0 failed in all 8 rounds of iteration 2 (87/87 x 8).

**Tests deleted:** none. Both failures survived STEP 1 (PRD verbatim-covers the asserted rule) and STEP 1b (unique derivability held), so neither qualified for deletion.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2123_modular_space_leasing/test_suite/test_03_accessories_and_permits.py` — `test_permit_jurisdiction_must_match_the_lease_jurisdiction`: the request sent `foundation_type: "PIER_FOUNDATION"` to the TX-RUR authority, whose `anchoring_standard` is `GROUND_ANCHOR`. PRD §2.9 puts the anchoring agreement at ladder rank 11 and the cross-entity link agreement at rank 13, so a PRD-faithful server must answer `ERR_ANCHORING_STANDARD_MISMATCH` — the test's own payload pre-empted the rule it meant to probe. Changed the foundation to `GROUND_ANCHOR` (the addressed authority's mandated class) so rank 11 passes and the link disagreement is the deciding check. The assertion itself was untouched; no error_id was weakened.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2123_modular_space_leasing/workspace/implementation/routes/logistics.py`, `complete_job` (TEARDOWN_RETURN branch) — teardown completion rewrote `unit.current_branch_id` to the destination yard but recomputed counters only on the destination. PRD §2.10 requires the three derived counters be "recomputed from scratch ... after every write that changes a unit's status **or its custody branch**", and defines `utilization_pct` over "the total number of units whose `current_branch_id` is this branch", with 0.00 when a branch has no units assigned. The yard the unit departed kept publishing a stale 100.00 with zero units on its books. Now the previous custody branch is recomputed as well, guarded so that origin == destination (the common single-yard case) is not touched twice.

**Notes on the two known scaffold discrepancies flagged upstream:** neither surfaced as a failure. The implementation already returns `ERR_INVALID_STATE` for completing a non-`DISPATCHED` job per PRD §3.8 (not the corner index's `ERR_JOB_NOT_DISPATCHABLE`), and the suite asserts `version` only relatively — no absolute `version == 1` assertions remain.

**Orchestrator verification:** all 8 `results.{i}.json` files independently confirmed at `passed == total == 87`.

## Step 8: Finalize PRD — 2026-08-17T20:22:00.000Z

`PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_2123_modular_space_leasing/workspace/PRD_FINALIZED.md`.

## Size delta

- PRD.md: 418 lines / 84,953 chars — PRD_FINALIZED.md: 418 lines / 86,072 chars.
- Line count delta: 0 (0.00%) — the PRD is one paragraph per line, so both edits landed inside existing lines. Character delta: +1,119 (+1.32%).

## Changes

- **§3.6 (Permits, Foundations and Lead Time)** — *insert* — pins that the rank-11 anchoring comparison reads the `anchoring_standard` of the authority the **application** names in its own `jurisdiction_id` (not the lease's), and that anchoring is screened ahead of the link agreement, so a wrong-authority application whose foundation the named authority does not mandate answers `ERR_ANCHORING_STANDARD_MISMATCH` — `implementation/routes/permits.py:24,32,37`.
- **§3.8 (Logistics: ... Return)** — *insert* — pins that teardown completion recomputes the counters of the unit's **former** custody branch in addition to the destination branch, identifies that branch as the unit's former `current_branch_id` (not the job's `origin_branch_id`), and pins the single-yard guard where former == destination is not restated twice — `implementation/routes/logistics.py:210,219-221`.

Not patched (deliberately): the `test_suite` payload change itself was a fixture bug on the ordering rule that §2.9 ranks 11/13 already state verbatim — only the *which-jurisdiction* half was under-determined, so only that half was pinned. The two "notes" in the diff (`ERR_INVALID_STATE` on completing a non-`DISPATCHED` job; absolute `version` assertions) produced no fix and no PRD divergence — §3.8 already states the `ERR_INVALID_STATE` rule verbatim, so nothing was touched there.

## Per-edit pre-edit search log

**Edit A — §3.6 anchoring agreement**
- (a) Subject: which jurisdiction's `anchoring_standard` a permit application's `foundation_type` is compared against, and where that comparison sits relative to the lease-link comparison.
- (b) Paths enumerated: `grep -rn "anchoring_standard\|foundation_type\|jurisdiction_id" --include=*.py` over `implementation/`. Read `routes/permits.py` in full — create (`resolve_fk` order `lease_id` -> `jurisdiction_id` at :23-24; anchoring at :32 against the **body-named** jurisdiction; link at :37; fee at :43 from the body-named jurisdiction + the lease's unit's spec), submit (:91 reads `record["jurisdiction_id"]` for `permit_lead_days`), decide (no jurisdiction read). Also checked the only *other* `anchoring_standard` consumer, `routes/leases.py:110` -> `calc.lease_mobilization_fee` (:177-178, `ANCHOR_COST_CENTS`), which reads the **lease's** jurisdiction, and `routes/catalog.py:64` (jurisdiction registration enum).
- (c) Adjustment: scoped the new sentence explicitly to "that second comparison" on a permit application, so it makes no claim about the mobilization anchoring allowance (which legitimately reads the lease's jurisdiction) and none about the fee/lead-time reads. Kept "not the lease's" as a contrast rather than a general statement about how jurisdictions are sourced elsewhere.

**Edit B — §3.8 teardown-completion counter recomputation**
- (a) Subject: which branch(es) have `units_in_yard` / `units_available` / `utilization_pct` recomputed when a unit's custody branch changes.
- (b) Paths enumerated: `grep -rn "recompute_branch\|recompute_customer\|current_branch_id"` over `implementation/`. Read `services.recompute_branch` / `recompute_branch_of_unit` (`services.py:54-66`, unconditional `touch` -> version bump even when the numbers do not move) and `calc.branch_counters` (`calc.py:299-310`, zero-assigned -> 0.00). Every recompute callsite read: `routes/catalog.py:225` (unit creation, receiving branch only), `routes/leases.py:119` (quote/reserve, custody branch), `routes/leases.py:217` (void release, guarded by "no other PENDING lease"), `routes/logistics.py:158` (dispatch `DELIVERY_INSTALL`), `:219`/`:221` (the edit site), `:256` (aborting a dispatched delivery), `routes/refurb.py:136`/`163`/`195` (approve / reject / complete — all recompute the *custody* branch via `recompute_branch_of_unit`, not the order's `branch_id`). Confirmed the paths that deliberately recompute **nothing**: teardown dispatch (`logistics.py:159-162`), delivery-install completion (`:199-205`), and the relocation self-loop (`:222-227`) — none call a recompute, matching §2.10's eight-write list and §3.8's existing "no branch counter moves" clauses. Confirmed `current_branch_id` is written in exactly two places: unit creation (`catalog.py:215`) and teardown completion (`logistics.py:213`).
- (c) Adjustment: the wording was deliberately confined to the teardown-completion cascade rather than stated as a general rule, so it cannot be read to add a recompute to delivery-install completion, teardown dispatch or relocation, where the implementation performs none (a general phrasing would have implied extra branch `version` bumps on those paths). Added "which is the unit's own former `current_branch_id`, not necessarily the job's `origin_branch_id`" after confirming the implementation restates the custody branch and not the crew branch — those differ whenever a branch books a job on a unit parked at another yard. Phrased the same-branch case as "not restated a second time" rather than "not restated", since the destination recompute still happens in that case.

## Step 9: Complete PRD — 2026-08-17T20:34:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_2123_modular_space_leasing/workspace/PRD_COMPLETED.md` is written.

## Scope of walk
All 18 impl source files read in full (`app.py`, `db.py`, `errors.py`, `response.py`, `guard.py`, `services.py`, `calc.py`, `serializers.py`, `routes/*.py` — 2691 lines). Verified against PRD: 49 endpoints, 43 error IDs, 5 role lists, the 26-rank ladder ordering inside every handler, all 14 calculation formulas (`calc.py` constants match PRD figures exactly), 7 state machines, both optimistic-concurrency rules, and all 13 serializers. All 20 `ERR_INVALID_STATE` raise sites in impl are now individually pinned.

## Counts
- PRD_FINALIZED.md: 418 lines / 86,072 chars -> PRD_COMPLETED.md: 418 lines / 91,213 chars (**+5,141 chars, +0 lines**) — every change is an in-paragraph insert or revision; no new sections, paragraphs, or table rows (28 headings, 49 endpoint rows, 43 error rows unchanged).
- **36 changes: 34 ambiguity-pins, 2 mismatch-revisions.**

## Changes
- §2.1 — revise — ambiguity — a context header present but empty counts as absent for `ERR_UNAUTHENTICATED` — guard.py:16
- §2.2 — insert — ambiguity — undefined route / unsupported method answer in the error envelope as `ERR_INVALID_REQUEST` at 404 / 405 — app.py:42-45
- §2.3 — insert — ambiguity — out-of-range or non-integer `limit`/`offset` is `ERR_INVALID_REQUEST` 422, not clamped — response.py:66-84
- §2.3 — insert — ambiguity — `has_more` = offset + returned < `total_count`; filters are exact string matches, empty filter value ignored — response.py:51, services.py:116-126
- §2.4 — revise — ambiguity — `version` stands at 1 when first persisted — db.py:73
- §2.5 — insert — ambiguity — which body fields must be JSON integers vs. accept fractional values — guard.py:84-115
- §2.6 — revise — ambiguity — `data` carries only `current_utc`, echoed verbatim when the input contains `T`, else `yyyy-mm-ddThh:mm:ssZ` — clock.py:232-237
- §2.9 rank 5 — revise — ambiguity — a required string may not be blank — guard.py:68-69
- §2.9 rank 5 — insert — ambiguity — absent/unparseable body read as an empty object — guard.py:48-53
- §2.9 rank 14 — revise — **mismatch** — config-published check applies to `POST /leases` **and** `POST /leases/{id}/activate`, not `POST /leases` alone — leases.py:202-204
- §3.1 — insert — ambiguity — `permit_required` and `ada_ramp_required` are required booleans with no default — catalog.py:328,333
- §3.3 — insert — ambiguity — general guarded-status-move rule: a unit not standing in the departing status keeps its status while the write, version bump, custody rewrite and counter recomputes still land — leases.py:155, logistics.py:155,200,211,253
- §3.4 — insert — ambiguity — a unit `IN_FLEET` in a `SUSPENDED` yard keeps `IN_FLEET`; the quote is not refused — leases.py:155
- §3.6 — revise — ambiguity — filing against a lease that left `PENDING` is `ERR_INVALID_STATE` — permits.py:164-165
- §3.6 — insert — ambiguity — deciding a non-`SUBMITTED` application is `ERR_INVALID_STATE`; omitted `reviewer_note` stored as null — permits.py:186,189-190
- §3.7 — revise — ambiguity — activation: occupancy not `PENDING` -> `ERR_INVALID_STATE`; billing `VOIDED`/`SETTLED` -> `ERR_LEASE_ALREADY_ACTIVATED`; config not published -> `ERR_CONFIG_NOT_PUBLISHED` — leases.py:197-204
- §3.7 — insert — ambiguity — void: both source-state failures answer `ERR_INVALID_STATE` — leases.py:232-237
- §3.7 — insert — ambiguity — void: a unit not `RESERVED` is not written at all — leases.py:248
- §3.7 — revise — **mismatch** — finalization requires occupancy `VACATED` only; a non-`ACCRUING` billing axis skips the cascade instead of refusing — assessments.py:205
- §3.7 — insert — ambiguity — successor born with `actual_vacated_date`/`final_settlement_cents` null and the five money/counter fields at zero — leases.py:315-324
- §3.7 — revise — ambiguity — the parent's own occupancy and billing axes are not screened on extension — leases.py:263-300
- §3.8 — revise — ambiguity — `DELIVERY_INSTALL` dispatch moves the unit under the §3.3 guard — logistics.py:155
- §3.8 — revise — ambiguity — `TEARDOWN_RETURN` dispatch: lease not `INSTALLED` -> `ERR_INVALID_STATE` — logistics.py:139-140
- §3.8 — insert — ambiguity — `RELOCATION` dispatch: same `ERR_INVALID_STATE`, and the unit is not written, so its `version` does not move — logistics.py:139-140,163
- §3.8 — insert — ambiguity — completion source state by type: `DELIVERY_INSTALL` needs lease `PENDING`, the other two need `INSTALLED`, else `ERR_INVALID_STATE` — logistics.py:182-187
- §3.9 — revise — ambiguity — appending a line item outside `DRAFT`/`DISPUTED` is `ERR_INVALID_STATE` — assessments.py:109-111
- §3.9 — insert — ambiguity — `dispute_reason` survives a re-submission rather than being cleared — assessments.py:143-145
- §3.9 — insert — ambiguity — disputing a non-`SUBMITTED` assessment is `ERR_INVALID_STATE`, screened at rank 7 ahead of the dispute budget — assessments.py:161-166
- §3.9 — revise — ambiguity — finalizing a lease short of `VACATED` is `ERR_INVALID_STATE` — assessments.py:186-187
- §3.9 — insert — ambiguity — settlement takes the first `APPROVED` permit application in creation order — assessments.py:207-210
- §3.9 — revise — ambiguity — approve: unit not `RETURNED` -> `ERR_INVALID_STATE` — refurb.py:122-123
- §3.9 — revise — ambiguity — approve recomputes the **unit's custody branch**, not the order's `branch_id` — refurb.py:136
- §3.9 — revise — ambiguity — reject: either state failure is `ERR_INVALID_STATE` — refurb.py:151-154
- §3.9 — revise — ambiguity — reject recomputes the unit's custody branch — refurb.py:163
- §3.9 — insert — ambiguity — complete: `actual_cost_cents` is a required non-negative integer; a non-`APPROVED` order -> `ERR_INVALID_STATE` — refurb.py:173,179-180
- §3.9 — revise — ambiguity — completion raises `units_available` on the unit's custody branch — refurb.py:195
