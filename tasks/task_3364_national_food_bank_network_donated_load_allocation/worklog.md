# Worklog — task_3364_national_food_bank_network_donated_load_allocation

Scenario: National Food Bank Network Donated Load Allocation & Shares Bidding (Feeding America).

## Step 1: Create task directory — 2026-10-01T09:10:00.000Z

Task directory `tasks/task_3364_national_food_bank_network_donated_load_allocation/` was pre-allocated by the caller with `workspace/` inside; no new index computed and no other `task_*` directory created.

## Step 2: Generate scaffold — 2026-10-01T09:52:47.922Z

Done. All three scaffold artifacts are written and lint-clean.

## Files written

| File | Path | Lines |
|---|---|---|
| SCAFFOLD.yaml (§1.0–§1.7) | `/home/ubuntu/github/CodingPRD/tasks/task_3364_national_food_bank_network_donated_load_allocation/SCAFFOLD.yaml` | 1822 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, single key `scaffold_difficulty_design`) | `/home/ubuntu/github/CodingPRD/tasks/task_3364_national_food_bank_network_donated_load_allocation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1161 |
| SCAFFOLD_CORNER_DESIGN.yaml (§1.9, single key `scaffold_corner_design`) | `/home/ubuntu/github/CodingPRD/tasks/task_3364_national_food_bank_network_donated_load_allocation/SCAFFOLD_CORNER_DESIGN.yaml` | 1718 |

## Counts

- **Entities: 10** (flat topology, FK-linked; MemberFoodBank, DonorAgreement, DonatedLoad, LoadBid, ShareLedgerEntry, ProductRecall, RecallHold, MemberAudit, StoreDonationProgram, StorePickup)
- **State machines: 7 / 36 transitions** (DonatedLoad parallel `status × safety_status` with an AWARDED→BIDDING cycle; MemberFoodBank cyclic posture; LoadBid with compensation; ProductRecall OPEN→TRACING→RESOLVED→REOPENED cycle; MemberAudit; StoreDonationProgram; StorePickup)
- **Endpoints: 40** (at the cap)
- **Calculations: 7**, all with `variants` (share grant forward-looking vs settled, bid ranking selector, freight subsidy provisional vs final, meal equivalency rounding order, share-balance recompute, audit weighted score, recall hold selection)
- **Validations: 32** (ordered priorities 1–32)
- **Errors: 39** — deliberately above the §0.4 expert band (18–30) for boundary precision (per-endpoint state errors, window-invalid vs window-overlap, etc.); every id is triggerable and referenced
- **Roles: 3** (NetworkAdmin opaque, MemberFoodBank `entity_backed:MemberFoodBank`, NetworkAuditor opaque with a segregation-of-duties check); **concurrency_rules: 2** (OCC on DonatedLoad.version for bid create, MemberFoodBank.version for epoch grants)
- **Difficulty design (§1.8, queue A): 18 instances** — exactly 2 per rule × 9 rules
- **Corner design (§1.9, queue B): 38 instances** — 31 active with test recipes, 7 `excluded_because:` stubs pointing at named §1.8 instances; sections covered: entities, state_machines, calculations, validations, errors, rbac, cross_cutting_complexity_layers, consistency_model, endpoints
- 486 structured `setup_api_calls` across both design files, all replay-checked

## Verification

`scaffold_lint.py` verdict (verbatim):

```
  §1.5 endpoints declared:    40
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     31
  Calls scanned (§1.8+§1.9):  573

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes: the read surface was reshaped mid-generation (sub-resource and filtered-list reverse-reachability GETs) to satisfy lint check (f) while holding the endpoint count at exactly 40; all formula-derived assertion literals were computed by executing the §1.3 formulas as code (e.g. freight 103230/113220/250000/64500, grants 71429/28571, meals 1249 vs 1250, audit 85.0/84.6/85.8); forbidden concurrency vocabulary is absent; neither design key appears inside SCAFFOLD.yaml. No sibling task directory was listed, globbed, or read.

### Orchestrator on-disk verification (independent of hand-back)

- `wc -l`: 1822 / 1161 / 1718 — matches the report.
- Top-level keys of SCAFFOLD.yaml: scenario, domain_name, api_prefix, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, response_envelope, endpoints, errors, roles. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` present (grep count 0).
- Design files each carry exactly their single required top-level key.
- `grep -cE '^  - method: '` → **40** endpoints (at the cap; impl-gen overshoot risk noted for Step 6).
- Entities in §1.1 → **10**; §1.8 instances → **18**; §1.9 instances → **38** (31 active + 7 stubs); ERR ids → **39**.

## Step 3: Copy shared INSTRUCTION.md — 2026-10-01T09:53:05.531Z

Copied `./INSTRUCTION.md` (1424 bytes) to `tasks/task_3364_national_food_bank_network_donated_load_allocation/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-01T10:20:00.000Z

**Note on provenance.** The Step 4 subagent was launched at ~09:54 and the host session was killed mid-flight before its final report was recorded. Per the "a lost subagent report ≠ a lost artifact" rule, the orchestrator did NOT blindly re-run the step; it verified the emitted artifact against SCAFFOLD.yaml instead. `workspace/PRD.md` (75,690 bytes, mtime 2026-10-01 10:09:16 UTC) is structurally complete and internally consistent — Step 4 is therefore treated as DONE, and the subagent's verbatim self-audit report is unavailable.

