# Worklog — task_2779_live_video_commerce_operations

## Step 1: Create task directory — 2026-09-04T20:22:47.995269323Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2779_live_video_commerce_operations and its workspace/ subdirectory. Index 2779 pre-assigned by the orchestrating command; no index scan performed.


### (Sub-note appended by the Step 2 scaffold subagent itself, not by the orchestrator — retitled from "## Step 2b" so it cannot be mistaken for a pipeline step; content left verbatim. It records the §1.9 corner-design substep of Step 2.)
- Wrote SCAFFOLD_CORNER_DESIGN.yaml (3220 lines, 83 instances across the nine
  claim-extraction-guide sections; 61 full test recipes + 22 excluded_because
  stubs citing §1.8 instances).
- scaffold_lint.py: VERDICT clean lint (62 endpoints, 13 entities,
  22 §1.8 instances, 61 §1.9 instances, 1609 calls scanned).

## Step 2: Generate scaffold — 2026-09-04T21:51:27.000Z

All three scaffold artifacts are complete and lint-clean.

Output directory:
    -rw-rw-r-- 1 ubuntu ubuntu 138978 SCAFFOLD.yaml                    2651 lines
    -rw-rw-r-- 1 ubuntu ubuntu  90690 SCAFFOLD_DIFFICULTY_DESIGN.yaml  1773 lines
    -rw-rw-r-- 1 ubuntu ubuntu 157468 SCAFFOLD_CORNER_DESIGN.yaml      3220 lines

SCAFFOLD.yaml top-level keys are `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key is present; each design file has exactly one top-level key.

Lint verdict (verbatim):

    SCAFFOLD §1.8/§1.9 -> §1.5 lint report
    ============================================================
      SCAFFOLD:           .../SCAFFOLD.yaml
      Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
      Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

    Coverage
      §1.5 endpoints declared:    62
      §1.1 entities declared:     13
      §1.8 instances scanned:     22
      §1.9 instances scanned:     61
      Calls scanned (§1.8+§1.9):  1609

    VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

(clean on the first lint run; no fix iterations needed)

SCAFFOLD.yaml counts: 13 entities · 62 endpoints · 8 state machines (45 transitions) · 8 calculations · 31 validations (priority 1–31) · 54 error codes · 7 roles · 2 OCC concurrency rules. Profile: `quota_allocation` / `temporal_windowing`, flat topology, cyclic state machines, `segregation_of_duties` role model, immediate consistency.

§1.8 rules → instances (22): `dual_variant_calc` 2 · `combinatorial_formula` 3 · `non_linear_state_machine` 2 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 3 · `boundary_precision_check` 3 · `cross_entity_state_dependency` 3 · `resource_temporal_overlap` 2 · `compensating_invariant` 2

§1.9 sections → instances (83 total = 61 recipes + 22 `excluded_because` stubs): entities 10 · state_machines 11 · calculations 13 (6 recipes + 7 stubs) · validations 15 · endpoints 5 (2 + 3) · errors 14 (7 + 7) · rbac 5 · cross_cutting_complexity_layers 9 (4 + 5) · consistency_model 1

Every stub cites a `difficulty_instance` that exists by name in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (verified programmatically), no stub carries a `test_recipe`, and all 83 corner names are unique across the union of both design files. All 54 error codes in the catalog are triggerable somewhere in the union (checked code by code). Every monetary/score literal was computed in Python from the §1.3 formulas before being written (tier boundaries 5000/15000, recovery re-lock 3420→3600, replay decay 4000/2400/1200/0, host score 65, marker offset range [0, 4200], readiness index 0 on channel failure).

Two notes: the "Generate task harder than expert level!" directive line was deliberately excluded from the `scenario:` key (it would otherwise leak into PRD.md via the scaffold), and the hard isolation constraint was respected — no sibling `task_*/` directory was listed, read, or grepped at any point.

## Step 3: Copy shared files — 2026-09-04T21:51:32.000Z

Copied ./INSTRUCTION.md to tasks/task_2779_live_video_commerce_operations/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T22:07:47.000Z

All checks complete. Final state of workspace/PRD.md:

Tail verification
- Final line count: 515
- Last section heading: `## 5. Error Code Catalogue` (line 458)
- Tail is complete: the document ends on a fully-rendered table row, `| `ERR_INSUFFICIENT_INVENTORY` | 422 Unprocessable Entity |` — not mid-sentence, not mid-table, not mid-endpoint. All 54 rows present; no trailing partial content.

Section list (28 headings)
`# Live Video Commerce Operations API — PRD` · `## 1. Introduction` · `## 2. Global Specifications & System-Wide Principles` (2.1 RBAC, 2.2 API Response Structure [+ 2 `####` sub-blocks], 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 The Logical Broadcast Clock, 2.6 Flat Topology & Reverse Lookups, 2.7 Order of Rejection: The Validation Ladder, 2.8 Optimistic Concurrency, 2.9 Money/Units/Fractions/Rounding, 2.10 Two Ledgers, 2.11 Cascade Discipline & Compound Readiness, 2.12 Segregation of Duties) · `## 3. Business Logic & Workflows` (3.1 Show Calendar/Host Booking/Disclosure, 3.2 Catalogue/Claim Substantiation/Lineup, 3.3 Simulcast Production & Readiness Index, 3.4 Readiness Gate & Going Live, 3.5 Flash Offers, 3.6 In-Stream Carts, 3.7 Abandonment/Recovery/Checkout/Order Ledger, 3.8 Interactive Layer, 3.9 Ending the Broadcast/Replay/Settlement) · `## 4. Endpoint Definitions` · `## 5. Error Code Catalogue`

