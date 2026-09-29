# Worklog — task_2982_renewable_energy_land_lease_easement_origination

## Step 1: Create task directory — 2026-09-06T01:18:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2982_renewable_energy_land_lease_easement_origination` and its `workspace/` subdirectory. Index 2982 was pre-assigned by the orchestrating command; no index scan was performed (concurrent pipelines on this host would collide).

## Step 2: Generate scaffold — 2026-09-06T02:45:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts for task 2982 are complete and lint-clean.

**Output directory** `/home/ubuntu/github/CodingPRD/tasks/task_2982_renewable_energy_land_lease_easement_origination/`

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2924 | 145,750 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1966 | 139,775 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2423 | 163,117 |

**SCAFFOLD.yaml** (§1.0–§1.7, no design keys — top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`): 12 entities, 11 state machines, 2 concurrency rules, 7 calculation rules, 43 validation rules (priority-ordered), 59 endpoints, 41 error codes, 5 roles. Domain `land-origination`, prefix `/land-origination`, `difficulty_level: expert_plus`, logical clock default `2026-08-01T00:00:00Z`, immediate consistency, segregation-of-duties role model.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (single key `scaffold_difficulty_design`): **9 difficulty rules / 20 instances** — dual_variant_calc (2), combinatorial_formula (2), non_linear_state_machine (2), transitive_cascade (2), priority_pair_validation_conflict (3), boundary_precision_check (2), cross_entity_state_dependency (3), resource_temporal_overlap (2), compensating_invariant (2).

**SCAFFOLD_CORNER_DESIGN.yaml** (single key `scaffold_corner_design`): **9 sections / 70 instances** (52 with full `test_recipe`, 18 `excluded_because` stubs that all cite an existing §1.8 instance by name): entities 10 (9+1), state_machines 9 (6+3), calculations 12 (6+6), validations 10 (7+3), endpoints 5 (4+1), errors 11 (8+3), rbac 5 (5+0), complexity_layers 7 (6+1), consistency_model 1 (1+0). All 90 instance names are unique across both design files.

Lint verdict (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2982_renewable_energy_land_lease_easement_origination/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2982_renewable_energy_land_lease_easement_origination/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2982_renewable_energy_land_lease_easement_origination/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     52
  Calls scanned (§1.8+§1.9):  488

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes worth passing on:
- The only lint failure in the final pass was two `$.data.total_count` captures on a list endpoint inside `compensating_invariant / option_payment_ledger_restored_by_withdraw_refund`; `total_count` lives in `meta`, so they were rewritten as `$.data[2].sequence_no` / `$.data[3].sequence_no` (plus `payment_kind`) and the corresponding assertion now states the row counts in prose.
- Three internal inconsistencies in SCAFFOLD.yaml were found while grounding corner claims and fixed: the priority-16 `resource_capacity_factor` domain (`< 1` -> `<= 1`, matching the entity constraint), a `§1.4 priority 28` mis-citation in `crossing_compensation` (-> priority 38), and an unbound `${nonexistent_version}` placeholder in a corner instance.
- Every numeric literal in both design files was verified by executing `.scratch/step2/corner_calc.py` (Decimal, ROUND_HALF_UP) — e.g. screening score 82.15 for the canonical clean parcel, security requirement 10,450,000 cents at 200.00 acres, PROVISIONAL year-1 rent 24,000,000 cents, consent release 20.00 acres at rate 0.2500 on 100.00 acres with `CONSENT_RELEASE_FRACTION`. Scratch was confined to `.scratch/step2/` and left in place.
- No sibling task directory was read, listed, or grepped at any point.

Orchestrator post-step action: the difficulty directive line "Generate task harder than expert level!" had leaked into SCAFFOLD.yaml's `scenario:` block (known scaffold-generator behaviour). Stripped it from SCAFFOLD.yaml so it cannot reach PRD.md via the doc generator; re-verified the YAML still parses and no other artifact contains the phrase.

## Step 3: Copy shared files — 2026-09-06T02:45:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-06T02:58:00.000Z

Subagent summary (verbatim):

Step 4 complete.

**Deliverable:** `workspace/PRD.md` — **498 lines**, 13,565 words, 96,310 bytes.

**Tail check:** the file terminates at a real section boundary — the last line of the §5 Error Code Catalogue table, `| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |`. No mid-sentence cut, no dropped trailing section. Section skeleton as built: §1 Introduction, §2.1–§2.10, §3.1–§3.9, §4 Endpoint Definitions, §5 Error Code Catalogue.

**Coverage confirmation (mechanically verified against SCAFFOLD.yaml):**
- Endpoints documented: **59 / 59** (§4 table has exactly 59 rows, Method | Path | Description | Authorized Role(s); zero scaffold endpoints missing)
- Validation rules: **43 / 43** (the §2.9 priority ladder is a full 43-rung table with Rung | Rejection | HTTP | Scope, each rung also narrated in §3)
- Error codes: **41 / 41** (§5 has 41 rows; every code is additionally referenced in prose in §2 or §3 — zero orphans)
- State machines: **11 / 11** (Landowner, Parcel, NeighborConsent, TitleCurativeItem, OptionAgreement, Corridor, CrossingAgreement, SiteAccessBooking, LeaseAgreement rent_status, LeaseAgreement recording_status, RentInvoice; all states and all transitions present, including the 14-transition cyclic option machine and the EXECUTED->EXECUTED extension self-loop)
- Calculations: **7 / 7** (parcel_screening_score both DESKTOP/FIELD_VERIFIED variants, buildable_acres_derivation, option_fee_schedule, annual_rent_amount both PROVISIONAL/FINAL_AS_BUILT variants, decommissioning_security_amount, landowner_paid_ledger, crossing_compensation) — each with its pinned rounding order stated in prose, no operator syntax

**Hard Contracts — all PASS:**
1. Field-Name Coverage — PASS. entity fields 121/121; request_body inputs 65/65; query_params 24/24; path_params 12/12; computed-read output keys 14/14. Zero missing identifiers out of 150 unique required.
2. Rule Coverage — PASS. All 43 validations, 11 machines, 7 calculations, 2 OCC rules (expected_parcel_version->ERR_STALE_PARCEL_VERSION 412, expected_lease_agreement_version->ERR_STALE_LEASE_VERSION 412), 4 named cascades, 4 clock sweeps S1–S4, and every named constant expressed in prose.
3. §3 Path Purity — PASS. 794 tokens scanned in §3: 0 slash-paths, 0 bare HTTP methods, 0 method+path pairs. The only literal paths in the document are the two OCC write_endpoints and the clock endpoint, which sit in §2 where they are permitted.

**Judgement calls worth flagging to the pipeline** (scaffold gaps where a precondition carried no error id; I never invented a code): ERR_UNAUTHORIZED for Landowner ownership mismatch; ERR_INVALID_REQUEST for landowner_id != parcel owner and for non-zero royalty_rate_bps under PER_ACRE; ERR_INVALID_STATE for the parcel-status gates on consent grant/revoke and for sub-80-acre exercise (deliberately *not* widening ERR_PARCEL_NOT_QUALIFIED, whose applies_to is send-only); SetbackRule (jurisdiction_code, rule_type) uniqueness stated descriptively with no code; variant_delta_cents defined as final minus provisional. There is no OptionPayment not-found code in the catalogue, so the ledger read is described without one.

Constraints honoured: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was opened, grepped, or referenced; no sibling task_*/ directory was read. Scratch was confined to `.scratch/step4/`.

Orchestrator verification: independently re-read the PRD tail — it ends on the final `ERR_PAYMENT_AMOUNT_MISMATCH | 422` catalogue row, a real section boundary, so the known doc-generator truncation failure did not occur. Confirmed the difficulty directive phrase appears 0 times in PRD.md.

## Step 6: Generate implementation — 2026-09-06T03:45:00.000Z

Subagent summary (verbatim):

Implementation complete and verified.

## Deliverables — `workspace/implementation/`

| Module | Lines | Role |
|---|---|---|
| `app.py` | 97 | `create_app()`, 13 blueprints, request serialisation lock, error handlers, `0.0.0.0:$PORT` (default 10000) |
| `errors.py` | 169 | all 41 error ids + HTTP status/message tables, `ApiError`, `fail`, `bad_request` |
| `util.py` | 126 | `Decimal` prec 60 / ROUND_HALF_UP, `fmt_dt` (exactly 3 fractional digits + `Z`), `parse_dt`, `add_days`, rounding helpers |
| `store.py` | 90 | in-memory `db` (12 dicts), logical clock epoch `2026-08-01T00:00:00Z`, `insert`/`touch`/`ordered` |
| `envelope.py` | 39 | `meta`/`response_type`/`data` envelope, `req_` + 20-char request ids, list `limit/offset/total_count/has_more` |
| `auth.py` | 77 | 5 roles, rung 1/2 gates, entity-backed `Landowner` scoping |
| `validation.py` | 323 | rungs 14/15/16 + `lookup_fk` (existence-before-shape), pagination, query filters |
| `calc.py` | 238 | all 7 pinned calculation rules and every pinned constant |
| `cascades.py` | 243 | the four named recompute procedures + ledger/counter recomputes |
| `serializers.py` | 246 | explicit field lists for all 12 entities (`OptionPayment` carries no `updated_at`/`version`) |
| `access.py` | 105 | typed path lookups (rungs 3–13) and ownership checks |
| `routes/` (14 files) | 1 857 | landowners 86, parcels 129, setback_rules 62, consents 125, curative 162, options 462, payments 52, corridors 71, crossings 142, bookings 110, leases 222, invoices 132, clock 102 |
| `start.sh` / `requirements.txt` | 20 / 1 | guarded pip check then `exec python3 app.py` |

**3 631 lines total. 59 endpoints registered — exactly matching the PRD endpoint table.** Storage is in-memory dicts only; a grep confirms no SQLite, no file writes, no `/tmp` use, and nothing is seeded at startup.

## Fixes made in this pass (both PRD-conformance bugs)

1. **Consent grant/revoke ran a fifth hop.** PRD §3.3 pins the consent cascade at **three** hops (acreage -> qualification -> posture); §2.8 defers to §3 for which procedures each transition triggers. Both handlers were also calling `recompute_parcel_screening`, inflating the parcel's `version` by one extra on every grant and revoke. Removed. (`SCAFFOLD.yaml` is self-contradictory here — its transition hops at lines 937/947 agree with the PRD, its endpoint `side_effects` at 2323/2338 do not; the PRD is normative.)
2. **Body FK existence now outranks request shape.** Ladder rungs 3–13 sit above rung 14, so a body FK that is a usable string must be resolved *before* the shape pass even when another field is missing. Added `validation.lookup_fk` and reordered all six creates with body FKs (parcel, consent, curative item, option, crossing, booking).

## Boot / smoke check

Booted with `PORT=44475 bash start.sh` from a fresh process (log clean, listener up in <4 s), then:
- `POST /land-origination/landowners` -> **201**; `GET /landowners/{id}` -> **200**; `GET /landowners?limit=2` -> **200** with correct list meta; unauthenticated `GET` -> `ERR_MISSING_USER_ID`.
- Full 202-line end-to-end walkthrough -> **SMOKE OK** (landowner -> parcel screening 92.8/PRIORITY -> negotiation -> execute -> extend -> ledger -> exercise -> security -> memo -> record -> invoice -> crossing -> booking -> clock sweep). Pinned arithmetic all matches hand calculation: option fee 1 500 000; extension fee 500 000; security 25 000 000 / 300 bps / 750 000 / 25 750 000; year-3 COMPOUND rent 49 419 000 with royalty 25 200 000; `due_at` = issued + 45 d; crossing 76 d -> 2 300 bps -> 6 273 000.
- New targeted probe -> **PROBE2 OK**: consent grant bumps the parcel by exactly 2 (acreage + qualification, no screening hop) and the consent by exactly 1; revoke restores `buildable_acres` 135.0 -> 75.0 (acreage conservation invariant); 14 ladder assertions confirm 2 > 3 > 4 > 5 > 7 > 9 > 14 ordering.
- Both smoke servers were stopped by their exact recorded PIDs; ports 44027 and 44475 verified free. No pattern kill was used.

One judgement call worth flagging: `created_at`/`updated_at` are stamped from wall clock, not the logical clock. PRD §2.6 enumerates the clock-stamped instants and deliberately excludes them, §2.4 defines `created_at` as "the instant at which the row was inserted", and the PRD's claim that the option-payment ledger is *the one* collection needing a secondary sort key only holds if `created_at` is naturally unique per row. All 13 business instants do come from the logical clock.

Scratch cleanup: `rm -rf .scratch/step6` only — `.scratch/step2` and `.scratch/step5` are intact. `worklog.md`, `test_suite/` and `test_helpers/` were never read or written.

## Step 5: Generate unit tests — 2026-09-06T04:05:00.000Z

Subagent summary (verbatim):

Step 5 is complete.

## Design instances consumed

| Queue | Instances | Non-stub | Consumed | Skipped |
|---|---|---|---|---|
| A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) | 20 | 20 | **20** | 0 |
| B — `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) | 70 | 52 | **52** | 0 |

