# Worklog — task_2131_orchestra_symphony_season

## Step 1: Create task directory — 2026-08-22T02:12:10.297Z

Created `./tasks/task_2131_orchestra_symphony_season/` and `./tasks/task_2131_orchestra_symphony_season/workspace/`. Index 2131 = highest existing (2130) + 1.

## Step 3: Copy shared files — 2026-08-22T02:12:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2131_orchestra_symphony_season/workspace/INSTRUCTION.md` (1424 bytes). (Run early; independent of Step 2.)

## Step 2: Generate scaffold — 2026-08-22T02:57:34.185Z

All three scaffold artifacts are generated and lint-clean.

## Files written to `/home/ubuntu/github/CodingPRD/tasks/task_2131_orchestra_symphony_season/`

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 1735 | §1.0–§1.7 + preamble; no design keys |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1527 | single key `scaffold_difficulty_design` — 9 rules × 19 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3694 | single key `scaffold_corner_design` — 9 sections, 86 instances (69 with recipes, 17 `excluded_because` stubs) |

## Design shape

**Expert band, deliberately above it** (the scenario asked for "harder than expert"): 13 entities, 54 endpoints, 49 error codes, 10 calculations, 22 ordered validations, 8 state machines, 2 OCC concurrency rules, 7 peer roles. `api_prefix: /orchestra`, flat/graph topology (MusicianEngagement is a true M:N junction; `SubscriptionPackage.prior_package_id` is a self-referential FK forming renewal chains).

Profile: `quota_allocation` × `temporal_windowing`, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint; `state_machine_shape: parallel` (Concert carries three independent status axes), `role_model: peer_roles`.

How each §0.5 rule is satisfied (≥2 instances each, differentiation honored):
- **dual_variant** — musician pay provisional 28500 vs final 36500 (labour domain) / package NEW 31920 vs RENEWAL 25718 (revenue domain)
- **combinatorial** — three modes: (a) nested min/max clamps on dynamic ticket price, (b) pinned per-line rounding 14438 vs 14439, (c) pinned discount-then-placement-fee ad invoice 552000 vs 561600
- **non_linear_sm** — cyclic GuestArtistContract (OFFERED↔COUNTERED) / parallel Concert dimensions
- **transitive_cascade** — depth-4 cancel chain (concert→service→engagement→musician ledger) and depth-4 decline chain (engagement→complement→compliance→readiness→programming unlock), different triggers
- **priority_pair** — state vs business_fiscal / business_safety vs business_temporal
- **boundary** — 150 vs 151 worked minutes on `/clock` / zero-taken empty-inventory on `/price-quote`
- **cross_entity** — Contract→Concert / SubscriptionPackage→Season
- **temporal_overlap** — buffered pairwise half-open intervals on Venue / aggregate calendar-date cap on Musician
- **compensating_invariant** — seats conserved (hold→ops-expiry) / cash conserved (payment→refund credit)

## Verification

Every formula-derived assert literal was computed in Python before being written (prices 7650/8100/10350/10800, packages 4512/8460/12859/13680/14438/21600/25718/27360/31920, pay 20000/28500/28900/31000/36500, ad invoices 80000/132480/552000).

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     69
  Calls scanned (§1.8+§1.9):  971

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional self-checks run beyond the linter, all passing: zero unbound `${var}` across 971 calls and all assert lines; instance names unique across both design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance and carries no `test_recipe`; no forbidden concurrency vocabulary anywhere; all 49 error codes exercised by at least one design instance and referenced by at least one validation/transition/endpoint; every `grounds:` reference (calculations, entity fields, validation priorities, errors, concurrency rules, roles, endpoints, state-machine edges) resolves into `SCAFFOLD.yaml`.

Two `SCAFFOLD.yaml` edits were made during §1.9 authoring, per the §1.5 priority-ladder discipline: the season SINGLE_ON_SALE advance now recomputes `readiness_posture` (making `BLOCKED` reachable), and `AdvertisingSales` was added to the `/_clock/set_current_utc` roles. No sibling task directory was read.

## Step 4: Generate PRD — 2026-08-22T03:08:13.168Z

PRD generated at `workspace/PRD.md` (437 lines). Read only `SCAFFOLD.yaml`, the skill spec, `section-2.2-response-structure.md`, and the reference example — neither design index was opened.