Coverage counts
- Endpoint table rows: 62 / 62 scaffold endpoints
- Error table rows: 54 / 54 scaffold errors
- Validations: 31 / 31 rendered as the §2.7 ordered ladder (priority 1–31, each with error ID, HTTP status, applies_to scope)
- Entities/fields 13 / 122, state machines 8 (45 transitions), calculations 8, concurrency rules 2, roles 7

Hard Contract reports
Contract 1 — Field-Name Coverage: PASS
    entities[].fields:              122 required, 122 present, 0 missing
    endpoints[].request_body:        62 required,  62 present, 0 missing
    endpoints[].query_params:        16 required,  16 present, 0 missing
    endpoints[].output (computed):   25 required,  25 present, 0 missing
    path_params:                     13 required,  13 present, 0 missing
    errors[].id:                     54 required,  54 present, 0 missing
    state values (enums):            61 required,  61 present, 0 missing
    roles:                            7 required,   7 present, 0 missing
Strict exact-backtick-token re-check now also returns 0 missing for entity fields and 0 for enum values (the 6 earlier soft flags — `effectiveness_score_live`, `effectiveness_score_attributed`, `ACKNOWLEDGED`, `ALLOCATED`, `APPROVED`, `BLOCKED` — were hardened into standalone backticked mentions in §3.1/§3.7/§3.8/§3.9).

Contract 2 — Rule Coverage: PASS
All 31 validations, 45 state transitions (with preconditions and side effects), 8 calculations, 2 OCC rules and 7 role grants are expressed in prose. Every calculation constant is present by value rather than by symbol name (e.g. TIER1_FLOOR_CENTS/TIER1_PCT as "50 dollars"/"5 percent", TAX_RATE as "8.75 percent", SHIPPING_FLAT_CENTS as "a flat 5.99 dollars", FREE_SHIP_THRESHOLD_CENTS as "at least 75 dollars", with §2.9 fixing all monetary fields as integer cents) — 0 constants unaccounted for. No pseudocode, no operator syntax, no fuzzy quantifiers.

Contract 3 — §3 Path Purity: PASS
    §3 backtick tokens scanned: 1063   unique: 325
    tokens starting with "/":        0
    bare HTTP methods:               0
    method+path pairs:               0
    tokens containing "/" anywhere:  0
All endpoint-path-bearing material (validation `applies_to` scopes, OCC `write_endpoint` names) lives in §2, where paths are permitted.

Byte-fidelity check: §2.2 is byte-identical to `section-2.2-response-structure.md`.

Constraints honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced; no sibling task directory was read; PRD.md was built via 8 sequential `cat >>` heredoc appends (82 -> 204 -> 240 -> 275 -> 310 -> 338 -> 388 -> 515 lines) so no write hit the 64k output cap.

Orchestrator verification: independently confirmed 515 lines, tail ends on the final complete error-table row inside `## 5. Error Code Catalogue`, and grep for the difficulty directive text in PRD.md returns nothing (no leak).

## Step 5: Generate unit tests — 2026-09-04T23:08:29.000Z

Stage 1 and Stage 2 are complete. Everything lives at the task root; nothing was created under `workspace/`, and `workspace/implementation/` was never touched.

Files written

`test_helpers/` (2,358 lines)
`__init__.py` 44 · `api_client.py` 248 (62 endpoint methods) · `api_errors.py` 139 (54 error ids + status map registration) · `assertions.py` 217 · `constants.py` 113 · `factories.py` 251 · `fixtures.py` 850 (5-tier fixture library) · `test_users.py` 90 · `types.py` 397

`test_suite/` (6,554 lines, 27 files)
- Queue A (mine): `conftest.py` 61 · `test_01_dual_variant_analytics` 313/10 · `test_02_simulcast_readiness_index` 130/6 · `test_03_cart_bundle_pricing` 186/6 · `test_04_flash_offer_restock_cycle` 167/6 · `test_05_order_payment_and_fulfilment` 156/6 · `test_06_show_end_cascade` 153/7 · `test_07_moderation_strike_cascade` 159/6 · `test_08_validation_precedence` 254/9 · `test_09_boundary_precision` 323/9 · `test_10_cross_entity_state` 270/9 · `test_11_temporal_overlap` 309/8 · `test_12_compensating_invariants` 307/12 -> 94 tests
- Queue B (two partitioned subagents): `test_20`–`test_26` (1,856 lines, 38 tests) and `test_30`–`test_36` (1,920 lines, 39 tests) -> 77 tests

Total: 171 test functions, 183 collected cases (`pytest --collect-only -q` -> 183 collected, 0 errors; `test_34` carries one 13-way parametrize over the path identifiers).

Coverage
- Queue A: 22 of 22 §1.8 instances translated, 0 skipped. Scripted diff of yaml `name:` values against emitted `Design: Difficulty/...` tags: 0 missing, 0 unknown.
- Queue B: 61 of 61 live §1.9 recipes translated, 0 skipped. All 22 `excluded_because:` stubs left untranslated; every tag's section label matches the yaml section.