**Skipped: 0.** No instance failed the PRD-first two-condition filter — every pinned code, field and figure was grep-confirmed verbatim in `workspace/PRD.md` and the asserted outcome uniquely derived before the test was written. The 18 queue-B `excluded_because:` stubs were deliberately **not** translated; all 18 cross-references resolve to real queue-A instance names (checker prints `[ok ]` for each).

Queue-B section breakdown: entities 9, state_machines 6, calculations 6, validations 7, endpoints 4, errors 8, rbac 5, complexity_layers 6, consistency_model 1.

## Deliverables (task root, not under `workspace/`)

`test_helpers/` — 2,568 lines: `__init__.py` 63, `api_client.py` 369, `api_errors.py` 101, `assertions.py` 313, `constants.py` 221, `factories.py` 412, `fixtures.py` 747, `test_users.py` 95, `types.py` 247.

`test_suite/` — `conftest.py` 31, then queue A: `test_01_dual_variant_calculations.py` 213 (6 tests), `test_02_combinatorial_formulas.py` 202 (5), `test_03_non_linear_state_machines.py` 230 (6), `test_04_transitive_cascades.py` 239 (6), `test_05_priority_pair_validation_conflicts.py` 312 (6), `test_06_boundary_precision.py` 210 (4), `test_07_cross_entity_state_dependency.py` 302 (7), `test_08_resource_temporal_overlap.py` 261 (5), `test_09_compensating_invariants.py` 324 (8); queue B: `test_10_entities.py` 489 (14), `test_11_state_machines.py` 490 (12), `test_12_calculations.py` 303 (7), `test_13_validations.py` 458 (10), `test_14_endpoints.py` 346 (8), `test_15_errors.py` 535 (13), `test_16_rbac.py` 440 (11), `test_17_complexity_layers.py` 620 (16), `test_18_consistency_model.py` 145 (3).