**Structure** (domain-derived, not copied from the example): §1 three-paragraph introduction framed on the three conflicting "clocks"; §2 with 13 subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 pagination, then Resource Identity & Logical Clock, Money/Basis Points/Rounding, Request Validation Order, Three Status Dimensions, Hall Occupancy & Changeover, Seat Inventory Conservation, Patron Cash Identity, Musician Service-Credit Ledger, OCC, Ops-Run Epoch); §3 with 9 subsections organised as a season timeline; §4 endpoint table (4 columns); §5 error table (2 columns).

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields + section_inventory subfields: 127 required, 127 present, 0 missing
- endpoints[].input / request_body: all present, 0 missing
- endpoints[].path_params / query_params / computed outputs: all present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 22 checked, 22 expressed in prose with explicit ordering + applies_to scopes, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_concert_version / expected_package_version + error_id + 412), 0 missing
- state_machines[].transitions: 30 checked (Season 5, Concert 8, GuestArtistContract 6, RehearsalService 4, MusicianEngagement 3, SubscriptionPackage 3, TicketOrder 3, AdBooking 2 — 34 edges total), all from/to states, preconditions-with-error_id and side-effects expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed in operator-free prose with pinned evaluation order and all constants, 0 missing
- validations[] conditions: 22 checked, 22 matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: 54 endpoints checked, all side-effect sets expressed, 0 missing
- entities[].fields[] structured content: 13 entities checked, defaults / initial values / enum sets / constraints reconstructible, 0 missing
- sibling-branch symmetry: 5 groups checked (sign OFFERED vs COUNTERED; service DRAFT vs PUBLISHED cancel; ad APPROVE vs REJECT; package NEW vs RENEWAL pricing; pay PROVISIONAL vs FINAL), equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 711
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Two scaffold inconsistencies resolved, worth flagging:**

1. `calculations.concert_readiness_posture.trigger` lists "concert cancellation" among the recompute points, but the `Concert SCHEDULED → CANCELLED` transition's own side-effects end with `"programming_status and readiness_posture are NOT changed by cancellation"`. Followed the more specific transition statement and wrote it unambiguously (cancellation leaves both fields exactly as they stood). These two readings produce different values, so if the test suite asserts a recompute-to-`READY` after cancellation, this is where the PRD and the tests would diverge.

2. `price-quote`'s `seat_count` is optional with no declared default; specified as treated as 1 when omitted, since `amount_due_cents` in the response shape is undefined otherwise.

Verified mechanically end-to-end: all 54 endpoints and 49 error codes present in the §4/§5 tables, every error id also mentioned in §2/§3 narrative, all state enum strings present, §2.2 byte-identical to the canonical source, and the file ends at §5 with no audit footer.

## Step 6: Generate implementation — 2026-08-22T03:27:00.750Z

Implementation complete and verified.

## What was built

`workspace/implementation/` — Python + Flask, in-memory dicts only, no seeding at startup.

```
start.sh (guarded pip install + exec python3 app.py, 0.0.0.0:$PORT default 10000)
requirements.txt, app.py, db.py, errors.py, response.py, middleware.py,
validate.py, calc.py, domain.py
routes/{seasons,venues,union,concerts,contracts,musicians,rehearsals,
        engagements,patrons,subscriptions,tickets,adbookings,clock}.py
```

**Verified**: all 54 endpoints routed (exact count printed from the url_map), server boots clean from a fresh process via `bash start.sh` and answers HTTP, and two end-to-end smoke suites pass with 0 failures.

## Coverage

- **Envelope**: `meta{api_request_id,api_request_timestamp}` / `response_type` / `data`; pagination (`limit`/`offset`/`total_count`/`has_more`) inside `meta`; `limit` default 10, min 1, max 100 (out-of-range → 422).
- **Auth**: `X-User-ID` + `X-User-Role`, 7 roles; opaque vs entity-backed identity (Patron→patron_id, Musician→engagement.musician_id, GuestArtist→contract.id) on exactly the 8 rung-5 operations.
- **22-rung validation ladder** implemented in strict order per §2.6 — notably OCC (rung 9) below the state gates, union rungs 10–15 above commercial rungs 17–22, seat availability last.
- **8 state machines** including Concert's 3 independent dimensions, the cyclic OFFERED↔COUNTERED contract, and the two divergent sign branches (agreed = offered_fee vs countered_fee).
- **All 10 calculations** with `Decimal`/ROUND_HALF_UP and pinned evaluation orders: dynamic ticket price (section→demand→donor→clamp last), per-line subscription rounding with NEW/RENEWAL variants, additive (never compounded) musician premiums with flat overtime, ad invoice (volume tier on undiscounted subtotal, placement fee on discounted), donor level, priority score, plus the three conserved-quantity invariants.
- **Cascades**: season advance (RENEWAL_WINDOW / SINGLE_ON_SALE 3-hop / CLOSED), run-ops epoch sweep, concert cancel CASCADE A+B, engagement decline CASCADE C, substitution unlock.
- **2 OCC rules** with `expected_concert_version` / `expected_package_version` → 412.
- **49 error codes** with the scaffold's exact HTTP statuses.