Audits run
- Tag discipline: all 171 tests have exactly one `Design:` line, well-formed, as the final docstring line; no dual tags, no untagged tests.
- PRD citation: 300 quoted fragments across the whole suite verified verbatim against `workspace/PRD.md` (whitespace/backtick/emphasis-normalised). Found and fixed 8 that had drifted — 7 elisions or punctuation edits plus one `restock[s]` bracket — by expanding them to full PRD sentences.
- No forbidden vocabulary ("scaffold", "difficulty design", "corner design") anywhere in `test_suite/` or `test_helpers/`; every queue-A docstring cites the PRD.
- pyflakes clean apart from the intentional re-exports in `test_helpers/__init__.py`.
- Conflict adjudication: where the design indices asserted HTTP 422 for `ERR_HOST_BOOKING_OVERLAP` and `ERR_OFFER_WINDOW_OVERLAP`, PRD §5 (409) wins — the tests assert via `validate_error`, which checks the registered map.

Sub-assertions dropped as non-derivable (instances still covered)
- `Show.margin_final_cents == null` after a FINAL read (§3.1 initialises derived counters to zero, so 0 reads equally faithfully).
- `muted_until` being cleared on auto-unmute; `GET /hosts/{id}/performance` raw-quantity fields (PRD pins the score formula, not the response shape); interaction `created_at`; CHAT `tallies`/`defer_count`; `readiness_checked_at` on the lineup-empty refusal; `held_item_count` on expired/recovered carts; exact page positions where five interactions share one logical `created_at` (asserted as a disjoint union instead).

One fixture fix worth noting for Step 7
`fixtures.add_offer_target()` copied `DEFAULT_SLOT`, which already carries `slot_sequence: 1`, so its `setdefault` never fired and a second call would have collided on the per-show uniqueness rule. Fixed to drop `slot_sequence` from the copied defaults before defaulting it to `len(scenario.slots) + 1`.

ORCHESTRATOR NOTE — sequencing deviation and its mitigation. The skill mandates launching Steps 5 and 6 concurrently in a single assistant message, which gives the implementation generator *physical* isolation from `test_suite/` (the directory does not exist when it starts). I issued Step 5 alone, so that physical isolation is unavailable for Step 6: `test_helpers/` and `test_suite/` already exist on disk when the implementation generator starts. Decision (no user available to consult): proceed with Step 6 now rather than discard and regenerate 8,900 lines of audited test code, and substitute an explicit, emphatic *contractual* prohibition in the Step 6 prompt — the impl generator is forbidden to list, read, grep, or reference `test_helpers/`, `test_suite/`, or either `SCAFFOLD_*_DESIGN.yaml`, and is told these are test-answer artifacts. Verification available to Step 7 and Step 9: any implementation behaviour that traces to a test assertion but to no verbatim PRD sentence is a leak signal and must be treated as an implementation-hacking violation. Test dirs verified present at the task root, absent under `workspace/`.

## Step 6: Generate implementation — 2026-09-04T23:33:14.000Z

Implementation complete and smoke-verified.

Output: `workspace/implementation/` (2872 lines total, in-memory dicts only, zero seeding)

| file | lines | contents |
|---|---|---|
| `store.py` | 112 | `Store` dicts (13 tables), logical broadcast clock (default `2026-08-01T00:00:00Z`), `new_record`/`touch`/`by_created`, `req_`-prefixed request ids, 3-fractional-digit ISO formatter |
| `errors.py` | 83 | all 54 error ids -> HTTP status, `ApiError` |
| `envelope.py` | 42 | `meta`/`response_type`/`data` envelope + pagination meta (`limit`/`offset`/`total_count`/`has_more`) |
| `guards.py` | 239 | ladder rungs 1–6: header auth, role gate, 13 FK resolvers, typed body coercers, ISO-8601 parser (second or `.mmm` + `Z` only), pagination bounds |
| `calc.py` | 560 | all 8 calculations + cascades (show-end, block/mute, primary-booking-cancel READY->DRAFT), Decimal/ROUND_HALF_UP throughout |
| `serializers.py` | 253 | 13 serializers with read-time derived fields (both ledgers, cart pre-discount subtotal, show GMV/abandonment/replay revenue) |
| `routes_a.py` | 199 | clock, hosts, products, viewers |
| `routes_shows.py` | 285 | shows lifecycle + analytics, stream channels + health reports |
| `routes_bookings.py` | 216 | host bookings, disclosure records |
| `routes_merch.py` | 232 | lineup slots, replay markers/conversions, flash offers |
| `routes_commerce.py` | 340 | carts, cart items, abandon/recover, checkout, orders, capture, cancel |
| `routes_interactions.py` | 249 | interactions, moderate, route, host-action, votes |
| `app.py` | 53 | blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers, `0.0.0.0:$PORT` |
| `start.sh` | 8 | `set -euo pipefail`, guarded `pip install`, `exec python3 app.py` foreground |

Coverage
- 62/62 endpoints — verified programmatically: `url_map` yields exactly 62 non-static rules and 62 GET/POST method bindings.
- 31 validations in the PRD §2.7 ladder order; 54 error codes mapped to their catalog HTTP status.
- 8 state machines / 45 transitions, including the compound revertible `Show.READY`, parallel `Order` payment×fulfillment, and all four cyclic machines (offer `ACTIVE<->EXHAUSTED`, cart `OPEN<->ABANDONED`, interaction `QUEUED->ROUTED->DEFERRED->QUEUED`, channel `PROVISIONED<->FAILED`).
- 8 calculations, both variant pairs (`PROVISIONAL`/`FINAL`, `LIVE_WINDOW`/`ATTRIBUTED_72H`), all money via `Decimal` + `ROUND_HALF_UP`.
- Both OCC rules (`expected_lineup_slot_version` -> 412 `ERR_STALE_LINEUP_SLOT_VERSION`; `expected_cart_version` -> 412 `ERR_STALE_CART_VERSION`) and the 7-role RBAC matrix.

