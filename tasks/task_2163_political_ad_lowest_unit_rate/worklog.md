# Worklog — task_2163_political_ad_lowest_unit_rate

## Step 1: Create Task Directory — 2026-08-28T00:00:00.000Z

Created `tasks/task_2163_political_ad_lowest_unit_rate/` and `tasks/task_2163_political_ad_lowest_unit_rate/workspace/`.

## Step 2: Generate Scaffold — 2026-08-28T10:12:00.000Z

All three artifacts are written and pass the skill's linter.

## Output

- `/home/ubuntu/github/CodingPRD/tasks/task_2163_political_ad_lowest_unit_rate/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_2163_political_ad_lowest_unit_rate/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, single top-level key
- `/home/ubuntu/github/CodingPRD/tasks/task_2163_political_ad_lowest_unit_rate/SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, single top-level key

## Design

**Profile**: `compliance_audit` × `pricing_engine`, flat topology, cyclic state machines, `segregation_of_duties`, immediate consistency; layers = OCC, cascading side effects, dual-variant calculation, rate/threshold triggers. Expert-plus band: **11 entities, 43 endpoints, 51 errors, 51 ordered validations, 8 state machines, 11 calculations, 2 OCC rules, 5 roles**.

Entities: Station, Election, Advertiser, RateClass, CommercialOrder, ScheduledSpot, PoliticalFileEntry, EqualOpportunityRequest, LucDetermination, RebateLedgerEntry (append-only), FccComplaint. Logical clock at `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default.

**Nine §0.5 rules, 2 instances each (18 total)**:
- *Dual-variant*: PROVISIONAL vs FINAL lowest-unit-charge (95000 vs 100000 on identical data) — pricing domain; SPOT_COUNT vs DOLLAR_VALUE equal-opportunity parity (6 vs 5 units) — airtime domain.
- *Combinatorial*: mode (b) round-per-spot-then-sum (35185 vs the 35183 trap); mode (c) commission tier keyed on gross 246000 → 4920/250920, not the fixed-point 8610/254610.
- *Non-linear*: Advertiser review cycle with fourth-REQUEST_INFO auto-reject; CommercialOrder `status × payment_status` parallel dimensions.
- *Cascades*: depth-4 FINAL-determination reprice → order → rebate → political file entry; depth-3 audit-sweep overdue → FROZEN posture → order SUSPENDED.
- *Priority conflicts*: state(27) vs business_fiscal(71); business_safety(43) vs business_temporal(57).
- *Boundaries*: posture at exactly 2 overdue (FROZEN) / exactly 1 (RESTRICTED); empty spot collection at submit.
- *Cross-entity*: EO request → CommercialOrder aired state; CommercialOrder → Station posture.
- *Overlap*: strict half-open collision on RateClass (1030 legal, 1029 rejected); 900-second buffer adjacency on Election across rate classes (899 rejected, 900 admitted).
- *Invariants*: money (`paid − refunded == net_due`, 0 drift after cancel+refund); airtime units (`election_eo_outstanding_units` back to 0 after cancelling the granted order).

**§1.9**: 61 instances across all nine claim-extraction sections (49 with executable recipes, 12 `excluded_because` stubs pointing at named §1.8 instances).

## Verification performed
- Every monetary/tier literal in the asserts was computed in Python against the declared formulas and constants (7037/35185, 7407/29628, 4920/250920, 6481/64810, 95000/100000, 5557, 7407+7407=14814, 172800 s, 570000→5 units).
- Custom placeholder-closure check: **0 unbound `${var}`** across both design files; 79 unique instance names, no collisions.
- Grounds resolution check: all `grounds[]` refs resolve to declared entities/fields, calculations, validation priorities, errors, roles, state transitions, endpoints, or concurrency rule ids.
- Error catalog ↔ validations cross-check: 0 orphan errors, 0 dangling error_ids; all endpoint roles declared, all roles used.
- Forbidden concurrency vocabulary: none present. No UUID/`id` used in any selector, ranking, or tie-break (LUC tie-break is `created_at ASC → air_date ASC → start_offset_seconds ASC`).

Linter verdict (verbatim):

```
SCAFFOLD §1.8/§1.9 -&gt; §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    43
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  806

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory was read, listed, or grepped at any point.

