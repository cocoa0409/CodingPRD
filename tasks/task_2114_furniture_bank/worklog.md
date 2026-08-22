# Worklog — task_2114_furniture_bank

## Step 1: Create Task Directory — 2026-08-17T03:12:21.485Z

Created `./tasks/task_2114_furniture_bank/` and `./tasks/task_2114_furniture_bank/workspace/`. Index 2114 chosen as max existing index (2113) + 1.

## Step 3: Copy Shared Files — 2026-08-17T03:12:38.925Z

Copied `./INSTRUCTION.md` → `tasks/task_2114_furniture_bank/workspace/INSTRUCTION.md` (1424 bytes). Executed early since it has no dependency on Step 2.

## Step 2: Generate Scaffold — 2026-08-17T04:32:19.426Z

All three scaffold artifacts are generated and lint-clean.

## Files written
- `SCAFFOLD.yaml` (§1.0–§1.7 + preamble; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Counts (verbatim for worklog)
- **Entities:** 14 (PartnerAgency, Client, Referral, Voucher, VoucherLine, DonationOffer, DonationItem, InventoryItem, Truck, DeliveryRun, DeliveryStop, Volunteer, CrewAssignment, WaitlistEntry)
- **State machines:** 9 (62 transitions) + 2 concurrency rules (OCC on Voucher.version, DeliveryRun.version)
- **Calculations:** 8 (+2 named conserved-quantity invariants)
- **Validations:** 29 (ordered, first-failure-wins)
- **Endpoints:** 48 (incl. `/_clock/set_current_utc`, `/_ops/run-cycle`)
- **Errors:** 46
- **Roles:** 6 (PlatformAdmin, CaseManager, IntakeCoordinator, WarehouseLead, DispatchPlanner, Volunteer)
- **Difficulty-design instances:** 19 across all 9 rule_ids (2 each, 3 for `combinatorial_formula`)
- **Corner-design instances:** 65 across all 9 guide sections (58 with full `test_recipe`, 7 `excluded_because` stubs)

## Profile
Expert+ band: `quota_allocation` x `temporal_windowing`, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / selector_policy`, topology **flat**, state-machine shape **cyclic** (+ parallel `Voucher.status x Voucher.fee_status`), role model **segregation_of_duties**, `api_prefix: ""`.

## Verification performed
- `scaffold_lint.py <task-dir>` -> **`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** (48 endpoints, 14 entities, 19 + 58 instances, 922 calls scanned).
- Custom checks, all zero-violation: placeholder closure across 922 calls, name uniqueness across both design files, `excluded_because` -> difficulty-instance resolution, forbidden concurrency vocabulary, every one of the 46 errors reachable from a design instance, and every `grounds[]` reference resolved against §1.1–§1.7 (calculations/constants, entity fields, transitions, priorities, error ids, concurrency rule ids, invariants, roles, global constants, endpoints).
- Every formula-derived assert literal was computed in Python before being written (delivery fees 5700/3990/1710, 6700/4690/2010, 9000/9000/0, 6900/4830/2070, 4200/2940/1260, 4200/2100/2100; chargebacks 946 / 1125 / 428 / 625; priority scores 45.0 / 49.0 / 30.0 / 24.0 / 18.0; ratios 0.5 / 0.333 / 50.0; and all date stamps 2026-09-18, 2026-11-02, 2026-10-03, 2026-08-18, 2026-08-25T16:00, 2026-08-07T16:00).

## Design notes worth carrying forward
- Clock default pinned to `2026-08-01T00:00:00Z`; every fixture date sits after it.
- `no_show_chargeback` deliberately diverges under the two rounding orders (946 vs 945) — round-per-line-then-sum is pinned.
- Voucher's two axes are coupled by exactly one rule: money fields freeze once `fee_status` leaves `PENDING`.
- The bed-bug cascade cancels only *same-service-date* runs, so `ERR_TRUCK_BED_BUG_LOCKOUT` stays reachable at dispatch on later-date runs.
- `POST /delivery-runs/{id}/dispatch` accepts `PLANNED` so `ERR_CREW_BELOW_MINIMUM` is observable; zero-stop runs fail earlier with `ERR_RUN_INVALID_STATE`.
- Pre-existing `worklog.md` and `workspace/` in the task dir were left untouched. No sibling task directory was read.

**File sizes:** SCAFFOLD.yaml 2821 lines / SCAFFOLD_DIFFICULTY_DESIGN.yaml 1852 lines / SCAFFOLD_CORNER_DESIGN.yaml 3543 lines.

## Step 4: Generate PRD — 2026-08-17T04:44:33.615Z

The PRD is complete and all three hard contracts pass.

**Output:** `workspace/PRD.md` — **445 lines**

**Structure:** §1 Introduction (3 paragraphs) · §2 Global Specifications (10 subsections: RBAC/identity, verbatim response envelope, pagination, common properties, path resolution, logical clock + operational cycle, precision, OCC, rejection precedence, cascade integrity/invariants) · §3 Business Logic (9 domain-derived subsections: agencies & quota epochs -> referral lifecycle -> voucher issuance -> donation triage -> warehouse intake/quarantine -> allocation & waitlist -> fleet/crew/dispatch -> delivery outcomes -> fees & billing) · §4 endpoint table (4 columns) · §5 error table (2 columns).

**Self-audit (written vs scaffold):**
- Entities: **14 / 14**
- State transitions: **62 / 62** (all expressed as explicit `FROM -> TO` arrow pairs)
- Calculations: **8 / 8** (all formulas as prose; no operator syntax, no fuzzy words — grep-verified clean)
- Validations: **29 / 29** (rendered as the ordered rejection-precedence list in §2.9, each with its `error_id`, HTTP status and `applies_to` scope enumerated)
- Endpoints: **48 / 48** table rows
- Error IDs: **46 / 46** in the §5 table, and **46 / 46** also mentioned in §1–§4 narrative
- Roles: **6 / 6** (each `identity:` translated — `CaseManager` -> PartnerAgency-backed, `Volunteer` -> Volunteer-backed, the other four opaque with the `WarehouseLead` -> `inspector_user_id` segregation carve-out)

**Hard contracts:**
```
Field coverage check:
- entities[].fields: 90 required, 90 present, 0 missing
- endpoints[].request_body: 46 required, 46 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing
- nested/response identifiers (inspections elements, run-cycle summary, unmet-need row shape, common fields): 25 required, 25 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed in prose (ordered list, §2.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_voucher_version / expected_run_version + ERR_STALE_*_VERSION + 412), 0 missing
- state_machines[].transitions: 62 checked, 62 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed incl. constants, evaluation order, precision, variants, 0 missing
- validations[] conditions: 29 checked, 29 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 48 checked, expressed (incl. 5-step bed-bug cascade, 3-step no-show contagion, 6-pass run-cycle with 3a/3b), 0 missing
- entities[].fields[] structured content: 90 checked, reconstructible from prose (defaults, initial values, enum member sets), 0 missing
- sibling-branch symmetry: 6 groups checked (5 allocate outcomes, 3 cancel sources, 3 expiry sources, 2 intake branches, 2 triage branches, 4 fee actions), 6 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 952
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 was verified byte-identical to `section-2.2-response-structure.md`. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

One process note worth recording: mid-generation I truncated the file to regenerate §4/§5 and silently dropped the last §3 paragraph (the fee-settlement block) — caught only because the Contract 1 audit flagged `action` as missing. The audit also initially produced garbage because triple-backtick fences in §2.2 break naive inline-code regex parity; fenced blocks must be stripped before extracting backticked tokens. Both are the same class of silent-truncation failure this task warned about.

**Orchestrator verification:** PRD.md = 445 lines; 0 design-index tokens leaked; `test_suite/` confirmed absent prior to launching Step 6 (physical isolation for impl-gen).

## Step 5: Generate Unit Tests — 2026-08-17T05:17:11.205Z

Test infrastructure and suite are complete. Here is the worklog entry.

## Summary

**Files: 12 test files + conftest (test_suite/), 9 files (test_helpers/). 96 test functions, 4,371 + 2,124 lines.**

### Per-queue instance coverage

| Queue | Instances | Translated | Skipped | Tests emitted |
|---|---|---|---|---|
| **A — Difficulty** (`§1.8`) | 19 | **19 / 19** | 0 | 38 (exactly 2 per instance) |
| **B — Corner** (`§1.9`, non-stub) | 58 | **58 / 58** | 0 | 58 (1 per instance) |
| **B — Corner** (`excluded_because` stubs) | 7 | n/a — not translated | — | 0 |

**No instances were skipped.** All 7 corner stubs' `difficulty_instance` cross-references were verified to resolve to real `SCAFFOLD_DIFFICULTY_DESIGN.yaml` `name:` values; no placeholder tests emitted for them.

### Verification passes (all green)
- **Design tags**: every one of the 96 tests ends its docstring with exactly one `Design:` line; 0 untagged, 0 dual-tagged, 0 unresolvable tags.
- **PRD verbatim**: 192 PRD quotations extracted and checked against `workspace/PRD.md` after whitespace normalisation — **0 non-verbatim**.
- **No `pytest.mark.skip` / `skipif` / `xfail`**; no "scaffold"/table references leaked into generated code.
- `pyflakes` clean; `pytest --collect-only` -> 96 tests collected.

### One assertion deliberately dropped (two-reader failure, instance still covered)
- `Corner/cross_cutting_layers/corner_ops_run_cycle_advances_quota_epoch_and_zeroes_usage` — the yaml asserts `restanding_count == 1`. PRD §2.6 names the field but never defines whether it counts *agencies recomputed* or *agencies whose standing changed*; two faithful readers would ship 1 and 0. The rest of the instance (epoch 1->2, `quota_used` zeroed, standing GOOD, referral still APPROVED with `approved_epoch` 1, `expired_referral_count` 0, `quota_epoch_advanced` true) is asserted, so the instance is still covered by >=1 test.

### test_helpers file list
```
test_helpers/__init__.py      45   barrel export (framework generics + domain)
test_helpers/types.py        419   14 entity TypedDicts + 20 status/role enums
test_helpers/api_client.py   227   ApiClient(GenericApiClient), 48 endpoint methods
test_helpers/api_errors.py   107   ApiErrorId (46 ids) + HTTP map, registered with framework
test_helpers/assertions.py   321   14 per-entity asserts + quota/stock conservation + money identity
test_helpers/factories.py    173   payload factories, input fields only
test_helpers/constants.py    100   fee/score/triage/chargeback/standing constants
test_helpers/test_users.py    70   role headers + make_case_manager_headers / make_volunteer_headers /
                                   make_warehouse_lead_headers (identity threading for the two
                                   entity_backed roles and the two distinct WarehouseLead operators)
test_helpers/fixtures.py     662   5 tiers: primitives -> state progression -> hierarchy ->
                                   stock supply (clean / quarantined / live-pest) -> allocated,
                                   crewed, dispatched, delivered, banned-household, suspended-agency
```

### Notes for the implementer-facing run
- Every fixture builds state from scratch through declared endpoints only; no test depends on another's state (`--isolation per-test-server` safe).
- The logical clock is set explicitly by every test that depends on time; `2026-08-01T00:00:00Z` startup default is exercised once (agency-defaults test).
- WarehouseLead segregation of duties is threaded through two constant opaque ids (`wl-inspector-1` / `wl-release-2`), and a third (`wl-inspector-2`) is used for the live-pest cascade so the inspecting lead differs from the clean-intake lead.

**Orchestrator verification:** 12 test files + conftest present; 96 test functions collected; 9 test_helpers modules present.

## Step 6: Generate Implementation — 2026-08-17T05:19:46.978Z

Implementation complete and verified. Here is the report.

## Files (`workspace/implementation/`, 3171 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 11 | guarded pip install + `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 70 | blueprint registration, error envelope handlers, `0.0.0.0:$PORT` (default 10000) |
| `core.py` | 196 | logical clock (default `2026-08-01T00:00:00Z`), ISO-8601 parse/format, `round_half_up`, global constants |
| `db.py` | 244 | in-memory dicts, `new_entity`, `touch`, serialisation, reverse-reachability helpers |
| `errors.py` | 72 | 46-entry error->HTTP catalogue + `ApiError` |
| `envelope.py` | 44 | `meta`/`response_type`/`data` envelope + pagination meta |
| `validation.py` | 187 | declarative body schema (rule 3), pagination (rule 4) |
| `auth.py` | 76 | header auth (rules 1-2), path/body resolution (5-6), agency & self scoping (7-8) |
| `services/calc.py` | 294 | need score, delivery fee, chargeback, standing, triage, selector keys |
| `services/allocation.py` | 181 | waterfall selector, waitlist upsert/promote, cancel/expire stock release |
| `services/delivery.py` | 250 | run feasibility, dispatch, outcomes, bed-bug + no-show cascades |
| `services/donations.py` | 132 | intake/grading/quarantine, truck & volunteer window predicates |
| `services/cycle.py` | 124 | six-pass operational cycle (1, 2, 3, 3a, 3b, 4, 5, 6) |
| `services/report.py` | 85 | unmet-need report |
| `routes/*.py` | 1204 | 48 endpoints across 8 blueprints |

**Endpoints: 48/48** (verified against the Flask URL map). **Errors: 46/46** (every catalogue id is reachable in code; verified programmatically). Storage is process-memory only — no file, DB, or cache; a `start.sh` restart returns an empty store (verified). No seeding anywhere.

Verified with four hand-written scenario suites (~150 assertions) covering the happy path, quarantine/SoD/dwell, live-pest cascade, no-show contagion, chargeback rounding (1125 / 625 / round-per-line), dual fee variants (8100/5670/2430 provisional vs 9000/6300/2700 final under the 9000 cap), billing freeze, expiry cycle, promotion pass, standing at exactly 0.25, OCC on both axes, precedence orderings, and pagination.

## PRD ambiguities resolved (judgment calls)

1. **Truck `label` uniqueness** — PRD declares it, catalogue has no dedicated id -> duplicate returns `ERR_VALIDATION` (400).
2. **`bed_bug_attestation` false at submit** — no id assigned; chose `ERR_CLIENT_BED_BUG_BLOCK` (422) because rule 3 explicitly applies only to "endpoints that accept a body" and submit has none, while rule 13's `applies_to` includes referral submission.
3. **Household not `ACTIVE` at submit** — no id assigned; chose `ERR_CLIENT_DELIVERY_BANNED` (422) (its catalogue condition is literally "the household is ON_HOLD"), evaluated at precedence slot 14.
4. **Intake `inspections` coverage** — its `ERR_VALIDATION` is checked *after* the offer state gate, so intake from a non-`PICKUP_SCHEDULED` state always answers `ERR_OFFER_INVALID_STATE`.
5. **`restanding_count`** — defined as the number of agencies recomputed (i.e. all of them), per §2.6 step 3 "Every agency's standing is recomputed", not the number that changed.
6. **Promotion pass scope** — runs the selector over vouchers in `ISSUED` or `PARTIALLY_ALLOCATED` that hold at least one `WAITING` entry, in `created_at` order; a voucher with no waitlist entry is never touched by the cycle.
7. **Version semantics** — a row mutated several times inside one request moves by exactly +1 (§2.4 "increases by exactly 1 on every mutation"), and indirect mutations (volunteer hours/reliability, agency ledger, client counters, run derived fields) do bump.
8. **Minted stock versions** — clean-branch and DISPOSED units land at `version` 2 (created `QUARANTINED`, then the landing edge applied in the same request, exactly as §3.5 says "it bumps the unit's version"); units left `QUARANTINED` stay at 1.
9. **`GET /delivery-runs/{id}/stops` sorted by `sequence`** ("in routing order", §4); every other list uses `created_at` ascending with insertion order as tie-break.
10. **Stop booking checks the run's state gate before the voucher's** (path resource resolves before body FK); both sit at precedence 11.
11. **Crew respond run-state preconditions** (CONFIRM needs `PLANNED`, WITHDRAW needs `PLANNED`/`CREWED`) answer `ERR_RUN_INVALID_STATE`; assignment-state failures answer `ERR_CREW_ASSIGNMENT_INVALID_STATE`.
12. **APPROVE does not write `review_note`** — only RETURN and DENY store it.
13. **Intake recomputes `accepted_item_count`/`rejected_item_count`** after D-grade demotions, to keep the field definitions true.
14. **`lines` must be non-empty** on voucher issuance, and `amount_cents` is required (`ERR_VALIDATION`) when the settlement action is `RECORD_PAYMENT`.
15. **Query-param filter values are not enum-validated** — an unrecognised filter matches nothing rather than erroring (rules 3/4 cover bodies and pagination only).
16. **`api_request_timestamp` uses wall-clock UTC** (transport metadata); every business instant — including `created_at`/`updated_at` — comes from the logical clock.
17. **No-show ban threshold uses `>= 2`** ("when that raised count reaches 2"), so a later strike re-stamps the ban.
18. **Unresolvable or empty-string FK ids yield the entity 404**, not 400; only the PRD-declared non-empty constraints (`name`, `label`, `donor_name`, `donor_phone`) are enforced as `ERR_VALIDATION`.

**Orchestrator verification:** no sqlite/file-write/json.dump/pickle/tmp-cache persistence found; `start.sh` execs `python3 app.py` in foreground; `test_suite/` and `test_helpers/` were not read by this subagent (launched concurrently with Step 5, before `test_suite/` existed).

## Step 7: Run Tests and Iterate — 2026-08-17T05:25:35.924Z

The 8-round parallel stability sweep came back completely clean on the first iteration, so no diagnostic protocol steps were triggered.

## Summary

**Iterations run:** 1 (one full 8-round parallel sweep; three earlier launches aborted immediately on my own malformed `--start-command` — it lacked the `cd` into `implementation/`, so the server exited 127 before any test ran. Those were operator error on my part, not task failures, and produced no results.)

**Sweep result:** all 8 concurrent rounds passed `96/96` (`passed=96 failed=0 errors=0 skipped=0 total=96` in every `results.${i}.json`, all written at 05:24:34 after the pre-sweep `rm -f results.*.json`, so none are stale). Union of failing tests across all 8 rounds is empty — no flakiness surfaced, including in the timing-sensitive concurrency tests (`test_replaying_a_spent_voucher_version_on_allocate_is_refused`, `test_replaying_a_spent_run_version_on_stop_booking_is_refused`) and the default-port-collision-prone paths.

**Tests deleted:** none. No test failed either sub-check of STEP 1, because no test failed at all.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Integrity checks performed before signing off** (to confirm the green result is real rather than a suite that had been hollowed out by a prior agent):
- 96 test functions across 12 test files + `conftest.py` — matches the stated inventory exactly.
- Zero `pytest.mark.skip`, `pytest.mark.xfail`, or `pytest.skip` anywhere in `test_suite/` or `test_helpers/`.
- No persistence in `implementation/`: no sqlite, no `open(`, no `json.dump`, no pickle/shelve, no `/tmp` cache, no external store. All 14 entity tables are plain in-memory dicts initialized empty in `implementation/db.py` (lines 21-34), so the per-test-server restart genuinely wipes state.
- No seeded/preloaded entity data — the only `seed` matches are comments in `app.py` and `db.py` explicitly stating nothing is seeded.

One note for the caller: the sweep leaves eight `results.*.json` files in `workspace/implementation/`. They are build artifacts inside the implementation directory and `workspace/implementation/` is currently untracked in git, so they'd be swept into any commit of that directory — worth deleting or ignoring before committing.

**Orchestrator independent verification (not delegated):** re-read all 8 `results.*.json` -> every round `passed=96 failed=0 errors=0 skipped=0 total=96`; `grep -c "^def test_"` across `test_suite/*.py` = 96; skip/xfail/pytest.skip marker count across `test_suite/` + `test_helpers/` = 0; `Design:` tag count = 96 (1:1 with test functions). Green result confirmed genuine.

## Step 8: Finalize PRD — SKIPPED — 2026-08-17T05:25:35.924Z

Skip condition met per the pipeline spec: Step 7 exited on its first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond baseline. `PRD.md` already uniquely determined every behavior the test suite exercised, so there is no Step 7 diff to patch and no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-17T05:39:29.130Z

`workspace/PRD_COMPLETED.md` is written.

## Size

| | PRD.md | PRD_COMPLETED.md |
|---|---|---|
| Lines | 445 (446 incl. trailing) | unchanged — every edit is in-paragraph |
| Chars | 91,246 | 102,618 (**+11,372**) |
| Lines touched | — | 41 of 445 |

## Counts
- **49 changes**: 43 ambiguity-pins, 6 mismatch-revisions.
- No new sections, no new paragraphs, no reordering, no table edits.

## Changes

- §2.1 (Volunteer bullet) — insert — ambiguity — self-scoping covers only the crew response and the single volunteer read; the nested crew-assignment listing has no ownership check — `routes/directory.py:113-119`
- §2.1 (CaseManager bullet) — insert — ambiguity — the nine scoped operations are all single-resource; household/referral/voucher listings **and** a voucher's nested lines/stops collections are unscoped — `routes/clients.py:51`, `routes/referrals.py:64`, `routes/vouchers.py:96,108,117`
- §2.3 — insert — ambiguity — `created_at` ties break on insertion sequence; the run's stop list is the sole `sequence`-ordered endpoint (a voucher's stop list is not); filters are exact string matches, unmatched values yield an empty page, unknown params ignored — `db.py:124-129`, `routes/runs.py:168`, `routes/_common.py:9-15`
- §2.4 — revise — **mismatch** — a request moves any row by at most 1 however many fields/cascade steps hit it, and a no-op recompute (standing, run derived numbers, waitlist rescore, line fill) is not a touch — `db.py:72-87`, `calc.py:216`, `delivery.py:44-53`, `allocation.py:32,108`
- §2.5 — insert — ambiguity — `rescheduled_from_run_id` resolved after `truck_id` — `routes/runs.py:51-53`
- §2.6 — insert — ambiguity — the clock move answers 200 with an empty `data` object — `routes/ops.py:19`
- §2.6 — insert — ambiguity — `advance_quota_epoch` defaults to false — `routes/ops.py:26`
- §2.6 — insert — ambiguity — the whole cycle is one request, so an agency hit by passes 1+3+6 moves version by exactly 1 — `services/cycle.py:143`, `db.py:80`
- §2.6 pass 2 — insert — ambiguity — only `ISSUED`/`PARTIALLY_ALLOCATED`/`ALLOCATED` expire; a `SCHEDULED` voucher is skipped; the pass reads the referral's `expires_at` directly — `services/cycle.py:140,171-177`
- §2.6 pass 3b — insert — ambiguity — a ban stamp exactly at now counts as passed; `delivery_ban_until` is not cleared on reinstatement — `services/cycle.py:202-209`
- §2.6 pass 5 — insert — ambiguity — candidates are vouchers with >=1 `WAITING` entry in `created_at` order, each run through a full allocation round that bumps version and rewrites provisional money — `services/cycle.py:232-246`
- §2.6 — insert — ambiguity — definitions for all seven summary counters; notably `restanding_count` = every agency visited (not those that changed) and `promoted_waitlist_count` = entries promoted (not vouchers) — `services/cycle.py:167,178,185,210,246,254`
- §2.7 — insert — ambiguity — `fill_ratio` is rounded half up — `services/calc.py:148`
- §2.9 rule 3 — insert — ambiguity — an explicit `null` counts as absent; no-body action endpoints reject any field as unknown — `validation.py:124-128`, `routes/referrals.py:79`
- §2.9 rule 14 — revise — **mismatch** — `ERR_CLIENT_DELIVERY_BANNED` also fires on referral submission for a non-`ACTIVE` household — `routes/referrals.py:99-100`
- §3.1 — insert — ambiguity — a 0-cent chargeback posts nothing and does not bump the agency's version — `services/delivery.py:229-231`
- §3.2 — insert — ambiguity — referral draft resolves `client_id` before `agency_id`; either scope mismatch is `ERR_AGENCY_SCOPE_VIOLATION` — `routes/referrals.py:31-35`
- §3.2 — insert — ambiguity — submission's unnamed errors pinned (`ERR_CLIENT_DELIVERY_BANNED` for non-`ACTIVE`, `ERR_CLIENT_BED_BUG_BLOCK` for a false attestation) plus the exact check order — `routes/referrals.py:87-108`
- §3.2 — insert — ambiguity — `APPROVE` never writes `review_note`; `RETURN`/`DENY` without a note write null — `routes/referrals.py:155-166`
- §3.2 — insert — ambiguity — the expiry refund never takes `quota_used` below 0 — `services/cycle.py:165`
- §3.3 — insert — ambiguity — the cancellation `reason` accepts any string and is stored nowhere — `routes/vouchers.py:203`
- §3.3 — insert — ambiguity — expiry and cancellation leave the money fields, `fee_basis` and `fill_ratio` standing — `services/allocation.py:154-181`
- §3.4 — insert — ambiguity — triage bumps every walked piece's version, accepted and refused alike — `services/calc.py:268`
- §3.5 — revise — **mismatch** — the inspections-coverage `ERR_VALIDATION` is evaluated *after* the state gate (exception to rule 3); duplicate `item_id`s also fail — `routes/donations.py:167-177`
- §3.5 — insert — ambiguity — units are minted in the accepted pieces' `created_at` order (which drives the allocation tie-break) — `services/donations.py:68,74`
- §3.5 — insert — ambiguity — a `D` grade still writes `graded_condition`, bumps the piece's version, and the intake recomputes `accepted_item_count`/`rejected_item_count` while leaving the triage numbers alone — `services/donations.py:76-84,107`
- §3.5 — insert — ambiguity — "accepted piece" on both branches means accepted at triage, so a piece this inspection grades `D` still triggers the risk branch — `services/donations.py:68,71`
- §3.5 — insert — ambiguity — a `QUARANTINED` unit sits at version 1 with null `available_since`; a `DISPOSED` unit never gets one — `services/donations.py:88-105`
- §3.5 — insert — ambiguity — the contagion cascade fires last, after grading, minting and the offer's own move — `services/donations.py:110-120`
- §3.5 — revise — **mismatch** — quarantine-release gates run SoD -> state -> dwell, not the narrative order; SoD is skipped while `inspector_user_id` is null — `routes/donations.py:189-201`
- §3.6 — insert — ambiguity — a top-up recomputes `priority_score` with the waitlist variant against the original `waiting_since`, and the entry's version moves only on an actual change — `services/allocation.py:24-33`
- §3.6 — insert — ambiguity — `generated_at` is the logical clock, not wall time — `services/report.py:337`
- §3.6 — insert — ambiguity — the report is an object endpoint: no pagination meta, `limit`/`offset` neither honoured nor validated — `routes/waitlist.py:36-41`
- §3.7 — insert — ambiguity — a duplicate truck `label` is `ERR_VALIDATION` — `routes/directory.py:62-64`
- §3.7 — insert — ambiguity — crew invitation has a run state gate (`PLANNED`/`CREWED`, else `ERR_RUN_INVALID_STATE`) ahead of the three guards — `routes/runs.py:186-188`
- §3.7 — insert — ambiguity — confirming against a non-`PLANNED` run is `ERR_RUN_INVALID_STATE` — `routes/runs.py:245-247`
- §3.7 — insert — ambiguity — declining never recomputes or touches the run — `routes/runs.py:254-256`
- §3.7 — insert — ambiguity — withdrawing outside `PLANNED`/`CREWED` is `ERR_RUN_INVALID_STATE` — `routes/runs.py:258-260`
- §3.7 — insert — ambiguity — the run's state gate is read before the voucher's on a stop booking — `routes/runs.py:111-116`
- §3.7 — insert — ambiguity — dispatch refreshes the derived numbers without a version bump, so a refused dispatch leaves no trace — `routes/runs.py:283`
- §3.8 — insert — ambiguity — `pest_observed_at_residence` is recorded on all three outcomes; the pinned effect order inside a failed outcome (chargeback -> stock -> voucher -> no-show chain -> stop -> pest -> standing -> run) — `services/delivery.py:199-250`
- §3.8 — insert — ambiguity — the referral moves to `FULFILLED` only if still `APPROVED` — `services/delivery.py:220-222`
- §3.8 — revise — **mismatch** — step two fires at a strike count of 2 *or more*, so every later no-show re-stamps the ban and re-runs step three — `services/delivery.py:173`
- §3.8 — insert — ambiguity — the residence cascade leaves strikes/ban alone, does not auto-deny referrals, and never fires on a `NO_SHOW` — `services/delivery.py:184-193,241`
- §3.9 — revise — **mismatch** — the provisional variant does not run on a zero-yield round that leaves the voucher `ISSUED` — `services/allocation.py:126-129`
- §3.9 — insert — ambiguity — `amount_cents` is required in fact for `RECORD_PAYMENT` (`ERR_VALIDATION` at rule-3 time, ahead of the path lookup) and ignored on the other three actions — `routes/vouchers.py:159-164`
- §3.9 — insert — ambiguity — waiving leaves `gross_fee_cents`, `fee_basis` and `amount_paid_cents` untouched — `routes/vouchers.py:184-187`
- §3.9 — insert — ambiguity — writing off leaves `amount_paid_cents` untouched — `routes/vouchers.py:193-195`
- §4 — insert — ambiguity — which single entity each multi-entity operation returns (stop for booking/outcome, assignment for invite/respond, voucher for issuance-without-lines/allocate/cancel/fee-settlement, offer for the four donation actions, run for dispatch, referral for submit/review) — `routes/*.py`