Smoke test
Ran a 45-step end-to-end scenario on `PORT=18779`, all steps returned the expected status with no server-side traceback (`grep -c traceback` = 0). Notable confirmations: pricing chain offer unit 8000 -> tier-1 10% bundle -> effective 7200, gross 14400, tax 1260, free shipping (>=7500) -> order total 15660; physical ledger moved 50->48 available on hold; allotment held/sold tracked; stale-version checkout correctly 412 then 201; duplicate vote 409; deferral produced `QUEUED` with `defer_count=1` and a double version bump (3->5); segregation of duties refused sign-off by the substantiating user (403) then accepted a different officer (200); `FINAL` margin stamped after sign-off; replay marker publish -> replay conversion -> host `ATTRIBUTED_72H` score computed.

Server killed by recorded PID only (`kill 630327` + `pkill -P 630327`); port 18779 confirmed free. No broad pattern was used. `__pycache__` removed.

One smoke-script bug worth noting (not an implementation defect)
The earlier `ERR_GO_LIVE_WINDOW_CLOSED` was the script leaving the logical clock at `09:00Z` for a `10:00Z` show whose window opens `09:30Z` — the refusal was correct. Advancing the clock to `09:45Z` made go-live and everything downstream pass.

PRD ambiguities resolved
- Negative `marker_offset_sec` -> `ERR_MARKER_OFFSET_OUT_OF_RANGE` (§3.9 states the range as "at least 0", so out-of-range beats shape).
- `replay-marker/publish` requires status `DRAFT`, else `ERR_REPLAY_MARKER_NOT_PUBLISHED` — deterministic for both `NONE` and already-`PUBLISHED`.
- Computed reads that stamp a value bump `version` (`GET /hosts/{id}/performance`, `GET /shows/{id}/analytics?variant=PROVISIONAL`), per §4's note that such a read is a modification returning 200; purely derived recomputation does not.
- Health reports are allowed on `FAILED` channels (PRD forbids only `DRAFT`/`ENDED`), but a `FAILED` channel is excluded from the reported set so it cannot drag the show index.
- First provisioning `DRAFT->PROVISIONED` does not recompute the show index; only the `FAILED->PROVISIONED` recovery branch does (the specific §3.3 sentence over the general one).
- Block cascade bumps `Viewer.version` once covering strike+mute; only the deferral loop is documented as a double increment.
- Show-state gates on child creates: channels `DRAFT`; bookings and lineup slots `{DRAFT, READY}`; disclosure records `{DRAFT, READY, LIVE}`; carts ungated.

## Step 7: Run tests and iterate — 2026-09-04T23:57:47.000Z

Loop complete — the suite is green.

Iterations run: 2

- Iteration 1 — 8-round parallel `setsid` sweep: all 8 rounds byte-identical at `total 183, passed 159, failed 24, errors 0, skipped 0` (~339 s/round). Fully deterministic; no `Terminated`/RemoteDisconnected pattern, so no load-induced noise to discount. All 24 failures triaged to the test layer.
- Iteration 2 — 8-round parallel sweep after the fixes: all 8 rounds `total 183, passed 183, failed 0, errors 0, skipped 0` (326.5 s/round). Union of non-passed statuses across all 8 `results.$i.json`: empty.

Tests deleted: none. Every failing test's rule is verbatim in PRD.md and uniquely derivable from it — no COMPUTED-FIELD SILENCE, DEFAULT-VALUE SILENCE, BRANCH-ASYMMETRIC SIDE EFFECT, ERROR PRECEDENCE SILENCE or ENUM-MEMBERSHIP-ONLY case arose. All 24 were test-expression / precondition bugs (STEP 2), not coverage or derivability failures.

Fixes to `test_helpers/`: none. `add_offer_target` was left in place — it is legitimate for a DRAFT show and test_30 was its only caller.

Fixes to `implementation/`: none. Zero implementation defects were found; the implementation was correct on all 24 failures, including the one that looked like a wrongful 409.

Fixes to `test_suite/` (3 clusters, 25 code sites across 7 files):

1. Double `data` extraction — 18 sites, 18 failures. Tests wrote `validate_success(...)["data"]`, but the runner's `validate_success` in `prd-bench-local-runner/src/prd_bench_local_runner/testing/validators.py` already `return body["data"]`, so the second index raised `KeyError: 'data'`. Stripped the trailing `["data"]` in `test_01_dual_variant_analytics.py` (4), `test_06_show_end_cascade.py` (2), `test_07_moderation_strike_cascade.py` (1), `test_09_boundary_precision.py` (2), `test_10_cross_entity_state.py` (4), `test_11_temporal_overlap.py` (5).

2. Missing 201 expectation — 6 sites, 5 failures. Creation endpoints were wrapped in `validate_success(...)` with its default `expected_status=200`, yielding `Expected 200, got 201`. Added the explicit `201` argument per PRD §4 ("Operations that bring a new stand-alone resource into existence return `201 Created`"): `test_09` `create_host_booking`; `test_10` `add_cart_item`; `test_11` `create_host_booking` x2 and `create_flash_offer` x2. This tightens the assertions toward the PRD rather than weakening them.