## Step 3: Copy Shared Files — 2026-08-28T10:12:00.000Z

Copied `INSTRUCTION.md` to `tasks/task_2163_political_ad_lowest_unit_rate/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-28T10:24:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2163_political_ad_lowest_unit_rate/workspace/PRD.md` (405 lines, ~84 KB), written incrementally in eight appends and verified against the scaffold programmatically.

**Structure**: §1 Introduction (3 paragraphs); §2 with nine subsections (2.1 Participants/Headers/Attribution, 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Identity/Versioning/Logical Clock, 2.5 Money & Rounding, 2.6 Stale-View Protection, 2.7 Path Resolution & Referential Scoping, 2.8 Cascade Discipline, 2.9 Rejection Precedence); §3 with nine domain-derived subsections (station posture ladder → elections & classification → rate card → order assembly & geometry → disclosure & acceptance → airing/preemption/settlement → LUC determinations & final reprice → equal opportunity → political file/complaints/audit checkpoint); §4 endpoint table (4 columns); §5 error table (2 columns).

**Hard Contracts**

```
Field coverage check:
- entities[].fields: 103 required, 103 present, 0 missing
- endpoints[].request_body/input: 60 required, 60 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 51 checked, 51 expressed in prose (§2.9 states the full 11-rung precedence ladder), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_election_version / expected_order_version + ERR_STALE_ELECTION_VERSION / ERR_STALE_ORDER_VERSION + HTTP 412 all named), 0 missing
- state_machines[].transitions: 8 machines / 34 transitions checked, 34 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed as prose (no pseudocode, no fuzzy words), 0 missing
- validations[] conditions: 51 checked, 51 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 43 endpoints checked, all side-effect sets expressed, 0 missing
- entities[].fields[] structured content: 103 checked, defaults/initials/enums reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (ACCEPT vs REJECT, GRANT vs DENY, AIRED vs PREEMPTED, PROVISIONAL vs FINAL, SPOT_COUNT vs DOLLAR_VALUE, sweep step 5 vs step 6), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 809
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Verification of completeness**: all 43 endpoint rows and all 51 error rows present in §4/§5; all 43 scaffold paths matched verbatim; §2.2 byte-identical to `section-2.2-response-structure.md`; all 8 state machines, all 11 calculations, and all enum/state values present. `RebateLedgerEntry`'s `common_fields: false` is stated explicitly (only `id` and `created_at`; no `updated_at`, no `version`). PRD ends at §5 with no audit footer.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

Orchestrator verification: `wc -l` = 405; §4 table = 43 endpoint rows; §5 table = 51 error rows; file ends at `ERR_ORDER_NOT_PAID` — no truncation.

## Step 5: Generate Unit Tests — 2026-08-28T11:06:00.000Z

Test infrastructure and suite generated and audited.

## What was produced

**`test_helpers/`** (9 files, ~2,057 lines)
- `types.py` — 24 status/role enums + 11 entity TypedDicts. `RebateLedgerEntry` correctly omits `updated_at`/`version` (it is the PRD's one `common_fields: false` resource).
- `api_client.py` — one method per endpoint, all 43 rows plus `/_clock/set_current_utc`.
- `api_errors.py` — all 51 error ids with their HTTP statuses, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity shape assertions plus domain invariants (`assert_station_posture` re-derives the max-not-sum rule, `assert_order_money_invariants`, `assert_unit_equivalent_normalisation`, `round_half_up`).
- `factories.py`, `constants.py`, `test_users.py` — `AdvertiserAgent` is `entity_backed:Advertiser`, so `make_advertiser_agent_headers(advertiser_id)` is mandatory and every fixture threads the real advertiser id; two distinct officer principals (`officer-alpha` / `officer-beta`) exist because segregation of duties is enforced on the person.
- `fixtures.py` (754 lines) — single-step steps plus four composite tiers: `setup_issue_order`, `setup_candidate_order`, `setup_two_candidate_orders` (opposing candidates + EO clock), `setup_station_with_two_overdue_adjustments` (double preemption → two overdue file entries → frozen posture).

**`test_suite/`** — `conftest.py` + 12 domain-named files, **88 tests**, all collecting cleanly.

## Coverage audit (all green)

- All **18** difficulty instances have **≥2** tests each (36 tests).
- All **51** non-stub corner instances have **≥1** test each.
- **10** `excluded_because:` stubs were not translated; every `difficulty_instance` cross-reference resolves to a real name.
- 0 untagged, 0 dual-tagged, 0 unknown tags; every docstring ends with exactly one `Design:` line.
- **179 PRD quotations machine-verified verbatim** against `workspace/PRD.md` (whitespace-normalised substring match). Two initial mismatches were found and corrected.
- No `skip`/`skipif`/`xfail`; no scaffold references leak into generated code.

## Two assertions deliberately narrowed (PRD gap, not weakening)

The PRD never states that creating a LUC determination advances the **election's** `version` — §2.6 only says the request is rejected when `expected_election_version` ≠ current. A PRD-only implementer could leave the election version at 1 forever and still be faithful. So:
- `Corner/endpoints/luc_determination_supersedes...` asserts `version == 1` on creation (§2.4 covers that) and the full supersede outcome, but not the `1 → 2 → 3` chain.
- `Corner/cross_cutting_complexity_layers/stale_expected_election_version...` sends an unambiguously wrong version (`current + 999`) rather than relying on an unstated bump, and asserts the rejection plus "no second determination row".

Both instances are still covered; only the un-derivable version arithmetic was dropped.

## One recipe deviation worth knowing

`Corner/rbac/missing_auth_headers...` asks to prove "no Station with call_sign WNUL-TV exists afterwards", but the PRD declares no station-listing endpoint. The test instead re-registers the same `call_sign` with valid headers and asserts it succeeds with `version == 1` — call signs are unique across the platform (§3.1), so success proves the unauthenticated attempt persisted nothing.

## Step 6: Generate Implementation — 2026-08-28T10:47:00.000Z

Implementation complete and verified.

## What was built

`tasks/task_2163_political_ad_lowest_unit_rate/workspace/implementation/` — Python + Flask, split across 8 modules (written and verified one at a time, no oversized single write):

- **`start.sh`** — guarded `pip install` (only when `import flask` fails), `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000).
- **`app.py`** — blueprint registration, `ApiError`/HTTPException handlers, plus a process-wide request lock so cascades and OCC checks stay atomic under concurrent requests.
- **`core.py`** — logical clock (defaults to `2026-08-01T00:00:00Z`, never falls back to wall time), in-memory store with `_seq` insertion ordering, error catalog (all 51 IDs → HTTP codes), `meta`/`response_type`/`data` envelope, auth (`X-User-ID`/`X-User-Role`, five roles), ownership check, pagination (`limit`/`offset`/`total_count`/`has_more`), fixed-type-order existence resolver, payload-shape validators.
- **`pricing.py`** — all constants and pure calcs (`Decimal` + `ROUND_HALF_UP` everywhere, no floats).
- **`domain.py`** — `order_gross_charge` (round-per-spot-then-sum), `order_net_due` (tier read from gross only), reprice-then-settle rebate increments, event-then-file entries, `lowest_unit_charge`, `luc_final_reprice` (4-hop cascade), EO parity, order-lifecycle helpers.
- **`serializers.py`** — exact field shapes; station counters and posture, election status, and `entitled_to_luc` are **derived on read** (immune to counter drift); `RebateLedgerEntry` carries only `id`/`created_at`.
- **`routes_admin.py` / `routes_orders.py` / `routes_compliance.py`** — all **43 endpoints**, each handler ordering its checks along the PRD §2.9 ladder (auth → pagination → existence → payload → OCC → lifecycle → safety gates → referential → temporal → composition/geometry → fiscal).