## Notes
- The generator's self-reported judgment calls were a subset; the ones it did not flag that I found independently include the once-per-request `version` dedupe (`db.py:72-87`), `restanding_count` counting *all* agencies, the intake coverage check's precedence inversion, "accepted piece" being read pre-grading on the risk branch, the `>=2` strike threshold, the unscoped list/nested-collection reads, and `ERR_CLIENT_DELIVERY_BANNED` on referral submission.
- All 48 impl routes and their role lists match the §4 table exactly; the 46-entry error catalogue matches `errors.py` exactly. No entity carries a field the PRD does not name, and no PRD-named field is unemitted — so no changes were needed there.
- Tests were consulted only as cross-reference (e.g. confirming no test covers list scoping, which is why that ambiguity survived Step 7's clean sweep); the implementation was the sole alignment target.

**Orchestrator verification:** `PRD_COMPLETED.md` present, 445 lines (line count preserved — all edits in-paragraph as required), 103,060 bytes vs PRD.md's 91,607 bytes; 0 scaffold-token leakage.

---

# PIPELINE COMPLETE — 2026-08-17T05:39:29.130Z

All 9 steps done (Step 8 skipped by its documented skip condition). Final state: 96/96 tests passing across 8 concurrent stability rounds under `--isolation per-test-server`.