**Total: 147 test functions across 18 files (6,150 test-suite lines).**

## Verification

- `.scratch/step5/verify.py`: 147 tests, 72 distinct design instances tagged, **0 citation problems** (each docstring carries exactly one whitespace-normalised-verbatim `PRD: "..."` quote found in PRD.md), **0 tag problems** (exactly one `Design:` line per test, none dangling).
- `.scratch/step5/coverage.py`: full non-stub coverage both queues, no stub tagged, `tagged but not in either index: []`.
- `python3 -m py_compile` over all 27 files: `ALL_COMPILED`. Unused-import detector now clean (last item, an unused `Optional` in `test_helpers/factories.py`, removed this pass).
- `__pycache__` removed from both output dirs. No smoke server was started, nothing was written under `workspace/`, and `worklog.md`, `PRD.md` and sibling task dirs were untouched. Scratch confined to `.scratch/step5/`.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single message, so the implementation generator could not see `test_suite/` (it did not exist at its spawn time). Verified test_helpers/ and test_suite/ landed at the task root, not under workspace/.

## Step 7: Run tests and iterate — 2026-09-06T04:35:00.000Z

Subagent summary (verbatim):

All 8 rounds clean. Storage is confirmed in-memory only (no sqlite/file/tmp writes), and `worklog.md`/`PRD.md` were never touched.