## Verification

Three scripted end-to-end suites, all **0 failures**, covering: volume-tier repricing, the PROVISIONAL cap at acceptance, `POSTED_RATE_FALLBACK` vs `LOWEST_QUALIFYING_SPOT`, FINAL retroactive reprice with 4 incremental rebate rows (9000 each, total 36000) and `PAID→REFUND_DUE→REFUNDED`, preemption raising surviving-spot charges, agency commission (52500 → 1050 → 53550), both EO parity bases (`SPOT_COUNT` 10 vs `DOLLAR_VALUE` 8 on identical spots), grant reversion on cancel, posture ladder + audit sweep `ACCEPTED→SUSPENDED→ACCEPTED`, `LATE_POSTED` lateness, segregation of duties, OCC (4 concurrent payments → one 200, three 412), and rounding edge (`9999 × 0.35 × 2 = 6999`, unit-equivalent `3500`). Fresh boot confirmed: all ten collections `total_count=0` — **no startup seeding**.

## Judgement calls worth flagging

1. **Three constraints have no declared error ID** — `CLASSIFY_CANDIDATE` preconditions, the EO grant's four order conditions, and duplicate `call_sign`. All return `ERR_INVALID_REQUEST` (422).
2. **Ownership before existence** (ladder rung 1 vs 3): checked when the resource resolves; an unknown id falls through to its 404. On creates the body's `advertiser_id` is compared only when actually supplied, so a *missing* one yields `ERR_INVALID_REQUEST`, not `ERR_NOT_RESOURCE_OWNER`.
3. **`sponsorship_disclosure_text` is required but nullable** (so `MISSING` grading stays reachable); `disclosure_duration_seconds` is strictly required.
4. **`luc_final_reprice` targets carry no order-status filter** — per PRD §3.7 the criteria list omits one, so spots on `DRAFT` candidate orders are repriced. This is literal-to-spec and surfaced in testing (a determination repriced 2 draft-order spots).
5. **Version bumps on cascade-repriced spots** follow PRD §2.8 ("each entity it touches") but only when a value actually changed, and never for the spot created in the same request — so a newly added spot still reads `version: 1`.