3. PRD-violating fixture precondition — 1 failure. `test_a_fourth_distinct_held_line_is_refused_by_the_cart_line_ceiling` in `test_suite/test_30_cart_hold_admission_and_ledgers.py` built its extra lineup slots via `add_offer_target()` on an already-LIVE show, so setup died with `HTTP 409: ERR_INVALID_SHOW_STATE`. The implementation was right — PRD 3.1: "Attempting to mutate a show's lineup or bookings once it has left `DRAFT` and `READY` behind is refused with `ERR_INVALID_SHOW_STATE`." Rewrote the setup to assemble all four products/slots/offers through `build_scenario(...)` while the show is DRAFT, then `take_live=True, activate=True`. Downstream assertions were left untouched and remain arithmetically correct under the pinned four-step pricing order (line 1: subtotal 3500 -> tier 0.00 -> 3500; line 2: 4500 -> 0.00 -> 1000; line 3: 5500 -> tier 0.05 -> 950; fourth add -> `ERR_CART_ITEM_LIMIT`).

No assertion was relaxed, no `skip`/`xfail` added, no error-id check downgraded, `worklog.md` was not read or touched, and no scaffold file was opened. Per-round artifacts are at `workspace/implementation/results.1..8.json`.

Orchestrator verification: independently re-read all 8 `results.$i.json` — every round reports `total 183, passed 183, failed 0, errors 0, skipped 0`. Artifacts present and timestamped from the final sweep (not stale).

## Step 8: Finalize PRD — 2026-09-05T00:01:24.000Z

`PRD_FINALIZED.md` is written. Result: one single-line revision; the other two Step 7 clusters were genuine test-harness bugs with no PRD silence or mismatch behind them.

Line counts
- PRD.md: 515 lines; PRD_FINALIZED.md: 515 lines — 0% line-count delta, 1 of 515 lines revised (0.19%).

Change
- §3.1 (show creation paragraph, PRD line 209) — revise — dropped the false universal "`DRAFT` — the only status in which its lineup, bookings and simulcast destinations may be assembled" and pinned the actual admissible statuses: lineup slots and bookings may still be added while the show is `READY`; simulcast destinations only in `DRAFT` — `implementation/routes_merch.py:42` (slot create: `DRAFT`/`READY`), `implementation/routes_bookings.py:38` (booking create: `DRAFT`/`READY`), `implementation/routes_shows.py:203` (channel create: `DRAFT` only).

Why it traces to Step 7: cluster 3's only real failure was the `test_30` fixture that called `add_offer_target()` (product -> slot -> offer) on an already-`LIVE` show and got a correct `409 ERR_INVALID_SHOW_STATE`. The subject of that fix is which show statuses admit lineup assembly, and PRD.md states that gate twice with conflicting scope in the same paragraph: "`DRAFT` — the only status…" versus "once it has left `DRAFT` and `READY` behind is refused". The implementation admits `DRAFT` and `READY`, so a fresh implementer taking the first clause literally would produce a divergent codebase (409 where the impl returns 201). The 2nd clause is left verbatim.

Pre-edit search log (edit 1)
- (a) Subject: the `Show.status` gate governing assembly of lineup slots, host bookings and simulcast destinations.
- (b) Impl paths enumerated — `grep -rn 'show\["status"\]' implementation/*.py` and read in full: `routes_merch.py:42` create_slot (`DRAFT`,`READY`); `routes_bookings.py:38` create_booking, `:99` confirm_booking, `:121` cancel_booking (all `DRAFT`,`READY`); `routes_shows.py:203` create_channel (`DRAFT` only), `:247` provision_channel (`DRAFT`,`READY`), `:265` health-reports (no show gate); `routes_bookings.py:155/208` disclosure create + acknowledge (`DRAFT`,`READY`,`LIVE`); `routes_merch.py:91/110/132` replay-marker set/publish/conversion (`ENDED`,`SETTLED`, i.e. slot mutation after air); `routes_merch.py:220` offer activate (`LIVE`); `routes_shows.py:64/102/126/138` lifecycle gates. Also confirmed there is no slot/booking update or delete endpoint, so "assembly" = creation only.
- (c) Wording adjustments made: (i) used "added"/"attached" rather than "mutated" so the sentence does not contradict the replay-marker operations, which mutate a lineup slot while the show is `ENDED`/`SETTLED`; (ii) split destinations out explicitly as `DRAFT`-only to stay consistent with `routes_shows.py:203` and with §3.3's existing "Destinations may only be attached while the show is in `DRAFT`"; (iii) deliberately said nothing about booking confirm/cancel or provisioning, whose `DRAFT`/`READY` gates are already stated verbatim later in §3.1 and §3.3.

Items examined and deliberately NOT patched
- Cluster 1 (18 sites, double `data` unwrap): pure harness bug — the runner's `validate_success` already returns `body["data"]`. Envelope shape in `implementation/envelope.py` matches §2.2 verbatim; no PRD choice is left open. No edit.
- Cluster 2 (6 sites, missing `201` expectation): `POST /host-bookings` (`routes_bookings.py:68`), `POST /flash-offers` (`routes_merch.py:191`) and `POST /carts/{cart_id}/items` (`routes_commerce.py:119`) all return 201 in the impl, which §4 already determines ("Operations that bring a new stand-alone resource into existence return `201 Created`"); `CartItem` is one of the thirteen resources of §2.4 and is addressed directly per §2.6, so its 201 is derivable without a new sentence. Verified every other creating POST in the impl returns 201 and every transition/computed read returns 200 (`routes_a.py:54/126/193`, `routes_interactions.py:98`, `routes_shows.py:51/218`, `routes_merch.py:61/140`, `routes_commerce.py:42/242`), matching §4 including the two flagged 201 exceptions (checkout, replay conversion). No edit.
- Cluster 3 downstream arithmetic: the rewritten `test_30` assertions (3500 -> 1000 -> 950, cart tier 0.05 at a 5500-cent subtotal, `ERR_CART_ITEM_LIMIT` on the fourth line) are all uniquely fixed by the pinned four-step order in §3.6 and rung 29 of §2.7. No edit.