## Design notes worth flagging

- **Inventory is recomputed from live claims** (§2.9 aggregation) rather than incremented/decremented, so `capacity = available + held + sold` holds by construction after every forward and compensating action. Smoke tests assert the identity across all concerts, and the patron cash identity (§2.10) too.
- **Version bookkeeping** uses a per-request "already bumped" set, so a cascade touching one resource across several hops leaves exactly one version increment. `force_bump` covers the one case (renew's prior package) where the spec mandates a bump with no other field change.
- **Datetime fields echo the client's literal string**; parsed values are kept under `_`-prefixed keys (stripped at serialization) for comparisons.
- **Logical clock** defaults to `2026-08-01T00:00:00Z`; `created_at` sorting is stabilized by an internal insertion sequence since a frozen clock makes timestamps identical.
- Two spots the PRD leaves genuinely open, decided literally: a `GuestArtist` signing a `COUNTERED` contract is **not** rejected (no error code is assigned to an actor/branch mismatch, and §4 lists both roles on the endpoint — the branch is chosen by contract state); and `GET /orchestra/union-agreements/{agreement_id}` on an unknown id returns 404 with `ERR_SERVICE_NOT_FOUND`, since the catalogue defines no agreement-specific 404.

## Step 5: Generate unit tests — 2026-08-22T03:36:37.352Z

Done. Both stages are written and audited.

## What was generated

**`test_helpers/`** (2,208 lines) — 9 modules:
- `types.py` — 18 status/role enums + TypedDicts for all 13 entities (all carry `id`/`created_at`/`updated_at`/`version`, per PRD §2.4's "There are no resources in this system that omit `updated_at` or `version`")
- `api_client.py` — one method per PRD endpoint (56 methods) under the `/orchestra` prefix, plus `/_clock/set_current_utc`
- `api_errors.py` — 50-entry `ApiErrorId` enum + HTTP map, registered with `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `inventory_for` / `assert_inventory_counts`, plus the three conserved-quantity checkers (`assert_seat_conservation`, `assert_patron_cash_identity`, `assert_service_credit_identity`)
- `factories.py`, `constants.py`, `test_users.py` (opaque-role constants **and** `make_patron_headers` / `make_musician_headers` / `make_guest_artist_headers` builders for the three `entity_backed` roles), `fixtures.py` (688 lines: primitives, fresh reads, a parameterised `build_world` season builder, `setup_published_service`, `setup_locked_concert`, `setup_renewal_chain` two-season builder, ticket/package shortcuts)

**`test_suite/`** — `conftest.py` + 12 domain-named files, **110 collected tests**.

## Coverage audit (scripted against both yamls)

- 19 difficulty instances × **≥2 tests each** = 38 tagged tests — zero shortfall
- 69 non-stub corner instances × **≥1 test each** = 69 tagged tests — zero shortfall
- 107 `Design:` tags total, every one resolving to a real instance; no untagged, dual-tagged or dangling tags
- All 17 `excluded_because` stubs verified to point at existing difficulty instances; none translated

## Verification performed

- **PRD verbatim check**: all 204 quoted citations normalised and confirmed as literal substrings of `workspace/PRD.md` (6 initial failures were `§`-symbol drops, fixed). Every test's shortest citation is ≥8 words.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere.
- `pyflakes` clean on `test_suite/`; `pytest --collect-only` collects 110 tests with no import errors.
- All literal expected values were re-derived by hand from the PRD formulas and match the design indices (e.g. provisional 28500 / final 36500 at 20 OT minutes; package 14438 not 14439; renewal 25718 vs NEW 31920; ad invoice 552000 not 561600; LAUREATE quote clamped up to 7650, PEAK clamped down to 10800; priority scores 570 / 600).

## Notes worth relaying

- Two mild judgement calls resolved in favour of generating: (1) list-filter query-parameter names (`?service_id=`, `?sale_status=`, `?prior_package_id=`) are named only as "filtered by service, musician or status" in the PRD's endpoint table — treated the entity's own field name as uniquely derivable, consistent with the rest of the PRD; (2) `negotiation_round` is asserted *not* to advance on `counter`, since the PRD attaches "increments `negotiation_round` by one" to `revise-offer` alone.
- Nothing was skipped: every non-stub instance passed the PRD-first two-condition filter, because this PRD states each rule, error id and threshold explicitly in prose.

## Step 7: Test and fix loop — 2026-08-22T03:41:00.000Z

The loop terminated on iteration 1 — no fixes were required.

## Summary

**Iterations run: 1** (one full 8-round parallel sweep).

**Result: all 8 rounds green — 110/110 passed, 0 failed, 0 errors, 0 skipped in every round.** Per-round wall time ~142s; the 8 rounds ran concurrently and each claimed its own port via the runner's lock file, with no collisions.

Verified two independent ways so a green result isn't taken on trust:
- `results.{1..8}.json`: `total=110, passed=110, failed=0, errors=0, skipped=0`, and every one of the 110 per-test records carries `status: "passed"` (not just the aggregate counters).
- Raw pytest logs for all 8 rounds: 110 `PASSED`, 0 `FAILED`, 0 `ERROR` each.

Since the union of failing tests across the 8 rounds was empty, the diagnostic protocol (STEP 0 → STEP 3) never engaged.

- **Tests deleted:** none. No test failed, so no PRD-silence or unique-derivability adjudication was triggered.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:** none.

Two notes worth passing on:

1. **No flakiness surfaced.** The timing-sensitive areas this sweep is designed to catch — the OCC rungs (`test_second_hold_from_a_stale_concert_version_is_rejected`), the ops-run epoch expiry, and the conserved-quantity identities — were stable across all 8 concurrent rounds. Determinism here is structural rather than lucky: the implementation uses a logical clock (frozen at `2026-08-01T00:00:00Z` until explicitly set) and recomputes inventory from live claims by aggregation instead of incrementing counters, so there's no accumulator to drift under load.

2. **One transient during the sweep.** Round 1's log shows a `Killed` line against the very first test's server boot before it went on to pass — consistent with memory pressure from 8 concurrent runners at startup, not an implementation fault. It self-recovered and did not recur; worth knowing if this sweep is ever run on a smaller host, where staggering the launches would be safer.

The suite also contains no `skip`/`xfail`/`skipif` markers anywhere, so the 110 passes are 110 real assertions rather than silently neutralized ones.

## Step 8: Finalize PRD — SKIPPED

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the tests exercised, so no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `workspace/PRD.md`.

## Step 9: Complete PRD — 2026-08-22T03:50:00.000Z

`workspace/PRD_COMPLETED.md` is written.

## Counts

| | |
|---|---|
| `PRD.md` | 436 lines, 102,605 chars |
| `PRD_COMPLETED.md` | 436 lines, 107,836 chars (**+5,231**) |
| Paragraphs touched | 26 (all in-paragraph; no new sections, no new paragraphs) |
| Ambiguity-pins | 27 |
| Mismatch-revisions | 3 |

## Changes

- §2.2 Response Structure — insert — ambiguity — `api_request_timestamp` reads the logical clock, not wall time; `api_request_id` is `req_` + 20 uppercase alphanumerics — `response.py:10,14,20`
- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` 422; empty string = omitted — `validate.py:163-182`
- §2.3 Pagination — insert — ambiguity — `created_at` ties broken by insertion order — `validate.py:185-188`
- §2.4 Audit Fields — insert — ambiguity — `created_at`/`updated_at` read the logical clock; a multi-hop request bumps `version` once but refreshes `updated_at` each hop — `domain.py:38-78`, `db.py:47-64`
- §2.6 rung 3 — insert — ambiguity — unresolvable `agreement_id` → `ERR_SERVICE_NOT_FOUND` — `routes/union.py:156`
- §2.6 rung 8 — revise — **mismatch** — rung guards ten operations, not six (adds publish/engagements for `ERR_UNION_AGREEMENT_MISSING`, decide/cancel for season-`CLOSED`) — `routes/rehearsals.py:125,245`, `routes/adbookings.py:230`, `routes/concerts.py:142`
- §2.9 Seat Inventory — insert — ambiguity — `section_inventory` elements ordered by section `created_at` ascending — `routes/concerts.py:30-33`
- §3.2 Concert creation — insert — ambiguity — no end-after-start rule on `performance_*_utc`; both echoed verbatim — `routes/concerts.py:62-72`
- §3.2 Counter — insert — ambiguity — `countered_fee_cents` required, non-negative — `routes/contracts.py:83`
- §3.2 Revise-offer — insert — ambiguity — `offered_fee_cents` required, non-negative — `routes/contracts.py:103`
- §3.2 Signing — revise — **mismatch** — branch chosen by contract status alone; either role may sign either branch (ownership only binds `GuestArtist`); no body fields — `routes/contracts.py:116-133`
- §3.3 Engagement booking — insert — ambiguity — `doubling_count` must not be negative — `routes/rehearsals.py:240`
- §3.3 Rest rule — insert — ambiguity — same-service engagements excluded; overlapping services are an outright rest violation — `routes/rehearsals.py:256-266`
- §3.3 Daily cap — insert — ambiguity — counts engagements on this very service too — `routes/rehearsals.py:271-279`
- §3.3 Clock-out — insert — ambiguity — worked minutes truncated downward to whole minutes — `routes/rehearsals.py:38-39,192`
- §3.3 Clock-out — insert — ambiguity — one overtime figure per service, stamped identically on every settled engagement — `routes/rehearsals.py:196,210`
- §3.3 Decline cascade — revise — **mismatch** — hop three recomputes posture on *every* decline (not "becomes AT_RISK"); hop four fires only when the service actually fell understaffed — `routes/engagements.py:226-231`
- §3.4 Donations — insert — ambiguity — `amount_cents` required integer, no minimum enforced — `routes/patrons.py:281`
- §3.5 Season advance — insert — ambiguity — `target_status` must be the immediate successor; bad enum → `ERR_INVALID_REQUEST`, wrong target → `ERR_INVALID_SEASON_TRANSITION` ahead of preconditions — `routes/seasons.py:16-22,72-77`
- §3.5 Package build — insert — ambiguity — `concert_ids` persisted/echoed in caller order; performance ordering is pricing-only — `routes/subscriptions.py:103`
- §3.5 Package build — insert — ambiguity — `fulfilled_concert_count` computed at creation, refreshed on concert cancellation — `routes/subscriptions.py:110,229`, `routes/concerts.py:162-165`
- §3.6 Renewal — insert — ambiguity — ownership compares the **prior** package's `patron_id` — `routes/subscriptions.py:175`
- §3.6 Priority gate — insert — ambiguity — recomputed score is persisted before the gate and survives a refusal — `routes/subscriptions.py:195-201`
- §3.6 Renewal gates — insert — ambiguity — no section-venue gate on renewal; foreign-hall concert → `ERR_INSUFFICIENT_SEATS` — `routes/subscriptions.py:208`, `domain.py:179-183`
- §3.6 Loyalty discount — revise — **mismatch** — rate reads the **target** season's `loyalty_discount_bp` and the patron's current `consecutive_renewal_years` — `routes/subscriptions.py:211-212`
- §3.7 Price quote — insert — ambiguity — query params; `seat_section_id` required; 404 order section→patron; `seat_count` integer ≥ 1 — `routes/concerts.py:282-301`
- §3.7 Price quote — insert — ambiguity — no venue match; foreign section priced as an empty house at its own capacity — `routes/concerts.py:307-311`
- §3.9 Substitution — insert — ambiguity — `replacement_fee_cents` non-negative; contract of another concert → `ERR_CONTRACT_NOT_FOUND` — `routes/concerts.py:219-223`
- §3.9 Substitution — insert — ambiguity — response body is the replacement contract, not the concert — `routes/concerts.py:249`
- §3.9 Cancellation — insert — ambiguity — `reason` required non-empty string, validated ahead of both state gates — `routes/concerts.py:138-143`

Verified-and-unchanged areas (PRD already pinned uniquely): all pricing formulas and rounding order (single-ticket clamp, package four-step, ad invoice, musician premium/overtime), donor thresholds and points, all three concert status dimensions and `readiness_posture` recompute sites, promotion/unlock conditions, ladder rung ordering in every handler, both cascades on cancellation, ops-run epoch semantics, conserved-quantity aggregation, and the full endpoint/role table.