## Step 7: Run Tests and Iterate — 2026-08-28T11:12:00.000Z

All 8 parallel rounds passed on the first iteration. Exiting per the protocol.

## Summary

**Iterations run:** 1 (single 8-round parallel stability sweep; no fixes were required).

**Sweep result:** all 8 rounds `passed == total == 88`, `failed = 0`, `errors = 0`, `skipped = 0`. Union of failing tests across rounds 1–8 is empty, so no flakiness surfaced (the 8 rounds tracked each other in lockstep through all 88 per-test-server reboots, including the OCC/concurrency and audit-sweep cases).

**Tests deleted:** none. The diagnostic protocol never entered STEP 1 — there were no failures in any round to triage, so no PRD-silence or unique-derivability deletion was warranted.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Vacuity check (since a green sweep alone is not proof of substance):**
- `grep -rn "skip\|xfail" test_suite/` → 0 hits, so nothing is being silently passed over.
- 88 `def test_` functions across the 12 suite files == 88 tests collected and reported per round — no collection shortfall hiding tests.
- `results.*.json` reports `skipped: 0` in every round, confirming the 88 are real executions.

**Relevant paths:**
- Test suite: `/home/ubuntu/github/CodingPRD/tasks/task_2163_political_ad_lowest_unit_rate/test_suite/` (12 files, 88 tests)
- Helpers: `/home/ubuntu/github/CodingPRD/tasks/task_2163_political_ad_lowest_unit_rate/test_helpers/` (`fixtures.py`, `factories.py`, `test_users.py`, `assertions.py`, `constants.py`, `api_client.py`, `api_errors.py`, `types.py`)
- Implementation: `/home/ubuntu/github/CodingPRD/tasks/task_2163_political_ad_lowest_unit_rate/workspace/implementation/` (`app.py`, `core.py`, `domain.py`, `pricing.py`, `serializers.py`, `routes_admin.py`, `routes_orders.py`, `routes_compliance.py`, `start.sh`)
- Per-round results: `/home/ubuntu/github/CodingPRD/tasks/task_2163_political_ad_lowest_unit_rate/workspace/implementation/results.{1..8}.json`