Orchestrator note: Step 8 was NOT skipped — the skip condition requires Step 7 to have exited on its first sweep with zero deletions and zero fixes in all three layers, and Step 7 ran 2 iterations with 25 `test_suite/` code-site fixes. Verified PRD_FINALIZED.md exists, is 515 lines, and differs from PRD.md by exactly the one §3.1 line reported above (diff confirmed by the orchestrator).

## Step 9: Complete PRD — 2026-09-05T00:28:13.000Z

Run as THREE SEQUENTIAL passes partitioned by implementation module, all editing one shared `workspace/PRD_COMPLETED.md`; pass 1 performed the `cp` from PRD_FINALIZED.md, passes 2 and 3 edited in place with the Edit tool only (never re-copying, which would have destroyed prior passes' work). Partition: pass 1 = app/envelope/errors/store/guards/routes_a; pass 2 = calc/serializers/routes_shows/routes_bookings; pass 3 = routes_merch/routes_commerce/routes_interactions.

TOTALS: PRD_FINALIZED.md 515 lines / 100,119 chars -> PRD_COMPLETED.md 524 lines / 127,706 chars (+9 lines, +27,587 chars). 60 substantive edits: 50 ambiguity-pins, 10 mismatch-revisions. `cmp` confirms the files are NOT byte-identical. Heading count and §4/§5 table row counts unchanged — no sections or table rows added or removed.

### Pass 1 (app.py, envelope.py, errors.py, store.py, guards.py, routes_a.py)
516 lines / 107,023 chars (+1 line, +6,904 chars). 16 ambiguity-pins, 3 mismatch-revisions. Cross-check that found no defect: the 54 error ids in `errors.py:3-70` and their statuses match §5 exactly — same set, same statuses, same table order.
- §2.1 — revise — ambiguity — a header present but carrying an empty string counts as absent; the seven role names are matched exactly and case-sensitively — `guards.py:41`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly twenty chars from `A`-`Z`/`0`-`9` (24 total) — `store.py:101-103`
- §2.2 — revise — mismatch — `api_request_timestamp` is the one value taken from the real wall clock, not the logical clock — `store.py:73-74`, `envelope.py:11`
- §2.2 — revise — mismatch — error envelope scope widened from "4xx status codes" to include the 5xx case — `app.py:42-44`
- §2.2 — insert — ambiguity — `message` wording is not contractual; the server synthesises one from the identifier when an endpoint supplies none — `errors.py:81-83`
- §2.2 — insert — ambiguity — unknown path -> `ERR_INVALID_REQUEST` at 404, unsupported method -> same id at 405, unexpected fault -> same id at 500 — `app.py:36-44`
- §2.3 — insert — ambiguity — non-base-ten `limit`/`offset` -> `ERR_INVALID_REQUEST`; an `offset` at/beyond `total_count` is in bounds and returns empty `data` — `guards.py:221-239`
- §2.3 — insert — ambiguity — `created_at` ties (the norm, since the clock is frozen) break by server minting order, earliest first — `store.py:96-98`
- §2.4 — revise — ambiguity — `id` is a version-4 UUID in canonical lower-case 36-char hyphenated form — `store.py:56-58`
- §2.5 — revise — mismatch — "Nothing in this system reads the host machine's wall clock" narrowed to business logic, with `api_request_timestamp` named as the sole exception — `store.py:73-74`
- §2.5 — insert — ambiguity — clock default re-established on every process start; store is in-memory and entirely empty at boot, nothing seeded — `app.py:3-4`, `store.py:16-21`
- §2.5 — revise — ambiguity — `current_utc` required; response `data` is exactly `current_utc` + `previous_utc` in three-digit form at 200; the clock may be moved backwards — `routes_a.py:21-30`
- §2.5 — revise — ambiguity — the two accepted timestamp shapes spelled out literally; `+00:00`, missing/lower-case `z`, other fractional widths, space-for-`T`, impossible dates and non-strings all rejected — `guards.py:31,188-206`
- §2.7 rung 5 — insert — ambiguity — a body FK that is absent/null/empty/non-string is `ERR_INVALID_REQUEST` at rung 5, not a 404 — `guards.py:118-124`
- §2.7 rung 6 — insert — ambiguity — no type coercion (`"5"` not an integer, booleans rejected); optional-`null` = absent + default; required-`null` = missing; required strings not satisfied by `""`; absent/unparseable body = `{}`, non-object JSON body = `ERR_INVALID_REQUEST` — `guards.py:49-55,128-185`
- §3.1 — revise — ambiguity — `certified_until` is written verbatim and need not be in the future; a past instant reads back `EXPIRED` — `routes_a.py:68-70`
- §3.2 — insert — ambiguity — omitted `on_hand_delta` = 0, omitted `unit_cost_cents` leaves cost untouched, supplied value must be >= 0 and is not re-checked against `base_price_cents` — `routes_a.py:141-149`
- §3.2 — revise — ambiguity — an `UNSUBSTANTIATED` decision leaves `substantiated_by_user_id`/`substantiated_at` as they stand (only `REJECTED` clears); `evidence_ref` validated but neither stored nor echoed — `routes_a.py:162-169`
- §3.8 — insert — ambiguity — viewer `email` gets an exact case-sensitive uniqueness test and no format check — `routes_a.py:180-183`
- §3.9 — revise — ambiguity — `variant`/`show_id` are query parameters; `show_id` is not FK-resolved, so an unknown one yields an empty scope and zeroed quantities rather than `ERR_SHOW_NOT_FOUND` — `routes_a.py:78-84`, `calc.py:409-410`
- §3.9 — insert — ambiguity — a `variant` outside the two names is `ERR_INVALID_REQUEST`; the read mutates (host `version`++/`updated_at`); response `data` is `host_id`, `variant` + the ten named computed fields — `routes_a.py:81-92`

### Pass 2 (calc.py, serializers.py, routes_shows.py, routes_bookings.py)
516 -> 516 lines, 107,023 -> 113,769 chars (+6,746). 13 ambiguity-pins, 4 mismatch-revisions.
- §2.10 — insert — ambiguity — both ledgers are derived from current cart-line states at read time; product and offer `version`/`updated_at` untouched unless the row itself mutates — `calc.py:165-197`, `serializers.py:33,141`
- §2.11 — insert — ambiguity — enumerated which figures are read-time derived (`gross_merchandise_cents`, `abandoned_cart_count`, `abandonment_rate_bp`, `pending_question_count`, `replay_attributed_revenue_cents`, `pre_discount_subtotal_cents`, `held_item_count`) versus stored (`simulcast_readiness_index`, `margin_provisional_cents`, `margin_final_cents`) — `serializers.py:64-86,173-190`, `calc.py:290-325`
- §3.1 — insert — ambiguity — show creation field shape (three stored counters + five derived at 0; five timestamps/ids null) and that neither planned instant is compared to the logical clock — `routes_shows.py:34-51`
- §3.1 — insert — ambiguity — new booking carries `confirmed_at` and `cancel_reason` null — `routes_bookings.py:64-65`
- §3.1 — insert — ambiguity — the turnaround overlap scan spans the host's bookings on every show and both roles — `routes_bookings.py:42-49`
- §3.1 — insert — ambiguity — disclosure defaults (`acknowledged_at` null, `acknowledged_late` false); the booking's own status is not examined, so a record cut against a `CANCELLED` booking can never be acknowledged and holds the readiness gate shut — `routes_bookings.py:151-166,205`
- §3.3 — insert — ambiguity — `is_primary` is documentary and `target_latency_ms` feeds no formula — `routes_shows.py:196-197`, `serializers.py:94-95`
- §3.3 — insert — ambiguity — `latency_ms` unbounded (0/negative accepted, penalty floors at 0); `dropped_frame_pct` accepts int or float and echoes as float — `guards.py:146,163`, `serializers.py:98`
- §3.3 — insert — ambiguity — a `FAILED` destination accepts reports (stored, count++, version++) but is not recomputed, stays out of the spread, and cannot recover by reporting healthy numbers — `routes_shows.py:265-269`, `calc.py:248-251`
- §3.3 — insert — ambiguity — `PARTNER_APP` is exempt from the penalty only; its latency still enters the max-min spread — `calc.py:252-254,262`
- §3.3 — revise — mismatch — "recomputed on every destination status change" replaced with the actual four trigger points (gate, go-live pre-comparison, `FAILED->PROVISIONED` recovery, health report) and the explicit non-triggers, so an `ENDED` show keeps its last index — `routes_shows.py:91,110,252-254,278`, `calc.py:520-523`
- §3.3 — insert — ambiguity — the sub-40 test covers only the destinations this report recomputed; the spread is computed once before failures are applied — `routes_shows.py:273-277`
- §3.4 — insert — ambiguity — the certification rung passes vacuously with no `CONFIRMED PRIMARY` booking, so the failure surfaces as `ERR_PRIMARY_HOST_MISSING` — `routes_shows.py:77-84`
- §3.4 — insert — ambiguity — the pre-comparison index write persists through an `ERR_SIMULCAST_NOT_READY` refusal (no rollback) while `version`/`updated_at` stay put — `routes_shows.py:110`, `calc.py:278-286`
- §3.7 — revise — mismatch — the end-of-broadcast abandon branch reads the cart's current line states and does not ask which cascade released them — `calc.py:536-547`
- §3.9 — revise — ambiguity+mismatch — `variant` is a query parameter, any other value is `ERR_INVALID_REQUEST`, the `PROVISIONAL` stamp increments the show's `version`/`updated_at` even when unchanged, `FINAL` writes nothing; response `data` is exactly twelve fields — `routes_shows.py:169-186`
- §3.9 — revise — mismatch — "it applies while the show is `LIVE` or `ENDED`" replaced: neither variant is status-gated — `routes_shows.py:165-174`
- §3.9 — insert — ambiguity — `attestation_note` validated as a string when present but neither stored nor echoed — `routes_shows.py:137`

### Pass 3 (routes_merch.py, routes_commerce.py, routes_interactions.py)
516 -> 524 lines, 113,769 -> 127,706 chars (+8 lines, +13,937). 21 ambiguity-pins, 3 mismatch-revisions.
- §2.6 — insert — ambiguity — reverse-lookup collections apply no owner scoping; a filter naming a nonexistent id matches nothing rather than 404 — `routes_commerce.py:51,272`, `routes_interactions.py:107`
- §2.7 rung 27 — revise — mismatch — `ERR_REPLAY_MARKER_NOT_PUBLISHED` guards marker publication + conversion recording, not marker setting; `ERR_MARKER_OFFSET_OUT_OF_RANGE` guards setting alone — `routes_merch.py:97,113,135`
- §2.7 rungs 30-31 — revise — mismatch — dropped "cart recovery" from both; recovery skips ineligible lines silently and can only raise `ERR_NO_RECOVERABLE_ITEMS` — `routes_commerce.py:174,179`
- §3.2 — insert — ambiguity — slot's other four replay fields initialise (offsets/url null, counts 0); duplicate-sequence and envelope checks precede the show-status check — `routes_merch.py:34,42,53`
- §3.5 — insert — ambiguity — offer creation examines no show status and never compares the window to the clock — `routes_merch.py:144`
- §3.5 — insert — ambiguity — the collision scan includes the `SCHEDULED` offer on the very slot being re-priced, so supersession needs a disjoint window — `routes_merch.py:163`
- §3.5 — revise — mismatch — a checkout commitment cannot drive `ACTIVE->EXHAUSTED`; status re-evaluated only in requests moving a line into/out of `HELD`, never on a read — `calc.py:200`, `routes_commerce.py:118`
- §3.6 — insert — ambiguity — cart creation resolves `show_id` but gates on no show status and leaves the show's `version` untouched — `routes_commerce.py:25`
- §3.6 — insert — ambiguity — [pass 2's deferred item] the tier is a JSON number rendered shortest-round-trip: `0.1` / `0.05` / `0.0`, not `0.10` — `routes_commerce.py:115,189`, `serializers.py:183`
- §3.6 — insert — ambiguity — `bundle_discount_pct` is the only stored one of the three; rewritten by add and recovery alone, so abandon/checkout leave it non-zero over an empty basket — `routes_commerce.py:115,141,220`
- §3.7 — insert — ambiguity — recovery skips ineligible lines silently; eligibility re-evaluated per line against live ledgers; the cart's final tier is the last line's — `routes_commerce.py:177,185,189`
- §3.7 — insert — ambiguity — the checkout sideways ledger move changes no offer status and bumps no offer `version` — `routes_commerce.py:213`
- §3.7 — insert — ambiguity — stamping `margin_provisional_cents` at capture is not a write to the show; missing primary booking => commission 0, not a refusal — `routes_commerce.py:294,301`, `calc.py:391`
- §3.7 — insert — ambiguity — cancellation gates on no show status (`SETTLED` included); the cart stays `CHECKED_OUT` with `version` untouched — `routes_commerce.py:305`
- §3.7 — insert — ambiguity — the refund re-stamp doesn't bump the show; the void branch doesn't re-stamp `margin_provisional_cents` at all, so it can sit stale — `routes_commerce.py:330,338`
- §3.8 — insert — ambiguity — kind/role pairing is a rung-2 check ahead of FK resolution and shape (`ERR_ROLE_NOT_PERMITTED` outranks `ERR_SHOW_NOT_FOUND`), but only for a valid kind name; plus the full 16-field null/0 shape per kind — `routes_interactions.py:45,70`
- §3.8 — insert — ambiguity — auto-unmute is a real write bumping the viewer's `version` while retaining `muted_until`; neither viewer nor host id is FK-resolved; polls need no booking — `routes_interactions.py:25,89`
- §3.8 — insert — ambiguity — `blocked_reason` defaults null and is discarded on `APPROVE` — `routes_interactions.py:127,141`
- §3.8 — insert — ambiguity — the withdrawal sweep is global across every show, in `created_at` order; the mute lives on the viewer — `routes_interactions.py:153`
- §3.8 — insert — ambiguity — the ownership branch is chosen by the target's kind, never the requested action, and runs before the body is read; `answer_body` optional/null, discarded on the other branches — `routes_interactions.py:187,196`
- §3.8 — insert — ambiguity — `DEFERRED` is never observable at rest, the second leg being unconditional — `routes_interactions.py:213`
- §3.8 — insert — ambiguity — `option_index`'s range test runs after show-LIVE, mute, poll-open and duplicate — `routes_interactions.py:233,242`
- §3.9 — insert — ambiguity — marker setting is freely repeatable and drives `PUBLISHED` back to `DRAFT`; publishing from `NONE` or `PUBLISHED` both give `ERR_REPLAY_MARKER_NOT_PUBLISHED` — `routes_merch.py:98,112`
- §3.9 — insert — ambiguity — `occurred_at` (rung 6) is checked before the marker status; `viewer_id` is validate-only; `net_revenue_cents` has no declared range — `routes_merch.py:124,125,128,134`

Orchestrator verification: PRD_COMPLETED.md exists at 524 lines, `cmp` against PRD_FINALIZED.md confirms it is NOT byte-identical (so the scan genuinely ran), tail ends on the final complete row of the §5 error table (not truncated), one worklog.md at the task root with no strays under workspace/, and `find` confirms NO file under test_suite/, test_helpers/ or workspace/implementation/ was modified after the final green sweep at 23:55 — the 8x183-passing result still describes the artifacts on disk.

PIPELINE COMPLETE.