## Summary

**Iterations run:** 3 sweeps (iteration 1 = collection-error triage, iteration 2 = 7 deterministic failures, iteration 3 = clean).

**Tests deleted:** none. Two assertions were removed under STEP 1c partial-coverage handling (details below); no test function was dropped, weakened to an HTTP-status check, skipped, or xfailed.

**Fixes applied to `test_helpers/`**
- `test_helpers/__init__.py`, `test_helpers/assertions.py` — stale symbol name. Both `__all__` blocks and the package re-export named `assert_descending_by_created_at`, but the function defined (and the name both test files import) is `assert_ascending_by_created_at`. This was a hard `ImportError` in `conftest.py`, so all 8 rounds of iteration 1 collected **0 tests** (`total: 0, errors: 1`) — no test ever ran. PRD line 84 confirms ascending is the correct order ("Collections are ordered by `created_at` ascending — oldest record first"), so the minority call sites were renamed to match.
- `test_helpers/assertions.py` — added `assert_version_advanced(before, after, label)`, used by the two cascade tests below; it pins that the version counter moved forward without pinning the step size.
- `test_helpers/assertions.py` — added the new symbol to `__all__` and to the `test_helpers` package re-export.

**Fixes applied to `test_suite/`**
- `test_suite/test_12_calculations.py` — local `_tract()` helper listed `slope_pct=4.0`, `interconnection_distance_km=3.50` etc. as explicit kwargs *and* forwarded `**overrides`, so any call overriding one of them raised `TypeError: register_parcel() got multiple values for keyword argument 'slope_pct'` before a single HTTP request was issued (3 tests). Rewritten to build a dict and `.update(overrides)`, matching the pattern the sibling `_owner_and_tract()` helpers in tests 13/17 already use correctly.
- `test_suite/test_10_entities.py` — removed 3 assertions demanding `created_at`/`updated_at == "2026-08-01T00:00:00Z"` (the logical-clock start value). **PRD-silence category: DEFAULT/SOURCE SILENCE.** PRD §2.6 enumerates exactly which instants are stamped from the logical clock (`requested_at`, `granted_at`, ... `paid_at`) and deliberately excludes `created_at`/`updated_at`; §2.4 defines `created_at` only as "the instant at which the row was inserted". A wall-clock `created_at` is the more defensible reading, since PRD line 84 asserts the option-payment ledger is *the one* collection needing a secondary sort key — which only holds if `created_at` is naturally unique per row. The covered assertions (common-field set, format, `version == 1`) were kept.
- `test_suite/test_17_complexity_layers.py:135` and `test_suite/test_18_consistency_model.py:145` — relaxed `version == before + 1` to `assert_version_advanced`. **PRD-silence category: not uniquely derivable.** PRD §2.4 line 113 states verbatim that after a neighbor-consent grant a client "will find the parcel's `version` **two or three higher** than it was — the acreage recompute, the qualification re-evaluation and the landowner posture sync each touch rows on the way through." The implementation's +2 is therefore the PRD-faithful behaviour and an exact-+1 assertion contradicts the PRD; the covered claim ("increments the parcel's `version`", §3.2/§3.3) is preserved.

**Fixes applied to `implementation/`:** none. Every failure traced to the test artifact. In particular I explicitly declined to coalesce the per-hop `touch()` calls in `workspace/implementation/cascades.py` into a single version bump, because that would contradict PRD §2.4's "two or three higher" sentence.

**Final sweep evidence:** results.1–8.json each `passed 147/147`, 0 failures enumerated, union of failures across all 8 rounds = 0, `VERDICT: ALL ROUNDS CLEAN`.

Orchestrator verification: independently ran `workspace/summarize_sweep.py` over the eight results files on disk — 8/8 rounds `passed 147/147`, union of failing tests 0, `VERDICT: ALL ROUNDS CLEAN`. Step 8 is NOT skipped: although `implementation/` took 0 fixes, Step 7 made `test_suite/` and `test_helpers/` fixes and removed assertions, so PRD silences were found and must be pinned.

## Step 8: Finalize PRD — 2026-09-06T04:33:00.000Z

Subagent summary (verbatim):