**Note on two things worth knowing about the artifact as it stands** (not defects, but they explain why the suite is green without intervention): the implementation already stores state in-memory only and does no startup seeding — `start.sh`'s guarded `pip install` (it installs only when `import flask` fails) is what keeps 8 concurrent rounds × 88 reboots from timing out on pip contention. And `test_users.py`'s `make_advertiser_agent_headers(advertiser_id)` threads the real advertiser id into `X-User-ID` for every buy-side call, which is what keeps the PRD's ownership rung (§2.9 rung 1) satisfied rather than tripping `ERR_NOT_RESOURCE_OWNER` across the order tests.

### Orchestrator-side corroboration of the first-sweep green

A green first sweep is indistinguishable, on its face, from a design-index leak or a vacuous suite, so the orchestrator independently verified all three explanations:

1. **All 8 result files re-read directly**: every round `passed=88, failed=0, total=88, errors=0, skipped=0`.
2. **Design-index leak audit (Step 6)**: the implementation-generator subagent transcript was scanned at the `tool_use` *input* level (not by grepping prose, which false-positives on the prompt's own mention of the filenames). 129 transcript lines, **0 tool calls** whose input referenced `SCAFFOLD_DIFFICULTY_DESIGN` or `SCAFFOLD_CORNER_DESIGN`. The withhold constraint held.
3. **Mutation test of the green sweep**: two mutations were injected into `implementation/pricing.py` — rounding mode `ROUND_HALF_UP → ROUND_DOWN`, and `POSTURE_FROZEN_THRESHOLD 2 → 3` (the exact-2-overdue boundary). Result: **78 passed / 10 failed**. The suite kills both mutants, so the green is substantive rather than vacuous. `pricing.py` was then restored (md5 verified identical to the pre-mutation copy) and re-run clean: **88/88**.

## Step 8: Finalize PRD — SKIPPED — 2026-08-28T11:20:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD_FINALIZED.md` is not produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-28T11:29:00.000Z

Done. PRD_COMPLETED.md is written, structurally intact (405 lines, 43 endpoint rows in §4, 51 error rows in §5, headings identical).

## Summary

- **Source**: `workspace/PRD.md` (405 lines, 83,704 bytes) → **`workspace/PRD_COMPLETED.md`** (405 lines, 90,258 bytes; **+6,554 bytes**, 0 line delta — every change is an in-paragraph insert/revise, no new sections or paragraphs).
- **19 lines changed**, all via targeted in-place edits.
- **Counts**: 16 ambiguity-pins, 3 mismatch-revisions.

### Changes

- §2.1 — revise — ambiguity — ownership vs. existence interleaving pinned: path-named order that resolves to nothing skips the ownership compare and falls to 404; body-named `advertiser_id`/`requesting_advertiser_id` is compared to `X-User-ID` *before* existence (403 even for a non-existent id); an absent/null/non-string field skips the compare and falls to rung 4 — `routes_orders.py:25-31,42-44`, `routes_compliance.py:86-88`
- §2.1 — insert — ambiguity — segregation-of-duties skipped when the named order has a null `accepted_by_user_id`, and cannot run against an unknown complaint (falls to `ERR_COMPLAINT_NOT_FOUND`) — `routes_compliance.py:330-338`
- §2.3 — insert — ambiguity — server creation order is the tie-break on equal `created_at` in every collection ordering — `core.py:236-239`
- §2.7 — insert — ambiguity — the fixed resource-type order is one combined pass over path *and* body identifiers — `core.py:272-281`, `routes_compliance.py:166-169`
- §2.8 — **revise — mismatch** — "bumps each entity it touches" → bumps only entities actually changed; repriced spot bumped only when a figure moved; spot created in the same request never bumped (returns `version` 1); no double-bump for a spot already bumped in an earlier hop; station bumped at most once per request; each lifecycle transition counts separately (airing that starts+completes an order = +2) — `domain.py:40-56,307-316`, `core.py:254-265`
- §2.9 — insert — ambiguity — per-field empty-string policy: identifiers plus `call_sign`/`rejection_reason`/`preemption_reason`/`denial_reason`/`granted_order_id` non-empty; the listed free-text fields required but empty-string-tolerant — `core.py:409-432` + all route call sites
- §3.1 — revise — ambiguity — duplicate `call_sign` → `ERR_INVALID_REQUEST` (422), checked after all other shape checks — `routes_admin.py:43-45`
- §3.2 — insert — ambiguity — `reason` handling: stored on `CLASSIFY_ISSUE`/`REJECT` only when supplied (no default), discarded entirely on the `REQUEST_INFO` loop leg, which writes neither `classification_reason` nor `classified_by_user_id` — `routes_admin.py:275-303`
- §3.2 — insert — ambiguity — the three `CLASSIFY_CANDIDATE` preconditions → `ERR_INVALID_REQUEST` (422), evaluated *after* the `UNDER_REVIEW` check, not at rung 4 — `routes_admin.py:283-290`
- §3.3 — insert — ambiguity — re-withdrawing an already-`WITHDRAWN` class succeeds with 200 and a further version bump — `routes_admin.py:364-370`
- §3.5 — insert — ambiguity — `sponsorship_disclosure_text` required-key-but-nullable (null/empty grade `MISSING`); `disclosure_duration_seconds` strictly required and non-nullable — `routes_orders.py:56-61`
- §3.6 — **revise — mismatch** — removed "a `CHARGE` requires the settlement state to be `INVOICED`"; impl has no settlement-state check, the amount test alone forecloses a second charge — `routes_orders.py:334-346`
- §3.7 — insert — ambiguity — the determination endpoint bumps the *election's* `version`; the acceptance-time `PROVISIONAL` determination does not; superseding bumps the superseded record — `routes_admin.py:192-195`, `routes_orders.py:293`
- §3.7 — insert — ambiguity — basis-spot tie-break has a fourth key: server creation order — `domain.py:158`
- §3.7 — **insert — mismatch/silence** — `FINAL` target set carries no order-status filter; `DRAFT`/`SUBMITTED`-order spots are repriced — `domain.py:203-221`
- §3.7 — insert — ambiguity — target processing order has creation order as final tie-break — `domain.py:223`
- §3.8 — insert — ambiguity — EO grant's four order conditions → `ERR_INVALID_REQUEST` (422), evaluated after the open-state and deadline checks — `routes_compliance.py:191-198`
- §3.9 — revise — ambiguity — `late_by_seconds` is keyed to `clock &gt; due_at`, not to the outcome: an `OVERDUE` entry posted after the clock is moved back reports `LATE_POSTED` with `late_by_seconds` 0 — `routes_compliance.py:59-72`
- §4 — revise — ambiguity — `payment_status` added to the filter enumeration and to the `GET /political-ads/orders` row — `routes_orders.py:117-121`

Notable non-changes (verified impl already matches PRD): the whole rejection ladder order at every endpoint, all pricing/rounding formulas, volume and commission tiers, posture thresholds, disclosure grading branches, placement-geometry predicates, the audit-sweep six steps, and all cascade shapes.

Orchestrator verification: `PRD_COMPLETED.md` = 405 lines / 90,258 bytes; §4 table intact at 43 endpoint rows; §5 table intact at 51 error rows — no truncation.