### Orchestrator on-disk verification (substitute for the lost report)

- `wc -lw` → **409 lines / 11,337 words**.
- Section headings present: `1. Introduction`; `2. Global Specifications & System-Wide Principles` with `2.1`–`2.12` (RBAC, Response Structure, Pagination, Common Resource Properties, Share Currency Ledger, Precision & Arithmetic, OCC, Cascading Effects & Posture Gating, Validation Order & Failure Precedence, Nested Retrieval & Reverse Reachability, Product Safety Containment, Logical Clock & Temporal Windows); `3. Business Logic & Workflows` with `3.1`–`3.9`; `4. Endpoint Definitions`; `5. Error Code Catalogue`.
- Endpoint table: **40 rows**, matching the scaffold's **40** endpoints exactly. Path-set diff (`comm`) is **empty in both directions** — 39 unique scaffold paths vs 39 unique PRD paths (the pickups path is shared by a POST and a GET). Both initially-suspected gaps (`/_clock/set_current_utc`, `/network/store-programs/{id}/pickups`) were confirmed present in the PRD table (lines 363 and 357–358); the first extraction pass had a faulty regex, not the PRD.
- Error catalogue: **39/39** scaffold `ERR_*` ids present in PRD prose/catalogue; no PRD-only error ids. (The single scaffold-only token `ERR_XXX` is the skill's template placeholder, not a real error.)
- State-name coverage: all of `PENDING_CERTIFICATION CERTIFIED PROBATION SUSPENDED BIDDING AWARDED CANCELLED DISPATCHED DELIVERED OPEN TRACING RESOLVED REOPENED SCHEDULED COMPLETED FAILED ACTIVE INACTIVE PENDING` appear in PRD prose.
- File ends cleanly on the final error-catalogue row (`ERR_SUBSIDY_POOL_EXHAUSTED`) — no truncation.
- Logical clock: PRD §2.12 pins the startup default to `2026-09-01T00:00:00Z` and states the no-wall-clock-fallback rule; §3.9 pins the 24-hour pickup spacing rule and the 48-hour completion tolerance; §3.7 pins the 1.2 meal factor. These are the constants Step 5 fixtures must respect.
- Both design indices (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were withheld from this step per the doc-generator contract.

## Step 5: Generate unit tests — 2026-10-01T10:50:00.000Z

Test generation is complete and verified. Final report:

## Files written (3,685 lines total)

**`test_helpers/`** (1,454 lines)
| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3364_national_food_bank_network_donated_load_allocation/test_helpers/__init__.py` | 30 |
| `.../test_helpers/types.py` | 317 |
| `.../test_helpers/api_client.py` | 148 (40 endpoint methods, one per PRD §4 row) |
| `.../test_helpers/api_errors.py` | 95 (39 error ids + status map registered with the framework) |
| `.../test_helpers/assertions.py` | 182 |
| `.../test_helpers/factories.py` | 138 |
| `.../test_helpers/constants.py` | 55 |
| `.../test_helpers/test_users.py` | 40 (entity-backed `make_member_headers(member_id)` + opaque admin/auditor builders) |
| `.../test_helpers/fixtures.py` | 449 |

**`test_suite/`** (2,231 lines): `conftest.py` 32; `test_01_member_certification.py` 228; `test_02_share_ledger_and_grants.py` 272; `test_03_load_lifecycle_and_bidding.py` 451; `test_04_award_and_freight.py` 315; `test_05_recall_and_safety.py` 392; `test_06_retail_pickups.py` 187; `test_07_donor_reporting.py` 181; `test_08_dispatch_and_delivery.py` 173.

## Test counts
- **Queue A (Difficulty): 35 tests** — 17 of 18 instances covered with ≥2 each (one instance has 3).
- **Queue B (Corner): 34 tests** — 31 of 31 non-stub instances covered.
- **69 tests total**, all collected cleanly (`pytest --collect-only`); zero pyflakes undefined names; zero `skip`/`skipif`/`xfail`; zero "scaffold"/table/§1.x references.

## Skipped instances
- **Queue A — `transitive_cascade/award_cascade_share_floor_to_probation_to_bid_withdrawal`: SKIPPED (PRD does not uniquely-derive).** The recipe awards a 99,980-share bid to a member whose `share_balance` is 10 at award time. PRD §3.5 makes award eligibility require "that member's `share_balance` is at least the bid's `shares_offered`", and §2.5 defines the stored `share_balance` as the gross ledger sum (already reduced by the bid's own `BID_HOLD`). Under that literal reading the bid is not a candidate (`ERR_NO_ELIGIBLE_BIDS`), so the asserted post-award balance of 20 and the hop-4 withdrawal are unreachable; under the alternative (add-back-the-hold) reading they are. Two faithful PRD-only implementers diverge, so the instance is not translated. No test asserts its numbers.
- **Queue B stubs: 7** `excluded_because:` instances — all cross-references verified to resolve to real §1.8 instance names; none translated, no placeholders emitted.
- Queue A instances whose design literals contradicted PRD-derived values were translated with the PRD-derived value (not skipped): the two-member-epoch M1 balance is 71,429/71,029 (not the design's 100,000), and the failing COMPREHENSIVE audit is 82.8 (not the design's 82.2). The `agreement_poundage_conserved_...` instance's "received poundage (sum of `weight_lbs` over non-CANCELLED loads)" assertion was dropped as PRD-silent; its four derivable assertions are covered by 2 tests.

## Numeric constants asserted, with the PRD sentence that values them
- 100,000 pool; 120 shares/1,000 population; 15 shares/10k lbs; 50-share probation floor; 100-share reinstatement floor — §2.5/§3.2 ("a fixed epoch pool of 100,000 shares"; "divided by one thousand, rounded down to a whole number of thousands, multiplied by 120 shares"; "multiplied by 15 shares"; "falls below 50 shares is moved down to `PROBATION`").
- 85 pass mark and 1-decimal round-half-up; COMPREHENSIVE 40/30/30, STORAGE 60/20/20 — §3.1/§3.1.1.
- 185 cents/mile; 30/55/75/100 %; ≥400 miles + 15 % uplift; 250,000-cent cap; 5,000-cent minimum — §3.6.
- 1.2 meal factor; ACTIVITY_BONUS 15 shares per full 10,000 lbs — §3.3/§3.7.
- 500-lb hold floor — §3.8; 24-hour pickup spacing and 3-consecutive-miss suspension — §3.9.
- All other asserted numbers (71,429/28,571 grants, 1,249 vs 1,250 meals, 114,700/113,220/12,580/250,000/64,500/66,600, 99,600/99,660/71,029, 33,333, 84.0/85.8/82.8/96.0, 1,300/1,400 lbs) are computed from those PRD-stated constants with fixture-chosen inputs, using the `expected_freight_subsidy`/`expected_freight_estimate`/`expected_activity_bonus` helpers that encode the PRD formulas.

## Confirmations
- **No test asserts a design-index-only literal** — verified by literal-by-literal sweep of every number in `test_suite/`; the only design-index-specific values (103,230 / the design's 100,000 and 82.2 / the provisional-vs-final framing) are either absent or replaced by PRD-derived values.
- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<instance.name>` or `Design: Corner/<section>/<instance.name>` line copied verbatim; an AST audit confirmed 69/69 tags resolve to real instances and no tag points to a stub.
- Every PRD citation passed a literal normalized-`grep` check against `workspace/PRD.md` (0 non-verbatim quotes); no citation is endpoint-titular.
- Logical-clock discipline: all fixture dates are ≥ `2026-09-01T00:00:00Z`; tests needing a later "now" set it via `POST /_clock/set_current_utc` (00:05/00:10 for the tie-break test).
- Identity discipline: every ownership-gated call uses `make_member_headers(member["id"])`; create endpoints are validated with an explicit `201` where asserted directly.

### Orchestrator on-disk verification (independent of hand-back)

- `wc -l` on `test_helpers/*.py` + `test_suite/*.py` → **3,685** total, matching the report file-by-file.
- `grep -c 'def test_'` → **69**; `grep -c 'Design: (Difficulty|Corner)/'` → **69** (1:1, no untagged or dual-tagged tests).
- `grep -rnE 'skip|xfail'` over both dirs → **0** hits.
- `python3 -m pytest test_suite/ --collect-only -q` → **69 tests collected in 0.21s**, no import/collection errors.

## Step 6: Generate implementation — 2026-10-01T11:14:39.975Z

Implementation complete and verified.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3364_national_food_bank_network_donated_load_allocation/workspace/implementation/`)

| Lines | File |
|---|---|
| 9 | `start.sh` (exec, guarded dep install) |
| 1 | `requirements.txt` (Flask) |
| 52 | `app.py` |
| 144 | `auth.py` |
| 84 | `clock.py` |
| 64 | `envelope.py` |
| 108 | `errors.py` |
| 93 | `store.py` |
| 122 | `serializers.py` |
| 302 | `routes/loads.py` |
| 198 | `routes/programs.py` |
| 172 | `routes/members.py` |
| 129 | `routes/recalls.py` |
| 128 | `routes/agreements.py` |
| 98 | `routes/audits.py` |
| 60 | `routes/misc.py` |
| 54 | `routes/bids.py` |
| 1 | `routes/__init__.py` |
| 230 | `services/loads.py` |
| 112 | `services/recalls.py` |
| 78 | `services/grants.py` |
| 57 | `services/audit.py` |
| 56 | `services/freight.py` |
| 53 | `services/ledger.py` |
| 52 | `services/members.py` |
| 47 | `services/programs.py` |
| 1 | `services/__init__.py` |

2505 lines total. No seeding, no wall-clock (`datetime.now`/`utcnow`/`time.time` absent), no persistence (no sqlite/pickle/open-for-write) — verified by grep; every `store.insert` is inside a request handler.

## Routes: 40 registered

Verified by introspecting the live Flask url_map and diffing against SCAFFOLD §1.5 after normalizing Flask `<param>` vs scaffold `{param}`: `REGISTERED 40 / DECLARED 40 / MISSING [] / EXTRA [] / EXACT_MATCH True`.

## Smoke test of a fresh boot

```
cd .../workspace/implementation && PORT=18741 bash start.sh
```
Observed: ready in **0.61 s**, log shows `Running on all addresses (0.0.0.0)` / `http://127.0.0.1:18741`, `ss` confirms `LISTEN 0.0.0.0:18741`. First response:
```json
{"data":[],"meta":{"api_request_id":"req_X0I2KBF0O83AQ9PB25","api_request_timestamp":"2026-09-01T00:00:00.000Z","has_more":false,"limit":10,"offset":0,"total_count":0},"response_type":"array"}
```
Empty store and pinned clock on a cold process. I also rebooted a second time and confirmed zero carry-over (no member survived). Four suites (~110 assertions) covering the award/probation cascade, freight decline unwind, freight COVERED math, dispatch windows, recall trace/resolve/reopen, audit→probation→suspension, miss cascade, PREFERENCE_FIRST / FORWARD_LOOKING / SUM_THEN_DIVIDE variants, pagination, and every error precedence I could reach all end at `FAILURES: 0`. Only PIDs I started were killed; all my ports are free.

## PRD rules I found ambiguous, and the interpretation chosen

1. **Award eligibility `share_balance >= shares_offered`.** Since the bid's `BID_HOLD` already reduced `share_balance`, the literal filter requires a member to hold ≥2× its bid to be awardable. I kept the literal reading because it is the scaffold's exact formula, it matches "a member whose share balance has fallen away since it bid is not awardable", and it is the only reading that preserves the declared `share_balance >= 0` invariant. The consequence is that the winner-demotion cascade needs a bid at most half the balance.
2. **`ERR_LOAD_RECALLED` vs `ERR_LOAD_SAFETY_HOLD` on dispatch.** §2.9 rank 20 shadows rank 21, but §2.11 partitions them explicitly. I followed §2.11: RECALLED → `ERR_LOAD_RECALLED`, HELD → `ERR_LOAD_SAFETY_HOLD`. (Note the load-state check at rank 14 always fires first, so `ERR_LOAD_RECALLED` is unreachable in practice for dispatch/deliver.)
3. **Bid-creation precedence.** §3.4 lists six gates in one order but says the order is "set out in §2.9"; I used the §2.9 ranks (duplicate → storage → posture → shares).
4. **`ERR_SUBSIDY_POOL_EXHAUSTED` trigger.** Implemented as: request `decision=COVERED` + member cannot self-transport + pool_remaining < 5000 → 409, checked before any mutation. If a COVERED computation collapses below the minimum, the recorded decision becomes DECLINED and the award unwinds (§3.6 "the decision the network records follows from the computed subsidy").
5. **Errors with no catalogue entry.** Certify without a passed COMPREHENSIVE audit, reinstate below `audit_score` 85 / 100 shares, duplicate member name per state, and pickup completion outside its window have no declared `error_id`; I used `ERR_INVALID_REQUEST` (400) for the first three and `ERR_PICKUP_WINDOW_INVALID` (400) for the last.
6. **`GET /network/members/{id}` roles.** The §4 table omits `NetworkAuditor`, but §2.1 prose and the scaffold RBAC matrix both grant the member read; I allowed all three roles.
7. **Admin-initiated bid withdrawal** records `rejection_reason = WITHDRAWN_BY_MEMBER` (no other constant exists).
8. **Spec deadlock worth flagging:** `SUSPENDED → PROBATION` reinstatement requires `audit_score >= 85`, but audits cannot be opened for a SUSPENDED member and suspension is only ever entered via a failing audit — so that transition is unreachable. I implemented both preconditions literally rather than loosening either.

### Orchestrator on-disk verification (independent of hand-back)

- All 27 source files present; `start.sh` mode `-rwxrwxr-x`; 2,495 Python lines (report said 2,505 including `requirements.txt` + `start.sh`).
- Forbidden-pattern grep (`datetime.now|utcnow|time.time(|sqlite|pickle|.dump(|open(...,'w')`) over all `*.py` → **0 hits**: no wall-clock fallback, no disk persistence, no seeding.
- Independent route count via live `app.url_map` introspection → **40** registered vs **40** declared in SCAFFOLD. Matches.
- Boot smoke test (own exact-PID server, dynamically allocated free port — an earlier attempt on fixed port 18991 collided with another pipeline on this shared host, so all later runs allocate a verified-free port): server binds `0.0.0.0`, `GET`/`POST` round-trip `POST /network/members` → **201** with `certification_status: PENDING_CERTIFICATION`, `share_balance: 0`; `GET /network/members/{id}` → **200** echoing the name. `POST /_clock/set_current_utc` → **200** and the response `api_request_timestamp` advanced to `2026-09-05T12:00:00.000Z`, confirming the logical clock drives the envelope and no wall-clock fallback occurs.
- An initial smoke attempt passed `transport_ability: true` and was correctly rejected **400 `ERR_INVALID_REQUEST`** ("must be a non-empty string") — SCAFFOLD declares the field as enum `NONE|LOCAL|REGIONAL|NATIONAL`, so this is input validation working as designed, not an implementation defect.
- Server stopped cleanly by exact PID each time; no broad kill patterns used.

## Step 7: Run tests and iterate — 2026-10-01T11:26:30.000Z

All 8 rounds pass 69/69. Work is complete.

## Summary

**Iterations run:** 2 (initial sweep → fixes → re-sweep)

**Initial sweep result:** 2 failures, deterministic (identical in all 8 rounds, so not flakiness):
- `test_third_consecutive_miss_suspends_program` — `assert 'ACTIVE' == 'SUSPENDED'`
- `test_touching_delivery_window_accepted` — `assert '2026-09-10T12:00:00.000Z' == '2026-09-10T12:00:00Z'`

**Final sweep result:** 8/8 rounds, 69/69 passed. Evidence left in place at `/home/ubuntu/github/CodingPRD/tasks/task_3364_national_food_bank_network_donated_load_allocation/workspace/implementation/results.{1..8}.json`.

**Tests deleted:** none. 69 tests, 69 Design tags, zero skip/xfail.

### Fixes applied to `test_suite/`
- `/home/ubuntu/github/CodingPRD/tasks/task_3364_national_food_bank_network_donated_load_allocation/test_suite/test_08_dispatch_and_delivery.py` — `test_touching_delivery_window_accepted`, line 103. The assertion required the dispatch response to echo `delivery_window_start` byte-for-byte as sent (`...T12:00:00Z`). PRD §2.4 pins the three-fractional-digit rendering only for `created_at`/`updated_at`; it never states the string form of a delivery window, and §2.12 itself writes the clock default as `2026-09-01T00:00:00Z`. An implementer that normalizes every emitted timestamp to the §2.4 canonical form (`...T12:00:00.000Z`) is equally PRD-faithful, so string equality is not uniquely derivable. Replaced with exact **instant** equality (plus an ISO-8601 validity check) — same value, same strictness, no format claim the PRD does not make. The PRD-covered half of the test (touching half-open windows are legal → `status == "IN_TRANSIT"`) is untouched. Not an implementation change: the implementation is free to keep normalizing.

### Fixes applied to `implementation/`
- `/home/ubuntu/github/CodingPRD/tasks/task_3364_national_food_bank_network_donated_load_allocation/workspace/implementation/services/programs.py` — `consecutive_missed()`. It computed the *trailing* run of MISSED rows over the full `scheduled_date`-ascending list, so a still-`SCHEDULED` pickup on a later date reset the count to 0 and the program never suspended. PRD §3.9 says the count is "the run of `MISSED` pickups that ends at the most recent one" — a run of MISSED pickups can only *end* at a MISSED pickup, and the very next clause ("every one of the program's remaining `SCHEDULED` pickups is marked `MISSED` as well") presupposes remaining SCHEDULED pickups exist at the moment of suspension, which the old reading made unreachable. Now counts the consecutive MISSED run ending at the most recently missed pickup; later SCHEDULED rows sit after the run and are swept to MISSED when the threshold trips.

Direct unit check of the corrected function: `M,M,M,S → 3`, `M,M,S → 2`, `M,S,M → 1`, `C,M,M → 2`, `S → 0` — i.e. a SCHEDULED or COMPLETED pickup *inside* the run still breaks consecutiveness, while a SCHEDULED pickup *after* the run does not. `test_two_misses_leave_program_active` and `test_failed_audit_marks_scheduled_pickup_missed` (a separate posture-cascade path) still pass.

**Note:** no `test_helpers/` changes were needed — the pickup and dispatch fixtures already act as the member itself via `make_member_headers(member["id"])` and construct PRD-consistent preconditions.

### Orchestrator on-disk verification (independent of hand-back)

- All **8** `results.{1..8}.json` present in `workspace/implementation/` (the Step 7 subagent was explicitly told not to clean them up, and did not).
- Per-round parse: **rounds 1–8 all `passed=69 total=69 failed=0`**.
- Both edits spot-checked against source: `services/programs.py::consecutive_missed` implements the "run ending at the most recent MISSED pickup" reading as described; `test_08_dispatch_and_delivery.py:116-117` asserts `is_iso8601_timestamp(...)` plus `_instant(...) == _instant("2026-09-10T12:00:00Z")` — instant equality, as described.
- Post-sweep write check: no `*.py` under `workspace/implementation/` has an mtime newer than the sweep, so the green sweep reflects the current code. (Newest source mtime is the Step 7 `services/programs.py` fix itself.)

### Hand-off note for Step 8

Step 7 produced **1 test_suite fix + 1 implementation fix, 0 deletions, 0 test_helpers fixes** → the Step 8 skip condition is NOT met, so Step 8 runs. Two PRD silences are known and in scope:
1. The string form of emitted window timestamps (`delivery_window_start` / `delivery_window_end`) — PRD §2.4 pins fractional-digit rendering only for `created_at`/`updated_at`. Step 8 should pin what the implementation actually emits.
2. The `consecutive_missed` definition — PRD §3.9's "run of MISSED pickups that ends at the most recent one" was read two ways; the implementation's reading (SCHEDULED rows after the run do not reset it) should be pinned.

Sibling paths worth naming for Step 9 (unasserted by any test, so Step 7 never exercised them): `ERR_LOAD_RECALLED` is unreachable on dispatch/deliver because the load-state check fires first (Step 6 note 2); the `SUSPENDED → PROBATION` reinstatement precondition is unreachable by construction (Step 6 note 8); and the four error paths Step 6 note 5 assigned `ERR_INVALID_REQUEST` to have no catalogue entry.

## Step 8: Finalize PRD — 2026-10-01T11:35:35.810Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_3364_national_food_bank_network_donated_load_allocation/workspace/PRD_FINALIZED.md`.

## Size

- PRD.md: 409 lines → PRD_FINALIZED.md: 411 lines (**+2 lines, +0.49%**); 2 changed hunks, no sections added or removed.

## Changes (one bullet per edit)

- **§2.4 — insert** — new paragraph after the append-only-resources paragraph: "The canonical rendering is not limited to `created_at` and `updated_at`. Every other timestamp the API emits for a resource is normalized the same way — UTC, exactly three fractional digits, trailing `Z` — however the client supplied it: a load's `delivery_window_start` and `delivery_window_end`, a pickup's `scheduled_date`, `window_start` and `window_end`, and a recall's `opened_at`. A delivery window endpoint sent as `2026-09-10T12:00:00Z`, for instance, is echoed back as `2026-09-10T12:00:00.000Z`." — traces to the Step 7 test relaxation in `test_touching_delivery_window_accepted` (PRD never pinned the string form of a delivery window; impl normalizes). Impl: `workspace/implementation/serializers.py:9-15` (`_value`/`_shape`), `workspace/implementation/clock.py:44-52` (`fmt`), consumed by dispatch at `workspace/implementation/routes/loads.py:186-187,226` + `workspace/implementation/services/loads.py:206-212`.
- **§3.9 — revise** — "counting the run of `MISSED` pickups that ends at the most recent one" → "counting the run of consecutive `MISSED` pickups that ends at the last `MISSED` pickup in that order — a pickup that is still `SCHEDULED` for a later date sits after that run and does not reset the count" — traces to the Step 7 impl fix in `consecutive_missed()`. Impl: `workspace/implementation/services/programs.py:23-45`.

Everything else is byte-identical to PRD.md; all PRD-determined prose kept verbatim.

## Per-edit pre-edit search log

**Edit 1 (§2.4, timestamp rendering)**
- (a) Subject: the string rendering of timestamps the API emits in response bodies for resource fields other than `created_at`/`updated_at` (delivery/pickup windows, `scheduled_date`, `opened_at`).
- (b) Paths enumerated and read/grepped: `serializers.py` `_value` + `_shape` and all ten resource field tuples (`LOAD_FIELDS`, `PICKUP_FIELDS`, `RECALL_FIELDS`, ledger/hold append-only shapers); `clock.py` `parse_iso`/`fmt`/`now_iso`; `envelope.py` `_meta`; `routes/loads.py` dispatch → `services/loads.py::dispatch_load`; `routes/programs.py::schedule_pickup`; `routes/recalls.py` recall creation (`opened_at=clock.now()`); whole-tree grep for `isoformat|strftime|%03d|Z"` confirmed `clock.fmt` is the only timestamp formatter, so no path emits a differently-shaped timestamp. Empirically confirmed output: `...T12:00:00Z` → `...T12:00:00.000Z`, `+02:00` offsets and 6-digit fractions normalized, bare date → `...T00:00:00.000Z`; `serializers.load/pickup/recall` all emit that form.
- (c) Wording adjustment: scoped the claim to "every other timestamp the API emits **for a resource**" (deliberately not touching the envelope `meta.api_request_timestamp`, already pinned by §2.2) and enumerated the exact serializer-formatted fields instead of a bare universal claim, so no unenumerated path can be mis-described.

**Edit 2 (§3.9, consecutive-missed count)**
- (a) Subject: recomputation of the program's consecutive-missed count when a `SCHEDULED` pickup is marked missed (which pickup the counted run ends at, and whether later `SCHEDULED` rows reset it).
- (b) Paths enumerated and read/grepped: `services/programs.py` `consecutive_missed`, `mark_missed`, `pickups_of` (ordering key `scheduled_date, created_at, _seq`); `services/members.py` `suspend_active_programs` (marks future `SCHEDULED` pickups `MISSED` directly, no count recomputation) and `activate_pending_programs`; `routes/programs.py` `miss_pickup` (the only caller of `mark_missed`), `schedule_pickup`, `create_program`; `routes/members.py` `reinstate_member`. Behavior verified empirically against the current code: `M,M,M,S→3`, `M,M,S→2`, `M,S,M→1`, `C,M,M→2`, `S→0`, `M,S,M,M→2`, `C,M,M,S,S→2`.
- (c) Wording adjustment: wrote the run as "consecutive `MISSED` pickups that ends at the **last `MISSED` pickup in that order**" and scoped the new clause to pickups "still `SCHEDULED` **for a later date**", so it does not falsely claim that an inner `SCHEDULED` pickup is ignored (the impl breaks the run there: `M,S,M→1`). Left the §3.1.2 member-posture suspension cascade untouched because that path sweeps pickups to `MISSED` without recomputing the count, so the added clause stays true on both paths.

Note: the two Step 7 items are covered as (1) a genuine PRD silence the impl pins (window/timestamp rendering) and (2) a PRD ambiguity the impl pins (referent of "the most recent one"); no other PRD text was changed, and no test-derived claim beyond what `implementation/` exhibits was added.

### Orchestrator on-disk verification (independent of hand-back)

- `wc -l` → PRD.md **409** / PRD_FINALIZED.md **411** (+2 lines, +0.49%), matching the report.
- `diff PRD.md PRD_FINALIZED.md` → exactly **2 hunks**: `88a89,90` (a 2-line insert) and `316c318` (one revised sentence). No section added, removed, or reordered; no truncation.
- The inserted §2.4 claim matches the implementation: `implementation/clock.py::fmt` renders `"%04d-%02d-%02dT%02d:%02d:%02d.%03dZ"` — UTC, exactly three fractional digits, trailing `Z` — which is precisely the canonical form the new paragraph pins.
- The revised §3.9 sentence matches `services/programs.py::consecutive_missed` as verified in Step 7's spot-check.

## Step 9: Complete PRD — 2026-10-01T11:58:00.000Z

`PRD_COMPLETED.md` is written and verified. Summary follows.

**Source / output**
- Source: `PRD_FINALIZED.md` (411 lines, 76,338 chars) → `PRD_COMPLETED.md` (411 lines, 86,117 chars; **+9,779 chars, +12.8%**, same line count — every edit is an inline insert/revision, no new sections).
- **43 changes: 34 ambiguity-pins, 9 mismatch-revisions.** Every behavioral claim was checked against the source and most were re-verified by booting the implementation on a private port (PID-controlled, since killed) and driving ~60 live requests.

**Mismatch-revisions (PRD described something else)**
- §2.5 — revise — mismatch — entry types are "positive amount" but zero-value `GRANT`/`ACTIVITY_BONUS` rows are still appended — services/ledger.py:40, services/loads.py:225, routes/misc.py:47
- §2.9 r4 — revise — mismatch — ownership/segregation need the path resource loaded first, so unknown ids give 404 not 403 — routes/bids.py:44, routes/audits.py:71, routes/programs.py:99
- §2.9 r20 — revise — mismatch — "HELD **or RECALLED** rejected here" is wrong; RECALLED is evaluated first at r21 — routes/loads.py:192-195
- §2.9 r27 — revise — mismatch — score band is applied with rank-2 body validation, before member existence — routes/audits.py:26,41
- §3.3 — revise — mismatch — activation moves **any** non-ACTIVE status incl. `CLOSED`; already-ACTIVE is a no-op — routes/agreements.py:69
- §3.6 — revise — mismatch — an explicit `DECLINED` for a self-transporter is recorded as DECLINED, not "always COVERED" — services/loads.py:162
- §3.8 — revise — mismatch — version bumps only when `safety_status` actually moves to HELD — services/recalls.py:74
- §3.9 — revise — mismatch — completion accepted whenever `now <= window_end + 48h` (early completion is legal) — routes/programs.py:174
- §4 table — revise — mismatch — `GET /network/members/{id}` must list `NetworkAuditor` (impl + §2.1 prose) — routes/members.py:84

**Ambiguity-pins (PRD silent)**
- §2.3 — insert — negative `offset` rejected as malformed — auth.py:141
- §2.5 — insert — `share_balance` is the raw ledger sum (already hold-reduced); `available_for_bidding` is exposed nowhere — services/ledger.py:31, serializers.py:33
- §2.5 — insert — the <50 demotion fires only from the award cascade, not from every balance movement — services/loads.py:125
- §2.9 r2 — insert — award/trace bodies are optional (absent or unparseable JSON = no selectors); the four selector fields are not closed enums — routes/loads.py:143, routes/recalls.py:74, auth.py:108
- §2.9 r9 — insert — unknown hold read returns `ERR_RECALL_NOT_FOUND` — routes/recalls.py:126
- §2.9 r24 — insert — `ERR_MEMBER_NOT_CERTIFIED` also covers dispatch and non-ACTIVE-program scheduling — routes/loads.py:200, routes/programs.py:108
- §2.11 — insert — the RECALLED guard precedes the hold guard and is defensive (RECALLED ⇒ DELIVERED) — services/recalls.py:58
- §3.1 — insert — duplicate member name per state → `ERR_INVALID_REQUEST` 400 — routes/members.py:58
- §3.1 — insert — suspended member cannot be audited → `ERR_MEMBER_SUSPENDED` 403 — routes/audits.py:48
- §3.1.1 — insert — the 70/15/15 variant applies only to a `STORAGE` audit — services/audit.py:34
- §3.1.1 — insert — "12 months" = 365 days back from the logical clock, tested on `created_at` — services/audit.py:19
- §3.1.2 — insert — certify without a passed COMPREHENSIVE audit → `ERR_INVALID_REQUEST` 400 — routes/members.py:95
- §3.1.2 — insert — reinstatement floor failures → `ERR_INVALID_REQUEST` 400 — routes/members.py:122
- §3.1.2 — insert — reinstatement out of SUSPENDED is unreachable (failed audit leaves score <85; suspended members can't be audited) — routes/members.py:122 + routes/audits.py:48
- §3.2 — insert — zero grants still append a row; response is the ledger entry, 201 — routes/misc.py:45
- §3.2 — insert — FORWARD_LOOKING attributes an undelivered load to its award/dispatch epoch, full weight — services/grants.py:16
- §3.3 — insert — `freight_subsidy_pool_cents` may be zero, not negative — routes/agreements.py:38
- §3.4 — insert — the shares gate reads the pre-hold balance (unlike award eligibility) — routes/loads.py:297
- §3.4 — insert — §2.9 rank order governs over the narrative enumeration (dup → storage → posture → shares) — routes/loads.py:281-299
- §3.4 — insert — admin withdrawal writes `WITHDRAWN_BY_MEMBER`; unknown bid → 404 before ownership — routes/bids.py:41, services/loads.py:94
- §3.5 — insert — award eligibility compares against the hold-reduced `share_balance`, so a member that spent its whole balance bidding can never be a candidate — services/loads.py:45
- §3.5.1 — insert — the demotion test reads the same hold-reduced figure — services/loads.py:120
- §3.6 — insert — the 400-mile uplift threshold uses `distance_miles` only, ignoring `detour_miles` — services/freight.py:45
- §3.6 — insert — `member_freight_due_cents` is not clamped (can go negative) — services/freight.py:52
- §3.6 — insert — `ERR_SUBSIDY_POOL_EXHAUSTED` fires only for COVERED + non-self-transport, pre-mutation; a COVERED that collapses <5000 unwinds like DECLINED — services/loads.py:172
- §3.6 — insert — the unwind leaves `freight_estimate_cents` standing — services/loads.py:140
- §3.7 — insert — dispatch before the freight decision → `ERR_LOAD_NOT_AWARDED`; lapsed member posture → `ERR_MEMBER_NOT_CERTIFIED` — routes/loads.py:196
- §3.8 — insert — creation `scope` is remembered; a trace body may override it for that trace — routes/recalls.py:43,86
- §3.8 — insert — `CATEGORY` scope matches by category; `hold_reason` values `LOT_MATCH`/`CATEGORY_MATCH`/`DONOR_WIDE_TRACE` — services/recalls.py:10
- §3.8 — insert — the resolve guard carries `ERR_RECALL_NOT_TRACING` — routes/recalls.py:98
- §3.9 — insert — scheduling against a non-ACTIVE program → `ERR_MEMBER_NOT_CERTIFIED` 403 — routes/programs.py:108
- §3.9 — insert — overlap/spacing tests see only SCHEDULED pickups, and spacing is symmetric — routes/programs.py:122
- §3.9 — insert — out-of-window completion → `ERR_PICKUP_WINDOW_INVALID` 400 — routes/programs.py:174
- §3.9 — insert — a program suspended by the 3-miss rule while its member is CERTIFIED can never be revived — services/programs.py:54

**Dead-code check**
- Every validation helper in `implementation/` has a reachable callsite **except three**, all confirmed by AST + grep to appear only at their definition site: `auth.opt_enum` (auth.py:108), `clock.months_ago` (clock.py:83), `store.find` (store.py:92).
- `opt_enum` is the one that matters: it is the validator for the PRD's rank-2 sentence "every enumerated input must be a member of its declared enumeration", which is unenforced for `ranking_basis`, `scope`, `activity_basis` and `rounding_basis` — pinned in §2.9 r2. `months_ago`/`store.find` correspond to no PRD sentence.
- All route handlers flagged "no callsite" by AST are decorator-registered (`@bp.route` × 40, `@app.errorhandler` × 3) and are reachable.
- Two further checks are called but unreachable by construction (creation already enforces positive values): the storage-capacity recheck in `certify` (pinned in §3.1.2) and the `weight_lbs` recheck in `post_load` (left unpinned — it can never fire, so it changes no behavior).

### Orchestrator on-disk verification (independent of hand-back)

- `wc -lc` → PRD.md **409 / 75,690** · PRD_FINALIZED.md **411 / 76,338** · PRD_COMPLETED.md **411 / 86,117**. Line count unchanged from FINALIZED (+9,779 chars, +12.8%) — consistent with inline insert/revision only.
- Heading count preserved at **27** in both FINALIZED and COMPLETED — no section added or removed.
- File ends cleanly on the final error-catalogue row (`ERR_SUBSIDY_POOL_EXHAUSTED`) — no truncation. `diff` hunk count vs FINALIZED = 39.
- Spot-checked the dead-code finding in the shipped text: §2.9 rank 2 now reads "…are not closed enumerations: a value other than the one named in §3, including an unrecognized string, selects the default behavior instead of being rejected here" — i.e. the PRD was revised to describe what `implementation/` actually does (no enum enforcement on the four selector fields), which is the correct direction of alignment.

## Final verification — 2026-10-01T12:03:04.417Z

**Post-Step-7/8/9 write check (sweep-invalidation guard).** `find workspace/implementation -name '*.py' -newer results.1.json` → **empty**, and the same check over `test_suite/` + `test_helpers/` → **empty**. Steps 8 and 9 edited only `workspace/PRD_FINALIZED.md` and `workspace/PRD_COMPLETED.md`; no implementation or test source was touched after the green sweep, so the Step 7 evidence stood.

**Independent orchestrator re-sweep.** Rather than rely solely on the Step 7 subagent's evidence, the orchestrator deleted the eight result files and re-ran the full 8-round parallel sweep itself against the frozen artifacts:

```
for i in 1 2 3 4 5 6 7 8; do prd-bench-local-run --start-command "… && bash start.sh" \
  --test-dir …/test_suite --isolation per-test-server --timeout 120 --test-timeout 30 \
  --results-file …/results.${i}.json & done; wait
```

Result — **all 8 rounds `passed=69 total=69 failed=0`**. Fresh `results.{1..8}.json` (12:00–12:03 UTC) are in place as the required evidence.

**Pipeline status: COMPLETE.** Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (9 files, 69 tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (27 source files, 40 routes), `workspace/implementation/results.{1..8}.json`.