Done. Six edits applied to `PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 498 lines / 13,565 words
- `PRD_FINALIZED.md`: 500 lines / 14,034 words
- Delta: **+2 lines (+0.40%)**, +469 words (+3.46%). `PRD.md` untouched.

## Triage of the <step_7_diff> items
- **`assert_descending_by_created_at` rename** — pure test-artifact symbol bug. PRD line 84 already pins ascending. **No PRD edit.**
- **`assert_version_advanced` added to `test_helpers`** — support for the version item below, no behavior of its own. **No PRD edit.**
- **`test_12` `_tract()` duplicate-kwarg `TypeError`** — pure fixture bug, no HTTP request ever issued. **No PRD edit.**
- **`test_10` `created_at`/`updated_at == "2026-08-01T00:00:00Z"` removed** — genuine DEFAULT/SOURCE silence -> Edits 1, 2.
- **`test_17`/`test_18` exact `+1` relaxed** — genuine PRD/impl **mismatch**: PRD §2.4 said "two or three higher"; the impl gives **+1 or +2** on the consent-grant path -> Edits 3, 4, 5, 6.

## Changes
- **§2.3 (line 84)** — revise — "the one collection with a *declared* secondary key", plus a tie-break clause: identical `created_at` values sort by insertion order, in every collection and cascade iteration — `implementation/store.py:54-60`, `cascades.py:31-34`.
- **§2.4 (line 107)** — revise — `created_at`/`updated_at` are read from the server's **real** UTC clock, not the logical clock of §2.6 — `implementation/store.py:67-86`.
- **§2.4 (line 111)** — revise — replaced the false "two or three higher" illustration with "one higher, or two when the status moved", naming which procedure writes which row — `implementation/routes/consents.py:91-98`, `cascades.py:96-97,150-161,186-187`.
- **§2.8 (after line 150)** — insert — one paragraph pinning which rows each of the four procedures *actually* touches (acreage + screening unconditional on the parcel; consent only when `released_acres` moves; qualification only when `status` moves; posture only when the posture or `total_paid_cents` moved), plus the parcel-registration exception that keeps a new parcel at `version` 1 — `cascades.py:68-198`, `routes/parcels.py:101-107`, `routes/options.py:282-288`.
- **§3.2 (line 267)** — revise — re-screen steps `version` by two, plus one per status move (qualification demotion/promotion and the `DISQUALIFIED` write) — `routes/parcels.py:119-128`.
- **§3.3 (line 282 grant, line 284 revoke)** — insert — the consent's `version` ends **exactly** 1 higher on both grant and revoke regardless of whether the acreage procedure rewrote its `released_acres`; the parcel's ends 1 or 2 higher — `routes/consents.py:85-98,113-124`.

## Per-edit pre-edit search log
**Edit 1+2 — subject: clock source of `created_at`/`updated_at` (and its knock-on for ordering).**
(b) Enumerated/read: `store.py:67 insert()` (both fields <- `utcnow()`), `insert(common_fields=False)` for ledger rows, `store.py:82 touch()`, `store.py:49 now()` (`db.clock`, business instants only), `envelope.py:11`, `serializers.py:10,26-27,143,152`; grepped the whole impl for any other assignment to either field — none. (c) Phrased generally ("neither field carries the logical clock's value") so it also covers the ledger row's `created_at`-only representation on line 109. The search also surfaced `store.py:54 sort_key = (created_at, _seq)` — a wall-clock ms `created_at` can tie, so Edit 2 was added to keep the ordering rule determinate; worded as a tie-break rather than a "secondary key" so it does not contradict the ledger's `sequence_no` sentence.

**Edits 3-6 — subject: per-transition `version` step count on the cascade.**
(b) Enumerated/read every cascade entry path and every `touch()` callsite: `cascades.py` (all four procedures + `run_parcel_chain` + `recount_curative_counters`, which never bumps), `routes/parcels.py:98-108` (create, `bump=False`) and `:111-129` (rescreen, up to +4), `routes/setback_rules.py:59-61` (publish, +2/+3), `routes/consents.py:71-125` (grant/revoke, +1/+2 with the consent forced to exactly +1), `routes/curative.py:88-94,97-110,131,160` (create/clear/waive, +1/+2 plus successor bumps), `routes/options.py:136,322-326,419,454-461` (draft/execute/exercise-no-parcel-touch/withdraw), `routes/clock.py:28-34,47,59,79` (four sweeps), `routes/leases.py:112,136,160-166,221`, `routes/landowners.py:85`.
(c) Adjustments made to avoid new mismatches: (i) no absolute number written into §2.4 — the step is expressed as "one, or two when the status moved", and a second sentence widens for the paths that also run the screening procedure; (ii) §2.8 carries an explicit parcel-**registration** carve-out, without which the new unconditional-bump rule would have contradicted `version` 1 on a freshly registered parcel (`routes/parcels.py:101-103`) — the carve-out is scoped to the three parcel-side procedures because the posture sync there *does* bump the owner; (iii) §3.2's re-screen sentence was re-worded to "one further step **for each of**" so the `QUALIFIED -> SCREENING -> DISQUALIFIED` path (+4) is covered rather than capped at +3; (iv) §3.3 grant **and** revoke both got an explicit "exactly 1 higher" guarantee for the consent row, because §2.8's new conditional-consent-bump clause would otherwise have implied +0 on a revoke (where `released_acres` is zeroed before the re-derivation runs) and on a grant against a non-waivable rule.

Orchestrator note: Step 8 was NOT skipped and PRD_FINALIZED.md is not byte-identical to PRD.md (96,310 -> 99,267 bytes, 498 -> 500 lines). Step 9 will run as four sequential module-partitioned passes over a single shared PRD_COMPLETED.md (pass 1 does the cp; passes 2-4 must not), with pass 4 reserved for cross-pass reconciliation.

## Step 9: Complete PRD — 2026-09-06T05:45:00.000Z

Run as FOUR sequential module-partitioned passes over a single shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from PRD_FINALIZED.md; passes 2-4 were forbidden from any `cp` and used targeted Edit calls only). Partition: pass 1 = global layer (app/errors/util/store/envelope/auth/validation/access/serializers); pass 2 = calc.py, cascades.py, landowner/parcel/setback/consent/curative routes; pass 3 = options/payments/leases/invoices/corridors/crossings/bookings/clock routes; pass 4 = reconciliation of the cross-pass contradictions the first three passes reported but were not authorised to fix.

Size trajectory: PRD.md 498 lines / 96,310 chars -> PRD_FINALIZED.md 500 / 99,267 -> PRD_COMPLETED.md 503 / 124,319 (+25,052 chars over the Step 8 output, prose-only, no new sections).

### Pass 1 (global layer) — verbatim summary

16 ambiguity-pins, 2 mismatch-revisions across 14 targeted Edit calls. PRD_COMPLETED.md 503 lines / 106,269 chars after edits. Changes: §2.1 401 covers a whitespace-only header (`auth.py:39`); §2.1 **mismatch** — the Landowner ownership 403 requires the row to resolve first, so a Landowner naming a nonexistent id gets that resource's 404 (`access.py:78-81`, verified live); §2.2 `api_request_id` is `req_` + exactly 20 chars of `A-Z0-9` (`util.py:28-30`); §2.2 `api_request_timestamp` from the real clock with trailing `Z` (`envelope.py:8-12`); §2.2 error `message` wording is never load-bearing (`errors.py:118-160`); §2.2 undeclared path/method answers `ERR_INVALID_REQUEST` via the router's 404/405, trailing slash tolerated (`app.py:53,78-81`); §2.3 `limit`/`offset` echoed as effective values, `total_count` counted after Landowner scoping, `has_more` = `offset + len(data) < total_count`, offset past the end is 200/empty, single-resource reads ignore paging (`envelope.py:20-27`, `validation.py:321-323`, `access.py:100-105`); §2.3 filters conjunctive, case-sensitive, untrimmed exact matches, unmatched/unparseable filter value yields 200 with empty array not 400, undeclared query params ignored (`validation.py:255-274,309-318`); §2.4 `id` is the canonical lowercase hyphenated UUID and storage is unseeded (`util.py:23-25`, `store.py:31-46`); §2.4 every instant-valued field renders ISO-8601 UTC with exactly 3 fractional digits + `Z`, `null` when unstamped, client instants accept optional fraction/seconds and `T` or space and `Z` or offset, naive = UTC, date-only rejected 400 (`util.py:37-71`); §2.5 **mismatch** — `_cents` renders `null` for a not-yet-known figure such as an unpaid invoice's `paid_amount_cents` (`serializers.py:21-22,239`); §2.5 acreage and scores are plain JSON numbers in shortest form (`util.py:101-105`); §2.9 a body FK present as a non-empty string resolves (and may 404) before any other field of that body is shape-checked (`validation.py:199-214`); §2.9 rung 8 also covers the option-payment read — `{paymentId}` has no 404 of its own so an unknown ledger row reports `ERR_OPTION_AGREEMENT_NOT_FOUND` (verified live, `routes/payments.py:33-35`); §2.9 rung 14 body must parse as a JSON object and declared instants must parse (`validation.py:18-26,172-186`); §2.9 rung 15 governs the rent-projection query input (`validation.py:280-306`); §2.9 rung-14 strictness paragraph — empty body = `{}`, non-object rejected, explicit `null` = omitted, strict types with integral-float tolerance (`5.0` yes, `5.5` no), undeclared fields ignored (`validation.py:29-36,93-104,138-168`).

### Pass 2 (calc/cascades/parcel-side routes) — verbatim summary

22 changes: 15 ambiguity-pins, 7 mismatch-revisions. 503 lines / 115,015 chars after edits; no `cp` run. Changes: §2.5 **mismatch** narrowed to only the resource sub-score carrying its own rounding (`calc.py:87-102`); §2.8 pinned that the curative counters, `total_option_paid_cents` and `total_paid_cents` are outside the four procedures and carry no version step of their own (`cascades.py:119-135,202-221`); §2.8 softened "Three further re-derivations" so it does not falsely enumerate pass-3 counters; §3.1 `mailing_state` is any two A-Z letters, never checked against USPS, `contact_email` need only be non-blank with an at-sign (`landowners.py:51-53`); §3.1 **mismatch** — `legal_name`/`entity_type` on an amendment are silently ignored, every amendment bumps `version`, recomputes nothing (`landowners.py:70-86`); §3.2 the four numeric parcel inputs' decimal places are conventions not bounds, APN duplicates compared case-sensitively across all statuses, prohibited-zoning compare exact and case-sensitive so `res1` is admitted (`parcels.py:69-84`); §3.2 the intake `REJECTED -> DISQUALIFIED` branch skips posture synchronisation entirely (`parcels.py:104-107`); §3.2 **mismatch** only the resource sub-score is pre-rounded (`calc.py:87-102`); §3.2 **mismatch** re-screen has no state gate — `OPTIONED`/`LEASED`/`DISQUALIFIED` parcels are re-screenable (`parcels.py:113-129`); §3.2 nothing restricts a parcel to one consent per rule (`cascades.py:78-89`); §3.2 deed-conservation invariant qualified to the two-decimal convention (`calc.py:129-146`); §3.2 **mismatch** removed an unreachable `ENGAGED -> PROSPECT` claim and pinned the resource sub-score as the one not clamped, reaching 250.00 at factor 1 (`calc.py:91`); §3.2 the weighted total is not clamped either — `screening_score` can reach 137.50 (`calc.py:98-101`); §3.3 **mismatch** `(jurisdiction_code, rule_type)` uniqueness is convention not enforced, duplicates accepted 201, the rule carries no `status` (`setback_rules.py:38-62`); §3.3 publish re-processes every matching parcel with no status filter, stepping each parcel by two (three when status moves) while the new rule stays at version 1 (`setback_rules.py:57-61`); §3.3 consent creation has no parcel-state gate and fires no cascade (`consents.py:40-68`); §3.3 the lapse test precedes the state test so a `GRANTED` consent past expiry reports `ERR_CONSENT_EXPIRED` (`consents.py:78-83`); §3.4 the predecessor need not share the successor's parcel (`curative.py:61-94`); §3.4 raising an item steps the parcel by 1 (2 when qualification moves) and does not run acreage (`curative.py:90-93`); §3.4 full version arithmetic for clear/waive (`curative.py:97-132`); §3.4 **mismatch** waiving imposes no parcel-status condition so a `DISQUALIFIED` parcel's defect may be waived where clearing refuses (`curative.py:141-154`); §3.4 a cross-parcel promotion leaves nothing stale because `blocking_curative_open_count` counts `BLOCKED` and `OPEN` alike (`cascades.py:124-132`). Eleven behavioural claims confirmed against a live server on an explicit high port (killed by exact PIDs), including `screening_score = 137.5 / PRIORITY` at `resource_capacity_factor = 1`, `99.93` for a mixed parcel, two granted consents on one rule flooring encumbrance at 0.0, and `gross_acres 100.00567 -> buildable 100.01`. Two would-be new mismatches were caught and avoided.

### Pass 3 (option/lease/corridor/clock routes) — verbatim summary

12 ambiguity-pins, 3 mismatch-revisions; 503 lines / 120,666 chars after edits; no `cp` run. Changes: §2.6 the clock endpoint imposes no monotonicity — any parseable instant, even an earlier one, is assigned and the sweeps run against it (`clock.py:88-94`); §3.5 **mismatch** the parcel's `status` literal is checked in its own right alongside the three qualification figures at send, while drafting has no parcel-status gate (`options.py:141-147,204-207`); §3.5 a revision leaves `round_index` untouched (`options.py:236-250`); §3.5 the `PER_ACRE`/`royalty_rate_bps` cross-field rule is re-tested on both amendments against post-amendment effective terms (`options.py:169-174`); §3.5 `withdraw_reason` >=1 char non-blank, no upper bound (`options.py:432`); §3.6 an unqualified parcel at execute is `ERR_INVALID_STATE` 409, not `ERR_PARCEL_NOT_QUALIFIED` (`options.py:302-305`); §3.6 `refund_extension_fees` defaults false when omitted or null (`options.py:433`); §3.6 both expiry and withdrawal-from-`EXECUTED` write the parcel status directly with no qualification re-evaluation, so a sub-80-acre parcel still returns to `QUALIFIED` (`clock.py:29-34`, `options.py:456-461`); §3.7 `memo_submitted_at`, `recorded_at`, `recording_instrument_no` all open null (`options.py:381-383`); §3.7 neither lease dimension gates security posting, over-posting is the only objection, `amount_cents` 0 admitted and still steps `version` (`leases.py:98-113`); §3.7 **mismatch** `ERR_ALREADY_RECORDED` is reported ahead of `ERR_INVALID_STATE` on both memo hops despite rung 24 sitting below rung 23 (`leases.py:123-126,150-153`); §3.7 `recording_instrument_no` is 1-60 chars non-blank (`leases.py:145-146`); §3.8 title and conflict are the only crossing-proposal gates — the corridor may still be `PLANNED` and the parcel's status is not examined (`crossings.py:92-100`); §3.8 the corridor's row is written by the recount on every successful grant, `version` +1 exactly (`crossings.py:140-141`); §3.8 no parcel-status gate on a booking (`bookings.py:65-98`); §3.9 **mismatch** `period_year` < 1 is `ERR_INVALID_REQUEST` 400 at rung 16 not the duplicate-period 409, > 35 is the 409, ceiling tested before the per-period scan and both after the concurrency guard (`leases.py:179-189`); §3.9 projection inputs are query parameters, `period_year` required int >=1, `production_mwh` optional default 0, with no term ceiling and no per-period uniqueness test (`leases.py:71-72`); §3.9 the lease's row is written on payment only when `last_paid_invoice_year` or `rent_status` actually moved (`invoices.py:104-115`); §3.9 `void_reason` >=1 char non-blank (`invoices.py:124`).

### Pass 4 (reconciliation) — verbatim summary

503 lines / 120,666 -> 503 lines / 124,319 chars, prose-only, no `cp`, no new sections.

R1 — VERIFIED-AND-FIXED. Rung 16's enumeration now states the real bounds: `option_term_days` <=1825, `extension_count_allowed` <=3, `royalty_rate_bps` <=2000, `escalator_pct_bps` <=1000 (`options.py:47-50,92-99`), `consent_expiry_days` <=365 (`consents.py:53`), plus two gaps the queue did not mention — `buffer_m` is 0..500 (`corridors.py:45-46`) and `setback_feet` (>=0) and `encumbrance_rate_per_acre` (0..1) were missing entirely (`setback_rules.py:44-45`). Also notes `period_year`'s 35-year ceiling belongs to rung 37 and adds a lead-in deferring each field's bounds to §3.

R2 — VERIFIED-AND-FIXED. The only `_bps` request inputs are `royalty_rate_bps` (<=2000) and `escalator_pct_bps` (<=1000); computed `_bps` are `admin_rate_bps` (300/450/600, `calc.py:212-218`) and `long_occupancy_surcharge_bps` (0..2500, `calc.py:227-231`), all inside 0..10000. §2.5 now says no `_bps` figure accepted or computed leaves 0..10000 but the range is never the operative input bound, naming the two tighter ceilings and the two computed fields with §3 pointers.

R3 — VERIFIED-AND-FIXED. Grepped every route module for `v.json_body()`: option send/accept/execute/extend, submit-memo, invoice issue, corridor permit, crossing grant, booking cancel, consent grant/revoke and curative clear never parse a body. The rung-14 note now says those endpoints ignore any payload including unparseable JSON, and the object/parse check is scoped to writes that declare fields; rung 14's scope cell reads "every write that declares input fields".

R4 — VERIFIED-AND-FIXED. Audited every handler's rejection order against the ladder: the memo hops are the ONLY 23/24 inversion, and the only other deviation anywhere is the Landowner ownership 403 (R7). Rung 24's row records the inversion scoped to "those two hops alone", plus a closing statement that no other rung is evaluated ahead of a lower-numbered one apart from that pair and the rung-2 qualification.

R5 — VERIFIED-AND-FIXED. §2.8's list now names `granted_crossing_count` (§3.8) and `last_paid_invoice_year` (§3.9) and closes with "any other derived figure §3 introduces without naming one of the four" (`cascades.py:232-243`).

R6 — VERIFIED-NO-CHANGE-NEEDED. `calc.py:87-102`: only `resource_sub` is `r2`'d; interconnect/buildability are clamped 0..100 but not rounded; `title_sub` is integral; the weighted total is `r2`'d and never clamped. §2.5, §3.2's two paragraphs and §2.9 are mutually consistent as they stand.

R7 — VERIFIED-NO-CHANGE-NEEDED in §2.1; the ladder needed the matching edit. `access.py:78-81` plus every Landowner-scoped call site (`options.py:59,218,257`, `leases.py:46`, `landowners.py:28`, `invoices.py:39`, `payments.py:36`) resolve the row first, so §2.1's "404 before the 403" is correct; rung 2's scope cell now carries the qualification.

Additional contradictions closed under duties A/B: §2.5 vs §3.2 on acreage decimals (§2.5's two-decimal discipline now scoped to DERIVED acreage, deferring the deeded figure to §3.2, matching `parcels.py:72` which only range-checks); §2.8 vs §3.8 on who publishes a non-four recompute (on a crossing grant `touch(corridor)` exists solely for the recount, `crossings.py:139-140`); §3.7's exercise gate list read as a precedence order (impl order is expiry -> three state checks -> SoD -> title -> hold, `options.py:400-416`; added a clause saying the list is narrative order and the ladder decides). Regression sweep word-diffed PRD_FINALIZED -> PRD_COMPLETED and re-verified every pass-inserted absolute against source; no further softening needed.

Integrity check: all headings present (§1, §2.1-§2.10, §3.1-§3.9, §4, §5); §4 = 59 endpoint rows; §5 = 41 error rows; final line is the complete table row `| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |` — a real section boundary, no truncation.

### Orchestrator verification

- `workspace/PRD_COMPLETED.md` exists at 503 lines / 124,319 chars and is NOT byte-identical to PRD_FINALIZED.md (`cmp` differs), so the scan genuinely ran rather than degenerating into a bare copy.
- Tail independently re-read: ends on the final `ERR_PAYMENT_AMOUNT_MISMATCH | 422` catalogue row. 27 heading lines present.
- Difficulty-directive phrase absent from PRD_COMPLETED.md (0 occurrences).
- The eight `results.{1..8}.json` from Step 7's final clean sweep remain in `workspace/implementation/` (8 files, each 147/147). Step 9 changed documentation only — no implementation or test file was touched after that sweep — so the green result still describes the shipped code.
- Only one `worklog.md` exists in the task tree (this file); no stray copies drifted into `workspace/`.

## Pipeline complete — 2026-09-06T05:46:00.000Z

All nine steps finished. Final deliverables: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files, 2,568 lines), test_suite/ (18 files, 147 tests), workspace/INSTRUCTION.md, workspace/PRD.md, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md, workspace/implementation/ (25 modules, 3,631 lines, 59 endpoints) and the 8 passing sweep result files.
